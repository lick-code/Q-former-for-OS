# CAPD Stage 7 Refit And Pressure Evaluation Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the six genuine Stage 7 raw traces, refit one global CAPD model from all six Train/Validation pairs with the already selected model settings, and rerun Stage 8 with separately reported Standard Test and traceable Pressure Test results.

**Architecture:** Keep every existing Stage 4/7/8 artifact immutable and create a repair namespace with new run IDs. A repair preparer audits raw SHA identities, builds a six-workload Train/Validation manifest, derives policy-independent contiguous Pressure Test windows, and freezes a versioned Stage 8 plan that points to newly trained checkpoints. Standard and Pressure results remain separate; Pressure results are forbidden from supporting memory, CPU, inference-time, or end-to-end latency claims.

**Execution boundary:** Raw-trace audit, capacity analysis, Pressure-window scanning, derived Pressure CSV creation, and the local SHA bundle run only on the local workstation. All other executable work, including tests for training/replay code, dataset generation, vocabulary construction, training, checkpoint selection, Stage 8 replay, aggregation, and overhead measurement, runs only on the Linux server. The server may verify the local bundle but must not rescan, reselect, or regenerate Pressure windows.

**Tech Stack:** Python 3.7-compatible code, PyTorch, CSV/JSON manifests, existing synchronous replay modules, `unittest`, Linux shell validation scripts.

---

## Material Passport

- Origin Skill: `academic-research-suite/experiment-agent`
- Origin Mode: `plan`
- Origin Date: `2026-08-01`
- Verification Status: `UNVERIFIED_PLAN`
- Version Label: `capd_stage7_repair_plan_v1`
- Raw data access: read-only
- Formal Test status: previously opened by invalid Stage 8; repaired evaluation must be reported as a protocol correction

## 1. Repair Decision And Boundaries

### 1.1 What is retained

- The six raw traces under `dataset/raw_traces/capd_proactive_stage7/stage7-local-collection-r1/` remain the only source data.
- Existing chronological splits remain the Standard track:
  - Train: `[0, 1800000)`
  - Validation: `[1800000, 2400000)`
  - Standard Test: `[2400000, 3000000)`
- Frozen controller/model settings remain:
  - `F_low=8`
  - `F_target=16`
  - `b_max=4`
  - `K=8`
  - `H=20`
  - `L=256`
  - `lambda=(1,1,2)`
  - seeds `3136859`, `42`, `2026`
  - TPP-inspired `epoch_length=1024`, `cold_threshold=1`, `dirty_tie_break=false`
  - cost profile `1:2:8:10`

### 1.2 What is invalidated

- `outputs/capd_proactive_stage8/stage8-sync-replay-r3/` remains on disk but is classified as `invalid_old_checkpoint_new_trace_diagnostic`.
- The three Stage 4 checkpoints in `stage4-f8-f16-r3` are calibration checkpoints, not repaired final checkpoints.
- The roles `seen_calibration_workload` and `held_out_unseen_workload` are removed from the repaired main experiment. All six workloads contribute Train/Validation data to one global CAPD model.
- Standard and Pressure results must never be merged into one macro average.

### 1.3 Integrity rules

- Do not edit, reorder, duplicate, delete, synthesize, or relabel raw access records.
- Every derived CSV records raw trace SHA256, source trace ID, half-open interval, derivation rule version, and derived SHA256.
- Pressure windows may use only Reactive-LRU pressure features. CAPD, TPP-inspired, Oracle, weighted cost, and previous policy results are prohibited selection inputs.
- Pressure Test is a post-hoc, method-independent secondary evaluation because the original Standard Test has already been inspected.
- Pressure Test cannot support claims about:
  - model memory footprint;
  - per-decision inference latency;
  - CPU cycles;
  - total execution time;
  - foreground blocking time;
  - end-to-end system overhead.
- Those overhead claims may use only the unselected Standard Test, fixed microbenchmarks, or the later asynchronous experiment.

## 2. Output Namespace And File Map

Do not modify the contents of any existing verified output directory.

**Create:**

