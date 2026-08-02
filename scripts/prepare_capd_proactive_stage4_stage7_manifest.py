#!/usr/bin/env python3
# coding=utf-8
"""Create the strict Stage-7 Train/Validation-only Stage-4 manifest."""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage4_stage7 as stage4


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("--source-manifest", required=True)
  parser.add_argument("--stage3-freeze", required=True)
  parser.add_argument("--output", required=True)
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  value = stage4.prepare_input_manifest(
      args.source_manifest, args.stage3_freeze, args.project_root)
  stage4.write_json_atomic(os.path.abspath(args.output), value)
  print("[OK] Stage4 Stage7 input manifest: {}".format(
      os.path.abspath(args.output)))
  print("[SHA256] {}".format(stage4.fingerprint_file(args.output)))
  print("[BOUNDARY] 6 Train + 6 Validation; Test/Pressure unopened")


if __name__ == "__main__":
  main()
