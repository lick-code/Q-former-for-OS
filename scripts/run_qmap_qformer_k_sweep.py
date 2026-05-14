# coding=utf-8
"""Run a controlled Q-Former query-count K sweep for QMAP.

This script isolates the Q-Former hyperparameter K (`--num_queries`) by keeping
the generated training samples, model depth, heads, dropout, weight decay, loss
weights, and evaluation setup fixed across runs.

Default output layout:

  outputs/results/qmap_qformer_k_sweep/k<K>/qmap.json
  outputs/checkpoints/qmap_qformer_k_sweep/k<K>/qmap_epoch_<N>.pth
  dataset/jsonl/qmap_qformer_k_sweep/train.jsonl
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_QUERIES = (1, 2, 3, 4, 5, 6, 8)


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run a controlled QMAP Q-Former K sweep.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_test.csv"))
  parser.add_argument("--queries", default=",".join(
      str(value) for value in DEFAULT_QUERIES),
                      help="Comma-separated Q-Former K values.")
  parser.add_argument("--baseline_k", type=int, default=4,
                      help="K used as the relative-metric baseline.")
  parser.add_argument("--result_dir",
                      default=path_from_root("outputs", "results",
                                             "qmap_qformer_k_sweep"))
  parser.add_argument("--checkpoint_root",
                      default=path_from_root("outputs", "checkpoints",
                                             "qmap_qformer_k_sweep"))
  parser.add_argument("--jsonl_path",
                      default=path_from_root("dataset", "jsonl",
                                             "qmap_qformer_k_sweep",
                                             "train.jsonl"))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--epochs", type=int, default=20)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--weight_decay", type=float, default=0.0)
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0)
  parser.add_argument("--num_layers", type=int, default=1)
  parser.add_argument("--num_heads", type=int, default=2)
  parser.add_argument("--feedforward_dim", type=int, default=None)
  parser.add_argument("--dropout", type=float, default=0.0)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--force", action="store_true",
                      help="Rerun K values even if matching results exist.")
  return parser


def parse_queries(text):
  values = []
  for item in text.split(","):
    item = item.strip()
    if not item:
      continue
    value = int(item)
    if value <= 0:
      raise ValueError("K values must be positive: {}".format(value))
    if value not in values:
      values.append(value)
  if not values:
    raise ValueError("At least one K value is required.")
  return values


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


def generation_metadata(args):
  return {
      "train_trace": normalized_path(args.train_trace),
      "page_shift": args.page_shift,
      "dram_capacity": args.dram_capacity,
      "history_length": args.history_length,
      "candidate_count": args.candidate_count,
      "lookahead": args.lookahead,
      "ablation": "full",
  }


def jsonl_metadata_path(args):
  return "{}.metadata.json".format(args.jsonl_path)


def prepare_jsonl(args):
  metadata_path = jsonl_metadata_path(args)
  if not args.force and os.path.exists(args.jsonl_path) and os.path.exists(
      metadata_path):
    try:
      if load_json(metadata_path) == generation_metadata(args):
        print("[skip] reusable jsonl: {}".format(args.jsonl_path), flush=True)
        return
    except (IOError, ValueError):
      pass

  os.makedirs(os.path.dirname(args.jsonl_path), exist_ok=True)
  generate_command = [
      args.python, "qmap/qmap_generator.py",
      "--input", args.train_trace,
      "--output", args.jsonl_path,
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--lookahead", str(args.lookahead),
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--ablation", "full",
  ]
  run_command(generate_command,
              os.path.join(args.result_dir, "logs", "generate.log"))
  write_json(generation_metadata(args), metadata_path)


def run_id(num_queries):
  return "k{}".format(num_queries)


def run_metadata(args, num_queries):
  return {
      "num_queries": num_queries,
      "train_trace": normalized_path(args.train_trace),
      "test_trace": normalized_path(args.test_trace),
      "jsonl_path": normalized_path(args.jsonl_path),
      "page_shift": args.page_shift,
      "dram_capacity": args.dram_capacity,
      "history_length": args.history_length,
      "candidate_count": args.candidate_count,
      "lookahead": args.lookahead,
      "epochs": args.epochs,
      "batch_size": args.batch_size,
      "lr": args.lr,
      "weight_decay": args.weight_decay,
      "write_sensitivity_weight": args.write_sensitivity_weight,
      "migration_cost_weight": args.migration_cost_weight,
      "nvm_write_cost": args.nvm_write_cost,
      "num_layers": args.num_layers,
      "num_heads": args.num_heads,
      "feedforward_dim": args.feedforward_dim,
      "dropout": args.dropout,
      "device": args.device,
      "seed": args.seed,
      "ablation": "full",
  }


def can_reuse_run(args, num_queries, qmap_json, checkpoint_path,
                  metadata_path):
  if args.force:
    return False
  if not (os.path.exists(qmap_json) and os.path.exists(checkpoint_path) and
          os.path.exists(metadata_path)):
    return False
  try:
    return load_json(metadata_path) == run_metadata(args, num_queries)
  except (IOError, ValueError):
    return False


def run_query_count(args, num_queries):
  current_run_id = run_id(num_queries)
  result_dir = os.path.join(args.result_dir, current_run_id)
  checkpoint_dir = os.path.join(args.checkpoint_root, current_run_id)
  log_dir = os.path.join(result_dir, "logs")
  qmap_json = os.path.join(result_dir, "qmap.json")
  metadata_path = os.path.join(result_dir, "run_metadata.json")
  checkpoint_path = os.path.join(
      checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  if can_reuse_run(args, num_queries, qmap_json, checkpoint_path,
                   metadata_path):
    print("[skip] reusable K run: {}".format(current_run_id), flush=True)
    return load_json(qmap_json), result_dir, checkpoint_path

  os.makedirs(result_dir, exist_ok=True)
  os.makedirs(checkpoint_dir, exist_ok=True)

  train_command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", args.jsonl_path,
      "--output_dir", checkpoint_dir,
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--weight_decay", str(args.weight_decay),
      "--write_sensitivity_weight", str(args.write_sensitivity_weight),
      "--migration_cost_weight", str(args.migration_cost_weight),
      "--num_queries", str(num_queries),
      "--num_layers", str(args.num_layers),
      "--num_heads", str(args.num_heads),
      "--dropout", str(args.dropout),
      "--device", args.device,
      "--seed", str(args.seed),
      "--ablation", "full",
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
      "--ablation", "full",
      "--json_output", qmap_json,
  ]
  run_command(eval_command, os.path.join(log_dir, "qmap.log"))
  write_json(run_metadata(args, num_queries), metadata_path)
  return load_json(qmap_json), result_dir, checkpoint_path


def add_relative_metrics(row, baseline):
  base_cost = float(baseline["weighted_access_cost"])
  base_writes = float(baseline["nvm_writes"])
  row["cost_delta_vs_baseline_percent"] = (
      (row["weighted_access_cost"] - base_cost) * 100.0 / base_cost)
  row["hit_rate_delta_vs_baseline_pp"] = (
      row["hit_rate_percent"] - baseline["hit_rate_percent"])
  if base_writes:
    row["nvm_writes_delta_vs_baseline_percent"] = (
        (row["nvm_writes"] - base_writes) * 100.0 / base_writes)
  else:
    row["nvm_writes_delta_vs_baseline_percent"] = 0.0


def write_summary_csv(rows, output_path):
  fields = [
      "num_queries",
      "hit_rate_percent",
      "hit_rate_delta_vs_baseline_pp",
      "weighted_access_cost",
      "cost_delta_vs_baseline_percent",
      "nvm_writes",
      "nvm_writes_delta_vs_baseline_percent",
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
  best_cost = min(rows, key=lambda row: row["weighted_access_cost"])
  best_hit = max(rows, key=lambda row: row["hit_rate_percent"])
  best_writes = min(rows, key=lambda row: row["nvm_writes"])

  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# QMAP Q-Former K Sweep\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- train trace: `{}`\n".format(
        os.path.relpath(args.train_trace, PROJECT_ROOT)))
    output_file.write("- test trace: `{}`\n".format(
        os.path.relpath(args.test_trace, PROJECT_ROOT)))
    output_file.write("- K values: `{}`\n".format(
        ",".join(str(row["num_queries"]) for row in rows)))
    output_file.write("- baseline K: `{}`\n".format(args.baseline_k))
    output_file.write("- h/c/d/l: `{}/{}/{}/{}`\n".format(
        args.history_length, args.candidate_count, args.dram_capacity,
        args.lookahead))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- lr: `{}`\n".format(args.lr))
    output_file.write("- weight decay: `{}`\n".format(args.weight_decay))
    output_file.write("- dropout: `{}`\n".format(args.dropout))
    output_file.write("- layers/heads: `{}/{}`\n".format(
        args.num_layers, args.num_heads))
    output_file.write("- device: `{}`\n".format(args.device))
    output_file.write("- seed: `{}`\n\n".format(args.seed))

    output_file.write("## Best Observed\n\n")
    output_file.write(
        "- lowest weighted cost: `K={}` with `{:.2f}`\n".format(
            best_cost["num_queries"], best_cost["weighted_access_cost"]))
    output_file.write(
        "- highest hit rate: `K={}` with `{:.2f}%`\n".format(
            best_hit["num_queries"], best_hit["hit_rate_percent"]))
    output_file.write(
        "- fewest NVM writes: `K={}` with `{}`\n\n".format(
            best_writes["num_queries"], best_writes["nvm_writes"]))

    output_file.write("## Results\n\n")
    output_file.write(
        "| K | Hit rate (%) | Hit delta vs baseline (pp) | Cost | "
        "Cost delta vs baseline (%) | NVM writes | "
        "Writes delta vs baseline (%) | NVM reads | Migrations | "
        "Decision ms |\n")
    output_file.write(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {num_queries} | {hit_rate_percent:.2f} | "
          "{hit_rate_delta_vs_baseline_pp:+.2f} | "
          "{weighted_access_cost:.2f} | "
          "{cost_delta_vs_baseline_percent:+.2f} | {nvm_writes} | "
          "{nvm_writes_delta_vs_baseline_percent:+.2f} | {nvm_reads} | "
          "{migrations} | {avg_decision_time_ms:.6f} |\n".format(**row))


def main():
  args = build_arg_parser().parse_args()
  queries = parse_queries(args.queries)
  if args.baseline_k not in queries:
    raise ValueError("--baseline_k={} must appear in --queries={}.".format(
        args.baseline_k, ",".join(str(value) for value in queries)))

  os.makedirs(args.result_dir, exist_ok=True)
  if not os.path.exists(args.train_trace):
    raise FileNotFoundError("Training trace not found: {}".format(
        args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError("Test trace not found: {}".format(
        args.test_trace))

  prepare_jsonl(args)

  query_results = {}
  for num_queries in queries:
    metrics, result_dir, checkpoint_path = run_query_count(args, num_queries)
    query_results[num_queries] = (metrics, result_dir, checkpoint_path)

  baseline_metrics = query_results[args.baseline_k][0]
  rows = []
  for num_queries in queries:
    metrics, result_dir, checkpoint_path = query_results[num_queries]
    row = dict(metrics)
    row["num_queries"] = num_queries
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
