#!/usr/bin/env python3
# coding=utf-8
"""Orchestrate CAPD post-Stage-6 frozen-method optimization O0-O3.

O1-O3 consume train/valid only. Missing fresh holdouts block O4, not these
pre-holdout phases. Every compute job has an atomic manifest and is resumable.
"""

from __future__ import print_function

import argparse
import copy
import csv
import json
import os
import shlex
import statistics
import subprocess
import sys
import time
import traceback


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import optimization_variants


PROFILE_RELATIVE_PATH = (
    "configs/finals/capd_post_stage6_optimization_profile.json")
STAGE6_MANIFEST = (
    "outputs/results/finals_v3_official/stage6/run_manifest.json")
BRIDGE_MANIFEST = (
    "outputs/results/capd_bridge_diagnostic/run_manifest.json")
SOURCE_SPEC_ROOT = "dataset/metadata/finals_v3_source_specs"
EXPECTED_PHASE_ORDER = (
    "O0_PROTOCOL_AND_HOLDOUT",
    "O1_ORACLE_HEADROOM",
    "O2_CONFIG_SEARCH",
    "O3_MULTISEED_CONFIRMATION",
    "O4_FINAL_HOLDOUT_ONCE",
)
CLASSICAL_POLICIES = ("lru", "clock")


def _absolute(root, path):
  return path if os.path.isabs(path) else os.path.join(root, path)


def _portable(path, root):
  path = os.path.abspath(path)
  relative = os.path.relpath(path, root)
  if relative == os.pardir or relative.startswith(os.pardir + os.sep):
    return path
  return relative.replace(os.sep, "/")


def _load_json(path):
  with open(path, "r", encoding="utf-8") as source:
    return json.load(source)


def _atomic_json(path, value):
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  temporary = "{}.tmp.{}".format(path, os.getpid())
  finals_config.write_json(temporary, value)
  os.replace(temporary, path)


def _write_csv(path, rows):
  rows = list(rows)
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  fields = sorted({key for row in rows for key in row})
  with open(path, "w", encoding="utf-8", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)


def _display_command(argv):
  return " ".join(shlex.quote(str(value)) for value in argv)


def _git_commit(repo_root):
  try:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        universal_newlines=True).strip()
  except (OSError, subprocess.CalledProcessError):
    return "unknown"


def _code_fingerprint(repo_root):
  paths = (
      "scripts/run_capd_optimization.py",
      "qmap/optimization_variants.py",
      "qmap/optimization_oracle.py",
      "qmap/finals_config.py",
      "qmap/finals_data.py",
      "qmap/finals_generator.py",
      "qmap/qmap_train.py",
      "qmap/qmap_eval.py",
      "qmap/candidate_filter.py",
      "policy_learning/cache_model/model.py",
      "policy_learning/cache_model/qmap_loss.py",
  )
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def _job_code_fingerprint(repo_root, kind):
  """Fingerprint only code that can change a job's compute result."""
  common = ("qmap/finals_config.py",)
  by_kind = {
      "data": (
          "qmap/optimization_variants.py", "qmap/finals_data.py",
          "qmap/finals_generator.py", "qmap/candidate_filter.py",
          "qmap/qmap_generator.py"),
      "oracle": (
          "qmap/optimization_oracle.py", "qmap/finals_generator.py",
          "qmap/candidate_filter.py", "qmap/qmap_eval.py",
          "qmap/qmap_generator.py"),
      "baseline": (
          "qmap/qmap_eval.py", "qmap/candidate_filter.py",
          "qmap/qmap_generator.py"),
      "train": (
          "qmap/qmap_train.py", "qmap/candidate_filter.py",
          "qmap/finals_generator.py", "policy_learning/cache_model/embed.py",
          "policy_learning/cache_model/model.py",
          "policy_learning/cache_model/qmap_loss.py"),
      "valid_replay": (
          "qmap/qmap_eval.py", "qmap/candidate_filter.py",
          "qmap/qmap_generator.py", "policy_learning/cache_model/embed.py",
          "policy_learning/cache_model/model.py"),
  }
  paths = common + by_kind[kind]
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def load_profile(args):
  profile = _load_json(_absolute(args.repo_root, args.profile))
  if profile.get("schema_version") != (
      "capd_post_stage6_optimization_profile_1"):
    raise ValueError("Unsupported optimization profile schema.")
  if tuple(profile.get("phase_order", ())) != EXPECTED_PHASE_ORDER:
    raise ValueError("Optimization phase order is not frozen.")
  if profile.get("contract_id") != "CAPD-MIC-1.0":
    raise ValueError("Optimization must remain bound to CAPD-MIC-1.0.")
  if profile.get("method_contract_changed") is not False:
    raise ValueError("Optimization cannot declare a method-contract change.")
  return profile


def _validate_candidate_configs(profile):
  frozen = profile["frozen_method"]
  identifiers = set()
  rows = []
  for config in profile["candidate_configurations"]:
    config_id = config["config_id"]
    if config_id in identifiers:
      raise ValueError("Duplicate optimization config: {}".format(config_id))
    identifiers.add(config_id)
    row = {
        "config_id": config_id,
        "D": int(frozen["D"]),
        "B": int(config["B"]),
        "K": int(config["K"]),
        "L": int(config["L"]),
        "H": int(config["H"]),
        "Hc": int(frozen["Hc"]),
        "Lres": int(frozen["Lres"]),
    }
    if not (0 < row["K"] <= row["B"] <= row["D"]):
      raise ValueError("{} violates K <= B <= D.".format(config_id))
    if min(row["L"], row["H"], row["Hc"], row["Lres"]) <= 0:
      raise ValueError("{} has a non-positive setting.".format(config_id))
    rows.append(row)
  if "opt_full_control" not in identifiers:
    raise ValueError("The frozen Full control is mandatory.")
  return rows


