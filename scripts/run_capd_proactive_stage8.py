#!/usr/bin/env python3
# coding=utf-8
"""Stage-8 preflight, 144-job execution, aggregation, and verification."""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_stage7_workloads as stage7
from qmap import proactive_stage5_replay
from qmap import proactive_stage8_contract as contract
from qmap import proactive_stage8_replay
from qmap import proactive_stage8_results


CODE_FILES = (
    "qmap/finals_config.py", "qmap/proactive_stage4.py",
    "qmap/proactive_replay.py", "qmap/proactive_cost.py",
    "qmap/proactive_stage5_contract.py",
    "qmap/proactive_stage5_policies.py", "qmap/proactive_stage5_replay.py",
    "qmap/proactive_stage6_contract.py", "qmap/proactive_stage6_tpp.py",
    "qmap/proactive_stage6_replay.py", "qmap/qmap_eval.py",
    "policy_learning/cache_model/embed.py",
    "policy_learning/cache_model/model.py",
    "qmap/proactive_stage8_contract.py", "qmap/proactive_stage8_replay.py",
    "qmap/proactive_stage8_results.py", "scripts/run_capd_proactive_stage8.py",
    "scripts/validate_capd_proactive_stage8_server.sh")


def _utc_now() -> str:
  return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


def _root(args, config: Mapping[str, Any]) -> str:
  stage7.safe_run_id(args.run_id)
  return os.path.join(args.project_root, config["output_root"], args.run_id)


def _load(args):
  config = contract.load_json(args.config)
  contract.validate_config(config)
  stage0 = finals_config.load_config(args.stage0_config)
  finals_config.validate_config(stage0)
  cost = proactive_cost.load_cost_config(args.cost_config)
  return config, stage0, cost


def _code_fingerprints(project_root: str) -> Dict[str, str]:
  return {path: contract.fingerprint_file(os.path.join(project_root, path))
          for path in CODE_FILES}


def _runtime_environment(config: Mapping[str, Any], device: str) -> Dict[str, Any]:
  expected = config["deterministic_runtime"]
  actual = {
      "CUBLAS_WORKSPACE_CONFIG": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
      "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED")}
  if actual["PYTHONHASHSEED"] != expected["pythonhashseed"]:
    raise contract.Stage8ContractError(
        "PYTHONHASHSEED must be set to {} before Python starts.".format(
            expected["pythonhashseed"]))
  if str(device).lower().startswith("cuda") and (
      actual["CUBLAS_WORKSPACE_CONFIG"] !=
      expected["cublas_workspace_config"]):
    raise contract.Stage8ContractError(
        "CUDA deterministic Replay requires CUBLAS_WORKSPACE_CONFIG={}.".format(
            expected["cublas_workspace_config"]))
  return actual


def _git_state(project_root: str) -> Dict[str, Any]:
  try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root).decode().strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=project_root).decode().strip()
    return {"commit": commit, "dirty_worktree": bool(status)}
  except (OSError, subprocess.CalledProcessError):
    return {"commit": "unknown", "dirty_worktree": None}


def _state_path(run_root: str) -> str:
  return os.path.join(run_root, "run_state.json")


def _write_state(run_root: str, status: str, completed: Sequence[str],
                 failure_step: Optional[str] = None) -> None:
  path = _state_path(run_root)
  previous = contract.load_json(path) if os.path.isfile(path) else {}
  history = list(previous.get("failure_history", []))
  if failure_step and failure_step not in history:
    history.append(failure_step)
  contract.write_json_atomic(path, {
      "schema_version": "capd_proactive_stage8_run_state_v1_0",
      "contract_id": contract.CONTRACT_ID, "status": status,
      "completed": list(completed), "failure_step": failure_step,
      "failure_history": history, "updated_at": _utc_now(),
      "test_used_for_parameter_selection": False,
      "automatic_retry": False})


