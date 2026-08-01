# coding=utf-8
"""Local R1-R4 contracts for the Stage-7 repair workflow."""

from __future__ import annotations

import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

from qmap import proactive_stage7_repair as repair


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage7_repair.json")


def write_trace(path, pages, writes=None):
  writes = writes or set()
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(("PID", "TID", "PC", "Address", "RW"))
    for index, page in enumerate(pages):
      writer.writerow((
          7, 7, hex(0x1000 + index), hex(page << 12),
          "W" if index in writes else "R"))


def candidate(start, decisions, unique_pages, capacity=64):
  return {
      "workload": "w",
      "requested_ratio": "0.20",
      "D_base": 20,
      "D_guarded": capacity,
      "effective_ratio": 0.64,
      "source_start_inclusive": start,
      "source_end_exclusive": start + 100,
      "unique_pages": unique_pages,
      "misses": decisions + capacity,
      "lru_replacement_decisions": decisions,
      "write_ratio": 0.25,
      "page_entry_count": decisions + capacity,
  }


class RepairConfigTest(unittest.TestCase):

  def test_cli_exposes_only_local_prepare_commands(self):
    script = os.path.join(
        PROJECT_ROOT, "scripts", "run_capd_proactive_stage7_repair.py")
    completed = subprocess.run(
        [sys.executable, script, "--help"], cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, check=False)
    self.assertEqual(0, completed.returncode, completed.stdout)
    for command in (
        "local-prepare", "preflight", "scan-pressure",
        "export-local-bundle", "verify-local-bundle"):
      self.assertIn(command, completed.stdout)
    for forbidden in ("build-training-manifest", "train", "freeze", "replay"):
      self.assertNotIn(forbidden, completed.stdout)

  def test_fixed_local_contract(self):
    value = repair.load_json(CONFIG_PATH)
    repair.validate_repair_config(value)
    self.assertEqual("pending_stage3_stage4_parameter_reselection",
                     value["parameter_status"])
    self.assertFalse(value["formal_freeze_allowed"])
    self.assertNotIn("fixed_parameters", value)
    self.assertEqual(8, value["candidate_parameters_snapshot"]["F_low"])
    self.assertEqual(16, value["candidate_parameters_snapshot"]["F_target"])
    self.assertEqual(0.25, value["capacity"]["reserve_fraction_cap"])
    self.assertEqual([2400000, 3000000], value["pressure_scan"]["test_interval"])
    self.assertEqual(100000, value["pressure_scan"]["window_records"])
    self.assertEqual(10000, value["pressure_scan"]["scan_step"])
    self.assertFalse(value["pressure_overhead_claims_allowed"])

  def test_changed_fixed_parameter_is_rejected(self):
    value = repair.load_json(CONFIG_PATH)
    value["candidate_parameters_snapshot"]["F_target"] = 15
    with self.assertRaises(repair.Stage7RepairError):
      repair.validate_repair_config(value)

  def test_pending_parameters_block_r2_r4(self):
    value = repair.load_json(CONFIG_PATH)
    with self.assertRaises(repair.Stage7RepairError):
      repair.require_formal_parameter_freeze(value)


