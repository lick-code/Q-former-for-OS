# CAPD Stage 7 数据重训与 Pressure Test 修复流程指南

## 0. 文档目的

本指南规定如何在**不重新采集、不修改原始访问记录**的前提下，修复当前 Stage 8 的数据链错误，并使用现有六个 Stage 7 workload 完成：

1. 六个 Train 的统一 CAPD 训练；
2. 六个 Validation 的 checkpoint 选择；
3. 原始 Standard Test 的正式回放；
4. 从真实 trace 派生的连续 Pressure Test 回放；
5. Standard 与 Pressure 两条结果线的独立报告。

代码实现任务详见：

`docs/superpowers/plans/2026-08-01-capd-stage7-refit-pressure-repair.md`

本次修复的成功标准是数据链正确、产物可追溯、比较公平。修复**不预先保证** CAPD 的 weighted cost 一定优于所有 baseline。

---

## 1. 当前错误与修复目标

当前已完成的 `stage8-sync-replay-r3` 使用：

```text
Stage 3/4 老 trace 训练出的 checkpoint
                  +
Stage 7 新 trace 的 Test
```

由于模型把绝对 page/PC 作为身份特征，新旧进程地址空间不同，Stage 8 中 page/PC 全部落入 UNK。该运行虽然工程验收通过，但不能作为最终 CAPD 性能结果。

修复后的数据链必须是：

```text
Stage 7 Train
  -> 生成训练样本与 Train 词表
  -> 训练三个 seed 的统一 CAPD

Stage 7 Validation
  -> 选择每个 seed 的最终 checkpoint

冻结 checkpoint、容量、Standard/Pressure Test 身份
  -> Stage 8 Test 回放
```

六个 workload 均参与 Train/Validation，因此修复后不再区分 `seen` 和 `held-out unseen`。Test 仍然是按时间顺序隔离、未参与模型拟合的测试区间。

---

## 2. 不可违反的边界

### 2.1 原始 trace 不变

以下目录只读：

```text
dataset/raw_traces/capd_proactive_stage7/stage7-local-collection-r1/
outputs/capd_proactive_stage7/stage7-server-suite-r1/
outputs/capd_proactive_stage4/stage4-f8-f16-r3/
outputs/capd_proactive_stage8/stage8-sync-replay-r3/
```

禁止：

- 修改 PC、Address 或 RW；
- 删除不利访问；
- 复制、重排或合成访问；
- 覆盖旧 split、checkpoint 或 Stage 8 结果；
- 把派生 Pressure Test 描述成未经选择的 Standard Test。

### 2.2 Pressure Test 的准确表述

统一表述为：

> Pressure Test 是从真实采集 trace 中，按照固定且与 CAPD 结果无关的 Reactive-LRU 压力规则，派生得到的连续时间片。

必须公开：

- 原始 trace ID 与 SHA256；
- 起止访问索引；
- 窗口长度与扫描步长；
- 全部候选窗口统计；
- 固定选择规则；
- 派生 CSV 的 SHA256。

### 2.3 Pressure Test 禁止用于开销结论

Pressure Test 只报告：

- DRAM hit；
- NVM read/write；
- demotion；
- weighted cost；
- Oracle headroom；
- proactive cycle/round；
- early-reuse；
- OOV；
- LRU replacement decision 数量。

Pressure Test 不报告或不用于声称：

- 模型内存开销；
- metadata 内存开销；
- 推理时间；
- CPU cycles；
- 总执行时间；
- 前台阻塞时间；
- 端到端系统开销。

这些开销只能来自未挑选的 Standard Test、固定微基准或后续异步实验。

### 2.4 本地与服务器执行边界

执行位置固定如下，不得临时互换：

- **本地（R1-R4）**：校验原始 trace、计算容量、扫描连续窗口、派生 Pressure CSV、生成来源清单和 SHA256；
- **服务器（R5-R11）**：生成训练 manifest、训练与 Validation 选 checkpoint、冻结执行计划、运行 Standard/Pressure Stage 8、聚合和验证；
- **本地禁止运行**：训练、checkpoint 选择、正式 Replay、性能统计或开销测量；
- **服务器禁止运行**：重新扫描窗口、改变窗口选择、重新派生 Pressure CSV。

