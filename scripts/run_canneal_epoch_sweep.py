# coding=utf-8
"""Evaluate canneal checkpoints across epochs and diagnose victim quality."""

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)
QMAP_DIR = os.path.join(PROJECT_ROOT, "qmap")
if QMAP_DIR not in sys.path:
  sys.path.insert(0, QMAP_DIR)

from qmap.qmap_generator import read_trace


QMAP_ABLATION = "cross_attention"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def run_command(command, log_path):
  os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
  print("[run] {}".format(" ".join(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      universal_newlines=True)
  with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def percentile(values, percent):
  values = sorted(values)
  if not values:
    return math.nan
  rank = (len(values) - 1) * percent / 100.0
  lower = int(math.floor(rank))
  upper = int(math.ceil(rank))
  if lower == upper:
    return float(values[lower])
  weight = rank - lower
  return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def summarize_distances(values):
  finite = [value for value in values if value != math.inf]
  if not values:
    return {
        "median": "",
        "p25": "",
        "p75": "",
        "inf_count": 0,
        "total": 0,
    }
  if not finite:
    return {
        "median": "inf",
        "p25": "inf",
        "p75": "inf",
        "inf_count": len(values),
        "total": len(values),
    }
  return {
      "median": statistics.median(finite),
      "p25": percentile(finite, 25),
      "p75": percentile(finite, 75),
      "inf_count": len(values) - len(finite),
      "total": len(values),
  }


def next_distance(trace, start_index, page):
  for index in range(start_index + 1, len(trace)):
    if trace[index]["page"] == page:
      return index - start_index
  return math.inf


def victim_diagnostics(trace_path, checkpoint_path, args, candidate_count):
  import torch
  from qmap.qmap_eval import QMAPPolicy

  trace, _ = read_trace(trace_path, args.page_shift)
  policy = QMAPPolicy(
      checkpoint_path,
      torch.device(args.device),
      args.history_length,
      candidate_count,
      args.lookahead,
      QMAP_ABLATION)

  dram = []
  history = []
  dram_insert_time = {}
  dirty_pages = set()
  ranks = []
  chosen_distances = []
  lru_distances = []
  worse_than_lru = 0
  short_reuse = 0

  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = access["rw"]
    if page in dram:
      dram.remove(page)
      dram.insert(0, page)
      if rw:
        dirty_pages.add(page)
    else:
      if len(dram) >= args.dram_capacity:
        candidates = list(reversed(dram[-candidate_count:]))
        decision_history = (history + [access])[-args.history_length:]
        victim = policy.choose_victim(
            dram, decision_history, 0, access_index, dram_insert_time,
            dirty_pages)
        lru_victim = dram[-1]
        chosen_distance = next_distance(trace, access_index, victim)
        lru_distance = next_distance(trace, access_index, lru_victim)
        ranks.append(candidates.index(victim) if victim in candidates else -1)
        chosen_distances.append(chosen_distance)
        lru_distances.append(lru_distance)
        if chosen_distance < lru_distance:
          worse_than_lru += 1
        if chosen_distance != math.inf and chosen_distance <= 10:
          short_reuse += 1
        dram.remove(victim)
        dram_insert_time.pop(victim, None)
        dirty_pages.discard(victim)

      dram.insert(0, page)
      dram_insert_time[page] = access_index
      if rw:
        dirty_pages.add(page)

    history.append(access)
    if len(history) > args.history_length:
      history.pop(0)

  chosen = summarize_distances(chosen_distances)
  lru = summarize_distances(lru_distances)
  return {
      "diagnostic_decisions": len(ranks),
      "worse_than_lru": worse_than_lru,
      "short_reuse_le_10": short_reuse,
      "chosen_median": chosen["median"],
      "chosen_p25": chosen["p25"],
      "chosen_p75": chosen["p75"],
      "chosen_inf_count": chosen["inf_count"],
      "lru_median": lru["median"],
      "lru_p25": lru["p25"],
      "lru_p75": lru["p75"],
      "lru_inf_count": lru["inf_count"],
      "top_ranks": repr(Counter(ranks).most_common(8)),
  }


def eval_policy(args, policy, output_path, log_path, checkpoint_path=None):
  command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", args.trace_path,
      "--policy", policy,
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--lookahead", str(args.lookahead),
      "--random_seed", str(args.random_seed),
      "--json_output", output_path,
  ]
  if policy == "qmap":
    command.extend([
        "--checkpoint", checkpoint_path,
        "--ablation", QMAP_ABLATION,
        "--device", args.device,
    ])
  run_command(command, log_path)
  return load_json(output_path)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Sweep canneal QMAP checkpoints across epochs.")
  parser.add_argument("--trace_path", default=path_from_root(
      "dataset", "processed", "real_workload_suite", "1m",
      "parsec_canneal_test.csv"))
  parser.add_argument("--checkpoint_dir", default=path_from_root(
      "outputs", "checkpoints", "real_workload_suite", "1m",
      "parsec_canneal"))
  parser.add_argument("--output_dir", default=path_from_root(
      "outputs", "results", "real_workload_suite", "1m",
      "canneal_epoch_sweep"))
  parser.add_argument("--epochs", default="1,2,3,4,5,6,7,8,9,10")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--dram_capacity", type=int, default=16)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=8)
  parser.add_argument("--eval_candidate_counts", default="8",
                      help=("Comma-separated candidate counts to use at eval "
                            "time for QMAP checkpoints, e.g. 1,2,4,8."))
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--random_seed", type=int, default=0)
  parser.add_argument("--skip_baselines", action="store_true")
  parser.add_argument("--skip_diagnostics", action="store_true")
  return parser


def write_outputs(rows, output_dir):
  fields = [
      "epoch",
      "eval_candidate_count",
      "policy",
      "weighted_access_cost",
      "hit_rate_percent",
      "nvm_writes",
      "migrations",
      "decision_count",
      "avg_decision_time_ms",
      "delta_vs_best_baseline_percent",
      "diagnostic_decisions",
      "worse_than_lru",
      "short_reuse_le_10",
      "chosen_median",
      "chosen_p25",
      "chosen_p75",
      "chosen_inf_count",
      "lru_median",
      "lru_p25",
      "lru_p75",
      "lru_inf_count",
      "top_ranks",
      "checkpoint",
  ]
  csv_path = os.path.join(output_dir, "summary.csv")
  with open(csv_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})

  md_path = os.path.join(output_dir, "summary.md")
  with open(md_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Canneal Epoch Sweep\n\n")
    output_file.write(
        "| Epoch | Cost | Delta vs best baseline | Migrations | Writes | "
        "Worse than LRU | Chosen median | LRU median | Top ranks |\n")
    output_file.write("|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
    for row in rows:
      if row["policy"] != "qmap":
        continue
      output_file.write(
          "| {epoch}/{eval_candidate_count} | {weighted_access_cost:.2f} | "
          "{delta_vs_best_baseline_percent:+.2f}% | {migrations} | "
          "{nvm_writes} | {worse_than_lru} | {chosen_median} | "
          "{lru_median} | {top_ranks} |\n".format(**row))
  return csv_path, md_path


def main():
  args = build_arg_parser().parse_args()
  os.makedirs(args.output_dir, exist_ok=True)
  log_dir = os.path.join(args.output_dir, "logs")
  json_dir = os.path.join(args.output_dir, "json")
  os.makedirs(json_dir, exist_ok=True)

  baseline_rows = []
  if not args.skip_baselines:
    for policy in ("lru", "random", "lfu", "clock"):
      row = eval_policy(
          args, policy,
          os.path.join(json_dir, "{}.json".format(policy)),
          os.path.join(log_dir, "{}.log".format(policy)))
      baseline_rows.append(row)
  best_baseline = min(
      baseline_rows,
      key=lambda row: (row["weighted_access_cost"], row["nvm_writes"],
                       -row["hit_rate_percent"]))
  best_cost = float(best_baseline["weighted_access_cost"])

  rows = []
  for row in baseline_rows:
    row = dict(row)
    row["epoch"] = "baseline"
    row["eval_candidate_count"] = ""
    row["delta_vs_best_baseline_percent"] = 0.0
    rows.append(row)

  eval_candidate_counts = [
      int(item.strip()) for item in args.eval_candidate_counts.split(",")
      if item.strip()
  ]
  if not eval_candidate_counts:
    raise ValueError("At least one eval candidate count is required.")

  for epoch_text in [item.strip() for item in args.epochs.split(",")
                     if item.strip()]:
    epoch = int(epoch_text)
    checkpoint_path = os.path.join(
        args.checkpoint_dir, "qmap_epoch_{}.pth".format(epoch))
    if not os.path.exists(checkpoint_path):
      raise FileNotFoundError(checkpoint_path)
    original_candidate_count = args.candidate_count
    for eval_candidate_count in eval_candidate_counts:
      args.candidate_count = eval_candidate_count
      row = eval_policy(
          args, "qmap",
          os.path.join(
              json_dir,
              "qmap_epoch_{}_c{}.json".format(epoch, eval_candidate_count)),
          os.path.join(
              log_dir,
              "qmap_epoch_{}_c{}.log".format(epoch, eval_candidate_count)),
          checkpoint_path)
      row["epoch"] = epoch
      row["eval_candidate_count"] = eval_candidate_count
      row["checkpoint"] = checkpoint_path
      row["delta_vs_best_baseline_percent"] = (
          (row["weighted_access_cost"] - best_cost) * 100.0 / best_cost)
      if not args.skip_diagnostics:
        row.update(victim_diagnostics(
            args.trace_path, checkpoint_path, args, eval_candidate_count))
      rows.append(row)
    args.candidate_count = original_candidate_count

  csv_path, md_path = write_outputs(rows, args.output_dir)
  print("[done] csv={}".format(csv_path))
  print("[done] md={}".format(md_path))


if __name__ == "__main__":
  main()
