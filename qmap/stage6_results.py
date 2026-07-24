# coding=utf-8
"""Pure-Python validation and summarization helpers for CAPD stage 6."""

from __future__ import print_function

import math

from qmap import stage5_results
from qmap import stage6_variants


COST_PROFILES = {
    "official": {
        "dram_read_cost": 1.0, "dram_write_cost": 1.0,
        "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
        "migration_cost": 10.0},
    "write_cost_low": {
        "dram_read_cost": 1.0, "dram_write_cost": 1.0,
        "nvm_read_cost": 2.0, "nvm_write_cost": 4.0,
        "migration_cost": 10.0},
    "write_cost_high": {
        "dram_read_cost": 1.0, "dram_write_cost": 1.0,
        "nvm_read_cost": 2.0, "nvm_write_cost": 16.0,
        "migration_cost": 10.0},
    "migration_cost_high": {
        "dram_read_cost": 1.0, "dram_write_cost": 1.0,
        "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
        "migration_cost": 20.0},
}

REQUIRED_PROFILE_COMPONENTS = (
    "selector", "tensor_and_embedding", "transformer_encoder",
    "cross_attention_scorer", "victim_selection", "full_decision")
CLASSIC_POLICIES = ("random", "lru", "lfu", "clock")


def require(condition, message):
  if not condition:
    raise ValueError(message)


def quantile(values, probability):
  values = sorted(float(value) for value in values)
  require(values, "Cannot summarize an empty sample.")
  require(all(math.isfinite(value) and value >= 0.0 for value in values),
          "Samples must be finite and non-negative.")
  if len(values) == 1:
    return values[0]
  position = (len(values) - 1) * float(probability)
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  fraction = position - lower
  return (values[lower] * (1.0 - fraction) +
          values[upper] * fraction)


def sample_summary(values):
  values = [float(value) for value in values]
  require(values, "Cannot summarize an empty sample.")
  require(all(math.isfinite(value) and value >= 0.0 for value in values),
          "Samples must be finite and non-negative.")
  return {
      "count": len(values),
      "mean": sum(values) / float(len(values)),
      "min": min(values),
      "p50": quantile(values, 0.50),
      "p95": quantile(values, 0.95),
      "p99": quantile(values, 0.99),
      "max": max(values),
  }


def reweighted_cost(row, profile):
  """Reweights counters without rerunning or retraining a policy."""
  require(profile["dram_read_cost"] == profile["dram_write_cost"],
          "Counter-only reweighting requires equal DRAM read/write costs.")
  hits = int(row["hits"])
  misses = int(row["misses"])
  reads = int(row["nvm_reads"])
  writes = int(row["nvm_writes"])
  migrations = int(row["migrations"])
  require(misses == reads + writes, "NVM read/write counters do not sum.")
  require(int(row["total_accesses"]) == hits + misses,
          "Hit/miss counters do not sum.")
  return (
      hits * float(profile["dram_read_cost"]) +
      reads * float(profile["nvm_read_cost"]) +
      writes * float(profile["nvm_write_cost"]) +
      migrations * float(profile["migration_cost"]))


