# CAPD proactive Stage9 outputs

This directory is reserved for immutable Linux CPU measurement runs:

`outputs/capd_proactive_stage9/<run_id>/`

Do not place simulated or local static-check data here as a formal run. A failed or interrupted run ID is permanently non-resumable; preserve its `run_state.json` and use a new run ID.

`stage9-overhead-r1` is a preserved Stage9 v1 failed run: hardware counters were denied by `kernel.perf_event_paranoid=4`, and its obsolete matrix produced zero formal latency samples. It is not resumable, overwritable, or importable. Stage9 v2 must start with a fresh ID such as `stage9-overhead-v2-r1`.

The v2 workflow consumes the read-only Stage8 r5 dual-track manifests. Each b_max has 30 `(track, workload, seed)` quality jobs: 27 active and 3 zero-round standard-fluidanimate jobs. Formal `b_max=2` instrumentation covers all 30 jobs; latency/perf cover only the 27 active jobs. Capacity accounting has 6 unique workload rows and records applicable tracks without double charging.

Required verified artifacts are defined by `configs/finals/capd_proactive_stage9_result_schema.json`. Only `scripts/run_capd_proactive_stage9.py verify` may emit `stage9_overhead_verified`, `stage10_entry_gate=satisfied`, and `[FINAL] STAGE9_OVERHEAD_VERIFIED` after Linux CPU, perf hardware cycles, memory, raw-summary, instrumentation, and regression checks all pass.

Stage8 r5 is an external read-only authority and must never be copied over or modified by Stage9. Stage9 records compatibility in its own `stage8_compatibility_receipt.json`.
