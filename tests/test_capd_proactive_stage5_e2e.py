# coding=utf-8

import os
import tempfile
import unittest
from unittest import mock

from qmap import proactive_stage4
from qmap import proactive_stage5_contract as contract
from scripts import run_capd_proactive_stage5 as runner


class ProactiveStage5ResumeTest(unittest.TestCase):

  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.run_root = self.temporary.name
    os.makedirs(os.path.join(self.run_root, "jobs"))
    proactive_stage4.write_json_atomic(os.path.join(
        self.run_root, "run_identity.json"), {
            "run_identity_sha256": "a" * 64})
    self.entry = {
        "workload": "resume_fixture",
        "split": "validation",
        "role": "parameter_selection",
        "trace_sha256": "b" * 64,
        "source_interval": {"start": 0, "end": 2},
    }
    self.working_set = {
        "dram_capacity_pages": 20,
        "union_working_set_pages": 2,
    }
    self.trace = [
        {"page": 1, "rw": 0}, {"page": 2, "rw": 1}]
    self.result = {
        "semantic_result_sha256": "c" * 64,
        "schema_version": contract.RESULT_SCHEMA_VERSION,
    }

  def tearDown(self):
    self.temporary.cleanup()

  def call_job(self, trace=None):
    with mock.patch.object(
        runner.stage5_replay, "run_replay",
        return_value=self.result) as replay:
      output = runner._run_job(
          self.run_root, {}, {}, {}, {}, trace or self.trace, self.entry,
          self.working_set, "proactive_lru", measure_latency=False)
      return output, replay.call_count

  def test_completed_exact_identity_is_reused_without_execution(self):
    first, calls = self.call_job()
    self.assertEqual(self.result, first)
    self.assertEqual(1, calls)
    second, calls = self.call_job()
    self.assertEqual(self.result, second)
    self.assertEqual(0, calls)

  def test_single_identity_change_is_not_reused(self):
    self.call_job()
    changed = self.trace + [{"page": 3, "rw": 0}]
    with self.assertRaises(contract.Stage5ContractError):
      self.call_job(changed)

  def test_running_or_failed_job_is_preserved_and_not_retried(self):
    name = runner._job_name(
        self.entry["workload"], self.entry["split"], "proactive_lru", None)
    paths = runner._job_paths(self.run_root, name)
    os.makedirs(paths["directory"], exist_ok=True)
    identity = {
        "run_identity_sha256": "a" * 64,
        "job_name": name,
        "policy": "proactive_lru",
        "seed": None,
        "workload": self.entry["workload"],
        "split": self.entry["split"],
        "trace_sha256": self.entry["trace_sha256"],
        "source_interval": self.entry["source_interval"],
        "accesses": len(self.trace),
        "checkpoint_sha256": None,
        "measure_latency": False,
    }
    proactive_stage4.write_json_atomic(paths["manifest"], {
        "job_identity_sha256":
            proactive_stage4.fingerprint_value(identity),
        "status": "failed",
    })
    with self.assertRaises(contract.Stage5ContractError):
      self.call_job()

  def test_external_validator_failure_is_atomically_marked(self):
    runner._write_state(
        self.run_root, contract.IMPLEMENTED, ["preflight"])
    runner._mark_run_not_verified(
        self.run_root, "stage4_chain_and_contamination_audit")
    state = proactive_stage4.load_json(os.path.join(
        self.run_root, "run_state.json"))
    self.assertEqual(contract.NOT_VERIFIED, state["status"])
    self.assertEqual(
        "stage4_chain_and_contamination_audit", state["failure_step"])
    self.assertEqual(
        ["stage4_chain_and_contamination_audit"],
        state["failure_history"])
    with self.assertRaises(contract.Stage5ContractError):
      runner._reject_failed_run_id(self.run_root)
    self.assertIn("preflight", state["completed"])
    self.assertIn("failure_evidence_preserved", state["completed"])
    self.assertFalse(state["automatic_retry"])

    runner._mark_run_not_verified(
        self.run_root, "stage4_chain_and_contamination_audit")
    state = proactive_stage4.load_json(os.path.join(
        self.run_root, "run_state.json"))
    self.assertEqual(
        ["stage4_chain_and_contamination_audit"],
        state["failure_history"])

  def test_run_identity_covers_capd_runtime_dependencies(self):
    required = {
        "qmap/finals_config.py",
        "qmap/qmap_eval.py",
        "qmap/qmap_generator.py",
        "qmap/proactive_replay.py",
        "qmap/proactive_stage4.py",
        "qmap/proactive_stage5_policies.py",
        "policy_learning/cache_model/embed.py",
        "policy_learning/cache_model/loss.py",
        "policy_learning/cache_model/model.py",
    }
    self.assertTrue(required.issubset(set(runner.CODE_ARTIFACTS)))
    self.assertNotIn("git", runner.RUN_IDENTITY_BINDING_FIELDS)
    self.assertIn("trace_sha256", runner.RUN_IDENTITY_BINDING_FIELDS)
    self.assertIn("checkpoint_sha256", runner.RUN_IDENTITY_BINDING_FIELDS)
    self.assertIn("code_artifacts", runner.RUN_IDENTITY_BINDING_FIELDS)


if __name__ == "__main__":
  unittest.main()
