# coding=utf-8
"""Contracts for deriving Stage-7 Pressure windows from Standard Test."""

from __future__ import annotations

import copy
import csv
import json
import os
import tempfile
import unittest

from qmap import proactive_pressure_stage7 as pressure


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDENDUM_PATH = os.path.join(
    PROJECT_ROOT, "outputs", "capd_proactive_stage3",
    "stage3-stage7-unified-contract-r4-pressure-addendum-r1",
    "pressure_window_selection_addendum.json")
ADDENDUM_AUDIT_PATH = os.path.join(
    os.path.dirname(ADDENDUM_PATH), "addendum_audit.json")
ADDENDUM_CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_pressure_stage7_r4_addendum_r1.json")


def _write_trace(path, pages):
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(("PID", "TID", "PC", "Address", "RW"))
    for index, page in enumerate(pages):
      writer.writerow((1, 1, hex(index), hex(int(page) << 12), "R"))


def _matrix():
  return [{
      "workload": "w", "D_standard": 8, "D_pressure": 8,
      "W_ref": 22, "window_records": 10,
      "working_set_definition":
          "train_chronological_window_unique_pages_quantile",
  }]


def _documents():
  matrix = _matrix()
  watermarks = [{"workload": "w", "D": 8, "F_low": 1,
                 "F_target": 2, "alpha": 0.15, "beta": 0.4}]
  shared = {
      "batch_mechanism": {"b_max": 2},
      "watermarks": copy.deepcopy(watermarks),
      "candidate_size_K": 8,
      "initial_state": "empty_dram_per_window",
      "chronological": True,
      "shuffle": False,
      "only_allowed_difference": "evaluation_interval_selection",
      "standard_capacity_matrix_ref": "unified_capacity_matrix",
      "pressure_capacity_matrix_ref": "unified_capacity_matrix",
      "model": "pending_stage4", "checkpoint": "pending_stage4",
      "seed": "pending_stage4",
  }
  final = {
      "formal_freeze": True,
      "status": "STAGE3_STAGE7_DERIVED_SELECTION_FORMALLY_FROZEN",
      "b_max": 2, "candidate_size_K": 8,
      "standard_capacity_matrix": copy.deepcopy(matrix),
      "pressure_capacity_matrix": copy.deepcopy(matrix),
      "unified_capacity_matrix": copy.deepcopy(matrix),
      "watermarks": copy.deepcopy(watermarks),
      "shared_standard_pressure_execution_contract": copy.deepcopy(shared),
  }
  contract = {
      "formal_freeze": True,
      "status": "STAGE3_STAGE7_PRESSURE_CONTRACT_FORMALLY_FROZEN",
      "b_max": 2, "selected_window_records": 10, "scan_step": 2,
      "standard_capacity_matrix": copy.deepcopy(matrix),
      "pressure_capacity_matrix": copy.deepcopy(matrix),
      "unified_capacity_matrix": copy.deepcopy(matrix),
      "shared_standard_pressure_execution_contract": copy.deepcopy(shared),
      "pressure_eligibility_rule": {
          "selection_policy": "fixed_reactive_lru_only",
          "minimum_reactive_lru_replacement_decisions": 100,
          "unique_pages_rule":
              "strictly_greater_than_D_pressure_plus_F_target",
          "prohibited_selection_features": [
              "capd", "oracle", "tpp", "weighted_cost", "stage8",
              "model_accuracy"],
      },
  }
  state = {"formal_freeze": True, "status": "derived_selection_formally_frozen"}
  return final, contract, state


def _approved_addendum():
  return pressure.load_json(ADDENDUM_PATH)


def _selection_candidate(start, end, trace_id, content_sha,
                         replacements, unique_pages, eligible=True):
  return {
      "pressure_eligible": eligible,
      "source_interval_start_inclusive": start,
      "source_interval_end_exclusive": end,
      "source_trace_id": trace_id,
      "candidate_content_sha256": content_sha,
      "reactive_lru_replacement_decisions": replacements,
      "unique_pages": unique_pages,
  }


