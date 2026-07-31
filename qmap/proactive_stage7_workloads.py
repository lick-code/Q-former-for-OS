# coding=utf-8
"""Stage-7 workload, trace, split, working-set, and Stage-8 plan contracts.

This module is standard-library only.  It deliberately separates Test payload
integrity/materialization from Train/Validation profiling: Stage 7 may hash and
split a confirmed Test interval, but it must never execute a policy on it.
"""

from __future__ import annotations

import collections
import copy
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional
from typing import Sequence, Set, Tuple

from qmap import proactive_stage4


SCHEMA_VERSION = "capd_proactive_stage7_workloads_v1_0"
CAPACITY_SCHEMA_VERSION = "capd_proactive_stage7_capacity_v1_0"
COLLECTION_SCHEMA_VERSION = (
    "capd_proactive_stage7_collection_manifest_v1_0")
CONTRACT_ID = "CAPD-PROACTIVE-STAGE7-1.0"
IMPLEMENTED = "stage7_implemented_awaiting_collection"
COLLECTION_COMPLETE = "stage7_collection_complete_awaiting_freeze"
VERIFIED = "stage7_workload_suite_verified"
NOT_VERIFIED = "stage7_not_verified"
SEEN = (
    "canneal",
    "streamcluster_pressure",
    "dedup_pressure",
)
ROLES = ("seen_calibration_workload", "held_out_unseen_workload")
RATIOS = ("0.20", "0.40", "0.60")
FORMAL_POLICIES = (
    "reactive_lru",
    "proactive_lru",
    "proactive_clock",
    "tpp_inspired",
    "capd",
    "oracle",
)
DETERMINISTIC_POLICIES = tuple(
    policy for policy in FORMAL_POLICIES if policy != "capd")
