#!/usr/bin/env python3
# coding=utf-8
"""Run, select, audit, and verify the Stage-6 TPP-inspired Validation grid."""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_cost
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as stage5
from qmap import proactive_stage6_contract as contract
from qmap import proactive_stage6_replay


CODE_ARTIFACTS = (
    "configs/finals/capd_proactive_stage6_tpp.json",
    "configs/finals/capd_proactive_stage6_tpp_result_schema.json",
    "qmap/proactive_replay.py",
    "qmap/proactive_cost.py",
    "qmap/proactive_stage5_contract.py",
    "qmap/proactive_stage5_policies.py",
    "qmap/proactive_stage5_replay.py",
    "qmap/proactive_stage6_contract.py",
    "qmap/proactive_stage6_tpp.py",
    "qmap/proactive_stage6_replay.py",
    "scripts/run_capd_proactive_stage6.py",
    "scripts/validate_capd_proactive_stage6_server.sh",
    "tests/test_capd_proactive_stage6_tpp.py",
    "tests/test_capd_proactive_stage6_e2e.py",
    "docs/CAPD_PROACTIVE_STAGE6_PROTOCOL_CN.md",
    "docs/CAPD_PROACTIVE_STAGE6_STATUS_CN.md",
    "docs/CAPD_PROACTIVE_STAGE6_SERVER_RUN_CN.md",
)
PREFLIGHT_FILES = (
    "run_identity.json", "resolved_config.json", "input_manifest.json",
    "working_set_summary.json", "policy_registry.json", "run_state.json")
GRID_JOB_SCHEMA = "capd_proactive_stage6_job_v1_0"
RUN_STATE_SCHEMA = "capd_proactive_stage6_run_manifest_v1_0"


def _utc_now() -> str:
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ")


