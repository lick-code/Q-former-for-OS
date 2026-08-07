# CAPD Stage10 v2-r2 Source Identity Migration Implementation Plan

## Material Passport

- Origin Skill: `academic-research-suite / experiment-agent`
- Origin Mode: `plan`
- Origin Date: `2026-08-06`
- Verification Status: `UNVERIFIED`
- Version Label: `stage10_v2_r2_implementation_plan_v2`
- Next Mandatory Gate: explicit implementation-plan approval

**Status:** implementation plan approved for Tasks 0-9; freeze-receipt SHA approval, formal simulation, release evidence, Stage11 migration, commit, and push are not authorized.

**Approved design:** `docs/superpowers/specs/2026-08-06-stage10-v2-r2-source-identity-migration-design.md`

**Approved design SHA256:** `e967307c7cc9c3548424c646ca2c442c01ef738da0995fbda9037044567f3cc2`

**Target contract:** `CAPD-PROACTIVE-STAGE10-2.0`

**Target evidence mode:** `deterministic_async_simulation`

**Target success status:** `stage10_async_simulation_verified`

**Target run id:** `stage10-async-simulator-v2-r2`

## 1. Approval gates and scope

This document is a plan only. Its creation does not authorize source changes, tests, receipt generation, or output creation.

Execution is divided into four non-transitive gates:

1. **Implementation gate:** after explicit approval, Tasks 0-9 may implement and test the r2 contract and produce a repository generation freeze receipt. Task 9 must stop and report the exact receipt SHA.
2. **Freeze approval gate:** the user must explicitly approve that exact receipt SHA. Receipt approval alone does not authorize a simulation run.
3. **Formal-run gate:** after a separate explicit approval, Task 10 may create the unique r2 run and execute the unchanged 60 deterministic scenarios. It must stop after generation verification.
4. **Release gate:** after another explicit approval, Tasks 11-12 may create readiness and final-status evidence. Only all generation and release verifiers together can close Stage10.

An approval of an earlier gate never implies approval of a later gate. If the user narrows an approval, the narrower boundary wins.

No task in this plan authorizes:

- rerunning, rewriting, or repairing Stage9;
- modifying Stage8, Stage9, Stage10A, or v2-r1 output artifacts;
- deleting, overwriting, resuming, or upgrading `stage10-async-simulator-v2-r1`;
- changing Stage9 timing provenance, migration ratios, arrival profiles, scenario matrix, simulator semantics, or result schema;
- Test-based parameter selection, retraining, or checkpoint changes;
- Stage11A positive migration;
- real NVM, real kernel concurrency, real foreground end-to-end latency, or real-system async performance claims;
- automatic commit or push.

## 2. Frozen authority and current baseline

Before any implementation edit, Task 0 must independently verify these bindings:

| Binding | Required value |
| --- | --- |
| Approved r2 design SHA | `e967307c7cc9c3548424c646ca2c442c01ef738da0995fbda9037044567f3cc2` |
| Stage9 byte-recovery audit SHA | `94a68bfccfa6fec3a947b6ed35f83cca04a09bfe708b9390385d7476e0c5bc64` |
| Stage9 run id | `stage9-overhead-v2-r3` |
| Stage9 contract | `CAPD-PROACTIVE-STAGE9-2.0` |
| Stage9 config SHA | `642641d56fe52e3772bdaa0772d5c9fd250cc17976918ce99acd36d18a035922` |
| Stage9 verification SHA | `bc5dc7fc46247da5d2085dd302150361232ff0cd27cd9b911cb559072ef8635f` |
| Stage9 checkpoint SHA | `8ec44db66348aef3c65459ea48a3b87fc417d862102c85b4fe6bda958bf915d3` |
| Stage9 latency-summary SHA | `a4e28f6627b278258202d7ab71db72474f29f9e569ca432ebfc40e36baf12a09` |
| Stage9 artifact map | exactly 19 entries, all recomputed |
| r2 scenario count | exactly 60 |
| r2 production run root | absent before Task 10 |
| r2 release base | absent before Task 11 |

`stage10-async-simulator-v2-r1` is permanently classified outside its saved metadata as:

```text
execution = completed
artifacts = generated_and_self_consistent
current_independent_verification = failed
formal_gate = not_satisfied
evidence_class = candidate_evidence
reason_code = generation_source_identity_lifecycle_conflict
```

Its 60 results, 14 manifest payloads, 15 checksum entries, saved source SHA, and current verifier failure remain read-only diagnostic evidence. Neither r1 numeric equality nor its saved success strings can authorize r2 or Stage11.

