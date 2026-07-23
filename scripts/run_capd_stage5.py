#!/usr/bin/env python3
# coding=utf-8
"""Unified CAPD stage-5 planner, executor, auditor, and summarizer.

Formal training/replay is intentionally opt-in via ``--execute`` or a concrete
``--job-id``.  Planning and input audit never launch training or replay.
"""

from __future__ import print_function

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import time
import traceback


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_generator
from qmap import stage5_results
from qmap import stage5_variants
from qmap.qmap_generator import read_trace


STAGE5_STATUS = "STAGE5_IMPLEMENTED_UNVERIFIED"
STAGES = (
    "audit-inputs", "plan", "main", "learned-baselines", "ablations",
    "sensitivity", "summarize", "all")
REQUIRED_OUTPUTS = (
    "stage5_main_results.csv", "stage5_main_summary.json",
    "stage5_main_report.md", "stage5_ablation_results.csv",
    "stage5_ablation_summary.json", "stage5_ablation_report.md",
    "stage5_sensitivity_results.csv", "stage5_sensitivity_report.md",
    "learned_baseline_comparability.json", "stage4_boundary_crosswalk.csv",
    "input_audit.json", "run_manifest.json", "execution_plan.json")


def _portable(path, root):
  path = os.path.abspath(path)
  relative = os.path.relpath(path, root)
  if relative == os.pardir or relative.startswith(os.pardir + os.sep):
    return path
  return relative.replace(os.sep, "/")


def _atomic_json(path, value):
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  temporary = "{}.tmp.{}".format(path, os.getpid())
  finals_config.write_json(temporary, value)
  os.replace(temporary, path)


def _git_commit(repo_root):
  try:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        universal_newlines=True).strip()
  except (OSError, subprocess.CalledProcessError):
    return "unknown"


def _code_fingerprint(repo_root):
  paths = (
      "scripts/run_capd_stage5.py", "qmap/stage5_variants.py",
      "qmap/stage5_results.py", "qmap/finals_config.py",
      "qmap/finals_generator.py", "qmap/candidate_filter.py",
      "qmap/qmap_train.py", "qmap/qmap_eval.py",
      "policy_learning/cache_model/model.py")
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def _base_artifacts(args, workload, B=64):
  root = os.path.join(args.artifact_root, workload, "B{}".format(B))
  return {
      "root": root,
      "config": os.path.join(root, "resolved_config.json"),
      "selector": os.path.join(root, "selector_params.json"),
      "train": os.path.join(root, "train.jsonl"),
      "valid": os.path.join(root, "valid.jsonl"),
  }


def _variant_roots(args, spec, workload):
  family = spec["family"]
  data_root = (
      args.ablation_data_root if family == "ablation"
      else args.sensitivity_data_root)
  checkpoint_root = (
      args.ablation_checkpoint_root if family == "ablation"
      else args.sensitivity_checkpoint_root)
  result_root = (
      args.ablation_result_root if family == "ablation"
      else args.sensitivity_result_root)
  data = os.path.join(data_root, spec["variant_id"], workload)
  checkpoint = os.path.join(
      checkpoint_root, spec["variant_id"], workload)
  result = os.path.join(result_root, "raw", spec["variant_id"], workload)
  return {"data": data, "checkpoint": checkpoint, "result": result}


def _display_command(argv):
  return " ".join(shlex.quote(value) for value in argv)


def _main_jobs(args):
  jobs = []
  for workload in stage5_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    for seed in stage5_variants.MODEL_SEEDS:
      checkpoint = os.path.join(
          args.stage4_checkpoint_root, workload,
          "seed_{}".format(seed), "qmap_best.pth")
      result = os.path.join(
          args.main_result_root, "raw", workload, "qmap",
          "seed_{}.json".format(seed))
      argv = [
          "python3", "qmap/qmap_eval.py", "--config", base["config"],
          "--selector_params", base["selector"], "--policy", "qmap",
          "--checkpoint", checkpoint, "--json_output", result]
      jobs.append({
          "job_id": "main:{}:qmap:{}".format(workload, seed),
          "stage": "main", "kind": "replay", "required": True,
          "workload": workload, "policy": "qmap", "model_seed": seed,
          "result_path": result, "argv": argv, "dependencies": [],
          "resource": "gpu_or_cpu_inference"})
    for replay_seed in stage5_variants.RANDOM_REPLAY_SEEDS:
      result = os.path.join(
          args.main_result_root, "raw", workload, "random",
          "seed_{}.json".format(replay_seed))
      argv = [
          "python3", "qmap/qmap_eval.py", "--config", base["config"],
          "--policy", "random", "--stage5_replay_seed", str(replay_seed),
          "--json_output", result]
      jobs.append({
          "job_id": "main:{}:random:{}".format(workload, replay_seed),
          "stage": "main", "kind": "replay", "required": True,
          "workload": workload, "policy": "random",
          "replay_seed": replay_seed, "result_path": result, "argv": argv,
          "dependencies": [], "resource": "cpu"})
    for policy in ("lru", "lfu", "clock"):
      result = os.path.join(
          args.main_result_root, "raw", workload, policy, "run.json")
      argv = [
          "python3", "qmap/qmap_eval.py", "--config", base["config"],
          "--policy", policy, "--json_output", result]
      jobs.append({
          "job_id": "main:{}:{}:deterministic".format(workload, policy),
          "stage": "main", "kind": "replay", "required": True,
          "workload": workload, "policy": policy, "result_path": result,
          "argv": argv, "dependencies": [], "resource": "cpu"})
  return jobs


