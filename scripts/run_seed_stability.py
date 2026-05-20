# coding=utf-8
"""Stage 7 seed-stability runner for real-workload QMAP-Pool results.

Default mode is local-safe and does not import torch:

  python scripts/run_seed_stability.py

It checks the required stage 5/6 artifacts and writes a server script with the
torch-dependent training/evaluation commands. On a machine with torch, run:

  python scripts/run_seed_stability.py --run_torch --summarize
"""

import argparse
import csv
import json
import math
import os
import shutil
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
NVM_WRITE_COST = 8.0
QMAP_ABLATION = "mean_pool"
DEFAULT_SEEDS = (3136859, 42, 2026)
BASELINE_POLICIES = ("lru", "random", "lfu", "clock")

WORKLOADS = {
    "streamcluster_pressure": {
        "display": "streamcluster_pressure",
        "workload": "parsec_streamcluster",
        "train_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_train.csv",
        "test_trace": "dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_test.csv",
        "source_jsonl": "dataset/jsonl/real_workload_suite_pressure/selected/parsec_streamcluster_train.jsonl",
        "baseline_dir": "outputs/results/real_workload_suite_pressure/selected/parsec_streamcluster",
    },
    "blackscholes": {
        "display": "blackscholes",
        "workload": "parsec_blackscholes",
        "train_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_train.csv",
        "test_trace": "dataset/processed/real_workload_suite/1m/parsec_blackscholes_test.csv",
        "source_jsonl": "dataset/jsonl/real_workload_suite/1m/parsec_blackscholes_train.jsonl",
        "baseline_dir": "outputs/results/real_workload_suite/1m/parsec_blackscholes",
    },
    "canneal": {
        "display": "canneal",
        "workload": "parsec_canneal",
        "train_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_train.csv",
        "test_trace": "dataset/processed/real_workload_suite/1m/parsec_canneal_test.csv",
        "source_jsonl": "dataset/jsonl/real_workload_suite/1m/parsec_canneal_train.jsonl",
        "baseline_dir": "outputs/results/real_workload_suite/1m/parsec_canneal",
    },
}


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_seeds(value):
  return tuple(int(item) for item in split_csv(value))


def shell_quote(value):
  return "'{}'".format(value.replace("'", "'\"'\"'"))


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


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


def selected_workloads(keys):
  if not keys:
    return tuple(WORKLOADS.keys())
  unknown = sorted(set(keys) - set(WORKLOADS.keys()))
  if unknown:
    raise ValueError("Unknown workload(s): {}".format(", ".join(unknown)))
  return tuple(keys)


def workload_paths(workload_key, seed=None):
  config = WORKLOADS[workload_key]
  target_jsonl = path_from_root(
      "dataset", "jsonl", "seed_stability", workload_key,
      "{}_train.jsonl".format(config["workload"]))
  source_jsonl = path_from_root(*config["source_jsonl"].split("/"))
  if os.path.exists(target_jsonl):
    jsonl = target_jsonl
  elif os.path.exists(source_jsonl):
    jsonl = source_jsonl
  else:
    jsonl = target_jsonl

  paths = {
      "train_trace": path_from_root(*config["train_trace"].split("/")),
      "test_trace": path_from_root(*config["test_trace"].split("/")),
      "source_jsonl": source_jsonl,
      "target_jsonl": target_jsonl,
      "jsonl": jsonl,
      "baseline_dir": path_from_root(*config["baseline_dir"].split("/")),
  }
  if seed is not None:
    seed_dir = "seed_{}".format(seed)
    paths.update({
        "checkpoint_dir": path_from_root(
            "outputs", "checkpoints", "seed_stability", workload_key,
            seed_dir),
        "checkpoint": path_from_root(
            "outputs", "checkpoints", "seed_stability", workload_key,
            seed_dir, "qmap_epoch_{}.pth".format(EPOCHS)),
        "result_dir": path_from_root(
            "outputs", "results", "seed_stability", workload_key, seed_dir),
        "result_json": path_from_root(
            "outputs", "results", "seed_stability", workload_key, seed_dir,
            "qmap.json"),
        "log_dir": path_from_root(
            "outputs", "results", "seed_stability", workload_key, seed_dir,
            "logs"),
    })
  return paths


