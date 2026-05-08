# QMAP Workload Suite

## Setup

- run id: `20260508_113526`
- workloads: `hotset, writeheavy, streaming, phasechange`
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
| hotset | lru | 86.50 | 38 | 3766.00 | 142 | 0.000245 |
| hotset | random | 83.90 | 55 | 4372.00 | 194 | 0.000886 |
| hotset | lfu | 86.60 | 39 | 3746.00 | 140 | 0.022639 |
| hotset | clock | 86.35 | 40 | 3803.00 | 145 | 0.001039 |
| hotset | qmap | 86.45 | 38 | 3777.00 | 143 | 5.623990 |
| writeheavy | lru | 71.30 | 238 | 7510.00 | 446 | 0.000249 |
| writeheavy | random | 66.45 | 310 | 8721.00 | 543 | 0.000877 |
| writeheavy | lfu | 71.95 | 224 | 7339.00 | 433 | 0.022638 |
| writeheavy | clock | 68.05 | 282 | 8313.00 | 511 | 0.000995 |
| writeheavy | qmap | 73.45 | 209 | 6979.00 | 403 | 3.032509 |
| streaming | lru | 0.00 | 100 | 22920.00 | 1872 | 0.000240 |
| streaming | random | 0.00 | 100 | 22920.00 | 1872 | 0.000844 |
| streaming | lfu | 0.00 | 100 | 22920.00 | 1872 | 0.021080 |
| streaming | clock | 0.00 | 100 | 22920.00 | 1872 | 0.000894 |
| streaming | qmap | 0.70 | 99 | 22764.00 | 1858 | 2.075083 |
| phasechange | lru | 62.25 | 188 | 9401.00 | 627 | 0.000241 |
| phasechange | random | 53.85 | 222 | 11317.00 | 795 | 0.000847 |
| phasechange | lfu | 71.70 | 112 | 7170.00 | 438 | 0.022477 |
| phasechange | clock | 54.90 | 233 | 11108.00 | 774 | 0.001023 |
| phasechange | qmap | 61.25 | 172 | 9589.00 | 647 | 2.580720 |
