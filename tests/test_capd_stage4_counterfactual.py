# coding=utf-8
"""Server tests for CAPD stage-4 G12 accounting and statistics."""

import math
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage4_common
from qmap import stage4_counterfactual


class State(object):
  dram_capacity = 2
  dram_pages = [1, 2]
  dirty_pages = {2}


COST = {"dram_read_cost": 1.0, "dram_write_cost": 1.0,
        "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
        "migration_cost": 10.0}


class CounterfactualAccountingTest(unittest.TestCase):

  def test_forced_first_victim_changes_hand_computable_future_cost(self):
    current = {"page": 3, "rw": 0}
    future = [{"page": 1, "rw": 0}, {"page": 3, "rw": 0}]
    evict_one = stage4_counterfactual.replay_forced_victim(
        State(), current, future, 1, COST)
    evict_two = stage4_counterfactual.replay_forced_victim(
        State(), current, future, 2, COST)
    self.assertGreater(evict_one["J"], evict_two["J"])
    self.assertEqual(2.0,
                     evict_one["common_current_nvm_access_cost_excluded_from_J"])

  def test_later_evictions_are_strict_lru_and_dirty_demotion_has_no_write(self):
    result = stage4_counterfactual.replay_forced_victim(
        State(), {"page": 3, "rw": 0},
        [{"page": 4, "rw": 0}, {"page": 2, "rw": 0}], 1, COST)
    self.assertEqual(2, result["future_migrations"])
    self.assertEqual(0, result["nvm_writes"])

  def test_spearman_uses_average_tie_ranks_and_undefined_constants(self):
    self.assertAlmostEqual(1.0, stage4_common.spearman(
        [1.0, 1.0, 2.0], [4.0, 4.0, 9.0]))
    self.assertIsNone(stage4_common.spearman([1, 1, 1], [1, 2, 3]))
    self.assertIsNone(stage4_common.spearman([1, 2, 3], [4, 4, 4]))

  def test_top1_is_set_any_hit_and_ideal_ndcg_is_one(self):
    candidates = [
        {"d_hat": 1, "q_hat": 0, "w_hat": 0, "J": 2,
         "original_pool_rank": 0},
        {"d_hat": 1, "q_hat": 0, "w_hat": 0, "J": 1,
         "original_pool_rank": 1},
    ]
    metric = stage4_counterfactual.decision_metrics(
        candidates, "base", (1, 1, 4))
    self.assertEqual(1.0, metric["top1_any_hit"])
    ndcg, _ = stage4_common.ndcg_from_costs([2, 1], [1, 2], [0, 1])
    self.assertEqual(1.0, ndcg)

  def test_equal_costs_do_not_create_nan_or_zero_division(self):
    ndcg, indistinguishable = stage4_common.ndcg_from_costs(
        [2, 1], [7, 7], [0, 1])
    self.assertTrue(indistinguishable)
    self.assertEqual(1.0, ndcg)
    self.assertTrue(math.isfinite(ndcg))

  def test_all_nine_label_variants_reuse_the_same_costs(self):
    self.assertEqual({
        "base", "no_write", "balanced_write", "half_write",
        "stronger_write", "inactivity_only", "coldness_only",
        "no_inactivity", "no_coldness"},
        set(stage4_common.LABEL_VARIANTS))


if __name__ == "__main__":
  unittest.main()
