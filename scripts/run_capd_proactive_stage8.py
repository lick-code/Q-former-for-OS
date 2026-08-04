#!/usr/bin/env python3
# coding=utf-8
"""Stage-8 preflight, gated 80-job replay, aggregation, and verification."""

from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_stage7_workloads as stage7
from qmap import proactive_stage8_contract as contract
from qmap import proactive_stage8_replay
from qmap import proactive_stage8_results


CODE_FILES = (
    "qmap/finals_config.py", "qmap/proactive_stage4.py",
    "qmap/proactive_replay.py", "qmap/proactive_cost.py",
    "qmap/proactive_stage5_contract.py", "qmap/proactive_stage5_policies.py",
    "qmap/proactive_stage5_replay.py", "qmap/proactive_stage6_contract.py",
    "qmap/proactive_stage6_tpp.py", "qmap/proactive_stage6_replay.py",
    "qmap/qmap_eval.py", "policy_learning/cache_model/embed.py",
    "policy_learning/cache_model/model.py",
    "qmap/proactive_stage8_contract.py", "qmap/proactive_stage8_replay.py",
    "qmap/proactive_stage8_results.py", "scripts/run_capd_proactive_stage8.py",
    "scripts/validate_capd_proactive_stage8_server.sh")


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
      "+00:00", "Z")


def _root(args, config: Mapping[str, Any]) -> str:
  stage7.safe_run_id(args.run_id)
  return os.path.join(args.project_root, config["output_root"], args.run_id)


def _load(args):
  config = contract.load_json(args.config)
  contract.validate_config(config)
  stage0 = finals_config.load_config(args.stage0_config)
  finals_config.validate_config(stage0)
  cost = proactive_cost.load_cost_config(args.cost_config)
  expected_cost_path = config["authorities"]["cost_config"]
  if (os.path.realpath(args.cost_config) != os.path.realpath(os.path.join(
      args.project_root, expected_cost_path["path"])) or
      contract.fingerprint_file(args.cost_config) != expected_cost_path["sha256"]):
    raise contract.Stage8ContractError("Frozen cost config path/SHA changed.")
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
        "PYTHONHASHSEED must be set before Python starts.")
  if str(device).lower().startswith("cuda") and actual[
      "CUBLAS_WORKSPACE_CONFIG"] != expected["cublas_workspace_config"]:
    raise contract.Stage8ContractError(
        "CUDA deterministic replay requires CUBLAS_WORKSPACE_CONFIG={}.".format(
            expected["cublas_workspace_config"]))
  return actual


def _git_state(project_root: str,
               runtime_output_root: Optional[str] = None) -> Dict[str, Any]:
  try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root).decode().strip()
    status_command = ["git", "status", "--porcelain", "--untracked-files=all"]
    if runtime_output_root is None:
      runtime_output_root = os.path.join(
          project_root, "outputs", "capd_proactive_stage8")
    project_path = os.path.realpath(project_root)
    output_path = os.path.realpath(runtime_output_root)
    relative_output = os.path.relpath(output_path, project_path)
    outside_project = (relative_output == os.pardir or
                       relative_output.startswith(os.pardir + os.sep))
    if relative_output not in (".", "") and not outside_project:
      relative_output = relative_output.replace(os.sep, "/").rstrip("/")
      status_command.extend([
          "--", ".", ":(exclude){}/**".format(relative_output)])
    status = subprocess.check_output(
        status_command, cwd=project_root).decode().strip()
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
      "schema_version": "capd_proactive_stage8_run_state_v2_0",
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
  if os.path.isfile(path) and contract.load_json(path).get("status") == (
      contract.NOT_VERIFIED):
    raise contract.Stage8ContractError(
        "Failed Stage-8 evidence is preserved; use a new run ID.")


