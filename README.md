# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

当前仓库已经完成了一套可复现的原型实验：主实验、checkpoint sweep、多 workload、参数敏感性、消融实验、PC/RW stress workload、cost-aware 权重实验和 Q-Former 对照实验都已有输出。

## 当前结论

可以写进论文或报告的结论：

```text
1. QMAP 原型已经跑通完整 pipeline：trace -> JSONL -> training -> replay evaluation -> summary。
2. 在 writeheavy workload 上，QMAP 是最强策略：hit rate 最高、NVM writes 最少、weighted cost 最低。
3. 参数敏感性整体稳定：history_length 和 lookahead 影响小，candidate_count=32 与 64 接近。
4. writeheavy 消融显示 full QMAP 的 PC/RW/Q-Former/cost-aware 组件都有小幅正贡献。
5. mean pooling 在 phasechange、pcrwstress 和 Q-Former 对照中更稳，说明当前 Q-Former 结构不是最终最优。
```

需要谨慎表述的结论：

```text
1. QMAP 不是所有 workload 都优于 LFU。hotset、phasechange、pcrwstress 上 LFU 仍然很强。
2. cost-aware loss 的收益目前偏弱：writeheavy 上强化权重只比 no_cost 少 1 次 NVM write。
3. PC/RW 特征在 pcrwstress 中没有明显拉开 NVM writes，说明当前 trace 或特征利用还不够强。
4. Q-Former 不应直接作为强贡献点；目前更适合把 mean_pool 作为正式 baseline 或候选最终版本。
```

最诚实的论文叙事是：

```text
QMAP 在写密集场景下能降低 NVM writes 和 weighted access cost；
但在稳定热点或 LFU 友好的 workload 上优势有限；
当前实验进一步表明，简单 mean pooling 比原始 Q-Former 更稳，后续应把 QMAP-Pool 作为主要实现继续打磨。
```

## 结果总览

| 模块 | 状态 | 结果 |
|---|---|---|
| 原型主实验 | 已完成 | `outputs/results/try_prototype/summary.md` |
| Checkpoint sweep | 已完成 | `outputs/results/checkpoint_sweep/summary.md` |
| 多 workload | 已完成 | `outputs/results/workload_suite/summary.md` |
| pcrwstress workload | 已完成 | `outputs/results/workload_suite_pcrwstress/summary.md` |
| 参数敏感性 | 已完成 | `outputs/results/qmap_parameter_sensitivity/summary.md` |
| try trace 消融 | 已完成 | `outputs/results/qmap_ablation/summary.md` |
| writeheavy 消融 | 已完成 | `outputs/results/qmap_ablation/writeheavy/summary.md` |
| phasechange 消融 | 已完成 | `outputs/results/qmap_ablation/phasechange/summary.md` |
| pcrwstress 消融 | 已完成 | `outputs/results/qmap_ablation_pcrwstress/summary.md` |
| cost-aware 权重实验 | 已完成 | `outputs/results/qmap_cost_w8_m4_writeheavy/summary.md` |
| Q-Former 对照 | 已完成 | `outputs/results/qmap_qformer_comparison_writeheavy/summary.md` |

## 目录结构

```text
qmap/
  trace_builder.py              # 构造 synthetic trace
  qmap_generator.py             # 从 CSV trace 生成 QMAP JSONL 样本
  qmap_train.py                 # 训练 QMAP checkpoint
  qmap_eval.py                  # replay 评估 LRU / Random / LFU / CLOCK / QMAP
  qmap_integration_test.py      # 模型和 loss 的 smoke test

policy_learning/cache_model/
  embed.py                      # QMAP embedding
  model.py                      # Transformer、Q-Former、mean pooling、候选页 scorer
  qmap_loss.py                  # cost-aware ranking loss
  qmap_data.py                  # JSONL dataset 和 collate 逻辑

scripts/
  run_prototype_experiment.py          # 单 workload 原型实验
  run_qmap_checkpoint_sweep.py         # checkpoint sweep
  build_workload_suite.py              # 生成多 workload trace
  run_workload_suite.py                # 多 workload 训练和评估
  run_qmap_parameter_sensitivity.py    # 参数敏感性实验
  run_qmap_ablation.py                 # 消融实验
  run_qmap_qformer_comparison.py       # Q-Former / mean_pool 对照实验

dataset/
  raw_traces/                   # 原始 synthetic traces
  processed/                    # train / valid / test CSV traces
  jsonl/                        # QMAP 训练样本
  metadata/                     # trace schema、split 和 workload manifest

outputs/
  checkpoints/                  # 训练得到的模型 checkpoint
  results/                      # JSON / CSV / Markdown 实验结果
```

## 主要实验结果

### 多 Workload

查看：

```bash
cat outputs/results/workload_suite/summary.md
cat outputs/results/workload_suite_pcrwstress/summary.md
```

关键结果：

