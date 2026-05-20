#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Override PY if your conda path differs.
PY=${PY:-'/home/likc/.conda/envs/qmap/bin/python'}
DEVICE=${DEVICE:-'cuda'}

# Regenerate JSONL on the server, then run torch-dependent steps.
$PY scripts/run_real_ablation.py --force_generate
$PY scripts/run_real_ablation.py --skip_generate --run_torch --summarize --python "$PY" --device "$DEVICE"
