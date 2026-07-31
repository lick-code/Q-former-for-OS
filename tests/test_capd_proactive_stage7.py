# coding=utf-8
"""Stage-7 workload-suite, leakage, capacity, and plan tests."""

from __future__ import annotations

import copy
import csv
import io
import os
import tempfile
import unittest

from qmap import proactive_stage7_workloads as stage7
from scripts import convert_drmemtrace_view as drmemtrace_converter


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage7_workloads.json")
CAPACITY_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage7_capacity.json")


def confirmed_config():
  value = stage7.load_json(CONFIG_PATH)
  value["suite_confirmation"].update({
      "confirmed": True,
      "confirmed_by": "unit-test",
      "confirmed_at": "2026-07-31T00:00:00Z",
  })
  return value


def collection_row(workload, role, path, sha256, total=180):
  return {
      "workload": workload,
      "role": role,
      "source_trace_id": workload + "-synthetic-id",
      "raw_trace_path": stage7.portable_path(path, PROJECT_ROOT),
      "raw_trace_sha256": sha256,
      "raw_trace_accesses": total,
      "page_shift": 12,
      "columns": ["PID", "TID", "PC", "Address", "RW"],
      "process_ids": [101],
      "thread_ids": [202],
      "model_training_used": False,
      "capd_checkpoint_retrained": False,
      "tpp_parameters_reselected": False,
      "benchmark": {
          "name": workload,
          "version": "synthetic-test",
          "binary_path": "/bin/true",
          "binary_sha256": "0" * 64,
          "input_name": "synthetic",
          "input_path": None,
          "input_sha256": None,
          "command": ["/bin/true"],
          "thread_parameter": 1,
      },
      "collector": {
          "name": "synthetic",
          "version": "1",
          "command": ["synthetic"],
          "started_at": "2026-07-31T00:00:00Z",
          "ended_at": "2026-07-31T00:00:01Z",
          "exit_code": 0,
          "stdout_log": "synthetic.log",
          "stderr_log": "synthetic.log",
          "truncated": False,
          "timed_out": False,
          "lost_events": False,
      },
      "environment": {
          "machine": "test",
          "cpu": "test",
          "memory": "test",
          "os": "test",
          "git_commit": "test",
          "dirty_worktree": False,
          "aslr": "2",
      },
      "splits": {
          "train": [0, 100],
          "validation": [100, 140],
          "test": [140, total],
      },
  }


def write_trace(path, total=180, mixed_pid=False, missing_rw=False):
  fields = ["PID", "TID", "PC", "Address"]
  if not missing_rw:
    fields.append("RW")
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(fields)
    for index in range(total):
      row = [
          999 if mixed_pid and index == total - 1 else 101,
          202, hex(0x1000 + index),
          hex((index + 1) << 12),
      ]
      if not missing_rw:
        row.append("W" if index % 3 == 0 else "R")
      writer.writerow(row)


