# coding=utf-8
"""Fail-closed Stage-7 Standard-Test to Pressure-Test derivation.

This module is intentionally independent from proactive_stage7_repair.  The
only reusable R1 artifacts are the raw identity audit and its verification;
no stale Pressure candidate, window, capacity, lock, or bundle artifact is
accepted as an input.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from array import array
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "capd_proactive_pressure_stage7_v1_0"
ADDENDUM_SCHEMA_VERSION = "capd_proactive_pressure_selection_addendum_v1_0"
BLOCKED_STATE = "PRESSURE_CONTRACT_INCOMPLETE_SELECTION_ORDER"
BLOCKED_COMPLETION = "PRESSURE_DERIVATION_IMPLEMENTED_BUT_CONTRACT_BLOCKED"
FORMAL_COMPLETION = "PRESSURE_TEST_DERIVED_AND_VERIFIED"
ALLOWED_WORKLOADS = (
    "canneal", "dedup_pressure", "blackscholes", "swaptions")
EXCLUDED_WORKLOADS = ("streamcluster_pressure", "fluidanimate")
PROHIBITED_SELECTION_TOKENS = (
    "capd", "oracle", "tpp", "weighted_cost", "stage8", "model_accuracy",
    "stage4", "checkpoint", "seed", "policy_result")
APPROVED_SORT_KEYS = (
    ("source_interval.start_inclusive", "ascending"),
    ("source_interval.end_exclusive", "ascending"),
    ("source_trace_id", "ascending"),
    ("candidate_content_sha256", "ascending"))
OVERHEAD_FIELDS = (
    "pressure_overhead", "memory_overhead", "metadata_memory_overhead",
    "inference_latency", "cpu_cycles", "total_execution_time",
    "foreground_blocking_time", "end_to_end_overhead", "throughput",
    "latency")
CANDIDATE_FIELDS = (
    "workload", "source_trace_id", "source_test_path", "source_test_sha256",
    "split_relative_start", "split_relative_end_exclusive",
    "source_interval_start_inclusive", "source_interval_end_exclusive",
    "raw_trace_start", "raw_trace_end_exclusive", "window_records",
    "scan_step", "D", "F_low", "F_target", "unique_pages",
    "reactive_lru_misses", "reactive_lru_replacement_decisions",
    "pressure_eligible", "ineligibility_reasons",
    "selection_features_used", "candidate_content_sha256",
    "candidate_content_sha256_semantics",
    "contract_sha256", "addendum_sha256", "code_sha256", "config_sha256")


class PressureStage7Error(ValueError):
  """Raised when an integrity, isolation, or derivation gate fails."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise PressureStage7Error(message)


def load_json(path: str) -> Any:
  with open(path, "r", encoding="utf-8") as handle:
    return json.load(handle)


def fingerprint_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    while True:
      block = handle.read(1024 * 1024)
      if not block:
        break
      digest.update(block)
  return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
  payload = json.dumps(
      value, ensure_ascii=False, sort_keys=True,
      separators=(",", ":")).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


def candidate_content_sha256(candidate: Mapping[str, Any]) -> str:
  """Hash only immutable source/interval identity, never ranking metrics."""
  fields = (
      "workload", "source_trace_id", "source_test_path",
      "source_test_sha256", "split_relative_start",
      "split_relative_end_exclusive", "source_interval_start_inclusive",
      "source_interval_end_exclusive", "window_records", "scan_step")
  _require(all(field in candidate for field in fields),
           "Candidate source/interval identity is incomplete.")
  return fingerprint_value({field: candidate[field] for field in fields})


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".pressure-stage7-json-", suffix=".tmp", dir=directory)
  os.close(descriptor)
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
      json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
      handle.write("\n")
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]],
                     fieldnames: Sequence[str]) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".pressure-stage7-csv-", suffix=".tmp", dir=directory)
  os.close(descriptor)
  try:
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(
          handle, fieldnames=list(fieldnames), lineterminator="\n")
      writer.writeheader()
      for row in rows:
        writer.writerow({field: row.get(field) for field in fieldnames})
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def verify_declared_sha(path: str, expected_sha256: str, label: str) -> str:
  _require(os.path.isfile(path), "Missing {}: {}".format(label, path))
  actual = fingerprint_file(path)
  _require(actual == str(expected_sha256).lower(),
           "{} SHA256 mismatch: expected {}, got {}.".format(
               label, expected_sha256, actual))
  return actual


def _canonical_rows(rows: Any) -> List[Mapping[str, Any]]:
  _require(isinstance(rows, list), "Capacity/watermark value must be a list.")
  return sorted((dict(row) for row in rows), key=lambda row: row["workload"])


def validate_r4_documents(final_freeze: Mapping[str, Any],
                          pressure_contract: Mapping[str, Any],
                          run_state: Mapping[str, Any]) -> None:
  _require(final_freeze.get("formal_freeze") is True,
           "final_freeze is not formally frozen.")
  _require(pressure_contract.get("formal_freeze") is True,
           "pressure_generation_contract is not formally frozen.")
  _require(run_state.get("formal_freeze") is True,
           "run_state formal_freeze must be true.")
  _require(final_freeze.get("status") ==
           "STAGE3_STAGE7_DERIVED_SELECTION_FORMALLY_FROZEN",
           "final_freeze status is not the formal R4 status.")
  _require(pressure_contract.get("status") ==
           "STAGE3_STAGE7_PRESSURE_CONTRACT_FORMALLY_FROZEN",
           "pressure_generation_contract status is not formally frozen.")
  _require(run_state.get("status") == "derived_selection_formally_frozen",
           "run_state status is not the formal R4 status.")

  matrices = []
  for document_name, document in (
      ("final_freeze", final_freeze),
      ("pressure_generation_contract", pressure_contract)):
    for field in ("standard_capacity_matrix", "pressure_capacity_matrix",
                  "unified_capacity_matrix"):
      rows = _canonical_rows(document.get(field))
      matrices.append(("{}.{}".format(document_name, field), rows))
  baseline_name, baseline = matrices[0]
  for name, rows in matrices[1:]:
    _require(rows == baseline,
             "Capacity matrix mismatch between {} and {}.".format(
                 baseline_name, name))
  for row in baseline:
    _require(row.get("D_standard") == row.get("D_pressure"),
             "Standard/Pressure D mismatch for {}.".format(row["workload"]))

  final_shared = final_freeze.get(
      "shared_standard_pressure_execution_contract", {})
  contract_shared = pressure_contract.get(
      "shared_standard_pressure_execution_contract", {})
  for field, expected in (
      ("initial_state", "empty_dram_per_window"),
      ("chronological", True), ("shuffle", False),
      ("only_allowed_difference", "evaluation_interval_selection"),
      ("standard_capacity_matrix_ref", "unified_capacity_matrix"),
      ("pressure_capacity_matrix_ref", "unified_capacity_matrix")):
    _require(final_shared.get(field) == expected and
             contract_shared.get(field) == expected,
             "Shared Standard/Pressure contract mismatch: {}.".format(field))
  for field in ("candidate_size_K", "model", "checkpoint", "seed"):
    _require(final_shared.get(field) == contract_shared.get(field),
             "Shared execution field mismatch: {}.".format(field))
  _require(final_freeze.get("b_max") == pressure_contract.get("b_max") ==
           final_shared.get("batch_mechanism", {}).get("b_max") ==
           contract_shared.get("batch_mechanism", {}).get("b_max"),
           "b_max differs across the R4 contract.")

  final_watermarks = _canonical_rows(final_freeze.get("watermarks"))
  shared_final_watermarks = _canonical_rows(final_shared.get("watermarks"))
  shared_contract_watermarks = _canonical_rows(
      contract_shared.get("watermarks"))
  _require(final_watermarks == shared_final_watermarks ==
           shared_contract_watermarks,
           "D/F_low/F_target watermarks differ across the R4 contract.")
  matrix_by_workload = {row["workload"]: row for row in baseline}
  for row in final_watermarks:
    _require(row.get("D") ==
             matrix_by_workload[row["workload"]].get("D_standard"),
             "Watermark D differs from unified capacity matrix.")


