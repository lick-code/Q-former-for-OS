# coding=utf-8
"""Run the frozen Stage9 runner with a scoped perf FIFO ACK compatibility fix."""

from __future__ import annotations

import importlib.util
import os
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
  runner.main(sys.argv[1:])


if __name__ == "__main__":
  main()
