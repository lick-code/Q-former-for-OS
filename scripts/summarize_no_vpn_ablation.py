# coding=utf-8
"""Summarize paired Full/NoVPN test-replay metrics across workloads/seeds."""

from __future__ import print_function

import argparse
import csv
import json
import math
import os
import statistics
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
SEEDS = (3136859, 42, 2026)
METRICS = (
    ("weighted_access_cost", "weighted cost"),
    ("hit_rate", "hit rate"),
    ("nvm_reads", "NVM reads"),
    ("nvm_writes", "NVM writes"),
    ("demotions", "demotions"),
    ("avg_decision_time_ms", "average decision time (ms)"),
)


def result_path(root, variant, workload, seed):
  return os.path.join(
      root, variant, workload, "seed_{}".format(seed), "qmap.json")


def load_pair(root, workload, seed):
  results = {}
  for variant in ("full", "no_vpn"):
    path = result_path(root, variant, workload, seed)
    if not os.path.exists(path):
      raise FileNotFoundError("Missing ablation result: {}".format(path))
    result = finals_config.load_json(path)
    if (result.get("variant") != variant or
        result.get("workload") != workload or
        int(result.get("seed", -1)) != int(seed)):
      raise ValueError("Result metadata mismatch: {}".format(path))
    results[variant] = result
  return results


def relative_delta(full, no_vpn):
  if full == 0.0:
    return None
  return (no_vpn - full) / full * 100.0


def per_seed_row(workload, seed, results):
  row = {"workload": workload, "seed": int(seed)}
  full = results["full"]
  no_vpn = results["no_vpn"]
  for key, _ in METRICS:
    full_value = float(full[key])
    no_vpn_value = float(no_vpn[key])
    row["full_{}".format(key)] = full_value
    row["no_vpn_{}".format(key)] = no_vpn_value
    row["{}_absolute_delta".format(key)] = no_vpn_value - full_value
    row["{}_relative_delta_percent".format(key)] = relative_delta(
        full_value, no_vpn_value)
  for variant, result in results.items():
    row["{}_best_epoch".format(variant)] = int(result["best_epoch"])
    row["{}_validation_metric".format(variant)] = float(
        result["validation_metric"]["value"])
    row["{}_training_time_seconds".format(variant)] = result.get(
        "training_time_seconds")
  return row


def descriptive(values):
  return {
      "mean": statistics.mean(values),
      "std": statistics.stdev(values) if len(values) > 1 else 0.0,
      "min": min(values),
      "max": max(values),
  }


def summarize(rows):
  output = []
  for workload in WORKLOADS:
    workload_rows = [row for row in rows if row["workload"] == workload]
    if not workload_rows:
      continue
    for key, label in METRICS:
      full_values = [row["full_{}".format(key)] for row in workload_rows]
      no_vpn_values = [
          row["no_vpn_{}".format(key)] for row in workload_rows]
      absolute = [
          row["{}_absolute_delta".format(key)] for row in workload_rows]
      relative = [
          row["{}_relative_delta_percent".format(key)]
          for row in workload_rows
          if row["{}_relative_delta_percent".format(key)] is not None]
      output.append({
          "workload": workload,
          "metric": key,
          "metric_label": label,
          "full": descriptive(full_values),
          "no_vpn": descriptive(no_vpn_values),
          "absolute_delta": descriptive(absolute),
          "relative_delta_percent": (
              descriptive(relative) if relative else None),
          "seed_count": len(workload_rows),
      })
  return output


def flatten_summary(row):
  flattened = {
      "workload": row["workload"],
      "metric": row["metric"],
      "metric_label": row["metric_label"],
      "seed_count": row["seed_count"],
  }
  for group in ("full", "no_vpn", "absolute_delta",
                "relative_delta_percent"):
    values = row[group]
    for statistic in ("mean", "std", "min", "max"):
      flattened["{}_{}".format(group, statistic)] = (
          values[statistic] if values is not None else "")
  return flattened


def write_csv(path, rows, fieldnames):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      writer.writerow({key: row.get(key, "") for key in fieldnames})


def format_value(value):
  if value is None:
    return "N/A"
  if isinstance(value, int):
    return str(value)
  if not math.isfinite(float(value)):
    return str(value)
  return "{:.6g}".format(float(value))


