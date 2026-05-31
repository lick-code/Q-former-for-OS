import unittest

from scripts import run_candidate_sensitivity


class CandidateSensitivityTest(unittest.TestCase):

  def test_build_pilot_command_uses_candidate_specific_paths(self):
    command = run_candidate_sensitivity.build_pilot_command(
        python_bin="python3",
        workload_key="streamcluster_pressure",
        candidate_count=16,
        device="cuda")

    self.assertEqual("python3", command[0])
    self.assertIn("scripts/run_real_pilot.py", command)
    self.assertIn("--skip_prepare", command)
    self.assertEqual(
        "parsec_streamcluster",
        command[command.index("--workloads") + 1])
    self.assertEqual("16", command[command.index("--candidate_count") + 1])
    self.assertEqual(
        "dataset/jsonl/candidate_sensitivity/streamcluster_pressure/c16",
        command[command.index("--jsonl_dir") + 1])
    self.assertEqual(
        "outputs/results/candidate_sensitivity/streamcluster_pressure/c16",
        command[command.index("--result_dir") + 1])
    self.assertEqual(
        "outputs/checkpoints/candidate_sensitivity/streamcluster_pressure/c16",
        command[command.index("--checkpoint_dir") + 1])

  def test_build_summary_row_uses_best_baseline_at_same_candidate_count(self):
    policy_results = {
        "lru": {
            "weighted_access_cost": 120.0,
            "nvm_writes": 9,
            "hit_rate_percent": 50.0,
        },
        "lfu": {
            "weighted_access_cost": 100.0,
            "nvm_writes": 8,
            "hit_rate_percent": 55.0,
        },
        "clock": {
            "weighted_access_cost": 110.0,
            "nvm_writes": 7,
            "hit_rate_percent": 54.0,
        },
        "qmap": {
            "weighted_access_cost": 90.0,
            "migrations": 6,
            "decision_count": 6,
            "nvm_writes": 3,
            "avg_decision_time_ms": 2.5,
        },
    }

    row = run_candidate_sensitivity.build_summary_row(
        "streamcluster_pressure", 16, policy_results)

    self.assertEqual("streamcluster_pressure", row["workload"])
    self.assertEqual(16, row["candidate_count"])
    self.assertEqual("lfu", row["best_baseline_policy"])
    self.assertEqual(100.0, row["best_baseline_cost"])
    self.assertEqual(90.0, row["qmap_cost"])
    self.assertAlmostEqual(-10.0, row["delta_percent"])
    self.assertEqual(6, row["qmap_migrations"])
    self.assertEqual(6, row["decision_count"])
    self.assertEqual(2.5, row["avg_decision_time_ms"])


if __name__ == "__main__":
  unittest.main()
