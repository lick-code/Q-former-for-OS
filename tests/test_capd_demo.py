# coding=utf-8
"""Focused tests for the isolated CAPD screen-recording demo."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_capd_demo as demo
from scripts import show_capd_repository as repository_tour


class CapdDemoTest(unittest.TestCase):

  def test_repository_tour_finds_all_representative_paths(self):
    self.assertEqual(
        0, repository_tour.show_tour(
            demo.ROOT, include_assets=False, pause=0.0))

  def test_synthetic_trace_is_deterministic_and_nontrivial(self):
    one = demo.build_demo_trace()
    two = demo.build_demo_trace()
    self.assertEqual(one, two)
    self.assertEqual(demo.fingerprint_value(one), demo.fingerprint_value(two))
    self.assertGreater(len(one), 300)
    self.assertGreater(len({row["page"] for row in one}), 24)
    self.assertTrue(all(set(row) == {"page", "rw", "pc"} for row in one))

  def test_rule_policy_demo_closes_without_formal_data(self):
    with tempfile.TemporaryDirectory(dir=demo.ROOT) as temporary:
      output = Path(temporary) / "rule-policy-demo"
      verification = demo.run_demo(
          demo.ROOT, output,
          ("reactive_lru", "proactive_lru", "proactive_clock"))
      self.assertEqual(
          "DEMO_CLOSED_LOOP_PASS", verification["closed_loop_status"])
      self.assertFalse(verification["formal_evidence"])
      self.assertFalse(
          verification["checks"]["formal_test_data_consumed"])
      self.assertFalse(
          verification["checks"]["checkpoint_sha256_verified"])
      saved = json.loads(
          (output / "verification.json").read_text(encoding="utf-8"))
      self.assertEqual(verification, saved)
      self.assertTrue((output / "demo_trace.jsonl").is_file())
      self.assertTrue((output / "results" / "reactive_lru.json").is_file())
      self.assertTrue((output / "results" / "proactive_clock.json").is_file())

  def test_self_check_rejects_counter_tampering(self):
    state = {
        "F_t": 2, "dram_resident": [1, 2], "nvm_resident": [3]}
    result = {
        "summary": {
            "total_accesses": 3, "dram_hits": 1, "nvm_reads": 1,
            "nvm_writes": 0, "page_enter_dram_count": 1,
            "total_demotions": 0, "proactive_demotions": 0,
            "reactive_demotions": 0, "emergency_demotions": 0},
        "weighted_cost": 3,
        "weighted_cost_components": {
            "dram_hit_cost": 1, "nvm_read_cost": 2,
            "nvm_write_cost": 0, "demotion_cost": 0},
        "final_state": state,
        "rounds": [],
    }
    failures = demo._verify_result(result, dram_pages=4)
    self.assertIn("access conservation", failures)

  def test_capd_rerank_summary_uses_same_round_lru_prefix(self):
    rounds = [
        {"b_t": 2, "candidate_pages": [1, 2, 3],
         "selected_pages": [1, 2]},
        {"b_t": 2, "candidate_pages": [4, 5, 6],
         "selected_pages": [6, 4]},
    ]
    value = demo._capd_rerank_summary("capd", rounds)
    self.assertEqual(2, value["total_decision_rounds"])
    self.assertEqual(1, value["model_reranked_rounds"])
    self.assertEqual(0.5, value["model_reranked_rate"])
    self.assertIsNone(demo._capd_rerank_summary("proactive_lru", rounds))

  def test_missing_torch_fails_before_creating_output(self):
    with tempfile.TemporaryDirectory(dir=demo.ROOT) as temporary:
      output = Path(temporary) / "must-not-exist"
      with mock.patch.object(
          demo, "_validate_runtime_dependencies",
          side_effect=demo.DemoError("torch unavailable")):
        with self.assertRaisesRegex(demo.DemoError, "torch unavailable"):
          demo.run_demo(demo.ROOT, output, ("capd",))
      self.assertFalse(output.exists())


if __name__ == "__main__":
  unittest.main()
