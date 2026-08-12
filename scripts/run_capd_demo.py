# coding=utf-8
"""Run an isolated, non-formal CAPD closed-loop demonstration.

This runner exercises the repository's real replay, ranking, checkpoint, and
cost implementations on a deterministic synthetic trace.  Its artifacts are
for a screen-recorded demonstration only and must not be cited as formal
experimental evidence.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from qmap import finals_config  # noqa: E402
from qmap import proactive_cost  # noqa: E402
from qmap import proactive_replay  # noqa: E402
from qmap import proactive_stage4  # noqa: E402
from qmap import proactive_stage5_policies as policies  # noqa: E402
from qmap import proactive_stage5_replay  # noqa: E402
from qmap import proactive_stage8_replay  # noqa: E402


DEMO_SCHEMA = "capd_closed_loop_demo_v1_0"
DEMO_STATUS = "non_formal_demo_only"
DEFAULT_POLICIES = (
    "reactive_lru", "proactive_lru", "proactive_clock", "capd")
DISPLAY_NAMES = {
    "reactive_lru": "Reactive-LRU",
    "proactive_lru": "Proactive-LRU",
    "proactive_clock": "Proactive-CLOCK",
    "capd": "CAPD",
}
CHECKPOINT_MANIFEST = Path(
    "outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/"
    "formal_checkpoint_manifest.json")
CHECKPOINT_ROOT = Path(
    "outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/"
    "checkpoints/opt-balanced")
STAGE0_CONFIG = Path("configs/finals/capd_proactive_stage0.json")
COST_CONFIG = Path("configs/finals/capd_proactive_stage2_cost_profiles.json")


class DemoError(RuntimeError):
  """Raised when the demonstration cannot establish its closed-loop checks."""


def _canonical_bytes(value: Any) -> bytes:
  return json.dumps(
      value, ensure_ascii=True, sort_keys=True,
      separators=(",", ":"), allow_nan=False).encode("utf-8")


def fingerprint_value(value: Any) -> str:
  return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(path.suffix + ".tmp")
  with temporary.open("w", encoding="utf-8", newline="\n") as output:
    json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2,
              allow_nan=False)
    output.write("\n")
  os.replace(str(temporary), str(path))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(path.suffix + ".tmp")
  with temporary.open("w", encoding="utf-8", newline="\n") as output:
    for row in rows:
      output.write(json.dumps(
          row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
  os.replace(str(temporary), str(path))


def build_demo_trace() -> List[Dict[str, int]]:
  """Build a deterministic locality/scan/write trace without formal data."""
  trace: List[Dict[str, int]] = []

  def emit(page: int, rw: int, pc_group: int) -> None:
    trace.append({
        "page": int(page), "rw": int(rw),
        "pc": int(0x400000 + pc_group * 0x40 + (page % 7) * 4)})

  # Stable hot working set, followed by scan pressure and recurring reuse.
  for epoch in range(8):
    for page in (0, 1, 2, 3, 4, 5, 2, 1, 6, 3, 0, 7):
      emit(page, int((page + epoch) % 11 == 0), 1)
  for epoch in range(6):
    for page in range(8, 40):
      emit(page, int((page + epoch) % 9 == 0), 2)
    for page in (0, 1, 2, 3, 4, 0, 2, 1, 5, 6, 3, 7):
      emit(page, int((page + 2 * epoch) % 13 == 0), 3)
  for epoch in range(5):
    for page in (40, 41, 42, 43, 44, 45, 46, 47):
      emit(page, int((page + epoch) % 5 == 0), 4)
    for page in (2, 3, 2, 1, 0, 4, 2, 5, 3, 1, 6, 0):
      emit(page, int((page + epoch) % 17 == 0), 5)
  return trace


def _resolve_checkpoint(root: Path, seed: int) -> Dict[str, Any]:
  manifest_path = root / CHECKPOINT_MANIFEST
  if not manifest_path.is_file():
    raise DemoError("Frozen checkpoint manifest is missing: {}".format(
        manifest_path))
  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  if manifest.get("formal_freeze") is not True:
    raise DemoError("Checkpoint manifest is not marked as a formal freeze.")
  entry = manifest.get("per_seed", {}).get(str(seed))
  if not isinstance(entry, Mapping):
    raise DemoError("Seed {} is absent from the checkpoint manifest.".format(
        seed))
  best = entry.get("checkpoints", {}).get("best", {})
  expected_sha = best.get("fingerprint")
  checkpoint_path = root / CHECKPOINT_ROOT / (
      "seed_{}/qmap_best.pth".format(seed))
  if not checkpoint_path.is_file():
    recorded = best.get("path")
    if isinstance(recorded, str) and Path(recorded).is_file():
      checkpoint_path = Path(recorded)
    else:
      raise DemoError(
          "Frozen CAPD checkpoint is missing. Expected {}".format(
              checkpoint_path))
  observed_sha = proactive_stage4.fingerprint_file(str(checkpoint_path))
  if observed_sha != expected_sha:
    raise DemoError(
        "Frozen CAPD checkpoint SHA-256 mismatch: expected {}, got {}".format(
            expected_sha, observed_sha))
  return {
      "seed": int(seed),
      "path": str(checkpoint_path.resolve()),
      "sha256": observed_sha,
      "selection_criterion": entry.get(
          "selection_criterion", "minimum_valid_loss_only"),
      "manifest_path": CHECKPOINT_MANIFEST.as_posix(),
  }


def _validate_runtime_dependencies(device: str) -> str:
  try:
    import torch
  except ImportError as error:
    raise DemoError(
        "CAPD demo requires PyTorch in the active Python environment.") from error
  if device == "cuda" and not torch.cuda.is_available():
    raise DemoError(
        "--device cuda was requested, but torch.cuda.is_available() is false.")
  return str(torch.__version__)


def _configure_known_framework_warnings() -> None:
  """Keep recording output clean without hiding unexpected warnings."""
  warnings.filterwarnings(
      "ignore", category=FutureWarning,
      message=r"You are using `torch\.load` with `weights_only=False`.*")
  warnings.filterwarnings(
      "ignore", category=UserWarning,
      message=r"enable_nested_tensor is True, but self\.use_nested_tensor.*")
  warnings.filterwarnings(
      "ignore", category=UserWarning,
      message=r"Support for mismatched src_key_padding_mask and mask.*")


def _parameters(policy: str, dram_pages: int) -> proactive_replay.ReplayParameters:
  if policy == "reactive_lru":
    return proactive_replay.ReplayParameters(
        policy_name=policy, dram_capacity_pages=dram_pages,
        history_window_size=20, early_reuse_window=64)
  return proactive_replay.ReplayParameters(
      policy_name=policy, dram_capacity_pages=dram_pages,
      F_low=8, F_target=16, b_max=4, candidate_size_K=8,
      history_window_size=20, early_reuse_window=64)


def _semantic_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
  summary_fields = (
      "total_accesses", "dram_hits", "nvm_reads", "nvm_writes",
      "page_enter_dram_count", "total_demotions", "proactive_demotions",
      "reactive_demotions", "emergency_demotions",
      "number_of_proactive_cycles", "number_of_proactive_rounds",
      "early_reuse_count", "minimum_free_frames",
      "free_frame_exhaustion_count")
  return {
      "policy": result["policy"],
      "summary": {key: result["summary"][key] for key in summary_fields},
      "weighted_cost": result["weighted_cost"],
      "events": [{
          key: row.get(key) for key in
          ("event_id", "event_type", "access_index", "page", "dirty")
      } for row in result["events"]],
      "rounds": [{
          key: row.get(key) for key in
          ("round_id", "access_index", "candidate_pages", "selected_pages",
           "b_t", "F_before", "F_after")
      } for row in result["rounds"]],
      "final_state": result["final_state"],
  }


def _capd_rerank_summary(
    policy: str, rounds: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
  if policy != "capd":
    return None
  changed = 0
  for row in rounds:
    b_t = int(row["b_t"])
    lru_prefix = list(row["candidate_pages"][:b_t])
    if list(row["selected_pages"]) != lru_prefix:
      changed += 1
  return {
      "comparison": "selected_pages_vs_same_round_lru_tail_prefix",
      "total_decision_rounds": len(rounds),
      "model_reranked_rounds": changed,
      "model_reranked_rate": changed / float(len(rounds)) if rounds else 0.0,
  }


def _verify_result(result: Mapping[str, Any], dram_pages: int) -> List[str]:
  summary = result["summary"]
  failures = []

  checks = {
      "access conservation": summary["total_accesses"] == (
          summary["dram_hits"] + summary["nvm_reads"] +
          summary["nvm_writes"]),
      "page-enter conservation": summary["page_enter_dram_count"] == (
          summary["nvm_reads"] + summary["nvm_writes"]),
      "demotion conservation": summary["total_demotions"] == (
          summary["proactive_demotions"] + summary["reactive_demotions"] +
          summary["emergency_demotions"]),
      "cost component sum": result["weighted_cost"] == sum(
          result["weighted_cost_components"].values()),
      "DRAM capacity conservation": (
          result["final_state"]["F_t"] +
          len(result["final_state"]["dram_resident"]) == dram_pages),
      "tier sets are disjoint": not (
          set(result["final_state"]["dram_resident"]) &
          set(result["final_state"]["nvm_resident"])),
  }
  for name, passed in checks.items():
    if not passed:
      failures.append(name)
  for index, row in enumerate(result["rounds"]):
    selected = row.get("selected_pages", [])
    candidates = row.get("candidate_pages", [])
    if not set(selected).issubset(set(candidates)):
      failures.append("round {} selected page outside candidate set".format(
          index))
      break
  return failures


def _run_policy(
    root: Path, stage0: Mapping[str, Any],
    cost_config: proactive_cost.CostConfiguration,
    trace: Sequence[Mapping[str, int]], policy: str, dram_pages: int,
    checkpoint: Optional[Mapping[str, Any]], device: str,
) -> Dict[str, Any]:
  policy_checkpoint = checkpoint if policy == "capd" else None
  policy_stage0 = proactive_stage5_replay._stage0_for_policy(
      stage0, policy, checkpoint=policy_checkpoint)
  parameters = _parameters(policy, dram_pages)
  ranker = None if policy == "reactive_lru" else policies.build_ranker(
      policy, trace=trace, checkpoint=policy_checkpoint, device=device)
  replay = proactive_replay.ProactiveReplay(
      policy_stage0, parameters, ranking_policy=ranker,
      invariant_mode="full", record_details=True,
      capture_page_enter_flags=True, measure_decision_latency=False,
      exclude_current_entering_page=True)
  replay.register_backing_pages(access["page"] for access in trace)
  raw = replay.run(trace, copy_trace=False, compact=False)
  replay.validate_log_accounting()
  summary = copy.deepcopy(raw["summary"])
  cost = proactive_cost.compute_weighted_cost(
      summary, cost_config.profiles["default"])
  early = proactive_stage8_replay.early_reuse_metrics(
      trace, raw["events"])
  result = {
      "schema_version": DEMO_SCHEMA,
      "artifact_status": DEMO_STATUS,
      "policy": policy,
      "policy_display_name": DISPLAY_NAMES[policy],
      "trace_source": "deterministic_synthetic_demo_generator",
      "formal_test": False,
      "formal_evidence": False,
      "test_used_for_selection": False,
      "future_information_accessed": bool(
          getattr(ranker, "future_information_accessed", False)),
      "checkpoint_sha256": (
          checkpoint["sha256"] if policy == "capd" and checkpoint else None),
      "parameters": parameters.to_dict(),
      "summary": summary,
      "weighted_cost": cost.weighted_cost,
      "weighted_cost_per_access": (
          cost.weighted_cost / float(summary["total_accesses"])),
      "weighted_cost_components": {
          "dram_hit_cost": cost.dram_hit_cost,
          "nvm_read_cost": cost.nvm_read_cost,
          "nvm_write_cost": cost.nvm_write_cost,
          "demotion_cost": cost.demotion_cost,
      },
      "capd_rerank_summary": _capd_rerank_summary(policy, raw["rounds"]),
      "early_reuse": early,
      "events": raw["events"],
      "rounds": raw["rounds"],
      "cycles": raw["cycles"],
      "final_state": raw["state"],
      "interpretation_boundary": (
          "Synthetic synchronous replay demonstrates the software loop and "
          "ranking/cost/state accounting only. It is not formal Test evidence, "
          "real NVM performance, foreground latency, or asynchronous execution."),
  }
  result["semantic_sha256"] = fingerprint_value(_semantic_payload(result))
  failures = _verify_result(result, dram_pages)
  if failures:
    raise DemoError("{} self-check failed: {}".format(
        DISPLAY_NAMES[policy], ", ".join(failures)))
  if policy == "capd" and result["future_information_accessed"]:
    raise DemoError("CAPD demo ranker unexpectedly accessed future information.")
  return result


def _print_banner() -> None:
  print("=" * 76)
  print(" CAPD CLOSED-LOOP DEMO | NON-FORMAL SYNTHETIC RUN")
  print(" This run demonstrates code execution; it is NOT formal experiment evidence.")
  print("=" * 76)


def _phase(index: int, total: int, title: str, pause: float) -> None:
  print("\n[{}/{}] {}".format(index, total, title), flush=True)
  if pause:
    time.sleep(pause)


def _print_table(results: Sequence[Mapping[str, Any]]) -> None:
  header = "{:<18} {:>8} {:>8} {:>8} {:>9} {:>12} {:>13}".format(
      "Policy", "Hit", "Read", "Write", "Demotion", "Cost/access",
      "Rank changes")
  print("\n" + header)
  print("-" * len(header))
  for result in results:
    summary = result["summary"]
    rerank = result["capd_rerank_summary"]
    rank_changes = (
        "{}/{}".format(rerank["model_reranked_rounds"],
                       rerank["total_decision_rounds"])
        if rerank is not None else "-")
    print("{:<18} {:>8} {:>8} {:>8} {:>9} {:>12.6f} {:>13}".format(
        result["policy_display_name"], summary["dram_hits"],
        summary["nvm_reads"], summary["nvm_writes"],
        summary["total_demotions"], result["weighted_cost_per_access"],
        rank_changes))


def run_demo(
    root: Path, output_directory: Path, selected_policies: Sequence[str],
    seed: int = 3136859, device: str = "cpu", dram_pages: int = 24,
    pause: float = 0.0,
) -> Dict[str, Any]:
  unknown = sorted(set(selected_policies) - set(DEFAULT_POLICIES))
  if unknown:
    raise DemoError("Unsupported demo policies: {}".format(unknown))
  if not selected_policies:
    raise DemoError("At least one demo policy is required.")
  if output_directory.exists():
    raise DemoError("Output directory already exists: {}".format(
        output_directory))

  _print_banner()
  _phase(1, 5, "Preflight: load contracts and verify inputs", pause)
  stage0_path = root / STAGE0_CONFIG
  cost_path = root / COST_CONFIG
  stage0 = finals_config.load_config(str(stage0_path))
  cost_config = proactive_cost.load_cost_config(str(cost_path))
  torch_version = None
  checkpoint = None
  if "capd" in selected_policies:
    torch_version = _validate_runtime_dependencies(device)
    _configure_known_framework_warnings()
    checkpoint = _resolve_checkpoint(root, seed)
  print("  [PASS] Stage-0 replay contract")
  print("  [PASS] Frozen default cost profile: hit=1 read=2 write=8 demotion=10")
  if checkpoint:
    print("  [PASS] PyTorch {} on {}".format(torch_version, device))
    print("  [PASS] Frozen CAPD checkpoint SHA-256: {}...".format(
        checkpoint["sha256"][:16]))

  _phase(2, 5, "Generate an isolated synthetic memory-access trace", pause)
  trace = build_demo_trace()
  trace_sha = fingerprint_value(trace)
  print("  [PASS] {} accesses, {} unique pages, trace SHA-256 {}...".format(
      len(trace), len({row["page"] for row in trace}), trace_sha[:16]))
  output_directory.mkdir(parents=True, exist_ok=False)
  _write_jsonl(output_directory / "demo_trace.jsonl", trace)

  _phase(3, 5, "Execute real replay and ranking implementations", pause)
  first_results = []
  for policy in selected_policies:
    print("  [RUN ] {}".format(DISPLAY_NAMES[policy]), flush=True)
    result = _run_policy(
        root, stage0, cost_config, trace, policy, dram_pages,
        checkpoint, device)
    first_results.append(result)
    _write_json(output_directory / "results" / (policy + ".json"), result)
    print("  [PASS] {} semantic SHA-256 {}...".format(
        DISPLAY_NAMES[policy], result["semantic_sha256"][:16]))

  _phase(4, 5, "Recompute cost and verify accounting invariants", pause)
  _print_table(first_results)
  for result in first_results:
    print("  [PASS] {:<16} access/page-enter/demotion/cost/state checks".format(
        result["policy_display_name"]))

  _phase(5, 5, "Repeat the run and compare semantic fingerprints", pause)
  repeat_hashes = {}
  for first in first_results:
    policy = first["policy"]
    repeated = _run_policy(
        root, stage0, cost_config, trace, policy, dram_pages,
        checkpoint, device)
    repeat_hashes[policy] = repeated["semantic_sha256"]
    if repeated["semantic_sha256"] != first["semantic_sha256"]:
      raise DemoError("{} repeat fingerprint mismatch.".format(
          DISPLAY_NAMES[policy]))
    print("  [PASS] {:<16} exact semantic match".format(
        DISPLAY_NAMES[policy]))

  result_hashes = {
      result["policy"]: result["semantic_sha256"] for result in first_results}
  verification = {
      "schema_version": DEMO_SCHEMA,
      "artifact_status": DEMO_STATUS,
      "closed_loop_status": "DEMO_CLOSED_LOOP_PASS",
      "formal_evidence": False,
      "trace_sha256": trace_sha,
      "result_semantic_sha256": result_hashes,
      "repeat_semantic_sha256": repeat_hashes,
      "checks": {
          "input_contracts_loaded": True,
          "checkpoint_sha256_verified": checkpoint is not None,
          "real_policy_implementations_executed": True,
          "cost_recomputed_from_raw_counters": True,
          "accounting_invariants_passed": True,
          "repeat_semantic_match": True,
          "formal_test_data_consumed": False,
      },
      "interpretation_boundary": (
          "DEMO_CLOSED_LOOP_PASS validates this synthetic demo run only; it "
          "does not upgrade, replace, or reproduce formal experimental evidence."),
  }
  manifest = {
      "schema_version": DEMO_SCHEMA,
      "artifact_status": DEMO_STATUS,
      "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
      "policies": list(selected_policies),
      "device": device,
      "dram_capacity_pages": dram_pages,
      "trace": {
          "source": "generated_in_run_capd_demo.py",
          "accesses": len(trace),
          "unique_pages": len({row["page"] for row in trace}),
          "sha256": trace_sha,
      },
      "checkpoint": (None if checkpoint is None else {
          key: checkpoint[key] for key in
          ("seed", "sha256", "selection_criterion", "manifest_path")}),
      "cost_config": {
          "path": COST_CONFIG.as_posix(),
          "sha256": proactive_stage4.fingerprint_file(str(cost_path)),
      },
      "formal_test_data_consumed": False,
      "formal_evidence": False,
  }
  _write_json(output_directory / "manifest.json", manifest)
  _write_json(output_directory / "summary.json", {
      "schema_version": DEMO_SCHEMA,
      "artifact_status": DEMO_STATUS,
      "rows": [{
          "policy": result["policy_display_name"],
          "dram_hits": result["summary"]["dram_hits"],
          "nvm_reads": result["summary"]["nvm_reads"],
          "nvm_writes": result["summary"]["nvm_writes"],
          "total_demotions": result["summary"]["total_demotions"],
          "proactive_demotions": result["summary"]["proactive_demotions"],
          "weighted_cost": result["weighted_cost"],
          "weighted_cost_per_access": result["weighted_cost_per_access"],
          "capd_rerank_summary": result["capd_rerank_summary"],
      } for result in first_results],
  })
  _write_json(output_directory / "verification.json", verification)
  print("\n" + "=" * 76)
  print(" DEMO_CLOSED_LOOP_PASS")
  print(" Artifacts: {}".format(output_directory))
  print(" Scope: synthetic synchronous replay; NOT formal experiment evidence")
  print("=" * 76)
  return verification


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      description="Run an isolated non-formal CAPD closed-loop demo.")
  parser.add_argument(
      "--output-root", default="outputs/capd_demo",
      help="Demo-only artifact root (default: outputs/capd_demo).")
  parser.add_argument(
      "--run-id", default=None,
      help="Unique demo run ID; default uses the current UTC time.")
  parser.add_argument(
      "--policies", default=",".join(DEFAULT_POLICIES),
      help="Comma-separated demo policies.")
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
  parser.add_argument("--dram-pages", type=int, default=24)
  parser.add_argument(
      "--pause", type=float, default=0.0,
      help="Seconds to pause after each phase heading for screen recording.")
  return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
  args = build_parser().parse_args(argv)
  run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime(
      "demo-%Y%m%dT%H%M%SZ")
  policies_arg = tuple(
      item.strip() for item in args.policies.split(",") if item.strip())
  output_root = Path(args.output_root)
  if not output_root.is_absolute():
    output_root = ROOT / output_root
  try:
    run_demo(
        ROOT, output_root / run_id, policies_arg, seed=args.seed,
        device=args.device, dram_pages=args.dram_pages, pause=args.pause)
  except Exception as error:  # Keep one clear terminal failure for recording.
    print("\n[DEMO_FAILED] {}: {}".format(
        type(error).__name__, error), file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
