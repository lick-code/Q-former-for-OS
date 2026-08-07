#!/usr/bin/env python3
"""Run and independently verify CAPD Stage10 v2 simulations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qmap import proactive_stage10 as engine
from qmap import proactive_stage10_v2 as stage10


EXPECTED_ARTIFACTS = {
    "config.json", "run_identity.json", "stage9_input_receipt.json",
    "timing_provenance.json", "scenario_matrix.json",
    "simulation_results.jsonl", "event_model.md", "parameters.md",
    "test_log.txt", "test_evidence.json", "report.md", "verification.json",
    "run_state.json", "manifest.json", "SHA256SUMS", "README.md",
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
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


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def relative_files(root: Path):
    return sorted((path.relative_to(root).as_posix(), path)
                  for path in root.rglob("*") if path.is_file())


def validate_test_log(path: Path, expected_sha256: str,
                      contract: Mapping[str, Any]) -> Mapping[str, Any]:
    if not path.is_file():
        raise stage10.Stage10V2ContractError("Stage10 v2 test log is missing.")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_sha256):
        raise stage10.Stage10V2ContractError("Stage10 v2 test-log SHA is invalid.")
    actual = stage10.sha256_file(path)
    if actual != expected_sha256:
        raise stage10.Stage10V2ContractError("Stage10 v2 test-log SHA mismatch.")
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    lines = [line.rstrip("\r") for line in text.splitlines()]
    commands = [line[len("COMMAND:"):].strip()
                for line in lines if line.startswith("COMMAND:")]
    if commands != [contract.get("expected_command")]:
        raise stage10.Stage10V2ContractError("Stage10 v2 test command is invalid.")
    matches = re.findall(r"(?m)^Ran\s+(\d+)\s+tests?\b", text)
    if len(matches) != 1:
        raise stage10.Stage10V2ContractError("Test log needs one Ran N tests line.")
    count = int(matches[0])
    if count < contract.get("minimum_test_count", 1):
        raise stage10.Stage10V2ContractError("Stage10 v2 test count is too low.")
    results = [line.strip() for line in lines
               if re.match(r"^test_\S.*\.\.\.\s+ok$", line.strip())]
    if len(results) != count:
        raise stage10.Stage10V2ContractError(
            "Verbose test result count differs from Ran N tests.")
    nonempty = [line.strip() for line in lines if line.strip()]
    if not nonempty or nonempty[-1] != "OK":
        raise stage10.Stage10V2ContractError("Stage10 v2 test log does not end in OK.")
    if any(line == "FAILED" or line == "ERROR" or line.startswith("FAILED (") or
           line.startswith("ERROR (") for line in nonempty):
        raise stage10.Stage10V2ContractError("Stage10 v2 test log contains failure.")
    required_modules = contract.get("required_modules")
    if not isinstance(required_modules, list) or not required_modules:
        raise stage10.Stage10V2ContractError("Required test modules are missing.")
    if any(not any(f"({module}." in line for module in required_modules)
           for line in results):
        raise stage10.Stage10V2ContractError("Test log contains an unknown module.")
    if any(not any(f"({module}." in line for line in results)
           for module in required_modules):
        raise stage10.Stage10V2ContractError("A required test module is absent.")
    return {
        "schema_version": "capd_proactive_stage10_test_evidence_v2_0",
        "sha256": actual, "command": commands[0],
        "module": contract["required_module"],
        "modules": required_modules, "test_count": count,
        "verbose_result_count": len(results), "final_status": "OK",
    }


def manifest_value(root: Path) -> Mapping[str, Any]:
    files = {}
    for relative, path in relative_files(root):
        if relative in ("manifest.json", "SHA256SUMS"):
            continue
        files[relative] = stage10.sha256_file(path)
    return {"schema_version": "capd_proactive_stage10_manifest_v2_0",
            "files": files}


def write_checksums(root: Path) -> None:
    rows = []
    for relative, path in relative_files(root):
        if relative == "SHA256SUMS":
            continue
        rows.append(f"{stage10.sha256_file(path)}  {relative}")
    write_text(root / "SHA256SUMS", "\n".join(rows) + "\n")


def _git_identity(project_root: Path) -> Mapping[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root,
            text=True, capture_output=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_root,
            text=True, capture_output=True, check=True).stdout.strip())
        return {"commit": commit, "dirty_worktree": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": "NOT_AVAILABLE", "dirty_worktree": True}


def _source_hashes(project_root: Path) -> Mapping[str, str]:
    paths = {
        "v2_module": project_root / "qmap/proactive_stage10_v2.py",
        "v2_runner": project_root / "scripts/run_capd_proactive_stage10_v2.py",
        "shared_engine": project_root / "qmap/proactive_stage10.py",
        "v2_tests": project_root / "tests/test_capd_proactive_stage10_v2.py",
    }
    return {name: stage10.sha256_file(path) for name, path in paths.items()}


def _matrix_payload(config: Mapping[str, Any], rows) -> Mapping[str, Any]:
    reference_streams = {}
    for row in rows:
        if (row["comparison_channel"] == "fixed_arrival" and
                row["timing_profile_id"] == stage10.REFERENCE_TIMING_PROFILE):
            reference_streams[row["arrival_profile_id"]] = \
                row["arrival_binding"]["arrival_stream_sha256"]
    return {
        "schema_version": "capd_proactive_stage10_scenario_matrix_v2_0",
        "contract_id": stage10.CONTRACT_ID,
        "comparison_channels": [row["id"] for row in config["comparison_channels"]],
        "reference_timing_profile": config["reference_timing_profile"],
        "scenario_count": len(rows),
        "scenario_ids": [row["scenario_id"] for row in rows],
        "reference_arrival_stream_sha256": dict(sorted(reference_streams.items())),
        "scenarios": list(rows),
    }


def expected_run_identity(run_root: Path, config: Mapping[str, Any], audit,
                          project_root: Path) -> Mapping[str, Any]:
    value = {
        "schema_version": "capd_proactive_stage10_run_identity_v2_0",
        "contract_id": stage10.CONTRACT_ID,
        "run_id": stage10.RUN_ID,
        "evidence_mode": stage10.EVIDENCE_MODE,
        "config_sha256": stage10.sha256_file(run_root / "config.json"),
        "result_schema_sha256": config["result_schema_sha256"],
        "approved_design_sha256": config["approved_design"]["sha256"],
        "byte_recovery_audit_sha256": config["byte_recovery_audit"]["sha256"],
        "stage9_input_receipt_sha256":
            stage10.sha256_file(run_root / "stage9_input_receipt.json"),
        "stage9_config_sha256": audit.binding.config_sha256,
        "stage9_verification_sha256": audit.binding.verification_sha256,
        "stage9_checkpoint_sha256": audit.binding.checkpoint_sha256,
        "stage9_latency_summary_sha256": audit.binding.latency_summary_sha256,
        "stage9_run_identity_sha256": audit.binding.run_identity_sha256,
        "timing_provenance_sha256":
            stage10.sha256_file(run_root / "timing_provenance.json"),
        "scenario_matrix_sha256":
            stage10.sha256_file(run_root / "scenario_matrix.json"),
        "test_evidence_sha256":
            stage10.sha256_file(run_root / "test_evidence.json"),
        "conversion_rule": stage10.CONVERSION_RULE,
        "source_sha256": _source_hashes(project_root),
        "git": _git_identity(project_root),
    }
    value["run_identity_sha256"] = stage10.fingerprint_value(value)
    return value


def expected_verification(results) -> Mapping[str, Any]:
    return {
        "schema_version": "capd_proactive_stage10_verification_v2_0",
        "contract_id": stage10.CONTRACT_ID,
        "evidence_mode": stage10.EVIDENCE_MODE,
        "status": stage10.VERIFIED_STATUS,
        "stage9_input_gate": "satisfied",
        "simulation_executed": True,
        "artifacts_independently_recomputed": True,
        "result_count": len(results),
        "scenario_ids": [line["scenario_id"] for line in results],
        "real_system_async_performance_verified": False,
    }


def expected_run_state() -> Mapping[str, Any]:
    return {
        "schema_version": "capd_proactive_stage10_run_state_v2_0",
        "contract_id": stage10.CONTRACT_ID,
        "run_id": stage10.RUN_ID,
        "evidence_mode": stage10.EVIDENCE_MODE,
        "status": stage10.VERIFIED_STATUS,
        "failure": None,
        "stage9_input_gate_passed": True,
        "simulation_executed": True,
        "artifacts_independently_verified": True,
        "real_system_async_performance_verified": False,
    }


def _write_payloads(run_root: Path, config: Mapping[str, Any], audit,
                    provenance: Mapping[str, Any], matrix, results,
                    test_log_input: Path, test_evidence: Mapping[str, Any],
                    project_root: Path) -> None:
    write_json(run_root / "config.json", config)
    write_json(run_root / "stage9_input_receipt.json", audit.receipt)
    write_json(run_root / "timing_provenance.json", provenance)
    matrix_payload = _matrix_payload(config, matrix)
    write_json(run_root / "scenario_matrix.json", matrix_payload)
    write_text(run_root / "simulation_results.jsonl", "".join(
        json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for line in results))
    write_text(run_root / "event_model.md",
               "# Stage10 v2 Event Model\n\n"
               "Deterministic integer-nanosecond discrete events reuse the tested "
               "Stage10A priority, reservation, capacity, LRU-tail, MRU-admission, "
               "FIFO-blocking, and exhaustion-integral semantics.\n")
    write_text(run_root / "parameters.md",
               "# Stage10 v2 Parameters\n\n"
               "Inference timing is derived from Stage9 r3. Migration timing is a "
               "predeclared simulator scenario, not an NVM measurement. fixed_arrival "
               "supports simulator-only timing sensitivity; capacity_normalized does not.\n")
    shutil.copyfile(test_log_input, run_root / "test_log.txt")
    write_json(run_root / "test_evidence.json", test_evidence)
    write_text(run_root / "report.md",
               "# Stage10 v2 Deterministic Simulation\n\n"
               f"Scenario rows: {len(results)}\n\n"
               "This evidence is deterministic simulation only. Real NVM, kernel "
               "concurrency, and foreground end-to-end performance remain unverified.\n")
    write_text(run_root / "README.md",
               "CAPD Stage10 v2 deterministic async-simulation evidence. "
               "It is not real-system asynchronous-performance evidence.\n")
    write_json(run_root / "run_identity.json",
               expected_run_identity(run_root, config, audit, project_root))
    write_json(run_root / "verification.json", expected_verification(results))
    write_json(run_root / "run_state.json", expected_run_state())
    write_json(run_root / "manifest.json", manifest_value(run_root))
    write_checksums(run_root)


def _execute(config: Mapping[str, Any], binding: stage10.TrustedStage9Binding,
             stage9_run_root: Path, output_root: Path, test_log_input: Path,
             test_log_sha256: str, project_root: Path,
             allow_test_parameters: bool) -> Path:
    audit = stage10.audit_stage9_run(stage9_run_root, binding)
    test_evidence = validate_test_log(
        test_log_input, test_log_sha256, config["test_evidence"])
    target = output_root.resolve() / stage10.RUN_ID
    if target.exists():
        raise stage10.Stage10V2ContractError("Stage10 v2 run ID already exists.")
    provenance = stage10.derive_timing_provenance(audit)
    streams = stage10.build_arrival_streams(config, provenance)
    matrix = stage10.expand_scenario_matrix(config, provenance, streams)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        results = []
        for scenario in matrix:
            key = (scenario["comparison_channel"], scenario["timing_profile_id"],
                   scenario["arrival_profile_id"])
            results.append(stage10.simulate_scenario(config, scenario, streams[key]))
        _write_payloads(target, config, audit, provenance, matrix, results,
                        test_log_input, test_evidence, project_root)
        verify_v2_run(target, project_root=project_root, binding=binding,
                      allow_test_parameters=allow_test_parameters)
    except Exception as exc:
        write_json(target / "run_state.json", {
            "schema_version": "capd_proactive_stage10_run_state_v2_0",
            "contract_id": stage10.CONTRACT_ID, "run_id": stage10.RUN_ID,
            "evidence_mode": stage10.EVIDENCE_MODE,
            "status": stage10.FAILURE_STATUS,
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "real_system_async_performance_verified": False,
        })
        raise
    return target


def build_run(*, config_path: Path, stage9_run_root: Path, output_root: Path,
              run_id: str, test_log_input: Path, test_log_sha256: str,
              project_root: Path = ROOT) -> Path:
    """Strict production entrypoint. All preflight checks precede mkdir."""
    root = Path(project_root).resolve()
    expected_config = root / "configs/finals/capd_proactive_stage10_v2.json"
    if Path(config_path).resolve() != expected_config.resolve():
        raise stage10.Stage10V2ContractError("Only the repository v2 config is allowed.")
    config = stage10.load_repository_config(root)
    if run_id != stage10.RUN_ID:
        raise stage10.Stage10V2ContractError("Stage10 v2 run id override is forbidden.")
    expected_output = (root / config["output_root"]).resolve()
    if Path(output_root).resolve() != expected_output:
        raise stage10.Stage10V2ContractError("Stage10 v2 output root override is forbidden.")
    binding = stage10.production_stage9_binding(config, root)
    expected_stage9 = binding.output_root / binding.run_id
    if Path(stage9_run_root).resolve() != expected_stage9.resolve():
        raise stage10.Stage10V2ContractError("Only the approved Stage9 r3 input is allowed.")
    # Audit and test-log validation are repeated inside _execute, but doing them
    # here guarantees all production preflight failures happen before mkdir.
    stage10.audit_stage9_run(stage9_run_root, binding)
    validate_test_log(Path(test_log_input), test_log_sha256, config["test_evidence"])
    if (expected_output / stage10.RUN_ID).exists():
        raise stage10.Stage10V2ContractError("Stage10 v2 run ID already exists.")
    return _execute(config, binding, Path(stage9_run_root), expected_output,
                    Path(test_log_input), test_log_sha256, root, False)


def build_prevalidated_test_run(*, config: Mapping[str, Any],
                                binding: stage10.TrustedStage9Binding,
                                stage9_run_root: Path, output_root: Path,
                                test_log_input: Path, test_log_sha256: str,
                                project_root: Path) -> Path:
    """Explicit synthetic-only entrypoint used by unit tests under temp roots."""
    if config.get("contract_id") != stage10.CONTRACT_ID or \
            config.get("scenario_count") != 60 or \
            config.get("evidence_mode") != stage10.EVIDENCE_MODE:
        raise stage10.Stage10V2ContractError("Synthetic v2 test contract is invalid.")
    project_root = Path(project_root).resolve()
    test_root = binding.project_root.resolve()
    target_output = Path(output_root).resolve()
    production_output = (project_root / "outputs/capd_proactive_stage10").resolve()
    if (test_root == project_root or target_output == production_output or
            not stage10._inside(test_root, target_output)):
        raise stage10.Stage10V2ContractError(
            "Synthetic runner is restricted to its external temporary project root.")
    return _execute(config, binding, Path(stage9_run_root), Path(output_root),
                    Path(test_log_input), test_log_sha256,
                    project_root, True)


def _validate_config_for_verify(config: Mapping[str, Any], project_root: Path,
                                allow_test_parameters: bool) -> None:
    if not allow_test_parameters:
        stage10.validate_config(config, project_root)
        return
    canonical = load_json(project_root / "configs/finals/capd_proactive_stage10_v2.json")
    candidate = json.loads(json.dumps(config))
    candidate["simulator_parameters"]["simulation_horizon_ns"] = \
        canonical["simulator_parameters"]["simulation_horizon_ns"]
    candidate_bursts = candidate["arrival_profiles"][-1]["bursts"]
    canonical_bursts = canonical["arrival_profiles"][-1]["bursts"]
    if len(candidate_bursts) != len(canonical_bursts):
        raise stage10.Stage10V2ContractError("Synthetic burst count changed.")
    for candidate_burst, canonical_burst in zip(candidate_bursts, canonical_bursts):
        candidate_burst["start_ns"] = canonical_burst["start_ns"]
        candidate_burst["duration_ns"] = canonical_burst["duration_ns"]
    stage10.validate_config(candidate, project_root)
    params = config.get("simulator_parameters", {})
    horizon = params.get("simulation_horizon_ns")
    if not isinstance(horizon, int) or horizon <= 0:
        raise stage10.Stage10V2ContractError("Synthetic horizon is invalid.")
    for burst in config["arrival_profiles"][-1]["bursts"]:
        if burst["start_ns"] < 0 or burst["duration_ns"] <= 0 or \
                burst["start_ns"] + burst["duration_ns"] > horizon:
            raise stage10.Stage10V2ContractError("Synthetic burst is outside horizon.")


def _verify_manifest_and_checksums(root: Path) -> None:
    names = {relative for relative, _ in relative_files(root)}
    if names != EXPECTED_ARTIFACTS:
        raise stage10.Stage10V2ContractError("Stage10 v2 artifact set is not exact.")
    manifest = load_json(root / "manifest.json")
    if manifest.get("schema_version") != "capd_proactive_stage10_manifest_v2_0":
        raise stage10.Stage10V2ContractError("Stage10 v2 manifest schema is invalid.")
    payload_names = names - {"manifest.json", "SHA256SUMS"}
    if set(manifest.get("files", {})) != payload_names:
        raise stage10.Stage10V2ContractError("Stage10 v2 manifest file set differs.")
    for relative, digest in manifest["files"].items():
        path = root / relative
        if not path.is_file() or not stage10._inside(root, path) or \
                stage10.sha256_file(path) != digest:
            raise stage10.Stage10V2ContractError("Manifest mismatch: " + relative)
    checksum_rows = []
    for raw in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if raw:
            try:
                digest, relative = raw.split("  ", 1)
            except ValueError as exc:
                raise stage10.Stage10V2ContractError("Malformed SHA256SUMS.") from exc
            checksum_rows.append((digest, relative))
    if {relative for _, relative in checksum_rows} != names - {"SHA256SUMS"}:
        raise stage10.Stage10V2ContractError("SHA256SUMS file set differs.")
    for digest, relative in checksum_rows:
        path = root / relative
        if relative == "SHA256SUMS" or not path.is_file() or \
                not stage10._inside(root, path) or stage10.sha256_file(path) != digest:
            raise stage10.Stage10V2ContractError("SHA256SUMS mismatch: " + relative)


def verify_v2_run(run_root: os.PathLike[str] | str, *, project_root: Path = ROOT,
                  binding: stage10.TrustedStage9Binding | None = None,
                  allow_test_parameters: bool = False) -> Mapping[str, Any]:
    root = Path(run_root).resolve()
    if not root.is_dir() or root.name != stage10.RUN_ID:
        raise stage10.Stage10V2ContractError("Stage10 v2 run directory is invalid.")
    _verify_manifest_and_checksums(root)
    config = load_json(root / "config.json")
    if config.get("contract_id") != stage10.CONTRACT_ID:
        raise stage10.Stage10V2ContractError("Stage10 v2 verifier rejects this contract.")
    project_root = Path(project_root).resolve()
    _validate_config_for_verify(config, project_root, allow_test_parameters)
    if binding is None:
        binding = stage10.production_stage9_binding(config, project_root)
    audit = stage10.audit_stage9_run(binding.output_root / binding.run_id, binding)
    if load_json(root / "stage9_input_receipt.json") != audit.receipt:
        raise stage10.Stage10V2ContractError("Saved Stage9 receipt does not recompute.")
    provenance = stage10.derive_timing_provenance(audit)
    if load_json(root / "timing_provenance.json") != provenance:
        raise stage10.Stage10V2ContractError("Timing provenance does not recompute.")
    streams = stage10.build_arrival_streams(config, provenance)
    matrix = stage10.expand_scenario_matrix(config, provenance, streams)
    if load_json(root / "scenario_matrix.json") != _matrix_payload(config, matrix):
        raise stage10.Stage10V2ContractError("Scenario matrix does not recompute.")
    schema_path = project_root / config["result_schema"]
    if stage10.sha256_file(schema_path) != config["result_schema_sha256"]:
        raise stage10.Stage10V2ContractError("Result-schema SHA binding mismatch.")
    schema = load_json(schema_path)
    actual = [json.loads(raw) for raw in
              (root / "simulation_results.jsonl").read_text(encoding="utf-8").splitlines()
              if raw]
    expected = []
    for scenario in matrix:
        key = (scenario["comparison_channel"], scenario["timing_profile_id"],
               scenario["arrival_profile_id"])
        line = stage10.simulate_scenario(config, scenario, streams[key])
        stage10.validate_result_line(line, schema)
        expected.append(line)
    if actual != expected:
        raise stage10.Stage10V2ContractError("Simulation results do not recompute.")
    for line in actual:
        stage10.validate_result_line(line, schema)
    evidence_saved = load_json(root / "test_evidence.json")
    evidence = validate_test_log(root / "test_log.txt", evidence_saved.get("sha256"),
                                 config["test_evidence"])
    if evidence != evidence_saved:
        raise stage10.Stage10V2ContractError("Test evidence does not recompute.")
    if load_json(root / "run_identity.json") != expected_run_identity(
            root, config, audit, project_root):
        raise stage10.Stage10V2ContractError(
            "Run identity does not match the complete independently constructed object.")
    if load_json(root / "verification.json") != expected_verification(expected):
        raise stage10.Stage10V2ContractError(
            "Verification metadata does not match the complete expected object.")
    if load_json(root / "run_state.json") != expected_run_state():
        raise stage10.Stage10V2ContractError(
            "Run state does not match the complete expected object.")
    return {"status": stage10.VERIFIED_STATUS, "result_count": len(actual),
            "manifest_files": len(load_json(root / "manifest.json")["files"]),
            "real_system_async_performance_verified": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--stage9-run-root")
    parser.add_argument("--output-root")
    parser.add_argument("--run-id")
    parser.add_argument("--test-log-input")
    parser.add_argument("--test-log-sha256")
    parser.add_argument("--verify")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            print(json.dumps(verify_v2_run(args.verify), sort_keys=True))
            return 0
        required = ("config", "stage9_run_root", "output_root", "run_id",
                    "test_log_input", "test_log_sha256")
        missing = [name for name in required if getattr(args, name) is None]
        if missing:
            raise stage10.Stage10V2ContractError(
                "Missing arguments: " + ",".join(missing))
        target = build_run(
            config_path=Path(args.config),
            stage9_run_root=Path(args.stage9_run_root),
            output_root=Path(args.output_root), run_id=args.run_id,
            test_log_input=Path(args.test_log_input),
            test_log_sha256=args.test_log_sha256, project_root=ROOT)
        print(str(target))
        return 0
    except (OSError, ValueError, stage10.Stage10V2ContractError) as exc:
        print("stage10-v2: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
