# CAPD Stage 4 Multi-seed Training

Identity: CAPD-MIC-1.0 / capd_finals_v3_0 / official / B=64 / K=8. Full per-run bindings are in stage4_training.csv.

Nine independent models; best epoch selected only by valid loss. These are stability diagnostics, not performance gains.

| workload | seed | best epoch | best valid loss | final train loss | seconds |
|---|---:|---:|---:|---:|---:|
| canneal | 3136859 | 10 | -0.03559598 | -0.05658842 | 53.02 |
| canneal | 42 | 10 | -0.03504672 | -0.05633408 | 51.27 |
| canneal | 2026 | 10 | -0.03549373 | -0.05660584 | 51.90 |
| streamcluster_pressure | 3136859 | 10 | -0.04698838 | -0.05216065 | 62.14 |
| streamcluster_pressure | 42 | 8 | -0.04704834 | -0.05201178 | 61.55 |
| streamcluster_pressure | 2026 | 10 | -0.04697556 | -0.05216767 | 62.76 |
| dedup_pressure | 3136859 | 1 | -0.00117816 | 0.00000000 | 35.78 |
| dedup_pressure | 42 | 1 | -0.00117863 | 0.00000000 | 35.20 |
| dedup_pressure | 2026 | 1 | -0.00117817 | 0.00000000 | 36.03 |

Aggregates use the sample standard deviation across the three frozen seeds.
