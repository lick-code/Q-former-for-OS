# Canneal Tuned Evaluation

## Selection Rule

The script selects the QMAP configuration with the lowest validation weighted access cost, then evaluates that one configuration on the test split.

## Selected Validation Config

| Epoch | Candidate count | Rank score penalty | Valid cost | Hit rate (%) | NVM writes | Migrations |
|---:|---:|---:|---:|---:|---:|---:|
| 9 | 8 | 0.5 | 132834.00 | 97.03 | 54 | 2954 |

## Test Result

| Policy | Cost | Delta vs best baseline | Hit rate (%) | NVM writes | Migrations | Decision ms |
|---|---:|---:|---:|---:|---:|---:|
| LRU | 126178.00 | +0.00% | 97.63 | 52 | 2350 | 0.000298 |
| RANDOM | 139465.00 |  | 96.50 | 193 | 3481 | 0.001181 |
| LFU | 159919.00 |  | 94.69 | 280 | 5293 | 0.005776 |
| CLOCK | 126325.00 |  | 97.62 | 60 | 2359 | 0.001696 |
| QMAP-CrossAttn | 144279.00 | +14.35% | 95.98 | 42 | 4001 | 2.447719 |

## Reproduction

```bash
python scripts/run_canneal_tuned_eval.py --device cuda
```

Selected QMAP-CrossAttn test delta vs best baseline (`LRU`) is +14.35%.