def build_plan(args, profile=None):
  """Return the protocol declaration used by O0 and focused tests."""
  profile = profile or load_profile(args)
  configs = _validate_candidate_configs(profile)
  stage6_path = _absolute(args.repo_root, STAGE6_MANIFEST)
  bridge_path = _absolute(args.repo_root, BRIDGE_MANIFEST)
  return {
      "schema_version": "capd_post_stage6_optimization_plan_2",
      "status": "DECLARED_O1_O3_ALLOWED_O4_HOLDOUT_GATED",
      "profile_id": profile["profile_id"],
      "contract_id": profile["contract_id"],
      "scientific_role": profile["scientific_role"],
      "method_contract_changed": False,
      "official_stage6_replaced": False,
      "phase_order": list(EXPECTED_PHASE_ORDER),
      "phases": profile["phases"],
      "workloads": list(profile["workloads"]),
      "candidate_configuration_count": len(configs),
      "candidate_configurations": configs,
      "selection": profile["selection"],
      "fresh_holdout": profile["fresh_holdout"],
      "preholdout_execution_allowed": True,
      "fresh_holdout_required_before_phase": "O4_FINAL_HOLDOUT_ONCE",
      "upstream": {
          "stage6_manifest": _portable(stage6_path, args.repo_root),
          "stage6_manifest_fingerprint": (
              finals_config.fingerprint_file(stage6_path)
              if os.path.isfile(stage6_path) else None),
          "bridge_manifest": _portable(bridge_path, args.repo_root),
          "bridge_manifest_fingerprint": (
              finals_config.fingerprint_file(bridge_path)
              if os.path.isfile(bridge_path) else None),
      },
      "test_used_for_selection": False,
  }


def _check(checks, name, status, detail, path=None):
  row = {"name": name, "status": status, "detail": detail}
  if path is not None:
    row["path"] = path
  checks.append(row)


def _audit_upstream(args, checks):
  stage6_path = _absolute(args.repo_root, STAGE6_MANIFEST)
  if not os.path.isfile(stage6_path):
    _check(checks, "stage6_manifest", "FAILED",
           "Stage-6 manifest is missing.", STAGE6_MANIFEST)
  else:
    manifest = _load_json(stage6_path)
    passed = (
        manifest.get("status") == "STAGE6_VERIFIED" and
        manifest.get("required_jobs") == 105 and
        manifest.get("completed_required_jobs") == 105 and
        manifest.get("test_used_for_selection") is False)
    _check(
        checks, "stage6_manifest", "PASSED" if passed else "FAILED",
        "Stage 6 must remain verified at 105/105 with no test selection.",
        STAGE6_MANIFEST)

  bridge_path = _absolute(args.repo_root, BRIDGE_MANIFEST)
  if not os.path.isfile(bridge_path):
    _check(checks, "bridge_manifest", "FAILED",
           "Bridge manifest is missing.", BRIDGE_MANIFEST)
  else:
    manifest = _load_json(bridge_path)
    passed = (
        manifest.get("status") == "BRIDGE_DIAGNOSTIC_COMPLETED" and
        manifest.get("required_jobs") == 33 and
        manifest.get("completed_required_jobs") == 33 and
        manifest.get("official_stage6_replaced") is False and
        manifest.get("method_contract_changed") is False and
        manifest.get("test_used_for_selection") is False)
    _check(
        checks, "bridge_manifest", "PASSED" if passed else "FAILED",
        "Bridge must remain completed at 33/33 and diagnostic-only.",
        BRIDGE_MANIFEST)


def _audit_official_source(args, workload, checks):
  relative = "{}/{}.json".format(SOURCE_SPEC_ROOT, workload)
  path = _absolute(args.repo_root, relative)
  if not os.path.isfile(path):
    _check(checks, "official_source_{}".format(workload), "FAILED",
           "Official source spec is missing.", relative)
    return None
  spec = _load_json(path)
  intervals = []
  for split in ("train", "valid", "test"):
    split_spec = spec.get("splits", {}).get(split, {})
    interval = split_spec.get("source_access_interval", {})
    try:
      start = int(interval["start_inclusive"])
      end = int(interval["end_exclusive"])
    except (KeyError, TypeError, ValueError):
      _check(checks, "official_source_{}".format(workload), "FAILED",
             "Official split interval is malformed.", relative)
      return None
    intervals.append((start, end, split))
  intervals.sort()
  contiguous = intervals[0][0] == 0
  for left, right in zip(intervals, intervals[1:]):
    contiguous = contiguous and left[1] == right[0]
  collection_ids = {
      spec["splits"][split].get("collection_id")
      for split in ("train", "valid", "test")}
  passed = (
      contiguous and len(collection_ids) == 1 and
      None not in collection_ids and spec.get("workload_id") == workload)
  detail = (
      "Official collection is fully allocated over {}; no unused interval "
      "is a fresh holdout.".format(
          ", ".join("{}=[{},{})".format(name, start, end)
                    for start, end, name in intervals)))
  _check(
      checks, "official_source_{}".format(workload),
      "PASSED" if passed else "FAILED", detail, relative)
  return {
      "collection_id": next(iter(collection_ids)) if passed else None,
      "allocated_end_exclusive": intervals[-1][1],
      "source_spec_fingerprint": finals_config.fingerprint_file(path),
  }


