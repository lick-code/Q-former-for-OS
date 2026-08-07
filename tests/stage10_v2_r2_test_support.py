"""Synthetic-only helpers for Stage10 v2-r2 lifecycle tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from qmap import proactive_stage10_v2_r2 as r2
from tests.stage10_v2_test_support import build_synthetic_stage9, write_json


def build_synthetic_r2(repository_root: Path, project_root: Path, stage10_v2):
    stage9_root, binding = build_synthetic_stage9(project_root, stage10_v2)
    result_schema_source = (
        repository_root / "configs/finals/capd_proactive_stage10_result_schema_v2.json")
    result_schema_target = (
        project_root / "configs/finals/capd_proactive_stage10_result_schema_v2.json")
    result_schema_target.parent.mkdir(parents=True, exist_ok=True)
    result_schema_target.write_bytes(result_schema_source.read_bytes())

    legacy = json.loads((
        repository_root / "configs/finals/capd_proactive_stage10_v2.json"
    ).read_text(encoding="utf-8"))
    config = copy.deepcopy(legacy)
    config.update({
        "schema_version": r2.CONFIG_SCHEMA_VERSION,
        "run_id": r2.RUN_ID,
        "result_schema_sha256": r2.sha256_file(result_schema_target),
        "approved_design": {
            "path": r2.APPROVED_DESIGN_PATH,
            "sha256": r2.APPROVED_DESIGN_SHA256,
            "status": "design_approved",
        },
        "approved_plan": {
            "path": r2.APPROVED_PLAN_PATH,
            "sha256": r2.APPROVED_PLAN_SHA256,
            "status": "implementation_plan_approved_tasks_0_9",
        },
        "controlled_execution": dict(r2.CONTROLLED_EXECUTION),
        "generation_tests": {
            "interpreter_policy": "current_runner_sys_executable",
            "argv_suffix": list(r2.GENERATION_TEST_ARGV_SUFFIX),
            "expected_test_count": 1,
            "ordered_verbose_test_ids": ["synthetic.test"],
        },
        "formal_simulation_worker": {
            "interpreter_policy": "current_runner_sys_executable",
            "argv_suffix": list(r2.FORMAL_WORKER_ARGV_SUFFIX),
        },
    })
    config.pop("test_evidence")
    config["simulator_parameters"]["simulation_horizon_ns"] = 10_000_000
    config["arrival_profiles"][-1]["bursts"] = [
        {"start_ns": 2_000_000, "duration_ns": 1_000_000, "multiplier": "2.0"},
        {"start_ns": 6_000_000, "duration_ns": 1_000_000, "multiplier": "1.6"},
    ]
    config["stage9_binding"].update({
        "config_sha256": binding.config_sha256,
        "result_schema_sha256": binding.result_schema_sha256,
        "verification_sha256": binding.verification_sha256,
        "run_state_sha256": binding.run_state_sha256,
        "checkpoint_sha256": binding.checkpoint_sha256,
        "latency_summary_sha256": binding.latency_summary_sha256,
        "run_identity_file_sha256": binding.run_identity_file_sha256,
        "run_identity_sha256": binding.run_identity_sha256,
        "stage8_receipt_sha256": binding.stage8_receipt_sha256,
        "expected_quality_rows": binding.expected_quality_rows,
        "expected_instrumentation_rows": binding.expected_instrumentation_rows,
    })

    core = project_root / "qmap/synthetic_core.py"
    core.parent.mkdir(parents=True, exist_ok=True)
    core.write_text("VALUE = 1\n", encoding="utf-8", newline="")
    entry = {
        "logical_name": "synthetic_core",
        "path": "qmap/synthetic_core.py",
        "role": "runtime",
        "sha256": r2.sha256_file(core),
        "generation_identity": True,
        "generation_test_groups": ["generation_core"],
    }
    manifest = {
        "schema_version": r2.SOURCE_MANIFEST_SCHEMA,
        "source_set_id": r2.SOURCE_SET_ID,
        "entries": [entry],
    }
    manifest_path = project_root / r2.SOURCE_MANIFEST_PATH
    write_json(manifest_path, manifest)
    snapshot = r2.snapshot_generation_sources(project_root, manifest)
    config["generation_source_manifest"] = {
        "path": r2.SOURCE_MANIFEST_PATH,
        "sha256": r2.sha256_file(manifest_path),
        "schema_version": r2.SOURCE_MANIFEST_SCHEMA,
        "source_set_id": r2.SOURCE_SET_ID,
        "entry_count": snapshot["entry_count"],
        "fingerprint_sha256": snapshot["fingerprint_sha256"],
    }
    receipt_path = project_root / r2.FREEZE_RECEIPT_PATH
    write_json(receipt_path, {
        "schema_version": r2.FREEZE_RECEIPT_SCHEMA,
        "source_set_id": r2.SOURCE_SET_ID,
        "synthetic_test_only": True,
    })
    approved_sha = r2.sha256_file(receipt_path)
    config["generation_freeze_receipt"] = {
        "path": r2.FREEZE_RECEIPT_PATH,
        "schema_version": r2.FREEZE_RECEIPT_SCHEMA,
    }
    config["metadata_schemas"] = {
        name: {"path": f"configs/finals/{name}.json", "sha256": "3" * 64}
        for name in r2.METADATA_SCHEMA_VERSIONS
    }
    config["release_contract"] = r2.expected_release_contract("4" * 64)
    config_path = project_root / r2.CONFIG_PATH
    write_json(config_path, config)
    return {
        "config": config,
        "config_path": config_path,
        "binding": binding,
        "stage9_root": stage9_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "snapshot": snapshot,
        "receipt_path": receipt_path,
        "approved_sha": approved_sha,
    }