- `configs/finals/capd_proactive_stage7_repair.json`: immutable repair policy, window rule, capacity guard, and six-workload training scope.
- `configs/finals/capd_proactive_stage8_repair.json`: repaired Stage 8 authority paths and dual-track reporting contract.
- `qmap/proactive_stage7_repair.py`: raw audit, fixed-capacity derivation, pressure scan, manifest construction, and freeze validation.
- `scripts/run_capd_proactive_stage7_repair.py`: local `preflight`/`scan-pressure`/`export-local-bundle` commands and server `verify-local-bundle`/`build-training-manifest`/`freeze`/`verify` commands.
- `scripts/run_capd_proactive_stage4_refit.py`: fixed-parameter six-workload refit CLI; it must not run the Stage 4 hyperparameter grid.
- `tests/test_capd_proactive_stage7_repair.py`: raw immutability, interval, deterministic scan, and manifest tests.
- `tests/test_capd_proactive_stage4_refit.py`: fixed parameters, six-workload merge, train-only vocabulary, and checkpoint tests.
- `tests/test_capd_proactive_stage8_repair.py`: repaired plan, dual-track aggregation, and overhead-claim rejection tests.
- `docs/CAPD_PROACTIVE_STAGE7_REPAIR_SERVER_CN.md`: server commands and artifact return checklist.

**Modify while preserving v1 compatibility:**

- `qmap/proactive_stage8_contract.py`: accept the repaired v2 execution plan and reject mixed Standard/Pressure aggregates.
- `qmap/proactive_stage8_results.py`: group by `evaluation_track` before any aggregation.
- `scripts/run_capd_proactive_stage8.py`: include `evaluation_track` in job identities and result manifests.
- `scripts/validate_capd_proactive_stage8_server.sh`: accept an optional repair config path.
- `docs/CAPD_PROACTIVE_STAGE8_SERVER_CN.md`: mark `stage8-sync-replay-r3` as historical diagnostic authority only.

**Generated artifacts:**

```text
outputs/capd_proactive_stage7_repair/stage7-repair-r1/
  raw_identity_audit.json
  frozen_parameters.json
  capacity_matrix_standard.json
  capacity_matrix_guarded.json
  pressure_candidates.csv
  pressure_window_manifest.json
  derived_pressure/<workload>/<capacity>.csv
  local_pressure_bundle_manifest.json
  stage4_input_manifest.json
  standard_test_lock.json
  pressure_test_lock.json
  stage8_execution_plan_v2.json
  verification.json

outputs/capd_proactive_stage4/stage4-stage7-refit-r1/
  final_rebuild/L256_lam1-1-2_K8_H20/
  final_freeze_candidate.json
  verification.json

outputs/capd_proactive_stage8/stage8-repair-r1/
  jobs/
  artifacts/standard/
  artifacts/pressure/
  verification.json
```

## 3. Chronological Repair Sequence

The mandatory order is:

```text
archive old result
  -> [local] audit immutable Stage 7 inputs
  -> [local] freeze repair contract and compute capacities
  -> [local] scan/derive/freeze Pressure windows with Reactive-LRU only
  -> [transfer] upload immutable local bundle and verify SHA on server
  -> [server] build six-workload Train/Validation manifest
  -> [server] refit three final CAPD checkpoints
  -> [server] freeze repaired Stage 7/Stage 8 plan
  -> [server] run Standard Stage 8
  -> [server] run Pressure Stage 8 from verified derived CSV files
  -> [server] aggregate the two tracks separately
  -> [server] verify and report
```

No step may read CAPD Test results before both locks and the execution plan are frozen.

## 4. Capacity And Pressure Rules

### 4.1 Standard capacity

Retain the original reproducibility matrix:

```text
W_i = unique pages in Stage 7 Train union Validation
D_base(i, r) = ceil(r * W_i), r in {0.20, 0.40, 0.60}
```

These cells reproduce the original capacity definition and remain the Standard track.

### 4.2 Mechanism-compatible guarded capacity

Pressure evaluation must keep the fixed absolute watermarks from consuming most of a tiny DRAM:

```text
reserve_fraction_cap = 0.25
D_guard_min = ceil(F_target / reserve_fraction_cap) = 64
D_guarded(i, r) = max(D_base(i, r), 64)
effective_ratio = D_guarded(i, r) / W_i
```

Every table must report `requested_ratio`, `D_base`, `D_guarded`, and `effective_ratio`. A clamped cell must not be described as an exact 20%, 40%, or 60% capacity experiment.

### 4.3 Pressure candidate scan

