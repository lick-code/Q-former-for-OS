# QMAP 项目交接说明

本文档用于交接当前 QMAP 原型工作。当前代码库原本基于 PARROT：

```text
An Imitation Learning Approach for Cache Replacement
```

原始 PARROT 面向 CPU Cache 替换，核心逻辑围绕 Cache Set / Cache Way /
Cache Line。当前我们已经新增了一条 QMAP 原型链路，目标变成：

```text
面向 DRAM/NVM 混合内存系统的全局页面迁移策略
```

QMAP 不再基于 Cache Set 做替换，而是在 DRAM miss 且 DRAM 满时，从 LRU
不活跃链表尾部采样 64 个候选页，并由模型选择最应该迁移出 DRAM 的页面。

## 当前进度

目前已经完成 QMAP 的最小可训练闭环：

```text
CSV trace
-> qmap_generator.py
-> train_data.jsonl
-> qmap_train.py
-> checkpoint
-> qmap_eval.py replay evaluation
```

模型链路如下：

```text
历史访存序列
-> Address / PC / RW Embedding
-> Transformer Encoder
-> Q-Former
-> 64 页面候选池打分
-> Cost-aware Listwise Ranking Loss
```

已经验证过：

- `qmap_generator.py` 可以生成 `train_data.jsonl`
- `qmap_integration_test.py` 可以完整跑通 forward、loss、backward
- `qmap_train.py` 可以训练并保存 checkpoint
- `qmap_eval.py` 可以 replay 评估 LRU / Random / QMAP 策略

## 主要文件说明

### `qmap_generator.py`

作用：从原始 CSV trace 生成 QMAP 训练数据 `train_data.jsonl`。

默认输入：

```text
environment/example_memtrace.csv
```

支持的 CSV 格式：

```text
PC,Address
PC,Address,RW
```

CSV 可以有表头，也可以没有表头。

RW 字段支持：

```text
R / W
read / write
load / store
L / S
0 / 1
```

如果 trace 没有 RW 列，会打印 warning，并使用 fallback：

```python
rw = page & 1
```

运行：

```bash
python qmap_generator.py
```

典型输出：

```text
[Warning] RW column not found in trace. Using simulated rw = page & 1 as fallback.
RW source: fallback simulated rw = page & 1
Read accesses: ...
Write accesses: ...
Total trace records: ...
Generated samples: ...
Wrote: train_data.jsonl
```

带真实 RW 的 trace 运行示例：

```bash
python qmap_generator.py \
  --input environment/test_memtrace_with_rw.csv \
  --output test_train_data_with_rw.jsonl \
  --history_length 2 \
  --lookahead 2
```

### `qmap_integration_test.py`

作用：QMAP 全流程 smoke test。

它会测试：

```text
Dataset
-> Embedding
-> Transformer + Q-Former
-> Candidate Scorer
-> Loss
-> backward
```

运行：

```bash
python qmap_integration_test.py
```

预期输出包含：

```text
access_features shape: (2, 4, 18)
Z shape: (2, 4, 18)
eviction_scores shape: (2, 64)
QMAP Pipeline Integration Successful!
```

### `qmap_train.py`

作用：训练 QMAP 模型并保存 checkpoint。

运行示例：

```bash
python qmap_train.py --train_data train_data.jsonl --epochs 2 --batch_size 2
```

训练日志会打印：

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

默认 checkpoint 目录：

```text
qmap_checkpoints/
```

### `qmap_eval.py`

作用：replay 评估页面迁移策略。

支持三种策略：

```text
lru
random
qmap
```

运行 LRU：

```bash
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy lru
```

运行 Random：

```bash
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy random
```

运行 QMAP：

```bash
python qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_2.pth
```

输出指标：

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

注意：`environment/example_memtrace.csv` 只有 10 条记录，只适合验证脚本能跑通，
不适合做正式实验结论。

## 模型组件说明

### 数据和 Embedding

相关文件：

```text
policy_learning/cache_model/qmap_data.py
policy_learning/cache_model/embed.py
```

QMAP 输入序列包含：

```text
physical_address
pc
rw
```

三路输入分别经过 Embedding 后拼接：

```text
[batch_size, sequence_length, hidden_dim]
```

当前默认 toy 设置：

```text
hidden_dim = 18
```

也就是：

