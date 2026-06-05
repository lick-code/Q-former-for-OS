# coding=utf-8
"""Generate QMAP JSONL training samples from a simple PC/address CSV trace.

输入 CSV 当前只有两列：
  pc,address

QMAP 训练需要更复杂的样本：
  1. 最近 history_length 次访存序列：physical_address / pc / rw
  2. 一次 DRAM miss 时，从 LRU 尾部采样 64 个候选页
  3. 每个候选页的 21 维页面状态特征
  4. 每个候选页的 4 个 oracle 代价标签

这个脚本使用轻量模拟逻辑把简单 trace 转换成 QMAP 的 JSONL 格式。
"""

import argparse
import collections
import csv
import json

ABLATION_CHOICES = (
    "full", "cross_attention", "no_pc", "no_rw", "mean_pool",
    "no_qformer", "no_cost")


def parse_int(value):
  """Parses hex strings such as 0x10 and decimal strings."""
  return int(value.strip(), 0)


def parse_rw(value):
  """Parses a real RW column from trace.

  Supported values:
    read: 0, r, read, load, l
    write: 1, w, write, store, s
  """
  normalized = value.strip().lower()
  if normalized in ("0", "r", "read", "load", "l"):
    return 0
  if normalized in ("1", "w", "write", "store", "s"):
    return 1
  raise ValueError("Unsupported RW value: {}".format(value))


def is_header_row(row):
  """Returns True if a CSV row looks like a column header."""
  normalized = {column.strip().lower() for column in row}
  header_names = {"pc", "address", "addr", "rw"}
  return bool(normalized & header_names)


def parse_header(row):
  """Parses CSV header indices for PC, Address, and optional RW."""
  normalized = [column.strip().lower() for column in row]
  pc_index = None
  address_index = None
  rw_index = None

  for index, column in enumerate(normalized):
    if column == "pc":
      pc_index = index
    elif column in ("address", "addr"):
      address_index = index
    elif column == "rw":
      rw_index = index

  missing = []
  if pc_index is None:
    missing.append("PC")
  if address_index is None:
    missing.append("Address")
  if missing:
    raise ValueError("CSV header is missing required column(s): {}."
                     .format(", ".join(missing)))

  return pc_index, address_index, rw_index


def warn_missing_rw_once(state):
  """Prints fallback RW warning once."""
  if not state["warned"]:
    print("[Warning] RW column not found in trace. "
          "Using simulated rw = page & 1 as fallback.")
    state["warned"] = True


def read_trace(csv_path, page_shift):
  """Reads a PC/address trace with optional RW column.

  Args:
    csv_path (str): 输入 CSV 路径，每行格式为 pc,address 或 pc,address,rw。
    page_shift (int): 地址右移位数。真实系统中可设为 12 得到 4KB 页号；
      当前 example_memtrace.csv 的地址已经很小，默认使用 0。

  Returns:
    tuple[list[dict], str]: trace 每条记录包含 pc、address、page、rw；
      rw_source 描述 RW 字段来源。
  """
  trace = []
  rw_source = None
  header_indices = None
  warning_state = {"warned": False}
  with open(csv_path, "r") as f:
    reader = csv.reader(f)
    for row_number, row in enumerate(reader, start=1):
      if not row:
        continue

      if row_number == 1 and is_header_row(row):
        header_indices = parse_header(row)
        if header_indices[2] is None:
          rw_source = "fallback simulated rw = page & 1"
          warn_missing_rw_once(warning_state)
        else:
          rw_source = "real trace RW column"
        continue

      if header_indices is not None:
        pc_index, address_index, rw_index = header_indices
        required_index = max(pc_index, address_index)
        if rw_index is not None:
          required_index = max(required_index, rw_index)
        if len(row) <= required_index:
          raise ValueError("Line {} does not contain all required header "
                           "columns.".format(row_number))
        pc = parse_int(row[pc_index])
        address = parse_int(row[address_index])
      else:
        if len(row) not in (2, 3):
          raise ValueError("Line {} must have 2 or 3 columns: "
                           "pc,address[,rw].".format(row_number))
        if rw_source is None:
          if len(row) == 2:
            rw_source = "fallback simulated rw = page & 1"
            warn_missing_rw_once(warning_state)
          else:
            rw_source = "real trace RW column"
        elif len(row) == 3 and rw_source != "real trace RW column":
          raise ValueError("Line {} has RW column but earlier rows do not."
                           .format(row_number))
        elif len(row) == 2 and rw_source == "real trace RW column":
          raise ValueError(
              "Line {} is missing RW column but earlier rows have it."
              .format(row_number))

        pc = parse_int(row[0])
        address = parse_int(row[1])

      page = address >> page_shift

      if header_indices is not None and header_indices[2] is not None:
        rw = parse_rw(row[header_indices[2]])
      elif header_indices is None and rw_source == "real trace RW column":
        rw = parse_rw(row[2])
      else:
        # 原始 CSV 没有读写标志。这里用地址最低位稳定模拟 RW：
        # 0 表示读，1 表示写。真实 trace 有 RW 字段后应替换为真实值。
        rw = page & 1
      trace.append({
          "pc": pc,
          "address": address,
          "page": page,
          "rw": rw,
      })
  return trace, rw_source or "fallback simulated rw = page & 1"


