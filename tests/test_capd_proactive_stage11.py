import csv
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qmap import proactive_stage11 as stage11


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "finals" / "capd_proactive_stage11a.json"
SCHEMA_PATH = ROOT / "configs" / "finals" / "capd_proactive_stage11a_result_schema.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class Stage11ConfigTest(unittest.TestCase):
    def test_config_contract_is_independent_and_has_four_profiles(self):
        config = load_json(CONFIG_PATH)
        stage11.validate_config(config)
        self.assertEqual(config["contract_id"], "CAPD-PROACTIVE-STAGE11A-1.0")
        self.assertEqual(
            config["cost_profiles"]["default"]["weights"],
            {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10},
        )
        self.assertEqual(
            set(config["cost_profiles"]),
            {"read_light", "default", "write_expensive", "migration_expensive"},
        )

    def test_missing_numeric_values_are_null_in_json_contract(self):
        schema = load_json(SCHEMA_PATH)
        self.assertEqual(schema["null_numeric_representation"], "null")
        self.assertEqual(schema["report_missing_numeric_representation"], "N/A")

    def test_main_b_max_is_immutable_and_sensitivity_is_analysis_only(self):
        config = load_json(CONFIG_PATH)
        self.assertEqual(config["main_control"]["b_max"], 2)
        self.assertEqual(config["sensitivity_grid"]["b_max"], [1, 2, 4])
        self.assertTrue(config["sensitivity_grid"]["analysis_only"])

    def test_input_ablation_is_blocked_until_pairwise_training_receipts_exist(self):
        config = load_json(CONFIG_PATH)
        self.assertEqual(config["input_ablation"]["status"], "BLOCKED")
        self.assertEqual(
            config["input_ablation"]["variants"],
            ["CAPD-Full", "CAPD-NoVPN", "CAPD-NoContext", "CAPD-NoPageState"],
        )


class Stage11OfflineTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="stage11a-")
        self.fixture_root = Path(self.tempdir) / "stage8"
        _write_stage8_fixture(self.fixture_root)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_job_join_reads_raw_counters_from_result_metrics(self):
        rows = stage11.load_stage8_rows(self.fixture_root)
        self.assertEqual(rows[0]["raw_access_count"], 600000)
        self.assertEqual(rows[0]["reactive_demotions"], 1314)
        self.assertEqual(rows[0]["source_job_id"], "standard__canneal__reactive_lru")

    def test_job_join_rejects_missing_result_sha(self):
        manifest_path = self.fixture_root / "jobs" / "standard__canneal__reactive_lru" / "job_manifest.json"
        manifest = load_json(manifest_path)
        manifest.pop("result_sha256")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(stage11.Stage11ContractError):
            stage11.load_stage8_rows(self.fixture_root)

    def test_tampered_result_bytes_are_rejected(self):
        result_path = self.fixture_root / "jobs" / "standard__canneal__reactive_lru" / "result.json"
        result = load_json(result_path)
        result["metrics"]["raw_access_count"] = 600001
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaises(stage11.Stage11ContractError):
            stage11.load_stage8_rows(self.fixture_root)

    def test_profile_recompute_uses_integer_counts_and_nulls_zero_access(self):
        source = stage11.load_stage8_rows(self.fixture_root)[0]
        result = stage11.recompute_profile_row(source, "default")
        self.assertEqual(result["weighted_cost"], 623172)
        self.assertEqual(result["weighted_cost_per_access"], 1.03862)
        zero = dict(source, raw_access_count=0)
        self.assertIsNone(stage11.recompute_profile_row(zero, "default")["weighted_cost_per_access"])

    def test_empty_input_is_rejected(self):
        empty = Path(self.tempdir) / "empty"
        empty.mkdir()
        with self.assertRaises(stage11.Stage11ContractError):
            stage11.load_stage8_rows(empty)


class Stage11GateTest(unittest.TestCase):
    def test_missing_stage9_is_not_verifiable(self):
        receipt = stage11.audit_stage9_gate("missing-stage9")
        self.assertEqual(receipt["status"], "NOT_VERIFIABLE")
        self.assertFalse(receipt["formal_authorized"])

    def test_stage10_fixture_is_blocked_not_formally_verified(self):
        receipt = stage11.audit_stage10_fixture("missing-stage10")
        self.assertEqual(receipt["status"], "NOT_VERIFIABLE")
        self.assertFalse(receipt["formal_authorized"])

    def test_complete_stage10a_fixture_is_blocked(self):
        root = ROOT / "outputs" / "capd_proactive_stage10" / "stage10-async-simulator-r1"
        receipt = stage11.audit_stage10_fixture(root)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["reason_code"], "stage10a_fixture_only")
        self.assertFalse(receipt["formal_authorized"])

    def test_historical_stage9_run_is_not_verifiable(self):
        root = ROOT / "outputs" / "capd_proactive_stage9" / "stage9-overhead-r1"
        receipt = stage11.audit_stage9_gate(root)
        self.assertIn(receipt["status"], ("BLOCKED", "NOT_VERIFIABLE"))
        self.assertFalse(receipt["formal_authorized"])