Task 0 records path/length/SHA256 tree snapshots for:

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`;
- `outputs/capd_proactive_stage9/stage9-overhead-v2-r3/`;
- `outputs/capd_proactive_stage10/stage10-async-simulator-r1/`;
- `outputs/capd_proactive_stage10/stage10-async-simulator-v2-r1/`.

Implementation-session snapshots belong under ignored temporary storage. They are audit controls, not formal results. Paths are normalized to project-relative POSIX form before fingerprinting.

## 3. Frozen r2 identities

The following values are exact and may not be inferred from r1:

```text
config_schema_version             = capd_proactive_stage10_v2_1
run_identity_schema_version       = capd_proactive_stage10_run_identity_v2_1
run_state_schema_version          = capd_proactive_stage10_run_state_v2_1
verification_schema_version       = capd_proactive_stage10_verification_v2_1
manifest_schema_version           = capd_proactive_stage10_manifest_v2_1
generation_source_manifest_schema = capd_proactive_stage10_generation_source_manifest_v1_0
generation_freeze_receipt_schema  = capd_proactive_stage10_generation_freeze_receipt_v1_0
generation_test_evidence_schema   = capd_proactive_stage10_generation_test_evidence_v1_0
execution_environment_schema      = capd_proactive_stage10_execution_environment_v1_0
release_readiness_receipt_schema  = capd_proactive_stage10_release_readiness_receipt_v1_0
release_test_evidence_schema      = capd_proactive_stage10_release_test_evidence_v1_0
stage11_audit_evidence_schema      = capd_proactive_stage10_stage11_negative_audit_evidence_v1_0
final_status_evidence_schema      = capd_proactive_stage10_final_status_evidence_receipt_v1_0
release_manifest_schema           = capd_proactive_stage10_release_manifest_v1_0
```

The result, scenario-matrix, timing-provenance, and Stage9-input-receipt payload schemas remain v2.0. The contract id is unchanged because simulation semantics are unchanged; the metadata envelope and run id separate r1 from r2.

## 4. File ownership map

### 4.1 Preserve unchanged

- `qmap/proactive_stage10.py`;
- `qmap/proactive_stage10_v2.py`;
- `scripts/run_capd_proactive_stage10_v2.py` as the legacy r1 runner/verifier;
- `tests/stage10_v2_test_support.py`;
- `configs/finals/capd_proactive_stage10_v2.json`;
- `configs/finals/capd_proactive_stage10_result_schema_v2.json`;
- historical Stage10A and v2-r1 design/plan documents;
- all Stage8, Stage9, Stage10A, and v2-r1 outputs;
- all Stage11A source, config, docs, tests, and outputs.

`qmap/proactive_stage10_v2.py` remains the shared v2.0 simulation/audit implementation and is not modified. The r2 adapter imports its existing public behavior without changing r1 constants. Any additional helper belongs in an r2-owned module.

### 4.2 Extend

- `scripts/run_capd_proactive_stage10.py`: add exact r2 dispatch and the conditional approved-SHA CLI input while preserving Stage10A and r1 behavior;
- `tests/test_capd_proactive_stage10_v2.py`: remove all Stage11 imports and assertions, including the current `qmap.proactive_stage11` import in `test_unknown_contract_and_stage11_positive_migration_are_rejected`, and move lifecycle-sensitive documentation assertions out of the generation module; retain Stage10-owned legacy contract/regression coverage;
- `docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md`: first record r1 candidate/r2 pending, then update only at the approved release phase.

### 4.3 Add generation-owned files

- `qmap/proactive_stage10_v2_r2.py`;
- `scripts/run_capd_proactive_stage10_v2_r2.py`;
- `tests/test_capd_proactive_stage10_v2_r2.py`;
- `tests/stage10_v2_r2_test_support.py`;
- `configs/finals/capd_proactive_stage10_v2_r2.json`;
- `configs/finals/capd_proactive_stage10_v2_r2_source_manifest.json`;
- `docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md`.

### 4.4 Add metadata schemas

- `configs/finals/capd_proactive_stage10_v2_r2_config_schema.json`;
- `configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json`;
- `configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json`;
- `configs/finals/capd_proactive_stage10_generation_test_evidence_schema.json`;
- `configs/finals/capd_proactive_stage10_execution_environment_schema.json`;
- `configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json`;
- `configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json`;
- `configs/finals/capd_proactive_stage10_verification_schema_v2_1.json`;
- `configs/finals/capd_proactive_stage10_manifest_schema_v2_1.json`;
- `configs/finals/capd_proactive_stage10_release_test_evidence_schema.json`;
- `configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json`;
- `configs/finals/capd_proactive_stage10_stage11_negative_audit_evidence_schema.json`;
- `configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json`;
- `configs/finals/capd_proactive_stage10_release_manifest_schema.json`.

Each schema has one exact `schema_version`, rejects unknown required-contract substitutions, and is itself SHA-bound by the freeze receipt. The implementation plan may consolidate schemas only through a new design approval; implementation must not silently reduce this file set.

### 4.5 Add release-owned files

- `tests/test_capd_proactive_stage10_v2_release.py`;
- `docs/superpowers/specs/2026-08-06-stage10-v2-r2-generation-freeze.json` after Task 9 only;
- runtime receipts under the approved release roots after Tasks 11-12 only.

The release test module is excluded from generation source-set identity but its exact file SHA, both test-group argv, and Stage11 audit-worker argv are bound directly by the approved freeze receipt.

## 5. Source manifest and dependency closure

The production source manifest uses `source_set_id=stage10-v2-r2-generation-core-v1`. It contains the complete executable/test dependency closure, not merely top-level files.

The minimum entry set is:

```text
qmap/proactive_stage10.py
qmap/proactive_stage10_v2.py
qmap/proactive_stage10_v2_r2.py
scripts/run_capd_proactive_stage10.py
scripts/run_capd_proactive_stage10_v2.py
scripts/run_capd_proactive_stage10_v2_r2.py
tests/test_capd_proactive_stage10.py
tests/test_capd_proactive_stage10_v2.py
tests/test_capd_proactive_stage10_v2_r2.py
tests/stage10_v2_test_support.py
tests/stage10_v2_r2_test_support.py
```

Any other imported repository module used by generation tests or the generation runner path must also be included. Task 9 derives the import/dependency closure and fails if an imported local file is omitted. The closure validator also fails if any generation test, runner path, or local transitive dependency statically imports, dynamically loads, or executes a Stage11-owned module, config, schema, test, or script.

The manifest excludes:

```text
tests/test_capd_proactive_stage10_v2_release.py
tests/test_capd_proactive_stage11.py
qmap/proactive_stage11.py
scripts/run_capd_proactive_stage11.py
configs/finals/capd_proactive_stage11a.json
configs/finals/capd_proactive_stage11a_result_schema.json
docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md
docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md
all other Stage11-owned files, run-after reports, and release artifacts
```

Exclusion from generation identity does not remove approval binding: the freeze receipt separately binds the release-test module SHA, exact release and Stage11-audit commands, schemas, protocol path, approved plan/design hashes, and the Stage11 audit dependency-snapshot policy. Stage11 dependencies are measured only for the readiness audit and never become generation identity.

Every entry contains exact `logical_name`, project-relative POSIX `path`, enumerated `role`, lowercase SHA256, `generation_identity=true`, and exact generation test groups. Entries are byte-sorted by path. Absolute paths, empty components, `.`, `..`, backslashes, duplicates, symlinks, junctions, reparse points, and paths outside the repository fail closed.

## 6. Controlled test command contract

No caller-provided log can authorize r2 execution. The runner launches tests itself with `shell=False`, project root as cwd, and an argv list rather than a command string.

The generation command identity is frozen as:

```text
interpreter_policy = current_runner_sys_executable
argv_suffix =
  -m unittest -v
  tests.test_capd_proactive_stage10
  tests.test_capd_proactive_stage10_v2
  tests.test_capd_proactive_stage10_v2_r2
