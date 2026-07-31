# coding=utf-8
"""Single-source Stage-8 aggregation, fairness, and frozen statistics."""

from __future__ import annotations

import collections
import csv
import json
import math
import os
import random
import statistics
import tempfile
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from qmap import proactive_stage8_contract as contract


PRIMARY_FIELDS = (
    "weighted_cost", "weighted_cost_per_access", "dram_hits", "nvm_reads",
    "nvm_writes", "total_demotions", "proactive_demotions",
    "emergency_demotions", "fallback_rate", "minimum_free_frames",
    "average_free_frames")


def _mean(values: Sequence[float]) -> float:
  return sum(float(v) for v in values) / float(len(values))


def _sample_std(values: Sequence[float]) -> float:
  return statistics.stdev(float(v) for v in values) if len(values) > 1 else 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
  ordered = sorted(float(v) for v in values)
  position = (len(ordered) - 1) * probability
  low = int(position)
  high = min(low + 1, len(ordered) - 1)
  return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_ci(values: Sequence[float], seed: int, resamples: int,
                 confidence: float = 0.95) -> Dict[str, Any]:
  if not values or resamples <= 0:
    raise contract.Stage8ContractError("Bootstrap requires values/resamples.")
  rng = random.Random(int(seed))
  n = len(values)
  draws = []
  for _ in range(int(resamples)):
    draws.append(_mean([values[rng.randrange(n)] for __ in range(n)]))
  alpha = (1.0 - float(confidence)) / 2.0
  return {
      "estimate": _mean(values), "lower": _percentile(draws, alpha),
      "upper": _percentile(draws, 1.0 - alpha),
      "confidence_level": confidence, "method": "percentile_bootstrap",
      "seed": int(seed), "resamples": int(resamples),
      "resampling_unit": "workload_capacity_cell", "cell_count": n}


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
    by_cell[(row["workload"], row["capacity_ratio"])].append(row)
  if len(by_cell) != 18:
    raise contract.Stage8ContractError("Fairness requires 18 cells.")
  audits = []
  candidate_by_state = collections.defaultdict(set)
  for cell, rows in sorted(by_cell.items()):
    by_policy = collections.defaultdict(list)
    for row in rows:
      by_policy[row["policy"]].append(row)
    if set(by_policy) != set(contract.FORMAL_POLICIES):
      raise contract.Stage8ContractError("Cell policy membership is incomplete.")
    if len(by_policy["capd"]) != 3 or any(
        len(by_policy[p]) != 1 for p in contract.DETERMINISTIC_POLICIES):
      raise contract.Stage8ContractError("Seed/deterministic cardinality changed.")
    all_rows = rows
    _same(all_rows, (
        "test_identity", "trace_sha256", "trace_range",
        "dram_capacity_pages", "initial_state_sha256", "cost_profile",
        "page_enter_dram_semantics"), "cell-common")
    active = [row for row in rows if row["policy"] in contract.COMPARISON_A]
    _same(active, (
        "F_low", "F_target", "candidate_size_K", "b_max", "b_t_rule",
        "candidate_source", "fallback_policy", "trigger_mode",
        "candidate_contract_sha256"), "Experiment A")
    for result in active:
      for decision in result.get("rounds", []):
        candidate_by_state[decision["candidate_state_sha256"]].add(
            decision["candidate_pages_sha256"])
    b_rows = [by_policy["reactive_lru"][0], by_policy["proactive_lru"][0]]
    _same(b_rows, (
        "test_identity", "trace_sha256", "trace_range",
        "dram_capacity_pages", "initial_state_sha256", "cost_profile",
        "page_enter_dram_semantics"), "Experiment B")
    audits.append({
        "workload": cell[0], "capacity_ratio": cell[1],
        "experiment_A": "passed", "experiment_B": "passed",
        "candidate_contract":
            "same_constructor_and_exact_for_identical_predecision_state",
        "expected_B_difference":
            "reactive_on_demand_vs_low_watermark_reserve"})
  if any(len(values) != 1 for values in candidate_by_state.values()):
    raise contract.Stage8ContractError(
        "Identical pre-decision state produced different candidates.")
  return {"status": "passed", "cell_count": 18, "cells": audits,
          "equal_predecision_state_candidate_identity": "passed",
          "test_used_for_parameter_selection": False}


def _metric_row(result: Mapping[str, Any]) -> Dict[str, Any]:
  metrics = result["metrics"]
  row = {
      "job_id": result["job_id"], "workload": result["workload"],
      "workload_role": result["workload_role"],
      "capacity_ratio": result["capacity_ratio"],
      "dram_pages": result["dram_capacity_pages"],
      "policy": result["policy"], "seed": result["seed"],
      "semantic_result_sha256": result["semantic_result_sha256"]}
  for field in PRIMARY_FIELDS:
    row[field] = metrics[field]
  for delta in (64, 256, 1024):
    early = metrics["early_reuse"]["windows"][str(delta)]
    row["early_reuse_{}_count".format(delta)] = early["early_reuse_count"]
    row["early_reuse_{}_rate".format(delta)] = early["rate"]
  row["wasted_demotion_count"] = metrics["early_reuse"]["wasted_demotion_count"]
  return row


