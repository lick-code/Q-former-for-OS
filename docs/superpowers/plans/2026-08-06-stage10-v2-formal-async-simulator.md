# CAPD Stage10 v2 Formal Async Simulator Implementation Plan

**Status:** implementation plan review pending; implementation, formal simulation, Stage11A migration, commit, and push are not authorized.

**Approved design:** `docs/superpowers/specs/2026-08-06-stage10-formal-async-simulator-migration-design.md`

**Approved design SHA256:** `2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd`

**Target contract:** `CAPD-PROACTIVE-STAGE10-2.0`

**Target success status:** `stage10_async_simulation_verified`

**Target evidence mode:** `deterministic_async_simulation`

**Target run id:** `stage10-async-simulator-v2-r1`

## 1. Approval and scope boundary

This document is a plan only. Writing or approving this plan does not retroactively authorize work already prohibited by the approved design.

The next explicit plan approval is intended to authorize the tasks in this document in order, including TDD implementation, local synthetic tests, one read-only integration audit of Stage9 r3, creation of the new 60-scenario Stage10 v2 run, and read-only independent verification. If the user approves only implementation but excludes the formal run, execution must stop after Task 9.

The plan never authorizes:

- rerunning or rewriting Stage9 measurement;
- modifying Stage9 `verification.json`, `run_state.json`, measurement checkpoint, summaries, or values;
- overwriting Stage8, Stage9, Stage10A, or failed Stage10 v2 evidence;
- retraining, checkpoint selection, Test-based tuning, or vocabulary changes;
- treating Cost profile weights as time;
- Stage11A positive migration;
- real NVM, kernel, concurrency, or foreground end-to-end claims;
- automatic commit or push.

## 2. Frozen authority and baseline bindings

Implementation must validate these values before any v2 output directory is created:

| Binding | Required value |
| --- | --- |
| Approved design SHA | `2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd` |
| Byte-recovery audit SHA | `94a68bfccfa6fec3a947b6ed35f83cca04a09bfe708b9390385d7476e0c5bc64` |
| Stage9 run id | `stage9-overhead-v2-r3` |
| Stage9 config SHA | `642641d56fe52e3772bdaa0772d5c9fd250cc17976918ce99acd36d18a035922` |
| Stage9 result schema SHA | `a07c1f4b192f76eff45d33fcbe6e37b325aec1a8648c5542538ead1b6ecda893` |
| Stage9 verification SHA | `bc5dc7fc46247da5d2085dd302150361232ff0cd27cd9b911cb559072ef8635f` |
| Stage9 checkpoint SHA | `8ec44db66348aef3c65459ea48a3b87fc417d862102c85b4fe6bda958bf915d3` |
| Stage9 latency summary SHA | `a4e28f6627b278258202d7ab71db72474f29f9e569ca432ebfc40e36baf12a09` |
| Stage9 run identity file SHA | `3241d3df3b1ff701dcc0a571d05f0eacab8412becf1fc960e22df97ef433c2b2` |
| Stage9 internal run identity SHA | `cc662852fa7ee43209d721b5acaae062fb02d790f82e5245ec0511c443987454` |
| Stage9 run state SHA | `c862886d04981e63569258e5605994c6bf14afca880122e39777903d30a3e1c3` |
| Stage8 compatibility receipt SHA | `fc91e2538e6f88a65fc777ea79fc5d99581f47034a194507c599d58c2b6ba27d` |
| Capacity CSV SHA | `aebc319fe12f34a93eb1405c7a8590262543935b67da751aed62ddad678d902a` |
| perf raw SHA | `aa946e5bfa49c34ad717da6066dd5180e0bff835e723588814f0a2067b5b3fd0` |

