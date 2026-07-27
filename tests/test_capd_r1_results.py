# coding=utf-8
"""Focused tests for R1 pressure-headroom result calculations."""

import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import pressure_headroom
from qmap import pressure_variants
from scripts import run_capd_r1 as r1


def _opportunity(rate):
  return {
      "eviction_decisions": 120,
      "complete_window_decisions": 100,
      "counterfactual_cost_distinguishable_decisions": int(rate * 100),
      "counterfactual_cost_distinguishable_rate": rate,
      "proxy_label_distinguishable_rate": 0.2,
      "future_write_label_distinguishable_rate": 0.1,
      "mixed_clean_dirty_candidate_rate": 0.3,
      "counterfactual_cost_spread_mean": 4.0,
      "counterfactual_cost_spread_median": 2.0,
      "counterfactual_cost_spread_max": 10.0,
  }


class R1PressureResultTest(unittest.TestCase):

  def test_positive_headroom_uses_best_classical_cost(self):
    point = pressure_variants.pressure_point("pressure_D16")
    oracle = {
        "workload": "canneal",
        "weighted_access_cost": 90.0,
        "oracle_decisions": 100,
        "strict_label_preference_decisions": 10,
        "strict_label_preference_rate": 0.1,
    }
    baselines = [
        {"policy": "lru", "weighted_access_cost": 100.0},
        {"policy": "clock", "weighted_access_cost": 105.0},
    ]
    row = pressure_headroom.summarize_pressure_point(
        point, oracle, _opportunity(0.25), baselines)
    self.assertEqual("lru", row["best_classic_policy"])
    self.assertEqual(10.0, row["absolute_headroom"])
    self.assertEqual(10.0, row["relative_headroom_percent"])
    self.assertTrue(row["measurable_headroom"])
    self.assertEqual(0.25, row[
        "counterfactual_cost_distinguishable_rate"])
    self.assertFalse(row["method_selection_performed"])

  def test_headroom_without_strict_preference_is_not_measurable(self):
    point = pressure_variants.pressure_point("pressure_D32")
    oracle = {
        "workload": "dedup_pressure",
        "weighted_access_cost": 99.0,
        "oracle_decisions": 100,
        "strict_label_preference_decisions": 0,
        "strict_label_preference_rate": 0.0,
    }
    baselines = [
        {"policy": "lru", "weighted_access_cost": 100.0},
        {"policy": "clock", "weighted_access_cost": 101.0},
    ]
    row = pressure_headroom.summarize_pressure_point(
        point, oracle, _opportunity(0.0), baselines)
    self.assertFalse(row["measurable_headroom"])

  def test_trend_is_descriptive_and_never_selects_a_capacity(self):
    rows = []
    for capacity, headroom, rate in (
        (16, 3.0, 0.30), (32, 1.0, 0.20), (64, 0.1, 0.05)):
      rows.append({
          "workload": "canneal",
          "D": capacity,
          "relative_headroom_percent": headroom,
          "counterfactual_cost_distinguishable_rate": rate,
          "measurable_headroom": True,
      })
    trend = r1._trend_rows(rows, ["canneal"])[0]
    self.assertEqual("MORE_HEADROOM_AT_D16",
                     trend["descriptive_pattern"])
    self.assertAlmostEqual(
        2.9, trend["headroom_percentage_point_D16_minus_D64"])
    self.assertFalse(trend["method_selection_performed"])
    self.assertNotIn("selected_capacity", trend)


if __name__ == "__main__":
  unittest.main()
