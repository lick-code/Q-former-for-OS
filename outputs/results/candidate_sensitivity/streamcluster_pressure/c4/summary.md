# Real/PARSEC QMAP Experiment

## Setup

- run id: `candidate_streamcluster_pressure_c4`
- workloads: `parsec_streamcluster`
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-CrossAttn`
- records per workload: `external processed splits (--skip_prepare)`
- test accesses: `parsec_streamcluster=200000`
- global skip: `0`
- split policy: `chronological 80/10/10`
- DRAM capacity: `16` pages
- h/c/d/l: `10/4/16/256`
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
| parsec_streamcluster | LRU | 95.35 | 585 | 305562.00 | 9276 | 0.000289 |
| parsec_streamcluster | RANDOM | 95.01 | 777 | 314183.00 | 9955 | 0.001142 |
| parsec_streamcluster | LFU | 92.84 | 740 | 361877.00 | 14311 | 0.005853 |
| parsec_streamcluster | CLOCK | 95.52 | 574 | 301767.00 | 8937 | 0.001440 |
| parsec_streamcluster | QMAP-CrossAttn | 96.31 | 589 | 284587.00 | 7367 | 2.298621 |

## QMAP-CrossAttn vs Best Baseline By Cost

| Workload | Best baseline and QMAP-CrossAttn cost delta |
|---|---:|
| parsec_streamcluster | CLOCK -5.69% |
