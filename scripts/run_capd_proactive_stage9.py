#!/usr/bin/env python3
# coding=utf-8
"""Stage-9 Linux CPU overhead measurement and independent verification."""

from __future__ import annotations

import argparse
import array
import copy
import gc
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage5_replay
from qmap import proactive_stage7_workloads as stage7
from qmap import proactive_stage8_contract as stage8_contract
from qmap import proactive_stage8_replay
from qmap import proactive_stage9 as stage9

if sys.platform.startswith("linux"):
  import resource
else:
  resource = None


CODE_FILES = (
    "qmap/finals_config.py", "qmap/proactive_replay.py",
    "qmap/proactive_stage4.py", "qmap/proactive_stage5_contract.py",
    "qmap/proactive_stage5_policies.py", "qmap/proactive_stage5_replay.py",
    "qmap/proactive_stage7_workloads.py", "qmap/proactive_stage8_contract.py",
    "qmap/proactive_stage8_replay.py", "qmap/qmap_eval.py",
    "qmap/proactive_stage9.py", "policy_learning/cache_model/embed.py",
    "policy_learning/cache_model/model.py",
    "scripts/run_capd_proactive_stage9.py",
    "scripts/validate_capd_proactive_stage9_server.sh",
    "tests/test_capd_proactive_stage9.py")
RAW_FIELDS = (
    "sample_kind", "repetition_index", "track", "workload", "seed",
    "D", "F_low", "F_target", "b_max", "trace_sha256",
    "checkpoint_sha256", "cycle_id", "cycle_round_index", "round_id",
    "access_index", "F_before", "candidate_count", "b_t") + tuple(
        stage9.LATENCY_FIELDS)


def _utc_now() -> str:
  return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


def _load(args):
  config = stage9.load_json(args.config)
  stage9.validate_config(config)
  schema_path = os.path.join(args.project_root, config["result_schema"])
  stage9.verify_file_binding(
      schema_path, config["result_schema_sha256"], "Stage-9 result schema")
  stage0 = finals_config.load_config(args.stage0_config)
  finals_config.validate_config(stage0)
  cost = proactive_cost.load_cost_config(args.cost_config)
  return config, stage0, cost


def _run_root(args, config):
  return os.path.join(args.project_root, config["output_root"], args.run_id)


def _repository_file(project_root: str, row: Mapping[str, Any]) -> str:
  path = stage7.repository_path(project_root, row["path"])
  stage9.verify_file_binding(path, row["sha256"], row["path"])
  return path


def _resolve_recorded_file(project_root, recorded_path, expected_sha256):
  root = os.path.realpath(project_root)
  normalized = str(recorded_path).replace("\\", "/")
  candidates = [recorded_path]
  for marker in ("/outputs/", "/configs/", "/dataset/"):
    if marker in normalized:
      suffix = marker.strip("/") + "/" + normalized.split(marker, 1)[1]
      candidates.append(os.path.join(root, suffix.replace("/", os.sep)))
  for candidate in candidates:
    resolved = os.path.realpath(candidate)
    try:
      inside = os.path.commonpath((root, resolved)) == root
    except ValueError:
      inside = False
    if inside and os.path.isfile(resolved):
      stage9.verify_file_binding(
          resolved, expected_sha256, str(recorded_path))
      return resolved
  raise stage9.Stage9ContractError(
      "Cannot resolve recorded Stage-4 checkpoint: " + str(recorded_path))


def _audit_stage8_entry(config, project_root, verify_payloads=True):
  paths = {name: _repository_file(project_root, row)
           for name, row in config["stage8_authority"].items()}
  stage4_paths = {name: _repository_file(project_root, row)
                  for name, row in config["stage4_authority"].items()}
  verification = stage9.load_json(paths["verification"])
  stage9.validate_stage8_verification(verification)
  stage8_config = stage8_contract.load_json(paths["config"])
  stage8_contract.validate_config(stage8_config)
  authority = stage8_contract.audit_authority(
      stage8_config, project_root, hash_test_payloads=verify_payloads,
      require_source_files=verify_payloads,
      require_checkpoints=False)
  if verify_payloads:
    for row in authority["checkpoint_bindings"].values():
      row["resolved_path"] = _resolve_recorded_file(
          project_root, row["path"], row["sha256"])
  stage8_identity = stage9.load_json(paths["run_identity"])
  resolved_config = stage9.load_json(paths["resolved_config"])
  stage8_contract.validate_config(resolved_config)
  manifest = stage9.load_json(paths["job_manifest"])
  stage8_run_state = stage9.load_json(paths["run_state"])
  expected_checkpoints = {
      str(seed): row["sha256"]
      for seed, row in authority["checkpoint_bindings"].items()}
  expected_jobs_sha256 = stage9.fingerprint_value(manifest.get("jobs", []))
  expected_counts = {
      "job_count": 80, "standard_job_count": 48,
      "pressure_job_count": 32}
  if (stage8_identity.get("contract_id") != stage8_contract.CONTRACT_ID or
      stage8_identity.get("config_sha256") !=
      config["stage8_authority"]["config"]["sha256"] or
      stage8_identity.get("checkpoint_sha256") != expected_checkpoints or
      stage8_identity.get("job_manifest_sha256") != expected_jobs_sha256 or
      any(stage8_identity.get(key) != value
          for key, value in expected_counts.items())):
    raise stage9.Stage9ContractError(
        "Stage-8 v2 run identity/config/checkpoint binding changed.")
  if (manifest.get("schema_version") !=
      stage8_contract.MANIFEST_SCHEMA_VERSION or
      manifest.get("contract_id") != stage8_contract.CONTRACT_ID or
      manifest.get("job_manifest_sha256") != expected_jobs_sha256 or
      manifest.get("jobs") != authority["jobs"] or
      any(manifest.get(key) != value for key, value in expected_counts.items())):
    raise stage9.Stage9ContractError(
        "Stage-8 v2 root job manifest is incomplete or changed.")
  if (stage8_run_state.get("contract_id") != stage8_contract.CONTRACT_ID or
      stage8_run_state.get("status") != "stage8_sync_replay_verified" or
      stage8_run_state.get("test_used_for_parameter_selection") is not False or
      not {"formal_80_jobs", "verification"} <=
      set(stage8_run_state.get("completed", ()) or ())):
    raise stage9.Stage9ContractError(
        "Stage-8 v2 run state is not fully verified.")
  authority_sha = stage8_identity.get("authority_sha256", {})
  stage4_identity_names = {
      "final_stage4_freeze": "stage4_final_freeze",
      "formal_checkpoint_manifest": "stage4_checkpoint_manifest",
      "stage8_model_contract": "stage4_model_contract"}
  if any(authority_sha.get(stage4_identity_names[name]) != row["sha256"]
         for name, row in config["stage4_authority"].items()):
    raise stage9.Stage9ContractError("Stage-4 authority SHA chain changed.")
  capd_jobs = [copy.deepcopy(job) for job in manifest["jobs"]
               if job.get("policy") == "capd"]
  if (len(capd_jobs) != 30 or
      len({(job.get("track"), job.get("workload"), job.get("seed"))
           for job in capd_jobs}) != 30):
    raise stage9.Stage9ContractError(
        "Stage-8 v2 must expose 30 track/workload/seed CAPD jobs.")
  job_manifests = {}
  stage8_run_root = os.path.dirname(paths["job_manifest"])
  for job in capd_jobs:
    job_path = os.path.join(
        stage8_run_root, "jobs", job["job_id"], "job_manifest.json")
    if not os.path.isfile(job_path):
      raise stage9.Stage9ContractError(
          "Missing Stage-8 CAPD job manifest: " + job["job_id"])
    item = stage9.load_json(job_path)
    identity = item.get("job_identity", {})
    checkpoint = job.get("checkpoint", {})
    if (item.get("status") != "completed" or
        identity.get("plan_job") != job or
        identity.get("trace_sha256") != job.get("trace_sha256") or
        identity.get("checkpoint_sha256") != checkpoint.get("sha256") or
        checkpoint.get("seed") != job.get("seed") or
        expected_checkpoints.get(str(job.get("seed"))) !=
        checkpoint.get("sha256")):
      raise stage9.Stage9ContractError(
          "Stage-8 CAPD job manifest binding changed: " + job["job_id"])
    job_manifests[job["job_id"]] = item
  receipt = {
      "schema_version": "capd_proactive_stage9_stage8_compatibility_v2_0",
      "contract_id": stage9.CONTRACT_ID,
      "stage8_contract_id": stage8_contract.CONTRACT_ID,
      "stage8_status": verification["status"],
      "stage9_entry_gate": "satisfied",
      "formal_job_count": 80, "standard_job_count": 48,
      "pressure_job_count": 32, "capd_job_count": 30,
      "track_workload_cell_count": 10,
      "fairness": "passed", "job_results_verified": True,
      "statistics_verified": True,
      "test_used_for_parameter_selection": False,
      "stage8_authority_sha256": {
          name: row["sha256"]
          for name, row in config["stage8_authority"].items()},
      "stage4_authority_sha256": {
          name: row["sha256"]
          for name, row in config["stage4_authority"].items()},
      "stage4_sha_chain_verified": True,
      "stage8_run_state_verified": True,
      "stage8_artifacts_read_only": True}
  return {"paths": paths, "stage4_paths": stage4_paths,
          "verification": verification,
          "identity": stage8_identity, "authority": authority,
          "config": stage8_config, "resolved_config": resolved_config,
          "manifest": manifest, "capd_jobs": capd_jobs,
          "capd_job_manifests": job_manifests,
          "compatibility_receipt": receipt}


