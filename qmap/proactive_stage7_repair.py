# coding=utf-8
"""Immutable local R1-R4 preparation for the CAPD Stage-7 repair."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from array import array
from collections import OrderedDict, defaultdict
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


CONTRACT_ID = "CAPD-PROACTIVE-STAGE7-REPAIR-R1-R4-1.0"
SCHEMA_VERSION = "capd_proactive_stage7_repair_v1_0"
WORKLOADS = (
    "canneal", "streamcluster_pressure", "dedup_pressure",
    "blackscholes", "swaptions", "fluidanimate")
PRESSURE_OVERHEAD_FIELDS = (
    "memory_overhead", "metadata_memory_overhead", "inference_latency",
    "cpu_cycles", "total_execution_time", "foreground_blocking_time",
    "end_to_end_overhead")
PROHIBITED_SELECTION_TOKENS = (
    "capd", "oracle", "tpp", "weighted_cost", "stage8", "policy_result")


class Stage7RepairError(ValueError):
  """Raised when an R1-R4 integrity or experiment-boundary gate fails."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage7RepairError(message)


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as handle:
    return json.load(handle)


def fingerprint_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    while True:
      block = handle.read(1024 * 1024)
      if not block:
        break
      digest.update(block)
  return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
  payload = json.dumps(
      value, ensure_ascii=False, sort_keys=True,
      separators=(",", ":")).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage7-repair-json-", suffix=".tmp", dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
      json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
      handle.write("\n")
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]],
                     fieldnames: Sequence[str]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage7-repair-csv-", suffix=".tmp", dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(
          handle, fieldnames=list(fieldnames), lineterminator="\n")
      writer.writeheader()
      for row in rows:
        writer.writerow({field: row.get(field) for field in fieldnames})
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def verify_declared_sha(path: str, expected_sha256: str, label: str) -> str:
  _require(os.path.isfile(path), "Missing {}: {}".format(label, path))
  actual = fingerprint_file(path)
  _require(actual == str(expected_sha256).lower(),
           "{} SHA256 mismatch: expected {}, got {}.".format(
               label, expected_sha256, actual))
  return actual


