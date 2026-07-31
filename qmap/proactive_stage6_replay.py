# coding=utf-8
"""Stage-6 TPP adapter over the unchanged shared proactive Replay machine."""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Sequence

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as stage5_contract
from qmap import proactive_stage5_replay as stage5_replay
from qmap import proactive_stage6_contract as contract
from qmap import proactive_stage6_tpp


def _stage0_for_tpp(stage0: Mapping[str, Any]) -> Dict[str, Any]:
  """Creates a Stage-6-only TPP runtime mapping without altering Stage 5."""
  value = copy.deepcopy(stage0)
  value["evaluation"]["policy_name"] = "tpp_inspired"
  value["evaluation"]["random_seed"] = None
  value["method"].update({
      "name": "tpp_inspired",
      "selector": "disabled",
      "candidate_size_K": 8,
      "candidate_source": "lru_tail",
      "fallback_policy": "lru",
      "trigger_mode": "low_watermark",
  })
  value["freeze_status"]["stage4_candidate"] = "frozen"
  value["freeze_status"]["stage4_training"] = "not_applicable"
  value["model"].update({
      "history_H": None,
      "lookahead_L": None,
      "label_weights": {
          "lambda_1": None,
          "lambda_2": None,
          "lambda_3": None,
      },
      "model_checkpoint": {
          "status": "not_applicable",
          "path": None,
          "fingerprint": None,
      },
  })
  finals_config.validate_config(value)
  return value


def _semantic_fingerprint(result: Mapping[str, Any]) -> str:
  summary = copy.deepcopy(result["summary"])
  for field in (
      "total_decision_time", "mean_decision_time", "p50_decision_time",
      "p95_decision_time", "p99_decision_time"):
    summary.pop(field, None)
  if isinstance(summary.get("tpp"), dict):
    summary["tpp"].pop("selection_latency", None)
  rounds = []
  for row in result["rounds"]:
    rounds.append({
        key: copy.deepcopy(value) for key, value in row.items()
        if key not in (
            "feature_latency", "inference_latency", "selection_latency",
            "tpp_selection_latency")})
  cycles = []
  for row in result["cycles"]:
    cycles.append({
        key: copy.deepcopy(value) for key, value in row.items()
        if key not in (
            "total_feature_time", "total_inference_time",
            "total_selection_time")})
  policy_state = copy.deepcopy(result["policy_state"])
  return proactive_stage4.fingerprint_value({
      "contract_id": contract.CONTRACT_ID,
      "policy": result["policy"],
      "parameters": result["tpp_parameters"],
      "summary": summary,
      "events": result["events"],
      "rounds": rounds,
      "cycles": cycles,
      "final_state": result["final_state"],
      "policy_state": policy_state,
  })