def check_inputs(workload_keys):
  missing = []
  for workload_key in workload_keys:
    paths = workload_paths(workload_key)
    for key in ("train_trace", "test_trace"):
      if not os.path.exists(paths[key]):
        missing.append(rel(paths[key]))
    if not os.path.exists(paths["jsonl"]):
      missing.append(rel(paths["jsonl"]))
    for policy in BASELINE_POLICIES:
      baseline_path = os.path.join(paths["baseline_dir"],
                                   "{}.json".format(policy))
      if not os.path.exists(baseline_path):
        missing.append(rel(baseline_path))
  if missing:
    raise FileNotFoundError(
        "Missing required stage 7 input(s):\n  {}".format(
            "\n  ".join(missing)))


def materialize_jsonl(workload_key, force=False):
  """Copies an existing matching JSONL into the stage 7 output tree."""
  paths = workload_paths(workload_key)
  if os.path.exists(paths["target_jsonl"]) and not force:
    print("[skip] JSONL exists: {}".format(rel(paths["target_jsonl"])))
    return
  if os.path.exists(paths["source_jsonl"]) and not force:
    os.makedirs(os.path.dirname(paths["target_jsonl"]), exist_ok=True)
    shutil.copyfile(paths["source_jsonl"], paths["target_jsonl"])
    print("[done] copied JSONL: {}".format(rel(paths["target_jsonl"])))
    return
  generate_jsonl(workload_key, force=force)


def generate_jsonl(workload_key, force=False):
  from qmap import qmap_generator

  config = WORKLOADS[workload_key]
  paths = workload_paths(workload_key)
  if os.path.exists(paths["target_jsonl"]) and not force:
    print("[skip] JSONL exists: {}".format(rel(paths["target_jsonl"])))
    return
  os.makedirs(os.path.dirname(paths["target_jsonl"]), exist_ok=True)
  args = SimpleNamespace(
      input=paths["train_trace"],
      output=paths["target_jsonl"],
      history_length=HISTORY_LENGTH,
      candidate_count=CANDIDATE_COUNT,
      lookahead=LOOKAHEAD,
      dram_capacity=DRAM_CAPACITY,
      page_shift=PAGE_SHIFT,
      ablation=QMAP_ABLATION)
  print("[generate] {} -> {}".format(
      config["display"], rel(paths["target_jsonl"])), flush=True)
  qmap_generator.generate_qmap_samples(args)


def generate_all_jsonl(workload_keys, force=False, copy_existing=False):
  for workload_key in workload_keys:
    if copy_existing:
      materialize_jsonl(workload_key, force=force)
    elif force:
      generate_jsonl(workload_key, force=True)
    else:
      paths = workload_paths(workload_key)
      print("[reuse] JSONL: {}".format(rel(paths["jsonl"])), flush=True)


def train_command(python_bin, workload_key, seed, device):
  paths = workload_paths(workload_key, seed)
  return [
      python_bin, "qmap/qmap_train.py",
      "--train_data", rel(paths["jsonl"]),
      "--output_dir", rel(paths["checkpoint_dir"]),
      "--epochs", str(EPOCHS),
      "--batch_size", str(BATCH_SIZE),
      "--lr", str(LR),
      "--seed", str(seed),
      "--device", device,
      "--ablation", QMAP_ABLATION,
  ]


def eval_command(python_bin, workload_key, seed, device):
  paths = workload_paths(workload_key, seed)
  config = WORKLOADS[workload_key]
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
      "--ablation", QMAP_ABLATION,
      "--json_output", rel(paths["result_json"]),
  ]


def run_torch_steps(python_bin, device, workload_keys, seeds, force=False):
  for workload_key in workload_keys:
    for seed in seeds:
      paths = workload_paths(workload_key, seed)
      os.makedirs(paths["checkpoint_dir"], exist_ok=True)
      os.makedirs(paths["result_dir"], exist_ok=True)
      if not os.path.exists(paths["checkpoint"]) or force:
        run_command(
            train_command(python_bin, workload_key, seed, device),
            os.path.join(paths["log_dir"], "train.log"))
      else:
        print("[skip] checkpoint exists: {}".format(rel(paths["checkpoint"])))
      if not os.path.exists(paths["result_json"]) or force:
        run_command(
            eval_command(python_bin, workload_key, seed, device),
            os.path.join(paths["log_dir"], "eval.log"))
      else:
        print("[skip] result exists: {}".format(rel(paths["result_json"])))


def load_baselines(workload_key):
  baseline_dir = workload_paths(workload_key)["baseline_dir"]
  return {
      policy: load_json(os.path.join(baseline_dir, "{}.json".format(policy)))
      for policy in BASELINE_POLICIES
  }


