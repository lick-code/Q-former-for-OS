# coding=utf-8

import copy
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

from qmap import proactive_cost
from qmap import proactive_stage4
from qmap import proactive_stage6_contract as contract
from qmap import proactive_stage6_replay


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "capd_proactive_stage6_runner",
    os.path.join(PROJECT_ROOT, "scripts/run_capd_proactive_stage6.py"))
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER)


def epoch_trace():
  trace = [
      {"page": page, "rw": int(page % 5 == 0), "pc": page % 7}
      for page in range(1, 14)]
  # Age the remaining resident pages through two complete empty epochs.
  trace.extend({"page": 13, "rw": 0, "pc": 1} for _ in range(130))
  trace.extend(
      {"page": page, "rw": int(page % 4 == 0), "pc": page % 7}
      for page in range(14, 28))
  return trace


class ProactiveStage6E2ETest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.config = contract.load_config(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage6_tpp.json"))
    cls.stage0 = proactive_stage4.load_json(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"))
    cls.cost = proactive_cost.load_cost_config(os.path.join(
        PROJECT_ROOT,
        "configs/finals/capd_proactive_stage2_cost_profiles.json"))
    cls.trace = epoch_trace()
    cls.trace_sha = proactive_stage4.fingerprint_value(cls.trace)

  def run_tpp(self, epoch_length=64, cold_threshold=2,
              dirty_tie_break=True):
    return proactive_stage6_replay.run_replay(
        self.stage0, self.config, self.cost, self.trace,
        workload="synthetic_stage6", split="validation",
        split_role="parameter_selection",
        source_interval={"start": 1000, "end": 1000 + len(self.trace)},
        trace_sha256=self.trace_sha,
        dram_capacity_pages=20,
        working_set_pages=len({row["page"] for row in self.trace}),
        epoch_length=epoch_length,
        cold_threshold=cold_threshold,
        dirty_tie_break=dirty_tie_break,
        measure_latency=False,
        retain_access_logs=True)

  def test_synthetic_e2e_epoch_cold_selection_and_multi_round_cycle(self):
    result = self.run_tpp()
    contract.audit_result(result)
    self.assertGreaterEqual(
        result["summary"]["tpp"]["epoch_transition_count"], 2)
    self.assertGreater(
        result["summary"]["tpp"]["selected_temperature_distribution"][
            "counts"]["Cold"], 0)
    self.assertTrue(any(
        cycle["number_of_rounds"] > 1 for cycle in result["cycles"]))
    self.assertTrue(all(
        set(row["selected_pages"]).issubset(set(row["candidate_pages"]))
        for row in result["rounds"]))
    self.assertTrue(all(
        len(row["selected_pages"]) == len(set(row["selected_pages"]))
        for row in result["rounds"]))
    self.assertTrue(all(
        event["event_type"] == "proactive_demotion"
        for event in result["events"]))
    self.assertFalse(result["tpp_fallback_used"])
    self.assertFalse(result["promotion_performed"])
    self.assertEqual("not_accessed", result["future_information"])

  def test_deterministic_semantic_replay_and_stage2_cost(self):
    first = self.run_tpp()
    second = self.run_tpp()
    self.assertEqual(first["semantic_result_sha256"],
                     second["semantic_result_sha256"])
    summary = first["summary"]
    manual = (
        summary["dram_hits"] +
        2 * summary["nvm_reads"] +
        8 * summary["nvm_writes"] +
        10 * summary["total_demotions"])
    self.assertEqual(manual, summary["weighted_cost"])
    self.assertEqual(len(self.trace), summary["total_accesses"])

  def test_global_selection_is_single_deterministic_and_not_per_workload(self):
    template = self.run_tpp()
    records = []
    for grid_index, grid_row in enumerate(contract.parameter_grid()):
      for workload_index, workload in enumerate(("alpha", "beta")):
        row = copy.deepcopy(template)
        row["workload"] = workload
        row["tpp_parameters"].update(grid_row)
        row["summary"]["weighted_cost"] = (
            row["summary"]["total_accesses"] * 2)
        # Keep all anomaly diagnostics equal so the predeclared complexity
        # order resolves configurations inside the 1% near-best set.
        row["summary"]["early_reuse_count"] = 0
        row["summary"]["emergency_demotions"] = 0
        row["summary"]["free_frame_exhaustion_count"] = 0
        row["summary"]["tpp"].update({
            "cold_selected_count": 1,
            "cold_short_reuse_count": 0,
            "epoch_transition_count": 0,
        })
        row["semantic_result_sha256"] = proactive_stage4.fingerprint_value({
            "workload": workload,
            "experiment_id": grid_row["experiment_id"],
        })
        records.append(row)
    first = contract.select_global_configuration(records, self.config)
    second = contract.select_global_configuration(records, self.config)
    self.assertEqual(first, second)
    self.assertEqual(12, first["configuration_count"])
    self.assertTrue(first["global_configuration_only"])
    self.assertEqual(["alpha", "beta"], first["workloads"])
    self.assertEqual("tpp-e1024-c1-doff",
                     first["selected_experiment_id"])
    self.assertFalse(first["test_trace_opened"])
    self.assertIsNone(first["performance_conclusion"])

  def test_stage6_experiment_a_includes_tpp_and_detects_pollution(self):
    jobs = os.path.join(
        PROJECT_ROOT, "outputs/capd_proactive_stage5",
        "stage5-baseline-r4", "jobs")
    workload = "canneal"
    records = []
    for policy in ("proactive_lru", "proactive_clock", "oracle"):
      records.append(proactive_stage4.load_json(os.path.join(
          jobs, "{}__validation__{}__seed-na".format(workload, policy),
          "result.json")))
    for seed in (3136859, 42, 2026):
      records.append(proactive_stage4.load_json(os.path.join(
          jobs, "{}__validation__capd__seed-{}".format(workload, seed),
          "result.json")))
    tpp = copy.deepcopy(records[0])
    tpp.update({
        "schema_version": contract.RESULT_SCHEMA_VERSION,
        "contract_id": contract.CONTRACT_ID,
        "stage_status": contract.IMPLEMENTED,
        "policy": "tpp_inspired",
        "policy_display_name": "TPP-inspired",
        "seed": None,
        "checkpoint": None,
        "future_information": "not_accessed",
        "promotion_performed": False,
        "tpp_fallback_used": False,
        "invariant_mode": "full",
        "final_full_invariant_check": True,
        "tpp_parameters": {
            "experiment_id": "tpp-e0064-c2-don",
            "epoch_length": 64,
            "cold_threshold": 2,
            "dirty_tie_break": True,
        },
        "policy_state": {"tpp_inspired": {}},
    })
    tpp["summary"]["tpp"] = {
        "cold_selected_count": 0,
        "cold_short_reuse_count": 0,
        "epoch_transition_count": 0,
    }
    for decision in tpp["rounds"]:
      decision["policy_scores"] = [{
          "page": page,
          "score": float(len(decision["candidate_pages"]) - index),
          "referenced_current_epoch": 0,
          "referenced_previous_epoch": 0,
          "last_access_epoch": None,
          "age_in_epochs": 1,
          "temperature": "Cold",
          "dirty": False,
          "lru_tail_rank": index,
          "ranking_key": [0, -1, index, int(page)],
      } for index, page in enumerate(decision["candidate_pages"])]
    tpp["semantic_result_sha256"] = proactive_stage4.fingerprint_value({
        "synthetic_tpp_fairness_fixture": True})
    report = contract.check_experiment_a(records + [tpp])
    self.assertEqual("passed", report["status"])
    self.assertIn("tpp_inspired", report["policies"])
    polluted = copy.deepcopy(tpp)
    polluted["cost_profile"]["weights"]["demotion"] = 11
    with self.assertRaises(contract.Stage6ContractError):
      contract.check_experiment_a(records + [polluted])

  def test_runner_receipt_parser_and_exact_completed_job_resume(self):
    parsed = RUNNER._parse_successful_unittest_log(
        "Ran 142 tests in 2.745s\n\nOK\ntrailing fixture output\n")
    self.assertEqual(142, parsed["tests_run"])
    with self.assertRaises(contract.Stage6ContractError):
      RUNNER._parse_successful_unittest_log(
          "Ran 142 tests in 2.745s\n\nFAILED (errors=1)\n")
    with tempfile.TemporaryDirectory() as directory:
      proactive_stage4.write_json_atomic(os.path.join(
          directory, "run_identity.json"), {
              "run_identity_sha256": "a" * 64})
      entry = {
          "workload": "resume_fixture",
          "split": "validation",
          "role": "parameter_selection",
          "source_interval": {"start": 0, "end": len(self.trace)},
          "trace_sha256": self.trace_sha,
      }
      working_set = {
          "dram_capacity_pages": 20,
          "union_working_set_pages": 27,
      }
      parameters = contract.parameter_grid()[0]
      expected_result = {"semantic_result_sha256": "b" * 64}
      with mock.patch.object(
          RUNNER.proactive_stage6_replay, "run_replay",
          return_value=expected_result) as execute:
        first = RUNNER._run_tpp_job(
            directory, self.config, self.stage0, self.cost, self.trace,
            entry, working_set, parameters, "grid",
            measure_latency=False, retain_access_logs=False)
        second = RUNNER._run_tpp_job(
            directory, self.config, self.stage0, self.cost, self.trace,
            entry, working_set, parameters, "grid",
            measure_latency=False, retain_access_logs=False)
      self.assertEqual(first, second)
      self.assertEqual(1, execute.call_count)
      changed = copy.deepcopy(entry)
      changed["trace_sha256"] = "c" * 64
      with self.assertRaises(contract.Stage6ContractError):
        RUNNER._run_tpp_job(
            directory, self.config, self.stage0, self.cost, self.trace,
            changed, working_set, parameters, "grid",
            measure_latency=False, retain_access_logs=False)


if __name__ == "__main__":
  unittest.main()
