import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap.finals_generator import LRUBehaviorState
from qmap.finals_generator import build_generator_decision_snapshot
from qmap.qmap_eval import build_replay_decision_snapshot


class GeneratorReplayFeatureEquivalenceTest(unittest.TestCase):

  def test_same_state_produces_identical_snapshot(self):
    config = {
        "memory": {"dram_capacity_pages": 64},
        "candidate": {"pool_size_B": 64, "retained_K": 8,
                      "selector_history_Hc": 32},
        "history": {"transformer_H": 10},
        "features": {"residency_scale_Lres": 256},
    }
    selector_params = {
        "c_Delta": 32.0, "c_A": 4.0, "c_W": 2.0,
        "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
        "w_C": 0.2, "w_R": 0.2,
    }
    state = LRUBehaviorState(config)
    for index in range(64):
      state.advance({
          "page": index + 1, "address": (index + 1) << 12,
          "pc": 0x100 + index, "rw": 1 if index % 9 == 0 else 0,
      }, index)
    current = {"page": 65, "address": 65 << 12, "pc": 0x999, "rw": 0}
    self.assertTrue(state.is_decision(current["page"]))
    generator = build_generator_decision_snapshot(
        state, current, 64, config, selector_params)
    replay = build_replay_decision_snapshot(
        state.dram_pages, state.decision_history(current), 64,
        state.dram_insert_time, state.dirty_pages, state.selector_history,
        config, selector_params)
    for key in ("P_t", "B_t", "K_t", "candidate_pages",
                "candidate_state_features", "candidate_mask",
                "original_pool_ranks"):
      self.assertEqual(generator[key], replay[key], key)
    self.assertEqual(
        [item["selector_features"] for item in generator["pool_records"]],
        [item["selector_features"] for item in replay["pool_records"]])
    self.assertEqual(
        [item["page"] for item in generator["selected_records"]],
        [item["page"] for item in replay["selected_records"]])


if __name__ == "__main__":
  unittest.main()
