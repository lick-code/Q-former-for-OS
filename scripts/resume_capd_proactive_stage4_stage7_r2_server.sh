#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$PWD}"
RUN_ID="stage4-stage7-unified-r2"
R1_ROOT="outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r1"
R2_ROOT="outputs/capd_proactive_stage4_stage7/${RUN_ID}"
CONFIG="configs/finals/capd_proactive_stage4_stage7_search_r2.json"
FREEZE="outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json"
MANIFEST="${R1_ROOT}/input_manifest.json"
LOG="validation_logs/capd_stage4_r2_resume.log"
EXIT_FILE="validation_logs/capd_stage4_r2_resume.exit"
RECEIPT="${R2_ROOT}/orchestration_repair_resume_receipt.json"
ORIGINAL_EXIT="validation_logs/capd_stage4_r2_search.exit"

cd "$PROJECT_ROOT"
mkdir -p validation_logs
exec > >(tee -a "$LOG") 2>&1
trap 'rc=$?; printf "%s\n" "$rc" > "$EXIT_FILE"; printf "[DONE] resume exit=%s\n" "$rc"' EXIT

printf '[STEP 1/5] verify frozen code, config, and partial-run evidence\n'
if [[ ! -f "$ORIGINAL_EXIT" || "$(tr -d '\r\n' < "$ORIGINAL_EXIT")" != "1" ]]; then
  printf '[REFUSE] original search exit=1 evidence is missing or changed\n' >&2
  exit 2
fi
sha256sum --check --strict <<'SHA'
3ac2078a1ecf521f42b9fe67dc93885ee43d45efd4bfbe69bbf230adb277f6de  qmap/proactive_stage4_stage7.py
4100b8b0afa8810c8ba0d5f8e329c123a990fa15bf5a28699e30f66ff2948fbf  scripts/run_capd_proactive_stage4_stage7.py
eb6250ef2ad4d0c3fda587d695366a3df7de34064f170f4bcb8d2900eaa61065  qmap/qmap_train.py
86b5a7341e8c7eceb9df9827dbbeaa2c4e131531b00fded5ffb1afc4a488ca3a  configs/finals/capd_proactive_stage4_stage7_search_r2.json
02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1  outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json
444cd59dddaa84d73e6f55c3d0c8aa052360e16f4e0687c632be65a3b7b13c50  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r1/input_manifest.json
0912390a46a38d44c6e2bc61db8be034faa31457b5867ddd441a1b96a67d76e9  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/sample_structure_report.json
3c09724ae76a48cf07917ac66699d4968e382b34ae2a3344b73005ac50350619  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/external_cache_reference.json
c9e2e70419688f740dae9d41e4bb255f3289b8d905b5802671b776de462820be  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/search_contract_confirmation.json
086a07011fa9a47e557a820309be26d6b8a02c43c11ba1a25170dd746a967dfc  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/confirmed_search_contract.json
bababf9d2ec5c8469e7bad788124d954cba0247dd0acd7d5712f28d281bbc9a9  outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/search/semantic/phase_result.json
SHA

printf '[STEP 2/5] compile and run the Stage4 regression suite\n'
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

printf '[STEP 3/5] audit completed checkpoints and the known architecture failure\n'
python3 - "$R2_ROOT" <<'PY'
import json
import sys
from pathlib import Path

from qmap import proactive_stage4_stage7 as stage4

root = Path(sys.argv[1])
seeds = {3136859, 42, 2026}
semantic_ids = {
    "sem-reference", "sem-L128", "sem-L512", "sem-H10", "sem-H40",
    "sem-lam111", "sem-lam114"}
architecture_ids = {"arch-balanced", "arch-compact", "arch-wide", "arch-deep"}
optimization_ids = {"opt-balanced", "opt-steady", "opt-fast", "opt-regularized"}
allowed_ids = semantic_ids | architecture_ids | optimization_ids
failure_reason = "r1 semantic cache index identity mismatch: da0dab0afec1945a70ef"

