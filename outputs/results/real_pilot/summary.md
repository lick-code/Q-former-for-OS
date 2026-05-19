# Real 100k Pilot

## Setup

- run id: `real_pilot_100k_dram64`
- workloads: `parsec_blackscholes`, `parsec_canneal`, `parsec_streamcluster`, `parsec_dedup`
- policies: `LRU`, `Random`, `LFU`, `CLOCK`, `QMAP-Pool`
- input trace size: `100000` records per workload
- split policy: chronological `80000/10000/10000`
- DRAM capacity: `64` pages
- history length: `10`
- candidate count: `64`
- lookahead: `256`
- QMAP model: `QMAP-Pool` (`ablation=mean_pool`)
- epochs: `10`
- batch size: `32`
- device: `cpu`

Note: this Codex run wrote large generated JSONL/checkpoint artifacts to
`C:\Users\LKC_LE~1\AppData\Local\Temp\qmap_real_pilot_100k_dram64` because the
shell process could read the workspace but could not create new binary/runtime
files inside it. The Markdown/CSV summaries were copied back into this results
directory.

## Training Samples

| Workload | Train records | Generated QMAP samples |
|---|---:|---:|
| parsec_blackscholes | 80000 | 47 |
| parsec_canneal | 80000 | 111 |
| parsec_streamcluster | 80000 | 110 |
| parsec_dedup | 80000 | 60 |

## Replay Results

| Workload | Policy | Hit rate (%) | NVM writes | Cost | Migrations | Decisions | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|
| parsec_blackscholes | LRU | 99.50 | 4 | 10074.00 | 0 | 0 | 0.000000 |
| parsec_blackscholes | Random | 99.50 | 4 | 10074.00 | 0 | 0 | 0.000000 |
| parsec_blackscholes | LFU | 99.50 | 4 | 10074.00 | 0 | 0 | 0.000000 |
| parsec_blackscholes | CLOCK | 99.50 | 4 | 10074.00 | 0 | 0 | 0.000000 |
| parsec_blackscholes | QMAP-Pool | 99.50 | 4 | 10074.00 | 0 | 0 | 0.000000 |
| parsec_canneal | LRU | 99.69 | 2 | 10043.00 | 0 | 0 | 0.000000 |
| parsec_canneal | Random | 99.69 | 2 | 10043.00 | 0 | 0 | 0.000000 |
| parsec_canneal | LFU | 99.69 | 2 | 10043.00 | 0 | 0 | 0.000000 |
| parsec_canneal | CLOCK | 99.69 | 2 | 10043.00 | 0 | 0 | 0.000000 |
| parsec_canneal | QMAP-Pool | 99.69 | 2 | 10043.00 | 0 | 0 | 0.000000 |
| parsec_streamcluster | LRU | 99.69 | 1 | 10037.00 | 0 | 0 | 0.000000 |
| parsec_streamcluster | Random | 99.69 | 1 | 10037.00 | 0 | 0 | 0.000000 |
| parsec_streamcluster | LFU | 99.69 | 1 | 10037.00 | 0 | 0 | 0.000000 |
| parsec_streamcluster | CLOCK | 99.69 | 1 | 10037.00 | 0 | 0 | 0.000000 |
| parsec_streamcluster | QMAP-Pool | 99.69 | 1 | 10037.00 | 0 | 0 | 0.000000 |
| parsec_dedup | LRU | 99.90 | 7 | 10052.00 | 0 | 0 | 0.000000 |
| parsec_dedup | Random | 99.90 | 7 | 10052.00 | 0 | 0 | 0.000000 |
| parsec_dedup | LFU | 99.90 | 7 | 10052.00 | 0 | 0 | 0.000000 |
| parsec_dedup | CLOCK | 99.90 | 7 | 10052.00 | 0 | 0 | 0.000000 |
| parsec_dedup | QMAP-Pool | 99.90 | 7 | 10052.00 | 0 | 0 | 0.000000 |

## Interpretation

The real-trace pipeline is runnable end to end: processed CSV -> QMAP JSONL -> QMAP-Pool training -> LRU/Random/LFU/CLOCK/QMAP replay.

However, `dram_capacity=64` is still too large for this 100k pilot test split. All workloads have `migrations=0` and `decision_count=0`, so the replay never reaches a policy-dependent eviction decision. The pilot therefore validates the plumbing, but not replacement quality.

Next pressure run should use `dram_capacity=32` first, and `dram_capacity=16` if decisions are still near zero. If 100k remains too easy, move to 1M traces or choose a split/window with more than 64 active pages in the test segment.
