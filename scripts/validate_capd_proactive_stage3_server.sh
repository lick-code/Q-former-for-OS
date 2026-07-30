#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG="${REPO_ROOT}/configs/finals/capd_proactive_stage3_active_mechanism.json"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage3-XXXXXX")"
LOG="${STAGE3_VALIDATION_LOG:-${REPO_ROOT}/stage3_validation.log}"

cleanup() {
  rm -rf -- "${TMP_DIR}"
}
trap cleanup EXIT

mkdir -p "${TMP_DIR}/pycache" "${TMP_DIR}/pytest-cache" "${TMP_DIR}/outputs"
export PYTHONPYCACHEPREFIX="${TMP_DIR}/pycache"
export PYTEST_ADDOPTS="-o cache_dir=${TMP_DIR}/pytest-cache"
cd "${REPO_ROOT}"
exec > >(tee "${LOG}") 2>&1

echo "[stage3] validate stages 0-2 and the predeclared stage-3 config"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage3_calibration.py \
  --config "${CONFIG}" \
  --validate-config

echo "[stage3] run stage-3 unit and synthetic integration tests"
"${PYTHON_BIN}" -m unittest discover \
  -s tests \
  -p 'test_capd_proactive_stage3.py' \
  -v

echo "[stage3] run frozen stage-0/1/2 regressions"
for pattern in \
    'test_capd_proactive_config.py' \
    'test_capd_proactive_replay.py' \
    'test_capd_stage1_stage2_integration.py' \
    'test_capd_proactive_cost.py'; do
  "${PYTHON_BIN}" -m unittest discover \
    -s tests \
    -p "${pattern}" \
    -v
done

echo "[stage3] compile without writing into the repository"
"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_stage3.py \
  scripts/prepare_capd_proactive_stage3_v2_manifest.py \
  scripts/run_capd_proactive_stage3_calibration.py \
  tests/test_capd_proactive_stage3.py

echo "[stage3] create isolated synthetic Train/Validation traces"
"${PYTHON_BIN}" - "${TMP_DIR}" <<'PY'
import csv
import json
import os
import sys

root = sys.argv[1]
for split, offset in (("train", 0), ("validation", 1000)):
  path = os.path.join(root, "{}.csv".format(split))
  with open(path, "w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(["pc", "address", "rw"])
    for page in range(40):
      for repeat in range(25):
        writer.writerow([
            hex(page), hex((offset + page) << 12), (page + repeat) % 2])

manifest = {
    "schema_version": "capd_proactive_stage3_input_manifest_v2_0",
    "calibration_kind": "synthetic_smoke",
    "path_base": "manifest_directory",
    "test_used_for_parameter_selection": False,
    "fresh_validation_attestation": {
        "capacity_rule_version": "capacity_rule_v2",
        "rule_frozen_before_validation_selection": True,
        "fresh_train_required": True,
        "train_used_in_rule_design": False,
        "fresh_validation_required": True,
        "validation_used_in_rule_design": False,
        "formal_test_reused": False,
        "previous_stage3_input_trace_fingerprints": {
            "synthetic_locality": ["0" * 64],
        },
    },
    "entries": [],
}
for split, role in (
    ("train", "training_and_fit"),
    ("validation", "parameter_selection")):
  manifest["entries"].append({
      "workload": "synthetic_locality",
      "split": split,
      "role": role,
      "trace_path": "{}.csv".format(split),
      "page_shift": 12,
      "source_kind": "raw_access_trace",
      "formal_test": False,
  })
with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as output:
  json.dump(manifest, output, indent=2, sort_keys=True)

bad = dict(manifest)
bad["entries"] = [dict(item) for item in manifest["entries"]]
bad["entries"][1]["split"] = "test"
bad["entries"][1]["role"] = "final_evaluation_only"
bad["entries"][1]["formal_test"] = True
with open(os.path.join(root, "test_manifest.json"), "w", encoding="utf-8") as output:
  json.dump(bad, output, indent=2, sort_keys=True)
PY

before_hash="$("${PYTHON_BIN}" - "${TMP_DIR}/manifest.json" "${TMP_DIR}/train.csv" "${TMP_DIR}/validation.csv" <<'PY'
import hashlib
import sys
digest = hashlib.sha256()
for path in sys.argv[1:]:
  with open(path, "rb") as input_file:
    digest.update(input_file.read())
print(digest.hexdigest())
PY
)"

echo "[stage3] run the complete synthetic matrix twice"
for run_id in synthetic-a synthetic-b; do
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage3_calibration.py \
    --config "${CONFIG}" \
    --input-manifest "${TMP_DIR}/manifest.json" \
    --run-id "${run_id}" \
    --output-root "${TMP_DIR}/outputs" \
    --project-root "${REPO_ROOT}"
done

echo "[stage3] verify deterministic decisions, complete artifacts, and pending gates"
"${PYTHON_BIN}" - "${TMP_DIR}/outputs" <<'PY'
import json
import os
import sys

