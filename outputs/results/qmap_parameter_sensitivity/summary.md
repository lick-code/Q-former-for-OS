# QMAP Parameter Sensitivity

## Conclusion

QMAP is stable for the algorithmic knobs tested here. `history_length` changes weighted cost by only `1.03%`, and `lookahead` changes it by only `1.33%`. `candidate_count=32` is essentially tied with 64 (`+0.79%` cost delta), while `candidate_count=16` is still usable but starts to lose quality (`+5.13%` cost, `+10.43%` NVM writes). `dram_capacity` has a large effect because it changes the memory pressure itself, so treat it as workload scaling rather than QMAP parameter instability.

## Setup

- design: one parameter at a time around `h10/c64/d128/l256`
- train trace: `dataset/processed/try_train.csv`
- test trace: `dataset/processed/try_test.csv`
- epochs: `10`
- batch size: `32`
- device: `cuda`
- seed: `3136859`

## Baseline

| Config | Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---|---:|---:|---:|---:|
| h10/c64/d128/l256 | 59.30 | 9904.00 | 115 | 686 |

## Parameter Ranges

| Parameter | Cost min | Cost max | Cost span (%) | Hit range (%) | NVM writes range |
|---|---:|---:|---:|---:|---:|
| history_length | 9803.00 | 9904.00 | 1.03 | 59.30-59.75 | 112-116 |
| candidate_count | 9904.00 | 10412.00 | 5.13 | 57.10-59.30 | 115-127 |
| dram_capacity | 5850.00 | 12530.00 | 114.19 | 50.40-71.60 | 81-129 |
| lookahead | 9774.00 | 9904.00 | 1.33 | 59.30-59.90 | 112-116 |

## Detailed Results

| Parameter | Value | Config | Hit rate (%) | Cost | Cost delta (%) | NVM writes | Migrations | Decision ms |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| history_length | 5 | h5/c64/d128/l256 | 59.35 | 9887.00 | -0.17 | 112 | 685 | 3.670382 |
| history_length | 10 | h10/c64/d128/l256 | 59.30 | 9904.00 | +0.00 | 115 | 686 | 4.100761 |
| history_length | 20 | h20/c64/d128/l256 | 59.65 | 9829.00 | -0.76 | 116 | 679 | 3.340718 |
| history_length | 50 | h50/c64/d128/l256 | 59.75 | 9803.00 | -1.02 | 114 | 677 | 4.557987 |
| candidate_count | 16 | h10/c16/d128/l256 | 57.10 | 10412.00 | +5.13 | 127 | 730 | 3.932636 |
| candidate_count | 32 | h10/c32/d128/l256 | 59.00 | 9982.00 | +0.79 | 121 | 692 | 3.604333 |
| candidate_count | 64 | h10/c64/d128/l256 | 59.30 | 9904.00 | +0.00 | 115 | 686 | 4.100761 |
| dram_capacity | 64 | h10/c64/d64/l256 | 50.40 | 12530.00 | +26.51 | 129 | 928 | 3.158921 |
| dram_capacity | 128 | h10/c64/d128/l256 | 59.30 | 9904.00 | +0.00 | 115 | 686 | 4.100761 |
| dram_capacity | 256 | h10/c64/d256/l256 | 71.60 | 5850.00 | -40.93 | 81 | 312 | 5.998610 |
| lookahead | 128 | h10/c64/d128/l128 | 59.60 | 9832.00 | -0.73 | 112 | 680 | 3.392193 |
| lookahead | 256 | h10/c64/d128/l256 | 59.30 | 9904.00 | +0.00 | 115 | 686 | 4.100761 |
| lookahead | 512 | h10/c64/d128/l512 | 59.90 | 9774.00 | -1.31 | 116 | 674 | 5.093029 |
