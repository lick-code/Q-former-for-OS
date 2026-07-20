# coding=utf-8
"""Synthetic deterministic tests for the CAPD stage-2 data contract.

These tests are written for the Linux validation server and are not executed
locally by Codex.
"""

import copy
import csv
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data


def write_trace(path, rows, include_rw=True):
  with open(path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(("PC", "Address", "RW") if include_rw else
                    ("PC", "Address"))
    for pc, address, rw in rows:
      writer.writerow((pc, address, rw) if include_rw else (pc, address))


def source_spec(source, split_paths, intervals, workload="synthetic"):
  return {
      "schema_version": finals_data.SOURCE_SPEC_SCHEMA,
      "contract_id": finals_data.CONTRACT_ID,
      "workload_id": workload,
      "page_shift": 0,
      "rw_source": {
          "kind": "trace_column", "column": "RW", "verified_real": True,
      },
      "split_strategy": "synthetic chronological half-open intervals",
      "collections": [{
          "collection_id": "capture-1",
          "source_trace": source,
          "tool": "synthetic-test-fixture",
          "command": "unit-test fixture construction",
          "source_label": "deterministic fixture",
          "provenance_complete": True,
      }],
      "splits": {
          name: {
              "path": split_paths[name],
              "collection_id": "capture-1",
              "source_access_interval": {
                  "start_inclusive": intervals[name][0],
                  "end_exclusive": intervals[name][1],
              },
          } for name in finals_data.REQUIRED_SPLITS
      },
  }


def build_fixture(directory, rows, intervals, workload="synthetic"):
  source = os.path.join(directory, "source.csv")
  write_trace(source, rows)
  split_paths = {}
  for name in finals_data.REQUIRED_SPLITS:
    start, end = intervals[name]
    split_paths[name] = os.path.join(directory, "{}.csv".format(name))
    write_trace(split_paths[name], rows[start:end])
  spec = source_spec(source, split_paths, intervals, workload=workload)
  manifest = finals_data.build_source_manifest(
      spec, directory, "test-commit")
  manifest_path = os.path.join(directory, "manifest.json")
  finals_data.write_json(manifest_path, manifest)
  return manifest_path, manifest


def audit_config(workload="synthetic", manifest=None):
  config = {
      "schema_version": "capd_finals_v3_0",
      "contract": {"id": "CAPD-MIC-1.0"},
      "trace": {"page_shift": 0},
      "memory": {"dram_capacity_pages": 2},
      "candidate": {"retained_K": 1, "selector_history_Hc": 2},
      "history": {"transformer_H": 2},
      "labels": {"future_lookahead_L": 2},
      "selector": {"epsilon_y": 1e-8},
      "sweep": {"pool_sizes_B": [1, 2]},
      "embedding": {
          "page": {"max_vocab_size": 100},
          "pc": {"max_vocab_size": 100},
      },
      "workloads": {workload: {}},
  }
  if manifest is not None:
    config["workloads"][workload] = {
        "{}_trace".format(split): manifest["splits"][split]["path"]
        for split in finals_data.REQUIRED_SPLITS
    }
  return config


def audit_profile():
  return {
      "profile_id": "synthetic-stage2-profile",
      "artifact_schema": "capd_finals_v3_0",
      "contract_id": "CAPD-MIC-1.0",
      "method_constants": {
          "D": 2, "K": 1, "H": 2, "Hc": 2, "L": 2,
          "pool_sizes_B": [1, 2],
      },
      "split_thresholds": {
          "train": {
              "min_accesses": 6, "min_victim_decisions": 1,
              "min_complete_window_decisions": 1,
              "min_effective_label_decisions": 1,
          },
          "valid": {
              "min_accesses": 6, "min_victim_decisions": 1,
              "min_complete_window_decisions": 1,
              "min_effective_label_decisions": 1,
          },
          "test": {"min_accesses": 6, "min_victim_decisions": 1},
      },
      "distribution_thresholds": {
          "max_nondiscriminative_ratio": 1.0,
          "min_reuse_event_ratio": 0.01,
          "max_top_1_percent_page_share": 0.99,
          "extreme_write_ratio_low": 0.01,
          "extreme_write_ratio_high": 0.99,
      },
      "drift_thresholds": {
          "max_write_ratio_span": 1.0,
          "max_decision_ratio_span": 1.0,
          "max_top_1_percent_page_share_span": 1.0,
      },
      "drift_action": "warning",
  }


class SourceManifestTest(unittest.TestCase):

  def test_distinct_collection_ids_may_repeat_values_and_interval_numbers(self):
    splits = {
        split: {
            "collection_id": "capture-{}".format(split),
            "source_access_interval": {
                "start_inclusive": 0, "end_exclusive": 6,
            },
        } for split in finals_data.REQUIRED_SPLITS
    }
    evidence = finals_data.assert_source_intervals_independent(splits)
    self.assertEqual(3, len(evidence))
    self.assertTrue(all(
        item["proof"] == "distinct_collection_id" for item in evidence))

  def test_nonoverlap_and_content_chain_are_verified(self):
    rows = [(index, (index % 4) + 1, index % 2) for index in range(18)]
    intervals = {"train": (0, 6), "valid": (6, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      manifest_path, manifest = build_fixture(directory, rows, intervals)
      result = finals_data.validate_source_manifest(
          manifest, directory, verify_files=True)
      self.assertEqual("synthetic", result["workload_id"])
      self.assertEqual(
          finals_data.fingerprint_file(manifest_path),
          finals_data.fingerprint_file(manifest_path))

  def test_source_interval_overlap_fails_even_when_paths_differ(self):
    rows = [(index, index + 1, index % 2) for index in range(18)]
    intervals = {"train": (0, 8), "valid": (7, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "source.csv")
      write_trace(source, rows)
      split_paths = {}
      for name, (start, end) in intervals.items():
        split_paths[name] = os.path.join(directory, name + ".csv")
        write_trace(split_paths[name], rows[start:end])
      spec = source_spec(source, split_paths, intervals)
      with self.assertRaises(ValueError):
        finals_data.build_source_manifest(spec, directory, "test-commit")

  def test_missing_real_rw_fails_for_official_data(self):
    rows = [(index, index + 1, 0) for index in range(18)]
    intervals = {"train": (0, 6), "valid": (6, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "source.csv")
      write_trace(source, rows, include_rw=False)
      split_paths = {}
      for name, (start, end) in intervals.items():
        split_paths[name] = os.path.join(directory, name + ".csv")
        write_trace(split_paths[name], rows[start:end], include_rw=False)
      with self.assertRaises(ValueError):
        finals_data.build_source_manifest(
            source_spec(source, split_paths, intervals), directory,
            "test-commit")

  def test_manifest_or_split_fingerprint_mismatch_hard_fails(self):
    rows = [(index, (index % 4) + 1, index % 2) for index in range(18)]
    intervals = {"train": (0, 6), "valid": (6, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      _, manifest = build_fixture(directory, rows, intervals)
      broken = copy.deepcopy(manifest)
      broken["splits"]["valid"]["fingerprint_sha256"] = "wrong"
      broken["content_fingerprint"] = finals_data.fingerprint_value(
          finals_data._manifest_payload(broken))
      with self.assertRaises(ValueError):
        finals_data.validate_source_manifest(
            broken, directory, verify_files=True)

  def test_passed_report_is_sealed_and_report_tampering_hard_fails(self):
    train = [(10 + i, page, i % 2)
             for i, page in enumerate((1, 2, 3, 1, 2, 3))]
    valid = [(20 + i, page, i % 2)
             for i, page in enumerate((2, 4, 5, 2, 4, 5))]
    test = [(30 + i, page, i % 2)
            for i, page in enumerate((1, 6, 7, 1, 6, 7))]
    rows = train + valid + test
    intervals = {"train": (0, 6), "valid": (6, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      manifest_path, manifest = build_fixture(directory, rows, intervals)
      report = finals_data.audit_source_manifest(
          manifest_path, directory, audit_config(manifest=manifest),
          audit_profile())
      self.assertEqual("PASSED", report["status"])
      report_path = os.path.join(directory, "audit.json")
      finals_data.write_json(report_path, report)
      finals_data.update_manifest_quality_gate(
          manifest_path, report_path, directory, report)
      finals_data.load_source_manifest(
          manifest_path, directory, verify_files=True,
          require_quality_pass=True)
      report["warnings"].append("tampered")
      finals_data.write_json(report_path, report)
      with self.assertRaises(ValueError):
        finals_data.load_source_manifest(
            manifest_path, directory, verify_files=True,
            require_quality_pass=True)


class AuditMetricsTest(unittest.TestCase):

  def test_future_boundary_and_complete_window_count_are_exact(self):
    metrics = finals_data.replay_quality_metrics(
        pages=[1, 2, 3, 4, 5], rws=[0, 0, 0, 0, 0],
        dram_capacity=2, lookahead=2, pool_sizes=[1, 2],
        retained_k=1, epsilon_y=1e-8)
    self.assertEqual(3, metrics["victim_decision_count"])
    # Decision t=2 has t+L=N-1 and is valid; t=3 and t=4 are dropped.
    self.assertEqual(1, metrics["complete_future_window_decision_count"])
    self.assertEqual(2, metrics["tail_dropped_decision_count"])

  def test_short_low_pressure_and_no_decision_are_diagnosed(self):
    rows = [(index, 1 + (index % 2), 0) for index in range(4)]
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "short.csv")
      write_trace(path, rows)
      constants = {
          "D": 2, "K": 1, "L": 2, "pool_sizes_B": [1, 2],
          "epsilon_y": 1e-8,
      }
      metrics, _, _, _, _ = finals_data.analyze_trace(path, 0, constants)
      failures, _ = finals_data._diagnose_split(
          "valid", metrics, audit_profile(), constants)
      self.assertIn(
          "trace_too_short_for_fill_and_complete_future_window", failures)
      self.assertIn("unique_pages_not_greater_than_D", failures)
      self.assertIn("victim_decisions_below_profile_minimum", failures)

  def test_streaming_and_extreme_write_are_diagnosed(self):
    rows = [(index, index + 1, 1) for index in range(8)]
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "stream.csv")
      write_trace(path, rows)
      constants = {
          "D": 2, "K": 1, "L": 2, "pool_sizes_B": [1, 2],
          "epsilon_y": 1e-8,
      }
      metrics, _, _, _, _ = finals_data.analyze_trace(path, 0, constants)
      _, warnings = finals_data._diagnose_split(
          "test", metrics, audit_profile(), constants)
      self.assertIn("near_streaming_or_no_reuse", warnings)
      self.assertIn("extreme_write_ratio", warnings)

  def test_report_fields_are_complete_deterministic_and_oov_is_correct(self):
    train = [(10 + i, page, i % 2)
             for i, page in enumerate((1, 2, 3, 1, 2, 3))]
    valid = [(20 + i, page, i % 2)
             for i, page in enumerate((2, 4, 5, 2, 4, 5))]
    test = [(30 + i, page, i % 2)
            for i, page in enumerate((1, 6, 7, 1, 6, 7))]
    rows = train + valid + test
    intervals = {"train": (0, 6), "valid": (6, 12), "test": (12, 18)}
    with tempfile.TemporaryDirectory() as directory:
      manifest_path, manifest = build_fixture(directory, rows, intervals)
      first = finals_data.audit_source_manifest(
          manifest_path, directory, audit_config(manifest=manifest),
          audit_profile())
      second = finals_data.audit_source_manifest(
          manifest_path, directory, audit_config(manifest=manifest),
          audit_profile())
      self.assertEqual(first, second)
      self.assertEqual(first["audit_fingerprint"],
                       second["audit_fingerprint"])
      for split in finals_data.REQUIRED_SPLITS:
        self.assertEqual(
            {"basic", "read_write", "dram_pressure_and_labels",
             "hotspot_and_tail", "diagnostics"},
            set(first["splits"][split]))
      valid_page_oov = first["cross_split"]["vocabulary_risk"]["oov"][
          "valid"]["page"]
      self.assertEqual(4, valid_page_oov["access_oov_count"])
      self.assertAlmostEqual(4.0 / 6.0, valid_page_oov["access_oov_ratio"])


class ArtifactBindingTest(unittest.TestCase):

  def test_jsonl_content_fingerprint_mismatch_is_rejected(self):
    with tempfile.TemporaryDirectory() as directory:
      jsonl_path = os.path.join(directory, "train.jsonl")
      with open(jsonl_path, "w", encoding="utf-8") as output_file:
        output_file.write("{}\n")
      finals_config.write_json(
          finals_config.metadata_path(jsonl_path), {
              "data_fingerprint": finals_config.fingerprint_file(jsonl_path),
          })
      finals_config.load_jsonl_metadata(jsonl_path)
      with open(jsonl_path, "a", encoding="utf-8") as output_file:
        output_file.write("{}\n")
      with self.assertRaises(ValueError):
        finals_config.load_jsonl_metadata(jsonl_path)

  def test_v2_and_unbound_or_mismatched_v3_artifacts_are_rejected(self):
    binding = {
        "source_manifest_fingerprint": "manifest-sha",
        "split_fingerprints": {
            "train": "train-sha", "valid": "valid-sha", "test": "test-sha",
        },
        "data_quality_profile_id": "profile-v1",
        "data_quality_profile_fingerprint": "profile-sha",
        "data_quality_report_fingerprint": "report-sha",
    }
    v3 = {"schema_version": "capd_finals_v3_0"}
    v3.update(copy.deepcopy(binding))
    finals_data.validate_artifact_binding(binding, v3, "v3 JSONL")
    with self.assertRaises(ValueError):
      finals_data.validate_artifact_binding(
          binding, {"schema_version": "capd_finals_v2_1"}, "v2 JSONL")
    broken = copy.deepcopy(v3)
    broken["split_fingerprints"]["valid"] = "wrong"
    with self.assertRaises(ValueError):
      finals_data.validate_artifact_binding(binding, broken, "v3 JSONL")
    broken = copy.deepcopy(v3)
    broken["source_manifest_fingerprint"] = "wrong"
    with self.assertRaises(ValueError):
      finals_data.validate_artifact_binding(binding, broken, "v3 JSONL")


if __name__ == "__main__":
  unittest.main()
