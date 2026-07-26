#!/usr/bin/env bash
set -u

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

evidence_root="$(mktemp -d /tmp/capd-optimization.XXXXXX)"
log_root="$evidence_root/logs"
mkdir -p "$log_root"
failures=0

run_step() {
  local name="$1"
  shift
  local log="$log_root/$name.log"
  local started
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[START] $name $started"
  printf '[COMMAND]'
  printf ' %q' "$@"
  printf '\n'
  (
    echo "[START] $name $started"
    printf '[COMMAND]'
    printf ' %q' "$@"
    printf '\n'
    "$@"
    rc=$?
    ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[END] $name $ended exit_code=$rc log=$log"
    exit "$rc"
  ) >"$log" 2>&1
  rc=$?
  cat "$log"
  if [[ "$rc" -ne 0 ]]; then
    failures=$((failures + 1))
  fi
}

abort_if_failed() {
  local gate="$1"
  if [[ "$failures" -ne 0 ]]; then
    echo "[INFO] acceptance evidence: $evidence_root"
    echo "[FINAL] CAPD_OPTIMIZATION_PREHOLDOUT_NOT_COMPLETED gate=$gate failures=$failures"
    exit 1
  fi
}

run_step input_audit \
  python3 scripts/run_capd_optimization.py --stage audit-inputs
run_step targeted_pytest \
  python3 -m pytest -q -p no:cacheprovider \
  tests/test_capd_optimization_plan.py \
  tests/test_checkpoint_config_contract.py
run_step mini_e2e \
  env CAPD_OPTIMIZATION_E2E=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_capd_optimization_end_to_end.py::OptimizationTorchMiniEndToEndTest
run_step execution_plan \
  python3 scripts/run_capd_optimization.py --stage plan
abort_if_failed preflight

run_step o1_compute \
  python3 scripts/run_capd_optimization.py --stage o1 --execute
run_step o1_summarize \
  python3 scripts/run_capd_optimization.py --stage summarize-o1
abort_if_failed o1

run_step o2_compute \
  python3 scripts/run_capd_optimization.py --stage o2 --execute
run_step o2_summarize \
  python3 scripts/run_capd_optimization.py --stage summarize-o2
abort_if_failed o2

run_step o3_compute \
  python3 scripts/run_capd_optimization.py --stage o3 --execute
run_step o3_summarize \
  python3 scripts/run_capd_optimization.py --stage summarize-o3

run_step provenance_check python3 -c "
import json
o0=json.load(open(
    'outputs/results/capd_post_stage6_optimization/stage0_input_audit.json',
    encoding='utf-8'))
o1=json.load(open(
    'outputs/results/capd_post_stage6_optimization/o1/headroom_gate.json',
    encoding='utf-8'))
o2=json.load(open(
    'outputs/results/capd_post_stage6_optimization/o2/search_shortlist.json',
    encoding='utf-8'))
o3=json.load(open(
    'outputs/results/capd_post_stage6_optimization/o3/run_manifest.json',
    encoding='utf-8'))
assert o0['status']=='O0_READY_FOR_O1_O3'
assert o0['eligible_to_start_O1'] is True
assert o1['status']=='O1_COMPLETED'
assert o2['status']=='O2_COMPLETED'
assert o3['status']=='O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT'
for payload in (o0,o1,o2,o3):
    assert payload['test_used_for_selection'] is False
assert o3['method_contract_changed'] is False
assert o3['official_stage6_replaced'] is False
"

run_step upstream_immutability python3 -c "
import json
s6=json.load(open(
    'outputs/results/finals_v3_official/stage6/run_manifest.json',
    encoding='utf-8'))
bridge=json.load(open(
    'outputs/results/capd_bridge_diagnostic/run_manifest.json',
    encoding='utf-8'))
assert s6['status']=='STAGE6_VERIFIED'
assert s6['required_jobs']==s6['completed_required_jobs']==105
assert bridge['status']=='BRIDGE_DIAGNOSTIC_COMPLETED'
assert bridge['required_jobs']==bridge['completed_required_jobs']==33
"
run_step diff_check git diff --check

echo "[INFO] acceptance evidence: $evidence_root"
if [[ "$failures" -eq 0 ]]; then
  echo "[FINAL] O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT"
  exit 0
fi
echo "[FINAL] CAPD_OPTIMIZATION_PREHOLDOUT_NOT_COMPLETED failures=$failures"
exit 1
