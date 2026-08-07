"""CAPD Stage10 v2 deterministic async-simulation contract.

This module owns the v2 evidence contract.  The event engine remains the
tested Stage10A engine, while all input gates, provenance, result semantics,
and artifact identities are version-specific.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from qmap import proactive_stage10 as engine


CONTRACT_ID = "CAPD-PROACTIVE-STAGE10-2.0"
CONFIG_SCHEMA_VERSION = "capd_proactive_stage10_v2_0"
RESULT_SCHEMA_VERSION = "capd_proactive_stage10_result_v2_0"
EVIDENCE_MODE = "deterministic_async_simulation"
VERIFIED_STATUS = "stage10_async_simulation_verified"
FAILURE_STATUS = "stage10_async_simulation_not_verified"
RUN_ID = "stage10-async-simulator-v2-r1"
STAGE9_GATE_STATUS = "stage10_stage9_input_verified"
REFERENCE_TIMING_PROFILE = "inference-mean__migration-ratio-0p10"
CONVERSION_RULE = "Decimal ROUND_HALF_UP to integral nanoseconds"

APPROVED_DESIGN_PATH = (
    "docs/superpowers/specs/"
    "2026-08-06-stage10-formal-async-simulator-migration-design.md")
APPROVED_DESIGN_SHA256 = (
    "2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd")
RECOVERY_AUDIT_PATH = (
    "docs/superpowers/specs/2026-08-06-stage10-stage9-r3-byte-recovery.json")
RECOVERY_AUDIT_SHA256 = (
    "94a68bfccfa6fec3a947b6ed35f83cca04a09bfe708b9390385d7476e0c5bc64")
PRODUCTION_CONFIG_SHA256 = (
    "0308139288c895cc98e3f96ee7dff25856a9334e48bf8aa226eb88f03a7e326c")
PRODUCTION_CONFIG_CANONICAL_SHA256 = (
    "6bff8f92b70b6d2372dd6b480fb9e7fd2c1eab75fad6da39152db14dd6ab26e9")
STAGE9_PINNED = {
    "config_path": "configs/finals/capd_proactive_stage9.json",
    "config_sha256":
        "642641d56fe52e3772bdaa0772d5c9fd250cc17976918ce99acd36d18a035922",
    "result_schema_path": "configs/finals/capd_proactive_stage9_result_schema.json",
    "result_schema_sha256":
        "a07c1f4b192f76eff45d33fcbe6e37b325aec1a8648c5542538ead1b6ecda893",
    "verification_sha256":
        "bc5dc7fc46247da5d2085dd302150361232ff0cd27cd9b911cb559072ef8635f",
    "run_state_sha256":
        "c862886d04981e63569258e5605994c6bf14afca880122e39777903d30a3e1c3",
    "checkpoint_sha256":
        "8ec44db66348aef3c65459ea48a3b87fc417d862102c85b4fe6bda958bf915d3",
    "latency_summary_sha256":
        "a4e28f6627b278258202d7ab71db72474f29f9e569ca432ebfc40e36baf12a09",
    "run_identity_file_sha256":
        "3241d3df3b1ff701dcc0a571d05f0eacab8412becf1fc960e22df97ef433c2b2",
    "run_identity_sha256":
        "cc662852fa7ee43209d721b5acaae062fb02d790f82e5245ec0511c443987454",
    "stage8_receipt_sha256":
        "fc91e2538e6f88a65fc777ea79fc5d99581f47034a194507c599d58c2b6ba27d",
}


class Stage10V2ContractError(ValueError):
    """Raised when a v2 input or artifact violates the frozen contract."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise Stage10V2ContractError(message)


def sha256_file(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: os.PathLike[str] | str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_json_decimal(path: os.PathLike[str] | str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, parse_float=Decimal)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root.resolve()), str(candidate.resolve()))) == \
            str(root.resolve())
    except (OSError, ValueError):
        return False


def _bound_file(project_root: Path, relative: str, expected_sha256: str) -> Path:
    _require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
             "Bound repository path is invalid.")
    path = project_root / relative
    _require(_inside(project_root, path) and path.is_file() and not path.is_symlink(),
             "Bound repository file is missing or escapes the project root: " + relative)
    _require(sha256_file(path) == expected_sha256,
             "Bound repository SHA256 mismatch: " + relative)
    return path


def _validate_result_schema(value: Mapping[str, Any]) -> None:
    _require(value.get("schema_version") == RESULT_SCHEMA_VERSION,
             "Stage10 v2 result schema version changed.")
    _require(value.get("contract_id") == CONTRACT_ID,
             "Stage10 v2 result schema contract changed.")
    _require(value.get("evidence_mode") == [EVIDENCE_MODE],
             "Result evidence mode is not exclusive.")
    _require(value.get("comparison_channels") ==
             ["fixed_arrival", "capacity_normalized"],
             "Result comparison channels changed.")
    _require(set(value.get("required_arrival_binding", ())) == {
        "arrival_rate_basis", "arrival_reference_profile",
        "arrival_stream_sha256", "absolute_arrival_rate",
        "normalized_load_ratio", "cross_profile_comparison_allowed",
        "cross_profile_comparison_scope"},
        "Result arrival binding is incomplete.")