def _safe_run_id(value: str) -> str:
  if (not isinstance(value, str) or not value or
      not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", value)):
    raise contract.Stage6ContractError(
        "run-id must use only letters, digits, dot, underscore, and dash.")
  return value


def _root(args, config: Mapping[str, Any]) -> str:
  return os.path.abspath(os.path.join(
      args.project_root, config["output_root"], _safe_run_id(args.run_id)))


def _git_state(project_root: str) -> Dict[str, Any]:
  def command(*arguments):
    return subprocess.check_output(
        ["git"] + list(arguments), cwd=project_root,
        stderr=subprocess.STDOUT)
  try:
    commit = command("rev-parse", "HEAD").decode("utf-8").strip()
    dirty_override = os.environ.get("CAPD_DIRTY_WORKTREE")
    if dirty_override in ("true", "false"):
      status_text = (
          "explicit-dirty-worktree-override\n"
          if dirty_override == "true" else "")
      diff = status_text.encode("utf-8")
    else:
      status_text = command("status", "--porcelain=v1").decode("utf-8")
      diff = command("diff", "--binary", "--no-ext-diff", "HEAD")
  except (OSError, subprocess.CalledProcessError):
    return {"commit": "unknown", "dirty_worktree": None,
            "dirty_diff_sha256": None, "status": []}
  return {
      "commit": commit,
      "dirty_worktree": bool(status_text.strip()),
      "dirty_diff_sha256": hashlib.sha256(diff).hexdigest(),
      "status": status_text.splitlines(),
  }


def _code_fingerprints(project_root: str) -> Dict[str, str]:
  output = {}
  for relative in CODE_ARTIFACTS:
    path = os.path.join(project_root, relative)
    if not os.path.isfile(path):
      raise contract.Stage6ContractError(
          "Stage-6 code artifact missing: " + relative)
    output[relative] = proactive_stage4.fingerprint_file(path)
  return output


def _load(args):
  config = contract.load_config(args.config)
  stage0 = proactive_stage4.load_json(args.stage0_config)
  cost = proactive_cost.load_cost_config(args.cost_config)
  return config, stage0, cost


def _write_state(
    run_root: str, status: str, completed: Sequence[str],
    failure_step: Optional[str] = None,
    failure_history: Optional[Sequence[str]] = None) -> None:
  state_path = os.path.join(run_root, "run_state.json")
  previous_completed = []
  if os.path.isfile(state_path):
    previous_completed = list(
        proactive_stage4.load_json(state_path).get("completed", []))
  merged_completed = list(previous_completed)
  for item in completed:
    if item not in merged_completed:
      merged_completed.append(item)
  value = {
      "schema_version": RUN_STATE_SCHEMA,
      "contract_id": contract.CONTRACT_ID,
      "status": status,
      "completed": merged_completed,
      "test_trace_opened": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "performance_conclusion": None,
      "updated_at": _utc_now(),
  }
  if failure_step is not None:
    value["failure_step"] = failure_step
    value["failure_history"] = list(failure_history or (failure_step,))
    value["failure_recorded_at"] = _utc_now()
    value["automatic_retry"] = False
  proactive_stage4.write_json_atomic(
      state_path, value)


def _mark_not_verified(run_root: str, failure_step: str) -> None:
  path = os.path.join(run_root, "run_state.json")
  previous = (
      proactive_stage4.load_json(path) if os.path.isfile(path) else {})
  history = list(previous.get("failure_history", []))
  if failure_step not in history:
    history.append(failure_step)
  completed = list(previous.get("completed", []))
  if "failure_evidence_preserved" not in completed:
    completed.append("failure_evidence_preserved")
  _write_state(
      run_root, contract.NOT_VERIFIED, completed,
      failure_step=failure_step, failure_history=history)


def mark_not_verified(args) -> None:
  config, _, _ = _load(args)
  run_root = _root(args, config)
  if not os.path.isdir(run_root):
    raise contract.Stage6ContractError("Run directory does not exist.")
  _mark_not_verified(run_root, args.failure_step)
  print("[NOT VERIFIED] {} failed at {}".format(
      args.run_id, args.failure_step))


def _load_inputs(
    args, stage6_config: Mapping[str, Any]
) -> Tuple[Mapping[str, Any], Dict[str, Dict[str, Sequence[Any]]],
           List[Dict[str, Any]], Dict[str, Any], Mapping[str, Any]]:
  stage5_path = contract._authority_path(
      args.project_root,
      stage6_config["stage5_entry_authority"]["stage5_config"])
  stage5_config = stage5.load_config(stage5_path)
  manifest, traces, entries = stage5.resolve_manifest_traces(
      stage5_config, args.project_root)
  working_set = proactive_stage4.working_set_and_capacity(traces)
  return manifest, traces, entries, working_set, stage5_config


def _entry(entries, workload: str, split: str) -> Mapping[str, Any]:
  matches = [row for row in entries
             if row["workload"] == workload and row["split"] == split]
  if len(matches) != 1:
    raise contract.Stage6ContractError(
        "Expected one input entry for {}/{}.".format(workload, split))
  return matches[0]


def preflight(args) -> str:
  config, _, _ = _load(args)
  run_root = _root(args, config)
  if os.path.isdir(run_root):
    state_path = os.path.join(run_root, "run_state.json")
    state = (proactive_stage4.load_json(state_path)
             if os.path.isfile(state_path) else {})
    if state.get("status") in (contract.NOT_VERIFIED, contract.VERIFIED):
      raise contract.Stage6ContractError(
          "Existing failed/verified run is immutable; use a new run-id.")
  os.makedirs(os.path.join(run_root, "jobs"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "logs"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "artifacts"), exist_ok=True)
  stage5_entry = contract.audit_stage5_entry(config, args.project_root)
  manifest, _, entries, working_set, stage5_config = _load_inputs(args, config)
  stage4_authority = stage5.audit_stage4_authority(
      stage5_config, args.project_root, require_checkpoints=True)
  identity = {
      "contract_id": contract.CONTRACT_ID,
      "config_sha256": proactive_stage4.fingerprint_file(args.config),
      "stage0_sha256": proactive_stage4.fingerprint_file(args.stage0_config),
      "cost_config_sha256":
          proactive_stage4.fingerprint_file(args.cost_config),
      "stage5_entry_sha256": stage5_entry["sha256"],
      "stage4_verification_sha256":
          stage4_authority["verification_sha256"],
      "stage4_freeze_candidate_sha256":
          stage4_authority["freeze_candidate_sha256"],
      "stage4_dataset_manifest_sha256":
          stage4_authority["dataset_manifest_sha256"],
      "stage4_dataset_identity_sha256":
          stage4_authority["dataset_identity_sha256"],
      "stage4_checkpoint_sha256": {
          str(row["seed"]): row["sha256"]
          for row in stage4_authority["checkpoints"]},
      "trace_sha256": {
          "{}:{}".format(row["workload"], row["split"]):
              row["trace_sha256"] for row in entries},
      "validation_grid_sha256":
          proactive_stage4.fingerprint_value(contract.parameter_grid()),
      "selection_rule_sha256":
          proactive_stage4.fingerprint_value(config["selection_rule"]),
      "code_artifacts": _code_fingerprints(args.project_root),
      "git": _git_state(args.project_root),
  }
  identity["run_identity_sha256"] = proactive_stage4.fingerprint_value(
      identity)
  identity_path = os.path.join(run_root, "run_identity.json")
  if os.path.isfile(identity_path):
    existing = proactive_stage4.load_json(identity_path)
    binding_keys = tuple(
        key for key in identity
        if key not in ("git", "run_identity_sha256"))
    if any(existing.get(key) != identity.get(key) for key in binding_keys):
      raise contract.Stage6ContractError(
          "Existing run-id has a different data/config/code identity.")
    missing = [name for name in PREFLIGHT_FILES
               if not os.path.isfile(os.path.join(run_root, name))]
    if missing:
      raise contract.Stage6ContractError(
          "Incomplete preflight must be preserved; use a new run-id: " +
          ", ".join(missing))
    print("[resume] exact preflight {}".format(run_root))
    return run_root
  proactive_stage4.write_json_atomic(identity_path, identity)
  resolved = copy.deepcopy(config)
  resolved.update({
      "run": {
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
      },
      "stage5_entry_resolved": stage5_entry,
      "stage4_authority_resolved": stage4_authority,
      "working_set": working_set,
      "input_entries": entries,
  })
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "resolved_config.json"), resolved)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "input_manifest.json"), manifest)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "working_set_summary.json"), working_set)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "policy_registry.json"), {
          "schema_version": contract.SCHEMA_VERSION,
          "contract_id": contract.CONTRACT_ID,
          "stage5_tpp_status": stage5.PENDING_TPP,
          "stage6_tpp": {
              "display_name": contract.DISPLAY_NAME,
              "status": "implemented",
              "fallback_to_lru_allowed": False,
              "promotion_allowed": False,
              "future_information_allowed": False,
          },
          "experiment_A": list(
              config["comparison_protocol_A"]["policies"]),
      })
  _write_state(run_root, contract.IMPLEMENTED, ["preflight"])
  print("[OK] stage6 preflight {}".format(run_root))
  return run_root