Scan only inside the existing Standard Test interval `[2400000, 3000000)`:

```text
window_records = 100000
scan_step = 10000
candidate starts = 2400000, 2410000, ..., 2900000
```

For every workload and guarded capacity, replay Reactive-LRU from an empty DRAM for each candidate. Record:

- unique pages;
- misses;
- LRU replacement decisions;
- write ratio;
- page-entry count;
- candidate source interval.

Eligibility requires both:

```text
unique_pages > D_guarded + F_target
LRU replacement decisions >= 100
```

Select by this fixed tuple:

```text
highest LRU replacement decisions
then highest unique pages
then earliest start index
```

If no candidate passes, emit `pressure_eligible=false`; do not manufacture a Pressure Test for that workload/capacity cell. Save all candidates so the selected window is auditable.

The local derivation must materialize each selected source interval as a new CSV. Each row must equal the corresponding source-Test row in the same order. `local_pressure_bundle_manifest.json` records source SHA, start/end indices, row count, derived SHA, config SHA, and every included file SHA. After upload, the server verifies this bundle byte-for-byte and must reject any missing or changed artifact; it does not rerun window selection.

## 5. Stage 3 Repair Audit

Stage 3 is rerun as a six-workload Train/Validation diagnostic, not as a Test-driven parameter search.

- Recompute `W_i`, `D_base`, `D_guarded`, page-entry bursts, Reactive-LRU misses, and decision counts from Train followed by Validation.
- Keep `F_low=8`, `F_target=16`, and `b_max=4` fixed.
- Reject any Test path passed to Stage 3.
- Write `frozen_parameters.json` with the inherited values and `selection_source=stage4-f8-f16-r3_calibration`.
- Do not promote a guarded capacity to Standard capacity; they are separate tracks.

Gate:

```text
STAGE7_REPAIR_STAGE3_AUDIT_READY
```

## 6. Stage 4 Fixed Refit

The repaired Stage 4 operation is a refit, not a second hyperparameter search.

- Merge all six Stage 7 Train splits into the global training dataset.
- Merge all six Stage 7 Validation splits into the global validation dataset.
- Generate proactive training samples with the inherited controller settings.
- Use exactly `L=256`, `lambda=(1,1,2)`, `K=8`, and `H=20`.
- Fit page/PC vocabularies from Train only, then freeze them before Validation.
- Train all three seeds for 10 epochs.
- Select each seed's checkpoint by minimum global Validation loss, tie-breaking on earliest epoch.
- Do not select a best seed; Stage 8 runs all three.
- Record per-workload Validation OOV and ranking metrics, but do not use Test.

Gate:

```text
STAGE4_STAGE7_REFIT_VERIFIED
```

Required verification fields:

```json
{
  "training_workloads": 6,
  "validation_workloads": 6,
  "formal_test_opened": false,
  "hyperparameters_reselected": false,
  "vocabulary_fit_split": "train_only",
  "checkpoint_selection_split": "validation_only",
  "checkpoint_count": 3
}
```

## 7. Stage 7 Repair Freeze

After checkpoint verification, freeze a v2 plan with:

- six `training_seen_workload` entries;
- three repaired checkpoint paths and SHA256 values;
- Standard Test locks for all six workloads;
- Pressure locks only for eligible workload/capacity cells;
- Standard job count exactly `6 * 3 * (5 + 3) = 144`;
- Pressure job count exactly `eligible_cells * (5 + 3)`;
- OOV diagnostics retained for both tracks;
- no `held_out_direct_checkpoint_inference` field;
- `checkpoint_retraining_completed=true`;
- `vocabulary_source=stage7_train_all_six`;
- `pressure_overhead_claims_allowed=false`.

Gate:

```text
STAGE7_REPAIR_EXECUTION_PLAN_VERIFIED
```

## 8. Stage 8 Execution And Reporting

### 8.1 Standard track

Run all 144 jobs on the unselected 600,000-access Standard Test splits. Report:

- DRAM hits;
- NVM reads and writes;
- proactive/reactive/emergency demotions;
- weighted cost;
- proactive cycles and rounds;
- early-reuse rates;
- OOV diagnostics;
- synchronous inference and memory overhead, with the existing interpretation boundary.

### 8.2 Pressure track

Run all six policies and all three CAPD seeds only for eligible cells. Report:

