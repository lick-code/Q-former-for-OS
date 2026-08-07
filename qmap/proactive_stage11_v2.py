"""Stage11 v2 evidence contracts and synthetic-only generation primitives."""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from qmap import proactive_cost
from qmap import proactive_stage11_v2_guard as path_guard


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11-2.0"
CONFIG_SCHEMA_VERSION = "capd_proactive_stage11_v2_config_v1_0"
APPROVED_DESIGN_SHA256 = "0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160"
APPROVED_PLAN_SHA256 = "64a8c99acd0f2475a5a792fe732439691b6667ed11890578da74ca0707832870"
STAGE8_CONTRACT_ID = "CAPD-PROACTIVE-STAGE8-2.0"
STAGE9_CONTRACT_ID = "CAPD-PROACTIVE-STAGE9-2.0"
STAGE10_CONTRACT_ID = "CAPD-PROACTIVE-STAGE10-2.0"
STAGE10_RUN_ID = "stage10-async-simulator-v2-r2"
STANDARD_WORKLOADS = (
    "blackscholes", "canneal", "dedup_pressure", "fluidanimate",
    "streamcluster_pressure", "swaptions")
STANDARD_MEMBERS = (
    ("reactive_lru", None), ("proactive_lru", None),
    ("proactive_clock", None), ("tpp_inspired", None), ("oracle", None),
    ("capd", 42), ("capd", 2026), ("capd", 3136859))
EXPECTED_PROFILES = copy.deepcopy(proactive_cost.FROZEN_PROFILE_WEIGHTS)
REAL_SYSTEM_FLAGS = (
    "real_nvm_measurement_verified", "kernel_behavior_verified",
    "real_concurrency_verified", "real_foreground_end_to_end_latency_verified",
    "real_system_async_performance_verified")
STAGE10_GENERATION_ARTIFACTS = frozenset({
    "config.json", "event_model.md", "execution_environment.json",
    "generation_freeze_receipt.json", "generation_source_manifest.json",
    "generation_test_evidence.json", "generation_test_log.txt", "parameters.md",
    "README.md", "report.md", "run_identity.json", "run_state.json",
    "scenario_matrix.json", "simulation_results.jsonl", "stage9_input_receipt.json",
    "timing_provenance.json", "verification.json", "manifest.json", "SHA256SUMS",
})
STAGE10_READINESS_ARTIFACTS = frozenset({
    "release_readiness_test_log.txt", "release_test_source_snapshot.py",
    "protocol_pending_snapshot.md", "status_pending_snapshot.md",
    "release_readiness_test_evidence.json", "stage11_negative_audit_log.txt",
    "stage11_negative_audit_source_snapshot.json",
    "stage11_negative_audit_result.json", "stage11_negative_audit_evidence.json",
    "release_readiness_receipt.json", "manifest.json", "SHA256SUMS",
})
STAGE10_FINAL_ARTIFACTS = frozenset({
    "final_status_test_log.txt", "release_test_source_snapshot.py",
    "protocol_final_snapshot.md", "status_final_snapshot.md",
    "final_status_test_evidence.json", "final_status_evidence_receipt.json",
    "manifest.json", "SHA256SUMS",
})
STAGE10_SOURCE_ENTRY_FIELDS = frozenset({
    "logical_name", "path", "role", "sha256", "generation_identity",
    "generation_test_groups",
})
SOURCE_EXCLUSIONS = (
    "docs", "tests", "tests/fixtures", "outputs", "release_receipts",
    "__pycache__", "temporary_files")

GENERATION_SOURCE_PATHS = (
    "scripts/run_capd_proactive_stage11_v2.py",
    "qmap/proactive_stage11_v2.py",
    "qmap/proactive_stage11_v2_guard.py",
    "qmap/proactive_cost.py",
    "configs/finals/capd_proactive_stage11_v2.json",
    "configs/finals/capd_proactive_stage11_v2_config_schema.json",
    "configs/finals/capd_proactive_stage11_v2_result_schema.json",
    "configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json",
    "configs/finals/capd_proactive_stage11_v2_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_verifier_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage9_result_schema.json",
    "configs/finals/capd_proactive_stage10_result_schema_v2.json",
    "configs/finals/capd_proactive_stage10_v2_r2_config_schema.json",
    "configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_verification_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json",
)
VERIFIER_SOURCE_PATHS = (
    "scripts/verify_capd_proactive_stage11_v2.py",
    "qmap/proactive_stage11_v2_verifier.py",
    "qmap/proactive_stage11_v2_guard.py",
    "configs/finals/capd_proactive_stage11_v2.json",
    "configs/finals/capd_proactive_stage11_v2_config_schema.json",
    "configs/finals/capd_proactive_stage11_v2_result_schema.json",
    "configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json",
    "configs/finals/capd_proactive_stage11_v2_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_verifier_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_verification_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_final_approval_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_final_status_evidence_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage9_result_schema.json",
    "configs/finals/capd_proactive_stage10_result_schema_v2.json",
    "configs/finals/capd_proactive_stage10_v2_r2_config_schema.json",
    "configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_verification_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json",
)


class Stage11V2ContractError(ValueError):
  pass


class Stage11V2Blocked(Stage11V2ContractError):
  pass


class Stage11V2NotVerifiable(Stage11V2ContractError):
  pass


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage11V2ContractError(message)