def summarize_cost_robustness(main_rows):
  """Builds workload/profile comparisons from Stage-5 official counters."""
  rows = []
  summary = {"status": "SUMMARIZED", "profiles": {}}
  for profile_name, profile in sorted(COST_PROFILES.items()):
    profile_summary = {}
    for workload in stage6_variants.WORKLOADS:
      workload_rows = [
          dict(row) for row in main_rows
          if row["workload"] == workload and
          str(row["policy"]).lower() in ("qmap",) + CLASSIC_POLICIES]
      require(workload_rows, "Missing Stage-5 rows for {}".format(workload))
      policies = {}
      for row in workload_rows:
        require(row.get("artifact_class") == "official",
                "Cost robustness accepts only official rows.")
        require(row.get("test_used_for_selection") is False,
                "Cost robustness cannot use test for selection.")
        policy = str(row["policy"]).lower()
        value = reweighted_cost(row, profile)
        policies.setdefault(policy, []).append(value)
        rows.append({
            "profile": profile_name, "workload": workload,
            "policy": policy, "model_seed": row.get("model_seed"),
            "replay_seed": row.get("replay_seed"),
            "reweighted_cost": value,
        })
      require("qmap" in policies, "Missing QMAP cost rows.")
      require(len(policies["qmap"]) == 3,
              "Cost robustness requires three QMAP seeds.")
      require(len(policies.get("random", [])) == 3,
              "Cost robustness requires three Random seeds.")
      for policy in ("lru", "lfu", "clock"):
        require(len(policies.get(policy, [])) == 1,
                "Cost robustness requires one {} row.".format(policy))
      qmap = stage5_results.sample_summary(policies["qmap"])
      external = {
          policy: stage5_results.sample_summary(values)
          for policy, values in policies.items() if policy != "qmap"}
      require(external, "Missing external cost baseline.")
      best_policy = min(
          external, key=lambda policy: external[policy]["mean"])
      best_cost = external[best_policy]["mean"]
      profile_summary[workload] = {
          "qmap": qmap,
          "external": external,
          "best_external_policy": best_policy,
          "best_external_cost": best_cost,
          "capd_improvement_percent":
              stage5_results.improvement_percent(best_cost, qmap["mean"]),
      }
    summary["profiles"][profile_name] = {
        "cost_model": dict(profile), "workloads": profile_summary}
  summary["rows"] = rows
  return summary


def validate_profile_result(row):
  require(row.get("artifact_class") == "official",
          "Stage-6 profile accepts only official artifacts.")
  require(row.get("test_used_for_selection") is False,
          "Stage-6 profile must not use test for selection.")
  profile = row.get("stage6_profile")
  require(isinstance(profile, dict), "Missing stage6_profile.")
  require(profile.get("measured_decisions", 0) > 0,
          "Profile has no post-warmup decisions.")
  for key in ("replay_wall_seconds", "throughput_accesses_per_second"):
    value = float(row[key])
    require(math.isfinite(value) and value >= 0.0,
            "{} must be finite and non-negative.".format(key))
  samples = profile.get("samples_ms", {})
  require("full_decision" in samples, "Missing full-decision samples.")
  measured = int(profile["measured_decisions"])
  require(len(samples["full_decision"]) == measured,
          "Full-decision sample count does not match measured_decisions.")
  if str(row.get("policy")).lower() == "qmap":
    for component in REQUIRED_PROFILE_COMPONENTS:
      require(component in samples,
              "Missing QMAP profile component: {}".format(component))
      require(len(samples[component]) == measured,
              "QMAP component sample count mismatch: {}".format(component))
  memory = profile.get("memory", {})
  for key in (
      "model_parameter_bytes", "model_buffer_bytes", "model_static_bytes",
      "process_peak_rss_bytes", "cuda_peak_allocated_bytes",
      "cuda_peak_reserved_bytes"):
    require(key in memory, "Missing memory field: {}".format(key))
    if memory[key] is not None:
      require(float(memory[key]) >= 0.0,
              "Memory fields must be non-negative.")
  for key in ("device", "cuda_device_name", "torch_version"):
    require(key in memory, "Missing runtime identity field: {}".format(key))
  return row


