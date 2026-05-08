# QMAP Parameter Sensitivity

## Conclusion

QMAP is stable for the algorithmic knobs tested here. `history_length` changes weighted cost by only `0.21%`, and `lookahead` changes it by only `1.54%`. `candidate_count=32` is essentially tied with 64 (`-0.03%` cost delta), while `candidate_count=16` is still usable but starts to lose quality (`+2.60%` cost, `+14.63%` NVM writes). `dram_capacity` has a large effect because it changes the memory pressure itself, so treat it as workload scaling rather than QMAP parameter instability.

## Setup

- design: one parameter at a time around `h10/c64/d128/l256`
- train trace: `dataset\processed\try_train.csv`
- test trace: `dataset\processed\try_test.csv`
- epochs: `5`
- batch size: `64`
- device: `cpu`
- seed: `3136859`

## Baseline

| Config | Hit rate (%) | Weighted cost | NVM writes | Migrations |
|---|---:|---:|---:|---:|
| h10/c64/d128/l256 | 57.70 | 10272.00 | 123 | 718 |

## Parameter Ranges

| Parameter | Cost min | Cost max | Cost span (%) | Hit range (%) | NVM writes range |
|---|---:|---:|---:|---:|---:|
| history_length | 10250.00 | 10272.00 | 0.21 | 57.70-57.80 | 123-123 |
| candidate_count | 10269.00 | 10539.00 | 2.63 | 56.65-57.75 | 123-141 |
| dram_capacity | 5826.00 | 13554.00 | 132.65 | 45.90-71.70 | 80-146 |
| lookahead | 10116.00 | 10272.00 | 1.54 | 57.70-58.40 | 122-123 |

## Detailed Results

| Parameter | Value | Config | Hit rate (%) | Cost | Cost delta (%) | NVM writes | Migrations | Decision ms |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| history_length | 5 | h5/c64/d128/l256 | 57.80 | 10250.00 | -0.21 | 123 | 716 | 1.810174 |
| history_length | 10 | h10/c64/d128/l256 | 57.70 | 10272.00 | +0.00 | 123 | 718 | 1.832666 |
| history_length | 20 | h20/c64/d128/l256 | 57.80 | 10250.00 | -0.21 | 123 | 716 | 1.971782 |
| history_length | 50 | h50/c64/d128/l256 | 57.80 | 10250.00 | -0.21 | 123 | 716 | 2.288315 |
| candidate_count | 16 | h10/c16/d128/l256 | 56.65 | 10539.00 | +2.60 | 141 | 739 | 1.794748 |
| candidate_count | 32 | h10/c32/d128/l256 | 57.75 | 10269.00 | -0.03 | 127 | 717 | 2.056160 |
| candidate_count | 64 | h10/c64/d128/l256 | 57.70 | 10272.00 | +0.00 | 123 | 718 | 1.832666 |
| dram_capacity | 64 | h10/c64/d64/l256 | 45.90 | 13554.00 | +31.95 | 146 | 1018 | 2.171736 |
| dram_capacity | 128 | h10/c64/d128/l256 | 57.70 | 10272.00 | +0.00 | 123 | 718 | 1.832666 |
| dram_capacity | 256 | h10/c64/d256/l256 | 71.70 | 5826.00 | -43.28 | 80 | 310 | 1.852587 |
| lookahead | 128 | h10/c64/d128/l128 | 58.40 | 10116.00 | -1.52 | 122 | 704 | 1.767049 |
| lookahead | 256 | h10/c64/d128/l256 | 57.70 | 10272.00 | +0.00 | 123 | 718 | 1.832666 |
| lookahead | 512 | h10/c64/d128/l512 | 58.05 | 10193.00 | -0.77 | 122 | 711 | 1.765750 |
