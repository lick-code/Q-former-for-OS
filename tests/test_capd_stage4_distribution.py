# coding=utf-8
"""Server tests for CAPD stage-4 G11 distribution identities."""

import inspect
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import stage4_common
from qmap import stage4_distribution
from scripts import run_capd_stage4 as stage4


class DistributionMetricTest(unittest.TestCase):

  def test_ks_identical_is_zero_and_disjoint_is_one(self):
    self.assertEqual(0.0, stage4_common.ks_statistic([1, 2], [1, 2]))
    self.assertEqual(1.0, stage4_common.ks_statistic([0, 0], [1, 1]))

  def test_quantiles_and_outside_range_ratio(self):
    self.assertEqual(2.5, stage4_common.quantile([1, 2, 3, 4], .5))
    result = stage4_common.distribution_distance([0, 1], [-1, .5, 2])
    self.assertAlmostEqual(2 / 3.0, result["outside_reference_range_ratio"])

  def test_wasserstein_matches_reference_quantile_sampling(self):
    left = [3, 0, 0, 9]
    right = [-1, 2, 2, 4, 10]
    count = max(len(left), len(right), 2)
    expected = sum(
        abs(stage4_common.quantile(left, index / float(count - 1)) -
            stage4_common.quantile(right, index / float(count - 1)))
        for index in range(count)) / float(count)
    self.assertAlmostEqual(
        expected, stage4_common.wasserstein_1(left, right), places=12)

  def test_distribution_metrics_are_linear_after_sorting(self):
    wasserstein_source = inspect.getsource(stage4_common.wasserstein_1)
    self.assertNotIn("quantile(left", wasserstein_source)
    self.assertNotIn("quantile(right", wasserstein_source)
    distance_source = inspect.getsource(stage4_common.distribution_distance)
    self.assertEqual(1, distance_source.count("min(reference)"))
    self.assertEqual(1, distance_source.count("max(reference)"))

  def test_ks_matches_simple_empirical_cdf_reference(self):
    left = [0, 0, 2, 4, 4]
    right = [-1, 0, 1, 4, 5, 5]
    points = sorted(set(left + right))
    expected = max(abs(
        sum(value <= point for value in left) / float(len(left)) -
        sum(value <= point for value in right) / float(len(right)))
                   for point in points)
    self.assertAlmostEqual(
        expected, stage4_common.ks_statistic(left, right), places=12)

  def test_binary_counts_and_ratio_difference(self):
    result = stage4_common.binary_distance([0, 1], [1, 1])
    self.assertEqual(1, result["reference"]["zero"])
    self.assertEqual(.5, result["one_ratio_difference"])

  def test_a_b_c_identities_cannot_be_mixed(self):
    empty = lambda name: {"identity": {"name": name}, "values": {}}
    with self.assertRaises(ValueError):
      stage4_distribution.audit_triplet(empty("B"), empty("A"), empty("C"))

  def test_feature_sampling_contract_is_explicit(self):
    self.assertEqual(5, len(stage4_distribution.SELECTOR_FEATURES))
    self.assertEqual(4, len(stage4_distribution.CANDIDATE_FEATURES))
    self.assertIn("decision_interval", stage4_distribution.DECISION_FEATURES)

  def test_first_decision_has_no_artificial_zero_interval(self):
    distribution = stage4_distribution._empty_distribution({"name": "A"})
    snapshot = {
        "pool_records": [{"selector_features": [0, 0, 0, 0, 0]}],
        "candidate_mask": [1],
        "candidate_state_features": [[0, 0, 0, 0]],
        "B_t": 1, "K_t": 1, "P_t": [1],
    }
    stage4_distribution._record(
        distribution, snapshot, set(), None, 10)
    self.assertEqual([], distribution["values"]["decision_interval"])
    stage4_distribution._record(
        distribution, snapshot, set(), 10, 14)
    self.assertEqual([4], distribution["values"]["decision_interval"])

  def test_g11_uses_fresh_spawned_processes_and_resumable_seed_partials(self):
    source = inspect.getsource(stage4.distribution_audit)
    self.assertIn("_run_distribution_processes", source)
    supervisor_source = inspect.getsource(stage4._run_distribution_processes)
    self.assertIn("multiprocessing.get_context(\"spawn\")", supervisor_source)
    self.assertIn("context.Process(", supervisor_source)
    self.assertIn("process.exitcode", supervisor_source)
    self.assertIn("process.terminate()", supervisor_source)
    self.assertNotIn("ProcessPoolExecutor", supervisor_source)
    worker_source = inspect.getsource(stage4._distribution_seed_job)
    self.assertIn("_write_json_atomic", worker_source)
    self.assertIn("[G11 END]", worker_source)

  def test_g11_releases_train_before_loading_valid(self):
    worker_source = inspect.getsource(stage4._distribution_seed_job)
    release = worker_source.index("del train_trace")
    valid_load = worker_source.index("valid_trace, _ = read_trace")
    self.assertLess(release, valid_load)
    self.assertIn("del valid_trace", worker_source)
    self.assertIn("gc.collect()", worker_source)

  def test_distribution_worker_count_is_configurable(self):
    args = stage4.build_parser().parse_args([
        "--stage", "distribution-audit", "--distribution-workers", "6"])
    self.assertEqual(6, args.distribution_workers)

  def test_resume_identity_ignores_orchestration_provenance(self):
    base = {key: "same" for key in stage4._DISTRIBUTION_RESUME_KEYS}
    left = dict(base, command="first", code_commit="one")
    right = dict(base, command="second", code_commit="two")
    left["code_fingerprint"] = "old-orchestrator"
    right["code_fingerprint"] = "new-orchestrator"
    self.assertEqual(stage4._distribution_resume_identity(left),
                     stage4._distribution_resume_identity(right))

  def test_legacy_partial_defaults_to_current_numeric_semantics(self):
    legacy = {key: "same" for key in stage4._DISTRIBUTION_RESUME_KEYS
              if key != "distribution_semantics_version"}
    current = dict(legacy, distribution_semantics_version=
                   stage4_distribution.NUMERIC_SEMANTICS_VERSION)
    self.assertEqual(stage4._distribution_resume_identity(legacy),
                     stage4._distribution_resume_identity(current))

  def test_changed_numeric_semantics_invalidates_partial(self):
    base = {key: "same" for key in stage4._DISTRIBUTION_RESUME_KEYS}
    changed = dict(base, distribution_semantics_version="future-v2")
    self.assertNotEqual(stage4._distribution_resume_identity(base),
                        stage4._distribution_resume_identity(changed))

  def test_partial_reuse_rejects_changed_checkpoint_identity(self):
    binding = {key: "same" for key in stage4._DISTRIBUTION_RESUME_KEYS}
    binding["test_trace_opened"] = False
    with tempfile.TemporaryDirectory() as directory:
      path = os.path.join(directory, "seed.json")
      stage4.finals_config.write_json(path, {
          "status": "COMPLETED", "test_trace_opened": False,
          "input_binding": binding, "comparisons": {"complete": True}})
      job = {"partial_path": path, "input_binding": binding}
      self.assertTrue(stage4._distribution_partial_matches(job))
      changed = dict(binding, checkpoint_fingerprint="changed")
      self.assertFalse(stage4._distribution_partial_matches({
          "partial_path": path, "input_binding": changed}))


if __name__ == "__main__":
  unittest.main()
