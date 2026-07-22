# coding=utf-8
"""Independent stage-3 analysis of the frozen CAPD candidate selector.

This program reads only stage-2 selector parameters, selector validation
samples, resolved configuration, and generator summary.  It never reads a
reranker JSONL or a test trace and never trains or replays a policy.
"""

from __future__ import print_function

import argparse
import csv
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

import numpy as np


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import selector_search


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
POOL_SIZES = (8, 16, 32, 64)
FEATURES = ("Delta", "A", "W", "C", "R")
K = 8
HC = 256
LOOKAHEAD = 256
EPSILON_Y = 1e-8
GRID_SIZE = 1001
LOO_GRID_SIZE = 286
RESULT_SCHEMA = "capd_finals_v3_stage3_selector_1"
METRIC_SOURCE = "valid_trace"
METRICS = (
    "PoolRecall@B", "SelectorRecall@K", "EndToEndRecall@K",
    "TieCoverage@K", "NRegret")
SELECTOR_METRICS = ("SelectorRecall@K", "NRegret")
ALL_WINDOW_METRICS = (
    "PoolRecall@B", "EndToEndRecall@K", "TieCoverage@K")
SELECTION_RULE = (
    "selector_recall_desc,nregret_asc,uniform_distance,lexicographic")


def _load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def _portable(path, repo_root):
  absolute = os.path.abspath(path)
  try:
    relative = os.path.relpath(absolute, repo_root)
  except ValueError:
    return absolute
  if relative == os.pardir or relative.startswith(os.pardir + os.sep):
    return absolute
  return relative.replace(os.sep, "/")


def _current_commit(repo_root):
  try:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        stderr=subprocess.STDOUT, universal_newlines=True).strip()
  except (OSError, subprocess.CalledProcessError):
    return "unknown"


def _input_record(path, repo_root):
  return {
      "path": _portable(path, repo_root),
      "sha256": finals_config.fingerprint_file(path),
  }


def _require(condition, message):
  if not condition:
    raise ValueError(message)


def _finite_sequence(values, context):
  for value in values:
    _require(math.isfinite(float(value)), "{} contains NaN/Inf".format(
        context))


def _load_and_validate_samples(path, workload, pool_size):
  samples = []
  decisions = set()
  with open(path, "r", encoding="utf-8") as input_file:
    for line_number, line in enumerate(input_file, start=1):
      if not line.strip():
        continue
      row = json.loads(line)
      context = "{}:{}".format(path, line_number)
      expected_identity = {
          "schema_version": finals_config.SCHEMA_VERSION,
          "contract_id": finals_config.CONTRACT_ID,
          "run_profile": finals_config.OFFICIAL_PROFILE,
          "artifact_class": "official",
          "workload_id": workload,
      }
      for key, expected in expected_identity.items():
        _require(row.get(key) == expected,
                 "{} {} mismatch".format(context, key))
      _require(int(row.get("B_t", -1)) == pool_size,
               "{} B_t mismatch".format(context))
      _require(int(row.get("retained_K", -1)) == K,
               "{} retained_K mismatch".format(context))
      decision = int(row.get("decision_index", -1))
      _require(decision >= 0 and decision not in decisions,
               "{} invalid/duplicate decision_index".format(context))
      decisions.add(decision)
      required = (
          "P_t", "original_pool_ranks", "selector_features", "relevance",
          "global_oracle_in_pool", "pool_recall")
      _require(all(key in row for key in required),
               "{} missing stage-3 sample fields".format(context))
      for key in ("P_t", "original_pool_ranks", "selector_features",
                  "relevance", "global_oracle_in_pool"):
        _require(len(row[key]) == pool_size,
                 "{} {} length mismatch".format(context, key))
      _require(row["original_pool_ranks"] == list(range(pool_size)),
               "{} original LRU ranks are not frozen order".format(context))
      _require(len(set(row["P_t"])) == pool_size,
               "{} P_t contains duplicate pages".format(context))
      for feature_index, feature_row in enumerate(row["selector_features"]):
        _require(len(feature_row) == len(FEATURES),
                 "{} feature width mismatch at {}".format(
                     context, feature_index))
        _finite_sequence(feature_row, context + " selector_features")
        _require(all(-1e-12 <= float(value) <= 1.0 + 1e-12
                     for value in feature_row),
                 "{} selector feature outside [0,1]".format(context))
      _finite_sequence(row["relevance"], context + " relevance")
      _require(all(float(value) >= 0.0 for value in row["relevance"]),
               "{} relevance must be nonnegative".format(context))
      _require(all(isinstance(value, bool)
                   for value in row["global_oracle_in_pool"]),
               "{} global oracle mask must be boolean".format(context))
      expected_pool_recall = float(any(row["global_oracle_in_pool"]))
      _require(float(row["pool_recall"]) == expected_pool_recall,
               "{} PoolRecall@B encoding mismatch".format(context))
      samples.append(row)
  _require(samples, "{} has no validation samples".format(path))
  return samples


