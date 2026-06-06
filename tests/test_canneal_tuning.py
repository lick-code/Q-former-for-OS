import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
QMAP_DIR = os.path.join(PROJECT_ROOT, "qmap")
if QMAP_DIR not in sys.path:
  sys.path.insert(0, QMAP_DIR)
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

import qmap_eval
from scripts import run_real_pilot
from scripts import run_real_workload_suite
from scripts import run_canneal_tuned_eval


class CannealTuningTest(unittest.TestCase):

  def test_rank_score_penalty_values_are_normalized_by_rank(self):
    penalties = qmap_eval.rank_score_penalty_values(
        candidate_count=4, penalty=2.0)

    self.assertEqual([0.0, 2.0 / 3.0, 4.0 / 3.0, 2.0], penalties)

  def test_rank_score_penalty_is_passed_to_qmap_eval(self):
    commands = []

    def fake_run_command(command, log_path):
      del log_path
      commands.append(command)

    def fake_load_json(path):
      del path
      return {
          "policy": "qmap",
          "hit_rate": 0.9,
          "hit_rate_percent": 90.0,
          "nvm_writes": 3,
          "weighted_access_cost": 123.0,
          "migrations": 4,
          "avg_decision_time_ms": 1.2,
          "decision_count": 4,
          "total_accesses": 100,
          "misses": 10,
          "nvm_reads": 7,
          "candidate_count": 8,
          "rank_guard": 0,
          "rank_score_penalty": 0.75,
      }

    args = SimpleNamespace(
        python="python",
        dram_capacity=16,
        page_shift=12,
        history_length=10,
        candidate_count=8,
        lookahead=256,
        random_seed=0,
        nvm_write_cost=8.0,
        rank_guard=0,
        rank_score_penalty=0.75,
        device="cuda")

    with tempfile.TemporaryDirectory() as tmpdir:
      paths = {
          "result_dir": tmpdir,
          "test_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_test.csv",
          "train_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_train.csv",
          "valid_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_valid.csv",
          "jsonl": "dataset/jsonl/real_workload_suite/1m/parsec_canneal_train.jsonl",
      }
      with mock.patch.object(run_real_pilot, "run_command", fake_run_command):
        with mock.patch.object(run_real_pilot, "load_json", fake_load_json):
          run_real_pilot.evaluate_policy(
              args, "parsec_canneal", "qmap", paths, "checkpoint.pth",
              os.path.join(tmpdir, "logs"))

    command = commands[0]
    self.assertIn("--rank_score_penalty", command)
    self.assertEqual(
        "0.75", command[command.index("--rank_score_penalty") + 1])

  def test_select_best_config_uses_validation_cost_with_stable_tiebreaks(self):
    rows = [
        {
            "epoch": 10,
            "candidate_count": 1,
            "rank_score_penalty": 0.0,
            "weighted_access_cost": 126178.0,
        },
        {
            "epoch": 1,
            "candidate_count": 2,
            "rank_score_penalty": 0.5,
            "weighted_access_cost": 125100.0,
        },
        {
            "epoch": 1,
            "candidate_count": 4,
            "rank_score_penalty": 0.0,
            "weighted_access_cost": 125100.0,
        },
    ]

    selected = run_canneal_tuned_eval.select_best_config(rows)

    self.assertEqual(1, selected["epoch"])
    self.assertEqual(4, selected["candidate_count"])
    self.assertEqual(0.0, selected["rank_score_penalty"])

  def test_stage5_defaults_keep_guard_and_penalty_disabled(self):
    args = run_real_workload_suite.build_arg_parser().parse_args([])

    self.assertEqual(0, args.rank_guard)
    self.assertEqual(0.0, args.rank_score_penalty)


if __name__ == "__main__":
  unittest.main()