| Workload | 最好策略 | QMAP 表现 |
|---|---|---|
| hotset | LFU | QMAP 接近 LFU，cost 3777 vs LFU 3746，NVM writes 与 LRU 同为 38 |
| writeheavy | QMAP | QMAP 最好，hit 73.45%，writes 209，cost 6979 |
| streaming | QMAP 略好 | 所有策略都很差，QMAP 只有轻微优势 |
| phasechange | LFU | QMAP 弱于 LFU，cost 9589 vs LFU 7170 |
| pcrwstress | LFU | QMAP 优于 LRU，但弱于 LFU，cost 6441 vs LFU 6133 |

writeheavy 是当前最有价值的主结果：

```text
QMAP vs LFU:
hit rate: 73.45% vs 71.95%
NVM writes: 209 vs 224
weighted cost: 6979 vs 7339
```

这可以支撑“QMAP 在写密集场景下有效”的结论。

### 消融实验

查看：

```bash
cat outputs/results/qmap_ablation/summary.md
cat outputs/results/qmap_ablation/writeheavy/summary.md
cat outputs/results/qmap_ablation/phasechange/summary.md
cat outputs/results/qmap_ablation_pcrwstress/summary.md
```

writeheavy 消融：

| Variant | Hit rate | Cost | NVM writes | 解读 |
|---|---:|---:|---:|---|
| full | 73.45 | 6979 | 209 | 最好 |
| no_pc | 73.25 | 7027 | 211 | PC 有小幅贡献 |
| no_rw | 73.30 | 7016 | 211 | RW 有小幅贡献 |
| no_qformer / mean_pool | 73.15 | 7051 | 212 | Q-Former 在 writeheavy 上略有帮助 |
| no_cost | 73.30 | 7016 | 211 | cost-aware 有小幅贡献 |

phasechange 消融：

```text
mean_pool/no_qformer 明显优于 full：
hit rate: 64.90% vs 61.25%
cost: 8740 vs 9589
NVM writes: 149 vs 172
```

pcrwstress 消融：

```text
mean_pool 仍然优于 full：
hit rate: 75.75% vs 74.65%
cost: 6199 vs 6441
NVM writes 都是 24
```

消融结论：

```text
writeheavy 上 full QMAP 组件都有小幅正贡献；
phasechange/pcrwstress 上 mean_pool 更稳；
因此当前不应把 Q-Former 写成稳定贡献点，更适合把 mean_pool 作为正式对照或最终候选实现。
```

### Cost-Aware 权重实验

查看：

```bash
cat outputs/results/qmap_cost_w8_m4_writeheavy/summary.md
```

结果：

```text
full:    hit 73.30%, cost 7854, NVM writes 210
no_cost: hit 73.30%, cost 7860, NVM writes 211
```

结论：

```text
强化 write_sensitivity=8、migration_cost=4 后，full 比 no_cost 少 1 次 NVM write，cost 低 6。
方向是对的，但收益很小。论文里可以说 cost-aware objective 有轻微信号，不能夸大。
```

### Q-Former 对照

查看：

```bash
cat outputs/results/qmap_qformer_comparison_writeheavy/summary.md
```

结果：

| Profile | Hit rate | Cost | NVM writes | 解读 |
|---|---:|---:|---:|---|
| full | 73.40 | 7856 | 214 | hit 略高，但 cost/writes 更差 |
| mean_pool | 73.35 | 7837 | 209 | 最低 cost 和 writes |
| qformer_light | 72.55 | 8061 | 217 | 明显变差 |
| qformer_tiny | 73.15 | 7905 | 213 | 仍弱于 mean_pool |

结论：

```text
mean_pool 是当前最稳的聚合方式。
Q-Former 可以保留为探索性模块，但不建议作为当前论文最强贡献点。
```

## 运行命令

### 主实验

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_prototype_experiment.py \
  --run_name try_prototype \
  --train_trace dataset/processed/try_train.csv \
  --test_trace dataset/processed/try_test.csv \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

### 多 Workload

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_workload_suite.py \
  --workloads hotset,writeheavy,streaming,phasechange \
  --policies lru,random,lfu,clock,qmap \
  --records 20000 \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

### pcrwstress Workload

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_workload_suite.py \
  --skip_build \
  --skip_generate \
  --workloads pcrwstress \
  --policies lru,random,lfu,clock,qmap \
  --result_dir outputs/results/workload_suite_pcrwstress \
  --checkpoint_dir outputs/checkpoints/workload_suite_pcrwstress \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

### 消融实验

try trace：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/try_train.csv \
  --test_trace dataset/processed/try_test.csv \
  --variants full,no_pc,no_rw,mean_pool,no_cost \
  --result_dir outputs/results/qmap_ablation \
  --checkpoint_root outputs/checkpoints/qmap_ablation \
  --jsonl_root dataset/jsonl/qmap_ablation \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

