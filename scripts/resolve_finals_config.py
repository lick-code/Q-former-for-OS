# coding=utf-8
"""Resolve one frozen workload/B combination into an immutable run config."""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


def main():
  parser = argparse.ArgumentParser(
      description="Resolve CAPD finals_v2.1 decision-holdout config.")
  parser.add_argument(
      "--base-config", default="configs/finals/capd_direction1.json")
  parser.add_argument(
      "--workload", choices=("canneal", "streamcluster_pressure",
                             "dedup_pressure"), required=True)
  parser.add_argument("--pool-size-B", type=int, choices=(8, 16, 32, 64),
                      required=True)
  parser.add_argument("--output", required=True)
  args = parser.parse_args()
  base = finals_config.load_config(args.base_config)
  resolved = finals_config.resolve_config(
      base, args.workload, args.pool_size_B, project_root=PROJECT_ROOT)
  finals_config.write_json(args.output, resolved)
  print("[done] resolved_config={}".format(args.output))
  print("[done] config_fingerprint={}".format(
      resolved["run"]["resolved_config_fingerprint"]))


if __name__ == "__main__":
  main()
