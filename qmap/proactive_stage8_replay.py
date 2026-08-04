# coding=utf-8
"""Stage-8 formal-Test adapter over the verified shared Replay machine."""

from __future__ import annotations

import bisect
import collections
import copy
import statistics
from typing import Any, Dict, Mapping, Optional, Sequence

from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage5_policies
from qmap import proactive_stage5_replay
from qmap import proactive_stage6_replay
from qmap import proactive_stage6_tpp
from qmap import proactive_stage8_contract as contract


DISPLAY_NAMES = {
    "reactive_lru": "Reactive-LRU", "proactive_lru": "Proactive-LRU",
    "proactive_clock": "Proactive-CLOCK", "tpp_inspired": "TPP-inspired",
    "capd": "CAPD", "oracle": "Oracle"}


def _quantiles(values: Sequence[int]) -> Dict[str, Any]:
  return {
      "count": len(values),
      "minimum": min(values) if values else None,
      "mean": statistics.mean(values) if values else None,
      "p50": proactive_stage5_replay._quantile(values, 0.50),
      "p95": proactive_stage5_replay._quantile(values, 0.95),
      "p99": proactive_stage5_replay._quantile(values, 0.99),
      "maximum": max(values) if values else None}


def early_reuse_metrics(trace: Sequence[Mapping[str, Any]],
                        events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  """Computes future reuse once from frozen trace/event semantics."""
  positions = collections.defaultdict(list)
  for index, access in enumerate(trace):
    positions[int(access["page"])].append(index)
  audits = []
  distances = []
  future_counts = []
  for event in events:
    if event.get("event_type") != proactive_replay.PROACTIVE_DEMOTION:
      continue
    page = int(event["page"])
    demoted_at = int(event["access_index"])
    page_positions = positions.get(page, [])
    offset = bisect.bisect_right(page_positions, demoted_at)
    future = len(page_positions) - offset
    distance = (page_positions[offset] - demoted_at if future else None)
    future_counts.append(future)
    if distance is not None:
      distances.append(distance)
    audits.append({
        "event_id": event["event_id"], "page": page,
        "demoted_at_access_index": demoted_at,
        "first_reuse_distance": distance, "future_access_count": future})
  denominator = len(audits)
  windows = {}
  for delta in (64, 256, 1024):
    count = sum(1 for value in distances if value <= delta)
    windows[str(delta)] = {
        "delta_accesses": delta, "early_reuse_count": count,
        "denominator_proactive_demotion_pages": denominator,
        "rate": count / float(denominator) if denominator else 0.0}
  wasted = sum(1 for value in future_counts if value == 0)
  return {
      "denominator_semantics":
          "proactive_demotion_events_each_selected_page_counts_once",
      "zero_denominator_rate": 0.0,
      "windows": windows,
      "first_reuse_distance": _quantiles(distances),
      "future_access_count": _quantiles(future_counts),
      "wasted_demotion_count": wasted,
      "wasted_demotion_rate": (
          wasted / float(denominator) if denominator else 0.0),
      "no_future_reuse_count": wasted,
      "per_demotion_audit": audits}


def _oov_diagnostics(ranker: Any, trace: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  page_vocab = ranker.predictor._feature_embedder.page_embedder
  pc_vocab = ranker.predictor._feature_embedder.pc_embedder
  if not page_vocab.frozen or not pc_vocab.frozen:
    raise contract.Stage8ContractError("CAPD vocabularies are not frozen.")
  page_known = set(page_vocab.input_to_index)
  pc_known = set(pc_vocab.input_to_index)
  pages = [int(access["page"]) for access in trace]
  pcs = [int(access.get("pc", 0)) for access in trace]
  unique_pages, unique_pcs = set(pages), set(pcs)
  page_access_oov = sum(page not in page_known for page in pages)
  pc_access_oov = sum(pc not in pc_known for pc in pcs)
  page_unique_oov = len(unique_pages - page_known)
  pc_unique_oov = len(unique_pcs - pc_known)
  return {
      "page_access_oov_count": page_access_oov,
      "page_access_oov_ratio": page_access_oov / float(len(pages)) if pages else 0.0,
      "page_unique_oov_count": page_unique_oov,
      "page_unique_oov_ratio": page_unique_oov / float(len(unique_pages)) if unique_pages else 0.0,
      "pc_access_oov_count": pc_access_oov,
      "pc_access_oov_ratio": pc_access_oov / float(len(pcs)) if pcs else 0.0,
      "pc_unique_oov_count": pc_unique_oov,
      "pc_unique_oov_ratio": pc_unique_oov / float(len(unique_pcs)) if unique_pcs else 0.0,
      "vocabulary_expansion_allowed": False, "unk_index": 0,
      "mapping_behavior": "unseen_frozen_input_maps_to_unk_index_0"}


def replay_parameters_for_job(policy: str,
                              controls: Mapping[str, Any]
                              ) -> proactive_replay.ReplayParameters:
  required = ("D", "F_low", "F_target", "K", "b_max", "history_H")
  if any(key not in controls for key in required):
    raise contract.Stage8ContractError("Job replay controls are incomplete.")
  if policy == "reactive_lru":
    return proactive_replay.ReplayParameters(
        policy_name=policy, dram_capacity_pages=int(controls["D"]),
        history_window_size=int(controls["history_H"]), early_reuse_window=64)
  return proactive_replay.ReplayParameters(
      policy_name=policy, dram_capacity_pages=int(controls["D"]),
      F_low=int(controls["F_low"]), F_target=int(controls["F_target"]),
      b_max=int(controls["b_max"]), candidate_size_K=int(controls["K"]),
      history_window_size=int(controls["history_H"]), early_reuse_window=64)


def _ranker_and_parameters(stage0: Mapping[str, Any], policy: str,
                           trace: Sequence[Mapping[str, Any]],
                           controls: Mapping[str, Any],
                           checkpoint: Optional[Mapping[str, Any]],
                           device: str):
  parameters = replay_parameters_for_job(policy, controls)
  if policy == "tpp_inspired":
    policy_stage0 = proactive_stage6_replay._stage0_for_tpp(stage0)
    ranker = proactive_stage6_tpp.TPPInspiredRanker(
        epoch_length=1024, cold_threshold=1, dirty_tie_break=False,
        early_reuse_window=64)
    return policy_stage0, parameters, ranker
  policy_stage0 = proactive_stage5_replay._stage0_for_policy(
      stage0, policy, checkpoint=checkpoint)
  ranker = None if policy == "reactive_lru" else (
      proactive_stage5_policies.build_ranker(
          policy, trace=trace, checkpoint=checkpoint, device=device))
  return policy_stage0, parameters, ranker


def run_formal_test_replay(
    stage0_config: Mapping[str, Any],
    cost_config: proactive_cost.CostConfiguration,
    trace: Sequence[Mapping[str, Any]], job: Mapping[str, Any],
    lock_row: Mapping[str, Any],
    checkpoint: Optional[Mapping[str, Any]] = None, device: str = "cpu",
    measure_latency: bool = True, retain_access_logs: bool = False,
    invariant_mode: str = "boundary") -> Dict[str, Any]:
  """The only policy entry allowed to consume a sealed Stage-7 Test trace."""
  policy = job["policy"]
  track = job.get("track")
  interval = job.get("evaluation_interval", {})
  expected_accesses = interval.get("end_exclusive", 0) - interval.get(
      "start_inclusive", 0)
  locked_identity = (lock_row.get("fairness_identity") if track == "standard"
                     else lock_row.get("candidate_content_sha256"))
  track_authorized = (
      lock_row.get("policy_replay_allowed_stage") == 8 if track == "standard"
      else lock_row.get("pressure_eligible") is True)
  if (job.get("formal_test") is not True or job.get("split_role") != "test" or
      track not in contract.TRACKS or not track_authorized or
      job.get("test_identity") != locked_identity or
      len(trace) != expected_accesses):
    raise contract.Stage8ContractError("Formal Test authorization mismatch.")
  if policy == "capd":
    if checkpoint is None or int(checkpoint["seed"]) != int(job["seed"]):
      raise contract.Stage8ContractError("CAPD checkpoint/job seed mismatch.")
  elif checkpoint is not None:
    raise contract.Stage8ContractError("Non-CAPD job received a checkpoint.")
  policy_stage0, parameters, ranker = _ranker_and_parameters(
      stage0_config, policy, trace, job["controls"], checkpoint, device)
  oov = _oov_diagnostics(ranker, trace) if policy == "capd" else None
  replay = proactive_replay.ProactiveReplay(
      policy_stage0, parameters, ranking_policy=ranker,
      invariant_mode=invariant_mode, record_details=True,
      capture_page_enter_flags=True,
      measure_decision_latency=measure_latency,
      exclude_current_entering_page=True)
  replay.register_backing_pages(
      replay._access_values(access)[0] for access in trace)
  for access in trace:
    replay.process_access(access)
    if not retain_access_logs:
      replay.access_logs[:] = []
  raw = replay.result()
  replay.validate_log_accounting()
  if policy == "tpp_inspired":
    if len(raw["rounds"]) != len(ranker.round_audits):
      raise contract.Stage8ContractError("TPP round audit count mismatch.")
    for common, tpp in zip(raw["rounds"], ranker.round_audits):
      if common["candidate_pages"] != tpp["candidate_pages"]:
        raise contract.Stage8ContractError("TPP candidate scope changed.")
  summary = copy.deepcopy(raw["summary"])
  cost = proactive_cost.compute_weighted_cost(
      summary, cost_config.profiles["default"])
  early = early_reuse_metrics(trace, raw["events"])
  page_enters = int(summary["page_enter_dram_count"])
  emergency = int(summary["emergency_demotions"])
  latency = proactive_stage5_replay._latency_summary(raw["rounds"])
  metrics = {
      "dram_hits": int(summary["dram_hits"]),
      "nvm_reads": int(summary["nvm_reads"]),
      "nvm_writes": int(summary["nvm_writes"]),
      "total_demotions": int(summary["total_demotions"]),
      "proactive_demotions": int(summary["proactive_demotions"]),
      "reactive_demotions": int(summary["reactive_demotions"]),
      "emergency_demotions": emergency,
      "weighted_cost": cost.weighted_cost,
      "weighted_cost_components": {
          "dram_hit_cost": cost.dram_hit_cost,
          "nvm_read_cost": cost.nvm_read_cost,
          "nvm_write_cost": cost.nvm_write_cost,
          "demotion_cost": cost.demotion_cost},
      "raw_access_count": len(trace),
      "weighted_cost_per_access": cost.weighted_cost / float(len(trace)),
      "page_enter_dram_count": page_enters,
      "number_of_proactive_cycles": int(summary["number_of_proactive_cycles"]),
      "number_of_proactive_rounds": int(summary["number_of_proactive_rounds"]),
      "mean_b_t": summary["mean_b_t"],
      "rounds_per_cycle": summary["rounds_per_cycle"],
      "minimum_free_frames": summary["minimum_free_frames"],
      "average_free_frames": summary["average_free_frames"],
      "free_frame_exhaustion_count": int(summary["free_frame_exhaustion_count"]),
      "emergency_fallback_count": emergency,
      "fallback_rate": emergency / float(page_enters) if page_enters else 0.0,
      "fallback_rate_denominator": "page_enter_dram_count",
      "early_reuse": early,
      "decision_count": int(summary["decision_count"]),
      "total_decision_time": latency["total_seconds"],
      "mean_decision_time": latency["mean_seconds"],
      "p50_decision_time": latency["p50_seconds"],
      "p95_decision_time": latency["p95_seconds"],
      "p99_decision_time": latency["p99_seconds"]}
  initial_state = {
      "dram_resident": [],
      "nvm_backing_pages": sorted({int(access["page"]) for access in trace}),
      "free_frames": int(job["D"]), "lru_order": [],
      "dirty_pages": []}
  candidate_contract = {
      "constructor": "lru_tail_current_state",
      "controls": copy.deepcopy(job["controls"]),
      "sha256": job["candidate_contract_sha256"]}
  result = {
      "schema_version": contract.RESULT_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "stage_status": contract.IMPLEMENTED,
      "job_id": job["job_id"], "track": track, "policy": policy,
      "policy_display_name": DISPLAY_NAMES[policy], "seed": job.get("seed"),
      "workload": job["workload"], "workload_role": job["workload_role"],
      "dram_capacity_pages": int(job["D"]), "split_role": "test",
      "formal_test": True, "test_used_for_selection": False,
      "test_identity": job["test_identity"],
      "trace_sha256": job["trace_sha256"],
      "source_interval": copy.deepcopy(job["source_interval"]),
      "evaluation_interval": copy.deepcopy(job["evaluation_interval"]),
      "source_standard_test_sha256": job["source_standard_test_sha256"],
      "derived_csv_sha256": job["derived_csv_sha256"],
      "source_raw_interval": copy.deepcopy(job["source_raw_interval"]),
      "pressure_lock_sha256": job["pressure_lock_sha256"],
      "pressure_bundle_manifest_sha256": job[
          "pressure_bundle_manifest_sha256"],
      "addendum_sha256": job["addendum_sha256"],
      "parent_r4_contract_sha256": job["parent_r4_contract_sha256"],
      "page_size_bytes": 4096,
      "nvm_capacity_model": "unbounded_backing_tier",
      "initial_state": initial_state,
      "initial_state_sha256": job["initial_state_sha256"],
      "observed_initial_state_sha256": contract.fingerprint_value(initial_state),
      "page_enter_dram_semantics": job["page_enter_dram_semantics"],
      "cost_profile": {"name": "default", "weights": dict(contract.FROZEN_COST)},
      "cost_profile_sha256": job["cost_profile_sha256"],
      "D": job["D"], "W_ref": job["W_ref"], "F_low": job["F_low"],
      "F_target": job["F_target"], "K": job["K"], "b_max": job["b_max"],
      "history_H": job["history_H"], "alpha": job["alpha"],
      "beta": job["beta"], "b_t_rule": job["controls"]["b_t_rule"],
      "candidate_source": job["controls"]["candidate_source"],
      "fallback_policy": job["controls"]["fallback_policy"],
      "trigger_mode": job["controls"]["trigger_mode"],
      "candidate_contract": candidate_contract,
      "candidate_contract_sha256": job["candidate_contract_sha256"],
      "selector_status": "disabled", "B": None,
      "checkpoint_sha256": None if checkpoint is None else checkpoint["sha256"],
      "checkpoint": (None if checkpoint is None else {
          "seed": int(checkpoint["seed"]),
          "recorded_path": job["checkpoint"]["path"],
          "resolved_path": checkpoint.get("resolved_path", checkpoint.get("path")),
          "sha256": checkpoint["sha256"],
          "selection_criterion": checkpoint["selection_criterion"]}),
      "capd_generalization": oov,
      "tpp_parameters": ({
          "epoch_length": 1024, "cold_threshold": 1,
          "dirty_tie_break": False, "promotion_performed": False,
          "future_information_accessed": False,
          "fallback_to_lru_used": False, "D": job["D"],
          "F_low": job["F_low"], "F_target": job["F_target"],
          "K": job["K"], "b_max": job["b_max"]}
          if policy == "tpp_inspired" else None),
      "future_information": "candidate_scoped_oracle_only" if policy == "oracle" else "not_accessed",
      "metrics": metrics, "events": raw["events"], "rounds": raw["rounds"],
      "cycles": raw["cycles"],
      "accesses": raw["accesses"] if retain_access_logs else [],
      "access_log_retention": "full" if retain_access_logs else "omitted_memory_bound",
      "final_state": raw["state"],
      "policy_state": ({"tpp_inspired": ranker.state_snapshot()}
                       if policy == "tpp_inspired" else None),
      "runtime": {"latency": latency, "measurement_enabled": measure_latency},
      "old_finals_v3_stage_artifacts_used": False,
      "performance_selection_performed": False,
      "interpretation_boundary":
          "Synchronous Replay measures page-ranking quality, NVM events, weighted cost, state trajectory, and synchronous decision overhead; it is not real background concurrency, foreground latency, CPU overhead, or memory overhead."}
  result["semantic_result_sha256"] = contract.fingerprint_value(
      contract.semantic_payload(result))
  contract.audit_job_result(result, job)
  return result
