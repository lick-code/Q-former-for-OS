# coding=utf-8
"""Stage-7 preflight, suite preparation, receipts, and final verification."""

from __future__ import print_function

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage7_workloads as stage7  # noqa: E402
import audit_capd_proactive_stage7_candidates as candidate_audit  # noqa: E402


DEFAULT_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage7_workloads.json")
DEFAULT_CAPACITY = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage7_capacity.json")


def _utc_now():
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_root(args):
  return os.path.join(
      PROJECT_ROOT, "outputs", "capd_proactive_stage7",
      stage7.safe_run_id(args.run_id))


def _load(args, confirmed=False):
  config = stage7.load_json(args.config)
  capacity = stage7.load_json(args.capacity_config)
  stage7.validate_workload_config(config, require_confirmed=confirmed)
  stage7.validate_capacity_config(capacity)
  return config, capacity


def _state(root, status, completed, **extra):
  value = {
      "schema_version": "capd_proactive_stage7_run_state_v1_0",
      "contract_id": stage7.CONTRACT_ID,
      "status": status,
      "completed": list(completed),
      "test_payload_read_for_integrity":
          bool(extra.pop("test_payload_read_for_integrity", False)),
      "test_used_for_parameter_selection": False,
      "test_policy_replay_executed": False,
      "test_performance_inspected": False,
      "formal_test_performance_conclusion": None,
      "updated_at": _utc_now(),
  }
  value.update(extra)
  stage7.write_json_atomic(os.path.join(root, "run_state.json"), value)
  return value


def preflight(args):
  config, capacity = _load(args, confirmed=False)
  entry = stage7.audit_stage6_entry(config, PROJECT_ROOT)
  root = _run_root(args)
  if os.path.exists(root):
    identity_path = os.path.join(root, "run_identity.json")
    if not os.path.isfile(identity_path):
      raise stage7.Stage7ContractError(
          "Existing incomplete run directory must not be reused.")
    existing = stage7.load_json(identity_path)
    expected = {
        "config_sha256": stage7.fingerprint_file(args.config),
        "capacity_config_sha256":
            stage7.fingerprint_file(args.capacity_config),
        "run_id": args.run_id,
    }
    if any(existing.get(key) != value for key, value in expected.items()):
      raise stage7.Stage7ContractError(
          "Run identity changed; use a new run ID.")
    print("[resume] exact Stage-7 preflight {}".format(root))
    return root
  os.makedirs(root)
  audit_path = os.path.join(root, "candidate_audit.json")
  audit = candidate_audit.audit(args.config, audit_path)
  identity = {
      "schema_version": "capd_proactive_stage7_run_identity_v1_0",
      "contract_id": stage7.CONTRACT_ID,
      "run_id": args.run_id,
      "config_path": stage7.portable_path(args.config, PROJECT_ROOT),
      "config_sha256": stage7.fingerprint_file(args.config),
      "capacity_config_path":
          stage7.portable_path(args.capacity_config, PROJECT_ROOT),
      "capacity_config_sha256":
          stage7.fingerprint_file(args.capacity_config),
      "stage6_entry_audit": entry,
      "candidate_audit_sha256": stage7.fingerprint_file(audit_path),
      "suite_confirmed":
          config["suite_confirmation"]["confirmed"],
      "test_payload_read_for_integrity": False,
      "test_policy_replay_executed": False,
      "created_at": _utc_now(),
  }
  stage7.write_json_atomic(os.path.join(root, "run_identity.json"), identity)
  stage7.write_json_atomic(os.path.join(root, "resolved_config.json"), {
      "workloads": config,
      "capacity": capacity,
      "stage_status": stage7.IMPLEMENTED,
  })
  _state(root, stage7.IMPLEMENTED, ["preflight", "candidate_audit"])
  print("[OK] Stage-7 preflight {}".format(root))
  print("suite_confirmed={}".format(
      str(config["suite_confirmation"]["confirmed"]).lower()))
  print("formally_reusable_trace_count={}".format(
      audit["formally_reusable_trace_count"]))
  return root


def collection_preflight(args):
  config, _ = _load(args, confirmed=True)
  proposed = {row["workload"]: row for row in config["proposed_suite"]}
  if args.workload not in proposed:
    raise stage7.Stage7ContractError(
        "Workload is not in the confirmed six-workload suite.")
  print("[OK] confirmed Stage-7 collection target {} ({})".format(
      args.workload, proposed[args.workload]["role"]))


def prepare(args):
  config, capacity = _load(args, confirmed=True)
  root = preflight(args)
  identity = stage7.load_json(os.path.join(root, "run_identity.json"))
  if identity.get("suite_confirmed") is not True:
    raise stage7.Stage7ContractError(
        "Preflight predates suite confirmation; use a new run ID.")
  manifest = stage7.load_json(args.collection_manifest)
  result = stage7.prepare_suite(
      config, capacity, manifest, PROJECT_ROOT, root)
  _state(
      root, stage7.COLLECTION_COMPLETE,
      ["preflight", "candidate_audit", "collection", "splits",
       "working_set", "profiles", "capacity_matrix",
       "standard_test_lock", "stage8_execution_plan"],
      test_payload_read_for_integrity=True)
  print("[OK] Stage-7 collection prepared: {}".format(
      json.dumps(result, sort_keys=True)))


