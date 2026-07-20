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
    self.selector = {
        "c_Delta": 10.0, "c_A": 2.0, "c_W": 1.0,
        "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
        "w_C": 0.2, "w_R": 0.2,
        "config_fingerprint": finals_config.config_fingerprint(self.config),
        "workload": "canneal",
    }
    self.checkpoint = {
        "schema_version": finals_config.SCHEMA_VERSION,
        "experiment_contract": finals_config.contract_from_config(
            self.config),
        "config_fingerprint": finals_config.config_fingerprint(self.config),
        "selector_fingerprint": finals_config.selector_fingerprint(
            self.selector),
        "workload": "canneal",
        "model_args": {"page_state_dim": 4},
    }

  def test_matching_contract_is_accepted(self):
    validate_checkpoint_config_contract(
        self.checkpoint, self.config, self.selector)

  def test_each_frozen_contract_mismatch_is_rejected(self):
    for field in ("D", "B", "K", "H", "Hc", "L", "Lres",
                  "page_state_dim"):
      with self.subTest(field=field):
        checkpoint = copy.deepcopy(self.checkpoint)
        checkpoint["experiment_contract"][field] += 1
        with self.assertRaises(ValueError):
          validate_checkpoint_config_contract(
              checkpoint, self.config, self.selector)


if __name__ == "__main__":
  unittest.main()
