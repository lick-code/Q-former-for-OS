# QMAP：面向 DRAM/NVM 混合内存的页面迁移原型

QMAP 是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型。它把页面迁移建模为候选页面排序问题：当 DRAM 已满并且一次 DRAM miss 触发迁移决策时，QMAP 从候选页面中选择最适合从 DRAM 降级到 NVM 的页面。

和老师讨论后，后续主线不再使用 Q-Former。最终模型收敛为：

```text
QMAP-Pool = Transformer Encoder + mean pooling + candidate scorer
```

Q-Former 相关实验只作为前期探索记录保留，不再作为论文主线。当前论文实验规模固定为：`1M real trace + pressure window + real ablation + seed stability`。暂不补 5M；如果后续老师要求更大规模，再重新采集真正的 5M trace 后补跑。当前 `outputs/results/real_workload_suite/5m/` 是 100k 回退结果，不能作为论文或文档中的 5M 实验结果。

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
5. 真实实验主线已经固定为 1M 标准 split、streamcluster/dedup pressure window、真实消融和多 seed。QMAP-Pool 在 streamcluster pressure window 和 blackscholes 上稳定优于最佳 baseline，在 dedup 上基本持平，在 canneal 上稳定失败。
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
| 真实 trace 100k pilot | 阶段 4 已完成；最终口径为 `dram_capacity=16`、`candidate_count=8`、QMAP-Pool mean_pool | `outputs/results/real_pilot/summary.md` |
| 真实 trace 1M 主实验 | 阶段 5 的正式主结果；作为论文主表来源 | `outputs/results/real_workload_suite/1m/summary.md` |
| pressure window 实验 | 阶段 5 的压力窗口补充；streamcluster 是最强真实正结果，dedup 基本持平 | `outputs/results/real_workload_suite_pressure/selected/summary.md` |
| 真实数据消融 | 阶段 6 已完成；只保留 `QMAP-Pool / no_rw / no_cost` | `outputs/results/real_ablation/summary.md` |
| 多 seed 稳定性 | 阶段 7 已完成；验证正结果和负例不是 seed 偶然 | `outputs/results/seed_stability/summary.md` |
| 5M 实验 | 暂缓；当前 5M 目录实际是 100k 回退结果，不进入论文 | `outputs/results/real_workload_suite/5m/` |
| cost-weight sensitivity | 待补；优先级最高，replay-only，不需要重新训练 | `outputs/results/cost_weight_sensitivity/summary.md` |
| capacity sensitivity | 待补；覆盖 streamcluster pressure 和 canneal，DRAM cap=8/16/32 | `outputs/results/capacity_sensitivity/summary.md` |
| candidate-count sensitivity | 待补；覆盖 streamcluster pressure 和 canneal，candidate count=4/8/16 | `outputs/results/candidate_sensitivity/summary.md` |

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
  run_real_pilot.py                    # 真实/PARSEC trace 的 split -> JSONL -> train -> eval -> summary 统一入口
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
candidate_count = 8
lookahead = 256
dram_capacity = 16
epochs = 10
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

状态：已完成，可以进入阶段 5。

目标：确认真实数据 pipeline 能跑通，并找到能产生有效 eviction 压力的真实 trace 配置。

最终采用的 pilot 口径：

