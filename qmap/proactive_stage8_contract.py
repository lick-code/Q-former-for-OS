# coding=utf-8
"""Fail-closed contracts for the frozen Stage-8 formal synchronous Replay."""

from __future__ import annotations

import collections
import copy
import os
from typing import Any, Dict, Mapping, Sequence

from qmap import proactive_stage4
from qmap import proactive_stage5_contract
from qmap import proactive_stage6_contract
from qmap import proactive_stage7_workloads as stage7


SCHEMA_VERSION = "capd_proactive_stage8_v1_0"
RESULT_SCHEMA_VERSION = "capd_proactive_stage8_job_result_v1_0"
MANIFEST_SCHEMA_VERSION = "capd_proactive_stage8_job_manifest_v1_0"
AGGREGATE_SCHEMA_VERSION = "capd_proactive_stage8_aggregate_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE8-1.0"
IMPLEMENTED = "stage8_implemented_awaiting_formal_replay"
VERIFIED = "stage8_sync_replay_verified"
NOT_VERIFIED = "stage8_not_verified"
FORMAL_POLICIES = (
    "reactive_lru", "proactive_lru", "proactive_clock", "tpp_inspired",
    "capd", "oracle")
DETERMINISTIC_POLICIES = tuple(p for p in FORMAL_POLICIES if p != "capd")
CAPD_SEEDS = (3136859, 42, 2026)
RATIOS = ("0.20", "0.40", "0.60")
COMPARISON_A = (
    "proactive_lru", "proactive_clock", "tpp_inspired", "capd", "oracle")
COMPARISON_B = ("reactive_lru", "proactive_lru")
FROZEN_CONTROLS = {
    "F_low": 8, "F_target": 16, "candidate_size_K": 8, "b_max": 4,
    "candidate_source": "lru_tail", "selector": "disabled",
    "fallback_policy": "lru", "trigger_mode": "low_watermark"}
FROZEN_COST = {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
               "demotion": 10}


class Stage8ContractError(ValueError):
  pass


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage8ContractError(message)


def load_json(path: str) -> Any:
  return proactive_stage4.load_json(path)


def fingerprint_file(path: str) -> str:
  return proactive_stage4.fingerprint_file(path)


def fingerprint_value(value: Any) -> str:
  return proactive_stage4.fingerprint_value(value)


def write_json_atomic(path: str, value: Any) -> None:
  proactive_stage4.write_json_atomic(path, value)


def write_text_atomic(path: str, value: str) -> None:
  proactive_stage4.write_text_atomic(path, value)


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping) and
           value.get("schema_version") == SCHEMA_VERSION and
           value.get("contract_id") == CONTRACT_ID,
           "Stage-8 config schema/contract mismatch.")
  _require(value.get("output_root") == "outputs/capd_proactive_stage8" and
           value.get("result_schema") ==
           "configs/finals/capd_proactive_stage8_result_schema.json",
           "Stage-8 output/result-schema binding changed.")
  _require(tuple(value.get("formal_policies", ())) == FORMAL_POLICIES and
           tuple(value.get("deterministic_policies", ())) ==
           DETERMINISTIC_POLICIES and
           tuple(value.get("capd_seeds", ())) == CAPD_SEEDS and
           tuple(value.get("capacity_ratios", ())) == RATIOS,
           "Stage-8 frozen matrix changed.")
  _require(tuple(value.get("comparison_A", ())) == COMPARISON_A and
           tuple(value.get("comparison_B", ())) == COMPARISON_B,
           "Stage-8 comparison membership changed.")
  _require(value.get("frozen_controls") == FROZEN_CONTROLS and
           value.get("cost_profile", {}).get("weights") == FROZEN_COST,
           "Stage-8 controls or Cost changed.")
  _require(value.get("capd") == {
      "lookahead_L": 256, "label_weights": [1, 1, 2], "history_H": 20,
      "vocabulary_expansion_allowed": False, "unk_index": 0,
      "best_seed_selection_allowed": False}, "CAPD freeze changed.")
  _require(value.get("tpp_inspired") == {
      "epoch_length": 1024, "cold_threshold": 1,
      "dirty_tie_break": False, "promotion_allowed": False},
      "TPP freeze changed.")
  _require(tuple(value.get("early_reuse_windows", ())) == (64, 256, 1024),
           "Early-Reuse windows changed.")
  statistics = value.get("statistics", {})
  _require(statistics.get("bootstrap_seed") == 20260801 and
           statistics.get("bootstrap_resamples") == 10000 and
           statistics.get("bootstrap_unit") == "workload_capacity_cell" and
           statistics.get("confidence_level") == 0.95 and
           statistics.get("std") == "sample_ddof_1" and
           statistics.get("zero_denominator_rate") == 0.0,
           "Stage-8 predeclared statistics changed.")
  _require(value.get("acceptance") == {
      "minimum_stage1_through_stage8_regression_tests": 380,
      "formal_job_count": 144,
      "verified_status": VERIFIED, "failure_status": NOT_VERIFIED},
      "Stage-8 acceptance gate changed.")
  return value


