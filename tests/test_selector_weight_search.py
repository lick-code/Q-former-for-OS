import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import selector_search


class SelectorWeightSearchTest(unittest.TestCase):

  def test_grid_has_exactly_1001_integer_compositions(self):
    grid = selector_search.weight_grid()
    self.assertEqual(1001, len(grid))
    self.assertEqual(1001, len(set(grid)))
    for weights in grid:
      self.assertAlmostEqual(1.0, sum(weights))

  def test_choice_key_prioritizes_recall_then_regret(self):
    uniform = (0.2,) * 5
    self.assertLess(
        selector_search.weight_choice_key(0.9, 0.9, uniform),
        selector_search.weight_choice_key(0.8, 0.0, uniform))
    self.assertLess(
        selector_search.weight_choice_key(0.9, 0.1, uniform),
        selector_search.weight_choice_key(0.9, 0.2, uniform))

  def test_choice_key_uses_uniform_distance_then_lexicographic_order(self):
    uniform = (0.2,) * 5
    far = (1.0, 0.0, 0.0, 0.0, 0.0)
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.0, uniform),
        selector_search.weight_choice_key(1.0, 0.0, far))
    left = (0.1, 0.2, 0.2, 0.2, 0.3)
    right = (0.3, 0.2, 0.2, 0.2, 0.1)
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.0, left),
        selector_search.weight_choice_key(1.0, 0.0, right))

  def test_empty_effective_validation_set_falls_back_to_uniform(self):
    result = selector_search.search_selector_weights([{
        "B_t": 2,
        "retained_K": 1,
        "selector_features": [[0.0] * 5, [1.0] * 5],
        "relevance": [0.5, 0.5],
    }])
    self.assertEqual((0.2,) * 5, result["weights"])
    self.assertTrue(result["fallback_uniform"])
    self.assertEqual(0, result["effective_decision_points"])


if __name__ == "__main__":
  unittest.main()