```

The freeze receipt records each group's exact expected test count and ordered verbose test identities. Execution evidence records the resolved `sys.executable`, exact argv array, cwd, exit code, full log SHA, observed exact test count, unique `Ran N tests`, ordered verbose result identities, and final `OK`; observed and approved values must match exactly.

Immediately before and after the subprocess, the runner recomputes the complete generation source path/SHA map, entry count, and canonical fingerprint. Both snapshots must equal each other and the approved source manifest. The runner writes `generation_test_log.txt` and `generation_test_evidence.json` only after these comparisons pass.

The separately terminable formal-simulation worker command identity is frozen as:

```text
<current_runner_sys_executable>
scripts/run_capd_proactive_stage10_v2_r2.py
--formal-simulation-worker
--config configs/finals/capd_proactive_stage10_v2_r2.json
--stage9-run-root outputs/capd_proactive_stage9/stage9-overhead-v2-r3
--approved-freeze-receipt-sha256 <exact-approved-sha>
```

The worker writes one canonical 60-result simulation bundle to stdout and never creates the production run root. The parent validates the bundle and only the parent writes run artifacts.

The release module is frozen once with two stable class-level commands:

```text
readiness group:
  tests.test_capd_proactive_stage10_v2_release.Stage10V2R2ReadinessDocumentationTest

post-decision group:
  tests.test_capd_proactive_stage10_v2_release.Stage10V2R2FinalStatusDocumentationTest