def _selector_weights(selector):
  return tuple(float(selector[name]) for name in selector_search.WEIGHT_NAMES)


def _weights_dict(weights):
  return {feature: float(value) for feature, value in zip(FEATURES, weights)}


def _metric_context(samples, epsilon_y=EPSILON_Y):
  effective = [sample for sample in samples
               if max(sample["relevance"]) - min(sample["relevance"])
               > epsilon_y]
  oracle_sizes = []
  for sample in samples:
    maximum = max(sample["relevance"])
    oracle_sizes.append(sum(
        1 for value in sample["relevance"]
        if math.isclose(value, maximum, rel_tol=0.0, abs_tol=1e-12)))
  return {
      "samples": samples,
      "effective": effective,
      "all_arrays": selector_search._sample_arrays(samples),
      "effective_arrays": selector_search._sample_arrays(effective),
      "total_complete_decision_points": len(samples),
      "effective_decision_points": len(effective),
      "nondiscriminative_ratio": (
          (len(samples) - len(effective)) / float(len(samples))),
      "mean_oracle_size": float(np.mean(oracle_sizes)),
      "unique_oracle_ratio": float(np.mean(
          [size == 1 for size in oracle_sizes])),
  }


def _evaluate_weights(context, weights):
  all_metrics = selector_search.evaluate_weight_batch_metrics(
      context["all_arrays"], [weights])
  result = {name: float(all_metrics[name][0])
            for name in ALL_WINDOW_METRICS}
  if context["effective_arrays"] is None:
    result.update({"SelectorRecall@K": 0.0, "NRegret": 0.0})
  else:
    effective_metrics = selector_search.evaluate_weight_batch_metrics(
        context["effective_arrays"], [weights])
    result.update({name: float(effective_metrics[name][0])
                   for name in SELECTOR_METRICS})
  result.update({
      "weights": tuple(float(value) for value in weights),
      "total_complete_decision_points": context[
          "total_complete_decision_points"],
      "effective_decision_points": context["effective_decision_points"],
      "nondiscriminative_ratio": context["nondiscriminative_ratio"],
      "mean_oracle_size": context["mean_oracle_size"],
      "unique_oracle_ratio": context["unique_oracle_ratio"],
      "fallback_uniform": context["effective_decision_points"] == 0,
      "metric_source": METRIC_SOURCE,
  })
  return result


def _search_grid(context, grid, weight_batch_size=32):
  _require(grid, "weight grid is empty")
  best = None
  for start in range(0, len(grid), weight_batch_size):
    weights = grid[start:start + weight_batch_size]
    all_metrics = selector_search.evaluate_weight_batch_metrics(
        context["all_arrays"], weights)
    if context["effective_arrays"] is None:
      recalls = np.zeros(len(weights), dtype=np.float64)
      regrets = np.zeros(len(weights), dtype=np.float64)
    else:
      effective_metrics = selector_search.evaluate_weight_batch_metrics(
          context["effective_arrays"], weights)
      recalls = effective_metrics["SelectorRecall@K"]
      regrets = effective_metrics["NRegret"]
    for offset, current in enumerate(weights):
      candidate = {
          "weights": tuple(float(value) for value in current),
          "PoolRecall@B": float(all_metrics["PoolRecall@B"][offset]),
          "SelectorRecall@K": float(recalls[offset]),
          "EndToEndRecall@K": float(
              all_metrics["EndToEndRecall@K"][offset]),
          "TieCoverage@K": float(all_metrics["TieCoverage@K"][offset]),
          "NRegret": float(regrets[offset]),
      }
      key = selector_search.weight_choice_key(
          candidate["SelectorRecall@K"], candidate["NRegret"], current)
      if best is None or key < best[0]:
        best = (key, candidate)
  result = best[1]
  result.update({
      "grid_size": len(grid),
      "total_complete_decision_points": context[
          "total_complete_decision_points"],
      "effective_decision_points": context["effective_decision_points"],
      "nondiscriminative_ratio": context["nondiscriminative_ratio"],
      "mean_oracle_size": context["mean_oracle_size"],
      "unique_oracle_ratio": context["unique_oracle_ratio"],
      "fallback_uniform": context["effective_decision_points"] == 0,
      "metric_source": METRIC_SOURCE,
  })
  return result


def _leave_one_out_grid(feature_index):
  grid = []
  for composition in selector_search.integer_weight_compositions(10, 4):
    expanded = list(composition)
    expanded.insert(feature_index, 0)
    grid.append(tuple(value / 10.0 for value in expanded))
  _require(len(grid) == LOO_GRID_SIZE and len(set(grid)) == LOO_GRID_SIZE,
           "leave-one-out grid is not exactly 286 unique weights")
  return grid