def mark_not_verified(args) -> None:
  config, _, _ = _load(args)
  run_root = _root(args, config)
  os.makedirs(run_root, exist_ok=True)
  old = contract.load_json(_state_path(run_root)) if os.path.isfile(
      _state_path(run_root)) else {}
  _write_state(run_root, contract.NOT_VERIFIED,
               old.get("completed", []), args.failure_step)
  print("[NOT VERIFIED] {} failed at {}".format(args.run_id, args.failure_step))


def _reject_failed_run(run_root: str) -> None:
  path = _state_path(run_root)
  if os.path.isfile(path) and contract.load_json(path).get("status") == contract.NOT_VERIFIED:
    raise contract.Stage8ContractError(
        "Failed Stage-8 evidence is preserved; use a new run ID.")


def preflight(args) -> str:
  config, _, _ = _load(args)
  runtime_environment = _runtime_environment(config, args.device)
  run_root = _root(args, config)
  _reject_failed_run(run_root)
  os.makedirs(os.path.join(run_root, "jobs"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "artifacts"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "logs"), exist_ok=True)
  authority = contract.audit_authority(
      config, args.project_root, hash_test_payloads=True)
  identity = {
      "contract_id": contract.CONTRACT_ID,
      "config_sha256": contract.fingerprint_file(args.config),
      "stage0_sha256": contract.fingerprint_file(args.stage0_config),
      "cost_config_sha256": contract.fingerprint_file(args.cost_config),
      "result_schema_sha256": contract.fingerprint_file(os.path.join(
          args.project_root, config["result_schema"])),
      "stage7_authority_sha256": {
          name: row["sha256"] for name, row in config["stage7_authority"].items()},
      "entry_authority_sha256": {
          name: row["sha256"] for name, row in config["entry_authority"].items()},
      "test_payload_sha256": {
          row["workload"]: row["sha256"] for row in authority["lock"]["workloads"]},
      "checkpoint_sha256": {
          str(seed): binding[1]
          for seed, binding in authority["checkpoint_bindings"].items()},
      "checkpoint_selection_criterion": {
          str(seed): row["selection_criterion"]
          for seed, row in authority["checkpoint_authority"].items()},
      "job_count": 144, "code_artifacts": _code_fingerprints(args.project_root),
      "deterministic_runtime_environment": runtime_environment,
      "device": args.device,
      "git": _git_state(args.project_root)}
  identity["run_identity_sha256"] = contract.fingerprint_value(identity)
  path = os.path.join(run_root, "run_identity.json")
  if os.path.isfile(path):
    if contract.load_json(path) != identity:
      raise contract.Stage8ContractError(
          "Existing run ID has a different authority/config/code identity.")
    for evidence in ("preflight.json", "resolved_config.json"):
      if not os.path.isfile(os.path.join(run_root, evidence)):
        raise contract.Stage8ContractError(
            "Incomplete preflight is preserved; use a new run ID.")
    print("[resume] exact Stage-8 preflight {}".format(run_root))
    return run_root
  contract.write_json_atomic(path, identity)
  resolved = copy.deepcopy(config)
  resolved["run"] = {
      "run_id": args.run_id, "created_at": _utc_now(),
      "run_identity_sha256": identity["run_identity_sha256"],
      "machine": {"platform": platform.platform(), "python": sys.version}}
  contract.write_json_atomic(os.path.join(run_root, "resolved_config.json"), resolved)
  contract.write_json_atomic(os.path.join(run_root, "preflight.json"), {
      "schema_version": "capd_proactive_stage8_preflight_v1_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "stage8_entry_gate": "satisfied", "standard_test_status": "sealed_for_stage8",
      "execution_plan_sha256": config["stage7_authority"]["execution_plan"]["sha256"],
      "job_count": 144, "test_payload_operation":
          "sha256_integrity_only_not_parsed",
      "deterministic_runtime_environment": runtime_environment,
      "cuda_checkpoint_smoke_required_before_execute": True,
      "test_performance_inspected": False,
      "test_policy_replay_executed": False,
      "checkpoint_sha256": identity["checkpoint_sha256"],
      "checkpoint_selection_criterion":
          identity["checkpoint_selection_criterion"],
      "frozen_parameters_changed": False})
  _write_state(run_root, contract.IMPLEMENTED, ["preflight"])
  print("[OK] Stage-8 preflight {} (Test bytes hashed, not parsed)".format(run_root))
  return run_root


