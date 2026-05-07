# coding=utf-8
"""Build page-granularity traces for hybrid-memory page replacement.

The generated trace schema is compatible with qmap_generator.py:

  PC,Address,RW
  0x400100,0x100000000,R
  0x400104,0x100001000,W

Address is aligned to page granularity, so qmap_generator.py should normally be
called with the same page shift, for example --page_shift 12 for 4 KB pages.
"""

import argparse
import csv
import random


READ_VALUES = ("0", "r", "read", "load", "l")
WRITE_VALUES = ("1", "w", "write", "store", "s")


def parse_int(value):
  return int(str(value).strip(), 0)


def parse_rw(value):
  normalized = str(value).strip().lower()
  if normalized in READ_VALUES:
    return "R"
  if normalized in WRITE_VALUES:
    return "W"
  raise ValueError("Unsupported RW value: {}".format(value))


def is_header(row):
  names = {column.strip().lower() for column in row}
  return bool(names & {"pc", "address", "addr", "rw"})


def parse_header(row):
  normalized = [column.strip().lower() for column in row]
  pc_index = None
  address_index = None
  rw_index = None
  for index, name in enumerate(normalized):
    if name == "pc":
      pc_index = index
    elif name in ("address", "addr"):
      address_index = index
    elif name == "rw":
      rw_index = index

  if pc_index is None or address_index is None:
    raise ValueError("Input header must contain PC and Address columns.")
  return pc_index, address_index, rw_index


def page_align(address, page_shift):
  page_size = 1 << page_shift
  return address & ~(page_size - 1)


def write_trace(rows, output_path):
  with open(output_path, "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(("PC", "Address", "RW"))
    for pc, address, rw in rows:
      writer.writerow((hex(pc), hex(address), rw))


def convert_trace(input_path, output_path, page_shift, fallback_rw):
  rows = []
  header_indices = None
  with open(input_path, "r") as input_file:
    reader = csv.reader(input_file)
    for row_number, row in enumerate(reader, start=1):
      if not row:
        continue
      if row_number == 1 and is_header(row):
        header_indices = parse_header(row)
        continue

      if header_indices is None:
        if len(row) not in (2, 3):
          raise ValueError(
              "Line {} must be pc,address[,rw].".format(row_number))
        pc = parse_int(row[0])
        address = parse_int(row[1])
        rw = parse_rw(row[2]) if len(row) == 3 else parse_rw(fallback_rw)
      else:
        pc_index, address_index, rw_index = header_indices
        required_index = max(pc_index, address_index)
        if rw_index is not None:
          required_index = max(required_index, rw_index)
        if len(row) <= required_index:
          raise ValueError(
              "Line {} is missing required columns.".format(row_number))
        pc = parse_int(row[pc_index])
        address = parse_int(row[address_index])
        rw = parse_rw(row[rw_index]) if rw_index is not None else parse_rw(
            fallback_rw)

      rows.append((pc, page_align(address, page_shift), rw))

  write_trace(rows, output_path)
  return len(rows)


def choose_page(rng, phase, hot_pages, cold_pages, scan_pages):
  selector = rng.random()
  if phase % 4 == 0:
    if selector < 0.72:
      return rng.choice(hot_pages)
    if selector < 0.90:
      return rng.choice(cold_pages)
    return rng.choice(scan_pages)
  if phase % 4 == 1:
    if selector < 0.54:
      return rng.choice(hot_pages)
    if selector < 0.74:
      return rng.choice(cold_pages)
    return rng.choice(scan_pages)
  if phase % 4 == 2:
    if selector < 0.62:
      return rng.choice(cold_pages)
    if selector < 0.84:
      return rng.choice(hot_pages)
    return rng.choice(scan_pages)
  if selector < 0.48:
    return rng.choice(scan_pages)
  if selector < 0.82:
    return rng.choice(hot_pages)
  return rng.choice(cold_pages)


def synthetic_rw(rng, page, hot_pages, write_hot_pages, base_write_ratio):
  if page in write_hot_pages:
    write_probability = max(base_write_ratio, 0.72)
  elif page in hot_pages:
    write_probability = max(base_write_ratio * 0.7, 0.18)
  else:
    write_probability = max(base_write_ratio * 0.45, 0.05)
  return "W" if rng.random() < write_probability else "R"


def synthesize_trace(args):
  rng = random.Random(args.seed)
  base_page = args.base_address >> args.page_shift
  pages = list(range(base_page, base_page + args.working_set_pages))

  hot_count = min(args.hot_pages, len(pages))
  write_hot_count = max(1, hot_count // 4)
  hot_pages = pages[:hot_count]
  write_hot_pages = set(hot_pages[:write_hot_count])
  cold_pages = pages[hot_count:max(hot_count + 1, len(pages) * 3 // 4)]
  scan_pages = pages[max(hot_count + 1, len(pages) * 3 // 4):]
  if not cold_pages:
    cold_pages = hot_pages
  if not scan_pages:
    scan_pages = pages

  rows = []
  phase_length = max(1, args.phase_length)
  for index in range(args.records):
    phase = index // phase_length
    page = choose_page(rng, phase, hot_pages, cold_pages, scan_pages)

    if phase % 4 == 3 and scan_pages:
      page = scan_pages[(index + phase) % len(scan_pages)]

    pc_region = phase % max(1, args.pc_regions)
    pc_offset = rng.randrange(args.pc_count) * 4
    pc = args.pc_base + pc_region * 0x1000 + pc_offset
    address = page << args.page_shift
    rw = synthetic_rw(rng, page, set(hot_pages), write_hot_pages,
                      args.write_ratio)
    rows.append((pc, address, rw))

  write_trace(rows, args.output)
  return len(rows)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Build page-aligned PC,Address,RW traces.")
  parser.add_argument("--input", default=None,
                      help="Optional existing PC,Address[,RW] trace to align.")
  parser.add_argument("--output",
                      default="environment/traces/hybrid_page_trace.csv")
  parser.add_argument("--page_shift", type=int, default=12,
                      help="12 means 4 KB page granularity.")
  parser.add_argument("--fallback_rw", default="R",
                      help="RW value used when converting a trace without RW.")

  parser.add_argument("--records", type=int, default=20000)
  parser.add_argument("--working_set_pages", type=int, default=512)
  parser.add_argument("--hot_pages", type=int, default=64)
  parser.add_argument("--write_ratio", type=float, default=0.30)
  parser.add_argument("--phase_length", type=int, default=2000)
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--base_address", type=parse_int, default=0x100000000)
  parser.add_argument("--pc_base", type=parse_int, default=0x400000)
  parser.add_argument("--pc_count", type=int, default=128)
  parser.add_argument("--pc_regions", type=int, default=4)
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.input:
    count = convert_trace(args.input, args.output, args.page_shift,
                          args.fallback_rw)
    mode = "converted"
  else:
    count = synthesize_trace(args)
    mode = "synthetic"

  page_size = 1 << args.page_shift
  print("Trace mode: {}".format(mode))
  print("Page size: {} bytes".format(page_size))
  print("Records: {}".format(count))
  print("Wrote: {}".format(args.output))


if __name__ == "__main__":
  main()
