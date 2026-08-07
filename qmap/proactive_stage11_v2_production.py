"""Stage11 v2 production contracts; real execution stays receipt-gated."""

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

from qmap import proactive_cost
from qmap import proactive_stage11_v2_production_guard as production_guard


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11-2.0"
PRODUCTION_REVISION = "stage11-v2-production-r3"
RUN_ID = "stage11-standard-cost-profiles-v2-r3"
AUDIT_ID = "stage11-input-audit-v2-r4"
APPROVED_DESIGN_SHA256 = (
    "ec00fdaeac4084f638fbf6da866d4444badd26dfac95eef061e137a5a26ba356")
APPROVED_PLAN_SHA256 = (
    "5ada02d3cd2f14c116dccbf4336dc833c460c3d7198e58eb17efd72f0bc66143")
PRODUCTION_ROOT = "outputs/capd_proactive_stage11_v2"

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
GENERATION_PAYLOADS = frozenset(
    production_guard.PHASE_ARTIFACTS["generation"] - {"manifest.json", "SHA256SUMS"})

MONITORING_CONTRACT = {
    "monitor_interval_seconds": 5,
    "hard_timeout_seconds": 1800,
    "termination_grace_seconds": 10,
    "attempt_count": 1,
    "automatic_retry_performed": False,
}

STAGE10_RUN_ID = "stage10-async-simulator-v2-r2"
STAGE10_GENERATION_ARTIFACTS = frozenset({
    "config.json", "event_model.md", "execution_environment.json",
    "generation_freeze_receipt.json", "generation_source_manifest.json",
    "generation_test_evidence.json", "generation_test_log.txt", "parameters.md",
    "README.md", "report.md", "run_identity.json", "run_state.json",
    "scenario_matrix.json", "simulation_results.jsonl", "stage9_input_receipt.json",
    "timing_provenance.json", "verification.json", "manifest.json", "SHA256SUMS"})
STAGE10_READINESS_ARTIFACTS = frozenset({
    "release_readiness_test_log.txt", "release_test_source_snapshot.py",
    "protocol_pending_snapshot.md", "status_pending_snapshot.md",
    "release_readiness_test_evidence.json", "stage11_negative_audit_log.txt",
    "stage11_negative_audit_source_snapshot.json",
    "stage11_negative_audit_result.json", "stage11_negative_audit_evidence.json",
    "release_readiness_receipt.json", "manifest.json", "SHA256SUMS"})
STAGE10_FINAL_ARTIFACTS = frozenset({
    "final_status_test_log.txt", "release_test_source_snapshot.py",
    "protocol_final_snapshot.md", "status_final_snapshot.md",
    "final_status_test_evidence.json", "final_status_evidence_receipt.json",
    "manifest.json", "SHA256SUMS"})


class ProductionContractError(ValueError):
  pass


class ProductionBlocked(ProductionContractError):
  pass


class ProductionNotVerifiable(ProductionContractError):
  pass


def _require(condition: object, message: str,
             error_type: type[ProductionContractError] = ProductionContractError
             ) -> None:
  if not condition:
    raise error_type(message)


def _duplicate_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
  result: dict[str, Any] = {}
  for key, value in pairs:
    _require(key not in result, "Duplicate JSON key: {}".format(key))
    result[key] = value
  return result


def _non_finite(value: str) -> None:
  raise ProductionContractError("Non-finite JSON value: {}".format(value))


def load_json_strict(path: os.PathLike[str] | str) -> Any:
  try:
    raw = Path(path).read_bytes()
    _require(not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM is forbidden.")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_object,
                      parse_constant=_non_finite)
  except ProductionContractError:
    raise
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise ProductionContractError(
        "Cannot load strict JSON {}: {}".format(path, exc)) from exc


def _assert_finite(value: Any) -> None:
  if isinstance(value, Mapping):
    for item in value.values():
      _assert_finite(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      _assert_finite(item)
  elif isinstance(value, float):
    _require(math.isfinite(value), "Non-finite values are forbidden.")


def canonical_json_bytes(value: Any) -> bytes:
  _assert_finite(value)
  return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def is_canonical_json_bytes(raw: bytes) -> bool:
  try:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_object,
                       parse_constant=_non_finite)
  except (UnicodeError, json.JSONDecodeError, ProductionContractError):
    return False
  return raw == canonical_json_bytes(value)


def sha256_bytes(raw: bytes) -> str:
  return hashlib.sha256(raw).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def sha256_value(value: Any) -> str:
  return sha256_bytes(canonical_json_bytes(value))


def stage8_fingerprint_value(value: Any) -> str:
  """Match Stage8's semantic fingerprint, which excludes a trailing LF."""
  _assert_finite(value)
  raw = json.dumps(
      value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
      allow_nan=False).encode("utf-8")
  return sha256_bytes(raw)


def validate_external_sha(path: os.PathLike[str] | str, expected: str) -> str:
  _require(isinstance(expected, str) and len(expected) == 64,
           "Explicit external SHA256 is required.", ProductionNotVerifiable)
  actual = sha256_file(path)
  _require(actual == expected, "External SHA256 mismatch.",
           ProductionNotVerifiable)
  return actual


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], label: str) -> None:
  _require(isinstance(value, Mapping) and set(value) == set(expected),
           "{} field set mismatch.".format(label))


def _canonical_relative(path: str) -> bool:
  pure = PurePosixPath(path)
  return (isinstance(path, str) and path == pure.as_posix() and
          not pure.is_absolute() and ".." not in pure.parts and path not in ("", "."))


def validate_config(config: Mapping[str, Any], *,
                    externally_approved_plan_sha256: str) -> Mapping[str, Any]:
  expected = {
      "schema_version", "contract_id", "production_revision", "run_id",
      "approved_production_design", "approved_production_plan", "upstream",
      "stage10_external_anchors", "input_audit", "source_manifests",
      "standard_contract", "cost_profiles", "cost_semantics", "main_control",
      "authorized_scope", "expected_result_rows", "blocked_lanes", "output_root",
      "production_branch_available", "test_used_for_parameter_selection"}
  _exact_keys(config, expected, "Production config")
  _require(config["schema_version"] ==
           "capd_proactive_stage11_v2_production_config_v1_0" and
           config["contract_id"] == CONTRACT_ID and
           config["production_revision"] == PRODUCTION_REVISION and
           config["run_id"] == RUN_ID, "Production config identity mismatch.")
  design = config["approved_production_design"]
  plan = config["approved_production_plan"]
  _require(design == {
      "path": "docs/superpowers/specs/2026-08-07-stage11-production-enablement-design.md",
      "sha256": APPROVED_DESIGN_SHA256, "required_status": "DESIGN_APPROVED"},
      "Approved production design binding mismatch.")
  _require(plan == {
      "path": "docs/superpowers/plans/2026-08-07-stage11-production-enablement.md",
      "sha256": APPROVED_PLAN_SHA256, "required_status": "PLAN_APPROVED"},
      "Approved production plan binding mismatch.")
  _require(externally_approved_plan_sha256 == APPROVED_PLAN_SHA256,
           "Missing or wrong externally approved plan SHA.",
           ProductionNotVerifiable)
  _require(config["cost_profiles"] == PROFILE_WEIGHTS,
           "Frozen Cost profiles changed.")
  _require(config["cost_semantics"] == {
      "nvm_write": "NVM write access cost",
      "demotion": "DRAM to NVM migration cost"}, "Cost semantics changed.")
  _require(config["main_control"] == {"b_max": 2},
           "Formal main b_max must remain 2.")
  _require(config["expected_result_rows"] == 192 and
           config["authorized_scope"] == "offline_cost_profiles_only",
           "Production scope or row count changed.")
  _require(tuple(config["blocked_lanes"]) == BLOCKED_LANES,
           "Blocked lane set changed.")
  _require(config["production_branch_available"] is True and
           config["test_used_for_parameter_selection"] is False,
           "Production branch metadata exceeds authorization.")
  standard = config["standard_contract"]
  _require(standard.get("job_count") == 48 and
           standard.get("workload_count") == 6 and
           tuple(standard.get("workloads", ())) == STANDARD_WORKLOADS and
           tuple((item.get("policy"), item.get("seed"))
                 for item in standard.get("members_per_workload", ())) ==
           STANDARD_MEMBERS, "Standard membership contract changed.")
  _require(config["source_manifests"] == {
      "generation": "configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest.json",
      "verifier": "configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest.json"},
      "Production source manifest paths changed.")
  _require(config["input_audit"] == {
      "audit_id": AUDIT_ID,
      "package_root": PRODUCTION_ROOT + "/input_audits/" + AUDIT_ID,
      "receipt_schema":
          "configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json"},
      "Input-audit revision contract changed.")
  _require(config["output_root"] == PRODUCTION_ROOT,
           "Production output root changed.")
  return config


