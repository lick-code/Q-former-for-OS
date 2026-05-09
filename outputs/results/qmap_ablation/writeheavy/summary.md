# QMAP Ablation

## Setup

- train trace: `dataset/processed/writeheavy_train.csv`
- test trace: `dataset/processed/writeheavy_test.csv`
- variants: `full,no_pc,no_rw,no_qformer,no_cost`
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- device: `cuda`
- seed: `3136859`

## Full Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 73.45 | 6979.00 | 209 | 403 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes delta (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| full | complete QMAP baseline | 73.45 | +0.00 | 6979.00 | +0.00 | 209 | +0.00 | 3.176137 |
| no_pc | remove program-counter context from the access sequence | 73.25 | -0.20 | 7027.00 | +0.69 | 211 | +0.96 | 3.129427 |
| no_rw | remove read/write type from the access sequence | 73.30 | -0.15 | 7016.00 | +0.53 | 211 | +0.96 | 3.650503 |
| no_qformer | replace Q-Former query aggregation with mean pooling | 73.15 | -0.30 | 7051.00 | +1.03 | 212 | +1.44 | 2.970084 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 73.30 | -0.15 | 7016.00 | +0.53 | 211 | +0.96 | 3.132808 |
