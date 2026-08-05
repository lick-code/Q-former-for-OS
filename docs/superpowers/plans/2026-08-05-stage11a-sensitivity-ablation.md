# CAPD Stage11A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a standalone CAPD Stage11A contract, runner, offline cost recomputation, synchronous candidate interfaces, and fail-closed Stage9/Stage10A gates without creating formal Stage9/Stage10 evidence.

**Architecture:** Add one Stage11-owned pure contract module and one CLI runner. The pure module validates the Stage11 config, joins Stage8 CSV rows to per-job manifests/results, delegates frozen cost arithmetic to `qmap.proactive_cost`, expands pre-frozen grids, validates Stage9's schema/artifact-SHA contract, and recognizes only the current Stage10A fixture as blocked. The runner performs global Stage8/config/output preflight, creates an isolated Stage11 run, executes independent lanes, writes provenance and reports, and independently verifies its own artifacts.

**Tech Stack:** Python 3 standard library, existing `qmap.proactive_cost` and `qmap.proactive_stage8_contract`, `unittest`, strict JSON/CSV, SHA256, PowerShell for local verification, Bash commands only as a non-executed Linux handoff.

---

## Approval And Scope Boundary

This document is an implementation plan only. Do not execute any task until the user chooses an execution style. This approval does not authorize a formal Stage11 experiment, Stage9 Linux measurement, Stage10B implementation, server execution, checkpoint changes, Test-based selection, commit, or push.

The following trees are read-only throughout implementation and verification:

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`
- `outputs/capd_proactive_stage9/stage9-overhead-r1/`
- frozen Stage4/7 checkpoint directories referenced by the Stage8 r5 authority.

The implementation may create only new Stage11 code/config/tests/docs and new runs below `outputs/capd_proactive_stage11/`. Local tests use synthetic fixtures and temporary directories. They must not use fixture data as formal evidence.

No commit commands are included. The worktree may remain with the new design and plan documents untracked until the user separately requests repository integration.

## File Map

- Create `qmap/proactive_stage11.py`: immutable Stage11 records, strict config/result validation, Stage8 job join, grid expansion, cost recomputation adapter, Stage9 gate, Stage10A fixture gate, hashing, null/report formatting.
- Create `scripts/run_capd_proactive_stage11.py`: CLI, global preflight, isolated run lifecycle, lane orchestration, result/report writers, Stage11 manifest/checksum writer, and independent verifier.
- Create `configs/finals/capd_proactive_stage11a.json`: independent Stage11A resolved configuration. Offline cost recomputation is enabled; synchronous execution is disabled until an explicit numeric watermark/label grid is supplied and approved.
- Create `configs/finals/capd_proactive_stage11a_result_schema.json`: Stage11A result, evidence status, run-state, provenance, nullability, and artifact contract.
- Create `tests/test_capd_proactive_stage11.py`: unit and integration tests for every Stage11A contract and fail-closed boundary.
- Create `tests/fixtures/stage11a/README.md`: fixture provenance statement and a map of generated fixture shapes; fixtures are never formal evidence.
- Create `docs/CAPD_PROACTIVE_STAGE11A_PROTOCOL_CN.md`: executable semantics, input join, cost profiles, grid rules, and interpretation boundary.
- Create `docs/CAPD_PROACTIVE_STAGE11A_STATUS_CN.md`: implemented/candidate-ready/blocked status and current non-conclusions.
- Create `docs/CAPD_PROACTIVE_STAGE11A_SERVER_CN.md`: copyable future Linux commands for Stage9/Stage10 gate checks only; explicitly state that commands are not executed locally or on the server in this task.
- Do not modify Stage8/Stage9/Stage10 runners, schemas, configs, result directories, or frozen checkpoints.

## Task 1: Capture Immutable Baselines And Add Failing Contract Tests

**Files:**

- Create: `tests/test_capd_proactive_stage11.py`
- Create: `tests/fixtures/stage11a/README.md`
- Create during execution only: `tmp/stage11a-frozen-before.json` (untracked verification state, not a result)

- [ ] **Step 1: Record the frozen trees before code edits**

Run this PowerShell snapshot before implementation changes:

```powershell
$frozenRoots = @(
  'outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit',
  'outputs/capd_proactive_stage9/stage9-overhead-r1'
)
$rows = foreach ($rootName in $frozenRoots) {
  $resolved = (Resolve-Path -LiteralPath $rootName).Path
  Get-ChildItem -LiteralPath $resolved -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
      [ordered]@{
        root = $rootName
        relative_path = $_.FullName.Substring($resolved.Length + 1).Replace('\', '/')
        length = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower()
      }
    }
}
$rows | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 'tmp/stage11a-frozen-before.json'
```

Expected: the command reads both trees and writes only the temporary snapshot.

- [ ] **Step 2: Write failing tests for the public Stage11A interfaces**

Start the test module with repository-root imports and these signatures:

```python
from qmap import proactive_stage11 as stage11


