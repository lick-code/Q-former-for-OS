# coding=utf-8
"""Stage-6 TPP-inspired contracts, entry audit, selection, and fairness."""

from __future__ import annotations

import copy
import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from qmap import proactive_stage4
from qmap import proactive_stage5_contract as stage5


SCHEMA_VERSION = "capd_proactive_stage6_tpp_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE6-TPP-1.0"
RESULT_SCHEMA_VERSION = "capd_proactive_stage6_tpp_result_v1_0"
IMPLEMENTED = "stage6_implemented_awaiting_validation"
RESULTS_READY = "stage6_results_ready_for_freeze"
VERIFIED = "stage6_tpp_inspired_verified"
NOT_VERIFIED = "stage6_not_verified"
POLICY = "tpp_inspired"
DISPLAY_NAME = "TPP-inspired"
EPOCH_LENGTHS = (64, 256, 1024)
COLD_THRESHOLDS = (1, 2)
DIRTY_TIE_BREAKS = (False, True)
EXPECTED_GRID_SIZE = 12
FROZEN_COST = dict(stage5.FROZEN_COST)
FROZEN_METHOD = dict(
    stage5.FROZEN_METHOD,
    capacity_claim="conditional_engineering_default_not_capacity_rule_v2_pass",
    initial_state="empty_dram_all_seen_pages_backed_by_nvm",
    early_reuse_window_accesses=64)
STAGE5_R4_RELATIVE_ROOT = (
    "outputs/capd_proactive_stage5/stage5-baseline-r4")
LEGACY_TPP_STAGE6_RE = re.compile(
    r"(?:^|/)(?:outputs/results/finals_v3_official/"
    r"(?:stage6|tpp)(?:[_.-][^/]*)?|old_tpp|legacy_tpp)(?:/|$)",
    re.IGNORECASE)