def _duplicate_object(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise Stage11V2ContractError("Duplicate JSON key: {}".format(key))
    result[key] = value
  return result


def _non_finite(value):
  raise Stage11V2ContractError("Non-finite JSON value: {}".format(value))


def load_json_strict(path: os.PathLike[str] | str) -> Any:
  try:
    with open(path, "r", encoding="utf-8") as handle:
      return json.load(handle, object_pairs_hook=_duplicate_object,
                       parse_constant=_non_finite)
  except Stage11V2ContractError:
    raise
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise Stage11V2ContractError(
        "Cannot load strict JSON {}: {}".format(path, exc)) from exc


def _assert_finite(value: Any) -> None:
  if isinstance(value, Mapping):
    for item in value.values():
      _assert_finite(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      _assert_finite(item)
  elif isinstance(value, float) and not math.isfinite(value):
    raise Stage11V2ContractError("Non-finite value is forbidden.")


def canonical_json_bytes(value: Any) -> bytes:
  _assert_finite(value)
  return json.dumps(value, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_value(value: Any) -> str:
  return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def validate_external_anchor(path: os.PathLike[str] | str,
                             expected_sha256: str) -> str:
  _require(isinstance(expected_sha256, str) and len(expected_sha256) == 64,
           "An explicit external SHA256 is required.")
  actual = sha256_file(path)
  _require(actual == expected_sha256, "External SHA256 anchor mismatch.")
  return actual


def _document_status(text: str, label: str, expected: str) -> bool:
  return "- {}: `{}`".format(label, expected) in text


def validate_approval_chain(project_root: os.PathLike[str] | str,
                            config: Mapping[str, Any]) -> Dict[str, str]:
  root = Path(project_root).resolve()
  result = {}
  for key, label in (("approved_design", "Design Status"),
                     ("approved_plan", "Plan Status")):
    item = config.get(key, {})
    path = (root / str(item.get("path", ""))).resolve()
    _require(path.is_file() and path.is_relative_to(root),
             "Approved document path is invalid.")
    actual = validate_external_anchor(path, item.get("sha256"))
    text = path.read_text(encoding="utf-8")
    _require(_document_status(text, label, item.get("required_status")),
             "Approved document status mismatch: {}".format(key))
    result[key + "_sha256"] = actual
  _require(result["approved_design_sha256"] == APPROVED_DESIGN_SHA256,
           "Approved design identity changed.")
  _require(result["approved_plan_sha256"] == APPROVED_PLAN_SHA256,
           "Approved plan identity changed.")
  return result


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Stage11 v2 config must be an object.")
  expected_keys = {
      "schema_version", "contract_id", "approved_design", "approved_plan",
      "source_manifests", "upstream", "stage10_external_anchors",
      "standard_contract", "cost_profiles", "cost_semantics", "main_control",
      "analysis_grid", "model_component_ablation", "output_root",
      "execution_authorization", "production_execution_enabled",
      "test_used_for_parameter_selection"}
  _require(set(value) == expected_keys,
           "Stage11 v2 config contains missing or unknown fields.")
  _require(value.get("schema_version") == CONFIG_SCHEMA_VERSION and
           value.get("contract_id") == CONTRACT_ID,
           "Stage11 v2 config identity mismatch.")
  _require(value.get("approved_design", {}).get("sha256") ==
           APPROVED_DESIGN_SHA256, "Config approved design SHA mismatch.")
  _require(value.get("approved_plan", {}).get("sha256") ==
           APPROVED_PLAN_SHA256, "Config approved plan SHA mismatch.")
  _require(value.get("main_control") == {"b_max": 2},
           "Formal b_max must remain 2.")
  _require(value.get("cost_profiles") == EXPECTED_PROFILES,
           "Cost profiles differ from the frozen four-profile set.")
  _require(value.get("cost_semantics") == {
      "nvm_write": "NVM write access cost",
      "demotion": "DRAM to NVM migration cost"},
      "Cost semantics are incomplete.")
  standard = value.get("standard_contract", {})
  _require(standard.get("job_count") == 48 and
           tuple(standard.get("workloads", ())) == STANDARD_WORKLOADS and
           tuple((row.get("policy"), row.get("seed"))
                 for row in standard.get("members_per_workload", ())) ==
           STANDARD_MEMBERS, "Standard source membership contract changed.")
  grid = value.get("analysis_grid", {})
  _require(grid.get("b_max") == [1, 2, 4] and
           grid.get("capacity_working_set_fraction") == [0.2, 0.4, 0.6] and
           grid.get("watermark_candidates") == [] and
           grid.get("label_weight_candidates") == [] and
           grid.get("grid_frozen") is True and
           grid.get("analysis_only") is True,
           "Frozen analysis grid changed.")
  _require(value.get("model_component_ablation", {}).get("status") == "BLOCKED",
           "Model component ablation must remain blocked.")
  _require(value.get("execution_authorization") == {
      "receipt_path": None, "expected_sha256": None},
      "Repository config cannot contain an execution authorization.")
  _require(value.get("source_manifests") == {
      "generation":
          "configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json",
      "verifier":
          "configs/finals/capd_proactive_stage11_v2_verifier_source_manifest.json"},
      "Source manifest paths changed.")
  upstream = value.get("upstream", {})
  _require(set(upstream) == {
      "stage8_root", "stage9_root", "stage10_root",
      "real_upstream_semantic_audit_authorized"},
      "Upstream config fields changed.")
  anchors = value.get("stage10_external_anchors", {})
  _require(set(anchors) == {
      "generation_freeze_receipt_sha256", "readiness_receipt_sha256",
      "final_status_receipt_sha256"} and
      all(isinstance(item, str) and len(item) == 64 for item in anchors.values()),
      "Stage10 external anchors are incomplete.")
  _require(value.get("output_root") == "outputs/capd_proactive_stage11_v2",
           "Production output root changed.")
  _require(value.get("production_execution_enabled") is False and
           value.get("test_used_for_parameter_selection") is False and
           value.get("upstream", {}).get(
               "real_upstream_semantic_audit_authorized") is False,
           "Repository config exceeds the approved implementation scope.")
  return value


def frozen_grid(config: Mapping[str, Any]) -> Dict[str, Any]:
  payload = {
      "main_b_max": config["main_control"]["b_max"],
      "analysis_grid": config["analysis_grid"],
      "cost_profiles": config["cost_profiles"],
      "model_component_ablation": config["model_component_ablation"],
      "test_used_for_parameter_selection": False,
  }
  return {"grid": payload, "frozen_grid_sha256": sha256_value(payload)}


def code_version(project_root: os.PathLike[str] | str) -> Dict[str, Any]:
  root = Path(project_root).resolve()
  try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        stderr=subprocess.DEVNULL).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True,
        stderr=subprocess.DEVNULL).strip())
    return {"commit": commit, "dirty": dirty}
  except (OSError, subprocess.SubprocessError):
    return {"commit": None, "dirty": None}


def _local_import_paths(path: Path) -> set[str]:
  tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
  result = set()
  for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "qmap":
      for alias in node.names:
        result.add("qmap/{}.py".format(alias.name.replace(".", "/")))
    elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("qmap."):
      result.add(node.module.replace(".", "/") + ".py")
    elif isinstance(node, ast.Import):
      for alias in node.names:
        if alias.name.startswith("qmap."):
          result.add(alias.name.replace(".", "/") + ".py")
  return result


def source_manifest_value(project_root: os.PathLike[str] | str,
                          role: str) -> Dict[str, Any]:
  root = Path(project_root).resolve()
  paths = GENERATION_SOURCE_PATHS if role == "generation" else VERIFIER_SOURCE_PATHS
  _require(role in ("generation", "verifier"), "Unknown source role.")
  members = []
  for relative in paths:
    path = (root / relative).resolve()
    _require(path.is_file() and path.is_relative_to(root),
             "Source member is missing: {}".format(relative))
    members.append({"path": relative, "sha256": sha256_file(path)})
  members.sort(key=lambda item: item["path"])
  return {
      "schema_version": "capd_proactive_stage11_v2_source_manifest_v1_0",
      "contract_id": CONTRACT_ID,
      "role": role,
      "approved_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_plan_sha256": APPROVED_PLAN_SHA256,
      "members": members,
      "member_count": len(members),
      "members_sha256": sha256_value(members),
      "local_import_closure_complete": True,
      "exclusions": list(SOURCE_EXCLUSIONS),
  }


