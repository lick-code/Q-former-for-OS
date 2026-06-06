# coding=utf-8
"""Stage 5 real workload suite runner.

This is a thin, fixed-configuration wrapper around run_real_pilot.py. It keeps
the stage 5 paper-table configuration in one place while reusing the already
validated real trace pipeline.
"""

import argparse
import json
import os
import shutil
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

STAGE5_HISTORY_LENGTH = 10
STAGE5_CANDIDATE_COUNT = 8
STAGE5_RANK_GUARD = 0
STAGE5_RANK_SCORE_PENALTY = 0.0
STAGE5_DRAM_CAPACITY = 16
STAGE5_LOOKAHEAD = 256
STAGE5_EPOCHS = 10
STAGE5_BATCH_SIZE = 32
STAGE5_MODEL = "QMAP-CrossAttn"
STAGE5_ABLATION = "cross_attention"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def access_tag(accesses):
  if accesses <= 0:
    return "all"
  if accesses % 1000000 == 0:
    return "{}m".format(accesses // 1000000)
  if accesses % 1000 == 0:
    return "{}k".format(accesses // 1000)
  return str(accesses)


def resolve_pattern(pattern, tag, accesses):
  return pattern.replace("{tag}", tag).replace("{accesses}", str(accesses))


def raw_input_path(raw_dir, raw_pattern, workload):
  return path_from_root(raw_dir, raw_pattern.format(workload=workload))


def command_to_text(command):
  return " ".join(command)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=("Run stage 5 real workload suite with fixed "
                   "QMAP-CrossAttn config."))
  parser.add_argument("--accesses", type=int, default=1000000,
                      help="Records kept per workload. Use 1000000 first, then 5000000.")
  parser.add_argument("--workloads", default=",".join(DEFAULT_WORKLOADS),
                      help="Comma-separated workload names.")
  parser.add_argument("--policies", default=",".join(DEFAULT_POLICIES),
                      help="Comma-separated policies. Stage 5 default is all table policies.")
  parser.add_argument("--rank_guard", type=int, default=STAGE5_RANK_GUARD,
                      help=("QMAP inference rank guard. Stage 5 default is "
                            "0, which keeps QMAP-CrossAttn unguarded."))
  parser.add_argument("--rank_score_penalty", type=float,
                      default=STAGE5_RANK_SCORE_PENALTY,
                      help=("QMAP score penalty for newer LRU-tail ranks. "
                            "Stage 5 default is 0; canneal tuning may set "
                            "this separately."))
  parser.add_argument("--device", default="cuda",
                      help="cuda, cpu, or auto. Use auto to let child scripts decide.")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--raw_dir", default=os.path.join("dataset", "raw_traces"))
  parser.add_argument("--raw_pattern", default="{workload}_{tag}.csv",
                      help=("Input file pattern under --raw_dir. Supports "
                            "{workload}, {tag}, and {accesses}."))
  parser.add_argument("--result_root", default=path_from_root(
      "outputs", "results", "real_workload_suite"))
  parser.add_argument("--checkpoint_root", default=path_from_root(
      "outputs", "checkpoints", "real_workload_suite"))
  parser.add_argument("--data_root_name", default="real_workload_suite",
                      help="Subdirectory name under dataset/raw_traces, processed, and jsonl.")
  parser.add_argument("--flat_output", action="store_true",
                      help=("Write summary/workload outputs directly in result_root and "
                            "checkpoints directly in checkpoint_root. By default, "
                            "outputs are grouped under the access tag, e.g. 1m/."))
  parser.add_argument("--skip", type=int, default=0,
                      help="Global raw trace records skipped before applying --accesses.")
  parser.add_argument("--dedup_skip", type=int, default=0,
                      help="Optional parsec_dedup skip override for pressure-window runs.")
  parser.add_argument("--workload_skips", default="",
                      help="Additional workload=skip overrides passed through.")
  parser.add_argument("--run_id", default=None)
  parser.add_argument("--skip_prepare", action="store_true")
  parser.add_argument("--skip_generate", action="store_true")
  parser.add_argument("--skip_train", action="store_true")
  parser.add_argument("--dry_run", action="store_true",
                      help="Print the child command without running it.")
  parser.add_argument("--skip_raw_check", action="store_true",
                      help="Do not verify that every patterned raw trace exists.")
  return parser


def append_if(command, enabled, *items):
  if enabled:
    command.extend(items)


def build_workload_skips(args):
  items = split_csv(args.workload_skips)
  if args.dedup_skip:
    items.append("parsec_dedup={}".format(args.dedup_skip))
  return ",".join(items)


def write_stage5_config(path, args, tag, command, result_dir, checkpoint_dir):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  config = {
      "created_at": datetime.now().isoformat(timespec="seconds"),
      "accesses": args.accesses,
      "tag": tag,
      "workloads": split_csv(args.workloads),
      "policies": split_csv(args.policies),
      "history_length": STAGE5_HISTORY_LENGTH,
      "candidate_count": STAGE5_CANDIDATE_COUNT,
      "rank_guard": args.rank_guard,
      "rank_score_penalty": args.rank_score_penalty,
      "dram_capacity": STAGE5_DRAM_CAPACITY,
      "lookahead": STAGE5_LOOKAHEAD,
      "epochs": STAGE5_EPOCHS,
      "batch_size": STAGE5_BATCH_SIZE,
      "model": STAGE5_MODEL,
      "ablation": STAGE5_ABLATION,
      "result_dir": result_dir,
      "checkpoint_dir": checkpoint_dir,
      "command": command,
  }
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(config, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def copy_tagged_summaries(result_dir, result_root, tag):
  if os.path.abspath(result_dir) == os.path.abspath(result_root):
    return
  os.makedirs(result_root, exist_ok=True)
  for extension in ("csv", "md"):
    source = os.path.join(result_dir, "summary.{}".format(extension))
    if os.path.exists(source):
      shutil.copyfile(
          source, os.path.join(result_root, "summary_{}.{}".format(
              tag, extension)))


def check_raw_inputs(args, raw_pattern):
  missing = []
  for workload in split_csv(args.workloads):
    path = raw_input_path(args.raw_dir, raw_pattern, workload)
    if not os.path.exists(path):
      missing.append(path)
  if missing:
    lines = ["Missing stage 5 raw trace input(s):"]
    lines.extend("  {}".format(path) for path in missing)
    lines.append(
        "Generate or copy the requested *_{} files before rerunning.".format(
            access_tag(args.accesses)))
    raise FileNotFoundError("\n".join(lines))


def main():
  args = build_arg_parser().parse_args()
  if args.accesses < 0:
    raise ValueError("--accesses must be non-negative.")
  if args.skip < 0:
    raise ValueError("--skip must be non-negative.")
  if args.dedup_skip < 0:
    raise ValueError("--dedup_skip must be non-negative.")
  if args.rank_guard < 0:
    raise ValueError("--rank_guard must be non-negative.")
  if args.rank_guard and args.rank_guard > STAGE5_CANDIDATE_COUNT:
    raise ValueError("--rank_guard cannot exceed candidate_count.")
  if args.rank_score_penalty < 0.0:
    raise ValueError("--rank_score_penalty must be non-negative.")

  tag = access_tag(args.accesses)
  result_dir = args.result_root
  checkpoint_dir = args.checkpoint_root
  if not args.flat_output:
    result_dir = os.path.join(args.result_root, tag)
    checkpoint_dir = os.path.join(args.checkpoint_root, tag)

  data_root = args.data_root_name
  data_suffix = "" if args.flat_output else tag
  data_parts = [data_root] + ([data_suffix] if data_suffix else [])
  normalized_raw_dir = path_from_root("dataset", "raw_traces", *data_parts)
  processed_dir = path_from_root("dataset", "processed", *data_parts)
  jsonl_dir = path_from_root("dataset", "jsonl", *data_parts)
  manifest = path_from_root(
      "dataset", "metadata", "{}_{}_manifest.json".format(data_root, tag))
  stats_dir = os.path.join(result_dir, "trace_stats")
  run_id = args.run_id or "{}_{}".format(data_root, tag)
  raw_pattern = resolve_pattern(args.raw_pattern, tag, args.accesses)
  workload_skips = build_workload_skips(args)
  if not args.skip_prepare and not args.skip_raw_check:
    check_raw_inputs(args, raw_pattern)

  command = [
      args.python, "scripts/run_real_pilot.py",
      "--workloads", args.workloads,
      "--policies", args.policies,
      "--limit", str(args.accesses),
      "--skip", str(args.skip),
      "--raw_dir", args.raw_dir,
      "--raw_pattern", raw_pattern,
      "--history_length", str(STAGE5_HISTORY_LENGTH),
      "--candidate_count", str(STAGE5_CANDIDATE_COUNT),
      "--rank_guard", str(args.rank_guard),
      "--rank_score_penalty", str(args.rank_score_penalty),
      "--dram_capacity", str(STAGE5_DRAM_CAPACITY),
      "--lookahead", str(STAGE5_LOOKAHEAD),
      "--epochs", str(STAGE5_EPOCHS),
      "--batch_size", str(STAGE5_BATCH_SIZE),
      "--run_id", run_id,
      "--normalized_raw_dir", normalized_raw_dir,
      "--processed_dir", processed_dir,
      "--jsonl_dir", jsonl_dir,
      "--result_dir", result_dir,
      "--checkpoint_dir", checkpoint_dir,
      "--manifest", manifest,
      "--stats_dir", stats_dir,
  ]
  if workload_skips:
    command.extend(["--workload_skips", workload_skips])
  if args.device and args.device != "auto":
    command.extend(["--device", args.device])
  append_if(command, args.skip_prepare, "--skip_prepare")
  append_if(command, args.skip_generate, "--skip_generate")
  append_if(command, args.skip_train, "--skip_train")

  print("[stage5] {}".format(command_to_text(command)), flush=True)
  if args.dry_run:
    print("[stage5] dry run; no files written")
    return

  config_path = os.path.join(result_dir, "stage5_config.json")
  write_stage5_config(config_path, args, tag, command, result_dir,
                      checkpoint_dir)

  process = subprocess.run(command, cwd=PROJECT_ROOT)
  if process.returncode != 0:
    raise subprocess.CalledProcessError(process.returncode, command)
  copy_tagged_summaries(result_dir, args.result_root, tag)
  print("[stage5] summary={}".format(os.path.join(result_dir, "summary.md")))
  print("[stage5] checkpoints={}".format(checkpoint_dir))


if __name__ == "__main__":
  main()
