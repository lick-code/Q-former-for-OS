# coding=utf-8
"""Capacity-sensitivity runner for the real-workload QMAP-CrossAttn experiments.

Default mode is local-safe:

  python scripts/run_capacity_sensitivity.py

It checks the required processed traces and writes a server shell script. On a
machine with torch/CUDA, run:

  python scripts/run_capacity_sensitivity.py --run --summarize --device cuda
"""

import argparse
import csv
import json
import os
import subprocess


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

HISTORY_LENGTH = 10
CANDIDATE_COUNT = 8
LOOKAHEAD = 256
PAGE_SHIFT = 12
EPOCHS = 10
BATCH_SIZE = 32
LR = 1e-4
SEED = 3136859
NVM_WRITE_COST = 8.0
QMAP_ABLATION = "cross_attention"

DEFAULT_CAPACITIES = (8, 16, 32)
BASELINE_POLICIES = ("lru", "random", "lfu", "clock")
POLICIES = BASELINE_POLICIES + ("qmap",)
RESULT_ROOT = os.path.join("outputs", "results", "capacity_sensitivity")

WORKLOADS = {
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "workload": "parsec_streamcluster",
        "processed_dir": os.path.join(
            "dataset", "processed", "real_workload_suite_pressure",
            "selected"),
        "manifest": os.path.join(
            "dataset", "metadata",
            "real_workload_suite_pressure_manifest.json"),
    },
    "canneal": {
        "display": "canneal",
        "workload": "parsec_canneal",
        "processed_dir": os.path.join(
            "dataset", "processed", "real_workload_suite", "1m"),
        "manifest": os.path.join(
            "dataset", "metadata", "real_workload_suite_1m_manifest.json"),
    },
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_capacities(value):
  capacities = tuple(int(item) for item in split_csv(value))
  if not capacities:
    raise ValueError("At least one DRAM capacity is required.")
  for capacity in capacities:
    if capacity <= 0:
      raise ValueError("DRAM capacities must be positive.")
  return capacities


def selected_workloads(keys):
  if not keys:
    return tuple(WORKLOADS.keys())
  unknown = sorted(set(keys) - set(WORKLOADS.keys()))
  if unknown:
    raise ValueError("Unknown workload(s): {}".format(", ".join(unknown)))
  return tuple(keys)


def shell_quote(value):
  return "'{}'".format(value.replace("'", "'\"'\"'"))


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def capacity_dir(root, workload_key, capacity):
  return os.path.join(root, workload_key, "cap{}".format(capacity)).replace(
      os.sep, "/")


def jsonl_dir(workload_key, capacity):
  return capacity_dir(
      os.path.join("dataset", "jsonl", "capacity_sensitivity"),
      workload_key,
      capacity)


def result_dir(workload_key, capacity):
  return capacity_dir(RESULT_ROOT, workload_key, capacity)


def checkpoint_dir(workload_key, capacity):
  return capacity_dir(
      os.path.join("outputs", "checkpoints", "capacity_sensitivity"),
      workload_key,
      capacity)


def build_pilot_command(python_bin, workload_key, capacity, device):
  config = WORKLOADS[workload_key]
  command = [
      python_bin, "scripts/run_real_pilot.py",
      "--skip_prepare",
      "--workloads", config["workload"],
      "--policies", ",".join(POLICIES),
      "--processed_dir", config["processed_dir"].replace(os.sep, "/"),
      "--manifest", config["manifest"].replace(os.sep, "/"),
      "--jsonl_dir", jsonl_dir(workload_key, capacity),
      "--result_dir", result_dir(workload_key, capacity),
      "--checkpoint_dir", checkpoint_dir(workload_key, capacity),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(CANDIDATE_COUNT),
      "--dram_capacity", str(capacity),
      "--lookahead", str(LOOKAHEAD),
      "--page_shift", str(PAGE_SHIFT),
      "--epochs", str(EPOCHS),
      "--batch_size", str(BATCH_SIZE),
      "--lr", str(LR),
      "--seed", str(SEED),
      "--nvm_write_cost", str(NVM_WRITE_COST),
      "--run_id", "capacity_{}_cap{}".format(workload_key, capacity),
  ]
  if device:
    command.extend(["--device", device])
  return command


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


def processed_trace_path(workload_key, split):
  config = WORKLOADS[workload_key]
  return path_from_root(
      config["processed_dir"],
      "{}_{}.csv".format(config["workload"], split))


def check_inputs(workload_keys):
  missing = []
  for workload_key in workload_keys:
    config = WORKLOADS[workload_key]
    for split in ("train", "valid", "test"):
      path = processed_trace_path(workload_key, split)
      if not os.path.exists(path):
        missing.append(rel(path))
    manifest = path_from_root(config["manifest"])
    if not os.path.exists(manifest):
      missing.append(rel(manifest))
  if missing:
    raise FileNotFoundError(
        "Missing required capacity-sensitivity input(s):\n  {}".format(
            "\n  ".join(missing)))


