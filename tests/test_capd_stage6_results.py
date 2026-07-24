# coding=utf-8
"""Stage-6 latency, memory, cost, capacity, and RW summary tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage6_results
from qmap import stage6_variants
from qmap.qmap_eval import ReplayStats


def result_row(workload, policy, cost, capacity=64, seed=None,
               replay_seed=None):
  row = {
      "workload": workload, "policy": policy,
      "total_accesses": 100, "hits": 60, "misses": 40,
      "nvm_reads": 30, "nvm_writes": 10, "migrations": 20,
      "weighted_access_cost": float(cost), "dram_capacity": capacity,
      "artifact_class": "official", "test_used_for_selection": False,
  }
  if seed is not None:
    row["model_seed"] = seed
  if replay_seed is not None:
    row["replay_seed"] = replay_seed
  return row


class Stage6ResultTest(unittest.TestCase):

  def test_reweighted_cost_uses_exact_counters(self):
    row = result_row("canneal", "qmap", 0)
    profile = stage6_results.COST_PROFILES["official"]
    self.assertEqual(
        60 + 30 * 2 + 10 * 8 + 20 * 10,
        stage6_results.reweighted_cost(row, profile))
    broken = dict(row, misses=41)
    with self.assertRaises(ValueError):
      stage6_results.reweighted_cost(broken, profile)

  def test_profile_preserves_raw_samples_and_percentiles(self):
    stats = ReplayStats(stage6_profile=True, warmup_decisions=1)
    components = {
        "tensor_and_embedding": 0.001,
        "transformer_encoder": 0.002,
        "cross_attention_scorer": 0.003,
        "victim_selection": 0.0001,
    }
    snapshot = {
        "selector_time_seconds": 0.0005, "B_t": 64, "K_t": 8}
    stats.record_selector(snapshot)
    stats.record_decision(0.010, components)
    stats.record_selector(snapshot)
    stats.record_decision(0.020, components)
    stats.total_accesses = 100
    stats.replay_wall_seconds = 1.0
    stats.profile_memory = {
        "model_parameter_bytes": 10, "model_buffer_bytes": 2,
        "model_static_bytes": 12, "device": "cpu",
        "cuda_device_name": None, "torch_version": None,
        "process_peak_rss_bytes": 100,
        "cuda_peak_allocated_bytes": 0,
        "cuda_peak_reserved_bytes": 0,
    }
    row = stats.to_dict("qmap", "trace.csv", 64)
    row.update({
        "workload": "canneal", "artifact_class": "official",
        "test_used_for_selection": False})
    profile = row["stage6_profile"]
    self.assertEqual(1, profile["measured_decisions"])
    self.assertEqual(20.0, profile["latency_ms"]["full_decision"]["p99"])
    self.assertEqual(
        2.0, profile["latency_ms"]["transformer_encoder"]["mean"])
    stage6_results.validate_profile_result(row)

  def test_cost_summary_keeps_negative_improvement(self):
    rows = []
    for workload in stage6_variants.WORKLOADS:
      for seed in stage6_variants.MODEL_SEEDS:
        qmap = result_row(workload, "qmap", 100, seed=seed)
        qmap.update({
            "hits": 50, "misses": 50, "nvm_reads": 40,
            "nvm_writes": 10, "migrations": 25})
        rows.append(qmap)
      rows.extend([
          result_row(workload, "random", 95, replay_seed=seed)
          for seed in stage6_variants.RANDOM_REPLAY_SEEDS])
      rows.append(result_row(workload, "lru", 90))
      rows.append(result_row(workload, "lfu", 110))
      rows.append(result_row(workload, "clock", 105))
      rows.append(result_row(workload, "optional_lite", 1))
    summary = stage6_results.summarize_cost_robustness(rows)
    for profile in summary["profiles"].values():
      for workload in stage6_variants.WORKLOADS:
        self.assertNotIn(
            "optional_lite",
            profile["workloads"][workload]["external"])
        self.assertLess(
            profile["workloads"][workload][
                "capd_improvement_percent"], 0.0)

  def test_profile_summarizes_throughput_and_system_effects(self):
    rows = []
    for workload in stage6_variants.WORKLOADS:
      for policy, count, throughput, migrations, writes in (
          ("qmap", 3, 80.0, 12, 7),
          ("random", 3, 100.0, 18, 9),
          ("lru", 1, 120.0, 10, 6),
          ("lfu", 1, 110.0, 11, 5),
          ("clock", 1, 90.0, 9, 8)):
        for index in range(count):
          rows.append({
              "workload": workload, "policy": policy,
              "model_seed": index if policy == "qmap" else None,
              "replay_seed": index if policy == "random" else None,
              "artifact_class": "official",
              "test_used_for_selection": False,
              "replay_wall_seconds": 1.0,
              "throughput_accesses_per_second": throughput,
              "migrations": migrations, "nvm_writes": writes,
              "stage6_profile": {
                  "measured_decisions": 1,
                  "samples_ms": (
                      {
                          component: [1.0]
                          for component in
                          stage6_results.REQUIRED_PROFILE_COMPONENTS
                      } if policy == "qmap" else {
                          "full_decision": [1.0]}),
                  "memory": {
                      "model_parameter_bytes": 0,
                      "model_buffer_bytes": 0,
                      "model_static_bytes": 0,
                      "device": "cpu",
                      "cuda_device_name": None,
                      "torch_version": None,
                      "process_peak_rss_bytes": 1,
                      "cuda_peak_allocated_bytes": 0,
                      "cuda_peak_reserved_bytes": 0}}})
    summary = stage6_results.summarize_profiles(rows)
    canneal = summary["effect_summary"]["canneal"]
    self.assertEqual("lru", canneal["throughput_reference_policy"])
    self.assertAlmostEqual(
        100.0 / 3.0,
        canneal["qmap_throughput_degradation_percent"])
    self.assertEqual("clock", canneal["migration_reference_policy"])
    self.assertEqual("lfu", canneal["nvm_write_reference_policy"])

  def test_capacity_requires_three_qmap_seeds_for_every_point(self):
    rows = []
    for capacity in (64,) + stage6_variants.CAPACITIES:
      for workload in stage6_variants.WORKLOADS:
        rows.extend([
            result_row(workload, "qmap", 80, capacity, seed=seed)
            for seed in stage6_variants.MODEL_SEEDS])
        rows.extend([
            result_row(
                workload, "random", 100, capacity, replay_seed=seed)
            for seed in stage6_variants.RANDOM_REPLAY_SEEDS])
        for policy, cost in (("lru", 90), ("lfu", 95), ("clock", 92)):
          rows.append(result_row(workload, policy, cost, capacity))
    summary = stage6_results.summarize_capacity(rows)
    self.assertEqual({"64", "128", "256"}, set(summary["capacities"]))
    broken = copy.deepcopy(rows)
    broken = [
        row for row in broken
        if not (row["dram_capacity"] == 128 and
                row["workload"] == "canneal" and
                row["policy"] == "qmap" and row["model_seed"] == 42)]
    with self.assertRaises(ValueError):
      stage6_results.summarize_capacity(broken)

  def test_natural_rw_summary_marks_descriptive_boundary(self):
    reports = {}
    main = {"rows": []}
    for index, workload in enumerate(stage6_variants.WORKLOADS):
      reports[workload] = {
          "status": "PASSED",
          "splits": {"test": {"read_write": {
              "read_ratio": 0.9 - index * 0.2,
              "write_ratio": 0.1 + index * 0.2,
              "rw_source": "real_trace_column"}}}}
      main["rows"].extend([
          result_row(workload, "qmap", 80),
          result_row(workload, "random", 100),
          result_row(workload, "lru", 90),
          result_row(workload, "lfu", 95),
          result_row(workload, "clock", 92),
          result_row(workload, "optional_lite", 1),
      ])
    result = stage6_results.summarize_natural_rw(reports, main)
    self.assertFalse(result["controlled_rw_intervention"])
    self.assertEqual(3, len(result["rows"]))
    self.assertTrue(all(
        row["best_external_policy"] == "lru"
        for row in result["rows"]))


if __name__ == "__main__":
  unittest.main()