这里的“本地派生”只允许把原 Test 中已经存在的连续行复制到新的 Pressure 文件。原始 CSV 仍为只读，不允许修改、重排、删行、复制行或合成访问。

---

## 3. 固定配置

本轮不重新搜索下列模型配置：

```text
F_low = 8
F_target = 16
b_max = 4
K = 8
H = 20
L = 256
lambda = (1, 1, 2)
seeds = 3136859, 42, 2026
```

同时继承：

```text
TPP epoch_length = 1024
TPP cold_threshold = 1
TPP dirty_tie_break = false
Cost = DRAM Hit 1, NVM Read 2, NVM Write 8, Demotion 10
```

这里的“固定”表示不根据已查看的 Stage 8 结果重新选择这些值。Stage 4 老 checkpoint 不再固定为最终 checkpoint。

---

## 4. 容量双轨

### 4.1 Standard 容量

Standard Test 保留原口径：

```text
W_i = |UniquePages(Train union Validation)|
D_base(i,r) = ceil(r * W_i)
r = 0.20 / 0.40 / 0.60
```

Standard 结果用于保持与原正式矩阵的可比性。

### 4.2 Pressure 的机制兼容容量

固定 `F_target=16` 时，22页 DRAM 会让储备占比过高。Pressure 轨采用预先声明的容量保护：

```text
reserve_fraction_cap = 0.25
D_guard_min = ceil(16 / 0.25) = 64
D_guarded = max(D_base, 64)
```

报告必须同时列出：

```text
requested_ratio
D_base
D_guarded
effective_ratio = D_guarded / W_i
```

被提升到64页的单元不得继续简称为“严格20%容量”。

---

## 5. Pressure 窗口规则

Pressure 候选只从原 Standard Test `[2400000,3000000)` 内产生，不能与 Train/Validation 重叠。

固定扫描参数：

```text
window_records = 100000
scan_step = 10000
```

候选起点为：

```text
2400000, 2410000, ..., 2900000
```

每个候选窗口只运行 Reactive-LRU，记录：

- unique pages；
- misses；
- replacement decisions；
- write ratio；
- page-entry count。

某个 workload/capacity 单元成为 Pressure Test 的必要条件：

```text
unique_pages > D_guarded + F_target
LRU replacement decisions >= 100
```

固定选择顺序：

```text
1. replacement decisions 更多
2. unique pages 更多
3. start index 更早
```

如果没有候选通过，写入：

```text
pressure_eligible = false
```

该单元只保留 Standard 结果，不得人为制造 Pressure 窗口。

---

## 6. 总体时间顺序

```text
R0  [文档]   保留旧结果并声明失效原因
R1  [本地]   审计六条原始 trace 的身份和 SHA
R2  [本地]   冻结修复配置、Standard 容量和 guarded 容量
R3  [本地]   运行 Stage 3 Train/Validation 压力审计
R4  [本地]   扫描、派生并冻结 Pressure Test 连续窗口
    [传输]   将本地冻结包上传服务器并验签
R5  [服务器] 生成六 workload Stage 4 Train/Validation manifest
R6  [服务器] 用固定超参数训练三个新 checkpoint
R7  [服务器] 用六个 Validation 选择并冻结 checkpoint
R8  [服务器] 生成修复后的 Stage 7 / Stage 8 执行计划
R9  [服务器] 先运行 Standard Stage 8
R10 [服务器] 再运行 Pressure Stage 8
R11 [服务器] 分轨聚合、验证和报告
```

只有前一步门禁通过，才能进入下一步。

### 6.1 实际执行方式

R0-R11 是产物门禁，不是12次独立人工操作。实际压缩为四个批处理：