def aggregate(results: Sequence[Mapping[str, Any]],
              config: Mapping[str, Any]) -> Dict[str, Any]:
  contract.validate_config(config)
  if len(results) != 144 or len({row["job_id"] for row in results}) != 144:
    raise contract.Stage8ContractError("Aggregation requires 144 unique jobs.")
  fairness = fairness_audit(results)
  raw = [_metric_row(row) for row in results]
  by_cell_policy = collections.defaultdict(list)
  for row in raw:
    by_cell_policy[(row["workload"], row["capacity_ratio"],
                    row["policy"])].append(row)
  table_a = []
  table_b = []
  paired = []
  best_descriptive = []
  cell_keys = sorted({(row["workload"], row["capacity_ratio"])
                      for row in raw})
  for workload, ratio in cell_keys:
    aggregated_policy = {}
    for policy in contract.FORMAL_POLICIES:
      rows = by_cell_policy[(workload, ratio, policy)]
      values = {}
      for field in PRIMARY_FIELDS:
        samples = [float(row[field]) for row in rows]
        values[field] = _mean(samples)
        values[field + "_sample_std"] = _sample_std(samples)
      record = {
          "workload": workload, "capacity_ratio": ratio, "policy": policy,
          "seed_count": len(rows), "metrics": values,
          "seeds": [row["seed"] for row in rows]}
      aggregated_policy[policy] = record
      if policy in contract.COMPARISON_A:
        table_a.append(record)
      if policy in contract.COMPARISON_B:
        table_b.append(record)
    capd = aggregated_policy["capd"]["metrics"]["weighted_cost"]
    tpp = aggregated_policy["tpp_inspired"]["metrics"]["weighted_cost"]
    delta = capd - tpp
    paired.append({
        "workload": workload, "capacity_ratio": ratio,
        "capd_mean_weighted_cost": capd, "tpp_weighted_cost": tpp,
        "capd_minus_tpp": delta,
        "relative_improvement": (tpp - capd) / tpp if tpp else 0.0})
    candidates = [aggregated_policy[p] for p in (
        "proactive_lru", "proactive_clock", "tpp_inspired")]
    best = min(candidates, key=lambda row: (
        row["metrics"]["weighted_cost"], row["policy"]))
    best_cost = best["metrics"]["weighted_cost"]
    best_descriptive.append({
        "workload": workload, "capacity_ratio": ratio,
        "predeclared_candidate_set": [
            "proactive_lru", "proactive_clock", "tpp_inspired"],
        "best_non_oracle_baseline": best["policy"],
        "best_non_oracle_weighted_cost": best_cost,
        "capd_mean_weighted_cost": capd,
        "capd_relative_improvement":
            (best_cost - capd) / best_cost if best_cost else 0.0})
  statistics_config = config["statistics"]
  absolute = [row["capd_minus_tpp"] for row in paired]
  relative = [row["relative_improvement"] for row in paired]
  bootstrap = {
      "capd_minus_tpp_weighted_cost": bootstrap_ci(
          absolute, statistics_config["bootstrap_seed"],
          statistics_config["bootstrap_resamples"]),
      "capd_relative_improvement_vs_tpp": bootstrap_ci(
          relative, statistics_config["bootstrap_seed"],
          statistics_config["bootstrap_resamples"])}
  direction = {
      "capd_lower_cost": sum(row["capd_minus_tpp"] < 0 for row in paired),
      "equal_cost": sum(row["capd_minus_tpp"] == 0 for row in paired),
      "capd_higher_cost": sum(row["capd_minus_tpp"] > 0 for row in paired)}
  mechanism = []
  for workload, ratio in cell_keys:
    reactive = by_cell_policy[(workload, ratio, "reactive_lru")][0][
        "weighted_cost"]
    proactive = by_cell_policy[(workload, ratio, "proactive_lru")][0][
        "weighted_cost"]
    mechanism.append({
        "workload": workload, "capacity_ratio": ratio,
        "proactive_minus_reactive": proactive - reactive,
        "relative_improvement":
            (reactive - proactive) / reactive if reactive else 0.0})
  absolute_ci = bootstrap["capd_minus_tpp_weighted_cost"]
  ci_direction = (
      "capd_lower_weighted_cost" if absolute_ci["upper"] < 0 else
      "capd_higher_weighted_cost" if absolute_ci["lower"] > 0 else
      "ci_includes_zero_no_single_direction_claim")
  roles = {
      "seen_calibration_workloads": set((
          "canneal", "streamcluster_pressure", "dedup_pressure")),
      "held_out_unseen_workloads": set((
          "blackscholes", "swaptions", "fluidanimate")),
      "all_workloads_macro": set(row["workload"] for row in raw)}
  groups = {}
  for name, workloads in roles.items():
    groups[name] = {}
    for policy in contract.FORMAL_POLICIES:
      rows = [row for row in raw
              if row["workload"] in workloads and row["policy"] == policy]
      # CAPD is first averaged within each cell, preventing seed pseudo-replication.
      cells = collections.defaultdict(list)
      for row in rows:
        cells[(row["workload"], row["capacity_ratio"])].append(
            float(row["weighted_cost"]))
      values = [_mean(cell) for cell in cells.values()]
      groups[name][policy] = {
          "cell_count": len(values),
          "macro_mean_weighted_cost": _mean(values) if values else None}
  return {
      "schema_version": contract.AGGREGATE_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "status": "aggregated_awaiting_independent_verification",
      "job_count": 144, "cell_count": 18,
      "table_A": table_a, "table_B": table_b,
      "per_workload_raw": raw,
      "capd_vs_tpp_paired": paired, "bootstrap_95ci": bootstrap,
      "proactive_lru_vs_reactive_lru_paired": mechanism,
      "best_non_oracle_descriptive": best_descriptive,
      "groups": groups, "fairness": fairness,
      "statistics_contract": config["statistics"],
      "test_used_for_parameter_selection": False,
      "performance_conclusion": {
          "type": "predeclared_descriptive_not_parameter_selection",
          "primary_metric": "weighted_cost",
          "capd_vs_tpp_cell_directions": direction,
          "bootstrap_ci_direction": ci_direction,
          "mean_relative_improvement_vs_tpp": _mean(relative),
          "proactive_lru_vs_reactive_lru_cell_directions": {
              "proactive_lower_cost": sum(
                  row["proactive_minus_reactive"] < 0 for row in mechanism),
              "equal_cost": sum(
                  row["proactive_minus_reactive"] == 0 for row in mechanism),
              "proactive_higher_cost": sum(
                  row["proactive_minus_reactive"] > 0 for row in mechanism)},
          "interpretation_rule":
              "combine_18_paired_deltas_ci_workload_directions_and_effect_size"},
      "interpretation_boundary": config["interpretation_boundary"]}


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]]) -> None:
  fields = sorted({key for row in rows for key in row})
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix=".stage8-", suffix=".csv", dir=directory)
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
      "# CAPD 主动降级 Stage 8 正式同步 Replay 报告", "",
      "状态：聚合完成，须以独立 verification 为最终门禁。", "",
      "本报告与 JSON/CSV 来自同一份已审计聚合对象；Test 未用于参数选择。", "",
      "## 表 A：统一主动机制下的页面选择", "",
      "| Workload | 容量 | 方法 | weighted cost（mean ± sample std） |",
      "|---|---:|---|---:|"]
  for row in aggregate_value["table_A"]:
    metric = row["metrics"]
    lines.append("| {} | {} | {} | {:.6f} ± {:.6f} |".format(
        row["workload"], row["capacity_ratio"], row["policy"],
        metric["weighted_cost"], metric["weighted_cost_sample_std"]))
  lines.extend(["", "## 表 B：主动储备机制对照", "",
                "| Workload | 容量 | 方法 | weighted cost | fallback rate |",
                "|---|---:|---|---:|---:|"])
  for row in aggregate_value["table_B"]:
    metric = row["metrics"]
    lines.append("| {} | {} | {} | {:.6f} | {:.6f} |".format(
        row["workload"], row["capacity_ratio"], row["policy"],
        metric["weighted_cost"], metric["fallback_rate"]))
  ci = aggregate_value["bootstrap_95ci"]["capd_minus_tpp_weighted_cost"]
  conclusion = aggregate_value["performance_conclusion"]
  lines.extend([
      "", "## 预声明配对统计", "",
      "CAPD 三 seed 先在每个 workload×capacity 单元内取均值，再与 TPP-inspired 配对。",
      "18 单元 CAPD−TPP weighted cost 的均值为 {:.6f}，95% percentile bootstrap CI 为 [{:.6f}, {:.6f}]（seed={}，{} 次）。".format(
          ci["estimate"], ci["lower"], ci["upper"], ci["seed"], ci["resamples"]),
      "逐单元方向：CAPD 较低 {} 个、相同 {} 个、较高 {} 个；预声明 CI 判定为 `{}`，平均相对改善为 {:.6%}。".format(
          conclusion["capd_vs_tpp_cell_directions"]["capd_lower_cost"],
          conclusion["capd_vs_tpp_cell_directions"]["equal_cost"],
          conclusion["capd_vs_tpp_cell_directions"]["capd_higher_cost"],
          conclusion["bootstrap_ci_direction"],
          conclusion["mean_relative_improvement_vs_tpp"]),
      "该描述同时保留逐 workload 方向、CI 与效应量，不依据单一 p-value 或总体均值下结论。",
      "", "## 解释边界", "", aggregate_value["interpretation_boundary"],
      "fallback 很少或为零仅说明同步功能正确性环境中的观察，不能外推到异步系统。",
      "Stage 8 不包含 Stage 9 的真实 CPU、内存或推理开销测量。", ""])
  return "\n".join(lines)
