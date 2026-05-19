#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Usage:
#   bash scripts/run_qmap_generate.bash [GPU_ID] [INPUT_TRACE] [OUTPUT_JSONL]
# Example:
#   bash scripts/run_qmap_generate.bash 0 dataset/processed/try_train.csv dataset/jsonl/try_train.jsonl
GPU_ID="${1:-0}"
INPUT_TRACE="${2:-${PROJECT_ROOT}/dataset/processed/try_train.csv}"
OUTPUT_JSONL="${3:-${PROJECT_ROOT}/dataset/jsonl/try_train.jsonl}"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}" "$(dirname "${OUTPUT_JSONL}")"

if [[ ! -f "${INPUT_TRACE}" ]]; then
  echo "[error] input trace not found: ${INPUT_TRACE}"
  echo "Usage: bash $0 [GPU_ID] [INPUT_TRACE] [OUTPUT_JSONL]"
  exit 1
fi

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qmap_generate_${RUN_TS}.log"

echo "[info] gpu=${GPU_ID}"
echo "[info] input_trace=${INPUT_TRACE}"
echo "[info] output_jsonl=${OUTPUT_JSONL}"
echo "[info] log_file=${LOG_FILE}"

CUDA_VISIBLE_DEVICES="${GPU_ID}" python qmap/qmap_generator.py \
  --input "${INPUT_TRACE}" \
  --output "${OUTPUT_JSONL}" \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --dram_capacity 128 \
  --page_shift 12 \
  --ablation mean_pool \
  2>&1 | tee "${LOG_FILE}"