class IntegrityAndSelectionTest(unittest.TestCase):

  def test_capacity_rows_preserve_base_guarded_and_effective_ratio(self):
    config = repair.load_json(CONFIG_PATH)
    rows = repair.compute_capacity_rows("blackscholes", 110, config)
    self.assertEqual([22, 44, 66], [row["D_base"] for row in rows])
    self.assertEqual([64, 64, 66], [row["D_guarded"] for row in rows])
    self.assertEqual(64 / 110.0, rows[0]["effective_ratio"])
    self.assertTrue(rows[0]["guard_applied"])
    self.assertFalse(rows[2]["guard_applied"])

  def test_candidate_starts_are_exact_and_bounded(self):
    config = repair.load_json(CONFIG_PATH)
    starts = repair.pressure_candidate_starts(config)
    self.assertEqual(51, len(starts))
    self.assertEqual(2400000, starts[0])
    self.assertEqual(2900000, starts[-1])

  def test_reactive_lru_candidate_starts_empty_and_counts_replacements(self):
    stats = repair.profile_lru_candidate(
        pages=[1, 2, 1, 3, 1, 2], writes=[False, True, False,
                                         False, True, False],
        dram_pages=2)
    self.assertEqual(3, stats["unique_pages"])
    self.assertEqual(4, stats["misses"])
    self.assertEqual(2, stats["lru_replacement_decisions"])
    self.assertEqual(4, stats["page_entry_count"])
    self.assertEqual(2 / 6.0, stats["write_ratio"])
    self.assertEqual("empty_dram", stats["initial_state"])

  def test_raw_sha_mismatch_is_rejected(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "raw.csv")
      write_trace(path, [1, 2, 3])
      with self.assertRaises(repair.Stage7RepairError):
        repair.verify_declared_sha(path, "0" * 64, "raw trace")

  def test_recorded_server_split_resolves_by_sha_to_local_suite(self):
    with tempfile.TemporaryDirectory() as directory:
      local_path = os.path.join(
          directory, "outputs", "capd_proactive_stage7",
          "stage7-local-suite-r1", "splits", "w", "train.csv")
      os.makedirs(os.path.dirname(local_path))
      write_trace(local_path, [1, 2, 3])
      recorded = (
          "outputs/capd_proactive_stage7/stage7-server-suite-r1/"
          "splits/w/train.csv")
      resolved = repair.resolve_recorded_split(
          directory, recorded, repair.fingerprint_file(local_path))
      self.assertEqual(os.path.realpath(local_path), resolved)

  def test_test_interval_out_of_bounds_is_rejected(self):
    with self.assertRaises(repair.Stage7RepairError):
      repair.validate_source_interval(2399999, 2499999, 2400000, 3000000)
    with self.assertRaises(repair.Stage7RepairError):
      repair.validate_source_interval(2950000, 3050000, 2400000, 3000000)

  def test_selection_uses_fixed_tie_break(self):
    rows = [
        candidate(2400200, 200, 90),
        candidate(2400100, 200, 91),
        candidate(2400000, 200, 91),
        candidate(2400300, 199, 999),
    ]
    selected = repair.select_pressure_windows(rows, {})
    cell = selected["cells"][0]
    self.assertTrue(cell["pressure_eligible"])
    self.assertEqual(2400000, cell["selected"]["source_start_inclusive"])
    self.assertEqual(
        ["reactive_lru_decisions", "unique_pages", "earliest_start"],
        cell["selection_features"])

  def test_capd_or_oracle_metrics_cannot_select_windows(self):
    for field in ("capd_weighted_cost", "oracle_headroom", "tpp_score"):
      row = candidate(2400000, 200, 100)
      row[field] = 1
      with self.assertRaises(repair.Stage7RepairError):
        repair.select_pressure_windows([row], {})

  def test_ineligible_cell_is_preserved_without_window(self):
    rows = [candidate(2400000, 99, 100), candidate(2400100, 200, 80)]
    rows[1]["unique_pages"] = rows[1]["D_guarded"] + 16
    selected = repair.select_pressure_windows(rows, {})
    cell = selected["cells"][0]
    self.assertFalse(cell["pressure_eligible"])
    self.assertIsNone(cell["selected"])
    self.assertIn("no_candidate_met", cell["ineligible_reason"])


