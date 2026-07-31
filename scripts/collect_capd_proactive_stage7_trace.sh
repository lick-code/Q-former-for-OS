#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 7 ]]; then
  echo "usage: $0 RUN_ID WORKLOAD ROLE BINARY INPUT_NAME INPUT_PATH -- COMMAND..." >&2
  exit 2
fi

RUN_ID=$1
WORKLOAD=$2
ROLE=$3
BINARY=$4
INPUT_NAME=$5
INPUT_PATH=$6
shift 6
if [[ ${1:-} != "--" ]]; then
  echo "benchmark command must follow --" >&2
  exit 2
fi
shift
if [[ $# -eq 0 ]]; then
  echo "benchmark command is empty" >&2
  exit 2
fi
TARGET=("$@")

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "${PROJECT_ROOT}"

PYTHON_BIN=${PYTHON_BIN:-python3}
TOTAL_ACCESSES=${STAGE7_TOTAL_ACCESSES:-3000000}
TRAIN_END=${STAGE7_TRAIN_END:-1800000}
VALIDATION_END=${STAGE7_VALIDATION_END:-2400000}
TIMEOUT_SECONDS=${STAGE7_COLLECTION_TIMEOUT_SECONDS:-14400}
DYNAMORIO_HOME=${DYNAMORIO_HOME:-}

"${PYTHON_BIN}" -c \
  'import sys; from qmap.proactive_stage7_workloads import safe_run_id; safe_run_id(sys.argv[1])' \
  "${RUN_ID}"

if [[ "${TOTAL_ACCESSES}" -ne 3000000 ||
      "${TRAIN_END}" -ne 1800000 ||
      "${VALIDATION_END}" -ne 2400000 ]]; then
  echo "[FAILED] confirmed Stage-7 split is immutable: total=3000000 train_end=1800000 validation_end=2400000" >&2
  exit 1
fi

if [[ -z "${DYNAMORIO_HOME}" ]]; then
  echo "[FAILED] DYNAMORIO_HOME is not set" >&2
  exit 1
fi
DRRUN="${DYNAMORIO_HOME}/bin64/drrun"
if [[ ! -x "${DRRUN}" ]]; then
  echo "[FAILED] drrun is not executable: ${DRRUN}" >&2
  exit 1
fi
if [[ ! -x "${BINARY}" ]]; then
  echo "[FAILED] benchmark binary is not executable: ${BINARY}" >&2
  exit 1
fi
if [[ "${INPUT_PATH}" != "-" && ! -f "${INPUT_PATH}" ]]; then
  echo "[FAILED] benchmark input is missing: ${INPUT_PATH}" >&2
  exit 1
fi

"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  collection-preflight --workload "${WORKLOAD}"

COLLECTION_ROOT="outputs/capd_proactive_stage7/collections/${RUN_ID}/${WORKLOAD}"
RAW_ROOT="dataset/raw_traces/capd_proactive_stage7/${RUN_ID}"
RAW_TRACE="${RAW_ROOT}/${WORKLOAD}.csv"
WORK_DIR="${COLLECTION_ROOT}/drmemtrace"
VIEW_LOG="${COLLECTION_ROOT}/drmemtrace.view.log"
CONSOLE_LOG="${COLLECTION_ROOT}/collector_console.log"
MANIFEST="outputs/capd_proactive_stage7/collections/${RUN_ID}/collection_manifest.json"

if [[ -e "${RAW_TRACE}" || -e "${COLLECTION_ROOT}" ]]; then
  if [[ "${STAGE7_RESUME:-0}" != "1" ]]; then
    echo "[FAILED] collection target already exists; set STAGE7_RESUME=1 only for an exact completed receipt" >&2
    exit 1
  fi
  RESUME_ARGS=(
    --manifest "${MANIFEST}"
    --run-id "${RUN_ID}"
    --workload "${WORKLOAD}"
    --role "${ROLE}"
    --raw-trace "${RAW_TRACE}"
    --binary "${BINARY}"
    --input-path "${INPUT_PATH}"
    --total-accesses "${TOTAL_ACCESSES}"
    --train-end "${TRAIN_END}"
    --validation-end "${VALIDATION_END}"
  )
  "${PYTHON_BIN}" scripts/verify_capd_proactive_stage7_collection_receipt.py \
    "${RESUME_ARGS[@]}" -- "${TARGET[@]}"
  exit 0
fi
mkdir -p "${COLLECTION_ROOT}" "${RAW_ROOT}"

STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DRRUN_VERSION=$("${DRRUN}" -version 2>&1 | head -1)
printf -v TARGET_QUOTED '%q ' "${TARGET[@]}"
COLLECTOR_COMMAND="${PYTHON_BIN} scripts/collect_trace_drmemtrace.py --drrun $(printf '%q' "${DRRUN}") --output $(printf '%q' "${RAW_TRACE}") --work-dir $(printf '%q' "${WORK_DIR}") --view-log $(printf '%q' "${VIEW_LOG}") --max-records ${TOTAL_ACCESSES} --skip-records 0 --trace-ref-multiplier 100 --page-shift 12 --include-process-thread -- ${TARGET_QUOTED}"

set +e
timeout --signal=TERM "${TIMEOUT_SECONDS}" \
  "${PYTHON_BIN}" scripts/collect_trace_drmemtrace.py \
    --drrun "${DRRUN}" \
    --output "${RAW_TRACE}" \
    --work-dir "${WORK_DIR}" \
    --view-log "${VIEW_LOG}" \
    --max-records "${TOTAL_ACCESSES}" \
    --skip-records 0 \
    --trace-ref-multiplier 100 \
    --page-shift 12 \
    --include-process-thread \
    -- "${TARGET[@]}" 2>&1 | tee "${CONSOLE_LOG}"
COLLECT_EXIT=${PIPESTATUS[0]}
set -e
ENDED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [[ ${COLLECT_EXIT} -ne 0 ]]; then
  echo "[FAILED] collection exit=${COLLECT_EXIT}; evidence preserved at ${COLLECTION_ROOT}" >&2
  exit "${COLLECT_EXIT}"
fi

if grep -Eiq \
  '(lost[ _-]*(events|records)[^0-9]*[1-9]|dropped[ _-]*(events|records)?[^0-9]*[1-9])' \
  "${CONSOLE_LOG}" "${VIEW_LOG}"; then
  echo "[FAILED] drmemtrace reported lost/dropped events; evidence preserved at ${COLLECTION_ROOT}" >&2
  exit 1
fi

RECORD_ARGS=(
  --manifest "${MANIFEST}"
  --run-id "${RUN_ID}"
  --workload "${WORKLOAD}"
  --role "${ROLE}"
  --source-trace-id "${WORKLOAD}-${STARTED_AT//[:\-]/}"
  --raw-trace "${RAW_TRACE}"
  --binary "${BINARY}"
  --benchmark-version "PARSEC 3.0"
  --input-name "${INPUT_NAME}"
  --collector-version "${DRRUN_VERSION}"
  --collector-command "${COLLECTOR_COMMAND}"
  --collector-log "${CONSOLE_LOG}"
  --started-at "${STARTED_AT}"
  --ended-at "${ENDED_AT}"
  --exit-code 0
  --total-accesses "${TOTAL_ACCESSES}"
  --train-end "${TRAIN_END}"
  --validation-end "${VALIDATION_END}"
  --thread-parameter 1
)
if [[ "${INPUT_PATH}" != "-" ]]; then
  RECORD_ARGS+=(--input-path "${INPUT_PATH}")
fi
if [[ -n "${STAGE7_DIRTY_WORKTREE:-}" ]]; then
  RECORD_ARGS+=(--dirty-worktree "${STAGE7_DIRTY_WORKTREE}")
elif [[ "${RUN_ID}" == stage7-local-* ]]; then
  # Local collection creates very large untracked trace artifacts on the
  # Windows-mounted repository. Avoid a repository-wide git status scan.
  RECORD_ARGS+=(--dirty-worktree true)
fi

"${PYTHON_BIN}" scripts/record_capd_proactive_stage7_collection.py \
  "${RECORD_ARGS[@]}" -- "${TARGET[@]}"

echo "[OK] Stage-7 raw Trace sealed: ${RAW_TRACE}"
echo "[OK] Collection manifest: ${MANIFEST}"
