#!/usr/bin/env python3
# coding=utf-8
"""Builds a strict Stage-4 Train/Validation manifest from raw trace paths."""

from __future__ import annotations

import argparse
import copy
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage3
from qmap import proactive_stage4


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("--source-manifest", required=True)
  parser.add_argument("--output", required=True)
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  group = parser.add_mutually_exclusive_group(required=True)
  group.add_argument(
      "--attest-distinct-source-traces", action="store_true",
      help=(
          "Attest that each Train/Validation file is a distinct capture, not "
          "an overlapping slice of one source trace."))
  group.add_argument(
      "--source-ranges-json",
      help=(
          "JSON mapping workload/split to source_trace_id/start/end when "
          "Train and Validation are slices of source traces."))
  return parser


def _resolve(entry, source, source_path, project_root):
  base = (
      os.path.dirname(os.path.abspath(source_path))
      if source.get("path_base") == "manifest_directory"
      else os.path.abspath(project_root))
  return os.path.abspath(os.path.join(base, entry["trace_path"]))


def main(argv=None):
  args = build_parser().parse_args(argv)
  source_document = proactive_stage3.load_json(args.source_manifest)
  source = source_document.get("manifest", source_document)
  entries = source.get("entries")
  if not isinstance(entries, list) or not entries:
    raise ValueError("Source manifest has no entries.")
  ranges = (
      proactive_stage4.load_json(args.source_ranges_json)
      if args.source_ranges_json else None)
  output_entries = []
  for source_entry in entries:
    split = source_entry.get("split")
    if split not in proactive_stage4.ALLOWED_SPLITS:
      raise ValueError("Stage-4 preparer rejects split={!r}.".format(split))
    if source_entry.get("formal_test") is not False:
      raise ValueError("Stage-4 preparer rejects formal Test inputs.")
    workload = source_entry["workload"]
    path = _resolve(
        source_entry, source, args.source_manifest, args.project_root)
    trace, _ = proactive_stage3._read_compact_trace(
        path, int(source_entry.get("page_shift", 12)))
    digest = proactive_stage4.fingerprint_file(path)
    if ranges is None:
      source_trace_id = "{}:{}:{}".format(workload, split, digest[:16])
      interval = {"start": 0, "end": len(trace)}
    else:
      item = ranges.get(workload, {}).get(split)
      if not isinstance(item, dict):
        raise ValueError(
            "Missing source range for {}/{}.".format(workload, split))
      source_trace_id = item["source_trace_id"]
      interval = {"start": int(item["start"]), "end": int(item["end"])}
      if interval["end"] - interval["start"] != len(trace):
        raise ValueError(
            "Source range length mismatch for {}/{}.".format(
                workload, split))
    output_entries.append({
        "workload": workload,
        "split": split,
        "role": (
            "training_and_fit" if split == "train"
            else "parameter_selection"),
        "trace_path": path,
        "trace_sha256": digest,
        "page_shift": int(source_entry.get("page_shift", 12)),
        "source_kind": "raw_access_trace",
        "formal_test": False,
        "source_trace_id": source_trace_id,
        "source_interval": interval,
    })
  manifest = {
      "schema_version": proactive_stage4.MANIFEST_SCHEMA,
      "contract_id": proactive_stage4.CONTRACT_ID,
      "path_base": "project_root",
      "test_used_for_parameter_selection": False,
      "split_non_overlap_attested": True,
      "source_manifest": os.path.abspath(args.source_manifest),
      "source_manifest_sha256":
          proactive_stage4.fingerprint_file(args.source_manifest),
      "non_overlap_evidence": (
          "user_attested_distinct_source_traces"
          if ranges is None else "explicit_half_open_source_ranges"),
      "entries": output_entries,
  }
  proactive_stage4.validate_manifest(manifest)
  proactive_stage4.write_json_atomic(args.output, manifest)
  print("[OK] wrote {}".format(os.path.abspath(args.output)))


if __name__ == "__main__":
  main()
