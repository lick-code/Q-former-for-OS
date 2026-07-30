# coding=utf-8
"""Official Stage-5 rankers for the single proactive Replay state machine."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as contract


class ProactiveLRURanker(proactive_replay.CandidateRankingPolicy):
  """Current LRU-tail order, coldest candidate first."""

  policy_name = "Proactive-LRU"

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del state, candidate_features, policy_context
    count = len(candidates)
    return [{
        "page": page,
        "score": float(count - index),
        "rule": "lru_tail_cold_to_hot",
        "lru_tail_rank": index,
    } for index, page in enumerate(candidates)]


class ProactiveClockRanker(proactive_replay.CandidateRankingPolicy):
  """Second-chance CLOCK constrained to the current LRU-tail K snapshot.

  ``pointer_slot`` is persistent.  At the beginning of a round it maps to
  ``pointer_slot % len(C_t)`` in the current oldest-to-newest candidate list.
  This provides an explicit deterministic mapping when C_t changes without
  ever scanning a page outside C_t.
  """

  policy_name = "Proactive-CLOCK"

  def __init__(self, pointer_slot: int = 0):
    self.pointer_slot = int(pointer_slot)
    if self.pointer_slot < 0:
      raise contract.Stage5ContractError("CLOCK pointer cannot be negative.")
    self.reference_bits: Dict[int, int] = {}
    self.round_audits: List[Dict[str, Any]] = []

  def on_page_enter_dram(self, state, page):
    del state
    self.reference_bits[int(page)] = 1

  def on_page_access(self, state, page, rw):
    del rw
    if page not in state.dram_resident:
      raise proactive_replay.ReplayInvariantError(
          "CLOCK access hook received a non-DRAM page.")
    self.reference_bits[int(page)] = 1

  def on_page_demoted(self, state, page, event_type):
    del state, event_type
    self.reference_bits.pop(int(page), None)

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del candidate_features
    candidates = list(candidates)
    if not candidates:
      self.round_audits.append({
          "access_index": state.access_index,
          "candidate_pages": [],
          "scanned_pages": [],
          "selected_pages": [],
          "pointer_before": self.pointer_slot,
          "pointer_after": self.pointer_slot,
      })
      return []
    missing = [
        page for page in state.dram_resident if page not in self.reference_bits]
    if missing:
      raise proactive_replay.ReplayInvariantError(
          "CLOCK lacks reference bits for DRAM pages: {}.".format(
              sorted(missing)))
    n = len(candidates)
    b_t = min(
        state.parameters.b_max,
        state.parameters.F_target - state.free_frames,
        n)
    pointer_before = self.pointer_slot
    index = self.pointer_slot % n
    scans = 0
    selected: List[int] = []
    selected_set = set()
    scan_trace = []
    # One pass may clear all bits; a second pass is sufficient to select every
    # legal candidate.  A selected page is never selected again in the round.
    while len(selected) < b_t and scans < 2 * n:
      page = candidates[index]
      bit_before = self.reference_bits[page]
      action = None
      if page in selected_set:
        action = "skip_already_selected"
      elif bit_before == 1:
        self.reference_bits[page] = 0
        action = "clear_and_skip"
      else:
        selected.append(page)
        selected_set.add(page)
        action = "select"
      scan_trace.append({
          "scan_index": scans,
          "candidate_slot": index,
          "page": page,
          "reference_bit_before": bit_before,
          "reference_bit_after": self.reference_bits[page],
          "action": action,
      })
      scans += 1
      index = (index + 1) % n
    if len(selected) != b_t:
      raise proactive_replay.ReplayInvariantError(
          "CLOCK could not select b_t pages within two candidate passes.")
    self.pointer_slot = index
    remainder = [
        page for page in candidates if page not in selected_set]
    ranked_pages = selected + remainder
    rank_position = {page: position for position, page in enumerate(
        ranked_pages)}
    audit = {
        "access_index": state.access_index,
        "cycle_id": policy_context["cycle_id"],
        "cycle_round_index": policy_context["cycle_round_index"],
        "candidate_pages": candidates,
        "scanned_pages": [item["page"] for item in scan_trace],
        "scan_trace": scan_trace,
        "selected_pages": selected,
        "pointer_before": pointer_before,
        "pointer_mapping_start_slot": pointer_before % n,
        "pointer_after": self.pointer_slot,
        "candidate_scope_preserved":
            set(item["page"] for item in scan_trace).issubset(set(candidates)),
    }
    self.round_audits.append(audit)
    return [{
        "page": page,
        "score": float(n - rank_position[page]),
        "rule": "candidate_scoped_second_chance_clock",
        "selected_by_clock": page in selected_set,
        "pointer_before": pointer_before,
        "pointer_after": self.pointer_slot,
    } for page in ranked_pages]


class OracleRanker(proactive_replay.CandidateRankingPolicy):
  """Candidate-set Oracle using only the frozen Stage-4 future label."""

  policy_name = "Oracle"

  def __init__(
      self, trace: Sequence[Any], lookahead: int = 256,
      weights: Sequence[float] = (1.0, 1.0, 2.0)):
    if lookahead != 256 or tuple(float(x) for x in weights) != (1.0, 1.0, 2.0):
      raise contract.Stage5ContractError("Oracle label parameters are frozen.")
    self.trace = trace
    self.lookahead = lookahead
    self.weights = tuple(float(value) for value in weights)
    self.future_information_accessed = True
    self.round_audits: List[Dict[str, Any]] = []

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del candidate_features
    rows = []
    for lru_rank, page in enumerate(candidates):
      components = proactive_stage4.label_components(
          self.trace, state.access_index, page, self.lookahead)
      score = proactive_stage4.composite_label(components, self.weights)
      if not math.isfinite(score):
        raise proactive_replay.ReplayInvariantError(
            "Oracle produced a non-finite label.")
      rows.append({
          "page": page,
          "score": float(score),
          "lru_tail_rank": lru_rank,
          "label_components": components,
          "tie_break": [lru_rank, int(page)],
      })
    ranked = sorted(
        rows,
        key=lambda item: (
            -item["score"], item["lru_tail_rank"], int(item["page"])))
    self.round_audits.append({
        "access_index": state.access_index,
        "cycle_id": policy_context["cycle_id"],
        "cycle_round_index": policy_context["cycle_round_index"],
        "candidate_pages": list(candidates),
        "ranked_pages": [item["page"] for item in ranked],
        "complete_lookahead": all(
            item["label_components"]["complete_future_window"]
            for item in ranked),
        "effective_lookahead": [
            item["label_components"]["effective_lookahead"]
            for item in ranked],
        "tie_break":
            "higher_label_then_colder_lru_tail_rank_then_lower_page_id",
    })
    return ranked


class CAPDRanker(proactive_replay.CandidateRankingPolicy):
  """Stage-4 checkpoint adapter with no trace/future-label input."""

  policy_name = "CAPD"

  def __init__(
      self, checkpoint_path: str, checkpoint_sha256: str, seed: int,
      device: str = "cpu", history_H: int = 20, candidate_K: int = 8,
      lookahead: int = 256, weights: Sequence[float] = (1.0, 1.0, 2.0)):
    if (seed not in contract.CAPD_SEEDS or history_H != 20 or
        candidate_K != 8 or lookahead != 256 or
        tuple(float(item) for item in weights) != (1.0, 1.0, 2.0)):
      raise contract.Stage5ContractError("CAPD frozen model identity changed.")
    if proactive_stage4.fingerprint_file(checkpoint_path) != checkpoint_sha256:
      raise contract.Stage5ContractError("CAPD checkpoint SHA-256 mismatch.")
    from qmap import qmap_eval  # Lazy: rule policies do not require torch.
    import torch
    torch.use_deterministic_algorithms(True)
    if hasattr(torch.backends, "cudnn"):
      torch.backends.cudnn.benchmark = False
      torch.backends.cudnn.deterministic = True
    checkpoint = torch.load(
        checkpoint_path, map_location=torch.device("cpu"))
    if checkpoint.get("contract_id") != proactive_stage4.CONTRACT_ID:
      raise contract.Stage5ContractError(
          "CAPD rejected a historical/non-proactive checkpoint.")
    training_contract = checkpoint.get("stage4_training_contract")
    if not isinstance(training_contract, Mapping):
      raise contract.Stage5ContractError(
          "CAPD checkpoint lacks Stage-4 training contract.")
    if checkpoint.get("stage4_training_contract_fingerprint") != (
        proactive_stage4.fingerprint_value(training_contract)):
      raise contract.Stage5ContractError(
          "CAPD checkpoint training-contract fingerprint mismatch.")
    if checkpoint.get("experiment_id") != "L256_lam1-1-2_K8_H20":
      raise contract.Stage5ContractError(
          "CAPD checkpoint experiment identity mismatch.")
    if training_contract.get("expected_shape") != {
        "H": 20, "K": 8, "page_state_dim": 4}:
      raise contract.Stage5ContractError("CAPD checkpoint shape mismatch.")
    if training_contract.get("labels") != {
        "lambda_1": 1.0, "lambda_2": 1.0, "lambda_3": 2.0}:
      raise contract.Stage5ContractError("CAPD label identity mismatch.")
    if (checkpoint.get("test_trace_opened") is not False or
        checkpoint.get("selector_status") != "disabled"):
      raise contract.Stage5ContractError("CAPD checkpoint is contaminated.")
    vocab = checkpoint.get("vocab_contract", {})
    if not (vocab.get("page_frozen") is True and
            vocab.get("pc_frozen") is True):
      raise contract.Stage5ContractError(
          "CAPD checkpoint vocabularies are not Train-fitted/frozen.")
    checkpoint_seed = checkpoint.get("seed", training_contract.get("seed"))
    if checkpoint_seed is not None and int(checkpoint_seed) != int(seed):
      raise contract.Stage5ContractError("CAPD checkpoint seed mismatch.")
    del checkpoint
    self.predictor = qmap_eval.QMAPPolicy(
        checkpoint_path=checkpoint_path, device=torch.device(device),
        history_length=history_H, candidate_count=candidate_K,
        lookahead=lookahead, ablation="cross_attention")
    page_vocab = self.predictor._feature_embedder.page_embedder
    pc_vocab = self.predictor._feature_embedder.pc_embedder
    if not page_vocab.frozen or not pc_vocab.frozen:
      raise contract.Stage5ContractError(
          "Loaded CAPD vocabularies are not frozen.")
    if (finals_config.fingerprint_value(page_vocab.input_to_index) !=
        vocab.get("page_vocab_fingerprint") or
        finals_config.fingerprint_value(pc_vocab.input_to_index) !=
        vocab.get("pc_vocab_fingerprint")):
      raise contract.Stage5ContractError(
          "Loaded CAPD vocabulary fingerprint mismatch.")
    self.seed = int(seed)
    self.checkpoint_path = checkpoint_path
    self.checkpoint_sha256 = checkpoint_sha256
    self.future_information_accessed = False
    self.score_inputs = (
        "current_candidate_pages", "past_history", "current_access_index",
        "past_dram_entry_time", "current_dirty_state")

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del candidate_features, policy_context
    if not candidates:
      return []
    # Deliberately no trace or label object exists in this adapter.
    self.predictor.synchronize()
    scores = self.predictor.score_explicit_candidates(
        candidates=candidates,
        history=list(state.history_window),
        access_index=state.access_index,
        dram_insert_time=state.dram_entry_index,
        dirty_pages={
            page for page, dirty in state.dirty_state.items() if dirty})
    self.predictor.synchronize()
    if len(scores) != len(candidates):
      raise proactive_replay.ReplayInvariantError(
          "CAPD score count does not match current candidates.")
    if any(not math.isfinite(float(score)) for score in scores):
      raise proactive_replay.ReplayInvariantError(
          "CAPD produced a non-finite candidate score.")
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-float(scores[item[0]]), item[0], int(item[1])))
    return [{
        "page": page,
        "score": float(scores[index]),
        "rule": "stage4_checkpoint_current_and_past_only",
        "original_candidate_rank": index,
    } for index, page in ranked]


class TPPInspiredPendingPolicy(proactive_replay.CandidateRankingPolicy):
  """Frozen Stage-6 interface; never substitutes another policy."""

  policy_name = "TPP-inspired"
  implementation_status = contract.PENDING_TPP
  state_schema = {
      "sampling_epoch": None,
      "hot_cold_state": {},
      "reference_state": {},
      "sampling_parameters": {},
  }

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del state, candidates, candidate_features, policy_context
    raise contract.PendingStage6Error(
        "TPP-inspired is pending_stage6; no LRU fallback is permitted.")


def build_ranker(
    policy: str, trace: Optional[Sequence[Any]] = None,
    checkpoint: Optional[Mapping[str, Any]] = None,
    device: str = "cpu") -> proactive_replay.CandidateRankingPolicy:
  if policy == "proactive_lru":
    return ProactiveLRURanker()
  if policy == "proactive_clock":
    return ProactiveClockRanker()
  if policy == "oracle":
    if trace is None:
      raise contract.Stage5ContractError("Oracle requires its current trace.")
    return OracleRanker(trace)
  if policy == "capd":
    if checkpoint is None:
      raise contract.Stage5ContractError("CAPD requires a frozen checkpoint.")
    return CAPDRanker(
        checkpoint["path"], checkpoint["sha256"], int(checkpoint["seed"]),
        device=device)
  if policy == "tpp_inspired":
    return TPPInspiredPendingPolicy()
  raise contract.Stage5ContractError(
      "No proactive ranker registered for {}.".format(policy))


POLICY_REGISTRY = {
    "reactive_lru": {
        "display_name": "Reactive-LRU",
        "mode": "reactive",
        "status": "implemented",
        "ranker": None,
    },
    "proactive_lru": {
        "display_name": "Proactive-LRU",
        "mode": "proactive",
        "status": "implemented",
        "ranker": ProactiveLRURanker,
    },
    "proactive_clock": {
        "display_name": "Proactive-CLOCK",
        "mode": "proactive",
        "status": "implemented",
        "ranker": ProactiveClockRanker,
    },
    "tpp_inspired": {
        "display_name": "TPP-inspired",
        "mode": "proactive",
        "status": contract.PENDING_TPP,
        "ranker": TPPInspiredPendingPolicy,
    },
    "capd": {
        "display_name": "CAPD",
        "mode": "proactive",
        "status": "implemented",
        "ranker": CAPDRanker,
    },
    "oracle": {
        "display_name": "Oracle",
        "mode": "proactive_analysis_upper_bound",
        "status": "implemented",
        "ranker": OracleRanker,
    },
}