def _code_fingerprints(project_root):
  return {path: stage9.fingerprint_file(os.path.join(project_root, path))
          for path in CODE_FILES}


def _git_state(project_root):
  try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root).decode().strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=project_root).decode().strip()
    return {"commit": commit, "dirty_worktree": bool(status)}
  except (OSError, subprocess.CalledProcessError):
    return {"commit": "unknown", "dirty_worktree": None}


def _read_text(path):
  try:
    with open(path, "r", encoding="utf-8") as handle:
      return {"status": "read", "path": path,
              "value": handle.read().strip()}
  except (OSError, UnicodeError) as error:
    return {"status": "unavailable", "value": None,
            "path": path,
            "reason": "{}: {}".format(type(error).__name__, error)}


def _cpu_information(affinity):
  model = "unknown"
  physical = set()
  current_physical = None
  current_core = None
  try:
    with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
      for line in handle:
        if not line.strip():
          if current_physical is not None and current_core is not None:
            physical.add((current_physical, current_core))
          current_physical = current_core = None
          continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "model name" and model == "unknown":
          model = value
        elif key == "physical id":
          current_physical = value
        elif key == "core id":
          current_core = value
  except OSError:
    pass
  if current_physical is not None and current_core is not None:
    physical.add((current_physical, current_core))
  governors = {}
  for cpu in affinity:
    governors[str(cpu)] = _read_text(
        "/sys/devices/system/cpu/cpu{}/cpufreq/scaling_governor".format(cpu))
  turbo = _read_text("/sys/devices/system/cpu/intel_pstate/no_turbo")
  if turbo["status"] == "read":
    turbo["semantic"] = "one_means_disabled_zero_means_enabled"
    turbo["enabled"] = (turbo["value"] == "0")
  else:
    turbo = _read_text("/sys/devices/system/cpu/cpufreq/boost")
    if turbo["status"] == "read":
      turbo["semantic"] = "one_means_enabled_zero_means_disabled"
      turbo["enabled"] = (turbo["value"] == "1")
  return {
      "model": model, "logical_cpu_count": os.cpu_count(),
      "physical_core_count": len(physical) if physical else None,
      "physical_core_count_status": "read" if physical else "unavailable",
      "governor_by_requested_cpu": governors,
      "turbo_or_boost_control": turbo}


def _configure_cpu_runtime(config):
  if sys.platform != "linux":
    raise stage9.Stage9ContractError(
        "Formal Stage-9 measurement requires Linux.")
  measurement = config["measurement"]
  stage9.require_cpu_device(measurement["device"])
  expected_env = {
      "OMP_NUM_THREADS": str(measurement["omp_num_threads"]),
      "MKL_NUM_THREADS": str(measurement["mkl_num_threads"])}
  for name, expected in expected_env.items():
    if os.environ.get(name) != expected:
      raise stage9.Stage9ContractError(
          "{} must be {} before Python starts.".format(name, expected))
  requested = set(measurement["cpu_affinity"])
  if not hasattr(os, "sched_setaffinity"):
    raise stage9.Stage9ContractError("Linux sched_setaffinity is unavailable.")
  os.sched_setaffinity(0, requested)
  actual = sorted(os.sched_getaffinity(0))
  import torch
  torch.set_num_threads(int(measurement["torch_intra_op_threads"]))
  torch.set_num_interop_threads(int(measurement["torch_inter_op_threads"]))
  binding = stage9.runtime_binding(
      sorted(requested), actual, measurement["cpu_threads"],
      torch.get_num_threads(), torch.get_num_interop_threads(),
      os.environ.get("OMP_NUM_THREADS"), os.environ.get("MKL_NUM_THREADS"),
      measurement["warmup_rounds"], measurement["formal_repetitions"])
  return binding, torch


def _environment(config, binding, torch):
  return {
      "schema_version": "capd_proactive_stage9_environment_v2_0",
      "contract_id": stage9.CONTRACT_ID,
      "platform": platform.platform(), "system": platform.system(),
      "linux_kernel": platform.release(),
      "python_version": platform.python_version(),
      "python_implementation": platform.python_implementation(),
      "pytorch_version": str(torch.__version__),
      "device": "cpu", "runtime_binding": binding,
      "cpu": _cpu_information(binding["actual_affinity"]),
      "governor_read_failure_is_explicit": True,
      "turbo_read_failure_is_explicit": True,
      "captured_at": _utc_now()}


def _identity(args, config, stage8_entry, binding):
  return {
      "schema_version": "capd_proactive_stage9_run_identity_v2_0",
      "contract_id": stage9.CONTRACT_ID, "run_id": args.run_id,
      "config_sha256": stage9.fingerprint_file(args.config),
      "result_schema_sha256": stage9.fingerprint_file(os.path.join(
          args.project_root, config["result_schema"])),
      "stage0_sha256": stage9.fingerprint_file(args.stage0_config),
      "cost_config_sha256": stage9.fingerprint_file(args.cost_config),
      "stage8_authority_sha256": {
          name: row["sha256"]
          for name, row in config["stage8_authority"].items()},
      "stage4_authority_sha256": {
          name: row["sha256"]
          for name, row in config["stage4_authority"].items()},
      "checkpoint_sha256": {
          str(seed): value["sha256"] for seed, value in
          stage8_entry["authority"]["checkpoint_bindings"].items()},
      "checkpoint_selection_criterion": {
          str(seed): row["selection_criterion"] for seed, row in
          stage8_entry["authority"]["checkpoint_authority"].items()},
      "device": "cpu", "runtime_binding": binding,
      "formal_b_max": 2, "sensitivity_b_max": [1, 2, 4],
      "test_used_for_parameter_selection": False,
      "git": _git_state(args.project_root),
      "code_artifacts": _code_fingerprints(args.project_root)}


def preflight(args):
  config, _, _ = _load(args)
  run_root = stage9.prepare_new_run(config["output_root"] if os.path.isabs(
      config["output_root"]) else os.path.join(
          args.project_root, config["output_root"]), args.run_id)
  binding, torch = _configure_cpu_runtime(config)
  stage8_entry = _audit_stage8_entry(config, args.project_root)
  identity = _identity(args, config, stage8_entry, binding)
  identity["run_identity_sha256"] = stage9.fingerprint_value(identity)
  stage9.write_json_atomic(os.path.join(run_root, "run_identity.json"), identity)
  resolved = copy.deepcopy(config)
  resolved.update({"run_id": args.run_id,
                   "run_identity_sha256": identity["run_identity_sha256"],
                   "config_sha256": identity["config_sha256"]})
  stage9.write_json_atomic(os.path.join(run_root, "resolved_config.json"), resolved)
  environment = _environment(config, binding, torch)
  stage9.write_json_atomic(os.path.join(run_root, "environment.json"), environment)
  receipt = copy.deepcopy(stage8_entry["compatibility_receipt"])
  receipt["created_at"] = _utc_now()
  stage9.write_json_atomic(
      os.path.join(run_root, "stage8_compatibility_receipt.json"), receipt)
  stage9.write_json_atomic(os.path.join(run_root, "preflight.json"), {
      "schema_version": "capd_proactive_stage9_preflight_v2_0",
      "contract_id": stage9.CONTRACT_ID, "status": "passed",
      "stage8_status": stage8_entry["verification"]["status"],
      "stage8_stage9_entry_gate": receipt["stage9_entry_gate"],
      "stage8_formal_job_count":
          stage8_entry["verification"]["formal_job_count"],
      "stage8_artifacts_read_only": True,
      "test_used_for_parameter_selection": False,
      "device": "cpu", "runtime_binding": binding,
      "completed_at": _utc_now()})
  stage9.write_run_state(run_root, stage9.RUNNING, ["preflight"])
  print("[OK] Stage-9 preflight passed; Stage-8 v2 compatibility is satisfied")


def _loaded_run(args):
  config, stage0, cost = _load(args)
  run_root = _run_root(args, config)
  state_path = os.path.join(run_root, "run_state.json")
  if not os.path.isfile(state_path):
    raise stage9.Stage9ContractError("Run has not passed Stage-9 preflight.")
  state = stage9.load_json(state_path)
  if state.get("status") == stage9.NOT_VERIFIED:
    raise stage9.Stage9ContractError(
        "Failed Stage-9 run is immutable; use a new run ID.")
  binding, torch = _configure_cpu_runtime(config)
  stage8_entry = _audit_stage8_entry(config, args.project_root)
  actual = _identity(args, config, stage8_entry, binding)
  expected = stage9.load_json(os.path.join(run_root, "run_identity.json"))
  actual["run_identity_sha256"] = stage9.fingerprint_value(actual)
  if actual != expected:
    raise stage9.Stage9ContractError(
        "Stage-9 identity changed after preflight; use a new run ID.")
  return run_root, config, stage0, cost, stage8_entry, expected, torch


def _current_rss_bytes():
  try:
    with open("/proc/self/status", "r", encoding="utf-8") as handle:
      for line in handle:
        if line.startswith("VmRSS:"):
          return int(line.split()[1]) * 1024
  except OSError:
    pass
  return 0


def _peak_rss_bytes():
  if resource is None:
    raise stage9.Stage9ContractError(
        "Formal RSS measurement requires Linux resource.getrusage.")
  value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
  return int(value * 1024)


