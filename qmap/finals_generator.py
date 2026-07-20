# coding=utf-8
"""Fit the CAPD selector and generate finals_v2.1 holdout JSONL files."""

from __future__ import print_function

import argparse
import bisect
import collections
import json
import math
import os
import shlex
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter
from qmap import finals_config
from qmap import selector_search
from qmap.qmap_generator import apply_history_ablation
from qmap.qmap_generator import future_stats
from qmap.qmap_generator import padded_history
from qmap.qmap_generator import read_trace


class FutureOracle(object):
  """Exact O(log n) future-window labels for a fixed trace and lookahead."""

  def __init__(self, trace, lookahead):
    self._trace_length = len(trace)
    self._lookahead = int(lookahead)
    self._positions = {}
    self._write_prefix = {}
    for index, access in enumerate(trace):
      page = access["page"]
      self._positions.setdefault(page, []).append(index)
      prefix = self._write_prefix.setdefault(page, [0])
      prefix.append(prefix[-1] + int(bool(access["rw"])))

  def stats(self, current_index, page):
    positions = self._positions.get(page, [])
    if not positions:
      return None, 0, 0
    start = bisect.bisect_right(positions, current_index)
    end_index = min(
        self._trace_length, current_index + 1 + self._lookahead)
    end = bisect.bisect_left(positions, end_index, lo=start)
    if start >= end:
      return None, 0, 0
    write_prefix = self._write_prefix[page]
    return (positions[start] - current_index, end - start,
            write_prefix[end] - write_prefix[start])


def reference_labels(trace, current_index, page, lookahead,
                     future_oracle=None):
  if future_oracle is None:
    next_distance, frequency, write_frequency = future_stats(
        trace, current_index, page, lookahead)
  else:
    next_distance, frequency, write_frequency = future_oracle.stats(
        current_index, page)
  if next_distance is None:
    inactivity = 1.0
  else:
    inactivity = min(next_distance, lookahead) / float(lookahead)
  coldness = 1.0 - min(frequency / float(lookahead), 1.0)
  write_intensity = min(write_frequency / float(lookahead), 1.0)
  relevance = inactivity + coldness - 4.0 * write_intensity
  return {
      "inactivity": inactivity,
      "coldness": coldness,
      "write_intensity": write_intensity,
      "migration_cost": 0.0,
      "relevance": relevance,
  }


class LRUBehaviorState(object):
  """Frozen LRU behavior-policy state shared by all generator passes."""

  def __init__(self, config):
    self.dram_capacity = int(config["memory"]["dram_capacity_pages"])
    self.transformer_H = int(config["history"]["transformer_H"])
    self.dram_pages = []
    self.dram_insert_time = {}
    self.dirty_pages = set()
    self.transformer_history = collections.deque(maxlen=self.transformer_H)
    self.selector_history = candidate_filter.SelectorHistory(
        int(config["candidate"]["selector_history_Hc"]))

  def is_decision(self, page):
    return page not in self.dram_pages and len(self.dram_pages) >= (
        self.dram_capacity)

  def decision_history(self, access):
    return (list(self.transformer_history) + [access])[-self.transformer_H:]

  def advance(self, access, access_index):
    page = access["page"]
    rw = access["rw"]
    if page in self.dram_pages:
      self.dram_pages.remove(page)
      self.dram_pages.insert(0, page)
      if rw:
        self.dirty_pages.add(page)
    else:
      if len(self.dram_pages) >= self.dram_capacity:
        victim = self.dram_pages.pop()
        self.dram_insert_time.pop(victim, None)
        self.dirty_pages.discard(victim)
      self.dram_pages.insert(0, page)
      self.dram_insert_time[page] = access_index
      if rw:
        self.dirty_pages.add(page)
    self.transformer_history.append(access)
    self.selector_history.observe(page, rw, access_index)


def collect_decision_indices(trace, config):
  """Returns chronological LRU victim-decision access indices."""
  state = LRUBehaviorState(config)
  decision_indices = []
  for access_index, access in enumerate(trace):
    if state.is_decision(access["page"]):
      decision_indices.append(access_index)
    state.advance(access, access_index)
  return decision_indices


