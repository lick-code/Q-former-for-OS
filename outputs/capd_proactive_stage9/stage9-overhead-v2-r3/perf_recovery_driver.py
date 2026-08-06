# coding=utf-8
"""Run the frozen Stage9 runner with a scoped perf FIFO ACK compatibility fix."""

from __future__ import annotations

import copy
import importlib.util
import math
import os
import re
import sys


RUN_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(RUN_ROOT)))
RUNNER_PATH = os.path.join(
    PROJECT_ROOT, "scripts", "run_capd_proactive_stage9.py")


def normalize_perf_ack(raw):
  """Accept perf's documented ack plus leading NUL bytes seen on this host."""
  response = raw.strip()
  normalized = response.lstrip("\x00")
  if normalized != "ack" or any(character != "\x00"
                                 for character in response[:-3]):
    raise ValueError("unexpected perf FIFO acknowledgement: {!r}".format(raw))
  return normalized


def verify_measurement_checkpoint(runner, path, raw_path, config, jobs):
  """Verify the real r3 checkpoint, whose persisted seed keys are strings."""
  value = runner.stage9.load_json(path)
  expected_cells = {
      (job["track"], job["workload"], int(job["seed"]), int(b_max))
      for job in jobs for b_max in runner.stage9.SENSITIVITY_BMAX}
  rows = value.get("completed_cells", [])
  try:
    observed_cells = {
        (row["track"], row["workload"], int(row["seed"]), int(row["b_max"]))
        for row in rows}
    effective = [int(row["effective_warmup_rounds"]) for row in rows]
  except (KeyError, TypeError, ValueError) as error:
    raise runner.stage9.Stage9ContractError(
        "Measurement checkpoint has malformed completed cells: {}".format(
            error))
  expected_seeds = sorted(str(seed) for seed in config["capd_seeds"])
  checks = {
      "schema_version": value.get("schema_version") ==
          "capd_proactive_stage9_measurement_checkpoint_v2_0",
      "status": value.get("status") == "completed",
      "failure": value.get("failure") is None,
      "completed_cell_count": len(rows) == len(expected_cells),
      "completed_cell_identity": observed_cells == expected_cells,
      "effective_warmup_bounds": not any(
          item < 0 or item > config["measurement"]["warmup_rounds"]
          for item in effective),
      "quality_row_count": value.get("quality_row_count") ==
          config["measurement_matrix"]["quality_job_count"],
      "instrumentation_audit_count":
          value.get("instrumentation_audit_count") ==
          config["measurement_matrix"]["formal_instrumentation_job_count"],
      "model_memory_seeds": value.get("model_memory_seeds") == expected_seeds,
      "raw_path": value.get("raw_partial_path") == os.path.basename(raw_path),
      "raw_bytes": value.get("raw_partial_bytes") == os.path.getsize(raw_path),
      "raw_sha256": value.get("raw_sha256") ==
          runner.stage9.fingerprint_file(raw_path),
  }
  failed = sorted(name for name, passed in checks.items() if not passed)
  if failed:
    raise runner.stage9.Stage9ContractError(
        "Completed measurement checkpoint failed: {}".format(", ".join(failed)))
  return value


def verify_recovery_identity(runner, expected, actual):
  """Allow only Git metadata drift after all recorded artifact SHA checks."""
  expected_bound = copy.deepcopy(expected)
  actual_bound = copy.deepcopy(actual)
  for value in (expected_bound, actual_bound):
    value.pop("git", None)
    value.pop("run_identity_sha256", None)
  differences = runner._identity_differences(expected_bound, actual_bound)
  if differences:
    raise runner.stage9.Stage9ContractError(
        "Stage-9 bound identity changed during perf recovery: {}".format(
            "; ".join(differences)))


def verify_regression_receipt(runner, run_root, project_root, receipt, minimum):
  """Reproduce the unittest summary even when buffered test stdout follows it."""
  recorded = receipt.get("log_path")
  if not isinstance(recorded, str) or os.path.isabs(recorded):
    raise runner.stage9.Stage9ContractError("Regression log path is invalid.")
  log_path = os.path.realpath(os.path.join(
      project_root, recorded.replace("/", os.sep).replace("\\", os.sep)))
  resolved_run_root = os.path.realpath(run_root)
  try:
    confined = os.path.commonpath((resolved_run_root, log_path)) == resolved_run_root
  except ValueError:
    confined = False
  if not confined or not os.path.isfile(log_path):
    raise runner.stage9.Stage9ContractError(
        "Regression log must be an artifact inside this Stage-9 run.")
  runner.stage9.verify_file_binding(
      log_path, receipt.get("log_sha256"), "Stage-9 regression log")
  with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  summaries = re.findall(
      r"(?m)^Ran\s+(\d+)\s+tests?[^\r\n]*\r?\n\s*"
      r"(OK(?:\s+\([^\r\n]*\))?|FAILED(?:\s+\([^\r\n]*\))?)\s*$",
      text)
  count = int(summaries[-1][0]) if summaries else 0
  final_ok = bool(summaries and summaries[-1][1].startswith("OK"))
  checks = {
      "schema_version": receipt.get("schema_version") ==
          "capd_proactive_stage9_server_test_receipt_v2_0",
      "contract_id": receipt.get("contract_id") == runner.stage9.CONTRACT_ID,
      "status": receipt.get("status") == "passed",
      "test_count": receipt.get("test_count") == count,
      "minimum_required": receipt.get("minimum_required") == minimum,
      "minimum_satisfied": count >= minimum,
      "unittest_summary": final_ok,
  }
  failed = sorted(name for name, passed in checks.items() if not passed)
  if failed:
    raise runner.stage9.Stage9ContractError(
        "Server regression receipt failed: {}".format(", ".join(failed)))


