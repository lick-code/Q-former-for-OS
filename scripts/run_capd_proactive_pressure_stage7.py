# coding=utf-8
"""Run fail-closed local Stage-7 Pressure derivation."""

from __future__ import annotations

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_pressure_stage7 as pressure


def _resolve(project_root, value):
  if os.path.isabs(value):
    return os.path.realpath(value)
  return os.path.realpath(os.path.join(project_root, value))


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Derive Stage-7 Pressure windows from frozen Standard Test only; "
          "fail closed when the formal total-order contract is incomplete."))
  subparsers = parser.add_subparsers(dest="command", required=True)
  for command in ("preflight", "scan", "derive", "verify", "all"):
    child = subparsers.add_parser(command)
    child.add_argument("--config", required=True)
    child.add_argument("--run-id", required=True)
    child.add_argument("--project-root", default=".")
    child.add_argument("--resume", action="store_true")
  return parser


def main(argv=None):
  args = build_arg_parser().parse_args(argv)
  project_root = _resolve(PROJECT_ROOT, args.project_root)
  config = _resolve(project_root, args.config)
  functions = {
      "preflight": pressure.run_preflight,
      "scan": pressure.run_scan,
      "derive": pressure.run_derive,
      "verify": pressure.run_verify,
      "all": pressure.run_all,
  }
  try:
    result = functions[args.command](
        config, args.run_id, project_root, resume=args.resume)
  except (OSError, ValueError, pressure.PressureStage7Error) as error:
    print("[ERROR] {}".format(error), file=sys.stderr)
    return 2
  print(json.dumps(result, ensure_ascii=False, sort_keys=True))
  print(result.get("status", "PRESSURE_STAGE7_COMMAND_COMPLETE"))
  return 0


if __name__ == "__main__":
  sys.exit(main())
