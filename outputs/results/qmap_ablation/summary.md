# QMAP Ablation

## Setup

- train trace: `dataset/processed/try_train.csv`
- test trace: `dataset/processed/try_test.csv`
- variants: `cross_attention,no_pc,no_rw,no_cost`
- baseline model: `QMAP-CrossAttn` (`ablation=cross_attention`)
- h/c/d/l: `10/64/128/256`
- epochs: `10`
- batch size: `32`
- loss weights: `write_sensitivity=4.0, migration_cost=2.0`
- NVM write cost: `8.0`
- device: `cuda`
- seed: `3136859`

## QMAP-CrossAttn Baseline

| Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---:|---:|---:|---:|
| 59.70 | 10240.00 | 109 | 678 |

## Results

| Variant | Purpose | Hit rate (%) | Hit delta (pp) | Cost | Cost delta (%) | NVM writes | Writes delta vs QMAP-CrossAttn | Writes delta (%) | QMAP-CrossAttn writes delta (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cross_attention | Transformer-encoded sequence with candidate-page cross-attention | 59.70 | +0.00 | 10240.00 | +0.00 | 109 | +0 | +0.00 | +0.00 | 3.299315 |
| no_pc | remove program-counter context from the access sequence | 59.50 | -0.20 | 10296.00 | +0.55 | 111 | +2 | +1.83 | +1.80 | 3.381464 |
| no_rw | remove read/write type from the access sequence | 59.60 | -0.10 | 10268.00 | +0.27 | 110 | +1 | +0.92 | +0.91 | 3.271945 |
| no_cost | disable write-sensitivity and migration-cost loss terms | 59.75 | +0.05 | 10223.00 | -0.17 | 108 | -1 | -0.92 | -0.93 | 3.375620 |
