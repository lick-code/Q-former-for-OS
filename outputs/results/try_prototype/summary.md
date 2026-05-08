# QMAP Prototype Experiment

## Setup

- train trace: `dataset/processed/try_train.csv`
- test trace: `dataset/processed/try_test.csv`
- DRAM capacity: `128` pages
- history length: `10`
- candidate count: `64`
- lookahead: `256`
- page shift: `12`
- epochs: `10`
- batch size: `32`

## Results

| Policy | Hit rate (%) | NVM writes | Weighted cost | Migrations | Avg decision ms |
|---|---:|---:|---:|---:|---:|
| lru | 51.80 | 168 | 11660.00 | 836 | 0.000249 |
| random | 45.95 | 209 | 13029.00 | 953 | 0.000859 |
| lfu | 60.45 | 115 | 9651.00 | 663 | 0.022740 |
| clock | 47.10 | 205 | 12768.00 | 930 | 0.000952 |
| qmap | 59.60 | 115 | 9838.00 | 680 | 2.555562 |
