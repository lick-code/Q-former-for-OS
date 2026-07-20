# coding=utf-8
"""Numeric, non-torch contract tests for CAPD finals stage 1.

These tests are constructed for later server execution. They are not evidence
of local verification.
"""

import copy
import csv
import os
import sys
import tempfile
import types
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter
from qmap import finals_config
from qmap import qmap_eval
from qmap import selector_search
from qmap.finals_generator import FutureOracle
from qmap.finals_generator import LRUBehaviorState
from qmap.finals_generator import build_generator_decision_snapshot
from qmap.finals_generator import has_complete_future_window
from qmap.finals_generator import reference_labels


def resolved_v3(workload="canneal"):
  path = os.path.join(
      PROJECT_ROOT, "configs", "finals", "capd_direction1_v3.json")
  base = finals_config.load_config(path)
  # Stage-1 semantic unit tests predate the stage-2 source-manifest gate.
  base["validation"]["require_data_manifest"] = False
  return finals_config.resolve_config(base, workload, 64)


def selector_for(config):
  selector = finals_config.artifact_identity_from_config(config)
  selector.update({
      "workload": config["run"]["workload"],
      "c_Delta": 10.0,
      "c_A": 2.0,
      "c_W": 1.0,
      "w_Delta": 0.2,
      "w_A": 0.2,
      "w_W": 0.2,
      "w_C": 0.2,
      "w_R": 0.2,
      "train_trace_fingerprint": "train-fingerprint",
      "valid_trace_fingerprint": "valid-fingerprint",
      "validation_samples_fingerprint": "validation-fingerprint",
      "PoolRecall@B": 0.75,
      "SelectorRecall@K": 1.0,
      "EndToEndRecall@K": 0.5,
      "TieCoverage@K": 0.625,
      "NRegret": 0.125,
      "effective_decision_points": 8,
      "nondiscriminative_ratio": 0.2,
      "mean_oracle_size": 1.5,
      "unique_oracle_ratio": 0.5,
      "behavior_policy": "lru",
      "tail_policy": "drop_incomplete_window",
      "selection_rule": (
          "selector_recall_desc,nregret_asc,uniform_distance,lexicographic"),
      "decision_holdout": None,
      "decision_holdout_fingerprint": None,
  })
  return selector


def checkpoint_for(config, selector):
  checkpoint = finals_config.artifact_identity_from_config(config)
  checkpoint.update({
      "workload": config["run"]["workload"],
      "experiment_contract": finals_config.contract_from_config(config),
      "selector_params": copy.deepcopy(selector),
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "decision_holdout_fingerprint": None,
      "feature_embedder": {},
      "extractor": {},
      "scorer": {},
      "seed": 3136859,
      "best_epoch": 3,
      "best_validation_loss": 0.25,
      "model_args": {
          "page_state_dim": 4,
          "shared_page_embedding": True,
          "position_encoding": "sinusoidal",
      },
      "vocab_contract": {
          "page_frozen": True,
          "pc_frozen": True,
          "unk_index": 0,
          "page_vocab_fingerprint": "page-vocab",
          "pc_vocab_fingerprint": "pc-vocab",
      },
      "jsonl_fingerprints": {
          "train": "train-jsonl",
          "valid": "valid-jsonl",
      },
  })
  return checkpoint


def replay_args(trace_path):
  return types.SimpleNamespace(
      trace_path=trace_path, page_shift=0, policy="lru", dram_capacity=2,
      random_seed=0, dram_read_cost=1.0, dram_write_cost=1.0,
      nvm_read_cost=2.0, nvm_write_cost=8.0, migration_cost=10.0,
      checkpoint=None, learned_model=None, device="cpu", history_length=10,
      candidate_count=8, lookahead=256, ablation=None, rank_guard=0,
      rank_score_penalty=0.0)


