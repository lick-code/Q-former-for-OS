"""Independent Stage11 v2 production verifier and release consumers."""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from qmap import proactive_stage11_v2_production_guard as production_guard


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11-2.0"
PRODUCTION_REVISION = "stage11-v2-production-r6"
RUN_ID = "stage11-standard-cost-profiles-v2-r6"
AUDIT_ID = "stage11-input-audit-v2-r7"
APPROVED_DESIGN_SHA256 = (
    "ec00fdaeac4084f638fbf6da866d4444badd26dfac95eef061e137a5a26ba356")
APPROVED_PLAN_SHA256 = (
    "5ada02d3cd2f14c116dccbf4336dc833c460c3d7198e58eb17efd72f0bc66143")
STANDARD_WORKLOADS = (
    "blackscholes", "canneal", "dedup_pressure", "fluidanimate",
    "streamcluster_pressure", "swaptions")
STANDARD_MEMBERS = (
    ("reactive_lru", None), ("proactive_lru", None),
    ("proactive_clock", None), ("tpp_inspired", None), ("oracle", None),
    ("capd", 42), ("capd", 2026), ("capd", 3136859))
PROFILE_NAMES = (
    "read_light", "default", "write_expensive", "migration_expensive")
PROFILE_WEIGHTS = {
    "read_light": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 4,
                   "demotion": 8},
    "default": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
                "demotion": 10},
    "write_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 12,
                        "demotion": 10},
    "migration_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
                            "demotion": 20},
}
BLOCKED_LANES = (
    "watermark_sensitivity", "label_weight_sensitivity",
    "capacity_sensitivity", "batch_sensitivity_b_max_1_4",
    "top1_topb_replay", "component_ablation", "inference_masking_diagnosis",
    "stage9_new_overhead_measurement", "stage10_new_async_scenario",
    "real_system_overhead_or_async_performance")
VERIFICATION_PAYLOADS = frozenset(
    production_guard.PHASE_ARTIFACTS["verification"] - {"manifest.json", "SHA256SUMS"})
GENERATION_PAYLOADS = frozenset(
    production_guard.PHASE_ARTIFACTS["generation"] - {"manifest.json", "SHA256SUMS"})
FROZEN_TREE_PATHS = (
    ("stage10_root", "outputs/capd_proactive_stage10"),
    ("stage11_v1", "outputs/capd_proactive_stage11"),
    ("stage4_stage7", "outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2"),
    ("stage8_r5", "outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit"),
    ("stage9_root", "outputs/capd_proactive_stage9"),
)

GENERATION_SOURCE_PATHS = (
    "configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_result_schema_v2.json",
    "configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_v2_r2_config_schema.json",
    "configs/finals/capd_proactive_stage10_verification_schema_v2_1.json",
    "configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json",
    "configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json",
    "configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production.json",
    "configs/finals/capd_proactive_stage11_v2_production_config_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_result_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json",
    "configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json",
    "configs/finals/capd_proactive_stage9_result_schema.json",
    "qmap/proactive_cost.py",
    "qmap/proactive_stage11_v2_production.py",
    "qmap/proactive_stage11_v2_production_guard.py",
    "scripts/run_capd_proactive_stage11_v2_production.py",
)

TEST_SOURCE_PATHS = (
    "qmap/finals_config.py", "qmap/proactive_cost.py",
    "qmap/proactive_replay.py", "qmap/proactive_stage10.py",
    "qmap/proactive_stage10_v2.py", "qmap/proactive_stage11.py",
    "qmap/proactive_stage11_v2.py", "qmap/proactive_stage11_v2_guard.py",
    "qmap/proactive_stage11_v2_production.py",
    "qmap/proactive_stage11_v2_production_guard.py",
    "qmap/proactive_stage11_v2_production_verifier.py",
    "qmap/proactive_stage11_v2_verifier.py", "qmap/proactive_stage3.py",
    "qmap/proactive_stage4.py", "qmap/proactive_stage7_workloads.py",
    "qmap/proactive_stage8_contract.py", "qmap/qmap_generator.py",
    "scripts/run_capd_proactive_stage10.py",
    "scripts/run_capd_proactive_stage10_v2.py",
    "scripts/run_capd_proactive_stage11_v2.py",
    "scripts/run_capd_proactive_stage11_v2_production.py",
    "scripts/verify_capd_proactive_stage11_v2.py",
    "scripts/verify_capd_proactive_stage11_v2_production.py",
    "tests/stage10_v2_test_support.py", "tests/test_capd_proactive_stage10.py",
    "tests/test_capd_proactive_stage10_v2.py",
    "tests/test_capd_proactive_stage11.py",
    "tests/test_capd_proactive_stage11_v2.py",
    "tests/test_capd_proactive_stage11_v2_production.py",
)

INPUT_AUDIT_PAYLOADS = frozenset(
    production_guard.PHASE_ARTIFACTS["input_audit"] - {"manifest.json", "SHA256SUMS"})

VERIFIER_SOURCE_PATHS = (
    "configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_manifest_schema.json",
    "configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json",
    "configs/finals/capd_proactive_stage10_result_schema_v2.json",
    "configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json",
    "configs/finals/capd_proactive_stage10_v2_r2_config_schema.json",
    "configs/finals/capd_proactive_stage10_verification_schema_v2_1.json",
    "configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json",
    "configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json",
    "configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production.json",
    "configs/finals/capd_proactive_stage11_v2_production_config_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_final_approval_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_result_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_verification_receipt_schema.json",
    "configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json",
    "configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json",
    "configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json",
    "configs/finals/capd_proactive_stage9_result_schema.json",
    "qmap/proactive_stage11_v2_production_guard.py",
    "qmap/proactive_stage11_v2_production_verifier.py",
    "scripts/verify_capd_proactive_stage11_v2_production.py",
)

MONITORING_FIXED = {
    "monitor_interval_seconds": 5, "hard_timeout_seconds": 1800,
    "termination_grace_seconds": 10, "attempt_count": 1,
    "automatic_retry_performed": False}


class VerificationError(ValueError):
  pass


def _require(condition: object, message: str) -> None:
  if not condition:
    raise VerificationError(message)


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], label: str) -> None:
  _require(isinstance(value, Mapping) and set(value) == set(expected),
           "{} field set mismatch.".format(label))


