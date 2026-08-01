# CAPD proactive Stage9 outputs

This directory is reserved for immutable Linux CPU measurement runs:

`outputs/capd_proactive_stage9/<run_id>/`

Do not place simulated or local static-check data here as a formal run. A failed or interrupted run ID is permanently non-resumable; preserve its `run_state.json` and use a new run ID.

`stage9-overhead-r1` is a preserved failed run: hardware counters were denied by `kernel.perf_event_paranoid=4`, and the obsolete 0.40 matrix produced zero formal latency samples. It is not resumable or importable. The corrected workflow uses the Stage7 pre-frozen 0.20 main default, retains all 18 quality cells per b_max, and measures latency/perf only for the 9 active-round cells.

Required verified artifacts are defined by `configs/finals/capd_proactive_stage9_result_schema.json`. Only `scripts/run_capd_proactive_stage9.py verify` may emit `stage9_overhead_verified`, `stage10_entry_gate=satisfied`, and `[FINAL] STAGE9_OVERHEAD_VERIFIED` after Linux CPU, perf hardware cycles, memory, raw-summary, instrumentation, and regression checks all pass.

Stage8 r3 is an external read-only authority and must never be copied over or modified by Stage9.