def validate_approved_documents(project_root: os.PathLike[str] | str,
                                config: Mapping[str, Any]) -> dict[str, str]:
  root = Path(project_root).resolve()
  result = {}
  for key, status_label in (("approved_production_design", "Design Status"),
                            ("approved_production_plan", "Plan Status")):
    item = config[key]
    path = (root / item["path"]).resolve()
    _require(path.is_relative_to(root) and path.is_file(),
             "Approved document path is invalid.", ProductionNotVerifiable)
    actual = validate_external_sha(path, item["sha256"])
    text = path.read_text(encoding="utf-8")
    _require("- {}: `{}`".format(status_label, item["required_status"]) in text,
             "Approved document state mismatch.", ProductionNotVerifiable)
    result[key + "_sha256"] = actual
  return result


def file_records(project_root: os.PathLike[str] | str,
                 paths: Sequence[str]) -> list[dict[str, Any]]:
  root = Path(project_root).resolve()
  _require(tuple(paths) == tuple(sorted(set(paths))),
           "Source path whitelist must be sorted and unique.")
  records = []
  for relative in paths:
    _require(_canonical_relative(relative), "Non-canonical source path.")
    path = (root / relative).resolve()
    _require(path.is_relative_to(root) and path.is_file(),
             "Source member missing: {}".format(relative),
             ProductionNotVerifiable)
    records.append({"path": relative, "length": path.stat().st_size,
                    "sha256": sha256_file(path)})
  return records


def source_snapshot(project_root: os.PathLike[str] | str,
                    paths: Sequence[str]) -> dict[str, Any]:
  records = file_records(project_root, paths)
  return {"members": records, "member_count": len(records),
          "members_sha256": sha256_value(records)}


def generation_source_manifest_value(project_root: os.PathLike[str] | str
                                     ) -> dict[str, Any]:
  snapshot = source_snapshot(project_root, GENERATION_SOURCE_PATHS)
  return {
      "schema_version": "capd_proactive_stage11_v2_production_source_manifest_v1_0",
      "contract_id": CONTRACT_ID, "role": "generation",
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "members": snapshot["members"], "member_count": 30,
      "members_sha256": snapshot["members_sha256"],
      "local_import_closure_complete": True,
      "exclusions": ["docs", "tests", "fixtures", "outputs", "receipts",
                     "logs", "__pycache__", "runtime_status"],
  }


def validate_generation_source_manifest(
    project_root: os.PathLike[str] | str,
    sealed: Mapping[str, Any]) -> Mapping[str, Any]:
  expected = generation_source_manifest_value(project_root)
  _require(sealed == expected,
           "Generation source manifest differs from the exact current closure.",
           ProductionNotVerifiable)
  forbidden = {
      "qmap/proactive_stage11_v2.py", "qmap/proactive_stage11_v2_guard.py",
      "qmap/proactive_stage11_v2_verifier.py",
      "scripts/run_capd_proactive_stage11_v2.py",
      "scripts/verify_capd_proactive_stage11_v2.py"}
  validate_local_import_closure(
      project_root, GENERATION_SOURCE_PATHS, forbidden=forbidden)
  return sealed


def validate_sealed_source_manifest_current_bytes(
    project_root: os.PathLike[str] | str, sealed: Mapping[str, Any], *,
    role: str, expected_count: int) -> Mapping[str, Any]:
  expected_fields = {
      "schema_version", "contract_id", "role",
      "approved_production_design_sha256", "approved_production_plan_sha256",
      "members", "member_count", "members_sha256",
      "local_import_closure_complete", "exclusions"}
  _exact_keys(sealed, expected_fields, "Production source manifest")
  _require(sealed["schema_version"] ==
           "capd_proactive_stage11_v2_production_source_manifest_v1_0" and
           sealed["contract_id"] == CONTRACT_ID and sealed["role"] == role and
           sealed["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           sealed["approved_production_plan_sha256"] == APPROVED_PLAN_SHA256 and
           sealed["member_count"] == expected_count and
           sealed["local_import_closure_complete"] is True,
           "Production source manifest identity mismatch.",
           ProductionNotVerifiable)
  members = sealed["members"]
  paths = [item.get("path") for item in members]
  _require(len(members) == len(set(paths)) == expected_count and
           paths == sorted(paths) and sealed["members_sha256"] ==
           sha256_value(members), "Production source member identity mismatch.",
           ProductionNotVerifiable)
  root = Path(project_root).resolve()
  for item in members:
    _exact_keys(item, {"path", "length", "sha256"}, "Source member")
    _require(_canonical_relative(item["path"]), "Source path is non-canonical.")
    path = (root / item["path"]).resolve()
    _require(path.is_relative_to(root) and path.is_file() and
             path.stat().st_size == item["length"] and
             sha256_file(path) == item["sha256"],
             "Source member bytes changed: {}".format(item["path"]),
             ProductionNotVerifiable)
  return sealed


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
                                  forbidden: Iterable[str] = ()) -> set[str]:
  root = Path(project_root).resolve()
  members = set(paths)
  imports = set()
  for relative in paths:
    if relative.endswith(".py"):
      imports.update(_local_imports(root / relative))
  local_imports = {item for item in imports if (root / item).is_file()}
  _require(local_imports <= members,
           "Source whitelist omits imports: {}".format(
               sorted(local_imports - members)), ProductionNotVerifiable)
  _require(not (set(forbidden) & local_imports),
           "Production source imports a forbidden historical contract.",
           ProductionNotVerifiable)
  return local_imports


def test_source_identity(project_root: os.PathLike[str] | str,
                         pre_snapshot: Mapping[str, Any],
                         post_snapshot: Mapping[str, Any]) -> dict[str, Any]:
  _require(tuple(TEST_SOURCE_PATHS) == tuple(sorted(TEST_SOURCE_PATHS)) and
           len(TEST_SOURCE_PATHS) == len(set(TEST_SOURCE_PATHS)) == 29,
           "Frozen test-source whitelist identity changed.")
  expected_pre = source_snapshot(project_root, TEST_SOURCE_PATHS)
  _require(pre_snapshot == expected_pre and post_snapshot == expected_pre,
           "Test source changed or supplied snapshot is stale.",
           ProductionNotVerifiable)
  return {
      "schema_version": "capd_proactive_stage11_v2_test_source_identity_v1_0",
      "contract_id": CONTRACT_ID, "audit_id": AUDIT_ID,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "members": copy.deepcopy(expected_pre["members"]),
      "members_sha256": expected_pre["members_sha256"],
      "member_count": 29,
      "test_source_pre_snapshot_sha256": sha256_value(pre_snapshot),
      "test_source_post_snapshot_sha256": sha256_value(post_snapshot),
      "test_sources_unchanged": True,
  }


def frozen_tree_snapshot(project_root: os.PathLike[str] | str,
                         roots: Sequence[tuple[str, str]] = FROZEN_TREE_PATHS
                         ) -> dict[str, Any]:
  _require(tuple(roots) == tuple(sorted(roots)) and len(roots) == 5 and
           len({item[0] for item in roots}) == 5,
           "Frozen tree roots must be the exact sorted five-root set.")
  project = Path(project_root).resolve()
  root_rows = []
  for root_id, relative_root in roots:
    _require(_canonical_relative(relative_root), "Frozen root path is invalid.")
    path = (project / relative_root).resolve()
    _require(path.is_relative_to(project), "Frozen root escapes repository.")
    members = []
    exists = path.is_dir()
    if exists:
      for member in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = member.relative_to(path).as_posix()
        members.append({"path": relative, "length": member.stat().st_size,
                        "sha256": sha256_file(member)})
    root_rows.append({"root_id": root_id,
                      "repository_relative_root": relative_root,
                      "exists": exists, "members": members})
  return {"schema_version":
          "capd_proactive_stage11_v2_frozen_tree_snapshot_v1_0",
          "contract_id": CONTRACT_ID, "roots": root_rows}