def _parse_test_log(text):
  match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", text)
  if not match or not re.search(r"(?m)^OK(?:\s|$)", text):
    raise stage7.Stage7ContractError(
        "Regression log lacks a recognized successful unittest receipt.")
  return {
      "tests_run": int(match.group(1)),
      "elapsed_seconds": float(match.group(2)),
      "summary_line": match.group(0),
      "success_line": "OK",
  }


def record_tests(args):
  root = _run_root(args)
  state_path = os.path.join(root, "run_state.json")
  if not os.path.isfile(state_path):
    raise stage7.Stage7ContractError("Stage-7 preflight is missing.")
  with open(args.test_log, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  parsed = _parse_test_log(text)
  if parsed["tests_run"] < args.minimum_tests:
    raise stage7.Stage7ContractError(
        "Regression coverage is below the declared Stage-7 minimum.")
  receipt = {
      "schema_version": "capd_proactive_stage7_test_receipt_v1_0",
      "contract_id": stage7.CONTRACT_ID,
      "status": "passed",
      "runner_exit_code": args.runner_exit_code,
      "minimum_tests": args.minimum_tests,
      "unittest": parsed,
      "log_path": stage7.portable_path(args.test_log, PROJECT_ROOT),
      "log_sha256": stage7.fingerprint_file(args.test_log),
      "test_policy_replay_executed": False,
      "recorded_at": _utc_now(),
  }
  if args.runner_exit_code != 0:
    raise stage7.Stage7ContractError("Regression runner returned nonzero.")
  stage7.write_json_atomic(
      os.path.join(root, "server_test_receipt.json"), receipt)
  print("[OK] Stage1-7 regression receipt recorded")


def verify(args):
  root = _run_root(args)
  receipt_path = os.path.join(root, "server_test_receipt.json")
  if not os.path.isfile(receipt_path):
    raise stage7.Stage7ContractError("Regression receipt is missing.")
  verification = stage7.verify_suite(root, stage7.load_json(receipt_path))
  verification["verified_at"] = _utc_now()
  stage7.write_json_atomic(
      os.path.join(root, "verification.json"), verification)
  _state(
      root, stage7.VERIFIED,
      ["preflight", "candidate_audit", "collection", "splits",
       "working_set", "profiles", "capacity_matrix",
       "standard_test_lock", "stage8_execution_plan",
       "stage1_stage7_regressions", "verification"],
      test_payload_read_for_integrity=True,
      stage8_entry_gate="satisfied")
  print("[FINAL] STAGE7_WORKLOAD_SUITE_VERIFIED")


def mark_not_verified(args):
  root = _run_root(args)
  os.makedirs(root, exist_ok=True)
  old = {}
  path = os.path.join(root, "run_state.json")
  if os.path.isfile(path):
    old = stage7.load_json(path)
  failures = list(old.get("failure_history", []))
  if args.failure_step not in failures:
    failures.append(args.failure_step)
  _state(
      root, stage7.NOT_VERIFIED,
      list(old.get("completed", [])),
      failure_step=args.failure_step,
      failure_history=failures,
      failure_recorded_at=_utc_now(),
      test_payload_read_for_integrity=bool(
          old.get("test_payload_read_for_integrity", False)))
  print("[FAILED] Stage-7 evidence preserved in {}".format(root))


def build_parser():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      "command",
      choices=("preflight", "collection-preflight", "prepare",
               "record-tests", "verify", "mark-not-verified"))
  parser.add_argument("--run-id", default="stage7-suite-r1")
  parser.add_argument("--config", default=DEFAULT_CONFIG)
  parser.add_argument("--capacity-config", default=DEFAULT_CAPACITY)
  parser.add_argument("--collection-manifest", default=None)
  parser.add_argument("--workload", default=None)
  parser.add_argument("--test-log", default=None)
  parser.add_argument("--runner-exit-code", type=int, default=0)
  parser.add_argument("--minimum-tests", type=int, default=180)
  parser.add_argument("--failure-step", default="unknown")
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  args.config = os.path.abspath(args.config)
  args.capacity_config = os.path.abspath(args.capacity_config)
  if args.collection_manifest:
    args.collection_manifest = os.path.abspath(args.collection_manifest)
  if args.test_log:
    args.test_log = os.path.abspath(args.test_log)
  commands = {
      "preflight": preflight,
      "collection-preflight": collection_preflight,
      "prepare": prepare,
      "record-tests": record_tests,
      "verify": verify,
      "mark-not-verified": mark_not_verified,
  }
  commands[args.command](args)


if __name__ == "__main__":
  main()