```

The module supports both document states and the Stage11 audit worker entrypoint without changing its bytes. Its two unittest groups must be self-contained apart from the standard library and generation-owned modules; only the separately invoked audit-worker path may import Stage11. An additional mutable release helper requires a design revision. Each release runner repeats the approved-SHA and generation-source checks, snapshots the release module/protocol/status documents before and after its own subprocess, and generates runner-owned evidence. External logs and receipts are rejected.

The Stage11A audit is a third, independent readiness subprocess, not a unittest group and not generation identity. Its exact frozen argv shape is:

```text
<current_runner_sys_executable>
-m tests.test_capd_proactive_stage10_v2_release
--stage11-negative-audit-worker
--stage10a-run-root outputs/capd_proactive_stage10/stage10-async-simulator-r1
--stage10-r2-run-root outputs/capd_proactive_stage10/stage10-async-simulator-v2-r2
--approved-freeze-receipt-sha256 <exact-approved-sha>
```

The release-owned worker may call only `qmap.proactive_stage11.audit_stage10_fixture` and writes one canonical structured result to stdout; it creates no Stage11 output. The readiness parent snapshots the release module plus the complete local dependency closure actually loaded by this audit, including Stage11-owned files and the dynamically loaded Stage10 verifier dependencies, before and after the subprocess. It seals the command, environment, log, snapshots, and structured result in readiness evidence. Because the release module and audit-only dependency closure are excluded from generation identity, this isolated worker does not make Stage11 a generation dependency.

### 6.1 Timeout, monitoring, and environment contract

The freeze receipt fixes these exact values, which no caller may override:

```text
generation_core_test_timeout_seconds = 1800
formal_simulation_timeout_seconds = 1800
release_readiness_test_timeout_seconds = 600
stage11_negative_audit_timeout_seconds = 600
final_status_test_timeout_seconds = 600
monitor_check_interval_seconds = 30
termination_grace_seconds = 10
automatic_retry_allowed = false
```

Every controlled test, simulation, and audit runs in a separately terminable subprocess with `shell=False` and records process-alive observations every 30 seconds. Output stalls are advisory only. At the hard timeout, the controller requests normal termination, waits 10 seconds, force-terminates the complete process tree if still alive, waits for collection, records `timed_out=true`, and fails closed. It never retries automatically.

Each execution-evidence object records exact argv, cwd, timeout, monitor interval and observations, start/end/duration wall-clock observations, exit/signal or platform equivalent, stdout/stderr SHA256, and:

```text
python_version
python_implementation
python_cache_tag
python_executable
os_name
platform_system
platform_release
platform_version
machine
architecture
required_dependency_versions
dependency_policy
```

`required_dependency_versions` is a path-sorted mapping for every declared non-standard dependency; a standard-library-only path records an empty mapping and `dependency_policy=stdlib_only`. Wall-clock values are observational only and never enter deterministic result equality or performance conclusions.

## 7. TDD execution discipline

Every implementation task follows this order:

1. Add one narrow failing test under the new r2 test module.
2. Run only that test and confirm failure is the missing contract behavior, not malformed fixtures or frozen evidence drift.
3. Implement the minimum behavior.
4. Rerun the narrow test to green.
5. Run all completed r2 test classes plus legacy Stage10A/v2 tests.
6. When filesystem orchestration is exercised, compare the four frozen output-tree snapshots.

All normal implementation tests use `TemporaryDirectory` and synthetic source manifests/run roots. They must not create either production path:

```text
outputs/capd_proactive_stage10/stage10-async-simulator-v2-r2/
outputs/capd_proactive_stage10/release_receipts/stage10-async-simulator-v2-r2/
```

Deterministic payload comparisons require exact numeric and byte equality. Timing metrics from the simulator are deterministic integer values; no tolerance-based substitution is allowed.

## 8. Task 0: Lock approval and baseline evidence

**Files:** plan status only after explicit approval; no production source.

### Checks

- Require the approved design file SHA to equal `e967307c7cc9c3548424c646ca2c442c01ef738da0995fbda9037044567f3cc2`.
- After plan approval, change only this plan status to `implementation plan approved` and compute the final approved-plan SHA.
- Verify the Stage9 recovery audit, both restored newline hashes, and all 19 Stage9 artifact hashes.
- Record the four frozen-tree snapshots from Section 2.
- Confirm Stage10A verifier returns 5 results and 12 manifest payloads.
- Confirm both current v2-r1 verifier entries fail with the recorded lifecycle identity mismatch.
- Confirm the actual Stage10A run returns `status=BLOCKED`, `reason_code=stage10a_fixture_only`, `formal_authorized=false`. Confirm from the current Stage11A source and a `TemporaryDirectory` r2-shaped negative fixture that the future r2 input expectation is `status=NOT_VERIFIABLE`, `reason_code=invalid_stage10a_fixture`, `formal_authorized=false`; diagnostic `detail` is not part of the stable identity. The production r2 path remains absent.
- Confirm production r2/release paths do not exist.

### Gate

Any mismatch stops before source edits. Baseline checks are evidence audits, not authorization to continue beyond the approved task scope.

## 9. Task 1: Implement source-manifest schemas and path validator

**Tests first:** `Stage10V2R2SourceManifestTest`

### Failing tests

- exact schema/source-set/version and complete entry objects pass;
- missing, extra, duplicate, unsorted, or differently cased paths fail;
- absolute path, `..`, `.`, empty component, backslash, path escape, symlink, junction, and reparse point fail;
- duplicate logical name, unknown role/group, invalid SHA, false generation identity, or dependency omission fail;
- any Stage11-owned path, static import, dynamic import target, transitive dependency, or observed generation-time module load fails;
- canonical entry fingerprint has independent fixed vectors;
- modifying a core file without updating the approved manifest fails;
- modifying manifest and all downstream self-reported hashes still fails without the external approved receipt SHA.

### Implementation

Add pure path normalization, entry validation, canonical JSON, fingerprint, and current-source snapshot helpers in `qmap/proactive_stage10_v2_r2.py`. Tests use temporary roots and do not read a caller-supplied production manifest.

### Targeted command after approval

```powershell
python -m unittest -v tests.test_capd_proactive_stage10_v2_r2.Stage10V2R2SourceManifestTest
```

## 10. Task 2: Add the r2 config and metadata-schema contract

**Tests first:** `Stage10V2R2ConfigSchemaTest`

### Failing tests

- all Section 3 identities and `run_id=stage10-async-simulator-v2-r2` are exact;
- the approved design SHA is exact and an approved-plan SHA field is required;
- result schema remains the existing v2.0 schema and its SHA is recomputed;
- Stage9 binding, Decimal timing derivation, three migration ratios, five arrivals, two channels, and 60 scenarios are byte/canonical-equal to r1 semantics;
- `T_inference=2000`, Cost weight 10 as nanoseconds, alternate Stage9 runs, parameter changes, output-root changes, or unknown fields fail;
- config binds source-manifest path/SHA/schema/source-set but does not contain its own SHA;
- execution-environment and Stage11-audit evidence schemas require every frozen timeout/environment/snapshot field and reject unknown substitutions;
- metadata schemas reject schema swaps, run-id swaps, evidence-mode swaps, missing interpretation boundaries, and additional unrecognized status fields.

### Implementation

Create strict structured validators and r2 identity constants in the r2 adapter. During Tasks 2-8, tests construct temporary canonical configs and manifests. The production manifest/config are finalized only in Task 9 after source bytes stop changing.

### Semantic regression

Build r1 and r2 scenario definitions from the same audited Stage9 fixture and require canonical equality for timing profiles, arrival bindings, scenario ids, event streams, and result rows. Any result difference is an unintended semantics change and blocks implementation.

## 11. Task 3: Implement controlled generation-test execution

**Tests first:** `Stage10V2R2ControlledGenerationTestTest`

### Failing tests

- the runner validates the explicit approved receipt SHA before launching tests;
- missing, malformed, uppercase, duplicate, wrong, repository-mismatched, or run-copy-mismatched SHA fails;
- the runner launches only the frozen argv with `shell=False` and project-root cwd;
- generation tests use the frozen 1800-second timeout, 30-second monitor interval, 10-second termination grace, and no automatic retry;
- timeout records the exact timeout/process-tree termination state, fails closed before production `mkdir`, and cannot be caller-overridden;
- execution evidence records the complete environment object and sorted dependency-version policy;
- caller log/evidence input options do not exist and cannot authorize execution;
- a correct-looking log from another source revision fails;
- source mutation during the subprocess or any observed Stage11 module load fails through unequal pre/post snapshots or the generation isolation check;
- command/module substitution, nonzero exit, empty log, duplicate `Ran`, wrong exact count, missing verbose identity, or non-final `OK` fails;
- rehashing a forged evidence object with mismatched snapshots still fails;
- a successful temporary execution produces byte-stable runner-owned log/evidence.

### Implementation

Implement an injectable subprocess boundary for synthetic tests, but the production path must always use `sys.executable` and the frozen argv. It must use a separately terminable process group/tree, monitor every 30 seconds, enforce the frozen hard timeout and 10-second grace, collect timeout/stderr/environment evidence, and never retry. The temporary evidence is held outside the production output root until all preflight checks pass.

## 12. Task 4: Implement complete v2.1 metadata construction

**Tests first:** `Stage10V2R2MetadataContractTest`

### Required objects

- `run_identity.json`;
- `verification.json`;
- `run_state.json`;
- `execution_environment.json`;
- generation manifest and `SHA256SUMS`.

### Failing tests

- verifier constructs the complete expected object and compares full equality for every metadata payload;
- run identity includes source-manifest schema/SHA/source-set/fingerprint/count, `approved_freeze_receipt_sha256`, repository/run-copy receipt SHA, and generation-test evidence SHA;
- run identity also binds `execution_environment.json` and the frozen timeout contract;
- verification repeats the independent bindings and requires current-source recomputation, controlled-test verification, and complete environment/timeout verification;
- run state uses only the exact r2 identity/status/evidence fields;
- generation Git identity binds the exact HEAD commit plus approved source-manifest fingerprint, not a repository-wide dirty bit or mutable non-generation file list;
- docs/release-only worktree changes leave expected generation identity unchanged, while any generation-source byte change fails;
- internal self-hash excludes only its own declared field and uses fixed canonical vectors;
- any field deletion, addition, schema change, provenance SHA change, status change, or interpretation change fails after all self-hashes/manifests/checksums are recomputed;
- source manifest and freeze receipt are present in the run manifest/checksum chain;
- extra or missing files fail.

### Implementation

Use pure expected-object builders shared by generation and verification. Saved metadata is never used as the template for expected metadata.

## 13. Task 5: Implement the r2 native runner lifecycle

**Tests first:** `Stage10V2R2RunnerLifecycleTest`

### Failing tests

- all approved-SHA, config, schema, source, Stage9, and test preflight checks occur before `mkdir`;
- Stage9 gate pass alone cannot create a success state;
- target run id and output root are exact and cannot be overridden;
- existing target rejects overwrite, resume, append, or alternate run id;
- successful temporary run executes exactly 60 unchanged scenarios and writes the exact artifact set;
- formal simulation runs in a separately terminable worker subprocess with the frozen 1800-second timeout, 30-second monitoring, 10-second grace, no retry, and a recorded environment object;
- a worker timeout after run creation preserves exact timeout/environment failure evidence and `stage10_async_simulation_not_verified`;
- post-creation failure preserves `stage10_async_simulation_not_verified` and never deletes/reuses the run id;
- v2-r1 config/run/schema cannot enter r2 code paths;
- manifest/checksum/result/metadata can be independently recomputed byte-for-byte.

### Implementation

Create `scripts/run_capd_proactive_stage10_v2_r2.py` with separated pure/preflight/write/verify functions. It reuses audited v2 simulation helpers but constructs only v2.1 metadata. Atomic file writes use sibling temporary files and `os.replace`; the run directory itself is unique and immutable after creation.

The production run file set is exact:

```text
config.json
event_model.md
execution_environment.json
generation_freeze_receipt.json
generation_source_manifest.json
generation_test_evidence.json
generation_test_log.txt
parameters.md
README.md
report.md
run_identity.json
run_state.json
scenario_matrix.json
simulation_results.jsonl
stage9_input_receipt.json
timing_provenance.json
verification.json
manifest.json
SHA256SUMS
```

The first 17 files are manifest payloads. `SHA256SUMS` includes `manifest.json` and excludes itself, for 18 checksum entries and 19 total files.

`execution_environment.json` contains exactly the generation-test and formal-simulation-worker environment/execution objects. It records their frozen timeout values, timeout outcome, monitor observations, termination outcome, dependency policy, and observational wall-clock fields; verifier equality excludes only wall-clock observations from deterministic result comparison, not from artifact integrity or schema validation.

All Task 5 runs use temporary output roots. Production r2 remains absent.

## 14. Task 6: Implement exact v1 dispatcher routing

**Tests first:** `Stage10V2R2DispatchTest`

### Failing tests

- Stage10A still routes to `verify_v1_fixture_run` without an r2 approved SHA;
- v2-r1 still routes to the legacy verifier and its current failure remains visible;
- v2-r2 routes only to the r2 native verifier;
- v2-r2 dispatch requires `--approved-freeze-receipt-sha256` and forwards the exact external value;
- unknown contract, config schema, run-identity schema, run-id swap, or mixed r1/r2 metadata fails before interpretation;
- r2 native verifier rejects Stage10A and v2-r1 in both directions;
- dispatcher/generation tests contain no Stage11 import or assertion; r2 remains non-authorizing to Stage11 by contract, but that runtime result is checked only by the independent readiness audit.

### Implementation

Extend `scripts/run_capd_proactive_stage10.py` without changing Stage10A behavior. Dispatch uses the tuple `contract_id + run_id + config schema + run-identity schema`, not contract id alone.

## 15. Task 7: Implement Phase A release readiness

**Tests first:** `Stage10V2R2ReleaseReadinessTest`

### Failing tests

- readiness creation and verification both require the exact external approved SHA;
- current generation core, repository receipt, and run-copy receipt are recomputed before release tests;
- the release test module SHA equals the freeze receipt binding;
- pending status snapshot states r1 candidate, r2 generation verified, and external completion pending;
- readiness runner executes only the frozen readiness class and records pre/post release-source snapshots;
- the release unittest classes do not load Stage11; readiness separately executes only the frozen release-owned Stage11 audit-worker argv;
- Stage11 audit pre/post snapshots cover its complete actual local dependency closure and match within the audit; it creates no Stage11 output;
- the Stage11A audit result must equal the exact Stage10A triple `BLOCKED / stage10a_fixture_only / false` and r2 triple `NOT_VERIFIABLE / invalid_stage10a_fixture / false`; any other status, reason, or authorization fails;
- readiness test and Stage11 audit enforce their frozen 600-second timeouts, 30-second monitoring, 10-second grace, no retry, and complete environment evidence;
- caller log, changed test module, protocol/status mutation during execution, wrong count/command/module, or forged receipt fails;
- receipt binds the full r2 run chain, both generation-verifier results, Stage9 19/19, Stage10A 5/12, the two exact Stage11A audit triples, Stage11 dependency snapshots, frozen trees, and real-system false boundary;
- verifier independently returns `stage10_release_readiness_verified` and only then `approved_for_status_finalization`;
- readiness cannot require or claim a completed final status.

### Implementation

Implement readiness create/verify modes in the r2 runner using temporary release roots. The runner invokes the frozen release-owned audit-worker command, parses its sole canonical JSON result, validates both exact triples, and seals the independently recomputed dependency snapshots and environment evidence. Do not modify the r2 run root or create any Stage11 output. Phase A production creation remains blocked until Task 11 approval.

The readiness file set is exact:

```text
release_readiness_test_log.txt
release_test_source_snapshot.py
protocol_pending_snapshot.md
status_pending_snapshot.md
release_readiness_test_evidence.json
stage11_negative_audit_log.txt
stage11_negative_audit_source_snapshot.json
stage11_negative_audit_result.json
stage11_negative_audit_evidence.json
release_readiness_receipt.json
manifest.json
SHA256SUMS
```

The first 10 files are manifest payloads. `SHA256SUMS` contains `manifest.json` and excludes itself, for 11 checksum entries and 12 total files.

## 16. Task 8: Implement Phase B final-status evidence

**Tests first:** `Stage10V2R2FinalStatusTest`

### Failing tests

- Phase B rejects a missing, failed, wrong-run, wrong-SHA, or unverified readiness receipt;
- final status cannot be sealed before `approved_for_status_finalization`;
- final-status runner executes only the frozen post-decision class;
- final-status tests enforce the frozen 600-second timeout, 30-second monitoring, 10-second grace, no retry, and complete environment evidence;
- release module/protocol/final-status pre/post snapshots must match exactly;
- official status records the already-made completion decision and fixed receipt path, not a self-fulfilling future receipt result;
- final receipt binds readiness receipt/manifest/checksums and verifier command/exit/status;
- from readiness creation through final-status sealing, current Stage11 audit dependencies must still equal the readiness snapshot; drift before sealing fails closed;
- changed/rehashed receipt, phase-order swap, source mutation, or document mutation fails;
- Phase B failure preserves failure evidence and cannot alter r2 or Phase A;
- successful temporary final verifier returns `stage10_final_status_evidence_verified`;
- after final-status sealing, future Stage11 or document drift is informational only for sealed Stage11/document snapshots, while generation-core drift remains fail closed.

### Implementation

Implement final-status seal/verify modes and the two release manifest/checksum contracts. The two production subdirectories are unique and cannot be resumed or overwritten.

The final-status file set is exact:

```text
final_status_test_log.txt
release_test_source_snapshot.py
protocol_final_snapshot.md
status_final_snapshot.md
final_status_test_evidence.json
final_status_evidence_receipt.json
manifest.json
SHA256SUMS
```

## 17. Task 9: Finalize repository artifacts and freeze candidate

Execute only if the implementation approval includes freeze-receipt generation.

### 9.1 Documentation state

- Move the current lifecycle-sensitive documentation assertions and every Stage11 import/assertion out of `tests/test_capd_proactive_stage10_v2.py`; generation tests must have no static, dynamic, or transitive Stage11 dependency.
- Add the stable two-group release test module.
- Update the status document truthfully to r1 candidate / r2 implementation complete / formal r2 run not authorized.
- Add the r2 protocol with external-SHA, controlled-test, two-phase release, fail-closed, and interpretation boundaries.

### 9.2 Full implementation verification

Run the complete generation suite from Section 6 and require exact success. Separately run release-contract unit tests and controlled Stage11-audit fixtures using temporary roots. Recompute Stage9 19/19 and all four frozen trees. Run legacy Stage10A verification and confirm v2-r1 remains candidate/failing rather than upgraded. Confirm generation source/import/module-load closure contains no Stage11-owned dependency.

### 9.3 No-cycle freeze order

After all generation-owned source bytes are final:

```text
final generation core bytes
  -> canonical generation source manifest
  -> final r2 config
  -> generation freeze receipt
  -> report exact receipt SHA and stop
