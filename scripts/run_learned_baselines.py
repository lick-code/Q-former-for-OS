# coding=utf-8
"""Run Kleio-lite and PatternS-lite baselines on real workload splits."""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

HISTORY_LENGTH = 10
CANDIDATE_COUNT = 8
DRAM_CAPACITY = 16
LOOKAHEAD = 256
PAGE_SHIFT = 12
LABEL_LOOKAHEAD = 256
MODEL_EPOCHS = 5
LEARNING_RATE = 0.05
L2 = 1e-4
CLUSTER_COUNT = 8
CLUSTER_ITERATIONS = 20
SEED = 3136859

LEARNED_POLICIES = ("kleio_lite", "patterns_lite")
RULE_POLICIES = ("lru", "random", "lfu", "clock")

WORKLOADS = {
    "blackscholes": {
        "display": "blackscholes",
        "train_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_train.csv",
        "test_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_test.csv",
        "qmap_result": "outputs/results/real_workload_suite/1m/parsec_blackscholes/qmap.json",
    },
    "canneal": {
        "display": "canneal",
        "train_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_train.csv",
        "test_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_test.csv",
        "qmap_result": "outputs/results/real_workload_suite/1m/parsec_canneal/qmap.json",
    },
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "train_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_train.csv",
        "test_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_test.csv",
        "qmap_result": "outputs/results/real_workload_suite_pressure/selected/parsec_streamcluster/qmap.json",
    },
    "dedup_pressure": {
        "display": "dedup_pressure",
        "train_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_dedup_train.csv",
        "test_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_dedup_test.csv",
        "qmap_result": "outputs/results/real_workload_suite_pressure/selected/parsec_dedup/qmap.json",
    },
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def selected_workloads(keys):
  if not keys:
    return tuple(WORKLOADS.keys())
  unknown = sorted(set(keys) - set(WORKLOADS.keys()))
  if unknown:
    raise ValueError("Unknown workload(s): {}".format(", ".join(unknown)))
  return tuple(keys)


def selected_policies(policies):
  if not policies:
    return LEARNED_POLICIES
  unknown = sorted(set(policies) - set(LEARNED_POLICIES))
  if unknown:
    raise ValueError("Unsupported learned policy(s): {}".format(
        ", ".join(unknown)))
  return tuple(policies)