def validate_config(value: Mapping[str, Any], project_root: Path) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Stage10 v2 config must be an object.")
    _require(fingerprint_value(value) == PRODUCTION_CONFIG_CANONICAL_SHA256,
             "Stage10 v2 config differs from the complete frozen canonical object.")
    _require(value.get("schema_version") == CONFIG_SCHEMA_VERSION,
             "Stage10 v2 config schema mismatch.")
    _require(value.get("contract_id") == CONTRACT_ID,
             "Stage10 v2 contract mismatch.")
    _require(value.get("evidence_mode") == EVIDENCE_MODE,
             "Stage10 v2 evidence mode mismatch.")
    _require(value.get("success_status") == VERIFIED_STATUS and
             value.get("failure_status") == FAILURE_STATUS,
             "Stage10 v2 state names changed.")
    _require(value.get("run_id") == RUN_ID and value.get("scenario_count") == 60,
             "Stage10 v2 run identity or scenario count changed.")

    design = value.get("approved_design", {})
    _require(design == {"path": APPROVED_DESIGN_PATH,
                        "sha256": APPROVED_DESIGN_SHA256,
                        "status": "design_approved"},
             "Approved-design binding is missing or changed.")
    recovery = value.get("byte_recovery_audit", {})
    _require(recovery == {"path": RECOVERY_AUDIT_PATH,
                          "sha256": RECOVERY_AUDIT_SHA256,
                          "status": "byte_recovery_verified"},
             "Stage9 byte-recovery binding is missing or changed.")
    _bound_file(project_root, design["path"], design["sha256"])
    _bound_file(project_root, recovery["path"], recovery["sha256"])

    schema_path = value.get("result_schema")
    schema_sha = value.get("result_schema_sha256")
    _require(schema_path ==
             "configs/finals/capd_proactive_stage10_result_schema_v2.json" and
             isinstance(schema_sha, str) and re.fullmatch(r"[0-9a-f]{64}", schema_sha),
             "Stage10 v2 result-schema binding is invalid.")
    schema = load_json(_bound_file(project_root, schema_path, schema_sha))
    _validate_result_schema(schema)

    stage9 = value.get("stage9_binding", {})
    _require(stage9.get("run_id") == "stage9-overhead-v2-r3" and
             stage9.get("output_root") == "outputs/capd_proactive_stage9" and
             stage9.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             stage9.get("required_artifact_count") == 19 and
             stage9.get("expected_quality_rows") == 90 and
             stage9.get("expected_instrumentation_rows") == 30 and
             stage9.get("rejected_run_ids") == [
                 "stage9-overhead-r1", "stage9-overhead-v2-r1",
                 "stage9-overhead-v2-r2"],
             "Stage9 authority identity is missing or weakened.")
    _require(all(stage9.get(name) == expected
                 for name, expected in STAGE9_PINNED.items()),
             "Stage9 pinned authority SHA/path changed.")
    pinned_names = (
        "config_sha256", "result_schema_sha256", "verification_sha256",
        "run_state_sha256", "checkpoint_sha256", "latency_summary_sha256",
        "run_identity_file_sha256", "run_identity_sha256",
        "stage8_receipt_sha256")
    _require(all(isinstance(stage9.get(name), str) and
                 re.fullmatch(r"[0-9a-f]{64}", stage9[name])
                 for name in pinned_names), "Stage9 SHA binding is incomplete.")

    params = value.get("simulator_parameters", {})
    _require(params == {
        "b_max": 2, "b_t_reference": 2, "dram_capacity_frames": 64,
        "initial_free_frames": 16, "F_low": 16, "F_target": 24,
        "K": 8, "candidate_source": "lru_tail", "seed": 3136859,
        "simulation_horizon_ns": 10000000000},
        "Simulator state parameters changed.")
    _require(value.get("timing_conversion_rule") == CONVERSION_RULE,
             "Timing conversion rule changed.")
    migrations = value.get("migration_scenarios")
    _require(migrations == [
        {"id": "migration-ratio-0p01", "ratio": "0.01",
         "role": "sensitivity_only",
         "source": "predeclared_simulator_scenario_ratio_not_hardware_measurement"},
        {"id": "migration-ratio-0p10", "ratio": "0.10",
         "role": "reference",
         "source": "predeclared_simulator_scenario_ratio_not_hardware_measurement"},
        {"id": "migration-ratio-1p00", "ratio": "1.00",
         "role": "sensitivity_only",
         "source": "predeclared_simulator_scenario_ratio_not_hardware_measurement"}],
        "Migration scenarios are missing, changed, or presented as measured.")
    _require(value.get("comparison_channels") == [
        {"id": "fixed_arrival", "arrival_rate_basis": "reference_profile_fixed",
         "cross_profile_comparison_allowed": True,
         "scope": "timing_sensitivity_within_simulator"},
        {"id": "capacity_normalized", "arrival_rate_basis": "per_profile_mu_demote",
         "cross_profile_comparison_allowed": False,
         "scope": "relative_capacity_pressure_only"}],
        "Comparison-channel contract changed.")
    arrival_ids = [row.get("id") for row in value.get("arrival_profiles", ())]
    _require(arrival_ids == ["uniform-0p5", "uniform-0p8", "uniform-1p0",
                             "uniform-1p2", "burst-reference"],
             "Arrival profile matrix changed.")
    _require(value.get("reference_timing_profile") == REFERENCE_TIMING_PROFILE,
             "Reference timing profile changed.")
    test_evidence = value.get("test_evidence", {})
    _require(test_evidence == {
        "required_module": "tests.test_capd_proactive_stage10_v2",
        "required_modules": [
            "tests.test_capd_proactive_stage10",
            "tests.test_capd_proactive_stage10_v2",
            "tests.test_capd_proactive_stage11"],
        "expected_command":
            "python -m unittest tests.test_capd_proactive_stage10 "
            "tests.test_capd_proactive_stage10_v2 "
            "tests.test_capd_proactive_stage11 -v",
        "minimum_test_count": 60},
        "Stage10 v2 test-evidence identity changed.")
    interpretation = value.get("interpretation_boundary", {})
    _require(interpretation.get("real_system_async_performance_verified") is False and
             interpretation.get("real_nvm_measurement_verified") is False and
             interpretation.get("kernel_behavior_verified") is False and
             interpretation.get("real_concurrency_verified") is False and
             interpretation.get("real_foreground_end_to_end_latency_verified") is False,
             "Real-system interpretation boundary was weakened.")
    return value