class AuthorityGateTest(unittest.TestCase):

  def test_final_freeze_sha_mismatch_fails(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "final_freeze.json")
      with open(path, "w", encoding="utf-8") as handle:
        handle.write("{}\n")
      with self.assertRaisesRegex(pressure.PressureStage7Error, "final_freeze"):
        pressure.verify_declared_sha(path, "0" * 64, "final_freeze")

  def test_pressure_contract_sha_mismatch_fails(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "pressure_generation_contract.json")
      with open(path, "w", encoding="utf-8") as handle:
        handle.write("{}\n")
      with self.assertRaisesRegex(pressure.PressureStage7Error,
                                  "pressure_generation_contract"):
        pressure.verify_declared_sha(
            path, "f" * 64, "pressure_generation_contract")

  def test_run_state_must_be_formally_frozen(self):
    final, contract, state = _documents()
    state["formal_freeze"] = False
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.validate_r4_documents(final, contract, state)

  def test_final_and_contract_status_must_be_formal(self):
    final, contract, state = _documents()
    final["status"] = "candidate"
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.validate_r4_documents(final, contract, state)
    final, contract, state = _documents()
    contract["status"] = "candidate"
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.validate_r4_documents(final, contract, state)

  def test_capacity_matrices_must_be_identical(self):
    final, contract, state = _documents()
    contract["pressure_capacity_matrix"][0]["D_pressure"] = 9
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.validate_r4_documents(final, contract, state)

  def test_watermarks_and_b_max_must_match(self):
    for field, value in (("D", 9), ("F_low", 2), ("F_target", 3)):
      final, contract, state = _documents()
      contract["shared_standard_pressure_execution_contract"]["watermarks"][0][field] = value
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.validate_r4_documents(final, contract, state)
    final, contract, state = _documents()
    contract["b_max"] = 3
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.validate_r4_documents(final, contract, state)

  def test_split_and_raw_sha_mismatch_fail(self):
    with tempfile.TemporaryDirectory() as directory:
      test_path = os.path.join(directory, "test.csv")
      raw_path = os.path.join(directory, "raw.csv")
      _write_trace(test_path, range(12))
      _write_trace(raw_path, range(20))
      with self.assertRaisesRegex(pressure.PressureStage7Error, "Test split"):
        pressure.validate_source_identity(
            test_path, "0" * 64, raw_path,
            pressure.fingerprint_file(raw_path))
      with self.assertRaisesRegex(pressure.PressureStage7Error, "raw trace"):
        pressure.validate_source_identity(
            test_path, pressure.fingerprint_file(test_path), raw_path,
            "0" * 64)


