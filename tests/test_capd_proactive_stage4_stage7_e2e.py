# coding=utf-8
"""Synthetic orchestration tests; no real Stage7/Test/Pressure payloads."""

import argparse
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from qmap import proactive_stage4_stage7 as stage4
from scripts import run_capd_proactive_stage4_stage7 as runner


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage4_stage7_search.json")
R2_CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage4_stage7_search_r2.json")


def fake_authority():
  methods = {
      "canneal": {"D": 120, "F_low": 6, "F_target": 16},
      "streamcluster_pressure": {"D": 22, "F_low": 1, "F_target": 3},
      "dedup_pressure": {"D": 21, "F_low": 1, "F_target": 3},
      "blackscholes": {"D": 8, "F_low": 1, "F_target": 2},
      "swaptions": {"D": 8, "F_low": 1, "F_target": 2},
      "fluidanimate": {"D": 22, "F_low": 1, "F_target": 3}}
  return {"run_id": "stage3-stage7-unified-contract-r4",
          "final_freeze_sha256": stage4.R4_FINAL_SHA256,
          "window_records": 500000, "capacity_ratio": 0.1,
          "b_max": 2, "candidate_size_K": 8,
          "workloads": methods,
          "cost_profile": {"dram_hit": 1, "nvm_read": 2,
                           "nvm_write": 8, "demotion": 10}}


def args(root):
  return argparse.Namespace(
      command="preflight", config=CONFIG_PATH, stage3_freeze="freeze.json",
      input_manifest="manifest.json", run_id=stage4.RUN_ID,
      reuse_sample_cache_from=None,
      project_root=root, device="cpu", require_cuda=False,
      train_workers=1, sample_workers=1, replay_workers=1,
      confirm_stage4_search=False, confirm_stage4_freeze=False,
      candidate=None)


