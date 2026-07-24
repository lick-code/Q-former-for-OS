# coding=utf-8
"""Opt-in torch-backed miniature Stage-6 profiling regression."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage6_results


@unittest.skipUnless(os.environ.get("CAPD_STAGE6_E2E") == "1",
                     "server-only: set CAPD_STAGE6_E2E=1")
class Stage6TorchMiniEndToEndTest(unittest.TestCase):

  def test_profiled_qmap_chain_uses_only_temporary_paths(self):
    fixture_path = os.path.join(
        PROJECT_ROOT, "tests", "test_capd_stage1_v3_end_to_end.py")
    spec = importlib.util.spec_from_file_location(
        "capd_stage1_e2e_fixture_for_stage6", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.FinalsV3MiniEndToEndTest()
    with tempfile.TemporaryDirectory() as root:
      config = helper._prepare_config(root)
      artifacts = helper._run_once(config, os.path.join(root, "bootstrap"))
      profiled = os.path.join(root, "profiled.json")
      module.run_command([
          sys.executable, "-m", "qmap.qmap_eval",
          "--config", config, "--policy", "qmap",
          "--selector_params", artifacts["selector"],
          "--checkpoint", artifacts["checkpoint"], "--device", "cpu",
          "--stage6_profile", "--stage6_warmup_decisions", "0",
          "--json_output", profiled])
      self.assertTrue(profiled.startswith(root))
      with open(profiled, "r", encoding="utf-8") as input_file:
        result = json.load(input_file)
      result.update({
          "workload": "mini_stage1", "artifact_class": "official",
          "test_used_for_selection": False})
      stage6_results.validate_profile_result(result)
      self.assertGreater(
          result["stage6_profile"]["memory"]["model_parameter_bytes"], 0)


if __name__ == "__main__":
  unittest.main()