def compare_frozen_snapshots(baseline: Mapping[str, Any],
                             observations: Sequence[tuple[str, Mapping[str, Any]]]
                             ) -> dict[str, Any]:
  _require(1 <= len(observations) <= 2, "One or two observations are required.")
  baseline_sha = sha256_value(baseline)
  baseline_roots = {item["root_id"]: item for item in baseline.get("roots", [])}
  comparisons = []
  all_identical = True
  for comparison_id, observed in observations:
    observed_roots = {item["root_id"]: item for item in observed.get("roots", [])}
    _require(set(observed_roots) == set(baseline_roots) and
             len(observed.get("roots", [])) == 5,
             "Frozen tree root identity mismatch.")
    per_root = []
    identical = baseline == observed
    for root_id in sorted(baseline_roots):
      before = baseline_roots[root_id]
      after = observed_roots[root_id]
      per_root.append({
          "root_id": root_id,
          "baseline_record_count": len(before["members"]),
          "observed_record_count": len(after["members"]),
          "identical": before == after})
    comparisons.append({
        "comparison_id": comparison_id,
        "baseline_snapshot_sha256": baseline_sha,
        "observed_snapshot_sha256": sha256_value(observed),
        "per_root_comparison": per_root, "identical": identical})
    all_identical = all_identical and identical
  return {"schema_version":
          "capd_proactive_stage11_v2_upstream_continuity_comparison_v1_0",
          "contract_id": CONTRACT_ID, "comparisons": comparisons,
          "identical": all_identical}


def assert_continuity(baseline: Mapping[str, Any],
                      observed: Mapping[str, Any], comparison_id: str) -> dict[str, Any]:
  comparison = compare_frozen_snapshots(baseline, [(comparison_id, observed)])
  _require(comparison["identical"], "Frozen upstream continuity changed.",
           ProductionNotVerifiable)
  return comparison


def build_manifest(phase: str, payloads: Mapping[str, bytes]) -> dict[str, Any]:
  _require(phase in production_guard.PHASES, "Unknown package phase.")
  _require("manifest.json" not in payloads and "SHA256SUMS" not in payloads,
           "Recursive manifest/checksum members are forbidden.")
  _require(set(payloads) == set(sorted(payloads)) and
           all(_canonical_relative(path) and len(PurePosixPath(path).parts) == 1
               for path in payloads), "Package member set is not canonical.")
  members = [{"path": path, "length": len(payloads[path]),
              "sha256": sha256_bytes(payloads[path])}
             for path in sorted(payloads)]
  return {
      "schema_version": "capd_proactive_stage11_v2_production_package_manifest_v1_0",
      "contract_id": CONTRACT_ID, "phase": phase, "members": members,
      "member_count": len(members), "members_sha256": sha256_value(members)}


def checksum_bytes(payloads: Mapping[str, bytes], manifest_raw: bytes) -> bytes:
  entries = dict(payloads)
  entries["manifest.json"] = manifest_raw
  lines = ["{}  {}".format(sha256_bytes(entries[path]), path)
           for path in sorted(entries)]
  return ("\n".join(lines) + "\n").encode("ascii")


def seal_package_bytes(phase: str, payloads: Mapping[str, bytes]) -> dict[str, bytes]:
  manifest = build_manifest(phase, payloads)
  manifest_raw = canonical_json_bytes(manifest)
  result = dict(payloads)
  result["manifest.json"] = manifest_raw
  result["SHA256SUMS"] = checksum_bytes(payloads, manifest_raw)
  return result


def validate_package_bytes(package: Mapping[str, bytes], *, phase: str,
                           expected_members: Iterable[str]) -> dict[str, Any]:
  expected = set(expected_members) | {"manifest.json", "SHA256SUMS"}
  _require(set(package) == expected, "Package exact member set mismatch.",
           ProductionNotVerifiable)
  _require(is_canonical_json_bytes(package["manifest.json"]),
           "Manifest is not canonical JSON.", ProductionNotVerifiable)
  manifest = json.loads(package["manifest.json"].decode("utf-8"))
  payloads = {name: package[name] for name in expected_members}
  _require(manifest == build_manifest(phase, payloads),
           "Package manifest does not match payload bytes.",
           ProductionNotVerifiable)
  _require(package["SHA256SUMS"] == checksum_bytes(payloads, package["manifest.json"]),
           "Package checksums do not match.", ProductionNotVerifiable)
  return manifest


def canonical_upstream_objects(stage8: Mapping[str, Any],
                               stage9: Mapping[str, Any],
                               stage10: Mapping[str, Any],
                               standard_manifest: Mapping[str, Any]
                               ) -> dict[str, bytes]:
  objects = {
      "stage8_standard_input_receipt.json": stage8,
      "stage9_input_receipt.json": stage9,
      "stage10_input_receipt.json": stage10,
      "standard_source_manifest.json": standard_manifest,
  }
  return {name: canonical_json_bytes(value) for name, value in objects.items()}


def compare_rebuilt_upstream_objects(sealed: Mapping[str, bytes],
                                     rebuilt: Mapping[str, bytes]) -> None:
  expected = {
      "stage8_standard_input_receipt.json", "stage9_input_receipt.json",
      "stage10_input_receipt.json", "standard_source_manifest.json"}
  _require(set(sealed) == expected and set(rebuilt) == expected,
           "Canonical upstream object set mismatch.", ProductionNotVerifiable)
  for name in sorted(expected):
    _require(is_canonical_json_bytes(sealed[name]),
             "Sealed upstream object is not canonical: {}".format(name),
             ProductionNotVerifiable)
    _require(sealed[name] == rebuilt[name],
             "Independent upstream rebuild differs: {}".format(name),
             ProductionNotVerifiable)


def _input_receipt(stage: str, status: str, **fields: Any) -> dict[str, Any]:
  value = {
      "schema_version": "capd_proactive_stage11_v2_{}_input_receipt_v1_0".format(stage),
      "contract_id": CONTRACT_ID, "stage": stage, "status": status,
      "authorized_external_input": status == "verified",
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False,
      "synthetic_test_only": False}
  value.update(fields)
  return value


def audit_stage9(stage9_root: os.PathLike[str] | str,
                 schema_path: os.PathLike[str] | str) -> dict[str, Any]:
  root = Path(stage9_root).resolve()
  try:
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
             verification.get("status") == "stage9_overhead_verified",
             "Stage9 verified state is absent.")
    for key, expected in schema.get("verification_required", {}).items():
      _require(verification.get(key) == expected,
               "Stage9 verification mismatch: {}".format(key))
    artifacts = [name for name in required
                 if name not in ("verification.json", "run_state.json")]
    hashes = verification.get("artifact_sha256")
    _require(isinstance(hashes, Mapping) and set(hashes) == set(artifacts),
             "Stage9 artifact SHA key set mismatch.")
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
             "Stage9 Stage8 compatibility receipt failed.")
    _require(environment.get("system") == "Linux" and
             environment.get("device") == "cpu" and
             isinstance(environment.get("linux_kernel"), str),
             "Stage9 Linux CPU evidence is missing.")
    perf = load_json_strict(root / "perf" / "perf_parsed.json")
    events = perf.get("events", {})
    _require(perf.get("counter_source") == schema.get("perf_counter_source") and
             perf.get("required_events_verified") is True and
             perf.get("cycles_verified") is True,
             "Stage9 perf evidence is incomplete.")
    for event in schema.get("perf_required_events", []):
      row = events.get(event, {})
      _require(row.get("status") == "ok" and
               isinstance(row.get("value"), (int, float)) and
               not isinstance(row.get("value"), bool) and row["value"] > 0,
               "Stage9 perf event is invalid: {}".format(event))
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
    _require(all(field in memory for field in
                 schema.get("memory_required_fields", [])) and
             all(field in rss for field in
                 schema.get("memory_rss_required_fields", [])) and
             isinstance(rss.get("process_baseline_rss_bytes"), int) and
             isinstance(rss.get("total_peak_rss_bytes"), int) and
             rss["total_peak_rss_bytes"] >= rss["process_baseline_rss_bytes"] and
             rss.get("stage9_incremental_peak_rss_bytes") ==
             rss["total_peak_rss_bytes"] - rss["process_baseline_rss_bytes"],
             "Stage9 RSS evidence is invalid.")
    with (root / "raw_latency_samples.csv").open(
        "r", encoding="utf-8", newline="") as handle:
      reader = csv.DictReader(handle)
      rows = list(reader)
      fields = set(reader.fieldnames or ())
    _require(set(schema.get("raw_latency_required_fields", [])) <= fields and rows,
             "Stage9 raw latency evidence is incomplete.")
    return _input_receipt(
        "stage9", "verified", run_state_sha256=sha256_file(root / "run_state.json"),
        verification_sha256=sha256_file(root / "verification.json"),
        stage8_compatibility_receipt_sha256=sha256_file(
            root / "stage8_compatibility_receipt.json"),
        artifact_verified_count=len(artifacts),
        test_used_for_parameter_selection=False)
  except Exception as exc:
    return _input_receipt(
        "stage9", "NOT_VERIFIABLE", reason_code="invalid_stage9_input",
        detail=str(exc), run_state_sha256=None, verification_sha256=None,
        stage8_compatibility_receipt_sha256=None,
        test_used_for_parameter_selection=False)


