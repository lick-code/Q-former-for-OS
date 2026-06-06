# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

## 2026-06-04 方法更新

当前代码主线已经从旧的 `QMAP-Pool/mean_pool` 改为
`QMAP-CrossAttn/cross_attention`。新方法不再在 Transformer Encoder
之后做均值池化，也不再把均值池化后的全局向量和页面特征简单拼接。

```text
QMAP-CrossAttn =
  access feature embedding
  -> 1-layer Transformer Encoder 得到 X_enc
  -> candidate page features 作为 Q
  -> X_enc 作为 K/V 做 cross-attention
  -> attention context vector 送入 MLP 输出 eviction score
```

旧的 `QMAP-Pool = Transformer Encoder + mean pooling + candidate scorer`
只作为历史口径保留；Q-Former 相关实验也只作为前期探索记录保留，不再作为论文主线。
由于模型结构已经变化，旧结果目录中的 `QMAP-Pool/mean_pool` 指标不能直接作为
新方法结果引用；当前正式结果已经按 `QMAP-CrossAttn/cross_attention` 重新训练并 replay。

当前论文实验规模仍固定为：`1M real trace + pressure window + real ablation + seed stability`。暂不补 5M；如果后续老师要求更大规模，再重新采集真正的 5M trace 后补跑。当前 `outputs/results/real_workload_suite/5m/` 是 100k 回退结果，不能作为论文或文档中的 5M 实验结果。

## 当前状态

已经完成：

```text
1. synthetic trace 上的 QMAP 原型 pipeline：trace -> JSONL -> train -> replay -> summary。
2. LRU / Random / LFU / CLOCK / QMAP 的基础对比。
3. checkpoint sweep、参数敏感性、消融实验，以及真实数据上的 cost/capacity/candidate sensitivity。
4. Q-Former 与 mean pooling 的对照已经保留为历史记录。
5. 当前代码默认使用 1-layer Transformer Encoder + candidate-page cross-attention。
```

当前结论：

```text
1. QMAP 在 writeheavy synthetic workload 上表现最好，能降低 NVM writes 和 weighted access cost。
2. QMAP 不是所有 workload 都优于 LFU，尤其在 hotset、phasechange、pcrwstress 上 LFU 仍然很强。
3. 旧的 mean pooling 结论只作为历史对照；新论文主线应使用 QMAP-CrossAttn。
4. 真实实验主线仍是 1M 标准 split、streamcluster/dedup pressure window、真实消融和多 seed。
5. 当前正式结果已经重跑为 `QMAP-CrossAttn/cross_attention`；旧 `QMAP-Pool/mean_pool` 只作为历史对照。
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
| 阶段 0：实验口径冻结 | 已更新 | 新实验默认 `cross_attention`，表格统一 `QMAP-CrossAttn` |
| Q-Former 对照 | 已完成，仅作历史参考 | `outputs/results/qmap_qformer_comparison_writeheavy/summary.md` |
| Encoder 层数对照 | 已完成，仅作历史参考 | `outputs/results/qmap_encoder_depth_comparison_writeheavy/summary.md` |
| 真实/标准 workload | 4 个 PARSEC 100k 真实 trace 已完成 | `outputs/results/real_trace_stats/summary.md` |
| 真实 trace 100k pilot | 历史 pipeline 验证；不作为当前 CrossAttn 结论 | `outputs/results/real_pilot/summary.md` |
| 真实 trace 1M 主实验 | 阶段 5 的正式主结果；作为论文主表来源 | `outputs/results/real_workload_suite/1m/summary.md` |
| pressure window 实验 | 阶段 5 的压力窗口补充；streamcluster 是最强真实正结果，dedup 基本持平 | `outputs/results/real_workload_suite_pressure/selected/summary.md` |
| 真实数据消融 | 已完成；当前口径为 `QMAP-CrossAttn / no_rw / no_cost` | `outputs/results/real_ablation/summary.md` |
| 多 seed 稳定性 | 阶段 7 已完成；streamcluster 正结果稳定，blackscholes 混合，canneal 负例稳定 | `outputs/results/seed_stability/summary.md` |
| 5M 实验 | 暂缓；当前 5M 目录实际是 100k 回退结果，不进入论文 | `outputs/results/real_workload_suite/5m/` |
| cost-weight sensitivity | 已完成；replay counter 重新加权，不重新训练 | `outputs/results/cost_weight_sensitivity/summary.md` |
| capacity sensitivity | 已完成；覆盖 streamcluster pressure 和 canneal，DRAM cap=8/16/32 | `outputs/results/capacity_sensitivity/summary.md` |
| candidate-count sensitivity | 已完成；覆盖 streamcluster pressure 和 canneal，candidate count=4/8/16 | `outputs/results/candidate_sensitivity/summary.md` |
| canneal targeted tuning | 新增代码入口；用 valid split 选择 epoch / candidate count / rank score penalty，再评 test | `outputs/results/canneal_tuned_eval/summary.md` |

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
  model.py                      # Transformer、candidate-page cross-attention、候选页 scorer；Q-Former/mean_pool 保留为历史探索
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
  run_real_pilot.py                    # 真实/PARSEC trace 的 split -> JSONL -> train -> eval -> summary 统一入口
  run_canneal_tuned_eval.py            # canneal 专项优化：valid 调参后只评一次 test
  diagnose_qmap_replay.py              # 真实 trace replay 诊断和 dedup pressure window 扫描

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
QMAP-CrossAttn
  access sequence encoder: Transformer Encoder
  sequence aggregation: none，保留完整 X_enc
  eviction decision: page features query X_enc by cross-attention, then MLP scorer
```

不再继续做：

```text
Q-Former query 数 K sweep
Q-Former light/tiny 变体
Encoder 2/3 层 sweep
把 mean_pool 作为论文主线
把 Q-Former 作为论文主贡献点
```

保留原因：

```text
1. Q-Former 和 mean_pool 结果是历史探索记录，便于解释方法演进。
2. 当前论文方法已经改为页面特征查询完整 X_enc 的 cross-attention。
3. 新方法已经重新训练和 replay，不能沿用旧 QMAP-Pool 数字。
```

