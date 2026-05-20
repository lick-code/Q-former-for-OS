# Real Pilot Diagnosis

## Replay Summary

| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |
|---|---|---:|---:|---:|---:|
| parsec_blackscholes | lru | 98.886 | 112958.0 | 1098 | 1098 |
| parsec_blackscholes | random | 98.655 | 115505.0 | 1329 | 1329 |
| parsec_blackscholes | lfu | 99.47399999999999 | 106952.0 | 510 | 510 |
| parsec_blackscholes | clock | 99.095 | 110437.0 | 889 | 889 |
| parsec_blackscholes | qmap | 99.098 | 110602.0 | 886 | 886 |
| parsec_canneal | lru | 97.634 | 126178.0 | 2350 | 2350 |
| parsec_canneal | random | 96.503 | 139465.0 | 3481 | 3481 |
| parsec_canneal | lfu | 94.691 | 159919.0 | 5293 | 5293 |
| parsec_canneal | clock | 97.625 | 126325.0 | 2359 | 2359 |
| parsec_canneal | qmap | 97.31400000000001 | 129698.0 | 2670 | 2670 |
| parsec_streamcluster | lru | 99.991 | 100033.0 | 0 | 0 |
| parsec_streamcluster | random | 99.991 | 100033.0 | 0 | 0 |
| parsec_streamcluster | lfu | 99.991 | 100033.0 | 0 | 0 |
| parsec_streamcluster | clock | 99.991 | 100033.0 | 0 | 0 |
| parsec_streamcluster | qmap | 99.991 | 100033.0 | 0 | 0 |
| parsec_dedup | lru | 99.946 | 100734.0 | 38 | 38 |
| parsec_dedup | random | 99.928 | 100968.0 | 56 | 56 |
| parsec_dedup | lfu | 99.89 | 101686.0 | 94 | 94 |
| parsec_dedup | clock | 99.945 | 100751.0 | 39 | 39 |
| parsec_dedup | qmap | 99.946 | 100734.0 | 38 | 38 |

## QMAP Victim Quality

| Workload | Decisions | Worse than LRU | Reuse <= 10 | Chosen future reuse | LRU future reuse | Top ranks |
|---|---:|---:|---:|---|---|---|
| parsec_blackscholes | 886 | 75 | 58 | median=137.0, p25=29.0, p75=316.0, inf=5/886 | median=67.0, p25=27.0, p75=169.0, inf=10/886 | [(0, 454), (1, 432)] |
| parsec_canneal | 2670 | 1276 | 228 | median=158.0, p25=54.0, p75=292.0, inf=73/2670 | median=150.0, p25=97.8, p75=243.2, inf=1134/2670 | [(1, 1862), (0, 808)] |
| parsec_streamcluster | 0 | 0 | 0 | n/a | n/a | [] |
| parsec_dedup | 38 | 0 | 0 | all inf | all inf | [(0, 38)] |

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
