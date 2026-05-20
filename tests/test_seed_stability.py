import unittest

from scripts import run_seed_stability


class SeedStabilitySummaryTest(unittest.TestCase):

  def test_collect_seed_row_uses_best_baseline_cost(self):
    qmap_result = {
        "weighted_access_cost": 90.0,
        "migrations": 7,
        "nvm_writes": 3,
    }
    baselines = {
        "lru": {"weighted_access_cost": 120.0},
        "lfu": {"weighted_access_cost": 100.0},
        "clock": {"weighted_access_cost": 110.0},
    }

    row = run_seed_stability.build_seed_row(
        "blackscholes", 42, qmap_result, baselines)

    self.assertEqual("blackscholes", row["workload"])
    self.assertEqual(42, row["seed"])
    self.assertEqual(90.0, row["qmap_cost"])
    self.assertEqual(100.0, row["best_baseline_cost"])
    self.assertAlmostEqual(-10.0, row["delta_percent"])
    self.assertEqual(7, row["migrations"])
    self.assertEqual(3, row["nvm_writes"])

  def test_summarize_rows_reports_population_stability_stats(self):
    rows = [
        {"workload": "streamcluster_pressure", "delta_percent": -12.0},
        {"workload": "streamcluster_pressure", "delta_percent": -10.0},
        {"workload": "streamcluster_pressure", "delta_percent": -11.0},
        {"workload": "canneal", "delta_percent": 19.0},
    ]

    summary = run_seed_stability.summarize_rows(rows)

    stream = summary["streamcluster_pressure"]
    self.assertAlmostEqual(-11.0, stream["mean_delta"])
    self.assertAlmostEqual(0.8164965809, stream["std_delta"])
    self.assertEqual(-12.0, stream["min_delta"])
    self.assertEqual(-10.0, stream["max_delta"])
    self.assertIn("stable positive", stream["conclusion"])

    canneal = summary["canneal"]
    self.assertAlmostEqual(19.0, canneal["mean_delta"])
    self.assertAlmostEqual(0.0, canneal["std_delta"])
    self.assertIn("negative", canneal["conclusion"])


if __name__ == "__main__":
  unittest.main()
