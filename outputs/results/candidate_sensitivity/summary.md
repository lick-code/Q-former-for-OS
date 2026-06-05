# Candidate-count Sensitivity

Purpose: test whether QMAP-CrossAttn's real-workload result depends on a single candidate_count setting.

## Setup

- workloads: `canneal`, `streamcluster_pressure`
- candidate_count: `4, 8, 16`
- history_length: `10`
- dram_capacity: `16` pages
- lookahead: `256`
- epochs: `10`
- batch_size: `32`
- model: `QMAP-CrossAttn` (`ablation=cross_attention`)

## Results

| Workload | Candidate count | Best baseline | QMAP cost | Delta | QMAP migrations | Decisions | Avg decision ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 4 | 301767.00 (CLOCK) | 284587.00 | -5.69% | 7367 | 7367 | 2.298621 |
| streamcluster_pressure | 8 | 301767.00 (CLOCK) | 269095.00 | -10.83% | 5981 | 5981 | 2.325202 |
| streamcluster_pressure | 16 | 301767.00 (CLOCK) | 286669.00 | -5.00% | 7673 | 7673 | 2.365804 |
| canneal | 4 | 126178.00 (LRU) | 134851.00 | +6.87% | 3139 | 3139 | 2.416627 |
| canneal | 8 | 126178.00 (LRU) | 150263.00 | +19.09% | 4545 | 4545 | 2.454731 |
| canneal | 16 | 126178.00 (LRU) | 295968.00 | +134.56% | 17636 | 17636 | 2.338841 |

## Readout

- canneal: QMAP-CrossAttn is worse than the best baseline for every tested candidate count.
- streamcluster_pressure: QMAP-CrossAttn beats the best baseline for every tested candidate count.

## Artifacts

- Per-run JSONL/checkpoints/results are under `dataset/jsonl/candidate_sensitivity/`, `outputs/checkpoints/candidate_sensitivity/`, and `outputs/results/candidate_sensitivity/`.
- Each row was produced by the full JSONL -> train -> eval pipeline via `scripts/run_real_pilot.py`.
