#!/usr/bin/env python3
"""Verify that one Stage-7 workload can be safely resumed without recollection."""

from __future__ import print_function

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage7_workloads as stage7  # noqa: E402


def _require(condition, message):
  if not condition:
    raise stage7.Stage7ContractError(message)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--manifest", required=True)
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--workload", required=True)
  parser.add_argument("--role", required=True)
  parser.add_argument("--raw-trace", required=True)
  parser.add_argument("--binary", required=True)
  parser.add_argument("--input-path", default="-")
  parser.add_argument("--total-accesses", type=int, required=True)
  parser.add_argument("--train-end", type=int, required=True)
  parser.add_argument("--validation-end", type=int, required=True)
  parser.add_argument("benchmark_command", nargs=argparse.REMAINDER)
  args = parser.parse_args(argv)

  manifest = stage7.load_json(os.path.abspath(args.manifest))
  _require(manifest.get("schema_version") == stage7.COLLECTION_SCHEMA_VERSION,
           "Existing collection receipt schema changed.")
  _require(manifest.get("contract_id") == stage7.CONTRACT_ID and
           manifest.get("run_id") == args.run_id,
           "Existing collection receipt run identity changed.")
  rows = [row for row in manifest.get("collections", [])
          if row.get("workload") == args.workload]
  _require(len(rows) == 1, "No unique completed workload receipt exists.")
  row = rows[0]
  raw_trace = os.path.abspath(args.raw_trace)
  _require(os.path.isfile(raw_trace), "Resumed raw Trace is missing.")
  _require(row.get("role") == args.role,
           "Resumed workload role changed.")
  _require(stage7.repository_path(
      PROJECT_ROOT, row.get("raw_trace_path", "")) == raw_trace,
      "Resumed raw Trace path changed.")
  _require(row.get("raw_trace_sha256") ==
           stage7.fingerprint_file(raw_trace),
           "Resumed raw Trace SHA-256 changed.")
  _require(row.get("raw_trace_accesses") == args.total_accesses,
           "Resumed raw Trace access count changed.")
  _require(row.get("splits") == {
      "train": [0, args.train_end],
      "validation": [args.train_end, args.validation_end],
      "test": [args.validation_end, args.total_accesses],
  }, "Resumed split identity changed.")
  _require(len(row.get("process_ids", [])) == 1 and
           len(row.get("thread_ids", [])) == 1,
           "Resumed Trace lacks single-process/single-thread identity.")

  benchmark = row.get("benchmark", {})
  binary = os.path.abspath(args.binary)
  _require(os.path.isfile(binary) and
           benchmark.get("binary_path") == binary and
           benchmark.get("binary_sha256") ==
           stage7.fingerprint_file(binary),
           "Resumed benchmark binary identity changed.")
  command = list(args.benchmark_command)
  if command[:1] == ["--"]:
    command = command[1:]
  _require(benchmark.get("command") == command,
           "Resumed benchmark command changed.")
  input_path = None if args.input_path == "-" else os.path.abspath(
      args.input_path)
  _require(benchmark.get("input_path") == input_path,
           "Resumed benchmark input path changed.")
  if input_path is not None:
    _require(os.path.isfile(input_path) and
             benchmark.get("input_sha256") ==
             stage7.fingerprint_file(input_path),
             "Resumed benchmark input identity changed.")
  collector = row.get("collector", {})
  _require(collector.get("exit_code") == 0 and
           collector.get("truncated") is False and
           collector.get("timed_out") is False and
           collector.get("lost_events") is False,
           "Resumed collection receipt is incomplete or lossy.")
  print("[resume] exact completed Stage-7 collection {}".format(
      args.workload))


if __name__ == "__main__":
  main()
