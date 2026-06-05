# coding=utf-8
"""Stage 6 real-workload QMAP ablation runner.

This script is intentionally narrow: it only covers the two stage 6 workloads
and the two requested ablation variants.

Default mode is local-safe and does not import torch:

  python scripts/run_real_ablation.py

It creates JSONL training data and writes a server shell script with the
torch-dependent training/evaluation commands. On a machine with torch, run:

  python scripts/run_real_ablation.py --run_torch --summarize
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from types import SimpleNamespace


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

HISTORY_LENGTH = 10
CANDIDATE_COUNT = 8
DRAM_CAPACITY = 16
LOOKAHEAD = 256
PAGE_SHIFT = 12
EPOCHS = 10
BATCH_SIZE = 32
LR = 1e-4
SEED = 3136859
NVM_WRITE_COST = 8.0

VARIANTS = ("no_rw", "no_cost")

WORKLOADS = {
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "workload": "parsec_streamcluster",
        "train_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_train.csv",
        "test_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_test.csv",
        "baseline_qmap": "outputs/results/real_workload_suite_pressure/selected/parsec_streamcluster/qmap.json",
    },
    "blackscholes": {
        "display": "blackscholes",
        "workload": "parsec_blackscholes",
        "train_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_train.csv",
        "test_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_test.csv",
        "baseline_qmap": "outputs/results/real_workload_suite/1m/parsec_blackscholes/qmap.json",
    },
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel(path):
  return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def shell_quote(path):
  return "'{}'".format(path.replace("'", "'\"'\"'"))


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(data, path):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(data, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def run_command(command, log_path=None):
  print("[run] {}".format(" ".join(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True)
  if log_path:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as output_file:
      output_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)
  return process.stdout


def variant_paths(workload_key, variant):
  config = WORKLOADS[workload_key]
  workload_name = config["workload"]
  return {
      "jsonl": path_from_root(
          "dataset", "jsonl", "real_ablation", workload_key, variant,
          "{}_train.jsonl".format(workload_name)),
      "checkpoint_dir": path_from_root(
          "outputs", "checkpoints", "real_ablation", workload_key, variant),
      "checkpoint": path_from_root(
          "outputs", "checkpoints", "real_ablation", workload_key, variant,
          "qmap_epoch_{}.pth".format(EPOCHS)),
      "result_dir": path_from_root(
          "outputs", "results", "real_ablation", workload_key, variant),
      "result_json": path_from_root(
          "outputs", "results", "real_ablation", workload_key, variant,
          "qmap.json"),
      "log_dir": path_from_root(
          "outputs", "results", "real_ablation", workload_key, variant,
          "logs"),
  }


def check_inputs():
  missing = []
  for config in WORKLOADS.values():
    for key in ("train_trace", "test_trace", "baseline_qmap"):
      path = path_from_root(*config[key].split("/"))
      if not os.path.exists(path):
        missing.append(config[key])
  if missing:
    raise FileNotFoundError(
        "Missing required stage 6 input(s):\n  {}".format(
            "\n  ".join(missing)))


def generate_jsonl_for_variant(workload_key, variant, force=False):
  from qmap import qmap_generator

  config = WORKLOADS[workload_key]
  paths = variant_paths(workload_key, variant)
  if os.path.exists(paths["jsonl"]) and not force:
    print("[skip] JSONL exists: {}".format(rel(paths["jsonl"])), flush=True)
    return

  os.makedirs(os.path.dirname(paths["jsonl"]), exist_ok=True)
  args = SimpleNamespace(
      input=path_from_root(*config["train_trace"].split("/")),
      output=paths["jsonl"],
      history_length=HISTORY_LENGTH,
      candidate_count=CANDIDATE_COUNT,
      lookahead=LOOKAHEAD,
      dram_capacity=DRAM_CAPACITY,
      page_shift=PAGE_SHIFT,
      ablation=variant)
  qmap_generator.generate_qmap_samples(args)


def generate_all_jsonl(force=False):
  for workload_key in WORKLOADS:
    for variant in VARIANTS:
      generate_jsonl_for_variant(workload_key, variant, force=force)


def train_command(python_bin, workload_key, variant, device):
  paths = variant_paths(workload_key, variant)
  return [
      python_bin, "qmap/qmap_train.py",
      "--train_data", rel(paths["jsonl"]),
      "--output_dir", rel(paths["checkpoint_dir"]),
      "--epochs", str(EPOCHS),
      "--batch_size", str(BATCH_SIZE),
      "--lr", str(LR),
      "--seed", str(SEED),
      "--device", device,
      "--ablation", variant,
  ]


def eval_command(python_bin, workload_key, variant, device):
  config = WORKLOADS[workload_key]
  paths = variant_paths(workload_key, variant)
  return [
      python_bin, "qmap/qmap_eval.py",
      "--trace_path", config["test_trace"],
      "--policy", "qmap",
      "--checkpoint", rel(paths["checkpoint"]),
      "--device", device,
      "--dram_capacity", str(DRAM_CAPACITY),
      "--page_shift", str(PAGE_SHIFT),
      "--history_length", str(HISTORY_LENGTH),
      "--candidate_count", str(CANDIDATE_COUNT),
      "--lookahead", str(LOOKAHEAD),
      "--nvm_write_cost", str(NVM_WRITE_COST),
      "--ablation", variant,
      "--json_output", rel(paths["result_json"]),
  ]


def run_torch_steps(python_bin, device, force=False):
  for workload_key in WORKLOADS:
    for variant in VARIANTS:
      paths = variant_paths(workload_key, variant)
      os.makedirs(paths["checkpoint_dir"], exist_ok=True)
      os.makedirs(paths["result_dir"], exist_ok=True)
      if not os.path.exists(paths["checkpoint"]) or force:
        run_command(
            train_command(python_bin, workload_key, variant, device),
            os.path.join(paths["log_dir"], "train.log"))
      else:
        print("[skip] checkpoint exists: {}".format(rel(paths["checkpoint"])))
      if not os.path.exists(paths["result_json"]) or force:
        run_command(
            eval_command(python_bin, workload_key, variant, device),
            os.path.join(paths["log_dir"], "eval.log"))
      else:
        print("[skip] result exists: {}".format(rel(paths["result_json"])))


def command_to_sh(command):
  return " ".join(shell_quote(item) if any(c in item for c in " ()[]{};&")
                  else item for item in command)


def write_server_script(path, python_bin, device):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  lines = [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "",
      "# Run from the repository root. Override PY if your conda path differs.",
      "PY=${PY:-%s}" % shell_quote(python_bin),
      "DEVICE=${DEVICE:-%s}" % shell_quote(device),
      "",
      "# Regenerate JSONL on the server, then run torch-dependent steps.",
      "$PY scripts/run_real_ablation.py --force_generate",
      "$PY scripts/run_real_ablation.py --skip_generate --run_torch --summarize --python \"$PY\" --device \"$DEVICE\"",
      "",
  ]
  try:
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
      output_file.write("\n".join(lines))
  except PermissionError:
    print("[warn] cannot write server script: {}".format(rel(path)),
          flush=True)
    return
  print("[done] server script: {}".format(rel(path)), flush=True)


def collect_summary_rows():
  rows = []
  pool_cost = {}
  for workload_key, config in WORKLOADS.items():
    baseline_path = path_from_root(*config["baseline_qmap"].split("/"))
    baseline = load_json(baseline_path)
    pool_cost[workload_key] = float(baseline["weighted_access_cost"])
    rows.append({
        "workload": config["display"],
        "variant": "QMAP-CrossAttn",
        "cost": float(baseline["weighted_access_cost"]),
        "vs_qmap_crossattn_percent": 0.0,
        "nvm_writes": baseline["nvm_writes"],
        "migrations": baseline["migrations"],
    })
    for variant in VARIANTS:
      result_path = variant_paths(workload_key, variant)["result_json"]
      if not os.path.exists(result_path):
        raise FileNotFoundError(
            "Missing eval output for summary: {}".format(rel(result_path)))
      data = load_json(result_path)
      cost = float(data["weighted_access_cost"])
      rows.append({
          "workload": config["display"],
          "variant": variant,
          "cost": cost,
          "vs_qmap_crossattn_percent": (
              (cost - pool_cost[workload_key]) * 100.0 /
              pool_cost[workload_key]),
          "nvm_writes": data["nvm_writes"],
          "migrations": data["migrations"],
      })
  return rows


def write_summary(rows):
  result_root = path_from_root("outputs", "results", "real_ablation")
  os.makedirs(result_root, exist_ok=True)
  csv_path = os.path.join(result_root, "summary.csv")
  md_path = os.path.join(result_root, "summary.md")
  fields = [
      "workload", "variant", "cost", "vs_qmap_crossattn_percent",
      "nvm_writes", "migrations",
  ]
  with open(csv_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow(row)

  with open(md_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Real QMAP Ablation\n\n")
    output_file.write(
        "| workload | variant | cost | vs QMAP-CrossAttn | NVM writes | migrations |\n")
    output_file.write("|---|---|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {variant} | {cost:.2f} | {delta:+.2f}% | "
          "{writes} | {migrations} |\n".format(
              workload=row["workload"],
              variant=row["variant"],
              cost=row["cost"],
              delta=row["vs_qmap_crossattn_percent"],
              writes=row["nvm_writes"],
              migrations=row["migrations"]))
  print("[done] summary: {}".format(rel(md_path)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run stage 6 real QMAP ablation experiments.")
  parser.add_argument("--python", default=sys.executable,
                      help="Python executable for torch-dependent commands.")
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--skip_generate", action="store_true",
                      help="Do not generate JSONL locally.")
  parser.add_argument("--force_generate", action="store_true",
                      help="Regenerate JSONL even when files already exist.")
  parser.add_argument("--run_torch", action="store_true",
                      help="Run qmap_train.py and qmap_eval.py.")
  parser.add_argument("--summarize", action="store_true",
                      help="Write outputs/results/real_ablation summary.")
  parser.add_argument("--force_torch", action="store_true",
                      help="Rerun training/eval even if outputs exist.")
  parser.add_argument("--server_script", default=path_from_root(
      "outputs", "results", "real_ablation", "run_on_server.sh"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  check_inputs()
  if not args.skip_generate:
    generate_all_jsonl(force=args.force_generate)
  write_server_script(args.server_script, args.python, args.device)
  if args.run_torch:
    run_torch_steps(args.python, args.device, force=args.force_torch)
  if args.summarize:
    write_summary(collect_summary_rows())


if __name__ == "__main__":
  main()
