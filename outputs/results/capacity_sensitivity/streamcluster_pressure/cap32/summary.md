# Real/PARSEC QMAP Experiment

## Setup

- run id: `capacity_streamcluster_pressure_cap32`
- workloads: `parsec_streamcluster`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `32` pages
- h/c/d/l: `10/8/32/256`
- QMAP model: `QMAP-Pool` (`ablation=mean_pool`)
- QMAP rank guard: `disabled`
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

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_streamcluster | LRU | 99.24 | 35 | 216577.00 | 1485 | 0.000326 |
| parsec_streamcluster | RANDOM | 98.52 | 171 | 233288.00 | 2930 | 0.001205 |
| parsec_streamcluster | LFU | 96.25 | 435 | 284746.00 | 7464 | 0.010751 |
| parsec_streamcluster | CLOCK | 99.11 | 64 | 219611.00 | 1745 | 0.001764 |
| parsec_streamcluster | QMAP-Pool | 99.21 | 15 | 217150.00 | 1548 | 2.566132 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_streamcluster | LRU +0.26% |
