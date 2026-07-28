# CAPD NoVPN Ablation Report

Primary evidence: paired test-trace replay metrics. Training loss is recorded only for checkpoint selection and is not the main conclusion.

Seeds: `3136859, 42, 2026`. Standard deviation uses the sample definition (ddof=1).

## Per-workload paired summary

| workload | metric | Full mean | NoVPN mean | absolute delta | relative delta | direction |
|---|---|---:|---:|---:|---:|---|
| canneal | weighted cost | 227495 | 228173 | 678.333 | 0.301684% | positive: NoVPN has higher cost |
| canneal | hit rate | 0.987255 | 0.986947 | -0.000308333 | -0.0311928% | negative: NoVPN hit rate is lower |
| canneal | NVM reads | 2533 | 2594.67 | 61.6667 | 2.66538% | NoVPN - Full |
| canneal | NVM writes | 16 | 16 | 0 | 0% | NoVPN - Full |
| canneal | demotions | 2485 | 2546.67 | 61.6667 | 2.72135% | NoVPN - Full |
| canneal | average decision time (ms) | 3.65756 | 3.76711 | 0.109548 | 3.01711% | NoVPN - Full |
| streamcluster_pressure | weighted cost | 230628 | 231750 | 1122 | 0.486498% | positive: NoVPN has higher cost |
| streamcluster_pressure | hit rate | 0.98579 | 0.98528 | -0.00051 | -0.0517352% | negative: NoVPN hit rate is lower |
| streamcluster_pressure | NVM reads | 2841 | 2943 | 102 | 3.59029% | NoVPN - Full |
| streamcluster_pressure | NVM writes | 1 | 1 | 0 | 0% | NoVPN - Full |
| streamcluster_pressure | demotions | 2778 | 2880 | 102 | 3.67171% | NoVPN - Full |
| streamcluster_pressure | average decision time (ms) | 3.70096 | 4.80122 | 1.10026 | 29.7598% | NoVPN - Full |
| dedup_pressure | weighted cost | 1.04542e+06 | 1.0455e+06 | 77.3333 | 0.0073973% | positive: NoVPN has higher cost |
| dedup_pressure | hit rate | 0.996653 | 0.996647 | -6.66667e-06 | -0.000668905% | negative: NoVPN hit rate is lower |
| dedup_pressure | NVM reads | 1805.33 | 1811.33 | 6 | 0.332425% | NoVPN - Full |
| dedup_pressure | NVM writes | 1541.33 | 1542 | 0.666667 | 0.043262% | NoVPN - Full |
| dedup_pressure | demotions | 3282.67 | 3289.33 | 6.66667 | 0.203076% | NoVPN - Full |
| dedup_pressure | average decision time (ms) | 3.6868 | 3.72853 | 0.041729 | 1.13415% | NoVPN - Full |

## Interpretation framework

Apply the following framework after reviewing the replay metrics; the report intentionally does not hard-code percentage thresholds.

1. If NoVPN and Full are very close, the evidence suggests CAPD's gain mainly comes from PC, R/W, candidate state, and access context rather than absolute page identity.
2. If NoVPN is clearly worse but still outperforms external baselines, absolute VPN is a useful auxiliary signal, but CAPD is not completely dependent on it.
3. If NoVPN degrades to near or below external baselines, Full CAPD has a stronger within-run dependence on page identity and cross-run claims must be limited carefully.
4. If NoVPN is better, absolute VPN embedding may introduce within-run overfitting.

## Direction conventions

- Every delta is `NoVPN - Full`.
- Weighted-cost relative delta above zero means NoVPN is worse.
- Hit-rate relative delta above zero means NoVPN has a higher hit rate.
- NVM read/write, demotion, and decision-time deltas retain their direct numeric direction; interpret them jointly with weighted cost.

## Artifact coverage

- Per-seed paired rows: 9.
- Workload/metric summary rows: 18.