def _loaded_run(args):
  config, stage0, cost = _load(args)
  run_root = _root(args, config)
  _reject_failed_run(run_root)
  identity_path = os.path.join(run_root, "run_identity.json")
  if not os.path.isfile(identity_path):
    raise contract.Stage8ContractError("Stage-8 preflight has not passed.")
  expected = contract.load_json(identity_path)
  runtime_environment = _runtime_environment(config, args.device)
  authority = contract.audit_authority(config, args.project_root, True)
  current = {
      "config_sha256": contract.fingerprint_file(args.config),
      "stage0_sha256": contract.fingerprint_file(args.stage0_config),
      "cost_config_sha256": contract.fingerprint_file(args.cost_config),
      "result_schema_sha256": contract.fingerprint_file(os.path.join(
          args.project_root, config["result_schema"])),
      "test_payload_sha256": {
          row["workload"]: row["sha256"] for row in authority["lock"]["workloads"]},
      "checkpoint_sha256": {str(seed): value[1]
                            for seed, value in authority["checkpoint_bindings"].items()},
      "checkpoint_selection_criterion": {
          str(seed): row["selection_criterion"]
          for seed, row in authority["checkpoint_authority"].items()},
      "code_artifacts": _code_fingerprints(args.project_root)}
  current["deterministic_runtime_environment"] = runtime_environment
  current["device"] = args.device
  for key, value in current.items():
    if expected.get(key) != value:
      raise contract.Stage8ContractError(
          "Stage-8 binding changed after preflight: " + key)
  return run_root, config, stage0, cost, authority, expected