class Stage11ConfigTest(unittest.TestCase):
    def test_config_contract_is_independent_and_has_four_profiles(self):
        config = load_json(CONFIG_PATH)
        stage11.validate_config(config)
        self.assertEqual(config["contract_id"], "CAPD-PROACTIVE-STAGE11A-1.0")
        self.assertEqual(config["cost_profiles"]["default"]["weights"],
                         {"dram_hit": 1, "nvm_read": 2,
                          "nvm_write": 8, "demotion": 10})


class Stage11OfflineTest(unittest.TestCase):
    def test_job_join_rejects_missing_result_sha(self):
        with self.assertRaises(stage11.Stage11ContractError):
            stage11.load_stage8_rows(self.fixture_root)


class Stage11GateTest(unittest.TestCase):
    def test_stage10_fixture_is_blocked_not_formally_verified(self):
        receipt = stage11.audit_stage10_fixture(self.stage10_fixture)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["formal_authorized"])
```

Add tests for empty input, missing fields, tampered result bytes, and the distinction between global preflight failure and lane-local gate failure. Do not call the real runner against Stage8 output in these tests.

- [ ] **Step 3: Run the focused tests and confirm they fail for missing Stage11 code**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11 -v
```

Expected: FAIL because `qmap.proactive_stage11` and the Stage11 config/schema do not exist yet. No Stage11 output directory is created.

- [ ] **Step 4: Add the fixture provenance note**

Write `tests/fixtures/stage11a/README.md` with these exact boundaries: fixture data is synthetic, fixture status is never formal, fixture Stage9/Stage10 directories test parser behavior only, and no fixture SHA can authorize a server measurement or paper claim.

## Task 2: Define The Stage11A Config And Result Schema

**Files:**

- Create: `configs/finals/capd_proactive_stage11a.json`
- Create: `configs/finals/capd_proactive_stage11a_result_schema.json`
- Modify: `tests/test_capd_proactive_stage11.py`

- [ ] **Step 1: Add config/schema contract tests**

Test the following before writing implementation values:

```python
def test_missing_numeric_values_are_null_in_json_contract(self):
    schema = load_json(SCHEMA_PATH)
    self.assertEqual(schema["null_numeric_representation"], "null")
    self.assertEqual(schema["report_missing_numeric_representation"], "N/A")


def test_main_b_max_is_immutable_and_sensitivity_is_analysis_only(self):
    config = load_json(CONFIG_PATH)
    self.assertEqual(config["main_control"]["b_max"], 2)
    self.assertEqual(config["sensitivity_grid"]["b_max"], [1, 2, 4])
    self.assertTrue(config["sensitivity_grid"]["analysis_only"])


def test_ablation_interfaces_are_blocked_until_pairwise_training_receipts_exist(self):
    config = load_json(CONFIG_PATH)
    self.assertEqual(config["input_ablation"]["status"], "BLOCKED")
    self.assertEqual(config["input_ablation"]["variants"], [
        "CAPD-Full", "CAPD-NoVPN", "CAPD-NoContext", "CAPD-NoPageState"])
```

Test that the config contains the four exact cost profiles, explicit NVM-write and demotion semantics, 20/40/60 capacity fractions, all requested parameter-record fields, `execution_authorized=false`, and no unapproved watermark or label-weight candidate values.

- [ ] **Step 2: Write the independent JSON config**

The config must include:

