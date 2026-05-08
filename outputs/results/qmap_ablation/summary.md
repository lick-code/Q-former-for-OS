# QMAP Ablation

## Setup

- train trace: `dataset/processed/try_train.csv`
- test trace: `dataset/processed/try_test.csv`
- variants: `full,no_pc,no_rw,no_qformer,no_cost`
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- device: `cuda`
- seed: `3136859`

## Full Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 59.30 | 9904.00 | 115 | 686 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes delta (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| full | complete QMAP baseline | 59.30 | +0.00 | 9904.00 | +0.00 | 115 | +0.00 | 5.121512 |
| no_pc | remove program-counter context from the access sequence | 59.65 | +0.35 | 9821.00 | -0.84 | 112 | -2.61 | 6.624588 |
| no_rw | remove read/write type from the access sequence | 59.85 | +0.55 | 9781.00 | -1.24 | 114 | -0.87 | 11.581924 |
| no_qformer | replace Q-Former query aggregation with mean pooling | 60.00 | +0.70 | 9738.00 | -1.68 | 109 | -5.22 | 7.419675 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 59.40 | +0.10 | 9884.00 | -0.20 | 116 | +0.87 | 5.029773 |
