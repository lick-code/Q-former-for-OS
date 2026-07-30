#!/usr/bin/env python3
# coding=utf-8
"""Build and verify the proactive Stage-5 Replay baseline framework.

This runner accepts Train/Validation only.  It deliberately has no formal
Test command and never upgrades the source configuration in place.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_cost  # noqa: E402
from qmap import proactive_stage4  # noqa: E402
from qmap import proactive_stage5_contract as contract  # noqa: E402
from qmap import proactive_stage5_replay as stage5_replay  # noqa: E402


CODE_ARTIFACTS = (
    "configs/finals/capd_proactive_stage5.json",
    "configs/finals/capd_proactive_stage5_result_schema.json",
    "qmap/finals_config.py",
    "qmap/qmap_eval.py",
    "qmap/qmap_generator.py",
    "qmap/candidate_filter.py",
    "qmap/no_vpn_ablation.py",
    "qmap/proactive_replay.py",
    "qmap/proactive_cost.py",
    "qmap/proactive_stage4.py",
    "qmap/proactive_stage5_contract.py",
    "qmap/proactive_stage5_policies.py",
    "qmap/proactive_stage5_replay.py",
    "policy_learning/cache_model/embed.py",
    "policy_learning/cache_model/loss.py",
    "policy_learning/cache_model/model.py",
    "scripts/run_capd_proactive_stage5.py",
    "scripts/validate_capd_proactive_stage5_server.sh",
    "tests/test_capd_proactive_stage5_contract.py",
    "tests/test_capd_proactive_stage5_replay.py",
    "tests/test_capd_proactive_stage5_e2e.py",
    "docs/CAPD_PROACTIVE_STAGE5_PROTOCOL_CN.md",
    "docs/CAPD_PROACTIVE_STAGE5_STATUS_CN.md",
    "docs/CAPD_PROACTIVE_STAGE5_SERVER_RUN_CN.md",
)
RUN_IDENTITY_BINDING_FIELDS = (
    "contract_id",
    "config_sha256",
    "stage0_sha256",
    "cost_config_sha256",
    "stage4_verification_sha256",
    "stage4_freeze_candidate_sha256",
    "stage4_dataset_manifest_sha256",
    "stage4_dataset_identity_sha256",
    "trace_sha256",
    "checkpoint_sha256",
    "acceptance",
    "code_artifacts",
)
PREFLIGHT_EVIDENCE = (
    "resolved_config.json",
    "input_manifest.json",
    "working_set_summary.json",
    "policy_registry.json",
    "run_state.json",
)
UNITTEST_SUMMARY_RE = re.compile(
    r"^Ran\s+(\d+)\s+tests?\s+in\s+([0-9]+(?:\.[0-9]+)?)s\s*$",
    re.MULTILINE)
UNITTEST_OK_RE = re.compile(
    r"^OK(?:\s+\([^\r\n]*\))?\s*$", re.MULTILINE)
UNITTEST_FAILURE_RE = re.compile(
    r"^(?:FAILED\b|ERROR:|FAIL:|Traceback \(most recent call last\):)",
    re.MULTILINE)


def _utc_now() -> str:
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ")


def _safe_run_id(value: str) -> str:
  if (not value or any(character not in
                       "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                       "0123456789-_."
                       for character in value)):
    raise contract.Stage5ContractError(
        "--run-id must be non-empty and filesystem-safe.")
  return value


def _root(args, config: Mapping[str, Any]) -> str:
  run_root = os.path.abspath(os.path.join(
      args.project_root, config["output_root"], _safe_run_id(args.run_id)))
  expected_root = os.path.abspath(os.path.join(
      args.project_root, config["output_root"]))
  if os.path.commonpath((run_root, expected_root)) != expected_root:
    raise contract.Stage5ContractError("Unsafe Stage-5 output root.")
  normalized = run_root.replace("\\", "/").lower()
  if "capd_proactive_stage5" not in normalized or "finals_v3" in normalized:
    raise contract.Stage5ContractError(
        "Run root must be isolated under capd_proactive_stage5.")
  return run_root


def _git_state(project_root: str) -> Dict[str, Any]:
  def command(*arguments):
    return subprocess.check_output(
        ["git"] + list(arguments), cwd=project_root,
        stderr=subprocess.DEVNULL, text=True).strip()
  try:
    commit = command("rev-parse", "HEAD")
    status = command("status", "--short")
    diff = subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=project_root)
  except (OSError, subprocess.CalledProcessError):
    commit, status, diff = "unknown", "unknown", b""
  return {
      "commit": commit,
      "dirty_worktree": bool(status),
      "status": status.splitlines(),
      "dirty_diff_sha256": hashlib.sha256(diff).hexdigest(),
  }


def _code_fingerprints(project_root: str) -> Dict[str, str]:
  result = {}
  for relative in CODE_ARTIFACTS:
    path = os.path.join(project_root, relative)
    if not os.path.isfile(path):
      raise contract.Stage5ContractError(
          "Required Stage-5 code artifact missing: " + relative)
    result[relative] = proactive_stage4.fingerprint_file(path)
  return result


def _load(args):
  config = contract.load_config(args.config)
  stage0 = proactive_stage4.load_json(args.stage0_config)
  cost = proactive_cost.load_cost_config(args.cost_config)
  if cost.profiles["default"].weights_dict() != contract.FROZEN_COST:
    raise contract.Stage5ContractError("Stage-2 default Cost profile changed.")
  return config, stage0, cost


def _write_state(
    run_root: str, status: str, completed: Sequence[str],
    extra: Optional[Mapping[str, Any]] = None) -> None:
  value = {
      "schema_version": contract.RUN_MANIFEST_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "status": status,
      "completed": list(completed),
      "updated_at": _utc_now(),
      "test_trace_opened": False,
      "performance_conclusion": None,
      "tpp_inspired_status": contract.PENDING_TPP,
  }
  if extra:
    value.update(dict(extra))
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "run_state.json"), value)


def _mark_run_not_verified(run_root: str, failure_step: str) -> None:
  """Atomically records an external or runner failure without deleting evidence."""
  if not failure_step:
    raise contract.Stage5ContractError("Failure step must be non-empty.")
  state_path = os.path.join(run_root, "run_state.json")
  previous = {}
  if os.path.isfile(state_path):
    previous = proactive_stage4.load_json(state_path)
  completed = list(previous.get("completed", []))
  if "failure_evidence_preserved" not in completed:
    completed.append("failure_evidence_preserved")
  history = list(previous.get("failure_history", []))
  if failure_step not in history:
    history.append(failure_step)
  _write_state(
      run_root, contract.NOT_VERIFIED, completed, {
          "failure_step": failure_step,
          "failure_history": history,
          "failure_recorded_at": _utc_now(),
          "automatic_retry": False,
      })


def _reject_failed_run_id(run_root: str) -> None:
  state_path = os.path.join(run_root, "run_state.json")
  if not os.path.isfile(state_path):
    return
  state = proactive_stage4.load_json(state_path)
  if state.get("status") == contract.NOT_VERIFIED:
    raise contract.Stage5ContractError(
        "This run-id is stage5_not_verified; preserve it and use a new "
        "run-id. Automatic retry is forbidden.")
  if state.get("status") == contract.VERIFIED:
    raise contract.Stage5ContractError(
        "This run-id is already verified and must not be rerun.")


def mark_not_verified(args) -> None:
  config = contract.load_config(args.config)
  run_root = _root(args, config)
  if not os.path.isdir(run_root):
    raise contract.Stage5ContractError(
        "Cannot mark a Stage-5 run that has no output directory.")
  _mark_run_not_verified(run_root, args.failure_step)
  print("[NOT VERIFIED] {} failed at {}".format(
      args.run_id, args.failure_step))


def _load_inputs(args, config):
  manifest, traces, entries = contract.resolve_manifest_traces(
      config, args.project_root)
  working_set = proactive_stage4.working_set_and_capacity(traces)
  return manifest, traces, entries, working_set


def preflight(args) -> str:
  config, _, _ = _load(args)
  run_root = _root(args, config)
  _reject_failed_run_id(run_root)
  os.makedirs(os.path.join(run_root, "jobs"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "artifacts"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "logs"), exist_ok=True)
  authority = contract.audit_stage4_authority(
      config, args.project_root, require_checkpoints=True)
  manifest, _, entries, working_set = _load_inputs(args, config)
  identity = {
      "contract_id": contract.CONTRACT_ID,
      "config_sha256": proactive_stage4.fingerprint_file(args.config),
      "stage0_sha256": proactive_stage4.fingerprint_file(args.stage0_config),
      "cost_config_sha256":
          proactive_stage4.fingerprint_file(args.cost_config),
      "stage4_verification_sha256": authority["verification_sha256"],
      "stage4_freeze_candidate_sha256":
          authority["freeze_candidate_sha256"],
      "stage4_dataset_manifest_sha256":
          authority["dataset_manifest_sha256"],
      "stage4_dataset_identity_sha256":
          authority["dataset_identity_sha256"],
      "trace_sha256": {
          "{}:{}".format(item["workload"], item["split"]):
              item["trace_sha256"] for item in entries},
      "checkpoint_sha256": {
          str(item["seed"]): item["sha256"]
          for item in authority["checkpoints"]},
      "acceptance": copy.deepcopy(config["framework_acceptance"]),
      "git": _git_state(args.project_root),
      "code_artifacts": _code_fingerprints(args.project_root),
  }
  identity["run_identity_sha256"] = proactive_stage4.fingerprint_value(identity)
  identity_path = os.path.join(run_root, "run_identity.json")
  if os.path.isfile(identity_path):
    existing_identity = proactive_stage4.load_json(identity_path)
    if any(existing_identity.get(key) != identity.get(key)
           for key in RUN_IDENTITY_BINDING_FIELDS):
      raise contract.Stage5ContractError(
          "Existing run-id has a different data/config/code identity.")
    missing_evidence = [
        filename for filename in PREFLIGHT_EVIDENCE
        if not os.path.isfile(os.path.join(run_root, filename))]
    if missing_evidence:
      raise contract.Stage5ContractError(
          "Existing preflight is incomplete; preserve it and use a new "
          "run-id. Missing: " + ", ".join(missing_evidence))
    print("[resume] exact preflight {}".format(run_root))
    return run_root
  proactive_stage4.write_json_atomic(identity_path, identity)
  resolved = copy.deepcopy(config)
  resolved["run"] = {
      "run_id": args.run_id,
      "created_at": _utc_now(),
      "output_directory": run_root,
      "run_identity_sha256": identity["run_identity_sha256"],
      "command": list(sys.argv),
      "machine_information": {
          "platform": platform.platform(),
          "python": sys.version,
          "processor": platform.processor(),
      },
  }
  resolved["stage4_authority_resolved"] = authority
  resolved["working_set"] = working_set
  resolved["input_entries"] = entries
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "resolved_config.json"), resolved)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "input_manifest.json"), manifest)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "working_set_summary.json"), working_set)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "policy_registry.json"), {
          "schema_version": contract.SCHEMA_VERSION,
          "formal_mainline": list(contract.FORMAL_POLICIES),
          "runnable_stage5": list(contract.RUNNABLE_POLICIES),
          "tpp_inspired": {
              "status": contract.PENDING_TPP,
              "fallback_allowed": False,
              "result_artifact_allowed": False,
          },
      })
  _write_state(run_root, contract.IMPLEMENTED, ["preflight"])
  print("[OK] stage5 preflight {}".format(run_root))
  return run_root


def _loaded_run(args):
  config, stage0, cost = _load(args)
  run_root = _root(args, config)
  identity_path = os.path.join(run_root, "run_identity.json")
  if not os.path.isfile(identity_path):
    raise contract.Stage5ContractError("Run has not passed preflight.")
  expected = proactive_stage4.load_json(identity_path)
  current_bindings = {
      "config_sha256": proactive_stage4.fingerprint_file(args.config),
      "stage0_sha256": proactive_stage4.fingerprint_file(args.stage0_config),
      "cost_config_sha256":
          proactive_stage4.fingerprint_file(args.cost_config),
  }
  if any(expected.get(key) != value
         for key, value in current_bindings.items()):
    raise contract.Stage5ContractError(
        "Stage-5 config/Stage-0/Cost binding changed after preflight.")
  current_code = _code_fingerprints(args.project_root)
  if current_code != expected["code_artifacts"]:
    raise contract.Stage5ContractError(
        "Stage-5 code changed after preflight; use a new run-id.")
  authority = contract.audit_stage4_authority(
      config, args.project_root, require_checkpoints=True)
  authority_bindings = {
      "stage4_verification_sha256": authority["verification_sha256"],
      "stage4_freeze_candidate_sha256":
          authority["freeze_candidate_sha256"],
      "stage4_dataset_manifest_sha256":
          authority["dataset_manifest_sha256"],
      "stage4_dataset_identity_sha256":
          authority["dataset_identity_sha256"],
      "checkpoint_sha256": {
          str(item["seed"]): item["sha256"]
          for item in authority["checkpoints"]},
  }
  if any(expected.get(key) != value
         for key, value in authority_bindings.items()):
    raise contract.Stage5ContractError(
        "Stage-4 verification/freeze/dataset/checkpoint authority changed "
        "after preflight.")
  manifest, traces, entries, working_set = _load_inputs(args, config)
  current_trace_sha256 = {
      "{}:{}".format(item["workload"], item["split"]):
          item["trace_sha256"] for item in entries}
  if current_trace_sha256 != expected.get("trace_sha256"):
    raise contract.Stage5ContractError(
        "Train/Validation Trace identity changed after preflight.")
  del manifest
  return run_root, config, stage0, cost, authority, traces, entries, working_set


def _entry(entries, workload, split):
  matches = [
      item for item in entries
      if item["workload"] == workload and item["split"] == split]
  if len(matches) != 1:
    raise contract.Stage5ContractError(
        "Expected one input entry for {}/{}.".format(workload, split))
  return matches[0]


def _job_name(workload: str, split: str, policy: str,
              seed: Optional[int]) -> str:
  return "{}__{}__{}__seed-{}".format(
      workload, split, policy, "na" if seed is None else seed)


def _job_paths(run_root: str, job_name: str) -> Dict[str, str]:
  directory = os.path.join(run_root, "jobs", job_name)
  return {
      "directory": directory,
      "manifest": os.path.join(directory, "job_manifest.json"),
      "result": os.path.join(directory, "result.json"),
  }


def _run_job(
    run_root, config, stage0, cost, authority, trace, entry, working_set,
    policy, checkpoint=None, measure_latency=True):
  seed = None if checkpoint is None else int(checkpoint["seed"])
  name = _job_name(entry["workload"], entry["split"], policy, seed)
  paths = _job_paths(run_root, name)
  os.makedirs(paths["directory"], exist_ok=True)
  identity = {
      "run_identity_sha256": proactive_stage4.load_json(os.path.join(
          run_root, "run_identity.json"))["run_identity_sha256"],
      "job_name": name,
      "policy": policy,
      "seed": seed,
      "workload": entry["workload"],
      "split": entry["split"],
      "trace_sha256": entry["trace_sha256"],
      "source_interval": entry["source_interval"],
      "accesses": len(trace),
      "checkpoint_sha256":
          None if checkpoint is None else checkpoint["sha256"],
      "measure_latency": bool(measure_latency),
  }
  identity_sha = proactive_stage4.fingerprint_value(identity)
  if os.path.isfile(paths["manifest"]):
    existing = proactive_stage4.load_json(paths["manifest"])
    if existing.get("job_identity_sha256") != identity_sha:
      raise contract.Stage5ContractError(
          "Existing job identity differs; use a new run-id: " + name)
    if existing.get("status") == "completed":
      if (not os.path.isfile(paths["result"]) or
          proactive_stage4.fingerprint_file(paths["result"]) !=
          existing.get("result_sha256")):
        raise contract.Stage5ContractError(
            "Completed job result is missing/corrupt: " + name)
      print("[resume] exact completed job {}".format(name))
      return proactive_stage4.load_json(paths["result"])
    raise contract.Stage5ContractError(
        "Existing incomplete/failed job is preserved; no automatic retry: "
        + name)
  manifest = {
      "schema_version": "capd_proactive_stage5_job_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "job_identity": identity,
      "job_identity_sha256": identity_sha,
      "status": "running",
      "started_at": _utc_now(),
      "automatic_retry": False,
  }
  proactive_stage4.write_json_atomic(paths["manifest"], manifest)
  try:
    result = stage5_replay.run_replay(
        stage0, config, cost, trace, policy,
        workload=entry["workload"],
        split=entry["split"],
        split_role=entry["role"],
        source_interval=entry["source_interval"],
        trace_sha256=entry["trace_sha256"],
        dram_capacity_pages=working_set["dram_capacity_pages"],
        working_set_pages=working_set["union_working_set_pages"],
        checkpoint=checkpoint,
        device=args_device(config),
        measure_latency=measure_latency)
    proactive_stage4.write_json_atomic(paths["result"], result)
  except Exception as error:
    manifest.update({
        "status": "failed",
        "failed_at": _utc_now(),
        "error_type": type(error).__name__,
        "error": str(error),
    })
    proactive_stage4.write_json_atomic(paths["manifest"], manifest)
    raise
  manifest.update({
      "status": "completed",
      "completed_at": _utc_now(),
      "result_sha256": proactive_stage4.fingerprint_file(paths["result"]),
      "semantic_result_sha256": result["semantic_result_sha256"],
  })
  proactive_stage4.write_json_atomic(paths["manifest"], manifest)
  print("[OK] {}".format(name))
  return result


_DEVICE = "cpu"


def args_device(config):
  del config
  return _DEVICE


def run_acceptance(args) -> None:
  global _DEVICE
  _DEVICE = args.device
  (run_root, config, stage0, cost, authority, traces, entries,
   working_set) = _loaded_run(args)
  split = config["framework_acceptance"]["split"]
  max_accesses = int(
      config["framework_acceptance"]["max_accesses_per_workload"])
  for workload in sorted(traces):
    entry = _entry(entries, workload, split)
    trace = traces[workload][split][:max_accesses]
    expected_end = entry["source_interval"]["start"] + len(trace)
    scoped_entry = copy.deepcopy(entry)
    scoped_entry["source_interval"] = {
        "start": entry["source_interval"]["start"], "end": expected_end}
    for policy in ("proactive_lru", "proactive_clock", "oracle",
                   "reactive_lru"):
      _run_job(
          run_root, config, stage0, cost, authority, trace, scoped_entry,
          working_set[workload], policy)
    for checkpoint in authority["checkpoints"]:
      _run_job(
          run_root, config, stage0, cost, authority, trace, scoped_entry,
          working_set[workload], "capd", checkpoint=checkpoint)
  _write_state(run_root, contract.IMPLEMENTED, [
      "preflight", "validation_acceptance_replays"])
  print("[OK] validation acceptance replays completed")


def _synthetic_trace() -> List[Dict[str, int]]:
  trace = []
  for page in range(1, 29):
    trace.append({"page": page, "rw": int(page % 7 == 0), "pc": page % 5})
  trace.extend([
      {"page": 2, "rw": 0, "pc": 1},
      {"page": 5, "rw": 1, "pc": 1},
      {"page": 29, "rw": 0, "pc": 2},
      {"page": 30, "rw": 1, "pc": 2},
      {"page": 3, "rw": 0, "pc": 3},
      {"page": 31, "rw": 0, "pc": 3},
      {"page": 32, "rw": 1, "pc": 4},
  ])
  return trace


def synthetic(args) -> None:
  global _DEVICE
  _DEVICE = args.device
  run_root, config, stage0, cost, authority, _, _, _ = _loaded_run(args)
  trace = _synthetic_trace()
  trace_sha = proactive_stage4.fingerprint_value(trace)
  entry = {
      "workload": "synthetic_stage5",
      "split": "validation",
      "role": "parameter_selection",
      "source_interval": {"start": 0, "end": len(trace)},
      "trace_sha256": trace_sha,
  }
  ws = {
      "dram_capacity_pages": 20,
      "union_working_set_pages": len({row["page"] for row in trace}),
  }
  rows = []
  for policy in ("proactive_lru", "proactive_clock", "oracle",
                 "reactive_lru"):
    rows.append(_run_job(
        run_root, config, stage0, cost, authority, trace, entry, ws, policy,
        measure_latency=False))
  for checkpoint in authority["checkpoints"]:
    rows.append(_run_job(
        run_root, config, stage0, cost, authority, trace, entry, ws, "capd",
        checkpoint=checkpoint, measure_latency=False))
  experiment_a = contract.check_experiment_a([
      row for row in rows if row["policy"] not in ("reactive_lru",)])
  experiment_b = contract.check_experiment_b([
      row for row in rows
      if row["policy"] in ("reactive_lru", "proactive_lru")])
  receipt = {
      "schema_version": "capd_proactive_stage5_synthetic_receipt_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "experiment_A": experiment_a,
      "experiment_B": experiment_b,
      "tpp_inspired_status": contract.PENDING_TPP,
      "tpp_fallback_used": False,
      "test_trace_opened": False,
      "performance_conclusion": None,
      "completed_at": _utc_now(),
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "synthetic_e2e_receipt.json"), receipt)
  _write_state(run_root, contract.IMPLEMENTED, ["preflight", "synthetic_e2e"])
  print("[OK] synthetic experiment A/B contracts")


def fairness(args) -> None:
  run_root, config, _, _, _, _, _, _ = _loaded_run(args)
  split = config["framework_acceptance"]["split"]
  resolved = proactive_stage4.load_json(os.path.join(
      run_root, "resolved_config.json"))
  reports = {}
  for workload in sorted(resolved["working_set"]):
    rows = []
    for directory in os.listdir(os.path.join(run_root, "jobs")):
      if directory.startswith("{}__{}__".format(workload, split)):
        path = os.path.join(run_root, "jobs", directory, "result.json")
        if os.path.isfile(path):
          rows.append(proactive_stage4.load_json(path))
    experiment_a_rows = [
        row for row in rows if row["policy"] in (
            "proactive_lru", "proactive_clock", "capd", "oracle")]
    experiment_b_rows = [
        row for row in rows if row["policy"] in (
            "reactive_lru", "proactive_lru")]
    reports[workload] = {
        "experiment_A": contract.check_experiment_a(experiment_a_rows),
        "experiment_B": contract.check_experiment_b(experiment_b_rows),
    }
  output = {
      "schema_version": "capd_proactive_stage5_fairness_suite_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "workloads": reports,
      "test_trace_opened": False,
      "performance_conclusion": None,
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "fairness_audit.json"), output)
  _write_state(run_root, contract.IMPLEMENTED, [
      "preflight", "validation_acceptance_replays", "fairness_audit"])
  print("[OK] experiment A/B fairness audit")


def _parse_successful_unittest_log(text: str) -> Dict[str, Any]:
  """Returns the canonical unittest summary even if tests print afterwards."""
  if UNITTEST_FAILURE_RE.search(text):
    raise contract.Stage5ContractError(
        "Regression log contains a unittest failure marker.")
  summaries = list(UNITTEST_SUMMARY_RE.finditer(text))
  if not summaries:
    raise contract.Stage5ContractError(
        "Regression log lacks the canonical 'Ran N tests' summary.")
  summary = summaries[-1]
  successes = [
      match for match in UNITTEST_OK_RE.finditer(text)
      if match.start() > summary.end()]
  if not successes:
    raise contract.Stage5ContractError(
        "Regression log lacks canonical unittest OK after its summary.")
  tests_run = int(summary.group(1))
  if tests_run <= 0:
    raise contract.Stage5ContractError(
        "Regression log reports no executed tests.")
  return {
      "tests_run": tests_run,
      "elapsed_seconds": float(summary.group(2)),
      "summary_line": summary.group(0).strip(),
      "success_line": successes[-1].group(0).strip(),
  }


def record_tests(args) -> None:
  run_root, _, _, _, _, _, _, _ = _loaded_run(args)
  if args.test_exit_code != 0:
    raise contract.Stage5ContractError(
        "Regression runner exit code was not zero.")
  if not os.path.isfile(args.test_log):
    raise contract.Stage5ContractError("Test log does not exist.")
  test_log = os.path.abspath(args.test_log)
  if os.path.commonpath((test_log, run_root)) != run_root:
    raise contract.Stage5ContractError(
        "Regression log must be inside the current Stage-5 run.")
  with open(args.test_log, "r", encoding="utf-8", errors="replace") as source:
    text = source.read()
  unittest_summary = _parse_successful_unittest_log(text)
  proactive_stage4.write_json_atomic(os.path.join(
      run_root, "server_test_receipt.json"), {
          "schema_version": "capd_proactive_stage5_test_receipt_v1_0",
          "contract_id": contract.CONTRACT_ID,
          "status": "passed",
          "log_path": os.path.relpath(
              test_log, args.project_root).replace("\\", "/"),
          "log_sha256": proactive_stage4.fingerprint_file(args.test_log),
          "runner_exit_code": int(args.test_exit_code),
          "unittest": unittest_summary,
          "stage1_through_stage5_regression_requested": True,
          "test_trace_opened": False,
          "recorded_at": _utc_now(),
      })
  print("[OK] server regression receipt recorded")


def verify(args) -> None:
  run_root, config, _, _, authority, _, _, _ = _loaded_run(args)
  required = (
      "synthetic_e2e_receipt.json", "fairness_audit.json",
      "server_test_receipt.json")
  for filename in required:
    if not os.path.isfile(os.path.join(run_root, filename)):
      raise contract.Stage5ContractError(
          "Verification evidence missing: " + filename)
    evidence = proactive_stage4.load_json(os.path.join(run_root, filename))
    if evidence.get("status") != "passed":
      raise contract.Stage5ContractError(
          "Verification evidence did not pass: " + filename)
    if evidence.get("test_trace_opened") is not False:
      raise contract.Stage5ContractError(
          "Verification evidence reports Test contamination.")
  test_receipt = proactive_stage4.load_json(os.path.join(
      run_root, "server_test_receipt.json"))
  if (test_receipt.get("runner_exit_code") != 0 or
      test_receipt.get("stage1_through_stage5_regression_requested")
      is not True):
    raise contract.Stage5ContractError(
        "Regression receipt lacks a successful runner exit contract.")
  test_log_path = contract.resolve_repository_path(
      test_receipt.get("log_path"), args.project_root,
      ("outputs/capd_proactive_stage5",), must_exist=True)
  if proactive_stage4.fingerprint_file(test_log_path) != (
      test_receipt.get("log_sha256")):
    raise contract.Stage5ContractError(
        "Regression log changed after its receipt was recorded.")
  with open(test_log_path, "r", encoding="utf-8",
            errors="replace") as source:
    parsed_unittest = _parse_successful_unittest_log(source.read())
  if parsed_unittest != test_receipt.get("unittest"):
    raise contract.Stage5ContractError(
        "Regression unittest summary differs from its receipt.")
  registry = proactive_stage4.load_json(os.path.join(
      run_root, "policy_registry.json"))
  if (registry["tpp_inspired"]["status"] != contract.PENDING_TPP or
      registry["tpp_inspired"]["fallback_allowed"] is not False or
      registry["tpp_inspired"]["result_artifact_allowed"] is not False):
    raise contract.Stage5ContractError("TPP pending-stage contract changed.")
  if sorted(item["seed"] for item in authority["checkpoints"]) != sorted(
      contract.CAPD_SEEDS):
    raise contract.Stage5ContractError("CAPD checkpoint set is incomplete.")
  expected_checkpoints = {
      int(item["seed"]): item["sha256"] for item in authority["checkpoints"]}
  resolved = proactive_stage4.load_json(os.path.join(
      run_root, "resolved_config.json"))
  split = config["framework_acceptance"]["split"]
  expected_jobs = set()
  for workload in resolved["working_set"]:
    for policy in ("proactive_lru", "proactive_clock", "oracle",
                   "reactive_lru"):
      expected_jobs.add(_job_name(workload, split, policy, None))
    for seed in contract.CAPD_SEEDS:
      expected_jobs.add(_job_name(workload, split, "capd", seed))
  for job_name in sorted(expected_jobs):
    paths = _job_paths(run_root, job_name)
    if not os.path.isfile(paths["manifest"]) or not os.path.isfile(
        paths["result"]):
      raise contract.Stage5ContractError(
          "Required acceptance job is missing: " + job_name)
    job_manifest = proactive_stage4.load_json(paths["manifest"])
    if (job_manifest.get("status") != "completed" or
        job_manifest.get("result_sha256") !=
        proactive_stage4.fingerprint_file(paths["result"])):
      raise contract.Stage5ContractError(
          "Required acceptance job is incomplete/corrupt: " + job_name)
    result = proactive_stage4.load_json(paths["result"])
    contract.audit_result(result)
    if result["policy"] == "capd":
      seed = int(result["seed"])
      if result["checkpoint"]["sha256"] != expected_checkpoints.get(seed):
        raise contract.Stage5ContractError(
            "CAPD result checkpoint is outside the Stage-4 freeze chain.")
  for directory in os.listdir(os.path.join(run_root, "jobs")):
    result_path = os.path.join(run_root, "jobs", directory, "result.json")
    if os.path.isfile(result_path):
      result = proactive_stage4.load_json(result_path)
      if result.get("policy") == "tpp_inspired":
        raise contract.Stage5ContractError(
            "TPP result exists even though implementation is pending.")
  fairness_value = proactive_stage4.load_json(os.path.join(
      run_root, "fairness_audit.json"))
  for workload, report in fairness_value["workloads"].items():
    if (report["experiment_A"]["status"] != "passed" or
        report["experiment_B"]["status"] != "passed"):
      raise contract.Stage5ContractError(
          "Fairness failed for " + workload)
  verification = {
      "schema_version": "capd_proactive_stage5_verification_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": contract.VERIFIED,
      "verified_at": _utc_now(),
      "framework_scope":
          "Train/Validation acceptance and synthetic E2E; no formal Test",
      "runnable_policies": list(contract.RUNNABLE_POLICIES),
      "formal_mainline": list(contract.FORMAL_POLICIES),
      "capd_seeds": list(contract.CAPD_SEEDS),
      "tpp_inspired_status": contract.PENDING_TPP,
      "selector_status": "disabled",
      "old_finals_v3_stage_artifacts_used": False,
      "test_trace_opened": False,
      "performance_conclusion": None,
      "stage6_entry_gate": "satisfied",
      "evidence_sha256": {
          filename: proactive_stage4.fingerprint_file(os.path.join(
              run_root, filename)) for filename in required},
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "verification.json"), verification)
  _write_state(run_root, contract.VERIFIED, [
      "preflight", "synthetic_e2e", "validation_acceptance_replays",
      "fairness_audit", "server_regressions", "verification"])
  print("[FINAL] STAGE5_BASELINE_FRAMEWORK_VERIFIED")


def run_all(args) -> None:
  preflight(args)
  synthetic(args)
  run_acceptance(args)
  fairness(args)
  if not args.test_log or args.test_exit_code is None:
    raise contract.Stage5ContractError(
        "all requires --test-log and --test-exit-code from a real "
        "regression run.")
  record_tests(args)
  verify(args)


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "command", choices=(
          "preflight", "synthetic", "run-acceptance", "fairness",
          "record-tests", "verify", "all", "mark-not-verified"))
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  parser.add_argument(
      "--config", default=os.path.join(
          PROJECT_ROOT, "configs/finals/capd_proactive_stage5.json"))
  parser.add_argument(
      "--stage0-config", default=os.path.join(
          PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"))
  parser.add_argument(
      "--cost-config", default=os.path.join(
          PROJECT_ROOT,
          "configs/finals/capd_proactive_stage2_cost_profiles.json"))
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--test-log")
  parser.add_argument("--test-exit-code", type=int)
  parser.add_argument("--failure-step")
  return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
  args = build_parser().parse_args(argv)
  args.project_root = os.path.abspath(args.project_root)
  global _DEVICE
  _DEVICE = args.device
  commands = {
      "preflight": preflight,
      "synthetic": synthetic,
      "run-acceptance": run_acceptance,
      "fairness": fairness,
      "record-tests": record_tests,
      "verify": verify,
      "all": run_all,
      "mark-not-verified": mark_not_verified,
  }
  try:
    if args.command == "mark-not-verified" and not args.failure_step:
      raise contract.Stage5ContractError(
          "mark-not-verified requires --failure-step.")
    if args.command == "record-tests" and (
        not args.test_log or args.test_exit_code is None):
      raise contract.Stage5ContractError(
          "record-tests requires --test-log and --test-exit-code.")
    commands[args.command](args)
  except Exception:
    try:
      config = contract.load_config(args.config)
      run_root = _root(args, config)
      if os.path.isdir(run_root):
        _mark_run_not_verified(run_root, args.command)
    except Exception:
      pass
    raise


if __name__ == "__main__":
  main()
