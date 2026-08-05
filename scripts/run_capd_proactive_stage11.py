#!/usr/bin/env python3
"""Stage11A three-lane runner and fail-closed verifier.

The runner only reads upstream evidence.  Every output is written below the
Stage11A output root and carries its own provenance envelope.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qmap import proactive_stage11 as contract

CONFIG_DEFAULT = ROOT / "configs" / "finals" / "capd_proactive_stage11a.json"
SCHEMA_DEFAULT = ROOT / "configs" / "finals" / "capd_proactive_stage11a_result_schema.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "capd_proactive_stage11"
PROTECTED = (
    ROOT / "outputs" / "capd_proactive_stage8",
    ROOT / "outputs" / "capd_proactive_stage9",
    ROOT / "outputs" / "capd_proactive_stage10",
)

ROW_FIELDS = list(contract.load_json(SCHEMA_DEFAULT)["required_row_fields"])


def sha256_file(path: Path) -> str:
    return contract.fingerprint_file(path)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def relative_files(root: Path) -> list[tuple[str, Path]]:
    return sorted((p.relative_to(root).as_posix(), p)
                  for p in root.rglob("*") if p.is_file())


def build_manifest(root: Path) -> Dict[str, Any]:
    return {
        "schema_version": "capd_proactive_stage11a_manifest_v1_0",
        "files": {relative: sha256_file(path)
                  for relative, path in relative_files(root)
                  if relative not in ("stage11a_manifest.json", "SHA256SUMS")},
    }


def write_checksums(root: Path) -> None:
    lines = []
    for relative, path in relative_files(root):
        if relative == "SHA256SUMS":
            continue
        lines.append(f"{sha256_file(path)}  {relative}")
    atomic_text(root / "SHA256SUMS", "\n".join(lines) + "\n")


def _inside(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def verify_manifest_and_checksums(root: Path) -> None:
    manifest = contract.load_json(root / "stage11a_manifest.json")
    if manifest.get("schema_version") != "capd_proactive_stage11a_manifest_v1_0":
        raise contract.Stage11ContractError("Stage11 manifest schema mismatch.")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) & {"stage11a_manifest.json", "SHA256SUMS"}:
        raise contract.Stage11ContractError("Stage11 manifest recursively hashes itself.")
    payload = {relative for relative, _ in relative_files(root)
               if relative not in ("stage11a_manifest.json", "SHA256SUMS")}
    if set(files) != payload:
        raise contract.Stage11ContractError("Stage11 manifest file set mismatch.")
    for relative, digest in files.items():
        path = (root / relative).resolve()
        if not _inside(root.resolve(), path) or not path.is_file() or sha256_file(path) != digest:
            raise contract.Stage11ContractError("Stage11 manifest hash mismatch: " + relative)
    checksum_lines = []
    with (root / "SHA256SUMS").open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                parts = raw.rstrip("\r\n").split("  ", 1)
                if len(parts) != 2:
                    raise contract.Stage11ContractError("Malformed SHA256SUMS line.")
                checksum_lines.append(tuple(parts))
    if len({name for _, name in checksum_lines}) != len(checksum_lines):
        raise contract.Stage11ContractError("Duplicate SHA256SUMS entry.")
    if {name for _, name in checksum_lines} != payload | {"stage11a_manifest.json"}:
        raise contract.Stage11ContractError("Stage11 SHA256SUMS file set mismatch.")
    for digest, relative in checksum_lines:
        path = (root / relative).resolve()
        if relative == "SHA256SUMS" or not _inside(root.resolve(), path) or not path.is_file():
            raise contract.Stage11ContractError("Invalid SHA256SUMS path.")
        if sha256_file(path) != digest:
            raise contract.Stage11ContractError("Stage11 SHA256SUMS mismatch: " + relative)


def code_version() -> Dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = None
    try:
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                             text=True, stderr=subprocess.DEVNULL).strip())
    except Exception:
        dirty = True
    return {
        "git_commit_sha": commit,
        "worktree_dirty": dirty,
        "runner_sha256": sha256_file(Path(__file__)),
        "contract_module_sha256": sha256_file(ROOT / "qmap" / "proactive_stage11.py"),
        "config_schema_sha256": sha256_file(SCHEMA_DEFAULT),
    }


def resolve_path(value: str | None, base: Path = ROOT) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def validate_preflight(config_path: Path, output_root: Path, run_id: str,
                       stage9_override: str | None = None,
                       stage10_override: str | None = None) -> tuple[Mapping[str, Any], Path, Path]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", run_id):
        raise contract.Stage11ContractError("Invalid run_id.")
    config = contract.load_json(config_path)
    if stage9_override is not None or stage10_override is not None:
        config = dict(config)
        gates = dict(config.get("external_gates", {}))
        if stage9_override is not None:
            gates["stage9_run_root"] = stage9_override
        if stage10_override is not None:
            gates["stage10_run_root"] = stage10_override
        config["external_gates"] = gates
    contract.validate_config(config)
    schema_path = ROOT / "configs" / "finals" / "capd_proactive_stage11a_result_schema.json"
    if not schema_path.is_file():
        raise contract.Stage11ContractError("Stage11 result schema is missing.")
    stage8_root = resolve_path(config["stage8_authority_path"])
    if stage8_root is None or not stage8_root.is_dir():
        raise contract.Stage11ContractError("Stage8 authority path is missing.")
    # This is a read-only preflight; loading also validates every job/result SHA.
    contract.load_stage8_rows(stage8_root)
    output_root = output_root.resolve()
    for protected in PROTECTED:
        if _inside(protected.resolve(), output_root) or _inside(output_root, protected.resolve()):
            raise contract.Stage11ContractError("Output path overlaps protected evidence tree.")
    run_root = (output_root / run_id).resolve()
    if run_root.exists():
        raise contract.Stage11ContractError("run_id already exists; refusing overwrite.")
    return config, stage8_root, run_root


def base_row(run_id: str, row_id: str, lane: str, status: str, envelope: Mapping[str, Any], **values: Any) -> Dict[str, Any]:
    row = {field: None for field in ROW_FIELDS}
    row.update({
        "run_id": run_id, "row_id": row_id, "source_job_id": None,
        "source_result_sha256": None, "source_semantic_result_sha256": None,
        "lane": lane, "evidence_status": status, "evidence_mode": None,
        "parameter_family": None, "grid_cell_id": None,
        "frozen_grid_sha256": envelope.get("frozen_grid_sha256"),
        "policy_or_ablation": None, "label_weights": envelope.get("label_weights"),
        "input_artifact_path": envelope.get("stage8_artifact_path"),
        "input_artifact_sha256": envelope.get("stage8_artifact_sha256"),
        "config_sha256": envelope.get("config_sha256"),
        "code_version": envelope.get("code_version"), "blocking_reason": None,
    })
    row.update(values)
    contract.validate_result_row(row)
    return row


def run_offline(stage8_root: Path, config: Mapping[str, Any], envelope: Mapping[str, Any], run_id: str) -> list[Dict[str, Any]]:
    source_rows = contract.load_stage8_rows(stage8_root)
    rows = []
    for source in source_rows:
        for profile in sorted(contract.EXPECTED_PROFILES):
            value = contract.recompute_profile_row(source, profile)
            row_id = f"offline-{source['source_job_id']}-{profile}"
            row = base_row(run_id, row_id, "offline_recompute", "candidate-ready", envelope,
                           source_job_id=source["source_job_id"],
                           source_result_sha256=source["source_result_sha256"],
                           source_semantic_result_sha256=source["source_semantic_result_sha256"],
                           evidence_mode="stage8_raw_counter_offline_recompute",
                           parameter_family="cost_profile", grid_cell_id=profile,
                           track=source.get("track"), workload=source.get("workload"),
                           seed=source.get("seed"), policy_or_ablation=source.get("policy"),
                           D=source.get("D"), F_low=source.get("F_low"),
                           F_target=source.get("F_target"),
                           F_target_minus_F_low=(source.get("F_target") - source.get("F_low")
                                                if source.get("F_target") is not None and source.get("F_low") is not None else None),
                           capacity_working_set_fraction=None, b_max=source.get("b_max"),
                           dram_hits=value["dram_hits"], nvm_reads=value["nvm_reads"],
                           nvm_writes=value["nvm_writes"], proactive_demotions=value["proactive_demotions"],
                           reactive_demotions=value["reactive_demotions"], emergency_demotions=value["emergency_demotions"],
                           total_demotions=value["total_demotions"], raw_access_count=value["raw_access_count"],
                           weighted_cost=value["weighted_cost"], weighted_cost_per_access=value["weighted_cost_per_access"],
                           cost_profile=profile, input_artifact_path=source["source_artifact_path"],
                           input_artifact_sha256=source["source_artifact_sha256"])
            rows.append(row)
    return rows


def blocked_row(run_id: str, lane: str, reason: str, envelope: Mapping[str, Any], family: str) -> Dict[str, Any]:
    return base_row(run_id, f"{lane}-{family.lower()}", lane, "BLOCKED", envelope,
                    evidence_mode="gate", parameter_family=family,
                    blocking_reason=reason)


def run_sync(config: Mapping[str, Any], envelope: Mapping[str, Any], run_id: str) -> list[Dict[str, Any]]:
    frozen = contract.require_sync_grid(config)
    rows = []
    for index, cell in enumerate(frozen["grid_records"]):
        rows.append(base_row(run_id, f"sync-{index:04d}", "sync_candidate", "candidate-ready", envelope,
                             evidence_mode="synchronous_replay_candidate", parameter_family="sensitivity",
                             grid_cell_id=f"cell-{index:04d}", F_low=cell["watermark_candidate"],
                             b_max=cell["b_max"], capacity_working_set_fraction=cell["capacity_working_set_fraction"],
                             cost_profile=cell["cost_profile"], blocking_reason=None))
    return rows


def run_ablation_interfaces(config: Mapping[str, Any], envelope: Mapping[str, Any],
                            run_id: str) -> list[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(contract.expand_ablation_grid(config)):
        row = base_row(run_id, f"ablation-{index:02d}", "sync_candidate",
                       item["evidence_status"], envelope,
                       evidence_mode=item["evidence_mode"],
                       parameter_family=item["parameter_family"],
                       grid_cell_id=f"ablation-{index:02d}",
                       policy_or_ablation=item["policy_or_ablation"],
                       blocking_reason=item.get("blocking_reason"))
        if "selection_count" in item:
            row["selection_count"] = item["selection_count"]
        rows.append(row)
    return rows


def run_external(config: Mapping[str, Any], envelope: Mapping[str, Any], run_id: str) -> list[Dict[str, Any]]:
    stage9 = contract.audit_stage9_gate(config.get("external_gates", {}).get("stage9_run_root"))
    stage10 = contract.audit_stage10_fixture(config.get("external_gates", {}).get("stage10_run_root"))
    rows = []
    for receipt in (stage9, stage10):
        status = ("candidate-ready" if receipt.get("status") == "verified" and
                  receipt.get("formal_authorized") is True else
                  "BLOCKED" if receipt.get("status") == "BLOCKED" else "NOT_VERIFIABLE")
        rows.append(base_row(run_id, f"external-{receipt['stage']}", "external_gates", status, envelope,
                             evidence_mode=receipt["stage"] + "_gate", parameter_family=receipt["stage"],
                             blocking_reason=receipt.get("reason_code")))
    return rows


def render_csv(root: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    lines = []
    with (root / "stage11a_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("N/A" if row.get(key) is None else row.get(key)) for key in ROW_FIELDS})


def render_report(rows: list[Mapping[str, Any]], gates: list[Mapping[str, Any]]) -> str:
    status_counts = {}
    for row in rows:
        status_counts[row["evidence_status"]] = status_counts.get(row["evidence_status"], 0) + 1
    lines = [
        "# CAPD Stage11A 状态报告", "",
        "## 1. 已实现的代码", "", "Stage11A 三通道 runner、配置、schema、哈希验证和 fail-closed 门禁已实现。", "",
        "## 2. candidate-ready 的同步/离线结果", "", f"状态计数：{status_counts}", "离线 weighted cost 仅来自 Stage8 r5 raw counters；缺失数值在报告中显示为 N/A。", "",
        "## 3. 因 Stage9 权限不足而阻塞的真实开销结果", "", "Stage9 CPU latency、cycles、instructions、task-clock、RSS 和模型内存没有在本地生成；当前门禁保持 BLOCKED/NOT_VERIFIABLE。", "",
        "## 4. 因 Stage10 未完成而阻塞的异步结果", "", "Stage10A fixture 只证明 fixture 完整性，不能升级为正式异步验证；Stage10B 正向契约尚未存在。", "",
        "## 5. 当前不能支持的论文结论", "", "不能从本报告支持真实系统开销、异步并发收益或 formally_verified Stage11 结论。", "",
    ]
    return "\n".join(lines) + "\n"


def verify_run(run_root: os.PathLike[str] | str) -> Dict[str, Any]:
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise contract.Stage11ContractError("Stage11 run directory is missing.")
    verify_manifest_and_checksums(root)
    config = contract.load_json(root / "stage11a_config.json")
    contract.validate_config(config)
    verification = contract.load_json(root / "verification.json")
    state = contract.load_json(root / "run_state.json")
    if verification.get("formally_verified") is not False or state.get("formally_verified") is not False:
        raise contract.Stage11ContractError("Stage11 formal verification state is invalid.")
    if state.get("status") == "stage11a_formally_verified":
        raise contract.Stage11ContractError("Stage11A v1.0 cannot be formally verified.")
    results = contract.load_json(root / "stage11a_results.json")
    if results.get("schema_version") != "capd_proactive_stage11a_result_schema_v1_0":
        raise contract.Stage11ContractError("Stage11 results schema mismatch.")
    rows = results.get("rows")
    if not isinstance(rows, list) or not rows:
        raise contract.Stage11ContractError("Stage11 results rows are empty.")
    for row in rows:
        contract.validate_result_row(row)
    resolved = config.get("resolved", {})
    stage8_path = resolved.get("stage8_authority_path")
    if stage8_path:
        source_rows = {item["source_job_id"]: item
                       for item in contract.load_stage8_rows(stage8_path)}
        for row in rows:
            if row.get("lane") != "offline_recompute":
                continue
            source = source_rows.get(row.get("source_job_id"))
            if source is None:
                raise contract.Stage11ContractError("Offline source job is not in Stage8 authority.")
            expected = contract.recompute_profile_row(source, row.get("cost_profile"))
            for field in ("source_result_sha256", "source_semantic_result_sha256",
                          "weighted_cost", "weighted_cost_per_access"):
                if row.get(field) != expected.get(field):
                    raise contract.Stage11ContractError("Offline recomputation mismatch: " + field)
    with (root / "stage11a_results.csv").open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    if len(csv_rows) != len(rows):
        raise contract.Stage11ContractError("Stage11 CSV row count mismatch.")
    return {"status": "verified", "row_count": len(rows),
            "manifest_sha256": sha256_file(root / "stage11a_manifest.json"),
            "checksums_sha256": sha256_file(root / "SHA256SUMS"),
            "config_sha256": sha256_file(root / "stage11a_config.json")}


def run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    output_root = Path(args.output_root).resolve()
    config, stage8_root, run_root = validate_preflight(
        config_path, output_root, args.run_id,
        args.stage9_run_root, args.stage10_run_root)
    # Freeze the envelope before creating any lane outputs.
    stage8_csv = stage8_root / "artifacts" / "per_workload_raw.csv"
    envelope = {
        "run_id": args.run_id,
        "stage8_authority_path": str(stage8_root),
        "stage8_artifact_path": str(stage8_csv.relative_to(stage8_root)).replace("\\", "/"),
        "stage8_artifact_sha256": sha256_file(stage8_csv),
        "config_sha256": sha256_file(config_path),
        "schema_sha256": sha256_file(SCHEMA_DEFAULT),
        "code_version": code_version(),
        "label_weights": config["main_control"]["label_weights"],
        "frozen_grid_sha256": contract.freeze_grid(config)["frozen_grid_sha256"],
        "run_identity": f"stage11a-{args.run_id}",
    }
    run_root.mkdir(parents=True)
    atomic_json(run_root / "stage11a_config.json", {**config, "resolved": envelope})
    rows: list[Dict[str, Any]] = []
    lanes = args.mode
    try:
        if lanes in ("offline", "all"):
            rows.extend(run_offline(stage8_root, config, envelope, args.run_id))
        if lanes in ("sync", "all"):
            try:
                frozen = contract.require_sync_grid(config)
                envelope["frozen_grid_sha256"] = frozen["frozen_grid_sha256"]
                rows.extend(run_sync(config, envelope, args.run_id))
            except contract.Stage11Blocked as exc:
                rows.append(blocked_row(args.run_id, "sync_candidate", str(exc), envelope, "sensitivity"))
            rows.extend(run_ablation_interfaces(config, envelope, args.run_id))
        if lanes == "all":
            rows.extend(run_external(config, envelope, args.run_id))
    except Exception:
        # Preserve a diagnostic run state but do not fabricate numeric rows.
        if not rows:
            rows.append(blocked_row(args.run_id, "offline_recompute", "lane_execution_failed", envelope, "offline"))
    atomic_json(run_root / "stage11a_results.json", {
        "schema_version": "capd_proactive_stage11a_result_schema_v1_0",
        "contract_id": contract.CONTRACT_ID, "run_id": args.run_id, "rows": rows,
    })
    render_csv(run_root, rows)
    gates = [row for row in rows if row["lane"] == "external_gates"]
    atomic_json(run_root / "verification.json", {
        "schema_version": "capd_proactive_stage11a_verification_v1_0",
        "run_id": args.run_id, "formally_verified": False,
        "row_count": len(rows), "external_gate_rows": len(gates),
        "input_sha256": envelope["stage8_artifact_sha256"],
        "config_sha256": envelope["config_sha256"],
        "code_version": envelope["code_version"],
    })
    status_set = {row["evidence_status"] for row in rows}
    status = ("stage11a_candidate_ready" if "candidate-ready" in status_set else
              "stage11a_blocked" if "BLOCKED" in status_set else "stage11a_not_verifiable")
    atomic_json(run_root / "run_state.json", {
        "schema_version": "capd_proactive_stage11a_run_state_v1_0",
        "run_id": args.run_id, "status": status,
        "completed_lanes": sorted({row["lane"] for row in rows}),
        "formally_verified": False,
    })
    atomic_text(run_root / "stage11a_report.md", render_report(rows, gates))
    atomic_json(run_root / "stage11a_manifest.json", build_manifest(run_root))
    write_checksums(run_root)
    if args.verify:
        verify_run(run_root)
    print(str(run_root))
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--config", default=str(CONFIG_DEFAULT))
    value.add_argument("--mode", choices=("offline", "sync", "all"), default="offline")
    value.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    value.add_argument("--run-id", required=True)
    value.add_argument("--stage9-run-root")
    value.add_argument("--stage10-run-root")
    value.add_argument("--verify", action="store_true")
    return value


if __name__ == "__main__":
    try:
        arguments = parser().parse_args()
        raise SystemExit(run(arguments))
    except Exception as exc:
        print("[BLOCKED] Stage11A preflight/lane failure: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