def policy_result_path(workload_key, capacity, policy):
  config = WORKLOADS[workload_key]
  return path_from_root(
      result_dir(workload_key, capacity),
      config["workload"],
      "{}.json".format(policy))


def case_has_all_results(workload_key, capacity):
  return all(
      os.path.exists(policy_result_path(workload_key, capacity, policy))
      for policy in POLICIES)


def run_experiments(python_bin, device, workload_keys, capacities,
                    skip_existing=False):
  for workload_key in workload_keys:
    for capacity in capacities:
      if skip_existing and case_has_all_results(workload_key, capacity):
        print("[skip] existing results: {} cap{}".format(
            workload_key, capacity), flush=True)
        continue
      log_path = path_from_root(
          RESULT_ROOT, "logs",
          "{}_cap{}.log".format(workload_key, capacity))
      run_command(
          build_pilot_command(python_bin, workload_key, capacity, device),
          log_path)


def load_policy_results(workload_key, capacity):
  results = {}
  missing = []
  for policy in POLICIES:
    path = policy_result_path(workload_key, capacity, policy)
    if not os.path.exists(path):
      missing.append(rel(path))
      continue
    results[policy] = load_json(path)
  if missing:
    raise FileNotFoundError(
        "Missing capacity-sensitivity result(s):\n  {}".format(
            "\n  ".join(missing)))
  return results


def best_baseline(policy_results):
  baselines = {
      policy: result
      for policy, result in policy_results.items()
      if policy in BASELINE_POLICIES
  }
  if not baselines:
    raise ValueError("At least one baseline result is required.")
  return min(
      baselines.items(),
      key=lambda item: (
          float(item[1]["weighted_access_cost"]),
          int(item[1].get("nvm_writes", 0)),
          -float(item[1].get("hit_rate_percent", 0.0))))


def pressure_note(decision_count):
  if decision_count == 0:
    return "no replacement pressure"
  if decision_count < 100:
    return "low-pressure"
  return ""


def build_summary_row(workload_key, capacity, policy_results):
  if "qmap" not in policy_results:
    raise ValueError("QMAP result is required for {}".format(workload_key))
  best_policy, best_result = best_baseline(policy_results)
  qmap_result = policy_results["qmap"]
  best_cost = float(best_result["weighted_access_cost"])
  qmap_cost = float(qmap_result["weighted_access_cost"])
  if best_cost == 0.0:
    delta = 0.0
  else:
    delta = (qmap_cost - best_cost) * 100.0 / best_cost
  decision_count = int(qmap_result.get("decision_count", 0))
  return {
      "workload": WORKLOADS.get(workload_key, {}).get("display",
                                                      workload_key),
      "dram_capacity": capacity,
      "best_baseline_policy": best_policy,
      "best_baseline_cost": best_cost,
      "qmap_cost": qmap_cost,
      "delta_percent": delta,
      "qmap_migrations": int(qmap_result.get("migrations", 0)),
      "decision_count": decision_count,
      "qmap_nvm_writes": int(qmap_result.get("nvm_writes", 0)),
      "note": pressure_note(decision_count),
  }


def collect_summary_rows(workload_keys, capacities):
  rows = []
  for workload_key in workload_keys:
    for capacity in capacities:
      rows.append(build_summary_row(
          workload_key,
          capacity,
          load_policy_results(workload_key, capacity)))
  return rows


