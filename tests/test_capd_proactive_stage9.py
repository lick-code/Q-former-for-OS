# coding=utf-8
"""Stage-9 CPU-overhead contracts, metrics, memory, and failure fixtures."""

from __future__ import annotations

import copy
import importlib.util
import os
import tempfile
import unittest

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage9 as stage9


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage9.json")


def _config():
  return stage9.load_json(CONFIG_PATH)


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
      workload="fixture", capacity_ratio="0.40", seed=42, b_max=4,
      round_id=repetition + 1, b_t=b_t,
      total_round_latency_ns=total_ns,
      unattributed_framework_overhead_ns=total_ns - sum(phases.values()))


class Stage9ContractTest(unittest.TestCase):

  def test_frozen_config_is_exact(self):
    stage9.validate_config(_config())

  def test_frozen_fields_and_formal_bmax_are_fail_closed(self):
    mutations = []
    for path, value in (
        (("frozen_controls", "F_low"), 7),
        (("frozen_controls", "b_max"), 2),
        (("capd", "history_H"), 21),
        (("capd", "best_seed_selection_allowed"), True),
        (("measurement", "device"), "cuda:0"),
        (("measurement", "batch_size_rounds"), 2),
        (("measurement", "warmup_rounds"), 0),
        (("measurement", "formal_repetitions"), 0),
        (("measurement_matrix", "capacity_ratios"), ["0.40"]),
        (("measurement_matrix", "expected_active_round_workloads"), []),
        (("sensitivity", "b_max_values"), [1, 4]),
        (("perf", "expected_snapshot_count"), 18),
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

  def test_measurement_uses_stage7_prefrozen_main_default_capacity(self):
    matrix = _config()["measurement_matrix"]
    self.assertEqual(["0.20"], matrix["capacity_ratios"])
    self.assertEqual(
        "stage7_prefrozen_main_default_capacity_not_stage8_test_selection",
        matrix["selection_basis"])
    self.assertEqual(9, matrix["expected_active_round_jobs_per_b_max"])
    self.assertEqual(9, matrix["expected_zero_round_jobs_per_b_max"])
    self.assertEqual(
        ["canneal", "dedup_pressure", "blackscholes"],
        matrix["expected_active_round_workloads"])

  def test_stage7_main_default_capacity_authority_is_verified(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    capacity = stage9.load_json(os.path.join(
        ROOT, "outputs", "capd_proactive_stage7", "stage7-server-suite-r1",
        "capacity_matrix.json"))
    authority = {
        "capacity": capacity,
        "lock": {"workloads": [
            {"workload": workload} for workload in (
                "canneal", "streamcluster_pressure", "dedup_pressure",
                "blackscholes", "swaptions", "fluidanimate")]}}
    runner._audit_main_default_capacity(_config(), authority)
    capacity["default_ratio"] = "0.40"
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_main_default_capacity(_config(), authority)

  def test_stage7_capacity_rows_are_stage9_owned_and_fail_closed(self):
    runner = Stage9LatencyAndCycleTest._runner_module()
    rows = [{"workload": "fixture", "ratio": "0.20"}]
    self.assertEqual(rows, runner._stage7_capacity_rows({"rows": rows}))
    self.assertEqual(rows, runner._stage7_capacity_rows(rows))
    for invalid in ({}, {"rows": None}, None):
      with self.subTest(invalid=invalid):
        with self.assertRaises(stage9.Stage9ContractError):
          runner._stage7_capacity_rows(invalid)
    with open(runner.__file__, "r", encoding="utf-8") as handle:
      self.assertNotIn("stage8_contract._capacity_rows", handle.read())

  def test_stage8_entry_gate_rejects_every_invalid_authority_field(self):
    valid = {
        "status": "stage8_sync_replay_verified",
        "stage9_entry_gate": "satisfied",
        "formal_job_count": 144,
        "test_used_for_parameter_selection": False,
        "frozen_parameters_changed": False,
    }
    stage9.validate_stage8_verification(valid)
    for key, value in (
        ("status", "stage8_not_verified"),
        ("stage9_entry_gate", "not_satisfied"),
        ("formal_job_count", 143),
        ("test_used_for_parameter_selection", True),
        ("frozen_parameters_changed", True),
    ):
      bad = dict(valid)
      bad[key] = value
      with self.assertRaises(stage9.Stage9ContractError):
        stage9.validate_stage8_verification(bad)

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
    for b_max in (1, 2, 4):
      quality.extend([
          {"b_max": b_max, "workload": workload, "seed": seed,
           "number_of_proactive_rounds": 30}
          for workload in ("canneal", "dedup_pressure", "blackscholes")
          for seed in (3136859, 42, 2026)])
      quality.extend([
          {"b_max": b_max, "workload": workload, "seed": seed,
           "number_of_proactive_rounds": 0}
          for workload in ("streamcluster_pressure", "swaptions",
                           "fluidanimate")
          for seed in (3136859, 42, 2026)])
      value = runner._LatencyAccumulator()
      value.warmup = 9 * 20
      value.measured = 9 * (30 - 20) * 3
      value.pages = value.measured
      for workload in ("canneal", "dedup_pressure", "blackscholes"):
        for seed in (3136859, 42, 2026):
          value.sample_counts_by_cell[(
              workload, "0.20", seed, "warmup")] = 20
          value.sample_counts_by_cell[(
              workload, "0.20", seed, "measured")] = 30
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
    active = [
        {"workload": workload, "capacity_ratio": "0.20", "seed": seed}
        for workload in ("canneal", "dedup_pressure", "blackscholes")
        for seed in (3136859, 42, 2026)]
    zero = [
        {"workload": workload, "capacity_ratio": "0.20", "seed": seed}
        for workload in ("streamcluster_pressure", "swaptions",
                         "fluidanimate")
        for seed in (3136859, 42, 2026)]
    scope = {
        "snapshot_count": 9,
        "measured_job_ids": ["active-{}".format(i) for i in range(9)],
        "measured_cells": active,
        "zero_round_job_count": 9,
        "zero_round_job_ids": ["zero-{}".format(i) for i in range(9)],
        "zero_round_cells": zero,
        "measured_rounds": 1800,
        "measured_demoted_pages": 7200}
    runner._audit_perf_scope_counts(scope, config)
    scope["measured_cells"] = active[:-1]
    with self.assertRaises(stage9.Stage9ContractError):
      runner._audit_perf_scope_counts(scope, config)

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
        workload_capacities=[{"workload": "w", "ratio": "0.40",
                              "dram_pages": 100}], page_size_bytes=4096)
    self.assertEqual(97, rows[0]["capd_effective_dram_pages"])
    self.assertEqual(3, rows[0]["management_pages"])
    self.assertAlmostEqual(3.0, rows[0]["capacity_overhead_percent"])

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
        F_low=8, F_target=16, b_max=4, candidate_size_K=8,
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
    self.assertEqual(4, _config()["frozen_controls"]["b_max"])
    self.assertEqual("analysis_only_not_selection",
                     _config()["sensitivity"]["purpose"])


if __name__ == "__main__":
  unittest.main()
