#!/usr/bin/env python3
# coding=utf-8
"""Server orchestrator for R4-authoritative CAPD Stage-4 search.

The search and formal freeze are separate, explicitly confirmed operations.
One training subprocess is active at a time; sample generation and CPU replay
may use per-workload process pools with deterministic merge order.
"""

import argparse
import concurrent.futures
import copy
import csv
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import proactive_stage3
from qmap import proactive_stage4_stage7 as stage4


def utc_now():
  return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_state(project_root):
  def run(*arguments):
    completed = subprocess.run(
        ["git"] + list(arguments), cwd=project_root, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return completed.returncode, completed.stdout.strip()
  code, commit = run("rev-parse", "HEAD")
  status_code, status = run("status", "--porcelain=v1", "--untracked-files=all")
  return {"commit": commit if code == 0 else "unknown",
          "dirty": bool(status) if status_code == 0 else None,
          "status_sha256": stage4.fingerprint_value(status.splitlines())}


def append_event(run_root, event, **fields):
  path = os.path.join(run_root, "logs", "events.jsonl")
  os.makedirs(os.path.dirname(path), exist_ok=True)
  row = {"at": utc_now(), "event": event}
  row.update(fields)
  with open(path, "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def runtime_device(requested, require_cuda):
  import torch
  if requested == "auto":
    resolved = "cuda" if torch.cuda.is_available() else "cpu"
  else:
    resolved = requested
  if require_cuda and (resolved != "cuda" or not torch.cuda.is_available()):
    raise RuntimeError("--require-cuda set, but CUDA is unavailable")
  if resolved == "cuda" and not torch.cuda.is_available():
    raise RuntimeError("CUDA requested, but torch.cuda.is_available() is false")
  return {"requested": requested, "actual": resolved,
          "require_cuda": bool(require_cuda),
          "cuda_available": bool(torch.cuda.is_available()),
          "cuda_device_count": int(torch.cuda.device_count()),
          "cuda_device_name": (torch.cuda.get_device_name(0)
                               if torch.cuda.is_available() else None)}


def load_context(args, require_traces=True):
  config = stage4.validate_search_config(stage4.load_json(args.config))
  authority = stage4.validate_stage3_authority(args.stage3_freeze)
  manifest = stage4.load_json(args.input_manifest)
  entries = (stage4.validate_input_manifest(
      manifest, args.input_manifest, args.project_root) if require_traces
             else manifest.get("entries", []))
  return config, authority, manifest, entries


def run_root(args, config):
  expected = os.path.abspath(os.path.join(args.project_root,
                                          config["output_root"], args.run_id))
  forbidden = os.path.abspath(os.path.join(args.project_root,
                                            "outputs/capd_proactive_stage4"))
  if os.path.commonpath([expected, forbidden]) == forbidden:
    raise RuntimeError("New Stage4 may not write into the legacy output root")
  return expected


def ensure_layout(root):
  for name in ("vocabulary", "datasets", "search", "checkpoints", "logs"):
    os.makedirs(os.path.join(root, name), exist_ok=True)


def preflight(args):
  config, authority, manifest, entries = load_context(args)
  trace_validation = stage4.validate_registered_trace_records(entries)
  if config.get("execution", {}).get("require_cuda") and not args.require_cuda:
    raise RuntimeError("Formal config requires explicit --require-cuda")
  root = run_root(args, config)
  ensure_layout(root)
  device = runtime_device(args.device, args.require_cuda)
  if device["actual"] == "cuda" and device["cuda_device_count"] != 1:
    raise RuntimeError("Formal Stage4 requires exactly one visible CUDA device")
  resolved = copy.deepcopy(config)
  resolved["runtime"] = {
      "run_id": args.run_id, "device": device,
      "workers": {"train": args.train_workers, "sample": args.sample_workers,
                  "replay": args.replay_workers},
      "single_gpu_training_process": True,
      "git": git_state(args.project_root),
      "source_config_path": os.path.abspath(args.config),
      "source_config_sha256": stage4.fingerprint_file(args.config),
      "input_manifest_sha256": stage4.fingerprint_file(args.input_manifest),
      "trace_record_validation": trace_validation,
      "preflight_at": utc_now(),
  }
  stage4.write_json_atomic(os.path.join(root, "resolved_config.json"), resolved)
  stage4.write_json_atomic(os.path.join(root, "stage3_authority.json"), authority)
  stage4.write_json_atomic(os.path.join(root, "input_manifest.json"), manifest)
  stage4.write_json_atomic(os.path.join(root, "search_space.json"), {
      "schema_version": config["schema_version"],
      "search": config["search"], "selection": config["selection"],
      "fixed": config["fixed"], "formal_seeds": config["formal_seeds"],
      "search_config_sha256": stage4.fingerprint_file(args.config),
  })
  stage4.write_json_atomic(os.path.join(root, "training_contract.json"), {
      "schema_version": "capd_proactive_stage4_stage7_training_plan_v1_0",
      "contract_id": stage4.CONTRACT_ID, "run_id": args.run_id,
      "model_scope": "one_unified_model_per_seed_across_six_workloads",
      "formal_seeds": config["formal_seeds"],
      "checkpoint_rule": config["selection"]["checkpoint_rule"],
      "search_confirmation_required": True,
      "test_trace_opened": False, "pressure_trace_opened": False,
  })
  state = {
      "schema_version": "capd_proactive_stage4_stage7_run_state_v1_0",
      "run_id": args.run_id, "status": "preflight_passed_awaiting_confirmation",
      "formal_freeze": False, "search_contract_confirmed": False,
      "input_entries": len(entries), "test_trace_opened": False,
      "pressure_trace_opened": False, "updated_at": utc_now(),
  }
  stage4.write_json_atomic(os.path.join(root, "search_state.json"), {
      "status": "not_started", "completed_phases": [],
      "active_training_processes": 0, "formal_freeze": False})
  stage4.write_json_atomic(os.path.join(root, "run_state.json"), state)
  append_event(root, "preflight_passed", device=device,
               entry_count=len(entries))
  print("[OK] preflight passed: {}".format(root))
  print("[GATE] full search is locked until explicit contract confirmation")
  return root


def confirm_contract(args):
  if not args.confirm_stage4_search:
    raise RuntimeError("Confirmation requires --confirm-stage4-search")
  config, _, _, _ = load_context(args)
  root = run_root(args, config)
  resolved_path = os.path.join(root, "resolved_config.json")
  if not os.path.isfile(resolved_path):
    raise RuntimeError("Run preflight before confirming the search contract")
  resolved = stage4.load_json(resolved_path)
  source_sha = stage4.fingerprint_file(args.config)
  if resolved["runtime"]["source_config_sha256"] != source_sha:
    raise RuntimeError("Search config changed after preflight")
  sample_gate = require_sample_structure_gate_passed(root)
  confirmation = {
      "schema_version": "capd_proactive_stage4_stage7_search_confirmation_v1_0",
      "run_id": args.run_id, "human_confirmation": True,
      "search_config_sha256": source_sha, "confirmed_at": utc_now(),
      "candidate_count": 15, "training_run_count": 45,
      "sample_structure_verification_sha256": stage4.fingerprint_file(
          os.path.join(root, "sample_structure_verification.json")),
      "sample_structure_report_sha256": sample_gate[
          "sample_structure_report_sha256"],
      "formal_freeze": False,
  }
  confirmed_contract = copy.deepcopy(config)
  confirmed_contract["status"] = "search_contract_human_confirmed"
  confirmed_contract["confirmation_gate"].update({
      "search_contract_confirmed": True, "full_search_allowed": True,
      "formal_freeze_allowed": False})
  confirmed_path = os.path.join(root, "confirmed_search_contract.json")
  stage4.write_json_atomic(confirmed_path, confirmed_contract)
  confirmation["confirmed_search_contract_sha256"] = (
      stage4.fingerprint_file(confirmed_path))
  stage4.write_json_atomic(os.path.join(root, "search_contract_confirmation.json"),
                           confirmation)
  state = stage4.load_json(os.path.join(root, "run_state.json"))
  state.update({"status": "search_contract_confirmed_ready_for_search",
                "search_contract_confirmed": True, "updated_at": utc_now()})
  stage4.write_json_atomic(os.path.join(root, "run_state.json"), state)
  append_event(root, "search_contract_confirmed")
  print("[OK] search contract confirmed; no training was started")


def require_search_confirmation(root, args):
  require_sample_structure_gate_passed(root)
  path = os.path.join(root, "search_contract_confirmation.json")
  if not os.path.isfile(path):
    raise RuntimeError("Full search is locked: explicit confirmation is missing")
  value = stage4.load_json(path)
  confirmed_path = os.path.join(root, "confirmed_search_contract.json")
  if (value.get("human_confirmation") is not True or
      value.get("search_config_sha256") != stage4.fingerprint_file(args.config) or
      not os.path.isfile(confirmed_path) or
      value.get("confirmed_search_contract_sha256") !=
      stage4.fingerprint_file(confirmed_path)):
    raise RuntimeError("Search confirmation identity mismatch")


SAMPLE_GATE_FORBIDDEN_TOP_LEVEL = (
    "confirmed_search_contract.json", "search_contract_confirmation.json",
    "stage4_candidate.json", "validation_selection_report.json",
    "checkpoint_manifest.json", "verification.json",
    "final_stage4_freeze.json", "stage8_model_contract.json",
    "formal_checkpoint_manifest.json", "validation_metrics.csv",
    "validation_metrics_by_workload.csv")


def sample_gate_forbidden_artifacts(root):
  """Return search/training/selection/freeze artifacts forbidden at this gate."""
  found = []
  for name in SAMPLE_GATE_FORBIDDEN_TOP_LEVEL:
    if os.path.exists(os.path.join(root, name)):
      found.append(name)
  for directory in ("search", "checkpoints"):
    base = os.path.join(root, directory)
    if not os.path.isdir(base):
      continue
    for current, _, files in os.walk(base):
      for name in files:
        found.append(os.path.relpath(os.path.join(current, name), root))
  return sorted(set(found))


def require_sample_structure_gate_ready(args, root, config):
  """Fail closed unless the run is still an untouched pre-search draft."""
  if (args.confirm_stage4_search or args.confirm_stage4_freeze or
      args.candidate is not None):
    raise RuntimeError(
        "samples forbids confirmation, freeze, and candidate arguments")
  resolved_path = os.path.join(root, "resolved_config.json")
  if not os.path.isfile(resolved_path):
    raise RuntimeError("Run preflight before sample generation")
  resolved = stage4.load_json(resolved_path)
  if (resolved.get("run_id") != args.run_id or
      resolved.get("runtime", {}).get("run_id") != args.run_id):
    raise RuntimeError("Sample gate run_id differs from preflight")
  if (resolved.get("runtime", {}).get("source_config_sha256") !=
      stage4.fingerprint_file(args.config) or
      resolved.get("runtime", {}).get("input_manifest_sha256") !=
      stage4.fingerprint_file(args.input_manifest)):
    raise RuntimeError("Sample gate config/input identity differs from preflight")
  run_state = stage4.load_json(os.path.join(root, "run_state.json"))
  allowed_statuses = {
      "preflight_passed_awaiting_confirmation",
      "sample_structure_gate_passed_awaiting_search_confirmation",
      "sample_structure_gate_failed"}
  if (run_state.get("status") not in allowed_statuses or
      run_state.get("formal_freeze") is not False or
      run_state.get("search_contract_confirmed") is not False or
      run_state.get("test_trace_opened") is not False or
      run_state.get("pressure_trace_opened") is not False):
    raise RuntimeError("Sample gate requires an unconfirmed, unfrozen run")
  search_state = stage4.load_json(os.path.join(root, "search_state.json"))
  if (search_state.get("status") != "not_started" or
      search_state.get("active_training_processes") != 0 or
      search_state.get("completed_phases") != [] or
      search_state.get("formal_freeze") is not False):
    raise RuntimeError("Sample gate requires search_state.status=not_started")
  forbidden = sample_gate_forbidden_artifacts(root)
  if forbidden:
    raise RuntimeError("Sample gate found forbidden artifacts: {}".format(
        ", ".join(forbidden)))
  return resolved


def require_sample_structure_gate_passed(root):
  """Validate the persisted pre-training sample gate and its SHA chain."""
  path = os.path.join(root, "sample_structure_verification.json")
  if not os.path.isfile(path):
    raise RuntimeError("Search confirmation requires the sample structure gate")
  value = stage4.load_json(path)
  required = {
      "sample_structure_report.json": value.get(
          "sample_structure_report_sha256"),
      "sample_manifest.json": value.get("sample_manifest_sha256"),
      "vocabulary_manifest.json": value.get("vocabulary_manifest_sha256")}
  if (value.get("status") != "PASS" or value.get("gate_pass") is not True or
      value.get("training_started") is not False or
      value.get("search_started") is not False or
      value.get("checkpoint_created") is not False or
      value.get("candidate_selected") is not False or
      value.get("test_trace_opened") is not False or
      value.get("pressure_trace_opened") is not False or
      value.get("search_contract_confirmed") is not False or
      value.get("zero_sample_workload_splits") != [] or
      value.get("zero_valid_decision_workload_splits") != [] or
      value.get("formal_freeze") is not False):
    raise RuntimeError("Sample structure gate is not a clean PASS")
  for name, expected in required.items():
    artifact = os.path.join(root, name)
    if (not expected or not os.path.isfile(artifact) or
        stage4.fingerprint_file(artifact) != expected):
      raise RuntimeError("Sample structure gate SHA mismatch: {}".format(name))
  return value


def write_jsonl(path, rows):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", encoding="utf-8", newline="\n") as handle:
    for row in rows:
      handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def sample_worker(payload):
  entry, candidate, authority, input_sha, output = payload
  trace, _ = proactive_stage3._read_compact_trace(
      entry["resolved_trace_path"], int(entry["page_shift"]))
  expected = (int(entry["source_interval"]["end_exclusive"]) -
              int(entry["source_interval"]["start_inclusive"]))
  if len(trace) != expected or len(trace) != int(entry["accesses"]):
    raise RuntimeError("Trace/source interval mismatch in sample worker")
  rows, diagnostics = stage4.generate_samples_for_trace(
      trace, entry, candidate, authority, input_sha)
  write_jsonl(output, rows)
  diagnostics["path"] = output
  diagnostics["sha256"] = stage4.fingerprint_file(output)
  return diagnostics


def semantic_key(candidate):
  return stage4.fingerprint_value({
      "L": candidate["lookahead_L"], "H": candidate["history_H"],
      "lambda": candidate["label_weights"]})[:20]


def replace_vocab_identity(path, vocabulary_sha):
  temporary = path + ".vocab.tmp"
  with open(path, "r", encoding="utf-8") as source, open(
      temporary, "w", encoding="utf-8", newline="\n") as output:
    for line in source:
      row = json.loads(line)
      row["vocabulary_sha256"] = vocabulary_sha
      output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
  os.replace(temporary, path)


def ensure_dataset(args, root, candidate, authority, entries):
  key = semantic_key(candidate)
  dataset_root = os.path.join(root, "datasets", key)
  manifest_path = os.path.join(dataset_root, "sample_manifest.json")
  expected_identity = stage4.sample_cache_identity(
      candidate, authority, stage4.fingerprint_file(args.input_manifest))
  if os.path.isfile(manifest_path):
    manifest = stage4.load_json(manifest_path)
    if manifest.get("sample_cache_identity") != expected_identity:
      raise RuntimeError("Incompatible cached sample contract: {}".format(key))
    for split in stage4.SPLITS:
      item = manifest["merged"][split]
      if stage4.fingerprint_file(item["path"]) != item["sha256"]:
        raise RuntimeError("Cached sample SHA mismatch")
    vocabulary = manifest.get("vocabulary", {})
    for prefix in ("page", "pc"):
      path = vocabulary.get(prefix + "_vocabulary_path", "")
      if (not os.path.isfile(path) or stage4.fingerprint_file(path) !=
          vocabulary.get(prefix + "_vocabulary_file_sha256")):
        raise RuntimeError("Cached vocabulary SHA mismatch")
    return manifest
  os.makedirs(dataset_root, exist_ok=True)
  temporary_root = os.path.join(dataset_root, "per_workload")
  payloads = []
  input_sha = stage4.fingerprint_file(args.input_manifest)
  for entry in sorted(entries, key=lambda item: (
      stage4.WORKLOADS.index(item["workload"]),
      stage4.SPLITS.index(item["split_role"]))):
    output = os.path.join(temporary_root, entry["workload"],
                          entry["split_role"] + ".jsonl")
    payloads.append((entry, candidate, authority, input_sha, output))
  if args.sample_workers == 1:
    diagnostics = [sample_worker(item) for item in payloads]
  else:
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(args.sample_workers, 6)) as executor:
      diagnostics = list(executor.map(sample_worker, payloads))
  merged = {}
  for split in stage4.SPLITS:
    path = os.path.join(dataset_root, "all_{}.jsonl".format(split))
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as output:
      for workload in stage4.WORKLOADS:
        source_path = os.path.join(temporary_root, workload, split + ".jsonl")
        with open(source_path, "r", encoding="utf-8") as source:
          for line in source:
            output.write(line); count += 1
    merged[split] = {"path": os.path.abspath(path), "sample_count": count}
  vocabulary = stage4.build_train_only_vocabulary(
      merged["train"]["path"], merged["validation"]["path"])
  vocabulary_root = os.path.join(root, "vocabulary", key)
  os.makedirs(vocabulary_root, exist_ok=True)
  page_map = vocabulary.pop("_page_input_to_index")
  pc_map = vocabulary.pop("_pc_input_to_index")
  page_path = os.path.join(vocabulary_root, "page_input_to_index.json")
  pc_path = os.path.join(vocabulary_root, "pc_input_to_index.json")
  stage4.write_json_atomic(page_path, page_map)
  stage4.write_json_atomic(pc_path, pc_map)
  vocabulary.update({
      "page_vocabulary_path": os.path.abspath(page_path),
      "pc_vocabulary_path": os.path.abspath(pc_path),
      "page_vocabulary_file_sha256": stage4.fingerprint_file(page_path),
      "pc_vocabulary_file_sha256": stage4.fingerprint_file(pc_path),
  })
  if (stage4.fingerprint_value(stage4.load_json(page_path)) !=
      vocabulary["page_vocabulary_sha256"] or
      stage4.fingerprint_value(stage4.load_json(pc_path)) !=
      vocabulary["pc_vocabulary_sha256"]):
    raise RuntimeError("Serialized Train-only vocabulary SHA mismatch")
  vocab_path = os.path.join(vocabulary_root, "vocabulary_manifest.json")
  stage4.write_json_atomic(vocab_path, vocabulary)
  vocabulary["manifest_path"] = os.path.abspath(vocab_path)
  vocabulary["manifest_sha256"] = stage4.fingerprint_file(vocab_path)
  for split in stage4.SPLITS:
    replace_vocab_identity(merged[split]["path"], vocabulary["vocabulary_sha256"])
    merged[split]["sha256"] = stage4.fingerprint_file(merged[split]["path"])
  manifest = {
      "schema_version": "capd_proactive_stage4_stage7_sample_manifest_v1_0",
      "contract_id": stage4.CONTRACT_ID, "semantic_key": key,
      "sample_cache_identity": expected_identity,
      "sample_cache_identity_sha256": stage4.fingerprint_value(expected_identity),
      "merged": merged, "vocabulary": vocabulary,
      "per_workload": diagnostics,
      "deterministic_merge_order": list(stage4.WORKLOADS),
      "test_trace_opened": False, "pressure_trace_opened": False,
  }
  stage4.write_json_atomic(manifest_path, manifest)
  return manifest


def sample_structure_dataset_report(root, candidate, manifest, authority):
  """Build one semantic-cache report with explicit per-workload decisions."""
  diagnostics = {}
  for row in manifest.get("per_workload", []):
    key = (row.get("workload"), row.get("split_role"))
    if key in diagnostics:
      raise RuntimeError("Duplicate sample diagnostics: {}/{}".format(*key))
    diagnostics[key] = row
  expected = {(workload, split) for workload in stage4.WORKLOADS
              for split in stage4.SPLITS}
  if set(diagnostics) != expected:
    missing = sorted(expected - set(diagnostics))
    extra = sorted(set(diagnostics) - expected)
    raise RuntimeError(
        "Sample diagnostics coverage mismatch: missing={} extra={}".format(
            missing, extra))
  contracts = {row.get("sample_generation_contract_sha256")
               for row in diagnostics.values()}
  if len(contracts) != 1 or None in contracts:
    raise RuntimeError("Sample generation contract SHA is not unified")
  per_workload = {}
  zero_samples, zero_decisions = [], []
  oov = manifest["vocabulary"]["validation_oov_by_workload"]
  for workload in stage4.WORKLOADS:
    splits = {}
    for split in stage4.SPLITS:
      row = diagnostics[(workload, split)]
      sample_count = int(row.get("sample_count", 0))
      valid_count = int(row.get("valid_decision_count", sample_count))
      splits[split] = {
          "sample_count": sample_count,
          "valid_decision_count": valid_count,
          "sample_path": row.get("path"),
          "sample_sha256": row.get("sha256"),
          "sample_generation_contract_sha256": row.get(
              "sample_generation_contract_sha256")}
      identity = "{}/{}".format(workload, split)
      if sample_count <= 0:
        zero_samples.append(identity)
      if valid_count <= 0:
        zero_decisions.append(identity)
      if valid_count != sample_count:
        raise RuntimeError("Sample/valid-decision count mismatch: {}".format(
            identity))
    per_workload[workload] = {
        "method": copy.deepcopy(authority["workloads"][workload]),
        "train": splits["train"], "validation": splits["validation"],
        "validation_oov": copy.deepcopy(oov[workload])}
  manifest_path = os.path.join(
      root, "datasets", manifest["semantic_key"], "sample_manifest.json")
  return {
      "candidate_id": candidate["candidate_id"],
      "semantic_key": manifest["semantic_key"],
      "sample_cache_identity_sha256": manifest[
          "sample_cache_identity_sha256"],
      "sample_generation_contract_sha256": next(iter(contracts)),
      "sample_manifest_path": os.path.abspath(manifest_path),
      "sample_manifest_sha256": stage4.fingerprint_file(manifest_path),
      "merged": copy.deepcopy(manifest["merged"]),
      "vocabulary": {
          key: copy.deepcopy(manifest["vocabulary"][key]) for key in (
              "fit_scope", "validation_used_for_fit", "test_used_for_fit",
              "pressure_used_for_fit", "page_vocabulary_size",
              "pc_vocabulary_size", "page_vocabulary_sha256",
              "pc_vocabulary_sha256", "vocabulary_sha256",
              "page_vocabulary_file_sha256", "pc_vocabulary_file_sha256",
              "manifest_path", "manifest_sha256")},
      "per_workload": per_workload,
      "zero_sample_workload_splits": zero_samples,
      "zero_valid_decision_workload_splits": zero_decisions,
  }


def generate_draft_samples(args):
  """Run the pre-training sample structure gate; never train or select."""
  config, authority, _, entries = load_context(args)
  root = run_root(args, config)
  resolved = require_sample_structure_gate_ready(args, root, config)
  dataset_reports = []
  for candidate in stage4.resolve_phase_candidates(config, "semantic"):
    manifest = ensure_dataset(args, root, candidate, authority, entries)
    dataset_reports.append(sample_structure_dataset_report(
        root, candidate, manifest, authority))
  zero_samples = sorted({item for dataset in dataset_reports
                         for item in dataset["zero_sample_workload_splits"]})
  zero_decisions = sorted({item for dataset in dataset_reports
                           for item in dataset[
                               "zero_valid_decision_workload_splits"]})
  gate_pass = not zero_samples and not zero_decisions
  sample_index = {
      "schema_version": "capd_proactive_stage4_stage7_sample_index_v1_1",
      "status": ("sample_structure_gate_passed_no_training_started"
                 if gate_pass else
                 "sample_structure_gate_failed_no_training_started"),
      "run_id": args.run_id,
      "manifests": [{
          "candidate_id": item["candidate_id"],
          "semantic_key": item["semantic_key"],
          "sample_generation_contract_sha256": item[
              "sample_generation_contract_sha256"],
          "sample_manifest_sha256": item["sample_manifest_sha256"]}
          for item in dataset_reports],
      "training_started": False, "search_started": False,
      "checkpoint_created": False, "candidate_selected": False,
      "test_trace_opened": False, "pressure_trace_opened": False,
      "search_contract_confirmed": False, "formal_freeze": False}
  sample_index_path = os.path.join(root, "sample_manifest.json")
  stage4.write_json_atomic(sample_index_path, sample_index)
  vocabulary_index = {
      "schema_version": "capd_proactive_stage4_stage7_vocabulary_index_v1_0",
      "run_id": args.run_id, "fit_scope": "six_train_only",
      "validation_used_for_fit": False, "test_used_for_fit": False,
      "pressure_used_for_fit": False,
      "datasets": [{
          "candidate_id": item["candidate_id"],
          "semantic_key": item["semantic_key"],
          "vocabulary_sha256": item["vocabulary"]["vocabulary_sha256"],
          "vocabulary_manifest_sha256": item["vocabulary"]["manifest_sha256"]}
          for item in dataset_reports],
      "training_started": False, "formal_freeze": False}
  vocabulary_index_path = os.path.join(root, "vocabulary_manifest.json")
  stage4.write_json_atomic(vocabulary_index_path, vocabulary_index)
  report = {
      "schema_version": "capd_proactive_stage4_stage7_sample_structure_report_v1_0",
      "contract_id": stage4.CONTRACT_ID, "run_id": args.run_id,
      "status": "PASS" if gate_pass else "FAIL", "gate_pass": gate_pass,
      "input_entry_count": len(entries),
      "train_entry_count": sum(row["split_role"] == "train" for row in entries),
      "validation_entry_count": sum(
          row["split_role"] == "validation" for row in entries),
      "semantic_dataset_count": len(dataset_reports),
      "search_config_sha256": resolved["runtime"]["source_config_sha256"],
      "input_manifest_sha256": resolved["runtime"]["input_manifest_sha256"],
      "r4_final_freeze_sha256": authority["final_freeze_sha256"],
      "r2_input_manifest_sha256": resolved["authority"][
          "r2_input_manifest_sha256"],
      "datasets": dataset_reports,
      "zero_sample_workload_splits": zero_samples,
      "zero_valid_decision_workload_splits": zero_decisions,
      "training_started": False, "search_started": False,
      "checkpoint_created": False, "candidate_selected": False,
      "test_trace_opened": False, "pressure_trace_opened": False,
      "search_contract_confirmed": False, "formal_freeze": False}
  report_path = os.path.join(root, "sample_structure_report.json")
  stage4.write_json_atomic(report_path, report)
  forbidden_after = sample_gate_forbidden_artifacts(root)
  if forbidden_after:
    raise RuntimeError("Sample gate created forbidden artifacts: {}".format(
        ", ".join(forbidden_after)))
  verification = {
      "schema_version":
          "capd_proactive_stage4_stage7_sample_structure_verification_v1_0",
      "run_id": args.run_id, "status": report["status"],
      "gate_pass": gate_pass,
      "sample_structure_report_sha256": stage4.fingerprint_file(report_path),
      "sample_manifest_sha256": stage4.fingerprint_file(sample_index_path),
      "vocabulary_manifest_sha256": stage4.fingerprint_file(
          vocabulary_index_path),
      "zero_sample_workload_splits": zero_samples,
      "zero_valid_decision_workload_splits": zero_decisions,
      "training_started": False, "search_started": False,
      "checkpoint_created": False, "candidate_selected": False,
      "test_trace_opened": False, "pressure_trace_opened": False,
      "search_contract_confirmed": False, "formal_freeze": False}
  verification_path = os.path.join(root, "sample_structure_verification.json")
  stage4.write_json_atomic(verification_path, verification)
  run_state_path = os.path.join(root, "run_state.json")
  run_state = stage4.load_json(run_state_path)
  run_state.update({
      "status": ("sample_structure_gate_passed_awaiting_search_confirmation"
                 if gate_pass else "sample_structure_gate_failed"),
      "sample_structure_gate_passed": gate_pass,
      "search_contract_confirmed": False, "formal_freeze": False,
      "test_trace_opened": False, "pressure_trace_opened": False,
      "updated_at": utc_now()})
  stage4.write_json_atomic(run_state_path, run_state)
  append_event(root, "sample_structure_gate_passed" if gate_pass else
               "sample_structure_gate_failed",
               semantic_dataset_count=len(dataset_reports),
               zero_sample_workload_splits=zero_samples,
               zero_valid_decision_workload_splits=zero_decisions)
  if not gate_pass:
    message = ("Sample structure gate failed: zero_samples={} "
               "zero_valid_decisions={}").format(zero_samples, zero_decisions)
    raise RuntimeError(message)
  print("[OK] sample structure gate passed; no training/search/selection/freeze")


def verify_candidate_outputs(args):
  config, _, _, _ = load_context(args, require_traces=False)
  root = run_root(args, config)
  required = ("stage4_candidate.json", "validation_selection_report.json",
              "checkpoint_manifest.json", "verification.json")
  missing = [name for name in required
             if not os.path.isfile(os.path.join(root, name))]
  if missing:
    raise RuntimeError("Candidate outputs are incomplete: {}".format(missing))
  checkpoint_manifest = stage4.load_json(
      os.path.join(root, "checkpoint_manifest.json"))
  if set(int(seed) for seed in checkpoint_manifest["per_seed"]) != set(
      stage4.FORMAL_SEEDS):
    raise RuntimeError("Candidate checkpoint manifest lost a formal seed")
  candidate = stage4.load_json(os.path.join(root, "stage4_candidate.json"))[
      "candidate"]
  validate_formal_checkpoint_manifests(checkpoint_manifest, candidate)
  if os.path.exists(os.path.join(root, "final_stage4_freeze.json")):
    raise RuntimeError("Candidate verification refuses an unexpected formal freeze")
  print("[OK] candidate artifacts verified; formal freeze is absent")


def validate_formal_checkpoint_manifests(checkpoint_manifest, candidate):
  for seed in stage4.FORMAL_SEEDS:
    manifest = checkpoint_manifest["per_seed"].get(str(seed))
    if not isinstance(manifest, dict):
      raise RuntimeError("Missing checkpoint manifest for seed {}".format(seed))
    if manifest.get("selection_criterion") != "minimum_valid_loss_only":
      raise RuntimeError("Checkpoint was not selected by Validation only")
    best = manifest.get("checkpoints", {}).get("best", {})
    if (not os.path.isfile(best.get("path", "")) or
        stage4.fingerprint_file(best["path"]) != best.get("fingerprint")):
      raise RuntimeError("Best checkpoint SHA mismatch for seed {}".format(seed))
    for key, expected in candidate["model"].items():
      if manifest.get("model_args", {}).get(key) != expected:
        raise RuntimeError("Checkpoint model arg mismatch: {}".format(key))
    for key, expected in candidate["training"].items():
      if manifest.get("training_args", {}).get(key) != expected:
        raise RuntimeError("Checkpoint training arg mismatch: {}".format(key))
    if manifest.get("seed") != seed:
      raise RuntimeError("Checkpoint seed mismatch")
    if manifest.get("training_args", {}).get("device") != candidate.get(
        "execution", {}).get("device"):
      raise RuntimeError("Checkpoint actual device mismatch")


def training_contract(candidate, seed, dataset, authority, output, device,
                      train_workers):
  candidate = copy.deepcopy(candidate)
  candidate["training"]["num_workers"] = int(train_workers)
  candidate["candidate_sha256"] = stage4.fingerprint_value({
      key: value for key, value in candidate.items()
      if key != "candidate_sha256"})
  experiment_id = dataset["sample_cache_identity_sha256"][:24]
  return {
      "schema_version": stage4.TRAINING_CONTRACT_SCHEMA,
      "contract_id": stage4.CONTRACT_ID, "experiment_id": experiment_id,
      "candidate_id": candidate["candidate_id"], "candidate": candidate,
      "seed": int(seed),
      "expected_shape": {"H": candidate["history_H"], "K": 8,
                         "page_state_dim": 4},
      "sample_identity": {"schema_version": stage4.SAMPLE_SCHEMA,
                          "contract_id": stage4.CONTRACT_ID,
                          "experiment_id": experiment_id},
      "labels": {"lambda_1": candidate["label_weights"][0],
                 "lambda_2": candidate["label_weights"][1],
                 "lambda_3": candidate["label_weights"][2]},
      "model_args": copy.deepcopy(candidate["model"]),
      "training_args": copy.deepcopy(candidate["training"]),
      "data": copy.deepcopy(dataset["merged"]),
      "vocabulary": copy.deepcopy(dataset["vocabulary"]),
      "method": {"candidate_size_K": 8, "b_max": 2,
                 "initial_dram_state": "empty_dram_per_window",
                 "workloads": copy.deepcopy(authority["workloads"]),
                 "cost_profile": copy.deepcopy(authority["cost_profile"])},
      "authority": {
          "r4_freeze_sha256": authority["final_freeze_sha256"],
          "r2_manifest_sha256": stage4.R2_MANIFEST_SHA256,
          "prepared_input_manifest_sha256":
              dataset["sample_cache_identity"][
                  "prepared_input_manifest_sha256"],
          "sample_generation_contract_sha256":
              dataset["sample_cache_identity_sha256"],
          "vocabulary_sha256": dataset["vocabulary"]["vocabulary_sha256"],
      },
      "execution": {"requested_device": device, "actual_device": device,
                    "train_workers": train_workers,
                    "single_gpu_training_process": True},
      "output_directory": os.path.abspath(output),
      "test_trace_opened": False, "pressure_trace_opened": False,
  }


def ensure_training(args, root, candidate, seed, dataset, authority):
  output = os.path.join(root, "checkpoints", candidate["candidate_id"],
                        "seed_{}".format(seed))
  os.makedirs(output, exist_ok=True)
  contract = training_contract(candidate, seed, dataset, authority, output,
                               args.device, args.train_workers)
  contract_path = os.path.join(output, "training_contract.json")
  manifest_path = os.path.join(output, "checkpoint_manifest.json")
  if os.path.isfile(contract_path):
    if stage4.load_json(contract_path) != contract:
      raise RuntimeError("Resume contract changed: {}".format(output))
  else:
    stage4.write_json_atomic(contract_path, contract)
  if os.path.isfile(manifest_path):
    manifest = stage4.load_json(manifest_path)
    best = manifest["checkpoints"]["best"]
    if (manifest.get("stage4_training_contract_fingerprint") !=
        stage4.fingerprint_value(contract) or
        stage4.fingerprint_file(best["path"]) != best["fingerprint"]):
      raise RuntimeError("Existing checkpoint identity mismatch")
    return manifest, contract
  command = [
      sys.executable, "-m", "qmap.qmap_train",
      "--train_data", dataset["merged"]["train"]["path"],
      "--valid_data", dataset["merged"]["validation"]["path"],
      "--proactive_stage4_contract", contract_path,
      "--output_dir", output, "--seed", str(seed),
      "--device", args.device, "--num_workers", str(args.train_workers),
      "--ablation", candidate["model"]["ablation"]]
  last = os.path.join(output, "qmap_last.pth")
  if os.path.isfile(last):
    command.extend(["--resume_checkpoint", last])
  log_path = os.path.join(root, "logs", "train_{}_{}.log".format(
      candidate["candidate_id"], seed))
  environment = dict(os.environ)
  environment["PYTHONHASHSEED"] = str(seed)
  environment.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
  append_event(root, "training_started", candidate=candidate["candidate_id"],
               seed=seed, active_training_processes=1)
  with open(log_path, "a", encoding="utf-8", newline="\n") as log:
    completed = subprocess.run(command, cwd=args.project_root, env=environment,
                               stdout=log, stderr=subprocess.STDOUT)
  append_event(root, "training_finished", candidate=candidate["candidate_id"],
               seed=seed, returncode=completed.returncode,
               active_training_processes=0)
  if completed.returncode != 0:
    raise RuntimeError("Training failed; inspect {}".format(log_path))
  return stage4.load_json(manifest_path), contract


def replay_worker(payload):
  entry, checkpoint, candidate, authority, seed = payload
  trace, _ = proactive_stage3._read_compact_trace(
      entry["resolved_trace_path"], int(entry["page_shift"]))
  expected = (int(entry["source_interval"]["end_exclusive"]) -
              int(entry["source_interval"]["start_inclusive"]))
  if len(trace) != expected or len(trace) != int(entry["accesses"]):
    raise RuntimeError("Trace/source interval mismatch in replay worker")
  return stage4.evaluate_checkpoint_windows(
      trace, entry["workload"], checkpoint, "cpu", seed, candidate, authority)


def evaluate_seed(args, root, candidate, seed, checkpoint_manifest, authority,
                  entries):
  checkpoint = checkpoint_manifest["checkpoints"]["best"]["path"]
  validation = [entry for entry in entries
                if entry["split_role"] == "validation"]
  payloads = [(entry, checkpoint, candidate, authority, seed)
              for entry in validation]
  if args.replay_workers == 1:
    rows = [replay_worker(item) for item in payloads]
  else:
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(args.replay_workers, 6)) as executor:
      rows = list(executor.map(replay_worker, payloads))
  rows.sort(key=lambda row: stage4.WORKLOADS.index(row["workload"]))
  path = os.path.join(root, "search", candidate["phase"],
                      candidate["candidate_id"],
                      "validation_seed_{}.json".format(seed))
  stage4.write_json_atomic(path, {"rows": rows, "seed": seed,
                                  "candidate_id": candidate["candidate_id"]})
  return rows


