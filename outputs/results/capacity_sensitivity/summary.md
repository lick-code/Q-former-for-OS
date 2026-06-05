# Capacity Sensitivity

Purpose: test whether the QMAP-CrossAttn conclusion depends on the single `dram_capacity=16` setting.

## Setup

- workloads: `streamcluster_pressure, canneal`
- DRAM capacities: `8, 16, 32` pages
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-CrossAttn`
- h/c/l: `10/8/256`
- epochs: `10`
- batch size: `32`
- QMAP model: `QMAP-CrossAttn` (`ablation=cross_attention`)

## Results

| Workload | DRAM cap | Best baseline cost | QMAP cost | delta | QMAP migrations | decision count | note |
|---|---:|---:|---:|---:|---:|---:|---|
| streamcluster_pressure | 8 | 369999.00 (LRU) | 332660.00 | -10.09% | 11738 | 11738 |  |
| streamcluster_pressure | 16 | 301767.00 (CLOCK) | 269095.00 | -10.83% | 5981 | 5981 |  |
| streamcluster_pressure | 32 | 216577.00 (LRU) | 217348.00 | +0.36% | 1566 | 1566 |  |
| canneal | 8 | 190696.00 (LRU) | 352852.00 | +85.03% | 22334 | 22334 |  |
| canneal | 16 | 126178.00 (LRU) | 150263.00 | +19.09% | 4545 | 4545 |  |
| canneal | 32 | 101502.00 (LRU) | 101298.00 | -0.20% | 114 | 114 |  |

## Artifact Layout

- JSONL: `dataset/jsonl/capacity_sensitivity/<workload>/cap*/`
- checkpoints: `outputs/checkpoints/capacity_sensitivity/<workload>/cap*/`
- per-case results: `outputs/results/capacity_sensitivity/<workload>/cap*/`
