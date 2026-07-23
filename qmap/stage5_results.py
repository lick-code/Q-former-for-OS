# coding=utf-8
"""Strict statistics and contamination gates for CAPD stage-5 results."""

from __future__ import print_function

import csv
import json
import math
import os
import statistics

from qmap import finals_config
from qmap import stage5_variants


REQUIRED_METRICS = (
    "total_accesses", "hits", "misses", "hit_rate", "nvm_reads",
    "nvm_writes", "migrations", "weighted_access_cost", "decision_count")
DETERMINISTIC_BASELINES = ("lru", "lfu", "clock")
REQUIRED_POLICIES = ("qmap", "lru", "random", "lfu", "clock")


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(path, value):
  finals_config.write_json(path, value)


def improvement_percent(baseline_cost, capd_cost):
  baseline_cost = float(baseline_cost)
  if baseline_cost <= 0.0:
    raise ValueError("baseline_cost must be positive.")
  return (baseline_cost - float(capd_cost)) / baseline_cost * 100.0


def sample_summary(values):
  values = [float(value) for value in values]
  if not values:
    raise ValueError("Cannot summarize an empty sample.")
  return {
      "count": len(values),
      "mean": statistics.mean(values),
      "sample_stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
      "min": min(values),
      "max": max(values),
      "values": values,
  }


def _policy(row):
  value = str(row.get("policy", "")).lower()
  return "qmap" if value in ("qmap", "capd") else value


def _run_seed(row):
  policy = _policy(row)
  if policy == "qmap":
    value = row.get("model_seed", row.get("seed"))
  else:
    value = row.get("replay_seed", row.get("random_seed"))
  return None if value is None else int(value)


def validate_result_row(row):
  missing = [key for key in REQUIRED_METRICS if key not in row]
  if missing:
    raise ValueError("Stage-5 result missing fields: {}".format(missing))
  if int(row["hits"]) + int(row["misses"]) != int(row["total_accesses"]):
    raise ValueError("Stage-5 hit/miss accounting mismatch.")
  if row.get("run_status") not in (None, "COMPLETED"):
    raise ValueError("Stage-5 result is not completed.")
  if row.get("test_used_for_selection") not in (None, False):
    raise ValueError("Stage-5 result reports test-based selection.")
  return row


def _require_same_binding(rows, keys, context):
  for key in keys:
    if any(key not in row or row[key] is None for row in rows):
      raise ValueError("{} missing required binding {}.".format(context, key))
    values = {finals_config.fingerprint_value(row.get(key)) for row in rows}
    if len(values) != 1:
      raise ValueError("{} binding differs for {}.".format(context, key))


def validate_main_fairness(rows):
  rows = [validate_result_row(dict(row)) for row in rows]
  for workload in stage5_variants.WORKLOADS:
    workload_rows = [
        row for row in rows if row.get("workload", row.get("workload_id")) ==
        workload]
    policies = {_policy(row) for row in workload_rows}
    missing = set(REQUIRED_POLICIES) - policies
    if missing:
      raise ValueError(
          "{} missing required policies: {}.".format(workload, sorted(missing)))
    _require_same_binding(
        workload_rows,
        ("test_trace_fingerprint", "cost_model", "dram_capacity",
         "dram_initial_state"),
        workload)
    capd = [row for row in workload_rows if _policy(row) == "qmap"]
    if sorted(_run_seed(row) for row in capd) != sorted(
        stage5_variants.MODEL_SEEDS):
      raise ValueError("{} must contain all three CAPD seeds.".format(workload))
    random_rows = [
        row for row in workload_rows if _policy(row) == "random"]
    if sorted(_run_seed(row) for row in random_rows) != list(
        stage5_variants.RANDOM_REPLAY_SEEDS):
      raise ValueError("{} must contain Random seeds 0,1,2.".format(workload))
    for policy in DETERMINISTIC_BASELINES:
      if len([row for row in workload_rows if _policy(row) == policy]) != 1:
        raise ValueError(
            "{} must contain one deterministic {} row.".format(
                workload, policy))
  return rows


