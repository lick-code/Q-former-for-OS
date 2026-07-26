# coding=utf-8
"""Bridge diagnostic profile and execution-plan tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import bridge_variants
from qmap import finals_config
from scripts import run_capd_bridge as bridge


class BridgePlanTest(unittest.TestCase):

  def _args(self, output_root):
    args = bridge.build_arg_parser().parse_args(["--stage", "plan"])
    args.repo_root = PROJECT_ROOT
    args.output_root = output_root
    return args

  def test_plan_is_the_frozen_33_job_matrix(self):
    root = os.path.join(
        PROJECT_ROOT, "tmp", "capd_bridge_plan_tests")
    plan = bridge.build_plan(self._args(root))
    self.assertEqual(33, plan["required_jobs"])
    self.assertEqual({
        "data": 3, "train": 9, "replay": 9, "baseline": 12},
        plan["job_counts"])
    self.assertEqual(5, len(plan["cases"]))
    self.assertEqual(4, len(plan["attribution_chain"]))
    self.assertFalse(plan["test_used_for_selection"])
    self.assertFalse(plan["official_stage6_replaced"])
    self.assertEqual(
        len(plan["jobs"]),
        len({job["job_id"] for job in plan["jobs"]}))
    self.assertTrue(all(job["job_fingerprint"] for job in plan["jobs"]))
    qmap = [job for job in plan["jobs"] if job["kind"] == "replay"]
    self.assertTrue(all("--bridge_diagnostics" in job["argv"] for job in qmap))

  def test_bridge_config_is_diagnostic_and_independent(self):
    path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "streamcluster_pressure", "B64", "resolved_config.json")
    base = finals_config.load_config(
        path, require_resolved=True, project_root=PROJECT_ROOT)
    for case in bridge_variants.COMPUTE_CASES:
      config = bridge_variants.build_bridge_config(
          base, case, PROJECT_ROOT, "test-commit")
      self.assertEqual(
          finals_config.DIAGNOSTIC_PROFILE, config["run_profile"])
      self.assertEqual(
          "diagnostic_only", config["validation"]["artifact_class"])
      self.assertEqual(
          "independent_valid_trace", config["validation"]["strategy"])
      self.assertFalse(config["validation"]["require_data_manifest"])
      self.assertEqual(case["D"], config["memory"]["dram_capacity_pages"])
      self.assertEqual(case["B"], config["candidate"]["pool_size_B"])
      self.assertEqual(case["K"], config["candidate"]["retained_K"])
      self.assertFalse(config["bridge_variant"]["test_used_for_selection"])
      finals_config.validate_config(config, require_resolved=True)

  def test_diagnostic_profile_rejects_official_artifact_label(self):
    path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "streamcluster_pressure", "B64", "resolved_config.json")
    base = finals_config.load_config(
        path, require_resolved=True, project_root=PROJECT_ROOT)
    config = bridge_variants.build_bridge_config(
        base, bridge_variants.COMPUTE_CASES[0],
        PROJECT_ROOT, "test-commit")
    invalid = copy.deepcopy(config)
    invalid["validation"]["artifact_class"] = "official"
    invalid["run"].pop("resolved_config_fingerprint", None)
    with self.assertRaises(ValueError):
      finals_config.validate_config(invalid, require_resolved=True)


if __name__ == "__main__":
  unittest.main()
