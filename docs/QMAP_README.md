# QMAP Handoff README

This document summarizes the current QMAP prototype built on top of the original
PARROT cache replacement codebase.

## Current Status

We have completed a minimal trainable QMAP pipeline:

```text
CSV trace
-> qmap_generator.py
-> train_data.jsonl
-> qmap_train.py
-> checkpoint
-> qmap_eval.py replay evaluation
```

The model-side pipeline is:

```text
history access sequence
-> address / PC / RW embeddings
-> Transformer Encoder
-> Q-Former
-> page-id embedding + page-state candidate scorer
-> cost-aware ApproxNDCG ranking loss
```

The previous PARROT LSTM/cache-set core is no longer used by the QMAP model
path. QMAP works on global DRAM page migration candidates rather than
cache-set/cache-way replacement.

## Main Files

### `qmap_generator.py`

Generates QMAP JSONL training data from a simple CSV memory trace.

Default input:

```text
environment/example_memtrace.csv
```

Supported CSV formats:

```text
PC,Address
PC,Address,RW
```

Header is optional. Supported RW values:

```text
R/W, read/write, load/store, L/S, 0/1
```

If no RW column exists, the script prints a warning and uses:

```python
rw = page & 1
```

Default output:

```text
train_data.jsonl
```

Training samples are emitted only when a DRAM miss triggers a real migration
decision, i.e., after the simulated DRAM cache is full. For the tiny bundled
trace, use a small `--dram_capacity` when smoke-testing the generator.

Run:

```bash
python qmap_generator.py
```

Smoke-test command for the bundled toy trace:

```bash
python qmap_generator.py \
  --input environment/example_memtrace.csv \
  --output tmp_qmap_train_data.jsonl \
  --dram_capacity 4 \
  --history_length 4 \
  --lookahead 4
```

Example output:

```text
[Warning] RW column not found in trace. Using simulated rw = page & 1 as fallback.
RW source: fallback simulated rw = page & 1
Read accesses: ...
Write accesses: ...
Total trace records: ...
Generated samples: ...
Wrote: train_data.jsonl
```

### `qmap_integration_test.py`

End-to-end smoke test for the full QMAP model pipeline.

Run:

```bash
python qmap_integration_test.py
```

Expected output includes:

```text
access_features shape: (2, 4, 18)
Z shape: (2, 4, 18)
eviction_scores shape: (2, 64)
QMAP Pipeline Integration Successful!
```

### `qmap_train.py`

Trains QMAP from `train_data.jsonl`.

Run:

```bash
python qmap_train.py --train_data train_data.jsonl --epochs 2 --batch_size 2
```

The script prints:

```text
QMAP training configuration:
  train_data path: ...
  number of training samples: ...
  batch_size: ...
  epochs: ...
  learning rate: ...
  device: ...
Epoch [1/2] iter=1 loss=...
Epoch [1/2] avg_loss=...
Saved checkpoint: qmap_checkpoints/qmap_epoch_1.pth
Training finished.
```

Checkpoints are saved under:

```text
qmap_checkpoints/
```

### `qmap_eval.py`

Replay evaluation script comparing:

```text
lru
random
qmap
```

Run LRU:

```bash
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy lru
```

Run Random:

```bash
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy random
```

Run QMAP:

```bash
python qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_2.pth
```

Metrics printed:

```text
Policy: ...
Total accesses: ...
Hits: ...
Misses: ...
Hit rate: ...%
Migrations: ...
NVM reads: ...
NVM writes: ...
Weighted access cost: ...
```

Note: `environment/example_memtrace.csv` is tiny, so it is only useful for
checking that the replay script runs. It is not meaningful for final evaluation.

## Model Components

### Data and Embedding

Files:

```text
policy_learning/cache_model/qmap_data.py
policy_learning/cache_model/embed.py
```

The QMAP input sequence contains:

```text
physical_address
pc
rw
```

Each field is embedded separately, then concatenated:

```text
[batch_size, sequence_length, hidden_dim]
```

The current toy/default hidden dimension is:

```text
hidden_dim = 18
```

### Macroscopic Pattern Extraction

File:

```text
policy_learning/cache_model/model.py
```

Main classes:

```python
QMAPMacroscopicPatternExtractor
QFormer
```

Flow:

```text
[B, T, hidden_dim]
-> causal TransformerEncoder
-> Q-Former with K learnable query vectors
-> Z: [B, K, hidden_dim]
```

