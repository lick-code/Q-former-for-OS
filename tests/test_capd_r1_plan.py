# coding=utf-8
"""R1 pressure-headroom protocol and execution-plan tests."""

import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import pressure_variants
from scripts import run_capd_r1 as r1


class R1PressurePlanTest(unittest.TestCase):

  def _args(self, output_root):
    args = r1.build_arg_parser().parse_args([
        "--stage", "plan",
        "--output-root", output_root,
        "--data-root", os.path.join(output_root, "data")])
    r1._resolve_args(args)
    return args

  def test_plan_is_45_cpu_jobs_without_training_or_test(self):
    root = os.path.join(PROJECT_ROOT, "tmp", "capd_r1_plan_tests", "plan")
    plan = r1.build_plan(self._args(root))
    self.assertEqual(45, plan["required_jobs"])
    self.assertEqual({
        "data": 9, "oracle": 9, "opportunity": 9, "baseline": 18},
        plan["job_counts"])
    self.assertEqual(0, plan["training_jobs"])
    self.assertEqual(
        len(plan["jobs"]),
        len({job["job_id"] for job in plan["jobs"]}))
    self.assertTrue(all(job["job_fingerprint"] for job in plan["jobs"]))
    commands = "\n".join(job["command"] for job in plan["jobs"])
    self.assertNotIn("--evaluation_split test", commands)
    self.assertNotIn("test.csv", commands)
    self.assertIn("--evaluation_split valid", commands)
    self.assertFalse(plan["method_selection_performed"])
    self.assertFalse(plan["bridge_test_used_for_selection"])
    self.assertFalse(plan["test_used_for_selection"])

  def test_pressure_matrix_is_exactly_d16_d32_d64_with_b_equal_d(self):
    profile_args = self._args(os.path.join(
        PROJECT_ROOT, "tmp", "capd_r1_plan_profile"))
    profile = r1.load_profile(profile_args)
    points = [
        pressure_variants.validate_pressure_point(point)
        for point in profile["pressure_points"]]
    self.assertEqual([16, 32, 64], [point["D"] for point in points])
    self.assertTrue(all(point["B"] == point["D"] for point in points))
    self.assertTrue(all(point["K"] == 8 for point in points))

  def test_pressure_configs_are_diagnostic_only_and_contract_preserving(self):
    base_path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    base = finals_config.load_config(
        base_path, require_resolved=True, project_root=PROJECT_ROOT,
        verify_manifest_files=False)
    for point in pressure_variants.PRESSURE_POINTS:
      config = pressure_variants.build_pressure_config(
          base, point, PROJECT_ROOT, "test-commit")
      self.assertEqual(
          finals_config.DIAGNOSTIC_PROFILE, config["run_profile"])
      self.assertEqual(
          "diagnostic_only", config["validation"]["artifact_class"])
      self.assertFalse(config["validation"]["require_data_manifest"])
      self.assertEqual(point["D"], config["memory"]["dram_capacity_pages"])
      self.assertEqual(point["B"], config["candidate"]["pool_size_B"])
      self.assertEqual(point["K"], config["candidate"]["retained_K"])
      variant = config["pressure_variant"]
      self.assertFalse(variant["retrain_required"])
      self.assertFalse(variant["method_selection_performed"])
      self.assertFalse(variant["test_used_for_selection"])
      self.assertFalse(variant["method_contract_changed"])
      finals_config.validate_config(config, require_resolved=True)

  def test_input_audit_keeps_upstream_frozen(self):
    root = os.path.join(PROJECT_ROOT, "tmp", "capd_r1_plan_tests", "audit")
    args = self._args(root)
    paths = [
        os.path.join(PROJECT_ROOT, r1.STAGE6_MANIFEST),
        os.path.join(PROJECT_ROOT, r1.BRIDGE_MANIFEST),
        os.path.join(PROJECT_ROOT, r1.O3_MANIFEST),
    ]
    before = [finals_config.fingerprint_file(path) for path in paths]
    audit = r1.audit_inputs(args)
    after = [finals_config.fingerprint_file(path) for path in paths]
    self.assertEqual(before, after)
    self.assertEqual("R1_READY", audit["status"])
    self.assertTrue(audit["eligible_to_execute_R1"])
    self.assertFalse(audit["test_trace_opened"])
    self.assertFalse(audit["method_selection_performed"])


if __name__ == "__main__":
  unittest.main()
