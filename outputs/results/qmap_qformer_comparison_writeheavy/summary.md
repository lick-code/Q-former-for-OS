# QMAP Q-Former Comparison

## Setup

- train trace: `dataset/processed/writeheavy_train.csv`
- test trace: `dataset/processed/writeheavy_test.csv`
- baseline: `mean_pool`
- profiles: `full,mean_pool,qformer_light,qformer_tiny`
- h/c/d/l: `10/64/128/256`
- epochs: `20`
- batch size: `32`
- lr: `0.0001`
- device: `cuda`
- seed: `3136859`

## Results

| Profile | Purpose | Q | Layers | Dropout | Weight decay | Hit rate (%) | Hit delta vs mean_pool (pp) | Cost | Cost delta vs mean_pool (%) | NVM writes | Writes delta vs mean_pool (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | original Q-Former capacity | 4 | 1 | 0 | 0 | 73.40 | +0.05 | 7856.00 | +0.24 | 214 | +2.39 | 3.017027 |
| mean_pool | formal mean-pooling baseline | 4 | 1 | 0 | 0 | 73.35 | +0.00 | 7837.00 | +0.00 | 209 | +0.00 | 2.768111 |
| qformer_light | lighter Q-Former with fewer queries and regularization | 2 | 1 | 0.1 | 0.0001 | 72.55 | -0.80 | 8061.00 | +2.86 | 217 | +3.83 | 2.982777 |
| qformer_tiny | minimal one-query Q-Former with regularization | 1 | 1 | 0.1 | 0.0001 | 73.15 | -0.20 | 7905.00 | +0.87 | 213 | +1.91 | 2.994798 |
