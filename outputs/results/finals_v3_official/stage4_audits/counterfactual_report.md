# CAPD Stage 4 G12 Counterfactual Audit

Identity: CAPD-MIC-1.0 / capd_finals_v3_0 / official / B=64 / K=8. Fingerprint bindings are in counterfactual_summary.json and per-workload JSONL.

Valid trace only; no test read. Metrics diagnose proxy-label consistency and are not system-performance claims.

| workload | variant | Spearman mean | top-1 any-hit | NDCG mean | indistinguishable |
|---|---|---:|---:|---:|---:|
| canneal | base | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | no_write | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | balanced_write | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | half_write | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | stronger_write | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | inactivity_only | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| canneal | coldness_only | 0.965174 | 1.000000 | 0.999387 | 0.965503 |
| canneal | no_inactivity | 0.965174 | 1.000000 | 0.999387 | 0.965503 |
| canneal | no_coldness | 0.965049 | 1.000000 | 0.999388 | 0.965503 |
| streamcluster_pressure | base | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | no_write | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | balanced_write | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | half_write | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | stronger_write | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | inactivity_only | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | coldness_only | 0.992795 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | no_inactivity | 0.992795 | 1.000000 | 0.999816 | 0.958084 |
| streamcluster_pressure | no_coldness | 0.992536 | 1.000000 | 0.999816 | 0.958084 |
| dedup_pressure | base | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | no_write | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | balanced_write | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | half_write | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | stronger_write | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | inactivity_only | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | coldness_only | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | no_inactivity | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
| dedup_pressure | no_coldness | 1.000000 | 1.000000 | 1.000000 | 0.998493 |
