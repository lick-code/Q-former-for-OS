# coding=utf-8
"""Server-only miniature v3 pipeline and fixed-seed determinism regression."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
  import torch
except ModuleNotFoundError:
  torch = None


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


RUN_E2E = os.environ.get("CAPD_RUN_STAGE1_E2E") == "1"


def write_trace(path, page_offset, pc_offset, access_count=330):
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["PC", "Address", "RW"])
    for index in range(access_count):
      page_id = page_offset + index
      writer.writerow([
          hex(pc_offset + index), hex(page_id << 12), int(index % 11 == 0)])


def run_command(command):
  environment = os.environ.copy()
  environment["PYTHONPATH"] = PROJECT_ROOT
  subprocess.check_call(command, cwd=PROJECT_ROOT, env=environment)


def assert_state_equal(testcase, left, right):
  testcase.assertEqual(set(left), set(right))
  for key in left:
    with testcase.subTest(state_key=key):
      if torch.is_tensor(left[key]):
        testcase.assertTrue(torch.equal(left[key], right[key]))
      else:
        testcase.assertEqual(left[key], right[key])


@unittest.skipUnless(
    RUN_E2E and torch is not None,
    "Set CAPD_RUN_STAGE1_E2E=1 on a torch-enabled validation server.")
class FinalsV3MiniEndToEndTest(unittest.TestCase):

  def _prepare_config(self, root):
    train_trace = os.path.join(root, "mini_train.csv")
    valid_trace = os.path.join(root, "mini_valid.csv")
    test_trace = os.path.join(root, "mini_test.csv")
    write_trace(train_trace, 1, 0x1000)
    write_trace(valid_trace, 1001, 0x2000)
    write_trace(test_trace, 2001, 0x3000)
    base_path = os.path.join(
        PROJECT_ROOT, "configs", "finals", "capd_direction1_v3.json")
    base = finals_config.load_config(base_path)
    base["training"]["epochs"] = 1
    base["training"]["batch_size"] = 2
    base["workloads"]["mini_stage1"] = {
        "train_trace": train_trace,
        "valid_trace": valid_trace,
        "test_trace": test_trace,
    }
    resolved = finals_config.resolve_config(base, "mini_stage1", 64)
    config_path = os.path.join(root, "resolved_v3.json")
    finals_config.write_json(config_path, resolved)
    return config_path

  def _run_once(self, config_path, root):
    os.makedirs(root, exist_ok=True)
    selector = os.path.join(root, "selector_params.json")
    selector_validation = os.path.join(root, "selector_validation.jsonl")
    train_jsonl = os.path.join(root, "train.jsonl")
    valid_jsonl = os.path.join(root, "valid.jsonl")
    generator_summary = os.path.join(root, "generator_summary.json")
    checkpoint_dir = os.path.join(root, "checkpoints")
    result = os.path.join(root, "qmap_result.json")
    run_command([
        sys.executable, "-m", "qmap.finals_generator",
        "--config", config_path,
        "--selector-output", selector,
        "--validation-samples-output", selector_validation,
        "--train-output", train_jsonl,
        "--valid-output", valid_jsonl,
        "--summary-output", generator_summary,
    ])
    run_command([
        sys.executable, "-m", "qmap.qmap_train",
        "--config", config_path,
        "--selector_params", selector,
        "--train_data", train_jsonl,
        "--valid_data", valid_jsonl,
        "--output_dir", checkpoint_dir,
        "--device", "cpu",
    ])
    checkpoint = os.path.join(checkpoint_dir, "qmap_best.pth")
    run_command([
        sys.executable, "-m", "qmap.qmap_eval",
        "--config", config_path,
        "--policy", "qmap",
        "--selector_params", selector,
        "--checkpoint", checkpoint,
        "--device", "cpu",
        "--json_output", result,
    ])
    return {
        "selector": selector,
        "generator_summary": generator_summary,
        "train_jsonl": train_jsonl,
        "valid_jsonl": valid_jsonl,
        "checkpoint": checkpoint,
        "result": result,
    }

  def test_mini_pipeline_contract_chain(self):
    with tempfile.TemporaryDirectory() as directory:
      config_path = self._prepare_config(directory)
      artifacts = self._run_once(config_path, os.path.join(directory, "run"))
      with open(artifacts["result"], "r", encoding="utf-8") as input_file:
        result = json.load(input_file)
      self.assertEqual(330, result["total_accesses"])
      self.assertEqual(
          result["total_accesses"], result["hits"] + result["misses"])
      self.assertEqual("capd_finals_v3_0", result["schema_version"])
      self.assertEqual("CAPD-MIC-1.0", result["contract_id"])
      self.assertEqual("official", result["artifact_class"])
      with open(artifacts["generator_summary"], "r",
                encoding="utf-8") as input_file:
        generator_summary = json.load(input_file)
      self.assertIsNone(generator_summary["decision_holdout"])
      self.assertEqual(
          "independent_train_trace",
          generator_summary["train_metadata"]["source_partition"])
      self.assertEqual(
          "independent_valid_trace",
          generator_summary["valid_metadata"]["source_partition"])
      self.assertEqual(3, len(set(
          generator_summary["trace_fingerprints"].values())))

  def test_two_run_fixed_seed_determinism(self):
    with tempfile.TemporaryDirectory() as directory:
      config_path = self._prepare_config(directory)
      first = self._run_once(config_path, os.path.join(directory, "run1"))
      second = self._run_once(config_path, os.path.join(directory, "run2"))

      self.assertEqual(
          finals_config.fingerprint_file(first["train_jsonl"]),
          finals_config.fingerprint_file(second["train_jsonl"]))
      self.assertEqual(
          finals_config.fingerprint_file(first["valid_jsonl"]),
          finals_config.fingerprint_file(second["valid_jsonl"]))
      first_selector = finals_config.load_json(first["selector"])
      second_selector = finals_config.load_json(second["selector"])
      self.assertEqual(
          finals_config.selector_fingerprint(first_selector),
          finals_config.selector_fingerprint(second_selector))

      first_checkpoint = torch.load(first["checkpoint"], map_location="cpu")
      second_checkpoint = torch.load(second["checkpoint"], map_location="cpu")
      for component in ("feature_embedder", "extractor", "scorer"):
        assert_state_equal(
            self, first_checkpoint[component], second_checkpoint[component])

      with open(first["result"], "r", encoding="utf-8") as input_file:
        first_result = json.load(input_file)
      with open(second["result"], "r", encoding="utf-8") as input_file:
        second_result = json.load(input_file)
      for key in (
          "total_accesses", "hits", "misses", "migrations", "nvm_reads",
          "nvm_writes", "weighted_access_cost"):
        self.assertEqual(first_result[key], second_result[key])


if __name__ == "__main__":
  unittest.main()