def best_baseline(baselines):
  return min(
      baselines.items(),
      key=lambda item: (
          float(item[1]["weighted_access_cost"]),
          int(item[1].get("nvm_writes", 0)),
          -float(item[1].get("hit_rate_percent", 0.0))))


def build_seed_row(workload, seed, qmap_result, baselines):
  best_policy, best_result = best_baseline(baselines)
  qmap_cost = float(qmap_result["weighted_access_cost"])
  baseline_cost = float(best_result["weighted_access_cost"])
  if baseline_cost == 0.0:
    delta = 0.0
  else:
    delta = (qmap_cost - baseline_cost) * 100.0 / baseline_cost
  return {
      "workload": workload,
      "seed": seed,
      "qmap_cost": qmap_cost,
      "best_baseline_policy": best_policy,
      "best_baseline_cost": baseline_cost,
      "delta_percent": delta,
      "migrations": int(qmap_result["migrations"]),
      "nvm_writes": int(qmap_result["nvm_writes"]),
  }


def collect_seed_rows(workload_keys, seeds):
  rows = []
  for workload_key in workload_keys:
    baselines = load_baselines(workload_key)
    for seed in seeds:
      result_path = workload_paths(workload_key, seed)["result_json"]
      if not os.path.exists(result_path):
        raise FileNotFoundError(
            "Missing QMAP eval output for summary: {}".format(
                rel(result_path)))
      rows.append(build_seed_row(
          WORKLOADS[workload_key]["display"],
          seed,
          load_json(result_path),
          baselines))
  return rows


def conclusion_for_delta_range(min_delta, max_delta, std_delta):
  if max_delta < 0.0:
    if std_delta <= 1.0:
      return "stable positive: all seeds beat best baseline"
    return "positive but seed-sensitive: all seeds beat best baseline"
  if min_delta > 0.0:
    return "negative boundary: all seeds worse than best baseline"
  return "mixed: seed can flip the conclusion"


def summarize_rows(rows):
  by_workload = {}
  for row in rows:
    by_workload.setdefault(row["workload"], []).append(row["delta_percent"])

  summary = {}
  for workload, deltas in by_workload.items():
    mean_delta = sum(deltas) / len(deltas)
    variance = sum((delta - mean_delta) ** 2 for delta in deltas) / len(deltas)
    std_delta = math.sqrt(variance)
    min_delta = min(deltas)
    max_delta = max(deltas)
    summary[workload] = {
        "workload": workload,
        "mean_delta": mean_delta,
        "std_delta": std_delta,
        "min_delta": min_delta,
        "max_delta": max_delta,
        "conclusion": conclusion_for_delta_range(
            min_delta, max_delta, std_delta),
    }
  return summary


