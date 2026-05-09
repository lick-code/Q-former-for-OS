# coding=utf-8
"""Run the QMAP workload suite end to end.

Pipeline:

  1. build hotset/writeheavy/streaming/phasechange/pcrwstress raw traces
  2. split each trace into train/valid/test CSV files
  3. generate QMAP JSONL training samples
  4. train one QMAP checkpoint per workload
  5. evaluate LRU / Random / LFU / CLOCK / QMAP on each workload test trace
  6. write suite-level CSV and Markdown summaries
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_WORKLOADS = ("hotset", "writeheavy", "streaming", "phasechange",
                     "pcrwstress")
DEFAULT_POLICIES = ("lru", "random", "lfu", "clock", "qmap")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel_path(path):
  return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def load_json(path):
  with open(path, "r") as input_file:
    return json.load(input_file)


def run_command(command, log_path):
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  print("[run] {}".format(" ".join(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  with open(log_path, "w") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run QMAP across multiple synthetic workloads.")
  parser.add_argument("--workloads", default=",".join(DEFAULT_WORKLOADS),
                      help="Comma-separated workload names.")
  parser.add_argument("--policies", default=",".join(DEFAULT_POLICIES),
                      help="Comma-separated policies to evaluate.")
  parser.add_argument("--records", type=int, default=20000)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--device", default=None,
                      help="cpu, cuda, or omit for qmap_train/qmap_eval auto.")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--raw_dir", default=os.path.join("dataset",
                                                        "raw_traces"))
  parser.add_argument("--processed_dir", default=os.path.join("dataset",
                                                              "processed"))
  parser.add_argument("--jsonl_dir", default=os.path.join("dataset", "jsonl"))
  parser.add_argument("--result_dir", default=path_from_root(
      "outputs", "results", "workload_suite"))
  parser.add_argument("--checkpoint_dir", default=path_from_root(
      "outputs", "checkpoints", "workload_suite"))
  parser.add_argument("--metadata", default=os.path.join(
      "dataset", "metadata", "workload_manifest.json"))
  parser.add_argument("--skip_build", action="store_true",
                      help="Use existing raw/processed workload CSV files.")
  parser.add_argument("--skip_generate", action="store_true",
                      help="Use existing workload JSONL files.")
  parser.add_argument("--skip_train", action="store_true",
                      help="Use existing checkpoints for QMAP evaluation.")
  parser.add_argument("--run_id", default=None,
                      help="Optional run id recorded in summary metadata.")
  return parser


def maybe_extend_device(command, device):
  if device:
    command.extend(["--device", device])


def build_workloads(args, workloads, log_dir):
  if args.skip_build:
    return
  command = [
      args.python, "scripts/build_workload_suite.py",
      "--records", str(args.records),
      "--page_shift", str(args.page_shift),
      "--raw_dir", args.raw_dir,
      "--processed_dir", args.processed_dir,
      "--metadata", args.metadata,
      "--python", args.python,
      "--workloads",
  ] + workloads
  run_command(command, os.path.join(log_dir, "build_workloads.log"))


def check_qmap_dependency(args, log_dir):
  command = [args.python, "-c", "import torch; print(torch.__version__)"]
  log_path = os.path.join(log_dir, "torch_check.log")
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  with open(log_path, "w") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    raise RuntimeError(
        "QMAP training/evaluation requires torch, but `{}` cannot import it. "
        "Install the project requirements or pass --python to an environment "
        "with torch. See {} for details.".format(args.python, log_path))


def workload_paths(args, workload):
  return {
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
      "--json_output", json_output,
  ]
  if policy == "qmap":
    command.extend(["--checkpoint", checkpoint_path])
    maybe_extend_device(command, args.device)
  run_command(command, os.path.join(log_dir, "{}_{}.log".format(
      workload, policy)))
  row = load_json(json_output)
  row["workload"] = workload
  row["checkpoint"] = checkpoint_path if policy == "qmap" else ""
  row["train_trace"] = rel_path(paths["train_trace"])
  row["test_trace"] = rel_path(paths["test_trace"])
  return row


def summary_row(row):
  return {
      "workload": row["workload"],
      "policy": row["policy"],
      "hit_rate": row["hit_rate"],
      "hit_rate_percent": row["hit_rate_percent"],
      "nvm_writes": row["nvm_writes"],
      "cost": row["weighted_access_cost"],
      "migrations": row["migrations"],
      "decision_ms": row["avg_decision_time_ms"],
      "decision_count": row["decision_count"],
      "total_accesses": row["total_accesses"],
      "misses": row["misses"],
      "nvm_reads": row["nvm_reads"],
      "train_trace": row["train_trace"],
      "test_trace": row["test_trace"],
      "checkpoint": row["checkpoint"],
  }


def write_summary_csv(rows, output_path):
  fields = [
      "workload",
      "policy",
      "hit_rate",
      "hit_rate_percent",
      "nvm_writes",
      "cost",
      "migrations",
      "decision_ms",
      "decision_count",
      "total_accesses",
      "misses",
      "nvm_reads",
      "train_trace",
      "test_trace",
      "checkpoint",
  ]
  with open(output_path, "w", newline="") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def write_summary_markdown(rows, output_path, args, workloads, policies):
  run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
  with open(output_path, "w") as output_file:
    output_file.write("# QMAP Workload Suite\n\n")
    output_file.write("## Setup\n\n")
    output_file.write("- run id: `{}`\n".format(run_id))
    output_file.write("- workloads: `{}`\n".format(", ".join(workloads)))
    output_file.write("- policies: `{}`\n".format(", ".join(policies)))
    output_file.write("- records per workload: `{}`\n".format(args.records))
    output_file.write("- split policy: `chronological 80/10/10`\n")
    output_file.write("- DRAM capacity: `{}` pages\n".format(
        args.dram_capacity))
    output_file.write("- history length: `{}`\n".format(args.history_length))
    output_file.write("- candidate count: `{}`\n".format(
        args.candidate_count))
    output_file.write("- lookahead: `{}`\n".format(args.lookahead))
    output_file.write("- page shift: `{}`\n".format(args.page_shift))
    output_file.write("- epochs: `{}`\n".format(args.epochs))
    output_file.write("- batch size: `{}`\n".format(args.batch_size))
    output_file.write("- device: `{}`\n\n".format(args.device or "auto"))
    output_file.write("## Results\n\n")
    output_file.write(
        "| Workload | Policy | Hit rate (%) | NVM writes | Cost | "
        "Migrations | Decision ms |\n")
    output_file.write("|---|---|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {policy} | {hit_rate:.2f} | {writes} | "
          "{cost:.2f} | {migrations} | {decision_ms:.6f} |\n".format(
              workload=row["workload"],
              policy=row["policy"],
              hit_rate=row["hit_rate_percent"],
              writes=row["nvm_writes"],
              cost=row["cost"],
              migrations=row["migrations"],
              decision_ms=row["decision_ms"]))


def main():
  args = build_arg_parser().parse_args()
  workloads = split_csv(args.workloads)
  policies = split_csv(args.policies)
  unknown_policies = sorted(set(policies) - set(DEFAULT_POLICIES))
  if unknown_policies:
    raise ValueError("Unsupported policies: {}".format(unknown_policies))
  if "qmap" in policies and args.skip_train:
    print("[info] --skip_train set; QMAP will use existing checkpoints.",
          flush=True)

  log_dir = os.path.join(args.result_dir, "logs")
  os.makedirs(args.result_dir, exist_ok=True)
  os.makedirs(log_dir, exist_ok=True)

  if "qmap" in policies:
    check_qmap_dependency(args, log_dir)

  build_workloads(args, workloads, log_dir)

  rows = []
  for workload in workloads:
    print("[workload] {}".format(workload), flush=True)
    paths = workload_paths(args, workload)
    check_required_trace_paths(paths)
    generate_jsonl(args, workload, paths, log_dir)
    checkpoint_path = None
    if "qmap" in policies:
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