def _authority_file(project_root: str, row: Mapping[str, Any]) -> str:
  path = stage7.repository_path(project_root, row.get("path", ""))
  _require(fingerprint_file(path) == row.get("sha256"),
           "Authority SHA mismatch: {}".format(row.get("path")))
  return path


def _capacity_rows(capacity: Any) -> Sequence[Mapping[str, Any]]:
  rows = capacity.get("rows") if isinstance(capacity, Mapping) else capacity
  _require(isinstance(rows, list), "Capacity matrix rows are missing.")
  return rows


def _expected_jobs(plan: Mapping[str, Any], lock: Mapping[str, Any],
                   capacity: Any) -> Sequence[str]:
  capacity_map = collections.defaultdict(dict)
  for row in _capacity_rows(capacity):
    capacity_map[row["workload"]][str(row["ratio"])] = row
  ids = []
  for locked in lock["workloads"]:
    workload = locked["workload"]
    for ratio in RATIOS:
      _require(ratio in capacity_map[workload],
               "Capacity matrix cell missing: {} {}".format(workload, ratio))
      for policy in DETERMINISTIC_POLICIES:
        ids.append("{}__r{}__{}__seed-na".format(
            workload, ratio.replace(".", ""), policy))
      for seed in CAPD_SEEDS:
        ids.append("{}__r{}__capd__seed-{}".format(
            workload, ratio.replace(".", ""), seed))
  return ids


