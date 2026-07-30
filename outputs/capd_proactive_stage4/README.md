# capd_proactive_stage4

This directory contains the verified proactive Stage-4 workflow artifacts.
Historical `finals_v3` Stage-4 artifacts are not inputs to this tree.

The formally archived run is:

- manifest: `manifests/stage4-f8-f16-r3.json`
- run directory: `stage4-f8-f16-r3/`
- status: `stage4_verified`
- selected parameters: `L=256`, `lambda=(1,1,2)`, `K=8`, `H=20`
- seeds: `3136859`, `42`, `2026`

The run completed real Train/Validation generation, training, global parameter
selection, final rebuilding, 113 server regression tests, artifact fingerprint
verification, and Test/legacy-artifact contamination audits. Its authoritative
completion evidence is `stage4-f8-f16-r3/verification.json`.

Each run directory is immutable and identity-bound. A future change to source
data, code, watermarks, the parameter grid, or the training contract requires a
new `run_id`; do not overwrite the archived `stage4-f8-f16-r3` directory.

`configs/finals/capd_proactive_stage4.json` remains the predeclared protocol
input and intentionally retains its awaiting-input status. Live completion
status is recorded by the run's `run_state.json` and `verification.json`.
