"""Deterministic CAPD Stage10A discrete-event simulator."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import csv
from collections import Counter, deque
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Deque, List, Mapping, Set


SCHEMA_VERSION = "capd_proactive_stage10_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE10-1.0"
FIXTURE = "fixture"
FORMAL_BLOCKED = "stage10_formal_blocked_by_stage9"
ALLOWED_ARRIVAL_MODELS = ("uniform", "burst")
EVENT_PRIORITY = {
    "demotion_finish": 0,
    "capd_inference_finish": 1,
    "capd_round_start": 2,
    "emergency_fallback": 3,
    "page_enter_dram": 4,
}


class Stage10ContractError(ValueError):
    """Raised when Stage10 input, state, or evidence violates the contract."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise Stage10ContractError(message)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_value(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def render_report(observed: Mapping[str, Any]) -> str:
    def value(name: str) -> str:
        item = observed.get(name)
        return "N/A" if item is None else str(item)
    return "\n".join([
        "blocking_sample_count=" + value("blocking_sample_count"),
        "foreground_blocking_time_mean=" +
        value("foreground_blocking_time_mean"),
        "foreground_blocking_time_p95=" +
        value("foreground_blocking_time_p95"),
    ]) + "\n"


def validate_test_log(path: str, expected_sha256: str,
                      evidence_contract: Mapping[str, Any]) -> Mapping[str, Any]:
    if not os.path.isfile(path):
        raise Stage10ContractError("Test log is missing.")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", expected_sha256):
        raise Stage10ContractError("Test-log SHA256 argument is invalid.")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256.lower():
        raise Stage10ContractError("Test-log SHA256 mismatch.")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read().lstrip("\ufeff")
    lines = [line.rstrip("\r") for line in text.splitlines()]
    command_lines = [line[len("COMMAND:"):].strip()
                     for line in lines if line.startswith("COMMAND:")]
    if len(command_lines) != 1:
        raise Stage10ContractError("Test log must contain one COMMAND line.")
    command = command_lines[0]
    expected_commands = evidence_contract.get("expected_commands", ())
    if not isinstance(expected_commands, list) or command not in expected_commands:
        raise Stage10ContractError("Test command identity is invalid.")
    matches = re.findall(r"(?m)^Ran\s+(\d+)\s+tests?\b", text)
    if len(matches) != 1:
        raise Stage10ContractError("Test log must contain one Ran N tests line.")
    test_count = int(matches[0])
    if test_count < evidence_contract["minimum_test_count"]:
        raise Stage10ContractError("Test count is below the configured minimum.")
    result_lines = [line.strip() for line in lines
                    if re.match(r"^test_\S.*\.\.\.\s+ok$", line.strip())]
    if len(result_lines) != test_count:
        raise Stage10ContractError("Verbose test result count does not match.")
    nonempty = [line.strip() for line in lines if line.strip()]
    if not nonempty or nonempty[-1] != "OK":
        raise Stage10ContractError("Test log does not end in OK.")
    if any(line in ("FAILED", "ERROR") or line.startswith("FAILED (") or
           line.startswith("ERROR (") for line in nonempty):
        raise Stage10ContractError("Test log contains a failure status.")
    return {
        "sha256": actual_sha256,
        "command": command,
        "module": evidence_contract["required_module"],
        "test_count": test_count,
        "result_line_count": len(result_lines),
        "final_status": "OK",
    }


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Stage10 config must be an object.")
    _require(value.get("schema_version") == SCHEMA_VERSION,
             "Stage10 schema mismatch.")
    _require(value.get("contract_id") == CONTRACT_ID,
             "Stage10 contract mismatch.")
    _require(value.get("result_schema") ==
             "configs/finals/capd_proactive_stage10_result_schema.json" and
             isinstance(value.get("result_schema_sha256"), str) and
             re.fullmatch(r"[0-9a-f]{64}", value["result_schema_sha256"]) is not None,
             "Stage10 result-schema binding is missing.")
    _require(value.get("mode") == FIXTURE, "Repository config must be fixture.")
    _require(value.get("candidate_source") == "lru_tail",
             "Stage10 candidate source changed.")
    _require(value.get("arrival_models") == list(ALLOWED_ARRIVAL_MODELS),
             "Stage10A supports uniform and burst arrivals only.")
    _require(value.get("trace_replay") == {
        "enabled": False,
        "status": "future_input_option_requires_reliable_timestamps"},
        "Trace replay must remain disabled.")
    test_evidence = value.get("test_evidence", {})
    _require(test_evidence.get("required_command_tokens") ==
             ["-m", "unittest"] and
             test_evidence.get("required_module") ==
             "tests.test_capd_proactive_stage10" and
             test_evidence.get("expected_command") ==
             "python -m unittest tests.test_capd_proactive_stage10 -v" and
             test_evidence.get("expected_commands") == [
                 "python -m unittest tests.test_capd_proactive_stage10 -v",
                 "python -m unittest "
                 "tests.test_capd_proactive_stage10.Stage10ConfigContractTest "
                 "tests.test_capd_proactive_stage10.Stage10EventHeapTest "
                 "tests.test_capd_proactive_stage10.Stage10StateContractTest "
                 "tests.test_capd_proactive_stage10.Stage10ArrivalTest "
                 "tests.test_capd_proactive_stage10.Stage10SimulationTest "
                 "tests.test_capd_proactive_stage10.Stage10FormalGateTest -v"] and
             isinstance(test_evidence.get("minimum_test_count"), int) and
             test_evidence["minimum_test_count"] >= 10,
             "Test evidence identity/count contract is missing.")
    formal_gate = value.get("formal_gate", {})
    expected_stage9_files = [
        "run_identity.json", "resolved_config.json",
        "stage8_compatibility_receipt.json", "preflight.json",
        "environment.json", "raw_latency_samples.csv", "latency_summary.json",
        "throughput_summary.json", "quality_summary.json",
        "instrumentation_audit.json", "perf/perf-stat.raw",
        "perf/perf_parsed.json", "perf/perf_scope_counts.json",
        "memory_breakdown.json", "capacity_overhead.csv",
        "artifacts/report_cn.md", "logs/stage1_stage9_regression.log",
        "server_test_receipt.json", "verification.json", "run_state.json"]
    expected_stage9_verification = {
        "schema_version": "capd_proactive_stage9_verification_v2_0",
        "status": "stage9_overhead_verified",
        "stage10_entry_gate": "satisfied", "stage8_entry_gate": "satisfied",
        "device": "cpu", "linux_measurement": True,
        "perf_cycles_verified": True, "memory_verified": True,
        "raw_to_summary_verified": True,
        "instrumentation_semantics_verified": True,
        "stage8_compatibility_receipt_verified": True,
        "test_used_for_parameter_selection": False, "formal_b_max": 2,
        "b_max_sensitivity_purpose": "analysis_only_not_selection",
        "stage8_artifacts_overwritten": False,
        "fair_capacity_replay_status": "deferred"}
    _require(formal_gate.get("required_stage9_contract_id") ==
             "CAPD-PROACTIVE-STAGE9-2.0" and
             formal_gate.get("required_stage9_status") ==
             "stage9_overhead_verified" and
             formal_gate.get("stage9_config_path") ==
             "configs/finals/capd_proactive_stage9.json" and
             formal_gate.get("stage9_config_sha256") ==
             "4fbbe7fe17f3ef10a9f04c83960901837f0dcda513d843c27b9d8e888ce2c1a7" and
             formal_gate.get("stage9_output_root") ==
             "outputs/capd_proactive_stage9" and
             formal_gate.get("rejected_run_ids") == ["stage9-overhead-r1"] and
             formal_gate.get("stage9_required_files") == expected_stage9_files and
             formal_gate.get("stage9_verification_required") ==
             expected_stage9_verification and
             formal_gate.get("stage8_r5_verification_sha256") ==
             "b531f7324af9a6edf7dc31adc1426782c2389be35fd4b6058aa1986764e8025b" and
             formal_gate.get("stage8_r5_tree_sha256") ==
             "554eba14afa57eab2e02aaa156f32181d29d4c66929a5fd2ca934e87c5cf49db",
             "Stage9 formal gate contract is missing or weakened.")
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
        integer_fields = (
            "T_inference_ns", "T_migration_ns", "b_max", "b_t_reference",
            "dram_capacity_frames", "initial_free_frames", "F_low",
            "F_target", "K", "simulation_horizon_ns", "seed")
        _require(all(isinstance(getattr(self, name), int) and
                     not isinstance(getattr(self, name), bool)
                     for name in integer_fields),
                 "Simulator parameters must be integers.")
        _require(self.seed >= 0, "Seed must be non-negative.")
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
        _require(kind in ("normal", "emergency"),
                 "Unknown migration job kind.")
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
        _require(isinstance(limit, int) and limit >= 0,
                 "Candidate limit must be non-negative.")
        candidates = [page for page in reversed(self.lru_mru_to_lru)
                      if page not in self.reserved_page_ids]
        return candidates[:limit]

    def batch_size(self, free_frames: int, candidate_count: int) -> int:
        _require(free_frames >= 0 and candidate_count >= 0,
                 "Batch inputs must be non-negative.")
        return min(self.config.b_max,
                   self.config.F_target - free_frames,
                   candidate_count)

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
    _require(isinstance(horizon_ns, int) and horizon_ns >= 0,
             "Arrival horizon must be a non-negative integer.")
    period = _period_ns(params, load_ratio)
    result = []
    index = 0
    first_page_id = params.dram_capacity_frames - params.initial_free_frames
    while True:
        timestamp = int(period * index)
        if timestamp > horizon_ns:
            break
        result.append(Arrival(timestamp, first_page_id + index))
        index += 1
    return result


