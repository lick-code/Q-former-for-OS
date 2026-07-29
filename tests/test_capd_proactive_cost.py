# coding=utf-8
"""Stage-2 Cost freeze, arithmetic, input-contract, and CLI tests."""

import ast
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_cost
from scripts import recompute_proactive_cost


CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals",
    "capd_proactive_stage2_cost_profiles.json")
FIXTURE_PATH = os.path.join(
    PROJECT_ROOT, "tests", "fixtures",
    "capd_proactive_stage2_raw_events.json")
INVALID_FIXTURE_PATH = os.path.join(
    PROJECT_ROOT, "tests", "fixtures",
    "capd_proactive_stage2_invalid_raw_events.json")


@contextlib.contextmanager
def workspace_temp_path(suffix):
  """Uses a file directly under the writable workspace on restricted hosts."""
  temporary = tempfile.NamedTemporaryFile(
      dir=PROJECT_ROOT, suffix=suffix, delete=False)
  path = temporary.name
  temporary.close()
  try:
    yield path
  finally:
    if os.path.exists(path):
      os.remove(path)


class CostProfileFreezeTest(unittest.TestCase):

  def setUp(self):
    self.config = proactive_cost.load_cost_config(CONFIG_PATH)

  def test_all_four_profiles_are_frozen_exactly(self):
    self.assertEqual(
        {
            "read_light": {
                "dram_hit": 1, "nvm_read": 2, "nvm_write": 4,
                "demotion": 8},
            "default": {
                "dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
                "demotion": 10},
            "write_expensive": {
                "dram_hit": 1, "nvm_read": 2, "nvm_write": 12,
                "demotion": 10},
            "migration_expensive": {
                "dram_hit": 1, "nvm_read": 2, "nvm_write": 8,
                "demotion": 20},
        },
        {
            name: profile.weights_dict()
            for name, profile in self.config.profiles.items()
        })

  def test_default_and_parameterized_provenance_are_frozen(self):
    self.assertEqual("default", self.config.default_profile)
    self.assertEqual(
        "parameterized_profile_set", self.config.calibration_mode)
    self.assertEqual(
        "no_real_nvm_platform",
        self.config.source["provenance"]["platform_availability"])
    rendered = json.dumps(self.config.source, ensure_ascii=False).lower()
    self.assertNotIn('"measured"', rendered)
    self.assertNotIn("hardware_calibrated", rendered)
    self.assertNotIn("real_nvm_measurement", rendered)
    self.assertNotIn("empirical_nvm_latency", rendered)

  def test_awaiting_stage1_status_cannot_claim_verified(self):
    self.assertEqual(
        "stage2_implemented_awaiting_stage1_integration",
        self.config.stage_status)
    self.assertFalse(self.config.stage1_integration_completed)

  def test_unsupported_schema_version_is_rejected(self):
    invalid = copy.deepcopy(self.config.source)
    invalid["schema_version"] = "future_schema"
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "schema_version"):
      proactive_cost.validate_cost_config(invalid)

  def test_default_profile_must_exist_and_equal_default(self):
    invalid = copy.deepcopy(self.config.source)
    invalid["default_profile"] = "unknown"
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "default_profile"):
      proactive_cost.validate_cost_config(invalid)

  def test_missing_or_illegal_weight_is_rejected(self):
    cases = []
    missing = copy.deepcopy(self.config.source)
    del missing["profiles"]["default"]["nvm_write"]
    cases.append(missing)
    zero = copy.deepcopy(self.config.source)
    zero["profiles"]["default"]["nvm_write"] = 0
    cases.append(zero)
    floating = copy.deepcopy(self.config.source)
    floating["profiles"]["default"]["nvm_write"] = 8.0
    cases.append(floating)
    boolean = copy.deepcopy(self.config.source)
    boolean["profiles"]["default"]["nvm_write"] = True
    cases.append(boolean)
    for invalid in cases:
      with self.subTest(invalid=invalid["profiles"]["default"]):
        with self.assertRaises(proactive_cost.CostContractError):
          proactive_cost.validate_cost_config(invalid)

  def test_duplicate_json_profile_name_is_rejected_before_validation(self):
    with workspace_temp_path(".json") as path:
      with open(path, "w", encoding="utf-8") as output_file:
        output_file.write(
            '{"profiles":{"default":{},"default":{}},"schema_name":"x"}')
      with self.assertRaisesRegex(
          proactive_cost.CostContractError, "Duplicate JSON object key"):
        proactive_cost.load_cost_config(path)


