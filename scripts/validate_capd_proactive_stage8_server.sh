#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 RUN_ID [DEVICE]" >&2
  exit 2
fi

RUN_ID="$1"
DEVICE="${2:-cuda:0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ROOT="${PROJECT_ROOT}/outputs/capd_proactive_stage8/${RUN_ID}"
TEST_LOG="${RUN_ROOT}/logs/stage1_stage8_regression.log"
CURRENT_STEP="bootstrap"

cd "${PROJECT_ROOT}"

preserve_failure() {
  local exit_code=$?
  trap - ERR
  set +e
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    mark-not-verified --failure-step "${CURRENT_STEP}"
  echo "[FAILED] Stage-8 validation stopped at ${CURRENT_STEP}; evidence preserved in ${RUN_ROOT}" >&2
  exit "${exit_code}"
}
trap preserve_failure ERR

echo "python=$(${PYTHON_BIN} -c 'import sys; print(sys.version)')"
"${PYTHON_BIN}" - <<'PY'
import torch
print("torch={}".format(torch.__version__))
print("cuda_available={}".format(torch.cuda.is_available()))
if torch.cuda.is_available():
  print("cuda_device={}".format(torch.cuda.get_device_name(0)))
PY

CURRENT_STEP="preflight"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" --device "${DEVICE}" preflight

CURRENT_STEP="static_compile"
"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_stage8_contract.py \
  qmap/proactive_stage8_replay.py \
  qmap/proactive_stage8_results.py \
  scripts/run_capd_proactive_stage8.py

CURRENT_STEP="synthetic_e2e"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" synthetic

CURRENT_STEP="stage1_stage8_regression"
mkdir -p "$(dirname "${TEST_LOG}")"
"${PYTHON_BIN}" -m unittest discover -s tests -p 'test*.py' -v 2>&1 | tee "${TEST_LOG}"

CURRENT_STEP="record_regression_receipt"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
  record-tests --test-log "${TEST_LOG}"

CURRENT_STEP="formal_144_job_execute"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" --device "${DEVICE}" execute

CURRENT_STEP="audited_aggregation"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" aggregate

CURRENT_STEP="independent_verification"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage8.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" verify

trap - ERR
