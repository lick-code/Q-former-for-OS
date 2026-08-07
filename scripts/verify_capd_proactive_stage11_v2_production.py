#!/usr/bin/env python3
"""Independent Stage11 v2 production verification/release entry point."""

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

from qmap import proactive_stage11_v2_production_guard as production_guard
from qmap import proactive_stage11_v2_production_verifier as verifier


MONITORING = {
    "monitor_interval_seconds": 5, "hard_timeout_seconds": 1800,
    "termination_grace_seconds": 10, "attempt_count": 1,
    "automatic_retry_performed": False}


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
    if monotonic() - start >= MONITORING["hard_timeout_seconds"]:
      timed_out = True
      process.terminate()
      grace = monotonic()
      while (process.poll() is None and
             monotonic() - grace < MONITORING["termination_grace_seconds"]):
        sleep(min(0.1, MONITORING["termination_grace_seconds"]))
      if process.poll() is None:
        process.kill()
      break
    sleep(MONITORING["monitor_interval_seconds"])
    samples += 1
  stdout, stderr = process.communicate()
  end = monotonic()
  monitoring = dict(MONITORING)
  monitoring.update({
      "timed_out": timed_out, "exit_code": process.returncode,
      "process_alive_sample_count": samples, "wall_clock_start": start,
      "wall_clock_end": end, "wall_clock_duration_seconds": end - start,
      "worker_pid": getattr(process, "pid", None)})
  return {"monitoring": monitoring, "stdout": stdout, "stderr": stderr,
          "success": not timed_out and process.returncode == 0}


def parser() -> argparse.ArgumentParser:
  value = argparse.ArgumentParser(description=__doc__)
  mode = value.add_mutually_exclusive_group()
  mode.add_argument("--verify-input-audit", action="store_true")
  mode.add_argument("--verify-generation", action="store_true")
  mode.add_argument("--consume-final-status", action="store_true")
  value.add_argument("--allow-real-upstream-audit", action="store_true")
  value.add_argument(
      "--config", type=Path,
      default=PROJECT_ROOT /
      "configs/finals/capd_proactive_stage11_v2_production.json")
  value.add_argument("--package", type=Path)
  value.add_argument("--expected-receipt-sha256")
  value.add_argument("--expected-manifest-sha256")
  value.add_argument("--expected-checksums-sha256")
  value.add_argument("--generation-package", type=Path)
  value.add_argument("--expected-generation-result-sha256")
  value.add_argument("--expected-generation-manifest-sha256")
  value.add_argument("--expected-generation-checksums-sha256")
  value.add_argument("--input-audit-package", type=Path)
  value.add_argument("--expected-input-audit-receipt-sha256")
  value.add_argument("--expected-input-audit-manifest-sha256")
  value.add_argument("--expected-input-audit-checksums-sha256")
  value.add_argument("--execution-authorization-package", type=Path)
  value.add_argument("--expected-execution-authorization-receipt-sha256")
  value.add_argument("--expected-execution-authorization-manifest-sha256")
  value.add_argument("--expected-execution-authorization-checksums-sha256")
  value.add_argument("--verification-package", type=Path)
  value.add_argument("--expected-verification-receipt-sha256")
  value.add_argument("--expected-verification-manifest-sha256")
  value.add_argument("--expected-verification-checksums-sha256")
  value.add_argument("--final-approval-package", type=Path)
  value.add_argument("--expected-final-approval-receipt-sha256")
  value.add_argument("--expected-final-approval-manifest-sha256")
  value.add_argument("--expected-final-approval-checksums-sha256")
  value.add_argument("--approved-plan-sha256")
  value.add_argument("--capability", type=Path)
  value.add_argument("--verification-output", type=Path)
  value.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
  value.add_argument("--worker-token", help=argparse.SUPPRESS)
  value.add_argument("--worker-input", type=Path, help=argparse.SUPPRESS)
  value.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
  return value


def _require_external_gate(args: argparse.Namespace) -> None:
  if not (args.package and args.expected_receipt_sha256 and
          args.expected_manifest_sha256 and args.expected_checksums_sha256 and
          args.approved_plan_sha256 == verifier.APPROVED_PLAN_SHA256 and
          args.capability):
    raise verifier.VerificationError(
        "Independent verification requires its exact external gate bindings.")


def _require_generation_identity_gate(args: argparse.Namespace) -> None:
  required = (
      args.input_audit_package,
      args.expected_input_audit_receipt_sha256,
      args.expected_input_audit_manifest_sha256,
      args.expected_input_audit_checksums_sha256,
      args.execution_authorization_package,
      args.expected_execution_authorization_receipt_sha256,
      args.expected_execution_authorization_manifest_sha256,
      args.expected_execution_authorization_checksums_sha256)
  if any(item is None for item in required):
    raise verifier.VerificationError(
        "Generation verification requires the exact input-audit and "
        "execution-authorization packages and external SHA bindings.")


