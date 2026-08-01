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
# If the server cpuset does not allow CPU 0, edit only the config ONCE before a
# new run. This script reads the configured CPU and uses it for every taskset.
export OMP_NUM_THREADS="1"
export MKL_NUM_THREADS="1"
export PYTHONHASHSEED="0"

cd "${PROJECT_ROOT}"

# Keep the shell binding exactly aligned with the predeclared JSON config.
# This read happens before a run directory is created.
CPU_AFFINITY="$("${PYTHON_BIN}" -c '
import json
with open("configs/finals/capd_proactive_stage9.json", "r", encoding="utf-8") as handle:
  value = json.load(handle)["measurement"]["cpu_affinity"]
if len(value) != 1 or not isinstance(value[0], int) or value[0] < 0:
  raise SystemExit("Stage-9 requires one non-negative CPU affinity entry")
print(value[0])
')"

if ! taskset -c "${CPU_AFFINITY}" /bin/true; then
  echo "[PRE-RUN FAILED] CPU ${CPU_AFFINITY} is outside this process cpuset; no Stage-9 run was started." >&2
  grep Cpus_allowed_list /proc/self/status >&2 || true
  exit 3
fi

# Pre-run environment probe: do this before creating/burning RUN_ID and before
# the expensive 54-cell Replay. A numeric paranoid value alone is not enough;
# capabilities may still allow perf, so the hardware events are exercised.
command -v perf >/dev/null || {
  echo "[PRE-RUN FAILED] Linux perf is not installed; no Stage-9 run was started." >&2
  exit 3
}
PERF_HELP="$(perf stat -h 2>&1 || true)"
if ! grep -q -- '--control' <<<"${PERF_HELP}"; then
  echo "[PRE-RUN FAILED] This perf build lacks stat --control FIFO support; no Stage-9 run was started." >&2
  exit 3
fi
PERF_PROBE_RAW="$(mktemp)"
PERF_PROBE_ERR="$(mktemp)"
if ! perf stat -x ';' -e cycles,instructions,task-clock \
  -o "${PERF_PROBE_RAW}" -- taskset -c "${CPU_AFFINITY}" /bin/true \
  2>"${PERF_PROBE_ERR}" || \
  grep -Eq '<not supported>|<not counted>' "${PERF_PROBE_RAW}"; then
  echo "[PRE-RUN FAILED] Hardware perf counters are unavailable; no Stage-9 run was started." >&2
  cat "${PERF_PROBE_ERR}" >&2
  cat "${PERF_PROBE_RAW}" >&2
  if [[ -r /proc/sys/kernel/perf_event_paranoid ]]; then
    echo "kernel.perf_event_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid)" >&2
  fi
  echo "Ask the administrator to authorize hardware counters, e.g.:" >&2
  echo "  sudo sysctl -w kernel.perf_event_paranoid=0" >&2
  echo "Then rerun this command. Do not estimate cycles from wall time." >&2
  rm -f "${PERF_PROBE_RAW}" "${PERF_PROBE_ERR}"
  exit 3
fi
rm -f "${PERF_PROBE_RAW}" "${PERF_PROBE_ERR}"
echo "[OK] pre-run perf hardware counter and FIFO-control capability probe passed"

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
echo "CPU_AFFINITY=${CPU_AFFINITY}"

CURRENT_STEP="preflight"
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
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
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
  record-tests --test-log "${TEST_LOG}"

CURRENT_STEP="latency_quality_memory"
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
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
  -- taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    perf-workload --perf-control-fifo "${CONTROL_FIFO}" \
    --perf-ack-fifo "${ACK_FIFO}" \
  2> "${PERF_DIR}/perf-stderr.log"

CURRENT_STEP="parse_perf"
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" parse-perf

CURRENT_STEP="independent_verification"
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" verify

trap - ERR
