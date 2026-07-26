# coding=utf-8
"""Post-Stage-6 frozen-method optimization declaration and O0 tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import optimization_variants
from qmap import qmap_eval
from scripts import run_capd_optimization as optimization


class OptimizationPlanTest(unittest.TestCase):

  def _args(self, suffix):
    output_root = os.path.join(
        PROJECT_ROOT, "tmp", "capd_optimization_tests", suffix)
    args = optimization.build_arg_parser().parse_args([
        "--stage", "stage0", "--output-root", output_root])
    args.repo_root = PROJECT_ROOT
    args.output_root = output_root
    return args

  def test_protocol_declares_ordered_gated_phases(self):
    args = self._args("protocol")
    profile = optimization.load_profile(args)
    plan = optimization.build_plan(args, profile)
    self.assertEqual(
        list(optimization.EXPECTED_PHASE_ORDER), plan["phase_order"])
    self.assertEqual(8, plan["candidate_configuration_count"])
    self.assertFalse(plan["method_contract_changed"])
    self.assertFalse(plan["official_stage6_replaced"])
    self.assertFalse(plan["test_used_for_selection"])
    self.assertTrue(plan["preholdout_execution_allowed"])
    self.assertEqual(
        "O4_FINAL_HOLDOUT_ONCE",
        plan["fresh_holdout_required_before_phase"])
    self.assertEqual(
        "forbidden",
        plan["fresh_holdout"]["access_policy"]["O2_CONFIG_SEARCH"])
    for phase in ("O1_ORACLE_HEADROOM", "O2_CONFIG_SEARCH",
                  "O3_MULTISEED_CONFIRMATION"):
      forbidden = plan["phases"][phase]["forbidden_inputs"]
      self.assertIn("official test", forbidden)
      self.assertIn("fresh final holdout", forbidden)

  def test_candidate_matrix_preserves_method_contract(self):
    args = self._args("matrix")
    profile = optimization.load_profile(args)
    plan = optimization.build_plan(args, profile)
    identifiers = {
        config["config_id"] for config in plan["candidate_configurations"]}
    self.assertEqual(8, len(identifiers))
    self.assertIn("opt_full_control", identifiers)
    for config in plan["candidate_configurations"]:
      self.assertEqual(64, config["D"])
      self.assertEqual(256, config["Hc"])
      self.assertEqual(256, config["Lres"])
      self.assertLessEqual(config["K"], config["B"])
      self.assertLessEqual(config["B"], config["D"])

  def test_o0_allows_o1_o3_but_blocks_o4_without_touching_upstream(self):
    stage6_path = os.path.join(PROJECT_ROOT, optimization.STAGE6_MANIFEST)
    bridge_path = os.path.join(PROJECT_ROOT, optimization.BRIDGE_MANIFEST)
    stage6_before = finals_config.fingerprint_file(stage6_path)
    bridge_before = finals_config.fingerprint_file(bridge_path)
    args = self._args("audit")
    profile = optimization.load_profile(args)
    isolated = copy.deepcopy(profile)
    for workload in isolated["workloads"]:
      isolated["fresh_holdout"]["metadata_paths"][workload] = os.path.join(
          args.output_root, "missing", "{}.json".format(workload))
    audit = optimization.audit_inputs(args, isolated)
    stage6_after = finals_config.fingerprint_file(stage6_path)
    bridge_after = finals_config.fingerprint_file(bridge_path)
    self.assertEqual(stage6_before, stage6_after)
    self.assertEqual(bridge_before, bridge_after)
    self.assertEqual("O0_READY_FOR_O1_O3", audit["status"])
    self.assertEqual(3, audit["blocked_o4_inputs"])
    self.assertEqual(0, audit["sealed_holdout_count"])
    self.assertTrue(audit["eligible_to_start_O1"])
    self.assertTrue(audit["eligible_to_start_O2"])
    self.assertTrue(audit["eligible_to_start_O3"])
    self.assertFalse(audit["eligible_to_start_O4"])
    self.assertFalse(audit["method_contract_changed"])
    self.assertFalse(audit["official_stage6_replaced"])

  def test_o1_plan_is_train_valid_only_and_has_54_jobs(self):
    args = self._args("o1_plan")
    profile = optimization.load_profile(args)
    plan = optimization.build_o1_plan(args, profile)
    self.assertEqual(54, plan["required_jobs"])
    self.assertEqual(
        24, len([job for job in plan["jobs"] if job["kind"] == "data"]))
    self.assertEqual(
        24, len([job for job in plan["jobs"] if job["kind"] == "oracle"]))
    self.assertEqual(
        6, len([job for job in plan["jobs"] if job["kind"] == "baseline"]))
    commands = "\n".join(job["command"] for job in plan["jobs"])
    self.assertNotIn("--evaluation_split test", commands)
    self.assertNotIn("test.csv", commands)
    self.assertIn("--evaluation_split valid", commands)

  def test_optimization_config_accepts_only_preregistered_matrix(self):
    args = self._args("config")
    profile = optimization.load_profile(args)
    candidate = optimization._validate_candidate_configs(profile)[-1]
    base_path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    base = finals_config.load_config(
        base_path, require_resolved=True, project_root=PROJECT_ROOT,
        verify_manifest_files=False)
    config = optimization_variants.build_optimization_config(
        base, candidate, "test-commit")
    self.assertEqual(
        finals_config.OPTIMIZATION_PROFILE, config["run_profile"])
    self.assertEqual(
        "optimization_only", config["validation"]["artifact_class"])
    self.assertEqual(32, config["candidate"]["pool_size_B"])
    self.assertEqual(16, config["candidate"]["retained_K"])
    self.assertEqual(512, config["labels"]["future_lookahead_L"])
    self.assertEqual(20, config["history"]["transformer_H"])
    self.assertFalse(
        config["optimization_variant"]["test_used_for_selection"])
    invalid = copy.deepcopy(candidate)
    invalid["H"] = 21
    with self.assertRaises(ValueError):
      optimization_variants.build_optimization_config(
          base, invalid, "test-commit")

  def test_valid_replay_mode_and_per_epoch_saving_are_explicit_opt_ins(self):
    args = self._args("valid_replay")
    profile = optimization.load_profile(args)
    candidate = optimization._validate_candidate_configs(profile)[0]
    base_path = os.path.join(
        PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official",
        "canneal", "B64", "resolved_config.json")
    base = finals_config.load_config(
        base_path, require_resolved=True, project_root=PROJECT_ROOT,
        verify_manifest_files=False)
    config = optimization_variants.build_optimization_config(
        base, candidate, "test-commit")
    config_path = os.path.join(args.output_root, "resolved_config.json")
    finals_config.write_json(config_path, config)
    replay_args = qmap_eval.build_arg_parser().parse_args([
        "--config", config_path, "--evaluation_split", "valid",
        "--policy", "lru"])
    loaded = qmap_eval.apply_replay_finals_config(replay_args)
    self.assertEqual(
        os.path.abspath(config["data"]["valid_trace"]),
        os.path.abspath(replay_args.trace_path))
    self.assertEqual(
        finals_config.OPTIMIZATION_PROFILE, loaded["run_profile"])

  def test_o2_plan_applies_o1_gate_per_workload(self):
    args = self._args("o2_plan")
    profile = optimization.load_profile(args)
    gate = {
        "status": "O1_COMPLETED",
        "proceed_by_workload": {
            "canneal": ["opt_full_control", "opt_B32_K16"],
            "streamcluster_pressure": ["opt_full_control"],
            "dedup_pressure": ["opt_full_control", "opt_L512"],
        },
    }
    finals_config.write_json(optimization._o1_gate_path(args), gate)
    plan = optimization.build_o2_plan(args, profile)
    train = [job for job in plan["jobs"] if job["kind"] == "train"]
    replay = [
        job for job in plan["jobs"] if job["kind"] == "valid_replay"]
    self.assertEqual(5, len(train))
    self.assertEqual(50, len(replay))
    self.assertTrue(all("--save_every_epoch" in job["argv"] for job in train))
    self.assertTrue(all(
        job["argv"][job["argv"].index("--evaluation_split") + 1] == "valid"
        for job in replay))

  def test_o3_plan_reuses_screening_seed_and_adds_two_seeds(self):
    args = self._args("o3_plan")
    profile = optimization.load_profile(args)
    shortlist = {
        "status": "O2_COMPLETED",
        "shortlist_by_workload": {
            workload: ["opt_full_control", "opt_B32_K16"]
            for workload in profile["workloads"]},
    }
    finals_config.write_json(optimization._o2_shortlist_path(args), shortlist)
    plan = optimization.build_o3_plan(args, profile)
    self.assertEqual(
        6, len([job for job in plan["jobs"] if job["kind"] == "data"]))
    self.assertEqual(
        12, len([job for job in plan["jobs"] if job["kind"] == "train"]))
    self.assertEqual(
        120,
        len([job for job in plan["jobs"] if job["kind"] == "valid_replay"]))
    self.assertEqual(138, plan["required_jobs"])
    self.assertEqual(
        {42, 2026},
        {job["seed"] for job in plan["jobs"] if job["kind"] == "train"})


if __name__ == "__main__":
  unittest.main()