Before implementation, capture path/length/SHA256 snapshots for:

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`;
- `outputs/capd_proactive_stage9/stage9-overhead-v2-r3/` using the recovered bytes as baseline;
- `outputs/capd_proactive_stage10/stage10-async-simulator-r1/`.

Store implementation-session snapshots under ignored `tmp/` paths. They are diagnostic controls, not formal artifacts. Compare them after every task that runs tests touching filesystem code, and again before final reporting.

## 3. Architecture and file map

### Preserve unchanged

- `docs/superpowers/specs/2026-08-05-stage10-async-simulator-design.md`
- `docs/superpowers/plans/2026-08-05-stage10-async-simulator.md`
- `configs/finals/capd_proactive_stage10.json`
- `configs/finals/capd_proactive_stage10_result_schema.json`
- `qmap/proactive_stage10.py`; v2 must use its existing public engine interfaces without modifying this v1 module
- `tests/test_capd_proactive_stage10.py`
- `outputs/capd_proactive_stage10/stage10-async-simulator-r1/`
- all Stage11A source, config, tests, docs, and outputs

### Extend

- `scripts/run_capd_proactive_stage10.py`
  - rename the current verifier internally to `verify_v1_fixture_run` without changing its behavior;
  - add strict `config.json.contract_id` dispatch;
  - dispatch v2 verification to the new v2 runner module;
  - reject unknown contracts before interpreting artifacts.

### Add

- `qmap/proactive_stage10_v2.py`
- `scripts/run_capd_proactive_stage10_v2.py`
- `configs/finals/capd_proactive_stage10_v2.json`
- `configs/finals/capd_proactive_stage10_result_schema_v2.json`
- `tests/test_capd_proactive_stage10_v2.py`
- `tests/stage10_v2_test_support.py`
- `docs/CAPD_PROACTIVE_STAGE10_V2_PROTOCOL_CN.md`
- `docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md`
- after all implementation gates pass: `outputs/capd_proactive_stage10/stage10-async-simulator-v2-r1/`

The v2 module may reuse v1 `EventQueue`, `SimulatorConfig`, arrival primitives, and `run_simulation` as a versioned engine dependency. It must not reuse v1 config validation, the obsolete Stage9 gate, fixture interpretation, result-row mode, or v1 state writer.

## 4. TDD execution discipline

Every task follows this order:

1. Add the narrow failing test.
2. Run only the named test and confirm failure is caused by missing v2 behavior, not syntax or fixture corruption.
3. Implement the minimum contract behavior.
4. Rerun the narrow test to green.
5. Run all completed v2 test classes plus the entire v1 Stage10 test module.
6. Compare frozen tree snapshots when the task exercised filesystem orchestration.

Do not create the target v2 run directory during Tasks 0-9. All runner tests use `tempfile.TemporaryDirectory` and unique run ids.

## 5. Task 0: Lock the approved design and frozen baselines

**Files:** no production code changes.

### Tests and checks

- Assert the approved design file SHA equals `2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd`.
- Parse the byte-recovery audit and require `status=byte_recovery_verified`, 31 before files, 31 after files, exactly two changed paths, and 19 verified Stage9 mappings.
- Require the two Stage9 files to resolve as Git binary attributes and match their formal hashes.
- Capture Stage8 r5, Stage9 r3, and Stage10A r1 tree snapshots.
- Run the existing Stage10A verifier and require 5 results and 12 manifest payloads.
- Run the existing Stage11A Stage10 audit and require `BLOCKED / stage10a_fixture_only`.

### Commands

```powershell
python scripts\run_capd_proactive_stage10.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-r1
python -m unittest tests.test_capd_proactive_stage10 -v
```

Expected: v1 tests pass; no v2 output directory exists; frozen snapshots are unchanged.

## 6. Task 1: Add the v2 config and result-schema contract

**Tests first:** `Stage10V2ConfigContractTest`

### Failing tests

- repository v2 config has the exact contract/schema/evidence/status/run-id values;
- config binds the final approved-design SHA, recovery-audit SHA, Stage9 authority hashes, and v2 result-schema SHA;
- result schema requires `comparison_channel`, `timing_profile_id`, `arrival_profile_id`, observed/derived/interpretation objects, and complete `arrival_binding`;
- result mode allows only `deterministic_async_simulation`;
- old fixture contract, pending-design SHA, unknown status, missing migration approval, unapproved ratios, wrong scenario count, or weakened Stage9 binding fail closed;
- no v2 constant is read from the v1 fixture parameters.

### Implementation

Create `qmap/proactive_stage10_v2.py` with:

```text
CONTRACT_ID = CAPD-PROACTIVE-STAGE10-2.0
CONFIG_SCHEMA_VERSION = capd_proactive_stage10_v2_0
RESULT_SCHEMA_VERSION = capd_proactive_stage10_result_v2_0
EVIDENCE_MODE = deterministic_async_simulation
VERIFIED_STATUS = stage10_async_simulation_verified
RUN_ID = stage10-async-simulator-v2-r1
```

Implement strict structured config validation. Do not allow caller overrides of contract identity, run id, approved design SHA, Stage9 run id, timing conversion rule, comparison channels, timing profiles, arrival profiles, or 60-scenario count.

Create the v2 result schema first, compute its SHA256, then place that digest in the v2 config. The config records migration scenarios as `predeclared_simulator_scenario_ratio_not_hardware_measurement` and labels `migration-ratio-0p10` as `reference`, never `primary_hardware` or `measured`.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2ConfigContractTest -v
```

