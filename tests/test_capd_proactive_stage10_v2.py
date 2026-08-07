"""Tests for the CAPD Stage10 v2 deterministic async-simulation contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from tests.stage10_v2_test_support import (
    build_synthetic_stage9,
    rebind_verification,
    synthetic_test_log,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/finals/capd_proactive_stage10_v2.json"
SCHEMA_PATH = ROOT / "configs/finals/capd_proactive_stage10_result_schema_v2.json"
REAL_STAGE9 = ROOT / "outputs/capd_proactive_stage9/stage9-overhead-v2-r3"


def module():
    from qmap import proactive_stage10_v2
    return proactive_stage10_v2


class Stage10V2ConfigContractTest(unittest.TestCase):
    def test_repository_config_and_schema_bind_approved_contract(self):
        v2 = module()
        config = v2.load_repository_config(ROOT)
        self.assertEqual(config["contract_id"], "CAPD-PROACTIVE-STAGE10-2.0")
        self.assertEqual(config["evidence_mode"], "deterministic_async_simulation")
        self.assertEqual(config["success_status"], "stage10_async_simulation_verified")
        self.assertEqual(config["run_id"], "stage10-async-simulator-v2-r1")
        self.assertEqual(config["scenario_count"], 60)
        self.assertEqual(
            config["approved_design"]["sha256"],
            "2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd",
        )
        self.assertEqual(
            config["byte_recovery_audit"]["sha256"],
            "94a68bfccfa6fec3a947b6ed35f83cca04a09bfe708b9390385d7476e0c5bc64",
        )

    def test_fixture_or_weakened_config_is_rejected(self):
        v2 = module()
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for path, value in (
            (("contract_id",), "CAPD-PROACTIVE-STAGE10-1.0"),
            (("scenario_count",), 59),
            (("stage9_binding", "run_id"), "stage9-overhead-v2-r2"),
            (("stage9_binding", "config_sha256"),
             "4fbbe7fe17f3ef10a9f04c83960901837f0dcda513d843c27b9d8e888ce2c1a7"),
            (("migration_scenarios", 1, "role"), "measured"),
            (("arrival_profiles", 0, "load_ratio"), "9.9"),
            (("arrival_profiles", 4, "bursts", 0, "multiplier"), "99.0"),
            (("timing_source", "original_value"), "1"),
            (("output_root",), "outputs/attacker-controlled"),
        ):
            changed = copy.deepcopy(config)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises(v2.Stage10V2ContractError):
                v2.validate_config(changed, ROOT)


class Stage10V2Stage9GateTest(unittest.TestCase):
    def test_real_stage9_r3_passes_complete_read_only_gate(self):
        v2 = module()
        config = v2.load_repository_config(ROOT)
        binding = v2.production_stage9_binding(config, ROOT)
        audit = v2.audit_stage9_run(REAL_STAGE9, binding)
        self.assertEqual(audit.receipt["status"], "stage10_stage9_input_verified")
        self.assertEqual(audit.receipt["artifact_sha256_verified_count"], 19)

    def test_no_root_manifest_is_required_but_hash_tamper_fails(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            self.assertFalse((run_root / "manifest.json").exists())
            self.assertFalse((run_root / "SHA256SUMS").exists())
            v2.audit_stage9_run(run_root, binding)
            (run_root / "capacity_overhead.csv").write_bytes(b"tampered\n")
            with self.assertRaises(v2.Stage10V2ContractError):
                v2.audit_stage9_run(run_root, binding)

    def test_perf_newline_change_fails_byte_exact_gate(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            perf = run_root / "perf/perf-stat.raw"
            perf.write_bytes(perf.read_bytes().replace(b"\n", b"\r\n"))
            with self.assertRaises(v2.Stage10V2ContractError):
                v2.audit_stage9_run(run_root, binding)

    def test_historical_run_and_self_declared_receipt_are_rejected(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            historical = run_root.with_name("stage9-overhead-v2-r2")
            run_root.rename(historical)
            with self.assertRaises(v2.Stage10V2ContractError):
                v2.audit_stage9_run(historical, binding)
            with self.assertRaises(TypeError):
                v2.audit_stage9_run(historical, {"formal_authorized": True})


class Stage10V2MeasurementCheckpointTest(unittest.TestCase):
    def test_checkpoint_identity_sets_and_raw_binding_are_verified(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            audit = v2.audit_stage9_run(run_root, binding)
            self.assertEqual(audit.receipt["quality_row_count"], 3)
            self.assertEqual(audit.receipt["instrumentation_audit_count"], 1)

    def test_rehashed_checkpoint_tamper_still_fails_pinned_sha(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            checkpoint_path = run_root / "measurement_checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["quality_row_count"] = 2
            write_json(checkpoint_path, checkpoint)
            verification_path = run_root / "verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["artifact_sha256"]["measurement_checkpoint.json"] = \
                v2.sha256_file(checkpoint_path)
            write_json(verification_path, verification)
            binding = rebind_verification(v2, binding, run_root)
            with self.assertRaises(v2.Stage10V2ContractError):
                v2.audit_stage9_run(run_root, binding)


class Stage10V2TimingProvenanceTest(unittest.TestCase):
    def test_decimal_round_half_up_derivation_is_exact(self):
        v2 = module()
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), v2)
            provenance = v2.derive_timing_provenance(
                v2.audit_stage9_run(run_root, binding))
            self.assertEqual(provenance["inference_ns"]["mean"], 2252304)
            self.assertEqual(provenance["inference_ns"]["p50"], 2192418)
            self.assertEqual(provenance["inference_ns"]["p95"], 2625519)
            self.assertEqual(provenance["inference_ns"]["p99"], 2938056)
            self.assertEqual(provenance["migration_ns"], {
                "migration-ratio-0p01": 22523,
                "migration-ratio-0p10": 225230,
                "migration-ratio-1p00": 2252304,
            })
            self.assertEqual(
                provenance["original_decimal"]["mean"], "2252304.4582606885")
            self.assertNotEqual(provenance["inference_ns"]["mean"], 2000)


class Stage10V2ArrivalMatrixTest(unittest.TestCase):
    def setUp(self):
        self.v2 = module()
        self.config = self.v2.load_repository_config(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), self.v2)
            self.timing = self.v2.derive_timing_provenance(
                self.v2.audit_stage9_run(run_root, binding))

    def compact_config(self, horizon_ns):
        config = copy.deepcopy(self.config)
        config["simulator_parameters"]["simulation_horizon_ns"] = horizon_ns
        burst = config["arrival_profiles"][-1]["bursts"]
        burst[0].update(start_ns=horizon_ns // 5, duration_ns=horizon_ns // 10)
        burst[1].update(start_ns=3 * horizon_ns // 5,
                        duration_ns=horizon_ns // 10)
        return config

    def test_sixty_rows_and_fixed_arrival_identity(self):
        config = self.compact_config(10_000_000)
        streams = self.v2.build_arrival_streams(config, self.timing)
        matrix = self.v2.expand_scenario_matrix(config, self.timing, streams)
        self.assertEqual(len(matrix), 60)
        self.assertEqual(len({row["scenario_id"] for row in matrix}), 60)
        for arrival_id in {row["arrival_profile_id"] for row in matrix}:
            fixed = [row for row in matrix
                     if row["comparison_channel"] == "fixed_arrival"
                     and row["arrival_profile_id"] == arrival_id]
            self.assertEqual(len(fixed), 6)
            self.assertEqual(len({row["arrival_binding"]["arrival_stream_sha256"]
                                  for row in fixed}), 1)
            self.assertEqual(len({row["arrival_binding"]["absolute_arrival_rate"]
                                  ["kind"] for row in fixed}), 1)
            arrays = []
            for row in fixed:
                key = (row["comparison_channel"], row["timing_profile_id"],
                       row["arrival_profile_id"])
                arrays.append(self.v2.canonical_arrival_payload(streams[key].arrivals))
            self.assertTrue(all(value == arrays[0] for value in arrays[1:]))

    def test_channel_rate_basis_and_comparison_scope_are_paired(self):
        config = self.compact_config(1_000_000)
        streams = self.v2.build_arrival_streams(config, self.timing)
        matrix = self.v2.expand_scenario_matrix(config, self.timing, streams)
        for row in matrix:
            binding = row["arrival_binding"]
            if row["comparison_channel"] == "fixed_arrival":
                self.assertEqual(binding["arrival_rate_basis"],
                                 "reference_profile_fixed")
                self.assertTrue(binding["cross_profile_comparison_allowed"])
            else:
                self.assertEqual(binding["arrival_rate_basis"],
                                 "per_profile_mu_demote")
                self.assertFalse(binding["cross_profile_comparison_allowed"])


class Stage10V2SimulationContractTest(unittest.TestCase):
    def setUp(self):
        self.v2 = module()
        self.config = self.v2.load_repository_config(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            run_root, binding = build_synthetic_stage9(Path(temporary), self.v2)
            self.timing = self.v2.derive_timing_provenance(
                self.v2.audit_stage9_run(run_root, binding))

    def compact_inputs(self):
        config = copy.deepcopy(self.config)
        horizon = 1_000_000
        config["simulator_parameters"]["simulation_horizon_ns"] = horizon
        bursts = config["arrival_profiles"][-1]["bursts"]
        bursts[0].update(start_ns=200_000, duration_ns=100_000)
        bursts[1].update(start_ns=600_000, duration_ns=100_000)
        streams = self.v2.build_arrival_streams(config, self.timing)
        matrix = self.v2.expand_scenario_matrix(config, self.timing, streams)
        return config, streams, matrix

    def test_v2_wrapper_is_deterministic_and_never_claims_real_system(self):
        config, streams, matrix = self.compact_inputs()
        scenario = matrix[0]
        key = (scenario["comparison_channel"], scenario["timing_profile_id"],
               scenario["arrival_profile_id"])
        first = self.v2.simulate_scenario(config, scenario, streams[key])
        second = self.v2.simulate_scenario(config, scenario, streams[key])
        self.assertEqual(first, second)
        self.assertEqual(first["evidence_mode"], "deterministic_async_simulation")
        interpretation = first["interpretation"]
        for field in (
            "real_nvm_measurement_verified", "kernel_behavior_verified",
            "real_concurrency_verified",
            "real_foreground_end_to_end_latency_verified",
            "real_system_async_performance_verified",
        ):
            self.assertFalse(interpretation[field])
        self.v2.validate_result_line(first, self.v2.load_result_schema(ROOT))

    def test_capacity_normalized_cannot_claim_timing_causality(self):
        config, streams, matrix = self.compact_inputs()
        scenario = next(row for row in matrix
                        if row["comparison_channel"] == "capacity_normalized")
        key = (scenario["comparison_channel"], scenario["timing_profile_id"],
               scenario["arrival_profile_id"])
        line = self.v2.simulate_scenario(config, scenario, streams[key])
        self.assertFalse(line["interpretation"]
                         ["timing_sensitivity_interpretation_allowed"])
        self.assertFalse(line["interpretation"]
                         ["capacity_normalized_timing_causal_interpretation_allowed"])


def load_v2_runner():
    path = ROOT / "scripts/run_capd_proactive_stage10_v2.py"
    spec = importlib.util.spec_from_file_location("capd_stage10_v2_runner_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load v2 runner")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_dispatch_runner():
    path = ROOT / "scripts/run_capd_proactive_stage10.py"
    spec = importlib.util.spec_from_file_location("capd_stage10_dispatch_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load dispatcher")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class Stage10V2RunnerLifecycleTest(unittest.TestCase):
    def test_preflight_failure_creates_no_output(self):
        runner = load_v2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "outputs/capd_proactive_stage10"
            with self.assertRaises(Exception):
                runner.build_run(
                    config_path=root / "missing.json",
                    stage9_run_root=root / "missing-stage9",
                    output_root=output,
                    run_id="stage10-async-simulator-v2-r1",
                    test_log_input=root / "missing.log",
                    test_log_sha256="0" * 64,
                    project_root=root,
                )
            self.assertFalse(output.exists())

    def test_temporary_compact_run_writes_and_verifies_exact_artifacts(self):
        v2 = module()
        runner = load_v2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            run_root, binding = build_synthetic_stage9(temp_root, v2)
            config = copy.deepcopy(v2.load_repository_config(ROOT))
            horizon = 1_000_000
            config["simulator_parameters"]["simulation_horizon_ns"] = horizon
            bursts = config["arrival_profiles"][-1]["bursts"]
            bursts[0].update(start_ns=200_000, duration_ns=100_000)
            bursts[1].update(start_ns=600_000, duration_ns=100_000)
            log = temp_root / "stage10-v2-tests.log"
            command = config["test_evidence"]["expected_command"]
            log_sha = synthetic_test_log(log, command)
            target = runner.build_prevalidated_test_run(
                config=config,
                binding=binding,
                stage9_run_root=run_root,
                output_root=temp_root / "stage10-output",
                test_log_input=log,
                test_log_sha256=log_sha,
                project_root=ROOT,
            )
            verified = runner.verify_v2_run(
                target, project_root=ROOT, binding=binding,
                allow_test_parameters=True)
            self.assertEqual(verified["result_count"], 60)
            self.assertEqual(verified["status"],
                             "stage10_async_simulation_verified")
            self.assertEqual(len(list(target.iterdir())), 16)
            with self.assertRaises(Exception):
                runner.build_prevalidated_test_run(
                    config=config, binding=binding, stage9_run_root=run_root,
                    output_root=temp_root / "stage10-output",
                    test_log_input=log, test_log_sha256=log_sha,
                    project_root=ROOT)
            extra = target / "extra.txt"
            extra.write_text("tamper", encoding="utf-8")
            with self.assertRaises(Exception):
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)
            extra.unlink()
            results = target / "simulation_results.jsonl"
            rows = results.read_text(encoding="utf-8").splitlines()
            first = json.loads(rows[0])
            first["observed"]["emergency_fallback_count"] += 1
            rows[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
            results.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="")
            write_json(target / "manifest.json", runner.manifest_value(target))
            runner.write_checksums(target)
            with self.assertRaises(Exception):
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)

    def test_empty_or_forged_test_log_is_rejected(self):
        v2 = module()
        runner = load_v2_runner()
        config = v2.load_repository_config(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "log.txt"
            path.write_text("synthetic integration test log\n", encoding="utf-8")
            with self.assertRaises(v2.Stage10V2ContractError):
                runner.validate_test_log(
                    path, v2.sha256_file(path), config["test_evidence"])

    def test_rehashed_metadata_tampering_fails_full_object_verification(self):
        v2 = module()
        runner = load_v2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            stage9_root, binding = build_synthetic_stage9(temp_root, v2)
            config = copy.deepcopy(v2.load_repository_config(ROOT))
            config["simulator_parameters"]["simulation_horizon_ns"] = 1_000_000
            bursts = config["arrival_profiles"][-1]["bursts"]
            bursts[0].update(start_ns=200_000, duration_ns=100_000)
            bursts[1].update(start_ns=600_000, duration_ns=100_000)
            log = temp_root / "stage10-v2-tests.log"
            log_sha = synthetic_test_log(
                log, config["test_evidence"]["expected_command"])
            target = runner.build_prevalidated_test_run(
                config=config, binding=binding, stage9_run_root=stage9_root,
                output_root=temp_root / "stage10-output",
                test_log_input=log, test_log_sha256=log_sha,
                project_root=ROOT)

            identity_path = target / "run_identity.json"
            verification_path = target / "verification.json"
            state_path = target / "run_state.json"
            originals = {
                identity_path: json.loads(identity_path.read_text(encoding="utf-8")),
                verification_path: json.loads(
                    verification_path.read_text(encoding="utf-8")),
                state_path: json.loads(state_path.read_text(encoding="utf-8")),
            }

            def rehash():
                write_json(target / "manifest.json", runner.manifest_value(target))
                runner.write_checksums(target)

            def restore():
                for path, value in originals.items():
                    write_json(path, value)
                rehash()
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)

            identity = copy.deepcopy(originals[identity_path])
            identity.update({
                "evidence_mode": "fixture",
                "config_sha256": "1" * 64,
                "result_schema_sha256": "2" * 64,
                "approved_design_sha256": "3" * 64,
                "byte_recovery_audit_sha256": "4" * 64,
                "stage9_config_sha256": "5" * 64,
                "stage9_verification_sha256": "6" * 64,
                "stage9_checkpoint_sha256": "7" * 64,
                "stage9_latency_summary_sha256": "8" * 64,
                "stage9_run_identity_sha256": "9" * 64,
                "timing_provenance_sha256": "a" * 64,
                "test_evidence_sha256": "b" * 64,
                "conversion_rule": "attacker-rule",
            })
            identity.pop("run_identity_sha256")
            identity["run_identity_sha256"] = v2.fingerprint_value(identity)
            write_json(identity_path, identity)
            rehash()
            with self.assertRaises(v2.Stage10V2ContractError):
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)
            restore()

            verification = copy.deepcopy(originals[verification_path])
            verification.update({
                "contract_id": "attacker-contract",
                "evidence_mode": "fixture",
                "simulation_executed": False,
                "artifacts_independently_recomputed": False,
            })
            write_json(verification_path, verification)
            rehash()
            with self.assertRaises(v2.Stage10V2ContractError):
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)
            restore()

            state = copy.deepcopy(originals[state_path])
            state.update({
                "schema_version": "attacker-schema",
                "contract_id": "attacker-contract",
                "run_id": "attacker-run",
                "evidence_mode": "fixture",
            })
            write_json(state_path, state)
            rehash()
            with self.assertRaises(v2.Stage10V2ContractError):
                runner.verify_v2_run(
                    target, project_root=ROOT, binding=binding,
                    allow_test_parameters=True)

    def test_synthetic_entrypoint_cannot_target_production_output(self):
        v2 = module()
        runner = load_v2_runner()
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            run_root, binding = build_synthetic_stage9(temp_root, v2)
            config = v2.load_repository_config(ROOT)
            log = temp_root / "tests.log"
            sha = synthetic_test_log(
                log, config["test_evidence"]["expected_command"])
            with self.assertRaises(v2.Stage10V2ContractError):
                runner.build_prevalidated_test_run(
                    config=config, binding=binding, stage9_run_root=run_root,
                    output_root=ROOT / "outputs/capd_proactive_stage10",
                    test_log_input=log, test_log_sha256=sha,
                    project_root=ROOT)


class Stage10V2VerifierDispatchTest(unittest.TestCase):
    def test_v1_dispatch_still_verifies_historical_fixture(self):
        runner = load_dispatch_runner()
        result = runner.verify_run(
            str(ROOT / "outputs/capd_proactive_stage10/stage10-async-simulator-r1"))
        self.assertEqual(result["result_count"], 5)

    def test_v1_and_v2_verifiers_are_bidirectionally_incompatible(self):
        v2_runner = load_v2_runner()
        dispatch = load_dispatch_runner()
        self.assertTrue(callable(dispatch.verify_v1_fixture_run))
        v1 = ROOT / "outputs/capd_proactive_stage10/stage10-async-simulator-r1"
        with self.assertRaises(Exception):
            v2_runner.verify_v2_run(v1, project_root=ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            write_json(run / "config.json", {
                "contract_id": "CAPD-PROACTIVE-STAGE10-2.0",
                "schema_version": "capd_proactive_stage10_v2_0",
            })
            with self.assertRaises(Exception) as caught:
                dispatch.verify_v1_fixture_run(str(run))
            self.assertNotIsInstance(caught.exception, AttributeError)

    def test_unknown_contract_is_rejected(self):
        dispatch = load_dispatch_runner()
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            write_json(run / "config.json", {"contract_id": "unknown"})
            with self.assertRaises(Exception):
                dispatch.verify_run(str(run))


if __name__ == "__main__":
    unittest.main()