def audit_authority(config: Mapping[str, Any], project_root: str,
                    hash_test_payloads: bool = True) -> Dict[str, Any]:
  """Hashes Test bytes for integrity only; never parses or summarizes them."""
  validate_config(config)
  result_schema_path = stage7.repository_path(
      project_root, config["result_schema"])
  result_schema = load_json(result_schema_path)
  _require(result_schema.get("contract_id") == CONTRACT_ID and
           result_schema.get("job_result_schema") == RESULT_SCHEMA_VERSION and
           result_schema.get("aggregate_schema") == AGGREGATE_SCHEMA_VERSION,
           "Stage-8 result schema artifact is invalid.")
  paths = {}
  for group in ("stage7_authority", "entry_authority"):
    for name, row in config[group].items():
      paths[name] = _authority_file(project_root, row)
  verification = load_json(paths["verification"])
  plan = load_json(paths["execution_plan"])
  lock = load_json(paths["standard_test_lock"])
  capacity = load_json(paths["capacity_matrix"])
  stage5_verification = load_json(paths["stage5_verification"])
  stage6_verification = load_json(paths["stage6_verification"])
  proactive_stage5_contract.validate_config(load_json(paths["stage5_config"]))
  proactive_stage6_contract.validate_config(load_json(paths["stage6_config"]))
  stage7_entry = stage7.audit_stage6_entry(
      load_json(paths["stage7_workload_config"]), project_root)
  _require(verification.get("status") == "stage7_workload_suite_verified" and
           verification.get("stage8_entry_gate") == "satisfied" and
           verification.get("stage8_job_count") == 144 and
           verification.get("test_performance_inspected") is False and
           verification.get("test_used_for_parameter_selection") is False and
           verification.get("capd_used_for_workload_selection") is False,
           "Stage-7 entry gate is not clean and satisfied.")
  _require(lock.get("status") == "sealed_for_stage8" and
           lock.get("test_performance_inspected") is False and
           lock.get("test_policy_replay_executed") is False and
           len(lock.get("workloads", ())) == 6,
           "Standard Test lock is invalid or contaminated.")
  _require(plan.get("schema_version") ==
           "capd_proactive_stage8_execution_plan_v1_0" and
           plan.get("status") == "frozen_plan_not_executed" and
           plan.get("job_count") == 144 and len(plan.get("jobs", ())) == 144,
           "Frozen Stage-8 execution plan is invalid.")
  _require(plan.get("test_policy_replay_executed") is False and
           plan.get("performance_results") is None and
           verification.get("frozen_parameters_changed") is False,
           "Stage-7 plan/gate reports execution, results, or parameter drift.")
  _require(tuple(plan.get("formal_policies", ())) == FORMAL_POLICIES and
           tuple(plan.get("deterministic_policies", ())) ==
           DETERMINISTIC_POLICIES and
           tuple(plan.get("capd_seeds", ())) == CAPD_SEEDS and
           tuple(plan.get("capacity_ratios", ())) == RATIOS and
           tuple(plan.get("comparison_contracts", {}).get("A", ())) ==
           COMPARISON_A and tuple(plan.get("comparison_contracts", {}).get(
               "B", ())) == COMPARISON_B,
           "Plan policies/seeds/capacities/comparisons changed.")
  generalization = plan.get("generalization_contract", {})
  _require(generalization.get("checkpoint_retraining_allowed") is False and
           generalization.get("vocabulary_expansion_allowed") is False and
           generalization.get("page_and_pc_oov_policy") ==
           "frozen_checkpoint_unk_index_0" and
           generalization.get("oov_diagnostics_required_for_capd") is True,
           "Stage-8 generalization/OOV contract changed.")
  _require(stage5_verification.get("status") ==
           "stage5_baseline_framework_verified" and
           stage6_verification.get("status") ==
           "stage6_tpp_inspired_verified",
           "Stage-5/6 verified policy authority is missing.")
  lock_map = {row["workload"]: row for row in lock["workloads"]}
  capacity_rows = _capacity_rows(capacity)
  capacity_map = {(row["workload"], str(row["ratio"])): row
                  for row in capacity_rows}
  _require(len(lock_map) == 6 and len(capacity_map) == 18,
           "Test/capacity identities are incomplete.")
  expected_ids = list(_expected_jobs(plan, lock, capacity))
  jobs = plan["jobs"]
  _require([job.get("job_id") for job in jobs] == expected_ids and
           len(set(expected_ids)) == 144,
           "144-job Cartesian product is missing, duplicated, or reordered.")
  checkpoint_bindings = {}
  for job in jobs:
    locked = lock_map.get(job.get("workload"))
    cap = capacity_map.get((job.get("workload"), str(job.get(
        "capacity_ratio"))))
    _require(locked is not None and cap is not None and
             job.get("split") == "test" and job.get("formal_test") is True and
             job.get("test_identity") == locked.get("fairness_identity") and
             job.get("workload_role") == locked.get("role") and
             job.get("dram_pages") == cap.get("dram_pages") and
             job.get("execution_status") == "planned_not_executed",
             "Job Trace/capacity/Test identity mismatch: {}".format(
                 job.get("job_id")))
    policy = job.get("policy")
    if policy == "capd":
      _require(job.get("seed") in CAPD_SEEDS and
               job.get("deterministic_policy") is False and
               isinstance(job.get("checkpoint"), Mapping) and
               job.get("experiment_labels") == ["A"],
               "CAPD job binding is invalid.")
      checkpoint = job["checkpoint"]
      resolved = stage7.resolve_recorded_artifact(
          project_root, checkpoint.get("path", ""), checkpoint.get("sha256"))
      previous = checkpoint_bindings.setdefault(
          int(job["seed"]), (resolved, checkpoint["sha256"]))
      _require(previous == (resolved, checkpoint["sha256"]),
               "A CAPD seed maps to multiple checkpoints.")
    else:
      _require(policy in DETERMINISTIC_POLICIES and job.get("seed") is None and
               job.get("checkpoint") is None and
               job.get("deterministic_policy") is True,
               "Deterministic job received seed/checkpoint.")
      expected_labels = (["B"] if policy == "reactive_lru" else
                         ["A", "B"] if policy == "proactive_lru" else ["A"])
      _require(job.get("experiment_labels") == expected_labels,
               "Job experiment A/B membership changed.")
  _require(set(checkpoint_bindings) == set(CAPD_SEEDS),
           "Three CAPD checkpoint bindings are incomplete.")
  test_files = {}
  for workload, locked in lock_map.items():
    _require(locked.get("formal_test") is True and
             locked.get("split_role") == "test" and
             locked.get("policy_replay_allowed_stage") == 8 and
             locked.get("parameter_selection_allowed") is False and
             locked.get("accesses") ==
             locked.get("interval", {}).get("end_exclusive") -
             locked.get("interval", {}).get("start_inclusive"),
             "Locked Test metadata is invalid: " + workload)
    test_path = stage7.repository_path(project_root, locked["path"])
    if hash_test_payloads:
      _require(fingerprint_file(test_path) == locked.get("sha256"),
               "Locked Test payload SHA mismatch: " + workload)
    test_files[workload] = test_path
  return {
      "verification": verification, "plan": plan, "lock": lock,
      "capacity": capacity, "paths": paths, "test_files": test_files,
      "result_schema_path": result_schema_path,
      "checkpoint_bindings": checkpoint_bindings,
      "stage7_entry": stage7_entry,
      "test_payload_operation": "sha256_integrity_only_not_parsed",
      "test_performance_inspected": False}


