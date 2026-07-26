#!/usr/bin/env python3
# coding=utf-8
"""Plan, execute, and summarize the CAPD post-hoc bridge diagnostic.

This runner never overwrites Stage-5 or Stage-6 artifacts.  Three current
engine cases are freshly generated/trained/replayed; the two endpoints import
immutable legacy-published and Stage-5 Full evidence.
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

from qmap import bridge_results
from qmap import bridge_variants
from qmap import finals_config
from qmap import finals_generator


BRIDGE_STATUS = "BRIDGE_IMPLEMENTED_UNVERIFIED"
STAGES = ("audit-inputs", "plan", "run", "summarize", "all")
SUMMARY_CASE_ORDER = (
    "legacy_published_D16_B8K8",
    "legacy_current_identity_D16_B8K8",
    "legacy_current_selector_D16_B16K8",
    "official_current_selector_D16_B16K8",
    "official_current_full_D64_B64K8",
)


def _portable(path, root):
  path = os.path.abspath(path)
  relative = os.path.relpath(path, root)
  if relative == os.pardir or relative.startswith(os.pardir + os.sep):
    return path
  return relative.replace(os.sep, "/")


def _absolute(root, path):
  return path if os.path.isabs(path) else os.path.join(root, path)


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
      "scripts/run_capd_bridge.py", "qmap/bridge_variants.py",
      "qmap/bridge_results.py", "qmap/finals_config.py",
      "qmap/finals_generator.py", "qmap/qmap_train.py",
      "qmap/qmap_eval.py", "qmap/candidate_filter.py",
      "policy_learning/cache_model/model.py")
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def _case_roots(args, case_id):
  return {
      "data": os.path.join(args.data_root, case_id),
      "checkpoint": os.path.join(args.checkpoint_root, case_id),
      "result": os.path.join(args.output_root, "raw", "cases", case_id),
  }


def _baseline_root(args, source_id, capacity):
  return os.path.join(
      args.output_root, "raw", "baselines",
      "{}_D{}".format(source_id, capacity))


def _case_by_id(case_id):
  matches = [
      case for case in bridge_variants.all_cases()
      if case["case_id"] == case_id]
  if len(matches) != 1:
    raise ValueError("Unknown bridge case: {}".format(case_id))
  return matches[0]


def _base_config_path(args):
  return os.path.join(
      args.artifact_root, bridge_variants.WORKLOAD, "B64",
      "resolved_config.json")


def _build_jobs(args):
  jobs = []
  for case in bridge_variants.COMPUTE_CASES:
    case_id = case["case_id"]
    roots = _case_roots(args, case_id)
    data_job_id = "bridge:data:{}".format(case_id)
    data_manifest = os.path.join(roots["data"], "variant_manifest.json")
    config_path = os.path.join(roots["data"], "resolved_config.json")
    selector_path = os.path.join(roots["data"], "selector_params.json")
    train_path = os.path.join(roots["data"], "train.jsonl")
    valid_path = os.path.join(roots["data"], "valid.jsonl")
    jobs.append({
        "job_id": data_job_id, "stage": "run", "kind": "data",
        "case_id": case_id, "source_id": case["source_id"],
        "required": True, "dependencies": [],
        "result_path": data_manifest, "resource": "cpu_memory_bound",
        "argv": [
            "python3", "scripts/run_capd_bridge.py", "--stage", "run",
            "--job-id", data_job_id]})
    for seed in bridge_variants.MODEL_SEEDS:
      checkpoint_dir = os.path.join(
          roots["checkpoint"], "seed_{}".format(seed))
      checkpoint_manifest = os.path.join(
          checkpoint_dir, "checkpoint_manifest.json")
      train_job_id = "bridge:train:{}:{}".format(case_id, seed)
      jobs.append({
          "job_id": train_job_id, "stage": "run", "kind": "train",
          "case_id": case_id, "source_id": case["source_id"],
          "model_seed": seed, "required": True,
          "dependencies": [data_job_id],
          "result_path": checkpoint_manifest, "resource": "single_gpu_train",
          "argv": [
              "python3", "qmap/qmap_train.py",
              "--config", config_path,
              "--selector_params", selector_path,
              "--train_data", train_path, "--valid_data", valid_path,
              "--output_dir", checkpoint_dir, "--seed", str(seed)]})
      result_path = os.path.join(
          roots["result"], "qmap", "seed_{}.json".format(seed))
      replay_job_id = "bridge:replay:{}:qmap:{}".format(case_id, seed)
      jobs.append({
          "job_id": replay_job_id, "stage": "run", "kind": "replay",
          "case_id": case_id, "source_id": case["source_id"],
          "policy": "qmap", "model_seed": seed, "required": True,
          "dependencies": [train_job_id],
          "result_path": result_path, "resource": "single_gpu_replay",
          "argv": [
              "python3", "qmap/qmap_eval.py",
              "--config", config_path,
              "--selector_params", selector_path,
              "--policy", "qmap",
              "--checkpoint", os.path.join(checkpoint_dir, "qmap_best.pth"),
              "--bridge_diagnostics", "--json_output", result_path]})

  baseline_anchors = (
      ("legacy_pressure_window",
       "legacy_current_selector_D16_B16K8", 16),
      ("official_recollection",
       "official_current_selector_D16_B16K8", 16),
  )
  for source_id, case_id, capacity in baseline_anchors:
    roots = _case_roots(args, case_id)
    config_path = os.path.join(roots["data"], "resolved_config.json")
    dependency = "bridge:data:{}".format(case_id)
    root = _baseline_root(args, source_id, capacity)
    for policy in ("lru", "lfu", "clock"):
      result_path = os.path.join(root, policy, "run.json")
      jobs.append({
          "job_id": "bridge:baseline:{}:D{}:{}:deterministic".format(
              source_id, capacity, policy),
          "stage": "run", "kind": "baseline", "case_id": case_id,
          "source_id": source_id, "capacity": capacity,
          "policy": policy, "required": True,
          "dependencies": [dependency], "result_path": result_path,
          "resource": "cpu_replay",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", config_path,
              "--policy", policy, "--json_output", result_path]})
    for seed in bridge_variants.RANDOM_REPLAY_SEEDS:
      result_path = os.path.join(
          root, "random", "seed_{}.json".format(seed))
      jobs.append({
          "job_id": "bridge:baseline:{}:D{}:random:{}".format(
              source_id, capacity, seed),
          "stage": "run", "kind": "baseline", "case_id": case_id,
          "source_id": source_id, "capacity": capacity,
          "policy": "random", "replay_seed": seed, "required": True,
          "dependencies": [dependency], "result_path": result_path,
          "resource": "cpu_replay",
          "argv": [
              "python3", "qmap/qmap_eval.py", "--config", config_path,
              "--policy", "random", "--stage5_replay_seed", str(seed),
              "--json_output", result_path]})
  return jobs


def build_plan(args):
  jobs = _build_jobs(args)
  code_fingerprint = _code_fingerprint(args.repo_root)
  stage6_manifest_path = os.path.join(
      args.stage6_result_root, "run_manifest.json")
  if not os.path.isfile(stage6_manifest_path):
    raise ValueError(
        "Stage-6 manifest is required before bridge planning: {}".format(
            stage6_manifest_path))
  stage6_manifest_fingerprint = finals_config.fingerprint_file(
      stage6_manifest_path)
  source_fingerprints = {
      source_id: bridge_variants.trace_fingerprints(
          args.repo_root, source_id)
      for source_id in bridge_variants.SOURCE_SPECS}
  imported_paths = []
  imported_paths.extend(
      _legacy_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS)
  imported_paths.extend(
      _legacy_baseline_path(args, policy)
      for policy in bridge_variants.CLASSIC_POLICIES)
  imported_paths.extend(
      _official_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS)
  imported_paths.extend(_official_baseline_paths(args))
  missing_imports = [path for path in imported_paths if not os.path.isfile(path)]
  if missing_imports:
    raise ValueError(
        "Bridge imported evidence is missing: {}".format(missing_imports))
  imported_evidence_fingerprints = {
      _portable(path, args.repo_root): finals_config.fingerprint_file(path)
      for path in imported_paths}
  for job in jobs:
    job["command"] = _display_command(job["argv"])
    job["job_fingerprint"] = finals_config.fingerprint_value({
        "job": {
            key: value for key, value in job.items()
            if key != "job_fingerprint"},
        "code_fingerprint": code_fingerprint,
        "source_fingerprints":
            source_fingerprints[job["source_id"]],
    })
  if len({job["job_id"] for job in jobs}) != len(jobs):
    raise AssertionError("Bridge job ids must be unique.")
  required = [job for job in jobs if job["required"]]
  kinds = {}
  for job in required:
    kinds[job["kind"]] = kinds.get(job["kind"], 0) + 1
  if kinds != {"data": 3, "train": 9, "replay": 9, "baseline": 12}:
    raise AssertionError("Unexpected bridge matrix: {}".format(kinds))
  plan = {
      "schema_version": "capd_bridge_execution_plan_1",
      "status": BRIDGE_STATUS,
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
      "test_used_for_selection": False,
      "official_stage6_replaced": False,
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": code_fingerprint,
      "stage6_manifest_fingerprint": stage6_manifest_fingerprint,
      "source_fingerprints": source_fingerprints,
      "imported_evidence_fingerprints": imported_evidence_fingerprints,
      "required_jobs": len(required),
      "job_counts": kinds,
      "imported_case_count": len(bridge_variants.IMPORTED_CASES),
      "compute_case_count": len(bridge_variants.COMPUTE_CASES),
      "cases": bridge_variants.all_cases(),
      "attribution_chain": list(bridge_variants.ATTRIBUTION_CHAIN),
      "jobs": jobs,
  }
  _atomic_json(os.path.join(args.output_root, "execution_plan.json"), plan)
  return plan


def _legacy_qmap_path(args, seed):
  return os.path.join(
      args.legacy_seed_result_root, "streamcluster_pressure",
      "seed_{}".format(seed), "qmap.json")


def _legacy_baseline_path(args, policy):
  return os.path.join(
      args.legacy_result_root, "parsec_streamcluster",
      "{}.json".format(policy))


def _official_qmap_path(args, seed):
  return os.path.join(
      args.stage5_result_root, "raw", bridge_variants.WORKLOAD,
      "qmap", "seed_{}.json".format(seed))


def _official_baseline_paths(args):
  paths = []
  for policy in ("lru", "lfu", "clock"):
    paths.append(os.path.join(
        args.stage5_result_root, "raw", bridge_variants.WORKLOAD,
        policy, "run.json"))
  for seed in bridge_variants.RANDOM_REPLAY_SEEDS:
    paths.append(os.path.join(
        args.stage5_result_root, "raw", bridge_variants.WORKLOAD,
        "random", "seed_{}.json".format(seed)))
  return paths


def _count_csv_records(path):
  with open(path, "r", encoding="utf-8", newline="") as input_file:
    return max(0, sum(1 for _ in input_file) - 1)


def audit_inputs(args):
  checks = []

  def check(name, passed, detail):
    checks.append({
        "name": name, "status": "PASS" if passed else "FAIL",
        "detail": detail})

  stage6_manifest = os.path.join(
      args.stage6_result_root, "run_manifest.json")
  check("stage6_manifest_exists", os.path.isfile(stage6_manifest),
        _portable(stage6_manifest, args.repo_root))
  if os.path.isfile(stage6_manifest):
    payload = finals_config.load_json(stage6_manifest)
    check("stage6_verified", payload.get("status") == "STAGE6_VERIFIED",
          str(payload.get("status")))

  base_config_path = _base_config_path(args)
  check("base_config_exists", os.path.isfile(base_config_path),
        _portable(base_config_path, args.repo_root))
  if os.path.isfile(base_config_path):
    try:
      base = finals_config.load_config(
          base_config_path, require_resolved=True,
          project_root=args.repo_root)
      check("base_config_valid", True,
            finals_config.config_fingerprint(base))
    except Exception as error:
      check("base_config_valid", False, str(error))

  source_hashes = {}
  for source_id, source in bridge_variants.SOURCE_SPECS.items():
    manifest = _absolute(args.repo_root, source["source_manifest"])
    check("{}_manifest_exists".format(source_id), os.path.isfile(manifest),
          _portable(manifest, args.repo_root))
    source_hashes[source_id] = {}
    for split in ("train", "valid", "test"):
      path = _absolute(args.repo_root, source["{}_trace".format(split)])
      exists = os.path.isfile(path)
      check("{}_{}_exists".format(source_id, split), exists,
            _portable(path, args.repo_root))
      if exists:
        records = _count_csv_records(path)
        expected = int(source["expected_access_counts"][split])
        check("{}_{}_record_count".format(source_id, split),
              records == expected, "{} / {}".format(records, expected))
        source_hashes[source_id][split] = (
            finals_config.fingerprint_file(path))
  if all("test" in item for item in source_hashes.values()):
    check("bridge_test_traces_are_distinct",
          source_hashes["legacy_pressure_window"]["test"] !=
          source_hashes["official_recollection"]["test"],
          "{} != {}".format(
              source_hashes["legacy_pressure_window"]["test"],
              source_hashes["official_recollection"]["test"]))

  imported = []
  imported.extend(
      _legacy_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS)
  imported.extend(
      _legacy_baseline_path(args, policy)
      for policy in bridge_variants.CLASSIC_POLICIES)
  imported.extend(
      _official_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS)
  imported.extend(_official_baseline_paths(args))
  for index, path in enumerate(imported):
    valid = os.path.isfile(path) and os.path.getsize(path) > 0
    if valid:
      try:
        result = finals_config.load_json(path)
        valid = (
            result.get("policy") in
            ("qmap", "lru", "random", "lfu", "clock") and
            int(result.get("total_accesses", 0)) == 200000 and
            float(result.get("weighted_access_cost", -1.0)) >= 0.0)
      except (ValueError, OSError, TypeError):
        valid = False
    check("imported_evidence_{:02d}".format(index), valid,
          _portable(path, args.repo_root))

  passed = all(item["status"] == "PASS" for item in checks)
  result = {
      "schema_version": "capd_bridge_input_audit_1",
      "status": "PASSED" if passed else "FAILED",
      "bridge_status": BRIDGE_STATUS,
      "checks": checks,
      "test_used_for_selection": False,
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
  }
  path = os.path.join(args.output_root, "input_audit.json")
  _atomic_json(path, result)
  if not passed:
    raise ValueError("Bridge input audit failed; see {}".format(path))
  return result


def _job_manifest_path(job):
  return "{}.job_manifest.json".format(job["result_path"])


def _job_is_complete(job):
  path = _job_manifest_path(job)
  if not os.path.isfile(path) or not os.path.isfile(job["result_path"]):
    return False
  payload = finals_config.load_json(path)
  return (
      payload.get("status") == "COMPLETED" and
      payload.get("job_fingerprint") == job["job_fingerprint"] and
      os.path.getsize(job["result_path"]) > 0 and
      payload.get("result_fingerprint") ==
      finals_config.fingerprint_file(job["result_path"]))


def _execute_data(args, job):
  case = bridge_variants.compute_case(job["case_id"])
  roots = _case_roots(args, job["case_id"])
  os.makedirs(roots["data"], exist_ok=True)
  base = finals_config.load_config(
      _base_config_path(args), require_resolved=True,
      project_root=args.repo_root)
  config = bridge_variants.build_bridge_config(
      base, case, args.repo_root, _git_commit(args.repo_root))
  config_path = os.path.join(roots["data"], "resolved_config.json")
  selector_path = os.path.join(roots["data"], "selector_params.json")
  validation_path = os.path.join(
      roots["data"], "selector_validation_samples.jsonl")
  train_path = os.path.join(roots["data"], "train.jsonl")
  valid_path = os.path.join(roots["data"], "valid.jsonl")
  summary_path = os.path.join(roots["data"], "generator_summary.json")
  finals_config.write_json(config_path, config)
  generator_args = argparse.Namespace(
      config=config_path, selector_output=selector_path,
      validation_samples_output=validation_path,
      train_output=train_path, valid_output=valid_path,
      summary_output=summary_path, page_shift=None)
  finals_generator.fit_selector_and_generate(generator_args)
  selector = finals_config.load_json(selector_path)
  manifest = {
      "schema_version": "capd_bridge_variant_manifest_1",
      "status": "COMPLETED", "case": case,
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
      "test_trace_opened": False, "test_used_for_selection": False,
      "config_path": _portable(config_path, args.repo_root),
      "config_fingerprint": finals_config.config_fingerprint(config),
      "selector_path": _portable(selector_path, args.repo_root),
      "selector_fingerprint": finals_config.selector_fingerprint(selector),
      "jsonl_fingerprints": {
          "train": finals_config.fingerprint_file(train_path),
          "valid": finals_config.fingerprint_file(valid_path)},
      "trace_fingerprints": dict(config["run"]["split_fingerprints"]),
      "code_commit": _git_commit(args.repo_root),
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
    raise ValueError(
        "Job {} failed with exit code {}.".format(
            job["job_id"], completed.returncode))
  if not os.path.isfile(job["result_path"]):
    raise ValueError("Job produced no result: {}".format(
        job["result_path"]))
  if job["kind"] in ("replay", "baseline"):
    result = finals_config.load_json(job["result_path"])
    result.update({
        "bridge_case_id": job["case_id"],
        "bridge_source_id": job["source_id"],
        "scientific_role": "post_hoc_diagnostic_not_method_selection",
        "test_used_for_selection": False,
        "run_status": "COMPLETED",
    })
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
  payload = {
      "job_id": job["job_id"],
      "job_fingerprint": job["job_fingerprint"],
      "status": "RUNNING", "started_unix": time.time(),
      "command": job["command"], "log_path": log_path,
      "retry_count": 0, "atomic_manifest": True}
  _atomic_json(manifest_path, payload)
  try:
    if job["kind"] == "data":
      _execute_data(args, job)
    else:
      _execute_subprocess(args, job, log_path)
    payload.update({
        "status": "COMPLETED", "ended_unix": time.time(),
        "exit_code": 0,
        "result_fingerprint":
            finals_config.fingerprint_file(job["result_path"])})
  except Exception as error:
    payload.update({
        "status": "FAILED", "ended_unix": time.time(), "exit_code": 1,
        "error": str(error), "traceback": traceback.format_exc()})
    _atomic_json(manifest_path, payload)
    raise
  _atomic_json(manifest_path, payload)
  print("[COMPLETED] {}".format(job["job_id"]))


def _load_rows(paths):
  return [finals_config.load_json(path) for path in paths]


def _computed_case_rows(args, case_id):
  root = _case_roots(args, case_id)["result"]
  return _load_rows([
      os.path.join(root, "qmap", "seed_{}.json".format(seed))
      for seed in bridge_variants.MODEL_SEEDS])


def _computed_baseline_rows(args, source_id, capacity=16):
  root = _baseline_root(args, source_id, capacity)
  paths = [
      os.path.join(root, policy, "run.json")
      for policy in ("lru", "lfu", "clock")]
  paths.extend(
      os.path.join(root, "random", "seed_{}.json".format(seed))
      for seed in bridge_variants.RANDOM_REPLAY_SEEDS)
  return _load_rows(paths)


def _imported_legacy_rows(args):
  qmap = _load_rows([
      _legacy_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS])
  for row, seed in zip(qmap, bridge_variants.MODEL_SEEDS):
    row["model_seed"] = seed
  baselines = _load_rows([
      _legacy_baseline_path(args, policy)
      for policy in bridge_variants.CLASSIC_POLICIES])
  return qmap, baselines


def _imported_official_rows(args):
  qmap = _load_rows([
      _official_qmap_path(args, seed)
      for seed in bridge_variants.MODEL_SEEDS])
  baselines = _load_rows(_official_baseline_paths(args))
  return qmap, baselines


def _report_lines(summary):
  rows = summary["cases"]
  lines = [
      "# CAPD 桥接诊断结果",
      "",
      "状态：`BRIDGE_DIAGNOSTIC_COMPLETED`。",
      "",
      "> 这是事后诊断，不是新的正式调参阶段；test 未用于方法或参数选择，"
      "且结果不替换 `STAGE6_VERIFIED`。",
      "",
      "## 五个桥接锚点",
      "",
      "| case | source | D/B/K | QMAP cost（mean±std） | best classic | "
      "improvement |",
      "|---|---|---:|---:|---:|---:|",
  ]
  for row in rows:
    lines.append(
        "| {case_id} | {source_id} | {D}/{B}/{K} | "
        "{qmap_cost_mean:.3f} ± {qmap_cost_sample_stddev:.3f} | "
        "{best_classic_cost_mean:.3f} ({best_classic_policy}) | "
        "{improvement_percent_mean:+.4f}% |".format(**row))
  lines.extend([
      "",
      "## 逐因素归因",
      "",
      "| factor | left → right | improvement change | effect |",
      "|---|---|---:|---|",
  ])
  for row in summary["attribution"]:
    lines.append(
        "| {factor} | `{left_case}` → `{right_case}` | "
        "{improvement_percentage_point_delta:+.4f} pp | "
        "{absolute_effect_class}, {direction} |".format(**row))
  lines.extend([
      "",
      "## 判读边界",
      "",
      "- 每一行只解释相邻锚点之间的匹配差异；不能外推为普遍因果。",
      "- `bridge_diagnostics` 记录 QMAP/LRU victim 分歧、有限前瞻结果、"
      "score margin 与 victim sequence fingerprint。",
      "- 若三个 seed 的 victim fingerprint 完全相同，说明随机训练没有"
      "改变最终决策序列；这属于诊断结果，不构成继续使用 test 调参的许可。",
  ])
  return lines


def summarize(args, plan):
  incomplete = [
      job["job_id"] for job in plan["jobs"]
      if job["required"] and not _job_is_complete(job)]
  if incomplete:
    raise ValueError("Bridge jobs incomplete: {}".format(incomplete))
  stage6_manifest_path = os.path.join(
      args.stage6_result_root, "run_manifest.json")
  current_stage6_fingerprint = finals_config.fingerprint_file(
      stage6_manifest_path)
  if current_stage6_fingerprint != plan["stage6_manifest_fingerprint"]:
    raise ValueError(
        "Official Stage-6 manifest changed during bridge execution.")
  for relative_path, expected in plan[
      "imported_evidence_fingerprints"].items():
    path = _absolute(args.repo_root, relative_path)
    if (not os.path.isfile(path) or
        finals_config.fingerprint_file(path) != expected):
      raise ValueError(
          "Imported bridge endpoint changed during execution: {}".format(
              relative_path))
  legacy_qmap, legacy_baselines = _imported_legacy_rows(args)
  official_qmap, official_baselines = _imported_official_rows(args)
  computed_baselines = {
      source_id: _computed_baseline_rows(args, source_id)
      for source_id in bridge_variants.SOURCE_SPECS}
  case_rows = {}
  case_rows["legacy_published_D16_B8K8"] = (
      bridge_results.summarize_case(
          _case_by_id("legacy_published_D16_B8K8"),
          legacy_qmap, legacy_baselines, "frozen_legacy_import"))
  for case in bridge_variants.COMPUTE_CASES:
    case_rows[case["case_id"]] = bridge_results.summarize_case(
        case, _computed_case_rows(args, case["case_id"]),
        computed_baselines[case["source_id"]], "fresh_bridge_compute")
  case_rows["official_current_full_D64_B64K8"] = (
      bridge_results.summarize_case(
          _case_by_id("official_current_full_D64_B64K8"),
          official_qmap, official_baselines, "frozen_stage5_import"))
  ordered = [case_rows[case_id] for case_id in SUMMARY_CASE_ORDER]
  summary = bridge_results.build_summary(
      ordered, legacy_baselines,
      computed_baselines["legacy_pressure_window"])
  _write_csv(os.path.join(args.output_root, "bridge_results.csv"), ordered)
  _write_csv(
      os.path.join(args.output_root, "bridge_attribution.csv"),
      summary["attribution"])
  _write_csv(
      os.path.join(args.output_root, "legacy_baseline_drift.csv"),
      summary["legacy_baseline_drift"])
  _atomic_json(
      os.path.join(args.output_root, "bridge_summary.json"), summary)
  report_path = os.path.join(args.output_root, "bridge_report.md")
  with open(report_path, "w", encoding="utf-8", newline="\n") as output:
    output.write("\n".join(_report_lines(summary)))
    output.write("\n")
  manifest = {
      "schema_version": "capd_bridge_run_manifest_1",
      "status": "BRIDGE_DIAGNOSTIC_COMPLETED",
      "required_jobs": plan["required_jobs"],
      "completed_required_jobs": sum(
          1 for job in plan["jobs"]
          if job["required"] and _job_is_complete(job)),
      "case_count": len(ordered),
      "attribution_factor_count": len(summary["attribution"]),
      "stage6_status": "STAGE6_VERIFIED",
      "official_stage6_replaced": False,
      "method_contract_changed": False,
      "test_used_for_selection": False,
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": plan["code_fingerprint"],
      "stage6_manifest_fingerprint":
          plan["stage6_manifest_fingerprint"],
      "required_outputs": [
          "input_audit.json", "execution_plan.json", "bridge_results.csv",
          "bridge_summary.json", "bridge_attribution.csv",
          "legacy_baseline_drift.csv", "bridge_report.md",
          "run_manifest.json"],
  }
  _atomic_json(os.path.join(args.output_root, "run_manifest.json"), manifest)
  return summary


def _run_jobs(args, plan):
  if args.job_id:
    matches = [job for job in plan["jobs"] if job["job_id"] == args.job_id]
    if len(matches) != 1:
      raise ValueError("Unknown --job-id: {}".format(args.job_id))
    execute_job(args, plan, matches[0])
    return
  if not args.execute:
    raise ValueError("--stage run requires --execute or --job-id.")
  for job in plan["jobs"]:
    execute_job(args, plan, job)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run the CAPD streamcluster bridge diagnostic.")
  parser.add_argument("--stage", choices=STAGES, default="plan")
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--job-id", default=None)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument(
      "--artifact-root",
      default=os.path.join(
          PROJECT_ROOT, "dataset", "jsonl", "finals_v3_official"))
  parser.add_argument(
      "--data-root",
      default=os.path.join(
          PROJECT_ROOT, "dataset", "jsonl", "capd_bridge_diagnostic"))
  parser.add_argument(
      "--checkpoint-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "checkpoints",
          "capd_bridge_diagnostic"))
  parser.add_argument(
      "--output-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "results",
          "capd_bridge_diagnostic"))
  parser.add_argument(
      "--legacy-result-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "results",
          "real_workload_suite_pressure", "selected"))
  parser.add_argument(
      "--legacy-seed-result-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "results", "seed_stability"))
  parser.add_argument(
      "--stage5-result-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "results", "finals_v3_official",
          "stage5_main"))
  parser.add_argument(
      "--stage6-result-root",
      default=os.path.join(
          PROJECT_ROOT, "outputs", "results", "finals_v3_official",
          "stage6"))
  return parser


def main():
  args = build_arg_parser().parse_args()
  args.repo_root = os.path.abspath(args.repo_root)
  plan = None
  if args.stage in ("audit-inputs", "all"):
    audit_inputs(args)
  if args.stage in ("plan", "run", "summarize", "all"):
    plan = build_plan(args)
  if args.stage in ("run", "all"):
    _run_jobs(args, plan)
  if args.stage in ("summarize", "all"):
    summarize(args, plan)


if __name__ == "__main__":
  main()
