# coding=utf-8
"""CAPD stage-4 frozen-reranker training and closed-loop audit driver.

Only train/valid traces are opened. Stage-2/3 outputs are immutable inputs;
all generated data, checkpoints, and audit results use stage-4 directories.
"""

from __future__ import print_function

import argparse
from concurrent.futures import as_completed
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import multiprocessing
import os
import shlex
import subprocess
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import finals_data
from qmap import stage4_common
from qmap import stage4_counterfactual
from qmap import stage4_distribution
from qmap.finals_generator import generate_reranker_jsonl
from qmap.qmap_generator import read_trace


STAGES = ("audit-inputs", "generate", "train", "counterfactual-audit",
          "distribution-audit", "summarize", "all")


def _write_json(path, value):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  finals_config.write_json(path, value)


def _write_json_atomic(path, value):
  temporary = "{}.tmp.{}".format(path, os.getpid())
  _write_json(temporary, value)
  os.replace(temporary, path)


def _command():
  return " ".join(shlex.quote(value) for value in sys.argv)


def _git_commit(repo_root):
  return subprocess.check_output(
      ["git", "rev-parse", "HEAD"], cwd=repo_root,
      universal_newlines=True).strip()


def _code_fingerprint(repo_root):
  paths = (
      "scripts/run_capd_stage4.py", "qmap/stage4_common.py",
      "qmap/stage4_counterfactual.py", "qmap/stage4_distribution.py",
      "qmap/qmap_train.py", "qmap/qmap_eval.py",
      "qmap/finals_generator.py", "qmap/candidate_filter.py")
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(repo_root, path))
      for path in paths})


def _is_ancestor(repo_root, older):
  if not older or older == "unknown":
    return False
  return subprocess.call(
      ["git", "merge-base", "--is-ancestor", older, "HEAD"],
      cwd=repo_root, stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL) == 0


def _paths(args, workload):
  stage2 = os.path.join(args.artifact_root, workload, "B64")
  generated = os.path.join(args.generated_root, workload, "B64")
  return {
      "stage2": stage2, "generated": generated,
      "config": os.path.join(stage2, "resolved_config.json"),
      "selector": os.path.join(stage2, "selector_params.json"),
      "stage2_summary": os.path.join(stage2, "generator_summary.json"),
      "selector_samples": os.path.join(
          stage2, "selector_validation_samples.jsonl"),
      "train_jsonl": os.path.join(generated, "train.jsonl"),
      "valid_jsonl": os.path.join(generated, "valid.jsonl"),
  }


def _require_fixed_scope(args):
  stage4_common.require(tuple(args.workloads) == stage4_common.WORKLOADS,
                        "official stage4 requires the three frozen workloads")
  stage4_common.require(tuple(args.seeds) == stage4_common.SEEDS,
                        "official stage4 requires seeds 3136859,42,2026")
  for path in (args.generated_root, args.checkpoint_root, args.output_root):
    lowered = os.path.abspath(path).lower()
    stage4_common.require("finals_v2" not in lowered and "smoke" not in lowered,
                          "stage4 rejects v2/smoke output paths")
  for workload in args.workloads:
    stage2 = os.path.abspath(os.path.join(
        args.artifact_root, workload, "B64"))
    for path in (args.generated_root, args.checkpoint_root, args.output_root):
      stage4_common.require(
          os.path.commonpath([stage2, os.path.abspath(path)]) != stage2,
          "stage4 output cannot be inside a stage2 B64 directory")