- the same page-event and weighted-cost metrics;
- Oracle headroom;
- LRU decision count;
- proactive trigger coverage;
- early-reuse rates;
- source interval and selection score.

The Pressure aggregate must set:

```json
{
  "overhead_claim_status": "not_reported_for_overhead_claim",
  "memory_overhead": null,
  "inference_latency": null,
  "cpu_cycles": null,
  "foreground_blocking_time": null
}
```

The verifier must fail if a Pressure report contains a non-null overhead value or if Standard and Pressure rows are combined in one confidence interval.

## 9. Implementation Tasks

### Task 1: Freeze the repair configuration

**Files:**
- Create: `configs/finals/capd_proactive_stage7_repair.json`
- Create: `configs/finals/capd_proactive_stage8_repair.json`
- Test: `tests/test_capd_proactive_stage7_repair.py`

- [ ] **Step 1: Write a failing config-contract test**

Assert exact inherited parameters, six training workloads, `reserve_fraction_cap=0.25`, immutable source run `stage7-server-suite-r1`, and `pressure_overhead_claims_allowed=false`.

- [ ] **Step 2: Run the focused test**

```bash
python3 -m unittest tests.test_capd_proactive_stage7_repair -v
```

Expected: FAIL because the repair configs do not exist.

- [ ] **Step 3: Add the two JSON configs**

The Stage 7 config must contain the exact rules in Sections 1 and 4. The Stage 8 config must point only to `stage7-repair-r1` artifacts and must not overwrite `configs/finals/capd_proactive_stage8.json`.

- [ ] **Step 4: Rerun the test**

Expected: config-contract tests PASS.

### Task 2: Implement immutable audit and pressure selection

**Files:**
- Create: `qmap/proactive_stage7_repair.py`
- Create: `scripts/run_capd_proactive_stage7_repair.py`
- Test: `tests/test_capd_proactive_stage7_repair.py`

- [ ] **Step 1: Add failing tests**

Cover raw SHA mismatch rejection, interval bounds, deterministic tie-breaking, prohibited CAPD/Oracle score inputs, ineligible cells, and derived-row equality with the source interval.

- [ ] **Step 2: Run the focused test**

Expected: FAIL because the repair module is missing.

- [ ] **Step 3: Implement these public functions**

```python
audit_raw_identities(config, project_root) -> dict
compute_capacity_matrices(split_manifest, config, project_root) -> dict
scan_pressure_candidates(test_lock, guarded_capacities, config, project_root) -> list
select_pressure_windows(candidates, config) -> dict
build_stage4_input_manifest(split_manifest, raw_audit, project_root) -> dict
freeze_repair_plan(inputs, checkpoints, output_root) -> dict
```

The CLI must expose:

```text
preflight
scan-pressure
export-local-bundle
verify-local-bundle
build-training-manifest
freeze
verify
```

- [ ] **Step 4: Rerun the focused test**

Expected: all repair audit and selection tests PASS.

### Task 3: Implement fixed six-workload refit

**Files:**
- Create: `scripts/run_capd_proactive_stage4_refit.py`
- Test: `tests/test_capd_proactive_stage4_refit.py`
- Reuse: `qmap/proactive_stage4.py`
- Reuse: `scripts/run_capd_proactive_stage4.py`

- [ ] **Step 1: Add failing tests**

Verify that the refit rejects Test entries, rejects any parameter other than `L256/lambda1-1-2/K8/H20`, includes six workload pairs, fits vocabulary from Train only, and emits three checkpoints.

- [ ] **Step 2: Run the focused test**

```bash
python3 -m unittest tests.test_capd_proactive_stage4_refit -v
```

Expected: FAIL because the refit runner is missing.

- [ ] **Step 3: Implement the runner**

The runner may reuse Stage 4 dataset generation, training, validation, resume, and verification helpers, but it must bypass `lookahead`, `label-weights`, and `candidate-history` grid selection. Its command set is:

```text
preflight
build-dataset
train
validate
verify
all
```

- [ ] **Step 4: Rerun the focused test**

Expected: all fixed-refit tests PASS.

### Task 4: Add repaired Stage 8 contract support

**Files:**
- Modify: `qmap/proactive_stage8_contract.py`
- Modify: `qmap/proactive_stage8_results.py`
- Modify: `scripts/run_capd_proactive_stage8.py`
- Test: `tests/test_capd_proactive_stage8_repair.py`

