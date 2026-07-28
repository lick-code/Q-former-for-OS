# coding=utf-8
"""Unit and minimal replay smoke tests for the strict CAPD NoVPN ablation."""

import copy
import csv
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

import torch
from torch.utils.data import DataLoader


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from policy_learning.cache_model import embed
from policy_learning.cache_model import model
from policy_learning.cache_model import qmap_loss
from qmap import finals_config
from qmap import no_vpn_ablation
from qmap import qmap_eval
from qmap import qmap_train
from scripts import summarize_no_vpn_ablation


def build_modules(use_page_id_embedding=None):
  kwargs = {}
  if use_page_id_embedding is not None:
    kwargs["use_page_id_embedding"] = use_page_id_embedding
  page = embed.DynamicVocabEmbedder(8, 128)
  pc = embed.DynamicVocabEmbedder(8, 128)
  page.fit(range(1, 41)).freeze()
  pc.fit(range(101, 121)).freeze()
  features = embed.QMAPAccessFeatureEmbedder(
      page, pc, embed.RWFlagEmbedder(2), **kwargs)
  extractor = model.QMAPMacroscopicPatternExtractor(
      hidden_dim=18, num_layers=1, num_heads=2, dropout=0.0,
      use_qformer=False, pooling_strategy="none",
      position_encoding="sinusoidal", max_sequence_length=4)
  scorer = model.QMAPCandidateScorer(
      hidden_dim=18, page_state_dim=4, page_embed_dim=8,
      page_vocab_size=128, num_heads=2, dropout=0.0,
      scoring_input="context", shared_page_embedding=True,
      context_mode="cross_attention", **kwargs)
  return features, extractor, scorer


def forward_scores(modules, history_pages, candidate_pages):
  features, extractor, scorer = modules
  pc = torch.tensor([[101, 102, 103, 104]], dtype=torch.long)
  rw = torch.tensor([[0, 1, 0, 1]], dtype=torch.long)
  history_mask = torch.ones(1, 4)
  state = torch.tensor([[
      [0.1, 0.0, 0.25, 1.0],
      [0.2, 1.0, 0.50, 0.5],
      [0.3, 0.0, 0.75, 0.0],
  ]])
  candidate_mask = torch.ones(1, 3)
  access = features(history_pages, pc, rw)
  encoded = extractor(access, history_mask=history_mask)
  return scorer(
      encoded, candidate_pages, state, candidate_mask,
      candidate_page_embeddings=features.embed_pages(candidate_pages),
      history_mask=history_mask)


