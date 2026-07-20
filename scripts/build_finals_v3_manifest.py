# coding=utf-8
"""Build a CAPD v3 source manifest from an explicit collection/split spec."""

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
      description=(
          "Build and verify a capd_finals_v3 source-provenance manifest."))
  parser.add_argument("--spec", required=True,
                      help="JSON source spec with collections and split ranges.")
  parser.add_argument("--output", required=True)
  parser.add_argument("--git-commit", required=True,
                      help="Exact code commit bound to the data manifest.")
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  return parser


def main():
  args = build_arg_parser().parse_args()
  repo_root = os.path.abspath(args.repo_root)
  spec = finals_data.load_json(finals_data.resolve_path(args.spec, repo_root))
  manifest = finals_data.build_source_manifest(
      spec, repo_root, args.git_commit)
  output = finals_data.resolve_path(args.output, repo_root)
  finals_data.write_json(output, manifest)
  print("[done] manifest={}".format(output))
  print("[done] fingerprint={}".format(
      finals_data.fingerprint_file(output)))


if __name__ == "__main__":
  main()
