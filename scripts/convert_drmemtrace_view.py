# coding=utf-8
"""Convert DynamoRIO drmemtrace "view" output to QMAP CSV.

The drmemtrace view tool prints data references like:

  10 2: W0.T292 write 8 byte(s) @ 0x... by PC 0x...

This converter extracts only data reads/writes and writes the legacy
QMAP-compatible schema by default:

  PC,Address,RW

Stage 7 passes ``--include-process-thread`` to preserve the observed identity:

  PID,TID,PC,Address,RW
"""

import argparse
import csv
import re
import sys


DATA_REF_RE = re.compile(
    r"\b(?P<kind>read|write)\s+"
    r"(?P<size>\d+)\s+byte\(s\)\s+@\s+"
    r"(?P<address>0x[0-9a-fA-F]+)\s+by PC\s+"
    r"(?P<pc>0x[0-9a-fA-F]+)")
VIEW_THREAD_RE = re.compile(
    r"^\s*\d+\s+\d+:\s+W(?P<workload_id>\d+)\.T(?P<tid>\d+)\b")


def page_align(address, page_shift):
  if page_shift <= 0:
    return address
  page_size = 1 << page_shift
  return address & ~(page_size - 1)


def convert_stream(input_stream, output_stream, limit, skip, page_shift,
                   keep_raw_address, include_process_thread=False,
                   process_id=None):
  if include_process_thread and process_id is None:
    raise ValueError(
        "Stage-7 PID must come from the drmemtrace directory identity.")
  writer = csv.writer(output_stream)
  if include_process_thread:
    writer.writerow(("PID", "TID", "PC", "Address", "RW"))
  else:
    writer.writerow(("PC", "Address", "RW"))

  seen_data_refs = 0
  written = 0
  process_ids = set()
  thread_ids = set()
  for line in input_stream:
    match = DATA_REF_RE.search(line)
    if not match:
      continue
    identity = VIEW_THREAD_RE.search(line)
    if include_process_thread and identity is None:
      raise ValueError(
          "drmemtrace data reference lacks a W#.T# thread identity: {}".format(
              line.rstrip()))

    seen_data_refs += 1
    if seen_data_refs <= skip:
      continue

    pc = int(match.group("pc"), 16)
    address = int(match.group("address"), 16)
    if not keep_raw_address:
      address = page_align(address, page_shift)
    rw = "W" if match.group("kind") == "write" else "R"
    if include_process_thread:
      pid = int(process_id)
      tid = int(identity.group("tid"))
      process_ids.add(pid)
      thread_ids.add(tid)
      writer.writerow((pid, tid, hex(pc), hex(address), rw))
    else:
      writer.writerow((hex(pc), hex(address), rw))
    written += 1

    if limit and written >= limit:
      break

  return {
      "seen_data_refs": seen_data_refs,
      "written": written,
      "process_ids": sorted(process_ids),
      "thread_ids": sorted(thread_ids),
  }


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Convert DynamoRIO drmemtrace view output to PC,Address,RW.")
  parser.add_argument("--input", default="-",
                      help="Input view log. Use '-' for stdin.")
  parser.add_argument("--output", required=True,
                      help="Output QMAP CSV path.")
  parser.add_argument("--limit", type=int, default=100000,
                      help="Maximum data references to write. 0 means all.")
  parser.add_argument("--skip", type=int, default=0,
                      help="Data references to skip before writing.")
  parser.add_argument("--page-shift", type=int, default=12,
                      help="Align addresses to this page size by default.")
  parser.add_argument("--keep-raw-address", action="store_true",
                      help="Do not page-align addresses.")
  parser.add_argument(
      "--include-process-thread", action="store_true",
      help="Write PID,TID,PC,Address,RW and reject unidentifiable records.")
  parser.add_argument(
      "--process-id", type=int, default=None,
      help="PID from the drmemtrace directory name; required with "
           "--include-process-thread.")
  parser.add_argument("--allow-short", action="store_true",
                      help="Do not fail if fewer than --limit records exist.")
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.limit < 0:
    raise ValueError("--limit must be non-negative.")
  if args.skip < 0:
    raise ValueError("--skip must be non-negative.")

  input_file = sys.stdin if args.input == "-" else open(args.input, "r")
  try:
    with open(args.output, "w", newline="") as output_file:
      stats = convert_stream(
          input_file, output_file, args.limit, args.skip, args.page_shift,
          args.keep_raw_address, args.include_process_thread,
          args.process_id)
  finally:
    if input_file is not sys.stdin:
      input_file.close()

  print("Seen data refs: {}".format(stats["seen_data_refs"]))
  print("Wrote records: {}".format(stats["written"]))
  if args.include_process_thread:
    print("Process IDs: {}".format(stats["process_ids"]))
    print("Thread IDs: {}".format(stats["thread_ids"]))
  print("Output: {}".format(args.output))
  if args.limit and stats["written"] < args.limit and not args.allow_short:
    raise SystemExit(
        "Only wrote {} records, fewer than requested {}. Increase the "
        "drmemtrace trace window or pass --allow-short.".format(
            stats["written"], args.limit))


if __name__ == "__main__":
  main()
