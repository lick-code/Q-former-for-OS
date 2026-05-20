# coding=utf-8
"""Prepare a real trace with an explicit pressure test window.

The standard prepare_real_trace.py uses a fixed 80/10/10 chronological split.
Some workloads have high-pressure regions that do not land in the final 10%.
This script keeps chronological training context before a chosen test window and
uses the chosen window directly as the test split.
"""

import argparse
import os
import sys
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)
SCRIPTS_DIR = os.path.dirname(__file__)
if SCRIPTS_DIR not in sys.path:
  sys.path.insert(0, SCRIPTS_DIR)

from prepare_real_trace import compute_stats
from prepare_real_trace import load_manifest
from prepare_real_trace import read_trace
from prepare_real_trace import rel_path
from prepare_real_trace import split_stats
from prepare_real_trace import write_manifest
from prepare_real_trace import write_stats_outputs
from prepare_real_trace import write_trace


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Prepare explicit pressure-window train/valid/test splits.")
  parser.add_argument("--input", required=True)
  parser.add_argument("--workload", required=True)
  parser.add_argument("--test_start", type=int, required=True)
  parser.add_argument("--test_records", type=int, required=True)
  parser.add_argument("--valid_records", type=int, default=100000)
  parser.add_argument("--train_records", type=int, default=0,
                      help="0 means use all records before valid/test.")
  parser.add_argument("--raw-output", default=None)
  parser.add_argument("--processed-dir", required=True)
  parser.add_argument("--manifest", default=path_from_root(
      "dataset", "metadata", "pressure_window_manifest.json"))
  parser.add_argument("--stats-dir", default=path_from_root(
      "outputs", "results", "pressure_window_stats"))
  parser.add_argument("--page-shift", type=int, default=12)
  parser.add_argument("--keep-raw-address", action="store_true")
  parser.add_argument("--fallback-rw", default="R")
  return parser


def validate_args(args, rows):
  if args.test_start < 0:
    raise ValueError("--test_start must be non-negative.")
  if args.test_records <= 0:
    raise ValueError("--test_records must be positive.")
  if args.valid_records < 0:
    raise ValueError("--valid_records must be non-negative.")
  if args.train_records < 0:
    raise ValueError("--train_records must be non-negative.")
  if args.test_start + args.test_records > len(rows):
    raise ValueError(
        "Test window {}-{} exceeds trace length {}.".format(
            args.test_start, args.test_start + args.test_records, len(rows)))
  if args.test_start < args.valid_records:
    raise ValueError("Not enough records before test_start for validation.")


def build_splits(rows, args):
  test_start = args.test_start
  test_end = args.test_start + args.test_records
  valid_start = test_start - args.valid_records
  train_end = valid_start
  if args.train_records:
    train_start = max(0, train_end - args.train_records)
  else:
    train_start = 0
  if train_start >= train_end:
    raise ValueError("Training split is empty.")
  return {
      "train": rows[train_start:train_end],
      "valid": rows[valid_start:test_start],
      "test": rows[test_start:test_end],
  }, {
      "train_start": train_start,
      "train_end": train_end,
      "valid_start": valid_start,
      "valid_end": test_start,
      "test_start": test_start,
      "test_end": test_end,
  }


def write_processed_splits(splits, args):
  split_manifest = {}
  split_paths = {}
  for split_name, split_rows in splits.items():
    split_path = os.path.join(
        args.processed_dir, "{}_{}.csv".format(args.workload, split_name))
    write_trace(split_rows, split_path)
    split_paths[split_name] = split_path
    split_manifest[split_name] = {
        "file": rel_path(split_path),
        "records": len(split_rows),
        "stats": split_stats(split_rows, args.page_shift),
    }
  return split_paths, split_manifest


def main():
  args = build_arg_parser().parse_args()
  rows = read_trace(
      args.input,
      args.page_shift,
      args.keep_raw_address,
      args.fallback_rw,
      skip=0,
      limit=0)
  validate_args(args, rows)
  splits, ranges = build_splits(rows, args)

  raw_output = args.raw_output or path_from_root(
      "dataset", "raw_traces", "{}_pressure.csv".format(args.workload))
  write_trace(rows, raw_output)
  split_paths, split_manifest = write_processed_splits(splits, args)

  manifest = load_manifest(args.manifest)
  manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
  manifest["workloads"][args.workload] = {
      "source_trace": rel_path(args.input),
      "raw_trace": rel_path(raw_output),
      "split_policy": "explicit pressure test window",
      "page_shift": args.page_shift,
      "pressure_window": ranges,
      "stats": compute_stats(rows, args.page_shift),
      "splits": split_manifest,
  }
  write_manifest(manifest, args.manifest)
  summary_path = write_stats_outputs(manifest, args.stats_dir)

  print("Workload: {}".format(args.workload))
  print("Raw trace: {}".format(raw_output))
  print("Train split: {}".format(split_paths["train"]))
  print("Valid split: {}".format(split_paths["valid"]))
  print("Test split: {}".format(split_paths["test"]))
  print("Pressure ranges: {}".format(ranges))
  print("Manifest: {}".format(args.manifest))
  print("Stats summary: {}".format(summary_path))


if __name__ == "__main__":
  main()
