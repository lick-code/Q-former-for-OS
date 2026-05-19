# Real Pilot Diagnosis

## Replay Summary

| Workload | Policy | Hit rate (%) | Cost | Migrations | Decisions |
|---|---|---:|---:|---:|---:|
| parsec_blackscholes | lru | 98.99 | 11023.0 | 85 | 85 |
| parsec_blackscholes | random | 98.33 | 11809.0 | 151 | 151 |
| parsec_blackscholes | lfu | 96.76 | 13548.0 | 308 | 308 |
| parsec_blackscholes | clock | 98.87 | 11155.0 | 97 | 97 |
| parsec_blackscholes | qmap | 92.42 | 18406.0 | 742 | 742 |
| parsec_canneal | lru | 94.17 | 16499.0 | 567 | 567 |
| parsec_canneal | random | 93.78 | 17012.0 | 606 | 606 |
| parsec_canneal | lfu | 95.98 | 14574.0 | 386 | 386 |
| parsec_canneal | clock | 94.47 | 16145.0 | 537 | 537 |
| parsec_canneal | qmap | 94.63000000000001 | 16029.0 | 521 | 521 |
| parsec_streamcluster | lru | 94.08999999999999 | 16587.0 | 575 | 575 |
| parsec_streamcluster | random | 93.73 | 17043.0 | 611 | 611 |
| parsec_streamcluster | lfu | 96.05 | 14473.0 | 379 | 379 |
| parsec_streamcluster | clock | 94.32000000000001 | 16280.0 | 552 | 552 |
| parsec_streamcluster | qmap | 94.27 | 16437.0 | 557 | 557 |
| parsec_dedup | lru | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | random | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | lfu | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | clock | 99.9 | 10052.0 | 0 | 0 |
| parsec_dedup | qmap | 99.9 | 10052.0 | 0 | 0 |

## QMAP Victim Quality

| Workload | Decisions | Worse than LRU | Reuse <= 10 | Chosen future reuse | LRU future reuse | Top ranks |
|---|---:|---:|---:|---|---|---|
| parsec_blackscholes | 742 | 698 | 232 | median=23.0, p25=10.0, p75=36.2, inf=34/742 | median=378.0, p25=215.0, p75=499.0, inf=649/742 | [(15, 379), (14, 260), (13, 46), (10, 10), (12, 7), (7, 6), (11, 6), (8, 5)] |
| parsec_canneal | 521 | 485 | 37 | median=221.0, p25=140.0, p75=235.0, inf=15/521 | median=35.0, p25=28.0, p75=62.0, inf=500/521 | [(13, 114), (14, 66), (12, 62), (15, 56), (9, 45), (11, 42), (8, 41), (7, 32)] |
| parsec_streamcluster | 557 | 530 | 49 | median=218.0, p25=140.0, p75=234.8, inf=15/557 | median=50.0, p25=34.0, p75=70.2, inf=545/557 | [(13, 111), (14, 82), (15, 75), (12, 58), (9, 50), (8, 42), (11, 40), (10, 39)] |
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