CAPD_SEEDS = (3136859, 42, 2026)
FROZEN_CONTROLS = {
    "F_low": 8,
    "F_target": 16,
    "b_max": 4,
    "candidate_size_K": 8,
}
FROZEN_COST = {
    "dram_hit": 1,
    "nvm_read": 2,
    "nvm_write": 8,
    "demotion": 10,
}
REQUIRED_COVERAGE = {
    "stable_locality",
    "high_capacity_pressure",
    "bursty_page_entry",
    "write_intensive",
    "irregular_access",
    "capd_challenge_method_independent",
}
LEGACY_RESULT_RE = re.compile(
    r"(?:^|/)(?:outputs/results/finals_v3_official|"
    r"dataset/jsonl/finals_v3_official)(?:/|$)", re.IGNORECASE)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class Stage7ContractError(ValueError):
  """Raised when a Stage-7 identity, leakage, or capacity gate fails."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage7ContractError(message)


def load_json(path: str) -> Any:
  return proactive_stage4.load_json(path)


def fingerprint_file(path: str) -> str:
  return proactive_stage4.fingerprint_file(path)


def fingerprint_value(value: Any) -> str:
  encoded = json.dumps(
      value, ensure_ascii=False, sort_keys=True,
      separators=(",", ":")).encode("utf-8")
  return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: str, value: Any) -> None:
  proactive_stage4.write_json_atomic(path, value)


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]],
                     fields: Sequence[str]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage7-csv-", suffix=".tmp", dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(
          handle, fieldnames=list(fields), lineterminator="\n")
      writer.writeheader()
      for row in rows:
        writer.writerow({
            field: (
                json.dumps(row.get(field), ensure_ascii=False,
                           sort_keys=True)
                if isinstance(row.get(field), (dict, list)) else
                row.get(field))
            for field in fields})
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def write_text_atomic(path: str, value: str) -> None:
  proactive_stage4.write_text_atomic(path, value)


def safe_run_id(value: str) -> str:
  _require(isinstance(value, str) and RUN_ID_RE.match(value) is not None,
           "run_id must use only letters, digits, dot, underscore, or dash.")
  return value


def repository_path(project_root: str, recorded_path: str,
                    must_exist: bool = True) -> str:
  _require(isinstance(recorded_path, str) and recorded_path,
           "A non-empty repository path is required.")
  normalized = recorded_path.replace("\\", "/")
  _require(not LEGACY_RESULT_RE.search(normalized),
           "Legacy finals_v3 policy/result artifacts are forbidden.")
  root = os.path.realpath(project_root)
  if os.path.isabs(recorded_path):
    candidate = os.path.realpath(recorded_path)
  else:
    candidate = os.path.realpath(os.path.join(root, recorded_path))
  try:
    common = os.path.commonpath((root, candidate))
  except ValueError:
    common = ""
  _require(common == root, "Path escapes the repository: {}".format(
      recorded_path))
  if must_exist:
    _require(os.path.isfile(candidate), "Missing file: {}".format(
        recorded_path))
  return candidate


def portable_path(path: str, project_root: str) -> str:
  root = os.path.realpath(project_root)
  candidate = os.path.realpath(path)
  try:
    common = os.path.commonpath((root, candidate))
  except ValueError:
    common = ""
  if common == root:
    return os.path.relpath(candidate, root).replace(os.sep, "/")
  return candidate


def resolve_recorded_artifact(project_root: str, recorded_path: str,
                              expected_sha256: Optional[str] = None) -> str:
  """Resolves a historical server absolute path through its repository suffix."""
  _require(isinstance(recorded_path, str) and recorded_path,
           "Recorded artifact path is empty.")
  root = os.path.realpath(project_root)
  normalized = recorded_path.replace("\\", "/")
  candidates = []
  if not os.path.isabs(recorded_path):
    candidates.append(os.path.join(root, recorded_path))
  else:
    candidates.append(recorded_path)
    for marker in ("/outputs/", "/configs/", "/dataset/"):
      if marker in normalized:
        candidates.append(os.path.join(
            root, normalized.split(marker, 1)[1].replace("/", os.sep)
            if marker == "/" else
            marker.strip("/") + os.sep +
            normalized.split(marker, 1)[1].replace("/", os.sep)))
  resolved = None
  for candidate in candidates:
    candidate = os.path.realpath(candidate)
    try:
      inside = os.path.commonpath((root, candidate)) == root
    except ValueError:
      inside = False
    if inside and os.path.isfile(candidate):
      resolved = candidate
      break
  _require(resolved is not None,
           "Cannot resolve recorded repository artifact: {}".format(
               recorded_path))
  if expected_sha256 is not None:
    _require(fingerprint_file(resolved) == expected_sha256,
             "Recorded artifact SHA mismatch: {}".format(recorded_path))
  return resolved


def decimal_ceil_pages(working_set_pages: int, ratio: str) -> int:
  _require(isinstance(working_set_pages, int) and
           not isinstance(working_set_pages, bool) and
           working_set_pages > 0, "working_set_pages must be positive.")
  _require(str(ratio) in RATIOS, "Capacity ratio must be 0.20/0.40/0.60.")
  value = (Decimal(working_set_pages) * Decimal(str(ratio))).to_integral_value(
      rounding=ROUND_CEILING)
  return max(1, int(value))


def validate_capacity_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Stage-7 capacity config must be JSON.")
  _require(value.get("schema_version") == CAPACITY_SCHEMA_VERSION,
           "Stage-7 capacity schema mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Stage-7 capacity contract mismatch.")
  _require(tuple(value.get("ratios", ())) == RATIOS and
           value.get("default_ratio") == "0.20",
           "Capacity ratios/default changed.")
  _require(value.get("working_set_definition") ==
           "active_unique_pages_from_train_and_validation",
           "Working-set definition changed.")
  _require(value.get("capacity_rounding") ==
           "decimal_ceiling_ratio_times_working_set_minimum_one_no_clamp",
           "Decimal ceiling capacity rule changed.")
  _require(value.get("page_size_bytes") == 4096 and
           value.get("nvm_capacity_model") == "unbounded_backing_tier",
           "Page size or NVM model changed.")
  controls = value.get("fixed_active_controls", {})
  _require({key: controls.get(key) for key in FROZEN_CONTROLS} ==
           FROZEN_CONTROLS and controls.get("scale_with_capacity") is False,
           "Active controls changed or scale with capacity.")
  profile = value.get("profile", {})
  _require(profile.get("policy") == "reactive_lru" and
           tuple(profile.get("allowed_splits", ())) ==
           ("train", "validation") and
           profile.get("forbidden_split") == "test" and
           profile.get("burst_window_accesses") == 100 and
           profile.get("burst_quantile_method") == "nearest_rank",
           "Train/Validation LRU profile contract changed.")
  _require(value.get("pressure_test", {}).get("enabled") is False,
           "Pressure Test is optional and disabled in the frozen source.")
  return value


def validate_workload_config(value: Mapping[str, Any],
                             require_confirmed: bool = False
                             ) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Stage-7 workload config must be JSON.")
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Stage-7 workload schema mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Stage-7 contract mismatch.")
  _require(value.get("stage_status") == IMPLEMENTED,
           "Source config must remain implemented-awaiting-collection.")
  _require(value.get("suite_size") == 6 and
           value.get("page_shift") == 12 and
           value.get("page_size_bytes") == 4096,
           "Suite size or page semantics changed.")
  scope = value.get("scope", {})
  _require(scope.get("single_process") is True and
           scope.get("single_thread") is True and
           scope.get("single_workload") is True and
           scope.get("test_policy_replay_allowed") is False and
           scope.get("test_policy_replay_allowed_stage") == 8,
           "Stage-7 execution scope changed.")
  frozen = value.get("frozen_inputs", {})
  _require(
      frozen.get("working_set_definition") ==
      "active_unique_pages_from_train_and_validation" and
      frozen.get("dram_working_set_ratio") == "0.20" and
      {key: frozen.get(key) for key in FROZEN_CONTROLS} ==
      FROZEN_CONTROLS and
      frozen.get("candidate_source") == "lru_tail" and
      frozen.get("selector") == "disabled" and
      frozen.get("fallback_policy") == "lru" and
      frozen.get("trigger_mode") == "low_watermark" and
      frozen.get("nvm_capacity_model") == "unbounded_backing_tier",
      "Stage-3/5 proactive freeze changed.")
  _require(frozen.get("cost_profile") == FROZEN_COST,
           "Stage-2 Cost profile changed.")
  capd = frozen.get("capd", {})
  _require(capd.get("lookahead_L") == 256 and
           capd.get("label_weights") == [1, 1, 2] and
           capd.get("history_H") == 20 and
           tuple(capd.get("checkpoint_seeds", ())) == CAPD_SEEDS and
           capd.get("best_seed_selection_allowed") is False and
           capd.get("retraining_allowed") is False and
           capd.get("vocabulary_expansion_allowed") is False,
           "Stage-4 CAPD freeze changed.")
  tpp = frozen.get("tpp_inspired", {})
  _require(tpp == {
      "epoch_length": 1024,
      "cold_threshold": 1,
      "dirty_tie_break": False,
      "promotion_allowed": False,
      "reselection_allowed": False,
  }, "Stage-6 TPP freeze changed.")
  _require(tuple(value.get("seen_calibration_workloads", ())) == SEEN,
           "Seen calibration workload set changed.")
  suite = value.get("proposed_suite", [])
  _require(isinstance(suite, list) and len(suite) == 6,
           "Exactly six proposed workloads are required.")
  names = [item.get("workload") for item in suite]
  _require(len(set(names)) == 6, "Workload names must be unique.")
  roles = {item.get("workload"): item.get("role") for item in suite}
  _require(tuple(name for name in names if roles.get(name) ==
                 "seen_calibration_workload") == SEEN,
           "The formal seen workload set/order is incorrect.")
  _require(all(role in ROLES for role in roles.values()),
           "Every workload requires a seen/unseen role.")
  if "blackscholes" in roles:
    _require(roles["blackscholes"] == "held_out_unseen_workload",
             "blackscholes must be held-out/unseen.")
  coverage = set()
  for item in suite:
    _require(isinstance(item.get("coverage"), list) and item["coverage"],
             "Every workload requires coverage labels.")
    _require(isinstance(item.get("collection_cost_estimate"), str) and
             item["collection_cost_estimate"] and
             isinstance(item.get("qualification_risks"), list),
             "Every workload requires collection cost and risk fields.")
    coverage.update(item["coverage"])
    if item["role"] == "held_out_unseen_workload":
      _require(item.get("model_training_used") is False and
               item.get("capd_checkpoint_retrained") is False and
               item.get("tpp_parameters_reselected") is False,
               "Held-out workload contaminated training or selection.")
  _require(REQUIRED_COVERAGE.issubset(coverage),
           "Proposed suite does not cover all required workload types.")
  confirmation = value.get("suite_confirmation", {})
  _require(confirmation.get(
      "required_before_collection_or_test_lock") is True,
      "Suite confirmation gate was removed.")
  if require_confirmed:
    _require(confirmation.get("confirmed") is True and
             confirmation.get("confirmed_by") and
             confirmation.get("confirmed_at"),
             "Six-workload suite requires explicit user confirmation.")
  split = value.get("split_policy_for_fresh_traces", {})
  _require(split.get("interval") == "half_open" and
           split.get("chronological") is True and
           split.get("shuffle") is False,
           "Fresh Trace split must be chronological half-open.")
  validate_intervals(split, int(split.get("total_accesses", -1)))
  return value


def audit_stage6_entry(config: Mapping[str, Any],
                       project_root: str) -> Dict[str, Any]:
  validate_workload_config(config)
  loaded = {}
  digests = {}
  for name, binding in config.get("entry_authority", {}).items():
    path = repository_path(project_root, binding.get("path"))
    actual = fingerprint_file(path)
    _require(actual == binding.get("sha256"),
             "Stage-7 entry authority SHA mismatch: {}.".format(name))
    loaded[name] = load_json(path)
    digests[name] = actual
  _require(loaded["stage6_verification"].get("status") ==
           "stage6_tpp_inspired_verified" and
           loaded["stage6_verification"].get("stage7_entry_gate") ==
           "satisfied", "Stage-6 entry gate is not satisfied.")
  _require(loaded["stage6_verification"].get("test_trace_opened") is False and
           loaded["stage6_verification"].get(
               "test_used_for_selection") is False,
           "Stage-6 entry reports Test contamination.")
  _require(loaded["stage6_final_tpp_config"].get(
      "selected_parameters") == {
          "epoch_length": 1024,
          "cold_threshold": 1,
          "dirty_tie_break": False,
      }, "Stage-6 final TPP parameters changed.")
  _require(loaded["stage5_verification"].get("status") ==
           "stage5_baseline_framework_verified" and
           loaded["stage4_verification"].get("status") ==
           "stage4_verified", "Stage-4/5 authority is not verified.")
  _require(loaded["stage4_verification"].get("selected_parameters") == {
      "candidate_size_K": 8,
      "history_H": 20,
      "label_weights": [1.0, 1.0, 2.0],
      "lookahead_L": 256,
  }, "Stage-4 parameters changed.")
  _require(loaded["stage3_engineering_default"].get(
      "formal_capacity_gate_passed") is False and
      loaded["stage3_engineering_default"].get("selected", {}).get(
          "dram_working_set_ratio") == 0.2,
      "20% conditional engineering default boundary changed.")
  verification_root = os.path.dirname(repository_path(
      project_root,
      config["entry_authority"]["stage6_verification"]["path"]))
  for filename, expected in loaded["stage6_verification"].get(
      "evidence_sha256", {}).items():
    path = os.path.join(verification_root, filename)
    _require(os.path.isfile(path) and fingerprint_file(path) == expected,
             "Stage-6 evidence SHA mismatch: {}.".format(filename))
  return {
      "status": "passed",
      "stage6_status": "stage6_tpp_inspired_verified",
      "stage7_entry_gate": "satisfied",
      "selected_tpp_parameters": copy.deepcopy(
          loaded["stage6_final_tpp_config"]["selected_parameters"]),
      "test_trace_opened": False,
      "authority_sha256": digests,
  }


def validate_intervals(value: Mapping[str, Any],
                       total_accesses: int) -> Dict[str, Tuple[int, int]]:
  result = {}
  previous_end = None
  for role in ("train", "validation", "test"):
    interval = value.get(role)
    _require(isinstance(interval, (list, tuple)) and len(interval) == 2,
             "Missing {} half-open interval.".format(role))
    start, end = interval
    _require(isinstance(start, int) and isinstance(end, int) and
             not isinstance(start, bool) and not isinstance(end, bool) and
             0 <= start < end <= total_accesses,
             "Invalid {} half-open interval.".format(role))
    if previous_end is not None:
      _require(start >= previous_end,
               "Train/Validation/Test intervals overlap or changed role.")
    result[role] = (start, end)
    previous_end = end
  _require(result["train"][0] == 0 and
           result["test"][1] == total_accesses,
           "Splits must cover the declared chronological source interval.")
  return result


def _header_map(fieldnames: Optional[Sequence[str]]) -> Dict[str, str]:
  _require(fieldnames is not None, "Trace is missing its CSV header.")
  normalized = {str(name).strip().lower(): name for name in fieldnames}
  result = {}
  aliases = {
      "pid": ("pid", "process_id"),
      "tid": ("tid", "thread_id"),
      "pc": ("pc",),
      "address": ("address", "addr"),
      "rw": ("rw",),
  }
  for key, options in aliases.items():
    actual = next((normalized[name] for name in options
                   if name in normalized), None)
    _require(actual is not None,
             "Trace header is missing required {} column.".format(key))
    result[key] = actual
  return result


def _parse_integer(value: Any, name: str) -> int:
  try:
    return int(str(value).strip(), 0)
  except (TypeError, ValueError):
    raise Stage7ContractError("Invalid {} value: {!r}.".format(name, value))


def _parse_rw(value: Any) -> str:
  normalized = str(value).strip().lower()
  if normalized in ("r", "read", "0", "load", "l"):
    return "R"
  if normalized in ("w", "write", "1", "store", "s"):
    return "W"
  raise Stage7ContractError("Invalid RW value: {!r}.".format(value))


def iter_trace(path: str, page_shift: int = 12
               ) -> Iterator[Dict[str, Any]]:
  _require(page_shift == 12, "Stage 7 requires page_shift=12.")
  with open(path, "r", encoding="utf-8", newline="") as input_file:
    reader = csv.DictReader(input_file)
    columns = _header_map(reader.fieldnames)
    for index, row in enumerate(reader):
      address = _parse_integer(row[columns["address"]], "Address")
      yield {
          "index": index,
          "pid": _parse_integer(row[columns["pid"]], "PID"),
          "tid": _parse_integer(row[columns["tid"]], "TID"),
          "pc": _parse_integer(row[columns["pc"]], "PC"),
          "address": address,
          "page": address >> 12,
          "rw": _parse_rw(row[columns["rw"]]),
      }


def validate_collection_manifest(value: Mapping[str, Any],
                                 config: Mapping[str, Any],
                                 require_confirmed: bool = True
                                 ) -> Mapping[str, Any]:
  validate_workload_config(config, require_confirmed=require_confirmed)
  _require(value.get("schema_version") == COLLECTION_SCHEMA_VERSION and
           value.get("contract_id") == CONTRACT_ID,
           "Collection manifest schema/contract mismatch.")
  safe_run_id(value.get("run_id", ""))
  if require_confirmed:
    _require(value.get("suite_confirmed") is True,
             "Collection manifest does not record suite confirmation.")
  _require(value.get("test_used_for_parameter_selection") is False and
           value.get("test_policy_replay_executed") is False and
           value.get("test_performance_inspected") is False,
           "Collection manifest reports Test contamination.")
  rows = value.get("collections", [])
  _require(isinstance(rows, list) and len(rows) == 6,
           "Collection manifest requires exactly six workloads.")
  proposed = {
      row["workload"]: row for row in config["proposed_suite"]}
  _require(set(row.get("workload") for row in rows) == set(proposed),
           "Collection workloads differ from the confirmed suite.")
  ids = set()
  paths = set()
  for row in rows:
    workload = row["workload"]
    _require(row.get("role") == proposed[workload]["role"],
             "Collection role mismatch for {}.".format(workload))
    _require(row.get("page_shift") == 12 and
             tuple(row.get("columns", ())) ==
             ("PID", "TID", "PC", "Address", "RW"),
             "Trace schema/page semantics mismatch for {}.".format(workload))
    source_id = row.get("source_trace_id")
    _require(isinstance(source_id, str) and source_id and source_id not in ids,
             "source_trace_id must be non-empty and unique.")
    ids.add(source_id)
    raw_path = str(row.get("raw_trace_path", "")).replace("\\", "/")
    _require(raw_path and raw_path not in paths and
             not LEGACY_RESULT_RE.search(raw_path),
             "Raw Trace path is missing, duplicated, or a policy result.")
    paths.add(raw_path)
    pids = row.get("process_ids")
    tids = row.get("thread_ids")
    _require(isinstance(pids, list) and len(pids) == 1 and
             isinstance(tids, list) and len(tids) == 1,
             "{} must attest exactly one PID and one TID.".format(workload))
    benchmark = row.get("benchmark", {})
    collector = row.get("collector", {})
    environment = row.get("environment", {})
    for field in ("name", "version", "binary_path", "binary_sha256",
                  "input_name", "command", "thread_parameter"):
      _require(benchmark.get(field) is not None,
               "{} benchmark.{} is required.".format(workload, field))
    if benchmark.get("input_path") is None:
      _require(benchmark.get("input_sha256") is None,
               "{} input SHA exists without an input path.".format(
                   workload))
    else:
      _require(benchmark.get("input_sha256"),
               "{} input path lacks SHA-256.".format(workload))
    _require(benchmark.get("thread_parameter") == 1,
             "{} is not configured single-thread.".format(workload))
    for field in ("name", "version", "command", "started_at", "ended_at",
                  "exit_code", "stdout_log", "stderr_log", "truncated",
                  "timed_out", "lost_events"):
      _require(field in collector,
               "{} collector.{} is required.".format(workload, field))
    _require(collector.get("exit_code") == 0 and
             collector.get("truncated") is False and
             collector.get("timed_out") is False and
             collector.get("lost_events") is False,
             "{} collection is incomplete or lossy.".format(workload))
    for field in ("machine", "cpu", "memory", "os", "git_commit",
                  "dirty_worktree", "aslr"):
      _require(environment.get(field) is not None,
               "{} environment.{} is required.".format(workload, field))
    total = row.get("raw_trace_accesses")
    _require(isinstance(total, int) and total > 0,
             "{} raw_trace_accesses must be positive.".format(workload))
    validate_intervals(row.get("splits", {}), total)
    if row["role"] == "held_out_unseen_workload":
      _require(row.get("model_training_used") is False and
               row.get("capd_checkpoint_retrained") is False and
               row.get("tpp_parameters_reselected") is False,
               "{} held-out contract was violated.".format(workload))
  return value


def _nearest_rank(values: Sequence[int], quantile: float) -> int:
  if not values:
    return 0
  ordered = sorted(values)
  rank = max(1, int(math.ceil(float(quantile) * len(ordered))))
  return int(ordered[min(rank - 1, len(ordered) - 1)])


def _split_for_index(intervals: Mapping[str, Tuple[int, int]],
                     index: int) -> Optional[str]:
  for role in ("train", "validation", "test"):
    start, end = intervals[role]
    if start <= index < end:
      return role
  return None


def inspect_collection(row: Mapping[str, Any], project_root: str,
                       output_root: str) -> Dict[str, Any]:
  """Materializes immutable splits and computes Train/Validation-only state."""
  raw_path = repository_path(project_root, row["raw_trace_path"])
  before = fingerprint_file(raw_path)
  if row.get("raw_trace_sha256"):
    _require(before == row["raw_trace_sha256"],
             "Raw Trace SHA mismatch for {}.".format(row["workload"]))
  intervals = validate_intervals(row["splits"], row["raw_trace_accesses"])
  split_root = os.path.join(output_root, "splits", row["workload"])
  os.makedirs(split_root, exist_ok=True)
  temporary = {}
  handles = {}
  writers = {}
  final_paths = {}
  counts = {role: 0 for role in intervals}
  unique = {role: set() for role in ("train", "validation")}
  rw_counts = {
      role: {"reads": 0, "writes": 0}
      for role in ("train", "validation")}
  observed_pids = set()
  observed_tids = set()
  access_count = 0
  try:
    for role in ("train", "validation", "test"):
      final_path = os.path.join(split_root, "{}.csv".format(role))
      fd, temporary_path = tempfile.mkstemp(
          prefix=".{}-".format(role), suffix=".tmp", dir=split_root)
      os.close(fd)
      handle = open(temporary_path, "w", encoding="utf-8", newline="")
      writer = csv.writer(handle, lineterminator="\n")
      writer.writerow(("PID", "TID", "PC", "Address", "RW"))
      temporary[role] = temporary_path
      handles[role] = handle
      writers[role] = writer
      final_paths[role] = final_path
    for record in iter_trace(raw_path, 12):
      role = _split_for_index(intervals, record["index"])
      _require(role is not None,
               "Trace record lies outside declared split intervals.")
      writers[role].writerow((
          record["pid"], record["tid"], hex(record["pc"]),
          hex(record["address"]), record["rw"]))
      counts[role] += 1
      observed_pids.add(record["pid"])
      observed_tids.add(record["tid"])
      if role in unique:
        unique[role].add(record["page"])
        rw_counts[role][
            "writes" if record["rw"] == "W" else "reads"] += 1
      access_count += 1
  finally:
    for handle in handles.values():
      handle.close()
  _require(access_count == row["raw_trace_accesses"],
           "Raw Trace access count mismatch for {}.".format(row["workload"]))
  _require(observed_pids == set(row["process_ids"]) and
           observed_tids == set(row["thread_ids"]) and
           len(observed_pids) == 1 and len(observed_tids) == 1,
           "Observed PID/TID identity differs from collection manifest.")
  for role in ("train", "validation", "test"):
    expected = intervals[role][1] - intervals[role][0]
    _require(counts[role] == expected,
             "{} split length mismatch.".format(role))
    os.replace(temporary[role], final_paths[role])
  after = fingerprint_file(raw_path)
  _require(before == after, "Raw Trace was modified during processing.")
  train_pages = unique["train"]
  validation_pages = unique["validation"]
  working_pages = train_pages | validation_pages
  _require(working_pages, "Active working set cannot be empty.")
  split_rows = {}
  for role in ("train", "validation", "test"):
    split_rows[role] = {
        "path": portable_path(final_paths[role], project_root),
        "source_trace_id": row["source_trace_id"],
        "interval": {
            "start_inclusive": intervals[role][0],
            "end_exclusive": intervals[role][1],
        },
        "accesses": counts[role],
        "sha256": fingerprint_file(final_paths[role]),
        "split_role": role,
        "formal_test": role == "test",
    }
  return {
      "workload": row["workload"],
      "role": row["role"],
      "raw_trace": {
          "path": portable_path(raw_path, project_root),
          "sha256": before,
          "accesses": access_count,
          "source_trace_id": row["source_trace_id"],
          "page_shift": 12,
          "process_ids": sorted(observed_pids),
          "thread_ids": sorted(observed_tids),
          "raw_trace_unchanged": True,
      },
      "splits": split_rows,
      "working_set": {
          "definition":
              "active_unique_pages_from_train_and_validation",
          "train_unique_pages": len(train_pages),
          "validation_unique_pages": len(validation_pages),
          "train_validation_intersection_pages":
              len(train_pages & validation_pages),
          "train_validation_union_pages": len(working_pages),
          "working_set_pages": len(working_pages),
          "test_pages_used": False,
      },
      "rw_counts_train_validation": {
          "train": rw_counts["train"],
          "validation": rw_counts["validation"],
      },
  }


def capacity_rows(workload: str, working_set_pages: int,
                  capacity_config: Mapping[str, Any]
                  ) -> List[Dict[str, Any]]:
  validate_capacity_config(capacity_config)
  rows = []
  for ratio in RATIOS:
    dram_pages = decimal_ceil_pages(working_set_pages, ratio)
    _require(dram_pages > max(
        capacity_config["fixed_active_controls"]["F_target"],
        capacity_config["fixed_active_controls"]["candidate_size_K"]),
        "{} D_{} fails F_target/K hard gate.".format(
            workload, ratio))
    nvm_pages = max(0, working_set_pages - dram_pages)
    rows.append({
        "workload": workload,
        "ratio": ratio,
        "is_main_default": ratio == "0.20",
        "working_set_pages": working_set_pages,
        "dram_pages": dram_pages,
        "dram_bytes": dram_pages * 4096,
        "maximum_expected_nvm_resident_pages": nvm_pages,
        "nvm_to_dram_ratio": float(nvm_pages) / float(dram_pages),
        "page_size_bytes": 4096,
        "nvm_capacity_model": "unbounded_backing_tier",
        "nvm_will_not_fill": True,
        "F_low": 8,
        "F_target": 16,
        "b_max": 4,
        "candidate_size_K": 8,
        "watermarks_scaled": False,
        "warning": (
            "D_20_below_100_evaluate_recollection_or_replacement"
            if ratio == "0.20" and dram_pages < 100 else None),
    })
  return rows


def profile_reactive_lru(split_paths: Sequence[str], dram_pages: int,
                         burst_window: int = 100) -> Dict[str, Any]:
  _require(dram_pages > 0 and burst_window > 0,
           "LRU profile parameters must be positive.")
  resident = collections.OrderedDict()
  page_enters = 0
  demotions = 0
  accesses = 0
  reads = 0
  writes = 0
  bursts = []
  current_burst = 0
  for path in split_paths:
    for record in iter_trace(path, 12):
      accesses += 1
      if record["rw"] == "W":
        writes += 1
      else:
        reads += 1
      page = record["page"]
      if page in resident:
        resident.move_to_end(page, last=True)
      else:
        page_enters += 1
        current_burst += 1
        if len(resident) >= dram_pages:
          resident.popitem(last=False)
          demotions += 1
        resident[page] = None
      if accesses % burst_window == 0:
        bursts.append(current_burst)
        current_burst = 0
  if accesses % burst_window:
    bursts.append(current_burst)
  return {
      "policy": "reactive_lru",
      "splits": ["train", "validation"],
      "test_accessed": False,
      "initial_state": "empty_dram_once_before_train",
      "accesses": accesses,
      "reads": reads,
      "writes": writes,
      "read_ratio": float(reads) / accesses if accesses else 0.0,
      "write_ratio": float(writes) / accesses if accesses else 0.0,
      "page_enter_dram_count": page_enters,
      "page_enter_rate": float(page_enters) / accesses if accesses else 0.0,
      "page_enter_burst_window_accesses": burst_window,
      "page_enter_burst_p50": _nearest_rank(bursts, 0.50),
      "page_enter_burst_p95": _nearest_rank(bursts, 0.95),
      "page_enter_burst_p99": _nearest_rank(bursts, 0.99),
      "reactive_lru_demotions": demotions,
      "reactive_lru_demotion_rate":
          float(demotions) / accesses if accesses else 0.0,
      "dram_pages": dram_pages,
  }


def build_stage8_plan(
    inspected: Sequence[Mapping[str, Any]],
    capacities: Sequence[Mapping[str, Any]],
    standard_lock: Mapping[str, Any],
    final_checkpoints: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
  _require(len(inspected) == 6, "Stage-8 plan requires six workloads.")
  checkpoint_map = {int(row["seed"]): row for row in final_checkpoints}
  _require(set(checkpoint_map) == set(CAPD_SEEDS),
           "All three frozen CAPD checkpoints are required.")
  capacity_map = collections.defaultdict(list)
  for row in capacities:
    capacity_map[row["workload"]].append(row)
  lock_map = {row["workload"]: row for row in standard_lock["workloads"]}
  jobs = []
  for item in inspected:
    workload = item["workload"]
    _require(len(capacity_map[workload]) == 3 and workload in lock_map,
             "Stage-8 capacity/Test identity incomplete.")
    for capacity in sorted(
        capacity_map[workload], key=lambda row: Decimal(row["ratio"])):
      for policy in DETERMINISTIC_POLICIES:
        experiment_labels = (
            ["B"] if policy == "reactive_lru" else
            ["A", "B"] if policy == "proactive_lru" else ["A"])
        jobs.append({
            "job_id": "{}__r{}__{}__seed-na".format(
                workload, capacity["ratio"].replace(".", ""), policy),
            "workload": workload,
            "workload_role": item["role"],
            "split": "test",
            "formal_test": True,
            "test_identity": lock_map[workload]["fairness_identity"],
            "capacity_ratio": capacity["ratio"],
            "dram_pages": capacity["dram_pages"],
            "policy": policy,
            "seed": None,
            "checkpoint": None,
            "deterministic_policy": True,
            "experiment_labels": experiment_labels,
            "execution_status": "planned_not_executed",
        })
      for seed in CAPD_SEEDS:
        checkpoint = checkpoint_map[seed]
        jobs.append({
            "job_id": "{}__r{}__capd__seed-{}".format(
                workload, capacity["ratio"].replace(".", ""), seed),
            "workload": workload,
            "workload_role": item["role"],
            "split": "test",
            "formal_test": True,
            "test_identity": lock_map[workload]["fairness_identity"],
            "capacity_ratio": capacity["ratio"],
            "dram_pages": capacity["dram_pages"],
            "policy": "capd",
            "seed": seed,
            "checkpoint": {
                "path": checkpoint["path"],
                "sha256": checkpoint["sha256"],
            },
            "deterministic_policy": False,
            "experiment_labels": ["A"],
            "execution_status": "planned_not_executed",
        })
  _require(len(jobs) == 144 and
           len({job["job_id"] for job in jobs}) == 144,
           "Stage-8 job matrix must contain exactly 144 unique jobs.")
  return {
      "schema_version": "capd_proactive_stage8_execution_plan_v1_0",
      "contract_id": CONTRACT_ID,
      "status": "frozen_plan_not_executed",
      "formal_policies": list(FORMAL_POLICIES),
      "deterministic_policies": list(DETERMINISTIC_POLICIES),
      "capd_seeds": list(CAPD_SEEDS),
      "workload_groups": {
          "seen_calibration_workloads": list(SEEN),
          "held_out_unseen_workloads": [
              item["workload"] for item in inspected
              if item["role"] == "held_out_unseen_workload"],
          "all_workloads": [item["workload"] for item in inspected],
      },
      "comparison_contracts": {
          "A": [
              "proactive_lru", "proactive_clock", "tpp_inspired",
              "capd", "oracle"],
          "B": ["reactive_lru", "proactive_lru"],
      },
      "generalization_contract": {
          "held_out_direct_checkpoint_inference": True,
          "checkpoint_retraining_allowed": False,
          "vocabulary_expansion_allowed": False,
          "page_and_pc_oov_policy": "frozen_checkpoint_unk_index_0",
          "oov_diagnostics_required_for_capd": True,
          "required_oov_metrics": [
              "page_access_oov_count",
              "page_access_oov_ratio",
              "page_unique_oov_count",
              "page_unique_oov_ratio",
              "pc_access_oov_count",
              "pc_access_oov_ratio",
              "pc_unique_oov_count",
              "pc_unique_oov_ratio"
          ],
          "required_result_groups": [
              "seen_calibration_workloads",
              "held_out_unseen_workloads",
              "all_workloads_macro",
              "per_workload_raw"
          ]
      },
      "capacity_ratios": list(RATIOS),
      "job_count": len(jobs),
      "jobs": jobs,
      "test_policy_replay_executed": False,
      "performance_results": None,
  }


def prepare_suite(
    config: Mapping[str, Any],
    capacity_config: Mapping[str, Any],
    collection_manifest: Mapping[str, Any],
    project_root: str,
    output_root: str,
) -> Dict[str, Any]:
  """Creates Stage-7 artifacts; requires explicit suite confirmation."""
  validate_workload_config(config, require_confirmed=True)
  validate_capacity_config(capacity_config)
  validate_collection_manifest(
      collection_manifest, config, require_confirmed=True)
  entry = audit_stage6_entry(config, project_root)
  os.makedirs(output_root, exist_ok=True)
  inspected = []
  collection_by_workload = {
      row["workload"]: row for row in collection_manifest["collections"]}
  # Manifest row order is not semantic (the recorder sorts rows for stable
  # atomic writes). Materialize in the confirmed suite order so role-group
  # identities and downstream Stage-8 plans remain deterministic.
  for declared in config["proposed_suite"]:
    inspected.append(inspect_collection(
        collection_by_workload[declared["workload"]],
        project_root, output_root))
  roles = {row["workload"]: row["role"] for row in config["proposed_suite"]}
  _require([item["workload"] for item in inspected
            if roles[item["workload"]] == "seen_calibration_workload"] ==
           list(SEEN), "Seen workload identities changed.")
  capacity_matrix = []
  profiles = []
  for item in inspected:
    rows = capacity_rows(
        item["workload"], item["working_set"]["working_set_pages"],
        capacity_config)
    capacity_matrix.extend(rows)
    d20 = next(row["dram_pages"] for row in rows
               if row["ratio"] == "0.20")
    train_path = repository_path(
        project_root, item["splits"]["train"]["path"])
    validation_path = repository_path(
        project_root, item["splits"]["validation"]["path"])
    profile = profile_reactive_lru(
        (train_path, validation_path), d20,
        capacity_config["profile"]["burst_window_accesses"])
    profile.update({
        "workload": item["workload"],
        "role": item["role"],
        "working_set_pages": item["working_set"]["working_set_pages"],
        "D_20": d20,
        "eligible": d20 > max(16, 8),
        "warnings": (
            ["D_20_below_100_evaluate_recollection_or_replacement"]
            if d20 < 100 else []),
    })
    profiles.append(profile)
  collection_by_workload = {
      row["workload"]: row for row in collection_manifest["collections"]}
  config_by_workload = {
      row["workload"]: row for row in config["proposed_suite"]}
  capacity_by_workload = collections.defaultdict(dict)
  for row in capacity_matrix:
    capacity_by_workload[row["workload"]][row["ratio"]] = row
  descriptions = []
  for item in inspected:
    workload = item["workload"]
    profile = next(
        row for row in profiles if row["workload"] == workload)
    collection = collection_by_workload[workload]
    capacities = capacity_by_workload[workload]
    descriptions.append({
        "workload": workload,
        "role": item["role"],
        "coverage": config_by_workload[workload]["coverage"],
        "benchmark_source": config_by_workload[workload]["source"],
        "input_name": collection["benchmark"]["input_name"],
        "trace_total_accesses": item["raw_trace"]["accesses"],
        "train_accesses": item["splits"]["train"]["accesses"],
        "validation_accesses": item["splits"]["validation"]["accesses"],
        "test_accesses": item["splits"]["test"]["accesses"],
        "active_unique_pages": item["working_set"]["working_set_pages"],
        "working_set_pages": item["working_set"]["working_set_pages"],
        "working_set_definition":
            "active_unique_pages_from_train_and_validation",
        "read_write_scope": "train_validation_only_test_sealed",
        "read_accesses": profile["reads"],
        "write_accesses": profile["writes"],
        "read_ratio": profile["read_ratio"],
        "write_ratio": profile["write_ratio"],
        "page_enter_dram_count": profile["page_enter_dram_count"],
        "page_enter_rate": profile["page_enter_rate"],
        "page_enter_burst_p50": profile["page_enter_burst_p50"],
        "page_enter_burst_p95": profile["page_enter_burst_p95"],
        "page_enter_burst_p99": profile["page_enter_burst_p99"],
        "reactive_lru_demotion_rate":
            profile["reactive_lru_demotion_rate"],
        "pressure_diagnostic_ratio": "0.20",
        "train_interval": item["splits"]["train"]["interval"],
        "validation_interval": item["splits"]["validation"]["interval"],
        "test_interval": item["splits"]["test"]["interval"],
        "raw_trace_sha256": item["raw_trace"]["sha256"],
        "train_sha256": item["splits"]["train"]["sha256"],
        "validation_sha256": item["splits"]["validation"]["sha256"],
        "test_sha256": item["splits"]["test"]["sha256"],
        "D_20_pages": capacities["0.20"]["dram_pages"],
        "D_40_pages": capacities["0.40"]["dram_pages"],
        "D_60_pages": capacities["0.60"]["dram_pages"],
        "NVM_to_DRAM_20": capacities["0.20"]["nvm_to_dram_ratio"],
        "NVM_to_DRAM_40": capacities["0.40"]["nvm_to_dram_ratio"],
        "NVM_to_DRAM_60": capacities["0.60"]["nvm_to_dram_ratio"],
        "process_ids": item["raw_trace"]["process_ids"],
        "thread_ids": item["raw_trace"]["thread_ids"],
        "single_process_audit": "passed",
        "single_thread_audit": "passed",
        "eligible": profile["eligible"],
        "warnings": profile["warnings"],
        "test_payload_read_for_integrity": True,
        "test_policy_replay_executed": False,
    })
  standard_rows = []
  for item in inspected:
    test = item["splits"]["test"]
    standard_rows.append({
        "workload": item["workload"],
        "role": item["role"],
        "test_source_id": item["raw_trace"]["source_trace_id"],
        "path": test["path"],
        "interval": test["interval"],
        "accesses": test["accesses"],
        "sha256": test["sha256"],
        "split_role": "test",
        "formal_test": True,
        "parameter_selection_allowed": False,
        "policy_replay_allowed_stage": 8,
        "fairness_identity": fingerprint_value({
            "source_trace_id": item["raw_trace"]["source_trace_id"],
            "interval": test["interval"],
            "sha256": test["sha256"],
        }),
    })
  standard_lock = {
      "schema_version": "capd_proactive_stage7_standard_test_lock_v1_0",
      "contract_id": CONTRACT_ID,
      "status": "sealed_for_stage8",
      "workloads": standard_rows,
      "test_payload_read_for_integrity": True,
      "test_used_for_parameter_selection": False,
      "test_policy_replay_executed": False,
      "test_performance_inspected": False,
  }
  final_freeze = load_json(repository_path(
      project_root,
      config["entry_authority"]["stage4_final_freeze"]["path"]))
  checkpoints = []
  for checkpoint in final_freeze["final_checkpoints"]:
    resolved_checkpoint = resolve_recorded_artifact(
        project_root, checkpoint["path"], checkpoint["sha256"])
    checkpoints.append({
        "seed": checkpoint["seed"],
        "path": portable_path(resolved_checkpoint, project_root),
        "sha256": checkpoint["sha256"],
    })
  stage8_plan = build_stage8_plan(
      inspected, capacity_matrix, standard_lock,
      checkpoints)
  artifacts = {
      "workload_registry.json": {
          "schema_version": "capd_proactive_stage7_registry_v1_0",
          "contract_id": CONTRACT_ID,
          "status": "frozen",
          "workloads": [
              {
                  "workload": row["workload"],
                  "role": row["role"],
                  "coverage": next(
                      item["coverage"] for item in config["proposed_suite"]
                      if item["workload"] == row["workload"]),
                  "eligible": True,
              } for row in inspected],
      },
      "collection_manifest.json": copy.deepcopy(collection_manifest),
      "raw_trace_manifest.json": {
          "schema_version": "capd_proactive_stage7_raw_trace_manifest_v1_0",
          "contract_id": CONTRACT_ID,
          "traces": [item["raw_trace"] for item in inspected],
      },
      "split_manifest.json": {
          "schema_version": "capd_proactive_stage7_split_manifest_v1_0",
          "contract_id": CONTRACT_ID,
          "interval": "half_open",
          "workloads": [
              {"workload": item["workload"], "splits": item["splits"]}
              for item in inspected],
      },
      "working_set_summary.json": {
          "schema_version": "capd_proactive_stage7_working_set_v1_0",
          "contract_id": CONTRACT_ID,
          "definition":
              "active_unique_pages_from_train_and_validation",
          "workloads": [
              dict({"workload": item["workload"]}, **item["working_set"])
              for item in inspected],
      },
      "workload_profiles.json": {
          "schema_version": "capd_proactive_stage7_profiles_v1_0",
          "contract_id": CONTRACT_ID,
          "selection_inputs": ["train", "validation"],
          "policy": "reactive_lru",
          "test_accessed": False,
          "workloads": descriptions,
          "reactive_lru_profiles": profiles,
      },
      "capacity_matrix.json": {
          "schema_version": "capd_proactive_stage7_capacity_matrix_v1_0",
          "contract_id": CONTRACT_ID,
          "ratios": list(RATIOS),
          "default_ratio": "0.20",
          "capacity_claim":
              "conditional_engineering_default_not_capacity_rule_v2_pass",
          "rows": capacity_matrix,
      },
      "standard_test_lock.json": standard_lock,
      "stage8_execution_plan.json": stage8_plan,
  }
  for filename, payload in artifacts.items():
    write_json_atomic(os.path.join(output_root, filename), payload)
  profile_fields = tuple(descriptions[0].keys())
  profile_csv = os.path.join(output_root, "workload_profiles.csv")
  write_csv_atomic(profile_csv, descriptions, profile_fields)
  table_lines = [
      "# 阶段7六-workload描述",
      "",
      "| workload | 角色 | W页 | D20/D40/D60页 | 读/写比例(T/V) | "
      "进入P50/P95/P99 | LRU降级率 | 资格/警告 |",
      "|---|---|---:|---:|---:|---:|---:|---|",
  ]
  for row in descriptions:
    table_lines.append(
        "| {workload} | {role} | {working_set_pages} | "
        "{D_20_pages}/{D_40_pages}/{D_60_pages} | "
        "{read_ratio:.6f}/{write_ratio:.6f} | "
        "{page_enter_burst_p50}/{page_enter_burst_p95}/"
        "{page_enter_burst_p99} | "
        "{reactive_lru_demotion_rate:.6f} | {eligible}/{warnings} |".format(
            **dict(row, warnings=";".join(row["warnings"]) or "none")))
  profile_table = os.path.join(output_root, "workload_table_cn.md")
  write_text_atomic(profile_table, "\n".join(table_lines) + "\n")
  extra_artifacts = {
      "workload_profiles.csv": profile_csv,
      "workload_table_cn.md": profile_table,
  }
  provenance = {
      "schema_version": "capd_proactive_stage7_provenance_v1_0",
      "contract_id": CONTRACT_ID,
      "status": COLLECTION_COMPLETE,
      "entry_audit": entry,
      "input_sha256": {
          "workload_config": fingerprint_value(config),
          "capacity_config": fingerprint_value(capacity_config),
          "collection_manifest": fingerprint_value(collection_manifest),
      },
      "output_sha256": {
          filename: fingerprint_file(os.path.join(output_root, filename))
          for filename in sorted(artifacts)},
      "test_payload_read_for_integrity": True,
      "test_used_for_parameter_selection": False,
      "test_policy_replay_executed": False,
      "test_performance_inspected": False,
      "formal_test_performance_conclusion": None,
  }
  provenance["output_sha256"].update({
      filename: fingerprint_file(path)
      for filename, path in extra_artifacts.items()})
  write_json_atomic(os.path.join(output_root, "provenance.json"), provenance)
  return {
      "status": COLLECTION_COMPLETE,
      "workload_count": 6,
      "capacity_row_count": len(capacity_matrix),
      "stage8_job_count": stage8_plan["job_count"],
      "output_root": output_root,
  }


def verify_suite(output_root: str,
                 server_test_receipt: Mapping[str, Any]) -> Dict[str, Any]:
  required = (
      "workload_registry.json",
      "collection_manifest.json",
      "raw_trace_manifest.json",
      "split_manifest.json",
      "working_set_summary.json",
      "workload_profiles.json",
      "capacity_matrix.json",
      "standard_test_lock.json",
      "stage8_execution_plan.json",
      "provenance.json",
      "workload_profiles.csv",
      "workload_table_cn.md",
  )
  loaded = {}
  for filename in required:
    path = os.path.join(output_root, filename)
    _require(os.path.isfile(path), "Missing Stage-7 artifact: " + filename)
    if filename.endswith(".json"):
      loaded[filename] = load_json(path)
  registry = loaded["workload_registry.json"]
  _require(registry.get("status") == "frozen" and
           len(registry.get("workloads", [])) == 6 and
           all(row.get("eligible") is True
               for row in registry["workloads"]),
           "Workload registry is not a qualified six-workload freeze.")
  capacities = loaded["capacity_matrix.json"]
  _require(capacities.get("ratios") == list(RATIOS) and
           capacities.get("default_ratio") == "0.20" and
           len(capacities.get("rows", [])) == 18 and
           all(row.get("watermarks_scaled") is False
               for row in capacities["rows"]),
           "Capacity matrix is incomplete or changed.")
  lock = loaded["standard_test_lock.json"]
  _require(lock.get("status") == "sealed_for_stage8" and
           len(lock.get("workloads", [])) == 6 and
           lock.get("test_used_for_parameter_selection") is False and
           lock.get("test_policy_replay_executed") is False and
           lock.get("test_performance_inspected") is False,
           "Standard Test lock is contaminated or incomplete.")
  plan = loaded["stage8_execution_plan.json"]
  _require(plan.get("status") == "frozen_plan_not_executed" and
           plan.get("job_count") == 144 and
           len(plan.get("jobs", [])) == 144 and
           plan.get("test_policy_replay_executed") is False and
           plan.get("performance_results") is None and
           tuple(plan.get("formal_policies", ())) == FORMAL_POLICIES,
           "Stage-8 plan is incomplete or contains results.")
  generalization = plan.get("generalization_contract", {})
  _require(
      generalization.get("held_out_direct_checkpoint_inference") is True and
      generalization.get("checkpoint_retraining_allowed") is False and
      generalization.get("vocabulary_expansion_allowed") is False and
      generalization.get("page_and_pc_oov_policy") ==
      "frozen_checkpoint_unk_index_0" and
      generalization.get("oov_diagnostics_required_for_capd") is True,
      "Stage-8 held-out/OOV reporting contract is missing or changed.")
  _require(server_test_receipt.get("status") == "passed" and
           server_test_receipt.get("runner_exit_code") == 0 and
           server_test_receipt.get("test_policy_replay_executed") is False,
           "Stage1-7 regression receipt is not valid.")
  evidence = {
      filename: fingerprint_file(os.path.join(output_root, filename))
      for filename in required}
  verification = {
      "schema_version": "capd_proactive_stage7_verification_v1_0",
      "contract_id": CONTRACT_ID,
      "status": VERIFIED,
      "stage8_entry_gate": "satisfied",
      "workload_count": 6,
      "seen_workloads": list(SEEN),
      "unseen_workloads": [
          row["workload"] for row in registry["workloads"]
          if row["role"] == "held_out_unseen_workload"],
      "capacity_ratios": list(RATIOS),
      "standard_test_sealed": True,
      "pressure_test_enabled": False,
      "stage8_job_count": 144,
      "test_payload_read_for_integrity": True,
      "test_used_for_parameter_selection": False,
      "test_policy_replay_executed": False,
      "test_performance_inspected": False,
      "capd_used_for_workload_selection": False,
      "frozen_parameters_changed": False,
      "formal_test_performance_conclusion": None,
      "evidence_sha256": evidence,
  }
  write_json_atomic(os.path.join(output_root, "verification.json"),
                    verification)
  return verification