def runtime_smoke(args) -> None:
  """Exercises all three frozen CAPD checkpoints before Test CSV parsing."""
  run_root, config, stage0, cost, authority, _ = _loaded_run(args)
  if not str(args.device).lower().startswith("cuda"):
    raise contract.Stage8ContractError(
        "Formal Stage-8 CAPD runtime smoke requires a CUDA device.")
  import torch
  if not torch.cuda.is_available():
    raise contract.Stage8ContractError("CUDA is unavailable for CAPD smoke.")
  try:
    device_index = int(str(args.device).split(":", 1)[1])
  except (IndexError, ValueError):
    raise contract.Stage8ContractError("CUDA device must use cuda:N format.")
  if device_index < 0 or device_index >= torch.cuda.device_count():
    raise contract.Stage8ContractError("Requested CUDA device does not exist.")
  torch.cuda.set_device(device_index)
  stage5_config = contract.load_json(authority["paths"]["stage5_config"])
  trace = [{"page": index % 37, "rw": int(index % 5 == 0),
            "pc": 100 + index % 11} for index in range(128)]
  checkpoint_receipts = {}
  for seed in contract.CAPD_SEEDS:
    checkpoint = _smoke_checkpoint(authority, seed)
    digest = checkpoint["sha256"]
    result = proactive_stage5_replay.run_replay(
        stage0, stage5_config, cost, trace, "capd",
        workload="stage8_cuda_smoke", split="validation",
        split_role="parameter_selection",
        source_interval={"start": 0, "end": len(trace)},
        trace_sha256=contract.fingerprint_value(trace),
        dram_capacity_pages=20, working_set_pages=100,
        checkpoint=checkpoint, device=args.device,
        measure_latency=False)
    checkpoint_receipts[str(seed)] = {
        "checkpoint_sha256": digest,
        "selection_criterion": checkpoint["selection_criterion"],
        "semantic_result_sha256": result["semantic_result_sha256"]}
    del result
    torch.cuda.synchronize(device_index)
    torch.cuda.empty_cache()
  receipt = {
      "schema_version": "capd_proactive_stage8_runtime_smoke_v1_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "device": args.device,
      "cuda_device_name": torch.cuda.get_device_name(device_index),
      "torch_version": torch.__version__,
      "deterministic_runtime_environment":
          _runtime_environment(config, args.device),
      "checkpoint_receipts": checkpoint_receipts,
      "test_trace_opened": False, "test_performance_inspected": False,
      "completed_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "runtime_smoke.json"), receipt)
  state = contract.load_json(_state_path(run_root))
  completed = list(state.get("completed", []))
  if "cuda_checkpoint_smoke" not in completed:
    completed.append("cuda_checkpoint_smoke")
  _write_state(run_root, state.get("status", contract.IMPLEMENTED), completed)
  print("[OK] Stage-8 deterministic CUDA smoke passed for 3/3 CAPD checkpoints")


def _smoke_checkpoint(authority, seed):
  """Returns the exact Stage-4/5 audited checkpoint row; never infers names."""
  row = authority.get("checkpoint_authority", {}).get(int(seed))
  if not isinstance(row, Mapping):
    raise contract.Stage8ContractError(
        "Missing audited checkpoint authority for seed {}.".format(seed))
  required = ("seed", "path", "sha256", "selection_criterion")
  if any(key not in row for key in required):
    raise contract.Stage8ContractError(
        "Incomplete audited checkpoint authority for seed {}.".format(seed))
  return {key: row[key] for key in required}


def _trace(path: str):
  return [{"page": row["page"], "rw": 1 if row["rw"] == "W" else 0,
           "pc": row["pc"]} for row in stage7.iter_trace(path, 12)]


def _job_paths(run_root: str, job_id: str) -> Dict[str, str]:
  directory = os.path.join(run_root, "jobs", job_id)
  return {"directory": directory,
          "manifest": os.path.join(directory, "job_manifest.json"),
          "result": os.path.join(directory, "result.json")}


def _run_job(run_root, stage0, cost, authority, run_identity, job,
             trace, lock_row, working_set_pages, device, measure_latency):
  paths = _job_paths(run_root, job["job_id"])
  os.makedirs(paths["directory"], exist_ok=True)
  checkpoint = None
  if job["policy"] == "capd":
    resolved, digest = authority["checkpoint_bindings"][int(job["seed"])]
    frozen = authority["checkpoint_authority"][int(job["seed"])]
    checkpoint = {
        "seed": int(job["seed"]), "path": resolved, "sha256": digest,
        "selection_criterion": frozen["selection_criterion"]}
  identity = {
      "run_identity_sha256": run_identity["run_identity_sha256"],
      "plan_job": copy.deepcopy(job), "trace_sha256": lock_row["sha256"],
      "checkpoint_sha256": None if checkpoint is None else checkpoint["sha256"],
      "checkpoint_selection_criterion": (
          None if checkpoint is None else checkpoint["selection_criterion"]),
      "device": device, "measure_latency": bool(measure_latency),
      "deterministic_runtime_environment": {
          "CUBLAS_WORKSPACE_CONFIG": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
          "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED")},
      "result_schema": contract.RESULT_SCHEMA_VERSION}
  identity_sha = contract.fingerprint_value(identity)
  if os.path.isfile(paths["manifest"]):
    manifest = contract.load_json(paths["manifest"])
    if manifest.get("job_identity_sha256") != identity_sha:
      raise contract.Stage8ContractError(
          "Existing job identity differs; use a new run ID: " + job["job_id"])
    if manifest.get("status") != "completed":
      raise contract.Stage8ContractError(
          "Existing running/failed job is preserved; use a new run ID: " + job["job_id"])
    if (not os.path.isfile(paths["result"]) or
        contract.fingerprint_file(paths["result"]) != manifest.get("result_sha256")):
      raise contract.Stage8ContractError(
          "Completed job result is missing/corrupt: " + job["job_id"])
    result = contract.load_json(paths["result"])
    contract.audit_job_result(result, job)
    print("[resume] exact completed job {}".format(job["job_id"]))
    return result
  manifest = {
      "schema_version": contract.MANIFEST_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID, "job_identity": identity,
      "job_identity_sha256": identity_sha, "status": "running",
      "started_at": _utc_now(), "automatic_retry": False}
  contract.write_json_atomic(paths["manifest"], manifest)
  try:
    result = proactive_stage8_replay.run_formal_test_replay(
        stage0, cost, trace, job, lock_row, working_set_pages,
        checkpoint=checkpoint, device=device,
        measure_latency=measure_latency, retain_access_logs=False,
        invariant_mode="boundary")
    result["runtime"]["deterministic_environment"] = copy.deepcopy(
        identity["deterministic_runtime_environment"])
    contract.write_json_atomic(paths["result"], result)
  except Exception as error:
    manifest.update({"status": "failed", "failed_at": _utc_now(),
                     "error_type": type(error).__name__, "error": str(error)})
    contract.write_json_atomic(paths["manifest"], manifest)
    raise
  manifest.update({
      "status": "completed", "completed_at": _utc_now(),
      "result_sha256": contract.fingerprint_file(paths["result"]),
      "semantic_result_sha256": result["semantic_result_sha256"]})
  contract.write_json_atomic(paths["manifest"], manifest)
  print("[OK] {}".format(job["job_id"]), flush=True)
  return result