def candidate_summary(candidate, seed_results, checkpoint_manifests):
  if set(seed_results) != set(stage4.FORMAL_SEEDS):
    raise RuntimeError("Candidate is missing a formal seed")
  per_workload = {}
  for workload in stage4.WORKLOADS:
    rows = [row for seed in stage4.FORMAL_SEEDS for row in seed_results[seed]
            if row["workload"] == workload]
    if len(rows) != len(stage4.FORMAL_SEEDS):
      raise RuntimeError("Candidate is missing workload/seed Validation rows")
    per_workload[workload] = stage4.macro_mean(
        [row["weighted_cost_per_access"] for row in rows])
  macro_by_seed = [stage4.macro_mean(
      [row["weighted_cost_per_access"] for row in seed_results[seed]])
                   for seed in stage4.FORMAL_SEEDS]
  ndcg = stage4.macro_mean([row["ndcg_at_b_t"]
                            for rows in seed_results.values() for row in rows])
  losses = [checkpoint_manifests[seed]["best_validation_loss"]
            for seed in stage4.FORMAL_SEEDS]
  model = candidate["model"]
  complexity = (model["hidden_dim"] * model["num_layers"] *
                model["feedforward_dim"])
  return {
      "candidate": candidate,
      "primary_metric": stage4.macro_mean(macro_by_seed),
      "worst_workload_metric": max(per_workload.values()),
      "macro_ndcg_at_b_t": ndcg,
      "mean_best_validation_loss": stage4.macro_mean(losses),
      "complexity_proxy": complexity, "per_workload": per_workload,
      "validation_rows": [row for seed in stage4.FORMAL_SEEDS
                           for row in seed_results[seed]],
      "all_formal_seeds_retained": True,
      "checkpoint_manifests": {
          str(seed): checkpoint_manifests[seed] for seed in stage4.FORMAL_SEEDS},
  }