def validate_source_manifest(project_root: os.PathLike[str] | str,
                             manifest: Mapping[str, Any], role: str
                             ) -> Dict[str, Any]:
  expected = source_manifest_value(project_root, role)
  _require(manifest == expected, "{} source manifest mismatch.".format(role))
  paths = {item["path"] for item in manifest["members"]}
  local_imports = set()
  root = Path(project_root).resolve()
  for relative in paths:
    if relative.endswith(".py"):
      local_imports.update(_local_import_paths(root / relative))
  _require(local_imports <= paths,
           "Source manifest omits local imports: {}".format(
               sorted(local_imports - paths)))
  _require("qmap/proactive_stage11.py" not in paths and
           "scripts/run_capd_proactive_stage11.py" not in paths,
           "Stage11 v1 leaked into the v2 source set.")
  return expected


def snapshot_source_manifest(project_root: os.PathLike[str] | str,
                             manifest: Mapping[str, Any]) -> Dict[str, Any]:
  root = Path(project_root).resolve()
  records = []
  for member in manifest.get("members", []):
    path = (root / member["path"]).resolve()
    records.append({"path": member["path"], "length": path.stat().st_size,
                    "sha256": sha256_file(path)})
  records.sort(key=lambda item: item["path"])
  return {"records": records, "snapshot_sha256": sha256_value(records)}


def semantic_stage8_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
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
              "p50_decision_time", "p95_decision_time", "p99_decision_time"):
    value.get("metrics", {}).pop(key, None)
  return value


def _non_negative_int(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
           "{} must be a non-negative integer.".format(field))
  return value


def _safe_job_root(root: Path, job_id: str) -> Path:
  _require(isinstance(job_id, str) and job_id and Path(job_id).name == job_id,
           "Invalid Stage8 job_id.")
  jobs = (root / "jobs").resolve()
  target = (jobs / job_id).resolve()
  _require(target.parent == jobs, "Stage8 job path escapes jobs root.")
  return target


