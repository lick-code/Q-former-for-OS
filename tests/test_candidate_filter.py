import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter


def selector_params(**overrides):
  params = {
      "c_Delta": 10.0, "c_A": 10.0, "c_W": 10.0,
      "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
      "w_C": 0.2, "w_R": 0.2,
  }
  params.update(overrides)
  return params


class CandidateFilterTest(unittest.TestCase):

  def test_pool_and_retained_size_use_actual_dram_size(self):
    history = candidate_filter.SelectorHistory(8)
    result = candidate_filter.select_candidates(
        [3, 2, 1], 8, 8, 10, history, set(), selector_params())
    self.assertEqual([1, 2, 3], result["P_t"])
    self.assertEqual(3, result["B_t"])
    self.assertEqual(3, result["K_t"])

  def test_five_feature_directions(self):
    history = candidate_filter.SelectorHistory(16)
    history.observe(1, 0, 1)
    history.observe(2, 1, 7)
    history.observe(2, 1, 8)
    old_clean = candidate_filter.raw_selector_values(
        1, 0, 4, 10, history, set())
    recent_dirty = candidate_filter.raw_selector_values(
        2, 3, 4, 10, history, {2})
    old_features = candidate_filter.selector_features(
        old_clean, selector_params())
    recent_features = candidate_filter.selector_features(
        recent_dirty, selector_params())
    self.assertEqual(5, len(old_features))
    self.assertGreater(old_features[0], recent_features[0])
    self.assertGreater(old_features[1], recent_features[1])
    self.assertGreater(old_features[2], recent_features[2])
    self.assertGreater(old_features[3], recent_features[3])
    self.assertGreater(old_features[4], recent_features[4])

  def test_tie_break_is_old_rank_then_page_id(self):
    records = [
        {"page": 8, "original_pool_rank": 1, "selector_score": 0.5},
        {"page": 9, "original_pool_rank": 0, "selector_score": 0.5},
        {"page": 7, "original_pool_rank": 1, "selector_score": 0.5},
    ]
    selected = candidate_filter.select_from_pool_records(records, 3)
    self.assertEqual([9, 7, 8], [item["page"] for item in selected])

  def test_selector_score_not_in_state_and_original_rank_survives(self):
    selected = [
        {"page": 30, "original_pool_rank": 2, "selector_score": 0.9,
         "B_t": 4},
        {"page": 10, "original_pool_rank": 0, "selector_score": 0.8,
         "B_t": 4},
    ]
    state = candidate_filter.build_candidate_state_features(
        selected, [{"page": 30}, {"page": 99}], 20,
        {30: 10, 10: 5}, {30}, 20, 4)
    self.assertEqual([2, 0, -1, -1], state["original_pool_ranks"])
    self.assertEqual(4, len(state["candidate_state_features"][0]))
    self.assertAlmostEqual(
        1.0 / 3.0, state["candidate_state_features"][0][3])
    self.assertNotIn(
        selected[0]["selector_score"],
        state["candidate_state_features"][0])
    self.assertEqual([1, 1, 0, 0], state["candidate_mask"])


if __name__ == "__main__":
  unittest.main()
