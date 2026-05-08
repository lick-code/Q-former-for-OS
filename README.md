# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满且一次 DRAM miss 触发迁移决策时，QMAP 从 LRU 尾部取一组候选页，对每个候选页打分，并选择最应该从 DRAM 降级到 NVM 的页面。

当前仓库目标是先做出一套可信、可复现的原型实验，而不是一次性完成论文级大规模评测。

## 当前进度

截至当前目录状态，前 4 步完成情况如下：

| 步骤 | 状态 | 说明 |
|---|---|---|
| 1. 清理目录并保留有效结果 | 基本完成 | 主结果在 `outputs/results/try_prototype/`，主权重在 `outputs/checkpoints/try_prototype/`。仍有 `outputs/results/diagnostic_baselines/` 这种调试结果，可以删除。 |
| 2. Checkpoint sweep | 已完成 | 结果在 `outputs/results/checkpoint_sweep/summary.md`。当前 `qmap_epoch_10.pth` 是 weighted cost 最低的 checkpoint。 |
| 3. 多 workload | 部分完成 | `hotset/writeheavy/streaming/phasechange` 的 raw/processed trace 已生成，见 `dataset/metadata/workload_manifest.json`；但当前没有看到 `outputs/results/workload_suite/summary.md`，说明完整多 workload 训练和评估还没跑完。 |
| 4. 参数敏感性实验 | 已完成 | 结果在 `outputs/results/qmap_parameter_sensitivity/summary.md`。 |
| 5. 消融实验 | 未完成 | 还没有 `no-PC/no-RW/no-QFormer/no-cost` 等消融开关和结果。 |

## 目录结构

```text
qmap/
  trace_builder.py              # 构造或转换页粒度 trace
  qmap_generator.py             # 从 CSV trace 生成 QMAP JSONL 样本
  qmap_train.py                 # 训练 QMAP checkpoint
  qmap_eval.py                  # replay 评估 LRU / Random / LFU / CLOCK / QMAP
  qmap_integration_test.py      # 模型和 loss 的 smoke test

policy_learning/cache_model/
  embed.py                      # QMAP embedding 模块
  model.py                      # Transformer、Q-Former、候选页打分器
  qmap_loss.py                  # cost-aware ranking loss

scripts/
  run_prototype_experiment.py          # 单 workload 原型实验
  run_qmap_checkpoint_sweep.py         # checkpoint sweep
  build_workload_suite.py              # 生成多 workload trace
  run_workload_suite.py                # 多 workload 训练和评估
  run_qmap_parameter_sensitivity.py    # 参数敏感性实验

dataset/
  raw_traces/                   # 原始 synthetic traces
  processed/                    # train / valid / test CSV traces
  jsonl/                        # 生成的 QMAP 训练样本
  metadata/                     # trace schema、split 和 workload manifest

outputs/
  checkpoints/                  # 训练得到的模型 checkpoint
  results/                      # JSON / CSV / Markdown 实验结果
```

## 输入 Trace 格式

推荐 CSV 格式：

```text
PC,Address,RW
0x400100,0x100000000,R
0x400104,0x100001000,W
```

`RW` 支持：

```text
R / W
read / write
load / store
L / S
0 / 1
```

如果地址是 4 KB 页对齐地址，运行时使用：

```text
--page_shift 12
```

## 1. 原型主实验：try_prototype

这是当前最基础、最重要的一组结果。它在 `try_train.csv` 上训练，在 `try_test.csv` 上比较 LRU / Random / LFU / CLOCK / QMAP。

运行命令：

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

如果 `dataset/processed/try_*.csv` 不存在，脚本会自动生成默认 toy trace 并切分。

结果位置：

```text
outputs/results/try_prototype/summary.md
outputs/results/try_prototype/summary.csv
outputs/results/try_prototype/lru.json
outputs/results/try_prototype/random.json
outputs/results/try_prototype/lfu.json
outputs/results/try_prototype/clock.json
outputs/results/try_prototype/qmap.json
outputs/results/try_prototype/logs/
```

权重位置：

```text
outputs/checkpoints/try_prototype/qmap_epoch_1.pth
...
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
```

查看结果：

```bash
cat outputs/results/try_prototype/summary.md
```

## 2. Checkpoint Sweep

目的：不要默认最后一个 epoch 最好，而是逐个评估 `qmap_epoch_1.pth` 到 `qmap_epoch_10.pth`，选择 weighted cost 最低或 NVM writes 最少的 checkpoint。

运行命令：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_checkpoint_sweep.py \
  --checkpoint_dir outputs/checkpoints/try_prototype \
  --trace_path dataset/processed/try_test.csv \
  --result_dir outputs/results/checkpoint_sweep \
  --epoch_start 1 \
  --epoch_end 10 \
  --dram_capacity 128 \
  --page_shift 12 \
  --history_length 10 \
  --candidate_count 64 \
  --device cuda
```

结果位置：

```text
outputs/results/checkpoint_sweep/summary.md
outputs/results/checkpoint_sweep/summary.csv
outputs/results/checkpoint_sweep/json/qmap_epoch_*.json
outputs/results/checkpoint_sweep/logs/qmap_epoch_*.log
```

查看结果：

```bash
cat outputs/results/checkpoint_sweep/summary.md
```

当前结果显示：

```text
weighted cost 最低：qmap_epoch_10.pth
NVM writes 最少：qmap_epoch_10.pth
```

因此当前主实验继续使用：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
```