class ScanContractTest(unittest.TestCase):

  def test_excluded_workload_is_never_opened(self):
    opened = []
    result = pressure.scan_workload(
        "fluidanimate", "does-not-exist.csv", 22, 3, 10, 2,
        excluded={"fluidanimate": "insufficient"},
        opener=lambda *args, **kwargs: opened.append(args))
    self.assertEqual([], opened)
    self.assertEqual("excluded", result["status"])

  def test_candidate_starts_have_frozen_window_and_step(self):
    self.assertEqual([0, 2, 4], pressure.candidate_starts(14, 10, 2))
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.candidate_starts(9, 10, 2)

  def test_each_candidate_starts_from_empty_dram(self):
    pages = [1, 2, 3, 1, 2, 3]
    first = pressure.profile_reactive_lru(pages[:3], 2)
    second = pressure.profile_reactive_lru(pages[3:], 2)
    self.assertEqual(first, second)
    self.assertEqual("empty_dram_per_window", first["initial_state"])

  def test_reactive_lru_replacement_counts_are_exact(self):
    stats = pressure.profile_reactive_lru([1, 2, 1, 3, 1, 2], 2)
    self.assertEqual(4, stats["reactive_lru_misses"])
    self.assertEqual(2, stats["reactive_lru_replacement_decisions"])

  def test_unique_page_gate_is_strict(self):
    self.assertFalse(pressure.assess_eligibility(10, 100, 8, 2)[0])
    self.assertTrue(pressure.assess_eligibility(11, 100, 8, 2)[0])

  def test_replacement_gate_is_inclusive_at_100(self):
    self.assertFalse(pressure.assess_eligibility(11, 99, 8, 2)[0])
    self.assertTrue(pressure.assess_eligibility(11, 100, 8, 2)[0])

  def test_prohibited_selection_fields_fail(self):
    for field in ("capd_cost", "oracle_score", "tpp_cost",
                  "weighted_cost", "stage8_metric", "model_accuracy",
                  "checkpoint", "seed"):
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.reject_prohibited_selection_fields([{field: 1}])

  def test_missing_total_order_fails_closed(self):
    _, contract, _ = _documents()
    gap = pressure.inspect_selection_order(contract)
    self.assertFalse(gap["complete"])
    with self.assertRaisesRegex(pressure.PressureStage7Error,
                                "INCOMPLETE_SELECTION_ORDER"):
      pressure.select_pressure_candidate([], contract)

  def test_approved_addendum_binds_parent_sha_and_canonical_sha(self):
    addendum = _approved_addendum()
    order = pressure.validate_pressure_addendum(
        addendum,
        "02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1",
        "1c4582c20098425f9e8a155e832aad737e35160e8d254808a09706ca45394761")
    self.assertTrue(order["complete"])
    for field in ("parent_final_freeze_sha256",
                  "parent_pressure_contract_sha256", "addendum_sha256"):
      changed = copy.deepcopy(addendum)
      changed[field] = "0" * 64
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.validate_pressure_addendum(
            changed,
            "02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1",
            "1c4582c20098425f9e8a155e832aad737e35160e8d254808a09706ca45394761")

  def test_addendum_audit_honestly_binds_blocked_run_and_file_sha(self):
    audit = pressure.load_json(ADDENDUM_AUDIT_PATH)
    self.assertEqual(pressure.fingerprint_file(ADDENDUM_PATH),
                     audit["addendum_file_sha256"])
    self.assertFalse(audit["formal_pressure_derive_executed"])
    self.assertFalse(audit["blocked_run_evidence"][
        "formal_pressure_test_generated"])
    disclosure = audit["honest_protocol_disclosure"]
    self.assertTrue(disclosure[
        "addendum_is_not_claimed_as_pre_registered_in_parent_r4"])
    self.assertFalse(disclosure[
        "pressure_intensity_metrics_used_for_eligible_window_ranking"])
    self.assertFalse(disclosure["capd_or_oracle_used_for_window_ranking"])

  def test_new_config_binds_parent_and_addendum_file_sha(self):
    config = pressure.load_json(ADDENDUM_CONFIG_PATH)
    authorities = config["authorities"]
    self.assertEqual(
        pressure.fingerprint_file(ADDENDUM_PATH),
        authorities["pressure_window_selection_addendum"]["sha256"])
    self.assertEqual(
        "02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1",
        authorities["final_freeze"]["sha256"])
    self.assertEqual(
        "1c4582c20098425f9e8a155e832aad737e35160e8d254808a09706ca45394761",
        authorities["pressure_generation_contract"]["sha256"])

  def test_multiple_eligible_windows_use_earliest_not_pressure_strength(self):
    addendum = _approved_addendum()
    rows = [
        _selection_candidate(2400000, 2900000, "trace", "a" * 64,
                             replacements=100, unique_pages=11),
        _selection_candidate(2410000, 2910000, "trace", "b" * 64,
                             replacements=999999, unique_pages=999999),
    ]
    with self.assertRaises(pressure.PressureStage7Error):
      pressure.select_pressure_candidate(rows, addendum, manual_start=2400000)
    self.assertEqual(
        2400000, pressure.select_pressure_candidate(rows, addendum)[
            "source_interval_start_inclusive"])

  def test_approved_tie_break_order_is_exact(self):
    addendum = _approved_addendum()
    rows = [
        _selection_candidate(10, 30, "a", "a" * 64, 100, 11),
        _selection_candidate(10, 20, "b", "b" * 64, 1000, 1000),
        _selection_candidate(10, 20, "a", "c" * 64, 999, 999),
        _selection_candidate(10, 20, "a", "b" * 64, 101, 12),
    ]
    selected = pressure.select_pressure_candidate(rows, addendum)
    self.assertEqual(20, selected["source_interval_end_exclusive"])
    self.assertEqual("a", selected["source_trace_id"])
    self.assertEqual("b" * 64, selected["candidate_content_sha256"])

  def test_candidate_content_sha_excludes_eligibility_and_pressure_metrics(self):
    candidate = {
        "workload": "w", "source_trace_id": "trace",
        "source_test_path": "splits/w/test.csv",
        "source_test_sha256": "f" * 64,
        "split_relative_start": 0,
        "split_relative_end_exclusive": 10,
        "source_interval_start_inclusive": 2400000,
        "source_interval_end_exclusive": 2400010,
        "window_records": 10, "scan_step": 2,
        "unique_pages": 11,
        "reactive_lru_replacement_decisions": 100,
    }
    first = pressure.candidate_content_sha256(candidate)
    candidate["unique_pages"] = 9999
    candidate["reactive_lru_replacement_decisions"] = 9999
    self.assertEqual(first, pressure.candidate_content_sha256(candidate))
    candidate["candidate_content_sha256"] = first
    candidate["candidate_content_sha256_semantics"] = (
        "sha256_of_normalized_source_identity_and_interval")
    pressure.verify_candidate_content_sha256(candidate)

  def test_no_eligible_window_returns_none_without_fabrication(self):
    rows = [_selection_candidate(
        1, 2, "trace", "a" * 64, 100, 11, eligible=False)]
    self.assertIsNone(pressure.select_pressure_candidate(
        rows, _approved_addendum()))


