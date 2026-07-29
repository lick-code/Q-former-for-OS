#!/usr/bin/env bash
# CAPD proactive stage-1 validation. Runs only synthetic Replay fixtures.

REPO="${REPO:-$HOME/Q-former-for-OS}"
EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capd-proactive-stage1.XXXXXX")"
LOG_ROOT="$EVIDENCE_ROOT/logs"
OUTPUT_ROOT="$EVIDENCE_ROOT/fixture-output"
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
  printf '[FINAL] STAGE1_NOT_VERIFIED\n'
  exit 1
fi

cd "$REPO" || {
  printf '[ERROR] cannot enter repository: %s\n' "$REPO"
  printf '[FINAL] STAGE1_NOT_VERIFIED\n'
  exit 1
}

run_group targeted_contract_and_replay_tests \
  python3 -m pytest -q \
  tests/test_capd_proactive_config.py \
  tests/test_checkpoint_config_contract.py \
  tests/test_capd_proactive_replay.py

run_group stage1_fixture_replay \
  python3 -m qmap.proactive_replay \
  --config configs/finals/capd_proactive_stage0.json \
  --fixture configs/finals/capd_proactive_stage1_fixture.json \
  --output-root "$OUTPUT_ROOT"

run_group stage1_output_contract \
  python3 -c \
  "import glob,json,os; runs=glob.glob(os.path.join('$OUTPUT_ROOT','stage1','*')); assert len(runs)==1, runs; r=runs[0]; required=['resolved_config.json','provenance.json','artifacts','logs']; assert all(os.path.exists(os.path.join(r,x)) for x in required); summaries=glob.glob(os.path.join(r,'logs','*_summary.json')); assert len(summaries)>=2; rows=[json.load(open(p,encoding='utf-8')) for p in summaries]; assert all(x['weighted_cost'] is None and x['weighted_cost_status']=='pending_stage2' for x in rows); assert all(x['selector_status']=='disabled' and x['checkpoint_status']=='not_required_stage1' for x in rows); print(r)"

run_group syntax_check \
  python3 -m py_compile \
  qmap/proactive_replay.py \
  tests/test_capd_proactive_replay.py

run_group diff_check git diff --check

if [ "$FAILURES" -eq 0 ]; then
  printf '[INFO] acceptance evidence: %s\n' "$EVIDENCE_ROOT"
  printf '[FINAL] STAGE1_VERIFIED\n'
  exit 0
fi

printf '[INFO] acceptance evidence: %s failures=%s\n' \
  "$EVIDENCE_ROOT" "$FAILURES"
printf '[FINAL] STAGE1_NOT_VERIFIED\n'
exit 1