def _audit_preexecute_evidence(run_root, config, authority):
  smoke_path = os.path.join(run_root, "runtime_smoke.json")
  receipt_path = os.path.join(run_root, "server_test_receipt.json")
  if not os.path.isfile(smoke_path) or not os.path.isfile(receipt_path):
    raise contract.Stage8ContractError(
        "Execute requires CUDA smoke and full regression receipt before Test parse.")
  smoke = contract.load_json(smoke_path)
  receipt = contract.load_json(receipt_path)
  expected_checkpoints = {
      str(seed): {
          "checkpoint_sha256": row["sha256"],
          "selection_criterion": row["selection_criterion"]}
      for seed, row in authority["checkpoint_authority"].items()}
  observed_checkpoints = {
      seed: {
          "checkpoint_sha256": row.get("checkpoint_sha256"),
          "selection_criterion": row.get("selection_criterion")}
      for seed, row in smoke.get("checkpoint_receipts", {}).items()}
  minimum = config["acceptance"][
      "minimum_stage1_through_stage8_regression_tests"]
  if (smoke.get("status") != "passed" or
      smoke.get("test_trace_opened") is not False or
      smoke.get("test_performance_inspected") is not False or
      observed_checkpoints != expected_checkpoints or
      smoke.get("deterministic_runtime_environment") !=
      _runtime_environment(config, smoke.get("device", ""))):
    raise contract.Stage8ContractError("CAPD CUDA runtime smoke is invalid.")
  if (receipt.get("status") != "passed" or
      int(receipt.get("test_count", 0)) < minimum):
    raise contract.Stage8ContractError("Stage1-8 regression receipt is invalid.")
  return receipt, smoke


