# coding=utf-8
"""Pure stage-5 variant identity and isolation tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter
from qmap import finals_config
from qmap import finals_generator
from qmap import stage5_variants


class Stage5VariantTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.base_path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    cls.base = finals_config.load_json(cls.base_path)

  def test_preregistered_matrix_is_complete_and_unique(self):
    core = stage5_variants.core_ablation_specs()
    sensitivity = stage5_variants.sensitivity_specs()
    self.assertEqual(10, len(core))
    self.assertEqual(12, len(sensitivity))
    identifiers = [item["variant_id"] for item in core + sensitivity]
    self.assertEqual(len(identifiers), len(set(identifiers)))
    self.assertEqual(
        "no_filter_B8_K8",
        stage5_variants.get_variant_spec("sensitivity_B8")["variant_id"])

  def test_every_variant_changes_only_preregistered_parameters(self):
    for spec in stage5_variants.all_variant_specs().values():
      config = stage5_variants.build_variant_config(self.base, spec)
      finals_config.validate_config(config, require_resolved=True)
      parameters = stage5_variants.config_parameters(config)
      expected = dict(stage5_variants.FULL_PARAMETERS)
      for name in ("B", "K", "H", "Hc", "L"):
        if name in spec["changes"]:
          expected[name] = spec["changes"][name]
      self.assertEqual(expected, parameters, spec["variant_id"])
      self.assertFalse(config["stage5_variant"]["test_used_for_selection"])

  def test_full_loader_still_rejects_non_sinusoidal_checkpoint_config(self):
    invalid = copy.deepcopy(self.base)
    invalid["model"]["position_encoding"] = "none"
    with self.assertRaises(ValueError):
      finals_config.validate_config(invalid, require_resolved=True)
    spec = stage5_variants.get_variant_spec("no_position_encoding")
    valid = stage5_variants.build_variant_config(self.base, spec)
    self.assertEqual("none", valid["model"]["position_encoding"])

  def test_no_filter_bypasses_selection_and_preserves_pool_order(self):
    spec = stage5_variants.get_variant_spec("no_filter_B8_K8")
    config = stage5_variants.build_variant_config(self.base, spec)
    selector = finals_config.load_json(os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B8", "selector_params.json"))
    selector = stage5_variants.build_bound_selector(
        selector, config, spec, command="unit-test")
    dram_pages = list(range(64, 0, -1))
    history = candidate_filter.SelectorHistory(256)
    snapshot = candidate_filter.build_filtered_candidate_snapshot(
        dram_pages, [], 100, {page: 0 for page in dram_pages}, set(),
        history, config, selector)
    self.assertEqual("identity_P_t_equals_C_t", snapshot["selection_mode"])
    self.assertEqual(snapshot["P_t"], snapshot["candidate_pages"])
    self.assertEqual(8, snapshot["B_t"])
    self.assertEqual(8, snapshot["K_t"])

  def test_stage3_leave_one_out_weights_are_frozen(self):
    csv_path = os.path.join(
        PROJECT_ROOT, "outputs", "results", "finals_v3_official",
        "stage3_selector", "stage3_ablation.csv")
    expected = {
        "Delta": (0.0, 0.2, 0.2, 0.3, 0.3),
        "A": (0.2, 0.0, 0.2, 0.3, 0.3),
        "W": (0.2, 0.2, 0.0, 0.3, 0.3),
        "C": (0.2, 0.2, 0.3, 0.0, 0.3),
        "R": (0.2, 0.2, 0.3, 0.3, 0.0),
    }
    for feature, weights in expected.items():
      self.assertEqual(
          weights,
          stage5_variants.stage3_loo_weights(
              csv_path, "canneal", feature))

  def test_uniform_selector_is_identity_not_independent_evidence(self):
    selector = finals_config.load_json(os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "selector_params.json"))
    result = stage5_variants.validate_uniform_identity(selector, selector)
    self.assertEqual("degenerate_identity_control", result["classification"])
    self.assertFalse(result["independent_performance_job"])

  def test_no_future_write_changes_only_write_risk_term(self):
    trace = [
        {"page": 1, "rw": 0}, {"page": 2, "rw": 1},
        {"page": 2, "rw": 1}, {"page": 3, "rw": 0}]
    full = finals_generator.reference_labels(
        trace, 0, 2, 3, require_complete=True, lambda_w=4.0)
    removed = finals_generator.reference_labels(
        trace, 0, 2, 3, require_complete=True, lambda_w=0.0)
    self.assertEqual(full["inactivity"], removed["inactivity"])
    self.assertEqual(full["coldness"], removed["coldness"])
    self.assertEqual(full["write_intensity"], removed["write_intensity"])
    self.assertGreater(removed["relevance"], full["relevance"])

  def test_history_mean_pool_excludes_padding_and_has_no_attention_module(self):
    try:
      import torch
      from policy_learning.cache_model import model
    except ImportError:
      self.skipTest("torch is unavailable")
    torch.manual_seed(7)
    scorer = model.QMAPCandidateScorer(
        hidden_dim=4, page_state_dim=4, page_embed_dim=2,
        page_vocab_size=32, num_heads=2, dropout=0.0,
        scoring_input="context", context_mode="history_mean_pool")
    self.assertIsNone(scorer._cross_attention)
    candidate_pages = torch.tensor([[1, 2]])
    state = torch.zeros((1, 2, 4))
    mask = torch.tensor([[1.0, 1.0]])
    history_mask = torch.tensor([[0.0, 1.0, 1.0]])
    first = torch.tensor([[[100.0] * 4, [1.0] * 4, [3.0] * 4]])
    second = torch.tensor([[[-500.0] * 4, [1.0] * 4, [3.0] * 4]])
    output_a = scorer(
        first, candidate_pages, state, mask, history_mask=history_mask)
    output_b = scorer(
        second, candidate_pages, state, mask, history_mask=history_mask)
    self.assertTrue(torch.allclose(output_a, output_b))

  def test_no_candidate_state_keeps_page_embedding_and_four_input_channels(self):
    try:
      from policy_learning.cache_model import model
    except ImportError:
      self.skipTest("torch is unavailable")
    scorer = model.QMAPCandidateScorer(
        hidden_dim=4, page_state_dim=4, page_embed_dim=2,
        page_vocab_size=32, num_heads=2, context_mode="cross_attention")
    self.assertIsNotNone(scorer._page_embedder)
    self.assertEqual(6, scorer._candidate_projector.in_features)


if __name__ == "__main__":
  unittest.main()
