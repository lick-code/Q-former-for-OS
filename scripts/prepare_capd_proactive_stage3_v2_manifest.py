#!/usr/bin/env python3
# coding=utf-8
"""Build a capacity_rule_v2 manifest from a completed v1 Stage-3 run.

The helper preserves the previous Train inputs, replaces every Validation
input explicitly, and records the previous Validation SHA-256 values as a
deny-list.  It never accepts or reads a formal Test manifest.
"""

import argparse
import copy
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_stage3


def parser():
  value = argparse.ArgumentParser()
  value.add_argument(
      "--previous-run-directory", required=True,
      help="Completed Stage-3 run containing input_manifest.json")
  value.add_argument(
      "--validation", action="append", required=True,
      metavar="WORKLOAD=PATH",
      help="Fresh post-rule-freeze Validation CSV; repeat once per workload")
  value.add_argument("--output", required=True)
  value.add_argument("--project-root", default=PROJECT_ROOT)
  return value


def _validation_map(values):
  result = {}
  for value in values:
    if "=" not in value:
      raise proactive_stage3.Stage3ContractError(
          "--validation must use WORKLOAD=PATH: {}".format(value))
    workload, path = value.split("=", 1)
    workload = workload.strip()
    path = path.strip()
    if not workload or not path or workload in result:
      raise proactive_stage3.Stage3ContractError(
          "Invalid or duplicate --validation value: {}".format(value))
    result[workload] = path
  return result


def main(argv=None):
  args = parser().parse_args(argv)
  project_root = os.path.abspath(args.project_root)
  previous_input_path = os.path.join(
      os.path.abspath(args.previous_run_directory), "input_manifest.json")
  if not os.path.isfile(previous_input_path):
    raise proactive_stage3.Stage3ContractError(
        "Previous input_manifest.json does not exist: {}".format(
            previous_input_path))
  previous = proactive_stage3.load_json(previous_input_path)
  if not isinstance(previous, dict) or not isinstance(
      previous.get("resolved_entries"), list):
    raise proactive_stage3.Stage3ContractError(
        "Previous run lacks resolved input provenance.")
  previous_manifest = previous.get("manifest")
  if not isinstance(previous_manifest, dict):
    raise proactive_stage3.Stage3ContractError(
        "Previous run lacks its source manifest.")
  if previous_manifest.get("test_used_for_parameter_selection") is not False:
    raise proactive_stage3.Stage3ContractError(
        "A run that used Test cannot seed a v2 manifest.")

  validation_paths = _validation_map(args.validation)
  entries_by_identity = {}
  previous_validation = {}
  workloads = set()
  for resolved in previous["resolved_entries"]:
    workload = resolved.get("workload")
    split = resolved.get("split")
    if split not in proactive_stage3.ALLOWED_SPLITS:
      raise proactive_stage3.Stage3ContractError(
          "Previous run contains a forbidden split.")
    identity = (workload, split)
    if identity in entries_by_identity:
      raise proactive_stage3.Stage3ContractError(
          "Previous run contains duplicate inputs: {}".format(identity))
    entries_by_identity[identity] = resolved
    workloads.add(workload)
    if split == "validation":
      fingerprint = resolved.get("trace_fingerprint")
      if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise proactive_stage3.Stage3ContractError(
            "Previous Validation fingerprint is missing for {}.".format(
                workload))
      previous_validation.setdefault(workload, []).append(fingerprint)

  if set(validation_paths) != workloads:
    raise proactive_stage3.Stage3ContractError(
        "Fresh Validation workloads must exactly match {}.".format(
            sorted(workloads)))

  new_entries = []
  for workload in sorted(workloads):
    train = entries_by_identity.get((workload, "train"))
    old_validation = entries_by_identity.get((workload, "validation"))
    if train is None or old_validation is None:
      raise proactive_stage3.Stage3ContractError(
          "{} lacks previous Train/Validation provenance.".format(workload))
    train_entry = {
        key: copy.deepcopy(train[key])
        for key in (
            "workload", "split", "role", "trace_path", "page_shift",
            "source_kind", "formal_test")}
    new_entries.append(train_entry)

    supplied_path = validation_paths[workload]
    resolved_path = (
        supplied_path if os.path.isabs(supplied_path)
        else os.path.join(project_root, supplied_path))
    resolved_path = os.path.abspath(resolved_path)
    if not os.path.isfile(resolved_path):
      raise proactive_stage3.Stage3ContractError(
          "Fresh Validation trace does not exist: {}".format(resolved_path))
    fingerprint = finals_config.fingerprint_file(resolved_path)
    previous_fingerprints = {
        item
        for values in previous_validation.values()
        for item in values}
    if fingerprint in previous_fingerprints:
      raise proactive_stage3.Stage3ContractError(
          "{} reuses a previous Validation trace.".format(workload))
    validation_entry = {
        key: copy.deepcopy(old_validation[key])
        for key in (
            "workload", "split", "role", "page_shift",
            "source_kind", "formal_test")}
    validation_entry["trace_path"] = supplied_path
    new_entries.append(validation_entry)

  output_path = os.path.abspath(args.output)
  if os.path.exists(output_path):
    raise proactive_stage3.Stage3ContractError(
        "Refusing to overwrite manifest: {}".format(output_path))
  manifest = {
      "schema_version": proactive_stage3.MANIFEST_SCHEMA,
      "calibration_kind": "real_train_fresh_validation_v2",
      "path_base": "project_root",
      "test_used_for_parameter_selection": False,
      "fresh_validation_attestation": {
          "capacity_rule_version": proactive_stage3.CAPACITY_RULE_VERSION,
          "rule_frozen_before_validation_selection": True,
          "fresh_validation_required": True,
          "validation_used_in_rule_design": False,
          "formal_test_reused": False,
          "previous_validation_trace_fingerprints": previous_validation,
      },
      "entries": new_entries,
  }
  proactive_stage3.validate_manifest(manifest)
  proactive_stage3.write_json(output_path, manifest)
  print(output_path)
  print("STAGE3_V2_FRESH_VALIDATION_MANIFEST_READY")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
