# coding=utf-8
"""Collect QMAP PC,Address,RW traces through DynamoRIO drmemtrace.

This script uses DynamoRIO's built-in drmemtrace tool, renders its human-readable
view, and converts read/write data references into the QMAP CSV schema. It
requires no custom DynamoRIO client build.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

from convert_drmemtrace_view import convert_stream


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def path_from_root(*parts):
  return os.path.join(PROJECT_ROOT, *parts)


def tool_path(path):
  """Prefer project-relative paths for DynamoRIO tools on Windows.

  Some bundled DynamoRIO tools print/use argv paths through the local code page.
  Keeping project paths relative avoids failures when PROJECT_ROOT contains
  non-ASCII characters.
  """
  absolute_path = os.path.abspath(path)
  try:
    common = os.path.commonpath([PROJECT_ROOT, absolute_path])
  except ValueError:
    return path
  if common == PROJECT_ROOT:
    return os.path.relpath(absolute_path, PROJECT_ROOT)
  return path


def find_drrun(explicit_path):
  if explicit_path:
    return explicit_path

  env_home = os.environ.get("DYNAMORIO_HOME")
  if env_home:
    candidate = os.path.join(env_home, "bin64", "drrun.exe")
    if os.path.exists(candidate):
      return candidate
    candidate = os.path.join(env_home, "bin64", "drrun")
    if os.path.exists(candidate):
      return candidate

  candidate = shutil.which("drrun") or shutil.which("drrun.exe")
  if candidate:
    return candidate

  raise FileNotFoundError(
      "Cannot find drrun. Set --drrun or DYNAMORIO_HOME.")


def find_drraw2trace(drrun):
  dynamorio_home = os.path.dirname(os.path.dirname(os.path.abspath(drrun)))
  executable = "drraw2trace.exe" if os.name == "nt" else "drraw2trace"
  candidate = os.path.join(dynamorio_home, "tools", "bin64", executable)
  if os.path.exists(candidate):
    return candidate

  candidate = shutil.which(executable)
  if candidate:
    return candidate

  raise FileNotFoundError(
      "Cannot find drraw2trace next to drrun or on PATH.")


def split_target_command(target):
  if target and target[0] == "--":
    return target[1:]
  return target


def make_default_work_dir(output_path):
  stem = os.path.splitext(os.path.basename(output_path))[0]
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  return path_from_root("tmp", "drmemtrace", "{}_{}".format(stem, timestamp))


def find_trace_dirs(work_dir):
  trace_dirs = []
  for root, dirs, _ in os.walk(work_dir):
    for dirname in dirs:
      if dirname.endswith(".dir"):
        trace_dirs.append(os.path.join(root, dirname))
  return sorted(trace_dirs)


TRACE_DIR_PID_RE = re.compile(r"\.(?P<pid>\d+)\.\d+\.dir$")


def trace_process_id(trace_dir):
  match = TRACE_DIR_PID_RE.search(os.path.basename(trace_dir))
  if match is None:
    raise ValueError(
        "Cannot parse PID from drmemtrace directory: {}".format(trace_dir))
  return int(match.group("pid"))


def trace_dir_has_trace_files(trace_dir):
  trace_subdir = os.path.join(trace_dir, "trace")
  if not os.path.isdir(trace_subdir):
    return False
  for _, _, files in os.walk(trace_subdir):
    for filename in files:
      if filename.endswith(".trace") or ".trace" in filename:
        return True
  return False


def convert_raw_trace(trace_dir, drrun, dry_run):
  if trace_dir_has_trace_files(trace_dir):
    return

  raw_dir = os.path.join(trace_dir, "raw")
  output_dir = os.path.join(trace_dir, "trace")
  if not os.path.isdir(raw_dir):
    raise FileNotFoundError("Missing drmemtrace raw dir: {}".format(raw_dir))
  os.makedirs(output_dir, exist_ok=True)

  command = [
      find_drraw2trace(drrun),
      "-indir", tool_path(raw_dir),
      "-out", tool_path(output_dir),
  ]
  run_command(command, PROJECT_ROOT, dry_run)


def run_command(command, cwd, dry_run):
  print("[run] {}".format(" ".join(command)), flush=True)
  if dry_run:
    return subprocess.CompletedProcess(command, 0, "", "")
  return subprocess.run(command, cwd=cwd, check=True)


def collect_trace(args, drrun, target_command):
  trace_refs = args.trace_refs
  if trace_refs is None:
    # A data record is only a subset of drmemtrace references because ifetch
    # records are included. This multiplier keeps the default pilot practical.
    trace_refs = max(1, (args.skip_records + args.max_records) *
                     args.trace_ref_multiplier)

  command = [
      drrun,
      "-t", "drmemtrace",
      "-offline",
      "-outdir", tool_path(args.work_dir),
  ]
  if args.trace_after_instrs:
    command.extend(["-trace_after_instrs", str(args.trace_after_instrs)])
  if args.exit_after_tracing:
    command.extend(["-exit_after_tracing", str(trace_refs)])
  else:
    command.extend(["-max_global_trace_refs", str(trace_refs)])
  command.extend(["--"] + target_command)

  os.makedirs(args.work_dir, exist_ok=True)
  run_command(command, PROJECT_ROOT, args.dry_run)


def render_and_convert(args, drrun):
  if args.dry_run:
    return {"seen_data_refs": 0, "written": 0}

  trace_dirs = find_trace_dirs(args.work_dir)
  if not trace_dirs:
    raise FileNotFoundError(
        "No drmemtrace .dir output found under {}.".format(args.work_dir))
  if len(trace_dirs) > 1 and args.include_process_thread:
    raise ValueError(
        "Stage-7 collection observed multiple process trace directories: "
        "{}".format(trace_dirs))
  if len(trace_dirs) > 1:
    print("[info] found multiple trace dirs; using {}".format(trace_dirs[0]))
  process_id = (
      trace_process_id(trace_dirs[0])
      if args.include_process_thread else None)
  convert_raw_trace(trace_dirs[0], drrun, args.dry_run)

  view_command = [
      drrun,
      "-t", "drmemtrace",
      "-indir", tool_path(trace_dirs[0]),
      "-tool", "view",
      "-view_syntax", "intel",
  ]
  print("[run] {}".format(" ".join(view_command)), flush=True)
  if args.dry_run:
    return {"seen_data_refs": 0, "written": 0}

  os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
  view_log_file = None
  if args.view_log:
    os.makedirs(os.path.dirname(os.path.abspath(args.view_log)), exist_ok=True)
    view_log_file = open(args.view_log, "w")

  process = subprocess.Popen(
      view_command,
      cwd=PROJECT_ROOT,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True,
      bufsize=1)
  try:
    with open(args.output, "w", newline="") as output_file:
      if view_log_file is None:
        stats = convert_stream(
            process.stdout, output_file, args.max_records, args.skip_records,
            args.page_shift, args.keep_raw_address,
            args.include_process_thread, process_id)
      else:
        stats = convert_stream(
            TeeStream(process.stdout, view_log_file), output_file,
            args.max_records, args.skip_records, args.page_shift,
            args.keep_raw_address, args.include_process_thread, process_id)
    if stats["written"] >= args.max_records:
      process.terminate()
    return_code = process.wait()
  finally:
    if view_log_file is not None:
      view_log_file.close()

  if return_code != 0 and stats["written"] < args.max_records:
    raise subprocess.CalledProcessError(return_code, view_command)
  return stats


class TeeStream(object):
  """Iterator that mirrors a text stream into a log file."""

  def __init__(self, stream, log_file):
    self._stream = stream
    self._log_file = log_file

  def __iter__(self):
    return self

  def __next__(self):
    line = next(self._stream)
    self._log_file.write(line)
    return line


def build_arg_parser():
  parser = argparse.ArgumentParser(
      description="Collect DynamoRIO drmemtrace output as QMAP CSV.")
  parser.add_argument("--drrun", default=None,
                      help="Path to DynamoRIO bin64/drrun.")
  parser.add_argument("--output", required=True,
                      help="Output PC,Address,RW CSV.")
  parser.add_argument("--work-dir", default=None,
                      help="Directory for drmemtrace intermediate files.")
  parser.add_argument("--max-records", type=int, default=100000,
                      help="Maximum data refs in the output CSV.")
  parser.add_argument("--skip-records", type=int, default=0,
                      help="Data refs skipped by the CSV converter.")
  parser.add_argument("--trace-after-instrs", type=int, default=0,
                      help="Optional drmemtrace instruction warmup.")
  parser.add_argument("--trace-refs", type=int, default=None,
                      help="Override drmemtrace global trace ref window.")
  parser.add_argument("--trace-ref-multiplier", type=int, default=8,
                      help="Default trace ref window = (skip + max) * this.")
  parser.add_argument("--page-shift", type=int, default=12)
  parser.add_argument("--keep-raw-address", action="store_true",
                      help="Do not page-align memory addresses in the CSV.")
  parser.add_argument(
      "--include-process-thread", action="store_true",
      help="Write PID,TID,PC,Address,RW for Stage-7 identity auditing.")
  parser.add_argument("--no-exit-after-tracing",
                      dest="exit_after_tracing",
                      action="store_false",
                      help="Let the target continue after trace window ends.")
  parser.add_argument("--view-log", default=None,
                      help="Optional file to save the drmemtrace view text.")
  parser.add_argument("--allow-short", action="store_true",
                      help="Do not fail if fewer than --max-records are found.")
  parser.add_argument("--dry-run", action="store_true",
                      help="Print commands without running them.")
  parser.add_argument("target", nargs=argparse.REMAINDER,
                      help="Target command after --.")
  parser.set_defaults(exit_after_tracing=True)
  return parser


def main():
  args = build_arg_parser().parse_args()
  if args.max_records <= 0:
    raise ValueError("--max-records must be positive.")
  if args.skip_records < 0:
    raise ValueError("--skip-records must be non-negative.")
  if args.trace_ref_multiplier <= 0:
    raise ValueError("--trace-ref-multiplier must be positive.")

  target_command = split_target_command(args.target)
  if not target_command:
    raise ValueError("Target command is required after --.")

  args.output = os.path.abspath(args.output)
  args.work_dir = os.path.abspath(args.work_dir or make_default_work_dir(
      args.output))
  drrun = find_drrun(args.drrun)

  collect_trace(args, drrun, target_command)
  stats = render_and_convert(args, drrun)

  print("Seen data refs: {}".format(stats["seen_data_refs"]))
  print("Wrote records: {}".format(stats["written"]))
  if args.include_process_thread:
    print("Process IDs: {}".format(stats["process_ids"]))
    print("Thread IDs: {}".format(stats["thread_ids"]))
  print("Output: {}".format(args.output))
  if (not args.dry_run and stats["written"] < args.max_records and
      not args.allow_short):
    raise SystemExit(
        "Only wrote {} records, fewer than requested {}. Increase "
        "--trace-ref-multiplier or --trace-refs.".format(
            stats["written"], args.max_records))


if __name__ == "__main__":
  main()