def _loaded_run(args):
  config, stage0, cost = _load(args)
  run_root = _root(args, config)
  identity_path = os.path.join(run_root, "run_identity.json")
  if not os.path.isfile(identity_path):
    raise contract.Stage6ContractError("Run has not passed preflight.")
  identity = proactive_stage4.load_json(identity_path)
  current = {
      "config_sha256": proactive_stage4.fingerprint_file(args.config),
      "stage0_sha256": proactive_stage4.fingerprint_file(args.stage0_config),
      "cost_config_sha256":
          proactive_stage4.fingerprint_file(args.cost_config),
  }
  if any(identity.get(key) != value for key, value in current.items()):
    raise contract.Stage6ContractError(
        "Stage-6 config/Stage-0/Cost changed after preflight.")
  if identity.get("code_artifacts") != _code_fingerprints(args.project_root):
    raise contract.Stage6ContractError(
        "Stage-6 code changed after preflight; use a new run-id.")
  stage5_entry = contract.audit_stage5_entry(config, args.project_root)
  if identity.get("stage5_entry_sha256") != stage5_entry["sha256"]:
    raise contract.Stage6ContractError(
        "Stage-5 r4 authority changed after preflight.")
  manifest, traces, entries, working_set, stage5_config = _load_inputs(
      args, config)
  del manifest
  current_traces = {
      "{}:{}".format(row["workload"], row["split"]): row["trace_sha256"]
      for row in entries}
  if identity.get("trace_sha256") != current_traces:
    raise contract.Stage6ContractError(
        "Train/Validation Trace identity changed after preflight.")
  return (run_root, config, stage0, cost, stage5_config,
          traces, entries, working_set)


def _job_paths(run_root: str, job_name: str) -> Dict[str, str]:
  directory = os.path.join(run_root, "jobs", job_name)
  return {
      "directory": directory,
      "manifest": os.path.join(directory, "job_manifest.json"),
      "result": os.path.join(directory, "result.json"),
  }


def _job_name(mode: str, workload: str, experiment_id: str) -> str:
  return "{}__{}__validation__{}".format(mode, workload, experiment_id)


