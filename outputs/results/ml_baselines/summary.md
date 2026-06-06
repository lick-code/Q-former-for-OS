# Learned Baseline Comparison

## Setup

- learned baselines: `Kleio-lite`, `PatternS-lite`
- history_length: `10`
- candidate_count: `8`
- dram_capacity: `16` pages
- lookahead: `256`
- label_lookahead: `256`

## Results

| Workload | Policy | Cost | Delta vs QMAP | Hit rate (%) | NVM writes | Migrations | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|
| blackscholes | QMAP-CrossAttn | 105983.00 | +0.00% | 99.46 | 32 | 525 | 3.459228 |
| blackscholes | Kleio-lite | 110390.00 | +4.16% | 99.04 | 2 | 942 | 0.068849 |
| blackscholes | PatternS-lite | 107207.00 | +1.15% | 99.36 | 49 | 627 | 0.075142 |
| blackscholes | LRU | 112958.00 | +6.58% | 98.89 | 144 | 1098 | 0.000307 |
| blackscholes | RANDOM | 115505.00 | +8.98% | 98.66 | 145 | 1329 | 0.001257 |
| blackscholes | LFU | 106952.00 | +0.91% | 99.47 | 221 | 510 | 0.006373 |
| blackscholes | CLOCK | 110437.00 | +4.20% | 99.09 | 107 | 889 | 0.002086 |
| canneal | QMAP-CrossAttn | 150263.00 | +0.00% | 95.44 | 42 | 4545 | 2.419797 |
| canneal | Kleio-lite | 124825.00 | -16.93% | 97.76 | 52 | 2227 | 0.068408 |
| canneal | PatternS-lite | 137429.00 | -8.54% | 96.64 | 103 | 3345 | 0.097725 |
| canneal | LRU | 126178.00 | -16.03% | 97.63 | 52 | 2350 | 0.000329 |
| canneal | RANDOM | 139465.00 | -7.19% | 96.50 | 193 | 3481 | 0.001221 |
| canneal | LFU | 159919.00 | +6.43% | 94.69 | 280 | 5293 | 0.006163 |
| canneal | CLOCK | 126325.00 | -15.93% | 97.62 | 60 | 2359 | 0.001755 |
| streamcluster_pressure | QMAP-CrossAttn | 269095.00 | +0.00% | 97.00 | 548 | 5981 | 2.346490 |
| streamcluster_pressure | Kleio-lite | 331941.00 | +23.35% | 94.19 | 697 | 11613 | 0.065855 |
| streamcluster_pressure | PatternS-lite | 332226.00 | +23.46% | 94.15 | 629 | 11676 | 0.085045 |
| streamcluster_pressure | LRU | 305562.00 | +13.55% | 95.35 | 585 | 9276 | 0.000307 |
| streamcluster_pressure | RANDOM | 314183.00 | +16.76% | 95.01 | 777 | 9955 | 0.001226 |
| streamcluster_pressure | LFU | 361877.00 | +34.48% | 92.84 | 740 | 14311 | 0.006037 |
| streamcluster_pressure | CLOCK | 301767.00 | +12.14% | 95.52 | 574 | 8937 | 0.001555 |
| dedup_pressure | QMAP-CrossAttn | 201567.00 | +0.00% | 99.95 | 99 | 87 | 9.032020 |
| dedup_pressure | Kleio-lite | 201567.00 | +0.00% | 99.95 | 99 | 87 | 0.076486 |
| dedup_pressure | PatternS-lite | 201567.00 | +0.00% | 99.95 | 99 | 87 | 0.230308 |
| dedup_pressure | LRU | 201567.00 | +0.00% | 99.95 | 99 | 87 | 0.000525 |
| dedup_pressure | RANDOM | 202076.00 | +0.25% | 99.93 | 105 | 130 | 0.002075 |
| dedup_pressure | LFU | 203845.00 | +1.13% | 99.88 | 233 | 221 | 0.006810 |
| dedup_pressure | CLOCK | 201584.00 | +0.01% | 99.95 | 100 | 88 | 0.001760 |

Artifacts are listed in `summary.csv`.
