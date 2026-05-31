# Real/PARSEC QMAP Experiment

## Setup

- run id: `candidate_streamcluster_pressure_c8`
- workloads: `parsec_streamcluster`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/8/16/256`
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
| parsec_streamcluster | LRU | 95.35 | 585 | 305562.00 | 9276 | 0.000300 |
| parsec_streamcluster | RANDOM | 95.01 | 777 | 314183.00 | 9955 | 0.001204 |
| parsec_streamcluster | LFU | 92.84 | 740 | 361877.00 | 14311 | 0.005964 |
| parsec_streamcluster | CLOCK | 95.52 | 574 | 301767.00 | 8937 | 0.001427 |
| parsec_streamcluster | QMAP-Pool | 97.22 | 589 | 264501.00 | 5541 | 2.383505 |

## QMAP-Pool vs Best Baseline By Cost

| Workload | Best baseline and QMAP-Pool cost delta |
|---|---:|
| parsec_streamcluster | CLOCK -12.35% |
