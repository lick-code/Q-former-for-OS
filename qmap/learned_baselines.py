# coding=utf-8
"""Lightweight learned page-replacement baselines for trace replay.

These are paper-aligned, trace-replay versions of two learned hybrid-memory
scheduler ideas:

  - Kleio-lite predicts per-page future hotness from recent history features.
  - PatternS-lite groups pages by access pattern, then predicts hotness with a
    group-specific model.

The implementation is deliberately dependency-free so it can run anywhere the
existing replay scripts run.  It is not a full reproduction of the original
systems; it is a comparable baseline under the repository's replay cost model.
"""

import argparse
import json
import math
import os
import random
import sys


try:
  from qmap_generator import get_lru_tail_candidates_and_mask
  from qmap_generator import read_trace
except ImportError:
  from qmap.qmap_generator import get_lru_tail_candidates_and_mask
  from qmap.qmap_generator import read_trace


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
KLEIO_LITE = "kleio_lite"
PATTERNS_LITE = "patterns_lite"
POLICY_CHOICES = (KLEIO_LITE, PATTERNS_LITE)

FEATURE_NAMES = (
    "bias",
    "rank_norm",
    "recency_norm",
    "residency_norm",
    "frequency_norm",
    "recent_count_norm",
    "recent_write_norm",
    "dirty",
)

PAGE_PATTERN_FEATURE_NAMES = (
    "access_count_norm",
    "write_ratio",
    "mean_gap_norm",
    "gap_cv_norm",
    "first_access_norm",
    "last_access_norm",
)


def safe_divide(numerator, denominator):
  if denominator == 0:
    return 0.0
  return numerator / float(denominator)


def clamp(value, lower=0.0, upper=1.0):
  return max(lower, min(upper, value))


def dot(weights, features):
  return sum(weight * feature for weight, feature in zip(weights, features))