def generate_burst_arrivals(params: SimulatorConfig,
                            bursts: List[Mapping[str, Any]],
                            base_load_ratio: str,
                            horizon_ns: int) -> List[Arrival]:
    _require(isinstance(horizon_ns, int) and horizon_ns >= 0,
             "Arrival horizon must be a non-negative integer.")
    ordered = sorted(bursts, key=lambda row: row["start_ns"])
    for previous, current in zip(ordered, ordered[1:]):
        _require(previous["start_ns"] + previous["duration_ns"] <=
                 current["start_ns"], "Burst intervals must not overlap.")
    for burst in ordered:
        start = burst["start_ns"]
        duration = burst["duration_ns"]
        _require(isinstance(start, int) and isinstance(duration, int) and
                 start >= 0 and duration > 0 and start + duration <= horizon_ns,
                 "Burst interval must be within the simulation horizon.")
        _require(Fraction(str(burst["multiplier"])) > 0,
                 "Burst multiplier must be positive.")

    base = Fraction(str(base_load_ratio))
    _require(base > 0, "Base arrival rate must be positive.")
    segments = []
    cursor = 0
    for index, burst in enumerate(ordered):
        start = burst["start_ns"]
        end = start + burst["duration_ns"]
        if cursor < start:
            segments.append((cursor, start, base, index * 2))
        segments.append((start, end,
                         base * Fraction(str(burst["multiplier"])), index * 2 + 1))
        cursor = end
    if cursor < horizon_ns:
        segments.append((cursor, horizon_ns, base, len(ordered) * 2))

    timestamps = []
    for start, end, ratio, segment_index in segments:
        period = _period_ns(params, str(ratio))
        period_ceiling = ((period.numerator + period.denominator - 1) //
                          period.denominator)
        phase = ((params.seed ^ start ^ end ^ segment_index) %
                 max(1, period_ceiling))
        index = 0
        while start + phase + int(period * index) < end:
            timestamps.append(start + phase + int(period * index))
            index += 1

    first_page_id = params.dram_capacity_frames - params.initial_free_frames
    return [Arrival(timestamp, first_page_id + index)
            for index, timestamp in enumerate(sorted(timestamps))]


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


