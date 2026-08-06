#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${RUN_ROOT}/../../.." && pwd)"
RUN_ID="$(basename "${RUN_ROOT}")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DRIVER="${RUN_ROOT}/perf_recovery_driver.py"

if [[ "${RUN_ID}" != "stage9-overhead-v2-r3" ]]; then
  echo "[VERIFY RECOVERY FAILED] This command is locked to stage9-overhead-v2-r3." >&2
  exit 2
fi

export OMP_NUM_THREADS="1"
export MKL_NUM_THREADS="1"
export PYTHONHASHSEED="0"
cd "${PROJECT_ROOT}"

CPU_AFFINITY="$("${PYTHON_BIN}" -c '
import json
with open("configs/finals/capd_proactive_stage9.json", "r", encoding="utf-8") as handle:
  value = json.load(handle)["measurement"]["cpu_affinity"]
print(value[0])
')"
taskset -c "${CPU_AFFINITY}" /bin/true

# All expensive and perf evidence already exists. The driver performs the
# corrected checkpoint/identity/receipt checks during verify; only the audited
# failed state is reopened here.
RUN_ROOT="${RUN_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
from qmap import proactive_stage9 as stage9

root = os.environ["RUN_ROOT"]
state_path = os.path.join(root, "run_state.json")
state = stage9.load_json(state_path)
if (state.get("status") != stage9.NOT_VERIFIED or
    state.get("failure", {}).get("reason") != "perf_recovery_exit_1" or
    "perf_cycles" not in state.get("completed", [])):
  raise stage9.Stage9ContractError(
      "r3 is not the expected post-perf verification failure state.")
for relative in (
    "perf/perf-stat.raw", "perf/perf-stderr.log",
    "perf/perf_scope_counts.json", "perf/perf_parsed.json",
    "server_test_receipt.json", "logs/stage1_stage9_regression.log"):
  if not os.path.isfile(os.path.join(root, relative)):
    raise stage9.Stage9ContractError(
        "verify-only recovery is missing {}".format(relative))
stage9.write_json_atomic(os.path.join(root, "verify_only_recovery_receipt.json"), {
    "schema_version": "capd_proactive_stage9_verify_only_recovery_v1_0",
    "run_id": "stage9-overhead-v2-r3",
    "status": "authorized",
    "scope": "reuse_completed_measurement_and_perf_then_verify_only",
    "verification_compatibility": [
        "unittest_OK_summary_may_precede_buffered_test_stdout",
        "quality_JSON_roundtrip_float_tolerance_1e-12"
    ],
    "perf_raw_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf-stat.raw")),
    "perf_scope_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf_scope_counts.json")),
    "perf_parsed_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf_parsed.json")),
    "server_test_receipt_sha256": stage9.fingerprint_file(
        os.path.join(root, "server_test_receipt.json")),
    "regression_log_sha256": stage9.fingerprint_file(
        os.path.join(root, "logs", "stage1_stage9_regression.log")),
})
stage9.write_run_state(root, stage9.RUNNING, state["completed"])
PY

verify_failed() {
  local exit_code=$?
  trap - ERR
  set +e
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    mark-not-verified --failure-step "independent_verification" \
    --failure-reason "verify_only_recovery_exit_${exit_code}"
  echo "[VERIFY RECOVERY FAILED] r3 remains not verified; no measurement or perf reran." >&2
  exit "${exit_code}"
}
trap verify_failed ERR

taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" "${DRIVER}" \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" verify

trap - ERR
RUN_ROOT="${RUN_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
from qmap import proactive_stage9 as stage9

root = os.environ["RUN_ROOT"]
receipt_path = os.path.join(root, "verify_only_recovery_receipt.json")
receipt = stage9.load_json(receipt_path)
receipt["status"] = "verified"
receipt["verification_sha256"] = stage9.fingerprint_file(
    os.path.join(root, "verification.json"))
stage9.write_json_atomic(receipt_path, receipt)
PY

echo "[FINAL] STAGE9_R3_VERIFY_ONLY_RECOVERY_VERIFIED"
