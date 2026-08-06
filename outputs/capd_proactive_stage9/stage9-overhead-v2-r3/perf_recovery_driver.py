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
  runner.main(sys.argv[1:])


if __name__ == "__main__":
  main()