def _variant_jobs(args, specs):
  jobs = []
  for spec in specs:
    for workload in stage5_variants.WORKLOADS:
      roots = _variant_roots(args, spec, workload)
      data_job_id = "{}:data:{}:{}".format(
          spec["family"], spec["variant_id"], workload)
      jobs.append({
          "job_id": data_job_id, "stage": (
              "ablations" if spec["family"] == "ablation"
              else "sensitivity"),
          "kind": "variant_data", "required": True, "workload": workload,
          "variant_id": spec["variant_id"], "result_path": os.path.join(
              roots["data"], "variant_manifest.json"),
          "dependencies": [], "resource": "cpu_memory_bound",
          "argv": [
              "python3", "scripts/run_capd_stage5.py", "--stage",
              ("ablations" if spec["family"] == "ablation"
               else "sensitivity"), "--job-id", data_job_id]})
      seeds = (
          stage5_variants.MODEL_SEEDS
          if spec["family"] == "ablation" else (3136859,))
      for seed in seeds:
        checkpoint_dir = os.path.join(
            roots["checkpoint"], "seed_{}".format(seed))
        train_job_id = "{}:train:{}:{}:{}".format(
            spec["family"], spec["variant_id"], workload, seed)
        replay_job_id = "{}:replay:{}:{}:{}".format(
            spec["family"], spec["variant_id"], workload, seed)
        config = os.path.join(roots["data"], "resolved_config.json")
        selector = os.path.join(roots["data"], "selector_params.json")
        train_jsonl = os.path.join(roots["data"], "train.jsonl")
        valid_jsonl = os.path.join(roots["data"], "valid.jsonl")
        train_argv = [
            "python3", "qmap/qmap_train.py", "--config", config,
            "--selector_params", selector, "--train_data", train_jsonl,
            "--valid_data", valid_jsonl, "--output_dir", checkpoint_dir,
            "--seed", str(seed)]
        jobs.append({
            "job_id": train_job_id, "stage": (
                "ablations" if spec["family"] == "ablation"
                else "sensitivity"),
            "kind": "train", "required": True, "workload": workload,
            "variant_id": spec["variant_id"], "model_seed": seed,
            "result_path": os.path.join(
                checkpoint_dir, "checkpoint_manifest.json"),
            "dependencies": [data_job_id], "resource": "single_gpu",
            "argv": train_argv})
        result = os.path.join(
            roots["result"], "seed_{}.json".format(seed))
        replay_argv = [
            "python3", "qmap/qmap_eval.py", "--config", config,
            "--selector_params", selector, "--policy", "qmap",
            "--checkpoint", os.path.join(checkpoint_dir, "qmap_best.pth"),
            "--json_output", result]
        jobs.append({
            "job_id": replay_job_id, "stage": (
                "ablations" if spec["family"] == "ablation"
                else "sensitivity"),
            "kind": "replay", "required": True, "workload": workload,
            "variant_id": spec["variant_id"], "model_seed": seed,
            "result_path": result, "dependencies": [train_job_id],
            "resource": "gpu_or_cpu_inference", "argv": replay_argv})
  return jobs


def _identity_jobs(args):
  return [{
      "job_id": "ablation:identity:uniform_selector:{}".format(workload),
      "stage": "ablations", "kind": "identity", "required": True,
      "workload": workload, "variant_id": "uniform_selector_identity",
      "result_path": os.path.join(
          args.ablation_result_root, "identity_controls",
          "{}.json".format(workload)),
      "dependencies": [], "resource": "cpu",
      "argv": [
          "python3", "scripts/run_capd_stage5.py", "--stage", "ablations",
          "--job-id",
          "ablation:identity:uniform_selector:{}".format(workload)]}
      for workload in stage5_variants.WORKLOADS]


def _learned_jobs(args):
  jobs = []
  for workload in stage5_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    config = finals_config.load_json(base["config"])
    for policy in ("kleio_lite", "patterns_lite"):
      model_path = os.path.join(
          args.learned_result_root, "models", workload,
          "{}.json".format(policy))
      result = os.path.join(
          args.learned_result_root, "raw", workload,
          "{}.json".format(policy))
      train_id = "learned:train:{}:{}".format(workload, policy)
      train_argv = [
          "python3", "qmap/learned_baselines.py", "--policy", policy,
          "--config", base["config"], "--train_trace",
          config["data"]["train_trace"], "--model_output", model_path]
      jobs.append({
          "job_id": train_id, "stage": "learned-baselines", "kind": "train",
          "required": False, "workload": workload, "policy": policy,
          "result_path": model_path, "dependencies": [],
          "resource": "cpu", "argv": train_argv})
      jobs.append({
          "job_id": "learned:replay:{}:{}".format(workload, policy),
          "stage": "learned-baselines", "kind": "replay",
          "required": False, "workload": workload, "policy": policy,
          "result_path": result, "dependencies": [train_id],
          "resource": "cpu",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", base["config"],
              "--policy", policy, "--learned_model", model_path,
              "--json_output", result]})
  return jobs