def load(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

run_state = load(root / "run_state.json")
search_state = load(root / "search_state.json")
confirmation = load(root / "search_contract_confirmation.json")
phase = load(root / "search" / "semantic" / "phase_result.json")

assert run_state["run_id"] == "stage4-stage7-unified-r2"
assert run_state["search_contract_confirmed"] is True
assert run_state["formal_freeze"] is False
assert run_state["test_trace_opened"] is False
assert run_state["pressure_trace_opened"] is False
assert search_state["status"] == "running"
assert search_state["active_training_processes"] == 0
assert search_state["completed_phases"] in (["semantic"],
                                             ["semantic", "architecture"])
assert confirmation["human_confirmation"] is True
assert confirmation["training_run_count"] == 45
assert confirmation["formal_freeze"] is False
assert phase["phase"] == "semantic"
assert phase["winner"]["candidate"]["candidate_id"] == "sem-reference"
assert len(phase["evaluated"]) == 7 and phase["failures"] == []

failure_files = sorted((root / "search" / "architecture").glob(
    "*/failure.json"))
if len(failure_files) != 4:
    raise RuntimeError("expected four preserved architecture failure files")
for path in failure_files:
    value = load(path)
    assert value["candidate_id"] in architecture_ids
    assert value["status"] == "rejected"
    assert value["reason"] == failure_reason

manifests = sorted((root / "checkpoints").glob(
    "*/seed_*/checkpoint_manifest.json"))
if not (21 <= len(manifests) < 45):
    raise RuntimeError(
        "expected exactly 21 completed semantic runs for the first repair "
        "resume, or 22-44 verified runs for a later safe resume; got {}".format(
            len(manifests)))

completed = set()
for manifest_path in manifests:
    candidate_id = manifest_path.parents[1].name
    seed = int(manifest_path.parent.name.split("_", 1)[1])
    assert candidate_id in allowed_ids and seed in seeds
    completed.add((candidate_id, seed))
    contract_path = manifest_path.parent / "training_contract.json"
    manifest = load(manifest_path)
    contract = load(contract_path)
    assert contract["candidate_id"] == candidate_id
    assert int(contract["seed"]) == seed
    assert contract["test_trace_opened"] is False
    assert contract["pressure_trace_opened"] is False
    assert manifest["test_trace_opened"] is False
    assert manifest["stage4_training_contract_fingerprint"] == (
        stage4.fingerprint_value(contract))
    for role in ("best", "last"):
        checkpoint = manifest["checkpoints"][role]
        path = Path(checkpoint["path"])
        assert path.is_file(), path
        assert stage4.fingerprint_file(str(path)) == checkpoint["fingerprint"]

expected_semantic = {(candidate_id, seed) for candidate_id in semantic_ids
                     for seed in seeds}
assert expected_semantic <= completed
assert not (root / "final_stage4_freeze.json").exists()
assert not (root / "stage8_model_contract.json").exists()

events = [json.loads(line) for line in
          (root / "logs" / "events.jsonl").read_text(
              encoding="utf-8").splitlines() if line]
semantic_finishes = {
    (row.get("candidate"), int(row.get("seed")))
    for row in events
    if row.get("event") == "training_finished" and row.get("returncode") == 0
    and row.get("candidate") in semantic_ids}
assert semantic_finishes == expected_semantic
known_rejections = [row for row in events
                    if row.get("event") == "candidate_rejected"
                    and row.get("phase") == "architecture"
                    and row.get("reason") == failure_reason]
assert {row["candidate"] for row in known_rejections} == architecture_ids

print("[OK] verified completed training manifests:", len(manifests))
print("[OK] preserved semantic phase and four architecture failure records")
PY

printf '[STEP 4/5] record the authorized orchestration-only repair\n'
python3 - "$RECEIPT" <<'PY'
import datetime
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = {
    "schema_version": "capd_stage4_r2_orchestration_repair_v1_0",
    "repair_id": "r2-cross-phase-semantic-cache-owner-alias-v1",
    "run_id": "stage4-stage7-unified-r2",
    "failure_stage": "architecture_before_any_architecture_training",
    "completed_training_runs_before_repair": 21,
    "preserved_semantic_phase_result_sha256":
        "bababf9d2ec5c8469e7bad788124d954cba0247dd0acd7d5712f28d281bbc9a9",
    "old_runner_sha256":
        "b4f2aa94070f3ade37fc007c639e92306fe83603a194343c7c8e30a7ee7498b6",
    "new_runner_sha256":
        "4100b8b0afa8810c8ba0d5f8e329c123a990fa15bf5a28699e30f66ff2948fbf",
    "repair_scope": "external_cache_cross_phase_candidate_alias_validation_only",
    "training_contract_changed": False,
    "search_config_changed": False,
    "sample_or_vocabulary_changed": False,
    "checkpoint_changed": False,
    "model_performance_used_to_define_repair": False,
    "test_trace_opened": False,
    "pressure_trace_opened": False,
    "formal_freeze": False,
}
if path.exists():
    actual = json.loads(path.read_text(encoding="utf-8"))
    for key, value in expected.items():
        assert actual.get(key) == value, key
else:
    value = dict(expected)
    value["recorded_at"] = datetime.datetime.now(
        datetime.timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)
print("[OK] orchestration repair receipt:", path)
PY

printf '[STEP 5/5] resume the confirmed search; completed checkpoints are reused\n'
python3 scripts/run_capd_proactive_stage4_stage7.py resume \
  --config "$CONFIG" \
  --stage3-freeze "$FREEZE" \
  --input-manifest "$MANIFEST" \
  --reuse-sample-cache-from "$R1_ROOT" \
  --run-id "$RUN_ID" \
  --project-root "$PROJECT_ROOT" \
  --device cuda --require-cuda \
  --train-workers 4 --sample-workers 6 --replay-workers 6

python3 - "$R2_ROOT" <<'PY'
import json
import sys
from pathlib import Path

from qmap import proactive_stage4_stage7 as stage4

root = Path(sys.argv[1])
load = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
run_state = load("run_state.json")
search_state = load("search_state.json")
verification = load("verification.json")
receipt = root / "orchestration_repair_resume_receipt.json"

assert len(list((root / "checkpoints").glob(
    "*/seed_*/checkpoint_manifest.json"))) == 45
assert run_state["status"] == "candidate_ready_awaiting_formal_freeze"
assert run_state["formal_freeze"] is False
assert search_state["status"] == "completed_candidate_ready"
assert search_state["completed_phases"] == [
    "semantic", "architecture", "optimization"]
assert search_state["active_training_processes"] == 0
assert search_state["formal_freeze"] is False
assert verification["status"] == "candidate_verified_awaiting_formal_freeze"
assert verification["test_trace_opened"] is False
assert verification["pressure_trace_opened"] is False
assert verification["artifact_sha256"][receipt.name] == (
    stage4.fingerprint_file(str(receipt)))
assert not (root / "final_stage4_freeze.json").exists()
assert not (root / "stage8_model_contract.json").exists()
print("[FINAL] STAGE4_R2_SEARCH_RESUMED_AND_CANDIDATE_READY")
print("[GATE] FORMAL_FREEZE_NOT_CREATED_AWAITING_REVIEW")
PY