## 下一步实验规划

下面是推荐的执行顺序。重点是先收敛代码和模型命名，再采集真实数据，再跑正式实验。不要一开始就大规模跑，否则出错成本很高。

### 阶段 0：冻结实验口径

状态：已完成。

目标：把后续所有实验统一到 QMAP-CrossAttn。

已落实：

```text
1. qmap_generator.py / qmap_train.py 默认 ablation=cross_attention。
2. run_prototype_experiment.py、run_workload_suite.py、run_qmap_parameter_sensitivity.py 等新实验入口显式传入 cross_attention。
3. 后续 summary 和论文表格统一叫 QMAP-CrossAttn。
4. Q-Former comparison、Q-Former K sweep、Encoder 2/3 层 sweep 加保护开关，仅用于复现历史探索。
5. replay cost model 暂时不再改，继续使用当前 qmap_eval.py 的配置。
```

建议新增或确认一个主运行配置：

```text
history_length = 10
candidate_count = 8
lookahead = 256
dram_capacity = 16
epochs = 10
batch_size = 32
model = QMAP-CrossAttn
ablation = cross_attention
```

严格依赖关系：

```text
阶段 0 必须在所有真实数据正式实验之前完成。
否则后面结果会混入 Q-Former / mean_pool / cross_attention 多套口径，论文会很难写。
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
QMAP-CrossAttn synthetic 复跑脚本整理
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
  --ablation cross_attention
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

该质量检查已通过，可以进入阶段 4 的 100k pilot 训练评估。当前论文正式 PARSEC 规模固定为 1M；5M 作为后续可选扩展，不纳入当前实验主线。

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
必须 generate JSONL，才能 train QMAP-CrossAttn；
必须有 checkpoint，才能评估 QMAP-CrossAttn。
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

状态：已完成，可以进入阶段 5。

目标：确认真实数据 pipeline 能跑通，并找到能产生有效 eviction 压力的真实 trace 配置。

100k pilot 只作为 pipeline 和压力窗口选择依据，不作为当前论文结果表。当前论文结果以阶段 5 之后的
`QMAP-CrossAttn` 1M/pressure/ablation/seed summary 为准。

最终沿用到正式实验的配置口径：

```text
records = 100k
chronological split = 80% train / 10% valid / 10% test
history_length = 10
candidate_count = 8
dram_capacity = 16
lookahead = 256
epochs = 10
model = QMAP-CrossAttn
ablation = cross_attention
policies = LRU / Random / LFU / CLOCK / QMAP-CrossAttn
```

阶段 4 过程中排除的旧口径：

```text
dram_capacity = 64:
  可以验证 pipeline，但 test 段 migrations=0、decision_count=0，没有策略比较价值。

candidate_count = 64:
  在 dram_capacity=16 下候选集合过宽，QMAP 容易选择过新的 DRAM 页；
  replay diagnosis 显示 blackscholes 中大量选择 MRU-ish rank，导致迁移次数和 cost 明显上升。

candidate_count = 8 + rank feature:
  明显缓解 MRU 误驱逐问题，是阶段 5 应继续使用的配置。
```

历史 100k pilot 输出：

```text
run id: real_pilot_100k_dram16_c8_rankfix
workloads: parsec_blackscholes / parsec_canneal / parsec_streamcluster / parsec_dedup
result: outputs/results/real_pilot_dram16_c8_rankfix/summary.md
diagnosis: outputs/results/real_pilot_dram16_c8_rankfix/diagnosis.md
```

这些输出用于确认 `dram_capacity=16`、`candidate_count=8` 和 pressure window 的必要性。
旧 `QMAP-Pool/mean_pool` 数字不进入当前论文结论，当前 README 后续只报告新方法结果。

阶段 4 结论：

```text
1. 四个 PARSEC workload 都已跑过 100k pilot。
2. blackscholes / canneal / streamcluster 在 c8/rankfix 配置下都有有效 eviction。
3. dedup 默认 100k chronological split 的 test 段没有 eviction 压力，必须使用 pressure window 或更大 trace。
4. pilot 的主要作用是筛出有效 eviction 压力和稳定的实验配置，不作为最终方法收益。
5. 阶段 5 沿用 `dram_capacity=16, candidate_count=8, lookahead=256`，但模型口径改为 `QMAP-CrossAttn`。
```

严格依赖关系：

```text
阶段 5 必须基于阶段 4 收敛出的系统配置：
dram_capacity=16, candidate_count=8, lookahead=256, QMAP-CrossAttn cross_attention。
```

可以并行：

```text
不同 workload 的 1M trace 采集可以并行；如后续补 5M，也按 workload 并行采集；
不同 workload 的 QMAP-CrossAttn 训练可以并行；
baselines replay 可以和 QMAP-CrossAttn 训练并行。
```

### 阶段 5：正式真实数据实验

状态：1M 主实验已完成；5M 暂缓。

目标：把论文主表固定在 1M 真实 trace 和 pressure window 上，形成一套可信、可解释、可复现的实验结果。当前不再把 5M 作为必需项；如果后续老师要求，再重新采集真正的 5M trace 后补跑。

阶段 5 固定口径：

```text
history_length = 10
candidate_count = 8
dram_capacity = 16
lookahead = 256
epochs = 10
batch_size = 32
model = QMAP-CrossAttn
ablation = cross_attention
policies = LRU / Random / LFU / CLOCK / QMAP-CrossAttn
```

当前阶段 5 口径决策：

```text
正式主表使用 QMAP-CrossAttn c8，rank_guard disabled。
历史 QMAP-Pool-Guard / rank_guard=2 只作为诊断记录，不作为当前论文主口径。
```

原因：

```text
当前新方法主结果已经关闭 Guard：`rank_guard=0`。
历史 Guard 结果来自旧 mean-pool 口径，不能和当前 CrossAttn 主结果混写。
canneal 的负结果由当前 candidate-count sensitivity 解释：candidate_count 越大，误驱逐和迁移放大越明显。
```

正式 trace 规模决策：

```text
论文当前固定使用：
  1M standard split
  pressure window
  real ablation
  seed stability

