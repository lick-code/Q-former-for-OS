# coding=utf-8
"""Configuration helpers for the train/valid-only R1 pressure diagnostic."""

from __future__ import print_function

import argparse
import copy
import os

from qmap import finals_config
from qmap import finals_generator


FAMILY = "frozen_method_pressure_headroom"
SOURCE_STAGE = "post_stage6_r1_pressure_headroom"
SCIENTIFIC_ROLE = "train_valid_only_pressure_opportunity_diagnostic"
FIXED = {"H": 10, "Hc": 256, "L": 256, "Lres": 256}
PRESSURE_POINTS = (
    {"case_id": "pressure_D16", "D": 16, "B": 16, "K": 8},
    {"case_id": "pressure_D32", "D": 32, "B": 32, "K": 8},
    {"case_id": "pressure_D64", "D": 64, "B": 64, "K": 8},
)


def pressure_point(case_id):
  matches = [row for row in PRESSURE_POINTS if row["case_id"] == case_id]
  if len(matches) != 1:
    raise ValueError("Unknown R1 pressure point: {}".format(case_id))
  return copy.deepcopy(matches[0])


def validate_pressure_point(point):
  expected = pressure_point(point["case_id"])
  actual = {
      key: (str(point[key]) if key == "case_id" else int(point[key]))
      for key in ("case_id", "D", "B", "K")}
  if actual != expected:
    raise ValueError(
        "R1 pressure point differs from the preregistered matrix: "
        "expected={} actual={}.".format(expected, actual))
  if not (0 < actual["K"] <= actual["B"] <= actual["D"]):
    raise ValueError("R1 requires K <= B <= D.")
  return actual


def build_pressure_config(base_config, point, repo_root, git_commit):
  """Build a diagnostic-only config bound to existing train/valid inputs."""
  point = validate_pressure_point(point)
  config = copy.deepcopy(base_config)
  for key in (
      "stage5_variant", "stage6_variant", "bridge_variant",
      "optimization_variant", "pressure_variant"):
    config.pop(key, None)
  config["run_profile"] = finals_config.DIAGNOSTIC_PROFILE
  config["memory"]["dram_capacity_pages"] = point["D"]
  config["candidate"]["pool_size_B"] = point["B"]
  config["candidate"]["retained_K"] = point["K"]
  config["candidate"]["selector_history_Hc"] = FIXED["Hc"]
  config["history"]["transformer_H"] = FIXED["H"]
  config["labels"]["future_lookahead_L"] = FIXED["L"]
  config["features"]["residency_scale_Lres"] = FIXED["Lres"]
  config.setdefault("sweep", {})["pool_sizes_B"] = [8, 16, 32, 64]
  config["validation"].update({
      "strategy": "independent_valid_trace",
      "require_data_manifest": False,
      "artifact_class": "diagnostic_only",
      "data_quality_profile":
          "configs/finals/capd_r1_pressure_headroom_profile.json",
  })
  config["pressure_variant"] = {
      "case_id": point["case_id"],
      "family": FAMILY,
      "source_stage": SOURCE_STAGE,
      "scientific_role": SCIENTIFIC_ROLE,
      "only_difference": (
          "Only the preregistered matched pressure point D=B changes; "
          "K/H/Hc/L/Lres, features, labels, loss and cost remain frozen."),
      "D": point["D"],
      "B": point["B"],
      "K": point["K"],
      "H": FIXED["H"],
      "Hc": FIXED["Hc"],
      "L": FIXED["L"],
      "Lres": FIXED["Lres"],
      "evaluation_inputs": ["train", "valid"],
      "retrain_required": False,
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }
  run = config.setdefault("run", {})
  for key in (
      "base_config_fingerprint", "source_manifest_fingerprint",
      "data_quality_profile_id", "data_quality_profile_fingerprint",
      "data_quality_report_fingerprint", "resolved_config_fingerprint"):
    run.pop(key, None)
  run.update({
      "project_root": os.path.abspath(repo_root),
      "git_commit": git_commit,
      "r1_pressure_case_id": point["case_id"],
  })
  finals_config.validate_config(config, require_resolved=True)
  run["resolved_config_fingerprint"] = finals_config.config_fingerprint(config)
  finals_config.validate_config(config, require_resolved=True)
  return config


def generate_pressure_artifacts(
    base_config_path, point, roots, repo_root, git_commit):
  """Fit the selector and generate train/valid-only diagnostic artifacts."""
  base = finals_config.load_config(
      base_config_path, require_resolved=True, project_root=repo_root,
      verify_manifest_files=False)
  config = build_pressure_config(base, point, repo_root, git_commit)
  finals_config.write_json(roots["config"], config)
  finals_generator.fit_selector_and_generate(argparse.Namespace(
      config=roots["config"], selector_output=roots["selector"],
      validation_samples_output=roots["validation_samples"],
      train_output=roots["train"], valid_output=roots["valid"],
      summary_output=roots["summary"], page_shift=None,
      metadata_only_test=True))
  selector = finals_config.load_json(roots["selector"])
  manifest = {
      "schema_version": "capd_r1_pressure_data_1",
      "status": "COMPLETED",
      "contract_id": finals_config.CONTRACT_ID,
      "workload": config["run"]["workload"],
      "case_id": point["case_id"],
      "pressure_variant": dict(config["pressure_variant"]),
      "config_fingerprint": finals_config.config_fingerprint(config),
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "train_jsonl_fingerprint":
          finals_config.fingerprint_file(roots["train"]),
      "valid_jsonl_fingerprint":
          finals_config.fingerprint_file(roots["valid"]),
      "train_trace_fingerprint": config["data"]["split_fingerprints"]["train"],
      "valid_trace_fingerprint": config["data"]["split_fingerprints"]["valid"],
      "test_trace_fingerprint_metadata_only":
          config["data"]["split_fingerprints"]["test"],
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }
  finals_config.write_json(roots["manifest"], manifest)
  return manifest
