# coding=utf-8
"""Contract, statistics, selection, and synthetic integration tests for stage 3."""

import copy
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage3


STAGE0 = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json")
STAGE2 = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage2_cost_profiles.json")
STAGE3 = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage3_active_mechanism.json")


class Stage3Test(unittest.TestCase):

  def setUp(self):
    self.stage0 = finals_config.load_config(STAGE0)
    self.stage2 = proactive_cost.load_cost_config(STAGE2)
    self.config = proactive_stage3.load_json(STAGE3)

  @staticmethod
  def manifest(kind="synthetic_smoke"):
    return {
        "schema_version": proactive_stage3.MANIFEST_SCHEMA,
        "calibration_kind": kind,
        "path_base": "project_root",
        "test_used_for_parameter_selection": False,
        "fresh_validation_attestation": {
            "capacity_rule_version": "capacity_rule_v2",
            "rule_frozen_before_validation_selection": True,
            "fresh_validation_required": True,
            "validation_used_in_rule_design": False,
            "formal_test_reused": False,
            "previous_stage3_input_trace_fingerprints": {
                "synthetic_locality": ["0" * 64],
            },
        },
        "entries": [
            {
                "workload": "synthetic_locality",
                "split": "train",
                "role": "training_and_fit",
                "trace_path": "train.csv",
                "page_shift": 12,
                "source_kind": "raw_access_trace",
                "formal_test": False,
            },
            {
                "workload": "synthetic_locality",
                "split": "validation",
                "role": "parameter_selection",
                "trace_path": "validation.csv",
                "page_shift": 12,
                "source_kind": "raw_access_trace",
                "formal_test": False,
            },
        ],
    }

  @staticmethod
  def trace(offset=0):
    # Forty pages, each accessed 25 consecutive times.  Window-100 admission
    # counts remain small enough to create three legal watermarks at 20% W.
    return [
        {"page": offset + page, "rw": (page + repeat) % 2, "pc": page}
        for page in range(40)
        for repeat in range(25)
    ]

  def test_config_is_predeclared_and_cross_stage_consistent(self):
    proactive_stage3.validate_config(
        self.config, stage0=self.stage0, stage2=self.stage2)
    self.assertIsNone(self.config["watermark_candidates"])
    self.assertEqual([1, 2, 4], self.config["b_max_candidates"])
    self.assertEqual(
        "non_formal_calibration_proxy",
        self.config["stage3_candidate_bound_status"])
    self.assertEqual(
        "pending", self.stage0["freeze_status"]["stage3_active_mechanism"])

  def test_stage2_must_be_verified(self):
    bad = copy.deepcopy(self.stage2.source)
    bad["stage_status"] = "pending"
    with self.assertRaises(proactive_cost.CostContractError):
      proactive_cost.validate_cost_config(bad)

  def test_test_split_and_formal_test_are_rejected(self):
    manifest = self.manifest()
    manifest["entries"][1]["split"] = "test"
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.validate_manifest(manifest)

  def test_manifest_loader_parses_raw_pages_and_fingerprints(self):
    temporary = tempfile.mkdtemp(prefix="capd-stage3-input-")
    self.addCleanup(shutil.rmtree, temporary, True)
    manifest = self.manifest()
    manifest["path_base"] = "manifest_directory"
    for entry in manifest["entries"]:
      path = os.path.join(temporary, entry["trace_path"])
      with open(path, "w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["pc", "address", "rw"])
        writer.writerow(["0x10", "0x1000", "read"])
        writer.writerow(["0x20", "0x2000", "write"])
    manifest_path = os.path.join(temporary, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as output_file:
      json.dump(manifest, output_file)
    loaded, traces, entries = proactive_stage3.load_inputs(
        manifest_path, PROJECT_ROOT)
    self.assertEqual(proactive_stage3.MANIFEST_SCHEMA, loaded["schema_version"])
    self.assertEqual([1, 2], [
        item["page"] for item in traces["synthetic_locality"]["train"]])
    self.assertEqual(2, len(entries))
    self.assertTrue(all(len(item["trace_fingerprint"]) == 64 for item in entries))
    reused = self.manifest()
    reused["path_base"] = "manifest_directory"
    reused["fresh_validation_attestation"][
        "previous_stage3_input_trace_fingerprints"]["synthetic_locality"] = [
            next(
                item["trace_fingerprint"] for item in entries
                if item["split"] == "validation")]
    reused_path = os.path.join(temporary, "reused.json")
    with open(reused_path, "w", encoding="utf-8") as output_file:
      json.dump(reused, output_file)
    with self.assertRaisesRegex(
        proactive_stage3.Stage3ContractError,
        "reuses a previous Stage-3 input"):
      proactive_stage3.load_inputs(reused_path, PROJECT_ROOT)
    manifest = self.manifest()
    manifest["entries"][1]["formal_test"] = True
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.validate_manifest(manifest)

  def test_capd_and_candidate_filter_cannot_calibrate(self):
    bad = copy.deepcopy(self.config)
    bad["ranking_policy"] = "capd"
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.validate_config(bad)
    bad = copy.deepcopy(self.config)
    bad["provenance"]["candidate_filter"] = "enabled"
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.validate_config(bad)

  def test_capacity_rule_v2_selects_fallback_from_validation_only(self):
    def rows(profile, ratios, validation_values, train_values):
      result = []
      for split, values in (
          ("train", train_values), ("validation", validation_values)):
        for ratio, replacement in zip(ratios, values):
          page_enters = 1000
          reactive = int(page_enters * replacement)
          result.append({
              "workload": "w",
              "split": split,
              "capacity_profile": profile,
              "capacity_ratio": ratio,
              "total_accesses": 10000,
              "page_enter_dram_count": page_enters,
              "nvm_reads": 100,
              "nvm_writes": 20,
              "total_demotions": reactive,
              "reactive_demotions": reactive,
              "free_frame_exhaustion_count": 0,
          })
      return result

    rule = self.config["pressure_distinguishability_rule"]
    primary = proactive_stage3.audit_pressure(
        rows(
            "primary", [0.2, 0.4, 0.6],
            [0.70, 0.05, 0.0],
            [0.70, 0.50, 0.20]),
        rule, "primary")
    fallback = proactive_stage3.audit_pressure(
        rows(
            "fallback", [0.1, 0.2, 0.4],
            [0.75, 0.45, 0.0],
            [0.95, 0.95, 0.95]),
        rule, "fallback")
    self.assertFalse(primary["all_selection_runs_distinguishable"])
    self.assertTrue(fallback["all_selection_runs_distinguishable"])
    decision = proactive_stage3.choose_capacity_profile(primary, fallback)
    self.assertEqual("fallback", decision["recommended_profile"])
    self.assertEqual([0.1, 0.2, 0.4], decision["recommended_ratios"])

  def test_working_set_uses_train_validation_union(self):
    traces = {
        "w": {
            "train": [{"page": 1}, {"page": 1}, {"page": 2}],
            "validation": [{"page": 2}, {"page": 3}],
        }}
    result = proactive_stage3.working_set_summary(traces)[0]
    self.assertEqual(2, result["train_unique_pages"])
    self.assertEqual(2, result["validation_unique_pages"])
    self.assertEqual(3, result["train_validation_union_pages"])
    self.assertEqual(1, result["overlap_pages"])

  def test_empty_working_set_fails(self):
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.working_set_summary({
          "w": {"train": [], "validation": [{"page": 1}]}})

  def test_capacity_rounding_is_decimal_ceiling_and_never_zero(self):
    self.assertEqual(
        1, proactive_stage3.capacity_pages(1, 0.2)["dram_capacity_pages"])
    self.assertEqual(
        3, proactive_stage3.capacity_pages(13, 0.2)["dram_capacity_pages"])
    self.assertEqual(
        "2.6", proactive_stage3.capacity_pages(13, 0.2)[
            "raw_capacity_pages"])
    for ratio in (-0.1, 0, 1.1):
      with self.assertRaises(proactive_stage3.Stage3ContractError):
        proactive_stage3.capacity_pages(10, ratio)

  def test_nearest_rank_is_deterministic(self):
    values = [0, 1, 2, 3, 4]
    self.assertEqual(2, proactive_stage3.nearest_rank(values, 0.5))
    self.assertEqual(4, proactive_stage3.nearest_rank(values, 0.95))
    self.assertIsNone(proactive_stage3.nearest_rank([], 0.5))

  def test_burst_windows_exclude_tail_from_quantiles(self):
    flags = [True] * 100 + [False] * 50
    stats, rows = proactive_stage3.burst_statistics(flags, 100)
    self.assertEqual(1, stats["window_count"])
    self.assertEqual(100, stats["p95"])
    self.assertEqual(50, stats["tail_accesses"])
    self.assertFalse(rows[-1]["complete_window"])

  def test_burst_all_zero_and_all_enter(self):
    zero, _ = proactive_stage3.burst_statistics([False] * 100, 100)
    full, _ = proactive_stage3.burst_statistics([True] * 100, 100)
    self.assertEqual(0, zero["max"])
    self.assertEqual(100, full["max"])

  def test_watermark_generation_is_traceable_and_strict(self):
    stats = [
        {
            "split": "validation", "window_size": 100,
            "p50": 2, "p95": 4, "p99": 6,
        }]
    result = proactive_stage3.generate_watermark_candidates(stats)
    self.assertEqual(["small", "medium", "large"], [
        item["label"] for item in result])
    self.assertEqual([(1, 2), (2, 4), (3, 6)], [
        (item["F_low"], item["F_target"]) for item in result])

  def test_early_reuse_zero_denominator_is_null(self):
    rate, status = proactive_stage3._early_reuse({
        "early_reuse_count": 0, "proactive_demotions": 0})
    self.assertIsNone(rate)
    self.assertEqual("undefined_no_proactive_demotions", status)

  def test_watermark_tie_prefers_smaller_reserve(self):
    summaries = []
    candidates = []
    for label, low, target in (("small", 1, 2), ("large", 2, 4)):
      candidates.append({"label": label, "F_low": low, "F_target": target})
      summaries.append({
          "watermark_label": label,
          "all_legal": True,
          "all_invariants_passed": True,
          "macro_average": {
              "free_frame_exhaustion_count": 0,
              "emergency_demotions": 0,
              "early_reuse_rate": 0.1,
              "total_demotions": 10,
              "nvm_reads": 10,
              "nvm_writes": 0,
          },
          "worst_case": {
              "free_frame_exhaustion_count": 0,
              "emergency_demotions": 0,
          },
      })
    decision = proactive_stage3.select_watermark(summaries, candidates)
    self.assertEqual("small", decision["selected_label"])

  def test_bmax_tie_prefers_smaller_batch(self):
    summaries = []
    for value in (1, 2, 4):
      summaries.append({
          "b_max": value,
          "all_legal": True,
          "all_invariants_passed": True,
          "macro_average": {
              "free_frame_exhaustion_count": 0,
              "emergency_demotions": 0,
              "default_weighted_cost_per_access": 2.0,
              "nvm_writes": 1,
              "early_reuse_rate": 0.1,
              "number_of_proactive_rounds": 2,
          },
          "worst_case": {
              "free_frame_exhaustion_count": 0,
              "emergency_demotions": 0,
          },
      })
    self.assertEqual(
        1, proactive_stage3.select_bmax(summaries)["selected_b_max"])

  def test_synthetic_end_to_end_is_awaiting_real_inputs(self):
    traces = {
        "synthetic_locality": {
            "train": self.trace(),
            "validation": self.trace(100),
        }}
    output_root = tempfile.mkdtemp(prefix="capd-stage3-test-")
    self.addCleanup(shutil.rmtree, output_root, True)
    before = copy.deepcopy(traces)
    result = proactive_stage3.run_calibration(
        self.config, self.stage0, self.stage2, self.manifest(),
        traces, [], "synthetic-smoke", output_root, PROJECT_ROOT)
    self.assertEqual(before, traces)
    self.assertEqual(proactive_stage3.AWAITING_INPUTS, result["stage_status"])
    self.assertFalse(result["selection_decision"]["test_used"])
    self.assertFalse(result["selection_decision"]["capd_used_for_selection"])
    self.assertEqual(
        "pending", result["selection_decision"]["stage4_candidate_status"])
    self.assertFalse(
        result["selection_decision"]["proactive_calibration_executed"])
    self.assertEqual(
        proactive_stage3.CAPACITY_BLOCKED,
        result["selection_decision"]["capacity"]["status"])
    run_root = result["output_directory"]
    for name in (
        "resolved_config.json", "provenance.json", "input_manifest.json",
        "working_set_summary.json", "capacity_pressure_audit.json",
        "burst_statistics.json", "burst_windows.jsonl",
        "watermark_results.jsonl", "watermark_summary.csv",
        "bmax_results.jsonl", "bmax_summary.csv", "selection_decision.json",
        "freeze_candidate.json", "logs", "report.md"):
      self.assertTrue(os.path.exists(os.path.join(run_root, name)), name)
    with open(
        os.path.join(run_root, "freeze_candidate.json"),
        encoding="utf-8") as input_file:
      freeze = json.load(input_file)
    self.assertFalse(freeze["main_config_updated"])
    with self.assertRaises(proactive_stage3.Stage3ContractError):
      proactive_stage3.run_calibration(
          self.config, self.stage0, self.stage2, self.manifest(),
          traces, [], "synthetic-smoke", output_root, PROJECT_ROOT)

  def test_fallback_profile_drives_fresh_proactive_matrix(self):
    traces = {
        "synthetic_locality": {
            "train": [
                {"page": page, "rw": page % 2, "pc": page}
                for page in range(2400)],
            "validation": [
                {"page": page, "rw": page % 2, "pc": page}
                for page in range(600)],
        }}
    output_root = tempfile.mkdtemp(prefix="capd-stage3-fallback-")
    self.addCleanup(shutil.rmtree, output_root, True)
    result = proactive_stage3.run_calibration(
        self.config, self.stage0, self.stage2, self.manifest(),
        traces, [], "fallback-proactive", output_root, PROJECT_ROOT)
    decision = result["selection_decision"]
    self.assertEqual("fallback", decision["capacity"]["recommended_profile"])
    self.assertEqual(
        [0.1, 0.2, 0.4], decision["capacity"]["recommended_ratios"])
    self.assertTrue(decision["proactive_calibration_executed"])
    self.assertTrue(result["watermark_results"])
    self.assertTrue(result["bmax_results"])
    self.assertEqual(
        {0.1, 0.2, 0.4},
        {row["capacity_ratio"] for row in result["watermark_results"]})
    self.assertEqual(
        {0.1, 0.2, 0.4},
        {row["capacity_ratio"] for row in result["bmax_results"]})

  def test_real_manifest_stops_at_results_ready_not_verified(self):
    traces = {
        "synthetic_locality": {
            "train": self.trace(),
            "validation": self.trace(100),
        }}
    output_root = tempfile.mkdtemp(prefix="capd-stage3-real-gate-")
    self.addCleanup(shutil.rmtree, output_root, True)
    result = proactive_stage3.run_calibration(
        self.config, self.stage0, self.stage2,
        self.manifest(kind="real_train_fresh_validation_v2"),
        traces, [], "real-gate", output_root, PROJECT_ROOT)
    self.assertEqual(proactive_stage3.RESULTS_READY, result["stage_status"])
    self.assertNotEqual(proactive_stage3.VERIFIED, result["stage_status"])
    self.assertTrue(
        result["selection_decision"]["capacity"][
            "requires_user_confirmation"])

  def test_stage3_compact_replay_matches_full_replay_exactly(self):
    trace = self.trace()[:300]
    capacity = proactive_stage3.capacity_pages(40, 0.2)
    parameters = proactive_replay.ReplayParameters(
        policy_name="proactive_lru",
        dram_capacity_pages=capacity["dram_capacity_pages"],
        F_low=2, F_target=4, b_max=2, candidate_size_K=8,
        history_window_size=10, early_reuse_window=64)
    full = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(trace)
    compact = proactive_replay.ProactiveReplay(
        self.stage0, parameters, invariant_mode="boundary",
        record_details=False).run(
            trace, copy_trace=False, compact=True)
    self.assertEqual(full["summary"], compact["summary"])
    self.assertEqual(1, compact["full_invariant_checks"])
    self.assertEqual(
        min(len(item["candidate_pages"]) for item in full["rounds"]),
        compact["actual_candidate_count_min"])
    self.assertEqual(
        max(len(item["candidate_pages"]) for item in full["rounds"]),
        compact["actual_candidate_count_max"])
    self.assertEqual(
        [len(item["candidate_pages"]) for item in full["rounds"]],
        compact["actual_candidate_counts_by_round"])

  def test_lru_order_matches_legacy_list_operations(self):
    optimized = proactive_replay._LRUOrder()
    legacy = []
    for page in (1, 2, 3, 4):
      optimized.insert(0, page)
      legacy.insert(0, page)
    for page in (2, 4, 1, 3, 2):
      optimized.remove(page)
      optimized.insert(0, page)
      legacy.remove(page)
      legacy.insert(0, page)
      self.assertEqual(legacy, list(optimized))
      self.assertEqual(legacy[-1], optimized[-1])
      self.assertEqual(
          list(reversed(legacy[-3:])),
          optimized.tail_oldest_first(3))

  def test_interrupted_run_resumes_and_matches_clean_run(self):
    traces = {
        "synthetic_locality": {
            "train": self.trace()[:200],
            "validation": self.trace(100)[:200],
        }}
    output_root = tempfile.mkdtemp(prefix="capd-stage3-resume-")
    self.addCleanup(shutil.rmtree, output_root, True)
    original = proactive_stage3._replay_row
    calls = {"count": 0}

    def fail_after_three(*args, **kwargs):
      calls["count"] += 1
      if calls["count"] == 4:
        raise RuntimeError("injected interruption")
      return original(*args, **kwargs)

    proactive_stage3._replay_row = fail_after_three
    try:
      with self.assertRaisesRegex(RuntimeError, "injected interruption"):
        proactive_stage3.run_calibration(
            self.config, self.stage0, self.stage2, self.manifest(),
            traces, [], "resume-case", output_root, PROJECT_ROOT)
    finally:
      proactive_stage3._replay_row = original
    incomplete = os.path.join(
        output_root, "stage3", "resume-case.incomplete")
    self.assertTrue(os.path.isdir(incomplete))
    with open(
        os.path.join(incomplete, "run_state.json"),
        encoding="utf-8") as input_file:
      state = json.load(input_file)
    self.assertEqual("failed", state["status"])
    self.assertEqual(3, state["completed_replay_tasks"])

    resumed = proactive_stage3.run_calibration(
        self.config, self.stage0, self.stage2, self.manifest(),
        traces, [], "resume-case", output_root, PROJECT_ROOT, resume=True)
    clean = proactive_stage3.run_calibration(
        self.config, self.stage0, self.stage2, self.manifest(),
        traces, [], "clean-case", output_root, PROJECT_ROOT)
    self.assertEqual(
        clean["selection_decision"], resumed["selection_decision"])
    self.assertEqual(
        clean["watermark_results"], resumed["watermark_results"])
    self.assertEqual(clean["bmax_results"], resumed["bmax_results"])
    self.assertFalse(os.path.exists(incomplete))
    with open(
        os.path.join(resumed["output_directory"], "run_state.json"),
        encoding="utf-8") as input_file:
      final_state = json.load(input_file)
    self.assertEqual("completed", final_state["status"])
    self.assertGreater(final_state["completed_replay_tasks"], 3)


if __name__ == "__main__":
  unittest.main()