def _run_tpp_job(
    run_root, config, stage0, cost, trace, entry, working_set,
    parameters, mode: str, measure_latency: bool = True,
    retain_access_logs: bool = False):
  name = _job_name(mode, entry["workload"], parameters["experiment_id"])
  paths = _job_paths(run_root, name)
  os.makedirs(paths["directory"], exist_ok=True)
  run_identity = proactive_stage4.load_json(os.path.join(
      run_root, "run_identity.json"))["run_identity_sha256"]
  identity = {
      "run_identity_sha256": run_identity,
      "job_name": name,
      "mode": mode,
      "policy": contract.POLICY,
      "parameters": copy.deepcopy(parameters),
      "workload": entry["workload"],
      "split": entry["split"],
      "trace_sha256": entry["trace_sha256"],
      "source_interval": entry["source_interval"],
      "accesses": len(trace),
      "measure_latency": bool(measure_latency),
      "retain_access_logs": bool(retain_access_logs),
      "invariant_mode": (
          "full" if mode in ("synthetic", "fairness") else "boundary"),
  }
  identity_sha = proactive_stage4.fingerprint_value(identity)
  if os.path.isfile(paths["manifest"]):
    existing = proactive_stage4.load_json(paths["manifest"])
    if existing.get("job_identity_sha256") != identity_sha:
      raise contract.Stage6ContractError(
          "Existing job identity differs; use a new run-id: " + name)
    if existing.get("status") == "completed":
      if (not os.path.isfile(paths["result"]) or
          proactive_stage4.fingerprint_file(paths["result"]) !=
          existing.get("result_sha256")):
        raise contract.Stage6ContractError(
            "Completed job result is missing/corrupt: " + name)
      print("[resume] exact completed job {}".format(name))
      return proactive_stage4.load_json(paths["result"])
    raise contract.Stage6ContractError(
        "Existing failed/running job is preserved; use a new run-id: " + name)
  manifest = {
      "schema_version": GRID_JOB_SCHEMA,
      "contract_id": contract.CONTRACT_ID,
      "job_identity": identity,
      "job_identity_sha256": identity_sha,
      "status": "running",
      "started_at": _utc_now(),
      "automatic_retry": False,
  }
  proactive_stage4.write_json_atomic(paths["manifest"], manifest)
  try:
    result = proactive_stage6_replay.run_replay(
        stage0, config, cost, trace,
        workload=entry["workload"],
        split=entry["split"],
        split_role=entry["role"],
        source_interval=entry["source_interval"],
        trace_sha256=entry["trace_sha256"],
        dram_capacity_pages=working_set["dram_capacity_pages"],
        working_set_pages=working_set["union_working_set_pages"],
        epoch_length=parameters["epoch_length"],
        cold_threshold=parameters["cold_threshold"],
        dirty_tie_break=parameters["dirty_tie_break"],
        measure_latency=measure_latency,
        retain_access_logs=retain_access_logs,
        invariant_mode=identity["invariant_mode"])
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


def synthetic(args) -> None:
  run_root, config, stage0, cost, _, _, _, _ = _loaded_run(args)
  trace = [
      {"page": page, "rw": int(page % 5 == 0), "pc": page % 7}
      for page in range(1, 14)]
  trace.extend({"page": 13, "rw": 0, "pc": 1} for _ in range(130))
  trace.extend(
      {"page": page, "rw": int(page % 4 == 0), "pc": page % 7}
      for page in range(14, 28))
  parameters = {
      "experiment_id": contract.parameter_id(64, 2, True),
      "epoch_length": 64, "cold_threshold": 2,
      "dirty_tie_break": True}
  entry = {
      "workload": "synthetic_stage6",
      "split": "validation",
      "role": "parameter_selection",
      "source_interval": {"start": 0, "end": len(trace)},
      "trace_sha256": proactive_stage4.fingerprint_value(trace),
  }
  ws = {
      "dram_capacity_pages": 20,
      "union_working_set_pages": len({row["page"] for row in trace}),
  }
  result = _run_tpp_job(
      run_root, config, stage0, cost, trace, entry, ws, parameters,
      "synthetic", measure_latency=False, retain_access_logs=True)
  metrics = result["summary"]["tpp"]
  if (metrics["epoch_transition_count"] < 2 or
      metrics["selected_temperature_distribution"]["counts"]["Cold"] < 1 or
      not any(row["number_of_rounds"] > 1 for row in result["cycles"])):
    raise contract.Stage6ContractError(
        "Synthetic E2E lacks epoch/Cold/multi-round coverage.")
  receipt = {
      "schema_version": "capd_proactive_stage6_synthetic_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "semantic_result_sha256": result["semantic_result_sha256"],
      "epoch_transition_covered": True,
      "cold_selection_covered": True,
      "multi_round_cycle_covered": True,
      "test_trace_opened": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "performance_conclusion": None,
      "completed_at": _utc_now(),
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "synthetic_e2e_receipt.json"), receipt)
  _write_state(run_root, contract.IMPLEMENTED, [
      "preflight", "synthetic_e2e"])
  print("[OK] Stage-6 synthetic E2E")