def load_repository_config(project_root: os.PathLike[str] | str) -> Mapping[str, Any]:
    root = Path(project_root).resolve()
    path = root / "configs/finals/capd_proactive_stage10_v2.json"
    _require(path.is_file(), "Repository Stage10 v2 config is missing.")
    _require(sha256_file(path) == PRODUCTION_CONFIG_SHA256,
             "Repository Stage10 v2 config byte SHA256 changed.")
    return validate_config(load_json(path), root)


@dataclass(frozen=True)
class TrustedStage9Binding:
    project_root: Path
    output_root: Path
    run_id: str
    rejected_run_ids: Tuple[str, ...]
    config_path: Path
    config_sha256: str
    result_schema_path: Path
    result_schema_sha256: str
    verification_sha256: str
    run_state_sha256: str
    checkpoint_sha256: str
    latency_summary_sha256: str
    run_identity_file_sha256: str
    run_identity_sha256: str
    stage8_receipt_sha256: str
    recovery_audit_sha256: str
    expected_artifact_count: int
    expected_quality_rows: int
    expected_instrumentation_rows: int


@dataclass(frozen=True)
class Stage9Audit:
    receipt: Mapping[str, Any]
    payloads: Mapping[str, Any]
    binding: TrustedStage9Binding


def production_stage9_binding(config: Mapping[str, Any],
                              project_root: os.PathLike[str] | str
                              ) -> TrustedStage9Binding:
    root = Path(project_root).resolve()
    stage9 = config["stage9_binding"]
    return TrustedStage9Binding(
        project_root=root,
        output_root=(root / stage9["output_root"]).resolve(),
        run_id=stage9["run_id"],
        rejected_run_ids=tuple(stage9["rejected_run_ids"]),
        config_path=(root / stage9["config_path"]).resolve(),
        config_sha256=stage9["config_sha256"],
        result_schema_path=(root / stage9["result_schema_path"]).resolve(),
        result_schema_sha256=stage9["result_schema_sha256"],
        verification_sha256=stage9["verification_sha256"],
        run_state_sha256=stage9["run_state_sha256"],
        checkpoint_sha256=stage9["checkpoint_sha256"],
        latency_summary_sha256=stage9["latency_summary_sha256"],
        run_identity_file_sha256=stage9["run_identity_file_sha256"],
        run_identity_sha256=stage9["run_identity_sha256"],
        stage8_receipt_sha256=stage9["stage8_receipt_sha256"],
        recovery_audit_sha256=config["byte_recovery_audit"]["sha256"],
        expected_artifact_count=stage9["required_artifact_count"],
        expected_quality_rows=stage9["expected_quality_rows"],
        expected_instrumentation_rows=stage9["expected_instrumentation_rows"],
    )


def _artifact_path(run_root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and relative and
             not Path(relative).is_absolute() and "\\" not in relative,
             "Stage9 artifact path is invalid.")
    candidate = run_root / relative
    _require(_inside(run_root, candidate) and candidate.is_file() and
             not candidate.is_symlink(),
             "Stage9 artifact is missing, symlinked, or escapes the run: " + relative)
    return candidate


def _cell_identity(row: Mapping[str, Any]) -> Tuple[str, str, int, int]:
    values = (row.get("track"), row.get("workload"), row.get("seed"),
              row.get("b_max"))
    _require(isinstance(values[0], str) and isinstance(values[1], str) and
             isinstance(values[2], int) and not isinstance(values[2], bool) and
             isinstance(values[3], int) and not isinstance(values[3], bool),
             "Stage9 cell identity is malformed.")
    return values  # type: ignore[return-value]