class Stage4Stage7SyntheticE2ETest(unittest.TestCase):

  def test_preflight_creates_expected_gate_artifacts(self):
    with tempfile.TemporaryDirectory() as root:
      config = copy.deepcopy(stage4.load_json(CONFIG_PATH))
      config["output_root"] = "outputs/new-stage4"
      config["execution"]["require_cuda"] = False
      manifest = {"entries": [{}] * 12}
      with mock.patch.object(runner, "load_context",
                             return_value=(config, fake_authority(), manifest,
                                           [{}] * 12)), \
           mock.patch.object(runner, "runtime_device", return_value={
               "requested": "cpu", "actual": "cpu", "require_cuda": False,
               "cuda_available": False, "cuda_device_count": 0,
               "cuda_device_name": None}), \
           mock.patch.object(runner, "git_state", return_value={
               "commit": "synthetic", "dirty": False,
               "status_sha256": "0" * 64}), \
           mock.patch.object(stage4, "validate_registered_trace_records",
                             return_value=[{}] * 12), \
           mock.patch.object(stage4, "fingerprint_file", return_value="1" * 64):
        output = runner.preflight(args(root))
      for name in ("resolved_config.json", "stage3_authority.json",
                   "input_manifest.json", "training_contract.json",
                   "search_space.json", "search_state.json", "run_state.json"):
        self.assertTrue(os.path.isfile(os.path.join(output, name)), name)
      state = stage4.load_json(os.path.join(output, "run_state.json"))
      self.assertFalse(state["formal_freeze"])
      self.assertFalse(state["search_contract_confirmed"])

  def test_r2_preflight_reuses_pinned_r1_parse_evidence(self):
    with tempfile.TemporaryDirectory() as root:
      config = copy.deepcopy(stage4.load_json(R2_CONFIG_PATH))
      config["output_root"] = "outputs/new-stage4"
      config["execution"]["require_cuda"] = False
      source_root = os.path.join(root, "r1")
      invocation = args(root)
      invocation.config = R2_CONFIG_PATH
      invocation.input_manifest = "r1-input-manifest.json"
      invocation.run_id = stage4.PROTOCOL_REPAIR_RUN_ID
      invocation.reuse_sample_cache_from = source_root
      config["cache_reuse"]["source_output_root"] = "r1"
      entries = [{"workload": workload, "split_role": split,
                  "accesses": 10}
                 for workload in stage4.WORKLOADS
                 for split in stage4.SPLITS]
      rows = [{"workload": entry["workload"],
               "split_role": entry["split_role"],
               "parsed_accesses": entry["accesses"],
               "rw_source": "real trace RW column"}
              for entry in entries]
      source_resolved = {"run_id": stage4.RUN_ID, "runtime": {
          "run_id": stage4.RUN_ID,
          "input_manifest_sha256": stage4.R1_PREPARED_INPUT_MANIFEST_SHA256,
          "trace_record_validation": rows}}
      with mock.patch.object(runner, "load_context", return_value=(
          config, fake_authority(), {"entries": entries}, entries)), \
           mock.patch.object(runner, "runtime_device", return_value={
               "requested": "cpu", "actual": "cpu", "require_cuda": False,
               "cuda_available": False, "cuda_device_count": 0,
               "cuda_device_name": None}), \
           mock.patch.object(runner, "git_state", return_value={
               "commit": "synthetic", "dirty": False,
               "status_sha256": "0" * 64}), \
           mock.patch.object(runner, "verify_failed_r1_audit", return_value={
               "resolved_config": source_resolved}), \
           mock.patch.object(stage4, "fingerprint_file", return_value=
                             stage4.R1_PREPARED_INPUT_MANIFEST_SHA256), \
           mock.patch.object(stage4, "validate_registered_trace_records") as \
               parse_current:
        output = runner.preflight(invocation)

      parse_current.assert_not_called()
      resolved = stage4.load_json(os.path.join(output, "resolved_config.json"))
      self.assertEqual(resolved["runtime"]["trace_record_validation"], rows)
      self.assertEqual(resolved["runtime"]["trace_record_validation_mode"],
                       "verified_r1_preflight_evidence_reuse")
      self.assertTrue(resolved["runtime"][
          "current_trace_payload_sha256_verified"])

  def test_full_search_refuses_missing_confirmation(self):
    with tempfile.TemporaryDirectory() as root:
      with self.assertRaises(RuntimeError):
        runner.require_search_confirmation(root, args(root))

  def test_confirmation_does_not_start_training(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    start = source.index("def confirm_contract")
    end = source.index("def require_search_confirmation")
    self.assertNotIn("ensure_training", source[start:end])
    self.assertNotIn("qmap.qmap_train", source[start:end])

  def test_sample_generation_binds_r4_method_and_is_deterministic(self):
    authority = fake_authority()
    config = stage4.load_json(CONFIG_PATH)
    candidate = stage4.resolve_phase_candidates(config, "semantic")[0]
    entry = {"workload": "blackscholes", "split_role": "train",
             "source_trace_id": "synthetic-train",
             "source_interval": {"start_inclusive": 0,
                                 "end_exclusive": 600}}
    trace = [{"page": index % 12, "pc": index % 7, "rw": index % 2}
             for index in range(600)]
    rows_a, diagnostics_a = stage4.generate_samples_for_trace(
        trace, entry, candidate, authority, "2" * 64)
    rows_b, diagnostics_b = stage4.generate_samples_for_trace(
        trace, entry, candidate, authority, "2" * 64)
    self.assertTrue(rows_a)
    self.assertEqual(stage4.fingerprint_value(rows_a),
                     stage4.fingerprint_value(rows_b))
    self.assertEqual(diagnostics_a["method"], diagnostics_b["method"])
    self.assertEqual(diagnostics_a["valid_decision_count"], len(rows_a))
    self.assertTrue(all(row["candidate_size_K"] == 8 for row in rows_a))
    self.assertTrue(all(row["b_max"] == 2 for row in rows_a))
    self.assertTrue(all(row["D"] == 8 and row["F_low"] == 1 and
                        row["F_target"] == 2 for row in rows_a))

  def test_architecture_learning_rate_and_seed_reuse_same_sample_identity(self):
    config = stage4.load_json(CONFIG_PATH)
    semantic = stage4.resolve_phase_candidates(config, "semantic")[0]
    architecture = stage4.resolve_phase_candidates(
        config, "architecture", semantic)[1]
    optimization = stage4.resolve_phase_candidates(
        config, "optimization", architecture)[1]
    authority = fake_authority()
    manifest_sha = "3" * 64
    self.assertEqual(
        stage4.sample_cache_identity(semantic, authority, manifest_sha),
        stage4.sample_cache_identity(architecture, authority, manifest_sha))
    self.assertEqual(
        stage4.sample_cache_identity(architecture, authority, manifest_sha),
        stage4.sample_cache_identity(optimization, authority, manifest_sha))

  def test_candidate_and_freeze_are_distinct_commands(self):
    parser = runner.build_parser()
    common = ["--stage3-freeze", "freeze.json",
              "--input-manifest", "manifest.json"]
    candidate_args = parser.parse_args(["candidate"] + common)
    freeze_args = parser.parse_args(["freeze"] + common +
                                    ["--confirm-stage4-freeze",
                                     "--candidate", "selected"])
    self.assertEqual(candidate_args.command, "candidate")
    self.assertTrue(freeze_args.confirm_stage4_freeze)

  def test_sample_gate_code_contains_no_training_or_selection_call(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    start = source.index("def generate_draft_samples")
    end = source.index("def verify_candidate_outputs")
    block = source[start:end]
    self.assertNotIn("ensure_training(", block)
    self.assertNotIn("run_search(", block)
    self.assertNotIn("confirm_contract(", block)
    self.assertNotIn("freeze(", block)

  def test_protocol_repair_candidate_summary_uses_only_active_four(self):
    config = stage4.load_json(R2_CONFIG_PATH)
    resolved = stage4.resolve_phase_candidates(config, "semantic")[0]
    seed_results = {}
    for seed in stage4.FORMAL_SEEDS:
      rows = []
      for index, workload in enumerate(stage4.ACTIVE_SELECTION_WORKLOADS):
        rows.append({
            "seed": seed, "workload": workload,
            "weighted_cost_per_access": float(index + 1),
            "ndcg_at_b_t": 0.5, "valid_decision_count": 10,
            "validation_role": "active_selection",
            "metric_status": "available", "model_invoked": True,
            "selection_eligible": True})
      rows.extend(stage4.structural_zero_validation_row(
          workload, seed, resolved, fake_authority())
                  for workload in stage4.STRUCTURAL_ZERO_DECISION_VALIDATION)
      rows.sort(key=lambda row: stage4.WORKLOADS.index(row["workload"]))
      seed_results[seed] = rows
    manifests = {seed: {
        "best_validation_loss": 0.25,
        "checkpoint_validation_scope": list(
            stage4.ACTIVE_SELECTION_WORKLOADS),
        "structural_zero_decision_validation": list(
            stage4.STRUCTURAL_ZERO_DECISION_VALIDATION)}
                 for seed in stage4.FORMAL_SEEDS}
    summary = runner.candidate_summary(
        config, resolved, seed_results, manifests)
    self.assertEqual(summary["primary_metric"], 2.5)
    self.assertEqual(summary["worst_workload_metric"], 4.0)
    self.assertEqual(summary["selection_scope"],
                     list(stage4.ACTIVE_SELECTION_WORKLOADS))
    self.assertEqual(set(summary["per_workload"]),
                     set(stage4.ACTIVE_SELECTION_WORKLOADS))

  def test_protocol_repair_candidate_summary_rejects_nonzero_structural_row(self):
    config = stage4.load_json(R2_CONFIG_PATH)
    resolved = stage4.resolve_phase_candidates(config, "semantic")[0]
    seed_results = {}
    for seed in stage4.FORMAL_SEEDS:
      rows = [{"seed": seed, "workload": workload,
               "weighted_cost_per_access": 1.0, "ndcg_at_b_t": 0.5,
               "valid_decision_count": 1, "validation_role": "active_selection",
               "metric_status": "available", "model_invoked": True,
               "selection_eligible": True}
              for workload in stage4.ACTIVE_SELECTION_WORKLOADS]
      rows.extend(stage4.structural_zero_validation_row(
          workload, seed, resolved, fake_authority())
                  for workload in stage4.STRUCTURAL_ZERO_DECISION_VALIDATION)
      rows[-1]["valid_decision_count"] = 1
      rows.sort(key=lambda row: stage4.WORKLOADS.index(row["workload"]))
      seed_results[seed] = rows
    with self.assertRaises(RuntimeError):
      runner.candidate_summary(
          config, resolved, seed_results,
          {seed: {
              "best_validation_loss": 0.25,
              "checkpoint_validation_scope": list(
                  stage4.ACTIVE_SELECTION_WORKLOADS),
              "structural_zero_decision_validation": list(
                  stage4.STRUCTURAL_ZERO_DECISION_VALIDATION)}
           for seed in stage4.FORMAL_SEEDS})

  def test_external_cache_registration_contains_no_copy_operation(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    start = source.index("def verify_and_register_external_cache")
    end = source.index("def load_verified_external_dataset")
    block = source[start:end]
    self.assertNotIn("shutil.copy", block)
    self.assertIn("copy_cache_files\": False", block)

  def test_sample_structure_report_detects_one_zero_workload_split(self):
    with tempfile.TemporaryDirectory() as root:
      key = "synthetic-semantic-key"
      dataset_root = os.path.join(root, "datasets", key)
      os.makedirs(dataset_root)
      manifest_path = os.path.join(dataset_root, "sample_manifest.json")
      with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump({"synthetic": True}, handle)
      diagnostics = []
      for workload in stage4.WORKLOADS:
        for split in stage4.SPLITS:
          count = 0 if (workload == "canneal" and
                        split == "validation") else 1
          diagnostics.append({
              "workload": workload, "split_role": split,
              "sample_count": count, "valid_decision_count": count,
              "path": "{}.jsonl".format(split), "sha256": "1" * 64,
              "sample_generation_contract_sha256": "2" * 64})
      empty_oov = {workload: {
          "page_total": 0, "page_oov_count": 0, "page_oov_unique": 0,
          "page_oov_rate": 0.0, "pc_total": 0, "pc_oov_count": 0,
          "pc_oov_unique": 0, "pc_oov_rate": 0.0}
                   for workload in stage4.WORKLOADS}
      vocabulary = {
          "fit_scope": "six_train_only", "validation_used_for_fit": False,
          "test_used_for_fit": False, "pressure_used_for_fit": False,
          "page_vocabulary_size": 1, "pc_vocabulary_size": 1,
          "page_vocabulary_sha256": "3" * 64,
          "pc_vocabulary_sha256": "4" * 64,
          "vocabulary_sha256": "5" * 64,
          "page_vocabulary_file_sha256": "6" * 64,
          "pc_vocabulary_file_sha256": "7" * 64,
          "manifest_path": "vocabulary_manifest.json",
          "manifest_sha256": "8" * 64,
          "validation_oov_by_workload": empty_oov}
      manifest = {
          "semantic_key": key, "sample_cache_identity_sha256": "9" * 64,
          "merged": {split: {"path": split + ".jsonl",
                             "sample_count": 5, "sha256": "a" * 64}
                     for split in stage4.SPLITS},
          "vocabulary": vocabulary, "per_workload": diagnostics}
      config = stage4.load_json(CONFIG_PATH)
      candidate = stage4.resolve_phase_candidates(config, "semantic")[0]
      report = runner.sample_structure_dataset_report(
          root, candidate, manifest, fake_authority())
      self.assertEqual(report["zero_sample_workload_splits"],
                       ["canneal/validation"])
      self.assertEqual(report["zero_valid_decision_workload_splits"],
                       ["canneal/validation"])

  def test_sample_gate_refuses_confirmation_flag_and_checkpoint(self):
    with tempfile.TemporaryDirectory() as root:
      invocation = args(root)
      invocation.input_manifest = os.path.join(root, "input_manifest.json")
      with open(invocation.input_manifest, "w", encoding="utf-8") as handle:
        json.dump({"entries": []}, handle)
      output = os.path.join(root, "outputs", "gate")
      os.makedirs(os.path.join(output, "checkpoints"))
      resolved = {
          "run_id": stage4.RUN_ID,
          "runtime": {
              "run_id": stage4.RUN_ID,
              "source_config_sha256": stage4.fingerprint_file(CONFIG_PATH),
              "input_manifest_sha256": stage4.fingerprint_file(
                  invocation.input_manifest)}}
      stage4.write_json_atomic(os.path.join(output, "resolved_config.json"),
                               resolved)
      stage4.write_json_atomic(os.path.join(output, "run_state.json"), {
          "status": "preflight_passed_awaiting_confirmation",
          "formal_freeze": False, "search_contract_confirmed": False,
          "test_trace_opened": False, "pressure_trace_opened": False})
      stage4.write_json_atomic(os.path.join(output, "search_state.json"), {
          "status": "not_started", "active_training_processes": 0,
          "completed_phases": [], "formal_freeze": False})
      invocation.confirm_stage4_search = True
      with self.assertRaises(RuntimeError):
        runner.require_sample_structure_gate_ready(
            invocation, output, stage4.load_json(CONFIG_PATH))
      invocation.confirm_stage4_search = False
      with open(os.path.join(output, "checkpoints", "model.pt"), "wb") as handle:
        handle.write(b"not-a-real-checkpoint")
      with self.assertRaises(RuntimeError):
        runner.require_sample_structure_gate_ready(
            invocation, output, stage4.load_json(CONFIG_PATH))


if __name__ == "__main__":
  unittest.main()
