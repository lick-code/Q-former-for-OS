"""Independent Stage11 v2 verifier.

This module deliberately does not import the generation module or Cost helper.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping

from qmap import proactive_stage11_v2_guard as path_guard


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11-2.0"
APPROVED_DESIGN_SHA256 = "0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160"
APPROVED_PLAN_SHA256 = "64a8c99acd0f2475a5a792fe732439691b6667ed11890578da74ca0707832870"
STANDARD_WORKLOADS = (
    "blackscholes", "canneal", "dedup_pressure", "fluidanimate",
    "streamcluster_pressure", "swaptions")
STANDARD_MEMBERS = (
    ("reactive_lru", None), ("proactive_lru", None),
    ("proactive_clock", None), ("tpp_inspired", None), ("oracle", None),
    ("capd", 42), ("capd", 2026), ("capd", 3136859))
PROFILES = {
    "read_light": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 4, "demotion": 8},
    "default": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
    "write_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 12, "demotion": 10},
    "migration_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 20},
}
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


class Stage11V2VerificationError(ValueError):
  pass


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage11V2VerificationError(message)


def _is_sha256(value: Any) -> bool:
  return (isinstance(value, str) and len(value) == 64 and
          all(character in "0123456789abcdef" for character in value))


def _pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise Stage11V2VerificationError("Duplicate JSON key: {}".format(key))
    result[key] = value
  return result


def _constant(value):
  raise Stage11V2VerificationError("Non-finite JSON value: {}".format(value))


def load_json_strict(path: os.PathLike[str] | str) -> Any:
  try:
    with open(path, "r", encoding="utf-8") as handle:
      return json.load(handle, object_pairs_hook=_pairs, parse_constant=_constant)
  except Stage11V2VerificationError:
    raise
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise Stage11V2VerificationError(
        "Cannot load JSON {}: {}".format(path, exc)) from exc


def _finite(value: Any) -> None:
  if isinstance(value, Mapping):
    for item in value.values():
      _finite(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      _finite(item)
  elif isinstance(value, float) and not math.isfinite(value):
    raise Stage11V2VerificationError("Non-finite JSON value.")


def canonical_bytes(value: Any) -> bytes:
  _finite(value)
  return json.dumps(value, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_value(value: Any) -> str:
  return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def _local_import_paths(path: Path) -> set[str]:
  tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
  result = set()
  for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "qmap":
      for alias in node.names:
        result.add("qmap/{}.py".format(alias.name.replace(".", "/")))
    elif (isinstance(node, ast.ImportFrom) and node.module and
          node.module.startswith("qmap.")):
      result.add(node.module.replace(".", "/") + ".py")
    elif isinstance(node, ast.Import):
      for alias in node.names:
        if alias.name.startswith("qmap."):
          result.add(alias.name.replace(".", "/") + ".py")
  return result


def validate_source_manifest(project_root: os.PathLike[str] | str,
                             manifest_path: os.PathLike[str] | str,
                             role: str) -> Dict[str, str]:
  root = Path(project_root).resolve()
  path = Path(manifest_path).resolve()
  _require(path.is_file() and path.is_relative_to(root),
           "Source manifest path is outside the project root.")
  expected_paths = (GENERATION_SOURCE_PATHS if role == "generation" else
                    VERIFIER_SOURCE_PATHS)
  _require(role in ("generation", "verifier") and
           len(expected_paths) == (22 if role == "generation" else 24),
           "Source role or exact path contract is invalid.")
  manifest = load_json_strict(path)
  expected_fields = {
      "schema_version", "contract_id", "role", "approved_design_sha256",
      "approved_plan_sha256", "members", "member_count", "members_sha256",
      "local_import_closure_complete", "exclusions"}
  _require(isinstance(manifest, Mapping) and set(manifest) == expected_fields and
           manifest.get("schema_version") ==
           "capd_proactive_stage11_v2_source_manifest_v1_0" and
           manifest.get("contract_id") == CONTRACT_ID and
           manifest.get("role") == role and
           manifest.get("approved_design_sha256") == APPROVED_DESIGN_SHA256 and
           manifest.get("approved_plan_sha256") == APPROVED_PLAN_SHA256 and
           manifest.get("local_import_closure_complete") is True and
           manifest.get("exclusions") == list(SOURCE_EXCLUSIONS),
           "Source manifest identity or field set mismatch.")
  members = manifest.get("members")
  _require(isinstance(members, list) and
           all(isinstance(item, Mapping) and set(item) == {"path", "sha256"}
               for item in members),
           "Source manifest members are malformed.")
  member_paths = [item["path"] for item in members]
  expected_sorted = sorted(expected_paths)
  _require(member_paths == expected_sorted and
           len(member_paths) == len(set(member_paths)) == len(expected_paths) and
           manifest.get("member_count") == len(expected_paths) and
           manifest.get("members_sha256") == sha256_value(members),
           "Source manifest exact member set or aggregate SHA mismatch.")
  local_imports = set()
  for member in members:
    member_path = (root / member["path"]).resolve()
    _require(member_path.is_file() and member_path.is_relative_to(root) and
             sha256_file(member_path) == member["sha256"],
             "Source member path or SHA mismatch: {}".format(member["path"]))
    if member["path"].endswith(".py"):
      local_imports.update(_local_import_paths(member_path))
  path_set = set(member_paths)
  _require(local_imports <= path_set,
           "Source manifest omits local import closure: {}".format(
               sorted(local_imports - path_set)))
  if role == "verifier":
    _require("qmap/proactive_stage11_v2.py" not in local_imports and
             "qmap/proactive_cost.py" not in local_imports,
             "Independent verifier imports generation or Cost code.")
  _require("qmap/proactive_stage11.py" not in path_set and
           "scripts/run_capd_proactive_stage11.py" not in path_set,
           "Stage11 v1 leaked into a v2 source manifest.")
  return {
      "{}_source_manifest_sha256".format(role): sha256_file(path),
      "{}_source_members_sha256".format(role): manifest["members_sha256"],
  }


def validate_source_identity(
    project_root: os.PathLike[str] | str,
    generation_manifest_path: os.PathLike[str] | str,
    verifier_manifest_path: os.PathLike[str] | str,
) -> Dict[str, str]:
  result = {}
  result.update(validate_source_manifest(
      project_root, generation_manifest_path, "generation"))
  result.update(validate_source_manifest(
      project_root, verifier_manifest_path, "verifier"))
  return result


def _relative_files(root: Path) -> list[tuple[str, Path]]:
  return sorted((path.relative_to(root).as_posix(), path)
                for path in root.rglob("*") if path.is_file())


def verify_envelope(root: os.PathLike[str] | str, phase: str,
                    receipt_name: str | None = None,
                    expected_receipt_sha256: str | None = None
                    ) -> Dict[str, Any]:
  base = Path(root).resolve()
  manifest = load_json_strict(base / "manifest.json")
  _require(manifest.get("contract_id") == CONTRACT_ID and
           manifest.get("phase") == phase, "Envelope identity mismatch.")
  actual = {name for name, _ in _relative_files(base)
            if name not in ("manifest.json", "SHA256SUMS")}
  files = manifest.get("files")
  _require(isinstance(files, Mapping) and set(files) == actual,
           "Manifest member set mismatch.")
  for name, digest in files.items():
    _require(sha256_file(base / name) == digest,
             "Manifest hash mismatch: {}".format(name))
  entries = []
  with (base / "SHA256SUMS").open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        parts = line.rstrip("\n").split("  ", 1)
        _require(len(parts) == 2, "Malformed checksum line.")
        entries.append((parts[0], parts[1]))
  _require(len(entries) == len({name for _, name in entries}) and
           {name for _, name in entries} == actual | {"manifest.json"},
           "Checksum member set mismatch.")
  for digest, name in entries:
    _require(sha256_file(base / name) == digest,
             "Checksum mismatch: {}".format(name))
  if receipt_name is not None:
    _require(isinstance(expected_receipt_sha256, str) and
             sha256_file(base / receipt_name) == expected_receipt_sha256,
             "External receipt anchor mismatch.")
  return {"manifest_sha256": sha256_file(base / "manifest.json"),
          "checksums_sha256": sha256_file(base / "SHA256SUMS")}


def _semantic_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
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


def _integer(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
           "{} must be a non-negative integer.".format(field))
  return value


def reconstruct_standard(stage8_root: os.PathLike[str] | str) -> Dict[str, Any]:
  root = Path(stage8_root).resolve()
  state = load_json_strict(root / "run_state.json")
  verification = load_json_strict(root / "verification.json")
  _require(state.get("status") == "stage8_sync_replay_verified" and
           verification.get("status") == "stage8_sync_replay_verified",
           "Stage8 fixture is not verified.")
  manifest = load_json_strict(root / "job_manifest.json")
  plans = [row for row in manifest.get("jobs", []) if row.get("track") == "standard"]
  by_id = {row.get("job_id"): row for row in plans}
  _require(len(plans) == len(by_id) == 48, "Standard plan set must contain 48 jobs.")
  with (root / "artifacts" / "per_workload_raw.csv").open(
      "r", encoding="utf-8", newline="") as handle:
    csv_ids = [row.get("job_id") for row in csv.DictReader(handle)
               if row.get("track") == "standard"]
  _require(len(csv_ids) == len(set(csv_ids)) == 48 and set(csv_ids) == set(by_id),
           "Standard CSV set differs from authority.")
  records = []
  counters = {}
  for job_id in sorted(csv_ids):
    job_root = (root / "jobs" / job_id).resolve()
    _require(job_root.parent == (root / "jobs").resolve(), "Job path escape.")
    job_manifest = load_json_strict(job_root / "job_manifest.json")
    result_path = job_root / "result.json"
    result = load_json_strict(result_path)
    plan = by_id[job_id]
    job_identity = job_manifest.get("job_identity")
    _require(job_manifest.get("status") == "completed" and
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
             sha256_value(job_identity) and
             job_manifest.get("result_sha256") == sha256_file(result_path) and
             job_manifest.get("semantic_result_sha256") ==
             result.get("semantic_result_sha256") and
             result.get("semantic_result_sha256") ==
             sha256_value(_semantic_payload(result)),
             "Stage8 job SHA chain mismatch.")
    for field in ("job_id", "track", "workload", "policy", "seed"):
      _require(result.get(field) == plan.get(field),
               "Stage8 result identity mismatch.")
    metrics = result.get("metrics", {})
    values = {field: _integer(metrics.get(field), field) for field in (
        "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
        "proactive_demotions", "reactive_demotions", "emergency_demotions",
        "raw_access_count")}
    _require(values["total_demotions"] == values["proactive_demotions"] +
             values["reactive_demotions"] + values["emergency_demotions"],
             "Demotion counter mismatch.")
    records.append({
        "job_id": job_id, "track": "standard", "workload": plan["workload"],
        "policy": plan["policy"], "seed": plan.get("seed"),
        "result_sha256": sha256_file(result_path),
        "semantic_result_sha256": result["semantic_result_sha256"]})
    counters[job_id] = values
  _require(tuple(sorted({row["workload"] for row in records})) == STANDARD_WORKLOADS,
           "Workload identity mismatch.")
  for workload in STANDARD_WORKLOADS:
    _require(Counter((row["policy"], row["seed"])
                     for row in records if row["workload"] == workload) ==
             Counter(STANDARD_MEMBERS), "Policy/seed multiset mismatch.")
  ids = [row["job_id"] for row in records]
  return {"records": records, "counters": counters,
          "standard_source_manifest_sha256": sha256_value(records),
          "sorted_job_ids_sha256": sha256_value(ids)}


def _expected_cost(counts: Mapping[str, int], weights: Mapping[str, int]) -> int:
  return (counts["dram_hits"] * weights["dram_hit"] +
          counts["nvm_reads"] * weights["nvm_read"] +
          counts["nvm_writes"] * weights["nvm_write"] +
          counts["total_demotions"] * weights["demotion"])


def verify_generation(generation_root: os.PathLike[str] | str,
                       stage8_root: os.PathLike[str] | str,
                       *, expected_approved_plan_sha256: str,
                       synthetic_mode: bool,
                       project_root: os.PathLike[str] | str,
                       generation_source_manifest: os.PathLike[str] | str,
                       verifier_source_manifest: os.PathLike[str] | str
                       ) -> Dict[str, Any]:
  source_before = validate_source_identity(
      project_root, generation_source_manifest, verifier_source_manifest)
  root = Path(generation_root).resolve()
  envelope = verify_envelope(root, "generation")
  identity = load_json_strict(root / "run_identity.json")
  state = load_json_strict(root / "run_state.json")
  results = load_json_strict(root / "stage11_v2_results.json")
  source_manifest = load_json_strict(root / "standard_source_manifest.json")
  authorization = load_json_strict(root / "execution_authorization_receipt.json")
  _require(expected_approved_plan_sha256 == APPROVED_PLAN_SHA256 and
           identity.get("approved_plan_sha256") == APPROVED_PLAN_SHA256 and
           authorization.get("approved_plan_sha256") == APPROVED_PLAN_SHA256,
           "Approved plan binding mismatch.")
  _require(results.get("contract_id") == CONTRACT_ID and
           results.get("run_id") == identity.get("run_id") and
           results.get("synthetic_test_only") is synthetic_mode,
           "Generation result identity mismatch.")
  authorization_sha = sha256_file(root / "execution_authorization_receipt.json")
  _require(identity.get("authorization_receipt_sha256") == authorization_sha,
           "Generation authorization SHA binding mismatch.")
  shared_identity_fields = (
      "run_id", "approved_design_sha256", "approved_plan_sha256",
      "config_sha256", "result_schema_sha256",
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "standard_source_manifest_sha256", "sorted_job_ids_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256",
      "frozen_grid_sha256")
  _require(all(identity.get(field) == authorization.get(field)
               for field in shared_identity_fields),
           "Generation identity differs from its authorization.")
  source_fields = (
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256")
  _require(all(identity.get(field) == source_before.get(field) and
               authorization.get(field) == source_before.get(field)
               for field in source_fields),
           "Generation source identity differs from independently rebuilt manifests.")
  _require(state.get("status") ==
           "stage11_generation_complete_pending_verification" and
           state.get("stage11_formally_verified") is False,
           "Generation run state is invalid.")
  reconstructed = reconstruct_standard(stage8_root)
  _require(source_manifest.get("records") == reconstructed["records"] and
           identity.get("standard_source_manifest_sha256") ==
           reconstructed["standard_source_manifest_sha256"] and
           identity.get("sorted_job_ids_sha256") ==
           reconstructed["sorted_job_ids_sha256"],
           "Generation Standard source identity mismatch.")
  rows = results.get("rows")
  _require(isinstance(rows, list) and len(rows) == 48 * 4,
           "Generation must contain 192 Cost rows.")
  seen = set()
  record_by_id = {row["job_id"]: row for row in reconstructed["records"]}
  for row in rows:
    key = (row.get("source_job_id"), row.get("cost_profile"))
    _require(key not in seen and key[0] in reconstructed["counters"] and
             key[1] in PROFILES, "Result row identity is invalid.")
    seen.add(key)
    counts = reconstructed["counters"][key[0]]
    record = record_by_id[key[0]]
    _require(row.get("row_id") == "{}__{}".format(key[0], key[1]) and
             row.get("run_id") == identity.get("run_id") and
             row.get("track") == "standard" and
             row.get("workload") == record["workload"] and
             row.get("policy") == record["policy"] and
             row.get("seed") == record["seed"] and
             row.get("cost_profile_weights") == PROFILES[key[1]] and
             all(row.get(field) == counts[field] for field in (
                 "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                 "proactive_demotions", "reactive_demotions",
                 "emergency_demotions", "raw_access_count")),
             "Result row source identity or raw counters changed.")
    expected = _expected_cost(counts, PROFILES[key[1]])
    _require(row.get("weighted_cost") == expected and
             row.get("evidence_status") == "candidate-ready" and
             row.get("evidence_mode") == "offline_raw_counter_recompute",
             "Independent Cost recomputation failed.")
    accesses = counts["raw_access_count"]
    expected_per_access = None if accesses == 0 else expected / float(accesses)
    _require(row.get("weighted_cost_per_access") == expected_per_access,
             "Cost per access mismatch.")
  _require(authorization.get("synthetic_test_only") is synthetic_mode and
           identity.get("synthetic_test_only") is synthetic_mode,
           "Synthetic/production identity mismatch.")
  source_after = validate_source_identity(
      project_root, generation_source_manifest, verifier_source_manifest)
  _require(source_after == source_before,
           "Verifier source identity changed during verification.")
  result = {
      "run_id": identity["run_id"],
      "authorization_receipt_sha256": sha256_file(
          root / "execution_authorization_receipt.json"),
      "generation_run_identity_sha256": sha256_file(root / "run_identity.json"),
      "generation_run_state_sha256": sha256_file(root / "run_state.json"),
      "generation_manifest_sha256": envelope["manifest_sha256"],
      "generation_checksums_sha256": envelope["checksums_sha256"],
      "result_artifact_sha256": sha256_file(root / "stage11_v2_results.json"),
      "standard_source_manifest_sha256":
          reconstructed["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": reconstructed["sorted_job_ids_sha256"],
      "stage11_generation_verified": True,
      "stage11_formally_verified": False,
      "synthetic_test_only": synthetic_mode,
  }
  result.update(source_before)
  return result


def _atomic_text(capability: Any, relative: str, value: str) -> Path:
  target = path_guard.child_target(capability, relative)
  target.parent.mkdir(parents=True, exist_ok=True)
  temporary = target.with_name(target.name + ".tmp")
  path_guard.require_capability(capability, temporary)
  temporary.write_text(value, encoding="utf-8", newline="")
  os.replace(temporary, target)
  return target


def _atomic_json(capability: Any, relative: str, value: Any) -> Path:
  return _atomic_text(
      capability, relative,
      json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                 allow_nan=False) + "\n")


def _manifest(root: Path, phase: str) -> Dict[str, Any]:
  files = {name: sha256_file(path) for name, path in _relative_files(root)
           if name not in ("manifest.json", "SHA256SUMS")}
  return {"schema_version": "capd_proactive_stage11_v2_release_manifest_v1_0",
          "contract_id": CONTRACT_ID, "phase": phase, "files": files}


def _checksums(root: Path) -> str:
  return "".join("{}  {}\n".format(sha256_file(path), name)
                 for name, path in _relative_files(root) if name != "SHA256SUMS")


def emit_verification_receipt(capability: Any, verified: Mapping[str, Any],
                              source_identity: Mapping[str, str],
                              negative_test_identity: str) -> Dict[str, str]:
  cap = path_guard.require_capability(capability)
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_verification_receipt_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": verified["run_id"],
      "approved_plan_sha256": APPROVED_PLAN_SHA256,
      "authorization_receipt_sha256": verified["authorization_receipt_sha256"],
      "generation_run_identity_sha256": verified["generation_run_identity_sha256"],
      "generation_run_state_sha256": verified["generation_run_state_sha256"],
      "generation_manifest_sha256": verified["generation_manifest_sha256"],
      "generation_checksums_sha256": verified["generation_checksums_sha256"],
      "result_artifact_sha256": verified["result_artifact_sha256"],
      "standard_source_manifest_sha256": verified["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": verified["sorted_job_ids_sha256"],
      "generation_source_manifest_sha256":
          source_identity["generation_source_manifest_sha256"],
      "verifier_source_manifest_sha256":
          source_identity["verifier_source_manifest_sha256"],
      "negative_test_identity": negative_test_identity,
      "stage11_generation_verified": True,
      "stage11_formally_verified": False,
      "synthetic_test_only": verified["synthetic_test_only"],
  }
  _atomic_json(cap, "verification_receipt.json", receipt)
  _atomic_json(cap, "manifest.json", _manifest(cap.root, "verification"))
  _atomic_text(cap, "SHA256SUMS", _checksums(cap.root))
  return {"receipt_sha256": sha256_file(cap.root / "verification_receipt.json"),
          "manifest_sha256": sha256_file(cap.root / "manifest.json"),
          "checksums_sha256": sha256_file(cap.root / "SHA256SUMS")}


def validate_final_approval(root: os.PathLike[str] | str,
                            expected_receipt_sha256: str,
                            *, expected: Mapping[str, Any] | None = None
                            ) -> Dict[str, Any]:
  base = Path(root).resolve()
  verify_envelope(base, "final_approval", "final_approval_receipt.json",
                  expected_receipt_sha256)
  receipt = load_json_strict(base / "final_approval_receipt.json")
  required_fields = {
      "schema_version", "contract_id", "run_id", "approved_plan_sha256",
      "approval_decision", "approval_authority", "approval_reference",
      "approval_timestamp", "execution_authorization_receipt_sha256",
      "generation_artifact_sha256", "verification_receipt_sha256",
      "verification_manifest_sha256", "verification_checksums_sha256",
      "standard_source_manifest_sha256", "sorted_job_ids_sha256",
      "standard_job_count", "standard_workload_count",
      "stage11_generation_verified", "stage11_final_approval_granted",
      "test_used_for_parameter_selection", "evidence_scope",
      "synthetic_test_only"}
  _require(set(receipt) == required_fields,
           "Final approval receipt contains missing or unknown fields.")
  _require(receipt.get("schema_version") ==
           "capd_proactive_stage11_v2_final_approval_receipt_v1_0" and
           receipt.get("contract_id") == CONTRACT_ID and
           receipt.get("approved_plan_sha256") == APPROVED_PLAN_SHA256 and
           receipt.get("approval_decision") == "approved_for_stage11_finalization" and
            receipt.get("stage11_generation_verified") is True and
            receipt.get("stage11_final_approval_granted") is True and
            receipt.get("standard_job_count") == 48 and
            receipt.get("standard_workload_count") == 6 and
            receipt.get("test_used_for_parameter_selection") is False,
            "Final approval receipt contract mismatch.")
  if expected is not None:
    allowed_bindings = (
        "run_id", "execution_authorization_receipt_sha256",
        "generation_artifact_sha256", "verification_receipt_sha256",
        "verification_manifest_sha256", "verification_checksums_sha256",
        "standard_source_manifest_sha256", "sorted_job_ids_sha256")
    _require(set(expected) <= set(allowed_bindings),
             "Unknown expected final-approval binding.")
    for field, value in expected.items():
      _require(receipt.get(field) == value,
               "Final approval binding mismatch: {}".format(field))
  return receipt


def build_synthetic_final_status(capability: Any,
                                 final_approval: Mapping[str, Any],
                                 final_approval_hashes: Mapping[str, str]
                                 ) -> Dict[str, str]:
  cap = path_guard.require_capability(capability)
  _require(final_approval.get("synthetic_test_only") is True and
           cap.mode == "synthetic", "Only synthetic final-status structure is allowed.")
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_final_status_evidence_receipt_v1_0",
      "contract_id": CONTRACT_ID, "run_id": final_approval["run_id"],
      "approved_plan_sha256": APPROVED_PLAN_SHA256,
      "status": "synthetic_final_status_structure",
      "execution_authorization_receipt_sha256":
          final_approval["execution_authorization_receipt_sha256"],
      "generation_artifact_sha256": final_approval["generation_artifact_sha256"],
      "verification_artifact_sha256": final_approval["verification_receipt_sha256"],
      "final_approval_receipt_sha256": final_approval_hashes["receipt_sha256"],
      "final_approval_manifest_sha256": final_approval_hashes["manifest_sha256"],
      "final_approval_checksums_sha256": final_approval_hashes["checksums_sha256"],
      "standard_source_manifest_sha256":
          final_approval["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": final_approval["sorted_job_ids_sha256"],
      "authorized_external_input": False,
      "stage11_execution_authorized": False,
      "stage11_generation_verified": True,
      "stage11_final_approval_verified": False,
      "stage11_final_status_evidence_verified": False,
      "stage11_formally_verified": False,
      "test_used_for_parameter_selection": False,
      "synthetic_test_only": True,
  }
  _atomic_json(cap, "final_status_evidence_receipt.json", receipt)
  _atomic_json(cap, "manifest.json", _manifest(cap.root, "final_status"))
  _atomic_text(cap, "SHA256SUMS", _checksums(cap.root))
  return {"receipt_sha256": sha256_file(cap.root / "final_status_evidence_receipt.json"),
          "manifest_sha256": sha256_file(cap.root / "manifest.json"),
          "checksums_sha256": sha256_file(cap.root / "SHA256SUMS")}


def consume_final_status(root: os.PathLike[str] | str,
                         expected_receipt_sha256: str,
                         *, expected: Mapping[str, Any] | None = None
                         ) -> Dict[str, Any]:
  base = Path(root).resolve()
  verify_envelope(base, "final_status", "final_status_evidence_receipt.json",
                  expected_receipt_sha256)
  receipt = load_json_strict(base / "final_status_evidence_receipt.json")
  required_fields = {
      "schema_version", "contract_id", "run_id", "approved_plan_sha256",
      "status", "execution_authorization_receipt_sha256",
      "generation_artifact_sha256", "verification_artifact_sha256",
      "final_approval_receipt_sha256", "final_approval_manifest_sha256",
      "final_approval_checksums_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256", "authorized_external_input",
      "stage11_execution_authorized", "stage11_generation_verified",
      "stage11_final_approval_verified", "stage11_final_status_evidence_verified",
      "stage11_formally_verified", "test_used_for_parameter_selection",
      "synthetic_test_only"}
  _require(isinstance(receipt, Mapping) and set(receipt) == required_fields and
           receipt.get("schema_version") ==
           "capd_proactive_stage11_v2_final_status_evidence_receipt_v1_0" and
           receipt.get("contract_id") == CONTRACT_ID and
           receipt.get("approved_plan_sha256") == APPROVED_PLAN_SHA256 and
           receipt.get("test_used_for_parameter_selection") is False,
           "Final-status receipt identity or exact field set mismatch.")
  sha_fields = {
      "execution_authorization_receipt_sha256",
      "generation_artifact_sha256", "verification_artifact_sha256",
      "final_approval_receipt_sha256", "final_approval_manifest_sha256",
      "final_approval_checksums_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256"}
  _require(isinstance(receipt.get("run_id"), str) and receipt["run_id"] and
           Path(receipt["run_id"]).name == receipt["run_id"] and
           all(_is_sha256(receipt.get(field)) for field in sha_fields),
           "Final-status run identity or SHA field format is invalid.")
  if receipt.get("synthetic_test_only") is True:
    _require(receipt.get("status") == "synthetic_final_status_structure" and
             receipt.get("authorized_external_input") is False and
             receipt.get("stage11_execution_authorized") is False and
             receipt.get("stage11_generation_verified") is True and
             receipt.get("stage11_final_approval_verified") is False and
             receipt.get("stage11_final_status_evidence_verified") is False and
             receipt.get("stage11_formally_verified") is False,
             "Synthetic final-status receipt exceeds its capability boundary.")
    return {"status": "BLOCKED", "reason_code": "synthetic_test_only",
            "stage11_formally_verified": False}
  binding_fields = {
      "run_id", "execution_authorization_receipt_sha256",
      "generation_artifact_sha256", "verification_artifact_sha256",
      "final_approval_receipt_sha256", "final_approval_manifest_sha256",
      "final_approval_checksums_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256"}
  _require(isinstance(expected, Mapping) and set(expected) == binding_fields,
           "Formal final-status consumption requires every external binding.")
  _require(all(receipt.get(field) == value for field, value in expected.items()),
           "Final-status upstream or run identity binding mismatch.")
  required_true = (
      "authorized_external_input", "stage11_execution_authorized",
      "stage11_generation_verified", "stage11_final_approval_verified",
      "stage11_final_status_evidence_verified", "stage11_formally_verified")
  _require(receipt.get("status") == "stage11_formally_verified" and
           receipt.get("synthetic_test_only") is False and
           all(receipt.get(key) is True for key in required_true),
           "Final status does not satisfy the formal contract.")
  return {"status": "verified", "stage11_formally_verified": True}
