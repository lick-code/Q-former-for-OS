# coding=utf-8
"""Deterministic stage-1 replay for the proactive CAPD contract.

This module is intentionally isolated from the historical full-DRAM,
single-victim replay in ``qmap_eval.py``.  It consumes the stage-0
``capd_proactive_v1_0`` contract, while all concrete stage-1 values live in
explicitly non-formal synthetic fixtures.

LRU ordering follows the existing repository convention:

* index 0 is MRU;
* the list tail is LRU;
* proactive candidates are returned from oldest to newest.
"""

from __future__ import print_function

import argparse
import array
import collections
import copy
import datetime
import hashlib
import itertools
import json
import os
import platform
import subprocess
import sys
import time

from qmap import finals_config


STAGE1_FIXTURE_SCHEMA_VERSION = "capd_proactive_stage1_fixture_v1_0"
STAGE1_LOG_SCHEMA_VERSION = "capd_proactive_stage1_log_v1_0"
STAGE1_RESULT_SCHEMA_VERSION = "capd_proactive_stage1_result_v1_0"
STAGE1_PROVENANCE_STATUS = "stage1_fixture_completed"

PROACTIVE_DEMOTION = "proactive_demotion"
REACTIVE_DEMOTION = "reactive_demotion"
EMERGENCY_DEMOTION = "emergency_fallback_demotion"
DEMOTION_EVENT_TYPES = (
    PROACTIVE_DEMOTION,
    REACTIVE_DEMOTION,
    EMERGENCY_DEMOTION,
)

ROUND_REQUIRED_FIELDS = (
    "schema_version",
    "decision_id",
    "cycle_id",
    "round_id",
    "cycle_round_index",
    "access_index",
    "policy_name",
    "F_before",
    "F_low",
    "F_target",
    "candidate_pages",
    "candidate_features",
    "policy_scores",
    "selected_pages",
    "b_t",
    "F_after",
    "feature_latency",
    "inference_latency",
    "selection_latency",
    "migration_count",
    "termination_reason",
)

CYCLE_REQUIRED_FIELDS = (
    "schema_version",
    "cycle_id",
    "start_access",
    "end_access",
    "start_F",
    "target_F",
    "number_of_rounds",
    "number_of_pages_demoted",
    "minimum_F",
    "total_inference_time",
    "total_selection_time",
    "emergency_fallback_occurred",
    "termination_reason",
)

SUMMARY_REQUIRED_FIELDS = (
    "schema_version",
    "policy_name",
    "total_accesses",
    "dram_hits",
    "nvm_reads",
    "nvm_writes",
    "page_enter_dram_count",
    "total_demotions",
    "proactive_demotions",
    "reactive_demotions",
    "emergency_demotions",
    "number_of_proactive_cycles",
    "number_of_proactive_rounds",
    "mean_b_t",
    "rounds_per_cycle",
    "minimum_free_frames",
    "average_free_frames",
    "free_frame_exhaustion_count",
    "accesses_below_F_low",
    "early_reuse_count",
    "decision_count",
    "total_decision_time",
    "decision_time_status",
    "weighted_cost",
    "weighted_cost_status",
)


class ReplayConfigurationError(ValueError):
  """Raised when a stage-1 fixture violates the frozen boundary."""


class ReplayInvariantError(RuntimeError):
  """Raised immediately when replay state conservation is violated."""


class _LRUOrder(object):
  """O(1) MRU/LRU updates with the legacy list-facing order."""

  def __init__(self):
    self._pages = collections.OrderedDict()

  def __bool__(self):
    return bool(self._pages)

  def __iter__(self):
    return iter(self._pages)

  def __len__(self):
    return len(self._pages)

  def __getitem__(self, index):
    if isinstance(index, slice):
      return list(self._pages)[index]
    if not isinstance(index, int):
      raise TypeError("LRU index must be an integer or slice.")
    if index == -1:
      try:
        return next(reversed(self._pages))
      except StopIteration:
        raise IndexError("LRU index out of range")
    if index == 0:
      try:
        return next(iter(self._pages))
      except StopIteration:
        raise IndexError("LRU index out of range")
    try:
      return next(itertools.islice(
          self._pages, index if index >= 0 else len(self) + index, None))
    except StopIteration:
      raise IndexError("LRU index out of range")

  def insert(self, index, page):
    if index != 0:
      raise ReplayInvariantError("LRU insert only supports the MRU position.")
    self._pages[page] = None
    self._pages.move_to_end(page, last=False)

  def remove(self, page):
    try:
      del self._pages[page]
    except KeyError:
      raise ValueError("{} is not in LRU".format(page))

  def tail_oldest_first(self, count):
    return list(itertools.islice(reversed(self._pages), 0, count))


def _utc_now():
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ")


def _safe_name(value):
  value = str(value).strip().lower()
  safe = []
  for character in value:
    if character.isalnum() or character in ("_", "-", "."):
      safe.append(character)
    else:
      safe.append("-")
  result = "".join(safe).strip("-")
  return result or "fixture"


def _write_json(path, value):
  finals_config.write_json(path, value)


