#!/usr/bin/env python3
# coding=utf-8
"""Counterfactual decision-opportunity audit for the R1 pressure scan."""

from __future__ import print_function

import argparse
import os
import statistics
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_generator
from qmap import pressure_variants
from qmap import stage4_common
from qmap import stage4_counterfactual
from qmap.qmap_generator import read_trace


def _rate(count, total):
  return count / float(total) if total else 0.0


def _spread(values):
  return max(values) - min(values) if values else 0.0


def audit_validation(config, selector_params):
  """Audit valid decisions incrementally without retaining candidate rows."""
  trace_path = config["data"]["valid_trace"]
  trace, _ = read_trace(trace_path, int(config["trace"]["page_shift"]))
  lookahead = int(config["labels"]["future_lookahead_L"])
  epsilon = float(config["selector"]["epsilon_y"])
  state = finals_generator.LRUBehaviorState(config)
  oracle = finals_generator.FutureOracle(
      trace, lookahead, require_complete=True)
  weights = stage4_common.LABEL_VARIANTS["base"]

  eviction_decisions = 0
  complete_decisions = 0
  cost_distinguishable = 0
  proxy_distinguishable = 0
  write_distinguishable = 0
  mixed_dirty_candidates = 0
  proxy_cost_top1_hits = 0.0
  ndcg_values = []
  correlations = []
  cost_spreads = []
  started = time.perf_counter()

  for access_index, access in enumerate(trace):
    is_decision = state.is_decision(access["page"])
    if is_decision:
      eviction_decisions += 1
    complete = finals_generator.has_complete_future_window(
        access_index, lookahead, len(trace))
    if is_decision and complete:
      snapshot = finals_generator.build_generator_decision_snapshot(
          state, access, access_index, config, selector_params)
      rows = []
      dirty_flags = []
      future_accesses = trace[
          access_index + 1:access_index + 1 + lookahead]
      for record in snapshot["selected_records"]:
        page = record["page"]
        label = finals_generator.reference_labels(
            trace, access_index, page, lookahead, oracle,
            require_complete=True)
        counterfactual = stage4_counterfactual.replay_forced_victim(
            state, access, future_accesses, page, config["cost_model"])
        row = {
            "original_pool_rank": record["original_pool_rank"],
            "d_hat": label["inactivity"],
            "q_hat": label["coldness"],
            "w_hat": label["write_intensity"],
        }
        row.update(counterfactual)
        rows.append(row)
        dirty_flags.append(page in state.dirty_pages)
      stage4_common.require(rows, "R1 decision has no retained candidates")
      metrics = stage4_counterfactual.decision_metrics(
          rows, "base", weights)
      costs = [float(row["J"]) for row in rows]
      proxy_scores = [float(value) for value in metrics["proxy_scores"]]
      write_labels = [float(row["w_hat"]) for row in rows]
      cost_spread = _spread(costs)
      complete_decisions += 1
      cost_distinguishable += int(cost_spread > 1e-12)
      proxy_distinguishable += int(_spread(proxy_scores) > epsilon)
      write_distinguishable += int(_spread(write_labels) > epsilon)
      mixed_dirty_candidates += int(
          any(dirty_flags) and not all(dirty_flags))
      proxy_cost_top1_hits += float(metrics["top1_any_hit"])
      ndcg_values.append(float(metrics["ndcg"]))
      if metrics["spearman_defined"]:
        correlations.append(float(metrics["spearman"]))
      cost_spreads.append(cost_spread)
      if complete_decisions % 250 == 0:
        print(
            "[R1_PROGRESS] workload={} case={} complete_decisions={} "
            "access_index={} elapsed_seconds={:.1f}".format(
                config["run"]["workload"],
                config["pressure_variant"]["case_id"],
                complete_decisions, access_index,
                time.perf_counter() - started),
            flush=True)
    state.advance(access, access_index)

  stage4_common.require(
      complete_decisions > 0, "R1 valid trace has no complete decisions")
  variant = dict(config["pressure_variant"])
  result = {
      "schema_version": "capd_r1_pressure_opportunity_1",
      "status": "COMPLETED",
      "contract_id": finals_config.CONTRACT_ID,
      "scientific_role": pressure_variants.SCIENTIFIC_ROLE,
      "workload": config["run"]["workload"],
      "case_id": variant["case_id"],
      "D": int(variant["D"]),
      "B": int(variant["B"]),
      "K": int(variant["K"]),
      "H": int(variant["H"]),
      "Hc": int(variant["Hc"]),
      "L": int(variant["L"]),
      "Lres": int(variant["Lres"]),
      "evaluation_split": "valid",
      "evaluation_trace_fingerprint":
          finals_config.fingerprint_file(trace_path),
      "selector_fingerprint":
          finals_config.selector_fingerprint(selector_params),
      "total_accesses": len(trace),
      "eviction_decisions": eviction_decisions,
      "complete_window_decisions": complete_decisions,
      "counterfactual_cost_distinguishable_decisions":
          cost_distinguishable,
      "counterfactual_cost_distinguishable_rate":
          _rate(cost_distinguishable, complete_decisions),
      "counterfactual_cost_indistinguishable_ratio":
          1.0 - _rate(cost_distinguishable, complete_decisions),
      "proxy_label_distinguishable_decisions": proxy_distinguishable,
      "proxy_label_distinguishable_rate":
          _rate(proxy_distinguishable, complete_decisions),
      "future_write_label_distinguishable_decisions":
          write_distinguishable,
      "future_write_label_distinguishable_rate":
          _rate(write_distinguishable, complete_decisions),
      "mixed_clean_dirty_candidate_decisions": mixed_dirty_candidates,
      "mixed_clean_dirty_candidate_rate":
          _rate(mixed_dirty_candidates, complete_decisions),
      "counterfactual_cost_spread_mean":
          statistics.mean(cost_spreads),
      "counterfactual_cost_spread_median":
          statistics.median(cost_spreads),
      "counterfactual_cost_spread_max": max(cost_spreads),
      "proxy_cost_top1_any_hit_rate":
          proxy_cost_top1_hits / float(complete_decisions),
      "proxy_cost_ndcg_mean": statistics.mean(ndcg_values),
      "proxy_cost_spearman_mean": (
          statistics.mean(correlations) if correlations else None),
      "proxy_cost_spearman_defined_decisions": len(correlations),
      "pressure_variant": variant,
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }
  result.update(finals_config.artifact_identity_from_config(config))
  return result


