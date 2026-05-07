#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 用法:
#   bash scripts/run_qmap_eval.bash [GPU_ID] [TRACE_PATH] [CHECKPOINT]
# 示例:
#   bash scripts/run_qmap_eval.bash 2 environment/test_memtrace_with_rw.csv qmap_checkpoints/qmap_epoch_10.pth
GPU_ID="${1:-2}"
TRACE_PATH="${2:-${PROJECT_ROOT}/environment/test_memtrace_with_rw.csv}"
CHECKPOINT="${3:-${PROJECT_ROOT}/qmap_checkpoints/qmap_epoch_10.pth}"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"

if [[ ! -f "${TRACE_PATH}" ]]; then
  echo "[error] trace not found: ${TRACE_PATH}"
  echo "用法: bash $0 [GPU_ID] [TRACE_PATH] [CHECKPOINT]"
  exit 1
fi

if [[ ! -f "${CHECKPOINT}" ]]; then
  echo "[error] checkpoint not found: ${CHECKPOINT}"
  echo "用法: bash $0 [GPU_ID] [TRACE_PATH] [CHECKPOINT]"
  exit 1
fi

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qmap_eval_${RUN_TS}.log"

# source /home/tingkun/lkc/StageI/venv/bin/activate

echo "[info] gpu=${GPU_ID}"
echo "[info] trace_path=${TRACE_PATH}"
echo "[info] checkpoint=${CHECKPOINT}"
echo "[info] log_file=${LOG_FILE}"

CUDA_VISIBLE_DEVICES="${GPU_ID}" python qmap/qmap_eval.py \
  --trace_path "${TRACE_PATH}" \
  --policy qmap \
  --checkpoint "${CHECKPOINT}" \
  --device cuda \
  2>&1 | tee "${LOG_FILE}"