Default:

```text
K = 4
hidden_dim = 18
```

### Candidate Scoring

File:

```text
policy_learning/cache_model/model.py
```

Main class:

```python
QMAPCandidateScorer
```

Input:

```text
Z: [B, K, hidden_dim]
candidate_pages: [B, 64]
candidate_state_features: [B, 64, 3]
candidate_mask: [B, 64]
```

The page-level representation follows the method section:

```text
page_id embedding || recent_frequency || dirty_state || residency_duration
```

Output:

```text
eviction_scores: [B, 64]
```

The highest score is selected as the page to migrate out of DRAM.

### Loss

File:

```text
policy_learning/cache_model/qmap_loss.py
```

Main class:

```python
QMAPCostAwareRankingLoss
```

Target score:

```python
y_true = (
    lambda_1 * inactivity
    + lambda_2 * coldness
    - lambda_3 * write_sensitivity
    - lambda_4 * migration_cost
)
```

Loss type:

```text
ApproxNDCG-style listwise ranking loss with padding mask support
```

## Training Data Format

Each line in `train_data.jsonl` is one JSON object:

```json
{
  "physical_address": [4096, 8192],
  "pc": [4194595, 4194600],
  "rw": [0, 1],
  "candidate_pages": [4096, "... 64 pages total ..."],
  "candidate_state_features": [[0.2, 1.0, 0.8], "... 64 pages total ..."],
  "candidate_mask": [1, "... 64 values total ..."],
  "inactivity": [1.0, "... 64 values total ..."],
  "coldness": [0.99, "... 64 values total ..."],
  "write_sensitivity": [0.12, "... 64 values total ..."],
  "migration_cost": [0.0, "... 64 values total ..."]
}
```

Expected shapes per batch:

```text
physical_address: [B, history_length]
pc: [B, history_length]
rw: [B, history_length]
candidate_pages: [B, 64]
candidate_state_features: [B, 64, 3]
candidate_mask: [B, 64]
inactivity: [B, 64]
coldness: [B, 64]
write_sensitivity: [B, 64]
migration_cost: [B, 64]
```

## Important Assumptions

The current implementation is a prototype.

Current simplifications:

- If RW is missing from trace, RW is simulated by `page & 1`.
- Candidate page state features currently include recent frequency, dirty
  state, and normalized residency duration. The model embeds the candidate page
  id separately.
- `inactivity`, `coldness`, `write_sensitivity`, and `migration_cost` are
  heuristic oracle labels from offline trace replay.
- Weighted access costs in replay evaluation are fixed constants:

```text
DRAM read = 1
DRAM write = 1
NVM read = 2
NVM write = 8
migration cost = 10
```

## Recommended Next Steps

1. Use a larger real trace.

   The current example trace has only 10 records, so it is only useful for smoke
   tests.

2. Use real RW if available.

   Prefer CSV with:

   ```text
   PC,Address,RW
   ```

3. Run a small training pass.

   ```bash
   python qmap_generator.py --input path/to/trace.csv --output train_data.jsonl
   python qmap_train.py --train_data train_data.jsonl --epochs 5 --batch_size 32
   ```

4. Run replay evaluation.

   ```bash
   python qmap_eval.py --trace_path path/to/trace.csv --policy lru
   python qmap_eval.py --trace_path path/to/trace.csv --policy random
   python qmap_eval.py \
     --trace_path path/to/trace.csv \
     --policy qmap \
     --checkpoint qmap_checkpoints/qmap_epoch_5.pth
   ```

5. Improve oracle labels and page features.

   The most important research work now is improving:

   - candidate page feature design
   - write sensitivity estimation
   - migration cost model
   - train/eval trace split
   - replay simulator fidelity

## Quick Smoke Test Commands

```bash
python qmap_generator.py \
  --input environment/example_memtrace.csv \
  --output tmp_qmap_train_data.jsonl \
  --dram_capacity 4 \
  --history_length 4 \
  --lookahead 4
python qmap_integration_test.py
python qmap_train.py --train_data tmp_qmap_train_data.jsonl --epochs 2 --batch_size 2
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy lru
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy random
python qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_2.pth \
  --dram_capacity 4 \
  --history_length 4
```

Checkpoints produced by the earlier prototype scorer are not compatible with
the paper-aligned scorer. Regenerate training data and retrain QMAP after these
changes.