def summarize_pressure_point(point, oracle, opportunity, baselines):
  """Combine one point's immutable job outputs into a flat result row."""
  if len(baselines) != 2:
    raise ValueError("R1 requires exactly LRU and CLOCK baselines.")
  best = min(
      baselines,
      key=lambda row: (
          float(row["weighted_access_cost"]), str(row["policy"])))
  baseline_cost = float(best["weighted_access_cost"])
  oracle_cost = float(oracle["weighted_access_cost"])
  saving = baseline_cost - oracle_cost
  return {
      "workload": oracle["workload"],
      "case_id": point["case_id"],
      "D": int(point["D"]),
      "B": int(point["B"]),
      "K": int(point["K"]),
      "best_classic_policy": best["policy"],
      "best_classic_weighted_access_cost": baseline_cost,
      "oracle_weighted_access_cost": oracle_cost,
      "absolute_headroom": saving,
      "relative_headroom_percent": (
          saving * 100.0 / baseline_cost if baseline_cost else 0.0),
      "oracle_decisions": int(oracle["oracle_decisions"]),
      "strict_label_preference_decisions":
          int(oracle["strict_label_preference_decisions"]),
      "strict_label_preference_rate":
          float(oracle["strict_label_preference_rate"]),
      "measurable_headroom": bool(
          saving > 0 and
          int(oracle["strict_label_preference_decisions"]) > 0),
      "eviction_decisions": int(opportunity["eviction_decisions"]),
      "complete_window_decisions":
          int(opportunity["complete_window_decisions"]),
      "counterfactual_cost_distinguishable_decisions": int(
          opportunity["counterfactual_cost_distinguishable_decisions"]),
      "counterfactual_cost_distinguishable_rate": float(
          opportunity["counterfactual_cost_distinguishable_rate"]),
      "proxy_label_distinguishable_rate": float(
          opportunity["proxy_label_distinguishable_rate"]),
      "future_write_label_distinguishable_rate": float(
          opportunity["future_write_label_distinguishable_rate"]),
      "mixed_clean_dirty_candidate_rate": float(
          opportunity["mixed_clean_dirty_candidate_rate"]),
      "counterfactual_cost_spread_mean": float(
          opportunity["counterfactual_cost_spread_mean"]),
      "counterfactual_cost_spread_median": float(
          opportunity["counterfactual_cost_spread_median"]),
      "counterfactual_cost_spread_max": float(
          opportunity["counterfactual_cost_spread_max"]),
      "evaluation_split": "valid",
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run one R1 valid-only counterfactual opportunity audit.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--selector_params", required=True)
  parser.add_argument("--json_output", required=True)
  return parser


def main():
  args = build_arg_parser().parse_args()
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT,
      verify_manifest_files=False)
  if config.get("run_profile") != finals_config.DIAGNOSTIC_PROFILE:
    raise ValueError("R1 opportunity audit requires diagnostic profile.")
  variant = config.get("pressure_variant", {})
  if variant.get("family") != pressure_variants.FAMILY:
    raise ValueError("R1 opportunity audit requires pressure_variant.")
  selector = finals_config.load_json(args.selector_params)
  finals_config.validate_selector_params(config, selector)
  result = audit_validation(config, selector)
  finals_config.write_json(args.json_output, result)
  print("[R1] workload={} case={} distinguishable={}/{}".format(
      result["workload"], result["case_id"],
      result["counterfactual_cost_distinguishable_decisions"],
      result["complete_window_decisions"]))


if __name__ == "__main__":
  main()
