# coding=utf-8
"""Strict configuration pairing for the CAPD NoVPN ablation.

The official v3 JSONL and selector artifacts stay bound to the sealed full
CAPD resolved configuration. Experiment configurations may differ only in the
declared experiment name, page-ID embedding switch, and isolated output roots.
This module validates that relationship before those immutable data artifacts
are reused.
"""

from __future__ import print_function

import copy
import os

from qmap import finals_config


ALLOWED_CONFIG_DIFFS = frozenset((
    ("experiment_name",),
    ("model", "use_page_id_embedding"),
    ("outputs", "checkpoint_root"),
    ("outputs", "result_root"),
    ("outputs", "log_root"),
))
DERIVED_RESOLVED_DIFFS = frozenset((
    ("run", "base_config_fingerprint"),
    ("run", "resolved_config_fingerprint"),
))
VARIANTS = ("full", "no_vpn")


def _leaf_values(value, prefix=()):
  if isinstance(value, dict):
    result = {}
    for key in sorted(value):
      result.update(_leaf_values(value[key], prefix + (key,)))
    return result
  return {prefix: value}


def config_differences(left, right):
  """Returns leaf-level differences as path -> (left, right)."""
  left_values = _leaf_values(left)
  right_values = _leaf_values(right)
  paths = sorted(set(left_values) | set(right_values))
  return {
      path: (left_values.get(path), right_values.get(path))
      for path in paths
      if left_values.get(path) != right_values.get(path)
  }


def variant_from_config(config):
  return ("full" if finals_config.use_page_id_embedding(config)
          else "no_vpn")


def assert_config_pair(full_config, no_vpn_config, allow_resolved=False):
  """Hard-fails unless the pair is a strict single-variable experiment."""
  finals_config.validate_config(full_config, require_resolved=allow_resolved)
  finals_config.validate_config(no_vpn_config, require_resolved=allow_resolved)
  if not finals_config.use_page_id_embedding(full_config):
    raise ValueError("Full config must enable page-ID embeddings.")
  if finals_config.use_page_id_embedding(no_vpn_config):
    raise ValueError("NoVPN config must disable page-ID embeddings.")
  allowed = set(ALLOWED_CONFIG_DIFFS)
  if allow_resolved:
    allowed.update(DERIVED_RESOLVED_DIFFS)
  differences = config_differences(full_config, no_vpn_config)
  unexpected = {
      ".".join(path): values
      for path, values in differences.items() if path not in allowed
  }
  if unexpected:
    raise ValueError(
        "Full/NoVPN configs differ outside the allowlist: {}".format(
            unexpected))
  required = {
      ("experiment_name",),
      ("model", "use_page_id_embedding"),
      ("outputs", "checkpoint_root"),
      ("outputs", "result_root"),
      ("outputs", "log_root"),
  }
  missing = sorted(".".join(path) for path in required - set(differences))
  if missing:
    raise ValueError(
        "Full/NoVPN configs must differ in all declared variant fields: {}"
        .format(missing))
  return differences


def assert_variant_matches_reference(reference_config, variant_config):
  """Verifies that a variant is an allowlisted clone of formal Full CAPD."""
  finals_config.validate_config(reference_config)
  finals_config.validate_config(variant_config)
  differences = config_differences(reference_config, variant_config)
  unexpected = {
      ".".join(path): values
      for path, values in differences.items()
      if path not in ALLOWED_CONFIG_DIFFS
  }
  if unexpected:
    raise ValueError(
        "Ablation config differs from formal Full CAPD outside the "
        "allowlist: {}".format(unexpected))
  required = set(ALLOWED_CONFIG_DIFFS)
  missing = sorted(".".join(path) for path in required - set(differences))
  if missing:
    raise ValueError(
        "Ablation config does not declare every isolated variant field: {}"
        .format(missing))
  return differences


def assert_data_config_compatible(data_config, experiment_config):
  """Verifies safe reuse of sealed full-config JSONL/selector artifacts."""
  finals_config.validate_config(data_config, require_resolved=True)
  finals_config.validate_config(experiment_config, require_resolved=True)
  data_variant = copy.deepcopy(data_config)
  data_variant["experiment_name"] = experiment_config["experiment_name"]
  data_variant.setdefault("model", {})["use_page_id_embedding"] = (
      experiment_config["model"]["use_page_id_embedding"])
  for key in ("checkpoint_root", "result_root", "log_root"):
    data_variant.setdefault("outputs", {})[key] = (
        experiment_config["outputs"][key])
  data_variant["run"]["base_config_fingerprint"] = experiment_config[
      "run"]["base_config_fingerprint"]
  data_variant["run"]["resolved_config_fingerprint"] = experiment_config[
      "run"]["resolved_config_fingerprint"]
  differences = config_differences(data_variant, experiment_config)
  if differences:
    raise ValueError(
        "Experiment config is not a model/output-only derivative of the "
        "sealed data config: {}".format({
            ".".join(path): values for path, values in differences.items()
        }))
  return data_config


def data_config_path_for_artifact(artifact_path):
  return os.path.join(os.path.dirname(os.path.abspath(artifact_path)),
                      "resolved_config.json")


def load_data_config(artifact_path, project_root, experiment_config):
  path = data_config_path_for_artifact(artifact_path)
  data_config = finals_config.load_config(
      path, require_resolved=True, project_root=project_root,
      verify_manifest_files=False)
  return assert_data_config_compatible(data_config, experiment_config)


def materialize_resolved_config(data_config, variant_base_config):
  """Overlays only allowed experiment fields on a sealed B64 data config."""
  finals_config.validate_config(data_config, require_resolved=True)
  finals_config.validate_config(variant_base_config)
  resolved = copy.deepcopy(data_config)
  resolved["experiment_name"] = variant_base_config["experiment_name"]
  resolved.setdefault("model", {})["use_page_id_embedding"] = (
      variant_base_config["model"]["use_page_id_embedding"])
  for key in ("checkpoint_root", "result_root", "log_root"):
    resolved.setdefault("outputs", {})[key] = (
        variant_base_config["outputs"][key])
  resolved["run"]["base_config_fingerprint"] = (
      finals_config.config_fingerprint(variant_base_config))
  resolved["run"].pop("resolved_config_fingerprint", None)
  resolved["run"]["resolved_config_fingerprint"] = (
      finals_config.config_fingerprint(resolved))
  finals_config.validate_config(resolved, require_resolved=True)
  assert_data_config_compatible(data_config, resolved)
  return resolved