writeheavy：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --variants full,no_pc,no_rw,mean_pool,no_cost \
  --result_dir outputs/results/qmap_ablation/writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_ablation/writeheavy \
  --jsonl_root dataset/jsonl/qmap_ablation/writeheavy \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

phasechange：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/phasechange_train.csv \
  --test_trace dataset/processed/phasechange_test.csv \
  --variants full,no_pc,no_rw,mean_pool,no_cost \
  --result_dir outputs/results/qmap_ablation/phasechange \
  --checkpoint_root outputs/checkpoints/qmap_ablation/phasechange \
  --jsonl_root dataset/jsonl/qmap_ablation/phasechange \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

pcrwstress：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/pcrwstress_train.csv \
  --test_trace dataset/processed/pcrwstress_test.csv \
  --variants full,no_pc,no_rw,mean_pool,no_cost \
  --result_dir outputs/results/qmap_ablation_pcrwstress \
  --checkpoint_root outputs/checkpoints/qmap_ablation_pcrwstress \
  --jsonl_root dataset/jsonl/qmap_ablation_pcrwstress \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --write_sensitivity_weight 4 \
  --migration_cost_weight 2 \
  --nvm_write_cost 8 \
  --device cuda
```

### Q-Former 对照

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_qformer_comparison.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --profiles full,mean_pool,qformer_light,qformer_tiny \
  --result_dir outputs/results/qmap_qformer_comparison_writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_qformer_comparison_writeheavy \
  --jsonl_root dataset/jsonl/qmap_qformer_comparison_writeheavy \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 20 \
  --batch_size 32 \
  --write_sensitivity_weight 4 \
  --migration_cost_weight 2 \
  --nvm_write_cost 8 \
  --device cuda
```

## 下一步计划

现在不建议继续盲目加新模块。更现实的下一步是“收敛版本 + 增强可信度”。

### 1. 确定最终策略命名

建议把当前策略分成两个名字：

```text
QMAP-Full：原始 Q-Former 版本
QMAP-Pool：Transformer encoder + mean pooling 版本
```

论文主结果可以先报告 QMAP-Full，因为 writeheavy 上 full 最好；但在讨论和消融中明确指出 QMAP-Pool 在 phasechange/pcrwstress 上更稳。

如果后续只能保留一个最终实现，更推荐选择 QMAP-Pool。

### 2. 做 3 个 seed 的重复实验

writeheavy 上很多消融差距只有 0.5% 到 1%，需要多 seed 支撑。建议至少对下面实验跑 3 个 seed：

```text
qmap_ablation/writeheavy
qmap_ablation/phasechange
qmap_ablation_pcrwstress
qmap_qformer_comparison_writeheavy
```

建议 seed：

```text
3136859
42
2026
```

如果多 seed 后趋势仍然一致，再写进论文；如果趋势不稳定，就把这些结果写成“诊断性实验”。

### 3. 汇总最终表格

建议最终论文保留 4 张表：

```text
Table 1: QMAP vs LRU/Random/LFU/CLOCK across workloads
Table 2: checkpoint sweep
Table 3: parameter sensitivity
Table 4: ablation and QMAP-Full vs QMAP-Pool
```

其中最重要的是 Table 1 和 Table 4。

### 4. 暂时不要继续强化 cost-aware

当前 cost-aware 权重实验收益太小：

```text
full 比 no_cost 少 1 次 NVM write，cost 低 6。
```

除非你愿意重新设计 label 或 trace，否则不建议再花太多时间调权重。

## 指标说明

`qmap_eval.py` 输出：

- `Hit rate`：DRAM 命中率
- `NVM reads`：NVM 读次数
- `NVM writes`：NVM 写次数
- `Migrations`：页面迁移次数
- `Weighted access cost`：加权访问代价
- `Policy decisions`：触发策略决策次数
- `Avg decision time`：平均单次策略决策时间

当前 replay cost model：

```text
DRAM read  = 1
DRAM write = 1
NVM read   = 2
NVM write  = 8
Migration  = 10
```

这些常数定义在：

```text
qmap/qmap_eval.py
```

## 服务器运行建议

使用 `tmux`：

```bash
tmux new -s qmap
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py ...
```

断开：

```text
Ctrl-b 然后按 d
```

重新进入：

```bash
tmux attach -t qmap
```

指定显卡：

```bash
CUDA_VISIBLE_DEVICES=2 python ...
```

脚本内部仍然写 `--device cuda`。此时程序看到的 `cuda:0` 实际对应物理 GPU 2。

## 建议保留

```text
outputs/results/
outputs/checkpoints/
dataset/processed/
dataset/raw_traces/
dataset/jsonl/
dataset/metadata/
```

不要删除这些关键权重：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/*/qmap_epoch_10.pth
outputs/checkpoints/workload_suite_pcrwstress/*/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/**/qmap_epoch_10.pth
outputs/checkpoints/qmap_qformer_comparison_writeheavy/**/qmap_epoch_20.pth
```
