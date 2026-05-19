# Real 100k PARSEC Pilot

## Setup

- run id: `real_pilot_dedup_pressure_limit50k_dram16`
- workloads: `parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `50000`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/64/16/256`
- QMAP model: `QMAP-Pool` (`ablation=mean_pool`)
- page shift: `12`
- epochs: `10`
- batch size: `32`
- seed: `3136859`
- random seed: `0`
- device: `cuda`

## Trace Stats

| Workload | Records | Unique pages | Unique PCs | Write ratio | Reuse ratio |
|---|---:|---:|---:|---:|---:|
| parsec_dedup | 50000 | 87 | 2099 | 0.2941 | 0.9983 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_dedup | LRU | 95.56 | 14 | 7366.00 | 206 | 0.000405 |
| parsec_dedup | RANDOM | 94.82 | 24 | 7833.00 | 243 | 0.001171 |
| parsec_dedup | LFU | 95.12 | 20 | 7644.00 | 228 | 0.005900 |
| parsec_dedup | CLOCK | 95.68 | 15 | 7306.00 | 200 | 0.001581 |
| parsec_dedup | QMAP-Pool | 94.10 | 7 | 8127.00 | 279 | 4.574475 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_dedup | CLOCK +11.24% |