def summarize_profiles(profile_rows, require_qmap_cuda=False):
  """Aggregates raw timing samples across runs without averaging percentiles."""
  grouped = {}
  memory_rows = []
  throughput_rows = []
  for row in profile_rows:
    validate_profile_result(row)
    if (require_qmap_cuda and
        str(row.get("policy")).lower() == "qmap"):
      memory = row["stage6_profile"]["memory"]
      require(str(memory.get("device", "")).startswith("cuda"),
              "Formal QMAP profiling must run on CUDA.")
      require(bool(memory.get("cuda_device_name")),
              "Formal QMAP profiling is missing the CUDA device name.")
      require(bool(memory.get("torch_version")),
              "Formal QMAP profiling is missing the PyTorch version.")
      require(int(memory.get("cuda_peak_allocated_bytes", 0)) > 0,
              "Formal QMAP profiling is missing CUDA allocation evidence.")
    key = (row["workload"], str(row["policy"]).lower())
    target = grouped.setdefault(key, {})
    for component, values in row["stage6_profile"]["samples_ms"].items():
      target.setdefault(component, []).extend(float(value) for value in values)
    memory = dict(row["stage6_profile"]["memory"])
    memory.update({
        "workload": row["workload"],
        "policy": str(row["policy"]).lower(),
        "model_seed": row.get("model_seed"),
        "replay_seed": row.get("replay_seed"),
    })
    memory_rows.append(memory)
    throughput_rows.append({
        "workload": row["workload"],
        "policy": str(row["policy"]).lower(),
        "model_seed": row.get("model_seed"),
        "replay_seed": row.get("replay_seed"),
        "replay_wall_seconds": float(row["replay_wall_seconds"]),
        "throughput_accesses_per_second": float(
            row["throughput_accesses_per_second"]),
        "migrations": int(row["migrations"]),
        "nvm_writes": int(row["nvm_writes"]),
    })
  summary = {"status": "SUMMARIZED", "workloads": {}}
  for (workload, policy), components in sorted(grouped.items()):
    workload_summary = summary["workloads"].setdefault(workload, {})
    workload_summary[policy] = {
        component: sample_summary(values)
        for component, values in sorted(components.items())}
  effect_summary = {}
  for workload in stage6_variants.WORKLOADS:
    selected = [
        row for row in throughput_rows if row["workload"] == workload]
    policies = {}
    for row in selected:
      policy = row["policy"]
      target = policies.setdefault(policy, {
          "throughput_accesses_per_second": [],
          "migrations": [], "nvm_writes": []})
      for metric in target:
        target[metric].append(float(row[metric]))
    require(len(policies.get("qmap", {}).get(
        "throughput_accesses_per_second", [])) == 3,
        "Profile requires three QMAP seeds for {}.".format(workload))
    require(len(policies.get("random", {}).get(
        "throughput_accesses_per_second", [])) == 3,
        "Profile requires three Random seeds for {}.".format(workload))
    for policy in ("lru", "lfu", "clock"):
      require(len(policies.get(policy, {}).get(
          "throughput_accesses_per_second", [])) == 1,
          "Profile requires one {} run for {}.".format(policy, workload))
    statistics = {
        policy: {
            metric: sample_summary(values)
            for metric, values in metrics.items()}
        for policy, metrics in policies.items()}
    qmap = statistics["qmap"]
    external = {
        policy: values for policy, values in statistics.items()
        if policy in CLASSIC_POLICIES}
    fastest_policy = max(
        external,
        key=lambda policy:
            external[policy]["throughput_accesses_per_second"]["mean"])
    fewest_migrations_policy = min(
        external,
        key=lambda policy: external[policy]["migrations"]["mean"])
    fewest_writes_policy = min(
        external,
        key=lambda policy: external[policy]["nvm_writes"]["mean"])
    fastest = external[fastest_policy][
        "throughput_accesses_per_second"]["mean"]
    fewest_migrations = external[fewest_migrations_policy][
        "migrations"]["mean"]
    fewest_writes = external[fewest_writes_policy]["nvm_writes"]["mean"]
    effect_summary[workload] = {
        "policies": statistics,
        "throughput_reference_policy": fastest_policy,
        "qmap_throughput_degradation_percent": (
            (fastest - qmap["throughput_accesses_per_second"]["mean"]) /
            fastest * 100.0 if fastest > 0.0 else None),
        "migration_reference_policy": fewest_migrations_policy,
        "qmap_migration_delta": (
            qmap["migrations"]["mean"] - fewest_migrations),
        "qmap_migration_change_percent": (
            (qmap["migrations"]["mean"] - fewest_migrations) /
            fewest_migrations * 100.0 if fewest_migrations > 0.0 else None),
        "nvm_write_reference_policy": fewest_writes_policy,
        "qmap_nvm_write_delta": (
            qmap["nvm_writes"]["mean"] - fewest_writes),
        "qmap_nvm_write_change_percent": (
            (qmap["nvm_writes"]["mean"] - fewest_writes) /
            fewest_writes * 100.0 if fewest_writes > 0.0 else None),
    }
  summary["effect_summary"] = effect_summary
  summary["memory_rows"] = memory_rows
  summary["throughput_rows"] = throughput_rows
  return summary