class Stage7ConfigTest(unittest.TestCase):

  def setUp(self):
    self.config = stage7.load_json(CONFIG_PATH)
    self.capacity = stage7.load_json(CAPACITY_PATH)

  def test_01_stage6_entry_chain_is_valid(self):
    audit = stage7.audit_stage6_entry(self.config, PROJECT_ROOT)
    self.assertEqual("satisfied", audit["stage7_entry_gate"])

  def test_02_stage6_authority_sha_mutation_is_rejected(self):
    changed = copy.deepcopy(self.config)
    changed["entry_authority"]["stage6_verification"]["sha256"] = "0" * 64
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.audit_stage6_entry(changed, PROJECT_ROOT)

  def test_03_stage6_tpp_parameters_are_frozen(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_inputs"]["tpp_inspired"]["epoch_length"] = 256
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_04_stage4_capd_parameters_are_frozen(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_inputs"]["capd"]["lookahead_L"] = 128
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_05_active_controls_are_frozen(self):
    for field in ("F_low", "F_target", "b_max", "candidate_size_K"):
      changed = copy.deepcopy(self.config)
      changed["frozen_inputs"][field] += 1
      with self.assertRaises(stage7.Stage7ContractError):
        stage7.validate_workload_config(changed)

  def test_06_selector_must_remain_disabled(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_inputs"]["selector"] = "legacy_selector"
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_07_seen_workload_set_is_exact(self):
    stage7.validate_workload_config(self.config)
    self.assertEqual(stage7.SEEN, tuple(
        self.config["seen_calibration_workloads"]))

  def test_08_blackscholes_is_unseen(self):
    row = next(item for item in self.config["proposed_suite"]
               if item["workload"] == "blackscholes")
    self.assertEqual("held_out_unseen_workload", row["role"])

  def test_09_exactly_six_workloads_are_required(self):
    changed = copy.deepcopy(self.config)
    changed["proposed_suite"].pop()
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_10_duplicate_workload_is_rejected(self):
    changed = copy.deepcopy(self.config)
    changed["proposed_suite"][-1]["workload"] = "blackscholes"
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_11_required_type_coverage_is_enforced(self):
    changed = copy.deepcopy(self.config)
    for row in changed["proposed_suite"]:
      row["coverage"] = ["stable_locality"]
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_12_unconfirmed_suite_cannot_freeze(self):
    changed = copy.deepcopy(self.config)
    changed["suite_confirmation"].update({
        "confirmed": False,
        "confirmed_by": None,
        "confirmed_at": None,
    })
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(
          changed, require_confirmed=True)

  def test_13_confirmed_suite_passes_confirmation_gate(self):
    stage7.validate_workload_config(
        confirmed_config(), require_confirmed=True)

  def test_14_heldout_retraining_is_rejected(self):
    changed = confirmed_config()
    changed["proposed_suite"][3]["model_training_used"] = True
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_15_cost_profile_is_frozen(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_inputs"]["cost_profile"]["nvm_write"] = 9
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_16_decimal_ceiling_capacity(self):
    self.assertEqual(21, stage7.decimal_ceil_pages(101, "0.20"))
    self.assertEqual(41, stage7.decimal_ceil_pages(101, "0.40"))
    self.assertEqual(61, stage7.decimal_ceil_pages(101, "0.60"))

  def test_17_capacity_ratios_are_exact(self):
    stage7.validate_capacity_config(self.capacity)
    self.assertEqual(stage7.RATIOS, tuple(self.capacity["ratios"]))

  def test_18_twenty_percent_default_is_not_reselected(self):
    changed = copy.deepcopy(self.capacity)
    changed["default_ratio"] = "0.40"
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_capacity_config(changed)

  def test_19_watermarks_must_not_scale(self):
    changed = copy.deepcopy(self.capacity)
    changed["fixed_active_controls"]["scale_with_capacity"] = True
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_capacity_config(changed)

  def test_20_nvm_is_unbounded_backing_tier(self):
    changed = copy.deepcopy(self.capacity)
    changed["nvm_capacity_model"] = "bounded"
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_capacity_config(changed)

  def test_21_d20_hard_gate_is_enforced(self):
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.capacity_rows("tiny", 80, self.capacity)

  def test_22_d20_below_100_emits_warning(self):
    rows = stage7.capacity_rows("small", 200, self.capacity)
    self.assertIsNotNone(rows[0]["warning"])

  def test_23_pressure_test_is_disabled(self):
    changed = copy.deepcopy(self.capacity)
    changed["pressure_test"]["enabled"] = True
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_capacity_config(changed)

  def test_24_profile_policy_cannot_be_capd(self):
    changed = copy.deepcopy(self.capacity)
    changed["profile"]["policy"] = "capd"
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_capacity_config(changed)


class Stage7TraceAndManifestTest(unittest.TestCase):

  def setUp(self):
    test_tmp_root = os.path.join(PROJECT_ROOT, "tmp")
    os.makedirs(test_tmp_root, exist_ok=True)
    self.temp = tempfile.TemporaryDirectory(dir=test_tmp_root)
    self.config = confirmed_config()
    self.capacity = stage7.load_json(CAPACITY_PATH)
    self.paths = {}
    rows = []
    role_map = {
        item["workload"]: item["role"]
        for item in self.config["proposed_suite"]}
    for workload in role_map:
      path = os.path.join(self.temp.name, workload + ".csv")
      write_trace(path)
      self.paths[workload] = path
      rows.append(collection_row(
          workload, role_map[workload], path,
          stage7.fingerprint_file(path)))
    self.manifest = {
        "schema_version": stage7.COLLECTION_SCHEMA_VERSION,
        "contract_id": stage7.CONTRACT_ID,
        "run_id": "synthetic-stage7",
        "suite_confirmed": True,
        "test_payload_read_for_integrity": True,
        "test_used_for_parameter_selection": False,
        "test_policy_replay_executed": False,
        "test_performance_inspected": False,
        "collections": rows,
    }

  def tearDown(self):
    self.temp.cleanup()

  def test_25_valid_collection_manifest_passes(self):
    stage7.validate_collection_manifest(self.manifest, self.config)

  def test_26_mixed_manifest_pid_is_rejected(self):
    changed = copy.deepcopy(self.manifest)
    changed["collections"][0]["process_ids"] = [1, 2]
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_collection_manifest(changed, self.config)

  def test_27_mixed_manifest_tid_is_rejected(self):
    changed = copy.deepcopy(self.manifest)
    changed["collections"][0]["thread_ids"] = [1, 2]
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_collection_manifest(changed, self.config)

  def test_28_missing_rw_column_is_rejected(self):
    path = os.path.join(self.temp.name, "missing_rw.csv")
    write_trace(path, missing_rw=True)
    with self.assertRaises(stage7.Stage7ContractError):
      list(stage7.iter_trace(path))

  def test_29_page_shift_other_than_12_is_rejected(self):
    with self.assertRaises(stage7.Stage7ContractError):
      list(stage7.iter_trace(self.paths["canneal"], page_shift=13))

  def test_30_overlapping_split_is_rejected(self):
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_intervals({
          "train": [0, 100],
          "validation": [90, 140],
          "test": [140, 180],
      }, 180)

  def test_31_split_role_swap_is_rejected(self):
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_intervals({
          "train": [100, 140],
          "validation": [0, 100],
          "test": [140, 180],
      }, 180)

  def test_32_test_contamination_flag_is_rejected(self):
    changed = copy.deepcopy(self.manifest)
    changed["test_used_for_parameter_selection"] = True
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_collection_manifest(changed, self.config)

  def test_33_loss_or_timeout_is_rejected(self):
    for field in ("lost_events", "timed_out", "truncated"):
      changed = copy.deepcopy(self.manifest)
      changed["collections"][0]["collector"][field] = True
      with self.assertRaises(stage7.Stage7ContractError):
        stage7.validate_collection_manifest(changed, self.config)

  def test_34_raw_sha_mismatch_is_rejected(self):
    changed = copy.deepcopy(self.manifest["collections"][0])
    changed["raw_trace_sha256"] = "0" * 64
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.inspect_collection(changed, PROJECT_ROOT, self.temp.name)

  def test_35_observed_mixed_pid_is_rejected(self):
    path = os.path.join(self.temp.name, "mixed.csv")
    write_trace(path, mixed_pid=True)
    changed = copy.deepcopy(self.manifest["collections"][0])
    changed["raw_trace_path"] = stage7.portable_path(path, PROJECT_ROOT)
    changed["raw_trace_sha256"] = stage7.fingerprint_file(path)
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.inspect_collection(changed, PROJECT_ROOT, self.temp.name)

  def test_36_working_set_excludes_test_only_pages(self):
    row = self.manifest["collections"][0]
    output = os.path.join(self.temp.name, "inspect")
    result = stage7.inspect_collection(row, PROJECT_ROOT, output)
    self.assertEqual(140, result["working_set"]["working_set_pages"])
    self.assertFalse(result["working_set"]["test_pages_used"])

  def test_37_raw_trace_is_not_modified(self):
    row = self.manifest["collections"][0]
    before = stage7.fingerprint_file(self.paths[row["workload"]])
    result = stage7.inspect_collection(
        row, PROJECT_ROOT, os.path.join(self.temp.name, "inspect2"))
    self.assertEqual(before, stage7.fingerprint_file(
        self.paths[row["workload"]]))
    self.assertTrue(result["raw_trace"]["raw_trace_unchanged"])

  def test_38_profile_is_exactly_deterministic(self):
    result = stage7.inspect_collection(
        self.manifest["collections"][0], PROJECT_ROOT,
        os.path.join(self.temp.name, "inspect3"))
    paths = [
        stage7.repository_path(PROJECT_ROOT, result["splits"][role]["path"])
        for role in ("train", "validation")]
    first = stage7.profile_reactive_lru(paths, 28)
    second = stage7.profile_reactive_lru(paths, 28)
    self.assertEqual(first, second)

  def test_39_full_prepare_freezes_standard_test_and_plan(self):
    output = os.path.join(self.temp.name, "suite")
    result = stage7.prepare_suite(
        self.config, self.capacity, self.manifest, PROJECT_ROOT, output)
    self.assertEqual(144, result["stage8_job_count"])
    lock = stage7.load_json(os.path.join(
        output, "standard_test_lock.json"))
    self.assertEqual("sealed_for_stage8", lock["status"])
    self.assertFalse(lock["test_policy_replay_executed"])
    plan = stage7.load_json(os.path.join(
        output, "stage8_execution_plan.json"))
    self.assertEqual(list(stage7.FORMAL_POLICIES),
                     plan["formal_policies"])
    self.assertIsNone(plan["performance_results"])
    self.assertEqual(
        "frozen_checkpoint_unk_index_0",
        plan["generalization_contract"]["page_and_pc_oov_policy"])
    self.assertTrue(
        plan["generalization_contract"]["oov_diagnostics_required_for_capd"])
    self.assertTrue(os.path.isfile(os.path.join(
        output, "workload_profiles.csv")))
    self.assertTrue(os.path.isfile(os.path.join(
        output, "workload_table_cn.md")))

  def test_40_stage8_plan_has_three_capd_seeds_and_no_rule_seeds(self):
    inspected = [
        {"workload": row["workload"], "role": row["role"]}
        for row in self.manifest["collections"]]
    capacities = []
    for row in inspected:
      capacities.extend(stage7.capacity_rows(
          row["workload"], 140, self.capacity))
    lock = {
        "workloads": [
            {"workload": row["workload"],
             "fairness_identity": row["workload"] + "-test"}
            for row in inspected]}
    checkpoints = [
        {"seed": seed, "path": "checkpoint-{}".format(seed),
         "sha256": str(seed)}
        for seed in stage7.CAPD_SEEDS]
    plan = stage7.build_stage8_plan(
        inspected, capacities, lock, checkpoints)
    capd = [job for job in plan["jobs"] if job["policy"] == "capd"]
    rules = [job for job in plan["jobs"] if job["policy"] != "capd"]
    self.assertEqual(set(stage7.CAPD_SEEDS),
                     set(job["seed"] for job in capd))
    self.assertTrue(all(job["seed"] is None for job in rules))
    self.assertNotIn("random", plan["formal_policies"])
    self.assertNotIn("lfu", plan["formal_policies"])

  def test_41_drmemtrace_converter_preserves_legacy_schema(self):
    source = io.StringIO(
        "47446 37770: 1 read 8 byte(s) @ 0x1234 by PC 0x5678\n")
    output = io.StringIO()
    stats = drmemtrace_converter.convert_stream(
        source, output, 1, 0, 12, False)
    self.assertEqual(["PC,Address,RW", "0x5678,0x1000,R"],
                     output.getvalue().strip().splitlines())
    self.assertEqual(1, stats["written"])

  def test_42_drmemtrace_converter_preserves_pid_tid(self):
    source = io.StringIO(
        "10 2: W0.T292 write 8 byte(s) @ 0x2345 by PC 0x6789\n")
    output = io.StringIO()
    stats = drmemtrace_converter.convert_stream(
        source, output, 1, 0, 12, False, True, 292)
    self.assertEqual(
        ["PID,TID,PC,Address,RW", "292,292,0x6789,0x2000,W"],
        output.getvalue().strip().splitlines())
    self.assertEqual([292], stats["process_ids"])
    self.assertEqual([292], stats["thread_ids"])

  def test_43_drmemtrace_converter_rejects_missing_identity(self):
    source = io.StringIO(
        "1 read 8 byte(s) @ 0x1234 by PC 0x5678\n")
    with self.assertRaisesRegex(ValueError, "lacks a W#.T# thread identity"):
      drmemtrace_converter.convert_stream(
          source, io.StringIO(), 1, 0, 12, False, True, 292)

  def test_44_legacy_B64_is_rejected(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_inputs"]["candidate_size_K"] = 64
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_workload_config(changed)

  def test_45_stage7_test_policy_replay_is_rejected(self):
    changed = copy.deepcopy(self.manifest)
    changed["test_policy_replay_executed"] = True
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.validate_collection_manifest(changed, self.config)

  def test_46_drmemtrace_pid_must_be_explicit(self):
    source = io.StringIO(
        "10 2: W0.T292 read 8 byte(s) @ 0x1234 by PC 0x5678\n")
    with self.assertRaisesRegex(ValueError, "PID must come from"):
      drmemtrace_converter.convert_stream(
          source, io.StringIO(), 1, 0, 12, False, True)

  def test_47_prepare_uses_confirmed_order_not_manifest_order(self):
    changed = copy.deepcopy(self.manifest)
    changed["collections"].reverse()
    output = os.path.join(self.temp.name, "suite-shuffled")
    stage7.prepare_suite(
        self.config, self.capacity, changed, PROJECT_ROOT, output)
    registry = stage7.load_json(os.path.join(
        output, "workload_registry.json"))
    self.assertEqual(
        [row["workload"] for row in self.config["proposed_suite"]],
        [row["workload"] for row in registry["workloads"]])


if __name__ == "__main__":
  unittest.main()
