#!/usr/bin/env python3
"""Run and verify the CAPD Stage10A deterministic fixture simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qmap import proactive_stage10 as stage10


def write_json(path: Path, value) -> None:
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


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _relative_files(root: Path):
    return sorted((path.relative_to(root).as_posix(), path)
                  for path in root.rglob("*") if path.is_file())


def _manifest(root: Path):
    files = {}
    for relative, path in _relative_files(root):
        if relative in ("manifest.json", "SHA256SUMS"):
            continue
        files[relative] = stage10.sha256_file(str(path))
    return {"schema_version": "capd_proactive_stage10_manifest_v1_0",
            "files": files}


def _write_checksums(root: Path):
    rows = []
    for relative, path in _relative_files(root):
        if relative == "SHA256SUMS":
            continue
        rows.append(f"{stage10.sha256_file(str(path))}  {relative}")
    write_text(root / "SHA256SUMS", "\n".join(rows) + "\n")


def _scenario_rows(config):
    for row in config["uniform_scenarios"]:
        yield row["scenario_id"], {
            "kind": "uniform", "load_ratio": row["load_ratio"]}
    for row in config["burst_scenarios"]:
        yield row["scenario_id"], {
            "kind": "burst", "base_load_ratio": row["base_load_ratio"],
            "bursts": row["bursts"]}


def _result_line(scenario_id, model, result):
    derived = dict(result.derived)
    derived["arrival_model"] = model["kind"]
    if model["kind"] == "uniform":
        derived["load_ratio"] = model["load_ratio"]
    else:
        derived["base_load_ratio"] = model["base_load_ratio"]
        derived["bursts"] = model["bursts"]
    return {
        "scenario_id": scenario_id,
        "mode": "fixture",
        "observed": dict(result.metrics),
        "derived": derived,
        "interpretation": dict(result.interpretation),
    }


def _verify_metric_line(line):
    required_observed = {
        "emergency_fallback_count", "fallback_rate",
        "foreground_blocking_time_total", "foreground_blocking_time_mean",
        "foreground_blocking_time_p95", "blocking_sample_count",
        "minimum_free_frames", "free_frame_exhaustion_duration",
        "background_queue_length_mean", "background_queue_length_max",
        "background_queue_length_p95", "background_utilization",
        "page_enter_dram_count", "demotion_finish_count",
        "effective_demotion_rate", "unfinished_blocked_request_count",
    }
    if not required_observed <= set(line.get("observed", {})):
        raise stage10.Stage10ContractError("Result observed fields are incomplete.")
    if line.get("mode") != "fixture":
        raise stage10.Stage10ContractError("Fixture result mode is invalid.")
    interpretation = line.get("interpretation", {})
    if interpretation.get("real_linux_measurement_claimed") is not False:
        raise stage10.Stage10ContractError("Fixture claims Linux measurement.")
    if interpretation.get("kernel_behavior_claimed") is not False:
        raise stage10.Stage10ContractError("Fixture claims kernel behavior.")


def verify_run(run_root: str):
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise stage10.Stage10ContractError("Stage10 run directory is missing.")
    config = load_json(root / "config.json")
    stage10.validate_config(config)
    schema_path = (ROOT / config["result_schema"]).resolve()
    if stage10.sha256_file(str(schema_path)) != config["result_schema_sha256"]:
        raise stage10.Stage10ContractError("Result-schema SHA256 binding mismatch.")
    manifest = load_json(root / "manifest.json")
    if manifest.get("schema_version") != "capd_proactive_stage10_manifest_v1_0":
        raise stage10.Stage10ContractError("Manifest schema is invalid.")
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise stage10.Stage10ContractError("Manifest files must be an object.")
    if set(manifest.get("files", {})) & {"manifest.json", "SHA256SUMS"}:
        raise stage10.Stage10ContractError("Manifest recursively hashes itself.")
    payload_files = {
        relative for relative, _ in _relative_files(root)
        if relative not in ("manifest.json", "SHA256SUMS")
    }
    if set(manifest_files) != payload_files:
        raise stage10.Stage10ContractError(
            "Manifest file set does not match the run directory.")
    for relative, digest in manifest_files.items():
        candidate = (root / relative).resolve()
        try:
            inside = os.path.commonpath((str(root), str(candidate))) == str(root)
        except ValueError:
            inside = False
        if not inside:
            raise stage10.Stage10ContractError("Manifest path escapes run root.")
        path = root / relative
        if not path.is_file() or stage10.sha256_file(str(path)) != digest:
            raise stage10.Stage10ContractError("Manifest hash mismatch: " + relative)
    checksum_lines = []
    with (root / "SHA256SUMS").open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                digest, relative = raw.rstrip("\r\n").split("  ", 1)
                checksum_lines.append((digest, relative))
    checksum_names = {relative for _, relative in checksum_lines}
    if checksum_names != payload_files | {"manifest.json"}:
        raise stage10.Stage10ContractError(
            "SHA256SUMS file set does not match the run directory.")
    for digest, relative in checksum_lines:
        candidate = (root / relative).resolve()
        try:
            inside = os.path.commonpath((str(root), str(candidate))) == str(root)
        except ValueError:
            inside = False
        if not inside:
            raise stage10.Stage10ContractError("SHA256SUMS path escapes run root.")
        path = root / relative
        if relative == "SHA256SUMS" or not path.is_file():
            raise stage10.Stage10ContractError("SHA256SUMS entry is invalid.")
        if stage10.sha256_file(str(path)) != digest:
            raise stage10.Stage10ContractError("SHA256SUMS mismatch: " + relative)
    results = []
    with (root / "fixture_results.jsonl").open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                line = json.loads(raw)
                _verify_metric_line(line)
                results.append(line)
    if len(results) != 5:
        raise stage10.Stage10ContractError("Fixture scenario count is not five.")
    expected_lines = []
    params = stage10.SimulatorConfig.from_mapping(config["fixture_parameters"])
    for scenario_id, model in _scenario_rows(config):
        result = stage10.run_simulation(params, stage10.generate_arrivals(params, model))
        expected_lines.append(_result_line(scenario_id, model, result))
    if results != expected_lines:
        raise stage10.Stage10ContractError(
            "Fixture results do not reproduce deterministic simulation metrics.")
    evidence = stage10.validate_test_log(
        str(root / "test_log.txt"), stage10.sha256_file(str(root / "test_log.txt")),
        config["test_evidence"])
    if load_json(root / "test_evidence.json") != evidence:
        raise stage10.Stage10ContractError("Test evidence does not match test log.")
    verification = load_json(root / "verification.json")
    if verification.get("result_count") != len(results):
        raise stage10.Stage10ContractError("Verification result count mismatch.")
    if verification.get("scenario_ids") != [line["scenario_id"] for line in expected_lines]:
        raise stage10.Stage10ContractError("Verification scenario IDs are invalid.")
    if verification.get("result_schema_sha256") != config["result_schema_sha256"]:
        raise stage10.Stage10ContractError("Verification schema binding mismatch.")
    gate = load_json(root / "formal_gate.json")
    if (gate.get("formal_authorized") is not False or
            gate.get("status") != "stage10_formal_blocked_by_stage9"):
        raise stage10.Stage10ContractError("Formal gate state is invalid.")
    state = load_json(root / "run_state.json")
    if (state.get("status") != "stage10_simulator_tests_passed" or
            state.get("stage10_simulator_implemented") is not True or
            state.get("stage10_simulator_tests_passed") is not True or
            state.get("stage10_formal_blocked_by_stage9") is not True or
            state.get("stage10_formally_verified") is not False):
        raise stage10.Stage10ContractError("Formal verification cannot be claimed.")
    return {"status": "verified", "result_count": len(results),
            "manifest_files": len(manifest["files"])}


def _build_run(config, mode, output_root, run_id, test_log_input,
               test_log_sha256, stage9_run_root):
    config_path = Path(config).resolve()
    repository_config = load_json(config_path)
    stage10.validate_config(repository_config)
    schema_path = (ROOT / repository_config["result_schema"]).resolve()
    if stage10.sha256_file(str(schema_path)) != repository_config["result_schema_sha256"]:
        raise stage10.Stage10ContractError("Result-schema SHA256 binding mismatch.")
    gate_config = repository_config["formal_gate"]
    if mode == "fixture":
        historical = ROOT / "outputs" / "capd_proactive_stage9" / "stage9-overhead-r1"
        receipt = stage10.audit_stage9_run(str(ROOT), str(historical), gate_config)
        gate = stage10.check_formal_stage9_gate(receipt, gate_config)
    else:
        if not stage9_run_root:
            raise stage10.Stage10ContractError("Formal mode requires --stage9-run-root.")
        receipt = stage10.audit_stage9_run(str(ROOT), stage9_run_root, gate_config)
        gate = stage10.check_formal_stage9_gate(receipt, gate_config)
        if not gate["formal_authorized"]:
            raise stage10.Stage10ContractError("Stage9 gate blocked formal Stage10: " +
                                                "; ".join(gate["reasons"]))
    if not test_log_input or not test_log_sha256:
        raise stage10.Stage10ContractError("Test-log input and SHA256 are required.")
    evidence = stage10.validate_test_log(
        test_log_input, test_log_sha256, repository_config["test_evidence"])
    output_root = Path(output_root).resolve()
    run_root = output_root / run_id
    if run_root.exists():
        raise stage10.Stage10ContractError("Stage10 run ID already exists.")
    run_root.mkdir(parents=True)
    try:
        write_json(run_root / "config.json", repository_config)
        write_json(run_root / "stage9_compatibility_receipt.json", receipt)
        write_json(run_root / "formal_gate.json", gate)
        shutil.copyfile(test_log_input, run_root / "test_log.txt")
        write_json(run_root / "test_evidence.json", evidence)
        params = stage10.SimulatorConfig.from_mapping(repository_config["fixture_parameters"])
        lines = []
        for scenario_id, model in _scenario_rows(repository_config):
            arrivals = stage10.generate_arrivals(params, model)
            result = stage10.run_simulation(params, arrivals)
            lines.append(_result_line(scenario_id, model, result))
        write_text(run_root / "fixture_results.jsonl",
                   "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n"
                           for line in lines))
        write_text(run_root / "event_model.md",
                   "# Stage10A Event Model\n\n"
                   "Integer nanoseconds; heap key `(timestamp_ns,event_priority,event_id)`; "
                   "demotion_finish, capd_inference_finish, capd_round_start, "
                   "emergency_fallback, page_enter_dram.\n")
        write_text(run_root / "parameters.md",
                   "# Stage10A Parameters\n\n"
                   "mu_demote uses b_t_reference; actual b_t is recorded per round. "
                   "New and unblocked pages enter the MRU head. "
                   "free_frame_exhaustion_duration integrates F_t=0 over "
                   "[0, simulation_horizon].\n")
        write_text(run_root / "README.md",
                   "Stage10A fixture candidate-ready; formal verification is blocked by Stage9.\n")
        write_text(run_root / "report.md", stage10.render_report(lines[0]["observed"]))
        write_json(run_root / "verification.json", {
            "schema_version": "capd_proactive_stage10_verification_v1_0",
            "result_count": len(lines),
            "scenario_ids": [line["scenario_id"] for line in lines],
            "mode_values": sorted({line["mode"] for line in lines}),
            "result_schema_sha256": repository_config["result_schema_sha256"],
        })
        write_json(run_root / "run_state.json", {
            "schema_version": "capd_proactive_stage10_run_state_v1_0",
            "status": "stage10_simulator_tests_passed",
            "stage10_simulator_implemented": True,
            "stage10_simulator_tests_passed": True,
            "stage10_formal_blocked_by_stage9": not gate["formal_authorized"],
            "stage10_formally_verified": False,
        })
        write_json(run_root / "manifest.json", _manifest(run_root))
        _write_checksums(run_root)
        verify_run(str(run_root))
    except Exception:
        shutil.rmtree(run_root)
        raise
    return run_root


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--mode", choices=("fixture", "formal"))
    parser.add_argument("--output-root")
    parser.add_argument("--run-id")
    parser.add_argument("--test-log-input")
    parser.add_argument("--test-log-sha256")
    parser.add_argument("--stage9-run-root")
    parser.add_argument("--verify")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_run(args.verify)
            print(json.dumps(result, sort_keys=True))
            return 0
        missing = [name for name in ("config", "mode", "output_root", "run_id")
                   if getattr(args, name) is None]
        if missing:
            raise stage10.Stage10ContractError("Missing arguments: " + ",".join(missing))
        run_root = _build_run(args.config, args.mode, args.output_root, args.run_id,
                              args.test_log_input, args.test_log_sha256,
                              args.stage9_run_root)
        print(str(run_root))
        return 0
    except (OSError, ValueError, stage10.Stage10ContractError) as exc:
        print(f"stage10: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
