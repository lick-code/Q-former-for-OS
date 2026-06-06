# coding=utf-8
"""Tune canneal QMAP replay settings on validation, then evaluate on test.

This script is intentionally narrow.  Canneal is sensitive to candidate rank:
large candidate windows let QMAP evict newer pages and over-migrate.  The
script therefore sweeps epoch, eval-time candidate count, and an optional
LRU-rank score penalty on the validation split, then reports one selected test
result without using test metrics for selection.
"""

import argparse
import csv
import json
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QMAP_ABLATION = "cross_attention"
BASELINE_POLICIES = ("lru", "random", "lfu", "clock")


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def split_csv(value):
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_list(value, flag_name):
  values = []
  for item in split_csv(value):
    number = int(item)
    if number <= 0:
      raise ValueError("{} values must be positive: {}".format(
          flag_name, number))
    values.append(number)
  if not values:
    raise ValueError("{} requires at least one value.".format(flag_name))
  return values


def parse_float_list(value, flag_name):
  values = []
  for item in split_csv(value):
    number = float(item)
    if number < 0.0:
      raise ValueError("{} values must be non-negative: {}".format(
          flag_name, number))
    values.append(number)
  if not values:
    raise ValueError("{} requires at least one value.".format(flag_name))
  return values


def penalty_tag(value):
  return str(value).replace("-", "m").replace(".", "p")


def run_command(command, log_path):
  os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
  print("[run] {}".format(" ".join(command)), flush=True)
  process = subprocess.run(
      command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      universal_newlines=True)
  with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write(process.stdout)
  if process.returncode != 0:
    print(process.stdout)
    raise subprocess.CalledProcessError(process.returncode, command)


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(path, data):
  os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(data, output_file, indent=2, sort_keys=True)
    output_file.write("\n")


def select_best_config(rows):
  """Selects the lowest validation cost with deterministic tie-breaking."""
  if not rows:
    raise ValueError("No validation rows available for selection.")
  return min(
      rows,
      key=lambda row: (
          float(row["weighted_access_cost"]),
          -int(row["candidate_count"]),
          float(row.get("rank_score_penalty", 0.0)),
          int(row["epoch"])))


def best_baseline(rows):
  if not rows:
    return None
  return min(
      rows,
      key=lambda row: (float(row["weighted_access_cost"]),
                       int(row["nvm_writes"]),
                       -float(row["hit_rate_percent"])))


def delta_percent(cost, baseline_cost):
  if baseline_cost is None or baseline_cost == 0.0:
    return ""
  return (float(cost) - baseline_cost) * 100.0 / baseline_cost


def maybe_extend_device(command, device):
  if device and device != "auto":
    command.extend(["--device", device])


def checkpoint_path(args, epoch):
  return os.path.join(args.checkpoint_dir, "qmap_epoch_{}.pth".format(epoch))


def eval_policy(args, split_name, trace_path, policy, output_path, log_path,
                checkpoint=None, epoch="", candidate_count=None,
                rank_score_penalty=0.0):
  candidate_count = candidate_count or args.candidate_count
  command = [
      args.python, "qmap/qmap_eval.py",
      "--trace_path", trace_path,
      "--policy", policy,
      "--dram_capacity", str(args.dram_capacity),
      "--page_shift", str(args.page_shift),
      "--history_length", str(args.history_length),
      "--candidate_count", str(candidate_count),
      "--lookahead", str(args.lookahead),
      "--random_seed", str(args.random_seed),
      "--dram_read_cost", str(args.dram_read_cost),
      "--dram_write_cost", str(args.dram_write_cost),
      "--nvm_read_cost", str(args.nvm_read_cost),
      "--nvm_write_cost", str(args.nvm_write_cost),
      "--migration_cost", str(args.migration_cost),
      "--json_output", output_path,
  ]
  if policy == "qmap":
    if not checkpoint:
      raise ValueError("checkpoint is required for qmap evaluation.")
    command.extend([
        "--checkpoint", checkpoint,
        "--ablation", QMAP_ABLATION,
    ])
    if rank_score_penalty:
      command.extend([
          "--rank_score_penalty", str(rank_score_penalty)])
    maybe_extend_device(command, args.device)

  run_command(command, log_path)
  row = load_json(output_path)
  row["split"] = split_name
  row["epoch"] = epoch
  row["candidate_count"] = candidate_count if policy == "qmap" else ""
  row["rank_score_penalty"] = (
      rank_score_penalty if policy == "qmap" else "")
  row["checkpoint"] = checkpoint if policy == "qmap" else ""
  row["ablation"] = QMAP_ABLATION if policy == "qmap" else ""
  return row