def _identity(args, config, authority, runtime_environment):
  return {
      "contract_id": contract.CONTRACT_ID,
      "config_sha256": contract.fingerprint_file(args.config),
      "stage0_sha256": contract.fingerprint_file(args.stage0_config),
      "cost_config_sha256": contract.fingerprint_file(args.cost_config),
      "result_schema_sha256": contract.fingerprint_file(os.path.join(
          args.project_root, config["result_schema"])),
      "authority_sha256": {
          name: row["sha256"] for name, row in config["authorities"].items()},
      "standard_payload_sha256": {
          workload: row["sha256"]
          for workload, row in authority["standard_rows"].items()},
      "pressure_payload_sha256": {
          workload: row["derived_sha256"]
          for workload, row in authority["pressure_rows"].items()},
      "checkpoint_sha256": {
          str(seed): row["sha256"]
          for seed, row in authority["checkpoint_bindings"].items()},
      "job_manifest_sha256": contract.fingerprint_value(authority["jobs"]),
      "job_count": 80, "standard_job_count": 48, "pressure_job_count": 32,
      "cell_count": 10, "code_artifacts": _code_fingerprints(args.project_root),
      "deterministic_runtime_environment": runtime_environment,
      "device": args.device, "git": _git_state(
          args.project_root,
          os.path.join(args.project_root, config["output_root"]))}


def preflight(args) -> str:
  config, _, _ = _load(args)
  runtime_environment = _runtime_environment(config, args.device)
  run_root = _root(args, config)
  _reject_failed_run(run_root)
  for directory in ("jobs", "artifacts", "logs"):
    os.makedirs(os.path.join(run_root, directory), exist_ok=True)
  authority = contract.audit_authority(
      config, args.project_root, hash_test_payloads=True,
      require_source_files=True, require_checkpoints=True)
  identity = _identity(args, config, authority, runtime_environment)
  identity["run_identity_sha256"] = contract.fingerprint_value(identity)
  identity_path = os.path.join(run_root, "run_identity.json")
  if os.path.isfile(identity_path):
    if contract.load_json(identity_path) != identity:
      raise contract.Stage8ContractError(
          "Existing run ID has a different authority/config/code identity.")
    for evidence in ("preflight.json", "resolved_config.json", "job_manifest.json"):
      if not os.path.isfile(os.path.join(run_root, evidence)):
        raise contract.Stage8ContractError(
            "Incomplete preflight is preserved; use a new run ID.")
    print("[resume] exact Stage-8 preflight {}".format(run_root))
    return run_root
  contract.write_json_atomic(identity_path, identity)
  resolved = copy.deepcopy(config)
  resolved["run"] = {
      "run_id": args.run_id, "created_at": _utc_now(),
      "run_identity_sha256": identity["run_identity_sha256"],
      "machine": {"platform": platform.platform(), "python": sys.version}}
  contract.write_json_atomic(os.path.join(run_root, "resolved_config.json"), resolved)
  contract.write_json_atomic(os.path.join(run_root, "job_manifest.json"), {
      "schema_version": contract.MANIFEST_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID, "status": "frozen_not_executed",
      "job_count": 80, "standard_job_count": 48, "pressure_job_count": 32,
      "cell_count": 10, "jobs": authority["jobs"],
      "job_manifest_sha256": identity["job_manifest_sha256"]})
  contract.write_json_atomic(os.path.join(run_root, "preflight.json"), {
      "schema_version": "capd_proactive_stage8_preflight_v2_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "job_count": 80, "standard_job_count": 48, "pressure_job_count": 32,
      "cell_count": 10, "test_payload_operation":
          "sha256_integrity_only_not_parsed",
      "deterministic_runtime_environment": runtime_environment,
      "cuda_checkpoint_smoke_required_before_formal_replay": True,
      "test_performance_inspected": False,
      "test_policy_replay_executed": False,
      "frozen_parameters_changed": False})
  _write_state(run_root, contract.IMPLEMENTED, ["preflight"])
  print("[OK] Stage-8 preflight {} (payload bytes hashed, not parsed)".format(
      run_root))
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
  authority = contract.audit_authority(
      config, args.project_root, hash_test_payloads=True,
      require_source_files=True, require_checkpoints=True)
  current = _identity(args, config, authority, runtime_environment)
  for key, value in current.items():
    if expected.get(key) != value:
      raise contract.Stage8ContractError(
          "Stage-8 binding changed after preflight: " + key)
  return run_root, config, stage0, cost, authority, expected