class NoVpnModelContractTest(unittest.TestCase):

  def setUp(self):
    torch.manual_seed(7)

  def test_default_matches_explicit_true_with_identical_weights(self):
    default_modules = build_modules()
    explicit_modules = build_modules(True)
    for source, target in zip(default_modules, explicit_modules):
      target.load_state_dict(copy.deepcopy(source.state_dict()))
      source.eval()
      target.eval()
    history = torch.tensor([[1, 2, 3, 4]])
    candidates = torch.tensor([[5, 6, 7]])
    default_scores = forward_scores(default_modules, history, candidates)
    explicit_scores = forward_scores(explicit_modules, history, candidates)
    self.assertTrue(torch.equal(default_scores, explicit_scores))

  def test_no_vpn_is_invariant_to_all_page_ids(self):
    modules = build_modules(False)
    for module in modules:
      module.eval()
    first = forward_scores(
        modules, torch.tensor([[1, 2, 3, 4]]),
        torch.tensor([[5, 6, 7]]))
    second = forward_scores(
        modules, torch.tensor([[21, 22, 23, 24]]),
        torch.tensor([[25, 26, 27]]))
    max_abs_diff = torch.max(torch.abs(first - second)).item()
    self.assertLess(max_abs_diff, 1e-6)

  def test_no_vpn_page_embedding_has_no_loss_gradient(self):
    modules = build_modules(False)
    scores = forward_scores(
        modules, torch.tensor([[1, 2, 3, 4]]),
        torch.tensor([[5, 6, 7]]))
    scores.sum().backward()
    page_gradient = modules[0].page_embedder._embedding.weight.grad
    self.assertTrue(
        page_gradient is None or torch.count_nonzero(page_gradient) == 0)
    self.assertIsNotNone(modules[0].pc_embedder._embedding.weight.grad)
    self.assertIsNotNone(modules[0]._rw_embedder._embedding.weight.grad)

  def test_full_mode_keeps_page_embedding_path_active(self):
    modules = build_modules(True)
    page_embedder = modules[0].page_embedder
    with torch.no_grad():
      page_embedder._embedding.weight[1].fill_(0.25)
      page_embedder._embedding.weight[2].fill_(-0.5)
    first = modules[0].embed_pages(torch.tensor([[1]]))
    second = modules[0].embed_pages(torch.tensor([[2]]))
    self.assertFalse(torch.equal(first, second))
    scores = forward_scores(
        modules, torch.tensor([[1, 2, 3, 4]]),
        torch.tensor([[5, 6, 7]]))
    scores.sum().backward()
    gradient = page_embedder._embedding.weight.grad
    self.assertIsNotNone(gradient)
    self.assertGreater(torch.count_nonzero(gradient).item(), 0)

  @unittest.skipUnless(torch.cuda.is_available(), "CUDA is unavailable.")
  def test_cuda_no_vpn_identity_invariance_and_backward(self):
    modules = tuple(module.to("cuda") for module in build_modules(False))
    pc = torch.tensor([[101, 102, 103, 104]], device="cuda")
    rw = torch.tensor([[0, 1, 0, 1]], device="cuda")
    mask = torch.ones(1, 4, device="cuda")
    candidate_mask = torch.ones(1, 3, device="cuda")
    state = torch.tensor([[
        [0.1, 0.0, 0.25, 1.0],
        [0.2, 1.0, 0.50, 0.5],
        [0.3, 0.0, 0.75, 0.0],
    ]], device="cuda")

    def scores(history_ids, candidate_ids):
      history = torch.tensor([history_ids], device="cuda")
      candidates = torch.tensor([candidate_ids], device="cuda")
      encoded = modules[1](
          modules[0](history, pc, rw), history_mask=mask)
      return modules[2](
          encoded, candidates, state, candidate_mask,
          candidate_page_embeddings=modules[0].embed_pages(candidates),
          history_mask=mask)

    first = scores([1, 2, 3, 4], [5, 6, 7])
    second = scores([21, 22, 23, 24], [25, 26, 27])
    self.assertLess(torch.max(torch.abs(first - second)).item(), 1e-6)
    first.sum().backward()
    gradient = modules[0].page_embedder._embedding.weight.grad
    self.assertTrue(gradient is None or torch.count_nonzero(gradient) == 0)


class NoVpnConfigContractTest(unittest.TestCase):

  def test_only_allowlisted_fields_differ(self):
    full = finals_config.load_config(
        os.path.join(
            PROJECT_ROOT, "configs", "finals",
            "capd_direction1_v3_ablation_full.json"))
    no_vpn = finals_config.load_config(
        os.path.join(
            PROJECT_ROOT, "configs", "finals",
            "capd_direction1_v3_no_vpn.json"))
    differences = no_vpn_ablation.assert_config_pair(full, no_vpn)
    self.assertEqual(
        set(no_vpn_ablation.ALLOWED_CONFIG_DIFFS), set(differences))
    reference = finals_config.load_config(
        os.path.join(
            PROJECT_ROOT, "configs", "finals",
            "capd_direction1_v3.json"))
    self.assertEqual(
        set(no_vpn_ablation.ALLOWED_CONFIG_DIFFS),
        set(no_vpn_ablation.assert_variant_matches_reference(
            reference, full)))
    self.assertEqual(
        set(no_vpn_ablation.ALLOWED_CONFIG_DIFFS),
        set(no_vpn_ablation.assert_variant_matches_reference(
            reference, no_vpn)))

  def test_old_config_defaults_to_page_id_enabled(self):
    old = finals_config.load_config(
        os.path.join(
            PROJECT_ROOT, "configs", "finals",
            "capd_direction1_v3.json"))
    self.assertNotIn("use_page_id_embedding", old["model"])
    self.assertTrue(finals_config.use_page_id_embedding(old))


