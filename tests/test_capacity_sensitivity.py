import unittest

from scripts import run_capacity_sensitivity


class CapacitySensitivityTest(unittest.TestCase):

  def test_build_pilot_command_uses_capacity_specific_paths(self):
    command = run_capacity_sensitivity.build_pilot_command(
        python_bin="python3",
        workload_key="streamcluster_pressure",
        capacity=8,
        device="cuda")

    self.assertEqual("python3", command[0])
    self.assertIn("scripts/run_real_pilot.py", command)
    self.assertIn("--skip_prepare", command)
    self.assertEqual(
        "parsec_streamcluster",
        command[command.index("--workloads") + 1])
    self.assertEqual("8", command[command.index("--dram_capacity") + 1])
    self.assertEqual(
        "dataset/jsonl/capacity_sensitivity/streamcluster_pressure/cap8",
        command[command.index("--jsonl_dir") + 1])
    self.assertEqual(
        "outputs/results/capacity_sensitivity/streamcluster_pressure/cap8",
        command[command.index("--result_dir") + 1])
    self.assertEqual(
        "outputs/checkpoints/capacity_sensitivity/streamcluster_pressure/cap8",
        command[command.index("--checkpoint_dir") + 1])

  def test_build_summary_row_uses_best_baseline_at_same_capacity(self):
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
        },
    }

    row = run_capacity_sensitivity.build_summary_row(
        "streamcluster_pressure", 16, policy_results)

    self.assertEqual("streamcluster_pressure", row["workload"])
    self.assertEqual(16, row["dram_capacity"])
    self.assertEqual("lfu", row["best_baseline_policy"])
    self.assertEqual(100.0, row["best_baseline_cost"])
    self.assertEqual(90.0, row["qmap_cost"])
    self.assertAlmostEqual(-10.0, row["delta_percent"])
    self.assertEqual(6, row["qmap_migrations"])
    self.assertEqual(6, row["decision_count"])


if __name__ == "__main__":
  unittest.main()