```json
{
  "schema_version": "capd_proactive_stage11a_config_v1_0",
  "contract_id": "CAPD-PROACTIVE-STAGE11A-1.0",
  "stage8_authority_path": "outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit",
  "main_control": {"b_max": 2, "label_weights": [1, 1, 2]},
  "cost_profiles": {
    "read_light": {"weights": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 4, "demotion": 8}},
    "default": {"weights": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 10}},
    "write_expensive": {"weights": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 12, "demotion": 10}},
    "migration_expensive": {"weights": {"dram_hit": 1, "nvm_read": 2, "nvm_write": 8, "demotion": 20}}
  },
  "sensitivity_grid": {
    "b_max": [1, 2, 4],
    "capacity_working_set_fraction": [0.2, 0.4, 0.6],
    "watermark_candidates": [],
    "label_weight_candidates": [],
    "analysis_only": true,
    "grid_frozen": false,
    "execution_authorized": false
  },
  "input_ablation": {
    "status": "BLOCKED",
    "variants": ["CAPD-Full", "CAPD-NoVPN", "CAPD-NoContext", "CAPD-NoPageState"],
    "checkpoint_selection": "future_separately_approved_validation_only"
  },
  "batch_ablation": {
    "variants": ["Proactive-CAPD-Top-1", "Proactive-CAPD-Top-b"],
    "only_changed_parameter": "selection_count"
  },
  "external_gates": {
    "stage9_run_root": null,
    "stage10_run_root": null,
    "stage10_contract_version": "stage10a_fixture_only"
  }
}
```

`watermark_candidates` and `label_weight_candidates` remain empty until a later approved config explicitly enumerates integer candidates; the runner must reject synchronous execution while they are empty. The cost profile names map to the required weight tuples; the default profile is `1:2:8:10`.

- [ ] **Step 3: Write the result schema**

Define required row identity and provenance fields: `run_id`, `row_id`, `source_job_id`, source result/semantic SHAs, `lane`, `evidence_status`, `evidence_mode`, `grid_cell_id`, `frozen_grid_sha256`, track/workload/seed, policy/ablation, controls, raw counters, `raw_access_count`, weighted cost, input/config/code SHAs, and `null_numeric_representation`. Define evidence statuses as `implemented`, `candidate-ready`, `formally_verified`, `BLOCKED`, and `NOT_VERIFIABLE`; reserve `formally_verified` as vocabulary but reject it in Stage11A v1.0 run-state validation.

Define the run artifact list and the Stage11 manifest rule: `stage11a_manifest.json` excludes itself and `SHA256SUMS`; `SHA256SUMS` includes the manifest and excludes itself. Numeric result properties accept JSON `null`; report renderers convert null to `N/A`.

- [ ] **Step 4: Implement strict config/schema loading**

Implement `validate_config(value)` and `validate_result_row(value)` in `qmap/proactive_stage11.py`. Reject duplicate JSON keys, non-finite numbers, unknown cost profiles, negative counters, a main `b_max` other than 2, `grid_frozen=false` for sync mode, and any input-ablation row that claims `candidate-ready` or `formally_verified`.

- [ ] **Step 5: Run the contract tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11ConfigTest -v
```

Expected: all config/schema tests PASS; no output run is created.

## Task 3: Implement Stage8 Job-Join And Offline Cost Recompute

**Files:**

- Modify: `tests/test_capd_proactive_stage11.py`
- Modify: `qmap/proactive_stage11.py`

- [ ] **Step 1: Add raw join and recomputation tests**

Cover these cases:

```python
def test_join_reads_metrics_from_job_result_not_csv_float(self):
    rows = stage11.load_stage8_rows(self.fixture_root)
    self.assertEqual(rows[0]["raw_access_count"], 600000)
    self.assertEqual(rows[0]["reactive_demotions"], 1314)
    self.assertEqual(rows[0]["source_job_id"], "standard__canneal__reactive_lru")


def test_profile_recompute_uses_integer_counts_and_nulls_zero_access(self):
    result = stage11.recompute_profile_row(self.source_row, "default")
    self.assertEqual(result["weighted_cost"], 623172)
    self.assertEqual(result["weighted_cost_per_access"], 1.03862)
    zero = dict(self.source_row, raw_access_count=0)
    self.assertIsNone(stage11.recompute_profile_row(zero, "default")
                      ["weighted_cost_per_access"])
