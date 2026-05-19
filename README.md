# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

和老师讨论后，后续主线不再使用 Q-Former。最终模型收敛为：

```text
QMAP-Pool = Transformer Encoder + mean pooling + candidate scorer
```

Q-Former 相关实验只作为前期探索记录保留，不再作为论文主线。当前已补上第一批 4 个 PARSEC 100k 真实 trace，下一步进入 100k pilot 训练评估。

## 当前状态

已经完成：

```text
1. synthetic trace 上的 QMAP 原型 pipeline：trace -> JSONL -> train -> replay -> summary。
2. LRU / Random / LFU / CLOCK / QMAP 的基础对比。
3. checkpoint sweep、参数敏感性、消融实验。
4. Q-Former 与 mean pooling 的对照。
5. Encoder 层数对照，结果显示 1-layer mean_pool 已经足够稳。
```

当前结论：

```text
1. QMAP 在 writeheavy synthetic workload 上表现最好，能降低 NVM writes 和 weighted access cost。
2. QMAP 不是所有 workload 都优于 LFU，尤其在 hotset、phasechange、pcrwstress 上 LFU 仍然很强。
3. mean pooling 比 Q-Former 更稳，且结构更简单、推理开销更低。
4. 后续论文主线应改为 QMAP-Pool，而不是 QMAP-Full/Q-Former。
5. 最大短板已从“没有真实 trace”转为“需要在 4 个 PARSEC 100k trace 上完成 pilot 训练评估，并扩到 1M/5M 正式规模”。
```

## 结果总览

| 模块 | 状态 | 结果 |
|---|---|---|
| 原型主实验 | 已完成 | `outputs/results/try_prototype/summary.md` |
| Checkpoint sweep | 已完成 | `outputs/results/checkpoint_sweep/summary.md` |
| 多 workload | 已完成 | `outputs/results/workload_suite/summary.md` |
| pcrwstress workload | 已完成 | `outputs/results/workload_suite_pcrwstress/summary.md` |
| 参数敏感性 | 已完成 | `outputs/results/qmap_parameter_sensitivity/summary.md` |
| 消融实验 | 已完成 | `outputs/results/qmap_ablation/` |
| cost-aware 权重实验 | 已完成 | `outputs/results/qmap_cost_w8_m4_writeheavy/summary.md` |
| 阶段 0：实验口径冻结 | 已完成 | 新实验默认 `mean_pool`，表格统一 `QMAP-Pool` |
| Q-Former 对照 | 已完成，仅作历史参考 | `outputs/results/qmap_qformer_comparison_writeheavy/summary.md` |
| Encoder 层数对照 | 已完成，仅作历史参考 | `outputs/results/qmap_encoder_depth_comparison_writeheavy/summary.md` |
| 真实/标准 workload | 4 个 PARSEC 100k 真实 trace 已完成 | `outputs/results/real_trace_stats/summary.md` |

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
  model.py                      # Transformer、mean pooling、候选页 scorer；Q-Former 代码保留为历史探索
  qmap_loss.py                  # cost-aware ranking loss
  qmap_data.py                  # JSONL dataset 和 collate 逻辑

scripts/
  run_prototype_experiment.py          # 单 workload 原型实验
  run_qmap_checkpoint_sweep.py         # checkpoint sweep
  build_workload_suite.py              # 生成 synthetic workload trace
  run_workload_suite.py                # 多 workload 训练和评估
  run_qmap_parameter_sensitivity.py    # 参数敏感性实验
  run_qmap_ablation.py                 # 消融实验
  run_qmap_encoder_depth_comparison.py # mean_pool 下 encoder 层数对照

dataset/
  raw_traces/                   # 原始 traces，后续真实 trace 也放这里
  processed/                    # train / valid / test CSV traces
  jsonl/                        # QMAP 训练样本
  metadata/                     # trace schema、split 和 workload manifest

outputs/
  checkpoints/                  # 训练得到的模型 checkpoint
  results/                      # JSON / CSV / Markdown 实验结果
```

## 最终模型设定

后续默认模型：

```text
QMAP-Pool
  access sequence encoder: Transformer Encoder
  sequence aggregation: mean pooling
  eviction decision: candidate scorer
