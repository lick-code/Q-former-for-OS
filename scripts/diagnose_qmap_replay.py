# coding=utf-8
"""Diagnose real-trace QMAP replay failures.

The script has two jobs:

  1. For QMAP runs with checkpoints, compare each QMAP victim against LRU and
     the offline best candidate by future reuse distance.
  2. Scan raw dedup windows so a pressure test can avoid low-pressure tails.

It is intentionally read-only unless --output points to a file.
"""

import argparse
import csv
import math
import os
import statistics
import sys
from collections import Counter


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)
QMAP_DIR = os.path.join(PROJECT_ROOT, "qmap")
if QMAP_DIR not in sys.path:
  sys.path.insert(0, QMAP_DIR)

from qmap.qmap_generator import read_trace


DEFAULT_WORKLOADS = (
    "parsec_blackscholes",
    "parsec_canneal",
    "parsec_streamcluster",
    "parsec_dedup",
)


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Diagnose QMAP real-trace replay behavior.")
  parser.add_argument("--result_dir", default=path_from_root(
      "outputs", "results", "real_pilot_dram16"))
  parser.add_argument("--checkpoint_dir", default=path_from_root(
      "outputs", "checkpoints", "real_pilot_dram16"))
  parser.add_argument("--workloads", default=",".join(DEFAULT_WORKLOADS))
  parser.add_argument("--dram_capacity", type=int, default=16)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--dedup_raw_trace", default=path_from_root(
      "dataset", "raw_traces", "parsec_dedup.csv"))
  parser.add_argument("--window_size", type=int, default=10000)
  parser.add_argument("--window_step", type=int, default=1000)
  parser.add_argument("--output", default=path_from_root(
      "outputs", "results", "real_pilot_diagnosis.md"),
                      help="Markdown output path, or '-' for stdout only.")
  return parser


def load_summary_rows(result_dir):
  path = os.path.join(result_dir, "summary.csv")
  if not os.path.exists(path):
    return []
  with open(path, newline="", encoding="utf-8") as input_file:
    return list(csv.DictReader(input_file))


def next_distance(trace, start_index, page):
  for index in range(start_index + 1, len(trace)):
    if trace[index]["page"] == page:
      return index - start_index
  return math.inf


def summarize_distances(values):
  finite = [value for value in values if value != math.inf]
  if not values:
    return "n/a"
  if not finite:
    return "all inf"
  return "median={:.1f}, p25={:.1f}, p75={:.1f}, inf={}/{}".format(
      statistics.median(finite),
      percentile(finite, 25),
      percentile(finite, 75),
      len(values) - len(finite),
      len(values))


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


def simulate_lru_pressure(trace, dram_capacity):
  dram = []
  misses = 0
  decisions = 0
  for access in trace:
    page = access["page"]
    if page in dram:
      dram.remove(page)
      dram.insert(0, page)
      continue
    misses += 1
    if len(dram) >= dram_capacity:
      decisions += 1
      dram.pop()
    dram.insert(0, page)
  return misses, decisions


def qmap_choice_diagnostics(workload, args):
  try:
    import torch
    from qmap.qmap_eval import QMAPPolicy
  except ImportError as error:
    return {"error": "torch/QMAP import unavailable: {}".format(error)}

  trace_path = path_from_root(
      "dataset", "processed", "{}_test.csv".format(workload))
  checkpoint_path = os.path.join(
      args.checkpoint_dir, workload, "qmap_epoch_10.pth")
  if not os.path.exists(trace_path):
    return {"error": "missing test trace: {}".format(trace_path)}
  if not os.path.exists(checkpoint_path):
    return {"error": "missing checkpoint: {}".format(checkpoint_path)}

  trace, _ = read_trace(trace_path, args.page_shift)
  policy = QMAPPolicy(
      checkpoint_path,
      torch.device(args.device),
      args.history_length,
      args.candidate_count,
      "mean_pool")

  dram = []
  history = []
  dram_insert_time = {}
  dirty_pages = set()
  ranks = []
  chosen_distances = []
  lru_distances = []
  oracle_distances = []
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
        candidates = list(reversed(dram[-args.candidate_count:]))
        decision_history = (history + [access])[-args.history_length:]
        victim = policy.choose_victim(
            dram, decision_history, 0, access_index, dram_insert_time,
            dirty_pages)
        lru_victim = dram[-1]
        oracle_victim = max(
            candidates,
            key=lambda candidate: next_distance(trace, access_index,
                                                candidate))
        chosen_distance = next_distance(trace, access_index, victim)
        lru_distance = next_distance(trace, access_index, lru_victim)
        oracle_distance = next_distance(trace, access_index, oracle_victim)

        ranks.append(candidates.index(victim) if victim in candidates else -1)
        chosen_distances.append(chosen_distance)
        lru_distances.append(lru_distance)
        oracle_distances.append(oracle_distance)
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

  return {
      "decisions": len(ranks),
      "rank_counts": Counter(ranks).most_common(8),
      "chosen_distance": summarize_distances(chosen_distances),
      "lru_distance": summarize_distances(lru_distances),
      "oracle_distance": summarize_distances(oracle_distances),
      "worse_than_lru": worse_than_lru,
      "short_reuse": short_reuse,
  }