def build_execution_plan(args):
  core = stage5_variants.core_ablation_specs()
  sensitivity = stage5_variants.sensitivity_specs()
  jobs = (_main_jobs(args) + _identity_jobs(args) +
          _variant_jobs(args, core) + _variant_jobs(args, sensitivity) +
          _learned_jobs(args))
  code_fingerprint = _code_fingerprint(args.repo_root)
  file_fingerprint_cache = {}

  def fingerprint_path(path):
    absolute = path if os.path.isabs(path) else os.path.join(
        args.repo_root, path)
    absolute = os.path.abspath(absolute)
    if absolute not in file_fingerprint_cache:
      file_fingerprint_cache[absolute] = (
          finals_config.fingerprint_file(absolute)
          if os.path.isfile(absolute) else None)
    return file_fingerprint_cache[absolute]

  by_id = {}
  for job in jobs:
    job["command"] = _display_command(job["argv"])
    input_paths = []
    if not job.get("dependencies"):
      for flag in (
          "--config", "--selector_params", "--checkpoint", "--train_trace"):
        if flag in job["argv"]:
          input_paths.append(job["argv"][job["argv"].index(flag) + 1])
      if job["kind"] == "identity":
        base = _base_artifacts(args, job["workload"])
        input_paths.extend((base["config"], base["selector"]))
      elif job["kind"] == "variant_data":
        spec = stage5_variants.get_variant_spec(job["variant_id"])
        base = _base_artifacts(
            args, job["workload"],
            8 if spec["variant_id"] == "no_filter_B8_K8" else 64)
        input_paths.extend((base["config"], base["selector"]))
        if spec["changes"].get("selector_drop"):
          input_paths.append(args.stage3_ablation_csv)
      for path in list(input_paths):
        absolute = path if os.path.isabs(path) else os.path.join(
            args.repo_root, path)
        if (os.path.basename(path) == "resolved_config.json" and
            os.path.isfile(absolute)):
          config = finals_config.load_json(absolute)
          input_paths.extend(
              config.get("data", {}).get(key)
              for key in ("train_trace", "valid_trace", "test_trace"))
    job["input_fingerprints"] = {}
    for path in input_paths:
      if not path:
        continue
      absolute = path if os.path.isabs(path) else os.path.join(
          args.repo_root, path)
      job["input_fingerprints"][
          _portable(absolute, args.repo_root)] = fingerprint_path(absolute)
    job["dependency_fingerprints"] = {
        dependency: by_id[dependency]["job_fingerprint"]
        for dependency in job.get("dependencies", [])
    }
    fingerprint_payload = {
        key: job.get(key) for key in (
            "job_id", "kind", "workload", "variant_id", "policy",
            "model_seed", "replay_seed", "result_path", "dependencies",
            "command", "input_fingerprints", "dependency_fingerprints")
    }
    fingerprint_payload["code_fingerprint"] = code_fingerprint
    job["job_fingerprint"] = finals_config.fingerprint_value(
        fingerprint_payload)
    by_id[job["job_id"]] = job
  required = [job for job in jobs if job["required"]]
  counts = {
      "main_replay": len([job for job in required if job["stage"] == "main"]),
      "identity_controls": len([
          job for job in required if job["kind"] == "identity"]),
      "core_ablation_data": len([
          job for job in required if job["stage"] == "ablations" and
          job["kind"] == "variant_data"]),
      "core_ablation_training": len([
          job for job in required if job["stage"] == "ablations" and
          job["kind"] == "train"]),
      "core_ablation_replay": len([
          job for job in required if job["stage"] == "ablations" and
          job["kind"] == "replay"]),
      "sensitivity_data": len([
          job for job in required if job["stage"] == "sensitivity" and
          job["kind"] == "variant_data"]),
      "sensitivity_training": len([
          job for job in required if job["stage"] == "sensitivity" and
          job["kind"] == "train"]),
      "sensitivity_replay": len([
          job for job in required if job["stage"] == "sensitivity" and
          job["kind"] == "replay"]),
      "optional_learned_baseline_jobs": len([
          job for job in jobs if not job["required"]]),
  }
  counts["required_experiment_jobs"] = sum(
      value for key, value in counts.items()
      if key != "optional_learned_baseline_jobs")
  return {
      "schema_version": "capd_finals_v3_stage5_plan_1",
      "contract_id": finals_config.CONTRACT_ID,
      "stage_status": STAGE5_STATUS,
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": code_fingerprint,
      "test_used_for_selection": False,
      "full_defaults_reused": True,
      "sensitivity_B8_alias": "no_filter_B8_K8",
      "counts": counts,
      "jobs": jobs,
  }


