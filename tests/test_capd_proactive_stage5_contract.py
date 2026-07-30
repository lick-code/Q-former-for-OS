# coding=utf-8

import copy
import inspect
import os
import tempfile
import unittest

from qmap import proactive_stage4
from qmap import proactive_stage5_contract as contract
from qmap import proactive_stage5_policies as policies


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "configs", "finals", "capd_proactive_stage5.json")


class ProactiveStage5ContractTest(unittest.TestCase):

  def setUp(self):
    self.config = contract.load_config(CONFIG_PATH)

  def test_frozen_parameters_and_formal_policy_table(self):
    self.assertEqual("stage5_implemented", self.config["stage_status"])
    self.assertEqual(8, self.config["frozen_method"]["F_low"])
    self.assertEqual(16, self.config["frozen_method"]["F_target"])
    self.assertEqual(4, self.config["frozen_method"]["b_max"])
    self.assertEqual(8, self.config["frozen_method"]["candidate_size_K"])
    self.assertEqual("disabled", self.config["frozen_method"]["selector"])
    self.assertEqual(
        list(contract.FORMAL_POLICIES),
        self.config["policies"]["formal_mainline"])
    self.assertNotIn("random", self.config["policies"]["formal_mainline"])
    self.assertNotIn("lfu", self.config["policies"]["formal_mainline"])

  def test_every_frozen_single_field_mutation_is_rejected(self):
    mutations = (
        ("frozen_method", "F_low", 7),
        ("frozen_method", "F_target", 15),
        ("frozen_method", "b_max", 3),
        ("frozen_method", "candidate_size_K", 64),
        ("frozen_method", "selector", "enabled"),
        ("frozen_method", "dram_working_set_ratio", 0.25),
        ("frozen_model", "lookahead_L", 512),
        ("frozen_model", "history_H", 10),
        ("frozen_model", "label_weights", [1, 1, 4]),
        ("frozen_model", "seeds", [3136859]),
    )
    for section, field, value in mutations:
      broken = copy.deepcopy(self.config)
      broken[section][field] = value
      with self.subTest(field=field):
        with self.assertRaises(contract.Stage5ContractError):
          contract.validate_config(broken)

  def test_stage4_verification_chain_reads_all_seed_bindings_without_pth(self):
    authority = contract.audit_stage4_authority(
        self.config, PROJECT_ROOT, require_checkpoints=False)
    self.assertEqual(
        list(contract.CAPD_SEEDS),
        [item["seed"] for item in authority["checkpoints"]])
    self.assertTrue(all(len(item["sha256"]) == 64
                        for item in authority["checkpoints"]))
    self.assertEqual("disabled", authority["selector_status"])
    self.assertFalse(authority["test_trace_opened"])

  def test_portable_absolute_checkpoint_resolution(self):
    frozen = proactive_stage4.load_json(os.path.join(
        PROJECT_ROOT, self.config["stage4_authority"]["freeze_candidate"]))
    recorded = frozen["final_checkpoints"][0]["path"]
    resolved = contract.resolve_repository_path(
        recorded, PROJECT_ROOT, ("outputs/capd_proactive_stage4",),
        must_exist=False)
    self.assertTrue(resolved.startswith(PROJECT_ROOT))
    self.assertTrue(resolved.replace("\\", "/").endswith(
        "checkpoints/seed_3136859/qmap_best.pth"))

  def test_path_resolution_rejects_escape_and_old_stage_tree(self):
    with self.assertRaises(contract.Stage5ContractError):
      contract.resolve_repository_path(
          "../../outside.pth", PROJECT_ROOT,
          ("outputs/capd_proactive_stage4",), must_exist=False)
    forbidden = (
        "outputs/results/finals_v3_official/stage4/run_manifest.json",
        "outputs/results/finals_v3_official/stage4_audits/report.json",
        "outputs/results/finals_v3_official/stage4-main/result.json",
        "outputs/results/finals_v3_official/stage5/run_manifest.json",
        "outputs/results/finals_v3_official/stage5_main/run_manifest.json",
        "outputs/results/finals_v3_official/stage5_ablation/result.json",
        "outputs/results/finals_v3_official/stage5.ablation/result.json",
        "stage4_audits/legacy.json",
    )
    for path in forbidden:
      with self.subTest(path=path):
        with self.assertRaises(contract.Stage5ContractError):
          contract.audit_no_legacy_stage_artifacts([path])
    contract.audit_no_legacy_stage_artifacts([
        "dataset/processed/finals_v3_official/canneal/valid.csv",
        "outputs/results/finals_v3_official/stage6/run_manifest.json",
    ])

  def test_tpp_is_registered_pending_and_never_falls_back(self):
    self.assertEqual(
        contract.PENDING_TPP, policies.POLICY_REGISTRY[
            "tpp_inspired"]["status"])
    with self.assertRaises(contract.PendingStage6Error):
      contract.assert_runnable_policy("tpp_inspired")
    pending = policies.TPPInspiredPendingPolicy()
    with self.assertRaises(contract.PendingStage6Error):
      pending.rank_candidates(None, [], [], {})

  def test_capd_adapter_has_no_trace_or_future_label_constructor_input(self):
    signature = inspect.signature(policies.CAPDRanker.__init__)
    self.assertNotIn("trace", signature.parameters)
    self.assertNotIn("labels", signature.parameters)

  def test_test_and_historical_policy_are_hard_rejected(self):
    for policy in ("random", "lfu", "reactive_capd", "old_capd"):
      with self.subTest(policy=policy):
        with self.assertRaises(contract.Stage5ContractError):
          contract.assert_runnable_policy(policy)
    with self.assertRaises(contract.Stage5ContractError):
      contract.audit_result({
          "schema_version": "capd_finals_v3_stage5_result",
          "status": "STAGE5_VERIFIED",
      })


if __name__ == "__main__":
  unittest.main()
