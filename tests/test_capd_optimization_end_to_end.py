# coding=utf-8
"""Opt-in torch-backed mini regression for O2 checkpoint selection."""

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


@unittest.skipUnless(os.environ.get("CAPD_OPTIMIZATION_E2E") == "1",
                     "server-only: set CAPD_OPTIMIZATION_E2E=1")
class OptimizationTorchMiniEndToEndTest(unittest.TestCase):

  def test_per_epoch_checkpoint_replays_valid_without_opening_test(self):
    fixture_path = os.path.join(
        PROJECT_ROOT, "tests", "test_capd_stage1_v3_end_to_end.py")
    spec = importlib.util.spec_from_file_location(
        "capd_stage1_e2e_fixture_for_optimization", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.FinalsV3MiniEndToEndTest()
    with tempfile.TemporaryDirectory() as root:
      config_path = helper._prepare_config(root)
      run_root = os.path.join(root, "optimization")
      os.makedirs(run_root, exist_ok=True)
      selector = os.path.join(run_root, "selector_params.json")
      selector_validation = os.path.join(
          run_root, "selector_validation.jsonl")
      train_jsonl = os.path.join(run_root, "train.jsonl")
      valid_jsonl = os.path.join(run_root, "valid.jsonl")
      generator_summary = os.path.join(
          run_root, "generator_summary.json")
      checkpoint_dir = os.path.join(run_root, "checkpoints")
      valid_result = os.path.join(run_root, "valid_epoch_1.json")

      module.run_command([
          sys.executable, "-m", "qmap.finals_generator",
          "--config", config_path,
          "--selector-output", selector,
          "--validation-samples-output", selector_validation,
          "--train-output", train_jsonl,
          "--valid-output", valid_jsonl,
          "--summary-output", generator_summary])
      module.run_command([
          sys.executable, "-m", "qmap.qmap_train",
          "--config", config_path,
          "--selector_params", selector,
          "--train_data", train_jsonl,
          "--valid_data", valid_jsonl,
          "--output_dir", checkpoint_dir,
          "--device", "cpu",
          "--save_every_epoch"])
      epoch_checkpoint = os.path.join(
          checkpoint_dir, "qmap_epoch_1.pth")
      self.assertTrue(os.path.isfile(epoch_checkpoint))
      manifest = finals_config.load_json(os.path.join(
          checkpoint_dir, "checkpoint_manifest.json"))
      self.assertTrue(manifest["per_epoch_checkpoints_saved"])
      self.assertEqual(1, len(manifest["checkpoints"]["per_epoch"]))

      module.run_command([
          sys.executable, "-m", "qmap.qmap_eval",
          "--config", config_path,
          "--evaluation_split", "valid",
          "--policy", "qmap",
          "--selector_params", selector,
          "--checkpoint", epoch_checkpoint,
          "--device", "cpu",
          "--json_output", valid_result])
      result = finals_config.load_json(valid_result)
      config = finals_config.load_json(config_path)
      self.assertEqual("valid", result["evaluation_split"])
      self.assertFalse(result["test_trace_opened"])
      self.assertFalse(result["test_used_for_selection"])
      self.assertNotIn("test_trace_fingerprint", result)
      self.assertEqual(
          finals_config.fingerprint_file(config["data"]["valid_trace"]),
          result["evaluation_trace_fingerprint"])


if __name__ == "__main__":
  unittest.main()