def _require_input_audit_gate(args: argparse.Namespace) -> None:
  if not (args.package and args.expected_receipt_sha256 and
          args.expected_manifest_sha256 and args.expected_checksums_sha256 and
          args.approved_plan_sha256 == verifier.APPROVED_PLAN_SHA256):
    raise verifier.VerificationError(
        "Input-audit verification requires all exact external SHA bindings.")


def _direct_package(path: Path) -> dict[str, bytes]:
  if not path.is_dir():
    raise verifier.VerificationError("Generation package directory is missing.")
  entries = list(path.iterdir())
  if any(not item.is_file() for item in entries):
    raise verifier.VerificationError("Nested generation artifacts are forbidden.")
  return {item.name: item.read_bytes() for item in entries}


def _load_capability(path: Path, *, phase: str, identity: str,
                     output_root: Path) -> production_guard.WriteCapability:
  value = verifier.load_json_strict(path)
  if set(value) != {
      "phase", "output_root", "identity", "approved_plan_sha256", "nonce",
      "synthetic_test_only"}:
    raise verifier.VerificationError("Capability envelope field set mismatch.")
  declared_root = Path(value["output_root"])
  if not declared_root.is_absolute():
    declared_root = PROJECT_ROOT / declared_root
  if not (value["phase"] == phase and value["identity"] == identity and
          declared_root.resolve() == output_root.resolve() and
          value["approved_plan_sha256"] == verifier.APPROVED_PLAN_SHA256 and
          value["synthetic_test_only"] is False):
    raise verifier.VerificationError("Capability envelope identity mismatch.")
  return production_guard.issue_capability(
      phase=phase, output_root=output_root, identity=identity,
      approved_plan_sha256=value["approved_plan_sha256"], nonce=value["nonce"],
      synthetic_test_only=False, allow_production_root=True)


def _worker(args: argparse.Namespace) -> int:
  token = os.environ.get("CAPD_STAGE11_VERIFIER_WORKER_TOKEN")
  if not token or args.worker_token != token:
    raise verifier.VerificationError("Private verifier worker token mismatch.")
  jobs = verifier.load_json_strict(args.worker_input)
  rows = verifier.independent_cost_rows(jobs)
  Path(args.worker_output).write_bytes(verifier.canonical_json_bytes(rows))
  return 0


def verify_input_audit(args: argparse.Namespace) -> int:
  if not args.allow_real_upstream_audit:
    raise verifier.VerificationError(
        "Real upstream input-audit verification is separately gated.")
  _require_input_audit_gate(args)
  package = _direct_package(Path(args.package).resolve())
  verifier.verify_package(
      package, phase="input_audit", payload_names=verifier.INPUT_AUDIT_PAYLOADS)
  for name, expected in (
      ("input_audit_receipt.json", args.expected_receipt_sha256),
      ("manifest.json", args.expected_manifest_sha256),
      ("SHA256SUMS", args.expected_checksums_sha256)):
    if verifier.sha256_bytes(package[name]) != expected:
      raise verifier.VerificationError(
          "Input-audit external SHA mismatch: {}".format(name))
  config = verifier.load_json_strict(args.config)
  receipt = verifier.verify_input_audit_package(
      project_root=PROJECT_ROOT, package=package, config=config)
  print(json.dumps({
      "status": "input_audit_verified_pending_external_sha_approval",
      "audit_id": receipt["audit_id"],
      "repository_revision_match": receipt["repository_revision_match"],
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "stage11_execution_authorized": False,
      "stage11_formally_verified": False}, sort_keys=True))
  return 0