```

The production source manifest is generated from the exact approved entry set and dependency closure. The r2 config then binds the manifest SHA/fingerprint/count and all frozen semantic values. Finally create:

`docs/superpowers/specs/2026-08-06-stage10-v2-r2-generation-freeze.json`

It binds:

- approved design path/SHA;
- approved implementation-plan path/final SHA;
- r2 config path/SHA;
- source-manifest path/SHA/fingerprint/count;
- result schema and every metadata schema path/SHA;
- release-test module and r2 protocol path/SHA;
- exact generation/formal-simulation-worker/readiness/post-decision argv identities, expected test counts, and ordered verbose test identities;
- exact Stage11 negative-audit worker argv, expected Stage10A/r2 result triples, and dependency-snapshot policy;
- generation `1800`, formal simulation `1800`, readiness `600`, Stage11 audit `600`, final-status `600`, monitor interval `30`, termination grace `10`, and `automatic_retry_allowed=false`;
- execution-environment schema, required fields, declared non-standard dependency names, and standard-library-only policy;
- Stage9 authority and recovery-audit bindings;
- `formal_run_authorized_at_receipt_creation=false` and `release_authorized_at_receipt_creation=false` as immutable creation-time facts.

The receipt must not bind its own SHA. The implementation report computes its file SHA externally and asks the user to approve that exact value.

### Mandatory stop

At Task 9 completion:

- production r2 run root must still be absent;
- production release base must still be absent;
- no formal result status may be claimed;
- report tests, file changes, source-manifest fingerprint, config SHA, receipt SHA, Stage9/frozen-tree audits, and no commit/push;
- wait for explicit approval of the exact freeze-receipt SHA.

## 18. Freeze approval gate

The user approval must name the exact SHA from Task 9. Every later command receives it through:

```text
--approved-freeze-receipt-sha256 APPROVED_FREEZE_RECEIPT_SHA256
```

Missing, malformed, uppercase, stale, or different values fail closed. Repository/run-copy fields may record the same value but cannot substitute for this external argument.

After freeze approval, stop again unless the user also separately authorizes Task 10 formal execution.

## 19. Task 10: Create and verify the formal r2 run

Execute only after both exact freeze-SHA approval and separate formal-run approval.

### Preconditions

- approved design, approved plan, config, source manifest, schemas, and receipt all match their frozen SHA values;
- current generation source snapshot equals the approved manifest;
- Stage9 r3 still passes its complete 19-artifact and structured gate;
- all four frozen trees match Task 0;
- production r2 path does not exist;
- HEAD and every generation-source byte required by the receipt are unchanged; repository-wide dirty state is observational and cannot replace the source manifest;
- no caller test log is accepted.
- every controlled command uses the frozen timeout/monitoring/no-retry/environment contract.

### Command shape

```powershell
$approvedFreezeSha = 'APPROVED_FREEZE_RECEIPT_SHA256'
python scripts\run_capd_proactive_stage10_v2_r2.py `
  --run `
  --config configs\finals\capd_proactive_stage10_v2_r2.json `
  --stage9-run-root outputs\capd_proactive_stage9\stage9-overhead-v2-r3 `
  --output-root outputs\capd_proactive_stage10 `
  --run-id stage10-async-simulator-v2-r2 `
  --approved-freeze-receipt-sha256 $approvedFreezeSha
