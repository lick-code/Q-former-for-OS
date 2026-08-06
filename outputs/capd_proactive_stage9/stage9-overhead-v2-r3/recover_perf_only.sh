#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${RUN_ROOT}/../../.." && pwd)"
RUN_ID="$(basename "${RUN_ROOT}")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PERF_DIR="${RUN_ROOT}/perf"
CONTROL_FIFO="${PERF_DIR}/control.recovery.fifo"
ACK_FIFO="${PERF_DIR}/ack.recovery.fifo"
DRIVER="${RUN_ROOT}/perf_recovery_driver.py"
RECEIPT="${RUN_ROOT}/perf_recovery_receipt.json"
ORIGINAL_STATE="${RUN_ROOT}/run_state.perf_failure.original.json"
FAILED_PERF_DIR="${PERF_DIR}/failed-attempt-nul-ack"

if [[ "${RUN_ID}" != "stage9-overhead-v2-r3" ]]; then
  echo "[RECOVERY FAILED] This recovery is locked to stage9-overhead-v2-r3." >&2
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
if len(value) != 1 or not isinstance(value[0], int) or value[0] < 0:
  raise SystemExit("Stage-9 requires one non-negative CPU affinity entry")
print(value[0])
')"

taskset -c "${CPU_AFFINITY}" /bin/true
command -v perf >/dev/null
PERF_PROBE_RAW="$(mktemp)"
PERF_PROBE_ERR="$(mktemp)"
if ! perf stat -x ';' -e cycles,instructions,task-clock \
  -o "${PERF_PROBE_RAW}" -- taskset -c "${CPU_AFFINITY}" /bin/true \
  2>"${PERF_PROBE_ERR}" || \
  grep -Eq '<not supported>|<not counted>' "${PERF_PROBE_RAW}"; then
  cat "${PERF_PROBE_ERR}" >&2
  cat "${PERF_PROBE_RAW}" >&2
  rm -f "${PERF_PROBE_RAW}" "${PERF_PROBE_ERR}"
  echo "[RECOVERY FAILED] Hardware perf counters are unavailable; r3 was not changed." >&2
  exit 3
fi
rm -f "${PERF_PROBE_RAW}" "${PERF_PROBE_ERR}"

# Audit the frozen r3 identity and completed expensive measurement before
# authorizing the narrow failed-perf recovery.
RUN_ROOT="${RUN_ROOT}" PROJECT_ROOT="${PROJECT_ROOT}" DRIVER="${DRIVER}" \
RECOVERY_SCRIPT="${BASH_SOURCE[0]}" "${PYTHON_BIN}" - <<'PY'
import importlib.util
import os
import shutil

from qmap import proactive_stage9 as stage9