def audit_inputs(args, write=True):
  _require_fixed_scope(args)
  stage3_summary_path = os.path.join(args.stage3_root, "stage3_summary.json")
  stage3_metrics = os.path.join(args.stage3_root, "stage3_metrics.csv")
  stage3_ablation = os.path.join(args.stage3_root, "stage3_ablation.csv")
  stage3_audit = os.path.join(args.stage3_root, "input_audit.json")
  for path in (stage3_summary_path, stage3_metrics, stage3_ablation,
               stage3_audit, args.stage3_conformance):
    stage4_common.require(os.path.isfile(path), "missing input: {}".format(path))
  stage3_summary = stage4_common.load_json(stage3_summary_path)
  stage3_input_audit = stage4_common.load_json(stage3_audit)
  with open(args.stage3_conformance, "r", encoding="utf-8") as input_file:
    stage3_evidence = input_file.read()
  stage4_common.require("状态：`STAGE3_VERIFIED`" in stage3_evidence,
                        "stage3 conformance evidence is not VERIFIED")
  stage4_common.require(stage3_input_audit.get("status") == "PASSED",
                        "stage3 input audit did not pass")
  stage4_common.require(stage3_summary.get("result_count") == 12,
                        "stage3 does not contain 12 frozen analyses")
  stage4_common.require(stage3_summary.get("K") == 8 and
                        64 in stage3_summary.get("pool_sizes_B", []),
                        "stage3 B/K identity mismatch")

  head = _git_commit(args.repo_root)
  inputs = []
  for workload in args.workloads:
    paths = _paths(args, workload)
    for name in ("config", "selector", "stage2_summary", "selector_samples"):
      stage4_common.require(os.path.isfile(paths[name]),
                            "missing stage2 {} for {}".format(name, workload))
    config = finals_config.load_config(
        paths["config"], require_resolved=True, project_root=args.repo_root,
        verify_manifest_files=False)
    selector = finals_config.load_json(paths["selector"])
    summary = finals_config.load_json(paths["stage2_summary"])
    stage4_common.require(config["schema_version"] == finals_config.SCHEMA_VERSION,
                          "stage4 rejects non-v3 schema")
    finals_config.validate_artifact_identity(config, selector, "selector")
    finals_config.validate_selector_params(config, selector)
    stage4_common.require(config["run_profile"] == "official" and
                          config["validation"]["artifact_class"] == "official",
                          "stage4 accepts official artifacts only")
    stage4_common.require(config["run"]["workload"] == workload,
                          "workload identity mismatch")
    stage4_common.require(int(config["candidate"]["pool_size_B"]) == 64 and
                          int(config["candidate"]["retained_K"]) == 8,
                          "stage4 requires B=64,K=8")
    weights = [float(selector[key]) for key in
               ("w_Delta", "w_A", "w_W", "w_C", "w_R")]
    stage4_common.require(weights == [.2] * 5,
                          "selector weights are not five exact 0.2 values")
    stage4_common.require(selector.get("fallback_uniform") is False,
                          "stage4 rejects fallback-uniform selector")
    selector_fp = finals_config.selector_fingerprint(selector)
    config_fp = finals_config.config_fingerprint(config)
    stage4_common.require(
        summary.get("selector_fingerprint") == selector_fp and
        summary.get("train_metadata", {}).get("selector_fingerprint") ==
        selector_fp and
        summary.get("valid_metadata", {}).get("selector_fingerprint") ==
        selector_fp,
        "stage2 generator summary selector binding mismatch")
    stage4_common.require(
        summary.get("train_metadata", {}).get("config_fingerprint") ==
        config_fp and
        summary.get("valid_metadata", {}).get("config_fingerprint") ==
        config_fp,
        "stage2 generator summary config binding mismatch")
    stage3_binding = next((item for item in stage3_summary["input_bindings"]
                           if item["workload"] == workload and item["B"] == 64),
                          None)
    stage4_common.require(stage3_binding and
                          stage3_binding["selector_fingerprint"] == selector_fp,
                          "stage2/stage3 selector fingerprint mismatch")
    manifest_path = config["data"]["source_manifest"]
    manifest_absolute = finals_data.resolve_path(manifest_path, args.repo_root)
    manifest = finals_data.load_source_manifest(
        manifest_path, args.repo_root, verify_files=False,
        require_quality_pass=True, expected_workload=workload)
    manifest_fingerprint = config["run"]["source_manifest_fingerprint"]
    finals_config.assert_independent_trace_sources(
        config, source_manifest=manifest, project_root=args.repo_root)
    for split in ("train", "valid"):
      stage4_common.require(
          finals_config.fingerprint_file(config["data"][split + "_trace"]) ==
          config["data"]["split_fingerprints"][split],
          "{} trace fingerprint mismatch".format(split))
    stage4_common.require(
        _is_ancestor(args.repo_root, selector.get("git_commit")) and
        _is_ancestor(args.repo_root, stage3_summary.get("code_commit")),
        "HEAD is not a descendant of stage2/stage3 generation commits")
    inputs.append({
        "workload": workload, "B": 64, "K": 8,
        "config_fingerprint": config_fp,
        "selector_path": stage4_common.portable(paths["selector"], args.repo_root),
        "selector_fingerprint": selector_fp,
        "source_manifest_path": stage4_common.portable(
            manifest_absolute, args.repo_root),
        "source_manifest_fingerprint": manifest_fingerprint,
        "source_manifest_provenance_identity":
            finals_data.manifest_source_identity(manifest),
        "source_manifest_file_sha256": finals_config.fingerprint_file(
            manifest_absolute),
        "split_fingerprints": dict(config["data"]["split_fingerprints"]),
        "stage2_generator_summary_fingerprint": finals_config.fingerprint_file(
            paths["stage2_summary"]),
    })
  audit = {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "run_profile": "official", "artifact_class": "official",
      "status": "PASSED", "code_commit": head, "command": _command(),
      "code_fingerprint": _code_fingerprint(args.repo_root),
      "stage3_status": "STAGE3_VERIFIED",
      "stage3_summary_fingerprint": finals_config.fingerprint_file(
          stage3_summary_path),
      "stage3_conformance_fingerprint": finals_config.fingerprint_file(
          args.stage3_conformance),
      "inputs": inputs,
      "opened_trace_roles": ["train", "valid"],
      "test_trace_opened": False,
      "forbidden_inputs": ["test trace", "v2", "smoke", "B!=64"],
  }
  if write:
    path = os.path.join(args.output_root, "input_audit.json")
    _write_json(path, audit)
  return audit


