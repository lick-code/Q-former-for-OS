import unittest

from scripts import run_cost_weight_sensitivity


class CostWeightSensitivityTest(unittest.TestCase):

  def test_reweight_result_uses_existing_replay_counters(self):
    result = {
        "policy": "qmap",
        "hits": 10,
        "nvm_reads": 3,
        "nvm_writes": 2,
        "migrations": 1,
        "weighted_access_cost": 1000.0,
    }
    cost_model = {
        "name": "write-heavy",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 16.0,
        "migration_cost": 10.0,
    }

    row = run_cost_weight_sensitivity.reweight_result(
        "streamcluster_pressure", cost_model, result)

    self.assertEqual("streamcluster_pressure", row["workload"])
    self.assertEqual("write-heavy", row["cost_model"])
    self.assertEqual("qmap", row["policy"])
    self.assertEqual(58.0, row["reweighted_cost"])
    self.assertEqual(10, row["hits"])
    self.assertEqual(3, row["nvm_reads"])
    self.assertEqual(2, row["nvm_writes"])
    self.assertEqual(1, row["migrations"])

  def test_build_summary_rows_compares_qmap_to_reweighted_best_baseline(self):
    policy_results = {
        "qmap": {
            "policy": "qmap",
            "hits": 100,
            "nvm_reads": 10,
            "nvm_writes": 2,
            "migrations": 2,
        },
        "lru": {
            "policy": "lru",
            "hits": 80,
            "nvm_reads": 20,
            "nvm_writes": 4,
            "migrations": 4,
        },
        "lfu": {
            "policy": "lfu",
            "hits": 95,
            "nvm_reads": 11,
            "nvm_writes": 2,
            "migrations": 1,
        },
    }
    cost_models = [{
        "name": "default",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 8.0,
        "migration_cost": 10.0,
    }]

    rows = run_cost_weight_sensitivity.build_summary_rows(
        {"toy": policy_results}, cost_models)

    self.assertEqual(1, len(rows))
    row = rows[0]
    self.assertEqual("toy", row["workload"])
    self.assertEqual("default", row["cost_model"])
    self.assertEqual(156.0, row["qmap_cost"])
    self.assertEqual("lfu", row["best_baseline_policy"])
    self.assertEqual(143.0, row["best_baseline_cost"])
    self.assertAlmostEqual(9.0909090909, row["delta_percent"])
    self.assertEqual(2, row["qmap_nvm_writes"])
    self.assertEqual(2, row["qmap_migrations"])


if __name__ == "__main__":
  unittest.main()
