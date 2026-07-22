# coding=utf-8
"""Fit the CAPD selector and generate versioned finals JSONL artifacts."""

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
from qmap import finals_data
from qmap import selector_search
from qmap.qmap_generator import apply_history_ablation
from qmap.qmap_generator import future_stats
from qmap.qmap_generator import padded_history
from qmap.qmap_generator import read_trace


class FutureOracle(object):
  """Exact O(log n) future-window labels for a fixed trace and lookahead."""

  def __init__(self, trace, lookahead, require_complete=True):
    self._trace_length = len(trace)
    self._lookahead = int(lookahead)
    self._require_complete = bool(require_complete)
    self._positions = {}
    self._write_prefix = {}
    for index, access in enumerate(trace):
      page = access["page"]
      self._positions.setdefault(page, []).append(index)
      prefix = self._write_prefix.setdefault(page, [0])
      prefix.append(prefix[-1] + int(bool(access["rw"])))

  def stats(self, current_index, page):
    if (self._require_complete and not has_complete_future_window(
        current_index, self._lookahead, self._trace_length)):
      raise ValueError(
          "Future labels require t + L < N; decision {} has no complete "
          "window of {} accesses in trace length {}.".format(
              current_index, self._lookahead, self._trace_length))
    positions = self._positions.get(page, [])
    if not positions:
      return None, 0, 0
    start = bisect.bisect_right(positions, current_index)
    end_index = current_index + 1 + self._lookahead
    end = bisect.bisect_left(positions, end_index, lo=start)
    if start >= end:
      return None, 0, 0
    write_prefix = self._write_prefix[page]
    return (positions[start] - current_index, end - start,
            write_prefix[end] - write_prefix[start])


def has_complete_future_window(current_index, lookahead, trace_length):
  """Frozen tail guard: labels exist iff t + L < N."""
  return int(current_index) + int(lookahead) < int(trace_length)


def reference_labels(trace, current_index, page, lookahead,
                     future_oracle=None, require_complete=True):
  if (require_complete and
      not has_complete_future_window(current_index, lookahead, len(trace))):
    raise ValueError("Cannot generate labels from an incomplete future window.")
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
  is_v3 = config.get("schema_version") == finals_config.SCHEMA_VERSION
  future_oracle = FutureOracle(
      trace, lookahead, require_complete=is_v3)
  pool_size = int(config["candidate"]["pool_size_B"])
  retained = int(config["candidate"]["retained_K"])
  for access_index, access in enumerate(trace):
    complete_window = has_complete_future_window(
        access_index, lookahead, len(trace))
    if (state.is_decision(access["page"]) and
        decision_belongs_to_split(access_index, "valid", holdout) and
        (complete_window or not is_v3)):
      records = candidate_filter.build_pool_records(
          state.dram_pages, pool_size, access_index, state.selector_history,
          state.dirty_pages, params)
      labels = [
          reference_labels(
              trace, access_index, item["page"], lookahead, future_oracle,
              require_complete=is_v3)
          for item in records
      ]
      all_dram_labels = {
          page: reference_labels(
              trace, access_index, page, lookahead, future_oracle,
              require_complete=is_v3)["relevance"]
          for page in state.dram_pages
      }
      global_maximum = max(all_dram_labels.values())
      global_oracle = {
          page for page, relevance in all_dram_labels.items()
          if math.isclose(
              relevance, global_maximum, rel_tol=0.0, abs_tol=1e-12)
      }
      pool_pages = [item["page"] for item in records]
      sample = {
          "decision_index": access_index,
          "P_t": pool_pages,
          "B_t": len(records),
          "retained_K": retained,
          "selector_features": [item["selector_features"]
                                for item in records],
          "original_pool_ranks": [item["original_pool_rank"]
                                  for item in records],
          "relevance": [label["relevance"] for label in labels],
          "global_oracle_in_pool": [
              page in global_oracle for page in pool_pages],
          "pool_recall": float(bool(set(pool_pages) & global_oracle)),
      }
      if is_v3:
        sample.update({
            "schema_version": config["schema_version"],
            "contract_id": finals_config.CONTRACT_ID,
            "workload_id": config["run"]["workload"],
            "run_profile": config["run_profile"],
            "artifact_class": config["validation"]["artifact_class"],
        })
      yield sample
    state.advance(access, access_index)


def build_validation_samples(trace, config, clipping, holdout=None):
  """Materializes samples only for small callers and focused unit tests."""
  return list(iter_validation_samples(trace, config, clipping, holdout))


def write_jsonl(path, rows):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    for row in rows:
      output_file.write(json.dumps(row, sort_keys=True) + "\n")


