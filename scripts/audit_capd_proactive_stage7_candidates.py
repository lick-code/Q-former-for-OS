# coding=utf-8
"""Audit Stage-7 candidates without opening or replaying Test payloads."""

from __future__ import print_function

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage7_workloads as stage7  # noqa: E402


def _utc_now():
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_stage7_result_audit():
  command = ["git", "show", "--name-only", "--format=", "b714ad0"]
  try:
    output = subprocess.check_output(
        command, cwd=PROJECT_ROOT, stderr=subprocess.STDOUT,
        universal_newlines=True)
  except (OSError, subprocess.CalledProcessError) as error:
    return {
        "commit": "b714ad0",
        "audit_status": "unavailable",
        "error": str(error),
    }
  paths = [line.strip().replace("\\", "/")
           for line in output.splitlines() if line.strip()]
  only_stage6 = bool(paths) and all(
      path.startswith("outputs/capd_proactive_stage6/stage6-tpp-r1/") or
      path == "stage6-stage6-tpp-r1-console.log"
      for path in paths)
  return {
      "commit": "b714ad0",
      "path_count": len(paths),
      "contains_only_stage6_tpp_r1_artifacts_and_console_log": only_stage6,
      "is_current_stage7_evidence": False,
      "audit_status": "passed" if only_stage6 else "unexpected_content",
  }


def audit(config_path, output_path=None):
  config = stage7.load_json(config_path)
  stage7.validate_workload_config(config)
  entry = stage7.audit_stage6_entry(config, PROJECT_ROOT)
  rows = []
  for candidate in config["proposed_suite"]:
    workload = candidate["workload"]
    row = {
        "workload": workload,
        "role": candidate["role"],
        "coverage": candidate["coverage"],
        "collection_cost_estimate": candidate["collection_cost_estimate"],
        "qualification_risks": candidate["qualification_risks"],
        "test_payload_read": False,
        "capd_results_used": False,
        "formal_suite_frozen": False,
        "recommended_action": candidate["trace_action"],
        "qualification_status": "fresh_collection_required",
        "reusable_now": False,
        "gaps": [],
    }
    existing_manifest = candidate.get("existing_manifest")
    if existing_manifest:
      manifest_path = stage7.repository_path(
          PROJECT_ROOT, existing_manifest)
      manifest = stage7.load_json(manifest_path)
      source = manifest.get("collections", [{}])[0].get("source_trace", {})
      row.update({
          "existing_manifest": existing_manifest,
          "existing_manifest_sha256": stage7.fingerprint_file(manifest_path),
          "recorded_source_trace_id":
              manifest.get("collections", [{}])[0].get("collection_id"),
          "recorded_source_trace_path": source.get("path"),
          "recorded_source_trace_sha256": source.get("fingerprint_sha256"),
          "recorded_accesses": source.get("access_count"),
          "recorded_real_rw": manifest.get("rw_source", {}).get(
              "verified_real") is True,
          "recorded_page_shift": manifest.get("page_shift"),
          "recorded_chronological_nonoverlap":
              manifest.get("split_strategy", "").startswith(
                  "explicit chronological non-overlapping"),
      })
      # The historical manifests did not record actual observed PID/TID sets,
      # ASLR, loss, timeout, or truncation fields required by the new contract.
      row["gaps"] = [
          "actual_process_ids_not_recorded",
          "actual_thread_ids_not_recorded",
          "aslr_state_not_recorded",
          "lost_event_status_not_recorded",
          "timeout_status_not_recorded",
          "truncation_status_not_recorded",
          "historical_test_was_used_by_old_finals_v3_experiments",
      ]
      row["qualification_status"] = (
          "conditional_reuse_blocked_missing_stage7_identity_evidence")
      row["recommended_action"] = (
          "fresh_collection_or_independent_supplemental_identity_evidence")
    if candidate.get("historical_trace_policy_results_exist") is True:
      row["gaps"].append(
          "historical_trace_test_policy_results_exist_recollect_test")
    rows.append(row)
  report = {
      "schema_version": "capd_proactive_stage7_candidate_audit_v1_0",
      "contract_id": stage7.CONTRACT_ID,
      "generated_at": _utc_now(),
      "stage6_entry": entry,
      "historical_commit_audit": _git_stage7_result_audit(),
      "suite_confirmation_required": True,
      "suite_confirmed": config["suite_confirmation"]["confirmed"],
      "metadata_only": True,
      "test_payload_read_for_integrity": False,
      "test_used_for_parameter_selection": False,
      "test_policy_replay_executed": False,
      "test_performance_inspected": False,
      "candidates": rows,
      "formally_reusable_trace_count": sum(
          1 for row in rows if row["reusable_now"]),
      "fresh_or_supplemental_collection_count": sum(
          1 for row in rows if not row["reusable_now"]),
      "status": stage7.IMPLEMENTED,
  }
  if output_path:
    stage7.write_json_atomic(output_path, report)
  return report


def main():
  parser = argparse.ArgumentParser(
      description="Audit Stage-7 workload candidates without Test replay.")
  parser.add_argument(
      "--config",
      default=os.path.join(
          PROJECT_ROOT, "configs", "finals",
          "capd_proactive_stage7_workloads.json"))
  parser.add_argument("--output", default=None)
  args = parser.parse_args()
  report = audit(os.path.abspath(args.config), args.output)
  print("stage6_entry={}".format(report["stage6_entry"]["status"]))
  for row in report["candidates"]:
    print("{:<28} {:<28} {}".format(
        row["workload"], row["role"], row["qualification_status"]))
  print("formally_reusable_trace_count={}".format(
      report["formally_reusable_trace_count"]))
  print("fresh_or_supplemental_collection_count={}".format(
      report["fresh_or_supplemental_collection_count"]))
  print("status={}".format(report["status"]))


if __name__ == "__main__":
  main()
