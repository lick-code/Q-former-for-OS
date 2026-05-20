# Real QMAP Ablation

Stage 6 target:

| workload | variants |
|---|---|
| streamcluster_pressure | no_rw, no_cost |
| blackscholes | no_rw, no_cost |

Run from the repository root:

```bash
PY=/home/likc/.conda/envs/qmap/bin/python DEVICE=cuda \
  bash scripts/run_real_ablation_on_server.sh
```

The runner writes:

- `dataset/jsonl/real_ablation/...`
- `outputs/checkpoints/real_ablation/...`
- `outputs/results/real_ablation/...`
- `outputs/results/real_ablation/summary.md`