def build_decision_holdout(trace, config):
  """Builds the frozen chronological 80/20 decision split with an L guard."""
  decision_indices = collect_decision_indices(trace, config)
  total_decisions = len(decision_indices)
  if total_decisions < 2:
    raise ValueError(
        "train_trace_decision_holdout needs at least two victim decisions; "
        "found {}.".format(total_decisions))

  validation = config["validation"]
  fraction = float(validation["holdout_fraction"])
  validation_decisions = int(math.ceil(total_decisions * fraction))
  if validation_decisions <= 0 or validation_decisions >= total_decisions:
    raise ValueError(
        "Decision holdout leaves no train or validation decisions: "
        "total={} validation={}.".format(
            total_decisions, validation_decisions))

  validation_start = decision_indices[-validation_decisions]
  guard_accesses = int(validation["guard_accesses"])
  train_end = max(0, validation_start - guard_accesses)
  train_decisions = [
      index for index in decision_indices if index < train_end]
  guard_decisions = [
      index for index in decision_indices
      if train_end <= index < validation_start]
  heldout_decisions = [
      index for index in decision_indices if index >= validation_start]
  if not train_decisions:
    raise ValueError(
        "The validation guard removes every training decision; "
        "validation_start={} guard_accesses={}.".format(
            validation_start, guard_accesses))
  if len(heldout_decisions) != validation_decisions:
    raise AssertionError("Decision holdout count is inconsistent.")
  if train_decisions[-1] + guard_accesses >= validation_start:
    raise AssertionError("Training lookahead can cross the validation boundary.")

  plan = {
      "strategy": validation["strategy"],
      "basis": "lru_victim_decision_points",
      "order": "chronological",
      "holdout_fraction": fraction,
      "rounding": validation["rounding"],
      "guard_accesses": guard_accesses,
      "trace_access_count": len(trace),
      "total_decision_points": total_decisions,
      "train_access_end_exclusive": train_end,
      "validation_access_start_inclusive": validation_start,
      "train_decision_points": len(train_decisions),
      "guard_decision_points": len(guard_decisions),
      "validation_decision_points": len(heldout_decisions),
      "last_train_decision_index": train_decisions[-1],
      "first_validation_decision_index": heldout_decisions[0],
  }
  plan["fingerprint"] = finals_config.decision_holdout_fingerprint(plan)
  return finals_config.validate_decision_holdout(plan, config)


def decision_belongs_to_split(access_index, split_name, holdout):
  if holdout is None:
    return True
  if split_name == "train":
    return access_index < int(holdout["train_access_end_exclusive"])
  if split_name == "valid":
    return access_index >= int(
        holdout["validation_access_start_inclusive"])
  raise ValueError("Unsupported reranker split: {}".format(split_name))


def trace_diagnostics(trace, config):
  return {
      "access_count": len(trace),
      "unique_page_count": len(set(item["page"] for item in trace)),
      "lru_victim_decision_points": len(
          collect_decision_indices(trace, config)),
  }


def collect_training_observations(trace, config, holdout=None):
  state = LRUBehaviorState(config)
  pool_size = int(config["candidate"]["pool_size_B"])
  observations = {"Delta": [], "A": [], "W": []}
  decision_count = 0
  for access_index, access in enumerate(trace):
    if (state.is_decision(access["page"]) and
        decision_belongs_to_split(access_index, "train", holdout)):
      pool = candidate_filter.build_candidate_pool(state.dram_pages, pool_size)
      for rank, page in enumerate(pool):
        raw = candidate_filter.raw_selector_values(
            page, rank, len(pool), access_index, state.selector_history,
            state.dirty_pages)
        observations["Delta"].append(raw["Delta"])
        observations["A"].append(raw["A"])
        observations["W"].append(raw["W"])
      decision_count += 1
    state.advance(access, access_index)
  return observations, decision_count


