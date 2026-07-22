# coding=utf-8
"""One-shot Linux acceptance for the complete CAPD finals-v3 stage-2 set."""

from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import tempfile


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
POOL_SIZES = (8, 16, 32, 64)
GENERATION_COMMIT = "2bd07f29a639d54db5180b57651842ce95dd3014"
BASE_CONFIG = "configs/finals/capd_direction1_v3.json"
DATA_PROFILE = "configs/finals/capd_stage2_data_profile.json"


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def run(command, timeout=None, environment=None):
  return subprocess.run(
      command, cwd=PROJECT_ROOT, env=environment, timeout=timeout,
      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
      universal_newlines=True)


def verify_generation_commit(errors):
  result = run([
      "git", "merge-base", "--is-ancestor", GENERATION_COMMIT, "HEAD",
  ])
  if result.returncode:
    errors.append("generation commit is not an ancestor of HEAD")
  else:
    print("[OK] generation_commit_ancestor")


def verify_data(temp_root, errors):
  base = finals_config.load_config(path_from_root(*BASE_CONFIG.split("/")))
  profile = finals_data.load_json(path_from_root(*DATA_PROFILE.split("/")))
  for workload in WORKLOADS:
    manifest_path = path_from_root(
        "dataset", "metadata", "finals_v3_official", workload + ".json")
    report_path = path_from_root(
        "dataset", "metadata", "finals_v3_official", "reports",
        workload + ".json")
    try:
      manifest = finals_data.load_source_manifest(
          manifest_path, PROJECT_ROOT, verify_files=True,
          require_quality_pass=True, expected_workload=workload)
      print("[OK] sealed_manifest_{}".format(workload))
    except (OSError, UnicodeError, ValueError) as error:
      errors.append("sealed_manifest_{}: {}".format(workload, error))
      continue

    report = finals_data.audit_source_manifest(
        manifest_path, PROJECT_ROOT, base, profile)
    if report.get("status") != "PASSED":
      errors.append("data_audit_{}: {}".format(
          workload, report.get("hard_failures") or
          report.get("sufficiency_failures")))
      continue
    if report != load_json(report_path):
      errors.append("data_audit_{}: committed report mismatch".format(
          workload))
      continue
    output = os.path.join(temp_root, workload + ".json")
    finals_data.write_json(output, report)
    print("[OK] data_audit_{}".format(workload))


def verify_artifacts(temp_root, errors):
  for workload in WORKLOADS:
    for pool_size in POOL_SIZES:
      label = "{}_B{}".format(workload, pool_size)
      artifact_root = path_from_root(
          "dataset", "jsonl", "finals_v3_official", workload,
          "B{}".format(pool_size))
      output = os.path.join(temp_root, label + ".json")
      command = [
          sys.executable, path_from_root(
              "scripts", "verify_finals_v3_artifacts.py"),
          "--config", os.path.join(artifact_root, "resolved_config.json"),
          "--selector", os.path.join(artifact_root, "selector_params.json"),
          "--validation-samples", os.path.join(
              artifact_root, "selector_validation_samples.jsonl"),
          "--train-jsonl", os.path.join(artifact_root, "train.jsonl"),
          "--valid-jsonl", os.path.join(artifact_root, "valid.jsonl"),
          "--summary", os.path.join(artifact_root, "generator_summary.json"),
          "--output", output,
      ]
      result = run(command, timeout=300)
      if result.returncode:
        errors.append("artifact_{}: {}".format(
            label, result.stdout.strip().splitlines()[-1]
            if result.stdout.strip() else "verifier failed"))
        continue
      expected = path_from_root(
          "dataset", "metadata", "finals_v3_official",
          "artifact_audits", label + ".json")
      if load_json(output) != load_json(expected):
        errors.append("artifact_{}: committed audit mismatch".format(label))
        continue
      print("[OK] artifact_{}".format(label))


def verify_repository(errors):
  result = run(["git", "diff", "--check"])
  if result.returncode:
    errors.append("git_diff_check: {}".format(result.stdout.strip()))
  else:
    print("[OK] git_diff_check")

  result = run(["git", "status", "--porcelain"])
  if result.returncode or result.stdout.strip():
    errors.append("worktree_clean: {}".format(result.stdout.strip()))
  else:
    print("[OK] worktree_clean")

  for relative in (
      os.path.join("outputs", "checkpoints", "finals_v3_official"),
      os.path.join("outputs", "results", "finals_v3_official"),
  ):
    absolute = path_from_root(relative)
    if os.path.isdir(absolute) and any(os.scandir(absolute)):
      errors.append("unexpected training/result output: {}".format(relative))
  if not any(item.startswith("unexpected training/result") for item in errors):
    print("[OK] no_training_outputs")


def verify_regression(errors):
  environment = os.environ.copy()
  environment["CAPD_RUN_STAGE1_E2E"] = "0"
  result = run(
      [sys.executable, "-m", "pytest", "-q"], timeout=1800,
      environment=environment)
  if result.returncode:
    tail = "\n".join(result.stdout.splitlines()[-30:])
    errors.append("full_regression:\n{}".format(tail))
  else:
    summary = result.stdout.strip().splitlines()[-1]
    print("[OK] full_regression {}".format(summary))


def main():
  parser = argparse.ArgumentParser(
      description="Verify all CAPD finals-v3 stage-2 data and artifacts.")
  parser.add_argument(
      "--skip-regression", action="store_true",
      help="Skip pytest only when a successful server run is already sealed.")
  args = parser.parse_args()

  errors = []
  temp = tempfile.mkdtemp(prefix="capd-stage2-acceptance-")
  print("[INFO] repo={}".format(PROJECT_ROOT))
  print("[INFO] evidence={}".format(temp))
  verify_generation_commit(errors)
  verify_data(temp, errors)
  verify_artifacts(temp, errors)
  if not args.skip_regression:
    verify_regression(errors)
  verify_repository(errors)

  if errors:
    print("\n===== FAILURES =====")
    for error in errors:
      print("[FAIL] {}".format(error))
    print("\n[FINAL] STAGE2_NOT_VERIFIED")
    print("[INFO] evidence_retained={}".format(temp))
    return 1
  print("\n[FINAL] STAGE2_VERIFIED")
  print("[INFO] evidence_retained={}".format(temp))
  return 0


if __name__ == "__main__":
  sys.exit(main())