class RawEventContractTest(unittest.TestCase):

  def test_total_and_complete_breakdown_must_match(self):
    raw = proactive_cost.normalize_raw_event_counts({
        "dram_hits": 2,
        "nvm_reads": 3,
        "nvm_writes": 4,
        "total_demotions": 6,
        "proactive_demotions": 1,
        "reactive_demotions": 2,
        "emergency_demotions": 3,
    })
    self.assertEqual(6, raw.total_demotions)
    self.assertEqual(1, raw.proactive_demotions)
    broken = raw.to_dict()
    broken["total_demotions"] = 7
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "breakdown sum"):
      proactive_cost.normalize_raw_event_counts(broken)

  def test_complete_breakdown_alone_derives_total(self):
    raw = proactive_cost.normalize_raw_event_counts({
        "dram_hits": 0,
        "nvm_reads": 0,
        "nvm_writes": 0,
        "proactive_demotions": 4,
        "reactive_demotions": 5,
        "emergency_demotions": 6,
    })
    self.assertEqual(15, raw.total_demotions)

  def test_partial_breakdown_never_silently_passes(self):
    for missing in proactive_cost.DEMOTION_BREAKDOWN_FIELDS:
      value = {
          "dram_hits": 0,
          "nvm_reads": 0,
          "nvm_writes": 0,
          "proactive_demotions": 1,
          "reactive_demotions": 2,
          "emergency_demotions": 3,
      }
      del value[missing]
      with self.subTest(missing=missing):
        with self.assertRaisesRegex(
            proactive_cost.CostContractError, "partial"):
          proactive_cost.normalize_raw_event_counts(value)

  def test_missing_required_base_or_demotion_field_is_rejected(self):
    valid = {
        "dram_hits": 1, "nvm_reads": 2, "nvm_writes": 3,
        "total_demotions": 4}
    for missing in (
        "dram_hits", "nvm_reads", "nvm_writes", "total_demotions"):
      invalid = dict(valid)
      del invalid[missing]
      with self.subTest(missing=missing):
        with self.assertRaises(proactive_cost.CostContractError):
          proactive_cost.normalize_raw_event_counts(invalid)

  def test_negative_float_string_boolean_and_nan_counts_are_rejected(self):
    for invalid_value in (-1, 1.0, "1", True, float("nan")):
      raw = {
          "dram_hits": invalid_value,
          "nvm_reads": 0,
          "nvm_writes": 0,
          "total_demotions": 0,
      }
      with self.subTest(value=repr(invalid_value)):
        with self.assertRaises(proactive_cost.CostContractError):
          proactive_cost.normalize_raw_event_counts(raw)

  def test_all_zero_counts_are_valid(self):
    raw = proactive_cost.normalize_raw_event_counts({
        "dram_hits": 0, "nvm_reads": 0, "nvm_writes": 0,
        "total_demotions": 0})
    self.assertEqual(
        {
            "dram_hits": 0, "nvm_reads": 0, "nvm_writes": 0,
            "total_demotions": 0},
        raw.to_dict())


