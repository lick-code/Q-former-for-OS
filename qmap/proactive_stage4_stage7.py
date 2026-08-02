# coding=utf-8
"""R4-authoritative Stage-7 Train/Validation adapter for CAPD Stage 4.

This module intentionally contains no Test or Pressure-data entry point.  It
reuses the deterministic proactive replay and label primitives, while binding
all controller values to the registered R4 freeze instead of legacy Stage-4
constants.
"""

from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qmap import finals_config
from qmap import finals_generator
from qmap import proactive_replay
from qmap import proactive_stage3
from qmap import proactive_stage4 as shared_stage4


SCHEMA_VERSION = "capd_proactive_stage4_stage7_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE4-STAGE7-1.0"
MANIFEST_SCHEMA = "capd_proactive_stage4_stage7_input_manifest_v1_0"
SAMPLE_SCHEMA = "capd_proactive_stage4_stage7_sample_v1_0"
TRAINING_CONTRACT_SCHEMA = (
    "capd_proactive_stage4_stage7_training_contract_v1_0")
SEARCH_SCHEMA = "capd_proactive_stage4_stage7_search_v1_0"
RUN_ID = "stage4-stage7-unified-r1"
OUTPUT_ROOT = "outputs/capd_proactive_stage4_stage7"
WORKLOADS = (
    "canneal", "streamcluster_pressure", "dedup_pressure", "blackscholes",
    "swaptions", "fluidanimate")
SPLITS = ("train", "validation")
FORMAL_SEEDS = (3136859, 42, 2026)
EXPECTED_WORKLOAD_METHODS = {
    "canneal": {"D": 120, "F_low": 6, "F_target": 16},
    "streamcluster_pressure": {"D": 22, "F_low": 1, "F_target": 3},
    "dedup_pressure": {"D": 21, "F_low": 1, "F_target": 3},
    "blackscholes": {"D": 8, "F_low": 1, "F_target": 2},
    "swaptions": {"D": 8, "F_low": 1, "F_target": 2},
    "fluidanimate": {"D": 22, "F_low": 1, "F_target": 3},
}
R4_FINAL_SHA256 = (
    "02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1")
R4_PRESSURE_CONTRACT_SHA256 = (
    "1c4582c20098425f9e8a155e832aad737e35160e8d254808a09706ca45394761")
R4_RUN_STATE_SHA256 = (
    "71da1d6386d7f1f7e62ef4965d3d41abc7c5b775350760cb249dabbece8a0f63")
R2_MANIFEST_SHA256 = (
    "108b2c34b5809e911b8b92864b111fc117caea8566997c101607928c590ed85f")
FORBIDDEN_ROLES = ("test", "pressure", "pressure_test")
FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(^|[/\\])test([/\\]|$)", re.IGNORECASE),
    re.compile(r"pressure[_-]?test", re.IGNORECASE),
    re.compile(r"pressure[_-]?(window|derived|output|manifest)", re.IGNORECASE),
    re.compile(r"capd_proactive_pressure", re.IGNORECASE),
    re.compile(r"capd_proactive_stage8", re.IGNORECASE),
    re.compile(r"capd_proactive_stage4([/\\]|$)", re.IGNORECASE),
)
SEARCH_FORBIDDEN_KEYS = {
    "window_records", "W_ref_quantile", "capacity_ratio", "D", "alpha",
    "beta", "F_low", "F_target", "b_max", "candidate_size_K", "K"}


class Stage4Stage7ContractError(ValueError):
  """Fail-closed contract violation."""


def _require(condition: bool, message: str) -> None:
  if not condition:
    raise Stage4Stage7ContractError(message)


def _reject_constant(value: str) -> None:
  raise Stage4Stage7ContractError("Non-finite JSON value: {}".format(value))


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
  value = {}
  for key, item in pairs:
    _require(key not in value, "Duplicate JSON key: {}".format(key))
    value[key] = item
  return value


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as handle:
    return json.load(handle, object_pairs_hook=_unique_object,
                     parse_constant=_reject_constant)


def fingerprint_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
  encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False).encode("utf-8")
  return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(prefix=".stage4-stage7-",
                                            suffix=".tmp", dir=directory)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
      json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2,
                allow_nan=False)
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _positive_int(value: Any, field: str) -> int:
  _require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
           "{} must be a positive integer".format(field))
  return value


def _finite(value: Any, field: str) -> float:
  _require(isinstance(value, (int, float)) and not isinstance(value, bool) and
           math.isfinite(float(value)), "{} must be finite".format(field))
  return float(value)


def _sha(path: str, expected: str, role: str) -> str:
  _require(os.path.isfile(path), "{} is missing: {}".format(role, path))
  actual = fingerprint_file(path)
  _require(actual == expected,
           "{} SHA-256 mismatch: expected {}, got {}".format(
               role, expected, actual))
  return actual


