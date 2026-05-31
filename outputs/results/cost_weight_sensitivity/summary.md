# Cost-weight Sensitivity

Purpose: recompute weighted access cost from existing replay JSON counters without retraining or rerunning replay.

Formula:

`cost = hits * dram_access_cost + nvm_reads * nvm_read_cost + nvm_writes * nvm_write_cost + migrations * migration_cost`

## Cost Models

| Cost model | DRAM read/write | NVM read | NVM write | Migration |
|---|---:|---:|---:|---:|
| default | 1 | 2 | 8 | 10 |
| mild | 1 | 2 | 4 | 5 |
| write-heavy | 1 | 2 | 16 | 10 |
| migration-heavy | 1 | 2 | 8 | 20 |

## QMAP vs Best Baseline

| Cost model | streamcluster_pressure delta | blackscholes delta | canneal delta |
|---|---:|---:|---:|
| default | -12.35% | -0.91% | +19.32% |
| mild | -7.99% | -0.28% | +11.64% |
| write-heavy | -12.12% | -2.28% | +19.25% |
| migration-heavy | -18.21% | -0.73% | +31.10% |

## Detailed Summary

| workload | cost model | best baseline | best baseline cost | QMAP cost | delta | QMAP writes | QMAP migrations |
|---|---|---|---:|---:|---:|---:|---:|
| streamcluster_pressure | default | CLOCK | 301767.00 | 264501.00 | -12.35% | 589 | 5541 |
| streamcluster_pressure | mild | CLOCK | 254786.00 | 234440.00 | -7.99% | 589 | 5541 |
| streamcluster_pressure | write-heavy | CLOCK | 306359.00 | 269213.00 | -12.12% | 589 | 5541 |
| streamcluster_pressure | migration-heavy | CLOCK | 391137.00 | 319911.00 | -18.21% | 589 | 5541 |
| blackscholes | default | LFU | 106952.00 | 105983.00 | -0.91% | 32 | 525 |
| blackscholes | mild | LFU | 103518.00 | 103230.00 | -0.28% | 32 | 525 |
| blackscholes | write-heavy | LFU | 108720.00 | 106239.00 | -2.28% | 32 | 525 |
| blackscholes | migration-heavy | LFU | 112052.00 | 111233.00 | -0.73% | 32 | 525 |
| canneal | default | LRU | 126178.00 | 150559.00 | +19.32% | 51 | 4567 |
| canneal | mild | LRU | 114220.00 | 127520.00 | +11.64% | 51 | 4567 |
| canneal | write-heavy | LRU | 126594.00 | 150967.00 | +19.25% | 51 | 4567 |
| canneal | migration-heavy | LRU | 149678.00 | 196229.00 | +31.10% | 51 | 4567 |

## Interpretation

- `streamcluster_pressure`: QMAP-Pool beats the best baseline under every tested cost model.
- `blackscholes`: QMAP-Pool beats the best baseline under every tested cost model.
- `canneal`: QMAP-Pool remains worse than the best baseline under every tested cost model.
- These numbers reuse existing replay counters only; no checkpoint training or replay was run by this script.
