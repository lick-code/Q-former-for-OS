# coding=utf-8
"""Torch-dependent CAPD stage-1 tests for later server execution."""

import json
import os
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

if torch is not None:
  from policy_learning.cache_model import embed
  from policy_learning.cache_model import model
  from policy_learning.cache_model import qmap_loss
  from qmap import finals_config
  from qmap.qmap_train import QMAPAccessSequenceDataset


@unittest.skipIf(torch is None, "PyTorch is required on the validation server.")
class SharedVocabAndEmbeddingTest(unittest.TestCase):

  def test_train_fit_freeze_oov_and_valid_forward_do_not_mutate_vocab(self):
    page_vocab = embed.DynamicVocabEmbedder(8, 32)
    pc_vocab = embed.DynamicVocabEmbedder(8, 32)
    features = embed.QMAPAccessFeatureEmbedder(
        address_embedder=page_vocab,
        pc_embedder=pc_vocab,
        rw_embedder=embed.RWFlagEmbedder(2))
    page_vocab.fit([11, 22]).freeze()
    pc_vocab.fit([101, 202]).freeze()
    self.assertEqual([1, 0], page_vocab.indices([11, 999]).tolist())
    self.assertEqual([1, 0], pc_vocab.indices([101, 999]).tolist())
    page_before = page_vocab.input_to_index
    pc_before = pc_vocab.input_to_index
    page_size_before = page_vocab.vocab_size
    pc_size_before = pc_vocab.vocab_size

    history_pages = torch.tensor([[11, 999]], dtype=torch.long)
    pcs = torch.tensor([[101, 999]], dtype=torch.long)
    rw = torch.tensor([[0, 1]], dtype=torch.long)
    features(history_pages, pcs, rw)
    features.embed_pages(torch.tensor([[22, 777]], dtype=torch.long))
    features(torch.tensor([[1000, 22]]),
             torch.tensor([[1000, 202]]), rw)

    self.assertEqual(page_size_before, page_vocab.vocab_size)
    self.assertEqual(pc_size_before, pc_vocab.vocab_size)
    self.assertEqual(page_before, page_vocab.input_to_index)
    self.assertEqual(pc_before, pc_vocab.input_to_index)

  def test_history_and_candidate_paths_share_the_exact_embedding_row(self):
    page_vocab = embed.DynamicVocabEmbedder(8, 32)
    page_vocab.fit([42]).freeze()
    features = embed.QMAPAccessFeatureEmbedder(
        address_embedder=page_vocab,
        pc_embedder=embed.DynamicVocabEmbedder(8, 32).freeze(),
        rw_embedder=embed.RWFlagEmbedder(2))
    history_features = features(
        torch.tensor([[42]]), torch.tensor([[7]]), torch.tensor([[0]]))
    history_lookup = history_features[..., :page_vocab.embed_dim]
    candidate_lookup = features.embed_pages(torch.tensor([[42]]))
    self.assertTrue(torch.equal(history_lookup, candidate_lookup))
    self.assertEqual(
        page_vocab._embedding.weight.data_ptr(),
        features.page_embedder._embedding.weight.data_ptr())

    scorer = model.QMAPCandidateScorer(
        hidden_dim=18, page_state_dim=4, page_embed_dim=8,
        page_vocab_size=32, num_heads=2, scoring_input="context",
        shared_page_embedding=True)
    self.assertIsNone(scorer._page_embedder)
    encoded = torch.zeros(1, 2, 18)
    states = torch.zeros(1, 1, 4)
    mask = torch.ones(1, 1)
    scores = scorer(
        encoded, torch.tensor([[42]]), states, mask,
        candidate_page_embeddings=candidate_lookup,
        history_mask=torch.ones(1, 2))
    self.assertEqual((1, 1), tuple(scores.shape))


