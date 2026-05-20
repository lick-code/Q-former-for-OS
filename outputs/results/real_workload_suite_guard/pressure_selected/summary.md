# Real/PARSEC QMAP Experiment

## Setup

- run id: `real_workload_suite_guard_pressure`
- workloads: `parsec_streamcluster, parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000, parsec_dedup=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/8/16/256`
- QMAP model: `QMAP-Pool-Guard` (`ablation=mean_pool`)
- QMAP rank guard: `2`
- page shift: `12`
- epochs: `10`
- batch size: `32`
- seed: `3136859`
- random seed: `0`
- device: `cuda`

## Trace Stats

| Workload | Records | Unique pages | Unique PCs | Write ratio | Reuse ratio |
|---|---:|---:|---:|---:|---:|
| parsec_streamcluster | 1000000 | 767 | 4238 | 0.3495 | 0.9992 |
| parsec_dedup | 1000000 | 493 | 34 | 0.5000 | 0.9995 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_streamcluster | LRU | 95.35 | 585 | 305562.00 | 9276 | 0.000287 |
| parsec_streamcluster | RANDOM | 95.01 | 777 | 314183.00 | 9955 | 0.001131 |
| parsec_streamcluster | LFU | 92.84 | 740 | 361877.00 | 14311 | 0.006411 |
| parsec_streamcluster | CLOCK | 95.52 | 574 | 301767.00 | 8937 | 0.001444 |
| parsec_streamcluster | QMAP-Pool | 95.85 | 582 | 294643.00 | 8285 | 2.178862 |
| parsec_dedup | LRU | 99.95 | 99 | 201567.00 | 87 | 0.000494 |
| parsec_dedup | RANDOM | 99.93 | 105 | 202076.00 | 130 | 0.001686 |
| parsec_dedup | LFU | 99.88 | 233 | 203845.00 | 221 | 0.006243 |
| parsec_dedup | CLOCK | 99.95 | 100 | 201584.00 | 88 | 0.001635 |
| parsec_dedup | QMAP-Pool | 99.95 | 99 | 201567.00 | 87 | 8.907985 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_streamcluster | CLOCK -2.36% |
| parsec_dedup | LRU +0.00% |