```text
批处理A [本地]   R1-R4：审计 + 扫描 + 派生 + SHA 冻结
批处理B [服务器] R5-R8：验签 + manifest + 训练 + checkpoint/计划冻结
批处理C [服务器] R9-R10：Standard + Pressure Replay
批处理D [服务器] R11：分轨聚合 + 验证 + 报告
```

四个批处理都必须支持断点续跑：已通过且身份哈希一致的步骤直接跳过；输入、配置或 checkpoint SHA 变化时拒绝复用旧产物并要求新 run ID。这样任何中断都从最近的有效门禁继续，而不是重跑整个流程。

---

## 7. 分步骤执行说明

### R0：保留并隔离旧结果

旧结果不删除、不覆盖。

将其状态解释为：

```text
verified execution of invalid old-checkpoint/new-trace protocol
```

新 run ID 固定为：

```text
Stage 7 repair: stage7-repair-r1
Stage 4 refit:  stage4-stage7-refit-r1
Stage 8 repair: stage8-repair-r1
```

### R1：原始身份审计

**执行位置：本地。**

读取并交叉验证：

```text
raw_trace_manifest.json
collection_manifest.json
split_manifest.json
实际 raw CSV SHA256
实际 split CSV SHA256
```

检查每个 workload：

- 一个 PID；
- 一个 TID；
- `page_shift=12`；
- 3,000,000 条访问；
- Train/Validation/Test 区间无重叠；
- raw SHA 与 Stage 7 原记录一致。

输出：

```text
outputs/capd_proactive_stage7_repair/stage7-repair-r1/raw_identity_audit.json
```

门禁：

```text
STAGE7_REPAIR_RAW_IDENTITY_VERIFIED
```

### R2：冻结修复合同和容量

**执行位置：本地。**

生成：

```text
frozen_parameters.json
capacity_matrix_standard.json
capacity_matrix_guarded.json
```

检查：

- 固定参数与旧 Stage 4 最终选择一致；
- Standard 使用 `D_base`；
- Pressure 使用 `D_guarded`；
- 没有根据 CAPD Test 指标调整容量。

### R3：Stage 3 修复审计

**执行位置：本地。** 本步骤只做 trace 统计与压力可达性审计，不训练模型、不运行正式 Stage 8。

只读取六个 Train/Validation，按 Train 后接 Validation 的顺序运行 Reactive-LRU 和页面进入统计。

本步骤重新计算：

- working set；
- page-entry burst；
- LRU miss；
- LRU replacement decisions；
- Standard/guarded 容量可达性。

本步骤不修改 `F_low/F_target/b_max`，也不读取 Test。

门禁：

```text
STAGE7_REPAIR_STAGE3_AUDIT_READY
```

### R4：冻结 Pressure Test

**执行位置：本地。** 服务器不得重新执行选择规则。

使用第5节固定规则扫描原 Standard Test，保存所有候选，不只保存最终窗口。

输出：

```text
pressure_candidates.csv
pressure_window_manifest.json
pressure_test_lock.json
derived_pressure/<workload>/<capacity>.csv
local_pressure_bundle_manifest.json
```

人工复核只能检查规则是否正确执行，不允许手动替换窗口。

每个派生 CSV 必须逐行等于其声明的原 Test 连续区间，并在 `local_pressure_bundle_manifest.json` 中记录源 SHA、起止索引、派生 SHA 和行数。上传服务器后必须先验签；任一 SHA 不一致立即停止，不能在服务器重建或替换窗口。

### R5：生成六 workload Stage 4 manifest

**执行位置：服务器。** 输入为服务器上的六个 Stage 7 Train/Validation，以及已验签的本地冻结包；本步骤不得重新派生 Pressure trace。

manifest 必须正好包含12项：

```text
6 Train
6 Validation
0 Test
```

每项保存：

- workload；
- split；
- source trace ID；
- source interval；
- CSV SHA256；
- `formal_test=false`。

输出：

```text
stage4_input_manifest.json
```

### R6：固定参数重新训练

**执行位置：服务器。**

使用所有六个 Train：

```text
canneal
streamcluster_pressure
dedup_pressure
blackscholes
swaptions
fluidanimate
```

训练要求：

