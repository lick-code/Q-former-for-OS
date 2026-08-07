"""Compact synthetic evidence helpers for CAPD Stage10 v2 tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="")


def rebind_verification(stage10_v2, binding, run_root: Path):
    return replace(
        binding,
        verification_sha256=stage10_v2.sha256_file(run_root / "verification.json"),
    )


def build_synthetic_stage9(project_root: Path, stage10_v2):
    """Build a tiny Stage9-shaped tree and its explicit trusted test binding."""
    config_path = project_root / "configs/finals/capd_proactive_stage9.json"
    schema_path = project_root / "configs/finals/capd_proactive_stage9_result_schema.json"
    output_root = project_root / "outputs/capd_proactive_stage9"
    run_root = output_root / "stage9-overhead-v2-r3"
    run_root.mkdir(parents=True)

    required = [
        "run_identity.json", "resolved_config.json",
        "stage8_compatibility_receipt.json", "preflight.json",
        "environment.json", "measurement_checkpoint.json",
        "raw_latency_samples.csv", "latency_summary.json",
        "throughput_summary.json", "quality_summary.json",
        "instrumentation_audit.json", "perf/perf-stat.raw",
        "perf/perf_parsed.json", "perf/perf_scope_counts.json",
        "memory_breakdown.json", "capacity_overhead.csv",
        "artifacts/report_cn.md", "logs/stage1_stage9_regression.log",
        "server_test_receipt.json", "verification.json", "run_state.json",
    ]
    schema = {
        "schema_version": "capd_proactive_stage9_result_schema_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "required_run_artifacts": required,
        "perf_required_events": ["cycles", "instructions", "task-clock"],
        "memory_rss_required_fields": [
            "process_baseline_rss_bytes", "process_baseline_rss_mib",
            "total_peak_rss_bytes", "total_peak_rss_mib",
            "stage9_incremental_peak_rss_bytes",
            "stage9_incremental_peak_rss_mib",
        ],
        "verification_required": {
            "status": "stage9_overhead_verified",
            "stage10_entry_gate": "satisfied",
            "stage8_entry_gate": "satisfied",
            "device": "cpu", "linux_measurement": True,
            "perf_cycles_verified": True, "memory_verified": True,
            "raw_to_summary_verified": True,
            "instrumentation_semantics_verified": True,
            "stage8_compatibility_receipt_verified": True,
            "test_used_for_parameter_selection": False,
            "formal_b_max": 2, "fair_capacity_replay_status": "deferred",
        },
    }
    write_json(schema_path, schema)
    config = {
        "schema_version": "capd_proactive_stage9_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "result_schema": "configs/finals/capd_proactive_stage9_result_schema.json",
        "result_schema_sha256": stage10_v2.sha256_file(schema_path),
        "measurement_matrix": {
            "quality_job_count": 3,
            "formal_instrumentation_job_count": 1,
            "jobs_per_b_max": 1,
            "track_workload_cell_count": 1,
        },
        "sensitivity": {"b_max_values": [1, 2, 4], "formal_b_max": 2},
    }
    write_json(config_path, config)
    config_sha = stage10_v2.sha256_file(config_path)
    internal_identity = "c" * 64
    resolved = dict(config)
    resolved.update({
        "config_sha256": config_sha,
        "run_id": "stage9-overhead-v2-r3",
        "run_identity_sha256": internal_identity,
    })
    write_json(run_root / "resolved_config.json", resolved)
    write_json(run_root / "run_identity.json", {
        "schema_version": "capd_proactive_stage9_run_identity_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "run_id": "stage9-overhead-v2-r3", "config_sha256": config_sha,
        "result_schema_sha256": config["result_schema_sha256"],
        "formal_b_max": 2, "run_identity_sha256": internal_identity,
    })
    write_json(run_root / "stage8_compatibility_receipt.json", {
        "schema_version": "capd_proactive_stage9_stage8_compatibility_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "stage8_contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "stage8_status": "stage8_sync_replay_verified",
        "stage9_entry_gate": "satisfied", "stage8_run_state_verified": True,
        "stage4_sha_chain_verified": True, "job_results_verified": True,
        "statistics_verified": True, "stage8_artifacts_read_only": True,
        "test_used_for_parameter_selection": False,
    })
    write_json(run_root / "preflight.json", {
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0", "status": "passed",
        "device": "cpu", "stage8_stage9_entry_gate": "satisfied",
        "stage8_status": "stage8_sync_replay_verified",
        "stage8_artifacts_read_only": True,
        "test_used_for_parameter_selection": False,
    })
    write_json(run_root / "environment.json", {
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0", "system": "Linux",
        "device": "cpu", "linux_kernel": "synthetic-linux",
    })
    raw = b"sample_kind,total_round_latency_ns\nformal,2252304\n"
    (run_root / "raw_latency_samples.csv").write_bytes(raw)

    cells = [
        {"track": "standard", "workload": "tiny", "seed": 3136859,
         "b_max": b_max, "effective_warmup_rounds": 1}
        for b_max in (1, 2, 4)
    ]
    quality_rows = [dict(row, D=8, F_low=1, F_target=2,
                         checkpoint_sha256="d" * 64,
                         trace_sha256="e" * 64)
                    for row in cells]
    checkpoint = {
        "schema_version": "capd_proactive_stage9_measurement_checkpoint_v2_0",
        "status": "completed", "failure": None, "completed_cells": cells,
        "quality_row_count": 3, "instrumentation_audit_count": 1,
        "raw_partial_path": "raw_latency_samples.csv",
        "raw_partial_bytes": len(raw),
        "raw_sha256": stage10_v2.sha256_file(run_root / "raw_latency_samples.csv"),
    }
    write_json(run_root / "measurement_checkpoint.json", checkpoint)
    write_json(run_root / "quality_summary.json", {
        "schema_version": "capd_proactive_stage9_quality_v2_0",
        "formal_b_max": 2, "test_used_for_parameter_selection": False,
        "rows": quality_rows,
    })
    write_json(run_root / "instrumentation_audit.json", {
        "schema_version": "capd_proactive_stage9_instrumentation_audit_v2_0",
        "status": "identical", "formal_b_max": 2, "job_count": 1,
        "jobs": [{"track": "standard", "workload": "tiny", "seed": 3136859,
                  "b_max": 2, "status": "identical"}],
    })
    write_json(run_root / "latency_summary.json", {
        "schema_version": "capd_proactive_stage9_latency_v2_0",
        "formal_b_max": 2,
        "by_b_max": {"2": {"stages": {"total_round_latency_ns": {
            "count": 182394, "mean": 2252304.4582606885,
            "p50": 2192418.0, "p95": 2625519.0,
            "p99": 2938056.360000004,
        }}}},
    })
    write_json(run_root / "throughput_summary.json", {
        "schema_version": "synthetic", "formal_b_max": 2,
    })
    write_text(run_root / "perf/perf-stat.raw", "1;cycles\n1;instructions\n1;task-clock\n")
    scope = {
        "formal_b_max": 2, "snapshot_count": 1,
        "measured_cells": [{"track": "standard", "workload": "tiny",
                            "seed": 3136859, "b_max": 2}],
        "zero_round_cells": [], "zero_round_job_count": 0,
        "measured_job_ids": ["standard__tiny__capd__seed-3136859"],
        "zero_round_job_ids": [], "measured_rounds": 1,
        "measured_demoted_pages": 2,
    }
    write_json(run_root / "perf/perf_scope_counts.json", scope)
    write_json(run_root / "perf/perf_parsed.json", {
        "counter_source": "linux_perf_hardware", "cycles_verified": True,
        "required_events": ["cycles", "instructions", "task-clock"],
        "required_events_verified": True, "failure_reason": None,
        "events": {name: {"value": 1} for name in
                   ("cycles", "instructions", "task-clock")},
        "scope_counts": scope,
    })
    rss = {
        "process_baseline_rss_bytes": 1, "process_baseline_rss_mib": 1.0,
        "total_peak_rss_bytes": 2, "total_peak_rss_mib": 2.0,
        "stage9_incremental_peak_rss_bytes": 1,
        "stage9_incremental_peak_rss_mib": 1.0,
    }
    write_json(run_root / "memory_breakdown.json", {
        "schema_version": "synthetic", "rss": rss,
        "metadata_bytes_per_page": 64,
    })
    write_text(
        run_root / "capacity_overhead.csv",
        "workload,tracks,baseline_dram_pages,management_memory_bytes,management_pages,capd_effective_dram_pages,capacity_overhead_percent,fair_capacity_replay_status\r\n"
        "tiny,standard,8,4096,1,7,12.5,deferred\r\n",
    )
    write_text(run_root / "artifacts/report_cn.md", "synthetic Stage9 report\n")
    write_text(run_root / "logs/stage1_stage9_regression.log", "Ran 686 tests\nOK\n")
    write_json(run_root / "server_test_receipt.json", {
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0", "status": "passed",
        "minimum_required": 450, "test_count": 686,
        "log_sha256": stage10_v2.sha256_file(
            run_root / "logs/stage1_stage9_regression.log"),
    })

    mapped = [name for name in required
              if name not in ("verification.json", "run_state.json")]
    artifact_sha = {
        name: stage10_v2.sha256_file(run_root / name) for name in mapped
    }
    verification = dict(schema["verification_required"])
    verification.update({
        "schema_version": "capd_proactive_stage9_verification_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "artifact_sha256": artifact_sha,
        "run_identity_sha256": internal_identity,
        "stage8_artifacts_overwritten": False,
    })
    write_json(run_root / "verification.json", verification)
    write_json(run_root / "run_state.json", {
        "schema_version": "capd_proactive_stage9_run_state_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "status": "stage9_overhead_verified", "stage10_entry_gate": "satisfied",
        "failure": None,
    })

    binding = stage10_v2.TrustedStage9Binding(
        project_root=project_root,
        output_root=output_root,
        run_id="stage9-overhead-v2-r3",
        rejected_run_ids=("stage9-overhead-r1", "stage9-overhead-v2-r1",
                          "stage9-overhead-v2-r2"),
        config_path=config_path,
        config_sha256=config_sha,
        result_schema_path=schema_path,
        result_schema_sha256=stage10_v2.sha256_file(schema_path),
        verification_sha256=stage10_v2.sha256_file(run_root / "verification.json"),
        run_state_sha256=stage10_v2.sha256_file(run_root / "run_state.json"),
        checkpoint_sha256=stage10_v2.sha256_file(
            run_root / "measurement_checkpoint.json"),
        latency_summary_sha256=stage10_v2.sha256_file(
            run_root / "latency_summary.json"),
        run_identity_file_sha256=stage10_v2.sha256_file(
            run_root / "run_identity.json"),
        run_identity_sha256=internal_identity,
        stage8_receipt_sha256=stage10_v2.sha256_file(
            run_root / "stage8_compatibility_receipt.json"),
        recovery_audit_sha256="f" * 64,
        expected_artifact_count=19,
        expected_quality_rows=3,
        expected_instrumentation_rows=1,
    )
    return run_root, binding


def synthetic_test_log(path: Path, command: str, count: int = 60) -> str:
    lines = ["COMMAND: " + command]
    modules = (
        "tests.test_capd_proactive_stage10",
        "tests.test_capd_proactive_stage10_v2",
        "tests.test_capd_proactive_stage11",
    )
    lines.extend(
        f"test_case_{index:03d} ({modules[index % len(modules)]}.Synthetic) ... ok"
        for index in range(count)
    )
    lines.extend(["", f"Ran {count} tests in 0.001s", "", "OK", ""])
    write_text(path, "\n".join(lines))
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()