def audit_inputs(args):
  checks = []

  def check(name, condition, detail):
    checks.append({
        "name": name, "status": "PASS" if condition else "FAIL",
        "detail": detail})

  stage4_summary_path = os.path.join(
      args.stage4_result_root, "stage4_summary.json")
  distribution_path = os.path.join(
      args.stage4_result_root, "distribution_summary.json")
  distribution_metrics_path = os.path.join(
      args.stage4_result_root, "distribution_metrics.csv")
  counterfactual_path = os.path.join(
      args.stage4_result_root, "counterfactual_summary.json")
  check("stage4_summary_exists", os.path.isfile(stage4_summary_path),
        _portable(stage4_summary_path, args.repo_root))
  if os.path.isfile(stage4_summary_path):
    stage4 = finals_config.load_json(stage4_summary_path)
    check("stage4_verified", stage4.get("status") == "STAGE4_VERIFIED",
          str(stage4.get("status")))
  check("g11_distribution_exists", os.path.isfile(distribution_path),
        _portable(distribution_path, args.repo_root))
  if os.path.isfile(distribution_path):
    distribution = finals_config.load_json(distribution_path)
    check("g11_review_required",
          distribution.get("review_required") is True,
          "REVIEW_REQUIRED={}".format(distribution.get("review_required")))
  warning_counts = {}
  if os.path.isfile(distribution_metrics_path):
    with open(distribution_metrics_path, "r", encoding="utf-8",
              newline="") as input_file:
      for row in csv.DictReader(input_file):
        warning = row.get("warning")
        warning_counts[warning] = warning_counts.get(warning, 0) + 1
  check("g11_warning_counts",
        warning_counts.get("large") == 36 and
        warning_counts.get("moderate") == 9,
        "large={} moderate={}".format(
            warning_counts.get("large"), warning_counts.get("moderate")))
  check("g12_counterfactual_exists", os.path.isfile(counterfactual_path),
        _portable(counterfactual_path, args.repo_root))

  checkpoint_count = 0
  for workload in stage5_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    for name, path in base.items():
      if name != "root":
        check("{}_{}_exists".format(workload, name), os.path.isfile(path),
              _portable(path, args.repo_root))
    for seed in stage5_variants.MODEL_SEEDS:
      directory = os.path.join(
          args.stage4_checkpoint_root, workload,
          "seed_{}".format(seed))
      manifest_path = os.path.join(directory, "checkpoint_manifest.json")
      checkpoint_path = os.path.join(directory, "qmap_best.pth")
      valid = os.path.isfile(manifest_path) and os.path.isfile(checkpoint_path)
      detail = _portable(directory, args.repo_root)
      if valid:
        manifest = finals_config.load_json(manifest_path)
        actual = finals_config.fingerprint_file(checkpoint_path)
        valid = (
            int(manifest.get("seed", -1)) == seed and
            manifest.get("checkpoints", {}).get("best", {}).get(
                "fingerprint") == actual and
            manifest.get("test_trace_opened") is False)
      check("checkpoint_{}_{}".format(workload, seed), valid, detail)
      checkpoint_count += int(valid)
  passed = all(item["status"] == "PASS" for item in checks)
  result = {
      "schema_version": "capd_finals_v3_stage5_input_audit_1",
      "contract_id": finals_config.CONTRACT_ID,
      "stage_status": STAGE5_STATUS,
      "status": "PASSED" if passed else "FAILED",
      "checkpoint_count": checkpoint_count,
      "expected_checkpoint_count": 9,
      "checks": checks,
      "test_trace_role": "fingerprint_only_until_final_replay",
      "test_used_for_selection": False,
  }
  path = os.path.join(args.output_root, "input_audit.json")
  _atomic_json(path, result)
  if not passed:
    raise ValueError("Stage-5 input audit failed; see {}".format(path))
  return result


def _dependency_complete(plan_by_id, job):
  for dependency in job.get("dependencies", []):
    parent = plan_by_id[dependency]
    manifest = _job_manifest_path(args=None, job=parent)
    if not os.path.isfile(manifest):
      raise ValueError("Dependency is incomplete: {}".format(dependency))
    payload = finals_config.load_json(manifest)
    if payload.get("status") != "COMPLETED":
      raise ValueError("Dependency did not complete: {}".format(dependency))


def _job_manifest_path(args, job):
  del args
  return "{}.job_manifest.json".format(job["result_path"])


def _job_is_complete(job):
  manifest_path = _job_manifest_path(None, job)
  if not os.path.isfile(manifest_path) or not os.path.isfile(
      job["result_path"]):
    return False
  manifest = finals_config.load_json(manifest_path)
  return (
      manifest.get("status") == "COMPLETED" and
      manifest.get("job_fingerprint") == job["job_fingerprint"] and
      os.path.getsize(job["result_path"]) > 0 and
      manifest.get("result_fingerprint") ==
      finals_config.fingerprint_file(job["result_path"]))