def _trace(path):
  return [{"page": row["page"], "rw": 1 if row["rw"] == "W" else 0,
           "pc": row["pc"]} for row in stage7.iter_trace(path, 12)]


def _job_trace(project_root, job):
  path = stage7.repository_path(project_root, job["trace_path"])
  stage9.verify_file_binding(path, job["trace_sha256"], job["trace_path"])
  trace = _trace(path)
  interval = job.get("evaluation_interval", {})
  expected = int(interval.get("end_exclusive", 0)) - int(
      interval.get("start_inclusive", 0))
  if len(trace) != expected:
    raise stage9.Stage9ContractError(
        "Stage-8 v2 trace length changed: " + job["job_id"])
  return trace


def _measurement_jobs(config, stage8_entry):
  jobs = [copy.deepcopy(job) for job in stage8_entry["capd_jobs"]]
  identities = {(job.get("track"), job.get("workload"), job.get("seed"))
                for job in jobs}
  if (len(jobs) != config["measurement_matrix"]["jobs_per_b_max"] or
      len(identities) != len(jobs) or
      any(job.get("track") not in ("standard", "pressure") or
          job.get("seed") not in stage9.CAPD_SEEDS or
          job.get("policy") != "capd" for job in jobs)):
    raise stage9.Stage9ContractError(
        "Stage-9 measurement matrix is incomplete.")
  return jobs


def _checkpoint(stage8_entry, job):
  frozen = stage8_entry["authority"]["checkpoint_bindings"][int(job["seed"])]
  job_checkpoint = job.get("checkpoint", {})
  if (frozen["selection_criterion"] != "minimum_valid_loss_only" or
      job_checkpoint.get("selection_criterion") !=
      "minimum_valid_loss_only" or
      int(frozen["seed"]) != int(job["seed"]) or
      int(job_checkpoint.get("seed", -1)) != int(job["seed"]) or
      frozen["sha256"] != job_checkpoint.get("sha256")):
    raise stage9.Stage9ContractError("Checkpoint selection rule changed.")
  return {"seed": int(job["seed"]),
          "path": frozen.get("resolved_path", frozen["path"]),
          "sha256": frozen["sha256"],
          "selection_criterion": frozen["selection_criterion"]}


def _replay_parameters(job, b_max):
  return proactive_replay.ReplayParameters(
      policy_name="capd", dram_capacity_pages=int(job["dram_pages"]),
      F_low=int(job["F_low"]), F_target=int(job["F_target"]),
      b_max=int(b_max), candidate_size_K=int(job["K"]),
      history_window_size=int(job["history_H"]), early_reuse_window=64)


def _job_context(job, b_max):
  return {
      "track": job["track"], "workload": job["workload"],
      "seed": int(job["seed"]), "D": int(job["dram_pages"]),
      "F_low": int(job["F_low"]), "F_target": int(job["F_target"]),
      "b_max": int(b_max), "trace_sha256": job["trace_sha256"],
      "checkpoint_sha256": job["checkpoint"]["sha256"]}


def _expected_job_map(jobs):
  expected = {(job["track"], job["workload"], int(job["seed"])): job
              for job in jobs}
  if len(expected) != len(jobs):
    raise stage9.Stage9ContractError(
        "Stage-9 job identity collision in audited Stage-8 manifest.")
  return expected


def _audit_record_identities(rows, jobs, allowed_b_max):
  expected = _expected_job_map(jobs)
  allowed = {int(value) for value in allowed_b_max}
  for row in rows:
    identity = (row.get("track"), row.get("workload"), row.get("seed"))
    job = expected.get(identity)
    if job is None or row.get("b_max") not in allowed:
      raise stage9.Stage9ContractError(
          "Stage-9 record has an unknown track/workload/seed/b_max identity.")
    context = _job_context(job, int(row["b_max"]))
    if any(row.get(key) != value for key, value in context.items()):
      raise stage9.Stage9ContractError(
          "Stage-9 record differs from its Stage-8 v2 plan_job: {}.".format(
              identity))


def _capacity_workload_rows(jobs):
  by_workload = {}
  for job in jobs:
    workload = job["workload"]
    item = by_workload.setdefault(workload, {
        "workload": workload, "dram_pages": int(job["dram_pages"]),
        "tracks": set()})
    if item["dram_pages"] != int(job["dram_pages"]):
      raise stage9.Stage9ContractError(
          "Stage-8 tracks disagree on frozen D for " + workload)
    item["tracks"].add(job["track"])
  return [dict(row, tracks=sorted(row["tracks"]))
          for _, row in sorted(by_workload.items())]


def _build_profiled_replay(stage0, job, checkpoint, b_max, config):
  policy_stage0 = proactive_stage5_replay._stage0_for_policy(
      stage0, "capd", checkpoint=checkpoint)
  parameters = _replay_parameters(job, b_max)
  ranker = stage9.ProfiledCAPDRanker(
      checkpoint_path=checkpoint["path"],
      checkpoint_sha256=checkpoint["sha256"], seed=checkpoint["seed"],
      device="cpu", history_H=int(job["history_H"]),
      candidate_K=int(job["K"]), lookahead=256,
      weights=(1.0, 1.0, 2.0))
  replay = stage9.InstrumentedProactiveReplay(
      policy_stage0, parameters, ranker,
      warmup_rounds=config["measurement"]["warmup_rounds"],
      formal_repetitions=config["measurement"]["formal_repetitions"],
      invariant_mode="boundary", exclude_current_entering_page=True,
      sample_context=_job_context(job, b_max))
  return replay, ranker


class _LatencyAccumulator(object):
  def __init__(self):
    self.values = {field: array.array("Q") for field in stage9.LATENCY_FIELDS}
    self.warmup = 0
    self.measured = 0
    self.pages = 0
    self.b_t = {}
    self.amortized = array.array("d")
    self.sample_counts_by_cell = {}

  def add(self, sample):
    cell = (sample["track"], sample["workload"], int(sample["seed"]),
            sample["sample_kind"])
    self.sample_counts_by_cell[cell] = (
        self.sample_counts_by_cell.get(cell, 0) + 1)
    if sample["sample_kind"] == "warmup":
      self.warmup += 1
      return
    self.measured += 1
    for field in stage9.LATENCY_FIELDS:
      self.values[field].append(int(sample[field]))
    b_t = int(sample["b_t"])
    self.pages += b_t
    self.b_t[str(b_t)] = self.b_t.get(str(b_t), 0) + 1
    if b_t:
      self.amortized.append(sample["total_round_latency_ns"] / float(b_t))

  def latency(self):
    return {
        "schema_version": "capd_proactive_stage9_latency_summary_v2_0",
        "clock": "time.perf_counter_ns", "stage_timings": "exclusive",
        "total_boundary": "watermark_check_start_through_top_b_result",
        "excluded_from_total": [
            "page_migration", "replay_state_update", "invariant_checks",
            "quality_metrics", "artifact_serialization"],
        "measured_sample_count": self.measured,
        "warmup_sample_count": self.warmup,
        "stages": {field: stage9.distribution(values)
                   for field, values in self.values.items()}}

  def throughput(self):
    total = sum(self.values["total_round_latency_ns"])
    return {
        "schema_version": "capd_proactive_stage9_throughput_v2_0",
        "measured_rounds": self.measured,
        "measured_demoted_pages": self.pages,
        "measured_total_round_latency_ns": total,
        "rounds_per_second": self.measured * 1e9 / total if total else None,
        "demoted_pages_per_second": self.pages * 1e9 / total if total else None,
        "b_t_distribution": self.b_t,
        "b_t_zero_count": self.b_t.get("0", 0),
        "amortized_sample_count": len(self.amortized),
        "amortized_latency_ns_per_page": stage9.distribution(self.amortized),
        "b_t_zero_policy": "counted_separately_excluded_from_division"}


def _quality_row(trace, raw, job, b_max, cost_config):
  summary = raw["summary"]
  weighted = proactive_cost.compute_weighted_cost(
      summary, cost_config.profiles["default"])
  early = proactive_stage8_replay.early_reuse_metrics(trace, raw["events"])
  return dict(_job_context(job, b_max), **{
      "weighted_cost": weighted.weighted_cost,
      "weighted_cost_per_access": weighted.weighted_cost / float(len(trace)),
      "early_reuse_rate_64": early["windows"]["64"]["rate"],
      "early_reuse_rate_256": early["windows"]["256"]["rate"],
      "early_reuse_rate_1024": early["windows"]["1024"]["rate"],
      "proactive_demotions": int(summary["proactive_demotions"]),
      "number_of_proactive_rounds": int(summary["number_of_proactive_rounds"]),
      "test_used_for_selection": False,
      "sensitivity_purpose": "analysis_only_not_selection"})


def _quality_group(rows):
  active = [row for row in rows if row["number_of_proactive_rounds"] > 0]
  return {
      "cell_count": len(rows),
      "active_round_cell_count": len(active),
      "zero_round_cell_count": len(rows) - len(active),
      "weighted_cost_mean": statistics_mean(
          row["weighted_cost"] for row in rows),
      "early_reuse_rate_64_mean": statistics_mean(
          row["early_reuse_rate_64"] for row in rows),
      "early_reuse_rate_256_mean": statistics_mean(
          row["early_reuse_rate_256"] for row in rows),
      "early_reuse_rate_1024_mean": statistics_mean(
          row["early_reuse_rate_1024"] for row in rows)}