def _audit_holdout(args, profile, workload, official_source, checks):
  relative = profile["fresh_holdout"]["metadata_paths"][workload]
  path = _absolute(args.repo_root, relative)
  if not os.path.isfile(path):
    _check(
        checks, "fresh_holdout_{}".format(workload),
        "BLOCKED_O4_ONLY",
        "A new sealed collection is required before O4, not before O1-O3.",
        relative)
    return None
  manifest = _load_json(path)
  required = profile["fresh_holdout"]["required_manifest_fields"]
  raw_relative = manifest.get("raw_trace_path")
  raw_path = _absolute(args.repo_root, raw_relative) if raw_relative else None
  problems = [
      "missing field {}".format(field)
      for field in required if field not in manifest]
  if manifest.get("workload_id") != workload:
    problems.append("workload mismatch")
  if official_source and manifest.get("collection_id") == (
      official_source["collection_id"]):
    problems.append("collection reuses official collection id")
  if manifest.get("provenance_complete") is not True:
    problems.append("provenance_complete is not true")
  if manifest.get("sealed") is not True:
    problems.append("sealed is not true")
  if manifest.get("used_for_selection") is not False:
    problems.append("used_for_selection is not false")
  if manifest.get("eligible_for_final_holdout") is not True:
    problems.append("eligible_for_final_holdout is not true")
  try:
    minimum = int(profile["fresh_holdout"]["minimum_accesses"][workload])
    if int(manifest.get("access_count", -1)) < minimum:
      problems.append("access_count below preregistered minimum")
  except (TypeError, ValueError):
    problems.append("access_count is invalid")
  if not raw_path or not os.path.isfile(raw_path):
    problems.append("raw trace is missing")
  elif manifest.get("raw_trace_fingerprint") != (
      finals_config.fingerprint_file(raw_path)):
    problems.append("raw trace fingerprint mismatch")
  _check(
      checks, "fresh_holdout_{}".format(workload),
      "PASSED" if not problems else "FAILED",
      ("Fresh holdout is sealed."
       if not problems else "; ".join(problems)), relative)
  return manifest if not problems else None


def audit_inputs(args, profile=None):
  profile = profile or load_profile(args)
  _validate_candidate_configs(profile)
  checks = []
  _audit_upstream(args, checks)
  sources = {}
  holdouts = {}
  for workload in profile["workloads"]:
    sources[workload] = _audit_official_source(args, workload, checks)
    holdouts[workload] = _audit_holdout(
        args, profile, workload, sources[workload], checks)
  failed = [item for item in checks if item["status"] == "FAILED"]
  blocked_o4 = [
      item for item in checks if item["status"] == "BLOCKED_O4_ONLY"]
  status = "FAILED" if failed else "O0_READY_FOR_O1_O3"
  return {
      "schema_version": "capd_post_stage6_stage0_audit_2",
      "status": status,
      "profile_id": profile["profile_id"],
      "checks": checks,
      "failed_checks": len(failed),
      "blocked_o4_inputs": len(blocked_o4),
      "official_sources": sources,
      "sealed_holdout_count": sum(
          1 for value in holdouts.values() if value is not None),
      "required_holdout_count": len(profile["workloads"]),
      "eligible_to_start_O1": not failed,
      "eligible_to_start_O2": not failed,
      "eligible_to_start_O3": not failed,
      "eligible_to_start_O4": not failed and not blocked_o4,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
      "test_used_for_selection": False,
  }


def _data_roots(args, workload, config_id):
  data = os.path.join(args.data_root, config_id, workload)
  return {
      "data": data,
      "config": os.path.join(data, "resolved_config.json"),
      "selector": os.path.join(data, "selector_params.json"),
      "train": os.path.join(data, "train.jsonl"),
      "valid": os.path.join(data, "valid.jsonl"),
      "validation_samples": os.path.join(
          data, "selector_validation_samples.jsonl"),
      "summary": os.path.join(data, "generator_summary.json"),
      "manifest": os.path.join(data, "variant_manifest.json"),
  }


def _checkpoint_root(args, phase, workload, config_id, seed):
  return os.path.join(
      args.checkpoint_root, phase, workload, config_id,
      "seed_{}".format(seed))


def _result_root(args, phase, workload, config_id, seed=None):
  values = [args.output_root, "raw", phase, workload, config_id]
  if seed is not None:
    values.append("seed_{}".format(seed))
  return os.path.join(*values)


def _base_config_path(args, workload):
  return os.path.join(
      args.official_artifact_root, workload, "B64", "resolved_config.json")


def _input_fingerprints(paths, repo_root):
  result = {}
  for path in dict.fromkeys(paths):
    absolute = _absolute(repo_root, path)
    result[_portable(absolute, repo_root)] = (
        finals_config.fingerprint_file(absolute)
        if os.path.isfile(absolute) else None)
  return result


