import copy
import math
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap.finals_generator import build_decision_holdout
from qmap.finals_generator import collect_training_observations
from qmap.finals_generator import iter_validation_samples


def make_config(pool_size):
  return {
      "memory": {"dram_capacity_pages": 4},
      "candidate": {
          "pool_size_B": pool_size,
          "retained_K": 2,
          "selector_history_Hc": 8,
      },
      "history": {"transformer_H": 3},
      "labels": {"future_lookahead_L": 4},
      "validation": {
          "strategy": "train_trace_decision_holdout",
          "holdout_fraction": 0.2,
          "rounding": "ceil",
          "guard_accesses": 4,
      },
  }


def make_trace(length=40):
  return [{
      "page": index,
      "address": index << 12,
      "pc": 0x1000 + index,
      "rw": 1 if index % 7 == 0 else 0,
  } for index in range(length)]


class DecisionHoldoutTest(unittest.TestCase):

  def test_chronological_eighty_twenty_split_has_lookahead_guard(self):
    trace = make_trace()
    plan = build_decision_holdout(trace, make_config(4))
    expected_validation = int(math.ceil(
        plan["total_decision_points"] * 0.2))
    self.assertEqual(expected_validation, plan["validation_decision_points"])
    self.assertEqual(4, plan["guard_accesses"])
    self.assertLess(
        plan["last_train_decision_index"] + plan["guard_accesses"],
        plan["first_validation_decision_index"])
    self.assertEqual(
        plan["first_validation_decision_index"],
        plan["validation_access_start_inclusive"])

  def test_split_is_deterministic_and_independent_of_B(self):
    trace = make_trace()
    b2 = build_decision_holdout(trace, make_config(2))
    b4 = build_decision_holdout(trace, make_config(4))
    self.assertEqual(b2, b4)
    self.assertEqual(b2, build_decision_holdout(
        trace, copy.deepcopy(make_config(2))))

  def test_selector_fit_and_validation_use_only_their_decision_ranges(self):
    trace = make_trace()
    config = make_config(4)
    plan = build_decision_holdout(trace, config)
    observations, train_count = collect_training_observations(
        trace, config, plan)
    self.assertEqual(plan["train_decision_points"], train_count)
    self.assertEqual(train_count * 4, len(observations["Delta"]))

    clipping = {"c_Delta": 40.0, "c_A": 4.0, "c_W": 4.0}
    validation = list(iter_validation_samples(
        trace, config, clipping, plan))
    self.assertEqual(plan["validation_decision_points"], len(validation))
    self.assertTrue(all(
        sample["decision_index"] >=
        plan["validation_access_start_inclusive"]
        for sample in validation))

  def test_too_few_decisions_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "at least two victim decisions"):
      build_decision_holdout(make_trace(length=5), make_config(4))


if __name__ == "__main__":
  unittest.main()