def eval_baselines(args, split_name, trace_path, json_dir, log_dir):
  rows = []
  for policy in BASELINE_POLICIES:
    row = eval_policy(
        args,
        split_name,
        trace_path,
        policy,
        os.path.join(json_dir, "{}.json".format(policy)),
        os.path.join(log_dir, "{}.log".format(policy)))
    rows.append(row)
  return rows


def eval_validation_sweep(args, epochs, candidate_counts,
                          rank_score_penalties):
  rows = []
  json_dir = os.path.join(args.output_dir, "json", "valid")
  log_dir = os.path.join(args.output_dir, "logs", "valid")
  for epoch in epochs:
    checkpoint = checkpoint_path(args, epoch)
    if not os.path.exists(checkpoint):
      raise FileNotFoundError(checkpoint)
    for candidate_count in candidate_counts:
      for penalty in rank_score_penalties:
        name = "qmap_epoch_{}_c{}_p{}.json".format(
            epoch, candidate_count, penalty_tag(penalty))
        row = eval_policy(
            args,
            "valid",
            args.valid_trace,
            "qmap",
            os.path.join(json_dir, name),
            os.path.join(log_dir, name.replace(".json", ".log")),
            checkpoint=checkpoint,
            epoch=epoch,
            candidate_count=candidate_count,
            rank_score_penalty=penalty)
        rows.append(row)
  return rows


def eval_selected_test(args, selected):
  epoch = int(selected["epoch"])
  candidate_count = int(selected["candidate_count"])
  penalty = float(selected["rank_score_penalty"])
  checkpoint = checkpoint_path(args, epoch)
  return eval_policy(
      args,
      "test",
      args.test_trace,
      "qmap",
      os.path.join(args.output_dir, "json", "test",
                   "qmap_selected.json"),
      os.path.join(args.output_dir, "logs", "test",
                   "qmap_selected.log"),
      checkpoint=checkpoint,
      epoch=epoch,
      candidate_count=candidate_count,
      rank_score_penalty=penalty)


