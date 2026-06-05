# Stage 7 Seed Stability

Purpose: answer whether the QMAP-CrossAttn result is an accidental training-seed outcome.

## Per-seed Results

| workload | seed | QMAP cost | best baseline | delta | migrations | writes |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 3136859 | 269095.00 | 301767.00 (CLOCK) | -10.83% | 5981 | 548 |
| streamcluster_pressure | 42 | 266439.00 | 301767.00 (CLOCK) | -11.71% | 5715 | 593 |
| streamcluster_pressure | 2026 | 269501.00 | 301767.00 (CLOCK) | -10.69% | 5995 | 590 |
| blackscholes | 3136859 | 105983.00 | 106952.00 (LFU) | -0.91% | 525 | 32 |
| blackscholes | 42 | 109794.00 | 106952.00 (LFU) | +2.66% | 878 | 20 |
| blackscholes | 2026 | 105862.00 | 106952.00 (LFU) | -1.02% | 514 | 32 |
| canneal | 3136859 | 150263.00 | 126178.00 (LRU) | +19.09% | 4545 | 42 |
| canneal | 42 | 144827.00 | 126178.00 (LRU) | +14.78% | 4041 | 60 |
| canneal | 2026 | 147081.00 | 126178.00 (LRU) | +16.57% | 4253 | 47 |

## Stability Summary

| workload | mean delta | std delta | min/max delta | conclusion |
|---|---:|---:|---:|---|
| streamcluster_pressure | -11.08% | 0.45% | -11.71% / -10.69% | stable positive: all seeds beat best baseline |
| blackscholes | +0.24% | 1.71% | -1.02% / +2.66% | mixed: seed can flip the conclusion |
| canneal | +16.81% | 1.77% | +14.78% / +19.09% | negative boundary: all seeds worse than best baseline |

## Notes

- LRU, LFU and CLOCK baselines are deterministic and reused from the existing stage 5/6 result directories.
- Random is reused from the existing fixed-random-seed baseline run; QMAP-CrossAttn is the only policy retrained across seeds.