def write_summary_csv(rows, path):
  fields = [
      "workload",
      "dram_capacity",
      "best_baseline_policy",
      "best_baseline_cost",
      "qmap_cost",
      "delta_percent",
      "qmap_migrations",
      "decision_count",
      "qmap_nvm_writes",
      "note",
  ]
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def write_summary_markdown(rows, path, workload_keys, capacities):
  with open(path, "w", encoding="utf-8") as output_file:
    output_file.write("# Capacity Sensitivity\n\n")
    output_file.write(
        "Purpose: test whether the QMAP-CrossAttn conclusion depends on the "
        "single `dram_capacity=16` setting.\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- workloads: `{}`\n".format(", ".join(workload_keys)))
    output_file.write("- DRAM capacities: `{}` pages\n".format(
        ", ".join(str(capacity) for capacity in capacities)))
    output_file.write("- policies: `{}`\n".format(", ".join(
        policy.upper() if policy != "qmap" else "QMAP-CrossAttn"
        for policy in POLICIES)))
    output_file.write("- h/c/l: `{}/{}/{}`\n".format(
        HISTORY_LENGTH, CANDIDATE_COUNT, LOOKAHEAD))
    output_file.write("- epochs: `{}`\n".format(EPOCHS))
    output_file.write("- batch size: `{}`\n".format(BATCH_SIZE))
    output_file.write("- QMAP model: `QMAP-CrossAttn` (`ablation={}`)\n\n".format(
        QMAP_ABLATION))

    output_file.write("## Results\n\n")
    output_file.write(
        "| Workload | DRAM cap | Best baseline cost | QMAP cost | delta | "
        "QMAP migrations | decision count | note |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|---|\n")
    for row in rows:
      baseline = "{:.2f} ({})".format(
          row["best_baseline_cost"], row["best_baseline_policy"].upper())
      output_file.write(
          "| {workload} | {cap} | {baseline} | {qmap:.2f} | "
          "{delta:+.2f}% | {migrations} | {decisions} | {note} |\n"
          .format(
              workload=row["workload"],
              cap=row["dram_capacity"],
              baseline=baseline,
              qmap=row["qmap_cost"],
              delta=row["delta_percent"],
              migrations=row["qmap_migrations"],
              decisions=row["decision_count"],
              note=row["note"]))

    output_file.write("\n## Artifact Layout\n\n")
    output_file.write(
        "- JSONL: `dataset/jsonl/capacity_sensitivity/<workload>/cap*/`\n")
    output_file.write(
        "- checkpoints: "
        "`outputs/checkpoints/capacity_sensitivity/<workload>/cap*/`\n")
    output_file.write(
        "- per-case results: "
        "`outputs/results/capacity_sensitivity/<workload>/cap*/`\n")


def write_summary(rows, output_dir, workload_keys, capacities):
  os.makedirs(output_dir, exist_ok=True)
  csv_path = os.path.join(output_dir, "summary.csv")
  md_path = os.path.join(output_dir, "summary.md")
  write_summary_csv(rows, csv_path)
  write_summary_markdown(rows, md_path, workload_keys, capacities)
  print("[done] summary csv: {}".format(rel(csv_path)), flush=True)
  print("[done] summary md: {}".format(rel(md_path)), flush=True)


def write_server_script(path, python_bin, device, workload_keys, capacities):
  workload_arg = ",".join(workload_keys)
  capacity_arg = ",".join(str(capacity) for capacity in capacities)
  run_line = (
      "$PY scripts/run_capacity_sensitivity.py --run --summarize "
      "--workloads \"$WORKLOADS\" --capacities \"$CAPACITIES\" "
      "--python \"$PY\" --device \"$DEVICE\"")
  lines = [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "",
      "# Run from the repository root. Override PY/DEVICE if needed.",
      "PY=${PY:-%s}" % shell_quote(python_bin),
      "DEVICE=${DEVICE:-%s}" % shell_quote(device),
      "WORKLOADS=${WORKLOADS:-%s}" % shell_quote(workload_arg),
      "CAPACITIES=${CAPACITIES:-%s}" % shell_quote(capacity_arg),
      "",
      "# Full pipeline: JSONL generation -> QMAP-CrossAttn training -> policy eval -> final summary.",
      run_line,
      "",
  ]
  try:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
      output_file.write("\n".join(lines))
  except PermissionError:
    print("[warn] cannot write server script: {}".format(rel(path)),
          flush=True)
    print("[warn] command to run on server:", flush=True)
    print(run_line, flush=True)
    return
  print("[done] server script: {}".format(rel(path)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run capacity sensitivity for QMAP-CrossAttn.")
  parser.add_argument("--workloads", default=",".join(WORKLOADS.keys()),
                      help="Comma-separated keys: {}".format(
                          ",".join(WORKLOADS.keys())))
  parser.add_argument("--capacities", default=",".join(
      str(capacity) for capacity in DEFAULT_CAPACITIES))
  parser.add_argument("--python", default="python3",
                      help="Python executable for child commands.")
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--run", action="store_true",
                      help="Run the six JSONL/train/eval sub-experiments.")
  parser.add_argument("--summarize", action="store_true",
                      help="Write outputs/results/capacity_sensitivity summary.")
  parser.add_argument("--skip_existing", action="store_true",
                      help="Skip a sub-experiment when all policy JSONs exist.")
  parser.add_argument("--server_script", default=path_from_root(
      RESULT_ROOT, "run_on_server.sh"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  workload_keys = selected_workloads(split_csv(args.workloads))
  capacities = parse_capacities(args.capacities)
  check_inputs(workload_keys)
  write_server_script(args.server_script, args.python, args.device,
                      workload_keys, capacities)
  if args.run:
    run_experiments(
        args.python,
        args.device,
        workload_keys,
        capacities,
        skip_existing=args.skip_existing)
  if args.summarize:
    write_summary(
        collect_summary_rows(workload_keys, capacities),
        path_from_root(RESULT_ROOT),
        workload_keys,
        capacities)


if __name__ == "__main__":
  main()