class CostArithmeticTest(unittest.TestCase):

  def setUp(self):
    self.config = proactive_cost.load_cost_config(CONFIG_PATH)
    self.raw_mapping = {
        "dram_hits": 100,
        "nvm_reads": 10,
        "nvm_writes": 5,
        "total_demotions": 3,
    }

  def test_default_hand_calculation_and_components(self):
    result = proactive_cost.compute_weighted_cost(
        self.raw_mapping, self.config.profiles["default"]).to_dict()
    self.assertEqual(190, result["weighted_cost"])
    self.assertEqual(
        {
            "dram_hit_cost": 100,
            "nvm_read_cost": 20,
            "nvm_write_cost": 40,
            "demotion_cost": 30,
        },
        result["component_costs"])
    self.assertEqual(
        result["weighted_cost"], sum(result["component_costs"].values()))

  def test_other_profiles_match_hand_calculation(self):
    expected = {
        "read_light": 164,
        "write_expensive": 210,
        "migration_expensive": 220,
    }
    for name, weighted_cost in expected.items():
      with self.subTest(profile=name):
        result = proactive_cost.compute_weighted_cost(
            self.raw_mapping, self.config.profiles[name])
        self.assertEqual(weighted_cost, result.weighted_cost)

  def test_all_profiles_reuse_identical_counts(self):
    results = proactive_cost.compute_all_profiles(
        self.raw_mapping, self.config.profiles)
    normalized = next(iter(results.values())).raw_counts.to_dict()
    self.assertTrue(all(
        result.raw_counts.to_dict() == normalized
        for result in results.values()))

  def test_switching_profile_changes_only_profile_and_cost_fields(self):
    results = proactive_cost.compute_all_profiles(
        self.raw_mapping, self.config.profiles)
    serialized = {
        name: result.to_dict() for name, result in results.items()}
    for result in serialized.values():
      self.assertEqual(self.raw_mapping, result["raw_counts"])
      self.assertEqual(
          {
              "profile_name", "raw_counts", "weights",
              "component_costs", "weighted_cost"},
          set(result))

  def test_input_mapping_is_not_modified_and_repeated_runs_are_identical(self):
    value = dict(self.raw_mapping, workload="toy", policy="capd")
    before = copy.deepcopy(value)
    first = proactive_cost.recompute_record(
        value, self.config, proactive_cost.FROZEN_PROFILE_NAMES)
    second = proactive_cost.recompute_record(
        value, self.config, proactive_cost.FROZEN_PROFILE_NAMES)
    self.assertEqual(before, value)
    self.assertEqual(first, second)

  def test_only_stage2_namespace_is_added_and_identity_is_unchanged(self):
    value = proactive_cost.load_strict_json(FIXTURE_PATH)
    output = proactive_cost.recompute_record(
        value, self.config, proactive_cost.FROZEN_PROFILE_NAMES)
    for key, original in value.items():
      self.assertIn(key, output)
      self.assertEqual(original, output[key])
    self.assertEqual(
        190, output["stage2_cost"]["default_weighted_cost"])
    self.assertEqual(
        set(proactive_cost.FROZEN_PROFILE_NAMES),
        set(output["stage2_cost"]["cost_results"]))

  def test_reserved_output_namespace_is_never_overwritten(self):
    value = dict(self.raw_mapping, stage2_cost={"existing": True})
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "refusing to overwrite"):
      proactive_cost.recompute_record(value, self.config)

  def test_cost_module_has_no_replay_model_or_gpu_import(self):
    with open(proactive_cost.__file__, "r", encoding="utf-8") as input_file:
      tree = ast.parse(input_file.read())
    imported = set()
    for node in ast.walk(tree):
      if isinstance(node, ast.Import):
        imported.update(alias.name for alias in node.names)
      elif isinstance(node, ast.ImportFrom):
        imported.add(node.module or "")
    self.assertFalse(any(
        name.startswith(("qmap.qmap_eval", "torch", "tensorflow"))
        for name in imported))


