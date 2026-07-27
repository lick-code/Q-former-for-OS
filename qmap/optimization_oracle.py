#!/usr/bin/env python3
# coding=utf-8
"""Validation-only bounded label Oracle for O1 headroom diagnosis.

The policy is deliberately non-deployable: at each valid-trace eviction it
uses the future-label definition to choose the best page inside the frozen
B-to-K candidate snapshot. Its full replay cost measures whether the candidate
pipeline leaves any learnable headroom. It never opens the official test trace.
"""

from __future__ import print_function

import argparse
import os
import sys
import time
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter
from qmap import finals_config
from qmap import finals_generator
from qmap import qmap_eval
from qmap.qmap_generator import read_trace


def _select_oracle_victim(snapshot, trace, access_index, lookahead, oracle,
                          lambda_w):
  choices = []
  for page, mask, rank in zip(
      snapshot["candidate_pages"], snapshot["candidate_mask"],
      snapshot["original_pool_ranks"]):
    if not mask:
      continue
    label = finals_generator.reference_labels(
        trace, access_index, page, lookahead, oracle,
        require_complete=False, lambda_w=lambda_w)
    choices.append((float(label["relevance"]), -int(rank), -int(page), page))
  if not choices:
    raise ValueError("Bounded Oracle received no valid candidate.")
  return max(choices)[-1], max(choices)[0]


def replay_validation(config, selector_params):
  trace_path = config["data"]["valid_trace"]
  trace, _ = read_trace(trace_path, int(config["trace"]["page_shift"]))
  lookahead = int(config["labels"]["future_lookahead_L"])
  oracle = finals_generator.FutureOracle(
      trace, lookahead, require_complete=False)
  replay_args = SimpleNamespace(**{
      key: float(value) for key, value in config["cost_model"].items()})
  capacity = int(config["memory"]["dram_capacity_pages"])
  history_length = int(config["history"]["transformer_H"])
  selector_history = candidate_filter.SelectorHistory(
      int(config["candidate"]["selector_history_Hc"]))
  stats = qmap_eval.ReplayStats()
  dram_pages = []
  nvm_pages = set(item["page"] for item in trace)
  dram_insert_time = {}
  dirty_pages = set()
  history = []
  oracle_decisions = 0
  oracle_lru_disagreements = 0
  strict_label_preferences = 0
  lambda_w = float(config["labels"]["lambda_w"])

  started = time.perf_counter()
  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = access["rw"]
    stats.total_accesses += 1
    if page in dram_pages:
      stats.hit_count += 1
      stats.weighted_access_cost += qmap_eval.dram_access_cost(
          rw, replay_args)
      qmap_eval.update_mru(dram_pages, page)
      if rw:
        dirty_pages.add(page)
    else:
      stats.miss_count += 1
      stats.weighted_access_cost += qmap_eval.nvm_access_cost(
          rw, replay_args)
      if rw:
        stats.nvm_write_count += 1
      else:
        stats.nvm_read_count += 1
      if len(dram_pages) >= capacity:
        decision_history = (history + [access])[-history_length:]
        snapshot = candidate_filter.build_filtered_candidate_snapshot(
            dram_pages, decision_history, access_index, dram_insert_time,
            dirty_pages, selector_history, config, selector_params)
        victim, oracle_score = _select_oracle_victim(
            snapshot, trace, access_index, lookahead, oracle, lambda_w)
        lru_victim = dram_pages[-1]
        lru_label = finals_generator.reference_labels(
            trace, access_index, lru_victim, lookahead, oracle,
            require_complete=False, lambda_w=lambda_w)
        oracle_decisions += 1
        oracle_lru_disagreements += int(victim != lru_victim)
        strict_label_preferences += int(
            oracle_score > float(lru_label["relevance"]) + 1e-12)
        dram_pages.remove(victim)
        nvm_pages.add(victim)
        dram_insert_time.pop(victim, None)
        dirty_pages.discard(victim)
        stats.migration_count += 1
        stats.weighted_access_cost += replay_args.migration_cost
        stats.record_decision(0.0)
      nvm_pages.discard(page)
      dram_pages.insert(0, page)
      dram_insert_time[page] = access_index
      if rw:
        dirty_pages.add(page)

    history.append(access)
    if len(history) > history_length:
      history.pop(0)
    selector_history.observe(page, rw, access_index)

  stats.replay_wall_seconds = time.perf_counter() - started
  result = stats.to_dict("bounded_label_oracle", trace_path, capacity)
  result.update(finals_config.artifact_identity_from_config(config))
  result.update({
      "schema_version": config["schema_version"],
      "contract_id": finals_config.CONTRACT_ID,
      "workload": config["run"]["workload"],
      "workload_id": config["run"]["workload"],
      "policy": "bounded_label_oracle",
      "scientific_role": "validation_only_non_deployable_headroom_bound",
      "evaluation_split": "valid",
      "evaluation_trace_fingerprint":
          finals_config.fingerprint_file(trace_path),
      "selector_fingerprint":
          finals_config.selector_fingerprint(selector_params),
      "experiment_contract": finals_config.contract_from_config(config),
      "oracle_decisions": oracle_decisions,
      "oracle_lru_disagreements": oracle_lru_disagreements,
      "oracle_lru_disagreement_rate": (
          oracle_lru_disagreements / float(oracle_decisions)
          if oracle_decisions else 0.0),
      "strict_label_preference_decisions": strict_label_preferences,
      "strict_label_preference_rate": (
          strict_label_preferences / float(oracle_decisions)
          if oracle_decisions else 0.0),
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "cost_model": dict(config["cost_model"]),
  })
  if config.get("optimization_variant") is not None:
    result["optimization_variant"] = dict(config["optimization_variant"])
  if config.get("pressure_variant") is not None:
    result["pressure_variant"] = dict(config["pressure_variant"])
  return result


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run the O1 bounded label Oracle on valid only.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--selector_params", required=True)
  parser.add_argument("--json_output", required=True)
  return parser


def main():
  args = build_arg_parser().parse_args()
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT,
      verify_manifest_files=False)
  if config["run_profile"] != finals_config.OPTIMIZATION_PROFILE:
    raise ValueError("O1 Oracle requires an optimization-only config.")
  selector = finals_config.load_json(args.selector_params)
  finals_config.validate_selector_params(config, selector)
  result = replay_validation(config, selector)
  finals_config.write_json(args.json_output, result)
  print("[O1] workload={} config={} cost={:.2f} decisions={}".format(
      result["workload"],
      config["optimization_variant"]["variant_id"],
      result["weighted_access_cost"], result["oracle_decisions"]))


if __name__ == "__main__":
  main()