```text
records = 100k
chronological split = 80% train / 10% valid / 10% test
history_length = 10
candidate_count = 8
dram_capacity = 16
lookahead = 256
epochs = 10
model = QMAP-Pool
ablation = mean_pool
policies = LRU / Random / LFU / CLOCK / QMAP-Pool
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

最终 100k pilot 结果：

```text
run id: real_pilot_100k_dram16_c8_rankfix
workloads: parsec_blackscholes / parsec_canneal / parsec_streamcluster / parsec_dedup
result: outputs/results/real_pilot_dram16_c8_rankfix/summary.md
diagnosis: outputs/results/real_pilot_dram16_c8_rankfix/diagnosis.md
```

| Workload | Best baseline | Best baseline cost | QMAP-Pool cost | QMAP-Pool vs best | 结论 |
|---|---|---:|---:|---:|---|
| parsec_blackscholes | LRU | 11023.00 | 11159.00 | +1.23% | QMAP 略差，主要成本来自额外迁移 |
| parsec_canneal | LFU | 14574.00 | 14398.00 | -1.21% | QMAP 优于最佳 baseline |
| parsec_streamcluster | LFU | 14473.00 | 14260.00 | -1.47% | QMAP 优于最佳 baseline |
| parsec_dedup | LRU | 10052.00 | 10052.00 | +0.00% | 默认 split 无 eviction，不能作为有效比较 |

dedup 额外补了 pressure window：

```text
run id: real_pilot_dedup_pressure_c8_rankfix
records = 50k
result: outputs/results/real_pilot_dedup_pressure_c8_rankfix/summary.md
```

| Workload | Best baseline | Best baseline cost | QMAP-Pool cost | QMAP-Pool vs best | 结论 |
|---|---|---:|---:|---:|---|
| parsec_dedup pressure | CLOCK | 7306.00 | 7366.00 | +0.82% | QMAP 与 LRU 持平，接近 CLOCK |

阶段 4 结论：

```text
1. 四个 PARSEC workload 都已跑过 100k pilot。
2. blackscholes / canneal / streamcluster 在 c8/rankfix 配置下都有有效 eviction。
3. dedup 默认 100k chronological split 的 test 段没有 eviction 压力，必须使用 pressure window 或更大 trace。
4. QMAP-Pool 在 canneal、streamcluster 上已经超过最佳 baseline；在 blackscholes 上略差；在 dedup pressure 上接近最佳 baseline。
5. 阶段 5 不应沿用 dram64 或 candidate_count=64，应冻结 c8/rankfix 配置。
```

严格依赖关系：

```text
阶段 5 必须基于阶段 4 最终口径：
dram_capacity=16, candidate_count=8, lookahead=256, QMAP-Pool mean_pool。
```

可以并行：

```text
不同 workload 的 1M trace 采集可以并行；如后续补 5M，也按 workload 并行采集；
不同 workload 的 QMAP-Pool 训练可以并行；
baselines replay 可以和 QMAP-Pool 训练并行。
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
model = QMAP-Pool
ablation = mean_pool
policies = LRU / Random / LFU / CLOCK / QMAP-Pool
```

当前阶段 5 口径决策：

```text
正式主表仍使用 QMAP-Pool c8，也就是 rank_guard disabled。
QMAP-Pool-Guard / rank_guard=2 只作为诊断和附表，不作为统一主口径。
```

原因：

```text
rank_guard=2 能缓解 canneal 的 MRU-ish 误驱逐，但会明显伤害 blackscholes 和 streamcluster pressure window。
统一改成 Guard 后，blackscholes 从 -0.91% 变成 +3.41%，streamcluster pressure 从 -12.35% 降到 -2.36%。
因此 Guard 不是当前阶段 5 的正式策略，只用于解释 canneal 的失败原因和候选 rank 敏感性。
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
  outputs/results/real_workload_suite_guard/

可进主表：
  parsec_blackscholes 1M standard, QMAP-Pool c8:
    QMAP vs best baseline = -0.91%
    结论：有效正结果。

  parsec_streamcluster pressure window, QMAP-Pool c8:
    QMAP vs best baseline = -12.35%
    结论：最强真实 workload 正结果。

需要诊断或降级：
  parsec_canneal 1M standard, QMAP-Pool c8:
    QMAP vs LRU = +19.32%
    迁移次数 4567 vs LRU 2350。
    结论：负结果/诊断案例，不强行改统一口径。

  parsec_dedup pressure window:
    QMAP 与 LRU 持平，decision_count 只有 87。
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
outputs/results/real_workload_suite/1m/canneal_epoch_candidate_sweep/

