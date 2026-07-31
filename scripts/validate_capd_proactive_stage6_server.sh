#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 RUN_ID [DEVICE]" >&2
  exit 2
fi

RUN_ID="$1"
DEVICE="${2:-cpu}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
RUN_ROOT="outputs/capd_proactive_stage6/${RUN_ID}"
LOG_DIR="${RUN_ROOT}/logs"
TEST_LOG="${LOG_DIR}/stage1_stage6_regression.log"
CURRENT_STEP="bootstrap"
COMMON_ARGS=(
  --run-id "${RUN_ID}"
  --project-root "${PROJECT_ROOT}"
  --device "${DEVICE}"
)

record_failure() {
  local failure_step="$1"
  if [[ -d "${RUN_ROOT}" ]]; then
    "${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py \
      mark-not-verified "${COMMON_ARGS[@]}" \
      --failure-step "${failure_step}" >/dev/null 2>&1 || true
  fi
}

on_error() {
  local status="$?"
  trap - ERR
  record_failure "${CURRENT_STEP}"
  echo "[FAILED] Stage-6 validation stopped at ${CURRENT_STEP}; evidence preserved in ${RUN_ROOT}" >&2
  exit "${status}"
}
trap on_error ERR

CURRENT_STEP="environment_and_authority_files"
command -v "${PYTHON_BIN}" >/dev/null
command -v git >/dev/null
test "$(git branch --show-current)" = "main"
test -f configs/finals/capd_proactive_stage6_tpp.json
test -f configs/finals/capd_proactive_stage6_tpp_result_schema.json
test -f outputs/capd_proactive_stage5/stage5-baseline-r4/verification.json
test -f outputs/capd_proactive_stage5/stage5-baseline-r4/run_state.json
test -f outputs/capd_proactive_stage5/stage5-baseline-r4/fairness_audit.json
test -f outputs/capd_proactive_stage4/stage4-f8-f16-r3/verification.json

"${PYTHON_BIN}" - <<'PY'
import sys
print("python={}".format(sys.version.replace("\n", " ")))
try:
  import torch
except ImportError:
  print("torch=not_importable (TPP rule path does not require torch)")
else:
  print("torch={}".format(torch.__version__))
  print("cuda_available={}".format(torch.cuda.is_available()))
PY

CURRENT_STEP="python_compile"
"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_replay.py \
  qmap/proactive_cost.py \
  qmap/proactive_stage5_contract.py \
  qmap/proactive_stage5_policies.py \
  qmap/proactive_stage5_replay.py \
  qmap/proactive_stage6_contract.py \
  qmap/proactive_stage6_tpp.py \
  qmap/proactive_stage6_replay.py \
  scripts/run_capd_proactive_stage6.py

CURRENT_STEP="preflight"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py preflight \
  "${COMMON_ARGS[@]}"
mkdir -p "${LOG_DIR}"

CURRENT_STEP="stage5_r4_and_stage6_contract_audit"
"${PYTHON_BIN}" - <<'PY'
import os
from qmap import proactive_stage5_contract as s5
from qmap import proactive_stage5_policies as p5
from qmap import proactive_stage6_contract as s6

root = os.getcwd()
config = s6.load_config("configs/finals/capd_proactive_stage6_tpp.json")
entry = s6.audit_stage5_entry(config, root)
assert entry["status"] == s5.VERIFIED
assert entry["stage6_entry_gate"] == "satisfied"
assert entry["tpp_inspired_status"] == s5.PENDING_TPP
try:
  s5.assert_runnable_policy("tpp_inspired")
except s5.PendingStage6Error:
  pass
else:
  raise AssertionError("Stage-5 TPP unexpectedly became runnable")
try:
  p5.build_ranker("tpp_inspired").rank_candidates(None, [], [], {})
except s5.PendingStage6Error:
  pass
else:
  raise AssertionError("Stage-5 pending ranker did not reject")
assert len(s6.parameter_grid()) == 12
assert len({row["experiment_id"] for row in s6.parameter_grid()}) == 12
for forbidden in (
    "outputs/results/finals_v3_official/stage5_main/result.json",
    "outputs/results/finals_v3_official/stage6_tpp/result.json",
    "dataset/test.csv",
):
  try:
    s6.audit_no_contamination([forbidden])
  except (s5.Stage5ContractError, s6.Stage6ContractError):
    pass
  else:
    raise AssertionError("contaminated path was not rejected: " + forbidden)
print("stage5_r4_and_stage6_contract_audit=passed")
PY

CURRENT_STEP="stage1_stage6_regression"
set +e
"${PYTHON_BIN}" -m unittest -v \
  tests.test_capd_proactive_config \
  tests.test_capd_proactive_replay \
  tests.test_capd_proactive_cost \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  tests.test_capd_proactive_stage5_contract \
  tests.test_capd_proactive_stage5_replay \
  tests.test_capd_proactive_stage5_e2e \
  tests.test_capd_proactive_stage6_tpp \
  tests.test_capd_proactive_stage6_e2e \
  2>&1 | tee "${TEST_LOG}"
PIPE_STATUSES=("${PIPESTATUS[@]}")
TEST_STATUS="${PIPE_STATUSES[0]}"
TEE_STATUS="${PIPE_STATUSES[1]}"
set -e
if [[ "${TEST_STATUS}" -ne 0 || "${TEE_STATUS}" -ne 0 ]]; then
  record_failure "${CURRENT_STEP}"
  echo "Stage 1-6 regression failed; inspect ${TEST_LOG}" >&2
  if [[ "${TEST_STATUS}" -ne 0 ]]; then
    exit "${TEST_STATUS}"
  fi
  exit "${TEE_STATUS}"
fi

CURRENT_STEP="record_regression_receipt"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py record-tests \
  "${COMMON_ARGS[@]}" \
  --test-log "${TEST_LOG}" \
  --test-exit-code "${TEST_STATUS}"

CURRENT_STEP="synthetic_e2e"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py synthetic \
  "${COMMON_ARGS[@]}"

CURRENT_STEP="full_validation_grid_12_configs"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py run-grid \
  "${COMMON_ARGS[@]}"

CURRENT_STEP="global_parameter_selection"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py select \
  "${COMMON_ARGS[@]}"

CURRENT_STEP="selected_full_validation_confirmation"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py confirm \
  "${COMMON_ARGS[@]}"

CURRENT_STEP="experiment_A_fairness"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py fairness \
  "${COMMON_ARGS[@]}"

CURRENT_STEP="final_verification"
"${PYTHON_BIN}" scripts/run_capd_proactive_stage6.py verify \
  "${COMMON_ARGS[@]}"