def _decorate_variant(kind, feature, result, full):
  decorated = dict(result)
  decorated["kind"] = kind
  decorated["feature"] = feature
  decorated["weights_by_feature"] = _weights_dict(result["weights"])
  decorated["delta_vs_full"] = {
      name: float(result[name] - full[name]) for name in (
          "SelectorRecall@K", "EndToEndRecall@K", "TieCoverage@K",
          "NRegret")
  }
  decorated.pop("weights", None)
  return decorated


def _assert_close(actual, expected, context, tolerance=1e-12):
  if not math.isclose(float(actual), float(expected), rel_tol=tolerance,
                      abs_tol=tolerance):
    raise ValueError("{} mismatch: recomputed={} frozen={}".format(
        context, actual, expected))


def _verify_full_matches_selector(full, selector):
  frozen_weights = _selector_weights(selector)
  for index, (actual, expected) in enumerate(zip(
      full["weights"], frozen_weights)):
    _assert_close(actual, expected, "full weight {}".format(FEATURES[index]))
  for name in METRICS:
    _assert_close(full[name], selector[name], "full {}".format(name))
  for name in (
      "effective_decision_points", "nondiscriminative_ratio",
      "mean_oracle_size", "unique_oracle_ratio"):
    _assert_close(full[name], selector[name], "full {}".format(name))
  _require(int(full["grid_size"]) == int(selector.get("grid_size", -1)) ==
           GRID_SIZE, "full grid_size mismatch")
  _require(bool(full["fallback_uniform"]) == bool(
      selector.get("fallback_uniform")), "full fallback_uniform mismatch")


def _audit_pair(repo_root, artifact_root, workload, pool_size):
  root = os.path.join(artifact_root, workload, "B{}".format(pool_size))
  paths = {
      "resolved_config": os.path.join(root, "resolved_config.json"),
      "selector_params": os.path.join(root, "selector_params.json"),
      "selector_validation_samples": os.path.join(
          root, "selector_validation_samples.jsonl"),
      "generator_summary": os.path.join(root, "generator_summary.json"),
  }
  for name, path in paths.items():
    _require(os.path.isfile(path), "missing {}: {}".format(name, path))
  # The stage-2 resolved-config loader deliberately reopens manifests and
  # hashes split traces, so it is not used in this independent analysis.
  # Stage 3 must validate the frozen resolved payload without touching traces.
  config = _load_json(paths["resolved_config"])
  finals_config.validate_config(config, require_resolved=True)
  recorded_config_fingerprint = config.get("run", {}).get(
      "resolved_config_fingerprint")
  _require(recorded_config_fingerprint is not None and
           recorded_config_fingerprint == finals_config.config_fingerprint(
               config),
           "resolved config fingerprint is missing or stale")
  _require(config["schema_version"] == finals_config.SCHEMA_VERSION,
           "resolved config is not finals v3")
  _require(config["contract"]["id"] == finals_config.CONTRACT_ID,
           "resolved config contract mismatch")
  _require(config["run_profile"] == "official" and
           config["validation"]["artifact_class"] == "official",
           "resolved config is not official")
  _require(config["run"]["workload"] == workload,
           "resolved config workload/directory mismatch")
  _require(int(config["candidate"]["pool_size_B"]) == pool_size,
           "resolved config B/directory mismatch")
  _require(int(config["candidate"]["retained_K"]) == K,
           "stage 3 requires retained_K=8")
  _require(int(config["candidate"]["selector_history_Hc"]) == HC,
           "stage 3 requires Hc=256")
  _require(int(config["labels"]["future_lookahead_L"]) == LOOKAHEAD,
           "stage 3 requires L=256")
  _require(float(config["selector"]["epsilon_y"]) == EPSILON_Y,
           "stage 3 requires epsilon_y=1e-8")
  _require(float(config["selector"]["grid_step"]) == 0.1,
           "stage 3 requires selector grid step 0.1")
  _require(config["validation"]["strategy"] == "independent_valid_trace",
           "stage 3 requires independent_valid_trace")
  _require(config["metrics"]["selector_recall_tie"] == "any_hit",
           "stage 3 requires any-hit selector recall")

  selector = _load_json(paths["selector_params"])
  finals_config.validate_selector_params(config, selector)
  selector_weights = _selector_weights(selector)
  _finite_sequence(selector_weights, "selector weights")
  _require(all(value >= 0.0 for value in selector_weights) and
           math.isclose(sum(selector_weights), 1.0,
                        rel_tol=0.0, abs_tol=1e-12),
           "selector weights must be nonnegative and sum to one")
  for clipping_name in ("c_Delta", "c_A", "c_W"):
    clipping_value = float(selector[clipping_name])
    _require(math.isfinite(clipping_value) and clipping_value >= 1.0,
             "{} must be finite and at least one".format(clipping_name))
  _require(selector.get("grid_size") == GRID_SIZE,
           "selector grid_size is not 1001")
  _require(selector.get("selection_rule") == SELECTION_RULE,
           "selector selection rule mismatch")
  sample_hash = finals_config.fingerprint_file(
      paths["selector_validation_samples"])
  _require(selector.get("validation_samples_fingerprint") == sample_hash,
           "selector/validation sample fingerprint mismatch")
  valid_fingerprint = config["data"]["split_fingerprints"]["valid"]
  _require(selector.get("valid_trace_fingerprint") == valid_fingerprint,
           "selector is not bound to frozen valid trace")

  summary = _load_json(paths["generator_summary"])
  finals_config.validate_artifact_identity(config, summary,
                                            "generator summary")
  _require(summary.get("selector_fingerprint") ==
           finals_config.selector_fingerprint(selector),
           "generator summary/selector fingerprint mismatch")
  valid_metadata = summary.get("valid_metadata", {})
  _require(valid_metadata.get("source_partition") ==
           "independent_valid_trace",
           "validation samples are not identified as valid trace")
  _require(valid_metadata.get("source_trace_fingerprint") ==
           valid_fingerprint,
           "generator summary/valid trace fingerprint mismatch")
  _require(summary.get("validation_samples_fingerprint") == sample_hash,
           "generator summary/validation sample fingerprint mismatch")

  samples = _load_and_validate_samples(
      paths["selector_validation_samples"], workload, pool_size)
  _require(int(selector.get("validation_decision_points", -1)) == len(samples),
           "selector validation decision count mismatch")
  _require(int(valid_metadata.get("sample_count", -1)) == len(samples),
           "generator summary validation decision count mismatch")
  return {
      "root": root,
      "paths": paths,
      "config": config,
      "selector": selector,
      "samples": samples,
      "identity": {
          "schema_version": RESULT_SCHEMA,
          "artifact_schema": finals_config.SCHEMA_VERSION,
          "contract_id": finals_config.CONTRACT_ID,
          "run_profile": "official",
          "artifact_class": "official",
          "workload": workload,
          "B": pool_size,
          "K": K,
          "config_fingerprint": finals_config.config_fingerprint(config),
          "selector_fingerprint": finals_config.selector_fingerprint(
              selector),
          "validation_samples_fingerprint": sample_hash,
          "inputs": {name: _input_record(path, repo_root)
                     for name, path in paths.items()},
      },
  }