root = sys.argv[1]
required = [
    "resolved_config.json", "provenance.json", "input_manifest.json",
    "working_set_summary.json", "capacity_pressure_audit.json",
    "reactive_results.jsonl", "burst_statistics.json", "burst_windows.jsonl",
    "watermark_results.jsonl", "watermark_summary.csv",
    "bmax_results.jsonl", "bmax_summary.csv", "selection_decision.json",
    "freeze_candidate.json", "run_state.json", "checkpoints",
    "logs/progress.jsonl", "report.md",
]
runs = [os.path.join(root, "stage3", name)
        for name in ("synthetic-a", "synthetic-b")]
for run in runs:
  assert all(os.path.exists(os.path.join(run, name)) for name in required), run
  with open(os.path.join(run, "resolved_config.json"), encoding="utf-8") as f:
    config = json.load(f)
  assert config["stage_status"] == \
      "stage3_implemented_awaiting_calibration_inputs"
  with open(os.path.join(run, "selection_decision.json"), encoding="utf-8") as f:
    decision = json.load(f)
  assert decision["test_used"] is False
  assert decision["capd_used_for_selection"] is False
  assert decision["stage4_candidate_status"] == "pending"
  with open(os.path.join(run, "freeze_candidate.json"), encoding="utf-8") as f:
    freeze = json.load(f)
  assert freeze["main_config_updated"] is False
  with open(os.path.join(run, "run_state.json"), encoding="utf-8") as f:
    state = json.load(f)
  assert state["status"] == "completed"
  assert state["completed_replay_tasks"] > 0
with open(os.path.join(runs[0], "selection_decision.json"), "rb") as f:
  first = f.read()
with open(os.path.join(runs[1], "selection_decision.json"), "rb") as f:
  second = f.read()
assert first == second
PY

after_hash="$("${PYTHON_BIN}" - "${TMP_DIR}/manifest.json" "${TMP_DIR}/train.csv" "${TMP_DIR}/validation.csv" <<'PY'
import hashlib
import sys
digest = hashlib.sha256()
for path in sys.argv[1:]:
  with open(path, "rb") as input_file:
    digest.update(input_file.read())
print(digest.hexdigest())
PY
)"
test "${before_hash}" = "${after_hash}"

echo "[stage3] verify formal Test input is rejected"
if "${PYTHON_BIN}" scripts/run_capd_proactive_stage3_calibration.py \
    --config "${CONFIG}" \
    --input-manifest "${TMP_DIR}/test_manifest.json" \
    --run-id must-fail \
    --output-root "${TMP_DIR}/outputs" \
    --project-root "${REPO_ROOT}"; then
  echo "ERROR: Test input unexpectedly passed stage-3 gate" >&2
  exit 1
fi
test ! -e "${TMP_DIR}/outputs/stage3/must-fail"

echo "[stage3] repository whitespace validation"
git diff --check

if [[ -n "${STAGE3_INPUT_MANIFEST:-}" ]]; then
  real_run_id="${STAGE3_RUN_ID:-stage3-$(date -u +%Y%m%dT%H%M%SZ)}"
  real_output_root="${STAGE3_OUTPUT_ROOT:-${REPO_ROOT}/outputs/capd_proactive_calibration}"
  echo "[stage3] run real Train/Validation calibration run_id=${real_run_id}"
  resume_args=()
  if [[ "${STAGE3_RESUME:-0}" == "1" ]]; then
    resume_args+=(--resume)
  fi
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage3_calibration.py \
    --config "${CONFIG}" \
    --input-manifest "${STAGE3_INPUT_MANIFEST}" \
    --run-id "${real_run_id}" \
    --output-root "${real_output_root}" \
    --project-root "${REPO_ROOT}" \
    "${resume_args[@]}"
  real_run_dir="${real_output_root}/stage3/${real_run_id}"
  "${PYTHON_BIN}" - "${real_run_dir}" <<'PY'
import json
import os
import sys

run = sys.argv[1]
with open(os.path.join(run, "selection_decision.json"), encoding="utf-8") as f:
  decision = json.load(f)
with open(os.path.join(run, "freeze_candidate.json"), encoding="utf-8") as f:
  freeze = json.load(f)
assert decision["capacity_rule_version"] == "capacity_rule_v2"
assert decision["fresh_validation_attested"] is True
assert decision["test_used"] is False
profile = decision["capacity"]["recommended_profile"]
if profile is None:
  print("STAGE3_V2_CAPACITY_NOT_FREEZABLE")
  raise SystemExit(3)
assert decision["proactive_calibration_executed"] is True
if freeze["status"] != "candidate_ready_for_user_confirmation":
  print("STAGE3_V2_PROACTIVE_NOT_FREEZABLE")
  raise SystemExit(4)
print("STAGE3_V2_FREEZE_CANDIDATE_READY profile={}".format(profile))
PY
  echo "STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE"
else
  echo "STAGE3_IMPLEMENTED_AWAITING_CALIBRATION_INPUTS"
fi