```

不再继续做：

```text
Q-Former query 数 K sweep
Q-Former light/tiny 变体
Encoder 2/3 层 sweep
把 Q-Former 作为论文主贡献点
```

保留原因：

```text
1. mean_pool 在 phasechange、pcrwstress 和 Q-Former 对照中更稳。
2. Encoder 层数对照显示 1-layer mean_pool 的 weighted cost 最低且推理最快。
3. 去掉 Q-Former 后论文主线更清晰，复杂度更低。
```

## 下一步实验规划

下面是推荐的执行顺序。重点是先收敛代码和模型命名，再采集真实数据，再跑正式实验。不要一开始就大规模跑，否则出错成本很高。

### 阶段 0：冻结实验口径

状态：已完成。

目标：把后续所有实验统一到 QMAP-Pool。

已落实：

```text
1. qmap_generator.py / qmap_train.py 默认 ablation=mean_pool。
2. run_prototype_experiment.py、run_workload_suite.py、run_qmap_parameter_sensitivity.py 等新实验入口显式传入 mean_pool。
3. 后续 summary 和论文表格统一叫 QMAP-Pool。
4. Q-Former comparison、Q-Former K sweep、Encoder 2/3 层 sweep 加保护开关，仅用于复现历史探索。
5. replay cost model 暂时不再改，继续使用当前 qmap_eval.py 的配置。
```

建议新增或确认一个主运行配置：

```text
history_length = 10
candidate_count = 64
lookahead = 256
dram_capacity = 128
epochs = 10 或 20
batch_size = 32
model = QMAP-Pool
ablation = mean_pool
```

严格依赖关系：

```text
阶段 0 必须在所有真实数据正式实验之前完成。
否则后面结果会混入 Q-Former / mean_pool 两套口径，论文会很难写。
```

可以并行：

```text
阶段 0 的 README/脚本命名整理 可以和 真实 benchmark 环境准备 并行。
```

### 阶段 1：选择真实/标准数据集

目标：补一组正式 workload，解决“只有 synthetic trace”的问题。

推荐优先级：

```text
优先级 1：PARSEC
  原因：学术论文中常见，适合多核/内存行为研究，获取和运行成本相对可控。

优先级 2：真实系统 workload，例如 Redis / RocksDB + YCSB
  原因：系统味更强，但采集链路更麻烦，容易拖慢进度。

优先级 3：SPEC CPU
  原因：权威性强，但通常涉及授权和运行规范，成本最高。
```

阶段 1 已选定 PARSEC 作为第一批真实/标准 benchmark。第一批先跑 4 个：

```text
blackscholes    计算密集，作为相对平稳 workload
canneal         内存访问更复杂，常用于内存系统研究
streamcluster   流式/聚类访问，有机会验证 streaming-like 行为
dedup           数据处理/写入压力更明显，可观察 NVM writes
```

`ferret` 作为 fallback：如果 `dedup` 的依赖、构建或 trace 采集不稳定，就用 `ferret` 替换。

本阶段输出：

```text
outputs/results/parsec_stage1_selection/summary.md
dataset/metadata/parsec_workload_manifest.json
```

阶段 1 只冻结 benchmark 选择和后续采集契约，不把 PARSEC 源码、输入集或大规模 raw trace 放进仓库。阶段 2 在 Linux/WSL/服务器上搭建 PARSEC 环境，并采集 `PC,Address,RW` CSV trace。

严格依赖关系：

```text
先确定 benchmark 列表，再写采集脚本；
不要一边改列表一边跑完整训练。
```

可以并行：

```text
PARSEC 环境搭建
trace 采集工具准备
QMAP-Pool synthetic 复跑脚本整理
```

### 阶段 2：实现真实 trace 采集和转换

目标：把真实程序访存记录转成 QMAP 已支持的 CSV 格式。

最终格式必须是：

```text
PC,Address,RW
0x400100,0x7f12345000,R
0x400108,0x7f12346000,W
```

采集方式建议：

```text
Pin / DynamoRIO / Valgrind 任选一个。
优先建议 Pin 或 DynamoRIO，因为可以直接拿到 PC、访存地址、读写类型。
```

第一版采集要求：

```text
1. 只采用户态内存访问。
2. 每条记录包含 PC、Address、RW。
3. 支持限制最大记录数，例如 100k / 1M / 5M。
4. 支持跳过 warmup，例如跳过前 10k 或 100k 条访问。
5. 输出 CSV 到 dataset/raw_traces/。
```

建议文件命名：

```text
dataset/raw_traces/parsec_blackscholes.csv
dataset/raw_traces/parsec_canneal.csv
dataset/raw_traces/parsec_streamcluster.csv
dataset/raw_traces/parsec_dedup.csv
```

当前已实现的采集链路：

```text
scripts/collect_trace_drmemtrace.py
  使用 DynamoRIO 自带 drmemtrace 采集离线访存 trace；
  自动执行 drraw2trace raw -> trace 转换；
  再调用 view 工具解析 read/write data reference；
  输出 QMAP 需要的 PC,Address,RW CSV；
  支持 --max-records、--skip-records、--trace-after-instrs；
  默认把 Address 对齐到 4KB 页边界，和 QMAP page trace 口径一致。
  在中文路径工作区下对 drraw2trace/view 使用项目相对路径，避免工具内部路径编码问题。

