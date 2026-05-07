#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 用法:
#   bash scripts/run_qmap_generate.bash [GPU_ID] [INPUT_TRACE] [OUTPUT_JSONL]
# 示例:
#   bash scripts/run_qmap_generate.bash 2 environment/test_memtrace_with_rw.csv train_data.jsonl
GPU_ID="${1:-2}"
INPUT_TRACE="${2:-${PROJECT_ROOT}/environment/test_memtrace_with_rw.csv}"
OUTPUT_JSONL="${3:-${PROJECT_ROOT}/train_data.jsonl}"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"

if [[ ! -f "${INPUT_TRACE}" ]]; then
  echo "[error] input trace not found: ${INPUT_TRACE}"
  echo "用法: bash $0 [GPU_ID] [INPUT_TRACE] [OUTPUT_JSONL]"
  exit 1
fi

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qmap_generate_${RUN_TS}.log"

# source /home/tingkun/lkc/StageI/venv/bin/activate

echo "[info] gpu=${GPU_ID}"
echo "[info] input_trace=${INPUT_TRACE}"
echo "[info] output_jsonl=${OUTPUT_JSONL}"
echo "[info] log_file=${LOG_FILE}"

CUDA_VISIBLE_DEVICES="${GPU_ID}" python qmap/qmap_generator.py \
  --input "${INPUT_TRACE}" \
  --output "${OUTPUT_JSONL}" \
  2>&1 | tee "${LOG_FILE}"