Expected: tests pass; no output run is created.

## 7. Task 2: Implement the read-only Stage9 r3 input gate

**Tests first:** `Stage10V2Stage9GateTest`

### Test support

Create `tests/stage10_v2_test_support.py` to build compact Stage9-shaped evidence under a temporary project root. The low-level audit accepts a validated `TrustedStage9Binding` object so synthetic tests can bind their own compact artifact hashes. The production entrypoint constructs that binding only from the strict repository v2 config; callers cannot supply a receipt or bypass the production constants.

Do not copy, rewrite, hardlink-and-mutate, or monkeypatch the real 194 MB `raw_latency_samples.csv`. Only one positive integration test reads the real r3 directory, and that test is read-only.

### Failing tests

- real `stage9-overhead-v2-r3` passes the complete production gate;
- r1, v2-r1, v2-r2, unknown run ids, indirect children, outside-repository paths, symlinks/path escape, missing files, malformed JSON, and identity mismatch fail;
- old Stage9 config SHA fails;
- Stage9 root without manifest/SHA256SUMS passes when its own schema is complete;
- a caller-provided self-declared verified receipt is ignored/rejected;
- all 19 `verification.artifact_sha256` keys are exact and recomputed;
- converting capacity CSV back to LF or perf raw back to CRLF fails;
- `verification.json` or `run_state.json` tampering fails through their separately pinned SHA;
- Stage8 compatibility receipt, Linux environment, perf required events, RSS, regression receipt, instrumentation, quality, capacity, and preflight fields are checked.

### Implementation

Add immutable typed records for trusted bindings and audit results. Implement path containment before opening each required artifact. Load the Stage9 result schema from the trusted repository path, derive the exact required list, and explicitly exclude only `verification.json` and `run_state.json` from the Stage9 artifact map comparison.

Generate a Stage10-owned receipt in memory only after all checks pass:

```text
schema_version = capd_proactive_stage10_stage9_input_receipt_v2_0
status = stage10_stage9_input_verified
source_run_id = stage9-overhead-v2-r3
formal_authorized = true
```

The receipt must contain observed hashes, not copied self-assertions.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2Stage9GateTest -v
```

Expected: real r3 integration passes; all synthetic corruptions fail; r3 tree snapshot is unchanged.

## 8. Task 3: Validate the measurement checkpoint

**Tests first:** `Stage10V2MeasurementCheckpointTest`

### Failing tests

- checkpoint is required and must be present in the 19-key verification map;
- `status=completed`, `failure=null`, raw path, raw length, and raw SHA are exact;
- 90 completed cells are unique and equal the 90 quality-row identities;
- the 30 `b_max=2` identities equal the 30 instrumentation identities;
- `quality_row_count=90`, `instrumentation_audit_count=30`, and Stage9 config matrix counts agree;
- missing, rehashed tamper, duplicate cell, wrong b_max, wrong seed/workload/track, count-only forgery, or raw/checkpoint SHA mismatch fails.

### Implementation

Implement a dedicated checkpoint validator. Compare identity sets, not only counts. Bind the checkpoint file SHA from the production v2 config before trusting its fields.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2MeasurementCheckpointTest -v
```

Expected: all negative fixtures fail closed; no Stage9 file is written.

## 9. Task 4: Derive timing provenance with Decimal arithmetic

**Tests first:** `Stage10V2TimingProvenanceTest`

### Failing tests

- parse Stage9 JSON numbers with `parse_float=Decimal`;
- read exact source field `by_b_max["2"].stages.total_round_latency_ns`;
- require count 182394 and formal b_max 2;
- convert mean `2252304.4582606885` to 2252304 via `ROUND_HALF_UP`;
- convert p50/p95/p99 to 2192418/2625519/2938056;
- derive migration ratios to 22523/225230/2252304 using the same rule;
- reject fixture 2000 ns, binary-float provenance, direct timing override, Cost weight 10, missing source hashes, or a reference role changed after results;
- provenance serializes original decimals as strings and binds every required Stage9 SHA.

