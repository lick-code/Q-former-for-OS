# coding=utf-8
"""Build a small synthetic workload suite for QMAP experiments.

The script generates raw CSV traces and chronological train/valid/test splits
for workloads with different locality and write behavior:

  hotset       strong hot-page locality
  writeheavy   write-intensive hot pages
  streaming    sequential scan with little reuse
  phasechange  shifting hot sets across phases
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

WORKLOAD_CONFIGS = {
    "hotset": {
        "seed": 1101,
        "working_set_pages": 512,
        "hot_pages": 32,
        "write_ratio": 0.24,
        "phase_length": 2500,
    },
    "writeheavy": {
        "seed": 2202,
        "working_set_pages": 512,
        "hot_pages": 96,
        "write_ratio": 0.78,
        "phase_length": 2000,
    },
    "streaming": {
        "seed": 3303,
        "working_set_pages": 2048,
        "hot_pages": 16,
        "write_ratio": 0.10,
        "phase_length": 2048,
    },
    "phasechange": {
        "seed": 4404,
        "working_set_pages": 1024,
        "hot_pages": 96,
        "write_ratio": 0.32,
        "phase_length": 2500,
    },
}

DEFAULT_WORKLOADS = ("hotset", "writeheavy", "streaming", "phasechange")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel_path(path):
  return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


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
  return {
      "train": (0, train_end - 1, train_end),
      "valid": (train_end, valid_end - 1, valid_end - train_end),
      "test": (valid_end, len(data_rows) - 1, len(data_rows) - valid_end),
  }


def trace_stats(input_path):
  with open(input_path, "r", newline="") as input_file:
    reader = csv.DictReader(input_file)
    rows = list(reader)
  pages = {row["Address"] for row in rows}
  writes = sum(1 for row in rows if row["RW"].strip().upper() == "W")
  total = len(rows)
  return {
      "total_records": total,
      "unique_pages": len(pages),
      "write_records": writes,
      "write_ratio": round(writes / float(total), 4) if total else 0.0,
  }


def run_trace_builder(args, workload, raw_path):
  config = WORKLOAD_CONFIGS[workload]
  command = [
      args.python,
      path_from_root("qmap", "trace_builder.py"),
      "--output", raw_path,
      "--page_shift", str(args.page_shift),
      "--records", str(args.records),
      "--workload", workload,
      "--working_set_pages", str(config["working_set_pages"]),
      "--hot_pages", str(config["hot_pages"]),
      "--write_ratio", str(config["write_ratio"]),
      "--phase_length", str(config["phase_length"]),
      "--seed", str(config["seed"]),
  ]
  subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def build_workload(args, workload):
  raw_path = path_from_root(args.raw_dir, "{}.csv".format(workload))
  train_path = path_from_root(args.processed_dir, "{}_train.csv".format(workload))
  valid_path = path_from_root(args.processed_dir, "{}_valid.csv".format(workload))
  test_path = path_from_root(args.processed_dir, "{}_test.csv".format(workload))

  os.makedirs(os.path.dirname(raw_path), exist_ok=True)
  run_trace_builder(args, workload, raw_path)
  split_ranges = split_trace(raw_path, train_path, valid_path, test_path)
  stats = trace_stats(raw_path)

  return {
      "description": {
          "hotset": "Strong locality around a small hot page set.",
          "writeheavy": "Write-intensive accesses concentrated on hot pages.",
          "streaming": "Sequential scan with low temporal reuse.",
          "phasechange": "Hot page set and write behavior shift by phase.",
      }[workload],
      "source_trace": rel_path(raw_path),
      "split_policy": "chronological 80/10/10",
      "stats": stats,
      "train": {
          "file": rel_path(train_path),
          "range": [split_ranges["train"][0], split_ranges["train"][1]],
          "records": split_ranges["train"][2],
      },
      "valid": {
          "file": rel_path(valid_path),
          "range": [split_ranges["valid"][0], split_ranges["valid"][1]],
          "records": split_ranges["valid"][2],
      },
      "test": {
          "file": rel_path(test_path),
          "range": [split_ranges["test"][0], split_ranges["test"][1]],
          "records": split_ranges["test"][2],
      },
  }


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Build QMAP workload CSV suite.")
  parser.add_argument("--records", type=int, default=20000)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--raw_dir", default=os.path.join("dataset", "raw_traces"))
  parser.add_argument("--processed_dir",
                      default=os.path.join("dataset", "processed"))
  parser.add_argument("--metadata",
                      default=os.path.join("dataset", "metadata",
                                           "workload_manifest.json"))
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--workloads", nargs="+",
                      choices=sorted(WORKLOAD_CONFIGS.keys()),
                      default=DEFAULT_WORKLOADS)
  return parser


def main():
  args = build_arg_parser().parse_args()
  manifest = {}
  for workload in args.workloads:
    print("[build] {}".format(workload), flush=True)
    manifest[workload] = build_workload(args, workload)

  metadata_path = path_from_root(args.metadata)
  os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
  with open(metadata_path, "w") as output_file:
    json.dump(manifest, output_file, indent=2, sort_keys=True)
    output_file.write("\n")
  print("[done] wrote {}".format(metadata_path))


if __name__ == "__main__":
  main()