def _relative_files(root: Path) -> list[tuple[str, Path]]:
  return sorted((path.relative_to(root).as_posix(), path)
                for path in root.rglob("*") if path.is_file())


def _verify_stage10_envelope(base: Path, *, phase: str,
                             exact_artifacts: frozenset[str]) -> dict[str, str]:
  names = {name for name, _ in _relative_files(base)}
  _require(names == set(exact_artifacts),
           "Stage10 {} artifact set mismatch.".format(phase))
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
           "Stage10 manifest payload set mismatch.")
  for name, expected in manifest["files"].items():
    _require(re.fullmatch(r"[0-9a-f]{64}", str(expected)) and
             sha256_file(base / name) == expected,
             "Stage10 manifest SHA mismatch: {}".format(name))
  checksum_rows = []
  with (base / "SHA256SUMS").open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        parts = line.rstrip("\n").split("  ", 1)
        _require(len(parts) == 2, "Stage10 checksum line is malformed.")
        checksum_rows.append((parts[0], parts[1]))
  _require(len(checksum_rows) == len({name for _, name in checksum_rows}) and
           {name for _, name in checksum_rows} == names - {"SHA256SUMS"},
           "Stage10 checksum member set mismatch.")
  for expected, name in checksum_rows:
    _require(sha256_file(base / name) == expected,
             "Stage10 checksum mismatch: {}".format(name))
  return {"manifest_sha256": sha256_file(base / "manifest.json"),
          "checksums_sha256": sha256_file(base / "SHA256SUMS")}


def audit_stage10(stage10_root: os.PathLike[str] | str,
                  anchors: Mapping[str, str]) -> dict[str, Any]:
  base = Path(stage10_root).resolve()
  try:
    generation = _verify_stage10_envelope(
        base, phase="generation", exact_artifacts=STAGE10_GENERATION_ARTIFACTS)
    identity = load_json_strict(base / "run_identity.json")
    state = load_json_strict(base / "run_state.json")
    verification = load_json_strict(base / "verification.json")
    _require(identity.get("contract_id") == "CAPD-PROACTIVE-STAGE10-2.0" and
             identity.get("run_id") == STAGE10_RUN_ID and
             identity.get("evidence_mode") == "deterministic_async_simulation" and
             state.get("status") == "stage10_async_simulation_verified" and
             state.get("artifacts_independently_verified") is True and
             state.get("simulation_executed") is True and
             state.get("stage9_input_gate_passed") is True and
             state.get("real_system_async_performance_verified") is False and
             verification.get("status") == "stage10_async_simulation_verified" and
             verification.get("artifacts_independently_recomputed") is True and
             verification.get("current_generation_sources_recomputed") is True and
             verification.get("generation_tests_verified") is True and
             verification.get("stage9_input_gate") == "satisfied" and
             verification.get("result_count") == 60,
             "Stage10 sealed generation state is invalid.")
    for flag in (
        "real_nvm_measurement_verified", "kernel_behavior_verified",
        "real_concurrency_verified", "real_foreground_end_to_end_latency_verified",
        "real_system_async_performance_verified"):
      _require(verification.get(flag) is False,
               "Stage10 capability boundary changed: {}".format(flag))
    matrix = load_json_strict(base / "scenario_matrix.json")
    matrix_rows = matrix.get("scenarios") if isinstance(matrix, Mapping) else matrix
    matrix_ids = [row.get("scenario_id") for row in matrix_rows]
    result_ids = []
    with (base / "simulation_results.jsonl").open("r", encoding="utf-8") as handle:
      for line in handle:
        if line.strip():
          result_ids.append(json.loads(line).get("scenario_id"))
    _require(len(matrix_ids) == len(set(matrix_ids)) == 60 and
             result_ids == matrix_ids and verification.get("scenario_ids") == matrix_ids,
             "Stage10 scenario identity mismatch.")
    source = load_json_strict(base / "generation_source_manifest.json")
    entries = source.get("entries")
    _require(source.get("schema_version") ==
             "capd_proactive_stage10_generation_source_manifest_v1_0" and
             source.get("source_set_id") == "stage10-v2-r2-generation-core-v1" and
             isinstance(entries, list) and len(entries) == 11,
             "Stage10 generation source identity mismatch.")
    source_match = True
    for entry in entries:
      path = (Path(__file__).resolve().parents[1] / entry.get("path", "")).resolve()
      if (not path.is_file() or
          sha256_file(path) != entry.get("sha256")):
        source_match = False
    freeze_path = base / "generation_freeze_receipt.json"
    validate_external_sha(freeze_path, anchors.get("generation_freeze_receipt_sha256"))
    freeze_sha = sha256_file(freeze_path)
    _require(identity.get("generation_freeze_receipt_sha256") == freeze_sha and
             verification.get("approved_freeze_receipt_sha256") == freeze_sha,
             "Stage10 freeze receipt binding mismatch.")
    release_root = base.parent / "release_receipts" / STAGE10_RUN_ID
    readiness_root = release_root / "readiness"
    final_root = release_root / "final-status"
    readiness_envelope = _verify_stage10_envelope(
        readiness_root, phase="readiness",
        exact_artifacts=STAGE10_READINESS_ARTIFACTS)
    final_envelope = _verify_stage10_envelope(
        final_root, phase="final_status", exact_artifacts=STAGE10_FINAL_ARTIFACTS)
    validate_external_sha(
        readiness_root / "release_readiness_receipt.json",
        anchors.get("readiness_receipt_sha256"))
    validate_external_sha(
        final_root / "final_status_evidence_receipt.json",
        anchors.get("final_status_receipt_sha256"))
    readiness = load_json_strict(readiness_root / "release_readiness_receipt.json")
    final = load_json_strict(final_root / "final_status_evidence_receipt.json")
    _require(readiness.get("release_status") ==
             "stage10_release_readiness_verified" and
             readiness.get("stage11_positive_migration_authorized") is False and
             readiness.get("real_system_async_performance_verified") is False and
             readiness.get("synthetic_test_only") is False and
             final.get("status") == "stage10_final_status_evidence_verified" and
             final.get("real_system_async_performance_verified") is False and
             final.get("synthetic_test_only") is False and
             final.get("readiness_manifest_sha256") ==
             readiness_envelope["manifest_sha256"] and
             final.get("readiness_checksums_sha256") ==
             readiness_envelope["checksums_sha256"],
             "Stage10 sealed dual-verifier attestation failed.")
    revision = code_version(Path(__file__).resolve().parents[1]).get("commit")
    sealed_revision = identity.get("git", {}).get("commit")
    return _input_receipt(
        "stage10", "verified", stage10_contract_id="CAPD-PROACTIVE-STAGE10-2.0",
        run_id=STAGE10_RUN_ID, artifact_integrity="verified",
        sealed_dual_verifier_attestation="verified",
        generation_source_set_match=source_match,
        repository_revision_match=revision == sealed_revision,
        current_live_replay_compatibility="NOT_VERIFIABLE",
        generation_manifest_sha256=generation["manifest_sha256"],
        readiness_manifest_sha256=readiness_envelope["manifest_sha256"],
        final_status_manifest_sha256=final_envelope["manifest_sha256"],
        test_used_for_parameter_selection=False)
  except Exception as exc:
    return _input_receipt(
        "stage10", "NOT_VERIFIABLE", reason_code="invalid_stage10_input",
        detail=str(exc), test_used_for_parameter_selection=False)


