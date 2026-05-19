# coding=utf-8
"""Run QMAP ablation experiments.

Each variant is run as an independent generate -> train -> evaluate pipeline and
is summarized against the frozen QMAP-Pool baseline. The default output layout is:

  outputs/results/qmap_ablation/<variant>/qmap.json
  outputs/checkpoints/qmap_ablation/<variant>/qmap_epoch_<N>.pth
  dataset/jsonl/qmap_ablation/<variant>.jsonl
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QMAP_MODEL_NAME = "QMAP-Pool"
BASELINE_VARIANT = "mean_pool"

VARIANT_PURPOSES = {
    "full": "historical Q-Former baseline",
    "no_pc": "remove program-counter context from the access sequence",
    "no_rw": "remove read/write type from the access sequence",
    "mean_pool": "QMAP-Pool baseline without Q-Former queries",
    "no_qformer": "legacy alias for mean_pool",
    "no_cost": "disable write-sensitivity and migration-cost loss terms",
}

DEFAULT_VARIANTS = ("mean_pool", "no_pc", "no_rw", "no_cost")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Run QMAP ablation variants.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_test.csv"))
  parser.add_argument("--variants", default=",".join(DEFAULT_VARIANTS),
                      help="Comma-separated variants to run.")
  parser.add_argument("--result_dir",
                      default=path_from_root("outputs", "results",
                                             "qmap_ablation"))
  parser.add_argument("--checkpoint_root",
                      default=path_from_root("outputs", "checkpoints",
                                             "qmap_ablation"))
  parser.add_argument("--jsonl_root",
                      default=path_from_root("dataset", "jsonl",
                                             "qmap_ablation"))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0,
                      help="NVM write cost used by qmap_eval weighted cost.")
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--allow_historical_qformer", action="store_true",
                      help="Allow the historical `full` Q-Former variant.")
  parser.add_argument("--force", action="store_true",
                      help="Rerun variants even if matching results exist.")
  return parser


def parse_variants(text, allow_historical_qformer=False):
  variants = [item.strip() for item in text.split(",") if item.strip()]
  unknown = [item for item in variants if item not in VARIANT_PURPOSES]
  if unknown:
    raise ValueError("Unknown ablation variant(s): {}".format(
        ", ".join(unknown)))
  if "full" in variants and not allow_historical_qformer:
    raise ValueError(
        "`full` is the historical Q-Former variant. New experiments are "
        "frozen to QMAP-Pool/mean_pool; pass --allow_historical_qformer only "
        "when intentionally reproducing old exploratory results.")
  if not variants:
    raise ValueError("At least one variant is required.")
  return variants


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


def run_metadata(args, variant):
  return {
      "variant": variant,
      "qmap_model": QMAP_MODEL_NAME,
      "baseline_variant": BASELINE_VARIANT,
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


def can_reuse_run(args, variant, qmap_json, checkpoint_path, metadata_path):
  if args.force:
    return False
  if not (os.path.exists(qmap_json) and os.path.exists(checkpoint_path) and
          os.path.exists(metadata_path)):
    return False
  try:
    return load_json(metadata_path) == run_metadata(args, variant)
  except (IOError, ValueError):
    return False


def run_variant(args, variant):
  result_dir = os.path.join(args.result_dir, variant)
  checkpoint_dir = os.path.join(args.checkpoint_root, variant)
  jsonl_path = os.path.join(args.jsonl_root, "{}.jsonl".format(variant))
  log_dir = os.path.join(result_dir, "logs")
  qmap_json = os.path.join(result_dir, "qmap.json")
  metadata_path = os.path.join(result_dir, "run_metadata.json")
  checkpoint_path = os.path.join(
      checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  if can_reuse_run(args, variant, qmap_json, checkpoint_path, metadata_path):
    print("[skip] reusable variant: {}".format(variant), flush=True)
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
      "--ablation", variant,
  ]
  run_command(generate_command, os.path.join(log_dir, "generate.log"))

  train_command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", jsonl_path,
      "--output_dir", checkpoint_dir,
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--write_sensitivity_weight", str(args.write_sensitivity_weight),
      "--migration_cost_weight", str(args.migration_cost_weight),
      "--device", args.device,
      "--seed", str(args.seed),
      "--ablation", variant,
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
      "--ablation", variant,
      "--json_output", qmap_json,
  ]
  run_command(eval_command, os.path.join(log_dir, "qmap.log"))
  write_json(run_metadata(args, variant), metadata_path)

  return load_json(qmap_json), result_dir, checkpoint_path


def add_relative_metrics(row, baseline):
  base_cost = float(baseline["weighted_access_cost"])
  base_writes = float(baseline["nvm_writes"])
  row["cost_delta_percent"] = (
      (row["weighted_access_cost"] - base_cost) * 100.0 / base_cost)
  if base_writes:
    row["nvm_writes_delta_percent"] = (
        (row["nvm_writes"] - base_writes) * 100.0 / base_writes)
  else:
    row["nvm_writes_delta_percent"] = 0.0
  row["hit_rate_delta_pp"] = (
      row["hit_rate_percent"] - baseline["hit_rate_percent"])
  row["nvm_writes_saved_vs_qmap_pool"] = (
      row["nvm_writes"] - baseline["nvm_writes"])
  row["nvm_writes_reduction_vs_variant_percent"] = (
      (row["nvm_writes"] - base_writes) * 100.0 / row["nvm_writes"]
      if row["nvm_writes"] else 0.0)


def write_summary_csv(rows, output_path):
  fields = [
      "variant",
      "purpose",
      "hit_rate_percent",
      "hit_rate_delta_pp",
      "weighted_access_cost",
      "cost_delta_percent",
      "nvm_writes",
      "nvm_writes_saved_vs_qmap_pool",
      "nvm_writes_delta_percent",
      "nvm_writes_reduction_vs_variant_percent",
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
  baseline = next((row for row in rows
                   if row["variant"] == BASELINE_VARIANT), None)
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# QMAP Ablation\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- train trace: `{}`\n".format(
        os.path.relpath(args.train_trace, PROJECT_ROOT)))
    output_file.write("- test trace: `{}`\n".format(
        os.path.relpath(args.test_trace, PROJECT_ROOT)))
    output_file.write("- variants: `{}`\n".format(
        ",".join(row["variant"] for row in rows)))
    output_file.write("- baseline model: `{}` (`ablation={}`)\n".format(
        QMAP_MODEL_NAME, BASELINE_VARIANT))
    output_file.write("- h/c/d/l: `{}/{}/{}/{}`\n".format(
        args.history_length, args.candidate_count, args.dram_capacity,
        args.lookahead))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- loss weights: `write_sensitivity={}, "
                      "migration_cost={}`\n".format(
                          args.write_sensitivity_weight,
                          args.migration_cost_weight))
    output_file.write("- NVM write cost: `{}`\n".format(args.nvm_write_cost))
    output_file.write("- device: `{}`\n".format(args.device))
    output_file.write("- seed: `{}`\n\n".format(args.seed))

    if baseline is not None:
      output_file.write("## QMAP-Pool Baseline\n\n")
      output_file.write(
        "| Hit rate (%) | Weighted cost | NVM writes | Migrations |\n")
      output_file.write("|---:|---:|---:|---:|\n")
      output_file.write("| {hit_rate_percent:.2f} | "
                        "{weighted_access_cost:.2f} | {nvm_writes} | "
        "{migrations} |\n\n".format(**baseline))

    output_file.write("## Results\n\n")
    output_file.write(
        "| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | "
        "Cost delta (%) | NVM writes | Writes delta vs QMAP-Pool | "
        "Writes delta (%) | QMAP-Pool writes delta (%) | Decision ms |\n")
    output_file.write("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {variant} | {purpose} | {hit_rate_percent:.2f} | "
          "{hit_rate_delta_pp:+.2f} | {weighted_access_cost:.2f} | "
          "{cost_delta_percent:+.2f} | {nvm_writes} | "
          "{nvm_writes_saved_vs_qmap_pool:+.0f} | "
          "{nvm_writes_delta_percent:+.2f} | "
          "{nvm_writes_reduction_vs_variant_percent:+.2f} | "
          "{avg_decision_time_ms:.6f} |\n".format(**row))


def main():
  args = build_arg_parser().parse_args()
  variants = parse_variants(args.variants, args.allow_historical_qformer)
  os.makedirs(args.result_dir, exist_ok=True)

  if BASELINE_VARIANT not in variants:
    raise ValueError("The ablation summary needs the `{}` baseline. "
                     "Include {} in --variants.".format(
                         BASELINE_VARIANT, BASELINE_VARIANT))
  if not os.path.exists(args.train_trace):
    raise FileNotFoundError("Training trace not found: {}".format(
        args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError("Test trace not found: {}".format(
        args.test_trace))

  variant_results = {}
  for variant in variants:
    metrics, result_dir, checkpoint_path = run_variant(args, variant)
    variant_results[variant] = (metrics, result_dir, checkpoint_path)

  baseline_metrics = variant_results[BASELINE_VARIANT][0]
  rows = []
  for variant in variants:
    metrics, result_dir, checkpoint_path = variant_results[variant]
    row = dict(metrics)
    row["variant"] = variant
    row["purpose"] = VARIANT_PURPOSES[variant]
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
