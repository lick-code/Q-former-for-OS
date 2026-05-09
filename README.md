# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从一组候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

当前仓库的目标是先做出一套可信、可复现的原型实验，而不是一次性完成论文级大规模评测。现在主实验、checkpoint sweep、多 workload 实验、参数敏感性实验和消融实验这 5 个模块都已经具备。

## 当前进度

| 步骤 | 状态 | 结果位置 |
|---|---|---|
| 1. 原型主实验：QMAP vs LRU / Random / LFU / CLOCK | 已完成 | `outputs/results/try_prototype/summary.md` |
| 2. Checkpoint sweep：选择最佳 epoch | 已完成 | `outputs/results/checkpoint_sweep/summary.md` |
| 3. 多 workload：hotset / writeheavy / streaming / phasechange | 已完成 | `outputs/results/workload_suite/summary.md` |
| 4. 参数敏感性：history / candidate / DRAM capacity / lookahead | 已完成 | `outputs/results/qmap_parameter_sensitivity/summary.md` |
| 5. 消融实验：no-PC / no-RW / no-QFormer / no-cost-aware | 已完成 | `outputs/results/qmap_ablation/summary.md` |

## 当前结果判断

这套结果是“原型实验已经齐全，但算法效果还需要继续打磨”的状态。

可以比较放心写进论文或中期材料的点：

```text
1. QMAP 能完整跑通训练、replay 评估和多策略对比。
2. 在 writeheavy workload 上，QMAP 同时取得最高 hit rate、最低 NVM writes 和最低 weighted cost。
3. 在 streaming workload 上，所有策略都很差，QMAP 只有轻微优势，这符合低复用流式访问的直觉。
4. 参数敏感性结果比较稳定：history_length 和 lookahead 影响小，candidate_count=32/64 接近。
5. checkpoint sweep 显示训练到 epoch 10 的效果持续改善，不是随便挑了一个权重。
```

需要谨慎写、不能夸大的点：

```text
1. hotset 和 phasechange 上 LFU 仍然比 QMAP 更强。
2. try_prototype 上 QMAP 接近 LFU，但 weighted cost 略高于 LFU。
3. 消融实验里 no_qformer 反而优于 full，说明当前 Q-Former 结构没有被证明有效。
4. no_pc/no_rw 也没有变差，说明当前 trace 或模型还没有充分利用 PC/RW 特征。
5. no_cost 只让 NVM writes 略变差，cost 几乎不变，cost-aware loss 的贡献还不够强。
```

因此，当前最诚实的结论是：

```text
QMAP 原型已经完成，并且在写密集 workload 上显示出优势；
但当前模型结构贡献还不够稳定，特别是 Q-Former、PC/RW 特征和 cost-aware loss 需要进一步验证和增强。
```

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
  qmap_data.py                  # JSONL dataset 和 collate 逻辑

scripts/
  run_prototype_experiment.py          # 单 workload 原型实验
  run_qmap_checkpoint_sweep.py         # checkpoint sweep
  build_workload_suite.py              # 生成多 workload trace
  run_workload_suite.py                # 多 workload 训练和评估
  run_qmap_parameter_sensitivity.py    # 参数敏感性实验
  run_qmap_ablation.py                 # 消融实验

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

当前 `try_prototype` 的现象是：QMAP 明显优于 LRU / Random / CLOCK，和 LFU 接近；QMAP 与 LFU 的 NVM writes 相同，但 weighted access cost 略高于 LFU。这说明原型已经跑通，但还不能只靠这一组结果下强结论。

## 2. Checkpoint Sweep

目的：不要默认最后一个 epoch 最好，而是逐个评估 `qmap_epoch_1.pth` 到 `qmap_epoch_10.pth`，选择 weighted access cost 最低或 NVM writes 最少的 checkpoint。

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
weighted access cost 最低：qmap_epoch_10.pth
NVM writes 最少：qmap_epoch_10.pth
```

因此当前主实验继续使用：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
```

## 3. 多 Workload 实验

目的：避免只在一个 `try` trace 上证明 QMAP。当前仓库已经完成四类 workload：

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

### 3.2 跑完整多 workload 训练和评估

重新运行完整实验：

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

当前多 workload 结果的总体解读：

```text
writeheavy：QMAP 表现最好，说明写敏感场景下 QMAP 有价值。
streaming：所有策略都比较差，QMAP 只有轻微优势，这是低复用 workload 的合理现象。
hotset：LFU 最好，QMAP 接近 LRU/LFU，但没有超过 LFU。
phasechange：LFU 最好，QMAP 优于 LRU/Random/CLOCK，但弱于 LFU。
```

写论文或报告时，这组结果可以支撑一个更诚实的结论：QMAP 在写密集和部分非平稳访问下有收益，但不是在所有 workload 上都压过 LFU。

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

当前参数敏感性结论：

```text
history_length 和 lookahead 对 cost 影响较小；
candidate_count=32 与 64 接近，candidate_count=16 开始变差；
dram_capacity 影响很大，但它更像 workload pressure/scaling，而不是 QMAP 自身不稳定。
```

## 5. 消融实验

消融实验已经完成，脚本是：

```text
scripts/run_qmap_ablation.py
```

它包含 5 个版本：

| 版本 | 含义 | 结果解释 |
|---|---|---|
| `full` | 当前完整 QMAP | 消融基线 |
| `no_pc` | 去掉 PC 信息 | 检查 PC 上下文是否有贡献 |
| `no_rw` | 去掉读写类型 | 检查读写类型是否有助于减少 NVM writes |
| `no_qformer` | 用 mean pooling 替代 Q-Former | 检查 Q-Former 是否优于简单聚合 |
| `no_cost` | 关闭 write-sensitivity 和 migration-cost loss 项 | 检查 cost-aware objective 是否有效 |