class DerivationTest(unittest.TestCase):

  def test_derived_rows_equal_source_interval_and_source_is_unchanged(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "test.csv")
      derived = os.path.join(directory, "derived.csv")
      write_trace(source, list(range(20)), writes={2, 7, 12})
      before = repair.fingerprint_file(source)
      result = repair.derive_pressure_csv(source, derived, 5, 8)
      self.assertEqual(before, repair.fingerprint_file(source))
      self.assertEqual(8, result["rows"])
      repair.verify_derived_rows(source, derived, 5, 8)
      with open(source, "r", encoding="utf-8", newline="") as handle:
        source_rows = list(csv.reader(handle))
      with open(derived, "r", encoding="utf-8", newline="") as handle:
        derived_rows = list(csv.reader(handle))
      self.assertEqual(source_rows[0], derived_rows[0])
      self.assertEqual(source_rows[6:14], derived_rows[1:])

  def test_repeated_derivation_has_identical_sha(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "test.csv")
      first = os.path.join(directory, "first.csv")
      second = os.path.join(directory, "second.csv")
      write_trace(source, list(range(50)))
      a = repair.derive_pressure_csv(source, first, 10, 20)
      b = repair.derive_pressure_csv(source, second, 10, 20)
      self.assertEqual(a["sha256"], b["sha256"])

  def test_pressure_overhead_must_be_null_or_absent(self):
    repair.assert_no_pressure_overhead({"memory_overhead": None})
    repair.assert_no_pressure_overhead({})
    for field in repair.PRESSURE_OVERHEAD_FIELDS:
      with self.assertRaises(repair.Stage7RepairError):
        repair.assert_no_pressure_overhead({field: 0})

  def test_manifest_rejects_non_null_nested_overhead(self):
    value = {"cells": [{"selected": {"cpu_cycles": 1}}]}
    with self.assertRaises(repair.Stage7RepairError):
      repair.assert_no_pressure_overhead(value)

  def test_bundle_verifier_rejects_changed_artifact(self):
    with tempfile.TemporaryDirectory() as directory:
      artifact = os.path.join(directory, "frozen_parameters.json")
      with open(artifact, "w", encoding="utf-8") as handle:
        json.dump({"fixed": True}, handle)
      manifest_path = os.path.join(
          directory, "local_pressure_bundle_manifest.json")
      manifest = repair.build_bundle_manifest(
          directory, "stage7-repair-test", [artifact], [])
      repair.write_json_atomic(manifest_path, manifest)
      repair.verify_bundle_manifest(manifest_path)
      with open(artifact, "a", encoding="utf-8") as handle:
        handle.write("\n")
      with self.assertRaises(repair.Stage7RepairError):
        repair.verify_bundle_manifest(manifest_path)

  def test_bundle_verifier_rejects_paused_or_revoked_bundle(self):
    with tempfile.TemporaryDirectory() as directory:
      artifact = os.path.join(directory, "raw_identity_audit.json")
      with open(artifact, "w", encoding="utf-8") as handle:
        json.dump({"status": "R1_verified"}, handle)
      manifest_path = os.path.join(
          directory, "local_pressure_bundle_manifest.json")
      manifest = repair.build_bundle_manifest(
          directory, "stage7-repair-test", [artifact], [])
      manifest["formal_pressure_bundle"] = False
      manifest["status"] = "revoked_pending_parameter_reselection"
      repair.write_json_atomic(manifest_path, manifest)
      with self.assertRaises(repair.Stage7RepairError):
        repair.verify_bundle_manifest(manifest_path)

  def test_export_is_blocked_when_r2_r4_are_paused(self):
    with tempfile.TemporaryDirectory() as directory:
      output = repair.repair_output_root(directory, "paused-run")
      os.makedirs(output)
      repair.write_json_atomic(os.path.join(output, "local_prepare_state.json"), {
          "phase": "r1_verified_r2_r4_paused"})
      repair.write_json_atomic(os.path.join(output, "repair_pause.json"), {
          "formal_pressure_bundle_export_allowed": False})
      with self.assertRaisesRegex(repair.Stage7RepairError, "R2-R4 paused"):
        repair.export_local_bundle("paused-run", directory)


if __name__ == "__main__":
  unittest.main()
