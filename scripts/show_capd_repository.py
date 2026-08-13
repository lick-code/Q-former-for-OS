# coding=utf-8
"""Print a concise, read-only CAPD repository tour for screen recording."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]

SECTIONS: Sequence[Tuple[str, str, Sequence[Tuple[str, str]]]] = (
    (
        "1. Experiment contracts and configuration",
        "Defines data roles, policy controls, cost models, and result schemas.",
        (
            ("configs/finals/capd_proactive_stage0.json",
             "base experiment contract"),
            ("configs/finals/capd_proactive_stage2_cost_profiles.json",
             "independent event-cost profiles"),
            ("configs/finals/capd_proactive_stage8.json",
             "unified replay configuration"),
            ("configs/finals/capd_proactive_stage8_result_schema.json",
             "machine-checkable result schema"),
        ),
    ),
    (
        "2. Trace and workload pipeline",
        "Collects, checks, splits, and binds memory-access workloads.",
        (
            ("dataset/raw_traces", "raw trace storage"),
            ("dataset/processed", "processed train/validation/test data"),
            ("qmap/proactive_stage7_workloads.py",
             "workload identity and split checks"),
            ("scripts/run_capd_proactive_stage7_local_collection.sh",
             "server-side collection workflow"),
        ),
    ),
    (
        "3. Model training, freeze, and inference",
        "Implements QMAP/CAPD training, frozen model loading, and ranking.",
        (
            ("qmap/qmap_train.py", "model training entry"),
            ("qmap/qmap_eval.py", "frozen checkpoint inference"),
            ("qmap/proactive_stage4_stage7.py",
             "training and validation pipeline"),
            ("outputs/capd_proactive_stage4_stage7/"
             "stage4-stage7-unified-r2/formal_checkpoint_manifest.json",
             "checkpoint identity manifest"),
        ),
    ),
    (
        "4. Unified replay and metric computation",
        "Runs multiple policies through one state machine and recomputes cost.",
        (
            ("qmap/proactive_replay.py", "shared memory-tier state machine"),
            ("qmap/proactive_stage5_policies.py",
             "baseline and CAPD ranking adapters"),
            ("qmap/proactive_stage8_replay.py",
             "evaluation replay adapter"),
            ("qmap/proactive_cost.py", "replay-independent cost computation"),
        ),
    ),
    (
        "5. Tests, verification, and evidence",
        "Keeps implementation tests, run receipts, and evidence boundaries.",
        (
            ("tests/test_capd_proactive_replay.py",
             "state and accounting invariants"),
            ("tests/test_capd_proactive_stage8.py",
             "evaluation contract and aggregation tests"),
            ("outputs/capd_proactive_stage8/"
             "stage8-dual-track-20260804-r5-post-evidence-commit/"
             "verification.json", "replay verification receipt"),
            ("docs/CAPD_PROACTIVE_STAGE8_RESULTS_CN.md",
             "evidence-bounded experiment documentation"),
        ),
    ),
)

COUNT_ROOTS: Sequence[Tuple[str, Sequence[str], Callable[[Path], bool]]] = (
    ("configs/finals", (".json",),
     lambda path: path.name.startswith("capd_")),
    ("qmap", (".py",),
     lambda path: "proactive" in path.name or path.name.startswith("qmap_")),
    ("scripts", (".py", ".sh"),
     lambda path: "capd_" in path.name),
    ("tests", (".py",),
     lambda path: path.name.startswith("test_capd")),
    ("docs", (".md", ".tex", ".csv"),
     lambda path: path.name.lower().startswith("capd")),
)

ASSET_ROOTS = (
    "dataset",
    "outputs/capd_proactive_stage4_stage7",
    "outputs/capd_proactive_stage7",
    "outputs/capd_proactive_stage8",
    "outputs/capd_proactive_stage9",
    "outputs/capd_proactive_stage11_v2",
)


def _matching_files(root: Path, suffixes: Iterable[str]) -> List[Path]:
  suffix_set = {suffix.lower() for suffix in suffixes}
  if not root.exists():
    return []
  return [
      path for path in root.rglob("*")
      if path.is_file() and path.suffix.lower() in suffix_set]


def _directory_size(root: Path) -> Tuple[int, int]:
  files = 0
  total = 0
  if not root.exists():
    return files, total
  for directory, _, names in os.walk(root):
    for name in names:
      path = Path(directory) / name
      try:
        total += path.stat().st_size
        files += 1
      except OSError:
        continue
  return files, total


def _format_size(value: int) -> str:
  size = float(value)
  for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
    if size < 1024.0 or unit == "TiB":
      return "{:.1f} {}".format(size, unit)
    size /= 1024.0
  raise AssertionError("unreachable")


def _print_header(title: str) -> None:
  print("\n" + "=" * 76)
  print(" " + title)
  print("=" * 76)


def _pause(seconds: float) -> None:
  if seconds > 0:
    time.sleep(seconds)


def show_tour(
    root: Path, include_assets: bool = True, pause: float = 0.0) -> int:
  _print_header("CAPD EXPERIMENT REPOSITORY TOUR")
  print("Purpose: show the experiment workflow and engineering artifacts.")
  print("Scope: repository structure and evidence organization, not result claims.")

  print("\n[Repository overview]")
  for relative, suffixes, predicate in COUNT_ROOTS:
    count = len([
        path for path in _matching_files(root / relative, suffixes)
        if predicate(path)])
    labels = "/".join(suffix.lstrip(".") for suffix in suffixes)
    print("  {:<18} {:>4} {:<10} files".format(relative + "/", count, labels))
  _pause(pause)

  missing = []
  for title, purpose, entries in SECTIONS:
    print("\n[{}]".format(title))
    print("  " + purpose)
    for relative, role in entries:
      path = root / relative
      status = "OK" if path.exists() else "MISSING"
      print("  [{:<7}] {}".format(status, role))
      print("            " + relative)
      if status == "MISSING":
        missing.append(relative)
    _pause(pause)

  if include_assets:
    print("\n[Current experiment assets]")
    for relative in ASSET_ROOTS:
      files, size = _directory_size(root / relative)
      status = "OK" if (root / relative).exists() else "MISSING"
      print("  [{:<7}] {:<47} {:>5} files  {:>10}".format(
          status, relative + "/", files, _format_size(size)))
    _pause(pause)

  print("\n[Tour check]")
  if missing:
    print("  REPOSITORY_TOUR_INCOMPLETE: {} representative paths missing".format(
        len(missing)))
    return 1
  print("  REPOSITORY_TOUR_READY: all representative paths are present")
  print("  Next: python -u scripts/run_capd_demo.py --device cpu --pause 0.5")
  return 0


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      description="Print a concise, read-only CAPD repository tour.")
  parser.add_argument(
      "--skip-assets", action="store_true",
      help="Skip recursive size calculation for large experiment assets.")
  parser.add_argument(
      "--pause", type=float, default=0.0,
      help="Seconds to pause after each tour section for narration.")
  return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
  args = build_parser().parse_args(argv)
  return show_tour(
      ROOT, include_assets=not args.skip_assets, pause=max(0.0, args.pause))


if __name__ == "__main__":
  raise SystemExit(main())
