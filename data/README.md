# CAPD Data

This directory contains the small public data artifacts needed to understand
and demonstrate the CAPD trace-replay pipeline. Large raw traces, generated
JSONL training samples, and model checkpoints are intentionally excluded from
the competition repository.

## Directory Layout

```text
data/
├─ examples/
│  └─ capd_demo.csv
└─ metadata/
   ├─ trace_schema.json
   ├─ main_1m_manifest.json
   └─ pressure_window_manifest.json
```

## Demo Trace

`examples/capd_demo.csv` is a small synthetic memory-access trace copied from
the development repository's `dataset/raw_traces/try.csv`. Its columns are:

```text
PC,Address,RW
```

- `PC`: program-counter value in hexadecimal.
- `Address`: 4 KB page-aligned virtual address in hexadecimal.
- `RW`: `R` for reads and `W` for writes.

The prototype uses virtual page identifiers during replay and does not
reconstruct physical addresses.

## Metadata

- `metadata/trace_schema.json` records the trace fields, page size, and R/W
  encoding.
- `metadata/main_1m_manifest.json` records the chronological 800K/100K/100K
  train/validation/test splits used by the standard 1M-reference experiments.
- `metadata/pressure_window_manifest.json` records the fixed pressure windows
  selected using LRU-triggered demotion counts before CAPD training and
  evaluation.

The manifest paths preserve the original development-repository layout for
provenance. Update those paths only after the competition repository's final
data-download and reproduction workflow is fixed.

## Large Data

Do not commit the full PARSEC-derived traces or generated JSONL files directly
to Git. Document their collection procedure, checksums, and download location
instead. Trace collection and conversion instructions are maintained in:

```text
tools/trace_collectors/dynamorio/README.md
```
