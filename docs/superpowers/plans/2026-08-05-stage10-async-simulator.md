# CAPD Stage10A Async Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Build and locally verify a deterministic pure-Python Stage10A discrete-event simulator whose fixture results are candidate-ready while formal Stage10 remains fail-closed until verified Stage9 v2 evidence exists.

**Architecture:** Keep simulation semantics in one import-safe module and orchestration/artifact writing in one runner. The simulator uses integer nanoseconds, a deterministic heap, one serial background state machine, a unified reservation contract, and event-interval metric accumulation. Configuration and result schema are Stage10-owned; Stage8 r5 and the failed Stage9 r1 tree remain read-only authorities.

**Tech Stack:** Python 3 standard library, unittest, JSON/JSONL, hashlib, heapq, dataclasses, fractions/decimal, PowerShell and Bash handoff commands.

---

## Approval And Scope Boundary

This document is a plan only. Do not execute any task until the user approves this plan and chooses an execution style.

After approval, Task 1 changes the design status from `design review pending; implementation not authorized` to `design approved; Stage10A implementation authorized`. No task authorizes Stage10B, a Stage9 90-job replay, changes to Stage8 r5 or Stage9 r1 evidence, formal-result fabrication, commit, push, or Test-based tuning. Commit commands below are optional execution checkpoints and require the user's repository-write approval at execution time.