@dataclass
class SimulationResult:
    events: List[Mapping[str, Any]]
    metrics: Mapping[str, Any]
    derived: Mapping[str, Any]
    interpretation: Mapping[str, Any]


def _percentile(values: List[int], percentile: int) -> int | None:
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
            "foreground_blocking_time_total": self.blocking_total_ns,
            "foreground_blocking_time_mean": mean,
            "foreground_blocking_time_p95":
                _percentile(self.blocking_durations, 95),
            "blocking_sample_count": count,
            "free_frame_exhaustion_duration": self.exhaustion_ns,
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


def run_simulation(params: SimulatorConfig,
                   arrivals: List[Arrival]) -> SimulationResult:
    state = SimulatorState(params)
    queue = EventQueue()
    metrics = _MetricAccumulator(params.simulation_horizon_ns)
    events = []
    for arrival in arrivals:
        _require(isinstance(arrival.timestamp_ns, int) and
                 0 <= arrival.timestamp_ns <= params.simulation_horizon_ns,
                 "Arrival timestamp is outside the simulation horizon.")
    ordered_arrivals = sorted(
        arrivals, key=lambda item: (item.timestamp_ns, item.page_id))
    first_page_id = state.initial_resident_count
    _require([item.page_id for item in ordered_arrivals] ==
             list(range(first_page_id, first_page_id + len(ordered_arrivals))),
             "Arrival page IDs must be contiguous and unique.")
    for arrival in ordered_arrivals:
        queue.schedule(arrival.timestamp_ns, "page_enter_dram",
                       {"page_id": arrival.page_id})
    active_service = None
    pending_jobs = deque()
    actual_b_t_values = []
    fallback_count = 0
    arrival_attempt_count = 0
    demotion_count = 0
    next_batch_id = 1

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
            current_batch_id = next_batch_id
            next_batch_id += 1
            if active_service is None and 0 < state.free_frames < params.F_low:
                candidates = state.select_candidates(params.K)
                batch = state.batch_size(state.free_frames, len(candidates))
                actual_b_t_values.append(batch)
                if batch:
                    selected = candidates[:batch]
                    state.reserve_inference(selected)
                    active_service = ("inference", selected)
                    queue.schedule(event.timestamp_ns + params.T_inference_ns,
                                   "capd_inference_finish",
                                   {"page_ids": selected,
                                    "batch_id": current_batch_id})
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
        event_payload = dict(event.payload)
        if event.kind == "capd_round_start":
            event_payload["batch_id"] = current_batch_id
        if event.kind == "emergency_fallback":
            blocked_at = next(
                start for start, page in state.blocked_requests
                if page == event.payload["page_id"])
            event_payload.update({
                "free_frames": state.free_frames,
                "background_queue_length": len(pending_jobs),
                "blocked_start_ns": blocked_at})
        events.append({"timestamp_ns": event.timestamp_ns, "kind": event.kind,
                       "event_id": event.event_id, "payload": event_payload})
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
                 "mu_demote": str(mu_demote(params)),
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