scripts/convert_drmemtrace_view.py
  把 drmemtrace view 文本流转换为 PC,Address,RW。

scripts/prepare_real_trace.py
  规范化 raw trace；
  截取 100k/1M/5M；
  按时间顺序切成 80% train / 10% valid / 10% test；
  输出 trace 质量统计和 real_workload_manifest.json。

tools/trace_collectors/dynamorio/README.md
  记录 DynamoRIO 采集命令模板。
```

本机 100k instrumentation pilot 已完成：

```text
DynamoRIO: 11.91.20581
drrun: tools/extern/DynamoRIO-Windows-11.91.20581/bin64/drrun.exe
target: D:/Anaconda/python.exe
target workload: 64MB bytearray page-stride write/read loop
trace window: --trace-after-instrs 5000000, --max-records 100000, --skip-records 10000
collector result: seen data refs = 110000, wrote records = 100000
```

本机 pilot 输出：

```text
dataset/raw_traces/local_python_loop_100k.csv
dataset/raw_traces/local_python_loop_pilot.csv
dataset/processed/local_python_loop_pilot_train.csv
dataset/processed/local_python_loop_pilot_valid.csv
dataset/processed/local_python_loop_pilot_test.csv
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

质量统计：

```text
records = 100000
unique pages = 115
unique PCs = 2147
write ratio = 0.3514
reuse ratio = 0.9989
split = 80000 / 10000 / 10000
```

QMAP 数据管线验证：

```bash
python qmap/qmap_generator.py \
  --input dataset/processed/local_python_loop_pilot_train.csv \
  --output dataset/jsonl/local_python_loop_pilot_train_h64.jsonl \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --dram_capacity 64 \
  --page_shift 12 \
  --ablation mean_pool
```

生成结果：

```text
RW source = real trace RW column
train records = 80000
generated samples = 173
```

说明：本机 Python pilot 的目标是验证 instrumentation、CSV schema、切分和 JSONL 入口链路，不作为论文主表 workload。

PARSEC 100k 真实 trace pilot 已完成：

```text
WSL source: D:/WSL/Ubuntu-22.04/Ubuntu-22.04.tar and ext4.vhdx
WSL distro used: QMAP-Ubuntu-22.04, Ubuntu 22.04.5 LTS, root
PARSEC source: connorimes/parsec-3.0 sparse checkout
PARSEC packages:
  parsec.blackscholes, gcc-pthreads
  parsec.canneal, gcc-serial
  parsec.streamcluster, gcc-pthreads
  parsec.dedup, gcc-pthreads with -fcommon for modern GCC
DynamoRIO: Linux 11.91.20581
drmemtrace window: --max-records 100000, --skip-records 10000, --trace-ref-multiplier 20
collector result: each workload saw 110000 data refs and wrote 100000 records
```

采集命令示例：