def _watermark_map(freeze: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
  rows = freeze.get("watermarks")
  _require(isinstance(rows, list) and len(rows) == len(WORKLOADS),
           "R4 watermarks must cover exactly six workloads")
  result = {}
  for row in rows:
    workload = row.get("workload")
    _require(workload in WORKLOADS and workload not in result,
             "R4 watermarks contain an unknown or duplicate workload")
    D = _positive_int(row.get("D"), "watermarks.D")
    F_low = _positive_int(row.get("F_low"), "watermarks.F_low")
    F_target = _positive_int(row.get("F_target"), "watermarks.F_target")
    _require(0 < F_low < F_target <= D,
             "Invalid R4 watermarks for {}".format(workload))
    result[workload] = {"D": D, "F_low": F_low, "F_target": F_target}
  _require(set(result) == set(WORKLOADS), "R4 workload set is incomplete")
  return result


def validate_stage3_authority(
    final_freeze_path: str, expected_final_sha: str = R4_FINAL_SHA256,
    expected_pressure_sha: str = R4_PRESSURE_CONTRACT_SHA256,
    expected_run_state_sha: str = R4_RUN_STATE_SHA256) -> Dict[str, Any]:
  """Validates only the three post-freeze authority files (never verification)."""
  final_freeze_path = os.path.abspath(final_freeze_path)
  directory = os.path.dirname(final_freeze_path)
  pressure_path = os.path.join(directory, "pressure_generation_contract.json")
  run_state_path = os.path.join(directory, "run_state.json")
  final_sha = _sha(final_freeze_path, expected_final_sha, "R4 final freeze")
  pressure_sha = _sha(pressure_path, expected_pressure_sha,
                      "R4 pressure generation contract")
  run_state_sha = _sha(run_state_path, expected_run_state_sha, "R4 run state")
  freeze = load_json(final_freeze_path)
  run_state = load_json(run_state_path)
  _require(freeze.get("formal_freeze") is True,
           "R4 formal_freeze must be true")
  _require(freeze.get("stage4_entry_allowed") is True,
           "R4 stage4_entry_allowed must be true")
  _require(freeze.get("status") ==
           "STAGE3_STAGE7_DERIVED_SELECTION_FORMALLY_FROZEN",
           "R4 final freeze status mismatch")
  _require(run_state.get("formal_freeze") is True,
           "R4 run_state formal_freeze must be true")
  _require(run_state.get("status") == "derived_selection_formally_frozen",
           "R4 run_state status is not derived_selection_formally_frozen")
  _require(freeze.get("run_id") == "stage3-stage7-unified-contract-r4",
           "Unexpected R4 run ID")
  _require(freeze.get("selected_candidate_id") ==
           "win500000-q50-r10-a15-b04-batch2", "R4 candidate mismatch")
  _require(freeze.get("candidate_size_K") == 8, "R4 K must be 8")
  _require(freeze.get("b_max") == 2, "R4 b_max must be 2")
  watermarks = _watermark_map(freeze)
  matrix = freeze.get("unified_capacity_matrix")
  _require(isinstance(matrix, list) and len(matrix) == len(WORKLOADS),
           "R4 capacity matrix must cover six workloads")
  capacities = {}
  for row in matrix:
    workload = row.get("workload")
    _require(workload in WORKLOADS and workload not in capacities,
             "R4 capacity matrix contains unknown or duplicate workload")
    _require(row.get("D_standard") == row.get("D_pressure"),
             "Standard/Pressure D mismatch for {}".format(workload))
    capacities[workload] = _positive_int(row.get("D_standard"), "D_standard")
    _require(capacities[workload] == watermarks[workload]["D"],
             "Capacity/watermark D mismatch for {}".format(workload))
  execution = freeze.get("shared_standard_pressure_execution_contract", {})
  _require(execution.get("candidate_size_K") == 8, "Execution K must be 8")
  _require(execution.get("batch_mechanism", {}).get("b_max") == 2,
           "Execution b_max must be 2")
  _require(execution.get("initial_state") == "empty_dram_per_window",
           "R4 initial state must be empty_dram_per_window")
  costs = execution.get("cost_profile")
  _require(costs == {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
                     "demotion": 10}, "R4 cost profile mismatch")
  return {
      "run_id": freeze["run_id"], "final_freeze_path": final_freeze_path,
      "final_freeze_sha256": final_sha,
      "pressure_generation_contract_path": pressure_path,
      "pressure_generation_contract_sha256": pressure_sha,
      "run_state_path": run_state_path, "run_state_sha256": run_state_sha,
      "selected_candidate_id": freeze["selected_candidate_id"],
      "window_records": int(freeze["selected_window_records"]),
      "W_ref_quantile": float(freeze["W_ref_quantile"]),
      "capacity_ratio": float(freeze["requested_pressure_ratio"]),
      "alpha": float(freeze["alpha"]), "beta": float(freeze["beta"]),
      "b_max": 2, "candidate_size_K": 8,
      "initial_dram_state": execution["initial_state"],
      "cost_profile": copy.deepcopy(costs), "workloads": watermarks,
  }


def _forbidden_path(path: str) -> bool:
  normalized = str(path).replace("\\", "/")
  return any(pattern.search(normalized) for pattern in FORBIDDEN_PATH_PATTERNS)


def validate_r2_source_manifest(
    value: Mapping[str, Any], manifest_path: str,
    expected_sha: str = R2_MANIFEST_SHA256) -> List[Dict[str, Any]]:
  _sha(os.path.abspath(manifest_path), expected_sha, "R2 input manifest")
  _require(value.get("formal_test") is False and value.get("test_entries") == 0,
           "R2 manifest must contain zero Test entries")
  entries = value.get("entries")
  _require(isinstance(entries, list) and len(entries) == 12,
           "R2 manifest must contain 12 entries")
  seen = set()
  counts = collections.Counter()
  for entry in entries:
    workload = entry.get("workload")
    split = entry.get("split_role")
    _require(workload in WORKLOADS, "Unknown R2 workload")
    _require(split in SPLITS, "R2 split_role must be train/validation")
    _require((workload, split) not in seen, "Duplicate workload/split")
    seen.add((workload, split))
    counts[split] += 1
    _require(entry.get("formal_test") is False, "Test input is forbidden")
    _require(isinstance(entry.get("source_trace_id"), str) and
             entry["source_trace_id"], "source_trace_id is required")
    interval = entry.get("source_interval", {})
    start = interval.get("start_inclusive")
    end = interval.get("end_exclusive")
    _require(isinstance(start, int) and isinstance(end, int) and
             0 <= start < end, "Invalid half-open source interval")
    _require(end - start == entry.get("accesses"),
             "Source interval/access count mismatch")
    _require(re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))),
             "Trace SHA-256 is missing")
    _require(not _forbidden_path(entry.get("trace_path", "")),
             "Test/Pressure-derived/old-Stage4 path is forbidden")
  _require(counts == collections.Counter({"train": 6, "validation": 6}),
           "R2 split counts must be 6 Train and 6 Validation")
  _require(seen == {(w, s) for w in WORKLOADS for s in SPLITS},
           "R2 workload/split coverage is incomplete")
  return [copy.deepcopy(entry) for entry in entries]


