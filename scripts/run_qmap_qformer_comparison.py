# coding=utf-8
"""Compare formal mean-pooling baseline against lighter Q-Former variants.

This runner is intentionally separate from the feature ablation script: mean
pooling is treated as a baseline policy, while Q-Former variants differ only in
aggregation capacity and training regularization.
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PROFILES = {
    "full": {
        "purpose": "original Q-Former capacity",
        "train_ablation": "full",
        "eval_ablation": "full",
        "num_queries": 4,
        "num_layers": 1,
        "dropout": 0.0,
        "weight_decay": 0.0,
    },
    "mean_pool": {
        "purpose": "formal mean-pooling baseline",
        "train_ablation": "mean_pool",
        "eval_ablation": "mean_pool",
        "num_queries": 4,
        "num_layers": 1,
        "dropout": 0.0,
        "weight_decay": 0.0,
    },
    "qformer_light": {
        "purpose": "lighter Q-Former with fewer queries and regularization",
        "train_ablation": "full",
        "eval_ablation": "full",
        "num_queries": 2,
        "num_layers": 1,
        "dropout": 0.1,
        "weight_decay": 1e-4,
    },
    "qformer_tiny": {
        "purpose": "minimal one-query Q-Former with regularization",
        "train_ablation": "full",
        "eval_ablation": "full",
        "num_queries": 1,
        "num_layers": 1,
        "dropout": 0.1,
        "weight_decay": 1e-4,
    },
}

DEFAULT_PROFILES = ("full", "mean_pool", "qformer_light")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run mean-pooling vs lighter Q-Former comparison.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_test.csv"))
  parser.add_argument("--profiles", default=",".join(DEFAULT_PROFILES),
                      help="Comma-separated profiles: {}.".format(
                          ",".join(sorted(PROFILES))))
  parser.add_argument("--result_dir",
                      default=path_from_root("outputs", "results",
                                             "qmap_qformer_comparison"))
  parser.add_argument("--checkpoint_root",
                      default=path_from_root("outputs", "checkpoints",
                                             "qmap_qformer_comparison"))
  parser.add_argument("--jsonl_root",
                      default=path_from_root("dataset", "jsonl",
                                             "qmap_qformer_comparison"))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--epochs", type=int, default=20,
                      help="Longer default training for Q-Former comparison.")
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--allow_historical_qformer", action="store_true",
                      help="Required to run historical Q-Former comparison.")
  parser.add_argument("--force", action="store_true",
                      help="Rerun profiles even if matching results exist.")
  return parser


def parse_profiles(text):
  profiles = [item.strip() for item in text.split(",") if item.strip()]
  unknown = [item for item in profiles if item not in PROFILES]
  if unknown:
    raise ValueError("Unknown Q-Former profile(s): {}".format(
        ", ".join(unknown)))
  if "mean_pool" not in profiles:
    raise ValueError("Include `mean_pool`; it is the formal baseline.")
  return profiles


def command_to_text(command):
  return " ".join(command)


def run_command(command, log_path):
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  print("[run]", command_to_text(command), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  with open(log_path, "w", encoding="utf-8") as output_file:
    output_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(data, path):
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(data, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def normalized_path(path):
  return os.path.normpath(os.path.abspath(path))


def run_metadata(args, profile_name):
  profile = PROFILES[profile_name]
  return {
      "profile": profile_name,
      "profile_config": dict(profile),
      "train_trace": normalized_path(args.train_trace),
      "test_trace": normalized_path(args.test_trace),
      "page_shift": args.page_shift,
      "dram_capacity": args.dram_capacity,
      "history_length": args.history_length,
      "candidate_count": args.candidate_count,
      "lookahead": args.lookahead,
      "epochs": args.epochs,
      "batch_size": args.batch_size,
      "lr": args.lr,
      "write_sensitivity_weight": args.write_sensitivity_weight,
      "migration_cost_weight": args.migration_cost_weight,
      "nvm_write_cost": args.nvm_write_cost,
      "device": args.device,
      "seed": args.seed,
  }


def can_reuse_run(args, profile_name, qmap_json, checkpoint_path,
                  metadata_path):
  if args.force:
    return False
  if not (os.path.exists(qmap_json) and os.path.exists(checkpoint_path) and
          os.path.exists(metadata_path)):
    return False
  try:
    return load_json(metadata_path) == run_metadata(args, profile_name)
  except (IOError, ValueError):
    return False


def run_profile(args, profile_name):
  profile = PROFILES[profile_name]
  result_dir = os.path.join(args.result_dir, profile_name)
  checkpoint_dir = os.path.join(args.checkpoint_root, profile_name)
  jsonl_path = os.path.join(args.jsonl_root, "{}.jsonl".format(profile_name))
  log_dir = os.path.join(result_dir, "logs")
  qmap_json = os.path.join(result_dir, "qmap.json")
  metadata_path = os.path.join(result_dir, "run_metadata.json")
  checkpoint_path = os.path.join(
      checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  if can_reuse_run(
      args, profile_name, qmap_json, checkpoint_path, metadata_path):
    print("[skip] reusable profile: {}".format(profile_name), flush=True)
    return load_json(qmap_json), result_dir, checkpoint_path

  os.makedirs(result_dir, exist_ok=True)
  os.makedirs(checkpoint_dir, exist_ok=True)
  os.makedirs(args.jsonl_root, exist_ok=True)

  generate_command = [
      args.python, "qmap/qmap_generator.py",
      "--input", args.train_trace,
      "--output", jsonl_path,
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--lookahead", str(args.lookahead),
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--ablation", profile["train_ablation"],
  ]
  run_command(generate_command, os.path.join(log_dir, "generate.log"))

  train_command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", jsonl_path,
      "--output_dir", checkpoint_dir,
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--weight_decay", str(profile["weight_decay"]),
      "--write_sensitivity_weight", str(args.write_sensitivity_weight),
      "--migration_cost_weight", str(args.migration_cost_weight),
      "--num_queries", str(profile["num_queries"]),
      "--num_layers", str(profile["num_layers"]),
      "--dropout", str(profile["dropout"]),
      "--device", args.device,
      "--seed", str(args.seed),
      "--ablation", profile["train_ablation"],
  ]
  run_command(train_command, os.path.join(log_dir, "train.log"))

  eval_command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", args.test_trace,
      "--policy", "qmap",
      "--checkpoint", checkpoint_path,
      "--device", args.device,
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--nvm_write_cost", str(args.nvm_write_cost),
      "--ablation", profile["eval_ablation"],
      "--json_output", qmap_json,
  ]
  run_command(eval_command, os.path.join(log_dir, "qmap.log"))
  write_json(run_metadata(args, profile_name), metadata_path)
  return load_json(qmap_json), result_dir, checkpoint_path


def add_relative_metrics(row, baseline):
  base_cost = float(baseline["weighted_access_cost"])
  base_writes = float(baseline["nvm_writes"])
  row["cost_delta_vs_mean_pool_percent"] = (
      (row["weighted_access_cost"] - base_cost) * 100.0 / base_cost)
  row["hit_rate_delta_vs_mean_pool_pp"] = (
      row["hit_rate_percent"] - baseline["hit_rate_percent"])
  if base_writes:
    row["nvm_writes_delta_vs_mean_pool_percent"] = (
        (row["nvm_writes"] - base_writes) * 100.0 / base_writes)
  else:
    row["nvm_writes_delta_vs_mean_pool_percent"] = 0.0


def write_summary_csv(rows, output_path):
  fields = [
      "profile",
      "purpose",
      "num_queries",
      "num_layers",
      "dropout",
      "weight_decay",
      "hit_rate_percent",
      "hit_rate_delta_vs_mean_pool_pp",
      "weighted_access_cost",
      "cost_delta_vs_mean_pool_percent",
      "nvm_writes",
      "nvm_writes_delta_vs_mean_pool_percent",
      "nvm_reads",
      "migrations",
      "avg_decision_time_ms",
      "decision_count",
      "result_dir",
      "checkpoint",
  ]
  with open(output_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def write_summary_markdown(rows, output_path, args):
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# QMAP Q-Former Comparison\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- train trace: `{}`\n".format(
        os.path.relpath(args.train_trace, PROJECT_ROOT)))
    output_file.write("- test trace: `{}`\n".format(
        os.path.relpath(args.test_trace, PROJECT_ROOT)))
    output_file.write("- baseline: `mean_pool`\n")
    output_file.write("- profiles: `{}`\n".format(
        ",".join(row["profile"] for row in rows)))
    output_file.write("- h/c/d/l: `{}/{}/{}/{}`\n".format(
        args.history_length, args.candidate_count, args.dram_capacity,
        args.lookahead))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- lr: `{}`\n".format(args.lr))
    output_file.write("- device: `{}`\n".format(args.device))
    output_file.write("- seed: `{}`\n\n".format(args.seed))

    output_file.write("## Results\n\n")
    output_file.write(
        "| Profile | Purpose | Q | Layers | Dropout | Weight decay | "
        "Hit rate (%) | Hit delta vs mean_pool (pp) | Cost | "
        "Cost delta vs mean_pool (%) | NVM writes | "
        "Writes delta vs mean_pool (%) | Decision ms |\n")
    output_file.write(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {profile} | {purpose} | {num_queries} | {num_layers} | "
          "{dropout:.3g} | {weight_decay:.3g} | {hit_rate_percent:.2f} | "
          "{hit_rate_delta_vs_mean_pool_pp:+.2f} | "
          "{weighted_access_cost:.2f} | "
          "{cost_delta_vs_mean_pool_percent:+.2f} | {nvm_writes} | "
          "{nvm_writes_delta_vs_mean_pool_percent:+.2f} | "
          "{avg_decision_time_ms:.6f} |\n".format(**row))


def main():
  args = build_arg_parser().parse_args()
  if not args.allow_historical_qformer:
    raise RuntimeError(
        "Q-Former comparison is frozen as historical exploration. New "
        "experiments should use QMAP-Pool (`ablation=mean_pool`). Pass "
        "--allow_historical_qformer only when intentionally reproducing old "
        "results.")
  profiles = parse_profiles(args.profiles)
  os.makedirs(args.result_dir, exist_ok=True)

  if not os.path.exists(args.train_trace):
    raise FileNotFoundError("Training trace not found: {}".format(
        args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError("Test trace not found: {}".format(
        args.test_trace))

  profile_results = {}
  for profile_name in profiles:
    metrics, result_dir, checkpoint_path = run_profile(args, profile_name)
    profile_results[profile_name] = (metrics, result_dir, checkpoint_path)

  baseline_metrics = profile_results["mean_pool"][0]
  rows = []
  for profile_name in profiles:
    profile = PROFILES[profile_name]
    metrics, result_dir, checkpoint_path = profile_results[profile_name]
    row = dict(metrics)
    row["profile"] = profile_name
    row["purpose"] = profile["purpose"]
    row["num_queries"] = profile["num_queries"]
    row["num_layers"] = profile["num_layers"]
    row["dropout"] = profile["dropout"]
    row["weight_decay"] = profile["weight_decay"]
    row["result_dir"] = os.path.relpath(result_dir, PROJECT_ROOT)
    row["checkpoint"] = os.path.relpath(checkpoint_path, PROJECT_ROOT)
    add_relative_metrics(row, baseline_metrics)
    rows.append(row)

  summary_csv = os.path.join(args.result_dir, "summary.csv")
  summary_md = os.path.join(args.result_dir, "summary.md")
  write_summary_csv(rows, summary_csv)
  write_summary_markdown(rows, summary_md, args)
  print("[done] result_dir={}".format(args.result_dir))
  print("[done] summary={}".format(summary_md))


if __name__ == "__main__":
  main()