def _audit_stage8_result(result: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
  for field in ("job_id", "track", "workload", "policy", "seed", "D", "W_ref",
                "F_low", "F_target", "K", "b_max", "history_H", "alpha", "beta",
                "trace_sha256", "source_interval", "evaluation_interval",
                "initial_state_sha256", "cost_profile_sha256"):
    _require(result.get(field) == plan.get(field),
             "Stage8 result/plan mismatch: {}".format(field))
  _require(result.get("schema_version") == "capd_proactive_stage8_job_result_v2_0" and
           result.get("contract_id") == STAGE8_CONTRACT_ID and
           result.get("formal_test") is True and
           result.get("test_used_for_selection") is False and
           result.get("selector_status") == "disabled",
           "Stage8 result state is invalid.")
  metrics = result.get("metrics", {})
  for field in ("dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                "proactive_demotions", "reactive_demotions",
                "emergency_demotions", "raw_access_count"):
    _non_negative_int(metrics.get(field), "metrics." + field)
  _require(metrics["total_demotions"] == metrics["proactive_demotions"] +
           metrics["reactive_demotions"] + metrics["emergency_demotions"],
           "Stage8 demotion counters are inconsistent.")
  _require(result.get("semantic_result_sha256") ==
           sha256_value(semantic_stage8_payload(result)),
           "Stage8 semantic result SHA mismatch.")


def load_stage8_standard_source(root: os.PathLike[str] | str) -> Dict[str, Any]:
  stage8_root = Path(root).resolve()
  _require(stage8_root.is_dir(), "Stage8 fixture root is missing.")
  state = load_json_strict(stage8_root / "run_state.json")
  _require(state.get("contract_id") == STAGE8_CONTRACT_ID and
           state.get("status") == "stage8_sync_replay_verified" and
           state.get("test_used_for_parameter_selection") is False,
           "Stage8 run state is not verified.")
  verification = load_json_strict(stage8_root / "verification.json")
  _require(verification.get("status") == "stage8_sync_replay_verified",
           "Stage8 verification status mismatch.")
  root_manifest = load_json_strict(stage8_root / "job_manifest.json")
  plans = root_manifest.get("jobs")
  _require(root_manifest.get("contract_id") == STAGE8_CONTRACT_ID and
           isinstance(plans, list), "Stage8 root manifest is malformed.")
  standard_plans = [row for row in plans if row.get("track") == "standard"]
  plan_by_id = {row.get("job_id"): row for row in standard_plans}
  _require(len(plan_by_id) == len(standard_plans) == 48,
           "Stage8 Standard authority must contain 48 unique jobs.")

  csv_path = stage8_root / "artifacts" / "per_workload_raw.csv"
  with csv_path.open("r", encoding="utf-8", newline="") as handle:
    csv_rows = list(csv.DictReader(handle))
  selected = [row for row in csv_rows if row.get("track") == "standard"]
  csv_ids = [row.get("job_id") for row in selected]
  _require(len(csv_ids) == len(set(csv_ids)) == 48 and set(csv_ids) == set(plan_by_id),
           "Stage8 CSV Standard job set differs from authority.")

  records = []
  rows = []
  for job_id in sorted(csv_ids):
    plan = plan_by_id[job_id]
    job_root = _safe_job_root(stage8_root, job_id)
    job_manifest = load_json_strict(job_root / "job_manifest.json")
    result_path = job_root / "result.json"
    result_sha = sha256_file(result_path)
    job_identity = job_manifest.get("job_identity")
    _require(job_manifest.get("status") == "completed" and
             job_manifest.get("result_sha256") == result_sha and
             isinstance(job_identity, Mapping) and
             set(job_identity) == {
                 "checkpoint_sha256", "deterministic_runtime_environment",
                 "device", "measure_latency", "plan_job", "result_schema",
                 "run_identity_sha256", "trace_sha256"} and
             job_identity.get("plan_job") == plan and
             job_identity.get("result_schema") ==
             "capd_proactive_stage8_job_result_v2_0" and
             job_identity.get("trace_sha256") == plan.get("trace_sha256") and
             job_manifest.get("job_identity_sha256") ==
             sha256_value(job_identity),
             "Stage8 per-job manifest binding failed.")
    result = load_json_strict(result_path)
    _audit_stage8_result(result, plan)
    _require(job_manifest.get("semantic_result_sha256") ==
             result.get("semantic_result_sha256"),
             "Stage8 semantic SHA differs from job manifest.")
    metrics = result["metrics"]
    records.append({
        "job_id": job_id, "track": "standard", "workload": plan["workload"],
        "policy": plan["policy"], "seed": plan.get("seed"),
        "result_sha256": result_sha,
        "semantic_result_sha256": result["semantic_result_sha256"],
    })
    rows.append({
        "source_job_id": job_id, "track": "standard",
        "workload": plan["workload"], "policy": plan["policy"],
        "seed": plan.get("seed"), "dram_hits": metrics["dram_hits"],
        "nvm_reads": metrics["nvm_reads"], "nvm_writes": metrics["nvm_writes"],
        "total_demotions": metrics["total_demotions"],
        "proactive_demotions": metrics["proactive_demotions"],
        "reactive_demotions": metrics["reactive_demotions"],
        "emergency_demotions": metrics["emergency_demotions"],
        "raw_access_count": metrics["raw_access_count"],
        "source_result_sha256": result_sha,
        "source_semantic_result_sha256": result["semantic_result_sha256"],
    })

  _require(tuple(sorted({row["workload"] for row in records})) == STANDARD_WORKLOADS,
           "Stage8 Standard workload set mismatch.")
  for workload in STANDARD_WORKLOADS:
    actual = Counter((row["policy"], row["seed"])
                     for row in records if row["workload"] == workload)
    _require(actual == Counter(STANDARD_MEMBERS),
             "Stage8 policy/seed multiset mismatch: {}".format(workload))
  records.sort(key=lambda item: item["job_id"])
  sorted_ids = [item["job_id"] for item in records]
  return {
      "records": records,
      "rows": rows,
      "job_count": 48,
      "workload_count": 6,
      "standard_source_manifest_sha256": sha256_value(records),
      "sorted_job_ids_sha256": sha256_value(sorted_ids),
      "stage8_run_state_sha256": sha256_file(stage8_root / "run_state.json"),
      "stage8_verification_sha256": sha256_file(stage8_root / "verification.json"),
  }


def recompute_cost_rows(source: Mapping[str, Any]) -> list[Dict[str, Any]]:
  counts = proactive_cost.RawEventCounts(
      dram_hits=_non_negative_int(source.get("dram_hits"), "dram_hits"),
      nvm_reads=_non_negative_int(source.get("nvm_reads"), "nvm_reads"),
      nvm_writes=_non_negative_int(source.get("nvm_writes"), "nvm_writes"),
      total_demotions=_non_negative_int(source.get("total_demotions"), "total_demotions"),
      proactive_demotions=_non_negative_int(source.get("proactive_demotions"), "proactive_demotions"),
      reactive_demotions=_non_negative_int(source.get("reactive_demotions"), "reactive_demotions"),
      emergency_demotions=_non_negative_int(source.get("emergency_demotions"), "emergency_demotions"))
  rows = []
  for name in sorted(EXPECTED_PROFILES):
    profile = proactive_cost.CostProfile.from_mapping(name, EXPECTED_PROFILES[name])
    cost = proactive_cost.compute_weighted_cost(counts, profile)
    value = dict(source)
    accesses = _non_negative_int(source.get("raw_access_count"), "raw_access_count")
    value.update({
        "cost_profile": name, "cost_profile_weights": profile.weights_dict(),
        "weighted_cost": cost.weighted_cost,
        "weighted_cost_per_access": (
            None if accesses == 0 else cost.weighted_cost / float(accesses)),
        "evidence_mode": "offline_raw_counter_recompute",
        "evidence_status": "candidate-ready",
    })
    rows.append(value)
  return rows


def _artifact_receipt(stage: str, status: str, synthetic: bool,
                      **values: Any) -> Dict[str, Any]:
  receipt = {
      "stage": stage, "status": status,
      "synthetic_test_only": synthetic,
      "authorized_external_input": status == "verified" and not synthetic,
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False,
  }
  receipt.update(values)
  return receipt


def audit_stage9(run_root: os.PathLike[str] | str,
                 schema_path: os.PathLike[str] | str,
                 *, fixture_mode: bool = False) -> Dict[str, Any]:
  root = Path(run_root).resolve()
  try:
    schema = load_json_strict(schema_path)
    required = schema.get("required_run_artifacts", [])
    _require(required and all((root / name).is_file() for name in required),
             "Stage9 required artifact is missing.")
    state = load_json_strict(root / "run_state.json")
    verification = load_json_strict(root / "verification.json")
    compatibility = load_json_strict(root / "stage8_compatibility_receipt.json")
    environment = load_json_strict(root / "environment.json")
    _require(state.get("contract_id") == STAGE9_CONTRACT_ID and
             state.get("schema_version") == "capd_proactive_stage9_run_state_v2_0" and
             state.get("status") == "stage9_overhead_verified" and
             verification.get("status") == "stage9_overhead_verified",
             "Stage9 state is not verified.")
    for key, expected in schema.get("verification_required", {}).items():
      _require(verification.get(key) == expected,
               "Stage9 verification field mismatch: {}".format(key))
    artifact_names = [name for name in required
                      if name not in ("verification.json", "run_state.json")]
    hashes = verification.get("artifact_sha256")
    _require(isinstance(hashes, Mapping) and set(hashes) == set(artifact_names),
             "Stage9 artifact hash key set mismatch.")
    for name in artifact_names:
      _require(sha256_file(root / name) == hashes[name],
               "Stage9 artifact SHA mismatch: {}".format(name))
    _require(compatibility.get("stage9_entry_gate") == "satisfied" and
             compatibility.get("stage8_contract_id") == STAGE8_CONTRACT_ID and
             compatibility.get("stage8_status") == "stage8_sync_replay_verified" and
             compatibility.get("job_results_verified") is True and
             compatibility.get("statistics_verified") is True and
             compatibility.get("stage8_run_state_verified") is True and
             compatibility.get("stage8_artifacts_read_only") is True and
             compatibility.get("test_used_for_parameter_selection") is False,
             "Stage9 compatibility receipt mismatch.")
    _require(environment.get("system") == "Linux" and
              environment.get("device") == "cpu" and
              isinstance(environment.get("linux_kernel"), str),
              "Stage9 Linux CPU evidence is missing.")
    perf = load_json_strict(root / "perf" / "perf_parsed.json")
    events = perf.get("events", {})
    _require(perf.get("counter_source") == schema.get("perf_counter_source") and
             perf.get("required_events_verified") is True and
             perf.get("cycles_verified") is True and
             set(events) >= set(schema.get("perf_required_events", [])),
             "Stage9 Linux perf evidence is incomplete.")
    for event in schema.get("perf_required_events", []):
      row = events.get(event, {})
      _require(row.get("status") == "ok" and
               isinstance(row.get("value"), (int, float)) and
               not isinstance(row.get("value"), bool) and row["value"] > 0,
               "Stage9 perf event is invalid: {}".format(event))
    derived = perf.get("derived", {})
    _require(all(isinstance(derived.get(field), (int, float)) and
                 not isinstance(derived.get(field), bool) and
                 derived[field] > 0
                 for field in schema.get("perf_derived_fields", [])),
             "Stage9 derived perf fields are invalid.")
    scope = load_json_strict(root / "perf" / "perf_scope_counts.json")
    _require(all(field in scope for field in
                 schema.get("perf_scope_required_fields", [])) and
             isinstance(scope.get("measured_rounds"), int) and
             scope["measured_rounds"] > 0 and
             isinstance(scope.get("measured_demoted_pages"), int) and
             scope["measured_demoted_pages"] > 0,
             "Stage9 perf scope evidence is incomplete.")
    memory = load_json_strict(root / "memory_breakdown.json")
    _require(all(field in memory for field in
                 schema.get("memory_required_fields", [])),
             "Stage9 memory evidence is incomplete.")
    rss = memory.get("rss", {})
    _require(all(field in rss for field in
                 schema.get("memory_rss_required_fields", [])) and
             isinstance(rss.get("process_baseline_rss_bytes"), int) and
             rss["process_baseline_rss_bytes"] > 0 and
             isinstance(rss.get("total_peak_rss_bytes"), int) and
             rss["total_peak_rss_bytes"] >= rss["process_baseline_rss_bytes"] and
             rss.get("stage9_incremental_peak_rss_bytes") ==
             rss["total_peak_rss_bytes"] - rss["process_baseline_rss_bytes"],
             "Stage9 RSS evidence is invalid.")
    with (root / "raw_latency_samples.csv").open(
        "r", encoding="utf-8", newline="") as handle:
      latency_reader = csv.DictReader(handle)
      latency_rows = list(latency_reader)
      latency_fields = set(latency_reader.fieldnames or ())
    _require(set(schema.get("raw_latency_required_fields", [])) <= latency_fields and
             len(latency_rows) > 0,
             "Stage9 raw CPU latency evidence is incomplete.")
    synthetic = fixture_mode or verification.get("synthetic_test_only") is True
    return _artifact_receipt(
        "stage9", "synthetic_structure_verified" if synthetic else "verified",
        synthetic,
        run_state_sha256=sha256_file(root / "run_state.json"),
        verification_sha256=sha256_file(root / "verification.json"),
        stage8_compatibility_receipt_sha256=sha256_file(
            root / "stage8_compatibility_receipt.json"),
        artifact_verified_count=len(artifact_names),
        population_scope="stage9_contract_not_standard_only_latency_aggregate")
  except Exception as exc:
    return _artifact_receipt(
        "stage9", "NOT_VERIFIABLE", fixture_mode,
        reason_code="invalid_stage9_input", detail=str(exc),
        run_state_sha256=None, verification_sha256=None,
        stage8_compatibility_receipt_sha256=None)


def _relative_files(root: Path) -> list[tuple[str, Path]]:
  return sorted((path.relative_to(root).as_posix(), path)
                for path in root.rglob("*") if path.is_file())


def manifest_value(root: os.PathLike[str] | str, phase: str) -> Dict[str, Any]:
  base = Path(root).resolve()
  files = {name: sha256_file(path) for name, path in _relative_files(base)
           if name not in ("manifest.json", "SHA256SUMS")}
  return {
      "schema_version": "capd_proactive_stage11_v2_release_manifest_v1_0",
      "contract_id": CONTRACT_ID, "phase": phase, "files": files}


def checksum_text(root: os.PathLike[str] | str) -> str:
  base = Path(root).resolve()
  return "".join("{}  {}\n".format(sha256_file(path), name)
                 for name, path in _relative_files(base)
                 if name != "SHA256SUMS")


def verify_release_envelope(root: os.PathLike[str] | str, phase: str,
                            *, expected_receipt_name: Optional[str] = None,
                            expected_receipt_sha256: Optional[str] = None
                            ) -> Dict[str, Any]:
  base = Path(root).resolve()
  manifest = load_json_strict(base / "manifest.json")
  _require(manifest.get("phase") == phase and
           manifest.get("contract_id") in (CONTRACT_ID, STAGE10_CONTRACT_ID),
           "Release manifest phase/contract mismatch.")
  actual_payload = {name for name, _ in _relative_files(base)
                    if name not in ("manifest.json", "SHA256SUMS")}
  files = manifest.get("files")
  _require(isinstance(files, Mapping) and set(files) == actual_payload,
           "Release manifest payload set mismatch.")
  for name, expected in files.items():
    _require(sha256_file(base / name) == expected,
             "Release manifest SHA mismatch: {}".format(name))
  expected_checksum_names = actual_payload | {"manifest.json"}
  entries = []
  with (base / "SHA256SUMS").open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        parts = line.rstrip("\n").split("  ", 1)
        _require(len(parts) == 2, "Malformed SHA256SUMS line.")
        entries.append((parts[0], parts[1]))
  _require(len(entries) == len({name for _, name in entries}) and
           {name for _, name in entries} == expected_checksum_names,
           "Release checksum member set mismatch.")
  for expected, name in entries:
    _require(sha256_file(base / name) == expected,
             "Release checksum mismatch: {}".format(name))
  if expected_receipt_name is not None:
    receipt_path = base / expected_receipt_name
    validate_external_anchor(receipt_path, expected_receipt_sha256)
  return {
      "manifest_sha256": sha256_file(base / "manifest.json"),
      "checksums_sha256": sha256_file(base / "SHA256SUMS"),
      "payload_count": len(actual_payload),
  }


def _stage10_checksum_rows(base: Path, expected_names: set[str]) -> None:
  rows = []
  with (base / "SHA256SUMS").open("r", encoding="utf-8") as handle:
    for line in handle:
      if not line.strip():
        continue
      parts = line.rstrip("\n").split("  ", 1)
      _require(len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]),
               "Stage10 SHA256SUMS line is malformed.")
      rows.append((parts[0], parts[1]))
  names = [name for _, name in rows]
  _require(len(names) == len(set(names)) and set(names) == expected_names,
           "Stage10 SHA256SUMS member set differs.")
  for expected, name in rows:
    _require(sha256_file(base / name) == expected,
             "Stage10 SHA256SUMS mismatch: {}".format(name))