class NoVpnTrainReplaySmokeTest(unittest.TestCase):

  @staticmethod
  def _write_jsonl(path):
    sample = {
        "physical_address": [1, 2, 3, 4],
        "pc": [101, 102, 103, 104],
        "rw": [0, 1, 0, 1],
        "candidate_pages": [1, 2, 3, 4],
        "candidate_state_features": [
            [0.1, 0.0, 0.1, 1.0],
            [0.2, 1.0, 0.2, 0.67],
            [0.3, 0.0, 0.3, 0.33],
            [0.4, 1.0, 0.4, 0.0],
        ],
        "candidate_mask": [1, 1, 1, 1],
        "inactivity": [1.0, 0.8, 0.4, 0.2],
        "coldness": [0.9, 0.7, 0.3, 0.1],
        "write_sensitivity": [0.0, 1.0, 0.0, 1.0],
        "migration_cost": [0.0, 0.0, 0.0, 0.0],
    }
    with open(path, "w", encoding="utf-8") as output:
      output.write(json.dumps(sample) + "\n")

  @staticmethod
  def _write_trace(path):
    with open(path, "w", encoding="utf-8", newline="") as output:
      writer = csv.writer(output)
      writer.writerow(["PC", "Address", "RW"])
      for index in range(24):
        page = (index * 3) % 7 + 1
        writer.writerow([hex(101 + index % 4), hex(page), index % 2])

  def _run_variant(self, directory, use_page_id_embedding):
    jsonl_path = os.path.join(directory, "train.jsonl")
    trace_path = os.path.join(directory, "trace.csv")
    checkpoint_path = os.path.join(
        directory, "checkpoint_{}.pth".format(use_page_id_embedding))
    self._write_jsonl(jsonl_path)
    self._write_trace(trace_path)
    dataset = qmap_train.QMAPAccessSequenceDataset(jsonl_path)
    batch = next(iter(DataLoader(dataset, batch_size=1)))
    modules = build_modules(use_page_id_embedding)
    loss_fn = qmap_loss.QMAPCostAwareRankingLoss()
    loss = qmap_train._forward_loss(
        batch, modules[0], modules[1], modules[2], loss_fn,
        "cross_attention")
    loss.backward()
    optimizer = torch.optim.AdamW(
        list(modules[0].parameters()) +
        list(modules[1].parameters()) +
        list(modules[2].parameters()), lr=1e-4)
    optimizer.step()
    torch.save({
        "epoch": 1,
        "feature_embedder": modules[0].state_dict(),
        "extractor": modules[1].state_dict(),
        "scorer": modules[2].state_dict(),
        "model_args": {
            "hidden_dim": 18,
            "address_embed_dim": 8,
            "pc_embed_dim": 8,
            "rw_embed_dim": 2,
            "address_vocab_size": 128,
            "pc_vocab_size": 128,
            "page_state_dim": 4,
            "page_embed_dim": 8,
            "page_vocab_size": 128,
            "page_dim": None,
            "num_layers": 1,
            "num_heads": 2,
            "dropout": 0.0,
            "ablation": "cross_attention",
            "pooling_strategy": "none",
            "position_encoding": "sinusoidal",
            "scoring_input": "context",
            "shared_page_embedding": True,
            "context_mode": "cross_attention",
            "use_page_id_embedding": use_page_id_embedding,
        },
    }, checkpoint_path)
    args = SimpleNamespace(
        trace_path=trace_path, page_shift=0, policy="qmap",
        dram_capacity=4, history_length=4, candidate_count=4,
        lookahead=8, random_seed=0, device="cpu",
        checkpoint=checkpoint_path, ablation="cross_attention",
        rank_guard=0, rank_score_penalty=0.0, selector_params=None,
        learned_model=None, stage6_profile=False,
        stage6_warmup_decisions=0, bridge_diagnostics=False,
        dram_read_cost=1.0, dram_write_cost=1.0,
        nvm_read_cost=2.0, nvm_write_cost=8.0,
        migration_cost=10.0)
    stats = qmap_eval.replay(args)
    self.assertEqual(24, stats.total_accesses)
    self.assertGreater(stats.decision_count, 0)
    self.assertTrue(os.path.exists(checkpoint_path))

  def test_full_and_no_vpn_train_save_load_replay(self):
    with tempfile.TemporaryDirectory() as directory:
      for use_page_id_embedding in (True, False):
        with self.subTest(use_page_id_embedding=use_page_id_embedding):
          self._run_variant(directory, use_page_id_embedding)


