import os
import random
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import learned_baselines
from qmap import qmap_eval


class BaselineGoldenTest(unittest.TestCase):

  def test_classical_victim_functions_keep_full_dram_native_logic(self):
    dram = [5, 4, 3, 2, 1]
    self.assertEqual(1, qmap_eval.choose_victim_lru(dram))
    first = qmap_eval.choose_victim_random(dram, random.Random(0))
    second = qmap_eval.choose_victim_random(dram, random.Random(0))
    self.assertEqual(first, second)
    self.assertIn(first, dram)
    self.assertEqual(3, qmap_eval.choose_victim_lfu(
        dram,
        access_frequency={1: 4, 2: 2, 3: 1, 4: 1, 5: 5},
        last_access_time={1: 9, 2: 8, 3: 2, 4: 3, 5: 10}))
    clock = qmap_eval.ClockPolicy()
    for page in dram:
      clock.touch(page)
    # First sweep clears all bits; hand then selects the first full-DRAM page.
    self.assertEqual(5, clock.choose_victim(dram))

  def test_learned_baseline_keeps_native_lru_tail_eight(self):
    policy = learned_baselines.LearnedBaselinePolicy({
        "policy": "kleio_lite",
        "feature_names": ["rank_norm"],
        "weights": [1.0],
        "candidate_count": 8,
        "history_length": 10,
        "lookahead": 256,
    })
    dram = list(range(12, 0, -1))
    victim = policy.choose_victim(
        dram_pages=dram, history=[], access_index=20,
        dram_insert_time={page: page for page in dram}, dirty_pages=set(),
        access_frequency={}, last_access_time={})
    self.assertEqual(1, victim)
    self.assertIn(victim, dram[-8:])

  def test_patterns_lite_keeps_native_group_scoring(self):
    policy = learned_baselines.LearnedBaselinePolicy({
        "policy": "patterns_lite",
        "feature_names": ["bias"],
        "cluster_weights": [[2.0], [0.1]],
        "clusters": {
            "centroids": [[1.0, 0.0], [0.0, 1.0]],
            "page_to_cluster": {"1": 0, "2": 1},
            "default_cluster": 0,
        },
        "candidate_count": 8,
        "history_length": 10,
        "lookahead": 256,
    })
    dram = list(range(12, 0, -1))
    victim = policy.choose_victim(
        dram_pages=dram, history=[], access_index=20,
        dram_insert_time={page: page for page in dram}, dirty_pages=set(),
        access_frequency={}, last_access_time={})
    self.assertEqual(2, victim)
    self.assertIn(victim, dram[-8:])


if __name__ == "__main__":
  unittest.main()
