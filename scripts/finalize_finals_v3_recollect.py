# coding=utf-8
"""Finalize one verified recollection as sealed CAPD finals-v3 data."""

from __future__ import print_function

import argparse
import copy
import os
import shlex
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data


RECOLLECT_SCHEMA = "capd_finals_v3_recollect_source_spec_v1"


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Materialize, manifest, audit, and seal one verified finals-v3 "
          "recollection without overwriting existing artifacts."))
  parser.add_argument("--recollect-spec", required=True)
  parser.add_argument("--workload", required=True)
  for split in finals_data.REQUIRED_SPLITS:
    parser.add_argument("--{}-start".format(split), type=int, required=True)
    parser.add_argument("--{}-end".format(split), type=int, required=True)
  parser.add_argument(
      "--config", default="configs/finals/capd_direction1_v3.json")
  parser.add_argument(
      "--profile", default="configs/finals/capd_stage2_data_profile.json")
  parser.add_argument("--git-commit", required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  return parser


def _require_keys(value, keys, label):
  missing = [key for key in keys if key not in value]
  if missing:
    raise ValueError("{} is missing: {}".format(label, ", ".join(missing)))


def _target_paths(repo_root, workload):
  processed_dir = os.path.join(
      repo_root, "dataset", "processed", "finals_v3_official", workload)
  metadata_dir = os.path.join(
      repo_root, "dataset", "metadata", "finals_v3_official")
  return {
      "processed_dir": processed_dir,
      "splits": {
          split: os.path.join(processed_dir, "{}.csv".format(split))
          for split in finals_data.REQUIRED_SPLITS
      },
      "source_spec": os.path.join(
          repo_root, "dataset", "metadata", "finals_v3_source_specs",
          "{}.json".format(workload)),
      "manifest": os.path.join(metadata_dir, "{}.json".format(workload)),
      "report": os.path.join(
          metadata_dir, "reports", "{}.json".format(workload)),
  }


def _assert_fresh_targets(paths):
  files = list(paths["splits"].values()) + [
      paths["source_spec"], paths["manifest"], paths["report"]]
  existing = [path for path in files if os.path.exists(path)]
  if existing:
    raise FileExistsError(
        "Refusing to overwrite existing official artifacts: {}".format(
            ", ".join(existing)))


def _validated_recollection(path, repo_root, workload):
  absolute = finals_data.resolve_path(path, repo_root)
  recollect = finals_data.load_json(absolute)
  _require_keys(recollect, (
      "schema_version", "status", "canonical_workload", "raw_trace",
      "raw_trace_records", "raw_trace_sha256", "collector_argv",
      "dynamorio_version", "started_at_utc", "host", "parsec_git",
      "project_git", "input_class", "input_path", "input_sha256",
      "source_archive", "source_archive_sha256", "source_image",
      "source_layer_sha256", "binary_path", "binary_sha256",
      "runconf_path", "runconf_sha256", "collector_path",
      "collector_sha256"), "recollection source spec")
  if recollect["schema_version"] != RECOLLECT_SCHEMA:
    raise ValueError("Unsupported recollection source-spec schema.")
  if recollect["status"] != "complete":
    raise ValueError("Recollection is not complete.")
  if recollect["canonical_workload"] != workload:
    raise ValueError("Recollection/workload mismatch.")
  raw_path = finals_data.resolve_path(recollect["raw_trace"], repo_root)
  scan = finals_data.scan_trace(
      raw_path, int(recollect.get("page_shift", 12)),
      require_real_rw=True, collect=False)
  if scan["access_count"] != int(recollect["raw_trace_records"]):
    raise ValueError("Recollection raw-trace record count mismatch.")
  if scan["fingerprint_sha256"] != recollect["raw_trace_sha256"]:
    raise ValueError("Recollection raw-trace SHA-256 mismatch.")
  return absolute, recollect, raw_path, scan


def _build_source_spec(recollect_path, recollect, raw_path, workload,
                       paths, intervals, repo_root):
  collection_id = "{}-{}".format(workload, recollect["run_id"])
  environment = {
      "recollect_source_spec": finals_data.portable_path(
          recollect_path, repo_root),
      "recollect_source_spec_sha256": finals_data.fingerprint_file(
          recollect_path),
      "host": copy.deepcopy(recollect["host"]),
      "parsec_git": copy.deepcopy(recollect["parsec_git"]),
      "project_git": copy.deepcopy(recollect["project_git"]),
      "input": {
          "class": recollect["input_class"],
          "path": recollect["input_path"],
          "fingerprint_sha256": recollect["input_sha256"],
          "source_archive": recollect["source_archive"],
          "source_archive_fingerprint_sha256": recollect[
              "source_archive_sha256"],
          "source_image": recollect["source_image"],
          "source_layer_sha256": recollect["source_layer_sha256"],
      },
      "binary": {
          "path": recollect["binary_path"],
          "fingerprint_sha256": recollect["binary_sha256"],
      },
      "runconf": {
          "path": recollect["runconf_path"],
          "fingerprint_sha256": recollect["runconf_sha256"],
      },
      "collector": {
          "path": recollect["collector_path"],
          "fingerprint_sha256": recollect["collector_sha256"],
      },
  }
  splits = {
      split: {
          "path": finals_data.portable_path(paths["splits"][split], repo_root),
          "collection_id": collection_id,
          "source_access_interval": {
              "start_inclusive": intervals[split][0],
              "end_exclusive": intervals[split][1],
          },
      }
      for split in finals_data.REQUIRED_SPLITS
  }
  return {
      "schema_version": finals_data.SOURCE_SPEC_SCHEMA,
      "contract_id": finals_data.CONTRACT_ID,
      "workload_id": workload,
      "page_shift": int(recollect.get("page_shift", 12)),
      "rw_source": {
          "kind": "trace_column", "column": "RW", "verified_real": True,
      },
      "split_strategy": (
          "explicit chronological non-overlapping half-open intervals from "
          "one verified real-RW recollection"),
      "collections": [{
          "collection_id": collection_id,
          "source_trace": finals_data.portable_path(raw_path, repo_root),
          "tool": "DynamoRIO drmemtrace {}".format(
              recollect["dynamorio_version"]),
          "command": shlex.join(str(value) for value in
                                  recollect["collector_argv"]),
          "collected_at": recollect["started_at_utc"],
          "source_label": "finals_v3_recollect/{}".format(
              recollect["phase"]),
          "environment": environment,
          "provenance_complete": True,
      }],
      "splits": splits,
  }


def main():
  args = build_arg_parser().parse_args()
  repo_root = os.path.abspath(args.repo_root)
  config_path = finals_data.resolve_path(args.config, repo_root)
  profile_path = finals_data.resolve_path(args.profile, repo_root)
  config = finals_config.load_config(config_path)
  if args.workload not in config["workloads"]:
    raise ValueError("Workload is absent from the official v3 config.")
  intervals = {
      split: (
          getattr(args, "{}_start".format(split)),
          getattr(args, "{}_end".format(split)))
      for split in finals_data.REQUIRED_SPLITS
  }
  for split, interval in intervals.items():
    if interval[0] < 0 or interval[1] <= interval[0]:
      raise ValueError("Invalid {} interval: {}".format(split, interval))

  paths = _target_paths(repo_root, args.workload)
  _assert_fresh_targets(paths)
  recollect_path, recollect, raw_path, raw_scan = _validated_recollection(
      args.recollect_spec, repo_root, args.workload)
  for split, interval in intervals.items():
    if interval[1] > raw_scan["access_count"]:
      raise ValueError("{} interval exceeds the recollection.".format(split))

  finals_data.materialize_source_intervals(
      raw_path, paths["splits"], intervals,
      int(recollect.get("page_shift", 12)))
  source_spec = _build_source_spec(
      recollect_path, recollect, raw_path, args.workload,
      paths, intervals, repo_root)
  finals_data.write_json(paths["source_spec"], source_spec)
  manifest = finals_data.build_source_manifest(
      source_spec, repo_root, args.git_commit)
  finals_data.write_json(paths["manifest"], manifest)

  profile = finals_data.load_json(profile_path)
  report = finals_data.audit_source_manifest(
      paths["manifest"], repo_root, config, profile)
  finals_data.write_json(paths["report"], report)
  if report["status"] != "PASSED":
    raise RuntimeError(
        "Official data quality gate did not pass: {}".format(
            report["status"]))
  finals_data.update_manifest_quality_gate(
      paths["manifest"], paths["report"], repo_root, report)
  finals_data.load_source_manifest(
      paths["manifest"], repo_root, verify_files=True,
      require_quality_pass=True, expected_workload=args.workload)

  print("[done] workload={}".format(args.workload))
  print("[done] source_trace_sha256={}".format(
      raw_scan["fingerprint_sha256"]))
  for split in finals_data.REQUIRED_SPLITS:
    print("[done] {}={} interval={}-{}".format(
        split, paths["splits"][split], intervals[split][0],
        intervals[split][1]))
  print("[done] source_spec={}".format(paths["source_spec"]))
  print("[done] manifest={}".format(paths["manifest"]))
  print("[done] report={}".format(paths["report"]))
  print("[done] status={}".format(report["status"]))
  print("[done] audit_fingerprint={}".format(
      report["audit_fingerprint"]))


if __name__ == "__main__":
  main()