def _seal_jobs(args, phase, jobs):
  code_fingerprint = _code_fingerprint(args.repo_root)
  by_id = {}
  for job in jobs:
    if (job.get("job_fingerprint") and
        job.get("job_id", "").startswith("o1:data:")):
      # O2/O3 consume the exact O1 data artifacts and manifests. Preserve
      # their original fingerprint so later phases never regenerate them
      # under a phase-local identity.
      by_id[job["job_id"]] = job
      continue
    job["command"] = _display_command(job["argv"])
    dependencies = {
        dependency: by_id[dependency]["job_fingerprint"]
        for dependency in job["dependencies"]}
    job["dependency_fingerprints"] = dependencies
    job["input_fingerprints"] = _input_fingerprints(
        job.pop("_input_paths", []), args.repo_root)
    job_code_fingerprint = _job_code_fingerprint(
        args.repo_root, job["kind"])
    job["code_fingerprint"] = job_code_fingerprint
    job["job_fingerprint"] = finals_config.fingerprint_value({
        "phase": phase,
        "job": {
            key: job.get(key) for key in (
                "job_id", "kind", "workload", "config_id", "seed", "epoch",
                "policy", "result_path", "dependencies", "command")},
        "inputs": job["input_fingerprints"],
        "dependencies": dependencies,
        "code_fingerprint": job_code_fingerprint,
    })
    by_id[job["job_id"]] = job
  return {
      "schema_version": "capd_post_stage6_{}_plan_1".format(phase),
      "phase": phase,
      "status": "PLANNED",
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": code_fingerprint,
      "required_jobs": len(jobs),
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "jobs": jobs,
  }


def build_o1_plan(args, profile=None):
  profile = profile or load_profile(args)
  configs = _validate_candidate_configs(profile)
  jobs = []
  data_ids = {}
  for workload in profile["workloads"]:
    for candidate in configs:
      config_id = candidate["config_id"]
      roots = _data_roots(args, workload, config_id)
      job_id = "o1:data:{}:{}".format(workload, config_id)
      data_ids[(workload, config_id)] = job_id
      base = _base_config_path(args, workload)
      jobs.append({
          "job_id": job_id, "kind": "data", "workload": workload,
          "config_id": config_id, "candidate": candidate,
          "result_path": roots["manifest"], "dependencies": [],
          "resource": "cpu_memory_bound",
          "argv": [
              "python3", "scripts/run_capd_optimization.py",
              "--stage", "o1", "--job-id", job_id],
          "_input_paths": [base],
      })
  for workload in profile["workloads"]:
    for candidate in configs:
      config_id = candidate["config_id"]
      roots = _data_roots(args, workload, config_id)
      result = os.path.join(
          _result_root(args, "o1", workload, config_id), "oracle.json")
      jobs.append({
          "job_id": "o1:oracle:{}:{}".format(workload, config_id),
          "kind": "oracle", "workload": workload, "config_id": config_id,
          "result_path": result,
          "dependencies": [data_ids[(workload, config_id)]],
          "resource": "cpu",
          "argv": [
              "python3", "qmap/optimization_oracle.py",
              "--config", roots["config"],
              "--selector_params", roots["selector"],
              "--json_output", result],
          "_input_paths": [],
      })
    control = _data_roots(args, workload, "opt_full_control")
    for policy in CLASSICAL_POLICIES:
      result = os.path.join(
          _result_root(
              args, "o1", workload, "opt_full_control"),
          "{}.json".format(policy))
      jobs.append({
          "job_id": "o1:baseline:{}:{}".format(workload, policy),
          "kind": "baseline", "workload": workload,
          "config_id": "opt_full_control", "policy": policy,
          "result_path": result,
          "dependencies": [data_ids[(workload, "opt_full_control")]],
          "resource": "cpu",
          "argv": [
              "python3", "qmap/qmap_eval.py",
              "--config", control["config"],
              "--evaluation_split", "valid",
              "--policy", policy, "--json_output", result],
          "_input_paths": [],
      })
  return _seal_jobs(args, "o1", jobs)


def _o1_gate_path(args):
  return os.path.join(args.output_root, "o1", "headroom_gate.json")


def _o2_shortlist_path(args):
  return os.path.join(args.output_root, "o2", "search_shortlist.json")


def _o2_proceed_configs(args, profile, workload):
  gate_path = _o1_gate_path(args)
  if not os.path.isfile(gate_path):
    raise ValueError("O1 gate is missing; summarize O1 before planning O2.")
  gate = _load_json(gate_path)
  if gate.get("status") != "O1_COMPLETED":
    raise ValueError("O1 gate is not complete.")
  allowed = set(gate["proceed_by_workload"][workload])
  allowed.add("opt_full_control")
  configs = [
      row for row in _validate_candidate_configs(profile)
      if row["config_id"] in allowed]
  if not configs:
    raise ValueError("O1 gate produced no O2 configurations.")
  return configs


