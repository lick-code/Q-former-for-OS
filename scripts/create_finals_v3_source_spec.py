# coding=utf-8
"""Create a one-collection CAPD v3 source spec without shell JSON assembly."""

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
      description="Write an explicit one-collection CAPD v3 source spec.")
  parser.add_argument("--workload", required=True)
  parser.add_argument("--source-trace", required=True)
  parser.add_argument("--collection-id", required=True)
  parser.add_argument("--collection-tool", required=True)
  parser.add_argument("--collection-command", required=True)
  parser.add_argument("--collected-at", default=None)
  parser.add_argument("--source-label", default=None)
  parser.add_argument("--environment", default=None,
                      help="Kernel/tool/workload environment identity.")
  parser.add_argument("--split-strategy", required=True)
  for split in finals_data.REQUIRED_SPLITS:
    parser.add_argument("--{}-trace".format(split), required=True)
    parser.add_argument("--{}-start".format(split), type=int, required=True)
    parser.add_argument("--{}-end".format(split), type=int, required=True)
  parser.add_argument("--page-shift", type=int, default=12)
  parser.add_argument("--output", required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  return parser


def main():
  args = build_arg_parser().parse_args()
  if not args.collected_at and not args.source_label:
    raise ValueError("Provide --collected-at or --source-label.")
  splits = {}
  for split in finals_data.REQUIRED_SPLITS:
    splits[split] = {
        "path": getattr(args, "{}_trace".format(split)),
        "collection_id": args.collection_id,
        "source_access_interval": {
            "start_inclusive": getattr(args, "{}_start".format(split)),
            "end_exclusive": getattr(args, "{}_end".format(split)),
        },
    }
  spec = {
      "schema_version": finals_data.SOURCE_SPEC_SCHEMA,
      "contract_id": finals_data.CONTRACT_ID,
      "workload_id": args.workload,
      "page_shift": args.page_shift,
      "rw_source": {
          "kind": "trace_column", "column": "RW", "verified_real": True,
      },
      "split_strategy": args.split_strategy,
      "collections": [{
          "collection_id": args.collection_id,
          "source_trace": args.source_trace,
          "tool": args.collection_tool,
          "command": args.collection_command,
          "collected_at": args.collected_at,
          "source_label": args.source_label,
          "environment": args.environment,
          "provenance_complete": True,
      }],
      "splits": splits,
  }
  output = finals_data.resolve_path(args.output, os.path.abspath(args.repo_root))
  finals_data.write_json(output, spec)
  print("[done] source_spec={}".format(output))


if __name__ == "__main__":
  main()