def _verify_stage10_generation_envelope(base: Path) -> Dict[str, Any]:
  names = {name for name, _ in _relative_files(base)}
  _require(names == set(STAGE10_GENERATION_ARTIFACTS),
           "Stage10 generation artifact set is not exact.")
  manifest = load_json_strict(base / "manifest.json")
  _require(set(manifest) == {"schema_version", "files"} and
           manifest.get("schema_version") ==
           "capd_proactive_stage10_manifest_v2_1",
           "Stage10 generation manifest identity is invalid.")
  payload_names = names - {"manifest.json", "SHA256SUMS"}
  files = manifest.get("files")
  _require(isinstance(files, Mapping) and set(files) == payload_names,
           "Stage10 generation manifest member set differs.")
  for name, expected in files.items():
    _require(re.fullmatch(r"[0-9a-f]{64}", str(expected)) is not None and
             sha256_file(base / name) == expected,
             "Stage10 generation manifest SHA mismatch: {}".format(name))
  _stage10_checksum_rows(base, names - {"SHA256SUMS"})
  return {
      "manifest_sha256": sha256_file(base / "manifest.json"),
      "checksums_sha256": sha256_file(base / "SHA256SUMS"),
  }


def _verify_stage10_release_envelope(base: Path, phase: str,
                                     expected_artifacts: frozenset[str],
                                     receipt_name: str,
                                     receipt_sha256: str) -> Dict[str, Any]:
  names = {name for name, _ in _relative_files(base)}
  _require(names == set(expected_artifacts),
           "Stage10 {} artifact set is not exact.".format(phase))
  manifest = load_json_strict(base / "manifest.json")
  _require(set(manifest) == {"schema_version", "phase", "files"} and
           manifest.get("schema_version") ==
           "capd_proactive_stage10_release_manifest_v1_0" and
           manifest.get("phase") == phase,
           "Stage10 release manifest identity is invalid.")
  payload_names = names - {"manifest.json", "SHA256SUMS"}
  files = manifest.get("files")
  _require(isinstance(files, Mapping) and set(files) == payload_names,
           "Stage10 release manifest member set differs.")
  for name, expected in files.items():
    _require(re.fullmatch(r"[0-9a-f]{64}", str(expected)) is not None and
             sha256_file(base / name) == expected,
             "Stage10 release manifest SHA mismatch: {}".format(name))
  _stage10_checksum_rows(base, names - {"SHA256SUMS"})
  validate_external_anchor(base / receipt_name, receipt_sha256)
  return {
      "manifest_sha256": sha256_file(base / "manifest.json"),
      "checksums_sha256": sha256_file(base / "SHA256SUMS"),
  }


