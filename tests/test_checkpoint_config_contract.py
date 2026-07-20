import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap.qmap_eval import validate_checkpoint_config_contract


class CheckpointConfigContractTest(unittest.TestCase):

  def setUp(self):
    base_path = os.path.join(
        PROJECT_ROOT, "configs", "finals", "capd_direction1.json")
    base = finals_config.load_config(base_path)
    self.config = finals_config.resolve_config(base, "canneal", 64)
    holdout = {
        "strategy": "train_trace_decision_holdout",
        "basis": "lru_victim_decision_points",
        "order": "chronological",
        "holdout_fraction": 0.2,
        "rounding": "ceil",
        "guard_accesses": 256,
        "trace_access_count": 1000,
        "total_decision_points": 100,
        "train_access_end_exclusive": 101,
        "validation_access_start_inclusive": 357,
        "train_decision_points": 79,
        "guard_decision_points": 1,
        "validation_decision_points": 20,
        "last_train_decision_index": 100,
        "first_validation_decision_index": 357,
    }
    holdout["fingerprint"] = finals_config.decision_holdout_fingerprint(
        holdout)
    self.selector = {
        "c_Delta": 10.0, "c_A": 2.0, "c_W": 1.0,
        "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
        "w_C": 0.2, "w_R": 0.2,
        "config_fingerprint": finals_config.config_fingerprint(self.config),
        "workload": "canneal",
        "decision_holdout": holdout,
        "decision_holdout_fingerprint": holdout["fingerprint"],
    }
    self.checkpoint = {
        "schema_version": finals_config.SCHEMA_VERSION,
        "experiment_contract": finals_config.contract_from_config(
            self.config),
        "config_fingerprint": finals_config.config_fingerprint(self.config),
        "selector_fingerprint": finals_config.selector_fingerprint(
            self.selector),
        "decision_holdout_fingerprint": holdout["fingerprint"],
        "workload": "canneal",
        "model_args": {"page_state_dim": 4},
    }

  def test_matching_contract_is_accepted(self):
    validate_checkpoint_config_contract(
        self.checkpoint, self.config, self.selector)

  def test_each_frozen_contract_mismatch_is_rejected(self):
    for field in ("D", "B", "K", "H", "Hc", "L", "Lres",
                  "page_state_dim", "validation_holdout_fraction",
                  "validation_guard_accesses"):
      with self.subTest(field=field):
        checkpoint = copy.deepcopy(self.checkpoint)
        checkpoint["experiment_contract"][field] += 1
        with self.assertRaises(ValueError):
          validate_checkpoint_config_contract(
              checkpoint, self.config, self.selector)

  def test_validation_strategy_mismatch_is_rejected(self):
    checkpoint = copy.deepcopy(self.checkpoint)
    checkpoint["experiment_contract"]["validation_strategy"] = "external"
    with self.assertRaises(ValueError):
      validate_checkpoint_config_contract(
          checkpoint, self.config, self.selector)

  def test_decision_holdout_mismatch_is_rejected(self):
    checkpoint = copy.deepcopy(self.checkpoint)
    checkpoint["decision_holdout_fingerprint"] = "wrong"
    with self.assertRaises(ValueError):
      validate_checkpoint_config_contract(
          checkpoint, self.config, self.selector)


if __name__ == "__main__":
  unittest.main()
