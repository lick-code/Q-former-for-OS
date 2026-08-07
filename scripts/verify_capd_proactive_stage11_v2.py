#!/usr/bin/env python3
"""Independently verify a Stage11 v2 synthetic generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from qmap import proactive_stage11_v2_guard as path_guard
from qmap import proactive_stage11_v2_verifier as verifier


def parser() -> argparse.ArgumentParser:
  value = argparse.ArgumentParser(description=__doc__)
  value.add_argument("--generation-root", required=True)
  value.add_argument("--stage8-root", required=True)
  value.add_argument("--generation-source-manifest", required=True)
  value.add_argument("--verifier-source-manifest", required=True)
  value.add_argument("--emit-verification-receipt", action="store_true")
  value.add_argument("--receipt-root")
  value.add_argument("--test-temp-root")
  value.add_argument("--negative-test-identity", default="synthetic-negative-suite")
  return value


def main(argv: list[str] | None = None) -> int:
  args = parser().parse_args(argv)
  try:
    if not args.test_temp_root:
      raise verifier.Stage11V2VerificationError(
          "Synthetic verification requires an explicit test-temp-root.")
    test_temp_root = Path(args.test_temp_root).resolve()
    generation_root = path_guard.validate_read_root(
        args.generation_root, test_temp_root)
    stage8_root = path_guard.validate_read_root(args.stage8_root, test_temp_root)
    verified = verifier.verify_generation(
        generation_root, stage8_root,
        expected_approved_plan_sha256=verifier.APPROVED_PLAN_SHA256,
        synthetic_mode=True, project_root=ROOT,
        generation_source_manifest=Path(
            args.generation_source_manifest).resolve(),
        verifier_source_manifest=Path(args.verifier_source_manifest).resolve())
    result = dict(verified)
    if args.emit_verification_receipt:
      if not args.receipt_root or not args.test_temp_root:
        raise verifier.Stage11V2VerificationError(
            "Receipt emission requires receipt-root and test-temp-root.")
      authorization = {"synthetic_test_only": True}
      capability = path_guard.authorize_write_context(
          "synthetic", args.receipt_root, verified["run_id"], authorization,
          test_temp_root=args.test_temp_root,
          production_root=ROOT / "outputs/capd_proactive_stage11_v2",
          production_enabled=False)
      result["verification_release"] = verifier.emit_verification_receipt(
          capability, verified, {
              "generation_source_manifest_sha256":
                  verified["generation_source_manifest_sha256"],
              "verifier_source_manifest_sha256":
                  verified["verifier_source_manifest_sha256"]},
          args.negative_test_identity)
    print(json.dumps(result, sort_keys=True))
    return 0
  except Exception as exc:
    print("stage11-v2-verifier: {}".format(exc), file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
