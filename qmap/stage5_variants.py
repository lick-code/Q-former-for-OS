# coding=utf-8
"""Preregistered CAPD stage-5 variant identities and config construction.

This module is intentionally free of torch imports.  It is the single source of
truth for the stage-5 ablation/sensitivity matrix and for the only deviations
that the finals config validator may accept.
"""

from __future__ import print_function

import copy
import csv
import os

from qmap import finals_config


FULL_PARAMETERS = {
    "D": 64, "B": 64, "K": 8, "H": 10, "Hc": 256, "L": 256,
    "Lres": 256,
}
MODEL_SEEDS = (3136859, 42, 2026)
RANDOM_REPLAY_SEEDS = (0, 1, 2)
WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
SELECTOR_FEATURES = ("Delta", "A", "W", "C", "R")
UNIFORM_SELECTOR = (0.2, 0.2, 0.2, 0.2, 0.2)


def _spec(variant_id, family, difference, retrain=True, **changes):
  return {
      "variant_id": variant_id,
      "family": family,
      "only_difference": difference,
      "retrain_required": bool(retrain),
      "changes": dict(changes),
      "source_stage": "stage5",
      "test_used_for_selection": False,
  }


def core_ablation_specs():
  specs = [
      _spec(
          "no_filter_B8_K8", "ablation",
          "B=K=8 and P_t=C_t; bypass B-to-K selection",
          B=8, K=8, selection_mode="identity_P_t_equals_C_t"),
  ]
  for feature in SELECTOR_FEATURES:
    specs.append(_spec(
        "selector_drop_{}".format(feature), "ablation",
        "stage3 B64 leave-one-out selector fixes {} weight to zero".format(
            feature),
        selector_drop=feature))
  specs.extend([
      _spec(
          "no_position_encoding", "ablation",
          "position_encoding=none; history and all other model inputs retained",
          position_encoding="none"),
      _spec(
          "no_candidate_state", "ablation",
          "zero only the four candidate-state channels; retain page embedding",
          candidate_state="zeros"),
      _spec(
          "history_mean_pool", "ablation",
          "masked mean of Transformer history; no candidate-history attention",
          context_mode="history_mean_pool"),
      _spec(
          "no_future_write", "ablation",
          "lambda_w=0; labels are d_hat+q_hat; future window unchanged",
          lambda_w=0.0),
  ])
  return specs


def sensitivity_specs():
  specs = []
  for value in (16, 32):
    specs.append(_spec(
        "sensitivity_B{}".format(value), "sensitivity",
        "only B changes from 64 to {}".format(value), B=value))
  for value in (4, 16):
    specs.append(_spec(
        "sensitivity_K{}".format(value), "sensitivity",
        "only K changes from 8 to {}".format(value), K=value))
  for value in (5, 20):
    specs.append(_spec(
        "sensitivity_H{}".format(value), "sensitivity",
        "only H changes from 10 to {}".format(value), H=value))
  for value in (64, 128, 512):
    specs.append(_spec(
        "sensitivity_Hc{}".format(value), "sensitivity",
        "only Hc changes from 256 to {}".format(value), Hc=value))
  for value in (64, 128, 512):
    specs.append(_spec(
        "sensitivity_L{}".format(value), "sensitivity",
        "only L changes from 256 to {}".format(value), L=value))
  return specs


def all_variant_specs():
  specs = core_ablation_specs() + sensitivity_specs()
  result = {item["variant_id"]: item for item in specs}
  if len(result) != len(specs):
    raise AssertionError("Stage-5 variant ids must be unique.")
  return result


def get_variant_spec(variant_id):
  if variant_id == "sensitivity_B8":
    # The protocol requires this point to share the no-filter artifact.
    variant_id = "no_filter_B8_K8"
  try:
    return copy.deepcopy(all_variant_specs()[variant_id])
  except KeyError:
    raise ValueError("Unknown stage-5 variant: {}".format(variant_id))


def config_parameters(config):
  return {
      "D": int(config["memory"]["dram_capacity_pages"]),
      "B": int(config["candidate"]["pool_size_B"]),
      "K": int(config["candidate"]["retained_K"]),
      "H": int(config["history"]["transformer_H"]),
      "Hc": int(config["candidate"]["selector_history_Hc"]),
      "L": int(config["labels"]["future_lookahead_L"]),
      "Lres": int(config["features"]["residency_scale_Lres"]),
  }


def build_variant_config(base_config, spec):
  """Returns a resolved, fingerprinted config for one preregistered variant."""
  config = copy.deepcopy(base_config)
  changes = spec["changes"]
  if "B" in changes:
    config["candidate"]["pool_size_B"] = int(changes["B"])
  if "K" in changes:
    config["candidate"]["retained_K"] = int(changes["K"])
  if "H" in changes:
    config["history"]["transformer_H"] = int(changes["H"])
  if "Hc" in changes:
    config["candidate"]["selector_history_Hc"] = int(changes["Hc"])
  if "L" in changes:
    config["labels"]["future_lookahead_L"] = int(changes["L"])
    config["validation"]["guard_accesses"] = int(changes["L"])
  if "position_encoding" in changes:
    config["model"]["position_encoding"] = changes["position_encoding"]
  if "lambda_w" in changes:
    config["labels"]["lambda_w"] = float(changes["lambda_w"])

  config["stage5_variant"] = {
      key: copy.deepcopy(spec[key]) for key in (
          "variant_id", "family", "only_difference", "source_stage",
          "test_used_for_selection", "retrain_required")
  }
  if spec["variant_id"] == "no_filter_B8_K8":
    config["stage5_variant"]["shared_sensitivity_alias"] = "sensitivity_B8"
  config.setdefault("run", {}).pop("resolved_config_fingerprint", None)
  finals_config.validate_config(config, require_resolved=True)
  config["run"]["resolved_config_fingerprint"] = (
      finals_config.config_fingerprint(config))
  finals_config.validate_config(config, require_resolved=True)
  return config


