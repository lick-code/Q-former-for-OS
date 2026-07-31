# coding=utf-8
"""Server tests for stage-4 multi-seed and artifact binding."""

import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import qmap_train
from scripts import run_capd_stage4 as stage4


class MultiSeedTrainingTest(unittest.TestCase):

  def _args(self):
    return qmap_train.build_arg_parser().parse_args([
        "--train_data", "train.jsonl", "--config", "config.json"])

  def _config(self):
    return {
        "training": {"seed": 3136859, "epochs": 10, "batch_size": 32,
                     "learning_rate": 1e-4},
        "labels": {"lambda_d": 1, "lambda_q": 1, "lambda_w": 4},
        "features": {"page_state_dim": 4},
        "loss": {"approx_ndcg_alpha": 10},
        "model": {"position_encoding": "sinusoidal"},
        "embedding": {"page": {"shared": True, "max_vocab_size": 100},
                      "pc": {"max_vocab_size": 100}},
        "schema_version": "capd_finals_v3_0",
    }

  def test_default_seed_remains_config_3136859(self):
    args = self._args()
    with mock.patch.object(qmap_train.finals_config, "load_config",
                           return_value=self._config()), \
         mock.patch.object(qmap_train, "_validate_finals_artifacts",
                           return_value={}):
      qmap_train.apply_finals_config(args, explicit_seed=None)
    self.assertEqual(3136859, args.seed)
    self.assertEqual("config_default", args.training_seed_source)

  def test_explicit_seed_is_not_silently_overwritten(self):
    args = self._args()
    with mock.patch.object(qmap_train.finals_config, "load_config",
                           return_value=self._config()), \
         mock.patch.object(qmap_train, "_validate_finals_artifacts",
                           return_value={}):
      qmap_train.apply_finals_config(args, explicit_seed=42)
    self.assertEqual(42, args.seed)
    self.assertEqual("explicit_cli", args.training_seed_source)

  def test_validated_loader_result_is_not_reparsed_as_raw_v3(self):
    args = self._args()
    with mock.patch.object(qmap_train.finals_config, "load_config",
                           return_value=self._config()) as loader, \
         mock.patch.object(qmap_train.finals_config,
                           "use_page_id_embedding",
                           side_effect=AssertionError(
                               "validated config was reparsed")), \
         mock.patch.object(qmap_train, "_validate_finals_artifacts",
                           return_value={}):
      qmap_train.apply_finals_config(args, explicit_seed=42)
    loader.assert_called_once_with(
        "config.json", require_resolved=True,
        project_root=qmap_train.PROJECT_ROOT,
        verify_manifest_files=False)
    self.assertTrue(args.use_page_id_embedding)

  def test_official_seed_set_and_output_directories_are_distinct(self):
    self.assertEqual((3136859, 42, 2026), stage4.stage4_common.SEEDS)
    paths = {"seed_{}".format(seed) for seed in stage4.stage4_common.SEEDS}
    self.assertEqual(3, len(paths))

  def test_training_source_has_valid_only_selection_and_nonfinite_guard(self):
    source = inspect.getsource(qmap_train.main)
    self.assertIn("validation_loss < best_loss", source)
    self.assertIn("Non-finite training or validation loss", source)
    self.assertNotIn("test_loss", source)

  def test_stage4_generate_reuses_frozen_selector_without_search(self):
    source = inspect.getsource(stage4.generate)
    self.assertNotIn("search_selector", source)
    self.assertNotIn("fit_selector", source)
    self.assertIn("generate_reranker_jsonl", source)

  def test_jsonl_semantic_fingerprint_ignores_crlf_and_json_whitespace(self):
    rows = [{"b": 2, "a": 1}, {"x": [1, 2]}]
    with tempfile.TemporaryDirectory() as directory:
      left = os.path.join(directory, "left.jsonl")
      right = os.path.join(directory, "right.jsonl")
      with open(left, "wb") as output:
        output.write((json.dumps(rows[0]) + "\r\n" +
                      json.dumps(rows[1]) + "\r\n").encode("utf-8"))
      with open(right, "wb") as output:
        output.write((json.dumps(rows[0], sort_keys=True,
                                 separators=(",", ":")) + "\n" +
                      json.dumps(rows[1], sort_keys=True,
                                 separators=(",", ":")) + "\n").encode(
                                     "utf-8"))
      identity = stage4.stage4_common.assert_jsonl_semantically_equal(
          left, right, "newline regression")
      self.assertEqual(2, identity["row_count"])

  def test_jsonl_semantic_comparison_rejects_content_change(self):
    with tempfile.TemporaryDirectory() as directory:
      left = os.path.join(directory, "left.jsonl")
      right = os.path.join(directory, "right.jsonl")
      with open(left, "w", encoding="utf-8", newline="\n") as output:
        output.write('{"value":1}\n')
      with open(right, "w", encoding="utf-8", newline="\n") as output:
        output.write('{"value":2}\n')
      with self.assertRaisesRegex(ValueError, "semantic mismatch.*row 1"):
        stage4.stage4_common.assert_jsonl_semantically_equal(
            left, right, "content regression")

  def test_stage4_preserves_frozen_manifest_binding_and_records_raw_sha(self):
    source = inspect.getsource(stage4.audit_inputs)
    self.assertIn("manifest_source_identity", source)
    self.assertIn("source_manifest_provenance_identity", source)
    self.assertIn("source_manifest_file_sha256", source)

  def test_stage4_training_has_no_test_argument_or_path(self):
    source = inspect.getsource(stage4.train)
    self.assertNotIn("test_trace", source)
    self.assertNotIn("test_data", source)
    self.assertIn("verify_manifest_files=False",
                  inspect.getsource(qmap_train.apply_finals_config))


if __name__ == "__main__":
  unittest.main()
