# coding=utf-8

import copy
import json
import os
import tempfile
import unittest

from qmap import proactive_replay
from qmap import proactive_stage4


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))


def load(path):
  with open(os.path.join(PROJECT_ROOT, path), "r", encoding="utf-8") as source:
    return json.load(source)


class ProactiveStage4ContractTest(unittest.TestCase):

  def setUp(self):
    self.config = load("configs/finals/capd_proactive_stage4.json")
    self.stage0 = load("configs/finals/capd_proactive_stage0.json")
    self.stage3 = load(
        "configs/finals/capd_proactive_stage3_engineering_default.json")

  def test_authority_config_is_valid(self):
    proactive_stage4.validate_config(
        self.config, self.stage0, self.stage3)

  def test_stage3_values_cannot_change(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_stage3"]["F_low"] = 1
    with self.assertRaisesRegex(
        proactive_stage4.Stage4ContractError, "Stage-3 frozen"):
      proactive_stage4.validate_config(
          changed, self.stage0, self.stage3)

  def test_selector_cannot_be_enabled(self):
    changed = copy.deepcopy(self.config)
    changed["frozen_stage3"]["selector"] = "enabled"
    with self.assertRaises(proactive_stage4.Stage4ContractError):
      proactive_stage4.validate_config(
          changed, self.stage0, self.stage3)

  def test_k_less_than_or_equal_to_bmax_is_rejected(self):
    changed = copy.deepcopy(self.config)
    changed["grid"]["candidate_size_K"] = [4, 8]
    with self.assertRaisesRegex(
        proactive_stage4.Stage4ContractError, "K grid"):
      proactive_stage4.validate_config(
          changed, self.stage0, self.stage3)
    with self.assertRaisesRegex(
        proactive_replay.ReplayConfigurationError, "b_max < K"):
      proactive_replay.ReplayParameters(
          policy_name="capd", dram_capacity_pages=10,
          F_low=2, F_target=4, b_max=4, candidate_size_K=4)


class ProactiveStage4ManifestTest(unittest.TestCase):

  def _entry(self, workload, split, path, digest, source, start, end):
    return {
        "workload": workload,
        "split": split,
        "role": (
            "training_and_fit" if split == "train"
            else "parameter_selection"),
        "trace_path": path,
        "trace_sha256": digest,
        "page_shift": 12,
        "source_kind": "raw_access_trace",
        "formal_test": False,
        "source_trace_id": source,
        "source_interval": {"start": start, "end": end},
    }

  def test_test_and_overlapping_intervals_are_rejected(self):
    digest_a = "a" * 64
    digest_b = "b" * 64
    train = self._entry(
        "w", "train", "train.csv", digest_a, "capture", 0, 10)
    valid = self._entry(
        "w", "validation", "valid.csv", digest_b, "capture", 9, 20)
    manifest = {
        "schema_version": proactive_stage4.MANIFEST_SCHEMA,
        "contract_id": proactive_stage4.CONTRACT_ID,
        "path_base": "project_root",
        "test_used_for_parameter_selection": False,
        "split_non_overlap_attested": True,
        "entries": [train, valid],
    }
    with self.assertRaisesRegex(
        proactive_stage4.Stage4ContractError, "overlap"):
      proactive_stage4.validate_manifest(manifest)
    valid["source_interval"] = {"start": 10, "end": 20}
    proactive_stage4.validate_manifest(manifest)
    valid["split"] = "test"
    valid["role"] = "parameter_selection"
    with self.assertRaisesRegex(
        proactive_stage4.Stage4ContractError, "Train/Validation"):
      proactive_stage4.validate_manifest(manifest)

  def test_test_named_path_is_rejected(self):
    train = self._entry(
        "w", "train", "workload_test.csv", "a" * 64, "a", 0, 1)
    valid = self._entry(
        "w", "validation", "valid.csv", "b" * 64, "b", 0, 1)
    manifest = {
        "schema_version": proactive_stage4.MANIFEST_SCHEMA,
        "contract_id": proactive_stage4.CONTRACT_ID,
        "path_base": "project_root",
        "test_used_for_parameter_selection": False,
        "split_non_overlap_attested": True,
        "entries": [train, valid],
    }
    with self.assertRaisesRegex(
        proactive_stage4.Stage4ContractError, "Test artifact"):
      proactive_stage4.validate_manifest(manifest)

  def test_resolved_sha_and_distinct_content_are_enforced(self):
    with tempfile.TemporaryDirectory() as directory:
      train = os.path.join(directory, "train.csv")
      valid = os.path.join(directory, "valid.csv")
      with open(train, "w", encoding="utf-8") as output:
        output.write("1,4096,0\n")
      with open(valid, "w", encoding="utf-8") as output:
        output.write("2,8192,1\n")
      entries = [
          self._entry(
              "w", "train", train,
              proactive_stage4.fingerprint_file(train), "train-capture", 0, 1),
          self._entry(
              "w", "validation", valid,
              proactive_stage4.fingerprint_file(valid), "valid-capture", 0, 1),
      ]
      manifest = {
          "schema_version": proactive_stage4.MANIFEST_SCHEMA,
          "contract_id": proactive_stage4.CONTRACT_ID,
          "path_base": "project_root",
          "test_used_for_parameter_selection": False,
          "split_non_overlap_attested": True,
          "entries": entries,
      }
      path = os.path.join(directory, "manifest.json")
      proactive_stage4.write_json_atomic(path, manifest)
      _, traces, resolved = proactive_stage4.resolve_inputs(
          path, PROJECT_ROOT)
      self.assertEqual(len(traces["w"]["train"]), 1)
      self.assertEqual(len(resolved), 2)
      entries[1]["trace_sha256"] = entries[0]["trace_sha256"]
      proactive_stage4.write_json_atomic(path, manifest)
      with self.assertRaisesRegex(
          proactive_stage4.Stage4ContractError, "SHA-256 mismatch"):
        proactive_stage4.resolve_inputs(path, PROJECT_ROOT)


class ProactiveStage4LabelAndMetricTest(unittest.TestCase):

  def test_all_six_weight_formulas_and_relabel(self):
    components = {"d_hat": 0.5, "q_hat": 0.25, "w_hat": 0.125}
    expected = [0.625, 0.5, 0.25, -0.25, 0.5, 0.75]
    actual = [
        proactive_stage4.composite_label(components, weights)
        for weights in proactive_stage4.LABEL_WEIGHT_GRID]
    self.assertEqual(actual, expected)
    sample = {
        "label_components": [components, components],
        "candidate_mask": [1, 0],
        "ranking_label": [999, 999],
    }
    changed = proactive_stage4.relabel_sample(sample, (1, 1, 8))
    self.assertEqual(changed["ranking_label"], [-0.25, 0.0])
    self.assertEqual(sample["ranking_label"], [999, 999])

  def test_incomplete_and_empty_future_windows_are_explicit(self):
    trace = [
        {"page": 1, "rw": 0, "pc": 1},
        {"page": 2, "rw": 1, "pc": 2},
    ]
    tail = proactive_stage4.label_components(trace, 0, 2, 4)
    self.assertFalse(tail["complete_future_window"])
    self.assertEqual(tail["effective_lookahead"], 1)
    empty = proactive_stage4.label_components(trace, 1, 2, 4)
    self.assertFalse(empty["complete_future_window"])
    self.assertEqual(empty["effective_lookahead"], 0)
    self.assertTrue(empty["no_future_reuse"])

  def test_variable_top_b_metrics_ties_and_short_candidates(self):
    tied = proactive_stage4.variable_top_b_metrics(
        [0.2, 0.1], [1.0, 1.0], 4)
    self.assertEqual(tied["effective_b_t"], 2)
    self.assertEqual(tied["ndcg_at_b_t"], 1.0)
    self.assertEqual(tied["top_b_t_overlap"], 1.0)
    self.assertEqual(tied["top_b_t_regret"], 0.0)
    self.assertEqual(tied["oracle_set_size"], 2)
    self.assertTrue(tied["all_labels_tied"])
    ranked = proactive_stage4.variable_top_b_metrics(
        [0.1, 0.9, 0.2], [3.0, 1.0, 2.0], 2)
    self.assertGreater(ranked["top_b_t_regret"], 0.0)
    self.assertGreaterEqual(ranked["ndcg_at_1"], 0.0)
    self.assertLessEqual(ranked["ndcg_at_1"], 1.0)


class ProactiveStage4TrajectoryTest(unittest.TestCase):

  def test_multi_round_samples_rebuild_after_state_updates(self):
    stage0 = load("configs/finals/capd_proactive_stage0.json")
    trace = [
        {"page": page, "rw": page % 2, "pc": page + 100}
        for page in range(1, 40)]
    ranker = proactive_stage4.TrainingSampleRanking(
        trace, "synthetic", "train", lookahead=5, history_H=5,
        candidate_K=8, weights=(1, 1, 4),
        experiment_id="synthetic")
    parameters = proactive_replay.ReplayParameters(
        policy_name="capd", dram_capacity_pages=12,
        F_low=2, F_target=6, b_max=2, candidate_size_K=8,
        history_window_size=5, early_reuse_window=4)
    replay = proactive_replay.ProactiveReplay(
        stage0, parameters, ranking_policy=ranker,
        invariant_mode="full", record_details=True)
    result = replay.run(trace)
    multi = [
        cycle for cycle in result["cycles"]
        if cycle["number_of_rounds"] > 1]
    self.assertTrue(multi)
    for cycle in multi:
      rows = [
          row for row in result["rounds"]
          if row["cycle_id"] == cycle["cycle_id"]]
      for before, after in zip(rows, rows[1:]):
        self.assertNotEqual(
            before["candidate_pages"], after["candidate_pages"])
        self.assertEqual(before["F_after"], after["F_before"])
    event_types = [event["event_type"] for event in result["events"]]
    self.assertEqual(
        result["summary"]["emergency_demotions"],
        event_types.count(proactive_replay.EMERGENCY_DEMOTION))
    self.assertEqual(
        result["summary"]["proactive_demotions"],
        event_types.count(proactive_replay.PROACTIVE_DEMOTION))


class ProactiveStage4SelectionTest(unittest.TestCase):

  def _candidate(self, identity, cost, write, ndcg, complexity):
    rows = []
    for workload in ("a", "b"):
      for seed in proactive_stage4.SEEDS:
        rows.append({
            "workload": workload, "seed": seed,
            "weighted_cost_per_access": cost,
            "nvm_writes": write,
            "dram_hits": 10, "nvm_reads": 1,
            "total_demotions": 1, "proactive_demotions": 1,
            "emergency_fallback_rate": 0.0, "exhaustion_rate": 0.0,
            "early_reuse_rate": 0.0, "proactive_cycle_count": 1,
            "proactive_round_count": 1, "ndcg_at_1": ndcg,
            "ndcg_at_b_t": ndcg, "top_b_t_overlap": ndcg,
            "top_b_t_regret": 1.0 - ndcg,
            "amortized_latency_per_page_seconds": 0.1,
        })
    return {
        "experiment_id": identity,
        "complexity_rank": complexity,
        "rows": rows,
        "aggregate": proactive_stage4.aggregate_metric_rows(rows),
    }

  def test_selection_is_global_and_deterministic(self):
    reference = self._candidate("reference", 1.0, 10, 0.8, [1])
    simpler = self._candidate("simpler", 1.005, 10, 0.9, [0])
    rule = load(
        "configs/finals/capd_proactive_stage4.json")["selection_rule"]
    decision = proactive_stage4.select_global_candidate(
        [reference, simpler], "reference", rule)
    # The global worst-workload guard precedes ranking/complexity tie-breaks.
    self.assertEqual(decision["selected_experiment_id"], "reference")
    self.assertFalse(decision["test_used"])


if __name__ == "__main__":
  unittest.main()
