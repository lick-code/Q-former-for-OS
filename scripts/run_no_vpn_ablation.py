# coding=utf-8
"""Run the paired CAPD Full/NoVPN B64 experiment without regenerating data."""

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
from qmap import no_vpn_ablation


WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")
SEEDS = (3136859, 42, 2026)
BASE_CONFIGS = {
    "full": "configs/finals/capd_direction1_v3_ablation_full.json",
    "no_vpn": "configs/finals/capd_direction1_v3_no_vpn.json",
}


def project_path(path):
  return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def relative(path):
  return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(
      os.sep, "/")


def command_text(command):
  return " ".join(shlex.quote(str(value)) for value in command)


def canonical_data_paths(workload):
  root = project_path(os.path.join(
      "dataset", "jsonl", "finals_v3_official", workload, "B64"))
  return {
      "root": root,
      "config": os.path.join(root, "resolved_config.json"),
      "selector": os.path.join(root, "selector_params.json"),
      "train": os.path.join(root, "train.jsonl"),
      "valid": os.path.join(root, "valid.jsonl"),
  }


def run_paths(base_config, variant, workload, seed):
  seed_name = "seed_{}".format(seed)
  checkpoint_dir = project_path(os.path.join(
      base_config["outputs"]["checkpoint_root"], workload, seed_name))
  result_dir = project_path(os.path.join(
      base_config["outputs"]["result_root"], workload, seed_name))
  log_dir = project_path(os.path.join(
      base_config["outputs"]["log_root"], workload, seed_name))
  resolved_config = project_path(os.path.join(
      base_config["outputs"]["log_root"], "resolved_configs",
      "{}_B64.json".format(workload)))
  return {
      "checkpoint_dir": checkpoint_dir,
      "best_checkpoint": os.path.join(checkpoint_dir, "qmap_best.pth"),
      "last_checkpoint": os.path.join(checkpoint_dir, "qmap_last.pth"),
      "checkpoint_manifest": os.path.join(
          checkpoint_dir, "checkpoint_manifest.json"),
      "result_dir": result_dir,
      "result": os.path.join(result_dir, "qmap.json"),
      "log_dir": log_dir,
      "train_log": os.path.join(log_dir, "train.log"),
      "eval_log": os.path.join(log_dir, "eval.log"),
      "resolved_config": resolved_config,
      "variant": variant,
  }


def load_base_configs():
  configs = {
      variant: finals_config.load_config(project_path(path))
      for variant, path in BASE_CONFIGS.items()
  }
  no_vpn_ablation.assert_config_pair(
      configs["full"], configs["no_vpn"], allow_resolved=False)
  reference = finals_config.load_config(
      project_path("configs/finals/capd_direction1_v3.json"))
  for config in configs.values():
    no_vpn_ablation.assert_variant_matches_reference(reference, config)
  return configs


def materialize_configs(base_configs, workload):
  data = canonical_data_paths(workload)
  canonical = finals_config.load_config(
      data["config"], require_resolved=True, project_root=PROJECT_ROOT,
      verify_manifest_files=False)
  if (canonical["candidate"]["pool_size_B"] != 64 or
      canonical["run"]["workload"] != workload):
    raise ValueError("NoVPN ablation requires the official workload B64 data.")
  resolved = {
      variant: no_vpn_ablation.materialize_resolved_config(
          canonical, base_configs[variant])
      for variant in no_vpn_ablation.VARIANTS
  }
  no_vpn_ablation.assert_config_pair(
      resolved["full"], resolved["no_vpn"], allow_resolved=True)
  for variant, config in resolved.items():
    path = run_paths(
        base_configs[variant], variant, workload, SEEDS[0])["resolved_config"]
    finals_config.write_json(path, config)
  return resolved


def execute(command, log_path, dry_run=False):
  print("[command] {}".format(command_text(command)), flush=True)
  if dry_run:
    return
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  with open(log_path, "w", encoding="utf-8", newline="\n") as log_file:
    process = subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
      sys.stdout.write(line)
      log_file.write(line)
      log_file.flush()
    return_code = process.wait()
  if return_code != 0:
    raise subprocess.CalledProcessError(return_code, command)


def git_state():
  def output(command):
    try:
      return subprocess.check_output(
          command, cwd=PROJECT_ROOT, stderr=subprocess.STDOUT,
          text=True).strip()
    except (OSError, subprocess.CalledProcessError):
      return "unknown"
  status = output(["git", "status", "--porcelain", "--untracked-files=no"])
  return {
      "commit": output(["git", "rev-parse", "HEAD"]),
      "tracked_worktree_dirty": bool(status and status != "unknown"),
  }


def training_command(python_bin, device, seed, resolved_config, data, paths,
                     resume):
  command = [
      python_bin, "-m", "qmap.qmap_train",
      "--config", paths["resolved_config"],
      "--selector_params", data["selector"],
      "--train_data", data["train"],
      "--valid_data", data["valid"],
      "--output_dir", paths["checkpoint_dir"],
      "--seed", str(seed),
      "--device", device,
      "--ablation", "cross_attention",
  ]
  if resume:
    command.extend(["--resume_checkpoint", paths["last_checkpoint"]])
  return command


def evaluation_command(python_bin, device, paths, data):
  return [
      python_bin, "-m", "qmap.qmap_eval",
      "--config", paths["resolved_config"],
      "--evaluation_split", "test",
      "--selector_params", data["selector"],
      "--policy", "qmap",
      "--checkpoint", paths["best_checkpoint"],
      "--device", device,
      "--json_output", paths["result"],
  ]