```

Also test that a CSV-only row, a missing per-job manifest, a result SHA mismatch, a semantic SHA mismatch, a duplicate `job_id`, a missing `raw_access_count`, and a negative counter raise `Stage11ContractError`.

- [ ] **Step 2: Implement the Stage8 loader**

Use `qmap.proactive_stage8_contract.fingerprint_file`, `fingerprint_value`, and `audit_job_result`. The loader must:

1. validate Stage8 r5 `run_state.json`, `verification.json`, contract/status/job counts, and root `job_manifest.json`;
2. read `artifacts/per_workload_raw.csv` only as a row index;
3. resolve each `source_job_id` under `jobs/<job_id>/` without allowing path escape;
4. validate per-job manifest status, `job_identity_sha256`, `result_sha256`, and `semantic_result_sha256`;
5. load `result.json`, audit it against the root job plan, and copy metrics from `result.json.metrics`;
6. return immutable normalized rows carrying `source_job_id`, source SHAs, trace/checkpoint SHAs, controls, raw counts, and evidence mode.

Do not modify source JSON/CSV or normalize missing values into zero.

- [ ] **Step 3: Implement the cost adapter**

Construct `qmap.proactive_cost.RawEventCounts` from integer metrics and call the existing `CostProfile`/`compute_all_profiles` APIs. For each selected profile compute:

```python
weighted_cost = cost_result.weighted_cost
weighted_cost_per_access = (
    None if raw_access_count == 0
    else weighted_cost / float(raw_access_count)
)
```

The adapter must preserve the source profile name and all four weight fields. It must never calculate `raw_access_count` from a cost value.

- [ ] **Step 4: Run focused offline tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11OfflineTest -v
```

Expected: all join, SHA, counter, and profile tests PASS.

## Task 4: Implement Frozen Grid Expansion And Candidate/Ablation Interfaces

**Files:**

- Modify: `tests/test_capd_proactive_stage11.py`
- Modify: `qmap/proactive_stage11.py`

- [ ] **Step 1: Add grid and ablation tests**

Test stable expansion and digest:

```python
def test_grid_digest_is_order_independent_only_before_sorting(self):
    config = explicit_synthetic_grid_config()
    first = stage11.freeze_grid(config)
    shuffled = copy.deepcopy(config)
    shuffled["sensitivity_grid"]["b_max"] = [4, 1, 2]
    second = stage11.freeze_grid(shuffled)
    self.assertEqual(first["frozen_grid_sha256"], second["frozen_grid_sha256"])


def test_sync_mode_blocks_empty_unapproved_watermark_grid(self):
    with self.assertRaises(stage11.Stage11Blocked):
        stage11.require_sync_grid(repository_config())


def test_input_ablation_rows_are_blocked_and_top_batch_differs_only_in_count(self):
    rows = stage11.expand_ablation_grid(explicit_synthetic_grid_config())
    self.assertTrue(all(row["evidence_status"] == "BLOCKED"
                        for row in rows if row["parameter_family"] == "input_ablation"))
    top1, topb = stage11.top_batch_pair(rows)
    self.assertEqual(stage11.config_without_selection_count(top1),
                     stage11.config_without_selection_count(topb))
```

Test `b_max=2` remains the main control, `b_max=1/2/4` rows carry `analysis_only=true`, capacity fractions are exactly 0.2/0.4/0.6, watermark candidates must be explicit integers, and Test data is never read by grid expansion.

- [ ] **Step 2: Implement deterministic grid expansion**

Implement `freeze_grid(config)`, `require_sync_grid(config)`, and `expand_ablation_grid(config)`. Sort records by `(parameter_family, track, workload, seed, policy_or_ablation, b_max, capacity_fraction, cost_profile)`, serialize with stable UTF-8 JSON, and hash the serialized grid. Reject duplicate cell IDs, implicit numeric generation, `grid_frozen=false` in sync mode, and any attempt to overwrite the main control.

- [ ] **Step 3: Implement the two batch rows and blocked input-variant rows**

`Proactive-CAPD-Top-1` and `Proactive-CAPD-Top-b` share all fields except `selection_count`. `CAPD-NoVPN`, `CAPD-NoContext`, and `CAPD-NoPageState` produce interface rows with `evidence_mode="model_component_ablation"` and `evidence_status="BLOCKED"`; they contain a `blocking_reason` requiring a future separately approved training/checkpoint receipt. No training command is constructed by Stage11A.