def _read_json_if_present(path: str):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def audit_stage9_run(project_root: str, stage9_run_root: str,
                     gate: Mapping[str, Any]) -> Mapping[str, Any]:
    reasons = []
    project_root = os.path.realpath(project_root)
    run_root = os.path.realpath(stage9_run_root)
    try:
        inside = os.path.commonpath((project_root, run_root)) == project_root
    except ValueError:
        inside = False
    if not inside or not os.path.isdir(run_root):
        reasons.append("Stage9 run directory is outside the repository or missing")
    expected_output_root = os.path.realpath(os.path.join(
        project_root, gate.get("stage9_output_root", "")))
    if os.path.dirname(run_root) != expected_output_root:
        reasons.append("Stage9 run directory is not a direct child of the trusted output root")
    stage9_config = None
    stage9_config_path = os.path.join(project_root,
                                      gate.get("stage9_config_path", ""))
    if (not os.path.isfile(stage9_config_path) or
            sha256_file(stage9_config_path) != gate.get("stage9_config_sha256")):
        reasons.append("Trusted Stage9 config binding is unavailable or changed")
    else:
        stage9_config = _read_json_if_present(stage9_config_path)
        if (not isinstance(stage9_config, Mapping) or
                stage9_config.get("contract_id") != gate.get("required_stage9_contract_id") or
                stage9_config.get("schema_version") != "capd_proactive_stage9_v2_0"):
            reasons.append("Trusted Stage9 config contract is invalid")
    run_id = os.path.basename(run_root)
    if run_id in gate.get("rejected_run_ids", ()):
        reasons.append("historical stage9-overhead-r1 is immutable failed evidence")
        reasons.append("stage9_overhead_verified status cannot authorize historical evidence")

    required = tuple(gate["stage9_required_files"])
    paths = {relative: os.path.join(run_root, relative)
             for relative in required}
    missing = [relative for relative, path in paths.items()
               if not os.path.isfile(path)]
    if missing:
        reasons.append("Stage9 required files missing: " + ",".join(missing))

    state = _read_json_if_present(paths["run_state.json"])
    if not isinstance(state, Mapping):
        reasons.append("Stage9 run_state.json is unavailable")
    else:
        if state.get("schema_version") != "capd_proactive_stage9_run_state_v2_0":
            reasons.append("Stage9 run_state schema is not v2")
        if state.get("contract_id") != gate["required_stage9_contract_id"]:
            reasons.append("Stage9 run_state contract is not v2")
        if state.get("status") != gate["required_stage9_status"]:
            reasons.append("Stage9 run_state status is not verified")
        if state.get("stage10_entry_gate") != "satisfied":
            reasons.append("Stage9 run_state Stage10 gate is not satisfied")
        if state.get("failure") is not None:
            reasons.append("Stage9 run_state contains a failure record")
        completed = set(state.get("completed", ()))
        if not {"perf_cycles", "independent_verification"} <= completed:
            reasons.append("Stage9 run_state lacks completed verification steps")

    identity = _read_json_if_present(os.path.join(run_root, "run_identity.json"))
    if not isinstance(identity, Mapping):
        reasons.append("Stage9 run_identity.json is unavailable")
    elif isinstance(stage9_config, Mapping):
        expected_schema = os.path.join(project_root, stage9_config.get("result_schema", ""))
        expected_stage8 = {
            name: row.get("sha256") for name, row in
            stage9_config.get("stage8_authority", {}).items()
            if isinstance(row, Mapping)}
        expected_stage4 = {
            name: row.get("sha256") for name, row in
            stage9_config.get("stage4_authority", {}).items()
            if isinstance(row, Mapping)}
        identity_checks = {
            "schema_version": "capd_proactive_stage9_run_identity_v2_0",
            "contract_id": gate.get("required_stage9_contract_id"),
            "run_id": run_id,
            "config_sha256": gate.get("stage9_config_sha256"),
            "result_schema_sha256": (
                sha256_file(expected_schema) if os.path.isfile(expected_schema) else None),
            "device": "cpu", "formal_b_max": 2,
            "sensitivity_b_max": [1, 2, 4],
            "test_used_for_parameter_selection": False,
        }
        for key, expected in identity_checks.items():
            if identity.get(key) != expected:
                reasons.append("Stage9 run_identity field mismatch: " + key)
        if identity.get("stage8_authority_sha256") != expected_stage8:
            reasons.append("Stage9 run_identity Stage8 authority binding mismatch")
        if identity.get("stage4_authority_sha256") != expected_stage4:
            reasons.append("Stage9 run_identity Stage4 authority binding mismatch")
        recorded_identity_hash = identity.get("run_identity_sha256")
        unhashed_identity = dict(identity)
        unhashed_identity.pop("run_identity_sha256", None)
        if (not isinstance(recorded_identity_hash, str) or
                fingerprint_value(unhashed_identity) != recorded_identity_hash):
            reasons.append("Stage9 run_identity_sha256 is invalid")

    resolved_config = _read_json_if_present(paths["resolved_config.json"])
    if isinstance(stage9_config, Mapping):
        if not isinstance(resolved_config, Mapping):
            reasons.append("Stage9 resolved_config.json is unavailable")
        else:
            for key in ("schema_version", "contract_id", "result_schema",
                        "result_schema_sha256", "output_root"):
                if resolved_config.get(key) != stage9_config.get(key):
                    reasons.append("Stage9 resolved_config field mismatch: " + key)
            if resolved_config.get("run_id") != run_id:
                reasons.append("Stage9 resolved_config run_id mismatch")
            if (not isinstance(identity, Mapping) or
                    resolved_config.get("run_identity_sha256") !=
                    identity.get("run_identity_sha256") or
                    resolved_config.get("config_sha256") != gate.get("stage9_config_sha256")):
                reasons.append("Stage9 resolved_config identity binding mismatch")

    preflight = _read_json_if_present(paths["preflight.json"])
    if isinstance(preflight, Mapping):
        for key, expected in {"schema_version": "capd_proactive_stage9_preflight_v2_0",
                              "contract_id": gate.get("required_stage9_contract_id"),
                              "status": "passed", "stage8_stage9_entry_gate": "satisfied",
                              "stage8_formal_job_count": 80,
                              "stage8_artifacts_read_only": True,
                              "test_used_for_parameter_selection": False,
                              "device": "cpu"}.items():
            if preflight.get(key) != expected:
                reasons.append("Stage9 preflight field mismatch: " + key)
    else:
        reasons.append("Stage9 preflight.json is unavailable")

    verification = _read_json_if_present(paths["verification.json"])
    expected_verification = gate["stage9_verification_required"]
    if not isinstance(verification, Mapping):
        reasons.append("Stage9 verification.json is unavailable")
    else:
        if verification.get("contract_id") != gate["required_stage9_contract_id"]:
            reasons.append("Stage9 verification contract is not v2")
        for key, expected in expected_verification.items():
            if verification.get(key) != expected:
                reasons.append("Stage9 verification field mismatch: " + key)
        if (verification.get("stage8_verification_sha256") !=
                gate["stage8_r5_verification_sha256"]):
            reasons.append("Stage8 r5 verification binding mismatch")
        if (not isinstance(identity, Mapping) or
                verification.get("run_identity_sha256") !=
                identity.get("run_identity_sha256")):
            reasons.append("Stage9 verification identity binding mismatch")
        if (isinstance(stage9_config, Mapping) and
                verification.get("interpretation_boundary") !=
                stage9_config.get("interpretation_boundary")):
            reasons.append("Stage9 verification interpretation boundary mismatch")

    compatibility = _read_json_if_present(
        paths["stage8_compatibility_receipt.json"])
    compatibility_requirements = {
        "stage9_entry_gate": "satisfied",
        "formal_job_count": 80,
        "standard_job_count": 48,
        "pressure_job_count": 32,
        "capd_job_count": 30,
        "track_workload_cell_count": 10,
        "fairness": "passed",
        "job_results_verified": True,
        "statistics_verified": True,
        "test_used_for_parameter_selection": False,
        "stage4_sha_chain_verified": True,
        "stage8_run_state_verified": True,
        "stage8_artifacts_read_only": True,
    }
    if not isinstance(compatibility, Mapping):
        reasons.append("Stage8 compatibility receipt is unavailable")
    else:
        for key, expected in compatibility_requirements.items():
            if compatibility.get(key) != expected:
                reasons.append("Stage8 compatibility field mismatch: " + key)

    observed_hashes = {}
    expected_hashes = (verification.get("artifact_sha256", {})
                       if isinstance(verification, Mapping) else {})
    expected_hashed = set(required) - {"verification.json", "run_state.json"}
    if not isinstance(expected_hashes, Mapping):
        reasons.append("Stage9 artifact_sha256 is not an object")
        expected_hashes = {}
    if set(expected_hashes) != expected_hashed:
        reasons.append("Stage9 artifact_sha256 key set is incomplete")
    for relative, path in paths.items():
        if os.path.isfile(path):
            digest = sha256_file(path)
            observed_hashes[relative] = digest
            if relative in expected_hashed and expected_hashes.get(relative) != digest:
                reasons.append("Stage9 artifact SHA mismatch: " + relative)

    # Reject empty placeholder evidence before the Stage10 gate. The full
    # Stage9 verifier remains authoritative for recomputing measurements, but
    # these structural checks prevent a forged directory of `{}` payloads.
    json_requirements = {
        "environment.json": ("schema_version", "contract_id", "system",
                              "device", "runtime_binding"),
        "latency_summary.json": ("by_b_max", "applicability"),
        "throughput_summary.json": ("by_b_max", "applicability"),
        "quality_summary.json": ("rows", "by_b_max", "purpose"),
        "instrumentation_audit.json": ("schema_version", "formal_b_max",
                                        "job_count", "status", "jobs"),
        "perf/perf_parsed.json": ("required_events_verified", "events",
                                   "counter_source"),
        "perf/perf_scope_counts.json": ("snapshot_count", "measured_job_ids",
                                         "measured_rounds", "measured_demoted_pages"),
        "memory_breakdown.json": ("model_parameters", "rss",
                                   "management_fixed_bytes"),
        "server_test_receipt.json": ("schema_version", "contract_id", "status",
                                      "test_count", "minimum_required"),
    }
    for relative, fields in json_requirements.items():
        payload = _read_json_if_present(paths[relative])
        if (not isinstance(payload, Mapping) or
                any(field not in payload for field in fields)):
            reasons.append("Stage9 evidence artifact is structurally incomplete: " + relative)
    raw_path = paths["raw_latency_samples.csv"]
    try:
        with open(raw_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(list(reader)) == 0:
                reasons.append("Stage9 raw latency samples are empty")
    except (OSError, UnicodeError, csv.Error):
        reasons.append("Stage9 raw latency samples are unreadable")
    try:
        with open(paths["capacity_overhead.csv"], "r", encoding="utf-8",
                  newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not list(reader):
                reasons.append("Stage9 capacity accounting is empty")
    except (OSError, UnicodeError, csv.Error):
        reasons.append("Stage9 capacity accounting is unreadable")

    state_values = state if isinstance(state, Mapping) else {}
    receipt = {
        "schema_version": "capd_proactive_stage10_stage9_compatibility_v1_0",
        "status": ("stage9_compatibility_verified" if not reasons
                   else "stage10_formal_blocked_by_stage9"),
        "formal_authorized": not reasons,
        "source_run_id": run_id,
        "source_run_root": os.path.relpath(run_root, project_root),
        "source_stage9_contract_id": state_values.get("contract_id"),
        "source_stage9_status": state_values.get("status"),
        "source_artifact_sha256": observed_hashes,
        "stage9_verification_sha256": (
            sha256_file(paths["verification.json"])
            if os.path.isfile(paths["verification.json"]) else None),
        "stage9_run_state_sha256": (
            sha256_file(paths["run_state.json"])
            if os.path.isfile(paths["run_state.json"]) else None),
        "stage8_compatibility_receipt_sha256": (
            sha256_file(paths["stage8_compatibility_receipt.json"])
            if os.path.isfile(paths["stage8_compatibility_receipt.json"])
            else None),
        "stage8_r5_verification_sha256": gate["stage8_r5_verification_sha256"],
        "stage8_r5_tree_sha256": gate["stage8_r5_tree_sha256"],
        "reasons": reasons,
    }
    return receipt


def check_formal_stage9_gate(receipt: Mapping[str, Any],
                             gate: Mapping[str, Any]) -> Mapping[str, Any]:
    result = dict(receipt)
    reasons = list(receipt.get("reasons", ()))
    if receipt.get("status") != "stage9_compatibility_verified":
        reasons.append("Stage10-owned Stage9 compatibility receipt is blocked")
    if receipt.get("source_run_id") in gate.get("rejected_run_ids", ()):
        reasons.append("Stage9 r1 cannot authorize Stage10")
    if receipt.get("stage8_r5_tree_sha256") != gate["stage8_r5_tree_sha256"]:
        reasons.append("Stage8 r5 tree binding mismatch")
    result["reasons"] = sorted(set(reasons))
    result["formal_authorized"] = not result["reasons"]
    result["status"] = ("stage10_formal_authorized"
                         if result["formal_authorized"]
                         else "stage10_formal_blocked_by_stage9")
    return result
