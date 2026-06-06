# QMAP Parameter Sensitivity

## Conclusion

QMAP is stable for the algorithmic knobs tested here. `history_length` changes weighted cost by only `0.43%`, and `lookahead` changes it by only `1.01%`. `candidate_count=32` is essentially tied with 64 (`+0.73%` cost delta), while `candidate_count=16` is still usable but starts to lose quality (`+6.22%` cost, `+18.35%` NVM writes). `dram_capacity` has a large effect because it changes the memory pressure itself, so treat it as workload scaling rather than QMAP parameter instability.

## Setup

- design: one parameter at a time around `h10/c64/d128/l256`
- QMAP model: `QMAP-CrossAttn` (`ablation=cross_attention`)
- train trace: `dataset/processed/try_train.csv`
- test trace: `dataset/processed/try_test.csv`
- epochs: `10`
- batch size: `32`
- device: `cuda`
- seed: `3136859`

## Baseline

| Config | Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---|---:|---:|---:|---:|
| h10/c64/d128/l256 | 59.70 | 10240.00 | 109 | 678 |

## Parameter Ranges

| Parameter | Cost min | Cost max | Cost span (%) | Hit range (%) | NVM writes range |
|---|---:|---:|---:|---:|---:|
| history_length | 10213.00 | 10257.00 | 0.43 | 59.65-59.85 | 109-110 |
| candidate_count | 10240.00 | 10877.00 | 6.22 | 57.35-59.70 | 109-129 |
| dram_capacity | 6323.00 | 12924.00 | 104.40 | 50.90-70.95 | 82-127 |
| lookahead | 10220.00 | 10323.00 | 1.01 | 59.35-59.90 | 109-113 |

## Detailed Results

| Parameter | Value | Config | Hit rate (%) | Cost | Cost delta (%) | NVM writes | Migrations | Decision ms |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| history_length | 5 | h5/c64/d128/l256 | 59.85 | 10213.00 | -0.26 | 110 | 675 | 3.370322 |
| history_length | 10 | h10/c64/d128/l256 | 59.70 | 10240.00 | +0.00 | 109 | 678 | 3.354256 |
| history_length | 20 | h20/c64/d128/l256 | 59.70 | 10240.00 | +0.00 | 109 | 678 | 3.363553 |
| history_length | 50 | h50/c64/d128/l256 | 59.65 | 10257.00 | +0.17 | 110 | 679 | 3.407668 |
| candidate_count | 16 | h10/c16/d128/l256 | 57.35 | 10877.00 | +6.22 | 129 | 725 | 3.071113 |
| candidate_count | 32 | h10/c32/d128/l256 | 59.55 | 10315.00 | +0.73 | 116 | 681 | 3.160477 |
| candidate_count | 64 | h10/c64/d128/l256 | 59.70 | 10240.00 | +0.00 | 109 | 678 | 3.354256 |
| dram_capacity | 64 | h10/c64/d64/l256 | 50.90 | 12924.00 | +26.21 | 127 | 918 | 3.044110 |
| dram_capacity | 128 | h10/c64/d128/l256 | 59.70 | 10240.00 | +0.00 | 109 | 678 | 3.354256 |
| dram_capacity | 256 | h10/c64/d256/l256 | 70.95 | 6323.00 | -38.25 | 82 | 325 | 4.224906 |
| lookahead | 128 | h10/c64/d128/l128 | 59.35 | 10323.00 | +0.81 | 110 | 685 | 3.248580 |
| lookahead | 256 | h10/c64/d128/l256 | 59.70 | 10240.00 | +0.00 | 109 | 678 | 3.354256 |
| lookahead | 512 | h10/c64/d128/l512 | 59.90 | 10220.00 | -0.20 | 113 | 674 | 3.314879 |
