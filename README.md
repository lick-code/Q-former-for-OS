# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为
候选页面排序问题：当 DRAM 已满且一次 DRAM miss 触发迁移决策时，QMAP 从 LRU
尾部取一小组候选页，对每个候选页打分，并选择最应该从 DRAM 降级到 NVM 的页面。

当前仓库的目标是先做出一套可信、可复现的原型实验，不是一次性完成论文级大规模
评测。第一阶段先稳定比较 QMAP 和几个简单 baseline，再继续扩展真实 trace、
消融实验和更强的系统 baseline。

## 当前实现

当前 QMAP 实验链路如下：

```text
PC,Address,RW trace
-> qmap/qmap_generator.py
-> QMAP JSONL 训练样本
-> qmap/qmap_train.py
-> QMAP checkpoint
-> qmap/qmap_eval.py
-> LRU / Random / LFU / CLOCK / QMAP replay 指标
```

模型路径包括：

- 物理地址、PC、读写类型三路 embedding
- 轻量 Transformer encoder
- 使用可学习 query 的 Q-Former，用于提取全局访存模式
- 基于 LRU 尾部候选页的页面打分器
- cost-aware ranking loss，标签由离线 replay 统计得到，包括未来不活跃程度、
  coldness、write sensitivity 和 migration cost

## 目录结构

```text
qmap/
  trace_builder.py              # 构造或转换页粒度 trace
  qmap_generator.py             # 生成 QMAP JSONL 样本
  qmap_train.py                 # 训练 QMAP checkpoint
  qmap_eval.py                  # replay 评估所有策略
  qmap_integration_test.py      # 模型和 loss 的 smoke test

policy_learning/cache_model/
  embed.py                      # QMAP embedding 模块
  model.py                      # Transformer、Q-Former、候选页打分器
  qmap_loss.py                  # cost-aware ranking loss

dataset/
  raw_traces/                   # 原始 trace
  processed/                    # train / valid / test CSV trace
  jsonl/                        # 生成的 QMAP 训练样本
  metadata/                     # trace schema 和 split 信息

scripts/
  run_prototype_experiment.py   # 一键原型实验脚本
  run_qmap_generate.bash        # 手动生成样本脚本
  run_qmap_train.bash           # 手动训练脚本
  run_qmap_eval.bash            # 手动评估 QMAP 脚本

outputs/
  checkpoints/                  # 训练得到的模型 checkpoint
  results/                      # JSON / CSV / Markdown 实验结果

logs/                           # 临时日志
docs/                           # 更长的说明、路线图和历史文档
```

`requirements.txt` 暂时保持原样，因为服务器环境已经能跑。

## 输入 Trace 格式

原型实验推荐使用如下 CSV 格式：

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

仓库里已经有一个 toy split：

```text
dataset/processed/try_train.csv
dataset/processed/try_valid.csv
dataset/processed/try_test.csv
```

如果服务器上没有这几个文件，一键实验脚本会自动用 `qmap/trace_builder.py`
生成一套默认 toy trace，并切分出 `try_train.csv`、`try_valid.csv` 和
`try_test.csv`。这组数据适合 smoke test 和第一版原型实验，但还不能支撑最终论文
里的强结论。

## 一键运行原型实验

在服务器上运行：

```bash
python scripts/run_prototype_experiment.py \
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

该命令会自动完成：

0. 如果 `dataset/processed/try_*.csv` 不存在，先自动生成默认 toy trace
1. 从 `try_train.csv` 生成 QMAP JSONL 训练样本
2. 训练 QMAP 模型
3. 在 `try_test.csv` 上评估 LRU、Random、LFU、CLOCK 和 QMAP
4. 生成 JSON、CSV 和 Markdown 结果表

输出目录如下：

```text
dataset/jsonl/try_prototype_train.jsonl
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
outputs/results/try_prototype/
  lru.json
  random.json
  lfu.json
  clock.json
  qmap.json
  summary.csv
  summary.md
  logs/
```

主结果表在：

```text
outputs/results/try_prototype/summary.md
```

## 手动运行各步骤

生成训练样本：

```bash
python qmap/qmap_generator.py \
  --input dataset/processed/try_train.csv \
  --output dataset/jsonl/try_train.jsonl \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --dram_capacity 128 \
  --page_shift 12
```

训练 QMAP：

```bash
python qmap/qmap_train.py \
  --train_data dataset/jsonl/try_train.jsonl \
  --output_dir outputs/checkpoints/try \
  --epochs 10 \
  --batch_size 32 \
  --lr 1e-4 \
  --device cuda
```

评估 baseline 和 QMAP：

```bash
python qmap/qmap_eval.py --trace_path dataset/processed/try_test.csv --policy lru --page_shift 12
python qmap/qmap_eval.py --trace_path dataset/processed/try_test.csv --policy random --page_shift 12
python qmap/qmap_eval.py --trace_path dataset/processed/try_test.csv --policy lfu --page_shift 12
python qmap/qmap_eval.py --trace_path dataset/processed/try_test.csv --policy clock --page_shift 12
python qmap/qmap_eval.py \
  --trace_path dataset/processed/try_test.csv \
  --policy qmap \
  --checkpoint outputs/checkpoints/try/qmap_epoch_10.pth \
  --page_shift 12 \
  --device cuda
```

## 评估指标

`qmap_eval.py` 会输出：

- `Hit rate`：DRAM 命中率
- `NVM reads`：NVM 读次数
- `NVM writes`：NVM 写次数
- `Migrations`：页面迁移次数
- `Weighted access cost`：加权访问代价
- `Policy decisions`：触发策略决策的次数
- `Avg decision time`：平均单次策略决策时间

当前原型使用一个简单的加权代价模型：

```text
DRAM read  = 1
DRAM write = 1
NVM read   = 2
NVM write  = 4
Migration  = 10
```

这些常数定义在 `qmap/qmap_eval.py` 中。如果把结果写进论文或报告，需要明确说明
这是原型 replay 的 cost model。

## 当前第一阶段实验目标

当前最有价值的第一张表是：

```text
LRU / Random / LFU / CLOCK / QMAP
对比：
hit rate、NVM writes、weighted access cost、migrations、avg decision time
```

这张表跑通并稳定后，再继续做：

- 更多 workload，覆盖不同 locality 和写入比例
- `history_length`、`candidate_count`、`dram_capacity`、`lookahead` 的敏感性实验
- 去掉 PC、去掉 RW、去掉 Q-Former、去掉 cost-aware label 的消融实验
- 如果论文仍然要声称超过已有学习型迁移方法，再加入更强 baseline

## 当前注意事项

- `dataset/processed/try_*.csv` 是 toy 数据，只能用于原型验证。
- 当前 QMAP 是离线训练 + replay 评估，不是完整 OS 内核集成。
- QMAP 推理只在 migration event 上执行，不在每次访存关键路径上执行。
- GPU 上计时前后已经做了 CUDA synchronize，`Avg decision time` 更接近真实单次
  决策开销。