def result_is_complete(path, variant, workload, seed, config_hash):
  if not os.path.exists(path):
    return False
  try:
    result = finals_config.load_json(path)
  except (OSError, ValueError, json.JSONDecodeError):
    return False
  return (
      result.get("variant") == variant and
      result.get("workload") == workload and
      int(result.get("seed", -1)) == int(seed) and
      result.get("config_hash") == config_hash and
      all(key in result for key in (
          "weighted_access_cost", "hit_rate", "nvm_reads", "nvm_writes",
          "migrations", "best_epoch", "validation_metric")))


def annotate_result(paths, variant, workload, seed, config, data):
  result = finals_config.load_json(paths["result"])
  manifest = finals_config.load_json(paths["checkpoint_manifest"])
  config_hash = finals_config.config_fingerprint(config)
  source_manifest = config["data"]["source_manifest"]
  test_metrics = {
      key: result[key] for key in (
          "weighted_access_cost", "hit_rate", "hit_rate_percent",
          "nvm_reads", "nvm_writes", "migrations",
          "decision_time_seconds", "avg_decision_time_ms")
      if key in result
  }
  result.update({
      "variant": variant,
      "seed": int(seed),
      "config_path": relative(paths["resolved_config"]),
      "config_hash": config_hash,
      "config_file_sha256": finals_config.fingerprint_file(
          paths["resolved_config"]),
      "data_config_path": relative(data["config"]),
      "data_config_hash": finals_config.config_fingerprint(
          finals_config.load_config(
              data["config"], require_resolved=True,
              project_root=PROJECT_ROOT, verify_manifest_files=False)),
      "data_manifest": source_manifest,
      "data_manifest_hash": finals_config.fingerprint_file(
          project_path(source_manifest)),
      "checkpoint_path": relative(paths["best_checkpoint"]),
      "checkpoint_fingerprint": finals_config.fingerprint_file(
          paths["best_checkpoint"]),
      "git_state": git_state(),
      "best_epoch": int(manifest["best_epoch"]),
      "validation_metric": {
          "name": "validation_loss",
          "value": float(manifest["best_validation_loss"]),
          "selection": "minimum_valid_loss_only",
      },
      "training_time_seconds": manifest.get("training_duration_seconds"),
      "demotions": int(result["migrations"]),
      "test_metrics": test_metrics,
  })
  finals_config.write_json(paths["result"], result)


def run_one(args, base_config, resolved_config, variant, workload, seed):
  data = canonical_data_paths(workload)
  paths = run_paths(base_config, variant, workload, seed)
  config_hash = finals_config.config_fingerprint(resolved_config)
  print(
      "[run] variant={} workload={} seed={}".format(
          variant, workload, seed), flush=True)
  if args.skip_existing and result_is_complete(
      paths["result"], variant, workload, seed, config_hash):
    print("[skip] valid result exists: {}".format(
        relative(paths["result"])), flush=True)
    return
  if not args.dry_run:
    for key in ("checkpoint_dir", "result_dir", "log_dir"):
      os.makedirs(paths[key], exist_ok=True)

  training_complete = (
      os.path.exists(paths["checkpoint_manifest"]) and
      os.path.exists(paths["best_checkpoint"]))
  resume_checkpoint = (
      args.resume and not training_complete and
      os.path.exists(paths["last_checkpoint"]))
  if not training_complete:
    execute(
        training_command(
            args.python, args.device, seed, resolved_config, data, paths,
            resume=resume_checkpoint),
        paths["train_log"], dry_run=args.dry_run)
  elif args.resume:
    print("[resume] training already complete: {}".format(
        relative(paths["checkpoint_manifest"])), flush=True)
  else:
    execute(
        training_command(
            args.python, args.device, seed, resolved_config, data, paths,
            resume=False),
        paths["train_log"], dry_run=args.dry_run)

  execute(
      evaluation_command(args.python, args.device, paths, data),
      paths["eval_log"], dry_run=args.dry_run)
  if not args.dry_run:
    annotate_result(
        paths, variant, workload, seed, resolved_config, data)
    print("[done] result={}".format(relative(paths["result"])), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Run strict CAPD Full versus NoVPN B64 ablation.")
  parser.add_argument(
      "--variant", choices=("full", "no_vpn", "both"), default="both")
  parser.add_argument(
      "--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
  parser.add_argument(
      "--seeds", nargs="+", type=int, default=list(SEEDS))
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument(
      "--resume", action="store_true",
      help="Resume qmap_last.pth or reuse a completed training manifest.")
  parser.add_argument(
      "--skip-existing", action="store_true",
      help="Skip only results whose variant/workload/seed/config metadata pass.")
  parser.add_argument("--prepare-only", action="store_true")
  parser.add_argument("--dry-run", action="store_true")
  return parser


def main():
  args = build_arg_parser().parse_args()
  if not args.seeds:
    raise ValueError("At least one seed is required.")
  if any(seed < 0 for seed in args.seeds):
    raise ValueError("Seeds must be non-negative.")
  base_configs = load_base_configs()
  variants = (no_vpn_ablation.VARIANTS if args.variant == "both"
              else (args.variant,))
  resolved_by_workload = {
      workload: materialize_configs(base_configs, workload)
      for workload in args.workloads
  }
  if args.prepare_only:
    print("[done] configs prepared and strict diff checks passed.")
    return
  for variant in variants:
    for workload in args.workloads:
      for seed in args.seeds:
        run_one(
            args, base_configs[variant],
            resolved_by_workload[workload][variant],
            variant, workload, seed)


if __name__ == "__main__":
  main()
