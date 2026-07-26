# coding=utf-8
"""Frozen-method post-Stage-6 optimization configuration helpers."""

from __future__ import print_function

import argparse
import copy

from qmap import finals_config
from qmap import finals_generator


FAMILY = "frozen_method_config_search"


def build_optimization_config(base_config, candidate, code_commit):
  """Build a manifest-bound train/valid-only optimization config."""
  config = copy.deepcopy(base_config)
  for key in ("stage5_variant", "stage6_variant", "bridge_variant"):
    config.pop(key, None)
  config["run_profile"] = finals_config.OPTIMIZATION_PROFILE
  config["validation"]["artifact_class"] = "optimization_only"
  config["validation"]["strategy"] = "independent_valid_trace"
  config["validation"]["require_data_manifest"] = True
  config["memory"]["dram_capacity_pages"] = int(candidate["D"])
  config["candidate"]["pool_size_B"] = int(candidate["B"])
  config["candidate"]["retained_K"] = int(candidate["K"])
  config["candidate"]["selector_history_Hc"] = int(candidate["Hc"])
  config["history"]["transformer_H"] = int(candidate["H"])
  config["labels"]["future_lookahead_L"] = int(candidate["L"])
  config["features"]["residency_scale_Lres"] = int(candidate["Lres"])
  config["optimization_variant"] = {
      "variant_id": candidate["config_id"],
      "family": FAMILY,
      "source_stage": "post_stage6_optimization",
      "only_difference": (
          "Only preregistered B/K/L/H configuration values may differ from "
          "the frozen Full control."),
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "retrain_required": True,
      "selection_inputs": ["train", "valid"],
      "code_commit": code_commit,
  }
  config.setdefault("run", {}).pop("resolved_config_fingerprint", None)
  finals_config.validate_config(config, require_resolved=True)
  config["run"]["resolved_config_fingerprint"] = (
      finals_config.config_fingerprint(config))
  finals_config.validate_config(config, require_resolved=True)
  return config


def generate_optimization_artifacts(
    base_config_path, candidate, roots, repo_root, code_commit):
  """Generate one O1 train/valid artifact bundle without opening test rows."""
  base = finals_config.load_config(
      base_config_path, require_resolved=True, project_root=repo_root,
      verify_manifest_files=False)
  config = build_optimization_config(base, candidate, code_commit)
  finals_config.write_json(roots["config"], config)
  finals_generator.fit_selector_and_generate(argparse.Namespace(
      config=roots["config"], selector_output=roots["selector"],
      validation_samples_output=roots["validation_samples"],
      train_output=roots["train"], valid_output=roots["valid"],
      summary_output=roots["summary"], page_shift=None,
      metadata_only_test=True))
  selector = finals_config.load_json(roots["selector"])
  manifest = {
      "schema_version": "capd_post_stage6_optimization_data_1",
      "status": "COMPLETED",
      "contract_id": finals_config.CONTRACT_ID,
      "workload": config["run"]["workload"],
      "config_id": candidate["config_id"],
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
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "optimization_variant": dict(config["optimization_variant"]),
  }
  finals_config.write_json(roots["manifest"], manifest)
  return manifest