- 一个 global CAPD；
- 三个 seed 独立训练；
- page/PC 词表只从 Train 拟合；
- 拟合后立即冻结词表；
- 不执行 L、lambda、K、H 网格搜索；
- 不读取任何 Test；
- 保留断点续训和 deterministic 设置。

### R7：Validation 选择 checkpoint

**执行位置：服务器。**

六个 Validation 只用于：

- 每个 seed 的 minimum validation loss checkpoint；
- 相同 loss 时选择更早 epoch；
- 输出逐 workload Validation 指标和 OOV。

不得：

- 选择“最好 seed”；
- 根据 Test 修改 epoch、学习率或模型结构；
- 扩展冻结后的词表。

门禁：

```text
STAGE4_STAGE7_REFIT_VERIFIED
```

### R8：生成修复后的执行计划

**执行位置：服务器。**

修复计划必须：

- 将六个 workload 全部标为 `training_seen_workload`；
- 指向三个新 checkpoint 及其 SHA；
- Standard jobs 固定为144个；
- Pressure jobs 数量为 `eligible_cells * 8`；
- 为每个 job 写入 `evaluation_track=standard|pressure`；
- 保存 Standard 与 Pressure 各自的 Test lock；
- 要求两条轨道都输出 OOV；
- 写入 `pressure_overhead_claims_allowed=false`。

门禁：

```text
STAGE7_REPAIR_EXECUTION_PLAN_VERIFIED
```

### R9：运行 Standard Stage 8

**执行位置：服务器。**

先完整运行144个 Standard job。

Standard 是：

- 固定600,000访问的原 Test；
- 所有策略使用同一 trace 和容量；
- CAPD 使用三个新 seed checkpoint；
- 可用于同步 Replay 范围内的时间和内存开销报告。

### R10：运行 Pressure Stage 8

**执行位置：服务器。** 只读取已验签的本地派生 CSV，不得重新选窗。

只运行 `pressure_eligible=true` 的单元。

所有策略必须使用同一个：

- 起止区间；
- guarded capacity；
- 初始空 DRAM 状态；
- cost profile；
- 主动控制参数。

Pressure result 中下列字段必须为 `null`：

```text
memory_overhead
inference_latency
cpu_cycles
foreground_blocking_time
```

并写入：

```text
overhead_claim_status = not_reported_for_overhead_claim
```

### R11：分轨聚合和最终结论

**执行位置：服务器。**

生成两个独立目录：

```text
artifacts/standard/
artifacts/pressure/
```

禁止：

- 将两条轨道混成一个 macro average；
- 将 Pressure 时间片当作独立新采集 trace；
- 用 Pressure 结果声称算法时间/内存开销更低；
- 只报告有利 Pressure 单元而隐藏未通过资格门禁的单元。

---

## 8. 执行命令与交接

以下命令是修复代码实现后的目标接口。除 trace 审计与派生外，所有需要运行代码的步骤都在服务器完成。

### 8.1 本地：审计并派生 Pressure trace

```powershell
Set-Location 'D:\计算机系统大赛\功能赛道\cache_replacement'

python scripts/run_capd_proactive_stage7_repair.py preflight `
  --config configs/finals/capd_proactive_stage7_repair.json `
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 `
  --run-id stage7-repair-r1

python scripts/run_capd_proactive_stage7_repair.py scan-pressure `
  --config configs/finals/capd_proactive_stage7_repair.json `
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 `
  --run-id stage7-repair-r1

python scripts/run_capd_proactive_stage7_repair.py export-local-bundle `
  --run-id stage7-repair-r1
```

本地结束门禁：

```text
STAGE7_REPAIR_LOCAL_PRESSURE_BUNDLE_VERIFIED
```

本地冻结包至少包含容量矩阵、全部候选统计、窗口清单、派生 CSV、源/派生 SHA 和配置 SHA。冻结后不得手工编辑；将整个目录原样上传服务器。

### 8.2 服务器：环境检查与本地冻结包验签

```bash
cd /home/likc/Q-former-for-OS
conda activate capd
git status --short
python3 -c 'import sys,torch; print(sys.version); print(torch.__version__); print(torch.cuda.is_available())'

