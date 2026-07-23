# coding=utf-8
"""Opt-in Linux-server miniature stage-5 execution-chain regression.

The fast default test audits the complete job matrix.  Set CAPD_STAGE5_E2E=1
on the Linux server to execute the torch-backed miniature chain in pytest's
temporary directory; no formal stage-5 path is used.
"""

import importlib.util
import csv
import json
import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from scripts import run_capd_stage5 as stage5
from qmap import finals_config
from qmap import finals_generator
from qmap import stage5_variants
from qmap.qmap_generator import read_trace


class Stage5PlanEndToEndTest(unittest.TestCase):

  def test_plan_has_full_required_matrix_without_duplicate_B8(self):
    args = stage5.build_parser().parse_args(["--stage", "plan"])
    stage5._resolve_paths(args)
    plan = stage5.build_execution_plan(args)
    self.assertEqual(27, plan["counts"]["main_replay"])
    self.assertEqual(90, plan["counts"]["core_ablation_training"])
    self.assertEqual(90, plan["counts"]["core_ablation_replay"])
    self.assertEqual(36, plan["counts"]["sensitivity_training"])
    self.assertEqual(348, plan["counts"]["required_experiment_jobs"])
    sensitivity_ids = {
        job.get("variant_id") for job in plan["jobs"]
        if job["stage"] == "sensitivity"}
    self.assertNotIn("sensitivity_B8", sensitivity_ids)
    self.assertIn("no_filter_B8_K8", {
        job.get("variant_id") for job in plan["jobs"]
        if job["stage"] == "ablations"})
    self.assertTrue(all(
        job["job_fingerprint"] for job in plan["jobs"]))
    self.assertTrue(all(
        job["dependency_fingerprints"] or job["input_fingerprints"]
        for job in plan["jobs"]))
    classical = [
        job for job in plan["jobs"]
        if job["stage"] == "main" and job.get("policy") in (
            "lru", "random", "lfu", "clock")]
    self.assertTrue(all(
        "--selector_params" not in job["argv"] and
        "--checkpoint" not in job["argv"] for job in classical))
    for variant_id in (
        "no_filter_B8_K8", "selector_drop_Delta",
        "no_position_encoding", "no_candidate_state",
        "history_mean_pool", "no_future_write"):
      self.assertEqual(
          18, len([
              job for job in plan["jobs"]
              if job.get("variant_id") == variant_id and
              job["kind"] in ("train", "replay")]))

  def test_resume_rejects_changed_output_content(self):
    with tempfile.TemporaryDirectory() as root:
      result_path = os.path.join(root, "result.json")
      job = {
          "result_path": result_path,
          "job_fingerprint": "job-fingerprint",
      }
      finals_config.write_json(result_path, {"value": 1})
      finals_config.write_json(
          stage5._job_manifest_path(None, job), {
              "status": "COMPLETED",
              "job_fingerprint": "job-fingerprint",
              "result_fingerprint": finals_config.fingerprint_file(
                  result_path),
          })
      self.assertTrue(stage5._job_is_complete(job))
      finals_config.write_json(result_path, {"value": 2})
      self.assertFalse(stage5._job_is_complete(job))


@unittest.skipUnless(os.environ.get("CAPD_STAGE5_E2E") == "1",
                     "server-only: set CAPD_STAGE5_E2E=1")