def prepare_input_manifest(source_manifest_path: str, final_freeze_path: str,
                           project_root: str) -> Dict[str, Any]:
  authority = validate_stage3_authority(final_freeze_path)
  source_manifest_path = os.path.abspath(source_manifest_path)
  source = load_json(source_manifest_path)
  entries = validate_r2_source_manifest(source, source_manifest_path)
  prepared = []
  for entry in entries:
    item = copy.deepcopy(entry)
    item["trace_path"] = entry["trace_path"]
    item["trace_sha256"] = entry["sha256"]
    item["r2_manifest_sha256"] = R2_MANIFEST_SHA256
    item["r4_freeze_sha256"] = authority["final_freeze_sha256"]
    item.pop("resolved_trace_path", None)
    prepared.append(item)
  result = {
      "schema_version": MANIFEST_SCHEMA, "contract_id": CONTRACT_ID,
      "run_id": RUN_ID, "path_base": "project_root",
      "project_root_at_generation": os.path.abspath(project_root),
      "source_manifest_path": source_manifest_path,
      "source_manifest_sha256": R2_MANIFEST_SHA256,
      "stage3_freeze_path": os.path.abspath(final_freeze_path),
      "stage3_freeze_sha256": authority["final_freeze_sha256"],
      "allowed_split_roles": list(SPLITS), "forbidden_roles": list(FORBIDDEN_ROLES),
      "formal_test": False, "pressure_input_used": False,
      "entries": prepared,
  }
  validate_input_manifest(result, "<not-written-yet>", project_root)
  return result


def validate_input_manifest(value: Mapping[str, Any], manifest_path: str,
                            project_root: str) -> List[Dict[str, Any]]:
  _require(value.get("schema_version") == MANIFEST_SCHEMA,
           "Prepared manifest schema mismatch")
  _require(value.get("contract_id") == CONTRACT_ID, "Contract ID mismatch")
  _require(value.get("formal_test") is False and
           value.get("pressure_input_used") is False,
           "Test/Pressure input is forbidden")
  _require(value.get("source_manifest_sha256") == R2_MANIFEST_SHA256,
           "R2 manifest identity mismatch")
  _require(value.get("stage3_freeze_sha256") == R4_FINAL_SHA256,
           "R4 freeze identity mismatch")
  source_manifest_path = os.path.abspath(value.get("source_manifest_path", ""))
  _require(os.path.isfile(source_manifest_path),
           "Authoritative R2 source manifest is missing")
  source_value = load_json(source_manifest_path)
  source_entries = validate_r2_source_manifest(
      source_value, source_manifest_path, R2_MANIFEST_SHA256)
  registered = {(entry["workload"], entry["split_role"]): entry
                for entry in source_entries}
  entries = value.get("entries")
  _require(isinstance(entries, list) and len(entries) == 12,
           "Prepared manifest must contain 12 entries")
  seen = set()
  seen_paths = set()
  seen_trace_sha = set()
  source_ranges = collections.defaultdict(list)
  resolved = []
  for entry in entries:
    workload, split = entry.get("workload"), entry.get("split_role")
    _require(workload in WORKLOADS and split in SPLITS,
             "Prepared manifest has forbidden workload/split")
    _require((workload, split) not in seen, "Duplicate workload/split")
    seen.add((workload, split))
    _require(entry.get("trace_sha256") == entry.get("sha256"),
             "Trace identity aliases disagree")
    _require(entry.get("formal_test") is False,
             "Prepared Test input is forbidden")
    _require(isinstance(entry.get("source_trace_id"), str) and
             entry["source_trace_id"], "source_trace_id is required")
    _require(entry.get("r2_manifest_sha256") == R2_MANIFEST_SHA256 and
             entry.get("r4_freeze_sha256") == R4_FINAL_SHA256,
             "Entry authority identity mismatch")
    source_entry = registered.get((workload, split))
    _require(source_entry is not None, "Input is not registered by R2")
    for field in ("trace_path", "sha256", "source_trace_id", "source_interval",
                  "accesses", "page_shift", "formal_test"):
      _require(entry.get(field) == source_entry.get(field),
               "Prepared input differs from R2 registration: {}".format(field))
    interval = entry.get("source_interval", {})
    start, end = interval.get("start_inclusive"), interval.get("end_exclusive")
    _require(isinstance(start, int) and isinstance(end, int) and start < end and
             end - start == entry.get("accesses"), "Source interval mismatch")
    path = os.path.abspath(os.path.join(project_root, entry["trace_path"]))
    _require(not _forbidden_path(path), "Forbidden Test/Pressure/old output path")
    _require(os.path.isfile(path), "Registered trace is missing: {}".format(path))
    _require(path not in seen_paths, "Duplicate resolved trace path")
    _require(entry["trace_sha256"] not in seen_trace_sha,
             "Duplicate trace contents across Train/Validation")
    seen_paths.add(path)
    seen_trace_sha.add(entry["trace_sha256"])
    _require(fingerprint_file(path) == entry["trace_sha256"],
             "Trace SHA-256 mismatch: {}".format(path))
    source_key = (workload, entry["source_trace_id"])
    for previous_start, previous_end in source_ranges[source_key]:
      _require(end <= previous_start or start >= previous_end,
               "Overlapping source intervals are forbidden")
    source_ranges[source_key].append((start, end))
    item = copy.deepcopy(entry)
    item["resolved_trace_path"] = path
    resolved.append(item)
  _require(seen == {(w, s) for w in WORKLOADS for s in SPLITS},
           "Prepared manifest coverage is incomplete")
  return resolved


