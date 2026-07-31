#!/usr/bin/env python3
# coding=utf-8
"""End-to-end CAPD proactive Stage-4 server driver.

Commands are idempotent when config, manifest, code, data, and artifact
fingerprints match.  Test traces are never accepted by this program.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import itertools
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Mapping, Sequence, Tuple


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import proactive_stage4


PHASES = ("lookahead", "label_weights", "candidate_history")


def _utc_now():
  return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _git_state(project_root):
  def command(*arguments):
    try:
      return subprocess.check_output(
          ["git", "-C", project_root] + list(arguments),
          stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
      return "unknown"
  commit = command("rev-parse", "HEAD")
  # Runtime outputs and deployment bundles must not change the source-code
  # identity. In particular, preflight writes into outputs before a resumed
  # invocation rechecks identity.
  source_scope = (
      ".", ":(exclude)outputs", ":(exclude)tmp",
      ":(exclude)*.patch", ":(exclude)*.tar.gz")
  dirty_override = os.environ.get("CAPD_DIRTY_WORKTREE")
  if dirty_override in ("true", "false"):
    status = (
        "explicit-dirty-worktree-override"
        if dirty_override == "true" else "")
    diff = status
  else:
    status = command(
        "status", "--porcelain", "--untracked-files=all", "--",
        *source_scope)
    diff = command(
        "diff", "--binary", "--no-ext-diff", "--", *source_scope)
  return {
      "commit": commit,
      "dirty_worktree": status not in ("", "unknown"),
      "dirty_status_sha256":
          proactive_stage4.fingerprint_value(status),
      "dirty_diff_sha256":
          proactive_stage4.fingerprint_value(diff),
  }


def _code_artifact_fingerprints(project_root):
  paths = (
      "qmap/proactive_stage4.py",
      "qmap/proactive_replay.py",
      "qmap/proactive_stage3.py",
      "qmap/proactive_cost.py",
      "qmap/finals_config.py",
      "qmap/no_vpn_ablation.py",
      "qmap/qmap_train.py",
      "qmap/qmap_eval.py",
      "qmap/qmap_generator.py",
      "policy_learning/cache_model/embed.py",
      "policy_learning/cache_model/model.py",
      "policy_learning/cache_model/qmap_loss.py",
      "scripts/prepare_capd_proactive_stage4_manifest.py",
      "scripts/run_capd_proactive_stage4.py",
  )
  return {
      path: proactive_stage4.fingerprint_file(
          os.path.join(project_root, path))
      for path in paths}


def _append_progress(run_root, event, **fields):
  path = os.path.join(run_root, "logs", "progress.jsonl")
  os.makedirs(os.path.dirname(path), exist_ok=True)
  row = {"created_at": _utc_now(), "event": event}
  row.update(fields)
  with open(path, "a", encoding="utf-8", newline="\n") as output:
    output.write(json.dumps(
        row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    output.flush()
    os.fsync(output.fileno())


def _load_authority(args):
  config = proactive_stage4.load_json(args.config)
  stage0 = proactive_stage4.load_json(args.stage0_config)
  stage3_default = proactive_stage4.load_json(args.stage3_default)
  proactive_stage4.validate_config(config, stage0, stage3_default)
  return config, stage0, stage3_default


def _run_root(args, config):
  if not args.run_id or any(
      character not in
      "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
      for character in args.run_id):
    raise ValueError("--run-id must be a non-empty filesystem-safe value.")
  root = os.path.abspath(os.path.join(
      args.project_root, config["output_root"], args.run_id))
  normalized = root.replace("\\", "/").lower()
  if "capd_proactive_stage4" not in normalized:
    raise ValueError("Run root lacks capd_proactive_stage4 identity.")
  if "finals_v3" in normalized or "stage4_audits" in normalized:
    raise ValueError("Historical Stage-4 output trees are forbidden.")
  return root


def _write_state(run_root, status, completed=None):
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "run_state.json"), {
          "schema_version": proactive_stage4.SCHEMA_VERSION,
          "status": status,
          "completed": list(completed or []),
          "updated_at": _utc_now(),
          "test_trace_opened": False,
      })


def preflight(args):
  config, stage0, stage3_default = _load_authority(args)
  run_root = _run_root(args, config)
  os.makedirs(os.path.join(run_root, "artifacts"), exist_ok=True)
  os.makedirs(os.path.join(run_root, "logs"), exist_ok=True)
  manifest, traces, entries = proactive_stage4.resolve_inputs(
      args.manifest, args.project_root)
  working_set = proactive_stage4.working_set_and_capacity(traces)
  resolved = copy.deepcopy(config)
  resolved.update({
      "stage_status": proactive_stage4.AWAITING_INPUTS,
      "run": {
          "run_id": args.run_id,
          "created_at": _utc_now(),
          "project_root": os.path.abspath(args.project_root),
          "output_directory": run_root,
          "input_manifest": os.path.abspath(args.manifest),
          "input_manifest_sha256":
              proactive_stage4.fingerprint_file(args.manifest),
          "code": _git_state(args.project_root),
      },
      "resolved_inputs": entries,
      "working_set": working_set,
  })
  identity = {
      "config_sha256": proactive_stage4.fingerprint_file(args.config),
      "stage0_sha256": proactive_stage4.fingerprint_file(args.stage0_config),
      "stage3_default_sha256":
          proactive_stage4.fingerprint_file(args.stage3_default),
      "manifest_sha256": proactive_stage4.fingerprint_file(args.manifest),
      "trace_sha256": {
          "{}:{}".format(entry["workload"], entry["split"]):
              entry["trace_sha256"] for entry in entries},
      "code": resolved["run"]["code"],
      "code_artifacts": _code_artifact_fingerprints(args.project_root),
  }
  identity["run_identity_sha256"] = proactive_stage4.fingerprint_value(
      identity)
  existing_identity_path = os.path.join(run_root, "run_identity.json")
  if os.path.isfile(existing_identity_path):
    existing = proactive_stage4.load_json(existing_identity_path)
    if existing != identity:
      raise ValueError(
          "Existing run_id has a different config/data/code identity.")
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "resolved_config.json"), resolved)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "input_manifest.json"), manifest)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "input_artifacts.json"), {"entries": entries})
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "working_set_summary.json"), working_set)
  proactive_stage4.write_json_atomic(existing_identity_path, identity)
  provenance = {
      "schema_version": "capd_proactive_stage4_provenance_v1_0",
      "contract_id": proactive_stage4.CONTRACT_ID,
      "run_id": args.run_id,
      "created_at": _utc_now(),
      "command": " ".join(sys.argv),
      "machine_information": {
          "platform": platform.platform(),
          "python": sys.version,
          "processor": platform.processor(),
      },
      "identity": identity,
      "stage3_capacity_claim":
          "20% is a user-accepted conditional engineering default; "
          "capacity_rule_v2 did not pass.",
      "selector_status": "disabled",
      "old_finals_v3_artifacts_used": False,
      "test_trace_opened": False,
      "status": proactive_stage4.AWAITING_INPUTS,
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "provenance.json"), provenance)
  _write_state(run_root, proactive_stage4.AWAITING_INPUTS, ["preflight"])
  _append_progress(
      run_root, "preflight_complete",
      run_identity_sha256=identity["run_identity_sha256"])
  print("[OK] preflight {}".format(run_root))
  return run_root, config, stage0, traces, working_set


def _load_run(args):
  config, stage0, _ = _load_authority(args)
  run_root = _run_root(args, config)
  identity_path = os.path.join(run_root, "run_identity.json")
  if not os.path.isfile(identity_path):
    raise ValueError("Run has not passed preflight.")
  expected_manifest_sha = proactive_stage4.fingerprint_file(args.manifest)
  identity = proactive_stage4.load_json(identity_path)
  if identity["manifest_sha256"] != expected_manifest_sha:
    raise ValueError("Run/input manifest identity mismatch.")
  _, traces, _ = proactive_stage4.resolve_inputs(
      args.manifest, args.project_root)
  working_set = proactive_stage4.load_json(
      os.path.join(run_root, "working_set_summary.json"))
  return run_root, config, stage0, traces, working_set


def _parameters(item):
  return (
      int(item["lookahead_L"]),
      tuple(float(value) for value in item["label_weights"]),
      int(item["candidate_size_K"]),
      int(item["history_H"]))


def _experiment_directory(run_root, scope, parameters):
  identity = proactive_stage4.experiment_id(*parameters)
  return os.path.join(run_root, scope, identity)


def _write_merged_jsonl(path, source_paths):
  directory = os.path.dirname(os.path.abspath(path))
  os.makedirs(directory, exist_ok=True)
  temporary = path + ".building.{}".format(os.getpid())
  if os.path.exists(temporary):
    raise ValueError("Stale temporary JSONL requires inspection: " + temporary)
  count = 0
  try:
    with open(temporary, "w", encoding="utf-8", newline="\n") as output:
      for source_path in source_paths:
        with open(source_path, "r", encoding="utf-8") as source:
          for line in source:
            if line.strip():
              output.write(line.rstrip("\r\n") + "\n")
              count += 1
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  except Exception:
    if os.path.exists(temporary):
      os.unlink(temporary)
    raise
  return count


def _audit_dataset_manifest(metadata):
  if metadata.get("test_trace_opened") is not False:
    raise ValueError("Dataset manifest has Test contamination.")
  if metadata.get("selector_status") != "disabled":
    raise ValueError("Dataset manifest enabled the candidate selector.")
  for split, item in metadata["merged"].items():
    if split not in proactive_stage4.ALLOWED_SPLITS:
      raise ValueError("Dataset manifest contains a forbidden split.")
    if proactive_stage4.fingerprint_file(item["path"]) != item["sha256"]:
      raise ValueError("Merged dataset fingerprint mismatch: " + split)
  for workload, split_items in metadata["per_workload"].items():
    for split, item in split_items.items():
      if split not in proactive_stage4.ALLOWED_SPLITS:
        raise ValueError("Dataset manifest contains a forbidden split.")
      if proactive_stage4.fingerprint_file(item["path"]) != item["sha256"]:
        raise ValueError(
            "Dataset fingerprint mismatch: {}/{}.".format(workload, split))
  return True


def ensure_dataset(
    run_root, scope, stage0, traces, working_set, parameters):
  L, weights, K, H = parameters
  experiment = proactive_stage4.experiment_id(L, weights, K, H)
  root = _experiment_directory(run_root, scope, parameters)
  metadata_path = os.path.join(root, "dataset", "dataset_manifest.json")
  expected_identity = {
      "experiment_id": experiment,
      "parameters": {
          "lookahead_L": L, "label_weights": list(weights),
          "candidate_size_K": K, "history_H": H},
      "raw_input_sha256":
          proactive_stage4.load_json(
              os.path.join(run_root, "run_identity.json"))["trace_sha256"],
      "scope": scope,
  }
  expected_identity["identity_sha256"] = proactive_stage4.fingerprint_value(
      expected_identity)
  if os.path.isfile(metadata_path):
    metadata = proactive_stage4.load_json(metadata_path)
    if metadata.get("identity") != expected_identity:
      raise ValueError("Existing dataset identity mismatch: " + root)
    _audit_dataset_manifest(metadata)
    return metadata
  os.makedirs(os.path.join(root, "dataset"), exist_ok=True)
  per_workload = {}
  diagnostics = []
  generation_started = time.time()
  for workload in sorted(traces):
    per_workload[workload] = {}
    for split in proactive_stage4.ALLOWED_SPLITS:
      started = time.time()
      rows, diagnostic, replay_summary = proactive_stage4.generate_samples(
          stage0, traces[workload][split], workload, split,
          int(working_set[workload]["dram_capacity_pages"]),
          L, weights, K, H)
      path = os.path.abspath(os.path.join(
          root, "dataset", "{}_{}.jsonl".format(workload, split)))
      count = proactive_stage4.write_jsonl_atomic(path, rows)
      if count <= 0:
        raise ValueError(
            "{} {} produced no complete active-round samples.".format(
                workload, split))
      diagnostic["generation_seconds"] = time.time() - started
      diagnostic["replay_summary"] = replay_summary
      diagnostics.append(diagnostic)
      per_workload[workload][split] = {
          "path": path,
          "sample_count": count,
          "sha256": proactive_stage4.fingerprint_file(path),
      }
      _append_progress(
          run_root, "dataset_workload_complete", scope=scope,
          experiment_id=experiment, workload=workload, split=split,
          sample_count=count)
  merged = {}
  for split in proactive_stage4.ALLOWED_SPLITS:
    path = os.path.abspath(os.path.join(
        root, "dataset", "all_{}.jsonl".format(split)))
    count = _write_merged_jsonl(
        path, [per_workload[workload][split]["path"]
               for workload in sorted(per_workload)])
    merged[split] = {
        "path": path, "sample_count": count,
        "sha256": proactive_stage4.fingerprint_file(path)}
  metadata = {
      "schema_version": "capd_proactive_stage4_dataset_manifest_v1_0",
      "contract_id": proactive_stage4.CONTRACT_ID,
      "identity": expected_identity,
      "per_workload": per_workload,
      "merged": merged,
      "diagnostics": diagnostics,
      "generation_seconds": time.time() - generation_started,
      "incomplete_lookahead_handling":
          "excluded_from_training_and_counted_in_diagnostics",
      "trajectory_policy": "proactive_lru",
      "selector_status": "disabled",
      "test_trace_opened": False,
  }
  proactive_stage4.write_json_atomic(metadata_path, metadata)
  return metadata


def _training_contract(config, metadata, parameters, seed, output_root):
  L, weights, K, H = parameters
  experiment = proactive_stage4.experiment_id(L, weights, K, H)
  training = copy.deepcopy(config["training"])
  training.pop("checkpoint_rule", None)
  training.pop("dataset_trajectory_policy", None)
  training.pop("global_model_across_workloads", None)
  return {
      "schema_version": proactive_stage4.TRAINING_CONTRACT_SCHEMA,
      "contract_id": proactive_stage4.CONTRACT_ID,
      "experiment_id": experiment,
      "seed": int(seed),
      "expected_shape": {"H": H, "K": K, "page_state_dim": 4},
      "sample_identity": {
          "schema_version": proactive_stage4.SAMPLE_SCHEMA,
          "contract_id": proactive_stage4.CONTRACT_ID,
          "experiment_id": experiment,
      },
      "labels": {
          "lambda_1": weights[0], "lambda_2": weights[1],
          "lambda_3": weights[2]},
      "training": training,
      "data": {
          "train": metadata["merged"]["train"],
          "validation": metadata["merged"]["validation"],
      },
      "method": {
          "F_low": 8, "F_target": 16, "b_max": 4,
          "candidate_source": "lru_tail", "selector": "disabled",
          "trajectory_policy": "proactive_lru",
      },
      "output_directory": os.path.abspath(output_root),
      "test_trace_opened": False,
  }


def ensure_training(
    args, run_root, scope, config, metadata, parameters, seed):
  root = _experiment_directory(run_root, scope, parameters)
  output = os.path.abspath(os.path.join(
      root, "checkpoints", "seed_{}".format(seed)))
  os.makedirs(output, exist_ok=True)
  contract = _training_contract(
      config, metadata, parameters, seed, output)
  contract_path = os.path.join(output, "training_contract.json")
  if os.path.isfile(contract_path):
    if proactive_stage4.load_json(contract_path) != contract:
      raise ValueError("Existing training contract mismatch: " + output)
  else:
    proactive_stage4.write_json_atomic(contract_path, contract)
  manifest_path = os.path.join(output, "checkpoint_manifest.json")
  if os.path.isfile(manifest_path):
    manifest = proactive_stage4.load_json(manifest_path)
    if (manifest.get("stage4_training_contract_fingerprint") !=
        proactive_stage4.fingerprint_value(contract)):
      raise ValueError("Existing checkpoint contract mismatch.")
    checkpoint = manifest["checkpoints"]["best"]["path"]
    if proactive_stage4.fingerprint_file(checkpoint) != (
        manifest["checkpoints"]["best"]["fingerprint"]):
      raise ValueError("Existing best checkpoint fingerprint mismatch.")
    return manifest
  command = [
      sys.executable, "-m", "qmap.qmap_train",
      "--train_data", metadata["merged"]["train"]["path"],
      "--valid_data", metadata["merged"]["validation"]["path"],
      "--proactive_stage4_contract", contract_path,
      "--output_dir", output,
      "--seed", str(seed),
      "--device", args.device,
      "--ablation", "cross_attention",
  ]
  last_checkpoint = os.path.join(output, "qmap_last.pth")
  if os.path.isfile(last_checkpoint):
    command.extend(["--resume_checkpoint", last_checkpoint])
  log_path = os.path.join(
      run_root, "logs", "{}_{}_seed_{}.log".format(
          scope.replace("/", "_"),
          proactive_stage4.experiment_id(*parameters), seed))
  _append_progress(
      run_root, "training_start", scope=scope,
      experiment_id=proactive_stage4.experiment_id(*parameters), seed=seed,
      resume=os.path.isfile(last_checkpoint))
  with open(log_path, "a", encoding="utf-8", newline="\n") as log:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = str(seed)
    environment.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    completed = subprocess.run(
        command, cwd=args.project_root, stdout=log,
        stderr=subprocess.STDOUT, check=False, env=environment)
  if completed.returncode != 0:
    raise RuntimeError(
        "Training failed (exit {}); inspect {}.".format(
            completed.returncode, log_path))
  manifest = proactive_stage4.load_json(manifest_path)
  _append_progress(
      run_root, "training_complete", scope=scope,
      experiment_id=proactive_stage4.experiment_id(*parameters), seed=seed,
      checkpoint_sha256=manifest["checkpoints"]["best"]["fingerprint"])
  return manifest


def ensure_evaluation(
    args, run_root, scope, stage0, traces, working_set, parameters, seed,
    checkpoint_manifest):
  root = _experiment_directory(run_root, scope, parameters)
  output = os.path.join(root, "validation", "seed_{}".format(seed))
  summary_path = os.path.join(output, "summary.json")
  checkpoint = checkpoint_manifest["checkpoints"]["best"]["path"]
  checkpoint_sha = proactive_stage4.fingerprint_file(checkpoint)
  if os.path.isfile(summary_path):
    summary = proactive_stage4.load_json(summary_path)
    if summary.get("checkpoint_sha256") != checkpoint_sha:
      raise ValueError("Existing validation/checkpoint mismatch.")
    return summary["rows"]
  os.makedirs(output, exist_ok=True)
  rows = []
  for workload in sorted(traces):
    row, details = proactive_stage4.evaluate_checkpoint(
        stage0, traces[workload]["validation"], workload,
        int(working_set[workload]["dram_capacity_pages"]),
        checkpoint, args.device, seed, *parameters)
    row["training_contract_sha256"] = checkpoint_manifest[
        "stage4_training_contract_fingerprint"]
    details_path = os.path.abspath(os.path.join(
        output, "{}_round_metrics.jsonl".format(workload)))
    proactive_stage4.write_jsonl_atomic(details_path, details)
    row["round_metrics_path"] = details_path
    row["round_metrics_sha256"] = proactive_stage4.fingerprint_file(
        details_path)
    rows.append(row)
  summary = {
      "schema_version": proactive_stage4.METRIC_SCHEMA,
      "checkpoint_sha256": checkpoint_sha,
      "seed": seed,
      "rows": rows,
      "aggregate": proactive_stage4.aggregate_metric_rows(rows),
      "test_trace_opened": False,
  }
  proactive_stage4.write_json_atomic(summary_path, summary)
  _append_progress(
      run_root, "validation_complete", scope=scope,
      experiment_id=proactive_stage4.experiment_id(*parameters), seed=seed)
  return rows


def run_experiment(
    args, run_root, scope, config, stage0, traces, working_set, parameters):
  root = _experiment_directory(run_root, scope, parameters)
  result_path = os.path.join(root, "experiment_result.json")
  if os.path.isfile(result_path):
    result = proactive_stage4.load_json(result_path)
    if result.get("parameters") != {
        "lookahead_L": parameters[0],
        "label_weights": list(parameters[1]),
        "candidate_size_K": parameters[2],
        "history_H": parameters[3]}:
      raise ValueError("Existing experiment result identity mismatch.")
    metadata = proactive_stage4.load_json(result["dataset_manifest_path"])
    _audit_dataset_manifest(metadata)
    for checkpoint in result["checkpoints"]:
      if proactive_stage4.fingerprint_file(checkpoint["path"]) != (
          checkpoint["sha256"]):
        raise ValueError("Existing experiment checkpoint mismatch.")
    if result.get("test_trace_opened") is not False:
      raise ValueError("Existing experiment has Test contamination.")
    return result
  metadata = ensure_dataset(
      run_root, scope, stage0, traces, working_set, parameters)
  rows = []
  checkpoints = []
  for seed in config["seeds"]:
    checkpoint_manifest = ensure_training(
        args, run_root, scope, config, metadata, parameters, seed)
    checkpoints.append({
        "seed": seed,
        "path": checkpoint_manifest["checkpoints"]["best"]["path"],
        "sha256": checkpoint_manifest["checkpoints"]["best"]["fingerprint"],
        "selection_criterion":
            checkpoint_manifest["selection_criterion"],
    })
    rows.extend(ensure_evaluation(
        args, run_root, scope, stage0, traces, working_set, parameters,
        seed, checkpoint_manifest))
  L, weights, K, H = parameters
  result = {
      "schema_version": proactive_stage4.METRIC_SCHEMA,
      "contract_id": proactive_stage4.CONTRACT_ID,
      "experiment_id": proactive_stage4.experiment_id(*parameters),
      "scope": scope,
      "parameters": {
          "lookahead_L": L, "label_weights": list(weights),
          "candidate_size_K": K, "history_H": H},
      "complexity_rank": [
          L, K, abs(H - 10), H, sum(weights)],
      "dataset_manifest_path": os.path.abspath(os.path.join(
          root, "dataset", "dataset_manifest.json")),
      "checkpoints": checkpoints,
      "rows": rows,
      "aggregate": proactive_stage4.aggregate_metric_rows(rows),
      "test_trace_opened": False,
  }
  proactive_stage4.write_json_atomic(result_path, result)
  return result


def _selected_parameters(run_root, phase):
  path = os.path.join(run_root, "selections", phase + ".json")
  decision = proactive_stage4.load_json(path)
  return _parameters(decision["selected_parameters"])


def _phase_candidates(config, run_root, phase):
  reference = config["reference"]
  base_weights = tuple(float(value) for value in reference["label_weights"])
  if phase == "lookahead":
    return [
        (int(L), base_weights, int(reference["candidate_size_K"]),
         int(reference["history_H"]))
        for L in config["grid"]["lookahead_L"]]
  selected_L = _selected_parameters(run_root, "lookahead")[0]
  if phase == "label_weights":
    return [
        (selected_L, tuple(float(value) for value in weights),
         int(reference["candidate_size_K"]), int(reference["history_H"]))
        for weights in config["grid"]["label_weights"]]
  selected_weights = _selected_parameters(
      run_root, "label_weights")[1]
  return [
      (selected_L, selected_weights, int(K), int(H))
      for K, H in itertools.product(
          config["grid"]["candidate_size_K"],
          config["grid"]["history_H"])]


def run_phase(args, phase):
  if phase not in PHASES:
    raise ValueError("Unknown phase: " + phase)
  run_root, config, stage0, traces, working_set = _load_run(args)
  if phase != "lookahead":
    prior = "lookahead" if phase == "label_weights" else "label_weights"
    if not os.path.isfile(os.path.join(
        run_root, "selections", prior + ".json")):
      raise ValueError("Prior phase selection is missing: " + prior)
  candidates = _phase_candidates(config, run_root, phase)
  results = [
      run_experiment(
          args, run_root, "experiments", config, stage0, traces,
          working_set, parameters)
      for parameters in candidates]
  reference_parameters = {
      "lookahead": (
          256, (1.0, 1.0, 4.0), 8, 10),
      "label_weights": (
          candidates[0][0], (1.0, 1.0, 4.0), 8, 10),
      "candidate_history": (
          candidates[0][0], candidates[0][1], 8, 10),
  }[phase]
  reference_id = proactive_stage4.experiment_id(*reference_parameters)
  decision = proactive_stage4.select_global_candidate(
      results, reference_id, config["selection_rule"])
  selected = next(
      result for result in results
      if result["experiment_id"] == decision["selected_experiment_id"])
  reference = next(
      result for result in results
      if result["experiment_id"] == reference_id)
  decision.update({
      "schema_version": "capd_proactive_stage4_selection_v1_0",
      "phase": phase,
      "selected_parameters": selected["parameters"],
      "reference_experiment_id": reference_id,
      "candidate_result_paths": [
          os.path.abspath(os.path.join(
              _experiment_directory(
                  run_root, "experiments", _parameters(result["parameters"])),
              "experiment_result.json"))
          for result in results],
      "paired_differences_vs_reference": {
          metric: proactive_stage4.paired_differences(
              selected["rows"], reference["rows"], metric)
          for metric in (
              "weighted_cost_per_access", "nvm_writes",
              "ndcg_at_b_t", "top_b_t_regret")},
      "test_used": False,
      "created_at": _utc_now(),
  })
  os.makedirs(os.path.join(run_root, "selections"), exist_ok=True)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "selections", phase + ".json"), decision)
  _append_progress(
      run_root, "phase_complete", phase=phase,
      selected_experiment_id=decision["selected_experiment_id"])
  print("[OK] {} selected {}".format(
      phase, decision["selected_experiment_id"]))


def finalize(args):
  run_root, config, stage0, traces, working_set = _load_run(args)
  for phase in PHASES:
    if not os.path.isfile(os.path.join(
        run_root, "selections", phase + ".json")):
      raise ValueError("Cannot finalize before phase: " + phase)
  parameters = _selected_parameters(run_root, "candidate_history")
  result = run_experiment(
      args, run_root, "final_rebuild", config, stage0, traces,
      working_set, parameters)
  freeze = {
      "schema_version": "capd_proactive_stage4_freeze_candidate_v1_0",
      "contract_id": proactive_stage4.CONTRACT_ID,
      "status": proactive_stage4.RESULTS_READY,
      "selected_parameters": result["parameters"],
      "final_dataset_manifest": result["dataset_manifest_path"],
      "final_dataset_manifest_sha256": proactive_stage4.fingerprint_file(
          result["dataset_manifest_path"]),
      "final_checkpoints": result["checkpoints"],
      "checkpoint_selection_rule": "minimum_validation_loss_only",
      "checkpoint_tie_break": "earliest_epoch",
      "hyperparameter_selection_scope":
          "global_across_all_validation_workloads_and_seeds",
      "stage3_capacity_claim":
          "conditional_engineering_default_not_capacity_rule_v2_pass",
      "selector_status": "disabled",
      "test_trace_opened": False,
      "created_at": _utc_now(),
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "final_freeze_candidate.json"), freeze)
  macro = result["aggregate"]["macro_average"]
  report_lines = [
      "# CAPD 主动降级阶段 4 结果待冻结报告",
      "",
      "- 状态：`{}`".format(proactive_stage4.RESULTS_READY),
      "- Test 参与：否",
      "- 候选筛选器：disabled",
      "- 阶段 3 容量边界：20% 为条件工程默认；capacity_rule_v2 未通过",
      "",
      "## 全局选择",
      "",
      "- `L={}`".format(parameters[0]),
      "- `lambda={}`".format(list(parameters[1])),
      "- `K={}`".format(parameters[2]),
      "- `H={}`".format(parameters[3]),
      "",
      "## Validation 宏平均",
      "",
      "| 指标 | 值 |",
      "|---|---:|",
  ]
  for label, key in (
      ("weighted cost/access", "weighted_cost_per_access"),
      ("NDCG@1", "ndcg_at_1"),
      ("NDCG@b_t", "ndcg_at_b_t"),
      ("Top-b overlap", "top_b_t_overlap"),
      ("Top-b regret", "top_b_t_regret"),
      ("NVM read", "nvm_reads"),
      ("NVM write", "nvm_writes"),
      ("proactive demotions", "proactive_demotions"),
      ("emergency fallback rate", "emergency_fallback_rate"),
      ("exhaustion rate", "exhaustion_rate"),
      ("early reuse rate", "early_reuse_rate"),
      ("amortized latency/page (s)",
       "amortized_latency_per_page_seconds"),
  ):
    report_lines.append("| {} | {} |".format(label, macro.get(key)))
  report_lines.extend([
      "",
      "三个 seed 用于描述稳定性，不解释为强统计显著性结论。",
      "本报告只有通过服务器测试和最终一致性审计后才可升级为 verified。",
  ])
  report_path = os.path.join(run_root, "report.md")
  proactive_stage4.write_text_atomic(report_path, "\n".join(report_lines))
  freeze["report_path"] = os.path.abspath(report_path)
  freeze["report_sha256"] = proactive_stage4.fingerprint_file(report_path)
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "final_freeze_candidate.json"), freeze)
  provenance_path = os.path.join(run_root, "provenance.json")
  provenance = proactive_stage4.load_json(provenance_path)
  provenance["status"] = proactive_stage4.RESULTS_READY
  provenance["final_freeze_candidate_sha256"] = (
      proactive_stage4.fingerprint_file(os.path.join(
          run_root, "final_freeze_candidate.json")))
  proactive_stage4.write_json_atomic(provenance_path, provenance)
  _write_state(
      run_root, proactive_stage4.RESULTS_READY,
      ["preflight"] + list(PHASES) + ["final_rebuild"])
  _append_progress(run_root, "final_rebuild_complete")
  print("[OK] {}".format(proactive_stage4.RESULTS_READY))


def record_tests(args):
  run_root, _, _, _, _ = _load_run(args)
  if not os.path.isfile(args.test_log):
    raise ValueError("Test log does not exist: " + args.test_log)
  text = open(args.test_log, "r", encoding="utf-8", errors="replace").read()
  if "FAILED" in text or "ERRORS" in text or "Traceback (most recent call last)" in text:
    raise ValueError("Test log contains a failure marker.")
  if "passed" not in text and "\nOK" not in text and not text.rstrip().endswith("OK"):
    raise ValueError("Test log has no recognized success marker.")
  receipt = {
      "schema_version": "capd_proactive_stage4_test_receipt_v1_0",
      "log_path": os.path.abspath(args.test_log),
      "log_sha256": proactive_stage4.fingerprint_file(args.test_log),
      "recorded_at": _utc_now(),
      "stage1_to_stage4_regression_requested": True,
      "test_trace_opened": False,
      "status": "passed",
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "server_test_receipt.json"), receipt)
  print("[OK] test receipt recorded")


def verify(args):
  run_root, config, _, _, _ = _load_run(args)
  freeze_path = os.path.join(run_root, "final_freeze_candidate.json")
  receipt_path = os.path.join(run_root, "server_test_receipt.json")
  if not os.path.isfile(freeze_path):
    raise ValueError("Final rebuild/freeze candidate is missing.")
  if not os.path.isfile(receipt_path):
    raise ValueError("Server test receipt is missing.")
  freeze = proactive_stage4.load_json(freeze_path)
  receipt = proactive_stage4.load_json(receipt_path)
  if freeze["status"] != proactive_stage4.RESULTS_READY:
    raise ValueError("Freeze candidate is not results-ready.")
  if receipt["status"] != "passed":
    raise ValueError("Server tests did not pass.")
  for phase in PHASES:
    decision = proactive_stage4.load_json(os.path.join(
        run_root, "selections", phase + ".json"))
    if decision.get("test_used") is not False:
      raise ValueError("{} selection has Test contamination.".format(phase))
  if freeze.get("test_trace_opened") is not False:
    raise ValueError("Freeze candidate has Test contamination.")
  if freeze.get("selector_status") != "disabled":
    raise ValueError("Candidate selector was enabled.")
  if (not os.path.isfile(freeze.get("report_path", "")) or
      proactive_stage4.fingerprint_file(freeze["report_path"]) !=
      freeze.get("report_sha256")):
    raise ValueError("Stage-4 result report is missing or corrupted.")
  if (freeze.get("checkpoint_selection_rule") !=
      "minimum_validation_loss_only" or
      freeze.get("checkpoint_tie_break") != "earliest_epoch"):
    raise ValueError("Final checkpoint selection rule mismatch.")
  for item in freeze["final_checkpoints"]:
    if proactive_stage4.fingerprint_file(item["path"]) != item["sha256"]:
      raise ValueError("Final checkpoint SHA-256 mismatch.")
    if item["selection_criterion"] != "minimum_valid_loss_only":
      raise ValueError("Final checkpoint was not selected by Validation only.")
  dataset_manifest = proactive_stage4.load_json(
      freeze["final_dataset_manifest"])
  if proactive_stage4.fingerprint_file(
      freeze["final_dataset_manifest"]) != (
          freeze["final_dataset_manifest_sha256"]):
    raise ValueError("Final dataset manifest SHA-256 mismatch.")
  _audit_dataset_manifest(dataset_manifest)
  if tuple(config["seeds"]) != proactive_stage4.SEEDS:
    raise ValueError("Final seeds changed.")
  verification = {
      "schema_version": "capd_proactive_stage4_verification_v1_0",
      "contract_id": proactive_stage4.CONTRACT_ID,
      "status": proactive_stage4.VERIFIED,
      "verified_at": _utc_now(),
      "final_freeze_candidate_sha256":
          proactive_stage4.fingerprint_file(freeze_path),
      "server_test_receipt_sha256":
          proactive_stage4.fingerprint_file(receipt_path),
      "selected_parameters": freeze["selected_parameters"],
      "selector_status": "disabled",
      "old_finals_v3_artifacts_used": False,
      "test_trace_opened": False,
  }
  proactive_stage4.write_json_atomic(
      os.path.join(run_root, "verification.json"), verification)
  provenance_path = os.path.join(run_root, "provenance.json")
  provenance = proactive_stage4.load_json(provenance_path)
  provenance["status"] = proactive_stage4.VERIFIED
  provenance["verification_sha256"] = proactive_stage4.fingerprint_file(
      os.path.join(run_root, "verification.json"))
  proactive_stage4.write_json_atomic(provenance_path, provenance)
  _write_state(
      run_root, proactive_stage4.VERIFIED,
      ["preflight"] + list(PHASES) +
      ["final_rebuild", "server_tests", "verification"])
  _append_progress(run_root, "verification_complete")
  print("[FINAL] STAGE4_VERIFIED")


def run_all(args):
  preflight(args)
  for phase in PHASES:
    run_phase(args, phase)
  finalize(args)


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "command",
      choices=("preflight", "lookahead", "label-weights",
               "candidate-history", "finalize", "record-tests", "verify",
               "all"))
  parser.add_argument(
      "--config",
      default="configs/finals/capd_proactive_stage4.json")
  parser.add_argument(
      "--stage0-config",
      default="configs/finals/capd_proactive_stage0.json")
  parser.add_argument(
      "--stage3-default",
      default="configs/finals/capd_proactive_stage3_engineering_default.json")
  parser.add_argument("--manifest", required=True)
  parser.add_argument("--run-id", required=True)
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  parser.add_argument("--device", default="cpu")
  parser.add_argument("--test-log")
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  args.project_root = os.path.abspath(args.project_root)
  for field in ("config", "stage0_config", "stage3_default", "manifest"):
    value = getattr(args, field)
    if not os.path.isabs(value):
      setattr(args, field, os.path.abspath(os.path.join(
          args.project_root, value)))
  if args.command == "preflight":
    preflight(args)
  elif args.command == "lookahead":
    run_phase(args, "lookahead")
  elif args.command == "label-weights":
    run_phase(args, "label_weights")
  elif args.command == "candidate-history":
    run_phase(args, "candidate_history")
  elif args.command == "finalize":
    finalize(args)
  elif args.command == "record-tests":
    if not args.test_log:
      raise ValueError("record-tests requires --test-log.")
    record_tests(args)
  elif args.command == "verify":
    verify(args)
  elif args.command == "all":
    run_all(args)


if __name__ == "__main__":
  main()
