# coding=utf-8
"""Frozen stage-1 Replay summary to stage-2 Cost integration tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from scripts import recompute_proactive_cost


STAGE0_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json")
STAGE1_FIXTURE = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage1_fixture.json")
STAGE2_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage2_cost_profiles.json")


class Stage1Stage2IntegrationTest(unittest.TestCase):

  def setUp(self):
    self.stage0 = finals_config.load_config(STAGE0_CONFIG)
    self.fixture = finals_config.load_json(STAGE1_FIXTURE)
    self.cost_config = proactive_cost.load_cost_config(STAGE2_CONFIG)

  def test_cross_stage_contracts_are_frozen_and_consistent(self):
    self.assertEqual(
        "frozen",
        self.stage0["freeze_status"]["stage2_cost_profile"])
    self.assertEqual(
        self.cost_config.profiles["default"].weights_dict(),
        self.stage0["evaluation"]["cost_profile"]["weights"])
    self.assertEqual("stage2_verified", self.cost_config.stage_status)
    self.assertTrue(self.cost_config.stage1_integration_completed)

  def test_every_stage1_fixture_summary_recomputes_all_profiles(self):
    replay_results = proactive_replay.run_fixture_scenarios(
        self.stage0, self.fixture)
    self.assertGreaterEqual(len(replay_results), 2)

    for scenario_name, replay_result in replay_results.items():
      with self.subTest(scenario=scenario_name):
        summary = replay_result["summary"]
        before = copy.deepcopy(summary)
        output = recompute_proactive_cost.recompute_records(
            [summary], True, self.cost_config,
            proactive_cost.FROZEN_PROFILE_NAMES)
        payload = output["stage2_cost"]
        raw = payload["raw_counts"]

        self.assertEqual(before, summary)
        self.assertEqual(
            proactive_replay.STAGE1_LOG_SCHEMA_VERSION,
            payload["stage1_log_schema_version"])
        self.assertEqual(
            proactive_cost.STAGE1_ADAPTER_STATUS,
            payload["stage1_adapter_status"])
        self.assertEqual(
            summary["total_demotions"],
            summary["proactive_demotions"] +
            summary["reactive_demotions"] +
            summary["emergency_demotions"])
        self.assertEqual(summary["dram_hits"], raw["dram_hits"])
        self.assertEqual(summary["nvm_reads"], raw["nvm_reads"])
        self.assertEqual(summary["nvm_writes"], raw["nvm_writes"])
        self.assertEqual(summary["total_demotions"], raw["total_demotions"])
        self.assertEqual(
            set(proactive_cost.FROZEN_PROFILE_NAMES),
            set(payload["cost_results"]))

        expected_default = (
            summary["dram_hits"] +
            2 * summary["nvm_reads"] +
            8 * summary["nvm_writes"] +
            10 * summary["total_demotions"])
        self.assertEqual(
            expected_default, payload["default_weighted_cost"])
        for result in payload["cost_results"].values():
          self.assertEqual(raw, result["raw_counts"])
          self.assertEqual(
              result["weighted_cost"],
              sum(result["component_costs"].values()))

  def test_stage1_adapter_rejects_wrong_or_already_costed_summary(self):
    replay_results = proactive_replay.run_fixture_scenarios(
        self.stage0, self.fixture)
    summary = next(iter(replay_results.values()))["summary"]

    wrong_schema = copy.deepcopy(summary)
    wrong_schema["schema_version"] = "unknown_stage1_schema"
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "schema_version"):
      proactive_cost.recompute_stage1_summary(
          wrong_schema, self.cost_config)

    already_costed = copy.deepcopy(summary)
    already_costed["weighted_cost"] = 123
    already_costed["weighted_cost_status"] = "computed"
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "must remain null"):
      proactive_cost.recompute_stage1_summary(
          already_costed, self.cost_config)


if __name__ == "__main__":
  unittest.main()