def run_grid(args) -> None:
  run_root, config, stage0, cost, _, traces, entries, working_set = (
      _loaded_run(args))
  for workload in sorted(traces):
    entry = _entry(entries, workload, "validation")
    trace = traces[workload]["validation"]
    expected = int(entry["source_interval"]["end"]) - int(
        entry["source_interval"]["start"])
    if len(trace) != expected:
      raise contract.Stage6ContractError(
          "Formal grid must use the full frozen Validation interval.")
    for parameters in contract.parameter_grid():
      _run_tpp_job(
          run_root, config, stage0, cost, trace, entry,
          working_set[workload], parameters, "grid",
          measure_latency=True, retain_access_logs=False)
  _write_state(run_root, contract.IMPLEMENTED, [
      "preflight", "synthetic_e2e", "full_validation_grid"])
  print("[OK] complete 12-configuration Validation grid")


def _load_jobs_by_mode(run_root: str, mode: str) -> List[Mapping[str, Any]]:
  rows = []
  prefix = mode + "__"
  jobs_root = os.path.join(run_root, "jobs")
  for directory in sorted(os.listdir(jobs_root)):
    if not directory.startswith(prefix):
      continue
    paths = _job_paths(run_root, directory)
    if not (os.path.isfile(paths["manifest"]) and
            os.path.isfile(paths["result"])):
      raise contract.Stage6ContractError("Job artifact is incomplete: " +
                                         directory)
    manifest = proactive_stage4.load_json(paths["manifest"])
    if (manifest.get("status") != "completed" or
        manifest.get("result_sha256") !=
        proactive_stage4.fingerprint_file(paths["result"])):
      raise contract.Stage6ContractError(
          "Job manifest/result is incomplete or corrupt: " + directory)
    rows.append(proactive_stage4.load_json(paths["result"]))
  return rows


def select(args) -> None:
  run_root, config, _, _, _, traces, _, _ = _loaded_run(args)
  rows = _load_jobs_by_mode(run_root, "grid")
  expected = len(traces) * contract.EXPECTED_GRID_SIZE
  if len(rows) != expected:
    raise contract.Stage6ContractError(
        "Expected {} full-grid jobs, found {}.".format(expected, len(rows)))
  decision = contract.select_global_configuration(rows, config)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "selection_decision.json"), decision)
  frozen = {
      "schema_version": "capd_proactive_stage6_frozen_tpp_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": contract.RESULTS_READY,
      "policy_display_name": contract.DISPLAY_NAME,
      "implementation": "replay_compatible_adaptation",
      "selected_experiment_id": decision["selected_experiment_id"],
      "selected_parameters": decision["selected_parameters"],
      "selection_decision_sha256":
          proactive_stage4.fingerprint_file(os.path.join(
              run_root, "selection_decision.json")),
      "test_trace_opened": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "performance_conclusion": None,
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "final_tpp_config.json"), frozen)
  _write_state(run_root, contract.RESULTS_READY, [
      "preflight", "synthetic_e2e", "full_validation_grid",
      "global_parameter_selection"])
  print("[OK] selected global TPP configuration {}".format(
      decision["selected_experiment_id"]))


def confirm(args) -> None:
  run_root, config, stage0, cost, _, traces, entries, working_set = (
      _loaded_run(args))
  decision_path = os.path.join(run_root, "selection_decision.json")
  if not os.path.isfile(decision_path):
    raise contract.Stage6ContractError("Selection decision is missing.")
  decision = proactive_stage4.load_json(decision_path)
  parameters = dict(
      decision["selected_parameters"],
      experiment_id=decision["selected_experiment_id"])
  confirmations = {}
  for workload in sorted(traces):
    entry = _entry(entries, workload, "validation")
    result = _run_tpp_job(
        run_root, config, stage0, cost, traces[workload]["validation"],
        entry, working_set[workload], parameters, "confirm",
        measure_latency=True, retain_access_logs=False)
    grid_name = _job_name("grid", workload, parameters["experiment_id"])
    grid_result = proactive_stage4.load_json(
        _job_paths(run_root, grid_name)["result"])
    if result["semantic_result_sha256"] != (
        grid_result["semantic_result_sha256"]):
      raise contract.Stage6ContractError(
          "Confirmation semantic replay differs for " + workload)
    confirmations[workload] = result["semantic_result_sha256"]
  receipt = {
      "schema_version": "capd_proactive_stage6_confirmation_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "selected_experiment_id": parameters["experiment_id"],
      "selected_parameters": decision["selected_parameters"],
      "semantic_result_sha256": confirmations,
      "test_trace_opened": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "performance_conclusion": None,
      "completed_at": _utc_now(),
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "confirmation_receipt.json"), receipt)
  _write_state(run_root, contract.RESULTS_READY, [
      "preflight", "synthetic_e2e", "full_validation_grid",
      "global_parameter_selection", "final_validation_confirmation"])
  print("[OK] selected TPP full-Validation confirmation")