def write_validation_samples(path, samples):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  count = 0
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
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
  is_v3 = config.get("schema_version") == finals_config.SCHEMA_VERSION
  future_oracle = FutureOracle(
      trace, lookahead, require_complete=is_v3)
  decision_count = 0
  selector_time = 0.0
  bt_values = []
  kt_values = []
  max_page = max((item["page"] for item in trace), default=1)

  directory = os.path.dirname(os.path.abspath(output_path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(output_path, "w", encoding="utf-8", newline="\n") as output_file:
    for access_index, access in enumerate(trace):
      complete_window = has_complete_future_window(
          access_index, lookahead, len(trace))
      if (state.is_decision(access["page"]) and
          decision_belongs_to_split(access_index, split_name, holdout) and
          (complete_window or not is_v3)):
        decision_history = state.decision_history(access)
        snapshot = build_generator_decision_snapshot(
            state, access, access_index, config, selector_params)
        selected_pages = [
            item["page"] for item in snapshot["selected_records"]]
        labels = [
            reference_labels(
                trace, access_index, page, lookahead, future_oracle,
                require_complete=is_v3)
            for page in selected_pages
        ]
        padded_labels = _pad_labels(labels, retained)
        history_page_ids, pc, rw = apply_history_ablation(
            *padded_history(decision_history, history_length),
            ablation="cross_attention")
        history_mask = ([0] * (history_length - len(decision_history)) +
                        [1] * len(decision_history))
        sample = {
            "schema_version": config["schema_version"],
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
        if is_v3:
          sample.update({
              "contract_id": finals_config.CONTRACT_ID,
              "workload_id": config["run"]["workload"],
              "decision_index": access_index,
              "history_page_ids": history_page_ids,
              "history_mask": history_mask,
          })
        else:
          sample["physical_address"] = history_page_ids
        output_file.write(json.dumps(sample, sort_keys=True) + "\n")
        decision_count += 1
        selector_time += snapshot["selector_time_seconds"]
        bt_values.append(snapshot["B_t"])
        kt_values.append(snapshot["K_t"])
      state.advance(access, access_index)

  data_fingerprint = finals_config.fingerprint_file(output_path)
  metadata = {
      "schema_version": config["schema_version"],
      "workload": config["run"]["workload"],
      "workload_id": config["run"]["workload"],
      "split": split_name,
      "source_partition": (
          "train_trace_decision_holdout" if holdout else
          "independent_{}_trace".format(split_name)),
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
  if is_v3:
    metadata.update({
        "contract_id": finals_config.CONTRACT_ID,
        "run_profile": config["run_profile"],
        "artifact_class": config["validation"]["artifact_class"],
        "tail_policy": config["labels"]["tail_policy"],
        "history_page_field": "history_page_ids",
    })
    metadata.update(finals_config.artifact_identity_from_config(config))
  finals_config.write_json(finals_config.metadata_path(output_path), metadata)
  return metadata


def fit_selector_and_generate(args):
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT)
  is_v3 = config["schema_version"] == finals_config.SCHEMA_VERSION
  configured_page_shift = int(config.get("trace", {}).get("page_shift", 12))
  if args.page_shift is not None and args.page_shift != configured_page_shift:
    raise ValueError("--page-shift does not match the resolved config.")
  args.page_shift = configured_page_shift
  train_path = config["data"]["train_trace"]
  valid_path = config["data"]["valid_trace"]
  test_path = config["data"]["test_trace"]
  train_trace, train_rw_source = read_trace(train_path, args.page_shift)
  valid_trace, valid_rw_source = read_trace(valid_path, args.page_shift)
  trace_fingerprints = {
      "train_trace": finals_config.fingerprint_file(train_path),
      "valid_trace": finals_config.fingerprint_file(valid_path),
      "test_trace": finals_config.fingerprint_file(test_path),
  }
  if is_v3 and config["run_profile"] == finals_config.OFFICIAL_PROFILE:
    if config.get("validation", {}).get("require_data_manifest"):
      manifest = finals_data.load_source_manifest(
          config["data"]["source_manifest"], PROJECT_ROOT,
          verify_files=True, require_quality_pass=True,
          expected_workload=config["run"]["workload"])
      finals_config.assert_independent_trace_sources(
          config, source_manifest=manifest, project_root=PROJECT_ROOT)
      bound_trace_fingerprints = {
          "{}_trace".format(split): fingerprint
          for split, fingerprint in
          config["data"]["split_fingerprints"].items()
      }
      if trace_fingerprints != bound_trace_fingerprints:
        raise ValueError("Resolved split fingerprints are stale.")
    else:
      finals_config.assert_independent_trace_sources(
          config, fingerprints=trace_fingerprints)
    holdout = None
    selector_validation_trace = valid_trace
  else:
    holdout = build_decision_holdout(train_trace, config)
    selector_validation_trace = train_trace

  raw_observations, train_decisions = collect_training_observations(
      train_trace, config, holdout)
  if holdout is not None and train_decisions != holdout["train_decision_points"]:
    raise AssertionError("Training decision count does not match split plan.")
  clipping = selector_search.clipping_values(
      raw_observations,
      float(config["features"]["selector_clip_quantile"]))
  validation_fingerprint, validation_count = write_validation_samples(
      args.validation_samples_output,
      iter_validation_samples(
          selector_validation_trace, config, clipping, holdout))
  if validation_count <= 0:
    raise ValueError(
        "Validation trace produced no complete-window selector samples.")
  if (holdout is not None and not is_v3 and
      validation_count != holdout["validation_decision_points"]):
    raise AssertionError("Validation decision count does not match split plan.")
  search_result = selector_search.search_selector_weights_jsonl(
      args.validation_samples_output,
      epsilon_y=float(config["selector"]["epsilon_y"]))
  selector_params = selector_search.selector_params_from_search(
      clipping, search_result)
  command_text = " ".join(shlex.quote(value) for value in sys.argv)
  selector_params.update({
      "schema_version": config["schema_version"],
      "workload": config["run"]["workload"],
      "config_fingerprint": finals_config.config_fingerprint(config),
      "train_trace_fingerprint": trace_fingerprints["train_trace"],
      "decision_holdout": holdout,
      "decision_holdout_fingerprint": (
          holdout["fingerprint"] if holdout is not None else None),
      "validation_samples_fingerprint": validation_fingerprint,
      "train_decision_points": train_decisions,
      "validation_decision_points": validation_count,
      "git_commit": config.get("run", {}).get("git_commit", "unknown"),
      "command": command_text,
  })
  if holdout is None:
    selector_params["decision_holdout_fingerprint"] = None
  if is_v3:
    selector_params.update({
        "contract_id": finals_config.CONTRACT_ID,
        "workload_id": config["run"]["workload"],
        "run_profile": config["run_profile"],
        "artifact_class": config["validation"]["artifact_class"],
        "valid_trace_fingerprint": trace_fingerprints["valid_trace"],
        "behavior_policy": config["selector"]["behavior_policy"],
        "tail_policy": config["labels"]["tail_policy"],
        "selection_rule": (
            "selector_recall_desc,nregret_asc,uniform_distance,lexicographic"),
    })
    selector_params.update(finals_config.artifact_identity_from_config(config))
  else:
    selector_params.update({
        "external_valid_trace_fingerprint": trace_fingerprints["valid_trace"],
        "external_valid_trace_role": config["validation"][
            "external_valid_trace_role"],
    })
  finals_config.validate_selector_params(config, selector_params)
  finals_config.write_json(args.selector_output, selector_params)
  finals_config.write_json(
      os.path.join(os.path.dirname(os.path.abspath(args.selector_output)),
                   "resolved_config.json"),
      config)

  train_metadata = generate_reranker_jsonl(
      train_trace, train_path, "train", args.train_output, config,
      selector_params, args.config, command_text, holdout=holdout)
  reranker_valid_trace = valid_trace if holdout is None else train_trace
  reranker_valid_path = valid_path if holdout is None else train_path
  valid_metadata = generate_reranker_jsonl(
      reranker_valid_trace, reranker_valid_path, "valid", args.valid_output, config,
      selector_params, args.config, command_text, holdout=holdout)
  valid_diagnostics = trace_diagnostics(valid_trace, config)
  valid_diagnostics.update({
      "path": valid_path,
      "fingerprint": trace_fingerprints["valid_trace"],
      "role": ("selector_search_and_model_selection" if holdout is None
               else config["validation"]["external_valid_trace_role"]),
      "rw_source": valid_rw_source,
  })
  result = {
      "schema_version": config["schema_version"],
      "selector_params": args.selector_output,
      "selector_fingerprint": finals_config.selector_fingerprint(
          selector_params),
      "decision_holdout": holdout,
      "train_metadata": train_metadata,
      "valid_metadata": valid_metadata,
      "valid_trace_diagnostics": valid_diagnostics,
      "trace_fingerprints": trace_fingerprints,
      "rw_source": {
          "train_trace": train_rw_source,
          "valid_trace": valid_rw_source,
      },
  }
  if is_v3:
    result.update(finals_config.artifact_identity_from_config(config))
  finals_config.write_json(args.summary_output, result)
  print("[done] selector={}".format(args.selector_output))
  print("[done] train_jsonl={}".format(args.train_output))
  print("[done] valid_jsonl={}".format(args.valid_output))
  print("[done] summary={}".format(args.summary_output))


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Fit a versioned CAPD selector and generate contract-bound "
          "train/valid JSONL."))
  parser.add_argument("--config", required=True,
                      help="Resolved v2.1 or capd_finals_v3_0 config.")
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