### Implementation

Add a `TimingProvenance` record and pure derivation function. It receives the already-audited Stage9 payload and trusted hashes; it never accepts free-form nanoseconds from the CLI.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2TimingProvenanceTest -v
```

Expected: exact integer values match the approved design; no result is selected from simulation output.

## 10. Task 5: Build exact-rational arrival bindings and the 60-scenario matrix

**Tests first:** `Stage10V2ArrivalMatrixTest`

### Failing tests

- exactly six timing profiles, five arrival profiles, two channels, and 60 stable unique scenario ids;
- reference timing profile is mean inference plus `migration-ratio-0p10`;
- `fixed_arrival` generates each arrival profile once from reference `mu_demote` and reuses identical timestamp/page-id arrays for all six timing profiles;
- the six fixed-arrival rows for one arrival profile have identical canonical `arrival_stream_sha256`;
- fixed-arrival absolute rates are identical across timing profiles while effective normalized ratios change correctly;
- `capacity_normalized` uses each profile's own `mu_demote`, may produce different stream SHA, and always sets cross-profile comparison false;
- channel and `arrival_rate_basis` pairing is exact;
- uniform and burst rates are reduced rational objects, never floats;
- burst base, `[2s,3s)`, `[6s,7s)`, and post-burst rates/timestamps are represented and verified as piecewise objects;
- reorder, duplicate event, changed page id, changed timestamp, stale SHA, wrong reference, invalid scope, or non-reduced fraction fails.

### Implementation

Add pure helpers:

```text
canonical_arrival_payload(arrivals)
arrival_stream_sha256(arrivals)
exact_rate(mu, ratio)
build_fixed_arrival_streams(config, reference_timing)
build_capacity_normalized_streams(config, timing_profiles)
expand_scenario_matrix(config, timing, arrival_streams)
```

Canonical JSON uses UTF-8, sorted keys, compact separators, and stable event ordering. Store exact rates as integer numerator/denominator/unit objects. Store burst rates and normalized ratios as piecewise objects.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2ArrivalMatrixTest -v
```

Expected: matrix count is exactly 60; fixed-arrival stream identities are shared by construction and independently rechecked.

## 11. Task 6: Wrap the deterministic simulator without changing v1 semantics

**Tests first:** `Stage10V2SimulationContractTest`

### Failing tests

- a v2 scenario converts only approved timing and state fields into v1 engine inputs;
- observed metrics retain event priority, reservation disjointness, capacity, LRU tail, MRU admission, FIFO blocking, exhaustion integral, and null/N/A behavior;
- all 60 rows use `evidence_mode=deterministic_async_simulation` and not fixture/real-system modes;
- v2 interpretation explicitly sets real NVM, kernel behavior, real concurrency, and real foreground end-to-end claims false;
- fixed-arrival rows with different timing reuse identical arrivals but can produce different queue metrics;
- capacity-normalized rows cannot emit timing-causal interpretation;
- identical inputs produce byte-identical result rows;
- v1 fixture tests still pass byte-for-byte behavior checks.

### Implementation

Implement a v2 result wrapper around the stable event engine. Discard the v1 fixture interpretation and construct a v2 interpretation object from the approved contract. Do not alter ranking quality, candidate selection, promotion, or Stage8 evidence.

### Commands

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2SimulationContractTest -v
python -m unittest tests.test_capd_proactive_stage10 -v
```

Expected: both v1 and v2 tests pass; no v2 output directory exists.

## 12. Task 7: Implement the v2 runner lifecycle and artifact writer

**Tests first:** `Stage10V2RunnerLifecycleTest`

### Failing tests

- Stage9/config/design/schema/migration preflight failure creates no target directory;
- target run id is exact, must not exist, and cannot be overridden, resumed, or overwritten;
- Stage9 gate pass alone does not create a success state;
- after directory creation, execution failure writes `stage10_async_simulation_not_verified` and the run cannot resume;
- successful temporary runs write the exact v2 artifact set and 60 rows;
- run identity binds code/config/schema/engine/design/Stage9/timing/scenario/test evidence hashes;
- test log requires exact command identity, SHA, `Ran N tests`, minimum count, verbose result count, and final `OK`;
- arbitrary, empty, failed, wrong-module, stale-SHA, or modified logs fail;
- manifest and SHA256SUMS file sets and recursion exclusions are exact;
- extra files and path escape fail.

### Implementation

Create `scripts/run_capd_proactive_stage10_v2.py` with separate functions:

```text
load_and_validate_inputs
run_preflight
build_stage9_input_receipt
build_run_identity
execute_scenarios
write_payload_artifacts
write_manifest_and_checksums
verify_v2_run
main
```

Preflight performs all read-only checks before `mkdir`. Once the target directory is created, write atomically via temporary sibling files and `os.replace`. If execution fails after creation, preserve an immutable failure `run_state.json`; do not delete and reuse the run id.

### Targeted command

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2RunnerLifecycleTest -v
```