def load_model(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def save_model(model_dict, path):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(model_dict, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def recent_page_counts(history, page):
  count = 0
  writes = 0
  for access in history:
    if access["page"] == page:
      count += 1
      writes += access["rw"]
  return count, writes


def candidate_feature_values(feature_names, page, rank, candidate_count,
                             history, access_index, dram_insert_time,
                             dirty_pages, access_frequency, last_access_time,
                             history_length, lookahead):
  recent_count, recent_writes = recent_page_counts(history, page)
  if page in last_access_time:
    recency = access_index - last_access_time[page]
  else:
    recency = lookahead
  residency = access_index - dram_insert_time.get(page, access_index)
  rank_norm = safe_divide(rank, candidate_count - 1)
  values = {
      "bias": 1.0,
      "rank_norm": clamp(rank_norm),
      "recency_norm": clamp(safe_divide(recency, lookahead)),
      "residency_norm": clamp(safe_divide(residency, lookahead)),
      "frequency_norm": clamp(safe_divide(
          access_frequency.get(page, 0), lookahead)),
      "recent_count_norm": clamp(safe_divide(recent_count, history_length)),
      "recent_write_norm": clamp(safe_divide(recent_writes, history_length)),
      "dirty": 1.0 if page in dirty_pages else 0.0,
  }
  return [values[name] for name in feature_names]


def future_hotness(trace, start_index, page, label_lookahead):
  score = 0.0
  end_index = min(len(trace), start_index + label_lookahead + 1)
  for index in range(start_index + 1, end_index):
    access = trace[index]
    if access["page"] == page:
      score += 1.0 + 0.5 * access["rw"]
  return clamp(score / float(max(1, label_lookahead)))


def replay_lru_collect_samples(trace, args, page_to_cluster=None,
                               cluster_count=None):
  dram_pages = []
  dram_insert_time = {}
  dirty_pages = set()
  access_frequency = {}
  last_access_time = {}
  history = []
  samples = []
  cluster_samples = [[] for _ in range(cluster_count or 0)]

  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = access["rw"]
    access_frequency[page] = access_frequency.get(page, 0) + 1
    last_access_time[page] = access_index

    if page in dram_pages:
      dram_pages.remove(page)
      dram_pages.insert(0, page)
      if rw:
        dirty_pages.add(page)
    else:
      if len(dram_pages) >= args.dram_capacity:
        candidates, candidate_mask = get_lru_tail_candidates_and_mask(
            dram_pages, args.candidate_count)
        decision_history = (history + [access])[-args.history_length:]
        for rank, candidate in enumerate(candidates):
          if not candidate_mask[rank]:
            continue
          features = candidate_feature_values(
              FEATURE_NAMES, candidate, rank, args.candidate_count,
              decision_history, access_index, dram_insert_time, dirty_pages,
              access_frequency, last_access_time, args.history_length,
              args.lookahead)
          label = future_hotness(
              trace, access_index, candidate, args.label_lookahead)
          if page_to_cluster is None:
            samples.append((features, label))
          else:
            cluster = page_to_cluster.get(candidate, 0)
            cluster_samples[cluster].append((features, label))

        victim = dram_pages[-1]
        dram_pages.remove(victim)
        dram_insert_time.pop(victim, None)
        dirty_pages.discard(victim)

      dram_pages.insert(0, page)
      dram_insert_time[page] = access_index
      if rw:
        dirty_pages.add(page)

    history.append(access)
    if len(history) > args.history_length:
      history.pop(0)

  return cluster_samples if page_to_cluster is not None else samples


def train_linear_model(samples, feature_count, epochs, learning_rate, l2,
                       seed):
  weights = [0.0] * feature_count
  if not samples:
    return weights
  rng = random.Random(seed)
  samples = list(samples)
  for _ in range(epochs):
    rng.shuffle(samples)
    for features, label in samples:
      error = dot(weights, features) - label
      for index, value in enumerate(features):
        weights[index] -= learning_rate * (
            error * value + l2 * weights[index])
  return weights


def page_pattern_stats(trace):
  stats = {}
  for index, access in enumerate(trace):
    page = access["page"]
    item = stats.setdefault(page, {
        "count": 0,
        "writes": 0,
        "first": index,
        "last": index,
        "positions": [],
    })
    item["count"] += 1
    item["writes"] += access["rw"]
    item["last"] = index
    item["positions"].append(index)
  return stats


def page_pattern_vector(item, trace_length):
  positions = item["positions"]
  gaps = [
      positions[index] - positions[index - 1]
      for index in range(1, len(positions))
  ]
  mean_gap = safe_divide(sum(gaps), len(gaps)) if gaps else trace_length
  variance = safe_divide(
      sum((gap - mean_gap) ** 2 for gap in gaps), len(gaps)) if gaps else 0.0
  std_gap = math.sqrt(variance)
  count_norm = safe_divide(
      math.log1p(item["count"]), math.log1p(max(1, trace_length)))
  return [
      clamp(count_norm),
      clamp(safe_divide(item["writes"], item["count"])),
      clamp(safe_divide(mean_gap, trace_length)),
      clamp(safe_divide(safe_divide(std_gap, mean_gap), 5.0)),
      clamp(safe_divide(item["first"], trace_length)),
      clamp(safe_divide(item["last"], trace_length)),
  ]


def squared_distance(left, right):
  return sum((a - b) ** 2 for a, b in zip(left, right))


def nearest_centroid(vector, centroids):
  return min(
      range(len(centroids)),
      key=lambda index: squared_distance(vector, centroids[index]))


def kmeans(vectors_by_page, cluster_count, iterations, seed):
  if not vectors_by_page:
    return [], {}
  pages = sorted(vectors_by_page)
  cluster_count = min(cluster_count, len(pages))
  rng = random.Random(seed)
  shuffled = list(pages)
  rng.shuffle(shuffled)
  centroids = [vectors_by_page[page] for page in shuffled[:cluster_count]]
  assignments = {page: 0 for page in pages}

  for _ in range(iterations):
    changed = False
    for page in pages:
      cluster = nearest_centroid(vectors_by_page[page], centroids)
      if assignments.get(page) != cluster:
        changed = True
      assignments[page] = cluster
    if not changed:
      break
    sums = [[0.0] * len(centroids[0]) for _ in range(cluster_count)]
    counts = [0] * cluster_count
    for page in pages:
      cluster = assignments[page]
      counts[cluster] += 1
      for index, value in enumerate(vectors_by_page[page]):
        sums[cluster][index] += value
    for cluster in range(cluster_count):
      if counts[cluster] == 0:
        continue
      centroids[cluster] = [
          value / float(counts[cluster])
          for value in sums[cluster]
      ]
  return centroids, assignments


def build_pattern_clusters(trace, args):
  stats = page_pattern_stats(trace)
  trace_length = max(1, len(trace))
  vectors_by_page = {
      page: page_pattern_vector(item, trace_length)
      for page, item in stats.items()
  }
  centroids, assignments = kmeans(
      vectors_by_page, args.cluster_count, args.cluster_iterations,
      args.seed)
  return {
      "centroids": centroids,
      "page_to_cluster": {str(page): cluster
                          for page, cluster in assignments.items()},
      "default_cluster": 0,
      "feature_names": list(PAGE_PATTERN_FEATURE_NAMES),
  }


def train_kleio_lite(trace, args):
  samples = replay_lru_collect_samples(trace, args)
  weights = train_linear_model(
      samples, len(FEATURE_NAMES), args.model_epochs, args.learning_rate,
      args.l2, args.seed)
  return {
      "policy": KLEIO_LITE,
      "feature_names": list(FEATURE_NAMES),
      "weights": weights,
      "candidate_count": args.candidate_count,
      "history_length": args.history_length,
      "lookahead": args.lookahead,
      "label_lookahead": args.label_lookahead,
      "training": {
          "sample_count": len(samples),
          "train_trace": args.train_trace,
          "dram_capacity": args.dram_capacity,
      },
  }


def train_patterns_lite(trace, args):
  clusters = build_pattern_clusters(trace, args)
  page_to_cluster = {
      int(page): cluster
      for page, cluster in clusters["page_to_cluster"].items()
  }
  cluster_count = max(1, len(clusters["centroids"]))
  cluster_samples = replay_lru_collect_samples(
      trace, args, page_to_cluster=page_to_cluster,
      cluster_count=cluster_count)
  cluster_weights = []
  for cluster, samples in enumerate(cluster_samples):
    cluster_weights.append(train_linear_model(
        samples, len(FEATURE_NAMES), args.model_epochs, args.learning_rate,
        args.l2, args.seed + cluster))
  return {
      "policy": PATTERNS_LITE,
      "feature_names": list(FEATURE_NAMES),
      "cluster_weights": cluster_weights,
      "clusters": clusters,
      "candidate_count": args.candidate_count,
      "history_length": args.history_length,
      "lookahead": args.lookahead,
      "label_lookahead": args.label_lookahead,
      "training": {
          "sample_count": sum(len(samples) for samples in cluster_samples),
          "cluster_sample_counts": [len(samples)
                                    for samples in cluster_samples],
          "train_trace": args.train_trace,
          "dram_capacity": args.dram_capacity,
      },
  }


class LearnedBaselinePolicy(object):
  """Runtime predictor loaded by qmap_eval.py."""

  def __init__(self, model_dict):
    self._model = model_dict
    self._policy = model_dict["policy"]
    if self._policy not in POLICY_CHOICES:
      raise ValueError("Unsupported learned policy: {}".format(self._policy))
    self._feature_names = model_dict.get("feature_names", list(FEATURE_NAMES))
    self._candidate_count = int(model_dict.get("candidate_count", 8))
    self._history_length = int(model_dict.get("history_length", 10))
    self._lookahead = int(model_dict.get("lookahead", 256))
    self._weights = model_dict.get("weights", [])
    self._cluster_weights = model_dict.get("cluster_weights", [])
    clusters = model_dict.get("clusters", {})
    self._centroids = clusters.get("centroids", [])
    self._page_to_cluster = {
        int(page): cluster
        for page, cluster in clusters.get("page_to_cluster", {}).items()
    }
    self._default_cluster = int(clusters.get("default_cluster", 0))

  def _cluster_for_page(self, page, access_frequency, last_access_time,
                        access_index, dirty_pages):
    if page in self._page_to_cluster:
      return self._page_to_cluster[page]
    if not self._centroids:
      return self._default_cluster
    count = access_frequency.get(page, 0)
    last_seen = last_access_time.get(page, access_index)
    vector = [
        clamp(safe_divide(math.log1p(count), math.log1p(
            max(1, access_index + 1)))),
        1.0 if page in dirty_pages else 0.0,
        clamp(safe_divide(access_index - last_seen, max(1, access_index + 1))),
        0.0,
        0.0,
        clamp(safe_divide(last_seen, max(1, access_index + 1))),
    ]
    return nearest_centroid(vector, self._centroids)

  def _weights_for_page(self, page, access_frequency, last_access_time,
                        access_index, dirty_pages):
    if self._policy == KLEIO_LITE:
      return self._weights
    cluster = self._cluster_for_page(
        page, access_frequency, last_access_time, access_index, dirty_pages)
    if not self._cluster_weights:
      return [0.0] * len(self._feature_names)
    cluster = max(0, min(cluster, len(self._cluster_weights) - 1))
    return self._cluster_weights[cluster]

  def choose_victim(self, dram_pages, history, access_index,
                    dram_insert_time, dirty_pages, access_frequency,
                    last_access_time):
    candidates, candidate_mask = get_lru_tail_candidates_and_mask(
        dram_pages, self._candidate_count)
    scored_candidates = []
    for rank, candidate in enumerate(candidates):
      if not candidate_mask[rank]:
        continue
      features = candidate_feature_values(
          self._feature_names, candidate, rank, self._candidate_count,
          history, access_index, dram_insert_time, dirty_pages,
          access_frequency, last_access_time, self._history_length,
          self._lookahead)
      weights = self._weights_for_page(
          candidate, access_frequency, last_access_time, access_index,
          dirty_pages)
      score = dot(weights, features)
      scored_candidates.append((score, rank, candidate))
    if not scored_candidates:
      raise ValueError("LearnedBaselinePolicy cannot choose from empty DRAM.")
    return min(scored_candidates, key=lambda item: (item[0], item[1]))[2]


def train_model(args):
  trace, _ = read_trace(args.train_trace, args.page_shift)
  if args.policy == KLEIO_LITE:
    return train_kleio_lite(trace, args)
  if args.policy == PATTERNS_LITE:
    return train_patterns_lite(trace, args)
  raise ValueError("Unsupported policy: {}".format(args.policy))


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Train lightweight learned replacement baselines.")
  parser.add_argument("--policy", choices=POLICY_CHOICES, required=True)
  parser.add_argument("--config", default=None,
                      help="Resolved CAPD finals_v2.1 config.")
  parser.add_argument("--train_trace", default=None)
  parser.add_argument("--model_output", required=True)
  parser.add_argument("--dram_capacity", type=int, default=16)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=8)
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--label_lookahead", type=int, default=256)
  parser.add_argument("--model_epochs", type=int, default=5)
  parser.add_argument("--learning_rate", type=float, default=0.05)
  parser.add_argument("--l2", type=float, default=1e-4)
  parser.add_argument("--cluster_count", type=int, default=8)
  parser.add_argument("--cluster_iterations", type=int, default=20)
  parser.add_argument("--seed", type=int, default=3136859)
  return parser


def apply_finals_config(args):
  if not args.config:
    return None
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT)
  args.train_trace = config["data"]["train_trace"]
  args.dram_capacity = int(config["memory"]["dram_capacity_pages"])
  args.page_shift = int(config.get("trace", {}).get("page_shift", 12))
  args.history_length = int(config["history"]["transformer_H"])
  # Native learned baselines remain restricted to their original LRU-tail 8.
  args.candidate_count = 8
  args.lookahead = int(config["features"]["residency_scale_Lres"])
  args.label_lookahead = int(config["labels"]["future_lookahead_L"])
  args.seed = int(config["training"]["seed"])
  return config


