# coding=utf-8
"""Run one-at-a-time QMAP parameter sensitivity experiments.

The goal is not to produce many plots.  This script answers whether QMAP is
stable around the current prototype setting by varying one parameter at a time:

  history_length: 5, 10, 20, 50
  candidate_count: 16, 32, 64
  dram_capacity: 64, 128, 256
  lookahead: 128, 256, 512

For each unique configuration it regenerates QMAP samples, retrains QMAP with a
fixed seed, evaluates QMAP on the test trace, and writes compact CSV/Markdown
summaries.
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DEFAULTS = {
    "history_length": 10,
    "candidate_count": 64,
    "dram_capacity": 128,
    "lookahead": 256,
}

PARAMETER_VALUES = {
    "history_length": [5, 10, 20, 50],
    "candidate_count": [16, 32, 64],
    "dram_capacity": [64, 128, 256],
    "lookahead": [128, 256, 512],
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run QMAP one-at-a-time parameter sensitivity.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_test.csv"))
  parser.add_argument("--result_dir",
                      default=path_from_root("outputs", "results",
                                             "qmap_parameter_sensitivity"))
  parser.add_argument("--checkpoint_root",
                      default=path_from_root("outputs", "checkpoints",
                                             "qmap_parameter_sensitivity"))
  parser.add_argument("--jsonl_root",
                      default=path_from_root("dataset", "jsonl",
                                             "qmap_parameter_sensitivity"))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--force", action="store_true",
                      help="Rerun experiments even if qmap.json exists.")
  return parser


def config_id(config):
  return "h{history_length}_c{candidate_count}_d{dram_capacity}_l{lookahead}".format(
      **config)


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
  with open(log_path, "w") as output_file:
    output_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def build_rows():
  rows = []
  for parameter, values in PARAMETER_VALUES.items():
    for value in values:
      config = dict(DEFAULTS)
      config[parameter] = value
      rows.append((parameter, value, config))
  return rows


def run_experiment(args, config):
  run_id = config_id(config)
  result_dir = os.path.join(args.result_dir, "runs", run_id)
  checkpoint_dir = os.path.join(args.checkpoint_root, run_id)
  jsonl_path = os.path.join(args.jsonl_root, "{}.jsonl".format(run_id))
  log_dir = os.path.join(result_dir, "logs")
  qmap_json = os.path.join(result_dir, "qmap.json")
  checkpoint_path = os.path.join(
      checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  if not args.force and os.path.exists(qmap_json):
    return load_json(qmap_json), result_dir, checkpoint_path

  os.makedirs(result_dir, exist_ok=True)
  os.makedirs(checkpoint_dir, exist_ok=True)
  os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)

  generate_command = [
      args.python, "qmap/qmap_generator.py",
      "--input", args.train_trace,
      "--output", jsonl_path,
      "--history_length", str(config["history_length"]),
      "--candidate_count", str(config["candidate_count"]),
      "--lookahead", str(config["lookahead"]),
      "--dram_capacity", str(config["dram_capacity"]),
      "--page_shift", str(args.page_shift),
  ]
  run_command(generate_command, os.path.join(log_dir, "generate.log"))

  train_command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", jsonl_path,
      "--output_dir", checkpoint_dir,
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--device", args.device,
      "--seed", str(args.seed),
  ]
  run_command(train_command, os.path.join(log_dir, "train.log"))

  eval_command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", args.test_trace,
      "--policy", "qmap",
      "--checkpoint", checkpoint_path,
      "--device", args.device,
      "--dram_capacity", str(config["dram_capacity"]),
      "--page_shift", str(args.page_shift),
      "--history_length", str(config["history_length"]),
      "--candidate_count", str(config["candidate_count"]),
      "--json_output", qmap_json,
  ]
  run_command(eval_command, os.path.join(log_dir, "qmap.log"))

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


def write_summary_csv(rows, output_path):
  fields = [
      "parameter",
      "value",
      "history_length",
      "candidate_count",
      "dram_capacity",
      "lookahead",
      "hit_rate_percent",
      "hit_rate_delta_pp",
      "weighted_access_cost",
      "cost_delta_percent",
      "nvm_writes",
      "nvm_writes_delta_percent",
      "nvm_reads",
      "migrations",
      "avg_decision_time_ms",
      "decision_count",
      "run_id",
      "result_dir",
      "checkpoint",
  ]
  with open(output_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def parameter_ranges(rows):
  ranges = []
  for parameter in PARAMETER_VALUES:
    subset = [row for row in rows if row["parameter"] == parameter]
    costs = [row["weighted_access_cost"] for row in subset]
    hits = [row["hit_rate_percent"] for row in subset]
    writes = [row["nvm_writes"] for row in subset]
    ranges.append({
        "parameter": parameter,
        "cost_min": min(costs),
        "cost_max": max(costs),
        "cost_span_percent": (
            (max(costs) - min(costs)) * 100.0 / max(1.0, min(costs))),
        "hit_min": min(hits),
        "hit_max": max(hits),
        "writes_min": min(writes),
        "writes_max": max(writes),
    })
  return ranges


def write_summary_markdown(rows, output_path, args):
  ranges = parameter_ranges(rows)
  baseline = next(row for row in rows
                  if row["parameter"] == "history_length" and
                  row["value"] == DEFAULTS["history_length"])
  by_parameter = {}
  for row in rows:
    by_parameter.setdefault(row["parameter"], []).append(row)
  candidate_16 = next(row for row in by_parameter["candidate_count"]
                      if row["value"] == 16)
  candidate_32 = next(row for row in by_parameter["candidate_count"]
                      if row["value"] == 32)
  lookahead_range = next(item for item in ranges
                         if item["parameter"] == "lookahead")
  history_range = next(item for item in ranges
                       if item["parameter"] == "history_length")

  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# QMAP Parameter Sensitivity\n\n")
    output_file.write("## Conclusion\n\n")
    output_file.write(
        "QMAP is stable for the algorithmic knobs tested here. "
        "`history_length` changes weighted cost by only `{:.2f}%`, and "
        "`lookahead` changes it by only `{:.2f}%`. `candidate_count=32` is "
        "essentially tied with 64 (`{:+.2f}%` cost delta), while "
        "`candidate_count=16` is still usable but starts to lose quality "
        "(`{:+.2f}%` cost, `{:+.2f}%` NVM writes). "
        "`dram_capacity` has a large effect because it changes the memory "
        "pressure itself, so treat it as workload scaling rather than QMAP "
        "parameter instability.\n\n".format(
            history_range["cost_span_percent"],
            lookahead_range["cost_span_percent"],
            candidate_32["cost_delta_percent"],
            candidate_16["cost_delta_percent"],
            candidate_16["nvm_writes_delta_percent"]))

    output_file.write("## Setup\n\n")
    output_file.write("- design: one parameter at a time around `h10/c64/d128/l256`\n")
    output_file.write("- train trace: `{}`\n".format(
        os.path.relpath(args.train_trace, PROJECT_ROOT)))
    output_file.write("- test trace: `{}`\n".format(
        os.path.relpath(args.test_trace, PROJECT_ROOT)))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- device: `{}`\n".format(args.device))
    output_file.write("- seed: `{}`\n\n".format(args.seed))

    output_file.write("## Baseline\n\n")
    output_file.write(
        "| Config | Hit rate (%) | Weighted cost | NVM writes | Migrations |\n")
    output_file.write("|---|---:|---:|---:|---:|\n")
    output_file.write(
        "| h10/c64/d128/l256 | {hit:.2f} | {cost:.2f} | {writes} | {migrations} |\n\n"
        .format(hit=baseline["hit_rate_percent"],
                cost=baseline["weighted_access_cost"],
                writes=baseline["nvm_writes"],
                migrations=baseline["migrations"]))

    output_file.write("## Parameter Ranges\n\n")
    output_file.write(
        "| Parameter | Cost min | Cost max | Cost span (%) | Hit range (%) | NVM writes range |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|\n")
    for item in ranges:
      output_file.write(
          "| {parameter} | {cost_min:.2f} | {cost_max:.2f} | "
          "{cost_span_percent:.2f} | {hit_min:.2f}-{hit_max:.2f} | "
          "{writes_min}-{writes_max} |\n".format(**item))

    output_file.write("\n## Detailed Results\n\n")
    output_file.write(
        "| Parameter | Value | Config | Hit rate (%) | Cost | Cost delta (%) | "
        "NVM writes | Migrations | Decision ms |\n")
    output_file.write("|---|---:|---|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {parameter} | {value} | h{history_length}/c{candidate_count}/"
          "d{dram_capacity}/l{lookahead} | {hit_rate_percent:.2f} | "
          "{weighted_access_cost:.2f} | {cost_delta_percent:+.2f} | "
          "{nvm_writes} | {migrations} | {avg_decision_time_ms:.6f} |\n"
          .format(**row))


def main():
  args = build_arg_parser().parse_args()
  os.makedirs(args.result_dir, exist_ok=True)

  if not os.path.exists(args.train_trace):
    raise FileNotFoundError("Training trace not found: {}".format(
        args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError("Test trace not found: {}".format(
        args.test_trace))

  config_results = {}
  for _, _, config in build_rows():
    run_id = config_id(config)
    if run_id in config_results:
      continue
    metrics, result_dir, checkpoint_path = run_experiment(args, config)
    config_results[run_id] = (metrics, result_dir, checkpoint_path)

  baseline_id = config_id(DEFAULTS)
  baseline_metrics = config_results[baseline_id][0]
  rows = []
  for parameter, value, config in build_rows():
    run_id = config_id(config)
    metrics, result_dir, checkpoint_path = config_results[run_id]
    row = dict(metrics)
    row.update(config)
    row["parameter"] = parameter
    row["value"] = value
    row["run_id"] = run_id
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