class LruAndMetricSemanticsTest(unittest.TestCase):

  def test_lru_direction_uses_original_B_t_not_filtered_K_t(self):
    history = candidate_filter.SelectorHistory(8)
    oldest = candidate_filter.raw_selector_values(
        10, 0, 4, 20, history, set())
    newest = candidate_filter.raw_selector_values(
        40, 3, 4, 20, history, set())
    self.assertEqual(1.0, oldest["R_LRU"])
    self.assertEqual(0.0, newest["R_LRU"])
    selected = [
        {"page": 30, "original_pool_rank": 2, "B_t": 4},
        {"page": 10, "original_pool_rank": 0, "B_t": 4},
    ]
    state = candidate_filter.build_candidate_state_features(
        selected, [], 20, {30: 10, 10: 10}, set(), 256, 2)
    self.assertAlmostEqual(1.0 / 3.0,
                           state["candidate_state_features"][0][3])
    self.assertEqual(1.0, state["candidate_state_features"][1][3])

  def test_any_hit_and_tie_coverage_are_distinct_numeric_metrics(self):
    sample = {
        "B_t": 3,
        "retained_K": 1,
        "selector_features": [
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.5, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        "relevance": [1.0, 1.0, 0.0],
        "global_oracle_in_pool": [True, True, False],
        "pool_recall": 1.0,
    }
    metrics = selector_search.evaluate_selector_metrics(
        [sample], (1.0, 0.0, 0.0, 0.0, 0.0))
    self.assertEqual(1.0, metrics["SelectorRecall@K"])
    self.assertEqual(0.5, metrics["TieCoverage@K"])

  def test_pool_selector_end_to_end_and_regret_are_separate(self):
    samples = [
        {
            "B_t": 3, "retained_K": 1,
            "selector_features": [[1.0] + [0.0] * 4,
                                  [0.5] + [0.0] * 4,
                                  [0.0] * 5],
            "relevance": [1.0, 1.0, 0.0],
            "global_oracle_in_pool": [True, True, False],
            "pool_recall": 1.0,
        },
        {
            "B_t": 3, "retained_K": 1,
            "selector_features": [[1.0] + [0.0] * 4,
                                  [0.5] + [0.0] * 4,
                                  [0.0] * 5],
            "relevance": [0.0, 0.0, 1.0],
            "global_oracle_in_pool": [False, False, False],
            "pool_recall": 0.0,
        },
    ]
    metrics = selector_search.evaluate_selector_metrics(
        samples, (1.0, 0.0, 0.0, 0.0, 0.0))
    self.assertEqual(0.5, metrics["PoolRecall@B"])
    self.assertEqual(0.5, metrics["SelectorRecall@K"])
    self.assertEqual(0.5, metrics["EndToEndRecall@K"])
    self.assertEqual(0.25, metrics["TieCoverage@K"])
    self.assertEqual(0.5, metrics["NRegret"])


class FutureSplitAndSnapshotTest(unittest.TestCase):

  def test_future_window_boundary_and_exact_label(self):
    trace = [
        {"page": 1, "pc": 1, "rw": 0},
        {"page": 2, "pc": 2, "rw": 0},
        {"page": 1, "pc": 3, "rw": 0},
        {"page": 3, "pc": 4, "rw": 0},
        {"page": 1, "pc": 5, "rw": 1},
    ]
    self.assertTrue(has_complete_future_window(2, 2, 5))
    self.assertFalse(has_complete_future_window(3, 2, 5))
    oracle = FutureOracle(trace, 2)
    labels = reference_labels(trace, 2, 1, 2, oracle)
    self.assertEqual(1.0, labels["inactivity"])
    self.assertEqual(0.5, labels["coldness"])
    self.assertEqual(0.5, labels["write_intensity"])
    self.assertEqual(-0.5, labels["relevance"])
    with self.assertRaises(ValueError):
      oracle.stats(3, 1)

  def test_official_sources_are_independent_and_holdout_is_smoke_only(self):
    official = resolved_v3()
    self.assertEqual("independent_valid_trace",
                     official["validation"]["strategy"])
    finals_config.assert_independent_trace_sources(official)
    overlap = copy.deepcopy(official)
    overlap["data"]["valid_trace"] = overlap["data"]["train_trace"]
    with self.assertRaises(ValueError):
      finals_config.assert_independent_trace_sources(overlap)
    with self.assertRaises(ValueError):
      finals_config.assert_independent_trace_sources(official, {
          "train_trace": "same", "valid_trace": "same",
          "test_trace": "different",
      })

    base_path = os.path.join(
        PROJECT_ROOT, "configs", "finals", "capd_direction1_v3.json")
    smoke_base = finals_config.load_config(base_path)
    smoke_base["run_profile"] = "smoke"
    smoke_base["validation"]["strategy"] = "train_trace_decision_holdout"
    smoke_base["validation"]["artifact_class"] = "smoke_only"
    smoke = finals_config.resolve_config(smoke_base, "canneal", 64)
    smoke_artifact = finals_config.artifact_identity_from_config(smoke)
    official_artifact = finals_config.artifact_identity_from_config(official)
    with self.assertRaises(ValueError):
      finals_config.validate_artifact_identity(
          official, smoke_artifact, "official aggregator")
    with self.assertRaises(ValueError):
      finals_config.validate_artifact_identity(
          smoke, official_artifact, "smoke loader")

  def test_triggering_request_only_enters_reranker_history(self):
    config = {
        "memory": {"dram_capacity_pages": 3},
        "candidate": {"pool_size_B": 3, "retained_K": 2,
                      "selector_history_Hc": 8},
        "history": {"transformer_H": 3},
        "features": {"residency_scale_Lres": 16},
    }
    params = {
        "c_Delta": 8.0, "c_A": 2.0, "c_W": 1.0,
        "w_Delta": 0.2, "w_A": 0.2, "w_W": 0.2,
        "w_C": 0.2, "w_R": 0.2,
    }
    state = LRUBehaviorState(config)
    for index, page in enumerate((1, 2, 3)):
      state.advance({"page": page, "pc": 10 + page, "rw": 0}, index)
    current = {"page": 4, "pc": 99, "rw": 1}
    selector_length_before = len(state.selector_history)
    history = state.decision_history(current)
    snapshot = build_generator_decision_snapshot(
        state, current, 3, config, params)
    self.assertEqual(4, history[-1]["page"])
    self.assertEqual(selector_length_before, len(state.selector_history))
    self.assertEqual(0, state.selector_history.access_count(4))
    self.assertNotIn(4, snapshot["P_t"])


class ReplayAccountingTest(unittest.TestCase):

  def test_first_read_write_hit_nvm_revisit_and_demotion_costs(self):
    rows = [
        (1, 1, 0),
        (2, 1, 0),
        (3, 2, 1),
        (4, 3, 0),
        (5, 1, 0),
    ]
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "trace.csv")
      with open(path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["PC", "Address", "RW"])
        writer.writerows(rows)
      stats = qmap_eval.replay(replay_args(path))
    self.assertEqual(5, stats.total_accesses)
    self.assertEqual(1, stats.hit_count)
    self.assertEqual(4, stats.miss_count)
    self.assertEqual(3, stats.nvm_read_count)
    self.assertEqual(1, stats.nvm_write_count)
    self.assertEqual(2, stats.migration_count)
    # 2 + 1 + 8 + (2+10) + (2+10) = 35. Dirty demotion adds no write.
    self.assertEqual(35.0, stats.weighted_access_cost)