class Stage5TorchMiniEndToEndTest(unittest.TestCase):

  def test_full_baselines_and_structural_variants_use_only_tmp_path(self):
    # Reuse the established non-trivial stage-1 trace fixture, but execute the
    # stage-5-specific two-seed Full/baseline/variant matrix below.
    fixture_path = os.path.join(
        PROJECT_ROOT, "tests", "test_capd_stage1_v3_end_to_end.py")
    spec = importlib.util.spec_from_file_location(
        "capd_stage1_e2e_fixture_for_stage5", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module.FinalsV3MiniEndToEndTest()
    run_command = module.run_command
    with tempfile.TemporaryDirectory() as root:
      config_path = helper._prepare_config(root)
      generated = helper._run_once(
          config_path, os.path.join(root, "full_bootstrap"))
      results = [generated["result"]]

      # Full uses two distinct miniature model seeds.
      for seed in (11, 12):
        checkpoint_dir = os.path.join(root, "full", "seed_{}".format(seed))
        result = os.path.join(root, "full", "seed_{}.json".format(seed))
        run_command([
            sys.executable, "-m", "qmap.qmap_train",
            "--config", config_path,
            "--selector_params", generated["selector"],
            "--train_data", generated["train_jsonl"],
            "--valid_data", generated["valid_jsonl"],
            "--output_dir", checkpoint_dir, "--device", "cpu",
            "--seed", str(seed)])
        run_command([
            sys.executable, "-m", "qmap.qmap_eval",
            "--config", config_path, "--policy", "qmap",
            "--selector_params", generated["selector"],
            "--checkpoint", os.path.join(checkpoint_dir, "qmap_best.pth"),
            "--device", "cpu", "--json_output", result])
        results.append(result)

      # Required external baselines use the exact same miniature test trace.
      for policy in ("lru", "random", "lfu", "clock"):
        result = os.path.join(root, "baselines", "{}.json".format(policy))
        command = [
            sys.executable, "-m", "qmap.qmap_eval",
            "--config", config_path, "--policy", policy,
            "--json_output", result]
        if policy == "random":
          command.extend(["--stage5_replay_seed", "0"])
        run_command(command)
        results.append(result)

      base_config = finals_config.load_config(
          config_path, require_resolved=True, verify_manifest_files=False)
      base_selector = finals_config.load_json(generated["selector"])
      loo_csv = os.path.join(root, "mini_stage3_ablation.csv")
      with open(loo_csv, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=(
            "workload", "B", "kind", "feature", "run_status",
            "Delta", "A", "W", "C", "R"))
        writer.writeheader()
        writer.writerow({
            "workload": "mini_stage1", "B": 64,
            "kind": "leave_one_out", "feature": "Delta",
            "run_status": "PASSED", "Delta": 0.0,
            "A": 0.25, "W": 0.25, "C": 0.25, "R": 0.25,
        })
      for variant_id in (
          "no_filter_B8_K8", "selector_drop_Delta", "no_position_encoding",
          "history_mean_pool", "no_future_write"):
        spec = stage5_variants.get_variant_spec(variant_id)
        config = stage5_variants.build_variant_config(base_config, spec)
        variant_root = os.path.join(root, "variants", variant_id)
        os.makedirs(variant_root)
        variant_config_path = os.path.join(
            variant_root, "resolved_config.json")
        selector_path = os.path.join(variant_root, "selector_params.json")
        train_path = os.path.join(variant_root, "train.jsonl")
        valid_path = os.path.join(variant_root, "valid.jsonl")
        finals_config.write_json(variant_config_path, config)
        if stage5_variants.variant_requires_fresh_selector(spec):
          finals_generator.fit_selector_and_generate(
              type("Args", (), {
                  "config": variant_config_path,
                  "selector_output": selector_path,
                  "validation_samples_output": os.path.join(
                      variant_root, "selector_validation.jsonl"),
                  "train_output": train_path,
                  "valid_output": valid_path,
                  "summary_output": os.path.join(
                      variant_root, "generator_summary.json"),
                  "page_shift": None})())
        else:
          selector = stage5_variants.build_bound_selector(
              base_selector, config, spec,
              stage3_ablation_csv=(
                  loo_csv if variant_id == "selector_drop_Delta" else None),
              command="stage5-mini-e2e")
          finals_config.write_json(selector_path, selector)
          for split, output in (("train", train_path), ("valid", valid_path)):
            trace_path = config["data"]["{}_trace".format(split)]
            trace, _ = read_trace(
                trace_path, int(config["trace"]["page_shift"]))
            finals_generator.generate_reranker_jsonl(
                trace, trace_path, split, output, config, selector,
                variant_config_path, "stage5-mini-e2e", holdout=None)
        checkpoint_dir = os.path.join(variant_root, "seed_11")
        result = os.path.join(variant_root, "result.json")
        run_command([
            sys.executable, "-m", "qmap.qmap_train",
            "--config", variant_config_path,
            "--selector_params", selector_path,
            "--train_data", train_path, "--valid_data", valid_path,
            "--output_dir", checkpoint_dir, "--device", "cpu",
            "--seed", "11"])
        run_command([
            sys.executable, "-m", "qmap.qmap_eval",
            "--config", variant_config_path, "--policy", "qmap",
            "--selector_params", selector_path,
            "--checkpoint", os.path.join(checkpoint_dir, "qmap_best.pth"),
            "--device", "cpu", "--json_output", result])
        results.append(result)

      fingerprints = set()
      for result_path in results:
        self.assertTrue(result_path.startswith(root))
        with open(result_path, "r", encoding="utf-8") as input_file:
          result = json.load(input_file)
        self.assertEqual(
            result["total_accesses"], result["hits"] + result["misses"])
        fingerprints.add(result["test_trace_fingerprint"])
      self.assertEqual(1, len(fingerprints))


if __name__ == "__main__":
  unittest.main()
