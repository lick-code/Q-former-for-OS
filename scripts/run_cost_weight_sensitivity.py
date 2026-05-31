# coding=utf-8
"""Replay-only cost-weight sensitivity summary.

This script does not retrain or rerun replay. It reads existing evaluation
JSON files and recomputes weighted cost from hits / NVM reads / NVM writes /
migrations under several cost models.

Default usage:

  python scripts/run_cost_weight_sensitivity.py
"""

import argparse
import csv
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

BASELINE_POLICIES = ("lru", "random", "lfu", "clock")
POLICIES = BASELINE_POLICIES + ("qmap",)

WORKLOADS = {
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "result_dir": "outputs/results/real_workload_suite_pressure/selected/parsec_streamcluster",
    },
    "blackscholes": {
        "display": "blackscholes",
        "result_dir": "outputs/results/real_workload_suite/1m/parsec_blackscholes",
    },
    "canneal": {
        "display": "canneal",
        "result_dir": "outputs/results/real_workload_suite/1m/parsec_canneal",
    },
}

COST_MODELS = (
    {
        "name": "default",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 8.0,
        "migration_cost": 10.0,
    },
    {
        "name": "mild",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 4.0,
        "migration_cost": 5.0,
    },
    {
        "name": "write-heavy",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 16.0,
        "migration_cost": 10.0,
    },
    {
        "name": "migration-heavy",
        "dram_access_cost": 1.0,
        "nvm_read_cost": 2.0,
        "nvm_write_cost": 8.0,
        "migration_cost": 20.0,
    },
)


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def reweighted_cost(result, cost_model):
  return (
      float(result["hits"]) * float(cost_model["dram_access_cost"]) +
      float(result["nvm_reads"]) * float(cost_model["nvm_read_cost"]) +
      float(result["nvm_writes"]) * float(cost_model["nvm_write_cost"]) +
      float(result["migrations"]) * float(cost_model["migration_cost"]))


def reweight_result(workload, cost_model, result):
  return {
      "workload": workload,
      "cost_model": cost_model["name"],
      "policy": result.get("policy", ""),
      "reweighted_cost": reweighted_cost(result, cost_model),
      "hits": int(result["hits"]),
      "nvm_reads": int(result["nvm_reads"]),
      "nvm_writes": int(result["nvm_writes"]),
      "migrations": int(result["migrations"]),
      "hit_rate_percent": float(result.get("hit_rate_percent", 0.0)),
      "decision_count": int(result.get("decision_count", 0)),
      "avg_decision_time_ms": float(result.get("avg_decision_time_ms", 0.0)),
  }


def best_baseline_row(policy_rows):
  baseline_rows = [
      row for row in policy_rows
      if row["policy"].lower() in BASELINE_POLICIES
  ]
  if not baseline_rows:
    raise ValueError("No baseline policy rows available.")
  return min(
      baseline_rows,
      key=lambda row: (
          row["reweighted_cost"],
          row["nvm_writes"],
          -row["hit_rate_percent"],
          row["policy"]))


def build_policy_rows(workload_results, cost_model):
  rows = []
  for workload, policy_results in workload_results.items():
    for policy in POLICIES:
      if policy not in policy_results:
        continue
      rows.append(reweight_result(workload, cost_model, policy_results[policy]))
  return rows


def build_summary_rows(workload_results, cost_models=COST_MODELS):
  rows = []
  for workload, policy_results in workload_results.items():
    if "qmap" not in policy_results:
      raise ValueError("Missing qmap result for workload: {}".format(workload))
    for cost_model in cost_models:
      policy_rows = [
          reweight_result(workload, cost_model, result)
          for result in policy_results.values()
      ]
      qmap_row = next(
          row for row in policy_rows if row["policy"].lower() == "qmap")
      baseline = best_baseline_row(policy_rows)
      baseline_cost = baseline["reweighted_cost"]
      if baseline_cost == 0.0:
        delta = 0.0
      else:
        delta = (
            qmap_row["reweighted_cost"] - baseline_cost) * 100.0 / baseline_cost
      rows.append({
          "cost_model": cost_model["name"],
          "workload": workload,
          "best_baseline_policy": baseline["policy"],
          "best_baseline_cost": baseline_cost,
          "qmap_cost": qmap_row["reweighted_cost"],
          "delta_percent": delta,
          "qmap_nvm_writes": qmap_row["nvm_writes"],
          "qmap_migrations": qmap_row["migrations"],
          "qmap_hit_rate_percent": qmap_row["hit_rate_percent"],
          "qmap_decision_count": qmap_row["decision_count"],
      })
  return rows


