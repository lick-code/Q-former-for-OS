#!/usr/bin/env bash
# CAPD bridge diagnostic Linux entrypoint. Deliberately no global `set -e`.

REPO="${REPO:-$HOME/Q-former-for-OS}"
MODE="execute"
if [ "${1:-}" = "--plan" ] || [ "${1:-}" = "--dry-run" ]; then
  MODE="plan"
fi

EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-bridge.XXXXXX")"
LOG_ROOT="$EVIDENCE_ROOT/logs"
mkdir -p "$LOG_ROOT" "$EVIDENCE_ROOT/pytest-cache" "$EVIDENCE_ROOT/pycache"
export PYTHONPYCACHEPREFIX="$EVIDENCE_ROOT/pycache"
export PYTEST_ADDOPTS="-o cache_dir=$EVIDENCE_ROOT/pytest-cache"

FAILURES=0

run_group() {
  name="$1"
  shift
  log="$LOG_ROOT/$name.log"
  printf '[START] %s %s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee "$log"
  printf '[COMMAND] ' | tee -a "$log"
  printf '%q ' "$@" | tee -a "$log"
  printf '\n' | tee -a "$log"
  "$@" >>"$log" 2>&1
  rc=$?
  printf '[END] %s %s exit_code=%s log=%s\n' \
    "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rc" "$log" | tee -a "$log"
  if [ "$rc" -ne 0 ]; then
    FAILURES=$((FAILURES + 1))
  fi
  return "$rc"
}

if [ ! -d "$REPO" ]; then
  printf '[ERROR] repository not found: %s\n' "$REPO"
  printf '[FINAL] BRIDGE_DIAGNOSTIC_NOT_COMPLETED\n'
  exit 1
fi

cd "$REPO" || {
  printf '[ERROR] cannot enter repository: %s\n' "$REPO"
  printf '[FINAL] BRIDGE_DIAGNOSTIC_NOT_COMPLETED\n'
  exit 1
}

run_group input_audit \
  python3 scripts/run_capd_bridge.py --stage audit-inputs
run_group targeted_pytest \
  python3 -m pytest -q \
  tests/test_capd_bridge_plan.py \
  tests/test_capd_bridge_results.py \
  tests/test_capd_bridge_end_to_end.py
run_group mini_e2e env CAPD_BRIDGE_E2E=1 \
  python3 -m pytest -q \
  tests/test_capd_bridge_end_to_end.py::BridgeTorchMiniEndToEndTest
run_group full_pytest python3 -m pytest -q
run_group execution_plan \
  python3 scripts/run_capd_bridge.py --stage plan

if [ "$MODE" = "plan" ]; then
  printf '[INFO] plan-only evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] BRIDGE_DIAGNOSTIC_NOT_COMPLETED\n'
  exit "$FAILURES"
fi

run_group bridge_compute \
  python3 scripts/run_capd_bridge.py --stage run --execute
run_group summarize \
  python3 scripts/run_capd_bridge.py --stage summarize
run_group provenance_check \
  python3 -c \
  "import json; p='outputs/results/capd_bridge_diagnostic/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); assert d['status']=='BRIDGE_DIAGNOSTIC_COMPLETED'; assert d['required_jobs']==33; assert d['completed_required_jobs']==33; assert d['stage6_status']=='STAGE6_VERIFIED'; assert d['official_stage6_replaced'] is False; assert d['method_contract_changed'] is False; assert d['test_used_for_selection'] is False"
run_group stage6_immutability \
  python3 -c \
  "import json; p='outputs/results/finals_v3_official/stage6/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); assert d['status']=='STAGE6_VERIFIED'; assert d['required_jobs']==105; assert d['completed_required_jobs']==105"
run_group diff_check git diff --check

if [ "$FAILURES" -eq 0 ]; then
  printf '[INFO] acceptance evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] BRIDGE_DIAGNOSTIC_COMPLETED\n'
  exit 0
fi

printf '[INFO] acceptance evidence: %s failures=%s\n' \
  "$EVIDENCE_ROOT" "$FAILURES"
printf '[FINAL] BRIDGE_DIAGNOSTIC_NOT_COMPLETED\n'
exit 1

