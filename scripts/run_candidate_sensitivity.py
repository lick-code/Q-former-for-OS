# coding=utf-8
"""Candidate-count sensitivity runner for QMAP-Pool real-workload results.

Default mode is local-safe and does not import torch:

  python scripts/run_candidate_sensitivity.py

It checks required processed traces and writes a server script. On a machine
with torch/CUDA, run:

  python scripts/run_candidate_sensitivity.py --run --summarize
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

HISTORY_LENGTH = 10
DRAM_CAPACITY = 16
LOOKAHEAD = 256
PAGE_SHIFT = 12
EPOCHS = 10
BATCH_SIZE = 32
DEFAULT_CANDIDATE_COUNTS = (4, 8, 16)
QMAP_ABLATION = "mean_pool"
POLICIES = ("lru", "random", "lfu", "clock", "qmap")
BASELINE_POLICIES = ("lru", "random", "lfu", "clock")

WORKLOADS = {
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "workload": "parsec_streamcluster",
        "processed_dir": "dataset/processed/real_workload_suite_pressure/selected",
        "manifest": "dataset/metadata/real_workload_suite_pressure_manifest.json",
    },
    "canneal": {
        "display": "canneal",
        "workload": "parsec_canneal",
        "processed_dir": "dataset/processed/real_workload_suite/1m",
        "manifest": "dataset/metadata/real_workload_suite_1m_manifest.json",
    },
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_candidate_counts(value):
  counts = tuple(int(item) for item in split_csv(value))
  if not counts:
    raise ValueError("At least one candidate count is required.")
  for count in counts:
    if count <= 0:
      raise ValueError("candidate_count must be positive: {}".format(count))
  return counts


def shell_quote(value):
  return "'{}'".format(value.replace("'", "'\"'\"'"))


def selected_workloads(keys):
  if not keys:
    return tuple(WORKLOADS.keys())
  unknown = sorted(set(keys) - set(WORKLOADS.keys()))
  if unknown:
    raise ValueError("Unknown workload(s): {}".format(", ".join(unknown)))
  return tuple(keys)


def candidate_dir(root, workload_key, candidate_count):
  return "{}/{}/c{}".format(root, workload_key, candidate_count)


def result_dir(workload_key, candidate_count):
  return candidate_dir("outputs/results/candidate_sensitivity", workload_key,
                       candidate_count)


def jsonl_dir(workload_key, candidate_count):
  return candidate_dir("dataset/jsonl/candidate_sensitivity", workload_key,
                       candidate_count)


def checkpoint_dir(workload_key, candidate_count):
  return candidate_dir("outputs/checkpoints/candidate_sensitivity",
                       workload_key, candidate_count)


def build_pilot_command(python_bin, workload_key, candidate_count, device):
  config = WORKLOADS[workload_key]
  command = [
      python_bin, "scripts/run_real_pilot.py",
      "--skip_prepare",
      "--workloads", config["workload"],
      "--policies", ",".join(POLICIES),
      "--processed_dir", config["processed_dir"],
      "--manifest", config["manifest"],
      "--jsonl_dir", jsonl_dir(workload_key, candidate_count),
      "--result_dir", result_dir(workload_key, candidate_count),
      "--checkpoint_dir", checkpoint_dir(workload_key, candidate_count),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(candidate_count),
      "--dram_capacity", str(DRAM_CAPACITY),
      "--lookahead", str(LOOKAHEAD),
      "--page_shift", str(PAGE_SHIFT),
      "--epochs", str(EPOCHS),
      "--batch_size", str(BATCH_SIZE),
      "--run_id", "candidate_{}_c{}".format(workload_key, candidate_count),
  ]
  if device:
    command.extend(["--device", device])
  return command


def processed_trace_paths(workload_key):
  config = WORKLOADS[workload_key]
  workload = config["workload"]
  return [
      path_from_root(config["processed_dir"], "{}_{}.csv".format(workload,
                                                                 split_name))
      for split_name in ("train", "valid", "test")
  ]


def check_inputs(workload_keys):
  missing = []
  for workload_key in workload_keys:
    config = WORKLOADS[workload_key]
    manifest = path_from_root(*config["manifest"].split("/"))
    if not os.path.exists(manifest):
      missing.append(rel(manifest))
    for trace_path in processed_trace_paths(workload_key):
      if not os.path.exists(trace_path):
        missing.append(rel(trace_path))
  if missing:
    raise FileNotFoundError(
        "Missing required candidate-sensitivity input(s):\n  {}".format(
            "\n  ".join(missing)))


def run_command(command, log_path):
  print("[run] {}".format(" ".join(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  with open(log_path, "w", encoding="utf-8") as output_file:
    output_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def run_pilot_commands(python_bin, device, workload_keys, candidate_counts):
  log_dir = path_from_root("outputs", "results", "candidate_sensitivity",
                           "logs")
  for workload_key in workload_keys:
    for candidate_count in candidate_counts:
      command = build_pilot_command(
          python_bin, workload_key, candidate_count, device)
      run_command(
          command,
          os.path.join(log_dir, "{}_c{}.log".format(workload_key,
                                                    candidate_count)))


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def result_json_path(workload_key, candidate_count, policy):
  config = WORKLOADS[workload_key]
  return path_from_root(result_dir(workload_key, candidate_count),
                        config["workload"], "{}.json".format(policy))


def load_policy_results(workload_key, candidate_count):
  missing = []
  results = {}
  for policy in POLICIES:
    json_path = result_json_path(workload_key, candidate_count, policy)
    if not os.path.exists(json_path):
      missing.append(rel(json_path))
      continue
    results[policy] = load_json(json_path)
  if missing:
    raise FileNotFoundError(
        "Missing candidate-sensitivity result JSON(s):\n  {}".format(
            "\n  ".join(missing)))
  return results


def best_baseline(policy_results):
  baselines = [
      (policy, policy_results[policy])
      for policy in BASELINE_POLICIES
      if policy in policy_results
  ]
  if not baselines:
    raise ValueError("At least one baseline policy result is required.")
  return min(
      baselines,
      key=lambda item: (
          float(item[1]["weighted_access_cost"]),
          int(item[1].get("nvm_writes", 0)),
          -float(item[1].get("hit_rate_percent", 0.0))))


def build_summary_row(workload_key, candidate_count, policy_results):
  best_policy, best_result = best_baseline(policy_results)
  qmap_result = policy_results["qmap"]
  best_cost = float(best_result["weighted_access_cost"])
  qmap_cost = float(qmap_result["weighted_access_cost"])
  if best_cost == 0.0:
    delta = 0.0
  else:
    delta = (qmap_cost - best_cost) * 100.0 / best_cost
  return {
      "workload": workload_key,
      "candidate_count": int(candidate_count),
      "best_baseline_policy": best_policy,
      "best_baseline_cost": best_cost,
      "qmap_cost": qmap_cost,
      "delta_percent": delta,
      "qmap_migrations": int(qmap_result["migrations"]),
      "decision_count": int(qmap_result["decision_count"]),
      "qmap_nvm_writes": int(qmap_result["nvm_writes"]),
      "avg_decision_time_ms": float(qmap_result["avg_decision_time_ms"]),
      "qmap_hit_rate_percent": float(qmap_result.get("hit_rate_percent", 0.0)),
      "best_baseline_nvm_writes": int(best_result.get("nvm_writes", 0)),
      "result_dir": result_dir(workload_key, candidate_count),
  }


def collect_summary_rows(workload_keys, candidate_counts):
  rows = []
  for workload_key in workload_keys:
    for candidate_count in candidate_counts:
      rows.append(build_summary_row(
          workload_key,
          candidate_count,
          load_policy_results(workload_key, candidate_count)))
  return rows


def conclusion_for_workload(rows):
  deltas = [row["delta_percent"] for row in rows]
  if all(delta < 0.0 for delta in deltas):
    return "QMAP-Pool beats the best baseline for every tested candidate count."
  if all(delta > 0.0 for delta in deltas):
    return "QMAP-Pool is worse than the best baseline for every tested candidate count."
  return "The conclusion changes with candidate count."


def write_summary(rows, output_dir):
  os.makedirs(output_dir, exist_ok=True)
  csv_path = os.path.join(output_dir, "summary.csv")
  md_path = os.path.join(output_dir, "summary.md")

  fields = [
      "workload", "candidate_count", "best_baseline_policy",
      "best_baseline_cost", "qmap_cost", "delta_percent",
      "qmap_migrations", "decision_count", "qmap_nvm_writes",
      "avg_decision_time_ms", "qmap_hit_rate_percent",
      "best_baseline_nvm_writes", "result_dir",
  ]
  with open(csv_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})

  with open(md_path, "w", encoding="utf-8") as output_file:
    workload_names = sorted({row["workload"] for row in rows})
    candidate_counts = sorted({row["candidate_count"] for row in rows})
    output_file.write("# Candidate-count Sensitivity\n\n")
    output_file.write(
        "Purpose: test whether QMAP-Pool's real-workload result depends on "
        "a single candidate_count setting.\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- workloads: `{}`\n".format(
        "`, `".join(workload_names)))
    output_file.write("- candidate_count: `{}`\n".format(
        ", ".join(str(count) for count in candidate_counts)))
    output_file.write("- history_length: `{}`\n".format(HISTORY_LENGTH))
    output_file.write("- dram_capacity: `{}` pages\n".format(DRAM_CAPACITY))
    output_file.write("- lookahead: `{}`\n".format(LOOKAHEAD))
    output_file.write("- epochs: `{}`\n".format(EPOCHS))
    output_file.write("- batch_size: `{}`\n".format(BATCH_SIZE))
    output_file.write("- model: `QMAP-Pool` (`ablation={}`)\n\n".format(
        QMAP_ABLATION))

    output_file.write("## Results\n\n")
    output_file.write(
        "| Workload | Candidate count | Best baseline | QMAP cost | "
        "Delta | QMAP migrations | Decisions | Avg decision ms |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {candidate} | {base_cost:.2f} ({base}) | "
          "{qmap_cost:.2f} | {delta:+.2f}% | {migrations} | "
          "{decisions} | {decision_ms:.6f} |\n".format(
              workload=row["workload"],
              candidate=row["candidate_count"],
              base_cost=row["best_baseline_cost"],
              base=row["best_baseline_policy"].upper(),
              qmap_cost=row["qmap_cost"],
              delta=row["delta_percent"],
              migrations=row["qmap_migrations"],
              decisions=row["decision_count"],
              decision_ms=row["avg_decision_time_ms"]))

    output_file.write("\n## Readout\n\n")
    by_workload = {}
    for row in rows:
      by_workload.setdefault(row["workload"], []).append(row)
    for workload in sorted(by_workload):
      output_file.write("- {}: {}\n".format(
          workload, conclusion_for_workload(by_workload[workload])))

    output_file.write("\n## Artifacts\n\n")
    output_file.write(
        "- Per-run JSONL/checkpoints/results are under "
        "`dataset/jsonl/candidate_sensitivity/`, "
        "`outputs/checkpoints/candidate_sensitivity/`, and "
        "`outputs/results/candidate_sensitivity/`.\n")
    output_file.write(
        "- Each row was produced by the full JSONL -> train -> eval pipeline "
        "via `scripts/run_real_pilot.py`.\n")

  print("[done] summary csv: {}".format(rel(csv_path)), flush=True)
  print("[done] summary md: {}".format(rel(md_path)), flush=True)


def command_to_sh(command):
  return " ".join(shell_quote(item) if any(c in item for c in " ()[]{};&")
                  else item for item in command)


def write_server_script(path, python_bin, device, workload_keys,
                        candidate_counts):
  workload_arg = ",".join(workload_keys)
  candidate_arg = ",".join(str(count) for count in candidate_counts)
  lines = [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "",
      "# Run from the repository root. Override PY/DEVICE if needed.",
      "PY=${PY:-%s}" % shell_quote(python_bin),
      "DEVICE=${DEVICE:-%s}" % shell_quote(device),
      "WORKLOADS=${WORKLOADS:-%s}" % shell_quote(workload_arg),
      "CANDIDATES=${CANDIDATES:-%s}" % shell_quote(candidate_arg),
      "",
      "# Runs the complete JSONL -> train -> eval pipeline and writes the final summary.",
      "$PY scripts/run_candidate_sensitivity.py --workloads \"$WORKLOADS\" --candidate_counts \"$CANDIDATES\" --run --summarize --python \"$PY\" --device \"$DEVICE\"",
      "",
  ]
  try:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
      output_file.write("\n".join(lines))
  except PermissionError:
    print("[warn] cannot write server script locally: {}".format(rel(path)),
          flush=True)
    print("[warn] command to run on server:", flush=True)
    print(lines[-2], flush=True)
    return
  print("[done] server script: {}".format(rel(path)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run QMAP candidate-count sensitivity experiments.")
  parser.add_argument("--workloads", default=",".join(WORKLOADS.keys()),
                      help="Comma-separated keys: {}".format(
                          ",".join(WORKLOADS.keys())))
  parser.add_argument("--candidate_counts", default=",".join(
      str(count) for count in DEFAULT_CANDIDATE_COUNTS))
  parser.add_argument("--python", default=sys.executable,
                      help="Python executable for child commands.")
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--run", action="store_true",
                      help="Run the full run_real_pilot pipeline.")
  parser.add_argument("--summarize", action="store_true",
                      help="Write outputs/results/candidate_sensitivity summaries.")
  parser.add_argument("--server_script", default=path_from_root(
      "outputs", "results", "candidate_sensitivity", "run_on_server.sh"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  workload_keys = selected_workloads(split_csv(args.workloads))
  candidate_counts = parse_candidate_counts(args.candidate_counts)
  check_inputs(workload_keys)
  write_server_script(args.server_script, args.python, args.device,
                      workload_keys, candidate_counts)
  if args.run:
    run_pilot_commands(
        args.python, args.device, workload_keys, candidate_counts)
  if args.summarize:
    write_summary(
        collect_summary_rows(workload_keys, candidate_counts),
        path_from_root("outputs", "results", "candidate_sensitivity"))


if __name__ == "__main__":
  main()