def _aggregate_quality(rows):
  groups = {}
  for b_max in stage9.SENSITIVITY_BMAX:
    selected = [row for row in rows if row["b_max"] == b_max]
    group = _quality_group(selected)
    group["by_track"] = {
        track: _quality_group(
            [row for row in selected if row["track"] == track])
        for track in ("standard", "pressure")}
    track_workloads = sorted({(row["track"], row["workload"])
                              for row in selected})
    group["by_track_workload"] = {
        "{}|{}".format(track, workload): _quality_group([
            row for row in selected
            if row["track"] == track and row["workload"] == workload])
        for track, workload in track_workloads}
    groups[str(b_max)] = group
  return {"schema_version": "capd_proactive_stage9_quality_v2_0",
          "formal_b_max": 2, "purpose": "analysis_only_not_selection",
          "test_used_for_parameter_selection": False,
          "rows": rows, "by_b_max": groups}


def statistics_mean(values):
  values = list(values)
  return sum(values) / float(len(values)) if values else None


def _audit_measurement_completeness(
    accumulators, quality_rows, config, expected_jobs=None):
  matrix = config["measurement_matrix"]
  if expected_jobs is not None:
    _audit_record_identities(
        quality_rows, expected_jobs, stage9.SENSITIVITY_BMAX)
  warmup_rounds = config["measurement"]["warmup_rounds"]
  repetitions = config["measurement"]["formal_repetitions"]
  expected_active = matrix["expected_active_round_jobs_per_b_max"]
  expected_zero = matrix["expected_zero_round_jobs_per_b_max"]
  expected_zero_cells = {
      (parts[0], parts[1], int(parts[2]))
      for parts in (key.split("|")
                    for key in matrix["expected_zero_round_job_keys"])}
  for b_max in stage9.SENSITIVITY_BMAX:
    rows = [row for row in quality_rows if row["b_max"] == b_max]
    active = [row for row in rows
              if row["number_of_proactive_rounds"] > 0]
    zero = [row for row in rows
            if row["number_of_proactive_rounds"] == 0]
    if (len(rows) != expected_active + expected_zero or
        len(active) != expected_active or len(zero) != expected_zero):
      raise stage9.Stage9ContractError(
          "b_max={} active/zero-round applicability changed: {}/{}.".format(
              b_max, len(active), len(zero)))
    all_cells = {(row["track"], row["workload"], int(row["seed"]))
                 for row in rows}
    active_cells = {(row["track"], row["workload"], int(row["seed"]))
                    for row in active}
    zero_cells = {(row["track"], row["workload"], int(row["seed"]))
                  for row in zero}
    track_workloads = {(row["track"], row["workload"]) for row in rows}
    if (len(all_cells) != matrix["jobs_per_b_max"] or
        len(track_workloads) != matrix["track_workload_cell_count"] or
        zero_cells != expected_zero_cells or
        active_cells != all_cells - expected_zero_cells):
      raise stage9.Stage9ContractError(
          "b_max={} active/zero workload identities changed.".format(b_max))
    insufficient = [row for row in active
                    if row["number_of_proactive_rounds"] <= warmup_rounds]
    if insufficient:
      raise stage9.Stage9ContractError(
          "Active cells do not exceed frozen warmup rounds: {}".format(
              [row["workload"] for row in insufficient]))
    expected_warmup = len(active) * warmup_rounds
    expected_measured = sum(
        (row["number_of_proactive_rounds"] - warmup_rounds) * repetitions
        for row in active)
    observed = accumulators[str(b_max)]
    for row in active:
      cell = (row["track"], row["workload"], int(row["seed"]))
      if (observed.sample_counts_by_cell.get(cell + ("warmup",), 0) !=
          warmup_rounds or
          observed.sample_counts_by_cell.get(cell + ("measured",), 0) !=
          (row["number_of_proactive_rounds"] - warmup_rounds) * repetitions):
        raise stage9.Stage9ContractError(
            "b_max={} raw sample count changed for workload/seed {}.".format(
                b_max, cell))
    unexpected_cells = {
        cell[:3] for cell in observed.sample_counts_by_cell
        if cell[:3] not in {
            (row["track"], row["workload"], int(row["seed"]))
            for row in active}}
    if unexpected_cells:
      raise stage9.Stage9ContractError(
          "b_max={} raw samples include inapplicable cells: {}.".format(
              b_max, sorted(unexpected_cells)))
    if (observed.warmup != expected_warmup or
        observed.measured != expected_measured or
        observed.measured <= 0 or observed.pages <= 0):
      raise stage9.Stage9ContractError(
          "b_max={} latency sample completeness failed: warmup {}/{}, "
          "measured {}/{}, pages {}.".format(
              b_max, observed.warmup, expected_warmup,
              observed.measured, expected_measured, observed.pages))


def _audit_perf_scope_counts(scope, config, expected_jobs=None):
  matrix = config["measurement_matrix"]
  expected_zero_cells = {
      (parts[0], parts[1], int(parts[2]))
      for parts in (key.split("|")
                    for key in matrix["expected_zero_round_job_keys"])}
  measured_cells = {
      (row.get("track"), row.get("workload"), row.get("seed"))
      for row in scope.get("measured_cells", [])}
  zero_cells = {
      (row.get("track"), row.get("workload"), row.get("seed"))
      for row in scope.get("zero_round_cells", [])}
  all_expected = ({(job["track"], job["workload"], int(job["seed"]))
                   for job in expected_jobs} if expected_jobs is not None else
                  measured_cells | zero_cells)
  if expected_jobs is not None:
    _audit_record_identities(
        list(scope.get("measured_cells", [])) +
        list(scope.get("zero_round_cells", [])),
        expected_jobs, (config["sensitivity"]["formal_b_max"],))
  expected_active_cells = all_expected - expected_zero_cells
  expected_snapshots = config["perf"]["expected_snapshot_count"]
  repetitions = config["perf"]["repetitions_per_snapshot"]
  if (scope.get("snapshot_count") != expected_snapshots or
      scope.get("zero_round_job_count") !=
      matrix["expected_zero_round_jobs_per_b_max"] or
      len(scope.get("measured_job_ids", [])) != expected_snapshots or
      len(set(scope.get("measured_job_ids", []))) != expected_snapshots or
      len(scope.get("zero_round_job_ids", [])) != len(expected_zero_cells) or
      len(set(scope.get("zero_round_job_ids", []))) != len(expected_zero_cells) or
      measured_cells != expected_active_cells or
      zero_cells != expected_zero_cells or
      len(all_expected) != matrix["jobs_per_b_max"] or
      scope.get("measured_rounds") != expected_snapshots * repetitions or
      scope.get("measured_demoted_pages", 0) <= 0):
    raise stage9.Stage9ContractError(
        "Perf snapshot/job/cell scope completeness failed.")


def _audit_instrumentation(raw, cpu_reference, job, b_max):
  observed_rounds = [row["selected_pages"] for row in raw["rounds"]]
  expected_rounds = [row["selected_pages"]
                     for row in cpu_reference["rounds"]]
  if (stage9.fingerprint_value(observed_rounds) !=
      stage9.fingerprint_value(expected_rounds) or
      stage9.fingerprint_value(raw["state"]) !=
      stage9.fingerprint_value(cpu_reference["final_state"])):
    raise stage9.Stage9ContractError(
        "Timing instrumentation changed formal b_max=2 Top-b/state trajectory.")
  return dict(_job_context(job, b_max), **{
          "job_id": cpu_reference["job_id"],
          "reference_device": "cpu",
          "comparison": "uninstrumented_cpu_vs_instrumented_cpu",
          "top_b_sha256": stage9.fingerprint_value(observed_rounds),
          "final_state_sha256": stage9.fingerprint_value(raw["state"]),
          "status": "identical"})


def _merge_model_memory_observation(model_memory_by_seed, seed, observation):
  key = str(seed)
  existing = model_memory_by_seed.get(key)
  if existing is None:
    model_memory_by_seed[key] = copy.deepcopy(observation)
    return
  if (existing["model_parameters"] != observation["model_parameters"] or
      existing["model_buffers"] != observation["model_buffers"]):
    raise stage9.Stage9ContractError(
        "Model parameter/buffer memory changed within a frozen seed.")
  runtime = existing.setdefault("runtime_tensors", {})
  for name, value in observation.get("runtime_tensors", {}).items():
    if name.endswith("_bytes"):
      runtime[name] = max(int(runtime.get(name, 0)), int(value))
    else:
      runtime.setdefault(name, value)


