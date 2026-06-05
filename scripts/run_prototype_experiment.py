# coding=utf-8
"""Run the QMAP prototype experiment end to end.

This script intentionally keeps the first experiment small and reproducible:

  1. generate QMAP JSONL training samples from a page trace
  2. train QMAP
  3. evaluate LRU / Random / LFU / CLOCK / QMAP on the test trace
  4. write JSON, CSV, and Markdown summaries under outputs/results

It shells out to the existing QMAP tools so the individual steps remain easy to
debug and rerun by hand.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QMAP_MODEL_NAME = "QMAP-CrossAttn"
QMAP_ABLATION = "cross_attention"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Run QMAP prototype experiment.")
  parser.add_argument("--run_name", default=None,
                      help="Result directory name. Default uses timestamp.")
  parser.add_argument("--train_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_train.csv"))
  parser.add_argument("--test_trace",
                      default=path_from_root("dataset", "processed",
                                             "try_test.csv"))
  parser.add_argument("--train_jsonl", default=None,
                      help="Optional generated JSONL path.")
  parser.add_argument("--checkpoint_dir", default=None,
                      help="Optional checkpoint output directory.")
  parser.add_argument("--result_dir", default=None,
                      help="Optional result output directory.")
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--device", default="cuda",
                      help="cuda, cpu, or omit only when running steps by hand.")
  parser.add_argument("--skip_generate", action="store_true")
  parser.add_argument("--skip_train", action="store_true")
  parser.add_argument("--checkpoint", default=None,
                      help="Existing checkpoint used when --skip_train is set.")
  parser.add_argument("--policies", default="lru,random,lfu,clock,qmap",
                      help="Comma-separated policies to evaluate.")
  parser.add_argument("--python", default=sys.executable,
                      help="Python executable used for QMAP subcommands.")
  parser.add_argument("--toy_records", type=int, default=20000,
                      help="Records used when auto-creating missing toy trace.")
  return parser


def run_command(command, log_path):
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  print("[run]", " ".join(command))
  with open(log_path, "w") as log_file:
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True)
    log_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def load_json(path):
  with open(path, "r") as input_file:
    return json.load(input_file)


def display_policy(policy):
  return QMAP_MODEL_NAME if policy == "qmap" else policy.upper()


def is_default_try_trace(path, split_name):
  expected = path_from_root("dataset", "processed",
                           "try_{}.csv".format(split_name))
  return os.path.abspath(path) == os.path.abspath(expected)


def is_trace_header(row):
  normalized = {column.strip().lower() for column in row}
  return bool(normalized & {"pc", "address", "addr", "rw"})


def write_trace_split(header, rows, output_path):
  os.makedirs(os.path.dirname(output_path), exist_ok=True)
  with open(output_path, "w", newline="") as output_file:
    writer = csv.writer(output_file)
    if header:
      writer.writerow(header)
    writer.writerows(rows)


def split_trace(input_path, train_path, valid_path, test_path):
  with open(input_path, "r", newline="") as input_file:
    rows = list(csv.reader(input_file))
  if not rows:
    raise ValueError("Trace is empty: {}".format(input_path))

  header = rows[0] if is_trace_header(rows[0]) else None
  data_rows = rows[1:] if header else rows
  if len(data_rows) < 10:
    raise ValueError("Trace is too small to split: {}".format(input_path))

  train_end = int(len(data_rows) * 0.8)
  valid_end = int(len(data_rows) * 0.9)
  write_trace_split(header, data_rows[:train_end], train_path)
  write_trace_split(header, data_rows[train_end:valid_end], valid_path)
  write_trace_split(header, data_rows[valid_end:], test_path)


def ensure_default_try_split(args, log_dir):
  """Creates the default toy split if dataset/processed/try_*.csv is missing."""
  train_is_default = is_default_try_trace(args.train_trace, "train")
  test_is_default = is_default_try_trace(args.test_trace, "test")
  if not (train_is_default and test_is_default):
    return
  if os.path.exists(args.train_trace) and os.path.exists(args.test_trace):
    return

  raw_trace = path_from_root("dataset", "raw_traces", "try.csv")
  valid_trace = path_from_root("dataset", "processed", "try_valid.csv")
  os.makedirs(os.path.dirname(raw_trace), exist_ok=True)
  os.makedirs(os.path.dirname(args.train_trace), exist_ok=True)

  build_command = [
      args.python, "qmap/trace_builder.py",
      "--output", raw_trace,
      "--page_shift", str(args.page_shift),
      "--records", str(args.toy_records),
      "--working_set_pages", "512",
      "--hot_pages", "64",
      "--write_ratio", "0.30",
      "--phase_length", "2000",
      "--seed", "3136859",
  ]
  print("[info] default toy split is missing; creating dataset/processed/try_*.csv")
  run_command(build_command, os.path.join(log_dir, "build_default_trace.log"))
  split_trace(raw_trace, args.train_trace, valid_trace, args.test_trace)


def write_summary_csv(rows, output_path):
  fields = [
      "policy",
      "hit_rate_percent",
      "nvm_writes",
      "weighted_access_cost",
      "migrations",
      "avg_decision_time_ms",
      "decision_count",
      "total_accesses",
      "misses",
      "nvm_reads",
  ]
  with open(output_path, "w", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def write_summary_markdown(rows, output_path, args):
  with open(output_path, "w") as output_file:
    output_file.write("# QMAP Prototype Experiment\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- train trace: `{}`\n".format(args.train_trace))
    output_file.write("- test trace: `{}`\n".format(args.test_trace))
    output_file.write("- DRAM capacity: `{}` pages\n".format(
        args.dram_capacity))
    output_file.write("- history length: `{}`\n".format(args.history_length))
    output_file.write("- candidate count: `{}`\n".format(
        args.candidate_count))
    output_file.write("- lookahead: `{}`\n".format(args.lookahead))
    output_file.write("- QMAP model: `{}` (`ablation={}`)\n".format(
        QMAP_MODEL_NAME, QMAP_ABLATION))
    output_file.write("- page shift: `{}`\n".format(args.page_shift))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n\n".format(args.batch_size))
    output_file.write("## Results\n\n")
    output_file.write(
        "| Policy | Hit rate (%) | NVM writes | Weighted cost | "
        "Migrations | Avg decision ms |\n")
    output_file.write(
        "|---|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {policy} | {hit_rate:.2f} | {writes} | {cost:.2f} | "
          "{migrations} | {decision_ms:.6f} |\n".format(
              policy=display_policy(row["policy"]),
              hit_rate=row["hit_rate_percent"],
              writes=row["nvm_writes"],
              cost=row["weighted_access_cost"],
              migrations=row["migrations"],
              decision_ms=row["avg_decision_time_ms"]))


def main():
  args = build_arg_parser().parse_args()
  run_name = args.run_name or datetime.now().strftime("prototype_%Y%m%d_%H%M%S")
  result_dir = args.result_dir or path_from_root("outputs", "results", run_name)
  checkpoint_dir = args.checkpoint_dir or path_from_root(
      "outputs", "checkpoints", run_name)
  train_jsonl = args.train_jsonl or path_from_root(
      "dataset", "jsonl", "{}_train.jsonl".format(run_name))
  log_dir = os.path.join(result_dir, "logs")

  os.makedirs(result_dir, exist_ok=True)
  if not args.skip_train:
    os.makedirs(checkpoint_dir, exist_ok=True)
  os.makedirs(os.path.dirname(train_jsonl), exist_ok=True)

  ensure_default_try_split(args, log_dir)
  if not os.path.exists(args.train_trace):
    raise FileNotFoundError(
        "Training trace not found: {}. Provide --train_trace or put the file "
        "under dataset/processed/.".format(args.train_trace))
  if not os.path.exists(args.test_trace):
    raise FileNotFoundError(
        "Test trace not found: {}. Provide --test_trace or put the file under "
        "dataset/processed/.".format(args.test_trace))

  if not args.skip_generate:
    generate_command = [
        args.python, "qmap/qmap_generator.py",
        "--input", args.train_trace,
        "--output", train_jsonl,
        "--history_length", str(args.history_length),
        "--candidate_count", str(args.candidate_count),
        "--lookahead", str(args.lookahead),
        "--dram_capacity", str(args.dram_capacity),
        "--page_shift", str(args.page_shift),
        "--ablation", QMAP_ABLATION,
    ]
    run_command(generate_command, os.path.join(log_dir, "generate.log"))

  checkpoint_path = args.checkpoint
  if not args.skip_train:
    train_command = [
        args.python, "qmap/qmap_train.py",
        "--train_data", train_jsonl,
        "--output_dir", checkpoint_dir,
        "--epochs", str(args.epochs),
        "--batch_size", str(args.batch_size),
        "--lr", str(args.lr),
        "--device", args.device,
        "--ablation", QMAP_ABLATION,
    ]
    run_command(train_command, os.path.join(log_dir, "train.log"))
    checkpoint_path = os.path.join(
        checkpoint_dir, "qmap_epoch_{}.pth".format(args.epochs))

  rows = []
  policies = [policy.strip() for policy in args.policies.split(",")
              if policy.strip()]
  for policy in policies:
    json_output = os.path.join(result_dir, "{}.json".format(policy))
    eval_command = [
        args.python, "qmap/qmap_eval.py",
        "--trace_path", args.test_trace,
        "--policy", policy,
        "--dram_capacity", str(args.dram_capacity),
        "--page_shift", str(args.page_shift),
        "--history_length", str(args.history_length),
        "--candidate_count", str(args.candidate_count),
        "--json_output", json_output,
    ]
    if policy == "qmap":
      if not checkpoint_path:
        raise ValueError("QMAP evaluation needs --checkpoint or training.")
      eval_command.extend([
          "--checkpoint", checkpoint_path,
          "--device", args.device,
          "--ablation", QMAP_ABLATION,
      ])
    run_command(eval_command, os.path.join(log_dir, "{}.log".format(policy)))
    rows.append(load_json(json_output))

  write_summary_csv(rows, os.path.join(result_dir, "summary.csv"))
  write_summary_markdown(rows, os.path.join(result_dir, "summary.md"), args)

  print("[done] result_dir={}".format(result_dir))
  print("[done] summary={}".format(os.path.join(result_dir, "summary.md")))


if __name__ == "__main__":
  main()
