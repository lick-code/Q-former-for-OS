#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 RUN_ID SOURCE_TRAIN_VALID_MANIFEST [DEVICE]" >&2
  exit 2
fi

RUN_ID="$1"
SOURCE_MANIFEST="$2"
DEVICE="${3:-cpu}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_BASE="outputs/capd_proactive_stage4"
MANIFEST_DIR="${OUTPUT_BASE}/manifests"
RUN_ROOT="${OUTPUT_BASE}/${RUN_ID}"
LOG_DIR="${RUN_ROOT}/logs"
STAGE4_MANIFEST="${MANIFEST_DIR}/${RUN_ID}.json"
TEST_LOG="${LOG_DIR}/server_tests.log"
mkdir -p "${MANIFEST_DIR}" "${LOG_DIR}"

command -v "${PYTHON_BIN}" >/dev/null
command -v git >/dev/null
test -f "${SOURCE_MANIFEST}"
test -f configs/finals/capd_proactive_stage0.json
test -f configs/finals/capd_proactive_stage3_engineering_default.json
test -f configs/finals/capd_proactive_stage4.json

"${PYTHON_BIN}" - <<'PY'
import sys
import torch
print("python={}".format(sys.version.replace("\n", " ")))
print("torch={}".format(torch.__version__))
print("cuda_available={}".format(torch.cuda.is_available()))
PY

if [[ "${DEVICE}" == cuda* ]]; then
  "${PYTHON_BIN}" - <<'PY'
import torch
if not torch.cuda.is_available():
  raise SystemExit("CUDA device requested but torch.cuda.is_available() is false")
print("cuda_device={}".format(torch.cuda.get_device_name(0)))
PY
fi

PREPARE_ARGS=(
  --source-manifest "${SOURCE_MANIFEST}"
  --output "${STAGE4_MANIFEST}"
  --project-root "${PROJECT_ROOT}"
)
if [[ -n "${CAPD_STAGE4_SOURCE_RANGES_JSON:-}" ]]; then
  PREPARE_ARGS+=(--source-ranges-json "${CAPD_STAGE4_SOURCE_RANGES_JSON}")
elif [[ "${CAPD_STAGE4_ATTEST_DISTINCT_SOURCE_TRACES:-0}" == "1" ]]; then
  PREPARE_ARGS+=(--attest-distinct-source-traces)
else
  echo "Refusing to invent Train/Validation non-overlap evidence." >&2
  echo "Set CAPD_STAGE4_SOURCE_RANGES_JSON to audited half-open source ranges," >&2
  echo "or set CAPD_STAGE4_ATTEST_DISTINCT_SOURCE_TRACES=1 only when the six files are genuinely distinct captures." >&2
  exit 2
fi

"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage4_manifest.py \
  "${PREPARE_ARGS[@]}"

COMMON_ARGS=(
  --manifest "${STAGE4_MANIFEST}"
  --run-id "${RUN_ID}"
  --project-root "${PROJECT_ROOT}"
  --device "${DEVICE}"
)

"${PYTHON_BIN}" scripts/run_capd_proactive_stage4.py preflight \
  "${COMMON_ARGS[@]}"

"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_stage4.py \
  qmap/proactive_replay.py \
  qmap/proactive_stage3.py \
  qmap/qmap_train.py \
  qmap/qmap_eval.py \
  scripts/prepare_capd_proactive_stage4_manifest.py \
  scripts/run_capd_proactive_stage4.py

set +e
"${PYTHON_BIN}" -m unittest -v \
  tests.test_capd_proactive_config \
  tests.test_capd_proactive_replay \
  tests.test_capd_proactive_cost \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  2>&1 | tee "${TEST_LOG}"
TEST_STATUS="${PIPESTATUS[0]}"
set -e
if [[ "${TEST_STATUS}" -ne 0 ]]; then
  echo "Stage 1-4 regression tests failed; inspect ${TEST_LOG}" >&2
  exit "${TEST_STATUS}"
fi

"${PYTHON_BIN}" scripts/run_capd_proactive_stage4.py all \
  "${COMMON_ARGS[@]}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage4.py record-tests \
  "${COMMON_ARGS[@]}" \
  --test-log "${TEST_LOG}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage4.py verify \
  "${COMMON_ARGS[@]}"
