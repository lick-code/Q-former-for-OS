#!/usr/bin/env python3
# coding=utf-8
"""CAPD stage-6 robustness, overhead, and system-evidence orchestrator.

Planning, auditing, and summarization are pure Python.  GPU-backed profiling
and capacity retraining are opt-in via ``--execute`` or a concrete
``--job-id`` and use atomic per-job manifests for resumability.
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
from qmap import stage6_results
from qmap import stage6_variants


STAGE6_STATUS = "STAGE6_IMPLEMENTED_UNVERIFIED"
STAGES = (
    "audit-inputs", "plan", "profile", "capacity", "summarize", "all")
REQUIRED_OUTPUTS = (
    "input_audit.json", "execution_plan.json",
    "stage6_profile_results.csv", "stage6_profile_summary.json",
    "stage6_profile_report.md", "stage6_capacity_results.csv",
    "stage6_capacity_summary.json", "stage6_capacity_report.md",
    "stage6_cost_robustness.csv", "stage6_cost_robustness.json",
    "stage6_cost_robustness_report.md", "stage6_rw_robustness.csv",
    "stage6_rw_robustness.json", "stage6_rw_robustness_report.md",
    "stage6_system_platform_validation.json",
    "stage6_system_platform_validation_report.md",
    "run_manifest.json")


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


def _write_csv(path, rows):
  rows = list(rows)
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  fields = sorted({key for row in rows for key in row})
  with open(path, "w", encoding="utf-8", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)


def _write_markdown(path, title, lines):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as output:
    output.write("# {}\n\n".format(title))
    for line in lines:
      output.write("{}\n".format(line))


def _display_command(argv):
  return " ".join(shlex.quote(value) for value in argv)


def _git_commit(repo_root):
  try:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        universal_newlines=True).strip()
  except (OSError, subprocess.CalledProcessError):
    return "unknown"


def _code_fingerprint(repo_root):
  paths = (
      "scripts/run_capd_stage6.py", "qmap/stage6_results.py",
      "qmap/stage6_variants.py", "qmap/finals_config.py",
      "qmap/finals_generator.py", "qmap/qmap_train.py",
      "qmap/qmap_eval.py", "policy_learning/cache_model/model.py")
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def _base_artifacts(args, workload):
  root = os.path.join(args.artifact_root, workload, "B64")
  return {
      "config": os.path.join(root, "resolved_config.json"),
      "selector": os.path.join(root, "selector_params.json"),
      "train": os.path.join(root, "train.jsonl"),
      "valid": os.path.join(root, "valid.jsonl"),
  }


def _config_bound_inputs(config_path, repo_root):
  """Returns source-manifest and split paths sealed by a resolved config."""
  if not os.path.isfile(config_path):
    return []
  config = finals_config.load_json(config_path)
  data = config.get("data", {})
  paths = []
  for key in (
      "source_manifest", "train_trace", "valid_trace", "test_trace"):
    value = data.get(key)
    if value:
      paths.append(
          value if os.path.isabs(value) else os.path.join(repo_root, value))
  return paths


def _capacity_roots(args, workload, capacity):
  variant_id = "capacity_D{}".format(capacity)
  data = os.path.join(args.capacity_data_root, variant_id, workload)
  checkpoint = os.path.join(
      args.capacity_checkpoint_root, variant_id, workload)
  result = os.path.join(
      args.capacity_result_root, "raw", variant_id, workload)
  return {"data": data, "checkpoint": checkpoint, "result": result}


def _profile_jobs(args):
  jobs = []
  for workload in stage6_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    for seed in stage6_variants.MODEL_SEEDS:
      checkpoint = os.path.join(
          args.stage4_checkpoint_root, workload,
          "seed_{}".format(seed), "qmap_best.pth")
      result = os.path.join(
          args.profile_result_root, "raw", workload, "qmap",
          "seed_{}.json".format(seed))
      jobs.append({
          "job_id": "profile:{}:qmap:{}".format(workload, seed),
          "stage": "profile", "kind": "replay", "required": True,
          "workload": workload, "policy": "qmap", "model_seed": seed,
          "result_path": result, "dependencies": [],
          "resource": "single_gpu_profile",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", base["config"],
              "--selector_params", base["selector"], "--policy", "qmap",
              "--checkpoint", checkpoint, "--stage6_profile",
              "--stage6_warmup_decisions", str(args.profile_warmup),
              "--json_output", result]})
    for replay_seed in stage6_variants.RANDOM_REPLAY_SEEDS:
      result = os.path.join(
          args.profile_result_root, "raw", workload, "random",
          "seed_{}.json".format(replay_seed))
      jobs.append({
          "job_id": "profile:{}:random:{}".format(workload, replay_seed),
          "stage": "profile", "kind": "replay", "required": True,
          "workload": workload, "policy": "random",
          "replay_seed": replay_seed, "result_path": result,
          "dependencies": [], "resource": "cpu_profile",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", base["config"],
              "--policy", "random", "--stage5_replay_seed",
              str(replay_seed), "--stage6_profile",
              "--stage6_warmup_decisions", str(args.profile_warmup),
              "--json_output", result]})
    for policy in ("lru", "lfu", "clock"):
      result = os.path.join(
          args.profile_result_root, "raw", workload, policy, "run.json")
      jobs.append({
          "job_id": "profile:{}:{}:deterministic".format(workload, policy),
          "stage": "profile", "kind": "replay", "required": True,
          "workload": workload, "policy": policy,
          "result_path": result, "dependencies": [],
          "resource": "cpu_profile",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", base["config"],
              "--policy", policy, "--stage6_profile",
              "--stage6_warmup_decisions", str(args.profile_warmup),
              "--json_output", result]})
  return jobs


def _capacity_jobs(args):
  jobs = []
  for capacity in stage6_variants.CAPACITIES:
    variant_id = "capacity_D{}".format(capacity)
    for workload in stage6_variants.WORKLOADS:
      roots = _capacity_roots(args, workload, capacity)
      data_job = "capacity:data:{}:{}".format(variant_id, workload)
      jobs.append({
          "job_id": data_job, "stage": "capacity", "kind": "capacity_data",
          "required": True, "workload": workload, "capacity": capacity,
          "variant_id": variant_id,
          "result_path": os.path.join(roots["data"], "variant_manifest.json"),
          "dependencies": [], "resource": "cpu_memory_bound",
          "argv": [
              "python3", "scripts/run_capd_stage6.py", "--stage", "capacity",
              "--job-id", data_job]})
      for seed in stage6_variants.MODEL_SEEDS:
        checkpoint_dir = os.path.join(
            roots["checkpoint"], "seed_{}".format(seed))
        train_job = "capacity:train:{}:{}:{}".format(
            variant_id, workload, seed)
        config = os.path.join(roots["data"], "resolved_config.json")
        selector = os.path.join(roots["data"], "selector_params.json")
        jobs.append({
            "job_id": train_job, "stage": "capacity", "kind": "train",
            "required": True, "workload": workload, "capacity": capacity,
            "variant_id": variant_id, "model_seed": seed,
            "result_path": os.path.join(
                checkpoint_dir, "checkpoint_manifest.json"),
            "dependencies": [data_job], "resource": "single_gpu",
            "argv": [
                "python3", "qmap/qmap_train.py", "--config", config,
                "--selector_params", selector, "--train_data",
                os.path.join(roots["data"], "train.jsonl"),
                "--valid_data", os.path.join(roots["data"], "valid.jsonl"),
                "--output_dir", checkpoint_dir, "--seed", str(seed)]})
        result = os.path.join(
            roots["result"], "qmap", "seed_{}.json".format(seed))
        jobs.append({
            "job_id": "capacity:replay:{}:{}:qmap:{}".format(
                variant_id, workload, seed),
            "stage": "capacity", "kind": "replay", "required": True,
            "workload": workload, "capacity": capacity,
            "variant_id": variant_id, "policy": "qmap", "model_seed": seed,
            "result_path": result, "dependencies": [train_job],
            "resource": "gpu_or_cpu_inference",
            "argv": [
                "python3", "qmap/qmap_eval.py", "--config", config,
                "--selector_params", selector, "--policy", "qmap",
                "--checkpoint", os.path.join(
                    checkpoint_dir, "qmap_best.pth"),
                "--json_output", result]})
      for replay_seed in stage6_variants.RANDOM_REPLAY_SEEDS:
        result = os.path.join(
            roots["result"], "random",
            "seed_{}.json".format(replay_seed))
        jobs.append({
            "job_id": "capacity:replay:{}:{}:random:{}".format(
                variant_id, workload, replay_seed),
            "stage": "capacity", "kind": "replay", "required": True,
            "workload": workload, "capacity": capacity,
            "variant_id": variant_id, "policy": "random",
            "replay_seed": replay_seed, "result_path": result,
            "dependencies": [data_job], "resource": "cpu",
            "argv": [
                "python3", "qmap/qmap_eval.py", "--config",
                os.path.join(roots["data"], "resolved_config.json"),
                "--policy", "random", "--stage5_replay_seed",
                str(replay_seed), "--json_output", result]})
      for policy in ("lru", "lfu", "clock"):
        result = os.path.join(roots["result"], policy, "run.json")
        jobs.append({
            "job_id": "capacity:replay:{}:{}:{}:deterministic".format(
                variant_id, workload, policy),
            "stage": "capacity", "kind": "replay", "required": True,
            "workload": workload, "capacity": capacity,
            "variant_id": variant_id, "policy": policy,
            "result_path": result, "dependencies": [data_job],
            "resource": "cpu",
            "argv": [
                "python3", "qmap/qmap_eval.py", "--config",
                os.path.join(roots["data"], "resolved_config.json"),
                "--policy", policy, "--json_output", result]})
  return jobs


def build_execution_plan(args):
  jobs = _profile_jobs(args) + _capacity_jobs(args)
  code_fingerprint = _code_fingerprint(args.repo_root)
  by_id = {}
  for job in jobs:
    job["command"] = _display_command(job["argv"])
    input_paths = []
    if not job["dependencies"]:
      if job["kind"] == "capacity_data":
        input_paths.extend(_base_artifacts(
            args, job["workload"]).values())
      else:
        for flag in ("--config", "--selector_params", "--checkpoint"):
          if flag in job["argv"]:
            input_paths.append(job["argv"][job["argv"].index(flag) + 1])
    for path in list(input_paths):
      if os.path.basename(path) == "resolved_config.json":
        input_paths.extend(_config_bound_inputs(path, args.repo_root))
    inputs = {}
    for path in dict.fromkeys(input_paths):
      absolute = path if os.path.isabs(path) else os.path.join(
          args.repo_root, path)
      inputs[_portable(absolute, args.repo_root)] = (
          finals_config.fingerprint_file(absolute)
          if os.path.isfile(absolute) else None)
    dependencies = {
        dependency: by_id[dependency]["job_fingerprint"]
        for dependency in job["dependencies"]}
    job["input_fingerprints"] = inputs
    job["dependency_fingerprints"] = dependencies
    job["job_fingerprint"] = finals_config.fingerprint_value({
        "job": {
            key: job.get(key) for key in (
                "job_id", "stage", "kind", "workload", "capacity",
                "variant_id", "policy", "model_seed", "replay_seed",
                "result_path", "dependencies", "command")},
        "inputs": inputs, "dependencies": dependencies,
        "code_fingerprint": code_fingerprint})
    by_id[job["job_id"]] = job
  counts = {
      "profile_replay_jobs": len([
          job for job in jobs if job["stage"] == "profile"]),
      "capacity_data_jobs": len([
          job for job in jobs if job["kind"] == "capacity_data"]),
      "capacity_training_jobs": len([
          job for job in jobs if job["kind"] == "train"]),
      "capacity_replay_jobs": len([
          job for job in jobs
          if job["stage"] == "capacity" and job["kind"] == "replay"]),
  }
  counts["required_jobs"] = len(jobs)
  return {
      "schema_version": "capd_finals_v3_stage6_plan_1",
      "contract_id": finals_config.CONTRACT_ID,
      "stage_status": STAGE6_STATUS,
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": code_fingerprint,
      "stage5_required_status": "STAGE5_VERIFIED",
      "test_used_for_selection": False,
      "capacities": [64] + list(stage6_variants.CAPACITIES),
      "profile_warmup_decisions": args.profile_warmup,
      "counts": counts, "jobs": jobs,
  }


def audit_inputs(args):
  checks = []

  def check(name, condition, detail):
    checks.append({
        "name": name, "status": "PASS" if condition else "FAIL",
        "detail": detail})

  stage5_manifest_path = os.path.join(
      args.stage5_result_root, "run_manifest.json")
  check("stage5_manifest_exists", os.path.isfile(stage5_manifest_path),
        _portable(stage5_manifest_path, args.repo_root))
  if os.path.isfile(stage5_manifest_path):
    stage5 = finals_config.load_json(stage5_manifest_path)
    check("stage5_verified", stage5.get("status") == "STAGE5_VERIFIED",
          str(stage5.get("status")))
    check("stage5_complete",
          stage5.get("completed_required_jobs") ==
          stage5.get("required_jobs") == 348,
          "{}/{}".format(stage5.get("completed_required_jobs"),
                         stage5.get("required_jobs")))
    check("stage5_test_not_selected",
          stage5.get("test_used_for_selection") is False,
          str(stage5.get("test_used_for_selection")))

  main_summary = os.path.join(
      args.stage5_result_root, "stage5_main_summary.json")
  check("stage5_main_summary_exists", os.path.isfile(main_summary),
        _portable(main_summary, args.repo_root))
  checkpoint_count = 0
  for workload in stage6_variants.WORKLOADS:
    base = _base_artifacts(args, workload)
    for name, path in base.items():
      check("{}_{}_exists".format(workload, name), os.path.isfile(path),
            _portable(path, args.repo_root))
    if os.path.isfile(base["config"]):
      try:
        config = finals_config.load_json(base["config"])
        finals_config.validate_config(config, require_resolved=True)
        check("{}_config_semantics".format(workload), True,
              "resolved config validates")
        bound = {
            key: (
                value if os.path.isabs(value) else
                os.path.join(args.repo_root, value))
            for key, value in config["data"].items()
            if key in (
                "source_manifest", "train_trace", "valid_trace",
                "test_trace")}
        for name, path in sorted(bound.items()):
          exists = os.path.isfile(path)
          check("{}_{}_exists".format(workload, name), exists,
                _portable(path, args.repo_root))
          if name.endswith("_trace") and exists:
            split = name[:-len("_trace")]
            expected = config["data"]["split_fingerprints"][split]
            actual = finals_config.fingerprint_file(path)
            check("{}_{}_fingerprint".format(workload, split),
                  actual == expected,
                  "expected={} actual={}".format(expected, actual))
      except Exception as error:
        check("{}_config_semantics".format(workload), False, str(error))
    report = os.path.join(args.data_report_root, "{}.json".format(workload))
    check("{}_data_report".format(workload), os.path.isfile(report),
          _portable(report, args.repo_root))
    if os.path.isfile(report):
      payload = finals_config.load_json(report)
      check("{}_data_passed".format(workload),
            payload.get("status") == "PASSED",
            str(payload.get("status")))
    for seed in stage6_variants.MODEL_SEEDS:
      checkpoint = os.path.join(
          args.stage4_checkpoint_root, workload,
          "seed_{}".format(seed), "qmap_best.pth")
      manifest = os.path.join(
          args.stage4_checkpoint_root, workload,
          "seed_{}".format(seed), "checkpoint_manifest.json")
      valid = os.path.isfile(checkpoint) and os.path.isfile(manifest)
      check("checkpoint_{}_{}".format(workload, seed), valid,
            _portable(checkpoint, args.repo_root))
      checkpoint_count += int(valid)
  passed = all(item["status"] == "PASS" for item in checks)
  result = {
      "schema_version": "capd_finals_v3_stage6_input_audit_1",
      "contract_id": finals_config.CONTRACT_ID,
      "stage_status": STAGE6_STATUS,
      "status": "PASSED" if passed else "FAILED",
      "expected_checkpoint_count": 9,
      "checkpoint_count": checkpoint_count,
      "test_used_for_selection": False,
      "checks": checks,
  }
  path = os.path.join(args.output_root, "input_audit.json")
  _atomic_json(path, result)
  if not passed:
    raise ValueError("Stage-6 input audit failed; see {}".format(path))
  return result


def _job_manifest_path(job):
  return "{}.job_manifest.json".format(job["result_path"])


def _job_is_complete(job):
  path = _job_manifest_path(job)
  if not os.path.isfile(path) or not os.path.isfile(job["result_path"]):
    return False
  manifest = finals_config.load_json(path)
  return (
      manifest.get("status") == "COMPLETED" and
      manifest.get("job_fingerprint") == job["job_fingerprint"] and
      os.path.getsize(job["result_path"]) > 0 and
      manifest.get("result_fingerprint") ==
      finals_config.fingerprint_file(job["result_path"]))


def _execute_capacity_data(args, job):
  roots = _capacity_roots(args, job["workload"], job["capacity"])
  os.makedirs(roots["data"], exist_ok=True)
  base = _base_artifacts(args, job["workload"])
  base_config = finals_config.load_config(
      base["config"], require_resolved=True, project_root=args.repo_root)
  config = stage6_variants.build_capacity_config(
      base_config, job["capacity"])
  config_path = os.path.join(roots["data"], "resolved_config.json")
  selector_path = os.path.join(roots["data"], "selector_params.json")
  train_path = os.path.join(roots["data"], "train.jsonl")
  valid_path = os.path.join(roots["data"], "valid.jsonl")
  validation_path = os.path.join(
      roots["data"], "selector_validation_samples.jsonl")
  summary_path = os.path.join(roots["data"], "generator_summary.json")
  finals_config.write_json(config_path, config)
  finals_generator.fit_selector_and_generate(argparse.Namespace(
      config=config_path, selector_output=selector_path,
      validation_samples_output=validation_path, train_output=train_path,
      valid_output=valid_path, summary_output=summary_path, page_shift=None))
  selector = finals_config.load_json(selector_path)
  manifest = {
      "schema_version": "capd_finals_v3_stage6_capacity_data_1",
      "contract_id": finals_config.CONTRACT_ID,
      "stage6_variant": dict(config["stage6_variant"]),
      "workload": job["workload"], "capacity": job["capacity"],
      "config_fingerprint": finals_config.config_fingerprint(config),
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "jsonl_fingerprints": {
          "train": finals_config.fingerprint_file(train_path),
          "valid": finals_config.fingerprint_file(valid_path)},
      "split_fingerprints": dict(config["data"]["split_fingerprints"]),
      "test_trace_opened": False, "test_used_for_selection": False,
      "run_status": "COMPLETED",
  }
  _atomic_json(job["result_path"], manifest)


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
  if job["kind"] == "replay":
    result = finals_config.load_json(job["result_path"])
    result.update({
        "workload": job["workload"], "run_status": "COMPLETED",
        "artifact_class": "official", "test_used_for_selection": False,
    })
    if job.get("capacity") is not None:
      result["stage6_variant_id"] = job["variant_id"]
    if job.get("model_seed") is not None:
      result["model_seed"] = int(job["model_seed"])
    if job.get("replay_seed") is not None:
      result["replay_seed"] = int(job["replay_seed"])
    _atomic_json(job["result_path"], result)


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
      "retry_count": 0, "atomic_manifest": True}
  _atomic_json(manifest_path, manifest)
  try:
    if job["kind"] == "capacity_data":
      _execute_capacity_data(args, job)
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


def _collect_rows(plan, stage):
  rows = []
  for job in plan["jobs"]:
    if job["stage"] != stage or job["kind"] != "replay":
      continue
    if not _job_is_complete(job):
      raise ValueError("Required job incomplete: {}".format(job["job_id"]))
    rows.append(finals_config.load_json(job["result_path"]))
  return rows


def summarize(args, plan):
  incomplete = [
      job["job_id"] for job in plan["jobs"] if not _job_is_complete(job)]
  if incomplete:
    raise ValueError(
        "Cannot summarize Stage 6 with incomplete required jobs: {}"
        .format(", ".join(incomplete[:10])))
  main = finals_config.load_json(os.path.join(
      args.stage5_result_root, "stage5_main_summary.json"))
  profile_rows = _collect_rows(plan, "profile")
  profile = stage6_results.summarize_profiles(
      profile_rows, require_qmap_cuda=True)
  _write_csv(
      os.path.join(args.output_root, "stage6_profile_results.csv"),
      profile["throughput_rows"])
  _atomic_json(
      os.path.join(args.output_root, "stage6_profile_summary.json"), profile)
  _write_markdown(
      os.path.join(args.output_root, "stage6_profile_report.md"),
      "CAPD 阶段6开销报告", [
          "延迟统计使用逐决策原始样本，而不是平均各运行的分位数。",
          "QMAP 在组件边界执行设备同步；初始 {} 次决策不进入分位数。"
          .format(args.profile_warmup),
          "报告 selector、Transformer、Cross-Attention scorer、完整决策、"
          "吞吐和内存峰值。",
          "吞吐下降以最快经典基线为参照；迁移和NVM写入变化分别以"
          "对应计数最低的经典基线为参照。"])

  capacity_rows = [
      row for row in main["rows"]
      if str(row["policy"]).lower() in (
          "qmap", "random", "lru", "lfu", "clock")]
  capacity_rows.extend(_collect_rows(plan, "capacity"))
  capacity = stage6_results.summarize_capacity(capacity_rows)
  stage5_results.write_csv(
      os.path.join(args.output_root, "stage6_capacity_results.csv"),
      capacity_rows)
  _atomic_json(
      os.path.join(args.output_root, "stage6_capacity_summary.json"),
      capacity)
  _write_markdown(
      os.path.join(args.output_root, "stage6_capacity_report.md"),
      "CAPD 阶段6容量稳健性报告", [
          "D=64 引用 Stage 5；本矩阵正式重训并评估 D=128/256。",
          "每个容量、每个 workload 保留三模型 seed、Random 三回放 seed"
          "以及 LRU/LFU/CLOCK。",
          "容量变化不改变 CAPD-MIC-1.0 方法语义。"])

  cost = stage6_results.summarize_cost_robustness(main["rows"])
  _write_csv(
      os.path.join(args.output_root, "stage6_cost_robustness.csv"),
      cost["rows"])
  _atomic_json(
      os.path.join(args.output_root, "stage6_cost_robustness.json"), cost)
  _write_markdown(
      os.path.join(args.output_root, "stage6_cost_robustness_report.md"),
      "CAPD 阶段6成本权重稳健性报告", [
          "只从 Stage 5 official 原始计数离线重加权，不重新选择模型。",
          "DRAM 读写成本保持相同，因此现有计数足以精确重算。",
          "覆盖 official、较低/较高 NVM 写成本和较高迁移成本。"])

  reports = {
      workload: finals_config.load_json(os.path.join(
          args.data_report_root, "{}.json".format(workload)))
      for workload in stage6_variants.WORKLOADS}
  rw = stage6_results.summarize_natural_rw(reports, main)
  _write_csv(
      os.path.join(args.output_root, "stage6_rw_robustness.csv"), rw["rows"])
  _atomic_json(
      os.path.join(args.output_root, "stage6_rw_robustness.json"), rw)
  _write_markdown(
      os.path.join(args.output_root, "stage6_rw_robustness_report.md"),
      "CAPD 阶段6自然读写比例稳健性报告", [
          "使用三个 official workload 的真实 Trace 读写比例。",
          "该结果是跨 workload 描述性证据，不解释为受控因果干预。"])

  system_platform = {
      "schema_version": "capd_finals_v3_stage6_system_platform_1",
      "status": "CONDITIONAL_NOT_RUN",
      "evidence_available": False,
      "software_results_relabelled_as_hardware": False,
      "limitation": (
          "No real hybrid-memory platform was provided for this run. "
          "Software profiling and trace-driven evaluation remain the "
          "available Stage-6 evidence."),
  }
  _atomic_json(
      os.path.join(
          args.output_root, "stage6_system_platform_validation.json"),
      system_platform)
  _write_markdown(
      os.path.join(
          args.output_root,
          "stage6_system_platform_validation_report.md"),
      "CAPD 阶段6真实系统平台验证", [
          "状态：`CONDITIONAL_NOT_RUN`。",
          "本次未提供真实混合内存平台；软件测量没有被重新标记为硬件实测。",
          "该限制必须在论文和最终报告中披露。"])

  manifest = {
      "schema_version": "capd_finals_v3_stage6_run_manifest_1",
      "contract_id": finals_config.CONTRACT_ID,
      "status": STAGE6_STATUS,
      "stage5_status": "STAGE5_VERIFIED",
      "required_jobs": plan["counts"]["required_jobs"],
      "completed_required_jobs": len(plan["jobs"]),
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "system_platform_validation": system_platform["status"],
      "server_gate_ready": True,
      "outputs": list(REQUIRED_OUTPUTS),
  }
  missing_outputs = [
      name for name in REQUIRED_OUTPUTS if name != "run_manifest.json" and
      (not os.path.isfile(os.path.join(args.output_root, name)) or
       os.path.getsize(os.path.join(args.output_root, name)) <= 0)]
  if missing_outputs:
    raise ValueError(
        "Stage-6 output bundle is incomplete: {}".format(missing_outputs))
  _atomic_json(os.path.join(args.output_root, "run_manifest.json"), manifest)
  return manifest


def build_parser():
  parser = argparse.ArgumentParser(description="CAPD stage-6 orchestrator.")
  parser.add_argument("--stage", choices=STAGES, required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument("--job-id", default=None)
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--dry-run", action="store_true")
  parser.add_argument("--profile-warmup", type=int, default=20)
  parser.add_argument(
      "--artifact-root", default="dataset/jsonl/finals_v3_official")
  parser.add_argument(
      "--stage4-checkpoint-root",
      default="outputs/checkpoints/finals_v3_official/stage4_reranker")
  parser.add_argument(
      "--stage5-result-root",
      default="outputs/results/finals_v3_official/stage5_main")
  parser.add_argument(
      "--data-report-root",
      default="dataset/metadata/finals_v3_official/reports")
  parser.add_argument(
      "--capacity-data-root",
      default="dataset/jsonl/finals_v3_official/stage6_capacity")
  parser.add_argument(
      "--capacity-checkpoint-root",
      default="outputs/checkpoints/finals_v3_official/stage6_capacity")
  parser.add_argument(
      "--capacity-result-root",
      default="outputs/results/finals_v3_official/stage6_capacity")
  parser.add_argument(
      "--profile-result-root",
      default="outputs/results/finals_v3_official/stage6_profile")
  parser.add_argument(
      "--output-root",
      default="outputs/results/finals_v3_official/stage6")
  return parser


def _resolve_paths(args):
  args.repo_root = os.path.abspath(args.repo_root)
  if args.profile_warmup < 0:
    raise ValueError("--profile-warmup must be non-negative.")
  for name in (
      "artifact_root", "stage4_checkpoint_root", "stage5_result_root",
      "data_report_root", "capacity_data_root", "capacity_checkpoint_root",
      "capacity_result_root", "profile_result_root", "output_root"):
    value = getattr(args, name)
    if not os.path.isabs(value):
      value = os.path.join(args.repo_root, value)
    setattr(args, name, os.path.abspath(value))


def _run_jobs(args, plan, stage):
  selected = [job for job in plan["jobs"] if job["stage"] == stage]
  if args.job_id:
    selected = [job for job in selected if job["job_id"] == args.job_id]
    if len(selected) != 1:
      raise ValueError("Unknown {} job: {}".format(stage, args.job_id))
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
  if args.stage in ("plan", "all") and not args.dry_run:
    _atomic_json(
        os.path.join(args.output_root, "execution_plan.json"), plan)
  if args.stage == "plan":
    print(json.dumps(plan["counts"], indent=2, sort_keys=True))
    for job in plan["jobs"]:
      print("{} {}".format(job["job_id"], job["command"]))
    return
  if args.stage in ("audit-inputs", "all"):
    audit_inputs(args)
  if args.stage in ("profile", "all"):
    _run_jobs(args, plan, "profile")
  if args.stage in ("capacity", "all"):
    _run_jobs(args, plan, "capacity")
  if args.stage in ("summarize", "all"):
    summarize(args, plan)


if __name__ == "__main__":
  main()
