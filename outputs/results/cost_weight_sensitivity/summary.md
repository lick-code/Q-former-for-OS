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
| default | -10.83% | +3.37% | +2.45% |
| mild | -6.98% | +2.03% | +1.48% |
| write-heavy | -10.73% | +2.54% | +2.44% |
| migration-heavy | -15.91% | +6.65% | +3.94% |

## Detailed Summary

| workload | cost model | best baseline | best baseline cost | QMAP cost | delta | QMAP writes | QMAP migrations |
|---|---|---|---:|---:|---:|---:|---:|
| streamcluster_pressure | default | CLOCK | 301767.00 | 269095.00 | -10.83% | 548 | 5981 |
| streamcluster_pressure | mild | CLOCK | 254786.00 | 236998.00 | -6.98% | 548 | 5981 |
| streamcluster_pressure | write-heavy | CLOCK | 306359.00 | 273479.00 | -10.73% | 548 | 5981 |
| streamcluster_pressure | migration-heavy | CLOCK | 391137.00 | 328905.00 | -15.91% | 548 | 5981 |
| blackscholes | default | LFU | 106952.00 | 110557.00 | +3.37% | 116 | 895 |
| blackscholes | mild | LFU | 103518.00 | 105618.00 | +2.03% | 116 | 895 |
| blackscholes | write-heavy | LFU | 108720.00 | 111485.00 | +2.54% | 116 | 895 |
| blackscholes | migration-heavy | LFU | 112052.00 | 119507.00 | +6.65% | 116 | 895 |
| canneal | default | LRU | 126178.00 | 129269.00 | +2.45% | 52 | 2631 |
| canneal | mild | LRU | 114220.00 | 115906.00 | +1.48% | 52 | 2631 |
| canneal | write-heavy | LRU | 126594.00 | 129685.00 | +2.44% | 52 | 2631 |
| canneal | migration-heavy | LRU | 149678.00 | 155579.00 | +3.94% | 52 | 2631 |

## Per-policy Reweighted Costs

