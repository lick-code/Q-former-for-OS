# QMAP Ablation

## Setup

- train trace: `dataset/processed/writeheavy_train.csv`
- test trace: `dataset/processed/writeheavy_test.csv`
- variants: `full,no_cost`
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- loss weights: `write_sensitivity=8.0, migration_cost=4.0`
- NVM write cost: `8.0`
- device: `cuda`
- seed: `3136859`

## Full Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 73.30 | 7854.00 | 210 | 406 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes saved vs full | Writes delta (%) | Full writes reduction (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | complete QMAP baseline | 73.30 | +0.00 | 7854.00 | +0.00 | 210 | +0 | +0.00 | +0.00 | 3.056702 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 73.30 | +0.00 | 7860.00 | +0.08 | 211 | +1 | +0.48 | +0.47 | 3.057403 |
