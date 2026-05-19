# PARSEC Stage 1 Workload Selection

## Decision

Stage 1 is complete. The first real/standard workload suite for QMAP will use PARSEC.

Primary batch:

| Workload | Role | Why it is useful for QMAP |
|---|---|---|
| blackscholes | Compute-stable anchor | Gives a relatively steady baseline so real traces are not all dominated by irregular memory behavior. |
| canneal | Irregular memory workload | Stresses locality, reuse, and working-set pressure; useful for comparing QMAP with LRU/LFU. |
| streamcluster | Streaming-like locality stress | Tests whether QMAP still behaves sensibly when temporal reuse may be weaker. |
| dedup | Data-processing/write-pressure workload | Better chance to expose NVM writes and migration-cost interactions. |

Fallback:

| Workload | Use when |
|---|---|
| ferret | Replace dedup if dedup build, dependency, or trace capture is unstable. |

## Selection Rationale

PARSEC is the best first target because it is a classic chip-multiprocessor benchmark suite and covers workload diversity that matters for a DRAM/NVM migration policy: working set shape, locality, sharing, synchronization, and memory traffic behavior.

This stage deliberately stops at benchmark selection. Raw PARSEC source, input archives, and full traces should not be committed to this repository. Stage 2 should run the actual build and tracing on a Linux, WSL2, or server environment, then write the converted CSV traces into `dataset/raw_traces/`.

## Stage 2 Contract

All captured traces must match the QMAP CSV schema:

```text
PC,Address,RW
0x400100,0x7f12345000,R
0x400108,0x7f12346000,W
```

Planned raw trace targets:

```text
dataset/raw_traces/parsec_blackscholes.csv
dataset/raw_traces/parsec_canneal.csv
dataset/raw_traces/parsec_streamcluster.csv
dataset/raw_traces/parsec_dedup.csv
```

Recommended pilot settings:

```text
records per workload: 100k
warmup skip: 10k accesses
split: chronological 80/10/10
thread counts: start with 1 and 4
inputs: simsmall or simmedium for pilot; simlarge/native for later formal runs
```

Recommended PARSEC command shape on the Linux trace host:

```bash
./bin/parsecmgmt -a build -p blackscholes -c gcc-pthreads
./bin/parsecmgmt -a run -p blackscholes -c gcc-pthreads -i simsmall -n 4
```

Repeat the same build/run pattern for `canneal`, `streamcluster`, and `dedup`; use `ferret` only as the fallback.

## Artifacts

Machine-readable workload manifest:

```text
dataset/metadata/parsec_workload_manifest.json
```

This manifest records the selected batch, fallback workload, expected QMAP signal, raw trace target paths, and Stage 2 capture contract.