def run_replay(
    stage0_config: Mapping[str, Any],
    stage6_config: Mapping[str, Any],
    cost_config: proactive_cost.CostConfiguration,
    trace: Sequence[Any],
    workload: str,
    split: str,
    split_role: str,
    source_interval: Mapping[str, int],
    trace_sha256: str,
    dram_capacity_pages: int,
    working_set_pages: int,
    epoch_length: int,
    cold_threshold: int,
    dirty_tie_break: bool,
    measure_latency: bool = True,
    retain_access_logs: bool = False,
    invariant_mode: str = "full",
) -> Dict[str, Any]:
  """Runs TPP-inspired while reusing ``ProactiveReplay`` state transitions."""
  contract.validate_config(stage6_config)
  contract.validate_tpp_parameters(
      epoch_length, cold_threshold, dirty_tie_break)
  if invariant_mode not in ("full", "boundary"):
    raise contract.Stage6ContractError(
        "invariant_mode must be full or boundary.")
  if split not in ("train", "validation") or split == "test":
    raise contract.Stage6ContractError("Stage-6 Replay hard-rejects Test.")
  if split_role not in ("training_and_fit", "parameter_selection"):
    raise contract.Stage6ContractError(
        "Stage-6 split role must be Train/Validation.")
  policy_stage0 = _stage0_for_tpp(stage0_config)
  parameters = proactive_replay.ReplayParameters(
      policy_name="tpp_inspired",
      dram_capacity_pages=int(dram_capacity_pages),
      F_low=8,
      F_target=16,
      b_max=4,
      candidate_size_K=8,
      history_window_size=20,
      early_reuse_window=64)
  ranker = proactive_stage6_tpp.TPPInspiredRanker(
      epoch_length=epoch_length,
      cold_threshold=cold_threshold,
      dirty_tie_break=dirty_tie_break,
      early_reuse_window=64)
  replay = proactive_replay.ProactiveReplay(
      policy_stage0,
      parameters,
      ranking_policy=ranker,
      invariant_mode=invariant_mode,
      record_details=True,
      capture_page_enter_flags=True,
      measure_decision_latency=measure_latency,
      exclude_current_entering_page=True)
  # This is the same three-step loop as ProactiveReplay.run(). Clearing only
  # access audit rows keeps full-Validation memory bounded; state transitions,
  # event/round/cycle accounting, and candidate construction remain shared.
  replay.register_backing_pages(
      replay._access_values(access)[0] for access in trace)
  for access in trace:
    replay.process_access(access)
    if not retain_access_logs:
      replay.access_logs[:] = []
  raw = replay.result()
  replay.validate_log_accounting()
  if len(raw["rounds"]) != len(ranker.round_audits):
    raise proactive_replay.ReplayInvariantError(
        "TPP round audit count differs from shared Replay rounds.")
  for replay_round, ranker_round in zip(raw["rounds"], ranker.round_audits):
    if replay_round["candidate_pages"] != ranker_round["candidate_pages"]:
      raise proactive_replay.ReplayInvariantError(
          "TPP ranker received a different candidate snapshot.")
    replay_round.update({
        "current_epoch": ranker_round["current_epoch"],
        "epoch_length": ranker_round["epoch_length"],
        "cold_threshold": ranker_round["cold_threshold"],
        "dirty_tie_break": ranker_round["dirty_tie_break"],
        "selected_temperature_distribution":
            ranker_round["selected_temperature_distribution"],
        "tpp_contract_id": contract.CONTRACT_ID,
        "tpp_selection_latency": (
            None if replay_round["inference_latency"] is None or
            replay_round["selection_latency"] is None
            else replay_round["inference_latency"] +
            replay_round["selection_latency"]),
    })
  summary = copy.deepcopy(raw["summary"])
  cost_result = proactive_cost.compute_weighted_cost(
      summary, cost_config.profiles["default"])
  latency = stage5_replay._latency_summary(raw["rounds"])
  tpp_selection_values = [
      float(row["tpp_selection_latency"]) for row in raw["rounds"]
      if row.get("tpp_selection_latency") is not None]
  tpp_metrics = ranker.summary_metrics()
  tpp_metrics["selection_latency"] = {
      "count": len(tpp_selection_values),
      "total_seconds": sum(tpp_selection_values),
      "mean_seconds": (
          sum(tpp_selection_values) / float(len(tpp_selection_values))
          if tpp_selection_values else None),
      "p50_seconds":
          stage5_replay._quantile(tpp_selection_values, 0.50),
      "p95_seconds":
          stage5_replay._quantile(tpp_selection_values, 0.95),
      "p99_seconds":
          stage5_replay._quantile(tpp_selection_values, 0.99),
      "measurement_scope":
          "synchronous_tpp_ranking_plus_top_b_selection",
  }
  proactive_demotions = int(summary["proactive_demotions"])
  summary.update({
      "early_reuse_rate": (
          summary["early_reuse_count"] / float(proactive_demotions)
          if proactive_demotions else 0.0),
      "total_decision_time": latency["total_seconds"],
      "mean_decision_time": latency["mean_seconds"],
      "p50_decision_time": latency["p50_seconds"],
      "p95_decision_time": latency["p95_seconds"],
      "p99_decision_time": latency["p99_seconds"],
      "decision_time_status": (
          "measured_synchronous_replay" if measure_latency
          else "measurement_disabled"),
      "weighted_cost": cost_result.weighted_cost,
      "weighted_cost_status": "stage2_frozen_default_profile",
      "weighted_cost_components": {
          "dram_hit_cost": cost_result.dram_hit_cost,
          "nvm_read_cost": cost_result.nvm_read_cost,
          "nvm_write_cost": cost_result.nvm_write_cost,
          "demotion_cost": cost_result.demotion_cost,
      },
      "tpp": tpp_metrics,
  })
  initial_state = {
      "dram_resident": [],
      "nvm_backing_pages":
          sorted({int(replay._access_values(access)[0]) for access in trace}),
      "free_frames": int(dram_capacity_pages),
      "lru_order": [],
      "dirty_pages": [],
  }
  candidate_identity = stage5_contract.candidate_contract_identity()
  lru_contract = {
      "order": "mru_at_head_lru_at_tail",
      "hit": "move_to_mru",
      "page_enter_dram": "insert_mru",
      "demotion": "remove_resident",
  }
  experiment_id = contract.parameter_id(
      epoch_length, cold_threshold, dirty_tie_break)
  result = {
      "schema_version": contract.RESULT_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "stage_status": contract.IMPLEMENTED,
      "policy": contract.POLICY,
      "policy_display_name": contract.DISPLAY_NAME,
      "seed": None,
      "workload": workload,
      "split": split,
      "split_role": split_role,
      "formal_test": False,
      "test_used_for_selection": False,
      "trace_sha256": trace_sha256,
      "trace_range": {
          "start": int(source_interval["start"]),
          "end": int(source_interval["start"]) + len(trace),
          "interval": "half_open",
      },
      "raw_access_event_count": len(trace),
      "dram_capacity_pages": int(dram_capacity_pages),
      "nvm_capacity_model": "unbounded_backing_tier",
      "page_size_bytes": 4096,
      "working_set_definition":
          "active_unique_pages_from_train_and_validation",
      "working_set_pages": int(working_set_pages),
      "dram_working_set_ratio": 0.2,
      "capacity_claim":
          "conditional_engineering_default_not_capacity_rule_v2_pass",
      "page_enter_dram_semantics":
          "occupies_one_free_frame_regardless_of_source",
      "initial_state": initial_state,
      "initial_state_sha256":
          proactive_stage4.fingerprint_value(initial_state),
      "cost_profile": {
          "name": "default", "weights": dict(contract.FROZEN_COST)},
      "F_low": 8,
      "F_target": 16,
      "candidate_size_K": 8,
      "b_max": 4,
      "B": None,
      "b_t_rule": "min(b_max,F_target-F_t,|C_t|)",
      "fallback_policy": "lru",
      "trigger_mode": "low_watermark",
      "candidate_source": "lru_tail",
      "candidate_contract": candidate_identity,
      "candidate_contract_sha256": candidate_identity["sha256"],
      "lru_contract_sha256":
          proactive_stage4.fingerprint_value(lru_contract),
      "selector_status": "disabled",
      "old_finals_v3_stage_artifacts_used": False,
      "checkpoint": None,
      "future_information": "not_accessed",
      "promotion_performed": False,
      "tpp_fallback_used": False,
      "emergency_fallback_policy": "shared_lru_not_tpp_selection",
      "tpp_parameters": {
          "experiment_id": experiment_id,
          "epoch_length": int(epoch_length),
          "cold_threshold": int(cold_threshold),
          "dirty_tie_break": bool(dirty_tie_break),
          "epoch_interval":
              "half_open_epoch_id_equals_access_index_div_epoch_length",
          "cold_short_reuse_window_accesses": 64,
      },
      "summary": summary,
      "latency": latency,
      "events": raw["events"],
      "rounds": raw["rounds"],
      "cycles": raw["cycles"],
      "accesses": raw["accesses"] if retain_access_logs else [],
      "access_log_retention": (
          "full" if retain_access_logs else
          "omitted_full_validation_memory_bound_round_event_logs_retained"),
      "invariant_mode": invariant_mode,
      "final_full_invariant_check": True,
      "final_state": raw["state"],
      "policy_state": {"tpp_inspired": ranker.state_snapshot()},
      "interpretation_boundary": (
          "Replay-compatible synchronous adaptation; measures ranking "
          "quality, NVM events, weighted cost, state trajectory, and "
          "synchronous selection overhead. It is not Linux TPP, background "
          "execution, promotion, or foreground latency."),
      "performance_conclusion": None,
  }
  result["semantic_result_sha256"] = _semantic_fingerprint(result)
  contract.audit_result(result)
  return result
