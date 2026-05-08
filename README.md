# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从一组候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

当前仓库的目标是先做出一套可信、可复现的原型实验，而不是一次性完成论文级大规模评测。现在主实验、checkpoint sweep、多 workload 实验和参数敏感性实验都已经具备；剩下主要是消融实验。

## 当前进度

| 步骤 | 状态 | 结果位置 |
|---|---|---|
| 1. 原型主实验：QMAP vs LRU / Random / LFU / CLOCK | 已完成 | `outputs/results/try_prototype/summary.md` |
| 2. Checkpoint sweep：选择最佳 epoch | 已完成 | `outputs/results/checkpoint_sweep/summary.md` |
| 3. 多 workload：hotset / writeheavy / streaming / phasechange | 已完成 | `outputs/results/workload_suite/summary.md` |
| 4. 参数敏感性：history / candidate / DRAM capacity / lookahead | 已完成 | `outputs/results/qmap_parameter_sensitivity/summary.md` |
| 5. 消融实验：no-PC / no-RW / no-QFormer / no-cost-aware | 未完成 | 建议输出到 `outputs/results/qmap_ablation/` |

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

## 5. 消融实验该怎么做

消融实验的目标不是再和 LRU / LFU 比一次，而是回答：QMAP 里面每个设计到底有没有贡献。建议至少做 5 个版本：

| 版本 | 含义 | 要证明的问题 |
|---|---|---|
| `full` | 当前完整 QMAP | 作为消融基线 |
| `no_pc` | 不使用 PC 信息 | PC 上下文是否真的帮助预测页面复用 |
| `no_rw` | 不使用读写类型信息 | 读写类型是否帮助减少 NVM writes |
| `no_qformer` | 去掉 Q-Former 查询聚合 | Q-Former 结构是否比简单 pooling 更有用 |
| `no_cost` | 去掉 cost-aware label / loss 里的写敏感和迁移代价项 | cost-aware 设计是否真的降低 writes 和 weighted cost |

### 5.1 推荐实现方式

第一步，在 `qmap/qmap_train.py` 和 `qmap/qmap_eval.py` 增加参数：

```text
--ablation full|no_pc|no_rw|no_qformer|no_cost
```

训练时把这个参数写入 checkpoint，例如写到 `model_args` 或 `ablation` 字段里。评估时如果没有显式传入 `--ablation`，优先从 checkpoint 读取。

第二步，实现 `no_pc`：

```text
位置：qmap/qmap_train.py、qmap/qmap_eval.py 或 policy_learning/cache_model/qmap_data.py
做法：进入模型前，把 batch 里的 PC 特征统一置零或置为同一个 unknown id。
目的：模型仍然能跑，但不能区分不同 PC。
```

看结果时重点关注：

```text
hit rate 是否下降；
weighted access cost 是否上升。
```

如果 `no_pc` 明显变差，可以说明 PC 上下文有用。

第三步，实现 `no_rw`：

```text
位置：qmap/qmap_train.py、qmap/qmap_eval.py 或 policy_learning/cache_model/qmap_data.py
做法：进入模型前，把 batch 里的 RW 特征统一置为 read，或者统一置零。
目的：模型无法知道访问是读还是写。
```

看结果时重点关注：

```text
NVM writes 是否增加；
weighted access cost 是否上升。
```

如果 `no_rw` 的 NVM writes 明显更多，可以说明读写类型对写敏感迁移有贡献。

第四步，实现 `no_qformer`：

```text
位置：policy_learning/cache_model/model.py
做法：增加一个模型开关，例如 use_qformer=True/False。
full：继续使用 Q-Former 查询向量聚合历史访问表示。
no_qformer：改成简单 mean pooling 或 last-token pooling，再送入同一个候选页 scorer。
```

这里要注意保持 scorer 输入形状尽量一致，避免比较不公平。可以把 mean pooling 得到的 `[B, H]` 扩展成 `[B, 1, H]`，然后复用原来的打分逻辑。

看结果时重点关注：

```text
hit rate；
weighted access cost；
avg decision time。
```

如果 `no_qformer` 性能下降，说明 Q-Former 聚合有用；如果性能接近但 overhead 明显下降，也可以作为论文里的 trade-off 分析。

第五步，实现 `no_cost`：

```text
位置：policy_learning/cache_model/qmap_loss.py 或 qmap/qmap_generator.py
做法一：训练时把 cost-aware loss 里的 write_sensitivity 和 migration_cost 权重置零。
做法二：生成 label 时把与写敏感、迁移代价相关的项置零。
```

推荐优先做法一，因为改动更小、更容易复现：

```text
full：使用原始 QMAPCostAwareRankingLoss。
no_cost：lambda_3=0，lambda_4=0，只保留 reuse/inactivity 类信号。
```

看结果时重点关注：

```text
NVM writes；
migration count；
weighted access cost。
```

如果 `no_cost` 的 hit rate 接近但 NVM writes / weighted cost 变差，就能说明 cost-aware objective 的价值。

### 5.2 建议新增脚本

建议新增：

```text
scripts/run_qmap_ablation.py
```

它负责循环运行多个 ablation 版本：

```text
full
no_pc
no_rw
no_qformer
no_cost
```

每个版本单独生成 JSONL、训练 checkpoint、评估 QMAP，并最终汇总成 Markdown 和 CSV。

推荐输出结构：

```text
outputs/results/qmap_ablation/
  summary.md
  summary.csv
  full/qmap.json
  no_pc/qmap.json
  no_rw/qmap.json
  no_qformer/qmap.json
  no_cost/qmap.json
  logs/

outputs/checkpoints/qmap_ablation/
  full/qmap_epoch_10.pth
  no_pc/qmap_epoch_10.pth
  no_rw/qmap_epoch_10.pth
  no_qformer/qmap_epoch_10.pth
  no_cost/qmap_epoch_10.pth
```

### 5.3 建议运行命令

消融实验先在 `try_train.csv` / `try_test.csv` 上跑通：

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

如果时间允许，再在最有代表性的两个 workload 上补跑：

```text
writeheavy     因为它最能体现 NVM writes 和 cost-aware 的价值
phasechange    因为它能体现非平稳访问下的泛化能力
```

### 5.4 消融结果应该怎么看

建议最终表格至少包含：

```text
variant
hit_rate_percent
nvm_reads
nvm_writes
migrations
weighted_access_cost
avg_decision_time_ms
```

论文里更建议报告相对变化：

```text
cost_delta_vs_full = (variant_cost - full_cost) / full_cost
writes_delta_vs_full = (variant_writes - full_writes) / full_writes
```

判断标准：

```text
no_pc 变差：说明 PC 上下文对复用预测有贡献。
no_rw 的 NVM writes 增加：说明读写类型对写敏感迁移有贡献。
no_qformer 变差：说明 Q-Former 聚合比简单 pooling 有贡献。
no_qformer 接近 full 但更快：说明 Q-Former 的收益需要结合 overhead 讨论。
no_cost 的 hit rate 接近但 writes/cost 变差：说明 cost-aware objective 的贡献主要体现在降低写放大和总访问代价。
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

outputs/checkpoints/try_prototype/
outputs/checkpoints/workload_suite/
outputs/checkpoints/qmap_parameter_sensitivity/

dataset/processed/
dataset/raw_traces/
dataset/metadata/
```

不要随便删除：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/*/qmap_epoch_10.pth
```

它们是当前主实验和多 workload 实验的关键权重。
