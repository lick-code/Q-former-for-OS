"""Contract tests for the CAPD Stage10 v2-r2 source-identity migration."""

from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from qmap import proactive_stage10_v2_r2 as contract


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


def load_r2_runner():
    path = ROOT / "scripts/run_capd_proactive_stage10_v2_r2.py"
    spec = importlib.util.spec_from_file_location("capd_stage10_v2_r2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Stage10 v2-r2 runner")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


class Stage10V2R2SourceManifestTest(unittest.TestCase):
    def _entry(self, root: Path, relative: str, *, role: str = "runtime"):
        return {
            "logical_name": relative.replace("/", "__"),
            "path": relative,
            "role": role,
            "sha256": contract.sha256_file(root / relative),
            "generation_identity": True,
            "generation_test_groups": ["generation_core"],
        }

    def test_exact_manifest_and_current_snapshot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "qmap").mkdir()
            (root / "qmap/core.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = {
                "schema_version": contract.SOURCE_MANIFEST_SCHEMA,
                "source_set_id": contract.SOURCE_SET_ID,
                "entries": [self._entry(root, "qmap/core.py")],
            }
            validated = contract.validate_source_manifest(manifest, root)
            snapshot = contract.snapshot_generation_sources(root, validated)
            self.assertEqual(snapshot["entry_count"], 1)
            self.assertEqual(snapshot["entries"], manifest["entries"])

    def test_path_sort_sha_and_stage11_leakage_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "qmap").mkdir()
            (root / "qmap/a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "qmap/b.py").write_text("VALUE = 2\n", encoding="utf-8")
            entries = [self._entry(root, "qmap/a.py"), self._entry(root, "qmap/b.py")]
            for changed in (
                list(reversed(entries)),
                [dict(entries[0], path="../qmap/a.py")],
                [dict(entries[0], sha256="0" * 64)],
                [dict(entries[0], path="qmap/proactive_stage11.py")],
            ):
                manifest = {
                    "schema_version": contract.SOURCE_MANIFEST_SCHEMA,
                    "source_set_id": contract.SOURCE_SET_ID,
                    "entries": changed,
                }
                with self.assertRaises(contract.Stage10V2R2ContractError):
                    contract.validate_source_manifest(manifest, root)

    def test_static_stage11_import_and_dependency_omission_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "qmap").mkdir()
            (root / "qmap/core.py").write_text(
                "from qmap import helper\nfrom qmap.proactive_stage11 import audit_stage10_fixture\n",
                encoding="utf-8",
            )
            (root / "qmap/helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = {
                "schema_version": contract.SOURCE_MANIFEST_SCHEMA,
                "source_set_id": contract.SOURCE_SET_ID,
                "entries": [self._entry(root, "qmap/core.py")],
            }
            with self.assertRaises(contract.Stage10V2R2ContractError):
                contract.validate_source_manifest(manifest, root)

            (root / "qmap/core.py").write_text(
                "from qmap import helper\n", encoding="utf-8")
            manifest["entries"][0]["sha256"] = contract.sha256_file(root / "qmap/core.py")
            with self.assertRaises(contract.Stage10V2R2ContractError):
                contract.validate_source_manifest(manifest, root)


