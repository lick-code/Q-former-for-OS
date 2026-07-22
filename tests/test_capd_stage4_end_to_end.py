# coding=utf-8
"""Opt-in Linux-server miniature stage-4 regression.

Enable with CAPD_STAGE4_E2E=1. Every artifact is written below pytest's
temporary directory; the fixture test trace is deleted before stage-4 work to
turn any accidental test read into a hard failure.
"""

import json
import importlib.util
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import stage4_counterfactual
from qmap import stage4_distribution
from qmap.finals_generator import generate_reranker_jsonl
from qmap.qmap_generator import read_trace
_FIXTURE_PATH = os.path.join(PROJECT_ROOT, "tests",
                             "test_capd_stage1_v3_end_to_end.py")
_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "capd_stage1_e2e_fixture", _FIXTURE_PATH)
_FIXTURE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE)
FinalsV3MiniEndToEndTest = _FIXTURE.FinalsV3MiniEndToEndTest
run_command = _FIXTURE.run_command


@unittest.skipUnless(os.environ.get("CAPD_STAGE4_E2E") == "1",
                     "server-only: set CAPD_STAGE4_E2E=1")
class Stage4MiniEndToEndTest(unittest.TestCase):

  def test_frozen_generate_two_seed_train_g12_g11_chain(self):
    import tempfile
    with tempfile.TemporaryDirectory() as root:
      helper = FinalsV3MiniEndToEndTest()
      config_path = helper._prepare_config(root)
      config = finals_config.load_config(
          config_path, require_resolved=True, verify_manifest_files=False)
      config["training"]["epochs"] = 2
      config["run"]["resolved_config_fingerprint"] = None
      config["run"]["resolved_config_fingerprint"] = (
          finals_config.config_fingerprint(config))
      finals_config.write_json(config_path, config)

      # Fixture-only stage-2 bootstrap. Stage-4 begins after selector freeze.
      bootstrap = helper._run_once(config_path, os.path.join(root, "bootstrap"))
      selector = finals_config.load_json(bootstrap["selector"])
      train_trace, _ = read_trace(
          config["data"]["train_trace"], int(config["trace"]["page_shift"]))
      valid_trace, _ = read_trace(
          config["data"]["valid_trace"], int(config["trace"]["page_shift"]))
      stage4_root = os.path.join(root, "stage4")
      os.makedirs(stage4_root)
      train_jsonl = os.path.join(stage4_root, "train.jsonl")
      valid_jsonl = os.path.join(stage4_root, "valid.jsonl")
      generate_reranker_jsonl(
          train_trace, config["data"]["train_trace"], "train", train_jsonl,
          config, selector, config_path, "stage4-mini", holdout=None)
      generate_reranker_jsonl(
          valid_trace, config["data"]["valid_trace"], "valid", valid_jsonl,
          config, selector, config_path, "stage4-mini", holdout=None)
      helper._assert_nontrivial_training_signal(config_path, train_jsonl)

      # Stage-4 training/audits must not need the test trace.
      os.remove(config["data"]["test_trace"])
      manifests = []
      checkpoints = {}
      for run_name, seed in (("seed42_a", 42), ("seed2026", 2026),
                             ("seed42_b", 42)):
        output = os.path.join(stage4_root, run_name)
        run_command([
            sys.executable, "-m", "qmap.qmap_train",
            "--config", config_path, "--selector_params", bootstrap["selector"],
            "--train_data", train_jsonl, "--valid_data", valid_jsonl,
            "--output_dir", output, "--device", "cpu", "--seed", str(seed)])
        with open(os.path.join(output, "checkpoint_manifest.json"), "r",
                  encoding="utf-8") as input_file:
          manifest = json.load(input_file)
        self.assertEqual(seed, manifest["seed"])
        self.assertEqual(2, len(manifest["loss_curve"]))
        manifests.append(manifest)
        checkpoints.setdefault(seed, os.path.join(output, "qmap_best.pth"))
      first = manifests[0]["best_validation_loss"]
      repeated = manifests[2]["best_validation_loss"]
      self.assertLessEqual(abs(first - repeated) / max(abs(first), 1e-12), .05)

      decisions = stage4_counterfactual.audit_trace(
          valid_trace, config, selector)
      self.assertTrue(decisions)
      self.assertIn("base", stage4_counterfactual.summarize(decisions))
      dist_a = stage4_distribution.collect_lru(
          train_trace, config, selector, "A")
      dist_b = stage4_distribution.collect_lru(
          valid_trace, config, selector, "B")
      for seed in (42, 2026):
        dist_c = stage4_distribution.collect_capd(
            valid_trace, config, selector, checkpoints[seed], seed, "cpu")
        comparisons = stage4_distribution.audit_triplet(
            dist_a, dist_b, dist_c)
        self.assertEqual(3, len(comparisons))


if __name__ == "__main__":
  unittest.main()
