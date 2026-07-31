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
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as stage5_contract
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


def _ranker_and_parameters(stage0: Mapping[str, Any], policy: str,
                           trace: Sequence[Mapping[str, Any]],
                           dram_pages: int,
                           checkpoint: Optional[Mapping[str, Any]],
                           device: str):
  if policy == "tpp_inspired":
    policy_stage0 = proactive_stage6_replay._stage0_for_tpp(stage0)
    parameters = proactive_replay.ReplayParameters(
        policy_name=policy, dram_capacity_pages=int(dram_pages), F_low=8,
        F_target=16, b_max=4, candidate_size_K=8,
        history_window_size=20, early_reuse_window=64)
    ranker = proactive_stage6_tpp.TPPInspiredRanker(
        epoch_length=1024, cold_threshold=1, dirty_tie_break=False,
        early_reuse_window=64)
    return policy_stage0, parameters, ranker
  policy_stage0 = proactive_stage5_replay._stage0_for_policy(
      stage0, policy, checkpoint=checkpoint)
  parameters = proactive_stage5_replay._parameters(policy, int(dram_pages))
  ranker = None if policy == "reactive_lru" else (
      proactive_stage5_policies.build_ranker(
          policy, trace=trace, checkpoint=checkpoint, device=device))
  return policy_stage0, parameters, ranker


def run_formal_test_replay(
    stage0_config: Mapping[str, Any],
    cost_config: proactive_cost.CostConfiguration,
    trace: Sequence[Mapping[str, Any]], job: Mapping[str, Any],
    lock_row: Mapping[str, Any], working_set_pages: int,
    checkpoint: Optional[Mapping[str, Any]] = None, device: str = "cpu",
    measure_latency: bool = True, retain_access_logs: bool = False,
    invariant_mode: str = "boundary") -> Dict[str, Any]:
  """The only policy entry allowed to consume a sealed Stage-7 Test trace."""
  policy = job["policy"]
  if (job.get("formal_test") is not True or job.get("split") != "test" or
      lock_row.get("policy_replay_allowed_stage") != 8 or
      job.get("test_identity") != lock_row.get("fairness_identity") or
      len(trace) != lock_row.get("accesses")):
    raise contract.Stage8ContractError("Formal Test authorization mismatch.")
  if policy == "capd":
    if checkpoint is None or int(checkpoint["seed"]) != int(job["seed"]):
      raise contract.Stage8ContractError("CAPD checkpoint/job seed mismatch.")
  elif checkpoint is not None:
    raise contract.Stage8ContractError("Non-CAPD job received a checkpoint.")
  policy_stage0, parameters, ranker = _ranker_and_parameters(
      stage0_config, policy, trace, int(job["dram_pages"]), checkpoint, device)
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
      "free_frames": int(job["dram_pages"]), "lru_order": [],
      "dirty_pages": []}
  candidate_contract = stage5_contract.candidate_contract_identity()
  result = {
      "schema_version": contract.RESULT_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "stage_status": contract.IMPLEMENTED,
      "job_id": job["job_id"], "policy": policy,
      "policy_display_name": DISPLAY_NAMES[policy], "seed": job.get("seed"),
      "workload": job["workload"], "workload_role": job["workload_role"],
      "capacity_ratio": str(job["capacity_ratio"]),
      "dram_capacity_pages": int(job["dram_pages"]),
      "working_set_pages": int(working_set_pages), "split": "test",
      "formal_test": True, "test_used_for_selection": False,
      "test_identity": job["test_identity"],
      "trace_sha256": lock_row["sha256"],
      "trace_range": copy.deepcopy(lock_row["interval"]),
      "page_size_bytes": 4096,
      "nvm_capacity_model": "unbounded_backing_tier",
      "initial_state": initial_state,
      "initial_state_sha256": proactive_stage4.fingerprint_value(initial_state),
      "page_enter_dram_semantics":
          "occupies_one_free_frame_regardless_of_source",
      "cost_profile": {"name": "default", "weights": dict(contract.FROZEN_COST)},
      "F_low": None if policy == "reactive_lru" else 8,
      "F_target": None if policy == "reactive_lru" else 16,
      "candidate_size_K": None if policy == "reactive_lru" else 8,
      "b_max": None if policy == "reactive_lru" else 4,
      "b_t_rule": None if policy == "reactive_lru" else
          "min(b_max,F_target-F_t,|C_t|)",
      "candidate_source": None if policy == "reactive_lru" else "lru_tail",
      "fallback_policy": None if policy == "reactive_lru" else "lru",
      "trigger_mode": None if policy == "reactive_lru" else "low_watermark",
      "candidate_contract": candidate_contract,
      "candidate_contract_sha256": candidate_contract["sha256"],
      "selector_status": "disabled", "B": None,
      "checkpoint": (None if checkpoint is None else {
          "seed": int(checkpoint["seed"]),
          "recorded_path": job["checkpoint"]["path"],
          "resolved_path": checkpoint["path"],
          "sha256": checkpoint["sha256"]}),
      "capd_generalization": oov,
      "tpp_parameters": ({
          "epoch_length": 1024, "cold_threshold": 1,
          "dirty_tie_break": False, "promotion_performed": False,
          "future_information_accessed": False,
          "fallback_to_lru_used": False} if policy == "tpp_inspired" else None),
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
          "Synchronous Replay measures page-ranking quality, NVM events, weighted cost, state trajectory, and synchronous decision overhead; it is not real background concurrency or foreground latency."}
  result["semantic_result_sha256"] = contract.fingerprint_value(
      contract.semantic_payload(result))
  contract.audit_job_result(result, job)
  return result
