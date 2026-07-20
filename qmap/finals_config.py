# coding=utf-8
"""Authoritative configuration and artifact contracts for CAPD finals_v2."""

from __future__ import print_function

import copy
import hashlib
import json
import os
import subprocess


SCHEMA_VERSION = "capd_finals_v2"
CONTRACT_FIELDS = (
    ("schema_version",),
    ("memory", "dram_capacity_pages"),
    ("memory", "nvm_capacity_pages"),
    ("candidate", "pool_size_B"),
    ("candidate", "retained_K"),
    ("candidate", "selector_history_Hc"),
    ("history", "transformer_H"),
    ("labels", "future_lookahead_L"),
    ("features", "residency_scale_Lres"),
    ("features", "page_state_dim"),
)


def canonical_json_bytes(value):
  return json.dumps(
      value, sort_keys=True, separators=(",", ":"),
      ensure_ascii=False).encode("utf-8")


def fingerprint_value(value):
  return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def fingerprint_file(path, chunk_size=1024 * 1024):
  digest = hashlib.sha256()
  with open(path, "rb") as input_file:
    while True:
      chunk = input_file.read(chunk_size)
      if not chunk:
        break
      digest.update(chunk)
  return digest.hexdigest()


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(path, value):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(value, output_file, indent=2, sort_keys=True,
              ensure_ascii=False)
    output_file.write("\n")


def _get(config, path):
  current = config
  for key in path:
    if key not in current:
      raise ValueError("Missing finals config field: {}".format(
          ".".join(path)))
    current = current[key]
  return current


def validate_config(config, require_resolved=False):
  for path in CONTRACT_FIELDS:
    _get(config, path)
  if config["schema_version"] != SCHEMA_VERSION:
    raise ValueError("Unsupported schema_version: {}".format(
        config["schema_version"]))

  dram_capacity = int(config["memory"]["dram_capacity_pages"])
  nvm_capacity = config["memory"]["nvm_capacity_pages"]
  pool_size = int(config["candidate"]["pool_size_B"])
  retained = int(config["candidate"]["retained_K"])
  selector_history = int(config["candidate"]["selector_history_Hc"])
  transformer_history = int(config["history"]["transformer_H"])
  lookahead = int(config["labels"]["future_lookahead_L"])
  residency_scale = int(config["features"]["residency_scale_Lres"])
  page_state_dim = int(config["features"]["page_state_dim"])
  page_shift = int(config.get("trace", {}).get("page_shift", -1))

  if dram_capacity <= 0:
    raise ValueError("dram_capacity_pages must be positive.")
  if nvm_capacity is not None:
    raise ValueError(
        "CAPD finals_v2 freezes nvm_capacity_pages to null/unbounded.")
  if pool_size <= 0 or retained <= 0:
    raise ValueError("pool_size_B and retained_K must be positive.")
  if pool_size > dram_capacity:
    raise ValueError("pool_size_B cannot exceed dram_capacity_pages.")
  if selector_history <= 0 or transformer_history <= 0:
    raise ValueError("H and Hc must be positive.")
  if lookahead <= 0 or residency_scale <= 0:
    raise ValueError("L and Lres must be positive.")
  if page_state_dim != 4:
    raise ValueError("CAPD finals_v2 requires page_state_dim=4.")
  if page_shift < 0:
    raise ValueError("CAPD finals_v2 requires a non-negative trace.page_shift.")
  if config.get("selector", {}).get("behavior_policy") != "lru":
    raise ValueError("CAPD finals_v2 requires behavior_policy=lru.")
  if float(config.get("selector", {}).get("grid_step", 0.0)) != 0.1:
    raise ValueError("CAPD finals_v2 requires selector grid_step=0.1.")
  if int(config.get("training", {}).get("seed", -1)) != 3136859:
    raise ValueError("CAPD finals_v2 requires training seed 3136859.")
  if int(config.get("evaluation", {}).get("random_seed", -1)) != 0:
    raise ValueError("CAPD finals_v2 requires random baseline seed 0.")
  expected_costs = {
      "dram_read_cost": 1.0, "dram_write_cost": 1.0,
      "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
      "migration_cost": 10.0}
  actual_costs = config.get("cost_model", {})
  if any(float(actual_costs.get(key, -1.0)) != value
         for key, value in expected_costs.items()):
    raise ValueError("CAPD finals_v2 keeps the existing replay cost model.")
  labels = config.get("labels", {})
  if (float(labels.get("lambda_d", -1)) != 1.0 or
      float(labels.get("lambda_q", -1)) != 1.0 or
      float(labels.get("lambda_w", -1)) != 4.0):
    raise ValueError("CAPD finals_v2 requires label weights 1,1,4.")
  training = config.get("training", {})
  if int(training.get("epochs", 0)) <= 0:
    raise ValueError("training.epochs must be positive.")
  if int(training.get("batch_size", 0)) <= 0:
    raise ValueError("training.batch_size must be positive.")
  if float(training.get("learning_rate", 0.0)) <= 0.0:
    raise ValueError("training.learning_rate must be positive.")
  profile = config.get("run_profile", "official")
  if profile not in ("official", "smoke"):
    raise ValueError("run_profile must be official or smoke.")
  if dram_capacity != 64 or retained != 8 or transformer_history != 10:
    raise ValueError("CAPD finals_v2 freezes D=64, K=8 and H=10.")
  if residency_scale != 256:
    raise ValueError("CAPD finals_v2 freezes Lres=256.")
  if profile == "official" and (selector_history != 256 or lookahead != 256):
    raise ValueError("Official finals_v2 freezes Hc=L=256.")

  allowed_pool_sizes = config.get("sweep", {}).get("pool_sizes_B")
  if allowed_pool_sizes is not None and pool_size not in allowed_pool_sizes:
    raise ValueError("pool_size_B {} is outside frozen sweep {}.".format(
        pool_size, allowed_pool_sizes))
  if profile == "official" and sorted(allowed_pool_sizes or []) != [8, 16, 32, 64]:
    raise ValueError("Official finals_v2 sweep must be B={8,16,32,64}.")

  if require_resolved:
    if not config.get("run", {}).get("workload"):
      raise ValueError("Resolved config must include run.workload.")
    for split in ("train_trace", "valid_trace", "test_trace"):
      if not config.get("data", {}).get(split):
        raise ValueError("Resolved config must include data.{}.".format(split))
  return config