def write_summary(rows, output_dir):
  os.makedirs(output_dir, exist_ok=True)
  detail_csv = os.path.join(output_dir, "seed_results.csv")
  summary_csv = os.path.join(output_dir, "summary.csv")
  md_path = os.path.join(output_dir, "summary.md")

  detail_fields = [
      "workload", "seed", "qmap_cost", "best_baseline_policy",
      "best_baseline_cost", "delta_percent", "migrations", "nvm_writes",
  ]
  with open(detail_csv, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=detail_fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in detail_fields})

  summary = summarize_rows(rows)
  summary_fields = [
      "workload", "mean_delta", "std_delta", "min_delta", "max_delta",
      "conclusion",
  ]
  with open(summary_csv, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=summary_fields)
    writer.writeheader()
    for workload in summary:
      writer.writerow(summary[workload])

  with open(md_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Stage 7 Seed Stability\n\n")
    output_file.write(
        "Purpose: answer whether the QMAP-Pool result is an accidental "
        "training-seed outcome.\n\n")
    output_file.write("## Per-seed Results\n\n")
    output_file.write(
        "| workload | seed | QMAP cost | best baseline | delta | "
        "migrations | writes |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {seed} | {qmap:.2f} | {baseline:.2f} "
          "({policy}) | {delta:+.2f}% | {migrations} | {writes} |\n"
          .format(
              workload=row["workload"],
              seed=row["seed"],
              qmap=row["qmap_cost"],
              baseline=row["best_baseline_cost"],
              policy=row["best_baseline_policy"].upper(),
              delta=row["delta_percent"],
              migrations=row["migrations"],
              writes=row["nvm_writes"]))

    output_file.write("\n## Stability Summary\n\n")
    output_file.write(
        "| workload | mean delta | std delta | min/max delta | conclusion |\n")
    output_file.write("|---|---:|---:|---:|---|\n")
    for workload in summary:
      row = summary[workload]
      output_file.write(
          "| {workload} | {mean:+.2f}% | {std:.2f}% | "
          "{min_delta:+.2f}% / {max_delta:+.2f}% | {conclusion} |\n"
          .format(
              workload=workload,
              mean=row["mean_delta"],
              std=row["std_delta"],
              min_delta=row["min_delta"],
              max_delta=row["max_delta"],
              conclusion=row["conclusion"]))

    output_file.write("\n## Notes\n\n")
    output_file.write(
        "- LRU, LFU and CLOCK baselines are deterministic and reused from "
        "the existing stage 5/6 result directories.\n")
    output_file.write(
        "- Random is reused from the existing fixed-random-seed baseline run; "
        "QMAP-Pool is the only policy retrained across seeds.\n")

  print("[done] detail csv: {}".format(rel(detail_csv)), flush=True)
  print("[done] summary csv: {}".format(rel(summary_csv)), flush=True)
  print("[done] summary md: {}".format(rel(md_path)), flush=True)


def command_to_sh(command):
  return " ".join(shell_quote(item) if any(c in item for c in " ()[]{};&")
                  else item for item in command)


def write_server_script(path, python_bin, device, workload_keys, seeds):
  workload_arg = ",".join(workload_keys)
  seed_arg = ",".join(str(seed) for seed in seeds)
  lines = [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "",
      "# Run from the repository root. Override PY/DEVICE if needed.",
      "PY=${PY:-%s}" % shell_quote(python_bin),
      "DEVICE=${DEVICE:-%s}" % shell_quote(device),
      "WORKLOADS=${WORKLOADS:-%s}" % shell_quote(workload_arg),
      "SEEDS=${SEEDS:-%s}" % shell_quote(seed_arg),
      "",
      "# The script reuses existing JSONL by default, then trains/evaluates QMAP-Pool for each seed.",
      "$PY scripts/run_seed_stability.py --workloads \"$WORKLOADS\" --seeds \"$SEEDS\" --skip_generate --run_torch --summarize --python \"$PY\" --device \"$DEVICE\"",
      "",
  ]
  try:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
      output_file.write("\n".join(lines))
  except PermissionError:
    print("[warn] cannot write server script locally: {}".format(rel(path)),
          flush=True)
    print("[warn] command to run on server:", flush=True)
    print(lines[-2], flush=True)
    return
  print("[done] server script: {}".format(rel(path)), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run stage 7 QMAP seed-stability experiments.")
  parser.add_argument("--workloads", default=",".join(WORKLOADS.keys()),
                      help="Comma-separated keys: {}".format(
                          ",".join(WORKLOADS.keys())))
  parser.add_argument("--seeds", default=",".join(str(seed)
                                                  for seed in DEFAULT_SEEDS))
  parser.add_argument("--python", default=sys.executable,
                      help="Python executable for torch-dependent commands.")
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--skip_generate", action="store_true",
                      help="Do not materialize or regenerate JSONL locally.")
  parser.add_argument("--force_generate", action="store_true",
                      help="Regenerate stage 7 JSONL even if it exists.")
  parser.add_argument("--copy_existing_jsonl", action="store_true",
                      help="Copy existing matching JSONL into dataset/jsonl/seed_stability.")
  parser.add_argument("--run_torch", action="store_true",
                      help="Run qmap_train.py and qmap_eval.py.")
  parser.add_argument("--summarize", action="store_true",
                      help="Write outputs/results/seed_stability summaries.")
  parser.add_argument("--force_torch", action="store_true",
                      help="Rerun training/eval even if outputs exist.")
  parser.add_argument("--server_script", default=path_from_root(
      "outputs", "results", "seed_stability", "run_on_server.sh"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  workload_keys = selected_workloads(split_csv(args.workloads))
  seeds = parse_seeds(args.seeds)
  if not seeds:
    raise ValueError("At least one seed is required.")
  check_inputs(workload_keys)
  if not args.skip_generate:
    generate_all_jsonl(
        workload_keys,
        force=args.force_generate,
        copy_existing=args.copy_existing_jsonl)
  write_server_script(args.server_script, args.python, args.device,
                      workload_keys, seeds)
  if args.run_torch:
    run_torch_steps(
        args.python, args.device, workload_keys, seeds,
        force=args.force_torch)
  if args.summarize:
    write_summary(
        collect_seed_rows(workload_keys, seeds),
        path_from_root("outputs", "results", "seed_stability"))


if __name__ == "__main__":
  main()
