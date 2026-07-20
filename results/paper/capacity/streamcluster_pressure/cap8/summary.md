# Real/PARSEC QMAP Experiment

## Setup

- run id: `capacity_streamcluster_pressure_cap8`
- workloads: `parsec_streamcluster`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-CrossAttn`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `8` pages
- h/c/d/l: `10/8/8/256`
- QMAP model: `QMAP-CrossAttn` (`ablation=cross_attention`)
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
| parsec_streamcluster | LRU | 92.47 | 731 | 369999.00 | 15055 | 0.000291 |
| parsec_streamcluster | RANDOM | 89.95 | 2110 | 433691.00 | 20093 | 0.001203 |
| parsec_streamcluster | LFU | 89.56 | 818 | 434464.00 | 20868 | 0.003339 |
| parsec_streamcluster | CLOCK | 92.31 | 734 | 373526.00 | 15374 | 0.001388 |
| parsec_streamcluster | QMAP-CrossAttn | 94.13 | 589 | 332660.00 | 11738 | 2.356620 |

## QMAP-CrossAttn vs Best Baseline By Cost

| Workload | Best baseline and QMAP-CrossAttn cost delta |
|---|---:|
| parsec_streamcluster | LRU -10.09% |