@unittest.skipIf(torch is None, "PyTorch is required on the validation server.")
class PositionAndLossTest(unittest.TestCase):

  def test_fixed_sinusoidal_positions_have_exact_dtype_device_and_values(self):
    encoding = model.SinusoidalPositionEncoding(6, max_sequence_length=4)
    inputs = torch.zeros(1, 3, 6, dtype=torch.float64)
    output = encoding(inputs)
    self.assertEqual(inputs.dtype, output.dtype)
    self.assertEqual(inputs.device, output.device)
    self.assertTrue(torch.equal(
        output[0, 0],
        torch.tensor([0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
                     dtype=torch.float64)))
    self.assertFalse(torch.equal(output[0, 0], output[0, 1]))
    self.assertFalse(encoding.encoding.requires_grad)

  def test_history_padding_cannot_change_valid_transformer_tokens(self):
    torch.manual_seed(0)
    extractor = model.QMAPMacroscopicPatternExtractor(
        hidden_dim=6, num_layers=1, num_heads=2, dropout=0.0,
        use_qformer=False, pooling_strategy="none",
        position_encoding="sinusoidal", max_sequence_length=4)
    extractor.eval()
    left = torch.zeros(1, 4, 6)
    right = left.clone()
    valid = torch.tensor([
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        [0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
    ])
    left[0, 2:] = valid
    right[0, :2] = 1000.0
    right[0, 2:] = valid
    history_mask = torch.tensor([[0.0, 0.0, 1.0, 1.0]])
    left_encoded = extractor(left, history_mask=history_mask)
    right_encoded = extractor(right, history_mask=history_mask)
    self.assertTrue(torch.isfinite(left_encoded).all())
    self.assertTrue(torch.isfinite(right_encoded).all())
    self.assertTrue(torch.equal(
        left_encoded[:, :2, :], torch.zeros_like(left_encoded[:, :2, :])))
    self.assertTrue(torch.equal(
        right_encoded[:, :2, :], torch.zeros_like(right_encoded[:, :2, :])))
    self.assertTrue(torch.allclose(
        left_encoded[:, 2:, :], right_encoded[:, 2:, :],
        rtol=0.0, atol=1e-6))

  def test_approx_positions_exclude_diagonal_and_padding_exactly(self):
    loss_fn = qmap_loss.QMAPCostAwareRankingLoss(alpha=10.0)
    scores = torch.tensor([[2.0, 0.0, 100.0]])
    mask = torch.tensor([[1.0, 1.0, 0.0]])
    positions = loss_fn._approx_positions(scores, mask)
    expected_first = 1.0 + torch.sigmoid(torch.tensor(-20.0)).item()
    expected_second = 1.0 + torch.sigmoid(torch.tensor(20.0)).item()
    self.assertAlmostEqual(expected_first, positions[0, 0].item(), places=6)
    self.assertAlmostEqual(expected_second, positions[0, 1].item(), places=6)
    self.assertEqual(1.0, positions[0, 2].item())

  def test_padding_values_do_not_change_approx_ndcg(self):
    loss_fn = qmap_loss.QMAPCostAwareRankingLoss(alpha=10.0)
    two_scores = torch.tensor([[2.0, 0.0]])
    two_mask = torch.tensor([[1.0, 1.0]])
    three_scores = torch.tensor([[2.0, 0.0, 1000.0]])
    three_mask = torch.tensor([[1.0, 1.0, 0.0]])
    inactivity_two = torch.tensor([[1.0, 0.0]])
    inactivity_three = torch.tensor([[1.0, 0.0, -999.0]])
    zeros_two = torch.zeros_like(two_scores)
    zeros_three = torch.zeros_like(three_scores)
    loss_two = loss_fn(
        two_scores, inactivity_two, zeros_two, zeros_two, zeros_two,
        two_mask)
    loss_three = loss_fn(
        three_scores, inactivity_three, zeros_three, zeros_three, zeros_three,
        three_mask)
    self.assertAlmostEqual(loss_two.item(), loss_three.item(), places=6)


@unittest.skipIf(torch is None, "PyTorch is required on the validation server.")
class V3JsonlSchemaTest(unittest.TestCase):

  @staticmethod
  def sample():
    return {
        "schema_version": finals_config.SCHEMA_VERSION,
        "contract_id": finals_config.CONTRACT_ID,
        "workload_id": "unit",
        "decision_index": 12,
        "history_page_ids": [0, 11],
        "history_mask": [0, 1],
        "pc": [0, 101],
        "rw": [0, 1],
        "candidate_pages": [11, 22],
        "candidate_state_features": [
            [0.5, 1.0, 0.25, 1.0],
            [0.0, 0.0, 0.5, 0.0],
        ],
        "candidate_mask": [1, 1],
        "original_pool_ranks": [0, 3],
        "inactivity": [1.0, 0.5],
        "coldness": [0.5, 1.0],
        "write_sensitivity": [0.25, 0.0],
        "migration_cost": [0.0, 0.0],
    }

  def test_v3_accepts_history_page_ids_and_rejects_old_field(self):
    with tempfile.TemporaryDirectory() as directory:
      valid_path = os.path.join(directory, "valid.jsonl")
      with open(valid_path, "w", encoding="utf-8") as output_file:
        output_file.write(json.dumps(self.sample()) + "\n")
      dataset = QMAPAccessSequenceDataset(
          valid_path, expected_shape={"H": 2, "K": 2,
                                      "page_state_dim": 4},
          expected_identity={
              "schema_version": finals_config.SCHEMA_VERSION,
              "contract_id": finals_config.CONTRACT_ID,
              "workload_id": "unit",
          })
      self.assertEqual([0, 11], dataset[0]["history_page_ids"].tolist())
      self.assertEqual([0.0, 1.0], dataset[0]["history_mask"].tolist())

      old_path = os.path.join(directory, "old-field.jsonl")
      old_sample = self.sample()
      old_sample["physical_address"] = [0, 11]
      with open(old_path, "w", encoding="utf-8") as output_file:
        output_file.write(json.dumps(old_sample) + "\n")
      with self.assertRaisesRegex(ValueError, "rejects legacy field"):
        QMAPAccessSequenceDataset(old_path)


if __name__ == "__main__":
  unittest.main()
