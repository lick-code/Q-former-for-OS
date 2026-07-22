# coding=utf-8
"""Server tests for CAPD stage-4 G11 distribution identities."""

import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage4_common
from qmap import stage4_distribution


class DistributionMetricTest(unittest.TestCase):

  def test_ks_identical_is_zero_and_disjoint_is_one(self):
    self.assertEqual(0.0, stage4_common.ks_statistic([1, 2], [1, 2]))
    self.assertEqual(1.0, stage4_common.ks_statistic([0, 0], [1, 1]))

  def test_quantiles_and_outside_range_ratio(self):
    self.assertEqual(2.5, stage4_common.quantile([1, 2, 3, 4], .5))
    result = stage4_common.distribution_distance([0, 1], [-1, .5, 2])
    self.assertAlmostEqual(2 / 3.0, result["outside_reference_range_ratio"])

  def test_binary_counts_and_ratio_difference(self):
    result = stage4_common.binary_distance([0, 1], [1, 1])
    self.assertEqual(1, result["reference"]["zero"])
    self.assertEqual(.5, result["one_ratio_difference"])

  def test_a_b_c_identities_cannot_be_mixed(self):
    empty = lambda name: {"identity": {"name": name}, "values": {}}
    with self.assertRaises(ValueError):
      stage4_distribution.audit_triplet(empty("B"), empty("A"), empty("C"))

  def test_feature_sampling_contract_is_explicit(self):
    self.assertEqual(5, len(stage4_distribution.SELECTOR_FEATURES))
    self.assertEqual(4, len(stage4_distribution.CANDIDATE_FEATURES))
    self.assertIn("decision_interval", stage4_distribution.DECISION_FEATURES)

  def test_first_decision_has_no_artificial_zero_interval(self):
    distribution = stage4_distribution._empty_distribution({"name": "A"})
    snapshot = {
        "pool_records": [{"selector_features": [0, 0, 0, 0, 0]}],
        "candidate_mask": [1],
        "candidate_state_features": [[0, 0, 0, 0]],
        "B_t": 1, "K_t": 1, "P_t": [1],
    }
    stage4_distribution._record(
        distribution, snapshot, set(), None, 10)
    self.assertEqual([], distribution["values"]["decision_interval"])
    stage4_distribution._record(
        distribution, snapshot, set(), 10, 14)
    self.assertEqual([4], distribution["values"]["decision_interval"])


if __name__ == "__main__":
  unittest.main()
