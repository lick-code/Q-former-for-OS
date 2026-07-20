# coding=utf-8
"""Run one resolved CAPD finals_v2.1 workload/B pipeline on the server."""

from __future__ import print_function

import argparse
import json
import os
import shlex
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config


CLASSICAL_BASELINES = ("lru", "random", "lfu", "clock")
LEARNED_BASELINES = ("kleio_lite", "patterns_lite")


def run_layout(config):
  workload = config["run"]["workload"]
  pool_size = int(config["candidate"]["pool_size_B"])
  suffix = os.path.join(workload, "B{}".format(pool_size))
  return {
      "jsonl_dir": os.path.join(config["outputs"]["jsonl_root"], suffix),
      "checkpoint_dir": os.path.join(
          config["outputs"]["checkpoint_root"], suffix),
      "result_dir": os.path.join(config["outputs"]["result_root"], suffix),
      "baseline_model_dir": os.path.join(
          config["outputs"]["checkpoint_root"], workload, "baselines"),
  }


def artifact_paths(config):
  layout = run_layout(config)
  jsonl_dir = layout["jsonl_dir"]
  result_dir = layout["result_dir"]
  paths = dict(layout)
  paths.update({
      "selector": os.path.join(jsonl_dir, "selector_params.json"),
      "selector_validation": os.path.join(
          jsonl_dir, "selector_validation_samples.jsonl"),
      "train_jsonl": os.path.join(jsonl_dir, "train.jsonl"),
      "valid_jsonl": os.path.join(jsonl_dir, "valid.jsonl"),
      "generator_summary": os.path.join(jsonl_dir, "generator_summary.json"),
      "qmap_result": os.path.join(result_dir, "qmap.json"),
      "summary": os.path.join(result_dir, "summary.json"),
      "manifest": os.path.join(result_dir, "run_manifest.json"),
  })
  return paths


def command_text(command):
  return " ".join(shlex.quote(value) for value in command)


def execute(command, dry_run=False):
  print("$ {}".format(command_text(command)), flush=True)
  if not dry_run:
    subprocess.check_call(command, cwd=PROJECT_ROOT)


def generation_command(python_bin, config_path, paths):
  return [
      python_bin, "-m", "qmap.finals_generator", "--config", config_path,
      "--selector-output", paths["selector"],
      "--validation-samples-output", paths["selector_validation"],
      "--train-output", paths["train_jsonl"],
      "--valid-output", paths["valid_jsonl"],
      "--summary-output", paths["generator_summary"]]


def training_command(python_bin, config_path, paths, device=None):
  command = [
      python_bin, "-m", "qmap.qmap_train",
      "--config", config_path,
      "--selector_params", paths["selector"],
      "--train_data", paths["train_jsonl"],
      "--valid_data", paths["valid_jsonl"],
      "--output_dir", paths["checkpoint_dir"]]
  if device:
    command.extend(["--device", device])
  return command


def eval_command(python_bin, config_path, paths, policy, learned_model=None,
                 device=None):
  result_path = os.path.join(paths["result_dir"], "{}.json".format(policy))
  command = [python_bin, "-m", "qmap.qmap_eval", "--config", config_path,
             "--policy", policy, "--json_output", result_path]
  if policy == "qmap":
    command.extend([
        "--selector_params", paths["selector"], "--checkpoint",
        os.path.join(paths["checkpoint_dir"], "qmap_best.pth")])
    if device:
      command.extend(["--device", device])
  elif learned_model:
    command.extend(["--learned_model", learned_model])
  return command


def learned_train_command(python_bin, config_path, policy, model_path):
  return [
      python_bin, "-m", "qmap.learned_baselines", "--policy", policy,
      "--config", config_path, "--model_output", model_path]


def write_summary(config, paths, policies):
  results = {}
  for policy in policies:
    path = os.path.join(paths["result_dir"], "{}.json".format(policy))
    if os.path.exists(path):
      results[policy] = finals_config.load_json(path)
  summary = {
      "schema_version": finals_config.SCHEMA_VERSION,
      "workload": config["run"]["workload"],
      "experiment_contract": finals_config.contract_from_config(config),
      "config_fingerprint": finals_config.config_fingerprint(config),
      "results": results,
  }
  finals_config.write_json(paths["summary"], summary)
  return summary