run_root = os.environ["RUN_ROOT"]
project_root = os.environ["PROJECT_ROOT"]
runner_path = os.path.join(project_root, "scripts", "run_capd_proactive_stage9.py")
spec = importlib.util.spec_from_file_location("stage9_recovery_audit", runner_path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

config_path = os.path.join(project_root, "configs", "finals", "capd_proactive_stage9.json")
config = stage9.load_json(config_path)
stage9.validate_config(config)
identity_path = os.path.join(run_root, "run_identity.json")
identity = stage9.load_json(identity_path)
for relative, expected in identity["code_artifacts"].items():
  actual = stage9.fingerprint_file(os.path.join(project_root, relative))
  if actual != expected:
    raise stage9.Stage9ContractError(
        "Frozen r3 code changed before recovery: {}".format(relative))
bound_files = {
    "config_sha256": config_path,
    "result_schema_sha256": os.path.join(project_root, config["result_schema"]),
    "stage0_sha256": os.path.join(
        project_root, "configs", "finals", "capd_proactive_stage0.json"),
    "cost_config_sha256": os.path.join(
        project_root, "configs", "finals",
        "capd_proactive_stage2_cost_profiles.json"),
}
for identity_key, path in bound_files.items():
  if stage9.fingerprint_file(path) != identity[identity_key]:
    raise stage9.Stage9ContractError(
        "Frozen r3 input changed before recovery: {}".format(identity_key))
actual_git = runner._git_state(project_root)

state_path = os.path.join(run_root, "run_state.json")
state = stage9.load_json(state_path)
original_state = os.path.join(run_root, "run_state.perf_failure.original.json")
authorization_state = (stage9.load_json(original_state)
                       if os.path.isfile(original_state) else state)
failure = authorization_state.get("failure", {})
current_failure = state.get("failure", {})
if (state.get("status") != stage9.NOT_VERIFIED or
    current_failure.get("step") != "perf_hardware_counters" or
    authorization_state.get("status") != stage9.NOT_VERIFIED or
    failure.get("step") != "perf_hardware_counters" or
    "\\x00ack" not in repr(failure.get("perf_failure_evidence", {}).get(
        "perf-stderr.log", ""))):
  raise stage9.Stage9ContractError(
      "r3 is not the expected NUL-prefixed perf ACK failure.")

entry = runner._audit_stage8_entry(config, project_root)
jobs = runner._measurement_jobs(config, entry)
raw_path = os.path.join(run_root, "raw_latency_samples.csv")
checkpoint_path = os.path.join(run_root, "measurement_checkpoint.json")
runner._verify_measurement_checkpoint(checkpoint_path, raw_path, config, jobs)

if not os.path.exists(original_state):
  shutil.copy2(state_path, original_state)
receipt = {
    "schema_version": "capd_proactive_stage9_perf_recovery_v1_0",
    "run_id": "stage9-overhead-v2-r3",
    "status": "authorized",
    "reason": "perf_fifo_ack_was_nul_prefixed",
    "scope": "reuse_completed_latency_quality_memory_and_rerun_perf_only",
    "original_run_state_sha256": stage9.fingerprint_file(original_state),
    "run_identity_sha256": stage9.fingerprint_file(identity_path),
    "recorded_git_identity": identity["git"],
    "recovery_time_git_identity": actual_git,
    "git_worktree_change_tolerated_only_after_all_bound_sha_checks": True,
    "measurement_checkpoint_sha256": stage9.fingerprint_file(checkpoint_path),
    "raw_latency_samples_sha256": stage9.fingerprint_file(raw_path),
    "raw_latency_samples_bytes": os.path.getsize(raw_path),
    "recovery_driver_sha256": stage9.fingerprint_file(os.environ["DRIVER"]),
    "recovery_script_sha256": stage9.fingerprint_file(os.environ["RECOVERY_SCRIPT"]),
    "semantic_change": "strip_leading_nul_bytes_from_perf_fifo_ack_only",
    "expensive_measurement_rerun": False,
}
stage9.write_json_atomic(os.path.join(run_root, "perf_recovery_receipt.json"), receipt)
stage9.write_run_state(run_root, stage9.RUNNING, state["completed"])
PY

mkdir -p "${FAILED_PERF_DIR}"
for name in perf-stat.raw perf-stderr.log; do
  if [[ -f "${PERF_DIR}/${name}" && ! -f "${FAILED_PERF_DIR}/${name}" ]]; then
    cp -p "${PERF_DIR}/${name}" "${FAILED_PERF_DIR}/${name}"
  fi
done

recovery_failed() {
  local exit_code=$?
  trap - ERR
  set +e
  "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    mark-not-verified --failure-step "perf_hardware_counters" \
    --failure-reason "perf_recovery_exit_${exit_code}"
  echo "[RECOVERY FAILED] r3 remains not verified; evidence stayed in ${RUN_ROOT}." >&2
  exit "${exit_code}"
}
trap recovery_failed ERR

rm -f "${CONTROL_FIFO}" "${ACK_FIFO}"
mkfifo "${CONTROL_FIFO}" "${ACK_FIFO}"
perf stat \
  --delay=-1 \
  --control="fifo:${CONTROL_FIFO},${ACK_FIFO}" \
  -x ';' \
  -e cycles,instructions,task-clock,context-switches,cpu-migrations,page-faults \
  -o "${PERF_DIR}/perf-stat.raw" \
  -- taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" "${DRIVER}" \
    --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" \
    perf-workload --perf-control-fifo "${CONTROL_FIFO}" \
    --perf-ack-fifo "${ACK_FIFO}" \
  2> "${PERF_DIR}/perf-stderr.log"

taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" parse-perf
taskset -c "${CPU_AFFINITY}" "${PYTHON_BIN}" scripts/run_capd_proactive_stage9.py \
  --project-root "${PROJECT_ROOT}" --run-id "${RUN_ID}" verify

trap - ERR
RUN_ROOT="${RUN_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
from qmap import proactive_stage9 as stage9

root = os.environ["RUN_ROOT"]
receipt_path = os.path.join(root, "perf_recovery_receipt.json")
receipt = stage9.load_json(receipt_path)
receipt["status"] = "recovered_and_verified"
stage9.write_json_atomic(receipt_path, receipt)
binding = {
    "schema_version": "capd_proactive_stage9_perf_recovery_binding_v1_0",
    "run_id": "stage9-overhead-v2-r3",
    "perf_recovery_receipt_sha256": stage9.fingerprint_file(receipt_path),
    "verification_sha256": stage9.fingerprint_file(
        os.path.join(root, "verification.json")),
    "recovered_perf_raw_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf-stat.raw")),
    "recovered_perf_scope_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf_scope_counts.json")),
    "recovered_perf_parsed_sha256": stage9.fingerprint_file(
        os.path.join(root, "perf", "perf_parsed.json")),
}
stage9.write_json_atomic(
    os.path.join(root, "perf_recovery_binding.json"), binding)
PY

echo "[FINAL] STAGE9_R3_PERF_RECOVERY_VERIFIED"