def validate_test_log_identity(log: Mapping[str, Any], expected_ids: Sequence[str],
                               expected_count: int) -> None:
  _exact_keys(log, {"test_ids", "tests_run", "result", "exit_code",
                    "timed_out", "automatic_retry_performed"}, "Test log")
  _require(tuple(log["test_ids"]) == tuple(expected_ids) and
           log["tests_run"] == expected_count and log["result"] == "OK" and
           log["exit_code"] == 0 and log["timed_out"] is False and
           log["automatic_retry_performed"] is False,
           "Test log identity or execution status mismatch.",
           ProductionNotVerifiable)


def build_input_audit_package(
    *, project_root: os.PathLike[str] | str, config: Mapping[str, Any],
    stage8_source: Mapping[str, Any], stage9_receipt: Mapping[str, Any],
    stage10_receipt: Mapping[str, Any],
    generation_source_manifest: Mapping[str, Any],
    verifier_source_manifest: Mapping[str, Any],
    test_identity: Mapping[str, Any], audit_commands: Mapping[str, Any],
    synthetic_log: bytes, production_log: bytes, legacy_log: bytes,
    audit_stdout: Mapping[str, Any], frozen_before: Mapping[str, Any],
    frozen_after: Mapping[str, Any]) -> dict[str, bytes]:
  _require(stage9_receipt.get("status") == "verified" and
           stage9_receipt.get("authorized_external_input") is True and
           stage10_receipt.get("status") == "verified" and
           stage10_receipt.get("authorized_external_input") is True,
           "Input audit cannot seal failed Stage9/Stage10 gates.",
           ProductionNotVerifiable)
  required_stdout = {
      "real_upstream_audit": "COMPLETED", "stage8_input_verified": True,
      "stage9_input_authorized": True, "stage10_input_authorized": True,
      "generation_source_manifest_verified": True,
      "verifier_source_manifest_verified": True,
      "generation_source_set_match": True,
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "stage11_execution_authorized": False, "stage11_formally_verified": False}
  _require(set(audit_stdout) == set(required_stdout) | {"repository_revision_match"} and
           all(audit_stdout[key] == value for key, value in required_stdout.items()) and
           isinstance(audit_stdout["repository_revision_match"], bool),
           "Real-upstream audit stdout contract mismatch.",
           ProductionNotVerifiable)
  tree_comparison = compare_frozen_snapshots(
      frozen_before, [("audit_before_vs_after", frozen_after)])
  _require(tree_comparison["identical"], "Input-audit frozen trees changed.",
           ProductionNotVerifiable)
  _require(test_identity.get("member_count") == 29 and
           test_identity.get("test_sources_unchanged") is True,
           "Test-source identity is incomplete.", ProductionNotVerifiable)
  _require(generation_source_manifest.get("member_count") == 30 and
           verifier_source_manifest.get("member_count") == 32,
           "Production source identity counts differ.", ProductionNotVerifiable)
  canonical = canonical_upstream_objects(
      stage8_source["receipt"], stage9_receipt, stage10_receipt,
      stage8_source["manifest"])
  source_identity = {
      "schema_version": "capd_proactive_stage11_v2_source_identity_v1_0",
      "contract_id": CONTRACT_ID,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "production_config_sha256": sha256_file(
          Path(project_root) /
          "configs/finals/capd_proactive_stage11_v2_production.json"),
      "production_result_schema_sha256": sha256_file(
          Path(project_root) /
          "configs/finals/capd_proactive_stage11_v2_production_result_schema.json"),
      "generation_source_manifest_path":
          config["source_manifests"]["generation"],
      "generation_source_manifest_sha256": sha256_file(
          Path(project_root) / config["source_manifests"]["generation"]),
      "generation_source_members_sha256":
          generation_source_manifest["members_sha256"],
      "generation_source_member_count": 30,
      "verifier_source_manifest_path": config["source_manifests"]["verifier"],
      "verifier_source_manifest_sha256": sha256_file(
          Path(project_root) / config["source_manifests"]["verifier"]),
      "verifier_source_members_sha256": verifier_source_manifest["members_sha256"],
      "verifier_source_member_count": 32,
      "source_pre_snapshot_sha256": test_identity["test_source_pre_snapshot_sha256"],
      "source_post_snapshot_sha256": test_identity["test_source_post_snapshot_sha256"],
      "source_unchanged": True, "code_version": code_version(project_root)}
  payload_values = {
      "audit_identity.json": {
          "schema_version": "capd_proactive_stage11_v2_input_audit_identity_v1_0",
          "contract_id": CONTRACT_ID, "audit_id": AUDIT_ID,
          "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
          "approved_production_plan_sha256": APPROVED_PLAN_SHA256},
      "audit_commands.json": audit_commands,
      "real_upstream_audit_stdout.json": audit_stdout,
      "frozen_tree_before.json": frozen_before,
      "frozen_tree_after.json": frozen_after,
      "frozen_tree_comparison.json": tree_comparison,
      "source_identity.json": source_identity,
      "test_source_identity.json": test_identity}
  payloads = {name: canonical_json_bytes(value)
              for name, value in payload_values.items()}
  payloads.update(canonical)
  payloads.update({
      "synthetic_allowlist.log": synthetic_log,
      "production_enablement_tests.log": production_log,
      "legacy_semantic_tests.log": legacy_log})
  sorted_ids = [row["job_id"] for row in stage8_source["manifest"]["records"]]
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_input_audit_receipt_v1_0",
      "contract_id": CONTRACT_ID, "audit_id": AUDIT_ID,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "production_config_sha256": source_identity["production_config_sha256"],
      "production_result_schema_sha256":
          source_identity["production_result_schema_sha256"],
      "generation_source_manifest_sha256":
          sha256_file(Path(project_root) / config["source_manifests"]["generation"]),
      "generation_source_members_sha256":
          generation_source_manifest["members_sha256"],
      "generation_source_member_count": 30,
      "verifier_source_manifest_sha256":
          sha256_file(Path(project_root) / config["source_manifests"]["verifier"]),
      "verifier_source_members_sha256": verifier_source_manifest["members_sha256"],
      "verifier_source_member_count": 32,
      "test_source_identity_sha256": sha256_value(test_identity),
      "test_source_pre_snapshot_sha256":
          test_identity["test_source_pre_snapshot_sha256"],
      "test_source_post_snapshot_sha256":
          test_identity["test_source_post_snapshot_sha256"],
      "test_sources_unchanged": True,
      "audit_commands_sha256": sha256_value(audit_commands),
      "synthetic_allowlist_log_sha256": sha256_bytes(synthetic_log),
      "production_enablement_tests_log_sha256": sha256_bytes(production_log),
      "legacy_semantic_tests_log_sha256": sha256_bytes(legacy_log),
      "real_upstream_audit_stdout_sha256": sha256_value(audit_stdout),
      "synthetic_test_count": 41, "production_enablement_test_count": 56,
      "legacy_semantic_test_count": 6, "stage8_input_verified": True,
      "stage9_input_authorized": True, "stage10_input_authorized": True,
      "stage8_input_receipt_sha256":
          sha256_bytes(canonical["stage8_standard_input_receipt.json"]),
      "stage9_input_receipt_sha256":
          sha256_bytes(canonical["stage9_input_receipt.json"]),
      "stage10_input_receipt_sha256":
          sha256_bytes(canonical["stage10_input_receipt.json"]),
      "standard_source_manifest_sha256":
          sha256_bytes(canonical["standard_source_manifest.json"]),
      "sorted_job_ids_sha256": sha256_value(sorted_ids),
      "standard_job_count": 48, "standard_workload_count": 6,
      "frozen_tree_before_sha256": sha256_value(frozen_before),
      "frozen_tree_after_sha256": sha256_value(frozen_after),
      "frozen_tree_comparison_sha256": sha256_value(tree_comparison),
      "frozen_trees_unchanged": True, "generation_source_set_match": True,
      "repository_revision_match": audit_stdout["repository_revision_match"],
      "sealed_dual_verifier_attestation": "verified",
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "input_audit_verified": True, "stage11_execution_authorized": False,
      "stage11_formally_verified": False,
      "test_used_for_parameter_selection": False, "synthetic_test_only": False}
  validate_input_audit_receipt(receipt, expected_plan_sha256=APPROVED_PLAN_SHA256)
  payloads["input_audit_receipt.json"] = canonical_json_bytes(receipt)
  _require(set(payloads) == INPUT_AUDIT_PAYLOADS,
           "Input-audit payload exact member set mismatch.")
  return seal_package_bytes("input_audit", payloads)