def load_registered_traces(entries: Sequence[Mapping[str, Any]]) -> Tuple[
    Dict[str, Dict[str, Sequence[Any]]], Dict[Tuple[str, str], Mapping[str, Any]]]:
  traces = collections.defaultdict(dict)
  identities = {}
  for entry in entries:
    trace, rw_source = proactive_stage3._read_compact_trace(
        entry["resolved_trace_path"], int(entry["page_shift"]))
    _require(len(trace) == int(entry["accesses"]),
             "Parsed trace length/source interval mismatch")
    traces[entry["workload"]][entry["split_role"]] = trace
    identity = copy.deepcopy(entry)
    identity["rw_source"] = rw_source
    identities[(entry["workload"], entry["split_role"])] = identity
  return dict(traces), identities


def validate_registered_trace_records(
    entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
  """Parses one registered trace at a time and verifies its source interval."""
  result = []
  for entry in entries:
    trace, rw_source = proactive_stage3._read_compact_trace(
        entry["resolved_trace_path"], int(entry["page_shift"]))
    expected = (int(entry["source_interval"]["end_exclusive"]) -
                int(entry["source_interval"]["start_inclusive"]))
    _require(len(trace) == expected == int(entry["accesses"]),
             "Parsed trace length/source interval mismatch: {} {}".format(
                 entry["workload"], entry["split_role"]))
    result.append({"workload": entry["workload"],
                   "split_role": entry["split_role"],
                   "parsed_accesses": len(trace), "rw_source": rw_source})
    del trace
  return result


def _walk_keys(value: Any) -> Iterable[str]:
  if isinstance(value, Mapping):
    for key, child in value.items():
      yield key
      yield from _walk_keys(child)
  elif isinstance(value, list):
    for child in value:
      yield from _walk_keys(child)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
  result = copy.deepcopy(base)
  for key, value in override.items():
    if key == "id":
      continue
    if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
      result[key] = _deep_merge(result[key], value)
    else:
      result[key] = copy.deepcopy(value)
  return result


def validate_search_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(value.get("schema_version") == SEARCH_SCHEMA, "Search schema mismatch")
  _require(value.get("contract_id") == CONTRACT_ID, "Search contract mismatch")
  fixed = value.get("fixed", {})
  _require(fixed.get("candidate_size_K") == 8, "Fixed K must be 8")
  _require(fixed.get("b_max") == 2, "Fixed b_max must be 2")
  search = value.get("search", {})
  forbidden = SEARCH_FORBIDDEN_KEYS.intersection(_walk_keys(search))
  _require(not forbidden, "Frozen parameters entered search: {}".format(
      sorted(forbidden)))
  _require(tuple(value.get("formal_seeds", [])) == FORMAL_SEEDS,
           "Formal seeds must be explicit and complete")
  phases = search.get("phases", [])
  _require([phase.get("name") for phase in phases] ==
           ["semantic", "architecture", "optimization"],
           "Search phase order mismatch")
  count = sum(len(phase.get("candidates", [])) for phase in phases)
  _require(count == search.get("candidate_count") == 15,
           "Search must declare exactly 15 candidate configurations")
  _require(search.get("training_run_count") == count * len(FORMAL_SEEDS),
           "Training run count mismatch")
  reference = search.get("reference", {})
  validate_candidate(reference, "reference")
  selection = value.get("selection", {})
  _require(selection.get("seed_rule") ==
           "retain_all_formal_seeds_never_select_or_discard_a_seed",
           "Seed selection is forbidden")
  gate = value.get("confirmation_gate", {})
  _require(gate.get("full_search_allowed") is False and
           gate.get("formal_freeze_allowed") is False,
           "Draft config must remain behind confirmation gate")
  return value


def validate_candidate(candidate: Mapping[str, Any], context: str) -> None:
  L = _positive_int(candidate.get("lookahead_L"), context + ".lookahead_L")
  H = _positive_int(candidate.get("history_H"), context + ".history_H")
  del L, H
  weights = candidate.get("label_weights")
  _require(isinstance(weights, list) and len(weights) == 3,
           context + ".label_weights must have three values")
  for index, weight in enumerate(weights):
    _finite(weight, context + ".label_weights[{}]".format(index))
  model = candidate.get("model", {})
  for field in ("hidden_dim", "address_embed_dim", "pc_embed_dim",
                "rw_embed_dim", "page_embed_dim", "num_layers", "num_heads",
                "feedforward_dim", "num_queries", "page_dim",
                "page_state_dim", "address_vocab_size", "pc_vocab_size",
                "page_vocab_size"):
    _positive_int(model.get(field), context + ".model." + field)
  _require(model["hidden_dim"] == model["address_embed_dim"] +
           model["pc_embed_dim"] + model["rw_embed_dim"],
           context + " embedding dimensions must sum to hidden_dim")
  _require(model["hidden_dim"] % model["num_heads"] == 0,
           context + " hidden_dim must be divisible by num_heads")
  dropout = _finite(model.get("dropout"), context + ".model.dropout")
  _require(0.0 <= dropout < 1.0, context + " dropout out of range")
  _require(model.get("ablation") == "cross_attention",
           context + " must use cross_attention")
  training = candidate.get("training", {})
  _finite(training.get("learning_rate"), context + ".training.learning_rate")
  _finite(training.get("weight_decay"), context + ".training.weight_decay")
  for field in ("batch_size", "epochs", "num_workers"):
    _positive_int(training.get(field), context + ".training." + field)
  _require(training.get("deterministic_algorithms") is True,
           context + " must require deterministic algorithms")
  _require(training.get("precision") == "fp32",
           context + " must use fp32")
  _require(training.get("checkpoint_tie_break") == "earliest_epoch",
           context + " checkpoint tie-break mismatch")


def resolve_phase_candidates(config: Mapping[str, Any], phase_name: str,
                             inherited: Optional[Mapping[str, Any]] = None
                             ) -> List[Dict[str, Any]]:
  validate_search_config(config)
  phase = next((item for item in config["search"]["phases"]
                if item["name"] == phase_name), None)
  _require(phase is not None, "Unknown phase: {}".format(phase_name))
  base = copy.deepcopy(inherited or config["search"]["reference"])
  resolved = []
  for override in phase["candidates"]:
    candidate = _deep_merge(base, override)
    candidate["candidate_id"] = override["id"]
    candidate["phase"] = phase_name
    validate_candidate(candidate, override["id"])
    candidate["candidate_sha256"] = fingerprint_value(candidate)
    resolved.append(candidate)
  return resolved


def replay_stage0_template(method: Mapping[str, Any]) -> Dict[str, Any]:
  """Builds shared state-machine semantics; values come from R4 method."""
  template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "configs", "finals",
                               "capd_proactive_stage0.json")
  value = load_json(template_path)
  value["active_demotion"] = {
      "F_low": method["F_low"], "F_target": method["F_target"],
      "b_max": method["b_max"]}
  value["memory"]["dram_working_set_ratio"] = method["capacity_ratio"]
  value["memory"]["working_set_definition"] = (
      "r4_train_chronological_window_unique_pages_quantile")
  value["evaluation"]["cost_profile"]["weights"] = copy.deepcopy(
      method["cost_profile"])
  return value


