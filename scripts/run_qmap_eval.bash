#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Usage:
#   bash scripts/run_qmap_eval.bash [GPU_ID] [TRACE_PATH] [CHECKPOINT]
# Example:
#   bash scripts/run_qmap_eval.bash 0 dataset/processed/try_test.csv outputs/checkpoints/try/qmap_epoch_10.pth
GPU_ID="${1:-0}"
TRACE_PATH="${2:-${PROJECT_ROOT}/dataset/processed/try_test.csv}"
CHECKPOINT="${3:-${PROJECT_ROOT}/outputs/checkpoints/try/qmap_epoch_10.pth}"
LOG_DIR="${PROJECT_ROOT}/logs"
RESULT_DIR="${PROJECT_ROOT}/outputs/results/manual_eval"
mkdir -p "${LOG_DIR}" "${RESULT_DIR}"

if [[ ! -f "${TRACE_PATH}" ]]; then
  echo "[error] trace not found: ${TRACE_PATH}"
  echo "Usage: bash $0 [GPU_ID] [TRACE_PATH] [CHECKPOINT]"
  exit 1
fi

if [[ ! -f "${CHECKPOINT}" ]]; then
  echo "[error] checkpoint not found: ${CHECKPOINT}"
  echo "Usage: bash $0 [GPU_ID] [TRACE_PATH] [CHECKPOINT]"
  exit 1
fi

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qmap_eval_${RUN_TS}.log"

echo "[info] gpu=${GPU_ID}"
echo "[info] trace_path=${TRACE_PATH}"
echo "[info] checkpoint=${CHECKPOINT}"
echo "[info] log_file=${LOG_FILE}"

CUDA_VISIBLE_DEVICES="${GPU_ID}" python qmap/qmap_eval.py \
  --trace_path "${TRACE_PATH}" \
  --policy qmap \
  --checkpoint "${CHECKPOINT}" \
  --device cuda \
  --page_shift 12 \
  --json_output "${RESULT_DIR}/qmap_${RUN_TS}.json" \
  2>&1 | tee "${LOG_FILE}"
