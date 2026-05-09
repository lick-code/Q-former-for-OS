# QMAP Workload Suite

## Setup

- run id: `20260509_212943`
- workloads: `pcrwstress`
- policies: `lru, random, lfu, clock, qmap`
- records per workload: `20000`
- split policy: `chronological 80/10/10`
- DRAM capacity: `128` pages
- history length: `10`
- candidate count: `64`
- lookahead: `256`
- page shift: `12`
- epochs: `10`
- batch size: `32`
- device: `cuda`

## Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|
| pcrwstress | lru | 72.70 | 24 | 6870.00 | 418 | 0.000267 |
| pcrwstress | random | 65.35 | 100 | 8943.00 | 565 | 0.000908 |
| pcrwstress | lfu | 76.05 | 24 | 6133.00 | 351 | 0.023268 |
| pcrwstress | clock | 68.30 | 96 | 8270.00 | 506 | 0.001091 |
| pcrwstress | qmap | 74.65 | 24 | 6441.00 | 379 | 3.142116 |