class ArtifactIdentityTest(unittest.TestCase):

  def test_checkpoint_contract_config_workload_selector_mismatches_hard_fail(self):
    config = resolved_v3()
    selector = selector_for(config)
    checkpoint = checkpoint_for(config, selector)
    qmap_eval.validate_checkpoint_config_contract(
        checkpoint, config, selector)
    mutations = (
        ("schema_version", "capd_finals_v2_1"),
        ("contract_id", "CAPD-MIC-OTHER"),
        ("config_fingerprint", "wrong-config"),
        ("workload_id", "other-workload"),
        ("selector_fingerprint", "wrong-selector"),
    )
    for field, value in mutations:
      with self.subTest(field=field):
        broken = copy.deepcopy(checkpoint)
        broken[field] = value
        with self.assertRaises(ValueError):
          qmap_eval.validate_checkpoint_config_contract(
              broken, config, selector)
    broken_contract = copy.deepcopy(checkpoint)
    broken_contract["experiment_contract"]["L"] += 1
    with self.assertRaises(ValueError):
      qmap_eval.validate_checkpoint_config_contract(
          broken_contract, config, selector)
    smoke_checkpoint = copy.deepcopy(checkpoint)
    smoke_checkpoint["decision_holdout"] = {"strategy": "smoke"}
    with self.assertRaises(ValueError):
      qmap_eval.validate_checkpoint_config_contract(
          smoke_checkpoint, config, selector)

  def test_jsonl_metadata_and_result_mismatches_hard_fail(self):
    config = resolved_v3()
    # Stage-1 contract tests must not depend on stage-2 official traces having
    # already been materialized.  Use a local fixture for fingerprint checks.
    trace_directory = tempfile.TemporaryDirectory()
    self.addCleanup(trace_directory.cleanup)
    test_trace = os.path.join(trace_directory.name, "test_trace.csv")
    with open(test_trace, "w", encoding="utf-8") as output_file:
      output_file.write("PC,Address,RW\n0x1,0x1000,R\n")
    config["data"]["test_trace"] = test_trace
    selector = selector_for(config)
    with tempfile.TemporaryDirectory() as directory:
      jsonl_path = os.path.join(directory, "train.jsonl")
      with open(jsonl_path, "w", encoding="utf-8") as output_file:
        output_file.write("{}\n")
      metadata = finals_config.artifact_identity_from_config(config)
      metadata.update({
          "split": "train",
          "data_fingerprint": finals_config.fingerprint_file(jsonl_path),
          "experiment_contract": finals_config.contract_from_config(config),
          "selector_fingerprint": finals_config.selector_fingerprint(selector),
      })
      finals_config.write_json(
          finals_config.metadata_path(jsonl_path), metadata)
      finals_config.load_jsonl_metadata(
          jsonl_path, config=config, split="train",
          selector_params=selector)
      for field, value in (
          ("schema_version", "capd_finals_v2_1"),
          ("contract_id", "wrong-contract"),
          ("workload_id", "wrong-workload"),
          ("config_fingerprint", "wrong-config"),
          ("selector_fingerprint", "wrong-selector")):
        with self.subTest(jsonl_metadata_field=field):
          broken_metadata = copy.deepcopy(metadata)
          broken_metadata[field] = value
          finals_config.write_json(
              finals_config.metadata_path(jsonl_path), broken_metadata)
          with self.assertRaises(ValueError):
            finals_config.load_jsonl_metadata(
                jsonl_path, config=config, split="train",
                selector_params=selector)

    result = finals_config.artifact_identity_from_config(config)
    result.update({
        "policy": "qmap",
        "experiment_contract": finals_config.contract_from_config(config),
        "selector_fingerprint": finals_config.selector_fingerprint(selector),
        "checkpoint_fingerprint": "checkpoint",
        "total_accesses": 5,
        "hits": 1,
        "misses": 4,
        "nvm_reads": 3,
        "nvm_writes": 1,
        "migrations": 2,
        "weighted_access_cost": 35.0,
        "test_trace_fingerprint": finals_config.fingerprint_file(
            config["data"]["test_trace"]),
        "cost_model": copy.deepcopy(config["cost_model"]),
        "nvm_capacity_pages": None,
        "dram_initial_state": "empty",
        "initial_residency": "all_trace_pages_in_nvm",
        "trace_page_backing": "all_trace_pages",
        "first_touch_accounting": "nvm_access",
        "dirty_demotion_nvm_write": "none",
        "candidate_coverage_validation": {
            key: selector[key] for key in (
                "PoolRecall@B", "SelectorRecall@K", "EndToEndRecall@K",
                "TieCoverage@K", "NRegret")
        },
        "candidate_coverage_metric_source": "valid_trace",
    })
    finals_config.validate_result_contract(
        config, result, selector, checkpoint_fingerprint="checkpoint")
    result["checkpoint_fingerprint"] = "wrong"
    with self.assertRaises(ValueError):
      finals_config.validate_result_contract(
          config, result, selector, checkpoint_fingerprint="checkpoint")
    broken_trace = copy.deepcopy(result)
    broken_trace["checkpoint_fingerprint"] = "checkpoint"
    broken_trace["test_trace_fingerprint"] = "wrong-test-trace"
    with self.assertRaises(ValueError):
      finals_config.validate_result_contract(
          config, broken_trace, selector,
          checkpoint_fingerprint="checkpoint")
    broken_coverage = copy.deepcopy(result)
    broken_coverage["checkpoint_fingerprint"] = "checkpoint"
    broken_coverage["candidate_coverage_validation"]["NRegret"] += 0.1
    with self.assertRaises(ValueError):
      finals_config.validate_result_contract(
          config, broken_coverage, selector,
          checkpoint_fingerprint="checkpoint")

  def test_v2_and_v3_artifacts_are_mutually_incompatible(self):
    v3 = resolved_v3()
    v3_artifact = finals_config.artifact_identity_from_config(v3)
    legacy_path = os.path.join(
        PROJECT_ROOT, "configs", "finals", "capd_direction1.json")
    legacy = finals_config.resolve_config(
        finals_config.load_config(legacy_path), "canneal", 64)
    legacy_artifact = finals_config.artifact_identity_from_config(legacy)
    with self.assertRaises(ValueError):
      finals_config.validate_artifact_identity(
          legacy, v3_artifact, "legacy loader")
    with self.assertRaises(ValueError):
      finals_config.validate_artifact_identity(
          v3, legacy_artifact, "v3 loader")


if __name__ == "__main__":
  unittest.main()