def verify_generation(args: argparse.Namespace) -> int:
  _require_external_gate(args)
  _require_generation_identity_gate(args)
  generation_root = Path(args.package).resolve()
  package = _direct_package(generation_root)
  verifier.verify_package(
      package, phase="generation", payload_names=verifier.GENERATION_PAYLOADS)
  checks = {
      "stage11_v2_results.json": args.expected_receipt_sha256,
      "manifest.json": args.expected_manifest_sha256,
      "SHA256SUMS": args.expected_checksums_sha256}
  for name, expected in checks.items():
    if verifier.sha256_bytes(package[name]) != expected:
      raise verifier.VerificationError(
          "Generation external SHA mismatch: {}".format(name))
  input_package = _direct_package(Path(args.input_audit_package).resolve())
  authorization_package = _direct_package(
      Path(args.execution_authorization_package).resolve())
  input_hashes = {
      "receipt_sha256": args.expected_input_audit_receipt_sha256,
      "manifest_sha256": args.expected_input_audit_manifest_sha256,
      "checksums_sha256": args.expected_input_audit_checksums_sha256}
  authorization_hashes = {
      "receipt_sha256":
          args.expected_execution_authorization_receipt_sha256,
      "manifest_sha256":
          args.expected_execution_authorization_manifest_sha256,
      "checksums_sha256":
          args.expected_execution_authorization_checksums_sha256}
  verifier.validate_external_generation_inputs(
      package, input_package, authorization_package,
      input_hashes=input_hashes, authorization_hashes=authorization_hashes)
  verifier.validate_generation_identity_chain(PROJECT_ROOT, package)
  config = json.loads(package["stage11_v2_config.json"])
  sealed = json.loads(package["sealed_frozen_tree_after.json"])
  standard_manifest = json.loads(package["standard_source_manifest.json"])
  pre_snapshot = verifier.frozen_tree_snapshot(PROJECT_ROOT)
  verifier.compare_continuity(
      sealed, [("sealed_vs_pre_verification", pre_snapshot)])
  output = Path(args.verification_output).resolve() if args.verification_output else None
  if output is None:
    raise verifier.VerificationError("Exact verification output directory is required.")
  if output.exists():
    raise verifier.VerificationError("Verification package identity already exists.")
  jobs = verifier.load_jobs_from_standard_manifest(
      PROJECT_ROOT / config["upstream"]["stage8_root"], standard_manifest)
  with tempfile.TemporaryDirectory(prefix="capd-stage11-verifier-worker-") as temp:
    temp_root = Path(temp)
    worker_input = temp_root / "jobs.json"
    worker_output = temp_root / "rows.json"
    worker_input.write_bytes(verifier.canonical_json_bytes(jobs))
    token = secrets.token_hex(32)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               "--worker-token", token, "--worker-input", str(worker_input),
               "--worker-output", str(worker_output)]
    environment = dict(os.environ)
    environment["CAPD_STAGE11_VERIFIER_WORKER_TOKEN"] = token
    supervised = supervise_process(command, cwd=PROJECT_ROOT,
                                   environment=environment)
    if not supervised["success"]:
      raise verifier.VerificationError(
          "Verifier worker failed; no automatic retry performed.")
    independent_rows = verifier.load_json_strict(worker_output)
  generation_rows = json.loads(package["stage11_v2_results.json"])["rows"]
  if independent_rows != generation_rows:
    raise verifier.VerificationError("Independent worker result differs.")
  post_snapshot = verifier.frozen_tree_snapshot(PROJECT_ROOT)
  verification_package = verifier.build_verification_package(
      generation_package=package, jobs=jobs, sealed_snapshot=sealed,
      pre_snapshot=pre_snapshot, post_snapshot=post_snapshot,
      monitoring=supervised["monitoring"])
  capability = _load_capability(
      Path(args.capability), phase="verification", identity=verifier.RUN_ID,
      output_root=output)
  try:
    verifier.write_release_package(
        capability, phase="verification", identity=verifier.RUN_ID,
        output_root=output, package=verification_package)
  except Exception:
    production_root = (
        PROJECT_ROOT / "outputs/capd_proactive_stage11_v2").resolve()
    if output.exists() and output.is_relative_to(production_root):
      shutil.rmtree(output, ignore_errors=True)
    raise
  print(json.dumps({
      "status": "stage11_generation_verified_pending_final_approval",
      "result_row_count": 192, "stage11_formally_verified": False},
      sort_keys=True))
  return 0


def _check_package_external_hashes(
    package: Mapping[str, bytes], triples: Sequence[tuple[str, str | None]],
    label: str) -> None:
  for name, expected in triples:
    if not expected or verifier.sha256_bytes(package[name]) != expected:
      raise verifier.VerificationError(
          "{} external SHA mismatch: {}".format(label, name))


