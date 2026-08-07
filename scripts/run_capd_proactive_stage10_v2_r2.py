#!/usr/bin/env python3
"""Run and independently verify CAPD Stage10 v2-r2 evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qmap import proactive_stage10_v2_r2 as contract
from qmap import proactive_stage10_v2 as stage10_v2
from scripts import run_capd_proactive_stage10_v2 as legacy_runner


EXPECTED_ARTIFACTS = {
    "config.json", "event_model.md", "execution_environment.json",
    "generation_freeze_receipt.json", "generation_source_manifest.json",
    "generation_test_evidence.json", "generation_test_log.txt", "parameters.md",
    "README.md", "report.md", "run_identity.json", "run_state.json",
    "scenario_matrix.json", "simulation_results.jsonl", "stage9_input_receipt.json",
    "timing_provenance.json", "verification.json", "manifest.json", "SHA256SUMS",
}


def validate_approved_freeze_sha(
        supplied_sha256: str | None,
        repository_receipt: Path,
        run_copy: Path | None = None) -> str:
    if (not isinstance(supplied_sha256, str) or
            not re.fullmatch(r"[0-9a-f]{64}", supplied_sha256)):
        raise contract.Stage10V2R2ContractError(
            "The exact lowercase approved freeze-receipt SHA256 is required.")
    repository_receipt = Path(repository_receipt)
    if (not repository_receipt.is_file() or repository_receipt.is_symlink() or
            contract.sha256_file(repository_receipt) != supplied_sha256):
        raise contract.Stage10V2R2ContractError(
            "Approved freeze-receipt SHA256 does not match the repository receipt.")
    if run_copy is not None:
        run_copy = Path(run_copy)
        if (not run_copy.is_file() or run_copy.is_symlink() or
                contract.sha256_file(run_copy) != supplied_sha256 or
                run_copy.read_bytes() != repository_receipt.read_bytes()):
            raise contract.Stage10V2R2ContractError(
                "Run copy of the approved freeze receipt is not byte-identical.")
    return supplied_sha256


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _relative_files(root: Path):
    return sorted((path.relative_to(root).as_posix(), path)
                  for path in root.rglob("*") if path.is_file())


def _manifest_value(root: Path) -> Mapping[str, Any]:
    files = {
        relative: contract.sha256_file(path)
        for relative, path in _relative_files(root)
        if relative not in {"manifest.json", "SHA256SUMS"}
    }
    return {"schema_version": contract.MANIFEST_SCHEMA_VERSION, "files": files}


def _write_checksums(root: Path) -> None:
    lines = [
        f"{contract.sha256_file(path)}  {relative}"
        for relative, path in _relative_files(root) if relative != "SHA256SUMS"
    ]
    write_text(root / "SHA256SUMS", "\n".join(lines) + "\n")


def rebuild_manifest_and_checksums_for_test(root: Path) -> None:
    write_json(root / "manifest.json", _manifest_value(root))
    _write_checksums(root)


def environment_snapshot(dependency_names: Sequence[str]) -> Mapping[str, Any]:
    names = sorted(set(dependency_names))
    versions = {}
    for name in names:
        if not isinstance(name, str) or not name:
            raise contract.Stage10V2R2ContractError(
                "Dependency names must be non-empty strings.")
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise contract.Stage10V2R2ContractError(
                "Required dependency version is unavailable: " + name) from exc
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": getattr(sys.implementation, "cache_tag", None),
        "python_executable": str(Path(sys.executable).resolve()),
        "os_name": os.name,
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "architecture": platform.architecture()[0],
        "required_dependency_versions": versions,
        "dependency_policy": "pinned_non_stdlib" if versions else "stdlib_only",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _terminate_process_tree(process: subprocess.Popen,
                            grace_seconds: float) -> tuple[bool, str]:
    if process.poll() is not None:
        return True, "already_exited"
    method = "terminate"
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        method = "force_kill_process_tree"
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=max(1.0, grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return process.poll() is not None, method


def run_controlled_process(
        argv: Sequence[str], *, cwd: Path,
        timeout_seconds: float,
        monitor_interval_seconds: float,
        termination_grace_seconds: float,
        dependency_names: Sequence[str]) -> Mapping[str, Any]:
    if (not isinstance(argv, (list, tuple)) or not argv or
            any(not isinstance(item, str) or not item for item in argv)):
        raise contract.Stage10V2R2ContractError("Controlled argv is invalid.")
    if (not isinstance(timeout_seconds, (int, float)) or
            isinstance(timeout_seconds, bool) or timeout_seconds <= 0 or
            not isinstance(monitor_interval_seconds, (int, float)) or
            isinstance(monitor_interval_seconds, bool) or
            monitor_interval_seconds <= 0 or
            not isinstance(termination_grace_seconds, (int, float)) or
            isinstance(termination_grace_seconds, bool) or
            termination_grace_seconds < 0):
        raise contract.Stage10V2R2ContractError(
            "Controlled timeout/monitor/grace values are invalid.")
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise contract.Stage10V2R2ContractError("Controlled cwd is missing.")

    environment = environment_snapshot(dependency_names)
    start_text = _utc_now()
    start = time.monotonic()
    observations = []
    creationflags = 0
    popen_kwargs = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        list(argv), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, creationflags=creationflags, **popen_kwargs,
    )
    timed_out = False
    termination_requested = False
    termination_method = None
    stdout = b""
    stderr = b""
    while True:
        elapsed = time.monotonic() - start
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            timed_out = True
            break
        try:
            stdout, stderr = process.communicate(
                timeout=min(monitor_interval_seconds, remaining))
            break
        except subprocess.TimeoutExpired:
            observations.append({
                "elapsed_seconds": round(time.monotonic() - start, 6),
                "process_alive": process.poll() is None,
            })
    if timed_out:
        termination_requested = True
        collected, termination_method = _terminate_process_tree(
            process, termination_grace_seconds)
        try:
            stdout, stderr = process.communicate(timeout=max(1.0, termination_grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            collected = process.poll() is not None
    else:
        collected = process.poll() is not None
    duration = time.monotonic() - start
    observations.append({
        "elapsed_seconds": round(duration, 6),
        "process_alive": process.poll() is None,
    })
    return {
        "argv": list(argv),
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "monitor_interval_seconds": monitor_interval_seconds,
        "termination_grace_seconds": termination_grace_seconds,
        "attempt_count": 1,
        "automatic_retry_performed": False,
        "started_at_utc": start_text,
        "ended_at_utc": _utc_now(),
        "wall_clock_duration_seconds": round(duration, 6),
        "monitor_observations": observations,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "termination_requested": termination_requested,
        "termination_method": termination_method,
        "process_tree_collected": collected,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "environment": environment,
    }


_IDENTITY_CONTEXT_FIELDS = {
    "config_sha256", "result_schema_sha256",
    "approved_freeze_receipt_sha256", "generation_freeze_receipt_sha256",
    "generation_source_manifest_sha256",
    "generation_source_set_fingerprint_sha256", "generation_source_entry_count",
    "generation_test_evidence_sha256", "execution_environment_sha256",
    "stage9_input_receipt_sha256", "stage9_config_sha256",
    "stage9_verification_sha256", "stage9_checkpoint_sha256",
    "stage9_latency_summary_sha256", "stage9_run_identity_sha256",
    "timing_provenance_sha256", "scenario_matrix_sha256", "git_commit",
}


def _validate_identity_context(context: Mapping[str, Any]) -> None:
    if not isinstance(context, Mapping) or set(context) != _IDENTITY_CONTEXT_FIELDS:
        raise contract.Stage10V2R2ContractError(
            "Run-identity construction context is incomplete.")
    for name, value in context.items():
        if name == "generation_source_entry_count":
            if (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
                raise contract.Stage10V2R2ContractError(
                    "Generation source entry count is invalid.")
        elif name == "git_commit":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40,64}", value):
                raise contract.Stage10V2R2ContractError("Git commit identity is invalid.")
        elif not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise contract.Stage10V2R2ContractError(
                "Run-identity SHA field is invalid: " + name)


def expected_run_identity(context: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_identity_context(context)
    value = {
        "schema_version": contract.RUN_IDENTITY_SCHEMA_VERSION,
        "contract_id": contract.CONTRACT_ID,
        "run_id": contract.RUN_ID,
        "evidence_mode": contract.EVIDENCE_MODE,
        "config_sha256": context["config_sha256"],
        "result_schema_sha256": context["result_schema_sha256"],
        "approved_design_sha256": contract.APPROVED_DESIGN_SHA256,
        "approved_plan_sha256": contract.APPROVED_PLAN_SHA256,
        "approved_freeze_receipt_sha256":
            context["approved_freeze_receipt_sha256"],
        "generation_freeze_receipt_sha256":
            context["generation_freeze_receipt_sha256"],
        "generation_source_manifest_schema": contract.SOURCE_MANIFEST_SCHEMA,
        "generation_source_manifest_sha256":
            context["generation_source_manifest_sha256"],
        "generation_source_set_id": contract.SOURCE_SET_ID,
        "generation_source_set_fingerprint_sha256":
            context["generation_source_set_fingerprint_sha256"],
        "generation_source_entry_count":
            context["generation_source_entry_count"],
        "generation_test_evidence_sha256":
            context["generation_test_evidence_sha256"],
        "execution_environment_schema": contract.EXECUTION_ENVIRONMENT_SCHEMA,
        "execution_environment_sha256": context["execution_environment_sha256"],
        "stage9_input_receipt_sha256": context["stage9_input_receipt_sha256"],
        "stage9_config_sha256": context["stage9_config_sha256"],
        "stage9_verification_sha256": context["stage9_verification_sha256"],
        "stage9_checkpoint_sha256": context["stage9_checkpoint_sha256"],
        "stage9_latency_summary_sha256": context["stage9_latency_summary_sha256"],
        "stage9_run_identity_sha256": context["stage9_run_identity_sha256"],
        "timing_provenance_sha256": context["timing_provenance_sha256"],
        "scenario_matrix_sha256": context["scenario_matrix_sha256"],
        "conversion_rule": "Decimal ROUND_HALF_UP to integral nanoseconds",
        "controlled_execution": dict(contract.CONTROLLED_EXECUTION),
        "git": {
            "commit": context["git_commit"],
            "generation_source_set_fingerprint_sha256":
                context["generation_source_set_fingerprint_sha256"],
        },
    }
    value["run_identity_sha256"] = contract.self_hash(
        value, "run_identity_sha256")
    return value


def expected_verification(context: Mapping[str, Any],
                          results: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    _validate_identity_context(context)
    if (not isinstance(results, Sequence) or len(results) != 60 or
            any(not isinstance(row, Mapping) or
                not isinstance(row.get("scenario_id"), str) for row in results)):
        raise contract.Stage10V2R2ContractError(
            "Verification requires exactly 60 identified result rows.")
    return {
        "schema_version": contract.VERIFICATION_SCHEMA_VERSION,
        "contract_id": contract.CONTRACT_ID,
        "evidence_mode": contract.EVIDENCE_MODE,
        "status": contract.VERIFIED_STATUS,
        "stage9_input_gate": "satisfied",
        "simulation_executed": True,
        "artifacts_independently_recomputed": True,
        "current_generation_sources_recomputed": True,
        "generation_tests_verified": True,
        "approved_freeze_receipt_sha256":
            context["approved_freeze_receipt_sha256"],
        "generation_source_manifest_sha256":
            context["generation_source_manifest_sha256"],
        "generation_source_set_fingerprint_sha256":
            context["generation_source_set_fingerprint_sha256"],
        "generation_source_entry_count":
            context["generation_source_entry_count"],
        "generation_test_evidence_sha256":
            context["generation_test_evidence_sha256"],
        "execution_environment_sha256": context["execution_environment_sha256"],
        "controlled_execution": dict(contract.CONTROLLED_EXECUTION),
        "result_count": len(results),
        "scenario_ids": [row["scenario_id"] for row in results],
        "real_nvm_measurement_verified": False,
        "kernel_behavior_verified": False,
        "real_concurrency_verified": False,
        "real_foreground_end_to_end_latency_verified": False,
        "real_system_async_performance_verified": False,
    }


def expected_run_state() -> Mapping[str, Any]:
    return {
        "schema_version": contract.RUN_STATE_SCHEMA_VERSION,
        "contract_id": contract.CONTRACT_ID,
        "run_id": contract.RUN_ID,
        "evidence_mode": contract.EVIDENCE_MODE,
        "status": contract.VERIFIED_STATUS,
        "failure": None,
        "stage9_input_gate_passed": True,
        "simulation_executed": True,
        "artifacts_independently_verified": True,
        "real_system_async_performance_verified": False,
    }


def require_complete_metadata(actual, expected) -> None:
    if (not isinstance(actual, tuple) or not isinstance(expected, tuple) or
            len(actual) != 3 or len(expected) != 3):
        raise contract.Stage10V2R2ContractError("Metadata comparison tuple is invalid.")
    identity = actual[0]
    if (not isinstance(identity, Mapping) or
            identity.get("run_identity_sha256") !=
            contract.self_hash(identity, "run_identity_sha256")):
        raise contract.Stage10V2R2ContractError("Run identity self-hash is invalid.")
    labels = ("Run identity", "Verification", "Run state")
    for label, observed, required in zip(labels, actual, expected):
        if observed != required:
            raise contract.Stage10V2R2ContractError(
                label + " does not match the complete independently constructed object.")


def _git_commit(project_root: Path, *, synthetic: bool) -> str:
    if synthetic:
        return "0" * 40
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root,
            capture_output=True, text=True, check=True,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError) as exc:
        raise contract.Stage10V2R2ContractError("Git HEAD cannot be resolved.") from exc
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise contract.Stage10V2R2ContractError("Git HEAD identity is invalid.")
    return value


def _execution_summary(value: Mapping[str, Any]) -> Mapping[str, Any]:
    excluded = {"stdout", "stderr"}
    return {key: item for key, item in value.items() if key not in excluded}


def _synthetic_generation_evidence(project_root: Path,
                                   approved_sha: str,
                                   manifest_sha: str,
                                   snapshot: Mapping[str, Any]):
    log = "synthetic prevalidated generation evidence\n"
    environment = environment_snapshot(())
    evidence = {
        "schema_version": contract.GENERATION_TEST_EVIDENCE_SCHEMA,
        "approved_freeze_receipt_sha256": approved_sha,
        "source_manifest_sha256": manifest_sha,
        "argv": [sys.executable, "synthetic-prevalidated"],
        "cwd": str(project_root.resolve()),
        "timeout_seconds": contract.CONTROLLED_EXECUTION[
            "generation_core_test_timeout_seconds"],
        "monitor_interval_seconds": contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        "termination_grace_seconds": contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"],
        "attempt_count": 1,
        "automatic_retry_performed": False,
        "pre_source_snapshot": snapshot,
        "post_source_snapshot": snapshot,
        "test_count": 1,
        "ordered_verbose_test_ids": ["synthetic.test"],
        "final_status": "OK",
        "exit_code": 0,
        "timed_out": False,
        "environment": environment,
        "log_sha256": hashlib.sha256(log.encode("utf-8")).hexdigest(),
        "synthetic_test_only": True,
    }
    execution = {
        "schema_version": contract.EXECUTION_ENVIRONMENT_SCHEMA,
        "generation_test": {
            "environment": environment,
            "timeout_seconds": evidence["timeout_seconds"],
            "timed_out": False,
            "wall_clock_observation": "synthetic-test-only",
        },
        "formal_simulation_worker": {
            "environment": environment,
            "timeout_seconds": contract.CONTROLLED_EXECUTION[
                "formal_simulation_timeout_seconds"],
            "timed_out": False,
            "wall_clock_observation": "synthetic-test-only",
        },
    }
    return log, evidence, execution


def _parse_unittest_log(text: str) -> tuple[int, list[str]]:
    matches = re.findall(r"(?m)^Ran\s+(\d+)\s+tests?\b", text)
    if len(matches) != 1:
        raise contract.Stage10V2R2ContractError(
            "Controlled unittest log must contain one Ran N tests line.")
    count = int(matches[0])
    identities = []
    for line in text.splitlines():
        stripped = line.strip()
        identity = re.fullmatch(
            r"test_[^\s()]+\s+\(([^\s()]+)\)\s+\.\.\. ok", stripped)
        if identity:
            identities.append(identity.group(1))
    nonempty = [line.strip() for line in text.splitlines() if line.strip()]
    if (len(identities) != count or not nonempty or nonempty[-1] != "OK" or
            any(line.startswith("FAILED") or line.startswith("ERROR")
                for line in nonempty)):
        raise contract.Stage10V2R2ContractError(
            "Controlled unittest log does not prove exact final success.")
    return count, identities


def run_generation_tests(config: Mapping[str, Any], project_root: Path,
                         source_manifest: Mapping[str, Any],
                         pre_snapshot: Mapping[str, Any],
                         approved_sha: str):
    generation = config["generation_tests"]
    argv = [sys.executable, *generation["argv_suffix"]]
    process = run_controlled_process(
        argv, cwd=project_root,
        timeout_seconds=contract.CONTROLLED_EXECUTION[
            "generation_core_test_timeout_seconds"],
        monitor_interval_seconds=contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        termination_grace_seconds=contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"],
        dependency_names=(),
    )
    post_snapshot = contract.snapshot_generation_sources(project_root, source_manifest)
    if pre_snapshot != post_snapshot:
        raise contract.Stage10V2R2ContractError(
            "Generation source set changed during controlled tests.")
    log = process["stdout"] + process["stderr"]
    if process["timed_out"] or process["exit_code"] != 0:
        raise contract.Stage10V2R2ContractError(
            "Controlled generation tests failed or timed out.")
    count, identities = _parse_unittest_log(log)
    if (count != generation["expected_test_count"] or
            identities != generation["ordered_verbose_test_ids"]):
        raise contract.Stage10V2R2ContractError(
            "Controlled generation test identities differ from the freeze.")
    evidence = {
        "schema_version": contract.GENERATION_TEST_EVIDENCE_SCHEMA,
        "approved_freeze_receipt_sha256": approved_sha,
        "source_manifest_sha256":
            contract.sha256_file(project_root / contract.SOURCE_MANIFEST_PATH),
        "argv": argv,
        "cwd": str(project_root.resolve()),
        "timeout_seconds": process["timeout_seconds"],
        "monitor_interval_seconds": process["monitor_interval_seconds"],
        "termination_grace_seconds": process["termination_grace_seconds"],
        "attempt_count": process["attempt_count"],
        "automatic_retry_performed": process["automatic_retry_performed"],
        "pre_source_snapshot": pre_snapshot,
        "post_source_snapshot": post_snapshot,
        "test_count": count,
        "ordered_verbose_test_ids": identities,
        "final_status": "OK",
        "exit_code": process["exit_code"],
        "timed_out": process["timed_out"],
        "environment": process["environment"],
        "log_sha256": hashlib.sha256(log.encode("utf-8")).hexdigest(),
    }
    return log, evidence, process


def _replace_approved_placeholder(argv_suffix: Sequence[str], approved_sha: str):
    token = "<external-approved-freeze-receipt-sha256>"
    if list(argv_suffix).count(token) != 1:
        raise contract.Stage10V2R2ContractError(
            "Controlled command approved-SHA placeholder is invalid.")
    return [approved_sha if item == token else item for item in argv_suffix]


def run_formal_worker(config: Mapping[str, Any], project_root: Path,
                      approved_sha: str) -> Mapping[str, Any]:
    suffix = _replace_approved_placeholder(
        config["formal_simulation_worker"]["argv_suffix"], approved_sha)
    return run_controlled_process(
        [sys.executable, *suffix], cwd=project_root,
        timeout_seconds=contract.CONTROLLED_EXECUTION[
            "formal_simulation_timeout_seconds"],
        monitor_interval_seconds=contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        termination_grace_seconds=contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"],
        dependency_names=(),
    )


def _metadata_context(run_root: Path, config: Mapping[str, Any], audit,
                      snapshot: Mapping[str, Any], approved_sha: str,
                      project_root: Path, *, synthetic: bool) -> Mapping[str, Any]:
    return {
        "config_sha256": contract.sha256_file(run_root / "config.json"),
        "result_schema_sha256": config["result_schema_sha256"],
        "approved_freeze_receipt_sha256": approved_sha,
        "generation_freeze_receipt_sha256":
            contract.sha256_file(run_root / "generation_freeze_receipt.json"),
        "generation_source_manifest_sha256":
            contract.sha256_file(run_root / "generation_source_manifest.json"),
        "generation_source_set_fingerprint_sha256": snapshot["fingerprint_sha256"],
        "generation_source_entry_count": snapshot["entry_count"],
        "generation_test_evidence_sha256":
            contract.sha256_file(run_root / "generation_test_evidence.json"),
        "execution_environment_sha256":
            contract.sha256_file(run_root / "execution_environment.json"),
        "stage9_input_receipt_sha256":
            contract.sha256_file(run_root / "stage9_input_receipt.json"),
        "stage9_config_sha256": audit.binding.config_sha256,
        "stage9_verification_sha256": audit.binding.verification_sha256,
        "stage9_checkpoint_sha256": audit.binding.checkpoint_sha256,
        "stage9_latency_summary_sha256": audit.binding.latency_summary_sha256,
        "stage9_run_identity_sha256": audit.binding.run_identity_sha256,
        "timing_provenance_sha256":
            contract.sha256_file(run_root / "timing_provenance.json"),
        "scenario_matrix_sha256":
            contract.sha256_file(run_root / "scenario_matrix.json"),
        "git_commit": _git_commit(project_root, synthetic=synthetic),
    }


def _write_run_payloads(
        run_root: Path, config: Mapping[str, Any], audit,
        provenance: Mapping[str, Any], matrix, results,
        repository_manifest: Mapping[str, Any], repository_receipt: Path,
        source_snapshot: Mapping[str, Any], approved_sha: str,
        generation_log: str, generation_evidence: Mapping[str, Any],
        execution_environment: Mapping[str, Any], project_root: Path,
        *, synthetic: bool) -> None:
    write_json(run_root / "config.json", config)
    write_json(run_root / "stage9_input_receipt.json", audit.receipt)
    write_json(run_root / "timing_provenance.json", provenance)
    write_json(run_root / "scenario_matrix.json",
               legacy_runner._matrix_payload(config, matrix))
    write_text(run_root / "simulation_results.jsonl", "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False) + "\n"
        for row in results))
    write_json(run_root / "generation_source_manifest.json", repository_manifest)
    shutil.copyfile(repository_receipt, run_root / "generation_freeze_receipt.json")
    write_text(run_root / "generation_test_log.txt", generation_log)
    write_json(run_root / "generation_test_evidence.json", generation_evidence)
    write_json(run_root / "execution_environment.json", execution_environment)
    write_text(run_root / "event_model.md",
               "# Stage10 v2-r2 Event Model\n\n"
               "Deterministic integer-nanosecond discrete events preserve the approved "
               "Stage10 v2 event priority, reserved-page, capacity, LRU-tail, "
               "MRU-admission, FIFO-blocking, fallback, and exhaustion-integral semantics.\n")
    write_text(run_root / "parameters.md",
               "# Stage10 v2-r2 Parameters\n\n"
               "Stage9 r3 supplies inference timing. Migration timing remains a "
               "predeclared simulator scenario and is not an NVM measurement.\n")
    write_text(run_root / "README.md",
               "CAPD Stage10 v2-r2 deterministic async-simulation evidence. "
               "It is not real-system asynchronous-performance evidence.\n")
    write_text(run_root / "report.md",
               "# Stage10 v2-r2 Deterministic Simulation\n\n"
               f"Scenario rows: {len(results)}\n\n"
               "Real NVM, kernel concurrency, foreground end-to-end latency, and "
               "real-system asynchronous performance remain unverified.\n")
    context = _metadata_context(
        run_root, config, audit, source_snapshot, approved_sha, project_root,
        synthetic=synthetic)
    write_json(run_root / "run_identity.json", expected_run_identity(context))
    write_json(run_root / "verification.json", expected_verification(context, results))
    write_json(run_root / "run_state.json", expected_run_state())
    write_json(run_root / "manifest.json", _manifest_value(run_root))
    _write_checksums(run_root)


def _simulate(config: Mapping[str, Any], audit):
    provenance = stage10_v2.derive_timing_provenance(audit)
    streams = stage10_v2.build_arrival_streams(config, provenance)
    matrix = stage10_v2.expand_scenario_matrix(config, provenance, streams)
    results = []
    for scenario in matrix:
        key = (scenario["comparison_channel"], scenario["timing_profile_id"],
               scenario["arrival_profile_id"])
        results.append(stage10_v2.simulate_scenario(config, scenario, streams[key]))
    return provenance, streams, matrix, results


def build_prevalidated_test_run(
        *, config: Mapping[str, Any], binding: stage10_v2.TrustedStage9Binding,
        stage9_run_root: Path, output_root: Path, project_root: Path,
        source_manifest: Mapping[str, Any], repository_receipt: Path,
        approved_freeze_receipt_sha256: str) -> Path:
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve()
    if project_root == ROOT or not stage10_v2._inside(project_root, output_root):
        raise contract.Stage10V2R2ContractError(
            "Synthetic r2 runs are restricted to an external temporary root.")
    validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, Path(repository_receipt))
    snapshot = contract.snapshot_generation_sources(project_root, source_manifest)
    target = output_root / contract.RUN_ID
    if target.exists():
        raise contract.Stage10V2R2ContractError("Stage10 r2 run ID already exists.")
    audit = stage10_v2.audit_stage9_run(stage9_run_root, binding)
    provenance, _, matrix, results = _simulate(config, audit)
    log, evidence, environment = _synthetic_generation_evidence(
        project_root, approved_freeze_receipt_sha256,
        contract.sha256_file(project_root / contract.SOURCE_MANIFEST_PATH), snapshot)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        _write_run_payloads(
            target, config, audit, provenance, matrix, results, source_manifest,
            Path(repository_receipt), snapshot, approved_freeze_receipt_sha256,
            log, evidence, environment, project_root, synthetic=True)
    except Exception as exc:
        write_json(target / "run_state.json", {
            "schema_version": contract.RUN_STATE_SCHEMA_VERSION,
            "contract_id": contract.CONTRACT_ID, "run_id": contract.RUN_ID,
            "evidence_mode": contract.EVIDENCE_MODE,
            "status": contract.FAILURE_STATUS,
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "real_system_async_performance_verified": False,
        })
        raise
    return target


def _verify_manifest_and_checksums(root: Path) -> Mapping[str, Any]:
    names = {relative for relative, _ in _relative_files(root)}
    if names != EXPECTED_ARTIFACTS:
        raise contract.Stage10V2R2ContractError("Stage10 r2 artifact set is not exact.")
    manifest = contract.load_json(root / "manifest.json")
    if (manifest.get("schema_version") != contract.MANIFEST_SCHEMA_VERSION or
            set(manifest) != {"schema_version", "files"}):
        raise contract.Stage10V2R2ContractError("Stage10 r2 manifest is invalid.")
    payload_names = names - {"manifest.json", "SHA256SUMS"}
    if set(manifest.get("files", {})) != payload_names:
        raise contract.Stage10V2R2ContractError("Manifest file set differs.")
    for relative, digest in manifest["files"].items():
        path = contract.resolve_regular_file(root, relative)
        if contract.sha256_file(path) != digest:
            raise contract.Stage10V2R2ContractError("Manifest mismatch: " + relative)
    rows = []
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise contract.Stage10V2R2ContractError("Malformed SHA256SUMS.") from exc
        rows.append((digest, relative))
    if {relative for _, relative in rows} != names - {"SHA256SUMS"}:
        raise contract.Stage10V2R2ContractError("SHA256SUMS file set differs.")
    for digest, relative in rows:
        path = contract.resolve_regular_file(root, relative)
        if contract.sha256_file(path) != digest:
            raise contract.Stage10V2R2ContractError("SHA256SUMS mismatch: " + relative)
    return manifest


def _validate_test_config(config: Mapping[str, Any]) -> None:
    if (config.get("schema_version") != contract.CONFIG_SCHEMA_VERSION or
            config.get("contract_id") != contract.CONTRACT_ID or
            config.get("run_id") != contract.RUN_ID or
            config.get("scenario_count") != 60 or
            config.get("evidence_mode") != contract.EVIDENCE_MODE):
        raise contract.Stage10V2R2ContractError("Synthetic r2 config identity is invalid.")
    horizon = config.get("simulator_parameters", {}).get("simulation_horizon_ns")
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
        raise contract.Stage10V2R2ContractError("Synthetic horizon is invalid.")


def _validate_generation_evidence(
        root: Path, config: Mapping[str, Any], snapshot: Mapping[str, Any],
        approved_sha: str, *, allow_test_parameters: bool) -> Mapping[str, Any]:
    evidence = contract.load_json(root / "generation_test_evidence.json")
    log_sha = contract.sha256_file(root / "generation_test_log.txt")
    required = {
        "schema_version": contract.GENERATION_TEST_EVIDENCE_SCHEMA,
        "approved_freeze_receipt_sha256": approved_sha,
        "source_manifest_sha256":
            contract.sha256_file(root / "generation_source_manifest.json"),
        "pre_source_snapshot": snapshot,
        "post_source_snapshot": snapshot,
        "final_status": "OK", "exit_code": 0, "timed_out": False,
        "log_sha256": log_sha,
    }
    if any(evidence.get(key) != value for key, value in required.items()):
        raise contract.Stage10V2R2ContractError(
            "Generation-test evidence does not independently recompute.")
    if (evidence.get("attempt_count") != 1 or
            evidence.get("automatic_retry_performed") is not False):
        raise contract.Stage10V2R2ContractError("Generation test was retried.")
    if not allow_test_parameters:
        generation = config["generation_tests"]
        if (evidence.get("argv") != [sys.executable, *generation["argv_suffix"]] or
                evidence.get("test_count") != generation["expected_test_count"] or
                evidence.get("ordered_verbose_test_ids") !=
                generation["ordered_verbose_test_ids"]):
            raise contract.Stage10V2R2ContractError(
                "Generation-test command/count identity changed.")
    return evidence


def verify_r2_run(
        run_root: os.PathLike[str] | str, *, project_root: Path = ROOT,
        binding: stage10_v2.TrustedStage9Binding | None = None,
        repository_config: Mapping[str, Any] | None = None,
        repository_manifest: Mapping[str, Any] | None = None,
        repository_receipt: Path | None = None,
        approved_freeze_receipt_sha256: str | None = None,
        allow_test_parameters: bool = False) -> Mapping[str, Any]:
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise contract.Stage10V2R2ContractError("Stage10 r2 run directory is missing.")
    project_root = Path(project_root).resolve()
    if repository_receipt is None:
        repository_receipt = project_root / contract.FREEZE_RECEIPT_PATH
    approved_sha = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt,
        root / "generation_freeze_receipt.json")
    manifest_payload = _verify_manifest_and_checksums(root)

    saved_config = contract.load_json(root / "config.json")
    if repository_config is None:
        repository_config = contract.load_json(project_root / contract.CONFIG_PATH)
    if saved_config != repository_config:
        raise contract.Stage10V2R2ContractError(
            "Run config is not the exact repository config.")
    if allow_test_parameters:
        _validate_test_config(saved_config)
    else:
        contract.validate_config(saved_config)
        _validate_repository_bindings(saved_config, project_root)

    saved_manifest = contract.load_json(root / "generation_source_manifest.json")
    if repository_manifest is None:
        repository_manifest = contract.load_json(project_root / contract.SOURCE_MANIFEST_PATH)
    if saved_manifest != repository_manifest:
        raise contract.Stage10V2R2ContractError(
            "Run source manifest is not the exact repository manifest.")
    snapshot = contract.snapshot_generation_sources(project_root, repository_manifest)
    source_binding = saved_config["generation_source_manifest"]
    if (contract.sha256_file(project_root / contract.SOURCE_MANIFEST_PATH) !=
            source_binding["sha256"] or
            snapshot["fingerprint_sha256"] != source_binding["fingerprint_sha256"] or
            snapshot["entry_count"] != source_binding["entry_count"]):
        raise contract.Stage10V2R2ContractError(
            "Current generation source set does not match config binding.")

    if binding is None:
        binding = stage10_v2.production_stage9_binding(saved_config, project_root)
    audit = stage10_v2.audit_stage9_run(binding.output_root / binding.run_id, binding)
    if contract.load_json(root / "stage9_input_receipt.json") != audit.receipt:
        raise contract.Stage10V2R2ContractError("Stage9 receipt does not recompute.")
    provenance, _, matrix, expected_results = _simulate(saved_config, audit)
    if contract.load_json(root / "timing_provenance.json") != provenance:
        raise contract.Stage10V2R2ContractError("Timing provenance does not recompute.")
    if contract.load_json(root / "scenario_matrix.json") != \
            legacy_runner._matrix_payload(saved_config, matrix):
        raise contract.Stage10V2R2ContractError("Scenario matrix does not recompute.")
    actual_results = [json.loads(line) for line in
                      (root / "simulation_results.jsonl").read_text(
                          encoding="utf-8").splitlines() if line]
    if actual_results != expected_results:
        raise contract.Stage10V2R2ContractError("Simulation results do not recompute.")
    result_schema = contract.load_json(project_root / saved_config["result_schema"])
    if (contract.sha256_file(project_root / saved_config["result_schema"]) !=
            saved_config["result_schema_sha256"]):
        raise contract.Stage10V2R2ContractError("Result-schema SHA binding mismatch.")
    for row in actual_results:
        stage10_v2.validate_result_line(row, result_schema)

    evidence = _validate_generation_evidence(
        root, saved_config, snapshot, approved_sha,
        allow_test_parameters=allow_test_parameters)
    execution = contract.load_json(root / "execution_environment.json")
    if (execution.get("schema_version") != contract.EXECUTION_ENVIRONMENT_SCHEMA or
            execution.get("generation_test", {}).get("environment") !=
            evidence.get("environment")):
        raise contract.Stage10V2R2ContractError("Execution environment is invalid.")
    current_environment = environment_snapshot(())
    for phase in ("generation_test", "formal_simulation_worker"):
        if execution.get(phase, {}).get("environment") != current_environment:
            raise contract.Stage10V2R2ContractError(
                "Current execution environment differs from run evidence.")

    context = _metadata_context(
        root, saved_config, audit, snapshot, approved_sha, project_root,
        synthetic=allow_test_parameters)
    actual_metadata = (
        contract.load_json(root / "run_identity.json"),
        contract.load_json(root / "verification.json"),
        contract.load_json(root / "run_state.json"),
    )
    expected_metadata = (
        expected_run_identity(context),
        expected_verification(context, expected_results),
        expected_run_state(),
    )
    require_complete_metadata(actual_metadata, expected_metadata)
    return {
        "status": contract.VERIFIED_STATUS,
        "result_count": len(actual_results),
        "manifest_files": len(manifest_payload["files"]),
        "real_system_async_performance_verified": False,
    }


def _validate_repository_bindings(config: Mapping[str, Any], project_root: Path):
    contract.validate_config(config)
    if (contract.sha256_file(project_root / contract.APPROVED_DESIGN_PATH) !=
            contract.APPROVED_DESIGN_SHA256 or
            contract.sha256_file(project_root / contract.APPROVED_PLAN_PATH) !=
            contract.APPROVED_PLAN_SHA256):
        raise contract.Stage10V2R2ContractError("Approved design/plan SHA changed.")
    source_path = project_root / contract.SOURCE_MANIFEST_PATH
    source_manifest = contract.load_json(source_path)
    snapshot = contract.snapshot_generation_sources(project_root, source_manifest)
    binding = config["generation_source_manifest"]
    if (contract.sha256_file(source_path) != binding["sha256"] or
            snapshot["entry_count"] != binding["entry_count"] or
            snapshot["fingerprint_sha256"] != binding["fingerprint_sha256"]):
        raise contract.Stage10V2R2ContractError("Source-manifest binding changed.")
    for name, schema_version in contract.METADATA_SCHEMA_VERSIONS.items():
        item = config["metadata_schemas"][name]
        path = project_root / item["path"]
        schema = contract.load_json(path)
        if (contract.sha256_file(path) != item["sha256"] or
                schema.get("schema_version") != schema_version or
                schema.get("additionalProperties") is not False):
            raise contract.Stage10V2R2ContractError(
                "Metadata schema binding changed: " + name)
    release = config["release_contract"]["release_test_module"]
    if contract.sha256_file(project_root / release["path"]) != release["sha256"]:
        raise contract.Stage10V2R2ContractError("Release-test module SHA changed.")
    receipt_path = project_root / contract.FREEZE_RECEIPT_PATH
    receipt = contract.load_json(receipt_path)
    contract.validate_freeze_receipt(receipt, config, project_root)
    return source_manifest, snapshot


def build_run(*, config_path: Path, stage9_run_root: Path, output_root: Path,
              run_id: str, approved_freeze_receipt_sha256: str,
              project_root: Path = ROOT) -> Path:
    project_root = Path(project_root).resolve()
    expected_config_path = (project_root / contract.CONFIG_PATH).resolve()
    if Path(config_path).resolve() != expected_config_path:
        raise contract.Stage10V2R2ContractError(
            "Only the repository Stage10 r2 config is allowed.")
    config = contract.load_json(expected_config_path)
    source_manifest, snapshot = _validate_repository_bindings(config, project_root)
    if run_id != contract.RUN_ID:
        raise contract.Stage10V2R2ContractError("Stage10 r2 run-id override is forbidden.")
    expected_output = (project_root / config["output_root"]).resolve()
    if Path(output_root).resolve() != expected_output:
        raise contract.Stage10V2R2ContractError("Stage10 r2 output-root override is forbidden.")
    repository_receipt = project_root / contract.FREEZE_RECEIPT_PATH
    approved_sha = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt)
    binding = stage10_v2.production_stage9_binding(config, project_root)
    expected_stage9 = binding.output_root / binding.run_id
    if Path(stage9_run_root).resolve() != expected_stage9.resolve():
        raise contract.Stage10V2R2ContractError("Only approved Stage9 r3 is allowed.")
    audit = stage10_v2.audit_stage9_run(expected_stage9, binding)
    target = expected_output / contract.RUN_ID
    if target.exists():
        raise contract.Stage10V2R2ContractError("Stage10 r2 run ID already exists.")
    generation_log, generation_evidence, generation_process = \
        run_generation_tests(config, project_root, source_manifest, snapshot,
                             approved_sha)
    if target.exists():
        raise contract.Stage10V2R2ContractError("Stage10 r2 run ID appeared during preflight.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        worker = run_formal_worker(config, project_root, approved_sha)
        if worker["timed_out"] or worker["exit_code"] != 0:
            raise contract.Stage10V2R2ContractError(
                "Formal simulation worker failed or timed out.")
        bundle = json.loads(worker["stdout"])
        provenance = bundle["timing_provenance"]
        matrix = bundle["scenario_matrix"]
        results = bundle["results"]
        if len(results) != 60:
            raise contract.Stage10V2R2ContractError("Formal worker result count is not 60.")
        execution = {
            "schema_version": contract.EXECUTION_ENVIRONMENT_SCHEMA,
            "generation_test": _execution_summary(generation_process),
            "formal_simulation_worker": _execution_summary(worker),
        }
        _write_run_payloads(
            target, config, audit, provenance, matrix["scenarios"], results,
            source_manifest, repository_receipt, snapshot, approved_sha,
            generation_log, generation_evidence, execution, project_root,
            synthetic=False)
        verify_r2_run(
            target, project_root=project_root,
            approved_freeze_receipt_sha256=approved_sha)
    except Exception as exc:
        write_json(target / "run_state.json", {
            "schema_version": contract.RUN_STATE_SCHEMA_VERSION,
            "contract_id": contract.CONTRACT_ID, "run_id": contract.RUN_ID,
            "evidence_mode": contract.EVIDENCE_MODE,
            "status": contract.FAILURE_STATUS,
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "real_system_async_performance_verified": False,
        })
        raise
    return target


def formal_simulation_worker(*, config_path: Path, stage9_run_root: Path,
                             approved_freeze_receipt_sha256: str,
                             project_root: Path = ROOT) -> Mapping[str, Any]:
    project_root = Path(project_root).resolve()
    expected_config = (project_root / contract.CONFIG_PATH).resolve()
    if Path(config_path).resolve() != expected_config:
        raise contract.Stage10V2R2ContractError(
            "Formal worker requires the repository r2 config.")
    config = contract.load_json(expected_config)
    _validate_repository_bindings(config, project_root)
    validate_approved_freeze_sha(
        approved_freeze_receipt_sha256,
        project_root / contract.FREEZE_RECEIPT_PATH)
    binding = stage10_v2.production_stage9_binding(config, project_root)
    expected_stage9 = binding.output_root / binding.run_id
    if Path(stage9_run_root).resolve() != expected_stage9.resolve():
        raise contract.Stage10V2R2ContractError(
            "Formal worker requires approved Stage9 r3.")
    audit = stage10_v2.audit_stage9_run(expected_stage9, binding)
    provenance, _, matrix, results = _simulate(config, audit)
    return {
        "schema_version": "capd_proactive_stage10_formal_worker_bundle_v1_0",
        "timing_provenance": provenance,
        "scenario_matrix": legacy_runner._matrix_payload(config, matrix),
        "results": results,
    }


READINESS_FILES = {
    "release_readiness_test_log.txt", "release_test_source_snapshot.py",
    "protocol_pending_snapshot.md", "status_pending_snapshot.md",
    "release_readiness_test_evidence.json", "stage11_negative_audit_log.txt",
    "stage11_negative_audit_source_snapshot.json",
    "stage11_negative_audit_result.json", "stage11_negative_audit_evidence.json",
    "release_readiness_receipt.json", "manifest.json", "SHA256SUMS",
}
FINAL_STATUS_FILES = {
    "final_status_test_log.txt", "release_test_source_snapshot.py",
    "protocol_final_snapshot.md", "status_final_snapshot.md",
    "final_status_test_evidence.json", "final_status_evidence_receipt.json",
    "manifest.json", "SHA256SUMS",
}


def validate_stage11_result(value: Mapping[str, Any]) -> None:
    stable = {
        "stage10a": value.get("stage10a"),
        "stage10_r2": value.get("stage10_r2"),
        "stage11_positive_migration_authorized":
            value.get("stage11_positive_migration_authorized"),
    }
    if stable != contract.STAGE11_EXPECTED:
        raise contract.Stage10V2R2ContractError(
            "Stage11 audit does not match the exact frozen negative triples.")


def _snapshot_paths(project_root: Path,
                    relative_paths: Sequence[str]) -> Mapping[str, Any]:
    files = []
    for relative in sorted(set(relative_paths)):
        path = contract.resolve_regular_file(project_root, relative)
        files.append({
            "path": relative,
            "length": path.stat().st_size,
            "sha256": contract.sha256_file(path),
        })
    return {
        "file_count": len(files),
        "fingerprint_sha256": contract.fingerprint_value(files),
        "files": files,
    }


def _snapshot_optional_tree(root: Path) -> Mapping[str, Any]:
    if not root.exists():
        return {"exists": False, "file_count": 0,
                "fingerprint_sha256": contract.fingerprint_value([]), "files": []}
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files.append({
            "path": path.relative_to(root).as_posix(),
            "length": path.stat().st_size,
            "sha256": contract.sha256_file(path),
        })
    return {"exists": True, "file_count": len(files),
            "fingerprint_sha256": contract.fingerprint_value(files), "files": files}


def _production_generation_chain(run_root: Path,
                                 approved_sha: str) -> Mapping[str, Any]:
    run_root = Path(run_root).resolve()
    native = verify_r2_run(
        run_root, approved_freeze_receipt_sha256=approved_sha)
    from scripts import run_capd_proactive_stage10 as dispatcher
    dispatched = dispatcher.verify_run(
        str(run_root), approved_freeze_receipt_sha256=approved_sha)
    stage10a_root = run_root.parent / "stage10-async-simulator-r1"
    stage10a = dispatcher.verify_v1_fixture_run(str(stage10a_root))
    stage9_receipt = contract.load_json(run_root / "stage9_input_receipt.json")
    return {
        "run_identity_sha256": contract.sha256_file(run_root / "run_identity.json"),
        "verification_sha256": contract.sha256_file(run_root / "verification.json"),
        "run_state_sha256": contract.sha256_file(run_root / "run_state.json"),
        "manifest_sha256": contract.sha256_file(run_root / "manifest.json"),
        "checksums_sha256": contract.sha256_file(run_root / "SHA256SUMS"),
        "native_verifier_status": native["status"],
        "dispatcher_verifier_status": dispatched["status"],
        "stage9_artifact_sha256_verified_count":
            stage9_receipt["artifact_sha256_verified_count"],
        "stage10a": stage10a,
        "synthetic_test_only": False,
    }


def create_release_readiness(
        run_root: Path, *, approved_freeze_receipt_sha256: str,
        project_root: Path = ROOT) -> Path:
    project_root = Path(project_root).resolve()
    run_root = Path(run_root).resolve()
    expected_run = (project_root / "outputs/capd_proactive_stage10" /
                    contract.RUN_ID).resolve()
    if run_root != expected_run:
        raise contract.Stage10V2R2ContractError(
            "Readiness requires the unique production r2 run.")
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256,
        project_root / contract.FREEZE_RECEIPT_PATH,
        run_root / "generation_freeze_receipt.json")
    config = contract.load_json(project_root / contract.CONFIG_PATH)
    _validate_repository_bindings(config, project_root)
    generation_chain = _production_generation_chain(run_root, approved)
    release_root = (project_root / "outputs/capd_proactive_stage10/release_receipts" /
                    contract.RUN_ID / "readiness").resolve()
    if release_root.exists():
        raise contract.Stage10V2R2ContractError(
            "Release readiness directory already exists.")

    release_paths = [
        config["release_contract"]["release_test_module"]["path"],
        "docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md",
        "docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md",
    ]
    release_pre = _snapshot_paths(project_root, release_paths)
    readiness_argv = [
        sys.executable,
        *config["release_contract"]["readiness_test_argv_suffix"],
    ]
    readiness_process = run_controlled_process(
        readiness_argv, cwd=project_root,
        timeout_seconds=contract.CONTROLLED_EXECUTION[
            "release_readiness_test_timeout_seconds"],
        monitor_interval_seconds=contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        termination_grace_seconds=contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"], dependency_names=())
    release_post = _snapshot_paths(project_root, release_paths)
    readiness_log = readiness_process["stdout"] + readiness_process["stderr"]
    if (release_pre != release_post or readiness_process["timed_out"] or
            readiness_process["exit_code"] != 0):
        raise contract.Stage10V2R2ContractError(
            "Release-readiness test failed, timed out, or changed source.")
    readiness_count, readiness_ids = _parse_unittest_log(readiness_log)
    if readiness_count != 1:
        raise contract.Stage10V2R2ContractError(
            "Release-readiness test count is not exact.")

    audit_paths = [
        config["release_contract"]["release_test_module"]["path"],
        "qmap/proactive_stage11.py", "qmap/proactive_stage10.py",
        "qmap/proactive_stage10_v2.py", "qmap/proactive_stage10_v2_r2.py",
        "scripts/run_capd_proactive_stage10.py",
        "scripts/run_capd_proactive_stage10_v2.py",
        "scripts/run_capd_proactive_stage10_v2_r2.py",
    ]
    audit_pre = _snapshot_paths(project_root, audit_paths)
    stage11_output = project_root / "outputs/capd_proactive_stage11"
    stage11_output_pre = _snapshot_optional_tree(stage11_output)
    audit_suffix = _replace_approved_placeholder(
        config["release_contract"]["stage11_audit_argv_suffix"], approved)
    audit_process = run_controlled_process(
        [sys.executable, *audit_suffix], cwd=project_root,
        timeout_seconds=contract.CONTROLLED_EXECUTION[
            "stage11_negative_audit_timeout_seconds"],
        monitor_interval_seconds=contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        termination_grace_seconds=contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"], dependency_names=())
    audit_post = _snapshot_paths(project_root, audit_paths)
    stage11_output_post = _snapshot_optional_tree(stage11_output)
    if (audit_pre != audit_post or stage11_output_pre != stage11_output_post or
            audit_process["timed_out"] or audit_process["exit_code"] != 0):
        raise contract.Stage10V2R2ContractError(
            "Stage11 audit failed, timed out, changed dependencies, or wrote output.")
    try:
        stage11_result = json.loads(audit_process["stdout"].strip())
    except json.JSONDecodeError as exc:
        raise contract.Stage10V2R2ContractError(
            "Stage11 audit did not emit one canonical JSON result.") from exc
    validate_stage11_result(stage11_result)
    audit_log = audit_process["stdout"] + audit_process["stderr"]

    release_root.parent.mkdir(parents=True, exist_ok=True)
    release_root.mkdir()
    try:
        write_text(release_root / "release_readiness_test_log.txt", readiness_log)
        shutil.copyfile(project_root / release_paths[0],
                        release_root / "release_test_source_snapshot.py")
        shutil.copyfile(project_root / release_paths[1],
                        release_root / "protocol_pending_snapshot.md")
        shutil.copyfile(project_root / release_paths[2],
                        release_root / "status_pending_snapshot.md")
        write_json(release_root / "release_readiness_test_evidence.json", {
            "schema_version": contract.RELEASE_TEST_EVIDENCE_SCHEMA,
            "phase": "readiness", "argv": readiness_argv,
            "timeout_seconds": readiness_process["timeout_seconds"],
            "pre_source_snapshot": release_pre,
            "post_source_snapshot": release_post,
            "log_sha256": contract.sha256_file(
                release_root / "release_readiness_test_log.txt"),
            "test_count": readiness_count,
            "ordered_verbose_test_ids": readiness_ids,
            "final_status": "OK", "exit_code": 0, "timed_out": False,
            "environment": readiness_process["environment"],
        })
        write_text(release_root / "stage11_negative_audit_log.txt", audit_log)
        write_json(release_root / "stage11_negative_audit_source_snapshot.json", {
            "schema_version": "capd_proactive_stage10_stage11_source_snapshot_v1_0",
            "pre": audit_pre, "post": audit_post,
            "stage11_output_pre": stage11_output_pre,
            "stage11_output_post": stage11_output_post,
            "stage11_output_created": False,
        })
        write_json(release_root / "stage11_negative_audit_result.json", stage11_result)
        write_json(release_root / "stage11_negative_audit_evidence.json", {
            "schema_version": contract.STAGE11_AUDIT_EVIDENCE_SCHEMA,
            "argv": [sys.executable, *audit_suffix],
            "timeout_seconds": audit_process["timeout_seconds"],
            "pre_dependency_snapshot": audit_pre,
            "post_dependency_snapshot": audit_post,
            "result_sha256": contract.sha256_file(
                release_root / "stage11_negative_audit_result.json"),
            "log_sha256": contract.sha256_file(
                release_root / "stage11_negative_audit_log.txt"),
            "exit_code": 0, "timed_out": False,
            "environment": audit_process["environment"],
        })
        write_json(release_root / "release_readiness_receipt.json",
                   _expected_readiness_receipt(
                       release_root, approved, stage11_result, generation_chain,
                       synthetic=False))
        _write_release_manifest(release_root, "readiness")
    except Exception:
        raise
    return release_root


def _release_manifest_value(root: Path, phase: str) -> Mapping[str, Any]:
    files = {
        relative: contract.sha256_file(path)
        for relative, path in _relative_files(root)
        if relative not in {"manifest.json", "SHA256SUMS"}
    }
    return {
        "schema_version": contract.RELEASE_MANIFEST_SCHEMA,
        "phase": phase,
        "files": files,
    }


def _write_release_manifest(root: Path, phase: str) -> None:
    write_json(root / "manifest.json", _release_manifest_value(root, phase))
    _write_checksums(root)


def _verify_release_manifest(root: Path, phase: str,
                             expected_files: set[str]) -> Mapping[str, Any]:
    names = {relative for relative, _ in _relative_files(root)}
    if names != expected_files:
        raise contract.Stage10V2R2ContractError(
            "Release evidence file set is not exact.")
    manifest = contract.load_json(root / "manifest.json")
    if manifest != _release_manifest_value(root, phase):
        raise contract.Stage10V2R2ContractError(
            "Release manifest does not independently recompute.")
    rows = []
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise contract.Stage10V2R2ContractError(
                "Release SHA256SUMS is malformed.") from exc
        rows.append((digest, relative))
    if {relative for _, relative in rows} != names - {"SHA256SUMS"}:
        raise contract.Stage10V2R2ContractError(
            "Release SHA256SUMS file set differs.")
    for digest, relative in rows:
        if contract.sha256_file(contract.resolve_regular_file(root, relative)) != digest:
            raise contract.Stage10V2R2ContractError(
                "Release SHA256SUMS mismatch: " + relative)
    return manifest


def _expected_readiness_receipt(root: Path, approved_sha: str,
                                stage11_result: Mapping[str, Any],
                                generation_chain: Mapping[str, Any],
                                *, synthetic: bool) -> Mapping[str, Any]:
    validate_stage11_result(stage11_result)
    return {
        "schema_version": contract.RELEASE_READINESS_SCHEMA,
        "contract_id": contract.CONTRACT_ID,
        "run_id": contract.RUN_ID,
        "evidence_mode": contract.EVIDENCE_MODE,
        "approved_freeze_receipt_sha256": approved_sha,
        "release_status": "stage10_release_readiness_verified",
        "completion_decision": "approved_for_status_finalization",
        "release_test_evidence_sha256":
            contract.sha256_file(root / "release_readiness_test_evidence.json"),
        "generation_chain": generation_chain,
        "stage11_negative_audit": {
            "result": {
                "stage10a": stage11_result["stage10a"],
                "stage10_r2": stage11_result["stage10_r2"],
            },
            "result_sha256":
                contract.sha256_file(root / "stage11_negative_audit_result.json"),
            "evidence_sha256":
                contract.sha256_file(root / "stage11_negative_audit_evidence.json"),
            "source_snapshot_sha256": contract.sha256_file(
                root / "stage11_negative_audit_source_snapshot.json"),
        },
        "stage11_positive_migration_authorized": False,
        "real_system_async_performance_verified": False,
        "synthetic_test_only": synthetic,
    }


def _synthetic_generation_chain() -> Mapping[str, Any]:
    return {
        "run_identity_sha256": "0" * 64,
        "verification_sha256": "0" * 64,
        "run_state_sha256": "0" * 64,
        "manifest_sha256": "0" * 64,
        "checksums_sha256": "0" * 64,
        "native_verifier_status": contract.VERIFIED_STATUS,
        "dispatcher_verifier_status": contract.VERIFIED_STATUS,
        "stage9_artifact_sha256_verified_count": 19,
        "stage10a": {"status": "verified", "result_count": 5,
                     "manifest_files": 12},
        "synthetic_test_only": True,
    }


def build_prevalidated_release_readiness(
        *, release_root: Path, approved_freeze_receipt_sha256: str,
        repository_receipt: Path, stage11_result: Mapping[str, Any]) -> Path:
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt)
    validate_stage11_result(stage11_result)
    release_root = Path(release_root).resolve()
    if release_root.exists():
        raise contract.Stage10V2R2ContractError(
            "Release readiness directory already exists.")
    environment = environment_snapshot(())
    release_root.parent.mkdir(parents=True, exist_ok=True)
    release_root.mkdir()
    write_text(release_root / "release_readiness_test_log.txt",
               "synthetic readiness test\nOK\n")
    write_text(release_root / "release_test_source_snapshot.py",
               "# synthetic release source snapshot\n")
    write_text(release_root / "protocol_pending_snapshot.md",
               "release_pending\nreal_system_async_performance_verified=false\n")
    write_text(release_root / "status_pending_snapshot.md",
               "generation_verified\nrelease_pending\n")
    write_json(release_root / "release_readiness_test_evidence.json", {
        "schema_version": contract.RELEASE_TEST_EVIDENCE_SCHEMA,
        "phase": "readiness", "argv": [sys.executable, "synthetic-readiness"],
        "timeout_seconds": contract.CONTROLLED_EXECUTION[
            "release_readiness_test_timeout_seconds"],
        "pre_source_snapshot": {"synthetic": True},
        "post_source_snapshot": {"synthetic": True},
        "log_sha256": contract.sha256_file(
            release_root / "release_readiness_test_log.txt"),
        "test_count": 1, "final_status": "OK", "exit_code": 0,
        "timed_out": False, "environment": environment,
    })
    result_payload = {
        "schema_version": "capd_proactive_stage10_stage11_negative_audit_result_v1_0",
        **stage11_result,
    }
    write_text(release_root / "stage11_negative_audit_log.txt",
               json.dumps(result_payload, sort_keys=True, separators=(",", ":")) + "\n")
    write_json(release_root / "stage11_negative_audit_source_snapshot.json", {
        "schema_version": "capd_proactive_stage10_stage11_source_snapshot_v1_0",
        "pre": {"synthetic": True}, "post": {"synthetic": True},
        "stage11_output_created": False,
    })
    write_json(release_root / "stage11_negative_audit_result.json", result_payload)
    write_json(release_root / "stage11_negative_audit_evidence.json", {
        "schema_version": contract.STAGE11_AUDIT_EVIDENCE_SCHEMA,
        "argv": [sys.executable, "synthetic-stage11-audit"],
        "timeout_seconds": contract.CONTROLLED_EXECUTION[
            "stage11_negative_audit_timeout_seconds"],
        "pre_dependency_snapshot": {"synthetic": True},
        "post_dependency_snapshot": {"synthetic": True},
        "result_sha256": contract.sha256_file(
            release_root / "stage11_negative_audit_result.json"),
        "log_sha256": contract.sha256_file(
            release_root / "stage11_negative_audit_log.txt"),
        "exit_code": 0, "timed_out": False, "environment": environment,
    })
    receipt = _expected_readiness_receipt(
        release_root, approved, stage11_result, _synthetic_generation_chain(),
        synthetic=True)
    write_json(release_root / "release_readiness_receipt.json", receipt)
    _write_release_manifest(release_root, "readiness")
    return release_root


def verify_release_readiness(
        readiness_root: os.PathLike[str] | str, *,
        approved_freeze_receipt_sha256: str,
        repository_receipt: Path | None = None,
        allow_test_evidence: bool = False) -> Mapping[str, Any]:
    root = Path(readiness_root).resolve()
    if not root.is_dir():
        raise contract.Stage10V2R2ContractError(
            "Release readiness directory is missing.")
    if repository_receipt is None:
        repository_receipt = ROOT / contract.FREEZE_RECEIPT_PATH
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt)
    if not allow_test_evidence:
        config = contract.load_json(ROOT / contract.CONFIG_PATH)
        _validate_repository_bindings(config, ROOT)
    _verify_release_manifest(root, "readiness", READINESS_FILES)
    result = contract.load_json(root / "stage11_negative_audit_result.json")
    validate_stage11_result(result)
    expected = _expected_readiness_receipt(
        root, approved, result,
        _synthetic_generation_chain() if allow_test_evidence else
        _production_generation_chain(root.parents[2] / contract.RUN_ID, approved),
        synthetic=allow_test_evidence)
    saved = contract.load_json(root / "release_readiness_receipt.json")
    if saved != expected:
        raise contract.Stage10V2R2ContractError(
            "Release readiness receipt does not independently recompute.")
    return {
        "release_status": saved["release_status"],
        "completion_decision": saved["completion_decision"],
    }


def _expected_final_receipt(root: Path, readiness_root: Path,
                            approved_sha: str, *, synthetic: bool):
    return {
        "schema_version": contract.FINAL_STATUS_EVIDENCE_SCHEMA,
        "contract_id": contract.CONTRACT_ID,
        "run_id": contract.RUN_ID,
        "approved_freeze_receipt_sha256": approved_sha,
        "readiness_receipt_sha256": contract.sha256_file(
            readiness_root / "release_readiness_receipt.json"),
        "readiness_manifest_sha256": contract.sha256_file(
            readiness_root / "manifest.json"),
        "readiness_checksums_sha256": contract.sha256_file(
            readiness_root / "SHA256SUMS"),
        "completion_decision": "approved_for_status_finalization",
        "status": "stage10_final_status_evidence_verified",
        "final_status_test_evidence_sha256": contract.sha256_file(
            root / "final_status_test_evidence.json"),
        "real_system_async_performance_verified": False,
        "synthetic_test_only": synthetic,
    }


def build_prevalidated_final_status(
        *, final_root: Path, readiness_root: Path,
        approved_freeze_receipt_sha256: str,
        repository_receipt: Path) -> Path:
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt)
    verify_release_readiness(
        readiness_root, approved_freeze_receipt_sha256=approved,
        repository_receipt=repository_receipt, allow_test_evidence=True)
    final_root = Path(final_root).resolve()
    if final_root.exists():
        raise contract.Stage10V2R2ContractError(
            "Final-status evidence directory already exists.")
    environment = environment_snapshot(())
    final_root.parent.mkdir(parents=True, exist_ok=True)
    final_root.mkdir()
    write_text(final_root / "final_status_test_log.txt", "synthetic final test\nOK\n")
    write_text(final_root / "release_test_source_snapshot.py",
               "# synthetic release source snapshot\n")
    write_text(final_root / "protocol_final_snapshot.md",
               "completion_decision=approved_for_status_finalization\n")
    write_text(final_root / "status_final_snapshot.md",
               "stage10_final_status_evidence_verified\n")
    write_json(final_root / "final_status_test_evidence.json", {
        "schema_version": contract.RELEASE_TEST_EVIDENCE_SCHEMA,
        "phase": "final_status", "argv": [sys.executable, "synthetic-final"],
        "timeout_seconds": contract.CONTROLLED_EXECUTION[
            "final_status_test_timeout_seconds"],
        "pre_source_snapshot": {"synthetic": True},
        "post_source_snapshot": {"synthetic": True},
        "log_sha256": contract.sha256_file(final_root / "final_status_test_log.txt"),
        "test_count": 1, "final_status": "OK", "exit_code": 0,
        "timed_out": False, "environment": environment,
    })
    write_json(final_root / "final_status_evidence_receipt.json",
               _expected_final_receipt(
                   final_root, Path(readiness_root), approved, synthetic=True))
    _write_release_manifest(final_root, "final_status")
    return final_root


def verify_final_status(
        final_root: os.PathLike[str] | str, *,
        approved_freeze_receipt_sha256: str,
        repository_receipt: Path | None = None,
        allow_test_evidence: bool = False) -> Mapping[str, Any]:
    root = Path(final_root).resolve()
    if not root.is_dir():
        raise contract.Stage10V2R2ContractError(
            "Final-status evidence directory is missing.")
    if repository_receipt is None:
        repository_receipt = ROOT / contract.FREEZE_RECEIPT_PATH
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256, repository_receipt)
    if not allow_test_evidence:
        config = contract.load_json(ROOT / contract.CONFIG_PATH)
        _validate_repository_bindings(config, ROOT)
    _verify_release_manifest(root, "final_status", FINAL_STATUS_FILES)
    readiness = root.parent / "readiness"
    verify_release_readiness(
        readiness, approved_freeze_receipt_sha256=approved,
        repository_receipt=repository_receipt,
        allow_test_evidence=allow_test_evidence)
    expected = _expected_final_receipt(
        root, readiness, approved, synthetic=allow_test_evidence)
    saved = contract.load_json(root / "final_status_evidence_receipt.json")
    if saved != expected:
        raise contract.Stage10V2R2ContractError(
            "Final-status receipt does not independently recompute.")
    return {"status": saved["status"]}


def seal_final_status(
        readiness_root: Path, *, approved_freeze_receipt_sha256: str,
        project_root: Path = ROOT) -> Path:
    project_root = Path(project_root).resolve()
    readiness_root = Path(readiness_root).resolve()
    expected_readiness = (
        project_root / "outputs/capd_proactive_stage10/release_receipts" /
        contract.RUN_ID / "readiness").resolve()
    if readiness_root != expected_readiness:
        raise contract.Stage10V2R2ContractError(
            "Final status requires the unique production readiness receipt.")
    approved = validate_approved_freeze_sha(
        approved_freeze_receipt_sha256,
        project_root / contract.FREEZE_RECEIPT_PATH)
    verify_release_readiness(
        readiness_root, approved_freeze_receipt_sha256=approved)
    config = contract.load_json(project_root / contract.CONFIG_PATH)
    final_root = readiness_root.parent / "final-status"
    if final_root.exists():
        raise contract.Stage10V2R2ContractError(
            "Final-status evidence directory already exists.")
    release_paths = [
        config["release_contract"]["release_test_module"]["path"],
        "docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md",
        "docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md",
    ]
    pre = _snapshot_paths(project_root, release_paths)
    argv = [sys.executable,
            *config["release_contract"]["final_status_test_argv_suffix"]]
    process = run_controlled_process(
        argv, cwd=project_root,
        timeout_seconds=contract.CONTROLLED_EXECUTION[
            "final_status_test_timeout_seconds"],
        monitor_interval_seconds=contract.CONTROLLED_EXECUTION[
            "monitor_check_interval_seconds"],
        termination_grace_seconds=contract.CONTROLLED_EXECUTION[
            "termination_grace_seconds"], dependency_names=())
    post = _snapshot_paths(project_root, release_paths)
    log = process["stdout"] + process["stderr"]
    if pre != post or process["timed_out"] or process["exit_code"] != 0:
        raise contract.Stage10V2R2ContractError(
            "Final-status tests failed, timed out, or changed source.")
    count, identities = _parse_unittest_log(log)
    if count != 1:
        raise contract.Stage10V2R2ContractError(
            "Final-status test count is not exact.")
    final_root.mkdir()
    write_text(final_root / "final_status_test_log.txt", log)
    shutil.copyfile(project_root / release_paths[0],
                    final_root / "release_test_source_snapshot.py")
    shutil.copyfile(project_root / release_paths[1],
                    final_root / "protocol_final_snapshot.md")
    shutil.copyfile(project_root / release_paths[2],
                    final_root / "status_final_snapshot.md")
    write_json(final_root / "final_status_test_evidence.json", {
        "schema_version": contract.RELEASE_TEST_EVIDENCE_SCHEMA,
        "phase": "final_status", "argv": argv,
        "timeout_seconds": process["timeout_seconds"],
        "pre_source_snapshot": pre, "post_source_snapshot": post,
        "log_sha256": contract.sha256_file(
            final_root / "final_status_test_log.txt"),
        "test_count": count, "ordered_verbose_test_ids": identities,
        "final_status": "OK", "exit_code": 0, "timed_out": False,
        "environment": process["environment"],
    })
    write_json(final_root / "final_status_evidence_receipt.json",
               _expected_final_receipt(
                   final_root, readiness_root, approved, synthetic=False))
    _write_release_manifest(final_root, "final_status")
    return final_root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--verify")
    mode.add_argument("--formal-simulation-worker", action="store_true")
    mode.add_argument("--create-release-readiness")
    mode.add_argument("--verify-release-readiness")
    mode.add_argument("--seal-final-status")
    mode.add_argument("--verify-final-status")
    parser.add_argument("--config")
    parser.add_argument("--stage9-run-root")
    parser.add_argument("--output-root")
    parser.add_argument("--run-id")
    parser.add_argument("--approved-freeze-receipt-sha256")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_r2_run(
                args.verify,
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.create_release_readiness:
            target = create_release_readiness(
                Path(args.create_release_readiness),
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(str(target))
            return 0
        if args.verify_release_readiness:
            result = verify_release_readiness(
                args.verify_release_readiness,
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.seal_final_status:
            target = seal_final_status(
                Path(args.seal_final_status),
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(str(target))
            return 0
        if args.verify_final_status:
            result = verify_final_status(
                args.verify_final_status,
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.formal_simulation_worker:
            if args.config is None or args.stage9_run_root is None:
                raise contract.Stage10V2R2ContractError(
                    "Formal worker requires --config and --stage9-run-root.")
            result = formal_simulation_worker(
                config_path=Path(args.config),
                stage9_run_root=Path(args.stage9_run_root),
                approved_freeze_receipt_sha256=
                    args.approved_freeze_receipt_sha256)
            print(json.dumps(result, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False))
            return 0
        required = ("config", "stage9_run_root", "output_root", "run_id",
                    "approved_freeze_receipt_sha256")
        missing = [name for name in required if getattr(args, name) is None]
        if missing:
            raise contract.Stage10V2R2ContractError(
                "Missing run arguments: " + ",".join(missing))
        target = build_run(
            config_path=Path(args.config),
            stage9_run_root=Path(args.stage9_run_root),
            output_root=Path(args.output_root), run_id=args.run_id,
            approved_freeze_receipt_sha256=
                args.approved_freeze_receipt_sha256)
        print(str(target))
        return 0
    except (OSError, ValueError, contract.Stage10V2R2ContractError) as exc:
        print("stage10-v2-r2: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
