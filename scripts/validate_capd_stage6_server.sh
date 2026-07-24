#!/usr/bin/env bash
# CAPD stage-6 Linux acceptance entrypoint. Deliberately no global `set -e`.

REPO="${REPO:-$HOME/Q-former-for-OS}"
MODE="execute"
if [ "${1:-}" = "--plan" ] || [ "${1:-}" = "--dry-run" ]; then
  MODE="plan"
fi

EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage6.XXXXXX")"
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
  printf '[FINAL] STAGE6_NOT_VERIFIED\n'
  exit 1
fi

cd "$REPO" || {
  printf '[ERROR] cannot enter repository: %s\n' "$REPO"
  printf '[FINAL] STAGE6_NOT_VERIFIED\n'
  exit 1
}

run_group input_audit \
  python3 scripts/run_capd_stage6.py --stage audit-inputs
run_group targeted_pytest \
  python3 -m pytest -q \
  tests/test_capd_stage6_results.py \
  tests/test_capd_stage6_plan.py \
  tests/test_capd_stage6_end_to_end.py
run_group mini_e2e env CAPD_STAGE6_E2E=1 \
  python3 -m pytest -q \
  tests/test_capd_stage6_end_to_end.py::Stage6TorchMiniEndToEndTest
run_group full_pytest python3 -m pytest -q
run_group execution_plan \
  python3 scripts/run_capd_stage6.py --stage plan

if [ "$MODE" = "plan" ]; then
  printf '[INFO] plan-only evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE6_NOT_VERIFIED\n'
  exit "$FAILURES"
fi

run_group profile \
  python3 scripts/run_capd_stage6.py --stage profile --execute
run_group capacity \
  python3 scripts/run_capd_stage6.py --stage capacity --execute
run_group summarize \
  python3 scripts/run_capd_stage6.py --stage summarize
run_group provenance_check \
  python3 -c \
  "import json; p='outputs/results/finals_v3_official/stage6/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); assert d['status']=='STAGE6_IMPLEMENTED_UNVERIFIED'; assert d['required_jobs']==105; assert d['completed_required_jobs']==105; assert d['stage5_status']=='STAGE5_VERIFIED'; assert d['test_used_for_selection'] is False; assert d['method_contract_changed'] is False; assert d['server_gate_ready'] is True"
run_group diff_check git diff --check

if [ "$FAILURES" -eq 0 ]; then
  run_group finalize_verified \
    python3 -c \
    "import json,os,tempfile; p='outputs/results/finals_v3_official/stage6/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); d['status']='STAGE6_VERIFIED'; d['verified_by']='scripts/validate_capd_stage6_server.sh'; fd,t=tempfile.mkstemp(prefix='.stage6-',suffix='.json',dir=os.path.dirname(p)); f=os.fdopen(fd,'w',encoding='utf-8'); json.dump(d,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\\n'); f.close(); os.replace(t,p)"
fi

if [ "$FAILURES" -eq 0 ]; then
  printf '[INFO] acceptance evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE6_VERIFIED\n'
  exit 0
fi

printf '[INFO] acceptance evidence: %s failures=%s\n' \
  "$EVIDENCE_ROOT" "$FAILURES"
printf '[FINAL] STAGE6_NOT_VERIFIED\n'
exit 1