def write_report(path, rows, summary_rows, seeds):
  lookup = {(row["workload"], row["metric"]): row for row in summary_rows}
  lines = [
      "# CAPD NoVPN Ablation Report",
      "",
      "Primary evidence: paired test-trace replay metrics. Training loss is "
      "recorded only for checkpoint selection and is not the main conclusion.",
      "",
      "Seeds: `{}`. Standard deviation uses the sample definition (ddof=1)."
      .format(", ".join(str(seed) for seed in seeds)),
      "",
      "## Per-workload paired summary",
      "",
      "| workload | metric | Full mean | NoVPN mean | absolute delta | "
      "relative delta | direction |",
      "|---|---|---:|---:|---:|---:|---|",
  ]
  for workload in WORKLOADS:
    for key, label in METRICS:
      row = lookup.get((workload, key))
      if row is None:
        continue
      relative = row["relative_delta_percent"]
      relative_mean = relative["mean"] if relative else None
      if key == "weighted_access_cost":
        direction = (
            "positive: NoVPN has higher cost"
            if relative_mean is not None and relative_mean > 0 else
            "negative: NoVPN has lower cost"
            if relative_mean is not None and relative_mean < 0 else
            "no mean change")
      elif key == "hit_rate":
        direction = (
            "positive: NoVPN hit rate is higher"
            if relative_mean is not None and relative_mean > 0 else
            "negative: NoVPN hit rate is lower"
            if relative_mean is not None and relative_mean < 0 else
            "no mean change")
      else:
        direction = "NoVPN - Full"
      lines.append(
          "| {} | {} | {} | {} | {} | {}% | {} |".format(
              workload, label,
              format_value(row["full"]["mean"]),
              format_value(row["no_vpn"]["mean"]),
              format_value(row["absolute_delta"]["mean"]),
              format_value(relative_mean), direction))

  lines.extend([
      "",
      "## Interpretation framework",
      "",
      "Apply the following framework after reviewing the replay metrics; the "
      "report intentionally does not hard-code percentage thresholds.",
      "",
      "1. If NoVPN and Full are very close, the evidence suggests CAPD's gain "
      "mainly comes from PC, R/W, candidate state, and access context rather "
      "than absolute page identity.",
      "2. If NoVPN is clearly worse but still outperforms external baselines, "
      "absolute VPN is a useful auxiliary signal, but CAPD is not completely "
      "dependent on it.",
      "3. If NoVPN degrades to near or below external baselines, Full CAPD has "
      "a stronger within-run dependence on page identity and cross-run claims "
      "must be limited carefully.",
      "4. If NoVPN is better, absolute VPN embedding may introduce within-run "
      "overfitting.",
      "",
      "## Direction conventions",
      "",
      "- Every delta is `NoVPN - Full`.",
      "- Weighted-cost relative delta above zero means NoVPN is worse.",
      "- Hit-rate relative delta above zero means NoVPN has a higher hit rate.",
      "- NVM read/write, demotion, and decision-time deltas retain their direct "
      "numeric direction; interpret them jointly with weighted cost.",
      "",
      "## Artifact coverage",
      "",
      "- Per-seed paired rows: {}.".format(len(rows)),
      "- Workload/metric summary rows: {}.".format(len(summary_rows)),
  ])
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    output_file.write("\n".join(lines) + "\n")


def main():
  parser = argparse.ArgumentParser(
      description="Summarize CAPD Full/NoVPN paired replay results.")
  parser.add_argument(
      "--result-root", default="outputs/results/ablation_no_vpn")
  parser.add_argument(
      "--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
  parser.add_argument(
      "--seeds", nargs="+", type=int, default=list(SEEDS))
  args = parser.parse_args()
  result_root = os.path.abspath(args.result_root)
  rows = [
      per_seed_row(workload, seed, load_pair(result_root, workload, seed))
      for workload in args.workloads for seed in args.seeds
  ]
  summary_rows = summarize(rows)

  per_seed_path = os.path.join(
      result_root, "no_vpn_ablation_per_seed.csv")
  summary_csv_path = os.path.join(
      result_root, "no_vpn_ablation_summary.csv")
  summary_json_path = os.path.join(
      result_root, "no_vpn_ablation_summary.json")
  report_path = os.path.join(
      result_root, "no_vpn_ablation_report.md")
  per_seed_fields = ["workload", "seed"]
  for key, _ in METRICS:
    per_seed_fields.extend([
        "full_{}".format(key), "no_vpn_{}".format(key),
        "{}_absolute_delta".format(key),
        "{}_relative_delta_percent".format(key),
    ])
  for variant in ("full", "no_vpn"):
    per_seed_fields.extend([
        "{}_best_epoch".format(variant),
        "{}_validation_metric".format(variant),
        "{}_training_time_seconds".format(variant),
    ])
  write_csv(per_seed_path, rows, per_seed_fields)
  flat_summary = [flatten_summary(row) for row in summary_rows]
  summary_fields = list(flat_summary[0].keys()) if flat_summary else []
  write_csv(summary_csv_path, flat_summary, summary_fields)
  with open(summary_json_path, "w", encoding="utf-8", newline="\n") as output:
    json.dump({
        "schema_version": "capd_no_vpn_ablation_summary_1",
        "delta_definition": "no_vpn - full",
        "std_definition": "sample standard deviation, ddof=1",
        "workloads": list(args.workloads),
        "seeds": list(args.seeds),
        "per_seed": rows,
        "summary": summary_rows,
    }, output, indent=2, sort_keys=True, ensure_ascii=False)
    output.write("\n")
  write_report(report_path, rows, summary_rows, args.seeds)
  for path in (
      per_seed_path, summary_csv_path, summary_json_path, report_path):
    print("[done] {}".format(os.path.relpath(path, PROJECT_ROOT)))


if __name__ == "__main__":
  main()
