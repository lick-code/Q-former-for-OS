# coding=utf-8
"""Training-only clipping statistics and fixed-sample selector grid search."""

from __future__ import print_function

import math
import json

import numpy as np


WEIGHT_NAMES = ("w_Delta", "w_A", "w_W", "w_C", "w_R")


def quantile(values, probability):
  if not values:
    return 1.0
  if probability < 0.0 or probability > 1.0:
    raise ValueError("probability must be in [0, 1].")
  ordered = sorted(float(value) for value in values)
  if len(ordered) == 1:
    return ordered[0]
  position = (len(ordered) - 1) * probability
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  if lower == upper:
    return ordered[lower]
  fraction = position - lower
  return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def clipping_values(raw_observations, clip_quantile=0.99):
  return {
      "c_Delta": max(quantile(raw_observations.get("Delta", []),
                              clip_quantile), 1.0),
      "c_A": max(quantile(raw_observations.get("A", []),
                          clip_quantile), 1.0),
      "c_W": max(quantile(raw_observations.get("W", []),
                          clip_quantile), 1.0),
  }


def integer_weight_compositions(total=10, dimensions=5):
  if total < 0 or dimensions <= 0:
    raise ValueError("Invalid composition dimensions.")

  def generate(prefix, remaining, slots):
    if slots == 1:
      yield tuple(prefix + [remaining])
      return
    for value in range(remaining + 1):
      for item in generate(prefix + [value], remaining - value, slots - 1):
        yield item

  return generate([], total, dimensions)


def weight_grid():
  return [tuple(value / 10.0 for value in composition)
          for composition in integer_weight_compositions(10, 5)]


def _sample_arrays(samples):
  if not samples:
    return None
  max_candidates = max(int(sample["B_t"]) for sample in samples)
  sample_count = len(samples)
  features = np.zeros((sample_count, max_candidates, 5), dtype=np.float64)
  relevance = np.full(
      (sample_count, max_candidates), -np.inf, dtype=np.float64)
  mask = np.zeros((sample_count, max_candidates), dtype=bool)
  oracle = np.zeros((sample_count, max_candidates), dtype=bool)
  oracle_sizes = np.zeros(sample_count, dtype=np.float64)
  ranges = np.zeros(sample_count, dtype=np.float64)
  retained = np.zeros(sample_count, dtype=np.int64)
  for sample_index, sample in enumerate(samples):
    count = int(sample["B_t"])
    current_features = np.asarray(sample["selector_features"],
                                  dtype=np.float64)
    current_relevance = np.asarray(sample["relevance"], dtype=np.float64)
    features[sample_index, :count, :] = current_features
    relevance[sample_index, :count] = current_relevance
    mask[sample_index, :count] = True
    maximum = np.max(current_relevance)
    minimum = np.min(current_relevance)
    oracle[sample_index, :count] = np.isclose(
        current_relevance, maximum, rtol=0.0, atol=1e-12)
    oracle_sizes[sample_index] = np.sum(oracle[sample_index, :count])
    ranges[sample_index] = maximum - minimum
    retained[sample_index] = min(int(sample["retained_K"]), count)
  return {
      "features": features,
      "relevance": relevance,
      "mask": mask,
      "oracle": oracle,
      "oracle_sizes": oracle_sizes,
      "ranges": ranges,
      "retained": retained,
  }


def evaluate_weight_batch(arrays, weights):
  features = arrays["features"]
  relevance = arrays["relevance"]
  mask = arrays["mask"]
  oracle = arrays["oracle"]
  oracle_sizes = arrays["oracle_sizes"]
  ranges = arrays["ranges"]
  retained = arrays["retained"]
  weights = np.asarray(weights, dtype=np.float64)
  scores = np.einsum("nbf,wf->nwb", features, weights)
  scores = np.where(mask[:, None, :], scores, -np.inf)
  # Pool entries are stored in original LRU-rank order. Stable sorting therefore
  # implements score, original rank, page-id tie breaking (ranks are unique).
  order = np.argsort(-scores, axis=2, kind="stable")
  recalls = np.zeros(weights.shape[0], dtype=np.float64)
  regrets = np.zeros(weights.shape[0], dtype=np.float64)
  for sample_index in range(features.shape[0]):
    k_value = retained[sample_index]
    selected = order[sample_index, :, :k_value]
    selected_oracle = np.take(
        oracle[sample_index], selected, axis=0)
    recalls += np.sum(selected_oracle, axis=1) / oracle_sizes[sample_index]
    selected_relevance = np.take(
        relevance[sample_index], selected, axis=0)
    best_selected = np.max(selected_relevance, axis=1)
    regrets += (
        np.max(relevance[sample_index]) - best_selected) / ranges[sample_index]
  divisor = float(features.shape[0])
  return recalls / divisor, regrets / divisor


