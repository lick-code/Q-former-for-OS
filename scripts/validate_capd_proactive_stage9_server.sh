#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 1 ]]; then
  echo "usage: $0 RUN_ID" >&2
  exit 2
fi

RUN_ID="$1"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ROOT="${PROJECT_ROOT}/outputs/capd_proactive_stage9/${RUN_ID}"
TEST_LOG="${RUN_ROOT}/logs/stage1_stage9_regression.log"
PERF_DIR="${RUN_ROOT}/perf"
CONTROL_FIFO="${PERF_DIR}/control.fifo"
ACK_FIFO="${PERF_DIR}/ack.fifo"
CURRENT_STEP="bootstrap"

# These values are frozen in configs/finals/capd_proactive_stage9.json.
# If the server cpuset does not allow CPU 0, edit the config ONCE before a new
# run, record the new config SHA through preflight, and keep it unchanged.
export OMP_NUM_THREADS="1"
export MKL_NUM_THREADS="1"
export PYTHONHASHSEED="0"

cd "${PROJECT_ROOT}"

preserve_failure() {
  local exit_code=$?
  trap - ERR
  set +e
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    mark-not-verified --failure-step "${CURRENT_STEP}" \
    --failure-reason "server_validation_exit_${exit_code}"
  echo "[FAILED] Stage-9 stopped at ${CURRENT_STEP}; use a NEW run ID. Evidence: ${RUN_ROOT}" >&2
  exit "${exit_code}"
}
trap preserve_failure ERR

echo "python=$(${PYTHON_BIN} -c 'import sys; print(sys.version)')"
echo "kernel=$(uname -srvo)"
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"
echo "MKL_NUM_THREADS=${MKL_NUM_THREADS}"
echo "PYTHONHASHSEED=${PYTHONHASHSEED}"

CURRENT_STEP="preflight"
taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" preflight

CURRENT_STEP="static_compile"
"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_stage9.py \
  scripts/run_capd_proactive_stage9.py

CURRENT_STEP="stage1_stage9_regression"
mkdir -p "$(dirname "${TEST_LOG}")"
"${PYTHON_BIN}" -m unittest discover -s tests -p 'test*.py' -v \
  2>&1 | tee "${TEST_LOG}"

CURRENT_STEP="record_regression_receipt"
taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
  record-tests --test-log "${TEST_LOG}"

CURRENT_STEP="latency_quality_memory"
taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" measure

CURRENT_STEP="perf_hardware_counters"
command -v perf >/dev/null
mkdir -p "${PERF_DIR}"
rm -f "${CONTROL_FIFO}" "${ACK_FIFO}"
mkfifo "${CONTROL_FIFO}" "${ACK_FIFO}"
perf stat \
  --delay=-1 \
  --control="fifo:${CONTROL_FIFO},${ACK_FIFO}" \
  -x ';' \
  -e cycles,instructions,task-clock,context-switches,cpu-migrations,page-faults \
  -o "${PERF_DIR}/perf-stat.raw" \
  -- taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    perf-workload --perf-control-fifo "${CONTROL_FIFO}" \
    --perf-ack-fifo "${ACK_FIFO}" \
  2> "${PERF_DIR}/perf-stderr.log"

CURRENT_STEP="parse_perf"
taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" parse-perf

CURRENT_STEP="independent_verification"
taskset -c 0 "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" verify

trap - ERR
