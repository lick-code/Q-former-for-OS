#!/usr/bin/env python3
# coding=utf-8
"""CLI for CAPD proactive stage-3 Train/Validation calibration."""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_stage3


def parser():
  value = argparse.ArgumentParser()
  value.add_argument(
      "--config", default=os.path.join(
          PROJECT_ROOT, "configs", "finals",
          "capd_proactive_stage3_active_mechanism.json"))
  value.add_argument(
      "--stage0-config", default=os.path.join(
          PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json"))
  value.add_argument(
      "--stage2-config", default=os.path.join(
          PROJECT_ROOT, "configs", "finals",
          "capd_proactive_stage2_cost_profiles.json"))
  value.add_argument("--input-manifest")
  value.add_argument("--run-id")
  value.add_argument("--output-root")
  value.add_argument("--project-root", default=PROJECT_ROOT)
  value.add_argument("--validate-config", action="store_true")
  return value


def main(argv=None):
  args = parser().parse_args(argv)
  config = proactive_stage3.load_json(args.config)
  stage0 = finals_config.load_config(args.stage0_config)
  stage2 = proactive_cost.load_cost_config(args.stage2_config)
  proactive_stage3.validate_config(config, stage0=stage0, stage2=stage2)
  if args.validate_config:
    print("STAGE3_CONFIG_VALID")
    return 0
  if not args.input_manifest or not args.run_id:
    parser().error("--input-manifest and --run-id are required for calibration")
  manifest, traces, resolved_entries = proactive_stage3.load_inputs(
      args.input_manifest, args.project_root)
  output_root = args.output_root or os.path.join(
      args.project_root, config["output_root"])
  result = proactive_stage3.run_calibration(
      config, stage0, stage2, manifest, traces, resolved_entries,
      args.run_id, output_root, args.project_root)
  print(result["output_directory"])
  if result["stage_status"] == proactive_stage3.RESULTS_READY:
    print("STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE")
  else:
    print("STAGE3_IMPLEMENTED_AWAITING_CALIBRATION_INPUTS")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