def write_summary_csv(rows, output_path):
  fields = [
      "split",
      "policy",
      "epoch",
      "candidate_count",
      "rank_score_penalty",
      "weighted_access_cost",
      "delta_vs_best_baseline_percent",
      "hit_rate_percent",
      "nvm_writes",
      "migrations",
      "decision_count",
      "avg_decision_time_ms",
      "total_accesses",
      "misses",
      "nvm_reads",
      "checkpoint",
      "ablation",
      "trace_path",
  ]
  with open(output_path, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      writer.writerow({field: row.get(field, "") for field in fields})


def markdown_policy_name(row):
  return "QMAP-CrossAttn" if row["policy"] == "qmap" else row["policy"].upper()


def write_summary_markdown(selected_valid, test_rows, output_path, args):
  best = best_baseline([row for row in test_rows if row["policy"] != "qmap"])
  baseline_cost = float(best["weighted_access_cost"]) if best else None
  qmap_row = next((row for row in test_rows if row["policy"] == "qmap"), None)
  qmap_delta = (
      delta_percent(qmap_row["weighted_access_cost"], baseline_cost)
      if qmap_row else "")

  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write("# Canneal Tuned Evaluation\n\n")
    output_file.write("## Selection Rule\n\n")
    output_file.write(
        "The script selects the QMAP configuration with the lowest validation "
        "weighted access cost, then evaluates that one configuration on the "
        "test split.\n\n")
    output_file.write("## Selected Validation Config\n\n")
    output_file.write(
        "| Epoch | Candidate count | Rank score penalty | Valid cost | "
        "Hit rate (%) | NVM writes | Migrations |\n")
    output_file.write("|---:|---:|---:|---:|---:|---:|---:|\n")
    output_file.write(
        "| {epoch} | {candidate_count} | {rank_score_penalty} | "
        "{weighted_access_cost:.2f} | {hit_rate_percent:.2f} | "
        "{nvm_writes} | {migrations} |\n\n".format(**selected_valid))

    output_file.write("## Test Result\n\n")
    output_file.write(
        "| Policy | Cost | Delta vs best baseline | Hit rate (%) | "
        "NVM writes | Migrations | Decision ms |\n")
    output_file.write("|---|---:|---:|---:|---:|---:|---:|\n")
    for row in test_rows:
      delta = row.get("delta_vs_best_baseline_percent", "")
      delta_text = "" if delta == "" else "{:+.2f}%".format(delta)
      output_file.write(
          "| {policy} | {cost:.2f} | {delta} | {hit_rate:.2f} | "
          "{writes} | {migrations} | {decision_ms:.6f} |\n".format(
              policy=markdown_policy_name(row),
              cost=row["weighted_access_cost"],
              delta=delta_text,
              hit_rate=row["hit_rate_percent"],
              writes=row["nvm_writes"],
              migrations=row["migrations"],
              decision_ms=row["avg_decision_time_ms"]))

    output_file.write("\n## Reproduction\n\n")
    output_file.write("```bash\n")
    output_file.write(
        "python scripts/run_canneal_tuned_eval.py --device {}\n".format(
            args.device))
    output_file.write("```\n\n")
    if best and qmap_row:
      output_file.write(
          "Selected QMAP-CrossAttn test delta vs best baseline (`{}`) is "
          "{:+.2f}%.\n".format(markdown_policy_name(best), qmap_delta))


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description=("Tune canneal QMAP eval parameters on validation and "
                   "evaluate the selected config on test."))
  parser.add_argument("--valid_trace", default=path_from_root(
      "dataset", "processed", "real_workload_suite", "1m",
      "parsec_canneal_valid.csv"))
  parser.add_argument("--test_trace", default=path_from_root(
      "dataset", "processed", "real_workload_suite", "1m",
      "parsec_canneal_test.csv"))
  parser.add_argument("--checkpoint_dir", default=path_from_root(
      "outputs", "checkpoints", "real_workload_suite", "1m",
      "parsec_canneal"))
  parser.add_argument("--output_dir", default=path_from_root(
      "outputs", "results", "canneal_tuned_eval"))
  parser.add_argument("--epochs", default="1,2,3,4,5,6,7,8,9,10")
  parser.add_argument("--candidate_counts", default="1,2,4,8")
  parser.add_argument("--rank_score_penalties",
                      default="0,0.25,0.5,1.0,2.0")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument("--device", default="cuda")
  parser.add_argument("--dram_capacity", type=int, default=16)
  parser.add_argument("--page_shift", type=int, default=12)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=8,
                      help="Candidate count used for baseline replay flags.")
  parser.add_argument("--lookahead", type=int, default=256)
  parser.add_argument("--random_seed", type=int, default=0)
  parser.add_argument("--dram_read_cost", type=float, default=1.0)
  parser.add_argument("--dram_write_cost", type=float, default=1.0)
  parser.add_argument("--nvm_read_cost", type=float, default=2.0)
  parser.add_argument("--nvm_write_cost", type=float, default=8.0)
  parser.add_argument("--migration_cost", type=float, default=10.0)
  parser.add_argument("--skip_baselines", action="store_true")
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.dram_capacity <= 0:
    raise ValueError("--dram_capacity must be positive.")
  if args.candidate_count <= 0:
    raise ValueError("--candidate_count must be positive.")

  epochs = parse_int_list(args.epochs, "--epochs")
  candidate_counts = parse_int_list(
      args.candidate_counts, "--candidate_counts")
  rank_score_penalties = parse_float_list(
      args.rank_score_penalties, "--rank_score_penalties")

  os.makedirs(args.output_dir, exist_ok=True)
  valid_rows = eval_validation_sweep(
      args, epochs, candidate_counts, rank_score_penalties)
  selected_valid = select_best_config(valid_rows)

  test_rows = []
  if not args.skip_baselines:
    test_rows.extend(eval_baselines(
        args,
        "test",
        args.test_trace,
        os.path.join(args.output_dir, "json", "test"),
        os.path.join(args.output_dir, "logs", "test")))
  selected_test = eval_selected_test(args, selected_valid)
  test_rows.append(selected_test)

  best = best_baseline([row for row in test_rows if row["policy"] != "qmap"])
  baseline_cost = float(best["weighted_access_cost"]) if best else None
  for row in test_rows:
    if row["policy"] == "qmap":
      row["delta_vs_best_baseline_percent"] = delta_percent(
          row["weighted_access_cost"], baseline_cost)
    elif best and row["policy"] == best["policy"]:
      row["delta_vs_best_baseline_percent"] = 0.0
    else:
      row["delta_vs_best_baseline_percent"] = ""
  for row in valid_rows:
    row["delta_vs_best_baseline_percent"] = ""

  selected_config = {
      "selection_rule": "lowest validation weighted_access_cost",
      "selected_validation": selected_valid,
      "selected_test": selected_test,
      "best_test_baseline": best,
  }
  write_json(os.path.join(args.output_dir, "selected_config.json"),
             selected_config)

  all_rows = valid_rows + test_rows
  summary_csv = os.path.join(args.output_dir, "summary.csv")
  summary_md = os.path.join(args.output_dir, "summary.md")
  write_summary_csv(all_rows, summary_csv)
  write_summary_markdown(selected_valid, test_rows, summary_md, args)
  print("[done] selected_config={}".format(
      os.path.join(args.output_dir, "selected_config.json")))
  print("[done] summary_csv={}".format(summary_csv))
  print("[done] summary_md={}".format(summary_md))


if __name__ == "__main__":
  main()
