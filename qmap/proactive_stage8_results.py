# coding=utf-8
"""Track-separated Stage-8 aggregation, fairness, and frozen statistics."""

from __future__ import annotations

import collections
import csv
import json
import os
import random
import statistics
import tempfile
from typing import Any, Dict, Mapping, Sequence

from qmap import proactive_stage8_contract as contract


PRIMARY_FIELDS = (
    "weighted_cost", "weighted_cost_per_access", "dram_hits", "nvm_reads",
    "nvm_writes", "total_demotions", "proactive_demotions",
    "emergency_demotions", "fallback_rate", "minimum_free_frames",
    "average_free_frames")


def _mean(values: Sequence[float]) -> float:
  return sum(float(value) for value in values) / float(len(values))


def _sample_std(values: Sequence[float]) -> float:
  return statistics.stdev(float(value) for value in values) if len(values) > 1 else 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
  ordered = sorted(float(value) for value in values)
  position = (len(ordered) - 1) * probability
  low = int(position)
  high = min(low + 1, len(ordered) - 1)
  return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_ci(values: Sequence[float], seed: int, resamples: int,
                 confidence: float = 0.95) -> Dict[str, Any]:
  if not values or resamples <= 0:
    raise contract.Stage8ContractError("Bootstrap requires values/resamples.")
  rng = random.Random(int(seed))
  count = len(values)
  draws = []
  for _ in range(int(resamples)):
    draws.append(_mean([values[rng.randrange(count)] for __ in range(count)]))
  alpha = (1.0 - float(confidence)) / 2.0
  return {
      "estimate": _mean(values), "lower": _percentile(draws, alpha),
      "upper": _percentile(draws, 1.0 - alpha),
      "confidence_level": confidence, "method": "percentile_bootstrap",
      "seed": int(seed), "resamples": int(resamples),
      "resampling_unit": "track_workload_cell", "cell_count": count}


def _same(rows: Sequence[Mapping[str, Any]], fields: Sequence[str],
          label: str) -> None:
  for field in fields:
    values = {json.dumps(row.get(field), sort_keys=True) for row in rows}
    if len(values) != 1:
      raise contract.Stage8ContractError(
          "{} fairness mismatch: {}".format(label, field))


