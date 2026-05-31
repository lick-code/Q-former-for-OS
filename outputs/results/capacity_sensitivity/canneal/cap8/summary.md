# Real/PARSEC QMAP Experiment

## Setup

- run id: `capacity_canneal_cap8`
- workloads: `parsec_canneal`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_canneal=100000`
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
| parsec_canneal | 1000000 | 254 | 6821 | 0.2854 | 0.9997 |

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| parsec_canneal | LRU | 91.87 | 228 | 190696.00 | 8120 | 0.000275 |
| parsec_canneal | RANDOM | 89.55 | 653 | 218810.00 | 10444 | 0.001099 |
| parsec_canneal | LFU | 85.09 | 910 | 269379.00 | 14901 | 0.003362 |
| parsec_canneal | CLOCK | 91.39 | 156 | 195599.00 | 8605 | 0.001446 |
| parsec_canneal | QMAP-Pool | 80.82 | 616 | 314640.00 | 19176 | 2.269642 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_canneal | LRU +65.00% |