def validate_source_identity(test_path: str, expected_test_sha256: str,
                             raw_path: str,
                             expected_raw_sha256: str) -> Dict[str, str]:
  return {
      "test_sha256": verify_declared_sha(
          test_path, expected_test_sha256, "Test split"),
      "raw_sha256": verify_declared_sha(
          raw_path, expected_raw_sha256, "raw trace"),
  }


def candidate_starts(test_records: int, window_records: int,
                     scan_step: int) -> List[int]:
  _require(all(isinstance(value, int) and value > 0 for value in
               (test_records, window_records, scan_step)),
           "Test length, window length, and scan step must be positive ints.")
  _require(window_records <= test_records,
           "Pressure window exceeds Standard Test length.")
  starts = list(range(0, test_records - window_records + 1, scan_step))
  _require(starts and starts[-1] + window_records <= test_records,
           "Pressure candidate construction failed.")
  return starts


def profile_reactive_lru(pages: Sequence[int], dram_pages: int,
                         start: int = 0,
                         end: Optional[int] = None) -> Dict[str, Any]:
  _require(isinstance(dram_pages, int) and dram_pages > 0,
           "DRAM capacity must be a positive integer.")
  end = len(pages) if end is None else end
  _require(0 <= start < end <= len(pages), "LRU interval is out of bounds.")
  resident: OrderedDict[int, None] = OrderedDict()
  unique = set()
  misses = 0
  replacements = 0
  for index in range(start, end):
    page = int(pages[index])
    unique.add(page)
    if page in resident:
      resident.move_to_end(page)
      continue
    misses += 1
    if len(resident) >= dram_pages:
      resident.popitem(last=False)
      replacements += 1
    resident[page] = None
  return {
      "policy": "reactive_lru",
      "initial_state": "empty_dram_per_window",
      "unique_pages": len(unique),
      "reactive_lru_misses": misses,
      "reactive_lru_replacement_decisions": replacements,
      "window_records": end - start,
  }


def assess_eligibility(unique_pages: int, replacement_decisions: int,
                       dram_pages: int, f_target: int,
                       minimum_replacements: int = 100) -> Tuple[bool, List[str]]:
  reasons = []
  if int(unique_pages) <= int(dram_pages) + int(f_target):
    reasons.append("unique_pages_not_strictly_greater_than_D_plus_F_target")
  if int(replacement_decisions) < int(minimum_replacements):
    reasons.append("reactive_lru_replacement_decisions_below_minimum")
  return not reasons, reasons


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
  if isinstance(value, Mapping):
    yield value
    for nested in value.values():
      for row in _walk_mappings(nested):
        yield row
  elif isinstance(value, (list, tuple)):
    for nested in value:
      for row in _walk_mappings(nested):
        yield row


def reject_prohibited_selection_fields(rows: Sequence[Mapping[str, Any]]) -> None:
  for row in rows:
    for field in row:
      normalized = str(field).lower()
      if any(token in normalized for token in PROHIBITED_SELECTION_TOKENS):
        raise PressureStage7Error(
            "Prohibited Pressure selection field: {}.".format(field))


def inspect_selection_order(contract: Mapping[str, Any],
                            addendum: Optional[Mapping[str, Any]] = None
                            ) -> Dict[str, Any]:
  path = "pressure_window_selection_order"
  source = addendum if isinstance(addendum, Mapping) else contract
  value = source.get(path)
  missing = []
  if not isinstance(value, Mapping):
    missing.append(path)
    return {"complete": False, "field_path": path,
            "missing_fields": missing, "contract_value": None}
  expected_sort_keys = [
      {"field": field, "order": order}
      for field, order in APPROVED_SORT_KEYS]
  for field, expected in (
      ("rule", "earliest_eligible_window_in_source_trace"),
      ("scope", "independently_per_workload"),
      ("eligibility_filter_first", True),
      ("sort_keys", expected_sort_keys),
      ("selected_rank", 1),
      ("metrics_for_ranking", []),
      ("no_eligible_action", "exclude_workload_fail_closed")):
    if value.get(field) != expected:
      missing.append("{}.{}={}".format(path, field, expected))
  return {"complete": not missing, "field_path": path,
          "missing_fields": missing, "contract_value": dict(value)}


