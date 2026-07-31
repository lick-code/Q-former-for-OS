# coding=utf-8

import copy
import os
import unittest

from qmap import proactive_cost
from qmap import proactive_replay
from qmap import proactive_stage4
from qmap import proactive_stage5_contract
from qmap import proactive_stage5_policies
from qmap import proactive_stage6_contract as contract
from qmap import proactive_stage6_replay
from qmap import proactive_stage6_tpp


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class DummyReplayState(object):

  def __init__(self):
    self.access_index = 0
    self.dram_resident = set()
    self.dirty_state = {}
    self.parameters = proactive_replay.ReplayParameters(
        "tpp_inspired", 32, F_low=8, F_target=16, b_max=4,
        candidate_size_K=8, history_window_size=20,
        early_reuse_window=64)

  @property
  def free_frames(self):
    return self.parameters.dram_capacity_pages - len(self.dram_resident)


class ProactiveStage6TPPTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.config = contract.load_config(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage6_tpp.json"))
    cls.stage0 = proactive_stage4.load_json(os.path.join(
        PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"))
    cls.cost = proactive_cost.load_cost_config(os.path.join(
        PROJECT_ROOT,
        "configs/finals/capd_proactive_stage2_cost_profiles.json"))

  def test_stage5_entry_chain_and_pending_contract_remain_valid(self):
    audit = contract.audit_stage5_entry(self.config, PROJECT_ROOT)
    self.assertEqual("stage5_baseline_framework_verified", audit["status"])
    self.assertEqual("satisfied", audit["stage6_entry_gate"])
    self.assertEqual("pending_stage6", audit["tpp_inspired_status"])
    with self.assertRaises(proactive_stage5_contract.PendingStage6Error):
      proactive_stage5_contract.assert_runnable_policy("tpp_inspired")
    pending = proactive_stage5_policies.build_ranker("tpp_inspired")
    with self.assertRaises(proactive_stage5_contract.PendingStage6Error):
      pending.rank_candidates(None, [], [], {})

  def test_stage6_stage0_mapping_is_tpp_specific_and_checkpoint_free(self):
    original = copy.deepcopy(self.stage0)
    mapped = proactive_stage6_replay._stage0_for_tpp(self.stage0)
    self.assertEqual("tpp_inspired", mapped["method"]["name"])
    self.assertEqual("tpp_inspired", mapped["evaluation"]["policy_name"])
    self.assertEqual("frozen",
                     mapped["freeze_status"]["stage4_candidate"])
    self.assertEqual("not_applicable",
                     mapped["freeze_status"]["stage4_training"])
    self.assertEqual(
        {"status": "not_applicable", "path": None, "fingerprint": None},
        mapped["model"]["model_checkpoint"])
    self.assertEqual(original, self.stage0)

  def test_grid_has_exactly_twelve_unique_predeclared_configs(self):
    grid = contract.parameter_grid()
    self.assertEqual(12, len(grid))
    self.assertEqual(12, len({row["experiment_id"] for row in grid}))
    self.assertEqual({64, 256, 1024},
                     {row["epoch_length"] for row in grid})
    self.assertEqual({1, 2},
                     {row["cold_threshold"] for row in grid})
    self.assertEqual({False, True},
                     {row["dirty_tie_break"] for row in grid})

  def test_frozen_stage3_stage4_cost_and_selector_fields_cannot_change(self):
    mutations = []
    changed = copy.deepcopy(self.config)
    changed["frozen_method"]["F_low"] = 9
    mutations.append(changed)
    changed = copy.deepcopy(self.config)
    changed["frozen_method"]["selector"] = "enabled"
    mutations.append(changed)
    changed = copy.deepcopy(self.config)
    changed["frozen_method"]["dram_working_set_ratio"] = 0.25
    mutations.append(changed)
    changed = copy.deepcopy(self.config)
    changed["frozen_stage4"]["history_H"] = 21
    mutations.append(changed)
    changed = copy.deepcopy(self.config)
    changed["cost_profile"]["weights"]["demotion"] = 11
    mutations.append(changed)
    changed = copy.deepcopy(self.config)
    changed["selection_rule"]["near_best_relative_tolerance"] = 0.02
    mutations.append(changed)
    for value in mutations:
      with self.subTest(value=value):
        with self.assertRaises(contract.Stage6ContractError):
          contract.validate_config(value)

  def test_new_page_access_epoch_boundary_and_multi_epoch_jump(self):
    ranker = proactive_stage6_tpp.TPPInspiredRanker(64, 2, True)
    state = DummyReplayState()
    state.dram_resident.add(7)
    state.dirty_state[7] = False
    ranker.on_page_enter_dram(state, 7)
    first_lifecycle = ranker.page_states[7].residence_lifecycle_id
    self.assertEqual(1, ranker.page_states[7].referenced_current_epoch)
    self.assertEqual(0, ranker.page_states[7].referenced_previous_epoch)
    self.assertEqual(0, ranker.page_states[7].last_access_epoch)
    state.access_index = 63
    ranker.on_page_access(state, 7, 0)
    self.assertEqual(0, ranker.current_epoch)
    state.access_index = 64
    ranker.advance_to_access(state.access_index)
    self.assertEqual(1, ranker.current_epoch)
    self.assertEqual(0, ranker.page_states[7].referenced_current_epoch)
    self.assertEqual(1, ranker.page_states[7].referenced_previous_epoch)
    self.assertEqual("Warm", ranker.classify(ranker.page_states[7]))
    state.access_index = 64 * 4
    ranker.advance_to_access(state.access_index)
    self.assertEqual(0, ranker.page_states[7].referenced_current_epoch)
    self.assertEqual(0, ranker.page_states[7].referenced_previous_epoch)
    self.assertEqual("Cold", ranker.classify(ranker.page_states[7]))
    ranker.on_page_demoted(
        state, 7, proactive_replay.EMERGENCY_DEMOTION)
    state.dram_resident.remove(7)
    self.assertNotIn(7, ranker.page_states)
    state.access_index += 1
    state.dram_resident.add(7)
    ranker.on_page_enter_dram(state, 7)
    self.assertGreater(
        ranker.page_states[7].residence_lifecycle_id, first_lifecycle)
    self.assertEqual(0, ranker.page_states[7].referenced_previous_epoch)

  def test_threshold_one_and_two_classification(self):
    one = proactive_stage6_tpp.TPPInspiredRanker(64, 1, False)
    two = proactive_stage6_tpp.TPPInspiredRanker(64, 2, False)
    current = proactive_stage6_tpp.TPPPageState(1, 1, 0, False, 1)
    previous = proactive_stage6_tpp.TPPPageState(0, 1, 0, False, 2)
    neither = proactive_stage6_tpp.TPPPageState(0, 0, None, False, 3)
    self.assertEqual("Hot", one.classify(current))
    self.assertEqual("Cold", one.classify(previous))
    self.assertEqual("Cold", one.classify(neither))
    self.assertEqual("Hot", two.classify(current))
    self.assertEqual("Warm", two.classify(previous))
    self.assertEqual("Cold", two.classify(neither))

  def _rank_fixture(self, dirty_tie_break):
    ranker = proactive_stage6_tpp.TPPInspiredRanker(
        64, 2, dirty_tie_break)
    state = DummyReplayState()
    state.access_index = 128
    ranker.current_epoch = 2
    candidates = [60, 50, 40, 30, 20, 10]
    state.dram_resident.update(candidates)
    state.dirty_state.update({
        60: False, 50: True, 40: False,
        30: True, 20: False, 10: True})
    definitions = {
        60: (0, 0, 0), 50: (0, 0, 0),
        40: (0, 1, 1), 30: (0, 1, 1),
        20: (1, 0, 2), 10: (1, 0, 2)}
    for lifecycle, page in enumerate(candidates, 1):
      current, previous, last = definitions[page]
      ranker.page_states[page] = proactive_stage6_tpp.TPPPageState(
          current, previous, last, state.dirty_state[page], lifecycle)
    features = [
        {"page": page, "lru_tail_rank": index}
        for index, page in enumerate(candidates)]
    ranking = ranker.rank_candidates(
        state, candidates, features,
        {"cycle_id": 1, "cycle_round_index": 1})
    return ranker, state, ranking

  def test_dirty_tie_break_on_uses_six_level_order(self):
    _, _, ranking = self._rank_fixture(True)
    self.assertEqual(
        [60, 50, 40, 30, 20, 10],
        [row["page"] for row in ranking])
    self.assertEqual(
        ["Cold", "Cold", "Warm", "Warm", "Hot", "Hot"],
        [row["temperature"] for row in ranking])
    self.assertEqual([0, 1, 2, 3, 4, 5],
                     [row["ranking_key"][0] for row in ranking])

  def test_dirty_tie_break_off_ignores_dirty_and_uses_age_lru_page(self):
    ranker, state, _ = self._rank_fixture(False)
    # Reverse dirty flags without changing any other ranking field.
    for page in state.dirty_state:
      state.dirty_state[page] = not state.dirty_state[page]
    candidates = [60, 50, 40, 30, 20, 10]
    features = [{"page": page, "lru_tail_rank": index}
                for index, page in enumerate(candidates)]
    second = ranker.rank_candidates(
        state, candidates, features,
        {"cycle_id": 2, "cycle_round_index": 1})
    self.assertEqual(candidates, [row["page"] for row in second])
    self.assertTrue(all(
        row["rule"] == "temperature_age_lru_page_dirty_ignored"
        for row in second))
    # Explicit tie-break key: class, older age, tail rank, page id.
    self.assertTrue(all(len(row["ranking_key"]) == 4 for row in second))

  def test_missing_state_is_deterministic_and_candidate_scoped(self):
    ranker = proactive_stage6_tpp.TPPInspiredRanker(64, 2, False)
    state = DummyReplayState()
    state.access_index = 130
    candidates = [9, 3]
    state.dram_resident.update(candidates)
    state.dirty_state.update({9: False, 3: False})
    ranking = ranker.rank_candidates(
        state, candidates,
        [{"page": 9, "lru_tail_rank": 0},
         {"page": 3, "lru_tail_rank": 1}],
        {"cycle_id": 1, "cycle_round_index": 1})
    self.assertEqual({9, 3}, {row["page"] for row in ranking})
    self.assertEqual(2, ranker.summary_metrics()[
        "missing_state_initializations"])
    self.assertTrue(all(row["last_access_epoch"] is None
                        for row in ranking))

  def test_top_b_is_unique_and_strictly_within_candidate_snapshot(self):
    _, _, ranking = self._rank_fixture(True)
    selected = proactive_replay.select_top_b(ranking, 4)
    self.assertEqual(4, len(selected))
    self.assertEqual(4, len(set(selected)))
    self.assertTrue(set(selected).issubset(
        {row["page"] for row in ranking}))

  def test_emergency_demotion_is_not_counted_as_tpp_selection(self):
    ranker = proactive_stage6_tpp.TPPInspiredRanker(64, 2, True)
    state = DummyReplayState()
    state.dram_resident.add(1)
    state.dirty_state[1] = False
    ranker.on_page_enter_dram(state, 1)
    ranker.on_page_demoted(
        state, 1, proactive_replay.EMERGENCY_DEMOTION)
    metrics = ranker.summary_metrics()
    self.assertEqual(0, metrics["selected_temperature_distribution"]["total"])
    self.assertFalse(metrics["fallback_to_lru_used"])

  def test_cold_short_reuse_uses_frozen_64_access_window(self):
    ranker = proactive_stage6_tpp.TPPInspiredRanker(64, 2, True)
    state = DummyReplayState()
    state.access_index = 128
    # Make free_frames=12 so rank_candidates is called in a legal target gap.
    state.dram_resident.update(range(1, 21))
    state.dirty_state.update({page: False for page in range(1, 21)})
    ranker.current_epoch = 2
    for page in range(1, 21):
      ranker.page_states[page] = proactive_stage6_tpp.TPPPageState(
          0, 0, 0, False, page)
    candidates = [1, 2]
    ranking = ranker.rank_candidates(
        state, candidates,
        [{"page": 1, "lru_tail_rank": 0},
         {"page": 2, "lru_tail_rank": 1}],
        {"cycle_id": 1, "cycle_round_index": 1})
    self.assertEqual([1, 2], [row["page"] for row in ranking])
    ranker.on_page_demoted(
        state, 1, proactive_replay.PROACTIVE_DEMOTION)
    state.dram_resident.remove(1)
    state.access_index += 10
    state.dram_resident.add(1)
    ranker.on_page_enter_dram(state, 1)
    ranker.on_page_access(state, 1, 0)
    metrics = ranker.summary_metrics()
    self.assertEqual(1, metrics["cold_selected_count"])
    self.assertEqual(1, metrics["cold_short_reuse_count"])
    self.assertEqual(1.0, metrics["cold_short_reuse_rate"])
    self.assertEqual(64, metrics["cold_short_reuse_window_accesses"])

  def test_test_input_and_legacy_artifact_are_hard_rejected(self):
    trace = [{"page": 1, "rw": 0}]
    with self.assertRaises(contract.Stage6ContractError):
      proactive_stage6_replay.run_replay(
          self.stage0, self.config, self.cost, trace,
          workload="synthetic", split="test",
          split_role="final_evaluation_only",
          source_interval={"start": 0, "end": 1},
          trace_sha256=proactive_stage4.fingerprint_value(trace),
          dram_capacity_pages=20, working_set_pages=1,
          epoch_length=64, cold_threshold=2,
          dirty_tie_break=True, measure_latency=False)
    with self.assertRaises(proactive_stage5_contract.Stage5ContractError):
      contract.audit_no_contamination([
          "outputs/results/finals_v3_official/stage5_main/result.json"])
    with self.assertRaises(contract.Stage6ContractError):
      contract.audit_no_contamination([
          "outputs/results/finals_v3_official/stage6_tpp/result.json"])


if __name__ == "__main__":
  unittest.main()