def _analyze_pair(audit):
  samples = audit["samples"]
  context = _metric_context(samples)
  full_raw = selector_search.search_selector_weights(
      samples, epsilon_y=EPSILON_Y, batch_size=32)
  full_raw["total_complete_decision_points"] = len(samples)
  full_raw["metric_source"] = METRIC_SOURCE
  _verify_full_matches_selector(full_raw, audit["selector"])
  full = _decorate_variant("full", None, full_raw, full_raw)
  single = []
  leave_out = []
  for index, feature in enumerate(FEATURES):
    weights = tuple(1.0 if item == index else 0.0
                    for item in range(len(FEATURES)))
    single_result = _evaluate_weights(context, weights)
    single.append(_decorate_variant(
        "single_feature", feature, single_result, full_raw))
    loo_result = _search_grid(context, _leave_one_out_grid(index))
    leave_out.append(_decorate_variant(
        "leave_one_out", feature, loo_result, full_raw))
  b8_invariants = None
  if audit["identity"]["B"] == K:
    b8_invariants = {
        "P_t_equals_C_t": True,
        "SelectorRecall@K_equals_1_if_effective": (
            not context["effective_decision_points"] or
            math.isclose(full_raw["SelectorRecall@K"], 1.0,
                         rel_tol=0.0, abs_tol=1e-12)),
        "EndToEndRecall@K_equals_PoolRecall@B": math.isclose(
            full_raw["EndToEndRecall@K"], full_raw["PoolRecall@B"],
            rel_tol=0.0, abs_tol=1e-12),
        "NRegret_equals_0": math.isclose(
            full_raw["NRegret"], 0.0, rel_tol=0.0, abs_tol=1e-12),
    }
    _require(all(b8_invariants.values()), "B=8 mechanical invariant failed")
  detail = dict(audit["identity"])
  detail.update({
      "status": "STAGE3_IMPLEMENTED_UNVERIFIED",
      "run_status": "PASSED",
      "metric_source": METRIC_SOURCE,
      "metric_denominators": {
          "SelectorRecall@K": "effective_decision_points",
          "NRegret": "effective_decision_points",
          "PoolRecall@B": "total_complete_decision_points",
          "EndToEndRecall@K": "total_complete_decision_points",
          "TieCoverage@K": "total_complete_decision_points",
      },
      "weight_search": {
          "full_grid_size": GRID_SIZE,
          "leave_one_out_grid_size": LOO_GRID_SIZE,
          "step": 0.1,
          "constraints": "nonnegative,sum_to_one",
          "selection_rule": SELECTION_RULE,
      },
      "full": full,
      "single_feature": single,
      "leave_one_out": leave_out,
      "B8_invariants": b8_invariants,
  })
  return detail