def semantic_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
  value = copy.deepcopy(dict(result))
  value.pop("semantic_result_sha256", None)
  value.pop("runtime", None)
  for row in value.get("rounds", []):
    for key in ("feature_latency", "inference_latency", "selection_latency",
                "tpp_selection_latency"):
      row.pop(key, None)
  for row in value.get("cycles", []):
    for key in ("total_feature_time", "total_inference_time",
                "total_selection_time"):
      row.pop(key, None)
  for key in ("total_decision_time", "mean_decision_time",
              "p50_decision_time", "p95_decision_time",
              "p99_decision_time"):
    value.get("metrics", {}).pop(key, None)
  return value


def audit_job_result(result: Mapping[str, Any], job: Mapping[str, Any]) -> None:
  _require(result.get("schema_version") == RESULT_SCHEMA_VERSION and
           result.get("contract_id") == CONTRACT_ID and
           result.get("job_id") == job.get("job_id") and
           result.get("policy") == job.get("policy") and
           result.get("seed") == job.get("seed") and
           result.get("formal_test") is True and
           result.get("test_used_for_selection") is False,
           "Stage-8 job result identity/schema mismatch.")
  _require(result.get("selector_status") == "disabled" and
           result.get("B") is None and
           result.get("old_finals_v3_stage_artifacts_used") is False and
           result.get("performance_selection_performed") is False,
           "Stage-8 result contains selector/B64/legacy/selection pollution.")
  policy = result["policy"]
  if policy == "reactive_lru":
    _require(all(result.get(field) is None for field in (
        "F_low", "F_target", "candidate_size_K", "b_max", "b_t_rule",
        "candidate_source", "fallback_policy", "trigger_mode")),
        "Reactive-LRU was assigned proactive controls.")
  else:
    _require({
        "F_low": result.get("F_low"), "F_target": result.get("F_target"),
        "candidate_size_K": result.get("candidate_size_K"),
        "b_max": result.get("b_max"),
        "candidate_source": result.get("candidate_source"),
        "selector": result.get("selector_status"),
        "fallback_policy": result.get("fallback_policy"),
        "trigger_mode": result.get("trigger_mode")} == FROZEN_CONTROLS and
        result.get("b_t_rule") == "min(b_max,F_target-F_t,|C_t|)",
        "Active Stage-8 controls changed.")
  metrics = result.get("metrics", {})
  for field in ("dram_hits", "nvm_reads", "nvm_writes", "total_demotions",
                "proactive_demotions", "emergency_demotions",
                "weighted_cost", "raw_access_count",
                "weighted_cost_per_access", "fallback_rate",
                "early_reuse"):
    _require(field in metrics, "Missing Stage-8 metric: " + field)
  _require(metrics["total_demotions"] ==
           metrics["proactive_demotions"] +
           metrics.get("reactive_demotions", 0) +
           metrics["emergency_demotions"], "Demotion accounting mismatch.")
  expected_cost = (metrics["dram_hits"] * FROZEN_COST["dram_hit"] +
                   metrics["nvm_reads"] * FROZEN_COST["nvm_read"] +
                   metrics["nvm_writes"] * FROZEN_COST["nvm_write"] +
                   metrics["total_demotions"] * FROZEN_COST["demotion"])
  _require(metrics["weighted_cost"] == expected_cost,
           "Weighted Cost does not match frozen components.")
  _require(len(result.get("events", ())) == metrics["total_demotions"] and
           len(result.get("rounds", ())) == metrics["decision_count"] and
           len(result.get("cycles", ())) ==
           metrics["number_of_proactive_cycles"],
           "Event/round/cycle audit cardinality mismatch.")
  allowed_events = ({"reactive_demotion"} if policy == "reactive_lru" else
                    {"proactive_demotion", "emergency_fallback_demotion"})
  _require(set(row.get("event_type") for row in result.get("events", ())) <=
           allowed_events, "Demotion event types are mixed.")
  for row in result.get("rounds", ()):
    candidates = row.get("candidate_pages", [])
    selected = row.get("selected_pages", [])
    _require(len(candidates) == len(set(candidates)) and
             len(selected) == len(set(selected)) and
             set(selected) <= set(candidates) and
             row.get("b_t") == len(selected),
             "Round candidate/selection identity is invalid.")
  page_enters = int(metrics.get("page_enter_dram_count", 0))
  expected_fallback = (metrics["emergency_demotions"] / float(page_enters)
                       if page_enters else 0.0)
  _require(metrics.get("fallback_rate_denominator") ==
           "page_enter_dram_count" and
           metrics.get("emergency_fallback_count") ==
           metrics["emergency_demotions"] and
           metrics.get("fallback_rate") == expected_fallback,
           "FallbackRate numerator/denominator semantics changed.")
  early = metrics.get("early_reuse", {})
  _require(early.get("denominator_semantics") ==
           "proactive_demotion_events_each_selected_page_counts_once" and
           early.get("zero_denominator_rate") == 0.0 and
           set(early.get("windows", {})) == {"64", "256", "1024"},
           "Early-Reuse window/denominator semantics changed.")
  for delta in (64, 256, 1024):
    row = early["windows"][str(delta)]
    denominator = int(row.get("denominator_proactive_demotion_pages", -1))
    count = int(row.get("early_reuse_count", -1))
    expected_rate = count / float(denominator) if denominator else 0.0
    _require(row.get("delta_accesses") == delta and
             denominator == metrics["proactive_demotions"] and
             0 <= count <= denominator and row.get("rate") == expected_rate,
             "Early-Reuse accounting mismatch at delta {}.".format(delta))
  if policy == "capd":
    checkpoint = result.get("checkpoint", {})
    generalization = result.get("capd_generalization", {})
    required_oov = {
        "page_access_oov_count", "page_access_oov_ratio",
        "page_unique_oov_count", "page_unique_oov_ratio",
        "pc_access_oov_count", "pc_access_oov_ratio",
        "pc_unique_oov_count", "pc_unique_oov_ratio"}
    _require(checkpoint.get("seed") == job.get("seed") and
             checkpoint.get("recorded_path") ==
             job.get("checkpoint", {}).get("path") and
             isinstance(checkpoint.get("resolved_path"), str) and
             bool(checkpoint.get("resolved_path")) and
             checkpoint.get("sha256") == job.get("checkpoint", {}).get("sha256") and
             required_oov <= set(generalization) and
             generalization.get("vocabulary_expansion_allowed") is False and
             generalization.get("unk_index") == 0,
             "CAPD checkpoint/OOV/UNK contract changed.")
  else:
    _require(result.get("checkpoint") is None and
             result.get("capd_generalization") is None,
             "Non-CAPD result contains CAPD state.")
  if policy == "tpp_inspired":
    _require(result.get("tpp_parameters") == {
        "epoch_length": 1024, "cold_threshold": 1,
        "dirty_tie_break": False, "promotion_performed": False,
        "future_information_accessed": False,
        "fallback_to_lru_used": False}, "TPP parameters/semantics changed.")
  if policy == "oracle":
    _require(result.get("future_information") ==
             "candidate_scoped_oracle_only",
             "Oracle future-information scope changed.")
  else:
    _require(result.get("future_information") == "not_accessed",
             "Online policy accessed future information.")
  _require(result.get("semantic_result_sha256") ==
           fingerprint_value(semantic_payload(result)),
           "Stage-8 semantic result SHA mismatch.")
