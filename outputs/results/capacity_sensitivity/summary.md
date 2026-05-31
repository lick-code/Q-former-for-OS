# Capacity Sensitivity

Purpose: test whether the QMAP-Pool conclusion depends on the single `dram_capacity=16` setting.

## Setup

- workloads: `streamcluster_pressure, canneal`
- DRAM capacities: `8, 16, 32` pages
- policies: `LRU, RANDOM, LFU, CLOCK, QMAP-Pool`
- h/c/l: `10/8/256`
- epochs: `10`
- batch size: `32`
- QMAP model: `QMAP-Pool` (`ablation=mean_pool`)

## Results

| Workload | DRAM cap | Best baseline cost | QMAP cost | delta | QMAP migrations | decision count | note |
|---|---:|---:|---:|---:|---:|---:|---|
| streamcluster_pressure | 8 | 369999.00 (LRU) | 331072.00 | -10.52% | 11592 | 11592 |  |
| streamcluster_pressure | 16 | 301767.00 (CLOCK) | 264501.00 | -12.35% | 5541 | 5541 |  |
| streamcluster_pressure | 32 | 216577.00 (LRU) | 217150.00 | +0.26% | 1548 | 1548 |  |
| canneal | 8 | 190696.00 (LRU) | 314640.00 | +65.00% | 19176 | 19176 |  |
| canneal | 16 | 126178.00 (LRU) | 150559.00 | +19.32% | 4567 | 4567 |  |
| canneal | 32 | 101502.00 (LRU) | 101320.00 | -0.18% | 116 | 116 |  |

## Artifact Layout

- JSONL: `dataset/jsonl/capacity_sensitivity/<workload>/cap*/`
- checkpoints: `outputs/checkpoints/capacity_sensitivity/<workload>/cap*/`
- per-case results: `outputs/results/capacity_sensitivity/<workload>/cap*/`
