#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Override PY/DEVICE if needed.
PY=${PY:-'/home/likc/.conda/envs/qmap/bin/python'}
DEVICE=${DEVICE:-'cuda'}
WORKLOADS=${WORKLOADS:-'streamcluster_pressure,canneal'}
CANDIDATES=${CANDIDATES:-'4,8,16'}

# Runs the complete JSONL -> train -> eval pipeline and writes the final summary.
$PY scripts/run_candidate_sensitivity.py --workloads "$WORKLOADS" --candidate_counts "$CANDIDATES" --run --summarize --python "$PY" --device "$DEVICE"
