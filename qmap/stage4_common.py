# coding=utf-8
"""Pure, dependency-light helpers for CAPD stage-4 audits."""

from __future__ import print_function

import hashlib
import itertools
import json
import math
import os


STAGE4_SCHEMA = "capd_finals_v3_stage4_audit_1"
WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
SEEDS = (3136859, 42, 2026)
LABEL_VARIANTS = {
    "base": (1.0, 1.0, 4.0),
    "no_write": (1.0, 1.0, 0.0),
    "balanced_write": (1.0, 1.0, 1.0),
    "half_write": (1.0, 1.0, 2.0),
    "stronger_write": (1.0, 1.0, 8.0),
    "inactivity_only": (1.0, 0.0, 0.0),
    "coldness_only": (0.0, 1.0, 0.0),
    "no_inactivity": (0.0, 1.0, 4.0),
    "no_coldness": (1.0, 0.0, 4.0),
}


def require(condition, message):
  if not condition:
    raise ValueError(message)


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def _canonical_jsonl_rows(path):
  with open(path, "r", encoding="utf-8", newline=None) as input_file:
    for line_number, line in enumerate(input_file, start=1):
      if not line.strip():
        continue
      try:
        row = json.loads(line)
      except ValueError as error:
        raise ValueError("{}:{} is not valid JSON".format(
            path, line_number)) from error
      yield line_number, json.dumps(
          row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalized_jsonl_fingerprint(path):
  """Hashes JSON rows canonically, independent of CRLF/LF and whitespace."""
  digest = hashlib.sha256()
  count = 0
  for _, canonical in _canonical_jsonl_rows(path):
    digest.update(canonical.encode("utf-8"))
    digest.update(b"\n")
    count += 1
  return {"sha256": digest.hexdigest(), "row_count": count}


def assert_jsonl_semantically_equal(left_path, right_path, context):
  """Hard-fails at the first semantic row difference, not byte newlines."""
  left_identity = normalized_jsonl_fingerprint(left_path)
  right_identity = normalized_jsonl_fingerprint(right_path)
  if left_identity == right_identity:
    return left_identity
  missing = object()
  for left, right in itertools.zip_longest(
      _canonical_jsonl_rows(left_path), _canonical_jsonl_rows(right_path),
      fillvalue=missing):
    if left is missing or right is missing:
      raise ValueError(
          "{} row-count mismatch: {} != {}".format(
              context, left_identity["row_count"],
              right_identity["row_count"]))
    if left[1] != right[1]:
      raise ValueError(
          "{} semantic mismatch at JSONL row {}".format(context, left[0]))
  raise ValueError("{} normalized fingerprint mismatch".format(context))


def portable(path, root):
  absolute = os.path.abspath(path)
  relative = os.path.relpath(absolute, root)
  if relative == os.pardir or relative.startswith(os.pardir + os.sep):
    return absolute
  return relative.replace(os.sep, "/")


def finite(values, context):
  require(all(math.isfinite(float(value)) for value in values),
          "{} contains NaN/Inf".format(context))


def _quantile_sorted(values, probability):
  """Linear-interpolation quantile for an already sorted float sequence."""
  require(values, "quantile requires non-empty values")
  position = (len(values) - 1) * float(probability)
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  if lower == upper:
    return values[lower]
  fraction = position - lower
  return values[lower] * (1.0 - fraction) + values[upper] * fraction


def quantile(values, probability):
  return _quantile_sorted(
      sorted(float(value) for value in values), probability)


def mean(values):
  return sum(values) / float(len(values)) if values else None


def sample_std(values):
  if len(values) < 2:
    return 0.0 if values else None
  center = mean(values)
  return math.sqrt(sum((value - center) ** 2 for value in values) /
                   float(len(values) - 1))


def describe(values):
  values = [float(value) for value in values]
  finite(values, "distribution")
  if not values:
    return {"count": 0}
  values.sort()
  return {
      "count": len(values), "min": values[0], "max": values[-1],
      "P01": _quantile_sorted(values, .01),
      "P05": _quantile_sorted(values, .05),
      "P25": _quantile_sorted(values, .25),
      "P50": _quantile_sorted(values, .50),
      "P75": _quantile_sorted(values, .75),
      "P95": _quantile_sorted(values, .95),
      "P99": _quantile_sorted(values, .99), "mean": mean(values),
      "std": sample_std(values),
  }


def _average_ranks(values):
  ordered = sorted(range(len(values)), key=lambda index: values[index])
  ranks = [0.0] * len(values)
  cursor = 0
  while cursor < len(ordered):
    end = cursor + 1
    while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
      end += 1
    average = (cursor + 1 + end) / 2.0
    for position in range(cursor, end):
      ranks[ordered[position]] = average
    cursor = end
  return ranks


def spearman(left, right):
  require(len(left) == len(right) and len(left) >= 2,
          "Spearman requires equal sequences with at least two values")
  finite(left, "Spearman left")
  finite(right, "Spearman right")
  left_rank = _average_ranks(left)
  right_rank = _average_ranks(right)
  left_mean = mean(left_rank)
  right_mean = mean(right_rank)
  left_ss = sum((value - left_mean) ** 2 for value in left_rank)
  right_ss = sum((value - right_mean) ** 2 for value in right_rank)
  if left_ss == 0.0 or right_ss == 0.0:
    return None
  covariance = sum((a - left_mean) * (b - right_mean)
                   for a, b in zip(left_rank, right_rank))
  return covariance / math.sqrt(left_ss * right_ss)


def ks_statistic(left, right):
  left = sorted(float(value) for value in left)
  right = sorted(float(value) for value in right)
  require(left and right, "KS requires two non-empty samples")
  finite(left, "KS left")
  finite(right, "KS right")
  i = j = 0
  maximum = 0.0
  while i < len(left) or j < len(right):
    if j >= len(right) or (i < len(left) and left[i] <= right[j]):
      value = left[i]
    else:
      value = right[j]
    while i < len(left) and left[i] <= value:
      i += 1
    while j < len(right) and right[j] <= value:
      j += 1
    maximum = max(maximum, abs(i / float(len(left)) - j / float(len(right))))
  return maximum


def wasserstein_1(left, right):
  require(left and right, "Wasserstein-1 requires two non-empty samples")
  left = sorted(float(value) for value in left)
  right = sorted(float(value) for value in right)
  count = max(len(left), len(right), 2)
  total = 0.0
  for index in range(count):
    probability = index / float(count - 1)
    total += abs(_quantile_sorted(left, probability) -
                 _quantile_sorted(right, probability))
  return total / float(count)


def distribution_distance(reference, observed):
  reference_min = min(reference)
  reference_max = max(reference)
  summary = {
      "reference": describe(reference), "observed": describe(observed),
      "ks": ks_statistic(reference, observed),
      "wasserstein_1": wasserstein_1(reference, observed),
      "outside_reference_range_ratio": mean([
          float(value < reference_min or value > reference_max)
          for value in observed]),
  }
  summary["warning"] = (
      "large" if summary["ks"] >= .2 else
      "moderate" if summary["ks"] >= .1 else "none")
  summary["warning_note"] = (
      "Engineering diagnostic threshold, not statistical significance.")
  return summary


def binary_distance(reference, observed):
  require(reference and observed, "binary comparison requires values")
  require(set(reference).issubset({0, 1}) and set(observed).issubset({0, 1}),
          "binary feature contains a non-binary value")
  ref_one = mean(reference)
  obs_one = mean(observed)
  return {
      "reference": {"count": len(reference), "zero": reference.count(0),
                    "one": reference.count(1), "one_ratio": ref_one},
      "observed": {"count": len(observed), "zero": observed.count(0),
                   "one": observed.count(1), "one_ratio": obs_one},
      "one_ratio_difference": obs_one - ref_one,
      "ks": abs(obs_one - ref_one),
  }


def proxy_scores(labels, weights):
  lambda_d, lambda_q, lambda_w = weights
  return [lambda_d * row["d_hat"] + lambda_q * row["q_hat"] -
          lambda_w * row["w_hat"] for row in labels]


def ndcg_from_costs(scores, costs, original_ranks):
  require(len(scores) == len(costs) == len(original_ranks) and scores,
          "NDCG inputs must be non-empty and aligned")
  finite(scores, "NDCG scores")
  finite(costs, "NDCG costs")
  minimum = min(costs)
  maximum = max(costs)
  indistinguishable = maximum == minimum
  relevance = ([1.0] * len(costs) if indistinguishable else
               [(maximum - value) / float(maximum - minimum)
                for value in costs])
  predicted = sorted(range(len(scores)),
                     key=lambda i: (-scores[i], original_ranks[i]))
  ideal = sorted(range(len(scores)),
                 key=lambda i: (-relevance[i], original_ranks[i]))
  def dcg(order):
    return sum(relevance[index] / math.log(position + 2, 2)
               for position, index in enumerate(order))
  denominator = dcg(ideal)
  return (1.0 if denominator == 0.0 else dcg(predicted) / denominator,
          indistinguishable)
