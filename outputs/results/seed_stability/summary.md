# Stage 7 Seed Stability

Purpose: answer whether the QMAP-CrossAttn result is an accidental training-seed outcome.

## Per-seed Results

| workload | seed | QMAP cost | best baseline | delta | migrations | writes |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 3136859 | 264501.00 | 301767.00 (CLOCK) | -12.35% | 5541 | 589 |
| streamcluster_pressure | 42 | 270304.00 | 301767.00 (CLOCK) | -10.43% | 6068 | 590 |
| streamcluster_pressure | 2026 | 265585.00 | 301767.00 (CLOCK) | -11.99% | 5639 | 590 |
| blackscholes | 3136859 | 105983.00 | 106952.00 (LFU) | -0.91% | 525 | 32 |
| blackscholes | 42 | 104707.00 | 106952.00 (LFU) | -2.10% | 409 | 32 |
| blackscholes | 2026 | 105002.00 | 106952.00 (LFU) | -1.82% | 438 | 28 |
| canneal | 3136859 | 150559.00 | 126178.00 (LRU) | +19.32% | 4567 | 51 |
| canneal | 42 | 152154.00 | 126178.00 (LRU) | +20.59% | 4718 | 40 |
| canneal | 2026 | 147212.00 | 126178.00 (LRU) | +16.67% | 4260 | 56 |

## Stability Summary

| workload | mean delta | std delta | min/max delta | conclusion |
|---|---:|---:|---:|---|
| streamcluster_pressure | -11.59% | 0.83% | -12.35% / -10.43% | stable positive: all seeds beat best baseline |
| blackscholes | -1.61% | 0.51% | -2.10% / -0.91% | stable positive: all seeds beat best baseline |
| canneal | +18.86% | 1.63% | +16.67% / +20.59% | negative boundary: all seeds worse than best baseline |

## Notes

- LRU, LFU and CLOCK baselines are deterministic and reused from the existing stage 5/6 result directories.
- Random is reused from the existing fixed-random-seed baseline run; QMAP-CrossAttn is the only policy retrained across seeds.