class OfflineCliTest(unittest.TestCase):

  def test_json_single_default_and_all_profiles(self):
    config = proactive_cost.load_cost_config(CONFIG_PATH)
    records, single = recompute_proactive_cost.read_records(FIXTURE_PATH)
    default = recompute_proactive_cost.recompute_records(
        records, single, config, ("default",))
    all_profiles = recompute_proactive_cost.recompute_records(
        records, single, config, proactive_cost.FROZEN_PROFILE_NAMES)
    self.assertEqual(190, default["stage2_cost"]["default_weighted_cost"])
    self.assertEqual(
        4, len(all_profiles["stage2_cost"]["cost_results"]))

  def test_jsonl_and_csv_multiple_records_are_supported(self):
    with workspace_temp_path(".jsonl") as jsonl_path:
      with workspace_temp_path(".csv") as csv_path:
        records = [
            {
                "workload": "a", "dram_hits": 1, "nvm_reads": 2,
                "nvm_writes": 3, "total_demotions": 4},
            {
                "workload": "b", "dram_hits": 5, "nvm_reads": 6,
                "nvm_writes": 7, "total_demotions": 8},
        ]
        with open(jsonl_path, "w", encoding="utf-8") as output_file:
          for record in records:
            output_file.write(json.dumps(record) + "\n")
        with open(csv_path, "w", encoding="utf-8", newline="") as output_file:
          output_file.write(
              "workload,dram_hits,nvm_reads,nvm_writes,total_demotions\n")
          output_file.write("a,1,2,3,4\n")
          output_file.write("b,5,6,7,8\n")
        jsonl, jsonl_single = recompute_proactive_cost.read_records(jsonl_path)
        csv_rows, csv_single = recompute_proactive_cost.read_records(csv_path)
    self.assertFalse(jsonl_single)
    self.assertFalse(csv_single)
    self.assertEqual(records, jsonl)
    self.assertEqual(records, csv_rows)

  def test_csv_conversion_is_explicit_and_rejects_noncanonical_counts(self):
    with workspace_temp_path(".csv") as path:
      with open(path, "w", encoding="utf-8", newline="") as output_file:
        output_file.write(
            "dram_hits,nvm_reads,nvm_writes,total_demotions\n")
        output_file.write("1.0,2,3,4\n")
      with self.assertRaisesRegex(
          proactive_cost.CostContractError, "canonical"):
        recompute_proactive_cost.read_records(path)

  def test_cli_writes_json_without_changing_input(self):
    with workspace_temp_path(".input.json") as input_path:
      with workspace_temp_path(".output.json") as output_path:
        with open(FIXTURE_PATH, "rb") as source:
          original_bytes = source.read()
        with open(input_path, "wb") as destination:
          destination.write(original_bytes)
        exit_code = recompute_proactive_cost.run([
            "--config", CONFIG_PATH,
            "--input", input_path,
            "--all-profiles",
            "--output", output_path,
        ])
        with open(input_path, "rb") as input_file:
          after_bytes = input_file.read()
        with open(output_path, "r", encoding="utf-8") as output_file:
          output = json.load(output_file)
    self.assertEqual(0, exit_code)
    self.assertEqual(original_bytes, after_bytes)
    self.assertEqual(4, len(output["stage2_cost"]["cost_results"]))

  def test_cli_refuses_input_output_alias(self):
    with self.assertRaisesRegex(
        proactive_cost.CostContractError, "must differ"):
      recompute_proactive_cost.run([
          "--config", CONFIG_PATH,
          "--input", FIXTURE_PATH,
          "--output", FIXTURE_PATH,
      ])

  def test_invalid_cli_input_returns_nonzero_and_diagnostic(self):
    stderr = io.StringIO()
    argv = [
        "recompute_proactive_cost.py",
        "--config", CONFIG_PATH,
        "--input", INVALID_FIXTURE_PATH,
    ]
    with mock.patch.object(sys, "argv", argv):
      with contextlib.redirect_stderr(stderr):
        exit_code = recompute_proactive_cost.main()
    self.assertEqual(2, exit_code)
    self.assertIn("nvm_writes", stderr.getvalue())

  def test_validate_config_mode_needs_no_input(self):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
      exit_code = recompute_proactive_cost.run([
          "--config", CONFIG_PATH, "--validate-config"])
    self.assertEqual(0, exit_code)
    self.assertIn("VALID stage2 Cost config", stdout.getvalue())


if __name__ == "__main__":
  unittest.main()