```

The runner first validates the external SHA and current source, executes the fixed generation tests itself under the frozen controlled-execution contract, checks source snapshots before/after tests, and only then creates the run root and launches the 60-scenario simulation in a separately terminable worker under its frozen controlled-execution contract.

### Independent verification

```powershell
python scripts\run_capd_proactive_stage10.py `
  --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r2 `
  --approved-freeze-receipt-sha256 $approvedFreezeSha

python scripts\run_capd_proactive_stage10_v2_r2.py `
  --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r2 `
  --approved-freeze-receipt-sha256 $approvedFreezeSha
```

Expected generation evidence is exactly 60 deterministic results with v2.1 metadata, runner-owned generation test evidence, `execution_environment.json`, complete source/receipt/timeout bindings, independently recomputed manifest/checksums, and all real-system verification fields false. Wall-clock observations are not compared as deterministic payload results and cannot support a performance claim.

### Failure rule and stop

Preflight failure creates no run root. Failure after creation preserves `stage10_async_simulation_not_verified`; the r2 run id cannot be deleted, resumed, overwritten, or reused. A failed r2 requires a new design/run id.

After both generation verifiers, stop and report. Do not update the official status to completed and do not create release evidence without the release gate.

## 20. Task 11: Create and verify readiness evidence

Execute only after explicit release authorization.

First update the official status document to the truthful pending snapshot: r1 candidate, r2 generation verified, Stage10 external completion pending release evidence. Then run:

```powershell
python scripts\run_capd_proactive_stage10_v2_r2.py `
  --create-release-readiness outputs\capd_proactive_stage10\stage10-async-simulator-v2-r2 `
  --approved-freeze-receipt-sha256 $approvedFreezeSha

