import csv
import os
import sys
import tempfile
import types
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import qmap_eval


def replay_args(trace_path):
  return types.SimpleNamespace(
      trace_path=trace_path, page_shift=0, policy="lru", dram_capacity=2,
      random_seed=0, dram_read_cost=1.0, dram_write_cost=1.0,
      nvm_read_cost=2.0, nvm_write_cost=8.0, migration_cost=10.0,
      checkpoint=None, learned_model=None, device="cpu", history_length=10,
      candidate_count=8, lookahead=256, ablation=None, rank_guard=0,
      rank_score_penalty=0.0)


def write_trace(path, first_rw):
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["PC", "Address", "RW"])
    writer.writerow(["0x1", "0x1", first_rw])
    writer.writerow(["0x2", "0x2", 0])
    writer.writerow(["0x3", "0x3", 0])


class DirtyAccountingTest(unittest.TestCase):

  def test_dirty_and_clean_victim_each_migrate_once_without_writeback_count(self):
    with tempfile.TemporaryDirectory() as directory:
      clean_path = os.path.join(directory, "clean.csv")
      dirty_path = os.path.join(directory, "dirty.csv")
      write_trace(clean_path, 0)
      write_trace(dirty_path, 1)
      clean = qmap_eval.replay(replay_args(clean_path))
      dirty = qmap_eval.replay(replay_args(dirty_path))
    self.assertEqual(1, clean.migration_count)
    self.assertEqual(1, dirty.migration_count)
    self.assertEqual(0, clean.nvm_write_count)
    # Exactly the triggering write access itself; dirty eviction adds nothing.
    self.assertEqual(1, dirty.nvm_write_count)
    self.assertEqual(
        clean.weighted_access_cost + 6.0, dirty.weighted_access_cost)


if __name__ == "__main__":
  unittest.main()