def validate_input_audit_receipt(receipt: Mapping[str, Any], *,
                                 expected_plan_sha256: str) -> Mapping[str, Any]:
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
           receipt["contract_id"] == CONTRACT_ID and receipt["audit_id"] == AUDIT_ID,
           "Input-audit receipt identity mismatch.")
  _require(receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == expected_plan_sha256 ==
           APPROVED_PLAN_SHA256, "Input-audit approval binding mismatch.")
  required_true = (
      "test_sources_unchanged", "stage8_input_verified", "stage9_input_authorized",
      "stage10_input_authorized", "frozen_trees_unchanged",
      "generation_source_set_match", "input_audit_verified")
  _require(all(receipt[field] is True for field in required_true),
           "Input-audit gate is incomplete.", ProductionNotVerifiable)
  _require(receipt["generation_source_member_count"] == 30 and
           receipt["verifier_source_member_count"] == 32 and
           receipt["synthetic_test_count"] == 41 and
           receipt["production_enablement_test_count"] == 56 and
           receipt["legacy_semantic_test_count"] == 6 and
           receipt["standard_job_count"] == 48 and
           receipt["standard_workload_count"] == 6,
           "Input-audit frozen counts changed.")
  _require(isinstance(receipt["repository_revision_match"], bool) and
           receipt["sealed_dual_verifier_attestation"] == "verified" and
           receipt["current_live_replay_compatibility"] == "NOT_VERIFIABLE",
           "Stage10 diagnostic/evidence classification changed.")
  _require(receipt["stage11_execution_authorized"] is False and
           receipt["stage11_formally_verified"] is False and
           receipt["test_used_for_parameter_selection"] is False and
           receipt["synthetic_test_only"] is False,
           "Input audit improperly grants a later state.")
  return receipt


def validate_execution_authorization(receipt: Mapping[str, Any],
                                     config: Mapping[str, Any],
                                     input_receipt: Mapping[str, Any],
                                     *, expected_plan_sha256: str,
                                     input_audit_external_hashes: Mapping[str, str]
                                     ) -> Mapping[str, Any]:
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
  _exact_keys(receipt, required, "Execution authorization")
  _require(receipt["schema_version"] ==
           "capd_proactive_stage11_v2_production_execution_authorization_v1_0" and
           receipt["contract_id"] == CONTRACT_ID and
           receipt["production_revision"] == PRODUCTION_REVISION and
           receipt["run_id"] == RUN_ID, "Execution authorization identity mismatch.")
  _require(receipt["approved_production_design_sha256"] == APPROVED_DESIGN_SHA256 and
           receipt["approved_production_plan_sha256"] == expected_plan_sha256 ==
           APPROVED_PLAN_SHA256, "Execution approval document binding mismatch.")
  _require(receipt["input_audit_receipt_sha256"] ==
           input_audit_external_hashes.get("receipt_sha256") and
           receipt["input_audit_manifest_sha256"] ==
           input_audit_external_hashes.get("manifest_sha256") and
           receipt["input_audit_checksums_sha256"] ==
           input_audit_external_hashes.get("checksums_sha256"),
           "Execution authorization does not bind all input-audit external hashes.")
  for field in (
      "generation_source_manifest_sha256", "generation_source_members_sha256",
      "verifier_source_manifest_sha256", "verifier_source_members_sha256",
      "test_source_identity_sha256", "test_source_pre_snapshot_sha256",
      "test_source_post_snapshot_sha256", "standard_source_manifest_sha256",
      "sorted_job_ids_sha256", "stage8_input_receipt_sha256",
      "stage9_input_receipt_sha256", "stage10_input_receipt_sha256"):
    _require(receipt[field] == input_receipt[field],
             "Execution/input-audit binding mismatch: {}".format(field))
  _require(receipt["sealed_frozen_tree_after_sha256"] ==
           input_receipt["frozen_tree_after_sha256"],
           "Execution sealed tree binding mismatch.")
  _require(receipt["main_b_max"] == 2 and
           receipt["authorized_scope"] == "offline_cost_profiles_only" and
           receipt["expected_result_rows"] == 192 and
           tuple(receipt["blocked_lanes"]) == BLOCKED_LANES and
           receipt["stage11_execution_authorized"] is True and
           receipt["synthetic_test_only"] is False and
           receipt["test_used_for_parameter_selection"] is False and
           receipt["future_output_hashes_absent"] is True,
           "Execution authorization scope is invalid.")
  _require(receipt["generation_source_member_count"] == 30 and
           receipt["verifier_source_member_count"] == 32 and
           receipt["standard_job_count"] == 48 and
           receipt["standard_workload_count"] == 6 and
           receipt["test_sources_unchanged"] is True,
           "Execution authorization frozen counts changed.")
  _require(receipt["frozen_cost_profiles_sha256"] ==
           sha256_value(config["cost_profiles"]), "Cost profile hash mismatch.")
  return receipt


def _non_negative_int(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
           "{} must be a non-negative integer.".format(field))
  return value


def validate_standard_jobs(jobs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
  _require(len(jobs) == 48, "Standard source must contain exactly 48 jobs.")
  job_ids = [job.get("job_id") for job in jobs]
  _require(all(isinstance(item, str) and item for item in job_ids) and
           len(set(job_ids)) == 48, "Stage8 job_id values must be unique.")
  _require(all(job.get("track") == "standard" for job in jobs),
           "Pressure/non-Standard job is forbidden.")
  workloads = Counter(job.get("workload") for job in jobs)
  _require(workloads == Counter({name: 8 for name in STANDARD_WORKLOADS}),
           "Standard workload multiset mismatch.")
  for workload in STANDARD_WORKLOADS:
    members = Counter((job.get("policy"), job.get("seed"))
                      for job in jobs if job.get("workload") == workload)
    _require(members == Counter(STANDARD_MEMBERS),
             "Policy/seed multiset mismatch for {}.".format(workload))
  return sorted(jobs, key=lambda job: job["job_id"])


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


def load_stage8_standard_source(stage8_root: os.PathLike[str] | str
                               ) -> dict[str, Any]:
  root = Path(stage8_root).resolve()
  _require(root.is_dir(), "Stage8 r5 root is missing.", ProductionNotVerifiable)
  state = load_json_strict(root / "run_state.json")
  verification = load_json_strict(root / "verification.json")
  authority = load_json_strict(root / "job_manifest.json")
  _require(state.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
           state.get("status") == "stage8_sync_replay_verified" and
           state.get("test_used_for_parameter_selection") is False and
           verification.get("status") == "stage8_sync_replay_verified",
           "Stage8 r5 state is not verified.", ProductionNotVerifiable)
  plans = authority.get("jobs")
  _require(authority.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
           isinstance(plans, list), "Stage8 authority manifest is malformed.",
           ProductionNotVerifiable)
  standard_plans = [row for row in plans if row.get("track") == "standard"]
  plan_by_id = {row.get("job_id"): row for row in standard_plans}
  _require(len(standard_plans) == len(plan_by_id) == 48,
           "Stage8 authority must contain 48 unique Standard jobs.",
           ProductionNotVerifiable)
  csv_path = root / "artifacts" / "per_workload_raw.csv"
  with csv_path.open("r", encoding="utf-8", newline="") as handle:
    selected = [row for row in csv.DictReader(handle)
                if row.get("track") == "standard"]
  csv_ids = [row.get("job_id") for row in selected]
  _require(len(csv_ids) == len(set(csv_ids)) == 48 and
           set(csv_ids) == set(plan_by_id),
           "Stage8 CSV/authority Standard job set mismatch.",
           ProductionNotVerifiable)
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
             "Stage8 job SHA/semantic identity failed: {}".format(job_id),
             ProductionNotVerifiable)
    for field in ("job_id", "track", "workload", "policy", "seed", "D",
                  "W_ref", "F_low", "F_target", "K", "b_max", "history_H",
                  "alpha", "beta", "trace_sha256", "source_interval",
                  "evaluation_interval", "initial_state_sha256",
                  "cost_profile_sha256"):
      _require(result.get(field) == plan.get(field),
               "Stage8 result/plan mismatch: {}".format(field),
               ProductionNotVerifiable)
    _require(result.get("schema_version") ==
             "capd_proactive_stage8_job_result_v2_0" and
             result.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
             result.get("formal_test") is True and
             result.get("test_used_for_selection") is False and
             result.get("selector_status") == "disabled",
             "Stage8 result formal state is invalid.", ProductionNotVerifiable)
    metrics = result.get("metrics", {})
    job = {"job_id": job_id, "track": "standard",
           "workload": plan["workload"], "policy": plan["policy"],
           "seed": plan.get("seed")}
    for field in ("dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                  "raw_access_count", "reactive_demotions",
                  "proactive_demotions", "emergency_demotions"):
      job[field] = _non_negative_int(metrics.get(field), "metrics." + field)
    _require(job["total_demotions"] == job["reactive_demotions"] +
             job["proactive_demotions"] + job["emergency_demotions"],
             "Stage8 demotion counters are inconsistent.",
             ProductionNotVerifiable)
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
      "contract_id": CONTRACT_ID, "stage8_contract_id":
          "CAPD-PROACTIVE-STAGE8-2.0", "records": records,
      "job_count": 48, "workload_count": 6,
      "sorted_job_ids_sha256": sha256_value(sorted_ids)}
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_stage8_input_receipt_v1_0",
      "contract_id": CONTRACT_ID, "stage": "stage8",
      "status": "verified", "authorized_external_input": True,
      "stage8_run_state_sha256": sha256_file(root / "run_state.json"),
      "stage8_verification_sha256": sha256_file(root / "verification.json"),
      "stage8_job_manifest_sha256": sha256_file(root / "job_manifest.json"),
      "standard_source_manifest_sha256": sha256_value(manifest),
      "sorted_job_ids_sha256": manifest["sorted_job_ids_sha256"],
      "job_count": 48, "workload_count": 6,
      "test_used_for_parameter_selection": False,
      "synthetic_test_only": False}
  return {"jobs": jobs, "manifest": manifest, "receipt": receipt}


