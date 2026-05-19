# Real 100k PARSEC Pilot

## Setup

- run id: `real_pilot_100k_dram32`
- workloads: `parsec_blackscholes, parsec_canneal, parsec_streamcluster, parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `100000`
- split policy: `chronological 80/10/10`
- DRAM capacity: `32` pages
- h/c/d/l: `10/64/32/256`
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
| parsec_blackscholes | LRU | 99.45 | 5 | 10315.00 | 23 | 0.000333 |
| parsec_blackscholes | RANDOM | 99.33 | 5 | 10447.00 | 35 | 0.001463 |
| parsec_blackscholes | LFU | 99.37 | 6 | 10409.00 | 31 | 0.015043 |
| parsec_blackscholes | CLOCK | 99.29 | 6 | 10497.00 | 39 | 0.001418 |
| parsec_blackscholes | QMAP-Pool | 99.46 | 4 | 10298.00 | 22 | 28.863295 |
| parsec_canneal | LRU | 99.69 | 2 | 10043.00 | 0 | 0.000000 |
| parsec_canneal | RANDOM | 99.69 | 2 | 10043.00 | 0 | 0.000000 |
| parsec_canneal | LFU | 99.69 | 2 | 10043.00 | 0 | 0.000000 |
| parsec_canneal | CLOCK | 99.69 | 2 | 10043.00 | 0 | 0.000000 |
| parsec_canneal | QMAP-Pool | 99.69 | 2 | 10043.00 | 0 | 0.000000 |
| parsec_streamcluster | LRU | 99.69 | 1 | 10037.00 | 0 | 0.000000 |
| parsec_streamcluster | RANDOM | 99.69 | 1 | 10037.00 | 0 | 0.000000 |
| parsec_streamcluster | LFU | 99.69 | 1 | 10037.00 | 0 | 0.000000 |
| parsec_streamcluster | CLOCK | 99.69 | 1 | 10037.00 | 0 | 0.000000 |
| parsec_streamcluster | QMAP-Pool | 99.69 | 1 | 10037.00 | 0 | 0.000000 |
| parsec_dedup | LRU | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | RANDOM | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | LFU | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | CLOCK | 99.90 | 7 | 10052.00 | 0 | 0.000000 |
| parsec_dedup | QMAP-Pool | 99.90 | 7 | 10052.00 | 0 | 0.000000 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_blackscholes | LRU -0.16% |
| parsec_canneal | LRU +0.00% |
| parsec_streamcluster | LRU +0.00% |
| parsec_dedup | LRU +0.00% |