运行命令：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/try_train.csv \
  --test_trace dataset/processed/try_test.csv \
  --variants full,no_pc,no_rw,no_qformer,no_cost \
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
outputs/results/qmap_ablation/summary.md
outputs/results/qmap_ablation/summary.csv
outputs/results/qmap_ablation/full/qmap.json
outputs/results/qmap_ablation/no_pc/qmap.json
outputs/results/qmap_ablation/no_rw/qmap.json
outputs/results/qmap_ablation/no_qformer/qmap.json
outputs/results/qmap_ablation/no_cost/qmap.json
```

权重位置：

```text
outputs/checkpoints/qmap_ablation/full/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/no_pc/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/no_rw/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/no_qformer/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/no_cost/qmap_epoch_10.pth
```

查看结果：

```bash
cat outputs/results/qmap_ablation/summary.md
```

当前消融结果：

| Variant | Hit rate (%) | Cost | Cost delta | NVM writes | Writes delta |
|---|---:|---:|---:|---:|---:|
| `full` | 59.30 | 9904 | +0.00% | 115 | +0.00% |
| `no_pc` | 59.65 | 9821 | -0.84% | 112 | -2.61% |
| `no_rw` | 59.85 | 9781 | -1.24% | 114 | -0.87% |
| `no_qformer` | 60.00 | 9738 | -1.68% | 109 | -5.22% |
| `no_cost` | 59.40 | 9884 | -0.20% | 116 | +0.87% |

这个结果要谨慎解释。它没有证明 Q-Former、PC/RW 特征和 cost-aware loss 都有明显正贡献，反而暴露了当前模型还需要继续打磨：

```text
no_qformer 比 full 更好：当前 Q-Former 结构没有被证明有效，mean pooling 反而更稳。
no_pc/no_rw 比 full 略好：当前 synthetic trace 可能没有让 PC/RW 特征发挥出来，或者模型没有学会利用它们。
no_cost 的 writes 略高但 cost 接近：cost-aware loss 有一点写敏感信号，但强度还不够。
```

因此，当前消融实验在论文里更适合写成“诊断性消融”：

```text
它说明当前 QMAP 框架可运行、可评估；
但完整模型还不是最终最优结构；
下一步应该围绕 Q-Former 结构、PC/RW 特征设计和 cost-aware loss 权重继续优化。
```

## 下一步实验建议

如果只想让结果更像一篇完整论文，建议优先做下面 4 件事。

第一，做 workload 上的消融，而不是只在 `try` trace 上做消融。当前消融只说明 toy trace 上 full 不占优，不能说明所有 workload 都这样。优先补：

```text
writeheavy     重点看 no_rw/no_cost 是否导致 NVM writes 上升
phasechange    重点看 no_pc/no_qformer 是否影响阶段变化适应能力
```

第二，强化 cost-aware loss。当前 `no_cost` 只让 NVM writes 从 115 增到 116，差异太小。可以尝试：

```text
提高 write_sensitivity 权重；
提高 migration_cost 权重；
把 weighted access cost 里的 NVM write cost 从 4 调到 8 或 10 做压力测试；
单独报告 writes reduction，而不是只报告 hit rate。
```

第三，重做 Q-Former 对照。当前 `no_qformer` 最好，说明 full 的 Q-Former 设计可能过重或训练不足。可以尝试：

```text
减少 query 数量；
减少 Transformer 层数；
加入 dropout / weight decay；
延长训练 epoch；
把 mean pooling 作为正式 baseline，而不是只作为消融项。
```

第四，构造更能体现 PC/RW 的 trace。当前 `no_pc/no_rw` 不差，说明 trace 里 PC/RW 信号可能太弱。可以补一个更清晰的 synthetic workload：

```text
不同 PC 对应不同页面复用距离；
写热点和读热点分离；
同一页面在不同 phase 中读写行为变化；
让错误迁移写热点页面时付出更高 cost。
```

推荐实验顺序：

```text
1. 先在 writeheavy 上补消融；
2. 再调 cost-aware loss 权重；
3. 然后比较 full / mean pooling / lighter Q-Former；
4. 最后再补更真实或更有区分度的 trace。
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
NVM write  = 8
Migration  = 10
```

这些常数定义在：

```text
qmap/qmap_eval.py
```

如果把结果写进论文或报告，需要明确说明这是原型 replay 的 cost model。

## 服务器后台运行建议

可以用 `tmux` 挂后台运行：

```bash
tmux new -s qmap
CUDA_VISIBLE_DEVICES=2 python scripts/run_workload_suite.py ...
```

断开：

```text
Ctrl-b 然后按 d
```

重新进入：

```bash
tmux attach -t qmap
```

指定显卡用：

```bash
CUDA_VISIBLE_DEVICES=2 python ...
```

脚本内部仍然写 `--device cuda` 即可。此时程序看到的 `cuda:0` 实际对应物理 GPU 2。

## 建议保留和清理

建议保留：

```text
outputs/results/try_prototype/
outputs/results/checkpoint_sweep/
outputs/results/workload_suite/
outputs/results/qmap_parameter_sensitivity/
outputs/results/qmap_ablation/

outputs/checkpoints/try_prototype/
outputs/checkpoints/workload_suite/
outputs/checkpoints/qmap_parameter_sensitivity/
outputs/checkpoints/qmap_ablation/

dataset/processed/
dataset/raw_traces/
dataset/metadata/
```

不要随便删除：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/*/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/*/qmap_epoch_10.pth
```

它们是当前主实验和多 workload 实验的关键权重。
