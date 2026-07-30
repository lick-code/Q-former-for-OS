# coding=utf-8
"""Frozen contracts, portable Stage-4 bindings, and Stage-5 fairness gates."""

from __future__ import annotations

import copy
import os
import re
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from qmap import proactive_stage4


SCHEMA_VERSION = "capd_proactive_stage5_v1_0"
CONTRACT_ID = "CAPD-PROACTIVE-STAGE5-1.0"
RESULT_SCHEMA_VERSION = "capd_proactive_stage5_result_v1_0"
RUN_MANIFEST_SCHEMA_VERSION = "capd_proactive_stage5_run_manifest_v1_0"
IMPLEMENTED = "stage5_implemented"
VERIFIED = "stage5_baseline_framework_verified"
NOT_VERIFIED = "stage5_not_verified"
PENDING_TPP = "pending_stage6"

RUNNABLE_POLICIES = (
    "reactive_lru", "proactive_lru", "proactive_clock", "capd", "oracle")
FORMAL_POLICIES = (
    "reactive_lru", "proactive_lru", "proactive_clock", "tpp_inspired",
    "capd", "oracle")
ACTIVE_POLICIES = tuple(
    policy for policy in FORMAL_POLICIES if policy != "reactive_lru")
CAPD_SEEDS = (3136859, 42, 2026)
FORBIDDEN_POLICY_TOKENS = (
    "random", "lfu", "old_capd", "reactive_capd", "autonuma", "pet",
    "flexmem")
LEGACY_STAGE_ARTIFACT_RE = re.compile(
    r"(?:^|/)(?:outputs/results/finals_v3_official/"
    r"(?:stage4|stage5)(?:[_.-][^/]*)?|stage4_audits)(?:/|$)",
    re.IGNORECASE)
TEST_TOKEN_RE = re.compile(r"(?:^|[_./-])test(?:[_./-]|$)", re.IGNORECASE)