class Stage11GridTest(unittest.TestCase):
    def test_grid_digest_is_order_independent(self):
        config = load_json(CONFIG_PATH)
        config["sensitivity_grid"]["watermark_candidates"] = [4, 8]
        config["sensitivity_grid"]["label_weight_candidates"] = [1]
        first = stage11.freeze_grid(config)
        shuffled = copy.deepcopy(config)
        shuffled["sensitivity_grid"]["b_max"] = [4, 1, 2]
        shuffled["sensitivity_grid"]["capacity_working_set_fraction"] = [0.6, 0.2, 0.4]
        second = stage11.freeze_grid(shuffled)
        self.assertEqual(first["frozen_grid_sha256"], second["frozen_grid_sha256"])

    def test_sync_mode_blocks_empty_unapproved_watermark_grid(self):
        with self.assertRaises(stage11.Stage11Blocked):
            stage11.require_sync_grid(load_json(CONFIG_PATH))

    def test_input_ablation_rows_are_blocked_and_top_batch_differs_only_in_count(self):
        rows = stage11.expand_ablation_grid(load_json(CONFIG_PATH))
        self.assertTrue(all(row["evidence_status"] == "BLOCKED"
                            for row in rows if row["parameter_family"] == "input_ablation"))
        top1, topb = stage11.top_batch_pair(rows)
        self.assertEqual(stage11.config_without_selection_count(top1),
                         stage11.config_without_selection_count(topb))
        self.assertNotEqual(top1["selection_count"], topb["selection_count"])


class Stage11RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="stage11a-runner-")
        self.fixture_root = Path(self.tempdir) / "stage8"
        _write_stage8_fixture(self.fixture_root)
        config = load_json(CONFIG_PATH)
        config["stage8_authority_path"] = str(self.fixture_root)
        self.config_path = Path(self.tempdir) / "config.json"
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self.output_root = Path(self.tempdir) / "outputs"

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def invoke(self, *extra):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_capd_proactive_stage11.py"),
             "--config", str(self.config_path), "--output-root", str(self.output_root),
             "--run-id", "runner-test", *extra],
            cwd=str(ROOT), capture_output=True, text=True)

    def test_external_gate_failure_still_writes_offline_candidate(self):
        completed = self.invoke("--mode", "all", "--verify")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = load_json(self.output_root / "runner-test" / "stage11a_results.json")
        statuses = {row["evidence_status"] for row in results["rows"]}
        self.assertIn("candidate-ready", statuses)
        self.assertIn("NOT_VERIFIABLE", statuses)

    def test_existing_run_id_is_rejected_without_overwrite(self):
        first = self.invoke("--mode", "offline")
        second = self.invoke("--mode", "offline")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotEqual(second.returncode, 0)

    def test_global_preflight_failure_creates_no_run_directory(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_capd_proactive_stage11.py"),
             "--config", str(Path(self.tempdir) / "missing.json"),
             "--output-root", str(self.output_root), "--run-id", "global-fail"],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.output_root / "global-fail").exists())


