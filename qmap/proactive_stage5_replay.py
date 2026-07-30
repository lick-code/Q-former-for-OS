# coding=utf-8
"""Unified Stage-5 Replay adapter, result schema, and frozen Cost binding."""

from __future__ import annotations

import copy
import statistics
from typing import Any, Dict, Mapping, Optional, Sequence

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as contract
from qmap import proactive_stage5_policies as policies


DISPLAY_NAMES = {
    "reactive_lru": "Reactive-LRU",
    "proactive_lru": "Proactive-LRU",
    "proactive_clock": "Proactive-CLOCK",
    "capd": "CAPD",
    "oracle": "Oracle",
}
METHOD_NAMES = {
    "reactive_lru": "reactive_lru",
    "proactive_lru": "proactive_lru",
    "proactive_clock": "proactive_clock",
    "capd": "capd_proactive",
    "oracle": "oracle",
}


def _quantile(values: Sequence[float], probability: float) -> Optional[float]:
  if not values:
    return None
  ordered = sorted(float(value) for value in values)
  position = (len(ordered) - 1) * probability
  lower = int(position)
  upper = min(lower + 1, len(ordered) - 1)
  fraction = position - lower
  return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _stage0_for_policy(
    stage0: Mapping[str, Any], policy: str,
    checkpoint: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
  """Builds a policy-specific, fully frozen Stage-0 runtime contract."""
  value = copy.deepcopy(stage0)
  value["evaluation"]["policy_name"] = policy
  value["method"]["name"] = METHOD_NAMES[policy]
  value["method"]["selector"] = "disabled"
  value["evaluation"]["random_seed"] = None
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

  if policy == "reactive_lru":
    if checkpoint is not None:
      raise contract.Stage5ContractError(
          "Reactive-LRU must not receive a checkpoint.")
    value["active_demotion"].update({
        "F_low": None,
        "F_target": None,
        "b_max": None,
    })
    value["method"].update({
        "candidate_size_K": None,
        # Stage-0 keeps this shared schema token even though Reactive-LRU
        # never constructs a candidate set.
        "candidate_source": "lru_tail",
        "fallback_policy": "not_applicable",
        "trigger_mode": "on_demand_no_free_frame",
    })
    value["freeze_status"]["stage4_candidate"] = "not_applicable"
    value["freeze_status"]["stage4_training"] = "not_applicable"
  else:
    value["method"].update({
        "candidate_size_K": 8,
        "candidate_source": "lru_tail",
        "fallback_policy": "lru",
        "trigger_mode": "low_watermark",
    })
    value["freeze_status"]["stage4_candidate"] = "frozen"
    if policy in ("proactive_lru", "proactive_clock"):
      if checkpoint is not None:
        raise contract.Stage5ContractError(
            "{} must not receive a checkpoint.".format(policy))
      value["freeze_status"]["stage4_training"] = "not_applicable"
    elif policy == "oracle":
      if checkpoint is not None:
        raise contract.Stage5ContractError(
            "Oracle must not receive a checkpoint.")
      value["freeze_status"]["stage4_training"] = "frozen"
      value["model"].update({
          "lookahead_L": 256,
          "label_weights": {
              "lambda_1": 1.0,
              "lambda_2": 1.0,
              "lambda_3": 2.0,
          },
      })
    elif policy == "capd":
      if not isinstance(checkpoint, Mapping):
        raise contract.Stage5ContractError(
            "CAPD runtime contract requires a frozen checkpoint.")
      missing = {"seed", "path", "sha256"} - set(checkpoint)
      if missing:
        raise contract.Stage5ContractError(
            "CAPD checkpoint binding is incomplete: {}".format(
                sorted(missing)))
      digest = checkpoint["sha256"]
      if (int(checkpoint["seed"]) not in contract.CAPD_SEEDS or
          not isinstance(checkpoint["path"], str) or
          not checkpoint["path"] or
          not isinstance(digest, str) or len(digest) != 64 or
          any(character not in "0123456789abcdef" for character in digest)):
        raise contract.Stage5ContractError(
            "CAPD checkpoint seed/path/SHA-256 binding is invalid.")
      value["freeze_status"]["stage4_training"] = "frozen"
      value["evaluation"]["random_seed"] = int(checkpoint["seed"])
      value["model"].update({
          "history_H": 20,
          "lookahead_L": 256,
          "label_weights": {
              "lambda_1": 1.0,
              "lambda_2": 1.0,
              "lambda_3": 2.0,
          },
          "model_checkpoint": {
              "status": "frozen",
              "path": checkpoint["path"],
              "fingerprint": checkpoint["sha256"],
          },
      })
    else:
      raise contract.Stage5ContractError(
          "No Stage-0 runtime mapping for policy: " + policy)
  finals_config.validate_config(value)
  return value


def _parameters(policy: str, dram_capacity_pages: int
                ) -> proactive_replay.ReplayParameters:
  if policy == "reactive_lru":
    return proactive_replay.ReplayParameters(
        policy_name=policy,
        dram_capacity_pages=dram_capacity_pages,
        history_window_size=20,
        early_reuse_window=64)
  return proactive_replay.ReplayParameters(
      policy_name=policy,
      dram_capacity_pages=dram_capacity_pages,
      F_low=8,
      F_target=16,
      b_max=4,
      candidate_size_K=8,
      history_window_size=20,
      early_reuse_window=64)


def _latency_summary(rounds: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  values = []
  feature = 0.0
  inference = 0.0
  selection = 0.0
  for row in rounds:
    components = [
        row.get("feature_latency"), row.get("inference_latency"),
        row.get("selection_latency")]
    if all(value is not None for value in components):
      feature += float(components[0])
      inference += float(components[1])
      selection += float(components[2])
      values.append(sum(float(value) for value in components))
  return {
      "count": len(values),
      "total_seconds": sum(values),
      "mean_seconds": statistics.mean(values) if values else None,
      "p50_seconds": _quantile(values, 0.50),
      "p95_seconds": _quantile(values, 0.95),
      "p99_seconds": _quantile(values, 0.99),
      "feature_total_seconds": feature,
      "inference_total_seconds": inference,
      "selection_total_seconds": selection,
      "measurement_scope": "synchronous_replay_decision_overhead",
  }


def _semantic_fingerprint(result: Mapping[str, Any]) -> str:
  summary = copy.deepcopy(result["summary"])
  for field in (
      "total_decision_time", "mean_decision_time", "p50_decision_time",
      "p95_decision_time", "p99_decision_time"):
    summary.pop(field, None)
  rounds = []
  for row in result["rounds"]:
    rounds.append({
        key: copy.deepcopy(value) for key, value in row.items()
        if key not in (
            "feature_latency", "inference_latency", "selection_latency")})
  cycles = []
  for row in result["cycles"]:
    cycles.append({
        key: copy.deepcopy(value) for key, value in row.items()
        if key not in (
            "total_feature_time", "total_inference_time",
            "total_selection_time")})
  return proactive_stage4.fingerprint_value({
      "policy": result["policy"],
      "seed": result["seed"],
      "summary": summary,
      "events": result["events"],
      "rounds": rounds,
      "cycles": cycles,
      "final_state": result["final_state"],
  })


def run_replay(
    stage0_config: Mapping[str, Any],
    stage5_config: Mapping[str, Any],
    cost_config: proactive_cost.CostConfiguration,
    trace: Sequence[Any],
    policy: str,
    workload: str,
    split: str,
    split_role: str,
    source_interval: Mapping[str, int],
    trace_sha256: str,
    dram_capacity_pages: int,
    working_set_pages: int,
    checkpoint: Optional[Mapping[str, Any]] = None,
    device: str = "cpu",
    measure_latency: bool = True,
) -> Dict[str, Any]:
  """Runs one policy without any policy-specific state-machine fork."""
  contract.validate_config(stage5_config)
  contract.assert_runnable_policy(policy)
  if split not in ("train", "validation") or split == "test":
    raise contract.Stage5ContractError("Stage-5 Replay hard-rejects Test.")
  if split_role not in ("training_and_fit", "parameter_selection"):
    raise contract.Stage5ContractError("Split role is not Train/Validation.")
  if policy == "capd":
    if checkpoint is None or int(checkpoint["seed"]) not in contract.CAPD_SEEDS:
      raise contract.Stage5ContractError(
          "CAPD requires one of all three frozen seed checkpoints.")
    seed = int(checkpoint["seed"])
  else:
    if checkpoint is not None:
      raise contract.Stage5ContractError(
          "{} must not receive a CAPD checkpoint.".format(policy))
    seed = None

  policy_stage0 = _stage0_for_policy(
      stage0_config, policy, checkpoint=checkpoint)
  parameters = _parameters(policy, int(dram_capacity_pages))
  ranker = None if policy == "reactive_lru" else policies.build_ranker(
      policy, trace=trace, checkpoint=checkpoint, device=device)
  unique_pages = sorted({int(access["page"]) for access in trace})
  initial_state = {
      "dram_resident": [],
      "nvm_backing_pages": unique_pages,
      "free_frames": int(dram_capacity_pages),
      "lru_order": [],
      "dirty_pages": [],
  }
  initial_state_sha256 = proactive_stage4.fingerprint_value(initial_state)
  replay = proactive_replay.ProactiveReplay(
      policy_stage0,
      parameters,
      ranking_policy=ranker,
      invariant_mode="full",
      record_details=True,
      capture_page_enter_flags=True,
      measure_decision_latency=measure_latency,
      exclude_current_entering_page=True)
  raw = replay.run(trace, copy_trace=False, compact=False)
  replay.validate_log_accounting()
  summary = copy.deepcopy(raw["summary"])
  cost_result = proactive_cost.compute_weighted_cost(
      summary, cost_config.profiles["default"])
  latency = _latency_summary(raw["rounds"])
  proactive_demotions = int(summary["proactive_demotions"])
  summary.update({
      "early_reuse_rate": (
          summary["early_reuse_count"] / float(proactive_demotions)
          if proactive_demotions else None),
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
  })
  candidate_identity = contract.candidate_contract_identity()
  lru_contract = {
      "order": "mru_at_head_lru_at_tail",
      "hit": "move_to_mru",
      "page_enter_dram": "insert_mru",
      "demotion": "remove_resident",
  }
  result = {
      "schema_version": contract.RESULT_SCHEMA_VERSION,
      "contract_id": contract.CONTRACT_ID,
      "stage_status": contract.IMPLEMENTED,
      "policy": policy,
      "policy_display_name": DISPLAY_NAMES[policy],
      "seed": seed,
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
      "initial_state_sha256": initial_state_sha256,
      "cost_profile": {
          "name": "default", "weights": dict(contract.FROZEN_COST)},
      "F_low": None if policy == "reactive_lru" else 8,
      "F_target": None if policy == "reactive_lru" else 16,
      "candidate_size_K": None if policy == "reactive_lru" else 8,
      "b_max": None if policy == "reactive_lru" else 4,
      "B": None,
      "b_t_rule": (
          None if policy == "reactive_lru"
          else "min(b_max,F_target-F_t,|C_t|)"),
      "fallback_policy": None if policy == "reactive_lru" else "lru",
      "trigger_mode":
          None if policy == "reactive_lru" else "low_watermark",
      "candidate_source":
          None if policy == "reactive_lru" else "lru_tail",
      "candidate_contract": candidate_identity,
      "candidate_contract_sha256": candidate_identity["sha256"],
      "lru_contract_sha256":
          proactive_stage4.fingerprint_value(lru_contract),
      "selector_status": "disabled",
      "old_finals_v3_stage_artifacts_used": False,
      "checkpoint": (
          None if checkpoint is None else {
              "seed": seed,
              "path": checkpoint["path"],
              "sha256": checkpoint["sha256"],
              "selection_criterion": checkpoint["selection_criterion"],
          }),
      "future_information": (
          "candidate_scoped_oracle_only" if policy == "oracle"
          else "not_accessed"),
      "summary": summary,
      "latency": latency,
      "events": raw["events"],
      "rounds": raw["rounds"],
      "cycles": raw["cycles"],
      "accesses": raw["accesses"],
      "final_state": raw["state"],
      "policy_state": {
          "clock": (
              {"pointer_slot": ranker.pointer_slot,
               "reference_bits": dict(ranker.reference_bits),
               "round_audits": ranker.round_audits}
              if policy == "proactive_clock" else None),
          "oracle": (
              {"round_audits": ranker.round_audits,
               "online_deployable": False}
              if policy == "oracle" else None),
          "capd": (
              {"future_information_accessed":
                   ranker.future_information_accessed,
               "score_inputs": list(ranker.score_inputs)}
              if policy == "capd" else None),
      },
      "interpretation_boundary": (
          "Synchronous Replay measures policy selection quality, NVM events, "
          "weighted cost, state trajectory, and synchronous decision "
          "overhead; it is not real background execution or foreground "
          "latency."),
      "performance_conclusion": None,
  }
  result["semantic_result_sha256"] = _semantic_fingerprint(result)
  contract.audit_result(result)
  return result