- [ ] **Step 4: Run grid tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11GridTest -v
```

Expected: all grid, digest, b_max, batch-pair, and blocked-ablation tests PASS.

## Task 5: Implement Stage9 And Stage10A Local Gate Validators

**Files:**

- Modify: `tests/test_capd_proactive_stage11.py`
- Modify: `qmap/proactive_stage11.py`

- [ ] **Step 1: Add fail-closed gate tests**

Test these exact outcomes:

```python
def test_missing_stage9_is_not_verifiable(self):
    receipt = stage11.audit_stage9_gate("missing-stage9")
    self.assertEqual(receipt["status"], "NOT_VERIFIABLE")


def test_stage9_r1_is_rejected_without_manifest_requirement(self):
    receipt = stage11.audit_stage9_gate(STAGE9_R1_ROOT)
    self.assertIn(receipt["status"], ("BLOCKED", "NOT_VERIFIABLE"))
    self.assertFalse(receipt["formal_authorized"])


def test_complete_stage10a_fixture_is_blocked(self):
    receipt = stage11.audit_stage10_fixture(STAGE10_FIXTURE_ROOT)
    self.assertEqual(receipt["status"], "BLOCKED")
    self.assertEqual(receipt["reason_code"], "stage10a_fixture_only")
```

Tamper `verification.json.artifact_sha256` in a Stage9 fixture and each of `manifest.json`, `SHA256SUMS`, `formal_gate.json`, `run_state.json`, and `fixture_results.jsonl` in a Stage10A fixture. Every tamper must fail closed.

- [ ] **Step 2: Implement the Stage9-specific gate**

Implement `audit_stage9_gate(run_root)` without requiring root `manifest.json` or `SHA256SUMS`. Load the Stage9 result schema, require its `required_run_artifacts`, require Linux CPU environment, require `run_state.status == stage9_overhead_verified`, load `stage8_compatibility_receipt.json`, and recompute every artifact listed in `verification.json.artifact_sha256` except the Stage9-defined exclusions `verification.json` and `run_state.json`. Reject `stage9-overhead-r1`, missing perf/RSS/server evidence, invalid schema fields, and Stage8 receipt mismatches.

Return a serializable receipt:

```python
{
    "stage": "stage9",
    "status": "verified" | "BLOCKED" | "NOT_VERIFIABLE",
    "formal_authorized": bool,
    "reason_code": str,
    "run_root": str,
    "run_state_sha256": str | None,
    "verification_sha256": str | None,
    "stage8_compatibility_receipt_sha256": str | None,
}
```

The current repository's failed r1 result must return a non-authorized status and must never be rewritten.

- [ ] **Step 3: Implement the Stage10A-only gate**

Implement `audit_stage10_fixture(run_root)` by importing the existing Stage10 verifier contract or reproducing its independent checks without changing Stage10 files. Require `mode=fixture`, Stage10A schema SHA binding, Stage10A manifest and checksum rules, `formal_gate.status == stage10_formal_blocked_by_stage9`, and `run_state.stage10_formally_verified == false`. A complete fixture returns `BLOCKED`; missing or tampered input returns `NOT_VERIFIABLE`. Do not create any positive Stage10 status branch.

- [ ] **Step 4: Run gate tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11GateTest -v
```

Expected: missing and failed inputs fail closed; Stage10A fixture is blocked; no gate returns a formal authorization.

## Task 6: Implement Runner Lifecycle And Lane-Oriented Outputs

**Files:**

- Modify: `tests/test_capd_proactive_stage11.py`
- Create: `scripts/run_capd_proactive_stage11.py`

- [ ] **Step 1: Add runner lifecycle tests before implementation**

Test these invariants:

```python
def test_global_preflight_failure_creates_no_run_directory(self):
    completed = invoke_runner(config_path="missing.json", run_id="global-fail")
    self.assertNotEqual(completed.returncode, 0)
    self.assertFalse(os.path.exists(os.path.join(self.output_root, "global-fail")))


def test_external_gate_failure_still_writes_offline_candidate(self):
    completed = invoke_runner(mode="all", run_id="offline-with-gates-blocked")
    self.assertEqual(completed.returncode, 0)
    run_root = os.path.join(self.output_root, "offline-with-gates-blocked")
    results = load_json(os.path.join(run_root, "stage11a_results.json"))
    self.assertIn("candidate-ready", {row["evidence_status"] for row in results["rows"]})
    self.assertIn("BLOCKED", {row["evidence_status"] for row in results["rows"]})


def test_existing_run_id_is_rejected_without_overwrite(self):
    first = invoke_runner(run_id="duplicate")
    second = invoke_runner(run_id="duplicate")
    self.assertEqual(first.returncode, 0)
    self.assertNotEqual(second.returncode, 0)
```

