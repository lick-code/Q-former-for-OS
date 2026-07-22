# coding=utf-8
"""Server tests for stage-4 multi-seed and artifact binding."""

import inspect
import os
import sys
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

  def test_stage4_training_has_no_test_argument_or_path(self):
    source = inspect.getsource(stage4.train)
    self.assertNotIn("test_trace", source)
    self.assertNotIn("test_data", source)
    self.assertIn("verify_manifest_files=False",
                  inspect.getsource(qmap_train.apply_finals_config))


if __name__ == "__main__":
  unittest.main()