def load_config(path, require_resolved=False):
  config = load_json(path)
  validate_config(config, require_resolved=require_resolved)
  return config


def contract_from_config(config):
  validate_config(config)
  return {
      "schema_version": config["schema_version"],
      "D": int(config["memory"]["dram_capacity_pages"]),
      "B": int(config["candidate"]["pool_size_B"]),
      "K": int(config["candidate"]["retained_K"]),
      "H": int(config["history"]["transformer_H"]),
      "Hc": int(config["candidate"]["selector_history_Hc"]),
      "L": int(config["labels"]["future_lookahead_L"]),
      "Lres": int(config["features"]["residency_scale_Lres"]),
      "page_state_dim": int(config["features"]["page_state_dim"]),
  }


def assert_contract_matches(expected, actual, context):
  missing = [key for key in expected if key not in actual]
  mismatches = {
      key: (expected[key], actual.get(key))
      for key in expected
      if key in actual and expected[key] != actual[key]
  }
  if missing or mismatches:
    raise ValueError(
        "{} contract mismatch; missing={} mismatches={}".format(
            context, missing, mismatches))


def config_fingerprint(config):
  validate_config(config)
  payload = copy.deepcopy(config)
  if "run" in payload:
    payload["run"].pop("resolved_config_fingerprint", None)
  return fingerprint_value(payload)


def selector_contract(selector_params):
  required = (
      "c_Delta", "c_A", "c_W", "w_Delta", "w_A", "w_W", "w_C",
      "w_R")
  missing = [key for key in required if key not in selector_params]
  if missing:
    raise ValueError("selector_params missing fields: {}".format(missing))
  return {key: selector_params[key] for key in required}


def selector_fingerprint(selector_params):
  return fingerprint_value(selector_contract(selector_params))


def metadata_path(jsonl_path):
  return jsonl_path + ".metadata.json"


def load_jsonl_metadata(jsonl_path):
  path = metadata_path(jsonl_path)
  if not os.path.exists(path):
    raise FileNotFoundError("Finals JSONL metadata not found: {}".format(path))
  metadata = load_json(path)
  actual = fingerprint_file(jsonl_path)
  if metadata.get("data_fingerprint") != actual:
    raise ValueError("JSONL fingerprint mismatch for {}.".format(jsonl_path))
  return metadata


def current_git_commit(project_root):
  try:
    output = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root,
        stderr=subprocess.STDOUT, universal_newlines=True)
    return output.strip()
  except (OSError, subprocess.CalledProcessError):
    return "unknown"


def resolve_config(base_config, workload, pool_size_B, project_root=None,
                   overrides=None):
  config = copy.deepcopy(base_config)
  if workload not in config.get("workloads", {}):
    raise ValueError("Unknown frozen workload: {}".format(workload))
  pool_size_B = int(pool_size_B)
  config["candidate"]["pool_size_B"] = pool_size_B
  config["run"] = {"workload": workload}
  config["data"] = copy.deepcopy(config["workloads"][workload])
  if overrides:
    for dotted_key, value in overrides.items():
      keys = dotted_key.split(".")
      target = config
      for key in keys[:-1]:
        target = target.setdefault(key, {})
      target[keys[-1]] = value
  if project_root:
    config["run"]["project_root"] = os.path.abspath(project_root)
    config["run"]["git_commit"] = current_git_commit(project_root)
  config["run"]["base_config_fingerprint"] = config_fingerprint(base_config)
  validate_config(config, require_resolved=True)
  config["run"]["resolved_config_fingerprint"] = config_fingerprint(config)
  return config
