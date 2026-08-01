# coding=utf-8
"""Stage-9 Linux CPU latency, perf-cycle, and memory measurement contracts.

This module is deliberately separate from the verified Stage-8 adapter.  It
reuses the frozen Replay state machine but never writes below the Stage-8
output root.  Pure accounting helpers avoid importing torch, so contract and
statistics tests remain runnable on machines without the model runtime.
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys
import tempfile
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from qmap import finals_config
from qmap import proactive_replay
from qmap import proactive_stage5_policies


SCHEMA_VERSION = "capd_proactive_stage9_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE9-1.0"
IMPLEMENTED = "stage9_implemented_awaiting_server_measurement"
RUNNING = "stage9_running"
VERIFIED = "stage9_overhead_verified"
NOT_VERIFIED = "stage9_not_verified"
STAGE10_SATISFIED = "satisfied"
STAGE10_NOT_SATISFIED = "not_satisfied"
CAPD_SEEDS = (3136859, 42, 2026)
SENSITIVITY_BMAX = (1, 2, 4)
LATENCY_FIELDS = (
    "watermark_check_ns", "candidate_construction_ns",
    "feature_construction_ns", "transformer_encoding_ns",
    "candidate_scoring_ns", "top_b_selection_ns",
    "total_round_latency_ns", "unattributed_framework_overhead_ns")
EXCLUSIVE_PHASE_FIELDS = LATENCY_FIELDS[:6]
FROZEN_CONTROLS = {
    "F_low": 8, "F_target": 16, "b_max": 4, "candidate_size_K": 8,
    "candidate_source": "lru_tail", "selector": "disabled",
    "fallback_policy": "lru", "trigger_mode": "low_watermark"}
FROZEN_CAPD = {
    "lookahead_L": 256, "label_weights": [1, 1, 2], "history_H": 20,
    "vocabulary_expansion_allowed": False, "unk_index": 0,
    "best_seed_selection_allowed": False}
FROZEN_COST = {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
               "demotion": 10}


class Stage9ContractError(ValueError):
  pass


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage9ContractError(message)


def load_json(path: str) -> Any:
  return finals_config.load_json(path)


def fingerprint_file(path: str) -> str:
  return finals_config.fingerprint_file(path)


def fingerprint_value(value: Any) -> str:
  return finals_config.fingerprint_value(value)


def write_json_atomic(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage9-json-", suffix=".tmp", dir=directory)
  try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
      json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def write_text_atomic(path: str, value: str) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage9-text-", suffix=".tmp", dir=directory)
  try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
      handle.write(value)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def write_csv_atomic(path: str, rows: Sequence[Mapping[str, Any]],
                     fieldnames: Optional[Sequence[str]] = None) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  if fieldnames is None:
    fieldnames = list(rows[0]) if rows else []
  fd, temporary = tempfile.mkstemp(
      prefix=".stage9-csv-", suffix=".tmp", dir=directory)
  try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
      writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
      writer.writeheader()
      for row in rows:
        writer.writerow({key: row.get(key) for key in fieldnames})
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping) and
           value.get("schema_version") == SCHEMA_VERSION and
           value.get("contract_id") == CONTRACT_ID,
           "Stage-9 config schema/contract mismatch.")
  _require(value.get("stage_status") == IMPLEMENTED and
           value.get("output_root") == "outputs/capd_proactive_stage9" and
           value.get("result_schema") ==
           "configs/finals/capd_proactive_stage9_result_schema.json",
           "Stage-9 output/status binding changed.")
  _require(value.get("frozen_controls") == FROZEN_CONTROLS,
           "Stage-9 frozen Replay controls changed.")
  _require(value.get("capd") == FROZEN_CAPD and
           tuple(value.get("capd_seeds", ())) == CAPD_SEEDS,
           "Stage-9 frozen CAPD/checkpoint seed identity changed.")
  _require(value.get("cost_profile", {}).get("weights") == FROZEN_COST,
           "Stage-9 Cost profile changed.")
  storage = value.get("storage", {})
  _require(storage.get("page_size_bytes") == 4096 and
           storage.get("page_enter_dram_semantics") ==
           "occupies_one_free_frame_regardless_of_source" and
           storage.get("promotion_allowed") is False,
           "Stage-9 storage semantics changed.")
  measurement = value.get("measurement", {})
  _require(measurement.get("device") == "cpu" and
           measurement.get("batch_size_rounds") == 1 and
           measurement.get("clock") == "time.perf_counter_ns" and
           measurement.get("stage_timings") == "exclusive" and
           measurement.get("torch_intra_op_threads") >= 1 and
           measurement.get("torch_inter_op_threads") >= 1 and
           measurement.get("cpu_threads") >= 1 and
           isinstance(measurement.get("cpu_affinity"), list) and
           measurement.get("cpu_affinity") and
           all(isinstance(cpu, int) and cpu >= 0
               for cpu in measurement["cpu_affinity"]) and
           measurement.get("warmup_rounds") == 20 and
           measurement.get("formal_repetitions") == 3 and
           measurement.get("omp_num_threads") == 1 and
           measurement.get("mkl_num_threads") == 1 and
           measurement.get("model_eval") is True and
           measurement.get("torch_no_grad") is True,
           "Stage-9 CPU measurement contract changed.")
  sensitivity = value.get("sensitivity", {})
  _require(tuple(sensitivity.get("b_max_values", ())) == SENSITIVITY_BMAX and
           sensitivity.get("formal_b_max") == 4 and
           sensitivity.get("purpose") == "analysis_only_not_selection" and
           sensitivity.get("quality_metrics") ==
           ["weighted_cost", "early_reuse"],
           "Stage-9 b_max sensitivity contract changed.")
  test_policy = value.get("test_policy", {})
  _require(test_policy == {
      "used_for_parameter_selection": False,
      "checkpoint_selection_allowed": False,
      "formal_b_max_selection_allowed": False,
      "retraining_allowed": False,
      "vocabulary_expansion_allowed": False,
      "oov_fix_allowed": False},
      "Stage-9 Test/freeze stop-loss policy changed.")
  matrix = value.get("measurement_matrix", {})
  _require(matrix.get("capacity_ratios") == ["0.40"] and
           matrix.get("workloads") == "all_stage8_locked_workloads" and
           matrix.get("seeds") == list(CAPD_SEEDS) and
           matrix.get("job_count") == 54,
           "Stage-9 predeclared measurement matrix changed.")
  _require(value.get("fair_capacity", {}).get("formal_replay") == "deferred" and
           value.get("fair_capacity", {}).get("overwrite_stage8_allowed") is False,
           "Stage-9 fair-capacity boundary changed.")
  return value


def validate_stage8_verification(value: Mapping[str, Any]) -> None:
  _require(value.get("status") == "stage8_sync_replay_verified" and
           value.get("stage9_entry_gate") == "satisfied" and
           value.get("formal_job_count") == 144 and
           value.get("test_used_for_parameter_selection") is False and
           value.get("frozen_parameters_changed") is False,
           "Stage-8 authority does not satisfy the Stage-9 entry gate.")


def verify_file_binding(path: str, expected_sha256: str, label: str) -> str:
  _require(os.path.isfile(path), "Missing {}: {}".format(label, path))
  actual = fingerprint_file(path)
  _require(actual == expected_sha256,
           "{} SHA-256 mismatch: expected {}, got {}.".format(
               label, expected_sha256, actual))
  return actual


def require_cpu_device(device: str) -> str:
  normalized = str(device).strip().lower()
  _require(normalized == "cpu", "Stage-9 formal online device must be CPU.")
  return normalized


def assert_eval_mode(modules: Iterable[Any]) -> None:
  _require(all(getattr(module, "training", None) is False
               for module in modules), "Every CAPD module must be in eval mode.")


def assert_grad_disabled(grad_enabled: bool) -> None:
  _require(grad_enabled is False,
           "Stage-9 inference must execute inside torch.no_grad().")


def runtime_binding(requested_affinity: Sequence[int],
                    actual_affinity: Sequence[int], cpu_threads: int,
                    torch_intra_op_threads: int,
                    torch_inter_op_threads: int, omp_num_threads: str,
                    mkl_num_threads: str, warmup_rounds: int,
                    formal_repetitions: int) -> Dict[str, Any]:
  value = {
      "requested_affinity": sorted(int(x) for x in requested_affinity),
      "actual_affinity": sorted(int(x) for x in actual_affinity),
      "cpu_threads": int(cpu_threads),
      "torch_intra_op_threads": int(torch_intra_op_threads),
      "torch_inter_op_threads": int(torch_inter_op_threads),
      "OMP_NUM_THREADS": str(omp_num_threads),
      "MKL_NUM_THREADS": str(mkl_num_threads),
      "warmup_rounds": int(warmup_rounds),
      "formal_repetitions": int(formal_repetitions),
  }
  validate_runtime_binding(value)
  return value


def validate_runtime_binding(value: Mapping[str, Any]) -> None:
  _require(value.get("requested_affinity") == value.get("actual_affinity"),
           "Actual CPU affinity differs from the frozen request.")
  _require(value.get("cpu_threads", 0) >= 1 and
           value.get("cpu_threads") == len(value.get("actual_affinity", ())) and
           value.get("torch_intra_op_threads", 0) >= 1 and
           value.get("torch_inter_op_threads", 0) >= 1 and
           value.get("OMP_NUM_THREADS") == str(value.get("cpu_threads")) and
           value.get("MKL_NUM_THREADS") == str(value.get("cpu_threads")) and
           value.get("warmup_rounds", 0) >= 1 and
           value.get("formal_repetitions", 0) >= 1,
           "CPU threads/environment/warmup/repetition binding is invalid.")


def prepare_new_run(output_root: str, run_id: str) -> str:
  _require(isinstance(run_id, str) and run_id and
           all(ch.isalnum() or ch in "._-" for ch in run_id) and
           run_id not in (".", ".."), "Unsafe Stage-9 run ID.")
  run_root = os.path.join(output_root, run_id)
  if os.path.exists(run_root):
    raise Stage9ContractError(
        "Stage-9 run IDs are immutable and cannot be reused; use a new run ID.")
  else:
    os.makedirs(run_root)
  return run_root


def write_run_state(run_root: str, status: str, completed: Sequence[str],
                    failure: Optional[Mapping[str, Any]] = None) -> None:
  _require(status in (IMPLEMENTED, RUNNING, VERIFIED, NOT_VERIFIED),
           "Unknown Stage-9 run status.")
  write_json_atomic(os.path.join(run_root, "run_state.json"), {
      "schema_version": "capd_proactive_stage9_run_state_v1_0",
      "contract_id": CONTRACT_ID,
      "status": status,
      "stage10_entry_gate": (
          STAGE10_SATISFIED if status == VERIFIED else STAGE10_NOT_SATISFIED),
      "completed": list(completed),
      "failure": None if failure is None else dict(failure),
  })


def _quantile(values: Sequence[float], probability: float) -> Optional[float]:
  if not values:
    return None
  ordered = sorted(values)
  if len(ordered) == 1:
    return ordered[0]
  position = (len(ordered) - 1) * probability
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  if lower == upper:
    return ordered[lower]
  return ordered[lower] + (ordered[upper] - ordered[lower]) * (
      position - lower)


def distribution(values: Sequence[float]) -> Dict[str, Any]:
  values = list(values)
  return {
      "count": len(values),
      "mean": statistics.mean(values) if values else None,
      "p50": _quantile(values, 0.50),
      "p95": _quantile(values, 0.95),
      "p99": _quantile(values, 0.99),
      "minimum": min(values) if values else None,
      "maximum": max(values) if values else None,
  }


def summarize_latency_samples(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  measured = [row for row in samples if row.get("sample_kind") == "measured"]
  warmup = [row for row in samples if row.get("sample_kind") == "warmup"]
  _require(len(measured) + len(warmup) == len(samples),
           "Latency samples contain an unknown sample_kind.")
  result = {
      "schema_version": "capd_proactive_stage9_latency_summary_v1_0",
      "clock": "time.perf_counter_ns",
      "stage_timings": "exclusive",
      "total_boundary": "watermark_check_start_through_top_b_result",
      "excluded_from_total": [
          "page_migration", "replay_state_update", "invariant_checks",
          "quality_metrics", "artifact_serialization"],
      "measured_sample_count": len(measured),
      "warmup_sample_count": len(warmup),
      "stages": {field: distribution([row[field] for row in measured])
                 for field in LATENCY_FIELDS},
  }
  return result


def audit_latency_summary(samples: Sequence[Mapping[str, Any]],
                          summary: Mapping[str, Any]) -> None:
  expected = summarize_latency_samples(samples)
  _require(summary == expected,
           "Raw latency samples do not reproduce latency_summary.json.")
  for row in samples:
    _require(all(isinstance(row.get(field), int) and row[field] >= 0
                 for field in LATENCY_FIELDS),
             "Latency sample has missing/negative nanosecond field.")
    phase_sum = sum(row[field] for field in EXCLUSIVE_PHASE_FIELDS)
    _require(row["unattributed_framework_overhead_ns"] ==
             row["total_round_latency_ns"] - phase_sum and phase_sum <=
             row["total_round_latency_ns"],
             "Exclusive phase accounting exceeds or differs from total.")


def throughput_from_samples(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  measured = [row for row in samples if row.get("sample_kind") == "measured"]
  total_ns = sum(int(row["total_round_latency_ns"]) for row in measured)
  pages = sum(int(row["b_t"]) for row in measured)
  b_zero = sum(int(row["b_t"]) == 0 for row in measured)
  amortized = [row["total_round_latency_ns"] / float(row["b_t"])
               for row in measured if int(row["b_t"]) > 0]
  b_distribution = {}
  for row in measured:
    key = str(int(row["b_t"]))
    b_distribution[key] = b_distribution.get(key, 0) + 1
  return {
      "schema_version": "capd_proactive_stage9_throughput_v1_0",
      "measured_rounds": len(measured),
      "measured_demoted_pages": pages,
      "measured_total_round_latency_ns": total_ns,
      "rounds_per_second": (
          len(measured) * 1e9 / total_ns if total_ns else None),
      "demoted_pages_per_second": pages * 1e9 / total_ns if total_ns else None,
      "b_t_distribution": b_distribution,
      "b_t_zero_count": b_zero,
      "amortized_sample_count": len(amortized),
      "amortized_latency_ns_per_page": distribution(amortized),
      "b_t_zero_policy": "counted_separately_excluded_from_division",
  }


def cycles_per_unit(cycles: int, measured_rounds: int, measured_pages: int,
                    counter_source: str) -> Dict[str, Any]:
  _require(counter_source == "linux_perf_hardware",
           "CPU cycles must come from Linux perf hardware counters.")
  _require(cycles >= 0 and measured_rounds >= 0 and measured_pages >= 0,
           "Perf counts must be non-negative.")
  return {
      "counter_source": counter_source,
      "cycles": int(cycles),
      "measured_rounds": int(measured_rounds),
      "measured_demoted_pages": int(measured_pages),
      "cpu_cycles_per_round": (
          cycles / float(measured_rounds) if measured_rounds else None),
      "cpu_cycles_per_demoted_page": (
          cycles / float(measured_pages) if measured_pages else None),
  }


def parse_perf_stat(raw: str, delimiter: str = ";") -> Dict[str, Any]:
  known = ("cycles", "instructions", "task-clock", "context-switches",
           "cpu-migrations", "page-faults")
  events = {}
  for line in raw.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    fields = [field.strip() for field in stripped.split(delimiter)]
    event = next((item for item in fields if item in known), None)
    if event is None:
      continue
    raw_value = fields[0]
    normalized = raw_value.lower()
    if "not supported" in normalized:
      events[event] = {"status": "not_supported", "value": None,
                       "raw_value": raw_value}
    elif "not counted" in normalized:
      events[event] = {"status": "not_counted", "value": None,
                       "raw_value": raw_value}
    else:
      try:
        numeric = float(raw_value.replace(",", ""))
      except ValueError:
        events[event] = {"status": "parse_error", "value": None,
                         "raw_value": raw_value}
      else:
        value = int(numeric) if numeric.is_integer() else numeric
        events[event] = {"status": "ok", "value": value,
                         "raw_value": raw_value}
  for event in known:
    events.setdefault(event, {"status": "missing", "value": None,
                              "raw_value": None})
  return {
      "schema_version": "capd_proactive_stage9_perf_v1_0",
      "delimiter": delimiter, "events": events,
      "cycles_verified": events["cycles"]["status"] == "ok",
      "failure_reason": (None if events["cycles"]["status"] == "ok" else
                         "cycles counter status: " +
                         events["cycles"]["status"]),
  }


def _tensor_bytes(value: Any) -> int:
  return int(value.numel()) * int(value.element_size())


def parameter_memory_breakdown(
    named_parameters: Iterable[Sequence[Any]]) -> Dict[str, Any]:
  categories = {"page": 0, "pc": 0, "transformer": 0, "other": 0}
  seen = set()
  for name, tensor in named_parameters:
    identity = id(tensor)
    if identity in seen:
      continue
    seen.add(identity)
    size = _tensor_bytes(tensor)
    lower = str(name).lower()
    if ("address_embedder" in lower or
        "scorer._page_embedder" in lower or ".page_embedder" in lower):
      categories["page"] += size
    elif "pc_embedder" in lower:
      categories["pc"] += size
    elif "extractor" in lower or "transformer" in lower or "qformer" in lower:
      categories["transformer"] += size
    else:
      categories["other"] += size
  total = sum(categories.values())
  return {
      "measurement_method": "exact_tensor_numel_times_element_size",
      "all_model_parameters_bytes": total,
      "all_model_parameters_mib": total / 1048576.0,
      "page_embedding_parameter_bytes": categories["page"],
      "pc_embedding_parameter_bytes": categories["pc"],
      "transformer_parameter_bytes": categories["transformer"],
      "other_parameter_bytes": categories["other"],
  }


def metadata_memory_bytes(page_count: int, bytes_per_page: int) -> int:
  _require(page_count >= 0 and bytes_per_page >= 0,
           "Metadata inputs must be non-negative.")
  return int(page_count) * int(bytes_per_page)


def management_pages(management_memory_bytes: int,
                     page_size_bytes: int = 4096) -> int:
  _require(management_memory_bytes >= 0 and page_size_bytes > 0,
           "Management memory/page size is invalid.")
  return int(math.ceil(management_memory_bytes / float(page_size_bytes)))


def capacity_overhead_rows(
    management_fixed_bytes: int, metadata_bytes_per_page: int,
    workload_capacities: Sequence[Mapping[str, Any]],
    page_size_bytes: int = 4096) -> Sequence[Dict[str, Any]]:
  rows = []
  for capacity in workload_capacities:
    dram_pages = int(capacity["dram_pages"])
    total = management_fixed_bytes + metadata_memory_bytes(
        dram_pages, metadata_bytes_per_page)
    pages = management_pages(total, page_size_bytes)
    effective = dram_pages - pages
    rows.append({
        "workload": capacity["workload"],
        "capacity_ratio": str(capacity["ratio"]),
        "baseline_dram_pages": dram_pages,
        "management_fixed_bytes": int(management_fixed_bytes),
        "metadata_bytes_per_page": int(metadata_bytes_per_page),
        "management_memory_bytes": int(total),
        "management_memory_mib": total / 1048576.0,
        "management_pages": pages,
        "capd_effective_dram_pages": effective,
        "capacity_feasible": effective >= 0,
        "management_exceeds_capacity_pages": max(0, -effective),
        "capacity_overhead_percent": (
            pages * 100.0 / dram_pages if dram_pages else None),
        "page_size_bytes": page_size_bytes,
        "fair_capacity_replay_status": "deferred",
    })
  return rows


def rss_breakdown(baseline_rss_bytes: int,
                  peak_rss_bytes: int) -> Dict[str, Any]:
  _require(baseline_rss_bytes >= 0 and peak_rss_bytes >= baseline_rss_bytes,
           "RSS peak must be at least the process baseline.")
  incremental = peak_rss_bytes - baseline_rss_bytes
  return {
      "measurement_method": "os_observed_rss",
      "process_baseline_rss_bytes": int(baseline_rss_bytes),
      "process_baseline_rss_mib": baseline_rss_bytes / 1048576.0,
      "total_peak_rss_bytes": int(peak_rss_bytes),
      "total_peak_rss_mib": peak_rss_bytes / 1048576.0,
      "stage9_incremental_peak_rss_bytes": int(incremental),
      "stage9_incremental_peak_rss_mib": incremental / 1048576.0,
  }


def deep_sizeof(value: Any) -> int:
  """Best-effort recursive Python-object estimate; never a native RSS claim."""
  seen = set()
  def visit(item):
    identity = id(item)
    if identity in seen:
      return 0
    seen.add(identity)
    size = sys.getsizeof(item)
    if isinstance(item, dict):
      size += sum(visit(key) + visit(val) for key, val in item.items())
    elif isinstance(item, (list, tuple, set, frozenset)):
      size += sum(visit(child) for child in item)
    return size
  return visit(value)


class InstrumentedProactiveReplay(proactive_replay.ProactiveReplay):
  """A Stage-9-only timing adapter with Stage-1-equivalent state updates."""

  def __init__(self, stage0_config, parameters, ranking_policy,
               warmup_rounds=20, formal_repetitions=3,
               invariant_mode="boundary", exclude_current_entering_page=True,
               sample_context=None):
    super().__init__(
        stage0_config, parameters, ranking_policy=ranking_policy,
        invariant_mode=invariant_mode, record_details=True,
        capture_page_enter_flags=True, measure_decision_latency=False,
        exclude_current_entering_page=exclude_current_entering_page)
    _require(warmup_rounds >= 0 and formal_repetitions >= 1,
             "Warmup/repetition counts are invalid.")
    self.stage9_warmup_rounds = int(warmup_rounds)
    self.stage9_formal_repetitions = int(formal_repetitions)
    self.stage9_latency_samples = []
    self.stage9_sample_context = dict(sample_context or {})
    self._stage9_logical_rounds = 0

  def _rank_profiled(self, candidates, candidate_features, context):
    if hasattr(self.ranking_policy, "rank_candidates_profiled"):
      ranking, timings = self.ranking_policy.rank_candidates_profiled(
          self, candidates, candidate_features, context)
      required = {"feature_construction_ns", "transformer_encoding_ns",
                  "candidate_scoring_ns"}
      _require(required <= set(timings),
               "Profiled ranker omitted a Stage-9 component timing.")
      return ranking, {key: int(timings[key]) for key in required}
    started = time.perf_counter_ns()
    ranking = self.ranking_policy.rank_candidates(
        self, candidates, candidate_features, context)
    return ranking, {
        "feature_construction_ns": 0,
        "transformer_encoding_ns": 0,
        "candidate_scoring_ns": time.perf_counter_ns() - started,
    }

  def _measure_decision(self, cycle_id, cycle_round_index, F_before,
                        sample_kind, repetition_index):
    total_started = time.perf_counter_ns()
    started = time.perf_counter_ns()
    should_continue = self.free_frames < self.parameters.F_target
    watermark_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    candidates = self.build_candidates() if should_continue else []
    candidate_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    candidate_features = self._candidate_features(candidates)
    replay_feature_ns = time.perf_counter_ns() - started
    ranking, rank_timings = self._rank_profiled(
        candidates, candidate_features, {
            "cycle_id": cycle_id, "cycle_round_index": cycle_round_index,
            "access_index": self.access_index})
    self._validate_ranking(candidates, ranking)
    b_t = min(self.parameters.b_max,
              self.parameters.F_target - F_before, len(candidates))
    started = time.perf_counter_ns()
    selected = proactive_replay.select_top_b(ranking, b_t) if b_t > 0 else []
    selection_ns = time.perf_counter_ns() - started
    total_ns = time.perf_counter_ns() - total_started
    phases = {
        "watermark_check_ns": watermark_ns,
        "candidate_construction_ns": candidate_ns,
        "feature_construction_ns": (
            replay_feature_ns + rank_timings["feature_construction_ns"]),
        "transformer_encoding_ns": rank_timings["transformer_encoding_ns"],
        "candidate_scoring_ns": rank_timings["candidate_scoring_ns"],
        "top_b_selection_ns": selection_ns,
    }
    phase_sum = sum(phases.values())
    _require(phase_sum <= total_ns,
             "Nested Stage-9 timing phases exceed the total boundary.")
    sample = dict(self.stage9_sample_context)
    sample.update({
        "sample_kind": sample_kind,
        "repetition_index": repetition_index,
        "cycle_id": cycle_id,
        "cycle_round_index": cycle_round_index,
        "round_id": self._round_id + 1,
        "access_index": self.access_index,
        "F_before": F_before,
        "candidate_count": len(candidates),
        "b_max": self.parameters.b_max,
        "b_t": len(selected),
        "total_round_latency_ns": total_ns,
        "unattributed_framework_overhead_ns": total_ns - phase_sum,
    })
    sample.update(phases)
    return candidates, candidate_features, ranking, selected, sample

  def decision_without_timing(self, cycle_id, cycle_round_index, F_before):
    """Executes the same stateless decision without timer instrumentation.

    This is the perf-counter workload: it keeps candidate construction,
    feature preparation, model inference, deterministic sorting, validation,
    and Top-b, but omits perf_counter calls and sample-dict construction.
    """
    candidates = (self.build_candidates()
                  if self.free_frames < self.parameters.F_target else [])
    candidate_features = self._candidate_features(candidates)
    ranking = self.ranking_policy.rank_candidates(
        self, candidates, candidate_features, {
            "cycle_id": cycle_id, "cycle_round_index": cycle_round_index,
            "access_index": self.access_index})
    self._validate_ranking(candidates, ranking)
    b_t = min(self.parameters.b_max,
              self.parameters.F_target - F_before, len(candidates))
    selected = proactive_replay.select_top_b(ranking, b_t) if b_t > 0 else []
    return candidates, candidate_features, ranking, selected

  def _run_proactive_cycle(self, force_after_emergency=False,
                           emergency_fallback_occurred=False):
    if self.is_reactive:
      raise proactive_replay.ReplayInvariantError(
          "Reactive-LRU cannot create a proactive cycle.")
    if self.active_proactive_cycle is not None:
      raise proactive_replay.ReplayInvariantError(
          "A proactive cycle is already active.")
    should_start = (
        0 < self.free_frames < self.parameters.F_low or
        (force_after_emergency and self.free_frames < self.parameters.F_target))
    if not should_start:
      return None

    self._cycle_id += 1
    cycle_id = self._cycle_id
    cycle_start_F = self.free_frames
    cycle_minimum_F = self.free_frames
    cycle_start_round_count = self._round_count
    cycle_start_demotions = self.counters["proactive_demotions"]
    self.active_proactive_cycle = {
        "cycle_id": cycle_id, "start_access": self.access_index}
    termination_reason = None
    maximum_rounds = self.parameters.dram_capacity_pages + 1
    cycle_round_index = 0

    while self.free_frames < self.parameters.F_target:
      cycle_round_index += 1
      if cycle_round_index > maximum_rounds:
        termination_reason = "max_rounds_exceeded"
        break
      F_before = self.free_frames
      self._stage9_logical_rounds += 1
      warmup = self._stage9_logical_rounds <= self.stage9_warmup_rounds
      repetitions = 1 if warmup else self.stage9_formal_repetitions
      observed = []
      for repetition in range(repetitions):
        decision = self._measure_decision(
            cycle_id, cycle_round_index, F_before,
            "warmup" if warmup else "measured", repetition)
        observed.append(decision)
        self.stage9_latency_samples.append(decision[-1])
      candidates, candidate_features, ranking, selected, _ = observed[0]
      for candidate2, features2, ranking2, selected2, _ in observed[1:]:
        _require(candidate2 == candidates and features2 == candidate_features and
                 ranking2 == ranking and selected2 == selected,
                 "Repeated timing changed candidate order, ranking, or Top-b.")

      candidate_state_sha256 = finals_config.fingerprint_value({
          "access_index": self.access_index, "F_t": F_before,
          "dram_lru_mru_to_lru": list(self.dram_lru),
          "dram_resident": sorted(self.dram_resident),
          "excluded_current_entering_page": self._current_entering_page})
      b_t = min(self.parameters.b_max,
                self.parameters.F_target - F_before, len(candidates))
      if not candidates:
        termination_reason = "candidate_set_empty"
        self._round_log(
            cycle_id, cycle_round_index, candidates, candidate_features,
            ranking, [], F_before, termination_reason,
            {"feature_latency": None, "inference_latency": None,
             "selection_latency": None}, candidate_state_sha256)
        break
      if b_t <= 0:
        termination_reason = "b_t_zero"
        self._round_log(
            cycle_id, cycle_round_index, candidates, candidate_features,
            ranking, [], F_before, termination_reason,
            {"feature_latency": None, "inference_latency": None,
             "selection_latency": None}, candidate_state_sha256)
        break
      self.assert_invariants(candidates=candidates, selected=selected, b_t=b_t,
                             F_before=F_before)
      round_id = self._round_id + 1
      for page in selected:
        self._page_demote_from_dram(
            page, proactive_replay.PROACTIVE_DEMOTION,
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
          ranking, selected, F_before, termination_reason,
          {"feature_latency": None, "inference_latency": None,
           "selection_latency": None}, candidate_state_sha256)
      if termination_reason != "continue_rebuild_candidates":
        break

    if termination_reason is None:
      termination_reason = "target_already_reached"
    rounds = self._round_count - cycle_start_round_count
    pages_demoted = self.counters["proactive_demotions"] - cycle_start_demotions
    cycle_log = {
        "schema_version": proactive_replay.STAGE1_LOG_SCHEMA_VERSION,
        "cycle_id": cycle_id, "start_access": self.access_index,
        "end_access": self.access_index, "start_F": cycle_start_F,
        "target_F": self.parameters.F_target,
        "number_of_rounds": rounds,
        "number_of_pages_demoted": pages_demoted,
        "minimum_F": cycle_minimum_F,
        "total_feature_time": None, "total_inference_time": None,
        "total_selection_time": None,
        "emergency_fallback_occurred": bool(emergency_fallback_occurred),
        "termination_reason": termination_reason}
    missing = set(proactive_replay.CYCLE_REQUIRED_FIELDS) - set(cycle_log)
    if missing:
      raise proactive_replay.ReplayInvariantError(
          "Cycle log missing fields: {}.".format(sorted(missing)))
    self._cycle_count += 1
    self.cycle_logs.append(cycle_log)
    self.active_proactive_cycle = None
    self.assert_invariants()
    return cycle_log


class ProfiledCAPDRanker(proactive_stage5_policies.CAPDRanker):
  """Frozen CAPD ranker with exclusive CPU phase boundaries.

  Tensor creation plus access/candidate embedding is feature construction;
  the complete macroscopic extractor (Transformer plus its configured
  Q-Former/pooling) is transformer encoding; the candidate scorer, CPU scalar
  conversion, and deterministic score sort are candidate scoring.  Top-b is
  intentionally owned by :class:`InstrumentedProactiveReplay`.
  """

  def __init__(self, *args, **kwargs):
    require_cpu_device(str(kwargs.get("device", "cpu")))
    super().__init__(*args, **kwargs)
    modules = self.model_modules()
    for module in modules:
      module.eval()
    assert_eval_mode(modules)
    self.last_memory_observation = {}

  def model_modules(self):
    return (self.predictor._feature_embedder,
            self.predictor._extractor, self.predictor._scorer)

  def named_model_parameters(self):
    for prefix, module in zip(
        ("feature_embedder", "extractor", "scorer"), self.model_modules()):
      for name, value in module.named_parameters():
        yield prefix + "." + name, value

  def named_model_buffers(self):
    for prefix, module in zip(
        ("feature_embedder", "extractor", "scorer"), self.model_modules()):
      for name, value in module.named_buffers():
        yield prefix + "." + name, value

  def rank_candidates_profiled(self, state, candidates, candidate_features,
                               policy_context):
    del candidate_features, policy_context
    if not candidates:
      return [], {
          "feature_construction_ns": 0,
          "transformer_encoding_ns": 0,
          "candidate_scoring_ns": 0}
    predictor = self.predictor
    torch = predictor._torch
    _require(predictor._device.type == "cpu",
             "Stage-9 profiled CAPD predictor moved off CPU.")
    assert_eval_mode(self.model_modules())
    actual_count = len(candidates)
    _require(actual_count <= predictor._candidate_count and
             actual_count == len(set(candidates)),
             "Stage-9 explicit candidate contract changed.")
    padding = predictor._candidate_count - actual_count
    padded_candidates = list(candidates) + [0] * padding
    candidate_mask = [1] * actual_count + [0] * padding
    recent_history = list(state.history_window)[-predictor._history_length:]

    from qmap import qmap_eval
    with torch.no_grad():
      assert_grad_disabled(torch.is_grad_enabled())
      feature_started = time.perf_counter_ns()
      candidate_state_features = []
      for rank, candidate in enumerate(candidates):
        residency_duration = state.access_index - state.dram_entry_index.get(
            candidate, state.access_index)
        candidate_state_features.append(
            qmap_eval.build_candidate_state_features(
                candidate, recent_history, residency_duration,
                candidate in {page for page, dirty in state.dirty_state.items()
                              if dirty},
                predictor._lookahead, rank=rank,
                candidate_count=predictor._candidate_count))
      candidate_state_features += [
          [0.0] * predictor._page_state_dim for _ in range(padding)]
      history_page_ids, pc, rw = qmap_eval.apply_history_ablation(
          *qmap_eval.padded_history(
              recent_history, predictor._history_length),
          ablation=predictor._ablation)
      history_mask = (
          [0] * (predictor._history_length - len(recent_history)) +
          [1] * len(recent_history))
      history_page_ids = torch.tensor(
          [history_page_ids], dtype=torch.long, device=predictor._device)
      history_mask_tensor = torch.tensor(
          [history_mask], dtype=torch.float32, device=predictor._device)
      pc = torch.tensor([pc], dtype=torch.long, device=predictor._device)
      rw = torch.tensor([rw], dtype=torch.long, device=predictor._device)
      candidate_pages = torch.tensor(
          [padded_candidates], dtype=torch.long, device=predictor._device)
      candidate_state_tensor = torch.tensor(
          [candidate_state_features], dtype=torch.float32,
          device=predictor._device)
      candidate_mask_tensor = torch.tensor(
          [candidate_mask], dtype=torch.float32, device=predictor._device)
      access_features = predictor._feature_embedder(history_page_ids, pc, rw)
      candidate_page_embeddings = (
          predictor._feature_embedder.embed_pages(candidate_pages)
          if getattr(predictor._scorer, "_shared_page_embedding", False)
          else None)
      feature_ns = time.perf_counter_ns() - feature_started

      transformer_started = time.perf_counter_ns()
      z = predictor._extractor(
          access_features, history_mask=history_mask_tensor)
      transformer_ns = time.perf_counter_ns() - transformer_started

      scoring_started = time.perf_counter_ns()
      scores = predictor._scorer(
          z, candidate_pages, candidate_state_tensor,
          candidate_mask_tensor,
          candidate_page_embeddings=candidate_page_embeddings,
          history_mask=history_mask_tensor)
      score_values = [
          float(value) for value in qmap_eval._flat_sequence(
              scores[0], "Stage-9 explicit candidate scores")[:actual_count]]
      _require(len(score_values) == actual_count and
               all(math.isfinite(value) for value in score_values),
               "CAPD produced missing or non-finite Stage-9 scores.")
      ranked = sorted(
          enumerate(candidates),
          key=lambda item: (-score_values[item[0]], item[0], int(item[1])))
      ranking = [{
          "page": page, "score": score_values[index],
          "rule": "stage4_checkpoint_current_and_past_only",
          "original_candidate_rank": index}
                 for index, page in ranked]
      scoring_ns = time.perf_counter_ns() - scoring_started

    input_tensors = (
        history_page_ids, history_mask_tensor, pc, rw, candidate_pages,
        candidate_state_tensor, candidate_mask_tensor)
    candidate_tensors = (
        candidate_pages, candidate_state_tensor, candidate_mask_tensor)
    self.last_memory_observation = {
        "measurement_method":
            "exact_materialized_tensor_bytes_and_output_activation_lower_bound",
        "input_tensor_bytes": sum(_tensor_bytes(value)
                                  for value in input_tensors),
        "history_tensor_bytes": sum(_tensor_bytes(value) for value in (
            history_page_ids, history_mask_tensor, pc, rw)),
        "candidate_tensor_bytes": sum(_tensor_bytes(value)
                                      for value in candidate_tensors),
        "feature_activation_bytes": _tensor_bytes(access_features),
        "transformer_activation_bytes": _tensor_bytes(z),
        "score_tensor_bytes": _tensor_bytes(scores),
        "activation_limit": (
            "Observed materialized inputs/outputs; internal ATen workspace and "
            "allocator fragmentation are represented only by OS RSS peaks."),
    }
    return ranking, {
        "feature_construction_ns": feature_ns,
        "transformer_encoding_ns": transformer_ns,
        "candidate_scoring_ns": scoring_ns}


def model_memory_from_ranker(ranker: ProfiledCAPDRanker) -> Dict[str, Any]:
  parameters = parameter_memory_breakdown(ranker.named_model_parameters())
  seen = set()
  buffer_bytes = 0
  for _, value in ranker.named_model_buffers():
    if id(value) not in seen:
      seen.add(id(value))
      buffer_bytes += _tensor_bytes(value)
  return {
      "model_parameters": parameters,
      "model_buffers": {
          "measurement_method": "exact_tensor_numel_times_element_size",
          "bytes": int(buffer_bytes), "mib": buffer_bytes / 1048576.0},
      "runtime_tensors": dict(ranker.last_memory_observation),
  }
