# coding=utf-8
"""Scan raw traces for chronological-split pressure windows.

The stage 5 runner prepares each selected raw window with an 80/10/10
chronological split. A raw trace can look high-pressure overall while its final
test tail has no eviction pressure. This helper scores candidate (skip, limit)
windows by the LRU decision count in the future test split.
"""

import argparse
import csv
import os


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_WORKLOADS = ("parsec_streamcluster", "parsec_dedup")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_int(value):
  return int(str(value).strip(), 0)


def read_pages(path, page_shift):
  pages = []
  writes = []
  with open(path, newline="", encoding="utf-8") as input_file:
    reader = csv.DictReader(input_file)
    for row in reader:
      address_text = row.get("Address") or row.get("address")
      rw_text = (row.get("RW") or row.get("rw") or "R").strip().lower()
      address = parse_int(address_text)
      pages.append(address >> page_shift if page_shift > 0 else address)
      writes.append(1 if rw_text in ("1", "w", "write", "store", "s") else 0)
  return pages, writes


def lru_pressure(pages, dram_capacity):
  dram = []
  misses = 0
  decisions = 0
  for page in pages:
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


def scan_window(workload, raw_path, pages, writes, limit, step,
                dram_capacity, top_k):
  rows = []
  if limit <= 0 or limit > len(pages):
    return rows
  for skip in range(0, len(pages) - limit + 1, step):
    window_pages = pages[skip:skip + limit]
    window_writes = writes[skip:skip + limit]
    train_end = int(limit * 0.8)
    valid_end = int(limit * 0.9)
    test_pages = window_pages[valid_end:]
    test_writes = window_writes[valid_end:]
    _, decisions = lru_pressure(test_pages, dram_capacity)
    misses, full_decisions = lru_pressure(window_pages, dram_capacity)
    rows.append({
        "workload": workload,
        "raw_path": raw_path,
        "skip": skip,
        "limit": limit,
        "test_start": skip + valid_end,
        "test_end": skip + limit,
        "test_records": len(test_pages),
        "test_unique_pages": len(set(test_pages)),
        "test_write_ratio": (
            sum(test_writes) / float(len(test_writes)) if test_writes else 0.0),
        "test_lru_decisions": decisions,
        "window_unique_pages": len(set(window_pages)),
        "window_lru_misses": misses,
        "window_lru_decisions": full_decisions,
    })
  rows.sort(key=lambda row: (
      row["test_lru_decisions"],
      row["test_unique_pages"],
      row["window_lru_decisions"]), reverse=True)
  return rows[:top_k]


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Scan raw traces for high-pressure test windows.")
  parser.add_argument("--workloads", default=",".join(DEFAULT_WORKLOADS))
  parser.add_argument("--raw_dir", default=path_from_root(
      "dataset", "raw_traces"))
  parser.add_argument("--raw_pattern", default="{workload}_1m.csv")
  parser.add_argument("--limits", default="100000,200000",
                      help="Comma-separated selected raw window sizes.")
  parser.add_argument("--step", type=int, default=10000)
  parser.add_argument("--dram_capacity", type=int, default=16)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--top_k", type=int, default=10)
  parser.add_argument("--output_dir", default=path_from_root(
      "outputs", "results", "real_workload_suite", "pressure_windows"))
  return parser


def write_outputs(rows, output_dir):
  os.makedirs(output_dir, exist_ok=True)
  csv_path = os.path.join(output_dir, "pressure_windows.csv")
  fields = [
      "workload",
      "skip",
      "limit",
      "test_start",
      "test_end",
      "test_records",
      "test_unique_pages",
      "test_write_ratio",
      "test_lru_decisions",
      "window_unique_pages",
      "window_lru_misses",
      "window_lru_decisions",
      "raw_path",
  ]
  with open(csv_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row[field] for field in fields})

  md_path = os.path.join(output_dir, "pressure_windows.md")
  with open(md_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Pressure Window Scan\n\n")
    output_file.write(
        "| Workload | Skip | Limit | Test range | Test pages | "
        "Test write ratio | Test LRU decisions | Window decisions |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output_file.write(
          "| {workload} | {skip} | {limit} | {test_start}-{test_end} | "
          "{test_unique_pages} | {test_write_ratio:.4f} | "
          "{test_lru_decisions} | {window_lru_decisions} |\n".format(**row))
  return csv_path, md_path


def main():
  args = build_arg_parser().parse_args()
  if args.step <= 0:
    raise ValueError("--step must be positive.")
  workloads = split_csv(args.workloads)
  limits = [int(value) for value in split_csv(args.limits)]
  all_rows = []
  for workload in workloads:
    raw_path = os.path.join(
        args.raw_dir, args.raw_pattern.format(workload=workload))
    if not os.path.exists(raw_path):
      raise FileNotFoundError(raw_path)
    pages, writes = read_pages(raw_path, args.page_shift)
    for limit in limits:
      all_rows.extend(scan_window(
          workload, raw_path, pages, writes, limit, args.step,
          args.dram_capacity, args.top_k))
  all_rows.sort(key=lambda row: (
      row["workload"],
      -row["test_lru_decisions"],
      -row["test_unique_pages"],
      row["limit"],
      row["skip"]))
  csv_path, md_path = write_outputs(all_rows, args.output_dir)
  print("[done] csv={}".format(csv_path))
  print("[done] md={}".format(md_path))


if __name__ == "__main__":
  main()
