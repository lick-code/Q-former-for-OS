# QMAP 训练流程说明

本文档把当前仓库里与 **QMAP** 相关的训练流程整理成一份可执行的操作说明。

这个流程对应的是仓库里新增的 QMAP 原型链路，而不是原始 PARROT cache replacement 训练流程。

---

## 1. 训练目标

QMAP 当前的目标是：

- 从内存访问 trace 中构造训练样本
- 学习页面迁移策略
- 在 replay 评估中对比 `lru`、`random`、`qmap`

当前最小闭环是：

```text
CSV trace
-> qmap_generator.py
-> train_data.jsonl
-> qmap_train.py
-> checkpoint
-> qmap_eval.py
```

---

## 2. 代码入口

和训练直接相关的文件主要有：

- `cache_replacement/qmap/qmap_generator.py`
- `cache_replacement/qmap/qmap_train.py`
- `cache_replacement/qmap/qmap_eval.py`
- `cache_replacement/qmap/qmap_integration_test.py`

如果你只是想快速跑通一次流程，推荐先用 `example_memtrace.csv` 做 smoke test；如果要做正式实验，建议换成更长的真实 trace。

---

## 3. 环境准备

先进入仓库根目录：

```bash
cd /home/tingkun/lcs/cache_replacement
```

建议使用虚拟环境，并安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

如果你机器上要指定某块显卡，可以先检查可见 GPU：

```bash
nvidia-smi
```

如果要只使用某一块卡，可以在命令前设置：

```bash
export CUDA_VISIBLE_DEVICES=0
```

如果你想给自己留一个显卡型号检查位，可以先放一个变量占位：

```bash
# 例如：RTX 4090 / A100 / H100 / 其他型号
GPU_MODEL="YOUR_GPU_MODEL_HERE"
echo "Target GPU model: ${GPU_MODEL}"
```

> 说明：`GPU_MODEL` 这里只是给脚本留注释位，不会自动限制硬件型号。真正限制使用哪块卡，还是靠 `CUDA_VISIBLE_DEVICES`。

---

## 4. 第一步：把 CSV trace 转成训练数据

QMAP 训练不是直接吃 CSV，而是先生成 `train_data.jsonl`。

### 4.1 输入格式

输入 trace 最好至少包含下面两列：

```text
PC,Address
```

如果有读写信息，建议用：

```text
PC,Address,RW
```

其中 `RW` 支持：

- `R / W`
- `read / write`
- `load / store`
- `L / S`
- `0 / 1`

如果没有 `RW`，脚本会使用 fallback 逻辑，但这更偏原型验证。

### 4.2 生成训练样本

最简单的生成命令：

```bash
python qmap/qmap_generator.py \
  --input environment/example_memtrace.csv \
  --output train_data.jsonl
```

如果你有自己的 trace：

```bash
python qmap/qmap_generator.py \
  --input /path/to/your_trace.csv \
  --output /path/to/train_data.jsonl
```

如果你想调整历史长度和 lookahead，也可以显式传参：

```bash
python qmap/qmap_generator.py \
  --input /path/to/your_trace.csv \
  --output /path/to/train_data.jsonl \
  --history_length 10 \
  --lookahead 64
```

### 4.3 建议的批处理脚本

下面这个 Bash 示例适合你先跑通一条数据管线：

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /home/tingkun/lcs/cache_replacement
source venv/bin/activate

export CUDA_VISIBLE_DEVICES=0
GPU_MODEL="YOUR_GPU_MODEL_HERE"
echo "Using GPU placeholder: ${GPU_MODEL}"

INPUT_TRACE="environment/example_memtrace.csv"
OUTPUT_JSONL="train_data.jsonl"

python qmap/qmap_generator.py \
  --input "${INPUT_TRACE}" \
  --output "${OUTPUT_JSONL}"
```

你可以把它保存成 `run_generate.sh`，然后执行：

```bash
bash run_generate.sh
```

---

## 5. 第二步：先跑一次集成测试

在正式训练前，建议先做一次 smoke test，确认数据、模型、loss、backward 都正常。

```bash
python qmap/qmap_integration_test.py
```

预期是能看到类似：

```text
QMAP Pipeline Integration Successful!
```

如果这个都过不了，先不要开始正式训练。

---

## 6. 第三步：训练模型

### 6.1 最小训练命令

```bash
python qmap/qmap_train.py \
  --train_data train_data.jsonl \
  --epochs 2 \
  --batch_size 2
```

训练完成后，checkpoint 默认会保存到：

```text
qmap_checkpoints/
```

### 6.2 指定显卡的训练命令

如果你想只用 0 号 GPU：

```bash
export CUDA_VISIBLE_DEVICES=0
python qmap/qmap_train.py \
  --train_data train_data.jsonl \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

如果你想保留“指定 GPU 型号”的注释位，可以这样写：

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /home/tingkun/lcs/cache_replacement
source venv/bin/activate

export CUDA_VISIBLE_DEVICES=0
GPU_MODEL="A100"
echo "Expected GPU model: ${GPU_MODEL}"