def validate_pressure_addendum(addendum: Mapping[str, Any],
                               parent_final_freeze_sha256: str,
                               parent_pressure_contract_sha256: str
                               ) -> Dict[str, Any]:
  _require(addendum.get("schema_version") == ADDENDUM_SCHEMA_VERSION,
           "Pressure selection addendum schema mismatch.")
  _require(addendum.get("addendum_run_id") ==
           "stage3-stage7-unified-contract-r4-pressure-addendum-r1",
           "Pressure selection addendum run ID mismatch.")
  _require(addendum.get("parent_stage3_run_id") ==
           "stage3-stage7-unified-contract-r4",
           "Pressure selection addendum parent run mismatch.")
  _require(addendum.get("parent_final_freeze_path") ==
           "outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/"
           "final_freeze.json",
           "Pressure selection addendum parent final_freeze path mismatch.")
  _require(addendum.get("parent_pressure_contract_path") ==
           "outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/"
           "pressure_generation_contract.json",
           "Pressure selection addendum parent contract path mismatch.")
  _require(addendum.get("parent_final_freeze_sha256") ==
           parent_final_freeze_sha256,
           "Pressure selection addendum parent final_freeze SHA mismatch.")
  _require(addendum.get("parent_pressure_contract_sha256") ==
           parent_pressure_contract_sha256,
           "Pressure selection addendum parent contract SHA mismatch.")
  _require(addendum.get("approval_status") == "FORMALLY_APPROVED_BY_USER" and
           bool(addendum.get("approval_timestamp")),
           "Pressure selection addendum lacks explicit approval evidence.")
  _require(addendum.get("pressure_window_selection_rule") ==
           "earliest_eligible_window_in_source_trace",
           "Pressure selection rule mismatch.")
  eligibility = addendum.get("eligibility_rule", {})
  _require(eligibility == {
      "minimum_reactive_lru_replacement_decisions": 100,
      "selection_policy": "fixed_reactive_lru_only",
      "unique_pages_rule":
          "strictly_greater_than_D_pressure_plus_F_target"},
      "Addendum changed the parent R4 eligibility rule.")
  excluded = _map_by_workload(addendum.get("excluded_workloads", []))
  _require(excluded == {
      "streamcluster_pressure": {
          "workload": "streamcluster_pressure",
          "reason": "insufficient_replacement_decisions_across_train_blocks"},
      "fluidanimate": {
          "workload": "fluidanimate",
          "reason": "insufficient_replacement_decisions_across_train_blocks"}},
      "Addendum changed the frozen excluded workload set.")
  order = inspect_selection_order({}, addendum)
  _require(order["complete"],
           "Approved addendum selection order is incomplete: {}.".format(
               order["missing_fields"]))
  _require(addendum.get("selection_sort_keys") == [
      "{}:{}".format(field, direction)
      for field, direction in APPROVED_SORT_KEYS],
      "Addendum selection_sort_keys do not match the approved order.")
  _require(addendum.get("tie_break") == [
      "{}:{}".format(field, direction)
      for field, direction in APPROVED_SORT_KEYS[1:]],
      "Addendum tie_break does not match the approved order.")
  prohibited = set(addendum.get("ranking_prohibitions", []))
  _require({
      "reactive_lru_replacement_decisions", "unique_pages",
      "replacement_rate", "oracle_headroom", "capd_cost",
      "capd_relative_improvement", "stage4_model_prediction",
      "manual_posthoc_selection"}.issubset(prohibited),
      "Addendum ranking prohibitions are incomplete.")
  disclosure = addendum.get("honest_protocol_disclosure", {})
  _require(disclosure.get(
      "original_r4_froze_eligibility_but_not_unique_selection_order") is True and
      disclosure.get("gap_discovered_after_local_candidate_scan") is True and
      disclosure.get("formal_pressure_test_generated_before_addendum") is False and
      disclosure.get("capd_or_oracle_used_for_selection") is False and
      disclosure.get("model_or_stage4_checkpoint_used_for_selection") is False and
      disclosure.get("pressure_intensity_or_method_effect_used_for_ranking") is False and
      disclosure.get("original_r4_rule_pre_registered_claim_allowed") is False and
      disclosure.get("eligible_candidate_counts_known_at_gap_discovery") == {
          "canneal": 11, "dedup_pressure": 11,
          "blackscholes": 11, "swaptions": 11},
      "Addendum honest protocol disclosure is incomplete or inaccurate.")
  _require(addendum.get("addendum_sha256_semantics") ==
           "sha256_of_canonical_json_excluding_addendum_sha256_field",
           "Addendum canonical SHA semantics mismatch.")
  canonical = dict(addendum)
  declared = canonical.pop("addendum_sha256", None)
  _require(declared == fingerprint_value(canonical),
           "Addendum canonical SHA256 mismatch.")
  return order


def select_pressure_candidate(candidates: Sequence[Mapping[str, Any]],
                              selection_authority: Mapping[str, Any],
                              manual_start: Optional[int] = None
                              ) -> Optional[Dict[str, Any]]:
  order = inspect_selection_order({}, selection_authority)
  _require(order["complete"],
           BLOCKED_STATE + ": formal deterministic total order is missing.")
  _require(manual_start is None,
           "Manual Pressure window selection is prohibited.")
  rows = [dict(row) for row in candidates if row.get("pressure_eligible") is True]
  reject_prohibited_selection_fields(rows)
  if not rows:
    return None
  def sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        int(row["source_interval_start_inclusive"]),
        int(row["source_interval_end_exclusive"]),
        str(row["source_trace_id"]),
        str(row["candidate_content_sha256"]))

  return dict(sorted(rows, key=sort_key)[0])


def _load_pages(test_path: str, expected_records: int,
                page_shift: int = 12, opener=open) -> array:
  pages = array("Q")
  with opener(test_path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.reader(handle)
    try:
      header = next(reader)
    except StopIteration as error:
      raise PressureStage7Error("Standard Test CSV is empty.") from error
    _require("Address" in header, "Standard Test CSV lacks Address column.")
    address_index = header.index("Address")
    for row in reader:
      _require(len(row) == len(header), "Malformed Standard Test CSV row.")
      pages.append(int(row[address_index], 0) >> page_shift)
  _require(len(pages) == expected_records,
           "Standard Test row count mismatch: expected {}, got {}.".format(
               expected_records, len(pages)))
  return pages


def scan_workload(workload: str, test_path: str, dram_pages: int,
                  f_target: int, window_records: int, scan_step: int,
                  excluded: Mapping[str, str], expected_records: int = 600000,
                  page_shift: int = 12, opener=open) -> Dict[str, Any]:
  if workload in excluded:
    return {"workload": workload, "status": "excluded",
            "reason": excluded[workload], "test_payload_opened": False,
            "candidates": []}
  pages = _load_pages(test_path, expected_records, page_shift, opener)
  rows = []
  for start in candidate_starts(len(pages), window_records, scan_step):
    stats = profile_reactive_lru(
        pages, dram_pages, start, start + window_records)
    eligible, reasons = assess_eligibility(
        stats["unique_pages"],
        stats["reactive_lru_replacement_decisions"], dram_pages, f_target)
    stats.update({
        "workload": workload,
        "split_relative_start": start,
        "split_relative_end_exclusive": start + window_records,
        "pressure_eligible": eligible,
        "ineligibility_reasons": reasons,
    })
    rows.append(stats)
  return {"workload": workload, "status": "scanned",
          "test_payload_opened": True, "candidates": rows}


def _copy_binary_lines(source_path: str, destination_path: str,
                       relative_start: int, row_count: int) -> int:
  _require(relative_start >= 0 and row_count > 0,
           "Derived interval must have non-negative start and positive rows.")
  directory = os.path.dirname(os.path.abspath(destination_path))
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".pressure-stage7-derived-", suffix=".tmp", dir=directory)
  os.close(descriptor)
  copied = 0
  try:
    with open(source_path, "rb") as source, open(temporary, "wb") as output:
      header = source.readline()
      _require(bool(header), "Source Test CSV is empty.")
      output.write(header)
      for index, line in enumerate(source):
        if index < relative_start:
          continue
        if index >= relative_start + row_count:
          break
        output.write(line)
        copied += 1
    _require(copied == row_count,
             "Source Test interval is out of bounds: requested {}, copied {}."
             .format(row_count, copied))
    os.replace(temporary, destination_path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)
  return copied


def derive_pressure_csv(source_test_path: str, destination_path: str,
                        relative_start: int, row_count: int) -> Dict[str, Any]:
  source_before = fingerprint_file(source_test_path)
  rows = _copy_binary_lines(
      source_test_path, destination_path, relative_start, row_count)
  source_after = fingerprint_file(source_test_path)
  _require(source_before == source_after,
           "Source Test CSV changed during derivation.")
  return {
      "rows": rows,
      "source_test_sha256_before": source_before,
      "source_test_sha256_after": source_after,
      "derived_sha256": fingerprint_file(destination_path),
  }


def verify_derived_rows(source_test_path: str, derived_path: str,
                        relative_start: int, row_count: int) -> None:
  with open(source_test_path, "rb") as source:
    source_header = source.readline()
    expected = []
    for index, line in enumerate(source):
      if index < relative_start:
        continue
      if index >= relative_start + row_count:
        break
      expected.append(line)
  with open(derived_path, "rb") as derived:
    derived_header = derived.readline()
    actual = list(derived)
  _require(source_header == derived_header,
           "Derived CSV header differs from Standard Test.")
  _require(len(expected) == row_count and len(actual) == row_count,
           "Derived CSV row count differs from the frozen window length.")
  _require(actual == expected,
           "Derived CSV rows differ from the declared Test interval.")


