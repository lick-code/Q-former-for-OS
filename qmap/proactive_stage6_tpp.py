# coding=utf-8
"""TPP-inspired Stage-6 ranker for the shared proactive Replay state machine."""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qmap import proactive_replay
from qmap import proactive_stage6_contract as contract


TEMPERATURE_PRIORITY = {"Cold": 0, "Warm": 1, "Hot": 2}


class TPPPageState(object):
  """State belonging to one DRAM residence lifecycle."""

  def __init__(
      self, referenced_current_epoch: int,
      referenced_previous_epoch: int,
      last_access_epoch: Optional[int],
      dirty: bool,
      residence_lifecycle_id: int):
    self.referenced_current_epoch = int(bool(referenced_current_epoch))
    self.referenced_previous_epoch = int(bool(referenced_previous_epoch))
    self.last_access_epoch = (
        None if last_access_epoch is None else int(last_access_epoch))
    self.dirty = bool(dirty)
    self.residence_lifecycle_id = int(residence_lifecycle_id)

  def to_dict(self) -> Dict[str, Any]:
    return {
        "referenced_current_epoch": self.referenced_current_epoch,
        "referenced_previous_epoch": self.referenced_previous_epoch,
        "last_access_epoch": self.last_access_epoch,
        "dirty": self.dirty,
        "residence_lifecycle_id": self.residence_lifecycle_id,
    }