python qmap/qmap_train.py \
  --train_data train_data.jsonl \
  --output_dir qmap_checkpoints \
  --epochs 10 \
  --batch_size 32 \
  --lr 1e-4 \
  --device cuda
```

### 6.3 推荐的训练参数起点

如果你是第一次在新数据集上跑，建议从下面这个起点开始：

- `--epochs 10`
- `--batch_size 32`
- `--lr 1e-4`
- `--device cuda`

如果显存不够，优先调小 batch size。

### 6.4 训练时会输出什么

训练过程中一般会打印：

- 数据集样本数
- batch size
- epochs
- 学习率
- 设备
- 每个 epoch 的平均 loss
- checkpoint 保存路径

例如：

```text
Epoch [1/10] iter=1 loss=...
Epoch [1/10] avg_loss=...
Saved checkpoint: qmap_checkpoints/qmap_epoch_1.pth
```

---

## 7. 第四步：评估训练结果

训练完以后，可以用 replay evaluation 对比三种策略：

- `lru`
- `random`
- `qmap`

### 7.1 评估 LRU

```bash
python qmap/qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy lru
```

### 7.2 评估 Random

```bash
python qmap/qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy random
```

### 7.3 评估 QMAP

```bash
python qmap/qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_10.pth
```

如果想指定 GPU：

```bash
export CUDA_VISIBLE_DEVICES=0
python qmap/qmap_eval.py \
  --trace_path environment/example_memtrace.csv \
  --policy qmap \
  --checkpoint qmap_checkpoints/qmap_epoch_10.pth \
  --device cuda
```

### 7.4 输出指标

会输出：

- `Total accesses`
- `Hits`
- `Misses`
- `Hit rate`
- `Migrations`
- `NVM reads`
- `NVM writes`
- `Weighted access cost`

建议重点看：

- `Hit rate`
- `Weighted access cost`
- `Migrations`

---

## 8. 一个更完整的训练脚本示例

下面是一个从生成数据到训练再到评估的完整 Bash 示例。

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /home/tingkun/lcs/cache_replacement
source venv/bin/activate

# 只让 0 号 GPU 可见
export CUDA_VISIBLE_DEVICES=0
GPU_MODEL="A100"
echo "Target GPU model: ${GPU_MODEL}"

TRACE_PATH="environment/example_memtrace.csv"
TRAIN_JSONL="train_data.jsonl"
CKPT_DIR="qmap_checkpoints"

# 1) 生成训练数据
python qmap/qmap_generator.py \
  --input "${TRACE_PATH}" \
  --output "${TRAIN_JSONL}"

# 2) 训练
python qmap/qmap_train.py \
  --train_data "${TRAIN_JSONL}" \
  --output_dir "${CKPT_DIR}" \
  --epochs 10 \
  --batch_size 32 \
  --lr 1e-4 \
  --device cuda

# 3) 评估
python qmap/qmap_eval.py \
  --trace_path "${TRACE_PATH}" \
  --policy qmap \
  --checkpoint "${CKPT_DIR}/qmap_epoch_10.pth" \
  --device cuda
```

---

## 9. 训练前的检查清单

正式训练前，建议确认下面这些项：

- [ ] 你的 trace 至少有 `PC` 和 `Address`
- [ ] 最好带 `RW`
- [ ] `qmap_generator.py` 能成功生成 `train_data.jsonl`
- [ ] `qmap_integration_test.py` 可以通过
- [ ] 你的 GPU 可见性配置正确
- [ ] `CUDA_VISIBLE_DEVICES` 已设置到你想使用的卡
- [ ] 训练目录有足够磁盘空间保存 checkpoint

---

## 10. 常见问题

### 10.1 `hidden_dim` 报错

`qmap_train.py` 里要求：

```text
hidden_dim = address_embed_dim + pc_embed_dim + rw_embed_dim
```

默认值是：

- `8 + 8 + 2 = 18`

所以如果你改了 embedding 维度，也要同步改 `--hidden_dim`。

### 10.2 样本数量太少

如果生成的 `train_data.jsonl` 很小，模型会很难学到东西。建议：

- 用更长的 trace
- 增加多个 trace 进行混合训练
- 检查 generator 是否真的读到了有效访问序列

### 10.3 训练能跑但效果没变化

可能原因：

- 数据太少
- 标签太噪声
- trace 太短
- 模型容量不够
- 学习率不合适

可以先从更长 trace 和更稳定的数据开始。

---

## 11. 结论

如果你的目标是先把 QMAP 原型训练起来，当前最推荐的流程就是：

1. 准备 trace
2. 生成 `train_data.jsonl`
3. 先跑 integration test
4. 再跑 `qmap_train.py`
5. 用 `qmap_eval.py` 做 replay 评估

如果你愿意，我下一步还可以继续帮你补一版：

- **更适合正式实验的 README 风格文档**
- 或者 **直接给你再写一个一键训练的 `bash` 脚本模板**