def rel(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def model_path(workload_key, policy, model_root):
  return "{}/{}/{}.json".format(model_root, workload_key, policy)


def result_json_path(workload_key, policy, result_root):
  return "{}/{}/{}.json".format(result_root, workload_key, policy)


def result_log_path(workload_key, policy, result_root):
  return "{}/logs/{}_{}.log".format(result_root, workload_key, policy)


def train_log_path(workload_key, policy, result_root):
  return "{}/logs/{}_{}_train.log".format(result_root, workload_key, policy)


def build_train_command(python_bin, workload_key, policy, model_root):
  config = WORKLOADS[workload_key]
  return [
      python_bin, "qmap/learned_baselines.py",
      "--policy", policy,
      "--train_trace", config["train_trace"],
      "--model_output", model_path(workload_key, policy, model_root),
      "--dram_capacity", str(DRAM_CAPACITY),
      "--page_shift", str(PAGE_SHIFT),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(CANDIDATE_COUNT),
      "--lookahead", str(LOOKAHEAD),
      "--label_lookahead", str(LABEL_LOOKAHEAD),
      "--model_epochs", str(MODEL_EPOCHS),
      "--learning_rate", str(LEARNING_RATE),
      "--l2", str(L2),
      "--cluster_count", str(CLUSTER_COUNT),
      "--cluster_iterations", str(CLUSTER_ITERATIONS),
      "--seed", str(SEED),
  ]


def build_eval_command(python_bin, workload_key, policy, model_path_value,
                       result_root):
  config = WORKLOADS[workload_key]
  return [
      python_bin, "qmap/qmap_eval.py",
      "--trace_path", config["test_trace"],
      "--policy", policy,
      "--learned_model", model_path_value,
      "--dram_capacity", str(DRAM_CAPACITY),
      "--page_shift", str(PAGE_SHIFT),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(CANDIDATE_COUNT),
      "--lookahead", str(LOOKAHEAD),
      "--json_output", result_json_path(workload_key, policy, result_root),
  ]


def build_rule_eval_command(python_bin, workload_key, policy, result_root):
  config = WORKLOADS[workload_key]
  return [
      python_bin, "qmap/qmap_eval.py",
      "--trace_path", config["test_trace"],
      "--policy", policy,
      "--dram_capacity", str(DRAM_CAPACITY),
      "--page_shift", str(PAGE_SHIFT),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(CANDIDATE_COUNT),
      "--lookahead", str(LOOKAHEAD),
      "--json_output", result_json_path(workload_key, policy, result_root),
  ]


def command_to_text(command):
  return " ".join(command)


def run_command(command, log_path):
  print("[run] {}".format(command_to_text(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      universal_newlines=True)
  os.makedirs(os.path.dirname(path_from_root(log_path)), exist_ok=True)
  with open(path_from_root(log_path), "w", encoding="utf-8") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)


def check_inputs(workload_keys):
  missing = []
  for workload_key in workload_keys:
    config = WORKLOADS[workload_key]
    for key in ("train_trace", "test_trace"):
      path = path_from_root(*config[key].split("/"))
      if not os.path.exists(path):
        missing.append(rel(path))
  if missing:
    raise FileNotFoundError(
        "Missing learned-baseline input trace(s):\n  {}".format(
            "\n  ".join(missing)))


def run_experiments(args, workload_keys, policies):
  for workload_key in workload_keys:
    for policy in policies:
      current_model_path = model_path(workload_key, policy, args.model_root)
      if not args.skip_train:
        run_command(
            build_train_command(
                args.python, workload_key, policy, args.model_root),
            train_log_path(workload_key, policy, args.result_root))
      if not args.skip_eval:
        run_command(
            build_eval_command(
                args.python, workload_key, policy, current_model_path,
                args.result_root),
            result_log_path(workload_key, policy, args.result_root))
    if args.include_rule_baselines and not args.skip_eval:
      for policy in RULE_POLICIES:
        run_command(
            build_rule_eval_command(
                args.python, workload_key, policy, args.result_root),
            result_log_path(workload_key, policy, args.result_root))


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def qmap_reference_path(workload_key):
  return path_from_root(*WORKLOADS[workload_key]["qmap_result"].split("/"))


def result_path_from_root(path):
  return path_from_root(*path.split("/"))


def policy_display(policy):
  if policy == "qmap":
    return "QMAP-CrossAttn"
  if policy == "kleio_lite":
    return "Kleio-lite"
  if policy == "patterns_lite":
    return "PatternS-lite"
  return policy.upper()


def collect_result_rows(workload_keys, policies, result_root,
                        include_rule_baselines, include_qmap_reference):
  rows = []
  for workload_key in workload_keys:
    workload = WORKLOADS[workload_key]["display"]
    workload_rows = []
    if include_qmap_reference:
      qmap_path = qmap_reference_path(workload_key)
      if os.path.exists(qmap_path):
        qmap = load_json(qmap_path)
        workload_rows.append((qmap, qmap_path, "qmap"))
    for policy in policies:
      path = result_path_from_root(result_json_path(
          workload_key, policy, result_root))
      if os.path.exists(path):
        workload_rows.append((load_json(path), path, policy))
    if include_rule_baselines:
      for policy in RULE_POLICIES:
        path = result_path_from_root(result_json_path(
            workload_key, policy, result_root))
        if os.path.exists(path):
          workload_rows.append((load_json(path), path, policy))

    qmap_cost = None
    for result, _, policy in workload_rows:
      if policy == "qmap":
        qmap_cost = float(result["weighted_access_cost"])
        break
    for result, path, policy in workload_rows:
      cost = float(result["weighted_access_cost"])
      if qmap_cost is None or qmap_cost == 0.0:
        delta_vs_qmap = ""
      else:
        delta_vs_qmap = (cost - qmap_cost) * 100.0 / qmap_cost
      rows.append({
          "workload": workload,
          "policy": policy,
          "policy_display": policy_display(policy),
          "weighted_access_cost": cost,
          "delta_vs_qmap_percent": delta_vs_qmap,
          "hit_rate_percent": float(result.get("hit_rate_percent", 0.0)),
          "nvm_writes": int(result.get("nvm_writes", 0)),
          "migrations": int(result.get("migrations", 0)),
          "decision_count": int(result.get("decision_count", 0)),
          "avg_decision_time_ms": float(
              result.get("avg_decision_time_ms", 0.0)),
          "artifact": rel(path),
      })
  return rows


def write_summary(rows, output_dir):
  os.makedirs(path_from_root(output_dir), exist_ok=True)
  csv_path = path_from_root(output_dir, "summary.csv")
  md_path = path_from_root(output_dir, "summary.md")
  fields = [
      "workload",
      "policy",
      "policy_display",
      "weighted_access_cost",
      "delta_vs_qmap_percent",
      "hit_rate_percent",
      "nvm_writes",
      "migrations",
      "decision_count",
      "avg_decision_time_ms",
      "artifact",
  ]
  with open(csv_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})

  with open(md_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Learned Baseline Comparison\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- learned baselines: `Kleio-lite`, `PatternS-lite`\n")
    output_file.write("- history_length: `{}`\n".format(HISTORY_LENGTH))
    output_file.write("- candidate_count: `{}`\n".format(CANDIDATE_COUNT))
    output_file.write("- dram_capacity: `{}` pages\n".format(DRAM_CAPACITY))
    output_file.write("- lookahead: `{}`\n".format(LOOKAHEAD))
    output_file.write("- label_lookahead: `{}`\n\n".format(LABEL_LOOKAHEAD))
    output_file.write("## Results\n\n")
    output_file.write(
        "| Workload | Policy | Cost | Delta vs QMAP | Hit rate (%) | "
        "NVM writes | Migrations | Decision ms |\n")
    output_file.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      delta = row["delta_vs_qmap_percent"]
      delta_text = "" if delta == "" else "{:+.2f}%".format(delta)
      output_file.write(
          "| {workload} | {policy} | {cost:.2f} | {delta} | "
          "{hit:.2f} | {writes} | {migrations} | {decision:.6f} |\n".format(
              workload=row["workload"],
              policy=row["policy_display"],
              cost=row["weighted_access_cost"],
              delta=delta_text,
              hit=row["hit_rate_percent"],
              writes=row["nvm_writes"],
              migrations=row["migrations"],
              decision=row["avg_decision_time_ms"]))
    output_file.write("\nArtifacts are listed in `summary.csv`.\n")
  print("[done] summary_csv={}".format(rel(csv_path)), flush=True)
  print("[done] summary_md={}".format(rel(md_path)), flush=True)


def shell_quote(value):
  return "'{}'".format(value.replace("'", "'\"'\"'"))


def write_server_script(path, args, workload_keys, policies):
  lines = [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "",
      "PY=${PY:-%s}" % shell_quote(args.python),
      "WORKLOADS=${WORKLOADS:-%s}" % shell_quote(",".join(workload_keys)),
      "POLICIES=${POLICIES:-%s}" % shell_quote(",".join(policies)),
      "",
      "$PY scripts/run_learned_baselines.py \\",
      "  --workloads \"$WORKLOADS\" \\",
      "  --policies \"$POLICIES\" \\",
      "  --run \\",
      "  --summarize \\",
      "  --include_rule_baselines \\",
      "  --python \"$PY\"",
      "",
  ]
  absolute_path = path_from_root(path)
  os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
  with open(absolute_path, "w", encoding="utf-8", newline="\n") as output_file:
    output_file.write("\n".join(lines))
  print("[done] server_script={}".format(rel(absolute_path)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run Kleio-lite and PatternS-lite learned baselines.")
  parser.add_argument("--workloads", default=",".join(WORKLOADS.keys()),
                      help="Comma-separated keys: {}".format(
                          ",".join(WORKLOADS.keys())))
  parser.add_argument("--policies", default=",".join(LEARNED_POLICIES),
                      help="Comma-separated learned policies.")
  parser.add_argument("--model_root", default="outputs/checkpoints/ml_baselines")
  parser.add_argument("--result_root", default="outputs/results/ml_baselines")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--run", action="store_true")
  parser.add_argument("--summarize", action="store_true")
  parser.add_argument("--skip_train", action="store_true")
  parser.add_argument("--skip_eval", action="store_true")
  parser.add_argument("--include_rule_baselines", action="store_true")
  parser.add_argument("--no_qmap_reference", action="store_true")
  parser.add_argument("--server_script", default=(
      "outputs/results/ml_baselines/run_on_server.sh"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  workload_keys = selected_workloads(split_csv(args.workloads))
  policies = selected_policies(split_csv(args.policies))
  check_inputs(workload_keys)
  write_server_script(args.server_script, args, workload_keys, policies)
  if args.run:
    run_experiments(args, workload_keys, policies)
  if args.summarize:
    rows = collect_result_rows(
        workload_keys, policies, args.result_root,
        args.include_rule_baselines, not args.no_qmap_reference)
    write_summary(rows, args.result_root)


if __name__ == "__main__":
  main()
