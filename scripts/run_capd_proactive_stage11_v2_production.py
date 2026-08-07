#!/usr/bin/env python3
"""Stage11 v2 production capture/generation entry point."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(PROJECT_ROOT))

from qmap import proactive_stage11_v2_production as production
from qmap import proactive_stage11_v2_production_guard as production_guard


HISTORICAL_CLASSES = (
    "tests.test_capd_proactive_stage11_v2.Stage11V2NoRealUpstreamAccessTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2ApprovalChainTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2ConfigTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2SourceClosureTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2PrimitiveTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2StandardInputTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2Stage9GateTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2Stage10GateTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2AuthorizationTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2PathGuardTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2RunnerTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2VerificationTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2ReleaseTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2DocumentationTest",
    "tests.test_capd_proactive_stage11_v2.Stage11V2CompatibilityTest")
PRODUCTION_CLASSES = (
    "tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest",
    "tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest",
    "tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest",
    "tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest",
    "tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest",
    "tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest",
    "tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest",
    "tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest",
    "tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest")
LEGACY_TEST_IDS = (
    "tests.test_capd_proactive_stage10.Stage10FormalGateTest.test_historical_r1_run_directory_is_rejected",
    "tests.test_capd_proactive_stage10_v2.Stage10V2Stage9GateTest.test_real_stage9_r3_passes_complete_read_only_gate",
    "tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_dispatch_still_verifies_historical_fixture",
    "tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_and_v2_verifiers_are_bidirectionally_incompatible",
    "tests.test_capd_proactive_stage11.Stage11GateTest.test_complete_stage10a_fixture_is_blocked",
    "tests.test_capd_proactive_stage11.Stage11GateTest.test_historical_stage9_run_is_not_verifiable")


def supervise_process(
    command: Sequence[str], *, cwd: os.PathLike[str] | str,
    environment: Mapping[str, str] | None = None,
    process_factory: Callable[..., Any] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
  start = monotonic()
  process = process_factory(
      list(command), cwd=str(cwd), env=dict(environment or os.environ),
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
  samples = 1
  timed_out = False
  while process.poll() is None:
    elapsed = monotonic() - start
    if elapsed >= production.MONITORING_CONTRACT["hard_timeout_seconds"]:
      timed_out = True
      process.terminate()
      grace_start = monotonic()
      while (process.poll() is None and
             monotonic() - grace_start <
             production.MONITORING_CONTRACT["termination_grace_seconds"]):
        sleep(min(0.1, production.MONITORING_CONTRACT["termination_grace_seconds"]))
      if process.poll() is None:
        process.kill()
      break
    sleep(production.MONITORING_CONTRACT["monitor_interval_seconds"])
    samples += 1
  stdout, stderr = process.communicate()
  end = monotonic()
  return {
      "monitoring": production.monitoring_record(
          timed_out=timed_out, exit_code=process.returncode,
          sample_count=samples, wall_clock_start=start, wall_clock_end=end,
          worker_pid=getattr(process, "pid", None)),
      "stdout": stdout, "stderr": stderr,
      "success": not timed_out and process.returncode == 0,
  }


def _load_capability(path: Path, phase: str, identity: str,
                     output_root: Path) -> production_guard.WriteCapability:
  value = production.load_json_strict(path)
  production._require(set(value) == {
      "phase", "output_root", "identity", "approved_plan_sha256", "nonce",
      "synthetic_test_only"}, "Capability envelope field set mismatch.")
  declared_root = Path(value["output_root"])
  if not declared_root.is_absolute():
    declared_root = PROJECT_ROOT / declared_root
  production._require(value["phase"] == phase and value["identity"] == identity and
                      declared_root.resolve() == output_root.resolve() and
                      value["approved_plan_sha256"] == production.APPROVED_PLAN_SHA256 and
                      value["synthetic_test_only"] is False,
                      "Capability envelope identity mismatch.")
  return production_guard.issue_capability(
      phase=phase, output_root=output_root, identity=identity,
      approved_plan_sha256=value["approved_plan_sha256"],
      nonce=value["nonce"], synthetic_test_only=False,
      allow_production_root=True)


def _direct_package(path: Path) -> dict[str, bytes]:
  production._require(path.is_dir(), "Receipt package directory is missing.",
                      production.ProductionNotVerifiable)
  files = [item for item in path.iterdir() if item.is_file()]
  production._require(len(files) == len(list(path.iterdir())),
                      "Nested package members are forbidden.",
                      production.ProductionNotVerifiable)
  return {item.name: item.read_bytes() for item in files}


def _check_external_member(package: Mapping[str, bytes], name: str,
                           expected_sha256: str) -> None:
  production._require(name in package and
                      production.sha256_bytes(package[name]) == expected_sha256,
                      "External package hash mismatch: {}".format(name),
                      production.ProductionNotVerifiable)


def _execute_worker(args: argparse.Namespace) -> int:
  expected_token = os.environ.get("CAPD_STAGE11_PRODUCTION_WORKER_TOKEN")
  production._require(expected_token and args.worker_token == expected_token,
                      "Private worker supervisor token mismatch.",
                      production.ProductionBlocked)
  jobs = production.load_json_strict(args.worker_input)
  production._require(isinstance(jobs, list), "Worker input must be a job list.")
  rows = production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS,
                                       main_b_max=2)
  Path(args.worker_output).write_bytes(production.canonical_json_bytes(rows))
  return 0


def capture_input_audit(args: argparse.Namespace) -> int:
  if not args.allow_real_upstream_audit:
    raise production.ProductionBlocked(
        "Real upstream audit requires a separate Gate C authorization.")
  if not args.capability or not args.audit_output:
    raise production.ProductionBlocked(
        "Input-audit capability and exact output directory are required.")
  output = Path(args.audit_output).resolve()
  expected = (PROJECT_ROOT / production.PRODUCTION_ROOT / "input_audits" /
              production.AUDIT_ID).resolve()
  production._require(output == expected, "Input-audit output identity mismatch.")
  production._require(not output.exists(), "Input-audit identity already exists.",
                      production.ProductionBlocked)
  capability = _load_capability(
      Path(args.capability), "input_audit", production.AUDIT_ID, output)
  config = production.load_json_strict(args.config)
  production.validate_config(
      config, externally_approved_plan_sha256=args.approved_plan_sha256)
  production.validate_approved_documents(PROJECT_ROOT, config)
  generation_path = PROJECT_ROOT / config["source_manifests"]["generation"]
  verifier_path = PROJECT_ROOT / config["source_manifests"]["verifier"]
  generation_manifest = production.load_json_strict(generation_path)
  verifier_manifest = production.load_json_strict(verifier_path)
  production.validate_generation_source_manifest(PROJECT_ROOT, generation_manifest)
  production.validate_sealed_source_manifest_current_bytes(
      PROJECT_ROOT, verifier_manifest, role="verifier", expected_count=32)
  frozen_before = production.frozen_tree_snapshot(PROJECT_ROOT)
  test_pre = production.source_snapshot(PROJECT_ROOT, production.TEST_SOURCE_PATHS)

  commands = [
      ("synthetic_allowlist", list(HISTORICAL_CLASSES), 41),
      ("production_enablement", list(PRODUCTION_CLASSES), 56)]
  command_records = []
  logs: dict[str, bytes] = {}
  for command_id, test_ids, expected_count in commands:
    command = [sys.executable, "-B", "-m", "unittest", *test_ids]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    result = supervise_process(command, cwd=PROJECT_ROOT, environment=environment)
    combined = (result["stdout"] + result["stderr"]).encode("utf-8")
    production._require(result["success"] and
                        "Ran {} tests".format(expected_count) in combined.decode(
                            "utf-8", errors="replace") and
                        "OK" in combined.decode("utf-8", errors="replace"),
                        "Audit test command failed: {}".format(command_id),
                        production.ProductionNotVerifiable)
    log_name = {
        "synthetic_allowlist": "synthetic_allowlist.log",
        "production_enablement": "production_enablement_tests.log",
        "legacy_semantic": "legacy_semantic_tests.log"}[command_id]
    logs[log_name] = combined
    command_records.append({
        "command_id": command_id, "argv": command, "test_ids": test_ids,
        "expected_test_count": expected_count, "exit_code":
            result["monitoring"]["exit_code"],
        "timed_out": result["monitoring"]["timed_out"],
        "attempt_count": 1, "automatic_retry_performed": False,
        "log_sha256": production.sha256_bytes(combined)})

  stage8 = production.load_stage8_standard_source(
      PROJECT_ROOT / config["upstream"]["stage8_root"])
  stage9 = production.audit_stage9(
      PROJECT_ROOT / config["upstream"]["stage9_root"],
      PROJECT_ROOT / "configs/finals/capd_proactive_stage9_result_schema.json")
  stage10 = production.audit_stage10(
      PROJECT_ROOT / config["upstream"]["stage10_root"],
      config["stage10_external_anchors"])
  production._require(stage9["status"] == "verified" and
                      stage10["status"] == "verified",
                      "Real upstream semantic gates failed.",
                      production.ProductionNotVerifiable)
  audit_stdout = {
      "real_upstream_audit": "COMPLETED", "stage8_input_verified": True,
      "stage9_input_authorized": True, "stage10_input_authorized": True,
      "generation_source_manifest_verified": True,
      "verifier_source_manifest_verified": True,
      "generation_source_set_match":
          stage10["generation_source_set_match"],
      "repository_revision_match": stage10["repository_revision_match"],
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "stage11_execution_authorized": False, "stage11_formally_verified": False}

  legacy_command = [sys.executable, "-B", "-m", "unittest", *LEGACY_TEST_IDS]
  legacy_environment = dict(os.environ)
  legacy_environment["PYTHONDONTWRITEBYTECODE"] = "1"
  legacy_environment["PYTHONPATH"] = str(PROJECT_ROOT)
  legacy_result = supervise_process(
      legacy_command, cwd=PROJECT_ROOT, environment=legacy_environment)
  legacy_bytes = (legacy_result["stdout"] + legacy_result["stderr"]).encode("utf-8")
  production._require(
      legacy_result["success"] and "Ran 6 tests" in legacy_bytes.decode(
          "utf-8", errors="replace") and
      "OK" in legacy_bytes.decode("utf-8", errors="replace"),
      "Audit legacy semantic command failed.",
      production.ProductionNotVerifiable)
  logs["legacy_semantic_tests.log"] = legacy_bytes
  command_records.append({
      "command_id": "legacy_semantic", "argv": legacy_command,
      "test_ids": list(LEGACY_TEST_IDS), "expected_test_count": 6,
      "exit_code": legacy_result["monitoring"]["exit_code"],
      "timed_out": legacy_result["monitoring"]["timed_out"],
      "attempt_count": 1, "automatic_retry_performed": False,
      "log_sha256": production.sha256_bytes(legacy_bytes)})
  test_post = production.source_snapshot(PROJECT_ROOT, production.TEST_SOURCE_PATHS)
  test_identity = production.test_source_identity(PROJECT_ROOT, test_pre, test_post)
  frozen_after = production.frozen_tree_snapshot(PROJECT_ROOT)
  audit_commands = {
      "schema_version": "capd_proactive_stage11_v2_audit_commands_v1_0",
      "contract_id": production.CONTRACT_ID, "audit_id": production.AUDIT_ID,
      "cwd": ".", "python_executable_sha256":
          production.sha256_file(sys.executable),
      "python_version": sys.version, "commands": command_records,
      "real_upstream_audit": {"argv": [
          sys.executable, str(Path(__file__).resolve()), "--capture-input-audit",
          "--allow-real-upstream-audit"], "exit_code": 0, "timed_out": False,
          "attempt_count": 1, "automatic_retry_performed": False}}
  package = production.build_input_audit_package(
      project_root=PROJECT_ROOT, config=config, stage8_source=stage8,
      stage9_receipt=stage9, stage10_receipt=stage10,
      generation_source_manifest=generation_manifest,
      verifier_source_manifest=verifier_manifest,
      test_identity=test_identity, audit_commands=audit_commands,
      synthetic_log=logs["synthetic_allowlist.log"],
      production_log=logs["production_enablement_tests.log"],
      legacy_log=logs["legacy_semantic_tests.log"],
      audit_stdout=audit_stdout, frozen_before=frozen_before,
      frozen_after=frozen_after)
  production.write_phase_package(
      capability, phase="input_audit", identity=production.AUDIT_ID,
      output_root=output, package=package)
  print(json.dumps(audit_stdout, sort_keys=True))
  return 0


def execute_production(args: argparse.Namespace) -> int:
  required = (
      args.authorization_receipt, args.authorization_receipt_sha256,
      args.authorization_manifest_sha256, args.authorization_checksums_sha256,
      args.input_audit_receipt_sha256, args.input_audit_manifest_sha256,
      args.input_audit_checksums_sha256, args.approved_plan_sha256,
      args.capability)
  if any(item is None for item in required):
    raise production.ProductionBlocked(
        "Production execution requires all externally approved receipt hashes.")
  config_path = Path(args.config).resolve()
  config = production.load_json_strict(config_path)
  production.validate_config(
      config, externally_approved_plan_sha256=args.approved_plan_sha256)
  generation_manifest_path = PROJECT_ROOT / config["source_manifests"]["generation"]
  verifier_manifest_path = PROJECT_ROOT / config["source_manifests"]["verifier"]
  production._require(generation_manifest_path.is_file() and
                      verifier_manifest_path.is_file(),
                      "Production source manifests are not frozen (Gate B pending).",
                      production.ProductionNotVerifiable)
  generation_manifest = production.load_json_strict(generation_manifest_path)
  verifier_manifest = production.load_json_strict(verifier_manifest_path)
  production.validate_generation_source_manifest(PROJECT_ROOT, generation_manifest)
  production.validate_sealed_source_manifest_current_bytes(
      PROJECT_ROOT, verifier_manifest, role="verifier", expected_count=32)

  production._require(args.input_audit_package and args.authorization_package,
                      "Both sealed receipt package directories are required.",
                      production.ProductionBlocked)
  input_package = _direct_package(Path(args.input_audit_package).resolve())
  production.validate_package_bytes(
      input_package, phase="input_audit",
      expected_members=production.INPUT_AUDIT_PAYLOADS)
  _check_external_member(input_package, "input_audit_receipt.json",
                         args.input_audit_receipt_sha256)
  _check_external_member(input_package, "manifest.json",
                         args.input_audit_manifest_sha256)
  _check_external_member(input_package, "SHA256SUMS",
                         args.input_audit_checksums_sha256)
  authorization_package = _direct_package(Path(args.authorization_package).resolve())
  production.validate_package_bytes(
      authorization_package, phase="execution_authorization",
      expected_members={"execution_authorization_receipt.json"})
  _check_external_member(authorization_package,
                         "execution_authorization_receipt.json",
                         args.authorization_receipt_sha256)
  _check_external_member(authorization_package, "manifest.json",
                         args.authorization_manifest_sha256)
  _check_external_member(authorization_package, "SHA256SUMS",
                         args.authorization_checksums_sha256)
  authorization_receipt_path = Path(args.authorization_receipt).resolve()
  production._require(
      authorization_receipt_path ==
      (Path(args.authorization_package).resolve() /
       "execution_authorization_receipt.json") and
      production.sha256_file(authorization_receipt_path) ==
      args.authorization_receipt_sha256 and
      authorization_receipt_path.read_bytes() ==
      authorization_package["execution_authorization_receipt.json"],
      "Execution authorization receipt path/bytes differ from sealed package.",
      production.ProductionNotVerifiable)

  production._require(
      production.is_canonical_json_bytes(input_package["input_audit_receipt.json"]) and
      production.is_canonical_json_bytes(
          authorization_package["execution_authorization_receipt.json"]),
      "Receipt package contains non-canonical JSON.",
      production.ProductionNotVerifiable)
  input_receipt = json.loads(input_package["input_audit_receipt.json"])
  authorization = json.loads(
      authorization_package["execution_authorization_receipt.json"])
  input_hashes = {
      "receipt_sha256": args.input_audit_receipt_sha256,
      "manifest_sha256": args.input_audit_manifest_sha256,
      "checksums_sha256": args.input_audit_checksums_sha256}
  production.validate_input_audit_receipt(
      input_receipt, expected_plan_sha256=args.approved_plan_sha256)
  production.validate_execution_authorization(
      authorization, config, input_receipt,
      expected_plan_sha256=args.approved_plan_sha256,
      input_audit_external_hashes=input_hashes)
  production._require(
      input_receipt["generation_source_manifest_sha256"] ==
      production.sha256_file(generation_manifest_path) and
      input_receipt["generation_source_members_sha256"] ==
      generation_manifest["members_sha256"] and
      input_receipt["verifier_source_manifest_sha256"] ==
      production.sha256_file(verifier_manifest_path) and
      input_receipt["verifier_source_members_sha256"] ==
      verifier_manifest["members_sha256"],
      "Input audit does not bind the frozen source manifest files.",
      production.ProductionNotVerifiable)

  canonical_names = (
      "stage8_standard_input_receipt.json", "stage9_input_receipt.json",
      "stage10_input_receipt.json", "standard_source_manifest.json")
  canonical_values = {}
  for name in canonical_names:
    production._require(production.is_canonical_json_bytes(input_package[name]),
                        "Sealed canonical input object is non-canonical.",
                        production.ProductionNotVerifiable)
    canonical_values[name] = json.loads(input_package[name])
  sealed_snapshot = json.loads(input_package["frozen_tree_after.json"])
  current_snapshot = production.frozen_tree_snapshot(PROJECT_ROOT)
  output_root = (PROJECT_ROOT / config["output_root"]).resolve()
  run_root = output_root / production.RUN_ID
  production.preflight_before_mkdir(
      output_dir=run_root, sealed_snapshot=sealed_snapshot,
      current_snapshot=current_snapshot, config=config,
      externally_approved_plan_sha256=args.approved_plan_sha256,
      input_audit_receipt=input_receipt,
      authorization_receipt=authorization,
      input_audit_external_hashes=input_hashes)
  jobs = production.load_jobs_from_sealed_manifest(
      PROJECT_ROOT / config["upstream"]["stage8_root"],
      canonical_values["standard_source_manifest.json"])

  with tempfile.TemporaryDirectory(prefix="capd-stage11-production-worker-") as temp:
    temp_root = Path(temp)
    worker_input = temp_root / "jobs.json"
    worker_output = temp_root / "rows.json"
    worker_input.write_bytes(production.canonical_json_bytes(jobs))
    token = secrets.token_hex(32)
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker",
        "--worker-token", token, "--worker-input", str(worker_input),
        "--worker-output", str(worker_output)]
    environment = dict(os.environ)
    environment["CAPD_STAGE11_PRODUCTION_WORKER_TOKEN"] = token
    supervised = supervise_process(
        command, cwd=PROJECT_ROOT, environment=environment)
    production._require(supervised["success"],
                        "Production worker failed; no automatic retry performed.",
                        production.ProductionNotVerifiable)
    rows = production.load_json_strict(worker_output)

  post_snapshot = production.frozen_tree_snapshot(PROJECT_ROOT)
  production.assert_continuity(
      sealed_snapshot, post_snapshot, "sealed_vs_post_generation")
  input_binding = {
      "schema_version": "capd_proactive_stage11_v2_input_audit_binding_v1_0",
      "contract_id": production.CONTRACT_ID, "audit_id": production.AUDIT_ID,
      "package_path": Path(args.input_audit_package).resolve().as_posix(),
      **input_hashes}
  authorization_binding = {
      "schema_version":
          "capd_proactive_stage11_v2_production_execution_authorization_binding_v1_0",
      "contract_id": production.CONTRACT_ID, "run_id": production.RUN_ID,
      "package_path": Path(args.authorization_package).resolve().as_posix(),
      "receipt_sha256": args.authorization_receipt_sha256,
      "manifest_sha256": args.authorization_manifest_sha256,
      "checksums_sha256": args.authorization_checksums_sha256}
  package = production.build_generation_package(
      project_root=PROJECT_ROOT, config=config,
      input_audit_binding=input_binding,
      authorization_binding=authorization_binding,
      input_audit_receipt=input_receipt,
      authorization_receipt=authorization,
      stage8_receipt=canonical_values["stage8_standard_input_receipt.json"],
      stage9_receipt=canonical_values["stage9_input_receipt.json"],
      stage10_receipt=canonical_values["stage10_input_receipt.json"],
      standard_manifest=canonical_values["standard_source_manifest.json"],
      generation_source_manifest=generation_manifest,
      verifier_source_manifest=verifier_manifest,
      sealed_snapshot=sealed_snapshot, pre_snapshot=current_snapshot,
      post_snapshot=post_snapshot, rows=rows,
      monitoring=supervised["monitoring"])
  temporary_run = output_root / ("." + production.RUN_ID + ".generation-staging")
  production._require(not temporary_run.exists(),
                      "Production staging identity already exists.",
                      production.ProductionBlocked)
  capability = _load_capability(
      Path(args.capability), "generation", production.RUN_ID, temporary_run)
  try:
    production.write_phase_package(
        capability, phase="generation", identity=production.RUN_ID,
        output_root=temporary_run, package=package)
    production._require(not run_root.exists(), "Production run ID already exists.",
                        production.ProductionBlocked)
    os.replace(temporary_run, run_root)
  except Exception:
    if temporary_run.exists() and temporary_run.is_relative_to(output_root):
      shutil.rmtree(temporary_run, ignore_errors=True)
    raise
  print(json.dumps({
      "status": "stage11_generation_complete_pending_independent_verification",
      "run_id": production.RUN_ID, "result_row_count": 192,
      "stage11_formally_verified": False}, sort_keys=True))
  return 0


def parser() -> argparse.ArgumentParser:
  value = argparse.ArgumentParser(description=__doc__)
  value.add_argument(
      "--config", type=Path,
      default=PROJECT_ROOT / "configs/finals/capd_proactive_stage11_v2_production.json")
  mode = value.add_mutually_exclusive_group()
  mode.add_argument("--capture-input-audit", action="store_true")
  mode.add_argument("--execute-production", action="store_true")
  value.add_argument("--allow-real-upstream-audit", action="store_true")
  value.add_argument("--audit-output", type=Path)
  value.add_argument("--capability", type=Path)
  value.add_argument("--authorization-receipt", type=Path)
  value.add_argument("--input-audit-package", type=Path)
  value.add_argument("--authorization-package", type=Path)
  value.add_argument("--authorization-receipt-sha256")
  value.add_argument("--authorization-manifest-sha256")
  value.add_argument("--authorization-checksums-sha256")
  value.add_argument("--input-audit-receipt-sha256")
  value.add_argument("--input-audit-manifest-sha256")
  value.add_argument("--input-audit-checksums-sha256")
  value.add_argument("--approved-plan-sha256")
  value.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
  value.add_argument("--worker-token", help=argparse.SUPPRESS)
  value.add_argument("--worker-input", type=Path, help=argparse.SUPPRESS)
  value.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
  return value


def main(argv: Sequence[str] | None = None) -> int:
  args = parser().parse_args(argv)
  try:
    if args.worker:
      return _execute_worker(args)
    if args.capture_input_audit:
      return capture_input_audit(args)
    if args.execute_production:
      return execute_production(args)
    print(json.dumps({
        "production_revision": production.PRODUCTION_REVISION,
        "input_audit": "PENDING_SEPARATE_GATE",
        "production_generation": "BLOCKED",
        "real_upstream_audit": "NOT_RUN",
        "stage11_formally_verified": False}, sort_keys=True))
    return 0
  except production.ProductionContractError as exc:
    print(json.dumps({"status": "BLOCKED", "reason": str(exc),
                      "stage11_formally_verified": False}, sort_keys=True))
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
