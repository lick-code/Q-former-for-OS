import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qmap import proactive_stage10 as stage10
from scripts import run_capd_proactive_stage10 as stage10_runner


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage10.json")
SCHEMA_PATH = os.path.join(
    ROOT, "configs", "finals", "capd_proactive_stage10_result_schema.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class Stage10ConfigContractTest(unittest.TestCase):

    def test_repository_config_and_schema_are_valid(self):
        config = load_json(CONFIG_PATH)
        schema = load_json(SCHEMA_PATH)
        stage10.validate_config(config)
        self.assertEqual("CAPD-PROACTIVE-STAGE10-1.0",
                         config["contract_id"])
        self.assertEqual(
            stage10.sha256_file(SCHEMA_PATH),
            config["result_schema_sha256"])
        self.assertRegex(config["result_schema_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual("fixture", config["mode"])
        self.assertEqual("lru_tail", config["candidate_source"])
        self.assertEqual(["-m", "unittest"],
                         config["test_evidence"]["required_command_tokens"])
        self.assertEqual("tests.test_capd_proactive_stage10",
                         config["test_evidence"]["required_module"])
        self.assertGreaterEqual(config["test_evidence"]["minimum_test_count"],
                                10)
        self.assertEqual(["0.5", "0.8", "1.0", "1.2"],
                         [row["load_ratio"]
                          for row in config["uniform_scenarios"]])
        self.assertEqual("capd_proactive_stage10_result_v1_0",
                         schema["schema_version"])
        self.assertEqual(["null", "integer"],
                         schema["properties"]["observed"]["properties"]
                         ["foreground_blocking_time_mean"]["type"])

    def test_invalid_timing_capacity_and_arrival_kind_fail_closed(self):
        base = load_json(CONFIG_PATH)
        for path, value in (
            (("fixture_parameters", "T_inference_ns"), 0),
            (("fixture_parameters", "b_t_reference"), 3),
            (("fixture_parameters", "initial_free_frames"), 65),
            (("fixture_parameters", "F_low"), 24),
            (("candidate_source",), "all_resident"),
            (("arrival_models",), ["trace"]),
        ):
            bad = copy.deepcopy(base)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                with self.assertRaises(stage10.Stage10ContractError):
                    stage10.validate_config(bad)
        weakened = copy.deepcopy(base)
        weakened["formal_gate"]["stage9_required_files"] = ["run_state.json"]
        with self.assertRaises(stage10.Stage10ContractError):
            stage10.validate_config(weakened)


class Stage10EventHeapTest(unittest.TestCase):

    def test_same_time_events_follow_frozen_priority_then_event_id(self):
        queue = stage10.EventQueue()
        queue.schedule(9, "page_enter_dram", {"name": "arrival-1"})
        queue.schedule(9, "capd_round_start", {"name": "round"})
        queue.schedule(9, "demotion_finish", {"name": "demotion"})
        queue.schedule(9, "emergency_fallback", {"name": "fallback"})
        queue.schedule(9, "capd_inference_finish", {"name": "inference"})
        queue.schedule(9, "page_enter_dram", {"name": "arrival-2"})
        self.assertEqual(
            ["demotion_finish", "capd_inference_finish", "capd_round_start",
             "emergency_fallback", "page_enter_dram", "page_enter_dram"],
            [queue.pop().kind for _ in range(6)])

    def test_event_ids_are_strictly_monotonic(self):
        queue = stage10.EventQueue()
        first = queue.schedule(3, "page_enter_dram", {})
        second = queue.schedule(1, "page_enter_dram", {})
        self.assertEqual((1, 2), (first.event_id, second.event_id))


class Stage10StateContractTest(unittest.TestCase):

    def _state(self, **overrides):
        config = load_json(CONFIG_PATH)["fixture_parameters"]
        config.update(overrides)
        return stage10.SimulatorState(stage10.SimulatorConfig.from_mapping(config))

    def test_initial_resident_ids_and_lru_order_are_deterministic(self):
        state = self._state(dram_capacity_frames=8, initial_free_frames=3,
                            F_low=2, F_target=4, K=4)
        self.assertEqual(5, state.initial_resident_count)
        self.assertEqual([0, 1, 2, 3, 4], state.lru_mru_to_lru)
        self.assertEqual([4, 3, 2], state.select_candidates(3))

    def test_new_and_unblocked_pages_enter_mru_head(self):
        state = self._state(dram_capacity_frames=4, initial_free_frames=1,
                            F_low=1, F_target=2, K=2)
        page_id = state.admit_new_page(state.next_page_id)
        self.assertEqual(page_id, state.lru_mru_to_lru[0])
        state.begin_blocked_request(11, state.next_page_id)
        state.release_resident_page(2)
        state.admit_oldest_blocked(12)
        self.assertEqual(state.last_admitted_page_id, state.lru_mru_to_lru[0])

    def test_reserved_components_are_disjoint_and_duplicate_is_rejected(self):
        state = self._state()
        state.reserve_inference([0])
        with self.assertRaises(stage10.Stage10ContractError):
            state.reserve_normal_migration([0])
        with self.assertRaises(stage10.Stage10ContractError):
            state.reserve_emergency_migration([0])
        self.assertEqual({0}, state.reserved_page_ids)

    def test_capacity_and_frame_invariants_hold_after_admission_and_release(self):
        state = self._state(dram_capacity_frames=4, initial_free_frames=1,
                            F_low=1, F_target=2, K=2)
        state.admit_new_page(state.next_page_id)
        self.assertEqual(0, state.free_frames)
        state.begin_blocked_request(2, state.next_page_id)
        state.release_resident_page(2)
        state.admit_oldest_blocked(3)
        state.assert_invariants()
        self.assertEqual(4, state.free_frames + len(state.resident_page_ids))

    def test_batch_size_is_bounded_by_target_gap_and_candidates(self):
        state = self._state(b_max=4, F_low=2, F_target=5)
        self.assertEqual(4, state.batch_size(free_frames=1, candidate_count=9))
        self.assertEqual(2, state.batch_size(free_frames=3, candidate_count=9))
        self.assertEqual(1, state.batch_size(free_frames=1, candidate_count=1))


class Stage10ArrivalTest(unittest.TestCase):

    def test_uniform_generator_is_reproducible_and_integer_ns(self):
        config = load_json(CONFIG_PATH)["fixture_parameters"]
        params = stage10.SimulatorConfig.from_mapping(config)
        first = stage10.generate_uniform_arrivals(
            params, load_ratio="0.8", horizon_ns=100000)
        second = stage10.generate_uniform_arrivals(
            params, load_ratio="0.8", horizon_ns=100000)
        self.assertEqual(first, second)
        self.assertTrue(all(isinstance(item.timestamp_ns, int) for item in first))
        self.assertTrue(all(0 <= item.timestamp_ns <= 100000 for item in first))

    def test_uniform_period_uses_reference_batch_and_model_capacity(self):
        config = load_json(CONFIG_PATH)["fixture_parameters"]
        params = stage10.SimulatorConfig.from_mapping(config)
        arrivals = stage10.generate_uniform_arrivals(
            params, load_ratio="1.0", horizon_ns=100000)
        expected_period = (
            params.T_inference_ns +
            params.b_t_reference * params.T_migration_ns
        ) // params.b_t_reference
        self.assertEqual(expected_period,
                         arrivals[1].timestamp_ns - arrivals[0].timestamp_ns)

    def test_burst_model_keeps_base_flow_before_inside_and_after_bursts(self):
        config = load_json(CONFIG_PATH)
        params = stage10.SimulatorConfig.from_mapping(config["fixture_parameters"])
        bursts = config["burst_scenarios"][0]["bursts"]
        first = stage10.generate_burst_arrivals(
            params, bursts, base_load_ratio="0.5",
            horizon_ns=params.simulation_horizon_ns)
        second = stage10.generate_burst_arrivals(
            params, bursts, base_load_ratio="0.5",
            horizon_ns=params.simulation_horizon_ns)
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first, key=lambda item: item.timestamp_ns))
        self.assertTrue(any(item.timestamp_ns < bursts[0]["start_ns"] for item in first))
        self.assertTrue(any(
            bursts[0]["start_ns"] <= item.timestamp_ns <
            bursts[0]["start_ns"] + bursts[0]["duration_ns"] for item in first))
        self.assertTrue(any(
            bursts[1]["start_ns"] <= item.timestamp_ns <
            bursts[1]["start_ns"] + bursts[1]["duration_ns"] for item in first))
        self.assertTrue(any(item.timestamp_ns >=
                            bursts[-1]["start_ns"] + bursts[-1]["duration_ns"]
                            for item in first))
        self.assertEqual(
            list(range(params.dram_capacity_frames - params.initial_free_frames,
                       params.dram_capacity_frames - params.initial_free_frames +
                       len(first))),
            [item.page_id for item in first])

    def test_trace_replay_is_rejected_until_a_future_timestamp_contract_exists(self):
        params = stage10.SimulatorConfig.from_mapping(
            load_json(CONFIG_PATH)["fixture_parameters"])
        with self.assertRaises(stage10.Stage10ContractError):
            stage10.generate_arrivals(params, {"kind": "trace", "path": "trace.json"})

    def test_overlapping_bursts_are_rejected(self):
        params = stage10.SimulatorConfig.from_mapping(
            load_json(CONFIG_PATH)["fixture_parameters"])
        with self.assertRaises(stage10.Stage10ContractError):
            stage10.generate_burst_arrivals(
                params,
                [{"start_ns": 10, "duration_ns": 20, "multiplier": "2.0"},
                 {"start_ns": 20, "duration_ns": 20, "multiplier": "1.5"}],
                base_load_ratio="0.5", horizon_ns=100)


class Stage10SimulationTest(unittest.TestCase):

    def _params(self, **overrides):
        value = load_json(CONFIG_PATH)["fixture_parameters"]
        value.update(overrides)
        return stage10.SimulatorConfig.from_mapping(value)

    def test_identical_seed_and_arrivals_produce_identical_events_and_metrics(self):
        params = self._params(simulation_horizon_ns=50000)
        arrivals = stage10.generate_uniform_arrivals(params, "0.8", 50000)
        first = stage10.run_simulation(params, arrivals)
        second = stage10.run_simulation(params, arrivals)
        self.assertEqual(first.events, second.events)
        self.assertEqual(first.metrics, second.metrics)

    def test_arrival_consumes_frame_and_demotion_releases_it(self):
        params = self._params(dram_capacity_frames=3, initial_free_frames=1,
                              F_low=1, F_target=2, simulation_horizon_ns=10000)
        result = stage10.run_simulation(
            params, [stage10.Arrival(0, 2), stage10.Arrival(6000, 3)])
        self.assertGreaterEqual(result.metrics["page_enter_dram_count"], 1)
        self.assertGreaterEqual(result.metrics["demotion_finish_count"], 1)
        self.assertGreaterEqual(result.metrics["minimum_free_frames"], 0)

    def test_full_arrival_is_blocked_then_admitted_after_demotion(self):
        params = self._params(dram_capacity_frames=2, initial_free_frames=0,
                              F_low=1, F_target=2, simulation_horizon_ns=10000)
        result = stage10.run_simulation(params, [stage10.Arrival(0, 2)])
        self.assertEqual(1, result.metrics["blocking_sample_count"])
        self.assertGreater(result.metrics["foreground_blocking_time_total"], 0)
        self.assertEqual(0, result.metrics["unfinished_blocked_request_count"])

    def test_empty_blocking_samples_are_null_and_exhaustion_is_time_integral(self):
        params = self._params(initial_free_frames=0, simulation_horizon_ns=10000)
        result = stage10.run_simulation(params, [])
        self.assertIsNone(result.metrics["foreground_blocking_time_mean"])
        self.assertIsNone(result.metrics["foreground_blocking_time_p95"])
        self.assertEqual(0, result.metrics["blocking_sample_count"])
        self.assertEqual(10000, result.metrics["free_frame_exhaustion_duration"])
        self.assertEqual(0, result.metrics["emergency_fallback_count"])

    def test_arrivals_outside_horizon_are_rejected(self):
        params = self._params(simulation_horizon_ns=1000)
        with self.assertRaises(stage10.Stage10ContractError):
            stage10.run_simulation(params, [stage10.Arrival(1001, 48)])

    def test_runtime_batch_values_are_bounded_and_high_load_queue_is_explainable(self):
        params = self._params(simulation_horizon_ns=200000)
        low = stage10.run_simulation(
            params, stage10.generate_uniform_arrivals(params, "0.5", 200000))
        high = stage10.run_simulation(
            params, stage10.generate_uniform_arrivals(params, "1.2", 200000))
        self.assertTrue(all(0 <= value <= params.b_max
                            for value in high.derived["actual_b_t_values"]))
        self.assertGreater(high.metrics["background_queue_length_max"], 0)
        self.assertGreaterEqual(
            high.metrics["background_queue_length_max"],
            low.metrics["background_queue_length_max"])


class Stage10FormalGateTest(unittest.TestCase):

    def _gate_config(self):
        return load_json(CONFIG_PATH)["formal_gate"]

    def _write_verified_run(self, run_root):
        gate = self._gate_config()
        stage9_config_path = os.path.join(ROOT, gate["stage9_config_path"])
        stage9_config = load_json(stage9_config_path)
        run_id = os.path.basename(run_root)
        for relative in gate["stage9_required_files"]:
            path = os.path.join(run_root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}" + chr(10))
        compatibility = {
            "stage9_entry_gate": "satisfied",
            "formal_job_count": 80,
            "standard_job_count": 48,
            "pressure_job_count": 32,
            "capd_job_count": 30,
            "track_workload_cell_count": 10,
            "fairness": "passed",
            "job_results_verified": True,
            "statistics_verified": True,
            "test_used_for_parameter_selection": False,
            "stage4_sha_chain_verified": True,
            "stage8_run_state_verified": True,
            "stage8_artifacts_read_only": True,
        }
        with open(os.path.join(run_root, "stage8_compatibility_receipt.json"),
                  "w", encoding="utf-8") as handle:
            json.dump(compatibility, handle, sort_keys=True)
        state = {
            "schema_version": "capd_proactive_stage9_run_state_v2_0",
            "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
            "status": "stage9_overhead_verified",
            "stage10_entry_gate": "satisfied",
            "completed": ["perf_cycles", "independent_verification"],
            "failure": None,
        }
        with open(os.path.join(run_root, "run_state.json"),
                  "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
        artifact_sha256 = {
            relative: stage10.sha256_file(os.path.join(run_root, relative))
            for relative in gate["stage9_required_files"]
            if relative not in ("verification.json", "run_state.json")
        }
        verification = dict(gate["stage9_verification_required"])
        verification.update({
            "contract_id": "CAPD-PROACTIVE-STAGE9-2.0",
            "stage8_verification_sha256": "b531f7324af9a6edf7dc31adc1426782c2389be35fd4b6058aa1986764e8025b",
            "artifact_sha256": artifact_sha256,
        })
        with open(os.path.join(run_root, "verification.json"),
                  "w", encoding="utf-8") as handle:
            json.dump(verification, handle, sort_keys=True)
        identity = {
            "schema_version": "capd_proactive_stage9_run_identity_v2_0",
            "contract_id": gate["required_stage9_contract_id"],
            "run_id": run_id,
            "config_sha256": gate["stage9_config_sha256"],
            "result_schema_sha256": stage10.sha256_file(
                os.path.join(ROOT, stage9_config["result_schema"])),
            "stage8_authority_sha256": {
                name: row["sha256"]
                for name, row in stage9_config["stage8_authority"].items()},
            "stage4_authority_sha256": {
                name: row["sha256"]
                for name, row in stage9_config["stage4_authority"].items()},
            "device": "cpu", "formal_b_max": 2,
            "sensitivity_b_max": [1, 2, 4],
            "test_used_for_parameter_selection": False,
        }
        identity["run_identity_sha256"] = stage10.fingerprint_value(identity)
        with open(os.path.join(run_root, "run_identity.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(identity, handle, sort_keys=True)
        resolved = copy.deepcopy(stage9_config)
        resolved.update({"run_id": run_id,
                         "run_identity_sha256": identity["run_identity_sha256"],
                         "config_sha256": gate["stage9_config_sha256"]})
        with open(os.path.join(run_root, "resolved_config.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(resolved, handle, sort_keys=True)
        preflight = {
            "schema_version": "capd_proactive_stage9_preflight_v2_0",
            "contract_id": gate["required_stage9_contract_id"],
            "status": "passed", "stage8_stage9_entry_gate": "satisfied",
            "stage8_formal_job_count": 80,
            "stage8_artifacts_read_only": True,
            "test_used_for_parameter_selection": False, "device": "cpu"}
        with open(os.path.join(run_root, "preflight.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(preflight, handle, sort_keys=True)
        verification["artifact_sha256"] = {
            relative: stage10.sha256_file(os.path.join(run_root, relative))
            for relative in gate["stage9_required_files"]
            if relative not in ("verification.json", "run_state.json")}
        with open(os.path.join(run_root, "verification.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(verification, handle, sort_keys=True)

    def test_historical_r1_run_directory_is_rejected(self):
        result = stage10.audit_stage9_run(
            ROOT,
            os.path.join(ROOT, "outputs", "capd_proactive_stage9",
                         "stage9-overhead-r1"),
            self._gate_config())
        self.assertEqual("stage10_formal_blocked_by_stage9", result["status"])
        self.assertFalse(result["formal_authorized"])
        self.assertIn("stage9_overhead_verified", " ".join(result["reasons"]))

    def test_forged_run_directory_is_rejected_before_stage10_gate(self):
        trusted_output = os.path.join(ROOT, "outputs", "capd_proactive_stage9")
        with tempfile.TemporaryDirectory(dir=trusted_output) as run_root:
            self._write_verified_run(run_root)
            receipt = stage10.audit_stage9_run(ROOT, run_root, self._gate_config())
            self.assertEqual("stage10_formal_blocked_by_stage9", receipt["status"])
            self.assertFalse(receipt["formal_authorized"])
            self.assertTrue(any("structurally incomplete" in reason
                                for reason in receipt["reasons"]))
            self.assertNotIn("sha_chain_verified", receipt)
            self.assertEqual(os.path.basename(run_root), receipt["source_run_id"])
            self.assertIn("verification.json", receipt["source_artifact_sha256"])

    def test_missing_or_tampered_artifact_is_rejected_before_gate(self):
        trusted_output = os.path.join(ROOT, "outputs", "capd_proactive_stage9")
        with tempfile.TemporaryDirectory(dir=trusted_output) as run_root:
            self._write_verified_run(run_root)
            with open(os.path.join(run_root, "memory_breakdown.json"),
                      "a", encoding="utf-8") as handle:
                handle.write("tamper")
            result = stage10.audit_stage9_run(ROOT, run_root, self._gate_config())
            self.assertEqual("stage10_formal_blocked_by_stage9", result["status"])
            self.assertFalse(result["formal_authorized"])
            self.assertTrue(any("artifact SHA mismatch" in reason
                                for reason in result["reasons"]))


class Stage10RunnerTest(unittest.TestCase):

    _TEST_CLASSES = [
        "tests.test_capd_proactive_stage10.Stage10ConfigContractTest",
        "tests.test_capd_proactive_stage10.Stage10EventHeapTest",
        "tests.test_capd_proactive_stage10.Stage10StateContractTest",
        "tests.test_capd_proactive_stage10.Stage10ArrivalTest",
        "tests.test_capd_proactive_stage10.Stage10SimulationTest",
        "tests.test_capd_proactive_stage10.Stage10FormalGateTest",
    ]

    def _write_real_test_log(self, output):
        test_log = os.path.join(output, "source-test.log")
        command_args = ([sys.executable, "-m", "unittest"] +
                        self._TEST_CLASSES + ["-v"])
        completed = subprocess.run(
            command_args, cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stdout)
        command = "python -m unittest " + " ".join(self._TEST_CLASSES) + " -v"
        with open(test_log, "w", encoding="utf-8") as handle:
            handle.write("COMMAND: " + command + chr(10))
            handle.write(completed.stdout)
        return test_log

    def _invoke_fixture(self, output, test_log, expected_sha=None):
        runner = os.path.join(ROOT, "scripts", "run_capd_proactive_stage10.py")
        return subprocess.run(
            [sys.executable, runner, "--config", CONFIG_PATH,
             "--mode", "fixture", "--output-root", output,
             "--run-id", "fixture-test", "--test-log-input", test_log,
             "--test-log-sha256", expected_sha or stage10.sha256_file(test_log)],
            cwd=ROOT, capture_output=True, text=True, check=False)

    def test_fixture_runner_writes_candidate_ready_artifacts(self):
        with tempfile.TemporaryDirectory() as output:
            test_log = self._write_real_test_log(output)
            completed = self._invoke_fixture(output, test_log)
            self.assertEqual(0, completed.returncode, completed.stderr)
            run_root = os.path.join(output, "fixture-test")
            for name in ("config.json", "event_model.md", "parameters.md",
                         "fixture_results.jsonl", "test_log.txt", "formal_gate.json",
                         "stage9_compatibility_receipt.json", "test_evidence.json",
                         "verification.json", "run_state.json", "manifest.json",
                         "SHA256SUMS", "README.md"):
                self.assertTrue(os.path.isfile(os.path.join(run_root, name)), name)
            run_state = load_json(os.path.join(run_root, "run_state.json"))
            self.assertEqual("stage10_simulator_tests_passed", run_state["status"])
            self.assertTrue(run_state["stage10_simulator_implemented"])
            self.assertTrue(run_state["stage10_simulator_tests_passed"])
            self.assertTrue(run_state["stage10_formal_blocked_by_stage9"])
            self.assertFalse(run_state["stage10_formally_verified"])
            evidence = load_json(os.path.join(run_root, "test_evidence.json"))
            self.assertGreaterEqual(evidence["test_count"], 10)
            self.assertEqual(evidence["test_count"], evidence["result_line_count"])
            self.assertEqual("OK", evidence["final_status"])
            self.assertIn("tests.test_capd_proactive_stage10", evidence["command"])
            gate = load_json(os.path.join(run_root, "formal_gate.json"))
            self.assertEqual("stage10_formal_blocked_by_stage9", gate["status"])

    def test_manifest_and_sha256sums_recompute_independently(self):
        with tempfile.TemporaryDirectory() as output:
            test_log = self._write_real_test_log(output)
            completed = self._invoke_fixture(output, test_log)
            self.assertEqual(0, completed.returncode, completed.stderr)
            root = os.path.join(output, "fixture-test")
            manifest = load_json(os.path.join(root, "manifest.json"))
            self.assertNotIn("manifest.json", manifest["files"])
            self.assertNotIn("SHA256SUMS", manifest["files"])
            for name, digest in manifest["files"].items():
                self.assertEqual(digest, stage10.sha256_file(os.path.join(root, name)))
            with open(os.path.join(root, "SHA256SUMS"), encoding="utf-8") as handle:
                checksum_lines = [line.strip().split("  ", 1) for line in handle if line.strip()]
            self.assertIn("manifest.json", [name for _, name in checksum_lines])
            self.assertNotIn("SHA256SUMS", [name for _, name in checksum_lines])
            for digest, name in checksum_lines:
                self.assertEqual(digest, stage10.sha256_file(os.path.join(root, name)))

    def test_independent_verifier_rejects_rehashed_tamper_and_extra_file(self):
        with tempfile.TemporaryDirectory() as output:
            test_log = self._write_real_test_log(output)
            completed = self._invoke_fixture(output, test_log)
            self.assertEqual(0, completed.returncode, completed.stderr)
            root = os.path.join(output, "fixture-test")
            lines = []
            with open(os.path.join(root, "fixture_results.jsonl"),
                      encoding="utf-8") as handle:
                for raw in handle:
                    line = json.loads(raw)
                    lines.append(line)
            lines[0]["observed"]["emergency_fallback_count"] += 1
            with open(os.path.join(root, "fixture_results.jsonl"), "w",
                      encoding="utf-8", newline="") as handle:
                handle.write("".join(json.dumps(line, sort_keys=True) + "\n"
                                    for line in lines))
            manifest = stage10_runner._manifest(Path(root))
            stage10_runner.write_json(Path(root) / "manifest.json", manifest)
            stage10_runner._write_checksums(Path(root))
            with self.assertRaises(stage10.Stage10ContractError):
                stage10_runner.verify_run(root)

        with tempfile.TemporaryDirectory() as output:
            test_log = self._write_real_test_log(output)
            completed = self._invoke_fixture(output, test_log)
            self.assertEqual(0, completed.returncode, completed.stderr)
            root = os.path.join(output, "fixture-test")
            with open(os.path.join(root, "unexpected.bin"), "wb") as handle:
                handle.write(b"unexpected")
            with self.assertRaises(stage10.Stage10ContractError):
                stage10_runner.verify_run(root)

    def test_n_a_is_used_only_for_empty_blocking_samples(self):
        report = stage10.render_report({
            "foreground_blocking_time_mean": None,
            "foreground_blocking_time_p95": None,
            "blocking_sample_count": 0})
        self.assertIn("N/A", report)
        self.assertNotIn("mean=0", report)

    def test_empty_failed_wrong_module_or_tampered_logs_are_rejected(self):
        invalid_logs = {
            "empty": "",
            "failed": ("COMMAND: python -m unittest "
                       "tests.test_capd_proactive_stage10 -v\n"
                       "Ran 27 tests in 0.01s\n"
                       "FAILED (failures=1)\n"),
            "wrong-module": ("COMMAND: python -m unittest tests.other -v\n"
                              "Ran 27 tests in 0.01s\nOK\n"),
        }
        for name, content in invalid_logs.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as output:
                test_log = os.path.join(output, "invalid.log")
                with open(test_log, "w", encoding="utf-8") as handle:
                    handle.write(content)
                completed = self._invoke_fixture(output, test_log)
                self.assertNotEqual(0, completed.returncode)
                self.assertFalse(os.path.exists(os.path.join(output, "fixture-test")))

        with tempfile.TemporaryDirectory() as output:
            test_log = self._write_real_test_log(output)
            expected_sha = stage10.sha256_file(test_log)
            with open(test_log, "a", encoding="utf-8") as handle:
                handle.write("tampered\n")
            completed = self._invoke_fixture(output, test_log, expected_sha)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(os.path.exists(os.path.join(output, "fixture-test")))

    def test_formal_mode_without_a_verified_receipt_writes_no_run(self):
        runner = os.path.join(ROOT, "scripts", "run_capd_proactive_stage10.py")
        with tempfile.TemporaryDirectory() as output:
            completed = subprocess.run(
                [sys.executable, runner, "--config", CONFIG_PATH,
                 "--mode", "formal", "--output-root", output,
                 "--run-id", "must-not-be-created"],
                cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(os.path.exists(
                os.path.join(output, "must-not-be-created")))


class Stage10DocumentationTest(unittest.TestCase):

    def test_docs_state_candidate_ready_and_formal_blocked(self):
        status_path = os.path.join(ROOT, "docs", "CAPD_PROACTIVE_STAGE10_STATUS_CN.md")
        server_path = os.path.join(ROOT, "docs", "CAPD_PROACTIVE_STAGE10_SERVER_CN.md")
        with open(status_path, encoding="utf-8") as handle:
            status = handle.read()
        with open(server_path, encoding="utf-8") as handle:
            server = handle.read()
        self.assertIn("candidate-ready", status)
        self.assertIn("stage10_formal_blocked_by_stage9", status)
        self.assertIn("stage9_overhead_verified", server)
        self.assertIn("stage9-overhead-r1", server)
        self.assertIn("stage10_formally_verified=false", status)
        self.assertNotIn("stage10_formally_verified=true", status)