def load_jobs_from_sealed_manifest(stage8_root: os.PathLike[str] | str,
                                   sealed_manifest: Mapping[str, Any]
                                   ) -> list[dict[str, Any]]:
  rebuilt = load_stage8_standard_source(stage8_root)
  _require(rebuilt["manifest"] == sealed_manifest,
           "Sealed Standard source manifest differs from current Stage8 bytes.",
           ProductionNotVerifiable)
  return rebuilt["jobs"]


def generate_cost_rows(jobs: Sequence[Mapping[str, Any]],
                       cost_profiles: Mapping[str, Mapping[str, int]],
                       *, main_b_max: int = 2) -> list[dict[str, Any]]:
  _require(main_b_max == 2, "Formal main b_max cannot be overridden.")
  _require(dict(cost_profiles) == PROFILE_WEIGHTS,
           "Cost profiles must be the frozen four-profile set.")
  # This assertion binds the implementation to the repository's frozen Cost helper.
  _require(proactive_cost.FROZEN_PROFILE_WEIGHTS == PROFILE_WEIGHTS,
           "Repository Cost helper profile identity changed.")
  rows = []
  for job in validate_standard_jobs(jobs):
    counts = {}
    for field in (
        "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
        "raw_access_count", "reactive_demotions", "proactive_demotions",
        "emergency_demotions"):
      counts[field] = _non_negative_int(job.get(field), field)
    _require(counts["total_demotions"] == counts["reactive_demotions"] +
             counts["proactive_demotions"] + counts["emergency_demotions"],
             "Demotion total does not equal its integer breakdown.")
    for profile_name in PROFILE_NAMES:
      weights = cost_profiles[profile_name]
      weighted = (
          counts["dram_hits"] * weights["dram_hit"] +
          counts["nvm_reads"] * weights["nvm_read"] +
          counts["nvm_writes"] * weights["nvm_write"] +
          counts["total_demotions"] * weights["demotion"])
      per_access = (weighted / counts["raw_access_count"]
                    if counts["raw_access_count"] > 0 else None)
      rows.append({
          "row_id": "{}::{}".format(job["job_id"], profile_name),
          "run_id": RUN_ID, "source_job_id": job["job_id"],
          "track": "standard", "workload": job["workload"],
          "policy": job["policy"], "seed": job["seed"],
          "cost_profile": profile_name,
          "cost_profile_weights": copy.deepcopy(weights), **counts,
          "weighted_cost": weighted,
          "weighted_cost_per_access": per_access,
          "evidence_mode": "offline_raw_counter_recompute",
          "evidence_status": "candidate-ready"})
  validate_result_rows(rows, jobs)
  return rows


def validate_result_rows(rows: Sequence[Mapping[str, Any]],
                         jobs: Sequence[Mapping[str, Any]]) -> None:
  sorted_jobs = validate_standard_jobs(jobs)
  expected = {(job["job_id"], profile) for job in sorted_jobs
              for profile in PROFILE_NAMES}
  actual = [(row.get("source_job_id"), row.get("cost_profile")) for row in rows]
  _require(len(rows) == 192 and len(set(actual)) == 192 and set(actual) == expected,
           "Result rows are not the exact 48x4 Cartesian product.")
  _require(all(row.get("track") == "standard" and
               row.get("evidence_mode") == "offline_raw_counter_recompute" and
               row.get("evidence_status") == "candidate-ready"
               for row in rows), "Result evidence status/lane is invalid.")
  _require(all((row.get("weighted_cost_per_access") is None)
               == (row.get("raw_access_count") == 0) for row in rows),
           "Zero-access rows must use JSON null only.")


RESULT_CSV_FIELDS = (
    "row_id", "run_id", "source_job_id", "track", "workload", "policy",
    "seed", "cost_profile", "dram_hit_weight", "nvm_read_weight",
    "nvm_write_weight", "demotion_weight", "dram_hits", "nvm_reads",
    "nvm_writes", "total_demotions", "raw_access_count",
    "reactive_demotions", "proactive_demotions", "emergency_demotions",
    "weighted_cost", "weighted_cost_per_access", "evidence_mode",
    "evidence_status")


def rows_to_csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
  stream = io.StringIO(newline="")
  writer = csv.DictWriter(stream, fieldnames=RESULT_CSV_FIELDS,
                          lineterminator="\n")
  writer.writeheader()
  for row in rows:
    weights = row["cost_profile_weights"]
    flat = {key: row.get(key) for key in RESULT_CSV_FIELDS}
    for name in ("dram_hit", "nvm_read", "nvm_write", "demotion"):
      flat[name + "_weight"] = weights[name]
    flat["seed"] = "N/A" if row["seed"] is None else row["seed"]
    flat["weighted_cost_per_access"] = (
        "N/A" if row["weighted_cost_per_access"] is None
        else row["weighted_cost_per_access"])
    writer.writerow(flat)
  return stream.getvalue().encode("utf-8")


def _report_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
  lines = [
      "# CAPD Stage11 v2 Production Offline Cost Results", "",
      "- status: `candidate-ready`", "- row count: `{}`".format(len(rows)),
      "- scope: `48 Standard jobs x 4 frozen Cost profiles`",
      "- independent verification: `PENDING`",
      "- final approval: `PENDING`", "- formally verified: `false`", "",
      "Blocked lanes: " + ", ".join("`{}`".format(item)
                                     for item in BLOCKED_LANES), "",
      "Missing numeric values are shown as `N/A`; no Stage9/Stage10/system "
      "overhead value is estimated.", ""]
  return "\n".join(lines).encode("utf-8")