FROZEN_METHOD = {
    "working_set_definition": "active_unique_pages_from_train_and_validation",
    "dram_working_set_ratio": 0.2,
    "F_low": 8,
    "F_target": 16,
    "b_max": 4,
    "candidate_size_K": 8,
    "candidate_source": "lru_tail",
    "selector": "disabled",
    "fallback_policy": "lru",
    "trigger_mode": "low_watermark",
    "page_enter_dram_semantics":
        "occupies_one_free_frame_regardless_of_source",
    "page_size_bytes": 4096,
    "nvm_capacity_model": "unbounded_backing_tier",
}
FROZEN_MODEL = {
    "lookahead_L": 256,
    "label_weights": [1, 1, 2],
    "candidate_size_K": 8,
    "history_H": 20,
    "page_state_dim": 4,
    "seeds": list(CAPD_SEEDS),
    "checkpoint_selection_rule": "minimum_validation_loss_only",
    "checkpoint_tie_break": "earliest_epoch",
    "best_seed_selection_allowed": False,
}
FROZEN_COST = {
    "dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10}


class Stage5ContractError(ValueError):
  """Raised before any run when an authority or fairness contract differs."""


class PendingStage6Error(RuntimeError):
  """TPP-inspired is registered but deliberately unavailable in Stage 5."""

  status = PENDING_TPP


def _require(condition: Any, message: str) -> None:
  if not condition:
    raise Stage5ContractError(message)


def _normalized(path: str) -> str:
  return os.path.normpath(os.path.abspath(path)).replace("\\", "/")


def _is_within(path: str, root: str) -> bool:
  try:
    return os.path.commonpath(
        (os.path.abspath(path), os.path.abspath(root))) == os.path.abspath(root)
  except ValueError:
    return False


def load_config(path: str) -> Dict[str, Any]:
  value = proactive_stage4.load_json(path)
  validate_config(value)
  return value


def validate_config(value: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(isinstance(value, Mapping), "Stage-5 config must be an object.")
  _require(value.get("schema_version") == SCHEMA_VERSION,
           "Stage-5 schema_version mismatch.")
  _require(value.get("contract_id") == CONTRACT_ID,
           "Stage-5 contract_id mismatch.")
  _require(value.get("stage_status") == IMPLEMENTED,
           "The source config is a predeclared implemented-state contract.")
  _require(value.get("result_schema") ==
           "configs/finals/capd_proactive_stage5_result_schema.json",
           "Unified result schema binding changed.")
  _require(tuple(value["allowed_splits"]) == ("train", "validation"),
           "Only Train/Validation are allowed in Stage 5.")
  _require(tuple(value["forbidden_splits"]) == ("test",),
           "Test must be explicitly forbidden.")
  _require(value["frozen_method"] == dict(
      FROZEN_METHOD,
      capacity_claim="conditional_engineering_default_not_capacity_rule_v2_pass",
      initial_state="empty_dram_all_seen_pages_backed_by_nvm"),
      "Stage-3/Stage-4 frozen method parameters changed.")
  model = value["frozen_model"]
  for key, expected in FROZEN_MODEL.items():
    _require(model.get(key) == expected,
             "Frozen model field {} changed.".format(key))
  _require(value["cost_profile"]["name"] == "default" and
           value["cost_profile"]["weights"] == FROZEN_COST,
           "Stage-2 default Cost profile changed.")
  policies = value["policies"]
  _require(tuple(policies["formal_mainline"]) == FORMAL_POLICIES,
           "Formal baseline mainline changed.")
  _require(tuple(policies["runnable_stage5"]) == RUNNABLE_POLICIES,
           "Runnable Stage-5 policy set changed.")
  _require(policies["tpp_inspired"]["implementation_status"] == PENDING_TPP and
           policies["tpp_inspired"]["fallback_allowed"] is False,
           "TPP must remain pending_stage6 without fallback.")
  _require(value["stage4_authority"]["old_finals_v3_artifacts_allowed"] is False,
           "Historical Stage-4/5 artifacts must remain forbidden.")
  _require(value["framework_acceptance"]["formal_test_allowed"] is False and
           value["framework_acceptance"]["performance_conclusions_allowed"]
           is False,
           "Stage 5 cannot run formal Test or form performance conclusions.")
  return value


def resolve_repository_path(
    recorded_path: str, project_root: str,
    allowed_prefixes: Sequence[str], must_exist: bool = True) -> str:
  """Resolves a frozen server path using a safe repository-relative suffix.

  The original absolute path is accepted only when it is already inside the
  current repository.  Otherwise the first explicitly allowed repository
  prefix is extracted from the normalized path.
  """
  _require(isinstance(recorded_path, str) and recorded_path,
           "Recorded artifact path is empty.")
  root = os.path.abspath(project_root)
  normalized_recorded = recorded_path.replace("\\", "/")
  candidates: List[str] = []
  if os.path.isabs(recorded_path) and _is_within(recorded_path, root):
    candidates.append(os.path.abspath(recorded_path))
  elif not os.path.isabs(recorded_path):
    candidates.append(os.path.abspath(os.path.join(root, recorded_path)))
  lower = normalized_recorded.lower()
  for prefix in allowed_prefixes:
    marker = prefix.strip("/").replace("\\", "/")
    index = lower.find(marker.lower())
    if index >= 0:
      suffix = normalized_recorded[index:]
      candidates.append(os.path.abspath(os.path.join(
          root, *suffix.split("/"))))
  for candidate in candidates:
    if not _is_within(candidate, root):
      continue
    relative = os.path.relpath(candidate, root).replace("\\", "/")
    if not any(
        relative == prefix.strip("/") or
        relative.startswith(prefix.strip("/") + "/")
        for prefix in allowed_prefixes):
      continue
    if LEGACY_STAGE_ARTIFACT_RE.search(relative):
      raise Stage5ContractError(
          "Historical finals_v3 Stage-4/5 artifact is forbidden: {}".format(
              relative))
    if not must_exist or os.path.isfile(candidate):
      return candidate
  raise Stage5ContractError(
      "Cannot safely resolve frozen artifact inside repository: {}".format(
          recorded_path))


def _authority_path(config: Mapping[str, Any], key: str,
                    project_root: str) -> str:
  return resolve_repository_path(
      config["stage4_authority"][key], project_root, ("outputs",))


def audit_stage4_authority(
    config: Mapping[str, Any], project_root: str,
    require_checkpoints: bool = True) -> Dict[str, Any]:
  """Validates the complete Stage-4 verification/freeze/checkpoint chain."""
  validate_config(config)
  verification_path = _authority_path(config, "verification", project_root)
  freeze_path = _authority_path(config, "freeze_candidate", project_root)
  verification = proactive_stage4.load_json(verification_path)
  freeze = proactive_stage4.load_json(freeze_path)
  _require(verification.get("status") == "stage4_verified",
           "Stage-4 verification status is not stage4_verified.")
  _require(verification.get("contract_id") == "CAPD-PROACTIVE-STAGE4-1.0" and
           freeze.get("contract_id") == "CAPD-PROACTIVE-STAGE4-1.0",
           "Stage-4 contract ID mismatch.")
  _require(proactive_stage4.fingerprint_file(freeze_path) ==
           verification.get("final_freeze_candidate_sha256"),
           "Stage-4 freeze candidate SHA-256 is not bound by verification.")
  _require(verification.get("selected_parameters") == {
      "candidate_size_K": 8, "history_H": 20,
      "label_weights": [1.0, 1.0, 2.0], "lookahead_L": 256},
      "Stage-4 verified parameters changed.")
  _require(freeze.get("selected_parameters") ==
           verification["selected_parameters"],
           "Stage-4 freeze/verification parameter mismatch.")
  _require(freeze.get("selector_status") == "disabled" and
           verification.get("selector_status") == "disabled",
           "Stage-4 selector must remain disabled.")
  _require(freeze.get("test_trace_opened") is False and
           verification.get("test_trace_opened") is False,
           "Stage-4 authority reports Test contamination.")
  _require(verification.get("old_finals_v3_artifacts_used") is False,
           "Stage-4 authority reports historical artifact use.")
  _require(freeze.get("checkpoint_selection_rule") ==
           "minimum_validation_loss_only" and
           freeze.get("checkpoint_tie_break") == "earliest_epoch",
           "Checkpoint selection contract changed.")
  _require(freeze.get("stage3_capacity_claim") ==
           "conditional_engineering_default_not_capacity_rule_v2_pass",
           "20% capacity claim was incorrectly upgraded.")
  dataset_manifest_path = resolve_repository_path(
      freeze.get("final_dataset_manifest"), project_root,
      ("outputs/capd_proactive_stage4",), must_exist=True)
  _require(proactive_stage4.fingerprint_file(dataset_manifest_path) ==
           freeze.get("final_dataset_manifest_sha256"),
           "Stage-4 final dataset manifest SHA-256 mismatch.")
  dataset_manifest = proactive_stage4.load_json(dataset_manifest_path)
  _require(dataset_manifest.get("contract_id") ==
           "CAPD-PROACTIVE-STAGE4-1.0" and
           dataset_manifest.get("selector_status") == "disabled" and
           dataset_manifest.get("test_trace_opened") is False,
           "Stage-4 final dataset manifest is contaminated.")
  _require(dataset_manifest.get("identity", {}).get("parameters") == {
      "candidate_size_K": 8, "history_H": 20,
      "label_weights": [1.0, 1.0, 2.0], "lookahead_L": 256},
      "Stage-4 final dataset identity changed.")

  checkpoints = []
  seeds = []
  for item in freeze.get("final_checkpoints", []):
    seed = int(item["seed"])
    seeds.append(seed)
    path = resolve_repository_path(
        item["path"], project_root,
        ("outputs/capd_proactive_stage4",),
        must_exist=require_checkpoints)
    if require_checkpoints:
      _require(proactive_stage4.fingerprint_file(path) == item["sha256"],
               "Checkpoint SHA-256 mismatch for seed {}.".format(seed))
    _require(item.get("selection_criterion") ==
             "minimum_valid_loss_only",
             "Checkpoint was not selected by minimum Validation loss.")
    checkpoints.append({
        "seed": seed, "path": path, "sha256": item["sha256"],
        "selection_criterion": item["selection_criterion"]})
  _require(tuple(sorted(seeds)) == tuple(sorted(CAPD_SEEDS)),
           "Stage 4 must expose all three frozen checkpoints.")
  return {
      "verification_path": verification_path,
      "verification_sha256":
          proactive_stage4.fingerprint_file(verification_path),
      "freeze_candidate_path": freeze_path,
      "freeze_candidate_sha256":
          proactive_stage4.fingerprint_file(freeze_path),
      "checkpoints": sorted(checkpoints, key=lambda item: CAPD_SEEDS.index(
          item["seed"])),
      "dataset_manifest_path": dataset_manifest_path,
      "dataset_manifest_sha256":
          proactive_stage4.fingerprint_file(dataset_manifest_path),
      "dataset_identity_sha256":
          dataset_manifest["identity"]["identity_sha256"],
      "selector_status": "disabled",
      "test_trace_opened": False,
      "old_finals_v3_artifacts_used": False,
  }


def resolve_manifest_traces(
    config: Mapping[str, Any], project_root: str
) -> Tuple[Mapping[str, Any], Dict[str, Dict[str, Sequence[Any]]],
           List[Dict[str, Any]]]:
  manifest_path = _authority_path(config, "input_manifest", project_root)
  manifest = proactive_stage4.load_json(manifest_path)
  # Stage-4 manifests can contain absolute paths from another server.  Resolve
  # only raw dataset paths, write nothing, and preserve their frozen hashes.
  portable = copy.deepcopy(manifest)
  portable["path_base"] = "project_root"
  for entry in portable["entries"]:
    entry["trace_path"] = os.path.relpath(resolve_repository_path(
        entry["trace_path"], project_root, ("dataset",)), project_root)
  temporary_root = os.path.join(
      project_root, "outputs", "capd_proactive_stage5")
  os.makedirs(temporary_root, exist_ok=True)
  descriptor, temporary_manifest = tempfile.mkstemp(
      prefix=".portable-stage4-", suffix=".json", dir=temporary_root)
  os.close(descriptor)
  proactive_stage4.write_json_atomic(temporary_manifest, portable)
  try:
    return proactive_stage4.resolve_inputs(temporary_manifest, project_root)
  finally:
    try:
      os.unlink(temporary_manifest)
    except OSError:
      pass


def policy_status(policy: str) -> str:
  if policy == "tpp_inspired":
    return PENDING_TPP
  if policy in RUNNABLE_POLICIES:
    return "implemented"
  raise Stage5ContractError("Unknown formal policy: {}.".format(policy))


def assert_runnable_policy(policy: str) -> None:
  if policy == "tpp_inspired":
    raise PendingStage6Error(
        "TPP-inspired is pending_stage6; Stage 5 forbids fallback.")
  _require(policy in RUNNABLE_POLICIES,
           "Policy is not runnable in Stage 5: {}.".format(policy))
  _require(not any(token in policy for token in FORBIDDEN_POLICY_TOKENS),
           "Historical/non-mainline policy is forbidden: {}.".format(policy))


def candidate_contract_identity() -> Dict[str, Any]:
  value = {
      "candidate_source": "current_lru_tail",
      "candidate_size_K": 8,
      "candidate_order": "oldest_to_newest",
      "candidate_rebuilt_every_round": True,
      "padding": False,
      "current_entering_page_excluded_until_resident": True,
      "selection_subset_required": True,
  }
  value["sha256"] = proactive_stage4.fingerprint_value(value)
  return value


FAIRNESS_A_FIELDS = (
    "trace_sha256", "trace_range", "split", "split_role",
    "dram_capacity_pages", "nvm_capacity_model", "page_size_bytes",
    "working_set_definition", "working_set_pages",
    "dram_working_set_ratio", "capacity_claim",
    "page_enter_dram_semantics", "initial_state_sha256", "cost_profile",
    "F_low", "F_target", "candidate_size_K", "b_max", "b_t_rule",
    "fallback_policy", "trigger_mode", "candidate_source",
    "raw_access_event_count",
    "candidate_contract_sha256")
FAIRNESS_B_FIELDS = (
    "trace_sha256", "trace_range", "split", "split_role",
    "dram_capacity_pages", "nvm_capacity_model", "page_size_bytes",
    "working_set_definition", "working_set_pages",
    "dram_working_set_ratio", "capacity_claim",
    "page_enter_dram_semantics", "initial_state_sha256", "cost_profile",
    "raw_access_event_count", "lru_contract_sha256")


def _same(records: Sequence[Mapping[str, Any]], fields: Iterable[str],
          context: str) -> None:
  for field in fields:
    _require(all(field in row for row in records),
             "{} missing fairness field {}.".format(context, field))
    identities = {
        proactive_stage4.fingerprint_value(row[field]) for row in records}
    _require(len(identities) == 1,
             "{} differs on fairness field {}.".format(context, field))


def audit_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
  _require(result.get("schema_version") == RESULT_SCHEMA_VERSION,
           "Result schema is not proactive Stage 5.")
  _require(result.get("contract_id") == CONTRACT_ID,
           "Result contract ID mismatch.")
  policy = result.get("policy")
  assert_runnable_policy(policy)
  _require(result.get("split") in ("train", "validation") and
           result.get("split") != "test",
           "Stage-5 result cannot read Test.")
  _require(result.get("formal_test") is False and
           result.get("test_used_for_selection") is False,
           "Result reports Test contamination.")
  _require(result.get("selector_status") == "disabled",
           "Result enabled the legacy selector.")
  _require(result.get("old_finals_v3_stage_artifacts_used") is False,
           "Result used historical finals_v3 Stage-4/5 artifacts.")
  _require(result.get("B") is None,
           "Stage-5 result contains forbidden legacy B/selector semantics.")
  _require(result.get("cost_profile") == {
      "name": "default", "weights": FROZEN_COST},
      "Result Cost profile differs from the Stage-2 freeze.")
  _require(result.get("dram_working_set_ratio") == 0.2 and
           result.get("capacity_claim") ==
           "conditional_engineering_default_not_capacity_rule_v2_pass",
           "20% capacity engineering-default boundary changed.")
  _require(result.get("candidate_size_K") in (None, 8),
           "Candidate K changed.")
  _require(result.get("raw_access_event_count") ==
           result.get("summary", {}).get("total_accesses"),
           "Raw access-event count differs from Replay accounting.")
  checkpoint = result.get("checkpoint")
  if policy == "capd":
    _require(isinstance(checkpoint, Mapping) and
             int(checkpoint.get("seed")) == int(result.get("seed")) and
             int(result.get("seed")) in CAPD_SEEDS,
             "CAPD result lacks its independent frozen seed checkpoint.")
    digest = checkpoint.get("sha256")
    _require(isinstance(digest, str) and len(digest) == 64 and
             all(character in "0123456789abcdef" for character in digest),
             "CAPD checkpoint SHA-256 is invalid.")
    _require(checkpoint.get("selection_criterion") ==
             "minimum_valid_loss_only",
             "CAPD checkpoint selection criterion changed.")
    _require(result.get("future_information") == "not_accessed" and
             result.get("policy_state", {}).get("capd", {}).get(
                 "future_information_accessed") is False,
             "CAPD accessed future information.")
  else:
    _require(checkpoint is None,
             "A non-CAPD policy received a CAPD checkpoint.")
  if policy == "oracle":
    _require(result.get("future_information") ==
             "candidate_scoped_oracle_only",
             "Oracle future-information scope changed.")
  elif policy != "capd":
    _require(result.get("future_information") == "not_accessed",
             "Online rule policy accessed future information.")
  if policy == "reactive_lru":
    _require(all(result.get(key) is None for key in (
        "F_low", "F_target", "candidate_size_K", "b_max", "b_t_rule",
        "trigger_mode", "candidate_source", "fallback_policy")),
        "Reactive-LRU must not be forced to carry proactive controls.")
    summary = result["summary"]
    _require(summary["number_of_proactive_cycles"] == 0 and
             summary["number_of_proactive_rounds"] == 0 and
             summary["proactive_demotions"] == 0 and
             summary["emergency_demotions"] == 0,
             "Reactive-LRU created proactive/emergency events.")
  else:
    _require((result["F_low"], result["F_target"],
              result["candidate_size_K"], result["b_max"]) == (8, 16, 8, 4),
             "Active-policy frozen controls changed.")
    _require(result.get("fallback_policy") == "lru",
             "Active emergency fallback changed.")
    _require(result.get("trigger_mode") == "low_watermark" and
             result.get("candidate_source") == "lru_tail",
             "Active trigger/candidate-source contract changed.")
    _require(result["summary"]["reactive_demotions"] == 0,
             "Active policy emitted Reactive-LRU demotions.")
  summary = result["summary"]
  _require(summary["total_accesses"] ==
           summary["dram_hits"] + summary["nvm_reads"] +
           summary["nvm_writes"],
           "Raw access accounting mismatch.")
  _require(summary["total_demotions"] ==
           summary["proactive_demotions"] +
           summary["reactive_demotions"] +
           summary["emergency_demotions"],
           "Demotion accounting mismatch.")
  expected_event_types = (
      {"reactive_demotion"} if policy == "reactive_lru"
      else {"proactive_demotion", "emergency_fallback_demotion"})
  _require(all(event.get("event_type") in expected_event_types
               for event in result.get("events", [])),
           "Demotion event type is mixed across policy semantics.")
  for row in result.get("rounds", []):
    candidates = row["candidate_pages"]
    _require(isinstance(row.get("candidate_state_sha256"), str) and
             len(row["candidate_state_sha256"]) == 64,
             "Candidate pre-decision state fingerprint is missing.")
    _require(row["candidate_pages_sha256"] ==
             proactive_stage4.fingerprint_value(candidates),
             "Candidate-set fingerprint mismatch.")
    _require(len(candidates) <= 8 and len(candidates) == len(set(candidates)),
             "Candidate set is padded, oversized, or duplicated.")
    _require(set(row["selected_pages"]).issubset(set(candidates)),
             "Policy selected outside its supplied candidate set.")
    _require([item["page"] for item in row["candidate_features"]] ==
             candidates and
             [item["lru_tail_rank"]
              for item in row["candidate_features"]] ==
             list(range(len(candidates))),
             "Candidate features do not preserve the current LRU-tail identity.")
    _require(len(row.get("policy_scores", [])) == len(candidates) and
             {item["page"] for item in row["policy_scores"]} ==
             set(candidates),
             "Policy scores do not cover exactly the supplied candidates.")
  return result


def check_experiment_a(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  rows = [audit_result(row) for row in records]
  policies = {row["policy"] for row in rows}
  _require({"proactive_lru", "proactive_clock", "capd", "oracle"} <= policies,
           "Experiment A lacks a runnable Stage-5 policy.")
  _require("reactive_lru" not in policies and "tpp_inspired" not in policies,
           "Experiment A runnable table has an invalid policy.")
  capd_seeds = sorted(int(row["seed"]) for row in rows
                      if row["policy"] == "capd")
  _require(capd_seeds == sorted(CAPD_SEEDS),
           "Experiment A must keep all three CAPD seeds independently.")
  _same(rows, FAIRNESS_A_FIELDS, "Experiment A")
  by_predecision_state: Dict[str, set] = {}
  for result in rows:
    for decision in result.get("rounds", []):
      by_predecision_state.setdefault(
          decision["candidate_state_sha256"], set()).add(
              decision["candidate_pages_sha256"])
  _require(all(len(fingerprints) == 1
               for fingerprints in by_predecision_state.values()),
           "Identical pre-decision state produced inconsistent candidates.")
  return {
      "schema_version": "capd_proactive_stage5_fairness_v1_0",
      "contract_id": CONTRACT_ID,
      "experiment": "A",
      "status": "passed",
      "policies": sorted(policies),
      "capd_seeds": capd_seeds,
      "tpp_inspired_status": PENDING_TPP,
      "candidate_identity_check":
          "same_constructor_contract_per_round_snapshot_and_exact_identity_"
          "for_every_equal_predecision_state",
      "test_used_for_selection": False,
  }


def check_experiment_b(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
  rows = [audit_result(row) for row in records]
  _require({row["policy"] for row in rows} ==
           {"reactive_lru", "proactive_lru"},
           "Experiment B must contain only Reactive-LRU and Proactive-LRU.")
  _require(len(rows) == 2,
           "Experiment B requires exactly one row per deterministic policy.")
  _same(rows, FAIRNESS_B_FIELDS, "Experiment B")
  return {
      "schema_version": "capd_proactive_stage5_fairness_v1_0",
      "contract_id": CONTRACT_ID,
      "experiment": "B",
      "status": "passed",
      "policies": ["proactive_lru", "reactive_lru"],
      "expected_difference":
          "reactive_on_demand_vs_low_watermark_proactive_reserve",
      "test_used_for_selection": False,
  }


def audit_no_legacy_stage_artifacts(paths: Iterable[str]) -> None:
  for path in paths:
    normalized = str(path).replace("\\", "/")
    if LEGACY_STAGE_ARTIFACT_RE.search(normalized):
      raise Stage5ContractError(
          "Historical finals_v3 Stage-4/5 artifact cannot satisfy Stage 5: "
          + normalized)
