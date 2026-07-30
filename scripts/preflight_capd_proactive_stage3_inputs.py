#!/usr/bin/env python3
# coding=utf-8
"""Fail fast when Stage-3 Validation cannot exercise capacity_rule_v2."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage3


def parser():
  value = argparse.ArgumentParser()
  value.add_argument("--input-manifest", required=True)
  value.add_argument(
      "--config", default=os.path.join(
          PROJECT_ROOT, "configs", "finals",
          "capd_proactive_stage3_active_mechanism.json"))
  value.add_argument("--project-root", default=PROJECT_ROOT)
  value.add_argument("--output")
  return value


def main(argv=None):
  args = parser().parse_args(argv)
  try:
    config = proactive_stage3.load_json(args.config)
    _, traces, _ = proactive_stage3.load_inputs(
        args.input_manifest, args.project_root)
    result = proactive_stage3.capacity_input_preflight(traces, config)
  except (
      OSError, ValueError,
      proactive_stage3.Stage3ContractError) as error:
    print("STAGE3_V2_INPUT_PREFLIGHT_ERROR: {}".format(error))
    return 2
  if args.output:
    proactive_stage3.write_json(args.output, result)
  for profile_name in ("primary", "fallback"):
    profile = result["profiles"][profile_name]
    for item in profile["workloads"]:
      print(
          "STAGE3_PREFLIGHT profile={} workload={} middle_ratio={} "
          "middle_capacity={} validation_unique_pages={} "
          "validation_accesses={} structurally_capable={}".format(
              profile_name, item["workload"], item["middle_capacity_ratio"],
              item["middle_capacity_pages"],
              item["validation_unique_pages"],
              item["validation_accesses"],
              str(item["structurally_capable_of_passing_v2"]).lower()))
  print("STAGE3_PREFLIGHT_ARTIFACT={}".format(
      os.path.abspath(args.output) if args.output else "not_requested"))
  if result["any_profile_structurally_capable"]:
    print("STAGE3_V2_INPUT_PREFLIGHT_READY")
    return 0
  print("STAGE3_V2_INPUT_PREFLIGHT_BLOCKED")
  return 3


if __name__ == "__main__":
  raise SystemExit(main())
