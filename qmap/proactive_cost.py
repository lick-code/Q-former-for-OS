# coding=utf-8
"""Strict, replay-independent Cost computation for proactive CAPD stage 2.

This module consumes already-aggregated event counters.  It never reads a
trace, imports Replay/model code, or changes policy behavior.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


SCHEMA_NAME = "capd_proactive_stage2_cost_profiles"
SCHEMA_VERSION = "capd_proactive_stage2_cost_profiles_v1_0"
CONTRACT_VERSION = "capd_proactive_raw_events_v1_0"
STAGE_STATUS = "stage2_implemented_awaiting_stage1_integration"
NORMALIZATION_BASIS = "dram_hit_equals_1"
CALIBRATION_MODE = "parameterized_profile_set"
PROVENANCE_PLATFORM = "no_real_nvm_platform"
PROFILE_WEIGHT_FIELDS = ("dram_hit", "nvm_read", "nvm_write", "demotion")
REQUIRED_COUNT_FIELDS = ("dram_hits", "nvm_reads", "nvm_writes")
DEMOTION_TOTAL_FIELD = "total_demotions"
DEMOTION_BREAKDOWN_FIELDS = (
    "proactive_demotions", "reactive_demotions", "emergency_demotions")
FROZEN_PROFILE_NAMES = (
    "read_light", "default", "write_expensive", "migration_expensive")
FROZEN_PROFILE_WEIGHTS = {
    "read_light": {
        "dram_hit": 1, "nvm_read": 2, "nvm_write": 4, "demotion": 8},
    "default": {
        "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
    "write_expensive": {
        "dram_hit": 1, "nvm_read": 2, "nvm_write": 12, "demotion": 10},
    "migration_expensive": {
        "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 20},
}
RESULT_NAMESPACE = "stage2_cost"


class CostContractError(ValueError):
  """Raised when a profile configuration or raw record violates the contract."""


def _require_exact_keys(value: Mapping[str, Any], expected: Iterable[str],
                        context: str) -> None:
  expected_set = set(expected)
  actual_set = set(value)
  missing = sorted(expected_set - actual_set)
  extra = sorted(actual_set - expected_set)
  if missing or extra:
    raise CostContractError(
        "{} keys mismatch; missing={} extra={}.".format(
            context, missing, extra))


def _require_non_negative_integer(value: Any, field: str) -> int:
  if isinstance(value, bool) or not isinstance(value, int):
    raise CostContractError(
        "{} must be an integer, not {}.".format(
            field, type(value).__name__))
  if value < 0:
    raise CostContractError("{} must be greater than or equal to 0.".format(
        field))
  return value


def _require_positive_integer(value: Any, field: str) -> int:
  value = _require_non_negative_integer(value, field)
  if value == 0:
    raise CostContractError("{} must be greater than 0.".format(field))
  return value


def _reject_json_constant(value: str) -> None:
  raise CostContractError(
      "Non-finite JSON numeric constant is forbidden: {}.".format(value))


def _unique_json_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
  value: Dict[str, Any] = {}
  for key, item in pairs:
    if key in value:
      raise CostContractError("Duplicate JSON object key: {}.".format(key))
    value[key] = item
  return value


def load_strict_json(path: str) -> Any:
  """Loads JSON while rejecting duplicate keys and NaN/Infinity."""
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(
        input_file,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant)


@dataclass(frozen=True)
class CostProfile:
  """One frozen set of positive integer relative event weights."""

  name: str
  dram_hit: int
  nvm_read: int
  nvm_write: int
  demotion: int

  @classmethod
  def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "CostProfile":
    if not isinstance(name, str) or not name:
      raise CostContractError("Profile name must be a non-empty string.")
    if not isinstance(value, Mapping):
      raise CostContractError(
          "Profile {} must be a JSON object.".format(name))
    _require_exact_keys(value, PROFILE_WEIGHT_FIELDS, "profile {}".format(
        name))
    return cls(
        name=name,
        dram_hit=_require_positive_integer(
            value["dram_hit"], "{}.dram_hit".format(name)),
        nvm_read=_require_positive_integer(
            value["nvm_read"], "{}.nvm_read".format(name)),
        nvm_write=_require_positive_integer(
            value["nvm_write"], "{}.nvm_write".format(name)),
        demotion=_require_positive_integer(
            value["demotion"], "{}.demotion".format(name)))

  def weights_dict(self) -> Dict[str, int]:
    return {
        "dram_hit": self.dram_hit,
        "nvm_read": self.nvm_read,
        "nvm_write": self.nvm_write,
        "demotion": self.demotion,
    }


@dataclass(frozen=True)
class RawEventCounts:
  """Normalized raw counters accepted by the stage-2 Cost contract."""

  dram_hits: int
  nvm_reads: int
  nvm_writes: int
  total_demotions: int
  proactive_demotions: Optional[int] = None
  reactive_demotions: Optional[int] = None
  emergency_demotions: Optional[int] = None

  def to_dict(self) -> Dict[str, int]:
    value = {
        "dram_hits": self.dram_hits,
        "nvm_reads": self.nvm_reads,
        "nvm_writes": self.nvm_writes,
        "total_demotions": self.total_demotions,
    }
    if self.proactive_demotions is not None:
      value.update({
          "proactive_demotions": self.proactive_demotions,
          "reactive_demotions": self.reactive_demotions,
          "emergency_demotions": self.emergency_demotions,
      })
    return value


@dataclass(frozen=True)
class CostResult:
  """Serializable weighted Cost result and its auditable components."""

  profile_name: str
  raw_counts: RawEventCounts
  weights: CostProfile
  dram_hit_cost: int
  nvm_read_cost: int
  nvm_write_cost: int
  demotion_cost: int
  weighted_cost: int

  def to_dict(self) -> Dict[str, Any]:
    components = {
        "dram_hit_cost": self.dram_hit_cost,
        "nvm_read_cost": self.nvm_read_cost,
        "nvm_write_cost": self.nvm_write_cost,
        "demotion_cost": self.demotion_cost,
    }
    if sum(components.values()) != self.weighted_cost:
      raise AssertionError("Cost component sum does not equal weighted_cost.")
    return {
        "profile_name": self.profile_name,
        "raw_counts": self.raw_counts.to_dict(),
        "weights": self.weights.weights_dict(),
        "component_costs": components,
        "weighted_cost": self.weighted_cost,
    }


@dataclass(frozen=True)
class CostConfiguration:
  """Validated immutable view of the stage-2 configuration."""

  schema_name: str
  schema_version: str
  contract_version: str
  default_profile: str
  normalization_basis: str
  calibration_mode: str
  stage_status: str
  stage1_integration_completed: bool
  profiles: Mapping[str, CostProfile]
  source: Mapping[str, Any]


def validate_cost_config(value: Mapping[str, Any]) -> CostConfiguration:
  """Strictly validates the frozen stage-2 profile configuration."""
  if not isinstance(value, Mapping):
    raise CostContractError("Cost configuration must be a JSON object.")
  top_level_fields = (
      "schema_name", "schema_version", "contract_version", "default_profile",
      "normalization_basis", "calibration_mode", "provenance", "profiles",
      "raw_event_contract", "weighted_cost_formula", "stage_status",
      "stage1_integration_completed")
  _require_exact_keys(value, top_level_fields, "cost configuration")

  expected_scalars = {
      "schema_name": SCHEMA_NAME,
      "schema_version": SCHEMA_VERSION,
      "contract_version": CONTRACT_VERSION,
      "default_profile": "default",
      "normalization_basis": NORMALIZATION_BASIS,
      "calibration_mode": CALIBRATION_MODE,
      "stage_status": STAGE_STATUS,
      "stage1_integration_completed": False,
  }
  for field, expected in expected_scalars.items():
    if value[field] != expected:
      raise CostContractError(
          "{} must be {!r}, got {!r}.".format(
              field, expected, value[field]))

  provenance = value["provenance"]
  if not isinstance(provenance, Mapping):
    raise CostContractError("provenance must be a JSON object.")
  _require_exact_keys(
      provenance,
      ("default_rationale", "platform_availability", "profile_source",
       "selection_constraint"),
      "provenance")
  if provenance["platform_availability"] != PROVENANCE_PLATFORM:
    raise CostContractError(
        "provenance.platform_availability must state that no real NVM "
        "platform is available.")
  if provenance["profile_source"] != "parameterized_relative_cost_assumptions":
    raise CostContractError("Unsupported profile provenance.")
  if provenance["selection_constraint"] != "predeclared_before_capd_results":
    raise CostContractError(
        "Cost profiles must be predeclared before CAPD results.")
  expected_rationale = (
      "该配置位于所考察参数区间的中部，用于表示目标分层存储系统的一组"
      "中间相对代价假设。")
  if provenance["default_rationale"] != expected_rationale:
    raise CostContractError("The frozen default-profile rationale changed.")

  profile_values = value["profiles"]
  if not isinstance(profile_values, Mapping):
    raise CostContractError("profiles must be a JSON object.")
  if set(profile_values) != set(FROZEN_PROFILE_NAMES):
    raise CostContractError(
        "profiles must contain exactly {}.".format(FROZEN_PROFILE_NAMES))
  profiles: Dict[str, CostProfile] = {}
  for name in FROZEN_PROFILE_NAMES:
    profile = CostProfile.from_mapping(name, profile_values[name])
    if profile.weights_dict() != FROZEN_PROFILE_WEIGHTS[name]:
      raise CostContractError(
          "Frozen weights changed for profile {}.".format(name))
    if profile.dram_hit != 1:
      raise CostContractError(
          "normalization_basis requires every dram_hit weight to equal 1.")
    profiles[name] = profile

  raw_contract = value["raw_event_contract"]
  if not isinstance(raw_contract, Mapping):
    raise CostContractError("raw_event_contract must be a JSON object.")
  _require_exact_keys(
      raw_contract,
      ("count_type", "required_base_fields", "demotion_total_field",
       "demotion_breakdown_fields", "demotion_rule",
       "identity_fields_preserved", "stage1_adapter_status"),
      "raw_event_contract")
  expected_raw = {
      "count_type": "non_negative_integer",
      "required_base_fields": list(REQUIRED_COUNT_FIELDS),
      "demotion_total_field": DEMOTION_TOTAL_FIELD,
      "demotion_breakdown_fields": list(DEMOTION_BREAKDOWN_FIELDS),
      "demotion_rule": (
          "total_or_complete_breakdown; when both are present "
          "total_must_equal_breakdown_sum"),
      "identity_fields_preserved": [
          "workload", "policy", "seed", "capacity_ratio", "run_id",
          "schema_version"],
      "stage1_adapter_status": "awaiting_stage1_field_freeze",
  }
  if raw_contract != expected_raw:
    raise CostContractError("raw_event_contract differs from the frozen v1.0 contract.")

  formula = value["weighted_cost_formula"]
  if not isinstance(formula, Mapping):
    raise CostContractError("weighted_cost_formula must be a JSON object.")
  _require_exact_keys(
      formula, ("expression", "components", "integer_arithmetic"),
      "weighted_cost_formula")
  expected_expression = (
      "dram_hit * dram_hits + nvm_read * nvm_reads + nvm_write * "
      "nvm_writes + demotion * total_demotions")
  expected_components = {
      "dram_hit_cost": "dram_hit * dram_hits",
      "nvm_read_cost": "nvm_read * nvm_reads",
      "nvm_write_cost": "nvm_write * nvm_writes",
      "demotion_cost": "demotion * total_demotions",
  }
  if (formula["expression"] != expected_expression or
      formula["components"] != expected_components or
      formula["integer_arithmetic"] is not True):
    raise CostContractError("weighted_cost_formula differs from the frozen formula.")

  return CostConfiguration(
      schema_name=value["schema_name"],
      schema_version=value["schema_version"],
      contract_version=value["contract_version"],
      default_profile=value["default_profile"],
      normalization_basis=value["normalization_basis"],
      calibration_mode=value["calibration_mode"],
      stage_status=value["stage_status"],
      stage1_integration_completed=value["stage1_integration_completed"],
      profiles=profiles,
      source=copy.deepcopy(value))


def load_cost_config(path: str) -> CostConfiguration:
  """Loads and validates a stage-2 Cost configuration from disk."""
  return validate_cost_config(load_strict_json(path))


def normalize_raw_event_counts(value: Mapping[str, Any]) -> RawEventCounts:
  """Validates and normalizes one raw event summary without mutating it.

  ``total_demotions`` may be supplied directly.  Alternatively, all three
  breakdown fields may be supplied and their sum becomes ``total_demotions``.
  If total and breakdown are both present, exact equality is mandatory.
  """
  if not isinstance(value, Mapping):
    raise CostContractError("Raw event summary must be a mapping.")
  counts: Dict[str, int] = {}
  for field in REQUIRED_COUNT_FIELDS:
    if field not in value:
      raise CostContractError("Missing required raw event field: {}.".format(
          field))
    counts[field] = _require_non_negative_integer(value[field], field)

  has_total = DEMOTION_TOTAL_FIELD in value
  split_presence = {
      field: field in value for field in DEMOTION_BREAKDOWN_FIELDS}
  has_any_split = any(split_presence.values())
  has_all_splits = all(split_presence.values())
  if has_any_split and not has_all_splits:
    missing = [
        field for field, present in split_presence.items() if not present]
    raise CostContractError(
        "Demotion breakdown is partial; missing {}.".format(missing))
  if not has_total and not has_all_splits:
    raise CostContractError(
        "Missing demotion information: provide total_demotions or all three "
        "demotion breakdown fields.")

  split_counts: Dict[str, int] = {}
  if has_all_splits:
    for field in DEMOTION_BREAKDOWN_FIELDS:
      split_counts[field] = _require_non_negative_integer(
          value[field], field)
    split_total = sum(split_counts.values())
  else:
    split_total = 0

  if has_total:
    total = _require_non_negative_integer(
        value[DEMOTION_TOTAL_FIELD], DEMOTION_TOTAL_FIELD)
    if has_all_splits and total != split_total:
      raise CostContractError(
          "total_demotions={} does not equal breakdown sum={}.".format(
              total, split_total))
  else:
    total = split_total

  return RawEventCounts(
      dram_hits=counts["dram_hits"],
      nvm_reads=counts["nvm_reads"],
      nvm_writes=counts["nvm_writes"],
      total_demotions=total,
      proactive_demotions=split_counts.get("proactive_demotions"),
      reactive_demotions=split_counts.get("reactive_demotions"),
      emergency_demotions=split_counts.get("emergency_demotions"))


def compute_weighted_cost(raw_counts: Any,
                          profile: CostProfile) -> CostResult:
  """Computes one profile with deterministic integer arithmetic."""
  if isinstance(raw_counts, Mapping):
    raw_counts = normalize_raw_event_counts(raw_counts)
  if not isinstance(raw_counts, RawEventCounts):
    raise CostContractError(
        "raw_counts must be RawEventCounts or a raw-event mapping.")
  if not isinstance(profile, CostProfile):
    raise CostContractError("profile must be a validated CostProfile.")
  dram_hit_cost = raw_counts.dram_hits * profile.dram_hit
  nvm_read_cost = raw_counts.nvm_reads * profile.nvm_read
  nvm_write_cost = raw_counts.nvm_writes * profile.nvm_write
  demotion_cost = raw_counts.total_demotions * profile.demotion
  weighted_cost = (
      dram_hit_cost + nvm_read_cost + nvm_write_cost + demotion_cost)
  return CostResult(
      profile_name=profile.name,
      raw_counts=raw_counts,
      weights=profile,
      dram_hit_cost=dram_hit_cost,
      nvm_read_cost=nvm_read_cost,
      nvm_write_cost=nvm_write_cost,
      demotion_cost=demotion_cost,
      weighted_cost=weighted_cost)


def compute_all_profiles(
    raw_counts: Any,
    profiles: Mapping[str, CostProfile]) -> Dict[str, CostResult]:
  """Computes every supplied profile from one normalized counter snapshot."""
  if isinstance(raw_counts, Mapping):
    raw_counts = normalize_raw_event_counts(raw_counts)
  if not isinstance(profiles, Mapping) or not profiles:
    raise CostContractError("profiles must be a non-empty mapping.")
  results: Dict[str, CostResult] = {}
  for name, profile in profiles.items():
    if name in results:
      raise CostContractError("Duplicate profile name: {}.".format(name))
    if not isinstance(profile, CostProfile) or profile.name != name:
      raise CostContractError(
          "Profile mapping key/name mismatch for {}.".format(name))
    results[name] = compute_weighted_cost(raw_counts, profile)
  normalized = raw_counts.to_dict()
  if any(result.raw_counts.to_dict() != normalized
         for result in results.values()):
    raise AssertionError("Profiles did not reuse identical raw counts.")
  return results


def select_profiles(config: CostConfiguration, profile_names: Sequence[str]
                    ) -> Dict[str, CostProfile]:
  """Selects profiles in caller order while rejecting duplicates/unknowns."""
  if not profile_names:
    raise CostContractError("At least one profile must be selected.")
  selected: Dict[str, CostProfile] = {}
  for name in profile_names:
    if name in selected:
      raise CostContractError("Duplicate selected profile: {}.".format(name))
    if name not in config.profiles:
      raise CostContractError(
          "Unknown profile {}; expected one of {}.".format(
              name, tuple(config.profiles)))
    selected[name] = config.profiles[name]
  return selected


def recompute_record(record: Mapping[str, Any], config: CostConfiguration,
                     profile_names: Optional[Sequence[str]] = None
                     ) -> Dict[str, Any]:
  """Returns a deep-copied input record with a namespaced Cost result.

  All original fields—including experiment identity and raw counters—are
  retained byte-for-byte at the value level.  Stage-2 output is added only
  under ``stage2_cost``.
  """
  if not isinstance(record, Mapping):
    raise CostContractError("Each input record must be a JSON object.")
  if RESULT_NAMESPACE in record:
    raise CostContractError(
        "Input already contains reserved field {!r}; refusing to overwrite."
        .format(RESULT_NAMESPACE))
  names = tuple(profile_names or (config.default_profile,))
  selected = select_profiles(config, names)
  raw_counts = normalize_raw_event_counts(record)
  results = compute_all_profiles(raw_counts, selected)
  output = copy.deepcopy(dict(record))
  cost_payload: Dict[str, Any] = {
      "schema_name": config.schema_name,
      "schema_version": config.schema_version,
      "contract_version": config.contract_version,
      "stage_status": config.stage_status,
      "default_profile": config.default_profile,
      "selected_profiles": list(names),
      "raw_counts": raw_counts.to_dict(),
      "cost_results": {
          name: result.to_dict() for name, result in results.items()},
  }
  if config.default_profile in results:
    cost_payload["default_weighted_cost"] = results[
        config.default_profile].weighted_cost
  output[RESULT_NAMESPACE] = cost_payload
  return output


def assert_finite_json_tree(value: Any) -> None:
  """Defensive serialization gate; stage-2 integers are always finite."""
  if isinstance(value, Mapping):
    for item in value.values():
      assert_finite_json_tree(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      assert_finite_json_tree(item)
  elif isinstance(value, float) and not math.isfinite(value):
    raise CostContractError("Output contains NaN or Infinity.")