- [ ] **Step 2: Implement global preflight and CLI parsing**

Support `--config`, `--mode offline|sync|all`, `--output-root`, `--run-id`, `--stage9-run-root`, `--stage10-run-root`, and `--verify`. Before creating the output run, validate config/schema SHA, Stage8 r5 status and job authority, absolute output containment under `outputs/capd_proactive_stage11`, `run_id` syntax, and absence of an existing run directory. Do not treat Stage9/Stage10 absence as a global preflight failure.

- [ ] **Step 3: Implement lane execution and run state**

After global preflight, create the new run directory and write `stage11a_config.json` with resolved paths and provenance. Execute lanes independently:

```python
rows = []
rows.extend(run_offline_recompute(stage8_root, config, envelope))
rows.extend(run_sync_candidate(stage8_root, config, envelope))
rows.extend(run_external_gates(config, envelope))
```

Catch `Stage11Blocked` and `Stage11NotVerifiable` inside the relevant lane, append a status row with JSON-null metrics and a blocking reason, and continue other lanes. A global preflight exception occurs before `mkdir` and creates no run.

- [ ] **Step 4: Implement atomic outputs**

Write `stage11a_results.json` with `{schema_version, run_id, rows}`, `stage11a_results.csv` using fixed columns and `N/A` rendering, `verification.json`, `run_state.json`, and `stage11a_report.md`. Use stable JSON serialization (`sort_keys=True`, UTF-8, newline) and atomic replace. `run_state.status` may be `stage11a_implemented`, `stage11a_candidate_ready`, `stage11a_blocked`, or `stage11a_not_verifiable`; never write `stage11a_formally_verified` in v1.0.

- [ ] **Step 5: Run runner lifecycle tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11RunnerTest -v
```

Expected: global failures create no run; local Stage9/Stage10 failures still produce an isolated run with offline candidate rows; duplicate run IDs never overwrite.

## Task 7: Add Independent Verification, Reports, And Documentation

**Files:**

- Modify: `tests/test_capd_proactive_stage11.py`
- Modify: `scripts/run_capd_proactive_stage11.py`
- Create: `docs/CAPD_PROACTIVE_STAGE11A_PROTOCOL_CN.md`
- Create: `docs/CAPD_PROACTIVE_STAGE11A_STATUS_CN.md`
- Create: `docs/CAPD_PROACTIVE_STAGE11A_SERVER_CN.md`

- [ ] **Step 1: Add verification and documentation tests**

Test `verify_run(run_root)` recomputes selected weighted costs, row count, frozen grid digest, source result SHAs, Stage11 manifest, and `SHA256SUMS`. Test that changing any output byte fails verification. Test that reports contain the five required sections, JSON null semantics, CSV/Markdown `N/A`, and literal statements that Stage9/Stage10 formal evidence is blocked.

- [ ] **Step 2: Implement Stage11 manifest and checksum verification**

Use these exact sets:

```python
payload = relative_files(run_root) - {"stage11a_manifest.json", "SHA256SUMS"}
manifest_files = payload
checksum_files = payload | {"stage11a_manifest.json"}
```

Reject path traversal, missing files, recursive self-hashes, duplicate checksum entries, and digest mismatches. Re-read and validate all JSON/CSV rows after hashing.

- [ ] **Step 3: Render protocol and status docs**

Document the Stage8 job join, cost formula and profile meanings, frozen-grid rule, `b_max=2` control, JSON null/CSV `N/A`, Stage9 schema-specific gate, Stage10A fixture-only negative gate, input-ablation `BLOCKED` state, and the synchronous-versus-real-system interpretation boundary. Never claim Stage9 CPU/RSS or Stage10 asynchronous behavior.

- [ ] **Step 4: Write the non-executed Linux handoff**

Include copyable commands that point to a future verified Stage9 v2 run and invoke Stage11 gate verification. The document must state that current `stage9-overhead-r1` is rejected, commands have not run, and no server result is present. Do not include a command that changes Stage8/Stage9 evidence or trains an input-ablation model.

- [ ] **Step 5: Run documentation and verifier tests**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11.Stage11VerificationTest -v
```

