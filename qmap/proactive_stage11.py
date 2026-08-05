"""Stage11A contracts and offline evidence helpers.

This module is intentionally independent from Stage8/9/10 runners.  It only
reads Stage8 authority artifacts and never writes to an upstream evidence tree.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from qmap import proactive_cost
from qmap import proactive_stage8_contract as stage8_contract


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11A-1.0"
EXPECTED_PROFILES = {
    "read_light": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 4, "demotion": 8},
    "default": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
    "write_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 12, "demotion": 10},
    "migration_expensive": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 20},
}
INPUT_ABLATIONS = ["CAPD-Full", "CAPD-NoVPN", "CAPD-NoContext", "CAPD-NoPageState"]
EVIDENCE_STATUSES = {"implemented", "candidate-ready", "formally_verified", "BLOCKED", "NOT_VERIFIABLE"}


class Stage11ContractError(ValueError):
    """Input or output violates the Stage11A contract."""


class Stage11Blocked(Stage11ContractError):
    """A known prerequisite is deliberately unavailable."""


class Stage11NotVerifiable(Stage11ContractError):
    """Evidence is missing, malformed, or tampered and cannot be classified."""


def _reject_duplicate_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Stage11ContractError("Duplicate JSON key: {}".format(key))
        value[key] = item
    return value


def _reject_constant(value):
    raise Stage11ContractError("Non-finite JSON constant: {}".format(value))


def load_json(path: os.PathLike[str] | str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_pairs,
                             parse_constant=_reject_constant)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise Stage11ContractError("Cannot load JSON {}: {}".format(path, exc)) from exc


def fingerprint_file(path: os.PathLike[str] | str) -> str:
    return stage8_contract.fingerprint_file(str(path))


def fingerprint_value(value: Any) -> str:
    return stage8_contract.fingerprint_value(value)


def fingerprint_value_for_stage8(value: Any) -> str:
    """Test/adapter spelling that delegates to the frozen Stage8 hash routine."""
    return fingerprint_value(stage8_contract.semantic_payload(value))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage11ContractError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _non_negative_int(value: Any, field: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
             "{} must be a non-negative integer.".format(field))
    return value


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Stage11A config must be an object.")
    _require(value.get("contract_id") == CONTRACT_ID, "Unexpected Stage11A contract id.")
    _require(value.get("schema_version") == "capd_proactive_stage11a_config_v1_0",
             "Unexpected Stage11A config schema version.")
    _require(value.get("stage8_authority_path"), "Stage8 authority path is required.")
    main = value.get("main_control")
    _require(isinstance(main, Mapping) and main.get("b_max") == 2,
             "Main Stage11A b_max must remain immutable at 2.")
    profiles = value.get("cost_profiles")
    _require(isinstance(profiles, Mapping) and set(profiles) == set(EXPECTED_PROFILES),
             "Stage11A must contain exactly the four frozen cost profiles.")
    for name, expected in EXPECTED_PROFILES.items():
        item = profiles[name]
        _require(isinstance(item, Mapping) and item.get("weights") == expected,
                 "Cost profile {} has unexpected weights.".format(name))
        semantics = item.get("semantics", {})
        _require(semantics.get("nvm_write") == "NVM write access cost" and
                 semantics.get("demotion") == "DRAM to NVM migration cost",
                 "Cost profile {} semantics are incomplete.".format(name))
    grid = value.get("sensitivity_grid")
    _require(isinstance(grid, Mapping), "Sensitivity grid is required.")
    _require(grid.get("b_max") == [1, 2, 4], "Sensitivity b_max grid is fixed to [1, 2, 4].")
    _require(grid.get("capacity_working_set_fraction") == [0.2, 0.4, 0.6],
             "Capacity sensitivity grid is fixed to 20/40/60 percent.")
    for key in ("watermark_candidates", "label_weight_candidates"):
        candidates = grid.get(key)
        _require(isinstance(candidates, list), "{} must be an explicit list.".format(key))
        _require(all(isinstance(item, int) and not isinstance(item, bool) for item in candidates),
                 "{} may contain only explicit integers.".format(key))
    _require(grid.get("analysis_only") is True, "Sensitivity grid must be analysis-only.")
    _require(value.get("test_used_for_parameter_selection") is False and
             value.get("execution_authorized") is False and
             grid.get("execution_authorized") is False,
             "Stage11A config cannot authorize formal execution or Test selection.")
    ablation = value.get("input_ablation")
    _require(isinstance(ablation, Mapping) and ablation.get("status") == "BLOCKED" and
             ablation.get("variants") == INPUT_ABLATIONS,
             "Input component ablations must remain blocked interfaces.")
    batch = value.get("batch_ablation")
    _require(isinstance(batch, Mapping) and
             batch.get("variants") == ["Proactive-CAPD-Top-1", "Proactive-CAPD-Top-b"] and
             batch.get("only_changed_parameter") == "selection_count",
             "Top-1/Top-b batch ablation contract is invalid.")
    return value


def validate_result_row(value: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Result row must be an object.")
    _require(value.get("evidence_status") in EVIDENCE_STATUSES,
             "Unknown Stage11A evidence status.")
    if value.get("evidence_status") == "formally_verified":
        raise Stage11ContractError("Stage11A v1.0 cannot generate formally_verified rows.")
    for field in ("dram_hits", "nvm_reads", "nvm_writes", "proactive_demotions",
                  "reactive_demotions", "emergency_demotions", "total_demotions",
                  "raw_access_count", "weighted_cost"):
        if value.get(field) is not None:
            _non_negative_int(value[field], field)
    if value.get("policy_or_ablation") in INPUT_ABLATIONS:
        _require(value.get("evidence_status") == "BLOCKED",
                 "Input model ablations cannot be candidate or formal rows.")
    return value


def _safe_job_dir(root: Path, job_id: str) -> Path:
    _require(isinstance(job_id, str) and job_id and Path(job_id).name == job_id,
             "Invalid Stage8 job_id path component.")
    path = (root / "jobs" / job_id).resolve()
    jobs_root = (root / "jobs").resolve()
    _require(path.parent == jobs_root, "Stage8 job path escapes jobs directory.")
    return path


def _validate_metrics(metrics: Mapping[str, Any]) -> None:
    for field in ("dram_hits", "nvm_reads", "nvm_writes", "proactive_demotions",
                  "reactive_demotions", "emergency_demotions", "total_demotions",
                  "raw_access_count", "weighted_cost"):
        _non_negative_int(metrics.get(field), "metrics." + field)
    _require(metrics["total_demotions"] == (
        metrics["proactive_demotions"] + metrics["reactive_demotions"] +
        metrics["emergency_demotions"]), "Stage8 demotion counters are inconsistent.")


def load_stage8_rows(root: os.PathLike[str] | str) -> list[Dict[str, Any]]:
    root = Path(root).resolve()
    _require(root.is_dir(), "Stage8 authority directory is missing.")
    state = load_json(root / "run_state.json")
    _require(state.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
             state.get("status") == "stage8_sync_replay_verified" and
             state.get("test_used_for_parameter_selection") is False,
             "Stage8 authority is not the verified r5 synchronous result.")
    _require({"formal_80_jobs", "verification"} <= set(state.get("completed", [])),
             "Stage8 authority completion evidence is incomplete.")
    load_json(root / "verification.json")
    root_manifest = load_json(root / "job_manifest.json")
    _require(root_manifest.get("contract_id") == "CAPD-PROACTIVE-STAGE8-2.0",
             "Stage8 root job manifest contract mismatch.")
    plans = root_manifest.get("jobs")
    _require(isinstance(plans, list) and plans and root_manifest.get("job_count") == len(plans),
             "Stage8 root job manifest has no complete job list.")
    plan_by_id = {}
    for plan in plans:
        _require(isinstance(plan, Mapping) and isinstance(plan.get("job_id"), str),
                 "Stage8 root job plan is malformed.")
        _require(plan["job_id"] not in plan_by_id, "Duplicate Stage8 job identity.")
        plan_by_id[plan["job_id"]] = plan
    csv_path = root / "artifacts" / "per_workload_raw.csv"
    _require(csv_path.is_file(), "Stage8 per_workload_raw.csv is missing.")
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    _require(csv_rows, "Stage8 per_workload_raw.csv is empty.")
    seen = set()
    normalized = []
    for csv_row in csv_rows:
        job_id = csv_row.get("job_id")
        _require(job_id in plan_by_id and job_id not in seen,
                 "CSV job_id is missing, unknown, or duplicated.")
        seen.add(job_id)
        job_dir = _safe_job_dir(root, job_id)
        job_manifest = load_json(job_dir / "job_manifest.json")
        _require(job_manifest.get("status") == "completed" and
                 isinstance(job_manifest.get("result_sha256"), str) and
                 isinstance(job_manifest.get("semantic_result_sha256"), str),
                 "Stage8 job manifest result SHA binding is incomplete.")
        result_path = job_dir / "result.json"
        _require(result_path.is_file(), "Stage8 job result is missing.")
        result_sha = fingerprint_file(result_path)
        _require(result_sha == job_manifest["result_sha256"],
                 "Stage8 result SHA mismatch for {}.".format(job_id))
        result = load_json(result_path)
        _require(result.get("semantic_result_sha256") == job_manifest["semantic_result_sha256"],
                 "Stage8 semantic result SHA binding mismatch for {}.".format(job_id))
        plan = plan_by_id[job_id]
        try:
            stage8_contract.audit_job_result(result, plan)
        except Exception as exc:
            raise Stage11ContractError("Stage8 result audit failed for {}: {}".format(job_id, exc)) from exc
        metrics = result.get("metrics")
        _require(isinstance(metrics, Mapping), "Stage8 result metrics are missing.")
        _validate_metrics(metrics)
        normalized.append({
            "source_job_id": job_id,
            "source_result_sha256": result_sha,
            "source_semantic_result_sha256": job_manifest["semantic_result_sha256"],
            "track": plan.get("track"),
            "workload": plan.get("workload"),
            "seed": plan.get("seed"),
            "policy": plan.get("policy"),
            "D": plan.get("D"),
            "F_low": plan.get("F_low"),
            "F_target": plan.get("F_target"),
            "K": plan.get("K"),
            "b_max": plan.get("b_max"),
            "controls": dict(plan.get("controls", {})),
            "trace_sha256": plan.get("trace_sha256"),
            "checkpoint_sha256": (plan.get("checkpoint") or {}).get("sha256"),
            "dram_hits": metrics["dram_hits"],
            "nvm_reads": metrics["nvm_reads"],
            "nvm_writes": metrics["nvm_writes"],
            "proactive_demotions": metrics["proactive_demotions"],
            "reactive_demotions": metrics["reactive_demotions"],
            "emergency_demotions": metrics["emergency_demotions"],
            "total_demotions": metrics["total_demotions"],
            "raw_access_count": metrics["raw_access_count"],
            "source_artifact_path": str(csv_path.relative_to(root)).replace("\\", "/"),
            "source_artifact_sha256": fingerprint_file(csv_path),
            "evidence_mode": "stage8_r5_raw_counters",
        })
    _require(len(seen) == len(plan_by_id), "Stage8 CSV does not cover the root job manifest.")
    return normalized


def recompute_profile_row(source: Mapping[str, Any], profile_name: str) -> Dict[str, Any]:
    _require(profile_name in EXPECTED_PROFILES, "Unknown Stage11A cost profile.")
    counts = proactive_cost.RawEventCounts(
        dram_hits=_non_negative_int(source.get("dram_hits"), "dram_hits"),
        nvm_reads=_non_negative_int(source.get("nvm_reads"), "nvm_reads"),
        nvm_writes=_non_negative_int(source.get("nvm_writes"), "nvm_writes"),
        total_demotions=_non_negative_int(source.get("total_demotions"), "total_demotions"),
        proactive_demotions=_non_negative_int(source.get("proactive_demotions"), "proactive_demotions"),
        reactive_demotions=_non_negative_int(source.get("reactive_demotions"), "reactive_demotions"),
        emergency_demotions=_non_negative_int(source.get("emergency_demotions"), "emergency_demotions"),
    )
    profile = proactive_cost.CostProfile.from_mapping(profile_name, EXPECTED_PROFILES[profile_name])
    result = proactive_cost.compute_weighted_cost(counts, profile)
    value = dict(source)
    value.update({
        "cost_profile": profile_name,
        "cost_profile_weights": profile.weights_dict(),
        "weighted_cost": result.weighted_cost,
        "weighted_cost_per_access": (
            None if source.get("raw_access_count") == 0
            else result.weighted_cost / float(source["raw_access_count"])),
    })
    return value


def freeze_grid(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Expand and hash the explicitly supplied analysis grid before execution."""
    grid = config.get("sensitivity_grid", {})
    watermark = list(grid.get("watermark_candidates", []))
    labels = list(grid.get("label_weight_candidates", []))
    records = []
    for b_max in grid.get("b_max", []):
        for capacity in grid.get("capacity_working_set_fraction", []):
            for profile in sorted(EXPECTED_PROFILES):
                for watermark_value in watermark:
                    for label_value in labels:
                        records.append({
                            "parameter_family": "sensitivity",
                            "watermark_candidate": watermark_value,
                            "label_weight_candidate": label_value,
                            "b_max": b_max,
                            "capacity_working_set_fraction": capacity,
                            "cost_profile": profile,
                            "analysis_only": True,
                        })
    records.sort(key=lambda row: (
        row["parameter_family"], row["watermark_candidate"],
        row["label_weight_candidate"], row["b_max"],
        row["capacity_working_set_fraction"], row["cost_profile"]))
    serialized = json.dumps(records, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "grid_records": records,
        "grid_frozen": bool(grid.get("grid_frozen", False)),
        "frozen_grid_sha256": hashlib.sha256(serialized).hexdigest(),
    }