def selected_workloads(keys):
  if not keys:
    return tuple(WORKLOADS.keys())
  unknown = sorted(set(keys) - set(WORKLOADS.keys()))
  if unknown:
    raise ValueError("Unknown workload(s): {}".format(", ".join(unknown)))
  return tuple(keys)


def load_workload_results(workload_keys):
  missing = []
  results = {}
  for workload_key in workload_keys:
    config = WORKLOADS[workload_key]
    result_dir = path_from_root(*config["result_dir"].split("/"))
    policy_results = {}
    for policy in POLICIES:
      path = os.path.join(result_dir, "{}.json".format(policy))
      if not os.path.exists(path):
        missing.append(rel(path))
        continue
      policy_results[policy] = load_json(path)
    results[config["display"]] = policy_results
  if missing:
    raise FileNotFoundError(
        "Missing required result JSON(s):\n  {}".format("\n  ".join(missing)))
  return results


def write_csv(path, rows, fields):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def cost_model_table():
  lines = [
      "| Cost model | DRAM read/write | NVM read | NVM write | Migration |",
      "|---|---:|---:|---:|---:|",
  ]
  for model in COST_MODELS:
    lines.append(
        "| {name} | {dram:g} | {read:g} | {write:g} | {migration:g} |"
        .format(
            name=model["name"],
            dram=model["dram_access_cost"],
            read=model["nvm_read_cost"],
            write=model["nvm_write_cost"],
            migration=model["migration_cost"]))
  return "\n".join(lines)


def conclusion_for_workload(deltas):
  if all(delta < 0.0 for delta in deltas):
    return "QMAP-Pool beats the best baseline under every tested cost model."
  if all(delta > 0.0 for delta in deltas):
    return "QMAP-Pool remains worse than the best baseline under every tested cost model."
  return "The conclusion changes across cost models."