def _smoke_checkpoint(authority, seed):
  row = authority.get("checkpoint_bindings", authority.get(
      "checkpoint_authority", {})).get(int(seed))
  if not isinstance(row, Mapping):
    raise contract.Stage8ContractError(
        "Missing audited checkpoint authority for seed {}.".format(seed))
  required = ("seed", "path", "sha256", "selection_criterion")
  if any(key not in row for key in required):
    raise contract.Stage8ContractError(
        "Incomplete audited checkpoint authority for seed {}.".format(seed))
  return {
      "seed": int(row["seed"]), "recorded_path": row["path"],
      "path": row.get("resolved_path", row["path"]),
      "resolved_path": row.get("resolved_path", row["path"]),
      "sha256": row["sha256"],
      "selection_criterion": row["selection_criterion"]}


def runtime_smoke(args) -> None:
  """Load and replay all three frozen CAPD checkpoints before payload parse."""
  run_root, config, stage0, cost, authority, _ = _loaded_run(args)
  if not str(args.device).lower().startswith("cuda"):
    raise contract.Stage8ContractError(
        "Formal Stage-8 CAPD runtime smoke requires cuda:N.")
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
  torch.use_deterministic_algorithms(True)
  torch.backends.cudnn.benchmark = False
  torch.backends.cudnn.deterministic = True
  trace = [{"page": index % 37, "rw": int(index % 5 == 0),
            "pc": 100 + index % 11} for index in range(128)]
  template = next(job for job in authority["jobs"]
                  if job["track"] == "standard" and
                  job["workload"] == "canneal" and job["policy"] == "capd")
  lock = {
      "workload": "stage8_cuda_smoke", "fairness_identity": "cuda-smoke",
      "policy_replay_allowed_stage": 8, "accesses": len(trace)}
  receipts = {}
  for seed in contract.CAPD_SEEDS:
    checkpoint = _smoke_checkpoint(authority, seed)
    job = copy.deepcopy(template)
    job.update({
        "job_id": "standard__stage8_cuda_smoke__capd__seed-{}".format(seed),
        "workload": "stage8_cuda_smoke", "seed": seed,
        "test_identity": "cuda-smoke",
        "trace_sha256": contract.fingerprint_value(trace),
        "source_interval": {"start_inclusive": 0, "end_exclusive": len(trace)},
        "evaluation_interval": {
            "start_inclusive": 0, "end_exclusive": len(trace)},
        "checkpoint": copy.deepcopy(authority["checkpoint_bindings"][seed])})
    result = proactive_stage8_replay.run_formal_test_replay(
        stage0, cost, trace, job, lock, checkpoint=checkpoint,
        device=args.device, measure_latency=False, invariant_mode="full")
    receipts[str(seed)] = {
        "checkpoint_sha256": checkpoint["sha256"],
        "selection_criterion": checkpoint["selection_criterion"],
        "semantic_result_sha256": result["semantic_result_sha256"]}
    del result
    torch.cuda.synchronize(device_index)
    torch.cuda.empty_cache()
  receipt = {
      "schema_version": "capd_proactive_stage8_runtime_smoke_v2_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "device": args.device, "cuda_device_name": torch.cuda.get_device_name(
          device_index), "torch_version": torch.__version__,
      "deterministic_runtime_environment": _runtime_environment(
          config, args.device), "checkpoint_receipts": receipts,
      "test_trace_opened": False, "pressure_trace_opened": False,
      "test_performance_inspected": False, "completed_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "runtime_smoke.json"), receipt)
  state = contract.load_json(_state_path(run_root))
  completed = list(state.get("completed", []))
  if "cuda_checkpoint_smoke" not in completed:
    completed.append("cuda_checkpoint_smoke")
  _write_state(run_root, state.get("status", contract.IMPLEMENTED), completed)
  print("[OK] Stage-8 deterministic CUDA smoke passed for 3/3 checkpoints")