def _verify_b_sweep(audits, details):
  diagnostics = {}
  for workload in WORKLOADS:
    by_b_audit = {item["identity"]["B"]: item for item in audits
                  if item["identity"]["workload"] == workload}
    by_b_detail = {item["B"]: item for item in details
                   if item["workload"] == workload}
    reference = by_b_audit[POOL_SIZES[-1]]["samples"]
    reference_by_decision = {
        row["decision_index"]: row for row in reference}
    alignment_errors = []
    for pool_size in POOL_SIZES[:-1]:
      current = by_b_audit[pool_size]["samples"]
      current_by_decision = {row["decision_index"]: row for row in current}
      if set(current_by_decision) != set(reference_by_decision):
        alignment_errors.append(
            "B{} decision_index set differs from B64".format(pool_size))
        continue
      for decision, row in current_by_decision.items():
        large = reference_by_decision[decision]
        if (large["P_t"][:pool_size] != row["P_t"] or
            large["original_pool_ranks"][:pool_size] !=
            row["original_pool_ranks"] or
            large["global_oracle_in_pool"][:pool_size] !=
            row["global_oracle_in_pool"]):
          alignment_errors.append(
              "B{} is not a B64 prefix at decision {}".format(
                  pool_size, decision))
          break
    pool_recalls = [by_b_detail[value]["full"]["PoolRecall@B"]
                    for value in POOL_SIZES]
    monotonic = all(
        right + 1e-12 >= left
        for left, right in zip(pool_recalls, pool_recalls[1:]))
    diagnostics[workload] = {
        "decision_alignment_passed": not alignment_errors,
        "decision_alignment_errors": alignment_errors,
        "pool_recall_values": {
            str(value): pool_recalls[index]
            for index, value in enumerate(POOL_SIZES)},
        "pool_recall_nondecreasing": monotonic,
        "pool_recall_absolute_gain_B8_to_B64": (
            pool_recalls[-1] - pool_recalls[0]),
        "expanded_pool_improved_coverage": pool_recalls[-1] > (
            pool_recalls[0] + 1e-12),
    }
  return diagnostics


def _macro_average(details):
  result = {}
  for pool_size in POOL_SIZES:
    rows = [item["full"] for item in details if item["B"] == pool_size]
    result[str(pool_size)] = {
        name: float(np.mean([row[name] for row in rows])) for name in METRICS
    }
  return result


def _selector_diagnostics(details):
  diagnostics = {}
  for workload in WORKLOADS:
    ordered = sorted(
        [item for item in details if item["workload"] == workload],
        key=lambda item: item["B"])
    vectors = [[item["full"]["weights_by_feature"][feature]
                for feature in FEATURES] for item in ordered]
    adjacent_l1 = [sum(abs(left - right) for left, right in zip(a, b))
                   for a, b in zip(vectors, vectors[1:])]
    degradations = []
    for item in ordered:
      for variant in item["leave_one_out"]:
        delta = variant["delta_vs_full"]
        if (delta["SelectorRecall@K"] < -1e-12 or
            delta["EndToEndRecall@K"] < -1e-12 or
            delta["TieCoverage@K"] < -1e-12 or
            delta["NRegret"] > 1e-12):
          degradations.append({
              "B": item["B"],
              "removed_feature": variant["feature"],
              "delta_vs_full": delta,
          })
    diagnostics[workload] = {
        "full_weights_by_B": {
            str(item["B"]): item["full"]["weights_by_feature"]
            for item in ordered},
        "exactly_stable_across_B": all(
            vector == vectors[0] for vector in vectors[1:]),
        "adjacent_B_weight_L1_distance": adjacent_l1,
        "max_adjacent_B_weight_L1_distance": max(adjacent_l1 or [0.0]),
        "fallback_uniform_B": [item["B"] for item in ordered
                               if item["full"]["fallback_uniform"]],
        "leave_one_out_degradation_count": len(degradations),
        "leave_one_out_degradations": degradations,
    }
  return diagnostics


def _binding_columns(detail):
  columns = {}
  for name, record in detail["inputs"].items():
    columns["{}_path".format(name)] = record["path"]
    columns["{}_sha256".format(name)] = record["sha256"]
  return columns


