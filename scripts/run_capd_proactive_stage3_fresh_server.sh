#!/usr/bin/env bash
# Collect a genuinely fresh 1M pair, preflight it, then run Stage 3 once.
# Run with "bash ..."; do not source this file into an interactive terminal.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PHASE="stage3_v2_fresh_001"
QMAP_ROOT_ARG=()

usage() {
  echo "usage: bash scripts/run_capd_proactive_stage3_fresh_server.sh [--phase NAME] [--qmap-root PATH]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      PHASE="$2"
      shift 2
      ;;
    --qmap-root)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      QMAP_ROOT_ARG=(--qmap-root "$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "STAGE3_FRESH_SERVER_ERROR: unknown argument $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! "${PHASE}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "STAGE3_FRESH_SERVER_ERROR: unsafe phase name ${PHASE}" >&2
  exit 2
fi

cd "${REPO_ROOT}" || exit 2
PREVIOUS_RUN="${REPO_ROOT}/outputs/capd_proactive_calibration/stage3/stage3-real-001"
RAW_ROOT="${REPO_ROOT}/dataset/raw_traces/finals_v3_recollect/${PHASE}"
PAIR_ROOT="${REPO_ROOT}/dataset/processed/capd_stage3_fresh/${PHASE}"
V2_MANIFEST="${REPO_ROOT}/stage3_manifest_${PHASE}.json"
RUN_ID="stage3-v2-${PHASE}"
OUTPUT_ROOT="${REPO_ROOT}/outputs/capd_proactive_calibration"
PREFLIGHT="${OUTPUT_ROOT}/stage3/${RUN_ID}-input-preflight.json"

run_step() {
  echo "[stage3-fresh] $1"
  shift
  "$@"
  status=$?
  if [[ "${status}" -ne 0 ]]; then
    echo "STAGE3_FRESH_SERVER_STEP_FAILED status=${status}" >&2
    return "${status}"
  fi
  return 0
}

run_step "preflight collector runtime before creating data" \
  "${PYTHON_BIN}" scripts/collect_finals_v3_recollect.py \
  "${QMAP_ROOT_ARG[@]}" \
  --preflight-only \
  --workloads \
  canneal_native_pilot,streamcluster_native_pilot,dedup_native_pilot
status=$?
[[ "${status}" -eq 0 ]] || exit "${status}"

project_commit="$(git rev-parse HEAD 2>/dev/null || true)"

run_step "collect fresh canneal 1M" \
  "${PYTHON_BIN}" scripts/collect_finals_v3_recollect.py \
  "${QMAP_ROOT_ARG[@]}" \
  --phase "${PHASE}" \
  --run-id "${PHASE}" \
  --workloads canneal_native_pilot \
  --max-records 1000000 \
  --skip-records 0 \
  --trace-ref-multiplier 100 \
  --trace-after-instrs 500000000 \
  --project-commit "${project_commit}" \
  --resume
status=$?
[[ "${status}" -eq 0 ]] || exit "${status}"

run_step "collect fresh streamcluster 1M" \
  "${PYTHON_BIN}" scripts/collect_finals_v3_recollect.py \
  "${QMAP_ROOT_ARG[@]}" \
  --phase "${PHASE}" \
  --run-id "${PHASE}" \
  --workloads streamcluster_native_pilot \
  --max-records 1000000 \
  --skip-records 0 \
  --trace-ref-multiplier 100 \
  --trace-after-instrs 5000000000 \
  --project-commit "${project_commit}" \
  --resume
status=$?
[[ "${status}" -eq 0 ]] || exit "${status}"

run_step "collect fresh dedup 1M" \
  "${PYTHON_BIN}" scripts/collect_finals_v3_recollect.py \
  "${QMAP_ROOT_ARG[@]}" \
  --phase "${PHASE}" \
  --run-id "${PHASE}" \
  --workloads dedup_native_pilot \
  --max-records 1000000 \
  --skip-records 100000 \
  --trace-ref-multiplier 100 \
  --trace-after-instrs 100000000 \
  --project-commit "${project_commit}" \
  --resume
status=$?
[[ "${status}" -eq 0 ]] || exit "${status}"

if [[ -f "${PAIR_ROOT}/pair_manifest.json" ]]; then
  echo "[stage3-fresh] reuse complete fresh Train/Validation pair ${PAIR_ROOT}"
else
  run_step "materialize 600k Train plus 400k Validation; never create Test" \
    "${PYTHON_BIN}" scripts/prepare_capd_proactive_stage3_fresh_pair.py \
    --source "canneal=${RAW_ROOT}/canneal_native_pilot.csv" \
    --source \
    "streamcluster_pressure=${RAW_ROOT}/streamcluster_native_pilot.csv" \
    --source "dedup_pressure=${RAW_ROOT}/dedup_native_pilot.csv" \
    --output-directory "${PAIR_ROOT}" \
    --train-records 600000 \
    --validation-records 400000 \
    --project-root "${REPO_ROOT}"
  status=$?
  [[ "${status}" -eq 0 ]] || exit "${status}"
fi

if [[ -f "${V2_MANIFEST}" ]]; then
  echo "[stage3-fresh] reuse manifest ${V2_MANIFEST}"
else
  run_step "build fresh v2 manifest with previous-input deny-list" \
    "${PYTHON_BIN}" scripts/prepare_capd_proactive_stage3_v2_manifest.py \
    --previous-run-directory "${PREVIOUS_RUN}" \
    --train "canneal=${PAIR_ROOT}/canneal/train.csv" \
    --validation "canneal=${PAIR_ROOT}/canneal/validation.csv" \
    --train \
    "streamcluster_pressure=${PAIR_ROOT}/streamcluster_pressure/train.csv" \
    --validation \
    "streamcluster_pressure=${PAIR_ROOT}/streamcluster_pressure/validation.csv" \
    --train "dedup_pressure=${PAIR_ROOT}/dedup_pressure/train.csv" \
    --validation \
    "dedup_pressure=${PAIR_ROOT}/dedup_pressure/validation.csv" \
    --output "${V2_MANIFEST}" \
    --project-root "${REPO_ROOT}"
  status=$?
  [[ "${status}" -eq 0 ]] || exit "${status}"
fi

mkdir -p "$(dirname "${PREFLIGHT}")"
run_step "fail-fast capacity reachability preflight" \
  "${PYTHON_BIN}" scripts/preflight_capd_proactive_stage3_inputs.py \
  --input-manifest "${V2_MANIFEST}" \
  --project-root "${REPO_ROOT}" \
  --output "${PREFLIGHT}"
status=$?
if [[ "${status}" -ne 0 ]]; then
  echo "STAGE3_FRESH_TRACE_REJECTED_BEFORE_EXPENSIVE_REPLAY"
  echo "STAGE3_PREFLIGHT_ARTIFACT=${PREFLIGHT}"
  exit "${status}"
fi

if [[ -d "${OUTPUT_ROOT}/stage3/${RUN_ID}" ]]; then
  echo "STAGE3_FRESH_SERVER_ERROR: final run already exists: ${RUN_ID}" >&2
  exit 2
fi

echo "[stage3-fresh] start formal Stage-3 run ${RUN_ID}"
resume_value=0
if [[ -d "${OUTPUT_ROOT}/stage3/${RUN_ID}.incomplete" ]]; then
  resume_value=1
  echo "[stage3-fresh] resume matching incomplete run ${RUN_ID}"
fi
STAGE3_INPUT_MANIFEST="${V2_MANIFEST}" \
STAGE3_RUN_ID="${RUN_ID}" \
STAGE3_OUTPUT_ROOT="${OUTPUT_ROOT}" \
STAGE3_RESUME="${resume_value}" \
bash scripts/validate_capd_proactive_stage3_server.sh
status=$?
echo "STAGE3_FRESH_SERVER_FINISHED status=${status}"
exit "${status}"