def _execute_variant_data(args, job):
  spec = stage5_variants.get_variant_spec(job["variant_id"])
  roots = _variant_roots(args, spec, job["workload"])
  os.makedirs(roots["data"], exist_ok=True)
  base_B = 8 if spec["variant_id"] == "no_filter_B8_K8" else 64
  base = _base_artifacts(args, job["workload"], base_B)
  base_config = finals_config.load_config(
      base["config"], require_resolved=True, project_root=args.repo_root)
  config = stage5_variants.build_variant_config(base_config, spec)
  config_path = os.path.join(roots["data"], "resolved_config.json")
  selector_path = os.path.join(roots["data"], "selector_params.json")
  train_path = os.path.join(roots["data"], "train.jsonl")
  valid_path = os.path.join(roots["data"], "valid.jsonl")
  validation_path = os.path.join(
      roots["data"], "selector_validation_samples.jsonl")
  summary_path = os.path.join(roots["data"], "generator_summary.json")
  finals_config.write_json(config_path, config)

  if stage5_variants.variant_requires_fresh_selector(spec):
    generator_args = argparse.Namespace(
        config=config_path, selector_output=selector_path,
        validation_samples_output=validation_path, train_output=train_path,
        valid_output=valid_path, summary_output=summary_path, page_shift=None)
    finals_generator.fit_selector_and_generate(generator_args)
    selector = finals_config.load_json(selector_path)
  else:
    base_selector = finals_config.load_json(base["selector"])
    selector = stage5_variants.build_bound_selector(
        base_selector, config, spec,
        stage3_ablation_csv=args.stage3_ablation_csv,
        command=job["command"])
    finals_config.write_json(selector_path, selector)
    train_trace, _ = read_trace(
        config["data"]["train_trace"], int(config["trace"]["page_shift"]))
    valid_trace, _ = read_trace(
        config["data"]["valid_trace"], int(config["trace"]["page_shift"]))
    train_metadata = finals_generator.generate_reranker_jsonl(
        train_trace, config["data"]["train_trace"], "train", train_path,
        config, selector, config_path, job["command"], holdout=None)
    del train_trace
    valid_metadata = finals_generator.generate_reranker_jsonl(
        valid_trace, config["data"]["valid_trace"], "valid", valid_path,
        config, selector, config_path, job["command"], holdout=None)
    del valid_trace
    finals_config.write_json(summary_path, {
        "schema_version": finals_config.SCHEMA_VERSION,
        "contract_id": finals_config.CONTRACT_ID,
        "stage5_variant": config["stage5_variant"],
        "selector_fingerprint": finals_config.selector_fingerprint(selector),
        "train_metadata": train_metadata, "valid_metadata": valid_metadata,
        "test_trace_opened": False, "test_used_for_selection": False})

  manifest = stage5_variants.variant_manifest(
      spec, config, _portable(selector_path, args.repo_root),
      finals_config.selector_fingerprint(selector),
      config["data"]["split_fingerprints"],
      {"train": finals_config.fingerprint_file(train_path),
       "valid": finals_config.fingerprint_file(valid_path)},
      None, None, None, _git_commit(args.repo_root), job["command"],
      official=True,
      upstream=("stage3_B64_leave_one_out" if
                spec["changes"].get("selector_drop") else
                "stage5_train_valid_regeneration"))
  manifest.update({
      "run_status": "COMPLETED", "test_trace_access": "fingerprint_only",
      "evidence_tier": (
          "three_seed_official_planned" if spec["family"] == "ablation"
          else "single_seed_sensitivity")})
  _atomic_json(job["result_path"], manifest)


def _execute_identity(args, job):
  base = _base_artifacts(args, job["workload"])
  selector = finals_config.load_json(base["selector"])
  control = stage5_variants.validate_uniform_identity(selector, selector)
  control.update({
      "workload": job["workload"], "run_status": "COMPLETED",
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "test_trace_opened": False, "test_used_for_selection": False})
  _atomic_json(job["result_path"], control)


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
    raise ValueError(
        "Job {} failed with exit code {}; no retry performed.".format(
            job["job_id"], completed.returncode))
  if not os.path.isfile(job["result_path"]):
    raise ValueError("Job completed without required output: {}".format(
        job["result_path"]))
  if job["kind"] == "replay":
    result = finals_config.load_json(job["result_path"])
    result.update({
        "workload": job["workload"], "run_status": "COMPLETED",
        "artifact_class": "official", "test_used_for_selection": False})
    if job.get("variant_id"):
      result["variant_id"] = job["variant_id"]
      result["evidence_tier"] = (
          "three_seed_official" if job["stage"] == "ablations"
          else "single_seed_sensitivity")
    if job.get("model_seed") is not None:
      result["model_seed"] = int(job["model_seed"])
    if job.get("replay_seed") is not None:
      result["replay_seed"] = int(job["replay_seed"])
    if job.get("variant_id"):
      def argv_value(flag):
        position = job["argv"].index(flag)
        return job["argv"][position + 1]

      spec = stage5_variants.get_variant_spec(job["variant_id"])
      config_path = argv_value("--config")
      selector_path = argv_value("--selector_params")
      checkpoint_path = argv_value("--checkpoint")
      config = finals_config.load_config(
          config_path, require_resolved=True, project_root=args.repo_root)
      selector = finals_config.load_json(selector_path)
      checkpoint_manifest_path = os.path.join(
          os.path.dirname(checkpoint_path), "checkpoint_manifest.json")
      checkpoint_manifest = finals_config.load_json(
          checkpoint_manifest_path)
      replay_manifest = stage5_variants.variant_manifest(
          spec, config, _portable(selector_path, args.repo_root),
          finals_config.selector_fingerprint(selector),
          config["data"]["split_fingerprints"],
          checkpoint_manifest.get("jsonl_fingerprints", {}),
          finals_config.fingerprint_file(checkpoint_path),
          job.get("model_seed"), job.get("replay_seed"),
          _git_commit(args.repo_root), job["command"], official=True,
          upstream=("stage3_B64_leave_one_out" if
                    spec["changes"].get("selector_drop") else
                    "stage5_train_valid_regeneration"))
      replay_manifest.update({
          "run_status": "COMPLETED",
          "checkpoint_path": _portable(checkpoint_path, args.repo_root),
          "checkpoint_manifest_fingerprint": (
              finals_config.fingerprint_file(checkpoint_manifest_path)),
          "result_path": _portable(job["result_path"], args.repo_root),
          "result_fingerprint": finals_config.fingerprint_value(result),
          "test_trace_opened": True,
          "test_used_for_selection": False,
          "evidence_tier": result["evidence_tier"],
      })
      replay_manifest_path = "{}.variant_manifest.json".format(
          job["result_path"])
      _atomic_json(replay_manifest_path, replay_manifest)
      result["variant_manifest_path"] = _portable(
          replay_manifest_path, args.repo_root)
    _atomic_json(job["result_path"], result)