def generate(args):
  audit = audit_inputs(args, write=False)
  for workload in args.workloads:
    paths = _paths(args, workload)
    os.makedirs(paths["generated"], exist_ok=True)
    config = finals_config.load_config(
        paths["config"], require_resolved=True, project_root=args.repo_root,
        verify_manifest_files=False)
    selector = finals_config.load_json(paths["selector"])
    train_path = config["data"]["train_trace"]
    valid_path = config["data"]["valid_trace"]
    train_trace, _ = read_trace(train_path, int(config["trace"]["page_shift"]))
    valid_trace, _ = read_trace(valid_path, int(config["trace"]["page_shift"]))
    metadata = {}
    for split, trace, trace_path, output in (
        ("train", train_trace, train_path, paths["train_jsonl"]),
        ("valid", valid_trace, valid_path, paths["valid_jsonl"])):
      temporary_output = output + ".building.{}".format(os.getpid())
      stage4_common.require(
          not os.path.exists(temporary_output) and
          not os.path.exists(finals_config.metadata_path(temporary_output)),
          "stale stage4 build temporary exists: {}".format(temporary_output))
      item = generate_reranker_jsonl(
          trace, trace_path, split, temporary_output, config, selector,
          paths["config"], _command(), holdout=None)
      normalized_identity = stage4_common.normalized_jsonl_fingerprint(
          temporary_output)
      item.update({
          "stage4_schema": stage4_common.STAGE4_SCHEMA,
          "stage2_selector_path": stage4_common.portable(
              paths["selector"], args.repo_root),
          "stage2_selector_fingerprint": finals_config.selector_fingerprint(
              selector),
          "source_manifest": config["data"]["source_manifest"],
          "source_manifest_fingerprint": next(
              row["source_manifest_fingerprint"] for row in audit["inputs"]
              if row["workload"] == workload),
          "generator_code_commit": _git_commit(args.repo_root),
          "generator_code_fingerprint": _code_fingerprint(args.repo_root),
          "complete_future_window": "t+L<N; drop incomplete tail",
          "behavior_policy": "lru", "test_trace_opened": False,
          "normalized_data_fingerprint": normalized_identity["sha256"],
          "normalized_row_count": normalized_identity["row_count"],
      })
      old = os.path.join(paths["stage2"], split + ".jsonl")
      if os.path.isfile(old):
        comparison = stage4_common.assert_jsonl_semantically_equal(
            old, temporary_output,
            "stage2/stage4 {} {}".format(workload, split))
        item["stage2_semantic_comparison"] = {
            "status": "IDENTICAL", "method": "canonical_json_rows",
            "normalized_sha256": comparison["sha256"],
            "row_count": comparison["row_count"],
            "stage2_byte_sha256": finals_config.fingerprint_file(old),
            "stage4_byte_sha256": item["data_fingerprint"],
        }
      _write_json(finals_config.metadata_path(temporary_output), item)
      os.replace(temporary_output, output)
      os.replace(finals_config.metadata_path(temporary_output),
                 finals_config.metadata_path(output))
      metadata[split] = item
    summary = {
        "schema_version": stage4_common.STAGE4_SCHEMA,
        "contract_id": finals_config.CONTRACT_ID, "workload": workload,
        "B": 64, "K": 8, "selector_path": paths["selector"],
        "selector_fingerprint": finals_config.selector_fingerprint(selector),
        "train_metadata": metadata["train"],
        "valid_metadata": metadata["valid"],
        "test_trace_opened": False, "status": "GENERATED_UNVERIFIED",
    }
    _write_json(os.path.join(paths["generated"], "generator_summary.json"),
                summary)


