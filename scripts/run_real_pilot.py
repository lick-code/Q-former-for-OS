# coding=utf-8
"""Run a real/PARSEC QMAP workload experiment end to end.

Pipeline:

  1. normalize and split each raw CSV trace into 80/10/10 train/valid/test
  2. generate QMAP JSONL training samples from the train split
  3. train one QMAP-Pool checkpoint per workload
  4. evaluate LRU / Random / LFU / CLOCK / QMAP-Pool on each test split
  5. write experiment-level CSV and Markdown summaries
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_WORKLOADS = (
    "parsec_blackscholes",
    "parsec_canneal",
    "parsec_streamcluster",
    "parsec_dedup",
)
DEFAULT_POLICIES = ("lru", "random", "lfu", "clock", "qmap")
QMAP_MODEL_NAME = "QMAP-Pool"
QMAP_ABLATION = "mean_pool"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel_path(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def display_policy(policy):
  return QMAP_MODEL_NAME if policy == "qmap" else policy.upper()


def display_qmap_model(args):
  if args.rank_guard:
    return "{}-Guard".format(QMAP_MODEL_NAME)
  return QMAP_MODEL_NAME


def command_to_text(command):
  return " ".join(command)


def run_command(command, log_path):
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  print("[run] {}".format(command_to_text(command)), flush=True)
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
  return process.stdout


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run a real/PARSEC QMAP workload experiment.")
  parser.add_argument("--workloads", default=",".join(DEFAULT_WORKLOADS),
                      help="Comma-separated workload names.")
  parser.add_argument("--policies", default=",".join(DEFAULT_POLICIES),
                      help="Comma-separated policies to evaluate.")
  parser.add_argument("--limit", type=int, default=100000,
                      help="Records kept from each raw trace. 0 means all.")
  parser.add_argument("--skip", type=int, default=0,
                      help="Records skipped before applying --limit.")
  parser.add_argument("--workload_skips", default="",
                      help=("Optional comma-separated workload=skip overrides, "
                            "for pressure-window runs such as "
                            "parsec_dedup=50000."))
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--rank_guard", type=int, default=0,
                      help=("For QMAP eval, restrict inference to the first N "
                            "LRU-tail candidates. 0 disables the guard."))
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0)
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--random_seed", type=int, default=0)
  parser.add_argument("--device", default=None,
                      help="cpu, cuda, or omitted for qmap_train/qmap_eval auto.")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--raw_dir", default=os.path.join("dataset",
                                                        "raw_traces"))
  parser.add_argument("--normalized_raw_dir", default=None,
                      help=("Directory for normalized raw CSV outputs. "
                            "Defaults to --raw_dir. Use a separate directory "
                            "for pressure-window reruns to avoid overwriting "
                            "canonical normalized traces."))
  parser.add_argument("--raw_pattern", default="{workload}_100k.csv",
                      help=("Input file pattern under --raw_dir. The token "
                            "{workload} is replaced by the workload name."))
  parser.add_argument("--processed_dir", default=os.path.join("dataset",
                                                              "processed"))
  parser.add_argument("--jsonl_dir", default=os.path.join("dataset", "jsonl",
                                                         "real_pilot"))
  parser.add_argument("--result_dir", default=path_from_root(
      "outputs", "results", "real_pilot"))
  parser.add_argument("--checkpoint_dir", default=path_from_root(
      "outputs", "checkpoints", "real_pilot"))
  parser.add_argument("--manifest", default=path_from_root(
      "dataset", "metadata", "real_workload_manifest.json"))
  parser.add_argument("--stats_dir", default=path_from_root(
      "outputs", "results", "real_trace_stats"))
  parser.add_argument("--skip_prepare", action="store_true",
                      help="Use existing processed train/valid/test CSV files.")
  parser.add_argument("--skip_generate", action="store_true",
                      help="Use existing real-pilot JSONL files.")
  parser.add_argument("--skip_train", action="store_true",
                      help="Use existing QMAP-Pool checkpoints.")
  parser.add_argument("--run_id", default=None,
                      help="Optional run id recorded in summary metadata.")
  return parser


def maybe_extend_device(command, device):
  if device:
    command.extend(["--device", device])


def parse_workload_skips(value):
  skips = {}
  if not value:
    return skips
  for item in split_csv(value):
    if "=" not in item:
      raise ValueError(
          "--workload_skips entries must use workload=skip: {}".format(item))
    workload, skip_text = item.split("=", 1)
    workload = workload.strip()
    if not workload:
      raise ValueError("Empty workload in --workload_skips.")
    skip = int(skip_text.strip())
    if skip < 0:
      raise ValueError("Skip must be non-negative for {}.".format(workload))
    skips[workload] = skip
  return skips


def check_qmap_dependency(args, log_dir):
  command = [args.python, "-c", "import torch; print(torch.__version__)"]
  log_path = os.path.join(log_dir, "torch_check.log")
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      universal_newlines=True)
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    raise RuntimeError(
        "QMAP training/evaluation requires torch, but `{}` cannot import it. "
        "Install requirements or pass --python to an environment with torch. "
        "See {} for details.".format(args.python, log_path))


def workload_paths(args, workload):
  raw_input = path_from_root(
      args.raw_dir, args.raw_pattern.format(workload=workload))
  fallback_input = path_from_root(args.raw_dir, "{}.csv".format(workload))
  if not os.path.exists(raw_input) and os.path.exists(fallback_input):
    raw_input = fallback_input
  normalized_raw_dir = args.normalized_raw_dir or args.raw_dir
  return {
      "raw_input": raw_input,
      "normalized_raw": path_from_root(normalized_raw_dir,
                                       "{}.csv".format(workload)),
      "train_trace": path_from_root(
          args.processed_dir, "{}_train.csv".format(workload)),
      "valid_trace": path_from_root(
          args.processed_dir, "{}_valid.csv".format(workload)),
      "test_trace": path_from_root(
          args.processed_dir, "{}_test.csv".format(workload)),
      "jsonl": path_from_root(args.jsonl_dir,
                              "{}_train.jsonl".format(workload)),
      "checkpoint_dir": os.path.join(args.checkpoint_dir, workload),
      "result_dir": os.path.join(args.result_dir, workload),
  }


def check_required_trace_paths(paths):
  for key in ("train_trace", "valid_trace", "test_trace"):
    if not os.path.exists(paths[key]):
      raise FileNotFoundError("{} not found: {}".format(key, paths[key]))


def prepare_workload(args, workload, paths, log_dir, skip):
  if args.skip_prepare:
    check_required_trace_paths(paths)
    return
  if not os.path.exists(paths["raw_input"]):
    raise FileNotFoundError("Raw input not found: {}".format(
        paths["raw_input"]))
  command = [
      args.python, "scripts/prepare_real_trace.py",
      "--input", paths["raw_input"],
      "--workload", workload,
      "--raw-output", paths["normalized_raw"],
      "--processed-dir", path_from_root(args.processed_dir),
      "--manifest", args.manifest,
      "--stats-dir", args.stats_dir,
      "--page-shift", str(args.page_shift),
      "--limit", str(args.limit),
      "--skip", str(skip),
  ]
  run_command(command, os.path.join(log_dir, "{}_prepare.log".format(
      workload)))
  check_required_trace_paths(paths)


def generate_jsonl(args, workload, paths, log_dir):
  if args.skip_generate:
    if not os.path.exists(paths["jsonl"]):
      raise FileNotFoundError("JSONL not found: {}".format(paths["jsonl"]))
    return
  os.makedirs(os.path.dirname(paths["jsonl"]), exist_ok=True)
  command = [
      args.python, "qmap/qmap_generator.py",
      "--input", paths["train_trace"],
      "--output", paths["jsonl"],
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--lookahead", str(args.lookahead),
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--ablation", QMAP_ABLATION,
  ]
  run_command(command, os.path.join(log_dir, "{}_generate.log".format(
      workload)))


def train_qmap(args, workload, paths, log_dir):
  checkpoint_path = os.path.join(
      paths["checkpoint_dir"], "qmap_epoch_{}.pth".format(args.epochs))
  if args.skip_train:
    if not os.path.exists(checkpoint_path):
      raise FileNotFoundError("Checkpoint not found: {}".format(
          checkpoint_path))
    return checkpoint_path

  os.makedirs(paths["checkpoint_dir"], exist_ok=True)
  command = [
      args.python, "qmap/qmap_train.py",
      "--train_data", paths["jsonl"],
      "--output_dir", paths["checkpoint_dir"],
      "--epochs", str(args.epochs),
      "--batch_size", str(args.batch_size),
      "--lr", str(args.lr),
      "--write_sensitivity_weight", str(args.write_sensitivity_weight),
      "--migration_cost_weight", str(args.migration_cost_weight),
      "--seed", str(args.seed),
      "--ablation", QMAP_ABLATION,
  ]
  maybe_extend_device(command, args.device)
  run_command(command, os.path.join(log_dir, "{}_train.log".format(workload)))
  if not os.path.exists(checkpoint_path):
    raise FileNotFoundError("Expected checkpoint not found: {}".format(
        checkpoint_path))
  return checkpoint_path


def evaluate_policy(args, workload, policy, paths, checkpoint_path, log_dir):
  os.makedirs(paths["result_dir"], exist_ok=True)
  json_output = os.path.join(paths["result_dir"], "{}.json".format(policy))
  command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", paths["test_trace"],
      "--policy", policy,
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--history_length", str(args.history_length),
      "--candidate_count", str(args.candidate_count),
      "--lookahead", str(args.lookahead),
      "--random_seed", str(args.random_seed),
      "--nvm_write_cost", str(args.nvm_write_cost),
      "--json_output", json_output,
  ]
  if policy == "qmap":
    command.extend([
        "--checkpoint", checkpoint_path,
        "--ablation", QMAP_ABLATION,
    ])
    if args.rank_guard:
      command.extend(["--rank_guard", str(args.rank_guard)])
    maybe_extend_device(command, args.device)
  run_command(command, os.path.join(log_dir, "{}_{}.log".format(
      workload, policy)))
  row = load_json(json_output)
  row["workload"] = workload
  row["checkpoint"] = checkpoint_path if policy == "qmap" else ""
  row["train_trace"] = rel_path(paths["train_trace"])
  row["valid_trace"] = rel_path(paths["valid_trace"])
  row["test_trace"] = rel_path(paths["test_trace"])
  row["jsonl"] = rel_path(paths["jsonl"]) if policy == "qmap" else ""
  row["candidate_count"] = row.get("candidate_count", "")
  row["rank_guard"] = row.get("rank_guard", "")
  return row


def summary_row(row):
  return {
      "workload": row["workload"],
      "policy": row["policy"],
      "hit_rate": row["hit_rate"],
      "hit_rate_percent": row["hit_rate_percent"],
      "nvm_writes": row["nvm_writes"],
      "weighted_access_cost": row["weighted_access_cost"],
      "migrations": row["migrations"],
      "avg_decision_time_ms": row["avg_decision_time_ms"],
      "decision_count": row["decision_count"],
      "total_accesses": row["total_accesses"],
      "misses": row["misses"],
      "nvm_reads": row["nvm_reads"],
      "train_trace": row["train_trace"],
      "valid_trace": row["valid_trace"],
      "test_trace": row["test_trace"],
      "jsonl": row["jsonl"],
      "candidate_count": row.get("candidate_count", ""),
      "rank_guard": row.get("rank_guard", ""),
      "checkpoint": row["checkpoint"],
  }


def write_summary_csv(rows, output_path):
  fields = [
      "workload",
      "policy",
      "hit_rate",
      "hit_rate_percent",
      "nvm_writes",
      "weighted_access_cost",
      "migrations",
      "avg_decision_time_ms",
      "decision_count",
      "total_accesses",
      "misses",
      "nvm_reads",
      "train_trace",
      "valid_trace",
      "test_trace",
      "jsonl",
      "candidate_count",
      "rank_guard",
      "checkpoint",
  ]
  with open(output_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def manifest_stats(manifest_path, workload):
  if not os.path.exists(manifest_path):
    return None
  manifest = load_json(manifest_path)
  entry = manifest.get("workloads", {}).get(workload)
  if not entry:
    return None
  return entry.get("stats")


def best_qmap_comparison(rows, workload):
  workload_rows = [row for row in rows if row["workload"] == workload]
  qmap_row = next((row for row in workload_rows if row["policy"] == "qmap"),
                  None)
  baseline_rows = [row for row in workload_rows if row["policy"] != "qmap"]
  if qmap_row is None or not baseline_rows:
    return ""
  best_baseline = min(
      baseline_rows,
      key=lambda row: (row["weighted_access_cost"], row["nvm_writes"],
                       -row["hit_rate_percent"]))
  base_cost = float(best_baseline["weighted_access_cost"])
  if base_cost == 0.0:
    delta = 0.0
  else:
    delta = (
        (qmap_row["weighted_access_cost"] - base_cost) * 100.0 / base_cost)
  return "{} {:+.2f}%".format(display_policy(best_baseline["policy"]), delta)


def write_summary_markdown(rows, output_path, args, workloads, policies):
  run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
  test_accesses = {}
  for row in rows:
    test_accesses.setdefault(row["workload"], row["total_accesses"])
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Real/PARSEC QMAP Experiment\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- run id: `{}`\n".format(run_id))
    output_file.write("- workloads: `{}`\n".format(", ".join(workloads)))
    output_file.write("- policies: `{}`\n".format(", ".join(
        display_policy(policy) for policy in policies)))
    if args.skip_prepare:
      output_file.write(
          "- records per workload: `external processed splits (--skip_prepare)`\n")
    else:
      output_file.write("- records per workload: `{}`\n".format(args.limit))
    output_file.write("- test accesses: `{}`\n".format(", ".join(
        "{}={}".format(workload, test_accesses.get(workload, ""))
        for workload in workloads)))
    output_file.write("- global skip: `{}`\n".format(args.skip))
    if args.workload_skips:
      output_file.write("- workload skips: `{}`\n".format(
          args.workload_skips))
    output_file.write("- split policy: `chronological 80/10/10`\n")
    output_file.write("- DRAM capacity: `{}` pages\n".format(
        args.dram_capacity))
    output_file.write("- h/c/d/l: `{}/{}/{}/{}`\n".format(
        args.history_length, args.candidate_count, args.dram_capacity,
        args.lookahead))
    output_file.write("- QMAP model: `{}` (`ablation={}`)\n".format(
        display_qmap_model(args), QMAP_ABLATION))
    output_file.write("- QMAP rank guard: `{}`\n".format(
        args.rank_guard or "disabled"))
    output_file.write("- page shift: `{}`\n".format(args.page_shift))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- seed: `{}`\n".format(args.seed))
    output_file.write("- random seed: `{}`\n".format(args.random_seed))
    output_file.write("- device: `{}`\n\n".format(args.device or "auto"))

    output_file.write("## Trace Stats\n\n")
    output_file.write(
        "| Workload | Records | Unique pages | Unique PCs | Write ratio | "
        "Reuse ratio |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|\n")
    for workload in workloads:
      stats = manifest_stats(args.manifest, workload)
      if not stats:
        output_file.write("| {} |  |  |  |  |  |\n".format(workload))
        continue
      output_file.write(
          "| {workload} | {records} | {pages} | {pcs} | {write:.4f} | "
          "{reuse:.4f} |\n".format(
              workload=workload,
              records=stats["total_accesses"],
              pages=stats["unique_pages"],
              pcs=stats["unique_pcs"],
              write=stats["write_ratio"],
              reuse=stats["page_reuse_ratio"]))

    output_file.write("\n## Results\n\n")
    output_file.write(
        "| Workload | Policy | Hit rate (%) | NVM writes | Cost | "
        "Migrations | Decision ms |\n")
    output_file.write("|---|---|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {policy} | {hit_rate:.2f} | {writes} | "
          "{cost:.2f} | {migrations} | {decision_ms:.6f} |\n".format(
              workload=row["workload"],
              policy=display_policy(row["policy"]),
              hit_rate=row["hit_rate_percent"],
              writes=row["nvm_writes"],
              cost=row["weighted_access_cost"],
              migrations=row["migrations"],
              decision_ms=row["avg_decision_time_ms"]))

    output_file.write("\n## QMAP-Pool vs Best Baseline By Cost\n\n")
    output_file.write("| Workload | Best baseline and QMAP-Pool cost delta |\n")
    output_file.write("|---|---:|\n")
    for workload in workloads:
      output_file.write("| {} | {} |\n".format(
          workload, best_qmap_comparison(rows, workload)))


def main():
  args = build_arg_parser().parse_args()
  if args.limit < 0:
    raise ValueError("--limit must be non-negative.")
  if args.skip < 0:
    raise ValueError("--skip must be non-negative.")
  if args.rank_guard < 0:
    raise ValueError("--rank_guard must be non-negative.")
  if args.rank_guard and args.rank_guard > args.candidate_count:
    raise ValueError("--rank_guard cannot exceed --candidate_count.")
  workloads = split_csv(args.workloads)
  policies = split_csv(args.policies)
  workload_skips = parse_workload_skips(args.workload_skips)
  unknown_policies = sorted(set(policies) - set(DEFAULT_POLICIES))
  if unknown_policies:
    raise ValueError("Unsupported policies: {}".format(unknown_policies))
  if not workloads:
    raise ValueError("At least one workload is required.")

  log_dir = os.path.join(args.result_dir, "logs")
  os.makedirs(args.result_dir, exist_ok=True)
  os.makedirs(log_dir, exist_ok=True)

  if "qmap" in policies:
    check_qmap_dependency(args, log_dir)

  rows = []
  for workload in workloads:
    print("[workload] {}".format(workload), flush=True)
    paths = workload_paths(args, workload)
    prepare_workload(
        args, workload, paths, log_dir,
        workload_skips.get(workload, args.skip))
    checkpoint_path = None
    if "qmap" in policies:
      generate_jsonl(args, workload, paths, log_dir)
      checkpoint_path = train_qmap(args, workload, paths, log_dir)
    for policy in policies:
      row = evaluate_policy(
          args, workload, policy, paths, checkpoint_path, log_dir)
      rows.append(summary_row(row))

  summary_csv = os.path.join(args.result_dir, "summary.csv")
  summary_md = os.path.join(args.result_dir, "summary.md")
  write_summary_csv(rows, summary_csv)
  write_summary_markdown(rows, summary_md, args, workloads, policies)
  print("[done] summary_csv={}".format(summary_csv))
  print("[done] summary_md={}".format(summary_md))


if __name__ == "__main__":
  main()
