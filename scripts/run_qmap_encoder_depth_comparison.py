# coding=utf-8
"""Compare mean-pooling QMAP with different Transformer encoder depths.

This runner keeps the current best aggregation choice fixed:

  TransformerEncoder(num_layers=N) -> mean pooling -> candidate scorer

Historical runs swept N over 1, 2 and 3. New experiments are frozen to the
one-layer QMAP-Pool setting unless --allow_historical_depth_sweep is passed.
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_LAYERS = (1,)
TRAIN_ABLATION = "mean_pool"
EVAL_ABLATION = "mean_pool"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run QMAP mean-pooling encoder depth comparison.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "writeheavy_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "writeheavy_test.csv"))
  parser.add_argument("--layers", default=",".join(str(x) for x in
                                                   DEFAULT_LAYERS),
                      help="Comma-separated Transformer encoder depths.")
  parser.add_argument("--result_dir",
                      default=path_from_root("outputs", "results",
                                             "qmap_encoder_depth_comparison"))
  parser.add_argument("--checkpoint_root",
                      default=path_from_root("outputs", "checkpoints",
                                             "qmap_encoder_depth_comparison"))
  parser.add_argument("--jsonl_root",
                      default=path_from_root("dataset", "jsonl",
                                             "qmap_encoder_depth_comparison"))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--epochs", type=int, default=20,
                      help="Default matches the Q-Former comparison run.")
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--weight_decay", type=float, default=0.0)
  parser.add_argument("--dropout", type=float, default=0.0)
  parser.add_argument("--num_heads", type=int, default=2)
  parser.add_argument("--feedforward_dim", type=int, default=None,
                      help="Transformer FFN dimension; omitted means 4x hidden.")
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--allow_historical_depth_sweep", action="store_true",
                      help="Allow encoder depths above the frozen 1-layer setup.")
  parser.add_argument("--force", action="store_true",
                      help="Rerun layers even if matching results exist.")
  return parser


def parse_layers(text):
  layers = []
  for item in text.split(","):
    item = item.strip()
    if not item:
      continue
    value = int(item)
    if value <= 0:
      raise ValueError("Transformer layer count must be positive: {}".format(
          value))
    layers.append(value)
  if not layers:
    raise ValueError("At least one Transformer layer count is required.")
  if len(set(layers)) != len(layers):
    raise ValueError("Duplicate layer counts are not allowed: {}".format(
        text))
  return layers


def layer_name(num_layers):
  return "layers_{}".format(num_layers)


def layer_purpose(num_layers):
  if num_layers == 1:
    return "current one-layer mean-pooling baseline"
  return "{}-layer mean-pooling encoder".format(num_layers)


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


def run_metadata(args, num_layers):
  return {
      "profile": layer_name(num_layers),
      "train_ablation": TRAIN_ABLATION,
      "eval_ablation": EVAL_ABLATION,
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
      "weight_decay": args.weight_decay,
      "dropout": args.dropout,
      "num_heads": args.num_heads,
      "num_layers": num_layers,
      "feedforward_dim": args.feedforward_dim,
      "write_sensitivity_weight": args.write_sensitivity_weight,
      "migration_cost_weight": args.migration_cost_weight,
      "nvm_write_cost": args.nvm_write_cost,
      "device": args.device,
      "seed": args.seed,
  }


def can_reuse_run(args, num_layers, qmap_json, checkpoint_path,
                  metadata_path):
  if args.force:
    return False
  if not (os.path.exists(qmap_json) and os.path.exists(checkpoint_path) and
          os.path.exists(metadata_path)):
    return False
  try:
    return load_json(metadata_path) == run_metadata(args, num_layers)
  except (IOError, ValueError):
    return False


def run_layer(args, num_layers):
  name = layer_name(num_layers)
  result_dir = os.path.join(args.result_dir, name)
  checkpoint_dir = os.path.join(args.checkpoint_root, name)
  jsonl_path = os.path.join(args.jsonl_root, "{}.jsonl".format(name))
  log_dir = os.path.join(result_dir, "logs")
  qmap_json = os.path.join(result_dir, "qmap.json")
  metadata_path = os.path.join(result_dir, "run_metadata.json")
  checkpoint_path = os.path.join(
      checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  if can_reuse_run(
      args, num_layers, qmap_json, checkpoint_path, metadata_path):
    print("[skip] reusable layer profile: {}".format(name), flush=True)
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
      "--ablation", TRAIN_ABLATION,
  ]
  run_command(generate_command, os.path.join(log_dir, "generate.log"))

  train_command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", jsonl_path,
      "--output_dir", checkpoint_dir,
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--weight_decay", str(args.weight_decay),
      "--write_sensitivity_weight", str(args.write_sensitivity_weight),
      "--migration_cost_weight", str(args.migration_cost_weight),
      "--num_layers", str(num_layers),
      "--num_heads", str(args.num_heads),
      "--dropout", str(args.dropout),
      "--device", args.device,
      "--seed", str(args.seed),
      "--ablation", TRAIN_ABLATION,
  ]
  if args.feedforward_dim is not None:
    train_command.extend(["--feedforward_dim", str(args.feedforward_dim)])
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
      "--ablation", EVAL_ABLATION,
      "--json_output", qmap_json,
  ]
  run_command(eval_command, os.path.join(log_dir, "qmap.log"))
  write_json(run_metadata(args, num_layers), metadata_path)
  return load_json(qmap_json), result_dir, checkpoint_path


def add_relative_metrics(row, baseline):
  base_cost = float(baseline["weighted_access_cost"])
  base_writes = float(baseline["nvm_writes"])
  row["cost_delta_vs_1_layer_percent"] = (
      (row["weighted_access_cost"] - base_cost) * 100.0 / base_cost)
  row["hit_rate_delta_vs_1_layer_pp"] = (
      row["hit_rate_percent"] - baseline["hit_rate_percent"])
  if base_writes:
    row["nvm_writes_delta_vs_1_layer_percent"] = (
        (row["nvm_writes"] - base_writes) * 100.0 / base_writes)
  else:
    row["nvm_writes_delta_vs_1_layer_percent"] = 0.0


def best_row(rows):
  return min(rows, key=lambda row: (
      row["weighted_access_cost"],
      row["nvm_writes"],
      -row["hit_rate_percent"]))


def write_summary_csv(rows, output_path):
  fields = [
      "profile",
      "purpose",
      "num_layers",
      "num_heads",
      "dropout",
      "weight_decay",
      "feedforward_dim",
      "hit_rate_percent",
      "hit_rate_delta_vs_1_layer_pp",
      "weighted_access_cost",
      "cost_delta_vs_1_layer_percent",
      "nvm_writes",
      "nvm_writes_delta_vs_1_layer_percent",
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
  best = best_row(rows)
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# QMAP Encoder Depth Comparison\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- aggregation: `TransformerEncoder -> mean pooling`\n")
    output_file.write("- train trace: `{}`\n".format(
        os.path.relpath(args.train_trace, PROJECT_ROOT)))
    output_file.write("- test trace: `{}`\n".format(
        os.path.relpath(args.test_trace, PROJECT_ROOT)))
    output_file.write("- baseline: `layers_1`\n")
    output_file.write("- layers: `{}`\n".format(
        ",".join(str(row["num_layers"]) for row in rows)))
    output_file.write("- h/c/d/l: `{}/{}/{}/{}`\n".format(
        args.history_length, args.candidate_count, args.dram_capacity,
        args.lookahead))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- lr: `{}`\n".format(args.lr))
    output_file.write("- dropout: `{}`\n".format(args.dropout))
    output_file.write("- weight decay: `{}`\n".format(args.weight_decay))
    output_file.write("- NVM write cost: `{}`\n".format(args.nvm_write_cost))
    output_file.write("- device: `{}`\n".format(args.device))
    output_file.write("- seed: `{}`\n\n".format(args.seed))

    output_file.write("## Best By Weighted Cost\n\n")
    output_file.write(
        "`{profile}`: hit `{hit_rate_percent:.2f}%`, cost "
        "`{weighted_access_cost:.2f}`, NVM writes `{nvm_writes}`.\n\n"
        .format(**best))

    output_file.write("## Results\n\n")
    output_file.write(
        "| Profile | Purpose | Layers | Heads | Dropout | Weight decay | "
        "Hit rate (%) | Hit delta vs 1-layer (pp) | Cost | "
        "Cost delta vs 1-layer (%) | NVM writes | "
        "Writes delta vs 1-layer (%) | Decision ms |\n")
    output_file.write(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {profile} | {purpose} | {num_layers} | {num_heads} | "
          "{dropout:.3g} | {weight_decay:.3g} | {hit_rate_percent:.2f} | "
          "{hit_rate_delta_vs_1_layer_pp:+.2f} | "
          "{weighted_access_cost:.2f} | "
          "{cost_delta_vs_1_layer_percent:+.2f} | {nvm_writes} | "
          "{nvm_writes_delta_vs_1_layer_percent:+.2f} | "
          "{avg_decision_time_ms:.6f} |\n".format(**row))


def main():
  args = build_arg_parser().parse_args()
  layers = parse_layers(args.layers)
  os.makedirs(args.result_dir, exist_ok=True)

  if 1 not in layers:
    raise ValueError("Include layer `1`; it is needed as the baseline.")
  if any(num_layers > 1 for num_layers in layers
         ) and not args.allow_historical_depth_sweep:
    raise RuntimeError(
        "Encoder 2/3-layer sweeps are frozen as historical exploration. New "
        "experiments should use the one-layer QMAP-Pool setting. Pass "
        "--allow_historical_depth_sweep only when intentionally reproducing "
        "old results.")
  if not os.path.exists(args.train_trace):
    raise FileNotFoundError("Training trace not found: {}".format(
        args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError("Test trace not found: {}".format(
        args.test_trace))

  layer_results = {}
  for num_layers in layers:
    metrics, result_dir, checkpoint_path = run_layer(args, num_layers)
    layer_results[num_layers] = (metrics, result_dir, checkpoint_path)

  baseline_metrics = layer_results[1][0]
  rows = []
  for num_layers in layers:
    metrics, result_dir, checkpoint_path = layer_results[num_layers]
    row = dict(metrics)
    row["profile"] = layer_name(num_layers)
    row["purpose"] = layer_purpose(num_layers)
    row["num_layers"] = num_layers
    row["num_heads"] = args.num_heads
    row["dropout"] = args.dropout
    row["weight_decay"] = args.weight_decay
    row["feedforward_dim"] = args.feedforward_dim
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