def train(args):
  stage4_common.require(args.log_root,
                        "--log-root outside the repository is required")
  log_root = os.path.abspath(args.log_root)
  stage4_common.require(
      os.path.commonpath([args.repo_root, log_root]) != args.repo_root,
      "training logs must be outside the repository")
  os.makedirs(log_root, exist_ok=True)
  for workload in args.workloads:
    paths = _paths(args, workload)
    for seed in args.seeds:
      output = os.path.join(args.checkpoint_root, workload,
                            "seed_{}".format(seed))
      manifest_path = os.path.join(output, "checkpoint_manifest.json")
      if os.path.isfile(manifest_path):
        existing = stage4_common.load_json(manifest_path)
        expected_jsonl = {
            "train": finals_config.fingerprint_file(paths["train_jsonl"]),
            "valid": finals_config.fingerprint_file(paths["valid_jsonl"])}
        expected_config = finals_config.config_fingerprint(
            finals_config.load_json(paths["config"]))
        if (int(existing.get("seed", -1)) == seed and
            existing.get("jsonl_fingerprints") == expected_jsonl and
            existing.get("config_fingerprint") == expected_config and
            existing.get("selector_fingerprint") ==
            finals_config.selector_fingerprint(
                finals_config.load_json(paths["selector"])) and
            existing.get("selection_criterion") ==
            "minimum_valid_loss_only" and
            existing.get("nan_or_inf_detected") is False and
            os.path.isfile(os.path.join(output, "qmap_best.pth")) and
            existing.get("checkpoints", {}).get("best", {}).get(
                "fingerprint") == finals_config.fingerprint_file(
                    os.path.join(output, "qmap_best.pth"))):
          print("[reuse] workload={} seed={} checkpoint={}".format(
              workload, seed, output))
          continue
        raise ValueError(
            "existing checkpoint directory is incomplete or identity-mismatched: "
            "{}".format(output))
      if os.path.isdir(output):
        stage4_common.require(
            not os.listdir(output),
            "non-empty failed checkpoint directory requires inspection: {}".format(
                output))
      else:
        os.makedirs(output)
      command = [
          args.python, "-m", "qmap.qmap_train",
          "--config", paths["config"],
          "--selector_params", paths["selector"],
          "--train_data", paths["train_jsonl"],
          "--valid_data", paths["valid_jsonl"],
          "--output_dir", output, "--seed", str(seed)]
      if args.device:
        command.extend(["--device", args.device])
      log_path = os.path.join(
          log_root, "{}_seed_{}.log".format(workload, seed))
      started = time.time()
      with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        log.write("started_unix={}\ncommand={}\n".format(
            started, " ".join(shlex.quote(value) for value in command)))
        log.flush()
        try:
          completed = subprocess.run(
              command, cwd=args.repo_root, stdout=log,
              stderr=subprocess.STDOUT, timeout=args.training_timeout,
              check=False)
          return_code = completed.returncode
          timed_out = False
        except subprocess.TimeoutExpired:
          return_code = 124
          timed_out = True
        log.write("\nended_unix={}\nexit_code={}\ntimed_out={}\n".format(
            time.time(), return_code, str(timed_out).lower()))
      stage4_common.require(return_code == 0,
                            "training failed; preserved {}".format(log_path))
      manifest = stage4_common.load_json(os.path.join(
          output, "checkpoint_manifest.json"))
      stage4_common.require(int(manifest["seed"]) == seed,
                            "actual checkpoint seed mismatch")
      stage4_common.require(manifest["selection_criterion"] ==
                            "minimum_valid_loss_only",
                            "checkpoint selection did not use valid loss only")


def counterfactual_audit(args):
  details_root = os.path.join(args.output_root, "counterfactual_details")
  os.makedirs(details_root, exist_ok=True)
  summaries = {}
  input_bindings = []
  for workload in args.workloads:
    paths = _paths(args, workload)
    config = finals_config.load_config(
        paths["config"], require_resolved=True, project_root=args.repo_root,
        verify_manifest_files=False)
    selector = finals_config.load_json(paths["selector"])
    valid_trace, _ = read_trace(
        config["data"]["valid_trace"], int(config["trace"]["page_shift"]))
    decisions = stage4_counterfactual.audit_trace(
        valid_trace, config, selector)
    summaries[workload] = stage4_counterfactual.summarize(decisions)
    identity = {
        "schema_version": stage4_common.STAGE4_SCHEMA,
        "contract_id": finals_config.CONTRACT_ID, "workload": workload,
        "B": 64, "K": 8,
        "selector_path": stage4_common.portable(paths["selector"], args.repo_root),
        "selector_fingerprint": finals_config.selector_fingerprint(selector),
        "valid_trace_fingerprint": config["data"]["split_fingerprints"]["valid"],
        "source_manifest_fingerprint": selector.get(
            "source_manifest_fingerprint"),
        "config_fingerprint": finals_config.config_fingerprint(config),
        "code_commit": _git_commit(args.repo_root), "command": _command(),
        "code_fingerprint": _code_fingerprint(args.repo_root),
        "audit_input_scope": "independent_valid_trace_only",
        "test_trace_opened": False,
    }
    input_bindings.append(identity)
    detail_path = os.path.join(details_root, workload + ".jsonl")
    with open(detail_path, "w", encoding="utf-8", newline="\n") as output:
      for decision in decisions:
        row = dict(decision)
        row["identity"] = identity
        output.write(json.dumps(row, sort_keys=True) + "\n")
  macro = {}
  for variant in stage4_common.LABEL_VARIANTS:
    macro[variant] = {
        key: stage4_common.mean([summaries[w][variant][key]
                                for w in args.workloads
                                if summaries[w][variant][key] is not None])
        for key in ("spearman_mean", "top1_any_hit_rate", "ndcg_mean",
                    "cost_indistinguishable_ratio")
    }
  result = {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "run_profile": "official", "artifact_class": "official",
      "B": 64, "K": 8,
      "audit_scope": "independent_valid_trace_only",
      "test_trace_opened": False, "workloads": summaries,
      "input_bindings": input_bindings,
      "macro_average": macro,
      "macro_average_note": "Unweighted workload macro average; no micro average.",
      "status": "COMPUTED_UNVERIFIED",
  }
  _write_json(os.path.join(args.output_root, "counterfactual_summary.json"),
              result)
  with open(os.path.join(args.output_root, "counterfactual_report.md"), "w",
            encoding="utf-8", newline="\n") as output:
    output.write("# CAPD Stage 4 G12 Counterfactual Audit\n\n")
    output.write("Identity: CAPD-MIC-1.0 / capd_finals_v3_0 / official / "
                 "B=64 / K=8. Fingerprint bindings are in "
                 "counterfactual_summary.json and per-workload JSONL.\n\n")
    output.write("Valid trace only; no test read. Metrics diagnose proxy-label "
                 "consistency and are not system-performance claims.\n")
    output.write("\n| workload | variant | Spearman mean | top-1 any-hit | NDCG mean | indistinguishable |\n")
    output.write("|---|---|---:|---:|---:|---:|\n")
    for workload in args.workloads:
      for variant in stage4_common.LABEL_VARIANTS:
        row = summaries[workload][variant]
        output.write("| {} | {} | {} | {:.6f} | {:.6f} | {:.6f} |\n".format(
            workload, variant,
            "undefined" if row["spearman_mean"] is None else
            "{:.6f}".format(row["spearman_mean"]),
            row["top1_any_hit_rate"], row["ndcg_mean"],
            row["cost_indistinguishable_ratio"]))