def write_markdown(path, summary_rows, policy_rows):
  by_workload = {}
  for row in summary_rows:
    by_workload.setdefault(row["workload"], []).append(row["delta_percent"])

  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    output_file.write("# Cost-weight Sensitivity\n\n")
    output_file.write(
        "Purpose: recompute weighted access cost from existing replay JSON "
        "counters without retraining or rerunning replay.\n\n")
    output_file.write("Formula:\n\n")
    output_file.write(
        "`cost = hits * dram_access_cost + nvm_reads * nvm_read_cost + "
        "nvm_writes * nvm_write_cost + migrations * migration_cost`\n\n")
    output_file.write("## Cost Models\n\n")
    output_file.write(cost_model_table())
    output_file.write("\n\n## QMAP vs Best Baseline\n\n")
    output_file.write(
        "| Cost model | streamcluster_pressure delta | blackscholes delta | "
        "canneal delta |\n")
    output_file.write("|---|---:|---:|---:|\n")
    workloads = [config["display"] for config in WORKLOADS.values()]
    for model in COST_MODELS:
      by_name = {
          row["workload"]: row
          for row in summary_rows
          if row["cost_model"] == model["name"]
      }
      output_file.write(
          "| {model} | {stream:+.2f}% | {black:+.2f}% | {canneal:+.2f}% |\n"
          .format(
              model=model["name"],
              stream=by_name[workloads[0]]["delta_percent"],
              black=by_name[workloads[1]]["delta_percent"],
              canneal=by_name[workloads[2]]["delta_percent"]))

    output_file.write("\n## Detailed Summary\n\n")
    output_file.write(
        "| workload | cost model | best baseline | best baseline cost | "
        "QMAP cost | delta | QMAP writes | QMAP migrations |\n")
    output_file.write("|---|---|---|---:|---:|---:|---:|---:|\n")
    for row in summary_rows:
      output_file.write(
          "| {workload} | {model} | {policy} | {baseline:.2f} | "
          "{qmap:.2f} | {delta:+.2f}% | {writes} | {migrations} |\n"
          .format(
              workload=row["workload"],
              model=row["cost_model"],
              policy=row["best_baseline_policy"].upper(),
              baseline=row["best_baseline_cost"],
              qmap=row["qmap_cost"],
              delta=row["delta_percent"],
              writes=row["qmap_nvm_writes"],
              migrations=row["qmap_migrations"]))

    output_file.write("\n## Per-policy Reweighted Costs\n\n")
    output_file.write(
        "| workload | cost model | policy | cost | hits | NVM reads | "
        "NVM writes | migrations |\n")
    output_file.write("|---|---|---|---:|---:|---:|---:|---:|\n")
    for row in policy_rows:
      output_file.write(
          "| {workload} | {model} | {policy} | {cost:.2f} | {hits} | "
          "{reads} | {writes} | {migrations} |\n"
          .format(
              workload=row["workload"],
              model=row["cost_model"],
              policy=row["policy"].upper(),
              cost=row["reweighted_cost"],
              hits=row["hits"],
              reads=row["nvm_reads"],
              writes=row["nvm_writes"],
              migrations=row["migrations"]))

    output_file.write("\n## Interpretation\n\n")
    for workload, deltas in by_workload.items():
      output_file.write(
          "- `{}`: {}\n".format(workload, conclusion_for_workload(deltas)))
    output_file.write(
        "- These numbers reuse existing replay counters only; no checkpoint "
        "training or replay was run by this script.\n")


def write_outputs(summary_rows, policy_rows, output_dir):
  os.makedirs(output_dir, exist_ok=True)
  summary_csv = os.path.join(output_dir, "summary.csv")
  policy_csv = os.path.join(output_dir, "per_policy_costs.csv")
  summary_md = os.path.join(output_dir, "summary.md")
  write_csv(summary_csv, summary_rows, [
      "cost_model", "workload", "best_baseline_policy",
      "best_baseline_cost", "qmap_cost", "delta_percent",
      "qmap_nvm_writes", "qmap_migrations", "qmap_hit_rate_percent",
      "qmap_decision_count",
  ])
  write_csv(policy_csv, policy_rows, [
      "workload", "cost_model", "policy", "reweighted_cost", "hits",
      "nvm_reads", "nvm_writes", "migrations", "hit_rate_percent",
      "decision_count", "avg_decision_time_ms",
  ])
  write_markdown(summary_md, summary_rows, policy_rows)
  print("[done] summary csv: {}".format(rel(summary_csv)), flush=True)
  print("[done] per-policy csv: {}".format(rel(policy_csv)), flush=True)
  print("[done] summary md: {}".format(rel(summary_md)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Recompute cost-weight sensitivity from existing JSON.")
  parser.add_argument("--workloads", default=",".join(WORKLOADS.keys()),
                      help="Comma-separated keys: {}".format(
                          ",".join(WORKLOADS.keys())))
  parser.add_argument("--output_dir", default=path_from_root(
      "outputs", "results", "cost_weight_sensitivity"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  workload_keys = selected_workloads(split_csv(args.workloads))
  workload_results = load_workload_results(workload_keys)
  summary_rows = build_summary_rows(workload_results)
  policy_rows = []
  for cost_model in COST_MODELS:
    policy_rows.extend(build_policy_rows(workload_results, cost_model))
  write_outputs(summary_rows, policy_rows, args.output_dir)


if __name__ == "__main__":
  main()