def summarize_main(rows):
  rows = validate_main_fairness(rows)
  optional_policies = sorted({
      _policy(row) for row in rows
      if _policy(row) not in REQUIRED_POLICIES
  })
  included_optional = []
  excluded_optional = []
  for policy in optional_policies:
    counts = {
        workload: len([
            row for row in rows
            if row.get("workload", row.get("workload_id")) == workload and
            _policy(row) == policy])
        for workload in stage5_variants.WORKLOADS
    }
    if all(count == 1 for count in counts.values()):
      included_optional.append(policy)
    else:
      excluded_optional.append({
          "policy": policy, "reason": "incomplete_workload_coverage",
          "row_counts_by_workload": counts,
      })
  reported_policies = list(REQUIRED_POLICIES) + included_optional
  external_policies = [
      policy for policy in reported_policies if policy != "qmap"]
  workloads = {}
  flat_rows = []
  for workload in stage5_variants.WORKLOADS:
    current = [
        row for row in rows if row.get("workload", row.get("workload_id")) ==
        workload and _policy(row) in reported_policies]
    by_policy = {}
    for policy in reported_policies:
      policy_rows = [row for row in current if _policy(row) == policy]
      costs = [row["weighted_access_cost"] for row in policy_rows]
      by_policy[policy] = {
          "weighted_access_cost": sample_summary(costs),
          "runs": policy_rows,
      }
    capd_mean = by_policy["qmap"]["weighted_access_cost"]["mean"]
    improvements = {}
    for policy in external_policies:
      baseline = by_policy[policy]["weighted_access_cost"]["mean"]
      improvements[policy] = improvement_percent(baseline, capd_mean)
    best_policy = min(
        external_policies,
        key=lambda item: by_policy[item]["weighted_access_cost"]["mean"])
    best_cost = by_policy[best_policy]["weighted_access_cost"]["mean"]
    workloads[workload] = {
        "policies": by_policy,
        "capd_improvement_percent": improvements,
        "best_external_baseline": {
            "policy": best_policy,
            "weighted_access_cost": best_cost,
            "capd_minus_baseline": capd_mean - best_cost,
            "capd_improvement_percent": improvement_percent(
                best_cost, capd_mean),
        },
    }
    for row in current:
      output = dict(row)
      output["normalized_policy"] = _policy(row)
      output["run_seed"] = _run_seed(row)
      flat_rows.append(output)

  macro = {
      policy: statistics.mean(
          workloads[workload]["capd_improvement_percent"][policy]
          for workload in stage5_variants.WORKLOADS)
      for policy in external_policies
  }
  capd_total = sum(
      workloads[workload]["policies"]["qmap"]["weighted_access_cost"]["mean"]
      for workload in stage5_variants.WORKLOADS)
  micro = {}
  for policy in external_policies:
    baseline_total = sum(
        workloads[workload]["policies"][policy][
            "weighted_access_cost"]["mean"]
        for workload in stage5_variants.WORKLOADS)
    micro[policy] = {
        "capd_total_cost": capd_total,
        "baseline_total_cost": baseline_total,
        "improvement_percent": improvement_percent(
            baseline_total, capd_total),
    }
  return {
      "status": "SUMMARIZED",
      "primary_metric": "weighted_access_cost",
      "workloads": workloads,
      "macro_average_unweighted_improvement_percent": macro,
      "micro_total_cost_aggregation": micro,
      "included_optional_policies": included_optional,
      "excluded_optional_policies": excluded_optional,
      "rows": flat_rows,
      "statistical_test": None,
      "statistical_test_note": (
          "No significance test: three workloads are reported individually; "
          "model seeds are not treated as independent workload samples."),
  }


def paired_ablation_summary(full_rows, variant_rows, required_seeds=None):
  required_seeds = tuple(
      required_seeds or stage5_variants.MODEL_SEEDS)
  full_by_seed = {_run_seed(row): validate_result_row(row) for row in full_rows}
  variant_by_seed = {
      _run_seed(row): validate_result_row(row) for row in variant_rows}
  if set(full_by_seed) != set(required_seeds):
    raise ValueError("Full rows are missing a required paired seed.")
  if set(variant_by_seed) != set(required_seeds):
    raise ValueError("Variant rows are missing a required paired seed.")
  classes = {
      row.get("artifact_class") for row in list(full_by_seed.values()) +
      list(variant_by_seed.values())}
  if len(classes) != 1 or classes != {"official"}:
    raise ValueError("Official paired table cannot mix pilot artifacts.")
  deltas = []
  per_seed = []
  for seed in required_seeds:
    full_cost = float(full_by_seed[seed]["weighted_access_cost"])
    variant_cost = float(variant_by_seed[seed]["weighted_access_cost"])
    delta = variant_cost - full_cost
    deltas.append(delta)
    per_seed.append({
        "seed": seed, "full_cost": full_cost, "variant_cost": variant_cost,
        "variant_minus_full": delta,
        "variant_improvement_over_full_percent": improvement_percent(
            full_cost, variant_cost),
    })
  return {"per_seed": per_seed, "paired_delta": sample_summary(deltas)}


def summarize_sensitivity(rows):
  result = {}
  for row in rows:
    validate_result_row(row)
    variant_id = row["variant_id"]
    seed = _run_seed(row)
    item = result.setdefault(variant_id, {
        "rows": [], "single_seed_sensitivity": True,
        "needs_seed_confirmation": False})
    item["rows"].append(row)
    if row.get("needs_seed_confirmation") is True:
      item["needs_seed_confirmation"] = True
    if seed != 3136859:
      item["single_seed_sensitivity"] = False
  return {
      "status": "SUMMARIZED",
      "interpretation_boundary": (
          "Single-seed points are descriptive only. A point that changes a "
          "paper-level conclusion must set needs_seed_confirmation and add "
          "seeds 42 and 2026 before confirmation."),
      "variants": result,
  }


def write_csv(path, rows):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  rows = list(rows)
  fieldnames = sorted({key for row in rows for key in row})
  with open(path, "w", encoding="utf-8", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      writer.writerow({
          key: (json.dumps(value, sort_keys=True, ensure_ascii=False)
                if isinstance(value, (dict, list)) else value)
          for key, value in row.items()
      })


def assert_finite_summary(value):
  if isinstance(value, dict):
    for item in value.values():
      assert_finite_summary(item)
  elif isinstance(value, list):
    for item in value:
      assert_finite_summary(item)
  elif isinstance(value, float) and not math.isfinite(value):
    raise ValueError("Summary contains NaN or Inf.")
