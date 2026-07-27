#!/usr/bin/env python3
# coding=utf-8
"""Plan, execute and summarize the CAPD R1 pressure-headroom diagnostic.

R1 reads only the existing official train/valid splits.  It does not train a
model, open test rows, consume Bridge test metrics, select a method/config, or
modify any Stage-6/Bridge/O1-O3 artifact.
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
from qmap import pressure_headroom
from qmap import pressure_variants


PROFILE_RELATIVE_PATH = (
    "configs/finals/capd_r1_pressure_headroom_profile.json")
STAGE6_MANIFEST = (
    "outputs/results/finals_v3_official/stage6/run_manifest.json")
BRIDGE_MANIFEST = (
    "outputs/results/capd_bridge_diagnostic/run_manifest.json")
O3_MANIFEST = (
    "outputs/results/capd_post_stage6_optimization/o3/run_manifest.json")
CLASSICAL_POLICIES = ("lru", "clock")
STAGES = ("audit-inputs", "plan", "run", "summarize", "all")


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
      "scripts/run_capd_r1.py",
      "qmap/pressure_variants.py",
      "qmap/pressure_oracle.py",
      "qmap/pressure_headroom.py",
      "qmap/optimization_oracle.py",
      "qmap/stage4_counterfactual.py",
      "qmap/finals_config.py",
      "qmap/finals_generator.py",
      "qmap/qmap_eval.py",
      "qmap/candidate_filter.py",
      "configs/finals/capd_r1_pressure_headroom_profile.json",
  )
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def load_profile(args):
  profile = _load_json(_absolute(args.repo_root, args.profile))
  if profile.get("schema_version") != (
      "capd_r1_pressure_headroom_profile_1"):
    raise ValueError("Unsupported R1 pressure profile schema.")
  if profile.get("contract_id") != finals_config.CONTRACT_ID:
    raise ValueError("R1 must remain bound to CAPD-MIC-1.0.")
  for field in (
      "method_contract_changed", "method_selection_performed",
      "official_stage6_replaced", "bridge_test_used_for_selection",
      "test_used_for_selection"):
    if profile.get(field) is not False:
      raise ValueError("R1 profile requires {}=false.".format(field))
  points = [
      pressure_variants.validate_pressure_point(row)
      for row in profile["pressure_points"]]
  if points != list(pressure_variants.PRESSURE_POINTS):
    raise ValueError("R1 pressure matrix is not the preregistered matrix.")
  if tuple(profile["classical_policies"]) != CLASSICAL_POLICIES:
    raise ValueError("R1 classical policies must be LRU and CLOCK.")
  if profile["frozen_method"] != {
      "H": 10, "Hc": 256, "L": 256, "Lres": 256,
      "loss": "QMAPCostAwareRankingLoss",
      "selector": "CAPD B-to-K selector",
      "architecture": "QMAP-CrossAttn",
      "cost_profile": "official",
      "training_scope": "per_workload",
  }:
    raise ValueError("R1 frozen method declaration changed.")
  return profile


def _base_config_path(args, workload):
  return os.path.join(
      args.official_artifact_root, workload, "B64", "resolved_config.json")


def _data_roots(args, workload, case_id):
  root = os.path.join(args.data_root, case_id, workload)
  return {
      "data": root,
      "config": os.path.join(root, "resolved_config.json"),
      "selector": os.path.join(root, "selector_params.json"),
      "train": os.path.join(root, "train.jsonl"),
      "valid": os.path.join(root, "valid.jsonl"),
      "validation_samples":
          os.path.join(root, "selector_validation_samples.jsonl"),
      "summary": os.path.join(root, "generator_summary.json"),
      "manifest": os.path.join(root, "variant_manifest.json"),
  }


def _result_root(args, workload, case_id):
  return os.path.join(args.output_root, "raw", workload, case_id)


def _check(checks, name, passed, detail, path=None):
  row = {
      "name": name,
      "status": "PASSED" if passed else "FAILED",
      "detail": detail,
  }
  if path is not None:
    row["path"] = _portable(path, PROJECT_ROOT)
  checks.append(row)


def _audit_manifest(
    args, checks, name, relative, expected_status, required_jobs=None):
  path = _absolute(args.repo_root, relative)
  if not os.path.isfile(path):
    _check(checks, name, False, "Required manifest is missing.", path)
    return None
  payload = _load_json(path)
  problems = []
  if payload.get("status") != expected_status:
    problems.append(
        "status={} expected={}".format(
            payload.get("status"), expected_status))
  if required_jobs is not None:
    if payload.get("required_jobs") != required_jobs:
      problems.append("required_jobs mismatch")
    if payload.get("completed_required_jobs") != required_jobs:
      problems.append("completed_required_jobs mismatch")
  if payload.get("test_used_for_selection") is not False:
    problems.append("test_used_for_selection is not false")
  _check(
      checks, name, not problems,
      "Manifest accepted." if not problems else "; ".join(problems), path)
  return payload if not problems else None


def audit_inputs(args, profile=None):
  profile = profile or load_profile(args)
  checks = []
  _audit_manifest(
      args, checks, "stage6", STAGE6_MANIFEST,
      "STAGE6_VERIFIED", required_jobs=105)
  _audit_manifest(
      args, checks, "bridge", BRIDGE_MANIFEST,
      "BRIDGE_DIAGNOSTIC_COMPLETED", required_jobs=33)
  o3 = _audit_manifest(
      args, checks, "o3_lock", O3_MANIFEST,
      "O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT")
  if o3 is not None:
    path = _absolute(args.repo_root, O3_MANIFEST)
    _check(
        checks, "o3_method_contract",
        o3.get("method_contract_changed") is False and
        o3.get("official_stage6_replaced") is False,
        "O3 remains frozen and does not replace Stage 6.", path)

  for workload in profile["workloads"]:
    path = _base_config_path(args, workload)
    if not os.path.isfile(path):
      _check(
          checks, "base_config_{}".format(workload), False,
          "Official B64 config is missing.", path)
      continue
    try:
      config = finals_config.load_config(
          path, require_resolved=True, project_root=args.repo_root,
          verify_manifest_files=False)
      train_path = config["data"]["train_trace"]
      valid_path = config["data"]["valid_trace"]
      passed = (
          config["run_profile"] == finals_config.OFFICIAL_PROFILE and
          config["run"]["workload"] == workload and
          os.path.isfile(train_path) and os.path.isfile(valid_path) and
          bool(config["data"]["split_fingerprints"]["test"]))
      detail = (
          "Official train/valid paths and split fingerprints accepted; "
          "test rows were not opened." if passed else
          "Official config or train/valid inputs are incomplete.")
    except Exception as error:
      passed = False
      detail = str(error)
    _check(
        checks, "base_config_{}".format(workload),
        passed, detail, path)

  failed = [row for row in checks if row["status"] == "FAILED"]
  return {
      "schema_version": "capd_r1_input_audit_1",
      "status": "R1_READY" if not failed else "FAILED",
      "profile_id": profile["profile_id"],
      "checks": checks,
      "failed_checks": len(failed),
      "eligible_to_execute_R1": not failed,
      "workload_count": len(profile["workloads"]),
      "pressure_point_count": len(profile["pressure_points"]),
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
  }


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
      manifest.get("result_fingerprint") ==
      finals_config.fingerprint_file(job["result_path"]))


def build_plan(args, profile=None):
  profile = profile or load_profile(args)
  jobs = []
  for workload in profile["workloads"]:
    for declared in profile["pressure_points"]:
      point = pressure_variants.validate_pressure_point(declared)
      case_id = point["case_id"]
      roots = _data_roots(args, workload, case_id)
      result_root = _result_root(args, workload, case_id)
      data_id = "r1:data:{}:{}".format(workload, case_id)
      jobs.append({
          "job_id": data_id,
          "kind": "data",
          "workload": workload,
          "case_id": case_id,
          "point": point,
          "dependencies": [],
          "resource": "cpu_memory_bound",
          "result_path": roots["manifest"],
          "argv": [
              "python3", "scripts/run_capd_r1.py",
              "--stage", "run", "--job-id", data_id],
          "_input_paths": [_base_config_path(args, workload)],
      })
      oracle_path = os.path.join(result_root, "oracle.json")
      jobs.append({
          "job_id": "r1:oracle:{}:{}".format(workload, case_id),
          "kind": "oracle",
          "workload": workload,
          "case_id": case_id,
          "point": point,
          "dependencies": [data_id],
          "resource": "cpu",
          "result_path": oracle_path,
          "argv": [
              "python3", "qmap/pressure_oracle.py",
              "--config", roots["config"],
              "--selector_params", roots["selector"],
              "--json_output", oracle_path],
          "_input_paths": [],
      })
      opportunity_path = os.path.join(
          result_root, "opportunity_audit.json")
      jobs.append({
          "job_id": "r1:opportunity:{}:{}".format(workload, case_id),
          "kind": "opportunity",
          "workload": workload,
          "case_id": case_id,
          "point": point,
          "dependencies": [data_id],
          "resource": "cpu_compute_bound",
          "result_path": opportunity_path,
          "argv": [
              "python3", "qmap/pressure_headroom.py",
              "--config", roots["config"],
              "--selector_params", roots["selector"],
              "--json_output", opportunity_path],
          "_input_paths": [],
      })
      for policy in CLASSICAL_POLICIES:
        baseline_path = os.path.join(
            result_root, "{}.json".format(policy))
        jobs.append({
            "job_id": "r1:baseline:{}:{}:{}".format(
                workload, case_id, policy),
            "kind": "baseline",
            "workload": workload,
            "case_id": case_id,
            "point": point,
            "policy": policy,
            "dependencies": [data_id],
            "resource": "cpu",
            "result_path": baseline_path,
            "argv": [
                "python3", "qmap/qmap_eval.py",
                "--config", roots["config"],
                "--evaluation_split", "valid",
                "--policy", policy,
                "--json_output", baseline_path],
            "_input_paths": [],
        })

  code_fingerprint = _code_fingerprint(args.repo_root)
  by_id = {}
  for job in jobs:
    job["command"] = _display_command(job["argv"])
    input_fingerprints = {}
    for path in job.pop("_input_paths"):
      input_fingerprints[_portable(path, args.repo_root)] = (
          finals_config.fingerprint_file(path)
          if os.path.isfile(path) else None)
    dependency_fingerprints = {
        dependency: by_id[dependency]["job_fingerprint"]
        for dependency in job["dependencies"]}
    job["input_fingerprints"] = input_fingerprints
    job["dependency_fingerprints"] = dependency_fingerprints
    job["job_fingerprint"] = finals_config.fingerprint_value({
        "job": {
            key: job.get(key) for key in (
                "job_id", "kind", "workload", "case_id", "policy",
                "dependencies", "result_path", "command")},
        "point": job["point"],
        "inputs": input_fingerprints,
        "dependencies": dependency_fingerprints,
        "code_fingerprint": code_fingerprint,
    })
    by_id[job["job_id"]] = job
  counts = {
      kind: len([job for job in jobs if job["kind"] == kind])
      for kind in ("data", "oracle", "opportunity", "baseline")}
  return {
      "schema_version": "capd_r1_execution_plan_1",
      "status": "PLANNED",
      "profile_id": profile["profile_id"],
      "scientific_role": profile["scientific_role"],
      "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": code_fingerprint,
      "required_jobs": len(jobs),
      "job_counts": counts,
      "workloads": list(profile["workloads"]),
      "pressure_points": list(profile["pressure_points"]),
      "allowed_splits": ["train", "valid"],
      "forbidden_splits": ["test", "fresh_holdout"],
      "training_jobs": 0,
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
      "jobs": jobs,
  }


def _execute_subprocess(args, job):
  argv = list(job["argv"])
  if argv and argv[0] == "python3":
    argv[0] = sys.executable
  log_path = "{}.log".format(job["result_path"])
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
    raise ValueError(
        "Job did not create {}".format(job["result_path"]))


def _execute_data_job(args, job):
  roots = _data_roots(args, job["workload"], job["case_id"])
  os.makedirs(roots["data"], exist_ok=True)
  pressure_variants.generate_pressure_artifacts(
      _base_config_path(args, job["workload"]), job["point"], roots,
      args.repo_root, _git_commit(args.repo_root))


def execute_job(args, plan, job):
  by_id = {row["job_id"]: row for row in plan["jobs"]}
  for dependency in job["dependencies"]:
    if not _job_is_complete(by_id[dependency]):
      raise ValueError("Incomplete dependency: {}".format(dependency))
  if _job_is_complete(job):
    print("[RESUME] {}".format(job["job_id"]))
    return
  manifest_path = _job_manifest_path(job)
  manifest = {
      "schema_version": "capd_r1_job_manifest_1",
      "job_id": job["job_id"],
      "job_fingerprint": job["job_fingerprint"],
      "status": "RUNNING",
      "started_unix": time.time(),
      "command": job["command"],
      "atomic_manifest": True,
  }
  _atomic_json(manifest_path, manifest)
  try:
    if job["kind"] == "data":
      _execute_data_job(args, job)
    else:
      _execute_subprocess(args, job)
    manifest.update({
        "status": "COMPLETED",
        "ended_unix": time.time(),
        "exit_code": 0,
        "result_fingerprint":
            finals_config.fingerprint_file(job["result_path"]),
    })
  except Exception as error:
    manifest.update({
        "status": "FAILED",
        "ended_unix": time.time(),
        "exit_code": 1,
        "error": str(error),
        "traceback": traceback.format_exc(),
    })
    _atomic_json(manifest_path, manifest)
    raise
  _atomic_json(manifest_path, manifest)
  print("[COMPLETED] {}".format(job["job_id"]))


def run_jobs(args, plan):
  selected = list(plan["jobs"])
  if args.job_id:
    selected = [job for job in selected if job["job_id"] == args.job_id]
    if len(selected) != 1:
      raise ValueError("Unknown R1 job: {}".format(args.job_id))
  elif not args.execute:
    print("[PLAN ONLY] {} jobs; pass --execute or --job-id.".format(
        len(selected)))
    return
  for job in selected:
    execute_job(args, plan, job)


def _assert_complete(plan):
  incomplete = [
      job["job_id"] for job in plan["jobs"]
      if not _job_is_complete(job)]
  if incomplete:
    raise ValueError(
        "Incomplete R1 jobs: {}".format(", ".join(incomplete[:10])))


def _trend_rows(rows, workloads):
  result = []
  for workload in workloads:
    selected = sorted(
        [row for row in rows if row["workload"] == workload],
        key=lambda row: int(row["D"]))
    if [row["D"] for row in selected] != [16, 32, 64]:
      raise ValueError("R1 trend requires D=16/32/64 for {}".format(
          workload))
    by_d = {int(row["D"]): row for row in selected}
    d16 = by_d[16]
    d64 = by_d[64]
    if (
        float(d16["relative_headroom_percent"]) >
        float(d64["relative_headroom_percent"]) and
        float(d16["relative_headroom_percent"]) > 0.0):
      description = "MORE_HEADROOM_AT_D16"
    elif any(bool(row["measurable_headroom"]) for row in selected):
      description = "MIXED_MEASURABLE_HEADROOM"
    else:
      description = "NO_MEASURABLE_HEADROOM"
    result.append({
        "workload": workload,
        "descriptive_pattern": description,
        "headroom_percentage_point_D16_minus_D64": (
            float(d16["relative_headroom_percent"]) -
            float(d64["relative_headroom_percent"])),
        "distinguishable_rate_D16_minus_D64": (
            float(d16["counterfactual_cost_distinguishable_rate"]) -
            float(d64["counterfactual_cost_distinguishable_rate"])),
        "method_selection_performed": False,
        "test_used_for_selection": False,
    })
  return result


def summarize(args, profile=None):
  profile = profile or load_profile(args)
  plan = build_plan(args, profile)
  _assert_complete(plan)
  rows = []
  for workload in profile["workloads"]:
    for declared in profile["pressure_points"]:
      point = pressure_variants.validate_pressure_point(declared)
      matched = [
          job for job in plan["jobs"]
          if job["workload"] == workload and
          job["case_id"] == point["case_id"]]
      oracle_job = [
          job for job in matched if job["kind"] == "oracle"][0]
      opportunity_job = [
          job for job in matched if job["kind"] == "opportunity"][0]
      baseline_jobs = [
          job for job in matched if job["kind"] == "baseline"]
      oracle = _load_json(oracle_job["result_path"])
      opportunity = _load_json(opportunity_job["result_path"])
      baselines = [
          _load_json(job["result_path"]) for job in baseline_jobs]
      rows.append(pressure_headroom.summarize_pressure_point(
          point, oracle, opportunity, baselines))
  rows.sort(key=lambda row: (row["workload"], int(row["D"])))
  trends = _trend_rows(rows, profile["workloads"])
  _write_csv(
      os.path.join(args.output_root, "pressure_headroom_results.csv"), rows)
  _write_csv(
      os.path.join(args.output_root, "pressure_headroom_trends.csv"), trends)
  summary = {
      "schema_version": "capd_r1_pressure_headroom_summary_1",
      "status": "R1_IMPLEMENTED_UNVERIFIED",
      "profile_id": profile["profile_id"],
      "scientific_role": profile["scientific_role"],
      "rows": rows,
      "trends": trends,
      "result_row_count": len(rows),
      "interpretation_boundary": (
          "Descriptive train/valid-only pressure diagnosis. It does not "
          "select a method/configuration or establish test/holdout gains."),
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
  }
  _atomic_json(
      os.path.join(args.output_root, "pressure_headroom_summary.json"),
      summary)
  manifest = {
      "schema_version": "capd_r1_run_manifest_1",
      "status": "R1_IMPLEMENTED_UNVERIFIED",
      "profile_id": profile["profile_id"],
      "required_jobs": plan["required_jobs"],
      "completed_required_jobs": plan["required_jobs"],
      "job_counts": plan["job_counts"],
      "result_row_count": len(rows),
      "workload_count": len(profile["workloads"]),
      "pressure_point_count": len(profile["pressure_points"]),
      "training_jobs": 0,
      "summary_fingerprint": finals_config.fingerprint_file(
          os.path.join(
              args.output_root, "pressure_headroom_summary.json")),
      "stage6_status": "STAGE6_VERIFIED",
      "bridge_status": "BRIDGE_DIAGNOSTIC_COMPLETED",
      "o3_status": "O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT",
      "method_selection_performed": False,
      "bridge_test_used_for_selection": False,
      "test_trace_opened": False,
      "test_used_for_selection": False,
      "method_contract_changed": False,
      "official_stage6_replaced": False,
  }
  _atomic_json(os.path.join(args.output_root, "run_manifest.json"), manifest)
  return manifest


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="CAPD R1 pressure-headroom diagnostic orchestrator.")
  parser.add_argument("--stage", choices=STAGES, default="audit-inputs")
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument("--profile", default=PROFILE_RELATIVE_PATH)
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--job-id", default=None)
  parser.add_argument(
      "--official-artifact-root",
      default="dataset/jsonl/finals_v3_official")
  parser.add_argument(
      "--data-root", default="dataset/jsonl/capd_r1_pressure_headroom")
  parser.add_argument(
      "--output-root",
      default="outputs/results/capd_r1_pressure_headroom")
  return parser


def _resolve_args(args):
  args.repo_root = os.path.abspath(args.repo_root)
  for name in ("official_artifact_root", "data_root", "output_root"):
    setattr(args, name, os.path.abspath(
        _absolute(args.repo_root, getattr(args, name))))


def main():
  args = build_arg_parser().parse_args()
  _resolve_args(args)
  profile = load_profile(args)
  if args.stage in ("audit-inputs", "all"):
    audit = audit_inputs(args, profile)
    _atomic_json(
        os.path.join(args.output_root, "input_audit.json"), audit)
    print("[R1] input_audit status={} checks={}".format(
        audit["status"], len(audit["checks"])))
    if audit["status"] == "FAILED":
      raise SystemExit(1)
  if args.stage in ("plan", "all"):
    plan = build_plan(args, profile)
    _atomic_json(
        os.path.join(args.output_root, "execution_plan.json"), plan)
    print("[R1] plan required_jobs={} counts={}".format(
        plan["required_jobs"], plan["job_counts"]))
    if args.stage == "plan":
      for job in plan["jobs"]:
        print("{} {}".format(job["job_id"], job["command"]))
  if args.stage in ("run", "all"):
    plan = build_plan(args, profile)
    _atomic_json(
        os.path.join(args.output_root, "execution_plan.json"), plan)
    run_jobs(args, plan)
  if args.stage in ("summarize", "all"):
    manifest = summarize(args, profile)
    print("[R1] status={} completed={}/{}".format(
        manifest["status"], manifest["completed_required_jobs"],
        manifest["required_jobs"]))


if __name__ == "__main__":
  main()