```bash
python3 scripts/collect_trace_drmemtrace.py \
  --drrun /root/qmap-work/tools/extern/DynamoRIO-Linux-11.91.20581/bin64/drrun \
  --output dataset/raw_traces/parsec_blackscholes_100k.csv \
  --work-dir /root/qmap-work/drmemtrace/parsec_blackscholes_100k_v2 \
  --max-records 100000 \
  --skip-records 10000 \
  --trace-ref-multiplier 20 \
  -- \
  /root/qmap-work/parsec-3.0/pkgs/apps/blackscholes/inst/amd64-linux.gcc-pthreads/bin/blackscholes \
  1 \
  /root/qmap-work/parsec-inputs/blackscholes-simdev/in_16.txt \
  /root/qmap-work/parsec-runs/blackscholes/prices_trace.txt
```

规范化和质量检查命令模板：

```bash
python3 scripts/prepare_real_trace.py \
  --input dataset/raw_traces/<workload>_100k.csv \
  --workload <workload> \
  --limit 100000
```

PARSEC 100k 输出：

```text
dataset/raw_traces/parsec_blackscholes_100k.csv
dataset/raw_traces/parsec_blackscholes.csv
dataset/processed/parsec_blackscholes_train.csv
dataset/processed/parsec_blackscholes_valid.csv
dataset/processed/parsec_blackscholes_test.csv
dataset/raw_traces/parsec_canneal_100k.csv
dataset/raw_traces/parsec_canneal.csv
dataset/processed/parsec_canneal_train.csv
dataset/processed/parsec_canneal_valid.csv
dataset/processed/parsec_canneal_test.csv
dataset/raw_traces/parsec_streamcluster_100k.csv
dataset/raw_traces/parsec_streamcluster.csv
dataset/processed/parsec_streamcluster_train.csv
dataset/processed/parsec_streamcluster_valid.csv
dataset/processed/parsec_streamcluster_test.csv
dataset/raw_traces/parsec_dedup_100k.csv
dataset/raw_traces/parsec_dedup.csv
dataset/processed/parsec_dedup_train.csv
dataset/processed/parsec_dedup_valid.csv
dataset/processed/parsec_dedup_test.csv
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

PARSEC 100k 质量统计：

```text
parsec_blackscholes:  records=100000, unique_pages=104, unique_PCs=4471, write_ratio=0.3231, reuse_ratio=0.9990
parsec_canneal:       records=100000, unique_pages=157, unique_PCs=1946, write_ratio=0.2736, reuse_ratio=0.9984
parsec_streamcluster: records=100000, unique_pages=156, unique_PCs=1941, write_ratio=0.2744, reuse_ratio=0.9984
parsec_dedup:         records=100000, unique_pages=121, unique_PCs=2678, write_ratio=0.3963, reuse_ratio=0.9988
all splits = 80000 / 10000 / 10000
schema check = 100000 rows per raw 100k CSV, bad rows = 0
```

该质量检查已通过，可以进入阶段 4 的 100k pilot 训练评估。后续正式 PARSEC/YCSB 规模从 100k pilot 扩到 1M/5M。

100k pilot 采集命令模板：

```bash
python scripts/collect_trace_drmemtrace.py \
  --output dataset/raw_traces/parsec_blackscholes_100k.csv \
  --max-records 100000 \
  --skip-records 10000 \
  --trace-ref-multiplier 20 \
  -- \
  /path/to/blackscholes args...
```

pilot 通过后做规范化、切分和质量检查：

```bash
python scripts/prepare_real_trace.py \
  --input dataset/raw_traces/parsec_blackscholes_100k.csv \
  --workload parsec_blackscholes \
  --limit 100000
```

输出：

```text
dataset/raw_traces/parsec_blackscholes.csv
dataset/processed/parsec_blackscholes_train.csv
dataset/processed/parsec_blackscholes_valid.csv
dataset/processed/parsec_blackscholes_test.csv
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

扩到 1M 或 5M 时只改记录数：