class Stage10V2R2ConfigSchemaTest(unittest.TestCase):
    def _config(self):
        legacy = json.loads(
            (ROOT / "configs/finals/capd_proactive_stage10_v2.json").read_text(
                encoding="utf-8"))
        value = dict(legacy)
        value.update({
            "schema_version": contract.CONFIG_SCHEMA_VERSION,
            "run_id": contract.RUN_ID,
            "approved_design": {
                "path": contract.APPROVED_DESIGN_PATH,
                "sha256": contract.APPROVED_DESIGN_SHA256,
                "status": "design_approved",
            },
            "approved_plan": {
                "path": contract.APPROVED_PLAN_PATH,
                "sha256": contract.APPROVED_PLAN_SHA256,
                "status": "implementation_plan_approved_tasks_0_9",
            },
            "generation_source_manifest": {
                "path": contract.SOURCE_MANIFEST_PATH,
                "sha256": "1" * 64,
                "schema_version": contract.SOURCE_MANIFEST_SCHEMA,
                "source_set_id": contract.SOURCE_SET_ID,
                "entry_count": 11,
                "fingerprint_sha256": "2" * 64,
            },
            "generation_freeze_receipt": {
                "path": contract.FREEZE_RECEIPT_PATH,
                "schema_version": contract.FREEZE_RECEIPT_SCHEMA,
            },
            "metadata_schemas": {
                name: {"path": f"configs/finals/{name}.json", "sha256": "3" * 64}
                for name in contract.METADATA_SCHEMA_VERSIONS
            },
            "controlled_execution": dict(contract.CONTROLLED_EXECUTION),
            "generation_tests": {
                "interpreter_policy": "current_runner_sys_executable",
                "argv_suffix": list(contract.GENERATION_TEST_ARGV_SUFFIX),
                "expected_test_count": 1,
                "ordered_verbose_test_ids": ["synthetic.test"],
            },
            "formal_simulation_worker": {
                "interpreter_policy": "current_runner_sys_executable",
                "argv_suffix": list(contract.FORMAL_WORKER_ARGV_SUFFIX),
            },
            "release_contract": contract.expected_release_contract("1" * 64),
        })
        value.pop("test_evidence")
        return value

    def test_complete_r2_config_structure_passes(self):
        value = self._config()
        self.assertIs(contract.validate_config(value), value)

    def test_identity_semantics_and_execution_tamper_fail(self):
        mutations = [
            ("run_id", "stage10-async-simulator-v2-r1"),
            ("output_root", "outputs/elsewhere"),
            ("timing_source", {"source_run_id": "forged"}),
            ("controlled_execution", dict(contract.CONTROLLED_EXECUTION,
                                           automatic_retry_allowed=True)),
        ]
        for field, replacement in mutations:
            value = self._config()
            value[field] = replacement
            with self.subTest(field=field):
                with self.assertRaises(contract.Stage10V2R2ContractError):
                    contract.validate_config(value)

        value = self._config()
        value["arrival_profiles"][0]["load_ratio"] = "9.9"
        with self.assertRaises(contract.Stage10V2R2ContractError):
            contract.validate_config(value)

        value = self._config()
        value["unexpected"] = True
        with self.assertRaises(contract.Stage10V2R2ContractError):
            contract.validate_config(value)


class Stage10V2R2FreezeReceiptTest(unittest.TestCase):
    def test_repository_receipt_is_completely_reconstructed(self):
        config_path = ROOT / contract.CONFIG_PATH
        receipt_path = ROOT / contract.FREEZE_RECEIPT_PATH
        if not config_path.is_file() or not receipt_path.is_file():
            self.skipTest("Task 9 freeze candidate has not been generated yet")
        config = contract.load_json(config_path)
        receipt = contract.load_json(receipt_path)
        self.assertIs(
            contract.validate_freeze_receipt(receipt, config, ROOT), receipt)

        changed = json.loads(json.dumps(receipt))
        changed["authorization_state"][
            "formal_run_authorized_at_receipt_creation"] = True
        with self.assertRaises(contract.Stage10V2R2ContractError):
            contract.validate_freeze_receipt(changed, config, ROOT)


class Stage10V2R2GenerationIsolationTest(unittest.TestCase):
    def test_generation_runtime_has_not_loaded_stage11(self):
        loaded = sorted(
            name for name in sys.modules
            if "proactive_stage11" in name or "test_capd_proactive_stage11" in name)
        self.assertEqual(loaded, [])