def execute_job(args, plan, job):
  by_id = {item["job_id"]: item for item in plan["jobs"]}
  for dependency in job.get("dependencies", []):
    parent = by_id[dependency]
    if not _job_is_complete(parent):
      raise ValueError("Required dependency is incomplete: {}".format(
          dependency))
  if _job_is_complete(job):
    print("[RESUME] {}".format(job["job_id"]))
    return
  manifest_path = _job_manifest_path(args, job)
  log_path = "{}.log".format(job["result_path"])
  started = time.time()
  manifest = {
      "job_id": job["job_id"], "job_fingerprint": job["job_fingerprint"],
      "status": "RUNNING", "started_unix": started,
      "command": job["command"], "log_path": log_path,
      "retry_count": 0, "atomic_manifest": True}
  _atomic_json(manifest_path, manifest)
  try:
    if job["kind"] == "variant_data":
      _execute_variant_data(args, job)
    elif job["kind"] == "identity":
      _execute_identity(args, job)
    else:
      _execute_subprocess(args, job, log_path)
    manifest.update({
        "status": "COMPLETED", "ended_unix": time.time(), "exit_code": 0,
        "result_fingerprint": finals_config.fingerprint_file(
            job["result_path"])})
  except Exception as error:
    manifest.update({
        "status": "FAILED", "ended_unix": time.time(), "exit_code": 1,
        "error": str(error), "traceback": traceback.format_exc()})
    _atomic_json(manifest_path, manifest)
    raise
  _atomic_json(manifest_path, manifest)
  print("[COMPLETED] {}".format(job["job_id"]))


def learned_comparability(args, plan):
  entries = []
  complete_by_policy = {}
  for policy in ("kleio_lite", "patterns_lite"):
    complete_by_policy[policy] = all(
        _job_is_complete(next(
            job for job in plan["jobs"]
            if job["job_id"] == "learned:train:{}:{}".format(
                workload, policy))) and
        _job_is_complete(next(
            job for job in plan["jobs"]
            if job["job_id"] == "learned:replay:{}:{}".format(
                workload, policy)))
        for workload in stage5_variants.WORKLOADS)
  for workload in stage5_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    config = finals_config.load_json(base["config"])
    for policy in ("kleio_lite", "patterns_lite"):
      train_job = next(
          job for job in plan["jobs"]
          if job["job_id"] == "learned:train:{}:{}".format(
              workload, policy))
      replay_job = next(
          job for job in plan["jobs"]
          if job["job_id"] == "learned:replay:{}:{}".format(
              workload, policy))
      completed = _job_is_complete(train_job) and _job_is_complete(replay_job)
      entries.append({
          "workload": workload, "policy": policy,
          "implementation_label": policy.replace("_", "-"),
          "same_train_valid_test_source": True,
          "training_reads_train_only": True,
          "valid_role": "not_required_by_fixed_training_algorithm",
          "test_role": "final_closed_loop_replay_only",
          "same_D": int(config["memory"]["dram_capacity_pages"]) == 64,
          "same_initial_state": True, "same_cost_model": True,
          "workload_bound_model": True, "test_tuning": False,
          "eligible": True,
          "included_in_main_table": (
              completed and complete_by_policy[policy]),
          "status": "COMPARABLE_COMPLETED" if completed else
                    "ELIGIBLE_NOT_RUN",
          "exclusion_reason": None if completed else (
              "Stage-5 isolated training/replay has not completed; excluded "
              "from result tables without blocking required baselines.")})
  payload = {
      "schema_version": "capd_finals_v3_stage5_learned_comparability_1",
      "contract_id": finals_config.CONTRACT_ID,
      "test_used_for_selection": False, "entries": entries}
  _atomic_json(
      os.path.join(args.output_root, "learned_baseline_comparability.json"),
      payload)
  return payload


def _collect_completed(plan, stage, kind=None):
  rows = []
  for job in plan["jobs"]:
    if job["stage"] != stage or (kind is not None and job["kind"] != kind):
      continue
    if job["required"] and not _job_is_complete(job):
      raise ValueError("Required job incomplete: {}".format(job["job_id"]))
    if _job_is_complete(job) and job["kind"] == "replay":
      rows.append(finals_config.load_json(job["result_path"]))
  return rows


def _write_markdown(path, title, lines):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output:
    output.write("# {}\n\n".format(title))
    for line in lines:
      output.write("{}\n".format(line))


