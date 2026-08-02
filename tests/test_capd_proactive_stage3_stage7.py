# coding=utf-8
"""Contract tests for six-workload Stage-7 Stage-3 calibration.

These tests are intentionally executable without opening any real trace.  The
Linux server suite supplies the integration coverage for CSV loading/replay.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest

from qmap import proactive_stage3_stage7 as stage3
from qmap import proactive_replay


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage3_stage7_calibration.json")
SELECTION_REPAIR_CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage3_stage7_selection_repair.json")


class Stage3Stage7ContractTest(unittest.TestCase):

  def setUp(self):
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
      self.config = json.load(handle)
    with open(SELECTION_REPAIR_CONFIG_PATH, "r", encoding="utf-8") as handle:
      self.selection_repair_config = json.load(handle)

  def test_config_freezes_six_workloads_and_stage3_only_search_space(self):
    stage3.validate_config(self.config)
    self.assertEqual(stage3.WORKLOADS, tuple(self.config["workloads"]))
    self.assertEqual([100000, 300000, 500000],
                     self.config["windowing"]["calibration_window_records"])
    self.assertEqual([0.05, 0.10, 0.15, 0.20],
                     self.config["pressure_capacity"]["ratios"])
    self.assertEqual([1, 2, 4, 8],
                     self.config["controller_search"]["b_max_candidates"])
    self.assertEqual(8, self.config["fixed_stage3"]["candidate_size_K"])
    self.assertNotIn("L", self.config["search_space"])
    self.assertNotIn("H", self.config["search_space"])
    self.assertFalse(self.config["provenance"]["test_used_for_selection"])
    self.assertEqual(3, self.config["execution"]["profile_workers"])
    self.assertEqual(
        "window", self.config["execution"]["profile_checkpoint_granularity"])
    self.assertTrue(self.config["execution"]["search_in_memory_cache"])

  def test_test_split_and_formal_test_are_hard_rejected(self):
    for value in (
        {"split_role": "test", "formal_test": False, "trace_path": "x.csv"},
        {"split": "test", "formal_test": False, "trace_path": "x.csv"},
        {"split_role": "validation", "formal_test": True,
         "trace_path": "x.csv"}):
      with self.assertRaises(stage3.Stage3Stage7Error):
        stage3.reject_forbidden_input(value)

  def test_forbidden_path_names_are_hard_rejected(self):
    for token in ("standard_test_lock", "pressure_test", "stage8"):
      with self.assertRaises(stage3.Stage3Stage7Error):
        stage3.reject_forbidden_input({
            "split_role": "validation", "formal_test": False,
            "trace_path": "/tmp/{}/input.csv".format(token)})

  def test_old_capd_and_oracle_test_metrics_are_hard_rejected(self):
    for source in ("old_capd_test_results.json", "oracle_test_metrics.json"):
      with self.assertRaises(stage3.Stage3Stage7Error):
        stage3.reject_forbidden_input({
            "split_role": "validation", "formal_test": False,
            "metrics_source": source})

  def test_authoritative_sha_chain_accepts_only_train_validation(self):
    authority = {
        "run_id": "stage7-repair-r1",
        "status": "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED",
        "input_identity_sha256": self.config["r1_authority"][
            "input_identity_sha256"],
        "identity_access_only": True,
        "policy_metrics_read": False,
        "workloads": []}
    for workload in stage3.WORKLOADS:
      authority["workloads"].append({
          "workload": workload, "page_shift": 12,
          "source_trace_id": workload + "-trace",
          "splits": {
              "train": {
                  "recorded_path": "splits/{}/train.csv".format(workload),
                  "sha256_declared": "a" * 64,
                  "sha256_actual": "a" * 64,
                  "accesses": 1800000,
                  "interval": {"start_inclusive": 0,
                               "end_exclusive": 1800000}},
              "validation": {
                  "recorded_path": "splits/{}/validation.csv".format(workload),
                  "sha256_declared": "b" * 64,
                  "sha256_actual": "b" * 64,
                  "accesses": 600000,
                  "interval": {"start_inclusive": 1800000,
                               "end_exclusive": 2400000}},
              "test": {"recorded_path": "must-not-be-copied/test.csv"}}})
    manifest = stage3.manifest_from_r1_authority(
        authority, self.config, verify_files=False)
    self.assertEqual(12, len(manifest["entries"]))
    self.assertEqual({"train", "validation"},
                     {row["split_role"] for row in manifest["entries"]})
    self.assertFalse(any("test" in row["trace_path"].lower()
                         for row in manifest["entries"]))
    changed = copy.deepcopy(manifest)
    changed["entries"][0]["sha256"] = "c" * 64
    with self.assertRaises(stage3.Stage3Stage7Error):
      stage3.validate_input_manifest(changed, authority)

  def test_multiscale_windows_are_deterministic_and_never_cross_blocks(self):
    first = stage3.build_window_descriptors(
        "train", 1800000, [100000, 300000, 500000], 10000, 3)
    second = stage3.build_window_descriptors(
        "train", 1800000, [100000, 300000, 500000], 10000, 3)
    self.assertEqual(first, second)
    self.assertTrue(first)
    for row in first:
      self.assertGreaterEqual(row["start_record"], row["block_start_record"])
      self.assertLessEqual(row["end_record"], row["block_end_record"])
      self.assertEqual(row["window_records"],
                       row["end_record"] - row["start_record"])
      self.assertFalse(row["crosses_split_boundary"])

  def test_profile_task_plan_is_complete_before_trace_scan(self):
    manifest = {"entries": []}
    for workload in stage3.WORKLOADS:
      manifest["entries"].extend([
          {"workload": workload, "split_role": "train",
           "accesses": 1800000},
          {"workload": workload, "split_role": "validation",
           "accesses": 600000}])
    plan = stage3.profile_task_plan(manifest, self.config)
    self.assertEqual(2232, plan["total_window_count"])
    self.assertEqual(4464, plan["total_task_count"])
    self.assertTrue(all(
        row["window_count"] == 372 and row["total_task_count"] == 744
        for row in plan["workloads"]))

  def test_blocked_calibration_is_chronological_and_not_shuffled(self):
    rows = stage3.build_window_descriptors(
        "train", 1800000, [100000], 10000, 3)
    self.assertEqual([0, 1, 2], sorted({row["block_index"] for row in rows}))
    for block in (0, 1, 2):
      starts = [row["start_record"] for row in rows
                if row["block_index"] == block]
      self.assertEqual(starts, sorted(starts))
    self.assertTrue(all(row["chronological"] for row in rows))
    self.assertTrue(all(not row["shuffle"] for row in rows))

  def test_nearest_rank_wref_quantiles(self):
    values = [1, 2, 3, 4]
    self.assertEqual(2, stage3.nearest_rank(values, 0.50))
    self.assertEqual(3, stage3.nearest_rank(values, 0.75))
    self.assertEqual(4, stage3.nearest_rank(values, 0.90))

  def test_standard_capacity_preserves_union_definition(self):
    rows = stage3.standard_capacity_rows("w", 101, [0.20, 0.40, 0.60])
    self.assertEqual([21, 41, 61], [row["D_standard"] for row in rows])
    self.assertTrue(all(
        row["working_set_definition"] ==
        "unique_pages_in_train_validation_union" for row in rows))

  def test_pressure_capacity_uses_new_ratios_without_64_page_guard(self):
    rows = [stage3.pressure_capacity_row("w", 100, 0.5, ratio)
            for ratio in (0.05, 0.10, 0.15, 0.20)]
    self.assertEqual([8, 10, 15, 20],
                     [row["D_pressure"] for row in rows])
    self.assertEqual([5, 10, 15, 20],
                     [row["D_pressure_raw"] for row in rows])
    self.assertTrue(rows[0]["minimum_capacity_applied"])
    self.assertFalse(any(row["D_pressure"] == 64 for row in rows))

  def test_dynamic_watermark_rounding_clamp_and_legality(self):
    value = stage3.dynamic_watermark(40, 0.10, 0.5)
    self.assertEqual((2, 4), (value["F_low"], value["F_target"]))
    clamped = stage3.dynamic_watermark(1000, 0.20, 0.6)
    self.assertEqual(16, clamped["F_target"])
    self.assertLess(clamped["F_low"], clamped["F_target"])
    self.assertLess(clamped["F_target"], clamped["D"])
    self.assertLessEqual(clamped["reserve_fraction"], 0.25)
    minimum = stage3.dynamic_watermark(8, 0.20, 0.6)
    self.assertEqual((1, 2), (minimum["F_low"], minimum["F_target"]))
    self.assertEqual(0.25, minimum["F_target_over_D"])

  def test_b_t_obeys_batch_gap_and_candidate_bounds(self):
    self.assertEqual(0, stage3.compute_b_t(8, 16, 16, 4, 8))
    self.assertEqual(4, stage3.compute_b_t(8, 16, 4, 4, 8))
    self.assertEqual(2, stage3.compute_b_t(8, 16, 4, 8, 2))
    for free_frames in range(0, 20):
      value = stage3.compute_b_t(8, 16, free_frames, 8, 5)
      self.assertGreaterEqual(value, 0)
      self.assertLessEqual(value, 8)
      self.assertLessEqual(value, max(0, 16 - free_frames))
      self.assertLessEqual(value, 5)

  def test_stage3_can_evaluate_bmax_equal_K_without_changing_old_default(self):
    with self.assertRaises(proactive_replay.ReplayConfigurationError):
      proactive_replay.ReplayParameters(
          policy_name="proactive_lru", dram_capacity_pages=40,
          F_low=4, F_target=8, b_max=8, candidate_size_K=8)
    old = proactive_replay.ReplayParameters(
        policy_name="proactive_lru", dram_capacity_pages=40,
        F_low=4, F_target=8, b_max=4, candidate_size_K=8)
    self.assertNotIn("allow_b_max_equal_candidate_size", old.to_dict())
    value = proactive_replay.ReplayParameters(
        policy_name="proactive_lru", dram_capacity_pages=40,
        F_low=4, F_target=8, b_max=8, candidate_size_K=8,
        allow_b_max_equal_candidate_size=True)
    self.assertEqual(8, value.b_max)
    self.assertTrue(value.allow_b_max_equal_candidate_size)
    self.assertTrue(value.to_dict()["allow_b_max_equal_candidate_size"])

  def test_pressure_eligibility_records_every_failure_reason(self):
    self.assertEqual(["eligible"], stage3.pressure_eligibility(30, 20, 4, 100))
    reasons = stage3.pressure_eligibility(24, 20, 4, 99)
    self.assertIn("unique_pages_not_greater_than_D_plus_F_target", reasons)
    self.assertIn("lru_replacement_decisions_below_100", reasons)
    self.assertIn("invalid_capacity_or_watermark",
                  stage3.pressure_eligibility(12, 8, 3, 100))
    self.assertIn("split_boundary_violation",
                  stage3.pressure_eligibility(30, 20, 4, 100,
                                              split_boundary_valid=False))

  def test_reactive_only_sentinel_selection_rejects_policy_metrics(self):
    rows = [
        {"start_record": 0, "unique_pages": 30,
         "lru_replacement_decisions": 120, "eligible": True},
        {"start_record": 10000, "unique_pages": 40,
         "lru_replacement_decisions": 120, "eligible": True}]
    selected = stage3.choose_reactive_sentinels(rows)
    self.assertEqual(10000, selected["pressure"]["start_record"])
    bad = copy.deepcopy(rows)
    bad[0]["oracle_headroom"] = 1
    with self.assertRaises(stage3.Stage3Stage7Error):
      stage3.choose_reactive_sentinels(bad)
    bad = copy.deepcopy(rows)
    bad[0]["weighted_cost"] = 1
    with self.assertRaises(stage3.Stage3Stage7Error):
      stage3.choose_reactive_sentinels(bad)

  def test_oracle_zero_headroom_blocks_stage4_candidate(self):
    blocked = stage3.oracle_headroom_gate([
        {"oracle_headroom": 0.0}, {"oracle_headroom": 0.0}])
    self.assertFalse(blocked["passed"])
    self.assertFalse(blocked["stage4_candidate_allowed"])
    passed = stage3.oracle_headroom_gate([
        {"oracle_headroom": 0.0}, {"oracle_headroom": 1.0}])
    self.assertTrue(passed["passed"])

  def test_validation_low_pressure_rejects_pointless_demotion(self):
    reactive = {"default_weighted_cost": 100, "dram_hits": 90,
                "reactive_demotions": 0, "page_enter_dram_count": 2}
    proactive = {"default_weighted_cost": 110, "dram_hits": 80,
                 "proactive_demotions": 5, "early_reuse_rate": 0.5}
    result = stage3.validation_safety_gate(
        reactive, proactive, self.config["validation_safety"])
    self.assertFalse(result["passed"])
    self.assertIn("meaningless_proactive_demotions", result["reasons"])
    self.assertIn("weighted_cost_regression", result["reasons"])
    self.assertIn("high_early_reuse", result["reasons"])
    self.assertIn("normal_dram_residency_degraded", result["reasons"])

  def test_selection_repair_scope_is_active_baselines_and_async_runtime(self):
    stage3.validate_selection_repair_config(self.selection_repair_config)
    scope = self.selection_repair_config["experiment_scope"]
    self.assertEqual(
        "pressure_qualification_and_descriptive_reference_only",
        scope["reactive_lru_role"])
    self.assertTrue(scope["asynchronous_replay_required"])
    self.assertTrue(scope["foreground_background_parallelism_required"])
    self.assertFalse(scope["synchronous_efficiency_claims_allowed"])
    self.assertTrue(
        self.selection_repair_config["disclosure"][
            "selection_rule_revised_after_r2_validation_review"])
    self.assertFalse(
        self.selection_repair_config["disclosure"][
            "source_profile_or_search_rerun"])

  def test_role_aware_gate_keeps_sync_reactive_deltas_descriptive(self):
    pressure = stage3.role_aware_validation_gate({
        "candidate_id": "c", "workload": "blackscholes",
        "evaluation_role": "validation_pressure", "start_record": 0,
        "weighted_cost_delta": 1000, "dram_hit_delta": -100,
        "early_reuse_ratio": 0.9, "proactive_demotions": 100,
        "pointless_demotion_limit": 1,
        "reasons": ["weighted_cost_regression", "high_early_reuse",
                    "normal_dram_residency_degraded"]},
        self.selection_repair_config)
    self.assertTrue(pressure["hard_gate_passed"])
    self.assertEqual("descriptive_not_hard_gate",
                     pressure["reactive_comparison_role"])
    self.assertIn("weighted_cost_regression",
                  pressure["diagnostic_flags"])
    low = stage3.role_aware_validation_gate({
        "candidate_id": "c", "workload": "dedup_pressure",
        "evaluation_role": "validation_low_pressure", "start_record": 0,
        "weighted_cost_delta": 1, "dram_hit_delta": 0,
        "early_reuse_ratio": 0.0, "proactive_demotions": 2,
        "pointless_demotion_limit": 1,
        "reasons": ["meaningless_proactive_demotions"]},
        self.selection_repair_config)
    self.assertFalse(low["hard_gate_passed"])
    self.assertEqual(["meaningless_proactive_demotions"],
                     low["hard_failures"])

  def test_active_oracle_gate_compares_two_active_policies(self):
    blocked = stage3.active_oracle_headroom_gate([
        {"active_oracle_headroom": 0.0}])
    self.assertFalse(blocked["passed"])
    passed = stage3.active_oracle_headroom_gate([
        {"active_oracle_headroom": 0.0},
        {"active_oracle_headroom": 3.0}])
    self.assertTrue(passed["passed"])
    self.assertEqual("proactive_lru_minus_proactive_oracle",
                     passed["comparison"])

  def test_active_pareto_does_not_gate_on_sync_reactive_cost_delta(self):
    common = {
        "empty_frame_exhaustion_reduction": 2.0,
        "minimum_free_frames": 3.0,
        "early_reuse_ratio": 0.1,
        "proactive_demotion_count": 9,
        "active_oracle_headroom": 4.0,
        "pressure_coverage": 0.5,
        "eligible_for_active_pareto": True}
    first = dict(common, candidate_id="a",
                 sync_weighted_cost_delta_vs_reactive=100000.0)
    second = dict(common, candidate_id="b",
                  sync_weighted_cost_delta_vs_reactive=1.0)
    frontier = stage3.active_baseline_pareto_frontier([first, second])
    self.assertEqual(["a", "b"],
                     [row["candidate_id"] for row in frontier])
    selected = stage3.select_active_baseline_frontier(
        frontier, self.selection_repair_config)
    self.assertEqual("a", selected["candidate_id"])

  def test_selection_repair_never_auto_freezes_or_claims_sync_efficiency(self):
    self.assertFalse(self.selection_repair_config["selection"]["auto_freeze"])
    self.assertFalse(
        self.selection_repair_config["experiment_scope"][
            "synchronous_efficiency_claims_allowed"])
    for field in (
        "test_payload_opened", "test_used_for_selection",
        "stage8_results_used", "pressure_test_generated",
        "model_training_executed"):
      self.assertFalse(self.selection_repair_config["disclosure"][field])

  def test_pareto_frontier_and_tie_break_are_deterministic(self):
    rows = [
        {"candidate_id": "a", "weighted_cost_delta": -2.0,
         "empty_frame_exhaustion_reduction": 1.0,
         "minimum_free_frames": 2.0, "early_reuse_ratio": 0.1,
         "proactive_demotion_count": 10, "oracle_headroom_utilization": 0.5,
         "pressure_coverage": 0.5, "validation_safety_passed": True},
        {"candidate_id": "b", "weighted_cost_delta": -1.0,
         "empty_frame_exhaustion_reduction": 2.0,
         "minimum_free_frames": 3.0, "early_reuse_ratio": 0.1,
         "proactive_demotion_count": 9, "oracle_headroom_utilization": 0.4,
         "pressure_coverage": 0.5, "validation_safety_passed": True},
        {"candidate_id": "dominated", "weighted_cost_delta": 1.0,
         "empty_frame_exhaustion_reduction": 0.0,
         "minimum_free_frames": 0.0, "early_reuse_ratio": 0.5,
         "proactive_demotion_count": 20, "oracle_headroom_utilization": 0.0,
         "pressure_coverage": 0.2, "validation_safety_passed": True}]
    first = stage3.pareto_frontier(rows)
    second = stage3.pareto_frontier(list(reversed(rows)))
    self.assertEqual(first, second)
    self.assertEqual(["a", "b"],
                     sorted(row["candidate_id"] for row in first))
    selected = stage3.select_from_frontier(first, self.config["selection"])
    self.assertIn(selected["candidate_id"], ("a", "b"))

  def test_profile_window_checkpoint_is_durable_and_reports_progress(self):
    with tempfile.TemporaryDirectory() as directory:
      calls = []
      metadata = {"workload": "canneal", "start_record": 0,
                  "end_record": 100000, "pass": "base_profile"}
      first = stage3._ProfileTaskCache(directory, "canneal")
      payload = first.run(
          metadata, lambda: calls.append("called") or {"unique_pages": 7})
      self.assertEqual({"unique_pages": 7}, payload)
      second = stage3._ProfileTaskCache(directory, "canneal")
      resumed = second.run(
          metadata, lambda: calls.append("called-again") or {"unique_pages": 8})
      self.assertEqual(payload, resumed)
      self.assertEqual(["called"], calls)
      with open(second.log_path, "r", encoding="utf-8") as handle:
        events = [json.loads(line)["event"] for line in handle if line.strip()]
      self.assertEqual(
          ["profile_task_started", "profile_task_completed",
           "profile_task_resumed"], events)

  def test_base_window_profile_reads_each_trace_record_once(self):
    class CountingTrace(object):

      def __init__(self, rows):
        self.rows = rows
        self.read_count = 0

      def __len__(self):
        return len(self.rows)

      def __getitem__(self, index):
        self.read_count += 1
        return self.rows[index]

    rows = [
        {"page": 1, "rw": 0, "pc": 10},
        {"page": 2, "rw": 1, "pc": 11},
        {"page": 1, "rw": 0, "pc": 12},
        {"page": 3, "rw": 0, "pc": 13}]
    trace = CountingTrace(rows)
    descriptor = {
        "split_role": "train", "block_index": 0,
        "block_start_record": 0, "block_end_record": 4,
        "window_records": 4, "start_record": 0, "end_record": 4,
        "chronological": True, "shuffle": False,
        "initial_state": "empty_dram_per_window",
        "crosses_split_boundary": False}
    profile = stage3._window_profile(trace, descriptor, 2, self.config)
    self.assertEqual(4, trace.read_count)
    self.assertEqual(3, profile["unique_pages"])
    self.assertEqual(3, profile["lru_misses"])
    self.assertEqual(1, profile["lru_replacement_decisions"])
    self.assertEqual(0.25, profile["write_ratio"])
    reference = stage3._reactive_lru_profile(
        rows, 2, self.config["windowing"]["page_entry_burst_records"])
    for field in (
        "dram_hits", "nvm_reads", "nvm_writes", "misses",
        "lru_replacement_decisions", "page_entry_count", "page_entry_burst",
        "minimum_free_frames", "mean_free_frames",
        "empty_frame_exhaustion", "default_weighted_cost"):
      self.assertEqual(reference[field], profile[field])
    pages = [row["page"] for row in rows]
    self.assertEqual(
        stage3._reuse_distance_summary(pages),
        profile["reuse_distance_summary"])
    self.assertEqual(
        stage3._growth_summary(
            pages,
            self.config["windowing"]["working_set_growth_sample_records"]),
        profile["working_set_growth"])

  def test_search_task_cache_reuses_memory_before_disk(self):
    with tempfile.TemporaryDirectory() as directory:
      calls = []
      cache = stage3._TaskCache(directory)
      metadata = {"policy": "reactive_lru", "D": 8,
                  "start_record": 0, "end_record": 100000}
      first = cache.run(
          metadata, lambda: calls.append("called") or {"cost": 10})
      second = cache.run(
          metadata, lambda: calls.append("called-again") or {"cost": 11})
      self.assertEqual(first, second)
      self.assertEqual(["called"], calls)
      with open(cache.log_path, "r", encoding="utf-8") as handle:
        events = [json.loads(line)["event"] for line in handle if line.strip()]
      self.assertEqual(
          ["search_task_started", "search_task_completed",
           "search_task_memory_reused"], events)

  def test_resume_identity_changes_when_input_config_or_code_changes(self):
    base = stage3.run_identity_payload("r", "a", "b", ["c"], ["d"])
    self.assertNotEqual(
        stage3.fingerprint_value(base),
        stage3.fingerprint_value(stage3.run_identity_payload(
            "r", "x", "b", ["c"], ["d"])))
    self.assertNotEqual(
        stage3.fingerprint_value(base),
        stage3.fingerprint_value(stage3.run_identity_payload(
            "r", "a", "b", ["changed"], ["d"])))

  def test_all_phases_stop_before_freeze_and_freeze_is_explicit(self):
    self.assertEqual(
        ("preflight", "profile", "search", "select", "verify"),
        stage3.ALL_PHASES)
    self.assertNotIn("freeze", stage3.ALL_PHASES)
    with self.assertRaises(stage3.Stage3Stage7Error):
      stage3.require_freeze_confirmation(False, "candidate.json")
    stage3.require_freeze_confirmation(True, "candidate.json")

  def test_pressure_contract_forbids_test_results(self):
    contract = stage3.build_pressure_contract_candidate({
        "selected_window_records": 300000,
        "W_ref_quantile": 0.75,
        "standard_capacity_matrix": [],
        "pressure_capacity_matrix": [],
        "watermarks": [], "b_max": 4}, self.config)
    self.assertFalse(contract["test_used_for_stage3_selection"])
    self.assertFalse(contract["capd_or_oracle_used_for_pressure_selection"])
    self.assertFalse(contract["pressure_overhead_claims_allowed"])
    self.assertNotIn("test_results", contract)
    stage3.assert_no_forbidden_result_dependency(contract)

  def test_verification_boundary_flags_are_explicitly_false(self):
    value = stage3.verification_boundary()
    self.assertEqual({
        "test_payload_opened": False,
        "test_used_for_selection": False,
        "stage8_results_used": False,
        "pressure_test_generated": False}, value)


if __name__ == "__main__":
  unittest.main()