def sample_cache_identity(candidate: Mapping[str, Any], authority: Mapping[str, Any],
                          input_manifest_sha: str) -> Dict[str, Any]:
  return {
      "schema_version": SAMPLE_SCHEMA, "contract_id": CONTRACT_ID,
      "lookahead_L": candidate["lookahead_L"],
      "history_H": candidate["history_H"],
      "label_weights": list(candidate["label_weights"]),
      "candidate_size_K": 8, "b_max": 2,
      "r4_freeze_sha256": authority["final_freeze_sha256"],
      "r2_manifest_sha256": R2_MANIFEST_SHA256,
      "prepared_input_manifest_sha256": input_manifest_sha,
  }


class Stage7TrainingSampleRanking(shared_stage4.TrainingSampleRanking):
  """Adds compact, auditable tier-state identities to shared label samples."""

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    previous = len(self.rows)
    ranking = super().rank_candidates(
        state, candidates, candidate_features, policy_context)
    if len(self.rows) > previous:
      row = self.rows[-1]
      dram = list(state.dram_lru)
      nvm = sorted(state.nvm_resident)
      dirty = sorted(page for page, value in state.dirty_state.items() if value)
      row.update({
          "dram_state_mru_to_lru": dram,
          "dram_state_sha256": fingerprint_value(dram),
          "nvm_state_page_count": len(nvm),
          "nvm_state_sha256": fingerprint_value(nvm),
          "dirty_state_sha256": fingerprint_value(dirty),
          "tier_state_representation":
              "dram_explicit_nvm_and_dirty_canonical_sha256",
      })
    return ranking


class IndexedLabelProvider(object):
  """O(log n) exact equivalent of shared Stage-4 future label scanning."""

  def __init__(self, trace: Sequence[Any], lookahead: int):
    self.trace = trace
    self.lookahead = int(lookahead)
    self.oracle = finals_generator.FutureOracle(
        trace, lookahead, require_complete=False)

  def __call__(self, trace, decision_index, candidate, lookahead):
    _require(trace is self.trace and int(lookahead) == self.lookahead,
             "Indexed label provider trace/contract mismatch")
    effective = min(self.lookahead, max(0, len(trace) - decision_index - 1))
    next_distance, frequency, writes = self.oracle.stats(
        decision_index, candidate)
    denominator = float(max(1, effective))
    return {
        "d_hat": (1.0 if next_distance is None else
                  min(next_distance, max(1, effective)) / denominator),
        "q_hat": 1.0 - min(frequency / denominator, 1.0),
        "w_hat": min(writes / denominator, 1.0),
        "next_reuse_distance": next_distance,
        "future_access_count": frequency,
        "future_write_count": writes,
        "effective_lookahead": effective,
        "complete_future_window": effective == self.lookahead,
        "no_future_reuse": next_distance is None,
    }