class Stage10V2R2ControlledGenerationTestTest(unittest.TestCase):
    def test_verbose_unittest_log_returns_canonical_test_identity(self):
        runner = load_r2_runner()
        identity = (
            "tests.test_capd_proactive_stage10.Stage10ArrivalTest."
            "test_burst_model_keeps_base_flow_before_inside_and_after_bursts")
        method = identity.rsplit(".", 1)[-1]
        log = (
            f"{method} ({identity}) ... ok\n\n"
            "----------------------------------------------------------------------\n"
            "Ran 1 test in 0.001s\n\nOK\n")
        count, identities = runner._parse_unittest_log(log)
        self.assertEqual(count, 1)
        self.assertEqual(identities, [identity])

    def test_external_approved_sha_is_required_and_recomputed(self):
        runner = load_r2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "freeze.json"
            receipt.write_text("{}\n", encoding="utf-8")
            digest = contract.sha256_file(receipt)
            self.assertEqual(
                runner.validate_approved_freeze_sha(digest, receipt), digest)
            for changed in (None, digest.upper(), "0" * 64):
                with self.assertRaises(contract.Stage10V2R2ContractError):
                    runner.validate_approved_freeze_sha(changed, receipt)

    def test_controlled_process_records_environment_and_single_execution(self):
        runner = load_r2_runner()
        result = runner.run_controlled_process(
            [sys.executable, "-c", "print('controlled-ok')"],
            cwd=ROOT,
            timeout_seconds=5,
            monitor_interval_seconds=1,
            termination_grace_seconds=1,
            dependency_names=(),
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["attempt_count"], 1)
        self.assertIn("controlled-ok", result["stdout"])
        environment = result["environment"]
        for field in contract.ENVIRONMENT_FIELDS:
            self.assertIn(field, environment)
        self.assertEqual(environment["dependency_policy"], "stdlib_only")

    def test_hard_timeout_fails_closed_without_retry(self):
        runner = load_r2_runner()
        result = runner.run_controlled_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=ROOT,
            timeout_seconds=0.05,
            monitor_interval_seconds=0.01,
            termination_grace_seconds=0.05,
            dependency_names=(),
        )
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["attempt_count"], 1)
        self.assertTrue(result["termination_requested"])
        self.assertTrue(result["process_tree_collected"])


class Stage10V2R2MetadataContractTest(unittest.TestCase):
    def _context(self):
        return {
            "config_sha256": "1" * 64,
            "result_schema_sha256": "2" * 64,
            "approved_freeze_receipt_sha256": "3" * 64,
            "generation_freeze_receipt_sha256": "3" * 64,
            "generation_source_manifest_sha256": "4" * 64,
            "generation_source_set_fingerprint_sha256": "5" * 64,
            "generation_source_entry_count": 11,
            "generation_test_evidence_sha256": "6" * 64,
            "execution_environment_sha256": "7" * 64,
            "stage9_input_receipt_sha256": "8" * 64,
            "stage9_config_sha256": "9" * 64,
            "stage9_verification_sha256": "a" * 64,
            "stage9_checkpoint_sha256": "b" * 64,
            "stage9_latency_summary_sha256": "c" * 64,
            "stage9_run_identity_sha256": "d" * 64,
            "timing_provenance_sha256": "e" * 64,
            "scenario_matrix_sha256": "f" * 64,
            "git_commit": "0" * 40,
        }

    def test_complete_expected_objects_are_stable(self):
        runner = load_r2_runner()
        context = self._context()
        results = [{"scenario_id": f"scenario-{index:02d}"} for index in range(60)]
        identity = runner.expected_run_identity(context)
        verification = runner.expected_verification(context, results)
        state = runner.expected_run_state()
        self.assertEqual(identity["run_identity_sha256"],
                         contract.self_hash(identity, "run_identity_sha256"))
        self.assertEqual(verification["result_count"], 60)
        self.assertEqual(state["status"], contract.VERIFIED_STATUS)

    def test_rehashed_metadata_tamper_still_fails_full_comparison(self):
        runner = load_r2_runner()
        context = self._context()
        results = [{"scenario_id": f"scenario-{index:02d}"} for index in range(60)]
        expected = (
            runner.expected_run_identity(context),
            runner.expected_verification(context, results),
            runner.expected_run_state(),
        )
        tampered = [dict(item) for item in expected]
        tampered[0]["contract_id"] = "forged"
        tampered[0]["run_identity_sha256"] = contract.self_hash(
            tampered[0], "run_identity_sha256")
        with self.assertRaises(contract.Stage10V2R2ContractError):
            runner.require_complete_metadata(tuple(tampered), expected)


