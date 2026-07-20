# CAPD Paper Results

This directory is a lightweight, copy-ready evidence package for the CAPD
competition repository. It contains the result summaries, machine-readable
metrics, and figures used by the latest paper. Training logs, checkpoints,
generated JSONL files, and unrelated historical experiments are excluded.

## Layout

```text
results/
└─ paper/
   ├─ main/
   ├─ pressure/
   ├─ learned_baselines/
   ├─ capacity/
   ├─ seed_stability/
   ├─ cost_weight/
   └─ figures/
```

## Contents

- `paper/main/`: standard 1M-reference replay summary and the blackscholes
  per-policy results used by the paper.
- `paper/pressure/`: fixed streamcluster and dedup pressure-window results,
  including per-policy JSON and trace statistics.
- `paper/learned_baselines/`: comparison with Kleio-lite and PatternS-lite.
- `paper/capacity/`: streamcluster-pressure results with 8, 16, and 32 DRAM
  pages.
- `paper/seed_stability/`: CAPD results for seeds 3136859, 42, and 2026 on
  streamcluster-pressure, blackscholes, and canneal.
- `paper/cost_weight/`: replay-only robustness results under alternative cost
  weights.
- `paper/figures/`: the CAPD main-result figure in PDF, PNG, and SVG formats.

## Naming Compatibility

The development code and raw machine-readable result files still use the
historical identifiers `qmap` and `QMAP-CrossAttn`. In the latest paper these
refer to the method named **CAPD**. The copied files remain unchanged so their
contents and checksums stay traceable to the original experiment outputs.

## Source Directories

The package was selected from:

```text
outputs/results/real_workload_suite/1m/
outputs/results/real_workload_suite_pressure/selected/
outputs/results/ml_baselines/
outputs/results/capacity_sensitivity/
outputs/results/seed_stability/
outputs/results/cost_weight_sensitivity/
outputs/figures/
```

The original directories remain the authoritative development artifacts.