def _training_and_replay_jobs(args, phase, workload, candidate, seed):
  config_id = candidate["config_id"]
  data = _data_roots(args, workload, config_id)
  checkpoint = _checkpoint_root(args, phase, workload, config_id, seed)
  train_id = "{}:train:{}:{}:{}".format(
      phase, workload, config_id, seed)
  data_dependency = "o1:data:{}:{}".format(workload, config_id)
  jobs = [{
      "job_id": train_id, "kind": "train", "workload": workload,
      "config_id": config_id, "seed": seed,
      "result_path": os.path.join(checkpoint, "checkpoint_manifest.json"),
      "dependencies": [data_dependency], "resource": "single_gpu",
      "argv": [
          "python3", "qmap/qmap_train.py",
          "--config", data["config"],
          "--selector_params", data["selector"],
          "--train_data", data["train"], "--valid_data", data["valid"],
          "--output_dir", checkpoint, "--seed", str(seed),
          "--save_every_epoch"],
      "_input_paths": [],
  }]
  epochs = int(load_profile(args)["training_epochs"])
  for epoch in range(1, epochs + 1):
    result = os.path.join(
        _result_root(args, phase, workload, config_id, seed),
        "epoch_{}.json".format(epoch))
    jobs.append({
        "job_id": "{}:replay:{}:{}:{}:{}".format(
            phase, workload, config_id, seed, epoch),
        "kind": "valid_replay", "workload": workload,
        "config_id": config_id, "seed": seed, "epoch": epoch,
        "policy": "qmap", "result_path": result,
        "dependencies": [train_id], "resource": "gpu_or_cpu_inference",
        "argv": [
            "python3", "qmap/qmap_eval.py",
            "--config", data["config"],
            "--selector_params", data["selector"],
            "--evaluation_split", "valid", "--policy", "qmap",
            "--checkpoint", os.path.join(
                checkpoint, "qmap_epoch_{}.pth".format(epoch)),
            "--json_output", result],
        "_input_paths": [],
    })
  return jobs


def build_o2_plan(args, profile=None):
  profile = profile or load_profile(args)
  o1 = build_o1_plan(args, profile)
  configs_by_workload = {
      workload: _o2_proceed_configs(args, profile, workload)
      for workload in profile["workloads"]}
  selected_pairs = {
      (workload, candidate["config_id"])
      for workload, candidates in configs_by_workload.items()
      for candidate in candidates}
  jobs = [
      copy.deepcopy(job) for job in o1["jobs"]
      if job["kind"] == "data" and
      (job["workload"], job["config_id"]) in selected_pairs]
  seed = int(profile["selection"]["screening_seed"])
  for workload in profile["workloads"]:
    for candidate in configs_by_workload[workload]:
      jobs.extend(_training_and_replay_jobs(
          args, "o2", workload, candidate, seed))
  return _seal_jobs(args, "o2", jobs)


def build_o3_plan(args, profile=None):
  profile = profile or load_profile(args)
  shortlist_path = _o2_shortlist_path(args)
  if not os.path.isfile(shortlist_path):
    raise ValueError("O2 shortlist is missing; summarize O2 first.")
  shortlist = _load_json(shortlist_path)
  if shortlist.get("status") != "O2_COMPLETED":
    raise ValueError("O2 shortlist is not complete.")
  by_id = {
      row["config_id"]: row for row in _validate_candidate_configs(profile)}
  selected_pairs = {
      (workload, config_id)
      for workload, values in shortlist["shortlist_by_workload"].items()
      for config_id in values}
  o1 = build_o1_plan(args, profile)
  jobs = [
      copy.deepcopy(job) for job in o1["jobs"]
      if job["kind"] == "data" and
      (job["workload"], job["config_id"]) in selected_pairs]
  screening = int(profile["selection"]["screening_seed"])
  confirmation = [
      int(seed) for seed in profile["selection"]["confirmation_seeds"]
      if int(seed) != screening]
  for workload in profile["workloads"]:
    for config_id in shortlist["shortlist_by_workload"][workload]:
      for seed in confirmation:
        jobs.extend(_training_and_replay_jobs(
            args, "o3", workload, by_id[config_id], seed))
  return _seal_jobs(args, "o3", jobs)


def _job_manifest_path(job):
  return "{}.job_manifest.json".format(job["result_path"])


def _job_is_complete(job):
  path = _job_manifest_path(job)
  if not os.path.isfile(path) or not os.path.isfile(job["result_path"]):
    return False
  manifest = _load_json(path)
  return (
      manifest.get("status") == "COMPLETED" and
      manifest.get("job_fingerprint") == job["job_fingerprint"] and
      os.path.getsize(job["result_path"]) > 0 and
      manifest.get("result_fingerprint") ==
      finals_config.fingerprint_file(job["result_path"]))


def _execute_data_job(args, job):
  roots = _data_roots(args, job["workload"], job["config_id"])
  os.makedirs(roots["data"], exist_ok=True)
  optimization_variants.generate_optimization_artifacts(
      _base_config_path(args, job["workload"]), job["candidate"], roots,
      args.repo_root, _git_commit(args.repo_root))


def _execute_subprocess(args, job, log_path):
  argv = list(job["argv"])
  if argv and argv[0] == "python3":
    argv[0] = sys.executable
  os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
  with open(log_path, "w", encoding="utf-8", newline="\n") as log:
    log.write("command={}\nstarted_unix={}\n".format(
        _display_command(argv), time.time()))
    log.flush()
    completed = subprocess.run(
        argv, cwd=args.repo_root, stdout=log, stderr=subprocess.STDOUT,
        check=False)
    log.write("ended_unix={}\nexit_code={}\n".format(
        time.time(), completed.returncode))
  if completed.returncode != 0:
    raise ValueError("Job {} failed with exit code {}.".format(
        job["job_id"], completed.returncode))
  if not os.path.isfile(job["result_path"]):
    raise ValueError("Job did not create {}".format(job["result_path"]))


