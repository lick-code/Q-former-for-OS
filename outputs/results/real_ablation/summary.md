# Real QMAP Ablation

| workload | variant | cost | vs QMAP-Pool | NVM writes | migrations |
|---|---|---:|---:|---:|---:|
| streamcluster_pressure | QMAP-Pool | 264501.00 | +0.00% | 589 | 5541 |
| streamcluster_pressure | no_rw | 265905.00 | +0.53% | 592 | 5667 |
| streamcluster_pressure | no_cost | 265395.00 | +0.34% | 584 | 5625 |
| blackscholes | QMAP-Pool | 105983.00 | +0.00% | 32 | 525 |
| blackscholes | no_rw | 105961.00 | -0.02% | 32 | 523 |
| blackscholes | no_cost | 105983.00 | +0.00% | 32 | 525 |
