# coding=utf-8
"""Authoritative configuration and artifact contracts for CAPD finals.

``capd_finals_v3_0`` implements frozen contract ``CAPD-MIC-1.0``. The legacy
v2.1 validator remains available only so the isolated v2 runner can reject or
consume its own historical artifacts; v2.1 and v3 artifacts never cross-load.
"""

from __future__ import print_function

import copy
import hashlib
import json
import math
import os
import subprocess


SCHEMA_VERSION = "capd_finals_v3_0"
LEGACY_SCHEMA_VERSION = "capd_finals_v2_1"
CONTRACT_ID = "CAPD-MIC-1.0"
OFFICIAL_PROFILE = "official"
SMOKE_PROFILE = "smoke"
DIAGNOSTIC_PROFILE = "diagnostic_bridge"
OPTIMIZATION_PROFILE = "post_stage6_optimization"
STAGE5_VARIANT_FAMILIES = ("ablation", "sensitivity")
STAGE6_VARIANT_FAMILIES = ("capacity_robustness",)
OPTIMIZATION_VARIANT_FAMILIES = ("frozen_method_config_search",)
LEGACY_CONTRACT_FIELDS = (
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
    ("validation", "strategy"),
    ("validation", "holdout_fraction"),
    ("validation", "rounding"),
    ("validation", "guard_accesses"),
    ("validation", "external_valid_trace_role"),
)

