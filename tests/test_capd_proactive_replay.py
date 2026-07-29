# coding=utf-8
"""Stage-1 correctness tests for deterministic proactive Replay."""

import copy
import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_replay


STAGE0_CONFIG = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage0.json")
STAGE1_FIXTURE = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage1_fixture.json")


class InvalidRanking(proactive_replay.CandidateRankingPolicy):

  policy_name = "invalid_fixture_ranker"

  def rank_candidates(self, state, candidates, candidate_features,
                      policy_context):
    del state, candidate_features, policy_context
    return [{"page": 999, "score": 1.0} for _ in candidates]


class ProactiveReplayStage1Test(unittest.TestCase):

  def setUp(self):
    self.stage0 = finals_config.load_config(STAGE0_CONFIG)

  def _active_parameters(
      self, capacity=6, low=3, target=5, b_max=2, K=4,
      non_demotable_pages=None):
    return proactive_replay.ReplayParameters(
        policy_name="proactive_lru",
        dram_capacity_pages=capacity,
        F_low=low,
        F_target=target,
        b_max=b_max,
        candidate_size_K=K,
        history_window_size=4,
        early_reuse_window=4,
        non_demotable_pages=non_demotable_pages,
    )

  def _reactive_parameters(self, capacity=3):
    return proactive_replay.ReplayParameters(
        policy_name="reactive_lru",
        dram_capacity_pages=capacity,
        history_window_size=4,
        early_reuse_window=4,
    )

  @staticmethod
  def _trace(*pages):
    return [
        {"page": page, "rw": index % 2}
        for index, page in enumerate(pages)
    ]

  def test_stage0_contract_and_fixture_remain_separate(self):
    fixture = finals_config.load_json(STAGE1_FIXTURE)
    proactive_replay.validate_stage1_fixture(fixture, self.stage0)
    self.assertEqual(
        "frozen", self.stage0["freeze_status"]["stage1_replay"])
    self.assertIsNone(self.stage0["active_demotion"]["F_low"])
    self.assertEqual("disabled", self.stage0["method"]["selector"])
    self.assertEqual(
        (
            "reactive_lru",
            "proactive_lru",
            "proactive_clock",
            "tpp_inspired",
            "capd",
            "oracle",
        ),
        finals_config.PROACTIVE_OFFICIAL_POLICIES)

  def test_F_at_or_above_low_does_not_trigger(self):
    parameters = self._active_parameters(
        capacity=5, low=2, target=4, b_max=1, K=2)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3))
    self.assertEqual(2, result["state"]["F_t"])
    self.assertEqual([], result["cycles"])
    self.assertEqual(0, result["summary"]["proactive_demotions"])

  def test_low_watermark_starts_cycle_and_reaches_target(self):
    parameters = self._active_parameters(
        capacity=5, low=2, target=4, b_max=1, K=3)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3, 4))
    self.assertEqual(4, result["state"]["F_t"])
    self.assertEqual(1, len(result["cycles"]))
    self.assertEqual("target_reached", result["cycles"][0][
        "termination_reason"])

  def test_single_round_top_b_uses_stub_ranking(self):
    parameters = self._active_parameters(
        capacity=6, low=3, target=4, b_max=2, K=4)
    ranker = proactive_replay.DeterministicStubRanking({
        1: 1.0, 2: 8.0, 3: 4.0, 4: 10.0})
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters, ranker).run(self._trace(1, 2, 3, 4))
    self.assertEqual(1, len(result["rounds"]))
    self.assertEqual([4, 2], result["rounds"][0]["selected_pages"])
    self.assertEqual(2, result["rounds"][0]["b_t"])
    self.assertEqual(4, result["state"]["F_t"])

  def test_multi_round_rebuilds_current_candidates(self):
    parameters = self._active_parameters(
        capacity=6, low=3, target=5, b_max=2, K=4)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3, 4))
    self.assertEqual(2, len(result["rounds"]))
    first = result["rounds"][0]
    second = result["rounds"][1]
    self.assertEqual([1, 2], first["selected_pages"])
    self.assertTrue(
        set(first["selected_pages"]).isdisjoint(
            set(second["candidate_pages"])))
    self.assertEqual("continue_rebuild_candidates", first[
        "termination_reason"])
    self.assertEqual("target_reached", second["termination_reason"])
    self.assertEqual(5, result["state"]["F_t"])

  def test_actual_candidate_count_and_all_b_t_bounds(self):
    parameters = self._active_parameters(
        capacity=4, low=2, target=3, b_max=2, K=5)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3))
    round_log = result["rounds"][0]
    self.assertEqual(3, len(round_log["candidate_pages"]))
    self.assertLess(len(round_log["candidate_pages"]), parameters.candidate_size_K)
    self.assertLessEqual(round_log["b_t"], parameters.b_max)
    self.assertLessEqual(
        round_log["b_t"], len(round_log["candidate_pages"]))
    self.assertLessEqual(
        round_log["b_t"],
        parameters.F_target - round_log["F_before"])

  def test_residency_lru_frequency_dirty_and_history_updates(self):
    replay = proactive_replay.ProactiveReplay(
        self.stage0, self._reactive_parameters(capacity=3))
    result = replay.run([
        {"page": 1, "rw": 1},
        {"page": 2, "rw": 0},
        {"page": 1, "rw": 0},
    ])
    state = result["state"]
    self.assertEqual([1, 2], state["dram_lru_mru_to_lru"])
    self.assertEqual(2, state["frequency_state"]["1"])
    self.assertTrue(state["dirty_state"]["1"])
    self.assertEqual("dram", state["residency_state"]["1"])
    self.assertEqual([1, 2, 1], [
        access["page"] for access in state["history_window"]])
    replay.assert_invariants()

  def test_reactive_lru_never_creates_proactive_logs(self):
    result = proactive_replay.ProactiveReplay(
        self.stage0, self._reactive_parameters()).run(
            self._trace(1, 2, 3, 4, 5))
    self.assertEqual([], result["rounds"])
    self.assertEqual([], result["cycles"])
    self.assertEqual(2, result["summary"]["reactive_demotions"])
    self.assertEqual(0, result["summary"]["proactive_demotions"])
    self.assertEqual(0, result["summary"]["emergency_demotions"])

  def test_proactive_reactive_and_emergency_events_do_not_mix(self):
    proactive = proactive_replay.ProactiveReplay(
        self.stage0, self._active_parameters()).run(
            self._trace(1, 2, 3, 4))
    reactive = proactive_replay.ProactiveReplay(
        self.stage0, self._reactive_parameters()).run(
            self._trace(1, 2, 3, 4))
    emergency_parameters = self._active_parameters(
        capacity=3, low=1, target=2, b_max=1, K=2)
    emergency = proactive_replay.ProactiveReplay(
        self.stage0, emergency_parameters).run(
            self._trace(20, 21, 22, 23))

    self.assertEqual(
        {proactive_replay.PROACTIVE_DEMOTION},
        {event["event_type"] for event in proactive["events"]})
    self.assertEqual(
        {proactive_replay.REACTIVE_DEMOTION},
        {event["event_type"] for event in reactive["events"]})
    emergency_types = {
        event["event_type"] for event in emergency["events"]}
    self.assertIn(proactive_replay.EMERGENCY_DEMOTION, emergency_types)
    self.assertIn(proactive_replay.PROACTIVE_DEMOTION, emergency_types)
    self.assertNotIn(proactive_replay.REACTIVE_DEMOTION, emergency_types)
    self.assertTrue(emergency["cycles"][0][
        "emergency_fallback_occurred"])

  def test_no_free_frame_demotes_before_page_enter_and_never_negative(self):
    parameters = self._active_parameters(
        capacity=3, low=1, target=2, b_max=1, K=2)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3, 4))
    access = result["accesses"][-1]
    emergency = [
        event for event in result["events"]
        if event["event_type"] == proactive_replay.EMERGENCY_DEMOTION][0]
    self.assertEqual(0, emergency["F_before"])
    self.assertEqual(1, emergency["F_after"])
    self.assertTrue(access["page_entered_dram"])
    self.assertTrue(all(
        event["F_before"] >= 0 and event["F_after"] >= 0
        for event in result["events"]))
    self.assertGreaterEqual(result["state"]["F_t"], 0)

  def test_empty_candidate_set_terminates_without_loop(self):
    parameters = self._active_parameters(
        capacity=4, low=2, target=3, b_max=1, K=3,
        non_demotable_pages=(1, 2, 3))
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3))
    self.assertEqual(1, len(result["rounds"]))
    self.assertEqual(
        "candidate_set_empty", result["rounds"][0]["termination_reason"])
    self.assertEqual(
        "candidate_set_empty", result["cycles"][0]["termination_reason"])
    self.assertEqual(0, result["summary"]["proactive_demotions"])

  def test_round_cycle_and_summary_fields_are_complete(self):
    result = proactive_replay.ProactiveReplay(
        self.stage0, self._active_parameters()).run(
            self._trace(1, 2, 3, 4))
    self.assertFalse(
        set(proactive_replay.ROUND_REQUIRED_FIELDS) -
        set(result["rounds"][0]))
    self.assertFalse(
        set(proactive_replay.CYCLE_REQUIRED_FIELDS) -
        set(result["cycles"][0]))
    self.assertFalse(
        set(proactive_replay.SUMMARY_REQUIRED_FIELDS) -
        set(result["summary"]))
    self.assertIsNone(result["rounds"][0]["feature_latency"])
    self.assertIsNone(result["rounds"][0]["inference_latency"])
    self.assertIsNone(result["rounds"][0]["selection_latency"])

  def test_summary_matches_raw_events(self):
    replay = proactive_replay.ProactiveReplay(
        self.stage0, self._active_parameters())
    result = replay.run(self._trace(1, 2, 3, 4, 1))
    self.assertTrue(replay.validate_log_accounting())
    summary = result["summary"]
    self.assertEqual(len(result["events"]), summary["total_demotions"])
    self.assertEqual(
        len(result["rounds"]), summary["number_of_proactive_rounds"])
    self.assertEqual(
        summary["total_accesses"],
        summary["dram_hits"] + summary["nvm_reads"] +
        summary["nvm_writes"])

  def test_same_trace_and_config_are_fully_deterministic(self):
    trace = self._trace(1, 2, 3, 4, 1, 5)
    parameters = self._active_parameters()
    first = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(trace)
    second = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(copy.deepcopy(trace))
    self.assertEqual(first, second)

  def test_stage1_does_not_compute_cost_or_require_checkpoint(self):
    result = proactive_replay.ProactiveReplay(
        self.stage0, self._active_parameters()).run(
            self._trace(1, 2, 3, 4))
    summary = result["summary"]
    self.assertIsNone(summary["weighted_cost"])
    self.assertEqual("pending_stage2", summary["weighted_cost_status"])
    self.assertEqual("not_required_stage1", summary["checkpoint_status"])
    self.assertEqual("disabled", summary["selector_status"])

  def test_capd_without_checkpoint_is_not_faked_by_lru_ranker(self):
    parameters = proactive_replay.ReplayParameters(
        policy_name="capd",
        dram_capacity_pages=6,
        F_low=3,
        F_target=5,
        b_max=2,
        candidate_size_K=4,
        history_window_size=4,
        early_reuse_window=4,
    )
    with self.assertRaises(proactive_replay.ReplayConfigurationError):
      proactive_replay.ProactiveReplay(self.stage0, parameters)

  def test_early_reuse_is_counted_from_proactive_event(self):
    parameters = self._active_parameters(
        capacity=6, low=3, target=4, b_max=2, K=4)
    result = proactive_replay.ProactiveReplay(
        self.stage0, parameters).run(self._trace(1, 2, 3, 4, 1))
    self.assertEqual(1, result["summary"]["early_reuse_count"])

  def test_invalid_ranker_fails_instead_of_silently_repairing(self):
    replay = proactive_replay.ProactiveReplay(
        self.stage0, self._active_parameters(), InvalidRanking())
    with self.assertRaises(proactive_replay.ReplayInvariantError):
      replay.run(self._trace(1, 2, 3, 4))

  def test_all_declared_fixture_scenarios_run(self):
    fixture = finals_config.load_json(STAGE1_FIXTURE)
    results = proactive_replay.run_fixture_scenarios(
        self.stage0, fixture)
    self.assertEqual(
        {scenario["name"] for scenario in fixture["scenarios"]},
        set(results))
    for result in results.values():
      self.assertEqual(
          proactive_replay.STAGE1_RESULT_SCHEMA_VERSION,
          result["schema_version"])


if __name__ == "__main__":
  unittest.main()
