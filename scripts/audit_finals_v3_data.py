# coding=utf-8
"""Deterministic CAPD stage-2 data quality audit entry point."""

from __future__ import print_function

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Audit one official CAPD v3 workload manifest.")
  parser.add_argument("--manifest", required=True)
  parser.add_argument("--config", required=True,
                      help="Base capd_direction1_v3.json configuration.")
  parser.add_argument("--profile", required=True,
                      help="Explicit data acceptance profile JSON.")
  parser.add_argument("--output", required=True)
  parser.add_argument("--update-manifest", action="store_true",
                      help=(
                          "Write PASSED/INSUFFICIENT/REJECTED and report "
                          "fingerprint back to the manifest."))
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  return parser


def main():
  args = build_arg_parser().parse_args()
  repo_root = os.path.abspath(args.repo_root)
  config = finals_config.load_config(
      finals_data.resolve_path(args.config, repo_root))
  profile = finals_data.load_json(
      finals_data.resolve_path(args.profile, repo_root))
  report = finals_data.audit_source_manifest(
      args.manifest, repo_root, config, profile)
  output = finals_data.resolve_path(args.output, repo_root)
  finals_data.write_json(output, report)
  seal_failed = False
  if args.update_manifest:
    try:
      sealed = finals_data.update_manifest_quality_gate(
          args.manifest, output, repo_root, report)
      print("[done] sealed_manifest_fingerprint={}".format(sealed))
    except (OSError, ValueError) as error:
      seal_failed = True
      print("[blocked] manifest was not sealed: {}".format(error))
  print("[done] status={}".format(report["status"]))
  print("[done] report={}".format(output))
  print("[done] audit_fingerprint={}".format(
      report["audit_fingerprint"]))
  if seal_failed:
    return 4
  if report["status"] == "REJECTED":
    return 3
  if report["status"] == "INSUFFICIENT":
    return 2
  return 0


if __name__ == "__main__":
  sys.exit(main())