class Stage10V2R2RunnerLifecycleTest(unittest.TestCase):
    def test_preflight_failure_creates_no_output(self):
        runner = load_r2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs/capd_proactive_stage10"
            with self.assertRaises(contract.Stage10V2R2ContractError):
                runner.build_run(
                    config_path=Path(temporary) / "missing.json",
                    stage9_run_root=Path(temporary) / "missing-stage9",
                    output_root=output,
                    run_id=contract.RUN_ID,
                    approved_freeze_receipt_sha256="0" * 64,
                    project_root=ROOT,
                )
            self.assertFalse(output.exists())

    def test_compact_temporary_run_has_exact_artifacts_and_recomputes(self):
        runner = load_r2_runner()
        from qmap import proactive_stage10_v2 as stage10_v2
        from tests.stage10_v2_r2_test_support import build_synthetic_r2
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            fixture = build_synthetic_r2(ROOT, project, stage10_v2)
            output = project / "outputs/capd_proactive_stage10"
            target = runner.build_prevalidated_test_run(
                config=fixture["config"], binding=fixture["binding"],
                stage9_run_root=fixture["stage9_root"], output_root=output,
                project_root=project,
                source_manifest=fixture["manifest"],
                repository_receipt=fixture["receipt_path"],
                approved_freeze_receipt_sha256=fixture["approved_sha"],
            )
            verified = runner.verify_r2_run(
                target, project_root=project, binding=fixture["binding"],
                repository_config=fixture["config"],
                repository_manifest=fixture["manifest"],
                repository_receipt=fixture["receipt_path"],
                approved_freeze_receipt_sha256=fixture["approved_sha"],
                allow_test_parameters=True,
            )
            self.assertEqual(verified["status"], contract.VERIFIED_STATUS)
            self.assertEqual(verified["result_count"], 60)
            self.assertEqual(verified["manifest_files"], 17)
            self.assertEqual(len(list(target.iterdir())), 19)

            state = json.loads((target / "run_state.json").read_text(encoding="utf-8"))
            state["contract_id"] = "forged"
            write_json(target / "run_state.json", state)
            runner.rebuild_manifest_and_checksums_for_test(target)
            with self.assertRaises(contract.Stage10V2R2ContractError):
                runner.verify_r2_run(
                    target, project_root=project, binding=fixture["binding"],
                    repository_config=fixture["config"],
                    repository_manifest=fixture["manifest"],
                    repository_receipt=fixture["receipt_path"],
                    approved_freeze_receipt_sha256=fixture["approved_sha"],
                    allow_test_parameters=True,
                )


class Stage10V2R2DispatchTest(unittest.TestCase):
    def test_r2_dispatch_requires_and_forwards_external_sha(self):
        from tests.test_capd_proactive_stage10_v2 import load_dispatch_runner
        dispatch = load_dispatch_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "config.json", {
                "contract_id": contract.CONTRACT_ID,
                "schema_version": contract.CONFIG_SCHEMA_VERSION,
                "run_id": contract.RUN_ID,
            })
            write_json(root / "run_identity.json", {
                "schema_version": contract.RUN_IDENTITY_SCHEMA_VERSION,
                "contract_id": contract.CONTRACT_ID,
                "run_id": contract.RUN_ID,
            })
            with self.assertRaises(contract.Stage10V2R2ContractError):
                dispatch.verify_run(str(root))
            approved = "a" * 64
            with mock.patch(
                    "scripts.run_capd_proactive_stage10_v2_r2.verify_r2_run",
                    return_value={"status": contract.VERIFIED_STATUS}) as verify:
                observed = dispatch.verify_run(
                    str(root), approved_freeze_receipt_sha256=approved)
            self.assertEqual(observed["status"], contract.VERIFIED_STATUS)
            self.assertEqual(
                verify.call_args.kwargs["approved_freeze_receipt_sha256"], approved)

    def test_mixed_r1_r2_identity_is_rejected(self):
        from tests.test_capd_proactive_stage10_v2 import load_dispatch_runner
        dispatch = load_dispatch_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "config.json", {
                "contract_id": contract.CONTRACT_ID,
                "schema_version": "capd_proactive_stage10_v2_0",
                "run_id": contract.RUN_ID,
            })
            write_json(root / "run_identity.json", {
                "schema_version": contract.RUN_IDENTITY_SCHEMA_VERSION,
                "run_id": contract.RUN_ID,
            })
            with self.assertRaises(Exception):
                dispatch.verify_run(
                    str(root), approved_freeze_receipt_sha256="a" * 64)