def measure(args):
  run_root, config, stage0, cost, entry, identity, _ = _loaded_run(args)
  raw_path = os.path.join(run_root, "raw_latency_samples.csv")
  if os.path.exists(raw_path):
    raise stage9.Stage9ContractError(
        "Measurement artifact already exists; use a new run ID.")
  baseline_rss = _current_rss_bytes()
  if baseline_rss <= 0:
    raise stage9.Stage9ContractError(
        "Could not read Linux process baseline RSS from /proc/self/status.")
  accumulators = {str(b): _LatencyAccumulator()
                  for b in stage9.SENSITIVITY_BMAX}
  quality_rows = []
  instrumentation_audit = []
  model_memory_by_seed = {}
  max_runtime = {}
  max_history_python = 0
  max_candidate_python = 0
  authority = entry["authority"]
  jobs = _measurement_jobs(config, entry)
  jobs_by_cell = {}
  for job in jobs:
    jobs_by_cell.setdefault((job["track"], job["workload"]), []).append(job)
  directory = os.path.dirname(raw_path)
  fd, temporary = tempfile.mkstemp(
      prefix=".stage9-latency-", suffix=".tmp", dir=directory)
  try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
      import csv
      writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
      writer.writeheader()
      for (track, workload), cell_jobs in jobs_by_cell.items():
        trace = _job_trace(args.project_root, cell_jobs[0])
        lock_row = (authority["standard_rows"][workload]
                    if track == "standard" else
                    authority["pressure_rows"][workload])
        for job in cell_jobs:
          checkpoint = _checkpoint(entry, job)
          for b_max in stage9.SENSITIVITY_BMAX:
            replay, ranker = _build_profiled_replay(
                stage0, job, checkpoint, b_max, config)
            replay.register_backing_pages(item["page"] for item in trace)
            for access in trace:
              replay.process_access(access)
              replay.access_logs[:] = []
            raw = replay.result()
            replay.validate_log_accounting()
            for sample in replay.stage9_latency_samples:
              writer.writerow({key: sample.get(key) for key in RAW_FIELDS})
              accumulators[str(b_max)].add(sample)
            quality_rows.append(_quality_row(trace, raw, job, b_max, cost))
            if b_max == config["sensitivity"]["formal_b_max"]:
              cpu_reference = proactive_stage8_replay.run_formal_test_replay(
                  stage0, cost, trace, job, lock_row,
                  checkpoint=checkpoint, device="cpu", measure_latency=False,
                  retain_access_logs=False, invariant_mode="boundary")
              instrumentation_audit.append(
                  _audit_instrumentation(raw, cpu_reference, job, b_max))
              del cpu_reference
            memory = stage9.model_memory_from_ranker(ranker)
            _merge_model_memory_observation(
                model_memory_by_seed, job["seed"], memory)
            for key, value in memory["runtime_tensors"].items():
              if key.endswith("_bytes"):
                max_runtime[key] = max(max_runtime.get(key, 0), int(value))
            max_history_python = max(
                max_history_python, stage9.deep_sizeof(list(replay.history_window)))
            candidate_snapshot = (raw["rounds"][-1]["candidate_features"]
                                  if raw["rounds"] else [])
            max_candidate_python = max(
                max_candidate_python, stage9.deep_sizeof(candidate_snapshot))
            del raw, replay, ranker
            gc.collect()
          print("[OK] Stage-9 latency/quality {}|{} seed {}".format(
              track, workload, job["seed"]), flush=True)
        del trace
        gc.collect()
      handle.flush()
      os.fsync(handle.fileno())
    _audit_measurement_completeness(
        accumulators, quality_rows, config, expected_jobs=jobs)
    os.replace(temporary, raw_path)
  except Exception:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise

  latency_summary = {
      "schema_version": "capd_proactive_stage9_latency_suite_v2_0",
      "formal_b_max": 2, "sensitivity_purpose": "analysis_only_not_selection",
      "applicability": config["measurement_matrix"]["latency_applicability"],
      "by_b_max": {key: value.latency()
                   for key, value in accumulators.items()}}
  throughput_summary = {
      "schema_version": "capd_proactive_stage9_throughput_suite_v2_0",
      "formal_b_max": 2, "sensitivity_purpose": "analysis_only_not_selection",
      "applicability": config["measurement_matrix"]["latency_applicability"],
      "by_b_max": {key: value.throughput()
                   for key, value in accumulators.items()}}
  stage9.write_json_atomic(
      os.path.join(run_root, "latency_summary.json"), latency_summary)
  stage9.write_json_atomic(
      os.path.join(run_root, "throughput_summary.json"), throughput_summary)
  stage9.write_json_atomic(
      os.path.join(run_root, "quality_summary.json"),
      _aggregate_quality(quality_rows))
  stage9.write_json_atomic(
      os.path.join(run_root, "instrumentation_audit.json"), {
          "schema_version": "capd_proactive_stage9_instrumentation_audit_v2_0",
          "formal_b_max": 2, "job_count": len(instrumentation_audit),
          "status": "identical", "jobs": instrumentation_audit})

  if not model_memory_by_seed:
    raise stage9.Stage9ContractError("No model memory observation was produced.")
  max_model = max(model_memory_by_seed.values(), key=lambda row:
                  row["model_parameters"]["all_model_parameters_bytes"] +
                  row["model_buffers"]["bytes"])
  parameter_bytes = max_model["model_parameters"]["all_model_parameters_bytes"]
  buffer_bytes = max_model["model_buffers"]["bytes"]
  history_logical = 20 * 24
  runtime_for_capacity = sum(max_runtime.get(key, 0) for key in (
      "feature_activation_bytes", "transformer_activation_bytes",
      "score_tensor_bytes", "candidate_tensor_bytes"))
  management_fixed = (parameter_bytes + buffer_bytes + history_logical +
                      runtime_for_capacity)
  peak_rss = max(_peak_rss_bytes(), _current_rss_bytes(), baseline_rss)
  memory_breakdown = {
      "schema_version": "capd_proactive_stage9_memory_v2_0",
      "model_by_seed": model_memory_by_seed,
      "model_parameters": max_model["model_parameters"],
      "model_buffers": max_model["model_buffers"],
      "page_embedding": {
          "bytes": max_model["model_parameters"][
              "page_embedding_parameter_bytes"],
          "method": "exact_tensor_numel_times_element_size"},
      "pc_embedding": {
          "bytes": max_model["model_parameters"][
              "pc_embedding_parameter_bytes"],
          "method": "exact_tensor_numel_times_element_size"},
      "transformer_parameters": {
          "bytes": max_model["model_parameters"][
              "transformer_parameter_bytes"],
          "method": "exact_tensor_numel_times_element_size"},
      "transformer_activation": {
          "bytes": max_runtime.get("transformer_activation_bytes", 0),
          "method": "materialized_output_tensor_lower_bound",
          "limitation": "Internal ATen workspaces are covered only by RSS peak."},
      "history_buffer": {
          "logical_packed_bytes": history_logical,
          "python_recursive_estimate_bytes": max_history_python,
          "python_estimate_limit": "sys.getsizeof recursion is not native RSS"},
      "candidate_tensor": {
          "bytes": max_runtime.get("candidate_tensor_bytes", 0),
          "method": "exact_materialized_tensor_bytes",
          "python_candidate_state_estimate_bytes": max_candidate_python},
      "metadata_bytes_per_page": config["memory"]["metadata_bytes_per_page"],
      "metadata_method": "analytical_packed_target_layout_not_python_dict_size",
      "management_fixed_bytes": management_fixed,
      "management_fixed_mib": management_fixed / 1048576.0,
      "runtime_tensor_maxima": max_runtime,
      "rss": stage9.rss_breakdown(baseline_rss, peak_rss),
      "tracemalloc_complete_for_torch_native": False}
  stage9.write_json_atomic(
      os.path.join(run_root, "memory_breakdown.json"), memory_breakdown)
  capacity_rows = stage9.capacity_overhead_rows(
      management_fixed, config["memory"]["metadata_bytes_per_page"],
      _capacity_workload_rows(jobs), 4096)
  stage9.write_csv_atomic(
      os.path.join(run_root, "capacity_overhead.csv"), capacity_rows)
  _write_report(run_root, latency_summary, throughput_summary,
                _aggregate_quality(quality_rows), memory_breakdown)
  state = stage9.load_json(os.path.join(run_root, "run_state.json"))
  completed = list(state.get("completed", []))
  completed.extend(item for item in ("latency", "quality", "memory",
                                      "capacity_accounting",
                                      "instrumentation_audit")
                   if item not in completed)
  stage9.write_run_state(run_root, stage9.RUNNING, completed)
  print("[OK] Stage-9 CPU latency, sensitivity quality, and memory measured")


