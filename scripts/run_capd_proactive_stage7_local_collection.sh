#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 RUN_ID [LOCAL_RUNTIME_ROOT]" >&2
  exit 2
fi

RUN_ID=$1
RUNTIME_ROOT=${2:-/home/hit/capd-tools}
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "${PROJECT_ROOT}"

export PYTHON_BIN=${PYTHON_BIN:-python3}
export STAGE7_DIRTY_WORKTREE=true
export STAGE7_RESUME=1
export DYNAMORIO_HOME="${RUNTIME_ROOT}/dynamorio/DynamoRIO-Linux-11.91.20581"
export PARSEC_ROOT="${RUNTIME_ROOT}/parsec-3.0"
export SWAPTIONS_BIN="${RUNTIME_ROOT}/swaptions-gcc-serial"

CANNEAL_INPUT="${RUNTIME_ROOT}/stage7-inputs/canneal/2500000.nets"
DEDUP_INPUT="${RUNTIME_ROOT}/stage7-inputs/dedup/FC-6-x86_64-disc1.iso"
BLACKSCHOLES_INPUT="${RUNTIME_ROOT}/stage7-inputs/blackscholes/in_10M.txt"
FLUIDANIMATE_INPUT="${RUNTIME_ROOT}/stage7-inputs/fluidanimate/in_500K.fluid"

export CANNEAL_INPUT DEDUP_INPUT BLACKSCHOLES_INPUT FLUIDANIMATE_INPUT

bash scripts/preflight_capd_proactive_stage7_collection.sh "${RUN_ID}"

CANNEAL_BIN="${PARSEC_ROOT}/pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"
STREAMCLUSTER_BIN="${PARSEC_ROOT}/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"
DEDUP_BIN="${PARSEC_ROOT}/pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"
BLACKSCHOLES_BIN="${PARSEC_ROOT}/pkgs/apps/blackscholes/inst/amd64-linux.gcc-serial/bin/blackscholes"
FLUIDANIMATE_BIN="${PARSEC_ROOT}/pkgs/apps/fluidanimate/inst/amd64-linux.gcc-pthreads/bin/fluidanimate"

echo "[LOCAL] collecting canneal"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" canneal seen_calibration_workload \
  "${CANNEAL_BIN}" native "${CANNEAL_INPUT}" -- \
  "${CANNEAL_BIN}" 1 15000 2000 "${CANNEAL_INPUT}" 6000

echo "[LOCAL] collecting streamcluster_pressure"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" streamcluster_pressure seen_calibration_workload \
  "${STREAMCLUSTER_BIN}" native_synthetic - -- \
  "${STREAMCLUSTER_BIN}" 10 20 128 1000000 200000 5000 none \
  "outputs/capd_proactive_stage7/collections/${RUN_ID}/streamcluster_pressure/streamcluster.out" 1

echo "[LOCAL] collecting dedup_pressure"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" dedup_pressure seen_calibration_workload \
  "${DEDUP_BIN}" native "${DEDUP_INPUT}" -- \
  "${DEDUP_BIN}" -c -p -v -t 1 -i "${DEDUP_INPUT}" \
  -o "outputs/capd_proactive_stage7/collections/${RUN_ID}/dedup_pressure/dedup.out.ddp"

echo "[LOCAL] collecting blackscholes"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" blackscholes held_out_unseen_workload \
  "${BLACKSCHOLES_BIN}" native "${BLACKSCHOLES_INPUT}" -- \
  "${BLACKSCHOLES_BIN}" 1 "${BLACKSCHOLES_INPUT}" \
  "outputs/capd_proactive_stage7/collections/${RUN_ID}/blackscholes/blackscholes.out"

echo "[LOCAL] collecting swaptions"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" swaptions held_out_unseen_workload \
  "${SWAPTIONS_BIN}" native_synthetic - -- \
  "${SWAPTIONS_BIN}" -ns 128 -sm 100000 -nt 1

echo "[LOCAL] collecting fluidanimate"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "${RUN_ID}" fluidanimate held_out_unseen_workload \
  "${FLUIDANIMATE_BIN}" native "${FLUIDANIMATE_INPUT}" -- \
  "${FLUIDANIMATE_BIN}" 1 5 "${FLUIDANIMATE_INPUT}" \
  "outputs/capd_proactive_stage7/collections/${RUN_ID}/fluidanimate/fluidanimate.out"

MANIFEST="outputs/capd_proactive_stage7/collections/${RUN_ID}/collection_manifest.json"
"${PYTHON_BIN}" -c \
  'import json,sys; value=json.load(open(sys.argv[1])); assert len(value["collections"]) == 6; print("[LOCAL] six collection records sealed")' \
  "${MANIFEST}"
echo "[LOCAL] collection_manifest=${MANIFEST}"
echo "[LOCAL] STAGE7_LOCAL_TRACE_COLLECTION_COMPLETE"