def _stage10_source_diagnostics(source: Mapping[str, Any], *,
                                fixture_mode: bool) -> tuple[bool, str]:
  _require(set(source) == {"schema_version", "source_set_id", "entries"} and
           source.get("schema_version") ==
           "capd_proactive_stage10_generation_source_manifest_v1_0" and
           source.get("source_set_id") == "stage10-v2-r2-generation-core-v1",
           "Stage10 generation source manifest identity is invalid.")
  entries = source.get("entries")
  _require(isinstance(entries, list) and len(entries) == 11,
           "Stage10 generation source manifest must contain exactly 11 entries.")
  paths = []
  logical_names = []
  for entry in entries:
    _require(isinstance(entry, Mapping) and
             set(entry) == set(STAGE10_SOURCE_ENTRY_FIELDS),
             "Stage10 generation source entry fields are not exact.")
    path = entry.get("path")
    pure = PurePosixPath(path) if isinstance(path, str) else PurePosixPath(".")
    _require(isinstance(path, str) and path == pure.as_posix() and
             not pure.is_absolute() and
             all(part not in ("", ".", "..") for part in pure.parts),
             "Stage10 generation source path is unsafe.")
    _require(entry.get("generation_identity") is True and
             entry.get("generation_test_groups") == ["generation_core"] and
             entry.get("role") in {"runtime", "runner", "test", "support"} and
             isinstance(entry.get("logical_name"), str) and
             re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))),
             "Stage10 generation source entry is invalid.")
    paths.append(path)
    logical_names.append(entry["logical_name"])
  _require(len(paths) == len(set(paths)) and
           len(logical_names) == len(set(logical_names)),
           "Stage10 generation source entries are duplicated.")
  if fixture_mode:
    return True, sha256_value(entries)
  project_root = Path(__file__).resolve().parents[1]
  matches = True
  for entry in entries:
    candidate = (project_root / entry["path"]).resolve()
    if (not candidate.is_file() or not candidate.is_relative_to(project_root) or
        sha256_file(candidate) != entry["sha256"]):
      matches = False
  return matches, sha256_value(entries)