c8 全 epoch 都差，说明不是 epoch 10 单点过拟合。
eval candidate_count=2 可以把 canneal 从 +19.32% 改善到约 -0.85%，说明问题来自 c8 下 QMAP 过度选择靠近 MRU 的 rank。
但 c2 / rank_guard=2 会伤害 blackscholes 和 streamcluster pressure，所以不作为统一主口径。
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
1. summary.md 中每个 workload 的 Migrations / Decision ms / QMAP-Pool vs best baseline。
2. diagnosis.md 中 QMAP 是否再次大量选择过新的候选页。
3. dedup 的 decision_count 是否足够；如果接近 0，该结果只能说明 workload 太容易，不能比较策略。
4. QMAP-Pool 的 avg decision time；当前 100k pilot 中 QMAP 是毫秒级，baseline 是微秒级，论文里要作为 overhead 报告。
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
QMAP-Pool vs best baseline cost delta
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
Step 4. 已完成：4 个 PARSEC 100k raw -> split -> 质量检查已通过。
Step 5. 已完成：阶段 4 100k pilot 已收敛到 `dram_capacity=16, candidate_count=8, lookahead=256`；canneal/streamcluster 上 QMAP-Pool 优于最佳 baseline，blackscholes 略差，dedup 需要 pressure window。
Step 6. 已完成：真实 1M trace 已采集，1M standard split 主实验已跑完。
Step 7. 已完成：streamcluster pressure window 已补，QMAP-Pool c8 有 -12.35% cost 改善。
Step 8. 已完成：canneal epoch/candidate sweep 已补，确认 c8 负结果来自 rank 偏置；rank_guard=2 不作为统一主口径。
Step 9. 已完成：1M 主表已固化，blackscholes 和 streamcluster pressure 作为正结果，canneal 作为负例诊断，dedup 标注 low-pressure tie。
Step 10. 已完成：真实数据必要消融已完成，覆盖 streamcluster pressure 和 blackscholes。
Step 11. 已完成：多 seed 验证已完成，覆盖 streamcluster pressure、blackscholes 和 canneal 负例。
Step 12. 暂缓：正式 5M。当前论文不补 5M；如后续老师要求，必须重新采集真实 5M 并确认 records=5000000。
Step 13. 当前下一步：补三项附录级敏感性实验：cost-weight、capacity、candidate-count。
Step 14. 敏感性实验补完后：开始写论文实验部分，按“1M 主实验 -> pressure window -> 消融 -> 多 seed -> overhead/局限性 -> 附录敏感性”的顺序组织。
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

当前论文实验规模固定为 `1M + pressure window + ablation + seed stability`。表格优先服务论文主线：QMAP-Pool 不是所有 workload 的无条件最优策略，但在有迁移压力和明显相位行为的真实 workload 上能稳定降低 weighted access cost，同时在 canneal 上暴露出候选 rank 敏感性。

推荐进入论文正文的表格：

| 表格 | 内容 | 数据来源 | 用途 |
|---|---|---|---|
| Table 1 | 1M 真实 trace 统计 | `outputs/results/real_workload_suite/1m/trace_stats/summary.md` | 说明数据规模、unique pages、write ratio、reuse ratio |
| Table 2 | 1M 标准 split 主实验：LRU / Random / LFU / CLOCK / QMAP-Pool | `outputs/results/real_workload_suite/1m/summary.md` | 论文主表，展示 blackscholes 正结果、canneal 负例、dedup 持平、streamcluster standard split 低压力问题 |
| Table 3 | pressure window 主实验 | `outputs/results/real_workload_suite_pressure/selected/summary.md` | 作为真实 workload 最强正结果，重点报告 streamcluster pressure 的 `-12.35%` cost delta |
| Table 4 | 真实数据消融：QMAP-Pool / no_rw / no_cost | `outputs/results/real_ablation/summary.md` | 解释 read/write 特征和 cost-aware 训练是否贡献收益 |
| Table 5 | 多 seed 稳定性 | `outputs/results/seed_stability/summary.md` | 证明 streamcluster pressure 和 blackscholes 的正结果不是训练 seed 偶然，canneal 负例也稳定 |

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
| 旧的 `QMAP-Full` 命名表 | 容易和当前 `QMAP-Pool` 主线混淆 |

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
   - blackscholes 是小幅稳定正结果
   - canneal 是稳定负例