def _write_report(run_root, latency, throughput, quality, memory):
  lines = [
      "# CAPD Stage9 CPU 推理与内存开销报告",
      "",
      "> 状态：服务器测量已生成，只有 verification.json 通过后才是 Stage9 完成。",
      "",
      "计时使用 `time.perf_counter_ns()`。六个子阶段均为 exclusive；总延迟从水位检查开始，到 Top-b 结果产生结束，不含迁移、Replay 状态更新、质量统计和文件写入。总延迟与子项之差保存为未归属框架开销。",
      "",
      "## 延迟与吞吐",
      "",
      "| b_max | Mean round (ns) | P50 | P95 | P99 | Mean amortized (ns/page) | rounds/s | pages/s |",
      "|---:|---:|---:|---:|---:|---:|---:|---:|",
  ]
  for b_max in (1, 2, 4):
    lat = latency["by_b_max"][str(b_max)]["stages"][
        "total_round_latency_ns"]
    tp = throughput["by_b_max"][str(b_max)]
    amort = tp["amortized_latency_ns_per_page"]["mean"]
    lines.append("| {b} | {mean} | {p50} | {p95} | {p99} | {amort} | {rps} | {pps} |".format(
        b=b_max, mean=lat["mean"], p50=lat["p50"], p95=lat["p95"],
        p99=lat["p99"], amort=amort, rps=tp["rounds_per_second"],
        pps=tp["demoted_pages_per_second"]))
  lines.extend([
      "", "b_t=0 单独计数并从单页摊销除法中排除。b_max=1/2/4 仅为预声明分析项；正式配置始终为 2。",
      "", "## 质量护栏", "",
      "| b_max | cells | active | zero-round | Mean weighted cost | Early-Reuse@64 | Early-Reuse@256 | Early-Reuse@1024 |",
      "|---:|---:|---:|---:|---:|---:|---:|---:|"])
  for b_max in (1, 2, 4):
    row = quality["by_b_max"][str(b_max)]
    lines.append("| {b} | {cell_count} | {active_round_cell_count} | {zero_round_cell_count} | {weighted_cost_mean} | {early_reuse_rate_64_mean} | {early_reuse_rate_256_mean} | {early_reuse_rate_1024_mean} |".format(
        b=b_max, **row))
  lines.extend([
      "", "## 内存口径", "",
      "模型参数和输入张量按 numel×element_size 精确计算；Transformer activation 是已物化输出张量下界。Python 容器采用递归 sys.getsizeof 估算，不能解释为完整 native 内存；PyTorch native allocator 由 OS RSS peak 覆盖，未使用 tracemalloc 冒充完整值。",
      "", "- 固定管理内存：{} bytes ({:.6f} MiB)".format(
          memory["management_fixed_bytes"], memory["management_fixed_mib"]),
      "- 每页 metadata：{} bytes/page".format(
          memory["metadata_bytes_per_page"]),
      "- 进程 baseline RSS：{} bytes".format(
          memory["rss"]["process_baseline_rss_bytes"]),
      "- 总 peak RSS：{} bytes".format(memory["rss"]["total_peak_rss_bytes"]),
      "- Stage9 增量 peak RSS：{} bytes".format(
          memory["rss"]["stage9_incremental_peak_rss_bytes"]),
      "", "## 边界", "",
      "capacity_overhead.csv 已按 ceil(management_memory_bytes/4096) 给出 6 个唯一 workload 冻结 D 的有效 DRAM 页数；tracks 列仅说明适用轨道，不重复计费。公平容量 Replay 复算本阶段标记为 deferred，且不会覆盖 Stage8 正式结果。perf cycles 见 perf/perf_parsed.json；本报告不声称内核集成、真实迁移耗时、前台端到端延迟或异步结果。",
      ""])
  stage9.write_text_atomic(
      os.path.join(run_root, "artifacts", "report_cn.md"), "\n".join(lines))


class _SnapshotReady(Exception):
  def __init__(self, decision, cycle_id, cycle_round_index, F_before):
    super().__init__("Stage-9 perf snapshot ready")
    self.decision = decision
    self.cycle_id = cycle_id
    self.cycle_round_index = cycle_round_index
    self.F_before = F_before


class _SnapshotReplay(stage9.InstrumentedProactiveReplay):
  def _measure_decision(self, cycle_id, cycle_round_index, F_before,
                        sample_kind, repetition_index):
    decision = super()._measure_decision(
        cycle_id, cycle_round_index, F_before, sample_kind, repetition_index)
    if sample_kind == "measured":
      raise _SnapshotReady(decision, cycle_id, cycle_round_index, F_before)
    return decision


class _PerfControl(object):
  def __init__(self, control_path, ack_path):
    if not control_path or not ack_path:
      raise stage9.Stage9ContractError(
          "Formal perf workload requires perf FIFO control and ack paths.")
    self.control = open(control_path, "w", encoding="ascii", buffering=1)
    self.ack = open(ack_path, "r", encoding="ascii", buffering=1)

  def command(self, value):
    self.control.write(value + "\n")
    response = self.ack.readline().strip()
    if response != "ack":
      raise stage9.Stage9ContractError(
          "perf control did not acknowledge {}: {!r}".format(value, response))

  def close(self):
    self.control.close()
    self.ack.close()


def perf_workload(args):
  run_root, config, stage0, _, entry, _, _ = _loaded_run(args)
  authority = entry["authority"]
  control = _PerfControl(args.perf_control_fifo, args.perf_ack_fifo)
  repetitions = int(config["perf"]["repetitions_per_snapshot"])
  measured_rounds = measured_pages = snapshot_count = 0
  zero_round_jobs = []
  measured_job_ids = []
  zero_round_cells = []
  measured_cells = []
  jobs = _measurement_jobs(config, entry)
  jobs_by_cell = {}
  for job in jobs:
    jobs_by_cell.setdefault((job["track"], job["workload"]), []).append(job)
  try:
    for (track, workload), cell_jobs in jobs_by_cell.items():
      trace = _job_trace(args.project_root, cell_jobs[0])
      for job in cell_jobs:
        checkpoint = _checkpoint(entry, job)
        replay, ranker = _build_profiled_replay(
            stage0, job, checkpoint,
            config["sensitivity"]["formal_b_max"], config)
        replay.__class__ = _SnapshotReplay
        replay.register_backing_pages(item["page"] for item in trace)
        snapshot = None
        try:
          for access in trace:
            replay.process_access(access)
        except _SnapshotReady as ready:
          snapshot = ready
        if snapshot is None:
          logical_rounds = replay._stage9_logical_rounds
          if logical_rounds == 0:
            zero_round_jobs.append(job["job_id"])
            zero_round_cells.append(_job_context(
                job, config["sensitivity"]["formal_b_max"]))
            del replay, ranker
            gc.collect()
            continue
          raise stage9.Stage9ContractError(
              "Perf cell has {} rounds, insufficient for {} warmup rounds: {}".format(
                  logical_rounds, config["measurement"]["warmup_rounds"],
                  job["job_id"]))
        expected = snapshot.decision[:4]
        control.command("enable")
        try:
          for repetition in range(repetitions):
            observed = replay.decision_without_timing(
                snapshot.cycle_id, snapshot.cycle_round_index,
                snapshot.F_before)
            if observed != expected:
              raise stage9.Stage9ContractError(
                  "Perf repetition changed candidate/ranking/Top-b.")
            measured_rounds += 1
            measured_pages += len(observed[3])
        finally:
          control.command("disable")
        snapshot_count += 1
        measured_job_ids.append(job["job_id"])
        measured_cells.append(_job_context(
            job, config["sensitivity"]["formal_b_max"]))
        del replay, ranker
        gc.collect()
      del trace
  finally:
    control.close()
  scope = {
          "schema_version": "capd_proactive_stage9_perf_scope_v2_0",
          "counter_scope": config["perf"]["scope"],
          "control": config["perf"]["control"],
          "snapshot_rule": config["perf"]["snapshot_rule"],
          "snapshot_count": snapshot_count,
          "measured_job_ids": measured_job_ids,
          "measured_cells": measured_cells,
          "zero_round_job_count": len(zero_round_jobs),
          "zero_round_job_ids": zero_round_jobs,
          "zero_round_cells": zero_round_cells,
          "repetitions_per_snapshot": repetitions,
          "measured_rounds": measured_rounds,
          "measured_demoted_pages": measured_pages,
          "formal_b_max": 2, "device": "cpu",
          "model_load_and_warmup_excluded": True,
          "test_used_for_parameter_selection": False}
  _audit_perf_scope_counts(scope, config, jobs)
  stage9.write_json_atomic(
      os.path.join(run_root, "perf", "perf_scope_counts.json"), scope)
  print("[OK] perf controlled region completed: {} rounds, {} pages".format(
      measured_rounds, measured_pages))


def parse_perf(args):
  run_root, config, _, _, _, _, _ = _loaded_run(args)
  raw_path = os.path.join(run_root, "perf", "perf-stat.raw")
  if not os.path.isfile(raw_path):
    raise stage9.Stage9ContractError("perf raw output is missing.")
  with open(raw_path, "r", encoding="utf-8", errors="replace") as handle:
    raw = handle.read()
  parsed = stage9.parse_perf_stat(raw, delimiter=";")
  counts = stage9.load_json(os.path.join(
      run_root, "perf", "perf_scope_counts.json"))
  cycles = parsed["events"]["cycles"]
  parsed["counter_source"] = config["perf"]["counter_source"]
  parsed["scope_counts"] = counts
  parsed["derived"] = None
  if cycles["status"] == "ok":
    parsed["derived"] = stage9.cycles_per_unit(
        int(cycles["value"]), int(counts["measured_rounds"]),
        int(counts["measured_demoted_pages"]),
        "linux_perf_hardware")
  else:
    parsed["permission_guidance"] = (
        "Grant access to hardware counters (for example lower "
        "kernel.perf_event_paranoid or use an authorized perf setup), then "
        "rerun with a NEW run ID. Never substitute wall time times frequency.")
  stage9.write_json_atomic(
      os.path.join(run_root, "perf", "perf_parsed.json"), parsed)
  if not parsed["required_events_verified"]:
    raise stage9.Stage9ContractError(
        "required perf counters unavailable: " +
        str(parsed["failure_reason"]))
  report_path = os.path.join(run_root, "artifacts", "report_cn.md")
  with open(report_path, "r", encoding="utf-8") as handle:
    report = handle.read().rstrip()
  derived = parsed["derived"]
  report += (
      "\n\n## Linux perf 硬件计数\n\n"
      "计数窗口由 perf FIFO enable/disable 控制，排除模型加载和预热；"
      "原始输出未改写地保存在 `perf/perf-stat.raw`。\n\n"
      "- cycles：{}\n"
      "- instructions：{}\n"
      "- task-clock：{}\n"
      "- cycles/round：{}\n"
      "- cycles/demoted page：{}\n\n".format(
          parsed["events"]["cycles"]["value"],
          parsed["events"]["instructions"]["value"],
          parsed["events"]["task-clock"]["value"],
          derived["cpu_cycles_per_round"],
          derived["cpu_cycles_per_demoted_page"]))
  stage9.write_text_atomic(report_path, report)
  state = stage9.load_json(os.path.join(run_root, "run_state.json"))
  completed = list(state.get("completed", []))
  if "perf_cycles" not in completed:
    completed.append("perf_cycles")
  stage9.write_run_state(run_root, stage9.RUNNING, completed)
  print("[OK] Linux perf hardware cycles parsed and normalized")