python scripts\run_capd_proactive_stage10_v2_r2.py `
  --verify-release-readiness outputs\capd_proactive_stage10\release_receipts\stage10-async-simulator-v2-r2\readiness `
  --approved-freeze-receipt-sha256 $approvedFreezeSha
```

Expected verifier status:

```text
release_status = stage10_release_readiness_verified
completion_decision = approved_for_status_finalization
```

This decision authorizes only the official status update required by Task 12. It does not alone close Stage10.

Readiness must additionally seal and verify the independent Stage11 audit with these exact stable results:

```text
Stage10A: status=BLOCKED, reason_code=stage10a_fixture_only, formal_authorized=false
Stage10 r2: status=NOT_VERIFIABLE, reason_code=invalid_stage10a_fixture, formal_authorized=false
stage11_positive_migration_authorized=false
```

The audit `detail` field is diagnostic only and is excluded from the stable expected identity. The audit is read-only, creates no Stage11 output, and its command, log, structured result, environment, timeout state, and complete Stage11 dependency pre/post snapshot are bound by readiness evidence.

## 21. Task 12: Seal and verify final-status evidence

Execute only after Task 11 independently returns `approved_for_status_finalization`.

Update the official status document to record that decision and the fixed final-status receipt path. It must not claim a future receipt verification as already observed. Then run:

```powershell
python scripts\run_capd_proactive_stage10_v2_r2.py `
  --seal-final-status outputs\capd_proactive_stage10\release_receipts\stage10-async-simulator-v2-r2\readiness `
  --approved-freeze-receipt-sha256 $approvedFreezeSha

python scripts\run_capd_proactive_stage10_v2_r2.py `
  --verify-final-status outputs\capd_proactive_stage10\release_receipts\stage10-async-simulator-v2-r2\final-status `
  --approved-freeze-receipt-sha256 $approvedFreezeSha
