"""Phase-bound write capabilities for Stage11 v2 production packages."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import FrozenSet, Iterable


CONTRACT_ID = "CAPD-PROACTIVE-STAGE11-2.0"
APPROVED_PLAN_SHA256 = (
    "5ada02d3cd2f14c116dccbf4336dc833c460c3d7198e58eb17efd72f0bc66143")
PRODUCTION_ROOT = "outputs/capd_proactive_stage11_v2"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PHASES = (
    "input_audit", "execution_authorization", "generation", "verification",
    "final_approval", "final_status")

PHASE_ARTIFACTS = {
    "input_audit": frozenset({
        "audit_identity.json", "audit_commands.json", "synthetic_allowlist.log",
        "production_enablement_tests.log", "legacy_semantic_tests.log",
        "real_upstream_audit_stdout.json", "stage8_standard_input_receipt.json",
        "stage9_input_receipt.json", "stage10_input_receipt.json",
        "standard_source_manifest.json", "frozen_tree_before.json",
        "frozen_tree_after.json", "frozen_tree_comparison.json",
        "source_identity.json", "test_source_identity.json",
        "input_audit_receipt.json", "manifest.json", "SHA256SUMS"}),
    "execution_authorization": frozenset({
        "execution_authorization_receipt.json", "manifest.json", "SHA256SUMS"}),
    "generation": frozenset({
        "stage11_v2_config.json", "run_identity.json", "run_state.json",
        "input_audit_binding.json", "input_audit_receipt.json",
        "execution_authorization_binding.json",
        "execution_authorization_receipt.json",
        "stage8_standard_input_receipt.json", "stage9_input_receipt.json",
        "stage10_input_receipt.json", "standard_source_manifest.json",
        "frozen_grid.json", "generation_source_manifest.json",
        "verifier_source_manifest.json", "sealed_frozen_tree_after.json",
        "pre_generation_continuity_snapshot.json",
        "post_generation_continuity_snapshot.json",
        "generation_continuity_comparison.json", "stage11_v2_results.json",
        "stage11_v2_results.csv", "stage11_v2_report.md", "manifest.json",
        "SHA256SUMS"}),
    "verification": frozenset({
        "verification_receipt.json", "sealed_frozen_tree_after.json",
        "pre_verification_continuity_snapshot.json",
        "post_verification_continuity_snapshot.json",
        "verification_continuity_comparison.json", "manifest.json",
        "SHA256SUMS"}),
    "final_approval": frozenset({
        "final_approval_receipt.json", "manifest.json", "SHA256SUMS"}),
    "final_status": frozenset({
        "final_status_evidence_receipt.json", "manifest.json", "SHA256SUMS"}),
}


class ProductionPathError(ValueError):
  """Raised when a write capability or target violates the frozen contract."""


_SECRET = secrets.token_bytes(32)
_NONCE_BINDINGS: dict[str, str] = {}


def _require(condition: object, message: str) -> None:
  if not condition:
    raise ProductionPathError(message)


def _is_sha256(value: object) -> bool:
  return (isinstance(value, str) and len(value) == 64 and
          all(char in "0123456789abcdef" for char in value))


def _binding_text(phase: str, output_root: str, identity: str,
                  approved_plan_sha256: str, nonce: str,
                  artifacts: Iterable[str], synthetic_test_only: bool) -> str:
  return "\n".join((
      CONTRACT_ID, phase, output_root, identity, approved_plan_sha256, nonce,
      ",".join(sorted(artifacts)), str(synthetic_test_only).lower()))


@dataclass(frozen=True)
class WriteCapability:
  phase: str
  output_root: str
  identity: str
  approved_plan_sha256: str
  nonce: str
  allowed_artifacts: FrozenSet[str]
  synthetic_test_only: bool
  signature: str


def issue_capability(*, phase: str, output_root: os.PathLike[str] | str,
                     identity: str, approved_plan_sha256: str, nonce: str,
                     synthetic_test_only: bool,
                     allow_production_root: bool = False) -> WriteCapability:
  _require(phase in PHASES, "Unknown Stage11 production capability phase.")
  _require(_is_sha256(approved_plan_sha256), "Approved plan SHA is invalid.")
  _require(approved_plan_sha256 == APPROVED_PLAN_SHA256,
           "Approved plan SHA does not match the frozen external identity.")
  _require(isinstance(identity, str) and identity,
           "A non-empty audit or run identity is required.")
  _require(isinstance(nonce, str) and len(nonce) >= 16,
           "A one-time nonce of at least 16 characters is required.")
  root = Path(output_root).resolve()
  production = (REPOSITORY_ROOT / PRODUCTION_ROOT).resolve()
  if root == production or production in root.parents:
    _require(allow_production_root and not synthetic_test_only,
             "Production output requires a separately authorized capability.")
  else:
    _require(synthetic_test_only,
             "Non-production capabilities must be marked synthetic_test_only.")
  root_text = root.as_posix()
  artifacts = PHASE_ARTIFACTS[phase]
  binding = _binding_text(phase, root_text, identity, approved_plan_sha256,
                          nonce, artifacts, synthetic_test_only)
  binding_sha = hashlib.sha256(binding.encode("utf-8")).hexdigest()
  prior = _NONCE_BINDINGS.setdefault(nonce, binding_sha)
  _require(prior == binding_sha, "Capability nonce was reused across bindings.")
  signature = hmac.new(_SECRET, binding.encode("utf-8"), hashlib.sha256).hexdigest()
  return WriteCapability(
      phase=phase, output_root=root_text, identity=identity,
      approved_plan_sha256=approved_plan_sha256, nonce=nonce,
      allowed_artifacts=artifacts, synthetic_test_only=synthetic_test_only,
      signature=signature)


def validate_capability(capability: WriteCapability, *, phase: str,
                        identity: str, output_root: os.PathLike[str] | str,
                        artifact: str) -> Path:
  _require(isinstance(capability, WriteCapability),
           "A genuine Stage11 write capability is required.")
  _require(phase in PHASES and capability.phase == phase,
           "Capability phase is not interchangeable.")
  _require(capability.identity == identity,
           "Capability audit/run identity mismatch.")
  _require(capability.approved_plan_sha256 == APPROVED_PLAN_SHA256,
           "Capability approved-plan identity mismatch.")
  _require(capability.allowed_artifacts == PHASE_ARTIFACTS[phase],
           "Capability artifact set changed.")
  pure = PurePosixPath(artifact)
  _require(artifact == pure.as_posix() and not pure.is_absolute() and
           len(pure.parts) == 1 and artifact not in (".", ".."),
           "Artifact path must be one canonical package member name.")
  _require(artifact in capability.allowed_artifacts,
           "Capability cannot write this phase artifact.")
  root = Path(output_root).resolve()
  _require(root.as_posix() == capability.output_root,
           "Capability output root mismatch.")
  binding = _binding_text(
      capability.phase, capability.output_root, capability.identity,
      capability.approved_plan_sha256, capability.nonce,
      capability.allowed_artifacts, capability.synthetic_test_only)
  expected = hmac.new(_SECRET, binding.encode("utf-8"), hashlib.sha256).hexdigest()
  _require(hmac.compare_digest(expected, capability.signature),
           "Capability signature mismatch.")
  return _safe_child(root, artifact)


def _has_reparse_point(path: Path) -> bool:
  try:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
  except OSError:
    return False
  return bool(attributes & 0x400)


def _safe_child(root: Path, artifact: str) -> Path:
  root = root.resolve()
  current = root
  for part in PurePosixPath(artifact).parts:
    current = current / part
    if current.exists() or current.is_symlink():
      _require(not current.is_symlink() and not _has_reparse_point(current),
               "Symlink/reparse targets are forbidden.")
  target = (root / artifact).resolve()
  _require(target.parent == root, "Artifact target escapes package root.")
  return target


def guarded_write_bytes(capability: WriteCapability, *, phase: str,
                        identity: str, output_root: os.PathLike[str] | str,
                        artifact: str, data: bytes) -> Path:
  _require(isinstance(data, bytes), "Writer payload must be bytes.")
  target = validate_capability(
      capability, phase=phase, identity=identity, output_root=output_root,
      artifact=artifact)
  root = Path(output_root).resolve()
  root.mkdir(parents=True, exist_ok=True)
  target = _safe_child(root, artifact)
  _require(not target.exists(), "Sealed artifact overwrite is forbidden.")
  with open(target, "xb") as handle:
    handle.write(data)
  return target


def reset_test_nonce_registry() -> None:
  """Clear process-local nonce state; only synthetic tests should call this."""
  _NONCE_BINDINGS.clear()