def build_generation_package(
    *, project_root: os.PathLike[str] | str, config: Mapping[str, Any],
    input_audit_binding: Mapping[str, Any],
    authorization_binding: Mapping[str, Any],
    input_audit_receipt: Mapping[str, Any],
    authorization_receipt: Mapping[str, Any],
    stage8_receipt: Mapping[str, Any], stage9_receipt: Mapping[str, Any],
    stage10_receipt: Mapping[str, Any], standard_manifest: Mapping[str, Any],
    generation_source_manifest: Mapping[str, Any],
    verifier_source_manifest: Mapping[str, Any],
    sealed_snapshot: Mapping[str, Any], pre_snapshot: Mapping[str, Any],
    post_snapshot: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
    monitoring: Mapping[str, Any]) -> dict[str, bytes]:
  comparison = compare_frozen_snapshots(
      sealed_snapshot, [("sealed_vs_pre_generation", pre_snapshot),
                        ("sealed_vs_post_generation", post_snapshot)])
  _require(comparison["identical"], "Generation continuity changed.",
           ProductionNotVerifiable)
  validate_result_rows(rows, [
      {key: row[key] for key in (
          "job_id", "track", "workload", "policy", "seed", "dram_hits",
          "nvm_reads", "nvm_writes", "total_demotions", "raw_access_count",
          "reactive_demotions", "proactive_demotions", "emergency_demotions")}
      for row in ({"job_id": item["source_job_id"], **item}
                  for item in rows[::4])])
  frozen_grid = {
      "schema_version": "capd_proactive_stage11_v2_frozen_grid_v1_0",
      "main_b_max": 2, "cost_profiles": copy.deepcopy(PROFILE_WEIGHTS),
      "blocked_lanes": list(BLOCKED_LANES),
      "test_used_for_parameter_selection": False}
  frozen_grid["frozen_grid_sha256"] = sha256_value({
      key: frozen_grid[key] for key in (
          "main_b_max", "cost_profiles", "blocked_lanes",
          "test_used_for_parameter_selection")})
  result_value = {
      "schema_version": "capd_proactive_stage11_v2_production_result_v1_0",
      "contract_id": CONTRACT_ID, "run_id": RUN_ID,
      "lane": "offline_cost_profiles", "rows": list(rows),
      "blocked_lanes": list(BLOCKED_LANES), "stage11_formally_verified": False,
      "test_used_for_parameter_selection": False}
  root = Path(project_root).resolve()
  config_sha = sha256_file(
      root / "configs/finals/capd_proactive_stage11_v2_production.json")
  result_schema_sha = sha256_file(
      root / "configs/finals/capd_proactive_stage11_v2_production_result_schema.json")
  source_snapshot_value = source_snapshot(root, GENERATION_SOURCE_PATHS)
  run_identity = {
      "schema_version": "capd_proactive_stage11_v2_production_run_identity_v1_0",
      "contract_id": CONTRACT_ID, "production_revision": PRODUCTION_REVISION,
      "run_id": RUN_ID,
      "approved_production_design_sha256": APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": APPROVED_PLAN_SHA256,
      "production_config_sha256": config_sha,
      "production_result_schema_sha256": result_schema_sha,
      "input_audit_receipt_sha256": input_audit_binding["receipt_sha256"],
      "input_audit_manifest_sha256": input_audit_binding["manifest_sha256"],
      "input_audit_checksums_sha256": input_audit_binding["checksums_sha256"],
      "execution_authorization_receipt_sha256":
          authorization_binding["receipt_sha256"],
      "execution_authorization_manifest_sha256":
          authorization_binding["manifest_sha256"],
      "execution_authorization_checksums_sha256":
          authorization_binding["checksums_sha256"],
      "generation_source_manifest_sha256": sha256_value(generation_source_manifest),
      "generation_source_members_sha256": generation_source_manifest["members_sha256"],
      "verifier_source_manifest_sha256": sha256_value(verifier_source_manifest),
      "verifier_source_members_sha256": verifier_source_manifest["members_sha256"],
      "stage8_input_receipt_sha256": sha256_value(stage8_receipt),
      "stage9_input_receipt_sha256": sha256_value(stage9_receipt),
      "stage10_input_receipt_sha256": sha256_value(stage10_receipt),
      "standard_source_manifest_sha256": sha256_value(standard_manifest),
      "sorted_job_ids_sha256": standard_manifest["sorted_job_ids_sha256"],
      "frozen_cost_profiles_sha256": sha256_value(PROFILE_WEIGHTS),
      "frozen_grid_sha256": frozen_grid["frozen_grid_sha256"],
      "sealed_frozen_tree_after_sha256": sha256_value(sealed_snapshot),
      "pre_generation_continuity_snapshot_sha256": sha256_value(pre_snapshot),
      "code_version": code_version(root),
      "source_snapshot_sha256": sha256_value(source_snapshot_value),
      "expected_result_rows": 192, "test_used_for_parameter_selection": False}
  run_state = {
      "schema_version": "capd_proactive_stage11_v2_production_run_state_v1_0",
      "contract_id": CONTRACT_ID, "run_id": RUN_ID,
      "status": "stage11_generation_complete_pending_independent_verification",
      "result_row_count": 192,
      "sealed_frozen_tree_after_sha256": sha256_value(sealed_snapshot),
      "pre_generation_continuity_snapshot_sha256": sha256_value(pre_snapshot),
      "post_generation_continuity_snapshot_sha256": sha256_value(post_snapshot),
      "generation_continuity_comparison_sha256": sha256_value(comparison),
      "upstream_continuity_verified": True,
      "blocked_lanes": list(BLOCKED_LANES), "monitoring": dict(monitoring),
      "stage11_generation_verified": False,
      "stage11_final_approval_verified": False,
      "stage11_formally_verified": False,
      "test_used_for_parameter_selection": False}
  json_payloads = {
      "stage11_v2_config.json": config,
      "run_identity.json": run_identity, "run_state.json": run_state,
      "input_audit_binding.json": input_audit_binding,
      "input_audit_receipt.json": input_audit_receipt,
      "execution_authorization_binding.json": authorization_binding,
      "execution_authorization_receipt.json": authorization_receipt,
      "stage8_standard_input_receipt.json": stage8_receipt,
      "stage9_input_receipt.json": stage9_receipt,
      "stage10_input_receipt.json": stage10_receipt,
      "standard_source_manifest.json": standard_manifest,
      "frozen_grid.json": frozen_grid,
      "generation_source_manifest.json": generation_source_manifest,
      "verifier_source_manifest.json": verifier_source_manifest,
      "sealed_frozen_tree_after.json": sealed_snapshot,
      "pre_generation_continuity_snapshot.json": pre_snapshot,
      "post_generation_continuity_snapshot.json": post_snapshot,
      "generation_continuity_comparison.json": comparison,
      "stage11_v2_results.json": result_value}
  payloads = {name: canonical_json_bytes(value)
              for name, value in json_payloads.items()}
  payloads["stage11_v2_results.csv"] = rows_to_csv_bytes(rows)
  payloads["stage11_v2_report.md"] = _report_bytes(rows)
  _require(set(payloads) == GENERATION_PAYLOADS,
           "Generation payload exact member set mismatch.")
  return seal_package_bytes("generation", payloads)


def monitoring_record(*, timed_out: bool, exit_code: int | None,
                      sample_count: int, wall_clock_start: float | None,
                      wall_clock_end: float | None, worker_pid: int | None
                      ) -> dict[str, Any]:
  _require(sample_count >= 1, "At least one process-alive sample is required.")
  result = dict(MONITORING_CONTRACT)
  result.update({
      "timed_out": bool(timed_out), "exit_code": exit_code,
      "process_alive_sample_count": sample_count,
      "wall_clock_start": wall_clock_start, "wall_clock_end": wall_clock_end,
      "wall_clock_duration_seconds": (
          wall_clock_end - wall_clock_start
          if wall_clock_start is not None and wall_clock_end is not None else None),
      "worker_pid": worker_pid})
  return result


def deterministic_result_view(result: Mapping[str, Any]) -> dict[str, Any]:
  value = copy.deepcopy(dict(result))
  value.pop("monitoring", None)
  return value


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


def preflight_before_mkdir(*, output_dir: os.PathLike[str] | str,
                           sealed_snapshot: Mapping[str, Any],
                           current_snapshot: Mapping[str, Any],
                           config: Mapping[str, Any],
                           externally_approved_plan_sha256: str,
                           input_audit_receipt: Mapping[str, Any],
                           authorization_receipt: Mapping[str, Any],
                           input_audit_external_hashes: Mapping[str, str]
                           ) -> dict[str, Any]:
  validate_config(config,
                  externally_approved_plan_sha256=externally_approved_plan_sha256)
  validate_input_audit_receipt(
      input_audit_receipt, expected_plan_sha256=externally_approved_plan_sha256)
  validate_execution_authorization(
      authorization_receipt, config, input_audit_receipt,
      expected_plan_sha256=externally_approved_plan_sha256,
      input_audit_external_hashes=input_audit_external_hashes)
  comparison = assert_continuity(
      sealed_snapshot, current_snapshot, "sealed_vs_pre_generation")
  target = Path(output_dir)
  _require(not target.exists(), "Production run ID already exists.", ProductionBlocked)
  return comparison


def write_phase_package(capability: production_guard.WriteCapability, *,
                        phase: str, identity: str,
                        output_root: os.PathLike[str] | str,
                        package: Mapping[str, bytes]) -> None:
  expected = production_guard.PHASE_ARTIFACTS[phase]
  _require(set(package) == set(expected), "Writer package member set mismatch.")
  for artifact in sorted(package):
    production_guard.guarded_write_bytes(
        capability, phase=phase, identity=identity, output_root=output_root,
        artifact=artifact, data=package[artifact])
