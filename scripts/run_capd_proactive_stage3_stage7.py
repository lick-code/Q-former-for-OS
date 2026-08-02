#!/usr/bin/env python3
# coding=utf-8
"""CLI for six-workload CAPD Stage-7 Stage-3 calibration."""

from __future__ import annotations

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage3_stage7


DEFAULT_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage3_stage7_calibration.json")
DEFAULT_RUN_ID = "stage3-stage7-calibration-r2"
DEFAULT_SELECTION_REPAIR_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage3_stage7_selection_repair.json")
DEFAULT_SELECTION_REPAIR_RUN_ID = "stage3-stage7-selection-repair-r3"


def _common(value: argparse.ArgumentParser) -> None:
  value.add_argument("--config", default=DEFAULT_CONFIG)
  value.add_argument("--run-id", default=DEFAULT_RUN_ID)
  value.add_argument("--project-root", default=PROJECT_ROOT)
  value.add_argument("--output-root")
  value.add_argument(
      "--resume", action="store_true",
      help="Reuse only exact-matching phase artifacts and checkpoints")


def _selection_repair_common(value: argparse.ArgumentParser) -> None:
  value.add_argument(
      "--selection-config", default=DEFAULT_SELECTION_REPAIR_CONFIG)
  value.add_argument("--run-id", default=DEFAULT_SELECTION_REPAIR_RUN_ID)
  value.add_argument("--project-root", default=PROJECT_ROOT)
  value.add_argument("--output-root")
  value.add_argument("--source-run-directory", required=True)


def parser() -> argparse.ArgumentParser:
  value = argparse.ArgumentParser(
      description=(
          "Stage-3 mechanism calibration on R1-authoritative Stage-7 "
          "Train/Validation only"))
  commands = value.add_subparsers(dest="command", required=True)
  for name in proactive_stage3_stage7.ALL_PHASES + ("all",):
    command = commands.add_parser(name)
    _common(command)
  freeze = commands.add_parser("freeze")
  _common(freeze)
  freeze.add_argument("--candidate", required=True)
  freeze.add_argument(
      "--confirm-stage3-stage7-freeze", action="store_true",
      help="Confirm human review of the exact candidate file")
  reselect = commands.add_parser("reselect")
  _selection_repair_common(reselect)
  verify_reselection = commands.add_parser("verify-reselection")
  _selection_repair_common(verify_reselection)
  freeze_reselection = commands.add_parser("freeze-reselection")
  _selection_repair_common(freeze_reselection)
  freeze_reselection.add_argument("--candidate", required=True)
  freeze_reselection.add_argument(
      "--confirm-stage3-stage7-freeze", action="store_true",
      help="Confirm human review of the exact derived candidate file")
  return value


def main(argv=None) -> int:
  args = parser().parse_args(argv)
  if args.command in ("reselect", "verify-reselection", "freeze-reselection"):
    repair_common = {
        "selection_config_path": args.selection_config,
        "run_id": args.run_id,
        "project_root": args.project_root,
        "source_run_directory": args.source_run_directory,
        "output_root": args.output_root,
    }
    if args.command == "reselect":
      result = proactive_stage3_stage7.run_reselect(**repair_common)
    elif args.command == "verify-reselection":
      result = proactive_stage3_stage7.run_verify_reselection(**repair_common)
    else:
      result = proactive_stage3_stage7.run_freeze_reselection(
          candidate_path=args.candidate,
          confirmed=args.confirm_stage3_stage7_freeze, **repair_common)
    print(result.get("output_directory", ""))
    print(result["status"])
    if args.command == "freeze-reselection":
      print("STAGE3_STAGE7_DERIVED_SELECTION_FORMAL_FREEZE_COMPLETE")
    else:
      print("STAGE3_STAGE7_DERIVED_SELECTION_FREEZE_NOT_EXECUTED")
    return 0
  common = {
      "config_path": args.config,
      "run_id": args.run_id,
      "project_root": args.project_root,
      "output_root": args.output_root,
  }
  if args.command == "freeze":
    result = proactive_stage3_stage7.run_freeze(
        candidate_path=args.candidate,
        confirmed=args.confirm_stage3_stage7_freeze, **common)
  else:
    function = {
        "preflight": proactive_stage3_stage7.run_preflight,
        "profile": proactive_stage3_stage7.run_profile,
        "search": proactive_stage3_stage7.run_search,
        "select": proactive_stage3_stage7.run_select,
        "verify": proactive_stage3_stage7.run_verify,
        "all": proactive_stage3_stage7.run_all,
    }[args.command]
    result = function(resume=args.resume, **common)
  print(result.get("output_directory", ""))
  print(result["status"])
  if args.command == "all":
    print("STAGE3_STAGE7_ALL_COMPLETE_FREEZE_NOT_EXECUTED")
  elif args.command == "freeze":
    print("STAGE3_STAGE7_FORMAL_FREEZE_COMPLETE")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
