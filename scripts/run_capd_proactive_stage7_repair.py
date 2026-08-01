# coding=utf-8
"""Run only the local R1-R4 CAPD Stage-7 repair preparation."""

from __future__ import annotations

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage7_repair as repair


def _path(value):
  if os.path.isabs(value):
    return os.path.realpath(value)
  return os.path.realpath(os.path.join(PROJECT_ROOT, value))


def _add_prepare_arguments(parser):
  parser.add_argument("--config", required=True)
  parser.add_argument("--source-stage7-run", required=True)
  parser.add_argument("--run-id", required=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Prepare and verify the immutable local CAPD Stage-7 repair R1-R4 "
          "Pressure bundle. R5-R11 are intentionally unavailable."))
  subparsers = parser.add_subparsers(dest="command", required=True)
  local = subparsers.add_parser(
      "local-prepare", help="Run preflight, scan, export, and verify in order.")
  _add_prepare_arguments(local)
  preflight = subparsers.add_parser(
      "preflight", help="Run R1-R3 raw, capacity, and Train/Validation audit.")
  _add_prepare_arguments(preflight)
  scan = subparsers.add_parser(
      "scan-pressure", help="Run fixed Reactive-LRU Test scan and derivation.")
  _add_prepare_arguments(scan)
  export = subparsers.add_parser(
      "export-local-bundle", help="Freeze and deeply verify the local bundle.")
  export.add_argument("--run-id", required=True)
  verify = subparsers.add_parser(
      "verify-local-bundle", help="Verify bundle file signatures for transfer.")
  verify.add_argument("--bundle", default=None)
  verify.add_argument("--run-id", required=True)
  return parser


def _summary(value):
  print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _preflight(args):
  result = repair.run_preflight(
      _path(args.config), _path(args.source_stage7_run), args.run_id,
      PROJECT_ROOT)
  _summary(result)
  print("STAGE7_REPAIR_RAW_IDENTITY_VERIFIED")
  if result["status"] in (
      "r1_verified_r2_r4_paused", "r1_resumed_r2_r4_paused"):
    print("STAGE7_REPAIR_R2_R4_PAUSED_PENDING_PARAMETER_RESELECTION")
  else:
    print("STAGE7_REPAIR_STAGE3_AUDIT_READY")
  return result


def _scan(args):
  result = repair.run_scan_pressure(
      _path(args.config), _path(args.source_stage7_run), args.run_id,
      PROJECT_ROOT)
  _summary(result)
  return result


def _export(args):
  result = repair.export_local_bundle(args.run_id, PROJECT_ROOT)
  _summary(result)
  print(result["marker"])
  return result


def _verify(args, local_marker=False):
  bundle = args.bundle
  if bundle is None:
    bundle = os.path.join(
        repair.repair_output_root(PROJECT_ROOT, args.run_id),
        "local_pressure_bundle_manifest.json")
  bundle = _path(bundle)
  value = repair.verify_bundle_manifest(bundle)
  if value.get("run_id") != args.run_id:
    raise repair.Stage7RepairError(
        "Bundle run ID differs from --run-id.")
  _summary({"status": "bundle_signature_verified", "bundle": bundle,
            "run_id": args.run_id})
  print("STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED" if local_marker else
        "STAGE7_REPAIR_SERVER_ACCEPTED_LOCAL_BUNDLE")
  return value


def main(argv=None):
  args = build_arg_parser().parse_args(argv)
  try:
    if args.command == "preflight":
      _preflight(args)
    elif args.command == "scan-pressure":
      _scan(args)
    elif args.command == "export-local-bundle":
      _export(args)
    elif args.command == "verify-local-bundle":
      _verify(args)
    elif args.command == "local-prepare":
      _preflight(args)
      _scan(args)
      repair.export_local_bundle(args.run_id, PROJECT_ROOT)
      verify_args = argparse.Namespace(
          bundle=os.path.join(
              repair.repair_output_root(PROJECT_ROOT, args.run_id),
              "local_pressure_bundle_manifest.json"),
          run_id=args.run_id)
      _verify(verify_args, local_marker=True)
    else:
      raise repair.Stage7RepairError("Unsupported local command.")
  except (OSError, ValueError, repair.Stage7RepairError) as error:
    print("[ERROR] {}".format(error), file=sys.stderr)
    return 2
  return 0


if __name__ == "__main__":
  sys.exit(main())