def fairness(args) -> None:
  run_root, config, stage0, cost, _, traces, entries, working_set = (
      _loaded_run(args))
  decision = proactive_stage4.load_json(os.path.join(
      run_root, "selection_decision.json"))
  parameters = dict(
      decision["selected_parameters"],
      experiment_id=decision["selected_experiment_id"])
  reports = {}
  stage5_jobs = os.path.join(
      args.project_root, contract.STAGE5_R4_RELATIVE_ROOT, "jobs")
  access_limit = int(
      config["comparison_protocol_A"]["framework_acceptance_accesses_per_workload"])
  for workload in sorted(traces):
    base_entry = _entry(entries, workload, "validation")
    trace = traces[workload]["validation"][:access_limit]
    entry = copy.deepcopy(base_entry)
    entry["source_interval"] = {
        "start": int(base_entry["source_interval"]["start"]),
        "end": int(base_entry["source_interval"]["start"]) + len(trace)}
    tpp = _run_tpp_job(
        run_root, config, stage0, cost, trace, entry,
        working_set[workload], parameters, "fairness",
        measure_latency=False, retain_access_logs=False)
    records = [tpp]
    for policy in ("proactive_lru", "proactive_clock", "oracle"):
      path = os.path.join(
          stage5_jobs,
          "{}__validation__{}__seed-na".format(workload, policy),
          "result.json")
      records.append(proactive_stage4.load_json(path))
    for seed in stage5.CAPD_SEEDS:
      path = os.path.join(
          stage5_jobs,
          "{}__validation__capd__seed-{}".format(workload, seed),
          "result.json")
      records.append(proactive_stage4.load_json(path))
    reports[workload] = contract.check_experiment_a(records)
  output = {
      "schema_version": "capd_proactive_stage6_fairness_suite_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "selected_experiment_id": parameters["experiment_id"],
      "workloads": reports,
      "test_trace_opened": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "performance_conclusion": None,
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "fairness_audit.json"), output)
  _write_state(run_root, contract.RESULTS_READY, [
      "preflight", "synthetic_e2e", "full_validation_grid",
      "global_parameter_selection", "final_validation_confirmation",
      "experiment_A_fairness"])
  print("[OK] Stage-6 experiment A fairness")


def _parse_successful_unittest_log(text: str) -> Dict[str, Any]:
  summaries = list(re.finditer(
      r"^Ran\s+(\d+)\s+tests?\s+in\s+([0-9]+(?:\.[0-9]+)?)s\s*$",
      text, flags=re.MULTILINE))
  if not summaries:
    raise contract.Stage6ContractError(
        "Regression log lacks a unittest Ran N tests summary.")
  summary = summaries[-1]
  tail = text[summary.end():]
  success = re.search(r"^\s*OK\s*$", tail, flags=re.MULTILINE)
  if success is None:
    raise contract.Stage6ContractError(
        "Regression log lacks an OK marker after its summary.")
  return {
      "tests_run": int(summary.group(1)),
      "elapsed_seconds": float(summary.group(2)),
      "summary_line": summary.group(0).strip(),
      "success_line": success.group(0).strip(),
  }


def record_tests(args) -> None:
  run_root, _, _, _, _, _, _, _ = _loaded_run(args)
  if int(args.test_exit_code) != 0:
    raise contract.Stage6ContractError(
        "Regression runner exit code is nonzero.")
  test_log = stage5.resolve_repository_path(
      args.test_log, args.project_root,
      ("outputs/capd_proactive_stage6",), must_exist=True)
  with open(test_log, "r", encoding="utf-8", errors="replace") as source:
    unittest_summary = _parse_successful_unittest_log(source.read())
  receipt = {
      "schema_version": "capd_proactive_stage6_test_receipt_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": "passed",
      "stage1_through_stage6_regression_requested": True,
      "runner_exit_code": int(args.test_exit_code),
      "log_path": os.path.relpath(
          test_log, args.project_root).replace(os.sep, "/"),
      "log_sha256": proactive_stage4.fingerprint_file(test_log),
      "unittest": unittest_summary,
      "test_trace_opened": False,
      "recorded_at": _utc_now(),
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "server_test_receipt.json"), receipt)
  _write_state(run_root, contract.IMPLEMENTED, [
      "preflight", "stage1_stage6_regressions"])
  print("[OK] recorded Stage1-6 regression receipt")


