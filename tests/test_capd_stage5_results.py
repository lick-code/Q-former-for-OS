# coding=utf-8
"""Stage-5 result direction, seed, fairness, and pairing tests."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage5_results
from qmap import stage5_variants


def row(workload, policy, cost, seed=None, replay_seed=None):
  value = {
      "workload": workload, "policy": policy,
      "total_accesses": 100, "hits": 60, "misses": 40, "hit_rate": .6,
      "nvm_reads": 30, "nvm_writes": 10, "migrations": 20,
      "weighted_access_cost": float(cost), "decision_count": 20,
      "test_trace_fingerprint": "trace-{}".format(workload),
      "cost_model": {"dram_read_cost": 1.0, "dram_write_cost": 1.0,
                     "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
                     "migration_cost": 10.0},
      "dram_capacity": 64, "dram_initial_state": "empty",
      "run_status": "COMPLETED", "artifact_class": "official",
      "test_used_for_selection": False,
  }
  if seed is not None:
    value["model_seed"] = seed
  if replay_seed is not None:
    value["replay_seed"] = replay_seed
  return value


class Stage5ResultTest(unittest.TestCase):

  def test_improvement_direction_and_negative_regression(self):
    self.assertEqual(20.0, stage5_results.improvement_percent(100, 80))
    self.assertEqual(-20.0, stage5_results.improvement_percent(100, 120))

  def test_sample_statistics_use_sample_standard_deviation(self):
    result = stage5_results.sample_summary([1, 2, 3])
    self.assertEqual(2.0, result["mean"])
    self.assertEqual(1.0, result["sample_stddev"])
    self.assertEqual(1.0, result["min"])
    self.assertEqual(3.0, result["max"])

  def _main_rows(self):
    rows = []
    for workload in stage5_variants.WORKLOADS:
      rows.extend([
          row(workload, "qmap", 80, seed=3136859),
          row(workload, "qmap", 82, seed=42),
          row(workload, "qmap", 78, seed=2026),
          row(workload, "random", 110, replay_seed=0),
          row(workload, "random", 100, replay_seed=1),
          row(workload, "random", 120, replay_seed=2),
          row(workload, "lru", 100),
          row(workload, "lfu", 90),
          row(workload, "clock", 95),
      ])
    return rows

  def test_main_summary_keeps_all_seeds_and_selects_lowest_cost_baseline(self):
    summary = stage5_results.summarize_main(self._main_rows())
    for workload in stage5_variants.WORKLOADS:
      item = summary["workloads"][workload]
      self.assertEqual(
          3, item["policies"]["qmap"]["weighted_access_cost"]["count"])
      self.assertEqual("lfu", item["best_external_baseline"]["policy"])
      self.assertGreater(
          item["capd_improvement_percent"]["lfu"], 0.0)
    self.assertIn("macro_average_unweighted_improvement_percent", summary)
    self.assertIn("micro_total_cost_aggregation", summary)

  def test_complete_optional_learned_baseline_enters_main_table(self):
    rows = self._main_rows()
    for workload in stage5_variants.WORKLOADS:
      rows.append(row(workload, "kleio_lite", 85))
    summary = stage5_results.summarize_main(rows)
    self.assertEqual(["kleio_lite"], summary["included_optional_policies"])
    for workload in stage5_variants.WORKLOADS:
      self.assertIn(
          "kleio_lite", summary["workloads"][workload]["policies"])

  def test_incomplete_optional_learned_baseline_is_excluded(self):
    rows = self._main_rows()
    rows.append(row("canneal", "kleio_lite", 85))
    summary = stage5_results.summarize_main(rows)
    self.assertEqual([], summary["included_optional_policies"])
    self.assertEqual(
        "incomplete_workload_coverage",
        summary["excluded_optional_policies"][0]["reason"])

  def test_missing_fairness_binding_hard_fails(self):
    rows = self._main_rows()
    del rows[0]["dram_initial_state"]
    with self.assertRaises(ValueError):
      stage5_results.summarize_main(rows)

  def test_missing_required_seed_hard_fails(self):
    rows = self._main_rows()
    rows = [
        item for item in rows
        if not (item["workload"] == "canneal" and
                item["policy"] == "qmap" and
                item.get("model_seed") == 42)]
    with self.assertRaises(ValueError):
      stage5_results.summarize_main(rows)

  def test_random_seed_cannot_be_overwritten(self):
    rows = self._main_rows()
    target = next(
        item for item in rows if item["workload"] == "canneal" and
        item["policy"] == "random" and item["replay_seed"] == 2)
    target["replay_seed"] = 1
    with self.assertRaises(ValueError):
      stage5_results.summarize_main(rows)

  def test_paired_ablation_uses_matching_seed(self):
    full = [
        row("canneal", "qmap", cost, seed=seed)
        for seed, cost in ((3136859, 100), (42, 80), (2026, 90))]
    variant = [
        row("canneal", "qmap", cost, seed=seed)
        for seed, cost in ((42, 84), (2026, 87), (3136859, 110))]
    paired = stage5_results.paired_ablation_summary(full, variant)
    by_seed = {item["seed"]: item for item in paired["per_seed"]}
    self.assertEqual(10.0, by_seed[3136859]["variant_minus_full"])
    self.assertEqual(4.0, by_seed[42]["variant_minus_full"])
    self.assertEqual(-3.0, by_seed[2026]["variant_minus_full"])

  def test_pilot_and_official_cannot_mix(self):
    full = [
        row("canneal", "qmap", 100, seed=seed)
        for seed in stage5_variants.MODEL_SEEDS]
    variant = copy.deepcopy(full)
    variant[0]["artifact_class"] = "pilot"
    with self.assertRaises(ValueError):
      stage5_results.paired_ablation_summary(full, variant)

  def test_sensitivity_confirmation_flag_is_preserved(self):
    item = row(
        "canneal", "qmap", 80, seed=3136859)
    item.update({
        "variant_id": "sensitivity_H20",
        "needs_seed_confirmation": True})
    summary = stage5_results.summarize_sensitivity([item])
    variant = summary["variants"]["sensitivity_H20"]
    self.assertTrue(variant["single_seed_sensitivity"])
    self.assertTrue(variant["needs_seed_confirmation"])


if __name__ == "__main__":
  unittest.main()
