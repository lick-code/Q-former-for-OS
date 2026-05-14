# QMAP Encoder Depth Comparison

## Setup

- aggregation: `TransformerEncoder -> mean pooling`
- train trace: `dataset/processed/writeheavy_train.csv`
- test trace: `dataset/processed/writeheavy_test.csv`
- baseline: `layers_1`
- layers: `1,2,3`
- h/c/d/l: `10/64/128/256`
- epochs: `20`
- batch size: `32`
- lr: `0.0001`
- dropout: `0.0`
- weight decay: `0.0`
- NVM write cost: `8.0`
- device: `cuda`
- seed: `3136859`

## Best By Weighted Cost

`layers_1`: hit `73.35%`, cost `7837.00`, NVM writes `209`.

## Results

| Profile | Purpose | Layers | Heads | Dropout | Weight decay | Hit rate (%) | Hit delta vs 1-layer (pp) | Cost | Cost delta vs 1-layer (%) | NVM writes | Writes delta vs 1-layer (%) | Decision ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| layers_1 | current one-layer mean-pooling baseline | 1 | 2 | 0 | 0 | 73.35 | +0.00 | 7837.00 | +0.00 | 209 | +0.00 | 3.073005 |
| layers_2 | 2-layer mean-pooling encoder | 2 | 2 | 0 | 0 | 73.30 | -0.05 | 7848.00 | +0.14 | 209 | +0.00 | 3.939193 |
| layers_3 | 3-layer mean-pooling encoder | 3 | 2 | 0 | 0 | 73.30 | -0.05 | 7842.00 | +0.06 | 208 | -0.48 | 4.104988 |
