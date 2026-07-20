# coding=utf-8
"""Read-only consistency audit for the CAPD finals_v2.1 artifact matrix."""

from __future__ import print_function

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from scripts import run_finals_v2


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
POOL_SIZES = (8, 16, 32, 64)
POLICIES = ("qmap",) + run_finals_v2.CLASSICAL_BASELINES + (
    run_finals_v2.LEARNED_BASELINES)
BASELINE_SIGNATURE_FIELDS = (
    "total_accesses", "hits", "misses", "migrations", "nvm_reads",
    "nvm_writes", "weighted_access_cost")


def require_file(path):
  if not os.path.isfile(path):
    raise ValueError("Missing artifact: {}".format(path))
  return path


def audit_generated(config, paths):
  selector_path = require_file(paths["selector"])
  selector = finals_config.load_json(selector_path)
  config_fingerprint = finals_config.config_fingerprint(config)
  if selector.get("schema_version") != finals_config.LEGACY_SCHEMA_VERSION:
    raise ValueError("Selector schema mismatch.")
  if selector.get("workload") != config["run"]["workload"]:
    raise ValueError("Selector workload mismatch.")
  if selector.get("config_fingerprint") != config_fingerprint:
    raise ValueError("Selector config fingerprint mismatch.")
  holdout = finals_config.validate_decision_holdout(
      selector.get("decision_holdout", {}), config)
  if selector.get("decision_holdout_fingerprint") != holdout["fingerprint"]:
    raise ValueError("Selector holdout fingerprint mismatch.")

  validation_samples = require_file(paths["selector_validation"])
  if finals_config.fingerprint_file(validation_samples) != selector.get(
      "validation_samples_fingerprint"):
    raise ValueError("Selector validation samples fingerprint mismatch.")

  selector_fingerprint = finals_config.selector_fingerprint(selector)
  metadata = {}
  for split, path in (("train", paths["train_jsonl"]),
                      ("valid", paths["valid_jsonl"])):
    require_file(path)
    current = finals_config.load_jsonl_metadata(path)
    if current.get("split") != split:
      raise ValueError("{} JSONL split mismatch.".format(split))
    if current.get("source_partition") != "train_trace_decision_holdout":
      raise ValueError("{} JSONL source partition mismatch.".format(split))
    if current.get("config_fingerprint") != config_fingerprint:
      raise ValueError("{} JSONL config fingerprint mismatch.".format(split))
    if current.get("selector_fingerprint") != selector_fingerprint:
      raise ValueError("{} JSONL selector fingerprint mismatch.".format(
          split))
    if current.get("decision_holdout") != holdout:
      raise ValueError("{} JSONL holdout plan mismatch.".format(split))
    if current.get("source_trace_fingerprint") != selector.get(
        "train_trace_fingerprint"):
      raise ValueError("{} JSONL train trace mismatch.".format(split))
    count_key = ("train_decision_points" if split == "train"
                 else "validation_decision_points")
    if int(current.get("sample_count", 0)) != int(holdout[count_key]):
      raise ValueError("{} JSONL sample count mismatch.".format(split))
    candidate_metrics = current.get("candidate_filter_metrics", {})
    expected_B = int(config["candidate"]["pool_size_B"])
    expected_K = int(config["candidate"]["retained_K"])
    if (int(candidate_metrics.get("min_B_t", -1)) != expected_B or
        int(candidate_metrics.get("max_B_t", -1)) != expected_B):
      raise ValueError("{} JSONL did not realize B_t=B={}.".format(
          split, expected_B))
    if (int(candidate_metrics.get("min_K_t", -1)) != expected_K or
        int(candidate_metrics.get("max_K_t", -1)) != expected_K):
      raise ValueError("{} JSONL did not realize K_t=K={}.".format(
          split, expected_K))
    finals_config.assert_contract_matches(
        finals_config.contract_from_config(config),
        current.get("experiment_contract", {}), "{} JSONL".format(split))
    metadata[split] = current

  generator_summary = finals_config.load_json(
      require_file(paths["generator_summary"]))
  if generator_summary.get("decision_holdout") != holdout:
    raise ValueError("Generator summary holdout mismatch.")
  diagnostic = generator_summary.get("external_valid_trace_diagnostics", {})
  if diagnostic.get("role") != "diagnostic_only":
    raise ValueError("External valid trace is not diagnostic-only.")
  return {
      "decision_holdout": holdout,
      "train_samples": metadata["train"]["sample_count"],
      "valid_samples": metadata["valid"]["sample_count"],
      "external_valid_trace_diagnostics": diagnostic,
  }


