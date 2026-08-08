"""Fixture-only contract tests for Stage11 v2 production enablement."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

from qmap import proactive_stage11_v2_production as production
from qmap import proactive_stage11_v2_production_guard as guard
from qmap import proactive_stage11_v2_production_verifier as verifier
from scripts import run_capd_proactive_stage11_v2_production as runner
from scripts import verify_capd_proactive_stage11_v2_production as verify_runner


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/finals/capd_proactive_stage11_v2_production.json"
REAL_ROOTS = tuple((ROOT / relative).resolve() for relative in (
    "outputs/capd_proactive_stage8", "outputs/capd_proactive_stage9",
    "outputs/capd_proactive_stage10", "outputs/capd_proactive_stage11",
    "outputs/capd_proactive_stage11_v2",
    "outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2"))
REAL_SUCCESSFUL_OPENS: list[str] = []
REAL_DENIED_OPENS: list[str] = []
SHA = "a" * 64


def _audit_hook(event, args):
  if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
    return
  path = Path(os.fsdecode(args[0])).absolute().resolve(strict=False)
  if any(path == root or root in path.parents for root in REAL_ROOTS):
    REAL_DENIED_OPENS.append(str(path))
    raise PermissionError("Stage11 production fixtures deny real-upstream opens")


sys.addaudithook(_audit_hook)


SCHEMA_FILES = (
    "capd_proactive_stage11_v2_production_config_schema.json",
    "capd_proactive_stage11_v2_production_result_schema.json",
    "capd_proactive_stage11_v2_production_run_identity_schema.json",
    "capd_proactive_stage11_v2_production_run_state_schema.json",
    "capd_proactive_stage11_v2_input_audit_receipt_schema.json",
    "capd_proactive_stage11_v2_input_audit_binding_schema.json",
    "capd_proactive_stage11_v2_production_execution_authorization_schema.json",
    "capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json",
    "capd_proactive_stage11_v2_test_source_identity_schema.json",
    "capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json",
    "capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json",
    "capd_proactive_stage11_v2_production_package_manifest_schema.json",
    "capd_proactive_stage11_v2_production_generation_source_manifest_schema.json",
    "capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json",
    "capd_proactive_stage11_v2_production_verification_receipt_schema.json",
    "capd_proactive_stage11_v2_production_final_approval_receipt_schema.json",
    "capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json",
)


def _load_config():
  return production.load_json_strict(CONFIG_PATH)


def _approved_plan_whitelist(section: str) -> tuple[str, ...]:
  plan = (ROOT / "docs/superpowers/plans/2026-08-07-stage11-production-enablement.md"
          ).read_text(encoding="utf-8")
  match = re.search(
      r"^### {}[^\n]*\n.*?^```text\n(.*?)^```$".format(re.escape(section)),
      plan, flags=re.MULTILINE | re.DOTALL)
  if match is None:
    raise AssertionError("Approved-plan source whitelist is missing: " + section)
  return tuple(line.strip() for line in match.group(1).splitlines()
               if line.strip())


def _sha_bytes(raw: bytes) -> str:
  return hashlib.sha256(raw).hexdigest()


def _jobs():
  result = []
  index = 0
  for workload in production.STANDARD_WORKLOADS:
    for policy, seed in production.STANDARD_MEMBERS:
      index += 1
      result.append({
          "job_id": "standard__{}__{}__{}".format(
              workload, policy, "none" if seed is None else seed),
          "track": "standard", "workload": workload, "policy": policy,
          "seed": seed, "dram_hits": 100 + index, "nvm_reads": 20 + index,
          "nvm_writes": 5 + index, "total_demotions": 6,
          "raw_access_count": 200 + index, "reactive_demotions": 3,
          "proactive_demotions": 2, "emergency_demotions": 1})
  return result


def _tree_fixture(root: Path):
  roots = tuple((name, name) for name in ("a", "b", "c", "d", "e"))
  for name, _ in roots[:4]:
    path = root / name
    path.mkdir(parents=True)
    (path / "member.bin").write_bytes(name.encode("ascii"))
  return roots, production.frozen_tree_snapshot(root, roots)


def _input_receipt(repository_revision_match=False):
  fields = {
      "schema_version": "capd_proactive_stage11_v2_input_audit_receipt_v1_0",
      "contract_id": production.CONTRACT_ID, "audit_id": production.AUDIT_ID,
      "approved_production_design_sha256": production.APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": production.APPROVED_PLAN_SHA256,
      "production_config_sha256": SHA, "production_result_schema_sha256": SHA,
      "generation_source_manifest_sha256": SHA,
      "generation_source_members_sha256": SHA,
      "generation_source_member_count": 30,
      "verifier_source_manifest_sha256": SHA,
      "verifier_source_members_sha256": SHA,
      "verifier_source_member_count": 32, "test_source_identity_sha256": SHA,
      "test_source_pre_snapshot_sha256": SHA,
      "test_source_post_snapshot_sha256": SHA, "test_sources_unchanged": True,
      "audit_commands_sha256": SHA, "synthetic_allowlist_log_sha256": SHA,
      "production_enablement_tests_log_sha256": SHA,
      "legacy_semantic_tests_log_sha256": SHA,
      "real_upstream_audit_stdout_sha256": SHA, "synthetic_test_count": 41,
      "production_enablement_test_count": 56, "legacy_semantic_test_count": 6,
      "stage8_input_verified": True, "stage9_input_authorized": True,
      "stage10_input_authorized": True, "stage8_input_receipt_sha256": SHA,
      "stage9_input_receipt_sha256": SHA, "stage10_input_receipt_sha256": SHA,
      "standard_source_manifest_sha256": SHA, "sorted_job_ids_sha256": SHA,
      "standard_job_count": 48, "standard_workload_count": 6,
      "frozen_tree_before_sha256": SHA, "frozen_tree_after_sha256": SHA,
      "frozen_tree_comparison_sha256": SHA, "frozen_trees_unchanged": True,
      "generation_source_set_match": True,
      "repository_revision_match": repository_revision_match,
      "sealed_dual_verifier_attestation": "verified",
      "current_live_replay_compatibility": "NOT_VERIFIABLE",
      "input_audit_verified": True, "stage11_execution_authorized": False,
      "stage11_formally_verified": False,
      "test_used_for_parameter_selection": False, "synthetic_test_only": False}
  return fields


def _authorization(input_receipt=None):
  source = input_receipt or _input_receipt()
  config = _load_config()
  value = {
      "schema_version":
          "capd_proactive_stage11_v2_production_execution_authorization_v1_0",
      "contract_id": production.CONTRACT_ID,
      "production_revision": production.PRODUCTION_REVISION,
      "run_id": production.RUN_ID,
      "approved_production_design_sha256": production.APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": production.APPROVED_PLAN_SHA256,
      "production_config_sha256": SHA, "production_result_schema_sha256": SHA,
      "production_run_identity_schema_sha256": SHA,
      "production_run_state_schema_sha256": SHA,
      "release_manifest_schema_sha256": SHA,
      "generation_source_manifest_sha256": source["generation_source_manifest_sha256"],
      "generation_source_members_sha256": source["generation_source_members_sha256"],
      "generation_source_member_count": 30,
      "verifier_source_manifest_sha256": source["verifier_source_manifest_sha256"],
      "verifier_source_members_sha256": source["verifier_source_members_sha256"],
      "verifier_source_member_count": 32,
      "test_source_identity_sha256": source["test_source_identity_sha256"],
      "test_source_pre_snapshot_sha256": source["test_source_pre_snapshot_sha256"],
      "test_source_post_snapshot_sha256": source["test_source_post_snapshot_sha256"],
      "test_sources_unchanged": True, "input_audit_receipt_sha256": SHA,
      "input_audit_manifest_sha256": SHA, "input_audit_checksums_sha256": SHA,
      "sealed_frozen_tree_after_sha256": source["frozen_tree_after_sha256"],
      "standard_source_manifest_sha256": source["standard_source_manifest_sha256"],
      "sorted_job_ids_sha256": source["sorted_job_ids_sha256"],
      "standard_job_count": 48, "standard_workload_count": 6,
      "stage8_input_receipt_sha256": source["stage8_input_receipt_sha256"],
      "stage9_input_receipt_sha256": source["stage9_input_receipt_sha256"],
      "stage10_input_receipt_sha256": source["stage10_input_receipt_sha256"],
      "stage10_generation_freeze_receipt_sha256": SHA,
      "stage10_readiness_receipt_sha256": SHA,
      "stage10_final_status_receipt_sha256": SHA,
      "frozen_cost_profiles_sha256": production.sha256_value(config["cost_profiles"]),
      "main_b_max": 2, "authorized_scope": "offline_cost_profiles_only",
      "expected_result_rows": 192, "blocked_lanes": list(production.BLOCKED_LANES),
      "stage11_execution_authorized": True, "synthetic_test_only": False,
      "test_used_for_parameter_selection": False,
      "future_output_hashes_absent": True, "approval_authority": "fixture",
      "approval_reference": "fixture-only"}
  return value


def _external_hashes():
  return {"receipt_sha256": SHA, "manifest_sha256": SHA,
          "checksums_sha256": SHA}


def _common_release():
  result = {field: SHA for field in verifier.COMMON_RELEASE_FIELDS
            if field.endswith("sha256")}
  result.update({
      "schema_version": "unused", "contract_id": production.CONTRACT_ID,
      "production_revision": production.PRODUCTION_REVISION,
      "run_id": production.RUN_ID,
      "approved_production_design_sha256": production.APPROVED_DESIGN_SHA256,
      "approved_production_plan_sha256": production.APPROVED_PLAN_SHA256,
      "upstream_continuity_verified": True, "synthetic_test_only": False,
      "test_used_for_parameter_selection": False})
  return result


def _verification_receipt():
  value = _common_release()
  value.update({
      "schema_version":
          "capd_proactive_stage11_v2_production_verification_receipt_v1_0",
      "verification_receipt_identity": "stage11-v2-production-verification-r1",
      "result_row_count": 192, "result_rows_verified": True,
      "status": "stage11_generation_verified_pending_final_approval",
      "monitoring": {
          **verifier.MONITORING_FIXED, "timed_out": False, "exit_code": 0,
          "process_alive_sample_count": 1, "wall_clock_start": 1.0,
          "wall_clock_end": 2.0, "wall_clock_duration_seconds": 1.0,
          "worker_pid": 1}, "stage11_formally_verified": False})
  return value


def _final_approval():
  value = _common_release()
  value.update({
      "schema_version":
          "capd_proactive_stage11_v2_production_final_approval_receipt_v1_0",
      "verification_receipt_sha256": SHA, "verification_manifest_sha256": SHA,
      "verification_checksums_sha256": SHA, "final_approval_granted": True,
      "approval_authority": "fixture", "approval_reference": "fixture-only",
      "stage11_formally_verified": False})
  return value


def _final_status():
  value = _common_release()
  value.update({
      "schema_version":
          "capd_proactive_stage11_v2_production_final_status_evidence_receipt_v1_0",
      "verification_receipt_sha256": SHA, "verification_manifest_sha256": SHA,
      "verification_checksums_sha256": SHA,
      "final_approval_receipt_sha256": SHA,
      "final_approval_manifest_sha256": SHA,
      "final_approval_checksums_sha256": SHA,
      "generation_verified": True, "final_approval_verified": True,
      "stage11_formally_verified": True})
  return value


class ProductionSchemaContractTest(unittest.TestCase):
  def test_exact_schema_family_exists(self):
    self.assertEqual(len(SCHEMA_FILES), 17)
    for name in SCHEMA_FILES:
      path = ROOT / "configs/finals" / name
      self.assertTrue(path.is_file(), name)
      value = json.loads(path.read_text(encoding="utf-8"))
      jsonschema.Draft202012Validator.check_schema(value)
      self.assertFalse(value["additionalProperties"])

  def test_config_binds_fixed_identity_grid_and_192_rows(self):
    config = _load_config()
    production.validate_config(
        config, externally_approved_plan_sha256=production.APPROVED_PLAN_SHA256)
    schema = json.loads((ROOT / "configs/finals" /
                         "capd_proactive_stage11_v2_production_config_schema.json"
                         ).read_text(encoding="utf-8"))
    jsonschema.validate(config, schema)
    self.assertEqual(config["main_control"], {"b_max": 2})
    self.assertEqual(config["expected_result_rows"], 192)
    self.assertEqual(len(config["cost_profiles"]), 4)

  def test_receipt_schemas_reject_non_exact_fields(self):
    receipt = _input_receipt()
    receipt["unexpected"] = True
    schema = json.loads((ROOT / "configs/finals" /
                         "capd_proactive_stage11_v2_input_audit_receipt_schema.json"
                         ).read_text(encoding="utf-8"))
    with self.assertRaises(jsonschema.ValidationError):
      jsonschema.validate(receipt, schema)
    with self.assertRaises(production.ProductionContractError):
      production.validate_input_audit_receipt(
          receipt, expected_plan_sha256=production.APPROVED_PLAN_SHA256)

  def test_package_manifest_breaks_recursive_hash_cycle(self):
    with self.assertRaises(production.ProductionContractError):
      production.build_manifest("generation", {"manifest.json": b"{}\n"})
    package = production.seal_package_bytes("generation", {"a.json": b"{}\n"})
    manifest = json.loads(package["manifest.json"])
    self.assertNotIn("manifest.json", {item["path"] for item in manifest["members"]})
    self.assertIn("manifest.json", package["SHA256SUMS"].decode("ascii"))
    self.assertNotIn("SHA256SUMS  SHA256SUMS", package["SHA256SUMS"].decode("ascii"))

  def test_missing_numeric_semantics_are_null_and_na(self):
    jobs = _jobs()
    jobs[0]["raw_access_count"] = 0
    rows = production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS)
    zero = [row for row in rows if row["source_job_id"] == jobs[0]["job_id"]]
    self.assertTrue(all(row["weighted_cost_per_access"] is None for row in zero))
    self.assertIn(b"N/A", production.rows_to_csv_bytes(rows))


class CanonicalUpstreamObjectTest(unittest.TestCase):
  def _objects(self):
    return production.canonical_upstream_objects(
        {"stage": 8}, {"stage": 9}, {"stage": 10}, {"jobs": []})

  def test_capture_emits_four_canonical_objects(self):
    objects = self._objects()
    self.assertEqual(set(objects), {
        "stage8_standard_input_receipt.json", "stage9_input_receipt.json",
        "stage10_input_receipt.json", "standard_source_manifest.json"})
    self.assertTrue(all(production.is_canonical_json_bytes(raw)
                        for raw in objects.values()))

  def test_independent_rebuild_matches_exact_bytes(self):
    production.compare_rebuilt_upstream_objects(self._objects(), self._objects())
    verifier.compare_rebuilt_upstream_objects(self._objects(), self._objects())
    value = {"b": 2, "a": 1}
    expected = hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    self.assertEqual(production.stage8_fingerprint_value(value), expected)
    self.assertEqual(verifier.stage8_fingerprint_value(value), expected)
    self.assertNotEqual(production.sha256_value(value), expected)

  def test_missing_canonical_object_is_rejected(self):
    objects = self._objects()
    objects.pop("stage9_input_receipt.json")
    with self.assertRaises(production.ProductionNotVerifiable):
      production.compare_rebuilt_upstream_objects(objects, self._objects())

  def test_rehashed_tampered_object_is_rejected(self):
    sealed = self._objects()
    rebuilt = dict(sealed)
    rebuilt["stage10_input_receipt.json"] = production.canonical_json_bytes(
        {"stage": 10, "tampered": True})
    with self.assertRaises(production.ProductionNotVerifiable):
      production.compare_rebuilt_upstream_objects(sealed, rebuilt)

  def test_semantically_equal_noncanonical_json_is_rejected(self):
    sealed = self._objects()
    sealed["stage8_standard_input_receipt.json"] = b'{ "stage": 8 }\n'
    with self.assertRaises(production.ProductionNotVerifiable):
      production.compare_rebuilt_upstream_objects(sealed, self._objects())


class InputAuditPackageTest(unittest.TestCase):
  def _payloads(self):
    result = {}
    for name in production.INPUT_AUDIT_PAYLOADS:
      result[name] = (b"fixture\n" if name.endswith(".log")
                      else production.canonical_json_bytes({"fixture": name}))
    return result

  def test_exact_input_audit_member_set(self):
    package = production.seal_package_bytes("input_audit", self._payloads())
    production.validate_package_bytes(
        package, phase="input_audit",
        expected_members=production.INPUT_AUDIT_PAYLOADS)
    with tempfile.TemporaryDirectory() as temporary:
      target = Path(temporary) / production.RUN_ID
      production.canonical_upstream_objects({}, {}, {}, {})
      self.assertFalse(target.exists())

  def test_external_receipt_manifest_checksums_sha_are_required(self):
    auth = _authorization()
    hashes = _external_hashes()
    hashes.pop("manifest_sha256")
    with self.assertRaises(production.ProductionContractError):
      production.validate_execution_authorization(
          auth, _load_config(), _input_receipt(),
          expected_plan_sha256=production.APPROVED_PLAN_SHA256,
          input_audit_external_hashes=hashes)

  def test_source_identity_rehashed_cross_binding_tamper_is_rejected(self):
    config = _load_config()
    generation = verifier.generation_source_manifest_value(ROOT)
    verifier_manifest = verifier.source_manifest_value(ROOT)
    snapshot = production.source_snapshot(ROOT, production.TEST_SOURCE_PATHS)
    test_identity = production.test_source_identity(ROOT, snapshot, snapshot)
    generation_path = ROOT / config["source_manifests"]["generation"]
    verifier_path = ROOT / config["source_manifests"]["verifier"]
    receipt = _input_receipt()
    receipt.update({
        "production_config_sha256": verifier.sha256_file(
            ROOT / "configs/finals/capd_proactive_stage11_v2_production.json"),
        "production_result_schema_sha256": verifier.sha256_file(
            ROOT /
            "configs/finals/capd_proactive_stage11_v2_production_result_schema.json"),
        "generation_source_manifest_sha256":
            verifier.sha256_file(generation_path),
        "generation_source_members_sha256": generation["members_sha256"],
        "verifier_source_manifest_sha256": verifier.sha256_file(verifier_path),
        "verifier_source_members_sha256": verifier_manifest["members_sha256"],
        "test_source_pre_snapshot_sha256":
            test_identity["test_source_pre_snapshot_sha256"],
        "test_source_post_snapshot_sha256":
            test_identity["test_source_post_snapshot_sha256"],
    })
    identity = {
        "schema_version": "capd_proactive_stage11_v2_source_identity_v1_0",
        "contract_id": production.CONTRACT_ID,
        "approved_production_design_sha256": production.APPROVED_DESIGN_SHA256,
        "approved_production_plan_sha256": production.APPROVED_PLAN_SHA256,
        "production_config_sha256": receipt["production_config_sha256"],
        "production_result_schema_sha256":
            receipt["production_result_schema_sha256"],
        "generation_source_manifest_path":
            config["source_manifests"]["generation"],
        "generation_source_manifest_sha256":
            receipt["generation_source_manifest_sha256"],
        "generation_source_members_sha256": generation["members_sha256"],
        "generation_source_member_count": 30,
        "verifier_source_manifest_path":
            config["source_manifests"]["verifier"],
        "verifier_source_manifest_sha256":
            receipt["verifier_source_manifest_sha256"],
        "verifier_source_members_sha256": verifier_manifest["members_sha256"],
        "verifier_source_member_count": 32,
        "source_pre_snapshot_sha256":
            test_identity["test_source_pre_snapshot_sha256"],
        "source_post_snapshot_sha256":
            test_identity["test_source_post_snapshot_sha256"],
        "source_unchanged": True,
        "code_version": verifier.code_version(ROOT),
    }
    verifier.validate_source_identity(
        project_root=ROOT, identity=identity, receipt=receipt, config=config,
        generation_manifest=generation, verifier_manifest=verifier_manifest,
        test_identity=test_identity)

    for field, wrong_value in (
        ("generation_source_manifest_sha256",
         verifier.sha256_value({
             "rehashed_tamper": verifier.load_json_strict(generation_path)})),
        ("verifier_source_manifest_sha256",
         verifier.sha256_value({
             "rehashed_tamper": verifier.load_json_strict(verifier_path)}))):
      tampered = copy.deepcopy(identity)
      tampered[field] = wrong_value
      payloads = self._payloads()
      payloads["source_identity.json"] = production.canonical_json_bytes(tampered)
      payloads["input_audit_receipt.json"] = production.canonical_json_bytes(receipt)
      rehashed = production.seal_package_bytes("input_audit", payloads)
      verifier.verify_package(
          rehashed, phase="input_audit",
          payload_names=verifier.INPUT_AUDIT_PAYLOADS)
      with self.assertRaises(verifier.VerificationError):
        verifier.validate_source_identity(
            project_root=ROOT, identity=tampered, receipt=receipt, config=config,
            generation_manifest=generation,
            verifier_manifest=verifier_manifest, test_identity=test_identity)

    missing = copy.deepcopy(identity)
    missing.pop("code_version")
    with self.assertRaises(verifier.VerificationError):
      verifier.validate_source_identity(
          project_root=ROOT, identity=missing, receipt=receipt, config=config,
          generation_manifest=generation, verifier_manifest=verifier_manifest,
          test_identity=test_identity)

  def test_wrong_log_ids_or_counts_are_rejected(self):
    value = {"test_ids": ["a"], "tests_run": 1, "result": "OK",
             "exit_code": 0, "timed_out": False,
             "automatic_retry_performed": False}
    with self.assertRaises(production.ProductionNotVerifiable):
      production.validate_test_log_identity(value, ["b"], 1)

  def test_failed_upstream_gate_fails_closed(self):
    receipt = _input_receipt()
    receipt["stage9_input_authorized"] = False
    with self.assertRaises(production.ProductionNotVerifiable):
      production.validate_input_audit_receipt(
          receipt, expected_plan_sha256=production.APPROVED_PLAN_SHA256)


class TestSourceIdentityTest(unittest.TestCase):
  def test_exact_29_member_whitelist(self):
    self.assertEqual(len(production.TEST_SOURCE_PATHS), 29)
    self.assertEqual(tuple(sorted(set(production.TEST_SOURCE_PATHS))),
                     production.TEST_SOURCE_PATHS)
    self.assertEqual(production.TEST_SOURCE_PATHS,
                     _approved_plan_whitelist("4.3"))

  def test_pre_post_test_source_snapshots_match(self):
    snapshot = production.source_snapshot(ROOT, production.TEST_SOURCE_PATHS)
    identity = production.test_source_identity(ROOT, snapshot, snapshot)
    self.assertTrue(identity["test_sources_unchanged"])
    verifier.validate_test_source_identity(ROOT, identity)

  def test_missing_transitive_helper_is_rejected(self):
    paths = tuple(path for path in production.TEST_SOURCE_PATHS
                  if path != "tests/stage10_v2_test_support.py")
    with self.assertRaises(production.ProductionNotVerifiable):
      production.validate_local_import_closure(ROOT, paths)

  def test_weakened_test_rehashed_package_is_rejected(self):
    snapshot = production.source_snapshot(ROOT, production.TEST_SOURCE_PATHS)
    weakened = copy.deepcopy(snapshot)
    weakened["members"][-1]["sha256"] = "0" * 64
    weakened["members_sha256"] = production.sha256_value(weakened["members"])
    with self.assertRaises(production.ProductionNotVerifiable):
      production.test_source_identity(ROOT, weakened, weakened)

  def test_same_count_replaced_member_is_rejected(self):
    snapshot = production.source_snapshot(ROOT, production.TEST_SOURCE_PATHS)
    changed = copy.deepcopy(snapshot)
    changed["members"][0]["path"] = "qmap/replaced.py"
    with self.assertRaises(production.ProductionNotVerifiable):
      production.test_source_identity(ROOT, snapshot, changed)

  def test_historical_five_sources_and_manifests_are_byte_unchanged(self):
    for manifest_name in (
        "capd_proactive_stage11_v2_generation_source_manifest.json",
        "capd_proactive_stage11_v2_verifier_source_manifest.json"):
      manifest = json.loads((ROOT / "configs/finals" / manifest_name).read_text(
          encoding="utf-8"))
      for member in manifest["members"]:
        raw = (ROOT / member["path"]).read_bytes()
        self.assertEqual(_sha_bytes(raw), member["sha256"])

  def test_production_modules_do_not_import_historical_contracts(self):
    forbidden = {
        "qmap.proactive_stage11_v2", "qmap.proactive_stage11_v2_guard",
        "qmap.proactive_stage11_v2_verifier",
        "scripts.run_capd_proactive_stage11_v2",
        "scripts.verify_capd_proactive_stage11_v2"}
    paths = [ROOT / path for path in (
        "qmap/proactive_stage11_v2_production.py",
        "qmap/proactive_stage11_v2_production_guard.py",
        "qmap/proactive_stage11_v2_production_verifier.py",
        "scripts/run_capd_proactive_stage11_v2_production.py",
        "scripts/verify_capd_proactive_stage11_v2_production.py")]
    imports = set()
    for path in paths:
      tree = ast.parse(path.read_text(encoding="utf-8"))
      for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
          imports.add(node.module)
          imports.update(node.module + "." + alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
          imports.update(alias.name for alias in node.names)
    self.assertFalse(imports & forbidden)


class FrozenTreeContinuityTest(unittest.TestCase):
  def test_snapshot_has_exact_five_roots(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, snapshot = _tree_fixture(Path(temporary))
      self.assertEqual(len(snapshot["roots"]), 5)
      self.assertFalse(snapshot["roots"][-1]["exists"])

  def test_pre_generation_check_precedes_mkdir(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      _, baseline = _tree_fixture(root / "trees")
      changed = copy.deepcopy(baseline)
      changed["roots"][0]["members"][0]["sha256"] = "0" * 64
      output = root / "run"
      with self.assertRaises(production.ProductionNotVerifiable):
        production.preflight_before_mkdir(
            output_dir=output, sealed_snapshot=baseline, current_snapshot=changed,
            config=_load_config(),
            externally_approved_plan_sha256=production.APPROVED_PLAN_SHA256,
            input_audit_receipt=_input_receipt(),
            authorization_receipt=_authorization(),
            input_audit_external_hashes=_external_hashes())
      self.assertFalse(output.exists())

  def test_pre_generation_drift_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      changed = copy.deepcopy(baseline)
      changed["roots"][0]["members"] = []
      with self.assertRaises(production.ProductionNotVerifiable):
        production.assert_continuity(baseline, changed, "sealed_vs_pre_generation")

  def test_post_generation_drift_prevents_seal(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      changed = copy.deepcopy(baseline)
      changed["roots"][1]["exists"] = False
      with self.assertRaises(production.ProductionNotVerifiable):
        production.assert_continuity(baseline, changed, "sealed_vs_post_generation")

  def test_pre_verification_drift_prevents_package(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      changed = copy.deepcopy(baseline)
      changed["roots"][2]["members"][0]["length"] += 1
      with self.assertRaises(verifier.VerificationError):
        verifier.compare_continuity(baseline, [("sealed_vs_pre_verification", changed)])

  def test_post_verification_drift_prevents_publish(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      changed = copy.deepcopy(baseline)
      changed["roots"][3]["members"][0]["path"] = "replacement.bin"
      with self.assertRaises(verifier.VerificationError):
        verifier.compare_continuity(baseline, [("sealed_vs_post_verification", changed)])

  def test_repository_revision_boolean_is_diagnostic_only(self):
    for value in (False, True):
      receipt = _input_receipt(value)
      production.validate_input_audit_receipt(
          receipt, expected_plan_sha256=production.APPROVED_PLAN_SHA256)
      self.assertEqual(receipt["current_live_replay_compatibility"], "NOT_VERIFIABLE")


class ProductionAuthorizationTest(unittest.TestCase):
  def test_approved_plan_external_sha_is_required(self):
    with self.assertRaises(production.ProductionNotVerifiable):
      production.validate_config(_load_config(), externally_approved_plan_sha256="")

  def test_input_audit_three_external_hashes_are_bound(self):
    authorization = _authorization()
    production.validate_execution_authorization(
        authorization, _load_config(), _input_receipt(),
        expected_plan_sha256=production.APPROVED_PLAN_SHA256,
        input_audit_external_hashes=_external_hashes())
    schema = json.loads((ROOT / "configs/finals" /
                         "capd_proactive_stage11_v2_production_execution_authorization_schema.json"
                         ).read_text(encoding="utf-8"))
    jsonschema.validate(authorization, schema)

  def test_test_identity_and_sealed_tree_are_bound(self):
    auth = _authorization()
    auth["sealed_frozen_tree_after_sha256"] = "0" * 64
    with self.assertRaises(production.ProductionContractError):
      production.validate_execution_authorization(
          auth, _load_config(), _input_receipt(),
          expected_plan_sha256=production.APPROVED_PLAN_SHA256,
          input_audit_external_hashes=_external_hashes())

  def test_synthetic_authorization_is_rejected(self):
    auth = _authorization()
    auth["synthetic_test_only"] = True
    with self.assertRaises(production.ProductionContractError):
      production.validate_execution_authorization(
          auth, _load_config(), _input_receipt(),
          expected_plan_sha256=production.APPROVED_PLAN_SHA256,
          input_audit_external_hashes=_external_hashes())

  def test_future_output_hashes_are_rejected(self):
    auth = _authorization()
    auth["generation_result_sha256"] = SHA
    with self.assertRaises(production.ProductionContractError):
      production.validate_execution_authorization(
          auth, _load_config(), _input_receipt(),
          expected_plan_sha256=production.APPROVED_PLAN_SHA256,
          input_audit_external_hashes=_external_hashes())


class ProductionGenerationTest(unittest.TestCase):
  def test_exact_192_row_cartesian_product(self):
    rows = production.generate_cost_rows(_jobs(), production.PROFILE_WEIGHTS)
    self.assertEqual(len(rows), 192)
    self.assertEqual(len({(r["source_job_id"], r["cost_profile"]) for r in rows}), 192)

  def test_duplicate_and_missing_pair_is_rejected(self):
    jobs = _jobs()
    rows = production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS)
    rows[-1] = copy.deepcopy(rows[0])
    with self.assertRaises(production.ProductionContractError):
      production.validate_result_rows(rows, jobs)

  def test_pressure_job_and_fifth_profile_are_rejected(self):
    jobs = _jobs()
    jobs[0]["track"] = "pressure"
    with self.assertRaises(production.ProductionContractError):
      production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS)
    profiles = copy.deepcopy(production.PROFILE_WEIGHTS)
    profiles["fifth"] = profiles["default"]
    with self.assertRaises(production.ProductionContractError):
      production.generate_cost_rows(_jobs(), profiles)

  def test_blocked_lanes_emit_no_numeric_rows(self):
    rows = production.generate_cost_rows(_jobs(), production.PROFILE_WEIGHTS)
    self.assertEqual({row["evidence_mode"] for row in rows},
                     {"offline_raw_counter_recompute"})
    self.assertTrue(all(lane not in row for lane in production.BLOCKED_LANES
                        for row in rows))

  def test_zero_access_uses_null_not_zero(self):
    jobs = _jobs()
    jobs[0]["raw_access_count"] = 0
    rows = production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS)
    selected = [row for row in rows if row["source_job_id"] == jobs[0]["job_id"]]
    self.assertTrue(all(row["weighted_cost_per_access"] is None for row in selected))

  def test_main_b_max_two_is_immutable(self):
    with self.assertRaises(production.ProductionContractError):
      production.generate_cost_rows(_jobs(), production.PROFILE_WEIGHTS, main_b_max=1)

  def test_generation_monitor_enforces_single_attempt_and_timeout(self):
    self.assertEqual(production.MONITORING_CONTRACT["attempt_count"], 1)
    self.assertFalse(production.MONITORING_CONTRACT["automatic_retry_performed"])
    self.assertEqual(production.MONITORING_CONTRACT["hard_timeout_seconds"], 1800)
    self.assertIn("process.poll()", (ROOT / "scripts/run_capd_proactive_stage11_v2_production.py").read_text(encoding="utf-8"))

  def test_generation_timeout_uses_fixed_termination_grace(self):
    self.assertEqual(production.MONITORING_CONTRACT, {
        "monitor_interval_seconds": 5, "hard_timeout_seconds": 1800,
        "termination_grace_seconds": 10, "attempt_count": 1,
        "automatic_retry_performed": False})
    source = (ROOT / "scripts/run_capd_proactive_stage11_v2_production.py").read_text(encoding="utf-8")
    self.assertIn("process.terminate()", source)
    self.assertIn("process.kill()", source)


class ProductionIndependentVerificationTest(unittest.TestCase):
  def test_verifier_has_no_generation_import(self):
    source = (ROOT / "qmap/proactive_stage11_v2_production_verifier.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
      if isinstance(node, ast.ImportFrom) and node.module:
        imports.append(node.module)
        imports.extend(node.module + "." + alias.name for alias in node.names)
    self.assertNotIn("qmap.proactive_stage11_v2_production", imports)
    self.assertNotIn("qmap.proactive_cost", imports)
    self.assertEqual(production.GENERATION_SOURCE_PATHS,
                     _approved_plan_whitelist("4.1"))
    self.assertEqual(verifier.GENERATION_SOURCE_PATHS,
                     production.GENERATION_SOURCE_PATHS)
    self.assertEqual(verifier.VERIFIER_SOURCE_PATHS,
                     _approved_plan_whitelist("4.2"))
    self.assertTrue(hasattr(verifier, "independent_stage8_source"))
    self.assertTrue(hasattr(verifier, "independent_stage9_receipt"))
    self.assertTrue(hasattr(verifier, "independent_stage10_receipt"))
    self.assertTrue(hasattr(verify_runner, "verify_input_audit"))

  def test_verifier_independently_recomputes_192_rows(self):
    jobs = _jobs()
    rows = production.generate_cost_rows(jobs, production.PROFILE_WEIGHTS)
    verifier.verify_result_rows(rows, jobs)

  def test_generation_continuity_bindings_are_exact(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      result = verifier.compare_continuity(
          baseline, [("sealed_vs_pre_generation", baseline),
                     ("sealed_vs_post_generation", baseline)])
      self.assertTrue(result["identical"])

    identity_fields = {
        "schema_version", "contract_id", "production_revision", "run_id",
        "approved_production_design_sha256",
        "approved_production_plan_sha256", "production_config_sha256",
        "production_result_schema_sha256", "input_audit_receipt_sha256",
        "input_audit_manifest_sha256", "input_audit_checksums_sha256",
        "execution_authorization_receipt_sha256",
        "execution_authorization_manifest_sha256",
        "execution_authorization_checksums_sha256",
        "generation_source_manifest_sha256",
        "generation_source_members_sha256",
        "verifier_source_manifest_sha256", "verifier_source_members_sha256",
        "stage8_input_receipt_sha256", "stage9_input_receipt_sha256",
        "stage10_input_receipt_sha256", "standard_source_manifest_sha256",
        "sorted_job_ids_sha256", "frozen_cost_profiles_sha256",
        "frozen_grid_sha256", "sealed_frozen_tree_after_sha256",
        "pre_generation_continuity_snapshot_sha256", "code_version",
        "source_snapshot_sha256", "expected_result_rows",
        "test_used_for_parameter_selection"}
    identity = {field: None for field in identity_fields}
    identity.pop("input_audit_manifest_sha256")
    payloads = {name: b"{}\n" for name in verifier.GENERATION_PAYLOADS}
    payloads["stage11_v2_config.json"] = verifier.canonical_json_bytes(
        json.loads((
            ROOT / "configs/finals/capd_proactive_stage11_v2_production.json"
            ).read_text(encoding="utf-8")))
    payloads["run_identity.json"] = verifier.canonical_json_bytes(identity)
    rehashed = verifier.package_bytes("generation", payloads)
    with self.assertRaisesRegex(
        verifier.VerificationError, "run identity field set mismatch"):
      verifier.validate_generation_identity_chain(ROOT, rehashed)

    input_payloads = {
        name: b"{}\n" for name in verifier.INPUT_AUDIT_PAYLOADS}
    input_package = verifier.package_bytes("input_audit", input_payloads)
    authorization_package = verifier.package_bytes(
        "execution_authorization",
        {"execution_authorization_receipt.json": b"{}\n"})
    payloads["input_audit_receipt.json"] = b'{"tampered":true}\n'
    payloads["execution_authorization_receipt.json"] = b"{}\n"
    rehashed = verifier.package_bytes("generation", payloads)
    input_hashes = {
        "receipt_sha256": verifier.sha256_bytes(
            input_package["input_audit_receipt.json"]),
        "manifest_sha256": verifier.sha256_bytes(input_package["manifest.json"]),
        "checksums_sha256": verifier.sha256_bytes(input_package["SHA256SUMS"])}
    authorization_hashes = {
        "receipt_sha256": verifier.sha256_bytes(
            authorization_package["execution_authorization_receipt.json"]),
        "manifest_sha256": verifier.sha256_bytes(
            authorization_package["manifest.json"]),
        "checksums_sha256": verifier.sha256_bytes(
            authorization_package["SHA256SUMS"])}
    with self.assertRaisesRegex(
        verifier.VerificationError, "embedded receipt differs"):
      verifier.validate_external_generation_inputs(
          rehashed, input_package, authorization_package,
          input_hashes=input_hashes,
          authorization_hashes=authorization_hashes)

  def test_verification_continuity_bindings_are_exact(self):
    with tempfile.TemporaryDirectory() as temporary:
      _, baseline = _tree_fixture(Path(temporary))
      result = verifier.compare_continuity(
          baseline, [("sealed_vs_pre_verification", baseline),
                     ("sealed_vs_post_verification", baseline)])
      self.assertEqual(len(result["comparisons"]), 2)

  def test_exact_seven_member_verification_package(self):
    payloads = {name: production.canonical_json_bytes({"fixture": name})
                for name in verifier.VERIFICATION_PAYLOADS}
    package = verifier.package_bytes("verification", payloads)
    verifier.verify_package(package, phase="verification",
                            payload_names=verifier.VERIFICATION_PAYLOADS)
    self.assertEqual(len(package), 7)

  def test_verification_monitor_enforces_single_attempt_and_timeout(self):
    self.assertEqual(verify_runner.MONITORING, {
        "monitor_interval_seconds": 5, "hard_timeout_seconds": 1800,
        "termination_grace_seconds": 10, "attempt_count": 1,
        "automatic_retry_performed": False})

  def test_wall_clock_diagnostics_are_excluded_from_result_equality(self):
    left = {"rows": [1], "monitoring": {"wall_clock_duration_seconds": 1}}
    right = {"rows": [1], "monitoring": {"wall_clock_duration_seconds": 99}}
    self.assertEqual(verifier.deterministic_result_view(left),
                     verifier.deterministic_result_view(right))


class ProductionReleaseGateTest(unittest.TestCase):
  def test_verification_stops_pending_final_approval(self):
    receipt = _verification_receipt()
    verifier.validate_verification_receipt(receipt)
    schema = json.loads((ROOT / "configs/finals" /
                         "capd_proactive_stage11_v2_production_verification_receipt_schema.json"
                         ).read_text(encoding="utf-8"))
    jsonschema.validate(receipt, schema)
    self.assertFalse(receipt["stage11_formally_verified"])

  def test_final_approval_requires_exact_external_binding(self):
    receipt = _final_approval()
    wrong = {"verification_receipt_sha256": "0" * 64,
             "verification_manifest_sha256": SHA,
             "verification_checksums_sha256": SHA}
    with self.assertRaises(verifier.VerificationError):
      verifier.validate_final_approval_receipt(receipt, wrong)

  def test_final_status_requires_complete_exact_chain(self):
    receipt = _final_status()
    hashes = {"final_approval_receipt_sha256": SHA,
              "final_approval_manifest_sha256": SHA,
              "final_approval_checksums_sha256": SHA}
    inherited = {"verification_receipt_sha256": SHA,
                 "generation_result_sha256": SHA}
    self.assertTrue(verifier.consume_final_status(
        receipt, final_approval_hashes=hashes, inherited_bindings=inherited))
    schema = json.loads((ROOT / "configs/finals" /
                         "capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json"
                         ).read_text(encoding="utf-8"))
    jsonschema.validate(receipt, schema)

  def test_rehashed_release_tamper_is_rejected(self):
    receipt = _final_status()
    receipt["run_id"] = "wrong-run"
    hashes = {"final_approval_receipt_sha256": SHA,
              "final_approval_manifest_sha256": SHA,
              "final_approval_checksums_sha256": SHA}
    with self.assertRaises(verifier.VerificationError):
      verifier.consume_final_status(
          receipt, final_approval_hashes=hashes,
          inherited_bindings={"generation_result_sha256": SHA})

  def test_no_gate_auto_issues_next_receipt(self):
    receipt = _verification_receipt()
    verifier.validate_verification_receipt(receipt)
    self.assertNotIn("final_approval_receipt_sha256", receipt)

  def test_verification_capability_cannot_write_final_packages(self):
    with tempfile.TemporaryDirectory() as temporary:
      guard.reset_test_nonce_registry()
      root = Path(temporary) / "verification"
      capability = guard.issue_capability(
          phase="verification", output_root=root, identity=production.RUN_ID,
          approved_plan_sha256=production.APPROVED_PLAN_SHA256,
          nonce="verification-nonce-0001", synthetic_test_only=True)
      with self.assertRaises(guard.ProductionPathError):
        guard.guarded_write_bytes(
            capability, phase="final_status", identity=production.RUN_ID,
            output_root=root, artifact="final_status_evidence_receipt.json",
            data=b"{}\n")

  def test_final_approval_capability_cannot_write_final_status(self):
    with tempfile.TemporaryDirectory() as temporary:
      guard.reset_test_nonce_registry()
      root = Path(temporary) / "approval"
      capability = guard.issue_capability(
          phase="final_approval", output_root=root, identity=production.RUN_ID,
          approved_plan_sha256=production.APPROVED_PLAN_SHA256,
          nonce="final-approval-nonce-01", synthetic_test_only=True)
      with self.assertRaises(guard.ProductionPathError):
        guard.guarded_write_bytes(
            capability, phase="final_status", identity=production.RUN_ID,
            output_root=root, artifact="final_status_evidence_receipt.json",
            data=b"{}\n")


def tearDownModule():
  if REAL_SUCCESSFUL_OPENS:
    raise AssertionError(
        "Fixture-only production suite opened real upstream: {}".format(
            REAL_SUCCESSFUL_OPENS))
