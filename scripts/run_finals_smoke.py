# coding=utf-8
"""Complete CPU smoke test for the frozen CAPD finals_v2 pipeline."""

from __future__ import print_function

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from scripts import run_finals_v2


TEST_FILES = (
    "tests/test_candidate_filter.py",
    "tests/test_selector_weight_search.py",
    "tests/test_generator_replay_feature_equivalence.py",
    "tests/test_dirty_accounting.py",
    "tests/test_checkpoint_config_contract.py",
    "tests/test_baseline_golden.py",
)


def synthetic_accesses(rotation):
  """Produces a deterministic trace with 160 unique pages and write pressure."""
  accesses = []
  page_count = 160
  for round_index in range(5):
    for offset in range(page_count):
      page = (offset + rotation + round_index * 17) % page_count
      accesses.append((0x1000 + (page % 23), page << 12,
                       1 if (page + round_index) % 11 == 0 else 0))
    # Reuse a hot subset so future relevance is not uniformly tied.
    for offset in range(48):
      page = (offset * 3 + rotation + round_index) % 64
      accesses.append((0x2000 + (offset % 13), page << 12,
                       1 if offset % 7 == 0 else 0))
  return accesses


def write_trace(path, rotation):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["PC", "Address", "RW"])
    for pc, address, rw in synthetic_accesses(rotation):
      writer.writerow([hex(pc), hex(address), rw])


def build_smoke_config(base_config_path, smoke_name):
  base = finals_config.load_config(base_config_path)
  trace_dir = os.path.join(
      PROJECT_ROOT, "dataset", "jsonl", "finals_v2", smoke_name, "traces")
  traces = {
      "train_trace": os.path.join(trace_dir, "train.csv"),
      "valid_trace": os.path.join(trace_dir, "valid.csv"),
      "test_trace": os.path.join(trace_dir, "test.csv"),
  }
  write_trace(traces["train_trace"], 0)
  write_trace(traces["valid_trace"], 5)
  write_trace(traces["test_trace"], 11)
  base["workloads"]["synthetic_smoke"] = traces
  base["run_profile"] = "smoke"
  base["candidate"]["selector_history_Hc"] = 32
  base["labels"]["future_lookahead_L"] = 32
  base["training"].update({"epochs": 1, "batch_size": 16})
  base["outputs"] = {
      "jsonl_root": os.path.join(
          PROJECT_ROOT, "dataset", "jsonl", "finals_v2", smoke_name),
      "checkpoint_root": os.path.join(
          PROJECT_ROOT, "outputs", "checkpoints", "finals_v2", smoke_name),
      "result_root": os.path.join(
          PROJECT_ROOT, "outputs", "results", "finals_v2", smoke_name),
  }
  resolved = finals_config.resolve_config(
      base, "synthetic_smoke", 64, project_root=PROJECT_ROOT)
  config_path = os.path.join(
      base["outputs"]["result_root"], "resolved_config.json")
  finals_config.write_json(config_path, resolved)
  return config_path, resolved


def validate_outputs(config, paths):
  selector = finals_config.load_json(paths["selector"])
  train_metadata = finals_config.load_jsonl_metadata(paths["train_jsonl"])
  valid_metadata = finals_config.load_jsonl_metadata(paths["valid_jsonl"])
  candidate_metrics = train_metadata["candidate_filter_metrics"]
  if candidate_metrics["max_B_t"] != 64:
    raise AssertionError("Smoke test never reached B_t=64.")
  if candidate_metrics["max_K_t"] != 8:
    raise AssertionError("Smoke test did not retain K_t=8.")
  with open(paths["train_jsonl"], "r", encoding="utf-8") as input_file:
    sample = json.loads(next(line for line in input_file if line.strip()))
  shape = {
      "history": len(sample["physical_address"]),
      "candidates": len(sample["candidate_pages"]),
      "state": len(sample["candidate_state_features"][0]),
      "mask": len(sample["candidate_mask"]),
  }
  if shape != {"history": 10, "candidates": 8, "state": 4, "mask": 8}:
    raise AssertionError("Unexpected smoke JSONL shape: {}".format(shape))

  import torch
  checkpoint_path = os.path.join(paths["checkpoint_dir"], "qmap_best.pth")
  checkpoint = torch.load(checkpoint_path, map_location="cpu")
  finals_config.assert_contract_matches(
      finals_config.contract_from_config(config),
      checkpoint.get("experiment_contract", {}), "smoke checkpoint")
  policy_names = ("qmap",) + run_finals_v2.CLASSICAL_BASELINES + (
      run_finals_v2.LEARNED_BASELINES)
  results = {}
  for policy in policy_names:
    result_path = os.path.join(paths["result_dir"], "{}.json".format(policy))
    results[policy] = finals_config.load_json(result_path)
  report = {
      "schema_version": finals_config.SCHEMA_VERSION,
      "status": "passed",
      "actual_B_t": candidate_metrics["max_B_t"],
      "actual_K_t": candidate_metrics["max_K_t"],
      "selector_weights": {
          key: selector[key]
          for key in ("w_Delta", "w_A", "w_W", "w_C", "w_R")
      },
      "selector_metrics": {
          key: selector[key]
          for key in ("Recall@K", "NRegret", "effective_decision_points",
                      "nondiscriminative_ratio", "mean_oracle_size",
                      "unique_oracle_ratio")
      },
      "jsonl_shape": shape,
      "train_samples": train_metadata["sample_count"],
      "valid_samples": valid_metadata["sample_count"],
      "checkpoint_contract": checkpoint["experiment_contract"],
      "checkpoint_validation_loss": checkpoint["validation_loss"],
      "results": results,
  }
  report_path = os.path.join(paths["result_dir"], "smoke_report.json")
  finals_config.write_json(report_path, report)
  return report_path


def main():
  parser = argparse.ArgumentParser(description="Run CAPD finals_v2 smoke test.")
  parser.add_argument(
      "--base-config", default="configs/finals/capd_direction1.json")
  parser.add_argument("--smoke-name", default="smoke_workspace")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--skip-unit-tests", action="store_true")
  args = parser.parse_args()
  if (not args.smoke_name or os.path.basename(args.smoke_name) !=
      args.smoke_name):
    raise ValueError("--smoke-name must be one directory name.")
  if not args.skip_unit_tests:
    for test_file in TEST_FILES:
      subprocess.check_call([args.python, test_file], cwd=PROJECT_ROOT)
  config_path, config = build_smoke_config(
      args.base_config, args.smoke_name)
  subprocess.check_call([
      args.python, os.path.join("scripts", "run_finals_v2.py"),
      "--config", config_path, "--stage", "all", "--include-baselines",
      "--retrain-learned-baselines", "--device", "cpu",
      "--python", args.python], cwd=PROJECT_ROOT)
  paths = run_finals_v2.artifact_paths(config)
  report_path = validate_outputs(config, paths)
  print("[passed] smoke_report={}".format(report_path))


if __name__ == "__main__":
  main()