def validate_measurement_checkpoint(run_root: Path,
                                    binding: TrustedStage9Binding,
                                    checkpoint: Mapping[str, Any],
                                    quality: Mapping[str, Any],
                                    instrumentation: Mapping[str, Any],
                                    resolved_config: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(sha256_file(run_root / "measurement_checkpoint.json") ==
             binding.checkpoint_sha256, "Stage9 checkpoint pinned SHA mismatch.")
    _require(checkpoint.get("schema_version") ==
             "capd_proactive_stage9_measurement_checkpoint_v2_0" and
             checkpoint.get("status") == "completed" and
             checkpoint.get("failure") is None,
             "Stage9 measurement checkpoint is incomplete.")
    raw_path = checkpoint.get("raw_partial_path")
    _require(raw_path == "raw_latency_samples.csv",
             "Stage9 checkpoint raw path changed.")
    raw = _artifact_path(run_root, raw_path)
    _require(checkpoint.get("raw_partial_bytes") == raw.stat().st_size and
             checkpoint.get("raw_sha256") == sha256_file(raw),
             "Stage9 checkpoint raw length/SHA mismatch.")

    completed = checkpoint.get("completed_cells")
    quality_rows = quality.get("rows")
    jobs = instrumentation.get("jobs")
    _require(isinstance(completed, list) and isinstance(quality_rows, list) and
             isinstance(jobs, list), "Stage9 checkpoint identity arrays are missing.")
    completed_ids = [_cell_identity(row) for row in completed]
    quality_ids = [_cell_identity(row) for row in quality_rows]
    instrumentation_ids = [_cell_identity(row) for row in jobs]
    _require(len(completed_ids) == len(set(completed_ids)) and
             len(quality_ids) == len(set(quality_ids)) and
             len(instrumentation_ids) == len(set(instrumentation_ids)),
             "Stage9 checkpoint contains duplicate identities.")
    _require(set(completed_ids) == set(quality_ids),
             "Checkpoint completed cells differ from quality identities.")
    formal_ids = {identity for identity in completed_ids if identity[3] == 2}
    _require(formal_ids == set(instrumentation_ids),
             "Formal b_max checkpoint cells differ from instrumentation identities.")
    _require(checkpoint.get("quality_row_count") == len(quality_ids) ==
             binding.expected_quality_rows and
             checkpoint.get("instrumentation_audit_count") ==
             len(instrumentation_ids) == binding.expected_instrumentation_rows and
             instrumentation.get("job_count") == len(instrumentation_ids),
             "Stage9 checkpoint count contract failed.")
    matrix = resolved_config.get("measurement_matrix", {})
    _require(matrix.get("quality_job_count") == len(quality_ids) and
             matrix.get("formal_instrumentation_job_count") ==
             len(instrumentation_ids),
             "Stage9 resolved measurement matrix disagrees with checkpoint.")
    _require({identity[3] for identity in completed_ids} == {1, 2, 4},
             "Stage9 checkpoint b_max coverage changed.")
    return {
        "quality_row_count": len(quality_ids),
        "instrumentation_audit_count": len(instrumentation_ids),
        "completed_cell_count": len(completed_ids),
        "raw_sha256": checkpoint["raw_sha256"],
    }


def audit_stage9_run(run_root: os.PathLike[str] | str,
                     binding: TrustedStage9Binding) -> Stage9Audit:
    if not isinstance(binding, TrustedStage9Binding):
        raise TypeError("audit_stage9_run requires TrustedStage9Binding")
    root = Path(run_root)
    _require(root.name == binding.run_id and root.name not in binding.rejected_run_ids,
             "Stage9 run id is not the approved r3 authority.")
    _require(not root.is_symlink() and root.resolve() ==
             (binding.output_root / binding.run_id).resolve() and
             root.parent.resolve() == binding.output_root.resolve(),
             "Stage9 run must be the direct approved output child.")
    _require(root.is_dir(), "Stage9 run directory is missing.")
    _require(sha256_file(binding.config_path) == binding.config_sha256 and
             sha256_file(binding.result_schema_path) == binding.result_schema_sha256,
             "Trusted Stage9 config/schema SHA mismatch.")
    stage9_config = load_json(binding.config_path)
    schema = load_json(binding.result_schema_path)
    _require(stage9_config.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             schema.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             stage9_config.get("result_schema_sha256") ==
             binding.result_schema_sha256,
             "Stage9 config/schema contract mismatch.")

    verification_path = _artifact_path(root, "verification.json")
    state_path = _artifact_path(root, "run_state.json")
    _require(sha256_file(verification_path) == binding.verification_sha256 and
             sha256_file(state_path) == binding.run_state_sha256,
             "Stage9 verification/run-state pinned SHA mismatch.")
    verification = load_json(verification_path)
    state = load_json(state_path)
    required = schema.get("required_run_artifacts")
    _require(isinstance(required, list) and len(required) == len(set(required)),
             "Stage9 result schema required artifacts are invalid.")
    for relative in required:
        _artifact_path(root, relative)
    mapped_required = set(required) - {"verification.json", "run_state.json"}
    artifact_map = verification.get("artifact_sha256")
    _require(isinstance(artifact_map, Mapping) and
             set(artifact_map) == mapped_required and
             len(artifact_map) == binding.expected_artifact_count,
             "Stage9 verification artifact map is not exact.")
    for relative, expected in artifact_map.items():
        _require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                 "Stage9 artifact SHA is malformed: " + relative)
        _require(sha256_file(_artifact_path(root, relative)) == expected,
                 "Stage9 artifact SHA mismatch: " + relative)

    _require(state.get("schema_version") ==
             "capd_proactive_stage9_run_state_v2_0" and
             state.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             state.get("status") == "stage9_overhead_verified" and
             state.get("stage10_entry_gate") == "satisfied" and
             state.get("failure") is None,
             "Stage9 run state does not authorize entry.")
    _require(verification.get("schema_version") ==
             "capd_proactive_stage9_verification_v2_0" and
             verification.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0",
             "Stage9 verification identity is invalid.")
    for key, expected in schema.get("verification_required", {}).items():
        _require(verification.get(key) == expected,
                 "Stage9 verification field mismatch: " + key)
    _require(verification.get("stage8_artifacts_overwritten") is False and
             verification.get("run_identity_sha256") == binding.run_identity_sha256,
             "Stage9 verification provenance was weakened.")

    names = (
        "run_identity.json", "resolved_config.json", "stage8_compatibility_receipt.json",
        "preflight.json", "environment.json", "measurement_checkpoint.json",
        "latency_summary.json", "quality_summary.json", "instrumentation_audit.json",
        "perf/perf_parsed.json", "perf/perf_scope_counts.json",
        "memory_breakdown.json", "server_test_receipt.json")
    payloads: Dict[str, Any] = {name: load_json_decimal(root / name)
                                if name == "latency_summary.json"
                                else load_json(root / name) for name in names}
    identity = payloads["run_identity.json"]
    resolved = payloads["resolved_config.json"]
    _require(sha256_file(root / "run_identity.json") ==
             binding.run_identity_file_sha256 and
             identity.get("run_id") == binding.run_id and
             identity.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             identity.get("config_sha256") == binding.config_sha256 and
             identity.get("result_schema_sha256") == binding.result_schema_sha256 and
             identity.get("run_identity_sha256") == binding.run_identity_sha256 and
             identity.get("formal_b_max") == 2,
             "Stage9 run identity binding failed.")
    _require(resolved.get("run_id") == binding.run_id and
             resolved.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
             resolved.get("config_sha256") == binding.config_sha256 and
             resolved.get("result_schema_sha256") == binding.result_schema_sha256 and
             resolved.get("run_identity_sha256") == binding.run_identity_sha256,
             "Stage9 resolved config binding failed.")
    stage8 = payloads["stage8_compatibility_receipt.json"]
    _require(sha256_file(root / "stage8_compatibility_receipt.json") ==
             binding.stage8_receipt_sha256 and
             stage8.get("stage8_contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
             stage8.get("stage8_status") == "stage8_sync_replay_verified" and
             stage8.get("stage9_entry_gate") == "satisfied" and
             all(stage8.get(key) is True for key in (
                 "stage8_run_state_verified", "stage4_sha_chain_verified",
                 "job_results_verified", "statistics_verified",
                 "stage8_artifacts_read_only")) and
             stage8.get("test_used_for_parameter_selection") is False,
             "Stage8 compatibility receipt is invalid.")
    environment = payloads["environment.json"]
    preflight = payloads["preflight.json"]
    _require(environment.get("system") == "Linux" and
             environment.get("device") == "cpu" and
             isinstance(environment.get("linux_kernel"), str) and
             preflight.get("status") == "passed" and
             preflight.get("device") == "cpu" and
             preflight.get("stage8_stage9_entry_gate") == "satisfied" and
             preflight.get("stage8_artifacts_read_only") is True and
             preflight.get("test_used_for_parameter_selection") is False,
             "Stage9 Linux environment/preflight validation failed.")
    perf = payloads["perf/perf_parsed.json"]
    perf_scope = payloads["perf/perf_scope_counts.json"]
    _require(perf.get("counter_source") == "linux_perf_hardware" and
             perf.get("cycles_verified") is True and
             perf.get("required_events_verified") is True and
             perf.get("failure_reason") is None and
             set(schema.get("perf_required_events", ())) <= set(perf.get("events", {})) and
             perf_scope.get("formal_b_max") == 2 and
             perf_scope.get("snapshot_count") ==
             len(perf_scope.get("measured_cells", ())) and
             perf_scope.get("zero_round_job_count") ==
             len(perf_scope.get("zero_round_cells", ())),
             "Stage9 perf evidence is invalid.")
    memory = payloads["memory_breakdown.json"]
    rss = memory.get("rss", {})
    _require(all(isinstance(rss.get(name), (int, float)) and rss[name] >= 0
                 for name in schema.get("memory_rss_required_fields", ())),
             "Stage9 RSS evidence is incomplete.")
    server = payloads["server_test_receipt.json"]
    _require(server.get("status") == "passed" and
             server.get("test_count", 0) >= server.get("minimum_required", 1) and
             server.get("log_sha256") ==
             artifact_map["logs/stage1_stage9_regression.log"],
             "Stage9 regression receipt is invalid.")
    with (root / "capacity_overhead.csv").open(
            "r", encoding="utf-8", newline="") as handle:
        capacity_rows = list(csv.DictReader(handle))
    _require(capacity_rows and all(row.get("fair_capacity_replay_status") == "deferred"
                                   for row in capacity_rows),
             "Stage9 capacity accounting is invalid.")
    checkpoint_summary = validate_measurement_checkpoint(
        root, binding, payloads["measurement_checkpoint.json"],
        payloads["quality_summary.json"], payloads["instrumentation_audit.json"],
        resolved)
    _require(sha256_file(root / "latency_summary.json") ==
             binding.latency_summary_sha256,
             "Stage9 latency summary pinned SHA mismatch.")
    receipt = {
        "schema_version": "capd_proactive_stage10_stage9_input_receipt_v2_0",
        "status": STAGE9_GATE_STATUS,
        "source_run_id": binding.run_id,
        "formal_authorized": True,
        "artifact_sha256_verified_count": len(artifact_map),
        "observed_artifact_sha256": dict(sorted(artifact_map.items())),
        "verification_sha256": binding.verification_sha256,
        "run_state_sha256": binding.run_state_sha256,
        "config_sha256": binding.config_sha256,
        "result_schema_sha256": binding.result_schema_sha256,
        "measurement_checkpoint_sha256": binding.checkpoint_sha256,
        "latency_summary_sha256": binding.latency_summary_sha256,
        "run_identity_file_sha256": binding.run_identity_file_sha256,
        "run_identity_sha256": binding.run_identity_sha256,
        "stage8_compatibility_receipt_sha256": binding.stage8_receipt_sha256,
        "byte_recovery_audit_sha256": binding.recovery_audit_sha256,
        **checkpoint_summary,
    }
    return Stage9Audit(receipt=receipt, payloads=payloads, binding=binding)


def _round_ns(value: Decimal) -> int:
    _require(isinstance(value, Decimal),
             "Timing values must be parsed as Decimal, not binary float.")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def derive_timing_provenance(audit: Stage9Audit) -> Mapping[str, Any]:
    _require(isinstance(audit, Stage9Audit) and
             audit.receipt.get("status") == STAGE9_GATE_STATUS,
             "Timing provenance requires a verified Stage9 audit.")
    latency = audit.payloads["latency_summary.json"]
    _require(latency.get("formal_b_max") == 2,
             "Stage9 latency formal b_max changed.")
    stats = latency.get("by_b_max", {}).get("2", {}).get("stages", {}).get(
        "total_round_latency_ns", {})
    _require(stats.get("count") == 182394,
             "Stage9 latency sample count changed.")
    decimal_values = {name: (value if isinstance(value, Decimal)
                             else Decimal(str(value)))
                      for name, value in ((name, stats.get(name))
                                          for name in ("mean", "p50", "p95", "p99"))}
    _require(decimal_values["mean"] == Decimal("2252304.4582606885"),
             "Stage9 primary mean latency changed.")
    inference = {name: _round_ns(value) for name, value in decimal_values.items()}
    _require(inference == {"mean": 2252304, "p50": 2192418,
                           "p95": 2625519, "p99": 2938056},
             "Stage9 timing conversion result changed.")
    ratios = {
        "migration-ratio-0p01": Decimal("0.01"),
        "migration-ratio-0p10": Decimal("0.10"),
        "migration-ratio-1p00": Decimal("1.00"),
    }
    migration = {name: _round_ns(decimal_values["mean"] * ratio)
                 for name, ratio in ratios.items()}
    return {
        "schema_version": "capd_proactive_stage10_timing_provenance_v2_0",
        "source_run_id": audit.binding.run_id,
        "source_artifact": "latency_summary.json",
        "formal_b_max": 2,
        "field": 'by_b_max["2"].stages.total_round_latency_ns.mean',
        "sample_count": stats["count"],
        "conversion_rule": CONVERSION_RULE,
        "original_decimal": {name: str(value)
                             for name, value in decimal_values.items()},
        "inference_ns": inference,
        "migration_ns": migration,
        "migration_source":
            "predeclared_simulator_scenario_ratio_not_hardware_measurement",
        "latency_summary_sha256": audit.binding.latency_summary_sha256,
        "stage9_verification_sha256": audit.binding.verification_sha256,
        "measurement_checkpoint_sha256": audit.binding.checkpoint_sha256,
        "run_identity_file_sha256": audit.binding.run_identity_file_sha256,
        "run_identity_sha256": audit.binding.run_identity_sha256,
        "stage9_config_sha256": audit.binding.config_sha256,
    }


def build_timing_profiles(provenance: Mapping[str, Any]) -> Tuple[Mapping[str, Any], ...]:
    inference = provenance["inference_ns"]
    migration = provenance["migration_ns"]
    rows = (
        (REFERENCE_TIMING_PROFILE, "mean", "migration-ratio-0p10", "reference"),
        ("inference-p50__migration-ratio-0p10", "p50",
         "migration-ratio-0p10", "inference_sensitivity"),
        ("inference-p95__migration-ratio-0p10", "p95",
         "migration-ratio-0p10", "inference_sensitivity"),
        ("inference-p99__migration-ratio-0p10", "p99",
         "migration-ratio-0p10", "inference_sensitivity"),
        ("inference-mean__migration-ratio-0p01", "mean",
         "migration-ratio-0p01", "migration_sensitivity"),
        ("inference-mean__migration-ratio-1p00", "mean",
         "migration-ratio-1p00", "migration_sensitivity"),
    )
    return tuple({"timing_profile_id": profile_id,
                  "inference_source_statistic": statistic,
                  "migration_scenario_id": migration_id,
                  "role": role,
                  "T_inference_ns": inference[statistic],
                  "T_migration_ns": migration[migration_id]}
                 for profile_id, statistic, migration_id, role in rows)


def canonical_arrival_payload(arrivals: Sequence[engine.Arrival]) -> list[dict[str, int]]:
    rows = [{"page_id": item.page_id, "timestamp_ns": item.timestamp_ns}
            for item in arrivals]
    _require(rows == sorted(rows, key=lambda row: (row["timestamp_ns"], row["page_id"])) and
             len({(row["timestamp_ns"], row["page_id"]) for row in rows}) == len(rows),
             "Arrival stream order or identity is invalid.")
    return rows


def arrival_stream_sha256(arrivals: Sequence[engine.Arrival]) -> str:
    return fingerprint_value(canonical_arrival_payload(arrivals))


def _fraction_object(value: Fraction, unit: bool = False) -> Mapping[str, Any]:
    result: Dict[str, Any] = {"numerator": value.numerator,
                              "denominator": value.denominator}
    if unit:
        result["unit"] = "pages_per_ns"
    return result


def _simulator_config(config: Mapping[str, Any], timing: Mapping[str, Any]
                      ) -> engine.SimulatorConfig:
    params = dict(config["simulator_parameters"])
    params.pop("candidate_source", None)
    params["T_inference_ns"] = timing["T_inference_ns"]
    params["T_migration_ns"] = timing["T_migration_ns"]
    return engine.SimulatorConfig.from_mapping(params)


def _absolute_rate(profile: Mapping[str, Any], params: engine.SimulatorConfig
                   ) -> Mapping[str, Any]:
    capacity = engine.mu_demote(params)
    if profile["kind"] == "uniform":
        rate = capacity * Fraction(profile["load_ratio"])
        return {"kind": "uniform", "rate": _fraction_object(rate, unit=True)}
    base = capacity * Fraction(profile["base_load_ratio"])
    return {
        "kind": "piecewise", "base_rate": _fraction_object(base, unit=True),
        "intervals": [
            {"start_ns": burst["start_ns"],
             "end_ns": burst["start_ns"] + burst["duration_ns"],
             "rate": _fraction_object(base * Fraction(burst["multiplier"]), unit=True)}
            for burst in profile["bursts"]],
    }


def _normalized_ratio(absolute: Mapping[str, Any], current_mu: Fraction,
                      timing_profile_id: str) -> Mapping[str, Any]:
    def fraction(row: Mapping[str, Any]) -> Fraction:
        return Fraction(row["numerator"], row["denominator"])
    if absolute["kind"] == "uniform":
        ratio = fraction(absolute["rate"]) / current_mu
        return {"kind": "uniform", "ratio": _fraction_object(ratio),
                "reference": timing_profile_id}
    base = fraction(absolute["base_rate"]) / current_mu
    return {
        "kind": "piecewise", "base_ratio": _fraction_object(base),
        "intervals": [
            {"start_ns": row["start_ns"], "end_ns": row["end_ns"],
             "ratio": _fraction_object(fraction(row["rate"]) / current_mu)}
            for row in absolute["intervals"]],
        "reference": timing_profile_id,
    }


@dataclass(frozen=True)
class ArrivalStream:
    arrivals: Tuple[engine.Arrival, ...]
    sha256: str
    absolute_arrival_rate: Mapping[str, Any]


def _generate_stream(profile: Mapping[str, Any], params: engine.SimulatorConfig
                     ) -> ArrivalStream:
    model = ({"kind": "uniform", "load_ratio": profile["load_ratio"]}
             if profile["kind"] == "uniform" else
             {"kind": "burst", "base_load_ratio": profile["base_load_ratio"],
              "bursts": profile["bursts"]})
    arrivals = tuple(engine.generate_arrivals(params, model))
    return ArrivalStream(arrivals, arrival_stream_sha256(arrivals),
                         _absolute_rate(profile, params))


def build_arrival_streams(config: Mapping[str, Any], provenance: Mapping[str, Any]
                          ) -> Mapping[Tuple[str, str, str], ArrivalStream]:
    timing_profiles = build_timing_profiles(provenance)
    by_id = {row["timing_profile_id"]: row for row in timing_profiles}
    reference = by_id[REFERENCE_TIMING_PROFILE]
    reference_params = _simulator_config(config, reference)
    streams: Dict[Tuple[str, str, str], ArrivalStream] = {}
    for arrival in config["arrival_profiles"]:
        shared = _generate_stream(arrival, reference_params)
        for timing in timing_profiles:
            streams[("fixed_arrival", timing["timing_profile_id"], arrival["id"])] = shared
    for timing in timing_profiles:
        params = _simulator_config(config, timing)
        for arrival in config["arrival_profiles"]:
            streams[("capacity_normalized", timing["timing_profile_id"],
                     arrival["id"])] = _generate_stream(arrival, params)
    return streams


def expand_scenario_matrix(config: Mapping[str, Any], provenance: Mapping[str, Any],
                           streams: Mapping[Tuple[str, str, str], ArrivalStream]
                           ) -> Tuple[Mapping[str, Any], ...]:
    timing_profiles = build_timing_profiles(provenance)
    rows = []
    channel_contract = {row["id"]: row for row in config["comparison_channels"]}
    for channel in ("fixed_arrival", "capacity_normalized"):
        channel_row = channel_contract[channel]
        for timing in timing_profiles:
            timing_id = timing["timing_profile_id"]
            params = _simulator_config(config, timing)
            for arrival in config["arrival_profiles"]:
                arrival_id = arrival["id"]
                stream = streams[(channel, timing_id, arrival_id)]
                reference = (REFERENCE_TIMING_PROFILE if channel == "fixed_arrival"
                             else timing_id)
                binding = {
                    "arrival_rate_basis": channel_row["arrival_rate_basis"],
                    "arrival_reference_profile": reference,
                    "arrival_stream_sha256": stream.sha256,
                    "absolute_arrival_rate": stream.absolute_arrival_rate,
                    "normalized_load_ratio": _normalized_ratio(
                        stream.absolute_arrival_rate, engine.mu_demote(params), timing_id),
                    "cross_profile_comparison_allowed":
                        channel_row["cross_profile_comparison_allowed"],
                    "cross_profile_comparison_scope": channel_row["scope"],
                }
                rows.append({
                    "scenario_id": f"{channel}__{timing_id}__{arrival_id}",
                    "comparison_channel": channel,
                    "timing_profile_id": timing_id,
                    "arrival_profile_id": arrival_id,
                    "T_inference_ns": timing["T_inference_ns"],
                    "T_migration_ns": timing["T_migration_ns"],
                    "arrival_binding": binding,
                })
    _require(len(rows) == config["scenario_count"] == 60 and
             len({row["scenario_id"] for row in rows}) == 60,
             "Stage10 v2 scenario matrix is not exactly 60 unique rows.")
    for arrival in config["arrival_profiles"]:
        fixed = [row for row in rows if row["comparison_channel"] == "fixed_arrival"
                 and row["arrival_profile_id"] == arrival["id"]]
        _require(len({row["arrival_binding"]["arrival_stream_sha256"]
                      for row in fixed}) == 1,
                 "Fixed-arrival stream identity differs across timing profiles.")
    return tuple(rows)


def load_result_schema(project_root: os.PathLike[str] | str) -> Mapping[str, Any]:
    root = Path(project_root).resolve()
    config = load_json(root / "configs/finals/capd_proactive_stage10_v2.json")
    path = root / config["result_schema"]
    _require(path.is_file() and sha256_file(path) == config["result_schema_sha256"],
             "Stage10 v2 result schema binding mismatch.")
    schema = load_json(path)
    _validate_result_schema(schema)
    return schema


def simulate_scenario(config: Mapping[str, Any], scenario: Mapping[str, Any],
                      stream: ArrivalStream) -> Mapping[str, Any]:
    _require(stream.sha256 == scenario.get("arrival_binding", {}).get(
        "arrival_stream_sha256"), "Scenario arrival stream SHA mismatch.")
    _require(arrival_stream_sha256(stream.arrivals) == stream.sha256,
             "Scenario arrivals changed after matrix construction.")
    timing = {
        "T_inference_ns": scenario["T_inference_ns"],
        "T_migration_ns": scenario["T_migration_ns"],
    }
    params = _simulator_config(config, timing)
    result = engine.run_simulation(params, list(stream.arrivals))
    derived = dict(result.derived)
    derived.update({
        "comparison_channel": scenario["comparison_channel"],
        "timing_profile_id": scenario["timing_profile_id"],
        "arrival_profile_id": scenario["arrival_profile_id"],
        "arrival_binding": scenario["arrival_binding"],
    })
    fixed = scenario["comparison_channel"] == "fixed_arrival"
    interpretation = {
        "scope": "deterministic_async_simulation_only",
        "deterministic_async_simulation_verified": True,
        "real_nvm_measurement_verified": False,
        "kernel_behavior_verified": False,
        "real_concurrency_verified": False,
        "real_foreground_end_to_end_latency_verified": False,
        "real_system_async_performance_verified": False,
        "timing_sensitivity_interpretation_allowed": fixed,
        "capacity_normalized_timing_causal_interpretation_allowed": False,
    }
    return {
        "scenario_id": scenario["scenario_id"],
        "contract_id": CONTRACT_ID,
        "evidence_mode": EVIDENCE_MODE,
        "observed": dict(result.metrics),
        "derived": derived,
        "interpretation": interpretation,
    }


def _validate_fraction(row: Any, *, unit: bool) -> None:
    _require(isinstance(row, Mapping), "Exact rational value must be an object.")
    numerator = row.get("numerator")
    denominator = row.get("denominator")
    _require(isinstance(numerator, int) and not isinstance(numerator, bool) and
             isinstance(denominator, int) and not isinstance(denominator, bool) and
             denominator > 0 and Fraction(numerator, denominator).denominator == denominator,
             "Exact rational value is malformed or not reduced.")
    if unit:
        _require(row.get("unit") == "pages_per_ns",
                 "Absolute arrival-rate unit changed.")
    else:
        _require("unit" not in row, "Normalized ratio must be unitless.")


def _validate_rate_object(value: Any, *, normalized: bool) -> None:
    _require(isinstance(value, Mapping) and value.get("kind") in
             ("uniform", "piecewise"), "Arrival rate object kind is invalid.")
    key = "ratio" if normalized else "rate"
    base_key = "base_ratio" if normalized else "base_rate"
    if value["kind"] == "uniform":
        _validate_fraction(value.get(key), unit=not normalized)
    else:
        _validate_fraction(value.get(base_key), unit=not normalized)
        intervals = value.get("intervals")
        _require(isinstance(intervals, list) and intervals,
                 "Piecewise rate intervals are missing.")
        previous_end = -1
        for interval in intervals:
            _require(isinstance(interval.get("start_ns"), int) and
                     isinstance(interval.get("end_ns"), int) and
                     interval["start_ns"] >= previous_end and
                     interval["end_ns"] > interval["start_ns"],
                     "Piecewise rate interval is invalid.")
            _validate_fraction(interval.get(key), unit=not normalized)
            previous_end = interval["end_ns"]
    if normalized:
        _require(isinstance(value.get("reference"), str),
                 "Normalized load ratio lacks a timing reference.")


def validate_result_line(line: Mapping[str, Any],
                         schema: Mapping[str, Any]) -> None:
    _validate_result_schema(schema)
    _require(set(schema["required_top_level"]) <= set(line),
             "Stage10 v2 result top-level fields are incomplete.")
    _require(line.get("contract_id") == CONTRACT_ID and
             line.get("evidence_mode") == EVIDENCE_MODE,
             "Stage10 v2 result identity is invalid.")
    observed = line.get("observed", {})
    derived = line.get("derived", {})
    interpretation = line.get("interpretation", {})
    _require(set(schema["required_observed"]) <= set(observed) and
             set(schema["required_derived"]) <= set(derived) and
             set(schema["required_interpretation"]) <= set(interpretation),
             "Stage10 v2 result fields are incomplete.")
    count = observed.get("blocking_sample_count")
    _require(isinstance(count, int) and count >= 0,
             "Blocking sample count is invalid.")
    if count == 0:
        _require(observed.get("foreground_blocking_time_mean") is None and
                 observed.get("foreground_blocking_time_p95") is None,
                 "Empty blocking samples must use JSON null.")
    channel = derived.get("comparison_channel")
    binding = derived.get("arrival_binding", {})
    _require(channel in schema["comparison_channels"] and
             set(schema["required_arrival_binding"]) <= set(binding) and
             re.fullmatch(r"[0-9a-f]{64}",
                          str(binding.get("arrival_stream_sha256"))) is not None,
             "Stage10 v2 arrival binding is incomplete.")
    _validate_rate_object(binding.get("absolute_arrival_rate"), normalized=False)
    _validate_rate_object(binding.get("normalized_load_ratio"), normalized=True)
    if channel == "fixed_arrival":
        _require(binding.get("arrival_rate_basis") == "reference_profile_fixed" and
                 binding.get("arrival_reference_profile") == REFERENCE_TIMING_PROFILE and
                 binding.get("cross_profile_comparison_allowed") is True and
                 binding.get("cross_profile_comparison_scope") ==
                 "timing_sensitivity_within_simulator" and
                 interpretation.get("timing_sensitivity_interpretation_allowed") is True,
                 "Fixed-arrival comparison contract is invalid.")
    else:
        _require(binding.get("arrival_rate_basis") == "per_profile_mu_demote" and
                 binding.get("arrival_reference_profile") ==
                 derived.get("timing_profile_id") and
                 binding.get("cross_profile_comparison_allowed") is False and
                 binding.get("cross_profile_comparison_scope") ==
                 "relative_capacity_pressure_only" and
                 interpretation.get("timing_sensitivity_interpretation_allowed") is False,
                 "Capacity-normalized comparison contract is invalid.")
    _require(interpretation.get("deterministic_async_simulation_verified") is True and
             all(interpretation.get(name) is False for name in (
                 "real_nvm_measurement_verified", "kernel_behavior_verified",
                 "real_concurrency_verified",
                 "real_foreground_end_to_end_latency_verified",
                 "real_system_async_performance_verified",
                 "capacity_normalized_timing_causal_interpretation_allowed")),
             "Stage10 v2 interpretation boundary is invalid.")
