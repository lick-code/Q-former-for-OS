# coding=utf-8
"""Seal one completed Stage-7 trace into a collection manifest."""

from __future__ import print_function

import argparse
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage7_workloads as stage7  # noqa: E402


def _utc_now():
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _command(args, default=None):
  try:
    return subprocess.check_output(
        args, cwd=PROJECT_ROOT, stderr=subprocess.STDOUT,
        universal_newlines=True).strip()
  except (OSError, subprocess.CalledProcessError):
    return default


def _memory():
  try:
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
      return handle.readline().strip()
  except OSError:
    return "unavailable"


def _aslr():
  try:
    with open("/proc/sys/kernel/randomize_va_space", "r",
              encoding="ascii") as handle:
      return handle.read().strip()
  except OSError:
    return "unavailable"


def _sha(path, required=True):
  if not path:
    return None
  if required and not os.path.isfile(path):
    raise stage7.Stage7ContractError("Missing file: {}".format(path))
  return stage7.fingerprint_file(path) if os.path.isfile(path) else None


def _count_identity(path):
  pids = set()
  tids = set()
  count = 0
  for record in stage7.iter_trace(path, 12):
    pids.add(record["pid"])
    tids.add(record["tid"])
    count += 1
  if len(pids) != 1 or len(tids) != 1:
    raise stage7.Stage7ContractError(
        "Formal Trace must contain exactly one PID and one TID; "
        "observed PID={} TID={}.".format(sorted(pids), sorted(tids)))
  return count, sorted(pids), sorted(tids)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--manifest", required=True)
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--workload", required=True)
  parser.add_argument("--role", required=True, choices=stage7.ROLES)
  parser.add_argument("--source-trace-id", required=True)
  parser.add_argument("--raw-trace", required=True)
  parser.add_argument("--binary", required=True)
  parser.add_argument("--benchmark-version", required=True)
  parser.add_argument("--input-name", required=True)
  parser.add_argument("--input-path", default=None)
  parser.add_argument("--collector-version", required=True)
  parser.add_argument("--collector-command", required=True)
  parser.add_argument("--collector-log", required=True)
  parser.add_argument("--started-at", required=True)
  parser.add_argument("--ended-at", default=None)
  parser.add_argument("--exit-code", type=int, required=True)
  parser.add_argument("--total-accesses", type=int, default=3000000)
  parser.add_argument("--train-end", type=int, default=1800000)
  parser.add_argument("--validation-end", type=int, default=2400000)
  parser.add_argument("--thread-parameter", type=int, default=1)
  parser.add_argument("--timed-out", action="store_true")
  parser.add_argument("--truncated", action="store_true")
  parser.add_argument("--lost-events", action="store_true")
  parser.add_argument(
      "--dirty-worktree", choices=("true", "false"), default=None,
      help="Optional pre-audited source dirty state.")
  parser.add_argument("benchmark_command", nargs=argparse.REMAINDER)
  args = parser.parse_args()
  stage7.safe_run_id(args.run_id)
  if args.exit_code != 0:
    raise stage7.Stage7ContractError(
        "Cannot seal a failed collection.")
  if args.thread_parameter != 1:
    raise stage7.Stage7ContractError(
        "Stage 7 accepts only thread_parameter=1.")
  raw_trace = os.path.abspath(args.raw_trace)
  count, pids, tids = _count_identity(raw_trace)
  if count != args.total_accesses:
    raise stage7.Stage7ContractError(
        "Trace access count {} differs from declared {}.".format(
            count, args.total_accesses))
  splits = {
      "train": [0, args.train_end],
      "validation": [args.train_end, args.validation_end],
      "test": [args.validation_end, args.total_accesses],
  }
  stage7.validate_intervals(splits, args.total_accesses)
  # Formal raw/view traces can be multi-gigabyte untracked artifacts on a
  # mounted Windows volume. Scanning them here once per workload is both slow
  # and unrelated to the source-state audit. Tracked modifications are enough
  # to attest this run's code state; run_identity.json separately fingerprints
  # every Stage-7 config and final artifacts carry their own SHA-256.
  git_status = None
  if args.dirty_worktree is None:
    git_status = _command([
        "git", "status", "--porcelain", "--untracked-files=no"], "")
    dirty_worktree = bool(git_status)
  else:
    dirty_worktree = args.dirty_worktree == "true"
  row = {
      "workload": args.workload,
      "role": args.role,
      "source_trace_id": args.source_trace_id,
      "raw_trace_path": stage7.portable_path(raw_trace, PROJECT_ROOT),
      "raw_trace_sha256": _sha(raw_trace),
      "raw_trace_accesses": count,
      "page_shift": 12,
      "columns": ["PID", "TID", "PC", "Address", "RW"],
      "process_ids": pids,
      "thread_ids": tids,
      "model_training_used": False,
      "capd_checkpoint_retrained": False,
      "tpp_parameters_reselected": False,
      "benchmark": {
          "name": args.workload,
          "version": args.benchmark_version,
          "binary_path": os.path.abspath(args.binary),
          "binary_sha256": _sha(os.path.abspath(args.binary)),
          "input_name": args.input_name,
          "input_path": (
              os.path.abspath(args.input_path) if args.input_path else None),
          "input_sha256": (
              _sha(os.path.abspath(args.input_path))
              if args.input_path else None),
          "command": (
              args.benchmark_command[1:]
              if args.benchmark_command[:1] == ["--"]
              else args.benchmark_command),
          "thread_parameter": args.thread_parameter,
      },
      "collector": {
          "name": "DynamoRIO drmemtrace",
          "version": args.collector_version,
          "command": args.collector_command,
          "started_at": args.started_at,
          "ended_at": args.ended_at or _utc_now(),
          "exit_code": args.exit_code,
          "stdout_log": stage7.portable_path(
              os.path.abspath(args.collector_log), PROJECT_ROOT),
          "stderr_log": stage7.portable_path(
              os.path.abspath(args.collector_log), PROJECT_ROOT),
          "combined_stdout_stderr": True,
          "truncated": args.truncated,
          "timed_out": args.timed_out,
          "lost_events": args.lost_events,
      },
      "environment": {
          "machine": socket.gethostname(),
          "cpu": platform.processor() or _command(
              ["bash", "-lc", "lscpu | grep 'Model name' | head -1"],
              "unavailable"),
          "memory": _memory(),
          "os": platform.platform(),
          "git_commit": _command(["git", "rev-parse", "HEAD"], "unavailable"),
          "dirty_worktree": dirty_worktree,
          "aslr": _aslr(),
      },
      "splits": splits,
  }
  manifest_path = os.path.abspath(args.manifest)
  if os.path.isfile(manifest_path):
    manifest = stage7.load_json(manifest_path)
    if (manifest.get("schema_version") != stage7.COLLECTION_SCHEMA_VERSION or
        manifest.get("contract_id") != stage7.CONTRACT_ID or
        manifest.get("run_id") != args.run_id):
      raise stage7.Stage7ContractError(
          "Existing collection manifest identity changed.")
  else:
    manifest = {
        "schema_version": stage7.COLLECTION_SCHEMA_VERSION,
        "contract_id": stage7.CONTRACT_ID,
        "run_id": args.run_id,
        "suite_confirmed": True,
        "test_payload_read_for_integrity": True,
        "test_used_for_parameter_selection": False,
        "test_policy_replay_executed": False,
        "test_performance_inspected": False,
        "collections": [],
    }
  existing = {
      item["workload"]: item for item in manifest["collections"]}
  if dirty_worktree:
    # The dirty state is monotonic inside one run. This also corrects an older
    # receipt whose expensive git-status probe was interrupted before later
    # local workloads were sealed.
    for item in existing.values():
      item.setdefault("environment", {})["dirty_worktree"] = True
  if args.workload in existing and existing[args.workload] != row:
    raise stage7.Stage7ContractError(
        "Workload collection already exists with another identity; "
        "use a new run ID.")
  existing[args.workload] = row
  manifest["collections"] = [
      existing[name] for name in sorted(existing)]
  stage7.write_json_atomic(manifest_path, manifest)
  print("[OK] sealed {} accesses for {} PID={} TID={}".format(
      count, args.workload, pids, tids))
  print("raw_trace_sha256={}".format(row["raw_trace_sha256"]))
  print("collection_manifest={}".format(manifest_path))


if __name__ == "__main__":
  main()
