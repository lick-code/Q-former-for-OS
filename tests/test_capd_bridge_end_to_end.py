# coding=utf-8
"""Opt-in torch-backed miniature bridge-profile regression."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


@unittest.skipUnless(os.environ.get("CAPD_BRIDGE_E2E") == "1",
                     "server-only: set CAPD_BRIDGE_E2E=1")
class BridgeTorchMiniEndToEndTest(unittest.TestCase):

  def test_diagnostic_profile_trains_and_emits_decision_evidence(self):
    fixture_path = os.path.join(
        PROJECT_ROOT, "tests", "test_capd_stage1_v3_end_to_end.py")
    spec = importlib.util.spec_from_file_location(
        "capd_stage1_e2e_fixture_for_bridge", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.FinalsV3MiniEndToEndTest()
    with tempfile.TemporaryDirectory() as root:
      config_path = helper._prepare_config(root)
      config = finals_config.load_json(config_path)
      config["run_profile"] = finals_config.DIAGNOSTIC_PROFILE
      config["validation"]["artifact_class"] = "diagnostic_only"
      config["validation"]["require_data_manifest"] = False
      config["bridge_variant"] = {
          "case_id": "mini_bridge",
          "scientific_role": "post_hoc_diagnostic_not_method_selection",
          "test_used_for_selection": False,
      }
      config["run"].pop("resolved_config_fingerprint", None)
      config["run"]["resolved_config_fingerprint"] = (
          finals_config.config_fingerprint(config))
      finals_config.validate_config(config, require_resolved=True)
      finals_config.write_json(config_path, config)
      artifacts = helper._run_once(
          config_path, os.path.join(root, "bootstrap"))
      result_path = os.path.join(root, "bridge_result.json")
      module.run_command([
          sys.executable, "-m", "qmap.qmap_eval",
          "--config", config_path, "--policy", "qmap",
          "--selector_params", artifacts["selector"],
          "--checkpoint", artifacts["checkpoint"], "--device", "cpu",
          "--bridge_diagnostics", "--json_output", result_path])
      with open(result_path, "r", encoding="utf-8") as input_file:
        result = json.load(input_file)
      self.assertEqual("diagnostic_bridge", result["run_profile"])
      self.assertEqual("diagnostic_only", result["artifact_class"])
      diagnostics = result["bridge_diagnostics"]
      self.assertFalse(diagnostics["test_used_for_selection"])
      self.assertEqual(
          result["decision_count"], diagnostics["decision_count"])
      self.assertEqual(
          64, len(diagnostics["victim_sequence_fingerprint"]))


if __name__ == "__main__":
  unittest.main()