class DerivationAndResumeTest(unittest.TestCase):

  def test_derived_csv_equals_source_interval_and_has_exact_rows(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "test.csv")
      derived = os.path.join(directory, "pressure.csv")
      _write_trace(source, range(20))
      before = pressure.fingerprint_file(source)
      result = pressure.derive_pressure_csv(source, derived, 5, 10)
      self.assertEqual(10, result["rows"])
      pressure.verify_derived_rows(source, derived, 5, 10)
      self.assertEqual(before, pressure.fingerprint_file(source))

  def test_derivation_rejects_wrong_row_count(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "test.csv")
      derived = os.path.join(directory, "pressure.csv")
      _write_trace(source, range(9))
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.derive_pressure_csv(source, derived, 0, 10)

  def test_repeat_derivation_and_candidate_json_are_deterministic(self):
    with tempfile.TemporaryDirectory() as directory:
      source = os.path.join(directory, "test.csv")
      a = os.path.join(directory, "a.csv")
      b = os.path.join(directory, "b.csv")
      _write_trace(source, range(20))
      first = pressure.derive_pressure_csv(source, a, 5, 10)
      second = pressure.derive_pressure_csv(source, b, 5, 10)
      self.assertEqual(first["derived_sha256"], second["derived_sha256"])
      rows = [{"workload": "w", "pressure_eligible": True}]
      self.assertEqual(pressure.fingerprint_value(rows),
                       pressure.fingerprint_value(copy.deepcopy(rows)))

  def test_resume_rejects_changed_input_config_or_code(self):
    state = {"input_identity_sha256": "a", "config_sha256": "b",
             "code_sha256": "c"}
    pressure.validate_resume_identity(state, "a", "b", "c")
    for values in (("x", "b", "c"), ("a", "x", "c"),
                   ("a", "b", "x")):
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.validate_resume_identity(state, *values)

  def test_pressure_outputs_cannot_claim_overhead(self):
    pressure.assert_no_overhead_claims({"pressure_overhead_claims_allowed": False})
    for field in pressure.OVERHEAD_FIELDS:
      with self.assertRaises(pressure.PressureStage7Error):
        pressure.assert_no_overhead_claims({field: 0})

  def test_forbidden_stage_and_stale_pressure_paths_are_rejected(self):
    for path in (
        "outputs/capd_proactive_stage4/x.json",
        "outputs/capd_proactive_stage8/x.json",
        "models/capd_checkpoint.pt",
        "outputs/capd_proactive_stage7_repair/stage7-repair-r1/pressure_candidates.csv",
        "outputs/capd_proactive_stage7_repair/stage7-repair-r1/pressure_test_lock.json",
    ):
      self.assertTrue(pressure.is_forbidden_input_path(path))
    self.assertFalse(pressure.is_forbidden_input_path(
        "outputs/capd_proactive_stage7_repair/stage7-repair-r1/raw_identity_audit.json"))


if __name__ == "__main__":
  unittest.main()