def record_tests(args):
  run_root, config, _, _, _, _, _ = _loaded_run(args)
  if not os.path.isfile(args.test_log):
    raise stage9.Stage9ContractError("Regression test log is missing.")
  with open(args.test_log, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  matches = re.findall(r"Ran\s+(\d+)\s+tests?", text)
  count = int(matches[-1]) if matches else 0
  minimum = config["acceptance"][
      "minimum_stage1_through_stage9_regression_tests"]
  passed = bool(re.search(r"(?m)^OK(?:\s|$)", text)) and count >= minimum
  receipt = {
      "schema_version": "capd_proactive_stage9_server_test_receipt_v2_0",
      "contract_id": stage9.CONTRACT_ID,
      "status": "passed" if passed else "failed",
      "test_count": count, "minimum_required": minimum,
      "log_path": os.path.relpath(args.test_log, args.project_root).replace(
          os.sep, "/"),
      "log_sha256": stage9.fingerprint_file(args.test_log),
      "recorded_at": _utc_now()}
  stage9.write_json_atomic(
      os.path.join(run_root, "server_test_receipt.json"), receipt)
  if not passed:
    raise stage9.Stage9ContractError(
        "Full Stage1-9 regression suite did not satisfy acceptance.")
  state = stage9.load_json(os.path.join(run_root, "run_state.json"))
  completed = list(state.get("completed", []))
  if "server_regressions" not in completed:
    completed.append("server_regressions")
  stage9.write_run_state(run_root, stage9.RUNNING, completed)
  print("[OK] recorded {} passing regression tests".format(count))


def _read_raw_accumulators(path, expected_jobs=None):
  accumulators = {str(b): _LatencyAccumulator()
                  for b in stage9.SENSITIVITY_BMAX}
  expected = (_expected_job_map(expected_jobs)
              if expected_jobs is not None else None)
  with open(path, "r", encoding="utf-8", newline="") as handle:
    import csv
    reader = csv.DictReader(handle)
    if tuple(reader.fieldnames or ()) != RAW_FIELDS:
      raise stage9.Stage9ContractError("Raw latency CSV schema changed.")
    for raw in reader:
      sample = {key: raw[key] for key in raw}
      for key in RAW_FIELDS:
        if key not in ("sample_kind", "track", "workload", "trace_sha256",
                       "checkpoint_sha256"):
          sample[key] = int(sample[key])
      phase_sum = sum(sample[field] for field in stage9.EXCLUSIVE_PHASE_FIELDS)
      if (sample["total_round_latency_ns"] - phase_sum !=
          sample["unattributed_framework_overhead_ns"]):
        raise stage9.Stage9ContractError("Raw exclusive timing accounting failed.")
      if expected is not None:
        identity = (sample["track"], sample["workload"], sample["seed"])
        job = expected.get(identity)
        context = (None if job is None else
                   _job_context(job, sample["b_max"]))
        if (context is None or
            any(sample.get(key) != value for key, value in context.items())):
          raise stage9.Stage9ContractError(
              "Raw latency sample differs from Stage-8 v2 plan_job.")
      accumulators[str(sample["b_max"])].add(sample)
  return accumulators


def _verify_regression_receipt(run_root, project_root, receipt, minimum):
  recorded = receipt.get("log_path")
  if not isinstance(recorded, str) or os.path.isabs(recorded):
    raise stage9.Stage9ContractError("Regression log path is invalid.")
  log_path = os.path.realpath(os.path.join(
      project_root, recorded.replace("/", os.sep).replace("\\", os.sep)))
  resolved_run_root = os.path.realpath(run_root)
  try:
    confined = os.path.commonpath((resolved_run_root, log_path)) == resolved_run_root
  except ValueError:
    confined = False
  if not confined or not os.path.isfile(log_path):
    raise stage9.Stage9ContractError(
        "Regression log must be an artifact inside this Stage-9 run.")
  stage9.verify_file_binding(
      log_path, receipt.get("log_sha256"), "Stage-9 regression log")
  with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
    text = handle.read()
  matches = re.findall(r"Ran\s+(\d+)\s+tests?", text)
  count = int(matches[-1]) if matches else 0
  nonempty = [line.strip() for line in text.splitlines() if line.strip()]
  final_ok = bool(nonempty and re.fullmatch(
      r"OK(?:\s+\([^\r\n]*\))?", nonempty[-1]))
  if (receipt.get("schema_version") !=
      "capd_proactive_stage9_server_test_receipt_v2_0" or
      receipt.get("contract_id") != stage9.CONTRACT_ID or
      receipt.get("status") != "passed" or
      receipt.get("test_count") != count or
      receipt.get("minimum_required") != minimum or
      count < minimum or not final_ok):
    raise stage9.Stage9ContractError(
        "Server regression receipt does not reproduce the confined log.")


def _verify_perf_evidence(raw, parsed, scope, config, jobs):
  reparsed = stage9.parse_perf_stat(raw, delimiter=";")
  _audit_perf_scope_counts(scope, config, jobs)
  cycles = reparsed["events"]["cycles"]
  if (reparsed.get("cycles_verified") is not True or
      reparsed.get("required_events_verified") is not True or
      cycles.get("status") != "ok"):
    raise stage9.Stage9ContractError(
        "Raw Linux perf output does not contain verified hardware counters.")
  expected = copy.deepcopy(reparsed)
  expected["counter_source"] = "linux_perf_hardware"
  expected["scope_counts"] = copy.deepcopy(scope)
  expected["derived"] = stage9.cycles_per_unit(
      int(cycles["value"]), int(scope["measured_rounds"]),
      int(scope["measured_demoted_pages"]), "linux_perf_hardware")
  if parsed != expected:
    raise stage9.Stage9ContractError(
        "Parsed perf evidence does not reproduce raw counters and scope.")
  return expected


def _verify_capacity_rows(memory, capacity_rows, jobs, config):
  expected_rows = stage9.capacity_overhead_rows(
      int(memory["management_fixed_bytes"]),
      int(memory["metadata_bytes_per_page"]),
      _capacity_workload_rows(jobs),
      int(config["storage"]["page_size_bytes"]))
  expected = {row["workload"]: row for row in expected_rows}
  if (len(capacity_rows) != 6 or
      {row.get("workload") for row in capacity_rows} != set(expected)):
    raise stage9.Stage9ContractError(
        "Capacity overhead matrix must have 6 unique workload rows.")
  for row in capacity_rows:
    reference = expected[row["workload"]]
    if (set(row) != set(reference) or
        any(str(row.get(key)) != str(value)
            for key, value in reference.items())):
      raise stage9.Stage9ContractError(
          "Capacity CSV does not reproduce the memory breakdown and Stage-8 D.")


def _verify_summary_metadata(latency, throughput, quality, perf_scope, config):
  applicability = config["measurement_matrix"]["latency_applicability"]
  expected = (
      (latency, {
          "schema_version": "capd_proactive_stage9_latency_suite_v2_0",
          "formal_b_max": 2,
          "sensitivity_purpose": "analysis_only_not_selection",
          "applicability": applicability}),
      (throughput, {
          "schema_version": "capd_proactive_stage9_throughput_suite_v2_0",
          "formal_b_max": 2,
          "sensitivity_purpose": "analysis_only_not_selection",
          "applicability": applicability}),
      (quality, {
          "schema_version": "capd_proactive_stage9_quality_v2_0",
          "formal_b_max": 2, "purpose": "analysis_only_not_selection",
          "test_used_for_parameter_selection": False}),
      (perf_scope, {
          "schema_version": "capd_proactive_stage9_perf_scope_v2_0",
          "formal_b_max": 2, "device": "cpu",
          "control": config["perf"]["control"],
          "snapshot_rule": config["perf"]["snapshot_rule"],
          "repetitions_per_snapshot":
              config["perf"]["repetitions_per_snapshot"],
          "model_load_and_warmup_excluded": True,
          "test_used_for_parameter_selection": False}))
  if any(any(value.get(key) != item for key, item in required.items())
         for value, required in expected):
    raise stage9.Stage9ContractError(
        "Stage-9 v2 summary schema/formal metadata changed.")


def verify(args):
  run_root, config, _, _, entry, identity, _ = _loaded_run(args)
  required = stage9.load_json(os.path.join(
      args.project_root, config["result_schema"]))["required_run_artifacts"]
  missing = [path for path in required if path != "verification.json"
             if not os.path.isfile(os.path.join(run_root, path))]
  if missing:
    raise stage9.Stage9ContractError(
        "Stage-9 required artifacts missing: {}".format(missing))
  environment = stage9.load_json(os.path.join(run_root, "environment.json"))
  stage9.validate_runtime_binding(environment["runtime_binding"])
  if environment.get("system") != "Linux" or environment.get("device") != "cpu":
    raise stage9.Stage9ContractError("Verification requires real Linux CPU data.")
  receipt = stage9.load_json(os.path.join(run_root, "server_test_receipt.json"))
  _verify_regression_receipt(
      run_root, args.project_root, receipt,
      config["acceptance"]["minimum_stage1_through_stage9_regression_tests"])
  perf = stage9.load_json(os.path.join(run_root, "perf", "perf_parsed.json"))
  jobs = _measurement_jobs(config, entry)
  perf_scope = stage9.load_json(os.path.join(
      run_root, "perf", "perf_scope_counts.json"))
  with open(os.path.join(run_root, "perf", "perf-stat.raw"), "r",
            encoding="utf-8", errors="replace") as handle:
    perf_raw = handle.read()
  _verify_perf_evidence(perf_raw, perf, perf_scope, config, jobs)
  memory = stage9.load_json(os.path.join(run_root, "memory_breakdown.json"))
  rss = memory.get("rss", {})
  if (memory.get("management_fixed_bytes", 0) <= 0 or
      memory.get("metadata_bytes_per_page") != 64 or
      rss.get("process_baseline_rss_bytes", 0) <= 0 or
      rss.get("total_peak_rss_bytes", 0) <= 0 or
      rss.get("stage9_incremental_peak_rss_bytes", -1) < 0 or
      rss.get("total_peak_rss_bytes", 0) <
      rss.get("process_baseline_rss_bytes", 0) or
      rss.get("stage9_incremental_peak_rss_bytes") !=
      rss.get("total_peak_rss_bytes") -
      rss.get("process_baseline_rss_bytes") or
      set(memory.get("model_by_seed", {})) != {"3136859", "42", "2026"}):
    raise stage9.Stage9ContractError("Memory breakdown is incomplete.")
  import csv
  capacity_path = os.path.join(run_root, "capacity_overhead.csv")
  with open(capacity_path, "r", encoding="utf-8", newline="") as handle:
    capacity_rows = list(csv.DictReader(handle))
  _verify_capacity_rows(memory, capacity_rows, jobs, config)
  accumulators = _read_raw_accumulators(
      os.path.join(run_root, "raw_latency_samples.csv"), expected_jobs=jobs)
  quality = stage9.load_json(os.path.join(run_root, "quality_summary.json"))
  _audit_measurement_completeness(
      accumulators, quality.get("rows", []), config, expected_jobs=jobs)
  expected_latency = {key: value.latency()
                      for key, value in accumulators.items()}
  expected_throughput = {key: value.throughput()
                         for key, value in accumulators.items()}
  latency = stage9.load_json(os.path.join(run_root, "latency_summary.json"))
  throughput = stage9.load_json(os.path.join(
      run_root, "throughput_summary.json"))
  _verify_summary_metadata(latency, throughput, quality, perf_scope, config)
  if (latency.get("by_b_max") != expected_latency or
      throughput.get("by_b_max") != expected_throughput or
      latency.get("applicability") !=
      config["measurement_matrix"]["latency_applicability"] or
      throughput.get("applicability") !=
      config["measurement_matrix"]["latency_applicability"]):
    raise stage9.Stage9ContractError(
        "Raw samples do not reproduce latency/throughput summaries.")
  if (set(quality.get("by_b_max", {})) != {"1", "2", "4"} or
      quality.get("purpose") != "analysis_only_not_selection" or
      quality.get("test_used_for_parameter_selection") is not False or
      len(quality.get("rows", ())) != 90 or
      any(quality["by_b_max"][key].get("cell_count") != 30 or
          quality["by_b_max"][key].get("active_round_cell_count") != 27 or
          quality["by_b_max"][key].get("zero_round_cell_count") != 3 or
          set(quality["by_b_max"][key].get("by_track", {})) !=
          {"standard", "pressure"} or
          len(quality["by_b_max"][key].get("by_track_workload", {})) != 10
          for key in ("1", "2", "4"))):
    raise stage9.Stage9ContractError("Sensitivity quality guard is incomplete.")
  if quality.get("by_b_max") != _aggregate_quality(
      quality.get("rows", []))["by_b_max"]:
    raise stage9.Stage9ContractError(
        "Sensitivity quality rows do not reproduce aggregate metrics.")
  instrumentation = stage9.load_json(os.path.join(
      run_root, "instrumentation_audit.json"))
  instrumentation_jobs = instrumentation.get("jobs", [])
  _audit_record_identities(instrumentation_jobs, jobs, (2,))
  if (instrumentation.get("status") != "identical" or
      instrumentation.get("formal_b_max") != 2 or
      instrumentation.get("job_count") != 30 or
      len(instrumentation_jobs) != 30 or
      len({row.get("job_id") for row in instrumentation_jobs}) != 30 or
      len({(row.get("track"), row.get("workload"), row.get("seed"))
           for row in instrumentation_jobs}) != 30 or
      any(row.get("status") != "identical" or
          row.get("reference_device") != "cpu" or row.get("b_max") != 2
          for row in instrumentation_jobs)):
    raise stage9.Stage9ContractError("Instrumentation semantics did not pass.")
  compatibility = stage9.load_json(os.path.join(
      run_root, "stage8_compatibility_receipt.json"))
  expected_compatibility = entry["compatibility_receipt"]
  if any(compatibility.get(key) != value
         for key, value in expected_compatibility.items()):
    raise stage9.Stage9ContractError(
        "Stage-8 v2 compatibility receipt changed after preflight.")
  verification = {
      "schema_version": "capd_proactive_stage9_verification_v2_0",
      "contract_id": stage9.CONTRACT_ID,
      "status": stage9.VERIFIED,
      "stage10_entry_gate": stage9.STAGE10_SATISFIED,
      "stage8_entry_gate": "satisfied",
      "stage8_verification_sha256":
          config["stage8_authority"]["verification"]["sha256"],
      "device": "cpu", "linux_measurement": True,
      "perf_cycles_verified": True, "memory_verified": True,
      "raw_to_summary_verified": True,
      "instrumentation_semantics_verified": True,
      "stage8_compatibility_receipt_verified": True,
      "test_used_for_parameter_selection": False,
      "formal_b_max": 2,
      "b_max_sensitivity_purpose": "analysis_only_not_selection",
      "fair_capacity_replay_status": "deferred",
      "stage8_artifacts_overwritten": False,
      "interpretation_boundary": config["interpretation_boundary"],
      "run_identity_sha256": identity["run_identity_sha256"],
      "artifact_sha256": {}, "verified_at": _utc_now()}
  artifact_names = [path for path in required if path not in (
      "verification.json", "run_state.json")]
  verification["artifact_sha256"] = {
      path: stage9.fingerprint_file(os.path.join(run_root, path))
      for path in artifact_names}
  stage9.write_json_atomic(
      os.path.join(run_root, "verification.json"), verification)
  stage9.write_run_state(run_root, stage9.VERIFIED, [
      "preflight", "server_regressions", "latency", "quality", "memory",
      "capacity_accounting", "instrumentation_audit", "perf_cycles",
      "independent_verification"])
  print(config["acceptance"]["success_marker"])


def mark_not_verified(args):
  config = stage9.load_json(args.config)
  stage9.validate_config(config)
  run_root = _run_root(args, config)
  os.makedirs(run_root, exist_ok=True)
  completed = []
  state_path = os.path.join(run_root, "run_state.json")
  if os.path.isfile(state_path):
    completed = stage9.load_json(state_path).get("completed", [])
  failure = {
      "step": args.failure_step, "reason": args.failure_reason,
      "failed_at": _utc_now(), "requires_new_run_id": True}
  if args.failure_step == "perf_hardware_counters":
    evidence = {}
    for name in ("perf-stderr.log", "perf-stat.raw"):
      path = os.path.join(run_root, "perf", name)
      if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
          evidence[name] = handle.read(4096)
    failure["perf_failure_evidence"] = evidence
    failure["permission_guidance"] = (
        "Check /proc/sys/kernel/perf_event_paranoid and hardware-counter "
        "availability; obtain authorized access and rerun with a NEW run ID. "
        "Do not estimate cycles from wall time and CPU frequency.")
  stage9.write_run_state(
      run_root, stage9.NOT_VERIFIED, completed, failure=failure)
  print("[FAILED] Stage-9 marked not verified at {}".format(args.failure_step))


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  parser.add_argument("--config", default=os.path.join(
      PROJECT_ROOT, "configs", "finals", "capd_proactive_stage9.json"))
  parser.add_argument("--stage0-config", default=os.path.join(
      PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json"))
  parser.add_argument("--cost-config", default=os.path.join(
      PROJECT_ROOT, "configs", "finals",
      "capd_proactive_stage2_cost_profiles.json"))
  parser.add_argument("--run-id", required=True)
  sub = parser.add_subparsers(dest="command", required=True)
  sub.add_parser("preflight")
  sub.add_parser("measure")
  perf = sub.add_parser("perf-workload")
  perf.add_argument("--perf-control-fifo", required=True)
  perf.add_argument("--perf-ack-fifo", required=True)
  sub.add_parser("parse-perf")
  tests = sub.add_parser("record-tests")
  tests.add_argument("--test-log", required=True)
  sub.add_parser("verify")
  failed = sub.add_parser("mark-not-verified")
  failed.add_argument("--failure-step", required=True)
  failed.add_argument("--failure-reason", default="server_command_failed")
  return parser


def main(argv: Optional[Sequence[str]] = None):
  args = build_parser().parse_args(argv)
  commands = {
      "preflight": preflight, "measure": measure,
      "perf-workload": perf_workload, "parse-perf": parse_perf,
      "record-tests": record_tests, "verify": verify,
      "mark-not-verified": mark_not_verified}
  commands[args.command](args)


if __name__ == "__main__":
  main()