## 3. 多 Workload 实验

目的：避免只在一个 `try` trace 上证明 QMAP。多 workload 至少覆盖：

```text
hotset       强局部性热点访问
writeheavy   写密集访问
streaming    低复用流式访问
phasechange  热点随阶段变化
```

### 3.1 只生成 workload 数据

如果只想生成 raw/processed trace：

```bash
python scripts/build_workload_suite.py \
  --records 20000 \
  --page_shift 12 \
  --workloads hotset writeheavy streaming phasechange
```

数据位置：

```text
dataset/raw_traces/hotset.csv
dataset/raw_traces/writeheavy.csv
dataset/raw_traces/streaming.csv
dataset/raw_traces/phasechange.csv

dataset/processed/hotset_train.csv
dataset/processed/hotset_valid.csv
dataset/processed/hotset_test.csv
...
dataset/metadata/workload_manifest.json
```

当前仓库已经完成了这一步。

### 3.2 跑完整多 workload 训练和评估

当前仓库还没有看到 `outputs/results/workload_suite/summary.md`，所以完整多 workload 评估还需要跑：

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

如果已经生成了 workload trace，想跳过重新生成数据：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_workload_suite.py \
  --skip_build \
  --workloads hotset,writeheavy,streaming,phasechange \
  --policies lru,random,lfu,clock,qmap \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

结果位置：

```text
outputs/results/workload_suite/summary.md
outputs/results/workload_suite/summary.csv
outputs/results/workload_suite/hotset/
outputs/results/workload_suite/writeheavy/
outputs/results/workload_suite/streaming/
outputs/results/workload_suite/phasechange/
outputs/results/workload_suite/logs/
```

权重位置：

```text
outputs/checkpoints/workload_suite/hotset/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/writeheavy/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/streaming/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/phasechange/qmap_epoch_10.pth
```

查看结果：

```bash
cat outputs/results/workload_suite/summary.md
```

## 4. 参数敏感性实验

目的：检查 QMAP 对关键参数是否稳定。当前脚本会围绕默认配置 `h10/c64/d128/l256` 做 one-at-a-time 实验。

默认测试范围：

```text
history_length:   5, 10, 20, 50
candidate_count:  16, 32, 64
dram_capacity:    64, 128, 256
lookahead:        128, 256, 512
```

运行命令：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_parameter_sensitivity.py \
  --train_trace dataset/processed/try_train.csv \
  --test_trace dataset/processed/try_test.csv \
  --result_dir outputs/results/qmap_parameter_sensitivity \
  --checkpoint_root outputs/checkpoints/qmap_parameter_sensitivity \
  --jsonl_root dataset/jsonl/qmap_parameter_sensitivity \
  --page_shift 12 \
  --epochs 5 \
  --batch_size 64 \
  --device cuda
```

结果位置：

```text
outputs/results/qmap_parameter_sensitivity/summary.md
outputs/results/qmap_parameter_sensitivity/summary.csv
outputs/results/qmap_parameter_sensitivity/runs/<config>/qmap.json
outputs/results/qmap_parameter_sensitivity/runs/<config>/logs/
```

权重位置：

```text
outputs/checkpoints/qmap_parameter_sensitivity/<config>/qmap_epoch_5.pth
```

查看结果：

```bash
cat outputs/results/qmap_parameter_sensitivity/summary.md
```

当前参数敏感性实验已经完成，结论是：

```text
history_length 和 lookahead 对 cost 影响较小；
candidate_count=32 与 64 接近，candidate_count=16 开始变差；
dram_capacity 影响很大，但它更像 workload pressure/scaling，而不是 QMAP 自身不稳定。
```

## 5. 后续未完成：消融实验

消融实验还没做。后面建议加入这些版本：

```text
QMAP-full
no-PC
no-RW
no-QFormer
no-cost-aware-label
```

这一步需要继续改代码，给 `qmap_generator.py`、`qmap_train.py`、模型和 loss 增加 ablation 开关。完成后结果建议放在：

```text
outputs/results/qmap_ablation/
outputs/checkpoints/qmap_ablation/
```

## 评估指标说明

`qmap_eval.py` 会输出：

- `Hit rate`：DRAM 命中率
- `NVM reads`：NVM 读次数
- `NVM writes`：NVM 写次数
- `Migrations`：页面迁移次数
- `Weighted access cost`：加权访问代价
- `Policy decisions`：触发策略决策的次数
- `Avg decision time`：平均单次策略决策时间

当前 replay 使用的简单代价模型：

```text
DRAM read  = 1
DRAM write = 1
NVM read   = 2
NVM write  = 4
Migration  = 10
```

这些常数定义在：

```text
qmap/qmap_eval.py
```

如果把结果写进论文或报告，需要明确说明这是原型 replay 的 cost model。

## 建议清理

可以保留：

```text
outputs/results/try_prototype/
outputs/results/checkpoint_sweep/
outputs/results/qmap_parameter_sensitivity/
outputs/checkpoints/try_prototype/
outputs/checkpoints/qmap_parameter_sensitivity/
dataset/processed/
dataset/raw_traces/
dataset/metadata/
```

如果不再需要调试结果，可以删除：

```bash
rm -rf outputs/results/diagnostic_baselines
```

不要随便删除：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
```

它是当前主实验和 checkpoint sweep 选出的最好权重。