def selection_key(summary):
  return (summary["primary_metric"], summary["worst_workload_metric"],
          -summary["macro_ndcg_at_b_t"],
          summary["mean_best_validation_loss"], summary["complexity_proxy"],
          summary["candidate"]["candidate_id"])


def run_search(args):
  config, authority, _, entries = load_context(args)
  root = run_root(args, config)
  require_search_confirmation(root, args)
  if config.get("execution", {}).get("require_cuda") and not args.require_cuda:
    raise RuntimeError("Formal search requires explicit --require-cuda")
  device = runtime_device(args.device, args.require_cuda)
  if device["actual"] == "cuda" and device["cuda_device_count"] != 1:
    raise RuntimeError("Search requires exactly one visible CUDA device")
  args.device = device["actual"]
  stage4.write_json_atomic(os.path.join(root, "search_state.json"), {
      "status": "running", "completed_phases": [],
      "active_training_processes": 0, "formal_freeze": False,
      "updated_at": utc_now()})
  inherited = None
  all_phase_results = []
  dataset_indexes = {}
  for phase_name in ("semantic", "architecture", "optimization"):
    candidates = stage4.resolve_phase_candidates(config, phase_name, inherited)
    phase_results = []
    phase_failures = []
    for candidate in candidates:
      try:
        candidate["training"]["num_workers"] = int(args.train_workers)
        candidate["execution"] = {
            "device": args.device, "require_cuda": bool(args.require_cuda),
            "train_workers": int(args.train_workers),
            "sample_workers": int(args.sample_workers),
            "replay_workers": int(args.replay_workers),
            "single_gpu_training_process": True,
        }
        candidate["candidate_sha256"] = stage4.fingerprint_value({
            key: value for key, value in candidate.items()
            if key != "candidate_sha256"})
        dataset = ensure_dataset(args, root, candidate, authority, entries)
        dataset_indexes[dataset["semantic_key"]] = {
            "sample_manifest_path": os.path.join(
                root, "datasets", dataset["semantic_key"], "sample_manifest.json"),
            "sample_manifest_sha256": stage4.fingerprint_file(os.path.join(
                root, "datasets", dataset["semantic_key"], "sample_manifest.json")),
            "vocabulary": dataset["vocabulary"]}
        seed_results, manifests = {}, {}
        for seed in stage4.FORMAL_SEEDS:  # Deliberately sequential on one GPU.
          manifests[seed], _ = ensure_training(
              args, root, candidate, seed, dataset, authority)
          seed_results[seed] = evaluate_seed(
              args, root, candidate, seed, manifests[seed], authority, entries)
        phase_results.append(candidate_summary(
            candidate, seed_results, manifests))
      except Exception as error:  # Preserve artifacts and reject this candidate.
        failure = {"candidate_id": candidate["candidate_id"],
                   "status": "rejected", "reason": str(error),
                   "failed_at": utc_now()}
        phase_failures.append(failure)
        failure_path = os.path.join(root, "search", phase_name,
                                    candidate["candidate_id"], "failure.json")
        stage4.write_json_atomic(failure_path, failure)
        append_event(root, "candidate_rejected", phase=phase_name,
                     candidate=candidate["candidate_id"], reason=str(error))
    if not phase_results:
      raise RuntimeError("Every candidate failed in phase {}".format(phase_name))
    phase_results.sort(key=selection_key)
    winner = phase_results[0]
    inherited = copy.deepcopy(winner["candidate"])
    phase_path = os.path.join(root, "search", phase_name, "phase_result.json")
    stage4.write_json_atomic(phase_path, {
        "phase": phase_name, "winner": winner, "evaluated": phase_results,
        "failures": phase_failures,
        "selection_key": list(selection_key(winner)),
        "test_trace_opened": False, "pressure_trace_opened": False})
    all_phase_results.append({"phase": phase_name, "winner": winner,
                              "evaluated": phase_results,
                              "failures": phase_failures,
                              "result_path": phase_path,
                              "result_sha256": stage4.fingerprint_file(phase_path)})
    append_event(root, "phase_completed", phase=phase_name,
                 winner=winner["candidate"]["candidate_id"])
    stage4.write_json_atomic(os.path.join(root, "search_state.json"), {
        "status": "running", "completed_phases": [
            item["phase"] for item in all_phase_results],
        "current_winner": winner["candidate"]["candidate_id"],
        "active_training_processes": 0, "formal_freeze": False,
        "updated_at": utc_now()})
  final = all_phase_results[-1]["winner"]
  report = {
      "schema_version": "capd_proactive_stage4_stage7_selection_report_v1_0",
      "run_id": args.run_id, "selection": config["selection"],
      "phase_results": all_phase_results, "selected": final,
      "candidate_only": True, "formal_freeze": False,
      "all_formal_seeds_retained": True,
      "test_trace_opened": False, "pressure_trace_opened": False,
  }
  report_path = os.path.join(root, "validation_selection_report.json")
  stage4.write_json_atomic(report_path, report)
  stage4.write_json_atomic(os.path.join(root, "stage4_candidate.json"), {
      "schema_version": "capd_proactive_stage4_stage7_candidate_v1_0",
      "run_id": args.run_id, "candidate": final["candidate"],
      "formal_seeds": list(stage4.FORMAL_SEEDS),
      "selection_report_sha256": stage4.fingerprint_file(report_path),
      "status": "candidate_awaiting_explicit_formal_freeze",
      "formal_freeze": False})
  checkpoint_manifest = {
      "schema_version": "capd_proactive_stage4_stage7_checkpoint_manifest_v1_0",
      "candidate_id": final["candidate"]["candidate_id"],
      "formal_seeds": list(stage4.FORMAL_SEEDS),
      "per_seed": final["checkpoint_manifests"],
      "seed_selection_performed": False, "formal_freeze": False}
  stage4.write_json_atomic(os.path.join(root, "checkpoint_manifest.json"),
                           checkpoint_manifest)
  stage4.write_json_atomic(os.path.join(root, "sample_manifest.json"), {
      "schema_version": "capd_proactive_stage4_stage7_sample_index_v1_0",
      "datasets": dataset_indexes, "formal_freeze": False})
  stage4.write_json_atomic(os.path.join(root, "vocabulary_manifest.json"), {
      "schema_version": "capd_proactive_stage4_stage7_vocabulary_index_v1_0",
      "fit_scope": "six_train_only", "datasets": {
          key: value["vocabulary"] for key, value in dataset_indexes.items()},
      "all_seeds_share_each_semantic_vocabulary": True,
      "validation_used_for_fit": False, "formal_freeze": False})
  write_metrics(root, all_phase_results)
  evidence_names = (
      "resolved_config.json", "stage3_authority.json", "input_manifest.json",
      "training_contract.json", "search_space.json", "sample_manifest.json",
      "confirmed_search_contract.json", "search_contract_confirmation.json",
      "vocabulary_manifest.json", "validation_metrics.csv",
      "validation_metrics_by_workload.csv", "stage4_candidate.json",
      "validation_selection_report.json", "checkpoint_manifest.json")
  evidence_sha = {name: stage4.fingerprint_file(os.path.join(root, name))
                  for name in evidence_names}
  stage4.write_json_atomic(os.path.join(root, "verification.json"), {
      "schema_version": "capd_proactive_stage4_stage7_verification_v1_0",
      "status": "candidate_verified_awaiting_formal_freeze",
      "candidate_artifacts_present": True, "formal_freeze_created": False,
      "artifact_sha256": evidence_sha,
      "r4_freeze_sha256": authority["final_freeze_sha256"],
      "r2_manifest_sha256": stage4.R2_MANIFEST_SHA256,
      "test_trace_opened": False, "pressure_trace_opened": False})
  state = stage4.load_json(os.path.join(root, "run_state.json"))
  state.update({"status": "candidate_ready_awaiting_formal_freeze",
                "formal_freeze": False, "updated_at": utc_now()})
  stage4.write_json_atomic(os.path.join(root, "run_state.json"), state)
  stage4.write_json_atomic(os.path.join(root, "search_state.json"), {
      "status": "completed_candidate_ready", "completed_phases": [
          "semantic", "architecture", "optimization"],
      "selected_candidate": final["candidate"]["candidate_id"],
      "active_training_processes": 0, "formal_freeze": False,
      "updated_at": utc_now()})
  print("[OK] candidate generated; formal freeze was NOT created")


