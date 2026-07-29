#!/usr/bin/env bash
# CAPD proactive stage-0 contract validation. No replay or experiment is run.

REPO="${REPO:-$HOME/Q-former-for-OS}"
EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-proactive-stage0.XXXXXX")"
LOG_ROOT="$EVIDENCE_ROOT/logs"
mkdir -p "$LOG_ROOT" "$EVIDENCE_ROOT/pytest-cache" "$EVIDENCE_ROOT/pycache"
export PYTHONPYCACHEPREFIX="$EVIDENCE_ROOT/pycache"
export PYTEST_ADDOPTS="-o cache_dir=$EVIDENCE_ROOT/pytest-cache"

FAILURES=0

run_group() {
  name="$1"
  shift
  log="$LOG_ROOT/$name.log"
  printf '[START] %s %s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" |
    tee "$log"
  printf '[COMMAND] ' | tee -a "$log"
  printf '%q ' "$@" | tee -a "$log"
  printf '\n' | tee -a "$log"
  "$@" >>"$log" 2>&1
  rc=$?
  printf '[END] %s %s exit_code=%s log=%s\n' \
    "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rc" "$log" |
    tee -a "$log"
  if [ "$rc" -ne 0 ]; then
    FAILURES=$((FAILURES + 1))
  fi
  return "$rc"
}

if [ ! -d "$REPO" ]; then
  printf '[ERROR] repository not found: %s\n' "$REPO"
  printf '[FINAL] STAGE0_NOT_VERIFIED\n'
  exit 1
fi

cd "$REPO" || {
  printf '[ERROR] cannot enter repository: %s\n' "$REPO"
  printf '[FINAL] STAGE0_NOT_VERIFIED\n'
  exit 1
}

run_group targeted_contract_tests \
  python3 -m pytest -q \
  tests/test_capd_proactive_config.py \
  tests/test_checkpoint_config_contract.py
run_group template_load \
  python3 -c \
  "from qmap import finals_config as c; x=c.load_config('configs/finals/capd_proactive_stage0.json'); assert x['method']['name']=='capd_proactive'; assert x['method']['selector']=='disabled'; print(c.config_fingerprint(x))"
run_group diff_check git diff --check

if [ "$FAILURES" -eq 0 ]; then
  printf '[INFO] acceptance evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE0_VERIFIED\n'
  exit 0
fi

printf '[INFO] acceptance evidence: %s failures=%s\n' \
  "$EVIDENCE_ROOT" "$FAILURES"
printf '[FINAL] STAGE0_NOT_VERIFIED\n'
exit 1
