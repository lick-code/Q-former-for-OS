# coding=utf-8
"""Contract tests for the R4/Stage7 CAPD Stage-4 entry."""

import argparse
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from qmap import proactive_stage4_stage7 as stage4
from qmap import proactive_stage4 as legacy_stage4
from qmap import qmap_train
from scripts import run_capd_proactive_stage4_stage7 as runner


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage4_stage7_search.json")


def dump(path, value):
  with open(path, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(value, handle, sort_keys=True, indent=2)
    handle.write("\n")


def authority_fixture(directory):
  watermarks = [
      {"workload": "canneal", "D": 120, "F_low": 6, "F_target": 16},
      {"workload": "streamcluster_pressure", "D": 22, "F_low": 1,
       "F_target": 3},
      {"workload": "dedup_pressure", "D": 21, "F_low": 1,
       "F_target": 3},
      {"workload": "blackscholes", "D": 8, "F_low": 1, "F_target": 2},
      {"workload": "swaptions", "D": 8, "F_low": 1, "F_target": 2},
      {"workload": "fluidanimate", "D": 22, "F_low": 1, "F_target": 3}]
  matrix = [{"workload": row["workload"], "D_standard": row["D"],
             "D_pressure": row["D"]} for row in watermarks]
  freeze = {
      "formal_freeze": True, "stage4_entry_allowed": True,
      "status": "STAGE3_STAGE7_DERIVED_SELECTION_FORMALLY_FROZEN",
      "run_id": "stage3-stage7-unified-contract-r4",
      "selected_candidate_id": "win500000-q50-r10-a15-b04-batch2",
      "selected_window_records": 500000, "W_ref_quantile": 0.5,
      "requested_pressure_ratio": 0.1, "alpha": 0.15, "beta": 0.4,
      "candidate_size_K": 8, "b_max": 2, "watermarks": watermarks,
      "unified_capacity_matrix": matrix,
      "shared_standard_pressure_execution_contract": {
          "candidate_size_K": 8, "batch_mechanism": {"b_max": 2},
          "initial_state": "empty_dram_per_window",
          "cost_profile": {"dram_hit": 1, "nvm_read": 2,
                           "nvm_write": 8, "demotion": 10}}}
  run_state = {"formal_freeze": True,
               "status": "derived_selection_formally_frozen"}
  paths = {"freeze": os.path.join(directory, "final_freeze.json"),
           "pressure": os.path.join(directory,
                                    "pressure_generation_contract.json"),
           "state": os.path.join(directory, "run_state.json")}
  dump(paths["freeze"], freeze); dump(paths["pressure"], {"ok": True})
  dump(paths["state"], run_state)
  hashes = {key: stage4.fingerprint_file(path) for key, path in paths.items()}
  return paths, hashes, freeze, run_state


def candidate():
  return copy.deepcopy(stage4.load_json(CONFIG_PATH)["search"]["reference"])


class Stage4Stage7AuthorityTest(unittest.TestCase):

  def test_r4_registered_sha_constants(self):
    self.assertEqual(len(stage4.R4_FINAL_SHA256), 64)
    self.assertEqual(len(stage4.R2_MANIFEST_SHA256), 64)

  def test_r4_correct_sha_passes(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, _, _ = authority_fixture(root)
      result = stage4.validate_stage3_authority(
          paths["freeze"], hashes["freeze"], hashes["pressure"],
          hashes["state"])
      self.assertEqual(result["candidate_size_K"], 8)

  def test_r4_wrong_sha_fails(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, _, _ = authority_fixture(root)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_stage3_authority(
            paths["freeze"], "0" * 64, hashes["pressure"], hashes["state"])

  def test_formal_freeze_false_fails(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, freeze, _ = authority_fixture(root)
      freeze["formal_freeze"] = False; dump(paths["freeze"], freeze)
      hashes["freeze"] = stage4.fingerprint_file(paths["freeze"])
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_stage3_authority(
            paths["freeze"], hashes["freeze"], hashes["pressure"], hashes["state"])

  def test_stage4_entry_false_fails(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, freeze, _ = authority_fixture(root)
      freeze["stage4_entry_allowed"] = False; dump(paths["freeze"], freeze)
      hashes["freeze"] = stage4.fingerprint_file(paths["freeze"])
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_stage3_authority(
            paths["freeze"], hashes["freeze"], hashes["pressure"], hashes["state"])

  def test_old_verification_is_not_read(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, _, _ = authority_fixture(root)
      dump(os.path.join(root, "verification.json"), {"formal_freeze_created": False})
      result = stage4.validate_stage3_authority(
          paths["freeze"], hashes["freeze"], hashes["pressure"], hashes["state"])
      self.assertEqual(result["run_id"], "stage3-stage7-unified-contract-r4")

  def test_workload_specific_watermarks(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, _, _ = authority_fixture(root)
      result = stage4.validate_stage3_authority(
          paths["freeze"], hashes["freeze"], hashes["pressure"], hashes["state"])
      self.assertEqual(result["workloads"]["canneal"],
                       {"D": 120, "F_low": 6, "F_target": 16})
      self.assertEqual(result["workloads"]["blackscholes"]["F_low"], 1)

  def test_legacy_uniform_watermarks_do_not_enter(self):
    with tempfile.TemporaryDirectory() as root:
      paths, hashes, freeze, _ = authority_fixture(root)
      freeze["watermarks"][3].update({"F_low": 8, "F_target": 16})
      dump(paths["freeze"], freeze); hashes["freeze"] = stage4.fingerprint_file(paths["freeze"])
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_stage3_authority(
            paths["freeze"], hashes["freeze"], hashes["pressure"], hashes["state"])


class Stage4Stage7SearchContractTest(unittest.TestCase):

  def setUp(self):
    self.config = stage4.load_json(CONFIG_PATH)

  def test_search_draft_is_valid(self):
    stage4.validate_search_config(self.config)

  def test_k_is_fixed_to_eight(self):
    self.assertEqual(self.config["fixed"]["candidate_size_K"], 8)

  def test_b_max_is_fixed_to_two(self):
    self.assertEqual(self.config["fixed"]["b_max"], 2)

  def test_search_containing_k_fails(self):
    value = copy.deepcopy(self.config)
    value["search"]["K"] = [8]
    with self.assertRaises(stage4.Stage4Stage7ContractError):
      stage4.validate_search_config(value)

  def test_search_containing_capacity_fails(self):
    value = copy.deepcopy(self.config)
    value["search"]["capacity_ratio"] = [0.1]
    with self.assertRaises(stage4.Stage4Stage7ContractError):
      stage4.validate_search_config(value)

  def test_all_formal_seeds_are_explicit(self):
    self.assertEqual(tuple(self.config["formal_seeds"]), stage4.FORMAL_SEEDS)

  def test_candidate_count_and_training_count(self):
    self.assertEqual(self.config["search"]["candidate_count"], 15)
    self.assertEqual(self.config["search"]["training_run_count"], 45)

  def test_full_model_dimensions_are_validated(self):
    value = candidate(); value["model"]["hidden_dim"] = 31
    with self.assertRaises(stage4.Stage4Stage7ContractError):
      stage4.validate_candidate(value, "bad")

  def test_phase_inheritance_keeps_complete_args(self):
    semantic = stage4.resolve_phase_candidates(self.config, "semantic")[0]
    architecture = stage4.resolve_phase_candidates(
        self.config, "architecture", semantic)[1]
    for key in ("hidden_dim", "address_embed_dim", "pc_embed_dim",
                "num_layers", "num_heads", "feedforward_dim", "dropout"):
      self.assertIn(key, architecture["model"])
    for key in ("learning_rate", "batch_size", "weight_decay", "epochs"):
      self.assertIn(key, architecture["training"])

  def test_all_command_does_not_call_freeze(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    block = source[source.index('elif args.command == "all"'):]
    block = block[:block.index('elif args.command == "freeze"')]
    self.assertNotIn("freeze(args)", block)

  def test_freeze_without_flag_fails(self):
    args = argparse.Namespace(confirm_stage4_freeze=False)
    with self.assertRaises(RuntimeError):
      runner.freeze(args)


class Stage4Stage7ManifestBoundaryTest(unittest.TestCase):

  def source_entries(self):
    entries = []
    for workload in stage4.WORKLOADS:
      for split, start in (("train", 0), ("validation", 10)):
        entries.append({
            "workload": workload, "split_role": split, "formal_test": False,
            "source_trace_id": workload + "-source",
            "source_interval": {"start_inclusive": start,
                                "end_exclusive": start + 10},
            "accesses": 10, "sha256": "a" * 64,
            "trace_path": "stage7/{}/{}.csv".format(workload, split)})
    return entries

  def test_missing_workload_fails(self):
    entries = self.source_entries()[:-2]
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)

  def test_missing_validation_fails(self):
    entries = [entry for entry in self.source_entries()
               if not (entry["workload"] == "canneal" and
                       entry["split_role"] == "validation")]
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)

  def test_duplicate_workload_split_fails(self):
    entries = self.source_entries(); entries[-1] = copy.deepcopy(entries[0])
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)

  def test_test_role_hard_fails(self):
    entries = self.source_entries(); entries[0]["split_role"] = "test"
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)

  def test_pressure_derived_path_hard_fails(self):
    entries = self.source_entries(); entries[0]["trace_path"] = "pressure_test/x.csv"
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)

  def test_legitimate_pressure_named_workload_is_allowed(self):
    self.assertFalse(stage4._forbidden_path(
        "outputs/capd_proactive_stage7/splits/dedup_pressure/train.csv"))

  def test_source_interval_length_mismatch_fails(self):
    entries = self.source_entries(); entries[0]["accesses"] = 9
    value = {"formal_test": False, "test_entries": 0, "entries": entries}
    with tempfile.NamedTemporaryFile(delete=False) as handle:
      path = handle.name
    try:
      dump(path, value); digest = stage4.fingerprint_file(path)
      with self.assertRaises(stage4.Stage4Stage7ContractError):
        stage4.validate_r2_source_manifest(value, path, digest)
    finally:
      os.unlink(path)


class Stage4Stage7TrainingContractTest(unittest.TestCase):

  def test_indexed_labels_equal_shared_reference(self):
    trace = [{"page": index % 5, "pc": index % 3, "rw": index % 2}
             for index in range(40)]
    provider = stage4.IndexedLabelProvider(trace, 8)
    for index in range(len(trace)):
      for page in range(6):
        self.assertEqual(provider(trace, index, page, 8),
                         legacy_stage4.label_components(trace, index, page, 8))

  def test_qmap_train_applies_every_candidate_argument(self):
    model = candidate()["model"]
    training = candidate()["training"]
    context = {"seed": 3136859, "training": training,
               "weights": [1.0, 1.0, 2.0],
               "expected_shape": {"page_state_dim": 4},
               "model_args": model, "contract": {}, "stage7": True}
    args = qmap_train.build_arg_parser().parse_args([
        "--train_data", "train.jsonl", "--valid_data", "valid.jsonl",
        "--proactive_stage4_contract", "contract.json",
        "--ablation", "cross_attention", "--device", "cpu"])
    raw = {"contract_id": stage4.CONTRACT_ID,
           "execution": {"actual_device": "cpu"}}
    with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(raw))), \
         mock.patch.object(stage4, "load_json", return_value=raw), \
         mock.patch.object(stage4, "validate_training_contract",
                           return_value=context):
      qmap_train.apply_proactive_stage4_contract(args, explicit_seed=3136859)
    self.assertEqual(args.hidden_dim, model["hidden_dim"])
    self.assertEqual(args.feedforward_dim, model["feedforward_dim"])
    self.assertEqual(args.lr, training["learning_rate"])
    self.assertEqual(args.weight_decay, training["weight_decay"])

  def test_checkpoint_argument_mismatch_fails(self):
    contract = {"model_args": {"hidden_dim": 32},
                "training_args": {"epochs": 8}, "seed": 3136859}
    checkpoint = {"model_args": {"hidden_dim": 24},
                  "training_args": {"epochs": 8}, "seed": 3136859,
                  "stage4_training_contract_fingerprint":
                      stage4.fingerprint_value(contract)}
    with self.assertRaises(stage4.Stage4Stage7ContractError):
      stage4.checkpoint_args_match(checkpoint, contract)

  def test_resume_contract_change_fails_closed(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    self.assertIn("Resume contract changed", source)
    self.assertIn("Cached sample SHA mismatch", source)

  def test_require_cuda_has_no_cpu_fallback(self):
    fake_torch = mock.Mock()
    fake_torch.cuda.is_available.return_value = False
    with mock.patch.dict("sys.modules", {"torch": fake_torch}):
      with self.assertRaises(RuntimeError):
        runner.runtime_device("auto", True)

  def test_single_gpu_training_loop_is_serial(self):
    source = open(runner.__file__, "r", encoding="utf-8").read()
    self.assertIn("for seed in stage4.FORMAL_SEEDS", source)
    self.assertNotIn("ProcessPoolExecutor(\n        max_workers=args.train_workers",
                     source)

  def test_vocabulary_declares_train_only_and_oov(self):
    with tempfile.TemporaryDirectory() as root:
      train = os.path.join(root, "train.jsonl")
      valid = os.path.join(root, "valid.jsonl")
      row = {"workload_id": "canneal", "history_page_ids": [1, 2],
             "history_mask": [1, 1], "candidate_pages": [3, 0],
             "candidate_mask": [1, 0], "pc": [5, 6]}
      write = lambda path, value: open(path, "w", encoding="utf-8").write(
          json.dumps(value) + "\n")
      write(train, row)
      changed = copy.deepcopy(row); changed["history_page_ids"] = [1, 99]
      changed["pc"] = [5, 77]
      write(valid, changed)
      manifest = stage4.build_train_only_vocabulary(train, valid)
      self.assertEqual(manifest["fit_scope"], "six_train_only")
      self.assertEqual(
          manifest["validation_oov_by_workload"]["canneal"]["page_oov_unique"],
          1)
      self.assertEqual(
          manifest["validation_oov_by_workload"]["canneal"]["pc_oov_unique"],
          1)


if __name__ == "__main__":
  unittest.main()
