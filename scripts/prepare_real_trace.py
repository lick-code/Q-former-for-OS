# coding=utf-8
"""Normalize, split, and summarize real QMAP traces.

Input and output schema:

  PC,Address,RW

The script keeps chronological order, writes an 80/10/10 train/valid/test split,
and updates a manifest plus a compact quality summary.
"""

import argparse
import collections
import csv
import json
import os
import sys
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
READ_VALUES = ("0", "r", "read", "load", "l")
WRITE_VALUES = ("1", "w", "write", "store", "s")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def rel_path(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def parse_int(value):
  return int(str(value).strip(), 0)


def parse_rw(value):
  normalized = str(value).strip().lower()
  if normalized in READ_VALUES:
    return "R"
  if normalized in WRITE_VALUES:
    return "W"
  raise ValueError("Unsupported RW value: {}".format(value))


def is_header_row(row):
  normalized = {column.strip().lower() for column in row}
  return bool(normalized & {"pc", "address", "addr", "rw"})


def parse_header(row):
  normalized = [column.strip().lower() for column in row]
  indices = {"pc": None, "address": None, "rw": None}
  for index, name in enumerate(normalized):
    if name == "pc":
      indices["pc"] = index
    elif name in ("address", "addr"):
      indices["address"] = index
    elif name == "rw":
      indices["rw"] = index
  missing = [name for name in ("pc", "address") if indices[name] is None]
  if missing:
    raise ValueError("Missing required columns: {}".format(", ".join(missing)))
  return indices


def page_align(address, page_shift):
  if page_shift <= 0:
    return address
  page_size = 1 << page_shift
  return address & ~(page_size - 1)


def read_trace(input_path, page_shift, keep_raw_address, fallback_rw, skip,
               limit):
  rows = []
  header = None
  data_seen = 0

  with open(input_path, "r", newline="") as input_file:
    reader = csv.reader(input_file)
    for row_number, row in enumerate(reader, start=1):
      if not row:
        continue
      if row_number == 1 and is_header_row(row):
        header = parse_header(row)
        continue

      if header is None:
        if len(row) not in (2, 3):
          raise ValueError("Line {} must be pc,address[,rw].".format(
              row_number))
        pc = parse_int(row[0])
        address = parse_int(row[1])
        rw = parse_rw(row[2]) if len(row) == 3 else parse_rw(fallback_rw)
      else:
        required = max(header["pc"], header["address"])
        if header["rw"] is not None:
          required = max(required, header["rw"])
        if len(row) <= required:
          raise ValueError("Line {} is missing required columns.".format(
              row_number))
        pc = parse_int(row[header["pc"]])
        address = parse_int(row[header["address"]])
        if header["rw"] is None:
          rw = parse_rw(fallback_rw)
        else:
          rw = parse_rw(row[header["rw"]])

      data_seen += 1
      if data_seen <= skip:
        continue
      if not keep_raw_address:
        address = page_align(address, page_shift)
      rows.append((pc, address, rw))
      if limit and len(rows) >= limit:
        break

  return rows


def write_trace(rows, output_path):
  os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
  with open(output_path, "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(("PC", "Address", "RW"))
    for pc, address, rw in rows:
      writer.writerow((hex(pc), hex(address), rw))


def split_rows(rows):
  if len(rows) < 10:
    raise ValueError("Trace is too small to split: {} records.".format(
        len(rows)))
  train_end = int(len(rows) * 0.8)
  valid_end = int(len(rows) * 0.9)
  return {
      "train": rows[:train_end],
      "valid": rows[train_end:valid_end],
      "test": rows[valid_end:],
  }


def split_stats(rows, page_shift):
  total = len(rows)
  writes = sum(1 for _, _, rw in rows if rw == "W")
  pages = {address >> page_shift if page_shift > 0 else address
           for _, address, _ in rows}
  return {
      "records": total,
      "unique_pages": len(pages),
      "write_ratio": writes / float(total) if total else 0.0,
  }


def compute_stats(rows, page_shift):
  total = len(rows)
  reads = sum(1 for _, _, rw in rows if rw == "R")
  writes = sum(1 for _, _, rw in rows if rw == "W")
  pages = [
      address >> page_shift if page_shift > 0 else address
      for _, address, _ in rows
  ]
  pcs = [pc for pc, _, _ in rows]
  page_counts = collections.Counter(pages)
  pc_counts = collections.Counter(pcs)

  last_seen = {}
  reuse_distances = []
  for index, page in enumerate(pages):
    if page in last_seen:
      reuse_distances.append(index - last_seen[page])
    last_seen[page] = index

  top_pages = []
  for page, count in page_counts.most_common(10):
    address = page << page_shift if page_shift > 0 else page
    top_pages.append({
        "page_address": hex(address),
        "accesses": count,
        "share": count / float(total) if total else 0.0,
    })

  return {
      "total_accesses": total,
      "read_accesses": reads,
      "write_accesses": writes,
      "write_ratio": writes / float(total) if total else 0.0,
      "unique_pages": len(page_counts),
      "unique_pcs": len(pc_counts),
      "reuse_events": len(reuse_distances),
      "page_reuse_ratio": (
          len(reuse_distances) / float(total) if total else 0.0),
      "mean_reuse_distance": (
          sum(reuse_distances) / float(len(reuse_distances))
          if reuse_distances else None),
      "top_pages": top_pages,
  }


def load_manifest(path):
  if not os.path.exists(path):
    return {"workloads": {}}
  with open(path, "r") as input_file:
    manifest = json.load(input_file)
  if "workloads" not in manifest:
    manifest = {"workloads": manifest}
  return manifest


def write_manifest(manifest, path):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w") as output_file:
    json.dump(manifest, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def write_stats_outputs(manifest, stats_dir):
  os.makedirs(stats_dir, exist_ok=True)
  summary_path = os.path.join(stats_dir, "summary.md")
  with open(summary_path, "w") as output_file:
    output_file.write("# Real Trace Stats\n\n")
    output_file.write(
        "| Workload | Records | Unique pages | Unique PCs | Write ratio | "
        "Reuse ratio | Train/Valid/Test |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|\n")
    for workload in sorted(manifest.get("workloads", {})):
      entry = manifest["workloads"][workload]
      stats = entry["stats"]
      splits = entry["splits"]
      split_text = "{}/{}/{}".format(
          splits["train"]["records"], splits["valid"]["records"],
          splits["test"]["records"])
      output_file.write(
          "| {workload} | {records} | {pages} | {pcs} | {write:.4f} | "
          "{reuse:.4f} | {split_text} |\n".format(
              workload=workload,
              records=stats["total_accesses"],
              pages=stats["unique_pages"],
              pcs=stats["unique_pcs"],
              write=stats["write_ratio"],
              reuse=stats["page_reuse_ratio"],
              split_text=split_text))

      detail_path = os.path.join(stats_dir, "{}.json".format(workload))
      with open(detail_path, "w") as detail_file:
        json.dump(entry, detail_file, indent=2, sort_keys=True)
        detail_file.write("\n")
  return summary_path


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Prepare a real PC,Address,RW trace for QMAP.")
  parser.add_argument("--input", required=True)
  parser.add_argument("--workload", default=None,
                      help="Workload name. Default uses input file stem.")
  parser.add_argument("--raw-output", default=None,
                      help="Normalized raw trace output path.")
  parser.add_argument("--processed-dir",
                      default=path_from_root("dataset", "processed"))
  parser.add_argument("--manifest",
                      default=path_from_root("dataset", "metadata",
                                             "real_workload_manifest.json"))
  parser.add_argument("--stats-dir",
                      default=path_from_root("outputs", "results",
                                             "real_trace_stats"))
  parser.add_argument("--page-shift", type=int, default=12)
  parser.add_argument("--limit", type=int, default=100000,
                      help="Maximum records to keep. 0 means all.")
  parser.add_argument("--skip", type=int, default=0)
  parser.add_argument("--keep-raw-address", action="store_true")
  parser.add_argument("--fallback-rw", default=None,
                      help="RW value if input has no RW column.")
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.limit < 0:
    raise ValueError("--limit must be non-negative.")
  if args.skip < 0:
    raise ValueError("--skip must be non-negative.")

  workload = args.workload or os.path.splitext(os.path.basename(
      args.input))[0]
  raw_output = args.raw_output or path_from_root(
      "dataset", "raw_traces", "{}.csv".format(workload))

  fallback_rw = args.fallback_rw
  if fallback_rw is None:
    fallback_rw = "R"

  rows = read_trace(
      args.input, args.page_shift, args.keep_raw_address, fallback_rw,
      args.skip, args.limit)
  splits = split_rows(rows)

  write_trace(rows, raw_output)
  split_paths = {}
  split_manifest = {}
  for split_name, split_rows_value in splits.items():
    split_path = os.path.join(
        args.processed_dir, "{}_{}.csv".format(workload, split_name))
    write_trace(split_rows_value, split_path)
    split_paths[split_name] = split_path
    split_manifest[split_name] = {
        "file": rel_path(split_path),
        "records": len(split_rows_value),
        "stats": split_stats(split_rows_value, args.page_shift),
    }

  stats = compute_stats(rows, args.page_shift)
  manifest = load_manifest(args.manifest)
  manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
  manifest["workloads"][workload] = {
      "source_trace": rel_path(args.input),
      "raw_trace": rel_path(raw_output),
      "split_policy": "chronological 80/10/10",
      "page_shift": args.page_shift,
      "limit": args.limit,
      "skip": args.skip,
      "stats": stats,
      "splits": split_manifest,
  }
  write_manifest(manifest, args.manifest)
  summary_path = write_stats_outputs(manifest, args.stats_dir)

  print("Workload: {}".format(workload))
  print("Records: {}".format(len(rows)))
  print("Raw trace: {}".format(raw_output))
  print("Train split: {}".format(split_paths["train"]))
  print("Valid split: {}".format(split_paths["valid"]))
  print("Test split: {}".format(split_paths["test"]))
  print("Manifest: {}".format(args.manifest))
  print("Stats summary: {}".format(summary_path))


if __name__ == "__main__":
  main()
