#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Override PY/DEVICE if needed.
PY=${PY:-'python'}
DEVICE=${DEVICE:-'cuda'}
WORKLOADS=${WORKLOADS:-'streamcluster_pressure,blackscholes,canneal'}
SEEDS=${SEEDS:-'3136859,42,2026'}

# The script reuses existing JSONL by default, then trains/evaluates QMAP-Pool for each seed.
$PY scripts/run_seed_stability.py --workloads "$WORKLOADS" --seeds "$SEEDS" --skip_generate --run_torch --summarize --python "$PY" --device "$DEVICE"