暂不使用：
  5M

原因：
  当前 1M + pressure window 已经能形成完整实验闭环；
  5M 目录中的现有结果实际只有 100k 规模，不能进入论文；
  后续如需补 5M，必须重新采集真正 5M trace，并确认 trace_stats 中 records=5000000。
```

阶段 5 workload 安排：

```text
必须跑：
  parsec_blackscholes
  parsec_canneal
  parsec_streamcluster
  parsec_dedup pressure window

dedup 注意：
  默认 chronological split 在 100k 下 test 段没有 eviction；
  1M 或后续 5M 扩展时也必须先检查 test 段 decision_count；
  如果 decision_count 仍然太低，就用 pressure-aware window，避免把无压力结果写进主表。
```

当前 1M 主结果状态：

```text
结果目录：
  outputs/results/real_workload_suite/1m/
  outputs/results/real_workload_suite_pressure/selected/
  outputs/results/real_workload_suite_guard/  # 历史诊断，不进入当前主结论

可进主表：
  parsec_blackscholes 1M standard, QMAP-CrossAttn c8:
    best baseline = LFU, cost = 106952
    QMAP-CrossAttn cost = 105983, delta = -0.91%
    NVM writes = 32, migrations = 525
    结论：单 seed 下小幅优于 best baseline，但 seed stability 显示该结论会翻转。

  parsec_streamcluster pressure window, QMAP-CrossAttn c8:
    best baseline = CLOCK, cost = 301767
    QMAP-CrossAttn cost = 269095, delta = -10.83%
    NVM writes = 548, migrations = 5981
    结论：最强真实 workload 正结果。

  需要诊断或降级：
  parsec_canneal 1M standard, QMAP-CrossAttn c8:
    best baseline = LRU, cost = 126178
    QMAP-CrossAttn cost = 150263, delta = +19.09%
    迁移次数 4545 vs LRU 2350。
    结论：负结果/诊断案例，不强行改统一口径。

  parsec_dedup pressure window:
    QMAP-CrossAttn 与 LRU 持平，cost = 201567，decision_count = 87。
    结论：弱压力 trace，只能说明不差，不能证明优势。

不能用作策略比较：
  parsec_streamcluster standard split:
    test 段 decision_count=0。
    已用 pressure window 结果替代。

  outputs/results/real_workload_suite/5m/:
    当前仍是旧的 100k 回退结果，不是正式 5M；
    不进入论文主表、附表或实验结论。
```

canneal 诊断结论：

```text
outputs/results/candidate_sensitivity/summary.md

candidate_count=4:  QMAP-CrossAttn vs LRU = +6.87%
candidate_count=8:  QMAP-CrossAttn vs LRU = +19.09%
candidate_count=16: QMAP-CrossAttn vs LRU = +134.56%

这说明 canneal 失败不是单个 checkpoint 偶然，而是候选集合扩大后误驱逐和迁移被放大。
当前统一主口径仍保持 c8，用 canneal 作为方法边界和失败诊断案例。
如果目标是把 canneal 单独调到接近持平或反超，不再使用统一 c8 口径，而是使用
`scripts/run_canneal_tuned_eval.py`：它先在 valid split 上选择
`epoch / candidate_count / rank_score_penalty`，再只对选中的配置评一次 test。
```

canneal 专项优化命令：

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/run_canneal_tuned_eval.py \
  --device cuda \
  --checkpoint_dir outputs/checkpoints/real_workload_suite/1m/parsec_canneal \
  --valid_trace dataset/processed/real_workload_suite/1m/parsec_canneal_valid.csv \
  --test_trace dataset/processed/real_workload_suite/1m/parsec_canneal_test.csv \
  --output_dir outputs/results/canneal_tuned_eval
```

默认搜索空间：

```text
epochs = 1,2,3,4,5,6,7,8,9,10
candidate_counts = 1,2,4,8
rank_score_penalties = 0,0.25,0.5,1.0,2.0
selection = lowest validation weighted_access_cost
```

1M 主实验命令模板：

```bash
python scripts/run_real_pilot.py \
  --device cuda \
  --limit 1000000 \
  --raw_pattern "{workload}_1m.csv" \
  --dram_capacity 16 \
  --candidate_count 8 \
  --lookahead 256 \
  --epochs 10 \
  --run_id real_workload_1m_c8_rankfix \
  --result_dir outputs/results/real_workload_1m_c8_rankfix \
  --checkpoint_dir outputs/checkpoints/real_workload_1m_c8_rankfix \
  --jsonl_dir dataset/jsonl/real_workload_1m_c8_rankfix \
  --normalized_raw_dir dataset/raw_traces/real_workload_1m_c8_rankfix
```

dedup pressure 1M 建议单独跑，避免覆盖默认 dedup 输出：

```bash
python scripts/run_real_pilot.py \
  --workloads parsec_dedup \
  --device cuda \
  --limit 1000000 \
  --raw_pattern "parsec_dedup_1m.csv" \
  --dram_capacity 16 \
  --candidate_count 8 \
  --lookahead 256 \
  --epochs 10 \
  --run_id real_dedup_pressure_1m_c8_rankfix \
  --normalized_raw_dir dataset/raw_traces/real_dedup_pressure_1m_c8_rankfix \
  --processed_dir dataset/processed/real_dedup_pressure_1m_c8_rankfix \
  --jsonl_dir dataset/jsonl/real_dedup_pressure_1m_c8_rankfix \
  --result_dir outputs/results/real_dedup_pressure_1m_c8_rankfix \
  --checkpoint_dir outputs/checkpoints/real_dedup_pressure_1m_c8_rankfix
```

每轮正式实验后必须检查：

