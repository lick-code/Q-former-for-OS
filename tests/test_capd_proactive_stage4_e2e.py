# coding=utf-8

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

from qmap import proactive_stage4


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
HAS_TORCH = importlib.util.find_spec("torch") is not None


def _sample(index, split):
  candidates = list(range(1, 9))
  inactivity = [1.0 - rank / 16.0 for rank in range(8)]
  coldness = [1.0 - rank / 20.0 for rank in range(8)]
  writes = [0.0 if rank % 2 == 0 else 0.1 for rank in range(8)]
  components = [
      {
          "d_hat": inactivity[rank],
          "q_hat": coldness[rank],
          "w_hat": writes[rank],
          "complete_future_window": True,
          "effective_lookahead": 256,
          "next_reuse_distance": None,
          "future_access_count": 0,
          "future_write_count": 0,
          "no_future_reuse": True,
      }
      for rank in range(8)]
  return {
      "schema_version": proactive_stage4.SAMPLE_SCHEMA,
      "contract_id": proactive_stage4.CONTRACT_ID,
      "experiment_id": "L256_lam1-1-4_K8_H5",
      "workload_id": "synthetic",
      "split": split,
      "decision_index": index,
      "history_page_ids": [0, 0, 1, 2, 3],
      "history_mask": [0, 0, 1, 1, 1],
      "pc": [0, 0, 11, 12, 13],
      "rw": [0, 0, 0, 1, 0],
      "candidate_pages": candidates,
      "candidate_state_features": [
          [rank / 8.0, float(rank % 2), 0.5, 1.0 - rank / 7.0]
          for rank in range(8)],
      "candidate_mask": [1] * 8,
      "original_pool_ranks": list(range(8)),
      "inactivity": inactivity,
      "coldness": coldness,
      "write_sensitivity": writes,
      "migration_cost": [0.0] * 8,
      "ranking_label": [
          proactive_stage4.composite_label(item, (1, 1, 4))
          for item in components],
      "label_components": components,
      "label_weights": [1, 1, 4],
      "lookahead_L": 256,
      "history_H": 5,
      "candidate_size_K": 8,
      "formal_test": False,
  }


@unittest.skipUnless(HAS_TORCH, "PyTorch is required for the training E2E")
class ProactiveStage4TrainingE2ETest(unittest.TestCase):

  def test_train_resume_identity_and_closed_loop_metric_path(self):
    with tempfile.TemporaryDirectory() as directory:
      train_path = os.path.join(directory, "train.jsonl")
      valid_path = os.path.join(directory, "validation.jsonl")
      train_count = proactive_stage4.write_jsonl_atomic(
          train_path, [_sample(index, "train") for index in range(6)])
      valid_count = proactive_stage4.write_jsonl_atomic(
          valid_path, [_sample(index, "validation") for index in range(2)])
      output = os.path.join(directory, "checkpoints")
      contract = {
          "schema_version": proactive_stage4.TRAINING_CONTRACT_SCHEMA,
          "contract_id": proactive_stage4.CONTRACT_ID,
          "experiment_id": "L256_lam1-1-4_K8_H5",
          "seed": 42,
          "expected_shape": {"H": 5, "K": 8, "page_state_dim": 4},
          "sample_identity": {
              "schema_version": proactive_stage4.SAMPLE_SCHEMA,
              "contract_id": proactive_stage4.CONTRACT_ID,
              "experiment_id": "L256_lam1-1-4_K8_H5",
          },
          "labels": {"lambda_1": 1, "lambda_2": 1, "lambda_3": 4},
          "training": {
              "epochs": 1, "batch_size": 2, "learning_rate": 0.0001,
              "checkpoint_tie_break": "earliest_epoch",
              "deterministic_algorithms": True,
              "position_encoding": "none",
              "use_page_id_embedding": True,
              "shared_page_embedding": False,
              "context_mode": "cross_attention",
              "approx_ndcg_alpha": 10.0,
          },
          "data": {
              "train": {
                  "path": train_path, "sample_count": train_count,
                  "sha256": proactive_stage4.fingerprint_file(train_path)},
              "validation": {
                  "path": valid_path, "sample_count": valid_count,
                  "sha256": proactive_stage4.fingerprint_file(valid_path)},
          },
          "method": {
              "F_low": 8, "F_target": 16, "b_max": 4,
              "candidate_source": "lru_tail", "selector": "disabled",
              "trajectory_policy": "proactive_lru",
          },
          "test_trace_opened": False,
      }
      contract_path = os.path.join(directory, "contract.json")
      proactive_stage4.write_json_atomic(contract_path, contract)
      completed = subprocess.run([
          sys.executable, "-m", "qmap.qmap_train",
          "--train_data", train_path,
          "--valid_data", valid_path,
          "--proactive_stage4_contract", contract_path,
          "--output_dir", output,
          "--seed", "42",
          "--device", "cpu",
          "--ablation", "cross_attention",
      ], cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
         stderr=subprocess.STDOUT, text=True, check=False)
      self.assertEqual(completed.returncode, 0, completed.stdout)
      manifest = proactive_stage4.load_json(os.path.join(
          output, "checkpoint_manifest.json"))
      self.assertEqual(
          manifest["selection_criterion"], "minimum_valid_loss_only")
      self.assertFalse(manifest["test_trace_opened"])
      checkpoint = manifest["checkpoints"]["best"]["path"]
      self.assertEqual(
          proactive_stage4.fingerprint_file(checkpoint),
          manifest["checkpoints"]["best"]["fingerprint"])
      with open(os.path.join(
          PROJECT_ROOT, "configs/finals/capd_proactive_stage0.json"),
                "r", encoding="utf-8") as source:
        stage0 = json.load(source)
      trace = [
          {"page": page, "rw": page % 2, "pc": page + 100}
          for page in range(1, 40)]
      row, details = proactive_stage4.evaluate_checkpoint(
          stage0, trace, "synthetic", 20, checkpoint, "cpu", 42,
          256, (1, 1, 4), 8, 5)
      self.assertEqual(row["seed"], 42)
      self.assertFalse(row["test_trace_opened"])
      self.assertGreater(row["proactive_round_count"], 0)
      self.assertEqual(
          row["proactive_round_count"],
          len(details))


if __name__ == "__main__":
  unittest.main()
