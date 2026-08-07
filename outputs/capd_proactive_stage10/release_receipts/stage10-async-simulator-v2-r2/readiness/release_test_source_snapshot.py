"""Release-only tests and Stage11 negative-audit worker for Stage10 v2-r2."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qmap import proactive_stage10_v2_r2 as contract


def _documentation_root() -> Path:
    override = os.environ.get("CAPD_STAGE10_RELEASE_DOCUMENT_ROOT")
    return Path(override).resolve() if override else ROOT


class Stage10V2R2ReadinessDocumentationTest(unittest.TestCase):
    def test_pending_status_and_interpretation_boundary(self):
        root = _documentation_root()
        protocol = (root / "docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md").read_text(
            encoding="utf-8")
        status = (root / "docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md").read_text(
            encoding="utf-8")
        combined = protocol + "\n" + status
        for token in (
            "stage10-async-simulator-v2-r1",
            "candidate_evidence",
            "stage10-async-simulator-v2-r2",
            "generation_verified",
            "release_pending",
            "real_system_async_performance_verified=false",
        ):
            self.assertIn(token, combined)
        self.assertNotIn("real_system_async_performance_verified=true", combined)


class Stage10V2R2FinalStatusDocumentationTest(unittest.TestCase):
    def test_completion_decision_is_already_observed(self):
        root = _documentation_root()
        protocol = (root / "docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md").read_text(
            encoding="utf-8")
        status = (root / "docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md").read_text(
            encoding="utf-8")
        combined = protocol + "\n" + status
        self.assertIn("completion_decision=approved_for_status_finalization", status)
        self.assertIn(
            "release_receipts/stage10-async-simulator-v2-r2/final-status", status)
        self.assertIn("real_system_async_performance_verified=false", combined)
        self.assertNotIn("real_system_async_performance_verified=true", combined)


def _stable_result(receipt):
    return {key: receipt[key] for key in
            ("status", "reason_code", "formal_authorized")}


def run_stage11_negative_audit(stage10a_root: Path, stage10_r2_root: Path):
    from qmap.proactive_stage11 import audit_stage10_fixture

    result = {
        "schema_version": "capd_proactive_stage10_stage11_negative_audit_result_v1_0",
        "stage10a": _stable_result(audit_stage10_fixture(stage10a_root)),
        "stage10_r2": _stable_result(audit_stage10_fixture(stage10_r2_root)),
        "stage11_positive_migration_authorized": False,
    }
    expected = dict(contract.STAGE11_EXPECTED)
    if ({key: result[key] for key in expected} != expected):
        raise contract.Stage10V2R2ContractError(
            "Stage11 negative-audit result is not the exact frozen contract.")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage11-negative-audit-worker", action="store_true")
    parser.add_argument("--stage10a-run-root")
    parser.add_argument("--stage10-r2-run-root")
    parser.add_argument("--approved-freeze-receipt-sha256")
    args = parser.parse_args(argv)
    if not args.stage11_negative_audit_worker:
        parser.error("Only the Stage11 negative-audit worker is a module CLI mode.")
    try:
        supplied = args.approved_freeze_receipt_sha256
        if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
            raise contract.Stage10V2R2ContractError(
                "Exact approved freeze-receipt SHA256 is required.")
        receipt = ROOT / contract.FREEZE_RECEIPT_PATH
        if not receipt.is_file() or contract.sha256_file(receipt) != supplied:
            raise contract.Stage10V2R2ContractError(
                "Approved freeze-receipt SHA256 does not match the repository.")
        config = contract.load_json(ROOT / contract.CONFIG_PATH)
        contract.validate_freeze_receipt(
            contract.load_json(receipt), config, ROOT)
        result = run_stage11_negative_audit(
            Path(args.stage10a_run_root), Path(args.stage10_r2_run_root))
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, contract.Stage10V2R2ContractError) as exc:
        print("stage10-v2-r2-stage11-audit: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
