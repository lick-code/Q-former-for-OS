# coding=utf-8
"""Stage-3 calibration for CAPD low-watermark active demotion.

The module is deliberately separate from model training and formal Test
evaluation.  It accepts only manifest-declared Train/Validation raw access
traces, profiles the working set and Reactive-LRU admission bursts, then uses
Proactive-LRU to calibrate watermarks and ``b_max``.
"""

from __future__ import annotations

import array
import collections
import copy
import csv
import datetime
import decimal
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from qmap.qmap_generator import is_header_row, parse_header, parse_int, parse_rw


SCHEMA_NAME = "capd_proactive_stage3_active_mechanism"
SCHEMA_VERSION = "capd_proactive_stage3_v1_0"
CONTRACT_VERSION = "CAPD-PROACTIVE-STAGE3-1.0"
MANIFEST_SCHEMA = "capd_proactive_stage3_input_manifest_v1_0"
RESULT_SCHEMA = "capd_proactive_stage3_result_v1_0"
AWAITING_INPUTS = "stage3_implemented_awaiting_calibration_inputs"
CAPACITY_READY = "stage3_capacity_results_ready_for_freeze"
RESULTS_READY = "stage3_calibration_results_ready_for_freeze"
VERIFIED = "stage3_verified"
CALIBRATION_POLICY = "proactive_lru"
PRE_WATERMARK_POLICY = "reactive_lru"
WORKING_SET_DEFINITION = "active_unique_pages_from_train_and_validation"
ALLOWED_SPLITS = ("train", "validation")
FORBIDDEN_SPLITS = ("test",)
WATERMARK_LABELS = ("small", "medium", "large")
RAW_METRICS = (
    "total_accesses", "dram_hits", "nvm_reads", "nvm_writes",
    "page_enter_dram_count", "total_demotions", "proactive_demotions",
    "reactive_demotions", "emergency_demotions",
    "number_of_proactive_cycles", "number_of_proactive_rounds",
    "minimum_free_frames", "average_free_frames",
    "free_frame_exhaustion_count", "accesses_below_F_low",
    "early_reuse_count")


class Stage3ContractError(ValueError):
  """Raised when stage-3 data or configuration violates the frozen boundary."""


class _CompactAccess(tuple):
  _FIELDS = {"page": 0, "rw": 1, "pc": 2}

  def __new__(cls, page, rw, pc):
    return tuple.__new__(cls, (page, rw, pc))

  def __getitem__(self, index):
    if isinstance(index, str):
      index = self._FIELDS[index]
    return tuple.__getitem__(self, index)

  def get(self, key, default=None):
    index = self._FIELDS.get(key)
    return default if index is None else tuple.__getitem__(self, index)


class CompactTrace(Sequence[Mapping[str, Any]]):
  """Reiterable trace backed by primitive arrays instead of millions of dicts."""

  def __init__(self):
    self.pages = array.array("Q")
    self.rws = bytearray()
    self.pcs = array.array("Q")

  def append(self, page: int, rw: int, pc: int) -> None:
    self.pages.append(page)
    self.rws.append(rw)
    self.pcs.append(pc)

  def __len__(self) -> int:
    return len(self.pages)

  def __iter__(self):
    return (
        _CompactAccess(
            self.pages[index], self.rws[index], self.pcs[index])
        for index in range(len(self.pages)))

  def __getitem__(self, index):
    if isinstance(index, slice):
      return [
          {"page": page, "rw": rw, "pc": pc}
          for page, rw, pc in zip(
              self.pages[index], self.rws[index], self.pcs[index])]
    return {
        "page": self.pages[index],
        "rw": self.rws[index],
        "pc": self.pcs[index],
    }

  def unique_pages(self):
    return set(self.pages)


def _read_compact_trace(csv_path: str, page_shift: int) -> Tuple[CompactTrace, str]:
  trace = CompactTrace()
  rw_source = None
  header_indices = None
  with open(csv_path, "r", encoding="utf-8", newline="") as input_file:
    reader = csv.reader(input_file)
    for row_number, row in enumerate(reader, start=1):
      if not row:
        continue
      if row_number == 1 and is_header_row(row):
        header_indices = parse_header(row)
        rw_source = (
            "real trace RW column" if header_indices[2] is not None
            else "fallback simulated rw = page & 1")
        continue
      if header_indices is not None:
        pc_index, address_index, rw_index = header_indices
        required_index = max(
            pc_index, address_index,
            -1 if rw_index is None else rw_index)
        _require(
            len(row) > required_index,
            "Line {} lacks a required CSV column: {}.".format(
                row_number, csv_path))
        pc = parse_int(row[pc_index])
        address = parse_int(row[address_index])
      else:
        _require(
            len(row) in (2, 3),
            "Line {} must have pc,address[,rw]: {}.".format(
                row_number, csv_path))
        if rw_source is None:
          rw_source = (
              "real trace RW column" if len(row) == 3
              else "fallback simulated rw = page & 1")
        _require(
            (len(row) == 3) == (rw_source == "real trace RW column"),
            "Inconsistent RW columns at line {}: {}.".format(
                row_number, csv_path))
        pc = parse_int(row[0])
        address = parse_int(row[1])
      page = address >> page_shift
      if header_indices is not None and header_indices[2] is not None:
        rw = parse_rw(row[header_indices[2]])
      elif header_indices is None and rw_source == "real trace RW column":
        rw = parse_rw(row[2])
      else:
        rw = page & 1
      _require(
          page >= 0 and pc >= 0,
          "Negative page/pc at line {}: {}.".format(row_number, csv_path))
      trace.append(page, rw, pc)
  return trace, rw_source or "fallback simulated rw = page & 1"


def _reject_json_constant(value: str) -> None:
  raise Stage3ContractError("Non-finite JSON value is forbidden: {}".format(
      value))


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
  result: Dict[str, Any] = {}
  for key, value in pairs:
    if key in result:
      raise Stage3ContractError("Duplicate JSON key: {}".format(key))
    result[key] = value
  return result


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(
        input_file, object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant)


