# coding=utf-8
"""Mini train/valid-only R1 data, Oracle and opportunity regression."""

import importlib.util
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import optimization_oracle
from qmap import pressure_headroom
from qmap import pressure_variants


@unittest.skipUnless(os.environ.get("CAPD_R1_E2E") == "1",
                     "server-only: set CAPD_R1_E2E=1")
class R1MiniEndToEndTest(unittest.TestCase):

  def test_missing_test_file_is_never_opened(self):
    fixture_path = os.path.join(
        PROJECT_ROOT, "tests", "test_capd_stage1_v3_end_to_end.py")
    spec = importlib.util.spec_from_file_location(
        "capd_stage1_e2e_fixture_for_r1", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.FinalsV3MiniEndToEndTest()
    os.makedirs(os.path.join(PROJECT_ROOT, "tmp"), exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=os.path.join(PROJECT_ROOT, "tmp")) as root:
      base_config_path = helper._prepare_config(root)
      base = finals_config.load_json(base_config_path)
      base["data"]["split_fingerprints"] = {
          split: finals_config.fingerprint_file(
              base["data"]["{}_trace".format(split)])
          for split in ("train", "valid", "test")}
      base["run"]["resolved_config_fingerprint"] = (
          finals_config.config_fingerprint(base))
      finals_config.write_json(base_config_path, base)
      test_path = base["data"]["test_trace"]
      os.remove(test_path)
      run_root = os.path.join(root, "r1")
      roots = {
          "data": run_root,
          "config": os.path.join(run_root, "resolved_config.json"),
          "selector": os.path.join(run_root, "selector_params.json"),
          "train": os.path.join(run_root, "train.jsonl"),
          "valid": os.path.join(run_root, "valid.jsonl"),
          "validation_samples":
              os.path.join(run_root, "selector_validation_samples.jsonl"),
          "summary": os.path.join(run_root, "generator_summary.json"),
          "manifest": os.path.join(run_root, "variant_manifest.json"),
      }
      os.makedirs(run_root, exist_ok=True)
      pressure_variants.generate_pressure_artifacts(
          base_config_path,
          pressure_variants.pressure_point("pressure_D16"),
          roots, PROJECT_ROOT, "test-commit")
      config = finals_config.load_config(
          roots["config"], require_resolved=True,
          project_root=PROJECT_ROOT, verify_manifest_files=False)
      selector = finals_config.load_json(roots["selector"])
      oracle = optimization_oracle.replay_validation(config, selector)
      opportunity = pressure_headroom.audit_validation(config, selector)

      self.assertFalse(os.path.exists(test_path))
      self.assertEqual("valid", oracle["evaluation_split"])
      self.assertEqual("valid", opportunity["evaluation_split"])
      self.assertFalse(oracle["test_trace_opened"])
      self.assertFalse(opportunity["test_trace_opened"])
      self.assertGreater(oracle["oracle_decisions"], 0)
      self.assertGreater(opportunity["complete_window_decisions"], 0)
      self.assertEqual(
          config["data"]["split_fingerprints"]["valid"],
          opportunity["evaluation_trace_fingerprint"])


if __name__ == "__main__":
  unittest.main()