- [ ] **Step 1: Add failing v2 contract tests**

Test 144 Standard jobs, variable eligible Pressure jobs, repaired checkpoint SHA enforcement, track-separated aggregates, and rejection of Pressure overhead claims.

- [ ] **Step 2: Run existing and new Stage 8 tests**

```bash
python3 -m unittest tests.test_capd_proactive_stage8 tests.test_capd_proactive_stage8_repair -v
```

Expected: existing v1 tests PASS; new v2 tests FAIL.

- [ ] **Step 3: Implement backward-compatible v2 handling**

Keep all v1 schemas readable. Add `evaluation_track` to repaired jobs and dispatch aggregation by track before workload/capacity grouping.

- [ ] **Step 4: Rerun both suites**

Expected: v1 and v2 tests PASS.

### Task 5: Add server validation and documentation

**Files:**
- Modify: `scripts/validate_capd_proactive_stage8_server.sh`
- Create: `docs/CAPD_PROACTIVE_STAGE7_REPAIR_SERVER_CN.md`
- Modify: `docs/CAPD_PROACTIVE_STAGE8_SERVER_CN.md`

- [ ] **Step 1: Add an optional repair config argument**

The existing two-argument invocation must keep working. The repaired invocation is:

```bash
bash scripts/validate_capd_proactive_stage8_server.sh \
  stage8-repair-r1 cuda:0 \
  configs/finals/capd_proactive_stage8_repair.json
```

- [ ] **Step 2: Document failure recovery**

Never delete a failed run. Reuse a Stage 4 refit run ID only when identity and contract hashes match; Stage 8 failures require a new run ID under the existing resume contract.

- [ ] **Step 3: Mark the old result correctly**

Documentation must call `stage8-sync-replay-r3` a verified execution of the invalid old-checkpoint/new-trace protocol, not the repaired formal result.

### Task 6: Respect the local/server execution split

- [ ] **Step 1: Run only trace audit/derivation checks locally**

```powershell
python scripts/run_capd_proactive_stage7_repair.py preflight --config configs/finals/capd_proactive_stage7_repair.json --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 --run-id stage7-repair-r1
python scripts/run_capd_proactive_stage7_repair.py scan-pressure --config configs/finals/capd_proactive_stage7_repair.json --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 --run-id stage7-repair-r1
python scripts/run_capd_proactive_stage7_repair.py export-local-bundle --run-id stage7-repair-r1
```

- [ ] **Step 2: Verify the local handoff artifact**

Expected assertions: raw SHA unchanged, deterministic window selection, derived rows exactly match the selected source intervals, and the bundle contains all source/derived/config SHA values. Required marker: `STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED`.

- [ ] **Step 3: Upload the frozen bundle without editing it**

The upload includes `pressure_candidates.csv`, both capacity matrices, the pressure window/test locks, every derived Pressure CSV, and `local_pressure_bundle_manifest.json`.

- [ ] **Step 4: Run all non-trace executable verification on the server**

Compilation, Stage 4 refit tests, Stage 8 contract tests, regression suites, training, replay, aggregation, and overhead measurements are server-only.

## 10. Linux Server Run Order

Run only after the local trace bundle is frozen and uploaded. The Linux server consumes that bundle; it must not scan or derive Pressure traces.

### 10.1 Environment and local-bundle verification

```bash
cd /home/likc/Q-former-for-OS
conda activate capd
git status --short
python3 -c 'import sys,torch; print(sys.version); print(torch.__version__); print(torch.cuda.is_available())'

python3 scripts/run_capd_proactive_stage7_repair.py verify-local-bundle \
  --bundle outputs/capd_proactive_stage7_repair/stage7-repair-r1/local_pressure_bundle_manifest.json \
  --run-id stage7-repair-r1
```

Stop unless the terminal prints:

```text
STAGE7_REPAIR_SERVER_ACCEPTED_LOCAL_BUNDLE
```

### 10.2 Compile and test server-only code

```bash
python3 -m py_compile \
  scripts/run_capd_proactive_stage4_refit.py \
  qmap/proactive_stage8_contract.py \
  qmap/proactive_stage8_results.py \
  scripts/run_capd_proactive_stage8.py

python3 -m unittest \
  tests.test_capd_proactive_stage4_refit \
  tests.test_capd_proactive_stage8_repair \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  tests.test_capd_proactive_stage7 \
  tests.test_capd_proactive_stage8 -v
```

