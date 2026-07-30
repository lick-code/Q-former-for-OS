# coding=utf-8

import copy
import os
import unittest

from qmap import proactive_cost
from qmap import proactive_stage4
from qmap import proactive_stage5_contract as contract
from qmap import proactive_stage5_replay


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def synthetic_trace():
  trace = [
      {"page": page, "rw": int(page % 5 == 0), "pc": page % 3}
      for page in range(1, 34)]
  trace.extend([
      {"page": 2, "rw": 0, "pc": 1},
      {"page": 5, "rw": 1, "pc": 1},
      {"page": 34, "rw": 0, "pc": 2},
      {"page": 35, "rw": 1, "pc": 2},
  ])
  return trace


class ProactiveStage5ReplayTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.stage0 = proactive_stage4.load_json(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"))
    cls.stage5 = contract.load_config(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage5.json"))
    cls.cost = proactive_cost.load_cost_config(os.path.join(
        PROJECT_ROOT,
        "configs/finals/capd_proactive_stage2_cost_profiles.json"))
    cls.trace = synthetic_trace()
    cls.trace_sha = proactive_stage4.fingerprint_value(cls.trace)

  def run_policy(self, policy):
    return proactive_stage5_replay.run_replay(
        self.stage0, self.stage5, self.cost, self.trace, policy,
        workload="synthetic", split="validation",
        split_role="parameter_selection",
        source_interval={"start": 100, "end": 100 + len(self.trace)},
        trace_sha256=self.trace_sha,
        dram_capacity_pages=20,
        working_set_pages=len({row["page"] for row in self.trace}),
        measure_latency=False)

  def test_reactive_lru_has_no_proactive_state_or_event_type(self):
    result = self.run_policy("reactive_lru")
    summary = result["summary"]
    self.assertEqual(0, summary["number_of_proactive_cycles"])
    self.assertEqual(0, summary["number_of_proactive_rounds"])
    self.assertEqual(0, summary["proactive_demotions"])
    self.assertEqual(0, summary["emergency_demotions"])
    self.assertGreater(summary["reactive_demotions"], 0)
    self.assertFalse(result["rounds"])
    self.assertTrue(all(
        event["event_type"] == "reactive_demotion"
        for event in result["events"]))
    self.assertTrue(all(
        event["F_before"] == 0 and event["F_after"] == 1
        for event in result["events"]))

  def test_proactive_lru_triggers_multiple_rounds_and_rebuilds_candidates(self):
    result = self.run_policy("proactive_lru")
    self.assertGreater(result["summary"]["number_of_proactive_cycles"], 0)
    self.assertGreater(result["summary"]["number_of_proactive_rounds"],
                       result["summary"]["number_of_proactive_cycles"])
    first_cycle = result["cycles"][0]
    rounds = [
        row for row in result["rounds"]
        if row["cycle_id"] == first_cycle["cycle_id"]]
    self.assertGreaterEqual(len(rounds), 2)
    self.assertEqual(len(rounds), len({
        row["candidate_pages_sha256"] for row in rounds}))
    self.assertEqual(16, first_cycle["target_F"])
    self.assertEqual("target_reached", rounds[-1]["termination_reason"])

  def test_current_entering_page_is_not_an_initialization_candidate(self):
    result = self.run_policy("proactive_lru")
    for row in result["rounds"]:
      access = result["accesses"][row["access_index"]]
      if access["page_entered_dram"]:
        self.assertNotIn(access["page"], row["candidate_pages"])

  def test_clock_is_candidate_scoped_clears_bits_and_persists_pointer(self):
    result = self.run_policy("proactive_clock")
    audits = result["policy_state"]["clock"]["round_audits"]
    self.assertTrue(audits)
    self.assertTrue(all(row["candidate_scope_preserved"] for row in audits))
    self.assertTrue(any(
        item["action"] == "clear_and_skip"
        for row in audits for item in row.get("scan_trace", [])))
    self.assertTrue(any(row["pointer_after"] != row["pointer_before"]
                        for row in audits))
    for replay_round, audit in zip(result["rounds"], audits):
      self.assertEqual(replay_round["candidate_pages"],
                       audit["candidate_pages"])
      self.assertTrue(set(audit["scanned_pages"]).issubset(
          set(replay_round["candidate_pages"])))
      self.assertEqual(len(audit["selected_pages"]),
                       len(set(audit["selected_pages"])))
    resident = set(result["final_state"]["dram_resident"])
    self.assertEqual(
        resident,
        set(int(page) for page in
            result["policy_state"]["clock"]["reference_bits"]))

  def test_oracle_is_deterministic_candidate_scoped_and_records_tail(self):
    first = self.run_policy("oracle")
    second = self.run_policy("oracle")
    self.assertEqual(first["semantic_result_sha256"],
                     second["semantic_result_sha256"])
    self.assertEqual("candidate_scoped_oracle_only",
                     first["future_information"])
    for row in first["rounds"]:
      self.assertTrue(set(row["selected_pages"]).issubset(
          set(row["candidate_pages"])))
      for score in row["policy_scores"]:
        self.assertIn("complete_future_window",
                      score["label_components"])
        self.assertIn("effective_lookahead", score["label_components"])

  def test_rule_policy_replay_is_exactly_deterministic_without_timing(self):
    for policy in ("reactive_lru", "proactive_lru", "proactive_clock"):
      with self.subTest(policy=policy):
        first = self.run_policy(policy)
        second = self.run_policy(policy)
        self.assertEqual(first["semantic_result_sha256"],
                         second["semantic_result_sha256"])

  def test_event_accounting_and_frozen_cost_match_manual_recompute(self):
    result = self.run_policy("proactive_lru")
    summary = result["summary"]
    manual = (
        summary["dram_hits"] +
        2 * summary["nvm_reads"] +
        8 * summary["nvm_writes"] +
        10 * summary["total_demotions"])
    self.assertEqual(manual, summary["weighted_cost"])
    self.assertEqual(
        summary["total_demotions"],
        summary["proactive_demotions"] +
        summary["reactive_demotions"] +
        summary["emergency_demotions"])
    self.assertEqual(len(self.trace), summary["total_accesses"])

  def test_test_input_is_hard_rejected(self):
    with self.assertRaises(contract.Stage5ContractError):
      proactive_stage5_replay.run_replay(
          self.stage0, self.stage5, self.cost, self.trace, "proactive_lru",
          workload="synthetic", split="test",
          split_role="final_evaluation_only",
          source_interval={"start": 0, "end": len(self.trace)},
          trace_sha256=self.trace_sha, dram_capacity_pages=20,
          working_set_pages=35, measure_latency=False)

  def test_fairness_a_and_b_and_single_field_pollution(self):
    lru = self.run_policy("proactive_lru")
    clock = self.run_policy("proactive_clock")
    oracle = self.run_policy("oracle")
    reactive = self.run_policy("reactive_lru")
    capd_rows = []
    for seed in contract.CAPD_SEEDS:
      row = copy.deepcopy(oracle)
      row.update({
          "policy": "capd",
          "policy_display_name": "CAPD",
          "seed": seed,
          "checkpoint": {
              "seed": seed,
              "path": "frozen-checkpoint",
              "sha256": "{:064x}".format(seed),
              "selection_criterion": "minimum_valid_loss_only",
          },
          "future_information": "not_accessed",
      })
      row["policy_state"]["oracle"] = None
      row["policy_state"]["capd"] = {
          "future_information_accessed": False,
          "score_inputs": ["current_and_past_only"],
      }
      capd_rows.append(row)
    self.assertEqual(
        "passed",
        contract.check_experiment_a(
            [lru, clock, oracle] + capd_rows)["status"])
    self.assertEqual(
        "passed",
        contract.check_experiment_b([reactive, lru])["status"])
    polluted = copy.deepcopy(clock)
    polluted["cost_profile"]["weights"]["demotion"] = 11
    with self.assertRaises(contract.Stage5ContractError):
      contract.check_experiment_a([lru, polluted, oracle] + capd_rows)
    candidate_polluted = copy.deepcopy(clock)
    source_round = lru["rounds"][0]
    target_round = candidate_polluted["rounds"][0]
    target_round["candidate_state_sha256"] = (
        source_round["candidate_state_sha256"])
    target_round["candidate_pages"] = list(
        reversed(source_round["candidate_pages"]))
    target_round["candidate_pages_sha256"] = (
        proactive_stage4.fingerprint_value(target_round["candidate_pages"]))
    target_round["candidate_features"] = [
        dict(item, page=page, lru_tail_rank=index)
        for index, (item, page) in enumerate(zip(
            reversed(source_round["candidate_features"]),
            target_round["candidate_pages"]))]
    target_round["policy_scores"] = [{
        "page": page, "score": float(len(target_round["candidate_pages"]) - i)}
        for i, page in enumerate(target_round["candidate_pages"])]
    target_round["selected_pages"] = target_round["candidate_pages"][
        :target_round["b_t"]]
    with self.assertRaises(contract.Stage5ContractError):
      contract.check_experiment_a(
          [lru, candidate_polluted, oracle] + capd_rows)


if __name__ == "__main__":
  unittest.main()
