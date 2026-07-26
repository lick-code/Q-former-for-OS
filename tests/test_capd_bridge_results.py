# coding=utf-8
"""Bridge summary and decision-diagnostic tests."""

import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import bridge_results
from qmap import bridge_variants
from qmap.qmap_eval import ReplayStats
from qmap.qmap_eval import _flat_sequence
from qmap.qmap_eval import bounded_next_use_distance


def baseline_rows(offset=0.0):
  return [
      {"policy": "lru", "weighted_access_cost": 100.0 + offset},
      {"policy": "random", "weighted_access_cost": 110.0 + offset},
      {"policy": "lfu", "weighted_access_cost": 120.0 + offset},
      {"policy": "clock", "weighted_access_cost": 105.0 + offset},
  ]


def qmap_rows(center):
  rows = []
  for index, cost in enumerate((center - 1.0, center, center + 1.0)):
    rows.append({
        "policy": "qmap", "weighted_access_cost": cost,
        "bridge_diagnostics": {
            "victim_sequence_fingerprint": "seed-{}".format(index),
            "lru_victim_disagreement_rate": 0.5,
            "lru_in_retained_candidates_rate": 0.75,
            "disagreement_next_use_outcomes": {
                "qmap_better": 3, "qmap_worse": 1, "equal": 2},
            "bounded_next_use_distance_advantage": {"mean": 2.0},
            "top1_top2_score_margin": {"mean": 0.25},
        }})
  return rows


class BridgeResultTest(unittest.TestCase):

  def test_case_summary_uses_positive_improvement_for_lower_cost(self):
    case = bridge_variants.COMPUTE_CASES[0]
    row = bridge_results.summarize_case(
        case, qmap_rows(90.0), baseline_rows(), "synthetic")
    self.assertAlmostEqual(10.0, row["improvement_percent_mean"])
    self.assertEqual("lru", row["best_classic_policy"])
    self.assertTrue(row["decision_diagnostics_available"])
    self.assertEqual(3, row["victim_sequence_unique_count"])
    self.assertEqual(9, row["disagreement_qmap_better_total"])
    self.assertFalse(row["test_used_for_selection"])

  def test_attribution_chain_changes_one_adjacent_anchor(self):
    improvements = (10.0, 9.0, 6.0, 2.0, 0.5)
    rows = []
    for case_id, improvement in zip(
        (
            "legacy_published_D16_B8K8",
            "legacy_current_identity_D16_B8K8",
            "legacy_current_selector_D16_B16K8",
            "official_current_selector_D16_B16K8",
            "official_current_full_D64_B64K8",
        ), improvements):
      rows.append({
          "case_id": case_id,
          "improvement_percent_mean": improvement})
    attribution = bridge_results.attribution_rows(rows)
    self.assertEqual(4, len(attribution))
    self.assertEqual("engine_and_pipeline", attribution[0]["factor"])
    self.assertAlmostEqual(
        -1.0, attribution[0]["improvement_percentage_point_delta"])
    self.assertEqual(
        "dram_capacity_and_feasible_pool", attribution[-1]["factor"])

  def test_replay_stats_records_noninvasive_bridge_diagnostics(self):
    stats = ReplayStats(bridge_diagnostics=True)
    stats.record_decision(0.001)
    stats.record_bridge_decision(
        10, 3, 2, 20, 5, 0.4, [2, 3, 4])
    stats.total_accesses = 1
    result = stats.to_dict("qmap", "trace.csv", 16)
    diagnostic = result["bridge_diagnostics"]
    self.assertEqual(1, diagnostic["lru_victim_disagreements"])
    self.assertEqual(
        1, diagnostic["disagreement_next_use_outcomes"]["qmap_better"])
    self.assertEqual(
        15.0,
        diagnostic["bounded_next_use_distance_advantage"]["mean"])
    self.assertFalse(diagnostic["test_used_for_selection"])

  def test_bounded_next_use_distance_caps_absent_page(self):
    trace = [{"page": value} for value in (1, 2, 3, 2, 4)]
    self.assertEqual(2, bounded_next_use_distance(trace, 1, 2, 3))
    self.assertEqual(4, bounded_next_use_distance(trace, 0, 9, 3))

  def test_bridge_score_conversion_requires_named_flat_sequence(self):
    self.assertEqual(
        [0.75, 0.25],
        _flat_sequence([0.75, 0.25], "bridge eviction_scores"))


if __name__ == "__main__":
  unittest.main()