```bash
# 1M
python scripts/collect_trace_drmemtrace.py \
  --output dataset/raw_traces/parsec_blackscholes_1m.csv \
  --max-records 1000000 \
  --skip-records 100000 \
  --trace-ref-multiplier 12 \
  -- \
  /path/to/blackscholes args...

# 5M
python scripts/collect_trace_drmemtrace.py \
  --output dataset/raw_traces/parsec_blackscholes_5m.csv \
  --max-records 5000000 \
  --skip-records 100000 \
  --trace-ref-multiplier 12 \
  -- \
  /path/to/blackscholes args...
```

本机环境检查结果：

```text
DynamoRIO 已下载并解压到 tools/extern/，该目录被 .gitignore 忽略。
drrun -version 通过：11.91.20581。
drmemtrace view -> PC,Address,RW 转换器 smoke test 通过。
prepare_real_trace.py 规范化、80/10/10 切分和统计输出通过。
本机 100k instrumentation pilot 已通过。
本机 WSL 里的 PARSEC blackscholes/canneal/streamcluster/dedup 100k 真实 trace pilot 已通过。
```

严格依赖关系：

```text
必须先有 raw trace，才能 split；
必须 split 成 train/test，才能 generate JSONL；
必须 generate JSONL，才能 train QMAP-Pool；
必须有 checkpoint，才能评估 QMAP-Pool。
```

可以并行：

```text
不同 benchmark 的 trace 采集可以并行；
同一个 benchmark 的 raw -> split -> jsonl -> train -> eval 必须串行。
```

### 阶段 3：真实 trace 质量检查

目标：不要把坏 trace 直接拿去训练。

每个真实 trace 至少统计：

```text
total accesses
unique pages
read/write ratio
unique PCs
page reuse 情况
前 10 个 hot pages 占比
train/test 是否分布差异过大
```

判断标准：

```text
如果 write ratio 太低，不能指望 QMAP 明显减少 NVM writes。
如果 unique pages 太少，LFU/LRU 可能已经足够好。
如果 streaming 太强，所有策略 hit rate 都可能很低。
如果 train/test 分布完全不同，QMAP 可能泛化差。
```

建议输出：

```text
dataset/metadata/real_workload_manifest.json
outputs/results/real_trace_stats/summary.md
```

严格依赖关系：

```text
质量检查必须在正式训练前完成。
```

可以并行：

```text
多个 workload 的统计可以并行。
```

### 阶段 4：小规模 pilot 实验

目标：先确认真实数据 pipeline 能跑通，不追求最终大规模。

建议每个 workload 先截取：

```text
100k accesses
chronological split: 80% train / 10% valid / 10% test
```

先跑这几个策略：

```text
LRU
LFU
CLOCK
QMAP-Pool
```

Random 可以先不跑，等正式实验再补。

pilot 输出建议：

```text
outputs/results/real_pilot/summary.md
outputs/checkpoints/real_pilot/<workload>/qmap_epoch_10.pth
```

严格依赖关系：

```text
pilot 通过后再跑 full-scale。
```

可以并行：

```text
不同 workload 的 pilot 可以并行；
同一 workload 内 QMAP-Pool 训练和 QMAP-Pool 评估串行；
baselines 的 replay 可以和 QMAP 训练并行，因为 baselines 不依赖 checkpoint。
```

### 阶段 5：正式真实数据实验

目标：把论文主表补完整。

正式实验策略：

```text
LRU
Random
LFU
CLOCK
QMAP-Pool
```

如果时间允许，再加：

```text
QMAP-Full 仅作为历史对照，可选，不作为主线。
```

正式 trace 规模建议：

```text
每个 workload 1M 到 5M accesses。
如果服务器时间紧，先用 1M。
如果 1M 结果稳定，再扩到 5M。
```

输出建议：

```text
outputs/results/real_workload_suite/summary.md
outputs/results/real_workload_suite/<workload>/*.json
outputs/checkpoints/real_workload_suite/<workload>/qmap_epoch_10.pth
```

主表要报告：

```text
hit rate
NVM writes
weighted access cost
migration count
avg decision time
```

严格依赖关系：

```text
真实 trace pilot 成功 -> 正式规模 trace -> 正式训练和评估 -> 汇总表格。
```