def padded_history(history, history_length):
  """Converts recent accesses to fixed-length model input sequences.

  QMAP 第一阶段需要长度固定的 [physical_address, pc, rw] 序列。
  当 trace 开头不足 history_length 条时，在左侧补 0。
  """
  padding = history_length - len(history)
  physical_address = [0] * padding + [item["page"] for item in history]
  pc = [0] * padding + [item["pc"] for item in history]
  rw = [0] * padding + [item["rw"] for item in history]
  return physical_address, pc, rw


def apply_history_ablation(physical_address, pc, rw, ablation):
  """Removes ablated access-sequence signals while preserving tensor shapes."""
  if ablation == "no_pc":
    pc = [0] * len(pc)
  elif ablation == "no_rw":
    rw = [0] * len(rw)
  return physical_address, pc, rw


def pseudo_random_0_1(value, salt=0):
  """Returns a deterministic pseudo-random value in [0, 1).

  这里用于在没有真实写入敏感性统计时，为候选页构造稳定的模拟标签。
  """
  mixed = (value * 1103515245 + 12345 + salt * 2654435761) & 0xFFFFFFFF
  return (mixed % 10000) / 10000.0


def future_stats(trace, start_index, candidate, lookahead):
  """Computes future reuse information for one candidate page.

  Args:
    trace (list[dict]): 完整访存 trace。
    start_index (int): 当前访问位置，向后看从 start_index + 1 开始。
    candidate (int): 候选页地址。
    lookahead (int): 最多向后看的记录数。

  Returns:
    tuple[int | None, int]: 下一次访问距离，以及未来窗口内访问频次。
  """
  next_distance = None
  frequency = 0
  write_frequency = 0
  end = min(len(trace), start_index + 1 + lookahead)
  for future_index in range(start_index + 1, end):
    if trace[future_index]["page"] == candidate:
      frequency += 1
      write_frequency += trace[future_index]["rw"]
      if next_distance is None:
        next_distance = future_index - start_index
  return next_distance, frequency, write_frequency


def build_candidate_state_features(candidate, history, residency_duration,
                                   is_dirty, residency_scale, rank=None,
                                   candidate_count=None):
  """Builds the page-state features described by QMAP.

  The page identifier itself is embedded by the model. This helper only
  constructs the lightweight state vector:
    0. recent access frequency in the current history window
    1. dirty/write-touched state
    2. normalized residency duration in DRAM
    3. optional normalized LRU-tail rank, where 0 is the oldest candidate
  """
  recent_frequency = sum(1 for item in history if item["page"] == candidate)
  recent_frequency = recent_frequency / max(1, len(history))
  normalized_residency = min(
      residency_duration / float(max(1, residency_scale)), 1.0)
  features = [
      recent_frequency,
      1.0 if is_dirty else 0.0,
      normalized_residency,
  ]
  if rank is not None:
    denominator = max(1, (candidate_count or 1) - 1)
    features.append(rank / float(denominator))
  return features