def audit_complete(config, paths, generated):
  checkpoint_path = require_file(os.path.join(
      paths["checkpoint_dir"], "qmap_best.pth"))
  checkpoint_manifest = finals_config.load_json(require_file(os.path.join(
      paths["checkpoint_dir"], "checkpoint_manifest.json")))
  if checkpoint_manifest.get("schema_version") != finals_config.LEGACY_SCHEMA_VERSION:
    raise ValueError("Checkpoint manifest schema mismatch.")
  if checkpoint_manifest.get("config_fingerprint") != (
      finals_config.config_fingerprint(config)):
    raise ValueError("Checkpoint manifest config fingerprint mismatch.")
  if checkpoint_manifest.get("decision_holdout_fingerprint") != (
      generated["decision_holdout"]["fingerprint"]):
    raise ValueError("Checkpoint manifest holdout fingerprint mismatch.")
  if checkpoint_manifest.get("checkpoints", {}).get("best", {}).get(
      "fingerprint") != finals_config.fingerprint_file(checkpoint_path):
    raise ValueError("Best checkpoint fingerprint mismatch.")

  results = {}
  expected_contract = finals_config.contract_from_config(config)
  expected_config_fingerprint = finals_config.config_fingerprint(config)
  for policy in POLICIES:
    result_path = require_file(os.path.join(
        paths["result_dir"], "{}.json".format(policy)))
    result = finals_config.load_json(result_path)
    if result.get("policy") != policy:
      raise ValueError("{} result policy mismatch.".format(policy))
    if result.get("schema_version") != finals_config.LEGACY_SCHEMA_VERSION:
      raise ValueError("{} result schema mismatch.".format(policy))
    if result.get("config_fingerprint") != expected_config_fingerprint:
      raise ValueError("{} result config fingerprint mismatch.".format(
          policy))
    finals_config.assert_contract_matches(
        expected_contract, result.get("experiment_contract", {}),
        "{} result".format(policy))
    if policy == "qmap" and result.get(
        "decision_holdout_fingerprint") != generated[
            "decision_holdout"]["fingerprint"]:
      raise ValueError("QMAP result holdout fingerprint mismatch.")
    results[policy] = result

  summary = finals_config.load_json(require_file(paths["summary"]))
  if set(summary.get("results", {})) != set(POLICIES):
    raise ValueError("Per-job summary does not contain all policies.")
  manifest_index = finals_config.load_json(require_file(paths["manifest"]))
  stage_keys = set(manifest_index.get("stage_manifests", {}))
  if "all" not in stage_keys and not {"generate", "train", "eval"}.issubset(
      stage_keys):
    raise ValueError("Run manifests do not cover the complete pipeline.")
  return results


def baseline_signature(result):
  return tuple(result.get(key) for key in BASELINE_SIGNATURE_FIELDS)


def main():
  parser = argparse.ArgumentParser(
      description="Audit the frozen 3-workload x 4-B finals_v2.1 matrix.")
  parser.add_argument(
      "--config-dir", default="configs/finals/resolved_v2_1")
  parser.add_argument(
      "--stage", choices=("generated", "complete"), required=True)
  parser.add_argument("--output", default=None)
  args = parser.parse_args()

  jobs = []
  errors = []
  holdouts_by_workload = {}
  baseline_signatures = {}
  base = finals_config.load_config("configs/finals/capd_direction1.json")
  for workload in WORKLOADS:
    for pool_size in POOL_SIZES:
      config_path = os.path.join(
          args.config_dir, "{}_B{}.json".format(workload, pool_size))
      try:
        config = finals_config.load_config(
            require_file(config_path), require_resolved=True)
        paths = run_finals_v2.artifact_paths(config)
        generated = audit_generated(config, paths)
        holdouts_by_workload.setdefault(workload, set()).add(
            generated["decision_holdout"]["fingerprint"])
        job = {
            "workload": workload,
            "B": pool_size,
            "config": config_path,
            "train_samples": generated["train_samples"],
            "valid_samples": generated["valid_samples"],
            "decision_holdout_fingerprint": generated[
                "decision_holdout"]["fingerprint"],
        }
        if args.stage == "complete":
          results = audit_complete(config, paths, generated)
          job["results"] = {
              policy: {
                  "weighted_access_cost": result.get(
                      "weighted_access_cost"),
                  "hit_rate": result.get("hit_rate"),
              }
              for policy, result in results.items()
          }
          for policy in POLICIES[1:]:
            baseline_signatures.setdefault(
                (workload, policy), set()).add(
                    baseline_signature(results[policy]))
        jobs.append(job)
      except Exception as error:  # Audit must report the whole missing matrix.
        errors.append({
            "workload": workload,
            "B": pool_size,
            "error": str(error),
        })

  for workload, fingerprints in holdouts_by_workload.items():
    if len(fingerprints) != 1:
      errors.append({
          "workload": workload,
          "error": "Decision holdout differs across B.",
      })
  if args.stage == "complete":
    for (workload, policy), signatures in baseline_signatures.items():
      if len(signatures) != 1:
        errors.append({
            "workload": workload,
            "policy": policy,
            "error": "Native baseline metrics differ across B.",
        })

  report = {
      "schema_version": finals_config.LEGACY_SCHEMA_VERSION,
      "audit_stage": args.stage,
      "status": "passed" if not errors and len(jobs) == 12 else "failed",
      "expected_jobs": 12,
      "validated_jobs": len(jobs),
      "jobs": jobs,
      "errors": errors,
  }
  output = args.output or os.path.join(
      base["outputs"]["result_root"],
      "{}_audit.json".format(args.stage))
  finals_config.write_json(output, report)
  print("[{}] validated_jobs={}/12 report={}".format(
      report["status"], len(jobs), output))
  for error in errors:
    print("[error] {}".format(error))
  if report["status"] != "passed":
    raise SystemExit(1)


if __name__ == "__main__":
  main()