def main():
  parser = argparse.ArgumentParser(description="Run one CAPD finals_v2.1 job.")
  parser.add_argument("--config", required=True)
  parser.add_argument("--stage", choices=("generate", "train", "eval", "all"),
                      default="all")
  parser.add_argument("--include-baselines", action="store_true")
  parser.add_argument("--retrain-learned-baselines", action="store_true")
  parser.add_argument("--device", default=None)
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--dry-run", action="store_true")
  args = parser.parse_args()

  config_path = os.path.abspath(args.config)
  config = finals_config.load_config(config_path, require_resolved=True)
  paths = artifact_paths(config)
  for key in ("jsonl_dir", "checkpoint_dir", "result_dir",
              "baseline_model_dir"):
    os.makedirs(paths[key], exist_ok=True)
  for directory in (paths["jsonl_dir"], paths["checkpoint_dir"],
                    paths["result_dir"]):
    finals_config.write_json(
        os.path.join(directory, "resolved_config.json"), config)

  commands = []
  if args.stage in ("generate", "all"):
    commands.append(generation_command(args.python, config_path, paths))
  if args.stage in ("train", "all"):
    commands.append(training_command(
        args.python, config_path, paths, device=args.device))
  evaluated_policies = []
  if args.stage in ("eval", "all"):
    commands.append(eval_command(
        args.python, config_path, paths, "qmap", device=args.device))
    evaluated_policies.append("qmap")
    if args.include_baselines:
      for policy in CLASSICAL_BASELINES:
        commands.append(eval_command(
            args.python, config_path, paths, policy))
        evaluated_policies.append(policy)
      for policy in LEARNED_BASELINES:
        model_path = os.path.join(
            paths["baseline_model_dir"], "{}.json".format(policy))
        if args.retrain_learned_baselines or not os.path.exists(model_path):
          commands.append(learned_train_command(
              args.python, config_path, policy, model_path))
        commands.append(eval_command(
            args.python, config_path, paths, policy,
            learned_model=model_path))
        evaluated_policies.append(policy)

  stage_key = args.stage + ("_dry_run" if args.dry_run else "")
  stage_manifest_path = os.path.join(
      paths["result_dir"], "run_manifest_{}.json".format(stage_key))
  stage_manifest = {
      "schema_version": finals_config.SCHEMA_VERSION,
      "config": config_path,
      "config_fingerprint": finals_config.config_fingerprint(config),
      "git_commit": config.get("run", {}).get("git_commit", "unknown"),
      "commands": [command_text(command) for command in commands],
      "stage": args.stage,
      "include_baselines": args.include_baselines,
      "validation_strategy": config["validation"]["strategy"],
      "dry_run": args.dry_run,
  }
  finals_config.write_json(stage_manifest_path, stage_manifest)
  manifest_index = {
      "schema_version": finals_config.SCHEMA_VERSION,
      "config": config_path,
      "config_fingerprint": finals_config.config_fingerprint(config),
      "git_commit": config.get("run", {}).get("git_commit", "unknown"),
      "stage_manifests": {},
  }
  if os.path.exists(paths["manifest"]):
    existing = finals_config.load_json(paths["manifest"])
    if (existing.get("schema_version") == finals_config.SCHEMA_VERSION and
        existing.get("config_fingerprint") ==
        manifest_index["config_fingerprint"]):
      manifest_index["stage_manifests"].update(
          existing.get("stage_manifests", {}))
  manifest_index["stage_manifests"][stage_key] = os.path.basename(
      stage_manifest_path)
  finals_config.write_json(paths["manifest"], manifest_index)
  for command in commands:
    execute(command, dry_run=args.dry_run)
  if evaluated_policies and not args.dry_run:
    write_summary(config, paths, evaluated_policies)
    print("[done] summary={}".format(paths["summary"]))


if __name__ == "__main__":
  main()
