# QMAP Ablation

## Setup

- train trace: `dataset/processed/phasechange_train.csv`
- test trace: `dataset/processed/phasechange_test.csv`
- variants: `full,no_pc,no_rw,no_qformer,no_cost`
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- device: `cuda`
- seed: `3136859`

## Full Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 61.25 | 9589.00 | 172 | 647 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes delta (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| full | complete QMAP baseline | 61.25 | +0.00 | 9589.00 | +0.00 | 172 | +0.00 | 2.634314 |
| no_pc | remove program-counter context from the access sequence | 61.15 | -0.10 | 9607.00 | +0.19 | 170 | -1.16 | 2.587061 |
| no_rw | remove read/write type from the access sequence | 61.20 | -0.05 | 9598.00 | +0.09 | 171 | -0.58 | 2.920913 |
| no_qformer | replace Q-Former query aggregation with mean pooling | 64.90 | +3.65 | 8740.00 | -8.85 | 149 | -13.37 | 2.405672 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 61.20 | -0.05 | 9598.00 | +0.09 | 171 | -0.58 | 2.961164 |