def validate_resume_identity(state: Mapping[str, Any], input_sha256: str,
                             config_sha256: str, code_sha256: str) -> None:
  _require(state.get("input_identity_sha256") == input_sha256,
           "--resume rejected: input identity changed.")
  _require(state.get("config_sha256") == config_sha256,
           "--resume rejected: config SHA256 changed.")
  _require(state.get("code_sha256") == code_sha256,
           "--resume rejected: code SHA256 changed.")


def assert_no_overhead_claims(value: Any) -> None:
  for row in _walk_mappings(value):
    for field in OVERHEAD_FIELDS:
      _require(field not in row or row[field] is None or row[field] is False,
               "Pressure output field {} cannot support an overhead claim."
               .format(field))


def is_forbidden_input_path(path: str) -> bool:
  normalized = str(path).replace("\\", "/").lower()
  if "/capd_proactive_stage4/" in "/" + normalized:
    return True
  if "/capd_proactive_stage8/" in "/" + normalized:
    return True
  if "checkpoint" in normalized or normalized.endswith((".pt", ".pth")):
    return True
  old_root = (
      "outputs/capd_proactive_stage7_repair/stage7-repair-r1/")
  if old_root in normalized:
    basename = normalized.rsplit("/", 1)[-1]
    return basename not in ("raw_identity_audit.json", "verification.json")
  return False


def _inside(root: str, path: str) -> bool:
  try:
    return os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
  except ValueError:
    return False


def _project_file(project_root: str, relative_path: str) -> str:
  _require(not os.path.isabs(relative_path),
           "Configured repository path must be relative.")
  _require(not is_forbidden_input_path(relative_path),
           "Forbidden Stage/Pressure input path: {}.".format(relative_path))
  path = os.path.realpath(os.path.join(
      os.path.realpath(project_root), relative_path.replace("/", os.sep)))
  _require(_inside(project_root, path), "Configured path escapes project root.")
  return path


def _safe_run_id(run_id: str) -> str:
  _require(run_id and all(character.isalnum() or character in "-_" for character in run_id),
           "Run ID must contain only letters, digits, hyphen, or underscore.")
  return run_id


def output_root(project_root: str, run_id: str) -> str:
  return os.path.join(os.path.realpath(project_root), "outputs",
                      "capd_proactive_pressure_stage7", _safe_run_id(run_id))


def validate_config(config: Mapping[str, Any]) -> None:
  _require(config.get("schema_version") == SCHEMA_VERSION,
           "Pressure Stage-7 config schema mismatch.")
  scan = config.get("scan", {})
  _require(scan.get("test_records") == 600000,
           "Standard Test length must be 600000.")
  _require(scan.get("window_records") == 500000,
           "Pressure window length must be 500000.")
  _require(scan.get("scan_step") == 10000,
           "Pressure scan step must be 10000.")
  _require(scan.get("page_shift") == 12,
           "Pressure page_shift must be 12.")
  _require(scan.get("raw_test_start") == 2400000 and
           scan.get("raw_test_end_exclusive") == 3000000,
           "Frozen raw Test interval mismatch.")
  _require(tuple(config.get("allowed_workloads", [])) == ALLOWED_WORKLOADS,
           "Allowed Pressure workload list mismatch.")
  _require(tuple(config.get("excluded_workloads", {}).keys()) ==
           EXCLUDED_WORKLOADS,
           "Excluded Pressure workload list mismatch.")
  for item in config.get("authorities", {}).values():
    _require(not is_forbidden_input_path(item.get("path", "")),
             "Config references a forbidden authority path.")
    _require(len(str(item.get("sha256", ""))) == 64,
             "Authority SHA256 must be declared.")


def _code_sha256(project_root: str) -> str:
  paths = [
      os.path.join(project_root, "qmap", "proactive_pressure_stage7.py"),
      os.path.join(project_root, "scripts",
                   "run_capd_proactive_pressure_stage7.py"),
  ]
  return fingerprint_value([
      {"path": os.path.relpath(path, project_root).replace(os.sep, "/"),
       "sha256": fingerprint_file(path)} for path in paths])


def _load_authorities(config: Mapping[str, Any], project_root: str
                      ) -> Tuple[Dict[str, Any], Dict[str, str]]:
  values = {}
  hashes = {}
  for name, item in sorted(config["authorities"].items()):
    path = _project_file(project_root, item["path"])
    hashes[name] = verify_declared_sha(path, item["sha256"], name)
    values[name] = load_json(path)
  return values, hashes


