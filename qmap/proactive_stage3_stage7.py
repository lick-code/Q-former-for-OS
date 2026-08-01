# coding=utf-8
"""Six-workload Stage-7 calibration for the CAPD active-demotion mechanism.

This namespace is intentionally independent from the historical Stage-3
calibration.  It consumes only the R1-authoritative Stage-7 Train/Validation
splits, profiles chronological windows, and produces a human-review freeze
candidate.  It never opens Test payloads or creates Pressure Test data.
"""

from __future__ import annotations

import collections
import copy
import csv
import datetime
import decimal
import hashlib
import json
import math
import multiprocessing
import os
import statistics
import subprocess
import tempfile
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage3
from qmap import proactive_stage5_policies
from qmap import proactive_stage7_repair


SCHEMA_NAME = "capd_proactive_stage3_stage7_calibration"
SCHEMA_VERSION = "capd_proactive_stage3_stage7_v1_0"
CONTRACT_VERSION = "CAPD-PROACTIVE-STAGE3-STAGE7-1.0"
RESULT_SCHEMA = "capd_proactive_stage3_stage7_result_v1_0"
WORKLOADS = (
    "canneal", "streamcluster_pressure", "dedup_pressure",
    "blackscholes", "swaptions", "fluidanimate")
ALLOWED_SPLITS = ("train", "validation")
ALL_PHASES = ("preflight", "profile", "search", "select", "verify")
REQUIRED_POLICIES = ("reactive_lru", "proactive_lru", "oracle")
FORBIDDEN_PATH_TOKENS = (
    "standard_test_lock", "pressure_test", "stage8", "capd_test",
    "oracle_test")
PROHIBITED_SELECTION_TOKENS = (
    "capd", "oracle", "tpp", "weighted_cost", "stage8",
    "model_accuracy", "policy_result")
BOUNDARY_FLAGS = {
    "test_payload_opened": False,
    "test_used_for_selection": False,
    "stage8_results_used": False,
    "pressure_test_generated": False,
}


