# coding=utf-8
"""Server-only miniature v3 pipeline and fixed-seed determinism regression."""

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest

try:
  import torch
except ModuleNotFoundError:
  torch = None


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config

if torch is not None:
  from policy_learning.cache_model import embed
  from policy_learning.cache_model import model
  from policy_learning.cache_model import qmap_loss
  from qmap import qmap_train
  from qmap.qmap_generator import read_trace


RUN_E2E = os.environ.get("CAPD_RUN_STAGE1_E2E") == "1"
TRACE_ACCESS_COUNT = 440


def write_trace(path, page_offset, pc_offset):
  """Writes a nontrivial trace with cold streams, hot reuse and writes."""
  accesses = []

  def append(page_number, rw):
    accesses.append((
        pc_offset + len(accesses), page_offset + page_number, int(bool(rw))))

  # Fill D=64 once. A few pages become dirty before the first eviction.
  for page_number in range(64):
    append(page_number, page_number % 17 == 0)

  # Force early victim decisions with cold, one-touch streaming pages.
  for page_number in range(64, 88):
    append(page_number, page_number % 5 == 0)

  # Revisit every original page, while making multiples of eight hotter and
  # varying write counts. Candidate future relevance is therefore nonconstant.
  for round_index in range(4):
    for page_number in range(64):
      append(page_number, (round_index * 64 + page_number) % 13 == 0)
      if page_number % 8 == 0:
        append(page_number, (round_index + page_number) % 3 == 0)

  # Keep replay nontrivial after the label-bearing prefix: mix hot revisits,
  # additional cold misses and writes.
  for index in range(64):
    if index % 9 == 0:
      page_number = 88 + index // 9
    else:
      page_number = (index * 11 + index // 7) % 64
    append(page_number, index % 10 in (0, 1))

  if len(accesses) != TRACE_ACCESS_COUNT:
    raise AssertionError("Synthetic trace construction count changed.")
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["PC", "Address", "RW"])
    for pc, page_id, rw in accesses:
      writer.writerow([hex(pc), hex(page_id << 12), rw])


def run_command(command):
  environment = os.environ.copy()
  environment["PYTHONPATH"] = PROJECT_ROOT
  subprocess.check_call(command, cwd=PROJECT_ROOT, env=environment)


def assert_state_equal(testcase, left, right):
  testcase.assertEqual(set(left), set(right))
  for key in left:
    with testcase.subTest(state_key=key):
      if torch.is_tensor(left[key]):
        testcase.assertTrue(torch.equal(left[key], right[key]))
      else:
        testcase.assertEqual(left[key], right[key])


@unittest.skipUnless(
    RUN_E2E and torch is not None,
    "Set CAPD_RUN_STAGE1_E2E=1 on a torch-enabled validation server.")