def weight_choice_key(recall_at_k, normalized_regret, weights):
  """Frozen deterministic optimization order for one grid point."""
  uniform = np.asarray([0.2] * 5, dtype=np.float64)
  weights_array = np.asarray(weights, dtype=np.float64)
  distance = float(np.sum((weights_array - uniform) ** 2))
  return (-float(recall_at_k), float(normalized_regret), distance,
          tuple(weights))


def _uniform_fallback(total_count):
  uniform = (0.2, 0.2, 0.2, 0.2, 0.2)
  return {
      "weights": uniform,
      "Recall@K": 0.0,
      "NRegret": 0.0,
      "effective_decision_points": 0,
      "nondiscriminative_ratio": 1.0 if total_count else 0.0,
      "mean_oracle_size": 0.0,
      "unique_oracle_ratio": 0.0,
      "grid_size": 1001,
      "fallback_uniform": True,
  }


def _search_chunks(chunks, epsilon_y):
  """Evaluates all 1001 weights on bounded batches of fixed samples."""
  grid = weight_grid()
  if len(grid) != 1001:
    raise AssertionError("Expected exactly 1001 selector weights.")
  recall_totals = np.zeros(len(grid), dtype=np.float64)
  regret_totals = np.zeros(len(grid), dtype=np.float64)
  total_count = 0
  valid_count = 0
  oracle_size_sum = 0.0
  unique_oracle_count = 0
  for chunk in chunks:
    total_count += len(chunk)
    valid_samples = []
    for sample in chunk:
      relevance = sample["relevance"]
      relevance_range = max(relevance) - min(relevance)
      if relevance_range <= epsilon_y:
        continue
      valid_samples.append(sample)
      maximum = max(relevance)
      oracle_size = sum(
          1 for value in relevance
          if math.isclose(value, maximum, rel_tol=0.0, abs_tol=1e-12))
      oracle_size_sum += oracle_size
      unique_oracle_count += int(oracle_size == 1)
    if not valid_samples:
      continue
    arrays = _sample_arrays(valid_samples)
    recalls, regrets = evaluate_weight_batch(arrays, grid)
    recall_totals += recalls * len(valid_samples)
    regret_totals += regrets * len(valid_samples)
    valid_count += len(valid_samples)

  if valid_count == 0:
    return _uniform_fallback(total_count)
  recalls = recall_totals / float(valid_count)
  regrets = regret_totals / float(valid_count)
  best = None
  uniform = np.asarray([0.2] * 5, dtype=np.float64)
  for index, weights in enumerate(grid):
    distance = float(np.sum((np.asarray(weights) - uniform) ** 2))
    candidate = {
        "weights": weights,
        "Recall@K": float(recalls[index]),
        "NRegret": float(regrets[index]),
        "uniform_distance": distance,
    }
    key = weight_choice_key(
        candidate["Recall@K"], candidate["NRegret"], weights)
    if best is None or key < best[0]:
      best = (key, candidate)
  result = best[1]
  result.update({
      "effective_decision_points": valid_count,
      "nondiscriminative_ratio": (
          (total_count - valid_count) / float(total_count)
          if total_count else 0.0),
      "mean_oracle_size": oracle_size_sum / float(valid_count),
      "unique_oracle_ratio": unique_oracle_count / float(valid_count),
      "grid_size": len(grid),
      "fallback_uniform": False,
  })
  return result


def _list_chunks(samples, batch_size):
  for start in range(0, len(samples), batch_size):
    yield samples[start:start + batch_size]


def search_selector_weights(samples, epsilon_y=1e-8, batch_size=32):
  return _search_chunks(_list_chunks(samples, batch_size), epsilon_y)


def _jsonl_chunks(path, batch_size):
  chunk = []
  with open(path, "r", encoding="utf-8") as input_file:
    for line in input_file:
      if not line.strip():
        continue
      chunk.append(json.loads(line))
      if len(chunk) >= batch_size:
        yield chunk
        chunk = []
  if chunk:
    yield chunk


def search_selector_weights_jsonl(path, epsilon_y=1e-8, batch_size=32):
  """Searches fixed validation samples without replaying the trace."""
  return _search_chunks(_jsonl_chunks(path, batch_size), epsilon_y)


def selector_params_from_search(clipping, search_result):
  weights = search_result["weights"]
  result = dict(clipping)
  for key, value in zip(WEIGHT_NAMES, weights):
    result[key] = float(value)
  for key in (
      "Recall@K", "NRegret", "effective_decision_points",
      "nondiscriminative_ratio", "mean_oracle_size",
      "unique_oracle_ratio", "grid_size", "fallback_uniform"):
    result[key] = search_result[key]
  return result