Immutable trees:

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`
- `outputs/capd_proactive_stage9/stage9-overhead-r1/`

Expected pre/post tree digests:

- Stage8 r5: `554eba14afa57eab2e02aaa156f32181d29d4c66929a5fd2ca934e87c5cf49db`
- Stage9 r1: `805c73bf0f280799817f481ef4a3cbab2d470de2c40adcf78d081f1f15a96a7b`

## File Map

- Create `qmap/proactive_stage10.py`: contracts, typed records, arrival generation, event heap, simulator state machine, metric aggregation, formal Stage9 receipt validation.
- Create `scripts/run_capd_proactive_stage10.py`: CLI, fixture scenarios, run-directory lifecycle, reports, candidate artifacts, manifest/SHA generation, independent verification.
- Create `configs/finals/capd_proactive_stage10.json`: explicit Stage10A fixture scenarios and formal-gate inputs.
- Create `configs/finals/capd_proactive_stage10_result_schema.json`: machine-readable result and nullability contract.
- Create `tests/test_capd_proactive_stage10.py`: deterministic synthetic unit and integration tests only.
- Create `docs/CAPD_PROACTIVE_STAGE10_PROTOCOL_CN.md`: simulator semantics and interpretation boundary.
- Create `docs/CAPD_PROACTIVE_STAGE10_STATUS_CN.md`: candidate/formal status and evidence boundary.
- Create `docs/CAPD_PROACTIVE_STAGE10_SERVER_CN.md`: copyable future Linux commands, gated on Stage9 v2.
- Modify `docs/superpowers/specs/2026-08-05-stage10-async-simulator-design.md`: status line only, after plan approval.

### Task 1: Approve The Design Status And Lock The Stage10 Contract

**Files:**

- Modify: `docs/superpowers/specs/2026-08-05-stage10-async-simulator-design.md:3`
- Create: `configs/finals/capd_proactive_stage10.json`
- Create: `configs/finals/capd_proactive_stage10_result_schema.json`
- Create: `qmap/proactive_stage10.py`
- Create: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Capture a direct before-snapshot of both immutable trees**

Run this before any implementation edit:

~~~powershell
$frozenRoots = @(
  'outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit',
  'outputs/capd_proactive_stage9/stage9-overhead-r1'
)
$frozenRows = foreach ($rootName in $frozenRoots) {
  $resolvedRoot = (Resolve-Path -LiteralPath $rootName).Path
  Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
      [ordered]@{
        root = $rootName
        relative_path = $_.FullName.Substring($resolvedRoot.Length + 1).Replace('\', '/')
        length = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower()
      }
    }
}
$frozenRows | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 'tmp/stage10-frozen-before.json'
~~~

This execution-local file-by-file snapshot supplements the two design-review tree digests and gives the final audit an exact comparison source.

- [ ] **Step 2: Update only the design approval line**

Change the exact line to:

~~~markdown
**Status:** design approved; Stage10A implementation authorized.
~~~

Do not change any other design text in this step.

- [ ] **Step 3: Write failing configuration and schema tests**

Create the test module with repository-local import setup and these contract tests:

~~~python
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from qmap import proactive_stage10 as stage10


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage10.json")
SCHEMA_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage10_result_schema.json")


def load_json(path):
  with open(path, "r", encoding="utf-8") as handle:
    return json.load(handle)


class Stage10ConfigContractTest(unittest.TestCase):

  def test_repository_config_and_schema_are_valid(self):
    config = load_json(CONFIG_PATH)
    schema = load_json(SCHEMA_PATH)
    stage10.validate_config(config)
    self.assertEqual("CAPD-PROACTIVE-STAGE10-1.0",
                     config["contract_id"])
    self.assertEqual("fixture", config["mode"])
    self.assertEqual("lru_tail", config["candidate_source"])
    self.assertEqual(["0.5", "0.8", "1.0", "1.2"],
                     [row["load_ratio"]
                      for row in config["uniform_scenarios"]])
    self.assertEqual("capd_proactive_stage10_result_v1_0",
                     schema["schema_version"])
    self.assertEqual(["null", "integer"],
                     schema["properties"]["observed"]["properties"]
                     ["foreground_blocking_time_mean_ns"]["type"])

  def test_invalid_timing_capacity_and_arrival_kind_fail_closed(self):
    base = load_json(CONFIG_PATH)
    for path, value in (
        (("fixture_parameters", "T_inference_ns"), 0),
        (("fixture_parameters", "b_t_reference"), 3),
        (("fixture_parameters", "initial_free_frames"), 65),
        (("fixture_parameters", "F_low"), 24),
        (("candidate_source",), "all_resident"),
        (("arrival_models",), ["trace"]),
    ):
      bad = copy.deepcopy(base)
      target = bad
      for key in path[:-1]:
        target = target[key]
      target[path[-1]] = value
      with self.subTest(path=path):
        with self.assertRaises(stage10.Stage10ContractError):
          stage10.validate_config(bad)
~~~

- [ ] **Step 4: Run the focused tests and confirm the expected import failure**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10ConfigContractTest -v
~~~

Expected: FAIL because `qmap.proactive_stage10` and the Stage10 config/schema do not exist.

- [ ] **Step 5: Create the explicit fixture configuration**

Create a JSON document with these exact contract values:

~~~json
{
  "schema_version": "capd_proactive_stage10_v1_0",
  "contract_id": "CAPD-PROACTIVE-STAGE10-1.0",
  "mode": "fixture",
  "stage_status": "stage10_simulator_implementation_candidate",
  "output_root": "outputs/capd_proactive_stage10",
  "candidate_run_id": "stage10-async-simulator-r1",
  "result_schema": "configs/finals/capd_proactive_stage10_result_schema.json",
  "candidate_source": "lru_tail",
  "arrival_models": ["uniform", "burst"],
  "trace_replay": {
    "enabled": false,
    "status": "future_input_option_requires_reliable_timestamps"
  },
  "fixture_parameters": {
    "T_inference_ns": 2000,
    "T_migration_ns": 1000,
    "b_max": 2,
    "b_t_reference": 2,
    "dram_capacity_frames": 64,
    "initial_free_frames": 16,
    "F_low": 16,
    "F_target": 24,
    "K": 8,
    "simulation_horizon_ns": 200000,
    "seed": 3136859
  },
  "uniform_scenarios": [
    {"scenario_id": "uniform-0p5", "load_ratio": "0.5"},
    {"scenario_id": "uniform-0p8", "load_ratio": "0.8"},
    {"scenario_id": "uniform-1p0", "load_ratio": "1.0"},
    {"scenario_id": "uniform-1p2", "load_ratio": "1.2"}
  ],
  "burst_scenarios": [
    {
      "scenario_id": "burst-multi-r1",
      "base_load_ratio": "0.5",
      "bursts": [
        {"start_ns": 50000, "duration_ns": 30000, "multiplier": "2.0"},
        {"start_ns": 120000, "duration_ns": 20000, "multiplier": "1.6"}
      ]
    }
  ],
  "formal_gate": {
    "required_stage9_contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
    "required_stage9_status": "stage9_overhead_verified",
    "rejected_run_ids": ["stage9-overhead-r1"],
    "historical_failed_run_state": {
      "path": "outputs/capd_proactive_stage9/stage9-overhead-r1/run_state.json",
      "sha256": "662a5e44f488a7951ddc2e9a75a39d49bd5024b6e9fde718a8553dd362711d15"
    },
    "stage8_r5_tree_sha256": "554eba14afa57eab2e02aaa156f32181d29d4c66929a5fd2ca934e87c5cf49db"
  }
}
~~~

`uniform` means deterministic fixed-rate uniform spacing, not random sampling. Trace timestamp replay is deliberately not an accepted Stage10A arrival kind.

- [ ] **Step 6: Create the result schema and minimal contract module**

The schema must require top-level `scenario_id`, `mode`, `observed`, `derived`, and `interpretation`; use JSON `null` for empty blocking mean/P95:

~~~json
{
  "schema_version": "capd_proactive_stage10_result_v1_0",
  "contract_id": "CAPD-PROACTIVE-STAGE10-1.0",
  "required": ["scenario_id", "mode", "observed", "derived", "interpretation"],
  "properties": {
    "scenario_id": {"type": "string"},
    "mode": {"enum": ["fixture"]},
    "observed": {
      "type": "object",
      "required": [
        "emergency_fallback_count",
        "fallback_rate",
        "foreground_blocking_time_total_ns",
        "foreground_blocking_time_mean_ns",
        "foreground_blocking_time_p95_ns",
        "blocking_sample_count",
        "minimum_free_frames",
        "free_frame_exhaustion_duration_ns",
        "background_queue_length_mean",
        "background_queue_length_max",
        "background_queue_length_p95",
        "background_utilization",
        "page_enter_dram_count",
        "demotion_finish_count",
        "effective_demotion_rate",
        "unfinished_blocked_request_count"
      ],
      "properties": {
        "emergency_fallback_count": {"type": "integer"},
        "fallback_rate": {"type": ["null", "number"]},
        "foreground_blocking_time_total_ns": {"type": "integer"},
        "foreground_blocking_time_mean_ns": {"type": ["null", "integer"]},
        "foreground_blocking_time_p95_ns": {"type": ["null", "integer"]},
        "blocking_sample_count": {"type": "integer"},
        "minimum_free_frames": {"type": "integer"},
        "free_frame_exhaustion_duration_ns": {"type": "integer"},
        "background_queue_length_mean": {"type": "number"},
        "background_queue_length_max": {"type": "integer"},
        "background_queue_length_p95": {"type": "integer"},
        "background_utilization": {"type": "number"},
        "page_enter_dram_count": {"type": "integer"},
        "demotion_finish_count": {"type": "integer"},
        "effective_demotion_rate": {"type": "number"},
        "unfinished_blocked_request_count": {"type": "integer"}
      }
    },
    "derived": {
      "type": "object",
      "required": [
        "simulation_horizon_ns", "seed", "T_inference_ns",
        "T_migration_ns", "b_max", "b_t_reference",
        "mu_demote_pages_per_ns_numerator",
        "mu_demote_pages_per_ns_denominator",
        "actual_b_t_values", "actual_b_t_distribution", "arrival_model"
      ]
    },
    "interpretation": {
      "type": "object",
      "required": [
        "scope", "real_linux_measurement_claimed",
        "kernel_behavior_claimed"
      ]
    }
  }
}
~~~

Create the module foundation:

~~~python
"""Deterministic CAPD Stage10A discrete-event simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "capd_proactive_stage10_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE10-1.0"
FIXTURE = "fixture"
FORMAL_BLOCKED = "stage10_formal_blocked_by_stage9"
ALLOWED_ARRIVAL_MODELS = ("uniform", "burst")


class Stage10ContractError(ValueError):
  """Raised when Stage10 input, state, or evidence violates the contract."""


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage10ContractError(message)


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Stage10 schema mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Stage10 contract mismatch.")
  _require(value.get("mode") == FIXTURE, "Repository config must be fixture.")
  _require(value.get("candidate_source") == "lru_tail",
           "Stage10 candidate source changed.")
  _require(value.get("arrival_models") == list(ALLOWED_ARRIVAL_MODELS),
           "Stage10A supports uniform and burst arrivals only.")
  _require(value.get("trace_replay") == {
      "enabled": False,
      "status": "future_input_option_requires_reliable_timestamps"},
      "Trace replay must remain disabled.")
  params = value.get("fixture_parameters", {})
  positive = ("T_inference_ns", "T_migration_ns", "b_max",
              "b_t_reference", "dram_capacity_frames", "F_low",
              "F_target", "K", "simulation_horizon_ns")
  _require(all(isinstance(params.get(key), int) and params[key] > 0
               for key in positive), "Positive integer parameter required.")
  capacity = params["dram_capacity_frames"]
  free = params.get("initial_free_frames")
  _require(isinstance(free, int) and 0 <= free <= capacity,
           "Invalid initial free-frame count.")
  _require(1 <= params["b_t_reference"] <= params["b_max"],
           "b_t_reference must be within [1,b_max].")
  _require(0 < params["F_low"] < params["F_target"] <= capacity,
           "Watermarks must satisfy 0<F_low<F_target<=capacity.")
  _require(params["K"] >= params["b_max"], "K must cover b_max.")
  ratios = [row.get("load_ratio")
            for row in value.get("uniform_scenarios", ())]
  _require(ratios == ["0.5", "0.8", "1.0", "1.2"],
           "Uniform load matrix changed.")
  return value
~~~

- [ ] **Step 7: Run the contract tests**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10ConfigContractTest -v
~~~

Expected: 2 tests PASS.

- [ ] **Step 8: Optional approved checkpoint commit**

~~~powershell
git add docs/superpowers/specs/2026-08-05-stage10-async-simulator-design.md configs/finals/capd_proactive_stage10.json configs/finals/capd_proactive_stage10_result_schema.json qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "test: lock Stage10A simulator contract"
~~~

### Task 2: Implement Deterministic Event Ordering

**Files:**

- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write failing event heap tests**

Append:

~~~python
class Stage10EventHeapTest(unittest.TestCase):

  def test_same_time_events_follow_frozen_priority_then_event_id(self):
    queue = stage10.EventQueue()
    queue.schedule(9, "page_enter_dram", {"name": "arrival-1"})
    queue.schedule(9, "capd_round_start", {"name": "round"})
    queue.schedule(9, "demotion_finish", {"name": "demotion"})
    queue.schedule(9, "emergency_fallback", {"name": "fallback"})
    queue.schedule(9, "capd_inference_finish", {"name": "inference"})
    queue.schedule(9, "page_enter_dram", {"name": "arrival-2"})
    self.assertEqual(
        ["demotion_finish", "capd_inference_finish", "capd_round_start",
         "emergency_fallback", "page_enter_dram", "page_enter_dram"],
        [queue.pop().kind for _ in range(6)])

  def test_event_ids_are_strictly_monotonic(self):
    queue = stage10.EventQueue()
    first = queue.schedule(3, "page_enter_dram", {})
    second = queue.schedule(1, "page_enter_dram", {})
    self.assertEqual((1, 2), (first.event_id, second.event_id))
~~~

- [ ] **Step 2: Run and confirm the missing-type failure**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10EventHeapTest -v
~~~

Expected: FAIL with missing `EventQueue`.

- [ ] **Step 3: Implement immutable events and the heap**

Add:

~~~python
import heapq
from dataclasses import dataclass, field
from typing import Dict, List


EVENT_PRIORITY = {
    "demotion_finish": 0,
    "capd_inference_finish": 1,
    "capd_round_start": 2,
    "emergency_fallback": 3,
    "page_enter_dram": 4,
}


@dataclass(order=True, frozen=True)
class Event:
  timestamp_ns: int
  priority: int
  event_id: int
  kind: str = field(compare=False)
  payload: Mapping[str, Any] = field(compare=False)


class EventQueue:

  def __init__(self) -> None:
    self._heap: List[Event] = []
    self._next_event_id = 1

  def schedule(self, timestamp_ns: int, kind: str,
               payload: Mapping[str, Any]) -> Event:
    _require(isinstance(timestamp_ns, int) and timestamp_ns >= 0,
             "Event time must be a non-negative integer.")
    _require(kind in EVENT_PRIORITY, "Unknown event kind: " + str(kind))
    event = Event(timestamp_ns, EVENT_PRIORITY[kind], self._next_event_id,
                  kind, dict(payload))
    self._next_event_id += 1
    heapq.heappush(self._heap, event)
    return event

  def pop(self) -> Event:
    _require(bool(self._heap), "Cannot pop an empty event queue.")
    return heapq.heappop(self._heap)

  def __bool__(self) -> bool:
    return bool(self._heap)
~~~

- [ ] **Step 4: Run event and contract tests**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10EventHeapTest tests.test_capd_proactive_stage10.Stage10ConfigContractTest -v
~~~

Expected: 4 tests PASS.

- [ ] **Step 5: Optional approved checkpoint commit**

~~~powershell
git add qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: add deterministic Stage10 event heap"
~~~

### Task 3: Implement Resident State, LRU Selection, And Reservations

**Files:**

- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write failing initialization, MRU, candidate, and duplicate-reservation tests**

Append:

~~~python
class Stage10StateContractTest(unittest.TestCase):

  def _state(self, **overrides):
    config = load_json(CONFIG_PATH)["fixture_parameters"]
    config.update(overrides)
    return stage10.SimulatorState(stage10.SimulatorConfig.from_mapping(config))

  def test_initial_resident_ids_and_lru_order_are_deterministic(self):
    state = self._state(dram_capacity_frames=8, initial_free_frames=3,
                        F_low=2, F_target=4, K=4)
    self.assertEqual(5, state.initial_resident_count)
    self.assertEqual([0, 1, 2, 3, 4], state.lru_mru_to_lru)
    self.assertEqual([4, 3, 2], state.select_candidates(3))

  def test_new_and_unblocked_pages_enter_mru_head(self):
    state = self._state(dram_capacity_frames=4, initial_free_frames=1,
                        F_low=1, F_target=2, K=2)
    page_id = state.admit_new_page(state.next_page_id)
    self.assertEqual(page_id, state.lru_mru_to_lru[0])
    state.begin_blocked_request(11, state.next_page_id)
    state.release_resident_page(2)
    state.admit_oldest_blocked(12)
    self.assertEqual(state.last_admitted_page_id, state.lru_mru_to_lru[0])

  def test_reserved_components_are_disjoint_and_duplicate_is_rejected(self):
    state = self._state()
    state.reserve_inference([0])
    with self.assertRaises(stage10.Stage10ContractError):
      state.reserve_normal_migration([0])
    with self.assertRaises(stage10.Stage10ContractError):
      state.reserve_emergency_migration([0])
    self.assertEqual({0}, state.reserved_page_ids)

  def test_capacity_and_frame_invariants_hold_after_admission_and_release(self):
    state = self._state(dram_capacity_frames=4, initial_free_frames=1,
                        F_low=1, F_target=2, K=2)
    state.admit_new_page(state.next_page_id)
    self.assertEqual(0, state.free_frames)
    state.begin_blocked_request(2, state.next_page_id)
    state.release_resident_page(2)
    state.admit_oldest_blocked(3)
    state.assert_invariants()
    self.assertEqual(4, state.free_frames + len(state.resident_page_ids))
~~~

- [ ] **Step 2: Run and confirm state symbols are absent**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10StateContractTest -v
~~~

Expected: FAIL because `SimulatorConfig` and `SimulatorState` are not yet defined.

- [ ] **Step 3: Add typed configuration and authoritative state**

Add these definitions after `validate_config`; preserve MRU-to-LRU ordering and keep all reservation components disjoint:

~~~python
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Set


@dataclass(frozen=True)
class SimulatorConfig:
  T_inference_ns: int
  T_migration_ns: int
  b_max: int
  b_t_reference: int
  dram_capacity_frames: int
  initial_free_frames: int
  F_low: int
  F_target: int
  K: int
  simulation_horizon_ns: int
  seed: int = 0

  def __post_init__(self) -> None:
    _require(self.T_inference_ns > 0 and self.T_migration_ns > 0,
             "Service durations must be positive.")
    _require(self.dram_capacity_frames > 0 and
             0 <= self.initial_free_frames <= self.dram_capacity_frames,
             "Initial frame state is invalid.")
    _require(0 < self.F_low < self.F_target <= self.dram_capacity_frames,
             "Watermarks are invalid.")
    _require(1 <= self.b_t_reference <= self.b_max <= self.K,
             "Batch and candidate bounds are invalid.")
    _require(self.simulation_horizon_ns > 0,
             "Simulation horizon must be positive.")

  @classmethod
  def from_mapping(cls, value: Mapping[str, Any]) -> "SimulatorConfig":
    return cls(**{key: value[key] for key in (
        "T_inference_ns", "T_migration_ns", "b_max", "b_t_reference",
        "dram_capacity_frames", "initial_free_frames", "F_low",
        "F_target", "K", "simulation_horizon_ns", "seed")})


@dataclass
class SimulatorState:
  config: SimulatorConfig
  free_frames: int = field(init=False)
  resident_page_ids: Set[int] = field(init=False)
  lru_mru_to_lru: List[int] = field(init=False)
  next_page_id: int = field(init=False)
  inference_selected_page_ids: Set[int] = field(default_factory=set)
  active_migration_page_ids: Set[int] = field(default_factory=set)
  pending_normal_migration_page_ids: Set[int] = field(default_factory=set)
  pending_emergency_migration_page_ids: Set[int] = field(default_factory=set)
  blocked_requests: Deque[tuple] = field(default_factory=deque)
  last_admitted_page_id: int = field(init=False, default=-1)

  def __post_init__(self):
    count = self.config.dram_capacity_frames - self.config.initial_free_frames
    self.free_frames = self.config.initial_free_frames
    self.resident_page_ids = set(range(count))
    self.lru_mru_to_lru = list(range(count))
    self.next_page_id = count
    self.assert_invariants()

  @property
  def initial_resident_count(self) -> int:
    return self.config.dram_capacity_frames - self.config.initial_free_frames

  @property
  def reserved_page_ids(self) -> Set[int]:
    groups = (
        self.inference_selected_page_ids,
        self.active_migration_page_ids,
        self.pending_normal_migration_page_ids,
        self.pending_emergency_migration_page_ids)
    _require(not any(groups[i] & groups[j]
                     for i in range(len(groups))
                     for j in range(i + 1, len(groups))),
             "A page is reserved by more than one work component.")
    return set().union(*groups)

  def assert_invariants(self) -> None:
    _require(self.free_frames >= 0, "Negative free-frame count.")
    _require(self.free_frames + len(self.resident_page_ids) ==
             self.config.dram_capacity_frames,
             "Frame/resident capacity invariant failed.")
    _require(set(self.lru_mru_to_lru) == self.resident_page_ids,
             "LRU order and resident set differ.")
    _require(self.reserved_page_ids <= self.resident_page_ids,
             "Reserved page is no longer resident.")

  def _reserve(self, target: Set[int], page_ids: List[int]) -> None:
    ids = set(page_ids)
    _require(len(ids) == len(page_ids), "Duplicate page in one reservation.")
    _require(ids <= self.resident_page_ids and not (ids & self.reserved_page_ids),
             "Page is unavailable for reservation.")
    target.update(ids)
    self.assert_invariants()

  def reserve_inference(self, page_ids: List[int]) -> None:
    self._reserve(self.inference_selected_page_ids, page_ids)

  def reserve_normal_migration(self, page_ids: List[int]) -> None:
    self._reserve(self.pending_normal_migration_page_ids, page_ids)

  def reserve_emergency_migration(self, page_ids: List[int]) -> None:
    self._reserve(self.pending_emergency_migration_page_ids, page_ids)

  def move_inference_to_normal(self, page_ids: List[int]) -> None:
    ids = set(page_ids)
    _require(ids == self.inference_selected_page_ids,
             "Inference completion batch changed.")
    self.inference_selected_page_ids.clear()
    self.pending_normal_migration_page_ids.update(ids)
    self.assert_invariants()

  def start_migration(self, kind: str, page_id: int) -> None:
    source = (self.pending_emergency_migration_page_ids
              if kind == "emergency"
              else self.pending_normal_migration_page_ids)
    _require(page_id in source and not self.active_migration_page_ids,
             "Migration start violates serial reservation state.")
    source.remove(page_id)
    self.active_migration_page_ids.add(page_id)
    self.assert_invariants()

  def finish_migration(self, page_id: int) -> None:
    _require(self.active_migration_page_ids == {page_id},
             "Migration completion does not match active page.")
    self.active_migration_page_ids.remove(page_id)

  def select_candidates(self, limit: int) -> List[int]:
    candidates = [page for page in reversed(self.lru_mru_to_lru)
                  if page not in self.reserved_page_ids]
    return candidates[:limit]

  def _insert_mru(self, page_id: int) -> None:
    self.lru_mru_to_lru.insert(0, page_id)
    self.resident_page_ids.add(page_id)
    self.last_admitted_page_id = page_id

  def admit_new_page(self, page_id: int) -> int:
    _require(self.free_frames > 0, "Admission requires a free frame.")
    _require(page_id == self.next_page_id,
             "Arrival page IDs must be monotonic.")
    self.next_page_id += 1
    self.free_frames -= 1
    self._insert_mru(page_id)
    self.assert_invariants()
    return page_id

  def begin_blocked_request(self, timestamp_ns: int, page_id: int) -> None:
    _require(self.free_frames == 0, "Blocked request requires no free frame.")
    _require(page_id == self.next_page_id,
             "Blocked page IDs must be monotonic.")
    self.blocked_requests.append((timestamp_ns, page_id))
    self.next_page_id += 1

  def release_resident_page(self, page_id: int) -> None:
    _require(page_id in self.resident_page_ids,
             "Demotion must remove one resident page.")
    _require(page_id not in self.reserved_page_ids,
             "Reservation must be cleared at the service boundary.")
    self.resident_page_ids.remove(page_id)
    self.lru_mru_to_lru.remove(page_id)
    self.free_frames += 1
    self.assert_invariants()

  def admit_oldest_blocked(self, timestamp_ns: int) -> int:
    _require(self.blocked_requests, "No blocked request to admit.")
    _require(self.free_frames > 0,
             "Blocked admission requires a released frame.")
    blocked_at, page_id = self.blocked_requests.popleft()
    self.free_frames -= 1
    self._insert_mru(page_id)
    self.assert_invariants()
    return timestamp_ns - blocked_at
~~~

- [ ] **Step 4: Run state tests and fix only contract errors**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10StateContractTest -v
~~~

Expected: 4 tests PASS. The implementation must not append admitted pages to the LRU tail; both immediate and post-blocking admissions use `_insert_mru`.

- [ ] **Step 5: Add low-watermark batch sizing tests and implementation**

Test and implement the exact batch rule:

~~~python
  def test_batch_size_is_bounded_by_target_gap_and_candidates(self):
    state = self._state(b_max=4, F_low=2, F_target=5)
    self.assertEqual(4, state.batch_size(free_frames=1, candidate_count=9))
    self.assertEqual(2, state.batch_size(free_frames=3, candidate_count=9))
    self.assertEqual(1, state.batch_size(free_frames=1, candidate_count=1))
~~~

~~~python
  def batch_size(self, free_frames: int, candidate_count: int) -> int:
    return min(self.config.b_max,
               self.config.F_target - free_frames,
               candidate_count)
~~~

- [ ] **Step 6: Run all tests from Tasks 1-3**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10 -v
~~~

Expected: all tests currently defined in the module PASS.

- [ ] **Step 7: Optional approved checkpoint commit**

~~~powershell
git add qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: enforce Stage10 resident and reservation invariants"
~~~

### Task 4: Implement Uniform And Burst Arrival Generators

**Files:**

- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write generator tests before implementation**

Append:

~~~python
class Stage10ArrivalTest(unittest.TestCase):

  def test_uniform_generator_is_reproducible_and_integer_ns(self):
    config = load_json(CONFIG_PATH)["fixture_parameters"]
    params = stage10.SimulatorConfig.from_mapping(config)
    first = stage10.generate_uniform_arrivals(
        params, load_ratio="0.8", horizon_ns=100000)
    second = stage10.generate_uniform_arrivals(
        params, load_ratio="0.8", horizon_ns=100000)
    self.assertEqual(first, second)
    self.assertTrue(all(isinstance(item.timestamp_ns, int) for item in first))
    self.assertTrue(all(0 <= item.timestamp_ns <= 100000 for item in first))

  def test_uniform_period_uses_reference_batch_and_model_capacity(self):
    config = load_json(CONFIG_PATH)["fixture_parameters"]
    params = stage10.SimulatorConfig.from_mapping(config)
    arrivals = stage10.generate_uniform_arrivals(
        params, load_ratio="1.0", horizon_ns=100000)
    expected_period = (
        params.T_inference_ns +
        params.b_t_reference * params.T_migration_ns
    ) // params.b_t_reference
    self.assertEqual(expected_period,
                     arrivals[1].timestamp_ns - arrivals[0].timestamp_ns)

  def test_burst_intervals_are_non_overlapping_and_reproducible(self):
    config = load_json(CONFIG_PATH)
    params = stage10.SimulatorConfig.from_mapping(config["fixture_parameters"])
    bursts = config["burst_scenarios"][0]["bursts"]
    first = stage10.generate_burst_arrivals(
        params, bursts, base_load_ratio="0.5",
        horizon_ns=params.simulation_horizon_ns)
    second = stage10.generate_burst_arrivals(
        params, bursts, base_load_ratio="0.5",
        horizon_ns=params.simulation_horizon_ns)
    self.assertEqual(first, second)
    self.assertEqual(first, sorted(first, key=lambda item: item.timestamp_ns))
    for item in first:
      self.assertTrue(
          any(burst["start_ns"] <= item.timestamp_ns <
              burst["start_ns"] + burst["duration_ns"]
              for burst in bursts))

  def test_trace_replay_is_rejected_until_a_future_timestamp_contract_exists(self):
    params = stage10.SimulatorConfig.from_mapping(
        load_json(CONFIG_PATH)["fixture_parameters"])
    with self.assertRaises(stage10.Stage10ContractError):
      stage10.generate_arrivals(params, {"kind": "trace", "path": "trace.json"})

  def test_overlapping_bursts_are_rejected(self):
    params = stage10.SimulatorConfig.from_mapping(
        load_json(CONFIG_PATH)["fixture_parameters"])
    with self.assertRaises(stage10.Stage10ContractError):
      stage10.generate_burst_arrivals(
          params,
          [{"start_ns": 10, "duration_ns": 20, "multiplier": "2.0"},
           {"start_ns": 20, "duration_ns": 20, "multiplier": "1.5"}],
          base_load_ratio="0.5", horizon_ns=100)
~~~

- [ ] **Step 2: Run and confirm generator symbols are absent**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10ArrivalTest -v
~~~

Expected: FAIL because the arrival functions are not defined.

- [ ] **Step 3: Implement model-derived capacity and exact fixed-point periods**

Use `Fraction` so decimal ratios do not accumulate binary floating-point error:

~~~python
from fractions import Fraction


@dataclass(frozen=True)
class Arrival:
  timestamp_ns: int
  page_id: int


def mu_demote(params: SimulatorConfig) -> Fraction:
  return Fraction(params.b_t_reference,
                  params.T_inference_ns +
                  params.b_t_reference * params.T_migration_ns)


def _period_ns(params: SimulatorConfig, load_ratio: str) -> Fraction:
  ratio = Fraction(str(load_ratio))
  _require(ratio > 0, "Arrival load ratio must be positive.")
  return Fraction(1, 1) / (mu_demote(params) * ratio)


def generate_uniform_arrivals(params: SimulatorConfig, load_ratio: str,
                              horizon_ns: int) -> List[Arrival]:
  period = _period_ns(params, load_ratio)
  result = []
  index = 0
  first_page_id = (
      params.dram_capacity_frames - params.initial_free_frames)
  while True:
    timestamp = int(period * index)
    if timestamp > horizon_ns:
      break
    result.append(Arrival(timestamp, first_page_id + index))
    index += 1
  return result


def generate_burst_arrivals(params: SimulatorConfig, bursts: List[Mapping[str, Any]],
                            base_load_ratio: str,
                            horizon_ns: int) -> List[Arrival]:
  result = []
  next_page_id = params.dram_capacity_frames - params.initial_free_frames
  ordered = sorted(bursts, key=lambda row: row["start_ns"])
  for previous, current in zip(ordered, ordered[1:]):
    _require(previous["start_ns"] + previous["duration_ns"] <=
             current["start_ns"], "Burst intervals must not overlap.")
  for burst in ordered:
    start = burst["start_ns"]
    end = start + burst["duration_ns"]
    _require(start >= 0 and end <= horizon_ns,
             "Burst interval must be within the simulation horizon.")
    ratio = Fraction(str(base_load_ratio)) * Fraction(str(burst["multiplier"]))
    period = _period_ns(params, str(ratio))
    period_ceiling = (period.numerator + period.denominator - 1) // period.denominator
    phase = (params.seed ^ start ^ end) % max(1, period_ceiling)
    index = 0
    while True:
      timestamp = start + phase + int(period * index)
      if timestamp >= end:
        break
      result.append(Arrival(timestamp, next_page_id))
      next_page_id += 1
      index += 1
  return sorted(result, key=lambda item: (item.timestamp_ns, item.page_id))


def generate_arrivals(params: SimulatorConfig,
                      model: Mapping[str, Any]) -> List[Arrival]:
  kind = model.get("kind")
  if kind == "uniform":
    return generate_uniform_arrivals(
        params, str(model["load_ratio"]), params.simulation_horizon_ns)
  if kind == "burst":
    return generate_burst_arrivals(
        params, list(model["bursts"]), str(model["base_load_ratio"]),
        params.simulation_horizon_ns)
  raise Stage10ContractError(
      "Stage10A supports uniform and burst arrivals only.")
~~~

The uniform generator is the default Stage10A arrival model. A reliable trace replay input can be added only as a later contract extension with timestamp units, monotonicity, and provenance fields; this plan does not implement it.

- [ ] **Step 4: Run arrival tests and verify all four load ratios**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10ArrivalTest -v
~~~

Expected: 5 tests PASS. Also run a one-line smoke check that `mu_demote` uses `b_t_reference`, not `b_max`:

~~~powershell
python -c "from fractions import Fraction; from qmap.proactive_stage10 import SimulatorConfig,mu_demote; p=SimulatorConfig(2000,1000,4,2,64,16,16,24,8,200000,1); assert mu_demote(p)==Fraction(2,4000)"
~~~

- [ ] **Step 5: Optional approved checkpoint commit**

~~~powershell
git add qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: add deterministic uniform and burst arrivals"
~~~

### Task 5: Implement The Single Background State Machine And Metrics

**Files:**

- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write failing end-to-end simulator tests**

Append:

~~~python
class Stage10SimulationTest(unittest.TestCase):

  def _params(self, **overrides):
    value = load_json(CONFIG_PATH)["fixture_parameters"]
    value.update(overrides)
    return stage10.SimulatorConfig.from_mapping(value)

  def test_identical_seed_and_arrivals_produce_identical_events_and_metrics(self):
    params = self._params(simulation_horizon_ns=50000)
    arrivals = stage10.generate_uniform_arrivals(params, "0.8", 50000)
    first = stage10.run_simulation(params, arrivals)
    second = stage10.run_simulation(params, arrivals)
    self.assertEqual(first.events, second.events)
    self.assertEqual(first.metrics, second.metrics)

  def test_arrival_consumes_frame_and_demotion_releases_it(self):
    params = self._params(dram_capacity_frames=3, initial_free_frames=1,
                          F_low=1, F_target=2, simulation_horizon_ns=10000)
    result = stage10.run_simulation(
        params, [stage10.Arrival(0, 2), stage10.Arrival(6000, 3)])
    self.assertGreaterEqual(result.metrics["page_enter_dram_count"], 1)
    self.assertGreaterEqual(result.metrics["demotion_finish_count"], 1)
    self.assertGreaterEqual(result.metrics["minimum_free_frames"], 0)

  def test_full_arrival_is_blocked_then_admitted_after_demotion(self):
    params = self._params(dram_capacity_frames=2, initial_free_frames=0,
                          F_low=1, F_target=2, simulation_horizon_ns=10000)
    result = stage10.run_simulation(
        params, [stage10.Arrival(0, 2)])
    self.assertEqual(1, result.metrics["blocking_sample_count"])
    self.assertGreater(result.metrics["foreground_blocking_time_total_ns"], 0)
    self.assertEqual(0, result.metrics["unfinished_blocked_request_count"])

  def test_empty_blocking_samples_are_null_and_exhaustion_is_time_integral(self):
    params = self._params(initial_free_frames=0, simulation_horizon_ns=10000)
    result = stage10.run_simulation(params, [])
    self.assertIsNone(result.metrics["foreground_blocking_time_mean_ns"])
    self.assertIsNone(result.metrics["foreground_blocking_time_p95_ns"])
    self.assertEqual(0, result.metrics["blocking_sample_count"])
    self.assertEqual(10000, result.metrics["free_frame_exhaustion_duration_ns"])
    self.assertEqual(0, result.metrics["emergency_fallback_count"])

  def test_runtime_batch_values_are_bounded_and_high_load_queue_is_explainable(self):
    params = self._params(simulation_horizon_ns=200000)
    low = stage10.run_simulation(
        params, stage10.generate_uniform_arrivals(params, "0.5", 200000))
    high = stage10.run_simulation(
        params, stage10.generate_uniform_arrivals(params, "1.2", 200000))
    self.assertTrue(all(0 <= value <= params.b_max
                        for value in high.derived["actual_b_t_values"]))
    self.assertGreater(high.metrics["background_queue_length_max"], 0)
    self.assertGreaterEqual(
        high.metrics["background_queue_length_max"],
        low.metrics["background_queue_length_max"])
~~~

- [ ] **Step 2: Run and confirm the simulator entry point is absent**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10SimulationTest -v
~~~

Expected: FAIL because `run_simulation` and `SimulationResult` are not defined.

- [ ] **Step 3: Add simulation records and event-interval accumulator**

Implement these records and helpers:

~~~python
from collections import Counter
from typing import Optional, Tuple


@dataclass
class SimulationResult:
  events: List[Mapping[str, Any]]
  metrics: Mapping[str, Any]
  derived: Mapping[str, Any]
  interpretation: Mapping[str, Any]


def _percentile(values: List[int], percentile: int) -> Optional[int]:
  if not values:
    return None
  ordered = sorted(values)
  index = (len(ordered) - 1) * percentile // 100
  return ordered[index]


class _MetricAccumulator:

  def __init__(self, horizon_ns: int):
    self.horizon_ns = horizon_ns
    self.last_time_ns = 0
    self.queue_area_ns = 0
    self.queue_durations_ns = Counter()
    self.background_active_ns = 0
    self.exhaustion_ns = 0
    self.queue_max = 0
    self.minimum_free_frames = None
    self.blocking_durations: List[int] = []
    self.blocking_total_ns = 0

  def observe_interval(self, now_ns: int, queue_length: int,
                       free_frames: int, background_active: bool) -> None:
    _require(0 <= self.last_time_ns <= now_ns <= self.horizon_ns,
             "Metric interval is outside the simulation window.")
    duration = now_ns - self.last_time_ns
    self.queue_area_ns += duration * queue_length
    self.queue_durations_ns[queue_length] += duration
    if background_active:
      self.background_active_ns += duration
    if free_frames == 0:
      self.exhaustion_ns += duration
    self.queue_max = max(self.queue_max, queue_length)
    if self.minimum_free_frames is None:
      self.minimum_free_frames = free_frames
    self.minimum_free_frames = min(self.minimum_free_frames, free_frames)
    self.last_time_ns = now_ns

  def observe_point(self, queue_length: int, free_frames: int) -> None:
    self.queue_max = max(self.queue_max, queue_length)
    if self.minimum_free_frames is None:
      self.minimum_free_frames = free_frames
    self.minimum_free_frames = min(self.minimum_free_frames, free_frames)

  def add_block(self, duration_ns: int) -> None:
    _require(duration_ns >= 0, "Blocking duration cannot be negative.")
    self.blocking_durations.append(duration_ns)
    self.blocking_total_ns += duration_ns

  def as_dict(self) -> Mapping[str, Any]:
    count = len(self.blocking_durations)
    mean = (self.blocking_total_ns // count) if count else None
    threshold = (95 * self.horizon_ns + 99) // 100
    cumulative = 0
    queue_p95 = 0
    for queue_length in sorted(self.queue_durations_ns):
      cumulative += self.queue_durations_ns[queue_length]
      if cumulative >= threshold:
        queue_p95 = queue_length
        break
    return {
        "foreground_blocking_time_total_ns": self.blocking_total_ns,
        "foreground_blocking_time_mean_ns": mean,
        "foreground_blocking_time_p95_ns":
            _percentile(self.blocking_durations, 95),
        "blocking_sample_count": count,
        "free_frame_exhaustion_duration_ns": self.exhaustion_ns,
        "background_queue_length_mean":
            (self.queue_area_ns / self.horizon_ns
             if self.horizon_ns else None),
        "background_queue_length_max": self.queue_max,
        "background_queue_length_p95": queue_p95,
        "background_utilization":
            (self.background_active_ns / self.horizon_ns
             if self.horizon_ns else None),
        "minimum_free_frames": self.minimum_free_frames,
    }
~~~

The accumulator must observe the final interval through `simulation_horizon_ns`; `free_frame_exhaustion_duration_ns` is exactly the integral of `F_t=0` on `[0, simulation_horizon_ns]`, including an initially exhausted state and the terminal interval after the last event. Queue mean/P95 are time-weighted over the same full window. Queue length means not-yet-started normal plus emergency migration jobs; it excludes the active inference or migration, whose interval is recorded separately by `background_utilization`.

- [ ] **Step 4: Implement event handlers with reservation transitions**

Implement `run_simulation` as one loop over `EventQueue`:

~~~python
def run_simulation(params: SimulatorConfig,
                   arrivals: List[Arrival]) -> SimulationResult:
  state = SimulatorState(params)
  queue = EventQueue()
  metrics = _MetricAccumulator(params.simulation_horizon_ns)
  events = []
  for arrival in arrivals:
    if 0 <= arrival.timestamp_ns <= params.simulation_horizon_ns:
      queue.schedule(arrival.timestamp_ns, "page_enter_dram",
                     {"page_id": arrival.page_id})
  active_service = None
  pending_jobs = deque()
  actual_b_t_values = []
  fallback_count = 0
  arrival_attempt_count = 0
  demotion_count = 0

  def start_next_migration(now_ns: int) -> None:
    nonlocal active_service
    if active_service is not None or not pending_jobs:
      return
    job_kind, page_id = pending_jobs.popleft()
    state.start_migration(job_kind, page_id)
    active_service = ("migration", page_id)
    queue.schedule(now_ns + params.T_migration_ns, "demotion_finish",
                   {"page_id": page_id, "job_kind": job_kind})

  while queue:
    event = queue.pop()
    if event.timestamp_ns > params.simulation_horizon_ns:
      break
    metrics.observe_interval(
        event.timestamp_ns, len(pending_jobs), state.free_frames,
        background_active=active_service is not None)
    if event.kind == "page_enter_dram":
      arrival_attempt_count += 1
      page_id = event.payload["page_id"]
      if state.free_frames:
        state.admit_new_page(page_id)
        queue.schedule(event.timestamp_ns, "capd_round_start", {})
      else:
        state.begin_blocked_request(event.timestamp_ns, page_id)
        queue.schedule(event.timestamp_ns, "emergency_fallback",
                       {"page_id": page_id})
    elif event.kind == "capd_round_start":
      if active_service is None and 0 < state.free_frames < params.F_low:
        candidates = state.select_candidates(params.K)
        batch = state.batch_size(state.free_frames, len(candidates))
        actual_b_t_values.append(batch)
        if batch:
          selected = candidates[:batch]
          state.reserve_inference(selected)
          active_service = ("inference", selected)
          queue.schedule(event.timestamp_ns + params.T_inference_ns,
                         "capd_inference_finish", {"page_ids": selected})
    elif event.kind == "capd_inference_finish":
      selected = list(event.payload["page_ids"])
      _require(active_service == ("inference", selected),
               "Inference completion does not match active batch.")
      active_service = None
      state.move_inference_to_normal(selected)
      pending_jobs.extend(("normal", page_id) for page_id in selected)
      start_next_migration(event.timestamp_ns)
    elif event.kind == "emergency_fallback":
      fallback_count += 1
      if not any(page == event.payload["page_id"]
                 for _, page in state.blocked_requests):
        raise Stage10ContractError("Fallback page/request identity mismatch.")
      releasable = len(pending_jobs)
      if active_service:
        releasable += (len(active_service[1])
                       if active_service[0] == "inference" else 1)
      candidates = state.select_candidates(params.K)
      if releasable < len(state.blocked_requests) and candidates:
        page_id = candidates[0]
        state.reserve_emergency_migration([page_id])
        pending_jobs.appendleft(("emergency", page_id))
        start_next_migration(event.timestamp_ns)
    elif event.kind == "demotion_finish":
      page_id = event.payload["page_id"]
      _require(active_service == ("migration", page_id),
               "Demotion completion does not match active migration.")
      state.finish_migration(page_id)
      state.release_resident_page(page_id)
      demotion_count += 1
      if state.blocked_requests:
        metrics.add_block(state.admit_oldest_blocked(event.timestamp_ns))
      active_service = None
      start_next_migration(event.timestamp_ns)
      if active_service is None:
        queue.schedule(event.timestamp_ns, "capd_round_start", {})
    else:
      raise Stage10ContractError("Unhandled event: " + event.kind)
    state.assert_invariants()
    metrics.observe_point(len(pending_jobs), state.free_frames)
    events.append({"timestamp_ns": event.timestamp_ns, "kind": event.kind,
                   "event_id": event.event_id,
                   "payload": dict(event.payload)})
  metrics.observe_interval(
      params.simulation_horizon_ns, len(pending_jobs), state.free_frames,
      background_active=active_service is not None)
  observed = metrics.as_dict()
  observed.update({
      "page_enter_dram_count": arrival_attempt_count,
      "demotion_finish_count": demotion_count,
      "emergency_fallback_count": fallback_count,
      "fallback_rate": (
          fallback_count / arrival_attempt_count
          if arrival_attempt_count else None),
      "unfinished_blocked_request_count": len(state.blocked_requests),
      "effective_demotion_rate": (
          demotion_count / (params.simulation_horizon_ns / 1_000_000_000)),
  })
  return SimulationResult(
      events=events,
      metrics=observed,
      derived={"actual_b_t_values": actual_b_t_values,
               "actual_b_t_distribution": [
                   {"b_t": value, "count": count}
                   for value, count in sorted(
                       Counter(actual_b_t_values).items())],
               "mu_demote_pages_per_ns_numerator":
                   mu_demote(params).numerator,
               "mu_demote_pages_per_ns_denominator":
                   mu_demote(params).denominator,
               "simulation_horizon_ns": params.simulation_horizon_ns,
               "T_inference_ns": params.T_inference_ns,
               "T_migration_ns": params.T_migration_ns,
               "b_max": params.b_max,
               "b_t_reference": params.b_t_reference,
               "seed": params.seed},
      interpretation={
          "scope": "deterministic_fixture_simulation_only",
          "real_linux_measurement_claimed": False,
          "kernel_behavior_claimed": False})
~~~

The production implementation may split handlers into private methods, but it must preserve this transition order: completed demotion clears its reservation and removes exactly one resident page, releases one frame, then admits the oldest blocked request into the MRU head, then starts the next serial job. Normal and emergency jobs share the same one-at-a-time service; emergency jobs wait at the head of pending work and never preempt active inference or migration. Every event ends with both capacity and reservation assertions.

- [ ] **Step 5: Verify the complete observed/derived/interpretation field contract**

Assert that `observed` contains `emergency_fallback_count`, `fallback_rate`, completed-blocking total/mean/P95/count, `minimum_free_frames`, full-window exhaustion duration, time-weighted queue mean/max/P95, `background_utilization`, page-entry and demotion counts, effective demotion rate, and unfinished blocked count. Assert that `derived` contains the horizon, seed, both timing inputs, `b_max`, `b_t_reference`, exact rational `mu_demote`, all actual `b_t` values and their count distribution, and runner-supplied arrival parameters. Keep blocking mean/P95 as JSON `null` when count is zero; report rendering in Task 7 prints `N/A`, never numeric zero. Assert that `interpretation` explicitly denies real Linux, kernel, CPU, and foreground end-to-end claims.

- [ ] **Step 6: Run simulation tests and inspect the invariant trace**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10SimulationTest -v
~~~

Expected: 5 tests PASS. Run the same simulation twice and compare serialized event/metric JSON byte-for-byte; any mismatch is a contract failure.

- [ ] **Step 7: Optional approved checkpoint commit**

~~~powershell
git add qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: implement Stage10A discrete-event simulation and metrics"
~~~

### Task 6: Implement The Fail-Closed Formal Stage9 Gate

**Files:**

- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write formal-gate tests against synthetic receipts**

Append:

~~~python
class Stage10FormalGateTest(unittest.TestCase):

  def test_stage9_r1_and_unverified_receipts_are_rejected(self):
    for receipt in (
        {"status": "stage9_not_verified", "run_id": "stage9-overhead-r1"},
        {"status": "stage9_overhead_verified", "run_id": "stage9-overhead-r1"},
        {"status": "stage9_implemented_awaiting_server_measurement",
         "run_id": "stage9-overhead-r2"},
    ):
      with self.subTest(receipt=receipt):
        result = stage10.check_formal_stage9_gate(receipt, {})
        self.assertEqual("stage10_formal_blocked_by_stage9", result["status"])
        self.assertFalse(result["formal_authorized"])

  def test_verified_receipt_requires_all_bindings(self):
    receipt = {
        "status": "stage9_overhead_verified",
        "run_id": "stage9-overhead-r2",
        "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
        "verification": {"cpu": True, "perf": True, "rss": True},
        "manifest_sha256": "a" * 64,
        "artifacts": {"manifest": {"sha256": "a" * 64}},
        "sha_chain_verified": True,
        "artifact_bindings_verified": True,
        "stage8_r5_tree_sha256":
            "554eba14afa57eab2e02aaa156f32181d29d4c66929a5fd2ca934e87c5cf49db"
    }
    result = stage10.check_formal_stage9_gate(receipt, {
        "stage8_r5_tree_sha256": receipt["stage8_r5_tree_sha256"]})
    self.assertTrue(result["formal_authorized"])
    receipt["artifact_bindings_verified"] = False
    self.assertFalse(stage10.check_formal_stage9_gate(
        receipt, {"stage8_r5_tree_sha256":
                  receipt["stage8_r5_tree_sha256"]})["formal_authorized"])

  def test_stage9_artifact_paths_and_hashes_are_verified(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
      artifacts = {}
      for name in ("run_state", "verification", "manifest", "sha256sums"):
        path = os.path.join(directory, name + ".json")
        with open(path, "w", encoding="utf-8") as handle:
          json.dump({"name": name}, handle)
        artifacts[name] = {
            "path": os.path.relpath(path, ROOT),
            "sha256": stage10.sha256_file(path)}
      receipt = {"artifacts": artifacts}
      verified = stage10.verify_stage9_artifact_bindings(ROOT, receipt)
      self.assertTrue(verified["artifact_bindings_verified"])
      with open(os.path.join(directory, "manifest.json"),
                "a", encoding="utf-8") as handle:
        handle.write("tamper")
      with self.assertRaises(stage10.Stage10ContractError):
        stage10.verify_stage9_artifact_bindings(ROOT, receipt)
~~~

- [ ] **Step 2: Run and confirm the gate helper is absent**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10FormalGateTest -v
~~~

Expected: FAIL because `check_formal_stage9_gate` is not defined.

- [ ] **Step 3: Implement receipt validation without Linux imports**

Add:

~~~python
import hashlib
import os


def check_formal_stage9_gate(receipt: Mapping[str, Any],
                             expected: Mapping[str, Any]) -> Mapping[str, Any]:
  reasons = []
  if receipt.get("status") != "stage9_overhead_verified":
    reasons.append("stage9 status is not verified")
  if receipt.get("run_id") == "stage9-overhead-r1":
    reasons.append("historical stage9-overhead-r1 is immutable failed evidence")
  if receipt.get("contract_id") != "CAPD-PROACTIVE-STAGE9-2.0":
    reasons.append("Stage9 v2 contract missing")
  verification = receipt.get("verification", {})
  for key in ("cpu", "perf", "rss"):
    if verification.get(key) is not True:
      reasons.append("missing verified " + key + " evidence")
  if (not isinstance(receipt.get("manifest_sha256"), str) or
      len(receipt["manifest_sha256"]) != 64):
    reasons.append("manifest SHA missing")
  elif (receipt.get("artifacts", {}).get("manifest", {}).get("sha256") !=
        receipt.get("manifest_sha256")):
    reasons.append("manifest receipt binding mismatch")
  if receipt.get("sha_chain_verified") is not True:
    reasons.append("SHA chain not verified")
  if receipt.get("artifact_bindings_verified") is not True:
    reasons.append("Stage9 artifact bindings not independently verified")
  if (receipt.get("stage8_r5_tree_sha256") !=
      expected.get("stage8_r5_tree_sha256")):
    reasons.append("Stage8 r5 authority binding mismatch")
  return {
      "status": ("stage10_formal_authorized" if not reasons
                 else "stage10_formal_blocked_by_stage9"),
      "formal_authorized": not reasons,
      "reasons": reasons,
  }


def sha256_file(path: str) -> str:
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def verify_stage9_artifact_bindings(
    project_root: str,
    receipt: Mapping[str, Any]) -> Mapping[str, Any]:
  required = {"run_state", "verification", "manifest", "sha256sums"}
  bindings = receipt.get("artifacts", {})
  _require(set(bindings) == required,
           "Stage9 receipt artifact set is incomplete.")
  root = os.path.realpath(project_root)
  for name in sorted(required):
    row = bindings[name]
    _require(isinstance(row, Mapping) and
             isinstance(row.get("path"), str) and
             isinstance(row.get("sha256"), str) and
             len(row["sha256"]) == 64,
             "Invalid Stage9 artifact binding: " + name)
    resolved = os.path.realpath(os.path.join(root, row["path"]))
    _require(os.path.commonpath((root, resolved)) == root,
             "Stage9 artifact escapes the repository: " + name)
    _require(os.path.isfile(resolved), "Missing Stage9 artifact: " + name)
    _require(sha256_file(resolved) == row["sha256"],
             "Stage9 artifact SHA mismatch: " + name)
  verified = dict(receipt)
  verified["artifact_bindings_verified"] = True
  return verified
~~~

Formal mode first calls `verify_stage9_artifact_bindings`, then checks the receipt fields. The runner must fail with a non-zero exit code before creating a run directory when `formal_authorized` is false. Fixture mode remains runnable and records the historical r1 rejection as evidence.

- [ ] **Step 4: Run formal-gate tests**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10FormalGateTest -v
~~~

Expected: 3 tests PASS, including rejection of every `stage9-overhead-r1` identity and independent detection of an artifact tamper.

- [ ] **Step 5: Optional approved checkpoint commit**

~~~powershell
git add qmap/proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: fail closed on incomplete Stage9 evidence"
~~~

### Task 7: Build The Fixture Runner, Reports, And Hash-Verified Artifacts

**Files:**

- Create: `scripts/run_capd_proactive_stage10.py`
- Modify: `qmap/proactive_stage10.py`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Write runner and artifact tests**

Append:

~~~python
class Stage10RunnerTest(unittest.TestCase):

  def _run_fixture(self, output):
    test_log = os.path.join(output, "source-test.log")
    with open(test_log, "w", encoding="utf-8") as handle:
      handle.write("synthetic integration test log\n")
    runner = os.path.join(ROOT, "scripts", "run_capd_proactive_stage10.py")
    return subprocess.run(
        [sys.executable, runner, "--config", CONFIG_PATH,
         "--mode", "fixture", "--output-root", output,
         "--run-id", "fixture-test", "--test-log-input", test_log],
        cwd=ROOT, capture_output=True, text=True, check=False)

  def test_fixture_runner_writes_candidate_ready_artifacts(self):
    with tempfile.TemporaryDirectory() as output:
      completed = self._run_fixture(output)
      self.assertEqual(0, completed.returncode, completed.stderr)
      run_root = os.path.join(output, "fixture-test")
      for name in ("config.json", "event_model.md", "parameters.md",
                   "fixture_results.jsonl", "test_log.txt", "formal_gate.json",
                   "verification.json", "run_state.json", "manifest.json",
                   "SHA256SUMS", "README.md"):
        self.assertTrue(os.path.isfile(os.path.join(run_root, name)), name)
      run_state = load_json(os.path.join(run_root, "run_state.json"))
      self.assertEqual("stage10_simulator_tests_passed",
                       run_state["status"])
      gate = load_json(os.path.join(run_root, "formal_gate.json"))
      self.assertEqual("stage10_formal_blocked_by_stage9", gate["status"])

  def test_manifest_and_sha256sums_recompute_independently(self):
    with tempfile.TemporaryDirectory() as output:
      completed = self._run_fixture(output)
      self.assertEqual(0, completed.returncode, completed.stderr)
      root = os.path.join(output, "fixture-test")
      manifest = load_json(os.path.join(root, "manifest.json"))
      self.assertNotIn("manifest.json", manifest["files"])
      self.assertNotIn("SHA256SUMS", manifest["files"])
      for name, digest in manifest["files"].items():
        self.assertEqual(
            digest, stage10.sha256_file(os.path.join(root, name)))
      with open(os.path.join(root, "SHA256SUMS"),
                encoding="utf-8") as handle:
        checksum_lines = [line.strip().split("  ", 1) for line in handle
                          if line.strip()]
      self.assertIn("manifest.json", [name for _, name in checksum_lines])
      self.assertNotIn("SHA256SUMS", [name for _, name in checksum_lines])
      for digest, name in checksum_lines:
        self.assertEqual(
            digest, stage10.sha256_file(os.path.join(root, name)))

  def test_n_a_is_used_only_for_empty_blocking_samples(self):
    report = stage10.render_report({
        "foreground_blocking_time_mean_ns": None,
        "foreground_blocking_time_p95_ns": None,
        "blocking_sample_count": 0})
    self.assertIn("N/A", report)
    self.assertNotIn("mean=0", report)
~~~

- [ ] **Step 2: Run runner tests and confirm the script is absent**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10RunnerTest -v
~~~

Expected: FAIL because the runner script and report/hash helpers do not exist.

- [ ] **Step 3: Implement CLI, scenario expansion, and artifact lifecycle**

The runner must:

1. Resolve the repository root from `__file__`, load and validate the config, and accept `--mode fixture|formal`, `--config`, `--output-root`, `--run-id`, `--test-log-input`, `--stage9-receipt`, and `--verify`.
2. Create a fresh run directory and reject an existing run ID rather than resume or overwrite.
3. Expand the four uniform scenarios and the multi-burst scenario, generate arrivals, call `run_simulation`, and write one canonical JSON object per line to `fixture_results.jsonl`.
4. Write `event_model.md` and `parameters.md` with integer units, the event priority table, `b_t` versus `b_t_reference`, MRU admission semantics, and the exhaustion integral definition.
5. Render human reports with `N/A` for null blocking mean/P95.
6. In fixture mode, read and hash-check the configured historical Stage9 r1 `run_state.json`, then write the rejection to `formal_gate.json`. In formal mode, require `--stage9-receipt` and validate that new receipt before creating a run directory.
7. Copy the supplied unit-test log to `test_log.txt`; write `run_state.json` with `stage10_simulator_tests_passed`, and set explicit booleans `stage10_simulator_implemented=true`, `stage10_simulator_tests_passed=true`, `stage10_formal_blocked_by_stage9=true`, `stage10_formally_verified=false`.
8. Write `verification.json` after independently recomputing selected metric fields and event counts.
9. Hash all payload files except `manifest.json` and `SHA256SUMS` into `manifest.json`; then hash every file except `SHA256SUMS` into `SHA256SUMS`. Recompute both lists before returning success.

Use atomic UTF-8 writes and stable JSON serialization:

~~~python
def write_json(path, value):
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  temporary = path + ".tmp"
  with open(temporary, "w", encoding="utf-8", newline="") as handle:
    json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
  os.replace(temporary, path)


def render_report(observed):
  def value(name):
    item = observed.get(name)
    return "N/A" if item is None else str(item)
  return "\n".join([
      "blocking_sample_count=" + value("blocking_sample_count"),
      "foreground_blocking_time_mean_ns=" +
          value("foreground_blocking_time_mean_ns"),
      "foreground_blocking_time_p95_ns=" +
          value("foreground_blocking_time_p95_ns"),
  ]) + "\n"
~~~

Place `render_report` in `qmap/proactive_stage10.py` beside the Task 6 `sha256_file` helper so tests and the runner share pure implementations. The CLI must return non-zero for `--mode formal` when the Stage9 gate is blocked and must not create a formal result or run directory. It must never read Test data to choose parameters.

- [ ] **Step 4: Run the complete Stage10 test module and the fixture runner**

Run:

~~~powershell
$testLog = 'tmp/stage10-unit-tests.log'
python -m unittest tests.test_capd_proactive_stage10 -v 2>&1 | Tee-Object -FilePath $testLog
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/run_capd_proactive_stage10.py --config configs/finals/capd_proactive_stage10.json --mode fixture --test-log-input $testLog --output-root outputs/capd_proactive_stage10 --run-id stage10-async-simulator-r1
~~~

Expected: all Stage10 tests PASS; runner exits 0; run state is `stage10_simulator_tests_passed`; formal gate is `stage10_formal_blocked_by_stage9`; no formal result file exists.

- [ ] **Step 5: Independently verify artifacts and frozen evidence**

Run:

~~~powershell
python -c "from scripts import run_capd_proactive_stage10 as r; r.verify_run('outputs/capd_proactive_stage10/stage10-async-simulator-r1')"
git diff --check
git status --short -- outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit outputs/capd_proactive_stage9/stage9-overhead-r1
$frozenRoots = @(
  'outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit',
  'outputs/capd_proactive_stage9/stage9-overhead-r1'
)
$afterRows = foreach ($rootName in $frozenRoots) {
  $resolvedRoot = (Resolve-Path -LiteralPath $rootName).Path
  Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
      [ordered]@{
        root = $rootName
        relative_path = $_.FullName.Substring($resolvedRoot.Length + 1).Replace('\', '/')
        length = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower()
      }
    }
}
$beforeJson = (Get-Content -Raw -LiteralPath 'tmp/stage10-frozen-before.json').Trim()
$afterJson = ($afterRows | ConvertTo-Json -Depth 3).Trim()
if ($beforeJson -ne $afterJson) { throw 'Frozen Stage8/Stage9 tree changed' }
~~~

The independent verifier must recompute manifest and `SHA256SUMS`, selected metrics, and result-schema fields. The frozen-tree status command must be empty and the file-by-file before/after snapshots must match exactly. The approved design's recorded Stage8 r5 and Stage9 r1 tree digests remain `554eba14...49db` and `805c73bf...a7b`; any observed content difference stops the handoff.

- [ ] **Step 6: Optional approved checkpoint commit**

~~~powershell
git add scripts/run_capd_proactive_stage10.py tests/test_capd_proactive_stage10.py
git commit -m "feat: add Stage10A fixture runner and verified artifacts"
~~~

### Task 8: Write Protocol, Status, Server Handoff, And Final Verification

**Files:**

- Create: `docs/CAPD_PROACTIVE_STAGE10_PROTOCOL_CN.md`
- Create: `docs/CAPD_PROACTIVE_STAGE10_STATUS_CN.md`
- Create: `docs/CAPD_PROACTIVE_STAGE10_SERVER_CN.md`
- Modify: `tests/test_capd_proactive_stage10.py`

- [ ] **Step 1: Add documentation contract tests**

Append:

~~~python
class Stage10DocumentationTest(unittest.TestCase):

  def test_docs_state_candidate_ready_and_formal_blocked(self):
    status_path = os.path.join(ROOT, "docs", "CAPD_PROACTIVE_STAGE10_STATUS_CN.md")
    server_path = os.path.join(ROOT, "docs", "CAPD_PROACTIVE_STAGE10_SERVER_CN.md")
    with open(status_path, encoding="utf-8") as handle:
      status = handle.read()
    with open(server_path, encoding="utf-8") as handle:
      server = handle.read()
    self.assertIn("candidate-ready", status)
    self.assertIn("stage10_formal_blocked_by_stage9", status)
    self.assertIn("stage9_overhead_verified", server)
    self.assertIn("stage9-overhead-r1", server)
    self.assertNotIn("STAGE10_FORMALLY_VERIFIED", status)
~~~

- [ ] **Step 2: Write the Chinese protocol document**

Document, with no claim of real Linux behavior:

- integer nanoseconds and heap key `(timestamp_ns,event_priority,event_id)`;
- exact priority order;
- initial resident count, IDs, MRU-to-LRU order, and `candidate_source=lru_tail`;
- unified `reserved_page_ids`, disjointness, and duplicate scheduling assertion;
- serial `idle -> inference -> migration -> idle` service;
- normal and emergency work ordering;
- immediate and unblocked admission both inserting at the MRU head;
- default parameterized uniform and burst arrivals;
- reliable timestamp Trace replay as a future input option only;
- `mu_demote` from `b_t_reference`, with actual per-round `b_t` recorded;
- null/P95 semantics and report `N/A`;
- `free_frame_exhaustion_duration` as the integral of `F_t=0` over `[0, simulation_horizon]`.

- [ ] **Step 3: Write the status document**

State exactly:

- simulator implemented and local tests passed;
- fixture output is candidate-ready, not formal;
- formal Stage10 is blocked by absent verified Stage9 v2 evidence;
- Stage8 r5 and Stage9 r1 are immutable;
- no Stage9 rerun, CPU/perf/RSS estimate, or Test tuning was performed;
- the next gate is a Stage9-owned receipt with status `stage9_overhead_verified`, complete Linux CPU/perf/RSS evidence, manifest/verification/SHA chain, and Stage8 r5 bindings.

- [ ] **Step 4: Write copyable but non-executed server handoff commands**

Include commands for a future Linux host:

~~~bash
set -o pipefail
export STAGE9_RECEIPT
test -n "$STAGE9_RECEIPT"
mkdir -p logs
python3 scripts/run_capd_proactive_stage10.py \
  --config configs/finals/capd_proactive_stage10.json \
  --mode formal \
  --stage9-receipt "$STAGE9_RECEIPT" \
  --output-root outputs/capd_proactive_stage10 \
  --run-id stage10-async-simulator-r1-linux \
  2>&1 | tee logs/stage10-async-simulator-r1-linux.log
python3 scripts/run_capd_proactive_stage10.py \
  --verify outputs/capd_proactive_stage10/stage10-async-simulator-r1-linux
~~~

Define `STAGE9_RECEIPT` as a required environment input pointing to a new verified Stage9 v2 receipt. State that these commands have not run and that the current repository's Stage9 r1 path must be rejected.

- [ ] **Step 5: Run documentation and full verification commands**

Run:

~~~powershell
python -m unittest tests.test_capd_proactive_stage10 -v
python scripts/run_capd_proactive_stage10.py --verify outputs/capd_proactive_stage10/stage10-async-simulator-r1
git diff --check
$forbiddenTerms = @('T' + 'ODO', 'T' + 'BD', 'FIX' + 'ME')
Get-Content -LiteralPath 'docs/superpowers/plans/2026-08-05-stage10-async-simulator.md' | Select-String -Pattern $forbiddenTerms
Get-Content -LiteralPath 'docs/superpowers/plans/2026-08-05-stage10-async-simulator.md' | Select-String -Pattern ('^\s*' + 'pass' + '\s*$')
~~~

Expected: all Stage10 tests PASS; independent verification exits 0; `git diff --check` is clean for tracked edits; the forbidden-term scan returns no lines. Because the plan is untracked at this point, additionally run a direct whitespace check:

~~~powershell
$planPath = (Resolve-Path 'docs/superpowers/plans/2026-08-05-stage10-async-simulator.md').Path
$bytes = [System.IO.File]::ReadAllBytes($planPath)
if ($bytes[-1] -ne 10) { throw 'plan must end with LF' }
if ((Get-Content -Raw -LiteralPath $planPath) -match '(?m)[ \t]+$') { throw 'trailing whitespace' }
if ((Get-Content -Raw -LiteralPath $planPath) -match '(?m)^\t') { throw 'tab-indented line' }
~~~

- [ ] **Step 6: Perform the final scope audit before handoff**

Confirm with `git status --short` that only intended new/modified Stage10 files are present, verify neither frozen output tree changed, verify every fixture result carries `mode=fixture`, and verify no artifact claims `stage10_formally_verified=true`. Do not change the design status again after this audit.

- [ ] **Step 7: Optional approved checkpoint commit**

~~~powershell
git add docs/CAPD_PROACTIVE_STAGE10_PROTOCOL_CN.md docs/CAPD_PROACTIVE_STAGE10_STATUS_CN.md docs/CAPD_PROACTIVE_STAGE10_SERVER_CN.md tests/test_capd_proactive_stage10.py
git commit -m "docs: document Stage10A candidate and formal boundary"
~~~

## Final Acceptance Gate

The implementation is accepted only when all of the following are true:

1. `python -m unittest tests.test_capd_proactive_stage10 -v` passes.
2. The fixture runner produces the complete candidate directory and independent manifest/SHA/metric verification passes.
3. Same-time ordering, reservation disjointness, capacity invariants, deterministic LRU-tail selection, MRU insertion, uniform/burst reproducibility, null/N/A blocking semantics, and full-window exhaustion integration are covered by tests.
4. Formal mode rejects absent/unverified Stage9 receipts, explicitly rejects `stage9-overhead-r1`, and writes no formal result.
5. Stage8 r5 and Stage9 r1 tree hashes remain unchanged.
6. The resulting status is `candidate-ready`, with `stage10_formal_blocked_by_stage9=true` and `stage10_formally_verified=false`.

Plan complete and saved to `docs/superpowers/plans/2026-08-05-stage10-async-simulator.md`. Two execution options:

1. Subagent-Driven (recommended): dispatch a fresh subagent per task with review checkpoints.
2. Inline Execution: execute tasks in this session using the executing-plans skill with checkpoints.

The user must approve the plan and choose one execution option before implementation begins.