def validate_repair_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Repair config schema mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Repair config contract mismatch.")
  _require(value.get("execution_scope") == "local_r1_r4_only",
           "Repair config must be local R1-R4 only.")
  _require(value.get("source_stage7_run_id") == "stage7-server-suite-r1",
           "Immutable source Stage-7 run changed.")
  _require(tuple(value.get("workloads", ())) == WORKLOADS,
           "The exact six-workload order is required.")
  _require(value.get("parameter_status") ==
           "pending_stage3_stage4_parameter_reselection" and
           value.get("formal_freeze_allowed") is False and
           "fixed_parameters" not in value,
           "Repair parameters must remain pending Stage-3/4 reselection.")
  fixed = value.get("candidate_parameters_snapshot", {})
  _require(fixed.get("F_low") == 8 and fixed.get("F_target") == 16 and
           fixed.get("b_max") == 4 and fixed.get("K") == 8 and
           fixed.get("H") == 20 and fixed.get("L") == 256 and
           fixed.get("lambda") == [1, 1, 2] and
           fixed.get("seeds") == [3136859, 42, 2026],
           "Frozen CAPD parameters changed.")
  _require(fixed.get("tpp_inspired") == {
      "epoch_length": 1024, "cold_threshold": 1,
      "dirty_tie_break": False}, "Frozen TPP-inspired parameters changed.")
  _require(fixed.get("cost_profile") == {
      "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
      "Frozen cost profile changed.")
  capacity = value.get("capacity", {})
  _require(capacity.get("requested_ratios") == ["0.20", "0.40", "0.60"] and
           capacity.get("reserve_fraction_cap") == 0.25 and
           capacity.get("D_guard_min") == 64,
           "Capacity guard contract changed.")
  split = value.get("split_contract", {})
  _require(split.get("total_accesses") == 3000000 and
           split.get("train") == [0, 1800000] and
           split.get("validation") == [1800000, 2400000] and
           split.get("test") == [2400000, 3000000] and
           split.get("interval") == "half_open" and
           split.get("chronological") is True and
           split.get("shuffle") is False,
           "Chronological split contract changed.")
  pressure = value.get("pressure_scan", {})
  _require(pressure.get("policy") == "reactive_lru" and
           pressure.get("initial_state") == "empty_dram_per_candidate" and
           pressure.get("test_interval") == [2400000, 3000000] and
           pressure.get("window_records") == 100000 and
           pressure.get("scan_step") == 10000 and
           pressure.get("minimum_lru_replacement_decisions") == 100 and
           pressure.get("selection_features") == [
               "reactive_lru_decisions", "unique_pages", "earliest_start"],
           "Pressure scan contract changed.")
  _require(value.get("pressure_overhead_claims_allowed") is False,
           "Pressure overhead claims must remain forbidden.")
  _require(value.get("test_access_policy") == {
      "r1_r3_test_payload_allowed": False,
      "r4_reader": "fixed_reactive_lru_only",
      "capd_or_oracle_selection_allowed": False},
      "Test access boundary changed.")
  _require(value.get("prohibited_local_stages") == [
      "R5", "R6", "R7", "R8", "R9", "R10", "R11"],
      "Local prohibited-stage boundary changed.")
  return value


def require_formal_parameter_freeze(value: Mapping[str, Any]) -> None:
  _require(value.get("formal_freeze_allowed") is True and
           value.get("parameter_status") ==
           "stage3_stage4_parameters_frozen" and
           isinstance(value.get("fixed_parameters"), Mapping),
           "R2-R4 paused: Stage-3/4 parameters are not formally frozen.")


def validate_source_interval(start: int, end: int,
                             test_start: int, test_end: int) -> None:
  _require(isinstance(start, int) and isinstance(end, int),
           "Source interval indices must be integers.")
  _require(test_start <= start < end <= test_end,
           "Source interval [{},{}) lies outside Test [{},{}).".format(
               start, end, test_start, test_end))


def compute_capacity_rows(workload: str, working_set_pages: int,
                          config: Mapping[str, Any]) -> List[Dict[str, Any]]:
  validate_repair_config(config)
  _require(isinstance(working_set_pages, int) and working_set_pages > 0,
           "Working set must contain a positive number of pages.")
  rows = []
  guard_min = int(config["capacity"]["D_guard_min"])
  for ratio in config["capacity"]["requested_ratios"]:
    base = int((Decimal(ratio) * Decimal(working_set_pages)).to_integral_value(
        rounding=ROUND_CEILING))
    guarded = max(base, guard_min)
    rows.append({
        "workload": workload,
        "working_set_pages": working_set_pages,
        "requested_ratio": ratio,
        "D_base": base,
        "D_guarded": guarded,
        "effective_ratio": guarded / float(working_set_pages),
        "guard_applied": guarded != base,
        "strict_requested_ratio_description_allowed": guarded == base,
    })
  return rows


def pressure_candidate_starts(config: Mapping[str, Any]) -> List[int]:
  validate_repair_config(config)
  pressure = config["pressure_scan"]
  test_start, test_end = pressure["test_interval"]
  window = pressure["window_records"]
  step = pressure["scan_step"]
  starts = list(range(test_start, test_end - window + 1, step))
  _require(starts and starts[-1] + window <= test_end,
           "Pressure candidate interval construction failed.")
  return starts


def profile_lru_candidate(pages: Sequence[int], writes: Sequence[bool],
                          dram_pages: int) -> Dict[str, Any]:
  _require(isinstance(dram_pages, int) and dram_pages > 0,
           "DRAM capacity must be positive.")
  _require(len(pages) == len(writes) and len(pages) > 0,
           "Candidate pages and writes must be non-empty and aligned.")
  resident = OrderedDict()
  unique = set()
  misses = 0
  replacements = 0
  write_count = 0
  for page, write in zip(pages, writes):
    page = int(page)
    unique.add(page)
    if bool(write):
      write_count += 1
    if page in resident:
      resident.move_to_end(page)
      continue
    misses += 1
    if len(resident) >= dram_pages:
      resident.popitem(last=False)
      replacements += 1
    resident[page] = None
  return {
      "policy": "reactive_lru",
      "initial_state": "empty_dram",
      "unique_pages": len(unique),
      "misses": misses,
      "lru_replacement_decisions": replacements,
      "write_count": write_count,
      "write_ratio": write_count / float(len(pages)),
      "page_entry_count": misses,
      "window_records": len(pages),
  }


def _inside(root: str, path: str) -> bool:
  try:
    return os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
  except ValueError:
    return False


def resolve_recorded_split(project_root: str, recorded_path: str,
                           expected_sha256: str) -> str:
  root = os.path.realpath(project_root)
  normalized = str(recorded_path).replace("\\", "/")
  _require(normalized and not os.path.isabs(normalized),
           "Recorded split path must be repository-relative.")
  candidates = [os.path.join(root, normalized.replace("/", os.sep))]
  if "stage7-server-suite-r1" in normalized:
    candidates.append(os.path.join(
        root, normalized.replace(
            "stage7-server-suite-r1", "stage7-local-suite-r1")
        .replace("/", os.sep)))
  marker = "/splits/"
  if marker in normalized:
    suffix = normalized.split(marker, 1)[1].replace("/", os.sep)
    stage7_root = os.path.join(root, "outputs", "capd_proactive_stage7")
    if os.path.isdir(stage7_root):
      for name in sorted(os.listdir(stage7_root)):
        candidates.append(os.path.join(stage7_root, name, "splits", suffix))
  seen = set()
  for candidate in candidates:
    resolved = os.path.realpath(candidate)
    if resolved in seen or not _inside(root, resolved):
      continue
    seen.add(resolved)
    if os.path.isfile(resolved) and fingerprint_file(resolved) == expected_sha256:
      return resolved
  raise Stage7RepairError(
      "Cannot resolve split with declared SHA256: {}.".format(recorded_path))


def _cell_key(row: Mapping[str, Any]) -> Tuple[str, str, int]:
  return (str(row["workload"]), str(row["requested_ratio"]),
          int(row["D_guarded"]))


def _reject_prohibited_selection_fields(rows: Sequence[Mapping[str, Any]]) -> None:
  for row in rows:
    for field in row:
      normalized = str(field).lower()
      if any(token in normalized for token in PROHIBITED_SELECTION_TOKENS):
        raise Stage7RepairError(
            "Prohibited Pressure selection field: {}.".format(field))


def select_pressure_windows(candidates: Sequence[Mapping[str, Any]],
                            config: Mapping[str, Any]) -> Dict[str, Any]:
  del config
  rows = [dict(row) for row in candidates]
  _require(rows, "Pressure candidate list cannot be empty.")
  _reject_prohibited_selection_fields(rows)
  groups = defaultdict(list)
  for row in rows:
    for field in (
        "workload", "requested_ratio", "D_base", "D_guarded",
        "source_start_inclusive", "source_end_exclusive", "unique_pages",
        "misses", "lru_replacement_decisions", "write_ratio",
        "page_entry_count"):
      _require(field in row, "Candidate missing field: {}.".format(field))
    groups[_cell_key(row)].append(row)
  cells = []
  for key in sorted(groups):
    group = groups[key]
    guarded = key[2]
    eligible = [row for row in group
                if int(row["unique_pages"]) > guarded + 16 and
                int(row["lru_replacement_decisions"]) >= 100]
    eligible.sort(key=lambda row: (
        -int(row["lru_replacement_decisions"]),
        -int(row["unique_pages"]), int(row["source_start_inclusive"])))
    selected = dict(eligible[0]) if eligible else None
    cells.append({
        "workload": key[0],
        "requested_ratio": key[1],
        "D_base": int(group[0]["D_base"]),
        "D_guarded": guarded,
        "effective_ratio": float(group[0]["effective_ratio"]),
        "candidate_count": len(group),
        "eligible_candidate_count": len(eligible),
        "pressure_eligible": bool(eligible),
        "selected": selected,
        "ineligible_reason": (None if eligible else
                              "no_candidate_met_unique_pages_and_"
                              "lru_replacement_decisions_gates"),
        "selection_features": [
            "reactive_lru_decisions", "unique_pages", "earliest_start"],
        "manual_override_allowed": False,
    })
  return {
      "schema_version": "capd_pressure_window_selection_v1_0",
      "selection_policy": "fixed_reactive_lru_only",
      "cells": cells,
  }


def _copy_binary_lines(source_path: str, destination_path: str,
                       relative_start: int, row_count: int) -> int:
  _require(relative_start >= 0 and row_count > 0,
           "Derived interval must have non-negative start and positive rows.")
  directory = os.path.dirname(os.path.abspath(destination_path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".pressure-derived-", suffix=".tmp", dir=directory)
  os.close(fd)
  copied = 0
  try:
    with open(source_path, "rb") as source, open(temporary, "wb") as output:
      header = source.readline()
      _require(bool(header), "Source Test CSV is empty.")
      output.write(header)
      for index, line in enumerate(source):
        if index < relative_start:
          continue
        if index >= relative_start + row_count:
          break
        output.write(line)
        copied += 1
    _require(copied == row_count,
             "Source Test interval is out of bounds: requested {}, copied {}."
             .format(row_count, copied))
    os.replace(temporary, destination_path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)
  return copied


def derive_pressure_csv(source_test_path: str, destination_path: str,
                        relative_start: int, row_count: int) -> Dict[str, Any]:
  source_before = fingerprint_file(source_test_path)
  rows = _copy_binary_lines(
      source_test_path, destination_path, relative_start, row_count)
  source_after = fingerprint_file(source_test_path)
  _require(source_before == source_after,
           "Source Test CSV changed during derivation.")
  return {
      "rows": rows,
      "source_split_sha256": source_before,
      "source_split_sha256_after": source_after,
      "sha256": fingerprint_file(destination_path),
  }


def verify_derived_rows(source_test_path: str, derived_path: str,
                        relative_start: int, row_count: int) -> None:
  with open(source_test_path, "rb") as source:
    source_header = source.readline()
    expected = []
    for index, line in enumerate(source):
      if index < relative_start:
        continue
      if index >= relative_start + row_count:
        break
      expected.append(line)
  with open(derived_path, "rb") as derived:
    derived_header = derived.readline()
    actual = list(derived)
  _require(source_header == derived_header,
           "Derived CSV header differs from source Test.")
  _require(len(expected) == row_count,
           "Declared source interval exceeds Test CSV.")
  _require(actual == expected,
           "Derived CSV rows differ from the declared source Test interval.")


def _walk_values(value: Any) -> Iterable[Mapping[str, Any]]:
  if isinstance(value, Mapping):
    yield value
    for item in value.values():
      for nested in _walk_values(item):
        yield nested
  elif isinstance(value, (list, tuple)):
    for item in value:
      for nested in _walk_values(item):
        yield nested


def assert_no_pressure_overhead(value: Any) -> None:
  for row in _walk_values(value):
    for field in PRESSURE_OVERHEAD_FIELDS:
      _require(field not in row or row[field] is None,
               "Pressure overhead field {} must be null or absent."
               .format(field))


def _portable_inside(path: str, root: str) -> str:
  resolved = os.path.realpath(path)
  _require(_inside(root, resolved),
           "Bundle artifact lies outside bundle root: {}.".format(path))
  return os.path.relpath(resolved, os.path.realpath(root)).replace(os.sep, "/")


def build_bundle_manifest(bundle_root: str, run_id: str,
                          artifact_paths: Sequence[str],
                          derived_entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  root = os.path.realpath(bundle_root)
  files = []
  seen = set()
  for path in artifact_paths:
    relative = _portable_inside(path, root)
    _require(relative not in seen, "Duplicate bundle artifact: {}.".format(relative))
    seen.add(relative)
    files.append({
        "path": relative,
        "sha256": fingerprint_file(path),
        "bytes": os.path.getsize(path),
    })
  files.sort(key=lambda row: row["path"])
  value = {
      "schema_version": "capd_stage7_repair_local_pressure_bundle_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "bundle_root": ".",
      "files": files,
      "derived_pressure": [dict(row) for row in derived_entries],
      "pressure_overhead_claims_allowed": False,
      "server_may_rescan_or_rederive": False,
      "included_stages": ["R1", "R2", "R3", "R4"],
      "excluded_stages": ["R5", "R6", "R7", "R8", "R9", "R10", "R11"],
      "status": "formal_pressure_bundle_frozen",
      "formal_pressure_bundle": True,
  }
  assert_no_pressure_overhead(value)
  return value


def verify_bundle_manifest(manifest_path: str) -> Mapping[str, Any]:
  manifest = load_json(manifest_path)
  _require(manifest.get("schema_version") ==
           "capd_stage7_repair_local_pressure_bundle_v1_0" and
           manifest.get("contract_id") == CONTRACT_ID,
           "Local bundle schema/contract mismatch.")
  _require(manifest.get("formal_pressure_bundle") is True and
           manifest.get("status") == "formal_pressure_bundle_frozen",
           "Pressure bundle is paused, revoked, or not formally frozen.")
  _require(manifest.get("pressure_overhead_claims_allowed") is False and
           manifest.get("server_may_rescan_or_rederive") is False and
           manifest.get("included_stages") == ["R1", "R2", "R3", "R4"] and
           manifest.get("excluded_stages") == [
               "R5", "R6", "R7", "R8", "R9", "R10", "R11"],
           "Local/server boundary changed in bundle manifest.")
  root = os.path.dirname(os.path.realpath(manifest_path))
  for item in manifest.get("files", []):
    relative = item.get("path", "")
    _require(relative and not os.path.isabs(relative),
             "Bundle file path must be relative.")
    path = os.path.realpath(os.path.join(root, relative.replace("/", os.sep)))
    _require(_inside(root, path), "Bundle file escapes bundle root.")
    verify_declared_sha(path, item.get("sha256", ""), "bundle artifact")
    _require(os.path.getsize(path) == item.get("bytes"),
             "Bundle artifact size mismatch: {}.".format(relative))
  assert_no_pressure_overhead(manifest)
  return manifest


def _portable(path: str, project_root: str) -> str:
  resolved = os.path.realpath(path)
  if _inside(project_root, resolved):
    return os.path.relpath(resolved, os.path.realpath(project_root)).replace(
        os.sep, "/")
  return resolved


def _project_file(project_root: str, recorded_path: str) -> str:
  _require(isinstance(recorded_path, str) and recorded_path,
           "Repository file path is empty.")
  _require(not os.path.isabs(recorded_path),
           "Repository file path must be relative.")
  path = os.path.realpath(os.path.join(
      project_root, recorded_path.replace("/", os.sep)))
  _require(_inside(project_root, path),
           "Repository file escapes project root: {}.".format(recorded_path))
  _require(os.path.isfile(path), "Missing repository file: {}.".format(
      recorded_path))
  return path


def _safe_run_id(run_id: str) -> str:
  _require(isinstance(run_id, str) and run_id and all(
      character.isalnum() or character in "._-" for character in run_id),
      "run_id contains unsafe characters.")
  return run_id


def repair_output_root(project_root: str, run_id: str) -> str:
  return os.path.join(
      os.path.realpath(project_root), "outputs",
      "capd_proactive_stage7_repair", _safe_run_id(run_id))


def _load_source_manifests(source_stage7_run: str) -> Dict[str, Any]:
  names = (
      "raw_trace_manifest.json", "collection_manifest.json",
      "split_manifest.json", "verification.json")
  result = {}
  for name in names:
    path = os.path.join(source_stage7_run, name)
    _require(os.path.isfile(path), "Missing source Stage-7 artifact: {}."
             .format(path))
    result[name] = {"path": path, "value": load_json(path),
                    "sha256": fingerprint_file(path)}
  evidence = result["verification.json"]["value"].get("evidence_sha256", {})
  for name in names[:3]:
    _require(evidence.get(name) == result[name]["sha256"],
             "Stage-7 verification SHA mismatch for {}.".format(name))
  return result


def _manifest_maps(manifests: Mapping[str, Any]) -> Tuple[Dict[str, Any],
                                                          Dict[str, Any],
                                                          Dict[str, Any]]:
  raw_rows = manifests["raw_trace_manifest.json"]["value"].get("traces", [])
  collection_rows = manifests["collection_manifest.json"]["value"].get(
      "collections", [])
  split_rows = manifests["split_manifest.json"]["value"].get("workloads", [])
  raw = {os.path.splitext(os.path.basename(row["path"]))[0]: row
         for row in raw_rows}
  collections = {row["workload"]: row for row in collection_rows}
  splits = {row["workload"]: row for row in split_rows}
  _require(set(raw) == set(WORKLOADS) and
           set(collections) == set(WORKLOADS) and
           set(splits) == set(WORKLOADS),
           "Source manifests must contain the exact six workloads.")
  return raw, collections, splits


def _split_interval(split: Mapping[str, Any]) -> Tuple[int, int]:
  interval = split.get("interval", {})
  return int(interval.get("start_inclusive", -1)), int(
      interval.get("end_exclusive", -1))


def _audit_csv_identity(path: str) -> Dict[str, Any]:
  pids = set()
  tids = set()
  rows = 0
  with open(path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.reader(handle)
    try:
      header = next(reader)
    except StopIteration:
      raise Stage7RepairError("Raw trace CSV is empty: {}.".format(path))
    normalized = {name.strip().lower(): index
                  for index, name in enumerate(header)}
    required = ("pid", "tid", "pc", "address", "rw")
    _require(all(name in normalized for name in required),
             "Raw trace header lacks PID/TID/PC/Address/RW.")
    max_index = max(normalized[name] for name in required)
    for row in reader:
      _require(len(row) > max_index, "Malformed raw trace row {}.".format(rows))
      try:
        pids.add(int(row[normalized["pid"]], 0))
        tids.add(int(row[normalized["tid"]], 0))
      except ValueError:
        raise Stage7RepairError("Invalid PID/TID at raw row {}.".format(rows))
      rows += 1
  return {"accesses": rows, "process_ids": sorted(pids),
          "thread_ids": sorted(tids), "columns": header}


def _resolve_all_inputs(project_root: str, config: Mapping[str, Any],
                        manifests: Mapping[str, Any]) -> Dict[str, Any]:
  raw_map, collection_map, split_map = _manifest_maps(manifests)
  inputs = {}
  expected_intervals = config["split_contract"]
  for workload in WORKLOADS:
    raw = raw_map[workload]
    collection = collection_map[workload]
    split_row = split_map[workload]
    _require(raw.get("source_trace_id") == collection.get("source_trace_id"),
             "Raw/collection source identity mismatch for {}.".format(workload))
    _require(raw.get("sha256") == collection.get("raw_trace_sha256"),
             "Raw/collection SHA mismatch for {}.".format(workload))
    _require(raw.get("path") == collection.get("raw_trace_path"),
             "Raw/collection path mismatch for {}.".format(workload))
    _require(raw.get("accesses") == 3000000 and
             collection.get("raw_trace_accesses") == 3000000 and
             raw.get("page_shift") == 12 and collection.get("page_shift") == 12,
             "Raw access/page-shift contract mismatch for {}.".format(workload))
    raw_path = _project_file(project_root, raw["path"])
    raw_sha = verify_declared_sha(
        raw_path, raw["sha256"], "{} raw trace".format(workload))
    resolved_splits = {}
    for role in ("train", "validation", "test"):
      item = split_row["splits"][role]
      expected = tuple(expected_intervals[role])
      actual = _split_interval(item)
      _require(actual == expected and
               item.get("accesses") == expected[1] - expected[0] and
               item.get("source_trace_id") == raw["source_trace_id"] and
               item.get("split_role") == role,
               "{} {} split identity/interval mismatch.".format(
                   workload, role))
      path = resolve_recorded_split(
          project_root, item["path"], item["sha256"])
      resolved_splits[role] = {
          "recorded_path": item["path"],
          "resolved_path": path,
          "sha256": item["sha256"],
          "interval": {
              "start_inclusive": actual[0], "end_exclusive": actual[1]},
          "accesses": item["accesses"],
      }
    inputs[workload] = {
        "raw_manifest": raw,
        "collection_manifest": collection,
        "raw_path": raw_path,
        "raw_sha256": raw_sha,
        "splits": resolved_splits,
    }
  return inputs


def _source_snapshot(project_root: str, config_path: str,
                     source_stage7_run: str,
                     config: Mapping[str, Any],
                     manifests: Mapping[str, Any],
                     inputs: Mapping[str, Any]) -> Dict[str, Any]:
  return {
      "config": {"path": _portable(config_path, project_root),
                 "sha256": fingerprint_file(config_path)},
      "source_stage7_run": _portable(source_stage7_run, project_root),
      "source_manifests": {
          name: item["sha256"] for name, item in sorted(manifests.items())},
      "workloads": [{
          "workload": workload,
          "source_trace_id": inputs[workload]["raw_manifest"]["source_trace_id"],
          "raw_path": _portable(inputs[workload]["raw_path"], project_root),
          "raw_sha256": inputs[workload]["raw_sha256"],
          "split_sha256": {
              role: inputs[workload]["splits"][role]["sha256"]
              for role in ("train", "validation", "test")},
      } for workload in WORKLOADS],
      "contract_fingerprint": fingerprint_value(config),
  }


def _state_path(output_root: str) -> str:
  return os.path.join(output_root, "local_prepare_state.json")


def _load_or_initialize_state(output_root: str,
                              snapshot: Mapping[str, Any]) -> Dict[str, Any]:
  path = _state_path(output_root)
  identity = fingerprint_value(snapshot)
  if os.path.exists(path):
    state = load_json(path)
    _require(state.get("input_identity_sha256") == identity,
             "Input/config identity changed for existing run ID; use a new run ID.")
    return state
  os.makedirs(output_root, exist_ok=True)
  unexpected = [name for name in os.listdir(output_root)
                if name != os.path.basename(path)]
  _require(not unexpected,
           "Existing run directory lacks a compatible resume state.")
  state = {
      "schema_version": "capd_stage7_repair_local_state_v1_0",
      "phase": "initialized",
      "input_identity_sha256": identity,
      "input_identity": dict(snapshot),
      "artifact_sha256": {},
  }
  write_json_atomic(path, state)
  return state


def _artifacts_match(output_root: str, state: Mapping[str, Any],
                     required: Sequence[str]) -> bool:
  digests = state.get("artifact_sha256", {})
  for relative in required:
    path = os.path.join(output_root, relative.replace("/", os.sep))
    if not os.path.isfile(path) or digests.get(relative) != fingerprint_file(path):
      return False
  return True


def _update_state(output_root: str, state: Dict[str, Any], phase: str,
                  artifact_paths: Sequence[str]) -> None:
  state["phase"] = phase
  for path in artifact_paths:
    relative = _portable_inside(path, output_root)
    state["artifact_sha256"][relative] = fingerprint_file(path)
  write_json_atomic(_state_path(output_root), state)


def _read_compact_splits(paths: Sequence[str]) -> Tuple[array, bytearray,
                                                        List[Dict[str, Any]]]:
  pages = array("Q")
  writes = bytearray()
  split_stats = []
  for path in paths:
    split_pages = set()
    split_rows = 0
    with open(path, "r", encoding="utf-8", newline="") as handle:
      reader = csv.reader(handle)
      try:
        header = next(reader)
      except StopIteration:
        raise Stage7RepairError("Split CSV is empty: {}.".format(path))
      normalized = {name.strip().lower(): index
                    for index, name in enumerate(header)}
      _require("address" in normalized and "rw" in normalized,
               "Split CSV lacks Address/RW columns.")
      address_index = normalized["address"]
      rw_index = normalized["rw"]
      for row in reader:
        try:
          page = int(row[address_index], 0) >> 12
        except (IndexError, ValueError):
          raise Stage7RepairError(
              "Invalid Address in split row {}.".format(split_rows))
        rw = row[rw_index].strip().upper()
        _require(rw in ("R", "W"),
                 "Invalid RW in split row {}.".format(split_rows))
        pages.append(page)
        writes.append(1 if rw == "W" else 0)
        split_pages.add(page)
        split_rows += 1
    split_stats.append({"rows": split_rows, "unique_pages": len(split_pages),
                        "pages": split_pages})
  return pages, writes, split_stats


def _nearest_rank(values: Sequence[int], quantile: float) -> int:
  if not values:
    return 0
  ordered = sorted(values)
  rank = max(1, int(math.ceil(quantile * len(ordered))))
  return ordered[rank - 1]


def _profile_train_validation(pages: Sequence[int], writes: Sequence[bool],
                              dram_pages: int) -> Dict[str, Any]:
  resident = OrderedDict()
  unique = set()
  bursts = []
  current = 0
  misses = 0
  replacements = 0
  write_count = 0
  for index, (page, write) in enumerate(zip(pages, writes)):
    unique.add(page)
    if write:
      write_count += 1
    if page in resident:
      resident.move_to_end(page)
    else:
      misses += 1
      current += 1
      if len(resident) >= dram_pages:
        resident.popitem(last=False)
        replacements += 1
      resident[page] = None
    if (index + 1) % 100 == 0:
      bursts.append(current)
      current = 0
  if len(pages) % 100:
    bursts.append(current)
  return {
      "policy": "reactive_lru",
      "initial_state": "empty_dram_once_before_train",
      "sequence": "train_then_validation",
      "test_accessed": False,
      "dram_pages": dram_pages,
      "accesses": len(pages),
      "unique_pages": len(unique),
      "misses": misses,
      "lru_replacement_decisions": replacements,
      "write_count": write_count,
      "write_ratio": write_count / float(len(pages)),
      "page_entry_count": misses,
      "page_entry_burst_window_records": 100,
      "page_entry_burst_p50": _nearest_rank(bursts, 0.50),
      "page_entry_burst_p95": _nearest_rank(bursts, 0.95),
      "page_entry_burst_p99": _nearest_rank(bursts, 0.99),
      "page_entry_burst_max": max(bursts) if bursts else 0,
  }


def _validate_authorities(project_root: str,
                          config: Mapping[str, Any]) -> Dict[str, Any]:
  stage4_path = _project_file(
      project_root, config["source_authority"]["stage4_verification"])
  stage6_path = _project_file(
      project_root, config["source_authority"]["stage6_verification"])
  stage4 = load_json(stage4_path)
  stage6 = load_json(stage6_path)
  _require(stage4.get("status") == "stage4_verified" and
           stage4.get("selected_parameters") == {
               "candidate_size_K": 8, "history_H": 20,
               "label_weights": [1.0, 1.0, 2.0], "lookahead_L": 256},
           "Stage-4 frozen parameter authority mismatch.")
  _require(stage6.get("status") == "stage6_tpp_inspired_verified" and
           stage6.get("selected_parameters") == {
               "cold_threshold": 1, "dirty_tie_break": False,
               "epoch_length": 1024},
           "Stage-6 TPP-inspired authority mismatch.")
  return {
      "stage4_verification": {
          "path": _portable(stage4_path, project_root),
          "sha256": fingerprint_file(stage4_path)},
      "stage6_verification": {
          "path": _portable(stage6_path, project_root),
          "sha256": fingerprint_file(stage6_path)},
  }


def _prepare_context(config_path: str, source_stage7_run: str, run_id: str,
                     project_root: str) -> Dict[str, Any]:
  root = os.path.realpath(project_root)
  config_path = os.path.realpath(config_path)
  source_stage7_run = os.path.realpath(source_stage7_run)
  _require(_inside(root, config_path) and _inside(root, source_stage7_run),
           "Config and source Stage-7 run must be inside the project.")
  config = load_json(config_path)
  validate_repair_config(config)
  _require(os.path.basename(source_stage7_run) ==
           config["source_stage7_run_id"],
           "Source Stage-7 run ID differs from frozen config.")
  manifests = _load_source_manifests(source_stage7_run)
  inputs = _resolve_all_inputs(root, config, manifests)
  snapshot = _source_snapshot(
      root, config_path, source_stage7_run, config, manifests, inputs)
  output_root = repair_output_root(root, run_id)
  state = _load_or_initialize_state(output_root, snapshot)
  return {
      "project_root": root,
      "config_path": config_path,
      "source_stage7_run": source_stage7_run,
      "config": config,
      "manifests": manifests,
      "inputs": inputs,
      "snapshot": snapshot,
      "output_root": output_root,
      "state": state,
  }


def run_preflight(config_path: str, source_stage7_run: str, run_id: str,
                  project_root: str) -> Dict[str, Any]:
  context = _prepare_context(
      config_path, source_stage7_run, run_id, project_root)
  output_root = context["output_root"]
  state = context["state"]
  parameters_pending = context["config"]["formal_freeze_allowed"] is False
  required = (("raw_identity_audit.json",) if parameters_pending else (
      "raw_identity_audit.json", "frozen_parameters.json",
      "capacity_matrix_standard.json", "capacity_matrix_guarded.json",
      "stage3_pressure_audit.json"))
  resumable_phases = (("r1_verified_r2_r4_paused",) if parameters_pending else
                      ("preflight_complete", "scan_complete",
                       "bundle_verified"))
  if (state.get("phase") in resumable_phases and
      _artifacts_match(output_root, state, required)):
    return {"status": ("r1_resumed_r2_r4_paused" if parameters_pending else
                       "preflight_resumed"), "output_root": output_root,
            "artifacts": list(required)}

  raw_audit_rows = []
  for workload in WORKLOADS:
    item = context["inputs"][workload]
    before = fingerprint_file(item["raw_path"])
    identity = _audit_csv_identity(item["raw_path"])
    after = fingerprint_file(item["raw_path"])
    declared = item["raw_manifest"]
    _require(before == item["raw_sha256"] == after,
             "Raw trace changed while auditing {}.".format(workload))
    _require(identity["accesses"] == 3000000 and
             identity["process_ids"] == declared["process_ids"] and
             identity["thread_ids"] == declared["thread_ids"] and
             len(identity["process_ids"]) == 1 and
             len(identity["thread_ids"]) == 1 and
             identity["columns"] == ["PID", "TID", "PC", "Address", "RW"],
             "Raw trace identity audit failed for {}.".format(workload))
    raw_audit_rows.append({
        "workload": workload,
        "source_trace_id": declared["source_trace_id"],
        "raw_path": _portable(item["raw_path"], context["project_root"]),
        "raw_sha256_before": before,
        "raw_sha256_declared": item["raw_sha256"],
        "raw_sha256_after": after,
        "raw_trace_unchanged": before == after,
        "accesses": identity["accesses"],
        "page_shift": 12,
        "process_ids": identity["process_ids"],
        "thread_ids": identity["thread_ids"],
        "columns": identity["columns"],
        "splits": {
            role: {
                "recorded_path": item["splits"][role]["recorded_path"],
                "resolved_path": _portable(
                    item["splits"][role]["resolved_path"],
                    context["project_root"]),
                "sha256_declared": item["splits"][role]["sha256"],
                "sha256_actual": fingerprint_file(
                    item["splits"][role]["resolved_path"]),
                "interval": item["splits"][role]["interval"],
                "accesses": item["splits"][role]["accesses"],
            } for role in ("train", "validation", "test")},
    })

  raw_audit = {
      "schema_version": "capd_stage7_repair_raw_identity_audit_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "status": "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED",
      "input_identity_sha256": state["input_identity_sha256"],
      "source_manifest_sha256": {
          name: item["sha256"] for name, item in sorted(
              context["manifests"].items())},
      "identity_access_only": True,
      "policy_metrics_read": False,
      "workloads": raw_audit_rows,
  }
  raw_audit_path = os.path.join(output_root, "raw_identity_audit.json")
  write_json_atomic(raw_audit_path, raw_audit)
  if parameters_pending:
    _update_state(
        output_root, state, "r1_verified_r2_r4_paused", (raw_audit_path,))
    _write_r1_pause_artifacts(
        output_root, context["project_root"], context["config"], state)
    return {
        "status": "r1_verified_r2_r4_paused",
        "output_root": output_root,
        "artifacts": ["raw_identity_audit.json", "r1_verification.json",
                      "repair_pause.json"],
    }

  require_formal_parameter_freeze(context["config"])

  authority = _validate_authorities(
      context["project_root"], context["config"])
  standard_rows = []
  guarded_rows = []
  audit_workloads = []
  for workload in WORKLOADS:
    item = context["inputs"][workload]
    train = item["splits"]["train"]
    validation = item["splits"]["validation"]
    pages, writes, stats = _read_compact_splits((
        train["resolved_path"], validation["resolved_path"]))
    _require(stats[0]["rows"] == train["accesses"] and
             stats[1]["rows"] == validation["accesses"],
             "Train/Validation row count mismatch for {}.".format(workload))
    working_pages = stats[0]["pages"] | stats[1]["pages"]
    capacity_rows = compute_capacity_rows(
        workload, len(working_pages), context["config"])
    profiles = {}
    for capacity in sorted(set(
        [row["D_base"] for row in capacity_rows] +
        [row["D_guarded"] for row in capacity_rows])):
      profiles[capacity] = _profile_train_validation(
          pages, writes, capacity)
    for row in capacity_rows:
      common = dict(row)
      standard_rows.append(dict(common, evaluation_track="standard",
                                dram_pages=row["D_base"]))
      guarded_rows.append(dict(common, evaluation_track="pressure",
                               dram_pages=row["D_guarded"]))
    audit_workloads.append({
        "workload": workload,
        "working_set_definition":
            "unique_pages_in_train_validation_union",
        "working_set_pages": len(working_pages),
        "train_accesses": stats[0]["rows"],
        "validation_accesses": stats[1]["rows"],
        "train_unique_pages": stats[0]["unique_pages"],
        "validation_unique_pages": stats[1]["unique_pages"],
        "train_validation_intersection_pages": len(
            stats[0]["pages"] & stats[1]["pages"]),
        "test_accessed": False,
        "capacity_cells": [{
            "requested_ratio": row["requested_ratio"],
            "D_base": row["D_base"],
            "D_guarded": row["D_guarded"],
            "effective_ratio": row["effective_ratio"],
            "standard_profile": profiles[row["D_base"]],
            "guarded_profile": profiles[row["D_guarded"]],
        } for row in capacity_rows],
    })

  frozen = {
      "schema_version": "capd_stage7_repair_frozen_parameters_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "selection_source": "stage4-f8-f16-r3_calibration",
      "hyperparameters_reselected": False,
      "fixed_parameters": context["config"]["fixed_parameters"],
      "capacity": context["config"]["capacity"],
      "pressure_scan": context["config"]["pressure_scan"],
      "pressure_overhead_claims_allowed": False,
      "local_execution_scope": ["R1", "R2", "R3", "R4"],
      "prohibited_local_stages": context["config"]["prohibited_local_stages"],
      "config_path": _portable(config_path, context["project_root"]),
      "config_sha256": fingerprint_file(config_path),
      "authority": authority,
  }
  standard = {
      "schema_version": "capd_stage7_repair_capacity_standard_v1_0",
      "contract_id": CONTRACT_ID,
      "working_set_definition":
          "unique_pages_in_train_validation_union",
      "capacity_rule": "D_base=ceil(requested_ratio*W_i)",
      "cells": standard_rows,
  }
  guarded = {
      "schema_version": "capd_stage7_repair_capacity_guarded_v1_0",
      "contract_id": CONTRACT_ID,
      "capacity_rule": "D_guarded=max(D_base,64)",
      "guard_min_pages": 64,
      "reserve_fraction_cap": 0.25,
      "clamped_cells_are_not_strict_requested_ratio_experiments": True,
      "cells": guarded_rows,
  }
  stage3_audit = {
      "schema_version": "capd_stage7_repair_stage3_pressure_audit_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "status": "STAGE7_REPAIR_STAGE3_AUDIT_READY",
      "reader_scope": ["train", "validation"],
      "test_accessed": False,
      "policy": "reactive_lru",
      "initial_state": "empty_dram_once_before_train",
      "parameter_selection_performed": False,
      "workloads": audit_workloads,
  }
  values = (
      ("frozen_parameters.json", frozen),
      ("capacity_matrix_standard.json", standard),
      ("capacity_matrix_guarded.json", guarded),
      ("stage3_pressure_audit.json", stage3_audit))
  paths = [raw_audit_path]
  for name, value in values:
    path = os.path.join(output_root, name)
    write_json_atomic(path, value)
    paths.append(path)
  _update_state(output_root, state, "preflight_complete", paths)
  return {"status": "preflight_complete", "output_root": output_root,
          "artifacts": [os.path.basename(path) for path in paths]}


def _verify_r1_identity_artifact(output_root: str,
                                 project_root: str) -> Dict[str, Any]:
  path = os.path.join(output_root, "raw_identity_audit.json")
  audit = load_json(path)
  _require(audit.get("status") == "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED" and
           audit.get("identity_access_only") is True and
           audit.get("policy_metrics_read") is False,
           "R1 raw identity gate is not verified.")
  rows = audit.get("workloads", [])
  _require(len(rows) == 6 and
           {row["workload"] for row in rows} == set(WORKLOADS),
           "R1 must contain the exact six workloads.")
  for row in rows:
    raw_path = _project_file(project_root, row["raw_path"])
    actual = fingerprint_file(raw_path)
    _require(row["raw_sha256_before"] == row["raw_sha256_declared"] ==
             row["raw_sha256_after"] == actual and
             row["raw_trace_unchanged"] is True,
             "R1 raw SHA changed for {}.".format(row["workload"]))
    for role in ("train", "validation", "test"):
      split = row["splits"][role]
      split_path = _project_file(project_root, split["resolved_path"])
      actual_split = fingerprint_file(split_path)
      _require(split["sha256_declared"] == split["sha256_actual"] ==
               actual_split,
               "R1 split SHA changed for {} {}.".format(
                   row["workload"], role))
  return {"workload_count": len(rows), "raw_and_split_sha_unchanged": True,
          "raw_identity_audit_sha256": fingerprint_file(path)}


def _mark_json_nonformal(path: str, status: str) -> None:
  if not os.path.isfile(path):
    return
  value = load_json(path)
  if "fixed_parameters" in value:
    value["candidate_parameters_snapshot"] = value.pop("fixed_parameters")
  value["status"] = status
  value["formal_freeze"] = False
  value["server_consumption_allowed"] = False
  value["supersession_reason"] = "pending_stage3_stage4_parameter_reselection"
  write_json_atomic(path, value)


def _write_r1_pause_artifacts(output_root: str, project_root: str,
                              config: Mapping[str, Any],
                              state: Dict[str, Any]) -> Dict[str, Any]:
  r1 = _verify_r1_identity_artifact(output_root, project_root)
  old_parameter_artifacts = (
      "frozen_parameters.json", "capacity_matrix_standard.json",
      "capacity_matrix_guarded.json", "stage3_pressure_audit.json",
      "pressure_candidates.csv", "pressure_window_manifest.json",
      "pressure_test_lock.json", "local_pressure_bundle_manifest.json")
  for name in (
      "frozen_parameters.json", "capacity_matrix_standard.json",
      "capacity_matrix_guarded.json", "stage3_pressure_audit.json",
      "pressure_window_manifest.json", "pressure_test_lock.json"):
    _mark_json_nonformal(
        os.path.join(output_root, name),
        "exploratory_old_parameter_artifact_not_frozen")
  bundle_path = os.path.join(
      output_root, "local_pressure_bundle_manifest.json")
  if os.path.isfile(bundle_path):
    bundle = load_json(bundle_path)
    bundle.update({
        "status": "revoked_pending_parameter_reselection",
        "formal_pressure_bundle": False,
        "server_consumption_rule": "forbidden",
        "revocation_reason": "R2-R4_not_formally_frozen",
    })
    write_json_atomic(bundle_path, bundle)
  pause = {
      "schema_version": "capd_stage7_repair_pause_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": os.path.basename(output_root),
      "status": "R1_verified_R2_R4_paused",
      "parameter_status": config["parameter_status"],
      "R1": "verified_and_retained",
      "R2": "paused_not_formally_frozen",
      "R3": "paused_not_formally_frozen",
      "R4": "paused_not_formally_frozen",
      "formal_pressure_bundle_export_allowed": False,
      "server_consumption_allowed": False,
      "R5_R11_allowed": False,
      "non_authoritative_old_parameter_artifacts": [
          name for name in old_parameter_artifacts
          if os.path.isfile(os.path.join(output_root, name))],
      "resume_requirement":
          "freeze_new_stage3_stage4_parameters_and_use_a_new_run_id",
  }
  r1_verification = {
      "schema_version": "capd_stage7_repair_r1_verification_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": os.path.basename(output_root),
      "status": "STAGE7_REPAIR_R1_RAW_IDENTITY_VERIFIED",
      "R1": "passed",
      "R2": "paused_not_formally_frozen",
      "R3": "paused_not_formally_frozen",
      "R4": "paused_not_formally_frozen",
      "formal_pressure_bundle_exported": False,
      "R5_R11_executed": False,
      "raw_and_split_sha_unchanged": r1["raw_and_split_sha_unchanged"],
      "workload_count": r1["workload_count"],
      "raw_identity_audit_sha256": r1["raw_identity_audit_sha256"],
  }
  pause_path = os.path.join(output_root, "repair_pause.json")
  r1_path = os.path.join(output_root, "r1_verification.json")
  verification_path = os.path.join(output_root, "verification.json")
  write_json_atomic(pause_path, pause)
  write_json_atomic(r1_path, r1_verification)
  write_json_atomic(verification_path, r1_verification)
  state["phase"] = "r1_verified_r2_r4_paused"
  changed = [
      os.path.join(output_root, "raw_identity_audit.json"), pause_path,
      r1_path, verification_path]
  changed.extend(os.path.join(output_root, name) for name in
                 old_parameter_artifacts
                 if os.path.isfile(os.path.join(output_root, name)))
  for path in changed:
    state.setdefault("artifact_sha256", {})[
        _portable_inside(path, output_root)] = fingerprint_file(path)
  write_json_atomic(_state_path(output_root), state)
  return r1_verification


def pause_after_r1(config_path: str, source_stage7_run: str, run_id: str,
                   project_root: str) -> Dict[str, Any]:
  root = os.path.realpath(project_root)
  config_path = os.path.realpath(config_path)
  source_stage7_run = os.path.realpath(source_stage7_run)
  config = load_json(config_path)
  validate_repair_config(config)
  output_root = repair_output_root(root, run_id)
  _require(os.path.isfile(os.path.join(
      output_root, "raw_identity_audit.json")),
      "R1 audit is missing; run R1 preflight first.")
  manifests = _load_source_manifests(source_stage7_run)
  inputs = _resolve_all_inputs(root, config, manifests)
  snapshot = _source_snapshot(
      root, config_path, source_stage7_run, config, manifests, inputs)
  state = load_json(_state_path(output_root))
  state["input_identity"] = snapshot
  state["input_identity_sha256"] = fingerprint_value(snapshot)
  audit_path = os.path.join(output_root, "raw_identity_audit.json")
  audit = load_json(audit_path)
  audit["input_identity_sha256"] = state["input_identity_sha256"]
  write_json_atomic(audit_path, audit)
  verification = _write_r1_pause_artifacts(
      output_root, root, config, state)
  return {"status": verification["status"], "output_root": output_root,
          "formal_pressure_bundle_exported": False}


CANDIDATE_FIELDS = (
    "workload", "source_trace_id", "requested_ratio", "D_base",
    "D_guarded", "effective_ratio", "guard_applied",
    "source_start_inclusive", "source_end_exclusive",
    "test_relative_start", "test_relative_end", "window_records",
    "unique_pages", "misses", "lru_replacement_decisions",
    "write_count", "write_ratio", "page_entry_count",
    "selection_eligible", "eligibility_reason", "source_raw_sha256",
    "source_split_sha256")


def _capacity_file_label(row: Mapping[str, Any]) -> str:
  return "ratio_{}_D{}".format(
      str(row["requested_ratio"]).replace(".", "p"), row["D_guarded"])


def _scan_required_paths(output_root: str) -> List[str]:
  required = [
      "pressure_candidates.csv", "pressure_window_manifest.json",
      "pressure_test_lock.json"]
  lock_path = os.path.join(output_root, "pressure_test_lock.json")
  if os.path.isfile(lock_path):
    lock = load_json(lock_path)
    for cell in lock.get("cells", []):
      if cell.get("pressure_eligible"):
        required.append(cell["derived_csv"]["path"])
  return required


def run_scan_pressure(config_path: str, source_stage7_run: str, run_id: str,
                      project_root: str) -> Dict[str, Any]:
  run_preflight(config_path, source_stage7_run, run_id, project_root)
  scan_config = load_json(config_path)
  validate_repair_config(scan_config)
  require_formal_parameter_freeze(scan_config)
  context = _prepare_context(
      config_path, source_stage7_run, run_id, project_root)
  output_root = context["output_root"]
  state = context["state"]
  required = _scan_required_paths(output_root)
  if state.get("phase") in ("scan_complete", "bundle_verified") and len(
      required) >= 3 and _artifacts_match(output_root, state, required):
    return {"status": "scan_resumed", "output_root": output_root,
            "artifacts": required}

  guarded_matrix = load_json(os.path.join(
      output_root, "capacity_matrix_guarded.json"))
  capacities_by_workload = defaultdict(list)
  for row in guarded_matrix["cells"]:
    capacities_by_workload[row["workload"]].append(row)
  starts = pressure_candidate_starts(context["config"])
  test_start, test_end = context["config"]["pressure_scan"]["test_interval"]
  window_records = context["config"]["pressure_scan"]["window_records"]
  candidates = []
  source_before = {}
  source_after = {}
  for workload in WORKLOADS:
    item = context["inputs"][workload]
    test = item["splits"]["test"]
    source_before[workload] = {
        "raw_sha256": fingerprint_file(item["raw_path"]),
        "test_split_sha256": fingerprint_file(test["resolved_path"]),
    }
    pages, writes, stats = _read_compact_splits((test["resolved_path"],))
    _require(stats[0]["rows"] == test_end - test_start == test["accesses"],
             "Test row count mismatch for {}.".format(workload))
    for start in starts:
      end = start + window_records
      validate_source_interval(start, end, test_start, test_end)
      relative_start = start - test_start
      relative_end = relative_start + window_records
      window_pages = pages[relative_start:relative_end]
      window_writes = writes[relative_start:relative_end]
      _require(len(window_pages) == window_records,
               "Pressure candidate is shorter than declared window.")
      for capacity in capacities_by_workload[workload]:
        profile = profile_lru_candidate(
            window_pages, window_writes, int(capacity["D_guarded"]))
        eligible_unique = (
            profile["unique_pages"] >
            int(capacity["D_guarded"]) +
            context["config"]["fixed_parameters"]["F_target"])
        eligible_decisions = (
            profile["lru_replacement_decisions"] >=
            context["config"]["pressure_scan"][
                "minimum_lru_replacement_decisions"])
        candidates.append({
            "workload": workload,
            "source_trace_id": item["raw_manifest"]["source_trace_id"],
            "requested_ratio": capacity["requested_ratio"],
            "D_base": capacity["D_base"],
            "D_guarded": capacity["D_guarded"],
            "effective_ratio": capacity["effective_ratio"],
            "guard_applied": capacity["guard_applied"],
            "source_start_inclusive": start,
            "source_end_exclusive": end,
            "test_relative_start": relative_start,
            "test_relative_end": relative_end,
            "window_records": window_records,
            "unique_pages": profile["unique_pages"],
            "misses": profile["misses"],
            "lru_replacement_decisions":
                profile["lru_replacement_decisions"],
            "write_count": profile["write_count"],
            "write_ratio": profile["write_ratio"],
            "page_entry_count": profile["page_entry_count"],
            "selection_eligible": eligible_unique and eligible_decisions,
            "eligibility_reason": (
                "eligible" if eligible_unique and eligible_decisions else
                "unique_pages_not_strictly_greater_than_guard_plus_target"
                if not eligible_unique else
                "lru_replacement_decisions_below_100"),
            "source_raw_sha256": item["raw_sha256"],
            "source_split_sha256": test["sha256"],
        })
    source_after[workload] = {
        "raw_sha256": fingerprint_file(item["raw_path"]),
        "test_split_sha256": fingerprint_file(test["resolved_path"]),
    }
    _require(source_before[workload] == source_after[workload] and
             source_after[workload]["raw_sha256"] == item["raw_sha256"] and
             source_after[workload]["test_split_sha256"] == test["sha256"],
             "Source raw/Test changed during Pressure scan for {}.".format(
                 workload))

  candidates.sort(key=lambda row: (
      WORKLOADS.index(row["workload"]),
      context["config"]["capacity"]["requested_ratios"].index(
          row["requested_ratio"]), row["source_start_inclusive"]))
  _require(len(candidates) == len(WORKLOADS) * 3 * len(starts),
           "Pressure scan did not retain every candidate.")
  candidate_path = os.path.join(output_root, "pressure_candidates.csv")
  write_csv_atomic(candidate_path, candidates, CANDIDATE_FIELDS)

  selection = select_pressure_windows(candidates, context["config"])
  derived_entries = []
  lock_cells = []
  window_cells = []
  for cell in selection["cells"]:
    workload = cell["workload"]
    item = context["inputs"][workload]
    test = item["splits"]["test"]
    window_cell = dict(cell)
    lock_cell = {
        "workload": workload,
        "requested_ratio": cell["requested_ratio"],
        "D_base": cell["D_base"],
        "D_guarded": cell["D_guarded"],
        "effective_ratio": cell["effective_ratio"],
        "pressure_eligible": cell["pressure_eligible"],
        "ineligible_reason": cell["ineligible_reason"],
        "all_policies_use_same_frozen_window": True,
        "server_may_rescan_reselect_or_rederive": False,
    }
    if cell["pressure_eligible"]:
      selected = cell["selected"]
      relative_start = selected["source_start_inclusive"] - test_start
      label = _capacity_file_label(selected)
      derived_path = os.path.join(
          output_root, "derived_pressure", workload, label + ".csv")
      derivation = derive_pressure_csv(
          test["resolved_path"], derived_path, relative_start, window_records)
      verify_derived_rows(
          test["resolved_path"], derived_path, relative_start, window_records)
      derived = {
          "path": _portable_inside(derived_path, output_root),
          "rows": derivation["rows"],
          "sha256": derivation["sha256"],
          "source_trace_id": item["raw_manifest"]["source_trace_id"],
          "source_raw_path": _portable(
              item["raw_path"], context["project_root"]),
          "source_raw_sha256": item["raw_sha256"],
          "source_test_recorded_path": test["recorded_path"],
          "source_test_resolved_path": _portable(
              test["resolved_path"], context["project_root"]),
          "source_split_sha256": test["sha256"],
          "source_start_inclusive": selected["source_start_inclusive"],
          "source_end_exclusive": selected["source_end_exclusive"],
          "test_relative_start": relative_start,
          "test_relative_end": relative_start + window_records,
          "derivation_rule": "binary_line_copy_of_one_contiguous_test_interval",
          "columns_rows_order_and_values_preserved": True,
      }
      derived_entries.append(dict({
          "workload": workload,
          "requested_ratio": cell["requested_ratio"],
          "D_guarded": cell["D_guarded"]}, **derived))
      window_cell["derived_csv"] = derived
      lock_cell["selected_window"] = {
          key: selected[key] for key in (
              "source_start_inclusive", "source_end_exclusive",
              "unique_pages", "misses", "lru_replacement_decisions",
              "write_ratio", "page_entry_count")}
      lock_cell["selection_features"] = cell["selection_features"]
      lock_cell["derived_csv"] = derived
    else:
      window_cell["derived_csv"] = None
      lock_cell["selected_window"] = None
      lock_cell["derived_csv"] = None
      lock_cell["selection_features"] = cell["selection_features"]
    window_cells.append(window_cell)
    lock_cells.append(lock_cell)

  pressure_window_manifest = {
      "schema_version": "capd_stage7_repair_pressure_windows_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "selection_policy": "fixed_reactive_lru_only",
      "test_interval": {"start_inclusive": test_start,
                         "end_exclusive": test_end},
      "window_records": window_records,
      "scan_step": context["config"]["pressure_scan"]["scan_step"],
      "candidate_starts": starts,
      "all_candidates_saved": True,
      "candidate_csv": {
          "path": "pressure_candidates.csv",
          "rows": len(candidates),
          "sha256": fingerprint_file(candidate_path)},
      "selection_features": [
          "reactive_lru_decisions", "unique_pages", "earliest_start"],
      "prohibited_selection_features": list(PROHIBITED_SELECTION_TOKENS),
      "manual_override_allowed": False,
      "cells": window_cells,
  }
  pressure_test_lock = {
      "schema_version": "capd_stage7_repair_pressure_test_lock_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "status": "pressure_test_frozen",
      "test_reader": "fixed_reactive_lru_only",
      "capd_or_oracle_used_for_selection": False,
      "all_policies_use_same_window_per_cell": True,
      "pressure_overhead_claims_allowed": False,
      "overhead": {
          "memory_overhead": None,
          "inference_latency": None,
          "cpu_cycles": None,
          "foreground_blocking_time": None},
      "source_immutability": [{
          "workload": workload,
          "before": source_before[workload],
          "after": source_after[workload],
          "unchanged": source_before[workload] == source_after[workload],
      } for workload in WORKLOADS],
      "cells": lock_cells,
  }
  assert_no_pressure_overhead(pressure_window_manifest)
  assert_no_pressure_overhead(pressure_test_lock)
  window_path = os.path.join(output_root, "pressure_window_manifest.json")
  lock_path = os.path.join(output_root, "pressure_test_lock.json")
  write_json_atomic(window_path, pressure_window_manifest)
  write_json_atomic(lock_path, pressure_test_lock)
  artifact_paths = [candidate_path, window_path, lock_path] + [
      os.path.join(output_root, row["path"].replace("/", os.sep))
      for row in derived_entries]
  _update_state(output_root, state, "scan_complete", artifact_paths)
  return {
      "status": "scan_complete",
      "output_root": output_root,
      "candidate_count": len(candidates),
      "eligible_cells": sum(
          1 for cell in lock_cells if cell["pressure_eligible"]),
      "derived_entries": derived_entries,
  }


def _read_candidate_csv(path: str) -> List[Dict[str, Any]]:
  rows = []
  integer_fields = (
      "D_base", "D_guarded", "source_start_inclusive",
      "source_end_exclusive", "test_relative_start", "test_relative_end",
      "window_records", "unique_pages", "misses",
      "lru_replacement_decisions", "write_count", "page_entry_count")
  float_fields = ("effective_ratio", "write_ratio")
  with open(path, "r", encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle):
      parsed = dict(row)
      for field in integer_fields:
        parsed[field] = int(parsed[field])
      for field in float_fields:
        parsed[field] = float(parsed[field])
      parsed["guard_applied"] = parsed["guard_applied"].lower() == "true"
      parsed["selection_eligible"] = (
          parsed["selection_eligible"].lower() == "true")
      rows.append(parsed)
  return rows


def verify_local_outputs(output_root: str, project_root: str) -> Dict[str, Any]:
  root = os.path.realpath(output_root)
  project_root = os.path.realpath(project_root)
  raw_audit = load_json(os.path.join(root, "raw_identity_audit.json"))
  frozen = load_json(os.path.join(root, "frozen_parameters.json"))
  standard = load_json(os.path.join(root, "capacity_matrix_standard.json"))
  guarded = load_json(os.path.join(root, "capacity_matrix_guarded.json"))
  stage3 = load_json(os.path.join(root, "stage3_pressure_audit.json"))
  window_manifest = load_json(os.path.join(
      root, "pressure_window_manifest.json"))
  pressure_lock = load_json(os.path.join(root, "pressure_test_lock.json"))
  candidates = _read_candidate_csv(os.path.join(
      root, "pressure_candidates.csv"))
  _require(raw_audit.get("status") == "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED" and
           stage3.get("status") == "STAGE7_REPAIR_STAGE3_AUDIT_READY",
           "R1/R3 local gate marker missing.")
  _require(frozen.get("pressure_overhead_claims_allowed") is False and
           frozen.get("prohibited_local_stages") == [
               "R5", "R6", "R7", "R8", "R9", "R10", "R11"],
           "Frozen local/server boundary mismatch.")
  _require(len(standard.get("cells", [])) == 18 and
           len(guarded.get("cells", [])) == 18 and
           len(stage3.get("workloads", [])) == 6,
           "Capacity/Stage-3 matrix dimensions are incomplete.")
  _require(len(candidates) == 918 and
           window_manifest.get("all_candidates_saved") is True,
           "Pressure candidate set must contain all 918 rows.")
  recomputed = select_pressure_windows(candidates, {})
  expected_cells = {(cell["workload"], cell["requested_ratio"]): cell
                    for cell in recomputed["cells"]}
  lock_cells = pressure_lock.get("cells", [])
  _require(len(lock_cells) == 18, "Pressure lock must contain all 18 cells.")
  for cell in lock_cells:
    expected = expected_cells[(cell["workload"], cell["requested_ratio"])]
    _require(cell["pressure_eligible"] == expected["pressure_eligible"],
             "Pressure eligibility differs from fixed selection rule.")
    if cell["pressure_eligible"]:
      selected = cell["selected_window"]
      _require(selected["source_start_inclusive"] ==
               expected["selected"]["source_start_inclusive"] and
               selected["source_end_exclusive"] ==
               expected["selected"]["source_end_exclusive"],
               "Frozen Pressure window differs from fixed ranking.")
      derived = cell["derived_csv"]
      derived_path = os.path.realpath(os.path.join(
          root, derived["path"].replace("/", os.sep)))
      _require(_inside(root, derived_path),
               "Derived Pressure path escapes output root.")
      verify_declared_sha(
          derived_path, derived["sha256"], "derived Pressure CSV")
      source_test = _project_file(
          project_root, derived["source_test_resolved_path"])
      verify_declared_sha(
          source_test, derived["source_split_sha256"], "source Test split")
      verify_derived_rows(
          source_test, derived_path, derived["test_relative_start"],
          derived["rows"])
      _require(derived["rows"] == 100000 and
               derived["source_end_exclusive"] -
               derived["source_start_inclusive"] == 100000 and
               derived["columns_rows_order_and_values_preserved"] is True,
               "Derived Pressure CSV contract mismatch.")
    else:
      _require(cell.get("selected_window") is None and
               cell.get("derived_csv") is None and
               bool(cell.get("ineligible_reason")),
               "Ineligible Pressure cell manufactured a window.")
  for item in raw_audit["workloads"]:
    raw_path = _project_file(project_root, item["raw_path"])
    actual = fingerprint_file(raw_path)
    _require(item["raw_sha256_before"] == item["raw_sha256_after"] ==
             item["raw_sha256_declared"] == actual and
             item["raw_trace_unchanged"] is True,
             "Raw trace changed after local R1-R4 processing.")
    for role in ("train", "validation", "test"):
      split = item["splits"][role]
      path = _project_file(project_root, split["resolved_path"])
      verify_declared_sha(path, split["sha256_declared"],
                          "source {} split".format(role))
  assert_no_pressure_overhead(window_manifest)
  assert_no_pressure_overhead(pressure_lock)
  return {
      "eligible_cells": sum(
          1 for cell in lock_cells if cell["pressure_eligible"]),
      "ineligible_cells": sum(
          1 for cell in lock_cells if not cell["pressure_eligible"]),
      "candidate_count": len(candidates),
      "raw_traces_unchanged": True,
      "derived_csvs_verified": sum(
          1 for cell in lock_cells if cell["pressure_eligible"]),
  }


def export_local_bundle(run_id: str, project_root: str) -> Dict[str, Any]:
  output_root = repair_output_root(project_root, run_id)
  pause_path = os.path.join(output_root, "repair_pause.json")
  if os.path.isfile(pause_path):
    pause = load_json(pause_path)
    _require(pause.get("formal_pressure_bundle_export_allowed") is not False,
             "R2-R4 paused: formal Pressure bundle export is forbidden.")
  state_path = _state_path(output_root)
  _require(os.path.isfile(state_path),
           "Run has no local prepare state; run preflight first.")
  state = load_json(state_path)
  _require(state.get("phase") in ("scan_complete", "bundle_verified"),
           "Pressure scan has not completed.")
  manifest_path = os.path.join(
      output_root, "local_pressure_bundle_manifest.json")
  verification_path = os.path.join(output_root, "verification.json")
  if state.get("phase") == "bundle_verified" and _artifacts_match(
      output_root, state,
      ("local_pressure_bundle_manifest.json", "verification.json")):
    verify_bundle_manifest(manifest_path)
    return {"status": "bundle_resumed", "output_root": output_root,
            "marker": "STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED"}

  local_verification = verify_local_outputs(output_root, project_root)
  required_names = (
      "raw_identity_audit.json", "frozen_parameters.json",
      "capacity_matrix_standard.json", "capacity_matrix_guarded.json",
      "stage3_pressure_audit.json", "pressure_candidates.csv",
      "pressure_window_manifest.json", "pressure_test_lock.json")
  artifact_paths = [os.path.join(output_root, name) for name in required_names]
  pressure_lock = load_json(os.path.join(output_root, "pressure_test_lock.json"))
  derived_entries = []
  for cell in pressure_lock["cells"]:
    if cell["pressure_eligible"]:
      derived = dict(cell["derived_csv"])
      derived.update({
          "workload": cell["workload"],
          "requested_ratio": cell["requested_ratio"],
          "D_base": cell["D_base"],
          "D_guarded": cell["D_guarded"],
          "effective_ratio": cell["effective_ratio"],
      })
      derived_entries.append(derived)
      artifact_paths.append(os.path.join(
          output_root, derived["path"].replace("/", os.sep)))
  manifest = build_bundle_manifest(
      output_root, run_id, artifact_paths, derived_entries)
  frozen = load_json(os.path.join(output_root, "frozen_parameters.json"))
  manifest.update({
      "input_identity_sha256": state["input_identity_sha256"],
      "configuration": {
          "source_path": frozen["config_path"],
          "source_sha256": frozen["config_sha256"],
          "frozen_parameters_path": "frozen_parameters.json",
          "frozen_parameters_sha256": fingerprint_file(os.path.join(
              output_root, "frozen_parameters.json"))},
      "capacity_matrices": {
          "standard": "capacity_matrix_standard.json",
          "guarded": "capacity_matrix_guarded.json"},
      "candidate_statistics": "pressure_candidates.csv",
      "window_lock": "pressure_test_lock.json",
      "server_consumption_rule": "verify_signatures_then_consume_only",
  })
  write_json_atomic(manifest_path, manifest)
  verify_bundle_manifest(manifest_path)
  verification = {
      "schema_version": "capd_stage7_repair_local_verification_v1_0",
      "contract_id": CONTRACT_ID,
      "run_id": run_id,
      "status": "STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED",
      "R1": "passed",
      "R2": "passed",
      "R3": "passed",
      "R4": "passed",
      "candidate_count": local_verification["candidate_count"],
      "eligible_cells": local_verification["eligible_cells"],
      "ineligible_cells": local_verification["ineligible_cells"],
      "derived_csvs_verified": local_verification["derived_csvs_verified"],
      "raw_traces_unchanged": True,
      "pressure_overhead_claims_allowed": False,
      "test_reader": "fixed_reactive_lru_only",
      "capd_or_oracle_used_for_selection": False,
      "executed_stages": ["R1", "R2", "R3", "R4"],
      "not_executed_stages": [
          "R5", "R6", "R7", "R8", "R9", "R10", "R11"],
      "bundle_manifest_sha256": fingerprint_file(manifest_path),
  }
  write_json_atomic(verification_path, verification)
  _update_state(output_root, state, "bundle_verified",
                (manifest_path, verification_path))
  return {"status": "bundle_verified", "output_root": output_root,
          "marker": "STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED",
          "verification": verification}
