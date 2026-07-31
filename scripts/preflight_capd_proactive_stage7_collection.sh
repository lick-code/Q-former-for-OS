#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "${PROJECT_ROOT}"
PYTHON_BIN=${PYTHON_BIN:-python3}
DYNAMORIO_HOME=${DYNAMORIO_HOME:-}
PARSEC_ROOT=${PARSEC_ROOT:-/root/qmap-work/parsec-3.0}

"${PYTHON_BIN}" scripts/prepare_capd_proactive_stage7_manifest.py \
  preflight --run-id "${1:-stage7-impl-r1}"

if [[ -z "${DYNAMORIO_HOME}" || ! -x "${DYNAMORIO_HOME}/bin64/drrun" ]]; then
  echo "[MISSING] set DYNAMORIO_HOME to a DynamoRIO installation" >&2
  exit 1
fi

declare -A BINARIES=(
  [canneal]="${PARSEC_ROOT}/pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"
  [streamcluster_pressure]="${PARSEC_ROOT}/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"
  [dedup_pressure]="${PARSEC_ROOT}/pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"
  [blackscholes]="${PARSEC_ROOT}/pkgs/apps/blackscholes/inst/amd64-linux.gcc-serial/bin/blackscholes"
  [swaptions]="${SWAPTIONS_BIN:-${PARSEC_ROOT}/pkgs/apps/swaptions/inst/amd64-linux.gcc-pthreads/bin/swaptions}"
  [fluidanimate]="${PARSEC_ROOT}/pkgs/apps/fluidanimate/inst/amd64-linux.gcc-pthreads/bin/fluidanimate"
)

for workload in "${!BINARIES[@]}"; do
  binary=${BINARIES[${workload}]}
  if [[ ! -x "${binary}" ]]; then
    echo "[MISSING] ${workload} binary: ${binary}" >&2
    exit 1
  fi
  echo "[OK] ${workload} binary $(sha256sum "${binary}" | awk '{print $1}')"
done

for variable in CANNEAL_INPUT DEDUP_INPUT BLACKSCHOLES_INPUT FLUIDANIMATE_INPUT; do
  value=${!variable:-}
  if [[ -z "${value}" || ! -f "${value}" ]]; then
    echo "[MISSING] export ${variable}=<existing input path>" >&2
    exit 1
  fi
  echo "[OK] ${variable} $(sha256sum "${value}" | awk '{print $1}')"
done

"${DYNAMORIO_HOME}/bin64/drrun" -version 2>&1 | head -1
"${PYTHON_BIN}" -m py_compile \
  scripts/collect_trace_drmemtrace.py \
  scripts/convert_drmemtrace_view.py \
  scripts/record_capd_proactive_stage7_collection.py

echo "[OK] Stage-7 collection environment preflight"
echo "[OK] suite_confirmation.confirmed=true; formal collection is enabled"