```

After final-status verification:

- rerun v1 dispatcher and native r2 generation verifiers with the same external SHA;
- rerun Stage10A verification and verify the sealed Stage11A negative-audit evidence; current post-seal Stage11 drift is informational and does not replace the sealed result;
- recompute Stage9 19/19;
- compare all frozen trees;
- independently recompute both release manifests/checksums;
- run the full regression suite, `git diff --check`, and whitespace checks for untracked files;
- do not commit or push.

Stage10 external completion requires all of:

```text
r2 run_state.status = stage10_async_simulation_verified
r2 verification.status = stage10_async_simulation_verified
v1 dispatcher generation verification = passed
r2 native generation verification = passed
readiness verification = stage10_release_readiness_verified
final-status verification = stage10_final_status_evidence_verified
```

Any missing or failed item leaves the formal gate open, even if simulation execution or artifact generation occurred.

## 22. Negative-test matrix

The combined r2 tests must cover at least:

- manifest missing/extra/duplicate/unsorted entries and dependency omission;
- any Stage11-owned generation path, static/dynamic/transitive dependency, or observed generation-time Stage11 module load;
- absolute/escaping/backslash paths, symlink/junction/reparse point, and role/group tamper;
- source, manifest, config, schema, receipt, run-copy, and approved-CLI SHA mismatch;
- missing/malformed/uppercase/wrong approved SHA at every r2 runner/verifier/release entry;
- caller-supplied logs/evidence and logs from another source revision;
- generation and release source mutation during subprocess execution;
- Stage11 audit dependency-closure omission, path escape, pre/post SHA/fingerprint change, or Stage11 output creation;
- Stage11 audit result tamper, including any Stage10A triple other than `BLOCKED / stage10a_fixture_only / false`, any r2 triple other than `NOT_VERIFIABLE / invalid_stage10a_fixture / false`, or any positive authorization;
- command/module substitution, nonzero exit, wrong exact count, duplicate `Ran`, and non-final `OK`;
- missing or caller-overridden frozen timeout, timeout without fail-closed state, failed process-tree collection, or any automatic retry;
- missing/malformed environment fields, dependency-version substitution, environment-object rehash tamper, and use of wall-clock values in deterministic equality or performance claims;
- pre/post snapshot tamper followed by complete rehashing;
- complete run identity, verification, and run-state tamper followed by self-hash/manifest/checksum rehashing;
- r1/r2 config, schema, run-id, and verifier swaps;
- Stage9 old runs, missing checkpoint, newline-byte changes, and 19-map tamper;
- any semantic change to timing, migration ratios, arrivals, channels, scenario ids, event streams, or result rows;
- readiness before generation verification, final status before readiness decision, and cyclic completed-state requirements;
- release receipt wrong run/phase/source/status binding and overwrite attempts;
- docs/Stage11 post-seal informational drift behavior versus generation-core fail-closed drift;
- failed preflight creating no production path and post-creation failure preserving immutable failure evidence;
- Stage10A 5/12, the exact two Stage11A negative triples, Stage9 19/19, and all frozen trees unchanged.

## 23. Failure handling

- **Implementation test failure:** fix only the approved r2 surface; do not adjust upstream evidence or simulation parameters.
- **Source closure failure:** add the real dependency to the manifest; never weaken closure checks.
- **Approved SHA failure:** stop and request a new explicit approval; never infer or auto-adopt a changed receipt.
- **Stage9 failure:** report exact path/field/SHA and stop; do not normalize bytes or edit Stage9.
- **Run preflight failure:** create no production directory.
- **Run post-creation failure:** preserve the immutable failed r2 run and require a new design/run id.
- **Controlled-execution timeout:** record timeout, monitoring, termination, environment, and stderr evidence; never retry automatically. Before production `mkdir`, create no production path; after creation, preserve immutable failure evidence.
- **Stage11 audit failure:** preserve readiness failure evidence, create no Stage11 output, and do not weaken the exact expected triples or add Stage11 to generation identity.
- **Readiness/final-status failure:** preserve that failed release directory; do not alter the generation run or earlier release phase.
- **Frozen-tree difference:** stop before any subsequent gate.
- **Unknown lifecycle conflict:** fail closed and return to design review.

## 24. Final handoff requirements

Reports must separate:

1. implementation and unit-test status;
2. approved freeze receipt and source identity;
3. Stage9 input-gate evidence;
4. r2 deterministic simulation execution and generation verification;
5. readiness and final-status evidence;
6. unsupported real-system conclusions;
7. sealed Stage11A exact negative compatibility results and any later informational drift;
8. exact modified/new files and confirmation of no commit/push.

Before Task 10, formal metrics are `N/A`. Between Task 10 and Task 12, simulation may be executed and generation-verified but Stage10 external completion remains pending. Only after Task 12 may the report say “Stage10 deterministic asynchronous simulation verified,” and it must still state that real-system asynchronous performance is not verified.

## 25. Plan self-review checklist

- [x] The plan binds the final approved-design SHA, not the pending-design SHA.
- [x] r1 remains immutable candidate evidence and cannot authorize r2.
- [x] r2 uses a new run id and v2.1 metadata without changing simulation semantics.
- [x] The source manifest contains executable and test dependency closure with strict path rules.
- [x] Generation source/import/module-load closure explicitly rejects every Stage11-owned dependency.
- [x] The external approved freeze SHA is mandatory at the runner, dispatcher, native verifier, readiness, and final-status entries.
- [x] Saved receipt fields are evidence records, not the external trust anchor.
- [x] Generation and release tests are runner-owned and bind exact pre/post source snapshots.
- [x] Stage11A uses a separate readiness-only controlled audit with exact Stage10A/r2 result triples and independent dependency snapshots.
- [x] Generation, simulation, readiness, Stage11 audit, and final-status subprocesses freeze timeout, 30-second monitoring, 10-second termination grace, no retry, and complete environment evidence.
- [x] Caller-provided valid-looking logs cannot authorize production work.
- [x] The release test module supports both phases without post-freeze byte changes.
- [x] Readiness, status-finalization decision, official-status update, and final-status seal form an acyclic lifecycle.
- [x] Production config/source manifest/freeze receipt follow the no-hash-cycle order.
- [x] Freeze approval, formal run, and release evidence each retain separate explicit gates.
- [x] Stage9 19/19, Stage10A, v2-r1, and frozen directories remain read-only.
- [x] Stage11A remains negative-only, creates no output during audit, and requires a later independent migration design; post-seal Stage11 drift is informational.
- [x] No real-system async performance claim is introduced.
- [x] This plan does not execute implementation, tests, receipts, simulations, release, commit, or push.

Self-review conclusion: the plan is ready for implementation-plan review. It is not implementation authorization until explicitly approved.
