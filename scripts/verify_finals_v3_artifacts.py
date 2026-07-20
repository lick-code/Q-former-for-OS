# coding=utf-8
"""Verify stage-2 selector samples and reranker JSONL fingerprint bindings."""

from __future__ import print_function

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data


def validate_jsonl_rows(path, config):
  count = 0
  with open(path, "r", encoding="utf-8") as input_file:
    for line_number, line in enumerate(input_file, start=1):
      if not line.strip():
        continue
      row = json.loads(line)
      if row.get("schema_version") != finals_config.SCHEMA_VERSION:
        raise ValueError("{}:{} is not v3.".format(path, line_number))
      if row.get("contract_id") != finals_config.CONTRACT_ID:
        raise ValueError("{}:{} contract mismatch.".format(path, line_number))
      if row.get("workload_id") != config["run"]["workload"]:
        raise ValueError("{}:{} workload mismatch.".format(path, line_number))
      if "physical_address" in row:
        raise ValueError("{}:{} contains the v2 history field.".format(
            path, line_number))
      required = (
          "decision_index", "history_page_ids", "history_mask", "pc", "rw",
          "candidate_pages", "candidate_state_features", "candidate_mask",
          "original_pool_ranks", "inactivity", "coldness",
          "write_sensitivity")
      missing = [key for key in required if key not in row]
      if missing:
        raise ValueError("{}:{} missing fields {}.".format(
            path, line_number, missing))
      count += 1
  return count


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Verify generated CAPD v3 stage-2 artifacts.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--selector", required=True)
  parser.add_argument("--validation-samples", required=True)
  parser.add_argument("--train-jsonl", required=True)
  parser.add_argument("--valid-jsonl", required=True)
  parser.add_argument("--summary", required=True)
  parser.add_argument("--output", required=True)
  return parser


def main():
  args = build_arg_parser().parse_args()
  config = finals_config.load_config(args.config, require_resolved=True)
  selector = finals_config.load_json(args.selector)
  finals_config.validate_selector_params(config, selector)
  if (selector.get("validation_samples_fingerprint") !=
      finals_config.fingerprint_file(args.validation_samples)):
    raise ValueError("Selector validation-sample fingerprint mismatch.")
  artifacts = {}
  for split, path in (("train", args.train_jsonl),
                      ("valid", args.valid_jsonl)):
    metadata = finals_config.load_jsonl_metadata(
        path, config=config, split=split, selector_params=selector)
    row_count = validate_jsonl_rows(path, config)
    if row_count != int(metadata["sample_count"]):
      raise ValueError("{} JSONL row/metadata count mismatch.".format(split))
    artifacts[split] = {
        "path": finals_data.portable_path(path, PROJECT_ROOT),
        "fingerprint_sha256": finals_config.fingerprint_file(path),
        "metadata_fingerprint_sha256": finals_config.fingerprint_file(
            finals_config.metadata_path(path)),
        "sample_count": row_count,
    }
  summary = finals_config.load_json(args.summary)
  finals_config.validate_artifact_identity(
      config, summary, "generator summary")
  if summary.get("selector_fingerprint") != finals_config.selector_fingerprint(
      selector):
    raise ValueError("Generator summary/selector mismatch.")
  report = {
      "schema_version": "capd_finals_v3_stage2_artifact_audit_1",
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "contract_id": finals_config.CONTRACT_ID,
      "workload_id": config["run"]["workload"],
      "status": "PASSED",
      "verification_status": "VERIFIED",
      "config_fingerprint": finals_config.config_fingerprint(config),
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "validation_samples_fingerprint": finals_config.fingerprint_file(
          args.validation_samples),
      "artifacts": artifacts,
  }
  report.update(finals_config.artifact_identity_from_config(config))
  report["audit_fingerprint"] = finals_data.fingerprint_value(report)
  finals_config.write_json(args.output, report)
  print("[done] artifact_audit={}".format(args.output))
  print("[done] audit_fingerprint={}".format(
      report["audit_fingerprint"]))


if __name__ == "__main__":
  main()
