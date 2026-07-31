#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 RUN_ID COLLECTION_MANIFEST" >&2
  exit 2
fi

RUN_ID=$1
COLLECTION_MANIFEST=$2
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "${PROJECT_ROOT}"
PYTHON_BIN=${PYTHON_BIN:-python3}
export CAPD_DIRTY_WORKTREE=${CAPD_DIRTY_WORKTREE:-true}
RUN_ROOT="outputs/capd_proactive_stage7/${RUN_ID}"
LOG_ROOT="${RUN_ROOT}/logs"
CURRENT_STEP=preflight
SUCCESS=0

preserve_failure() {
  local exit_code=$?
  if [[ ${SUCCESS} -eq 0 ]]; then
    "${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
      mark-not-verified --run-id "${RUN_ID}" \
      --failure-step "${CURRENT_STEP}" >/dev/null 2>&1 || true
    echo "[FAILED] Stage-7 validation stopped at ${CURRENT_STEP}; evidence preserved in ${RUN_ROOT}" >&2
  fi
  exit "${exit_code}"
}
trap preserve_failure EXIT

test "$(git branch --show-current)" = "main"
"${PYTHON_BIN}" -c 'import sys; print("python={}".format(sys.version))'

"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  preflight --run-id "${RUN_ID}"
mkdir -p "${LOG_ROOT}"

CURRENT_STEP=static_compile
"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_stage7_workloads.py \
  scripts/audit_capd_proactive_stage7_candidates.py \
  scripts/record_capd_proactive_stage7_collection.py \
  scripts/verify_capd_proactive_stage7_collection_receipt.py \
  scripts/prepare_capd_proactive_stage7_manifest.py

CURRENT_STEP=stage1_stage7_regression
set +e
"${PYTHON_BIN}" -m unittest discover -s tests -p 'test_capd*.py' -v \
  2>&1 | tee "${LOG_ROOT}/stage1_stage7_regression.log"
TEST_EXIT=${PIPESTATUS[0]}
set -e
if [[ ${TEST_EXIT} -ne 0 ]]; then
  exit "${TEST_EXIT}"
fi

CURRENT_STEP=record_regression_receipt
"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  record-tests --run-id "${RUN_ID}" \
  --test-log "${LOG_ROOT}/stage1_stage7_regression.log" \
  --runner-exit-code "${TEST_EXIT}" --minimum-tests 180

CURRENT_STEP=prepare_suite
"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  prepare --run-id "${RUN_ID}" \
  --collection-manifest "${COLLECTION_MANIFEST}"

CURRENT_STEP=verification
"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  verify --run-id "${RUN_ID}"

SUCCESS=1
trap - EXIT
echo "validator_exit=0"
