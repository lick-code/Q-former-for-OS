# coding=utf-8
"""Stage-8 frozen contracts, statistics, leakage, and failure fixtures."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from qmap import proactive_stage7_workloads as stage7
from qmap import proactive_stage5_contract as stage5_contract
from qmap import finals_config
from qmap import proactive_cost
from qmap import proactive_stage8_contract as contract
from qmap import proactive_stage8_replay as replay
from qmap import proactive_stage8_results as results


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "configs", "finals", "capd_proactive_stage8.json")


def _config():
  return contract.load_json(CONFIG_PATH)


def _fixture_results():
  authority = contract.audit_authority(
      _config(), ROOT, hash_test_payloads=False,
      require_source_files=False, require_checkpoints=False)
  rows = []
  for index, job in enumerate(authority["jobs"]):
    base = 1000.0 + (index % 24)
    if job["policy"] == "capd":
      base += {3136859: 0.0, 42: 2.0, 2026: 4.0}[job["seed"]]
    metrics = {
        "weighted_cost": base,
        "weighted_cost_per_access": base / 600000.0,
        "dram_hits": 10, "nvm_reads": 20, "nvm_writes": 30,
        "total_demotions": 4, "proactive_demotions": 4,
        "emergency_demotions": 0, "fallback_rate": 0.0,
         "minimum_free_frames": 1, "average_free_frames": 2.0,
         "early_reuse": {
            "windows": {str(delta): {"early_reuse_count": 1, "rate": 0.25}
                        for delta in (64, 256, 1024)},
            "wasted_demotion_count": 1}}
    rows.append({
        "job_id": job["job_id"], "track": job["track"],
        "workload": job["workload"],
        "workload_role": job["workload_role"],
        "policy": job["policy"],
        "seed": job["seed"], "dram_capacity_pages": job["dram_pages"],
        "D": job["controls"]["D"], "W_ref": job["controls"]["W_ref"],
        "F_low": job["controls"]["F_low"],
        "F_target": job["controls"]["F_target"],
        "K": job["controls"]["K"], "b_max": job["controls"]["b_max"],
        "alpha": job["controls"]["alpha"], "beta": job["controls"]["beta"],
        "history_H": job["controls"]["history_H"],
        "test_identity": job["test_identity"],
        "trace_sha256": job["trace_sha256"],
        "source_interval": job["source_interval"],
        "evaluation_interval": job["evaluation_interval"],
        "initial_state_sha256": job["initial_state_sha256"],
        "cost_profile_sha256": job["cost_profile_sha256"],
        "cost_profile": {"name": "default", "weights": contract.FROZEN_COST},
        "page_enter_dram_semantics": "occupies_one_free_frame_regardless_of_source",
        "K": job["controls"]["K"], "b_t_rule": job["controls"]["b_t_rule"],
        "candidate_source": job["controls"]["candidate_source"],
        "fallback_policy": job["controls"]["fallback_policy"],
        "trigger_mode": job["controls"]["trigger_mode"],
        "checkpoint_sha256": job.get("checkpoint", {}).get("sha256")
            if job.get("checkpoint") else None,
        "checkpoint": copy.deepcopy(job.get("checkpoint")),
        "formal_test": True, "test_used_for_selection": False,
        "selector_status": "disabled", "B": None,
        "old_finals_v3_stage_artifacts_used": False,
        "performance_selection_performed": False,
        "candidate_contract_sha256": "c" * 64,
        "capd_generalization": {
            "page_access_oov_count": 0, "page_access_oov_ratio": 0.0,
            "page_unique_oov_count": 0, "page_unique_oov_ratio": 0.0,
            "pc_access_oov_count": 0, "pc_access_oov_ratio": 0.0,
            "pc_unique_oov_count": 0, "pc_unique_oov_ratio": 0.0,
            "vocabulary_expansion_allowed": False, "unk_index": 0},
        "tpp_parameters": {
            "epoch_length": 1024, "cold_threshold": 1,
            "dirty_tie_break": False, "promotion_performed": False,
            "future_information_accessed": False,
            "fallback_to_lru_used": False},
        "future_information": "candidate_scoped_oracle_only"
            if job["policy"] == "oracle" else "not_accessed",
        "metrics": metrics, "semantic_result_sha256": "d" * 64})
  return rows


class Stage8ContractTest(unittest.TestCase):

  def test_frozen_config_is_exact(self):
    contract.validate_config(_config())

  def test_each_frozen_family_mutation_is_rejected(self):
    mutations = []
    for path, value in (
        (("frozen_controls", "b_max"), 64),
        (("cost_profile", "weights", "nvm_write"), 9),
        (("capd", "best_seed_selection_allowed"), True),
        (("tpp_inspired", "epoch_length"), 256),
        (("statistics", "bootstrap_seed"), 1),
        (("deterministic_runtime", "cublas_workspace_config"), ":16:8")):
      item = copy.deepcopy(_config())
      target = item
      for key in path[:-1]:
        target = target[key]
      target[path[-1]] = value
      mutations.append(item)
    for item in mutations:
      with self.assertRaises(contract.Stage8ContractError):
        contract.validate_config(item)

  def test_manifest_has_exact_80_track_jobs(self):
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    expected = [row["job_id"] for row in contract.expected_jobs(authority)]
    self.assertEqual(80, len(expected))
    self.assertEqual(expected, [row["job_id"] for row in authority["jobs"]])
    self.assertEqual(80, len(set(expected)))
    self.assertEqual(48, sum(row["track"] == "standard"
                              for row in authority["jobs"]))
    self.assertEqual(32, sum(row["track"] == "pressure"
                              for row in authority["jobs"]))

  def test_manifest_has_five_deterministic_and_three_capd_jobs_per_cell(self):
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    cells = {}
    for job in authority["jobs"]:
      cells.setdefault((job["track"], job["workload"]), []).append(job)
    self.assertEqual(10, len(cells))
    for jobs in cells.values():
      deterministic = [job for job in jobs if job["policy"] != "capd"]
      capd = [job for job in jobs if job["policy"] == "capd"]
      self.assertEqual(list(contract.DETERMINISTIC_POLICIES),
                       [job["policy"] for job in deterministic])
      self.assertEqual(list(contract.CAPD_SEEDS), [job["seed"] for job in capd])

  def test_pressure_manifest_excludes_structural_zero_workloads(self):
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    self.assertEqual(
        list(contract.PRESSURE_WORKLOADS),
        list(dict.fromkeys(row["workload"] for row in authority["jobs"]
                           if row["track"] == "pressure")))
    self.assertFalse(any(row["track"] == "pressure" and row["workload"] in
                         ("streamcluster_pressure", "fluidanimate")
                         for row in authority["jobs"]))

  def test_pressure_jobs_bind_complete_frozen_provenance(self):
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    for job in (row for row in authority["jobs"] if row["track"] == "pressure"):
      source = authority["pressure_rows"][job["workload"]]
      self.assertEqual(source["derived_sha256"], job["derived_csv_sha256"])
      self.assertEqual(source["source_test_sha256"],
                       job["source_standard_test_sha256"])
      self.assertEqual({
          "start_inclusive": source["source_interval_start_inclusive"],
          "end_exclusive": source["source_interval_end_exclusive"]},
          job["source_raw_interval"])
      self.assertEqual({"start_inclusive": 0, "end_exclusive": 500000},
                       job["evaluation_interval"])
      self.assertEqual(_config()["authorities"]["pressure_test_lock"]["sha256"],
                       job["pressure_lock_sha256"])
      self.assertEqual(
          _config()["authorities"]["pressure_bundle_manifest"]["sha256"],
          job["pressure_bundle_manifest_sha256"])
      self.assertEqual(source["addendum_sha256"], job["addendum_sha256"])
      self.assertEqual(source["contract_sha256"],
                       job["parent_r4_contract_sha256"])

  def test_standard_and_pressure_share_candidate_contract_per_workload(self):
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    for workload in contract.PRESSURE_WORKLOADS:
      values = {
          row["candidate_contract_sha256"] for row in authority["jobs"]
          if row["workload"] == workload}
      self.assertEqual(1, len(values), workload)

  def test_pressure_lock_rejects_forbidden_workload(self):
    config = _config()
    lock = contract.load_json(os.path.join(
        ROOT, config["authorities"]["pressure_test_lock"]["path"]))
    bundle = contract.load_json(os.path.join(
        ROOT, config["authorities"]["pressure_bundle_manifest"]["path"]))
    forbidden = copy.deepcopy(lock["workloads"][0])
    forbidden["workload"] = "streamcluster_pressure"
    lock["workloads"].append(forbidden)
    with self.assertRaises(contract.Stage8ContractError):
      contract._pressure_rows(ROOT, lock, bundle, "a" * 64, "b" * 64, False)

  def test_pressure_lock_and_bundle_share_addendum_and_parent_r4(self):
    config = _config()
    lock = contract.load_json(os.path.join(
        ROOT, config["authorities"]["pressure_test_lock"]["path"]))
    bundle = contract.load_json(os.path.join(
        ROOT, config["authorities"]["pressure_bundle_manifest"]["path"]))
    bundle["authority_sha256"]["pressure_window_selection_addendum"] = "0" * 64
    with self.assertRaises(contract.Stage8ContractError):
      contract._pressure_rows(ROOT, lock, bundle, "a" * 64, "b" * 64, False)
    bundle = contract.load_json(os.path.join(
        ROOT, config["authorities"]["pressure_bundle_manifest"]["path"]))
    bundle["authority_sha256"]["parent_pressure_contract"] = "0" * 64
    with self.assertRaises(contract.Stage8ContractError):
      contract._pressure_rows(ROOT, lock, bundle, "a" * 64, "b" * 64, False)

  def test_standard_missing_server_payload_path_is_fail_closed(self):
    config = _config()
    lock = contract.load_json(os.path.join(
        ROOT, config["authorities"]["standard_test_lock"]["path"]))
    self.assertIn("stage7-server-suite-r1", lock["workloads"][0]["path"])
    lock["workloads"][0]["path"] = (
        "outputs/capd_proactive_stage7/stage7-server-suite-r1/"
        "missing-fail-closed-fixture/test.csv")
    with self.assertRaises((contract.Stage8ContractError,
                            stage7.Stage7ContractError)):
      contract._standard_rows(ROOT, lock, True)

  def test_result_schema_sha_is_bound_and_audited(self):
    config = _config()
    schema_path = os.path.join(ROOT, config["result_schema"])
    self.assertEqual(contract.fingerprint_file(schema_path),
                     config["result_schema_sha256"])
    config["result_schema_sha256"] = "0" * 64
    with self.assertRaises(contract.Stage8ContractError):
      contract.audit_authority(
          config, ROOT, hash_test_payloads=False,
          require_source_files=False, require_checkpoints=False)

  def test_replay_parameters_are_injected_from_job_controls(self):
    controls = {"D": 21, "F_low": 1, "F_target": 3, "K": 8,
                "b_max": 2, "history_H": 20}
    parameters = replay.replay_parameters_for_job("proactive_lru", controls)
    self.assertEqual(21, parameters.dram_capacity_pages)
    self.assertEqual(1, parameters.F_low)
    self.assertEqual(3, parameters.F_target)
    self.assertEqual(8, parameters.candidate_size_K)
    self.assertEqual(2, parameters.b_max)
    self.assertEqual(20, parameters.history_window_size)
    tpp = replay.replay_parameters_for_job("tpp_inspired", controls)
    self.assertEqual((1, 3, 8, 2),
                     (tpp.F_low, tpp.F_target, tpp.candidate_size_K,
                      tpp.b_max))

  def test_legacy_finals_path_is_rejected(self):
    with self.assertRaises(stage7.Stage7ContractError):
      stage7.repository_path(ROOT, "outputs/results/finals_v3_official/x.json")

  def test_authority_sha_tamper_is_rejected(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
      path = os.path.join(directory, "authority.json")
      contract.write_json_atomic(path, {"ok": True})
      relative = os.path.relpath(path, ROOT).replace(os.sep, "/")
      with self.assertRaises(contract.Stage8ContractError):
        contract._authority_file(ROOT, {"path": relative, "sha256": "0" * 64})

  def test_failed_run_id_is_fail_closed(self):
    import importlib.util
    script = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    spec = importlib.util.spec_from_file_location("stage8_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
      contract.write_json_atomic(os.path.join(directory, "run_state.json"), {
          "status": contract.NOT_VERIFIED})
      with self.assertRaises(contract.Stage8ContractError):
        module._reject_failed_run(directory)

  def test_git_state_excludes_stage8_runtime_output(self):
    import importlib.util
    script = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    spec = importlib.util.spec_from_file_location("stage8_git_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
      def git(*args):
        return subprocess.run(
            ["git"] + list(args), cwd=directory, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

      git("init", "-q")
      git("config", "user.email", "stage8-test@example.invalid")
      git("config", "user.name", "Stage8 Test")
      with open(os.path.join(directory, "tracked.txt"), "w",
                encoding="utf-8") as handle:
        handle.write("baseline\n")
      git("add", "tracked.txt")
      git("commit", "-qm", "initial")

      output_root = os.path.join(
          directory, "outputs", "capd_proactive_stage8")
      os.makedirs(os.path.join(output_root, "new-run"))
      with open(os.path.join(output_root, "new-run", "preflight.json"),
                "w", encoding="utf-8") as handle:
        handle.write("{}\n")
      self.assertFalse(module._git_state(
          directory, output_root)["dirty_worktree"])
      self.assertFalse(module._git_state(directory)["dirty_worktree"])

      with open(os.path.join(directory, "unrelated.txt"), "w",
                encoding="utf-8") as handle:
        handle.write("unrelated\n")
      self.assertTrue(module._git_state(
          directory, output_root)["dirty_worktree"])

  def test_cuda_runtime_environment_is_fail_closed_and_exact(self):
    import importlib.util
    script = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    spec = importlib.util.spec_from_file_location("stage8_runtime_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with mock.patch.dict(os.environ, {
        "CUBLAS_WORKSPACE_CONFIG": ":16:8", "PYTHONHASHSEED": "0"},
                         clear=False):
      with self.assertRaises(contract.Stage8ContractError):
        module._runtime_environment(_config(), "cuda:0")
    with mock.patch.dict(os.environ, {
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "PYTHONHASHSEED": "0"},
                         clear=False):
      self.assertEqual(":4096:8", module._runtime_environment(
          _config(), "cuda:0")["CUBLAS_WORKSPACE_CONFIG"])
    with open(os.path.join(
        ROOT, "scripts", "validate_capd_proactive_stage8_server.sh"),
        "r", encoding="utf-8") as handle:
      shell = handle.read()
    self.assertLess(shell.index("export CUBLAS_WORKSPACE_CONFIG"),
                    shell.index("import torch"))
    self.assertIn('awaiting_formal_replay_confirmation', shell)
    self.assertNotIn('formal_144_job_execute', shell)
    self.assertNotIn(' scripts/run_capd_proactive_stage8.py \\\n    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" --device "${DEVICE}" execute', shell)

  def test_cuda_smoke_inherits_exact_stage4_checkpoint_criterion(self):
    import importlib.util
    script = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    spec = importlib.util.spec_from_file_location("stage8_smoke_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stage5_config = stage5_contract.load_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage5.json"))
    frozen = stage5_contract.audit_stage4_authority(
        stage5_config, ROOT, require_checkpoints=True)
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    authority["checkpoint_bindings"] = {
        int(row["seed"]): row for row in frozen["checkpoints"]}
    authority["checkpoint_authority"] = authority["checkpoint_bindings"]
    for seed in contract.CAPD_SEEDS:
      checkpoint = module._smoke_checkpoint(authority, seed)
      self.assertEqual("minimum_valid_loss_only",
                       checkpoint["selection_criterion"])
      self.assertEqual(seed, checkpoint["seed"])
      self.assertEqual(64, len(checkpoint["sha256"]))
    fake_cuda = types.SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 1,
        set_device=lambda index: None, synchronize=lambda index=None: None,
        empty_cache=lambda: None, get_device_name=lambda index: "fixture-gpu")
    fake_torch = types.SimpleNamespace(
        cuda=fake_cuda, __version__="fixture",
        use_deterministic_algorithms=lambda enabled: None,
        backends=types.SimpleNamespace(cudnn=types.SimpleNamespace(
            benchmark=True, deterministic=False)))
    calls = []
    def fake_replay(*args, **kwargs):
      checkpoint = kwargs["checkpoint"]
      self.assertEqual("minimum_valid_loss_only",
                       checkpoint["selection_criterion"])
      calls.append(checkpoint["seed"])
      return {"semantic_result_sha256": str(checkpoint["seed"])}
    with tempfile.TemporaryDirectory() as directory:
      contract.write_json_atomic(os.path.join(directory, "run_state.json"), {
          "status": contract.IMPLEMENTED, "completed": ["preflight"]})
      loaded = (directory, _config(), {}, None, authority, {})
      with mock.patch.object(module, "_loaded_run", return_value=loaded), \
           mock.patch.object(module.proactive_stage8_replay,
                             "run_formal_test_replay",
                             side_effect=fake_replay), \
           mock.patch.dict(os.environ, {
               "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
               "PYTHONHASHSEED": "0"}, clear=False), \
           mock.patch.dict("sys.modules", {"torch": fake_torch}):
        module.runtime_smoke(types.SimpleNamespace(device="cuda:0"))
      self.assertEqual(list(contract.CAPD_SEEDS), calls)
      receipt = contract.load_json(os.path.join(directory, "runtime_smoke.json"))
      self.assertEqual("passed", receipt["status"])
      self.assertEqual(3, len(receipt["checkpoint_receipts"]))

  def test_formal_replay_requires_stage8_locked_authorization(self):
    job = {"track": "standard", "policy": "reactive_lru",
           "formal_test": False, "split_role": "test",
           "test_identity": "x", "controls": {"D": 20}}
    lock = {"policy_replay_allowed_stage": 8, "fairness_identity": "x",
            "accesses": 1, "workload": "fixture"}
    with self.assertRaises(contract.Stage8ContractError):
      replay.run_formal_test_replay({}, None, [{"page": 1, "rw": 0}],
                                    job, lock)

  def test_formal_replay_cli_requires_explicit_confirmation_flag(self):
    import importlib.util
    script = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    spec = importlib.util.spec_from_file_location("stage8_cli_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with self.assertRaises(SystemExit):
      module.build_parser().parse_args(["--run-id", "fixture", "formal-replay"])
    args = module.build_parser().parse_args([
        "--run-id", "fixture", "formal-replay", "--confirm-formal-replay"])
    self.assertTrue(args.confirm_formal_replay)

  def test_test_parsers_are_only_called_by_gated_formal_replay(self):
    path = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    with open(path, "r", encoding="utf-8") as handle:
      source = handle.read()
    self.assertEqual(2, source.count("trace = _trace("))
    execute_body = source.split("def formal_replay(args)", 1)[1].split(
        "def _load_completed_results", 1)[0]
    self.assertEqual(2, execute_body.count("trace = _trace("))
    self.assertLess(execute_body.index("_audit_preexecute_evidence("),
                     execute_body.index("trace = _trace("))

  def test_validation_script_stops_before_formal_replay(self):
    path = os.path.join(ROOT, "scripts", "validate_capd_proactive_stage8_server.sh")
    with open(path, "r", encoding="utf-8") as handle:
      source = handle.read()
    self.assertIn("awaiting_formal_replay_confirmation", source)
    self.assertIn("record-tests", source)
    self.assertNotIn(" formal-replay", source)
    self.assertNotIn(" aggregate", source)
    self.assertNotIn(" verify", source)

  def test_stage8_production_files_have_no_obsolete_matrix_hardcodes(self):
    paths = (
        "qmap/proactive_stage8_contract.py", "qmap/proactive_stage8_replay.py",
        "qmap/proactive_stage8_results.py", "scripts/run_capd_proactive_stage8.py",
        "configs/finals/capd_proactive_stage8.json",
        "configs/finals/capd_proactive_stage8_result_schema.json")
    forbidden = (
        "working_set_pages", "capacity_ratio", "0.20", "0.40", "0.60",
        "formal_144_job_execute", "18-cell", "18_cell")
    for relative in paths:
      with open(os.path.join(ROOT, relative), "r", encoding="utf-8") as handle:
        text = handle.read()
      for token in forbidden:
        self.assertNotIn(token, text, "{} still contains {}".format(relative, token))


class Stage8MetricTest(unittest.TestCase):

  def test_five_non_capd_policies_share_replay_and_are_exact(self):
    stage0 = finals_config.load_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage0.json"))
    cost = proactive_cost.load_cost_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage2_cost_profiles.json"))
    trace = [{"page": index % 37, "rw": int(index % 5 == 0),
              "pc": index % 11} for index in range(100)]
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    for policy in contract.DETERMINISTIC_POLICIES:
      job = copy.deepcopy(next(
          row for row in authority["jobs"] if row["track"] == "standard" and
          row["workload"] == "canneal" and row["policy"] == policy))
      job["job_id"] = "fixture-" + policy
      job["evaluation_interval"] = {
          "start_inclusive": 0, "end_exclusive": len(trace)}
      lock = {"policy_replay_allowed_stage": 8,
              "fairness_identity": job["test_identity"]}
      one = replay.run_formal_test_replay(
          stage0, cost, trace, job, lock, measure_latency=False,
          invariant_mode="full")
      two = replay.run_formal_test_replay(
          stage0, cost, trace, job, lock, measure_latency=False,
          invariant_mode="full")
      self.assertEqual(one["semantic_result_sha256"],
                       two["semantic_result_sha256"])

  def test_pressure_result_records_and_audits_full_provenance(self):
    stage0 = finals_config.load_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage0.json"))
    cost = proactive_cost.load_cost_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage2_cost_profiles.json"))
    authority = contract.audit_authority(
        _config(), ROOT, hash_test_payloads=False,
        require_source_files=False, require_checkpoints=False)
    job = copy.deepcopy(next(
        row for row in authority["jobs"] if row["track"] == "pressure" and
        row["workload"] == "canneal" and row["policy"] == "reactive_lru"))
    trace = [{"page": index % 17, "rw": index % 2, "pc": index % 7}
             for index in range(100)]
    job["evaluation_interval"] = {"start_inclusive": 0, "end_exclusive": 100}
    lock = {"pressure_eligible": True,
            "candidate_content_sha256": job["test_identity"]}
    value = replay.run_formal_test_replay(
        stage0, cost, trace, job, lock, measure_latency=False,
        invariant_mode="full")
    for field in (
        "derived_csv_sha256", "source_standard_test_sha256",
        "source_raw_interval", "evaluation_interval", "pressure_lock_sha256",
        "pressure_bundle_manifest_sha256", "addendum_sha256",
        "parent_r4_contract_sha256"):
      self.assertEqual(job[field], value[field])
    value["addendum_sha256"] = "0" * 64
    value["semantic_result_sha256"] = contract.fingerprint_value(
        contract.semantic_payload(value))
    with self.assertRaises(contract.Stage8ContractError):
      contract.audit_job_result(value, job)

  def test_early_reuse_boundaries_64_256_1024(self):
    trace = [{"page": 9, "rw": 0, "pc": 0} for _ in range(1100)]
    for index in range(1100):
      trace[index]["page"] = index + 100
    trace[64]["page"] = 1
    trace[256]["page"] = 2
    trace[1024]["page"] = 3
    events = [
        {"event_id": 1, "event_type": "proactive_demotion", "access_index": 0, "page": 1},
        {"event_id": 2, "event_type": "proactive_demotion", "access_index": 0, "page": 2},
        {"event_id": 3, "event_type": "proactive_demotion", "access_index": 0, "page": 3}]
    value = replay.early_reuse_metrics(trace, events)
    self.assertEqual(1, value["windows"]["64"]["early_reuse_count"])
    self.assertEqual(2, value["windows"]["256"]["early_reuse_count"])
    self.assertEqual(3, value["windows"]["1024"]["early_reuse_count"])

  def test_early_reuse_zero_denominator_is_predeclared_zero(self):
    value = replay.early_reuse_metrics([], [])
    self.assertEqual(0.0, value["windows"]["64"]["rate"])
    self.assertEqual(0.0, value["wasted_demotion_rate"])

  def test_future_count_and_wasted_demotion(self):
    trace = [{"page": 1, "rw": 0, "pc": 0},
             {"page": 2, "rw": 0, "pc": 0},
             {"page": 1, "rw": 0, "pc": 0}]
    events = [
        {"event_id": 1, "event_type": "proactive_demotion", "access_index": 0, "page": 1},
        {"event_id": 2, "event_type": "proactive_demotion", "access_index": 1, "page": 2}]
    value = replay.early_reuse_metrics(trace, events)
    self.assertEqual(1, value["wasted_demotion_count"])
    self.assertEqual(1, value["per_demotion_audit"][0]["future_access_count"])

  def test_oov_counts_access_and_unique_without_expansion(self):
    class Vocab(object):
      frozen = True
      def __init__(self, values): self.input_to_index = values
    class Embed(object): pass
    class Predictor(object): pass
    class Ranker(object): pass
    embed = Embed()
    embed.page_embedder = Vocab({1: 1})
    embed.pc_embedder = Vocab({10: 1})
    predictor = Predictor()
    predictor._feature_embedder = embed
    ranker = Ranker()
    ranker.predictor = predictor
    value = replay._oov_diagnostics(ranker, [
        {"page": 1, "pc": 10}, {"page": 2, "pc": 11},
        {"page": 2, "pc": 11}])
    self.assertEqual(2, value["page_access_oov_count"])
    self.assertEqual(1, value["page_unique_oov_count"])
    self.assertFalse(value["vocabulary_expansion_allowed"])
    self.assertEqual(0, value["unk_index"])

  def test_semantic_hash_excludes_latency(self):
    one = {"metrics": {"total_decision_time": 1.0},
           "rounds": [{"feature_latency": 1.0, "page": 1}],
           "cycles": [{"total_feature_time": 1.0}],
           "runtime": {"x": 1}}
    two = copy.deepcopy(one)
    two["metrics"]["total_decision_time"] = 99.0
    two["rounds"][0]["feature_latency"] = 99.0
    two["cycles"][0]["total_feature_time"] = 99.0
    two["runtime"]["x"] = 99
    self.assertEqual(contract.fingerprint_value(contract.semantic_payload(one)),
                     contract.fingerprint_value(contract.semantic_payload(two)))

  def test_semantic_hash_excludes_resolved_absolute_checkpoint_path(self):
    one = {"checkpoint": {"recorded_path": "outputs/checkpoint.pth",
                           "resolved_path": "/server-a/checkpoint.pth",
                           "sha256": "a" * 64},
           "metrics": {}, "rounds": [], "cycles": []}
    two = copy.deepcopy(one)
    two["checkpoint"]["resolved_path"] = "/server-b/checkpoint.pth"
    self.assertEqual(contract.fingerprint_value(contract.semantic_payload(one)),
                     contract.fingerprint_value(contract.semantic_payload(two)))


class Stage8AggregationTest(unittest.TestCase):

  def test_bootstrap_is_fixed_seed_reproducible(self):
    one = results.bootstrap_ci([1, 2, 3, 4], 123, 500)
    two = results.bootstrap_ci([1, 2, 3, 4], 123, 500)
    self.assertEqual(one, two)
    self.assertEqual(4, one["cell_count"])

  def test_aggregation_membership_seed_std_and_groups(self):
    value = results.aggregate(_fixture_results(), _config())
    self.assertEqual(50, len(value["table_A"]))
    self.assertEqual(20, len(value["table_B"]))
    self.assertEqual(10, len(value["capd_vs_tpp_paired"]))
    capd = next(row for row in value["table_A"] if row["policy"] == "capd")
    self.assertEqual(3, capd["seed_count"])
    self.assertGreater(capd["metrics"]["weighted_cost_sample_std"], 0.0)
    self.assertEqual(10, value["cell_count"])
    self.assertEqual(48, value["track_macros"]["standard"]["job_count"])
    self.assertEqual(32, value["track_macros"]["pressure"]["job_count"])
    self.assertEqual({"standard", "pressure"}, set(value["bootstrap_95ci"]))

  def test_fairness_detects_one_field_pollution(self):
    rows = _fixture_results()
    rows[1]["trace_sha256"] = "f" * 64
    with self.assertRaises(contract.Stage8ContractError):
      results.fairness_audit(rows)

  def test_atomic_write_round_trip(self):
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "value.json")
      contract.write_json_atomic(path, {"a": 1})
      self.assertEqual({"a": 1}, contract.load_json(path))
      self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(directory)))


if __name__ == "__main__":
  unittest.main()