def fairness_audit(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  by_cell = collections.defaultdict(list)
  for row in results:
    by_cell[(row["track"], row["workload"])].append(row)
  expected_cells = ({("standard", workload) for workload in contract.STANDARD_WORKLOADS} |
                    {("pressure", workload) for workload in contract.PRESSURE_WORKLOADS})
  if set(by_cell) != expected_cells:
    raise contract.Stage8ContractError("Fairness requires the exact 10 cells.")
  common_fields = (
      "track", "workload", "test_identity", "trace_sha256",
      "source_interval", "evaluation_interval", "D", "W_ref", "F_low",
      "F_target", "K", "b_max", "alpha", "beta", "history_H",
      "initial_state_sha256", "cost_profile_sha256", "cost_profile",
      "page_enter_dram_semantics")
  audits = []
  for cell, rows in sorted(by_cell.items()):
    by_policy = collections.defaultdict(list)
    for row in rows:
      by_policy[row["policy"]].append(row)
    if set(by_policy) != set(contract.FORMAL_POLICIES):
      raise contract.Stage8ContractError("Cell policy membership is incomplete.")
    if len(by_policy["capd"]) != 3 or any(
        len(by_policy[policy]) != 1 for policy in contract.DETERMINISTIC_POLICIES):
      raise contract.Stage8ContractError("Seed/deterministic cardinality changed.")
    if [row["seed"] for row in by_policy["capd"]] != list(contract.CAPD_SEEDS):
      raise contract.Stage8ContractError("CAPD seeds were selected or reordered.")
    _same(rows, common_fields, "track-workload cell")
    _same([row for row in rows if row["policy"] in contract.COMPARISON_A], (
        "F_low", "F_target", "K", "b_max", "candidate_source",
        "fallback_policy", "trigger_mode", "candidate_contract_sha256"),
        "active-policy")
    audits.append({
        "track": cell[0], "workload": cell[1],
        "policy_membership": "passed", "seed_membership": "passed",
        "trace_and_control_identity": "passed"})
  cross_track = []
  for workload in contract.PRESSURE_WORKLOADS:
    standard = by_cell[("standard", workload)]
    pressure = by_cell[("pressure", workload)]
    _same(standard + pressure, (
        "D", "W_ref", "F_low", "F_target", "K", "b_max", "alpha", "beta",
        "history_H", "cost_profile_sha256", "initial_state_sha256",
        "candidate_contract_sha256", "page_enter_dram_semantics"),
        "cross-track controls")
    for seed in contract.CAPD_SEEDS:
      pair = [row for row in standard + pressure
              if row["policy"] == "capd" and row["seed"] == seed]
      _same(pair, ("checkpoint_sha256",), "cross-track checkpoint")
    cross_track.append({"workload": workload, "status": "passed"})
  return {
      "status": "passed", "cell_count": 10, "cells": audits,
      "standard_cell_count": 6, "pressure_cell_count": 4,
      "cross_track_same_model_checkpoint_controls": cross_track,
      "tracks_are_not_seeds": True,
      "test_used_for_parameter_selection": False}


def _metric_row(result: Mapping[str, Any]) -> Dict[str, Any]:
  metrics = result["metrics"]
  row = {
      "job_id": result["job_id"], "track": result["track"],
      "workload": result["workload"], "workload_role": result["workload_role"],
      "policy": result["policy"], "seed": result["seed"],
      "D": result["D"], "W_ref": result["W_ref"],
      "F_low": result["F_low"], "F_target": result["F_target"],
      "K": result["K"], "b_max": result["b_max"],
      "alpha": result["alpha"], "beta": result["beta"],
      "trace_sha256": result["trace_sha256"],
      "source_interval": result["source_interval"],
      "evaluation_interval": result["evaluation_interval"],
      "checkpoint_sha256": result.get("checkpoint_sha256"),
      "semantic_result_sha256": result["semantic_result_sha256"]}
  for field in PRIMARY_FIELDS:
    row[field] = metrics[field]
  for delta in (64, 256, 1024):
    early = metrics["early_reuse"]["windows"][str(delta)]
    row["early_reuse_{}_count".format(delta)] = early["early_reuse_count"]
    row["early_reuse_{}_rate".format(delta)] = early["rate"]
  row["wasted_demotion_count"] = metrics["early_reuse"]["wasted_demotion_count"]
  return row


def _policy_record(track: str, workload: str, policy: str,
                   rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  values = {}
  for field in PRIMARY_FIELDS:
    samples = [float(row[field]) for row in rows]
    values[field] = _mean(samples)
    values[field + "_sample_std"] = _sample_std(samples)
  return {
      "track": track, "workload": workload, "policy": policy,
      "seed_count": len(rows), "seeds": [row["seed"] for row in rows],
      "metrics": values}


def _track_macro(raw: Sequence[Mapping[str, Any]], track: str) -> Dict[str, Any]:
  track_rows = [row for row in raw if row["track"] == track]
  workloads = (contract.STANDARD_WORKLOADS if track == "standard" else
               contract.PRESSURE_WORKLOADS)
  policies = {}
  for policy in contract.FORMAL_POLICIES:
    cells = []
    for workload in workloads:
      samples = [float(row["weighted_cost"]) for row in track_rows
                 if row["workload"] == workload and row["policy"] == policy]
      cells.append(_mean(samples))
    policies[policy] = {
        "cell_count": len(cells), "macro_mean_weighted_cost": _mean(cells)}
  return {
      "track": track, "job_count": len(track_rows),
      "cell_count": len(workloads), "workloads": list(workloads),
      "policies": policies}


def aggregate(results: Sequence[Mapping[str, Any]],
              config: Mapping[str, Any]) -> Dict[str, Any]:
  contract.validate_config(config)
  if len(results) != 80 or len({row["job_id"] for row in results}) != 80:
    raise contract.Stage8ContractError("Aggregation requires 80 unique jobs.")
  fairness = fairness_audit(results)
  raw = [_metric_row(row) for row in results]
  by_cell_policy = collections.defaultdict(list)
  for row in raw:
    by_cell_policy[(row["track"], row["workload"], row["policy"])].append(row)
  table_a = []
  table_b = []
  capd_vs_tpp = []
  proactive_vs_reactive = []
  oracle_headroom = []
  cell_keys = sorted({(row["track"], row["workload"]) for row in raw})
  for track, workload in cell_keys:
    aggregated = {}
    for policy in contract.FORMAL_POLICIES:
      record = _policy_record(
          track, workload, policy, by_cell_policy[(track, workload, policy)])
      aggregated[policy] = record
      if policy in contract.COMPARISON_A:
        table_a.append(record)
      if policy in contract.COMPARISON_B:
        table_b.append(record)
    capd = aggregated["capd"]["metrics"]["weighted_cost"]
    tpp = aggregated["tpp_inspired"]["metrics"]["weighted_cost"]
    reactive = aggregated["reactive_lru"]["metrics"]["weighted_cost"]
    proactive = aggregated["proactive_lru"]["metrics"]["weighted_cost"]
    oracle = aggregated["oracle"]["metrics"]["weighted_cost"]
    capd_vs_tpp.append({
        "track": track, "workload": workload,
        "capd_mean_weighted_cost": capd, "tpp_weighted_cost": tpp,
        "capd_minus_tpp": capd - tpp,
        "relative_improvement": (tpp - capd) / tpp if tpp else 0.0})
    proactive_vs_reactive.append({
        "track": track, "workload": workload,
        "proactive_lru_weighted_cost": proactive,
        "reactive_lru_weighted_cost": reactive,
        "proactive_minus_reactive": proactive - reactive,
        "relative_improvement": (
            (reactive - proactive) / reactive if reactive else 0.0)})
    oracle_headroom.append({
        "track": track, "workload": workload,
        "capd_mean_weighted_cost": capd, "oracle_weighted_cost": oracle,
        "capd_minus_oracle": capd - oracle})
  statistics_config = config["statistics"]
  bootstrap = {}
  conclusions = {}
  for track, expected_count in (("standard", 6), ("pressure", 4)):
    paired = [row for row in capd_vs_tpp if row["track"] == track]
    if len(paired) != expected_count:
      raise contract.Stage8ContractError("Track cell count changed: " + track)
    absolute = [row["capd_minus_tpp"] for row in paired]
    relative = [row["relative_improvement"] for row in paired]
    bootstrap[track] = {
        "capd_minus_tpp_weighted_cost": bootstrap_ci(
            absolute, statistics_config["bootstrap_seed"],
            statistics_config["bootstrap_resamples"]),
        "capd_relative_improvement_vs_tpp": bootstrap_ci(
            relative, statistics_config["bootstrap_seed"],
            statistics_config["bootstrap_resamples"])}
    ci = bootstrap[track]["capd_minus_tpp_weighted_cost"]
    conclusions[track] = {
        "cell_count": expected_count,
        "capd_lower_cost": sum(value < 0 for value in absolute),
        "equal_cost": sum(value == 0 for value in absolute),
        "capd_higher_cost": sum(value > 0 for value in absolute),
        "mean_relative_improvement_vs_tpp": _mean(relative),
        "bootstrap_ci_direction": (
            "capd_lower_weighted_cost" if ci["upper"] < 0 else
            "capd_higher_weighted_cost" if ci["lower"] > 0 else
            "ci_includes_zero_no_single_direction_claim")}
  track_macros = {
      track: _track_macro(raw, track) for track in contract.TRACKS}
  return {
      "schema_version": contract.AGGREGATE_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "status": "aggregated_awaiting_independent_verification",
      "job_count": 80, "cell_count": 10,
      "standard_job_count": 48, "pressure_job_count": 32,
      "standard_cell_count": 6, "pressure_cell_count": 4,
      "table_A": table_a, "table_B": table_b,
      "per_workload_raw": raw, "capd_vs_tpp_paired": capd_vs_tpp,
      "proactive_lru_vs_reactive_lru_paired": proactive_vs_reactive,
      "oracle_headroom": oracle_headroom,
      "bootstrap_95ci": bootstrap, "track_macros": track_macros,
      "structural_zero_standard": [{
          "track": "standard", "workload": workload,
          "status": "retained_and_reported_not_deleted"}
          for workload in contract.STRUCTURAL_ZERO_STANDARD_WORKLOADS],
      "pressure_unavailable_workloads": list(
          contract.STRUCTURAL_ZERO_STANDARD_WORKLOADS),
      "performance_conclusion_by_track": conclusions,
      "fairness": fairness, "statistics_contract": config["statistics"],
      "test_used_for_parameter_selection": False,
      "tracks_are_not_independent_seeds": True,
      "interpretation_boundary": config["interpretation_boundary"]}


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]]) -> None:
  fields = sorted({key for row in rows for key in row})
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix=".stage8-", suffix=".csv",
                                   dir=directory)
  os.close(fd)
  try:
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
      writer.writeheader()
      for row in rows:
        writer.writerow(row)
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def markdown_report(aggregate_value: Mapping[str, Any]) -> str:
  lines = [
      "# CAPD Stage 8 formal synchronous Replay report", "",
      "Status: aggregated; independent verification is still required.", "",
      "Standard contains 6 workloads and Pressure contains 4 workloads.",
      "streamcluster_pressure and fluidanimate have no Pressure Test; both remain in Standard.",
      "Structural-zero Validation does not permit deleting a Standard workload.", ""]
  for track in contract.TRACKS:
    macro = aggregate_value["track_macros"][track]
    ci = aggregate_value["bootstrap_95ci"][track][
        "capd_minus_tpp_weighted_cost"]
    lines.extend([
        "## {} macro".format(track.title()), "",
        "Cells: {}; jobs: {}.".format(macro["cell_count"], macro["job_count"]),
        "CAPD minus TPP weighted-cost mean: {:.6f}; 95% percentile bootstrap CI: [{:.6f}, {:.6f}].".format(
            ci["estimate"], ci["lower"], ci["upper"]), ""])
  lines.extend([
      "## Interpretation boundary", "", aggregate_value["interpretation_boundary"],
      "Standard and Pressure are trace tracks, not independent seeds, and are not combined into one primary macro.",
      "Synchronous replay cannot establish asynchronous background execution, real foreground latency, CPU overhead, or memory overhead.", ""])
  return "\n".join(lines)
