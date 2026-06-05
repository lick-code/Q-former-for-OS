import os
import sys
import unittest

try:
  import torch
except ModuleNotFoundError:
  torch = None


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

if torch is not None:
  from policy_learning.cache_model import model


class QMAPCrossAttentionStaticTest(unittest.TestCase):

  def test_model_declares_full_sequence_extractor_mode(self):
    model_path = os.path.join(
        PROJECT_ROOT, "policy_learning", "cache_model", "model.py")
    with open(model_path, "r", encoding="utf-8") as model_file:
      source = model_file.read()

    self.assertIn('pooling_strategy not in ("mean", "last", "none")', source)

  def test_model_declares_context_only_candidate_scorer_mode(self):
    model_path = os.path.join(
        PROJECT_ROOT, "policy_learning", "cache_model", "model.py")
    with open(model_path, "r", encoding="utf-8") as model_file:
      source = model_file.read()

    self.assertIn("scoring_input", source)
    self.assertIn(
        'mlp_input_dim = hidden_dim if scoring_input == "context"', source)


@unittest.skipIf(torch is None, "PyTorch is not installed in this environment.")
class QMAPCrossAttentionTest(unittest.TestCase):

  def test_extractor_can_return_full_encoded_sequence(self):
    torch.manual_seed(0)
    access_features = torch.randn(2, 5, 18)
    extractor = model.QMAPMacroscopicPatternExtractor(
        hidden_dim=18,
        num_queries=4,
        num_layers=1,
        num_heads=2,
        use_qformer=False,
        pooling_strategy="none")

    encoded = extractor(access_features)

    self.assertEqual((2, 5, 18), tuple(encoded.shape))

  def test_candidate_scorer_uses_context_vector_without_concat(self):
    torch.manual_seed(0)
    encoded = torch.randn(2, 5, 18)
    candidate_pages = torch.randint(1, 4096, (2, 7))
    candidate_state_features = torch.randn(2, 7, 4)
    candidate_mask = torch.ones(2, 7)
    scorer = model.QMAPCandidateScorer(
        hidden_dim=18,
        page_state_dim=4,
        page_embed_dim=8,
        page_vocab_size=4096,
        num_heads=2,
        scoring_input="context")

    scores = scorer(
        encoded, candidate_pages, candidate_state_features, candidate_mask)

    self.assertEqual((2, 7), tuple(scores.shape))
    self.assertEqual(18, scorer._scoring_mlp[0].in_features)


if __name__ == "__main__":
  unittest.main()
