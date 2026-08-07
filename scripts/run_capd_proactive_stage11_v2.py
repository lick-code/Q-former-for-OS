#!/usr/bin/env python3
"""Run Stage11 v2 input audit or an authorized synthetic generation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from qmap import proactive_stage11_v2 as contract
from qmap import proactive_stage11_v2_guard as path_guard


DEFAULT_CONFIG = ROOT / "configs/finals/capd_proactive_stage11_v2.json"
RESULT_SCHEMA = ROOT / "configs/finals/capd_proactive_stage11_v2_result_schema.json"
STAGE9_SCHEMA = ROOT / "configs/finals/capd_proactive_stage9_result_schema.json"


def _json_bytes(value: Any) -> bytes:
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                     allow_nan=False) + "\n").encode("utf-8")


def _bytes_sha(value: bytes) -> str:
  return hashlib.sha256(value).hexdigest()


def _load_repository(config_path: Path) -> Mapping[str, Any]:
  config = contract.load_json_strict(config_path)
  contract.validate_config(config)
  contract.validate_approval_chain(ROOT, config)
  return config


def _source_state(config: Mapping[str, Any]) -> dict[str, Any]:
  values = {}
  for role in ("generation", "verifier"):
    path = ROOT / config["source_manifests"][role]
    manifest = contract.load_json_strict(path)
    contract.validate_source_manifest(ROOT, manifest, role)
    values[role] = {
        "path": path, "manifest": manifest,
        "manifest_sha256": contract.sha256_file(path),
        "members_sha256": manifest["members_sha256"],
        "snapshot": contract.snapshot_source_manifest(ROOT, manifest),
    }
  return values


def audit_inputs(config_path: Path, allow_real_upstream: bool) -> dict[str, Any]:
  config = _load_repository(config_path)
  sources = _source_state(config)
  diagnostic = {
      "contract_id": contract.CONTRACT_ID,
      "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
      "generation_source_manifest_verified": True,
      "verifier_source_manifest_verified": True,
      "real_upstream_audit": "NOT_RUN",
      "stage8_input_verified": None,
      "stage9_input_authorized": None,
      "stage10_input_authorized": None,
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False,
  }
  if not allow_real_upstream:
    return diagnostic
  stage8 = contract.load_stage8_standard_source(ROOT / config["upstream"]["stage8_root"])
  stage9 = contract.audit_stage9(
      ROOT / config["upstream"]["stage9_root"], STAGE9_SCHEMA)
  stage10 = contract.audit_stage10_r2(
      ROOT / config["upstream"]["stage10_root"],
      config["stage10_external_anchors"])
  diagnostic.update({
      "real_upstream_audit": "COMPLETED",
      "stage8_input_verified": stage8["job_count"] == 48,
      "stage9_input_authorized": stage9["authorized_external_input"],
      "stage10_input_authorized": stage10["authorized_external_input"],
      "generation_source_set_match": stage10.get("generation_source_set_match"),
      "repository_revision_match": stage10.get("repository_revision_match"),
      "current_live_replay_compatibility":
          stage10.get("current_live_replay_compatibility"),
      "source_snapshot_sha256": {
          role: values["snapshot"]["snapshot_sha256"]
          for role, values in sources.items()},
  })
  return diagnostic


def _report(rows: list[Mapping[str, Any]]) -> str:
  return "\n".join((
      "# CAPD Stage11 v2 Synthetic Generation",
      "",
      "- evidence status: candidate-ready",
      "- formally verified: false",
      "- synthetic test only: true",
      "- Standard jobs: 48",
      "- Cost rows: {}".format(len(rows)),
      "- Missing numeric rendering: N/A",
      "",
      "This fixture is not formal Stage11 evidence.",
      ""))


def _csv_text(rows: list[Mapping[str, Any]]) -> str:
  fields = (
      "row_id", "run_id", "source_job_id", "track", "workload", "policy",
      "seed", "cost_profile", "dram_hits", "nvm_reads", "nvm_writes",
      "total_demotions", "raw_access_count", "weighted_cost",
      "weighted_cost_per_access", "evidence_mode", "evidence_status")
  output = io.StringIO(newline="")
  writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
  writer.writeheader()
  for row in rows:
    writer.writerow({key: contract.render_missing(row.get(key)) for key in fields})
  return output.getvalue()


def execute_synthetic(args: argparse.Namespace) -> Path:
  config_path = Path(args.config).resolve()
  config = _load_repository(config_path)
  _require_synthetic_args(args, config)
  test_temp_root = Path(args.test_temp_root).resolve()
  output_root = Path(args.output_root).resolve()
  run_root = output_root / args.run_id
  path_guard.validate_synthetic_output_root(
      run_root, test_temp_root, ROOT / config["output_root"])
  fixture_paths = {}
  for field in ("stage8_root", "stage9_root", "stage10_root",
                "stage10_anchors", "authorization_receipt"):
    fixture_paths[field] = path_guard.validate_read_root(
        getattr(args, field), test_temp_root)
  sources = _source_state(config)
  source_before = {role: value["snapshot"] for role, value in sources.items()}

  stage8 = contract.load_stage8_standard_source(fixture_paths["stage8_root"])
  stage9 = contract.audit_stage9(
      fixture_paths["stage9_root"], STAGE9_SCHEMA, fixture_mode=True)
  stage10_anchors = contract.load_json_strict(fixture_paths["stage10_anchors"])
  stage10 = contract.audit_stage10_r2(
      fixture_paths["stage10_root"], stage10_anchors, fixture_mode=True)
  if stage9["status"] != "synthetic_structure_verified":
    raise contract.Stage11V2ContractError("Synthetic Stage9 gate failed: {}".format(stage9))
  if stage10["status"] != "synthetic_structure_verified":
    raise contract.Stage11V2ContractError("Synthetic Stage10 gate failed: {}".format(stage10))

  grid = contract.frozen_grid(config)
  stage8_receipt = {
      "contract_id": contract.CONTRACT_ID, "stage": "stage8",
      "status": "synthetic_structure_verified", "synthetic_test_only": True,
      "job_count": 48, "workload_count": 6,
      "standard_source_manifest_sha256": stage8["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": stage8["sorted_job_ids_sha256"],
  }
  receipt_bytes = {
      "stage8": _json_bytes(stage8_receipt),
      "stage9": _json_bytes(stage9), "stage10": _json_bytes(stage10)}
  expected = {
      "run_id": args.run_id,
      "approved_design_sha256": contract.APPROVED_DESIGN_SHA256,
      "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
      "config_sha256": contract.sha256_file(config_path),
      "result_schema_sha256": contract.sha256_file(RESULT_SCHEMA),
      "generation_source_manifest_sha256":
          sources["generation"]["manifest_sha256"],
      "generation_source_members_sha256": sources["generation"]["members_sha256"],
      "verifier_source_manifest_sha256": sources["verifier"]["manifest_sha256"],
      "verifier_source_members_sha256": sources["verifier"]["members_sha256"],
      "standard_source_manifest_sha256": stage8["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": stage8["sorted_job_ids_sha256"],
      "stage9_input_receipt_sha256": _bytes_sha(receipt_bytes["stage9"]),
      "stage10_input_receipt_sha256": _bytes_sha(receipt_bytes["stage10"]),
      "frozen_grid_sha256": grid["frozen_grid_sha256"],
  }
  authorization = contract.validate_execution_authorization(
      fixture_paths["authorization_receipt"], args.authorization_receipt_sha256,
      expected, synthetic_mode=True)

  if run_root.exists():
    raise contract.Stage11V2ContractError("Run ID already exists; overwrite refused.")
  capability = path_guard.authorize_write_context(
      "synthetic", run_root, args.run_id, authorization,
      test_temp_root=test_temp_root, production_root=ROOT / config["output_root"],
      production_enabled=False)
  try:
    rows = []
    for source in stage8["rows"]:
      for row in contract.recompute_cost_rows(source):
        row.update({"run_id": args.run_id,
                    "row_id": "{}__{}".format(
                        source["source_job_id"], row["cost_profile"])})
        rows.append(row)
    rows.sort(key=lambda row: row["row_id"])
    standard_manifest = {"records": stage8["records"],
                         "standard_source_manifest_sha256":
                             stage8["standard_source_manifest_sha256"],
                         "sorted_job_ids_sha256": stage8["sorted_job_ids_sha256"],
                         "job_count": 48, "workload_count": 6}
    authorization_bytes = fixture_paths["authorization_receipt"].read_bytes()
    run_identity = dict(expected)
    run_identity.update({
        "contract_id": contract.CONTRACT_ID,
        "authorization_receipt_sha256": _bytes_sha(authorization_bytes),
        "code_version": contract.code_version(ROOT),
        "synthetic_test_only": True,
    })
    contract.atomic_write_json(capability, "stage11_v2_config.json", config)
    contract.atomic_write_json(capability, "run_identity.json", run_identity)
    contract.atomic_write_json(capability, "stage8_standard_input_receipt.json",
                               stage8_receipt)
    contract.atomic_write_json(capability, "stage9_input_receipt.json", stage9)
    contract.atomic_write_json(capability, "stage10_input_receipt.json", stage10)
    contract.atomic_write_text(
        capability, "execution_authorization_receipt.json",
        authorization_bytes.decode("utf-8"))
    contract.atomic_write_json(capability, "standard_source_manifest.json",
                               standard_manifest)
    contract.atomic_write_json(capability, "frozen_grid.json", grid)
    contract.atomic_write_json(capability, "stage11_v2_results.json", {
        "schema_version": "capd_proactive_stage11_v2_results_v1_0",
        "contract_id": contract.CONTRACT_ID, "run_id": args.run_id,
        "synthetic_test_only": True, "rows": rows})
    contract.atomic_write_text(capability, "stage11_v2_results.csv", _csv_text(rows))
    contract.atomic_write_text(capability, "stage11_v2_report.md", _report(rows))
    contract.atomic_write_json(capability, "run_state.json", {
        "schema_version": "capd_proactive_stage11_v2_run_state_v1_0",
        "contract_id": contract.CONTRACT_ID, "run_id": args.run_id,
        "status": "stage11_generation_complete_pending_verification",
        "stage11_formally_verified": False, "synthetic_test_only": True})

    source_after = {role: contract.snapshot_source_manifest(ROOT, value["manifest"])
                    for role, value in sources.items()}
    if source_after != source_before:
      raise contract.Stage11V2ContractError("Source changed during generation.")
    contract.write_release_envelope(capability, "generation")
    return run_root
  except Exception:
    if run_root.exists() and run_root.is_relative_to(test_temp_root):
      shutil.rmtree(run_root, ignore_errors=True)
    raise


def _require_synthetic_args(args: argparse.Namespace,
                            config: Mapping[str, Any]) -> None:
  if not args.synthetic_test_only:
    raise contract.Stage11V2Blocked("Production execution is not authorized.")
  for field in ("test_temp_root", "stage8_root", "stage9_root", "stage10_root",
                "stage10_anchors", "authorization_receipt",
                "authorization_receipt_sha256"):
    if not getattr(args, field):
      raise contract.Stage11V2ContractError("Missing synthetic argument: " + field)
  if config.get("production_execution_enabled") is not False:
    raise contract.Stage11V2ContractError("Repository production state changed.")


def parser() -> argparse.ArgumentParser:
  value = argparse.ArgumentParser(description=__doc__)
  value.add_argument("--config", default=str(DEFAULT_CONFIG))
  modes = value.add_mutually_exclusive_group(required=True)
  modes.add_argument("--audit-inputs", action="store_true")
  modes.add_argument("--execute", action="store_true")
  value.add_argument("--allow-real-upstream-audit", action="store_true")
  value.add_argument("--synthetic-test-only", action="store_true")
  value.add_argument("--test-temp-root")
  value.add_argument("--output-root")
  value.add_argument("--run-id")
  value.add_argument("--stage8-root")
  value.add_argument("--stage9-root")
  value.add_argument("--stage10-root")
  value.add_argument("--stage10-anchors")
  value.add_argument("--authorization-receipt")
  value.add_argument("--authorization-receipt-sha256")
  return value


def main(argv: list[str] | None = None) -> int:
  args = parser().parse_args(argv)
  try:
    if args.audit_inputs:
      result = audit_inputs(Path(args.config).resolve(), args.allow_real_upstream_audit)
      print(json.dumps(result, sort_keys=True))
    else:
      if not args.output_root or not args.run_id:
        raise contract.Stage11V2ContractError(
            "Synthetic execute requires output-root and run-id.")
      print(execute_synthetic(args))
    return 0
  except Exception as exc:
    print("stage11-v2: {}".format(exc), file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