def _boundary_crosswalk(args, main_summary):
  metrics_path = os.path.join(
      args.stage4_result_root, "distribution_metrics.csv")
  counts = {}
  with open(metrics_path, "r", encoding="utf-8", newline="") as input_file:
    for item in csv.DictReader(input_file):
      workload_counts = counts.setdefault(item["workload"], {})
      warning = item["warning"]
      workload_counts[warning] = workload_counts.get(warning, 0) + 1
  rows = []
  for workload in stage5_variants.WORKLOADS:
    capd = main_summary["workloads"][workload]["policies"]["qmap"][
        "weighted_access_cost"]
    rows.append({
        "workload": workload,
        "stage4_large_warning_count": counts.get(
            workload, {}).get("large", 0),
        "stage4_moderate_warning_count": counts.get(
            workload, {}).get("moderate", 0),
        "stage4_review_required": True,
        "capd_seed_cost_mean": capd["mean"],
        "capd_seed_cost_sample_stddev": capd["sample_stddev"],
        "best_external_improvement_percent": main_summary["workloads"][
            workload]["best_external_baseline"][
                "capd_improvement_percent"],
        "interpretation": "descriptive_association_only_no_causality",
    })
  stage5_results.write_csv(
      os.path.join(args.output_root, "stage4_boundary_crosswalk.csv"), rows)
  return rows


def summarize(args, plan):
  main_rows = _collect_completed(plan, "main", "replay")
  main_rows.extend(_collect_completed(
      plan, "learned-baselines", "replay"))
  main = stage5_results.summarize_main(main_rows)
  stage5_results.assert_finite_summary(main)
  stage5_results.write_csv(
      os.path.join(args.main_result_root, "stage5_main_results.csv"),
      main["rows"])
  _atomic_json(
      os.path.join(args.main_result_root, "stage5_main_summary.json"), main)
  _write_markdown(
      os.path.join(args.main_result_root, "stage5_main_report.md"),
      "CAPD 阶段5主实验报告",
      ["状态：正式结果已汇总；不得据此反向调参。",
       "主指标：weighted_access_cost。",
       "逐 workload、三模型 seed、Random 三回放 seed 均保留。",
       "阶段4 G11 REVIEW_REQUIRED 边界见 stage4_boundary_crosswalk.csv。"])

  ablation_rows = _collect_completed(plan, "ablations", "replay")
  ablation_summary = {"status": "SUMMARIZED", "workloads": {}}
  paired_rows = []
  for workload in stage5_variants.WORKLOADS:
    full = [
        row for row in main_rows if row["workload"] == workload and
        str(row["policy"]).lower() == "qmap"]
    ablation_summary["workloads"][workload] = {}
    for spec in stage5_variants.core_ablation_specs():
      variant = [
          row for row in ablation_rows
          if row["workload"] == workload and
          row.get("variant_id") == spec["variant_id"]]
      paired = stage5_results.paired_ablation_summary(full, variant)
      ablation_summary["workloads"][workload][spec["variant_id"]] = paired
      for item in paired["per_seed"]:
        paired_rows.append(dict(
            item, workload=workload, variant_id=spec["variant_id"],
            artifact_class="official"))
  stage5_results.write_csv(
      os.path.join(args.ablation_result_root, "stage5_ablation_results.csv"),
      paired_rows)
  _atomic_json(
      os.path.join(args.ablation_result_root, "stage5_ablation_summary.json"),
      ablation_summary)
  _write_markdown(
      os.path.join(args.ablation_result_root, "stage5_ablation_report.md"),
      "CAPD 阶段5组件消融报告",
      ["所有核心消融按相同模型 seed 与 Full 配对。",
       "均匀 selector 为 degenerate identity control，不伪装为性能实验。",
       "pilot 与 official 不混表。"])

  sensitivity_rows = _collect_completed(plan, "sensitivity", "replay")
  for row in ablation_rows:
    if (row.get("variant_id") == "no_filter_B8_K8" and
        int(row.get("model_seed", -1)) == 3136859):
      shared = dict(row)
      shared["variant_id"] = "sensitivity_B8"
      shared["shared_artifact_source"] = "no_filter_B8_K8"
      shared["evidence_tier"] = "single_seed_sensitivity"
      sensitivity_rows.append(shared)
  sensitivity = stage5_results.summarize_sensitivity(sensitivity_rows)
  sensitivity["default_full_reference"] = {
      "parameters": dict(stage5_variants.FULL_PARAMETERS),
      "source": "stage5_main CAPD three-seed Full results",
      "recomputed": False,
  }
  stage5_results.write_csv(
      os.path.join(
          args.sensitivity_result_root, "stage5_sensitivity_results.csv"),
      sensitivity_rows)
  _atomic_json(
      os.path.join(
          args.sensitivity_result_root, "stage5_sensitivity_summary.json"),
      sensitivity)
  _write_markdown(
      os.path.join(
          args.sensitivity_result_root, "stage5_sensitivity_report.md"),
      "CAPD 阶段5参数敏感性报告",
      ["网格：B/K/H/Hc/L；默认点复用 Full。",
       "非默认点首先按 canonical seed=3136859 报告。",
       "若改变论文主结论，必须补跑 42 与 2026。"])
  _boundary_crosswalk(args, main)
  learned_comparability(args, plan)
  run_manifest = {
      "schema_version": "capd_finals_v3_stage5_run_manifest_1",
      "contract_id": finals_config.CONTRACT_ID,
      "status": STAGE5_STATUS,
      "server_gate_ready": True,
      "required_jobs": plan["counts"]["required_experiment_jobs"],
      "completed_required_jobs": sum(
          1 for job in plan["jobs"] if job["required"] and
          _job_is_complete(job)),
      "test_used_for_selection": False,
      "historical_capd_comparison": False,
      "stage6_entered": False,
      "outputs": list(REQUIRED_OUTPUTS)}
  _atomic_json(os.path.join(args.output_root, "run_manifest.json"), run_manifest)


