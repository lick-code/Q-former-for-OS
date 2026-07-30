#!/usr/bin/env python3
# coding=utf-8
"""Build a capacity_rule_v2 manifest from a completed v1 Stage-3 run.

The helper replaces every Train and Validation input explicitly and records
every previous Stage-3 Train/Validation SHA-256 as a deny-list.  It never
accepts or reads a formal Test manifest.
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
      "--train", action="append", required=True,
      metavar="WORKLOAD=PATH",
      help="Fresh Train CSV from the same new run as Validation; repeat once per workload")
  value.add_argument(
      "--validation", action="append", required=True,
      metavar="WORKLOAD=PATH",
      help="Fresh post-rule-freeze Validation CSV; repeat once per workload")
  value.add_argument("--output", required=True)
  value.add_argument("--project-root", default=PROJECT_ROOT)
  return value


def _input_map(values, option):
  result = {}
  for value in values:
    if "=" not in value:
      raise proactive_stage3.Stage3ContractError(
          "{} must use WORKLOAD=PATH: {}".format(option, value))
    workload, path = value.split("=", 1)
    workload = workload.strip()
    path = path.strip()
    if not workload or not path or workload in result:
      raise proactive_stage3.Stage3ContractError(
          "Invalid or duplicate {} value: {}".format(option, value))
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

  train_paths = _input_map(args.train, "--train")
  validation_paths = _input_map(args.validation, "--validation")
  entries_by_identity = {}
  previous_stage3_inputs = {}
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
    fingerprint = resolved.get("trace_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
      raise proactive_stage3.Stage3ContractError(
          "Previous Stage-3 input fingerprint is missing for {} {}.".format(
              workload, split))
    previous_stage3_inputs.setdefault(workload, []).append(fingerprint)

  if set(train_paths) != workloads or set(validation_paths) != workloads:
    raise proactive_stage3.Stage3ContractError(
        "Fresh Train/Validation workloads must exactly match {}.".format(
            sorted(workloads)))

  previous_fingerprints = {
      item
      for values in previous_stage3_inputs.values()
      for item in values}
  current_fingerprints = set()

  def fresh_entry(workload, split, template, supplied_path):
    resolved_path = (
        supplied_path if os.path.isabs(supplied_path)
        else os.path.join(project_root, supplied_path))
    resolved_path = os.path.abspath(resolved_path)
    if not os.path.isfile(resolved_path):
      raise proactive_stage3.Stage3ContractError(
          "Fresh {} trace does not exist: {}".format(split, resolved_path))
    fingerprint = finals_config.fingerprint_file(resolved_path)
    if fingerprint in previous_fingerprints:
      raise proactive_stage3.Stage3ContractError(
          "{} {} reuses a previous Stage-3 input trace.".format(
              workload, split))
    if fingerprint in current_fingerprints:
      raise proactive_stage3.Stage3ContractError(
          "Fresh Train/Validation traces must all be distinct.")
    current_fingerprints.add(fingerprint)
    result = {
        key: copy.deepcopy(template[key])
        for key in (
            "workload", "split", "role", "page_shift",
            "source_kind", "formal_test")}
    result["trace_path"] = supplied_path
    return result

  new_entries = []
  for workload in sorted(workloads):
    train = entries_by_identity.get((workload, "train"))
    old_validation = entries_by_identity.get((workload, "validation"))
    if train is None or old_validation is None:
      raise proactive_stage3.Stage3ContractError(
          "{} lacks previous Train/Validation provenance.".format(workload))
    new_entries.append(fresh_entry(
        workload, "train", train, train_paths[workload]))
    new_entries.append(fresh_entry(
        workload, "validation", old_validation,
        validation_paths[workload]))

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
          "fresh_train_required": True,
          "train_used_in_rule_design": False,
          "fresh_validation_required": True,
          "validation_used_in_rule_design": False,
          "formal_test_reused": False,
          "previous_stage3_input_trace_fingerprints":
              previous_stage3_inputs,
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
