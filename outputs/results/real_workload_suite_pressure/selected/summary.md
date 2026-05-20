# Real/PARSEC QMAP Experiment

## Setup

- run id: `real_pressure_windows_1m`
- workloads: `parsec_streamcluster, parsec_dedup`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `100000`
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
| parsec_streamcluster | 1000000 | 767 | 4238 | 0.3495 | 0.9992 |
| parsec_dedup | 1000000 | 493 | 34 | 0.5000 | 0.9995 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_streamcluster | LRU | 95.35 | 585 | 305562.00 | 9276 | 0.000318 |
| parsec_streamcluster | RANDOM | 95.01 | 777 | 314183.00 | 9955 | 0.001190 |
| parsec_streamcluster | LFU | 92.84 | 740 | 361877.00 | 14311 | 0.005936 |
| parsec_streamcluster | CLOCK | 95.52 | 574 | 301767.00 | 8937 | 0.001553 |
| parsec_streamcluster | QMAP-Pool | 97.22 | 589 | 264501.00 | 5541 | 2.360334 |
| parsec_dedup | LRU | 99.95 | 99 | 201567.00 | 87 | 0.000418 |
| parsec_dedup | RANDOM | 99.93 | 105 | 202076.00 | 130 | 0.001658 |
| parsec_dedup | LFU | 99.88 | 233 | 203845.00 | 221 | 0.006130 |
| parsec_dedup | CLOCK | 99.95 | 100 | 201584.00 | 88 | 0.001643 |
| parsec_dedup | QMAP-Pool | 99.95 | 99 | 201567.00 | 87 | 9.091155 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_streamcluster | CLOCK -12.35% |
| parsec_dedup | LRU +0.00% |
