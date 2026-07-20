# QMAP Prototype Experiment

## Setup

- train trace: `/home/likc/Q-former-for-OS/dataset/processed/try_train.csv`
- test trace: `/home/likc/Q-former-for-OS/dataset/processed/try_test.csv`
- DRAM capacity: `16` pages
- history length: `10`
- candidate count: `8`
- lookahead: `256`
- QMAP model: `QMAP-CrossAttn` (`ablation=cross_attention`)
- page shift: `12`
- epochs: `1`
- batch size: `32`

## Results

| Policy | Hit rate (%) | NVM writes | Weighted cost | Migrations | Avg decision ms |
|---|---:|---:|---:|---:|---:|
| LRU | 8.45 | 405 | 24411.00 | 1815 | 0.000324 |
| RANDOM | 8.40 | 407 | 24434.00 | 1816 | 0.001179 |
| LFU | 12.45 | 382 | 23393.00 | 1735 | 0.005917 |
| CLOCK | 8.35 | 407 | 24445.00 | 1817 | 0.001406 |
| QMAP-CrossAttn | 10.10 | 379 | 23892.00 | 1782 | 1.446129 |
