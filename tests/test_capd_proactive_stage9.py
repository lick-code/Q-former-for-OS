# coding=utf-8
"""Stage-9 CPU-overhead contracts, metrics, memory, and failure fixtures."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage9 as stage9


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage9.json")
STAGE8_ROOT = os.path.join(
    ROOT, "outputs", "capd_proactive_stage8",
    "stage8-dual-track-20260804-r5-post-evidence-commit")


def _config():
  return stage9.load_json(CONFIG_PATH)


def _stage8_manifest():
  return stage9.load_json(os.path.join(STAGE8_ROOT, "job_manifest.json"))


def _capd_jobs():
  return [row for row in _stage8_manifest()["jobs"]
          if row["policy"] == "capd"]


def _sample(total_ns, b_t, kind="measured", repetition=0):
  phases = {
      "watermark_check_ns": 1,
      "candidate_construction_ns": 2,
      "feature_construction_ns": 3,
      "transformer_encoding_ns": 4,
      "candidate_scoring_ns": 5,
      "top_b_selection_ns": 6,
  }
  return dict(
      phases, sample_kind=kind, repetition_index=repetition,
      track="standard", workload="fixture", seed=42,
      D=22, F_low=1, F_target=3, b_max=2,
      trace_sha256="1" * 64, checkpoint_sha256="2" * 64,
      round_id=repetition + 1, b_t=b_t,
      total_round_latency_ns=total_ns,
      unattributed_framework_overhead_ns=total_ns - sum(phases.values()))


class Stage9ContractTest(unittest.TestCase):

  def test_frozen_config_is_exact(self):
    stage9.validate_config(_config())

  def test_result_schema_is_v2_and_track_aware(self):
    schema = stage9.load_json(os.path.join(
        ROOT, "configs", "finals",
        "capd_proactive_stage9_result_schema.json"))
    self.assertEqual("capd_proactive_stage9_result_schema_v2_0",
                     schema["schema_version"])
    self.assertEqual(stage9.CONTRACT_ID, schema["contract_id"])
    self.assertIn("stage8_compatibility_receipt.json",
                  schema["required_run_artifacts"])
    self.assertIn("logs/stage1_stage9_regression.log",
                  schema["required_run_artifacts"])
    identity = {"track", "workload", "seed", "D", "F_low", "F_target",
                "b_max", "trace_sha256", "checkpoint_sha256"}
    self.assertTrue(identity <= set(schema["raw_latency_required_fields"]))
    self.assertTrue(identity <= set(
        schema["quality_row_required_identity_fields"]))
    self.assertIn("tracks", schema["capacity_required_fields"])
    self.assertNotIn("capacity_ratio", schema["capacity_required_fields"])
    self.assertEqual(2, schema["verification_required"]["formal_b_max"])

  def test_result_schema_sha_is_pinned_and_tamper_is_rejected(self):
    config = _config()
    schema_path = os.path.join(ROOT, config["result_schema"])
    self.assertEqual(stage9.fingerprint_file(schema_path),
                     config.get("result_schema_sha256"))
    tampered = copy.deepcopy(config)
    tampered["result_schema_sha256"] = "0" * 64
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.validate_config(tampered)

  def test_v2_fields_and_formal_bmax_are_fail_closed(self):
    mutations = []
    for path, value in (
        (("frozen_controls", "b_max"), 4),
        (("capd", "history_H"), 21),
        (("capd", "best_seed_selection_allowed"), True),
        (("measurement", "device"), "cuda:0"),
        (("measurement", "batch_size_rounds"), 2),
        (("measurement", "warmup_rounds"), 0),
        (("measurement", "formal_repetitions"), 0),
        (("measurement_matrix", "quality_job_count"), 54),
        (("measurement_matrix", "identity_fields"), ["workload", "seed"]),
        (("measurement_matrix", "expected_zero_round_job_keys"), []),
        (("sensitivity", "b_max_values"), [1, 4]),
        (("perf", "expected_snapshot_count"), 9),
        (("test_policy", "used_for_parameter_selection"), True),
    ):
      item = copy.deepcopy(_config())
      target = item
      for key in path[:-1]:
        target = target[key]
      target[path[-1]] = value
      mutations.append(item)
    for item in mutations:
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.validate_config(item)

  def test_measurement_matrix_is_stage8_v2_track_aware(self):
    matrix = _config()["measurement_matrix"]
    self.assertEqual(["track", "workload", "seed"],
                     matrix["identity_fields"])
    self.assertEqual(
        "stage8_v2_capd_job_manifests_plan_job", matrix["source"])
    self.assertEqual(30, matrix["jobs_per_b_max"])
    self.assertEqual(90, matrix["quality_job_count"])
    self.assertEqual(30, matrix["formal_instrumentation_job_count"])
    self.assertEqual(27, matrix["expected_active_round_jobs_per_b_max"])
    self.assertEqual(3, matrix["expected_zero_round_jobs_per_b_max"])
    self.assertEqual([
        "standard|fluidanimate|3136859",
        "standard|fluidanimate|42",
        "standard|fluidanimate|2026",
    ], matrix["expected_zero_round_job_keys"])
    self.assertEqual(6, matrix["unique_workload_capacity_count"])

  def test_stage8_v2_entry_accepts_without_mutating_stage8_gate(self):
    valid = {
        "contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "status": "stage8_sync_replay_verified",
        "formal_job_count": 80,
        "standard_job_count": 48,
        "pressure_job_count": 32,
        "track_workload_cell_count": 10,
        "fairness": "passed",
        "job_results_verified": True,
        "statistics_verified": True,
        "test_used_for_parameter_selection": False,
        "frozen_parameters_changed": False,
    }
    stage9.validate_stage8_verification(valid)
    self.assertNotIn("stage9_entry_gate", valid)
    for key, value in (
        ("contract_id", "CAPD-PROACTIVE-STAGE8-1.0"),
        ("status", "stage8_not_verified"),
        ("formal_job_count", 144),
        ("standard_job_count", 47),
        ("pressure_job_count", 31),
        ("track_workload_cell_count", 9),
        ("fairness", "failed"),
        ("job_results_verified", False),
        ("statistics_verified", False),
        ("test_used_for_parameter_selection", True),
        ("frozen_parameters_changed", True),
    ):
      bad = dict(valid)
      bad[key] = value
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.validate_stage8_verification(bad)
    for key in tuple(valid):
      bad = dict(valid)
      bad.pop(key)
      with self.subTest(missing=key):
        with self.assertRaises(stage9.Stage9ContractError):
          stage9.validate_stage8_verification(bad)

  def test_stage8_r5_sha_chain_and_30_capd_plan_jobs_are_audited(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    entry = runner._audit_stage8_entry(
        _config(), ROOT, verify_payloads=False)
    receipt = entry["compatibility_receipt"]
    self.assertEqual("satisfied", receipt["stage9_entry_gate"])
    self.assertEqual(80, receipt["formal_job_count"])
    self.assertEqual(48, receipt["standard_job_count"])
    self.assertEqual(32, receipt["pressure_job_count"])
    self.assertEqual(30, receipt["capd_job_count"])
    self.assertEqual(30, len(entry["capd_jobs"]))
    self.assertEqual(30, len(entry["capd_job_manifests"]))
    self.assertTrue(receipt["stage8_artifacts_read_only"])
    self.assertTrue(receipt["stage4_sha_chain_verified"])
    self.assertTrue(receipt["stage8_run_state_verified"])

  @unittest.skipUnless(os.name == "nt", "Windows path adaptation regression")
  def test_stage8_r5_resolves_all_three_linux_checkpoint_paths(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    entry = runner._audit_stage8_entry(_config(), ROOT, verify_payloads=False)
    bindings = entry["authority"]["checkpoint_bindings"]
    self.assertEqual({3136859, 42, 2026}, set(bindings))
    for row in bindings.values():
      resolved = runner._resolve_recorded_file(
          ROOT, row["path"], row["sha256"])
      self.assertTrue(os.path.isfile(resolved))
      self.assertEqual(row["sha256"],
                       stage9.fingerprint_file(resolved))

  def test_stage8_r5_outer_sha_mismatch_is_rejected(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    config = copy.deepcopy(_config())
    config["stage8_authority"]["verification"]["sha256"] = "0" * 64
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_stage8_entry(config, ROOT, verify_payloads=False)

  def test_track_workload_seed_identity_prevents_cross_track_collision(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    entry = {"capd_jobs": _capd_jobs()}
    jobs = runner._measurement_jobs(_config(), entry)
    identities = {(row["track"], row["workload"], row["seed"])
                  for row in jobs}
    self.assertEqual(30, len(jobs))
    self.assertEqual(30, len(identities))
    self.assertIn(("standard", "canneal", 42), identities)
    self.assertIn(("pressure", "canneal", 42), identities)

  def test_plan_job_controls_trace_and_checkpoint_are_forwarded(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    jobs = _capd_jobs()
    by_workload = {}
    for job in jobs:
      by_workload.setdefault(job["workload"], job)
    expected = {
        "canneal": (120, 6, 16),
        "streamcluster_pressure": (22, 1, 3),
        "dedup_pressure": (21, 1, 3),
        "blackscholes": (8, 1, 2),
        "swaptions": (8, 1, 2),
        "fluidanimate": (22, 1, 3),
    }
    for workload, controls in expected.items():
      job = by_workload[workload]
      params = runner._replay_parameters(job, b_max=4)
      self.assertEqual(controls, (
          params.dram_capacity_pages, params.F_low, params.F_target))
      self.assertEqual(4, params.b_max)
      self.assertEqual(job["K"], params.candidate_size_K)
      self.assertEqual(job["history_H"], params.history_window_size)
      self.assertNotEqual((8, 16), (params.F_low, params.F_target))
      self.assertEqual(job["trace_sha256"],
                       runner._job_context(job, 4)["trace_sha256"])
      self.assertEqual(job["checkpoint"]["sha256"],
                       runner._job_context(job, 4)["checkpoint_sha256"])

  def test_raw_quality_perf_and_audit_identity_tamper_is_rejected(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    jobs = _capd_jobs()
    rows = [runner._job_context(job, 2) for job in jobs]
    runner._audit_record_identities(rows, jobs, allowed_b_max=(2,))
    bad = copy.deepcopy(rows)
    bad[0]["F_low"] += 1
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_record_identities(bad, jobs, allowed_b_max=(2,))

  def test_standard_and_pressure_trace_bindings_remain_distinct(self):
    jobs = _capd_jobs()
    standard = next(row for row in jobs if row["track"] == "standard" and
                    row["workload"] == "canneal")
    pressure = next(row for row in jobs if row["track"] == "pressure" and
                    row["workload"] == "canneal")
    self.assertNotEqual(standard["trace_path"], pressure["trace_path"])
    self.assertNotEqual(standard["trace_sha256"], pressure["trace_sha256"])

  def test_sha_binding_rejects_tamper(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
      path = os.path.join(directory, "authority.json")
      stage9.write_json_atomic(path, {"ok": True})
      digest = stage9.fingerprint_file(path)
      stage9.verify_file_binding(path, digest, "fixture")
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.verify_file_binding(path, "0" * 64, "fixture")

  def test_cpu_device_is_mandatory(self):
    self.assertEqual("cpu", stage9.require_cpu_device("cpu"))
    for device in ("cuda", "cuda:0", "mps"):
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.require_cpu_device(device)

  def test_eval_and_no_grad_contract(self):
    class Module(object):
      training = False
    stage9.assert_eval_mode([Module(), Module()])
    bad = Module()
    bad.training = True
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.assert_eval_mode([bad])
    stage9.assert_grad_disabled(False)
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.assert_grad_disabled(True)

  def test_runtime_record_requires_requested_and_actual_affinity(self):
    value = stage9.runtime_binding(
        requested_affinity=[2, 3], actual_affinity=[2, 3],
        cpu_threads=2, torch_intra_op_threads=2,
        torch_inter_op_threads=1, omp_num_threads="2",
        mkl_num_threads="2", warmup_rounds=20, formal_repetitions=3)
    self.assertEqual([2, 3], value["actual_affinity"])
    bad = dict(value, actual_affinity=[2, 4])
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.validate_runtime_binding(bad)

  def test_run_id_isolated_and_failed_run_cannot_resume(self):
    with tempfile.TemporaryDirectory() as directory:
      first = stage9.prepare_new_run(directory, "run-a")
      self.assertTrue(first.endswith("run-a"))
      stage9.write_run_state(first, stage9.NOT_VERIFIED, ["preflight"],
                             failure={"step": "measure", "reason": "x"})
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.prepare_new_run(directory, "run-a")
      second = stage9.prepare_new_run(directory, "run-b")
      self.assertNotEqual(first, second)

  def test_git_identity_ignores_stage9_outputs_but_detects_source_changes(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    with tempfile.TemporaryDirectory() as directory:
      subprocess.check_call(
          ["git", "init", "-q"], cwd=directory)
      source = os.path.join(directory, "source.py")
      with open(source, "w", encoding="utf-8") as handle:
        handle.write("VALUE = 1\n")
      subprocess.check_call(["git", "add", "source.py"], cwd=directory)
      subprocess.check_call(
          ["git", "-c", "user.name=Stage9 Test", "-c",
           "user.email=stage9-test@example.invalid", "commit", "-q", "-m",
           "baseline"], cwd=directory)

      clean = runner._git_state(directory)
      self.assertFalse(clean["dirty_worktree"])
      run_root = os.path.join(
          directory, "outputs", "capd_proactive_stage9", "run-r1")
      os.makedirs(run_root)
      with open(os.path.join(run_root, "run_state.json"), "w",
                encoding="utf-8") as handle:
        json.dump({"status": "running"}, handle)
      self.assertEqual(clean, runner._git_state(directory))

      with open(source, "w", encoding="utf-8") as handle:
        handle.write("VALUE = 2\n")
      self.assertTrue(runner._git_state(directory)["dirty_worktree"])

  def test_identity_difference_reports_the_exact_json_path(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    differences = runner._identity_differences(
        {"git": {"commit": "abc", "dirty_worktree": False}},
        {"git": {"commit": "abc", "dirty_worktree": True}})
    self.assertEqual(
        ["git.dirty_worktree: False -> True"], differences)

  def test_server_checks_perf_permission_before_starting_expensive_run(self):
    path = os.path.join(
        ROOT, "scripts", "validate_capd_proactive_stage9_server.sh")
    with open(path, "r", encoding="utf-8") as handle:
      shell = handle.read()
    probe = shell.index("pre-run perf hardware counter")
    preflight = shell.index('CURRENT_STEP="preflight"')
    measure = shell.index('CURRENT_STEP="latency_quality_memory"')
    self.assertLess(probe, preflight)
    self.assertLess(probe, measure)
    self.assertIn("kernel.perf_event_paranoid=0", shell)
    self.assertIn("<not supported>|<not counted>", shell)


class Stage9LatencyAndCycleTest(unittest.TestCase):

  @staticmethod
  def _runner_module():
    path = os.path.join(ROOT, "scripts", "run_capd_proactive_stage9.py")
    spec = importlib.util.spec_from_file_location("stage9_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

  def test_empty_and_single_sample_statistics(self):
    self.assertEqual(
        {"count": 0, "mean": None, "p50": None, "p95": None,
         "p99": None, "minimum": None, "maximum": None},
        stage9.distribution([]))
    one = stage9.distribution([7])
    self.assertEqual(7, one["mean"])
    self.assertEqual(7, one["p50"])
    self.assertEqual(7, one["p95"])
    self.assertEqual(7, one["p99"])

  def test_warmup_is_never_in_formal_statistics(self):
    samples = [_sample(999999, 4, "warmup"), _sample(1000, 4, "measured", 1)]
    value = stage9.summarize_latency_samples(samples)
    self.assertEqual(1, value["measured_sample_count"])
    self.assertEqual(1, value["warmup_sample_count"])
    self.assertEqual(1000, value["stages"]["total_round_latency_ns"]["mean"])

  def test_mean_p50_p95_p99_and_raw_summary_consistency(self):
    samples = [_sample(value, 4, repetition=index)
               for index, value in enumerate((100, 200, 300, 400, 500))]
    summary = stage9.summarize_latency_samples(samples)
    expected = stage9.distribution([100, 200, 300, 400, 500])
    self.assertEqual(expected,
                     summary["stages"]["total_round_latency_ns"])
    stage9.audit_latency_summary(samples, summary)
    broken = copy.deepcopy(summary)
    broken["stages"]["total_round_latency_ns"]["mean"] += 1
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.audit_latency_summary(samples, broken)

  def test_zero_bt_is_counted_and_excluded_from_page_amortization(self):
    samples = [_sample(1000, 0), _sample(1200, 4, repetition=1)]
    value = stage9.throughput_from_samples(samples)
    self.assertEqual(1, value["b_t_zero_count"])
    self.assertEqual(1, value["amortized_sample_count"])
    self.assertEqual(300.0, value["amortized_latency_ns_per_page"]["mean"])
    self.assertAlmostEqual(2e9 / 2200.0, value["rounds_per_second"])
    self.assertAlmostEqual(4e9 / 2200.0, value["demoted_pages_per_second"])

  def test_cycles_per_round_and_page_use_real_counter_only(self):
    value = stage9.cycles_per_unit(
        cycles=9000, measured_rounds=3, measured_pages=6,
        counter_source="linux_perf_hardware")
    self.assertEqual(3000.0, value["cpu_cycles_per_round"])
    self.assertEqual(1500.0, value["cpu_cycles_per_demoted_page"])
    with self.assertRaises(stage9.Stage9ContractError):
      stage9.cycles_per_unit(9000, 3, 6, "wall_time_times_frequency")
    zero = stage9.cycles_per_unit(0, 0, 0, "linux_perf_hardware")
    self.assertIsNone(zero["cpu_cycles_per_round"])
    self.assertIsNone(zero["cpu_cycles_per_demoted_page"])

  def test_perf_parser_preserves_unavailable_reason(self):
    raw = (
        "1000;cycles;100.00;100.00;;\n"
        "2000;instructions;100.00;100.00;;\n"
        "<not supported>;task-clock;;;;\n")
    value = stage9.parse_perf_stat(raw, delimiter=";")
    self.assertEqual(1000, value["events"]["cycles"]["value"])
    self.assertEqual(2000, value["events"]["instructions"]["value"])
    self.assertEqual("not_supported",
                     value["events"]["task-clock"]["status"])
    self.assertFalse(value["required_events_verified"])

  def test_measurement_completeness_rejects_zero_latency_suite(self):
    runner = self._runner_module()
    quality = []
    accumulators = {}
    zero_keys = {
        ("standard", "fluidanimate", 3136859),
        ("standard", "fluidanimate", 42),
        ("standard", "fluidanimate", 2026),
    }
    identities = [(job["track"], job["workload"], job["seed"])
                  for job in _capd_jobs()]
    for b_max in (1, 2, 4):
      quality.extend({
          "b_max": b_max, "track": track, "workload": workload,
          "seed": seed,
          "number_of_proactive_rounds": (
              0 if (track, workload, seed) in zero_keys else 30)}
          for track, workload, seed in identities)
      value = runner._LatencyAccumulator()
      value.warmup = 27 * 20
      value.measured = 27 * (30 - 20) * 3
      value.pages = value.measured
      for track, workload, seed in identities:
        if (track, workload, seed) not in zero_keys:
          value.sample_counts_by_cell[(
              track, workload, seed, "warmup")] = 20
          value.sample_counts_by_cell[(
              track, workload, seed, "measured")] = 30
      accumulators[str(b_max)] = value
    runner._audit_measurement_completeness(
        accumulators, quality, _config())
    accumulators["4"].measured = 0
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_measurement_completeness(
          accumulators, quality, _config())

  def test_perf_scope_requires_exact_active_and_zero_cells(self):
    runner = self._runner_module()
    config = _config()
    zero = [{"track": "standard", "workload": "fluidanimate", "seed": seed}
            for seed in (3136859, 42, 2026)]
    zero_keys = {(row["track"], row["workload"], row["seed"])
                 for row in zero}
    active = [{"track": row["track"], "workload": row["workload"],
               "seed": row["seed"]} for row in _capd_jobs()
              if (row["track"], row["workload"], row["seed"])
              not in zero_keys]
    scope = {
        "snapshot_count": 27,
        "measured_job_ids": ["active-{}".format(i) for i in range(27)],
        "measured_cells": active,
        "zero_round_job_count": 3,
        "zero_round_job_ids": ["zero-{}".format(i) for i in range(3)],
        "zero_round_cells": zero,
        "measured_rounds": 5400,
        "measured_demoted_pages": 7200}
    runner._audit_perf_scope_counts(scope, config)
    scope["measured_cells"] = active[:-1]
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_perf_scope_counts(scope, config)

  def test_verify_reparses_raw_perf_and_matches_standalone_scope(self):
    runner = self._runner_module()
    config = _config()
    jobs = _capd_jobs()
    zero_keys = set(config["measurement_matrix"][
        "expected_zero_round_job_keys"])
    active = [job for job in jobs if "{}|{}|{}".format(
        job["track"], job["workload"], job["seed"]) not in zero_keys]
    zero = [job for job in jobs if job not in active]
    repetitions = config["perf"]["repetitions_per_snapshot"]
    scope = {
        "schema_version": "capd_proactive_stage9_perf_scope_v2_0",
        "snapshot_count": len(active),
        "measured_job_ids": [job["job_id"] for job in active],
        "measured_cells": [runner._job_context(job, 2) for job in active],
        "zero_round_job_count": len(zero),
        "zero_round_job_ids": [job["job_id"] for job in zero],
        "zero_round_cells": [runner._job_context(job, 2) for job in zero],
        "repetitions_per_snapshot": repetitions,
        "measured_rounds": len(active) * repetitions,
        "measured_demoted_pages": len(active) * repetitions * 2,
        "formal_b_max": 2, "device": "cpu",
        "control": config["perf"]["control"],
        "snapshot_rule": config["perf"]["snapshot_rule"],
        "model_load_and_warmup_excluded": True,
        "test_used_for_parameter_selection": False,
    }
    raw = "\n".join((
        "54000;;cycles", "108000;;instructions", "12.5;;task-clock",
        "2;;context-switches", "0;;cpu-migrations", "3;;page-faults"))
    parsed = stage9.parse_perf_stat(raw, delimiter=";")
    parsed["counter_source"] = "linux_perf_hardware"
    parsed["scope_counts"] = copy.deepcopy(scope)
    parsed["derived"] = stage9.cycles_per_unit(
        54000, scope["measured_rounds"], scope["measured_demoted_pages"],
        "linux_perf_hardware")
    runner._verify_perf_evidence(raw, parsed, scope, config, jobs)

    with self.assertRaises(stage9.Stage9ContractError):
      runner._verify_perf_evidence(
          raw.replace("54000", "54001"), parsed, scope, config, jobs)
    bad_scope = copy.deepcopy(scope)
    bad_scope["measured_demoted_pages"] += 1
    with self.assertRaises(stage9.Stage9ContractError):
      runner._verify_perf_evidence(raw, parsed, bad_scope, config, jobs)

  def test_quality_summary_keeps_track_and_ten_track_workload_units(self):
    runner = self._runner_module()
    rows = []
    for job in _capd_jobs():
      rows.append({
          "track": job["track"], "workload": job["workload"],
          "seed": job["seed"], "b_max": 2,
          "weighted_cost": 100 + job["seed"] % 3,
          "early_reuse_rate_64": 0.1,
          "early_reuse_rate_256": 0.2,
          "early_reuse_rate_1024": 0.3,
          "number_of_proactive_rounds": (
              0 if job["track"] == "standard" and
              job["workload"] == "fluidanimate" else 30)})
    summary = runner._aggregate_quality(rows)
    formal = summary["by_b_max"]["2"]
    self.assertEqual({"standard", "pressure"}, set(formal["by_track"]))
    self.assertEqual(10, len(formal["by_track_workload"]))
    self.assertEqual(18, formal["by_track"]["standard"]["cell_count"])
    self.assertEqual(12, formal["by_track"]["pressure"]["cell_count"])

  def test_raw_latency_schema_contains_full_v2_identity(self):
    runner = self._runner_module()
    required = {
        "track", "workload", "seed", "D", "F_low", "F_target", "b_max",
        "trace_sha256", "checkpoint_sha256"}
    self.assertTrue(required <= set(runner.RAW_FIELDS))
    self.assertNotIn("capacity_ratio", runner.RAW_FIELDS)

  def test_model_memory_keeps_max_runtime_instead_of_last_zero_cell(self):
    runner = self._runner_module()
    target = {}
    first = {
        "model_parameters": {"all_model_parameters_bytes": 100},
        "model_buffers": {"bytes": 10},
        "runtime_tensors": {"candidate_tensor_bytes": 64,
                            "measurement_method": "exact"}}
    last_zero = {
        "model_parameters": {"all_model_parameters_bytes": 100},
        "model_buffers": {"bytes": 10},
        "runtime_tensors": {}}
    runner._merge_model_memory_observation(target, 42, first)
    runner._merge_model_memory_observation(target, 42, last_zero)
    self.assertEqual(64, target["42"]["runtime_tensors"][
        "candidate_tensor_bytes"])


class Stage9MemoryAndSemanticsTest(unittest.TestCase):

  def test_parameter_bytes_and_embedding_split_are_exact(self):
    class Tensor(object):
      def __init__(self, count, width):
        self.count, self.width = count, width
      def numel(self): return self.count
      def element_size(self): return self.width
    named = [
        ("feature_embedder._address_embedder._embedding.weight", Tensor(10, 4)),
        ("feature_embedder._pc_embedder._embedding.weight", Tensor(20, 4)),
        ("extractor._transformer_encoder.layers.0.weight", Tensor(30, 4)),
        ("scorer._scoring_mlp.0.weight", Tensor(40, 4)),
    ]
    value = stage9.parameter_memory_breakdown(named)
    self.assertEqual(400, value["all_model_parameters_bytes"])
    self.assertEqual(40, value["page_embedding_parameter_bytes"])
    self.assertEqual(80, value["pc_embedding_parameter_bytes"])
    self.assertEqual(120, value["transformer_parameter_bytes"])
    self.assertEqual(160, value["other_parameter_bytes"])

  def test_metadata_linear_charge_and_4k_round_up(self):
    self.assertEqual(6400, stage9.metadata_memory_bytes(100, 64))
    self.assertEqual(0, stage9.management_pages(0, 4096))
    self.assertEqual(1, stage9.management_pages(1, 4096))
    self.assertEqual(2, stage9.management_pages(4097, 4096))
    rows = stage9.capacity_overhead_rows(
        management_fixed_bytes=4096, metadata_bytes_per_page=64,
        workload_capacities=[{"workload": "w", "tracks": ["standard"],
                              "dram_pages": 100}], page_size_bytes=4096)
    self.assertEqual(97, rows[0]["capd_effective_dram_pages"])
    self.assertEqual(3, rows[0]["management_pages"])
    self.assertAlmostEqual(3.0, rows[0]["capacity_overhead_percent"])
    self.assertEqual("standard", rows[0]["tracks"])

  def test_capacity_overhead_uses_six_unique_workload_controls(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    capacities = runner._capacity_workload_rows(_capd_jobs())
    self.assertEqual(6, len(capacities))
    self.assertEqual(6, len({row["workload"] for row in capacities}))
    canneal = next(row for row in capacities if row["workload"] == "canneal")
    fluid = next(row for row in capacities
                 if row["workload"] == "fluidanimate")
    self.assertEqual(120, canneal["dram_pages"])
    self.assertEqual(["pressure", "standard"], canneal["tracks"])
    self.assertEqual(22, fluid["dram_pages"])
    self.assertEqual(["standard"], fluid["tracks"])

  def test_capacity_csv_is_recomputed_from_memory_breakdown(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    memory = {"management_fixed_bytes": 4096,
              "metadata_bytes_per_page": 64}
    rows = stage9.capacity_overhead_rows(
        memory["management_fixed_bytes"], memory["metadata_bytes_per_page"],
        runner._capacity_workload_rows(_capd_jobs()), 4096)
    csv_rows = [{key: str(value) for key, value in row.items()}
                for row in rows]
    runner._verify_capacity_rows(memory, csv_rows, _capd_jobs(), _config())
    tampered = copy.deepcopy(csv_rows)
    tampered[0]["management_memory_bytes"] = "0"
    with self.assertRaises(stage9.Stage9ContractError):
      runner._verify_capacity_rows(memory, tampered, _capd_jobs(), _config())

  def test_regression_receipt_rechecks_confined_log_and_sha(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    with tempfile.TemporaryDirectory(dir=ROOT) as project_root:
      run_root = os.path.join(project_root, "outputs", "stage9", "run")
      log_path = os.path.join(run_root, "logs", "regression.log")
      os.makedirs(os.path.dirname(log_path))
      with open(log_path, "w", encoding="utf-8") as handle:
        handle.write("Ran 450 tests in 1.0s\n\nOK\n")
      receipt = {
          "schema_version": "capd_proactive_stage9_server_test_receipt_v2_0",
          "contract_id": stage9.CONTRACT_ID,
          "status": "passed", "test_count": 450, "minimum_required": 450,
          "log_path": os.path.relpath(log_path, project_root),
          "log_sha256": stage9.fingerprint_file(log_path)}
      runner._verify_regression_receipt(
          run_root, project_root, receipt, minimum=450)
      bad = copy.deepcopy(receipt)
      bad["log_sha256"] = "0" * 64
      with self.assertRaises(stage9.Stage9ContractError):
        runner._verify_regression_receipt(
            run_root, project_root, bad, minimum=450)
      with open(log_path, "w", encoding="utf-8") as handle:
        handle.write("Ran 450 tests in 1.0s\n\nFAILED (failures=1)\n")
      with self.assertRaises(stage9.Stage9ContractError):
        runner._verify_regression_receipt(
            run_root, project_root, receipt, minimum=450)

  def test_summary_v2_metadata_tamper_is_rejected(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    config = _config()
    applicability = config["measurement_matrix"]["latency_applicability"]
    latency = {
        "schema_version": "capd_proactive_stage9_latency_suite_v2_0",
        "formal_b_max": 2, "sensitivity_purpose": "analysis_only_not_selection",
        "applicability": applicability}
    throughput = {
        "schema_version": "capd_proactive_stage9_throughput_suite_v2_0",
        "formal_b_max": 2, "sensitivity_purpose": "analysis_only_not_selection",
        "applicability": applicability}
    quality = {
        "schema_version": "capd_proactive_stage9_quality_v2_0",
        "formal_b_max": 2, "purpose": "analysis_only_not_selection",
        "test_used_for_parameter_selection": False}
    perf_scope = {
        "schema_version": "capd_proactive_stage9_perf_scope_v2_0",
        "formal_b_max": 2, "device": "cpu",
        "control": config["perf"]["control"],
        "snapshot_rule": config["perf"]["snapshot_rule"],
        "repetitions_per_snapshot": config["perf"]["repetitions_per_snapshot"],
        "model_load_and_warmup_excluded": True,
        "test_used_for_parameter_selection": False}
    runner._verify_summary_metadata(
        latency, throughput, quality, perf_scope, config)
    bad = copy.deepcopy(quality)
    bad["formal_b_max"] = 4
    with self.assertRaises(stage9.Stage9ContractError):
      runner._verify_summary_metadata(
          latency, throughput, bad, perf_scope, config)

  def test_peak_rss_fields_have_bytes_and_mib(self):
    value = stage9.rss_breakdown(1000, 5096)
    self.assertEqual(4096, value["stage9_incremental_peak_rss_bytes"])
    self.assertAlmostEqual(5096 / 1048576.0,
                           value["total_peak_rss_mib"])
    self.assertEqual("os_observed_rss", value["measurement_method"])

  def test_instrumentation_preserves_top_b_and_state_trajectory(self):
    stage0 = finals_config.load_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage0.json"))
    parameters = proactive_replay.ReplayParameters(
        policy_name="proactive_lru", dram_capacity_pages=20,
        F_low=1, F_target=3, b_max=2, candidate_size_K=8,
        history_window_size=20, early_reuse_window=64)
    trace = [{"page": index % 29, "rw": int(index % 7 == 0),
              "pc": index % 5} for index in range(160)]
    plain = proactive_replay.ProactiveReplay(
        stage0, parameters,
        ranking_policy=proactive_replay.ProactiveLRURanking(),
        measure_decision_latency=False, record_details=True,
        exclude_current_entering_page=True)
    timed = stage9.InstrumentedProactiveReplay(
        stage0, parameters,
        ranking_policy=proactive_replay.ProactiveLRURanking(),
        warmup_rounds=2, formal_repetitions=2,
        exclude_current_entering_page=True)
    for replay in (plain, timed):
      replay.register_backing_pages(item["page"] for item in trace)
      for access in trace:
        replay.process_access(access)
    one, two = plain.result(), timed.result()
    self.assertEqual(one["state"], two["state"])
    self.assertEqual([row["selected_pages"] for row in one["rounds"]],
                     [row["selected_pages"] for row in two["rounds"]])
    self.assertGreater(len(timed.stage9_latency_samples), 0)
    self.assertTrue(all(row["sample_kind"] in ("warmup", "measured")
                        for row in timed.stage9_latency_samples))

  def test_test_data_cannot_select_parameter_checkpoint_or_formal_bmax(self):
    policy = _config()["test_policy"]
    self.assertFalse(policy["used_for_parameter_selection"])
    self.assertFalse(policy["checkpoint_selection_allowed"])
    self.assertFalse(policy["formal_b_max_selection_allowed"])
    self.assertEqual(2, _config()["frozen_controls"]["b_max"])
    self.assertEqual(2, _config()["sensitivity"]["formal_b_max"])
    self.assertEqual("analysis_only_not_selection",
                     _config()["sensitivity"]["purpose"])

  def test_windows_import_is_supported_but_formal_measurement_is_linux_only(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    if os.name == "nt":
      with self.assertRaises(stage9.Stage9ContractError):
        runner._configure_cpu_runtime(_config())


if __name__ == "__main__":
  unittest.main()
