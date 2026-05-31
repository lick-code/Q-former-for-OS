# Real/PARSEC QMAP Experiment

## Setup

- run id: `capacity_streamcluster_pressure_cap8`
- workloads: `parsec_streamcluster`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `8` pages
- h/c/d/l: `10/8/8/256`
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
| parsec_streamcluster | LRU | 92.47 | 731 | 369999.00 | 15055 | 0.000303 |
| parsec_streamcluster | RANDOM | 89.95 | 2110 | 433691.00 | 20093 | 0.001152 |
| parsec_streamcluster | LFU | 89.56 | 818 | 434464.00 | 20868 | 0.003447 |
| parsec_streamcluster | CLOCK | 92.31 | 734 | 373526.00 | 15374 | 0.001570 |
| parsec_streamcluster | QMAP-Pool | 94.20 | 592 | 331072.00 | 11592 | 2.299018 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_streamcluster | LRU -10.52% |