def verify(args) -> None:
  run_root, config, _, _, _, traces, _, _ = _loaded_run(args)
  contract.audit_stage5_entry(config, args.project_root)
  required = (
      "synthetic_e2e_receipt.json", "selection_decision.json",
      "final_tpp_config.json", "confirmation_receipt.json",
      "fairness_audit.json", "server_test_receipt.json")
  for filename in required:
    path = os.path.join(run_root, filename)
    if not os.path.isfile(path):
      raise contract.Stage6ContractError(
          "Verification evidence missing: " + filename)
  for filename in (
      "synthetic_e2e_receipt.json", "confirmation_receipt.json",
      "fairness_audit.json", "server_test_receipt.json"):
    value = proactive_stage4.load_json(os.path.join(run_root, filename))
    if value.get("status") != "passed":
      raise contract.Stage6ContractError(
          "Evidence did not pass: " + filename)
    if value.get("test_trace_opened") is not False:
      raise contract.Stage6ContractError(
          "Evidence reports Test access: " + filename)
  decision = proactive_stage4.load_json(os.path.join(
      run_root, "selection_decision.json"))
  if (decision.get("status") != contract.RESULTS_READY or
      decision.get("configuration_count") != contract.EXPECTED_GRID_SIZE or
      decision.get("global_configuration_only") is not True):
    raise contract.Stage6ContractError(
        "Global selection decision is incomplete.")
  frozen = proactive_stage4.load_json(os.path.join(
      run_root, "final_tpp_config.json"))
  confirmation = proactive_stage4.load_json(os.path.join(
      run_root, "confirmation_receipt.json"))
  selection_sha = proactive_stage4.fingerprint_file(os.path.join(
      run_root, "selection_decision.json"))
  if (frozen.get("status") != contract.RESULTS_READY or
      frozen.get("selection_decision_sha256") != selection_sha or
      frozen.get("selected_experiment_id") !=
      decision.get("selected_experiment_id") or
      frozen.get("selected_parameters") !=
      decision.get("selected_parameters") or
      confirmation.get("selected_experiment_id") !=
      decision.get("selected_experiment_id") or
      confirmation.get("selected_parameters") !=
      decision.get("selected_parameters")):
    raise contract.Stage6ContractError(
        "Frozen/confirmation configuration is not bound to selection.")
  resolved = proactive_stage4.load_json(os.path.join(
      run_root, "resolved_config.json"))
  full_validation_ranges = {
      row["workload"]: row["source_interval"]
      for row in resolved["input_entries"]
      if row["split"] == "validation"}
  expected_counts = {
      "grid": len(traces) * contract.EXPECTED_GRID_SIZE,
      "confirm": len(traces),
      "fairness": len(traces),
      "synthetic": 1,
  }
  for mode, count in expected_counts.items():
    rows = _load_jobs_by_mode(run_root, mode)
    if len(rows) != count:
      raise contract.Stage6ContractError(
          "{} job count mismatch: expected {}, found {}.".format(
              mode, count, len(rows)))
    for row in rows:
      contract.audit_result(row)
      if (row.get("future_information") != "not_accessed" or
          row.get("promotion_performed") is not False or
          row.get("tpp_fallback_used") is not False):
        raise contract.Stage6ContractError(
            "TPP contamination found in {} job.".format(mode))
      if mode in ("grid", "confirm"):
        expected_range = full_validation_ranges.get(row["workload"])
        if (expected_range is None or
            row.get("trace_range", {}).get("start") !=
            expected_range["start"] or
            row.get("trace_range", {}).get("end") !=
            expected_range["end"] or
            row.get("raw_access_event_count") !=
            expected_range["end"] - expected_range["start"]):
          raise contract.Stage6ContractError(
              "{} did not use the full frozen Validation interval: {}."
              .format(mode, row["workload"]))
  test_receipt = proactive_stage4.load_json(os.path.join(
      run_root, "server_test_receipt.json"))
  if (test_receipt.get("runner_exit_code") != 0 or
      test_receipt.get("stage1_through_stage6_regression_requested")
      is not True or
      int(test_receipt.get("unittest", {}).get("tests_run", 0)) <
      int(config["acceptance"][
          "minimum_stage1_through_stage6_regression_tests"])):
    raise contract.Stage6ContractError(
        "Regression receipt lacks a successful Stage1-6 runner.")
  log_path = stage5.resolve_repository_path(
      test_receipt["log_path"], args.project_root,
      ("outputs/capd_proactive_stage6",), must_exist=True)
  if proactive_stage4.fingerprint_file(log_path) != (
      test_receipt["log_sha256"]):
    raise contract.Stage6ContractError(
        "Regression log changed after receipt.")
  with open(log_path, "r", encoding="utf-8",
            errors="replace") as source:
    if _parse_successful_unittest_log(source.read()) != (
        test_receipt["unittest"]):
      raise contract.Stage6ContractError(
          "Regression summary changed after receipt.")
  fairness_value = proactive_stage4.load_json(os.path.join(
      run_root, "fairness_audit.json"))
  if any(report.get("status") != "passed"
         for report in fairness_value["workloads"].values()):
    raise contract.Stage6ContractError(
        "Experiment A fairness did not pass for every workload.")
  verification = {
      "schema_version": "capd_proactive_stage6_verification_v1_0",
      "contract_id": contract.CONTRACT_ID,
      "status": contract.VERIFIED,
      "verified_at": _utc_now(),
      "stage5_entry_status": stage5.VERIFIED,
      "stage5_tpp_status_preserved": stage5.PENDING_TPP,
      "selected_experiment_id": decision["selected_experiment_id"],
      "selected_parameters": decision["selected_parameters"],
      "validation_configuration_count": contract.EXPECTED_GRID_SIZE,
      "validation_workloads": sorted(traces),
      "full_frozen_validation_intervals": True,
      "experiment_A_fairness": "passed",
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "old_finals_v3_stage_artifacts_used": False,
      "performance_conclusion": None,
      "stage7_entry_gate": "satisfied",
      "interpretation_boundary":
          "TPP-inspired Replay-compatible adaptation; not Linux TPP and "
          "not formal Test performance.",
      "evidence_sha256": {
          filename: proactive_stage4.fingerprint_file(
              os.path.join(run_root, filename)) for filename in required},
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "verification.json"), verification)
  _write_state(run_root, contract.VERIFIED, [
      "preflight", "synthetic_e2e", "full_validation_grid",
      "global_parameter_selection", "final_validation_confirmation",
      "experiment_A_fairness", "stage1_stage6_regressions",
      "verification"])
  print("[FINAL] STAGE6_TPP_INSPIRED_VERIFIED")