_DISTRIBUTION_RESUME_KEYS = (
    "workload", "seed", "B", "K", "selector_fingerprint",
    "train_trace_fingerprint", "valid_trace_fingerprint",
    "source_manifest_fingerprint", "config_fingerprint",
    "checkpoint_fingerprint", "code_fingerprint", "audit_input_scope",
    "test_trace_opened")


def _distribution_resume_identity(binding):
  return {key: binding.get(key) for key in _DISTRIBUTION_RESUME_KEYS}


def _distribution_job_spec(args, workload, seed, code_commit,
                           code_fingerprint, command):
  paths = _paths(args, workload)
  config = finals_config.load_config(
      paths["config"], require_resolved=True, project_root=args.repo_root,
      verify_manifest_files=False)
  selector = finals_config.load_json(paths["selector"])
  checkpoint_directory = os.path.join(
      args.checkpoint_root, workload, "seed_{}".format(seed))
  checkpoint = os.path.join(checkpoint_directory, "qmap_best.pth")
  checkpoint_manifest = stage4_common.load_json(os.path.join(
      checkpoint_directory, "checkpoint_manifest.json"))
  checkpoint_fingerprint = finals_config.fingerprint_file(checkpoint)
  stage4_common.require(
      int(checkpoint_manifest["seed"]) == seed and
      checkpoint_manifest["checkpoints"]["best"]["fingerprint"] ==
      checkpoint_fingerprint,
      "distribution checkpoint seed/fingerprint mismatch")
  selector_fingerprint = finals_config.selector_fingerprint(selector)
  config_fingerprint = finals_config.config_fingerprint(config)
  stage4_common.require(
      checkpoint_manifest["selector_fingerprint"] == selector_fingerprint and
      checkpoint_manifest["config_fingerprint"] == config_fingerprint and
      checkpoint_manifest["jsonl_fingerprints"] == {
          "train": finals_config.fingerprint_file(paths["train_jsonl"]),
          "valid": finals_config.fingerprint_file(paths["valid_jsonl"])},
      "distribution checkpoint artifact binding mismatch")
  binding = {
      "workload": workload, "seed": seed, "B": 64, "K": 8,
      "selector_path": stage4_common.portable(paths["selector"], args.repo_root),
      "selector_fingerprint": selector_fingerprint,
      "train_trace_fingerprint": config["data"]["split_fingerprints"]["train"],
      "valid_trace_fingerprint": config["data"]["split_fingerprints"]["valid"],
      "source_manifest_fingerprint": selector.get(
          "source_manifest_fingerprint"),
      "config_fingerprint": config_fingerprint,
      "checkpoint_path": stage4_common.portable(checkpoint, args.repo_root),
      "checkpoint_fingerprint": checkpoint_fingerprint,
      "code_commit": code_commit, "command": command,
      "code_fingerprint": code_fingerprint,
      "audit_input_scope": "train_and_valid_trace_only",
      "test_trace_opened": False,
  }
  partial_path = os.path.join(
      args.output_root, "distribution_partials", workload,
      "seed_{}.json".format(seed))
  return {
      "repo_root": args.repo_root, "workload": workload, "seed": seed,
      "device": args.device, "config_path": paths["config"],
      "selector_path": paths["selector"], "checkpoint": checkpoint,
      "partial_path": partial_path, "input_binding": binding,
  }


def _distribution_partial_matches(job):
  path = job["partial_path"]
  if not os.path.isfile(path):
    return False
  try:
    partial = stage4_common.load_json(path)
  except (OSError, ValueError):
    return False
  return (
      partial.get("status") == "COMPLETED" and
      partial.get("test_trace_opened") is False and
      _distribution_resume_identity(partial.get("input_binding", {})) ==
      _distribution_resume_identity(job["input_binding"]) and
      isinstance(partial.get("comparisons"), dict))