def execute(args) -> None:
  run_root, config, stage0, cost, authority, identity = _loaded_run(args)
  try:
    _audit_preexecute_evidence(run_root, config, authority)
  except Exception:
    state = contract.load_json(_state_path(run_root))
    _write_state(run_root, contract.NOT_VERIFIED,
                 state.get("completed", []), "preexecute_evidence")
    raise
  lock_map = {row["workload"]: row for row in authority["lock"]["workloads"]}
  capacity_map = {(row["workload"], str(row["ratio"])): row
                  for row in contract._capacity_rows(authority["capacity"])}
  jobs_by_workload = {}
  for job in authority["plan"]["jobs"]:
    jobs_by_workload.setdefault(job["workload"], []).append(job)
  try:
    for lock_row in authority["lock"]["workloads"]:
      workload = lock_row["workload"]
      # This is the first and only command that parses sealed Test contents.
      trace = _trace(authority["test_files"][workload])
      if len(trace) != lock_row["accesses"]:
        raise contract.Stage8ContractError("Parsed Test access count mismatch.")
      for job in jobs_by_workload[workload]:
        capacity = capacity_map[(workload, str(job["capacity_ratio"]))]
        _run_job(run_root, stage0, cost, authority, identity, job, trace,
                 lock_map[workload], int(capacity["working_set_pages"]),
                 args.device, not args.disable_latency)
        if job["policy"] == "capd" and str(args.device).startswith("cuda"):
          # Each CAPD job owns an independent predictor/checkpoint lifecycle.
          # Synchronize before advancing and release allocator cache so 54
          # sequential jobs cannot accumulate avoidable CUDA cache pressure.
          import torch
          torch.cuda.synchronize()
          torch.cuda.empty_cache()
      del trace
  except Exception:
    state = contract.load_json(_state_path(run_root))
    _write_state(run_root, contract.NOT_VERIFIED, state.get("completed", []),
                 "formal_execute")
    raise
  _write_state(run_root, "stage8_formal_replay_complete",
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_144_jobs"])
  print("[OK] Stage-8 formal Test Replay completed 144/144")


def _load_completed_results(run_root, plan):
  results = []
  for job in plan["jobs"]:
    paths = _job_paths(run_root, job["job_id"])
    if not os.path.isfile(paths["manifest"]):
      raise contract.Stage8ContractError("Missing job manifest: " + job["job_id"])
    manifest = contract.load_json(paths["manifest"])
    if manifest.get("status") != "completed" or not os.path.isfile(paths["result"]):
      raise contract.Stage8ContractError("Job is not completed: " + job["job_id"])
    if contract.fingerprint_file(paths["result"]) != manifest.get("result_sha256"):
      raise contract.Stage8ContractError("Job result SHA mismatch: " + job["job_id"])
    result = contract.load_json(paths["result"])
    contract.audit_job_result(result, job)
    results.append(result)
  return results


def aggregate(args) -> None:
  run_root, config, _, _, authority, _ = _loaded_run(args)
  results = _load_completed_results(run_root, authority["plan"])
  value = proactive_stage8_results.aggregate(results, config)
  artifacts = os.path.join(run_root, "artifacts")
  aggregate_path = os.path.join(artifacts, "aggregate.json")
  contract.write_json_atomic(aggregate_path, value)
  proactive_stage8_results.write_csv_atomic(
      os.path.join(artifacts, "per_workload_raw.csv"), value["per_workload_raw"])
  proactive_stage8_results.write_csv_atomic(
      os.path.join(artifacts, "capd_vs_tpp_paired.csv"),
      value["capd_vs_tpp_paired"])
  proactive_stage8_results.write_csv_atomic(
      os.path.join(artifacts, "proactive_vs_reactive_paired.csv"),
      value["proactive_lru_vs_reactive_lru_paired"])
  for table_name in ("table_A", "table_B"):
    flattened = _flatten_table(value[table_name])
    proactive_stage8_results.write_csv_atomic(
        os.path.join(artifacts, table_name + ".csv"), flattened)
  contract.write_text_atomic(
      os.path.join(artifacts, "report_cn.md"),
      proactive_stage8_results.markdown_report(value))
  contract.write_json_atomic(os.path.join(artifacts, "fairness_audit.json"),
                             value["fairness"])
  _write_state(run_root, "stage8_aggregated_awaiting_verification",
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_144_jobs", "aggregation"])
  print("[OK] Stage-8 audited aggregation generated")


def _flatten_table(rows):
  flattened = []
  for row in rows:
    flat = {key: item for key, item in row.items() if key != "metrics"}
    flat.update(row["metrics"])
    flat["seeds"] = json.dumps(row["seeds"], ensure_ascii=False)
    flattened.append(flat)
  return flattened


def record_tests(args) -> None:
  run_root, config, _, _, _, _ = _loaded_run(args)
  with open(args.test_log, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+[0-9.]+s", text)
  ok = re.search(r"^OK(?:\s*\([^\n]*\))?\s*$", text, re.MULTILINE)
  minimum = config["acceptance"][
      "minimum_stage1_through_stage8_regression_tests"]
  if (match is None or ok is None or int(match.group(1)) < minimum or
      "FAILED (" in text):
    raise contract.Stage8ContractError(
        "Regression log does not prove a successful Stage1-8 test run.")
  receipt = {
      "schema_version": "capd_proactive_stage8_test_receipt_v1_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "test_count": int(match.group(1)),
      "log_path": os.path.abspath(args.test_log),
      "log_sha256": contract.fingerprint_file(args.test_log),
      "success_marker": ok.group(0).strip(),
      "recorded_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "server_test_receipt.json"), receipt)
  state = contract.load_json(_state_path(run_root))
  completed = list(state.get("completed", []))
  if "server_regressions" not in completed:
    completed.append("server_regressions")
  _write_state(run_root, state.get("status", contract.IMPLEMENTED), completed)
  print("[OK] Stage1-8 regression receipt recorded ({} tests)".format(
      receipt["test_count"]))


def verify(args) -> None:
  run_root, config, _, _, authority, _ = _loaded_run(args)
  results = _load_completed_results(run_root, authority["plan"])
  expected = proactive_stage8_results.aggregate(results, config)
  artifact_root = os.path.join(run_root, "artifacts")
  aggregate_path = os.path.join(artifact_root, "aggregate.json")
  if not os.path.isfile(aggregate_path) or contract.load_json(aggregate_path) != expected:
    raise contract.Stage8ContractError("Aggregate is absent or not reproducible.")
  required = ("per_workload_raw.csv", "capd_vs_tpp_paired.csv",
              "proactive_vs_reactive_paired.csv",
              "table_A.csv", "table_B.csv", "report_cn.md",
              "fairness_audit.json")
  for filename in required:
    if not os.path.isfile(os.path.join(artifact_root, filename)):
      raise contract.Stage8ContractError("Missing Stage-8 artifact: " + filename)
  with tempfile.TemporaryDirectory(prefix="stage8-verify-") as temporary:
    expected_csv = {
        "per_workload_raw.csv": expected["per_workload_raw"],
        "capd_vs_tpp_paired.csv": expected["capd_vs_tpp_paired"],
        "proactive_vs_reactive_paired.csv":
            expected["proactive_lru_vs_reactive_lru_paired"],
        "table_A.csv": _flatten_table(expected["table_A"]),
        "table_B.csv": _flatten_table(expected["table_B"])}
    for filename, rows in expected_csv.items():
      candidate = os.path.join(temporary, filename)
      proactive_stage8_results.write_csv_atomic(candidate, rows)
      if contract.fingerprint_file(candidate) != contract.fingerprint_file(
          os.path.join(artifact_root, filename)):
        raise contract.Stage8ContractError(
            "CSV is not derived from audited aggregate: " + filename)
  with open(os.path.join(artifact_root, "report_cn.md"), "r",
            encoding="utf-8") as handle:
    if handle.read() != proactive_stage8_results.markdown_report(expected):
      raise contract.Stage8ContractError(
          "Markdown report is not derived from audited aggregate.")
  if contract.load_json(os.path.join(artifact_root, "fairness_audit.json")) != (
      expected["fairness"]):
    raise contract.Stage8ContractError(
        "Fairness artifact is not derived from audited aggregate.")
  receipt, smoke = _audit_preexecute_evidence(run_root, config, authority)
  receipt_path = os.path.join(run_root, "server_test_receipt.json")
  smoke_path = os.path.join(run_root, "runtime_smoke.json")
  verification = {
      "schema_version": "capd_proactive_stage8_verification_v1_0",
      "contract_id": contract.CONTRACT_ID, "status": contract.VERIFIED,
      "stage9_entry_gate": "satisfied",
      "formal_job_count": 144, "workload_capacity_cell_count": 18,
      "stage7_entry_gate": "satisfied", "standard_test_lock": "sealed_for_stage8",
      "job_results_verified": True, "fairness_A": "passed",
      "fairness_B": "passed", "statistics_verified": True,
      "regression_test_count": receipt["test_count"],
      "regression_log_sha256": receipt["log_sha256"],
      "runtime_smoke_sha256": contract.fingerprint_file(smoke_path),
      "test_used_for_parameter_selection": False,
      "frozen_parameters_changed": False,
      "old_finals_v3_artifacts_used": False,
      "aggregate_sha256": contract.fingerprint_file(aggregate_path),
      "artifact_sha256": {name: contract.fingerprint_file(
          os.path.join(artifact_root, name)) for name in required},
      "performance_conclusion": None,
      "interpretation_boundary": config["interpretation_boundary"],
      "verified_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "verification.json"), verification)
  _write_state(run_root, contract.VERIFIED,
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_144_jobs", "aggregation", "verification"])
  print("[FINAL] STAGE8_SYNC_REPLAY_VERIFIED")


def synthetic(args) -> None:
  del args
  trace = [{"page": page, "rw": index % 2, "pc": 100 + index}
           for index, page in enumerate([1, 2, 3, 1, 4, 2, 5, 1])]
  events = [{"event_id": 1, "event_type": "proactive_demotion",
             "access_index": 1, "page": 1}]
  metrics = proactive_stage8_replay.early_reuse_metrics(trace, events)
  if metrics["windows"]["64"]["early_reuse_count"] != 1:
    raise contract.Stage8ContractError("Synthetic Early-Reuse fixture failed.")
  ci_a = proactive_stage8_results.bootstrap_ci([1, -1, 2], 17, 100)
  ci_b = proactive_stage8_results.bootstrap_ci([1, -1, 2], 17, 100)
  if ci_a != ci_b:
    raise contract.Stage8ContractError("Synthetic bootstrap is not deterministic.")
  print("[OK] Stage-8 synthetic non-Test statistics/Early-Reuse E2E")


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  parser.add_argument("--config", default=os.path.join(
      PROJECT_ROOT, "configs/finals/capd_proactive_stage8.json"))
  parser.add_argument("--stage0-config", default=os.path.join(
      PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"))
  parser.add_argument("--cost-config", default=os.path.join(
      PROJECT_ROOT, "configs/finals/capd_proactive_stage2_cost_profiles.json"))
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--disable-latency", action="store_true")
  sub = parser.add_subparsers(dest="command", required=True)
  for command in (
      "preflight", "runtime-smoke", "execute", "aggregate", "verify",
      "synthetic"):
    sub.add_parser(command)
  tests = sub.add_parser("record-tests")
  tests.add_argument("--test-log", required=True)
  failed = sub.add_parser("mark-not-verified")
  failed.add_argument("--failure-step", required=True)
  return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
  args = build_parser().parse_args(argv)
  commands = {"preflight": preflight, "execute": execute,
              "runtime-smoke": runtime_smoke,
              "aggregate": aggregate, "verify": verify,
              "synthetic": synthetic, "record-tests": record_tests,
              "mark-not-verified": mark_not_verified}
  commands[args.command](args)


if __name__ == "__main__":
  main()