def _csv_rows(details):
  rows = []
  for detail in details:
    variants = ([detail["full"]] + detail["single_feature"] +
                detail["leave_one_out"])
    for variant in variants:
      row = {
          "result_schema": detail["schema_version"],
          "artifact_schema": detail["artifact_schema"],
          "contract_id": detail["contract_id"],
          "run_profile": detail["run_profile"],
          "artifact_class": detail["artifact_class"],
          "stage_status": detail["status"],
          "run_status": detail["run_status"],
          "workload": detail["workload"],
          "B": detail["B"],
          "K": K,
          "kind": variant["kind"],
          "feature": variant.get("feature") or "",
          "metric_source": METRIC_SOURCE,
          "fallback_uniform": variant["fallback_uniform"],
          "total_complete_decision_points": variant[
              "total_complete_decision_points"],
          "effective_decision_points": variant[
              "effective_decision_points"],
          "nondiscriminative_ratio": variant[
              "nondiscriminative_ratio"],
          "config_fingerprint": detail["config_fingerprint"],
          "selector_fingerprint": detail["selector_fingerprint"],
          "validation_samples_fingerprint": detail[
              "validation_samples_fingerprint"],
          "code_commit": detail["code_commit"],
          "command": detail["command"],
          "selection_rule": SELECTION_RULE,
          "grid_size": (variant.get("grid_size", 0)
                        if variant["kind"] != "single_feature" else 0),
      }
      row.update(_binding_columns(detail))
      row.update(variant["weights_by_feature"])
      for name in METRICS:
        row[name] = (variant[name] if name != "PoolRecall@B" or
                     variant["kind"] == "full" else "")
      rows.append(row)
  return rows


def _ablation_rows(details):
  rows = []
  for detail in details:
    for variant in detail["single_feature"] + detail["leave_one_out"]:
      row = {
          "result_schema": detail["schema_version"],
          "artifact_schema": detail["artifact_schema"],
          "contract_id": detail["contract_id"],
          "run_profile": detail["run_profile"],
          "artifact_class": detail["artifact_class"],
          "stage_status": detail["status"],
          "run_status": detail["run_status"],
          "workload": detail["workload"], "B": detail["B"], "K": K,
          "kind": variant["kind"], "feature": variant["feature"],
          "metric_source": METRIC_SOURCE,
          "config_fingerprint": detail["config_fingerprint"],
          "selector_fingerprint": detail["selector_fingerprint"],
          "validation_samples_fingerprint": detail[
              "validation_samples_fingerprint"],
          "code_commit": detail["code_commit"],
          "command": detail["command"],
          "selection_rule": SELECTION_RULE,
          "grid_size": variant.get("grid_size", 0),
          "fallback_uniform": variant["fallback_uniform"],
          "total_complete_decision_points": variant[
              "total_complete_decision_points"],
          "effective_decision_points": variant[
              "effective_decision_points"],
      }
      row.update(_binding_columns(detail))
      row.update(variant["weights_by_feature"])
      for name, value in variant["delta_vs_full"].items():
        row["delta_{}".format(name)] = value
      rows.append(row)
  return rows


