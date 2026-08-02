#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$PWD}"
RUN_ID="${CAPD_STAGE4_STAGE7_RUN_ID:-stage4-stage7-unified-r1}"
CONFIG="${CAPD_STAGE4_STAGE7_CONFIG:-configs/finals/capd_proactive_stage4_stage7_search.json}"
FREEZE="${CAPD_STAGE4_STAGE7_FREEZE:-outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json}"
MANIFEST="${CAPD_STAGE4_STAGE7_MANIFEST:-outputs/capd_proactive_stage4_stage7/${RUN_ID}/input_manifest.json}"
DEVICE="${CAPD_STAGE4_STAGE7_DEVICE:-cuda}"
TRAIN_WORKERS="${CAPD_STAGE4_STAGE7_TRAIN_WORKERS:-4}"
SAMPLE_WORKERS="${CAPD_STAGE4_STAGE7_SAMPLE_WORKERS:-6}"
REPLAY_WORKERS="${CAPD_STAGE4_STAGE7_REPLAY_WORKERS:-6}"

cd "$PROJECT_ROOT"

python3 -m py_compile \
  qmap/proactive_stage4_stage7.py \
  scripts/prepare_capd_proactive_stage4_stage7_manifest.py \
  scripts/run_capd_proactive_stage4_stage7.py

python3 -m unittest \
  tests.test_capd_proactive_stage4_stage7 \
  tests.test_capd_proactive_stage4_stage7_e2e \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  -v

python3 scripts/run_capd_proactive_stage4_stage7.py preflight \
  --config "$CONFIG" \
  --stage3-freeze "$FREEZE" \
  --input-manifest "$MANIFEST" \
  --run-id "$RUN_ID" \
  --project-root "$PROJECT_ROOT" \
  --device "$DEVICE" \
  --require-cuda \
  --train-workers "$TRAIN_WORKERS" \
  --sample-workers "$SAMPLE_WORKERS" \
  --replay-workers "$REPLAY_WORKERS"

echo "[FINAL] STAGE4_STAGE7_LOCAL_CODE_AND_PREFLIGHT_VERIFIED"
echo "[GATE] Full search and formal freeze were not started."