def _trace(path: str):
  return [{"page": row["page"], "rw": 1 if row["rw"] == "W" else 0,
           "pc": row["pc"]} for row in stage7.iter_trace(path, 12)]


def _job_paths(run_root: str, job_id: str) -> Dict[str, str]:
  directory = os.path.join(run_root, "jobs", job_id)
  return {"directory": directory,
          "manifest": os.path.join(directory, "job_manifest.json"),
          "result": os.path.join(directory, "result.json")}


def _run_job(run_root, stage0, cost, authority, run_identity, job,
             trace, lock_row, device, measure_latency):
  paths = _job_paths(run_root, job["job_id"])
  os.makedirs(paths["directory"], exist_ok=True)
  checkpoint = None
  if job["policy"] == "capd":
    checkpoint = _smoke_checkpoint(authority, job["seed"])
  identity = {
      "run_identity_sha256": run_identity["run_identity_sha256"],
      "plan_job": copy.deepcopy(job), "trace_sha256": job["trace_sha256"],
      "checkpoint_sha256": None if checkpoint is None else checkpoint["sha256"],
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
          "Existing running/failed job is preserved; use a new run ID: " +
          job["job_id"])
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
        stage0, cost, trace, job, lock_row, checkpoint=checkpoint,
        device=device, measure_latency=measure_latency, retain_access_logs=False,
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
        "Formal replay requires CUDA smoke and regression receipt.")
  smoke = contract.load_json(smoke_path)
  receipt = contract.load_json(receipt_path)
  expected_checkpoints = {
      str(seed): row["sha256"]
      for seed, row in authority["checkpoint_bindings"].items()}
  observed_checkpoints = {
      seed: row.get("checkpoint_sha256")
      for seed, row in smoke.get("checkpoint_receipts", {}).items()}
  minimum = config["acceptance"][
      "minimum_stage1_through_stage8_regression_tests"]
  if (smoke.get("status") != "passed" or
      smoke.get("test_trace_opened") is not False or
      smoke.get("pressure_trace_opened") is not False or
      observed_checkpoints != expected_checkpoints):
    raise contract.Stage8ContractError("CAPD CUDA runtime smoke is invalid.")
  if receipt.get("status") != "passed" or int(receipt.get("test_count", 0)) < minimum:
    raise contract.Stage8ContractError("Regression receipt is invalid.")
  return receipt, smoke


