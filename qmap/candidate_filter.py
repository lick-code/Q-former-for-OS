# coding=utf-8
"""Lightweight B-to-K candidate selector shared by CAPD finals pipelines."""

from __future__ import print_function

import collections
import time


WEIGHT_KEYS = ("w_Delta", "w_A", "w_W", "w_C", "w_R")


class SelectorHistory(object):
  """O(1)-amortized Hc-window counts excluding the not-yet-observed request."""

  def __init__(self, history_length):
    if history_length <= 0:
      raise ValueError("history_length must be positive.")
    self.history_length = int(history_length)
    self._entries = collections.deque()
    self._access_counts = {}
    self._write_counts = {}
    self._last_access_index = {}

  def observe(self, page, rw, access_index):
    if len(self._entries) >= self.history_length:
      old_page, old_rw, _ = self._entries.popleft()
      self._decrement(self._access_counts, old_page, 1)
      if old_rw:
        self._decrement(self._write_counts, old_page, 1)
    rw = int(bool(rw))
    self._entries.append((page, rw, access_index))
    self._access_counts[page] = self._access_counts.get(page, 0) + 1
    if rw:
      self._write_counts[page] = self._write_counts.get(page, 0) + 1
    self._last_access_index[page] = access_index

  @staticmethod
  def _decrement(mapping, key, amount):
    value = mapping.get(key, 0) - amount
    if value <= 0:
      mapping.pop(key, None)
    else:
      mapping[key] = value

  def access_count(self, page):
    return self._access_counts.get(page, 0)

  def write_count(self, page):
    return self._write_counts.get(page, 0)

  def last_access_index(self, page, default=None):
    return self._last_access_index.get(page, default)

  def __len__(self):
    return len(self._entries)


def build_candidate_pool(dram_pages, pool_size_B):
  """Returns P_t in oldest-to-newest LRU order, without padding."""
  if pool_size_B <= 0:
    raise ValueError("pool_size_B must be positive.")
  pool_size = min(int(pool_size_B), len(dram_pages))
  return list(reversed(dram_pages[-pool_size:]))


def lru_preference(original_pool_rank, pool_size):
  """Returns frozen CAPD R_LRU using the original, unfiltered B_t rank."""
  if original_pool_rank < 0 or original_pool_rank >= pool_size:
    raise ValueError(
        "original_pool_rank must be in [0, pool_size).")
  denominator = max(int(pool_size) - 1, 1)
  return 1.0 - int(original_pool_rank) / float(denominator)


def raw_selector_values(page, original_pool_rank, pool_size, access_index,
                        selector_history, dirty_pages):
  last_access = selector_history.last_access_index(page, access_index)
  delta = max(0, access_index - last_access)
  access_count = selector_history.access_count(page)
  write_count = selector_history.write_count(page)
  clean = 0.0 if page in dirty_pages else 1.0
  lru_value = lru_preference(original_pool_rank, pool_size)
  return {
      "Delta": float(delta),
      "A": float(access_count),
      "W": float(write_count),
      "C": clean,
      "R_LRU": lru_value,
  }


def clipped_scale(value, clip_value):
  clip_value = max(float(clip_value), 1.0)
  return min(float(value), clip_value) / clip_value


def selector_features(raw_values, selector_params):
  return [
      clipped_scale(raw_values["Delta"], selector_params["c_Delta"]),
      1.0 - clipped_scale(raw_values["A"], selector_params["c_A"]),
      1.0 - clipped_scale(raw_values["W"], selector_params["c_W"]),
      float(raw_values["C"]),
      float(raw_values["R_LRU"]),
  ]


def selector_weights(selector_params):
  weights = [float(selector_params[key]) for key in WEIGHT_KEYS]
  if any(weight < 0.0 for weight in weights):
    raise ValueError("Selector weights must be non-negative.")
  if abs(sum(weights) - 1.0) > 1e-8:
    raise ValueError("Selector weights must sum to one.")
  return weights


def dot(left, right):
  return sum(a * b for a, b in zip(left, right))


def build_pool_records(dram_pages, pool_size_B, access_index,
                       selector_history, dirty_pages, selector_params):
  pool = build_candidate_pool(dram_pages, pool_size_B)
  weights = selector_weights(selector_params)
  records = []
  for rank, page in enumerate(pool):
    raw_values = raw_selector_values(
        page, rank, len(pool), access_index, selector_history, dirty_pages)
    features = selector_features(raw_values, selector_params)
    records.append({
        "page": page,
        "original_pool_rank": rank,
        "raw_values": raw_values,
        "selector_features": features,
        "selector_score": dot(weights, features),
    })
  return records