可以并行：

```text
多个 workload 的正式实验可以并行；
多个 baseline policy 可以并行；
多 seed 可以并行；
同一 QMAP-Pool workload 的 generate/train/eval 必须串行。
```

### 阶段 6：只做必要消融

目标：不要在真实数据上重复所有 synthetic 消融，只做最能支撑论文的部分。

真实数据上建议只做：

```text
QMAP-Pool
no_rw
no_cost
```

可选：

```text
no_pc
```

不再做：

```text
Q-Former K sweep
qformer_light / qformer_tiny
Encoder 2/3 层 sweep
大规模 cost weight grid
```

原因：

```text
老师已经决定不走 Q-Former；
真实数据实验的主要任务是证明 QMAP-Pool 在标准 workload 上仍然有效；
消融只需要说明 RW/cost-aware 是否有贡献。
```

严格依赖关系：

```text
先看正式真实 workload 主结果，再挑 1-2 个最有代表性的 workload 做消融。
```

可以并行：

```text
选定 workload 后，各 variant 可以并行训练和评估。
```

### 阶段 7：多 seed 验证

目标：增强可信度。

不需要所有实验都多 seed。建议只对最关键结果做：

```text
1. synthetic writeheavy: QMAP-Pool vs LFU/CLOCK
2. 真实数据中 QMAP-Pool 表现最好的 workload
3. 真实数据中 QMAP-Pool 表现最差或最接近 LFU 的 workload
```

建议 seed：

```text
3136859
42
2026
```

输出建议：

```text
outputs/results/seed_stability/summary.md
```

严格依赖关系：

```text
先知道哪些 workload 最关键，再做多 seed。
```

可以并行：

```text
不同 seed 可以并行；
不同 workload 可以并行。
```

## 推荐总执行顺序

最实际的顺序：

```text
Step 1. 已完成：冻结 QMAP-Pool 为最终模型，所有新实验统一 mean_pool。
Step 2. 已完成：在 WSL 搭建 PARSEC 环境，第一批固定为 blackscholes/canneal/streamcluster/dedup。
Step 3. 已完成：写/确认 trace 采集工具，输出 PC,Address,RW；dedup 不稳定时用 ferret 替换。
Step 4. 已完成前半：4 个 PARSEC 100k raw -> split -> 质量检查已通过；下一步进入 JSONL -> train -> eval。
Step 5. 已完成 trace 部分：4 个 PARSEC workload 的 100k pilot trace 已齐；下一步跑 100k pilot 训练评估。
Step 6. 选择 3-4 个有代表性的 workload，扩到 1M 或 5M 正式实验。
Step 7. 跑 LRU/Random/LFU/CLOCK/QMAP-Pool 主表。
Step 8. 选 1-2 个真实 workload 做 no_rw/no_cost 消融。
Step 9. 对关键结果做 3 seed 验证。
Step 10. 汇总论文表格和图。
```

## 并行执行建议

可以并行：

```text
1. 真实 benchmark 环境搭建 和 QMAP-Pool 脚本整理。
2. 多个 workload 的 trace 采集。
3. 多个 baseline replay。
4. 多个 workload 的 QMAP-Pool 训练。
5. 多 seed 实验。
```

不能并行、必须串行：

```text
1. raw trace -> split -> JSONL -> train -> QMAP eval。
2. pilot 实验 -> 正式规模实验。
3. 主结果分析 -> 选择真实数据消融 workload。
4. 确定最终模型口径 -> 写论文主表。
```

## 建议论文最终表格

```text
Table 1: Synthetic workloads 上 QMAP-Pool vs LRU/Random/LFU/CLOCK
Table 2: Real/PARSEC workloads 上 QMAP-Pool vs LRU/Random/LFU/CLOCK
Table 3: Parameter sensitivity
Table 4: Ablation on representative workloads
Table 5: Inference overhead
```

如果篇幅有限，保留：

```text
Table 1: Real workload main results
Table 2: Synthetic workload main results
Table 3: Ablation + overhead
```

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
outputs/checkpoints/qmap_encoder_depth_comparison_writeheavy/**/qmap_epoch_20.pth
```
