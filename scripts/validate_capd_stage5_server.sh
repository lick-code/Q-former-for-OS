#!/usr/bin/env bash
# CAPD stage-5 Linux acceptance entrypoint. Deliberately no global `set -e`.

REPO="${REPO:-$HOME/Q-former-for-OS}"
MODE="execute"
if [ "${1:-}" = "--plan" ] || [ "${1:-}" = "--dry-run" ]; then
  MODE="plan"
fi

EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage5.XXXXXX")"
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
  printf '[FINAL] STAGE5_NOT_VERIFIED\n'
  exit 1
fi

cd "$REPO" || {
  printf '[ERROR] cannot enter repository: %s\n' "$REPO"
  printf '[FINAL] STAGE5_NOT_VERIFIED\n'
  exit 1
}

run_group input_audit \
  python3 scripts/run_capd_stage5.py --stage audit-inputs
run_group targeted_pytest \
  python3 -m pytest -q \
  tests/test_capd_stage5_variants.py \
  tests/test_capd_stage5_results.py \
  tests/test_capd_stage5_end_to_end.py
run_group full_pytest python3 -m pytest -q
run_group mini_e2e env CAPD_STAGE5_E2E=1 \
  python3 -m pytest -q \
  tests/test_capd_stage5_end_to_end.py::Stage5TorchMiniEndToEndTest
run_group execution_plan \
  python3 scripts/run_capd_stage5.py --stage plan

if [ "$MODE" = "plan" ]; then
  printf '[INFO] plan-only evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE5_NOT_VERIFIED\n'
  exit "$FAILURES"
fi

# Sequential stage execution is the safe default for a single GPU. Every job
# has an atomic manifest and exact dependency; rerunning resumes only complete,
# fingerprint-matching jobs and never retries a failed job automatically.
run_group required_main \
  python3 scripts/run_capd_stage5.py --stage main --execute
run_group learned_comparability \
  python3 scripts/run_capd_stage5.py --stage learned-baselines --execute
run_group core_ablations \
  python3 scripts/run_capd_stage5.py --stage ablations --execute
run_group sensitivity_grid \
  python3 scripts/run_capd_stage5.py --stage sensitivity --execute
run_group summarize \
  python3 scripts/run_capd_stage5.py --stage summarize
run_group provenance_check \
  python3 -c \
  "import json; p='outputs/results/finals_v3_official/stage5_main/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); assert d['status']=='STAGE5_IMPLEMENTED_UNVERIFIED'; assert d['server_gate_ready'] is True; assert d['required_jobs']==348; assert d['completed_required_jobs']==348; assert d['test_used_for_selection'] is False; assert d['historical_capd_comparison'] is False; assert d['stage6_entered'] is False"
run_group diff_check git diff --check

if [ "$FAILURES" -eq 0 ]; then
  run_group finalize_verified \
    python3 -c \
    "import json,os,tempfile; p='outputs/results/finals_v3_official/stage5_main/run_manifest.json'; d=json.load(open(p, encoding='utf-8')); d['status']='STAGE5_VERIFIED'; d['verified_by']='scripts/validate_capd_stage5_server.sh'; fd,t=tempfile.mkstemp(prefix='.stage5-', suffix='.json', dir=os.path.dirname(p)); f=os.fdopen(fd,'w',encoding='utf-8'); json.dump(d,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\\n'); f.close(); os.replace(t,p)"
fi

if [ "$FAILURES" -eq 0 ]; then
  printf '[INFO] acceptance evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE5_VERIFIED\n'
  exit 0
fi

printf '[INFO] acceptance evidence: %s failures=%s\n' \
  "$EVIDENCE_ROOT" "$FAILURES"
printf '[FINAL] STAGE5_NOT_VERIFIED\n'
exit 1
