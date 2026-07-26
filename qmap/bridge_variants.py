# coding=utf-8
"""Frozen post-hoc bridge diagnostics between legacy and official CAPD runs.

The bridge is deliberately not a new official stage and is never eligible for
method or hyperparameter selection.  It changes one factor at a time on the
streamcluster pressure case so a headline-result difference can be attributed
to the legacy/current engine, candidate selection, trace source, or capacity.
"""

from __future__ import print_function

import copy
import os

from qmap import finals_config


WORKLOAD = "streamcluster_pressure"
MODEL_SEEDS = (3136859, 42, 2026)
RANDOM_REPLAY_SEEDS = (0, 1, 2)
CLASSIC_POLICIES = ("lru", "random", "lfu", "clock")

SOURCE_SPECS = {
    "legacy_pressure_window": {
        "display": "legacy selected pressure window",
        "source_manifest":
            "dataset/metadata/real_workload_suite_pressure_manifest.json",
        "train_trace": (
            "dataset/processed/real_workload_suite_pressure/selected/"
            "parsec_streamcluster_train.csv"),
        "valid_trace": (
            "dataset/processed/real_workload_suite_pressure/selected/"
            "parsec_streamcluster_valid.csv"),
        "test_trace": (
            "dataset/processed/real_workload_suite_pressure/selected/"
            "parsec_streamcluster_test.csv"),
        "expected_access_counts": {
            "train": 270000, "valid": 100000, "test": 200000},
        "provenance_class": "legacy_published_pressure_window",
    },
    "official_recollection": {
        "display": "finals_v3 official recollection",
        "source_manifest":
            "dataset/metadata/finals_v3_official/streamcluster_pressure.json",
        "train_trace": (
            "dataset/processed/finals_v3_official/"
            "streamcluster_pressure/train.csv"),
        "valid_trace": (
            "dataset/processed/finals_v3_official/"
            "streamcluster_pressure/valid.csv"),
        "test_trace": (
            "dataset/processed/finals_v3_official/"
            "streamcluster_pressure/test.csv"),
        "expected_access_counts": {
            "train": 600000, "valid": 200000, "test": 200000},
        "provenance_class": "sealed_finals_v3_official",
    },
}

COMPUTE_CASES = (
    {
        "case_id": "legacy_current_identity_D16_B8K8",
        "source_id": "legacy_pressure_window",
        "D": 16, "B": 8, "K": 8,
        "engine": "current_capd_mic_1_0",
        "candidate_mode": "identity_P_equals_C",
        "only_difference": (
            "current engine on legacy pressure window with D=16 and B=K=8"),
    },
    {
        "case_id": "legacy_current_selector_D16_B16K8",
        "source_id": "legacy_pressure_window",
        "D": 16, "B": 16, "K": 8,
        "engine": "current_capd_mic_1_0",
        "candidate_mode": "selector_B_to_K",
        "only_difference": (
            "enable current B-to-K selector: B changes from 8 to 16"),
    },
    {
        "case_id": "official_current_selector_D16_B16K8",
        "source_id": "official_recollection",
        "D": 16, "B": 16, "K": 8,
        "engine": "current_capd_mic_1_0",
        "candidate_mode": "selector_B_to_K",
        "only_difference": (
            "trace source changes from legacy window to official recollection"),
    },
)

IMPORTED_CASES = (
    {
        "case_id": "legacy_published_D16_B8K8",
        "source_id": "legacy_pressure_window",
        "D": 16, "B": 8, "K": 8,
        "engine": "legacy_published_pipeline",
        "candidate_mode": "legacy_lru_tail_8",
        "only_difference": "frozen published legacy evidence",
    },
    {
        "case_id": "official_current_full_D64_B64K8",
        "source_id": "official_recollection",
        "D": 64, "B": 64, "K": 8,
        "engine": "current_capd_mic_1_0",
        "candidate_mode": "selector_B_to_K",
        "only_difference": "frozen Stage-5 Full evidence at D=64",
    },
)