def run_all(args) -> None:
  preflight(args)
  synthetic(args)
  run_grid(args)
  select(args)
  confirm(args)
  fairness(args)
  if not args.test_log or args.test_exit_code is None:
    raise contract.Stage6ContractError(
        "all requires --test-log and --test-exit-code.")
  record_tests(args)
  verify(args)


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      description="CAPD proactive Stage-6 TPP-inspired Validation.")
  parser.add_argument("command", choices=(
      "preflight", "synthetic", "run-grid", "select", "confirm",
      "fairness", "record-tests", "verify", "all",
      "mark-not-verified"))
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--project-root", default=os.path.abspath(os.path.join(
      os.path.dirname(__file__), "..")))
  parser.add_argument(
      "--config",
      default="configs/finals/capd_proactive_stage6_tpp.json")
  parser.add_argument(
      "--stage0-config",
      default="configs/finals/capd_proactive_stage0.json")
  parser.add_argument(
      "--cost-config",
      default="configs/finals/capd_proactive_stage2_cost_profiles.json")
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--test-log")
  parser.add_argument("--test-exit-code", type=int)
  parser.add_argument("--failure-step")
  return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
  args = build_parser().parse_args(argv)
  args.project_root = os.path.abspath(args.project_root)
  for name in ("config", "stage0_config", "cost_config"):
    path = getattr(args, name)
    if not os.path.isabs(path):
      setattr(args, name, os.path.join(args.project_root, path))
  commands = {
      "preflight": preflight,
      "synthetic": synthetic,
      "run-grid": run_grid,
      "select": select,
      "confirm": confirm,
      "fairness": fairness,
      "record-tests": record_tests,
      "verify": verify,
      "all": run_all,
      "mark-not-verified": mark_not_verified,
  }
  if args.command == "mark-not-verified" and not args.failure_step:
    raise contract.Stage6ContractError(
        "mark-not-verified requires --failure-step.")
  commands[args.command](args)


if __name__ == "__main__":
  main()