def _assert_finite(value: Any) -> None:
  if isinstance(value, Mapping):
    for item in value.values():
      _assert_finite(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      _assert_finite(item)
  elif isinstance(value, float):
    _require(math.isfinite(value), "Non-finite JSON value is forbidden.")


def canonical_json_bytes(value: Any) -> bytes:
  _assert_finite(value)
  return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
  return hashlib.sha256(raw).hexdigest()


def sha256_value(value: Any) -> str:
  return sha256_bytes(canonical_json_bytes(value))


def stage8_fingerprint_value(value: Any) -> str:
  """Independently reproduce Stage8's no-trailing-LF JSON fingerprint."""
  _assert_finite(value)
  raw = json.dumps(
      value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
      allow_nan=False).encode("utf-8")
  return sha256_bytes(raw)


def sha256_file(path: os.PathLike[str] | str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def _duplicate_object(pairs):
  result = {}
  for key, value in pairs:
    _require(key not in result, "Duplicate JSON key: {}".format(key))
    result[key] = value
  return result


def load_json_strict(path: os.PathLike[str] | str) -> Any:
  try:
    raw = Path(path).read_bytes()
    _require(not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM is forbidden.")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          VerificationError("Non-finite JSON: " + value)))
  except VerificationError:
    raise
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise VerificationError("Cannot load strict JSON: {}".format(exc)) from exc


def load_json_bytes_strict(raw: bytes, label: str) -> Any:
  try:
    _require(isinstance(raw, bytes) and not raw.startswith(b"\xef\xbb\xbf"),
             "{} must be strict UTF-8 without BOM.".format(label))
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_duplicate_object,
        parse_constant=lambda item: (_ for _ in ()).throw(
            VerificationError("Non-finite JSON: " + item)))
    _require(canonical_json_bytes(value) == raw,
             "{} is not canonical JSON.".format(label))
    return value
  except VerificationError:
    raise
  except (UnicodeError, json.JSONDecodeError) as exc:
    raise VerificationError(
        "Cannot load canonical {}: {}".format(label, exc)) from exc


def semantic_stage8_payload(result: Mapping[str, Any]) -> dict[str, Any]:
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


def _safe_stage8_job_root(stage8_root: Path, job_id: str) -> Path:
  _require(isinstance(job_id, str) and job_id and Path(job_id).name == job_id,
           "Invalid Stage8 job ID.")
  jobs_root = (stage8_root / "jobs").resolve()
  target = (jobs_root / job_id).resolve()
  _require(target.parent == jobs_root, "Stage8 job path escapes jobs root.")
  return target


def independent_stage8_source(stage8_root: os.PathLike[str] | str
                              ) -> dict[str, Any]:
  root = Path(stage8_root).resolve()
  _require(root.is_dir(), "Stage8 r5 root is missing.")
  state = load_json_strict(root / "run_state.json")
  verification = load_json_strict(root / "verification.json")
  authority = load_json_strict(root / "job_manifest.json")
  _require(state.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
           state.get("status") == "stage8_sync_replay_verified" and
           state.get("test_used_for_parameter_selection") is False and
           verification.get("status") == "stage8_sync_replay_verified",
           "Stage8 r5 state is not verified.")
  plans = authority.get("jobs")
  _require(authority.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
           isinstance(plans, list), "Stage8 authority manifest is malformed.")
  standard_plans = [row for row in plans if row.get("track") == "standard"]
  plan_by_id = {row.get("job_id"): row for row in standard_plans}
  _require(len(standard_plans) == len(plan_by_id) == 48,
           "Stage8 authority must contain 48 unique Standard jobs.")
  with (root / "artifacts" / "per_workload_raw.csv").open(
      "r", encoding="utf-8", newline="") as handle:
    selected = [row for row in csv.DictReader(handle)
                if row.get("track") == "standard"]
  csv_ids = [row.get("job_id") for row in selected]
  _require(len(csv_ids) == len(set(csv_ids)) == 48 and
           set(csv_ids) == set(plan_by_id),
           "Stage8 CSV/authority Standard job set mismatch.")
  records = []
  jobs = []
  for job_id in sorted(csv_ids):
    plan = plan_by_id[job_id]
    job_root = _safe_stage8_job_root(root, job_id)
    job_manifest_path = job_root / "job_manifest.json"
    result_path = job_root / "result.json"
    job_manifest = load_json_strict(job_manifest_path)
    result = load_json_strict(result_path)
    result_sha = sha256_file(result_path)
    semantic_sha = stage8_fingerprint_value(semantic_stage8_payload(result))
    identity = job_manifest.get("job_identity")
    _require(job_manifest.get("status") == "completed" and
             job_manifest.get("result_sha256") == result_sha and
             job_manifest.get("semantic_result_sha256") == semantic_sha and
             result.get("semantic_result_sha256") == semantic_sha and
             isinstance(identity, Mapping) and
             identity.get("plan_job") == plan and
             job_manifest.get("job_identity_sha256") ==
             stage8_fingerprint_value(identity),
             "Stage8 job SHA/semantic identity failed: {}".format(job_id))
    for field in (
        "job_id", "track", "workload", "policy", "seed", "D", "W_ref",
        "F_low", "F_target", "K", "b_max", "history_H", "alpha", "beta",
        "trace_sha256", "source_interval", "evaluation_interval",
        "initial_state_sha256", "cost_profile_sha256"):
      _require(result.get(field) == plan.get(field),
               "Stage8 result/plan mismatch: {}".format(field))
    _require(result.get("schema_version") ==
             "capd_proactive_stage8_job_result_v2_0" and
             result.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
             result.get("formal_test") is True and
             result.get("test_used_for_selection") is False and
             result.get("selector_status") == "disabled",
             "Stage8 result formal state is invalid.")
    metrics = result.get("metrics", {})
    job = {"job_id": job_id, "track": "standard",
           "workload": plan["workload"], "policy": plan["policy"],
           "seed": plan.get("seed")}
    for field in (
        "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
        "raw_access_count", "reactive_demotions", "proactive_demotions",
        "emergency_demotions"):
      job[field] = _non_negative_int(metrics.get(field), "metrics." + field)
    _require(job["total_demotions"] == job["reactive_demotions"] +
             job["proactive_demotions"] + job["emergency_demotions"],
             "Stage8 demotion counters are inconsistent.")
    records.append({
        "job_id": job_id, "track": "standard", "workload": plan["workload"],
        "policy": plan["policy"], "seed": plan.get("seed"),
        "job_manifest_path": job_manifest_path.relative_to(root).as_posix(),
        "job_manifest_sha256": sha256_file(job_manifest_path),
        "result_path": result_path.relative_to(root).as_posix(),
        "result_sha256": result_sha, "semantic_result_sha256": semantic_sha})
    jobs.append(job)
  validate_standard_jobs(jobs)
  sorted_ids = [row["job_id"] for row in records]
  manifest = {
      "schema_version": "capd_proactive_stage11_v2_standard_source_manifest_v1_0",
      "contract_id": CONTRACT_ID,
      "stage8_contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
      "records": records, "job_count": 48, "workload_count": 6,
      "sorted_job_ids_sha256": sha256_value(sorted_ids)}
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_stage8_input_receipt_v1_0",
      "contract_id": CONTRACT_ID, "stage": "stage8", "status": "verified",
      "authorized_external_input": True,
      "stage8_run_state_sha256": sha256_file(root / "run_state.json"),
      "stage8_verification_sha256": sha256_file(root / "verification.json"),
      "stage8_job_manifest_sha256": sha256_file(root / "job_manifest.json"),
      "standard_source_manifest_sha256": sha256_value(manifest),
      "sorted_job_ids_sha256": manifest["sorted_job_ids_sha256"],
      "job_count": 48, "workload_count": 6,
      "test_used_for_parameter_selection": False,
      "synthetic_test_only": False}
  return {"jobs": jobs, "manifest": manifest, "receipt": receipt}


def load_jobs_from_standard_manifest(stage8_root: os.PathLike[str] | str,
                                     manifest: Mapping[str, Any]
                                     ) -> list[dict[str, Any]]:
  _exact_keys(manifest, {
      "schema_version", "contract_id", "stage8_contract_id", "records",
      "job_count", "workload_count", "sorted_job_ids_sha256"},
      "Standard source manifest")
  _require(manifest["schema_version"] ==
           "capd_proactive_stage11_v2_standard_source_manifest_v1_0" and
           manifest["contract_id"] == CONTRACT_ID and
           manifest["stage8_contract_id"] == "CAPD-PROACTIVE-STAGE8-2.0" and
           manifest["job_count"] == 48 and manifest["workload_count"] == 6,
           "Standard source manifest identity mismatch.")
  records = manifest["records"]
  ids = [item.get("job_id") for item in records]
  _require(len(records) == len(set(ids)) == 48 and ids == sorted(ids) and
           manifest["sorted_job_ids_sha256"] == sha256_value(ids),
           "Standard job ID set mismatch.")
  root = Path(stage8_root).resolve()
  jobs_root = (root / "jobs").resolve()
  jobs = []
  for record in records:
    _exact_keys(record, {
        "job_id", "track", "workload", "policy", "seed",
        "job_manifest_path", "job_manifest_sha256", "result_path",
        "result_sha256", "semantic_result_sha256"}, "Standard job record")
    job_id = record["job_id"]
    _require(Path(job_id).name == job_id and record["track"] == "standard",
             "Invalid Standard job record.")
    job_manifest_path = (root / record["job_manifest_path"]).resolve()
    result_path = (root / record["result_path"]).resolve()
    _require(job_manifest_path.parent == jobs_root / job_id and
             result_path.parent == jobs_root / job_id,
             "Stage8 job path escapes sealed job root.")
    _require(sha256_file(job_manifest_path) == record["job_manifest_sha256"] and
             sha256_file(result_path) == record["result_sha256"],
             "Stage8 sealed job artifact SHA mismatch.")
    job_manifest = load_json_strict(job_manifest_path)
    result = load_json_strict(result_path)
    semantic_sha = stage8_fingerprint_value(semantic_stage8_payload(result))
    _require(job_manifest.get("status") == "completed" and
             job_manifest.get("result_sha256") == record["result_sha256"] and
             job_manifest.get("semantic_result_sha256") == semantic_sha and
             record["semantic_result_sha256"] == semantic_sha and
             result.get("semantic_result_sha256") == semantic_sha,
             "Stage8 semantic/job manifest binding mismatch.")
    metrics = result.get("metrics", {})
    job = {"job_id": job_id, "track": "standard",
           "workload": record["workload"], "policy": record["policy"],
           "seed": record["seed"]}
    _require(result.get("workload") == job["workload"] and
             result.get("policy") == job["policy"] and
             result.get("seed") == job["seed"] and result.get("b_max") == 2 and
             result.get("formal_test") is True and
             result.get("test_used_for_selection") is False,
             "Stage8 result provenance mismatch.")
    for field in ("dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                  "raw_access_count", "reactive_demotions",
                  "proactive_demotions", "emergency_demotions"):
      job[field] = _non_negative_int(metrics.get(field), field)
    jobs.append(job)
  return validate_standard_jobs(jobs)


def frozen_tree_snapshot(project_root: os.PathLike[str] | str) -> dict[str, Any]:
  root = Path(project_root).resolve()
  rows = []
  for root_id, relative in FROZEN_TREE_PATHS:
    path = (root / relative).resolve()
    _require(path.is_relative_to(root), "Frozen root escapes repository.")
    members = []
    if path.is_dir():
      for member in sorted(item for item in path.rglob("*") if item.is_file()):
        members.append({
            "path": member.relative_to(path).as_posix(),
            "length": member.stat().st_size, "sha256": sha256_file(member)})
    rows.append({"root_id": root_id, "repository_relative_root": relative,
                 "exists": path.is_dir(), "members": members})
  return {"schema_version":
          "capd_proactive_stage11_v2_frozen_tree_snapshot_v1_0",
          "contract_id": CONTRACT_ID, "roots": rows}


def source_snapshot(project_root: os.PathLike[str] | str,
                    paths: Sequence[str]) -> dict[str, Any]:
  root = Path(project_root).resolve()
  _require(tuple(paths) == tuple(sorted(paths)) and
           len(paths) == len(set(paths)),
           "Source whitelist must be sorted and unique.")
  members = []
  for relative in paths:
    pure = PurePosixPath(relative)
    _require(relative == pure.as_posix() and not pure.is_absolute() and
             ".." not in pure.parts, "Source path is not canonical.")
    path = (root / relative).resolve()
    _require(path.is_relative_to(root) and path.is_file(),
             "Source member is missing: {}".format(relative))
    members.append({"path": relative, "length": path.stat().st_size,
                    "sha256": sha256_file(path)})
  return {"members": members, "member_count": len(members),
          "members_sha256": sha256_value(members)}


def _local_imports(path: Path) -> set[str]:
  tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
  imports = set()
  for node in ast.walk(tree):
    names = []
    if isinstance(node, ast.Import):
      names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module:
      names = [node.module]
      if node.module in ("qmap", "scripts", "tests"):
        names.extend(node.module + "." + alias.name for alias in node.names)
    for name in names:
      if name.startswith(("qmap.", "scripts.", "tests.")):
        imports.add(name.replace(".", "/") + ".py")
  return imports


def validate_local_import_closure(project_root: os.PathLike[str] | str,
                                  paths: Sequence[str], *,
                                  forbidden: Iterable[str] = ()) -> None:
  root = Path(project_root).resolve()
  members = set(paths)
  imports = set()
  for relative in paths:
    if relative.endswith(".py"):
      imports.update(_local_imports(root / relative))
  local = {item for item in imports if (root / item).is_file()}
  _require(local <= members,
           "Source whitelist omits imports: {}".format(sorted(local - members)))
  _require(not (set(forbidden) & local),
           "Production source imports a historical Stage11 contract.")


def _source_manifest(project_root: os.PathLike[str] | str,
                     paths: Sequence[str], role: str,
                     expected_count: int) -> dict[str, Any]:
  snapshot = source_snapshot(project_root, paths)
  _require(snapshot["member_count"] == expected_count,
           "{} source whitelist count changed.".format(role))
  return {
      "schema_version": "capd_proactive_stage11_v2_production_source_manifest_v1_0",
      "contract_id": CONTRACT_ID, "role": role,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "members": snapshot["members"], "member_count": expected_count,
      "members_sha256": snapshot["members_sha256"],
      "local_import_closure_complete": True,
      "exclusions": ["docs", "tests", "fixtures", "outputs", "receipts",
                     "logs", "__pycache__", "runtime_status"]}


def generation_source_manifest_value(
    project_root: os.PathLike[str] | str) -> dict[str, Any]:
  value = _source_manifest(
      project_root, GENERATION_SOURCE_PATHS, "generation", 30)
  validate_local_import_closure(
      project_root, GENERATION_SOURCE_PATHS,
      forbidden={
          "qmap/proactive_stage11_v2.py", "qmap/proactive_stage11_v2_guard.py",
          "qmap/proactive_stage11_v2_verifier.py",
          "scripts/run_capd_proactive_stage11_v2.py",
          "scripts/verify_capd_proactive_stage11_v2.py"})
  return value


def validate_test_source_identity(project_root: os.PathLike[str] | str,
                                  identity: Mapping[str, Any]) -> None:
  expected_fields = {
      "schema_version", "contract_id", "audit_id",
      "approved_production_design_sha256", "approved_production_plan_sha256",
      "members", "members_sha256", "member_count",
      "test_source_pre_snapshot_sha256", "test_source_post_snapshot_sha256",
      "test_sources_unchanged"}
  _exact_keys(identity, expected_fields, "Test-source identity")
  current = source_snapshot(project_root, TEST_SOURCE_PATHS)
  _require(identity["schema_version"] ==
           "capd_proactive_stage11_v2_test_source_identity_v1_0" and
           identity["contract_id"] == CONTRACT_ID and
           identity["audit_id"] == AUDIT_ID and
           identity["approved_production_design_sha256"] ==
           APPROVED_DESIGN_SHA256 and
           identity["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
           identity["member_count"] == 29 and
           identity["members"] == current["members"] and
           identity["members_sha256"] == current["members_sha256"] and
           identity["test_source_pre_snapshot_sha256"] == sha256_value(current) and
           identity["test_source_post_snapshot_sha256"] == sha256_value(current) and
           identity["test_sources_unchanged"] is True,
           "Test-source identity differs from current exact bytes.")


def _input_receipt(stage: str, status: str, **fields: Any) -> dict[str, Any]:
  value = {
      "schema_version": "capd_proactive_stage11_v2_{}_input_receipt_v1_0".format(stage),
      "contract_id": CONTRACT_ID, "stage": stage, "status": status,
      "authorized_external_input": status == "verified",
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False, "synthetic_test_only": False}
  value.update(fields)
  return value


def independent_stage9_receipt(stage9_root: os.PathLike[str] | str,
                               schema_path: os.PathLike[str] | str
                               ) -> dict[str, Any]:
  root = Path(stage9_root).resolve()
  schema = load_json_strict(schema_path)
  required = schema.get("required_run_artifacts", [])
  _require(required and all((root / name).is_file() for name in required),
           "Stage9 required artifact is missing.")
  state = load_json_strict(root / "run_state.json")
  verification = load_json_strict(root / "verification.json")
  compatibility = load_json_strict(root / "stage8_compatibility_receipt.json")
  environment = load_json_strict(root / "environment.json")
  _require(state.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
           state.get("schema_version") == "capd_proactive_stage9_run_state_v2_0" and
           state.get("status") == "stage9_overhead_verified" and
           verification.get("status") == "stage9_overhead_verified" and
           environment.get("system") == "Linux" and
           environment.get("device") == "cpu" and
           isinstance(environment.get("linux_kernel"), str),
           "Stage9 verified Linux state is absent.")
  for key, expected in schema.get("verification_required", {}).items():
    _require(verification.get(key) == expected,
             "Stage9 verification field mismatch: {}".format(key))
  artifacts = [name for name in required
               if name not in ("verification.json", "run_state.json")]
  hashes = verification.get("artifact_sha256")
  _require(isinstance(hashes, Mapping) and set(hashes) == set(artifacts),
           "Stage9 artifact SHA set mismatch.")
  for name in artifacts:
    _require(sha256_file(root / name) == hashes[name],
             "Stage9 artifact SHA mismatch: {}".format(name))
  _require(compatibility.get("stage9_entry_gate") == "satisfied" and
           compatibility.get("stage8_contract_id") ==
           "CAPD-PROACTIVE-STAGE8-2.0" and
           compatibility.get("stage8_status") == "stage8_sync_replay_verified" and
           compatibility.get("job_results_verified") is True and
           compatibility.get("statistics_verified") is True and
           compatibility.get("stage8_run_state_verified") is True and
           compatibility.get("stage8_artifacts_read_only") is True and
           compatibility.get("test_used_for_parameter_selection") is False,
           "Stage9 Stage8 binding mismatch.")
  perf = load_json_strict(root / "perf" / "perf_parsed.json")
  _require(perf.get("counter_source") == schema.get("perf_counter_source") and
           perf.get("required_events_verified") is True and
           perf.get("cycles_verified") is True,
           "Stage9 perf evidence is incomplete.")
  for event in schema.get("perf_required_events", []):
    row = perf.get("events", {}).get(event, {})
    _require(row.get("status") == "ok" and
             isinstance(row.get("value"), (int, float)) and
             not isinstance(row.get("value"), bool) and row["value"] > 0,
             "Stage9 perf event is invalid.")
  derived = perf.get("derived", {})
  _require(all(isinstance(derived.get(field), (int, float)) and
               not isinstance(derived.get(field), bool) and derived[field] > 0
               for field in schema.get("perf_derived_fields", [])),
           "Stage9 derived perf evidence is invalid.")
  scope = load_json_strict(root / "perf" / "perf_scope_counts.json")
  _require(all(field in scope for field in
               schema.get("perf_scope_required_fields", [])) and
           isinstance(scope.get("measured_rounds"), int) and
           scope["measured_rounds"] > 0 and
           isinstance(scope.get("measured_demoted_pages"), int) and
           scope["measured_demoted_pages"] > 0,
           "Stage9 perf scope evidence is invalid.")
  memory = load_json_strict(root / "memory_breakdown.json")
  rss = memory.get("rss", {})
  _require(all(field in memory for field in schema.get("memory_required_fields", [])) and
           all(field in rss for field in
               schema.get("memory_rss_required_fields", [])) and
           isinstance(rss.get("process_baseline_rss_bytes"), int) and
           isinstance(rss.get("total_peak_rss_bytes"), int) and
           rss["total_peak_rss_bytes"] >= rss["process_baseline_rss_bytes"] and
           rss.get("stage9_incremental_peak_rss_bytes") ==
           rss.get("total_peak_rss_bytes") - rss.get("process_baseline_rss_bytes"),
           "Stage9 RSS evidence is invalid.")
  with (root / "raw_latency_samples.csv").open(
      "r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)
    fields = set(reader.fieldnames or ())
  _require(rows and set(schema.get("raw_latency_required_fields", [])) <= fields,
           "Stage9 raw latency evidence is incomplete.")
  return _input_receipt(
      "stage9", "verified", run_state_sha256=sha256_file(root / "run_state.json"),
      verification_sha256=sha256_file(root / "verification.json"),
      stage8_compatibility_receipt_sha256=sha256_file(
          root / "stage8_compatibility_receipt.json"),
      artifact_verified_count=len(artifacts),
      test_used_for_parameter_selection=False)


def _relative_files(root: Path) -> list[tuple[str, Path]]:
  return sorted((path.relative_to(root).as_posix(), path)
                for path in root.rglob("*") if path.is_file())


def _legacy_stage10_envelope(base: Path, phase: str,
                             expected_artifacts: set[str]) -> dict[str, str]:
  names = {name for name, _ in _relative_files(base)}
  _require(names == expected_artifacts, "Stage10 artifact set mismatch.")
  manifest = load_json_strict(base / "manifest.json")
  payloads = names - {"manifest.json", "SHA256SUMS"}
  if phase == "generation":
    _require(set(manifest) == {"schema_version", "files"} and
             manifest.get("schema_version") ==
             "capd_proactive_stage10_manifest_v2_1",
             "Stage10 generation manifest identity mismatch.")
  else:
    _require(set(manifest) == {"schema_version", "phase", "files"} and
             manifest.get("schema_version") ==
             "capd_proactive_stage10_release_manifest_v1_0" and
             manifest.get("phase") == phase,
             "Stage10 release manifest identity mismatch.")
  _require(isinstance(manifest.get("files"), Mapping) and
           set(manifest["files"]) == payloads,
           "Stage10 manifest member set mismatch.")
  for name, expected in manifest["files"].items():
    _require(re.fullmatch(r"[0-9a-f]{64}", str(expected)) and
             sha256_file(base / name) == expected,
             "Stage10 manifest SHA mismatch.")
  rows = []
  with (base / "SHA256SUMS").open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        parts = line.rstrip("\n").split("  ", 1)
        _require(len(parts) == 2, "Stage10 checksum line is malformed.")
        rows.append((parts[0], parts[1]))
  _require(len(rows) == len({name for _, name in rows}) and
           {name for _, name in rows} == names - {"SHA256SUMS"},
           "Stage10 checksum member set mismatch.")
  for expected, name in rows:
    _require(sha256_file(base / name) == expected,
             "Stage10 checksum mismatch.")
  return {"manifest_sha256": sha256_file(base / "manifest.json"),
          "checksums_sha256": sha256_file(base / "SHA256SUMS")}


def _current_commit(project_root: Path) -> str | None:
  try:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root, text=True,
        stderr=subprocess.DEVNULL).strip()
  except (OSError, subprocess.SubprocessError):
    return None


def independent_stage10_receipt(stage10_root: os.PathLike[str] | str,
                                anchors: Mapping[str, str],
                                project_root: os.PathLike[str] | str
                                ) -> dict[str, Any]:
  base = Path(stage10_root).resolve()
  generation_artifacts = {
      "config.json", "event_model.md", "execution_environment.json",
      "generation_freeze_receipt.json", "generation_source_manifest.json",
      "generation_test_evidence.json", "generation_test_log.txt", "parameters.md",
      "README.md", "report.md", "run_identity.json", "run_state.json",
      "scenario_matrix.json", "simulation_results.jsonl", "stage9_input_receipt.json",
      "timing_provenance.json", "verification.json", "manifest.json", "SHA256SUMS"}
  readiness_artifacts = {
      "release_readiness_test_log.txt", "release_test_source_snapshot.py",
      "protocol_pending_snapshot.md", "status_pending_snapshot.md",
      "release_readiness_test_evidence.json", "stage11_negative_audit_log.txt",
      "stage11_negative_audit_source_snapshot.json",
      "stage11_negative_audit_result.json", "stage11_negative_audit_evidence.json",
      "release_readiness_receipt.json", "manifest.json", "SHA256SUMS"}
  final_artifacts = {
      "final_status_test_log.txt", "release_test_source_snapshot.py",
      "protocol_final_snapshot.md", "status_final_snapshot.md",
      "final_status_test_evidence.json", "final_status_evidence_receipt.json",
      "manifest.json", "SHA256SUMS"}
  generation = _legacy_stage10_envelope(base, "generation", generation_artifacts)
  identity = load_json_strict(base / "run_identity.json")
  state = load_json_strict(base / "run_state.json")
  check = load_json_strict(base / "verification.json")
  _require(identity.get("contract_id") == "CAPD-PROACTIVE-STAGE10-2.0" and
           identity.get("run_id") == "stage10-async-simulator-v2-r2" and
           identity.get("evidence_mode") == "deterministic_async_simulation" and
           state.get("status") == "stage10_async_simulation_verified" and
           state.get("artifacts_independently_verified") is True and
           state.get("simulation_executed") is True and
           state.get("stage9_input_gate_passed") is True and
           state.get("real_system_async_performance_verified") is False and
           check.get("status") == "stage10_async_simulation_verified" and
           check.get("artifacts_independently_recomputed") is True and
           check.get("current_generation_sources_recomputed") is True and
           check.get("generation_tests_verified") is True and
           check.get("stage9_input_gate") == "satisfied" and
           check.get("result_count") == 60,
           "Stage10 sealed generation state mismatch.")
  for flag in (
      "real_nvm_measurement_verified", "kernel_behavior_verified",
      "real_concurrency_verified", "real_foreground_end_to_end_latency_verified",
      "real_system_async_performance_verified"):
    _require(check.get(flag) is False, "Stage10 real-system boundary changed.")
  source = load_json_strict(base / "generation_source_manifest.json")
  entries = source.get("entries")
  _require(source.get("schema_version") ==
           "capd_proactive_stage10_generation_source_manifest_v1_0" and
           source.get("source_set_id") ==
           "stage10-v2-r2-generation-core-v1" and
           isinstance(entries, list) and len(entries) == 11,
           "Stage10 generation source set is incomplete.")
  source_match = all(
      (Path(project_root) / item["path"]).is_file() and
      sha256_file(Path(project_root) / item["path"]) == item["sha256"]
      for item in entries)
  freeze = base / "generation_freeze_receipt.json"
  _require(sha256_file(freeze) == anchors.get("generation_freeze_receipt_sha256"),
           "Stage10 freeze external SHA mismatch.")
  release = base.parent / "release_receipts" / "stage10-async-simulator-v2-r2"
  readiness_root = release / "readiness"
  final_root = release / "final-status"
  readiness_env = _legacy_stage10_envelope(
      readiness_root, "readiness", readiness_artifacts)
  final_env = _legacy_stage10_envelope(
      final_root, "final_status", final_artifacts)
  readiness_path = readiness_root / "release_readiness_receipt.json"
  final_path = final_root / "final_status_evidence_receipt.json"
  _require(sha256_file(readiness_path) == anchors.get("readiness_receipt_sha256") and
           sha256_file(final_path) == anchors.get("final_status_receipt_sha256"),
           "Stage10 release external SHA mismatch.")
  readiness = load_json_strict(readiness_path)
  final = load_json_strict(final_path)
  _require(readiness.get("release_status") ==
           "stage10_release_readiness_verified" and
           readiness.get("stage11_positive_migration_authorized") is False and
           readiness.get("real_system_async_performance_verified") is False and
           readiness.get("synthetic_test_only") is False and
           final.get("status") == "stage10_final_status_evidence_verified" and
           final.get("real_system_async_performance_verified") is False and
           final.get("synthetic_test_only") is False and
           final.get("readiness_manifest_sha256") ==
           readiness_env["manifest_sha256"] and
           final.get("readiness_checksums_sha256") ==
           readiness_env["checksums_sha256"],
           "Stage10 sealed dual-verifier attestation mismatch.")
  return _input_receipt(
      "stage10", "verified", stage10_contract_id="CAPD-PROACTIVE-STAGE10-2.0",
      run_id="stage10-async-simulator-v2-r2", artifact_integrity="verified",
      sealed_dual_verifier_attestation="verified",
      generation_source_set_match=source_match,
      repository_revision_match=(
          _current_commit(Path(project_root)) == identity.get("git", {}).get("commit")),
      current_live_replay_compatibility="NOT_VERIFIABLE",
      generation_manifest_sha256=generation["manifest_sha256"],
      readiness_manifest_sha256=readiness_env["manifest_sha256"],
      final_status_manifest_sha256=final_env["manifest_sha256"],
      test_used_for_parameter_selection=False)


def source_manifest_value(project_root: os.PathLike[str] | str) -> dict[str, Any]:
  value = _source_manifest(
      project_root, VERIFIER_SOURCE_PATHS, "verifier", 32)
  validate_local_import_closure(
      project_root, VERIFIER_SOURCE_PATHS,
      forbidden={
          "qmap/proactive_stage11_v2.py", "qmap/proactive_stage11_v2_guard.py",
          "qmap/proactive_stage11_v2_verifier.py",
          "scripts/run_capd_proactive_stage11_v2.py",
          "scripts/verify_capd_proactive_stage11_v2.py",
          "qmap/proactive_stage11_v2_production.py", "qmap/proactive_cost.py",
          "scripts/run_capd_proactive_stage11_v2_production.py"})
  return value


def validate_source_manifest(project_root: os.PathLike[str] | str,
                             sealed: Mapping[str, Any],
                             generation_identity: Mapping[str, Any],
                             authorization: Mapping[str, Any]) -> Mapping[str, Any]:
  rebuilt = source_manifest_value(project_root)
  _require(sealed == rebuilt, "Verifier source manifest differs from current bytes.")
  manifest_sha = sha256_value(sealed)
  for source in (generation_identity, authorization):
    _require(source.get("verifier_source_manifest_sha256") == manifest_sha and
             source.get("verifier_source_members_sha256") ==
             sealed["members_sha256"],
             "Verifier source identity is not bound exactly.")
  return sealed


def validate_input_audit_receipt(receipt: Mapping[str, Any]) -> None:
  required = {
      "schema_version", "contract_id", "audit_id",
      "approved_production_design_sha256", "approved_production_plan_sha256",
      "production_config_sha256", "production_result_schema_sha256",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "generation_source_member_count", "verifier_source_manifest_sha256",
      "verifier_source_members_sha256", "verifier_source_member_count",
      "test_source_identity_sha256", "test_source_pre_snapshot_sha256",
      "test_source_post_snapshot_sha256", "test_sources_unchanged",
      "audit_commands_sha256", "synthetic_allowlist_log_sha256",
      "production_enablement_tests_log_sha256", "legacy_semantic_tests_log_sha256",
      "real_upstream_audit_stdout_sha256", "synthetic_test_count",
      "production_enablement_test_count", "legacy_semantic_test_count",
      "stage8_input_verified", "stage9_input_authorized",
      "stage10_input_authorized", "stage8_input_receipt_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256",
      "standard_source_manifest_sha256", "sorted_job_ids_sha256",
      "standard_job_count", "standard_workload_count",
      "frozen_tree_before_sha256", "frozen_tree_after_sha256",
      "frozen_tree_comparison_sha256", "frozen_trees_unchanged",
      "generation_source_set_match", "repository_revision_match",
      "sealed_dual_verifier_attestation", "current_live_replay_compatibility",
      "input_audit_verified", "stage11_execution_authorized",
      "stage11_formally_verified", "test_used_for_parameter_selection",
      "synthetic_test_only"}
  _exact_keys(receipt, required, "Input-audit receipt")
  _require(receipt["schema_version"] ==
           "capd_proactive_stage11_v2_input_audit_receipt_v1_0" and
           receipt["contract_id"] == CONTRACT_ID and
           receipt["audit_id"] == AUDIT_ID and
           receipt["approved_production_design_sha256"] ==
           APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256,
           "Input-audit receipt identity mismatch.")
  _require(receipt["generation_source_member_count"] == 30 and
           receipt["verifier_source_member_count"] == 32 and
           receipt["synthetic_test_count"] == 41 and
           receipt["production_enablement_test_count"] == 56 and
           receipt["legacy_semantic_test_count"] == 6 and
           receipt["standard_job_count"] == 48 and
           receipt["standard_workload_count"] == 6,
           "Input-audit frozen counts changed.")
  required_true = (
      "test_sources_unchanged", "stage8_input_verified",
      "stage9_input_authorized", "stage10_input_authorized",
      "frozen_trees_unchanged", "generation_source_set_match",
      "input_audit_verified")
  _require(all(receipt[field] is True for field in required_true) and
           isinstance(receipt["repository_revision_match"], bool) and
           receipt["sealed_dual_verifier_attestation"] == "verified" and
           receipt["current_live_replay_compatibility"] == "NOT_VERIFIABLE" and
           receipt["stage11_execution_authorized"] is False and
           receipt["stage11_formally_verified"] is False and
           receipt["test_used_for_parameter_selection"] is False and
           receipt["synthetic_test_only"] is False,
           "Input-audit receipt semantics are invalid.")


def compare_rebuilt_upstream_objects(sealed: Mapping[str, bytes],
                                     rebuilt: Mapping[str, bytes]) -> None:
  expected = {
      "stage8_standard_input_receipt.json", "stage9_input_receipt.json",
      "stage10_input_receipt.json", "standard_source_manifest.json"}
  _require(set(sealed) == expected and set(rebuilt) == expected,
           "Canonical upstream object set mismatch.")
  for name in sorted(expected):
    load_json_bytes_strict(sealed[name], name)
    load_json_bytes_strict(rebuilt[name], "rebuilt " + name)
    _require(sealed[name] == rebuilt[name],
             "Independent upstream rebuild differs: {}".format(name))


def code_version(project_root: os.PathLike[str] | str) -> dict[str, Any]:
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


def validate_source_identity(
    *, project_root: os.PathLike[str] | str, identity: Mapping[str, Any],
    receipt: Mapping[str, Any], config: Mapping[str, Any],
    generation_manifest: Mapping[str, Any],
    verifier_manifest: Mapping[str, Any],
    test_identity: Mapping[str, Any]) -> None:
  expected_fields = {
      "schema_version", "contract_id", "approved_production_design_sha256",
      "approved_production_plan_sha256", "production_config_sha256",
      "production_result_schema_sha256", "generation_source_manifest_path",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "generation_source_member_count", "verifier_source_manifest_path",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "verifier_source_member_count", "source_pre_snapshot_sha256",
      "source_post_snapshot_sha256", "source_unchanged", "code_version"}
  _exact_keys(identity, expected_fields, "Source identity")
  root = Path(project_root).resolve()
  config_path = root / "configs/finals/capd_proactive_stage11_v2_production.json"
  result_schema_path = (
      root / "configs/finals/capd_proactive_stage11_v2_production_result_schema.json")
  generation_relative = config["source_manifests"]["generation"]
  verifier_relative = config["source_manifests"]["verifier"]
  generation_path = root / generation_relative
  verifier_path = root / verifier_relative
  _require(
      identity["schema_version"] ==
      "capd_proactive_stage11_v2_source_identity_v1_0" and
      identity["contract_id"] == CONTRACT_ID and
      identity["approved_production_design_sha256"] ==
      APPROVED_DESIGN_SHA256 and
      identity["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
      identity["production_config_sha256"] == sha256_file(config_path) ==
      receipt["production_config_sha256"] and
      identity["production_result_schema_sha256"] ==
      sha256_file(result_schema_path) ==
      receipt["production_result_schema_sha256"] and
      identity["generation_source_manifest_path"] == generation_relative and
      identity["generation_source_manifest_sha256"] ==
      sha256_file(generation_path) ==
      receipt["generation_source_manifest_sha256"] and
      identity["generation_source_members_sha256"] ==
      generation_manifest["members_sha256"] ==
      receipt["generation_source_members_sha256"] and
      identity["generation_source_member_count"] ==
      generation_manifest["member_count"] ==
      receipt["generation_source_member_count"] == 30 and
      identity["verifier_source_manifest_path"] == verifier_relative and
      identity["verifier_source_manifest_sha256"] ==
      sha256_file(verifier_path) == receipt["verifier_source_manifest_sha256"] and
      identity["verifier_source_members_sha256"] ==
      verifier_manifest["members_sha256"] ==
      receipt["verifier_source_members_sha256"] and
      identity["verifier_source_member_count"] ==
      verifier_manifest["member_count"] ==
      receipt["verifier_source_member_count"] == 32 and
      identity["source_pre_snapshot_sha256"] ==
      test_identity["test_source_pre_snapshot_sha256"] ==
      receipt["test_source_pre_snapshot_sha256"] and
      identity["source_post_snapshot_sha256"] ==
      test_identity["test_source_post_snapshot_sha256"] ==
      receipt["test_source_post_snapshot_sha256"] and
      identity["source_unchanged"] is True and
      identity["code_version"] == code_version(root),
      "Input-audit source identity binding mismatch.")


def verify_input_audit_package(
    *, project_root: os.PathLike[str] | str, package: Mapping[str, bytes],
    config: Mapping[str, Any]) -> Mapping[str, Any]:
  verify_package(package, phase="input_audit", payload_names=INPUT_AUDIT_PAYLOADS)
  root = Path(project_root).resolve()
  values = {}
  for name in INPUT_AUDIT_PAYLOADS:
    if name.endswith(".json"):
      values[name] = load_json_bytes_strict(package[name], name)
  receipt = values["input_audit_receipt.json"]
  validate_input_audit_receipt(receipt)
  _require(config.get("contract_id") == CONTRACT_ID and
           config.get("production_revision") == PRODUCTION_REVISION and
           config.get("run_id") == RUN_ID and
           config.get("input_audit") == {
               "audit_id": AUDIT_ID,
               "package_root":
                   "outputs/capd_proactive_stage11_v2/input_audits/" + AUDIT_ID,
               "receipt_schema":
                   "configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json"} and
           config.get("approved_production_design", {}).get("sha256") ==
           APPROVED_DESIGN_SHA256 and
           config.get("approved_production_plan", {}).get("sha256") ==
           APPROVED_PLAN_SHA256,
           "Production config identity mismatch.")
  config_path = root / "configs/finals/capd_proactive_stage11_v2_production.json"
  result_schema_path = (
      root / "configs/finals/capd_proactive_stage11_v2_production_result_schema.json")
  _require(receipt["production_config_sha256"] == sha256_file(config_path) and
           receipt["production_result_schema_sha256"] ==
           sha256_file(result_schema_path),
           "Input-audit config/schema binding mismatch.")

  generation_path = root / config["source_manifests"]["generation"]
  verifier_path = root / config["source_manifests"]["verifier"]
  generation_sealed = load_json_strict(generation_path)
  verifier_sealed = load_json_strict(verifier_path)
  generation_rebuilt = generation_source_manifest_value(root)
  verifier_rebuilt = source_manifest_value(root)
  _require(generation_sealed == generation_rebuilt and
           verifier_sealed == verifier_rebuilt,
           "Production source manifests differ from current exact closures.")
  _require(receipt["generation_source_manifest_sha256"] ==
           sha256_file(generation_path) and
           receipt["generation_source_members_sha256"] ==
           generation_rebuilt["members_sha256"] and
           receipt["verifier_source_manifest_sha256"] ==
           sha256_file(verifier_path) and
           receipt["verifier_source_members_sha256"] ==
           verifier_rebuilt["members_sha256"],
           "Input-audit source manifest binding mismatch.")

  test_identity = values["test_source_identity.json"]
  validate_test_source_identity(root, test_identity)
  _require(receipt["test_source_identity_sha256"] == sha256_value(test_identity) and
           receipt["test_source_pre_snapshot_sha256"] ==
           test_identity["test_source_pre_snapshot_sha256"] and
           receipt["test_source_post_snapshot_sha256"] ==
           test_identity["test_source_post_snapshot_sha256"],
           "Input-audit test-source binding mismatch.")
  validate_source_identity(
      project_root=root, identity=values["source_identity.json"],
      receipt=receipt, config=config, generation_manifest=generation_rebuilt,
      verifier_manifest=verifier_rebuilt, test_identity=test_identity)

  stage8 = independent_stage8_source(root / config["upstream"]["stage8_root"])
  stage9 = independent_stage9_receipt(
      root / config["upstream"]["stage9_root"],
      root / "configs/finals/capd_proactive_stage9_result_schema.json")
  stage10 = independent_stage10_receipt(
      root / config["upstream"]["stage10_root"],
      config["stage10_external_anchors"], root)
  rebuilt = {
      "stage8_standard_input_receipt.json": canonical_json_bytes(stage8["receipt"]),
      "stage9_input_receipt.json": canonical_json_bytes(stage9),
      "stage10_input_receipt.json": canonical_json_bytes(stage10),
      "standard_source_manifest.json": canonical_json_bytes(stage8["manifest"])}
  sealed = {name: package[name] for name in rebuilt}
  compare_rebuilt_upstream_objects(sealed, rebuilt)
  for name, field in (
      ("stage8_standard_input_receipt.json", "stage8_input_receipt_sha256"),
      ("stage9_input_receipt.json", "stage9_input_receipt_sha256"),
      ("stage10_input_receipt.json", "stage10_input_receipt_sha256"),
      ("standard_source_manifest.json", "standard_source_manifest_sha256")):
    _require(receipt[field] == sha256_bytes(package[name]),
             "Input-audit canonical object SHA mismatch: {}".format(name))
  _require(receipt["sorted_job_ids_sha256"] ==
           stage8["manifest"]["sorted_job_ids_sha256"],
           "Input-audit Standard job identity mismatch.")

  stdout = values["real_upstream_audit_stdout.json"]
  required_stdout = {
      "real_upstream_audit": "COMPLETED", "stage8_input_verified": True,
      "stage9_input_authorized": True, "stage10_input_authorized": True,
      "generation_source_manifest_verified": True,
      "verifier_source_manifest_verified": True,
      "generation_source_set_match": True,
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False}
  _require(set(stdout) == set(required_stdout) | {"repository_revision_match"} and
           all(stdout[key] == value for key, value in required_stdout.items()) and
           stdout["repository_revision_match"] is
           stage10["repository_revision_match"] and
           receipt["repository_revision_match"] is
           stage10["repository_revision_match"],
           "Input-audit Stage10 diagnostic classification mismatch.")

  before = values["frozen_tree_before.json"]
  after = values["frozen_tree_after.json"]
  comparison = values["frozen_tree_comparison.json"]
  expected_comparison = compare_continuity(
      before, [("audit_before_vs_after", after)])
  _require(expected_comparison == comparison and comparison["identical"] is True,
           "Input-audit frozen-tree comparison mismatch.")
  current = frozen_tree_snapshot(root)
  compare_continuity(after, [("audit_after_vs_independent_verification", current)])
  _require(receipt["frozen_tree_before_sha256"] == sha256_value(before) and
           receipt["frozen_tree_after_sha256"] == sha256_value(after) and
           receipt["frozen_tree_comparison_sha256"] == sha256_value(comparison),
           "Input-audit frozen-tree SHA binding mismatch.")

  commands = values["audit_commands.json"]
  _require(receipt["audit_commands_sha256"] == sha256_value(commands) and
           receipt["synthetic_allowlist_log_sha256"] ==
           sha256_bytes(package["synthetic_allowlist.log"]) and
           receipt["production_enablement_tests_log_sha256"] ==
           sha256_bytes(package["production_enablement_tests.log"]) and
           receipt["legacy_semantic_tests_log_sha256"] ==
           sha256_bytes(package["legacy_semantic_tests.log"]) and
           receipt["real_upstream_audit_stdout_sha256"] == sha256_value(stdout),
           "Input-audit command/log SHA binding mismatch.")
  records = commands.get("commands")
  expected_commands = {
      "synthetic_allowlist": 41, "production_enablement": 56,
      "legacy_semantic": 6}
  _require(isinstance(records, list) and len(records) == 3 and
           {row.get("command_id"): row.get("expected_test_count")
            for row in records} == expected_commands and
           all(row.get("exit_code") == 0 and row.get("timed_out") is False and
               row.get("attempt_count") == 1 and
               row.get("automatic_retry_performed") is False
               for row in records),
           "Input-audit command identity/status mismatch.")
  return receipt


def _non_negative_int(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
           "{} must be a non-negative integer.".format(field))
  return value


def validate_standard_jobs(jobs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
  _require(len(jobs) == 48, "Independent verifier requires exactly 48 jobs.")
  ids = [job.get("job_id") for job in jobs]
  _require(len(set(ids)) == 48 and all(isinstance(item, str) and item for item in ids),
           "Independent verifier found duplicate or invalid job IDs.")
  _require(all(job.get("track") == "standard" for job in jobs),
           "Independent verifier rejects Pressure jobs.")
  _require(Counter(job.get("workload") for job in jobs) ==
           Counter({name: 8 for name in STANDARD_WORKLOADS}),
           "Independent verifier workload multiset mismatch.")
  for workload in STANDARD_WORKLOADS:
    _require(Counter((job.get("policy"), job.get("seed")) for job in jobs
                     if job.get("workload") == workload) == Counter(STANDARD_MEMBERS),
             "Independent verifier policy/seed multiset mismatch.")
  return sorted(jobs, key=lambda item: item["job_id"])


def independent_cost_rows(jobs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
  rows = []
  for job in validate_standard_jobs(jobs):
    counts = {field: _non_negative_int(job.get(field), field) for field in (
        "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
        "raw_access_count", "reactive_demotions", "proactive_demotions",
        "emergency_demotions")}
    _require(counts["total_demotions"] == counts["reactive_demotions"] +
             counts["proactive_demotions"] + counts["emergency_demotions"],
             "Independent verifier demotion breakdown mismatch.")
    for profile in PROFILE_NAMES:
      weights = PROFILE_WEIGHTS[profile]
      cost = (counts["dram_hits"] * weights["dram_hit"] +
              counts["nvm_reads"] * weights["nvm_read"] +
              counts["nvm_writes"] * weights["nvm_write"] +
              counts["total_demotions"] * weights["demotion"])
      rows.append({
          "row_id": "{}::{}".format(job["job_id"], profile), "run_id": RUN_ID,
          "source_job_id": job["job_id"], "track": "standard",
          "workload": job["workload"], "policy": job["policy"],
          "seed": job["seed"], "cost_profile": profile,
          "cost_profile_weights": copy.deepcopy(weights), **counts,
          "weighted_cost": cost,
          "weighted_cost_per_access": (
              cost / counts["raw_access_count"]
              if counts["raw_access_count"] else None),
          "evidence_mode": "offline_raw_counter_recompute",
          "evidence_status": "candidate-ready"})
  return rows


def verify_result_rows(generation_rows: Sequence[Mapping[str, Any]],
                       jobs: Sequence[Mapping[str, Any]]) -> None:
  rebuilt = independent_cost_rows(jobs)
  _require(list(generation_rows) == rebuilt,
           "Independent 192-row recomputation differs from generation bytes.")
  pairs = [(row["source_job_id"], row["cost_profile"]) for row in rebuilt]
  _require(len(rebuilt) == len(set(pairs)) == 192,
           "Independent result is not the exact Cartesian product.")


CSV_FIELDS = (
    "row_id", "run_id", "source_job_id", "track", "workload", "policy",
    "seed", "cost_profile", "dram_hit_weight", "nvm_read_weight",
    "nvm_write_weight", "demotion_weight", "dram_hits", "nvm_reads",
    "nvm_writes", "total_demotions", "raw_access_count",
    "reactive_demotions", "proactive_demotions", "emergency_demotions",
    "weighted_cost", "weighted_cost_per_access", "evidence_mode",
    "evidence_status")


def expected_csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
  stream = io.StringIO(newline="")
  writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
  writer.writeheader()
  for row in rows:
    flat = {field: row.get(field) for field in CSV_FIELDS}
    for key, value in row["cost_profile_weights"].items():
      flat[key + "_weight"] = value
    flat["seed"] = "N/A" if row["seed"] is None else row["seed"]
    flat["weighted_cost_per_access"] = (
        "N/A" if row["weighted_cost_per_access"] is None
        else row["weighted_cost_per_access"])
    writer.writerow(flat)
  return stream.getvalue().encode("utf-8")


def verify_csv(rows: Sequence[Mapping[str, Any]], raw: bytes) -> None:
  _require(raw == expected_csv_bytes(rows),
           "CSV bytes do not independently match JSON rows/null semantics.")


def compare_continuity(sealed: Mapping[str, Any],
                       observations: Sequence[tuple[str, Mapping[str, Any]]]
                       ) -> dict[str, Any]:
  _require(1 <= len(observations) <= 2, "Invalid continuity observation count.")
  baseline_roots = {item["root_id"]: item for item in sealed.get("roots", [])}
  _require(len(baseline_roots) == 5, "Sealed continuity baseline is incomplete.")
  comparisons = []
  identical = True
  for identity, observed in observations:
    observed_roots = {item["root_id"]: item for item in observed.get("roots", [])}
    _require(set(observed_roots) == set(baseline_roots),
             "Continuity root set differs.")
    same = observed == sealed
    per_root = [{
        "root_id": root_id,
        "baseline_record_count": len(baseline_roots[root_id]["members"]),
        "observed_record_count": len(observed_roots[root_id]["members"]),
        "identical": baseline_roots[root_id] == observed_roots[root_id]}
                for root_id in sorted(baseline_roots)]
    comparisons.append({
        "comparison_id": identity,
        "baseline_snapshot_sha256": sha256_value(sealed),
        "observed_snapshot_sha256": sha256_value(observed),
        "per_root_comparison": per_root, "identical": same})
    identical = identical and same
  _require(identical, "Verification continuity changed.")
  return {"schema_version":
          "capd_proactive_stage11_v2_upstream_continuity_comparison_v1_0",
          "contract_id": CONTRACT_ID, "comparisons": comparisons,
          "identical": True}


def validate_monitoring(value: Mapping[str, Any]) -> None:
  expected = set(MONITORING_FIXED) | {
      "timed_out", "exit_code", "process_alive_sample_count",
      "wall_clock_start", "wall_clock_end", "wall_clock_duration_seconds",
      "worker_pid"}
  _exact_keys(value, expected, "Verification monitoring")
  _require(all(value[key] == expected_value
               for key, expected_value in MONITORING_FIXED.items()) and
           value["process_alive_sample_count"] >= 1,
           "Verification monitoring contract changed.")


def deterministic_result_view(value: Mapping[str, Any]) -> dict[str, Any]:
  result = copy.deepcopy(dict(value))
  result.pop("monitoring", None)
  return result


def _manifest(phase: str, payloads: Mapping[str, bytes]) -> dict[str, Any]:
  _require("manifest.json" not in payloads and "SHA256SUMS" not in payloads,
           "Recursive package hash is forbidden.")
  members = [{"path": path, "length": len(payloads[path]),
              "sha256": sha256_bytes(payloads[path])} for path in sorted(payloads)]
  return {"schema_version":
          "capd_proactive_stage11_v2_production_package_manifest_v1_0",
          "contract_id": CONTRACT_ID, "phase": phase, "members": members,
          "member_count": len(members), "members_sha256": sha256_value(members)}


def package_bytes(phase: str, payloads: Mapping[str, bytes]) -> dict[str, bytes]:
  manifest_raw = canonical_json_bytes(_manifest(phase, payloads))
  entries = dict(payloads)
  entries["manifest.json"] = manifest_raw
  checksums = ("\n".join("{}  {}".format(sha256_bytes(entries[name]), name)
                          for name in sorted(entries)) + "\n").encode("ascii")
  entries["SHA256SUMS"] = checksums
  return entries


def verify_package(package: Mapping[str, bytes], *, phase: str,
                   payload_names: Iterable[str]) -> None:
  names = set(payload_names)
  _require(set(package) == names | {"manifest.json", "SHA256SUMS"},
           "Release package exact member set mismatch.")
  expected = package_bytes(phase, {name: package[name] for name in names})
  _require(dict(package) == expected, "Release package hashes mismatch.")


def validate_execution_authorization_receipt(
    project_root: os.PathLike[str] | str, receipt: Mapping[str, Any],
    config: Mapping[str, Any], input_receipt: Mapping[str, Any],
    input_hashes: Mapping[str, str]) -> None:
  required = {
      "schema_version", "contract_id", "production_revision", "run_id",
      "approved_production_design_sha256", "approved_production_plan_sha256",
      "production_config_sha256", "production_result_schema_sha256",
      "production_run_identity_schema_sha256", "production_run_state_schema_sha256",
      "release_manifest_schema_sha256", "generation_source_manifest_sha256",
      "generation_source_members_sha256", "generation_source_member_count",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "verifier_source_member_count", "test_source_identity_sha256",
      "test_source_pre_snapshot_sha256", "test_source_post_snapshot_sha256",
      "test_sources_unchanged", "input_audit_receipt_sha256",
      "input_audit_manifest_sha256", "input_audit_checksums_sha256",
      "sealed_frozen_tree_after_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256", "standard_job_count", "standard_workload_count",
      "stage8_input_receipt_sha256", "stage9_input_receipt_sha256",
      "stage10_input_receipt_sha256", "stage10_generation_freeze_receipt_sha256",
      "stage10_readiness_receipt_sha256", "stage10_final_status_receipt_sha256",
      "frozen_cost_profiles_sha256", "main_b_max", "authorized_scope",
      "expected_result_rows", "blocked_lanes", "stage11_execution_authorized",
      "synthetic_test_only", "test_used_for_parameter_selection",
      "future_output_hashes_absent", "approval_authority", "approval_reference"}
  _exact_keys(receipt, required, "Execution authorization receipt")
  root = Path(project_root).resolve()
  schema_paths = {
      "production_config_sha256":
          "configs/finals/capd_proactive_stage11_v2_production.json",
      "production_result_schema_sha256":
          "configs/finals/capd_proactive_stage11_v2_production_result_schema.json",
      "production_run_identity_schema_sha256":
          "configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json",
      "production_run_state_schema_sha256":
          "configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json",
      "release_manifest_schema_sha256":
          "configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json"}
  _require(
      receipt["schema_version"] ==
      "capd_proactive_stage11_v2_production_execution_authorization_v1_0" and
      receipt["contract_id"] == CONTRACT_ID and
      receipt["production_revision"] == PRODUCTION_REVISION and
      receipt["run_id"] == RUN_ID and
      receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
      receipt["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
      all(receipt[field] == sha256_file(root / path)
          for field, path in schema_paths.items()) and
      receipt["input_audit_receipt_sha256"] == input_hashes["receipt_sha256"] and
      receipt["input_audit_manifest_sha256"] == input_hashes["manifest_sha256"] and
      receipt["input_audit_checksums_sha256"] == input_hashes["checksums_sha256"],
      "Execution authorization primary binding mismatch.")
  for field in (
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "test_source_identity_sha256", "test_source_pre_snapshot_sha256",
      "test_source_post_snapshot_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256", "stage8_input_receipt_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256"):
    _require(receipt[field] == input_receipt[field],
             "Execution/input-audit binding mismatch: {}".format(field))
  anchors = config["stage10_external_anchors"]
  _require(
      receipt["stage10_generation_freeze_receipt_sha256"] ==
      anchors["generation_freeze_receipt_sha256"] and
      receipt["stage10_readiness_receipt_sha256"] ==
      anchors["readiness_receipt_sha256"] and
      receipt["stage10_final_status_receipt_sha256"] ==
      anchors["final_status_receipt_sha256"] and
      receipt["sealed_frozen_tree_after_sha256"] ==
      input_receipt["frozen_tree_after_sha256"] and
      receipt["frozen_cost_profiles_sha256"] ==
      sha256_value(config["cost_profiles"]) and
      receipt["generation_source_member_count"] == 30 and
      receipt["verifier_source_member_count"] == 32 and
      receipt["standard_job_count"] == 48 and
      receipt["standard_workload_count"] == 6 and
      receipt["main_b_max"] == 2 and
      receipt["authorized_scope"] == "offline_cost_profiles_only" and
      receipt["expected_result_rows"] == 192 and
      tuple(receipt["blocked_lanes"]) == BLOCKED_LANES and
      receipt["stage11_execution_authorized"] is True and
      receipt["synthetic_test_only"] is False and
      receipt["test_used_for_parameter_selection"] is False and
      receipt["test_sources_unchanged"] is True and
      receipt["future_output_hashes_absent"] is True and
      isinstance(receipt["approval_authority"], str) and
      bool(receipt["approval_authority"]) and
      isinstance(receipt["approval_reference"], str) and
      bool(receipt["approval_reference"]),
      "Execution authorization scope or inherited binding mismatch.")


def validate_generation_identity_chain(
    project_root: os.PathLike[str] | str,
    generation_package: Mapping[str, bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
  verify_package(generation_package, phase="generation",
                 payload_names=GENERATION_PAYLOADS)
  root = Path(project_root).resolve()
  json_names = {name for name in GENERATION_PAYLOADS if name.endswith(".json")}
  values = {name: load_json_bytes_strict(generation_package[name], name)
            for name in json_names}
  config = values["stage11_v2_config.json"]
  current_config = load_json_strict(
      root / "configs/finals/capd_proactive_stage11_v2_production.json")
  _require(config == current_config and
           config.get("contract_id") == CONTRACT_ID and
           config.get("production_revision") == PRODUCTION_REVISION and
           config.get("run_id") == RUN_ID,
           "Generation config differs from the current frozen config.")

  identity = values["run_identity.json"]
  identity_fields = {
      "schema_version", "contract_id", "production_revision", "run_id",
      "approved_production_design_sha256", "approved_production_plan_sha256",
      "production_config_sha256", "production_result_schema_sha256",
      "input_audit_receipt_sha256", "input_audit_manifest_sha256",
      "input_audit_checksums_sha256", "execution_authorization_receipt_sha256",
      "execution_authorization_manifest_sha256",
      "execution_authorization_checksums_sha256",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "stage8_input_receipt_sha256", "stage9_input_receipt_sha256",
      "stage10_input_receipt_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256", "frozen_cost_profiles_sha256",
      "frozen_grid_sha256", "sealed_frozen_tree_after_sha256",
      "pre_generation_continuity_snapshot_sha256", "code_version",
      "source_snapshot_sha256", "expected_result_rows",
      "test_used_for_parameter_selection"}
  _exact_keys(identity, identity_fields, "Generation run identity")
  _exact_keys(identity["code_version"], {"commit", "dirty"},
              "Generation code version")
  _require((identity["code_version"]["commit"] is None or
            isinstance(identity["code_version"]["commit"], str)) and
           (identity["code_version"]["dirty"] is None or
            isinstance(identity["code_version"]["dirty"], bool)),
           "Generation code-version diagnostic is invalid.")
  _require(
      identity["schema_version"] ==
      "capd_proactive_stage11_v2_production_run_identity_v1_0" and
      identity["contract_id"] == CONTRACT_ID and
      identity["production_revision"] == PRODUCTION_REVISION and
      identity["run_id"] == RUN_ID and
      identity["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
      identity["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
      identity["production_config_sha256"] == sha256_file(
          root / "configs/finals/capd_proactive_stage11_v2_production.json") and
      identity["production_result_schema_sha256"] == sha256_file(
          root / "configs/finals/capd_proactive_stage11_v2_production_result_schema.json") and
      identity["expected_result_rows"] == 192 and
      identity["test_used_for_parameter_selection"] is False,
      "Generation run identity primary fields mismatch.")

  input_binding = values["input_audit_binding.json"]
  _exact_keys(input_binding, {
      "schema_version", "contract_id", "audit_id", "package_path",
      "receipt_sha256", "manifest_sha256", "checksums_sha256"},
      "Generation input-audit binding")
  input_receipt = values["input_audit_receipt.json"]
  validate_input_audit_receipt(input_receipt)
  _require(input_binding["schema_version"] ==
           "capd_proactive_stage11_v2_input_audit_binding_v1_0" and
           input_binding["contract_id"] == CONTRACT_ID and
           input_binding["audit_id"] == AUDIT_ID and
           identity["input_audit_receipt_sha256"] ==
           input_binding["receipt_sha256"] ==
           sha256_bytes(generation_package["input_audit_receipt.json"]) and
           identity["input_audit_manifest_sha256"] ==
           input_binding["manifest_sha256"] and
           identity["input_audit_checksums_sha256"] ==
           input_binding["checksums_sha256"],
           "Generation input-audit package binding mismatch.")

  authorization_binding = values["execution_authorization_binding.json"]
  _exact_keys(authorization_binding, {
      "schema_version", "contract_id", "run_id", "package_path",
      "receipt_sha256", "manifest_sha256", "checksums_sha256"},
      "Generation execution-authorization binding")
  authorization = values["execution_authorization_receipt.json"]
  input_hashes = {
      "receipt_sha256": input_binding["receipt_sha256"],
      "manifest_sha256": input_binding["manifest_sha256"],
      "checksums_sha256": input_binding["checksums_sha256"]}
  validate_execution_authorization_receipt(
      root, authorization, config, input_receipt, input_hashes)
  _require(authorization_binding["schema_version"] ==
           "capd_proactive_stage11_v2_production_execution_authorization_binding_v1_0" and
           authorization_binding["contract_id"] == CONTRACT_ID and
           authorization_binding["run_id"] == RUN_ID and
           identity["execution_authorization_receipt_sha256"] ==
           authorization_binding["receipt_sha256"] == sha256_bytes(
               generation_package["execution_authorization_receipt.json"]) and
           identity["execution_authorization_manifest_sha256"] ==
           authorization_binding["manifest_sha256"] and
           identity["execution_authorization_checksums_sha256"] ==
           authorization_binding["checksums_sha256"],
           "Generation execution-authorization package binding mismatch.")

  generation_manifest = values["generation_source_manifest.json"]
  verifier_manifest = values["verifier_source_manifest.json"]
  rebuilt_generation = generation_source_manifest_value(root)
  rebuilt_verifier = source_manifest_value(root)
  _require(generation_manifest == rebuilt_generation and
           verifier_manifest == rebuilt_verifier and
           identity["generation_source_manifest_sha256"] ==
           sha256_bytes(generation_package["generation_source_manifest.json"]) ==
           authorization["generation_source_manifest_sha256"] and
           identity["generation_source_members_sha256"] ==
           generation_manifest["members_sha256"] ==
           authorization["generation_source_members_sha256"] and
           identity["verifier_source_manifest_sha256"] ==
           sha256_bytes(generation_package["verifier_source_manifest.json"]) ==
           authorization["verifier_source_manifest_sha256"] and
           identity["verifier_source_members_sha256"] ==
           verifier_manifest["members_sha256"] ==
           authorization["verifier_source_members_sha256"] and
           identity["source_snapshot_sha256"] ==
           sha256_value(source_snapshot(root, GENERATION_SOURCE_PATHS)),
           "Generation source identity chain mismatch.")

  for name, field in (
      ("stage8_standard_input_receipt.json", "stage8_input_receipt_sha256"),
      ("stage9_input_receipt.json", "stage9_input_receipt_sha256"),
      ("stage10_input_receipt.json", "stage10_input_receipt_sha256"),
      ("standard_source_manifest.json", "standard_source_manifest_sha256")):
    _require(identity[field] == sha256_bytes(generation_package[name]) ==
             input_receipt[field] == authorization[field],
             "Generation canonical input binding mismatch: {}".format(name))
  standard_manifest = values["standard_source_manifest.json"]
  _require(identity["sorted_job_ids_sha256"] ==
           standard_manifest["sorted_job_ids_sha256"] ==
           input_receipt["sorted_job_ids_sha256"] ==
           authorization["sorted_job_ids_sha256"],
           "Generation Standard job identity mismatch.")

  grid = values["frozen_grid.json"]
  _exact_keys(grid, {"schema_version", "main_b_max", "cost_profiles",
                     "blocked_lanes", "test_used_for_parameter_selection",
                     "frozen_grid_sha256"}, "Frozen generation grid")
  grid_payload = {key: grid[key] for key in (
      "main_b_max", "cost_profiles", "blocked_lanes",
      "test_used_for_parameter_selection")}
  _require(grid["schema_version"] ==
           "capd_proactive_stage11_v2_frozen_grid_v1_0" and
           grid["main_b_max"] == 2 and grid["cost_profiles"] == PROFILE_WEIGHTS and
           tuple(grid["blocked_lanes"]) == BLOCKED_LANES and
           grid["test_used_for_parameter_selection"] is False and
           grid["frozen_grid_sha256"] == sha256_value(grid_payload) ==
           identity["frozen_grid_sha256"] and
           identity["frozen_cost_profiles_sha256"] ==
           sha256_value(PROFILE_WEIGHTS), "Generation frozen grid mismatch.")

  sealed = values["sealed_frozen_tree_after.json"]
  pre = values["pre_generation_continuity_snapshot.json"]
  post = values["post_generation_continuity_snapshot.json"]
  comparison = values["generation_continuity_comparison.json"]
  expected_comparison = compare_continuity(
      sealed, [("sealed_vs_pre_generation", pre),
               ("sealed_vs_post_generation", post)])
  state = values["run_state.json"]
  state_fields = {
      "schema_version", "contract_id", "run_id", "status", "result_row_count",
      "sealed_frozen_tree_after_sha256",
      "pre_generation_continuity_snapshot_sha256",
      "post_generation_continuity_snapshot_sha256",
      "generation_continuity_comparison_sha256", "upstream_continuity_verified",
      "blocked_lanes", "monitoring", "stage11_generation_verified",
      "stage11_final_approval_verified", "stage11_formally_verified",
      "test_used_for_parameter_selection"}
  _exact_keys(state, state_fields, "Generation run state")
  validate_monitoring(state["monitoring"])
  _require(state["monitoring"]["timed_out"] is False and
           state["monitoring"]["exit_code"] == 0 and
           state["schema_version"] ==
           "capd_proactive_stage11_v2_production_run_state_v1_0" and
           state["contract_id"] == CONTRACT_ID and state["run_id"] == RUN_ID and
           state["status"] ==
           "stage11_generation_complete_pending_independent_verification" and
           state["result_row_count"] == 192 and
           state["sealed_frozen_tree_after_sha256"] ==
           identity["sealed_frozen_tree_after_sha256"] ==
           input_receipt["frozen_tree_after_sha256"] == sha256_value(sealed) and
           state["pre_generation_continuity_snapshot_sha256"] ==
           identity["pre_generation_continuity_snapshot_sha256"] ==
           sha256_value(pre) and
           state["post_generation_continuity_snapshot_sha256"] ==
           sha256_value(post) and
           state["generation_continuity_comparison_sha256"] ==
           sha256_value(comparison) and comparison == expected_comparison and
           state["upstream_continuity_verified"] is True and
           tuple(state["blocked_lanes"]) == BLOCKED_LANES and
           state["stage11_generation_verified"] is False and
           state["stage11_final_approval_verified"] is False and
           state["stage11_formally_verified"] is False and
           state["test_used_for_parameter_selection"] is False,
           "Generation run-state or continuity binding mismatch.")
  return identity, state


def validate_external_generation_inputs(
    generation_package: Mapping[str, bytes],
    input_package: Mapping[str, bytes], authorization_package: Mapping[str, bytes],
    *, input_hashes: Mapping[str, str],
    authorization_hashes: Mapping[str, str]) -> None:
  verify_package(input_package, phase="input_audit",
                 payload_names=INPUT_AUDIT_PAYLOADS)
  verify_package(authorization_package, phase="execution_authorization",
                 payload_names={"execution_authorization_receipt.json"})
  for package, hashes, receipt_name, label in (
      (input_package, input_hashes, "input_audit_receipt.json", "Input audit"),
      (authorization_package, authorization_hashes,
       "execution_authorization_receipt.json", "Execution authorization")):
    _require(sha256_bytes(package[receipt_name]) == hashes["receipt_sha256"] and
             sha256_bytes(package["manifest.json"]) == hashes["manifest_sha256"] and
             sha256_bytes(package["SHA256SUMS"]) == hashes["checksums_sha256"],
             label + " external SHA mismatch.")
  _require(generation_package["input_audit_receipt.json"] ==
           input_package["input_audit_receipt.json"] and
           generation_package["execution_authorization_receipt.json"] ==
           authorization_package["execution_authorization_receipt.json"],
           "Generation embedded receipt differs from approved external package.")


def build_verification_package(
    *, generation_package: Mapping[str, bytes], jobs: Sequence[Mapping[str, Any]],
    sealed_snapshot: Mapping[str, Any], pre_snapshot: Mapping[str, Any],
    post_snapshot: Mapping[str, Any], monitoring: Mapping[str, Any]
    ) -> dict[str, bytes]:
  validate_generation_identity_chain(Path(__file__).resolve().parents[1],
                                     generation_package)
  result = json.loads(generation_package["stage11_v2_results.json"])
  _exact_keys(result, {
      "schema_version", "contract_id", "run_id", "lane", "rows",
      "blocked_lanes", "stage11_formally_verified",
      "test_used_for_parameter_selection"}, "Generation result")
  _require(result["schema_version"] ==
           "capd_proactive_stage11_v2_production_result_v1_0" and
           result["contract_id"] == CONTRACT_ID and result["run_id"] == RUN_ID and
           result["lane"] == "offline_cost_profiles" and
           tuple(result["blocked_lanes"]) == BLOCKED_LANES and
           result["stage11_formally_verified"] is False and
           result["test_used_for_parameter_selection"] is False,
           "Generation result state/scope mismatch.")
  verify_result_rows(result["rows"], jobs)
  verify_csv(result["rows"], generation_package["stage11_v2_results.csv"])
  identity = json.loads(generation_package["run_identity.json"])
  state = json.loads(generation_package["run_state.json"])
  _require(identity.get("contract_id") == CONTRACT_ID and
           identity.get("run_id") == RUN_ID and
           identity.get("approved_production_design_sha256") ==
           APPROVED_DESIGN_SHA256 and
           identity.get("approved_production_plan_sha256") ==
           APPROVED_PLAN_SHA256 and
           identity.get("expected_result_rows") == 192 and
           identity.get("test_used_for_parameter_selection") is False,
           "Generation run identity binding mismatch.")
  _require(state.get("status") ==
           "stage11_generation_complete_pending_independent_verification" and
           state.get("result_row_count") == 192 and
           state.get("upstream_continuity_verified") is True and
           state.get("stage11_generation_verified") is False and
           state.get("stage11_final_approval_verified") is False and
           state.get("stage11_formally_verified") is False and
           state.get("test_used_for_parameter_selection") is False,
           "Generation run state improperly advances release status.")
  comparison = compare_continuity(
      sealed_snapshot, [("sealed_vs_pre_verification", pre_snapshot),
                        ("sealed_vs_post_verification", post_snapshot)])
  validate_monitoring(monitoring)
  receipt = {
      "schema_version":
          "capd_proactive_stage11_v2_production_verification_receipt_v1_0",
      "contract_id": CONTRACT_ID, "production_revision": PRODUCTION_REVISION,
      "run_id": RUN_ID,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "input_audit_receipt_sha256": identity["input_audit_receipt_sha256"],
      "input_audit_manifest_sha256": identity["input_audit_manifest_sha256"],
      "input_audit_checksums_sha256": identity["input_audit_checksums_sha256"],
      "execution_authorization_receipt_sha256":
          identity["execution_authorization_receipt_sha256"],
      "execution_authorization_manifest_sha256":
          identity["execution_authorization_manifest_sha256"],
      "execution_authorization_checksums_sha256":
          identity["execution_authorization_checksums_sha256"],
      "generation_result_sha256":
          sha256_bytes(generation_package["stage11_v2_results.json"]),
      "generation_run_identity_sha256":
          sha256_bytes(generation_package["run_identity.json"]),
      "generation_run_state_sha256":
          sha256_bytes(generation_package["run_state.json"]),
      "generation_manifest_sha256": sha256_bytes(generation_package["manifest.json"]),
      "generation_checksums_sha256": sha256_bytes(generation_package["SHA256SUMS"]),
      "standard_source_manifest_sha256":
          identity["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": identity["sorted_job_ids_sha256"],
      "sealed_frozen_tree_after_sha256": sha256_value(sealed_snapshot),
      "pre_generation_continuity_snapshot_sha256":
          state["pre_generation_continuity_snapshot_sha256"],
      "post_generation_continuity_snapshot_sha256":
          state["post_generation_continuity_snapshot_sha256"],
      "pre_verification_continuity_snapshot_sha256": sha256_value(pre_snapshot),
      "post_verification_continuity_snapshot_sha256": sha256_value(post_snapshot),
      "generation_continuity_comparison_sha256":
          state["generation_continuity_comparison_sha256"],
      "verification_continuity_comparison_sha256": sha256_value(comparison),
      "upstream_continuity_verified": True,
      "verification_receipt_identity": "stage11-v2-production-verification-r1",
      "result_row_count": 192, "result_rows_verified": True,
      "status": "stage11_generation_verified_pending_final_approval",
      "monitoring": dict(monitoring), "stage11_formally_verified": False,
      "synthetic_test_only": False, "test_used_for_parameter_selection": False}
  validate_verification_receipt(receipt)
  payloads = {
      "verification_receipt.json": canonical_json_bytes(receipt),
      "sealed_frozen_tree_after.json": canonical_json_bytes(sealed_snapshot),
      "pre_verification_continuity_snapshot.json": canonical_json_bytes(pre_snapshot),
      "post_verification_continuity_snapshot.json": canonical_json_bytes(post_snapshot),
      "verification_continuity_comparison.json": canonical_json_bytes(comparison)}
  _require(set(payloads) == VERIFICATION_PAYLOADS,
           "Verification payload exact member set mismatch.")
  return package_bytes("verification", payloads)


COMMON_RELEASE_FIELDS = {
    "schema_version", "contract_id", "production_revision", "run_id",
    "approved_production_design_sha256", "approved_production_plan_sha256",
    "input_audit_receipt_sha256", "input_audit_manifest_sha256",
    "input_audit_checksums_sha256", "execution_authorization_receipt_sha256",
    "execution_authorization_manifest_sha256",
    "execution_authorization_checksums_sha256", "generation_result_sha256",
    "generation_run_identity_sha256", "generation_run_state_sha256",
    "generation_manifest_sha256", "generation_checksums_sha256",
    "standard_source_manifest_sha256", "sorted_job_ids_sha256",
    "sealed_frozen_tree_after_sha256", "pre_generation_continuity_snapshot_sha256",
    "post_generation_continuity_snapshot_sha256",
    "pre_verification_continuity_snapshot_sha256",
    "post_verification_continuity_snapshot_sha256",
    "generation_continuity_comparison_sha256",
    "verification_continuity_comparison_sha256", "upstream_continuity_verified",
    "synthetic_test_only", "test_used_for_parameter_selection"}


def validate_verification_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
  expected = COMMON_RELEASE_FIELDS | {
      "verification_receipt_identity", "result_row_count",
      "result_rows_verified", "status", "monitoring", "stage11_formally_verified"}
  _exact_keys(receipt, expected, "Verification receipt")
  _require(receipt["schema_version"] ==
           "capd_proactive_stage11_v2_production_verification_receipt_v1_0" and
           receipt["contract_id"] == CONTRACT_ID and
           receipt["production_revision"] == PRODUCTION_REVISION and
           receipt["run_id"] == RUN_ID, "Verification receipt identity mismatch.")
  _require(receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256,
           "Verification approval binding mismatch.")
  _require(receipt["result_row_count"] == 192 and
           receipt["result_rows_verified"] is True and
           receipt["upstream_continuity_verified"] is True and
           receipt["status"] == "stage11_generation_verified_pending_final_approval" and
           receipt["stage11_formally_verified"] is False and
           receipt["synthetic_test_only"] is False and
           receipt["test_used_for_parameter_selection"] is False,
           "Verification receipt improperly advances final state.")
  validate_monitoring(receipt["monitoring"])
  return receipt


def validate_final_approval_receipt(receipt: Mapping[str, Any],
                                    verification_hashes: Mapping[str, str],
                                    inherited_bindings: Mapping[str, Any] | None = None
                                    ) -> None:
  expected = COMMON_RELEASE_FIELDS | {
      "verification_receipt_sha256", "verification_manifest_sha256",
      "verification_checksums_sha256", "final_approval_granted",
      "approval_authority", "approval_reference", "stage11_formally_verified"}
  _exact_keys(receipt, expected, "Final approval receipt")
  _require(receipt["schema_version"] ==
           "capd_proactive_stage11_v2_production_final_approval_receipt_v1_0" and
           receipt["contract_id"] == CONTRACT_ID and
           receipt["production_revision"] == PRODUCTION_REVISION and
           receipt["run_id"] == RUN_ID, "Final approval identity mismatch.")
  for field in ("verification_receipt_sha256", "verification_manifest_sha256",
                "verification_checksums_sha256"):
    _require(receipt[field] == verification_hashes[field],
             "Final approval verification binding mismatch.")
  for field, value in (inherited_bindings or {}).items():
    _require(field in receipt and receipt[field] == value,
             "Final approval inherited binding mismatch: {}".format(field))
  _require(receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
           receipt["upstream_continuity_verified"] is True and
           receipt["final_approval_granted"] is True and
           receipt["stage11_formally_verified"] is False and
           receipt["synthetic_test_only"] is False and
           receipt["test_used_for_parameter_selection"] is False,
           "Final approval receipt semantics mismatch.")


def consume_final_status(receipt: Mapping[str, Any], *,
                         final_approval_hashes: Mapping[str, str],
                         inherited_bindings: Mapping[str, Any]) -> bool:
  expected = COMMON_RELEASE_FIELDS | {
      "verification_receipt_sha256", "verification_manifest_sha256",
      "verification_checksums_sha256", "final_approval_receipt_sha256",
      "final_approval_manifest_sha256", "final_approval_checksums_sha256",
      "generation_verified", "final_approval_verified",
      "stage11_formally_verified"}
  _exact_keys(receipt, expected, "Final-status evidence receipt")
  _require(receipt["schema_version"] ==
           "capd_proactive_stage11_v2_production_final_status_evidence_receipt_v1_0" and
           receipt["contract_id"] == CONTRACT_ID and
           receipt["production_revision"] == PRODUCTION_REVISION and
           receipt["run_id"] == RUN_ID, "Final-status identity mismatch.")
  for field in ("final_approval_receipt_sha256", "final_approval_manifest_sha256",
                "final_approval_checksums_sha256"):
    _require(receipt[field] == final_approval_hashes[field],
             "Final-status approval binding mismatch.")
  for field, value in inherited_bindings.items():
    _require(field in receipt and receipt[field] == value,
             "Final-status inherited binding mismatch: {}".format(field))
  _require(receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
           receipt["upstream_continuity_verified"] is True and
           receipt["generation_verified"] is True and
           receipt["final_approval_verified"] is True and
           receipt["stage11_formally_verified"] is True and
           receipt["synthetic_test_only"] is False and
           receipt["test_used_for_parameter_selection"] is False,
           "Final-status evidence chain is incomplete.")
  return True


def write_release_package(capability: production_guard.WriteCapability, *,
                          phase: str, identity: str,
                          output_root: os.PathLike[str] | str,
                          package: Mapping[str, bytes]) -> None:
  _require(set(package) == set(production_guard.PHASE_ARTIFACTS[phase]),
           "Release writer exact member set mismatch.")
  for artifact in sorted(package):
    production_guard.guarded_write_bytes(
        capability, phase=phase, identity=identity, output_root=output_root,
        artifact=artifact, data=package[artifact])
