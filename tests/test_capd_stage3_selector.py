# coding=utf-8
"""Deterministic CPU-only tests for CAPD stage-3 selector validation.

These tests are intended for the Linux validation server.  Codex does not run
them in the local development environment.
"""

import inspect
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import selector_search
from scripts import run_capd_stage3_selector as stage3


def sample(features, relevance, retained=1, global_oracle=None,
           decision=1):
  count = len(relevance)
  if global_oracle is None:
    maximum = max(relevance)
    global_oracle = [math.isclose(value, maximum) for value in relevance]
  return {
      "B_t": count,
      "retained_K": retained,
      "selector_features": features,
      "relevance": relevance,
      "global_oracle_in_pool": global_oracle,
      "pool_recall": float(any(global_oracle)),
      "decision_index": decision,
      "P_t": list(range(100, 100 + count)),
      "original_pool_ranks": list(range(count)),
      "schema_version": finals_config.SCHEMA_VERSION,
      "contract_id": finals_config.CONTRACT_ID,
      "run_profile": "official",
      "artifact_class": "official",
      "workload_id": "canneal",
  }


def frozen_selector(samples):
  result = selector_search.search_selector_weights(samples)
  selector = {
      name: value for name, value in zip(
          selector_search.WEIGHT_NAMES, result["weights"])
  }
  for name in stage3.METRICS + (
      "effective_decision_points", "nondiscriminative_ratio",
      "mean_oracle_size", "unique_oracle_ratio", "grid_size",
      "fallback_uniform"):
    selector[name] = result[name]
  return selector


class Stage3GridTest(unittest.TestCase):

  def test_full_grid_has_exactly_1001_points(self):
    grid = selector_search.weight_grid()
    self.assertEqual(1001, len(grid))
    self.assertEqual(1001, len(set(grid)))
    self.assertTrue(all(math.isclose(sum(weights), 1.0)
                        for weights in grid))

  def test_every_leave_one_out_grid_has_exactly_286_points(self):
    for index in range(5):
      grid = stage3._leave_one_out_grid(index)
      self.assertEqual(286, len(grid))
      self.assertEqual(286, len(set(grid)))
      self.assertTrue(all(weights[index] == 0.0 for weights in grid))

  def test_five_one_hot_weights_are_exact(self):
    expected = []
    for index in range(5):
      expected.append(tuple(
          1.0 if item == index else 0.0 for item in range(5)))
    self.assertEqual([
        (1.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 1.0),
    ], expected)

  def test_four_level_choice_order(self):
    uniform = (0.2,) * 5
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.9, uniform),
        selector_search.weight_choice_key(0.9, 0.0, uniform))
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.1, uniform),
        selector_search.weight_choice_key(1.0, 0.2, uniform))
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.0, uniform),
        selector_search.weight_choice_key(
            1.0, 0.0, (1.0, 0.0, 0.0, 0.0, 0.0)))
    left = (0.1, 0.2, 0.2, 0.2, 0.3)
    right = (0.3, 0.2, 0.2, 0.2, 0.1)
    self.assertLess(
        selector_search.weight_choice_key(1.0, 0.0, left),
        selector_search.weight_choice_key(1.0, 0.0, right))


class Stage3MetricTest(unittest.TestCase):

  def test_any_hit_recall_and_tie_coverage_are_distinct(self):
    current = sample(
        [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 1, 0, 0]],
        [2.0, 2.0, 0.0], retained=1)
    result = stage3._evaluate_weights(
        stage3._metric_context([current]), (1, 0, 0, 0, 0))
    self.assertEqual(1.0, result["SelectorRecall@K"])
    self.assertEqual(0.5, result["TieCoverage@K"])

  def test_nondiscriminative_sample_is_excluded_only_from_two_metrics(self):
    effective = sample(
        [[1, 0, 0, 0, 0], [0, 0, 0, 0, 0]], [0.0, 1.0],
        retained=1, decision=1)
    nondiscriminative = sample(
        [[1, 0, 0, 0, 0], [0, 0, 0, 0, 0]], [1.0, 1.0],
        retained=1, decision=2)
    result = stage3._evaluate_weights(
        stage3._metric_context([effective, nondiscriminative]),
        (1, 0, 0, 0, 0))
    self.assertEqual(2, result["total_complete_decision_points"])
    self.assertEqual(1, result["effective_decision_points"])
    self.assertEqual(0.0, result["SelectorRecall@K"])
    self.assertEqual(1.0, result["NRegret"])
    self.assertEqual(0.25, result["TieCoverage@K"])

  def test_all_nondiscriminative_full_search_uses_uniform_fallback(self):
    current = sample(
        [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0]], [2.0, 2.0],
        retained=1)
    result = selector_search.search_selector_weights([current])
    self.assertTrue(result["fallback_uniform"])
    self.assertEqual((0.2,) * 5, result["weights"])
    self.assertEqual(0, result["effective_decision_points"])

  def test_same_inputs_produce_identical_results(self):
    samples = [
        sample([[1, 0, 0, 0, 0], [0, 1, 0, 0, 0]],
               [1.0, 0.0], decision=1),
        sample([[0, 1, 0, 0, 0], [1, 0, 0, 0, 0]],
               [0.0, 1.0], decision=2),
    ]
    context = stage3._metric_context(samples)
    grid = stage3._leave_one_out_grid(4)
    self.assertEqual(stage3._search_grid(context, grid),
                     stage3._search_grid(context, grid))


