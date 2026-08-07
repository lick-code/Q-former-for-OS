"""Synthetic-only tests for the Stage11 v2 evidence migration contracts."""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qmap import proactive_stage11_v2 as contract
from qmap import proactive_stage11_v2_guard as path_guard
from qmap import proactive_stage11_v2_verifier as verifier
from scripts import run_capd_proactive_stage11_v2 as runner


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/finals/capd_proactive_stage11_v2.json"
RESULT_SCHEMA = ROOT / "configs/finals/capd_proactive_stage11_v2_result_schema.json"
STAGE9_SCHEMA = ROOT / "configs/finals/capd_proactive_stage9_result_schema.json"
REAL_ROOTS = tuple((ROOT / relative).resolve() for relative in (
    "outputs/capd_proactive_stage8", "outputs/capd_proactive_stage9",
    "outputs/capd_proactive_stage10", "outputs/capd_proactive_stage11",
    "outputs/capd_proactive_stage11_v2", "checkpoints"))
REAL_SUCCESSFUL_OPENS: list[str] = []
REAL_DENIED_OPENS: list[str] = []


def _audit_hook(event, args):
  if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
    return
  path = Path(os.fsdecode(args[0])).absolute().resolve(strict=False)
  if any(path == root or root in path.parents for root in REAL_ROOTS):
    REAL_DENIED_OPENS.append(str(path))
    raise PermissionError("Stage11 v2 synthetic tests deny real upstream opens")


sys.addaudithook(_audit_hook)


def _json_text(value):
  return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                    allow_nan=False) + "\n"


def _write_json(path: Path, value) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(_json_text(value), encoding="utf-8", newline="")
  return path


def _sha(path: Path) -> str:
  return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_envelope(root: Path, phase: str, contract_id: str) -> dict[str, str]:
  payload = sorted(path for path in root.rglob("*") if path.is_file() and
                   path.relative_to(root).as_posix() not in
                   ("manifest.json", "SHA256SUMS"))
  files = {path.relative_to(root).as_posix(): _sha(path) for path in payload}
  manifest = {
      "schema_version": "capd_proactive_stage11_v2_release_manifest_v1_0",
      "contract_id": contract_id, "phase": phase, "files": files}
  _write_json(root / "manifest.json", manifest)
  checksum_members = sorted(
      path for path in root.rglob("*") if path.is_file() and
      path.relative_to(root).as_posix() != "SHA256SUMS")
  text = "".join("{}  {}\n".format(_sha(path), path.relative_to(root).as_posix())
                 for path in checksum_members)
  (root / "SHA256SUMS").write_text(text, encoding="utf-8", newline="")
  return {"manifest_sha256": _sha(root / "manifest.json"),
          "checksums_sha256": _sha(root / "SHA256SUMS")}


def _write_stage10_envelope(root: Path, phase: str) -> dict[str, str]:
  payload = sorted(path for path in root.rglob("*") if path.is_file() and
                   path.relative_to(root).as_posix() not in
                   ("manifest.json", "SHA256SUMS"))
  files = {path.relative_to(root).as_posix(): _sha(path) for path in payload}
  if phase == "generation":
    manifest = {
        "schema_version": "capd_proactive_stage10_manifest_v2_1",
        "files": files}
  else:
    manifest = {
        "schema_version": "capd_proactive_stage10_release_manifest_v1_0",
        "phase": phase, "files": files}
  _write_json(root / "manifest.json", manifest)
  checksum_members = sorted(
      path for path in root.rglob("*") if path.is_file() and
      path.relative_to(root).as_posix() != "SHA256SUMS")
  (root / "SHA256SUMS").write_text(
      "".join("{}  {}\n".format(_sha(path), path.relative_to(root).as_posix())
              for path in checksum_members), encoding="utf-8", newline="")
  return {"manifest_sha256": _sha(root / "manifest.json"),
          "checksums_sha256": _sha(root / "SHA256SUMS")}


def _make_stage8(root: Path) -> Path:
  root.mkdir(parents=True)
  plans = []
  csv_rows = []
  index = 0
  for workload in contract.STANDARD_WORKLOADS:
    for policy, seed in contract.STANDARD_MEMBERS:
      index += 1
      seed_text = "none" if seed is None else str(seed)
      job_id = "standard__{}__{}__{}".format(workload, policy, seed_text)
      plan = {
          "job_id": job_id, "track": "standard", "workload": workload,
          "policy": policy, "seed": seed, "D": 20, "W_ref": 50,
          "F_low": 3, "F_target": 6, "K": 8, "b_max": 2,
          "history_H": 4, "alpha": 1.0, "beta": 1.0,
          "trace_sha256": "{:064x}".format(index),
          "source_interval": [0, 10], "evaluation_interval": [10, 20],
          "initial_state_sha256": "{:064x}".format(index + 100),
          "cost_profile_sha256": "{:064x}".format(index + 200)}
      metrics = {
          "dram_hits": 100 + index, "nvm_reads": 20 + index,
          "nvm_writes": 5 + index, "total_demotions": 6,
          "proactive_demotions": 2, "reactive_demotions": 3,
          "emergency_demotions": 1, "raw_access_count": 200 + index}
      result = dict(plan)
      result.update({
          "schema_version": "capd_proactive_stage8_job_result_v2_0",
          "contract_id": contract.STAGE8_CONTRACT_ID, "formal_test": True,
          "test_used_for_selection": False, "selector_status": "disabled",
          "metrics": metrics, "rounds": [], "cycles": []})
      result["semantic_result_sha256"] = contract.sha256_value(
          contract.semantic_stage8_payload(result))
      result_path = _write_json(root / "jobs" / job_id / "result.json", result)
      job_identity = {
          "checkpoint_sha256": None,
          "deterministic_runtime_environment": {"PYTHONHASHSEED": "0"},
          "device": "cpu", "measure_latency": False,
          "plan_job": plan,
          "result_schema": "capd_proactive_stage8_job_result_v2_0",
          "run_identity_sha256": "{:064x}".format(index + 300),
          "trace_sha256": plan["trace_sha256"]}
      job_manifest = {
          "status": "completed", "result_sha256": _sha(result_path),
          "semantic_result_sha256": result["semantic_result_sha256"],
          "job_identity": job_identity,
          "job_identity_sha256": contract.sha256_value(job_identity)}
      _write_json(root / "jobs" / job_id / "job_manifest.json", job_manifest)
      plans.append(plan)
      csv_rows.append({"job_id": job_id, "track": "standard"})
  _write_json(root / "run_state.json", {
      "contract_id": contract.STAGE8_CONTRACT_ID,
      "status": "stage8_sync_replay_verified",
      "test_used_for_parameter_selection": False})
  _write_json(root / "verification.json", {
      "status": "stage8_sync_replay_verified"})
  _write_json(root / "job_manifest.json", {
      "contract_id": contract.STAGE8_CONTRACT_ID, "jobs": plans})
  csv_path = root / "artifacts" / "per_workload_raw.csv"
  csv_path.parent.mkdir(parents=True)
  with csv_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=("job_id", "track"))
    writer.writeheader()
    writer.writerows(csv_rows)
  return root


