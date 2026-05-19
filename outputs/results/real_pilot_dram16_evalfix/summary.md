# Real 100k PARSEC Pilot

## Setup

- run id: `real_pilot_100k_dram16_evalfix`
- workloads: `parsec_blackscholes, parsec_canneal, parsec_streamcluster, parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `100000`
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
| parsec_blackscholes | 100000 | 104 | 4471 | 0.3231 | 0.9990 |
| parsec_canneal | 100000 | 157 | 1946 | 0.2736 | 0.9984 |
| parsec_streamcluster | 100000 | 156 | 1941 | 0.2744 | 0.9984 |
| parsec_dedup | 100000 | 121 | 2678 | 0.3963 | 0.9988 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_blackscholes | LRU | 98.99 | 12 | 11023.00 | 85 | 0.000311 |
| parsec_blackscholes | RANDOM | 98.33 | 22 | 11809.00 | 151 | 0.001227 |
| parsec_blackscholes | LFU | 96.76 | 24 | 13548.00 | 308 | 0.006455 |
| parsec_blackscholes | CLOCK | 98.87 | 12 | 11155.00 | 97 | 0.002125 |
| parsec_blackscholes | QMAP-Pool | 92.42 | 38 | 18406.00 | 742 | 3.265216 |
| parsec_canneal | LRU | 94.17 | 41 | 16499.00 | 567 | 0.000289 |
| parsec_canneal | RANDOM | 93.78 | 55 | 17012.00 | 606 | 0.001196 |
| parsec_canneal | LFU | 95.98 | 52 | 14574.00 | 386 | 0.006900 |
| parsec_canneal | CLOCK | 94.47 | 37 | 16145.00 | 537 | 0.001812 |
| parsec_canneal | QMAP-Pool | 94.63 | 47 | 16029.00 | 521 | 3.571660 |
| parsec_streamcluster | LRU | 94.09 | 41 | 16587.00 | 575 | 0.000355 |
| parsec_streamcluster | RANDOM | 93.73 | 51 | 17043.00 | 611 | 0.001523 |
| parsec_streamcluster | LFU | 96.05 | 48 | 14473.00 | 379 | 0.009194 |
| parsec_streamcluster | CLOCK | 94.32 | 32 | 16280.00 | 552 | 0.001758 |
| parsec_streamcluster | QMAP-Pool | 94.27 | 49 | 16437.00 | 557 | 3.474137 |
| parsec_dedup | LRU | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | RANDOM | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | LFU | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | CLOCK | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | QMAP-Pool | 99.90 | 7 | 10052.00 | 0 | 0.000000 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_blackscholes | LRU +66.98% |
| parsec_canneal | LFU +9.98% |
| parsec_streamcluster | LFU +13.57% |
| parsec_dedup | LRU +0.00% |