class Stage10V2R2ReleaseReadinessTest(unittest.TestCase):
    def test_exact_stage11_triples_and_twelve_file_readiness(self):
        runner = load_r2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "freeze.json"
            receipt.write_text("{}\n", encoding="utf-8")
            approved = contract.sha256_file(receipt)
            release = root / "readiness"
            runner.build_prevalidated_release_readiness(
                release_root=release,
                approved_freeze_receipt_sha256=approved,
                repository_receipt=receipt,
                stage11_result=contract.STAGE11_EXPECTED,
            )
            result = runner.verify_release_readiness(
                release,
                approved_freeze_receipt_sha256=approved,
                repository_receipt=receipt,
                allow_test_evidence=True,
            )
            self.assertEqual(result["release_status"],
                             "stage10_release_readiness_verified")
            self.assertEqual(len(list(release.iterdir())), 12)

    def test_stage11_tamper_fails_before_release_creation(self):
        runner = load_r2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "freeze.json"
            receipt.write_text("{}\n", encoding="utf-8")
            approved = contract.sha256_file(receipt)
            changed = json.loads(json.dumps(contract.STAGE11_EXPECTED))
            changed["stage10_r2"]["reason_code"] = "arbitrary_non_authorized"
            release = root / "readiness"
            with self.assertRaises(contract.Stage10V2R2ContractError):
                runner.build_prevalidated_release_readiness(
                    release_root=release,
                    approved_freeze_receipt_sha256=approved,
                    repository_receipt=receipt,
                    stage11_result=changed,
                )
            self.assertFalse(release.exists())


class Stage10V2R2FinalStatusTest(unittest.TestCase):
    def test_final_status_requires_verified_readiness_and_has_eight_files(self):
        runner = load_r2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "freeze.json"
            receipt.write_text("{}\n", encoding="utf-8")
            approved = contract.sha256_file(receipt)
            final = root / "final-status"
            with self.assertRaises(contract.Stage10V2R2ContractError):
                runner.build_prevalidated_final_status(
                    final_root=final, readiness_root=root / "missing-readiness",
                    approved_freeze_receipt_sha256=approved,
                    repository_receipt=receipt,
                )
            self.assertFalse(final.exists())
            readiness = root / "readiness"
            runner.build_prevalidated_release_readiness(
                release_root=readiness,
                approved_freeze_receipt_sha256=approved,
                repository_receipt=receipt,
                stage11_result=contract.STAGE11_EXPECTED,
            )
            runner.build_prevalidated_final_status(
                final_root=final, readiness_root=readiness,
                approved_freeze_receipt_sha256=approved,
                repository_receipt=receipt,
            )
            result = runner.verify_final_status(
                final,
                approved_freeze_receipt_sha256=approved,
                repository_receipt=receipt,
                allow_test_evidence=True,
            )
            self.assertEqual(result["status"],
                             "stage10_final_status_evidence_verified")
            self.assertEqual(len(list(final.iterdir())), 8)


if __name__ == "__main__":
    unittest.main()
