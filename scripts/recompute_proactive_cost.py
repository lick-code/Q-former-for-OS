#!/usr/bin/env python3
# coding=utf-8
"""Offline CAPD stage-2 Cost recomputation from raw event summaries."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_cost


DEFAULT_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage2_cost_profiles.json")
COUNT_FIELDS = set(
    proactive_cost.REQUIRED_COUNT_FIELDS +
    (proactive_cost.DEMOTION_TOTAL_FIELD,) +
    proactive_cost.DEMOTION_BREAKDOWN_FIELDS)
INTEGER_TEXT = re.compile(r"^(?:0|[1-9][0-9]*)$")


def _parse_csv_count(value: str, field: str, line_number: int) -> int:
  """Explicitly decodes a CSV integer cell; JSON string coercion stays banned."""
  if not INTEGER_TEXT.match(value or ""):
    raise proactive_cost.CostContractError(
        "CSV line {} field {} must be a canonical non-negative integer."
        .format(line_number, field))
  return int(value)


def _read_json(path: str) -> Tuple[List[Dict[str, Any]], bool]:
  value = proactive_cost.load_strict_json(path)
  if isinstance(value, dict):
    return [value], True
  if isinstance(value, list):
    if not value:
      raise proactive_cost.CostContractError(
          "JSON record array must not be empty.")
    if any(not isinstance(item, dict) for item in value):
      raise proactive_cost.CostContractError(
          "Every JSON array item must be an object.")
    return value, False
  raise proactive_cost.CostContractError(
      "JSON input must be one object or an array of objects.")


def _read_jsonl(path: str) -> Tuple[List[Dict[str, Any]], bool]:
  records = []
  with open(path, "r", encoding="utf-8") as input_file:
    for line_number, line in enumerate(input_file, 1):
      if not line.strip():
        continue
      try:
        value = json.loads(
            line,
            object_pairs_hook=proactive_cost._unique_json_object,
            parse_constant=proactive_cost._reject_json_constant)
      except (ValueError, json.JSONDecodeError) as error:
        raise proactive_cost.CostContractError(
            "Invalid JSONL at line {}: {}.".format(
                line_number, error)) from error
      if not isinstance(value, dict):
        raise proactive_cost.CostContractError(
            "JSONL line {} must contain an object.".format(line_number))
      records.append(value)
  if not records:
    raise proactive_cost.CostContractError(
        "JSONL input contains no records.")
  return records, False


def _read_csv(path: str) -> Tuple[List[Dict[str, Any]], bool]:
  records = []
  with open(path, "r", encoding="utf-8", newline="") as input_file:
    reader = csv.DictReader(input_file)
    if not reader.fieldnames:
      raise proactive_cost.CostContractError("CSV input has no header.")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
      raise proactive_cost.CostContractError(
          "CSV header contains duplicate field names.")
    for line_number, row in enumerate(reader, 2):
      record: Dict[str, Any] = {}
      for field, value in row.items():
        if field is None:
          raise proactive_cost.CostContractError(
              "CSV line {} has more values than header fields.".format(
                  line_number))
        if field in COUNT_FIELDS:
          if value == "":
            continue
          record[field] = _parse_csv_count(value, field, line_number)
        else:
          record[field] = value
      records.append(record)
  if not records:
    raise proactive_cost.CostContractError("CSV input contains no records.")
  return records, len(records) == 1


def detect_input_format(path: str, requested: str) -> str:
  if requested != "auto":
    return requested
  extension = os.path.splitext(path)[1].lower()
  formats = {".json": "json", ".jsonl": "jsonl", ".csv": "csv"}
  if extension not in formats:
    raise proactive_cost.CostContractError(
        "Cannot infer input format from {}; use --input-format.".format(
            extension or "<no extension>"))
  return formats[extension]


def read_records(path: str, input_format: str = "auto"
                 ) -> Tuple[List[Dict[str, Any]], bool]:
  input_format = detect_input_format(path, input_format)
  readers = {"json": _read_json, "jsonl": _read_jsonl, "csv": _read_csv}
  return readers[input_format](path)


def recompute_records(records: Sequence[Dict[str, Any]], single: bool,
                      config: proactive_cost.CostConfiguration,
                      profile_names: Sequence[str]) -> Any:
  outputs = [
      proactive_cost.recompute_record(record, config, profile_names)
      for record in records]
  value: Any = outputs[0] if single else outputs
  proactive_cost.assert_finite_json_tree(value)
  return value


def write_json_output(path: str, value: Any) -> None:
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
    json.dump(
        value, output_file, indent=2, sort_keys=True, ensure_ascii=False,
        allow_nan=False)
    output_file.write("\n")


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      description=(
          "Recompute proactive CAPD weighted Cost from existing raw event "
          "summaries; Replay/model/GPU are not used."))
  parser.add_argument("--config", default=DEFAULT_CONFIG,
                      help="Frozen stage-2 Cost profile JSON.")
  parser.add_argument("--input",
                      help="Input .json, .jsonl, or .csv raw summary.")
  parser.add_argument(
      "--input-format", choices=("auto", "json", "jsonl", "csv"),
      default="auto")
  selection = parser.add_mutually_exclusive_group()
  selection.add_argument(
      "--profile", choices=proactive_cost.FROZEN_PROFILE_NAMES,
      help="Compute one profile; default is the configured default profile.")
  selection.add_argument(
      "--all-profiles", action="store_true",
      help="Compute all four frozen profiles from the same counters.")
  parser.add_argument("--output",
                      help="Output JSON path. Input files are never overwritten.")
  parser.add_argument(
      "--stdout-preview", action="store_true",
      help="Also print JSON when --output is used.")
  parser.add_argument(
      "--validate-config", action="store_true",
      help="Validate the profile configuration and exit without input.")
  return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
  args = build_arg_parser().parse_args(argv)
  config = proactive_cost.load_cost_config(args.config)
  if args.validate_config:
    print(
        "VALID stage2 Cost config: {} profiles={} status={}".format(
            config.schema_version, ",".join(config.profiles),
            config.stage_status))
    return 0
  if not args.input:
    raise proactive_cost.CostContractError(
        "--input is required unless --validate-config is used.")
  if args.output and os.path.abspath(args.output) == os.path.abspath(
      args.input):
    raise proactive_cost.CostContractError(
        "Output path must differ from input path.")
  if args.all_profiles:
    profile_names = proactive_cost.FROZEN_PROFILE_NAMES
  elif args.profile:
    profile_names = (args.profile,)
  else:
    profile_names = (config.default_profile,)
  records, single = read_records(args.input, args.input_format)
  output = recompute_records(records, single, config, profile_names)
  rendered = json.dumps(
      output, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
  if args.output:
    write_json_output(args.output, output)
    if args.stdout_preview:
      print(rendered)
  else:
    print(rendered)
  return 0


def main() -> int:
  try:
    return run()
  except (OSError, ValueError, csv.Error) as error:
    print("ERROR: {}".format(error), file=sys.stderr)
    return 2


if __name__ == "__main__":
  sys.exit(main())