def build_candidate_features(candidate, rank, history, max_page):
  """Builds a 21-dimensional page feature vector.

  这些特征只来自当前可观测状态，不使用未来 oracle 标签：
    0.  页面地址归一化
    1.  地址是否大于 0x20，模拟所在介质/区域
    2.  LRU 候选排名归一化，0 最老，1 较新
    3.  最近 history 中该页出现频率
    4.  地址位模拟 dirty / write-prone 状态
    5.  候选页是否为 padding 页
    6-20. 页面地址低 15 位，作为轻量离散状态特征

  Args:
    candidate (int): 候选页地址。
    rank (int): 在 64 个候选页中的位置，0 表示最老的 LRU 页。
    history (collections.deque): 最近访问历史。
    max_page (int): trace 中最大页地址，用于归一化。

  Returns:
    list[float]: 长度固定为 21。
  """
  is_padding = 1.0 if candidate == 0 else 0.0
  recent_frequency = sum(1 for item in history if item["page"] == candidate)
  recent_frequency = recent_frequency / max(1, len(history))
  low_bits = [float((candidate >> bit) & 1) for bit in range(15)]

  features = [
      candidate / max(1, max_page),
      1.0 if candidate > 0x20 else 0.0,
      rank / 63.0,
      recent_frequency,
      float((candidate >> 1) & 1),
      is_padding,
  ] + low_bits

  if len(features) != 21:
    raise AssertionError("Candidate feature dimension must be 21.")
  return features


def build_labels(trace, current_index, candidate, lookahead):
  """Builds four oracle labels for one candidate page.

  inactivity:
    未来多久才会再次访问。越久越适合迁出，因此归一化到 [0, 1]，
    未来窗口内不再访问时取 1.0。

  coldness:
    基于未来 500 条记录中的访问频率得到。频率越低越冷，因此这里使用
    1 - normalized_frequency，让 coldness 越大表示越冷。

  write_sensitivity:
    原始 CSV 没有 RW 和写放大信息，因此使用地址生成稳定伪随机值。
    该值越高表示越不适合迁移/写入 NVM。

  migration_cost:
    按需求使用地址阈值模拟：地址大于 0x20 的页视为 NVM 区域，代价为 1；
    否则代价为 0。
  """
  next_distance, frequency, write_frequency = future_stats(
      trace, current_index, candidate, lookahead)

  if next_distance is None:
    inactivity = 1.0
  else:
    inactivity = min(next_distance, lookahead) / float(lookahead)

  coldness = 1.0 - min(frequency / float(lookahead), 1.0)
  write_sensitivity = min(write_frequency / float(lookahead), 1.0)
  migration_cost = 1.0 if candidate > 0x20 else 0.0
  return inactivity, coldness, write_sensitivity, migration_cost


def update_lru_cache(dram_cache, page, dram_capacity):
  """Updates a Python list used as an LRU DRAM cache.

  dram_cache 的约定：
    index 0 是 MRU，最近使用；
    list 尾部是 LRU，最久未使用。
  """
  if page in dram_cache:
    dram_cache.remove(page)
    dram_cache.insert(0, page)
    return True

  if len(dram_cache) >= dram_capacity:
    dram_cache.pop()
  dram_cache.insert(0, page)
  return False


def update_dram_metadata(page, is_hit, rw, index, dram_insert_time,
                         dirty_pages):
  """Updates per-page state used by QMAP candidate features."""
  if not is_hit:
    dram_insert_time[page] = index
  if rw:
    dirty_pages.add(page)


def get_lru_tail_candidates(dram_cache, candidate_count):
  """Returns exactly candidate_count pages from the LRU tail.

  真实系统应当在 DRAM 中已有足够页面后直接截取 64 个候选页。
  为了让小型 example_memtrace.csv 也能生成格式正确的样本，这里在候选不足
  64 个时使用 0 padding。真实训练数据建议在 DRAM warmup 后生成样本。
  """
  candidates = list(reversed(dram_cache[-candidate_count:]))
  if len(candidates) < candidate_count:
    candidates += [0] * (candidate_count - len(candidates))
  return candidates


def get_lru_tail_candidates_and_mask(dram_cache, candidate_count):
  """Returns LRU-tail candidates and a mask that excludes padding entries."""
  real_candidates = list(reversed(dram_cache[-candidate_count:]))
  mask = [1] * len(real_candidates)
  if len(real_candidates) < candidate_count:
    padding_count = candidate_count - len(real_candidates)
    real_candidates += [0] * padding_count
    mask += [0] * padding_count
  return real_candidates, mask


