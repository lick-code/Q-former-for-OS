# QMAP Prototype Experiment

## Setup

- train trace: `D:\计算机系统大赛\功能赛道\cache_replacement\dataset\processed\try_train.csv`
- test trace: `D:\计算机系统大赛\功能赛道\cache_replacement\dataset\processed\try_test.csv`
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
| lru | 51.80 | 168 | 11660.00 | 836 | 0.000119 |
| random | 45.95 | 209 | 13029.00 | 953 | 0.000343 |
| lfu | 60.45 | 115 | 9651.00 | 663 | 0.015102 |
| clock | 47.10 | 205 | 12768.00 | 930 | 0.000410 |