ATTRIBUTION_CHAIN = (
    {
        "factor": "engine_and_pipeline",
        "left": "legacy_published_D16_B8K8",
        "right": "legacy_current_identity_D16_B8K8",
    },
    {
        "factor": "candidate_selector",
        "left": "legacy_current_identity_D16_B8K8",
        "right": "legacy_current_selector_D16_B16K8",
    },
    {
        "factor": "trace_source",
        "left": "legacy_current_selector_D16_B16K8",
        "right": "official_current_selector_D16_B16K8",
    },
    {
        "factor": "dram_capacity_and_feasible_pool",
        "left": "official_current_selector_D16_B16K8",
        "right": "official_current_full_D64_B64K8",
    },
)


def source_spec(source_id):
  try:
    return copy.deepcopy(SOURCE_SPECS[source_id])
  except KeyError:
    raise ValueError("Unknown bridge source: {}".format(source_id))


def compute_case(case_id):
  matches = [item for item in COMPUTE_CASES if item["case_id"] == case_id]
  if len(matches) != 1:
    raise ValueError("Unknown bridge compute case: {}".format(case_id))
  return copy.deepcopy(matches[0])


def all_cases():
  return [
      copy.deepcopy(item) for item in IMPORTED_CASES + COMPUTE_CASES]


def _absolute(repo_root, path):
  return path if os.path.isabs(path) else os.path.join(repo_root, path)


def trace_fingerprints(repo_root, source_id):
  source = source_spec(source_id)
  return {
      split: finals_config.fingerprint_file(
          _absolute(repo_root, source["{}_trace".format(split)]))
      for split in ("train", "valid", "test")
  }


def build_bridge_config(base_config, case, repo_root, git_commit):
  """Builds a diagnostic-only v3 config with independent validation."""
  case = compute_case(case["case_id"])
  source = source_spec(case["source_id"])
  config = copy.deepcopy(base_config)
  config.pop("stage5_variant", None)
  config.pop("stage6_variant", None)
  config["run_profile"] = finals_config.DIAGNOSTIC_PROFILE
  config["memory"]["dram_capacity_pages"] = int(case["D"])
  config["candidate"]["pool_size_B"] = int(case["B"])
  config["candidate"]["retained_K"] = int(case["K"])
  config["sweep"]["pool_sizes_B"] = [8, 16, 32, 64]
  config["validation"].update({
      "strategy": "independent_valid_trace",
      "require_data_manifest": False,
      "artifact_class": "diagnostic_only",
      "data_quality_profile":
          "configs/finals/capd_bridge_diagnostic_profile.json",
  })
  config["data"] = {
      "train_trace": source["train_trace"],
      "valid_trace": source["valid_trace"],
      "test_trace": source["test_trace"],
      "source_manifest": source["source_manifest"],
  }
  fingerprints = trace_fingerprints(repo_root, case["source_id"])
  config["data"]["split_fingerprints"] = copy.deepcopy(fingerprints)
  manifest_path = _absolute(repo_root, source["source_manifest"])
  config["bridge_variant"] = {
      "case_id": case["case_id"],
      "source_id": case["source_id"],
      "source_manifest": source["source_manifest"],
      "source_manifest_fingerprint":
          finals_config.fingerprint_file(manifest_path),
      "source_provenance_class": source["provenance_class"],
      "engine": case["engine"],
      "candidate_mode": case["candidate_mode"],
      "only_difference": case["only_difference"],
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
      "test_used_for_selection": False,
      "D": int(case["D"]), "B": int(case["B"]), "K": int(case["K"]),
  }
  config["workloads"] = {
      WORKLOAD: {
          "train_trace": source["train_trace"],
          "valid_trace": source["valid_trace"],
          "test_trace": source["test_trace"],
          "source_manifest": source["source_manifest"],
      }}
  run = config.setdefault("run", {})
  for key in (
      "base_config_fingerprint", "source_manifest",
      "source_manifest_fingerprint", "data_quality_profile_id",
      "data_quality_profile_fingerprint",
      "data_quality_report_fingerprint", "resolved_config_fingerprint"):
    run.pop(key, None)
  run.update({
      "workload": WORKLOAD,
      "project_root": os.path.abspath(repo_root),
      "git_commit": git_commit,
      "split_fingerprints": copy.deepcopy(fingerprints),
      "bridge_case_id": case["case_id"],
      "bridge_source_id": case["source_id"],
  })
  finals_config.validate_config(config, require_resolved=True)
  run["resolved_config_fingerprint"] = finals_config.config_fingerprint(config)
  finals_config.validate_config(config, require_resolved=True)
  return config