def audit_stage10_r2(root: os.PathLike[str] | str,
                     anchors: Mapping[str, str], *, fixture_mode: bool = False
                     ) -> Dict[str, Any]:
  base = Path(root).resolve()
  try:
    generation = _verify_stage10_generation_envelope(base)
    identity = load_json_strict(base / "run_identity.json")
    state = load_json_strict(base / "run_state.json")
    verification = load_json_strict(base / "verification.json")
    _require(set(identity) == {
                 "approved_design_sha256", "approved_freeze_receipt_sha256",
                 "approved_plan_sha256", "config_sha256", "contract_id",
                 "controlled_execution", "conversion_rule", "evidence_mode",
                 "execution_environment_schema", "execution_environment_sha256",
                 "generation_freeze_receipt_sha256", "generation_source_entry_count",
                 "generation_source_manifest_schema",
                 "generation_source_manifest_sha256",
                 "generation_source_set_fingerprint_sha256",
                 "generation_source_set_id", "generation_test_evidence_sha256",
                 "git", "result_schema_sha256", "run_id", "run_identity_sha256",
                 "scenario_matrix_sha256", "schema_version",
                 "stage9_checkpoint_sha256", "stage9_config_sha256",
                 "stage9_input_receipt_sha256", "stage9_latency_summary_sha256",
                 "stage9_run_identity_sha256", "stage9_verification_sha256",
                 "timing_provenance_sha256"} and
             identity.get("schema_version") ==
             "capd_proactive_stage10_run_identity_v2_1" and
             identity.get("run_id") == STAGE10_RUN_ID and
             identity.get("contract_id") == STAGE10_CONTRACT_ID and
             identity.get("evidence_mode") == "deterministic_async_simulation",
             "Stage10 sealed run identity mismatch.")
    _require(set(state) == {
                 "artifacts_independently_verified", "contract_id", "evidence_mode",
                 "failure", "real_system_async_performance_verified", "run_id",
                 "schema_version", "simulation_executed", "stage9_input_gate_passed",
                 "status"} and
             state.get("schema_version") ==
             "capd_proactive_stage10_run_state_v2_1" and
             state.get("contract_id") == STAGE10_CONTRACT_ID and
             state.get("run_id") == STAGE10_RUN_ID and
             state.get("status") == "stage10_async_simulation_verified" and
             state.get("artifacts_independently_verified") is True and
             state.get("simulation_executed") is True and
             state.get("stage9_input_gate_passed") is True and
             state.get("failure") is None and
             state.get("real_system_async_performance_verified") is False and
             set(verification) == {
                 "approved_freeze_receipt_sha256", "artifacts_independently_recomputed",
                 "contract_id", "controlled_execution",
                 "current_generation_sources_recomputed", "evidence_mode",
                 "execution_environment_sha256", "generation_source_entry_count",
                 "generation_source_manifest_sha256",
                 "generation_source_set_fingerprint_sha256",
                 "generation_test_evidence_sha256", "generation_tests_verified",
                 "kernel_behavior_verified", "real_concurrency_verified",
                 "real_foreground_end_to_end_latency_verified",
                 "real_nvm_measurement_verified", "real_system_async_performance_verified",
                 "result_count", "scenario_ids", "schema_version",
                 "simulation_executed", "stage9_input_gate", "status"} and
             verification.get("schema_version") ==
             "capd_proactive_stage10_verification_v2_1" and
             verification.get("contract_id") == STAGE10_CONTRACT_ID and
             verification.get("status") == "stage10_async_simulation_verified",
             "Stage10 generation is not verified.")
    for flag in REAL_SYSTEM_FLAGS:
      _require(verification.get(flag) is False,
               "Stage10 capability contract is inconsistent: {}".format(flag))
    _require(verification.get("artifacts_independently_recomputed") is True and
             verification.get("current_generation_sources_recomputed") is True and
             verification.get("generation_tests_verified") is True and
             verification.get("simulation_executed") is True and
             verification.get("stage9_input_gate") == "satisfied" and
             verification.get("result_count") == 60,
             "Stage10 verification assertions are incomplete.")
    matrix = load_json_strict(base / "scenario_matrix.json")
    matrix_rows = matrix.get("scenarios") if isinstance(matrix, Mapping) else matrix
    _require(isinstance(matrix_rows, list) and len(matrix_rows) == 60,
             "Stage10 scenario matrix must contain 60 rows.")
    matrix_ids = [row.get("scenario_id") for row in matrix_rows]
    _require(None not in matrix_ids and len(set(matrix_ids)) == 60,
             "Stage10 scenario IDs are missing or duplicated.")
    result_rows = []
    with (base / "simulation_results.jsonl").open("r", encoding="utf-8") as handle:
      for line in handle:
        if line.strip():
          result_rows.append(json.loads(line))
    result_ids = [row.get("scenario_id") for row in result_rows]
    _require(len(result_ids) == 60 and result_ids == matrix_ids,
             "Stage10 matrix/result scenario identity mismatch.")
    _require(verification.get("scenario_ids") == matrix_ids,
             "Stage10 verification scenario IDs differ from generation.")

    source = load_json_strict(base / "generation_source_manifest.json")
    source_set_match, source_fingerprint = _stage10_source_diagnostics(
        source, fixture_mode=fixture_mode)
    source_sha = sha256_file(base / "generation_source_manifest.json")
    freeze_name = "generation_freeze_receipt.json"
    validate_external_anchor(
        base / freeze_name, anchors.get("generation_freeze_receipt_sha256"))
    freeze = load_json_strict(base / freeze_name)
    _require(set(freeze) == {
                 "approved_design", "approved_plan", "authorization_state",
                 "commands", "config", "controlled_execution",
                 "environment_contract", "schema_version", "schemas",
                 "source_manifest", "source_set_id", "stage9_binding"} and
             freeze.get("schema_version") ==
             "capd_proactive_stage10_generation_freeze_receipt_v1_0" and
             freeze.get("source_set_id") == "stage10-v2-r2-generation-core-v1" and
             freeze.get("authorization_state") == {
                 "formal_run_authorized_at_receipt_creation": False,
                 "release_authorized_at_receipt_creation": False,
                 "stage11_positive_migration_authorized_at_receipt_creation": False},
             "Stage10 generation freeze receipt is invalid.")
    source_binding = freeze.get("source_manifest")
    _require(isinstance(source_binding, Mapping) and
             set(source_binding) == {"entry_count", "fingerprint_sha256", "path",
                                     "schema_version", "sha256", "source_set_id"} and
             source_binding.get("path") ==
             "configs/finals/capd_proactive_stage10_v2_r2_source_manifest.json" and
             source_binding.get("schema_version") == source.get("schema_version") and
             source_binding.get("source_set_id") == source.get("source_set_id") and
             source_binding.get("entry_count") == 11 and
             source_binding.get("sha256") == source_sha and
             source_binding.get("fingerprint_sha256") == source_fingerprint,
             "Stage10 freeze/source binding mismatch.")
    freeze_sha = sha256_file(base / freeze_name)
    _require(identity.get("generation_freeze_receipt_sha256") == freeze_sha and
             identity.get("approved_freeze_receipt_sha256") == freeze_sha and
             identity.get("generation_source_manifest_sha256") == source_sha and
             identity.get("generation_source_entry_count") == 11 and
             identity.get("generation_source_set_fingerprint_sha256") ==
             source_fingerprint and
             verification.get("approved_freeze_receipt_sha256") == freeze_sha and
             verification.get("generation_source_manifest_sha256") == source_sha and
             verification.get("generation_source_entry_count") == 11 and
             verification.get("generation_source_set_fingerprint_sha256") ==
             source_fingerprint,
             "Stage10 generation identity/source bindings differ.")
    git_binding = identity.get("git")
    _require(isinstance(git_binding, Mapping) and
             set(git_binding) == {"commit", "generation_source_set_fingerprint_sha256"} and
             git_binding.get("generation_source_set_fingerprint_sha256") ==
             source_fingerprint and
             re.fullmatch(r"[0-9a-f]{40}", str(git_binding.get("commit"))),
             "Stage10 sealed repository revision binding is invalid.")

    release_root = base.parent / "release_receipts" / STAGE10_RUN_ID
    readiness_root = release_root / "readiness"
    final_root = release_root / "final-status"
    readiness_name = "release_readiness_receipt.json"
    final_name = "final_status_evidence_receipt.json"
    readiness_envelope = _verify_stage10_release_envelope(
        readiness_root, "readiness", STAGE10_READINESS_ARTIFACTS,
        readiness_name, anchors.get("readiness_receipt_sha256"))
    final_envelope = _verify_stage10_release_envelope(
        final_root, "final_status", STAGE10_FINAL_ARTIFACTS,
        final_name, anchors.get("final_status_receipt_sha256"))
    readiness = load_json_strict(readiness_root / readiness_name)
    final = load_json_strict(final_root / final_name)
    _require(set(readiness) == {
                 "approved_freeze_receipt_sha256", "completion_decision",
                 "contract_id", "evidence_mode", "generation_chain",
                 "real_system_async_performance_verified", "release_status",
                 "release_test_evidence_sha256", "run_id", "schema_version",
                 "stage11_negative_audit", "stage11_positive_migration_authorized",
                 "synthetic_test_only"} and
             readiness.get("schema_version") ==
             "capd_proactive_stage10_release_readiness_receipt_v1_0" and
             readiness.get("contract_id") == STAGE10_CONTRACT_ID and
             readiness.get("run_id") == STAGE10_RUN_ID and
             readiness.get("release_status") == "stage10_release_readiness_verified" and
             readiness.get("completion_decision") ==
             "approved_for_status_finalization" and
             readiness.get("approved_freeze_receipt_sha256") == freeze_sha and
             readiness.get("stage11_positive_migration_authorized") is False and
             readiness.get("real_system_async_performance_verified") is False and
             readiness.get("synthetic_test_only") is fixture_mode,
             "Stage10 sealed dual-verifier attestation failed.")
    chain = readiness.get("generation_chain")
    _require(isinstance(chain, Mapping) and set(chain) == {
                 "run_identity_sha256", "verification_sha256", "run_state_sha256",
                 "manifest_sha256", "checksums_sha256", "native_verifier_status",
                 "dispatcher_verifier_status", "stage9_artifact_sha256_verified_count",
                 "stage10a", "synthetic_test_only"} and
             chain.get("run_identity_sha256") == sha256_file(base / "run_identity.json") and
             chain.get("verification_sha256") == sha256_file(base / "verification.json") and
             chain.get("run_state_sha256") == sha256_file(base / "run_state.json") and
             chain.get("manifest_sha256") == generation["manifest_sha256"] and
             chain.get("checksums_sha256") == generation["checksums_sha256"] and
             chain.get("native_verifier_status") ==
             "stage10_async_simulation_verified" and
             chain.get("dispatcher_verifier_status") ==
             "stage10_async_simulation_verified" and
             chain.get("stage9_artifact_sha256_verified_count") == 19 and
             chain.get("stage10a") == {
                 "status": "verified", "result_count": 5, "manifest_files": 12} and
             chain.get("synthetic_test_only") is fixture_mode,
             "Stage10 sealed generation chain mismatch.")
    negative = readiness.get("stage11_negative_audit")
    _require(isinstance(negative, Mapping) and
             set(negative) == {"result", "result_sha256", "evidence_sha256",
                               "source_snapshot_sha256"} and
             negative.get("result") == {
                 "stage10a": {"formal_authorized": False,
                              "reason_code": "stage10a_fixture_only",
                              "status": "BLOCKED"},
                 "stage10_r2": {"formal_authorized": False,
                                "reason_code": "invalid_stage10a_fixture",
                                "status": "NOT_VERIFIABLE"}} and
             negative.get("result_sha256") == sha256_file(
                 readiness_root / "stage11_negative_audit_result.json") and
             negative.get("evidence_sha256") == sha256_file(
                 readiness_root / "stage11_negative_audit_evidence.json") and
             negative.get("source_snapshot_sha256") == sha256_file(
                 readiness_root / "stage11_negative_audit_source_snapshot.json") and
             readiness.get("release_test_evidence_sha256") == sha256_file(
                 readiness_root / "release_readiness_test_evidence.json"),
             "Stage10 readiness evidence bindings differ.")
    _require(set(final) == {
                 "approved_freeze_receipt_sha256", "completion_decision", "contract_id",
                 "final_status_test_evidence_sha256", "readiness_checksums_sha256",
                 "readiness_manifest_sha256", "readiness_receipt_sha256",
                 "real_system_async_performance_verified", "run_id", "schema_version",
                 "status", "synthetic_test_only"} and
             final.get("schema_version") ==
             "capd_proactive_stage10_final_status_evidence_receipt_v1_0" and
             final.get("contract_id") == STAGE10_CONTRACT_ID and
             final.get("run_id") == STAGE10_RUN_ID and
             final.get("status") == "stage10_final_status_evidence_verified",
             "Stage10 final-status receipt mismatch.")
    _require(final.get("approved_freeze_receipt_sha256") == freeze_sha and
             final.get("completion_decision") == "approved_for_status_finalization" and
             final.get("readiness_receipt_sha256") == sha256_file(
                 readiness_root / readiness_name) and
             final.get("readiness_manifest_sha256") ==
             readiness_envelope["manifest_sha256"] and
             final.get("readiness_checksums_sha256") ==
             readiness_envelope["checksums_sha256"] and
             final.get("final_status_test_evidence_sha256") == sha256_file(
                 final_root / "final_status_test_evidence.json") and
             final.get("real_system_async_performance_verified") is False and
             final.get("synthetic_test_only") is fixture_mode,
             "Stage10 final-status evidence bindings differ.")
    repository_revision_match = (not fixture_mode and
        code_version(Path(__file__).resolve().parents[1]).get("commit") ==
        git_binding.get("commit"))
    return _artifact_receipt(
        "stage10", "synthetic_structure_verified" if fixture_mode else "verified",
        fixture_mode, contract_id=STAGE10_CONTRACT_ID, run_id=STAGE10_RUN_ID,
        artifact_integrity="verified",
        sealed_dual_verifier_attestation="verified",
        generation_source_set_match=source_set_match,
        repository_revision_match=repository_revision_match,
        current_live_replay_compatibility="NOT_VERIFIABLE",
        reason_code=(None if repository_revision_match else
                     "repository_revision_differs_from_sealed_generation_revision"),
        generation_manifest_sha256=generation["manifest_sha256"],
        readiness_manifest_sha256=readiness_envelope["manifest_sha256"],
        final_status_manifest_sha256=final_envelope["manifest_sha256"])
  except Exception as exc:
    return _artifact_receipt(
        "stage10", "NOT_VERIFIABLE", fixture_mode,
        reason_code="invalid_stage10_r2_input", detail=str(exc))