def consume_final_status(args: argparse.Namespace) -> int:
  _require_external_gate(args)
  required = (
      args.generation_package, args.expected_generation_result_sha256,
      args.expected_generation_manifest_sha256,
      args.expected_generation_checksums_sha256,
      args.verification_package, args.expected_verification_receipt_sha256,
      args.expected_verification_manifest_sha256,
      args.expected_verification_checksums_sha256,
      args.final_approval_package,
      args.expected_final_approval_receipt_sha256,
      args.expected_final_approval_manifest_sha256,
      args.expected_final_approval_checksums_sha256)
  if any(item is None for item in required):
    raise verifier.VerificationError(
        "Final-status consumption requires every prior package external SHA.")
  final_root = Path(args.package).resolve()
  _load_capability(
      Path(args.capability), phase="final_status", identity=verifier.RUN_ID,
      output_root=final_root)
  generation_package = _direct_package(Path(args.generation_package).resolve())
  verification_package = _direct_package(Path(args.verification_package).resolve())
  approval_package = _direct_package(Path(args.final_approval_package).resolve())
  final_package = _direct_package(final_root)
  verifier.verify_package(
      generation_package, phase="generation",
      payload_names=verifier.GENERATION_PAYLOADS)
  verifier.verify_package(
      verification_package, phase="verification",
      payload_names=verifier.VERIFICATION_PAYLOADS)
  verifier.verify_package(
      approval_package, phase="final_approval",
      payload_names={"final_approval_receipt.json"})
  verifier.verify_package(
      final_package, phase="final_status",
      payload_names={"final_status_evidence_receipt.json"})
  _check_package_external_hashes(generation_package, (
      ("stage11_v2_results.json", args.expected_generation_result_sha256),
      ("manifest.json", args.expected_generation_manifest_sha256),
      ("SHA256SUMS", args.expected_generation_checksums_sha256)), "Generation")
  _check_package_external_hashes(verification_package, (
      ("verification_receipt.json", args.expected_verification_receipt_sha256),
      ("manifest.json", args.expected_verification_manifest_sha256),
      ("SHA256SUMS", args.expected_verification_checksums_sha256)), "Verification")
  _check_package_external_hashes(approval_package, (
      ("final_approval_receipt.json",
       args.expected_final_approval_receipt_sha256),
      ("manifest.json", args.expected_final_approval_manifest_sha256),
      ("SHA256SUMS", args.expected_final_approval_checksums_sha256)),
      "Final approval")
  _check_package_external_hashes(final_package, (
      ("final_status_evidence_receipt.json", args.expected_receipt_sha256),
      ("manifest.json", args.expected_manifest_sha256),
      ("SHA256SUMS", args.expected_checksums_sha256)), "Final status")

  verification_receipt = verifier.load_json_bytes_strict(
      verification_package["verification_receipt.json"], "verification receipt")
  approval_receipt = verifier.load_json_bytes_strict(
      approval_package["final_approval_receipt.json"], "final approval receipt")
  final_receipt = verifier.load_json_bytes_strict(
      final_package["final_status_evidence_receipt.json"],
      "final-status evidence receipt")
  verifier.validate_verification_receipt(verification_receipt)
  verification_hashes = {
      "verification_receipt_sha256": args.expected_verification_receipt_sha256,
      "verification_manifest_sha256": args.expected_verification_manifest_sha256,
      "verification_checksums_sha256": args.expected_verification_checksums_sha256}
  common = {
      field: verification_receipt[field]
      for field in verifier.COMMON_RELEASE_FIELDS if field != "schema_version"}
  verifier.validate_final_approval_receipt(
      approval_receipt, verification_hashes, inherited_bindings=common)
  inherited = {
      field: approval_receipt[field]
      for field in verifier.COMMON_RELEASE_FIELDS if field != "schema_version"}
  inherited.update(verification_hashes)
  generation_hashes = {
      "generation_result_sha256": args.expected_generation_result_sha256,
      "generation_manifest_sha256": args.expected_generation_manifest_sha256,
      "generation_checksums_sha256": args.expected_generation_checksums_sha256}
  for field, expected in generation_hashes.items():
    if final_receipt.get(field) != expected:
      raise verifier.VerificationError(
          "Final-status generation binding mismatch: {}".format(field))
  approval_hashes = {
      "final_approval_receipt_sha256":
          args.expected_final_approval_receipt_sha256,
      "final_approval_manifest_sha256":
          args.expected_final_approval_manifest_sha256,
      "final_approval_checksums_sha256":
          args.expected_final_approval_checksums_sha256}
  verifier.consume_final_status(
      final_receipt, final_approval_hashes=approval_hashes,
      inherited_bindings=inherited)
  print(json.dumps({
      "status": "stage11_final_status_evidence_verified",
      "run_id": verifier.RUN_ID, "stage11_formally_verified": True},
      sort_keys=True))
  return 0


def main(argv: Sequence[str] | None = None) -> int:
  args = parser().parse_args(argv)
  try:
    if args.worker:
      return _worker(args)
    if args.verify_input_audit:
      return verify_input_audit(args)
    if args.verify_generation:
      return verify_generation(args)
    if args.consume_final_status:
      return consume_final_status(args)
    print(json.dumps({
        "production_verifier": "implemented",
        "input_audit_verification": "PENDING_SEPARATE_GATE",
        "generation_verification": "PENDING_SEPARATE_GATE",
        "stage11_formally_verified": False}, sort_keys=True))
    return 0
  except verifier.VerificationError as exc:
    print(json.dumps({"status": "NOT_VERIFIABLE", "reason": str(exc),
                      "stage11_formally_verified": False}, sort_keys=True))
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
