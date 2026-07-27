#!/usr/bin/env python3
# coding=utf-8
"""CLI wrapper for the R1 valid-only bounded-label Oracle."""

from __future__ import print_function

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import optimization_oracle
from qmap import pressure_variants


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run one R1 bounded-label Oracle on valid only.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--selector_params", required=True)
  parser.add_argument("--json_output", required=True)
  return parser


def main():
  args = build_arg_parser().parse_args()
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT,
      verify_manifest_files=False)
  if config.get("run_profile") != finals_config.DIAGNOSTIC_PROFILE:
    raise ValueError("R1 Oracle requires diagnostic profile.")
  variant = config.get("pressure_variant", {})
  if variant.get("family") != pressure_variants.FAMILY:
    raise ValueError("R1 Oracle requires pressure_variant.")
  selector = finals_config.load_json(args.selector_params)
  finals_config.validate_selector_params(config, selector)
  result = optimization_oracle.replay_validation(config, selector)
  result.update({
      "schema_version": "capd_r1_pressure_oracle_1",
      "scientific_role": pressure_variants.SCIENTIFIC_ROLE,
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
  })
  finals_config.write_json(args.json_output, result)
  print("[R1] workload={} case={} oracle_cost={:.2f}".format(
      result["workload"], variant["case_id"],
      result["weighted_access_cost"]))


if __name__ == "__main__":
  main()
