# coding=utf-8
"""Fail-closed Stage-8 contract for the frozen Standard/Pressure replay."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from typing import Any, Dict, Mapping, Optional, Sequence

from qmap import proactive_stage7_workloads as stage7


SCHEMA_VERSION = "capd_proactive_stage8_v2_0"
RESULT_SCHEMA_VERSION = "capd_proactive_stage8_job_result_v2_0"
MANIFEST_SCHEMA_VERSION = "capd_proactive_stage8_job_manifest_v2_0"
AGGREGATE_SCHEMA_VERSION = "capd_proactive_stage8_aggregate_v2_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE8-2.0"
IMPLEMENTED = "stage8_implemented_awaiting_formal_replay"
AWAITING_FORMAL_REPLAY = "awaiting_formal_replay_confirmation"
FORMAL_REPLAY_COMPLETE = "stage8_formal_replay_complete"
VERIFIED = "stage8_sync_replay_verified"
NOT_VERIFIED = "stage8_not_verified"

FORMAL_POLICIES = (
    "reactive_lru", "proactive_lru", "proactive_clock", "tpp_inspired",
    "oracle", "capd")
DETERMINISTIC_POLICIES = FORMAL_POLICIES[:-1]
CAPD_SEEDS = (3136859, 42, 2026)
STANDARD_WORKLOADS = (
    "canneal", "streamcluster_pressure", "dedup_pressure", "blackscholes",
    "swaptions", "fluidanimate")
PRESSURE_WORKLOADS = (
    "canneal", "dedup_pressure", "blackscholes", "swaptions")
STRUCTURAL_ZERO_STANDARD_WORKLOADS = (
    "streamcluster_pressure", "fluidanimate")
TRACKS = ("standard", "pressure")
COMPARISON_A = (
    "proactive_lru", "proactive_clock", "tpp_inspired", "capd", "oracle")
COMPARISON_B = ("reactive_lru", "proactive_lru")
WORKLOAD_CONTROLS = {
    "canneal": {"D": 120, "F_low": 6, "F_target": 16},
    "streamcluster_pressure": {"D": 22, "F_low": 1, "F_target": 3},
    "dedup_pressure": {"D": 21, "F_low": 1, "F_target": 3},
    "blackscholes": {"D": 8, "F_low": 1, "F_target": 2},
    "swaptions": {"D": 8, "F_low": 1, "F_target": 2},
    "fluidanimate": {"D": 22, "F_low": 1, "F_target": 3},
}
FROZEN_CONTROLS = {
    "candidate_size_K": 8,
    "b_max": 2,
    "history_H": 20,
    "candidate_source": "lru_tail",
    "selector": "disabled",
    "fallback_policy": "lru",
    "trigger_mode": "low_watermark",
    "b_t_rule": "min(b_max,max(0,F_target-F_t),candidate_count)",
}
FROZEN_COST = {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
               "demotion": 10}
TPP_CONTROLS = {
    "epoch_length": 1024,
    "cold_threshold": 1,
    "dirty_tie_break": False,
    "promotion_allowed": False,
}
INITIAL_STATE_DESCRIPTION = "empty_dram_all_trace_pages_backed_by_nvm"
PAGE_ENTER_DRAM_SEMANTICS = "occupies_one_free_frame_regardless_of_source"


class Stage8ContractError(ValueError):
  pass


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage8ContractError(message)


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as handle:
    return json.load(handle)


def fingerprint_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
  encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
  return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix=".stage8-", suffix=".json",
                                   dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
      json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
      handle.write("\n")
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def write_text_atomic(path: str, value: str) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix=".stage8-", suffix=".tmp",
                                   dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
      handle.write(value)
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping) and
           value.get("schema_version") == SCHEMA_VERSION and
           value.get("contract_id") == CONTRACT_ID,
           "Stage-8 v2 config schema/contract mismatch.")
  _require(value.get("output_root") == "outputs/capd_proactive_stage8" and
           value.get("result_schema") ==
           "configs/finals/capd_proactive_stage8_result_schema.json",
           "Stage-8 output/result-schema binding changed.")
  _require(tuple(value.get("formal_policies", ())) == FORMAL_POLICIES and
           tuple(value.get("deterministic_policies", ())) ==
           DETERMINISTIC_POLICIES and
           tuple(value.get("capd_seeds", ())) == CAPD_SEEDS,
           "Stage-8 policy/seed matrix changed.")
  tracks = value.get("tracks", {})
  _require(tuple(tracks.get("standard", {}).get("workloads", ())) ==
           STANDARD_WORKLOADS and
           tuple(tracks.get("pressure", {}).get("workloads", ())) ==
           PRESSURE_WORKLOADS,
           "Stage-8 Standard/Pressure workload matrix changed.")
  _require(value.get("frozen_controls") == FROZEN_CONTROLS and
           value.get("cost_profile", {}).get("weights") == FROZEN_COST,
           "Stage-8 controls or cost changed.")
  _require(value.get("workload_controls") == WORKLOAD_CONTROLS,
           "Stage-8 workload controls changed.")
  _require(value.get("capd") == {
      "lookahead_L": 256, "label_weights": [1, 1, 2],
      "history_H": 20, "vocabulary_expansion_allowed": False,
      "unk_index": 0, "best_seed_selection_allowed": False},
      "CAPD freeze changed.")
  _require(value.get("tpp_inspired") == TPP_CONTROLS,
           "TPP freeze changed.")
  _require(value.get("storage") == {
      "page_size_bytes": 4096,
      "nvm_capacity_model": "unbounded_backing_tier",
      "page_enter_dram_semantics": PAGE_ENTER_DRAM_SEMANTICS,
      "initial_state": INITIAL_STATE_DESCRIPTION},
      "Storage/initial-state freeze changed.")
  statistics = value.get("statistics", {})
  _require(statistics.get("bootstrap_seed") == 20260801 and
           statistics.get("bootstrap_resamples") == 10000 and
           statistics.get("bootstrap_unit") == "track_workload_cell" and
           statistics.get("standard_cell_count") == 6 and
           statistics.get("pressure_cell_count") == 4 and
           statistics.get("confidence_level") == 0.95 and
           statistics.get("std") == "sample_ddof_1" and
           statistics.get("zero_denominator_rate") == 0.0,
           "Stage-8 predeclared statistics changed.")
  acceptance = value.get("acceptance", {})
  _require(acceptance == {
      "minimum_stage1_through_stage8_regression_tests": 380,
      "standard_job_count": 48, "pressure_job_count": 32,
      "formal_job_count": 80, "cell_count": 10,
      "verified_status": VERIFIED, "failure_status": NOT_VERIFIED,
      "awaiting_status": AWAITING_FORMAL_REPLAY},
      "Stage-8 acceptance gate changed.")
  _require(value.get("deterministic_runtime") == {
      "cublas_workspace_config": ":4096:8", "pythonhashseed": "0",
      "torch_deterministic_algorithms": True, "cudnn_benchmark": False,
      "cudnn_deterministic": True,
      "cuda_smoke_all_capd_checkpoints_before_test_parse": True},
      "Stage-8 deterministic runtime contract changed.")
  authorities = value.get("authorities", {})
  required_authorities = {
      "r4_final_freeze", "r4_pressure_generation_contract", "r4_run_state",
      "stage4_final_freeze", "stage4_model_contract",
      "stage4_checkpoint_manifest", "stage4_run_state", "standard_test_lock",
      "pressure_test_lock", "pressure_bundle_manifest", "cost_config"}
  _require(required_authorities <= set(authorities),
           "Frozen authority bindings are incomplete.")
  for name in required_authorities:
    row = authorities[name]
    _require(isinstance(row, Mapping) and isinstance(row.get("path"), str) and
             len(str(row.get("sha256", ""))) == 64,
             "Invalid authority binding: " + name)
  result_schema_sha = str(value.get("result_schema_sha256", ""))
  _require(len(result_schema_sha) == 64 and all(
      character in "0123456789abcdef" for character in result_schema_sha),
      "Result schema SHA binding is invalid.")
  return value


def _authority_file(project_root: str, row: Mapping[str, Any],
                    require_exists: bool = True) -> str:
  path = stage7.repository_path(project_root, row.get("path", ""),
                                must_exist=require_exists)
  if require_exists:
    _require(fingerprint_file(path) == row.get("sha256"),
             "Authority SHA mismatch: {}".format(row.get("path")))
  return path


def _verified_file(project_root: str, recorded_path: str, expected_sha: str,
                   require_exists: bool) -> Optional[str]:
  path = stage7.repository_path(project_root, recorded_path,
                                must_exist=require_exists)
  if require_exists:
    _require(fingerprint_file(path) == expected_sha,
             "Source SHA mismatch: {}".format(recorded_path))
    return path
  return path if os.path.isfile(path) else None


def _controls_from_r4(r4: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
  _require(r4.get("formal_freeze") is True and
           r4.get("human_confirmation") is True and
           r4.get("candidate_size_K") == FROZEN_CONTROLS["candidate_size_K"] and
           r4.get("b_max") == FROZEN_CONTROLS["b_max"] and
           r4.get("alpha") == 0.15 and r4.get("beta") == 0.4,
           "R4 final freeze is not the expected formal contract.")
  watermarks = {row["workload"]: row for row in r4.get("watermarks", [])}
  capacity = {row["workload"]: row
              for row in r4.get("unified_capacity_matrix", [])}
  _require(set(watermarks) == set(STANDARD_WORKLOADS) and
           set(capacity) == set(STANDARD_WORKLOADS),
           "R4 workload controls are incomplete.")
  controls = {}
  for workload in STANDARD_WORKLOADS:
    row = watermarks[workload]
    cap = capacity[workload]
    expected = WORKLOAD_CONTROLS[workload]
    _require({key: row.get(key) for key in ("D", "F_low", "F_target")} ==
             expected and cap.get("D_standard") == expected["D"] and
             cap.get("D_pressure") == expected["D"],
             "R4 workload control mismatch: " + workload)
    controls[workload] = dict(expected, W_ref=int(cap["W_ref"]),
                              alpha=float(row["alpha"]),
                              beta=float(row["beta"]),
                              K=8, b_max=2, history_H=20,
                              candidate_source="lru_tail", selector="disabled",
                              fallback_policy="lru", trigger_mode="low_watermark",
                              b_t_rule=FROZEN_CONTROLS["b_t_rule"])
  return controls


def _checkpoint_bindings(project_root: str, manifest: Mapping[str, Any],
                         require_checkpoints: bool) -> Dict[int, Dict[str, Any]]:
  _require(manifest.get("formal_freeze") is True and
           manifest.get("seed_selection_performed") is False,
           "Formal checkpoint manifest is not frozen.")
  result = {}
  for seed_text, row in manifest.get("per_seed", {}).items():
    seed = int(seed_text)
    best = row.get("checkpoints", {}).get("best", {})
    _require(seed in CAPD_SEEDS and row.get("selection_criterion") ==
             "minimum_valid_loss_only" and len(best.get("fingerprint", "")) == 64,
             "Invalid Stage-4 checkpoint binding for seed {}.".format(seed))
    recorded = best.get("path")
    if require_checkpoints:
      resolved = stage7.resolve_recorded_artifact(
          project_root, recorded, best["fingerprint"])
    else:
      resolved = recorded
    result[seed] = {
        "seed": seed, "path": recorded, "resolved_path": resolved,
        "sha256": best["fingerprint"],
        "selection_criterion": row["selection_criterion"]}
  _require(set(result) == set(CAPD_SEEDS),
           "All three frozen CAPD checkpoint seeds are required.")
  return result


def _standard_rows(project_root: str, lock: Mapping[str, Any],
                   require_source_files: bool) -> Dict[str, Dict[str, Any]]:
  _require(lock.get("status") == "sealed_for_stage8" and
           lock.get("test_performance_inspected") is False and
           lock.get("test_policy_replay_executed") is False and
           lock.get("test_used_for_parameter_selection") is False,
           "Standard Test lock is invalid or contaminated.")
  rows = {}
  for row in lock.get("workloads", []):
    workload = row.get("workload")
    _require(workload in STANDARD_WORKLOADS and row.get("formal_test") is True and
             row.get("split_role") == "test" and
             row.get("parameter_selection_allowed") is False and
             row.get("policy_replay_allowed_stage") == 8 and
             row.get("accesses") == 600000 and
             row.get("interval", {}).get("end_exclusive") -
             row.get("interval", {}).get("start_inclusive") == 600000,
             "Standard lock metadata is invalid: " + str(workload))
    path = _verified_file(project_root, row["path"], row["sha256"],
                          require_source_files)
    item = copy.deepcopy(row)
    item["resolved_path"] = path
    rows[workload] = item
  _require(tuple(rows) == STANDARD_WORKLOADS,
           "Standard lock must retain all six workloads.")
  return rows


def _pressure_rows(project_root: str, lock: Mapping[str, Any],
                   bundle: Mapping[str, Any], lock_sha: str,
                   bundle_sha: str, require_source_files: bool) -> Dict[str, Dict[str, Any]]:
  bundle_authority = bundle.get("authority_sha256", {})
  _require(lock.get("schema_version") == "capd_proactive_pressure_stage7_v1_0" and
           lock.get("standard_pressure_hard_principle_satisfied") is True and
           lock.get("test_used_for_stage3_selection") is False and
           bundle.get("formal_pressure_bundle") is True and
           lock.get("pressure_window_selection_addendum_sha256") ==
           bundle_authority.get("pressure_window_selection_addendum") and
           lock.get("selection_order_contract_sha256") ==
           bundle_authority.get("parent_pressure_contract"),
           "Pressure authority is invalid or incomplete.")
  rows = {}
  artifacts = bundle.get("artifacts", {})
  for row in lock.get("workloads", []):
    workload = row.get("workload")
    _require(workload in PRESSURE_WORKLOADS and
             row.get("pressure_eligible") is True and
             row.get("window_records") == 500000 and
             row.get("split_relative_end_exclusive") -
             row.get("split_relative_start") == 500000 and
             row.get("addendum_sha256") ==
             bundle_authority.get("pressure_window_selection_addendum") and
             row.get("contract_sha256") ==
             bundle_authority.get("parent_pressure_contract") and
             row.get("derived_sha256") == artifacts.get(
                 row.get("derived_path", "").replace(
                     "outputs/capd_proactive_pressure_stage7/stage7-pressure-derive-r2/", "")),
             "Pressure lock metadata is invalid: " + str(workload))
    derived_path = _verified_file(project_root, row["derived_path"],
                                  row["derived_sha256"], require_source_files)
    source_path = _verified_file(project_root, row["source_test_path"],
                                 row["source_test_sha256"], require_source_files)
    item = copy.deepcopy(row)
    item["resolved_derived_path"] = derived_path
    item["resolved_source_path"] = source_path
    item["pressure_lock_sha256"] = lock_sha
    item["pressure_bundle_manifest_sha256"] = bundle_sha
    rows[workload] = item
  _require(tuple(rows) == PRESSURE_WORKLOADS,
           "Pressure lock must contain exactly four eligible workloads.")
  return rows


def _job(track: str, workload: str, source: Mapping[str, Any],
         controls: Mapping[str, Any], policy: str,
         seed: Optional[int], checkpoint: Optional[Mapping[str, Any]],
         initial_state_sha256: str, cost_profile_sha256: str) -> Dict[str, Any]:
  identity = source.get("fairness_identity") or source.get(
      "candidate_content_sha256")
  suffix = policy if seed is None else "{}__seed-{}".format(policy, seed)
  job_id = "{}__{}__{}".format(track, workload, suffix)
  if track == "standard":
    source_interval = {
        "start_inclusive": int(source["interval"]["start_inclusive"]),
        "end_exclusive": int(source["interval"]["end_exclusive"])}
    evaluation_interval = {"start_inclusive": 0, "end_exclusive": 600000}
    trace_path = source["path"]
    source_standard_sha = source["sha256"]
    pressure_fields = {
        "derived_csv_sha256": None, "source_raw_interval": None,
        "pressure_lock_sha256": None,
        "pressure_bundle_manifest_sha256": None, "addendum_sha256": None,
        "parent_r4_contract_sha256": None}
  else:
    source_interval = {
        "start_inclusive": int(source["source_interval_start_inclusive"]),
        "end_exclusive": int(source["source_interval_end_exclusive"])}
    evaluation_interval = {
        "start_inclusive": int(source["split_relative_start"]),
        "end_exclusive": int(source["split_relative_end_exclusive"])}
    trace_path = source["derived_path"]
    source_standard_sha = source["source_test_sha256"]
    pressure_fields = {
        "derived_csv_sha256": source["derived_sha256"],
        "source_raw_interval": source_interval,
        "pressure_lock_sha256": source["pressure_lock_sha256"],
        "pressure_bundle_manifest_sha256": source[
            "pressure_bundle_manifest_sha256"],
        "addendum_sha256": source["addendum_sha256"],
        "parent_r4_contract_sha256": source["contract_sha256"]}
  value = {
      "job_id": job_id, "track": track, "workload": workload,
      "workload_role": source.get("role", "pressure_derived_window"),
      "policy": policy, "seed": seed, "formal_test": True,
      "split_role": "test", "test_identity": identity,
      "trace_path": trace_path, "trace_sha256": source[
          "sha256"] if track == "standard" else source["derived_sha256"],
      "source_interval": source_interval,
      "evaluation_interval": evaluation_interval,
      "source_standard_test_sha256": source_standard_sha,
      "initial_state_sha256": initial_state_sha256,
      "cost_profile_sha256": cost_profile_sha256,
      "page_enter_dram_semantics": PAGE_ENTER_DRAM_SEMANTICS,
      "controls": copy.deepcopy(dict(controls)),
      "D": controls["D"], "dram_pages": controls["D"],
      "W_ref": controls["W_ref"], "F_low": controls["F_low"],
      "F_target": controls["F_target"], "K": controls["K"],
      "b_max": controls["b_max"], "history_H": controls["history_H"],
      "alpha": controls["alpha"], "beta": controls["beta"],
      "candidate_contract_sha256": fingerprint_value({
          "controls": controls, "workload": workload}),
      "checkpoint": copy.deepcopy(checkpoint),
      "test_used_for_selection": False,
  }
  value.update(pressure_fields)
  return value


def expected_jobs(authority: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
  controls = authority["controls"]
  jobs = []
  for track, workloads in (("standard", STANDARD_WORKLOADS),
                            ("pressure", PRESSURE_WORKLOADS)):
    source_rows = authority["standard_rows"] if track == "standard" else authority[
        "pressure_rows"]
    for workload in workloads:
      source = source_rows[workload]
      for policy in DETERMINISTIC_POLICIES:
        jobs.append(_job(track, workload, source, controls[workload], policy,
                         None, None, authority["initial_state_sha256"],
                         authority["cost_profile_sha256"]))
      for seed in CAPD_SEEDS:
        jobs.append(_job(track, workload, source, controls[workload], "capd",
                         seed, authority["checkpoint_bindings"][seed],
                         authority["initial_state_sha256"],
                         authority["cost_profile_sha256"]))
  return jobs


def audit_authority(config: Mapping[str, Any], project_root: str,
                    hash_test_payloads: bool = True,
                    require_source_files: Optional[bool] = None,
                    require_checkpoints: Optional[bool] = None) -> Dict[str, Any]:
  """Audit only lock/manifest metadata; payload bytes are never parsed here."""
  validate_config(config)
  if require_source_files is None:
    require_source_files = bool(hash_test_payloads)
  if require_checkpoints is None:
    require_checkpoints = bool(hash_test_payloads)
  paths = {}
  for name, row in config["authorities"].items():
    paths[name] = _authority_file(project_root, row, require_exists=True)
  result_schema_path = stage7.repository_path(
      project_root, config["result_schema"], must_exist=True)
  _require(fingerprint_file(result_schema_path) == config["result_schema_sha256"],
           "Stage-8 result schema SHA mismatch.")
  schema = load_json(result_schema_path)
  _require(schema.get("contract_id") == CONTRACT_ID and
           schema.get("job_result_schema") == RESULT_SCHEMA_VERSION and
           schema.get("aggregate_schema") == AGGREGATE_SCHEMA_VERSION,
           "Stage-8 result schema artifact is invalid.")
  r4 = load_json(paths["r4_final_freeze"])
  r4_contract = load_json(paths["r4_pressure_generation_contract"])
  r4_state = load_json(paths["r4_run_state"])
  stage4_freeze = load_json(paths["stage4_final_freeze"])
  model_contract = load_json(paths["stage4_model_contract"])
  checkpoint_manifest = load_json(paths["stage4_checkpoint_manifest"])
  stage4_state = load_json(paths["stage4_run_state"])
  standard_lock = load_json(paths["standard_test_lock"])
  pressure_lock = load_json(paths["pressure_test_lock"])
  pressure_bundle = load_json(paths["pressure_bundle_manifest"])
  _require(r4_state.get("formal_freeze") is True and
           r4_state.get("status") == "derived_selection_formally_frozen" and
           stage4_state.get("formal_freeze") is True and
           stage4_state.get("status") == "stage4_formally_frozen" and
           stage4_state.get("test_trace_opened") is False and
           stage4_state.get("pressure_trace_opened") is False,
           "R4/Stage-4 freeze run state is not clean.")
  _require(stage4_freeze.get("formal_freeze") is True and
           stage4_freeze.get("human_confirmation") is True and
           stage4_freeze.get("candidate", {}).get("candidate_id") ==
           "opt-balanced" and
           tuple(stage4_freeze.get("formal_seeds", ())) == CAPD_SEEDS,
           "Stage-4 formal freeze identity changed.")
  _require(tuple(model_contract.get("standard_workloads", ())) ==
           STANDARD_WORKLOADS and tuple(model_contract.get("pressure_workloads", ())) ==
           PRESSURE_WORKLOADS and
           model_contract.get("standard_pressure_same_model_checkpoint_seed_required")
           is True and model_contract.get("standard_retains_structural_zero_workloads")
           is True,
           "Stage-4 Stage-8 model contract changed.")
  controls = _controls_from_r4(r4)
  _require(r4_contract.get("formal_freeze") is True and
           r4_contract.get("pressure_test_generated") is False and
           r4_contract.get("pressure_interval_unavailable_action") ==
           "record_exclusion_and_do_not_fabricate_pressure_data",
           "R4 pressure generation contract changed.")
  checkpoint_bindings = _checkpoint_bindings(
      project_root, checkpoint_manifest, bool(require_checkpoints))
  standard_rows = _standard_rows(project_root, standard_lock,
                                 bool(require_source_files))
  pressure_rows = _pressure_rows(
      project_root, pressure_lock, pressure_bundle,
      config["authorities"]["pressure_test_lock"]["sha256"],
      config["authorities"]["pressure_bundle_manifest"]["sha256"],
      bool(require_source_files))
  cost_profile_sha256 = fingerprint_value({
      "name": config["cost_profile"]["name"],
      "weights": config["cost_profile"]["weights"]})
  initial_state_sha256 = fingerprint_value({
      "description": INITIAL_STATE_DESCRIPTION,
      "page_enter_dram_semantics": PAGE_ENTER_DRAM_SEMANTICS})
  authority = {
      "paths": paths, "result_schema_path": result_schema_path,
      "r4": r4, "r4_contract": r4_contract, "stage4_freeze": stage4_freeze,
      "model_contract": model_contract, "standard_lock": standard_lock,
      "pressure_lock": pressure_lock,
      "pressure_bundle_manifest": pressure_bundle,
      "checkpoint_bindings": checkpoint_bindings,
      "checkpoint_authority": checkpoint_bindings,
      "standard_rows": standard_rows, "pressure_rows": pressure_rows,
      "controls": controls, "initial_state_sha256": initial_state_sha256,
      "cost_profile_sha256": cost_profile_sha256,
      "test_performance_inspected": False,
      "test_payload_operation": "sha256_integrity_only_not_parsed",
  }
  authority["jobs"] = list(expected_jobs(authority))
  _require(len(authority["jobs"]) == 80 and
           sum(job["track"] == "standard" for job in authority["jobs"]) == 48 and
           sum(job["track"] == "pressure" for job in authority["jobs"]) == 32,
           "Stage-8 80-job manifest is incomplete.")
  return authority


def semantic_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
  value = copy.deepcopy(dict(result))
  value.pop("semantic_result_sha256", None)
  value.pop("runtime", None)
  if isinstance(value.get("checkpoint"), dict):
    value["checkpoint"].pop("resolved_path", None)
  for row in value.get("rounds", []):
    for key in ("feature_latency", "inference_latency", "selection_latency",
                "tpp_selection_latency"):
      row.pop(key, None)
  for row in value.get("cycles", []):
    for key in ("total_feature_time", "total_inference_time",
                "total_selection_time"):
      row.pop(key, None)
  for key in ("total_decision_time", "mean_decision_time",
              "p50_decision_time", "p95_decision_time",
              "p99_decision_time"):
    value.get("metrics", {}).pop(key, None)
  return value


def audit_job_result(result: Mapping[str, Any], job: Mapping[str, Any]) -> None:
  _require(result.get("schema_version") == RESULT_SCHEMA_VERSION and
           result.get("contract_id") == CONTRACT_ID and
           result.get("job_id") == job.get("job_id") and
           result.get("track") == job.get("track") and
           result.get("workload") == job.get("workload") and
           result.get("policy") == job.get("policy") and
           result.get("seed") == job.get("seed") and
           result.get("formal_test") is True and
           result.get("test_used_for_selection") is False,
           "Stage-8 job result identity/schema mismatch.")
  _require(result.get("D") == job["D"] and
           result.get("W_ref") == job["W_ref"] and
           result.get("F_low") == job["F_low"] and
           result.get("F_target") == job["F_target"] and
           result.get("K") == job["K"] and result.get("b_max") == job["b_max"] and
           result.get("history_H") == job["history_H"] and
           result.get("alpha") == job["alpha"] and
           result.get("beta") == job["beta"] and
           result.get("trace_sha256") == job["trace_sha256"] and
           result.get("source_interval") == job["source_interval"] and
           result.get("evaluation_interval") == job["evaluation_interval"] and
           result.get("initial_state_sha256") == job["initial_state_sha256"] and
           result.get("cost_profile_sha256") == job["cost_profile_sha256"],
           "Frozen job controls/source metadata changed.")
  _require(result.get("selector_status") == "disabled" and
           result.get("B") is None and
           result.get("old_finals_v3_stage_artifacts_used") is False and
           result.get("performance_selection_performed") is False,
           "Stage-8 result contains selection/legacy pollution.")
  pressure_fields = (
      "derived_csv_sha256", "source_standard_test_sha256",
      "source_raw_interval", "pressure_lock_sha256",
      "pressure_bundle_manifest_sha256", "addendum_sha256",
      "parent_r4_contract_sha256")
  if result["track"] == "pressure":
    _require(all(result.get(field) == job.get(field)
                 for field in pressure_fields),
             "Pressure result provenance changed.")
  else:
    _require(result.get("source_standard_test_sha256") ==
             job.get("source_standard_test_sha256") and all(
                 result.get(field) is None for field in pressure_fields
                 if field != "source_standard_test_sha256"),
             "Standard result contains Pressure provenance.")
  metrics = result.get("metrics", {})
  for field in ("dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                "proactive_demotions", "emergency_demotions", "weighted_cost",
                "raw_access_count", "weighted_cost_per_access", "fallback_rate",
                "early_reuse"):
    _require(field in metrics, "Missing Stage-8 metric: " + field)
  expected_cost = (metrics["dram_hits"] * FROZEN_COST["dram_hit"] +
                   metrics["nvm_reads"] * FROZEN_COST["nvm_read"] +
                   metrics["nvm_writes"] * FROZEN_COST["nvm_write"] +
                   metrics["total_demotions"] * FROZEN_COST["demotion"])
  _require(metrics["weighted_cost"] == expected_cost,
           "Weighted Cost does not match frozen components.")
  _require(metrics["total_demotions"] ==
           metrics["proactive_demotions"] + metrics.get("reactive_demotions", 0) +
           metrics["emergency_demotions"], "Demotion accounting mismatch.")
  _require(len(result.get("events", ())) == metrics["total_demotions"] and
           len(result.get("rounds", ())) == metrics.get("decision_count", 0) and
           len(result.get("cycles", ())) ==
           metrics.get("number_of_proactive_cycles", 0),
           "Event/round/cycle audit cardinality mismatch.")
  if result["policy"] == "capd":
    checkpoint = result.get("checkpoint") or {}
    expected = job.get("checkpoint") or {}
    _require(checkpoint.get("seed") == job.get("seed") and
             checkpoint.get("recorded_path") == expected.get("path") and
             checkpoint.get("sha256") == expected.get("sha256") and
             checkpoint.get("selection_criterion") == "minimum_valid_loss_only",
             "CAPD checkpoint identity changed.")
    oov = result.get("capd_generalization", {})
    _require(oov.get("vocabulary_expansion_allowed") is False and
             oov.get("unk_index") == 0 and
             {"page_access_oov_count", "page_unique_oov_count",
              "pc_access_oov_count", "pc_unique_oov_count"} <= set(oov),
             "CAPD OOV/UNK contract changed.")
  else:
    _require(result.get("checkpoint") is None,
             "Non-CAPD result contains a checkpoint.")
  if result["policy"] == "tpp_inspired":
    tpp = result.get("tpp_parameters", {})
    _require(tpp.get("epoch_length") == 1024 and
             tpp.get("cold_threshold") == 1 and
             tpp.get("dirty_tie_break") is False and
             tpp.get("promotion_performed") is False and
             tpp.get("D") == job["D"] and
             tpp.get("F_low") == job["F_low"] and
             tpp.get("F_target") == job["F_target"] and
             tpp.get("K") == job["K"] and tpp.get("b_max") == job["b_max"],
             "TPP job controls/semantics changed.")
  if result["policy"] == "oracle":
    _require(result.get("future_information") == "candidate_scoped_oracle_only",
             "Oracle future-information scope changed.")
  else:
    _require(result.get("future_information") == "not_accessed",
             "Online policy accessed future information.")
  _require(result.get("semantic_result_sha256") ==
           fingerprint_value(semantic_payload(result)),
           "Stage-8 semantic result SHA mismatch.")