def iter_validation_samples(trace, config, clipping, holdout=None):
  state = LRUBehaviorState(config)
  params = dict(clipping)
  params.update({
      "w_Delta": 0.2,
      "w_A": 0.2,
      "w_W": 0.2,
      "w_C": 0.2,
      "w_R": 0.2,
  })
  lookahead = int(config["labels"]["future_lookahead_L"])
  future_oracle = FutureOracle(trace, lookahead)
  pool_size = int(config["candidate"]["pool_size_B"])
  retained = int(config["candidate"]["retained_K"])
  for access_index, access in enumerate(trace):
    if (state.is_decision(access["page"]) and
        decision_belongs_to_split(access_index, "valid", holdout)):
      records = candidate_filter.build_pool_records(
          state.dram_pages, pool_size, access_index, state.selector_history,
          state.dirty_pages, params)
      labels = [
          reference_labels(
              trace, access_index, item["page"], lookahead, future_oracle)
          for item in records
      ]
      yield {
          "decision_index": access_index,
          "P_t": [item["page"] for item in records],
          "B_t": len(records),
          "retained_K": retained,
          "selector_features": [item["selector_features"]
                                for item in records],
          "original_pool_ranks": [item["original_pool_rank"]
                                  for item in records],
          "relevance": [label["relevance"] for label in labels],
      }
    state.advance(access, access_index)


def build_validation_samples(trace, config, clipping, holdout=None):
  """Materializes samples only for small callers and focused unit tests."""
  return list(iter_validation_samples(trace, config, clipping, holdout))


def write_jsonl(path, rows):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    for row in rows:
      output_file.write(json.dumps(row, sort_keys=True) + "\n")


def write_validation_samples(path, samples):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  count = 0
  with open(path, "w", encoding="utf-8") as output_file:
    for sample in samples:
      output_file.write(json.dumps(sample, sort_keys=True) + "\n")
      count += 1
  return finals_config.fingerprint_file(path), count


def _pad_labels(labels, retained_K):
  values = {
      "inactivity": [],
      "coldness": [],
      "write_sensitivity": [],
      "migration_cost": [],
  }
  for label in labels:
    values["inactivity"].append(label["inactivity"])
    values["coldness"].append(label["coldness"])
    values["write_sensitivity"].append(label["write_intensity"])
    values["migration_cost"].append(0.0)
  for key in values:
    while len(values[key]) < retained_K:
      values[key].append(0.0)
  return values


def build_generator_decision_snapshot(state, access, access_index, config,
                                      selector_params):
  """Adapter kept explicit so tests can compare Generator and Replay paths."""
  return candidate_filter.build_filtered_candidate_snapshot(
      state.dram_pages, state.decision_history(access), access_index,
      state.dram_insert_time, state.dirty_pages, state.selector_history,
      config, selector_params)


