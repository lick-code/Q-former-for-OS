#!/usr/bin/env bash
# CAPD stage-4 Linux validation. Intentionally avoids global `set -e`.

REPO="${REPO:-$HOME/Q-former-for-OS}"
EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage4.XXXXXX")"
LOG_ROOT="$EVIDENCE_ROOT/logs"
PYTEST_ROOT="$EVIDENCE_ROOT/pytest"
PYCACHE_ROOT="$EVIDENCE_ROOT/pycache"
mkdir -p "$LOG_ROOT" "$PYTEST_ROOT" "$PYCACHE_ROOT"
export PYTHONPYCACHEPREFIX="$PYCACHE_ROOT"
export PYTEST_ADDOPTS="-o cache_dir=$PYTEST_ROOT/cache"
export CAPD_STAGE4_LOG_ROOT="$LOG_ROOT/training"

FAILURES=0
LAST_CODE=0
run_group() {
  name="$1"
  timeout_value="$2"
  shift 2
  log="$LOG_ROOT/${name}.log"
  printf '[START] %s %s\n' "$name" "$(date -Is)" | tee "$log"
  timeout "$timeout_value" "$@" >>"$log" 2>&1
  code=$?
  LAST_CODE=$code
  printf '[END] %s %s exit=%s log=%s\n' \
    "$name" "$(date -Is)" "$code" "$log" | tee -a "$log"
  if [ "$code" -ne 0 ]; then
    FAILURES=$((FAILURES + 1))
  fi
  return 0
}

run_required() {
  run_group "$@"
  if [ "$LAST_CODE" -ne 0 ]; then
    failed_log="$LOG_ROOT/$1.log"
    printf '[ERROR] %s failed; last 80 log lines follow: %s\n' \
      "$1" "$failed_log"
    tail -n 80 "$failed_log" || true
    printf '[EVIDENCE] %s\n' "$EVIDENCE_ROOT"
    printf '[FINAL] STAGE4_NOT_VERIFIED\n'
    exit 1
  fi
}

cd "$REPO" || {
  printf '[FINAL] STAGE4_NOT_VERIFIED\n'
  exit 2
}

run_required input_audit 10m python3 scripts/run_capd_stage4.py \
  --stage audit-inputs --repo-root "$REPO"
run_required targeted_tests 20m python3 -m pytest -q \
  tests/test_capd_stage4_counterfactual.py \
  tests/test_capd_stage4_distribution.py \
  tests/test_capd_stage4_training.py
run_required full_pytest 60m python3 -m pytest -q
run_required mini_e2e 60m env CAPD_STAGE4_E2E=1 python3 -m pytest -q \
  tests/test_capd_stage4_end_to_end.py
run_required generate 60m python3 scripts/run_capd_stage4.py \
  --stage generate --repo-root "$REPO"
run_required train_9 18h python3 scripts/run_capd_stage4.py \
  --stage train --repo-root "$REPO" --log-root "$CAPD_STAGE4_LOG_ROOT" \
  --training-timeout 21600
run_required counterfactual_g12 6h python3 scripts/run_capd_stage4.py \
  --stage counterfactual-audit --repo-root "$REPO"
run_required distribution_g11 6h python3 scripts/run_capd_stage4.py \
  --stage distribution-audit --repo-root "$REPO"
run_required summarize 20m python3 scripts/run_capd_stage4.py \
  --stage summarize --repo-root "$REPO"
run_required pollution_check 10m python3 -c \
  'import os; bad=[]
for root in ("dataset/jsonl/finals_v3_official", "outputs/results/finals_v3_official"):
  for path, _, files in os.walk(root):
    for name in files:
      full=os.path.join(path,name).replace(os.sep,"/")
      if "stage4" not in full and ("stage4_audit" in name or "stage4_reranker" in name): bad.append(full)
raise SystemExit("pollution: "+str(bad) if bad else 0)'
run_required diff_check 10m git diff --check

printf '[EVIDENCE] %s\n' "$EVIDENCE_ROOT"
if [ "$FAILURES" -eq 0 ]; then
  printf '[FINAL] STAGE4_VERIFIED\n'
  exit 0
fi
printf '[FINAL] STAGE4_NOT_VERIFIED\n'
exit 1