def _map_by_workload(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
  result = {row["workload"]: row for row in rows}
  _require(len(result) == len(rows), "Duplicate workload in authority manifest.")
  return result


def _validate_r1_and_stage7_authorities(values: Mapping[str, Any]) -> Dict[str, Any]:
  raw = values["r1_raw_identity_audit"]
  verification = values["r1_verification"]
  split_manifest = values["split_manifest"]
  standard_lock = values["standard_test_lock"]
  _require(raw.get("status") == "STAGE7_REPAIR_RAW_IDENTITY_VERIFIED" and
           raw.get("identity_access_only") is True and
           raw.get("policy_metrics_read") is False,
           "R1 raw identity audit boundary/status mismatch.")
  _require(verification.get("R1") == "passed" and
           verification.get("status") ==
           "STAGE7_REPAIR_R1_RAW_IDENTITY_VERIFIED" and
           verification.get("raw_and_split_sha_unchanged") is True and
           verification.get("R5_R11_executed") is False,
           "R1 verification does not prove the identity-only audit.")
  _require(verification.get("raw_identity_audit_sha256") ==
           fingerprint_value(raw) or
           verification.get("raw_identity_audit_sha256") ==
           values.get("_r1_raw_file_sha256"),
           "R1 verification does not bind the raw identity audit.")
  raw_map = _map_by_workload(raw.get("workloads", []))
  split_map = _map_by_workload(split_manifest.get("workloads", []))
  lock_map = _map_by_workload(standard_lock.get("workloads", []))
  expected = set(ALLOWED_WORKLOADS + EXCLUDED_WORKLOADS)
  _require(set(raw_map) == set(split_map) == set(lock_map) == expected,
           "R1/split/Standard-lock workload sets differ.")
  for workload in sorted(expected):
    raw_test = raw_map[workload]["splits"]["test"]
    split_test = split_map[workload]["splits"]["test"]
    lock_test = lock_map[workload]
    _require(raw_test["sha256_declared"] == raw_test["sha256_actual"] ==
             split_test["sha256"] == lock_test["sha256"],
             "Test SHA binding mismatch for {}.".format(workload))
    _require(raw_test["accesses"] == split_test["accesses"] ==
             lock_test["accesses"] == 600000,
             "Test length binding mismatch for {}.".format(workload))
    _require(raw_test["interval"] == split_test["interval"] ==
             lock_test["interval"] == {
                 "start_inclusive": 2400000,
                 "end_exclusive": 3000000},
             "Test interval binding mismatch for {}.".format(workload))
    _require(raw_map[workload]["raw_sha256_before"] ==
             raw_map[workload]["raw_sha256_after"] ==
             raw_map[workload]["raw_sha256_declared"] and
             raw_map[workload]["raw_trace_unchanged"] is True,
             "R1 raw SHA binding mismatch for {}.".format(workload))
  return {"raw": raw_map, "split": split_map, "lock": lock_map}


def _artifact_rows(output: str, names: Sequence[str]) -> Dict[str, str]:
  result = {}
  for name in names:
    path = os.path.join(output, name.replace("/", os.sep))
    _require(os.path.isfile(path), "Missing phase artifact: {}.".format(name))
    result[name] = fingerprint_file(path)
  return result


def _write_progress(output: str, events: Sequence[Mapping[str, Any]]) -> None:
  path = os.path.join(output, "logs", "progress.jsonl")
  directory = os.path.dirname(path)
  os.makedirs(directory, exist_ok=True)
  descriptor, temporary = tempfile.mkstemp(
      prefix=".pressure-stage7-progress-", suffix=".tmp", dir=directory)
  os.close(descriptor)
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
      for row in events:
        handle.write(json.dumps(
            row, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")) + "\n")
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _prepare_context(config_path: str, run_id: str, project_root: str
                     ) -> Dict[str, Any]:
  project_root = os.path.realpath(project_root)
  config_path = os.path.realpath(config_path)
  _require(_inside(project_root, config_path), "Config must lie inside project root.")
  config = load_json(config_path)
  validate_config(config)
  values, authority_hashes = _load_authorities(config, project_root)
  values["_r1_raw_file_sha256"] = authority_hashes["r1_raw_identity_audit"]
  validate_r4_documents(
      values["final_freeze"], values["pressure_generation_contract"],
      values["r4_run_state"])
  addendum = values.get("pressure_window_selection_addendum")
  if addendum is not None:
    selection_order = validate_pressure_addendum(
        addendum, authority_hashes["final_freeze"],
        authority_hashes["pressure_generation_contract"])
  else:
    selection_order = inspect_selection_order(
        values["pressure_generation_contract"])
  maps = _validate_r1_and_stage7_authorities(values)
  code_sha = _code_sha256(project_root)
  config_sha = fingerprint_file(config_path)
  current_inputs = {}
  local_split_root = _project_file(project_root, config["local_split_root"])
  raw_root = _project_file(project_root, config["raw_trace_root"])
  for workload in ALLOWED_WORKLOADS:
    test_path = os.path.join(local_split_root, workload, "test.csv")
    raw_path = os.path.join(raw_root, workload + ".csv")
    raw_row = maps["raw"][workload]
    identity = validate_source_identity(
        test_path, maps["split"][workload]["splits"]["test"]["sha256"],
        raw_path, raw_row["raw_sha256_declared"])
    current_inputs[workload] = {
        "test_path": test_path, "raw_path": raw_path,
        "test_sha256": identity["test_sha256"],
        "raw_sha256": identity["raw_sha256"],
    }
  identity_value = {
      "authority_sha256": authority_hashes,
      "allowed_workload_current_sha256": {
          workload: {
              "test_sha256": current_inputs[workload]["test_sha256"],
              "raw_sha256": current_inputs[workload]["raw_sha256"],
          } for workload in ALLOWED_WORKLOADS},
      "excluded_test_payload_opened": False,
      "excluded_workloads": list(EXCLUDED_WORKLOADS),
  }
  return {
      "project_root": project_root, "config_path": config_path,
      "config": config, "values": values, "maps": maps,
      "authority_hashes": authority_hashes, "current_inputs": current_inputs,
      "input_identity": identity_value,
      "input_identity_sha256": fingerprint_value(identity_value),
      "config_sha256": config_sha, "code_sha256": code_sha,
      "contract_sha256": authority_hashes["pressure_generation_contract"],
      "addendum_sha256": authority_hashes.get(
          "pressure_window_selection_addendum"),
      "selection_order": selection_order,
      "output": output_root(project_root, run_id), "run_id": run_id,
  }


def _new_state(context: Mapping[str, Any]) -> Dict[str, Any]:
  return {
      "schema_version": SCHEMA_VERSION,
      "run_id": context["run_id"],
      "status": "initialized",
      "input_identity_sha256": context["input_identity_sha256"],
      "config_sha256": context["config_sha256"],
      "code_sha256": context["code_sha256"],
      "completed_phases": [], "phase_artifacts": {},
  }


def _load_state(context: Mapping[str, Any], require_existing: bool = False
                ) -> Dict[str, Any]:
  path = os.path.join(context["output"], "run_state.json")
  if not os.path.isfile(path):
    _require(not require_existing, "Run has not completed preflight.")
    os.makedirs(context["output"], exist_ok=True)
    state = _new_state(context)
    write_json_atomic(path, state)
    return state
  state = load_json(path)
  validate_resume_identity(
      state, context["input_identity_sha256"], context["config_sha256"],
      context["code_sha256"])
  _require(state.get("run_id") == context["run_id"],
           "Existing state run ID mismatch.")
  return state


def _complete_phase(context: Mapping[str, Any], state: Dict[str, Any],
                    phase: str, status: str,
                    artifact_names: Sequence[str]) -> Dict[str, Any]:
  if phase not in state["completed_phases"]:
    state["completed_phases"].append(phase)
  state["status"] = status
  state["phase_artifacts"][phase] = _artifact_rows(
      context["output"], artifact_names)
  write_json_atomic(os.path.join(context["output"], "run_state.json"), state)
  _write_progress(context["output"], [
      {"sequence": index + 1, "phase": item,
       "status": (status if item == phase else "completed")}
      for index, item in enumerate(state["completed_phases"])])
  return state


def run_preflight(config_path: str, run_id: str, project_root: str,
                  resume: bool = False) -> Dict[str, Any]:
  context = _prepare_context(config_path, run_id, project_root)
  state_path = os.path.join(context["output"], "run_state.json")
  existed = os.path.isfile(state_path)
  state = _load_state(context)
  if "preflight" in state["completed_phases"]:
    _require(resume, "Preflight already completed; use --resume.")
    expected = state["phase_artifacts"]["preflight"]
    _require(_artifact_rows(context["output"], sorted(expected)) == expected,
             "Preflight artifact changed; resume rejected.")
    return {"status": "preflight_resumed", "output": context["output"],
            "selection_order_complete": context["selection_order"]["complete"]}
  _require(not existed or state.get("status") == "initialized",
           "Existing run cannot be overwritten.")
  input_identity = {
      "schema_version": SCHEMA_VERSION,
      "run_id": run_id,
      "input_identity_sha256": context["input_identity_sha256"],
      "config_sha256": context["config_sha256"],
      "code_sha256": context["code_sha256"],
      **context["input_identity"],
  }
  resolved = {
      "schema_version": SCHEMA_VERSION,
      "run_id": run_id,
      "formal_freeze": True,
      "authority_sha256": context["authority_hashes"],
      "window_records": context["config"]["scan"]["window_records"],
      "scan_step": context["config"]["scan"]["scan_step"],
      "page_shift": context["config"]["scan"]["page_shift"],
      "selection_order": context["selection_order"],
      "selection_order_contract_sha256": context["contract_sha256"],
      "selection_order_addendum_sha256": context["addendum_sha256"],
      "pressure_generation_allowed": context["selection_order"]["complete"],
      "only_allowed_difference": "evaluation_interval_selection",
  }
  exclusions = {
      "schema_version": SCHEMA_VERSION,
      "excluded": [{"workload": workload,
                    "reason": context["config"]["excluded_workloads"][workload],
                    "test_payload_opened": False,
                    "pressure_generated": False}
                   for workload in EXCLUDED_WORKLOADS],
  }
  write_json_atomic(os.path.join(context["output"], "input_identity.json"),
                    input_identity)
  write_json_atomic(os.path.join(context["output"], "resolved_contract.json"),
                    resolved)
  write_json_atomic(os.path.join(
      context["output"], "pressure_interval_exclusions.json"), exclusions)
  artifacts = ["input_identity.json", "resolved_contract.json",
               "pressure_interval_exclusions.json"]
  status = "PREFLIGHT_COMPLETE"
  if not context["selection_order"]["complete"]:
    status = BLOCKED_STATE
    gap = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATE,
        "formal_contract_path":
            context["config"]["authorities"][
                "pressure_generation_contract"]["path"],
        "formal_contract_sha256": context["contract_sha256"],
        "required_field_path": context["selection_order"]["field_path"],
        "missing_fields": context["selection_order"]["missing_fields"],
        "formal_pressure_csv_generation_allowed": False,
        "pressure_test_lock_generation_allowed": False,
        "manual_selection_allowed": False,
    }
    write_json_atomic(os.path.join(
        context["output"], "pressure_contract_gap_report.json"), gap)
    artifacts.append("pressure_contract_gap_report.json")
  _complete_phase(context, state, "preflight", status, artifacts)
  return {"status": status, "output": context["output"],
          "selection_order_complete": context["selection_order"]["complete"]}


def _candidate_from_stats(context: Mapping[str, Any], workload: str,
                          stats: Mapping[str, Any]) -> Dict[str, Any]:
  watermark = {row["workload"]: row for row in
               context["values"]["final_freeze"]["watermarks"]}[workload]
  source = context["current_inputs"][workload]
  source_trace_id = context["maps"]["lock"][workload]["test_source_id"]
  scan = context["config"]["scan"]
  start = int(stats["split_relative_start"])
  source_start = scan["raw_test_start"] + start
  source_end = scan["raw_test_start"] + stats["split_relative_end_exclusive"]
  candidate = {
      "workload": workload,
      "source_trace_id": source_trace_id,
      "source_test_path": os.path.relpath(
          source["test_path"], context["project_root"]).replace(os.sep, "/"),
      "source_test_sha256": source["test_sha256"],
      "split_relative_start": start,
      "split_relative_end_exclusive": stats["split_relative_end_exclusive"],
      "source_interval_start_inclusive": source_start,
      "source_interval_end_exclusive": source_end,
      "raw_trace_start": source_start,
      "raw_trace_end_exclusive": source_end,
      "window_records": scan["window_records"],
      "scan_step": scan["scan_step"],
      "D": watermark["D"], "F_low": watermark["F_low"],
      "F_target": watermark["F_target"],
      "unique_pages": stats["unique_pages"],
      "reactive_lru_misses": stats["reactive_lru_misses"],
      "reactive_lru_replacement_decisions":
          stats["reactive_lru_replacement_decisions"],
      "pressure_eligible": stats["pressure_eligible"],
      "ineligibility_reasons": json.dumps(
          stats["ineligibility_reasons"], ensure_ascii=False,
          separators=(",", ":")),
      "selection_features_used": json.dumps({
          "eligibility_filter": [
              "unique_pages", "reactive_lru_replacement_decisions"],
          "eligible_window_ranking": [
              field for field, unused in APPROVED_SORT_KEYS]},
          sort_keys=True, separators=(",", ":")),
      "contract_sha256": context["contract_sha256"],
      "addendum_sha256": context["addendum_sha256"],
      "code_sha256": context["code_sha256"],
      "config_sha256": context["config_sha256"],
  }
  candidate["candidate_content_sha256"] = candidate_content_sha256(candidate)
  candidate["candidate_content_sha256_semantics"] = (
      "sha256_of_normalized_source_identity_and_interval")
  return candidate


def run_scan(config_path: str, run_id: str, project_root: str,
             resume: bool = False) -> Dict[str, Any]:
  context = _prepare_context(config_path, run_id, project_root)
  state = _load_state(context, require_existing=True)
  _require("preflight" in state["completed_phases"],
           "Scan requires completed preflight.")
  if "scan" in state["completed_phases"]:
    _require(resume, "Scan already completed; use --resume.")
    expected = state["phase_artifacts"]["scan"]
    _require(_artifact_rows(context["output"], sorted(expected)) == expected,
             "Scan artifact changed; resume rejected.")
    return {"status": "scan_resumed", "output": context["output"]}
  exclusions = context["config"]["excluded_workloads"]
  rows = []
  summary = []
  scan = context["config"]["scan"]
  watermark_map = {row["workload"]: row for row in
                   context["values"]["final_freeze"]["watermarks"]}
  for workload in ALLOWED_WORKLOADS:
    watermark = watermark_map[workload]
    result = scan_workload(
        workload, context["current_inputs"][workload]["test_path"],
        watermark["D"], watermark["F_target"], scan["window_records"],
        scan["scan_step"], exclusions, scan["test_records"],
        scan["page_shift"])
    workload_rows = [
        _candidate_from_stats(context, workload, item)
        for item in result["candidates"]]
    rows.extend(workload_rows)
    summary.append({
        "workload": workload, "status": "scanned",
        "candidate_count": len(workload_rows),
        "eligible_candidate_count": sum(
            1 for item in workload_rows if item["pressure_eligible"]),
        "test_payload_opened": True,
        "selected_window": None,
    })
  for workload in EXCLUDED_WORKLOADS:
    result = scan_workload(
        workload, "FORBIDDEN_EXCLUDED_TEST", watermark_map[workload]["D"],
        watermark_map[workload]["F_target"], scan["window_records"],
        scan["scan_step"], exclusions)
    summary.append({
        "workload": workload, "status": result["status"],
        "reason": result["reason"], "candidate_count": 0,
        "eligible_candidate_count": 0, "test_payload_opened": False,
        "selected_window": None,
    })
  reject_prohibited_selection_fields(rows)
  write_csv_atomic(
      os.path.join(context["output"], "pressure_candidates.csv"), rows,
      CANDIDATE_FIELDS)
  summary_value = {
      "schema_version": SCHEMA_VERSION,
      "status": (BLOCKED_STATE if not context["selection_order"]["complete"]
                 else "PRESSURE_CANDIDATES_SCANNED"),
      "candidate_total": len(rows),
      "eligible_candidate_total": sum(
          1 for row in rows if row["pressure_eligible"]),
      "selection_order_complete": context["selection_order"]["complete"],
      "formal_pressure_generated": False,
      "workloads": summary,
  }
  assert_no_overhead_claims(summary_value)
  write_json_atomic(os.path.join(
      context["output"], "pressure_eligibility_summary.json"), summary_value)
  status = summary_value["status"]
  _complete_phase(context, state, "scan", status, [
      "pressure_candidates.csv", "pressure_eligibility_summary.json"])
  return {"status": status, "candidate_total": len(rows),
          "eligible_candidate_total": summary_value["eligible_candidate_total"],
          "output": context["output"]}


def _read_candidates(path: str) -> List[Dict[str, Any]]:
  rows = []
  with open(path, "r", encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle):
      for field in (
          "split_relative_start", "split_relative_end_exclusive",
          "source_interval_start_inclusive",
          "source_interval_end_exclusive",
          "raw_trace_start", "raw_trace_end_exclusive", "window_records",
          "scan_step", "D", "F_low", "F_target", "unique_pages",
          "reactive_lru_misses", "reactive_lru_replacement_decisions"):
        row[field] = int(row[field])
      row["pressure_eligible"] = row["pressure_eligible"].lower() == "true"
      rows.append(row)
  return rows


def verify_candidate_content_sha256(candidate: Mapping[str, Any]) -> None:
  declared = candidate.get("candidate_content_sha256")
  _require(isinstance(declared, str) and len(declared) == 64,
           "Candidate canonical SHA256 is missing.")
  _require(candidate.get("candidate_content_sha256_semantics") ==
           "sha256_of_normalized_source_identity_and_interval",
           "Candidate canonical SHA semantics mismatch.")
  _require(candidate_content_sha256(candidate) == declared,
           "Candidate canonical SHA256 mismatch.")


def run_derive(config_path: str, run_id: str, project_root: str,
               resume: bool = False) -> Dict[str, Any]:
  context = _prepare_context(config_path, run_id, project_root)
  state = _load_state(context, require_existing=True)
  _require("scan" in state["completed_phases"],
           "Derive requires completed scan.")
  _require(context["selection_order"]["complete"],
           BLOCKED_STATE + ": formal derive and pressure_test_lock are forbidden.")
  _require(context["addendum_sha256"] is not None,
           "Formal Pressure derive requires a separately frozen addendum.")
  if "derive" in state["completed_phases"]:
    _require(resume, "Derive already completed; use --resume.")
    expected = state["phase_artifacts"]["derive"]
    _require(_artifact_rows(context["output"], sorted(expected)) == expected,
             "Derive artifact changed; resume rejected.")
    return {"status": "derive_resumed", "output": context["output"]}
  candidates = _read_candidates(os.path.join(
      context["output"], "pressure_candidates.csv"))
  for candidate in candidates:
    verify_candidate_content_sha256(candidate)
  addendum = context["values"]["pressure_window_selection_addendum"]
  manifest_rows = []
  no_eligible = []
  for workload in ALLOWED_WORKLOADS:
    selected = select_pressure_candidate(
        [row for row in candidates if row["workload"] == workload], addendum)
    if selected is None:
      no_eligible.append({
          "workload": workload,
          "reason": "no_candidate_satisfied_parent_r4_eligibility_rule",
          "pressure_generated": False})
      continue
    source = context["current_inputs"][workload]
    raw_before = fingerprint_file(source["raw_path"])
    destination = os.path.join(
        context["output"], "derived_pressure", workload, "pressure.csv")
    result = derive_pressure_csv(
        source["test_path"], destination,
        selected["split_relative_start"], selected["window_records"])
    raw_after = fingerprint_file(source["raw_path"])
    _require(raw_before == raw_after == source["raw_sha256"],
             "Raw trace changed during Pressure derivation.")
    verify_derived_rows(
        source["test_path"], destination,
        selected["split_relative_start"], selected["window_records"])
    manifest_rows.append({
        **selected,
        "derived_path": os.path.relpath(
            destination, context["project_root"]).replace(os.sep, "/"),
        "derived_sha256": result["derived_sha256"],
        "raw_trace_sha256_before": raw_before,
        "raw_trace_sha256_after": raw_after,
    })
  _require(manifest_rows, "No eligible Pressure interval exists; no data fabricated.")
  derivation_exclusions = {
      "schema_version": SCHEMA_VERSION, "run_id": run_id,
      "parent_contract_exclusions": [
          {"workload": workload,
           "reason": context["config"]["excluded_workloads"][workload],
           "pressure_generated": False}
          for workload in EXCLUDED_WORKLOADS],
      "no_eligible_exclusions": no_eligible}
  manifest = {
      "schema_version": SCHEMA_VERSION, "run_id": run_id,
      "pressure_window_selection_rule":
          "earliest_eligible_window_in_source_trace",
      "parent_pressure_contract_sha256": context["contract_sha256"],
      "pressure_window_selection_addendum_sha256":
          context["addendum_sha256"],
      "windows": manifest_rows}
  lock = {
      "schema_version": SCHEMA_VERSION, "run_id": run_id,
      "pressure_overhead_claims_allowed": False,
      "test_used_for_stage3_selection": False,
      "capd_or_oracle_used_for_pressure_selection": False,
      "selection_policy": "fixed_reactive_lru_only",
      "standard_pressure_hard_principle_satisfied": True,
      "only_allowed_difference": "evaluation_interval_selection",
      "selection_order_field_path": context["selection_order"]["field_path"],
      "selection_order_contract_sha256": context["contract_sha256"],
      "pressure_window_selection_rule":
          "earliest_eligible_window_in_source_trace",
      "pressure_window_selection_addendum_sha256":
          context["addendum_sha256"],
      "eligible_window_ranking_metrics": [],
      "workloads": manifest_rows,
  }
  assert_no_overhead_claims(lock)
  write_json_atomic(os.path.join(
      context["output"], "pressure_window_manifest.json"), manifest)
  write_json_atomic(os.path.join(
      context["output"], "pressure_test_lock.json"), lock)
  write_json_atomic(os.path.join(
      context["output"], "pressure_derivation_exclusions.json"),
                    derivation_exclusions)
  bundle_files = [
      "input_identity.json", "resolved_contract.json",
      "pressure_candidates.csv", "pressure_eligibility_summary.json",
      "pressure_interval_exclusions.json", "pressure_window_manifest.json",
      "pressure_test_lock.json", "pressure_derivation_exclusions.json"] + [
          os.path.relpath(row["derived_path"], context["project_root"])
          if os.path.isabs(row["derived_path"]) else
          row["derived_path"].split(
              "outputs/capd_proactive_pressure_stage7/{}/".format(run_id), 1)[-1]
          for row in manifest_rows]
  bundle = {
      "schema_version": SCHEMA_VERSION, "run_id": run_id,
      "formal_pressure_bundle": True,
      "authority_sha256": {
          "parent_pressure_contract": context["contract_sha256"],
          "pressure_window_selection_addendum": context["addendum_sha256"]},
      "artifacts": _artifact_rows(context["output"], bundle_files),
  }
  write_json_atomic(os.path.join(
      context["output"], "local_pressure_bundle_manifest.json"), bundle)
  _complete_phase(context, state, "derive", "PRESSURE_DERIVED", [
      "pressure_window_manifest.json", "pressure_test_lock.json",
      "pressure_derivation_exclusions.json",
      "local_pressure_bundle_manifest.json"])
  return {"status": "PRESSURE_DERIVED", "derived_workloads":
          [row["workload"] for row in manifest_rows],
          "output": context["output"]}


def _verify_phase_artifacts(context: Mapping[str, Any],
                            state: Mapping[str, Any]) -> None:
  for phase, expected in state.get("phase_artifacts", {}).items():
    actual = _artifact_rows(context["output"], sorted(expected))
    _require(actual == expected,
             "{} artifact SHA changed after completion.".format(phase))


def run_verify(config_path: str, run_id: str, project_root: str,
               resume: bool = False) -> Dict[str, Any]:
  context = _prepare_context(config_path, run_id, project_root)
  state = _load_state(context, require_existing=True)
  _require("preflight" in state["completed_phases"] and
           "scan" in state["completed_phases"],
           "Verify requires preflight and scan.")
  _verify_phase_artifacts(context, state)
  if "verify" in state["completed_phases"]:
    _require(resume, "Verify already completed; use --resume.")
    return {"status": "verify_resumed", "output": context["output"]}
  candidates = _read_candidates(os.path.join(
      context["output"], "pressure_candidates.csv"))
  for candidate in candidates:
    verify_candidate_content_sha256(candidate)
  expected_count = len(ALLOWED_WORKLOADS) * len(candidate_starts(
      context["config"]["scan"]["test_records"],
      context["config"]["scan"]["window_records"],
      context["config"]["scan"]["scan_step"]))
  _require(len(candidates) == expected_count,
           "Pressure candidate table is incomplete.")
  reject_prohibited_selection_fields(candidates)
  summary = load_json(os.path.join(
      context["output"], "pressure_eligibility_summary.json"))
  assert_no_overhead_claims(summary)
  excluded_summary = {row["workload"]: row for row in summary["workloads"]
                      if row["workload"] in EXCLUDED_WORKLOADS}
  _require(set(excluded_summary) == set(EXCLUDED_WORKLOADS) and all(
      row.get("test_payload_opened") is False and
      row.get("candidate_count") == 0 for row in excluded_summary.values()),
      "Excluded workload isolation was not preserved.")
  blocked = not context["selection_order"]["complete"]
  if blocked:
    _require(os.path.isfile(os.path.join(
        context["output"], "pressure_contract_gap_report.json")),
        "Missing contract gap report.")
    _require(not os.path.exists(os.path.join(
        context["output"], "derived_pressure")),
        "Formal Pressure CSV exists despite incomplete selection contract.")
    _require(not os.path.exists(os.path.join(
        context["output"], "pressure_test_lock.json")),
        "pressure_test_lock exists despite incomplete selection contract.")
    status = BLOCKED_COMPLETION
  else:
    _require("derive" in state["completed_phases"],
             "Complete selection contract requires derive before verify.")
    addendum = context["values"]["pressure_window_selection_addendum"]
    manifest = load_json(os.path.join(
        context["output"], "pressure_window_manifest.json"))
    lock = load_json(os.path.join(
        context["output"], "pressure_test_lock.json"))
    bundle = load_json(os.path.join(
        context["output"], "local_pressure_bundle_manifest.json"))
    _require(manifest.get("pressure_window_selection_rule") ==
             "earliest_eligible_window_in_source_trace" and
             manifest.get("parent_pressure_contract_sha256") ==
             context["contract_sha256"] and
             manifest.get("pressure_window_selection_addendum_sha256") ==
             context["addendum_sha256"],
             "Pressure window manifest authority binding mismatch.")
    _require(lock.get("pressure_window_selection_rule") ==
             "earliest_eligible_window_in_source_trace" and
             lock.get("pressure_window_selection_addendum_sha256") ==
             context["addendum_sha256"] and
             lock.get("eligible_window_ranking_metrics") == [] and
             lock.get("capd_or_oracle_used_for_pressure_selection") is False,
             "Pressure Test lock selection/audit binding mismatch.")
    manifest_by_workload = _map_by_workload(manifest.get("windows", []))
    expected_derived_workloads = set()
    identity_fields = (
        "source_interval_start_inclusive", "source_interval_end_exclusive",
        "source_trace_id", "candidate_content_sha256")
    for workload in ALLOWED_WORKLOADS:
      expected = select_pressure_candidate(
          [row for row in candidates if row["workload"] == workload],
          addendum)
      if expected is None:
        _require(workload not in manifest_by_workload,
                 "No-eligible workload unexpectedly has Pressure data.")
        continue
      expected_derived_workloads.add(workload)
      _require(workload in manifest_by_workload,
               "Eligible workload is missing its Pressure window.")
      actual = manifest_by_workload[workload]
      _require(all(actual.get(field) == expected.get(field)
                   for field in identity_fields),
               "Selected Pressure window does not match the approved earliest "
               "eligible order for {}.".format(workload))
      source = context["current_inputs"][workload]
      derived_path = _project_file(
          context["project_root"], actual["derived_path"])
      verify_derived_rows(
          source["test_path"], derived_path,
          int(actual["split_relative_start"]),
          int(actual["window_records"]))
      _require(fingerprint_file(derived_path) == actual["derived_sha256"],
               "Derived Pressure SHA mismatch for {}.".format(workload))
      _require(fingerprint_file(source["test_path"]) ==
               actual["source_test_sha256"] == source["test_sha256"],
               "Source Test changed for {}.".format(workload))
      _require(fingerprint_file(source["raw_path"]) ==
               actual["raw_trace_sha256_before"] ==
               actual["raw_trace_sha256_after"] == source["raw_sha256"],
               "Raw trace changed for {}.".format(workload))
    _require(set(manifest_by_workload) == expected_derived_workloads,
             "Pressure manifest workload set differs from eligible workloads.")
    _require(bundle.get("formal_pressure_bundle") is True and
             bundle.get("authority_sha256") == {
                 "parent_pressure_contract": context["contract_sha256"],
                 "pressure_window_selection_addendum":
                     context["addendum_sha256"]},
             "Formal Pressure bundle authority binding mismatch.")
    expected_bundle_artifacts = bundle.get("artifacts", {})
    _require(_artifact_rows(
        context["output"], sorted(expected_bundle_artifacts)) ==
        expected_bundle_artifacts,
        "Formal Pressure bundle artifact SHA mismatch.")
    status = FORMAL_COMPLETION
  verification = {
      "schema_version": SCHEMA_VERSION, "run_id": run_id,
      "status": status,
      "r1_authority_sha_verified": True,
      "r4_authority_sha_verified": True,
      "formal_freeze_verified": True,
      "standard_pressure_capacity_identity_verified": True,
      "excluded_workload_payload_isolation_verified": True,
      "candidate_count_verified": len(candidates),
      "selection_order_complete": not blocked,
      "formal_pressure_test_generated": not blocked,
      "pressure_overhead_claims_allowed": False,
      "stage4_read_or_executed": False,
      "stage8_read_or_executed": False,
      "model_training_executed": False,
      "capd_or_oracle_used_for_selection": False,
  }
  write_json_atomic(os.path.join(
      context["output"], "verification.json"), verification)
  _complete_phase(context, state, "verify", status, ["verification.json"])
  return {"status": status, "candidate_count": len(candidates),
          "formal_pressure_test_generated": not blocked,
          "output": context["output"]}


def run_all(config_path: str, run_id: str, project_root: str,
            resume: bool = False) -> Dict[str, Any]:
  preflight = run_preflight(
      config_path, run_id, project_root, resume=resume)
  scan = run_scan(config_path, run_id, project_root, resume=resume)
  context = _prepare_context(config_path, run_id, project_root)
  derive = None
  if context["selection_order"]["complete"]:
    derive = run_derive(config_path, run_id, project_root, resume=resume)
  verify = run_verify(config_path, run_id, project_root, resume=resume)
  return {"preflight": preflight, "scan": scan, "derive": derive,
          "verify": verify, "status": verify["status"]}