def validate_args(args):
  if not args.train_trace:
    raise ValueError("--train_trace is required when --config is omitted.")
  if args.dram_capacity <= 0:
    raise ValueError("--dram_capacity must be positive.")
  if args.candidate_count <= 0:
    raise ValueError("--candidate_count must be positive.")
  if args.history_length <= 0:
    raise ValueError("--history_length must be positive.")
  if args.lookahead <= 0:
    raise ValueError("--lookahead must be positive.")
  if args.label_lookahead <= 0:
    raise ValueError("--label_lookahead must be positive.")
  if args.model_epochs <= 0:
    raise ValueError("--model_epochs must be positive.")
  if args.cluster_count <= 0:
    raise ValueError("--cluster_count must be positive.")


def main():
  args = build_arg_parser().parse_args()
  config = apply_finals_config(args)
  validate_args(args)
  model_dict = train_model(args)
  if config is not None:
    model_dict.update({
        "schema_version": config["schema_version"],
        "workload": config["run"]["workload"],
        "config_fingerprint": finals_config.config_fingerprint(config),
        "experiment_contract": finals_config.contract_from_config(config),
    })
    if config["schema_version"] == finals_config.SCHEMA_VERSION:
      model_dict.update(finals_config.artifact_identity_from_config(config))
  save_model(model_dict, args.model_output)
  print("[done] policy={} samples={} model={}".format(
      args.policy,
      model_dict.get("training", {}).get("sample_count", 0),
      args.model_output))


if __name__ == "__main__":
  main()