def execute_job(args, plan, job):
  by_id = {item["job_id"]: item for item in plan["jobs"]}
  for dependency in job["dependencies"]:
    if not _job_is_complete(by_id[dependency]):
      raise ValueError("Incomplete dependency: {}".format(dependency))
  if _job_is_complete(job):
    print("[RESUME] {}".format(job["job_id"]))
    return
  manifest_path = _job_manifest_path(job)
  log_path = "{}.log".format(job["result_path"])
  manifest = {
      "job_id": job["job_id"], "job_fingerprint": job["job_fingerprint"],
      "status": "RUNNING", "started_unix": time.time(),
      "command": job["command"], "log_path": log_path,
      "atomic_manifest": True}
  _atomic_json(manifest_path, manifest)
  try:
    if job["kind"] == "data":
      _execute_data_job(args, job)
    else:
      _execute_subprocess(args, job, log_path)
    manifest.update({
        "status": "COMPLETED", "ended_unix": time.time(), "exit_code": 0,
        "result_fingerprint":
            finals_config.fingerprint_file(job["result_path"])})
  except Exception as error:
    manifest.update({
        "status": "FAILED", "ended_unix": time.time(), "exit_code": 1,
        "error": str(error), "traceback": traceback.format_exc()})
    _atomic_json(manifest_path, manifest)
    raise
  _atomic_json(manifest_path, manifest)
  print("[COMPLETED] {}".format(job["job_id"]))


def _run_jobs(args, plan):
  selected = list(plan["jobs"])
  if args.job_id:
    selected = [job for job in selected if job["job_id"] == args.job_id]
    if len(selected) != 1:
      raise ValueError("Unknown job: {}".format(args.job_id))
  elif not args.execute:
    print("[PLAN ONLY] {} jobs; pass --execute or --job-id.".format(
        len(selected)))
    return
  for job in selected:
    execute_job(args, plan, job)


def _assert_complete(plan, kinds=None):
  selected = [
      job for job in plan["jobs"]
      if kinds is None or job["kind"] in kinds]
  incomplete = [job["job_id"] for job in selected if not _job_is_complete(job)]
  if incomplete:
    raise ValueError(
        "Incomplete required jobs: {}".format(", ".join(incomplete[:10])))


def summarize_o1(args, profile=None):
  profile = profile or load_profile(args)
  plan = build_o1_plan(args, profile)
  _assert_complete(plan)
  baselines = {}
  for job in plan["jobs"]:
    if job["kind"] == "baseline":
      row = _load_json(job["result_path"])
      baselines.setdefault(job["workload"], []).append(row)
  rows = []
  proceed_by_workload = {
      workload: {"opt_full_control"} for workload in profile["workloads"]}
  by_workload = {}
  for job in plan["jobs"]:
    if job["kind"] != "oracle":
      continue
    result = _load_json(job["result_path"])
    baseline = min(
        baselines[job["workload"]],
        key=lambda row: (
            float(row["weighted_access_cost"]), row["policy"]))
    oracle_cost = float(result["weighted_access_cost"])
    baseline_cost = float(baseline["weighted_access_cost"])
    saving = baseline_cost - oracle_cost
    measurable = (
        saving > 0.0 and
        int(result["strict_label_preference_decisions"]) > 0)
    if measurable:
      proceed_by_workload[job["workload"]].add(job["config_id"])
    row = {
        "workload": job["workload"], "config_id": job["config_id"],
        "oracle_policy": result["policy"],
        "oracle_weighted_access_cost": oracle_cost,
        "best_classic_policy": baseline["policy"],
        "best_classic_weighted_access_cost": baseline_cost,
        "absolute_headroom": saving,
        "relative_headroom_percent": (
            saving * 100.0 / baseline_cost if baseline_cost else 0.0),
        "oracle_decisions": result["oracle_decisions"],
        "strict_label_preference_decisions":
            result["strict_label_preference_decisions"],
        "strict_label_preference_rate":
            result["strict_label_preference_rate"],
        "measurable_headroom": measurable,
        "test_trace_opened": False,
        "test_used_for_selection": False,
    }
    rows.append(row)
    by_workload.setdefault(job["workload"], []).append(row)
  output = os.path.join(args.output_root, "o1")
  _write_csv(os.path.join(output, "headroom_results.csv"), rows)
  summary = {
      "schema_version": "capd_post_stage6_o1_summary_1",
      "status": "O1_COMPLETED",
      "rows": rows,
      "by_workload": by_workload,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }
  _atomic_json(os.path.join(output, "headroom_summary.json"), summary)
  gate = {
      "schema_version": "capd_post_stage6_o1_gate_1",
      "status": "O1_COMPLETED",
      "proceed_by_workload": {
          workload: sorted(config_ids)
          for workload, config_ids in proceed_by_workload.items()},
      "proceed_config_ids": sorted({
          config_id for config_ids in proceed_by_workload.values()
          for config_id in config_ids}),
      "full_control_retained": True,
      "selection_rule": (
          "strictly lower valid weighted_access_cost than best LRU/Clock "
          "and at least one strict future-label preference; Full retained"),
      "test_trace_opened": False,
      "test_used_for_selection": False,
  }
  _atomic_json(_o1_gate_path(args), gate)
  return gate