```text
1. summary.md 中每个 workload 的 Migrations / Decision ms / QMAP-CrossAttn vs best baseline。
2. diagnosis.md 中 QMAP 是否再次大量选择过新的候选页。
3. dedup 的 decision_count 是否足够；如果接近 0，该结果只能说明 workload 太容易，不能比较策略。
4. QMAP-CrossAttn 的 avg decision time；当前 QMAP 是毫秒级，baseline 是微秒级，论文里要作为 overhead 报告。
```

当前论文采用的阶段 5 输出：

```text
outputs/results/real_workload_suite/1m/summary.md
outputs/results/real_workload_suite/1m/<workload>/*.json
outputs/checkpoints/real_workload_suite/1m/<workload>/qmap_epoch_10.pth

outputs/results/real_workload_suite_pressure/selected/summary.md
outputs/results/real_workload_suite_pressure/selected/<workload>/*.json
```

主表要报告：

```text
hit rate
NVM writes
weighted access cost
migration count
avg decision time
QMAP-CrossAttn vs best baseline cost delta
```

严格依赖关系：

```text
1M trace 采集和质量检查 -> 1M 主实验 -> pressure window 诊断和补充 -> 消融 -> 多 seed -> 写实验部分。
```

可以并行：

```text
多个 workload 的正式实验可以并行；
多个 baseline policy 可以并行；
多 seed 可以并行；
同一 QMAP-CrossAttn workload 的 generate/train/eval 必须串行。
```

### 阶段 6：只做必要消融

目标：不要在真实数据上重复所有 synthetic 消融，只做最能支撑论文的部分。

真实数据上建议只做：

```text
QMAP-CrossAttn
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
真实数据实验的主要任务是验证 QMAP-CrossAttn 在真实 workload 上的收益边界；
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
1. synthetic writeheavy: QMAP-CrossAttn vs LFU/CLOCK
2. 真实数据中 QMAP-CrossAttn 表现最好的 workload
3. 真实数据中 QMAP-CrossAttn 表现最差或最接近 LFU 的 workload
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
Step 1. 已完成：最终模型更新为 QMAP-CrossAttn，所有新实验统一 cross_attention。
Step 2. 已完成：在 WSL 搭建 PARSEC 环境，第一批固定为 blackscholes/canneal/streamcluster/dedup。
Step 3. 已完成：写/确认 trace 采集工具，输出 PC,Address,RW；dedup 不稳定时用 ferret 替换。
Step 4. 已完成：4 个 PARSEC 100k raw -> split -> 质量检查已通过。
Step 5. 已完成：阶段 4 100k pilot 已收敛到 `dram_capacity=16, candidate_count=8, lookahead=256`；pilot 只用于配置选择，最终指标看 CrossAttn 复跑结果。
Step 6. 已完成：真实 1M trace 已采集，1M standard split 主实验已跑完。
Step 7. 已完成：streamcluster pressure window 已补，QMAP-CrossAttn c8 有 -10.83% cost 改善。
Step 8. 已完成：canneal candidate-count sensitivity 已补，确认候选集合扩大后负结果明显放大；rank_guard=2 不作为统一主口径。
Step 9. 已完成：1M 主表已固化，streamcluster pressure 作为稳定正结果，blackscholes 作为弱正/混合案例，canneal 作为负例诊断，dedup 标注 low-pressure tie。
Step 10. 已完成：真实数据必要消融已完成，覆盖 streamcluster pressure 和 blackscholes。
Step 11. 已完成：多 seed 验证已完成，覆盖 streamcluster pressure、blackscholes 和 canneal 负例。
Step 12. 暂缓：正式 5M。当前论文不补 5M；如后续老师要求，必须重新采集真实 5M 并确认 records=5000000。
Step 13. 已完成：三项附录级敏感性实验已补完：cost-weight、capacity、candidate-count。
Step 14. 当前下一步：开始写论文实验部分，按“1M 主实验 -> pressure window -> 消融 -> 多 seed -> overhead/局限性 -> 附录敏感性”的顺序组织。
```

## 并行执行建议

可以并行：

