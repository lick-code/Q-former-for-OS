# Real Pilot Diagnosis

## Replay Summary

| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |
|---|---|---:|---:|---:|---:|
| parsec_streamcluster | lru | 95.354 | 305562.0 | 9276 | 9276 |
| parsec_streamcluster | random | 95.0145 | 314183.0 | 9955 | 9955 |
| parsec_streamcluster | lfu | 92.8365 | 361877.0 | 14311 | 14311 |
| parsec_streamcluster | clock | 95.5235 | 301767.0 | 8937 | 8937 |
| parsec_streamcluster | qmap | 95.84949999999999 | 294643.0 | 8285 | 8285 |
| parsec_dedup | lru | 99.9485 | 201567.0 | 87 | 87 |
| parsec_dedup | random | 99.92699999999999 | 202076.0 | 130 | 130 |
| parsec_dedup | lfu | 99.8815 | 203845.0 | 221 | 221 |
| parsec_dedup | clock | 99.94800000000001 | 201584.0 | 88 | 88 |
| parsec_dedup | qmap | 99.9485 | 201567.0 | 87 | 87 |

## QMAP Victim Quality

| Workload | Decisions | Worse than LRU | Reuse <= 10 | Chosen future reuse | LRU future reuse | Top ranks |
|---|---:|---:|---:|---|---|---|
| parsec_streamcluster | 8285 | 903 | 269 | median=137.0, p25=91.0, p75=422.0, inf=177/8285 | median=88.0, p25=57.0, p75=152.0, inf=101/8285 | [(1, 5728), (0, 2557)] |
| parsec_dedup | 87 | 0 | 0 | all inf | all inf | [(0, 87)] |

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