3. Pressure Window Results
   - 重点报告 streamcluster pressure window
   - QMAP-Pool 相比最佳 baseline 降低 weighted access cost 12.35%
   - dedup pressure window 与 LRU 持平，作为边界案例

4. Ablation Study
   - streamcluster pressure 上 no_rw 和 no_cost 都变差
   - blackscholes 上消融差异很小，说明该 workload 机制不强

5. Seed Stability and Overhead
   - 三个 seed 下 streamcluster pressure 和 blackscholes 都稳定优于 best baseline
   - canneal 三个 seed 都稳定失败
   - QMAP-Pool 推理开销明显高于传统策略，需要作为代价讨论
```

## 待补三项敏感性实验

下面三项用于增强论文防御性，不改变当前主实验结论。推荐全部放附录，正文只各用一句话概括。

### 1. Cost-weight sensitivity

优先级：最高。

目的：回应 weighted access cost 中 `NVM write=8`、`migration=10` 是否过于主观。该实验不需要重新训练，只需要用已有 replay 结果重新计算 cost，或用 `qmap_eval.py` 指定不同 cost 参数重放。

推荐 workload：

```text
streamcluster_pressure  正例，使用 pressure window
blackscholes            小幅正例，使用 1M standard split
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

如果想用 replay 而不是手工重算，也可以直接调用 `qmap/qmap_eval.py`。示例：

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

最终汇总表：

| Cost model | streamcluster-p delta | blackscholes delta | canneal delta |
|---|---:|---:|---:|
| default | -12.35% | -0.91% | +19.32% |
| mild | 待补 | 待补 | 待补 |
| write-heavy | 待补 | 待补 | 待补 |
| migration-heavy | 待补 | 待补 | 待补 |

推荐输出：

```text
outputs/results/cost_weight_sensitivity/summary.md
outputs/results/cost_weight_sensitivity/summary.csv
```

判断标准：

```text
如果 streamcluster_pressure 在大多数 cost model 下仍优于 best baseline，
就可以在正文写：QMAP-Pool 的正结果不依赖单一 cost 权重。

如果 canneal 在大多数 cost model 下仍失败，
就可以写：canneal 是稳定边界案例，不是 cost 权重选择造成的偶然。
```

### 2. Capacity sensitivity

优先级：高。

目的：回应 `dram_capacity=16` pages 是否过小、结论是否只在单一容量下成立。该实验建议完整重新生成 JSONL、训练、评估，因为 `dram_capacity` 会影响候选样本生成和 replay 压力。

固定配置：

```text
history_length = 10
candidate_count = 8
lookahead = 256
epochs = 10
batch_size = 32
model = QMAP-Pool
ablation = mean_pool
policies = LRU / Random / LFU / CLOCK / QMAP-Pool
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

最终汇总表：

| Workload | DRAM cap | best baseline cost | QMAP cost | delta | QMAP migrations | decision count |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster-p | 8 | 待补 | 待补 | 待补 | 待补 | 待补 |
| streamcluster-p | 16 | 301767 | 264501 | -12.35% | 5541 | 5541 |
| streamcluster-p | 32 | 待补 | 待补 | 待补 | 待补 | 待补 |
| canneal | 8 | 待补 | 待补 | 待补 | 待补 | 待补 |
| canneal | 16 | 126178 | 150559 | +19.32% | 4567 | 4567 |
| canneal | 32 | 待补 | 待补 | 待补 | 待补 | 待补 |

推荐输出：

```text
outputs/results/capacity_sensitivity/summary.md
outputs/results/capacity_sensitivity/summary.csv
```

注意：上面的 `run_real_pilot.py` 命令会先在每个 `cap*` 子目录下生成单独的 `summary.md`。跑完 6 个组合后，需要把这些子目录结果汇总成 `outputs/results/capacity_sensitivity/summary.md` 和 `summary.csv`，再放入附录表。

判断标准：

```text
如果 cap=32 下 decision_count 或 migrations 很低，把该行标注为 low-pressure，不强行解释优劣。
如果 cap=8/16 下 streamcluster_pressure 都有优势，可以说明 QMAP-Pool 在有足够 replacement pressure 时稳定有效。
如果 canneal 在不同容量下仍失败，可以说明它是 workload/candidate-rank 边界，而不是单一容量造成的偶然。
```

### 3. Candidate-count sensitivity

优先级：中高。

目的：补足 canneal 失败机制的证据。已有 `outputs/results/real_workload_suite/1m/canneal_epoch_candidate_sweep/summary.md` 能证明 canneal 与 candidate/rank 有关，但它更像诊断 sweep。建议补一个统一口径的小型 sensitivity：同一训练流程、同一 workload、同一 dram_capacity，只改变 candidate count。

固定配置：

```text
history_length = 10
dram_capacity = 16
lookahead = 256
epochs = 10
batch_size = 32
model = QMAP-Pool
ablation = mean_pool
policies = LRU / Random / LFU / CLOCK / QMAP-Pool
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

