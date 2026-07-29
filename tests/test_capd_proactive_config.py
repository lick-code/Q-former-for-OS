# coding=utf-8
"""Stage-0 contract tests for the current proactive CAPD configuration."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


TEMPLATE_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json")


class ProactiveStage0ConfigTest(unittest.TestCase):

  def setUp(self):
    self.config = finals_config.load_json(TEMPLATE_PATH)

  def _freeze_stage3_and_candidate(self, config):
    config["freeze_status"]["stage3_active_mechanism"] = "frozen"
    config["memory"]["working_set_definition"] = (
        "active_unique_pages_from_train_and_validation")
    config["memory"]["dram_working_set_ratio"] = 0.4
    config["active_demotion"].update({
        "F_low": 4,
        "F_target": 8,
        "b_max": 2,
    })
    config["freeze_status"]["stage4_candidate"] = "frozen"
    config["method"]["candidate_size_K"] = 8

  def _freeze_workload_ranges(self, config):
    config["freeze_status"]["stage7_workload"] = "frozen"
    config["data"]["workload"] = "fixture_workload"
    config["data"]["trace_path"] = "dataset/fixture.trace"
    config["data"]["trace_range"].update({"start": 0, "end": 300})
    config["data"]["splits"]["train"].update({"start": 0, "end": 100})
    config["data"]["splits"]["validation"].update(
        {"start": 100, "end": 200})
    config["data"]["splits"]["test"].update({"start": 200, "end": 300})
    config["memory"]["working_set_size_pages"] = 300
    config["memory"]["dram_pages"] = 120

  def _as_reactive_lru(self, config):
    config["evaluation"]["policy_name"] = "reactive_lru"
    config["method"].update({
        "name": "reactive_lru",
        "candidate_size_K": None,
        "trigger_mode": "on_demand_no_free_frame",
        "fallback_policy": "not_applicable",
    })
    config["freeze_status"]["stage4_candidate"] = "not_applicable"
    config["freeze_status"]["stage4_training"] = "not_applicable"
    config["model"]["model_checkpoint"] = {
        "status": "not_applicable",
        "path": None,
        "fingerprint": None,
    }

  def test_legal_stage0_capd_template_is_accepted(self):
    loaded = finals_config.load_config(TEMPLATE_PATH)
    self.assertEqual(
        finals_config.PROACTIVE_SCHEMA_VERSION, loaded["schema_version"])
    self.assertEqual("capd_proactive", loaded["method"]["name"])

  def test_stage2_default_cost_profile_is_frozen(self):
    self.assertEqual(
        "frozen", self.config["freeze_status"]["stage2_cost_profile"])
    self.assertEqual(
        {
            "status": "frozen",
            "name": "default",
            "weights": {
                "dram_hit": 1,
                "nvm_read": 2,
                "nvm_write": 8,
                "demotion": 10,
            },
        },
        self.config["evaluation"]["cost_profile"])
    finals_config.validate_config(self.config)

  def test_capd_with_frozen_active_fields_is_accepted(self):
    self._freeze_stage3_and_candidate(self.config)
    finals_config.validate_config(self.config)

  def test_missing_required_field_is_rejected(self):
    del self.config["method"]["candidate_source"]
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_overlapping_chronological_splits_are_rejected(self):
    self._freeze_workload_ranges(self.config)
    self.config["data"]["splits"]["train"]["end"] = 120
    self.config["data"]["splits"]["validation"]["start"] = 100
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_split_roles_cannot_be_exchanged(self):
    self.config["data"]["splits"]["validation"]["role"] = (
        "final_evaluation_only")
    self.config["data"]["splits"]["test"]["role"] = "parameter_selection"
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_test_cannot_be_used_for_parameter_selection(self):
    self.config["data"]["parameter_selection_splits"].append("test")
    self.config["data"]["test_used_for_parameter_selection"] = True
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_selector_must_remain_disabled(self):
    self.config["method"]["selector"] = "enabled"
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_single_process_thread_workload_boundary_is_enforced(self):
    for field in ("single_process", "single_thread", "single_workload"):
      with self.subTest(field=field):
        invalid = copy.deepcopy(self.config)
        invalid["scope"][field] = False
        with self.assertRaises(ValueError):
          finals_config.validate_config(invalid)

  def test_unfrozen_formal_test_request_is_rejected(self):
    self.config["execution"].update({
        "mode": "formal_test",
        "requested_split": "test",
        "formal": True,
    })
    with self.assertRaisesRegex(ValueError, "before parameter freeze"):
      finals_config.validate_config(self.config)

  def test_illegal_policy_name_is_rejected(self):
    self.config["evaluation"]["policy_name"] = "old_capd"
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)

  def test_official_policy_set_is_frozen(self):
    self.assertEqual(
        (
            "reactive_lru",
            "proactive_lru",
            "proactive_clock",
            "tpp_inspired",
            "capd",
            "oracle",
        ),
        finals_config.PROACTIVE_OFFICIAL_POLICIES)

  def test_reactive_lru_does_not_require_proactive_fields(self):
    self._as_reactive_lru(self.config)
    finals_config.validate_config(self.config)

    invalid = copy.deepcopy(self.config)
    invalid["active_demotion"]["F_low"] = 1
    with self.assertRaises(ValueError):
      finals_config.validate_config(invalid)

  def test_non_learning_active_policy_requires_only_shared_active_fields(self):
    self.config["evaluation"]["policy_name"] = "proactive_lru"
    self.config["method"]["name"] = "proactive_lru"
    self.config["freeze_status"]["stage4_training"] = "not_applicable"
    self.config["model"]["model_checkpoint"] = {
        "status": "not_applicable",
        "path": None,
        "fingerprint": None,
    }
    self._freeze_stage3_and_candidate(self.config)
    finals_config.validate_config(self.config)

  def test_active_policy_requires_fields_when_its_gate_is_frozen(self):
    self.config["freeze_status"]["stage3_active_mechanism"] = "frozen"
    self.config["memory"]["working_set_definition"] = (
        "active_unique_pages_from_train_and_validation")
    self.config["memory"]["dram_working_set_ratio"] = 0.4
    with self.assertRaises(ValueError):
      finals_config.validate_config(self.config)


if __name__ == "__main__":
  unittest.main()