```text
1. 真实 benchmark 环境搭建 和 QMAP-CrossAttn 脚本整理。
2. 多个 workload 的 trace 采集。
3. 多个 baseline replay。
4. 多个 workload 的 QMAP-CrossAttn 训练。
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

当前论文实验规模固定为 `1M + pressure window + ablation + seed stability`。表格优先服务论文主线：QMAP-CrossAttn 不是所有 workload 的无条件最优策略，但在 streamcluster pressure 这类有持续迁移压力的真实 workload 上能稳定降低 weighted access cost；blackscholes 是弱正/混合案例，canneal 是稳定负例并暴露出候选集合敏感性。

推荐进入论文正文的表格：

| 表格 | 内容 | 数据来源 | 用途 |
|---|---|---|---|
| Table 1 | 1M 真实 trace 统计 | `outputs/results/real_workload_suite/1m/trace_stats/summary.md` | 说明数据规模、unique pages、write ratio、reuse ratio |
| Table 2 | 1M 标准 split 主实验：LRU / Random / LFU / CLOCK / QMAP-CrossAttn | `outputs/results/real_workload_suite/1m/summary.md` | 论文主表，展示 blackscholes 单 seed 小幅正、canneal 负例、dedup 持平、streamcluster standard split 低压力问题 |
| Table 3 | pressure window 主实验 | `outputs/results/real_workload_suite_pressure/selected/summary.md` | 作为真实 workload 最强正结果，重点报告 streamcluster pressure 的 `-10.83%` cost delta |
| Table 4 | 真实数据消融：QMAP-CrossAttn / no_rw / no_cost | `outputs/results/real_ablation/summary.md` | 解释 read/write 特征和 cost-aware 训练的贡献边界 |
| Table 5 | 多 seed 稳定性 | `outputs/results/seed_stability/summary.md` | 证明 streamcluster pressure 正结果稳定，blackscholes 会随 seed 翻转，canneal 负例稳定 |

推荐进入文档或附录的表格：

| 表格 | 内容 | 数据来源 | 用途 |
|---|---|---|---|
| Appendix A | 100k pilot | `outputs/results/real_pilot/summary.md` | 说明如何从 100k pilot 收敛到 `dram_capacity=16, candidate_count=8` |
| Appendix B | synthetic workload 原型对比 | `outputs/results/workload_suite/summary.md` 和 `outputs/results/workload_suite_pcrwstress/summary.md` | 作为方法原型有效性的补充，不作为最终真实结论 |
| Appendix C | checkpoint sweep | `outputs/results/checkpoint_sweep/summary.md` | 说明 epoch 10 的选择依据 |
| Appendix D | 参数敏感性 | `outputs/results/qmap_parameter_sensitivity/summary.md` | 说明 history/candidate/DRAM/lookahead 的影响 |
| Appendix E | canneal 诊断或 Guard 对照 | `outputs/results/real_workload_suite_guard/` | 解释 canneal 失败原因和 rank_guard 为什么不进入统一主口径 |
| Appendix F | cost-weight sensitivity | `outputs/results/cost_weight_sensitivity/summary.md` | 回应 cost model 权重是否影响结论 |
| Appendix G | capacity sensitivity | `outputs/results/capacity_sensitivity/summary.md` | 回应 `dram_capacity=16` 是否过于特殊 |
| Appendix H | candidate-count sensitivity | `outputs/results/candidate_sensitivity/summary.md` | 支撑 canneal 失败和候选 rank/candidate count 有关 |

不建议进入论文的表格：

| 内容 | 原因 |
|---|---|
| `outputs/results/real_workload_suite/5m/` | 当前实际是 100k 回退结果，不是 5M，不能引用 |
| Q-Former K sweep / Q-Former light/tiny | 已不是论文主线，只保留为历史探索 |
| Encoder 2/3 层 sweep | 已用于内部定型，不需要占正文篇幅 |
| 旧的 `QMAP-Full` / `QMAP-Pool` 命名表 | 容易和当前 `QMAP-CrossAttn` 主线混淆 |

正文实验部分推荐结构：

```text
1. Experimental Setup
   - Hybrid DRAM/NVM replay model
   - Baselines: LRU, Random, LFU, CLOCK
   - Metrics: hit rate, NVM writes, weighted access cost, migrations, decision overhead
   - Dataset: PARSEC 1M traces and pressure windows

2. Main Results on 1M Real Traces
   - 先报告完整 1M 标准 split
   - 明确说明 streamcluster standard split 几乎无 eviction，因此不能作为有效压力比较
   - blackscholes 是单 seed 小幅正、多 seed 混合结果
   - canneal 是稳定负例

3. Pressure Window Results
   - 重点报告 streamcluster pressure window
   - QMAP-CrossAttn 相比最佳 baseline 降低 weighted access cost 10.83%
   - dedup pressure window 与 LRU 持平，作为边界案例

4. Ablation Study
   - streamcluster pressure 上 no_rw 略优于完整模型，no_cost 基本持平
   - blackscholes 上消融变体更优，说明该 workload 不适合作为机制收益主证据

5. Seed Stability and Overhead
   - 三个 seed 下 streamcluster pressure 都稳定优于 best baseline
   - blackscholes 的 seed 结果会翻转，只作为弱正/混合案例
   - canneal 三个 seed 都稳定失败
   - QMAP-CrossAttn 推理开销明显高于传统策略，需要作为代价讨论

6. Appendix Sensitivity
   - cost-weight sensitivity: 正负结论不依赖单一 cost 权重
   - capacity sensitivity: streamcluster pressure 在 cap=8/16 有稳定收益，cap=32 接近持平
   - candidate-count sensitivity: streamcluster pressure 在 c4/c8/c16 均获益，canneal 随 candidate_count 增大明显恶化