def _distribution_seed_job(job):
  started = time.time()
  workload = job["workload"]
  seed = int(job["seed"])
  os.environ.setdefault("OMP_NUM_THREADS", "1")
  os.environ.setdefault("MKL_NUM_THREADS", "1")
  import torch
  torch.set_num_threads(1)
  try:
    torch.set_num_interop_threads(1)
  except RuntimeError:
    pass
  device = job["device"] or (
      "cuda" if torch.cuda.is_available() else "cpu")
  print("[G11 START] workload={} seed={} pid={} device={}".format(
      workload, seed, os.getpid(), device), flush=True)
  config = finals_config.load_config(
      job["config_path"], require_resolved=True,
      project_root=job["repo_root"], verify_manifest_files=False)
  selector = finals_config.load_json(job["selector_path"])
  train_trace, _ = read_trace(
      config["data"]["train_trace"], int(config["trace"]["page_shift"]))
  valid_trace, _ = read_trace(
      config["data"]["valid_trace"], int(config["trace"]["page_shift"]))
  dist_a = stage4_distribution.collect_lru(
      train_trace, config, selector, "A")
  dist_b = stage4_distribution.collect_lru(
      valid_trace, config, selector, "B")
  dist_c = stage4_distribution.collect_capd(
      valid_trace, config, selector, job["checkpoint"], seed, device)
  comparisons = stage4_distribution.audit_triplet(dist_a, dist_b, dist_c)
  partial = {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "status": "COMPLETED", "workload": workload, "seed": seed,
      "input_binding": job["input_binding"], "comparisons": comparisons,
      "duration_seconds": time.time() - started,
      "test_trace_opened": False,
  }
  _write_json_atomic(job["partial_path"], partial)
  print("[G11 END] workload={} seed={} seconds={:.1f} partial={}".format(
      workload, seed, partial["duration_seconds"], job["partial_path"]),
        flush=True)
  return job["partial_path"]


def distribution_audit(args):
  total_jobs = len(args.workloads) * len(args.seeds)
  stage4_common.require(1 <= args.distribution_workers <= total_jobs,
                        "distribution workers must be in [1, {}]".format(
                            total_jobs))
  code_commit = _git_commit(args.repo_root)
  code_fingerprint = _code_fingerprint(args.repo_root)
  command = _command()
  jobs = [
      _distribution_job_spec(
          args, workload, seed, code_commit, code_fingerprint, command)
      for workload in args.workloads for seed in args.seeds]
  pending = [job for job in jobs if not _distribution_partial_matches(job)]
  reused = total_jobs - len(pending)
  print("[G11 PLAN] jobs={} workers={} reused={} pending={} device={}".format(
      total_jobs, args.distribution_workers, reused, len(pending),
      args.device or "auto"), flush=True)
  completed = reused
  if pending and args.distribution_workers == 1:
    for job in pending:
      _distribution_seed_job(job)
      completed += 1
      print("[G11 PROGRESS] completed={}/{}".format(
          completed, total_jobs), flush=True)
  elif pending:
    context = multiprocessing.get_context("spawn")
    worker_count = min(args.distribution_workers, len(pending))
    with ProcessPoolExecutor(
        max_workers=worker_count, mp_context=context) as executor:
      futures = {executor.submit(_distribution_seed_job, job): job
                 for job in pending}
      for future in as_completed(futures):
        future.result()
        completed += 1
        job = futures[future]
        print("[G11 PROGRESS] completed={}/{} workload={} seed={}".format(
            completed, total_jobs, job["workload"], job["seed"]), flush=True)

  details = {workload: {} for workload in args.workloads}
  metric_rows = []
  input_bindings = []
  for job in jobs:
    stage4_common.require(
        _distribution_partial_matches(job),
        "missing or stale G11 partial: {}".format(job["partial_path"]))
    partial = stage4_common.load_json(job["partial_path"])
    workload = job["workload"]
    seed = int(job["seed"])
    comparisons = partial["comparisons"]
    details[workload][str(seed)] = comparisons
    input_bindings.append(partial["input_binding"])
    for comparison, features in comparisons.items():
      for feature, metrics in features.items():
        metric_rows.append({
            "workload": workload, "seed": seed,
            "comparison": comparison, "feature": feature,
            "ks": metrics["ks"],
            "warning": metrics.get("warning", "binary"),
            "outside_train_range_ratio": metrics.get(
                "outside_reference_range_ratio"),
        })
  aggregates = {}
  for workload in args.workloads:
    aggregates[workload] = {}
    for comparison in next(iter(details[workload].values())):
      aggregates[workload][comparison] = {}
      for feature in next(iter(details[workload].values()))[comparison]:
        values = [details[workload][str(seed)][comparison][feature]["ks"]
                  for seed in args.seeds]
        aggregates[workload][comparison][feature] = {
            "seed_mean": stage4_common.mean(values),
            "seed_sample_std": stage4_common.sample_std(values),
            "seed_min": min(values), "seed_max": max(values)}
  review_required = any(float(row["ks"]) >= .2 for row in metric_rows)
  result = {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "run_profile": "official", "artifact_class": "official",
      "B": 64, "K": 8,
      "distribution_definitions": {
          "A": "train trace + LRU behavior policy",
          "B": "valid trace + LRU behavior policy",
          "C": "valid trace + per-seed CAPD closed-loop policy"},
      "sampling_units": {
          "selector_features": "valid P_t pages",
          "candidate_features": "valid C_t candidates",
          "decision_features": "decision points"},
      "test_trace_opened": False, "workloads": details,
      "seed_aggregates": aggregates, "input_bindings": input_bindings,
      "distribution_workers": args.distribution_workers,
      "code_commit": code_commit, "command": command,
      "code_fingerprint": code_fingerprint,
      "review_required": review_required,
      "status": "COMPUTED_UNVERIFIED",
  }
  _write_json(os.path.join(args.output_root, "distribution_summary.json"),
              result)
  csv_path = os.path.join(args.output_root, "distribution_metrics.csv")
  with open(csv_path, "w", encoding="utf-8", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=list(metric_rows[0]))
    writer.writeheader()
    writer.writerows(metric_rows)
  with open(os.path.join(args.output_root, "distribution_report.md"), "w",
            encoding="utf-8", newline="\n") as output:
    output.write("# CAPD Stage 4 G11 Distribution Audit\n\n")
    output.write("Identity: CAPD-MIC-1.0 / capd_finals_v3_0 / official / "
                 "B=64 / K=8. Per-workload/seed checkpoint, selector, trace, "
                 "config and manifest bindings are in distribution_summary.json.\n\n")
    output.write("A/C is total deployment shift, A/B split drift, B/C "
                 "policy-induced shift. KS 0.1/0.2 warnings are engineering "
                 "diagnostics, not significance tests or retraining triggers.\n")
    output.write("\n| workload | seed | comparison | feature | KS | warning |\n")
    output.write("|---|---:|---|---|---:|---|\n")
    for row in metric_rows:
      output.write("| {workload} | {seed} | {comparison} | {feature} | "
                   "{ks:.6f} | {warning} |\n".format(**row))


