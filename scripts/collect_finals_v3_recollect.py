# coding=utf-8
"""Collect isolated, provenance-rich CAPD finals-v3 PARSEC traces.

Run this script inside the QMAP WSL environment.  It intentionally refuses to
overwrite an existing trace or drmemtrace directory.  Pilot and official runs
therefore remain separate from the historical PARSEC 1M traces.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QMAP_ROOT = "/root/qmap-work"
PARSEC_ROOT = os.path.join(QMAP_ROOT, "parsec-3.0")
DYNAMORIO = os.path.join(
    QMAP_ROOT,
    "tools/extern/DynamoRIO-Linux-11.91.20581/bin64/drrun")
INPUT_ROOT = os.path.join(
    QMAP_ROOT, "parsec-inputs/finals_v3_recollect")

SOURCE_IMAGE = "spirals/parsec-3.0:source"
SOURCE_LAYER_SHA256 = (
    "97c8f691638a5154690d307e18fcd33b557b47204ae4cf5641b6103a770a26d5")


WORKLOADS = {
    "canneal": {
        "canonical_workload": "canneal",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"),
        "input": os.path.join(INPUT_ROOT, "canneal_simlarge/400000.nets"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/canneal_input_simlarge.tar.xz"),
        "archive_sha256": (
            "3e4889c8a01bfc24d54161804dd239a9d5924e0eb1cb9ddb76daa4a75985d837"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/canneal/parsec/simlarge.runconf"),
        "args": lambda run_dir: [
            "1", "15000", "2000",
            os.path.join(INPUT_ROOT, "canneal_simlarge/400000.nets"), "128"],
        "input_class": "PARSEC 3.0 simlarge",
    },
    "streamcluster_pressure": {
        "canonical_workload": "streamcluster_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"),
        "input": None,
        "archive": None,
        "archive_sha256": None,
        "runconf": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/streamcluster/parsec/simlarge.runconf"),
        "args": lambda run_dir: [
            "10", "20", "128", "16384", "16384", "1000", "none",
            os.path.join(run_dir, "streamcluster_output.txt"), "1"],
        "input_class": "PARSEC 3.0 simlarge synthetic generator",
    },
    "dedup_pressure": {
        "canonical_workload": "dedup_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"),
        "input": os.path.join(INPUT_ROOT, "dedup_simlarge/media.dat"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/dedup_input_simlarge.tar.xz"),
        "archive_sha256": (
            "03cf16da377570a26136ced812405d306b48f37d9c7e9c58dd29d5bdc82e8e4c"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/dedup/parsec/simlarge.runconf"),
        "args": lambda run_dir: [
            "-c", "-p", "-v", "-t", "1", "-i",
            os.path.join(INPUT_ROOT, "dedup_simlarge/media.dat"), "-o",
            os.path.join(run_dir, "dedup_output.dat.ddp")],
        "input_class": "PARSEC 3.0 simlarge",
    },
    "dedup_pressure_4t_pilot": {
        "canonical_workload": "dedup_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"),
        "input": os.path.join(INPUT_ROOT, "dedup_simlarge/media.dat"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/dedup_input_simlarge.tar.xz"),
        "archive_sha256": (
            "03cf16da377570a26136ced812405d306b48f37d9c7e9c58dd29d5bdc82e8e4c"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/dedup/parsec/simlarge.runconf"),
        "args": lambda run_dir: [
            "-c", "-p", "-v", "-t", "4", "-i",
            os.path.join(INPUT_ROOT, "dedup_simlarge/media.dat"), "-o",
            os.path.join(run_dir, "dedup_output.dat.ddp")],
        "input_class": "PARSEC 3.0 simlarge, four pthread workers",
    },
    "dedup_native_pilot": {
        "canonical_workload": "dedup_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"),
        "input": os.path.join(
            INPUT_ROOT, "dedup_native/FC-6-x86_64-disc1.iso"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/dedup_input_native.tar.xz"),
        "archive_sha256": (
            "b99eabba399e8e425b73dc5d6d5217958d48d202b6b826fd1a8110b45d90ff8a"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/dedup/parsec/native.runconf"),
        "args": lambda run_dir: [
            "-c", "-p", "-v", "-t", "1", "-i",
            os.path.join(INPUT_ROOT, "dedup_native/FC-6-x86_64-disc1.iso"),
            "-o", os.path.join(run_dir, "dedup_output.dat.ddp")],
        "input_class": "PARSEC 3.0 native",
    },
    "dedup_native_8t_pilot": {
        "canonical_workload": "dedup_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"),
        "input": os.path.join(
            INPUT_ROOT, "dedup_native/FC-6-x86_64-disc1.iso"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/dedup_input_native.tar.xz"),
        "archive_sha256": (
            "b99eabba399e8e425b73dc5d6d5217958d48d202b6b826fd1a8110b45d90ff8a"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/dedup/parsec/native.runconf"),
        "args": lambda run_dir: [
            "-c", "-p", "-v", "-t", "8", "-i",
            os.path.join(INPUT_ROOT, "dedup_native/FC-6-x86_64-disc1.iso"),
            "-o", os.path.join(run_dir, "dedup_output.dat.ddp")],
        "input_class": "PARSEC 3.0 native, eight pthread workers",
    },
    "canneal_native_pilot": {
        "canonical_workload": "canneal",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"),
        "input": os.path.join(INPUT_ROOT, "canneal_native/2500000.nets"),
        "archive": os.path.join(
            INPUT_ROOT, "archives/canneal_input_native.tar.xz"),
        "archive_sha256": (
            "1aa6b1797c3c12efbd8591d26af752557fc5b44b75e89787401a1840db78e418"),
        "runconf": os.path.join(
            PARSEC_ROOT, "pkgs/kernels/canneal/parsec/native.runconf"),
        "args": lambda run_dir: [
            "1", "15000", "2000",
            os.path.join(INPUT_ROOT, "canneal_native/2500000.nets"), "6000"],
        "input_class": "PARSEC 3.0 native",
    },
    "streamcluster_native_pilot": {
        "canonical_workload": "streamcluster_pressure",
        "binary": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"),
        "input": None,
        "archive": None,
        "archive_sha256": None,
        "runconf": os.path.join(
            PARSEC_ROOT,
            "pkgs/kernels/streamcluster/parsec/native.runconf"),
        "args": lambda run_dir: [
            "10", "20", "128", "1000000", "200000", "5000", "none",
            os.path.join(run_dir, "streamcluster_output.txt"), "1"],
        "input_class": "PARSEC 3.0 native synthetic generator",
    },
}
DEFAULT_WORKLOADS = ("canneal", "streamcluster_pressure", "dedup_pressure")


def sha256_file(path):
  digest = hashlib.sha256()
  with open(path, "rb") as input_file:
    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def command_output(command, cwd=None):
  return subprocess.check_output(
      command, cwd=cwd, stderr=subprocess.STDOUT, text=True).strip()


def git_snapshot(root):
  commit = subprocess.run(
      ["git", "-C", root, "rev-parse", "HEAD"],
      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  if commit.returncode != 0:
    return {
        "root": root,
        "git_available": False,
        "error": commit.stdout.strip(),
    }
  return {
      "root": root,
      "git_available": True,
      "commit": commit.stdout.strip(),
      "status_short": command_output(
          ["git", "-C", root, "status", "--short"]),
  }


def write_json(path, payload):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  temporary = path + ".tmp"
  with open(temporary, "w", encoding="utf-8") as output_file:
    json.dump(payload, output_file, indent=2, sort_keys=True)
    output_file.write("\n")
  os.replace(temporary, path)


def run_logged(command, cwd, log_path):
  os.makedirs(os.path.dirname(log_path), exist_ok=True)
  print("[run] {}".format(shlex.join(command)), flush=True)
  with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write("[run] {}\n".format(shlex.join(command)))
    log_file.flush()
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    for line in process.stdout:
      sys.stdout.write(line)
      sys.stdout.flush()
      log_file.write(line)
      log_file.flush()
    return process.wait()


def validate_source(workload):
  spec = WORKLOADS[workload]
  required = [DYNAMORIO, spec["binary"], spec["runconf"]]
  if spec["input"]:
    required.append(spec["input"])
  if spec["archive"]:
    required.append(spec["archive"])
  missing = [path for path in required if not os.path.exists(path)]
  if missing:
    raise FileNotFoundError("Missing required files: {}".format(missing))
  if spec["archive"]:
    observed = sha256_file(spec["archive"])
    if observed != spec["archive_sha256"]:
      raise ValueError(
          "Archive SHA-256 mismatch for {}: {}".format(workload, observed))


def collect_one(args, workload, common):
  spec = WORKLOADS[workload]
  validate_source(workload)

  raw_dir = os.path.join(
      PROJECT_ROOT, "dataset/raw_traces/finals_v3_recollect", args.phase)
  result_dir = os.path.join(
      PROJECT_ROOT, "outputs/results/finals_v3_recollect", args.phase,
      workload)
  metadata_dir = os.path.join(
      PROJECT_ROOT, "dataset/metadata/finals_v3_recollect", args.phase)
  run_dir = os.path.join(
      QMAP_ROOT, "parsec-runs/finals_v3_recollect", args.phase, workload)
  work_dir = os.path.join(
      QMAP_ROOT, "drmemtrace/finals_v3_recollect", args.phase,
      "{}_{}".format(workload, args.run_id))
  output_path = os.path.join(raw_dir, "{}.csv".format(workload))
  source_spec_path = os.path.join(
      metadata_dir, "{}.json".format(workload))
  collector_log = os.path.join(result_dir, "collector.log")
  view_log = os.path.join(result_dir, "drmemtrace.view.log")

  existing = [path for path in (output_path, work_dir, source_spec_path)
              if os.path.exists(path)]
  if existing:
    if args.resume and os.path.exists(source_spec_path):
      with open(source_spec_path, encoding="utf-8") as input_file:
        previous = json.load(input_file)
      if previous.get("status") == "complete":
        print("[skip] {} already complete".format(workload), flush=True)
        return
    raise FileExistsError(
        "Refusing to overwrite existing artifacts: {}".format(existing))

  os.makedirs(raw_dir, exist_ok=True)
  os.makedirs(result_dir, exist_ok=True)
  os.makedirs(run_dir, exist_ok=True)
  target = [spec["binary"]] + spec["args"](run_dir)
  collector = [
      sys.executable,
      os.path.join(PROJECT_ROOT, "scripts/collect_trace_drmemtrace.py"),
      "--drrun", DYNAMORIO,
      "--output", output_path,
      "--work-dir", work_dir,
      "--max-records", str(args.max_records),
      "--skip-records", str(args.skip_records),
      "--trace-ref-multiplier", str(args.trace_ref_multiplier),
      "--view-log", view_log,
  ]
  if args.trace_after_instrs:
    collector.extend(["--trace-after-instrs", str(args.trace_after_instrs)])
  collector.extend(["--"] + target)

  started = datetime.datetime.now(datetime.timezone.utc)
  payload = {
      "schema_version": "capd_finals_v3_recollect_source_spec_v1",
      "status": "collecting",
      "phase": args.phase,
      "run_id": args.run_id,
      "workload": workload,
      "canonical_workload": spec["canonical_workload"],
      "input_class": spec["input_class"],
      "source_image": SOURCE_IMAGE,
      "source_layer_sha256": SOURCE_LAYER_SHA256,
      "source_archive": spec["archive"],
      "source_archive_sha256": spec["archive_sha256"],
      "input_path": spec["input"],
      "input_sha256": sha256_file(spec["input"]) if spec["input"] else None,
      "runconf_path": spec["runconf"],
      "runconf_sha256": sha256_file(spec["runconf"]),
      "binary_path": spec["binary"],
      "binary_sha256": sha256_file(spec["binary"]),
      "collector_path": os.path.join(
          PROJECT_ROOT, "scripts/collect_trace_drmemtrace.py"),
      "collector_sha256": sha256_file(os.path.join(
          PROJECT_ROOT, "scripts/collect_trace_drmemtrace.py")),
      "target_argv": target,
      "collector_argv": collector,
      "max_records": args.max_records,
      "skip_records": args.skip_records,
      "trace_ref_multiplier": args.trace_ref_multiplier,
      "trace_after_instrs": args.trace_after_instrs,
      "page_shift": 12,
      "raw_trace": output_path,
      "drmemtrace_work_dir": work_dir,
      "collector_log": collector_log,
      "view_log": view_log,
      "started_at_utc": started.isoformat(),
      "host": {
          "platform": platform.platform(),
          "uname": command_output(["uname", "-a"]),
          "processors": os.cpu_count(),
          "python": sys.version,
      },
      "dynamorio_version": command_output([DYNAMORIO, "-version"]),
      "project_git": common["project_git"],
      "parsec_git": common["parsec_git"],
  }
  write_json(source_spec_path, payload)

  start_seconds = time.time()
  return_code = run_logged(collector, PROJECT_ROOT, collector_log)
  payload["return_code"] = return_code
  payload["elapsed_seconds"] = round(time.time() - start_seconds, 3)
  payload["finished_at_utc"] = datetime.datetime.now(
      datetime.timezone.utc).isoformat()
  if return_code != 0:
    payload["status"] = "failed"
    write_json(source_spec_path, payload)
    raise subprocess.CalledProcessError(return_code, collector)

  with open(output_path, "rb") as trace_file:
    record_count = max(0, sum(1 for _ in trace_file) - 1)
  payload.update({
      "status": "complete",
      "raw_trace_bytes": os.path.getsize(output_path),
      "raw_trace_records": record_count,
      "raw_trace_sha256": sha256_file(output_path),
  })
  write_json(source_spec_path, payload)
  print("[done] {} records={} sha256={}".format(
      workload, record_count, payload["raw_trace_sha256"]), flush=True)


def build_arg_parser():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--phase", default="pilot_1m")
  parser.add_argument("--run-id", default=None)
  parser.add_argument(
      "--workloads", default=",".join(DEFAULT_WORKLOADS),
      help="Comma-separated workload keys.")
  parser.add_argument("--max-records", type=int, default=1000000)
  parser.add_argument("--skip-records", type=int, default=100000)
  parser.add_argument("--trace-ref-multiplier", type=int, default=100)
  parser.add_argument("--trace-after-instrs", type=int, default=0)
  parser.add_argument(
      "--project-commit", default=None,
      help="Git commit of the source workspace when the WSL mirror has no .git.")
  parser.add_argument("--resume", action="store_true")
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.max_records <= 0 or args.skip_records < 0:
    raise ValueError("Invalid record counts.")
  if args.trace_ref_multiplier <= 0:
    raise ValueError("--trace-ref-multiplier must be positive.")
  if args.trace_after_instrs < 0:
    raise ValueError("--trace-after-instrs must be non-negative.")
  args.run_id = args.run_id or datetime.datetime.now().strftime(
      "%Y%m%dT%H%M%S")
  workloads = [item.strip() for item in args.workloads.split(",")
               if item.strip()]
  unknown = sorted(set(workloads) - set(WORKLOADS))
  if unknown:
    raise ValueError("Unknown workloads: {}".format(unknown))

  project_git = git_snapshot(PROJECT_ROOT)
  if args.project_commit:
    project_git["source_workspace_commit"] = args.project_commit
  common = {
      "project_git": project_git,
      "parsec_git": git_snapshot(PARSEC_ROOT),
  }
  for workload in workloads:
    collect_one(args, workload, common)


if __name__ == "__main__":
  main()