def summarize_capacity(capacity_rows):
  """Summarizes three-seed CAPD and same-capacity external baselines."""
  summary = {"status": "SUMMARIZED", "capacities": {}}
  for capacity in (64,) + tuple(stage6_variants.CAPACITIES):
    capacity_summary = {}
    for workload in stage6_variants.WORKLOADS:
      selected = [
          row for row in capacity_rows
          if int(row["dram_capacity"]) == capacity and
          row["workload"] == workload and
          str(row["policy"]).lower() in (
              "qmap", "random", "lru", "lfu", "clock")]
      require(selected, "Missing D={}/{} rows.".format(capacity, workload))
      policies = {}
      for row in selected:
        require(row.get("artifact_class") == "official",
                "Capacity summary accepts only official rows.")
        require(row.get("test_used_for_selection") is False,
                "Capacity test cannot be used for selection.")
        policy = str(row["policy"]).lower()
        policies.setdefault(policy, []).append(
            float(row["weighted_access_cost"]))
      require(len(policies.get("qmap", [])) == 3,
              "Capacity CAPD requires exactly three model seeds.")
      qmap = stage5_results.sample_summary(policies["qmap"])
      external = {
          policy: stage5_results.sample_summary(values)
          for policy, values in policies.items() if policy != "qmap"}
      best_policy = min(
          external, key=lambda policy: external[policy]["mean"])
      best_cost = external[best_policy]["mean"]
      capacity_summary[workload] = {
          "qmap": qmap, "external": external,
          "best_external_policy": best_policy,
          "best_external_cost": best_cost,
          "capd_improvement_percent":
              stage5_results.improvement_percent(best_cost, qmap["mean"]),
      }
    summary["capacities"][str(capacity)] = capacity_summary
  return summary


def summarize_natural_rw(data_reports, main_summary):
  """Cross-references natural test write ratios with Stage-5 outcomes."""
  rows = []
  main_rows = main_summary.get("rows", [])
  for workload in stage6_variants.WORKLOADS:
    report = data_reports[workload]
    require(report.get("status") == "PASSED",
            "Data report is not PASSED: {}".format(workload))
    rw = report["splits"]["test"]["read_write"]
    selected = [
        row for row in main_rows
        if row["workload"] == workload and
        str(row["policy"]).lower() in ("qmap",) + CLASSIC_POLICIES]
    policies = {}
    for row in selected:
      require(row.get("artifact_class") == "official",
              "Natural RW summary accepts only official rows.")
      require(row.get("test_used_for_selection") is False,
              "Natural RW summary cannot use test for selection.")
      policies.setdefault(str(row["policy"]).lower(), []).append(
          float(row["weighted_access_cost"]))
    require("qmap" in policies, "Missing QMAP row for {}".format(workload))
    require(all(policy in policies for policy in CLASSIC_POLICIES),
            "Missing classic baseline row for {}".format(workload))
    means = {
        policy: stage5_results.sample_summary(values)["mean"]
        for policy, values in policies.items()}
    best_policy = min(
        CLASSIC_POLICIES, key=lambda policy: means[policy])
    best_cost = means[best_policy]
    qmap_cost = means["qmap"]
    rows.append({
        "workload": workload,
        "read_ratio": float(rw["read_ratio"]),
        "write_ratio": float(rw["write_ratio"]),
        "rw_source": rw["rw_source"],
        "best_external_policy": best_policy,
        "capd_improvement_percent":
            stage5_results.improvement_percent(best_cost, qmap_cost),
        "interpretation": "descriptive_natural_workload_robustness",
    })
  return {
      "status": "SUMMARIZED",
      "controlled_rw_intervention": False,
      "interpretation_boundary": (
          "Natural workload ratios are descriptive and are not a causal "
          "read/write-ratio intervention."),
      "rows": rows,
  }
