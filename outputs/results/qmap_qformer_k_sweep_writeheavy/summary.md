# QMAP Q-Former K Sweep

## Setup

- train trace: `dataset/processed/writeheavy_train.csv`
- test trace: `dataset/processed/writeheavy_test.csv`
- K values: `1,2,3,4,5,6,8`
- baseline K: `4`
- h/c/d/l: `10/64/128/256`
- epochs: `20`
- batch size: `32`
- lr: `0.0001`
- weight decay: `0.0`
- dropout: `0.0`
- layers/heads: `1/2`
- device: `cuda`
- seed: `3136859`

## Best Observed

- lowest weighted cost: `K=2` with `7810.00`
- highest hit rate: `K=2` with `73.50%`
- fewest NVM writes: `K=5` with `209`

## Results

| K | Hit rate (%) | Hit delta vs baseline (pp) | Cost | Cost delta vs baseline (%) | NVM writes | Writes delta vs baseline (%) | NVM reads | Migrations | Decision ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 73.45 | +0.05 | 7821.00 | -0.45 | 210 | -1.87 | 321 | 403 | 3.599028 |
| 2 | 73.50 | +0.10 | 7810.00 | -0.59 | 210 | -1.87 | 320 | 402 | 3.108128 |
| 3 | 73.25 | -0.15 | 7901.00 | +0.57 | 216 | +0.93 | 319 | 407 | 3.031829 |
| 4 | 73.40 | +0.00 | 7856.00 | +0.00 | 214 | +0.00 | 318 | 404 | 3.795502 |
| 5 | 73.45 | +0.05 | 7815.00 | -0.52 | 209 | -2.34 | 322 | 403 | 3.677597 |
| 6 | 73.20 | -0.20 | 7876.00 | +0.25 | 210 | -1.87 | 326 | 408 | 3.377931 |
| 8 | 73.35 | -0.05 | 7855.00 | -0.01 | 212 | -0.93 | 321 | 405 | 3.338933 |