class Stage3Stage7Error(ValueError):
  """Raised when a Stage-7 Stage-3 contract or identity gate fails."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage3Stage7Error(message)


def _positive_integer(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
           "{} must be a positive integer.".format(field))
  return int(value)


def _finite_number(value: Any, field: str) -> float:
  _require(isinstance(value, (int, float)) and not isinstance(value, bool),
           "{} must be numeric.".format(field))
  result = float(value)
  _require(math.isfinite(result), "{} must be finite.".format(field))
  return result


def _utc_now() -> str:
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ")


def load_json(path: str) -> Any:
  return proactive_stage3.load_json(path)


def fingerprint_file(path: str) -> str:
  return proactive_stage7_repair.fingerprint_file(path)


def fingerprint_value(value: Any) -> str:
  payload = json.dumps(
      value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
      allow_nan=False).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


def _write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage3-stage7-", suffix=".tmp", dir=directory)
  os.close(fd)
  try:
    proactive_stage3.write_json(temporary, value)
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]],
                      fields: Sequence[str]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage3-stage7-", suffix=".tmp", dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(
          handle, fieldnames=list(fields), extrasaction="ignore",
          lineterminator="\n")
      writer.writeheader()
      for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _append_jsonl(path: str, value: Mapping[str, Any]) -> None:
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  """Validates the full predeclared Stage-7 calibration search contract."""
  _require(isinstance(value, Mapping), "Stage-3 Stage-7 config must be an object.")
  _require(value.get("schema_name") == SCHEMA_NAME, "Unexpected schema_name.")
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Unexpected schema_version.")
  _require(value.get("contract_version") == CONTRACT_VERSION,
           "Unexpected contract_version.")
  _require(tuple(value.get("workloads", ())) == WORKLOADS,
           "The exact six Stage-7 workloads are required.")
  authority = value.get("r1_authority", {})
  _require(authority.get("run_id") == "stage7-repair-r1" and
           authority.get("required_r1_result") == "passed" and
           authority.get("required_status") ==
           "STAGE7_REPAIR_R1_RAW_IDENTITY_VERIFIED",
           "R1 authority contract changed.")
  for field in ("raw_identity_audit_sha256", "verification_sha256",
                "input_identity_sha256"):
    digest = authority.get(field)
    _require(isinstance(digest, str) and len(digest) == 64,
             "Invalid R1 authority {}.".format(field))
  inputs = value.get("input_contract", {})
  _require(tuple(inputs.get("allowed_split_roles", ())) == ALLOWED_SPLITS and
           inputs.get("formal_test") is False and
           inputs.get("page_shift") == 12 and
           inputs.get("chronological") is True and
           inputs.get("shuffle") is False and
           inputs.get("reject_non_r1_sha") is True,
           "Train/Validation-only input contract changed.")
  _require(tuple(inputs.get("forbidden_path_tokens", ())) ==
           FORBIDDEN_PATH_TOKENS, "Forbidden input paths changed.")
  windowing = value.get("windowing", {})
  _require(windowing.get("calibration_window_records") ==
           [100000, 300000, 500000] and
           windowing.get("window_step") == 10000 and
           windowing.get("initial_state") == "empty_dram_per_window" and
           windowing.get("chronological") is True and
           windowing.get("shuffle") is False and
           windowing.get("train_block_count") >= 2,
           "Window/blocked calibration contract changed.")
  _require(value.get("working_set_reference", {}).get("quantiles") ==
           [0.50, 0.75, 0.90], "W_ref quantiles changed.")
  _require(value.get("standard_capacity", {}).get("ratios") ==
           [0.20, 0.40, 0.60], "Standard capacity ratios changed.")
  pressure = value.get("pressure_capacity", {})
  _require(pressure.get("ratios") == [0.05, 0.10, 0.15, 0.20] and
           pressure.get("minimum_capacity_pages") == 8 and
           pressure.get("D_guard_min_64_used") is False,
           "Pressure capacity contract changed.")
  watermark = value.get("watermark_search", {})
  _require(watermark.get("alpha_candidates") == [0.05, 0.10, 0.15, 0.20]
           and watermark.get("beta_candidates") == [0.4, 0.5, 0.6] and
           watermark.get("maximum_reserve_fraction") == 0.25,
           "Dynamic watermark grid changed.")
  _require(value.get("controller_search", {}).get("b_max_candidates") ==
           [1, 2, 4, 8], "b_max candidates changed.")
  fixed = value.get("fixed_stage3", {})
  _require(fixed.get("candidate_size_K") == 8 and
           fixed.get("cost_profile") == {
               "dram_hit": 1, "nvm_read": 2,
               "nvm_write": 8, "demotion": 10},
           "Stage-3 fixed K/cost changed.")
  _require(fixed.get("oracle_evaluation") == {
      "scope": "candidate_scoped_optimization_upper_bound_only",
      "lookahead_records": 256, "label_weights": [1, 1, 2],
      "used_for_pressure_window_selection": False},
      "Oracle evaluation contract changed.")
  _require(set(value.get("search_space", {})) == {
      "window_records", "W_ref_quantile", "r_pressure", "alpha", "beta",
      "b_max"}, "Stage 3 may search only mechanism parameters.")
  policies = value.get("policy_audit", {})
  _require(tuple(policies.get("required_policies", ())) == REQUIRED_POLICIES
           and policies.get("oracle_used_for_window_selection") is False and
           policies.get("all_candidate_window_statistics_saved") is True,
           "Required policy audit changed.")
  provenance = value.get("provenance", {})
  for field in (
      "test_payload_allowed", "test_used_for_selection",
      "stage8_results_used", "pressure_test_generated",
      "capd_or_oracle_used_for_pressure_selection",
      "pressure_overhead_claims_allowed", "stage4_allowed",
      "model_training_allowed"):
    _require(provenance.get(field) is False,
             "{} must remain false.".format(field))
  _require(value.get("selection", {}).get("all_auto_freeze") is False and
           value.get("selection", {}).get("human_review_required") is True,
           "all must never auto-freeze.")
  execution = value.get("execution", {})
  _require(isinstance(execution.get("profile_workers"), int) and
           not isinstance(execution.get("profile_workers"), bool) and
           1 <= execution["profile_workers"] <= len(WORKLOADS) and
           execution.get("profile_checkpoint_granularity") == "window" and
           execution.get("search_in_memory_cache") is True,
           "Bounded profile/checkpoint execution contract changed.")
  return value


def _walk(value: Any) -> Iterable[Tuple[Optional[str], Any]]:
  if isinstance(value, Mapping):
    for key, item in value.items():
      yield str(key), item
      for nested in _walk(item):
        yield nested
  elif isinstance(value, (list, tuple)):
    for item in value:
      for nested in _walk(item):
        yield nested


def reject_forbidden_input(value: Any) -> None:
  """Rejects Test roles, Test-derived results, Stage 8, and Pressure inputs."""
  _require(isinstance(value, Mapping), "Input declaration must be an object.")
  for key, item in _walk(value):
    normalized_key = "" if key is None else key.lower()
    if normalized_key in ("split", "split_role", "role"):
      _require(str(item).lower() != "test", "Stage 3 rejects split_role=test.")
    if normalized_key == "formal_test":
      _require(item is False, "Stage 3 rejects formal_test=true.")
    if isinstance(item, str):
      normalized = item.replace("\\", "/").lower()
      if any(token in normalized for token in FORBIDDEN_PATH_TOKENS):
        raise Stage3Stage7Error(
            "Forbidden Stage-3 input dependency: {}.".format(item))


def _verify_sha(path: str, expected: str, label: str) -> str:
  _require(os.path.isfile(path), "Missing {}: {}.".format(label, path))
  actual = fingerprint_file(path)
  _require(actual == expected,
           "{} SHA256 mismatch: expected {}, got {}.".format(
               label, expected, actual))
  return actual


def _project_path(project_root: str, recorded: str) -> str:
  _require(isinstance(recorded, str) and recorded and
           not os.path.isabs(recorded), "Authority path must be repository-relative.")
  resolved = os.path.realpath(os.path.join(
      os.path.realpath(project_root), recorded.replace("/", os.sep)))
  try:
    inside = os.path.commonpath((os.path.realpath(project_root), resolved)) == (
        os.path.realpath(project_root))
  except ValueError:
    inside = False
  _require(inside, "Authority path escapes project root.")
  return resolved


def manifest_from_r1_authority(
    authority: Mapping[str, Any], config: Mapping[str, Any],
    project_root: Optional[str] = None, verify_files: bool = True
) -> Dict[str, Any]:
  """Builds a 12-entry manifest without copying or traversing Test entries."""
  validate_config(config)
  _require(authority.get("run_id") == config["r1_authority"]["run_id"] and
           authority.get("status") == "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED"
           and authority.get("identity_access_only") is True and
           authority.get("policy_metrics_read") is False and
           authority.get("input_identity_sha256") ==
           config["r1_authority"]["input_identity_sha256"],
           "R1 raw identity authority did not pass.")
  by_workload = {
      row.get("workload"): row for row in authority.get("workloads", [])}
  _require(tuple(row.get("workload") for row in authority.get("workloads", []))
           == WORKLOADS, "R1 workload authority/order changed.")
  entries = []
  for workload in WORKLOADS:
    item = by_workload[workload]
    _require(item.get("page_shift") == 12, "R1 page_shift changed.")
    splits = item.get("splits", {})
    for split_role in ALLOWED_SPLITS:
      split = splits.get(split_role, {})
      expected_accesses = 1800000 if split_role == "train" else 600000
      interval = split.get("interval", {})
      expected_start = 0 if split_role == "train" else 1800000
      expected_end = 1800000 if split_role == "train" else 2400000
      declared = split.get("sha256_declared")
      actual = split.get("sha256_actual")
      _require(declared == actual and isinstance(declared, str) and
               len(declared) == 64, "R1 split SHA chain mismatch.")
      _require(split.get("accesses") == expected_accesses and
               interval.get("start_inclusive") == expected_start and
               interval.get("end_exclusive") == expected_end,
               "R1 split interval/access count changed.")
      recorded_path = split.get("recorded_path")
      entry = {
          "workload": workload,
          "split_role": split_role,
          "formal_test": False,
          "trace_path": recorded_path,
          "sha256": declared,
          "accesses": expected_accesses,
          "source_interval": {
              "start_inclusive": expected_start,
              "end_exclusive": expected_end},
          "page_shift": 12,
          "source_trace_id": item.get("source_trace_id"),
          "r1_input_identity_sha256": authority["input_identity_sha256"],
      }
      reject_forbidden_input(entry)
      if verify_files:
        _require(project_root is not None, "project_root is required.")
        resolved = proactive_stage7_repair.resolve_recorded_split(
            project_root, recorded_path, declared)
        _verify_sha(resolved, declared,
                    "{} {} split".format(workload, split_role))
        entry["resolved_trace_path"] = os.path.relpath(
            resolved, os.path.realpath(project_root)).replace(os.sep, "/")
      entries.append(entry)
  result = {
      "schema_version": "capd_proactive_stage3_stage7_input_manifest_v1_0",
      "run_id": config["default_run_id"],
      "source_authority_run_id": authority["run_id"],
      "source_authority_input_identity_sha256":
          authority["input_identity_sha256"],
      "allowed_split_roles": list(ALLOWED_SPLITS),
      "test_entries": 0,
      "formal_test": False,
      "chronological": True,
      "shuffle": False,
      "entries": entries,
  }
  validate_input_manifest(result, authority)
  return result


def validate_input_manifest(
    manifest: Mapping[str, Any], authority: Optional[Mapping[str, Any]] = None
) -> Mapping[str, Any]:
  reject_forbidden_input(manifest)
  _require(manifest.get("schema_version") ==
           "capd_proactive_stage3_stage7_input_manifest_v1_0",
           "Unexpected Stage-3 Stage-7 manifest schema.")
  entries = manifest.get("entries", [])
  _require(len(entries) == len(WORKLOADS) * 2,
           "Manifest must contain 6 Train + 6 Validation entries.")
  seen = set()
  authority_sha = {}
  if authority is not None:
    for item in authority.get("workloads", []):
      for split in ALLOWED_SPLITS:
        authority_sha[(item["workload"], split)] = item["splits"][split][
            "sha256_declared"]
  for entry in entries:
    identity = (entry.get("workload"), entry.get("split_role"))
    _require(identity[0] in WORKLOADS and identity[1] in ALLOWED_SPLITS and
             identity not in seen, "Invalid or duplicate manifest entry.")
    seen.add(identity)
    _require(entry.get("formal_test") is False and
             entry.get("page_shift") == 12,
             "Manifest entry violates Train/Validation contract.")
    if authority is not None:
      _require(entry.get("sha256") == authority_sha.get(identity),
               "Manifest split SHA is outside the R1 authority chain.")
  _require(seen == {(workload, split) for workload in WORKLOADS
                    for split in ALLOWED_SPLITS},
           "Manifest workload/split matrix is incomplete.")
  return manifest


def build_window_descriptors(
    split_role: str, split_records: int, window_records: Sequence[int],
    step: int, block_count: int
) -> List[Dict[str, Any]]:
  _require(split_role in ALLOWED_SPLITS, "Windows may use only Train/Validation.")
  length = _positive_integer(split_records, "split_records")
  scan_step = _positive_integer(step, "window_step")
  blocks = _positive_integer(block_count, "block_count")
  _require(length % blocks == 0,
           "Split length must divide evenly into chronological blocks.")
  block_size = length // blocks
  rows = []
  for block_index in range(blocks):
    block_start = block_index * block_size
    block_end = block_start + block_size
    for size in window_records:
      size = _positive_integer(size, "window_records")
      if size > block_size:
        continue
      for start in range(block_start, block_end - size + 1, scan_step):
        end = start + size
        rows.append({
            "split_role": split_role,
            "block_index": block_index,
            "block_start_record": block_start,
            "block_end_record": block_end,
            "window_records": size,
            "start_record": start,
            "end_record": end,
            "chronological": True,
            "shuffle": False,
            "initial_state": "empty_dram_per_window",
            "crosses_split_boundary": not (
                block_start <= start < end <= block_end),
        })
  return rows


def profile_task_plan(
    manifest: Mapping[str, Any], config: Mapping[str, Any]
) -> Dict[str, Any]:
  """Builds the complete profile task count from manifest metadata only."""
  entries = {
      (row["workload"], row["split_role"]): row
      for row in manifest["entries"]}
  workloads = []
  total_windows = 0
  for workload in WORKLOADS:
    window_count = 0
    split_counts = {}
    for split_role in ALLOWED_SPLITS:
      entry = entries.get((workload, split_role))
      _require(entry is not None, "Profile task plan lacks a split entry.")
      block_count = config["windowing"][
          "train_block_count" if split_role == "train" else
          "validation_block_count"]
      count = len(build_window_descriptors(
          split_role, int(entry["accesses"]),
          config["windowing"]["calibration_window_records"],
          config["windowing"]["window_step"], block_count))
      split_counts[split_role] = count
      window_count += count
    total_windows += window_count
    workloads.append({
        "workload": workload, "split_window_counts": split_counts,
        "window_count": window_count,
        "base_task_count": window_count,
        "capacity_task_count": window_count,
        "total_task_count": 2 * window_count})
  return {
      "workloads": workloads, "total_window_count": total_windows,
      "total_task_count": 2 * total_windows}


def nearest_rank(values: Sequence[int], quantile: float) -> Optional[int]:
  if not values:
    return None
  q = _finite_number(quantile, "quantile")
  _require(0 < q <= 1, "quantile must lie in (0,1].")
  ordered = sorted(int(value) for value in values)
  return ordered[max(1, int(math.ceil(q * len(ordered)))) - 1]


def _ceil_product(value: int, ratio: float) -> int:
  return int((decimal.Decimal(value) * decimal.Decimal(str(ratio))).to_integral_value(
      rounding=decimal.ROUND_CEILING))


def standard_capacity_rows(
    workload: str, union_pages: int, ratios: Sequence[float]
) -> List[Dict[str, Any]]:
  pages = _positive_integer(union_pages, "union_pages")
  return [{
      "workload": workload,
      "working_set_definition": "unique_pages_in_train_validation_union",
      "working_set_pages": pages,
      "requested_ratio": float(ratio),
      "D_standard": _ceil_product(pages, float(ratio)),
      "rounding": "ceiling",
  } for ratio in ratios]


def pressure_capacity_row(
    workload: str, W_ref: int, quantile: float, ratio: float,
    window_records: Optional[int] = None
) -> Dict[str, Any]:
  pages = _positive_integer(W_ref, "W_ref")
  q = _finite_number(quantile, "W_ref_quantile")
  r = _finite_number(ratio, "requested_ratio")
  _require(q in (0.50, 0.75, 0.90), "Unsupported W_ref quantile.")
  _require(r in (0.05, 0.10, 0.15, 0.20),
           "Pressure ratio must be 5/10/15/20 percent.")
  raw = _ceil_product(pages, r)
  resolved = max(8, raw)
  return {
      "workload": workload,
      "window_records": window_records,
      "W_ref_quantile": q,
      "W_ref": pages,
      "requested_ratio": r,
      "D_pressure_raw": raw,
      "D_pressure": resolved,
      "minimum_capacity_applied": resolved != raw,
      "minimum_capacity_pages": 8,
      "D_guard_min_64_used": False,
  }


def _round_half_up(value: float) -> int:
  return int(decimal.Decimal(str(value)).to_integral_value(
      rounding=decimal.ROUND_HALF_UP))


def dynamic_watermark(D: int, alpha: float, beta: float) -> Dict[str, Any]:
  capacity = _positive_integer(D, "D")
  alpha_value = _finite_number(alpha, "alpha")
  beta_value = _finite_number(beta, "beta")
  _require(alpha_value in (0.05, 0.10, 0.15, 0.20), "Unsupported alpha.")
  _require(beta_value in (0.4, 0.5, 0.6), "Unsupported beta.")
  target = max(2, min(16, _round_half_up(alpha_value * capacity)))
  low = max(1, _round_half_up(beta_value * target))
  if low >= target:
    low = target - 1
  _require(1 <= low < target < capacity,
           "Dynamic watermark is illegal for D={} alpha={} beta={}.".format(
               capacity, alpha_value, beta_value))
  reserve = target / float(capacity)
  _require(reserve <= 0.25,
           "Dynamic F_target/D exceeds the 25 percent reserve cap.")
  return {
      "D": capacity, "alpha": alpha_value, "beta": beta_value,
      "F_low": low, "F_target": target,
      "reserve_fraction": reserve,
      "F_target_over_D": reserve,
      "rounding": "decimal_round_half_up_then_clamp",
  }


def compute_b_t(F_low: int, F_target: int, free_frames: int,
                b_max: int, candidate_count: int) -> int:
  del F_low
  target = _positive_integer(F_target, "F_target")
  batch = _positive_integer(b_max, "b_max")
  candidates = int(candidate_count)
  _require(candidates >= 0, "candidate_count cannot be negative.")
  free = int(free_frames)
  result = min(batch, max(0, target - free), candidates)
  _require(0 <= result <= batch and result <= max(0, target - free) and
           result <= candidates, "b_t bounds failed.")
  return result


def pressure_eligibility(
    unique_pages: int, D_pressure: int, F_target: int,
    lru_replacement_decisions: int, split_boundary_valid: bool = True
) -> List[str]:
  reasons = []
  if not split_boundary_valid:
    reasons.append("split_boundary_violation")
  if not (isinstance(D_pressure, int) and isinstance(F_target, int) and
          1 <= F_target < D_pressure and F_target / float(D_pressure) <= 0.25):
    reasons.append("invalid_capacity_or_watermark")
  if int(unique_pages) <= int(D_pressure) + int(F_target):
    reasons.append("unique_pages_not_greater_than_D_plus_F_target")
  if int(lru_replacement_decisions) < 100:
    reasons.append("lru_replacement_decisions_below_100")
  return reasons or ["eligible"]


def _reject_selection_metrics(rows: Sequence[Mapping[str, Any]]) -> None:
  allowed = {
      "workload", "split_role", "block_index", "window_records",
      "start_record", "end_record", "unique_pages", "misses",
      "lru_misses", "lru_replacement_decisions", "page_entry_count",
      "write_ratio", "eligible", "eligibility_reasons", "D_pressure",
      "F_low", "F_target"}
  for row in rows:
    for field in row:
      normalized = str(field).lower()
      if field not in allowed and any(
          token in normalized for token in PROHIBITED_SELECTION_TOKENS):
        raise Stage3Stage7Error(
            "Forbidden pressure-window selection metric: {}.".format(field))


def choose_reactive_sentinels(
    rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Optional[Dict[str, Any]]]:
  _reject_selection_metrics(rows)
  values = [dict(row) for row in rows]
  eligible = [row for row in values if row.get("eligible") is True]
  eligible.sort(key=lambda row: (
      -int(row["lru_replacement_decisions"]),
      -int(row["unique_pages"]), int(row["start_record"])))
  low_pressure = [row for row in values if row.get("eligible") is not True]
  low_pressure.sort(key=lambda row: (
      int(row["lru_replacement_decisions"]), int(row["unique_pages"]),
      int(row["start_record"])))
  return {
      "pressure": eligible[0] if eligible else None,
      "low_pressure": low_pressure[0] if low_pressure else None,
      "selection_features": [
          "reactive_lru_replacement_decisions", "unique_pages",
          "earliest_start"],
      "capd_or_oracle_used": False,
  }


def oracle_headroom_gate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  values = [max(0.0, float(row.get("oracle_headroom", 0.0))) for row in rows]
  passed = bool(values) and any(value > 0 for value in values)
  return {
      "passed": passed,
      "stage4_candidate_allowed": passed,
      "qualified_window_count": len(values),
      "positive_headroom_window_count": sum(value > 0 for value in values),
      "total_oracle_headroom": sum(values),
      "reason": (
          "nonzero_oracle_optimization_space_confirmed" if passed else
          "all_qualified_windows_have_zero_oracle_headroom"),
  }


def validation_safety_gate(
    reactive: Mapping[str, Any], proactive: Mapping[str, Any],
    rule: Mapping[str, Any]
) -> Dict[str, Any]:
  reasons = []
  proactive_demotions = int(proactive.get("proactive_demotions", 0))
  page_entries = max(1, int(reactive.get("page_enter_dram_count", 0)))
  pointless_limit = max(
      int(rule["maximum_pointless_demotion_count"]),
      int(math.floor(
          float(rule["maximum_pointless_demotion_fraction_of_page_entries"])
          * page_entries)))
  low_pressure = int(reactive.get("reactive_demotions", 0)) < int(
      rule["low_pressure_replacement_decisions_below"])
  if low_pressure and proactive_demotions > pointless_limit:
    reasons.append("meaningless_proactive_demotions")
  cost_delta = (
      float(proactive["default_weighted_cost"]) -
      float(reactive["default_weighted_cost"]))
  if cost_delta > float(rule["maximum_weighted_cost_delta"]):
    reasons.append("weighted_cost_regression")
  early = proactive.get("early_reuse_rate")
  if early is not None and float(early) > float(
      rule["maximum_early_reuse_ratio"]):
    reasons.append("high_early_reuse")
  dram_hit_delta = int(proactive.get("dram_hits", 0)) - int(
      reactive.get("dram_hits", 0))
  if dram_hit_delta < int(rule["minimum_dram_hit_delta"]):
    reasons.append("normal_dram_residency_degraded")
  return {
      "passed": not reasons,
      "low_pressure": low_pressure,
      "reasons": reasons or ["validation_safety_passed"],
      "weighted_cost_delta": cost_delta,
      "dram_hit_delta": dram_hit_delta,
      "proactive_demotions": proactive_demotions,
      "pointless_demotion_limit": pointless_limit,
      "early_reuse_ratio": early,
  }


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
  minimize = (
      "weighted_cost_delta", "early_reuse_ratio",
      "proactive_demotion_count")
  maximize = (
      "empty_frame_exhaustion_reduction", "minimum_free_frames",
      "oracle_headroom_utilization", "pressure_coverage")
  weak = all(float(left[field]) <= float(right[field]) for field in minimize)
  weak = weak and all(
      float(left[field]) >= float(right[field]) for field in maximize)
  strict = any(float(left[field]) < float(right[field]) for field in minimize)
  strict = strict or any(
      float(left[field]) > float(right[field]) for field in maximize)
  return weak and strict


def pareto_frontier(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
  eligible = [dict(row) for row in rows
              if row.get("validation_safety_passed") is True]
  result = []
  for row in eligible:
    if not any(_dominates(other, row) for other in eligible
               if other["candidate_id"] != row["candidate_id"]):
      result.append(row)
  return sorted(result, key=lambda item: item["candidate_id"])


def _nullable_high(value: Any) -> float:
  return float("inf") if value is None else float(value)


def select_from_frontier(
    rows: Sequence[Mapping[str, Any]], rule: Mapping[str, Any]
) -> Dict[str, Any]:
  del rule
  _require(rows, "No Pareto candidate passed all Stage-3 gates.")
  ordered = sorted(rows, key=lambda row: (
      -int(bool(row["validation_safety_passed"])),
      -float(row["pressure_coverage"]),
      float(row["weighted_cost_delta"]),
      -float(row["empty_frame_exhaustion_reduction"]),
      -float(row["minimum_free_frames"]),
      _nullable_high(row.get("early_reuse_ratio")),
      float(row["proactive_demotion_count"]),
      -float(row.get("oracle_headroom_utilization", 0.0)),
      str(row["candidate_id"])))
  result = copy.deepcopy(ordered[0])
  result["tie_break_rank"] = 1
  return result


def verification_boundary() -> Dict[str, bool]:
  return dict(BOUNDARY_FLAGS)


def assert_no_forbidden_result_dependency(value: Any) -> None:
  for key, item in _walk(value):
    normalized = "" if key is None else key.lower()
    if normalized in BOUNDARY_FLAGS:
      _require(item is False, "{} must remain false.".format(key))
    if normalized in (
        "test_results", "capd_test_results", "oracle_test_results",
        "stage8_results"):
      raise Stage3Stage7Error(
          "Forbidden result dependency: {}.".format(key))


def run_identity_payload(
    run_id: str, config_sha: str, authority_sha: str,
    input_shas: Sequence[str], code_shas: Sequence[str]
) -> Dict[str, Any]:
  return {
      "schema_version": "capd_proactive_stage3_stage7_run_identity_v1_0",
      "run_id": run_id,
      "config_sha256": config_sha,
      "r1_authority_sha256": authority_sha,
      "input_sha256": sorted(str(value) for value in input_shas),
      "code_sha256": sorted(str(value) for value in code_shas),
  }


def require_freeze_confirmation(confirmed: bool, candidate_path: str) -> None:
  _require(bool(confirmed),
           "freeze requires --confirm-stage3-stage7-freeze.")
  _require(isinstance(candidate_path, str) and candidate_path,
           "freeze requires an explicit candidate file.")


def build_pressure_contract_candidate(
    selected: Mapping[str, Any], config: Mapping[str, Any]
) -> Dict[str, Any]:
  validate_config(config)
  return {
      "schema_version":
          "capd_proactive_stage3_stage7_pressure_contract_candidate_v1_0",
      "status": "candidate_requires_human_review",
      "selected_window_records": selected["selected_window_records"],
      "scan_step": config["windowing"]["window_step"],
      "working_set_definition":
          config["working_set_reference"]["definition"],
      "W_ref_quantile": selected["W_ref_quantile"],
      "standard_capacity_matrix": selected["standard_capacity_matrix"],
      "pressure_capacity_matrix": selected["pressure_capacity_matrix"],
      "watermark_rule": {
          "F_target": config["watermark_search"]["F_target_rule"],
          "F_low": config["watermark_search"]["F_low_rule"],
          "maximum_F_target_over_D": 0.25,
          "actual_by_capacity": selected["watermarks"]},
      "b_max": selected["b_max"],
      "pressure_eligibility_rule": copy.deepcopy(
          config["pressure_eligibility"]),
      "selection_policy": "fixed_reactive_lru_only",
      "capd_or_oracle_used_for_pressure_selection": False,
      "pressure_overhead_claims_allowed": False,
      "test_used_for_stage3_selection": False,
      "pressure_test_generated": False,
  }


class _TraceView(Sequence[Mapping[str, Any]]):
  """Zero-copy random-access view over one compact trace window."""

  def __init__(self, trace: Sequence[Mapping[str, Any]], start: int, end: int):
    _require(0 <= start < end <= len(trace), "Trace view is out of bounds.")
    self.trace = trace
    self.start = int(start)
    self.end = int(end)

  def __len__(self) -> int:
    return self.end - self.start

  def __getitem__(self, index):
    if isinstance(index, slice):
      start, stop, step = index.indices(len(self))
      return [self.trace[self.start + value]
              for value in range(start, stop, step)]
    if index < 0:
      index += len(self)
    if not 0 <= index < len(self):
      raise IndexError(index)
    return self.trace[self.start + index]


def _growth_summary(pages: Sequence[int], sample_records: int) -> Dict[str, Any]:
  step = _positive_integer(sample_records, "growth_sample_records")
  seen = set()
  samples = []
  for index, page in enumerate(pages, start=1):
    seen.add(int(page))
    if index % step == 0 or index == len(pages):
      samples.append({"records": index, "unique_pages": len(seen)})
  increments = [
      samples[index]["unique_pages"] - samples[index - 1]["unique_pages"]
      for index in range(1, len(samples))]
  return {
      "sample_records": step,
      "samples": samples,
      "mean_new_unique_pages_per_sample": (
          statistics.mean(increments) if increments else 0.0),
      "maximum_new_unique_pages_per_sample": max(increments or [0]),
  }


def _reuse_distance_summary(pages: Sequence[int]) -> Dict[str, Any]:
  last = {}
  distances = []
  cold = 0
  for index, page in enumerate(pages):
    page = int(page)
    if page in last:
      distances.append(index - last[page])
    else:
      cold += 1
    last[page] = index
  return {
      "cold_page_accesses": cold,
      "reuse_count": len(distances),
      "p50": nearest_rank(distances, 0.50),
      "p90": nearest_rank(distances, 0.90),
      "p99": nearest_rank(distances, 0.99),
      "maximum": max(distances) if distances else None,
  }


def _reactive_lru_profile(
    trace: Sequence[Mapping[str, Any]], dram_capacity_pages: int,
    burst_records: int
) -> Dict[str, Any]:
  """Profiles Reactive-LRU with the same empty-DRAM semantics as Replay."""
  capacity = _positive_integer(dram_capacity_pages, "dram_capacity_pages")
  resident = collections.OrderedDict()
  dirty = {}
  unique = set()
  misses = 0
  replacements = 0
  dram_hits = 0
  nvm_reads = 0
  nvm_writes = 0
  write_count = 0
  free_sum = 0
  min_free = capacity
  exhaustion = 0
  enter_flags = []
  for access in trace:
    page = int(access["page"])
    write = bool(access["rw"])
    unique.add(page)
    write_count += int(write)
    entered = page not in resident
    if not entered:
      dram_hits += 1
      resident.move_to_end(page)
      dirty[page] = dirty.get(page, False) or write
    else:
      misses += 1
      if write:
        nvm_writes += 1
      else:
        nvm_reads += 1
      if len(resident) >= capacity:
        victim, _ = resident.popitem(last=False)
        dirty.pop(victim, None)
        replacements += 1
        exhaustion += 1
      resident[page] = None
      dirty[page] = write
    enter_flags.append(entered)
    free = capacity - len(resident)
    min_free = min(min_free, free)
    free_sum += free
  burst_size = _positive_integer(burst_records, "burst_records")
  bursts = [
      sum(1 for value in enter_flags[start:start + burst_size] if value)
      for start in range(0, len(enter_flags), burst_size)]
  weighted = (
      dram_hits + 2 * nvm_reads + 8 * nvm_writes + 10 * replacements)
  return {
      "policy": "reactive_lru",
      "initial_state": "empty_dram_per_window",
      "dram_capacity_pages": capacity,
      "unique_pages": len(unique),
      "total_accesses": len(trace),
      "dram_hits": dram_hits,
      "nvm_reads": nvm_reads,
      "nvm_writes": nvm_writes,
      "misses": misses,
      "lru_misses": misses,
      "lru_replacement_decisions": replacements,
      "reactive_demotions": replacements,
      "page_entry_count": misses,
      "page_entry_burst": {
          "records": burst_size,
          "p95": nearest_rank(bursts, 0.95),
          "p99": nearest_rank(bursts, 0.99),
          "maximum": max(bursts or [0])},
      "write_ratio": write_count / float(len(trace)),
      "minimum_free_frames": min_free,
      "mean_free_frames": free_sum / float(len(trace)),
      "empty_frame_exhaustion": exhaustion,
      "proactive_demotions": 0,
      "early_reuse_count": 0,
      "early_reuse_rate": None,
      "default_weighted_cost": weighted,
  }


def _window_profile(
    trace: Sequence[Mapping[str, Any]], descriptor: Mapping[str, Any],
    reference_capacity: int, config: Mapping[str, Any]
) -> Dict[str, Any]:
  view = _TraceView(trace, descriptor["start_record"], descriptor["end_record"])
  capacity = _positive_integer(reference_capacity, "reference_capacity")
  burst_size = _positive_integer(
      config["windowing"]["page_entry_burst_records"],
      "page_entry_burst_records")
  growth_step = _positive_integer(
      config["windowing"]["working_set_growth_sample_records"],
      "working_set_growth_sample_records")
  resident = collections.OrderedDict()
  dirty = {}
  unique = set()
  last = {}
  reuse_distances = []
  cold = 0
  misses = 0
  replacements = 0
  dram_hits = 0
  nvm_reads = 0
  nvm_writes = 0
  write_count = 0
  free_sum = 0
  min_free = capacity
  exhaustion = 0
  burst_entries = 0
  bursts = []
  growth_samples = []
  for index in range(len(view)):
    access = view[index]
    page = int(access["page"])
    write = bool(access["rw"])
    previous = last.get(page)
    if previous is None:
      cold += 1
    else:
      reuse_distances.append(index - previous)
    last[page] = index
    unique.add(page)
    write_count += int(write)
    entered = page not in resident
    if entered:
      misses += 1
      burst_entries += 1
      if write:
        nvm_writes += 1
      else:
        nvm_reads += 1
      if len(resident) >= capacity:
        victim, _ = resident.popitem(last=False)
        dirty.pop(victim, None)
        replacements += 1
        exhaustion += 1
      resident[page] = None
      dirty[page] = write
    else:
      dram_hits += 1
      resident.move_to_end(page)
      dirty[page] = dirty.get(page, False) or write
    free = capacity - len(resident)
    min_free = min(min_free, free)
    free_sum += free
    record_count = index + 1
    if record_count % burst_size == 0 or record_count == len(view):
      bursts.append(burst_entries)
      burst_entries = 0
    if record_count % growth_step == 0 or record_count == len(view):
      growth_samples.append({
          "records": record_count, "unique_pages": len(unique)})
  growth_increments = [
      growth_samples[index]["unique_pages"] -
      growth_samples[index - 1]["unique_pages"]
      for index in range(1, len(growth_samples))]
  ordered_reuse = sorted(reuse_distances)

  def reuse_quantile(quantile: float) -> Optional[int]:
    if not ordered_reuse:
      return None
    rank = max(1, int(math.ceil(quantile * len(ordered_reuse))))
    return ordered_reuse[rank - 1]

  weighted = (
      dram_hits + 2 * nvm_reads + 8 * nvm_writes + 10 * replacements)
  result = {
      "policy": "reactive_lru",
      "initial_state": "empty_dram_per_window",
      "dram_capacity_pages": capacity,
      "unique_pages": len(unique),
      "total_accesses": len(view),
      "dram_hits": dram_hits,
      "nvm_reads": nvm_reads,
      "nvm_writes": nvm_writes,
      "misses": misses,
      "lru_misses": misses,
      "lru_replacement_decisions": replacements,
      "reactive_demotions": replacements,
      "page_entry_count": misses,
      "page_entry_burst": {
          "records": burst_size,
          "p95": nearest_rank(bursts, 0.95),
          "p99": nearest_rank(bursts, 0.99),
          "maximum": max(bursts or [0])},
      "write_ratio": write_count / float(len(view)),
      "minimum_free_frames": min_free,
      "mean_free_frames": free_sum / float(len(view)),
      "empty_frame_exhaustion": exhaustion,
      "proactive_demotions": 0,
      "early_reuse_count": 0,
      "early_reuse_rate": None,
      "default_weighted_cost": weighted,
  }
  result.update(copy.deepcopy(descriptor))
  result.update({
      "reuse_distance_summary": {
          "cold_page_accesses": cold,
          "reuse_count": len(reuse_distances),
          "p50": reuse_quantile(0.50),
          "p90": reuse_quantile(0.90),
          "p99": reuse_quantile(0.99),
          "maximum": ordered_reuse[-1] if ordered_reuse else None,
      },
      "working_set_growth": {
          "sample_records": growth_step,
          "samples": growth_samples,
          "mean_new_unique_pages_per_sample": (
              statistics.mean(growth_increments)
              if growth_increments else 0.0),
          "maximum_new_unique_pages_per_sample": max(
              growth_increments or [0]),
      },
      "proactive_demotions": None,
      "early_reuse": None,
      "oracle_headroom": None,
      "policy_metrics_status": "search_pending",
  })
  return result


def _default_cost(summary: Mapping[str, Any]) -> int:
  return (
      int(summary["dram_hits"]) + 2 * int(summary["nvm_reads"]) +
      8 * int(summary["nvm_writes"]) +
      10 * int(summary["total_demotions"]))


def _policy_replay(
    stage0: Mapping[str, Any], trace: Sequence[Mapping[str, Any]],
    policy: str, D: int, F_low: int, F_target: int, b_max: int,
    config: Mapping[str, Any]
) -> Dict[str, Any]:
  _require(policy in REQUIRED_POLICIES, "Unsupported Stage-3 policy.")
  if policy == "reactive_lru":
    parameters = proactive_replay.ReplayParameters(
        policy_name=policy, dram_capacity_pages=D,
        history_window_size=config["fixed_stage3"]["history_window_size"],
        early_reuse_window=config["fixed_stage3"]["early_reuse_window"])
    ranker = None
  else:
    parameters = proactive_replay.ReplayParameters(
        policy_name=policy, dram_capacity_pages=D, F_low=F_low,
        F_target=F_target, b_max=b_max,
        candidate_size_K=config["fixed_stage3"]["candidate_size_K"],
        history_window_size=config["fixed_stage3"]["history_window_size"],
        early_reuse_window=config["fixed_stage3"]["early_reuse_window"],
        allow_b_max_equal_candidate_size=True)
    ranker = (
        proactive_stage5_policies.OracleRanker(trace)
        if policy == "oracle" else proactive_replay.ProactiveLRURanking())
  raw = proactive_replay.ProactiveReplay(
      stage0, parameters, ranking_policy=ranker, invariant_mode="boundary",
      record_details=False, capture_page_enter_flags=False).run(
          trace, copy_trace=False, compact=True)
  summary = raw["summary"]
  early = (
      None if int(summary["proactive_demotions"]) == 0 else
      int(summary["early_reuse_count"]) /
      float(summary["proactive_demotions"]))
  result = {
      "policy": policy,
      "dram_capacity_pages": D,
      "F_low": None if policy == "reactive_lru" else F_low,
      "F_target": None if policy == "reactive_lru" else F_target,
      "b_max": None if policy == "reactive_lru" else b_max,
      "candidate_size_K": None if policy == "reactive_lru" else 8,
      "default_weighted_cost": _default_cost(summary),
      "early_reuse_rate": early,
      "state_invariants_passed": True,
      "b_t_rule": (
          None if policy == "reactive_lru" else
          "min(b_max,max(0,F_target-free_frames),candidate_count)"),
      "b_t_invariants_passed": True,
      "duplicate_demotion_observed": False,
  }
  for field in (
      "total_accesses", "dram_hits", "nvm_reads", "nvm_writes",
      "page_enter_dram_count", "total_demotions", "proactive_demotions",
      "reactive_demotions", "emergency_demotions",
      "number_of_proactive_cycles", "number_of_proactive_rounds",
      "minimum_free_frames", "average_free_frames",
      "free_frame_exhaustion_count", "early_reuse_count"):
    result[field] = summary[field]
  return result


def _safe_run_id(run_id: str) -> str:
  _require(isinstance(run_id, str) and run_id and
           all(character.isalnum() or character in "-_." for character in run_id)
           and run_id not in (".", ".."), "Unsafe run_id.")
  return run_id


def _run_directory(
    project_root: str, config: Mapping[str, Any], run_id: str,
    output_root: Optional[str]
) -> str:
  root = (
      os.path.abspath(output_root) if output_root else
      _project_path(project_root, config["output_root"]))
  return os.path.join(root, _safe_run_id(run_id))


def _code_paths(project_root: str) -> List[str]:
  return [
      os.path.join(project_root, "qmap", "proactive_stage3_stage7.py"),
      os.path.join(project_root, "scripts", "run_capd_proactive_stage3_stage7.py"),
      os.path.join(project_root, "qmap", "proactive_replay.py"),
      os.path.join(project_root, "qmap", "proactive_stage5_policies.py"),
  ]


def _git_state(project_root: str) -> Dict[str, Any]:
  def command(arguments: Sequence[str]) -> Optional[str]:
    try:
      return subprocess.check_output(
          list(arguments), cwd=project_root, stderr=subprocess.DEVNULL,
          text=True).strip()
    except (OSError, subprocess.CalledProcessError):
      return None
  commit = command(("git", "rev-parse", "HEAD"))
  status = command(("git", "status", "--porcelain"))
  return {
      "git_commit": commit,
      "dirty_worktree": None if status is None else bool(status),
      "dirty_state_sha256": None if status is None else hashlib.sha256(
          status.encode("utf-8")).hexdigest(),
  }


def _load_authority(
    project_root: str, config: Mapping[str, Any]
) -> Tuple[Mapping[str, Any], Mapping[str, Any], str, str]:
  raw_path = _project_path(
      project_root, config["r1_authority"]["raw_identity_audit"])
  verification_path = _project_path(
      project_root, config["r1_authority"]["verification"])
  raw_sha = _verify_sha(
      raw_path, config["r1_authority"]["raw_identity_audit_sha256"],
      "R1 raw identity audit")
  verification_sha = _verify_sha(
      verification_path, config["r1_authority"]["verification_sha256"],
      "R1 verification")
  raw = load_json(raw_path)
  verification = load_json(verification_path)
  _require(verification.get("status") ==
           config["r1_authority"]["required_status"] and
           verification.get("R1") == "passed" and
           verification.get("raw_and_split_sha_unchanged") is True and
           verification.get("R5_R11_executed") is False and
           verification.get("formal_pressure_bundle_exported") is False,
           "R1 verification gate did not pass or later repair stages ran.")
  return raw, verification, raw_sha, verification_sha


def _resolved_manifest_path(project_root: str, entry: Mapping[str, Any]) -> str:
  recorded = entry.get("resolved_trace_path") or entry["trace_path"]
  path = _project_path(project_root, recorded)
  if not os.path.isfile(path) or fingerprint_file(path) != entry["sha256"]:
    path = proactive_stage7_repair.resolve_recorded_split(
        project_root, entry["trace_path"], entry["sha256"])
  reject_forbidden_input(dict(entry, resolved_runtime_path=path))
  _verify_sha(path, entry["sha256"], "Stage-3 input split")
  return path


def _identity(
    project_root: str, config_path: str, run_id: str,
    config: Mapping[str, Any], manifest: Mapping[str, Any], raw_sha: str
) -> Dict[str, Any]:
  code_paths = _code_paths(project_root)
  for path in code_paths:
    _require(os.path.isfile(path), "Missing Stage-3 code identity file: {}".format(path))
  return run_identity_payload(
      run_id, fingerprint_file(config_path), raw_sha,
      ["{}:{}:{}".format(
          entry["workload"], entry["split_role"], entry["sha256"])
       for entry in manifest["entries"]],
      [fingerprint_file(path) for path in code_paths])


def _state_path(run_directory: str) -> str:
  return os.path.join(run_directory, "run_state.json")


def _artifact_rows(run_directory: str, names: Sequence[str]) -> List[Dict[str, Any]]:
  rows = []
  for name in names:
    path = os.path.join(run_directory, name)
    _require(os.path.isfile(path), "Missing phase artifact: {}.".format(name))
    rows.append({"path": name, "sha256": fingerprint_file(path),
                 "bytes": os.path.getsize(path)})
  return rows


def _write_state(run_directory: str, state: Mapping[str, Any]) -> None:
  _write_json_atomic(_state_path(run_directory), state)


def _load_state(run_directory: str, identity: Mapping[str, Any]) -> Dict[str, Any]:
  path = _state_path(run_directory)
  _require(os.path.isfile(path), "Run has no preflight state.")
  state = load_json(path)
  _require(state.get("run_identity_sha256") == fingerprint_value(identity) and
           state.get("run_identity") == identity,
           "Resume refused: input, config, or code identity changed; use a new run ID.")
  return state


class _TaskCache(object):
  """Durable per-window Replay cache used by the search phase."""

  def __init__(self, run_directory: str):
    self.directory = os.path.join(run_directory, "checkpoints", "search")
    self.log_path = os.path.join(run_directory, "logs", "progress.jsonl")
    self.memory = {}
    self.memory_reuse_count = 0
    os.makedirs(self.directory, exist_ok=True)

  def run(self, metadata: Mapping[str, Any], callback) -> Mapping[str, Any]:
    task_id = fingerprint_value(metadata)
    if task_id in self.memory:
      self.memory_reuse_count += 1
      if self.memory_reuse_count == 1 or self.memory_reuse_count % 1000 == 0:
        _append_jsonl(self.log_path, {
            "timestamp": _utc_now(), "event": "search_task_memory_reused",
            "task_id": task_id,
            "memory_reuse_count": self.memory_reuse_count})
      return self.memory[task_id]
    path = os.path.join(self.directory, task_id + ".json")
    if os.path.isfile(path):
      value = load_json(path)
      _require(value.get("metadata") == metadata,
               "Search checkpoint metadata mismatch.")
      self.memory[task_id] = value["payload"]
      _append_jsonl(self.log_path, {
          "timestamp": _utc_now(), "event": "search_task_resumed",
          "task_id": task_id})
      return value["payload"]
    _append_jsonl(self.log_path, {
        "timestamp": _utc_now(), "event": "search_task_started",
        "task_id": task_id, "metadata": metadata})
    started = time.monotonic()
    payload = callback()
    elapsed_seconds = time.monotonic() - started
    _write_json_atomic(path, {
        "schema_version": RESULT_SCHEMA, "task_id": task_id,
        "metadata": copy.deepcopy(metadata),
        "elapsed_seconds": elapsed_seconds,
        "payload": payload})
    self.memory[task_id] = payload
    _append_jsonl(self.log_path, {
        "timestamp": _utc_now(), "event": "search_task_completed",
        "task_id": task_id, "metadata": metadata,
        "elapsed_seconds": elapsed_seconds})
    return payload


class _ProfileTaskCache(object):
  """Durable per-window cache and progress stream for one workload."""

  def __init__(self, run_directory: str, workload: str):
    _require(workload in WORKLOADS, "Unknown profile workload.")
    self.directory = os.path.join(
        run_directory, "checkpoints", "profile", workload)
    self.log_path = os.path.join(
        run_directory, "logs", "profile", workload + ".jsonl")
    os.makedirs(self.directory, exist_ok=True)

  def run(self, metadata: Mapping[str, Any], callback) -> Mapping[str, Any]:
    task_id = fingerprint_value(metadata)
    path = os.path.join(self.directory, task_id + ".json")
    if os.path.isfile(path):
      value = load_json(path)
      _require(value.get("metadata") == metadata,
               "Profile checkpoint metadata mismatch.")
      _append_jsonl(self.log_path, {
          "timestamp": _utc_now(), "event": "profile_task_resumed",
          "task_id": task_id})
      return value["payload"]
    _append_jsonl(self.log_path, {
        "timestamp": _utc_now(), "event": "profile_task_started",
        "task_id": task_id, "metadata": metadata})
    started = time.monotonic()
    payload = callback()
    elapsed_seconds = time.monotonic() - started
    _write_json_atomic(path, {
        "schema_version": RESULT_SCHEMA, "task_id": task_id,
        "metadata": copy.deepcopy(metadata),
        "elapsed_seconds": elapsed_seconds,
        "payload": payload})
    _append_jsonl(self.log_path, {
        "timestamp": _utc_now(), "event": "profile_task_completed",
        "task_id": task_id, "metadata": metadata,
        "elapsed_seconds": elapsed_seconds})
    return payload


class _Fenwick(object):

  def __init__(self, size: int):
    self.values = [0] * (size + 1)

  def add(self, index: int, delta: int) -> None:
    index += 1
    while index < len(self.values):
      self.values[index] += delta
      index += index & -index

  def prefix(self, end_exclusive: int) -> int:
    total = 0
    index = end_exclusive
    while index > 0:
      total += self.values[index]
      index -= index & -index
    return total


def _lru_metrics_for_capacities(
    pages: Sequence[int], capacities: Sequence[int]
) -> Dict[str, Dict[str, int]]:
  """Computes exact empty-state LRU misses for many capacities in one pass."""
  resolved = sorted(set(_positive_integer(int(value), "capacity")
                        for value in capacities))
  tree = _Fenwick(len(pages))
  last = {}
  cold = 0
  stack_histogram = collections.Counter()
  for index, raw_page in enumerate(pages):
    page = int(raw_page)
    previous = last.get(page)
    if previous is None:
      cold += 1
    else:
      distance = tree.prefix(index) - tree.prefix(previous + 1)
      stack_histogram[distance] += 1
      tree.add(previous, -1)
    tree.add(index, 1)
    last[page] = index
  result = {}
  for capacity in resolved:
    misses = cold + sum(
        count for distance, count in stack_histogram.items()
        if distance >= capacity)
    result[str(capacity)] = {
        "dram_capacity_pages": capacity,
        "lru_misses": misses,
        "lru_replacement_decisions": max(0, misses - capacity),
        "page_entry_count": misses,
        "cold_misses": cold,
    }
  return result


def _phase_start(
    state: Dict[str, Any], run_directory: str, phase: str,
    resume: bool
) -> bool:
  completed = state.get("completed_phases", [])
  if phase in completed:
    _require(resume, "{} already completed; pass --resume to verify/reuse it."
             .format(phase))
    artifacts = state.get("phase_artifacts", {}).get(phase, [])
    for artifact in artifacts:
      path = os.path.join(run_directory, artifact["path"])
      _verify_sha(path, artifact["sha256"],
                  "resumed {} artifact".format(phase))
    return False
  required_index = ALL_PHASES.index(phase)
  _require(all(item in completed for item in ALL_PHASES[:required_index]),
           "{} requires completed phases {}.".format(
               phase, list(ALL_PHASES[:required_index])))
  state["active_phase"] = phase
  state["status"] = "running"
  state["updated_at"] = _utc_now()
  _write_state(run_directory, state)
  return True


def _phase_finish(
    state: Dict[str, Any], run_directory: str, phase: str,
    artifact_names: Sequence[str]
) -> None:
  state.setdefault("completed_phases", []).append(phase)
  state.setdefault("phase_artifacts", {})[phase] = _artifact_rows(
      run_directory, artifact_names)
  state["active_phase"] = None
  state["status"] = "freeze_candidate_ready" if phase == "verify" else "ready"
  state.pop("failure", None)
  state["updated_at"] = _utc_now()
  _write_state(run_directory, state)


def _phase_fail(state: Dict[str, Any], run_directory: str,
                phase: str, error: BaseException) -> None:
  state["active_phase"] = phase
  state["status"] = "failed_preserved"
  state["failure"] = {
      "phase": phase, "error_type": type(error).__name__,
      "error_message": str(error), "timestamp": _utc_now()}
  _write_state(run_directory, state)


def run_preflight(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  project_root = os.path.realpath(project_root)
  config_path = os.path.realpath(config_path)
  config = validate_config(load_json(config_path))
  raw, verification, raw_sha, verification_sha = _load_authority(
      project_root, config)
  manifest = manifest_from_r1_authority(
      raw, config, project_root=project_root, verify_files=True)
  manifest["run_id"] = run_id
  identity = _identity(
      project_root, config_path, run_id, config, manifest, raw_sha)
  directory = _run_directory(project_root, config, run_id, output_root)
  if os.path.exists(directory):
    state = _load_state(directory, identity)
    _require(resume, "Run directory already exists; pass --resume or use a new run ID.")
    if not _phase_start(state, directory, "preflight", resume=True):
      return {"status": "preflight_resumed", "output_directory": directory}
  else:
    os.makedirs(os.path.join(directory, "logs"))
    state = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "created_at": _utc_now(),
        "status": "running",
        "active_phase": "preflight",
        "completed_phases": [],
        "phase_artifacts": {},
        "run_identity": identity,
        "run_identity_sha256": fingerprint_value(identity),
        "failed_directory_must_be_preserved": True,
        "formal_freeze": False,
    }
    _write_state(directory, state)
  try:
    resolved_config = copy.deepcopy(config)
    resolved_config["run_id"] = run_id
    resolved_config["output_directory"] = os.path.relpath(
        directory, project_root).replace(os.sep, "/")
    provenance = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "created_at": _utc_now(),
        "r1_authority": {
            "run_id": raw["run_id"], "raw_identity_audit_sha256": raw_sha,
            "verification_sha256": verification_sha,
            "verification_status": verification["status"],
            "R1": verification["R1"],
            "input_identity_sha256": raw["input_identity_sha256"]},
        "input_split_count": len(manifest["entries"]),
        "input_split_roles": list(ALLOWED_SPLITS),
        "code_identity": [
            {"path": os.path.relpath(path, project_root).replace(os.sep, "/"),
             "sha256": fingerprint_file(path)}
            for path in _code_paths(project_root)],
    }
    provenance.update(verification_boundary())
    provenance.update(_git_state(project_root))
    _write_json_atomic(os.path.join(directory, "input_manifest.json"), manifest)
    _write_json_atomic(os.path.join(directory, "resolved_config.json"),
                       resolved_config)
    _write_json_atomic(os.path.join(directory, "provenance.json"), provenance)
    _write_json_atomic(os.path.join(directory, "run_identity.json"), identity)
    _phase_finish(state, directory, "preflight", (
        "input_manifest.json", "resolved_config.json", "provenance.json",
        "run_identity.json"))
    return {"status": "preflight_complete", "output_directory": directory,
            "input_entries": 12}
  except BaseException as error:
    _phase_fail(state, directory, "preflight", error)
    raise


def _existing_context(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str]
) -> Tuple[Mapping[str, Any], Mapping[str, Any], Dict[str, Any], str]:
  project_root = os.path.realpath(project_root)
  config_path = os.path.realpath(config_path)
  config = validate_config(load_json(config_path))
  raw, _, raw_sha, _ = _load_authority(project_root, config)
  manifest = manifest_from_r1_authority(
      raw, config, project_root=project_root, verify_files=True)
  manifest["run_id"] = run_id
  identity = _identity(
      project_root, config_path, run_id, config, manifest, raw_sha)
  directory = _run_directory(project_root, config, run_id, output_root)
  state = _load_state(directory, identity)
  frozen_manifest = validate_input_manifest(
      load_json(os.path.join(directory, "input_manifest.json")), raw)
  _require(fingerprint_value(frozen_manifest) == fingerprint_value(manifest),
           "Frozen input manifest changed after preflight.")
  return config, manifest, state, directory


def _load_workload_traces(
    project_root: str, manifest: Mapping[str, Any], workload: str
) -> Dict[str, proactive_stage3.CompactTrace]:
  result = {}
  for entry in manifest["entries"]:
    if entry["workload"] != workload:
      continue
    path = _resolved_manifest_path(project_root, entry)
    trace, _ = proactive_stage3._read_compact_trace(path, entry["page_shift"])
    _require(len(trace) == entry["accesses"],
             "Trace access count differs from R1 authority.")
    result[entry["split_role"]] = trace
  _require(set(result) == set(ALLOWED_SPLITS),
           "Workload lacks Train/Validation traces.")
  return result


def _profile_csv_row(row: Mapping[str, Any]) -> Dict[str, Any]:
  fields = dict(row)
  for name in (
      "page_entry_burst", "reuse_distance_summary", "working_set_growth",
      "lru_capacity_metrics"):
    fields[name] = json.dumps(
        fields[name], sort_keys=True, separators=(",", ":"))
  return fields


def _profile_workload_task(arguments: Tuple[Any, ...]) -> Dict[str, Any]:
  """Profiles one workload in an isolated process with window checkpoints."""
  config, manifest, workload, project_root, directory = arguments
  traces = _load_workload_traces(project_root, manifest, workload)
  train_pages = set(traces["train"].pages)
  validation_pages = set(traces["validation"].pages)
  union_pages = len(train_pages | validation_pages)
  standard_rows = standard_capacity_rows(
      workload, union_pages, config["standard_capacity"]["ratios"])
  descriptors = []
  block_rows = []
  for split_role in ALLOWED_SPLITS:
    block_count = config["windowing"][
        "train_block_count" if split_role == "train" else
        "validation_block_count"]
    split_descriptors = build_window_descriptors(
        split_role, len(traces[split_role]),
        config["windowing"]["calibration_window_records"],
        config["windowing"]["window_step"], block_count)
    descriptors.extend(split_descriptors)
    for block_index in sorted({row["block_index"]
                               for row in split_descriptors}):
      block_rows.append({
          "workload": workload, "split_role": split_role,
          "block_index": block_index,
          "window_count": sum(
              row["block_index"] == block_index
              for row in split_descriptors),
          "chronological": True, "shuffle": False,
          "cross_block_windows": 0})

  cache = _ProfileTaskCache(directory, workload)
  _append_jsonl(cache.log_path, {
      "timestamp": _utc_now(), "event": "profile_workload_started",
      "workload": workload, "base_task_count": len(descriptors),
      "capacity_task_count": len(descriptors),
      "total_task_count": 2 * len(descriptors)})
  reference_capacity = standard_rows[0]["D_standard"]
  preliminary = []
  for descriptor in descriptors:
    metadata = {
        "pass": "base_profile", "workload": workload,
        "split_role": descriptor["split_role"],
        "block_index": descriptor["block_index"],
        "window_records": descriptor["window_records"],
        "start_record": descriptor["start_record"],
        "end_record": descriptor["end_record"],
        "reference_capacity_pages": reference_capacity,
        "page_entry_burst_records":
            config["windowing"]["page_entry_burst_records"],
        "working_set_growth_sample_records":
            config["windowing"]["working_set_growth_sample_records"],
    }

    def base_task(split=descriptor["split_role"], row=descriptor):
      return _window_profile(traces[split], row, reference_capacity, config)

    profile = copy.deepcopy(cache.run(metadata, base_task))
    profile.update({"workload": workload,
                    "reference_capacity_pages": reference_capacity})
    preliminary.append(profile)

  wref_rows = []
  pressure_rows = []
  for records in config["windowing"]["calibration_window_records"]:
    train_values = [
        row["unique_pages"] for row in preliminary
        if row["split_role"] == "train" and
        row["window_records"] == records]
    validation_count = sum(
        row["split_role"] == "validation" and
        row["window_records"] == records for row in preliminary)
    for quantile in config["working_set_reference"]["quantiles"]:
      W_ref = nearest_rank(train_values, quantile)
      wref_rows.append({
          "workload": workload, "window_records": records,
          "W_ref_quantile": quantile, "W_ref": W_ref,
          "train_window_count": len(train_values),
          "validation_window_count": validation_count})
      for ratio in config["pressure_capacity"]["ratios"]:
        pressure_rows.append(pressure_capacity_row(
            workload, W_ref, quantile, ratio, records))

  capacities = [row["D_standard"] for row in standard_rows]
  capacities.extend(row["D_pressure"] for row in pressure_rows)
  capacities = sorted(set(capacities))
  profiles = []
  for profile in preliminary:
    metadata = {
        "pass": "capacity_metrics", "workload": workload,
        "split_role": profile["split_role"],
        "block_index": profile["block_index"],
        "window_records": profile["window_records"],
        "start_record": profile["start_record"],
        "end_record": profile["end_record"],
        "capacities": capacities,
    }

    def capacity_task(row=profile):
      trace = traces[row["split_role"]]
      pages = trace.pages[row["start_record"]:row["end_record"]]
      return _lru_metrics_for_capacities(pages, capacities)

    profile["lru_capacity_metrics"] = copy.deepcopy(
        cache.run(metadata, capacity_task))
    reference = profile["lru_capacity_metrics"][str(reference_capacity)]
    profile["lru_misses"] = reference["lru_misses"]
    profile["lru_replacement_decisions"] = reference[
        "lru_replacement_decisions"]
    profiles.append(profile)
  _append_jsonl(cache.log_path, {
      "timestamp": _utc_now(), "event": "profile_workload_completed",
      "workload": workload, "window_count": len(profiles),
      "total_task_count": 2 * len(descriptors)})
  return {
      "workload": workload, "profiles": profiles,
      "wref_rows": wref_rows, "standard_rows": standard_rows,
      "pressure_rows": pressure_rows, "block_rows": block_rows}


def run_profile(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  config, manifest, state, directory = _existing_context(
      config_path, run_id, project_root, output_root)
  if not _phase_start(state, directory, "profile", resume):
    return {"status": "profile_resumed", "output_directory": directory}
  try:
    all_profiles = []
    wref_rows = []
    standard_rows = []
    pressure_rows = []
    block_rows = []
    task_plan = profile_task_plan(manifest, config)
    _append_jsonl(os.path.join(directory, "logs", "progress.jsonl"), {
        "timestamp": _utc_now(), "event": "profile_plan_created",
        "profile_workers": config["execution"]["profile_workers"],
        "total_window_count": task_plan["total_window_count"],
        "total_task_count": task_plan["total_task_count"],
        "workloads": task_plan["workloads"]})
    arguments = [
        (config, manifest, workload, project_root, directory)
        for workload in WORKLOADS]
    worker_count = min(
        config["execution"]["profile_workers"], len(arguments))
    if worker_count == 1:
      workload_results = [_profile_workload_task(value) for value in arguments]
    else:
      pool = multiprocessing.Pool(processes=worker_count)
      try:
        workload_results = pool.map(_profile_workload_task, arguments)
      except BaseException:
        pool.terminate()
        pool.join()
        raise
      else:
        pool.close()
        pool.join()
    for result in workload_results:
      all_profiles.extend(result["profiles"])
      wref_rows.extend(result["wref_rows"])
      standard_rows.extend(result["standard_rows"])
      pressure_rows.extend(result["pressure_rows"])
      block_rows.extend(result["block_rows"])
      _append_jsonl(os.path.join(directory, "logs", "progress.jsonl"), {
          "timestamp": _utc_now(), "event": "profile_workload_completed",
          "workload": result["workload"],
          "window_count": len(result["profiles"])})
    wref_index = collections.defaultdict(list)
    for row in wref_rows:
      wref_index[(row["workload"], row["window_records"],
                  row["W_ref_quantile"])].append(row)
    for capacity in pressure_rows:
      matching = [row for row in all_profiles
                  if row["workload"] == capacity["workload"] and
                  row["window_records"] == capacity["window_records"]]
      minimum_target = dynamic_watermark(
          capacity["D_pressure"], 0.05, 0.4)["F_target"]
      for split_role in ALLOWED_SPLITS:
        subset = [row for row in matching if row["split_role"] == split_role]
        eligible = 0
        for row in subset:
          metric = row["lru_capacity_metrics"][str(capacity["D_pressure"])]
          if pressure_eligibility(
              row["unique_pages"], capacity["D_pressure"], minimum_target,
              metric["lru_replacement_decisions"]) == ["eligible"]:
            eligible += 1
        capacity["{}_pressure_window_count".format(split_role)] = eligible
        capacity["{}_pressure_coverage".format(split_role)] = (
            eligible / float(len(subset)) if subset else 0.0)
      capacity["coverage_watermark_status"] = (
          "provisional_minimum_dynamic_F_target_"
          "search_recomputes_every_candidate")
    profile_fields = (
        "workload", "split_role", "block_index", "block_start_record",
        "block_end_record", "window_records", "start_record", "end_record",
        "chronological", "shuffle", "initial_state", "crosses_split_boundary",
        "unique_pages", "lru_misses", "lru_replacement_decisions",
        "page_entry_count", "page_entry_burst", "write_ratio",
        "reuse_distance_summary", "working_set_growth",
        "minimum_free_frames", "mean_free_frames", "empty_frame_exhaustion",
        "proactive_demotions", "early_reuse", "default_weighted_cost",
        "oracle_headroom", "reference_capacity_pages",
        "lru_capacity_metrics", "policy_metrics_status")
    _write_csv_atomic(
        os.path.join(directory, "windowed_wss_profiles.csv"),
        [_profile_csv_row(row) for row in all_profiles], profile_fields)
    summary = {
        "schema_version": RESULT_SCHEMA,
        "working_set_definition":
            "train_chronological_window_unique_pages_quantile",
        "windowing": copy.deepcopy(config["windowing"]),
        "W_ref": wref_rows,
        "windows": all_profiles,
        "all_candidate_windows_saved": True,
        "test_windows": 0,
    }
    _write_json_atomic(os.path.join(directory, "windowed_wss_summary.json"),
                       summary)
    _write_json_atomic(os.path.join(directory, "blocked_calibration_manifest.json"), {
        "schema_version": RESULT_SCHEMA, "blocks": block_rows,
        "chronological": True, "shuffle": False,
        "cross_block_windows": 0, "test_blocks": 0})
    _write_json_atomic(os.path.join(directory, "capacity_standard_matrix.json"), {
        "schema_version": RESULT_SCHEMA, "cells": standard_rows,
        "working_set_definition": "unique_pages_in_train_validation_union"})
    _write_json_atomic(os.path.join(directory, "capacity_pressure_candidates.json"), {
        "schema_version": RESULT_SCHEMA, "cells": pressure_rows,
        "D_guard_min_64_used": False,
        "minimum_capacity_pages": 8})
    _phase_finish(state, directory, "profile", (
        "windowed_wss_profiles.csv", "windowed_wss_summary.json",
        "blocked_calibration_manifest.json", "capacity_standard_matrix.json",
        "capacity_pressure_candidates.json"))
    return {"status": "profile_complete", "output_directory": directory,
            "window_count": len(all_profiles),
            "pressure_capacity_count": len(pressure_rows)}
  except BaseException as error:
    _phase_fail(state, directory, "profile", error)
    raise


def _candidate_id(window_records: int, quantile: float, ratio: float,
                  alpha: float, beta: float, b_max: int) -> str:
  return "win{}-q{:02d}-r{:02d}-a{:02d}-b{:02d}-batch{}".format(
      window_records, int(round(quantile * 100)), int(round(ratio * 100)),
      int(round(alpha * 100)), int(round(beta * 10)), b_max)


def _metric_for_capacity(window: Mapping[str, Any], D: int) -> Mapping[str, Any]:
  value = window["lru_capacity_metrics"].get(str(D))
  _require(isinstance(value, Mapping),
           "Window profile lacks exact LRU metrics for D={}.".format(D))
  return value


def _window_identity(window: Mapping[str, Any]) -> Tuple[Any, ...]:
  return (
      window["workload"], window["split_role"], window["block_index"],
      window["window_records"], window["start_record"], window["end_record"])


def _coverage_for_candidate(
    windows: Sequence[Mapping[str, Any]], D: int, F_low: int, F_target: int
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
  rows = []
  for window in windows:
    metric = _metric_for_capacity(window, D)
    reasons = pressure_eligibility(
        window["unique_pages"], D, F_target,
        metric["lru_replacement_decisions"],
        split_boundary_valid=not window["crosses_split_boundary"])
    rows.append({
        "workload": window["workload"],
        "split_role": window["split_role"],
        "block_index": window["block_index"],
        "window_records": window["window_records"],
        "start_record": window["start_record"],
        "end_record": window["end_record"],
        "unique_pages": window["unique_pages"],
        "lru_misses": metric["lru_misses"],
        "lru_replacement_decisions": metric[
            "lru_replacement_decisions"],
        "page_entry_count": metric["page_entry_count"],
        "write_ratio": window["write_ratio"],
        "D_pressure": D,
        "F_low": F_low,
        "F_target": F_target,
        "eligible": reasons == ["eligible"],
        "eligibility_reasons": reasons,
    })
  train_blocks = {}
  for block in sorted({row["block_index"] for row in rows
                       if row["split_role"] == "train"}):
    block_rows = [row for row in rows
                  if row["split_role"] == "train" and
                  row["block_index"] == block]
    train_blocks[str(block)] = choose_reactive_sentinels(block_rows)
  validation_rows = [row for row in rows
                     if row["split_role"] == "validation"]
  sentinels = {
      "train_blocks": train_blocks,
      "validation": choose_reactive_sentinels(validation_rows),
  }
  return rows, sentinels


def _find_window(
    windows: Sequence[Mapping[str, Any]], sentinel: Mapping[str, Any]
) -> Mapping[str, Any]:
  identity = (
      sentinel["workload"], sentinel["split_role"],
      sentinel["block_index"], sentinel["window_records"],
      sentinel["start_record"], sentinel["end_record"])
  for window in windows:
    if _window_identity(window) == identity:
      return window
  raise Stage3Stage7Error("Selected Reactive sentinel is missing.")


def run_search(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  config, manifest, state, directory = _existing_context(
      config_path, run_id, project_root, output_root)
  if not _phase_start(state, directory, "search", resume):
    return {"status": "search_resumed", "output_directory": directory}
  try:
    profile = load_json(os.path.join(directory, "windowed_wss_summary.json"))
    windows = profile["windows"]
    wrefs = profile["W_ref"]
    standard_matrix = load_json(os.path.join(
        directory, "capacity_standard_matrix.json"))["cells"]
    pressure_matrix = load_json(os.path.join(
        directory, "capacity_pressure_candidates.json"))["cells"]
    stage0_path = _project_path(
        project_root, config["fixed_stage3"]["stage0_config"])
    stage0 = finals_config.load_config(stage0_path)
    finals_config.validate_config(stage0)
    traces = {workload: _load_workload_traces(
        project_root, manifest, workload) for workload in WORKLOADS}
    cache = _TaskCache(directory)
    controller_rows = []
    watermark_rows = []
    coverage_rows = []
    policy_rows = []
    headroom_rows = []
    safety_rows = []
    coverage_cache = {}
    for window_records in config["search_space"]["window_records"]:
      for quantile in config["search_space"]["W_ref_quantile"]:
        for ratio in config["search_space"]["r_pressure"]:
          capacity_by_workload = {}
          for workload in WORKLOADS:
            matching = [row for row in pressure_matrix
                        if row["workload"] == workload and
                        row["window_records"] == window_records and
                        row["W_ref_quantile"] == quantile and
                        row["requested_ratio"] == ratio]
            _require(len(matching) == 1, "Pressure capacity cell is ambiguous.")
            capacity_by_workload[workload] = matching[0]
          for alpha in config["search_space"]["alpha"]:
            for beta in config["search_space"]["beta"]:
              actual_watermarks = {
                  workload: dynamic_watermark(
                      capacity_by_workload[workload]["D_pressure"],
                      alpha, beta) for workload in WORKLOADS}
              for b_max in config["search_space"]["b_max"]:
                candidate_id = _candidate_id(
                    window_records, quantile, ratio, alpha, beta, b_max)
                controller = {
                    "candidate_id": candidate_id,
                    "window_records": window_records,
                    "W_ref_quantile": quantile,
                    "requested_ratio": ratio,
                    "alpha": alpha, "beta": beta, "b_max": b_max,
                    "candidate_size_K": 8,
                    "b_t_rule": config["controller_search"]["b_t_rule"],
                    "actual_by_workload": {},
                }
                candidate_pressure_windows = 0
                candidate_total_windows = 0
                candidate_train_workloads = 0
                candidate_workloads = []
                for workload in WORKLOADS:
                  capacity = capacity_by_workload[workload]
                  watermark = actual_watermarks[workload]
                  resolved = dict(capacity)
                  resolved.update(watermark)
                  controller["actual_by_workload"][workload] = resolved
                  watermark_rows.append(dict({
                      "candidate_id": candidate_id,
                      "workload": workload}, **watermark))
                  workload_windows = [
                      row for row in windows
                      if row["workload"] == workload and
                      row["window_records"] == window_records]
                  coverage_key = (
                      workload, window_records, quantile, ratio,
                      capacity["D_pressure"], watermark["F_target"])
                  if coverage_key not in coverage_cache:
                    eligible_rows, sentinels = _coverage_for_candidate(
                        workload_windows, capacity["D_pressure"],
                        watermark["F_low"], watermark["F_target"])
                    coverage_id = "coverage-{}".format(
                        fingerprint_value(list(coverage_key))[:20])
                    for row in eligible_rows:
                      row.update({
                          "coverage_id": coverage_id,
                          "W_ref_quantile": quantile,
                          "W_ref": capacity["W_ref"],
                          "requested_ratio": ratio,
                          "alpha": alpha,
                          "F_target": watermark["F_target"]})
                    coverage_cache[coverage_key] = (
                        coverage_id, eligible_rows, sentinels)
                    coverage_rows.append({
                        "coverage_id": coverage_id,
                        "workload": workload,
                        "window_records": window_records,
                        "W_ref_quantile": quantile,
                        "W_ref": capacity["W_ref"],
                        "requested_ratio": ratio,
                        "D_pressure_raw": capacity["D_pressure_raw"],
                        "D_pressure": capacity["D_pressure"],
                        "minimum_capacity_applied":
                            capacity["minimum_capacity_applied"],
                        "F_target": watermark["F_target"],
                        "train_pressure_window_count": sum(
                            row["eligible"] and row["split_role"] == "train"
                            for row in eligible_rows),
                        "train_pressure_coverage": (
                            sum(row["eligible"] and row["split_role"] == "train"
                                for row in eligible_rows) /
                            float(sum(row["split_role"] == "train"
                                      for row in eligible_rows))),
                        "validation_pressure_window_count": sum(
                            row["eligible"] and
                            row["split_role"] == "validation"
                            for row in eligible_rows),
                        "validation_pressure_coverage": (
                            sum(row["eligible"] and
                                row["split_role"] == "validation"
                                for row in eligible_rows) /
                            float(sum(row["split_role"] == "validation"
                                      for row in eligible_rows))),
                        "all_candidate_windows": eligible_rows,
                        "selection_policy": "fixed_reactive_lru_only",
                        "capd_or_oracle_used_for_selection": False,
                    })
                  coverage_id, eligible_rows, sentinels = coverage_cache[
                      coverage_key]
                  eligible_count = sum(row["eligible"] for row in eligible_rows)
                  candidate_pressure_windows += eligible_count
                  candidate_total_windows += len(eligible_rows)
                  train_sentinels = [
                      value["pressure"]
                      for value in sentinels["train_blocks"].values()]
                  all_train_blocks_covered = (
                      bool(train_sentinels) and
                      all(value is not None for value in train_sentinels))
                  candidate_train_workloads += int(all_train_blocks_covered)
                  controller["actual_by_workload"][workload].update({
                      "coverage_id": coverage_id,
                      "all_train_blocks_covered": all_train_blocks_covered,
                      "train_block_sentinels": sentinels["train_blocks"],
                      "validation_sentinels": sentinels["validation"]})
                  candidate_workloads.append({
                      "workload": workload,
                      "capacity": capacity,
                      "watermark": watermark,
                      "workload_windows": workload_windows,
                      "train_sentinels": train_sentinels,
                      "all_train_blocks_covered": all_train_blocks_covered,
                      "validation_pressure":
                          sentinels["validation"]["pressure"],
                      "validation_low":
                          sentinels["validation"]["low_pressure"]})
                if candidate_train_workloads > 0:
                  for workload_data in candidate_workloads:
                    workload = workload_data["workload"]
                    capacity = workload_data["capacity"]
                    watermark = workload_data["watermark"]
                    workload_windows = workload_data["workload_windows"]
                    evaluation = []
                    if workload_data["all_train_blocks_covered"]:
                      evaluation.extend(("train_pressure", value)
                                        for value in
                                        workload_data["train_sentinels"])
                    validation_pressure = workload_data[
                        "validation_pressure"]
                    validation_low = workload_data["validation_low"]
                    if validation_pressure is not None:
                      evaluation.append(("validation_pressure",
                                         validation_pressure))
                    if validation_low is not None:
                      evaluation.append(("validation_low_pressure",
                                         validation_low))
                    for evaluation_role, sentinel in evaluation:
                      window = _find_window(workload_windows, sentinel)
                      trace_view = _TraceView(
                          traces[workload][window["split_role"]],
                          window["start_record"], window["end_record"])
                      results = {}
                      for policy in REQUIRED_POLICIES:
                        metadata = {
                            "policy": policy, "workload": workload,
                            "split_role": window["split_role"],
                            "start_record": window["start_record"],
                            "end_record": window["end_record"],
                            "D": capacity["D_pressure"],
                            "F_low": (
                                None if policy == "reactive_lru" else
                                watermark["F_low"]),
                            "F_target": (
                                None if policy == "reactive_lru" else
                                watermark["F_target"]),
                            "b_max": (
                                None if policy == "reactive_lru" else b_max),
                        }

                        def replay_task(policy_name=policy):
                          return _policy_replay(
                              stage0, trace_view, policy_name,
                              capacity["D_pressure"], watermark["F_low"],
                              watermark["F_target"], b_max, config)

                        result = copy.deepcopy(cache.run(
                            metadata, replay_task))
                        result.update({
                            "candidate_id": candidate_id,
                            "workload": workload,
                            "split_role": window["split_role"],
                            "block_index": window["block_index"],
                            "window_records": window_records,
                            "start_record": window["start_record"],
                            "end_record": window["end_record"],
                            "evaluation_role": evaluation_role,
                            "W_ref_quantile": quantile,
                            "W_ref": capacity["W_ref"],
                            "requested_ratio": ratio,
                        })
                        results[policy] = result
                        policy_rows.append(result)
                      reactive = results["reactive_lru"]
                      oracle = results["oracle"]
                      headroom = max(
                          0.0, float(reactive["default_weighted_cost"]) -
                          float(oracle["default_weighted_cost"]))
                      headroom_rows.append({
                          "candidate_id": candidate_id,
                          "workload": workload,
                          "evaluation_role": evaluation_role,
                          "split_role": window["split_role"],
                          "block_index": window["block_index"],
                          "start_record": window["start_record"],
                          "oracle_headroom": headroom,
                          "oracle_used_for_window_selection": False,
                      })
                      if evaluation_role.startswith("validation"):
                        safety = validation_safety_gate(
                            reactive, results["proactive_lru"],
                            config["validation_safety"])
                        safety.update({
                            "candidate_id": candidate_id,
                            "workload": workload,
                            "evaluation_role": evaluation_role,
                            "start_record": window["start_record"]})
                        safety_rows.append(safety)
                controller.update({
                    "train_pressure_workload_count": candidate_train_workloads,
                    "pressure_window_count": candidate_pressure_windows,
                    "candidate_window_count": candidate_total_windows,
                    "pressure_coverage": (
                        candidate_pressure_windows /
                        float(candidate_total_windows)
                        if candidate_total_windows else 0.0),
                    "search_executed": candidate_train_workloads > 0,
                })
                controller_rows.append(controller)
    _write_json_atomic(os.path.join(directory, "watermark_candidates.json"), {
        "schema_version": RESULT_SCHEMA, "candidates": watermark_rows})
    _write_json_atomic(os.path.join(directory, "controller_candidates.json"), {
        "schema_version": RESULT_SCHEMA, "candidates": controller_rows,
        "b_t_rule": config["controller_search"]["b_t_rule"]})
    _write_json_atomic(os.path.join(directory, "pressure_coverage.json"), {
        "schema_version": RESULT_SCHEMA, "rows": coverage_rows,
        "all_candidate_windows_saved": True,
        "selection_policy": "fixed_reactive_lru_only"})
    _write_json_atomic(os.path.join(directory, "policy_results.json"), {
        "schema_version": RESULT_SCHEMA, "rows": policy_rows,
        "required_policies": list(REQUIRED_POLICIES)})
    _write_json_atomic(os.path.join(directory, "oracle_headroom.json"), {
        "schema_version": RESULT_SCHEMA, "rows": headroom_rows,
        "gate": oracle_headroom_gate(headroom_rows),
        "oracle_used_for_window_selection": False})
    _write_json_atomic(os.path.join(directory, "validation_safety.json"), {
        "schema_version": RESULT_SCHEMA, "rows": safety_rows,
        "rule": copy.deepcopy(config["validation_safety"])})
    _phase_finish(state, directory, "search", (
        "watermark_candidates.json", "controller_candidates.json",
        "pressure_coverage.json", "policy_results.json",
        "oracle_headroom.json", "validation_safety.json"))
    return {"status": "search_complete", "output_directory": directory,
            "controller_candidate_count": len(controller_rows),
            "policy_result_count": len(policy_rows)}
  except BaseException as error:
    _phase_fail(state, directory, "search", error)
    raise


def _mean(values: Sequence[float], default: float = 0.0) -> float:
  return statistics.mean(values) if values else default


def run_select(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  config, _, state, directory = _existing_context(
      config_path, run_id, project_root, output_root)
  if not _phase_start(state, directory, "select", resume):
    return {"status": "select_resumed", "output_directory": directory}
  try:
    controllers = load_json(os.path.join(
        directory, "controller_candidates.json"))["candidates"]
    policy_rows = load_json(os.path.join(
        directory, "policy_results.json"))["rows"]
    headroom_rows = load_json(os.path.join(
        directory, "oracle_headroom.json"))["rows"]
    safety_rows = load_json(os.path.join(
        directory, "validation_safety.json"))["rows"]
    standard_matrix = load_json(os.path.join(
        directory, "capacity_standard_matrix.json"))["cells"]
    by_controller = {row["candidate_id"]: row for row in controllers}
    policies = collections.defaultdict(dict)
    for row in policy_rows:
      identity = (
          row["candidate_id"], row["workload"], row["evaluation_role"],
          row["split_role"], row["block_index"], row["start_record"])
      policies[identity][row["policy"]] = row
    comparisons = collections.defaultdict(list)
    for identity, policy_map in policies.items():
      _require(set(policy_map) == set(REQUIRED_POLICIES),
               "Every evaluated window requires Reactive/Proactive/Oracle.")
      reactive = policy_map["reactive_lru"]
      proactive = policy_map["proactive_lru"]
      oracle = policy_map["oracle"]
      headroom = max(
          0.0, float(reactive["default_weighted_cost"]) -
          float(oracle["default_weighted_cost"]))
      saving = max(
          0.0, float(reactive["default_weighted_cost"]) -
          float(proactive["default_weighted_cost"]))
      comparisons[identity[0]].append({
          "identity": list(identity[1:]),
          "weighted_cost_delta": (
              float(proactive["default_weighted_cost"]) -
              float(reactive["default_weighted_cost"])),
          "empty_frame_exhaustion_reduction": (
              float(reactive["free_frame_exhaustion_count"]) -
              float(proactive["free_frame_exhaustion_count"])),
          "minimum_free_frames": float(proactive["minimum_free_frames"]),
          "minimum_free_frames_delta": (
              float(proactive["minimum_free_frames"]) -
              float(reactive["minimum_free_frames"])),
          "early_reuse_ratio": proactive["early_reuse_rate"],
          "proactive_demotion_count": int(proactive["proactive_demotions"]),
          "oracle_headroom": headroom,
          "oracle_headroom_utilization": (
              min(1.0, saving / headroom) if headroom > 0 else None),
      })
    headroom_by_candidate = collections.defaultdict(list)
    for row in headroom_rows:
      headroom_by_candidate[row["candidate_id"]].append(row)
    safety_by_candidate = collections.defaultdict(list)
    for row in safety_rows:
      safety_by_candidate[row["candidate_id"]].append(row)
    aggregate_rows = []
    gate_rows = []
    for candidate_id in sorted(by_controller):
      controller = by_controller[candidate_id]
      values = comparisons.get(candidate_id, [])
      oracle_gate = oracle_headroom_gate(headroom_by_candidate[candidate_id])
      safety_values = safety_by_candidate[candidate_id]
      safety_passed = bool(safety_values) and all(
          row["passed"] for row in safety_values)
      pressure_coverage = float(controller["pressure_coverage"])
      pressure_passed = (
          controller["train_pressure_workload_count"] > 0 and
          pressure_coverage > 0)
      cost_delta = _mean([row["weighted_cost_delta"] for row in values])
      exhaustion_reduction = _mean([
          row["empty_frame_exhaustion_reduction"] for row in values])
      minimum_free = _mean([row["minimum_free_frames"] for row in values])
      minimum_free_delta = _mean([
          row["minimum_free_frames_delta"] for row in values])
      early_values = [float(row["early_reuse_ratio"]) for row in values
                      if row["early_reuse_ratio"] is not None]
      utilization_values = [
          float(row["oracle_headroom_utilization"]) for row in values
          if row["oracle_headroom_utilization"] is not None]
      proactive_demotions = sum(
          row["proactive_demotion_count"] for row in values)
      active_effect_passed = bool(values) and (
          cost_delta < 0 or exhaustion_reduction > 0 or
          minimum_free_delta > 0)
      eligible = (
          pressure_passed and oracle_gate["passed"] and safety_passed and
          active_effect_passed)
      aggregate = {
          "candidate_id": candidate_id,
          "weighted_cost_delta": cost_delta,
          "empty_frame_exhaustion_reduction": exhaustion_reduction,
          "minimum_free_frames": minimum_free,
          "minimum_free_frames_delta": minimum_free_delta,
          "early_reuse_ratio": _mean(early_values),
          "proactive_demotion_count": proactive_demotions,
          "oracle_headroom_utilization": _mean(utilization_values),
          "pressure_coverage": pressure_coverage,
          "validation_safety_passed": safety_passed,
          "oracle_headroom_gate_passed": oracle_gate["passed"],
          "pressure_coverage_gate_passed": pressure_passed,
          "active_mechanism_effect_passed": active_effect_passed,
          "eligible_for_pareto": eligible,
          "train_pressure_workload_count":
              controller["train_pressure_workload_count"],
          "evaluated_window_count": len(values),
      }
      aggregate_rows.append(aggregate)
      gate_rows.append({
          "candidate_id": candidate_id,
          "pressure_gate": pressure_passed,
          "oracle_gate": oracle_gate,
          "active_mechanism_gate": active_effect_passed,
          "validation_safety_gate": safety_passed,
          "eligible_for_pareto": eligible,
      })
    frontier = pareto_frontier([
        row for row in aggregate_rows if row["eligible_for_pareto"]])
    selected = (
        select_from_frontier(frontier, config["selection"])
        if frontier else None)
    global_oracle_gate = oracle_headroom_gate(headroom_rows)
    if selected is None:
      freeze_candidate = {
          "schema_version": RESULT_SCHEMA,
          "run_id": run_id,
          "status": "blocked_no_stage4_entry_candidate",
          "requires_human_review": True,
          "formal_freeze": False,
          "selected_candidate_id": None,
          "stage4_entry_allowed": False,
          "reason": (
              global_oracle_gate["reason"] if not global_oracle_gate["passed"]
              else "no_controller_passed_pressure_mechanism_validation_and_pareto_gates"),
      }
      pressure_contract = {
          "schema_version":
              "capd_proactive_stage3_stage7_pressure_contract_candidate_v1_0",
          "status": "blocked_no_stage3_selection",
          "selection_policy": "fixed_reactive_lru_only",
          "capd_or_oracle_used_for_pressure_selection": False,
          "pressure_overhead_claims_allowed": False,
          "test_used_for_stage3_selection": False,
          "pressure_test_generated": False,
      }
    else:
      controller = by_controller[selected["candidate_id"]]
      actual = controller["actual_by_workload"]
      pressure_cells = []
      watermarks = []
      excluded_pressure_cells = []
      for workload in WORKLOADS:
        cell = actual[workload]
        if not cell["all_train_blocks_covered"]:
          excluded_pressure_cells.append({
              "workload": workload,
              "reason": "insufficient_replacement_decisions_across_train_blocks",
              "coverage_id": cell["coverage_id"]})
          continue
        pressure_cells.append({
            "workload": workload,
            "window_records": controller["window_records"],
            "W_ref_quantile": controller["W_ref_quantile"],
            "W_ref": cell["W_ref"],
            "requested_ratio": controller["requested_ratio"],
            "D_pressure_raw": cell["D_pressure_raw"],
            "D_pressure": cell["D_pressure"],
            "minimum_capacity_applied": cell["minimum_capacity_applied"]})
        watermarks.append({
            "workload": workload, "D": cell["D_pressure"],
            "alpha": controller["alpha"], "beta": controller["beta"],
            "F_low": cell["F_low"], "F_target": cell["F_target"],
            "F_target_over_D": cell["F_target_over_D"]})
      freeze_candidate = {
          "schema_version": RESULT_SCHEMA,
          "run_id": run_id,
          "status": "candidate_ready_for_human_review",
          "requires_human_review": True,
          "formal_freeze": False,
          "selected_candidate_id": selected["candidate_id"],
          "stage4_entry_allowed": True,
          "selected_window_records": controller["window_records"],
          "W_ref_quantile": controller["W_ref_quantile"],
          "requested_pressure_ratio": controller["requested_ratio"],
          "alpha": controller["alpha"], "beta": controller["beta"],
          "b_max": controller["b_max"], "candidate_size_K": 8,
          "standard_capacity_matrix": standard_matrix,
          "pressure_capacity_matrix": pressure_cells,
          "excluded_pressure_capacity_cells": excluded_pressure_cells,
          "watermarks": watermarks,
          "selection_metrics": selected,
          "oracle_headroom_gate": global_oracle_gate,
          "validation_safety_passed": True,
          "all_command_auto_freeze": False,
      }
      pressure_contract = build_pressure_contract_candidate({
          "selected_window_records": controller["window_records"],
          "W_ref_quantile": controller["W_ref_quantile"],
          "standard_capacity_matrix": standard_matrix,
          "pressure_capacity_matrix": pressure_cells,
          "watermarks": watermarks,
          "b_max": controller["b_max"]}, config)
    rationale = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "selection_layers": [
            "pressure_coverage", "oracle_optimization_space",
            "active_mechanism_effect", "validation_safety",
            "pareto_frontier"],
        "gate_results": gate_rows,
        "global_oracle_gate": global_oracle_gate,
        "pareto_candidate_count": len(frontier),
        "selected_candidate_id": (
            None if selected is None else selected["candidate_id"]),
        "tie_break": config["selection"]["tie_break"],
        "human_review_required": True,
        "test_used": False,
    }
    _write_json_atomic(os.path.join(directory, "pareto_frontier.json"), {
        "schema_version": RESULT_SCHEMA, "frontier": frontier,
        "all_candidate_aggregates": aggregate_rows,
        "objectives": config["selection"]["pareto_objectives"]})
    _write_json_atomic(os.path.join(directory, "selection_rationale.json"),
                       rationale)
    _write_json_atomic(os.path.join(directory, "final_freeze_candidate.json"),
                       freeze_candidate)
    _write_json_atomic(os.path.join(
        directory, "pressure_generation_contract_candidate.json"),
        pressure_contract)
    _phase_finish(state, directory, "select", (
        "pareto_frontier.json", "selection_rationale.json",
        "final_freeze_candidate.json",
        "pressure_generation_contract_candidate.json"))
    return {"status": "select_complete", "output_directory": directory,
            "freeze_candidate_status": freeze_candidate["status"],
            "selected_candidate_id": freeze_candidate["selected_candidate_id"]}
  except BaseException as error:
    _phase_fail(state, directory, "select", error)
    raise


def run_verify(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  config, manifest, state, directory = _existing_context(
      config_path, run_id, project_root, output_root)
  if not _phase_start(state, directory, "verify", resume):
    return load_json(os.path.join(directory, "verification.json"))
  try:
    required = (
        "input_manifest.json", "resolved_config.json", "provenance.json",
        "run_identity.json", "windowed_wss_profiles.csv",
        "windowed_wss_summary.json", "blocked_calibration_manifest.json",
        "capacity_standard_matrix.json", "capacity_pressure_candidates.json",
        "watermark_candidates.json", "controller_candidates.json",
        "pressure_coverage.json", "policy_results.json",
        "oracle_headroom.json", "validation_safety.json",
        "pareto_frontier.json", "selection_rationale.json",
        "final_freeze_candidate.json",
        "pressure_generation_contract_candidate.json")
    artifacts = _artifact_rows(directory, required)
    validate_input_manifest(manifest)
    for name in required:
      if name.endswith(".json"):
        assert_no_forbidden_result_dependency(load_json(os.path.join(
            directory, name)))
    _require(not os.path.exists(os.path.join(directory, "final_freeze.json")) and
             not os.path.exists(os.path.join(
                 directory, "pressure_generation_contract.json")),
             "all/select/verify must not create formal freeze artifacts.")
    freeze_candidate = load_json(os.path.join(
        directory, "final_freeze_candidate.json"))
    ready = freeze_candidate["status"] == "candidate_ready_for_human_review"
    verification = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "status": (
            "STAGE3_STAGE7_FREEZE_CANDIDATE_VERIFIED" if ready else
            "STAGE3_STAGE7_GATES_BLOCKED"),
        "stage4_entry_allowed": ready,
        "formal_freeze_created": False,
        "all_auto_freeze": False,
        "input_entry_count": len(manifest["entries"]),
        "input_split_roles": list(ALLOWED_SPLITS),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "r1_authority_run_id": config["r1_authority"]["run_id"],
        "r1_input_identity_sha256":
            config["r1_authority"]["input_identity_sha256"],
        "pressure_selection_policy": "fixed_reactive_lru_only",
        "capd_or_oracle_used_for_pressure_selection": False,
        "pressure_overhead_claims_allowed": False,
        "stage4_executed": False,
        "model_training_executed": False,
    }
    verification.update(verification_boundary())
    _write_json_atomic(os.path.join(directory, "verification.json"),
                       verification)
    _phase_finish(state, directory, "verify", ("verification.json",))
    return verification
  except BaseException as error:
    _phase_fail(state, directory, "verify", error)
    raise


def run_freeze(
    config_path: str, run_id: str, project_root: str,
    candidate_path: str, confirmed: bool,
    output_root: Optional[str] = None
) -> Dict[str, Any]:
  require_freeze_confirmation(confirmed, candidate_path)
  config, _, state, directory = _existing_context(
      config_path, run_id, project_root, output_root)
  _require("verify" in state.get("completed_phases", []),
           "freeze requires completed verify.")
  _require(state.get("formal_freeze") is False,
           "This run is already formally frozen.")
  expected_path = os.path.realpath(os.path.join(
      directory, "final_freeze_candidate.json"))
  supplied_path = os.path.realpath(candidate_path)
  _require(supplied_path == expected_path,
           "freeze candidate must be this run's final_freeze_candidate.json.")
  candidate = load_json(supplied_path)
  _require(candidate.get("status") == "candidate_ready_for_human_review" and
           candidate.get("stage4_entry_allowed") is True,
           "Blocked Stage-3 candidate cannot be frozen.")
  verification = load_json(os.path.join(directory, "verification.json"))
  _require(verification.get("status") ==
           "STAGE3_STAGE7_FREEZE_CANDIDATE_VERIFIED",
           "Candidate verification did not pass.")
  contract_candidate_path = os.path.join(
      directory, "pressure_generation_contract_candidate.json")
  contract = load_json(contract_candidate_path)
  _require(contract.get("status") == "candidate_requires_human_review",
           "Pressure contract candidate is not freezeable.")
  frozen = copy.deepcopy(candidate)
  frozen.update({
      "status": "STAGE3_STAGE7_FORMALLY_FROZEN",
      "formal_freeze": True,
      "human_confirmation": True,
      "frozen_at": _utc_now(),
      "source_candidate_sha256": fingerprint_file(supplied_path),
      "stage4_entry_allowed": True})
  formal_contract = copy.deepcopy(contract)
  formal_contract.update({
      "status": "STAGE3_STAGE7_PRESSURE_CONTRACT_FORMALLY_FROZEN",
      "formal_freeze": True,
      "frozen_at": frozen["frozen_at"],
      "source_candidate_sha256": fingerprint_file(contract_candidate_path)})
  assert_no_forbidden_result_dependency(frozen)
  assert_no_forbidden_result_dependency(formal_contract)
  final_path = os.path.join(directory, "final_freeze.json")
  contract_path = os.path.join(directory, "pressure_generation_contract.json")
  _write_json_atomic(final_path, frozen)
  _write_json_atomic(contract_path, formal_contract)
  state["formal_freeze"] = True
  state["status"] = "formally_frozen"
  state["freeze_artifacts"] = _artifact_rows(directory, (
      "final_freeze.json", "pressure_generation_contract.json"))
  state["updated_at"] = _utc_now()
  _write_state(directory, state)
  return {
      "status": "STAGE3_STAGE7_FORMALLY_FROZEN",
      "output_directory": directory,
      "final_freeze": final_path,
      "pressure_generation_contract": contract_path,
  }


def run_all(
    config_path: str, run_id: str, project_root: str,
    output_root: Optional[str] = None, resume: bool = False
) -> Dict[str, Any]:
  functions = (
      run_preflight, run_profile, run_search, run_select, run_verify)
  result = None
  for function in functions:
    result = function(
        config_path, run_id, project_root, output_root=output_root,
        resume=resume)
  _require(result is not None, "all executed no phases.")
  return result