def summarize(args):
  for required in ("input_audit.json", "counterfactual_summary.json",
                   "distribution_summary.json"):
    path = os.path.join(args.output_root, required)
    stage4_common.require(os.path.isfile(path),
                          "missing stage4 audit artifact: {}".format(required))
    stage4_common.require(stage4_common.load_json(path).get(
        "test_trace_opened") is False,
        "stage4 audit does not prove test was unopened")
  rows = []
  for workload in args.workloads:
    paths = _paths(args, workload)
    expected_jsonl = {
        split: finals_config.fingerprint_file(paths[split + "_jsonl"])
        for split in ("train", "valid")}
    for seed in args.seeds:
      directory = os.path.join(args.checkpoint_root, workload,
                               "seed_{}".format(seed))
      manifest = stage4_common.load_json(os.path.join(
          directory, "checkpoint_manifest.json"))
      stage4_common.require(int(manifest["seed"]) == seed,
                            "checkpoint manifest seed mismatch")
      stage4_common.require(manifest["jsonl_fingerprints"] == expected_jsonl,
                            "seeds do not share frozen JSONL fingerprints")
      rows.append({
          "workload": workload, "seed": seed,
          "best_epoch": manifest["best_epoch"],
          "best_valid_loss": manifest["best_validation_loss"],
          "final_train_loss": manifest["final_train_loss"],
          "checkpoint_sha256": manifest["checkpoints"]["best"]["fingerprint"],
          "training_duration_seconds": manifest["training_duration_seconds"],
          "nan_or_inf_detected": manifest["nan_or_inf_detected"],
          "contract_id": finals_config.CONTRACT_ID,
          "artifact_schema": finals_config.SCHEMA_VERSION,
          "B": 64, "K": 8,
          "selector_path": stage4_common.portable(paths["selector"], args.repo_root),
          "selector_fingerprint": manifest["selector_fingerprint"],
          "train_trace_fingerprint": manifest["split_fingerprints"]["train"],
          "valid_trace_fingerprint": manifest["split_fingerprints"]["valid"],
          "source_manifest_fingerprint": manifest[
              "source_manifest_fingerprint"],
          "train_jsonl_fingerprint": manifest["jsonl_fingerprints"]["train"],
          "valid_jsonl_fingerprint": manifest["jsonl_fingerprints"]["valid"],
          "config_fingerprint": manifest["config_fingerprint"],
          "code_commit": manifest["git_commit"],
          "code_fingerprint": manifest["code_fingerprint"],
          "command": manifest["command"],
          "test_trace_opened": False,
      })
  csv_path = os.path.join(args.output_root, "stage4_training.csv")
  os.makedirs(args.output_root, exist_ok=True)
  with open(csv_path, "w", encoding="utf-8", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
  aggregates = {}
  for workload in args.workloads:
    current = [row for row in rows if row["workload"] == workload]
    aggregates[workload] = {}
    for metric in ("best_valid_loss", "final_train_loss"):
      values = [float(row[metric]) for row in current]
      aggregates[workload][metric] = {
          "mean": stage4_common.mean(values),
          "sample_std": stage4_common.sample_std(values),
          "min": min(values), "max": max(values)}
  summary = {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID,
      "artifact_schema": finals_config.SCHEMA_VERSION,
      "run_profile": "official", "artifact_class": "official",
      "B": 64, "K": 8,
      "status": "STAGE4_IMPLEMENTED_UNVERIFIED",
      "workloads": list(args.workloads), "seeds": list(args.seeds),
      "training_runs": len(rows), "training_aggregates": aggregates,
      "counterfactual_summary": "counterfactual_summary.json",
      "distribution_summary": "distribution_summary.json",
      "input_audit": "input_audit.json", "test_trace_opened": False,
      "code_commit": _git_commit(args.repo_root), "command": _command(),
      "code_fingerprint": _code_fingerprint(args.repo_root),
      "input_fingerprints": {
          name: finals_config.fingerprint_file(os.path.join(args.output_root, name))
          for name in ("input_audit.json", "counterfactual_summary.json",
                       "distribution_summary.json")},
      "prohibited_conclusions": (
          "No baseline comparison or end-to-end performance conclusion."),
  }
  _write_json(os.path.join(args.output_root, "stage4_summary.json"), summary)
  with open(os.path.join(args.output_root, "stage4_training_report.md"), "w",
            encoding="utf-8", newline="\n") as output:
    output.write("# CAPD Stage 4 Multi-seed Training\n\n")
    output.write("Identity: CAPD-MIC-1.0 / capd_finals_v3_0 / official / "
                 "B=64 / K=8. Full per-run bindings are in stage4_training.csv.\n\n")
    output.write("Nine independent models; best epoch selected only by valid loss. "
                 "These are stability diagnostics, not performance gains.\n")
    output.write("\n| workload | seed | best epoch | best valid loss | final train loss | seconds |\n")
    output.write("|---|---:|---:|---:|---:|---:|\n")
    for row in rows:
      output.write("| {workload} | {seed} | {best_epoch} | "
                   "{best_valid_loss:.8f} | {final_train_loss:.8f} | "
                   "{training_duration_seconds:.2f} |\n".format(**row))
    output.write("\nAggregates use the sample standard deviation across the three frozen seeds.\n")
  output_records = []
  for root, _, names in os.walk(args.output_root):
    for name in sorted(names):
      path = os.path.join(root, name)
      if name != "run_manifest.json":
        output_records.append({
            "path": stage4_common.portable(path, args.output_root),
            "sha256": finals_config.fingerprint_file(path)})
  output_records.sort(key=lambda item: item["path"])
  _write_json(os.path.join(args.output_root, "run_manifest.json"), {
      "schema_version": stage4_common.STAGE4_SCHEMA,
      "contract_id": finals_config.CONTRACT_ID, "artifact_schema":
          finals_config.SCHEMA_VERSION, "run_profile": "official",
      "artifact_class": "official", "B": 64, "K": 8,
      "command": _command(), "code_commit": _git_commit(args.repo_root),
      "code_fingerprint": _code_fingerprint(args.repo_root),
      "audit_input_scope": "train_and_valid_only",
      "test_trace_opened": False, "outputs": output_records})
  print("[FINAL] STAGE4_IMPLEMENTED_UNVERIFIED")


def build_parser():
  parser = argparse.ArgumentParser(description="Run isolated CAPD stage 4")
  parser.add_argument("--stage", choices=STAGES, required=True)
  parser.add_argument("--repo-root", default=PROJECT_ROOT)
  parser.add_argument("--artifact-root",
                      default="dataset/jsonl/finals_v3_official")
  parser.add_argument("--generated-root",
                      default="dataset/jsonl/finals_v3_official/stage4_reranker")
  parser.add_argument("--checkpoint-root", default=(
      "outputs/checkpoints/finals_v3_official/stage4_reranker"))
  parser.add_argument("--output-root", default=(
      "outputs/results/finals_v3_official/stage4_audits"))
  parser.add_argument("--stage3-root", default=(
      "outputs/results/finals_v3_official/stage3_selector"))
  parser.add_argument("--stage3-conformance", default=(
      "docs/CAPD_STAGE3_CONFORMANCE_REPORT_CN.md"))
  parser.add_argument("--workloads", nargs="+",
                      default=list(stage4_common.WORKLOADS))
  parser.add_argument("--seeds", nargs="+", type=int,
                      default=list(stage4_common.SEEDS))
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--device", default=None)
  parser.add_argument("--log-root", default=os.environ.get(
      "CAPD_STAGE4_LOG_ROOT"))
  parser.add_argument("--training-timeout", type=int, default=21600)
  parser.add_argument("--distribution-workers", type=int, default=int(
      os.environ.get("CAPD_STAGE4_DISTRIBUTION_WORKERS", "3")))
  return parser


def _absolute_args(args):
  if not os.path.isabs(args.repo_root):
    args.repo_root = os.path.abspath(args.repo_root)
  for name in ("artifact_root", "generated_root",
               "checkpoint_root", "output_root", "stage3_root",
               "stage3_conformance"):
    value = getattr(args, name)
    if not os.path.isabs(value):
      value = os.path.join(args.repo_root, value)
    setattr(args, name, os.path.abspath(value))
  return args


def main(argv=None):
  args = _absolute_args(build_parser().parse_args(argv))
  operations = {
      "audit-inputs": audit_inputs, "generate": generate, "train": train,
      "counterfactual-audit": counterfactual_audit,
      "distribution-audit": distribution_audit, "summarize": summarize}
  if args.stage == "all":
    for name in STAGES[:-1]:
      operations[name](args)
  else:
    operations[args.stage](args)
  return 0


if __name__ == "__main__":
  sys.exit(main())
