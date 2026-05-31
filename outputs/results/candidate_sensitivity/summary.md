# Candidate-count Sensitivity

Purpose: test whether QMAP-Pool's real-workload result depends on a single candidate_count setting.

## Setup

- workloads: `canneal`, `streamcluster_pressure`
- candidate_count: `4, 8, 16`
- history_length: `10`
- dram_capacity: `16` pages
- lookahead: `256`
- epochs: `10`
- batch_size: `32`
- model: `QMAP-Pool` (`ablation=mean_pool`)

## Results

| Workload | Candidate count | Best baseline | QMAP cost | Delta | QMAP migrations | Decisions | Avg decision ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 4 | 301767.00 (CLOCK) | 282349.00 | -6.43% | 7169 | 7169 | 2.301595 |
| streamcluster_pressure | 8 | 301767.00 (CLOCK) | 264501.00 | -12.35% | 5541 | 5541 | 2.383505 |
| streamcluster_pressure | 16 | 301767.00 (CLOCK) | 289085.00 | -4.20% | 7897 | 7897 | 2.366727 |
| canneal | 4 | 126178.00 (LRU) | 134802.00 | +6.83% | 3134 | 3134 | 2.377925 |
| canneal | 8 | 126178.00 (LRU) | 150559.00 | +19.32% | 4567 | 4567 | 2.429240 |
| canneal | 16 | 126178.00 (LRU) | 244261.00 | +93.58% | 12949 | 12949 | 2.396656 |

## Readout

- canneal: QMAP-Pool is worse than the best baseline for every tested candidate count.
- streamcluster_pressure: QMAP-Pool beats the best baseline for every tested candidate count.

## Artifacts

- Per-run JSONL/checkpoints/results are under `dataset/jsonl/candidate_sensitivity/`, `outputs/checkpoints/candidate_sensitivity/`, and `outputs/results/candidate_sensitivity/`.
- Each row was produced by the full JSONL -> train -> eval pipeline via `scripts/run_real_pilot.py`.
