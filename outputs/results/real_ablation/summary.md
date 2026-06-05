# Real QMAP Ablation

| workload | variant | cost | vs QMAP-CrossAttn | NVM writes | migrations |
|---|---|---:|---:|---:|---:|
| streamcluster_pressure | QMAP-CrossAttn | 269095.00 | +0.00% | 548 | 5981 |
| streamcluster_pressure | no_rw | 267644.00 | -0.54% | 550 | 5848 |
| streamcluster_pressure | no_cost | 269174.00 | +0.03% | 563 | 5980 |
| blackscholes | QMAP-CrossAttn | 110557.00 | +0.00% | 116 | 895 |
| blackscholes | no_rw | 106302.00 | -3.85% | 32 | 554 |
| blackscholes | no_cost | 105752.00 | -4.35% | 32 | 504 |