class NoVpnResumeAndSummaryTest(unittest.TestCase):

  def test_resume_restores_model_optimizer_epoch_and_variant(self):
    with tempfile.TemporaryDirectory() as directory:
      source = build_modules(False)
      source_optimizer = torch.optim.AdamW(
          list(source[0].parameters()) +
          list(source[1].parameters()) +
          list(source[2].parameters()), lr=1e-4)
      args = SimpleNamespace(
          seed=42, epochs=3, use_page_id_embedding=False)
      checkpoint = qmap_train.checkpoint_payload(
          source[0], source[1], source[2], source_optimizer, 1, 0.5,
          args, finals_context=None, best_epoch=1,
          best_validation_loss=0.5,
          loss_curve=[{"epoch": 1, "train_loss": 0.6,
                       "valid_loss": 0.5}],
          training_duration_seconds=1.25)
      checkpoint["seed"] = 42
      path = os.path.join(directory, "qmap_last.pth")
      torch.save(checkpoint, path)

      target = build_modules(False)
      target_optimizer = torch.optim.AdamW(
          list(target[0].parameters()) +
          list(target[1].parameters()) +
          list(target[2].parameters()), lr=1e-4)
      state = qmap_train._load_resume_checkpoint(
          path, torch.device("cpu"), target[0], target[1], target[2],
          target_optimizer, args, finals_context=None)
      self.assertEqual(2, state["start_epoch"])
      self.assertEqual(1, state["best_epoch"])
      self.assertEqual(0.5, state["best_loss"])
      self.assertEqual(1, len(state["loss_curve"]))
      self.assertEqual(1.25, state["training_duration_seconds"])

  def test_summary_delta_direction_and_statistics(self):
    rows = []
    for seed, full_cost, no_vpn_cost in (
        (3136859, 100.0, 110.0),
        (42, 120.0, 120.0),
        (2026, 80.0, 72.0),
    ):
      base = {
          "workload": "canneal",
          "seed": seed,
          "best_epoch": 2,
          "validation_metric": {"value": 0.5},
          "training_time_seconds": 1.0,
          "hit_rate": 0.5,
          "nvm_reads": 10,
          "nvm_writes": 2,
          "demotions": 4,
          "avg_decision_time_ms": 0.1,
      }
      full = dict(base, variant="full",
                  weighted_access_cost=full_cost)
      no_vpn = dict(base, variant="no_vpn",
                    weighted_access_cost=no_vpn_cost, hit_rate=0.55)
      row = summarize_no_vpn_ablation.per_seed_row(
          "canneal", seed, {"full": full, "no_vpn": no_vpn})
      rows.append(row)
    self.assertEqual(10.0, rows[0]["weighted_access_cost_absolute_delta"])
    self.assertEqual(
        10.0, rows[0]["weighted_access_cost_relative_delta_percent"])
    self.assertAlmostEqual(
        10.0, rows[0]["hit_rate_relative_delta_percent"])
    summary = summarize_no_vpn_ablation.summarize(rows)
    cost = next(row for row in summary
                if row["metric"] == "weighted_access_cost")
    self.assertEqual(100.0, cost["full"]["mean"])
    self.assertAlmostEqual(100.6666666667, cost["no_vpn"]["mean"])
    self.assertEqual(3, cost["seed_count"])


if __name__ == "__main__":
  unittest.main()