python3 scripts/run_capd_proactive_stage7_repair.py verify-local-bundle \
  --bundle outputs/capd_proactive_stage7_repair/stage7-repair-r1/local_pressure_bundle_manifest.json \
  --run-id stage7-repair-r1
```

服务器验签只能核对来源、内容和 SHA，不得重算候选排序或生成新的 Pressure 文件。必须得到：

```text
STAGE7_REPAIR_SERVER_ACCEPTED_LOCAL_BUNDLE
```

### 8.3 服务器：生成训练 manifest

```bash
python3 scripts/run_capd_proactive_stage7_repair.py build-training-manifest \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --run-id stage7-repair-r1
```

### 8.4 服务器：训练三个 checkpoint

```bash
python3 scripts/run_capd_proactive_stage4_refit.py all \
  --manifest outputs/capd_proactive_stage7_repair/stage7-repair-r1/stage4_input_manifest.json \
  --frozen-parameters outputs/capd_proactive_stage7_repair/stage7-repair-r1/frozen_parameters.json \
  --run-id stage4-stage7-refit-r1 \
  --project-root "$PWD" \
  --device cuda:0
```

监控：

```bash
tail -f outputs/capd_proactive_stage4/stage4-stage7-refit-r1/logs/progress.jsonl
```

### 8.5 服务器：冻结修复执行计划

```bash
python3 scripts/run_capd_proactive_stage7_repair.py freeze \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --checkpoint-freeze outputs/capd_proactive_stage4/stage4-stage7-refit-r1/final_freeze_candidate.json \
  --run-id stage7-repair-r1

python3 scripts/run_capd_proactive_stage7_repair.py verify \
  --config configs/finals/capd_proactive_stage7_repair.json \
  --source-stage7-run outputs/capd_proactive_stage7/stage7-server-suite-r1 \
  --run-id stage7-repair-r1
```

### 8.6 服务器：运行修复后的 Stage 8

```bash
set -o pipefail
bash scripts/validate_capd_proactive_stage8_server.sh \
  stage8-repair-r1 cuda:0 \
  configs/finals/capd_proactive_stage8_repair.json \
  2>&1 | tee stage8-stage8-repair-r1-console.log
```

---

## 9. 失败处理

- 任一 raw SHA 不一致：停止，不生成后续 manifest。
- Pressure 单元不合格：保留 `pressure_eligible=false`，继续其他单元。
- Stage 4 中断且身份一致：使用同一 refit run ID 续跑。
- Stage 4 参数或输入 SHA 改变：必须换新 run ID。
- Stage 8 job 失败或结果损坏：保留现场，修复后使用新 Stage 8 run ID。
- 不允许删除失败目录后伪装首次成功。

---

## 10. 最终验收清单

- [ ] 六条 raw trace SHA 与原 Stage 7 一致。
- [ ] 原始 CSV 和旧输出未发生修改。
- [ ] Pressure 扫描、派生和冻结只在本地完成。
- [ ] 服务器验签通过，且未重新选窗或重新派生 Pressure CSV。
- [ ] Stage 4 manifest 为6 Train + 6 Validation + 0 Test。
- [ ] L/H/K/lambda 与旧 Stage 4 选择完全一致。
- [ ] 新 checkpoint 共3个，词表来源为六个 Stage 7 Train。
- [ ] Validation 负责 checkpoint 选择，Test 未参与训练或选择。
- [ ] Standard job 为144个且全部完成。
- [ ] Pressure 只包含合格单元，所有策略窗口完全一致。
- [ ] Standard 与 Pressure 分开聚合。
- [ ] Pressure 报告不存在时间、内存、CPU 或端到端开销结论。
- [ ] 两条轨道均报告 page/PC OOV。
- [ ] 报告明确披露旧 Stage 8 的数据域错配和 Pressure 的派生规则。

全部通过后，才能把 `stage8-repair-r1` 作为修复后的正式实验结果。
