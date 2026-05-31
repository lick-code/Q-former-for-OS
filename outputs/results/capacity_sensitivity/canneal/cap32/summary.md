# Real/PARSEC QMAP Experiment

## Setup

- run id: `capacity_canneal_cap32`
- workloads: `parsec_canneal`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_canneal=100000`
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
| parsec_canneal | 1000000 | 254 | 6821 | 0.2854 | 0.9997 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_canneal | LRU | 99.84 | 3 | 101502.00 | 132 | 0.000299 |
| parsec_canneal | RANDOM | 99.79 | 11 | 102100.00 | 182 | 0.001247 |
| parsec_canneal | LFU | 99.12 | 8 | 109397.00 | 847 | 0.010721 |
| parsec_canneal | CLOCK | 99.82 | 4 | 101706.00 | 150 | 0.001549 |
| parsec_canneal | QMAP-Pool | 99.85 | 2 | 101320.00 | 116 | 7.190499 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_canneal | LRU -0.18% |