class TPPInspiredRanker(proactive_replay.CandidateRankingPolicy):
  """Epoch hot/warm/cold ranking restricted to the supplied LRU-tail K."""

  policy_name = "TPP-inspired"
  contract_id = contract.CONTRACT_ID
  future_information_accessed = False
  promotion_performed = False
  fallback_to_lru_used = False

  def __init__(
      self, epoch_length: int, cold_threshold: int,
      dirty_tie_break: bool, early_reuse_window: int = 64):
    contract.validate_tpp_parameters(
        epoch_length, cold_threshold, dirty_tie_break)
    if (not isinstance(early_reuse_window, int) or
        isinstance(early_reuse_window, bool) or early_reuse_window != 64):
      raise contract.Stage6ContractError(
          "TPP cold short-reuse window is frozen to 64 accesses.")
    self.epoch_length = int(epoch_length)
    self.cold_threshold = int(cold_threshold)
    self.dirty_tie_break = bool(dirty_tie_break)
    self.early_reuse_window = int(early_reuse_window)
    self.current_epoch = 0
    self.last_observed_access_index = -1
    self.page_states: Dict[int, TPPPageState] = {}
    self._lifecycle_counter = 0
    self._epoch_transition_count = 0
    self._missing_state_initializations = 0
    self._candidate_temperature_counts = collections.Counter()
    self._selected_temperature_counts = collections.Counter()
    self._selected_dirty_counts = collections.Counter()
    self._cold_demoted_at: Dict[int, int] = {}
    self._cold_selected_count = 0
    self._cold_short_reuse_count = 0
    self._latest_rank_by_page: Dict[int, Dict[str, Any]] = {}
    self.round_audits: List[Dict[str, Any]] = []

  @property
  def experiment_id(self) -> str:
    return contract.parameter_id(
        self.epoch_length, self.cold_threshold, self.dirty_tie_break)

  def _target_epoch(self, access_index: int) -> int:
    if access_index < 0:
      return 0
    return int(access_index) // self.epoch_length

  def advance_to_access(self, access_index: int) -> int:
    """Advances epoch bits with exact multi-empty-epoch decay semantics."""
    target = self._target_epoch(int(access_index))
    if target < self.current_epoch:
      raise proactive_replay.ReplayInvariantError(
          "TPP access index moved backwards across epochs.")
    steps = target - self.current_epoch
    if steps == 1:
      for page_state in self.page_states.values():
        page_state.referenced_previous_epoch = (
            page_state.referenced_current_epoch)
        page_state.referenced_current_epoch = 0
    elif steps >= 2:
      # Two sequential shifts always erase both retained reference epochs.
      for page_state in self.page_states.values():
        page_state.referenced_previous_epoch = 0
        page_state.referenced_current_epoch = 0
    self._epoch_transition_count += steps
    self.current_epoch = target
    self.last_observed_access_index = max(
        self.last_observed_access_index, int(access_index))
    return self.current_epoch

  def _new_lifecycle(self) -> int:
    self._lifecycle_counter += 1
    return self._lifecycle_counter

  def on_page_enter_dram(self, state, page):
    self.advance_to_access(state.access_index)
    page = int(page)
    if page in self.page_states:
      raise proactive_replay.ReplayInvariantError(
          "TPP page entered DRAM without ending its old lifecycle.")
    self.page_states[page] = TPPPageState(
        referenced_current_epoch=1,
        referenced_previous_epoch=0,
        last_access_epoch=self.current_epoch,
        dirty=bool(state.dirty_state.get(page, False)),
        residence_lifecycle_id=self._new_lifecycle())

  def on_page_access(self, state, page, rw):
    self.advance_to_access(state.access_index)
    page = int(page)
    if page not in state.dram_resident:
      raise proactive_replay.ReplayInvariantError(
          "TPP access hook received a non-DRAM page.")
    page_state = self.page_states.get(page)
    if page_state is None:
      raise proactive_replay.ReplayInvariantError(
          "TPP lacks state for a DRAM-resident page.")
    page_state.referenced_current_epoch = 1
    page_state.last_access_epoch = self.current_epoch
    page_state.dirty = bool(state.dirty_state.get(page, False) or rw == 1)
    demoted_at = self._cold_demoted_at.pop(page, None)
    if demoted_at is not None:
      distance = int(state.access_index) - int(demoted_at)
      if 0 < distance <= self.early_reuse_window:
        self._cold_short_reuse_count += 1

  def on_page_demoted(self, state, page, event_type):
    page = int(page)
    page_state = self.page_states.pop(page, None)
    if page_state is None:
      raise proactive_replay.ReplayInvariantError(
          "TPP demotion lacks a residence state.")
    if event_type == proactive_replay.PROACTIVE_DEMOTION:
      selected = self._latest_rank_by_page.get(page)
      if selected is None:
        raise proactive_replay.ReplayInvariantError(
            "TPP proactive demotion is outside its latest ranking.")
      temperature = selected["temperature"]
      self._selected_temperature_counts[temperature] += 1
      self._selected_dirty_counts[
          "dirty" if selected["dirty"] else "clean"] += 1
      if temperature == "Cold":
        self._cold_selected_count += 1
        self._cold_demoted_at[page] = int(state.access_index)
    elif event_type == proactive_replay.EMERGENCY_DEMOTION:
      # Emergency is the shared LRU fallback, never a TPP selection.
      pass
    else:
      raise proactive_replay.ReplayInvariantError(
          "TPP received a non-proactive/non-emergency demotion.")
    self._latest_rank_by_page.pop(page, None)

  def classify(self, page_state: TPPPageState) -> str:
    if page_state.referenced_current_epoch:
      return "Hot"
    if self.cold_threshold == 1:
      return "Cold"
    if page_state.referenced_previous_epoch:
      return "Warm"
    return "Cold"

  def _age(self, page_state: TPPPageState) -> int:
    if page_state.last_access_epoch is None:
      # Deterministic sentinel: older than every representable observed age.
      return self.current_epoch + 1
    return max(0, self.current_epoch - page_state.last_access_epoch)

  def _ranking_key(
      self, temperature: str, dirty: bool, age: int,
      lru_tail_rank: int, page: int) -> List[int]:
    temperature_rank = TEMPERATURE_PRIORITY[temperature]
    if self.dirty_tie_break:
      class_rank = temperature_rank * 2 + int(bool(dirty))
    else:
      class_rank = temperature_rank
    return [
        class_rank,
        -int(age),
        int(lru_tail_rank),
        int(page),
    ]

  def _state_for_candidate(self, state, page: int) -> TPPPageState:
    page_state = self.page_states.get(page)
    if page_state is not None:
      return page_state
    # This branch defines deterministic behavior for an externally supplied
    # residence with missing history. Normal Replay never reaches it.
    if page not in state.dram_resident:
      raise proactive_replay.ReplayInvariantError(
          "TPP candidate is not DRAM resident.")
    self._missing_state_initializations += 1
    page_state = TPPPageState(
        referenced_current_epoch=0,
        referenced_previous_epoch=0,
        last_access_epoch=None,
        dirty=bool(state.dirty_state.get(page, False)),
        residence_lifecycle_id=self._new_lifecycle())
    self.page_states[page] = page_state
    return page_state

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    self.advance_to_access(state.access_index)
    candidates = [int(page) for page in candidates]
    if len(candidates) != len(set(candidates)):
      raise proactive_replay.ReplayInvariantError(
          "TPP received duplicate candidates.")
    feature_pages = [int(item["page"]) for item in candidate_features]
    if feature_pages != candidates:
      raise proactive_replay.ReplayInvariantError(
          "TPP candidate feature identity/order changed.")
    rows = []
    for lru_tail_rank, page in enumerate(candidates):
      page_state = self._state_for_candidate(state, page)
      page_state.dirty = bool(state.dirty_state.get(page, False))
      temperature = self.classify(page_state)
      age = self._age(page_state)
      ranking_key = self._ranking_key(
          temperature, page_state.dirty, age, lru_tail_rank, page)
      rows.append({
          "page": page,
          "score": 0.0,
          "referenced_current_epoch":
              page_state.referenced_current_epoch,
          "referenced_previous_epoch":
              page_state.referenced_previous_epoch,
          "last_access_epoch": page_state.last_access_epoch,
          "age_in_epochs": age,
          "temperature": temperature,
          "dirty": page_state.dirty,
          "lru_tail_rank": lru_tail_rank,
          "residence_lifecycle_id":
              page_state.residence_lifecycle_id,
          "ranking_key": ranking_key,
          "rule": (
              "temperature_dirty_age_lru_page"
              if self.dirty_tie_break
              else "temperature_age_lru_page_dirty_ignored"),
      })
      self._candidate_temperature_counts[temperature] += 1
    ranked = sorted(rows, key=lambda item: tuple(item["ranking_key"]))
    for position, row in enumerate(ranked):
      row["score"] = float(len(ranked) - position)
    b_t = min(
        state.parameters.b_max,
        state.parameters.F_target - state.free_frames,
        len(candidates))
    selected = ranked[:b_t]
    self._latest_rank_by_page = {
        row["page"]: row for row in selected}
    selected_distribution = collections.Counter(
        row["temperature"] for row in selected)
    audit = {
        "access_index": int(state.access_index),
        "current_epoch": self.current_epoch,
        "epoch_length": self.epoch_length,
        "cold_threshold": self.cold_threshold,
        "dirty_tie_break": self.dirty_tie_break,
        "cycle_id": policy_context["cycle_id"],
        "cycle_round_index": policy_context["cycle_round_index"],
        "candidate_pages": list(candidates),
        "ranked_pages": [row["page"] for row in ranked],
        "selected_pages": [row["page"] for row in selected],
        "selected_temperature_distribution": {
            name: int(selected_distribution.get(name, 0))
            for name in ("Cold", "Warm", "Hot")},
        "candidate_scope_preserved":
            set(row["page"] for row in ranked) == set(candidates),
        "future_information_accessed": False,
        "promotion_performed": False,
        "fallback_to_lru_used": False,
    }
    self.round_audits.append(audit)
    return ranked

  @staticmethod
  def _distribution(counter: Mapping[str, int],
                    names: Sequence[str]) -> Dict[str, Any]:
    counts = {name: int(counter.get(name, 0)) for name in names}
    total = sum(counts.values())
    return {
        "counts": counts,
        "ratios": {
            name: (counts[name] / float(total) if total else 0.0)
            for name in names},
        "total": total,
    }

  def summary_metrics(self) -> Dict[str, Any]:
    candidate_distribution = self._distribution(
        self._candidate_temperature_counts, ("Cold", "Warm", "Hot"))
    selected_distribution = self._distribution(
        self._selected_temperature_counts, ("Cold", "Warm", "Hot"))
    dirty_distribution = self._distribution(
        self._selected_dirty_counts, ("clean", "dirty"))
    return {
        "experiment_id": self.experiment_id,
        "epoch_length": self.epoch_length,
        "cold_threshold": self.cold_threshold,
        "dirty_tie_break": self.dirty_tie_break,
        "current_epoch": self.current_epoch,
        "epoch_transition_count": self._epoch_transition_count,
        "candidate_temperature_distribution": candidate_distribution,
        "selected_temperature_distribution": selected_distribution,
        "selected_dirty_distribution": dirty_distribution,
        "cold_selected_count": self._cold_selected_count,
        "cold_short_reuse_count": self._cold_short_reuse_count,
        "cold_short_reuse_rate": (
            self._cold_short_reuse_count / float(self._cold_selected_count)
            if self._cold_selected_count else 0.0),
        "cold_short_reuse_window_accesses": self.early_reuse_window,
        "missing_state_initializations":
            self._missing_state_initializations,
        "future_information_accessed": False,
        "promotion_performed": False,
        "fallback_to_lru_used": False,
    }

  def state_snapshot(self) -> Dict[str, Any]:
    return {
        "current_epoch": self.current_epoch,
        "epoch_length": self.epoch_length,
        "cold_threshold": self.cold_threshold,
        "dirty_tie_break": self.dirty_tie_break,
        "page_states": {
            str(page): self.page_states[page].to_dict()
            for page in sorted(self.page_states)},
        "metrics": self.summary_metrics(),
        "round_audits": list(self.round_audits),
    }
