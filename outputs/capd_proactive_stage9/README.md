# CAPD proactive Stage9 outputs

This directory is reserved for immutable Linux CPU measurement runs:

`outputs/capd_proactive_stage9/<run_id>/`

Do not place simulated or local static-check data here as a formal run. A failed or interrupted run ID is permanently non-resumable; preserve its `run_state.json` and use a new run ID.

Required verified artifacts are defined by `configs/finals/capd_proactive_stage9_result_schema.json`. Only `scripts/run_capd_proactive_stage9.py verify` may emit `stage9_overhead_verified`, `stage10_entry_gate=satisfied`, and `[FINAL] STAGE9_OVERHEAD_VERIFIED` after Linux CPU, perf hardware cycles, memory, raw-summary, instrumentation, and regression checks all pass.

Stage8 r3 is an external read-only authority and must never be copied over or modified by Stage9.