def formal_replay(args) -> None:
  if not args.confirm_formal_replay:
    raise contract.Stage8ContractError(
        "Formal replay requires explicit --confirm-formal-replay approval.")
  run_root, config, stage0, cost, authority, identity = _loaded_run(args)
  state = contract.load_json(_state_path(run_root))
  if state.get("status") != contract.AWAITING_FORMAL_REPLAY:
    raise contract.Stage8ContractError(
        "Run is not awaiting formal replay confirmation.")
  _audit_preexecute_evidence(run_root, config, authority)
  source_rows = {
      ("standard", workload): row
      for workload, row in authority["standard_rows"].items()}
  source_rows.update({
      ("pressure", workload): row
      for workload, row in authority["pressure_rows"].items()})
  jobs_by_cell = collections.defaultdict(list)
  for job in authority["jobs"]:
    jobs_by_cell[(job["track"], job["workload"])].append(job)
  try:
    for cell in (("standard", workload) for workload in contract.STANDARD_WORKLOADS):
      track, workload = cell
      source = source_rows[cell]
      path = stage7.repository_path(args.project_root, source["path"], True)
      trace = _trace(path)
      for job in jobs_by_cell[cell]:
        _run_job(run_root, stage0, cost, authority, identity, job, trace,
                 source, args.device, not args.disable_latency)
        if job["policy"] == "capd" and str(args.device).startswith("cuda"):
          import torch
          torch.cuda.synchronize()
          torch.cuda.empty_cache()
      del trace
    for cell in (("pressure", workload) for workload in contract.PRESSURE_WORKLOADS):
      track, workload = cell
      source = source_rows[cell]
      path = stage7.repository_path(args.project_root, source["derived_path"], True)
      trace = _trace(path)
      for job in jobs_by_cell[cell]:
        _run_job(run_root, stage0, cost, authority, identity, job, trace,
                 source, args.device, not args.disable_latency)
        if job["policy"] == "capd" and str(args.device).startswith("cuda"):
          import torch
          torch.cuda.synchronize()
          torch.cuda.empty_cache()
      del trace
  except Exception:
    _write_state(run_root, contract.NOT_VERIFIED, state.get("completed", []),
                 "formal_replay")
    raise
  _write_state(run_root, contract.FORMAL_REPLAY_COMPLETE,
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_80_jobs"])
  print("[OK] Stage-8 formal replay completed 80/80")


def _load_completed_results(run_root, jobs):
  values = []
  for job in jobs:
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
    values.append(result)
  return values


def _flatten_table(rows):
  flattened = []
  for row in rows:
    flat = {key: item for key, item in row.items() if key != "metrics"}
    flat.update(row["metrics"])
    flat["seeds"] = json.dumps(row["seeds"], ensure_ascii=False)
    flattened.append(flat)
  return flattened


def aggregate(args) -> None:
  run_root, config, _, _, authority, _ = _loaded_run(args)
  if contract.load_json(_state_path(run_root)).get("status") != (
      contract.FORMAL_REPLAY_COMPLETE):
    raise contract.Stage8ContractError("Aggregation requires completed 80-job replay.")
  results = _load_completed_results(run_root, authority["jobs"])
  value = proactive_stage8_results.aggregate(results, config)
  artifacts = os.path.join(run_root, "artifacts")
  contract.write_json_atomic(os.path.join(artifacts, "aggregate.json"), value)
  for filename, rows in (
      ("per_workload_raw.csv", value["per_workload_raw"]),
      ("capd_vs_tpp_paired.csv", value["capd_vs_tpp_paired"]),
      ("proactive_vs_reactive_paired.csv",
       value["proactive_lru_vs_reactive_lru_paired"]),
      ("oracle_headroom.csv", value["oracle_headroom"]),
      ("table_A.csv", _flatten_table(value["table_A"])),
      ("table_B.csv", _flatten_table(value["table_B"]))):
    proactive_stage8_results.write_csv_atomic(os.path.join(artifacts, filename), rows)
  contract.write_text_atomic(os.path.join(artifacts, "report.md"),
                             proactive_stage8_results.markdown_report(value))
  contract.write_json_atomic(os.path.join(artifacts, "fairness_audit.json"),
                             value["fairness"])
  _write_state(run_root, "stage8_aggregated_awaiting_verification",
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_80_jobs", "aggregation"])
  print("[OK] Stage-8 track-separated aggregation generated")


def record_tests(args) -> None:
  run_root, config, _, _, _, _ = _loaded_run(args)
  with open(args.test_log, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+[0-9.]+s", text)
  ok = re.search(r"^OK(?:\s*\([^\n]*\))?\s*$", text, re.MULTILINE)
  minimum = config["acceptance"][
      "minimum_stage1_through_stage8_regression_tests"]
  if match is None or ok is None or int(match.group(1)) < minimum or "FAILED (" in text:
    raise contract.Stage8ContractError(
        "Regression log does not prove a successful Stage1-8 test run.")
  receipt = {
      "schema_version": "capd_proactive_stage8_test_receipt_v2_0",
      "contract_id": contract.CONTRACT_ID, "status": "passed",
      "test_count": int(match.group(1)), "log_path": os.path.abspath(args.test_log),
      "log_sha256": contract.fingerprint_file(args.test_log),
      "success_marker": ok.group(0).strip(), "recorded_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "server_test_receipt.json"), receipt)
  contract.write_json_atomic(os.path.join(run_root, "formal_replay_gate.json"), {
      "schema_version": "capd_proactive_stage8_formal_replay_gate_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": contract.AWAITING_FORMAL_REPLAY,
      "formal_replay_authorized": False,
      "requires_explicit_human_confirmation": True,
      "automatic_replay": False, "recorded_at": _utc_now()})
  state = contract.load_json(_state_path(run_root))
  completed = list(state.get("completed", []))
  if "server_regressions" not in completed:
    completed.append("server_regressions")
  _write_state(run_root, contract.AWAITING_FORMAL_REPLAY, completed)
  print("[STOP] {} ({} tests)".format(
      contract.AWAITING_FORMAL_REPLAY, receipt["test_count"]))


def verify(args) -> None:
  run_root, config, _, _, authority, _ = _loaded_run(args)
  results = _load_completed_results(run_root, authority["jobs"])
  expected = proactive_stage8_results.aggregate(results, config)
  artifact_root = os.path.join(run_root, "artifacts")
  aggregate_path = os.path.join(artifact_root, "aggregate.json")
  if not os.path.isfile(aggregate_path) or contract.load_json(aggregate_path) != expected:
    raise contract.Stage8ContractError("Aggregate is absent or not reproducible.")
  receipt, _ = _audit_preexecute_evidence(run_root, config, authority)
  verification = {
      "schema_version": "capd_proactive_stage8_verification_v2_0",
      "contract_id": contract.CONTRACT_ID, "status": contract.VERIFIED,
      "formal_job_count": 80, "standard_job_count": 48,
      "pressure_job_count": 32, "track_workload_cell_count": 10,
      "standard_cell_count": 6, "pressure_cell_count": 4,
      "job_results_verified": True, "fairness": "passed",
      "statistics_verified": True, "regression_test_count": receipt["test_count"],
      "test_used_for_parameter_selection": False,
      "frozen_parameters_changed": False,
      "aggregate_sha256": contract.fingerprint_file(aggregate_path),
      "performance_conclusion": None,
      "interpretation_boundary": config["interpretation_boundary"],
      "verified_at": _utc_now()}
  contract.write_json_atomic(os.path.join(run_root, "verification.json"), verification)
  _write_state(run_root, contract.VERIFIED,
               ["preflight", "cuda_checkpoint_smoke", "server_regressions",
                "formal_80_jobs", "aggregation", "verification"])
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
  first = proactive_stage8_results.bootstrap_ci([1, -1, 2], 17, 100)
  second = proactive_stage8_results.bootstrap_ci([1, -1, 2], 17, 100)
  if first != second or first["resampling_unit"] != "track_workload_cell":
    raise contract.Stage8ContractError("Synthetic bootstrap fixture failed.")
  print("[OK] Stage-8 synthetic replay/statistics checks")


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
  for command in ("preflight", "runtime-smoke", "aggregate", "verify", "synthetic"):
    sub.add_parser(command)
  replay = sub.add_parser("formal-replay")
  replay.add_argument("--confirm-formal-replay", action="store_true", required=True)
  tests = sub.add_parser("record-tests")
  tests.add_argument("--test-log", required=True)
  failed = sub.add_parser("mark-not-verified")
  failed.add_argument("--failure-step", required=True)
  return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
  args = build_parser().parse_args(argv)
  commands = {
      "preflight": preflight, "runtime-smoke": runtime_smoke,
      "formal-replay": formal_replay, "aggregate": aggregate,
      "verify": verify, "synthetic": synthetic,
      "record-tests": record_tests, "mark-not-verified": mark_not_verified}
  commands[args.command](args)


if __name__ == "__main__":
  main()