def _selected_epoch_rows(args, plan, phase):
  training = {
      (job["workload"], job["config_id"], int(job["seed"])): _load_json(
          job["result_path"])
      for job in plan["jobs"] if job["kind"] == "train"}
  rows = []
  for job in plan["jobs"]:
    if job["kind"] != "valid_replay":
      continue
    result = _load_json(job["result_path"])
    key = (job["workload"], job["config_id"], int(job["seed"]))
    manifest = training[key]
    loss_by_epoch = {
        int(item["epoch"]): float(item["valid_loss"])
        for item in manifest["loss_curve"]}
    rows.append({
        "phase": phase, "workload": job["workload"],
        "config_id": job["config_id"], "seed": int(job["seed"]),
        "epoch": int(job["epoch"]),
        "weighted_access_cost": float(result["weighted_access_cost"]),
        "valid_loss": loss_by_epoch[int(job["epoch"])],
        "checkpoint": result["checkpoint"],
        "checkpoint_fingerprint": result["checkpoint_fingerprint"],
        "config_fingerprint": result["config_fingerprint"],
        "selector_fingerprint": result["selector_fingerprint"],
        "evaluation_split": result["evaluation_split"],
        "test_trace_opened": False,
        "test_used_for_selection": False,
    })
  selected = {}
  for row in rows:
    key = (row["workload"], row["config_id"], row["seed"])
    candidate_key = (
        row["weighted_access_cost"], row["valid_loss"], row["epoch"])
    if key not in selected or candidate_key < (
        selected[key]["weighted_access_cost"],
        selected[key]["valid_loss"], selected[key]["epoch"]):
      selected[key] = row
  return rows, selected


def summarize_o2(args, profile=None):
  profile = profile or load_profile(args)
  plan = build_o2_plan(args, profile)
  _assert_complete(plan)
  rows, selected = _selected_epoch_rows(args, plan, "o2")
  output = os.path.join(args.output_root, "o2")
  _write_csv(os.path.join(output, "search_results.csv"), rows)
  selected_rows = list(selected.values())
  _write_csv(
      os.path.join(output, "selected_checkpoints.csv"), selected_rows)
  shortlist_size = int(
      profile["selection"]["shortlist_size_per_workload"])
  shortlist = {}
  for workload in profile["workloads"]:
    candidates = sorted(
        [row for row in selected_rows if row["workload"] == workload],
        key=lambda row: (
            row["weighted_access_cost"], row["valid_loss"], row["epoch"],
            row["config_id"]))
    shortlist[workload] = [
        row["config_id"] for row in candidates[:shortlist_size]]
  summary = {
      "schema_version": "capd_post_stage6_o2_summary_1",
      "status": "O2_COMPLETED",
      "selected_checkpoint_rows": selected_rows,
      "shortlist_by_workload": shortlist,
      "checkpoint_selection_rule": (
          "valid weighted_access_cost, valid loss, earlier epoch"),
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
  }
  _atomic_json(os.path.join(output, "search_summary.json"), summary)
  _atomic_json(_o2_shortlist_path(args), summary)
  return summary


def _complexity_key(candidate):
  return (
      int(candidate["B"]) * int(candidate["K"]),
      int(candidate["L"]), int(candidate["H"]),
      int(candidate["B"]), int(candidate["K"]),
      candidate["config_id"])


