# coding=utf-8
"""Materialize exact official-v3 source intervals without RW fallback."""

from __future__ import print_function

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_data


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Write exact train/valid/test slices from a real-RW trace.")
  parser.add_argument("--source-trace", required=True)
  parser.add_argument("--output-dir", required=True)
  parser.add_argument("--workload", required=True)
  parser.add_argument("--page-shift", type=int, default=12)
  for split in finals_data.REQUIRED_SPLITS:
    parser.add_argument("--{}-start".format(split), type=int, required=True)
    parser.add_argument("--{}-end".format(split), type=int, required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  return parser


def main():
  args = build_arg_parser().parse_args()
  repo_root = os.path.abspath(args.repo_root)
  output_dir = finals_data.resolve_path(args.output_dir, repo_root)
  output_paths = {
      split: os.path.join(output_dir, "{}.csv".format(split))
      for split in finals_data.REQUIRED_SPLITS
  }
  intervals = {
      split: (
          getattr(args, "{}_start".format(split)),
          getattr(args, "{}_end".format(split)))
      for split in finals_data.REQUIRED_SPLITS
  }
  result = finals_data.materialize_source_intervals(
      finals_data.resolve_path(args.source_trace, repo_root),
      output_paths, intervals, args.page_shift)
  print("[done] workload={}".format(args.workload))
  print("[done] source_access_count={}".format(
      result["source_access_count"]))
  for split in finals_data.REQUIRED_SPLITS:
    print("[done] {}={} records={}".format(
        split, output_paths[split], result["split_access_counts"][split]))


if __name__ == "__main__":
  main()
