# Real/PARSEC QMAP Experiment

## Setup

- run id: `real_workload_suite_1m`
- workloads: `parsec_blackscholes, parsec_canneal, parsec_streamcluster, parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `1000000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/8/16/256`
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
| parsec_blackscholes | 1000000 | 23 | 611 | 0.3468 | 1.0000 |
| parsec_canneal | 1000000 | 254 | 6821 | 0.2854 | 0.9997 |
| parsec_streamcluster | 1000000 | 767 | 4238 | 0.3495 | 0.9992 |
| parsec_dedup | 1000000 | 493 | 34 | 0.5000 | 0.9995 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_blackscholes | LRU | 98.89 | 144 | 112958.00 | 1098 | 0.000288 |
| parsec_blackscholes | RANDOM | 98.66 | 145 | 115505.00 | 1329 | 0.001238 |
| parsec_blackscholes | LFU | 99.47 | 221 | 106952.00 | 510 | 0.005870 |
| parsec_blackscholes | CLOCK | 99.09 | 107 | 110437.00 | 889 | 0.002007 |
| parsec_blackscholes | QMAP-Pool | 99.46 | 32 | 105983.00 | 525 | 3.387825 |
| parsec_canneal | LRU | 97.63 | 52 | 126178.00 | 2350 | 0.000287 |
| parsec_canneal | RANDOM | 96.50 | 193 | 139465.00 | 3481 | 0.001163 |
| parsec_canneal | LFU | 94.69 | 280 | 159919.00 | 5293 | 0.005749 |
| parsec_canneal | CLOCK | 97.62 | 60 | 126325.00 | 2359 | 0.001727 |
| parsec_canneal | QMAP-Pool | 95.42 | 51 | 150559.00 | 4567 | 2.401794 |
| parsec_streamcluster | LRU | 99.99 | 4 | 100033.00 | 0 | 0.000000 |
| parsec_streamcluster | RANDOM | 99.99 | 4 | 100033.00 | 0 | 0.000000 |
| parsec_streamcluster | LFU | 99.99 | 4 | 100033.00 | 0 | 0.000000 |
| parsec_streamcluster | CLOCK | 99.99 | 4 | 100033.00 | 0 | 0.000000 |
| parsec_streamcluster | QMAP-Pool | 99.99 | 4 | 100033.00 | 0 | 0.000000 |
| parsec_dedup | LRU | 99.95 | 50 | 100734.00 | 38 | 0.000572 |
| parsec_dedup | RANDOM | 99.93 | 56 | 100968.00 | 56 | 0.001950 |
| parsec_dedup | LFU | 99.89 | 106 | 101686.00 | 94 | 0.006607 |
| parsec_dedup | CLOCK | 99.94 | 51 | 100751.00 | 39 | 0.002321 |
| parsec_dedup | QMAP-Pool | 99.95 | 50 | 100734.00 | 38 | 18.408344 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_blackscholes | LFU -0.91% |
| parsec_canneal | LRU +19.32% |
| parsec_streamcluster | LRU +0.00% |
| parsec_dedup | LRU +0.00% |
