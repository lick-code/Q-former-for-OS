#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root.
# Override if the server uses a different environment:
#   PY=/path/to/python DEVICE=cuda bash scripts/run_real_ablation_on_server.sh
PY=${PY:-/home/likc/.conda/envs/qmap/bin/python}
DEVICE=${DEVICE:-cuda}

"$PY" scripts/run_real_ablation.py --force_generate
"$PY" scripts/run_real_ablation.py \
  --skip_generate \
  --run_torch \
  --summarize \
  --python "$PY" \
  --device "$DEVICE"