def _write_jsonl(path, rows):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    for row in rows:
      output_file.write(json.dumps(
          row, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
      output_file.write("\n")


def _require_keys(value, required, context):
  if not isinstance(value, dict):
    raise ReplayConfigurationError("{} must be an object.".format(context))
  missing = sorted(set(required) - set(value))
  if missing:
    raise ReplayConfigurationError(
        "{} missing fields: {}.".format(context, missing))


def _positive_integer(value, field):
  if (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
    raise ReplayConfigurationError(
        "{} must be a positive integer.".format(field))
  return value


class ReplayParameters(object):
  """Validated non-formal parameters used only by stage-1 fixtures."""

  def __init__(
      self, policy_name, dram_capacity_pages, F_low=None, F_target=None,
      b_max=None, candidate_size_K=None, history_window_size=10,
      early_reuse_window=64, non_demotable_pages=None):
    self.policy_name = str(policy_name)
    self.dram_capacity_pages = _positive_integer(
        dram_capacity_pages, "dram_capacity_pages")
    self.history_window_size = _positive_integer(
        history_window_size, "history_window_size")
    self.early_reuse_window = _positive_integer(
        early_reuse_window, "early_reuse_window")
    self.non_demotable_pages = frozenset(non_demotable_pages or ())

    if self.policy_name == "reactive_lru":
      values = (F_low, F_target, b_max, candidate_size_K)
      if any(value is not None for value in values):
        raise ReplayConfigurationError(
            "Reactive-LRU fixture must not define F_low/F_target/b_max/K.")
      self.F_low = None
      self.F_target = None
      self.b_max = None
      self.candidate_size_K = None
      return

    if self.policy_name not in finals_config.PROACTIVE_ACTIVE_POLICIES:
      raise ReplayConfigurationError(
          "Stage-1 replay policy must be reactive_lru or an official active "
          "policy; found {}.".format(self.policy_name))
    self.F_low = _positive_integer(F_low, "F_low")
    self.F_target = _positive_integer(F_target, "F_target")
    self.b_max = _positive_integer(b_max, "b_max")
    self.candidate_size_K = _positive_integer(
        candidate_size_K, "candidate_size_K")
    if not (0 < self.F_low < self.F_target):
      raise ReplayConfigurationError("Fixture requires 0 < F_low < F_target.")
    if self.F_target > self.dram_capacity_pages:
      raise ReplayConfigurationError(
          "F_target cannot exceed dram_capacity_pages.")
    if not (1 <= self.b_max < self.candidate_size_K):
      raise ReplayConfigurationError("Fixture requires 1 <= b_max < K.")

  @classmethod
  def from_fixture(cls, policy_name, value):
    required = (
        "dram_capacity_pages",
        "history_window_size",
        "early_reuse_window",
    )
    _require_keys(value, required, "replay_parameters")
    return cls(
        policy_name=policy_name,
        dram_capacity_pages=value["dram_capacity_pages"],
        F_low=value.get("F_low"),
        F_target=value.get("F_target"),
        b_max=value.get("b_max"),
        candidate_size_K=value.get("candidate_size_K"),
        history_window_size=value["history_window_size"],
        early_reuse_window=value["early_reuse_window"],
        non_demotable_pages=value.get("non_demotable_pages", []),
    )

  def to_dict(self):
    return {
        "policy_name": self.policy_name,
        "dram_capacity_pages": self.dram_capacity_pages,
        "F_low": self.F_low,
        "F_target": self.F_target,
        "b_max": self.b_max,
        "candidate_size_K": self.candidate_size_K,
        "history_window_size": self.history_window_size,
        "early_reuse_window": self.early_reuse_window,
        "non_demotable_pages": sorted(self.non_demotable_pages),
        "parameter_status": "non_formal_fixture",
    }


class CandidateRankingPolicy(object):
  """Minimal replaceable ranking interface for proactive replay."""

  policy_name = None

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    raise NotImplementedError

  # Stage-5 policies may keep lifecycle state (for example CLOCK reference
  # bits).  These no-op hooks preserve the frozen stage-1 behavior for every
  # existing ranker while avoiding a second Replay implementation.
  def on_page_enter_dram(self, state, page):
    del state, page

  def on_page_access(self, state, page, rw):
    del state, page, rw

  def on_page_demoted(self, state, page, event_type):
    del state, page, event_type


class ProactiveLRURanking(CandidateRankingPolicy):
  """Ranks the current LRU-tail candidates from oldest to newest."""

  policy_name = "proactive_lru"

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del state, candidate_features, policy_context
    count = len(candidates)
    return [
        {"page": page, "score": float(count - index)}
        for index, page in enumerate(candidates)
    ]


class DeterministicStubRanking(CandidateRankingPolicy):
  """Fixture-only scorer for deterministic Top-b state-machine tests."""

  policy_name = "deterministic_stub"

  def __init__(self, scores=None):
    self.scores = {
        int(page): float(score) for page, score in (scores or {}).items()}

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del state, candidate_features, policy_context
    indexed = list(enumerate(candidates))
    ranked = sorted(
        indexed,
        key=lambda item: (
            -self.scores.get(item[1], 0.0),
            item[0],
            item[1],
        ))
    return [
        {
            "page": page,
            "score": self.scores.get(page, 0.0),
        }
        for _, page in ranked
    ]


def select_top_b(ranking, b_t):
  """Returns the first ``b_t`` unique pages from an already ranked list."""
  if b_t < 0:
    raise ReplayInvariantError("b_t cannot be negative.")
  selected = []
  seen = set()
  for item in ranking:
    page = item["page"]
    if page in seen:
      raise ReplayInvariantError(
          "Ranking contains duplicate page {}.".format(page))
    seen.add(page)
    if len(selected) < b_t:
      selected.append(page)
  if len(selected) != b_t:
    raise ReplayInvariantError(
        "Ranking has fewer pages than requested b_t={}. ".format(b_t))
  return selected


class ProactiveReplay(object):
  """Synchronous deterministic Replay for stage-1 state validation."""

  def __init__(
      self, stage0_config, parameters, ranking_policy=None,
      invariant_mode="full", record_details=True,
      capture_page_enter_flags=False, measure_decision_latency=False,
      exclude_current_entering_page=False):
    finals_config.validate_config(stage0_config)
    if stage0_config["schema_version"] != (
        finals_config.PROACTIVE_SCHEMA_VERSION):
      raise ReplayConfigurationError(
          "Stage-1 replay requires capd_proactive_v1_0.")
    if stage0_config["method"]["selector"] != "disabled":
      raise ReplayConfigurationError(
          "Stage-1 replay refuses an enabled candidate selector.")
    if stage0_config["scope"]["page_enter_dram_semantics"] != (
        "occupies_one_free_frame_regardless_of_source"):
      raise ReplayConfigurationError(
          "Unexpected page_enter_dram semantics.")
    if not isinstance(parameters, ReplayParameters):
      raise ReplayConfigurationError(
          "parameters must be ReplayParameters.")
    if invariant_mode not in ("full", "boundary"):
      raise ReplayConfigurationError(
          "invariant_mode must be full or boundary.")

    self.stage0_contract = finals_config.proactive_contract_from_config(
        stage0_config)
    self.stage0_config_fingerprint = finals_config.config_fingerprint(
        stage0_config)
    self.parameters = parameters
    self.invariant_mode = invariant_mode
    self.record_details = bool(record_details)
    self.capture_page_enter_flags = bool(capture_page_enter_flags)
    self.measure_decision_latency = bool(measure_decision_latency)
    self.exclude_current_entering_page = bool(
        exclude_current_entering_page)
    self._current_entering_page = None
    self.is_reactive = parameters.policy_name == "reactive_lru"
    if self.is_reactive:
      if ranking_policy is not None:
        raise ReplayConfigurationError(
            "Reactive-LRU must not install a proactive ranker.")
      self.ranking_policy = None
    else:
      if ranking_policy is None:
        if parameters.policy_name != "proactive_lru":
          raise ReplayConfigurationError(
              "{} requires an explicit stage-1 ranker; Replay will not "
              "pretend that LRU is CAPD/CLOCK/TPP/Oracle.".format(
                  parameters.policy_name))
        ranking_policy = ProactiveLRURanking()
      self.ranking_policy = ranking_policy

    self.dram_lru = _LRUOrder()
    self.dram_resident = set()
    self.nvm_resident = set()
    self.residency_state = {}
    self.frequency_state = {}
    self.dirty_state = {}
    self.last_access_index = {}
    self.dram_entry_index = {}
    self.history_window = collections.deque(
        maxlen=parameters.history_window_size)
    self.active_proactive_cycle = None
    self.access_index = -1

    self.event_logs = []
    self.round_logs = []
    self.cycle_logs = []
    self.access_logs = []
    self._event_id = 0
    self._decision_id = 0
    self._cycle_id = 0
    self._round_id = 0
    self._round_count = 0
    self._cycle_count = 0
    self._b_t_sum = 0
    self._decision_latencies = []
    self._candidate_count_min = None
    self._candidate_count_max = None
    self._candidate_counts_by_round = array.array("I")
    self._free_frame_sample_count = 0
    self._free_frame_sample_sum = 0
    self._full_invariant_checks = 0
    self.page_enter_flags = []
    self._minimum_free_frames = parameters.dram_capacity_pages
    self._last_observed_free_frames = parameters.dram_capacity_pages
    self._proactively_demoted_at = {}

    self.counters = {
        "total_accesses": 0,
        "dram_hits": 0,
        "nvm_reads": 0,
        "nvm_writes": 0,
        "page_enter_dram_count": 0,
        "total_demotions": 0,
        "proactive_demotions": 0,
        "reactive_demotions": 0,
        "emergency_demotions": 0,
        "dirty_demotions": 0,
        "free_frame_exhaustion_count": 0,
        "accesses_below_F_low": 0,
        "early_reuse_count": 0,
    }
    self.assert_invariants()

  @property
  def free_frames(self):
    return self.parameters.dram_capacity_pages - len(self.dram_resident)

  def _observe_free_frames(self, access_sample=False):
    current = self.free_frames
    self._minimum_free_frames = min(self._minimum_free_frames, current)
    if current == 0 and self._last_observed_free_frames > 0:
      self.counters["free_frame_exhaustion_count"] += 1
    self._last_observed_free_frames = current
    if access_sample:
      self._free_frame_sample_count += 1
      self._free_frame_sample_sum += current

  def assert_invariants(self, candidates=None, selected=None, b_t=None,
                        F_before=None, force_full=False):
    capacity = self.parameters.dram_capacity_pages
    if self.free_frames != capacity - len(self.dram_resident):
      raise ReplayInvariantError("F_t/DRAM resident conservation failed.")
    if not (0 <= self.free_frames <= capacity):
      raise ReplayInvariantError("F_t lies outside [0, DRAM capacity].")
    if len(self.dram_lru) != len(self.dram_resident):
      raise ReplayInvariantError("LRU/DRAM resident count differs.")
    if force_full or self.invariant_mode == "full":
      self._full_invariant_checks += 1
      if self.dram_resident & self.nvm_resident:
        raise ReplayInvariantError("DRAM and NVM resident sets overlap.")
      if len(self.dram_lru) != len(set(self.dram_lru)):
        raise ReplayInvariantError("LRU contains duplicate pages.")
      if set(self.dram_lru) != self.dram_resident:
        raise ReplayInvariantError("LRU contains a non-DRAM or missing page.")
      for page, location in self.residency_state.items():
        in_dram = page in self.dram_resident
        in_nvm = page in self.nvm_resident
        if in_dram == in_nvm:
          raise ReplayInvariantError(
              "Resident page {} does not have a unique location.".format(page))
        if location != ("dram" if in_dram else "nvm"):
          raise ReplayInvariantError(
              "residency_state disagrees for page {}.".format(page))
    if selected is not None:
      candidates = list(candidates or ())
      selected = list(selected)
      if not set(selected).issubset(set(candidates)):
        raise ReplayInvariantError(
            "Selected pages must come from the current candidate set.")
      if len(selected) != len(set(selected)):
        raise ReplayInvariantError("Selected pages contain duplicates.")
      if b_t != len(selected):
        raise ReplayInvariantError("b_t does not match selected page count.")
      if b_t > len(candidates):
        raise ReplayInvariantError("b_t exceeds candidate count.")
      if b_t > self.parameters.b_max:
        raise ReplayInvariantError("b_t exceeds b_max.")
      if F_before is None:
        raise ReplayInvariantError("F_before is required for Top-b checks.")
      if b_t > self.parameters.F_target - F_before:
        raise ReplayInvariantError("b_t exceeds the target-watermark gap.")
    return True

  def register_backing_pages(self, pages):
    for raw_page in pages:
      page = int(raw_page)
      if page not in self.residency_state:
        self.nvm_resident.add(page)
        self.residency_state[page] = "nvm"
        self.dirty_state[page] = False
    self.assert_invariants()

  def _touch_mru(self, page):
    if page not in self.dram_resident:
      raise ReplayInvariantError("Cannot touch non-DRAM page as MRU.")
    self.dram_lru.remove(page)
    self.dram_lru.insert(0, page)

  def _record_early_reuse(self, page):
    demoted_at = self._proactively_demoted_at.pop(page, None)
    if demoted_at is None:
      return
    distance = self.access_index - demoted_at
    if 0 < distance <= self.parameters.early_reuse_window:
      self.counters["early_reuse_count"] += 1

  def _page_demote_from_dram(
      self, page, event_type, cycle_id=None, round_id=None):
    if event_type not in DEMOTION_EVENT_TYPES:
      raise ReplayInvariantError(
          "Unknown demotion event type: {}.".format(event_type))
    if page not in self.dram_resident:
      raise ReplayInvariantError(
          "Cannot demote non-DRAM page {}.".format(page))
    F_before = self.free_frames
    dirty_before = bool(self.dirty_state.get(page, False))
    self.dram_lru.remove(page)
    self.dram_resident.remove(page)
    self.nvm_resident.add(page)
    self.residency_state[page] = "nvm"
    self.dirty_state[page] = False
    self.dram_entry_index.pop(page, None)
    if self.ranking_policy is not None:
      self.ranking_policy.on_page_demoted(self, page, event_type)
    self._event_id += 1
    event = None
    if self.record_details:
      event = {
          "schema_version": STAGE1_LOG_SCHEMA_VERSION,
          "event_id": self._event_id,
          "event_type": event_type,
          "access_index": self.access_index,
          "page": page,
          "policy_name": self.parameters.policy_name,
          "ranking_policy": (
              None if self.ranking_policy is None
              else self.ranking_policy.policy_name),
          "cycle_id": cycle_id,
          "round_id": round_id,
          "F_before": F_before,
          "F_after": self.free_frames,
          "dirty_before": dirty_before,
      }
      self.event_logs.append(event)
    self.counters["total_demotions"] += 1
    counter = {
        PROACTIVE_DEMOTION: "proactive_demotions",
        REACTIVE_DEMOTION: "reactive_demotions",
        EMERGENCY_DEMOTION: "emergency_demotions",
    }[event_type]
    self.counters[counter] += 1
    if dirty_before:
      self.counters["dirty_demotions"] += 1
    if event_type == PROACTIVE_DEMOTION:
      self._proactively_demoted_at[page] = self.access_index
    self._observe_free_frames()
    self.assert_invariants()
    return event

  def _page_enter_dram(self, page):
    if self.free_frames <= 0:
      raise ReplayInvariantError(
          "page_enter_dram requires a free frame before entry.")
    if page in self.dram_resident:
      raise ReplayInvariantError(
          "page_enter_dram received a DRAM-resident page.")
    self.nvm_resident.discard(page)
    self.dram_resident.add(page)
    self.dram_lru.insert(0, page)
    self.residency_state[page] = "dram"
    self.dirty_state.setdefault(page, False)
    self.dram_entry_index[page] = self.access_index
    if self.ranking_policy is not None:
      self.ranking_policy.on_page_enter_dram(self, page)
    self.counters["page_enter_dram_count"] += 1
    self._observe_free_frames()
    self.assert_invariants()

  def build_candidates(self):
    """Builds the current actual LRU-tail candidate set without padding."""
    if self.is_reactive:
      return []
    scan_count = (
        len(self.dram_lru) if self.exclude_current_entering_page
        else self.parameters.candidate_size_K)
    oldest_first = self.dram_lru.tail_oldest_first(scan_count)
    eligible = [
        page for page in oldest_first
        if page not in self.parameters.non_demotable_pages and
        page != self._current_entering_page
    ]
    return eligible[:self.parameters.candidate_size_K]

  def _candidate_features(self, candidates):
    history_pages = [item["page"] for item in self.history_window]
    features = []
    for lru_tail_rank, page in enumerate(candidates):
      features.append({
          "page": page,
          "lru_tail_rank": lru_tail_rank,
          "frequency": self.frequency_state.get(page, 0),
          "dirty": bool(self.dirty_state.get(page, False)),
          "residency": self.residency_state.get(page),
          "last_access_index": self.last_access_index.get(page),
          "dram_entry_index": self.dram_entry_index.get(page),
          "history_occurrences": history_pages.count(page),
      })
    return features

  def _validate_ranking(self, candidates, ranking):
    if not isinstance(ranking, list):
      raise ReplayInvariantError("Ranking policy must return a list.")
    if any(not isinstance(item, dict) or
           set(("page", "score")) - set(item) for item in ranking):
      raise ReplayInvariantError(
          "Every ranking item must define page and score.")
    ranked_pages = [item["page"] for item in ranking]
    if len(ranked_pages) != len(set(ranked_pages)):
      raise ReplayInvariantError("Ranking contains duplicate pages.")
    if set(ranked_pages) != set(candidates):
      raise ReplayInvariantError(
          "Ranking must contain exactly the current candidates.")

  def _round_log(
      self, cycle_id, cycle_round_index, candidates, candidate_features,
      ranking, selected, F_before, termination_reason, timings=None,
      candidate_state_sha256=None):
    self._decision_id += 1
    self._round_id += 1
    self._round_count += 1
    self._b_t_sum += len(selected)
    candidate_count = len(candidates)
    self._candidate_counts_by_round.append(candidate_count)
    self._candidate_count_min = (
        candidate_count if self._candidate_count_min is None
        else min(self._candidate_count_min, candidate_count))
    self._candidate_count_max = (
        candidate_count if self._candidate_count_max is None
        else max(self._candidate_count_max, candidate_count))
    if not self.record_details:
      return {
          "round_id": self._round_id,
          "b_t": len(selected),
          "migration_count": len(selected),
      }
    timings = timings or {}
    log = {
        "schema_version": STAGE1_LOG_SCHEMA_VERSION,
        "decision_id": self._decision_id,
        "cycle_id": cycle_id,
        "round_id": self._round_id,
        "cycle_round_index": cycle_round_index,
        "access_index": self.access_index,
        "policy_name": self.parameters.policy_name,
        "ranking_policy": self.ranking_policy.policy_name,
        "F_before": F_before,
        "F_low": self.parameters.F_low,
        "F_target": self.parameters.F_target,
        "candidate_pages": list(candidates),
        "candidate_pages_sha256": finals_config.fingerprint_value(
            list(candidates)),
        "candidate_state_sha256": candidate_state_sha256,
        "candidate_features": copy.deepcopy(candidate_features),
        "policy_scores": copy.deepcopy(ranking),
        "selected_pages": list(selected),
        "b_t": len(selected),
        "F_after": self.free_frames,
        "feature_latency": timings.get("feature_latency"),
        "inference_latency": timings.get("inference_latency"),
        "selection_latency": timings.get("selection_latency"),
        "migration_count": len(selected),
        "termination_reason": termination_reason,
    }
    missing = set(ROUND_REQUIRED_FIELDS) - set(log)
    if missing:
      raise ReplayInvariantError(
          "Round log missing fields: {}.".format(sorted(missing)))
    self.round_logs.append(log)
    return log

  def _run_proactive_cycle(
      self, force_after_emergency=False,
      emergency_fallback_occurred=False):
    if self.is_reactive:
      raise ReplayInvariantError(
          "Reactive-LRU cannot create a proactive cycle.")
    if self.active_proactive_cycle is not None:
      raise ReplayInvariantError("A proactive cycle is already active.")
    should_start = (
        0 < self.free_frames < self.parameters.F_low or
        (force_after_emergency and
         self.free_frames < self.parameters.F_target))
    if not should_start:
      return None

    self._cycle_id += 1
    cycle_id = self._cycle_id
    cycle_start_F = self.free_frames
    cycle_minimum_F = self.free_frames
    cycle_start_round_count = self._round_count
    cycle_start_demotions = self.counters["proactive_demotions"]
    self.active_proactive_cycle = {
        "cycle_id": cycle_id,
        "start_access": self.access_index,
    }
    termination_reason = None
    maximum_rounds = self.parameters.dram_capacity_pages + 1
    cycle_round_index = 0

    while self.free_frames < self.parameters.F_target:
      cycle_round_index += 1
      if cycle_round_index > maximum_rounds:
        termination_reason = "max_rounds_exceeded"
        break
      F_before = self.free_frames
      candidates = self.build_candidates()
      candidate_state_sha256 = finals_config.fingerprint_value({
          "access_index": self.access_index,
          "F_t": F_before,
          "dram_lru_mru_to_lru": list(self.dram_lru),
          "dram_resident": sorted(self.dram_resident),
          "excluded_current_entering_page": self._current_entering_page,
      })
      feature_started = (
          time.perf_counter() if self.measure_decision_latency else None)
      candidate_features = self._candidate_features(candidates)
      feature_latency = (
          time.perf_counter() - feature_started
          if feature_started is not None else None)
      inference_started = (
          time.perf_counter() if self.measure_decision_latency else None)
      ranking = self.ranking_policy.rank_candidates(
          self, candidates, candidate_features, {
              "cycle_id": cycle_id,
              "cycle_round_index": cycle_round_index,
              "access_index": self.access_index,
          })
      inference_latency = (
          time.perf_counter() - inference_started
          if inference_started is not None else None)
      self._validate_ranking(candidates, ranking)
      b_t = min(
          self.parameters.b_max,
          self.parameters.F_target - F_before,
          len(candidates),
      )
      if not candidates:
        termination_reason = "candidate_set_empty"
        self._round_log(
            cycle_id, cycle_round_index, candidates, candidate_features,
            ranking, [], F_before, termination_reason, {
                "feature_latency": feature_latency,
                "inference_latency": inference_latency,
                "selection_latency": 0.0
                if self.measure_decision_latency else None,
            }, candidate_state_sha256)
        break
      if b_t <= 0:
        termination_reason = "b_t_zero"
        self._round_log(
            cycle_id, cycle_round_index, candidates, candidate_features,
            ranking, [], F_before, termination_reason, {
                "feature_latency": feature_latency,
                "inference_latency": inference_latency,
                "selection_latency": 0.0
                if self.measure_decision_latency else None,
            }, candidate_state_sha256)
        break

      selection_started = (
          time.perf_counter() if self.measure_decision_latency else None)
      selected = select_top_b(ranking, b_t)
      selection_latency = (
          time.perf_counter() - selection_started
          if selection_started is not None else None)
      self.assert_invariants(
          candidates=candidates, selected=selected, b_t=b_t,
          F_before=F_before)
      round_id = self._round_id + 1
      for page in selected:
        self._page_demote_from_dram(
            page, PROACTIVE_DEMOTION,
            cycle_id=cycle_id, round_id=round_id)
      cycle_minimum_F = min(cycle_minimum_F, self.free_frames)
      if self.free_frames <= F_before:
        termination_reason = "no_state_progress"
      elif self.free_frames >= self.parameters.F_target:
        termination_reason = "target_reached"
      else:
        termination_reason = "continue_rebuild_candidates"
      self._round_log(
          cycle_id, cycle_round_index, candidates, candidate_features,
          ranking, selected, F_before, termination_reason, {
              "feature_latency": feature_latency,
              "inference_latency": inference_latency,
              "selection_latency": selection_latency,
          }, candidate_state_sha256)
      if self.measure_decision_latency:
        self._decision_latencies.append(
            feature_latency + inference_latency + selection_latency)
      if termination_reason != "continue_rebuild_candidates":
        break

    if termination_reason is None:
      termination_reason = "target_already_reached"
    rounds = self._round_count - cycle_start_round_count
    pages_demoted = (
        self.counters["proactive_demotions"] - cycle_start_demotions)
    cycle_log = {
        "schema_version": STAGE1_LOG_SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "start_access": self.access_index,
        "end_access": self.access_index,
        "start_F": cycle_start_F,
        "target_F": self.parameters.F_target,
        "number_of_rounds": rounds,
        "number_of_pages_demoted": pages_demoted,
        "minimum_F": cycle_minimum_F,
        "total_feature_time": (
            sum(row["feature_latency"] for row in self.round_logs[
                cycle_start_round_count:] if row["feature_latency"] is not None)
            if self.measure_decision_latency and self.record_details else None),
        "total_inference_time": (
            sum(row["inference_latency"] for row in self.round_logs[
                cycle_start_round_count:] if row["inference_latency"] is not None)
            if self.measure_decision_latency and self.record_details else None),
        "total_selection_time": (
            sum(row["selection_latency"] for row in self.round_logs[
                cycle_start_round_count:] if row["selection_latency"] is not None)
            if self.measure_decision_latency and self.record_details else None),
        "emergency_fallback_occurred": bool(
            emergency_fallback_occurred),
        "termination_reason": termination_reason,
    }
    missing = set(CYCLE_REQUIRED_FIELDS) - set(cycle_log)
    if missing:
      raise ReplayInvariantError(
          "Cycle log missing fields: {}.".format(sorted(missing)))
    self._cycle_count += 1
    if self.record_details:
      self.cycle_logs.append(cycle_log)
    self.active_proactive_cycle = None
    self.assert_invariants()
    return cycle_log

  @staticmethod
  def _access_values(access):
    if isinstance(access, dict):
      _require_keys(access, ("page", "rw"), "trace access")
      return int(access["page"]), int(access["rw"]), access.get("pc")
    if isinstance(access, (tuple, list)) and len(access) in (2, 3):
      return (
          int(access[0]), int(access[1]),
          None if len(access) == 2 else access[2])
    raise ReplayConfigurationError(
        "Trace access must be a mapping or (page,rw[,pc]) tuple.")

  def process_access(self, access):
    page, rw, pc = self._access_values(access)
    if rw not in (0, 1):
      raise ReplayConfigurationError("Trace rw must be 0 or 1.")

    self.access_index += 1
    self.counters["total_accesses"] += 1
    self.register_backing_pages([page])
    location_before = self.residency_state[page]
    F_before_access = self.free_frames
    event_start = len(self.event_logs)
    emergency_occurred = False
    entered_dram = False

    self._record_early_reuse(page)
    if page in self.dram_resident:
      self.counters["dram_hits"] += 1
      self._touch_mru(page)
    else:
      if rw == 0:
        self.counters["nvm_reads"] += 1
      else:
        self.counters["nvm_writes"] += 1
      if self.free_frames == 0:
        if not self.dram_lru:
          raise ReplayInvariantError(
              "No free frame and no LRU page for fallback.")
        victim = self.dram_lru[-1]
        event_type = (
            REACTIVE_DEMOTION if self.is_reactive
            else EMERGENCY_DEMOTION)
        self._page_demote_from_dram(victim, event_type)
        emergency_occurred = not self.is_reactive
      F_before_page_enter = self.free_frames
      self._page_enter_dram(page)
      entered_dram = True
      if self.free_frames != F_before_page_enter - 1:
        raise ReplayInvariantError(
            "page_enter_dram must consume exactly one free frame.")

    self.frequency_state[page] = self.frequency_state.get(page, 0) + 1
    self.last_access_index[page] = self.access_index
    if rw == 1:
      self.dirty_state[page] = True
    if self.ranking_policy is not None:
      self.ranking_policy.on_page_access(self, page, rw)
    self.history_window.append({
        "page": page,
        "rw": rw,
        "pc": pc,
    })
    self.assert_invariants()

    F_before_watermark = self.free_frames
    if not self.is_reactive:
      if self.free_frames < self.parameters.F_low:
        self.counters["accesses_below_F_low"] += 1
      self._current_entering_page = (
          page if entered_dram and self.exclude_current_entering_page
          else None)
      self._run_proactive_cycle(
          force_after_emergency=emergency_occurred,
          emergency_fallback_occurred=emergency_occurred)
      self._current_entering_page = None
    self._observe_free_frames(access_sample=True)

    if self.capture_page_enter_flags:
      self.page_enter_flags.append(entered_dram)
    new_events = self.event_logs[event_start:] if self.record_details else []
    access_log = {
        "schema_version": STAGE1_LOG_SCHEMA_VERSION,
        "access_index": self.access_index,
        "page": page,
        "rw": rw,
        "location_before": location_before,
        "page_entered_dram": entered_dram,
        "F_before_access": F_before_access,
        "F_before_watermark_check": F_before_watermark,
        "F_after_access": self.free_frames,
        "demotion_event_ids": [event["event_id"] for event in new_events],
        "demotion_event_types": [
            event["event_type"] for event in new_events],
        "emergency_fallback_occurred": emergency_occurred,
    }
    if self.record_details:
      self.access_logs.append(access_log)
    self.assert_invariants()
    return access_log

  def run(self, trace, copy_trace=True, compact=False):
    if copy_trace:
      trace = [copy.deepcopy(access) for access in trace]
    self.register_backing_pages(
        self._access_values(access)[0] for access in trace)
    for access in trace:
      self.process_access(access)
    return self.compact_result() if compact else self.result()

  def summary(self):
    round_count = self._round_count
    cycle_count = self._cycle_count
    summary = {
        "schema_version": STAGE1_LOG_SCHEMA_VERSION,
        "policy_name": self.parameters.policy_name,
        "ranking_policy": (
            None if self.ranking_policy is None
            else self.ranking_policy.policy_name),
        "total_accesses": self.counters["total_accesses"],
        "dram_hits": self.counters["dram_hits"],
        "nvm_reads": self.counters["nvm_reads"],
        "nvm_writes": self.counters["nvm_writes"],
        "page_enter_dram_count": self.counters["page_enter_dram_count"],
        "total_demotions": self.counters["total_demotions"],
        "proactive_demotions": self.counters["proactive_demotions"],
        "reactive_demotions": self.counters["reactive_demotions"],
        "emergency_demotions": self.counters["emergency_demotions"],
        "dirty_demotions": self.counters["dirty_demotions"],
        "number_of_proactive_cycles": cycle_count,
        "number_of_proactive_rounds": round_count,
        "mean_b_t": (
            self._b_t_sum / float(round_count) if round_count else None),
        "rounds_per_cycle": (
            round_count / float(cycle_count) if cycle_count else None),
        "minimum_free_frames": self._minimum_free_frames,
        "average_free_frames": (
            self._free_frame_sample_sum /
            float(self._free_frame_sample_count)
            if self._free_frame_sample_count else None),
        "free_frame_exhaustion_count":
            self.counters["free_frame_exhaustion_count"],
        "accesses_below_F_low": self.counters["accesses_below_F_low"],
        "early_reuse_count": self.counters["early_reuse_count"],
        "decision_count": round_count,
        "total_decision_time": None,
        "decision_time_status": "not_measured_stage1",
        "weighted_cost": None,
        "weighted_cost_status": "pending_stage2",
        "selector_status": "disabled",
        "checkpoint_status": "not_required_stage1",
    }
    missing = set(SUMMARY_REQUIRED_FIELDS) - set(summary)
    if missing:
      raise ReplayInvariantError(
          "Summary missing fields: {}.".format(sorted(missing)))
    return summary

  def validate_log_accounting(self):
    summary = self.summary()
    if not self.record_details:
      if summary["total_accesses"] != (
          summary["dram_hits"] + summary["nvm_reads"] +
          summary["nvm_writes"]):
        raise ReplayInvariantError("Compact access accounting mismatch.")
      if summary["page_enter_dram_count"] != (
          summary["nvm_reads"] + summary["nvm_writes"]):
        raise ReplayInvariantError("Compact page-enter accounting mismatch.")
      if summary["total_demotions"] != (
          summary["proactive_demotions"] +
          summary["reactive_demotions"] +
          summary["emergency_demotions"]):
        raise ReplayInvariantError("Compact demotion accounting mismatch.")
      return True
    event_counts = collections.Counter(
        event["event_type"] for event in self.event_logs)
    expected = {
        "proactive_demotions": event_counts[PROACTIVE_DEMOTION],
        "reactive_demotions": event_counts[REACTIVE_DEMOTION],
        "emergency_demotions": event_counts[EMERGENCY_DEMOTION],
        "total_demotions": len(self.event_logs),
        "number_of_proactive_cycles": len(self.cycle_logs),
        "number_of_proactive_rounds": len(self.round_logs),
        "decision_count": len(self.round_logs),
    }
    mismatches = {
        key: (value, summary[key])
        for key, value in expected.items()
        if summary[key] != value
    }
    if summary["total_accesses"] != (
        summary["dram_hits"] +
        summary["nvm_reads"] +
        summary["nvm_writes"]):
      mismatches["access_accounting"] = (
          summary["total_accesses"],
          summary["dram_hits"] +
          summary["nvm_reads"] +
          summary["nvm_writes"])
    if summary["page_enter_dram_count"] != (
        summary["nvm_reads"] + summary["nvm_writes"]):
      mismatches["page_enter_accounting"] = (
          summary["page_enter_dram_count"],
          summary["nvm_reads"] + summary["nvm_writes"])
    if sum(log["migration_count"] for log in self.round_logs) != (
        summary["proactive_demotions"]):
      mismatches["round_migration_accounting"] = (
          sum(log["migration_count"] for log in self.round_logs),
          summary["proactive_demotions"])
    if mismatches:
      raise ReplayInvariantError(
          "Summary/log accounting mismatch: {}.".format(mismatches))
    return True

  def state_snapshot(self):
    return {
        "dram_capacity_pages": self.parameters.dram_capacity_pages,
        "F_t": self.free_frames,
        "dram_resident": sorted(self.dram_resident),
        "nvm_resident": sorted(self.nvm_resident),
        "dram_lru_mru_to_lru": list(self.dram_lru),
        "frequency_state": {
            str(page): self.frequency_state[page]
            for page in sorted(self.frequency_state)
        },
        "dirty_state": {
            str(page): bool(self.dirty_state[page])
            for page in sorted(self.dirty_state)
        },
        "residency_state": {
            str(page): self.residency_state[page]
            for page in sorted(self.residency_state)
        },
        "history_window": list(self.history_window),
        "active_proactive_cycle": copy.deepcopy(
            self.active_proactive_cycle),
        "access_index": self.access_index,
        "decision_counter": self._decision_id,
        "cycle_counter": self._cycle_id,
        "round_counter": self._round_id,
        "raw_event_counters": copy.deepcopy(self.counters),
    }

  def result(self):
    self.assert_invariants(force_full=True)
    self.validate_log_accounting()
    return {
        "schema_version": STAGE1_RESULT_SCHEMA_VERSION,
        "stage0_config_fingerprint": self.stage0_config_fingerprint,
        "stage0_contract": copy.deepcopy(self.stage0_contract),
        "fixture_parameters": self.parameters.to_dict(),
        "state": self.state_snapshot(),
        "events": copy.deepcopy(self.event_logs),
        "rounds": copy.deepcopy(self.round_logs),
        "cycles": copy.deepcopy(self.cycle_logs),
        "accesses": copy.deepcopy(self.access_logs),
        "summary": self.summary(),
    }

  def compact_result(self):
    """Returns only the aggregates Stage 3 needs after a final full audit."""
    self.assert_invariants(force_full=True)
    self.validate_log_accounting()
    return {
        "schema_version": STAGE1_RESULT_SCHEMA_VERSION,
        "summary": self.summary(),
        "actual_candidate_round_count": self._round_count,
        "actual_candidate_counts_by_round": list(
            self._candidate_counts_by_round),
        "actual_candidate_count_min": self._candidate_count_min,
        "actual_candidate_count_max": self._candidate_count_max,
        "page_enter_flags": list(self.page_enter_flags),
        "full_invariant_checks": self._full_invariant_checks,
    }


def validate_stage1_fixture(fixture, stage0_config):
  """Validates a synthetic fixture without consuming later-stage parameters."""
  required = (
      "schema_version",
      "fixture_status",
      "base_config_schema_version",
      "base_contract_id",
      "scenarios",
  )
  _require_keys(fixture, required, "stage1 fixture")
  if fixture["schema_version"] != STAGE1_FIXTURE_SCHEMA_VERSION:
    raise ReplayConfigurationError(
        "Unsupported stage-1 fixture schema.")
  if fixture["fixture_status"] != "non_formal_synthetic_only":
    raise ReplayConfigurationError(
        "Stage-1 values must be marked non_formal_synthetic_only.")
  if fixture["base_config_schema_version"] != (
      finals_config.PROACTIVE_SCHEMA_VERSION):
    raise ReplayConfigurationError(
        "Fixture base schema does not match capd_proactive_v1_0.")
  if fixture["base_contract_id"] != finals_config.PROACTIVE_CONTRACT_ID:
    raise ReplayConfigurationError("Fixture base contract id mismatch.")
  finals_config.validate_config(stage0_config)
  # Stage 1 emits raw counters and a pending Cost placeholder.  The enclosing
  # shared configuration may subsequently freeze stage 2 without changing
  # Replay behavior or the synthetic fixture.
  if stage0_config["method"]["selector"] != "disabled":
    raise ReplayConfigurationError("Selector must remain disabled.")
  if not isinstance(fixture["scenarios"], list) or not fixture["scenarios"]:
    raise ReplayConfigurationError(
        "Stage-1 fixture requires at least one scenario.")

  scenario_names = set()
  for index, scenario in enumerate(fixture["scenarios"]):
    context = "scenarios[{}]".format(index)
    _require_keys(
        scenario,
        ("name", "policy_name", "ranking", "replay_parameters", "trace"),
        context)
    name = scenario["name"]
    if not isinstance(name, str) or not name.strip():
      raise ReplayConfigurationError(
          "{}.name must be non-empty.".format(context))
    if name in scenario_names:
      raise ReplayConfigurationError(
          "Duplicate fixture scenario name: {}.".format(name))
    scenario_names.add(name)
    ReplayParameters.from_fixture(
        scenario["policy_name"], scenario["replay_parameters"])
    if scenario["policy_name"] not in ("reactive_lru", "proactive_lru"):
      raise ReplayConfigurationError(
          "Stage-1 synthetic fixtures implement only Reactive-LRU and "
          "Proactive-LRU control paths; found {}.".format(
              scenario["policy_name"]))
    if not isinstance(scenario["trace"], list) or not scenario["trace"]:
      raise ReplayConfigurationError(
          "{}.trace must be non-empty.".format(context))
    for access in scenario["trace"]:
      _require_keys(access, ("page", "rw"), "{} trace access".format(
          context))
    ranking = scenario["ranking"]
    _require_keys(ranking, ("type",), "{}.ranking".format(context))
    if scenario["policy_name"] == "reactive_lru":
      if ranking["type"] != "not_applicable":
        raise ReplayConfigurationError(
            "Reactive-LRU ranking must be not_applicable.")
    elif ranking["type"] not in (
        "proactive_lru", "deterministic_stub"):
      raise ReplayConfigurationError(
          "Unsupported fixture ranking type: {}.".format(ranking["type"]))
  return fixture


def _ranking_from_fixture(scenario):
  ranking = scenario["ranking"]
  if ranking["type"] == "not_applicable":
    return None
  if ranking["type"] == "proactive_lru":
    return ProactiveLRURanking()
  if ranking["type"] == "deterministic_stub":
    return DeterministicStubRanking(ranking.get("scores", {}))
  raise ReplayConfigurationError(
      "Unknown ranking fixture type: {}.".format(ranking["type"]))


def run_fixture_scenarios(stage0_config, fixture):
  validate_stage1_fixture(fixture, stage0_config)
  results = {}
  for scenario in fixture["scenarios"]:
    parameters = ReplayParameters.from_fixture(
        scenario["policy_name"], scenario["replay_parameters"])
    replay = ProactiveReplay(
        stage0_config, parameters,
        ranking_policy=_ranking_from_fixture(scenario))
    results[scenario["name"]] = replay.run(scenario["trace"])
  return results


def _git_state(project_root):
  try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root,
        stderr=subprocess.STDOUT, universal_newlines=True).strip()
    dirty_override = os.environ.get("CAPD_DIRTY_WORKTREE")
    if dirty_override in ("true", "false"):
      status = (
          "explicit-dirty-worktree-override\n"
          if dirty_override == "true" else "")
      diff = status.encode("utf-8")
    else:
      status = subprocess.check_output(
          ["git", "status", "--porcelain=v1"], cwd=project_root,
          stderr=subprocess.STDOUT, universal_newlines=True)
      diff = subprocess.check_output(
          ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
          cwd=project_root, stderr=subprocess.STDOUT)
  except (OSError, subprocess.CalledProcessError):
    return "unknown", None, None
  dirty = bool(status.strip())
  fingerprint = None
  if dirty:
    fingerprint = finals_config.fingerprint_value({
        "status": status,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
    })
  return commit, dirty, fingerprint


def _memory_bytes():
  try:
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_count = os.sysconf("SC_PHYS_PAGES")
    return int(page_size) * int(page_count)
  except (AttributeError, OSError, ValueError):
    return "unknown"


def _machine_information():
  return {
      "hostname": platform.node() or "unknown",
      "operating_system": platform.platform() or "unknown",
      "architecture": platform.machine() or "unknown",
      "cpu_model": platform.processor() or "unknown",
      "logical_cpu_count": os.cpu_count() or "unknown",
      "memory_bytes": _memory_bytes(),
      "runtime": "python",
      "runtime_version": platform.python_version(),
  }


def write_fixture_outputs(
    project_root, stage0_config, fixture, results, output_root, command):
  """Writes the stage-0 minimum layout for a non-formal stage-1 trial."""
  fixture_fingerprint = finals_config.fingerprint_value(fixture)
  timestamp = _utc_now()
  run_id = "{}__stage1_fixture__synthetic__seed-na__{}".format(
      timestamp.replace("-", "").replace(":", ""),
      fixture_fingerprint[:12])
  run_directory = os.path.abspath(os.path.join(
      output_root, "stage1", run_id))
  artifacts_directory = os.path.join(run_directory, "artifacts")
  logs_directory = os.path.join(run_directory, "logs")
  os.makedirs(artifacts_directory, exist_ok=False)
  os.makedirs(logs_directory, exist_ok=True)

  commit, dirty, dirty_fingerprint = _git_state(project_root)
  resolved = copy.deepcopy(stage0_config)
  resolved["experiment_stage"] = "stage1"
  resolved["stage1_fixture"] = {
      "schema_version": fixture["schema_version"],
      "fixture_status": fixture["fixture_status"],
      "fixture_fingerprint": fixture_fingerprint,
      "scenarios": copy.deepcopy(fixture["scenarios"]),
  }
  resolved["run"].update({
      "run_id": run_id,
      "output_directory": run_directory,
      "created_at": timestamp,
      "resolved_config_fingerprint": None,
      "code_commit": commit,
      "dirty_worktree": dirty,
      "machine_information": _machine_information(),
      "command": list(command),
  })
  resolved["run"]["resolved_config_fingerprint"] = (
      finals_config.config_fingerprint(resolved))
  resolved_path = os.path.join(
      run_directory, finals_config.PROACTIVE_RESOLVED_CONFIG_FILENAME)
  _write_json(resolved_path, resolved)

  output_artifacts = []
  for scenario_name, result in sorted(results.items()):
    safe = _safe_name(scenario_name)
    paths = {
        "result": os.path.join(artifacts_directory, safe + "_result.json"),
        "summary": os.path.join(logs_directory, safe + "_summary.json"),
        "events": os.path.join(logs_directory, safe + "_events.jsonl"),
        "rounds": os.path.join(logs_directory, safe + "_rounds.jsonl"),
        "cycles": os.path.join(logs_directory, safe + "_cycles.jsonl"),
        "accesses": os.path.join(logs_directory, safe + "_accesses.jsonl"),
    }
    _write_json(paths["result"], {
        key: value for key, value in result.items()
        if key not in ("events", "rounds", "cycles", "accesses")
    })
    _write_json(paths["summary"], result["summary"])
    _write_jsonl(paths["events"], result["events"])
    _write_jsonl(paths["rounds"], result["rounds"])
    _write_jsonl(paths["cycles"], result["cycles"])
    _write_jsonl(paths["accesses"], result["accesses"])
    output_artifacts.extend(
        os.path.relpath(path, run_directory).replace(os.sep, "/")
        for path in paths.values())

  provenance = {
      "schema_version":
          finals_config.PROACTIVE_PROVENANCE_SCHEMA_VERSION,
      "config_schema_version": stage0_config["schema_version"],
      "config_version": stage0_config["config_version"],
      "contract_id": stage0_config["contract"]["id"],
      "run_id": run_id,
      "created_at": timestamp,
      "resolved_config_filename":
          finals_config.PROACTIVE_RESOLVED_CONFIG_FILENAME,
      "resolved_config_fingerprint":
          resolved["run"]["resolved_config_fingerprint"],
      "code_commit": commit,
      "dirty_worktree": dirty,
      "dirty_diff_fingerprint": dirty_fingerprint,
      "machine_information": resolved["run"]["machine_information"],
      "command": list(command),
      "model_checkpoint": {
          "status": "not_required_stage1",
          "path": None,
          "fingerprint": None,
      },
      "input_artifacts": [
          {
              "role": "stage0_config",
              "fingerprint":
                  finals_config.config_fingerprint(stage0_config),
          },
          {
              "role": "stage1_fixture",
              "fingerprint": fixture_fingerprint,
          },
      ],
      "output_artifacts": sorted(output_artifacts),
      "status": STAGE1_PROVENANCE_STATUS,
  }
  missing_provenance = (
      set(finals_config.PROACTIVE_PROVENANCE_REQUIRED_FIELDS) -
      set(provenance))
  if missing_provenance:
    raise ReplayInvariantError(
        "Provenance missing fields: {}.".format(
            sorted(missing_provenance)))
  _write_json(os.path.join(
      run_directory, finals_config.PROACTIVE_PROVENANCE_FILENAME),
      provenance)
  return run_directory


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run non-formal CAPD proactive stage-1 fixtures.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--fixture", required=True)
  parser.add_argument("--output-root", required=True)
  return parser


def main(argv=None):
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  project_root = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
  stage0_config = finals_config.load_config(args.config)
  fixture = finals_config.load_json(args.fixture)
  results = run_fixture_scenarios(stage0_config, fixture)
  run_directory = write_fixture_outputs(
      project_root, stage0_config, fixture, results, args.output_root,
      command=sys.argv if argv is None else ["proactive_replay"] + list(argv))
  for name in sorted(results):
    print("[SCENARIO] {} {}".format(
        name, json.dumps(results[name]["summary"], sort_keys=True)))
  print("[OUTPUT] {}".format(run_directory))
  print("[FINAL] STAGE1_FIXTURE_REPLAY_OK")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