def select_from_pool_records(pool_records, retained_K):
  if retained_K <= 0:
    raise ValueError("retained_K must be positive.")
  # score descending, older original LRU rank first, then page id ascending.
  ordered = sorted(
      pool_records,
      key=lambda item: (
          -item["selector_score"], item["original_pool_rank"], item["page"]))
  return ordered[:min(int(retained_K), len(ordered))]


def select_candidates(dram_pages, pool_size_B, retained_K, access_index,
                      selector_history, dirty_pages, selector_params):
  start = time.perf_counter()
  pool_records = build_pool_records(
      dram_pages, pool_size_B, access_index, selector_history, dirty_pages,
      selector_params)
  selected = select_from_pool_records(pool_records, retained_K)
  return {
      "P_t": [item["page"] for item in pool_records],
      "B_t": len(pool_records),
      "K_t": len(selected),
      "pool_records": pool_records,
      "selected_records": selected,
      "selector_time_seconds": time.perf_counter() - start,
  }


def build_candidate_state_features(selected_records, transformer_history,
                                   access_index, dram_insert_time, dirty_pages,
                                   residency_scale_Lres, retained_K):
  """Builds only the four frozen reranker features; selector score is absent."""
  # Wrapper records carry B_t explicitly. The fallback keeps this helper
  # usable in focused unit tests without ever normalizing by filtered K_t.
  pool_size = max(
      [item["original_pool_rank"] + 1 for item in selected_records] or [1])
  history_length = max(1, len(transformer_history))
  pages = []
  states = []
  ranks = []
  mask = []
  for item in selected_records:
    page = item["page"]
    rank = item["original_pool_rank"]
    actual_pool_size = int(item.get("B_t", pool_size))
    recent_frequency = sum(
        1 for access in transformer_history if access["page"] == page)
    recent_frequency /= float(history_length)
    residency = access_index - dram_insert_time.get(page, access_index)
    normalized_residency = min(
        residency / float(max(1, residency_scale_Lres)), 1.0)
    normalized_rank = lru_preference(rank, actual_pool_size)
    pages.append(page)
    states.append([
        recent_frequency,
        1.0 if page in dirty_pages else 0.0,
        normalized_residency,
        normalized_rank,
    ])
    ranks.append(rank)
    mask.append(1)
  while len(pages) < retained_K:
    pages.append(0)
    states.append([0.0, 0.0, 0.0, 0.0])
    ranks.append(-1)
    mask.append(0)
  return {
      "candidate_pages": pages,
      "candidate_state_features": states,
      "candidate_mask": mask,
      "original_pool_ranks": ranks,
  }


def build_filtered_candidate_snapshot(
    dram_pages, transformer_history, access_index, dram_insert_time,
    dirty_pages, selector_history, config, selector_params):
  variant_id = config.get("stage5_variant", {}).get("variant_id")
  if variant_id == "no_filter_B8_K8":
    start = time.perf_counter()
    pool_records = build_pool_records(
        dram_pages, 8, access_index, selector_history, dirty_pages,
        selector_params)
    selection = {
        "P_t": [item["page"] for item in pool_records],
        "B_t": len(pool_records),
        "K_t": len(pool_records),
        "pool_records": pool_records,
        "selected_records": list(pool_records),
        "selector_time_seconds": time.perf_counter() - start,
        "selection_mode": "identity_P_t_equals_C_t",
    }
  else:
    selection = select_candidates(
        dram_pages,
        int(config["candidate"]["pool_size_B"]),
        int(config["candidate"]["retained_K"]),
        access_index,
        selector_history,
        dirty_pages,
        selector_params)
    selection["selection_mode"] = "selector_B_to_K"
  for item in selection["selected_records"]:
    item["B_t"] = selection["B_t"]
  reranker = build_candidate_state_features(
      selection["selected_records"], transformer_history, access_index,
      dram_insert_time, dirty_pages,
      int(config["features"]["residency_scale_Lres"]),
      int(config["candidate"]["retained_K"]))
  snapshot = dict(selection)
  snapshot.update(reranker)
  return snapshot