class Stage3AnalysisTest(unittest.TestCase):

  def test_synthetic_full_single_and_leave_one_out_are_complete(self):
    samples = [
        sample([[1, 0, 0, 0, 0], [0, 1, 0, 0, 0]],
               [1.0, 0.0], decision=1),
        sample([[0, 1, 0, 0, 0], [1, 0, 0, 0, 0]],
               [1.0, 0.0], decision=2),
    ]
    audit = {
        "samples": samples,
        "selector": frozen_selector(samples),
        "identity": {"workload": "canneal", "B": 2, "K": 8},
    }
    result = stage3._analyze_pair(audit)
    self.assertEqual("full", result["full"]["kind"])
    self.assertEqual(5, len(result["single_feature"]))
    self.assertEqual(5, len(result["leave_one_out"]))
    for index, variant in enumerate(result["single_feature"]):
      weights = variant["weights_by_feature"]
      self.assertEqual(1.0, weights[stage3.FEATURES[index]])
      self.assertEqual(1.0, sum(weights.values()))
    for variant in result["leave_one_out"]:
      self.assertEqual(0.0,
                       variant["weights_by_feature"][variant["feature"]])
      self.assertEqual(286, variant["grid_size"])

  def test_full_mismatch_hard_fails_before_ablation(self):
    samples = [sample(
        [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0]], [1.0, 0.0])]
    selector = frozen_selector(samples)
    selector["SelectorRecall@K"] = 0.25
    with self.assertRaises(ValueError):
      stage3._analyze_pair({
          "samples": samples, "selector": selector,
          "identity": {"workload": "canneal", "B": 2, "K": 8},
      })

  def test_B8_mechanical_invariants(self):
    features = []
    for index in range(8):
      features.append([float(index == feature) for feature in range(5)])
    samples = [sample(features, list(range(8)), retained=8)]
    audit = {
        "samples": samples,
        "selector": frozen_selector(samples),
        "identity": {"workload": "canneal", "B": 8, "K": 8},
    }
    result = stage3._analyze_pair(audit)
    self.assertTrue(all(result["B8_invariants"].values()))
    self.assertEqual(1.0, result["full"]["SelectorRecall@K"])
    self.assertEqual(result["full"]["PoolRecall@B"],
                     result["full"]["EndToEndRecall@K"])
    self.assertEqual(0.0, result["full"]["NRegret"])

  def test_b_sweep_reports_alignment_monotonicity_and_absolute_gain(self):
    audits = []
    details = []
    for workload in stage3.WORKLOADS:
      large_pages = list(range(64))
      large_oracle = [False] * 63 + [True]
      for pool_size in stage3.POOL_SIZES:
        row = {
            "decision_index": 10,
            "P_t": large_pages[:pool_size],
            "original_pool_ranks": list(range(pool_size)),
            "global_oracle_in_pool": large_oracle[:pool_size],
        }
        audits.append({
            "identity": {"workload": workload, "B": pool_size},
            "samples": [row],
        })
        details.append({
            "workload": workload, "B": pool_size,
            "full": {"PoolRecall@B": float(pool_size == 64)},
        })
    result = stage3._verify_b_sweep(audits, details)
    for workload in stage3.WORKLOADS:
      self.assertTrue(result[workload]["decision_alignment_passed"])
      self.assertTrue(result[workload]["pool_recall_nondecreasing"])
      self.assertEqual(
          1.0, result[workload]["pool_recall_absolute_gain_B8_to_B64"])
      self.assertTrue(result[workload]["expanded_pool_improved_coverage"])

  def test_atomic_output_bundle_is_complete_and_refuses_overwrite(self):
    samples = [sample(
        [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0]], [1.0, -1.0])]
    inputs = {
        name: {"path": name, "sha256": name + "-sha256"}
        for name in (
            "resolved_config", "selector_params",
            "selector_validation_samples", "generator_summary")
    }
    detail = stage3._analyze_pair({
        "samples": samples,
        "selector": frozen_selector(samples),
        "identity": {
            "schema_version": stage3.RESULT_SCHEMA,
            "artifact_schema": finals_config.SCHEMA_VERSION,
            "contract_id": finals_config.CONTRACT_ID,
            "run_profile": "official",
            "artifact_class": "official",
            "workload": "canneal", "B": 2, "K": 8,
            "config_fingerprint": "config-sha256",
            "selector_fingerprint": "selector-sha256",
            "validation_samples_fingerprint": "samples-sha256",
            "inputs": inputs,
        },
    })
    detail.update({"code_commit": "test-commit", "command": "test command"})
    sweep_item = {
        "decision_alignment_passed": True,
        "decision_alignment_errors": [],
        "pool_recall_nondecreasing": True,
        "pool_recall_absolute_gain_B8_to_B64": 0.0,
        "expanded_pool_improved_coverage": False,
    }
    selector_item = {
        "exactly_stable_across_B": True,
        "max_adjacent_B_weight_L1_distance": 0.0,
        "fallback_uniform_B": [],
        "leave_one_out_degradation_count": 0,
    }
    summary = {
        "schema_version": stage3.RESULT_SCHEMA,
        "artifact_schema": finals_config.SCHEMA_VERSION,
        "contract_id": finals_config.CONTRACT_ID,
        "code_commit": "test-commit",
        "command": "test command",
        "input_bindings": [{
            "workload": "canneal", "B": 2, "inputs": inputs,
        }],
        "B_sweep_diagnostics": {
            workload: dict(sweep_item) for workload in stage3.WORKLOADS
        },
        "selector_diagnostics": {
            workload: dict(selector_item) for workload in stage3.WORKLOADS
        },
    }
    with tempfile.TemporaryDirectory() as directory:
      output = os.path.join(directory, "stage3_selector")
      stage3._write_outputs(output, summary, [detail], {"status": "PASSED"})
      for relative in (
          "stage3_summary.json", "stage3_metrics.csv",
          "stage3_ablation.csv", "stage3_report.md", "input_audit.json",
          os.path.join("details", "canneal_B2.json")):
        self.assertTrue(os.path.isfile(os.path.join(output, relative)))
      with self.assertRaises(ValueError):
        stage3._write_outputs(
            output, summary, [detail], {"status": "PASSED"})