def generate_qmap_samples(args):
  trace, rw_source = read_trace(args.input, args.page_shift)
  max_page = max((item["page"] for item in trace), default=1)
  read_accesses = sum(1 for item in trace if item["rw"] == 0)
  write_accesses = sum(1 for item in trace if item["rw"] == 1)

  history = collections.deque(maxlen=args.history_length)
  dram_cache = []
  dram_insert_time = {}
  dirty_pages = set()
  num_samples = 0

  with open(args.output, "w") as output_file:
    for index, access in enumerate(trace):
      # 先更新 history，让当前访问也进入模型看到的最近 10 次访存序列。
      history.append(access)

      is_hit = access["page"] in dram_cache
      if not is_hit and len(dram_cache) >= args.dram_capacity:
        physical_address, pc, rw = apply_history_ablation(
            *padded_history(history, args.history_length),
            ablation=args.ablation)
        candidates, candidate_mask = get_lru_tail_candidates_and_mask(
            dram_cache, args.candidate_count)

        candidates_features = []
        candidate_state_features = []
        inactivity = []
        coldness = []
        write_sensitivity = []
        migration_cost = []

        for rank, candidate in enumerate(candidates):
          residency_duration = index - dram_insert_time.get(candidate, index)
          is_dirty = candidate in dirty_pages
          candidate_state_features.append(build_candidate_state_features(
              candidate, history, residency_duration, is_dirty,
              args.lookahead, rank=rank,
              candidate_count=args.candidate_count))
          candidates_features.append(build_candidate_features(
              candidate, rank, history, max_page))
          labels = build_labels(trace, index, candidate, args.lookahead)
          inactivity.append(labels[0])
          coldness.append(labels[1])
          write_sensitivity.append(labels[2])
          migration_cost.append(labels[3])

        sample = {
            "physical_address": physical_address,
            "pc": pc,
            "rw": rw,
            "candidate_pages": candidates,
            "candidate_state_features": candidate_state_features,
            "candidate_mask": candidate_mask,
            "candidates_features": candidates_features,
            "inactivity": inactivity,
            "coldness": coldness,
            "write_sensitivity": write_sensitivity,
            "migration_cost": migration_cost,
        }
        output_file.write(json.dumps(sample) + "\n")
        num_samples += 1

      is_hit_after_update = update_lru_cache(
          dram_cache, access["page"], args.dram_capacity)
      if len(dram_cache) > args.dram_capacity:
        raise AssertionError("DRAM cache exceeded configured capacity.")
      current_pages = set(dram_cache)
      for tracked_page in list(dram_insert_time):
        if tracked_page not in current_pages:
          dram_insert_time.pop(tracked_page, None)
          dirty_pages.discard(tracked_page)
      update_dram_metadata(
          access["page"], is_hit_after_update, access["rw"], index,
          dram_insert_time, dirty_pages)

  print("RW source: {}".format(rw_source))
  print("Read accesses: {}".format(read_accesses))
  print("Write accesses: {}".format(write_accesses))
  print("Total trace records: {}".format(len(trace)))
  print("Generated samples: {}".format(num_samples))
  print("Wrote:", args.output)


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Generate QMAP training JSONL.")
  parser.add_argument("--input", default="environment/example_memtrace.csv",
                      help=("Input CSV trace with PC,Address and optional RW "
                            "column."))
  parser.add_argument("--output", default="train_data.jsonl",
                      help="Output QMAP JSONL training file.")
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--lookahead", type=int, default=500)
  parser.add_argument("--dram_capacity", type=int, default=128,
                      help="Number of pages in the simulated DRAM LRU cache.")
  parser.add_argument("--page_shift", type=int, default=0,
                      help="Right shift raw addresses to page addresses.")
  parser.add_argument("--ablation", choices=ABLATION_CHOICES,
                      default="cross_attention",
                      help="QMAP ablation variant for generated samples.")
  return parser


if __name__ == "__main__":
  generate_qmap_samples(build_arg_parser().parse_args())