def _stage3_loo_row(csv_path, workload, feature):
  with open(csv_path, "r", encoding="utf-8", newline="") as input_file:
    rows = list(csv.DictReader(input_file))
  matches = [
      row for row in rows
      if row.get("workload") == workload and row.get("B") == "64" and
      row.get("kind") == "leave_one_out" and row.get("feature") == feature and
      row.get("run_status") == "PASSED"]
  if len(matches) != 1:
    raise ValueError(
        "Expected exactly one passed stage-3 B64 LOO row for {}/{}; got {}."
        .format(workload, feature, len(matches)))
  return matches[0]


def stage3_loo_weights(csv_path, workload, feature):
  row = _stage3_loo_row(csv_path, workload, feature)
  weights = tuple(float(row[name]) for name in SELECTOR_FEATURES)
  if abs(sum(weights) - 1.0) > 1e-8:
    raise ValueError("Stage-3 LOO weights do not sum to one.")
  removed_index = SELECTOR_FEATURES.index(feature)
  if weights[removed_index] != 0.0:
    raise ValueError("Stage-3 LOO removed-feature weight is not zero.")
  return weights


def build_bound_selector(
    base_selector, config, spec, stage3_ablation_csv=None,
    command="stage5 selector binding"):
  """Rebinds a frozen selector to a variant config without using test data."""
  selector = copy.deepcopy(base_selector)
  selector["config_fingerprint"] = finals_config.config_fingerprint(config)
  selector["workload"] = config["run"]["workload"]
  selector["workload_id"] = config["run"]["workload"]
  selector["command"] = command
  selector["stage5_variant_id"] = spec["variant_id"]
  selector["stage5_selector_source"] = "frozen_full_selector"
  selector["test_trace_opened"] = False
  selector["test_used_for_selection"] = False

  feature = spec["changes"].get("selector_drop")
  if feature is not None:
    if not stage3_ablation_csv:
      raise ValueError("selector_drop requires the stage-3 ablation CSV.")
    row = _stage3_loo_row(
        stage3_ablation_csv, config["run"]["workload"], feature)
    weights = tuple(float(row[name]) for name in SELECTOR_FEATURES)
    selector["stage5_selector_source"] = "stage3_B64_leave_one_out"
    selector["stage3_ablation_csv"] = os.path.abspath(stage3_ablation_csv)
    selector["stage3_ablation_row_fingerprint"] = (
        finals_config.fingerprint_value(row))
    for metric in (
        "SelectorRecall@K", "EndToEndRecall@K", "TieCoverage@K", "NRegret"):
      delta_key = "delta_{}".format(metric)
      if row.get(delta_key) not in (None, ""):
        selector[metric] = float(base_selector[metric]) + float(row[delta_key])
    selector["Recall@K"] = selector["SelectorRecall@K"]
  else:
    weights = tuple(float(selector["w_{}".format(name)])
                    for name in SELECTOR_FEATURES)
  for name, value in zip(SELECTOR_FEATURES, weights):
    selector["w_{}".format(name)] = float(value)
  finals_config.validate_selector_params(config, selector)
  return selector


def validate_uniform_identity(full_selector, uniform_selector):
  full = tuple(float(full_selector["w_{}".format(name)])
               for name in SELECTOR_FEATURES)
  uniform = tuple(float(uniform_selector["w_{}".format(name)])
                  for name in SELECTOR_FEATURES)
  if full != UNIFORM_SELECTOR or uniform != UNIFORM_SELECTOR:
    raise ValueError("Uniform selector identity control is not degenerate.")
  if finals_config.selector_fingerprint(full_selector) != (
      finals_config.selector_fingerprint(uniform_selector)):
    raise ValueError(
        "Uniform identity control must reference the exact Full selector.")
  return {
      "control": "uniform_selector",
      "classification": "degenerate_identity_control",
      "candidate_sets_equivalent_by_identity": True,
      "independent_performance_job": False,
  }


def variant_requires_fresh_selector(spec):
  """Whether train/valid selector statistics must be recomputed."""
  if spec["variant_id"] == "no_filter_B8_K8":
    return False
  changes = spec["changes"]
  return any(key in changes for key in ("B", "K", "Hc", "L", "lambda_w"))


def variant_manifest(
    spec, config, selector_path, selector_fingerprint, trace_fingerprints,
    jsonl_fingerprints, checkpoint_fingerprint, model_seed, replay_seed,
    code_commit, command, official, upstream):
  return {
      "variant_id": spec["variant_id"],
      "only_difference": spec["only_difference"],
      "contract_id": finals_config.CONTRACT_ID,
      "schema_version": finals_config.SCHEMA_VERSION,
      "workload": config["run"]["workload"],
      "parameters": config_parameters(config),
      "selector_path": selector_path,
      "selector_fingerprint": selector_fingerprint,
      "trace_fingerprints": dict(trace_fingerprints),
      "jsonl_fingerprints": dict(jsonl_fingerprints or {}),
      "checkpoint_fingerprint": checkpoint_fingerprint,
      "model_seed": model_seed,
      "replay_seed": replay_seed,
      "cost_model": copy.deepcopy(config["cost_model"]),
      "code_commit": code_commit,
      "command": command,
      "artifact_class": "official" if official else "pilot",
      "test_trace_opened": bool(replay_seed is not None),
      "test_used_for_selection": False,
      "training_source": upstream,
      "run_status": "PLANNED",
  }
