#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$PWD}"
RUN_ID="stage4-stage7-unified-r2"
R1_ROOT="outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r1"
R2_ROOT="outputs/capd_proactive_stage4_stage7/${RUN_ID}"
CONFIG="configs/finals/capd_proactive_stage4_stage7_search_r2.json"
FREEZE="outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json"
MANIFEST="${R1_ROOT}/input_manifest.json"
CONFIG_SHA256="3ea507da8ea119b7b6e4103057611ffbffb234ea2b5f3a6d63e5ddcf44d79c90"

cd "$PROJECT_ROOT"

printf '%s  %s\n' "$CONFIG_SHA256" "$CONFIG" | sha256sum --check --strict

python3 -m py_compile \
  qmap/proactive_stage4_stage7.py \
  qmap/qmap_train.py \
  scripts/run_capd_proactive_stage4_stage7.py

python3 -m unittest \
  tests.test_capd_proactive_stage4_stage7 \
  tests.test_capd_proactive_stage4_stage7_e2e \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  -v

python3 scripts/run_capd_proactive_stage4_stage7.py preflight \
  --config "$CONFIG" \
  --stage3-freeze "$FREEZE" \
  --input-manifest "$MANIFEST" \
  --reuse-sample-cache-from "$R1_ROOT" \
  --run-id "$RUN_ID" \
  --project-root "$PROJECT_ROOT" \
  --device cuda --require-cuda \
  --train-workers 4 --sample-workers 6 --replay-workers 6

python3 scripts/run_capd_proactive_stage4_stage7.py samples \
  --config "$CONFIG" \
  --stage3-freeze "$FREEZE" \
  --input-manifest "$MANIFEST" \
  --reuse-sample-cache-from "$R1_ROOT" \
  --run-id "$RUN_ID" \
  --project-root "$PROJECT_ROOT" \
  --device cuda --require-cuda \
  --train-workers 4 --sample-workers 6 --replay-workers 6

python3 - "$R1_ROOT" "$R2_ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

r1 = Path(sys.argv[1])
r2 = Path(sys.argv[2])

def load(root, name):
    with (root / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)

def sha(root, name):
    return hashlib.sha256((root / name).read_bytes()).hexdigest()

r1_run = load(r1, "run_state.json")
r1_search = load(r1, "search_state.json")
r2_run = load(r2, "run_state.json")
r2_search = load(r2, "search_state.json")
gate = load(r2, "sample_structure_verification.json")
report = load(r2, "sample_structure_report.json")
reference = load(r2, "external_cache_reference.json")

assert r1_run["status"] == "sample_structure_gate_failed"
assert r1_run["sample_structure_gate_passed"] is False
assert r1_run["search_contract_confirmed"] is False
assert r1_run["formal_freeze"] is False
assert r1_search["status"] == "not_started"
assert r1_search["active_training_processes"] == 0

assert r2_run["status"] == "sample_structure_gate_passed_awaiting_search_confirmation"
assert r2_run["search_contract_confirmed"] is False
assert r2_run["formal_freeze"] is False
assert r2_search["status"] == "not_started"
assert r2_search["active_training_processes"] == 0
assert r2_search["completed_phases"] == []

assert gate["status"] == "PASS" and gate["gate_pass"] is True
assert gate["protocol_repair"] is True
assert gate["active_selection_workloads"] == [
    "canneal", "dedup_pressure", "blackscholes", "swaptions"]
assert gate["structural_zero_decision_validation"] == [
    "streamcluster_pressure", "fluidanimate"]
assert gate["zero_sample_workload_splits"] == [
    "fluidanimate/validation", "streamcluster_pressure/validation"]
assert gate["zero_valid_decision_workload_splits"] == [
    "fluidanimate/validation", "streamcluster_pressure/validation"]
assert gate["structural_identity_violations"] == []
assert report["semantic_dataset_count"] == 7
assert reference["mode"] == "verified_external_read_only_reference"
assert reference["copy_cache_files"] is False
assert len(reference["datasets"]) == 7

assert sha(r2, "sample_structure_report.json") == gate[
    "sample_structure_report_sha256"]
assert sha(r2, "sample_manifest.json") == gate["sample_manifest_sha256"]
assert sha(r2, "vocabulary_manifest.json") == gate[
    "vocabulary_manifest_sha256"]
assert sha(r2, "external_cache_reference.json") == gate[
    "external_cache_reference_sha256"]
assert sha(r2, "protocol_repair.json") == gate["protocol_repair_sha256"]

for field in ("training_started", "search_started", "checkpoint_created",
              "candidate_selected", "test_trace_opened",
              "pressure_trace_opened", "search_contract_confirmed",
              "formal_freeze"):
    assert gate[field] is False, (field, gate[field])

for directory in ("search", "checkpoints"):
    assert not any(path.is_file() for path in (r2 / directory).rglob("*"))
for directory in ("datasets", "vocabulary"):
    assert not any(path.is_file() for path in (r2 / directory).rglob("*")), (
        "r2 must reference r1 cache without copying", directory)

print("[FINAL] STAGE4_R2_PREFLIGHT_AND_EXTERNAL_CACHE_GATE_VERIFIED")
print("[GATE] STOPPED_BEFORE_HUMAN_SEARCH_CONTRACT_CONFIRMATION")
PY