def summarize_o3(args, profile=None):
  profile = profile or load_profile(args)
  o3_plan = build_o3_plan(args, profile)
  _assert_complete(o3_plan)
  _, o3_selected = _selected_epoch_rows(args, o3_plan, "o3")
  o2_summary = _load_json(os.path.join(
      args.output_root, "o2", "search_summary.json"))
  all_selected = list(o2_summary["selected_checkpoint_rows"])
  all_selected.extend(o3_selected.values())
  candidates = {
      row["config_id"]: row for row in _validate_candidate_configs(profile)}
  aggregate_rows = []
  locked = {}
  for workload in profile["workloads"]:
    shortlist = o2_summary["shortlist_by_workload"][workload]
    for config_id in shortlist:
      values = [
          row for row in all_selected
          if row["workload"] == workload and row["config_id"] == config_id]
      seeds = sorted(int(row["seed"]) for row in values)
      expected = sorted(
          int(seed) for seed in profile["selection"]["confirmation_seeds"])
      if seeds != expected:
        raise ValueError(
            "O3 seed coverage mismatch for {}/{}: {}.".format(
                workload, config_id, seeds))
      costs = [float(row["weighted_access_cost"]) for row in values]
      aggregate_rows.append({
          "workload": workload, "config_id": config_id,
          "seed_count": len(costs),
          "valid_cost_mean": statistics.mean(costs),
          "valid_cost_sample_stddev": statistics.stdev(costs),
          "complexity_key": json.dumps(
              _complexity_key(candidates[config_id])[:-1]),
          "test_trace_opened": False,
          "test_used_for_selection": False,
      })
    ranked = sorted(
        [row for row in aggregate_rows if row["workload"] == workload],
        key=lambda row: (
            row["valid_cost_mean"], row["valid_cost_sample_stddev"],
            _complexity_key(candidates[row["config_id"]])))
    winner = ranked[0]
    config_id = winner["config_id"]
    checkpoint_rows = sorted(
        [row for row in all_selected
         if row["workload"] == workload and row["config_id"] == config_id],
        key=lambda row: int(row["seed"]))
    locked[workload] = {
        "config": candidates[config_id],
        "valid_cost_mean": winner["valid_cost_mean"],
        "valid_cost_sample_stddev": winner["valid_cost_sample_stddev"],
        "selected_checkpoints": checkpoint_rows,
    }
  output = os.path.join(args.output_root, "o3")
  _write_csv(
      os.path.join(output, "multiseed_results.csv"), aggregate_rows)
  lock = {
      "schema_version": "capd_post_stage6_o3_locked_configurations_1",
      "status": "O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT",
      "locked_by_workload": locked,
      "selection_rule": (
          "three-seed valid cost mean, sample stddev, lower complexity, "
          "config_id"),
      "fresh_holdout_opened": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
  }
  _atomic_json(os.path.join(output, "locked_configurations.json"), lock)
  _atomic_json(os.path.join(output, "run_manifest.json"), {
      "schema_version": "capd_post_stage6_o3_run_manifest_1",
      "status": lock["status"],
      "workload_count": len(locked),
      "required_seed_count": 3,
      "fresh_holdout_required_for_O4": True,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
  })
  return lock


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="CAPD frozen-method optimization O0-O3 orchestrator.")
  parser.add_argument(
      "--stage", choices=(
          "audit-inputs", "stage0", "plan",
          "o1", "summarize-o1",
          "o2", "summarize-o2",
          "o3", "summarize-o3", "preholdout"),
      default="stage0")
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument("--profile", default=PROFILE_RELATIVE_PATH)
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--job-id", default=None)
  parser.add_argument(
      "--official-artifact-root",
      default="dataset/jsonl/finals_v3_official")
  parser.add_argument(
      "--data-root", default="dataset/jsonl/capd_post_stage6_optimization")
  parser.add_argument(
      "--checkpoint-root",
      default="outputs/checkpoints/capd_post_stage6_optimization")
  parser.add_argument(
      "--output-root",
      default="outputs/results/capd_post_stage6_optimization")
  return parser


def _resolve_args(args):
  args.repo_root = os.path.abspath(args.repo_root)
  for name in (
      "official_artifact_root", "data_root", "checkpoint_root", "output_root"):
    setattr(args, name, os.path.abspath(
        _absolute(args.repo_root, getattr(args, name))))


def _write_phase_plan(args, phase, plan):
  path = os.path.join(args.output_root, phase, "execution_plan.json")
  _atomic_json(path, plan)
  print("[PLAN] {} required_jobs={}".format(phase, plan["required_jobs"]))


def main():
  args = build_arg_parser().parse_args()
  _resolve_args(args)
  profile = load_profile(args)
  if args.stage in ("audit-inputs", "stage0", "preholdout"):
    audit = audit_inputs(args, profile)
    _atomic_json(os.path.join(
        args.output_root, "stage0_input_audit.json"), audit)
    print("[O0] status={} O1={} O4={} sealed_holdouts={}/{}".format(
        audit["status"], audit["eligible_to_start_O1"],
        audit["eligible_to_start_O4"], audit["sealed_holdout_count"],
        audit["required_holdout_count"]))
    if audit["status"] == "FAILED":
      raise SystemExit(1)
  if args.stage in ("plan", "stage0"):
    declaration = build_plan(args, profile)
    _atomic_json(os.path.join(
        args.output_root, "execution_plan.json"), declaration)
    o1 = build_o1_plan(args, profile)
    _write_phase_plan(args, "o1", o1)
    print("[DECLARED] phases={} configs={}".format(
        len(declaration["phase_order"]),
        declaration["candidate_configuration_count"]))
    if args.stage == "plan":
      for job in o1["jobs"]:
        print("{} {}".format(job["job_id"], job["command"]))
  if args.stage in ("o1", "preholdout"):
    o1 = build_o1_plan(args, profile)
    _write_phase_plan(args, "o1", o1)
    _run_jobs(args, o1)
  if args.stage in ("summarize-o1", "preholdout"):
    gate = summarize_o1(args, profile)
    print("[O1] status={} proceed_configs={}".format(
        gate["status"], len(gate["proceed_config_ids"])))
  if args.stage in ("o2", "preholdout"):
    o2 = build_o2_plan(args, profile)
    _write_phase_plan(args, "o2", o2)
    _run_jobs(args, o2)
  if args.stage in ("summarize-o2", "preholdout"):
    summary = summarize_o2(args, profile)
    print("[O2] status={} workloads={}".format(
        summary["status"], len(summary["shortlist_by_workload"])))
  if args.stage in ("o3", "preholdout"):
    o3 = build_o3_plan(args, profile)
    _write_phase_plan(args, "o3", o3)
    _run_jobs(args, o3)
  if args.stage in ("summarize-o3", "preholdout"):
    lock = summarize_o3(args, profile)
    print("[O3] status={} workloads={}".format(
        lock["status"], len(lock["locked_by_workload"])))


if __name__ == "__main__":
  main()