class Stage3InputGateTest(unittest.TestCase):

  def _write_row(self, path, **overrides):
    row = sample([[float(index == feature) for feature in range(5)]
                  for index in range(8)], list(range(8)), retained=8)
    row.update(overrides)
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
      output_file.write(json.dumps(row, sort_keys=True) + "\n")

  def test_K_not_equal_to_8_hard_fails(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "samples.jsonl")
      self._write_row(path, retained_K=7)
      with self.assertRaises(ValueError):
        stage3._load_and_validate_samples(path, "canneal", 8)

  def test_negative_relevance_is_valid_under_frozen_proxy_formula(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "samples.jsonl")
      self._write_row(path, relevance=[-8.0, -7.0, -6.0, -5.0,
                                       -4.0, -3.0, -2.0, -1.0])
      rows = stage3._load_and_validate_samples(path, "canneal", 8)
      self.assertEqual(1, len(rows))
      self.assertEqual(-8.0, min(rows[0]["relevance"]))

  def test_contract_schema_profile_workload_and_B_mismatch_hard_fail(self):
    cases = (
        {"contract_id": "wrong"},
        {"schema_version": "capd_finals_v2_1"},
        {"run_profile": "smoke"},
        {"artifact_class": "smoke_only"},
        {"workload_id": "wrong"},
        {"B_t": 16},
    )
    with tempfile.TemporaryDirectory() as directory:
      for index, overrides in enumerate(cases):
        path = os.path.join(directory, "samples-{}.jsonl".format(index))
        self._write_row(path, **overrides)
        with self.assertRaises(ValueError, msg=str(overrides)):
          stage3._load_and_validate_samples(path, "canneal", 8)

  def test_output_inside_stage2_artifacts_is_rejected(self):
    with tempfile.TemporaryDirectory() as repo:
      artifacts = os.path.join(repo, "dataset", "jsonl",
                               "finals_v3_official")
      os.makedirs(artifacts)
      args = mock.Mock(workloads=list(stage3.WORKLOADS),
                       pool_sizes=list(stage3.POOL_SIZES))
      with self.assertRaises(ValueError):
        stage3._validate_cli_scope(
            args, repo, artifacts, os.path.join(artifacts, "stage3"))

  def test_analysis_audit_has_no_test_or_reranker_read_path(self):
    source = inspect.getsource(stage3._audit_pair)
    self.assertNotIn("test_trace", source)
    self.assertNotIn("train.jsonl", source)
    self.assertNotIn("valid.jsonl", source)

  def test_selector_validation_sample_fingerprint_mismatch_hard_fails(self):
    with tempfile.TemporaryDirectory() as repo:
      root = os.path.join(repo, "artifacts", "canneal", "B8")
      os.makedirs(root)
      paths = {
          "resolved_config.json": {},
          "selector_params.json": {},
          "generator_summary.json": {},
      }
      for name, value in paths.items():
        with open(os.path.join(root, name), "w", encoding="utf-8") as output:
          json.dump(value, output)
      sample_path = os.path.join(root, "selector_validation_samples.jsonl")
      self._write_row(sample_path)
      config = {
          "schema_version": finals_config.SCHEMA_VERSION,
          "contract": {"id": finals_config.CONTRACT_ID},
          "run_profile": "official",
          "validation": {"artifact_class": "official",
                         "strategy": "independent_valid_trace"},
          "run": {"workload": "canneal",
                  "resolved_config_fingerprint": "config-hash"},
          "candidate": {"pool_size_B": 8, "retained_K": 8,
                        "selector_history_Hc": 256},
          "labels": {"future_lookahead_L": 256},
          "selector": {"epsilon_y": 1e-8, "grid_step": 0.1},
          "metrics": {"selector_recall_tie": "any_hit"},
          "data": {"split_fingerprints": {"valid": "valid-hash"}},
      }
      selector = {
          "grid_size": 1001, "selection_rule": stage3.SELECTION_RULE,
          "validation_samples_fingerprint": "tampered",
          "valid_trace_fingerprint": "valid-hash",
          "c_Delta": 1.0, "c_A": 1.0, "c_W": 1.0,
          "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
          "w_C": 0.2, "w_R": 0.2,
      }
      with mock.patch.object(stage3, "_load_json",
                             side_effect=[config, selector, {}]), \
           mock.patch.object(stage3.finals_config, "validate_config"), \
           mock.patch.object(stage3.finals_config,
                             "validate_selector_params"), \
           mock.patch.object(stage3.finals_config, "config_fingerprint",
                             return_value="config-hash"):
        with self.assertRaises(ValueError):
          stage3._audit_pair(repo, os.path.join(repo, "artifacts"),
                             "canneal", 8)

  def test_generator_summary_uses_nested_validation_sample_fingerprints(self):
    expected = "sample-sha256"
    summary = {
        "train_metadata": {
            "selector_params": {
                "validation_samples_fingerprint": expected,
            },
        },
    }
    valid_metadata = {
        "selector_params": {
            "validation_samples_fingerprint": expected,
        },
    }
    stage3._validate_summary_validation_sample_fingerprint(
        summary, valid_metadata, expected)
    broken = {
        "selector_params": {
            "validation_samples_fingerprint": "wrong",
        },
    }
    with self.assertRaises(ValueError):
      stage3._validate_summary_validation_sample_fingerprint(
          summary, broken, expected)

  def test_audit_only_does_not_write_results(self):
    with tempfile.TemporaryDirectory() as repo:
      artifact_root = os.path.join(repo, "artifacts")
      os.makedirs(artifact_root)
      audit = {"identity": {"workload": "canneal", "B": 8}}
      argv = [
          "--repo-root", repo, "--artifact-root", artifact_root,
          "--output", os.path.join(repo, "results"), "--audit-only",
      ]
      with mock.patch.object(stage3, "_audit_pair", return_value=audit) as fn, \
           mock.patch.object(stage3, "_write_outputs") as write:
        self.assertEqual(0, stage3.main(argv))
        self.assertEqual(12, fn.call_count)
        write.assert_not_called()


if __name__ == "__main__":
  unittest.main()