def _write_csv(path, rows):
  _require(rows, "cannot write empty CSV")
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def _render_report(summary, details):
  lines = [
      "# CAPD 阶段3候选筛选器独立验证报告", "",
      "状态：`STAGE3_IMPLEMENTED_UNVERIFIED`。本报告仅使用冻结的 valid trace selector 样本，"
      "不包含训练、test replay、端到端实验或基线比较。", "",
      "## 制品身份", "",
      "- 结果 schema：`{}`".format(summary["schema_version"]),
      "- 输入 schema：`{}`".format(summary["artifact_schema"]),
      "- 合同：`{}`".format(summary["contract_id"]),
      "- 代码 commit：`{}`".format(summary["code_commit"]),
      "- 完整命令：`{}`".format(summary["command"]), "",
      "| workload | B | config SHA-256 | selector SHA-256 | samples SHA-256 | summary SHA-256 |",
      "|---|---:|---|---|---|---|",
  ]
  for binding in summary["input_bindings"]:
    inputs = binding["inputs"]
    lines.append("| {} | {} | {} | {} | {} | {} |".format(
        binding["workload"], binding["B"],
        inputs["resolved_config"]["sha256"],
        inputs["selector_params"]["sha256"],
        inputs["selector_validation_samples"]["sha256"],
        inputs["generator_summary"]["sha256"]))
  lines.extend([
      "", "输入文件路径与上述完整哈希同时记录在 `input_audit.json`。", "",
      "## B sweep", "",
      "| workload | B | PoolRecall@B | SelectorRecall@K | EndToEndRecall@K | TieCoverage@K | NRegret | weights (Delta,A,W,C,R) |",
      "|---|---:|---:|---:|---:|---:|---:|---|",
  ])
  for detail in details:
    full = detail["full"]
    weights = [full["weights_by_feature"][name] for name in FEATURES]
    lines.append(
        "| {} | {} | {:.12g} | {:.12g} | {:.12g} | {:.12g} | "
        "{:.12g} | {} |".format(
            detail["workload"], detail["B"], full["PoolRecall@B"],
            full["SelectorRecall@K"], full["EndToEndRecall@K"],
            full["TieCoverage@K"], full["NRegret"],
            ",".join("{:.1f}".format(value) for value in weights)))
  lines.extend(["", "## 观察范围扩展结论", ""])
  for workload in WORKLOADS:
    item = summary["B_sweep_diagnostics"][workload]
    answer = "是" if item["expanded_pool_improved_coverage"] else "否"
    lines.append(
        "- `{}`：B=8 到 B=64 的 PoolRecall 绝对增量为 `{:.12g}`；"
        "扩大观察范围是否实际提高覆盖：**{}**。".format(
            workload, item["pool_recall_absolute_gain_B8_to_B64"], answer))
    if not item["pool_recall_nondecreasing"]:
      lines.append("  - 检测到非单调异常；结果保持原样，需复核输入和决策点对齐。")
    if not item["decision_alignment_passed"]:
      lines.append("  - 输入对齐异常：{}".format(
          "; ".join(item["decision_alignment_errors"])))
  lines.extend(["", "## 权重稳定、退化与 fallback", ""])
  for workload in WORKLOADS:
    item = summary["selector_diagnostics"][workload]
    fallback = (",".join("B={}".format(value)
                         for value in item["fallback_uniform_B"])
                if item["fallback_uniform_B"] else "无")
    lines.append(
        "- `{}`：跨B权重完全相同=`{}`，相邻B最大L1距离=`{:.12g}`，"
        "uniform fallback=`{}`，leave-one-out出现退化的组合数=`{}`。".format(
            workload, item["exactly_stable_across_B"],
            item["max_adjacent_B_weight_L1_distance"], fallback,
            item["leave_one_out_degradation_count"]))
  lines.extend([
      "", "## 指标分母", "",
      "`SelectorRecall@K` 与 `NRegret` 只统计 `R_t^y > epsilon_y` 的有效决策点；"
      "`PoolRecall@B`、`EndToEndRecall@K` 与 `TieCoverage@K` 统计全部完整未来窗口决策点。"
      "所有指标来源均为 `valid_trace`，不同分母不合并解释。", "",
      "## 消融说明", "",
      "完整 selector 在五维 1001 点网格上重搜；single-feature 直接评估五个 one-hot；"
      "leave-one-out 将一个特征权重固定为0，并在其余四维的286点子网格上按同一四级规则重搜。"
      "逐项结果与相对 Full 的绝对变化见 `stage3_ablation.csv`。PoolRecall 与 selector 权重无关，"
      "每个 workload/B 只解释一次。", "",
      "## 边界", "",
      "这些结果只验证候选池和轻量筛选器的覆盖行为，不代表系统性能、加权代价或命中率提升。", "",
  ])
  return "\n".join(lines)


def _write_outputs(output_dir, summary, details, input_audit):
  parent = os.path.dirname(output_dir)
  os.makedirs(parent, exist_ok=True)
  _require(not os.path.exists(output_dir),
           "output already exists; refusing to overwrite: {}".format(
               output_dir))
  staging = tempfile.mkdtemp(prefix=".capd-stage3-", dir=parent)
  try:
    finals_config.write_json(os.path.join(staging, "stage3_summary.json"),
                             summary)
    finals_config.write_json(os.path.join(staging, "input_audit.json"),
                             input_audit)
    _write_csv(os.path.join(staging, "stage3_metrics.csv"),
               _csv_rows(details))
    _write_csv(os.path.join(staging, "stage3_ablation.csv"),
               _ablation_rows(details))
    with open(os.path.join(staging, "stage3_report.md"), "w",
              encoding="utf-8", newline="\n") as output_file:
      output_file.write(_render_report(summary, details))
    detail_root = os.path.join(staging, "details")
    os.makedirs(detail_root)
    for detail in details:
      finals_config.write_json(os.path.join(
          detail_root, "{}_B{}.json".format(
              detail["workload"], detail["B"])), detail)
    os.replace(staging, output_dir)
  except Exception:
    shutil.rmtree(staging, ignore_errors=True)
    raise