def generate_reranker_jsonl(trace, trace_path, split_name, output_path, config,
                            selector_params, resolved_config_path,
                            command_text, holdout=None):
  state = LRUBehaviorState(config)
  lookahead = int(config["labels"]["future_lookahead_L"])
  retained = int(config["candidate"]["retained_K"])
  history_length = int(config["history"]["transformer_H"])
  future_oracle = FutureOracle(trace, lookahead)
  decision_count = 0
  selector_time = 0.0
  bt_values = []
  kt_values = []
  max_page = max((item["page"] for item in trace), default=1)

  directory = os.path.dirname(os.path.abspath(output_path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(output_path, "w", encoding="utf-8") as output_file:
    for access_index, access in enumerate(trace):
      if (state.is_decision(access["page"]) and
          decision_belongs_to_split(access_index, split_name, holdout)):
        decision_history = state.decision_history(access)
        snapshot = build_generator_decision_snapshot(
            state, access, access_index, config, selector_params)
        selected_pages = [
            item["page"] for item in snapshot["selected_records"]]
        labels = [
            reference_labels(
                trace, access_index, page, lookahead, future_oracle)
            for page in selected_pages
        ]
        padded_labels = _pad_labels(labels, retained)
        physical_address, pc, rw = apply_history_ablation(
            *padded_history(decision_history, history_length),
            ablation="cross_attention")
        sample = {
            "schema_version": finals_config.SCHEMA_VERSION,
            "physical_address": physical_address,
            "pc": pc,
            "rw": rw,
            "candidate_pages": snapshot["candidate_pages"],
            "candidate_state_features": snapshot[
                "candidate_state_features"],
            "candidate_mask": snapshot["candidate_mask"],
            "original_pool_ranks": snapshot["original_pool_ranks"],
            "inactivity": padded_labels["inactivity"],
            "coldness": padded_labels["coldness"],
            "write_sensitivity": padded_labels["write_sensitivity"],
            # Constant and excluded by finals_v2 loss (lambda_4=0).
            "migration_cost": padded_labels["migration_cost"],
        }
        output_file.write(json.dumps(sample, sort_keys=True) + "\n")
        decision_count += 1
        selector_time += snapshot["selector_time_seconds"]
        bt_values.append(snapshot["B_t"])
        kt_values.append(snapshot["K_t"])
      state.advance(access, access_index)

  data_fingerprint = finals_config.fingerprint_file(output_path)
  metadata = {
      "schema_version": finals_config.SCHEMA_VERSION,
      "workload": config["run"]["workload"],
      "split": split_name,
      "source_partition": (
          "train_trace_decision_holdout" if holdout else split_name),
      "source_trace": trace_path,
      "source_trace_fingerprint": finals_config.fingerprint_file(trace_path),
      "resolved_config": os.path.abspath(resolved_config_path),
      "config_fingerprint": finals_config.config_fingerprint(config),
      "experiment_contract": finals_config.contract_from_config(config),
      "selector_params": selector_params,
      "selector_fingerprint": finals_config.selector_fingerprint(
          selector_params),
      "data_fingerprint": data_fingerprint,
      "sample_count": decision_count,
      "decision_holdout": holdout,
      "decision_holdout_fingerprint": (
          holdout.get("fingerprint") if holdout else None),
      "shape": {
          "H": history_length,
          "K": retained,
          "page_state_dim": int(config["features"]["page_state_dim"]),
      },
      "candidate_filter_metrics": {
          "decision_count": decision_count,
          "min_B_t": min(bt_values) if bt_values else 0,
          "max_B_t": max(bt_values) if bt_values else 0,
          "mean_B_t": sum(bt_values) / float(len(bt_values))
          if bt_values else 0.0,
          "min_K_t": min(kt_values) if kt_values else 0,
          "max_K_t": max(kt_values) if kt_values else 0,
          "mean_K_t": sum(kt_values) / float(len(kt_values))
          if kt_values else 0.0,
          "selector_time_seconds": selector_time,
          "avg_selector_time_ms": (
              selector_time * 1000.0 / decision_count
              if decision_count else 0.0),
      },
      "max_page": max_page,
      "git_commit": config.get("run", {}).get("git_commit", "unknown"),
      "command": command_text,
  }
  finals_config.write_json(finals_config.metadata_path(output_path), metadata)
  return metadata


def fit_selector_and_generate(args):
  config = finals_config.load_config(args.config, require_resolved=True)
  configured_page_shift = int(config.get("trace", {}).get("page_shift", 12))
  if args.page_shift is not None and args.page_shift != configured_page_shift:
    raise ValueError("--page-shift does not match the resolved config.")
  args.page_shift = configured_page_shift
  train_path = config["data"]["train_trace"]
  external_valid_path = config["data"]["valid_trace"]
  train_trace, train_rw_source = read_trace(train_path, args.page_shift)
  external_valid_trace, external_valid_rw_source = read_trace(
      external_valid_path, args.page_shift)

  holdout = build_decision_holdout(train_trace, config)

  raw_observations, train_decisions = collect_training_observations(
      train_trace, config, holdout)
  if train_decisions != holdout["train_decision_points"]:
    raise AssertionError("Training decision count does not match split plan.")
  clipping = selector_search.clipping_values(
      raw_observations,
      float(config["features"]["selector_clip_quantile"]))
  validation_fingerprint, validation_count = write_validation_samples(
      args.validation_samples_output,
      iter_validation_samples(train_trace, config, clipping, holdout))
  if validation_count <= 0:
    raise ValueError(
        "Decision holdout produced no selector/model validation samples.")
  if validation_count != holdout["validation_decision_points"]:
    raise AssertionError("Validation decision count does not match split plan.")
  search_result = selector_search.search_selector_weights_jsonl(
      args.validation_samples_output,
      epsilon_y=float(config["selector"]["epsilon_y"]))
  selector_params = selector_search.selector_params_from_search(
      clipping, search_result)
  command_text = " ".join(shlex.quote(value) for value in sys.argv)
  selector_params.update({
      "schema_version": finals_config.SCHEMA_VERSION,
      "workload": config["run"]["workload"],
      "config_fingerprint": finals_config.config_fingerprint(config),
      "train_trace_fingerprint": finals_config.fingerprint_file(train_path),
      "external_valid_trace_fingerprint": finals_config.fingerprint_file(
          external_valid_path),
      "external_valid_trace_role": config["validation"][
          "external_valid_trace_role"],
      "decision_holdout": holdout,
      "decision_holdout_fingerprint": holdout["fingerprint"],
      "validation_samples_fingerprint": validation_fingerprint,
      "train_decision_points": train_decisions,
      "validation_decision_points": validation_count,
      "git_commit": config.get("run", {}).get("git_commit", "unknown"),
      "command": command_text,
  })
  finals_config.write_json(args.selector_output, selector_params)
  finals_config.write_json(
      os.path.join(os.path.dirname(os.path.abspath(args.selector_output)),
                   "resolved_config.json"),
      config)

  train_metadata = generate_reranker_jsonl(
      train_trace, train_path, "train", args.train_output, config,
      selector_params, args.config, command_text, holdout=holdout)
  valid_metadata = generate_reranker_jsonl(
      train_trace, train_path, "valid", args.valid_output, config,
      selector_params, args.config, command_text, holdout=holdout)
  external_valid_diagnostics = trace_diagnostics(
      external_valid_trace, config)
  external_valid_diagnostics.update({
      "path": external_valid_path,
      "fingerprint": finals_config.fingerprint_file(external_valid_path),
      "role": config["validation"]["external_valid_trace_role"],
      "rw_source": external_valid_rw_source,
  })
  result = {
      "selector_params": args.selector_output,
      "selector_fingerprint": finals_config.selector_fingerprint(
          selector_params),
      "decision_holdout": holdout,
      "train_metadata": train_metadata,
      "valid_metadata": valid_metadata,
      "external_valid_trace_diagnostics": external_valid_diagnostics,
      "rw_source": {
          "train_trace": train_rw_source,
          "external_valid_trace": external_valid_rw_source,
      },
  }
  finals_config.write_json(args.summary_output, result)
  print("[done] selector={}".format(args.selector_output))
  print("[done] train_jsonl={}".format(args.train_output))
  print("[done] valid_jsonl={}".format(args.valid_output))
  print("[done] summary={}".format(args.summary_output))


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Fit CAPD finals_v2.1 selector and generate decision-holdout "
          "train/valid JSONL."))
  parser.add_argument("--config", required=True,
                      help="Resolved capd_finals_v2_1 config.")
  parser.add_argument("--selector-output", required=True)
  parser.add_argument("--validation-samples-output", required=True)
  parser.add_argument("--train-output", required=True)
  parser.add_argument("--valid-output", required=True)
  parser.add_argument("--summary-output", required=True)
  parser.add_argument("--page-shift", type=int, default=None,
                      help="Optional assertion against config.trace.page_shift.")
  return parser


if __name__ == "__main__":
  fit_selector_and_generate(build_arg_parser().parse_args())