```text
address_embed_dim = 8
pc_embed_dim = 8
rw_embed_dim = 2
```

### 宏观访存模式提取

相关文件：

```text
policy_learning/cache_model/model.py
```

主要类：

```python
QMAPMacroscopicPatternExtractor
QFormer
```

流程：

```text
[B, T, hidden_dim]
-> causal TransformerEncoder
-> K 个可学习 Query 的 Q-Former
-> Z: [B, K, hidden_dim]
```

当前默认：

```text
K = 4
hidden_dim = 18
```

### 64 页面候选池打分

相关文件：

```text
policy_learning/cache_model/model.py
```

主要类：

```python
QMAPCandidateScorer
```

输入：

```text
Z: [B, K, hidden_dim]
candidates_features: [B, 64, page_dim]
```

当前默认：

```text
page_dim = 21
```

输出：

```text
eviction_scores: [B, 64]
```

QMAP replay 时选择分数最高的候选页迁出 DRAM。

### Loss

相关文件：

```text
policy_learning/cache_model/qmap_loss.py
```

主要类：

```python
QMAPCostAwareRankingLoss
```

真实目标分数：

```python
y_true = (
    lambda_1 * inactivity
    + lambda_2 * coldness
    - lambda_3 * write_sensitivity
    - lambda_4 * migration_cost
)
```

损失函数：

```text
ListNet 风格列表级排序损失
```

## 训练数据格式

`train_data.jsonl` 每一行是一个 JSON object：

```json
{
  "physical_address": [4096, 8192],
  "pc": [4194595, 4194600],
  "rw": [0, 1],
  "candidates_features": [[0.0, "... 21 dims ..."], "... 64 pages total ..."],
  "inactivity": [1.0, "... 64 values total ..."],
  "coldness": [0.99, "... 64 values total ..."],
  "write_sensitivity": [0.12, "... 64 values total ..."],
  "migration_cost": [0.0, "... 64 values total ..."]
}
```

batch 后的形状：

```text
physical_address: [B, history_length]
pc: [B, history_length]
rw: [B, history_length]
candidates_features: [B, 64, 21]
inactivity: [B, 64]
coldness: [B, 64]
write_sensitivity: [B, 64]
migration_cost: [B, 64]
```

## 当前原型中的简化假设

当前版本是研究原型，还不是最终实验系统。

主要简化：

- 如果 trace 没有 RW，使用 `rw = page & 1` 模拟。
- 候选页特征是手工构造的 21 维特征。
- `inactivity`、`coldness`、`write_sensitivity`、`migration_cost` 是启发式
  oracle label。
- replay evaluation 里的访问代价是固定常数：

```text
DRAM read = 1
DRAM write = 1
NVM read = 2
NVM write = 8
migration cost = 10
```

## 交接后的建议下一步

### 1. 换成更大的真实 trace

当前 example trace 太小，不适合正式比较。

建议准备真实 trace：

```text
PC,Address,RW
```

如果 RW 暂时没有，也可以先用 fallback 跑通。

### 2. 生成真实训练数据

```bash
python qmap_generator.py \
  --input path/to/real_trace.csv \
  --output train_data.jsonl
```

### 3. 训练 QMAP

```bash
python qmap_train.py \
  --train_data train_data.jsonl \
  --epochs 5 \
  --batch_size 32
```

### 4. replay 比较 LRU / Random / QMAP

```bash
python qmap_eval.py --trace_path path/to/real_trace.csv --policy lru
python qmap_eval.py --trace_path path/to/real_trace.csv --policy random
python qmap_eval.py \
  --trace_path path/to/real_trace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_5.pth
```

### 5. 后续研究重点

后续最值得改进的地方：

- 更真实的页面特征设计
- 更真实的 write sensitivity 估计
- 更真实的 migration cost 建模
- train / eval trace split
- replay simulator fidelity
- 与真实 DRAM/NVM simulator 对齐

## 快速 Smoke Test 命令

```bash
python qmap_generator.py
python qmap_integration_test.py
python qmap_train.py --train_data train_data.jsonl --epochs 2 --batch_size 2
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy lru
python qmap_eval.py --trace_path environment/example_memtrace.csv --policy random
python qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_2.pth
```

如果这些命令能跑通，说明当前 QMAP 原型链路基本正常。