The server must not invoke `scan-pressure` or `export-local-bundle`.

Inspect the uploaded manifest without editing:

```bash
python3 -m json.tool \
  outputs/capd_proactive_stage7_repair/stage7-repair-r1/pressure_window_manifest.json
```

Stop unless every selected window has `selection_features=["reactive_lru_decisions","unique_pages","earliest_start"]` and every ineligible cell has an explicit reason.

### 10.3 Build the six-workload Stage 4 input manifest

```bash
python3 scripts/run_capd_proactive_stage7_repair.py build-training-manifest \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --run-id stage7-repair-r1
```

Stop unless the manifest contains exactly 12 entries: six Train and six Validation, with zero Test entries.

### 10.4 Train the repaired CAPD checkpoints

```bash
python3 scripts/run_capd_proactive_stage4_refit.py all \
  --manifest outputs/capd_proactive_stage7_repair/stage7-repair-r1/stage4_input_manifest.json \
  --frozen-parameters outputs/capd_proactive_stage7_repair/stage7-repair-r1/frozen_parameters.json \
  --run-id stage4-stage7-refit-r1 \
  --project-root "$PWD" \
  --device cuda:0
```

Monitor:

```bash
tail -f outputs/capd_proactive_stage4/stage4-stage7-refit-r1/logs/progress.jsonl
```

Stop unless verification reports six training workloads, no Test access, unchanged fixed parameters, frozen Train vocabularies, and three valid checkpoints.

### 10.5 Freeze the repaired Stage 7 execution plan

```bash
python3 scripts/run_capd_proactive_stage7_repair.py freeze \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --checkpoint-freeze outputs/capd_proactive_stage4/stage4-stage7-refit-r1/final_freeze_candidate.json \
  --run-id stage7-repair-r1

python3 scripts/run_capd_proactive_stage7_repair.py verify \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --run-id stage7-repair-r1
```

Required final marker:

```text
STAGE7_REPAIR_EXECUTION_PLAN_VERIFIED
```

### 10.6 Run repaired Stage 8

```bash
set -o pipefail
bash scripts/validate_capd_proactive_stage8_server.sh \
  stage8-repair-r1 cuda:0 \
  configs/finals/capd_proactive_stage8_repair.json \
  2>&1 | tee stage8-stage8-repair-r1-console.log
```

Required final marker:

```text
[FINAL] STAGE8_REPAIR_STANDARD_PRESSURE_VERIFIED
```

## 11. Final Acceptance Gates

The repair is complete only when all are true:

- Raw Stage 7 SHA identities match the original Stage 7 manifests.
- No raw trace has changed.
- The Stage 4 refit manifest contains all six Train/Validation pairs and no Test.
- Fixed parameters exactly match the inherited Stage 4 selection.
- Three new checkpoints exist and point to Stage 7 Train vocabularies.
- Standard Test has exactly 144 completed jobs.
- Pressure Test contains only eligible cells and identical windows across policies.
- Standard and Pressure aggregates are separate.
- Pressure reports contain no memory/time/CPU/end-to-end overhead claims.
- OOV is reported for both tracks and is no longer assumed to be zero.
- Existing historical outputs remain present and unchanged.
- The report discloses that Pressure Test is a post-hoc, method-independent continuous slice of genuinely collected traces.

## 12. Server Return Package

```bash
tar -czf capd-stage7-repair-r1-results.tar.gz \
  outputs/capd_proactive_stage7_repair/stage7-repair-r1 \
  outputs/capd_proactive_stage4/stage4-stage7-refit-r1 \
  outputs/capd_proactive_stage8/stage8-repair-r1 \
  stage8-stage8-repair-r1-console.log

sha256sum capd-stage7-repair-r1-results.tar.gz
```

Return the archive, its SHA256, the last 100 console lines, and these three verification files:

```text
outputs/capd_proactive_stage7_repair/stage7-repair-r1/verification.json
outputs/capd_proactive_stage4/stage4-stage7-refit-r1/verification.json
outputs/capd_proactive_stage8/stage8-repair-r1/verification.json
```
