# DynamoRIO Trace Collection

This directory documents the Stage 2 real-trace collection path. The current
implementation uses DynamoRIO's built-in `drmemtrace` client, then converts the
human-readable `view` stream into the QMAP CSV schema:

```text
PC,Address,RW
0x400100,0x7f12345000,R
0x400108,0x7f12346000,W
```

## Requirements

Install a DynamoRIO binary package and expose `drrun` through either:

```text
DYNAMORIO_HOME=<path-to-DynamoRIO>
```

or pass `--drrun <path-to-bin64/drrun>` to the wrapper.

The wrapper does not require compiling a custom DynamoRIO client. On Windows,
it also runs `drraw2trace` automatically when `drmemtrace` leaves raw files
without a populated `trace/` directory.

## Local 100k Pilot

This repository has already passed a local instrumentation pilot with
DynamoRIO `11.91.20581`:

```bash
python scripts/collect_trace_drmemtrace.py \
  --drrun tools/extern/DynamoRIO-Windows-11.91.20581/bin64/drrun.exe \
  --output dataset/raw_traces/local_python_loop_100k.csv \
  --work-dir tmp/drmemtrace/local_python_loop_100k \
  --max-records 100000 \
  --skip-records 10000 \
  --trace-after-instrs 5000000 \
  --trace-ref-multiplier 30 \
  -- \
  python -c "a=bytearray(67108864); s=0
for i in range(8000000):
    j=(i*4099)&67108863; a[j]=i&255; s+=a[j]
print(s)"
```

Result:

```text
Seen data refs: 110000
Wrote records: 100000
```

The normalized pilot is recorded as `local_python_loop_pilot` in:

```text
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

## 100k Pilot

```bash
python scripts/collect_trace_drmemtrace.py \
  --output dataset/raw_traces/parsec_blackscholes_100k.csv \
  --max-records 100000 \
  --skip-records 10000 \
  --trace-ref-multiplier 12 \
  -- \
  /path/to/blackscholes args...
```

Then normalize, split, and summarize:

```bash
python scripts/prepare_real_trace.py \
  --input dataset/raw_traces/parsec_blackscholes_100k.csv \
  --workload parsec_blackscholes \
  --limit 100000
```

This writes:

```text
dataset/raw_traces/parsec_blackscholes.csv
dataset/processed/parsec_blackscholes_train.csv
dataset/processed/parsec_blackscholes_valid.csv
dataset/processed/parsec_blackscholes_test.csv
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

## Scaling To 1M Or 5M

After the 100k pilot passes quality checks and QMAP replay, collect larger
windows by changing only the record count:

```bash
python scripts/collect_trace_drmemtrace.py \
  --output dataset/raw_traces/parsec_blackscholes_1m.csv \
  --max-records 1000000 \
  --skip-records 100000 \
  --trace-ref-multiplier 12 \
  -- \
  /path/to/blackscholes args...
```

For 5M, use `--max-records 5000000`. If the wrapper reports fewer data records
than requested, increase `--trace-ref-multiplier` or set an explicit
`--trace-refs` window.
