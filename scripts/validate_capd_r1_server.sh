#!/usr/bin/env bash
set -u

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

evidence_root="$(mktemp -d /tmp/capd-r1.XXXXXX)"
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
    echo "[FINAL] R1_NOT_COMPLETED gate=$gate failures=$failures"
    exit 1
  fi
}

run_step input_audit \
  python3 scripts/run_capd_r1.py --stage audit-inputs
run_step targeted_pytest \
  python3 -m pytest -q -p no:cacheprovider \
  tests/test_capd_r1_plan.py \
  tests/test_capd_r1_results.py
run_step mini_e2e \
  env CAPD_R1_E2E=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_capd_r1_end_to_end.py::R1MiniEndToEndTest
run_step full_pytest \
  python3 -m pytest -q -p no:cacheprovider
run_step execution_plan \
  python3 scripts/run_capd_r1.py --stage plan
abort_if_failed preflight

run_step r1_compute \
  python3 scripts/run_capd_r1.py --stage run --execute
run_step r1_summarize \
  python3 scripts/run_capd_r1.py --stage summarize
abort_if_failed compute

run_step provenance_check python3 -c "
import json
p='outputs/results/capd_r1_pressure_headroom/run_manifest.json'
d=json.load(open(p, encoding='utf-8'))
assert d['status']=='R1_IMPLEMENTED_UNVERIFIED'
assert d['required_jobs']==d['completed_required_jobs']==45
assert d['job_counts']=={
    'data':9,'oracle':9,'opportunity':9,'baseline':18}
assert d['result_row_count']==9
assert d['training_jobs']==0
assert d['stage6_status']=='STAGE6_VERIFIED'
assert d['bridge_status']=='BRIDGE_DIAGNOSTIC_COMPLETED'
assert d['o3_status']=='O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT'
assert d['method_selection_performed'] is False
assert d['bridge_test_used_for_selection'] is False
assert d['test_trace_opened'] is False
assert d['test_used_for_selection'] is False
assert d['method_contract_changed'] is False
assert d['official_stage6_replaced'] is False
"

run_step upstream_immutability python3 -c "
import json
s6=json.load(open(
    'outputs/results/finals_v3_official/stage6/run_manifest.json',
    encoding='utf-8'))
bridge=json.load(open(
    'outputs/results/capd_bridge_diagnostic/run_manifest.json',
    encoding='utf-8'))
o3=json.load(open(
    'outputs/results/capd_post_stage6_optimization/o3/run_manifest.json',
    encoding='utf-8'))
assert s6['status']=='STAGE6_VERIFIED'
assert s6['required_jobs']==s6['completed_required_jobs']==105
assert bridge['status']=='BRIDGE_DIAGNOSTIC_COMPLETED'
assert bridge['required_jobs']==bridge['completed_required_jobs']==33
assert o3['status']=='O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT'
"

run_step diff_check git diff --check
abort_if_failed acceptance

run_step finalize_verified python3 -c "
import json,os,tempfile
p='outputs/results/capd_r1_pressure_headroom/run_manifest.json'
d=json.load(open(p, encoding='utf-8'))
d['status']='R1_PRESSURE_HEADROOM_VERIFIED'
d['verified_by']='scripts/validate_capd_r1_server.sh'
fd,t=tempfile.mkstemp(prefix='.r1-',suffix='.json',dir=os.path.dirname(p))
f=os.fdopen(fd,'w',encoding='utf-8')
json.dump(d,f,ensure_ascii=False,indent=2,sort_keys=True)
f.write('\n')
f.close()
os.replace(t,p)
"

echo "[INFO] acceptance evidence: $evidence_root"
if [[ "$failures" -eq 0 ]]; then
  echo "[FINAL] R1_PRESSURE_HEADROOM_VERIFIED"
  exit 0
fi
echo "[FINAL] R1_NOT_COMPLETED failures=$failures"
exit 1