V3_CONTRACT_FIELDS = (
    ("schema_version",),
    ("contract", "id"),
    ("run_profile",),
    ("memory", "dram_capacity_pages"),
    ("memory", "nvm_capacity_pages"),
    ("replay", "dram_initial_state"),
    ("replay", "initial_residency"),
    ("replay", "trace_page_backing"),
    ("replay", "first_touch_accounting"),
    ("replay", "dirty_demotion_nvm_write"),
    ("candidate", "pool_size_B"),
    ("candidate", "retained_K"),
    ("candidate", "selector_history_Hc"),
    ("history", "transformer_H"),
    ("labels", "future_lookahead_L"),
    ("labels", "tail_policy"),
    ("features", "residency_scale_Lres"),
    ("features", "page_state_dim"),
    ("features", "lru_direction"),
    ("validation", "strategy"),
    ("validation", "development_fallback"),
    ("validation", "require_data_manifest"),
    ("validation", "data_quality_profile"),
    ("metrics", "selector_recall_tie"),
    ("embedding", "page", "shared"),
    ("embedding", "page", "vocab_fit"),
    ("embedding", "page", "oov"),
    ("embedding", "pc", "vocab_fit"),
    ("embedding", "pc", "oov"),
    ("model", "position_encoding"),
    ("loss", "approx_ndcg_alpha"),
    ("training", "scope"),
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
  with open(path, "w", encoding="utf-8", newline="\n") as output_file:
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


def _validate_legacy_config(config, require_resolved=False):
  for path in LEGACY_CONTRACT_FIELDS:
    _get(config, path)
  if config["schema_version"] != LEGACY_SCHEMA_VERSION:
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
  validation = config["validation"]
  validation_strategy = validation["strategy"]
  holdout_fraction = float(validation["holdout_fraction"])
  validation_rounding = validation["rounding"]
  guard_accesses = int(validation["guard_accesses"])
  external_valid_role = validation["external_valid_trace_role"]

  if dram_capacity <= 0:
    raise ValueError("dram_capacity_pages must be positive.")
  if nvm_capacity is not None:
    raise ValueError(
        "CAPD finals_v2.1 freezes nvm_capacity_pages to null/unbounded.")
  if pool_size <= 0 or retained <= 0:
    raise ValueError("pool_size_B and retained_K must be positive.")
  if pool_size > dram_capacity:
    raise ValueError("pool_size_B cannot exceed dram_capacity_pages.")
  if selector_history <= 0 or transformer_history <= 0:
    raise ValueError("H and Hc must be positive.")
  if lookahead <= 0 or residency_scale <= 0:
    raise ValueError("L and Lres must be positive.")
  if page_state_dim != 4:
    raise ValueError("CAPD finals_v2.1 requires page_state_dim=4.")
  if page_shift < 0:
    raise ValueError(
        "CAPD finals_v2.1 requires a non-negative trace.page_shift.")
  if validation_strategy != "train_trace_decision_holdout":
    raise ValueError(
        "CAPD finals_v2.1 requires train_trace_decision_holdout validation.")
  if holdout_fraction != 0.2:
    raise ValueError("CAPD finals_v2.1 freezes validation holdout to 0.2.")
  if validation_rounding != "ceil":
    raise ValueError("CAPD finals_v2.1 requires ceil holdout rounding.")
  if guard_accesses != lookahead:
    raise ValueError(
        "validation.guard_accesses must equal future_lookahead_L.")
  if external_valid_role != "diagnostic_only":
    raise ValueError(
        "CAPD finals_v2.1 keeps the external valid trace diagnostic-only.")
  if config.get("selector", {}).get("behavior_policy") != "lru":
    raise ValueError("CAPD finals_v2.1 requires behavior_policy=lru.")
  if float(config.get("selector", {}).get("grid_step", 0.0)) != 0.1:
    raise ValueError("CAPD finals_v2.1 requires selector grid_step=0.1.")
  if int(config.get("training", {}).get("seed", -1)) != 3136859:
    raise ValueError("CAPD finals_v2.1 requires training seed 3136859.")
  if int(config.get("evaluation", {}).get("random_seed", -1)) != 0:
    raise ValueError("CAPD finals_v2.1 requires random baseline seed 0.")
  expected_costs = {
      "dram_read_cost": 1.0, "dram_write_cost": 1.0,
      "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
      "migration_cost": 10.0}
  actual_costs = config.get("cost_model", {})
  if any(float(actual_costs.get(key, -1.0)) != value
         for key, value in expected_costs.items()):
    raise ValueError("CAPD finals_v2.1 keeps the existing replay cost model.")
  labels = config.get("labels", {})
  if (float(labels.get("lambda_d", -1)) != 1.0 or
      float(labels.get("lambda_q", -1)) != 1.0 or
      float(labels.get("lambda_w", -1)) != 4.0):
    raise ValueError("CAPD finals_v2.1 requires label weights 1,1,4.")
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
    raise ValueError("CAPD finals_v2.1 freezes D=64, K=8 and H=10.")
  if residency_scale != 256:
    raise ValueError("CAPD finals_v2.1 freezes Lres=256.")
  if profile == "official" and (selector_history != 256 or lookahead != 256):
    raise ValueError("Official finals_v2.1 freezes Hc=L=256.")

  allowed_pool_sizes = config.get("sweep", {}).get("pool_sizes_B")
  if allowed_pool_sizes is not None and pool_size not in allowed_pool_sizes:
    raise ValueError("pool_size_B {} is outside frozen sweep {}.".format(
        pool_size, allowed_pool_sizes))
  if profile == "official" and sorted(allowed_pool_sizes or []) != [8, 16, 32, 64]:
    raise ValueError("Official finals_v2.1 sweep must be B={8,16,32,64}.")

  if require_resolved:
    if not config.get("run", {}).get("workload"):
      raise ValueError("Resolved config must include run.workload.")
    for split in ("train_trace", "valid_trace", "test_trace"):
      if not config.get("data", {}).get(split):
        raise ValueError("Resolved config must include data.{}.".format(split))
  return config


def _normalized_path(path):
  return os.path.normcase(os.path.abspath(path))


def assert_independent_trace_sources(config, fingerprints=None,
                                     source_manifest=None,
                                     project_root=None):
  """Rejects ambiguous sources; v3 manifests prove interval independence."""
  data = config.get("data", config.get("workloads", {}).get(
      config.get("run", {}).get("workload", ""), {}))
  paths = [data.get(name) for name in (
      "train_trace", "valid_trace", "test_trace")]
  if any(not path for path in paths):
    raise ValueError("Official v3 requires train/valid/test trace paths.")
  normalized = [_normalized_path(path) for path in paths]
  if len(set(normalized)) != 3:
    raise ValueError("Official train/valid/test trace paths must be distinct.")
  if source_manifest is not None:
    from qmap import finals_data
    root = project_root or config.get("run", {}).get(
        "project_root") or os.getcwd()
    finals_data.validate_source_manifest(
        source_manifest, root, verify_files=False,
        require_quality_pass=False,
        expected_workload=config.get("run", {}).get("workload"))
    for split_name, config_key in (
        ("train", "train_trace"), ("valid", "valid_trace"),
        ("test", "test_trace")):
      declared = finals_data.resolve_path(
          source_manifest["splits"][split_name]["path"], root)
      configured = finals_data.resolve_path(data[config_key], root)
      if os.path.normcase(declared) != os.path.normcase(configured):
        raise ValueError(
            "Config/manifest path mismatch for {}.".format(split_name))
    return
  if fingerprints is not None:
    values = [fingerprints.get(name) for name in (
        "train_trace", "valid_trace", "test_trace")]
    if any(not value for value in values) or len(set(values)) != 3:
      raise ValueError(
          "Official train/valid/test trace fingerprints must be distinct.")


def _requires_data_manifest(config):
  return (
      config.get("schema_version") == SCHEMA_VERSION and
      config.get("run_profile") in (
          OFFICIAL_PROFILE, OPTIMIZATION_PROFILE) and
      config.get("validation", {}).get("require_data_manifest") is True)


def uses_independent_validation(config):
  """Whether train and validation artifacts come from independent traces."""
  return (
      config.get("schema_version") == SCHEMA_VERSION and
      config.get("run_profile") in (
          OFFICIAL_PROFILE, DIAGNOSTIC_PROFILE, OPTIMIZATION_PROFILE))


def _bind_resolved_data_manifest(config, project_root=None,
                                 verify_manifest_files=True):
  """Verifies and binds a PASSED source manifest into a resolved config."""
  if not _requires_data_manifest(config):
    return config
  from qmap import finals_data
  root = project_root or config.get("run", {}).get(
      "project_root") or os.getcwd()
  manifest_path = config.get("data", {}).get("source_manifest")
  if not manifest_path:
    raise ValueError("Official v3 requires data.source_manifest.")
  manifest = finals_data.load_source_manifest(
      manifest_path, root, verify_files=verify_manifest_files,
      require_quality_pass=True,
      expected_workload=config.get("run", {}).get("workload"))
  recorded_commit = config.get("run", {}).get("git_commit")
  if (not recorded_commit or
      manifest.get("git_commit") != recorded_commit):
    raise ValueError(
        "Data manifest git_commit does not match the resolved artifact.")
  assert_independent_trace_sources(
      config, source_manifest=manifest, project_root=root)
  profile_path = config.get("validation", {}).get("data_quality_profile")
  profile = finals_data.load_json(finals_data.resolve_path(profile_path, root))
  profile_identity = finals_data.validate_data_profile(profile, config)
  quality = manifest.get("quality_gate", {})
  if (quality.get("profile_id") != profile_identity["profile_id"] or
      quality.get("profile_fingerprint") !=
      profile_identity["profile_fingerprint"]):
    raise ValueError("Resolved config/data quality profile binding mismatch.")
  binding = finals_data.manifest_binding(
      manifest_path, manifest, root,
      expected_source_fingerprint=config.get("run", {}).get(
          "source_manifest_fingerprint"))
  config.setdefault("run", {}).update(binding)
  config["data"]["split_fingerprints"] = copy.deepcopy(
      binding["split_fingerprints"])
  return config


def _validate_v3_config(config, require_resolved=False):
  for path in V3_CONTRACT_FIELDS:
    _get(config, path)
  if config["schema_version"] != SCHEMA_VERSION:
    raise ValueError("Unsupported v3 schema_version: {}".format(
        config["schema_version"]))
  if config["contract"]["id"] != CONTRACT_ID:
    raise ValueError("CAPD v3 requires contract.id={}.".format(CONTRACT_ID))
  use_page_id_embedding = config.get(
      "model", {}).get("use_page_id_embedding", True)
  if not isinstance(use_page_id_embedding, bool):
    raise ValueError("model.use_page_id_embedding must be boolean.")

  profile = config["run_profile"]
  if profile not in (
      OFFICIAL_PROFILE, SMOKE_PROFILE, DIAGNOSTIC_PROFILE,
      OPTIMIZATION_PROFILE):
    raise ValueError(
        "run_profile must be official, smoke, diagnostic_bridge, or "
        "post_stage6_optimization.")
  dram_capacity = int(config["memory"]["dram_capacity_pages"])
  pool_size = int(config["candidate"]["pool_size_B"])
  retained = int(config["candidate"]["retained_K"])
  selector_history = int(config["candidate"]["selector_history_Hc"])
  transformer_history = int(config["history"]["transformer_H"])
  lookahead = int(config["labels"]["future_lookahead_L"])
  residency_scale = int(config["features"]["residency_scale_Lres"])
  page_state_dim = int(config["features"]["page_state_dim"])
  stage5_variant = config.get("stage5_variant")
  stage6_variant = config.get("stage6_variant")
  optimization_variant = config.get("optimization_variant")
  if sum(value is not None for value in (
      stage5_variant, stage6_variant, optimization_variant)) > 1:
    raise ValueError("A config cannot belong to multiple variant tracks.")
  if profile == OPTIMIZATION_PROFILE and optimization_variant is None:
    raise ValueError(
        "post_stage6_optimization requires optimization_variant.")
  if profile != OPTIMIZATION_PROFILE and optimization_variant is not None:
    raise ValueError(
        "optimization_variant requires post_stage6_optimization profile.")
  if dram_capacity <= 0 or pool_size <= 0 or retained <= 0:
    raise ValueError("D, B and K must be positive.")
  if pool_size > dram_capacity or retained > pool_size:
    raise ValueError("CAPD v3 requires K <= B <= D.")
  if selector_history <= 0 or transformer_history <= 0:
    raise ValueError("H and Hc must be positive.")
  if lookahead <= 0 or residency_scale <= 0:
    raise ValueError("L and Lres must be positive.")
  if page_state_dim != 4:
    raise ValueError("CAPD v3 requires page_state_dim=4.")
  if int(config.get("trace", {}).get("page_shift", -1)) < 0:
    raise ValueError("CAPD v3 requires non-negative trace.page_shift.")
  if config["memory"]["nvm_capacity_pages"] is not None:
    raise ValueError("CAPD v3 requires unbounded NVM capacity (null).")

  replay = config["replay"]
  expected_replay = {
      "dram_initial_state": "empty",
      "initial_residency": "all_trace_pages_in_nvm",
      "trace_page_backing": "all_trace_pages",
      "first_touch_accounting": "nvm_access",
      "dirty_demotion_nvm_write": "none",
  }
  for key, expected in expected_replay.items():
    if replay.get(key) != expected:
      raise ValueError("CAPD v3 replay.{} must be {}.".format(key, expected))

  validation = config["validation"]
  if validation["require_data_manifest"] not in (True, False):
    raise ValueError("validation.require_data_manifest must be boolean.")
  if not validation["data_quality_profile"]:
    raise ValueError("CAPD v3 requires a data quality profile path.")
  if validation["development_fallback"] != "train_trace_decision_holdout":
    raise ValueError("CAPD v3 must retain the named development fallback.")
  if uses_independent_validation(config):
    if validation["strategy"] != "independent_valid_trace":
      raise ValueError(
          "Independent-validation v3 profiles require "
          "independent_valid_trace.")
    expected_artifact_class = {
        OFFICIAL_PROFILE: "official",
        DIAGNOSTIC_PROFILE: "diagnostic_only",
        OPTIMIZATION_PROFILE: "optimization_only",
    }[profile]
    if validation.get("artifact_class") != expected_artifact_class:
      raise ValueError(
          "{} v3 artifacts must use artifact_class={}.".format(
              profile, expected_artifact_class))
    if (profile == DIAGNOSTIC_PROFILE and
        validation["require_data_manifest"] is not False):
      raise ValueError(
          "diagnostic_bridge must not masquerade as manifest-bound official "
          "evidence.")
    if (profile == OPTIMIZATION_PROFILE and
        validation["require_data_manifest"] is not True):
      raise ValueError(
          "post_stage6_optimization must stay bound to the sealed official "
          "source manifest.")
  else:
    if validation["strategy"] != "train_trace_decision_holdout":
      raise ValueError("Smoke v3 requires train_trace_decision_holdout.")
    if validation.get("artifact_class") != "smoke_only":
      raise ValueError("Smoke v3 artifacts must use artifact_class=smoke_only.")
    if float(validation.get("holdout_fraction", 0.0)) != 0.2:
      raise ValueError("Smoke holdout_fraction must be 0.2.")
    if validation.get("rounding") != "ceil":
      raise ValueError("Smoke holdout rounding must be ceil.")
    if int(validation.get("guard_accesses", -1)) != lookahead:
      raise ValueError("Smoke guard_accesses must equal L.")

  frozen_values = (
      (config["labels"]["tail_policy"], "drop_incomplete_window",
       "labels.tail_policy"),
      (config["features"]["lru_direction"], "oldest_is_one",
       "features.lru_direction"),
      (config["metrics"]["selector_recall_tie"], "any_hit",
       "metrics.selector_recall_tie"),
      (config["embedding"]["page"]["vocab_fit"], "train_only",
       "embedding.page.vocab_fit"),
      (config["embedding"]["page"]["oov"], "unk",
       "embedding.page.oov"),
      (config["embedding"]["pc"]["vocab_fit"], "train_only",
       "embedding.pc.vocab_fit"),
      (config["embedding"]["pc"]["oov"], "unk",
       "embedding.pc.oov"),
      (config["training"]["scope"], "per_workload",
       "training.scope"),
  )
  for actual, expected, name in frozen_values:
    if actual != expected:
      raise ValueError("CAPD v3 requires {}={}.".format(name, expected))
  if config["embedding"]["page"]["shared"] is not True:
    raise ValueError("CAPD v3 requires a shared page embedding.")
  if float(config["loss"]["approx_ndcg_alpha"]) != 10.0:
    raise ValueError("CAPD v3 freezes approx_ndcg_alpha=10.")
  if config.get("selector", {}).get("behavior_policy") != "lru":
    raise ValueError("CAPD v3 requires selector behavior_policy=lru.")
  if float(config.get("selector", {}).get("grid_step", 0.0)) != 0.1:
    raise ValueError("CAPD v3 requires selector grid_step=0.1.")
  labels = config["labels"]
  if (float(labels.get("lambda_d", -1)) != 1.0 or
      float(labels.get("lambda_q", -1)) != 1.0):
    raise ValueError("CAPD v3 requires lambda_d=lambda_q=1.")
  expected_costs = {
      "dram_read_cost": 1.0, "dram_write_cost": 1.0,
      "nvm_read_cost": 2.0, "nvm_write_cost": 8.0,
      "migration_cost": 10.0}
  if any(float(config.get("cost_model", {}).get(key, -1.0)) != value
         for key, value in expected_costs.items()):
    raise ValueError("CAPD v3 cost model does not match CAPD-MIC-1.0.")
  if profile == OFFICIAL_PROFILE:
    if stage5_variant is None and stage6_variant is None:
      if (dram_capacity != 64 or retained != 8 or
          transformer_history != 10 or selector_history != 256 or
          lookahead != 256 or residency_scale != 256):
        raise ValueError("Official v3 freezes D/K/H/Hc/L/Lres.")
      if config["model"]["position_encoding"] != "sinusoidal":
        raise ValueError(
            "Official Full v3 requires model.position_encoding=sinusoidal.")
      if float(labels.get("lambda_w", -1)) != 4.0:
        raise ValueError("Official Full v3 requires label weights 1,1,4.")
    elif stage5_variant is not None:
      _validate_stage5_variant_config(
          config, dram_capacity, pool_size, retained, transformer_history,
          selector_history, lookahead, residency_scale)
    else:
      _validate_stage6_variant_config(
          config, dram_capacity, pool_size, retained, transformer_history,
          selector_history, lookahead, residency_scale)
    if sorted(config.get("sweep", {}).get("pool_sizes_B", [])) != [8, 16, 32, 64]:
      raise ValueError("Official v3 sweep must be B={8,16,32,64}.")
  elif profile == OPTIMIZATION_PROFILE:
    _validate_optimization_variant_config(
        config, dram_capacity, pool_size, retained, transformer_history,
        selector_history, lookahead, residency_scale)
  else:
    if config["model"]["position_encoding"] != "sinusoidal":
      raise ValueError(
          "Non-official v3 requires sinusoidal position encoding.")
    if float(labels.get("lambda_w", -1)) != 4.0:
      raise ValueError("Non-official v3 requires label weights 1,1,4.")
  if pool_size not in config.get("sweep", {}).get("pool_sizes_B", [pool_size]):
    raise ValueError("pool_size_B is outside the configured sweep.")

  training = config.get("training", {})
  if (int(training.get("epochs", 0)) <= 0 or
      int(training.get("batch_size", 0)) <= 0 or
      float(training.get("learning_rate", 0.0)) <= 0.0):
    raise ValueError("Training epochs/batch_size/learning_rate must be positive.")
  if require_resolved:
    if not config.get("run", {}).get("workload"):
      raise ValueError("Resolved config must include run.workload.")
    assert_independent_trace_sources(config)
    if _requires_data_manifest(config):
      required_binding = (
          "source_manifest_fingerprint", "split_fingerprints",
          "data_quality_profile_id", "data_quality_profile_fingerprint",
          "data_quality_report_fingerprint")
      missing_binding = [
          key for key in required_binding if key not in config.get("run", {})]
      if missing_binding:
        raise ValueError(
            "Resolved official v3 config lacks data binding: {}".format(
                missing_binding))
  return config


def _validate_stage5_variant_config(
    config, dram_capacity, pool_size, retained, transformer_history,
    selector_history, lookahead, residency_scale):
  """Allows only the preregistered stage-5 deviations from frozen Full."""
  variant = config.get("stage5_variant")
  required = (
      "variant_id", "family", "only_difference", "source_stage",
      "test_used_for_selection", "retrain_required")
  missing = [key for key in required if key not in variant]
  if missing:
    raise ValueError("stage5_variant missing fields: {}".format(missing))
  if variant["family"] not in STAGE5_VARIANT_FAMILIES:
    raise ValueError("Unsupported stage5_variant family.")
  if variant["source_stage"] != "stage5":
    raise ValueError("stage5_variant source_stage must be stage5.")
  if variant["test_used_for_selection"] is not False:
    raise ValueError("Stage-5 variants must never use test for selection.")
  if not variant["only_difference"]:
    raise ValueError("stage5_variant.only_difference must be explicit.")
  if dram_capacity != 64 or residency_scale != 256:
    raise ValueError("Stage-5 variants freeze D=64 and Lres=256.")

  variant_id = variant["variant_id"]
  expected = {
      "B": 64, "K": 8, "H": 10, "Hc": 256, "L": 256,
      "position_encoding": "sinusoidal", "lambda_w": 4.0}
  if variant_id == "no_filter_B8_K8":
    expected["B"] = 8
  elif variant_id.startswith("selector_drop_"):
    feature = variant_id[len("selector_drop_"):]
    if feature not in ("Delta", "A", "W", "C", "R"):
      raise ValueError("Unknown selector drop feature: {}".format(feature))
  elif variant_id == "no_position_encoding":
    expected["position_encoding"] = "none"
  elif variant_id in ("no_candidate_state", "history_mean_pool"):
    pass
  elif variant_id == "no_future_write":
    expected["lambda_w"] = 0.0
  elif variant_id.startswith("sensitivity_B"):
    expected["B"] = int(variant_id[len("sensitivity_B"):])
    if expected["B"] not in (8, 16, 32):
      raise ValueError("Unsupported stage-5 B sensitivity point.")
  elif variant_id.startswith("sensitivity_K"):
    expected["K"] = int(variant_id[len("sensitivity_K"):])
    if expected["K"] not in (4, 16):
      raise ValueError("Unsupported stage-5 K sensitivity point.")
  elif variant_id.startswith("sensitivity_Hc"):
    expected["Hc"] = int(variant_id[len("sensitivity_Hc"):])
    if expected["Hc"] not in (64, 128, 512):
      raise ValueError("Unsupported stage-5 Hc sensitivity point.")
  elif variant_id.startswith("sensitivity_H"):
    expected["H"] = int(variant_id[len("sensitivity_H"):])
    if expected["H"] not in (5, 20):
      raise ValueError("Unsupported stage-5 H sensitivity point.")
  elif variant_id.startswith("sensitivity_L"):
    expected["L"] = int(variant_id[len("sensitivity_L"):])
    if expected["L"] not in (64, 128, 512):
      raise ValueError("Unsupported stage-5 L sensitivity point.")
  else:
    raise ValueError("Unknown stage5_variant.variant_id: {}".format(
        variant_id))

  actual = {
      "B": pool_size, "K": retained, "H": transformer_history,
      "Hc": selector_history, "L": lookahead,
      "position_encoding": config["model"]["position_encoding"],
      "lambda_w": float(config["labels"].get("lambda_w", -1))}
  if actual != expected:
    raise ValueError(
        "Stage-5 variant {} has undeclared differences: expected={} "
      "actual={}.".format(variant_id, expected, actual))


def _validate_stage6_variant_config(
    config, dram_capacity, pool_size, retained, transformer_history,
    selector_history, lookahead, residency_scale):
  """Allows only preregistered capacity changes for stage-6 robustness."""
  variant = config.get("stage6_variant")
  required = (
      "variant_id", "family", "only_difference", "source_stage",
      "test_used_for_selection", "retrain_required")
  missing = [key for key in required if key not in variant]
  if missing:
    raise ValueError("stage6_variant missing fields: {}".format(missing))
  if variant["family"] not in STAGE6_VARIANT_FAMILIES:
    raise ValueError("Unsupported stage6_variant family.")
  if variant["source_stage"] != "stage6":
    raise ValueError("stage6_variant source_stage must be stage6.")
  if variant["test_used_for_selection"] is not False:
    raise ValueError("Stage-6 variants must never use test for selection.")
  if variant["retrain_required"] is not True:
    raise ValueError("Stage-6 capacity variants require retraining.")
  if not variant["only_difference"]:
    raise ValueError("stage6_variant.only_difference must be explicit.")

  variant_id = variant["variant_id"]
  if not variant_id.startswith("capacity_D"):
    raise ValueError("Unknown stage6_variant.variant_id: {}".format(
        variant_id))
  expected_capacity = int(variant_id[len("capacity_D"):])
  if expected_capacity not in (128, 256):
    raise ValueError("Unsupported stage-6 capacity point.")
  expected = {
      "D": expected_capacity, "B": 64, "K": 8, "H": 10, "Hc": 256,
      "L": 256, "Lres": 256, "position_encoding": "sinusoidal",
      "lambda_w": 4.0}
  actual = {
      "D": dram_capacity, "B": pool_size, "K": retained,
      "H": transformer_history, "Hc": selector_history, "L": lookahead,
      "Lres": residency_scale,
      "position_encoding": config["model"]["position_encoding"],
      "lambda_w": float(config["labels"].get("lambda_w", -1))}
  if actual != expected:
    raise ValueError(
        "Stage-6 variant {} has undeclared differences: expected={} "
        "actual={}.".format(variant_id, expected, actual))


def _validate_optimization_variant_config(
    config, dram_capacity, pool_size, retained, transformer_history,
    selector_history, lookahead, residency_scale):
  """Allows only the preregistered frozen-method O2 configuration matrix."""
  variant = config.get("optimization_variant")
  required = (
      "variant_id", "family", "source_stage", "only_difference",
      "test_used_for_selection", "method_contract_changed",
      "retrain_required")
  missing = [key for key in required if key not in variant]
  if missing:
    raise ValueError(
        "optimization_variant missing fields: {}".format(missing))
  if variant["family"] not in OPTIMIZATION_VARIANT_FAMILIES:
    raise ValueError("Unsupported optimization_variant family.")
  if variant["source_stage"] != "post_stage6_optimization":
    raise ValueError(
        "optimization_variant source_stage must be "
        "post_stage6_optimization.")
  if variant["test_used_for_selection"] is not False:
    raise ValueError("Optimization variants must never use test selection.")
  if variant["method_contract_changed"] is not False:
    raise ValueError("Optimization variants must preserve CAPD-MIC-1.0.")
  if variant["retrain_required"] is not True:
    raise ValueError("Optimization variants require fresh retraining.")
  if not variant["only_difference"]:
    raise ValueError("optimization_variant.only_difference must be explicit.")

  allowed = {
      "opt_full_control": (64, 8, 256, 10),
      "opt_B32": (32, 8, 256, 10),
      "opt_K16": (64, 16, 256, 10),
      "opt_L512": (64, 8, 512, 10),
      "opt_H20": (64, 8, 256, 20),
      "opt_B32_K16": (32, 16, 256, 10),
      "opt_B32_K16_L512": (32, 16, 512, 10),
      "opt_B32_K16_L512_H20": (32, 16, 512, 20),
  }
  variant_id = variant["variant_id"]
  if variant_id not in allowed:
    raise ValueError(
        "Unknown optimization_variant.variant_id: {}".format(variant_id))
  expected_B, expected_K, expected_L, expected_H = allowed[variant_id]
  expected = {
      "D": 64, "B": expected_B, "K": expected_K, "H": expected_H,
      "Hc": 256, "L": expected_L, "Lres": 256,
      "position_encoding": "sinusoidal", "lambda_w": 4.0}
  actual = {
      "D": dram_capacity, "B": pool_size, "K": retained,
      "H": transformer_history, "Hc": selector_history, "L": lookahead,
      "Lres": residency_scale,
      "position_encoding": config["model"]["position_encoding"],
      "lambda_w": float(config["labels"].get("lambda_w", -1))}
  if actual != expected:
    raise ValueError(
        "Optimization variant {} has undeclared differences: expected={} "
        "actual={}.".format(variant_id, expected, actual))


def validate_config(config, require_resolved=False):
  schema = config.get("schema_version")
  if schema == LEGACY_SCHEMA_VERSION:
    return _validate_legacy_config(config, require_resolved=require_resolved)
  if schema == SCHEMA_VERSION:
    return _validate_v3_config(config, require_resolved=require_resolved)
  raise ValueError("Unsupported schema_version: {}".format(schema))


def load_config(path, require_resolved=False, project_root=None,
                verify_manifest_files=True):
  config = load_json(path)
  if require_resolved:
    _bind_resolved_data_manifest(
        config, project_root=project_root,
        verify_manifest_files=verify_manifest_files)
  validate_config(config, require_resolved=require_resolved)
  if require_resolved:
    recorded = config.get("run", {}).get("resolved_config_fingerprint")
    if recorded is None:
      raise ValueError(
          "Resolved config must include run.resolved_config_fingerprint.")
    if recorded != config_fingerprint(config):
      raise ValueError(
          "Resolved config fingerprint is stale; regenerate it before use.")
  return config


def contract_from_config(config):
  validate_config(config)
  contract = {
      "schema_version": config["schema_version"],
      "D": int(config["memory"]["dram_capacity_pages"]),
      "B": int(config["candidate"]["pool_size_B"]),
      "K": int(config["candidate"]["retained_K"]),
      "H": int(config["history"]["transformer_H"]),
      "Hc": int(config["candidate"]["selector_history_Hc"]),
      "L": int(config["labels"]["future_lookahead_L"]),
      "Lres": int(config["features"]["residency_scale_Lres"]),
      "page_state_dim": int(config["features"]["page_state_dim"]),
      "validation_strategy": config["validation"]["strategy"],
      "validation_holdout_fraction": float(
          config["validation"]["holdout_fraction"]),
      "validation_guard_accesses": int(
          config["validation"].get("guard_accesses", 0)),
  }
  if config["schema_version"] == SCHEMA_VERSION:
    contract.update({
        "contract_id": CONTRACT_ID,
        "run_profile": config["run_profile"],
        "artifact_class": config["validation"]["artifact_class"],
        "tail_policy": config["labels"]["tail_policy"],
        "lru_direction": config["features"]["lru_direction"],
        "selector_recall_tie": config["metrics"]["selector_recall_tie"],
        "shared_page_embedding": config["embedding"]["page"]["shared"],
        "page_vocab_fit": config["embedding"]["page"]["vocab_fit"],
        "page_oov": config["embedding"]["page"]["oov"],
        "pc_vocab_fit": config["embedding"]["pc"]["vocab_fit"],
        "pc_oov": config["embedding"]["pc"]["oov"],
        "position_encoding": config["model"]["position_encoding"],
        "approx_ndcg_alpha": float(config["loss"]["approx_ndcg_alpha"]),
        "training_scope": config["training"]["scope"],
        "nvm_capacity_pages": config["memory"]["nvm_capacity_pages"],
        "dram_initial_state": config["replay"]["dram_initial_state"],
        "initial_residency": config["replay"]["initial_residency"],
        "trace_page_backing": config["replay"]["trace_page_backing"],
        "first_touch_accounting": config["replay"][
            "first_touch_accounting"],
        "dirty_demotion_nvm_write": config["replay"][
            "dirty_demotion_nvm_write"],
    })
    if config.get("stage5_variant") is not None:
      contract.update({
          "stage5_variant_id": config["stage5_variant"]["variant_id"],
          "stage5_variant_family": config["stage5_variant"]["family"],
          "lambda_w": float(config["labels"]["lambda_w"]),
      })
    if config.get("stage6_variant") is not None:
      contract.update({
          "stage6_variant_id": config["stage6_variant"]["variant_id"],
          "stage6_variant_family": config["stage6_variant"]["family"],
      })
    if config.get("optimization_variant") is not None:
      contract.update({
          "optimization_variant_id":
              config["optimization_variant"]["variant_id"],
          "optimization_variant_family":
              config["optimization_variant"]["family"],
      })
  return contract


def use_page_id_embedding(config):
  """Returns the backward-compatible absolute page-ID embedding switch."""
  validate_config(config)
  return bool(config.get("model", {}).get("use_page_id_embedding", True))


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
  base_required = (
      "c_Delta", "c_A", "c_W", "w_Delta", "w_A", "w_W", "w_C",
      "w_R")
  schema = selector_params.get("schema_version", LEGACY_SCHEMA_VERSION)
  if schema == SCHEMA_VERSION:
    required = base_required + (
        "contract_id", "workload_id", "run_profile", "artifact_class",
        "git_commit", "config_fingerprint", "train_trace_fingerprint",
        "valid_trace_fingerprint", "validation_samples_fingerprint",
        "PoolRecall@B", "SelectorRecall@K", "EndToEndRecall@K",
        "TieCoverage@K", "NRegret", "effective_decision_points",
        "nondiscriminative_ratio", "mean_oracle_size",
        "unique_oracle_ratio", "behavior_policy", "tail_policy",
        "selection_rule")
  elif schema == LEGACY_SCHEMA_VERSION:
    required = base_required
  else:
    raise ValueError("Unsupported selector schema: {}".format(schema))
  missing = [key for key in required if key not in selector_params]
  if missing:
    raise ValueError("selector_params missing fields: {}".format(missing))
  optional_binding = (
      "source_manifest_fingerprint", "split_fingerprints",
      "data_quality_profile_id", "data_quality_profile_fingerprint",
      "data_quality_report_fingerprint")
  return {key: selector_params[key]
          for key in (("schema_version",) + required + optional_binding)
          if key in selector_params}


def selector_fingerprint(selector_params):
  return fingerprint_value(selector_contract(selector_params))


def artifact_identity_from_config(config):
  """Builds the immutable identity carried by every v3 artifact."""
  validate_config(config, require_resolved=True)
  identity = {
      "schema_version": config["schema_version"],
      "workload_id": config["run"]["workload"],
      "config_fingerprint": config_fingerprint(config),
  }
  if config["schema_version"] == SCHEMA_VERSION:
    identity.update({
        "contract_id": CONTRACT_ID,
        "run_profile": config["run_profile"],
        "artifact_class": config["validation"]["artifact_class"],
        "git_commit": config.get("run", {}).get("git_commit", "unknown"),
    })
    for key in (
        "source_manifest_fingerprint", "split_fingerprints",
        "data_quality_profile_id", "data_quality_profile_fingerprint",
        "data_quality_report_fingerprint"):
      if key in config.get("run", {}):
        identity[key] = copy.deepcopy(config["run"][key])
  return identity


def validate_artifact_identity(config, artifact, context,
                               expected_extra=None):
  """Hard-fails schema/contract/profile/workload/fingerprint mismatches."""
  expected = artifact_identity_from_config(config)
  actual = {}
  for key in expected:
    if key == "workload_id" and key not in artifact:
      actual[key] = artifact.get("workload")
    else:
      actual[key] = artifact.get(key)
  if expected_extra:
    expected.update(expected_extra)
    actual.update({key: artifact.get(key) for key in expected_extra})
  missing = [key for key in expected if actual.get(key) is None]
  mismatches = {
      key: (expected[key], actual.get(key)) for key in expected
      if actual.get(key) is not None and actual.get(key) != expected[key]
  }
  if missing or mismatches:
    raise ValueError(
        "{} identity mismatch; missing={} mismatches={}".format(
            context, missing, mismatches))
  if (config["schema_version"] == SCHEMA_VERSION and
      config["run_profile"] == OFFICIAL_PROFILE and
      artifact.get("artifact_class") != "official"):
    raise ValueError("{} rejects smoke_only artifacts in official mode.".format(
        context))
  return artifact


def validate_selector_params(config, selector_params):
  validate_artifact_identity(config, selector_params, "selector_params")
  selector_contract(selector_params)
  if config["schema_version"] == SCHEMA_VERSION:
    expected = {
        "behavior_policy": "lru",
        "tail_policy": "drop_incomplete_window",
        "selection_rule": (
            "selector_recall_desc,nregret_asc,uniform_distance,lexicographic"),
    }
    for key, value in expected.items():
      if selector_params.get(key) != value:
        raise ValueError("selector_params {} mismatch.".format(key))
  return selector_params


def validate_result_contract(config, result, selector_params=None,
                             checkpoint_fingerprint=None,
                             selector_config=None):
  validate_artifact_identity(config, result, "result")
  if config["schema_version"] == SCHEMA_VERSION:
    required = (
        "policy", "total_accesses", "hits", "misses", "nvm_reads",
        "nvm_writes",
        "migrations", "weighted_access_cost",
        "cost_model", "nvm_capacity_pages", "dram_initial_state",
        "initial_residency", "trace_page_backing",
        "first_touch_accounting", "dirty_demotion_nvm_write")
    missing = [key for key in required if key not in result]
    if missing:
      raise ValueError("result missing fields: {}".format(missing))
    if int(result["hits"]) + int(result["misses"]) != int(
        result["total_accesses"]):
      raise ValueError("result hit/miss accounting mismatch.")
    if result["cost_model"] != config["cost_model"]:
      raise ValueError("result cost_model mismatch.")
    evaluation_split = result.get("evaluation_split", "test")
    if evaluation_split not in ("valid", "test"):
      raise ValueError("result evaluation_split must be valid or test.")
    expected_trace_fingerprint = fingerprint_file(
        config["data"]["{}_trace".format(evaluation_split)])
    if evaluation_split == "test":
      if result.get(
          "test_trace_fingerprint") != expected_trace_fingerprint:
        raise ValueError("result/test trace fingerprint mismatch.")
    else:
      if result.get(
          "evaluation_trace_fingerprint") != expected_trace_fingerprint:
        raise ValueError("result/valid trace fingerprint mismatch.")
      if result.get("test_used_for_selection") is not False:
        raise ValueError(
            "Validation replay must declare test_used_for_selection=false.")
    if result["nvm_capacity_pages"] is not None:
      raise ValueError("result NVM capacity must be unbounded/null.")
    for key in (
        "dram_initial_state", "initial_residency", "trace_page_backing",
        "first_touch_accounting", "dirty_demotion_nvm_write"):
      if result[key] != config["replay"][key]:
        raise ValueError("result replay semantic mismatch: {}.".format(key))
  expected_contract = contract_from_config(config)
  assert_contract_matches(
      expected_contract, result.get("experiment_contract", {}), "result")
  if selector_params is not None:
    validate_selector_params(selector_config or config, selector_params)
    if result.get("selector_fingerprint") != selector_fingerprint(
        selector_params):
      raise ValueError("result/selector fingerprint mismatch.")
    if (config["schema_version"] == SCHEMA_VERSION and
        result.get("policy") == "qmap"):
      metric_names = (
          "PoolRecall@B", "SelectorRecall@K", "EndToEndRecall@K",
          "TieCoverage@K", "NRegret")
      coverage = result.get("candidate_coverage_validation", {})
      if any(name not in coverage for name in metric_names):
        raise ValueError("QMAP result is missing selector coverage metrics.")
      if any(coverage[name] != selector_params[name]
             for name in metric_names):
        raise ValueError("QMAP result/selector coverage metric mismatch.")
      expected_source = (
          "valid_trace" if uses_independent_validation(config) else
          "train_trace_decision_holdout")
      if result.get("candidate_coverage_metric_source") != expected_source:
        raise ValueError(
            "QMAP result coverage source must be {}.".format(
                expected_source))
  if (checkpoint_fingerprint is not None and
      result.get("checkpoint_fingerprint") != checkpoint_fingerprint):
    raise ValueError("result/checkpoint fingerprint mismatch.")
  return result


def decision_holdout_fingerprint(holdout):
  payload = copy.deepcopy(holdout)
  payload.pop("fingerprint", None)
  return fingerprint_value(payload)


def validate_decision_holdout(holdout, config=None):
  required = (
      "strategy", "basis", "order", "holdout_fraction", "rounding",
      "guard_accesses", "trace_access_count", "total_decision_points",
      "train_access_end_exclusive", "validation_access_start_inclusive",
      "train_decision_points", "guard_decision_points",
      "validation_decision_points", "last_train_decision_index",
      "first_validation_decision_index", "fingerprint")
  missing = [key for key in required if key not in holdout]
  if missing:
    raise ValueError("Decision holdout missing fields: {}".format(missing))
  if holdout["fingerprint"] != decision_holdout_fingerprint(holdout):
    raise ValueError("Decision holdout fingerprint mismatch.")
  if (holdout["basis"] != "lru_victim_decision_points" or
      holdout["order"] != "chronological"):
    raise ValueError("Decision holdout basis/order mismatch.")
  guard = int(holdout["guard_accesses"])
  total_decisions = int(holdout["total_decision_points"])
  train_decisions = int(holdout["train_decision_points"])
  guard_decisions = int(holdout["guard_decision_points"])
  validation_decisions = int(holdout["validation_decision_points"])
  if train_decisions + guard_decisions + validation_decisions != (
      total_decisions):
    raise ValueError("Decision holdout counts do not cover all decisions.")
  expected_validation = int(math.ceil(
      total_decisions * float(holdout["holdout_fraction"])))
  if validation_decisions != expected_validation:
    raise ValueError("Decision holdout validation count/ratio mismatch.")
  validation_start = int(holdout["validation_access_start_inclusive"])
  if int(holdout["first_validation_decision_index"]) != validation_start:
    raise ValueError("Decision holdout validation boundary mismatch.")
  if int(holdout["train_access_end_exclusive"]) != validation_start - guard:
    raise ValueError("Decision holdout guard boundary mismatch.")
  if int(holdout["last_train_decision_index"]) >= int(
      holdout["train_access_end_exclusive"]):
    raise ValueError("Decision holdout training boundary mismatch.")
  if validation_start >= int(holdout["trace_access_count"]):
    raise ValueError("Decision holdout validation starts outside the trace.")
  if int(holdout["last_train_decision_index"]) + guard >= int(
      holdout["first_validation_decision_index"]):
    raise ValueError("Decision holdout does not isolate future labels.")
  if int(holdout["validation_decision_points"]) <= 0:
    raise ValueError("Decision holdout has no validation decisions.")
  if int(holdout["train_decision_points"]) <= 0:
    raise ValueError("Decision holdout has no training decisions.")
  if config is not None:
    validation = config["validation"]
    expected = {
        "strategy": validation["strategy"],
        "holdout_fraction": float(validation["holdout_fraction"]),
        "rounding": validation["rounding"],
        "guard_accesses": int(validation["guard_accesses"]),
    }
    actual = {key: holdout[key] for key in expected}
    if actual != expected:
      raise ValueError(
          "Decision holdout/config mismatch: expected={} actual={}.".format(
              expected, actual))
  return holdout


def metadata_path(jsonl_path):
  return jsonl_path + ".metadata.json"


def load_jsonl_metadata(jsonl_path, config=None, split=None,
                        selector_params=None):
  path = metadata_path(jsonl_path)
  if not os.path.exists(path):
    raise FileNotFoundError("Finals JSONL metadata not found: {}".format(path))
  metadata = load_json(path)
  actual = fingerprint_file(jsonl_path)
  if metadata.get("data_fingerprint") != actual:
    raise ValueError("JSONL fingerprint mismatch for {}.".format(jsonl_path))
  if config is not None:
    validate_artifact_identity(config, metadata, "JSONL metadata")
    if split is not None and metadata.get("split") != split:
      raise ValueError("JSONL split mismatch: expected {}.".format(split))
    assert_contract_matches(
        contract_from_config(config), metadata.get("experiment_contract", {}),
        "JSONL metadata")
    if selector_params is not None:
      validate_selector_params(config, selector_params)
      if metadata.get("selector_fingerprint") != selector_fingerprint(
          selector_params):
        raise ValueError("JSONL/selector fingerprint mismatch.")
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
  _bind_resolved_data_manifest(config, project_root=project_root)
  validate_config(config, require_resolved=True)
  config["run"]["resolved_config_fingerprint"] = config_fingerprint(config)
  return config