def generate_samples_for_trace(
    trace: Sequence[Any], entry: Mapping[str, Any], candidate: Mapping[str, Any],
    authority: Mapping[str, Any], input_manifest_sha: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
  workload, split = entry["workload"], entry["split_role"]
  method = dict(authority["workloads"][workload])
  method.update({"b_max": 2, "candidate_size_K": 8,
                 "cost_profile": authority["cost_profile"],
                 "capacity_ratio": authority["capacity_ratio"]})
  _require(method["candidate_size_K"] == 8 and method["b_max"] == 2,
           "R4 K/b_max changed")
  stage0 = replay_stage0_template(method)
  identity = sample_cache_identity(candidate, authority, input_manifest_sha)
  identity_sha = fingerprint_value(identity)
  rows, summaries = [], []
  window_size = int(authority["window_records"])
  source_start = int(entry["source_interval"]["start_inclusive"])
  for window_start in range(0, len(trace), window_size):
    window = trace[window_start:window_start + window_size]
    ranker = Stage7TrainingSampleRanking(
        window, workload, split, int(candidate["lookahead_L"]),
        int(candidate["history_H"]), 8, candidate["label_weights"],
        identity_sha[:24], label_provider=IndexedLabelProvider(
            window, int(candidate["lookahead_L"])))
    parameters = proactive_replay.ReplayParameters(
        policy_name="capd", dram_capacity_pages=method["D"],
        F_low=method["F_low"], F_target=method["F_target"], b_max=2,
        candidate_size_K=8, history_window_size=candidate["history_H"],
        early_reuse_window=64)
    replay = proactive_replay.ProactiveReplay(
        stage0, parameters, ranking_policy=ranker, invariant_mode="boundary",
        record_details=False)
    result = replay.run(window, copy_trace=False, compact=True)
    summaries.append(result["summary"])
    for row in ranker.rows:
      local_index = int(row["decision_index"])
      row.update({
          "schema_version": SAMPLE_SCHEMA, "contract_id": CONTRACT_ID,
          "experiment_id": identity_sha[:24], "workload_id": workload,
          "split": split, "split_role": split,
          "source_trace_id": entry["source_trace_id"],
          "source_interval": copy.deepcopy(entry["source_interval"]),
          "record_index": source_start + window_start + local_index,
          "window_start_record_index": source_start + window_start,
          "D": method["D"], "F_low": method["F_low"],
          "F_target": method["F_target"], "b_max": 2,
          "candidate_size_K": 8, "initial_dram_state": "empty",
          "sample_generation_contract_sha256": identity_sha,
          "r4_freeze_sha256": authority["final_freeze_sha256"],
          "r2_manifest_sha256": R2_MANIFEST_SHA256,
          "prepared_input_manifest_sha256": input_manifest_sha,
          "vocabulary_sha256": "bound_after_train_only_vocabulary_build",
      })
      _require(sum(row["candidate_mask"]) <= 8, "Candidate set exceeds K=8")
      _require(int(row["b_t"]) <= 2, "Active demotion round exceeds b_max=2")
      rows.append(row)
  diagnostics = {
      "workload": workload, "split_role": split, "sample_count": len(rows),
      "windows": len(summaries), "method": method,
      "sample_generation_contract_sha256": identity_sha,
  }
  return rows, diagnostics


def build_train_only_vocabulary(train_jsonl: str, validation_jsonl: str,
                                maximum_page_vocab: int = 100000,
                                maximum_pc_vocab: int = 50000) -> Dict[str, Any]:
  pages, pcs, seen_pages, seen_pcs = [], [], set(), set()
  with open(train_jsonl, "r", encoding="utf-8") as handle:
    for line in handle:
      row = json.loads(line)
      for page, mask in zip(row["history_page_ids"], row["history_mask"]):
        if mask and page not in seen_pages and len(pages) + 1 < maximum_page_vocab:
          seen_pages.add(page); pages.append(page)
      for page, mask in zip(row["candidate_pages"], row["candidate_mask"]):
        if mask and page not in seen_pages and len(pages) + 1 < maximum_page_vocab:
          seen_pages.add(page); pages.append(page)
      for pc, mask in zip(row["pc"], row["history_mask"]):
        if mask and pc not in seen_pcs and len(pcs) + 1 < maximum_pc_vocab:
          seen_pcs.add(pc); pcs.append(pc)
  page_map = {str(value): index + 1 for index, value in enumerate(pages)}
  pc_map = {str(value): index + 1 for index, value in enumerate(pcs)}
  workload_oov = collections.defaultdict(lambda: {
      "page_oov": set(), "pc_oov": set(), "page_total": 0,
      "pc_total": 0, "page_oov_count": 0, "pc_oov_count": 0})
  with open(validation_jsonl, "r", encoding="utf-8") as handle:
    for line in handle:
      row = json.loads(line); workload = row["workload_id"]
      for page, mask in zip(row["history_page_ids"], row["history_mask"]):
        if mask:
          workload_oov[workload]["page_total"] += 1
          if str(page) not in page_map:
            workload_oov[workload]["page_oov"].add(page)
            workload_oov[workload]["page_oov_count"] += 1
      for page, mask in zip(row["candidate_pages"], row["candidate_mask"]):
        if mask:
          workload_oov[workload]["page_total"] += 1
          if str(page) not in page_map:
            workload_oov[workload]["page_oov"].add(page)
            workload_oov[workload]["page_oov_count"] += 1
      for pc, mask in zip(row["pc"], row["history_mask"]):
        if mask:
          workload_oov[workload]["pc_total"] += 1
          if str(pc) not in pc_map:
            workload_oov[workload]["pc_oov"].add(pc)
            workload_oov[workload]["pc_oov_count"] += 1
  identity = {
      "page_input_to_index": page_map, "pc_input_to_index": pc_map,
      "unk_index": 0, "fit_scope": "six_train_only",
  }
  return {
      "schema_version": "capd_proactive_stage4_stage7_vocabulary_v1_0",
      "contract_id": CONTRACT_ID, "fit_scope": "six_train_only",
      "validation_used_for_fit": False, "test_used_for_fit": False,
      "pressure_used_for_fit": False, "unk_index": 0,
      "page_vocabulary_size": len(page_map) + 1,
      "pc_vocabulary_size": len(pc_map) + 1,
      "page_vocabulary_sha256": fingerprint_value(page_map),
      "pc_vocabulary_sha256": fingerprint_value(pc_map),
      "vocabulary_sha256": fingerprint_value(identity),
      "_page_input_to_index": page_map,
      "_pc_input_to_index": pc_map,
      "validation_oov_by_workload": {
          workload: {
              "page_total": workload_oov[workload]["page_total"],
              "page_oov_count": workload_oov[workload]["page_oov_count"],
              "page_oov_unique": len(workload_oov[workload]["page_oov"]),
              "page_oov_rate": (workload_oov[workload]["page_oov_count"] /
                                float(workload_oov[workload]["page_total"])
                                if workload_oov[workload]["page_total"] else 0.0),
              "pc_total": workload_oov[workload]["pc_total"],
              "pc_oov_count": workload_oov[workload]["pc_oov_count"],
              "pc_oov_unique": len(workload_oov[workload]["pc_oov"]),
              "pc_oov_rate": (workload_oov[workload]["pc_oov_count"] /
                              float(workload_oov[workload]["pc_total"])
                              if workload_oov[workload]["pc_total"] else 0.0),
          }
          for workload in WORKLOADS},
  }


def validate_training_contract(value: Mapping[str, Any], train_path: str,
                               valid_path: str,
                               explicit_seed: Optional[int] = None
                               ) -> Dict[str, Any]:
  required = {"schema_version", "contract_id", "experiment_id", "seed",
              "expected_shape", "sample_identity", "labels", "model_args",
              "training_args", "data", "method", "vocabulary",
              "authority",
              "test_trace_opened", "pressure_trace_opened"}
  _require(isinstance(value, Mapping) and not (required - set(value)),
           "Stage7 training contract is incomplete")
  _require(value["schema_version"] == TRAINING_CONTRACT_SCHEMA and
           value["contract_id"] == CONTRACT_ID, "Training identity mismatch")
  _require(value["test_trace_opened"] is False and
           value["pressure_trace_opened"] is False,
           "Training contract is contaminated")
  shape = value["expected_shape"]
  _require(shape == {"H": value["candidate"]["history_H"], "K": 8,
                     "page_state_dim": 4}, "Training shape mismatch")
  candidate = copy.deepcopy(value["candidate"])
  validate_candidate(candidate, value["experiment_id"])
  _require(value["labels"] == {"lambda_1": candidate["label_weights"][0],
                               "lambda_2": candidate["label_weights"][1],
                               "lambda_3": candidate["label_weights"][2]},
           "Training labels mismatch")
  _require(value["model_args"] == candidate["model"], "model_args mismatch")
  _require(value["training_args"] == candidate["training"],
           "training_args mismatch")
  seed = _positive_int(value["seed"], "seed")
  _require(seed in FORMAL_SEEDS, "Unregistered seed")
  if explicit_seed is not None:
    _require(seed == int(explicit_seed), "CLI seed/contract mismatch")
  for split, path in (("train", train_path), ("validation", valid_path)):
    item = value["data"].get(split, {})
    _require(os.path.abspath(item.get("path", "")) == os.path.abspath(path),
             "{} data path mismatch".format(split))
    _require(fingerprint_file(path) == item.get("sha256"),
             "{} data SHA mismatch".format(split))
    _positive_int(item.get("sample_count"), split + ".sample_count")
  method = value["method"]
  _require(method.get("candidate_size_K") == 8 and method.get("b_max") == 2,
           "Training method K/b_max mismatch")
  _require(method.get("workloads") == EXPECTED_WORKLOAD_METHODS,
           "Training workload method matrix differs from R4")
  _require(method.get("cost_profile") == {
      "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
      "Training cost profile differs from R4")
  authority = value["authority"]
  _require(authority.get("r4_freeze_sha256") == R4_FINAL_SHA256 and
           authority.get("r2_manifest_sha256") == R2_MANIFEST_SHA256,
           "Training authority SHA mismatch")
  vocab = value["vocabulary"]
  _require(vocab.get("fit_scope") == "six_train_only" and
           vocab.get("validation_used_for_fit") is False,
           "Vocabulary is not Train-only")
  identity = value["sample_identity"]
  _require(identity == {"schema_version": SAMPLE_SCHEMA,
                        "contract_id": CONTRACT_ID,
                        "experiment_id": value["experiment_id"]},
           "Sample identity mismatch")
  return {
      "contract": value, "contract_fingerprint": fingerprint_value(value),
      "expected_shape": copy.deepcopy(shape), "sample_identity": identity,
      "weights": [value["labels"]["lambda_1"],
                  value["labels"]["lambda_2"],
                  value["labels"]["lambda_3"]],
      "seed": seed, "training": value["training_args"],
      "model_args": value["model_args"], "data": value["data"],
      "vocabulary": vocab, "stage7": True,
  }


def checkpoint_args_match(checkpoint: Mapping[str, Any],
                          contract: Mapping[str, Any]) -> bool:
  model_args = checkpoint.get("model_args", {})
  training_args = checkpoint.get("training_args", {})
  for key, expected in contract["model_args"].items():
    _require(model_args.get(key) == expected,
             "Checkpoint model_args.{} mismatch".format(key))
  for key, expected in contract["training_args"].items():
    normalized = "lr" if key == "learning_rate" else key
    _require(training_args.get(key, model_args.get(normalized)) == expected,
             "Checkpoint training_args.{} mismatch".format(key))
  _require(checkpoint.get("seed") == contract["seed"], "Checkpoint seed mismatch")
  _require(checkpoint.get("stage4_training_contract_fingerprint") ==
           fingerprint_value(contract), "Checkpoint contract SHA mismatch")
  return True


class Stage7ModelRanking(shared_stage4.ModelRanking):
  """Legacy ranking implementation with a strict Stage7/R4 checkpoint gate."""

  policy_name = "capd_proactive_stage4_stage7_model"

  def __init__(self, checkpoint_path: str, device: str, trace: Sequence[Any],
               candidate: Mapping[str, Any]):
    from qmap import qmap_eval
    import torch
    checkpoint = torch.load(checkpoint_path, map_location=torch.device("cpu"))
    _require(checkpoint.get("contract_id") == CONTRACT_ID,
             "Replay rejects non-Stage7 checkpoint")
    contract = checkpoint.get("stage4_training_contract")
    _require(isinstance(contract, Mapping), "Checkpoint lacks training contract")
    checkpoint_args_match(checkpoint, contract)
    _require(checkpoint.get("test_trace_opened") is False and
             checkpoint.get("selector_status") == "disabled",
             "Checkpoint provenance is contaminated")
    vocabulary = checkpoint.get("vocab_contract", {})
    _require(vocabulary.get("page_frozen") is True and
             vocabulary.get("pc_frozen") is True,
             "Checkpoint vocabularies are not frozen")
    self.predictor = qmap_eval.QMAPPolicy(
        checkpoint_path=checkpoint_path, device=torch.device(device),
        history_length=int(candidate["history_H"]), candidate_count=8,
        lookahead=int(candidate["lookahead_L"]),
        ablation=candidate["model"]["ablation"])
    self.trace = trace
    self.lookahead = int(candidate["lookahead_L"])
    self.history_H = int(candidate["history_H"])
    self.candidate_K = 8
    self.weights = tuple(float(value) for value in candidate["label_weights"])
    self.metric_rows = []
    self.latencies_seconds = []


def evaluate_checkpoint_windows(
    trace: Sequence[Any], workload: str, checkpoint_path: str, device: str,
    seed: int, candidate: Mapping[str, Any], authority: Mapping[str, Any]
    ) -> Dict[str, Any]:
  method = dict(authority["workloads"][workload])
  method.update({"b_max": 2, "candidate_size_K": 8,
                 "cost_profile": authority["cost_profile"],
                 "capacity_ratio": authority["capacity_ratio"]})
  totals = collections.Counter()
  metric_rows = []
  window_size = int(authority["window_records"])
  ranker = None
  for window_start in range(0, len(trace), window_size):
    window = trace[window_start:window_start + window_size]
    if ranker is None:
      ranker = Stage7ModelRanking(checkpoint_path, device, window, candidate)
    else:
      ranker.trace = window
      ranker.metric_rows = []
      ranker.latencies_seconds = []
    parameters = proactive_replay.ReplayParameters(
        policy_name="capd", dram_capacity_pages=method["D"],
        F_low=method["F_low"], F_target=method["F_target"], b_max=2,
        candidate_size_K=8, history_window_size=candidate["history_H"],
        early_reuse_window=64)
    result = proactive_replay.ProactiveReplay(
        replay_stage0_template(method), parameters, ranking_policy=ranker,
        invariant_mode="boundary", record_details=False).run(
            window, copy_trace=False, compact=True)
    summary = result["summary"]
    for key in ("total_accesses", "dram_hits", "nvm_reads", "nvm_writes",
                "total_demotions", "proactive_demotions",
                "emergency_demotions", "free_frame_exhaustion_count"):
      totals[key] += int(summary[key])
    metric_rows.extend(row for row in ranker.metric_rows
                       if row["complete_future_window"])
  _require(totals["total_accesses"] > 0, "Validation trace is empty")
  _require(metric_rows, "Validation workload has zero valid decisions")
  costs = authority["cost_profile"]
  weighted_cost = (costs["dram_hit"] * totals["dram_hits"] +
                   costs["nvm_read"] * totals["nvm_reads"] +
                   costs["nvm_write"] * totals["nvm_writes"] +
                   costs["demotion"] * totals["total_demotions"])
  return {
      "schema_version": "capd_proactive_stage4_stage7_validation_v1_0",
      "contract_id": CONTRACT_ID, "candidate_id": candidate["candidate_id"],
      "seed": int(seed), "workload": workload, "split_role": "validation",
      "D": method["D"], "F_low": method["F_low"],
      "F_target": method["F_target"], "b_max": 2, "candidate_size_K": 8,
      "checkpoint_path": os.path.abspath(checkpoint_path),
      "checkpoint_sha256": fingerprint_file(checkpoint_path),
      "total_accesses": totals["total_accesses"],
      "weighted_cost": weighted_cost,
      "weighted_cost_per_access": weighted_cost / totals["total_accesses"],
      "ndcg_at_b_t": macro_mean([row["ndcg_at_b_t"] for row in metric_rows
                                  if row["ndcg_at_b_t"] is not None]),
      "top_b_t_overlap": macro_mean([
          row["top_b_t_overlap"] for row in metric_rows
          if row["top_b_t_overlap"] is not None]),
      "valid_decision_count": len(metric_rows),
      "emergency_fallback_count": totals["emergency_demotions"],
      "exhaustion_count": totals["free_frame_exhaustion_count"],
      "test_trace_opened": False, "pressure_trace_opened": False,
  }


def macro_mean(values: Sequence[float]) -> float:
  _require(values and all(math.isfinite(float(value)) for value in values),
           "Macro aggregation requires finite values")
  return statistics.mean(float(value) for value in values)