最终汇总表：

| Workload | Candidate count | best baseline cost | QMAP cost | delta | QMAP migrations | decision count |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster-p | 4 | 待补 | 待补 | 待补 | 待补 | 待补 |
| streamcluster-p | 8 | 301767 | 264501 | -12.35% | 5541 | 5541 |
| streamcluster-p | 16 | 待补 | 待补 | 待补 | 待补 | 待补 |
| canneal | 4 | 待补 | 待补 | 待补 | 待补 | 待补 |
| canneal | 8 | 126178 | 150559 | +19.32% | 4567 | 4567 |
| canneal | 16 | 待补 | 待补 | 待补 | 待补 | 待补 |

推荐输出：

```text
outputs/results/candidate_sensitivity/summary.md
outputs/results/candidate_sensitivity/summary.csv
```

注意：上面的 `run_real_pilot.py` 命令会先在每个 `c*` 子目录下生成单独的 `summary.md`。跑完 6 个组合后，需要把这些子目录结果汇总成 `outputs/results/candidate_sensitivity/summary.md` 和 `summary.csv`，再放入附录表。

判断标准：

```text
如果 canneal 随 candidate_count 增大而明显变差，可以支撑“candidate-rank sensitivity”解释。
如果 streamcluster_pressure 在 c4/c8/c16 中至少 c8 或 c16 稳定优于 best baseline，可以说明正例不是单一 candidate_count 偶然。
如果 c16 推理开销明显增加，需要在附录标注 avg decision time。
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

## Stage 6: Real-workload ablation conclusion

Stage 6 answers: why QMAP works, and which feature/loss terms contribute.

Scope:

- `parsec_streamcluster` pressure window: main positive real workload case.
- `parsec_blackscholes` standard 1M split: smaller positive standard split case.
- Variants: `QMAP-Pool`, `no_rw`, `no_cost`.
- Configuration: `history_length=10`, `candidate_count=8`, `lookahead=256`, `dram_capacity=16`, `epochs=10`, `batch_size=32`, `seed=3136859`.

Result table:

| workload | variant | cost | vs QMAP-Pool | NVM writes | migrations |
|---|---|---:|---:|---:|---:|
| streamcluster_pressure | QMAP-Pool | 264501.00 | +0.00% | 589 | 5541 |
| streamcluster_pressure | no_rw | 265905.00 | +0.53% | 592 | 5667 |
| streamcluster_pressure | no_cost | 265395.00 | +0.34% | 584 | 5625 |
| blackscholes | QMAP-Pool | 105983.00 | +0.00% | 32 | 525 |
| blackscholes | no_rw | 105961.00 | -0.02% | 32 | 523 |
| blackscholes | no_cost | 105983.00 | +0.00% | 32 | 525 |

Interpretation:

- On `streamcluster_pressure`, both ablations make cost worse, so the real positive case supports the claim that QMAP uses read/write access context and cost-aware supervision. Removing RW hurts more (`+0.53%`) than removing the write-sensitivity / migration-cost loss terms (`+0.34%`).
- On `blackscholes`, the deltas are effectively neutral (`-0.02%` and `+0.00%`). This workload has a small active page set and the gain is already small, so the ablation does not expose a strong mechanism there.
- No full canneal ablation is needed for the main story. Canneal remains a failure-diagnosis case, not the primary evidence for QMAP's benefit.

Artifacts:

- `outputs/results/real_ablation/summary.md`
- `outputs/results/real_ablation/summary.csv`
- `outputs/results/real_ablation/*/*/qmap.json`
- `outputs/checkpoints/real_ablation/*/*/qmap_epoch_10.pth`
- `dataset/jsonl/real_ablation/*/*/*.jsonl`
- Runner: `scripts/run_real_ablation.py`

## Stage 7: Seed stability conclusion

Stage 7 answers: is the QMAP-Pool result just an accidental training-seed outcome?

Scope:

- `streamcluster_pressure`: strongest positive real workload case.
- `blackscholes`: standard 1M split positive case.
- `canneal`: negative / robustness-boundary case.
- Seeds: `3136859`, `42`, `2026`.
- Baselines are reused from the existing deterministic or fixed-random-seed runs. Only QMAP-Pool is retrained for each seed.

Per-seed results:

| workload | seed | QMAP cost | best baseline cost | delta | migrations | writes |
|---|---:|---:|---:|---:|---:|---:|
| streamcluster_pressure | 3136859 | 264501.00 | 301767.00 | -12.35% | 5541 | 589 |
| streamcluster_pressure | 42 | 270304.00 | 301767.00 | -10.43% | 6068 | 590 |
| streamcluster_pressure | 2026 | 265585.00 | 301767.00 | -11.99% | 5639 | 590 |
| blackscholes | 3136859 | 105983.00 | 106952.00 | -0.91% | 525 | 32 |
| blackscholes | 42 | 104707.00 | 106952.00 | -2.10% | 409 | 32 |
| blackscholes | 2026 | 105002.00 | 106952.00 | -1.82% | 438 | 28 |
| canneal | 3136859 | 150559.00 | 126178.00 | +19.32% | 4567 | 51 |
| canneal | 42 | 152154.00 | 126178.00 | +20.59% | 4718 | 40 |
| canneal | 2026 | 147212.00 | 126178.00 | +16.67% | 4260 | 56 |

Stability summary:

| workload | mean delta | std delta | min/max delta | conclusion |
|---|---:|---:|---:|---|
| streamcluster_pressure | -11.59% | 0.83% | -12.35% / -10.43% | Stable positive. All seeds beat the best baseline. |
| blackscholes | -1.61% | 0.51% | -2.10% / -0.91% | Stable positive. All seeds beat the best baseline. |
| canneal | +18.86% | 1.63% | +16.67% / +20.59% | Stable negative boundary. All seeds are worse than the best baseline. |

Interpretation:

- The strong `streamcluster_pressure` result is not a seed accident. All three retrainings remain clearly better than the best baseline, with a narrow delta range.
- The smaller `blackscholes` gain is also not a seed accident. The improvement is modest, but every seed still beats LFU.
- The `canneal` failure is robust rather than noise. QMAP-Pool consistently over-migrates and loses to LRU across all seeds.
- No further seed-stability runs are needed for the current story. The result supports a balanced claim: QMAP-Pool has stable wins on the selected positive workloads, and the known canneal boundary is also stable.

Artifacts:

- `outputs/results/seed_stability/summary.md`
- `outputs/results/seed_stability/summary.csv`
- `outputs/results/seed_stability/seed_results.csv`
- `outputs/results/seed_stability/*/seed_*/qmap.json`
- `outputs/checkpoints/seed_stability/*/seed_*/qmap_epoch_10.pth`
- Runner: `scripts/run_seed_stability.py`