Expected: all runs stay under temporary directories; production target run id remains absent.

## 13. Task 8: Implement independent v2 verification and version dispatch

**Tests first:** `Stage10V2VerifierDispatchTest`

### Failing tests

- top-level verifier dispatches v1 contract to unchanged v1 verifier and v2 contract to v2 verifier;
- v1 fixture is rejected by v2 verifier;
- v2 result is rejected by the v1 branch;
- unknown contract/schema is rejected before reading version-specific artifacts;
- verifier reruns Stage9 gate instead of trusting saved receipt;
- verifier independently re-derives timing, arrival streams, 60-scenario matrix, all result rows, manifest, checksums, run identity, state, and interpretation;
- rehashed result tamper, changed arrival SHA/rate/scope, weakened comparison permission, extra file, or state-only success forgery fails;
- Stage11A source remains unchanged and its current fixture audit returns `NOT_VERIFIABLE` for v2, never positive authorization.

### Implementation

Refactor only `scripts/run_capd_proactive_stage10.py`:

```text
verify_v1_fixture_run = current verify_run behavior
verify_run = strict contract dispatcher
```

Load only `config.json` to identify the contract, then invoke the version-specific verifier. Do not make v1 validation accept new fields or states.

### Commands

```powershell
python -m unittest tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest -v
python -m unittest tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage11 -v
```

Expected: v1 and Stage11A regressions pass; Stage11A does not acquire a positive v2 path.

## 14. Task 9: Add v2 protocol/status docs and complete local implementation verification

**Tests first:** `Stage10V2DocumentationTest`

### Required documentation assertions

- literal contract/evidence/success status names are present;
- `stage10_async_simulation_verified` is defined only as simulator verification;
- `fixed_arrival` is the only formal timing-sensitivity channel;
- `capacity_normalized` is relative-capacity pressure only;
- reference migration ratio is explicitly non-measured and non-typical;
- unsupported real NVM/kernel/concurrency/end-to-end claims are listed;
- Stage11A positive migration is deferred;
- no text claims the formal run has occurred before Task 10.

### Full local test command

```powershell
python -m unittest tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage10_v2 tests.test_capd_proactive_stage11 -v
```

Then run:

```powershell
python scripts\run_capd_proactive_stage10.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-r1
git diff --check
git status --short
```

Recompute Stage9 19/19 artifact hashes and compare all three frozen tree snapshots.

Expected: all tests pass, old fixture still verifies, Stage9 remains 19/19, frozen trees are unchanged, and the production v2 run directory is still absent.

This is the mandatory stop point if the next approval excludes formal simulation.

## 15. Task 10: Generate and independently verify the formal v2 simulation run

Execute this task only if the next plan approval explicitly includes formal simulation.

### Preconditions

- Tasks 0-9 are green in the same worktree state.
- The production target directory does not exist.
- Stage9 r3 still passes 19/19 hashes and all structured gates.
- approved-design and recovery-audit SHA bindings still match.
- the test log was generated by the exact full v1/v2/Stage11 regression command and independently hashed.

### Run command shape

```powershell
$stage10V2TestLog = Join-Path (Resolve-Path 'tmp') 'stage10-v2-formal-regression.log'
$stage10V2TestCommand = 'python -m unittest tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage10_v2 tests.test_capd_proactive_stage11 -v'
$stage10V2TestOutput = & python -m unittest tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage10_v2 tests.test_capd_proactive_stage11 -v 2>&1 | ForEach-Object { "$_" }
$stage10V2TestExit = $LASTEXITCODE
[IO.File]::WriteAllText(
  $stage10V2TestLog,
  "COMMAND: $stage10V2TestCommand`n" + ($stage10V2TestOutput -join "`n") + "`n",
  [Text.UTF8Encoding]::new($false))