def build_parser():
  parser = argparse.ArgumentParser(description="CAPD stage-5 orchestrator.")
  parser.add_argument("--stage", choices=STAGES, required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument("--job-id", default=None)
  parser.add_argument("--execute", action="store_true",
                      help="Execute all jobs in the selected stage.")
  parser.add_argument("--dry-run", action="store_true")
  parser.add_argument(
      "--artifact-root",
      default="dataset/jsonl/finals_v3_official")
  parser.add_argument(
      "--stage3-ablation-csv",
      default=("outputs/results/finals_v3_official/stage3_selector/"
               "stage3_ablation.csv"))
  parser.add_argument(
      "--stage4-checkpoint-root",
      default=("outputs/checkpoints/finals_v3_official/"
               "stage4_reranker"))
  parser.add_argument(
      "--stage4-result-root",
      default="outputs/results/finals_v3_official/stage4_audits")
  parser.add_argument(
      "--output-root",
      default="outputs/results/finals_v3_official/stage5_main")
  parser.add_argument(
      "--main-result-root",
      default="outputs/results/finals_v3_official/stage5_main")
  parser.add_argument(
      "--ablation-data-root",
      default="dataset/jsonl/finals_v3_official/stage5_ablation")
  parser.add_argument(
      "--ablation-checkpoint-root",
      default="outputs/checkpoints/finals_v3_official/stage5_ablation")
  parser.add_argument(
      "--ablation-result-root",
      default="outputs/results/finals_v3_official/stage5_ablation")
  parser.add_argument(
      "--sensitivity-data-root",
      default="dataset/jsonl/finals_v3_official/stage5_sensitivity")
  parser.add_argument(
      "--sensitivity-checkpoint-root",
      default="outputs/checkpoints/finals_v3_official/stage5_sensitivity")
  parser.add_argument(
      "--sensitivity-result-root",
      default="outputs/results/finals_v3_official/stage5_sensitivity")
  parser.add_argument(
      "--learned-result-root",
      default="outputs/results/finals_v3_official/stage5_learned_baselines")
  return parser


def _resolve_paths(args):
  args.repo_root = os.path.abspath(args.repo_root)
  for name in (
      "artifact_root", "stage3_ablation_csv", "stage4_checkpoint_root",
      "stage4_result_root", "output_root", "main_result_root",
      "ablation_data_root", "ablation_checkpoint_root",
      "ablation_result_root", "sensitivity_data_root",
      "sensitivity_checkpoint_root", "sensitivity_result_root",
      "learned_result_root"):
    value = getattr(args, name)
    if not os.path.isabs(value):
      value = os.path.join(args.repo_root, value)
    setattr(args, name, os.path.abspath(value))


def _run_stage_jobs(args, plan, stage):
  selected = [job for job in plan["jobs"] if job["stage"] == stage]
  if args.job_id:
    selected = [job for job in selected if job["job_id"] == args.job_id]
    if len(selected) != 1:
      raise ValueError("Unknown job id for {}: {}".format(
          stage, args.job_id))
  elif not args.execute:
    print("[PLAN ONLY] {} jobs; pass --execute or --job-id.".format(
        len(selected)))
    return
  for job in selected:
    if args.dry_run:
      print("[DRY RUN] {} {}".format(job["job_id"], job["command"]))
    else:
      execute_job(args, plan, job)


def main():
  args = build_parser().parse_args()
  _resolve_paths(args)
  plan = build_execution_plan(args)
  plan_path = os.path.join(args.output_root, "execution_plan.json")
  if args.stage in ("plan", "all") and not args.dry_run:
    _atomic_json(plan_path, plan)
  if args.stage == "plan":
    print(json.dumps(plan["counts"], indent=2, sort_keys=True))
    for job in plan["jobs"]:
      print("{} {}".format(job["job_id"], job["command"]))
    return
  if args.stage in ("audit-inputs", "all"):
    audit_inputs(args)
  if args.stage in ("main", "all"):
    _run_stage_jobs(args, plan, "main")
  if args.stage in ("learned-baselines", "all"):
    learned_comparability(args, plan)
    _run_stage_jobs(args, plan, "learned-baselines")
  if args.stage in ("ablations", "all"):
    _run_stage_jobs(args, plan, "ablations")
  if args.stage in ("sensitivity", "all"):
    _run_stage_jobs(args, plan, "sensitivity")
  if args.stage in ("summarize", "all"):
    summarize(args, plan)


if __name__ == "__main__":
  main()
