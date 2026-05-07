#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 用法:
#   bash scripts/run_qmap_train.bash [GPU_ID] [TRAIN_DATA] [OUTPUT_DIR]
# 示例:
#   bash scripts/run_qmap_train.bash 2 train_data.jsonl qmap_checkpoints
GPU_ID="${1:-2}"
TRAIN_DATA="${2:-${PROJECT_ROOT}/train_data.jsonl}"
OUTPUT_DIR="${3:-${PROJECT_ROOT}/qmap_checkpoints}"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${OUTPUT_DIR}" "${LOG_DIR}"

if [[ ! -f "${TRAIN_DATA}" ]]; then
  echo "[error] training data not found: ${TRAIN_DATA}"
  echo "用法: bash $0 [GPU_ID] [TRAIN_DATA] [OUTPUT_DIR]"
  exit 1
fi

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qmap_train_${RUN_TS}.log"

# source /home/tingkun/lkc/StageI/venv/bin/activate

echo "[info] gpu=${GPU_ID}"
echo "[info] train_data=${TRAIN_DATA}"
echo "[info] output_dir=${OUTPUT_DIR}"
echo "[info] log_file=${LOG_FILE}"

CUDA_VISIBLE_DEVICES="${GPU_ID}" python qmap/qmap_train.py \
  --train_data "${TRAIN_DATA}" \
  --output_dir "${OUTPUT_DIR}" \
  --epochs 10 \
  --batch_size 32 \
  --lr 1e-4 \
  --device cuda \
  2>&1 | tee "${LOG_FILE}"
