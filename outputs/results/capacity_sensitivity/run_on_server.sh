#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Override PY/DEVICE if needed.
PY=${PY:-'python3'}
DEVICE=${DEVICE:-'cuda'}
WORKLOADS=${WORKLOADS:-'streamcluster_pressure,canneal'}
CAPACITIES=${CAPACITIES:-'8,16,32'}

# Full pipeline: JSONL generation -> QMAP-Pool training -> policy eval -> final summary.
$PY scripts/run_capacity_sensitivity.py --run --summarize --workloads "$WORKLOADS" --capacities "$CAPACITIES" --python "$PY" --device "$DEVICE"
