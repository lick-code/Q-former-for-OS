# Real Pilot Diagnosis

## Replay Summary

| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |
|---|---|---:|---:|---:|---:|
| parsec_blackscholes | lru | 98.99 | 11023.0 | 85 | 85 |
| parsec_blackscholes | random | 98.33 | 11809.0 | 151 | 151 |
| parsec_blackscholes | lfu | 96.76 | 13548.0 | 308 | 308 |
| parsec_blackscholes | clock | 98.87 | 11155.0 | 97 | 97 |
| parsec_blackscholes | qmap | 87.38 | 24652.0 | 1246 | 1246 |
| parsec_canneal | lru | 94.17 | 16499.0 | 567 | 567 |
| parsec_canneal | random | 93.78 | 17012.0 | 606 | 606 |
| parsec_canneal | lfu | 95.98 | 14574.0 | 386 | 386 |
| parsec_canneal | clock | 94.47 | 16145.0 | 537 | 537 |
| parsec_canneal | qmap | 95.98 | 14274.0 | 386 | 386 |
| parsec_streamcluster | lru | 94.08999999999999 | 16587.0 | 575 | 575 |
| parsec_streamcluster | random | 93.73 | 17043.0 | 611 | 611 |
| parsec_streamcluster | lfu | 96.05 | 14473.0 | 379 | 379 |
| parsec_streamcluster | clock | 94.32000000000001 | 16280.0 | 552 | 552 |
| parsec_streamcluster | qmap | 95.94 | 14312.0 | 390 | 390 |
| parsec_dedup | lru | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | random | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | lfu | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | clock | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | qmap | 99.9 | 10052.0 | 0 | 0 |

## QMAP Victim Quality

| Workload | Decisions | Worse than LRU | Reuse <= 10 | Chosen future reuse | LRU future reuse | Top ranks |
|---|---:|---:|---:|---|---|---|
| parsec_blackscholes | 1246 | 1202 | 673 | median=8.0, p25=1.0, p75=24.0, inf=34/1246 | median=352.0, p25=254.0, p75=416.0, inf=1149/1246 | [(15, 1153), (14, 40), (13, 9), (12, 8), (9, 7), (0, 6), (11, 5), (5, 5)] |
| parsec_canneal | 386 | 164 | 12 | median=226.0, p25=185.0, p75=246.5, inf=15/386 | median=134.0, p25=72.2, p75=369.0, inf=40/386 | [(9, 98), (14, 97), (13, 77), (10, 46), (11, 41), (12, 12), (15, 3), (1, 3)] |
| parsec_streamcluster | 390 | 142 | 9 | median=226.0, p25=189.0, p75=255.0, inf=15/390 | median=135.0, p25=73.0, p75=277.0, inf=19/390 | [(9, 104), (14, 96), (13, 79), (10, 46), (11, 40), (12, 10), (8, 5), (0, 3)] |
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
