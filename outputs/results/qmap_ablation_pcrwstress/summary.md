# QMAP Ablation

## Setup

- train trace: `dataset/processed/pcrwstress_train.csv`
- test trace: `dataset/processed/pcrwstress_test.csv`
- variants: `full,no_pc,no_rw,mean_pool,no_cost`
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- loss weights: `write_sensitivity=4.0, migration_cost=2.0`
- NVM write cost: `8.0`
- device: `cuda`
- seed: `3136859`

## Full Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 74.65 | 6441.00 | 24 | 379 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes saved vs full | Writes delta (%) | Full writes reduction (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | complete QMAP baseline | 74.65 | +0.00 | 6441.00 | +0.00 | 24 | +0 | +0.00 | +0.00 | 4.715566 |
| no_pc | remove program-counter context from the access sequence | 74.30 | -0.35 | 6518.00 | +1.20 | 24 | +0 | +0.00 | +0.00 | 3.245345 |
| no_rw | remove read/write type from the access sequence | 74.35 | -0.30 | 6507.00 | +1.02 | 24 | +0 | +0.00 | +0.00 | 3.192424 |
| mean_pool | formal mean-pooling baseline without Q-Former queries | 75.75 | +1.10 | 6199.00 | -3.76 | 24 | +0 | +0.00 | +0.00 | 2.937993 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 74.80 | +0.15 | 6408.00 | -0.51 | 24 | +0 | +0.00 | +0.00 | 3.097983 |
