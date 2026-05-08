# QMAP Checkpoint Sweep

## Setup

- trace: `dataset\processed\try_test.csv`
- checkpoint dir: `outputs\checkpoints\try_prototype`
- epoch range: `1..10`
- DRAM capacity: `128` pages
- history length: `10`
- candidate count: `64`
- page shift: `12`
- device: `cpu`

## Selection

- lowest weighted cost: `epoch 10 (outputs\checkpoints\try_prototype\qmap_epoch_10.pth)` with cost `9838.00` and NVM writes `115`
- fewest NVM writes: `epoch 10 (outputs\checkpoints\try_prototype\qmap_epoch_10.pth)` with writes `115` and cost `9838.00`

Do not assume the final epoch is best; select the checkpoint by validation or replay cost for the reported experiment.

## Results

| Epoch | Weighted cost | NVM writes | NVM reads | Migrations | Hit rate (%) | Avg decision ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 11043.00 | 140 | 773 | 785 | 54.35 | 2.104725 |
| 2 | 10193.00 | 122 | 717 | 711 | 58.05 | 2.031242 |
| 3 | 9954.00 | 118 | 700 | 690 | 59.10 | 2.055684 |
| 4 | 9991.00 | 120 | 701 | 693 | 58.95 | 2.013168 |
| 5 | 9991.00 | 120 | 701 | 693 | 58.95 | 2.022224 |
| 6 | 9956.00 | 119 | 699 | 690 | 59.10 | 2.155230 |
| 7 | 9908.00 | 117 | 697 | 686 | 59.30 | 2.037102 |
| 8 | 9849.00 | 115 | 694 | 681 | 59.55 | 2.088010 |
| 9 | 9860.00 | 115 | 695 | 682 | 59.50 | 2.041211 |
| 10 | 9838.00 | 115 | 693 | 680 | 59.60 | 2.152374 |
