# Real QMAP Ablation

| workload | variant | cost | vs QMAP-CrossAttn | NVM writes | migrations |
|---|---|---:|---:|---:|---:|
| streamcluster_pressure | QMAP-CrossAttn | 269095.00 | +0.00% | 548 | 5981 |
| streamcluster_pressure | no_rw | 265905.00 | -1.19% | 592 | 5667 |
| streamcluster_pressure | no_cost | 265395.00 | -1.37% | 584 | 5625 |
| blackscholes | QMAP-CrossAttn | 110557.00 | +0.00% | 116 | 895 |
| blackscholes | no_rw | 105961.00 | -4.16% | 32 | 523 |
| blackscholes | no_cost | 105983.00 | -4.14% | 32 | 525 |
