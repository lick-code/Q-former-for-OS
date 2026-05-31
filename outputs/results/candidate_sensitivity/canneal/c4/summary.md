# Real/PARSEC QMAP Experiment

## Setup

- run id: `candidate_canneal_c4`
- workloads: `parsec_canneal`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_canneal=100000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/4/16/256`
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
| parsec_canneal | LRU | 97.63 | 52 | 126178.00 | 2350 | 0.000294 |
| parsec_canneal | RANDOM | 96.50 | 193 | 139465.00 | 3481 | 0.001163 |
| parsec_canneal | LFU | 94.69 | 280 | 159919.00 | 5293 | 0.005728 |
| parsec_canneal | CLOCK | 97.62 | 60 | 126325.00 | 2359 | 0.001661 |
| parsec_canneal | QMAP-Pool | 96.85 | 52 | 134802.00 | 3134 | 2.377925 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_canneal | LRU +6.83% |