class FinalsV3MiniEndToEndTest(unittest.TestCase):

  def _assert_nontrivial_training_signal(self, config_path, train_jsonl):
    """Runs one server-only production-model step on a nonconstant label row."""
    config = finals_config.load_config(config_path, require_resolved=True)
    epsilon_y = float(config["selector"]["epsilon_y"])
    rows = []
    with open(train_jsonl, "r", encoding="utf-8") as input_file:
      for line in input_file:
        if line.strip():
          rows.append(json.loads(line))
    nontrivial_index = None
    for index, row in enumerate(rows):
      relevance = [
          inactivity + coldness - 4.0 * write_sensitivity
          for inactivity, coldness, write_sensitivity, valid in zip(
              row["inactivity"], row["coldness"],
              row["write_sensitivity"], row["candidate_mask"])
          if valid
      ]
      if (len(relevance) >= 2 and
          max(relevance) - min(relevance) > epsilon_y):
        nontrivial_index = index
        break
    self.assertIsNotNone(
        nontrivial_index,
        "Generated train JSONL needs a nonconstant retained-candidate label.")

    contract = finals_config.contract_from_config(config)
    dataset = qmap_train.QMAPAccessSequenceDataset(
        train_jsonl,
        expected_shape={
            "H": contract["H"], "K": contract["K"],
            "page_state_dim": contract["page_state_dim"],
        },
        expected_identity={
            "schema_version": config["schema_version"],
            "contract_id": finals_config.CONTRACT_ID,
            "workload_id": config["run"]["workload"],
        })
    batch = {
        key: value.unsqueeze(0)
        for key, value in dataset[nontrivial_index].items()
    }

    torch.manual_seed(int(config["training"]["seed"]))
    feature_embedder = embed.QMAPAccessFeatureEmbedder(
        address_embedder=embed.DynamicVocabEmbedder(
            embed_dim=8,
            max_vocab_size=int(
                config["embedding"]["page"]["max_vocab_size"])),
        pc_embedder=embed.DynamicVocabEmbedder(
            embed_dim=8,
            max_vocab_size=int(
                config["embedding"]["pc"]["max_vocab_size"])),
        rw_embedder=embed.RWFlagEmbedder(embed_dim=2))
    train_trace, _ = read_trace(
        config["data"]["train_trace"], int(config["trace"]["page_shift"]))
    feature_embedder.page_embedder.fit(
        access["page_id"] for access in train_trace).freeze()
    feature_embedder.pc_embedder.fit(
        access["pc"] for access in train_trace).freeze()
    extractor = model.QMAPMacroscopicPatternExtractor(
        hidden_dim=18, num_queries=4, num_layers=1, num_heads=2,
        feedforward_dim=None, dropout=0.0, use_qformer=False,
        pooling_strategy="none",
        position_encoding=config["model"]["position_encoding"],
        max_sequence_length=contract["H"])
    scorer = model.QMAPCandidateScorer(
        hidden_dim=18, page_state_dim=contract["page_state_dim"],
        page_embed_dim=8,
        page_vocab_size=int(
            config["embedding"]["page"]["max_vocab_size"]),
        num_heads=2, dropout=0.0, page_dim=21,
        scoring_input="context", shared_page_embedding=True)
    loss_fn = qmap_loss.QMAPCostAwareRankingLoss(
        lambda_1=float(config["labels"]["lambda_d"]),
        lambda_2=float(config["labels"]["lambda_q"]),
        lambda_3=float(config["labels"]["lambda_w"]),
        lambda_4=0.0,
        alpha=float(config["loss"]["approx_ndcg_alpha"]))
    parameters = (
        list(feature_embedder.parameters()) + list(extractor.parameters()) +
        list(scorer.parameters()))
    before = [parameter.detach().clone() for parameter in parameters]
    optimizer = torch.optim.AdamW(
        parameters, lr=float(config["training"]["learning_rate"]),
        weight_decay=0.0)

    loss = qmap_train._forward_loss(
        batch, feature_embedder, extractor, scorer, loss_fn,
        "cross_attention")
    self.assertTrue(torch.isfinite(loss).item())
    self.assertGreater(abs(loss.item()), 0.0)
    optimizer.zero_grad()
    loss.backward()
    gradients = [
        parameter.grad for parameter in parameters
        if parameter.grad is not None
    ]
    self.assertTrue(gradients)
    self.assertTrue(all(torch.isfinite(gradient).all().item()
                        for gradient in gradients))
    gradient_l1 = sum(
        gradient.detach().abs().sum().item() for gradient in gradients)
    self.assertTrue(math.isfinite(gradient_l1))
    self.assertGreater(gradient_l1, 0.0)
    optimizer.step()
    self.assertTrue(any(
        not torch.equal(previous, parameter.detach())
        for previous, parameter in zip(before, parameters)))

  def _prepare_config(self, root):
    train_trace = os.path.join(root, "mini_train.csv")
    valid_trace = os.path.join(root, "mini_valid.csv")
    test_trace = os.path.join(root, "mini_test.csv")
    write_trace(train_trace, 1, 0x1000)
    write_trace(valid_trace, 1001, 0x2000)
    write_trace(test_trace, 2001, 0x3000)
    base_path = os.path.join(
        PROJECT_ROOT, "configs", "finals", "capd_direction1_v3.json")
    base = finals_config.load_config(base_path)
    # This server-only stage-1 chain validates method semantics. Stage 2 has
    # separate manifest/audit tests and keeps the production config gate on.
    base["validation"]["require_data_manifest"] = False
    base["training"]["epochs"] = 1
    base["training"]["batch_size"] = 2
    base["workloads"]["mini_stage1"] = {
        "train_trace": train_trace,
        "valid_trace": valid_trace,
        "test_trace": test_trace,
    }
    resolved = finals_config.resolve_config(base, "mini_stage1", 64)
    config_path = os.path.join(root, "resolved_v3.json")
    finals_config.write_json(config_path, resolved)
    return config_path

  def _run_once(self, config_path, root):
    os.makedirs(root, exist_ok=True)
    selector = os.path.join(root, "selector_params.json")
    selector_validation = os.path.join(root, "selector_validation.jsonl")
    train_jsonl = os.path.join(root, "train.jsonl")
    valid_jsonl = os.path.join(root, "valid.jsonl")
    generator_summary = os.path.join(root, "generator_summary.json")
    checkpoint_dir = os.path.join(root, "checkpoints")
    result = os.path.join(root, "qmap_result.json")
    run_command([
        sys.executable, "-m", "qmap.finals_generator",
        "--config", config_path,
        "--selector-output", selector,
        "--validation-samples-output", selector_validation,
        "--train-output", train_jsonl,
        "--valid-output", valid_jsonl,
        "--summary-output", generator_summary,
    ])
    run_command([
        sys.executable, "-m", "qmap.qmap_train",
        "--config", config_path,
        "--selector_params", selector,
        "--train_data", train_jsonl,
        "--valid_data", valid_jsonl,
        "--output_dir", checkpoint_dir,
        "--device", "cpu",
    ])
    checkpoint = os.path.join(checkpoint_dir, "qmap_best.pth")
    run_command([
        sys.executable, "-m", "qmap.qmap_eval",
        "--config", config_path,
        "--policy", "qmap",
        "--selector_params", selector,
        "--checkpoint", checkpoint,
        "--device", "cpu",
        "--json_output", result,
    ])
    return {
        "selector": selector,
        "selector_validation": selector_validation,
        "generator_summary": generator_summary,
        "train_jsonl": train_jsonl,
        "valid_jsonl": valid_jsonl,
        "checkpoint": checkpoint,
        "result": result,
    }

  def test_mini_pipeline_contract_chain(self):
    with tempfile.TemporaryDirectory() as directory:
      config_path = self._prepare_config(directory)
      artifacts = self._run_once(config_path, os.path.join(directory, "run"))
      with open(artifacts["result"], "r", encoding="utf-8") as input_file:
        result = json.load(input_file)
      self.assertEqual(TRACE_ACCESS_COUNT, result["total_accesses"])
      self.assertEqual(
          result["total_accesses"], result["hits"] + result["misses"])
      self.assertEqual("capd_finals_v3_0", result["schema_version"])
      self.assertEqual("CAPD-MIC-1.0", result["contract_id"])
      self.assertEqual("official", result["artifact_class"])
      with open(artifacts["generator_summary"], "r",
                encoding="utf-8") as input_file:
        generator_summary = json.load(input_file)
      self.assertIsNone(generator_summary["decision_holdout"])
      self.assertEqual(
          "independent_train_trace",
          generator_summary["train_metadata"]["source_partition"])
      self.assertEqual(
          "independent_valid_trace",
          generator_summary["valid_metadata"]["source_partition"])
      self.assertEqual(3, len(set(
          generator_summary["trace_fingerprints"].values())))
      selector = finals_config.load_json(artifacts["selector"])
      self.assertFalse(selector["fallback_uniform"])
      self.assertGreater(selector["effective_decision_points"], 0)
      epsilon_y = float(finals_config.load_config(
          config_path, require_resolved=True)["selector"]["epsilon_y"])
      relevance_ranges = []
      with open(artifacts["selector_validation"], "r",
                encoding="utf-8") as input_file:
        for line in input_file:
          if line.strip():
            sample = json.loads(line)
            relevance_ranges.append(
                max(sample["relevance"]) - min(sample["relevance"]))
      self.assertTrue(relevance_ranges)
      self.assertTrue(any(value > epsilon_y for value in relevance_ranges))
      self._assert_nontrivial_training_signal(
          config_path, artifacts["train_jsonl"])

  def test_two_run_fixed_seed_determinism(self):
    with tempfile.TemporaryDirectory() as directory:
      config_path = self._prepare_config(directory)
      first = self._run_once(config_path, os.path.join(directory, "run1"))
      second = self._run_once(config_path, os.path.join(directory, "run2"))

      self.assertEqual(
          finals_config.fingerprint_file(first["train_jsonl"]),
          finals_config.fingerprint_file(second["train_jsonl"]))
      self.assertEqual(
          finals_config.fingerprint_file(first["valid_jsonl"]),
          finals_config.fingerprint_file(second["valid_jsonl"]))
      first_selector = finals_config.load_json(first["selector"])
      second_selector = finals_config.load_json(second["selector"])
      self.assertEqual(
          finals_config.selector_fingerprint(first_selector),
          finals_config.selector_fingerprint(second_selector))

      first_checkpoint = torch.load(first["checkpoint"], map_location="cpu")
      second_checkpoint = torch.load(second["checkpoint"], map_location="cpu")
      for component in ("feature_embedder", "extractor", "scorer"):
        assert_state_equal(
            self, first_checkpoint[component], second_checkpoint[component])

      with open(first["result"], "r", encoding="utf-8") as input_file:
        first_result = json.load(input_file)
      with open(second["result"], "r", encoding="utf-8") as input_file:
        second_result = json.load(input_file)
      for key in (
          "total_accesses", "hits", "misses", "migrations", "nvm_reads",
          "nvm_writes", "weighted_access_cost"):
        self.assertEqual(first_result[key], second_result[key])


if __name__ == "__main__":
  unittest.main()