def _make_stage9(root: Path) -> Path:
  root.mkdir(parents=True)
  schema = contract.load_json_strict(STAGE9_SCHEMA)
  for name in schema["required_run_artifacts"]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
      _write_json(path, {"synthetic": True})
    else:
      path.write_text("synthetic\n", encoding="utf-8", newline="")
  _write_json(root / "stage8_compatibility_receipt.json", {
      "stage9_entry_gate": "satisfied",
      "stage8_contract_id": contract.STAGE8_CONTRACT_ID,
      "stage8_status": "stage8_sync_replay_verified",
      "job_results_verified": True, "statistics_verified": True,
      "stage8_run_state_verified": True, "stage8_artifacts_read_only": True,
      "test_used_for_parameter_selection": False})
  _write_json(root / "environment.json", {
      "system": "Linux", "device": "cpu", "linux_kernel": "synthetic"})
  _write_json(root / "perf" / "perf_parsed.json", {
      "counter_source": "linux_perf_hardware", "required_events_verified": True,
      "cycles_verified": True,
      "events": {name: {"status": "ok", "value": 1000}
                 for name in schema["perf_required_events"]},
      "derived": {name: 10.0 for name in schema["perf_derived_fields"]}})
  scope = {name: 1 for name in schema["perf_scope_required_fields"]}
  scope.update({"measured_job_ids": ["synthetic"], "measured_cells": ["synthetic"],
                "zero_round_job_ids": [], "zero_round_cells": [],
                "measured_rounds": 10, "measured_demoted_pages": 5})
  _write_json(root / "perf" / "perf_scope_counts.json", scope)
  memory = {name: 1 for name in schema["memory_required_fields"]}
  memory["rss"] = {
      "process_baseline_rss_bytes": 100, "process_baseline_rss_mib": 0.1,
      "total_peak_rss_bytes": 140, "total_peak_rss_mib": 0.14,
      "stage9_incremental_peak_rss_bytes": 40,
      "stage9_incremental_peak_rss_mib": 0.04}
  _write_json(root / "memory_breakdown.json", memory)
  with (root / "raw_latency_samples.csv").open(
      "w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=schema["raw_latency_required_fields"])
    writer.writeheader()
    writer.writerow({name: "1" for name in schema["raw_latency_required_fields"]})
  artifact_names = [name for name in schema["required_run_artifacts"]
                    if name not in ("verification.json", "run_state.json")]
  verification = dict(schema["verification_required"])
  verification.update({
      "artifact_sha256": {name: _sha(root / name) for name in artifact_names},
      "synthetic_test_only": True})
  _write_json(root / "verification.json", verification)
  _write_json(root / "run_state.json", {
      "schema_version": "capd_proactive_stage9_run_state_v2_0",
      "contract_id": contract.STAGE9_CONTRACT_ID,
      "status": "stage9_overhead_verified"})
  return root


def _make_stage10(root: Path) -> tuple[Path, dict[str, str]]:
  root.mkdir(parents=True)
  source_entries = [{
      "generation_identity": True,
      "generation_test_groups": ["generation_core"],
      "logical_name": "synthetic_source_{:02d}".format(index),
      "path": "synthetic/source_{:02d}.py".format(index),
      "role": "support", "sha256": "{:064x}".format(index + 1),
  } for index in range(11)]
  source = {
      "schema_version":
          "capd_proactive_stage10_generation_source_manifest_v1_0",
      "source_set_id": "stage10-v2-r2-generation-core-v1",
      "entries": source_entries}
  source_path = _write_json(root / "generation_source_manifest.json", source)
  source_sha = _sha(source_path)
  source_fingerprint = contract.sha256_value(source_entries)
  freeze_receipt = {
      "approved_design": {"path": "synthetic-design", "sha256": "1" * 64,
                          "status": "design_approved"},
      "approved_plan": {"path": "synthetic-plan", "sha256": "2" * 64,
                        "status": "implementation_plan_approved_tasks_0_9"},
      "authorization_state": {
          "formal_run_authorized_at_receipt_creation": False,
          "release_authorized_at_receipt_creation": False,
          "stage11_positive_migration_authorized_at_receipt_creation": False},
      "commands": {}, "config": {}, "controlled_execution": {},
      "environment_contract": {},
      "schema_version":
          "capd_proactive_stage10_generation_freeze_receipt_v1_0",
      "schemas": {},
      "source_manifest": {
          "entry_count": 11, "fingerprint_sha256": source_fingerprint,
          "path": "configs/finals/"
                  "capd_proactive_stage10_v2_r2_source_manifest.json",
          "schema_version": source["schema_version"], "sha256": source_sha,
          "source_set_id": source["source_set_id"]},
      "source_set_id": "stage10-v2-r2-generation-core-v1",
      "stage9_binding": {}}
  freeze_path = _write_json(root / "generation_freeze_receipt.json", freeze_receipt)
  freeze_sha = _sha(freeze_path)
  scenarios = [{"scenario_id": "scenario-{:02d}".format(i)} for i in range(60)]
  matrix_path = _write_json(root / "scenario_matrix.json", {"scenarios": scenarios})
  (root / "simulation_results.jsonl").write_text(
      "".join(json.dumps(row, sort_keys=True) + "\n" for row in scenarios),
      encoding="utf-8", newline="")
  zero = "0" * 64
  identity = {
      "approved_design_sha256": "1" * 64,
      "approved_freeze_receipt_sha256": freeze_sha,
      "approved_plan_sha256": "2" * 64, "config_sha256": zero,
      "contract_id": contract.STAGE10_CONTRACT_ID, "controlled_execution": {},
      "conversion_rule": "Decimal ROUND_HALF_UP to integral nanoseconds",
      "evidence_mode": "deterministic_async_simulation",
      "execution_environment_schema":
          "capd_proactive_stage10_execution_environment_v1_0",
      "execution_environment_sha256": zero,
      "generation_freeze_receipt_sha256": freeze_sha,
      "generation_source_entry_count": 11,
      "generation_source_manifest_schema": source["schema_version"],
      "generation_source_manifest_sha256": source_sha,
      "generation_source_set_fingerprint_sha256": source_fingerprint,
      "generation_source_set_id": source["source_set_id"],
      "generation_test_evidence_sha256": zero,
      "git": {"commit": "1" * 40,
              "generation_source_set_fingerprint_sha256": source_fingerprint},
      "result_schema_sha256": zero, "run_id": contract.STAGE10_RUN_ID,
      "run_identity_sha256": zero, "scenario_matrix_sha256": _sha(matrix_path),
      "schema_version": "capd_proactive_stage10_run_identity_v2_1",
      "stage9_checkpoint_sha256": zero, "stage9_config_sha256": zero,
      "stage9_input_receipt_sha256": zero, "stage9_latency_summary_sha256": zero,
      "stage9_run_identity_sha256": zero, "stage9_verification_sha256": zero,
      "timing_provenance_sha256": zero}
  _write_json(root / "run_identity.json", identity)
  _write_json(root / "run_state.json", {
      "artifacts_independently_verified": True,
      "contract_id": contract.STAGE10_CONTRACT_ID,
      "evidence_mode": "deterministic_async_simulation", "failure": None,
      "real_system_async_performance_verified": False,
      "run_id": contract.STAGE10_RUN_ID,
      "schema_version": "capd_proactive_stage10_run_state_v2_1",
      "simulation_executed": True, "stage9_input_gate_passed": True,
      "status": "stage10_async_simulation_verified"})
  verification = {
      "approved_freeze_receipt_sha256": freeze_sha,
      "artifacts_independently_recomputed": True,
      "contract_id": contract.STAGE10_CONTRACT_ID, "controlled_execution": {},
      "current_generation_sources_recomputed": True,
      "evidence_mode": "deterministic_async_simulation",
      "execution_environment_sha256": zero,
      "generation_source_entry_count": 11,
      "generation_source_manifest_sha256": source_sha,
      "generation_source_set_fingerprint_sha256": source_fingerprint,
      "generation_test_evidence_sha256": zero, "generation_tests_verified": True,
      "kernel_behavior_verified": False, "real_concurrency_verified": False,
      "real_foreground_end_to_end_latency_verified": False,
      "real_nvm_measurement_verified": False,
      "real_system_async_performance_verified": False, "result_count": 60,
      "scenario_ids": [row["scenario_id"] for row in scenarios],
      "schema_version": "capd_proactive_stage10_verification_v2_1",
      "simulation_executed": True, "stage9_input_gate": "satisfied",
      "status": "stage10_async_simulation_verified"}
  _write_json(root / "verification.json", verification)
  for name in contract.STAGE10_GENERATION_ARTIFACTS - {
      "generation_freeze_receipt.json", "generation_source_manifest.json",
      "run_identity.json", "run_state.json", "verification.json",
      "scenario_matrix.json", "simulation_results.jsonl", "manifest.json",
      "SHA256SUMS"}:
    path = root / name
    if name.endswith(".json"):
      _write_json(path, {"synthetic": True})
    else:
      path.write_text("synthetic\n", encoding="utf-8", newline="")
  generation = _write_stage10_envelope(root, "generation")

  receipts = root.parent / "release_receipts" / contract.STAGE10_RUN_ID
  readiness = receipts / "readiness"
  negative_result = {
      "stage10a": {"formal_authorized": False,
                   "reason_code": "stage10a_fixture_only", "status": "BLOCKED"},
      "stage10_r2": {"formal_authorized": False,
                     "reason_code": "invalid_stage10a_fixture",
                     "status": "NOT_VERIFIABLE"}}
  readiness_payloads = {
      "release_readiness_test_log.txt": "synthetic\n",
      "release_test_source_snapshot.py": "# synthetic\n",
      "protocol_pending_snapshot.md": "synthetic\n",
      "status_pending_snapshot.md": "synthetic\n",
      "stage11_negative_audit_log.txt": "synthetic\n"}
  for name, value in readiness_payloads.items():
    path = readiness / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="")
  _write_json(readiness / "release_readiness_test_evidence.json", {"synthetic": True})
  _write_json(readiness / "stage11_negative_audit_source_snapshot.json",
              {"synthetic": True})
  _write_json(readiness / "stage11_negative_audit_result.json", negative_result)
  _write_json(readiness / "stage11_negative_audit_evidence.json", {"synthetic": True})
  readiness_receipt = {
      "approved_freeze_receipt_sha256": freeze_sha,
      "completion_decision": "approved_for_status_finalization",
      "contract_id": contract.STAGE10_CONTRACT_ID,
      "evidence_mode": "deterministic_async_simulation",
      "generation_chain": {
          "checksums_sha256": generation["checksums_sha256"],
          "dispatcher_verifier_status": "stage10_async_simulation_verified",
          "manifest_sha256": generation["manifest_sha256"],
          "native_verifier_status": "stage10_async_simulation_verified",
          "run_identity_sha256": _sha(root / "run_identity.json"),
          "run_state_sha256": _sha(root / "run_state.json"),
          "stage10a": {"manifest_files": 12, "result_count": 5,
                       "status": "verified"},
          "stage9_artifact_sha256_verified_count": 19,
          "synthetic_test_only": True,
          "verification_sha256": _sha(root / "verification.json")},
      "real_system_async_performance_verified": False,
      "release_status": "stage10_release_readiness_verified",
      "release_test_evidence_sha256":
          _sha(readiness / "release_readiness_test_evidence.json"),
      "run_id": contract.STAGE10_RUN_ID,
      "schema_version":
          "capd_proactive_stage10_release_readiness_receipt_v1_0",
      "stage11_negative_audit": {
          "evidence_sha256": _sha(readiness / "stage11_negative_audit_evidence.json"),
          "result": negative_result,
          "result_sha256": _sha(readiness / "stage11_negative_audit_result.json"),
          "source_snapshot_sha256":
              _sha(readiness / "stage11_negative_audit_source_snapshot.json")},
      "stage11_positive_migration_authorized": False,
      "synthetic_test_only": True}
  readiness_receipt_path = _write_json(
      readiness / "release_readiness_receipt.json", readiness_receipt)
  readiness_envelope = _write_stage10_envelope(readiness, "readiness")

  final = receipts / "final-status"
  for name in ("final_status_test_log.txt", "release_test_source_snapshot.py",
               "protocol_final_snapshot.md", "status_final_snapshot.md"):
    path = final / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic\n", encoding="utf-8", newline="")
  _write_json(final / "final_status_test_evidence.json", {"synthetic": True})
  final_receipt = {
      "approved_freeze_receipt_sha256": freeze_sha,
      "completion_decision": "approved_for_status_finalization",
      "contract_id": contract.STAGE10_CONTRACT_ID,
      "final_status_test_evidence_sha256":
          _sha(final / "final_status_test_evidence.json"),
      "readiness_checksums_sha256": readiness_envelope["checksums_sha256"],
      "readiness_manifest_sha256": readiness_envelope["manifest_sha256"],
      "readiness_receipt_sha256": _sha(readiness_receipt_path),
      "real_system_async_performance_verified": False,
      "run_id": contract.STAGE10_RUN_ID,
      "schema_version":
          "capd_proactive_stage10_final_status_evidence_receipt_v1_0",
      "status": "stage10_final_status_evidence_verified",
      "synthetic_test_only": True}
  final_path = _write_json(final / "final_status_evidence_receipt.json", final_receipt)
  _write_stage10_envelope(final, "final_status")
  anchors = {
      "generation_freeze_receipt_sha256": freeze_sha,
      "readiness_receipt_sha256": _sha(readiness_receipt_path),
      "final_status_receipt_sha256": _sha(final_path)}
  return root, anchors