if ($stage10V2TestExit -ne 0) { throw "Stage10 v2 regression tests failed with exit code $stage10V2TestExit" }
$stage10V2TestSha = (Get-FileHash -LiteralPath $stage10V2TestLog -Algorithm SHA256).Hash.ToLowerInvariant()

python scripts\run_capd_proactive_stage10_v2.py `
  --config configs\finals\capd_proactive_stage10_v2.json `
  --stage9-run-root outputs\capd_proactive_stage9\stage9-overhead-v2-r3 `
  --output-root outputs\capd_proactive_stage10 `
  --run-id stage10-async-simulator-v2-r1 `
  --test-log-input $stage10V2TestLog `
  --test-log-sha256 $stage10V2TestSha
```

The runner must reject any run-id override that differs from the approved id even though the CLI displays the argument.

### Independent verification

```powershell
python scripts\run_capd_proactive_stage10.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r1
python scripts\run_capd_proactive_stage10_v2.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r1
```

Expected final evidence:

```text
contract_id = CAPD-PROACTIVE-STAGE10-2.0
evidence_mode = deterministic_async_simulation
run_state.status = stage10_async_simulation_verified
verification.status = stage10_async_simulation_verified
stage9_input_receipt.status = stage10_stage9_input_verified
result_count = 60
fixed_arrival timing comparison allowed = true
capacity_normalized timing comparison allowed = false
real_system_async_performance_verified = false
```

After verification:

- update `docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md` from its pre-run state to the exact verified run id, contract, evidence mode, verification SHA, result count, and interpretation boundary; do not edit protocol semantics or any output artifact;
- rerun `Stage10V2DocumentationTest` against the verified status document;
- recompute manifest and SHA256SUMS independently;
- rerun the full local test command;
- rerun old Stage10A verification;
- compare frozen Stage8, Stage9, and Stage10A snapshots;
- run `git diff --check` and inspect `git status --short`;
- do not commit or push.

## 16. Failure handling

- Preflight failure: return nonzero, emit structured stderr, create no target directory.
- Post-creation execution failure: preserve `stage10_async_simulation_not_verified`; never resume that run id.
- Verification failure: report the exact artifact/field/scenario mismatch; never rewrite evidence to pass.
- Stage9 hash or state failure: stop without weakening path, SHA, newline, checkpoint, or schema rules.
- Frozen tree difference: stop and report before any further run.
- Existing target run id: stop; do not delete, overwrite, rename, or choose a new id without a new design decision.
- Test failure: fix code/tests only within the approved v2 surface; do not alter Stage9, frozen evidence, or approved parameters.

## 17. Final handoff report

The implementation report must separate:

1. implemented code and passing tests;
2. Stage9 r3 input-gate evidence;
3. Stage10 v2 deterministic simulation evidence;
4. fixed-arrival timing sensitivity versus capacity-normalized pressure curves;
5. unsupported real-system conclusions;
6. exact modified/new files and confirmation of no commit/push.

If Task 10 was not authorized or did not complete, all formal result fields must be `N/A` or `NOT_VERIFIABLE`; implementation/tests cannot substitute for the missing run.

## 18. Plan self-review checklist

- [x] Final approved-design SHA, not pending-design SHA, is bound.
- [x] Stage9 uses its actual schema and 19-key artifact map; no root manifest/SHA256SUMS is invented.
- [x] Measurement checkpoint is required and validated by identity sets, not counts alone.
- [x] Timing is derived from Decimal Stage9 provenance; fixture 2000 ns and Cost weight 10 are rejected.
- [x] Migration 0.10 is a reference simulator scenario, not a hardware primary.
- [x] Fixed-arrival and capacity-normalized channels are separate and total exactly 60 rows.
- [x] Fixed-arrival event identity and exact-rational arrival binding are independently verified.
- [x] v1/v2 are bidirectionally incompatible and Stage11A remains negative-only.
- [x] Failed preflight creates no run; failed/complete run ids are immutable.
- [x] Formal verification reruns the simulation and input gate rather than trusting receipts or hashes alone.
- [x] Frozen Stage8/Stage9/Stage10A evidence is checked before and after.
- [x] No implementation, formal run, commit, or push is performed while this plan awaits approval.

Self-review conclusion: no unresolved P1/P2 implementation-plan issue was found. The plan is ready for user review but is not implementation authorization until explicitly approved.