def validate_execution_authorization(
    receipt_path: os.PathLike[str] | str, expected_sha256: str,
    expected: Mapping[str, Any], *, synthetic_mode: bool
) -> Dict[str, Any]:
  validate_external_anchor(receipt_path, expected_sha256)
  receipt = load_json_strict(receipt_path)
  _require(receipt.get("schema_version") ==
           "capd_proactive_stage11_v2_execution_authorization_v1_0" and
           receipt.get("contract_id") == CONTRACT_ID,
           "Execution authorization identity mismatch.")
  allowed_fields = {
      "schema_version", "contract_id", "run_id", "approved_design_sha256",
      "approved_plan_sha256", "config_sha256", "result_schema_sha256",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "standard_source_manifest_sha256", "sorted_job_ids_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256",
      "frozen_grid_sha256", "authorized_scope",
      "stage11_execution_authorized", "synthetic_test_only",
      "test_used_for_parameter_selection", "future_output_hashes_absent"}
  _require(set(receipt) == allowed_fields,
           "Execution authorization contains missing or unknown fields.")
  required_equal = (
      "run_id", "approved_design_sha256", "approved_plan_sha256",
      "config_sha256", "result_schema_sha256",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "standard_source_manifest_sha256", "sorted_job_ids_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256",
      "frozen_grid_sha256")
  for field in required_equal:
    _require(receipt.get(field) == expected.get(field),
             "Execution authorization binding mismatch: {}".format(field))
  _require(receipt.get("stage11_execution_authorized") is True and
           receipt.get("authorized_scope") == (
               "synthetic_fixture_generation_only" if synthetic_mode else
               "stage11_v2_production_generation") and
           receipt.get("test_used_for_parameter_selection") is False and
           receipt.get("future_output_hashes_absent") is True and
           receipt.get("synthetic_test_only") is synthetic_mode,
           "Execution authorization scope/state mismatch.")
  forbidden = {"result_sha256", "manifest_sha256", "verification_receipt_sha256",
               "final_status_receipt_sha256", "stage11_formally_verified"}
  _require(not (forbidden & set(receipt)),
           "Execution authorization binds a future output.")
  return receipt


def atomic_write_text(capability: Any, relative: str, value: str) -> Path:
  target = path_guard.child_target(capability, relative)
  target.parent.mkdir(parents=True, exist_ok=True)
  temporary = target.with_name(target.name + ".tmp")
  path_guard.require_capability(capability, temporary)
  temporary.write_text(value, encoding="utf-8", newline="")
  os.replace(temporary, target)
  return target


def atomic_write_json(capability: Any, relative: str, value: Any) -> Path:
  return atomic_write_text(
      capability, relative,
      json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                 allow_nan=False) + "\n")


def write_release_envelope(capability: Any, phase: str) -> Dict[str, str]:
  cap = path_guard.require_capability(capability)
  manifest = manifest_value(cap.root, phase)
  atomic_write_json(cap, "manifest.json", manifest)
  atomic_write_text(cap, "SHA256SUMS", checksum_text(cap.root))
  return {"manifest_sha256": sha256_file(cap.root / "manifest.json"),
          "checksums_sha256": sha256_file(cap.root / "SHA256SUMS")}


def render_missing(value: Any) -> str:
  return "N/A" if value is None else str(value)