class Stage6ContractError(ValueError):
  """Raised when Stage-6 input, results, or selection violate the freeze."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage6ContractError(message)


def load_config(path: str) -> Dict[str, Any]:
  value = proactive_stage4.load_json(path)
  validate_config(value)
  return value


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Stage-6 config must be an object.")
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Stage-6 schema_version mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Stage-6 contract_id mismatch.")
  _require(value.get("stage_status") == IMPLEMENTED,
           "Stage-6 source config must remain a predeclared implemented state.")
  _require(value.get("result_schema") ==
           "configs/finals/capd_proactive_stage6_tpp_result_schema.json",
           "Stage-6 unified result schema binding changed.")
  _require(tuple(value.get("allowed_splits", ())) == ("train", "validation"),
           "Stage 6 allows only Train/Validation.")
  _require(tuple(value.get("forbidden_splits", ())) == ("test",),
           "Stage 6 must explicitly forbid Test.")
  _require(value.get("frozen_method") == FROZEN_METHOD,
           "Stage-3/4/5 method freeze changed in Stage 6.")
  _require(value.get("frozen_stage4") == {
      "lookahead_L": 256,
      "label_weights": [1, 1, 2],
      "history_H": 20,
      "capd_seeds": [3136859, 42, 2026],
  }, "Stage-4 model/Oracle freeze changed in Stage 6.")
  _require(value.get("cost_profile", {}).get("name") == "default" and
           value["cost_profile"].get("weights") == FROZEN_COST,
           "Stage-2 Cost profile changed in Stage 6.")
  tpp = value.get("tpp_inspired", {})
  _require(tpp.get("display_name") == DISPLAY_NAME and
           tpp.get("implementation") == "replay_compatible_adaptation" and
           tpp.get("stage6_runnable") is True and
           tpp.get("stage5_status_unchanged") == stage5.PENDING_TPP,
           "TPP-inspired naming or Stage-5 compatibility changed.")
  _require(tpp.get("fallback_to_lru_allowed") is False and
           tpp.get("promotion_allowed") is False and
           tpp.get("future_information_allowed") is False,
           "TPP fallback/promotion/future-information guard changed.")
  grid = value.get("validation_grid", {})
  _require(tuple(grid.get("epoch_length_accesses", ())) == EPOCH_LENGTHS and
           tuple(grid.get("cold_threshold_epochs", ())) ==
           COLD_THRESHOLDS and
           tuple(grid.get("dirty_tie_break", ())) == DIRTY_TIE_BREAKS and
           grid.get("expected_configuration_count") == EXPECTED_GRID_SIZE,
           "The predeclared 12-configuration grid changed.")
  _require(grid.get("split") == "validation" and
           grid.get("full_frozen_interval_required") is True and
           grid.get("per_workload_selection_forbidden") is True,
           "Validation-only global selection contract changed.")
  selection = value.get("selection_rule", {})
  expected_selection = {
      "version": "stage6_tpp_global_selection_v1_0",
      "primary_metric":
          "validation_macro_weighted_cost_per_access",
      "aggregation":
          "unweighted_macro_mean_across_all_validation_workloads",
      "near_best_relative_tolerance": 0.01,
      "maximum_worst_workload_relative_gap": 0.10,
      "maximum_nvm_write_rate_relative_to_grid_minimum": 1.10,
      "nvm_write_rate_absolute_slack": 1e-06,
      "maximum_early_reuse_rate_absolute_gap": 0.05,
      "maximum_cold_short_reuse_rate_absolute_gap": 0.05,
      "require_zero_emergency_fallback": True,
      "require_zero_free_frame_exhaustion": True,
  }
  for key, expected in expected_selection.items():
    _require(selection.get(key) == expected,
             "Selection rule field {} changed.".format(key))
  _require(value.get("acceptance", {}).get("formal_test_allowed") is False and
           value["acceptance"].get("performance_conclusions_allowed") is False,
           "Stage 6 cannot run Test or form performance conclusions.")
  _require(value["acceptance"].get(
      "minimum_stage1_through_stage6_regression_tests") == 146,
      "Stage1-6 minimum regression coverage changed.")
  return value


def parameter_id(epoch_length: int, cold_threshold: int,
                 dirty_tie_break: bool) -> str:
  validate_tpp_parameters(
      epoch_length, cold_threshold, dirty_tie_break)
  return "tpp-e{:04d}-c{}-d{}".format(
      int(epoch_length), int(cold_threshold),
      "on" if dirty_tie_break else "off")


def validate_tpp_parameters(epoch_length: int, cold_threshold: int,
                            dirty_tie_break: bool) -> None:
  _require(
      isinstance(epoch_length, int) and not isinstance(epoch_length, bool) and
      epoch_length in EPOCH_LENGTHS,
      "epoch_length must be one of 64/256/1024.")
  _require(
      isinstance(cold_threshold, int) and
      not isinstance(cold_threshold, bool) and
      cold_threshold in COLD_THRESHOLDS,
      "cold_threshold must be 1 or 2.")
  _require(isinstance(dirty_tie_break, bool),
           "dirty_tie_break must be boolean.")


def parameter_grid() -> List[Dict[str, Any]]:
  rows = []
  for epoch_length in EPOCH_LENGTHS:
    for cold_threshold in COLD_THRESHOLDS:
      for dirty_tie_break in DIRTY_TIE_BREAKS:
        rows.append({
            "experiment_id": parameter_id(
                epoch_length, cold_threshold, dirty_tie_break),
            "epoch_length": epoch_length,
            "cold_threshold": cold_threshold,
            "dirty_tie_break": dirty_tie_break,
        })
  _require(len(rows) == EXPECTED_GRID_SIZE and
           len({row["experiment_id"] for row in rows}) ==
           EXPECTED_GRID_SIZE,
           "TPP grid is incomplete or duplicated.")
  return rows


def _authority_path(project_root: str, recorded_path: str) -> str:
  return stage5.resolve_repository_path(
      recorded_path, project_root,
      ("outputs/capd_proactive_stage5/stage5-baseline-r4", "configs/finals"),
      must_exist=True)


def audit_stage5_entry(config: Mapping[str, Any],
                       project_root: str) -> Dict[str, Any]:
  """Validates the immutable r4 Stage-5 entry evidence and all evidence SHA."""
  validate_config(config)
  authority = config["stage5_entry_authority"]
  loaded = {}
  resolved = {}
  for key in ("verification", "run_state", "fairness_audit", "stage5_config"):
    path = _authority_path(project_root, authority[key])
    _require(proactive_stage4.fingerprint_file(path) ==
             authority[key + "_sha256"],
             "Stage-5 r4 authority SHA mismatch: {}.".format(key))
    loaded[key] = proactive_stage4.load_json(path)
    resolved[key] = path
  verification = loaded["verification"]
  run_state = loaded["run_state"]
  fairness = loaded["fairness_audit"]
  stage5_config = loaded["stage5_config"]
  stage5.validate_config(stage5_config)
  _require(verification.get("status") == stage5.VERIFIED and
           verification.get("stage6_entry_gate") == "satisfied",
           "Stage-5 r4 entry gate is not satisfied.")
  _require(run_state.get("status") == stage5.VERIFIED,
           "Stage-5 r4 run_state is not verified.")
  _require(verification.get("tpp_inspired_status") == stage5.PENDING_TPP and
           run_state.get("tpp_inspired_status") == stage5.PENDING_TPP,
           "Stage-5 TPP placeholder was altered.")
  _require(verification.get("test_trace_opened") is False and
           run_state.get("test_trace_opened") is False and
           fairness.get("test_trace_opened") is False,
           "Stage-5 entry evidence reports Test access.")
  _require(verification.get("old_finals_v3_stage_artifacts_used") is False,
           "Stage-5 entry evidence used historical Stage4/5 artifacts.")
  _require(verification.get("performance_conclusion") is None and
           fairness.get("performance_conclusion") is None,
           "Stage-5 entry contains a forbidden performance conclusion.")
  _require(fairness.get("status") == "passed",
           "Stage-5 r4 fairness audit did not pass.")
  verification_root = os.path.dirname(resolved["verification"])
  for filename, digest in verification.get("evidence_sha256", {}).items():
    path = os.path.join(verification_root, filename)
    _require(os.path.isfile(path) and
             proactive_stage4.fingerprint_file(path) == digest,
             "Stage-5 r4 evidence SHA mismatch: {}.".format(filename))
  return {
      "status": stage5.VERIFIED,
      "stage6_entry_gate": "satisfied",
      "tpp_inspired_status": stage5.PENDING_TPP,
      "test_trace_opened": False,
      "old_finals_v3_stage_artifacts_used": False,
      "resolved_paths": resolved,
      "sha256": {
          key: authority[key + "_sha256"] for key in resolved},
  }


def audit_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(result.get("schema_version") == RESULT_SCHEMA_VERSION,
           "Result schema is not proactive Stage 6 TPP.")
  _require(result.get("contract_id") == CONTRACT_ID,
           "Stage-6 result contract ID mismatch.")
  _require(result.get("policy") == POLICY and
           result.get("policy_display_name") == DISPLAY_NAME,
           "Stage-6 result is not TPP-inspired.")
  _require(result.get("split") in ("train", "validation") and
           result.get("split") != "test" and
           result.get("formal_test") is False and
           result.get("test_used_for_selection") is False,
           "Stage-6 result contains Test contamination.")
  _require(result.get("selector_status") == "disabled" and
           result.get("old_finals_v3_stage_artifacts_used") is False,
           "Stage-6 result contains selector/legacy contamination.")
  _require(result.get("future_information") == "not_accessed" and
           result.get("promotion_performed") is False and
           result.get("tpp_fallback_used") is False,
           "TPP used future information, promotion, or an LRU substitute.")
  _require(result.get("invariant_mode") in ("full", "boundary") and
           result.get("final_full_invariant_check") is True,
           "TPP result lacks its final full state invariant check.")
  _require(result.get("cost_profile") == {
      "name": "default", "weights": FROZEN_COST},
      "Stage-6 result Cost profile changed.")
  _require((result.get("F_low"), result.get("F_target"),
            result.get("candidate_size_K"), result.get("b_max")) ==
           (8, 16, 8, 4), "Stage-6 proactive controls changed.")
  _require(result.get("candidate_source") == "lru_tail" and
           result.get("fallback_policy") == "lru" and
           result.get("trigger_mode") == "low_watermark",
           "Stage-6 trigger/candidate/fallback contract changed.")
  params = result.get("tpp_parameters", {})
  validate_tpp_parameters(
      params.get("epoch_length"), params.get("cold_threshold"),
      params.get("dirty_tie_break"))
  _require(params.get("experiment_id") == parameter_id(
      params["epoch_length"], params["cold_threshold"],
      params["dirty_tie_break"]),
      "TPP experiment ID does not match its parameters.")
  summary = result.get("summary", {})
  _require(result.get("raw_access_event_count") ==
           summary.get("total_accesses"),
           "Raw event count differs from Replay accounting.")
  _require(summary.get("total_accesses") ==
           summary.get("dram_hits", 0) + summary.get("nvm_reads", 0) +
           summary.get("nvm_writes", 0),
           "TPP access accounting mismatch.")
  _require(summary.get("total_demotions") ==
           summary.get("proactive_demotions", 0) +
           summary.get("emergency_demotions", 0) and
           summary.get("reactive_demotions") == 0,
           "TPP demotion event accounting is mixed.")
  _require(all(event.get("event_type") in (
      "proactive_demotion", "emergency_fallback_demotion")
      for event in result.get("events", [])),
      "TPP result contains an invalid event type.")
  for row in result.get("rounds", []):
    candidates = row.get("candidate_pages", [])
    ranking = row.get("policy_scores", [])
    _require(len(candidates) <= 8 and len(candidates) == len(set(candidates)),
             "TPP candidate snapshot is padded/duplicated/oversized.")
    _require(row.get("candidate_pages_sha256") ==
             proactive_stage4.fingerprint_value(candidates),
             "TPP candidate fingerprint mismatch.")
    _require(set(row.get("selected_pages", ())).issubset(set(candidates)),
             "TPP selected outside the immutable candidate snapshot.")
    _require(len(ranking) == len(candidates) and
             {item.get("page") for item in ranking} == set(candidates),
             "TPP ranking does not exactly cover its candidate snapshot.")
    _require(all(all(key in item for key in (
        "referenced_current_epoch", "referenced_previous_epoch",
        "last_access_epoch", "age_in_epochs", "temperature", "dirty",
        "lru_tail_rank", "ranking_key")) for item in ranking),
        "TPP candidate audit fields are incomplete.")
  return result


def _safe_rate(numerator: float, denominator: float) -> float:
  return float(numerator) / float(denominator) if denominator else 0.0


def _complexity_rank(parameters: Mapping[str, Any],
                     rule: Mapping[str, Any]) -> Tuple[int, int, int]:
  preference = rule["complexity_preference"]
  return (
      preference["dirty_tie_break"].index(parameters["dirty_tie_break"]),
      preference["cold_threshold"].index(parameters["cold_threshold"]),
      preference["epoch_length"].index(parameters["epoch_length"]),
  )


def select_global_configuration(
    records: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> Dict[str, Any]:
  """Selects exactly one global configuration from all full Validation jobs."""
  validate_config(config)
  rows = [audit_result(row) for row in records]
  _require(rows, "No Stage-6 Validation records were supplied.")
  _require(all(row["split"] == "validation" for row in rows),
           "Global TPP selection accepts Validation only.")
  workloads = sorted({row["workload"] for row in rows})
  _require(len(workloads) >= 1, "Global selection has no workloads.")
  grid_ids = [row["experiment_id"] for row in parameter_grid()]
  by_id: Dict[str, Dict[str, Mapping[str, Any]]] = {
      experiment_id: {} for experiment_id in grid_ids}
  for row in rows:
    experiment_id = row["tpp_parameters"]["experiment_id"]
    _require(experiment_id in by_id,
             "Result is outside the frozen Stage-6 grid.")
    _require(row["workload"] not in by_id[experiment_id],
             "Duplicate workload/config result.")
    by_id[experiment_id][row["workload"]] = row
  for experiment_id, workload_rows in by_id.items():
    _require(sorted(workload_rows) == workloads,
             "{} does not cover the same global workload set.".format(
                 experiment_id))
  workload_best = {}
  for workload in workloads:
    workload_best[workload] = min(
        _safe_rate(by_id[experiment_id][workload]["summary"]["weighted_cost"],
                   by_id[experiment_id][workload]["summary"]["total_accesses"])
        for experiment_id in grid_ids)
  aggregates = []
  for grid_row in parameter_grid():
    experiment_id = grid_row["experiment_id"]
    config_rows = [by_id[experiment_id][workload]
                   for workload in workloads]
    cost_rates = [
        _safe_rate(row["summary"]["weighted_cost"],
                   row["summary"]["total_accesses"])
        for row in config_rows]
    workload_gaps = [
        (rate - workload_best[workload]) /
        max(abs(workload_best[workload]), 1e-12)
        for workload, rate in zip(workloads, cost_rates)]
    total_accesses = sum(row["summary"]["total_accesses"]
                         for row in config_rows)
    total_proactive = sum(row["summary"]["proactive_demotions"]
                          for row in config_rows)
    total_early = sum(row["summary"]["early_reuse_count"]
                      for row in config_rows)
    total_nvm_writes = sum(row["summary"]["nvm_writes"]
                           for row in config_rows)
    total_cold_selected = sum(
        row["summary"]["tpp"]["cold_selected_count"]
        for row in config_rows)
    total_cold_reuse = sum(
        row["summary"]["tpp"]["cold_short_reuse_count"]
        for row in config_rows)
    transitions = sum(
        row["summary"]["tpp"]["epoch_transition_count"]
        for row in config_rows)
    aggregates.append({
        "experiment_id": experiment_id,
        "parameters": {
            key: grid_row[key] for key in (
                "epoch_length", "cold_threshold", "dirty_tie_break")},
        "macro_weighted_cost_per_access":
            sum(cost_rates) / float(len(cost_rates)),
        "worst_workload_relative_gap": max(workload_gaps),
        "workload_weighted_cost_per_access": dict(
            zip(workloads, cost_rates)),
        "nvm_write_rate": _safe_rate(total_nvm_writes, total_accesses),
        "early_reuse_rate": _safe_rate(total_early, total_proactive),
        "cold_short_reuse_rate":
            _safe_rate(total_cold_reuse, total_cold_selected),
        "demotion_rate": _safe_rate(total_proactive, total_accesses),
        "epoch_transition_rate": _safe_rate(transitions, total_accesses),
        "emergency_fallback_count": sum(
            row["summary"]["emergency_demotions"] for row in config_rows),
        "free_frame_exhaustion_count": sum(
            row["summary"]["free_frame_exhaustion_count"]
            for row in config_rows),
        "semantic_result_sha256": {
            row["workload"]: row["semantic_result_sha256"]
            for row in config_rows},
    })
  rule = config["selection_rule"]
  minimum_nvm = min(item["nvm_write_rate"] for item in aggregates)
  minimum_early = min(item["early_reuse_rate"] for item in aggregates)
  minimum_cold_reuse = min(item["cold_short_reuse_rate"]
                           for item in aggregates)
  for item in aggregates:
    reasons = []
    if (rule["require_zero_emergency_fallback"] and
        item["emergency_fallback_count"] != 0):
      reasons.append("nonzero_emergency_fallback")
    if (rule["require_zero_free_frame_exhaustion"] and
        item["free_frame_exhaustion_count"] != 0):
      reasons.append("nonzero_free_frame_exhaustion")
    if item["worst_workload_relative_gap"] > (
        rule["maximum_worst_workload_relative_gap"]):
      reasons.append("worst_workload_gap")
    nvm_limit = (
        minimum_nvm *
        rule["maximum_nvm_write_rate_relative_to_grid_minimum"] +
        rule["nvm_write_rate_absolute_slack"])
    if item["nvm_write_rate"] > nvm_limit:
      reasons.append("nvm_write_rate")
    if item["early_reuse_rate"] > (
        minimum_early + rule["maximum_early_reuse_rate_absolute_gap"]):
      reasons.append("early_reuse_rate")
    if item["cold_short_reuse_rate"] > (
        minimum_cold_reuse +
        rule["maximum_cold_short_reuse_rate_absolute_gap"]):
      reasons.append("cold_short_reuse_rate")
    item["eligible"] = not reasons
    item["exclusion_reasons"] = reasons
  eligible = [item for item in aggregates if item["eligible"]]
  _require(eligible,
           "No configuration survives the predeclared anomaly guards; "
           "preserve evidence and do not select post hoc.")
  minimum_macro = min(
      item["macro_weighted_cost_per_access"] for item in eligible)
  for item in aggregates:
    item["near_best"] = (
        item["eligible"] and
        item["macro_weighted_cost_per_access"] <=
        minimum_macro * (1.0 + rule["near_best_relative_tolerance"]))
  candidates = [item for item in aggregates if item["near_best"]]
  _require(candidates,
           "No configuration survives the predeclared eligibility/near-best "
           "rule; preserve evidence and do not select post hoc.")
  selected = min(candidates, key=lambda item: (
      item["worst_workload_relative_gap"],
      item["nvm_write_rate"],
      item["early_reuse_rate"],
      item["cold_short_reuse_rate"],
      item["demotion_rate"],
      item["epoch_transition_rate"],
      _complexity_rank(item["parameters"], rule),
      item["experiment_id"],
  ))
  selection_inputs = {
      "workloads": workloads,
      "grid": aggregates,
      "selection_rule": copy.deepcopy(rule),
  }
  return {
      "schema_version": "capd_proactive_stage6_selection_v1_0",
      "contract_id": CONTRACT_ID,
      "status": RESULTS_READY,
      "split": "validation",
      "full_frozen_validation_intervals": True,
      "workloads": workloads,
      "configuration_count": len(aggregates),
      "global_configuration_only": True,
      "selected_experiment_id": selected["experiment_id"],
      "selected_parameters": copy.deepcopy(selected["parameters"]),
      "selection_rule": copy.deepcopy(rule),
      "aggregates": aggregates,
      "selection_inputs_sha256":
          proactive_stage4.fingerprint_value(selection_inputs),
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "performance_conclusion": None,
  }


def _same(records: Sequence[Mapping[str, Any]], fields: Iterable[str]) -> None:
  for field in fields:
    _require(all(field in row for row in records),
             "Experiment A missing fairness field {}.".format(field))
    identities = {
        proactive_stage4.fingerprint_value(row[field]) for row in records}
    _require(len(identities) == 1,
             "Experiment A differs on fairness field {}.".format(field))


def check_experiment_a(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  """Extends Stage-5 experiment A with one Stage-6 TPP result."""
  audited = []
  for row in records:
    if row.get("policy") == POLICY:
      audited.append(audit_result(row))
    else:
      audited.append(stage5.audit_result(row))
  policies = {row["policy"] for row in audited}
  expected = {
      "proactive_lru", "proactive_clock", POLICY, "capd", "oracle"}
  _require(policies == expected,
           "Stage-6 experiment A policy set is incomplete.")
  _require(len(audited) == 7,
           "Experiment A requires four deterministic rows plus three CAPD "
           "seed rows.")
  capd_seeds = sorted(int(row["seed"]) for row in audited
                      if row["policy"] == "capd")
  _require(capd_seeds == sorted(stage5.CAPD_SEEDS),
           "Experiment A must retain all three CAPD seeds.")
  _same(audited, stage5.FAIRNESS_A_FIELDS)
  by_state: Dict[str, set] = {}
  for result in audited:
    for decision in result.get("rounds", []):
      by_state.setdefault(decision["candidate_state_sha256"], set()).add(
          decision["candidate_pages_sha256"])
  _require(all(len(values) == 1 for values in by_state.values()),
           "Identical pre-decision state produced inconsistent candidates.")
  return {
      "schema_version": "capd_proactive_stage6_fairness_v1_0",
      "contract_id": CONTRACT_ID,
      "experiment": "A",
      "status": "passed",
      "policies": sorted(policies),
      "capd_seeds": capd_seeds,
      "tpp_inspired_status": "implemented_and_selected_in_stage6",
      "candidate_identity_check":
          "shared_constructor_immutable_round_snapshot_and_exact_identity_"
          "for_equal_predecision_state",
      "test_used_for_selection": False,
      "performance_conclusion": None,
  }


def audit_no_contamination(paths: Iterable[str]) -> None:
  stage5.audit_no_legacy_stage_artifacts(paths)
  for path in paths:
    normalized = str(path).replace("\\", "/").lower()
    _require(not LEGACY_TPP_STAGE6_RE.search(normalized),
             "Historical TPP/Stage6 artifact is forbidden: {}".format(path))
    _require(not stage5.TEST_TOKEN_RE.search(normalized),
             "Test path/token is forbidden in Stage 6: {}".format(path))
