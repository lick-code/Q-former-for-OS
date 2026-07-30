# coding=utf-8
"""CAPD proactive Stage-4 data, metric, replay, and selection primitives.

This module is deliberately independent from the historical finals_v3/B=64
Stage-4 implementation.  It consumes only raw Train/Validation traces and the
frozen proactive Stage-0/Stage-3 contracts.
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
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage3
from qmap.qmap_generator import build_candidate_state_features
from qmap.qmap_generator import padded_history


SCHEMA_NAME = "capd_proactive_stage4"
SCHEMA_VERSION = "capd_proactive_stage4_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE4-1.0"
MANIFEST_SCHEMA = "capd_proactive_stage4_input_manifest_v1_0"
SAMPLE_SCHEMA = "capd_proactive_stage4_sample_v1_0"
TRAINING_CONTRACT_SCHEMA = "capd_proactive_stage4_training_contract_v1_0"
METRIC_SCHEMA = "capd_proactive_stage4_metrics_v1_0"
AWAITING_INPUTS = "stage4_implemented_awaiting_training_inputs"
RESULTS_READY = "stage4_results_ready_for_freeze"
VERIFIED = "stage4_verified"
ALLOWED_SPLITS = ("train", "validation")
FORBIDDEN_SPLITS = ("test",)
FROZEN_STAGE3 = {
    "working_set_definition": "active_unique_pages_from_train_and_validation",
    "dram_working_set_ratio": 0.2,
    "F_low": 8,
    "F_target": 16,
    "b_max": 4,
    "candidate_source": "lru_tail",
    "selector": "disabled",
    "trigger_mode": "low_watermark",
    "fallback_policy": "lru",
}
DEFAULT_COST = {
    "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10}
LABEL_WEIGHT_GRID = (
    (1.0, 1.0, 1.0),
    (1.0, 1.0, 2.0),
    (1.0, 1.0, 4.0),
    (1.0, 1.0, 8.0),
    (1.0, 2.0, 4.0),
    (2.0, 1.0, 4.0),
)
SEEDS = (3136859, 42, 2026)
_TEST_TOKEN = re.compile(r"(^|[_.\-])test([_.\-]|$)", re.IGNORECASE)


class Stage4ContractError(ValueError):
  """Raised when Stage-4 input or configuration violates the protocol."""


def _require(condition: bool, message: str) -> None:
  if not condition:
    raise Stage4ContractError(message)


def _reject_json_constant(value: str) -> None:
  raise Stage4ContractError("Non-finite JSON value is forbidden: {}".format(
      value))


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
  result = {}
  for key, value in pairs:
    _require(key not in result, "Duplicate JSON key: {}.".format(key))
    result[key] = value
  return result


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(
        input_file, object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant)


def fingerprint_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as input_file:
    while True:
      block = input_file.read(1024 * 1024)
      if not block:
        break
      digest.update(block)
  return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
  payload = json.dumps(
      value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
      allow_nan=False).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".stage4-", suffix=".tmp", dir=directory)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
      json.dump(
          value, output, ensure_ascii=False, sort_keys=True, indent=2,
          allow_nan=False)
      output.write("\n")
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def write_jsonl_atomic(path: str, rows: Iterable[Mapping[str, Any]]) -> int:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".stage4-", suffix=".jsonl.tmp", dir=directory)
  count = 0
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
      for row in rows:
        output.write(json.dumps(
            row, ensure_ascii=False, sort_keys=True, allow_nan=False))
        output.write("\n")
        count += 1
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
    return count
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def write_text_atomic(path: str, text: str) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".stage4-", suffix=".txt.tmp", dir=directory)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
      output.write(text)
      if not text.endswith("\n"):
        output.write("\n")
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def _positive_integer(value: Any, field: str) -> int:
  _require(
      isinstance(value, int) and not isinstance(value, bool) and value > 0,
      "{} must be a positive integer.".format(field))
  return int(value)


def _finite_number(value: Any, field: str) -> float:
  _require(
      isinstance(value, (int, float)) and not isinstance(value, bool) and
      math.isfinite(float(value)),
      "{} must be finite.".format(field))
  return float(value)


def validate_config(
    value: Mapping[str, Any],
    stage0: Optional[Mapping[str, Any]] = None,
    stage3_default: Optional[Mapping[str, Any]] = None
) -> Mapping[str, Any]:
  """Validates the complete predeclared Stage-4 protocol."""
  required = {
      "schema_name", "schema_version", "contract_id", "stage_status",
      "allowed_splits", "forbidden_splits", "frozen_stage3", "cost_profile",
      "reference", "grid", "seeds", "training", "selection_rule",
      "dataset", "provenance", "output_root"}
  _require(isinstance(value, Mapping), "Stage-4 config must be an object.")
  _require(not (required - set(value)), "Stage-4 config is incomplete.")
  _require(value["schema_name"] == SCHEMA_NAME, "Unexpected schema_name.")
  _require(value["schema_version"] == SCHEMA_VERSION, "Unexpected schema_version.")
  _require(value["contract_id"] == CONTRACT_ID, "Unexpected contract_id.")
  _require(value["stage_status"] == AWAITING_INPUTS,
           "Repository Stage-4 config must remain awaiting real inputs.")
  _require(tuple(value["allowed_splits"]) == ALLOWED_SPLITS,
           "Stage 4 only allows Train/Validation.")
  _require(tuple(value["forbidden_splits"]) == FORBIDDEN_SPLITS,
           "Stage 4 must hard-forbid Test.")
  _require(value["frozen_stage3"] == FROZEN_STAGE3,
           "Stage-3 frozen values were changed.")
  _require(value["cost_profile"] == {
      "name": "default", "status": "stage2_frozen", "weights": DEFAULT_COST},
      "Stage-2 default Cost profile mismatch.")
  reference = value["reference"]
  _require(reference == {
      "lookahead_L": 256,
      "label_weights": [1, 1, 4],
      "candidate_size_K": 8,
      "history_H": 10,
  }, "Unexpected Stage-4 reference configuration.")
  grid = value["grid"]
  _require(grid.get("lookahead_L") == [256, 512, 1024],
           "Lookahead grid must be 256/512/1024.")
  weights = [tuple(float(item) for item in row)
             for row in grid.get("label_weights", [])]
  _require(tuple(weights) == LABEL_WEIGHT_GRID,
           "Label-weight grid does not match the frozen six candidates.")
  _require(grid.get("candidate_size_K") == [8, 16],
           "Formal K grid must be 8/16; K=4 is illegal for b_max=4.")
  _require(grid.get("history_H") == [5, 10, 20],
           "History grid must be 5/10/20 after confirming current H=10.")
  _require(tuple(value["seeds"]) == SEEDS,
           "Stage-4 seeds must be 3136859/42/2026.")
  training = value["training"]
  for field in ("epochs", "batch_size"):
    _positive_integer(training.get(field), "training.{}".format(field))
  _finite_number(training.get("learning_rate"), "training.learning_rate")
  _require(training.get("checkpoint_rule") == "minimum_validation_loss_only",
           "Checkpoint rule must use Validation only.")
  _require(training.get("checkpoint_tie_break") == "earliest_epoch",
           "Checkpoint ties must keep the earliest epoch.")
  _require(training.get("dataset_trajectory_policy") == "proactive_lru",
           "Dataset trajectory policy must be frozen Proactive-LRU.")
  _require(training.get("global_model_across_workloads") is True,
           "Stage 4 requires one global model per seed.")
  _require(training.get("deterministic_algorithms") is True,
           "Stage 4 requires deterministic training algorithms.")
  dataset = value["dataset"]
  _require(dataset.get("page_state_dim") == 4,
           "Stage-4 candidate state must have four dimensions.")
  _require(dataset.get("incomplete_lookahead") ==
           "exclude_from_training_and_report",
           "Incomplete lookahead handling must be predeclared.")
  _positive_integer(dataset.get("early_reuse_window"),
                    "dataset.early_reuse_window")
  selection = value["selection_rule"]
  _require(selection.get("phase_order") == [
      "lookahead_L", "label_weights", "candidate_size_K_and_history_H"],
      "Stage-4 phase order was changed.")
  _finite_number(selection.get("near_best_relative_tolerance"),
                 "selection_rule.near_best_relative_tolerance")
  _finite_number(selection.get("worst_workload_relative_tolerance"),
                 "selection_rule.worst_workload_relative_tolerance")
  _finite_number(selection.get("nvm_write_relative_tolerance"),
                 "selection_rule.nvm_write_relative_tolerance")
  _require(
      selection.get("near_best_relative_tolerance") == 0.01 and
      selection.get("worst_workload_relative_tolerance") == 0.05 and
      selection.get("nvm_write_relative_tolerance") == 0.05,
      "Stage-4 numeric selection tolerances were changed.")
  _require(
      selection.get("primary_metric") ==
      "validation_macro_weighted_cost_per_access",
      "Unexpected Stage-4 primary metric.")
  _require(selection.get("tie_break_order") == [
      "lower_worst_workload_regression",
      "lower_nvm_write_regression",
      "higher_ndcg_at_b_t",
      "higher_top_b_t_overlap",
      "lower_top_b_t_regret",
      "lower_amortized_latency",
      "lower_complexity",
      "lower_macro_weighted_cost_within_near_best_band",
      "lexical_experiment_id",
  ], "Stage-4 tie-break order was changed.")
  _require(selection.get("test_used") is False,
           "Selection rule must explicitly forbid Test.")
  _require(selection.get("global_across_workloads") is True,
           "Per-workload hyperparameter selection is forbidden.")
  provenance = value["provenance"]
  _require(
      provenance.get("candidate_filter") == "disabled" and
      provenance.get("old_finals_v3_artifacts_allowed") is False and
      provenance.get("test_used") is False,
      "Stage-4 provenance boundary is invalid.")
  _require(
      isinstance(value["output_root"], str) and
      "capd_proactive_stage4" in value["output_root"].replace("\\", "/"),
      "Stage-4 output root must carry capd_proactive_stage4 identity.")
  if stage0 is not None:
    finals_config.validate_config(stage0)
    _require(stage0["schema_version"] == finals_config.PROACTIVE_SCHEMA_VERSION,
             "Stage 4 requires the proactive Stage-0 contract.")
    _require(stage0["method"]["selector"] == "disabled",
             "Candidate selector cannot be re-enabled.")
    for key, expected in (
        ("dram_working_set_ratio", 0.2),
        ("working_set_definition",
         "active_unique_pages_from_train_and_validation")):
      _require(stage0["memory"][key] == expected,
               "Stage-0 {} mismatch.".format(key))
    for key in ("F_low", "F_target", "b_max"):
      _require(stage0["active_demotion"][key] == FROZEN_STAGE3[key],
               "Stage-0 {} mismatch.".format(key))
    _require(stage0["freeze_status"]["stage3_active_mechanism"] == "frozen",
             "Stage 3 is not frozen in the main proactive config.")
    _require(stage0["freeze_status"]["stage4_candidate"] == "pending" and
             stage0["freeze_status"]["stage4_training"] == "pending",
             "Stage-4 gates must be pending before real execution.")
  if stage3_default is not None:
    _require(stage3_default.get("selected") == {
        "working_set_definition": FROZEN_STAGE3["working_set_definition"],
        "dram_working_set_ratio": 0.2,
        "F_low": 8, "F_target": 16, "b_max": 4,
        "candidate_size_K": None,
    }, "Stage-3 engineering-default inheritance mismatch.")
    _require(stage3_default.get("formal_capacity_gate_passed") is False,
             "Stage 4 must preserve the failed capacity-gate boundary.")
    _require(stage3_default.get("decision_status") ==
             "user_accepted_conditional_engineering_default",
             "Stage-3 decision status mismatch.")
  return value


def validate_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
  required = {
      "schema_version", "contract_id", "path_base", "entries",
      "test_used_for_parameter_selection", "split_non_overlap_attested"}
  _require(isinstance(value, Mapping), "Input manifest must be an object.")
  _require(not (required - set(value)), "Input manifest is incomplete.")
  _require(value["schema_version"] == MANIFEST_SCHEMA,
           "Unexpected Stage-4 manifest schema.")
  _require(value["contract_id"] == CONTRACT_ID,
           "Manifest contract_id mismatch.")
  _require(value["path_base"] in ("project_root", "manifest_directory"),
           "Unsupported manifest path_base.")
  _require(value["test_used_for_parameter_selection"] is False,
           "Test cannot be used for Stage-4 parameter selection.")
  _require(value["split_non_overlap_attested"] is True,
           "Train/Validation non-overlap must be explicitly attested.")
  entries = value["entries"]
  _require(isinstance(entries, list) and entries,
           "Manifest entries cannot be empty.")
  seen = set()
  splits_by_workload = collections.defaultdict(set)
  for index, entry in enumerate(entries):
    context = "entries[{}]".format(index)
    required_entry = {
        "workload", "split", "role", "trace_path", "trace_sha256",
        "page_shift", "source_kind", "formal_test", "source_trace_id",
        "source_interval"}
    _require(isinstance(entry, Mapping) and
             not (required_entry - set(entry)),
             "{} is incomplete.".format(context))
    split = entry["split"]
    _require(split in ALLOWED_SPLITS,
             "{} split must be Train/Validation.".format(context))
    expected_role = (
        "training_and_fit" if split == "train" else "parameter_selection")
    _require(entry["role"] == expected_role,
             "{} split/role mismatch.".format(context))
    _require(entry["formal_test"] is False,
             "{} cannot be formal Test.".format(context))
    _require(entry["source_kind"] == "raw_access_trace",
             "{} must be a raw trace.".format(context))
    _require(
        isinstance(entry["trace_path"], str) and entry["trace_path"] and
        not _TEST_TOKEN.search(os.path.basename(entry["trace_path"])),
        "{} trace_path looks like a Test artifact.".format(context))
    digest = entry["trace_sha256"]
    _require(
        isinstance(digest, str) and len(digest) == 64 and
        all(character in "0123456789abcdef" for character in digest),
        "{} trace_sha256 is invalid.".format(context))
    _require(isinstance(entry["source_trace_id"], str) and
             entry["source_trace_id"],
             "{} source_trace_id is required.".format(context))
    interval = entry["source_interval"]
    _require(isinstance(interval, Mapping) and
             set(interval) == {"start", "end"},
             "{} source_interval must be a half-open range.".format(context))
    start = interval["start"]
    end = interval["end"]
    _require(
        isinstance(start, int) and isinstance(end, int) and
        not isinstance(start, bool) and not isinstance(end, bool) and
        0 <= start < end,
        "{} source_interval must satisfy 0 <= start < end.".format(context))
    _require(entry["page_shift"] == 12,
             "{} must use 4 KiB pages.".format(context))
    identity = (entry["workload"], split)
    _require(identity not in seen,
             "Duplicate workload/split: {}.".format(identity))
    seen.add(identity)
    splits_by_workload[entry["workload"]].add(split)
  for workload, splits in splits_by_workload.items():
    _require(splits == set(ALLOWED_SPLITS),
             "{} must have Train and Validation.".format(workload))
    pair = [entry for entry in entries if entry["workload"] == workload]
    train = next(entry for entry in pair if entry["split"] == "train")
    valid = next(entry for entry in pair if entry["split"] == "validation")
    if train["source_trace_id"] == valid["source_trace_id"]:
      left = train["source_interval"]
      right = valid["source_interval"]
      _require(
          left["end"] <= right["start"] or right["end"] <= left["start"],
          "{} Train/Validation source intervals overlap.".format(workload))
  return value


def resolve_inputs(
    manifest_path: str, project_root: str
) -> Tuple[Mapping[str, Any], Dict[str, Dict[str, Sequence[Any]]],
           List[Dict[str, Any]]]:
  """Loads and fingerprints strict Train/Validation inputs."""
  manifest = validate_manifest(load_json(manifest_path))
  base = (
      os.path.dirname(os.path.abspath(manifest_path))
      if manifest["path_base"] == "manifest_directory"
      else os.path.abspath(project_root))
  traces = collections.defaultdict(dict)
  resolved = []
  seen_hashes = set()
  seen_paths = set()
  for entry in manifest["entries"]:
    path = os.path.abspath(os.path.join(base, entry["trace_path"]))
    _require(os.path.isfile(path), "Trace does not exist: {}".format(path))
    _require(path not in seen_paths,
             "Train/Validation cannot reuse the same resolved path.")
    seen_paths.add(path)
    digest = fingerprint_file(path)
    _require(digest == entry["trace_sha256"],
             "Trace SHA-256 mismatch: {}".format(path))
    _require(digest not in seen_hashes,
             "Train/Validation trace contents must all be distinct.")
    seen_hashes.add(digest)
    trace, rw_source = proactive_stage3._read_compact_trace(
        path, entry["page_shift"])
    _require(len(trace) > 0, "Empty trace is forbidden: {}".format(path))
    interval = entry["source_interval"]
    _require(
        interval["end"] - interval["start"] == len(trace),
        "{} source_interval length does not match parsed accesses.".format(
            entry["workload"]))
    traces[entry["workload"]][entry["split"]] = trace
    item = copy.deepcopy(entry)
    item.update({
        "resolved_trace_path": path,
        "trace_accesses": len(trace),
        "rw_source": rw_source,
    })
    resolved.append(item)
  return manifest, dict(traces), resolved


def working_set_and_capacity(
    traces: Mapping[str, Mapping[str, Sequence[Any]]]
) -> Dict[str, Dict[str, int]]:
  result = {}
  for workload in sorted(traces):
    train_pages = set(access["page"] for access in traces[workload]["train"])
    valid_pages = set(
        access["page"] for access in traces[workload]["validation"])
    union = train_pages | valid_pages
    capacity = proactive_stage3.capacity_pages(len(union), 0.2)
    _require(capacity["dram_capacity_pages"] >= FROZEN_STAGE3["F_target"],
             "{} DRAM capacity is below F_target.".format(workload))
    result[workload] = {
        "train_unique_pages": len(train_pages),
        "validation_unique_pages": len(valid_pages),
        "union_working_set_pages": len(union),
        "dram_capacity_pages": capacity["dram_capacity_pages"],
    }
  return result


def label_components(
    trace: Sequence[Any], decision_index: int, candidate: int, lookahead: int
) -> Dict[str, Any]:
  """Returns normalized future labels and explicit tail-window status."""
  _positive_integer(lookahead, "lookahead")
  _require(0 <= decision_index < len(trace), "decision_index out of range.")
  end = min(len(trace), decision_index + 1 + lookahead)
  effective = max(0, end - decision_index - 1)
  complete = effective == lookahead
  next_distance = None
  frequency = 0
  writes = 0
  for future_index in range(decision_index + 1, end):
    access = trace[future_index]
    if access["page"] == candidate:
      frequency += 1
      writes += int(access["rw"])
      if next_distance is None:
        next_distance = future_index - decision_index
  denominator = float(max(1, effective))
  inactivity = (
      1.0 if next_distance is None
      else min(next_distance, max(1, effective)) / denominator)
  return {
      "d_hat": inactivity,
      "q_hat": 1.0 - min(frequency / denominator, 1.0),
      "w_hat": min(writes / denominator, 1.0),
      "next_reuse_distance": next_distance,
      "future_access_count": frequency,
      "future_write_count": writes,
      "effective_lookahead": effective,
      "complete_future_window": complete,
      "no_future_reuse": next_distance is None,
  }


def composite_label(components: Mapping[str, Any],
                    weights: Sequence[float]) -> float:
  _require(len(weights) == 3, "Label weights must have three values.")
  lambda_1, lambda_2, lambda_3 = (
      _finite_number(value, "label weight") for value in weights)
  return (
      lambda_1 * float(components["d_hat"]) +
      lambda_2 * float(components["q_hat"]) -
      lambda_3 * float(components["w_hat"]))


def _padded_history_rows(history: Sequence[Mapping[str, Any]], H: int
                        ) -> Tuple[List[int], List[int], List[int], List[int]]:
  recent = list(history)[-H:]
  pages, pcs, rws = padded_history(recent, H)
  mask = [0] * (H - len(recent)) + [1] * len(recent)
  return pages, pcs, rws, mask


class TrainingSampleRanking(proactive_replay.CandidateRankingPolicy):
  """Captures active-round samples while LRU deterministically drives state."""

  policy_name = "stage4_training_proactive_lru"

  def __init__(
      self, trace: Sequence[Any], workload: str, split: str, lookahead: int,
      history_H: int, candidate_K: int, weights: Sequence[float],
      experiment_id: str):
    self.trace = trace
    self.workload = workload
    self.split = split
    self.lookahead = lookahead
    self.history_H = history_H
    self.candidate_K = candidate_K
    self.weights = tuple(float(value) for value in weights)
    self.experiment_id = experiment_id
    self.rows = []
    self.tail_excluded = 0
    self.empty_future_windows = 0
    self.total_rounds_seen = 0

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del candidate_features
    self.total_rounds_seen += 1
    components = [
        label_components(
            self.trace, state.access_index, page, self.lookahead)
        for page in candidates]
    complete = all(item["complete_future_window"] for item in components)
    if not complete:
      self.tail_excluded += 1
      if components and all(item["effective_lookahead"] == 0
                            for item in components):
        self.empty_future_windows += 1
    elif candidates:
      history_pages, pcs, rws, history_mask = _padded_history_rows(
          state.history_window, self.history_H)
      numeric_features = []
      for rank, page in enumerate(candidates):
        numeric_features.append(build_candidate_state_features(
            page, list(state.history_window)[-self.history_H:],
            state.access_index - state.dram_entry_index.get(
                page, state.access_index),
            bool(state.dirty_state.get(page, False)), self.lookahead,
            rank=rank, candidate_count=self.candidate_K))
      padding = self.candidate_K - len(candidates)
      _require(padding >= 0, "Actual candidate count exceeds K.")
      padded_components = components + [{
          "d_hat": 0.0, "q_hat": 0.0, "w_hat": 0.0,
          "next_reuse_distance": None, "future_access_count": 0,
          "future_write_count": 0, "effective_lookahead": self.lookahead,
          "complete_future_window": True, "no_future_reuse": True,
      } for _ in range(padding)]
      labels = [
          composite_label(item, self.weights) if index < len(candidates)
          else 0.0
          for index, item in enumerate(padded_components)]
      b_t = min(
          state.parameters.b_max,
          state.parameters.F_target - state.free_frames,
          len(candidates))
      self.rows.append({
          "schema_version": SAMPLE_SCHEMA,
          "contract_id": CONTRACT_ID,
          "experiment_id": self.experiment_id,
          "workload_id": self.workload,
          "split": self.split,
          "decision_index": state.access_index,
          "cycle_id": policy_context["cycle_id"],
          "cycle_round_index": policy_context["cycle_round_index"],
          "F_t": state.free_frames,
          "F_low": state.parameters.F_low,
          "F_target": state.parameters.F_target,
          "b_t": b_t,
          "history_page_ids": history_pages,
          "history_mask": history_mask,
          "pc": pcs,
          "rw": rws,
          "candidate_pages": list(candidates) + [0] * padding,
          "candidate_state_features": numeric_features + [[0.0] * 4
                                                          for _ in range(padding)],
          "candidate_mask": [1] * len(candidates) + [0] * padding,
          "original_pool_ranks": list(range(len(candidates))) +
                                 [-1] * padding,
          "inactivity": [item["d_hat"] for item in padded_components],
          "coldness": [item["q_hat"] for item in padded_components],
          "write_sensitivity": [
              item["w_hat"] for item in padded_components],
          "migration_cost": [0.0] * self.candidate_K,
          "ranking_label": labels,
          "label_components": padded_components,
          "label_weights": list(self.weights),
          "lookahead_L": self.lookahead,
          "history_H": self.history_H,
          "candidate_size_K": self.candidate_K,
          "complete_future_window": True,
          "trajectory_policy": "proactive_lru",
          "selector_status": "disabled",
          "formal_test": False,
      })
    count = len(candidates)
    return [
        {"page": page, "score": float(count - index)}
        for index, page in enumerate(candidates)]


def experiment_id(L: int, weights: Sequence[float], K: int, H: int) -> str:
  numbers = "-".join(str(int(value)) for value in weights)
  return "L{}_lam{}_K{}_H{}".format(L, numbers, K, H)


def generate_samples(
    stage0: Mapping[str, Any], trace: Sequence[Any], workload: str, split: str,
    dram_capacity_pages: int, L: int, weights: Sequence[float], K: int, H: int
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
  _require(K > FROZEN_STAGE3["b_max"], "Stage 4 requires K > b_max.")
  identity = experiment_id(L, weights, K, H)
  ranker = TrainingSampleRanking(
      trace, workload, split, L, H, K, weights, identity)
  parameters = proactive_replay.ReplayParameters(
      policy_name="capd",
      dram_capacity_pages=dram_capacity_pages,
      F_low=FROZEN_STAGE3["F_low"],
      F_target=FROZEN_STAGE3["F_target"],
      b_max=FROZEN_STAGE3["b_max"],
      candidate_size_K=K,
      history_window_size=H,
      early_reuse_window=64)
  replay = proactive_replay.ProactiveReplay(
      stage0, parameters, ranking_policy=ranker, invariant_mode="boundary",
      record_details=False)
  compact = replay.run(trace, copy_trace=False, compact=True)
  diagnostics = label_diagnostics(ranker.rows)
  diagnostics.update({
      "workload": workload,
      "split": split,
      "experiment_id": identity,
      "active_rounds_seen": ranker.total_rounds_seen,
      "training_samples": len(ranker.rows),
      "incomplete_tail_rounds_excluded": ranker.tail_excluded,
      "empty_future_window_rounds_excluded": ranker.empty_future_windows,
      "future_window_coverage": (
          len(ranker.rows) / float(ranker.total_rounds_seen)
          if ranker.total_rounds_seen else None),
  })
  return ranker.rows, diagnostics, compact["summary"]


def label_diagnostics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  labels = []
  no_reuse = 0
  candidate_count = 0
  tie_rows = 0
  oracle_sizes = []
  for row in rows:
    valid = [
        float(label) for label, mask in zip(
            row["ranking_label"], row["candidate_mask"]) if mask]
    if not valid:
      continue
    labels.extend(valid)
    candidate_count += len(valid)
    maximum = max(valid)
    oracle_size = sum(value == maximum for value in valid)
    oracle_sizes.append(oracle_size)
    if len(set(valid)) < len(valid):
      tie_rows += 1
    no_reuse += sum(
        bool(item["no_future_reuse"]) for item, mask in zip(
            row["label_components"], row["candidate_mask"]) if mask)
  return {
      "label_count": len(labels),
      "label_variance": (
          statistics.pvariance(labels) if len(labels) >= 2 else
          0.0 if labels else None),
      "decision_count": len(rows),
      "tied_label_decision_ratio": (
          tie_rows / float(len(rows)) if rows else None),
      "mean_oracle_set_size": (
          statistics.mean(oracle_sizes) if oracle_sizes else None),
      "no_future_reuse_ratio": (
          no_reuse / float(candidate_count) if candidate_count else None),
  }


def relabel_sample(row: Mapping[str, Any],
                   weights: Sequence[float]) -> Dict[str, Any]:
  result = copy.deepcopy(row)
  result["label_weights"] = [float(value) for value in weights]
  result["ranking_label"] = [
      composite_label(item, weights) if mask else 0.0
      for item, mask in zip(
          result["label_components"], result["candidate_mask"])]
  return result


def _discounted_gain(relevance: Sequence[float],
                     order: Sequence[int], cutoff: int) -> float:
  return sum(
      relevance[index] / math.log2(position + 2)
      for position, index in enumerate(order[:cutoff]))


def variable_top_b_metrics(
    scores: Sequence[float], labels: Sequence[float], b_t: int,
    original_ranks: Optional[Sequence[int]] = None
) -> Dict[str, Any]:
  """Computes deterministic variable-Top-b metrics with explicit tie status."""
  _require(len(scores) == len(labels) and len(scores) > 0,
           "Ranking metrics require aligned non-empty values.")
  _require(all(
      math.isfinite(float(value))
      for value in list(scores) + list(labels)),
           "Ranking metrics reject NaN/Inf.")
  b = min(_positive_integer(b_t, "b_t"), len(scores))
  ranks = list(original_ranks or range(len(scores)))
  _require(len(ranks) == len(scores), "original_ranks length mismatch.")
  predicted = sorted(
      range(len(scores)), key=lambda index: (
          -float(scores[index]), ranks[index], index))
  oracle = sorted(
      range(len(labels)), key=lambda index: (
          -float(labels[index]), ranks[index], index))
  minimum = min(float(value) for value in labels)
  relevance = [float(value) - minimum for value in labels]
  all_tied = max(labels) == min(labels)
  ideal_dcg_1 = _discounted_gain(relevance, oracle, 1)
  ideal_dcg_b = _discounted_gain(relevance, oracle, b)
  ndcg_1 = (
      1.0 if ideal_dcg_1 == 0.0
      else _discounted_gain(relevance, predicted, 1) / ideal_dcg_1)
  ndcg_b = (
      1.0 if ideal_dcg_b == 0.0
      else _discounted_gain(relevance, predicted, b) / ideal_dcg_b)
  boundary = float(labels[oracle[b - 1]])
  oracle_admissible = {
      index for index, value in enumerate(labels)
      if float(value) >= boundary}
  predicted_top = set(predicted[:b])
  overlap = len(predicted_top & oracle_admissible) / float(b)
  regret = (
      sum(float(labels[index]) for index in oracle[:b]) -
      sum(float(labels[index]) for index in predicted[:b]))
  return {
      "effective_b_t": b,
      "ndcg_at_1": ndcg_1,
      "ndcg_at_b_t": ndcg_b,
      "top_b_t_overlap": overlap,
      "top_b_t_regret": max(0.0, regret),
      "oracle_set_size": len(oracle_admissible),
      "all_labels_tied": all_tied,
      "ndcg_status": (
          "indistinguishable_all_labels_tied" if all_tied else "defined"),
  }


class ModelRanking(proactive_replay.CandidateRankingPolicy):
  """Ranks active LRU-tail candidates with a trained QMAP checkpoint."""

  policy_name = "capd_proactive_stage4_model"

  def __init__(
      self, checkpoint_path: str, device: str, trace: Sequence[Any],
      lookahead: int, history_H: int, candidate_K: int,
      weights: Sequence[float]):
    from qmap import qmap_eval  # Lazy: pure-data commands do not need torch.
    import torch
    checkpoint = torch.load(
        checkpoint_path, map_location=torch.device("cpu"))
    _require(checkpoint.get("contract_id") == CONTRACT_ID,
             "Stage-4 replay rejects a historical/non-proactive checkpoint.")
    training_contract = checkpoint.get("stage4_training_contract")
    _require(isinstance(training_contract, Mapping),
             "Checkpoint lacks its Stage-4 training contract.")
    _require(
        checkpoint.get("stage4_training_contract_fingerprint") ==
        fingerprint_value(training_contract),
        "Checkpoint training-contract fingerprint mismatch.")
    expected_experiment = experiment_id(
        lookahead, weights, candidate_K, history_H)
    _require(checkpoint.get("experiment_id") == expected_experiment,
             "Checkpoint Stage-4 experiment identity mismatch.")
    _require(training_contract.get("expected_shape") == {
        "H": history_H, "K": candidate_K, "page_state_dim": 4},
        "Checkpoint H/K/state shape mismatch.")
    _require(training_contract.get("labels") == {
        "lambda_1": weights[0], "lambda_2": weights[1],
        "lambda_3": weights[2]},
        "Checkpoint label-weight identity mismatch.")
    _require(
        checkpoint.get("test_trace_opened") is False and
        checkpoint.get("selector_status") == "disabled",
        "Checkpoint provenance is contaminated.")
    vocab = checkpoint.get("vocab_contract", {})
    _require(vocab.get("page_frozen") is True and
             vocab.get("pc_frozen") is True,
             "Stage-4 checkpoint vocabularies must be Train-fitted/frozen.")
    del checkpoint
    self.predictor = qmap_eval.QMAPPolicy(
        checkpoint_path=checkpoint_path, device=torch.device(device),
        history_length=history_H, candidate_count=candidate_K,
        lookahead=lookahead, ablation="cross_attention")
    self.trace = trace
    self.lookahead = lookahead
    self.history_H = history_H
    self.candidate_K = candidate_K
    self.weights = tuple(float(value) for value in weights)
    self.metric_rows = []
    self.latencies_seconds = []

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del candidate_features
    if not candidates:
      return []
    self.predictor.synchronize()
    started = time.perf_counter()
    scores = self.predictor.score_explicit_candidates(
        candidates=candidates,
        history=list(state.history_window),
        access_index=state.access_index,
        dram_insert_time=state.dram_entry_index,
        dirty_pages={
            page for page, dirty in state.dirty_state.items() if dirty})
    self.predictor.synchronize()
    latency = time.perf_counter() - started
    self.latencies_seconds.append(latency)
    components = [
        label_components(self.trace, state.access_index, page, self.lookahead)
        for page in candidates]
    labels = [composite_label(item, self.weights) for item in components]
    b_t = min(
        state.parameters.b_max,
        state.parameters.F_target - state.free_frames,
        len(candidates))
    metric = variable_top_b_metrics(
        scores, labels, b_t, list(range(len(candidates))))
    metric.update({
        "access_index": state.access_index,
        "cycle_id": policy_context["cycle_id"],
        "cycle_round_index": policy_context["cycle_round_index"],
        "candidate_count": len(candidates),
        "b_t": b_t,
        "decision_latency_seconds": latency,
        "amortized_latency_per_page_seconds": (
            latency / float(b_t) if b_t else None),
        "complete_future_window": all(
            item["complete_future_window"] for item in components),
        "empty_future_window": all(
            item["effective_lookahead"] == 0 for item in components),
    })
    self.metric_rows.append(metric)
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-float(scores[item[0]]), item[0], item[1]))
    return [
        {"page": page, "score": float(scores[index])}
        for index, page in ranked]


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
  filtered = [float(value) for value in values if value is not None]
  return statistics.mean(filtered) if filtered else None


def _sample_std(values: Iterable[Optional[float]]) -> Optional[float]:
  filtered = [float(value) for value in values if value is not None]
  if not filtered:
    return None
  return statistics.stdev(filtered) if len(filtered) >= 2 else 0.0


def _quantile(values: Sequence[float], probability: float) -> Optional[float]:
  if not values:
    return None
  ordered = sorted(float(value) for value in values)
  position = (len(ordered) - 1) * probability
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  if lower == upper:
    return ordered[lower]
  fraction = position - lower
  return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def evaluate_checkpoint(
    stage0: Mapping[str, Any], trace: Sequence[Any], workload: str,
    dram_capacity_pages: int, checkpoint_path: str, device: str, seed: int,
    L: int, weights: Sequence[float], K: int, H: int
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  ranker = ModelRanking(
      checkpoint_path, device, trace, L, H, K, weights)
  parameters = proactive_replay.ReplayParameters(
      policy_name="capd", dram_capacity_pages=dram_capacity_pages,
      F_low=8, F_target=16, b_max=4, candidate_size_K=K,
      history_window_size=H, early_reuse_window=64)
  result = proactive_replay.ProactiveReplay(
      stage0, parameters, ranking_policy=ranker, invariant_mode="boundary",
      record_details=False).run(trace, copy_trace=False, compact=True)
  summary = result["summary"]
  total_accesses = int(summary["total_accesses"])
  weighted_cost = (
      DEFAULT_COST["dram_hit"] * int(summary["dram_hits"]) +
      DEFAULT_COST["nvm_read"] * int(summary["nvm_reads"]) +
      DEFAULT_COST["nvm_write"] * int(summary["nvm_writes"]) +
      DEFAULT_COST["demotion"] * int(summary["total_demotions"]))
  complete_metrics = [
      row for row in ranker.metric_rows if row["complete_future_window"]]
  latencies = list(ranker.latencies_seconds)
  demotions = int(summary["proactive_demotions"])
  row = {
      "schema_version": METRIC_SCHEMA,
      "contract_id": CONTRACT_ID,
      "experiment_id": experiment_id(L, weights, K, H),
      "workload": workload,
      "split": "validation",
      "seed": int(seed),
      "lookahead_L": L,
      "label_weights": list(weights),
      "candidate_size_K": K,
      "history_H": H,
      "checkpoint_path": os.path.abspath(checkpoint_path),
      "checkpoint_sha256": fingerprint_file(checkpoint_path),
      "total_accesses": total_accesses,
      "weighted_cost": weighted_cost,
      "weighted_cost_per_access": (
          weighted_cost / float(total_accesses) if total_accesses else None),
      "dram_hits": int(summary["dram_hits"]),
      "nvm_reads": int(summary["nvm_reads"]),
      "nvm_writes": int(summary["nvm_writes"]),
      "total_demotions": int(summary["total_demotions"]),
      "proactive_demotions": demotions,
      "emergency_fallback_count": int(summary["emergency_demotions"]),
      "emergency_fallback_rate": (
          int(summary["emergency_demotions"]) / float(total_accesses)
          if total_accesses else None),
      "exhaustion_count": int(summary["free_frame_exhaustion_count"]),
      "exhaustion_rate": (
          int(summary["free_frame_exhaustion_count"]) / float(total_accesses)
          if total_accesses else None),
      "early_reuse_count": int(summary["early_reuse_count"]),
      "early_reuse_rate": (
          int(summary["early_reuse_count"]) / float(demotions)
          if demotions else None),
      "proactive_cycle_count": int(
          summary["number_of_proactive_cycles"]),
      "proactive_round_count": int(
          summary["number_of_proactive_rounds"]),
      "ndcg_at_1": _mean(row["ndcg_at_1"] for row in complete_metrics),
      "ndcg_at_b_t": _mean(
          row["ndcg_at_b_t"] for row in complete_metrics),
      "top_b_t_overlap": _mean(
          row["top_b_t_overlap"] for row in complete_metrics),
      "top_b_t_regret": _mean(
          row["top_b_t_regret"] for row in complete_metrics),
      "ranking_metric_rounds": len(complete_metrics),
      "incomplete_future_metric_rounds": (
          len(ranker.metric_rows) - len(complete_metrics)),
      "all_tied_rounds": sum(
          bool(row["all_labels_tied"]) for row in complete_metrics),
      "decision_latency_seconds": {
          "count": len(latencies),
          "mean": _mean(latencies),
          "p50": _quantile(latencies, 0.50),
          "p95": _quantile(latencies, 0.95),
          "p99": _quantile(latencies, 0.99),
      },
      "amortized_latency_per_page_seconds": _mean(
          row["amortized_latency_per_page_seconds"]
          for row in ranker.metric_rows),
      "selector_status": "disabled",
      "test_trace_opened": False,
  }
  return row, ranker.metric_rows


def aggregate_metric_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  _require(rows, "Cannot aggregate empty metrics.")
  metric_names = (
      "weighted_cost_per_access", "dram_hits", "nvm_reads", "nvm_writes",
      "total_demotions", "proactive_demotions", "emergency_fallback_rate",
      "exhaustion_rate", "early_reuse_rate", "proactive_cycle_count",
      "proactive_round_count", "ndcg_at_1", "ndcg_at_b_t",
      "top_b_t_overlap", "top_b_t_regret",
      "amortized_latency_per_page_seconds")
  by_workload = {}
  for workload in sorted(set(row["workload"] for row in rows)):
    workload_rows = [row for row in rows if row["workload"] == workload]
    summary = {}
    for metric in metric_names:
      values = [
          float(row[metric]) for row in workload_rows
          if row.get(metric) is not None]
      mean = _mean(values)
      std = _sample_std(values)
      critical = {
          2: 12.706, 3: 4.303, 6: 2.571, 9: 2.306}.get(len(values))
      half_width = (
          critical * std / math.sqrt(len(values))
          if critical is not None and std is not None else None)
      summary[metric] = {
          "count": len(values), "mean": mean, "sample_std": std,
          "ci95_t": (
              [mean - half_width, mean + half_width]
              if half_width is not None else None),
      }
    by_workload[workload] = summary
  macro = {
      metric: _mean(
          by_workload[workload][metric]["mean"] for workload in by_workload)
      for metric in metric_names}
  return {
      "schema_version": METRIC_SCHEMA,
      "row_count": len(rows),
      "seed_count": len(set(int(row["seed"]) for row in rows)),
      "workload_count": len(by_workload),
      "by_workload": by_workload,
      "macro_average": macro,
      "uncertainty_note":
          "Three seeds describe stability; t intervals are descriptive, not "
          "strong significance claims.",
  }


def paired_differences(
    candidate_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    metric: str
) -> Dict[str, Any]:
  reference = {
      (row["workload"], int(row["seed"])): row for row in reference_rows}
  differences = []
  for row in candidate_rows:
    key = (row["workload"], int(row["seed"]))
    if key in reference and row.get(metric) is not None and (
        reference[key].get(metric) is not None):
      differences.append(float(row[metric]) - float(reference[key][metric]))
  mean = _mean(differences)
  std = _sample_std(differences)
  critical = {
      2: 12.706, 3: 4.303, 6: 2.571, 9: 2.306}.get(
          len(differences))
  half_width = (
      critical * std / math.sqrt(len(differences))
      if critical is not None and std is not None else None)
  return {
      "metric": metric,
      "count": len(differences),
      "mean": mean,
      "sample_std": std,
      "ci95_t": (
          [mean - half_width, mean + half_width]
          if half_width is not None else None),
      "values": differences,
  }


def select_global_candidate(
    candidates: Sequence[Mapping[str, Any]],
    reference_id: str, selection_rule: Mapping[str, Any]
) -> Dict[str, Any]:
  """Applies the predeclared global deterministic selection rule."""
  _require(candidates, "No Stage-4 candidate results.")
  identities = [item["experiment_id"] for item in candidates]
  _require(len(identities) == len(set(identities)),
           "Duplicate experiment result.")
  reference = next(
      (item for item in candidates if item["experiment_id"] == reference_id),
      None)
  _require(reference is not None, "Phase reference result is missing.")
  primary_values = [
      float(item["aggregate"]["macro_average"][
          "weighted_cost_per_access"])
      for item in candidates]
  minimum = min(primary_values)
  near_tolerance = float(
      selection_rule["near_best_relative_tolerance"])
  worst_tolerance = float(
      selection_rule["worst_workload_relative_tolerance"])
  write_tolerance = float(
      selection_rule["nvm_write_relative_tolerance"])
  evaluated = []
  reference_workloads = reference["aggregate"]["by_workload"]
  for item, primary in zip(candidates, primary_values):
    near_best = primary <= minimum * (1.0 + near_tolerance)
    worst_regression = 0.0
    write_regression = 0.0
    for workload, metrics in item["aggregate"]["by_workload"].items():
      current_cost = metrics["weighted_cost_per_access"]["mean"]
      reference_cost = reference_workloads[
          workload]["weighted_cost_per_access"]["mean"]
      current_write = metrics["nvm_writes"]["mean"]
      reference_write = reference_workloads[workload]["nvm_writes"]["mean"]
      if reference_cost:
        worst_regression = max(
            worst_regression,
            (current_cost - reference_cost) / float(reference_cost))
      if reference_write:
        write_regression = max(
            write_regression,
            (current_write - reference_write) / float(reference_write))
      elif current_write:
        # Keep the decision file strict-JSON serializable while still making
        # a zero-to-positive NVM-write regression fail any practical bound.
        write_regression = 1.0e300
    constraints_pass = (
        worst_regression <= worst_tolerance and
        write_regression <= write_tolerance)
    evaluated.append({
        "experiment_id": item["experiment_id"],
        "near_best": near_best,
        "constraints_pass": constraints_pass,
        "macro_weighted_cost_per_access": primary,
        "worst_workload_relative_regression": worst_regression,
        "worst_nvm_write_relative_regression": write_regression,
        "macro_ndcg_at_b_t":
            item["aggregate"]["macro_average"]["ndcg_at_b_t"],
        "macro_top_b_t_overlap":
            item["aggregate"]["macro_average"]["top_b_t_overlap"],
        "macro_top_b_t_regret":
            item["aggregate"]["macro_average"]["top_b_t_regret"],
        "macro_amortized_latency":
            item["aggregate"]["macro_average"][
                "amortized_latency_per_page_seconds"],
        "complexity_rank": item["complexity_rank"],
    })
  eligible = [
      item for item in evaluated
      if item["near_best"] and item["constraints_pass"]]
  fallback_used = False
  if not eligible:
    fallback_used = True
    eligible = [item for item in evaluated if item["near_best"]]
  def key(item):
    return (
        item["worst_workload_relative_regression"],
        item["worst_nvm_write_relative_regression"],
        -(item["macro_ndcg_at_b_t"] or 0.0),
        -(item["macro_top_b_t_overlap"] or 0.0),
        item["macro_top_b_t_regret"] or 0.0,
        item["macro_amortized_latency"] or float("inf"),
        item["complexity_rank"],
        item["macro_weighted_cost_per_access"],
        item["experiment_id"],
    )
  selected = min(eligible, key=key)
  return {
      "selected_experiment_id": selected["experiment_id"],
      "fallback_used": fallback_used,
      "selection_scope": "global_across_all_validation_workloads_and_seeds",
      "test_used": False,
      "rule_fingerprint": fingerprint_value(selection_rule),
      "evaluated": sorted(evaluated, key=lambda item: item["experiment_id"]),
  }


def validate_training_contract(
    value: Mapping[str, Any], train_path: str, valid_path: str,
    explicit_seed: Optional[int] = None
) -> Dict[str, Any]:
  """Validates the contract consumed by qmap_train."""
  required = {
      "schema_version", "contract_id", "experiment_id", "seed",
      "expected_shape", "sample_identity", "labels", "training", "data",
      "method", "test_trace_opened"}
  _require(isinstance(value, Mapping) and not (required - set(value)),
           "Stage-4 training contract is incomplete.")
  _require(value["schema_version"] == TRAINING_CONTRACT_SCHEMA,
           "Training contract schema mismatch.")
  _require(value["contract_id"] == CONTRACT_ID,
           "Training contract ID mismatch.")
  _require(value["test_trace_opened"] is False,
           "Training contract cannot include Test.")
  shape = value["expected_shape"]
  H = _positive_integer(shape.get("H"), "expected_shape.H")
  K = _positive_integer(shape.get("K"), "expected_shape.K")
  _require(K > FROZEN_STAGE3["b_max"], "Training requires K > b_max.")
  _require(shape.get("page_state_dim") == 4,
           "Training page_state_dim must be four.")
  identity = value["sample_identity"]
  _require(identity == {
      "schema_version": SAMPLE_SCHEMA,
      "contract_id": CONTRACT_ID,
      "experiment_id": value["experiment_id"],
  }, "Training sample identity mismatch.")
  labels = value["labels"]
  weights = [
      _finite_number(labels.get(key), "labels.{}".format(key))
      for key in ("lambda_1", "lambda_2", "lambda_3")]
  training = value["training"]
  for field in ("epochs", "batch_size"):
    _positive_integer(training.get(field), "training.{}".format(field))
  _finite_number(training.get("learning_rate"), "training.learning_rate")
  _require(training.get("checkpoint_tie_break") == "earliest_epoch",
           "Training contract checkpoint tie-break mismatch.")
  _require(training.get("deterministic_algorithms") is True,
           "Training contract must require deterministic algorithms.")
  seed = _positive_integer(value["seed"], "seed")
  if explicit_seed is not None:
    _require(seed == int(explicit_seed), "CLI seed/training contract mismatch.")
  for split, path in (("train", train_path), ("validation", valid_path)):
    item = value["data"].get(split)
    _require(isinstance(item, Mapping),
             "Training contract lacks {} data.".format(split))
    _require(os.path.abspath(path) == os.path.abspath(item["path"]),
             "{} data path mismatch.".format(split))
    _require(fingerprint_file(path) == item["sha256"],
             "{} data SHA-256 mismatch.".format(split))
    _positive_integer(item["sample_count"],
                      "data.{}.sample_count".format(split))
  _require(value["method"] == {
      "F_low": 8, "F_target": 16, "b_max": 4,
      "candidate_source": "lru_tail", "selector": "disabled",
      "trajectory_policy": "proactive_lru",
  }, "Training contract changed the proactive method.")
  return {
      "contract": value,
      "contract_fingerprint": fingerprint_value(value),
      "expected_shape": {"H": H, "K": K, "page_state_dim": 4},
      "sample_identity": identity,
      "weights": weights,
      "seed": seed,
      "training": training,
      "data": value["data"],
  }