class Stage11VerificationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="stage11a-verify-")
        self.fixture_root = Path(self.tempdir) / "stage8"
        _write_stage8_fixture(self.fixture_root)
        config = load_json(CONFIG_PATH)
        config["stage8_authority_path"] = str(self.fixture_root)
        self.config_path = Path(self.tempdir) / "config.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.output_root = Path(self.tempdir) / "outputs"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_capd_proactive_stage11.py"),
             "--config", str(self.config_path), "--output-root", str(self.output_root),
             "--run-id", "verify-test", "--mode", "all", "--verify"],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.run_root = self.output_root / "verify-test"

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_manifest_and_checksums_verify(self):
        verified = __import__("scripts.run_capd_proactive_stage11", fromlist=["verify_run"])
        self.assertEqual(verified.verify_run(self.run_root)["status"], "verified")

    def test_payload_tamper_fails_closed(self):
        path = self.run_root / "stage11a_report.md"
        path.write_text(path.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        verified = __import__("scripts.run_capd_proactive_stage11", fromlist=["verify_run"])
        with self.assertRaises(Exception):
            verified.verify_run(self.run_root)

    def test_no_formal_stage11_status_is_generated(self):
        state = load_json(self.run_root / "run_state.json")
        results = load_json(self.run_root / "stage11a_results.json")
        self.assertNotEqual(state["status"], "stage11a_formally_verified")
        self.assertTrue(all(row["evidence_status"] != "formally_verified" for row in results["rows"]))

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_stage8_fixture(root):
    job_id = "standard__canneal__reactive_lru"
    job_dir = root / "jobs" / job_id
    (root / "artifacts").mkdir(parents=True)
    job_dir.mkdir(parents=True)
    plan = {
        "job_id": job_id,
        "track": "standard",
        "workload": "canneal",
        "policy": "reactive_lru",
        "seed": None,
        "D": 120,
        "F_low": 6,
        "F_target": 16,
        "K": 8,
        "W_ref": 1196,
        "b_max": 2,
        "history_H": 20,
        "alpha": 0.15,
        "beta": 0.4,
        "trace_sha256": "trace-sha",
        "source_interval": {"start_inclusive": 0, "end_exclusive": 3000000},
        "evaluation_interval": {"start_inclusive": 0, "end_exclusive": 600000},
        "initial_state_sha256": "initial-sha",
        "cost_profile_sha256": "cost-sha",
        "checkpoint": None,
        "source_standard_test_sha256": "standard-test-sha",
        "source_raw_interval": None,
        "derived_csv_sha256": None,
        "pressure_lock_sha256": None,
        "pressure_bundle_manifest_sha256": None,
        "addendum_sha256": None,
        "parent_r4_contract_sha256": None,
    }
    metrics = {
        "dram_hits": 598566,
        "nvm_reads": 1,
        "nvm_writes": 1433,
        "proactive_demotions": 0,
        "reactive_demotions": 1314,
        "emergency_demotions": 0,
        "total_demotions": 1314,
        "raw_access_count": 600000,
        "weighted_cost": 623172,
        "weighted_cost_per_access": 1.03862,
        "fallback_rate": 0.0,
        "early_reuse": {},
        "decision_count": 0,
        "number_of_proactive_cycles": 0,
    }
    result = dict(plan)
    result.update({
        "schema_version": "capd_proactive_stage8_job_result_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "formal_test": True,
        "test_used_for_selection": False,
        "selector_status": "disabled",
        "B": None,
        "old_finals_v3_stage_artifacts_used": False,
        "performance_selection_performed": False,
        "checkpoint": None,
        "source_standard_test_sha256": "standard-test-sha",
        "source_raw_interval": None,
        "pressure_lock_sha256": None,
        "pressure_bundle_manifest_sha256": None,
        "addendum_sha256": None,
        "parent_r4_contract_sha256": None,
        "events": [{} for _ in range(1314)],
        "rounds": [],
        "cycles": [],
        "metrics": metrics,
        "future_information": "not_accessed",
    })
    result["semantic_result_sha256"] = stage11.fingerprint_value_for_stage8(result)
    result_path = job_dir / "result.json"
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    job_manifest = {
        "schema_version": "capd_proactive_stage8_job_manifest_v2_0",
        "contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "status": "completed",
        "job_identity": {"plan_job": plan},
        "job_identity_sha256": stage11.fingerprint_value_for_stage8({"plan_job": plan}),
        "result_sha256": _sha256(result_path),
        "semantic_result_sha256": result["semantic_result_sha256"],
    }
    (job_dir / "job_manifest.json").write_text(json.dumps(job_manifest, sort_keys=True), encoding="utf-8")
    root_manifest = {
        "contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "job_count": 1,
        "jobs": [plan],
    }
    (root / "job_manifest.json").write_text(json.dumps(root_manifest, sort_keys=True), encoding="utf-8")
    (root / "run_state.json").write_text(json.dumps({
        "contract_id": "CAPD-PROACTIVE-STAGE8-2.0",
        "status": "stage8_sync_replay_verified",
        "completed": ["formal_80_jobs", "verification"],
        "test_used_for_parameter_selection": False,
    }), encoding="utf-8")
    (root / "verification.json").write_text(json.dumps({"status": "stage8_sync_replay_verified"}), encoding="utf-8")
    with open(root / "artifacts" / "per_workload_raw.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["job_id", "track", "workload", "policy", "seed"])
        writer.writeheader()
        writer.writerow({"job_id": job_id, "track": "standard", "workload": "canneal", "policy": "reactive_lru", "seed": ""})


if __name__ == "__main__":
    unittest.main()
