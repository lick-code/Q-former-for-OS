# coding=utf-8
"""Preregistered CAPD stage-6 robustness variants.

Stage 6 does not change the CAPD method.  Capacity variants change only the
DRAM capacity ``D`` and therefore rebuild train/valid selector and reranker
artifacts before retraining.  The original test trace remains final-evaluation
only.
"""

from __future__ import print_function

import copy

from qmap import finals_config


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
MODEL_SEEDS = (3136859, 42, 2026)
RANDOM_REPLAY_SEEDS = (0, 1, 2)
CAPACITIES = (128, 256)


def capacity_spec(capacity):
  capacity = int(capacity)
  if capacity not in CAPACITIES:
    raise ValueError("Unsupported stage-6 capacity: {}".format(capacity))
  return {
      "variant_id": "capacity_D{}".format(capacity),
      "family": "capacity_robustness",
      "only_difference": "only DRAM capacity D changes from 64 to {}".format(
          capacity),
      "source_stage": "stage6",
      "test_used_for_selection": False,
      "retrain_required": True,
      "capacity": capacity,
  }


def capacity_specs():
  return [capacity_spec(capacity) for capacity in CAPACITIES]


def build_capacity_config(base_config, capacity):
  """Builds a resolved config whose only method-setting change is D."""
  spec = capacity_spec(capacity)
  config = copy.deepcopy(base_config)
  if config.get("stage5_variant") is not None:
    raise ValueError("Stage-6 capacity must start from Stage-5 Full.")
  config["memory"]["dram_capacity_pages"] = spec["capacity"]
  config["stage6_variant"] = {
      key: copy.deepcopy(spec[key]) for key in (
          "variant_id", "family", "only_difference", "source_stage",
          "test_used_for_selection", "retrain_required")
  }
  config.setdefault("run", {}).pop("resolved_config_fingerprint", None)
  finals_config.validate_config(config, require_resolved=True)
  config["run"]["resolved_config_fingerprint"] = (
      finals_config.config_fingerprint(config))
  finals_config.validate_config(config, require_resolved=True)
  return config