def write_metrics(root, phase_results):
  aggregate_path = os.path.join(root, "validation_metrics.csv")
  workload_path = os.path.join(root, "validation_metrics_by_workload.csv")
  with open(aggregate_path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["phase", "candidate_id", "primary_metric",
                     "worst_workload_metric", "macro_ndcg_at_b_t",
                     "mean_best_validation_loss"])
    for phase in phase_results:
      for item in phase["evaluated"]:
        writer.writerow([phase["phase"], item["candidate"]["candidate_id"],
                         item["primary_metric"], item["worst_workload_metric"],
                         item["macro_ndcg_at_b_t"],
                         item["mean_best_validation_loss"]])
  with open(workload_path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["phase", "candidate_id", "seed", "workload",
                     "weighted_cost_per_access", "ndcg_at_b_t",
                     "valid_decision_count"])
    for phase in phase_results:
      for item in phase["evaluated"]:
        for row in item["validation_rows"]:
          writer.writerow([phase["phase"], item["candidate"]["candidate_id"],
                           row["seed"], row["workload"],
                           row["weighted_cost_per_access"],
                           row["ndcg_at_b_t"], row["valid_decision_count"]])


def freeze(args):
  if not args.confirm_stage4_freeze:
    raise RuntimeError("Formal freeze requires --confirm-stage4-freeze")
  config, authority, _, _ = load_context(args, require_traces=False)
  root = run_root(args, config)
  candidate_path = os.path.join(root, "stage4_candidate.json")
  report_path = os.path.join(root, "validation_selection_report.json")
  checkpoint_path = os.path.join(root, "checkpoint_manifest.json")
  for path in (candidate_path, report_path, checkpoint_path):
    if not os.path.isfile(path):
      raise RuntimeError("Candidate artifact is missing: {}".format(path))
  candidate = stage4.load_json(candidate_path)
  if args.candidate != candidate["candidate"]["candidate_id"]:
    raise RuntimeError("Explicit candidate ID does not match selected candidate")
  checkpoint_manifest = stage4.load_json(checkpoint_path)
  if set(int(seed) for seed in checkpoint_manifest["per_seed"]) != set(
      stage4.FORMAL_SEEDS):
    raise RuntimeError("Formal freeze requires all three seed checkpoints")
  validate_formal_checkpoint_manifests(
      checkpoint_manifest, candidate["candidate"])
  formal = {
      "schema_version": "capd_proactive_stage4_stage7_final_freeze_v1_0",
      "run_id": args.run_id, "formal_freeze": True,
      "human_confirmation": True, "frozen_at": utc_now(),
      "candidate": candidate["candidate"],
      "formal_seeds": list(stage4.FORMAL_SEEDS),
      "stage3_authority": authority,
      "selection_report_sha256": stage4.fingerprint_file(report_path),
      "checkpoint_manifest_sha256": stage4.fingerprint_file(checkpoint_path),
  }
  formal_path = os.path.join(root, "final_stage4_freeze.json")
  stage4.write_json_atomic(formal_path, formal)
  formal_checkpoint_manifest = copy.deepcopy(checkpoint_manifest)
  formal_checkpoint_manifest["formal_freeze"] = True
  formal_checkpoint_manifest["frozen_at"] = formal["frozen_at"]
  stage4.write_json_atomic(os.path.join(root, "formal_checkpoint_manifest.json"),
                           formal_checkpoint_manifest)
  stage4.write_json_atomic(os.path.join(root, "stage8_model_contract.json"), {
      "schema_version": "capd_stage8_model_contract_v1_0",
      "stage4_freeze_path": formal_path,
      "stage4_freeze_sha256": stage4.fingerprint_file(formal_path),
      "candidate": candidate["candidate"],
      "formal_seeds": list(stage4.FORMAL_SEEDS),
      "standard_pressure_same_model_checkpoint_seed_required": True,
      "checkpoint_manifest": formal_checkpoint_manifest,
  })
  state = stage4.load_json(os.path.join(root, "run_state.json"))
  state.update({"status": "stage4_formally_frozen", "formal_freeze": True,
                "updated_at": utc_now()})
  stage4.write_json_atomic(os.path.join(root, "run_state.json"), state)
  print("[FINAL] STAGE4_STAGE7_FORMALLY_FROZEN")


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("command", choices=("preflight", "confirm-contract",
                                          "samples", "search", "resume",
                                          "candidate", "all", "freeze"))
  parser.add_argument("--config", default=(
      "configs/finals/capd_proactive_stage4_stage7_search.json"))
  parser.add_argument("--stage3-freeze", required=True)
  parser.add_argument("--input-manifest", required=True)
  parser.add_argument("--run-id", default=stage4.RUN_ID)
  parser.add_argument("--project-root", default=PROJECT_ROOT)
  parser.add_argument("--device", choices=("auto", "cuda", "cpu"),
                      default="auto")
  parser.add_argument("--require-cuda", action="store_true")
  parser.add_argument("--train-workers", type=int, default=4)
  parser.add_argument("--sample-workers", type=int, default=6)
  parser.add_argument("--replay-workers", type=int, default=6)
  parser.add_argument("--confirm-stage4-search", action="store_true")
  parser.add_argument("--confirm-stage4-freeze", action="store_true")
  parser.add_argument("--candidate")
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  for field in ("train_workers", "sample_workers", "replay_workers"):
    if getattr(args, field) <= 0:
      raise ValueError("Worker counts must be positive")
  if args.command == "preflight":
    preflight(args)
  elif args.command == "confirm-contract":
    confirm_contract(args)
  elif args.command in ("search", "resume"):
    run_search(args)
  elif args.command == "samples":
    generate_draft_samples(args)
  elif args.command == "candidate":
    verify_candidate_outputs(args)
  elif args.command == "all":
    config = stage4.validate_search_config(stage4.load_json(args.config))
    root = run_root(args, config)
    if not os.path.isfile(os.path.join(root, "resolved_config.json")):
      preflight(args)
    run_search(args)  # Confirmation is still required; formal freeze is not run.
  elif args.command == "freeze":
    freeze(args)


if __name__ == "__main__":
  main()
