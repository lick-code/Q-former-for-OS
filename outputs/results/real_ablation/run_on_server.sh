#!/usr/bin/env bash
set -euo pipefail

PY=${PY:-/home/likc/.conda/envs/qmap/bin/python}
DEVICE=${DEVICE:-cuda}

"$PY" scripts/run_real_ablation.py --force_generate
"$PY" scripts/run_real_ablation.py \
  --skip_generate \
  --run_torch \
  --summarize \
  --python "$PY" \
  --device "$DEVICE"
