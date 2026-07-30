#!/usr/bin/env python3
# coding=utf-8
"""Materialize fresh Stage-3 Train/Validation pairs without creating Test."""

import argparse
import csv
import hashlib
import os
import shutil
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage3


def parser():
  value = argparse.ArgumentParser()
  value.add_argument(
      "--source", action="append", required=True, metavar="WORKLOAD=PATH",
      help="Fresh raw trace; repeat once per workload.")
  value.add_argument("--output-directory", required=True)
  value.add_argument("--skip-records", type=int, default=0)
  value.add_argument("--train-records", type=int, default=600000)
  value.add_argument("--validation-records", type=int, default=400000)
  value.add_argument("--page-shift", type=int, default=12)
  value.add_argument("--project-root", default=PROJECT_ROOT)
  return value


def _sources(values, project_root):
  result = {}
  for value in values:
    if "=" not in value:
      raise ValueError("--source must use WORKLOAD=PATH: {}".format(value))
    workload, path = value.split("=", 1)
    workload = workload.strip()
    path = path.strip()
    if not workload or not path or workload in result:
      raise ValueError("Invalid or duplicate --source: {}".format(value))
    absolute = (
        path if os.path.isabs(path)
        else os.path.join(project_root, path))
    absolute = os.path.abspath(absolute)
    if not os.path.isfile(absolute):
      raise FileNotFoundError(
          "Fresh source trace does not exist: {}".format(absolute))
    result[workload] = absolute
  return result


def _sha256(path):
  digest = hashlib.sha256()
  with open(path, "rb") as input_file:
    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def _materialize(source, train_path, validation_path, args):
  required = (
      args.skip_records + args.train_records + args.validation_records)
  with open(source, encoding="utf-8-sig", newline="") as input_file:
    reader = csv.DictReader(input_file)
    if reader.fieldnames is None:
      raise ValueError("Trace has no CSV header: {}".format(source))
    normalized = {
        name.strip().lower(): name for name in reader.fieldnames}
    if set(normalized) != {"pc", "address", "rw"}:
      raise ValueError(
          "Trace must contain exactly pc,address,rw: {}".format(source))
    outputs = {}
    try:
      for split, path in (
          ("train", train_path), ("validation", validation_path)):
        output = open(path, "w", encoding="utf-8", newline="")
        writer = csv.DictWriter(
            output, fieldnames=["pc", "address", "rw"])
        writer.writeheader()
        outputs[split] = (output, writer)
      seen = 0
      train_written = 0
      validation_written = 0
      for row in reader:
        if seen < args.skip_records:
          seen += 1
          continue
        relative = seen - args.skip_records
        if relative < args.train_records:
          outputs["train"][1].writerow({
              key: row[normalized[key]] for key in ("pc", "address", "rw")})
          train_written += 1
        elif relative < args.train_records + args.validation_records:
          outputs["validation"][1].writerow({
              key: row[normalized[key]] for key in ("pc", "address", "rw")})
          validation_written += 1
        else:
          break
        seen += 1
    finally:
      for output, _ in outputs.values():
        output.close()
  if seen < required:
    raise ValueError(
        "Trace has {} usable records but {} are required: {}".format(
            seen, required, source))
  if (
      train_written != args.train_records or
      validation_written != args.validation_records):
    raise ValueError("Fresh pair materialization produced incomplete splits.")
  return {
      "train_records": train_written,
      "validation_records": validation_written,
  }


def main(argv=None):
  args = parser().parse_args(argv)
  try:
    if (
        args.skip_records < 0 or args.train_records <= 0 or
        args.validation_records <= 0 or args.page_shift < 0):
      raise ValueError("Record counts and page_shift are invalid.")
    project_root = os.path.abspath(args.project_root)
    sources = _sources(args.source, project_root)
    output_directory = os.path.abspath(args.output_directory)
    incomplete = output_directory + ".incomplete"
    if os.path.exists(output_directory) or os.path.exists(incomplete):
      raise FileExistsError(
          "Refusing to overwrite fresh-pair output: {}".format(
              output_directory))
    os.makedirs(incomplete)
    workload_rows = []
    try:
      for workload in sorted(sources):
        workload_directory = os.path.join(incomplete, workload)
        os.makedirs(workload_directory)
        train_path = os.path.join(workload_directory, "train.csv")
        validation_path = os.path.join(
            workload_directory, "validation.csv")
        counts = _materialize(
            sources[workload], train_path, validation_path, args)
        workload_rows.append({
            "workload": workload,
            "source_trace": sources[workload],
            "source_trace_sha256": _sha256(sources[workload]),
            "source_interval": {
                "start_inclusive": args.skip_records,
                "end_exclusive": (
                    args.skip_records + args.train_records +
                    args.validation_records),
            },
            "splits": {
                "train": {
                    "path": os.path.join(
                        output_directory, workload, "train.csv"),
                    "records": counts["train_records"],
                    "source_interval": {
                        "start_inclusive": args.skip_records,
                        "end_exclusive":
                            args.skip_records + args.train_records,
                    },
                    "sha256": _sha256(train_path),
                },
                "validation": {
                    "path": os.path.join(
                        output_directory, workload, "validation.csv"),
                    "records": counts["validation_records"],
                    "source_interval": {
                        "start_inclusive":
                            args.skip_records + args.train_records,
                        "end_exclusive": (
                            args.skip_records + args.train_records +
                            args.validation_records),
                    },
                    "sha256": _sha256(validation_path),
                },
            },
        })
      proactive_stage3.write_json(
          os.path.join(incomplete, "pair_manifest.json"), {
              "schema_version":
                  "capd_proactive_stage3_fresh_pair_v1",
              "page_shift": args.page_shift,
              "split_policy":
                  "chronological_non_overlapping_train_validation_only",
              "formal_test_created": False,
              "formal_test_used": False,
              "workloads": workload_rows,
          })
      os.replace(incomplete, output_directory)
    except Exception:
      if os.path.isdir(incomplete):
        shutil.rmtree(incomplete)
      raise
    print(output_directory)
    print("STAGE3_FRESH_TRAIN_VALIDATION_PAIR_READY")
    print("STAGE3_FORMAL_TEST_NOT_CREATED")
    return 0
  except (OSError, ValueError) as error:
    print("STAGE3_FRESH_PAIR_ERROR: {}".format(error), file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
