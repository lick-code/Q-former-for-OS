# coding=utf-8
"""Stage-8 frozen contracts, statistics, leakage, and failure fixtures."""

from __future__ import annotations

import copy
import json
import os
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
PLAN_PATH = os.path.join(
    ROOT, "outputs", "capd_proactive_stage7", "stage7-server-suite-r1",
    "stage8_execution_plan.json")
LOCK_PATH = os.path.join(
    ROOT, "outputs", "capd_proactive_stage7", "stage7-server-suite-r1",
    "standard_test_lock.json")
CAPACITY_PATH = os.path.join(
    ROOT, "outputs", "capd_proactive_stage7", "stage7-server-suite-r1",
    "capacity_matrix.json")


def _config():
  return contract.load_json(CONFIG_PATH)


def _fixture_results():
  plan = contract.load_json(PLAN_PATH)
  rows = []
  for index, job in enumerate(plan["jobs"]):
    base = 1000.0 + (index % 24)
    if job["policy"] == "capd":
      base += {3136859: 0.0, 42: 2.0, 2026: 4.0}[job["seed"]]
    metrics = {
        "weighted_cost": base,
        "weighted_cost_per_access": base / 600000.0,
        "dram_hits": 10, "nvm_reads": 20, "nvm_writes": 30,
        "total_demotions": 4, "proactive_demotions": 4,
        "emergency_demotions": 0, "fallback_rate": 0.0,
        "minimum_free_frames": 8, "average_free_frames": 12.0,
        "early_reuse": {
            "windows": {str(delta): {"early_reuse_count": 1, "rate": 0.25}
                        for delta in (64, 256, 1024)},
            "wasted_demotion_count": 1}}
    rows.append({
        "job_id": job["job_id"], "workload": job["workload"],
        "workload_role": job["workload_role"],
        "capacity_ratio": job["capacity_ratio"], "policy": job["policy"],
        "seed": job["seed"], "dram_capacity_pages": job["dram_pages"],
        "test_identity": job["test_identity"], "trace_sha256": "a" * 64,
        "trace_range": {"start_inclusive": 0, "end_exclusive": 600000},
        "initial_state_sha256": "b" * 64,
        "cost_profile": {"name": "default", "weights": contract.FROZEN_COST},
        "page_enter_dram_semantics": "occupies_one_free_frame_regardless_of_source",
        "F_low": None if job["policy"] == "reactive_lru" else 8,
        "F_target": None if job["policy"] == "reactive_lru" else 16,
        "candidate_size_K": None if job["policy"] == "reactive_lru" else 8,
        "b_max": None if job["policy"] == "reactive_lru" else 4,
        "b_t_rule": None if job["policy"] == "reactive_lru" else
            "min(b_max,F_target-F_t,|C_t|)",
        "candidate_source": None if job["policy"] == "reactive_lru" else "lru_tail",
        "fallback_policy": None if job["policy"] == "reactive_lru" else "lru",
        "trigger_mode": None if job["policy"] == "reactive_lru" else "low_watermark",
        "candidate_contract_sha256": "c" * 64,
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

  def test_plan_has_exact_stable_144_cartesian_jobs(self):
    plan = contract.load_json(PLAN_PATH)
    lock = contract.load_json(LOCK_PATH)
    capacity = contract.load_json(CAPACITY_PATH)
    expected = list(contract._expected_jobs(plan, lock, capacity))
    self.assertEqual(144, len(expected))
    self.assertEqual(expected, [row["job_id"] for row in plan["jobs"]])
    self.assertEqual(144, len(set(expected)))

  def test_plan_has_five_deterministic_and_three_capd_jobs_per_cell(self):
    plan = contract.load_json(PLAN_PATH)
    cells = {}
    for job in plan["jobs"]:
      cells.setdefault((job["workload"], job["capacity_ratio"]), []).append(job)
    self.assertEqual(18, len(cells))
    for jobs in cells.values():
      deterministic = [job for job in jobs if job["policy"] != "capd"]
      capd = [job for job in jobs if job["policy"] == "capd"]
      self.assertEqual(list(contract.DETERMINISTIC_POLICIES),
                       [job["policy"] for job in deterministic])
      self.assertEqual(list(contract.CAPD_SEEDS), [job["seed"] for job in capd])

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
    self.assertLess(shell.index('CURRENT_STEP="cuda_checkpoint_smoke"'),
                    shell.index('CURRENT_STEP="formal_144_job_execute"'))
    for command in ("record-tests", "aggregate", "verify"):
      command_at = shell.index(command)
      self.assertIn('--device "${DEVICE}"', shell[max(0, command_at - 180):command_at])

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
    authority = {"checkpoint_authority": {
        int(row["seed"]): row for row in frozen["checkpoints"]}}
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
    fake_torch = types.SimpleNamespace(cuda=fake_cuda, __version__="fixture")
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
      loaded = (directory, _config(), {}, None, dict(authority, paths={
          "stage5_config": os.path.join(
              ROOT, "configs", "finals", "capd_proactive_stage5.json")}), {})
      with mock.patch.object(module, "_loaded_run", return_value=loaded), \
           mock.patch.object(module.proactive_stage5_replay, "run_replay",
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
    job = {"policy": "reactive_lru", "formal_test": False, "split": "test",
           "test_identity": "x", "dram_pages": 20}
    lock = {"policy_replay_allowed_stage": 8, "fairness_identity": "x",
            "accesses": 1}
    with self.assertRaises(contract.Stage8ContractError):
      replay.run_formal_test_replay({}, None, [{"page": 1, "rw": 0}],
                                    job, lock, 100)

  def test_standard_test_parser_is_only_called_by_execute(self):
    path = os.path.join(ROOT, "scripts", "run_capd_proactive_stage8.py")
    with open(path, "r", encoding="utf-8") as handle:
      source = handle.read()
    self.assertEqual(1, source.count("trace = _trace("))
    execute_body = source.split("def execute(args)", 1)[1].split(
        "def _load_completed_results", 1)[0]
    self.assertIn("trace = _trace(", execute_body)
    self.assertLess(execute_body.index("_audit_preexecute_evidence("),
                    execute_body.index("trace = _trace("))


class Stage8MetricTest(unittest.TestCase):

  def test_five_non_capd_policies_share_replay_and_are_exact(self):
    stage0 = finals_config.load_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage0.json"))
    cost = proactive_cost.load_cost_config(os.path.join(
        ROOT, "configs", "finals", "capd_proactive_stage2_cost_profiles.json"))
    trace = [{"page": index % 37, "rw": int(index % 5 == 0),
              "pc": index % 11} for index in range(100)]
    lock = {"policy_replay_allowed_stage": 8, "fairness_identity": "fixture",
            "accesses": len(trace), "sha256": "a" * 64,
            "interval": {"start_inclusive": 0,
                         "end_exclusive": len(trace)}}
    for policy in contract.DETERMINISTIC_POLICIES:
      job = {"job_id": "fixture-" + policy, "policy": policy,
             "formal_test": True, "split": "test",
             "test_identity": "fixture", "dram_pages": 20, "seed": None,
             "workload": "fixture", "workload_role": "fixture",
             "capacity_ratio": "0.20", "checkpoint": None}
      one = replay.run_formal_test_replay(
          stage0, cost, trace, job, lock, 100, measure_latency=False,
          invariant_mode="full")
      two = replay.run_formal_test_replay(
          stage0, cost, trace, job, lock, 100, measure_latency=False,
          invariant_mode="full")
      self.assertEqual(one["semantic_result_sha256"],
                       two["semantic_result_sha256"])

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
    self.assertEqual(90, len(value["table_A"]))
    self.assertEqual(36, len(value["table_B"]))
    self.assertEqual(18, len(value["capd_vs_tpp_paired"]))
    capd = next(row for row in value["table_A"] if row["policy"] == "capd")
    self.assertEqual(3, capd["seed_count"])
    self.assertGreater(capd["metrics"]["weighted_cost_sample_std"], 0.0)
    self.assertEqual({"seen_calibration_workloads",
                      "held_out_unseen_workloads", "all_workloads_macro"},
                     set(value["groups"]))

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
