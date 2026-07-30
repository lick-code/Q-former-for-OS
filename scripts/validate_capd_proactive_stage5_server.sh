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
RUN_ROOT="outputs/capd_proactive_stage5/${RUN_ID}"
LOG_DIR="${RUN_ROOT}/logs"
TEST_LOG="${LOG_DIR}/stage1_stage5_regression.log"

command -v "${PYTHON_BIN}" >/dev/null
command -v git >/dev/null
test "$(git branch --show-current)" = "main"
test -f configs/finals/capd_proactive_stage0.json
test -f configs/finals/capd_proactive_stage2_cost_profiles.json
test -f configs/finals/capd_proactive_stage3_engineering_default.json
test -f configs/finals/capd_proactive_stage4.json
test -f configs/finals/capd_proactive_stage5.json
test -f configs/finals/capd_proactive_stage5_result_schema.json
test -f outputs/capd_proactive_stage4/stage4-f8-f16-r3/verification.json
test -f outputs/capd_proactive_stage4/stage4-f8-f16-r3/final_freeze_candidate.json

"${PYTHON_BIN}" - <<'PY'
import sys
import torch
print("python={}".format(sys.version.replace("\n", " ")))
print("torch={}".format(torch.__version__))
print("cuda_available={}".format(torch.cuda.is_available()))
PY

if [[ "${DEVICE}" == cuda* ]]; then
  "${PYTHON_BIN}" - "${DEVICE}" <<'PY'
import sys
import torch
if not torch.cuda.is_available():
  raise SystemExit("CUDA device requested but unavailable")
device = sys.argv[1]
index = torch.device(device).index or 0
print("cuda_device={}".format(torch.cuda.get_device_name(index)))
PY
fi

"${PYTHON_BIN}" -m py_compile \
  qmap/proactive_replay.py \
  qmap/proactive_cost.py \
  qmap/proactive_stage5_contract.py \
  qmap/proactive_stage5_policies.py \
  qmap/proactive_stage5_replay.py \
  scripts/run_capd_proactive_stage5.py

COMMON_ARGS=(
  --run-id "${RUN_ID}"
  --project-root "${PROJECT_ROOT}"
  --device "${DEVICE}"
)

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py preflight \
  "${COMMON_ARGS[@]}"

mkdir -p "${LOG_DIR}"

"${PYTHON_BIN}" - <<'PY'
import json
import os
from qmap import proactive_stage5_contract as c

root = os.getcwd()
config = c.load_config("configs/finals/capd_proactive_stage5.json")
authority = c.audit_stage4_authority(config, root, require_checkpoints=True)
assert [row["seed"] for row in authority["checkpoints"]] == [3136859, 42, 2026]
assert authority["selector_status"] == "disabled"
assert authority["test_trace_opened"] is False
assert authority["old_finals_v3_artifacts_used"] is False
assert config["frozen_method"]["dram_working_set_ratio"] == 0.2
assert config["frozen_method"]["capacity_claim"] == (
    "conditional_engineering_default_not_capacity_rule_v2_pass")
assert config["policies"]["tpp_inspired"]["implementation_status"] == (
    "pending_stage6")
assert config["policies"]["tpp_inspired"]["fallback_allowed"] is False
try:
  c.audit_no_legacy_stage_artifacts([
      "outputs/results/finals_v3_official/stage5_main/run_manifest.json"])
except c.Stage5ContractError:
  pass
else:
  raise AssertionError("historical Stage-5 artifact was not rejected")
print("stage4_chain_and_contamination_audit=passed")
PY

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
  2>&1 | tee "${TEST_LOG}"
TEST_STATUS="${PIPESTATUS[0]}"
set -e
if [[ "${TEST_STATUS}" -ne 0 ]]; then
  echo "Stage 1-5 regression failed; inspect ${TEST_LOG}" >&2
  exit "${TEST_STATUS}"
fi

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py synthetic \
  "${COMMON_ARGS[@]}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py run-acceptance \
  "${COMMON_ARGS[@]}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py fairness \
  "${COMMON_ARGS[@]}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py record-tests \
  "${COMMON_ARGS[@]}" \
  --test-log "${TEST_LOG}"

"${PYTHON_BIN}" scripts/run_capd_proactive_stage5.py verify \
  "${COMMON_ARGS[@]}"