| workload | cost model | policy | cost | hits | NVM reads | NVM writes | migrations |
|---|---|---|---:|---:|---:|---:|---:|
| streamcluster_pressure | default | LRU | 305562.00 | 190708 | 8707 | 585 | 9276 |
| streamcluster_pressure | default | RANDOM | 314183.00 | 190029 | 9194 | 777 | 9955 |
| streamcluster_pressure | default | LFU | 361877.00 | 185673 | 13587 | 740 | 14311 |
| streamcluster_pressure | default | CLOCK | 301767.00 | 191047 | 8379 | 574 | 8937 |
| streamcluster_pressure | default | QMAP | 269095.00 | 194003 | 5449 | 548 | 5981 |
| blackscholes | default | LRU | 112958.00 | 98886 | 970 | 144 | 1098 |
| blackscholes | default | RANDOM | 115505.00 | 98655 | 1200 | 145 | 1329 |
| blackscholes | default | LFU | 106952.00 | 99474 | 305 | 221 | 510 |
| blackscholes | default | CLOCK | 110437.00 | 99095 | 798 | 107 | 889 |
| blackscholes | default | QMAP | 110557.00 | 99089 | 795 | 116 | 895 |
| canneal | default | LRU | 126178.00 | 97634 | 2314 | 52 | 2350 |
| canneal | default | RANDOM | 139465.00 | 96503 | 3304 | 193 | 3481 |
| canneal | default | LFU | 159919.00 | 94691 | 5029 | 280 | 5293 |
| canneal | default | CLOCK | 126325.00 | 97625 | 2315 | 60 | 2359 |
| canneal | default | QMAP | 129269.00 | 97353 | 2595 | 52 | 2631 |
| streamcluster_pressure | mild | LRU | 256842.00 | 190708 | 8707 | 585 | 9276 |
| streamcluster_pressure | mild | RANDOM | 261300.00 | 190029 | 9194 | 777 | 9955 |
| streamcluster_pressure | mild | LFU | 287362.00 | 185673 | 13587 | 740 | 14311 |
| streamcluster_pressure | mild | CLOCK | 254786.00 | 191047 | 8379 | 574 | 8937 |
| streamcluster_pressure | mild | QMAP | 236998.00 | 194003 | 5449 | 548 | 5981 |
| blackscholes | mild | LRU | 106892.00 | 98886 | 970 | 144 | 1098 |
| blackscholes | mild | RANDOM | 108280.00 | 98655 | 1200 | 145 | 1329 |
| blackscholes | mild | LFU | 103518.00 | 99474 | 305 | 221 | 510 |
| blackscholes | mild | CLOCK | 105564.00 | 99095 | 798 | 107 | 889 |
| blackscholes | mild | QMAP | 105618.00 | 99089 | 795 | 116 | 895 |
| canneal | mild | LRU | 114220.00 | 97634 | 2314 | 52 | 2350 |
| canneal | mild | RANDOM | 121288.00 | 96503 | 3304 | 193 | 3481 |
| canneal | mild | LFU | 132334.00 | 94691 | 5029 | 280 | 5293 |
| canneal | mild | CLOCK | 114290.00 | 97625 | 2315 | 60 | 2359 |
| canneal | mild | QMAP | 115906.00 | 97353 | 2595 | 52 | 2631 |
| streamcluster_pressure | write-heavy | LRU | 310242.00 | 190708 | 8707 | 585 | 9276 |
| streamcluster_pressure | write-heavy | RANDOM | 320399.00 | 190029 | 9194 | 777 | 9955 |
| streamcluster_pressure | write-heavy | LFU | 367797.00 | 185673 | 13587 | 740 | 14311 |
| streamcluster_pressure | write-heavy | CLOCK | 306359.00 | 191047 | 8379 | 574 | 8937 |
| streamcluster_pressure | write-heavy | QMAP | 273479.00 | 194003 | 5449 | 548 | 5981 |
| blackscholes | write-heavy | LRU | 114110.00 | 98886 | 970 | 144 | 1098 |
| blackscholes | write-heavy | RANDOM | 116665.00 | 98655 | 1200 | 145 | 1329 |
| blackscholes | write-heavy | LFU | 108720.00 | 99474 | 305 | 221 | 510 |
| blackscholes | write-heavy | CLOCK | 111293.00 | 99095 | 798 | 107 | 889 |
| blackscholes | write-heavy | QMAP | 111485.00 | 99089 | 795 | 116 | 895 |
| canneal | write-heavy | LRU | 126594.00 | 97634 | 2314 | 52 | 2350 |
| canneal | write-heavy | RANDOM | 141009.00 | 96503 | 3304 | 193 | 3481 |
| canneal | write-heavy | LFU | 162159.00 | 94691 | 5029 | 280 | 5293 |
| canneal | write-heavy | CLOCK | 126805.00 | 97625 | 2315 | 60 | 2359 |
| canneal | write-heavy | QMAP | 129685.00 | 97353 | 2595 | 52 | 2631 |
| streamcluster_pressure | migration-heavy | LRU | 398322.00 | 190708 | 8707 | 585 | 9276 |
| streamcluster_pressure | migration-heavy | RANDOM | 413733.00 | 190029 | 9194 | 777 | 9955 |
| streamcluster_pressure | migration-heavy | LFU | 504987.00 | 185673 | 13587 | 740 | 14311 |
| streamcluster_pressure | migration-heavy | CLOCK | 391137.00 | 191047 | 8379 | 574 | 8937 |
| streamcluster_pressure | migration-heavy | QMAP | 328905.00 | 194003 | 5449 | 548 | 5981 |
| blackscholes | migration-heavy | LRU | 123938.00 | 98886 | 970 | 144 | 1098 |
| blackscholes | migration-heavy | RANDOM | 128795.00 | 98655 | 1200 | 145 | 1329 |
| blackscholes | migration-heavy | LFU | 112052.00 | 99474 | 305 | 221 | 510 |
| blackscholes | migration-heavy | CLOCK | 119327.00 | 99095 | 798 | 107 | 889 |
| blackscholes | migration-heavy | QMAP | 119507.00 | 99089 | 795 | 116 | 895 |
| canneal | migration-heavy | LRU | 149678.00 | 97634 | 2314 | 52 | 2350 |
| canneal | migration-heavy | RANDOM | 174275.00 | 96503 | 3304 | 193 | 3481 |
| canneal | migration-heavy | LFU | 212849.00 | 94691 | 5029 | 280 | 5293 |
| canneal | migration-heavy | CLOCK | 149915.00 | 97625 | 2315 | 60 | 2359 |
| canneal | migration-heavy | QMAP | 155579.00 | 97353 | 2595 | 52 | 2631 |

## Interpretation

- `streamcluster_pressure`: QMAP-CrossAttn beats the best baseline under every tested cost model.
- `blackscholes`: QMAP-CrossAttn remains worse than the best baseline under every tested cost model.
- `canneal`: QMAP-CrossAttn remains worse than the best baseline under every tested cost model.
- These numbers reuse existing replay counters only; no checkpoint training or replay was run by this script.