```

## 已完成三项敏感性实验

下面三项用于增强论文防御性，不改变当前主实验结论。结果已经齐全，推荐全部放附录，正文只各用一句话概括。

### 1. Cost-weight sensitivity

状态：已完成。

目的：回应 weighted access cost 中 `NVM write=8`、`migration=10` 是否过于主观。该实验不重新训练，直接用已有 replay JSON 计数重新计算 cost。

推荐 workload：

```text
streamcluster_pressure  稳定正例，使用 pressure window
blackscholes            弱正/混合案例，使用 1M standard split
canneal                 负例，使用 1M standard split
```

推荐 cost model：

| Cost model | DRAM read/write | NVM read | NVM write | Migration |
|---|---:|---:|---:|---:|
| default | 1 | 2 | 8 | 10 |
| mild | 1 | 2 | 4 | 5 |
| write-heavy | 1 | 2 | 16 | 10 |
| migration-heavy | 1 | 2 | 8 | 20 |

最小实现方式：

```text
读取已有 JSON：
  outputs/results/real_workload_suite_pressure/selected/parsec_streamcluster/*.json
  outputs/results/real_workload_suite/1m/parsec_blackscholes/*.json
  outputs/results/real_workload_suite/1m/parsec_canneal/*.json

对每个 policy 重新计算：
  reweighted_cost = hits * 1
                  + nvm_reads * nvm_read_cost
                  + nvm_writes * nvm_write_cost
                  + migrations * migration_cost

每个 workload / cost model 下：
  best_baseline_cost = min(LRU, Random, LFU, CLOCK)
  delta = (QMAP_cost - best_baseline_cost) / best_baseline_cost
```

复现时如果想重新 replay，而不是手工重算，也可以直接调用 `qmap/qmap_eval.py`。示例：

```bash
python qmap/qmap_eval.py \
  --trace_path dataset/processed/real_workload_suite_pressure/selected/parsec_streamcluster_test.csv \
  --policy qmap \
  --checkpoint outputs/checkpoints/real_workload_suite_pressure/selected/parsec_streamcluster/qmap_epoch_10.pth \
  --dram_capacity 16 \
  --history_length 10 \
  --candidate_count 8 \
  --lookahead 256 \
  --page_shift 12 \
  --device cuda \
  --nvm_read_cost 2 \
  --nvm_write_cost 16 \
  --migration_cost 10 \
  --json_output outputs/results/cost_weight_sensitivity/write_heavy/streamcluster_pressure/qmap.json
```

结果汇总：

| Cost model | streamcluster-p delta | blackscholes delta | canneal delta |
|---|---:|---:|---:|
| default | -10.83% | +3.37% | +2.45% |
| mild | -6.98% | +2.03% | +1.48% |
| write-heavy | -10.73% | +2.54% | +2.44% |
| migration-heavy | -15.91% | +6.65% | +3.94% |

输出：

```text
outputs/results/cost_weight_sensitivity/summary.md
outputs/results/cost_weight_sensitivity/summary.csv
```

结论：

```text
streamcluster_pressure 在所有 cost model 下都优于 best baseline。
blackscholes 在该重算表中所有 cost model 下都差于 best baseline，说明它只能作为弱正/混合案例。
canneal 在所有 cost model 下都差于 best baseline。
因此，最强正例 streamcluster_pressure 和负例 canneal 都不依赖单一 cost 权重选择。
```

### 2. Capacity sensitivity

状态：已完成。

目的：回应 `dram_capacity=16` pages 是否过小、结论是否只在单一容量下成立。该实验建议完整重新生成 JSONL、训练、评估，因为 `dram_capacity` 会影响候选样本生成和 replay 压力。

固定配置：

```text
history_length = 10
candidate_count = 8
lookahead = 256
epochs = 10
batch_size = 32
model = QMAP-CrossAttn
ablation = cross_attention
policies = LRU / Random / LFU / CLOCK / QMAP-CrossAttn
```

变量：

```text
workloads:
  parsec_streamcluster pressure window
  parsec_canneal 1M standard split

dram_capacity:
  8
  16
  32
```

streamcluster pressure window 命令模板：

```bash
for cap in 8 16 32; do
  python scripts/run_real_pilot.py \
    --skip_prepare \
    --workloads parsec_streamcluster \
    --policies lru,random,lfu,clock,qmap \
    --processed_dir dataset/processed/real_workload_suite_pressure/selected \
    --manifest dataset/metadata/real_workload_suite_pressure_manifest.json \
    --jsonl_dir dataset/jsonl/capacity_sensitivity/streamcluster_pressure/cap${cap} \
    --result_dir outputs/results/capacity_sensitivity/streamcluster_pressure/cap${cap} \
    --checkpoint_dir outputs/checkpoints/capacity_sensitivity/streamcluster_pressure/cap${cap} \
    --history_length 10 \
    --candidate_count 8 \
    --dram_capacity ${cap} \
    --lookahead 256 \
    --epochs 10 \
    --batch_size 32 \
    --run_id capacity_streamcluster_pressure_cap${cap} \
    --device cuda
done
```

canneal 命令模板：

```bash
for cap in 8 16 32; do
  python scripts/run_real_pilot.py \
    --skip_prepare \
    --workloads parsec_canneal \
    --policies lru,random,lfu,clock,qmap \
    --processed_dir dataset/processed/real_workload_suite/1m \
    --manifest dataset/metadata/real_workload_suite_1m_manifest.json \
    --jsonl_dir dataset/jsonl/capacity_sensitivity/canneal/cap${cap} \
    --result_dir outputs/results/capacity_sensitivity/canneal/cap${cap} \
    --checkpoint_dir outputs/checkpoints/capacity_sensitivity/canneal/cap${cap} \
    --history_length 10 \
    --candidate_count 8 \
    --dram_capacity ${cap} \
    --lookahead 256 \
    --epochs 10 \
    --batch_size 32 \
    --run_id capacity_canneal_cap${cap} \
    --device cuda
done
```

结果汇总：

| Workload | DRAM cap | best baseline cost | QMAP cost | delta | QMAP migrations | decision count |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster-p | 8 | 369999 | 332660 | -10.09% | 11738 | 11738 |
| streamcluster-p | 16 | 301767 | 269095 | -10.83% | 5981 | 5981 |
| streamcluster-p | 32 | 216577 | 217348 | +0.36% | 1566 | 1566 |
| canneal | 8 | 190696 | 352852 | +85.03% | 22334 | 22334 |
| canneal | 16 | 126178 | 150263 | +19.09% | 4545 | 4545 |
| canneal | 32 | 101502 | 101298 | -0.20% | 114 | 114 |

输出：

```text
outputs/results/capacity_sensitivity/summary.md
outputs/results/capacity_sensitivity/summary.csv
```

注意：本地结果 JSON、summary 和 checkpoint 已齐全。JSONL 中间训练文件如果没有同步到本地，不影响论文表格；需要复现时可以由上面的命令重新生成。

结论：

```text
streamcluster_pressure 在 cap=8 和 cap=16 下稳定优于 best baseline；
cap=32 时 replacement pressure 明显降低，QMAP 与 best baseline 基本持平。
canneal 在 cap=8 和 cap=16 下明显失败，cap=32 时压力较弱并接近持平。
这说明 `dram_capacity=16` 不是孤立选择；QMAP-CrossAttn 的收益主要出现在有足够 replacement pressure 且访问模式适合学习的负载上。
```

### 3. Candidate-count sensitivity

状态：已完成。

目的：补足 canneal 失败机制的证据。已有 `outputs/results/real_workload_suite/1m/canneal_epoch_candidate_sweep/summary.md` 能证明 canneal 与 candidate/rank 有关，但它更像诊断 sweep。建议补一个统一口径的小型 sensitivity：同一训练流程、同一 workload、同一 dram_capacity，只改变 candidate count。

固定配置：

```text
history_length = 10
dram_capacity = 16
lookahead = 256
epochs = 10
batch_size = 32
model = QMAP-CrossAttn
ablation = cross_attention
policies = LRU / Random / LFU / CLOCK / QMAP-CrossAttn
```

变量：

```text
workloads:
  parsec_streamcluster pressure window
  parsec_canneal 1M standard split

candidate_count:
  4
  8
  16
```

streamcluster pressure window 命令模板：

```bash
for cand in 4 8 16; do
  python scripts/run_real_pilot.py \
    --skip_prepare \
    --workloads parsec_streamcluster \
    --policies lru,random,lfu,clock,qmap \
    --processed_dir dataset/processed/real_workload_suite_pressure/selected \
    --manifest dataset/metadata/real_workload_suite_pressure_manifest.json \
    --jsonl_dir dataset/jsonl/candidate_sensitivity/streamcluster_pressure/c${cand} \
    --result_dir outputs/results/candidate_sensitivity/streamcluster_pressure/c${cand} \
    --checkpoint_dir outputs/checkpoints/candidate_sensitivity/streamcluster_pressure/c${cand} \
    --history_length 10 \
    --candidate_count ${cand} \
    --dram_capacity 16 \
    --lookahead 256 \
    --epochs 10 \
    --batch_size 32 \
    --run_id candidate_streamcluster_pressure_c${cand} \
    --device cuda
done
```

canneal 命令模板：

```bash
for cand in 4 8 16; do
  python scripts/run_real_pilot.py \
    --skip_prepare \
    --workloads parsec_canneal \
    --policies lru,random,lfu,clock,qmap \
    --processed_dir dataset/processed/real_workload_suite/1m \
    --manifest dataset/metadata/real_workload_suite_1m_manifest.json \
    --jsonl_dir dataset/jsonl/candidate_sensitivity/canneal/c${cand} \
    --result_dir outputs/results/candidate_sensitivity/canneal/c${cand} \
    --checkpoint_dir outputs/checkpoints/candidate_sensitivity/canneal/c${cand} \
    --history_length 10 \
    --candidate_count ${cand} \
    --dram_capacity 16 \
    --lookahead 256 \
    --epochs 10 \
    --batch_size 32 \
    --run_id candidate_canneal_c${cand} \
    --device cuda
done
```

结果汇总：

| Workload | Candidate count | best baseline cost | QMAP cost | delta | QMAP migrations | decision count |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster-p | 4 | 301767 | 284587 | -5.69% | 7367 | 7367 |
| streamcluster-p | 8 | 301767 | 269095 | -10.83% | 5981 | 5981 |
| streamcluster-p | 16 | 301767 | 286669 | -5.00% | 7673 | 7673 |
| canneal | 4 | 126178 | 134851 | +6.87% | 3139 | 3139 |
| canneal | 8 | 126178 | 150263 | +19.09% | 4545 | 4545 |
| canneal | 16 | 126178 | 295968 | +134.56% | 17636 | 17636 |

输出：

```text
outputs/results/candidate_sensitivity/summary.md
outputs/results/candidate_sensitivity/summary.csv
```

注意：本地结果 JSON、summary 和 checkpoint 已齐全。JSONL 中间训练文件如果没有同步到本地，不影响论文表格；需要复现时可以由上面的命令重新生成。

结论：

```text
streamcluster_pressure 在 c4/c8/c16 下都优于 best baseline，c8 最好。
canneal 在 c4/c8/c16 下都差于 best baseline，并且 candidate_count 越大越差。
这直接支撑 canneal 失败来自 candidate/rank sensitivity，而不是单个训练 seed 或单个 candidate 设置的偶然。
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

### 按新方法重跑正式实验

先确认服务器 Python 环境能导入 PyTorch：

```bash
python -c "import torch; print(torch.__version__)"
python -m unittest tests.test_qmap_cross_attention
python qmap/qmap_integration_test.py
```

当前主线脚本已经默认使用：

```text
model = QMAP-CrossAttn
ablation = cross_attention
```

如果服务器上已经有 `dataset/processed/real_workload_suite/1m/` 下的 1M
切分数据，可以直接跳过 prepare，重新生成 JSONL、重新训练、重新 replay：

```bash
tmux new -s qmap_xattn_1m
CUDA_VISIBLE_DEVICES=0 python scripts/run_real_workload_suite.py \
  --accesses 1000000 \
  --skip_prepare \
  --device cuda
```

如果只想针对 canneal 重新做“接近持平/反超”的专项优化，先复用上面 1M
主实验已经训练出的 canneal checkpoints，然后单独跑 valid-tuned eval：

```bash
tmux new -s qmap_canneal_tune
CUDA_VISIBLE_DEVICES=0 python scripts/run_canneal_tuned_eval.py \
  --device cuda \
  --checkpoint_dir outputs/checkpoints/real_workload_suite/1m/parsec_canneal \
  --valid_trace dataset/processed/real_workload_suite/1m/parsec_canneal_valid.csv \
  --test_trace dataset/processed/real_workload_suite/1m/parsec_canneal_test.csv \
  --output_dir outputs/results/canneal_tuned_eval
```

输出看这里：

```text
outputs/results/canneal_tuned_eval/summary.md
outputs/results/canneal_tuned_eval/summary.csv
outputs/results/canneal_tuned_eval/selected_config.json
```

pressure window 主实验建议单独跑：

```bash
tmux new -s qmap_xattn_pressure
CUDA_VISIBLE_DEVICES=0 python scripts/run_real_pilot.py \
  --skip_prepare \
  --workloads parsec_streamcluster,parsec_dedup \
  --policies lru,random,lfu,clock,qmap \
  --processed_dir dataset/processed/real_workload_suite_pressure/selected \
  --manifest dataset/metadata/real_workload_suite_pressure_manifest.json \
  --jsonl_dir dataset/jsonl/real_workload_suite_pressure/selected \
  --result_dir outputs/results/real_workload_suite_pressure/selected \
  --checkpoint_dir outputs/checkpoints/real_workload_suite_pressure/selected \
  --history_length 10 \
  --candidate_count 8 \
  --dram_capacity 16 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda \
  --run_id real_pressure_selected_cross_attention
```

消融、seed 稳定性和敏感性实验在主结果跑完后执行：

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/run_real_ablation.py --force_generate
CUDA_VISIBLE_DEVICES=0 python scripts/run_real_ablation.py --skip_generate --run_torch --summarize --device cuda

CUDA_VISIBLE_DEVICES=0 python scripts/run_seed_stability.py --skip_generate --run_torch --summarize --device cuda

CUDA_VISIBLE_DEVICES=0 python scripts/run_capacity_sensitivity.py --run --summarize --device cuda
CUDA_VISIBLE_DEVICES=0 python scripts/run_candidate_sensitivity.py --run --summarize --device cuda
python scripts/run_cost_weight_sensitivity.py
```

上面的命令会把默认结果目录更新为 `QMAP-CrossAttn/cross_attention` 结果。
如果不想覆盖旧 `QMAP-Pool/mean_pool` 结果，先备份 `outputs/results/`、
`outputs/checkpoints/` 和需要保留的 `dataset/jsonl/` 子目录。

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

## Stage 6: Real-workload ablation conclusion

Stage 6 answers: why QMAP works, and which feature/loss terms contribute.

Scope:

- `parsec_streamcluster` pressure window: main positive real workload case.
- `parsec_blackscholes` standard 1M split: weak/mixed boundary case.
- Variants: `QMAP-CrossAttn`, `no_rw`, `no_cost`.
- Configuration: `history_length=10`, `candidate_count=8`, `lookahead=256`, `dram_capacity=16`, `epochs=10`, `batch_size=32`, `seed=3136859`.

Result table:

| workload | variant | cost | vs QMAP-CrossAttn | NVM writes | migrations |
|---|---|---:|---:|---:|---:|
| streamcluster_pressure | QMAP-CrossAttn | 269095.00 | +0.00% | 548 | 5981 |
| streamcluster_pressure | no_rw | 267644.00 | -0.54% | 550 | 5848 |
| streamcluster_pressure | no_cost | 269174.00 | +0.03% | 563 | 5980 |
| blackscholes | QMAP-CrossAttn | 110557.00 | +0.00% | 116 | 895 |
| blackscholes | no_rw | 106302.00 | -3.85% | 32 | 554 |
| blackscholes | no_cost | 105752.00 | -4.35% | 32 | 504 |

Interpretation:

- On `streamcluster_pressure`, `no_cost` is nearly tied with the full model (`+0.03%`), while `no_rw` is slightly better (`-0.54%`). This means the current real ablation does not support a strong claim that every feature/loss term independently improves this workload.
- On `blackscholes`, both ablations are better than the full model in this rerun. Because blackscholes is already weak/mixed in seed stability, it should not be used as the main mechanism-evidence workload.
- The safer paper claim is that QMAP-CrossAttn has a stable positive real workload in `streamcluster_pressure`, while feature/loss ablations show small and workload-dependent effects rather than universal gains.

Artifacts:

- `outputs/results/real_ablation/summary.md`
- `outputs/results/real_ablation/summary.csv`
- `outputs/results/real_ablation/*/*/qmap.json`
- `outputs/checkpoints/real_ablation/*/*/qmap_epoch_10.pth`
- `dataset/jsonl/real_ablation/*/*/*.jsonl`
- Runner: `scripts/run_real_ablation.py`

## Stage 7: Seed stability conclusion

Stage 7 answers: is the QMAP-CrossAttn result just an accidental training-seed outcome?

Scope:

- `streamcluster_pressure`: strongest positive real workload case.
- `blackscholes`: standard 1M split weak/mixed case.
- `canneal`: negative / robustness-boundary case.
- Seeds: `3136859`, `42`, `2026`.
- Baselines are reused from the existing deterministic or fixed-random-seed runs. Only QMAP-CrossAttn is retrained for each seed.

Per-seed results:

| workload | seed | QMAP cost | best baseline cost | delta | migrations | writes |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 3136859 | 269095.00 | 301767.00 | -10.83% | 5981 | 548 |
| streamcluster_pressure | 42 | 266439.00 | 301767.00 | -11.71% | 5715 | 593 |
| streamcluster_pressure | 2026 | 269501.00 | 301767.00 | -10.69% | 5995 | 590 |
| blackscholes | 3136859 | 105983.00 | 106952.00 | -0.91% | 525 | 32 |
| blackscholes | 42 | 109794.00 | 106952.00 | +2.66% | 878 | 20 |
| blackscholes | 2026 | 105862.00 | 106952.00 | -1.02% | 514 | 32 |
| canneal | 3136859 | 150263.00 | 126178.00 | +19.09% | 4545 | 42 |
| canneal | 42 | 144827.00 | 126178.00 | +14.78% | 4041 | 60 |
| canneal | 2026 | 147081.00 | 126178.00 | +16.57% | 4253 | 47 |

Stability summary:

| workload | mean delta | std delta | min/max delta | conclusion |
|---|---:|---:|---:|---|
| streamcluster_pressure | -11.08% | 0.45% | -11.71% / -10.69% | Stable positive. All seeds beat the best baseline. |
| blackscholes | +0.24% | 1.71% | -1.02% / +2.66% | Mixed. Seed can flip the conclusion. |
| canneal | +16.81% | 1.77% | +14.78% / +19.09% | Stable negative boundary. All seeds are worse than the best baseline. |

Interpretation:

- The strong `streamcluster_pressure` result is not a seed accident. All three retrainings remain clearly better than the best baseline, with a narrow delta range.
- `blackscholes` is mixed: two seeds beat LFU slightly, one seed loses. It should be described as a weak/borderline case, not as stable positive evidence.
- The `canneal` failure is robust rather than noise. QMAP-CrossAttn consistently over-migrates and loses to LRU across all seeds.
- No further seed-stability runs are needed for the current story. The result supports a balanced claim: QMAP-CrossAttn has a stable win on streamcluster pressure, a mixed blackscholes boundary, and a stable canneal failure case.

Artifacts:

- `outputs/results/seed_stability/summary.md`
- `outputs/results/seed_stability/summary.csv`
- `outputs/results/seed_stability/seed_results.csv`
- `outputs/results/seed_stability/*/seed_*/qmap.json`
- `outputs/checkpoints/seed_stability/*/seed_*/qmap_epoch_10.pth`
- Runner: `scripts/run_seed_stability.py`
