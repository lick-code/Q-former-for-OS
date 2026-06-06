#!/usr/bin/env bash
set -euo pipefail

PY=${PY:-'/home/likc/.conda/envs/qmap/bin/python'}
WORKLOADS=${WORKLOADS:-'blackscholes,canneal,streamcluster_pressure,dedup_pressure'}
POLICIES=${POLICIES:-'kleio_lite,patterns_lite'}

$PY scripts/run_learned_baselines.py \
  --workloads "$WORKLOADS" \
  --policies "$POLICIES" \
  --run \
  --summarize \
  --include_rule_baselines \
  --python "$PY"