def write_json(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    json.dump(
        value, output_file, ensure_ascii=False, sort_keys=True, indent=2,
        allow_nan=False)
    output_file.write("\n")


def write_jsonl(path: str, rows: Iterable[Mapping[str, Any]]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    for row in rows:
      output_file.write(json.dumps(
          row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
          allow_nan=False))
      output_file.write("\n")


def _require(condition: bool, message: str) -> None:
  if not condition:
    raise Stage3ContractError(message)


def _positive_integer(value: Any, field: str) -> int:
  _require(
      isinstance(value, int) and not isinstance(value, bool) and value > 0,
      "{} must be a positive integer.".format(field))
  return int(value)


def _non_negative_integer(value: Any, field: str) -> int:
  _require(
      isinstance(value, int) and not isinstance(value, bool) and value >= 0,
      "{} must be a non-negative integer.".format(field))
  return int(value)


def _finite_number(value: Any, field: str) -> float:
  _require(
      isinstance(value, (int, float)) and not isinstance(value, bool),
      "{} must be numeric.".format(field))
  result = float(value)
  _require(math.isfinite(result), "{} must be finite.".format(field))
  return result


def _utc_now() -> str:
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ")


def _fingerprint_value(value: Any) -> str:
  payload = json.dumps(
      value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
      allow_nan=False).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


def _git_state(project_root: str) -> Dict[str, Any]:
  def command(*arguments: str) -> Optional[str]:
    try:
      return subprocess.check_output(
          list(arguments), cwd=project_root, stderr=subprocess.DEVNULL,
          text=True).strip()
    except (OSError, subprocess.CalledProcessError):
      return None

  commit = command("git", "rev-parse", "HEAD")
  status = command("git", "status", "--porcelain")
  return {
      "code_commit": commit,
      "dirty_worktree": None if status is None else bool(status),
      "dirty_diff_fingerprint": (
          None if status is None else hashlib.sha256(
              status.encode("utf-8")).hexdigest()),
  }


def validate_config(
    value: Mapping[str, Any], stage0: Optional[Mapping[str, Any]] = None,
    stage2: Optional[proactive_cost.CostConfiguration] = None
) -> Mapping[str, Any]:
  """Validates the predeclared stage-3 calibration contract."""
  _require(isinstance(value, Mapping), "Stage-3 config must be an object.")
  required = {
      "schema_name", "schema_version", "contract_version", "stage_status",
      "input_manifest", "allowed_splits", "forbidden_splits",
      "working_set_definition", "page_size_bytes",
      "capacity_profile_candidates", "capacity_rounding_rule",
      "pressure_distinguishability_rule", "burst_profiler_policy",
      "burst_windows", "quantile_method", "watermark_candidate_rule",
      "watermark_candidates", "watermark_selection_rule",
      "b_max_candidates", "b_max_selection_rule", "ranking_policy",
      "cost_profile", "stage3_calibration_candidate_bound",
      "stage3_candidate_bound_status", "candidate_bound_invariance_values",
      "history_window_size", "early_reuse_window", "random_seed",
      "output_root", "provenance"}
  missing = sorted(required - set(value))
  _require(not missing, "Stage-3 config missing fields: {}.".format(missing))
  _require(value["schema_name"] == SCHEMA_NAME, "Unexpected schema_name.")
  _require(value["schema_version"] == SCHEMA_VERSION, "Unexpected schema_version.")
  _require(
      value["contract_version"] == CONTRACT_VERSION,
      "Unexpected contract_version.")
  _require(value["stage_status"] == AWAITING_INPUTS, "Initial stage status must await inputs.")
  _require(tuple(value["allowed_splits"]) == ALLOWED_SPLITS, "Only Train/Validation are allowed.")
  _require(tuple(value["forbidden_splits"]) == FORBIDDEN_SPLITS, "Test must be forbidden.")
  _require(
      value["working_set_definition"] == WORKING_SET_DEFINITION,
      "Unexpected Working Set definition.")
  _require(value["page_size_bytes"] == 4096, "Stage 3 requires 4 KiB pages.")
  _require(value["ranking_policy"] == CALIBRATION_POLICY, "Only Proactive-LRU may calibrate stage 3.")
  _require(value["burst_profiler_policy"] == PRE_WATERMARK_POLICY, "Burst profiling must use Reactive-LRU.")
  _require(tuple(value["burst_windows"]) == (100, 500, 1000), "Burst windows must be 100/500/1000.")
  _require(value["quantile_method"] == "nearest_rank", "Quantile method must be nearest_rank.")
  _require(value["b_max_candidates"] == [1, 2, 4], "b_max candidates must be [1,2,4].")
  bound = _positive_integer(
      value["stage3_calibration_candidate_bound"],
      "stage3_calibration_candidate_bound")
  _require(bound > max(value["b_max_candidates"]), "Calibration K proxy must exceed max(b_max).")
  _require(
      value["stage3_candidate_bound_status"] == "non_formal_calibration_proxy",
      "Stage-3 K must remain a non-formal proxy.")
  invariance = value["candidate_bound_invariance_values"]
  _require(
      isinstance(invariance, list) and len(invariance) >= 2 and
      all(isinstance(item, int) and item > max(value["b_max_candidates"])
          for item in invariance),
      "At least two legal K proxy values are required.")
  _require(bound in invariance, "Primary calibration K proxy must be included in the invariance values.")
  _require(value["history_window_size"] == 10, "Stage-3 history window must be 10.")
  _require(value["early_reuse_window"] == 64, "Stage-3 early-reuse window must be 64.")
  _positive_integer(value["random_seed"], "random_seed")
  _require(
      isinstance(value["output_root"], str) and value["output_root"],
      "output_root must be a non-empty string.")
  _require(value["cost_profile"] == {
      "name": "default",
      "weights": {
          "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
      "status": "stage2_frozen",
  }, "Stage 3 must use the frozen default Cost profile.")
  profiles = value["capacity_profile_candidates"]
  _require(profiles == {
      "primary": [0.2, 0.4, 0.6],
      "fallback": [0.1, 0.2, 0.4],
  }, "Capacity candidates must be primary 20/40/60 and fallback 10/20/40.")
  _require(
      value["capacity_rounding_rule"] ==
      "decimal_ceiling_ratio_times_working_set_minimum_one_no_clamp",
      "Unexpected capacity rounding rule.")
  pressure = value["pressure_distinguishability_rule"]
  pressure_required = {
      "min_accesses_per_run", "monotonic_tolerance",
      "minimum_nvm_access_rate_range", "minimum_demotion_rate_range",
      "near_no_migration_rate", "chronic_exhaustion_rate",
      "minimum_ordered_indicators"}
  _require(
      isinstance(pressure, Mapping) and
      not (pressure_required - set(pressure)),
      "Pressure rule is incomplete.")
  for key in pressure_required - {"min_accesses_per_run", "minimum_ordered_indicators"}:
    _finite_number(pressure[key], "pressure.{}".format(key))
  _positive_integer(pressure["min_accesses_per_run"], "pressure.min_accesses_per_run")
  _positive_integer(pressure["minimum_ordered_indicators"], "pressure.minimum_ordered_indicators")
  candidate_rule = value["watermark_candidate_rule"]
  _require(
      candidate_rule == {
          "burst_window": 100,
          "source_split": "validation",
          "aggregate_across_runs": "maximum",
          "small_source_quantile": "p50",
          "medium_source_quantile": "p95",
          "large_source_quantile": "p99",
          "target_rule": "max(2,ceil(source)); enforce_strict_label_order_by_previous_plus_one",
          "low_rule": "ceil(F_target/2)",
          "overflow_rule": "mark_illegal_without_clamp",
      }, "Unexpected watermark candidate rule.")
  _require(value["watermark_candidates"] is None, "Formal watermarks must not be prefilled.")
  _require(value["input_manifest"] is None, "Initial manifest must remain unresolved.")
  _require(value["watermark_selection_rule"] == {
      "candidate_order":
          "capacity_and_state,exhaustion,emergency,early_reuse,total_demotions,nvm_io,smaller_reserve",
      "capd_results_used": False,
      "macro_average": "unweighted_across_workload_capacity_runs",
      "policy": "proactive_lru",
      "test_used": False,
      "worst_case_reported": True,
  }, "Unexpected watermark selection rule.")
  _require(value["b_max_selection_rule"] == {
      "candidate_order":
          "state_invariants,exhaustion,emergency,validation_default_cost,nvm_write,early_reuse,rounds,smaller_b_max",
      "capd_latency_used": False,
      "capd_results_used": False,
      "split": "validation",
      "test_used": False,
      "tie_break": "smaller_b_max",
  }, "Unexpected b_max selection rule.")
  _require(
      value["provenance"].get("capd_used_for_selection") is False and
      value["provenance"].get("test_used") is False and
      value["provenance"].get("candidate_filter") == "disabled",
      "Provenance must forbid CAPD, Test, and the candidate filter.")
  if stage0 is not None:
    finals_config.validate_config(stage0)
    _require(
        stage0["freeze_status"]["stage1_replay"] == "frozen" and
        stage0["freeze_status"]["stage2_cost_profile"] == "frozen",
        "Stages 1 and 2 must be frozen.")
    _require(
        stage0["freeze_status"]["stage3_active_mechanism"] == "pending",
        "Stage 3 must remain pending before calibration.")
    for key in ("stage4_candidate", "stage4_training", "stage7_workload", "formal_test"):
      _require(stage0["freeze_status"][key] == "pending", "{} must remain pending.".format(key))
    _require(stage0["method"]["selector"] == "disabled", "Candidate selector must remain disabled.")
  if stage2 is not None:
    _require(stage2.stage_status == proactive_cost.STAGE_STATUS, "Stage 2 is not verified.")
    _require(
        stage2.profiles["default"].weights_dict() ==
        value["cost_profile"]["weights"],
        "Stage-2 default Cost weights do not match stage 3.")
  return value


def validate_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Input manifest must be an object.")
  required = {
      "schema_version", "calibration_kind", "path_base",
      "test_used_for_parameter_selection", "entries"}
  _require(not (required - set(value)), "Input manifest is incomplete.")
  _require(value["schema_version"] == MANIFEST_SCHEMA, "Unexpected manifest schema.")
  _require(
      value["calibration_kind"] in ("real_train_validation", "synthetic_smoke"),
      "Unsupported calibration_kind.")
  _require(
      value["path_base"] in ("manifest_directory", "project_root"),
      "Unsupported path_base.")
  _require(
      value["test_used_for_parameter_selection"] is False,
      "Formal Test cannot be used for parameter selection.")
  entries = value["entries"]
  _require(isinstance(entries, list) and entries, "Manifest entries cannot be empty.")
  seen = set()
  workloads: Dict[str, set] = collections.defaultdict(set)
  for index, entry in enumerate(entries):
    context = "entries[{}]".format(index)
    _require(isinstance(entry, Mapping), "{} must be an object.".format(context))
    fields = {
        "workload", "split", "role", "trace_path", "page_shift",
        "source_kind", "formal_test"}
    _require(not (fields - set(entry)), "{} is incomplete.".format(context))
    _require(isinstance(entry["workload"], str) and entry["workload"], "{} workload is invalid.".format(context))
    _require(entry["split"] in ALLOWED_SPLITS, "{} split must be Train/Validation.".format(context))
    _require(
        entry["role"] in ("training_and_fit", "parameter_selection") and
        ((entry["split"] == "train" and entry["role"] == "training_and_fit") or
         (entry["split"] == "validation" and entry["role"] == "parameter_selection")),
        "{} split/role mismatch.".format(context))
    _require(entry["formal_test"] is False, "{} cannot be formal Test.".format(context))
    _require(entry["source_kind"] == "raw_access_trace", "{} must be a raw access trace.".format(context))
    _require(isinstance(entry["trace_path"], str) and entry["trace_path"], "{} trace_path is invalid.".format(context))
    _non_negative_integer(entry["page_shift"], "{}.page_shift".format(context))
    identity = (entry["workload"], entry["split"])
    _require(identity not in seen, "Duplicate workload/split: {}.".format(identity))
    seen.add(identity)
    workloads[entry["workload"]].add(entry["split"])
  for workload, splits in workloads.items():
    _require(
        splits == set(ALLOWED_SPLITS),
        "{} must provide both Train and Validation.".format(workload))
  return value


def _resolve_trace_path(
    entry: Mapping[str, Any], manifest: Mapping[str, Any],
    manifest_path: str, project_root: str
) -> str:
  base = (
      os.path.dirname(os.path.abspath(manifest_path))
      if manifest["path_base"] == "manifest_directory"
      else os.path.abspath(project_root))
  path = os.path.abspath(os.path.join(base, entry["trace_path"]))
  _require(os.path.isfile(path), "Trace does not exist: {}".format(path))
  return path


def load_inputs(
    manifest_path: str, project_root: str
) -> Tuple[Mapping[str, Any], Dict[str, Dict[str, Sequence[Any]]], List[Dict[str, Any]]]:
  manifest = validate_manifest(load_json(manifest_path))
  traces: Dict[str, Dict[str, Sequence[Any]]] = collections.defaultdict(dict)
  resolved_entries = []
  for entry in manifest["entries"]:
    path = _resolve_trace_path(entry, manifest, manifest_path, project_root)
    trace, rw_source = _read_compact_trace(path, entry["page_shift"])
    _require(trace, "Empty trace is forbidden: {}".format(path))
    traces[entry["workload"]][entry["split"]] = trace
    resolved = copy.deepcopy(entry)
    resolved.update({
        "resolved_trace_path": path,
        "trace_fingerprint": finals_config.fingerprint_file(path),
        "trace_accesses": len(trace),
        "rw_source": rw_source,
    })
    resolved_entries.append(resolved)
  return manifest, dict(traces), resolved_entries


def working_set_summary(
    traces: Mapping[str, Mapping[str, Sequence[Any]]],
    page_size_bytes: int = 4096
) -> List[Dict[str, Any]]:
  results = []
  _positive_integer(page_size_bytes, "page_size_bytes")
  for workload in sorted(traces):
    train = traces[workload].get("train")
    validation = traces[workload].get("validation")
    _require(train is not None and validation is not None, "{} lacks Train/Validation.".format(workload))
    _require(train and validation, "{} has an empty split.".format(workload))
    train_pages = (
        train.unique_pages() if isinstance(train, CompactTrace)
        else {item["page"] for item in train})
    validation_pages = (
        validation.unique_pages() if isinstance(validation, CompactTrace)
        else {item["page"] for item in validation})
    union = train_pages | validation_pages
    _require(union, "{} has an empty Working Set.".format(workload))
    results.append({
        "schema_version": RESULT_SCHEMA,
        "workload": workload,
        "working_set_definition": WORKING_SET_DEFINITION,
        "train_unique_pages": len(train_pages),
        "validation_unique_pages": len(validation_pages),
        "train_validation_union_pages": len(union),
        "overlap_pages": len(train_pages & validation_pages),
        "page_size_bytes": page_size_bytes,
        "trace_accesses_train": len(train),
        "trace_accesses_validation": len(validation),
    })
  return results


def capacity_pages(working_set_pages: int, ratio: float) -> Dict[str, Any]:
  pages = _positive_integer(working_set_pages, "working_set_pages")
  ratio_value = _finite_number(ratio, "capacity_ratio")
  _require(0 < ratio_value <= 1, "capacity_ratio must lie in (0,1].")
  raw = decimal.Decimal(str(pages)) * decimal.Decimal(str(ratio_value))
  resolved = int(raw.to_integral_value(rounding=decimal.ROUND_CEILING))
  _require(resolved >= 1, "Capacity rounding cannot produce zero pages.")
  _require(resolved <= pages, "Capacity result cannot exceed Working Set.")
  return {
      "working_set_pages": pages,
      "capacity_ratio": ratio_value,
      "raw_capacity_pages": str(raw),
      "dram_capacity_pages": resolved,
      "rounding_rule":
          "decimal_ceiling_ratio_times_working_set_minimum_one_no_clamp",
  }


def nearest_rank(values: Sequence[int], percentile: float) -> Optional[int]:
  if not values:
    return None
  p = _finite_number(percentile, "percentile")
  _require(0 <= p <= 1, "percentile must lie in [0,1].")
  ordered = sorted(_non_negative_integer(item, "quantile item") for item in values)
  rank = max(1, int(math.ceil(p * len(ordered))))
  return ordered[rank - 1]


def burst_statistics(
    page_enter_flags: Sequence[bool], window_size: int
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  size = _positive_integer(window_size, "window_size")
  flags = [1 if bool(value) else 0 for value in page_enter_flags]
  full_count = len(flags) // size
  full_windows = [
      sum(flags[index * size:(index + 1) * size])
      for index in range(full_count)]
  tail = flags[full_count * size:]
  stats = {
      "window_size": size,
      "window_count": len(full_windows),
      "mean": statistics.mean(full_windows) if full_windows else None,
      "p50": nearest_rank(full_windows, 0.50),
      "p95": nearest_rank(full_windows, 0.95),
      "p99": nearest_rank(full_windows, 0.99),
      "max": max(full_windows) if full_windows else None,
      "total_page_enter_dram": sum(flags),
      "page_enter_dram_rate": (
          sum(flags) / float(len(flags)) if flags else None),
      "tail_accesses": len(tail),
      "tail_page_enter_dram": sum(tail),
      "tail_in_quantiles": False,
      "alignment": "access_index_zero_non_overlapping",
      "quantile_method": "nearest_rank",
  }
  rows = [
      {
          "window_size": size,
          "window_index": index,
          "start_access": index * size,
          "end_access": (index + 1) * size,
          "page_enter_dram_count": count,
          "complete_window": True,
      }
      for index, count in enumerate(full_windows)]
  if tail:
    rows.append({
        "window_size": size,
        "window_index": full_count,
        "start_access": full_count * size,
        "end_access": len(flags),
        "page_enter_dram_count": sum(tail),
        "complete_window": False,
    })
  return stats, rows


def _early_reuse(summary: Mapping[str, Any]) -> Tuple[Optional[float], str]:
  count = _non_negative_integer(summary["early_reuse_count"], "early_reuse_count")
  demotions = _non_negative_integer(summary["proactive_demotions"], "proactive_demotions")
  if demotions == 0:
    return None, "undefined_no_proactive_demotions"
  return count / float(demotions), "defined"


def _default_cost(summary: Mapping[str, Any]) -> Tuple[int, Dict[str, int]]:
  components = {
      "dram_hit_cost": int(summary["dram_hits"]),
      "nvm_read_cost": 2 * int(summary["nvm_reads"]),
      "nvm_write_cost": 8 * int(summary["nvm_writes"]),
      "demotion_cost": 10 * int(summary["total_demotions"]),
  }
  return sum(components.values()), components


def _replay_row(
    stage0: Mapping[str, Any], trace: Sequence[Any],
    workload: str, split: str, capacity: Mapping[str, Any], policy: str,
    F_low: Optional[int] = None, F_target: Optional[int] = None,
    b_max: Optional[int] = None, candidate_bound: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  if policy == PRE_WATERMARK_POLICY:
    parameters = proactive_replay.ReplayParameters(
        policy_name=policy,
        dram_capacity_pages=capacity["dram_capacity_pages"],
        history_window_size=10,
        early_reuse_window=64)
  else:
    _require(policy == CALIBRATION_POLICY, "Only Reactive/Proactive LRU are allowed.")
    parameters = proactive_replay.ReplayParameters(
        policy_name=policy,
        dram_capacity_pages=capacity["dram_capacity_pages"],
        F_low=F_low, F_target=F_target, b_max=b_max,
        candidate_size_K=candidate_bound,
        history_window_size=10, early_reuse_window=64)
  result = proactive_replay.ProactiveReplay(
      stage0, parameters, invariant_mode="boundary", record_details=False,
      capture_page_enter_flags=(policy == PRE_WATERMARK_POLICY)).run(
          trace, copy_trace=False, compact=True)
  summary = result["summary"]
  cost, components = _default_cost(summary)
  early_rate, early_status = _early_reuse(summary)
  row = {
      "schema_version": RESULT_SCHEMA,
      "workload": workload,
      "split": split,
      "policy": policy,
      "capacity_ratio": capacity["capacity_ratio"],
      "dram_capacity_pages": capacity["dram_capacity_pages"],
      "F_low": F_low,
      "F_target": F_target,
      "b_max": b_max,
      "stage3_calibration_candidate_bound": candidate_bound,
      "candidate_bound_status": (
          None if candidate_bound is None
          else "non_formal_calibration_proxy"),
      "default_weighted_cost": cost,
      "default_weighted_cost_per_access": cost / float(summary["total_accesses"]),
      "cost_components": components,
      "early_reuse_rate": early_rate,
      "early_reuse_rate_status": early_status,
  }
  for metric in RAW_METRICS:
    row[metric] = summary[metric]
  row["actual_candidate_round_count"] = result[
      "actual_candidate_round_count"]
  row["actual_candidate_counts_by_round"] = result[
      "actual_candidate_counts_by_round"]
  row["actual_candidate_count_min"] = result["actual_candidate_count_min"]
  row["actual_candidate_count_max"] = result["actual_candidate_count_max"]
  row["full_invariant_checks"] = result["full_invariant_checks"]
  row["state_invariants_passed"] = True
  return row, result


def _pressure_rates(row: Mapping[str, Any]) -> Dict[str, float]:
  accesses = float(row["total_accesses"])
  return {
      "page_enter_dram_rate": row["page_enter_dram_count"] / accesses,
      "nvm_access_rate": (row["nvm_reads"] + row["nvm_writes"]) / accesses,
      "demotion_rate": row["total_demotions"] / accesses,
      "exhaustion_rate": row["free_frame_exhaustion_count"] / accesses,
      "reactive_demotion_rate": row["reactive_demotions"] / accesses,
  }


def audit_pressure(
    rows: Sequence[Mapping[str, Any]], rule: Mapping[str, Any],
    profile_name: str
) -> Dict[str, Any]:
  grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = collections.defaultdict(list)
  for row in rows:
    grouped[(row["workload"], row["split"])].append(row)
  run_audits = []
  all_distinguishable = True
  all_reliable = True
  for identity in sorted(grouped):
    ordered = sorted(grouped[identity], key=lambda item: item["capacity_ratio"])
    rates = [_pressure_rates(item) for item in ordered]
    reliable = all(
        item["total_accesses"] >= rule["min_accesses_per_run"]
        for item in ordered)
    indicator_names = (
        "page_enter_dram_rate", "nvm_access_rate", "demotion_rate",
        "reactive_demotion_rate")
    ordered_indicators = 0
    for name in indicator_names:
      values = [item[name] for item in rates]
      if all(
          values[index] + rule["monotonic_tolerance"] >= values[index + 1]
          for index in range(len(values) - 1)):
        ordered_indicators += 1
    nvm_range = max(item["nvm_access_rate"] for item in rates) - min(
        item["nvm_access_rate"] for item in rates)
    demotion_range = max(item["demotion_rate"] for item in rates) - min(
        item["demotion_rate"] for item in rates)
    near_no_migration = max(item["demotion_rate"] for item in rates) < (
        rule["near_no_migration_rate"])
    chronic_exhaustion = min(item["exhaustion_rate"] for item in rates) > (
        rule["chronic_exhaustion_rate"])
    distinguishable = (
        reliable and
        ordered_indicators >= rule["minimum_ordered_indicators"] and
        (nvm_range >= rule["minimum_nvm_access_rate_range"] or
         demotion_range >= rule["minimum_demotion_rate_range"]) and
        not near_no_migration and not chronic_exhaustion)
    all_distinguishable = all_distinguishable and distinguishable
    all_reliable = all_reliable and reliable
    run_audits.append({
        "workload": identity[0],
        "split": identity[1],
        "profile_name": profile_name,
        "reliable_length": reliable,
        "ordered_indicators": ordered_indicators,
        "nvm_access_rate_range": nvm_range,
        "demotion_rate_range": demotion_range,
        "all_capacities_near_no_migration": near_no_migration,
        "all_capacities_chronically_exhausted": chronic_exhaustion,
        "distinguishable": distinguishable,
        "rates_by_capacity": [
            dict({"capacity_ratio": row["capacity_ratio"]}, **rate)
            for row, rate in zip(ordered, rates)],
    })
  return {
      "schema_version": RESULT_SCHEMA,
      "profile_name": profile_name,
      "rule": copy.deepcopy(rule),
      "all_runs_reliable": all_reliable,
      "all_workload_splits_distinguishable": all_distinguishable,
      "run_audits": run_audits,
  }


def choose_capacity_profile(
    primary_audit: Mapping[str, Any], fallback_audit: Mapping[str, Any]
) -> Dict[str, Any]:
  if primary_audit["all_workload_splits_distinguishable"]:
    return {
        "recommended_profile": "primary",
        "recommended_ratios": [0.2, 0.4, 0.6],
        "status": CAPACITY_READY,
        "reason": "primary_20_40_60_passed_predeclared_pressure_rule",
        "requires_user_confirmation": True,
    }
  if fallback_audit["all_workload_splits_distinguishable"]:
    return {
        "recommended_profile": "fallback",
        "recommended_ratios": [0.1, 0.2, 0.4],
        "status": CAPACITY_READY,
        "reason": "primary_failed_and_fallback_10_20_40_passed_predeclared_pressure_rule",
        "requires_user_confirmation": True,
    }
  return {
      "recommended_profile": None,
      "recommended_ratios": None,
      "status": CAPACITY_READY,
      "reason": "neither_capacity_profile_passed_predeclared_pressure_rule",
      "requires_user_confirmation": True,
  }


def generate_watermark_candidates(
    burst_stats: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
  source = [
      item for item in burst_stats
      if item["split"] == "validation" and item["window_size"] == 100]
  _require(source, "No Validation window-100 burst statistics.")
  quantiles = {
      "small": max(item["p50"] or 0 for item in source),
      "medium": max(item["p95"] or 0 for item in source),
      "large": max(item["p99"] or 0 for item in source),
  }
  result = []
  previous = 1
  for label in WATERMARK_LABELS:
    raw_source = quantiles[label]
    target = max(2, int(math.ceil(raw_source)), previous + 1)
    low = int(math.ceil(target / 2.0))
    _require(0 < low < target, "Generated watermark is internally illegal.")
    result.append({
        "label": label,
        "F_low": low,
        "F_target": target,
        "source_window": 100,
        "source_split": "validation",
        "source_quantile": {
            "small": "p50", "medium": "p95", "large": "p99"}[label],
        "source_aggregate": "maximum_across_workload_capacity_runs",
        "source_value": raw_source,
        "generation_rule":
            "target=max(2,ceil(source),previous_target+1);low=ceil(target/2)",
    })
    previous = target
  return result


def _macro_average(rows: Sequence[Mapping[str, Any]], field: str) -> Optional[float]:
  values = [row[field] for row in rows if row.get(field) is not None]
  return statistics.mean(values) if values else None


def summarize_candidate_rows(
    rows: Sequence[Mapping[str, Any]], candidate_field: str
) -> List[Dict[str, Any]]:
  grouped: Dict[Any, List[Mapping[str, Any]]] = collections.defaultdict(list)
  for row in rows:
    grouped[row[candidate_field]].append(row)
  summaries = []
  for candidate in sorted(grouped, key=lambda item: str(item)):
    items = grouped[candidate]
    legal_items = [
        item for item in items
        if item.get("legal", True) and item.get("state_invariants_passed")]
    worst_case = {
        "free_frame_exhaustion_count": None,
        "emergency_demotions": None,
        "early_reuse_rate": None,
        "total_demotions": None,
        "nvm_io": None,
    }
    if legal_items:
      worst_case = {
          "free_frame_exhaustion_count": max(
              item["free_frame_exhaustion_count"] for item in legal_items),
          "emergency_demotions": max(
              item["emergency_demotions"] for item in legal_items),
          "early_reuse_rate": max(
              (item["early_reuse_rate"] for item in legal_items
               if item["early_reuse_rate"] is not None), default=None),
          "total_demotions": max(
              item["total_demotions"] for item in legal_items),
          "nvm_io": max(
              item["nvm_reads"] + item["nvm_writes"]
              for item in legal_items),
      }
    summaries.append({
        candidate_field: candidate,
        "run_count": len(items),
        "all_legal": all(item.get("legal", True) for item in items),
        "all_invariants_passed": all(item["state_invariants_passed"] for item in items),
        "macro_average": {
            field: _macro_average(legal_items, field)
            for field in (
                "default_weighted_cost_per_access", "dram_hits", "nvm_reads",
                "nvm_writes", "total_demotions", "proactive_demotions",
                "reactive_demotions", "emergency_demotions",
                "early_reuse_rate", "number_of_proactive_rounds",
                "rounds_per_cycle", "free_frame_exhaustion_count",
                "minimum_free_frames", "average_free_frames",
                "accesses_below_F_low")
        },
        "worst_case": worst_case,
    })
  return summaries


def select_watermark(
    summaries: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
  by_label = {item["label"]: item for item in candidates}
  feasible = [
      item for item in summaries
      if item["all_legal"] and item["all_invariants_passed"]]
  if not feasible:
    return {
        "selected_label": None, "selected_watermark": None,
        "status": "blocked_no_globally_legal_watermark",
        "requires_user_confirmation": True,
        "ranking": [],
    }

  def key(item: Mapping[str, Any]) -> Tuple[Any, ...]:
    macro = item["macro_average"]
    worst = item["worst_case"]
    early = macro["early_reuse_rate"]
    candidate = by_label[item["watermark_label"]]
    return (
        worst["free_frame_exhaustion_count"],
        macro["free_frame_exhaustion_count"],
        worst["emergency_demotions"],
        macro["emergency_demotions"],
        float("inf") if early is None else early,
        macro["total_demotions"],
        macro["nvm_reads"] + macro["nvm_writes"],
        candidate["F_target"],
        candidate["F_low"],
    )

  ranking = sorted(feasible, key=key)
  selected = ranking[0]
  return {
      "selected_label": selected["watermark_label"],
      "selected_watermark": copy.deepcopy(by_label[selected["watermark_label"]]),
      "status": "recommended_by_predeclared_watermark_rule",
      "requires_user_confirmation": True,
      "selection_key_order": [
          "worst_exhaustion", "macro_exhaustion", "worst_emergency",
          "macro_emergency", "macro_early_reuse", "macro_total_demotions",
          "macro_nvm_io", "smaller_F_target", "smaller_F_low"],
      "ranking": [item["watermark_label"] for item in ranking],
  }


def select_bmax(summaries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  feasible = [
      item for item in summaries
      if item["all_legal"] and item["all_invariants_passed"]]
  if not feasible:
    return {
        "selected_b_max": None, "status": "blocked_no_feasible_bmax",
        "requires_user_confirmation": True, "ranking": []}

  def key(item: Mapping[str, Any]) -> Tuple[Any, ...]:
    macro = item["macro_average"]
    worst = item["worst_case"]
    early = macro["early_reuse_rate"]
    return (
        worst["free_frame_exhaustion_count"],
        macro["free_frame_exhaustion_count"],
        worst["emergency_demotions"],
        macro["emergency_demotions"],
        macro["default_weighted_cost_per_access"],
        macro["nvm_writes"],
        float("inf") if early is None else early,
        macro["number_of_proactive_rounds"],
        item["b_max"],
    )

  ranking = sorted(feasible, key=key)
  return {
      "selected_b_max": ranking[0]["b_max"],
      "status": "recommended_by_predeclared_bmax_rule",
      "requires_user_confirmation": True,
      "selection_key_order": [
          "worst_exhaustion", "macro_exhaustion", "worst_emergency",
          "macro_emergency", "macro_default_cost_per_access",
          "macro_nvm_writes", "macro_early_reuse",
          "macro_round_count", "smaller_b_max"],
      "ranking": [item["b_max"] for item in ranking],
  }


def _capacity_matrix(
    working_sets: Sequence[Mapping[str, Any]],
    ratios: Sequence[float]
) -> Dict[str, List[Dict[str, Any]]]:
  result = {}
  for item in working_sets:
    result[item["workload"]] = [
        capacity_pages(item["train_validation_union_pages"], ratio)
        for ratio in ratios]
  return result


def _write_csv(path: str, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8-sig", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
      writer.writerow(row)


def _report_markdown(payload: Mapping[str, Any]) -> str:
  decision = payload["selection_decision"]
  lines = [
      "# CAPD 主动降级阶段 3 校准报告",
      "",
      "- 状态：`{}`".format(payload["stage_status"]),
      "- 数据类型：`{}`".format(payload["calibration_kind"]),
      "- Test 是否用于选择：否",
      "- CAPD 是否用于参数选择：否",
      "- 标定策略：Reactive-LRU（突发/压力）与 Proactive-LRU（水位/b_max）",
      "",
      "## Working Set",
      "",
  ]
  for item in payload["working_set_summary"]:
    lines.append(
        "- {workload}: Train={train_unique_pages}, Validation={validation_unique_pages}, "
        "Union={train_validation_union_pages}, overlap={overlap_pages}".format(**item))
  lines.extend([
      "",
      "## 容量规则",
      "",
      "- 推荐：`{}`".format(
          decision["capacity"].get("recommended_ratios")),
      "- 原因：`{}`".format(decision["capacity"]["reason"]),
      "- 仍需用户确认：是",
      "",
      "## 水位与 b_max",
      "",
      "- 水位建议：`{}`".format(
          decision["watermark"].get("selected_watermark")),
      "- b_max 建议：`{}`".format(
          decision["b_max"].get("selected_b_max")),
      "- K 代理不变性：`{}`".format(
          decision["candidate_bound_invariance"]["status"]),
      "- K 代理不进入正式 method.candidate_size_K。",
      "",
      "## 边界",
      "",
      "- 未读取 Test，未运行 CAPD，未训练模型，未修改阶段 0 主配置。",
      "- 该报告只给出预声明规则产生的冻结候选；在用户确认和服务器回归完成前不得标记 stage3_verified。",
      "",
  ])
  return "\n".join(lines)


def _write_json_atomic(path: str, value: Any) -> None:
  temporary = "{}.tmp-{}".format(path, os.getpid())
  write_json(temporary, value)
  os.replace(temporary, path)


def _append_jsonl(path: str, value: Mapping[str, Any]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "a", encoding="utf-8", newline="\n") as output_file:
    output_file.write(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False))
    output_file.write("\n")
    output_file.flush()
    os.fsync(output_file.fileno())


class _RunJournal(object):
  """Durable per-replay checkpoints for interruption-safe calibration."""

  def __init__(
      self, directory: str, identity: Mapping[str, Any], resume: bool
  ) -> None:
    self.directory = directory
    self.state_path = os.path.join(directory, "run_state.json")
    self.log_path = os.path.join(directory, "logs", "progress.jsonl")
    self.checkpoint_directory = os.path.join(directory, "checkpoints")
    self.identity = copy.deepcopy(identity)
    self.resumed = False
    if os.path.exists(directory):
      _require(resume, "Incomplete run already exists; pass --resume: {}".format(
          directory))
      if os.path.isfile(self.state_path):
        state = load_json(self.state_path)
        _require(
            state.get("identity") == self.identity,
            "Resume refused because config, manifest, or inputs changed.")
        self.state = state
        self.resumed = True
        self.state["status"] = "running"
        self.state["resumed_at"] = _utc_now()
        self.state.pop("error_type", None)
        self.state.pop("error_message", None)
      else:
        _require(
            not os.listdir(directory),
            "Cannot adopt a non-empty legacy run without run_state.json.")
        os.makedirs(self.checkpoint_directory)
        os.makedirs(os.path.dirname(self.log_path))
        self.state = {
            "schema_version": RESULT_SCHEMA,
            "status": "running",
            "created_at": _utc_now(),
            "identity": self.identity,
            "completed_replay_tasks": 0,
            "last_task_id": None,
            "adopted_empty_legacy_directory": True,
        }
        self.resumed = True
    else:
      os.makedirs(self.checkpoint_directory)
      os.makedirs(os.path.dirname(self.log_path))
      self.state = {
          "schema_version": RESULT_SCHEMA,
          "status": "running",
          "created_at": _utc_now(),
          "identity": self.identity,
          "completed_replay_tasks": 0,
          "last_task_id": None,
      }
    _write_json_atomic(self.state_path, self.state)
    self.record("run_resumed" if self.resumed else "run_started", {
        "completed_replay_tasks": self.state["completed_replay_tasks"]})

  @staticmethod
  def task_id(phase: str, metadata: Mapping[str, Any]) -> str:
    return "{}-{}".format(phase, _fingerprint_value(metadata)[:20])

  def record(self, event: str, fields: Mapping[str, Any]) -> None:
    row = {
        "schema_version": RESULT_SCHEMA,
        "timestamp": _utc_now(),
        "event": event,
    }
    row.update(fields)
    _append_jsonl(self.log_path, row)

  def run_task(
      self, phase: str, metadata: Mapping[str, Any], callback
  ) -> Mapping[str, Any]:
    task_id = self.task_id(phase, metadata)
    checkpoint_path = os.path.join(
        self.checkpoint_directory, task_id + ".json")
    if os.path.isfile(checkpoint_path):
      checkpoint = load_json(checkpoint_path)
      _require(
          checkpoint.get("metadata") == metadata,
          "Checkpoint metadata mismatch: {}".format(task_id))
      self.record("replay_skipped_checkpoint", {
          "task_id": task_id, "phase": phase})
      print("[stage3] checkpoint reuse {}".format(task_id), flush=True)
      return checkpoint["payload"]
    self.record("replay_started", {
        "task_id": task_id, "phase": phase, "metadata": metadata})
    print(
        "[stage3] start {} workload={} split={} capacity={} ratio={}".format(
            phase, metadata.get("workload"), metadata.get("split"),
            metadata.get("dram_capacity_pages"),
            metadata.get("capacity_ratio")),
        flush=True)
    started = time.monotonic()
    payload = callback()
    elapsed = time.monotonic() - started
    checkpoint = {
        "schema_version": RESULT_SCHEMA,
        "task_id": task_id,
        "phase": phase,
        "metadata": copy.deepcopy(metadata),
        "elapsed_seconds": elapsed,
        "payload": payload,
    }
    _write_json_atomic(checkpoint_path, checkpoint)
    self.state["completed_replay_tasks"] += 1
    self.state["last_task_id"] = task_id
    self.state["updated_at"] = _utc_now()
    _write_json_atomic(self.state_path, self.state)
    self.record("replay_completed", {
        "task_id": task_id, "phase": phase,
        "elapsed_seconds": elapsed,
        "completed_replay_tasks": self.state["completed_replay_tasks"]})
    print(
        "[stage3] done {} {:.3f}s completed={}".format(
            task_id, elapsed, self.state["completed_replay_tasks"]),
        flush=True)
    return payload

  def finish(self, status: str) -> None:
    self.state["status"] = status
    self.state["finished_at"] = _utc_now()
    _write_json_atomic(self.state_path, self.state)
    self.record("run_{}".format(status), {
        "completed_replay_tasks": self.state["completed_replay_tasks"]})


def run_calibration(
    config: Mapping[str, Any], stage0: Mapping[str, Any],
    stage2: proactive_cost.CostConfiguration,
    manifest: Mapping[str, Any],
    traces: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    resolved_entries: Sequence[Mapping[str, Any]],
    run_id: str, output_root: str, project_root: str, resume: bool = False
) -> Dict[str, Any]:
  """Runs stage 3 with durable replay checkpoints and an immutable final dir."""
  validate_config(config, stage0=stage0, stage2=stage2)
  validate_manifest(manifest)
  _require(isinstance(run_id, str) and run_id.strip(), "run_id is required.")
  output_root = os.path.abspath(output_root)
  final_directory = os.path.join(output_root, "stage3", run_id)
  _require(not os.path.exists(final_directory), "run_id already exists: {}".format(final_directory))
  temporary_directory = final_directory + ".incomplete"
  identity = {
      "run_id": run_id,
      "config_fingerprint": _fingerprint_value(config),
      "manifest_fingerprint": _fingerprint_value(manifest),
      "stage0_config_fingerprint": finals_config.config_fingerprint(stage0),
      "stage2_config_fingerprint": _fingerprint_value(stage2.source),
      "input_fingerprints": sorted(
          [item["workload"], item["split"], item["trace_fingerprint"]]
          for item in resolved_entries),
  }
  journal = _RunJournal(temporary_directory, identity, bool(resume))
  try:
    working_sets = working_set_summary(traces, config["page_size_bytes"])
    profiles = config["capacity_profile_candidates"]
    capacity_matrices = {
        name: _capacity_matrix(working_sets, ratios)
        for name, ratios in profiles.items()}

    reactive_rows = []
    burst_stats_rows = []
    burst_window_rows = []
    for profile_name in ("primary", "fallback"):
      for workload in sorted(traces):
        for capacity in capacity_matrices[profile_name][workload]:
          for split in ALLOWED_SPLITS:
            metadata = {
                "workload": workload,
                "split": split,
                "capacity_ratio": capacity["capacity_ratio"],
                "dram_capacity_pages": capacity["dram_capacity_pages"],
                "policy": PRE_WATERMARK_POLICY,
            }

            def reactive_task():
              row_value, replay_result = _replay_row(
                  stage0, traces[workload][split], workload, split, capacity,
                  PRE_WATERMARK_POLICY)
              statistics_rows = []
              window_rows = []
              for window_size in config["burst_windows"]:
                stats_value, windows_value = burst_statistics(
                    replay_result["page_enter_flags"], window_size)
                statistics_rows.append(stats_value)
                window_rows.extend(windows_value)
              return {
                  "row": row_value,
                  "burst_statistics": statistics_rows,
                  "burst_windows": window_rows,
              }

            replay_payload = journal.run_task(
                "reactive", metadata, reactive_task)
            row = copy.deepcopy(replay_payload["row"])
            row["capacity_profile"] = profile_name
            reactive_rows.append(row)
            for stats_value in replay_payload["burst_statistics"]:
              stats = copy.deepcopy(stats_value)
              stats.update({
                  "schema_version": RESULT_SCHEMA,
                  "workload": workload,
                  "split": split,
                  "capacity_profile": profile_name,
                  "capacity_ratio": capacity["capacity_ratio"],
                  "dram_capacity_pages": capacity["dram_capacity_pages"],
              })
              burst_stats_rows.append(stats)
            for window_value in replay_payload["burst_windows"]:
              item = copy.deepcopy(window_value)
              item.update({
                  "schema_version": RESULT_SCHEMA,
                  "workload": workload,
                  "split": split,
                  "capacity_profile": profile_name,
                  "capacity_ratio": capacity["capacity_ratio"],
                  "dram_capacity_pages": capacity["dram_capacity_pages"],
              })
              burst_window_rows.append(item)
    write_jsonl(
        os.path.join(temporary_directory, "reactive_results.jsonl"),
        reactive_rows)
    write_json(
        os.path.join(temporary_directory, "burst_statistics.json"),
        burst_stats_rows)
    write_jsonl(
        os.path.join(temporary_directory, "burst_windows.jsonl"),
        burst_window_rows)

    primary_audit = audit_pressure(
        [row for row in reactive_rows if row["capacity_profile"] == "primary"],
        config["pressure_distinguishability_rule"], "primary")
    fallback_audit = audit_pressure(
        [row for row in reactive_rows if row["capacity_profile"] == "fallback"],
        config["pressure_distinguishability_rule"], "fallback")
    capacity_decision = choose_capacity_profile(primary_audit, fallback_audit)
    selected_profile = capacity_decision["recommended_profile"]
    if selected_profile is None:
      selected_profile = "primary"
    calibration_capacities = capacity_matrices[selected_profile]

    relevant_bursts = [
        item for item in burst_stats_rows
        if item["capacity_profile"] == selected_profile]
    watermarks = generate_watermark_candidates(relevant_bursts)
    watermark_rows = []
    proxy_values = config["candidate_bound_invariance_values"]
    for proxy_bound in proxy_values:
      for workload in sorted(traces):
        for capacity in calibration_capacities[workload]:
          for candidate in watermarks:
            legal = (
                0 < candidate["F_low"] < candidate["F_target"] <=
                capacity["dram_capacity_pages"])
            if not legal:
              watermark_rows.append({
                  "schema_version": RESULT_SCHEMA,
                  "watermark_label": candidate["label"],
                  "workload": workload,
                  "split": "validation",
                  "capacity_ratio": capacity["capacity_ratio"],
                  "dram_capacity_pages": capacity["dram_capacity_pages"],
                  "F_low": candidate["F_low"],
                  "F_target": candidate["F_target"],
                  "b_max": 1,
                  "stage3_calibration_candidate_bound": proxy_bound,
                  "legal": False,
                  "illegal_reason": "F_target_exceeds_dram_capacity_pages",
                  "state_invariants_passed": False,
              })
              continue
            metadata = {
                "workload": workload,
                "split": "validation",
                "capacity_ratio": capacity["capacity_ratio"],
                "dram_capacity_pages": capacity["dram_capacity_pages"],
                "policy": CALIBRATION_POLICY,
                "phase_candidate": "watermark",
                "watermark_label": candidate["label"],
                "F_low": candidate["F_low"],
                "F_target": candidate["F_target"],
                "b_max": 1,
                "candidate_bound": proxy_bound,
            }

            def watermark_task():
              row_value, _ = _replay_row(
                  stage0, traces[workload]["validation"], workload,
                  "validation", capacity, CALIBRATION_POLICY,
                  F_low=candidate["F_low"], F_target=candidate["F_target"],
                  b_max=1, candidate_bound=proxy_bound)
              return {"row": row_value}

            row = copy.deepcopy(journal.run_task(
                "watermark", metadata, watermark_task)["row"])
            row.update({
                "watermark_label": candidate["label"],
                "legal": True, "illegal_reason": None})
            watermark_rows.append(row)
    write_jsonl(
        os.path.join(temporary_directory, "watermark_results.jsonl"),
        watermark_rows)

    primary_proxy = config["stage3_calibration_candidate_bound"]
    watermark_primary_rows = [
        row for row in watermark_rows
        if row["stage3_calibration_candidate_bound"] == primary_proxy]
    watermark_summaries = summarize_candidate_rows(
        watermark_primary_rows, "watermark_label")
    watermark_decision = select_watermark(watermark_summaries, watermarks)

    bmax_rows = []
    if watermark_decision["selected_watermark"] is not None:
      chosen = watermark_decision["selected_watermark"]
      for proxy_bound in proxy_values:
        for workload in sorted(traces):
          for capacity in calibration_capacities[workload]:
            for b_max in config["b_max_candidates"]:
              legal = (
                  0 < chosen["F_low"] < chosen["F_target"] <=
                  capacity["dram_capacity_pages"] and b_max < proxy_bound)
              if not legal:
                bmax_rows.append({
                    "schema_version": RESULT_SCHEMA,
                    "b_max": b_max, "workload": workload,
                    "split": "validation",
                    "capacity_ratio": capacity["capacity_ratio"],
                    "dram_capacity_pages": capacity["dram_capacity_pages"],
                    "F_low": chosen["F_low"], "F_target": chosen["F_target"],
                    "stage3_calibration_candidate_bound": proxy_bound,
                    "legal": False,
                    "illegal_reason": "watermark_or_candidate_bound_illegal",
                    "state_invariants_passed": False,
                })
                continue
              metadata = {
                  "workload": workload,
                  "split": "validation",
                  "capacity_ratio": capacity["capacity_ratio"],
                  "dram_capacity_pages": capacity["dram_capacity_pages"],
                  "policy": CALIBRATION_POLICY,
                  "phase_candidate": "bmax",
                  "F_low": chosen["F_low"],
                  "F_target": chosen["F_target"],
                  "b_max": b_max,
                  "candidate_bound": proxy_bound,
              }

              def bmax_task():
                row_value, _ = _replay_row(
                    stage0, traces[workload]["validation"], workload,
                    "validation", capacity, CALIBRATION_POLICY,
                    F_low=chosen["F_low"], F_target=chosen["F_target"],
                    b_max=b_max, candidate_bound=proxy_bound)
                return {"row": row_value}

              row = copy.deepcopy(journal.run_task(
                  "bmax", metadata, bmax_task)["row"])
              row.update({"legal": True, "illegal_reason": None})
              bmax_rows.append(row)
    write_jsonl(
        os.path.join(temporary_directory, "bmax_results.jsonl"),
        bmax_rows)
    bmax_primary_rows = [
        row for row in bmax_rows
        if row["stage3_calibration_candidate_bound"] == primary_proxy]
    bmax_summaries = summarize_candidate_rows(bmax_primary_rows, "b_max")
    bmax_decision = select_bmax(bmax_summaries)

    proxy_decisions = {}
    for proxy_bound in proxy_values:
      proxy_watermark_summaries = summarize_candidate_rows(
          [row for row in watermark_rows
           if row["stage3_calibration_candidate_bound"] == proxy_bound],
          "watermark_label")
      proxy_watermark = select_watermark(proxy_watermark_summaries, watermarks)
      proxy_bmax_summaries = summarize_candidate_rows(
          [row for row in bmax_rows
           if row["stage3_calibration_candidate_bound"] == proxy_bound],
          "b_max")
      proxy_bmax = select_bmax(proxy_bmax_summaries)
      proxy_decisions[str(proxy_bound)] = {
          "selected_watermark_label": proxy_watermark["selected_label"],
          "selected_b_max": proxy_bmax["selected_b_max"],
      }
    unique_proxy_choices = {
        (item["selected_watermark_label"], item["selected_b_max"])
        for item in proxy_decisions.values()}
    invariance_passed = (
        len(unique_proxy_choices) == 1 and
        all(
            item["selected_watermark_label"] is not None and
            item["selected_b_max"] is not None
            for item in proxy_decisions.values()))
    invariance = {
        "status": "passed" if invariance_passed else "failed_proxy_K_changes_selection",
        "proxy_values": proxy_values,
        "decisions": proxy_decisions,
        "enters_formal_candidate_size_K": False,
    }

    calibration_kind = manifest["calibration_kind"]
    stage_status = (
        RESULTS_READY if calibration_kind == "real_train_validation"
        else AWAITING_INPUTS)
    selection_decision = {
        "schema_version": RESULT_SCHEMA,
        "capacity": capacity_decision,
        "watermark": watermark_decision,
        "b_max": bmax_decision,
        "candidate_bound_invariance": invariance,
        "test_used": False,
        "capd_used_for_selection": False,
        "stage4_candidate_status": "pending",
    }
    freeze_candidate = {
        "schema_version": RESULT_SCHEMA,
        "status": (
            "candidate_ready_for_user_confirmation"
            if stage_status == RESULTS_READY and invariance_passed and
            capacity_decision["recommended_ratios"] is not None and
            watermark_decision["selected_watermark"] is not None and
            bmax_decision["selected_b_max"] is not None
            else "not_freezable"),
        "working_set_definition": WORKING_SET_DEFINITION,
        "capacity_ratios": capacity_decision["recommended_ratios"],
        "default_capacity_ratio": (
            None if capacity_decision["recommended_ratios"] is None
            else capacity_decision["recommended_ratios"][1]),
        "F_low": (
            None if watermark_decision["selected_watermark"] is None
            else watermark_decision["selected_watermark"]["F_low"]),
        "F_target": (
            None if watermark_decision["selected_watermark"] is None
            else watermark_decision["selected_watermark"]["F_target"]),
        "b_max": bmax_decision["selected_b_max"],
        "formal_candidate_size_K": None,
        "requires_user_confirmation": True,
        "main_config_updated": False,
    }
    provenance = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "created_at": _utc_now(),
        "config_fingerprint": _fingerprint_value(config),
        "manifest_fingerprint": _fingerprint_value(manifest),
        "input_artifacts": list(resolved_entries),
        "stage0_config_fingerprint": finals_config.config_fingerprint(stage0),
        "stage2_config_fingerprint": _fingerprint_value(stage2.source),
        "test_used": False,
        "capd_used_for_selection": False,
        "candidate_filter": "disabled",
        "resumed_from_checkpoints": journal.resumed,
        "completed_replay_tasks": journal.state["completed_replay_tasks"],
    }
    provenance.update(_git_state(project_root))
    resolved_config = copy.deepcopy(config)
    resolved_config.update({
        "stage_status": stage_status,
        "input_manifest": copy.deepcopy(manifest),
        "watermark_candidates": watermarks,
        "resolved_capacity_profile": selected_profile,
        "run_id": run_id,
    })
    provenance["resolved_config_fingerprint"] = _fingerprint_value(
        resolved_config)
    payload = {
        "schema_version": RESULT_SCHEMA,
        "run_id": run_id,
        "stage_status": stage_status,
        "calibration_kind": calibration_kind,
        "working_set_summary": working_sets,
        "capacity_pressure_audit": {
            "primary": primary_audit,
            "fallback": fallback_audit,
            "reactive_rows": reactive_rows,
        },
        "burst_statistics": burst_stats_rows,
        "watermark_candidates": watermarks,
        "watermark_results": watermark_rows,
        "watermark_summary": watermark_summaries,
        "bmax_results": bmax_rows,
        "bmax_summary": bmax_summaries,
        "selection_decision": selection_decision,
        "freeze_candidate": freeze_candidate,
    }

    write_json(os.path.join(temporary_directory, "resolved_config.json"), resolved_config)
    write_json(os.path.join(temporary_directory, "input_manifest.json"), {
        "manifest": manifest, "resolved_entries": list(resolved_entries)})
    write_json(os.path.join(temporary_directory, "working_set_summary.json"), working_sets)
    write_json(os.path.join(temporary_directory, "capacity_pressure_audit.json"), payload["capacity_pressure_audit"])
    write_json(os.path.join(temporary_directory, "burst_statistics.json"), burst_stats_rows)
    write_jsonl(os.path.join(temporary_directory, "burst_windows.jsonl"), burst_window_rows)
    write_jsonl(os.path.join(temporary_directory, "watermark_results.jsonl"), watermark_rows)
    _write_csv(
        os.path.join(temporary_directory, "watermark_summary.csv"),
        watermark_primary_rows,
        ("workload", "split", "capacity_ratio", "dram_capacity_pages",
         "watermark_label", "F_low", "F_target", "legal",
         "free_frame_exhaustion_count", "emergency_demotions",
         "total_demotions", "proactive_demotions", "reactive_demotions",
         "early_reuse_count", "early_reuse_rate", "nvm_reads", "nvm_writes",
         "number_of_proactive_cycles", "number_of_proactive_rounds",
         "rounds_per_cycle", "minimum_free_frames", "average_free_frames",
         "accesses_below_F_low"))
    write_jsonl(os.path.join(temporary_directory, "bmax_results.jsonl"), bmax_rows)
    _write_csv(
        os.path.join(temporary_directory, "bmax_summary.csv"),
        bmax_primary_rows,
        ("workload", "split", "capacity_ratio", "dram_capacity_pages",
         "F_low", "F_target", "b_max", "legal", "default_weighted_cost",
         "dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
         "proactive_demotions", "early_reuse_rate",
         "number_of_proactive_rounds", "rounds_per_cycle",
         "emergency_demotions", "free_frame_exhaustion_count"))
    write_json(os.path.join(temporary_directory, "selection_decision.json"), selection_decision)
    write_json(os.path.join(temporary_directory, "freeze_candidate.json"), freeze_candidate)
    os.makedirs(os.path.join(temporary_directory, "logs"), exist_ok=True)
    with open(
        os.path.join(temporary_directory, "report.md"), "w",
        encoding="utf-8", newline="\n") as output_file:
      output_file.write(_report_markdown(payload))
    journal.finish("completed")
    output_artifacts = []
    for name in sorted(os.listdir(temporary_directory)):
      path = os.path.join(temporary_directory, name)
      if os.path.isfile(path):
        output_artifacts.append({
            "path": name,
            "sha256": finals_config.fingerprint_file(path),
            "size_bytes": os.path.getsize(path),
        })
    provenance["output_artifacts"] = output_artifacts
    write_json(
        os.path.join(temporary_directory, "provenance.json"), provenance)
    os.makedirs(os.path.dirname(final_directory), exist_ok=True)
    os.replace(temporary_directory, final_directory)
    payload["output_directory"] = final_directory
    return payload
  except BaseException as error:
    status = (
        "interrupted" if isinstance(error, KeyboardInterrupt) else "failed")
    journal.state["error_type"] = type(error).__name__
    journal.state["error_message"] = str(error)
    journal.finish(status)
    raise