def require_sync_grid(config: Mapping[str, Any]) -> Dict[str, Any]:
    grid = config.get("sensitivity_grid", {})
    if (grid.get("grid_frozen") is not True or
            grid.get("execution_authorized") is not True or
            not grid.get("watermark_candidates") or
            not grid.get("label_weight_candidates")):
        raise Stage11Blocked("sync_grid_not_explicitly_frozen_and_authorized")
    frozen = freeze_grid(config)
    if not frozen["grid_records"]:
        raise Stage11Blocked("sync_grid_empty")
    return frozen


def expand_ablation_grid(config: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Return only predeclared diagnostic rows; no training is started here."""
    rows = []
    for variant in config.get("input_ablation", {}).get("variants", INPUT_ABLATIONS):
        rows.append({
            "parameter_family": "input_ablation",
            "policy_or_ablation": variant,
            "evidence_mode": "model_component_ablation",
            "evidence_status": "BLOCKED",
            "blocking_reason": "future_separately_approved_validation_only_training_receipt",
        })
    rows.extend([
        {
            "parameter_family": "batch_ablation",
            "policy_or_ablation": "Proactive-CAPD-Top-1",
            "selection_count": 1,
            "evidence_mode": "synchronous_replay_candidate",
            "evidence_status": "BLOCKED",
        },
        {
            "parameter_family": "batch_ablation",
            "policy_or_ablation": "Proactive-CAPD-Top-b",
            "selection_count": config.get("main_control", {}).get("b_max", 2),
            "evidence_mode": "synchronous_replay_candidate",
            "evidence_status": "BLOCKED",
        },
    ])
    return rows


def top_batch_pair(rows: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    selected = {row.get("policy_or_ablation"): row for row in rows
                if row.get("parameter_family") == "batch_ablation"}
    _require("Proactive-CAPD-Top-1" in selected and "Proactive-CAPD-Top-b" in selected,
             "Top-1/Top-b pair is incomplete.")
    return selected["Proactive-CAPD-Top-1"], selected["Proactive-CAPD-Top-b"]


def config_without_selection_count(row: Mapping[str, Any]) -> Dict[str, Any]:
    value = dict(row)
    value.pop("selection_count", None)
    value.pop("policy_or_ablation", None)
    return value


def audit_stage9_gate(run_root: os.PathLike[str] | str) -> Dict[str, Any]:
    if run_root is None:
        return {"stage": "stage9", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "missing_stage9_run", "run_root": None,
                "run_state_sha256": None, "verification_sha256": None,
                "stage8_compatibility_receipt_sha256": None}
    path = Path(run_root)
    if not path.is_dir():
        return {"stage": "stage9", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "missing_stage9_run", "run_root": str(run_root),
                "run_state_sha256": None, "verification_sha256": None,
                "stage8_compatibility_receipt_sha256": None}
    try:
        schema_path = Path(__file__).resolve().parents[1] / "configs" / "finals" / "capd_proactive_stage9_result_schema.json"
        schema = load_json(schema_path)
        required = schema.get("required_run_artifacts")
        _require(isinstance(required, list) and required,
                 "Stage9 schema required_run_artifacts is missing.")
        missing = [name for name in required if not (path / name).is_file()]
        if missing:
            raise Stage11NotVerifiable("stage9_required_artifacts_missing:" + ",".join(missing))
        state = load_json(path / "run_state.json")
        verification = load_json(path / "verification.json")
        receipt = load_json(path / "stage8_compatibility_receipt.json")
        environment = load_json(path / "environment.json")
        _require(state.get("contract_id") == "CAPD-PROACTIVE-STAGE9-2.0" and
                 state.get("schema_version") == "capd_proactive_stage9_run_state_v2_0" and
                 state.get("status") == "stage9_overhead_verified" and
                 verification.get("status") == "stage9_overhead_verified",
                 "stage9_run_state_or_verification_not_verified")
        _require(receipt.get("stage9_entry_gate") == "satisfied" and
                 receipt.get("stage8_contract_id") == "CAPD-PROACTIVE-STAGE8-2.0" and
                 receipt.get("stage8_status") == "stage8_sync_replay_verified" and
                 receipt.get("job_results_verified") is True and
                 receipt.get("statistics_verified") is True and
                 receipt.get("stage8_run_state_verified") is True and
                 receipt.get("stage8_artifacts_read_only") is True and
                 receipt.get("test_used_for_parameter_selection") is False,
                 "stage9_stage8_compatibility_receipt_not_verified")
        _require(environment.get("system") == "Linux" and
                 environment.get("device") == "cpu" and
                 isinstance(environment.get("linux_kernel"), str),
                 "stage9_linux_cpu_environment_not_verified")
        artifact_sha = verification.get("artifact_sha256")
        artifact_names = [name for name in required
                          if name not in ("verification.json", "run_state.json")]
        _require(isinstance(artifact_sha, Mapping) and
                 set(artifact_sha) == set(artifact_names),
                 "stage9_artifact_sha256_key_set_incomplete")
        for name in artifact_names:
            _require(fingerprint_file(path / name) == artifact_sha[name],
                     "stage9_artifact_sha256_mismatch:" + name)
        required_verification = schema.get("verification_required", {})
        for key, expected in required_verification.items():
            _require(verification.get(key) == expected,
                     "stage9_verification_field_mismatch:" + key)
        # Stage11A never upgrades external evidence to a formal result. A
        # verified Stage9 run is only an authorized input for the external lane.
        return {"stage": "stage9", "status": "verified", "formal_authorized": True,
                "reason_code": "stage9_verified_input_authorized", "run_root": str(run_root),
                "run_state_sha256": fingerprint_file(path / "run_state.json"),
                "verification_sha256": fingerprint_file(path / "verification.json"),
                "stage8_compatibility_receipt_sha256": fingerprint_file(path / "stage8_compatibility_receipt.json")}
    except Stage11Blocked as exc:
        return {"stage": "stage9", "status": "BLOCKED", "formal_authorized": False,
                "reason_code": str(exc), "run_root": str(run_root),
                "run_state_sha256": fingerprint_file(path / "run_state.json") if (path / "run_state.json").is_file() else None,
                "verification_sha256": fingerprint_file(path / "verification.json") if (path / "verification.json").is_file() else None,
                "stage8_compatibility_receipt_sha256": fingerprint_file(path / "stage8_compatibility_receipt.json") if (path / "stage8_compatibility_receipt.json").is_file() else None}
    except Stage11NotVerifiable as exc:
        return {"stage": "stage9", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": str(exc), "run_root": str(run_root),
                "run_state_sha256": fingerprint_file(path / "run_state.json") if (path / "run_state.json").is_file() else None,
                "verification_sha256": fingerprint_file(path / "verification.json") if (path / "verification.json").is_file() else None,
                "stage8_compatibility_receipt_sha256": fingerprint_file(path / "stage8_compatibility_receipt.json") if (path / "stage8_compatibility_receipt.json").is_file() else None}
    except Exception as exc:
        return {"stage": "stage9", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "invalid_stage9_input", "detail": str(exc), "run_root": str(run_root),
                "run_state_sha256": None, "verification_sha256": None,
                "stage8_compatibility_receipt_sha256": None}


def audit_stage10_fixture(run_root: os.PathLike[str] | str) -> Dict[str, Any]:
    if run_root is None:
        return {"stage": "stage10", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "missing_stage10a_fixture", "run_root": None}
    path = Path(run_root)
    if not path.is_dir():
        return {"stage": "stage10", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "missing_stage10a_fixture", "run_root": str(run_root)}
    try:
        # The Stage10A verifier is the source of truth for its own manifest,
        # checksum, deterministic-result, formal-gate, and run-state rules.
        import importlib.util
        runner_path = Path(__file__).resolve().parents[1] / "scripts" / "run_capd_proactive_stage10.py"
        spec = importlib.util.spec_from_file_location("capd_stage10_runner", runner_path)
        _require(spec is not None and spec.loader is not None,
                 "Stage10 verifier cannot be loaded.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = load_json(path / "config.json")
        _require(config.get("mode") == "fixture", "stage10_mode_is_not_fixture")
        module.verify_run(str(path))
        state = load_json(path / "run_state.json")
        gate = load_json(path / "formal_gate.json")
        _require(state.get("stage10_formally_verified") is False and
                 gate.get("formal_authorized") is False and
                 gate.get("status") == "stage10_formal_blocked_by_stage9",
                 "stage10_fixture_formal_state_invalid")
        return {"stage": "stage10", "status": "BLOCKED", "formal_authorized": False,
                "reason_code": "stage10a_fixture_only", "run_root": str(run_root),
                "run_state_sha256": fingerprint_file(path / "run_state.json"),
                "formal_gate_sha256": fingerprint_file(path / "formal_gate.json"),
                "manifest_sha256": fingerprint_file(path / "manifest.json"),
                "checksums_sha256": fingerprint_file(path / "SHA256SUMS")}
    except Stage11Blocked as exc:
        return {"stage": "stage10", "status": "BLOCKED", "formal_authorized": False,
                "reason_code": str(exc), "run_root": str(run_root)}
    except Exception as exc:
        return {"stage": "stage10", "status": "NOT_VERIFIABLE", "formal_authorized": False,
                "reason_code": "invalid_stage10a_fixture", "detail": str(exc),
                "run_root": str(run_root)}