def verify_quality_aggregate_equivalent(stored, computed, path="quality"):
  """Require exact structure and tolerate only JSON round-trip float ULPs."""
  if isinstance(stored, dict) and isinstance(computed, dict):
    if set(stored) != set(computed):
      raise ValueError("{} keys changed".format(path))
    for key in stored:
      verify_quality_aggregate_equivalent(
          stored[key], computed[key], "{}.{}".format(path, key))
    return
  if isinstance(stored, list) and isinstance(computed, list):
    if len(stored) != len(computed):
      raise ValueError("{} length changed".format(path))
    for index, (left, right) in enumerate(zip(stored, computed)):
      verify_quality_aggregate_equivalent(
          left, right, "{}[{}]".format(path, index))
    return
  if isinstance(stored, float) and isinstance(computed, float):
    if (not math.isfinite(stored) or not math.isfinite(computed) or
        abs(stored - computed) > 1e-12):
      raise ValueError(
          "{} float changed: {!r} != {!r}".format(path, stored, computed))
    return
  if stored != computed:
    raise ValueError("{} changed: {!r} != {!r}".format(
        path, stored, computed))


def load_recovery_run(runner, args):
  """Load failed r3 while retaining every identity check except Git metadata."""
  config, stage0, cost = runner._load(args)
  run_root = runner._run_root(args, config)
  state_path = os.path.join(run_root, "run_state.json")
  if not os.path.isfile(state_path):
    raise runner.stage9.Stage9ContractError(
        "Recovery run has no Stage-9 run state.")
  state = runner.stage9.load_json(state_path)
  if state.get("status") != runner.stage9.RUNNING:
    raise runner.stage9.Stage9ContractError(
        "Perf recovery requires the audited running state.")
  binding, torch = runner._configure_cpu_runtime(config)
  stage8_entry = runner._audit_stage8_entry(config, args.project_root)
  actual = runner._identity(args, config, stage8_entry, binding)
  expected = runner.stage9.load_json(
      os.path.join(run_root, "run_identity.json"))
  actual["run_identity_sha256"] = runner.stage9.fingerprint_value(actual)
  verify_recovery_identity(runner, expected, actual)
  return run_root, config, stage0, cost, stage8_entry, expected, torch


def main():
  spec = importlib.util.spec_from_file_location(
      "stage9_frozen_runner_perf_recovery", RUNNER_PATH)
  runner = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(runner)

  def command(control, value):
    control.control.write(value + "\n")
    raw = control.ack.readline()
    try:
      normalize_perf_ack(raw)
    except ValueError as error:
      raise runner.stage9.Stage9ContractError(
          "perf control did not acknowledge {}: {}".format(value, error))

  runner._PerfControl.command = command
  runner._verify_measurement_checkpoint = lambda path, raw_path, config, jobs: (
      verify_measurement_checkpoint(runner, path, raw_path, config, jobs))
  runner._verify_regression_receipt = (
      lambda run_root, project_root, receipt, minimum:
      verify_regression_receipt(
          runner, run_root, project_root, receipt, minimum))
  original_aggregate_quality = runner._aggregate_quality
  quality_path = os.path.join(RUN_ROOT, "quality_summary.json")
  stored_quality = runner.stage9.load_json(quality_path)

  def aggregate_quality(rows):
    computed = original_aggregate_quality(rows)
    if rows == stored_quality.get("rows"):
      try:
        verify_quality_aggregate_equivalent(
            stored_quality.get("by_b_max"), computed.get("by_b_max"))
      except ValueError as error:
        raise runner.stage9.Stage9ContractError(str(error))
      computed["by_b_max"] = copy.deepcopy(stored_quality["by_b_max"])
    return computed

  runner._aggregate_quality = aggregate_quality
  runner._loaded_run = lambda args: load_recovery_run(runner, args)
  runner.main(sys.argv[1:])


if __name__ == "__main__":
  main()
