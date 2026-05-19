# coding=utf-8
"""Evaluate a range of QMAP checkpoints and rank replay metrics.

The sweep intentionally evaluates saved checkpoints by replay cost instead of
assuming the last epoch is best.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHECKPOINT_RE = re.compile(r"qmap_epoch_(\d+)\.pth$")
QMAP_MODEL_NAME = "QMAP-Pool"
QMAP_ABLATION = "mean_pool"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Sweep QMAP checkpoints with trace replay evaluation.")
  parser.add_argument(
      "--checkpoint_dir",
      default=path_from_root("outputs", "checkpoints", "try_prototype"),
      help="Directory containing qmap_epoch_N.pth checkpoints.")
  parser.add_argument(
      "--trace_path",
      default=path_from_root("dataset", "processed", "try_test.csv"),
      help="Replay trace used to score checkpoints.")
  parser.add_argument(
      "--result_dir",
      default=path_from_root("outputs", "results", "checkpoint_sweep"),
      help="Directory for per-checkpoint JSON and summary files.")
  parser.add_argument("--epoch_start", type=int, default=1)
  parser.add_argument("--epoch_end", type=int, default=10)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument(
      "--device",
      default="cpu",
      help="Evaluation device passed to qmap_eval.py. Use cuda for GPU.")
  parser.add_argument("--ablation", default=QMAP_ABLATION,
                      choices=("full", "no_pc", "no_rw", "mean_pool",
                               "no_qformer", "no_cost"),
                      help="Evaluation ablation. New experiments use mean_pool.")
  parser.add_argument("--python", default=sys.executable)
  return parser


def discover_checkpoints(checkpoint_dir, epoch_start, epoch_end):
  checkpoints = []
  for name in os.listdir(checkpoint_dir):
    match = CHECKPOINT_RE.match(name)
    if not match:
      continue
    epoch = int(match.group(1))
    if epoch_start <= epoch <= epoch_end:
      checkpoints.append((epoch, os.path.join(checkpoint_dir, name)))
  return sorted(checkpoints)


def run_eval(args, epoch, checkpoint_path, json_output, log_output):
  command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", args.trace_path,
      "--policy", "qmap",
      "--checkpoint", checkpoint_path,
      "--device", args.device,
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--ablation", args.ablation,
      "--json_output", json_output,
  ]
  print("[run] epoch={} checkpoint={}".format(epoch, checkpoint_path),
        flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  with open(log_output, "w") as output_file:
    output_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)


def load_json(path):
  with open(path, "r") as input_file:
    return json.load(input_file)


def checkpoint_label(row):
  return "epoch {} ({})".format(row["epoch"], row["checkpoint"])


def write_summary_csv(rows, output_path):
  fields = [
      "epoch",
      "checkpoint",
      "weighted_access_cost",
      "nvm_writes",
      "nvm_reads",
      "migrations",
      "hit_rate_percent",
      "misses",
      "decision_count",
      "avg_decision_time_ms",
      "total_accesses",
  ]
  with open(output_path, "w", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def write_summary_markdown(rows, output_path, args):
  best_cost = min(rows, key=lambda row: (
      row["weighted_access_cost"], row["nvm_writes"], row["epoch"]))
  best_writes = min(rows, key=lambda row: (
      row["nvm_writes"], row["weighted_access_cost"], row["epoch"]))

  with open(output_path, "w") as output_file:
    output_file.write("# QMAP Checkpoint Sweep\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- trace: `{}`\n".format(args.trace_path))
    output_file.write("- checkpoint dir: `{}`\n".format(args.checkpoint_dir))
    output_file.write("- epoch range: `{}..{}`\n".format(
        args.epoch_start, args.epoch_end))
    output_file.write("- DRAM capacity: `{}` pages\n".format(
        args.dram_capacity))
    output_file.write("- history length: `{}`\n".format(args.history_length))
    output_file.write("- candidate count: `{}`\n".format(
        args.candidate_count))
    output_file.write("- QMAP model: `{}` (`ablation={}`)\n".format(
        QMAP_MODEL_NAME, args.ablation))
    output_file.write("- page shift: `{}`\n".format(args.page_shift))
    output_file.write("- device: `{}`\n\n".format(args.device))
    output_file.write("## Selection\n\n")
    output_file.write(
        "- lowest weighted cost: `{}` with cost `{:.2f}` and NVM writes `{}`\n"
        .format(checkpoint_label(best_cost),
                best_cost["weighted_access_cost"],
                best_cost["nvm_writes"]))
    output_file.write(
        "- fewest NVM writes: `{}` with writes `{}` and cost `{:.2f}`\n\n"
        .format(checkpoint_label(best_writes),
                best_writes["nvm_writes"],
                best_writes["weighted_access_cost"]))
    output_file.write(
        "Do not assume the final epoch is best; select the checkpoint by "
        "validation or replay cost for the reported experiment.\n\n")
    output_file.write("## Results\n\n")
    output_file.write(
        "| Epoch | Weighted cost | NVM writes | NVM reads | Migrations | "
        "Hit rate (%) | Avg decision ms |\n")
    output_file.write("|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {epoch} | {cost:.2f} | {writes} | {reads} | {migrations} | "
          "{hit_rate:.2f} | {decision_ms:.6f} |\n".format(
              epoch=row["epoch"],
              cost=row["weighted_access_cost"],
              writes=row["nvm_writes"],
              reads=row["nvm_reads"],
              migrations=row["migrations"],
              hit_rate=row["hit_rate_percent"],
              decision_ms=row["avg_decision_time_ms"]))


def main():
  args = build_arg_parser().parse_args()
  if not os.path.isdir(args.checkpoint_dir):
    raise FileNotFoundError("Checkpoint directory not found: {}".format(
        args.checkpoint_dir))
  if not os.path.exists(args.trace_path):
    raise FileNotFoundError("Trace not found: {}".format(args.trace_path))

  checkpoints = discover_checkpoints(
      args.checkpoint_dir, args.epoch_start, args.epoch_end)
  expected = set(range(args.epoch_start, args.epoch_end + 1))
  found = {epoch for epoch, _ in checkpoints}
  missing = sorted(expected - found)
  if missing:
    raise FileNotFoundError("Missing checkpoint epochs: {}".format(missing))

  json_dir = os.path.join(args.result_dir, "json")
  log_dir = os.path.join(args.result_dir, "logs")
  os.makedirs(json_dir, exist_ok=True)
  os.makedirs(log_dir, exist_ok=True)

  rows = []
  for epoch, checkpoint_path in checkpoints:
    json_output = os.path.join(json_dir, "qmap_epoch_{}.json".format(epoch))
    log_output = os.path.join(log_dir, "qmap_epoch_{}.log".format(epoch))
    run_eval(args, epoch, checkpoint_path, json_output, log_output)
    row = load_json(json_output)
    row["epoch"] = epoch
    row["checkpoint"] = checkpoint_path
    rows.append(row)

  rows.sort(key=lambda row: row["epoch"])
  write_summary_csv(rows, os.path.join(args.result_dir, "summary.csv"))
  write_summary_markdown(rows, os.path.join(args.result_dir, "summary.md"),
                         args)
  best_cost = min(rows, key=lambda row: (
      row["weighted_access_cost"], row["nvm_writes"], row["epoch"]))
  best_writes = min(rows, key=lambda row: (
      row["nvm_writes"], row["weighted_access_cost"], row["epoch"]))
  print("[done] result_dir={}".format(args.result_dir))
  print("[done] lowest weighted cost: epoch {} cost {:.2f} writes {}".format(
      best_cost["epoch"], best_cost["weighted_access_cost"],
      best_cost["nvm_writes"]))
  print("[done] fewest NVM writes: epoch {} writes {} cost {:.2f}".format(
      best_writes["epoch"], best_writes["nvm_writes"],
      best_writes["weighted_access_cost"]))


if __name__ == "__main__":
  main()