def _make_authorization(path: Path, expected: dict, *, synthetic=True) -> str:
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_execution_authorization_v1_0",
      "contract_id": contract.CONTRACT_ID, **expected,
      "authorized_scope": ("synthetic_fixture_generation_only" if synthetic else
                           "stage11_v2_production_generation"),
      "stage11_execution_authorized": True, "synthetic_test_only": synthetic,
      "test_used_for_parameter_selection": False,
      "future_output_hashes_absent": True}
  _write_json(path, receipt)
  return _sha(path)


def _runner_fixture(temp_root: Path):
  stage8 = _make_stage8(temp_root / "stage8")
  stage9 = _make_stage9(temp_root / "stage9")
  stage10, anchors = _make_stage10(temp_root / "stage10")
  anchors_path = _write_json(temp_root / "stage10-anchors.json", anchors)
  config = runner._load_repository(CONFIG_PATH)
  sources = runner._source_state(config)
  stage8_value = contract.load_stage8_standard_source(stage8)
  stage9_value = contract.audit_stage9(stage9, STAGE9_SCHEMA, fixture_mode=True)
  stage10_value = contract.audit_stage10_r2(stage10, anchors, fixture_mode=True)
  grid = contract.frozen_grid(config)
  run_id = "synthetic-stage11-v2"
  expected = {
      "run_id": run_id,
      "approved_design_sha256": contract.APPROVED_DESIGN_SHA256,
      "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
      "config_sha256": contract.sha256_file(CONFIG_PATH),
      "result_schema_sha256": contract.sha256_file(RESULT_SCHEMA),
      "generation_source_manifest_sha256": sources["generation"]["manifest_sha256"],
      "generation_source_members_sha256": sources["generation"]["members_sha256"],
      "verifier_source_manifest_sha256": sources["verifier"]["manifest_sha256"],
      "verifier_source_members_sha256": sources["verifier"]["members_sha256"],
      "standard_source_manifest_sha256":
          stage8_value["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": stage8_value["sorted_job_ids_sha256"],
      "stage9_input_receipt_sha256": hashlib.sha256(
          runner._json_bytes(stage9_value)).hexdigest(),
      "stage10_input_receipt_sha256": hashlib.sha256(
          runner._json_bytes(stage10_value)).hexdigest(),
      "frozen_grid_sha256": grid["frozen_grid_sha256"]}
  authorization_path = temp_root / "execution-authorization.json"
  authorization_sha = _make_authorization(authorization_path, expected)
  args = argparse.Namespace(
      config=str(CONFIG_PATH), synthetic_test_only=True,
      test_temp_root=str(temp_root), output_root=str(temp_root / "generation"),
      run_id=run_id, stage8_root=str(stage8), stage9_root=str(stage9),
      stage10_root=str(stage10), stage10_anchors=str(anchors_path),
      authorization_receipt=str(authorization_path),
      authorization_receipt_sha256=authorization_sha)
  return args, stage8, expected


def _generate(temp_root: Path):
  args, stage8, expected = _runner_fixture(temp_root)
  return runner.execute_synthetic(args), stage8, expected


def _verify_fixture(run_root: Path, stage8: Path):
  return verifier.verify_generation(
      run_root, stage8,
      expected_approved_plan_sha256=contract.APPROVED_PLAN_SHA256,
      synthetic_mode=True, project_root=ROOT,
      generation_source_manifest=(
          ROOT / "configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json"),
      verifier_source_manifest=(
          ROOT / "configs/finals/capd_proactive_stage11_v2_verifier_source_manifest.json"))


def _final_approval(root: Path, run_id="synthetic-stage11-v2"):
  receipt = {
      "schema_version": "capd_proactive_stage11_v2_final_approval_receipt_v1_0",
      "contract_id": contract.CONTRACT_ID, "run_id": run_id,
      "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
      "approval_decision": "approved_for_stage11_finalization",
      "approval_authority": "synthetic-test", "approval_reference": "fixture",
      "approval_timestamp": "2026-08-07T00:00:00Z",
      "execution_authorization_receipt_sha256": "1" * 64,
      "generation_artifact_sha256": "2" * 64,
      "verification_receipt_sha256": "3" * 64,
      "verification_manifest_sha256": "4" * 64,
      "verification_checksums_sha256": "5" * 64,
      "standard_source_manifest_sha256": "6" * 64,
      "sorted_job_ids_sha256": "7" * 64,
      "standard_job_count": 48, "standard_workload_count": 6,
      "stage11_generation_verified": True,
      "stage11_final_approval_granted": True,
      "test_used_for_parameter_selection": False,
      "evidence_scope": "synthetic_contract_test", "synthetic_test_only": True}
  _write_json(root / "final_approval_receipt.json", receipt)
  hashes = _write_envelope(root, "final_approval", contract.CONTRACT_ID)
  hashes["receipt_sha256"] = _sha(root / "final_approval_receipt.json")
  return receipt, hashes


class Stage11V2NoRealUpstreamAccessTest(unittest.TestCase):
  def test_real_upstream_open_is_denied(self):
    before = len(REAL_DENIED_OPENS)
    with self.assertRaises(PermissionError):
      open(REAL_ROOTS[0] / "run_state.json", "rb")
    self.assertEqual(len(REAL_DENIED_OPENS), before + 1)
    self.assertEqual(REAL_SUCCESSFUL_OPENS, [])


class Stage11V2ApprovalChainTest(unittest.TestCase):
  def test_approved_chain_matches_external_hashes(self):
    config = contract.load_json_strict(CONFIG_PATH)
    self.assertEqual(contract.validate_approval_chain(ROOT, config), {
        "approved_design_sha256": contract.APPROVED_DESIGN_SHA256,
        "approved_plan_sha256": contract.APPROVED_PLAN_SHA256})

  def test_wrong_plan_sha_fails_closed(self):
    config = copy.deepcopy(contract.load_json_strict(CONFIG_PATH))
    config["approved_plan"]["sha256"] = "0" * 64
    with self.assertRaises(contract.Stage11V2ContractError):
      contract.validate_approval_chain(ROOT, config)


class Stage11V2ConfigTest(unittest.TestCase):
  def test_repository_config_is_frozen(self):
    config = contract.load_json_strict(CONFIG_PATH)
    contract.validate_config(config)
    self.assertEqual(config["main_control"]["b_max"], 2)
    self.assertEqual(len(config["cost_profiles"]), 4)

  def test_unknown_field_and_changed_grid_are_rejected(self):
    config = copy.deepcopy(contract.load_json_strict(CONFIG_PATH))
    config["unknown"] = True
    with self.assertRaises(contract.Stage11V2ContractError):
      contract.validate_config(config)
    del config["unknown"]
    config["analysis_grid"]["b_max"] = [1, 4]
    with self.assertRaises(contract.Stage11V2ContractError):
      contract.validate_config(config)


class Stage11V2SourceClosureTest(unittest.TestCase):
  def test_repository_source_sets_are_exact_and_independent(self):
    generation = contract.source_manifest_value(ROOT, "generation")
    verification = contract.source_manifest_value(ROOT, "verifier")
    self.assertNotIn("qmap/proactive_stage11_v2.py",
                     {row["path"] for row in verification["members"]})
    self.assertNotIn("qmap/proactive_cost.py",
                     {row["path"] for row in verification["members"]})
    contract.validate_source_manifest(ROOT, generation, "generation")
    contract.validate_source_manifest(ROOT, verification, "verifier")

  def test_dependency_omission_and_v1_leak_fail(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      _write_json(root / "unused.json", {})
      (root / "qmap").mkdir()
      (root / "qmap" / "a.py").write_text(
          "from qmap import b\n", encoding="utf-8")
      (root / "qmap" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
      with mock.patch.object(contract, "GENERATION_SOURCE_PATHS", ("qmap/a.py",)):
        manifest = contract.source_manifest_value(root, "generation")
        with self.assertRaises(contract.Stage11V2ContractError):
          contract.validate_source_manifest(root, manifest, "generation")
      (root / "qmap" / "proactive_stage11.py").write_text(
          "VALUE = 1\n", encoding="utf-8")
      with mock.patch.object(contract, "GENERATION_SOURCE_PATHS",
                             ("qmap/proactive_stage11.py",)):
        manifest = contract.source_manifest_value(root, "generation")
        with self.assertRaises(contract.Stage11V2ContractError):
          contract.validate_source_manifest(root, manifest, "generation")

  def test_source_snapshot_detects_same_length_mutation(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      path = root / "qmap" / "a.py"
      path.parent.mkdir()
      path.write_text("VALUE=1\n", encoding="utf-8")
      with mock.patch.object(contract, "GENERATION_SOURCE_PATHS", ("qmap/a.py",)):
        manifest = contract.source_manifest_value(root, "generation")
        before = contract.snapshot_source_manifest(root, manifest)
        path.write_text("VALUE=2\n", encoding="utf-8")
        after = contract.snapshot_source_manifest(root, manifest)
      self.assertNotEqual(before, after)

  def test_independent_verifier_rejects_empty_source_manifest(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      forged = {
          "schema_version": "capd_proactive_stage11_v2_source_manifest_v1_0",
          "contract_id": contract.CONTRACT_ID, "role": "generation",
          "approved_design_sha256": contract.APPROVED_DESIGN_SHA256,
          "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
          "members": [], "member_count": 0,
          "members_sha256": verifier.sha256_value([]),
          "local_import_closure_complete": True,
          "exclusions": list(verifier.SOURCE_EXCLUSIONS)}
      path = _write_json(root / "generation-manifest.json", forged)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        verifier.validate_source_manifest(root, path, "generation")


class Stage11V2PrimitiveTest(unittest.TestCase):
  def test_strict_json_and_non_finite_values(self):
    with tempfile.TemporaryDirectory() as temporary:
      path = Path(temporary) / "bad.json"
      path.write_text('{"x":1,"x":2}', encoding="utf-8")
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.load_json_strict(path)
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.canonical_json_bytes({"x": float("nan")})

  def test_manifest_checksum_and_tamper_detection(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      cap = path_guard.authorize_write_context(
          "synthetic", root / "run", "run", {"synthetic_test_only": True},
          test_temp_root=root, production_root=ROOT / "outputs/capd_proactive_stage11_v2")
      contract.atomic_write_text(cap, "payload.txt", "original\n")
      contract.write_release_envelope(cap, "generation")
      contract.verify_release_envelope(cap.root, "generation")
      (cap.root / "payload.txt").write_text("tampered\n", encoding="utf-8")
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.verify_release_envelope(cap.root, "generation")

  def test_extra_file_and_duplicate_checksum_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      cap = path_guard.authorize_write_context(
          "synthetic", root / "run", "run", {"synthetic_test_only": True},
          test_temp_root=root, production_root=ROOT / "outputs/capd_proactive_stage11_v2")
      contract.atomic_write_text(cap, "payload.txt", "value\n")
      contract.write_release_envelope(cap, "generation")
      contract.atomic_write_text(cap, "extra.txt", "extra\n")
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.verify_release_envelope(cap.root, "generation")
      (cap.root / "extra.txt").unlink()
      checksum = cap.root / "SHA256SUMS"
      checksum.write_text(checksum.read_text(encoding="utf-8") +
                          checksum.read_text(encoding="utf-8").splitlines()[0] + "\n",
                          encoding="utf-8", newline="")
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.verify_release_envelope(cap.root, "generation")


class Stage11V2StandardInputTest(unittest.TestCase):
  def test_exact_48_job_join_and_offline_cost(self):
    with tempfile.TemporaryDirectory() as temporary:
      source = contract.load_stage8_standard_source(
          _make_stage8(Path(temporary) / "stage8"))
      self.assertEqual(source["job_count"], 48)
      rows = contract.recompute_cost_rows(source["rows"][0])
      self.assertEqual(len(rows), 4)
      self.assertTrue(all(row["evidence_status"] == "candidate-ready" for row in rows))

  def test_duplicate_one_missing_one_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = _make_stage8(Path(temporary) / "stage8")
      path = root / "artifacts" / "per_workload_raw.csv"
      with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
      rows[-1] = dict(rows[0])
      with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("job_id", "track"))
        writer.writeheader()
        writer.writerows(rows)
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.load_stage8_standard_source(root)

  def test_zero_access_uses_json_null(self):
    row = {"dram_hits": 0, "nvm_reads": 0, "nvm_writes": 0,
           "total_demotions": 0, "proactive_demotions": 0,
           "reactive_demotions": 0, "emergency_demotions": 0,
           "raw_access_count": 0}
    self.assertIsNone(contract.recompute_cost_rows(row)[0]["weighted_cost_per_access"])
    self.assertEqual(contract.render_missing(None), "N/A")


class Stage11V2Stage9GateTest(unittest.TestCase):
  def test_schema_native_fixture_is_structurally_verified_not_authorized(self):
    with tempfile.TemporaryDirectory() as temporary:
      result = contract.audit_stage9(
          _make_stage9(Path(temporary) / "stage9"), STAGE9_SCHEMA,
          fixture_mode=True)
      self.assertEqual(result["status"], "synthetic_structure_verified")
      self.assertFalse(result["authorized_external_input"])

  def test_perf_rss_and_hash_tamper_fail_closed(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = _make_stage9(Path(temporary) / "stage9")
      perf = contract.load_json_strict(root / "perf" / "perf_parsed.json")
      perf["events"]["cycles"]["status"] = "not_supported"
      _write_json(root / "perf" / "perf_parsed.json", perf)
      result = contract.audit_stage9(root, STAGE9_SCHEMA, fixture_mode=True)
      self.assertEqual(result["status"], "NOT_VERIFIABLE")
      self.assertFalse(result["authorized_external_input"])

  def test_formal_bmax_or_test_selection_change_fails_closed(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = _make_stage9(Path(temporary) / "stage9")
      verification = contract.load_json_strict(root / "verification.json")
      verification["formal_b_max"] = 4
      verification["test_used_for_parameter_selection"] = True
      _write_json(root / "verification.json", verification)
      result = contract.audit_stage9(root, STAGE9_SCHEMA, fixture_mode=True)
      self.assertEqual(result["status"], "NOT_VERIFIABLE")


class Stage11V2Stage10GateTest(unittest.TestCase):
  def test_sealed_fixture_identity_is_not_external_authorization(self):
    with tempfile.TemporaryDirectory() as temporary:
      root, anchors = _make_stage10(Path(temporary) / "stage10")
      result = contract.audit_stage10_r2(root, anchors, fixture_mode=True)
      self.assertEqual(result["status"], "synthetic_structure_verified")
      self.assertTrue(result["generation_source_set_match"])
      self.assertFalse(result["repository_revision_match"])
      self.assertEqual(result["current_live_replay_compatibility"], "NOT_VERIFIABLE")
      self.assertFalse(result["authorized_external_input"])

  def test_wrong_anchor_and_real_system_flag_fail_closed(self):
    with tempfile.TemporaryDirectory() as temporary:
      root, anchors = _make_stage10(Path(temporary) / "stage10")
      bad = dict(anchors)
      bad["readiness_receipt_sha256"] = "0" * 64
      self.assertEqual(contract.audit_stage10_r2(
          root, bad, fixture_mode=True)["status"], "NOT_VERIFIABLE")
      final_path = (root.parent / "release_receipts" / contract.STAGE10_RUN_ID /
                    "final-status" /
                    "final_status_evidence_receipt.json")
      final = contract.load_json_strict(final_path)
      final[contract.REAL_SYSTEM_FLAGS[0]] = True
      _write_json(final_path, final)
      _write_stage10_envelope(final_path.parent, "final_status")
      bad_anchors = dict(anchors)
      bad_anchors["final_status_receipt_sha256"] = _sha(final_path)
      self.assertEqual(contract.audit_stage10_r2(
          root, bad_anchors, fixture_mode=True)["status"], "NOT_VERIFIABLE")

  def test_wrong_sealed_run_identity_fails_even_after_rehash(self):
    with tempfile.TemporaryDirectory() as temporary:
      root, anchors = _make_stage10(Path(temporary) / "stage10")
      identity = contract.load_json_strict(root / "run_identity.json")
      identity["run_id"] = "stage10-async-simulator-v2-r1"
      _write_json(root / "run_identity.json", identity)
      _write_stage10_envelope(root, "generation")
      self.assertEqual(contract.audit_stage10_r2(
          root, anchors, fixture_mode=True)["status"], "NOT_VERIFIABLE")


class Stage11V2AuthorizationTest(unittest.TestCase):
  def test_external_sha_and_all_bindings_are_required(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      expected = {name: "a" * 64 for name in (
          "approved_design_sha256", "approved_plan_sha256", "config_sha256",
          "result_schema_sha256", "generation_source_manifest_sha256",
          "generation_source_members_sha256", "verifier_source_manifest_sha256",
          "verifier_source_members_sha256", "standard_source_manifest_sha256",
          "sorted_job_ids_sha256", "stage9_input_receipt_sha256",
          "stage10_input_receipt_sha256", "frozen_grid_sha256")}
      expected["run_id"] = "run"
      path = root / "authorization.json"
      digest = _make_authorization(path, expected)
      contract.validate_execution_authorization(path, digest, expected,
                                                synthetic_mode=True)
      receipt = contract.load_json_strict(path)
      receipt["approved_plan_sha256"] = "b" * 64
      _write_json(path, receipt)
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.validate_execution_authorization(
            path, _sha(path), expected, synthetic_mode=True)

  def test_rehash_does_not_replace_external_anchor(self):
    with tempfile.TemporaryDirectory() as temporary:
      expected = {name: "a" * 64 for name in (
          "approved_design_sha256", "approved_plan_sha256", "config_sha256",
          "result_schema_sha256", "generation_source_manifest_sha256",
          "generation_source_members_sha256", "verifier_source_manifest_sha256",
          "verifier_source_members_sha256", "standard_source_manifest_sha256",
          "sorted_job_ids_sha256", "stage9_input_receipt_sha256",
          "stage10_input_receipt_sha256", "frozen_grid_sha256")}
      expected["run_id"] = "run"
      path = Path(temporary) / "authorization.json"
      original = _make_authorization(path, expected)
      receipt = contract.load_json_strict(path)
      receipt["run_id"] = "other"
      _write_json(path, receipt)
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.validate_execution_authorization(path, original, expected,
                                                  synthetic_mode=True)

  def test_future_output_hash_and_unknown_field_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      expected = {name: "a" * 64 for name in (
          "approved_design_sha256", "approved_plan_sha256", "config_sha256",
          "result_schema_sha256", "generation_source_manifest_sha256",
          "generation_source_members_sha256", "verifier_source_manifest_sha256",
          "verifier_source_members_sha256", "standard_source_manifest_sha256",
          "sorted_job_ids_sha256", "stage9_input_receipt_sha256",
          "stage10_input_receipt_sha256", "frozen_grid_sha256")}
      expected["run_id"] = "run"
      path = Path(temporary) / "authorization.json"
      _make_authorization(path, expected)
      receipt = contract.load_json_strict(path)
      receipt["result_sha256"] = "b" * 64
      _write_json(path, receipt)
      with self.assertRaises(contract.Stage11V2ContractError):
        contract.validate_execution_authorization(
            path, _sha(path), expected, synthetic_mode=True)


class Stage11V2PathGuardTest(unittest.TestCase):
  def test_synthetic_escape_and_production_mix_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      with self.assertRaises(path_guard.Stage11V2PathError):
        path_guard.authorize_write_context(
            "synthetic", root.parent / "escape", "run",
            {"synthetic_test_only": True}, test_temp_root=root,
            production_root=ROOT / "outputs/capd_proactive_stage11_v2")
      with self.assertRaises(path_guard.Stage11V2PathError):
        path_guard.authorize_write_context(
            "production", ROOT / "outputs/capd_proactive_stage11_v2/run",
            "run", {"synthetic_test_only": True},
            production_root=ROOT / "outputs/capd_proactive_stage11_v2",
            production_enabled=True)

  def test_direct_writer_bypass_and_relative_escape_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      with self.assertRaises(path_guard.Stage11V2PathError):
        contract.atomic_write_text(root / "bare", "x", "bad")
      cap = path_guard.authorize_write_context(
          "synthetic", root / "run", "run", {"synthetic_test_only": True},
          test_temp_root=root, production_root=ROOT / "outputs/capd_proactive_stage11_v2")
      with self.assertRaises(path_guard.Stage11V2PathError):
        contract.atomic_write_text(cap, "../escape", "bad")


class Stage11V2RunnerTest(unittest.TestCase):
  def test_audit_defaults_to_not_run(self):
    result = runner.audit_inputs(CONFIG_PATH, False)
    self.assertEqual(result["real_upstream_audit"], "NOT_RUN")
    self.assertFalse(result["stage11_execution_authorized"])

  def test_synthetic_generation_is_candidate_ready_only(self):
    with tempfile.TemporaryDirectory() as temporary:
      run_root, _, _ = _generate(Path(temporary))
      state = contract.load_json_strict(run_root / "run_state.json")
      results = contract.load_json_strict(run_root / "stage11_v2_results.json")
      self.assertEqual(state["status"],
                       "stage11_generation_complete_pending_verification")
      self.assertFalse(state["stage11_formally_verified"])
      self.assertEqual(len(results["rows"]), 192)
      self.assertEqual({row["evidence_status"] for row in results["rows"]},
                       {"candidate-ready"})

  def test_production_target_is_rejected_before_fixture_reads(self):
    with tempfile.TemporaryDirectory() as temporary:
      temp = Path(temporary)
      dummy = _write_json(temp / "dummy.json", {})
      args = argparse.Namespace(
          config=str(CONFIG_PATH), synthetic_test_only=True,
          test_temp_root=str(temp),
          output_root=str(ROOT / "outputs/capd_proactive_stage11_v2"),
          run_id="run", stage8_root=str(temp / "missing-stage8"),
          stage9_root=str(temp / "missing-stage9"),
          stage10_root=str(temp / "missing-stage10"), stage10_anchors=str(dummy),
          authorization_receipt=str(dummy), authorization_receipt_sha256="0" * 64)
      with self.assertRaises(path_guard.Stage11V2PathError):
        runner.execute_synthetic(args)

  def test_source_change_during_generation_removes_partial_run(self):
    with tempfile.TemporaryDirectory() as temporary:
      temp = Path(temporary)
      args, _, _ = _runner_fixture(temp)
      original = contract.snapshot_source_manifest
      calls = {"count": 0}

      def changed_after_generation(root, manifest):
        calls["count"] += 1
        value = original(root, manifest)
        if calls["count"] >= 3:
          value = copy.deepcopy(value)
          value["snapshot_sha256"] = "0" * 64
        return value

      with mock.patch.object(contract, "snapshot_source_manifest",
                             side_effect=changed_after_generation):
        with self.assertRaises(contract.Stage11V2ContractError):
          runner.execute_synthetic(args)
      self.assertFalse((Path(args.output_root) / args.run_id).exists())


class Stage11V2VerificationTest(unittest.TestCase):
  def test_independent_verifier_recomputes_cost(self):
    with tempfile.TemporaryDirectory() as temporary:
      run_root, stage8, _ = _generate(Path(temporary))
      result = _verify_fixture(run_root, stage8)
      self.assertTrue(result["stage11_generation_verified"])
      self.assertFalse(result["stage11_formally_verified"])
      self.assertEqual(result["generation_source_members_sha256"],
                       contract.load_json_strict(
                           ROOT / "configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json")["members_sha256"])

  def test_rehashed_result_tamper_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      run_root, stage8, _ = _generate(Path(temporary))
      result_path = run_root / "stage11_v2_results.json"
      result = contract.load_json_strict(result_path)
      result["rows"][0]["weighted_cost"] += 1
      _write_json(result_path, result)
      _write_envelope(run_root, "generation", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        _verify_fixture(run_root, stage8)

  def test_rehashed_row_identity_tamper_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      run_root, stage8, _ = _generate(Path(temporary))
      result_path = run_root / "stage11_v2_results.json"
      result = contract.load_json_strict(result_path)
      result["rows"][0]["workload"] = "wrong-workload"
      _write_json(result_path, result)
      _write_envelope(run_root, "generation", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        _verify_fixture(run_root, stage8)

  def test_rehashed_generation_source_binding_tamper_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      run_root, stage8, _ = _generate(Path(temporary))
      authorization_path = run_root / "execution_authorization_receipt.json"
      identity_path = run_root / "run_identity.json"
      authorization = contract.load_json_strict(authorization_path)
      identity = contract.load_json_strict(identity_path)
      authorization["generation_source_manifest_sha256"] = "0" * 64
      identity["generation_source_manifest_sha256"] = "0" * 64
      _write_json(authorization_path, authorization)
      identity["authorization_receipt_sha256"] = _sha(authorization_path)
      _write_json(identity_path, identity)
      _write_envelope(run_root, "generation", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        _verify_fixture(run_root, stage8)


class Stage11V2ReleaseTest(unittest.TestCase):
  def test_synthetic_final_chain_cannot_become_formal(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      approval_root = root / "approval"
      approval, hashes = _final_approval(approval_root)
      validated = verifier.validate_final_approval(
          approval_root, hashes["receipt_sha256"])
      cap = path_guard.authorize_write_context(
          "synthetic", root / "final-status", approval["run_id"],
          {"synthetic_test_only": True}, test_temp_root=root,
          production_root=ROOT / "outputs/capd_proactive_stage11_v2")
      final_hashes = verifier.build_synthetic_final_status(cap, validated, hashes)
      consumed = verifier.consume_final_status(
          cap.root, final_hashes["receipt_sha256"])
      self.assertEqual(consumed["status"], "BLOCKED")
      self.assertFalse(consumed["stage11_formally_verified"])

  def test_wrong_run_and_wrong_verification_binding_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "approval"
      approval, hashes = _final_approval(root)
      expected = {
          "run_id": approval["run_id"],
          "verification_receipt_sha256": approval["verification_receipt_sha256"]}
      approval["run_id"] = "wrong"
      approval["verification_receipt_sha256"] = "9" * 64
      _write_json(root / "final_approval_receipt.json", approval)
      _write_envelope(root, "final_approval", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        verifier.validate_final_approval(
            root, _sha(root / "final_approval_receipt.json"), expected=expected)

  def test_final_approval_extra_field_and_wrong_phase_are_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "approval"
      approval, _ = _final_approval(root)
      approval["unexpected"] = True
      _write_json(root / "final_approval_receipt.json", approval)
      _write_envelope(root, "verification", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        verifier.validate_final_approval(
            root, _sha(root / "final_approval_receipt.json"))

  def test_rehashed_incomplete_formal_final_status_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "final-status"
      receipt = {
          "status": "stage11_formally_verified",
          "authorized_external_input": True,
          "stage11_execution_authorized": True,
          "stage11_generation_verified": True,
          "stage11_final_approval_verified": True,
          "stage11_final_status_evidence_verified": True,
          "stage11_formally_verified": True,
          "synthetic_test_only": False}
      path = _write_json(root / "final_status_evidence_receipt.json", receipt)
      _write_envelope(root, "final_status", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        verifier.consume_final_status(root, _sha(path), expected={})

  def test_rehashed_formal_final_status_binding_tamper_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary) / "final-status"
      bindings = {
          "run_id": "formal-run",
          "execution_authorization_receipt_sha256": "1" * 64,
          "generation_artifact_sha256": "2" * 64,
          "verification_artifact_sha256": "3" * 64,
          "final_approval_receipt_sha256": "4" * 64,
          "final_approval_manifest_sha256": "5" * 64,
          "final_approval_checksums_sha256": "6" * 64,
          "standard_source_manifest_sha256": "7" * 64,
          "sorted_job_ids_sha256": "8" * 64}
      receipt = {
          "schema_version":
              "capd_proactive_stage11_v2_final_status_evidence_receipt_v1_0",
          "contract_id": contract.CONTRACT_ID,
          "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
          **bindings, "status": "stage11_formally_verified",
          "authorized_external_input": True,
          "stage11_execution_authorized": True,
          "stage11_generation_verified": True,
          "stage11_final_approval_verified": True,
          "stage11_final_status_evidence_verified": True,
          "stage11_formally_verified": True,
          "test_used_for_parameter_selection": False,
          "synthetic_test_only": False}
      receipt["verification_artifact_sha256"] = "9" * 64
      path = _write_json(root / "final_status_evidence_receipt.json", receipt)
      _write_envelope(root, "final_status", contract.CONTRACT_ID)
      with self.assertRaises(verifier.Stage11V2VerificationError):
        verifier.consume_final_status(root, _sha(path), expected=bindings)


class Stage11V2DocumentationTest(unittest.TestCase):
  def test_protocol_and_status_preserve_claim_boundaries(self):
    protocol = (ROOT / "docs/CAPD_PROACTIVE_STAGE11_V2_PROTOCOL_CN.md").read_text(
        encoding="utf-8")
    status = (ROOT / "docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md").read_text(
        encoding="utf-8")
    for token in (contract.APPROVED_DESIGN_SHA256, contract.APPROVED_PLAN_SHA256,
                  "Standard", "48", "sealed", "null", "N/A"):
      self.assertIn(token, protocol)
    for token in ("implemented", "candidate-ready", "BLOCKED", "NOT_RUN",
                  "NOT_AVAILABLE", "formally verified"):
      self.assertIn(token, status)


class Stage11V2CompatibilityTest(unittest.TestCase):
  def test_v1_is_static_only_and_synthetic_shape_isolated(self):
    expected = {
        "qmap/proactive_stage11.py":
            (26699, "04869e08b59e8f661d9dc3ca8c2eeae769480b94e79f6bf3c7e059ec633572bc"),
        "scripts/run_capd_proactive_stage11.py":
            (22926, "20021cd62342ab452b9e5ba545b82978086ad80f37aa1f3c3a2230c01fac985d"),
        "configs/finals/capd_proactive_stage11a.json":
            (1992, "c01dd4da275c52aa40dc52a147815bbc298296c6c1fbdecb67752579c9ad7ce2"),
        "configs/finals/capd_proactive_stage11a_result_schema.json":
            (1877, "73ae4e19ea9bb68a0ba100e8ef9485cb06a1fdf9eebe69423a1b955c7c252f97"),
        "tests/test_capd_proactive_stage11.py":
            (15611, "a297a0715344e1c8be94d672faaf69b807b7f3bf784ee7967785c69e342a5ca7")}
    for relative, (length, digest) in expected.items():
      path = ROOT / relative
      self.assertTrue(path.is_file(), relative)
      self.assertEqual(path.stat().st_size, length, relative)
      self.assertEqual(_sha(path), digest, relative)
    with tempfile.TemporaryDirectory() as temporary:
      fixture = _write_json(Path(temporary) / "stage11-v1-shaped.json", {
          "status": "BLOCKED", "synthetic_test_only": True,
          "stage11_formally_verified": False})
      value = contract.load_json_strict(fixture)
      self.assertTrue(value["synthetic_test_only"])
      self.assertFalse(value["stage11_formally_verified"])


def tearDownModule():
  if REAL_SUCCESSFUL_OPENS:
    raise AssertionError("Synthetic suite opened real upstream evidence: {}".format(
        REAL_SUCCESSFUL_OPENS))
