#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG="${REPO_ROOT}/configs/finals/capd_proactive_stage2_cost_profiles.json"
FIXTURE="${REPO_ROOT}/tests/fixtures/capd_proactive_stage2_raw_events.json"
INVALID_FIXTURE="${REPO_ROOT}/tests/fixtures/capd_proactive_stage2_invalid_raw_events.json"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage2-XXXXXX")"

cleanup() {
  rm -rf -- "${TMP_DIR}"
}
trap cleanup EXIT

cd "${REPO_ROOT}"

echo "[stage2] validate frozen Cost profile configuration"
"${PYTHON_BIN}" scripts/recompute_proactive_cost.py \
  --config "${CONFIG}" \
  --validate-config

echo "[stage2] run stage-2 unit tests"
"${PYTHON_BIN}" -m unittest discover \
  -s tests \
  -p 'test_capd_proactive_cost.py' \
  -v

echo "[stage2] run frozen stage-1 Replay and stage-1 to stage-2 integration"
"${PYTHON_BIN}" -m unittest discover \
  -s tests \
  -p 'test_capd_proactive_replay.py' \
  -v
"${PYTHON_BIN}" -m unittest discover \
  -s tests \
  -p 'test_capd_stage1_stage2_integration.py' \
  -v

echo "[stage2] run stage-0 and historical Cost/accounting regressions"
"${PYTHON_BIN}" -m unittest discover \
  -s tests \
  -p 'test_capd_proactive_config.py' \
  -v
for pattern in \
    'test_cost_weight_sensitivity.py' \
    'test_cost_weight_robustness.py' \
    'test_dirty_accounting.py' \
    'test_capd_stage6_results.py' \
    'test_capd_stage1_v3_semantics.py'; do
  "${PYTHON_BIN}" -m unittest discover \
    -s tests \
    -p "${pattern}" \
    -v
done

before_hash="$("${PYTHON_BIN}" - "${FIXTURE}" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as input_file:
  print(hashlib.sha256(input_file.read()).hexdigest())
PY
)"

echo "[stage2] recompute default and all profiles from one synthetic record"
"${PYTHON_BIN}" scripts/recompute_proactive_cost.py \
  --config "${CONFIG}" \
  --input "${FIXTURE}" \
  --profile default \
  --output "${TMP_DIR}/default.json"
"${PYTHON_BIN}" scripts/recompute_proactive_cost.py \
  --config "${CONFIG}" \
  --input "${FIXTURE}" \
  --all-profiles \
  --output "${TMP_DIR}/all_profiles.json"

"${PYTHON_BIN}" - "${TMP_DIR}/default.json" "${TMP_DIR}/all_profiles.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as input_file:
  default = json.load(input_file)
with open(sys.argv[2], "r", encoding="utf-8") as input_file:
  all_profiles = json.load(input_file)

assert default["stage2_cost"]["default_weighted_cost"] == 190
results = all_profiles["stage2_cost"]["cost_results"]
assert set(results) == {
    "read_light", "default", "write_expensive", "migration_expensive"}
raw = all_profiles["stage2_cost"]["raw_counts"]
for name, result in results.items():
  assert result["raw_counts"] == raw, name
  assert sum(result["component_costs"].values()) == result["weighted_cost"], name
PY

after_hash="$("${PYTHON_BIN}" - "${FIXTURE}" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as input_file:
  print(hashlib.sha256(input_file.read()).hexdigest())
PY
)"
test "${before_hash}" = "${after_hash}"

echo "[stage2] verify invalid input fails"
if "${PYTHON_BIN}" scripts/recompute_proactive_cost.py \
    --config "${CONFIG}" \
    --input "${INVALID_FIXTURE}" \
    --output "${TMP_DIR}/must_not_exist.json"; then
  echo "ERROR: invalid raw event input unexpectedly succeeded" >&2
  exit 1
fi
test ! -e "${TMP_DIR}/must_not_exist.json"

echo "[stage2] repository whitespace validation"
git diff --check

echo "STAGE2_VERIFIED"