Expected: artifact tampering is rejected, manifest/checksum sets are exact, reports preserve null/N/A semantics, and no document claims `formally_verified` output exists.

## Task 8: Full Local Verification And Frozen-Evidence Audit

**Files:**

- Modify only: `tests/test_capd_proactive_stage11.py` if a test exposes a contract defect.
- Create during execution only: `tmp/stage11a-frozen-after.json`, test logs, and a temporary fixture run.

- [ ] **Step 1: Run the complete Stage11A test module**

Run:

```powershell
python -m unittest tests.test_capd_proactive_stage11 -v
```

Expected: all Stage11A tests pass; tests report only `implemented`, `candidate-ready`, `BLOCKED`, or `NOT_VERIFIABLE`; no row has `evidence_status=formally_verified`.

- [ ] **Step 2: Verify a synthetic run independently**

Run the fixture-only runner into a temporary output root, then:

```powershell
python scripts/run_capd_proactive_stage11.py --verify <temporary-run-root>
```

Expected: independent verification exits 0, Stage10A is `BLOCKED`, missing Stage9 is `NOT_VERIFIABLE`, and offline fixture values match integer recomputation. Do not point this command at the formal Stage8 output unless a separate experiment execution approval is provided.

- [ ] **Step 3: Compare the frozen trees after testing**

Write the same file-by-file SHA snapshot command used in Task 1 to `tmp/stage11a-frozen-after.json`, then compare:

```powershell
if ((Get-Content -Raw 'tmp/stage11a-frozen-before.json') -ne
    (Get-Content -Raw 'tmp/stage11a-frozen-after.json')) {
  throw 'Frozen Stage8/Stage9 trees changed'
}
```

Expected: exact byte-for-byte equality. `git status --short` must show only the intended Stage11 plan/design/code/test/docs changes and unrelated pre-existing files; no Stage8/Stage9/frozen checkpoint path may appear.

- [ ] **Step 4: Run whitespace and forbidden-claim checks**

Run:

```powershell
$paths = @(
  'docs/superpowers/plans/2026-08-05-stage11a-sensitivity-ablation.md',
  'docs/CAPD_PROACTIVE_STAGE11A_PROTOCOL_CN.md',
  'docs/CAPD_PROACTIVE_STAGE11A_STATUS_CN.md',
  'docs/CAPD_PROACTIVE_STAGE11A_SERVER_CN.md'
)
foreach ($path in $paths) {
  $text = Get-Content -Raw -LiteralPath $path
  if ($text -match '(?m)[ \t]+$' -or $text -match '(?m)^\t') {
    throw "Whitespace violation: $path"
  }
  $forbidden = @('TO' + 'DO', 'T' + 'BD', 'FIX' + 'ME')
  $pattern = '(?im)\b(' + (($forbidden | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\b'
  if ($text -match $pattern) {
    throw "Placeholder violation: $path"
  }
}
```

Expected: no output and exit code 0. Do not commit or push as part of this plan.

## Plan Self-Review

- Spec coverage: Tasks 2 and 3 cover independent config, four cost profiles, Stage8 job/result SHA joins, raw counters, null semantics, and provenance. Task 4 covers all sensitivity and batch grids plus blocked model-component ablations. Task 5 covers Stage9's actual artifact-SHA contract and Stage10A's fixture-only negative gate. Task 6 covers global versus local gate lifecycle and independent lanes. Task 7 covers Stage11 artifact hashing, reports, and server handoff. Task 8 covers complete tests and frozen-tree preservation.
- No Stage10B positive schema or status is invented; the only Stage10 status accepted by v1.0 is the current fixture-blocked state.
- No unapproved watermark or label-weight values are selected; sync execution remains blocked until an explicit frozen grid is supplied.
- No formal Stage11 status is generated; `formally_verified` remains vocabulary only.
- No commit, push, Stage8/Stage9 modification, checkpoint modification, retraining, or Test-based selection is authorized.
- Placeholder scan target: this plan contains no forbidden placeholder markers.

Plan complete and saved to `docs/superpowers/plans/2026-08-05-stage11a-sensitivity-ablation.md`. Two execution options remain for after the user approves the plan:

1. Subagent-Driven: dispatch a fresh worker per task and review each checkpoint.
2. Inline Execution: execute tasks in this session with `superpowers:executing-plans` checkpoints.