def _validate_cli_scope(args, repo_root, artifact_root, output_dir):
  _require(tuple(args.workloads) == WORKLOADS,
           "official stage 3 requires workloads in frozen order: {}".format(
               ",".join(WORKLOADS)))
  _require(tuple(args.pool_sizes) == POOL_SIZES,
           "official stage 3 requires B in frozen order: 8,16,32,64")
  _require(os.path.isdir(repo_root), "repo root does not exist")
  _require(os.path.isdir(artifact_root), "official artifact root missing")
  _require(os.path.commonpath([repo_root, artifact_root]) == repo_root,
           "artifact root must be inside repo root")
  output_parent = os.path.dirname(output_dir)
  _require(os.path.commonpath([artifact_root, output_dir]) != artifact_root,
           "stage 3 output cannot be inside stage-2 artifact root")
  _require(output_dir != artifact_root and output_parent != artifact_root,
           "stage 3 output cannot overwrite stage-2 artifacts")


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run independent CAPD stage-3 selector validation.")
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument(
      "--artifact-root",
      default="dataset/jsonl/finals_v3_official")
  parser.add_argument("--workloads", nargs="+", default=list(WORKLOADS))
  parser.add_argument("--pool-sizes", nargs="+", type=int,
                      default=list(POOL_SIZES))
  parser.add_argument(
      "--output",
      default="outputs/results/finals_v3_official/stage3_selector")
  parser.add_argument(
      "--audit-only", action="store_true",
      help="Validate all 12 input sets without searching or writing results.")
  return parser


def main(argv=None):
  args = build_arg_parser().parse_args(argv)
  repo_root = os.path.abspath(args.repo_root)
  artifact_root = os.path.abspath(os.path.join(
      repo_root, args.artifact_root) if not os.path.isabs(args.artifact_root)
      else args.artifact_root)
  output_dir = os.path.abspath(os.path.join(
      repo_root, args.output) if not os.path.isabs(args.output)
      else args.output)
  _validate_cli_scope(args, repo_root, artifact_root, output_dir)
  command = shlex.join(sys.argv if argv is None else
                       [sys.argv[0]] + list(argv))
  code_commit = _current_commit(repo_root)
  audits = []
  for workload in WORKLOADS:
    for pool_size in POOL_SIZES:
      audit = _audit_pair(repo_root, artifact_root, workload, pool_size)
      audits.append(audit)
      print("[OK] input_audit {} B{}".format(workload, pool_size))
  if args.audit_only:
    print("[FINAL] STAGE3_INPUT_AUDIT_PASSED 12/12")
    return 0

  details = []
  for audit in audits:
    detail = _analyze_pair(audit)
    detail["code_commit"] = code_commit
    detail["command"] = command
    details.append(detail)
    print("[OK] analysis {} B{}".format(
        detail["workload"], detail["B"]))
  sweep = _verify_b_sweep(audits, details)
  summary = {
      "schema_version": RESULT_SCHEMA,
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "contract_id": finals_config.CONTRACT_ID,
      "run_profile": "official",
      "artifact_class": "official",
      "status": "STAGE3_IMPLEMENTED_UNVERIFIED",
      "metric_source": METRIC_SOURCE,
      "K": K,
      "workloads": list(WORKLOADS),
      "pool_sizes_B": list(POOL_SIZES),
      "code_commit": code_commit,
      "command": command,
      "result_count": len(details),
      "input_bindings": [{
          "workload": item["workload"],
          "B": item["B"],
          "config_fingerprint": item["config_fingerprint"],
          "selector_fingerprint": item["selector_fingerprint"],
          "validation_samples_fingerprint": item[
              "validation_samples_fingerprint"],
          "inputs": item["inputs"],
      } for item in details],
      "B_sweep_diagnostics": sweep,
      "selector_diagnostics": _selector_diagnostics(details),
      "macro_average_by_B": _macro_average(details),
      "macro_average_note": (
          "Unweighted macro average across the three named workloads; "
          "per-workload results remain authoritative."),
      "prohibited_conclusions": (
          "No training, test replay, baseline comparison, hit-rate claim, "
          "weighted-cost claim, or end-to-end system claim."),
  }
  input_audit = {
      "schema_version": RESULT_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "status": "PASSED",
      "audited_input_sets": len(audits),
      "code_commit": code_commit,
      "command": command,
      "analysis_reads": [
          "resolved_config.json", "selector_params.json",
          "selector_validation_samples.jsonl", "generator_summary.json"],
      "forbidden_reads": [
          "test trace", "train.jsonl", "valid.jsonl", "checkpoint"],
      "inputs": [audit["identity"] for audit in audits],
  }
  _write_outputs(output_dir, summary, details, input_audit)
  print("[done] output={}".format(output_dir))
  print("[FINAL] STAGE3_IMPLEMENTED_UNVERIFIED")
  return 0


if __name__ == "__main__":
  sys.exit(main())
