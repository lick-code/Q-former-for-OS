# coding=utf-8
"""Stage-6 config and execution-plan contract tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import stage6_variants
from scripts import run_capd_stage6 as stage6


class Stage6PlanTest(unittest.TestCase):

  def _args(self):
    args = stage6.build_parser().parse_args(["--stage", "plan"])
    stage6._resolve_paths(args)
    return args

  def test_plan_has_profile_and_capacity_matrix(self):
    plan = stage6.build_execution_plan(self._args())
    self.assertEqual(27, plan["counts"]["profile_replay_jobs"])
    self.assertEqual(6, plan["counts"]["capacity_data_jobs"])
    self.assertEqual(18, plan["counts"]["capacity_training_jobs"])
    self.assertEqual(54, plan["counts"]["capacity_replay_jobs"])
    self.assertEqual(105, plan["counts"]["required_jobs"])
    profile = next(
        job for job in plan["jobs"]
        if job["job_id"] == "profile:canneal:lru:deterministic")
    self.assertIn(
        "dataset/processed/finals_v3_official/canneal/test.csv",
        profile["input_fingerprints"])
    self.assertTrue(all(job["required"] for job in plan["jobs"]))
    self.assertTrue(all(job["job_fingerprint"] for job in plan["jobs"]))
    self.assertFalse(plan["test_used_for_selection"])
    qmap_profiles = [
        job for job in plan["jobs"]
        if job["stage"] == "profile" and job["policy"] == "qmap"]
    self.assertEqual(9, len(qmap_profiles))
    self.assertTrue(all(
        "--stage6_profile" in job["argv"] for job in qmap_profiles))

  def test_capacity_config_changes_only_declared_D(self):
    path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    base = finals_config.load_json(path)
    variant = stage6_variants.build_capacity_config(base, 128)
    self.assertEqual(128, variant["memory"]["dram_capacity_pages"])
    self.assertEqual(64, variant["candidate"]["pool_size_B"])
    self.assertEqual("capacity_D128",
                     variant["stage6_variant"]["variant_id"])
    finals_config.validate_config(variant, require_resolved=True)

    invalid = copy.deepcopy(variant)
    invalid["memory"]["dram_capacity_pages"] = 96
    invalid["run"].pop("resolved_config_fingerprint", None)
    with self.assertRaises(ValueError):
      finals_config.validate_config(invalid, require_resolved=True)

  def test_stage5_and_stage6_variant_cannot_mix(self):
    path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    config = stage6_variants.build_capacity_config(
        finals_config.load_json(path), 128)
    config["stage5_variant"] = {
        "variant_id": "sensitivity_B32", "family": "sensitivity",
        "only_difference": "invalid mixed test", "source_stage": "stage5",
        "test_used_for_selection": False, "retrain_required": True}
    with self.assertRaises(ValueError):
      finals_config.validate_config(config, require_resolved=True)


if __name__ == "__main__":
  unittest.main()