def scan_dedup_windows(raw_trace, page_shift, window_size, window_step):
  if not os.path.exists(raw_trace):
    return []
  trace, _ = read_trace(raw_trace, page_shift)
  rows = []
  for start in range(0, len(trace) - window_size + 1, window_step):
    window = trace[start:start + window_size]
    unique_pages = len({access["page"] for access in window})
    write_ratio = (
        sum(access["rw"] for access in window) / float(len(window)))
    misses16, decisions16 = simulate_lru_pressure(window, 16)
    misses8, decisions8 = simulate_lru_pressure(window, 8)
    rows.append({
        "start": start,
        "end": start + window_size,
        "unique_pages": unique_pages,
        "write_ratio": write_ratio,
        "cap16_decisions": decisions16,
        "cap8_decisions": decisions8,
        "cap16_misses": misses16,
        "cap8_misses": misses8,
    })
  rows.sort(key=lambda row: (
      row["cap16_decisions"], row["unique_pages"], row["write_ratio"]),
            reverse=True)
  return rows


def write_report(args):
  workloads = split_csv(args.workloads)
  rows = load_summary_rows(args.result_dir)
  lines = []
  lines.append("# Real Pilot Diagnosis")
  lines.append("")
  lines.append("## Replay Summary")
  lines.append("")
  lines.append("| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |")
  lines.append("|---|---|---:|---:|---:|---:|")
  for row in rows:
    lines.append("| {workload} | {policy} | {hit_rate_percent} | "
                 "{weighted_access_cost} | {migrations} | "
                 "{decision_count} |".format(**row))

  lines.append("")
  lines.append("## QMAP Victim Quality")
  lines.append("")
  lines.append("| Workload | Decisions | Worse than LRU | Reuse <= 10 | "
               "Chosen future reuse | LRU future reuse | Top ranks |")
  lines.append("|---|---:|---:|---:|---|---|---|")
  for workload in workloads:
    diagnostic = qmap_choice_diagnostics(workload, args)
    if "error" in diagnostic:
      lines.append("| {} |  |  |  | {} |  |  |".format(
          workload, diagnostic["error"]))
      continue
    lines.append("| {workload} | {decisions} | {worse} | {short} | "
                 "{chosen} | {lru} | {ranks} |".format(
                     workload=workload,
                     decisions=diagnostic["decisions"],
                     worse=diagnostic["worse_than_lru"],
                     short=diagnostic["short_reuse"],
                     chosen=diagnostic["chosen_distance"],
                     lru=diagnostic["lru_distance"],
                     ranks=diagnostic["rank_counts"]))

  lines.append("")
  lines.append("## Dedup Pressure Windows")
  lines.append("")
  lines.append("| Start | End | Unique pages | Write ratio | "
               "LRU decisions @16 | LRU decisions @8 |")
  lines.append("|---:|---:|---:|---:|---:|---:|")
  for row in scan_dedup_windows(
      args.dedup_raw_trace, args.page_shift, args.window_size,
      args.window_step)[:10]:
    lines.append("| {start} | {end} | {unique_pages} | {write_ratio:.4f} | "
                 "{cap16_decisions} | {cap8_decisions} |".format(**row))

  text = "\n".join(lines) + "\n"
  if args.output == "-":
    print(text)
  else:
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as output_file:
      output_file.write(text)
    print("[done] diagnosis={}".format(args.output))


def main():
  write_report(build_arg_parser().parse_args())


if __name__ == "__main__":
  main()
