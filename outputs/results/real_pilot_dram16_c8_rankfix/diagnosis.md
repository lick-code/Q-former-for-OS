# Real Pilot Diagnosis

## Replay Summary

| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |
|---|---|---:|---:|---:|---:|
| parsec_blackscholes | lru | 98.99 | 11023.0 | 85 | 85 |
| parsec_blackscholes | random | 98.33 | 11809.0 | 151 | 151 |
| parsec_blackscholes | lfu | 96.76 | 13548.0 | 308 | 308 |
| parsec_blackscholes | clock | 98.87 | 11155.0 | 97 | 97 |
| parsec_blackscholes | qmap | 98.85000000000001 | 11159.0 | 99 | 99 |
| parsec_canneal | lru | 94.17 | 16499.0 | 567 | 567 |
| parsec_canneal | random | 93.78 | 17012.0 | 606 | 606 |
| parsec_canneal | lfu | 95.98 | 14574.0 | 386 | 386 |
| parsec_canneal | clock | 94.47 | 16145.0 | 537 | 537 |
| parsec_canneal | qmap | 96.08 | 14398.0 | 376 | 376 |
| parsec_streamcluster | lru | 94.08999999999999 | 16587.0 | 575 | 575 |
| parsec_streamcluster | random | 93.73 | 17043.0 | 611 | 611 |
| parsec_streamcluster | lfu | 96.05 | 14473.0 | 379 | 379 |
| parsec_streamcluster | clock | 94.32000000000001 | 16280.0 | 552 | 552 |
| parsec_streamcluster | qmap | 96.2 | 14260.0 | 364 | 364 |
| parsec_dedup | lru | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | random | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | lfu | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | clock | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | qmap | 99.9 | 10052.0 | 0 | 0 |

## QMAP Victim Quality

| Workload | Decisions | Worse than LRU | Reuse <= 10 | Chosen future reuse | LRU future reuse | Top ranks |
|---|---:|---:|---:|---|---|---|
| parsec_blackscholes | 99 | 46 | 2 | median=140.0, p25=64.0, p75=362.0, inf=34/99 | median=239.5, p25=96.0, p75=425.5, inf=37/99 | [(7, 64), (6, 8), (2, 7), (0, 6), (5, 6), (4, 4), (3, 2), (1, 2)] |
| parsec_canneal | 376 | 182 | 5 | median=186.0, p25=146.0, p75=375.0, inf=15/376 | median=257.0, p25=103.0, p75=460.0, inf=27/376 | [(7, 173), (6, 95), (5, 36), (4, 30), (0, 24), (1, 14), (2, 2), (3, 2)] |
| parsec_streamcluster | 364 | 124 | 0 | median=204.0, p25=155.0, p75=381.0, inf=15/364 | median=383.0, p25=43.0, p75=484.0, inf=24/364 | [(7, 164), (0, 68), (4, 48), (5, 43), (6, 39), (3, 1), (1, 1)] |
| parsec_dedup | 0 | 0 | 0 | n/a | n/a | [] |

## Dedup Pressure Windows

| Start | End | Unique pages | Write ratio | LRU decisions @16 | LRU decisions @8 |
|---:|---:|---:|---:|---:|---:|
| 32000 | 42000 | 51 | 0.2944 | 489 | 766 |
| 16000 | 26000 | 46 | 0.2970 | 483 | 739 |
| 14000 | 24000 | 46 | 0.2979 | 477 | 737 |
| 33000 | 43000 | 52 | 0.2930 | 473 | 752 |
| 15000 | 25000 | 47 | 0.2979 | 473 | 738 |
| 13000 | 23000 | 46 | 0.2976 | 473 | 733 |
| 34000 | 44000 | 49 | 0.2948 | 464 | 746 |
| 36000 | 46000 | 57 | 0.2950 | 461 | 738 |
| 35000 | 45000 | 49 | 0.2933 | 461 | 745 |
| 12000 | 22000 | 45 | 0.3001 | 461 | 730 |
