# CAPD Stage 7 Recalibration, Refit, and Final Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Stop at every explicit human freeze gate; a verified candidate is not approval.

**Goal:** 基于六个真实 Stage 7 trace，重新校准 Stage 3 控制器与容量配置、重新搜索 Stage 4 模型超参数，并在冻结后的 Standard Test 和 Pressure Test 上完成最终 Stage 8。最终实验不继承旧固定参数，也不与旧实验做性能比较。

**Architecture:** R1 提供只读数据身份链；Stage 3 只用 Train/Validation 搜索 working set、窗口、容量、水位和批量机制；人工 freeze 后，一条分支在本地按冻结合同派生 Pressure Test，另一条分支在服务器搜索并训练统一 CAPD；两条分支冻结后才生成 Stage 8 计划。Test 永不反馈到 Stage 3/4。

**Execution boundary:** 本地负责代码修改、R1 审计和 Pressure 派生；服务器负责测试、Stage 3、Stage 4、Stage 8 及统计运行。服务器只验证本地 Pressure 包，不能重新选窗。

**Tech Stack:** Python 3.7-compatible code、PyTorch、CSV/JSON manifest、现有同步 replay 模块、`unittest`、PowerShell、Linux shell。

---

## Material Passport

- Origin Skill: `academic-research-suite/experiment-agent`
- Origin Mode: `implementation-plan`
- Origin Date: `2026-08-02`
- Verification Status: `PARTIALLY_IMPLEMENTED_STAGE3_RUNNING`
- Version Label: `capd_stage7_recalibration_plan_v2`
- Raw data access: read-only
- Test selection status: forbidden for Stage 3/4
- Performance comparison policy: current final experiment only; no old/new comparison

---

## 1. 当前事实与废止项

### 1.1 当前事实

- R1 原始 trace 审计已经完成。
- `stage3-stage7-calibration-r2` 当前正在服务器运行。
- Stage 3 尚未产生经人工同意的正式 freeze，所有超参数均未确定。
- 新 Stage 4 Stage 7 专用实现尚未完成。
- Pressure Test 尚未生成，必须等待 Stage 3 freeze。
- 最终 Stage 8 尚不能执行。

### 1.2 已废止的假设

下列值和规则不得再被当作最终配置：

```text
F_low=8
F_target=16
b_max=4
L=256
H=20
K=8
lambda=(1,1,2)
window_records=100000
D_guard_min=64
```

不得保留以下旧流程：

- 用旧 Stage 3/4 参数在 Stage 7 Test 上直接重跑；
- 固定模型参数后只做 refit；
- 用固定 100k 窗口先生成 Pressure，再补做 Stage 3；
- 用 20/40/60% 容量维持与旧实验可比；
- 把旧 run ID 作为本轮正式 run ID；
- 将旧 Stage 8 结果放入最终对比表。

旧代码和旧输出可以留在磁盘用于追溯，但不得参与选择、训练、聚合和结论。

---

## 2. 实施总图

```text
Task 0  文档与合同更新
Task 1  Stage 3 服务器运行（进行中）
Task 2  Stage 3 结果审计与人工 freeze
          |
          +---------------------------+
          |                           |
Task 3  本地 Pressure 派生实现      Task 4  本地 Stage 4 实现
Task 5  本地生成 Pressure           Task 6  服务器 Stage 4 搜索/训练
          |                           |
          +-------------+-------------+
                        |
Task 7  Stage 8 计划生成与冻结
Task 8  服务器 Standard + Pressure Replay
Task 9  分轨聚合、统计与最终报告
```

严格依赖：

```text
R1 -> Stage 3 run -> Stage 3 review -> explicit freeze
Stage 3 freeze -> Pressure generation
Stage 3 freeze -> Stage 4 execution
Pressure freeze + Stage 4 freeze -> Stage 8
```

Stage 3 freeze 后，Task 5 和 Task 6 可以分别在本地与服务器并行。Stage 4 代码可以提前开发，但不得把未冻结 Stage 3 候选硬编码为最终值。

---

## 3. 全局不可违反的合同

### 3.1 数据合同

- 六个 Stage 7 raw trace 和 R1 SHA 链是唯一数据源。
- 原始 trace 和已有 split 只读。
- Train/Validation 保持时间顺序，不 shuffle，不跨 split 取窗。
- Stage 3/4 输入必须是 `6 Train + 6 Validation + 0 Test`。
- 词表只从 Train 构建，冻结后不得由 Validation/Test 扩展。
- Test 不得用于容量、水位、模型结构、损失、seed 或 checkpoint 选择。

### 3.2 选择合同

- Stage 3 只用 Train 做 blocked calibration，用 Validation 做安全门禁和选择验证。
- Stage 4 只用 Train 训练，用 Validation 搜索模型和选择 checkpoint。
- Pressure 选择只使用 Stage 3 已冻结的 Reactive-LRU 压力规则。
- Oracle 只表示优化空间上界，不参与 Pressure 选窗。
- 每个选择步骤必须预先固定聚合指标、tie-break 和失败条件。

### 3.3 报告合同

- Standard 与 Pressure 分开报告。
- 不将旧实验作为 baseline 或前后对照。
- Pressure 不用于时间、内存、CPU、前台阻塞或端到端开销结论。
- 同步 replay 只证明 ranking、cost 和状态轨迹，不能证明真实异步收益。

---

## 4. Task 0：同步文档与权威入口

**Files:**

- Modify: `docs/CAPD_PROACTIVE_STAGE7_REPAIR_FLOW_CN.md`
- Modify: `docs/superpowers/plans/2026-08-01-capd-stage7-refit-pressure-repair.md`
- Reference: `docs/CAPD_PROACTIVE_STAGE3_STAGE7_SERVER_CN.md`
- Reference: `configs/finals/capd_proactive_stage3_stage7_calibration.json`

**Steps:**

- [x] 删除固定参数、固定窗口和固定容量保护的正式表述。
- [x] 将 Stage 3 重校准放在 Pressure 和 Stage 4 之前。
- [x] 明确 Stage 3 当前正在服务器运行，所有参数仍未确定。
- [x] 明确 Stage 4 必须重新搜索而不是固定 refit。
- [x] 删除新旧性能对比目标。
- [x] 保留 Pressure 的开销证据禁区。

**Gate:** 文档不得把任何 Stage 3/4 候选数值称为 final、selected 或 frozen。

---

## 5. Task 1：完成 Stage 3 服务器运行

**Implemented files:**

- `configs/finals/capd_proactive_stage3_stage7_calibration.json`
- `qmap/proactive_stage3_stage7.py`
- `scripts/run_capd_proactive_stage3_stage7.py`
- `tests/test_capd_proactive_stage3_stage7.py`
- `docs/CAPD_PROACTIVE_STAGE3_STAGE7_SERVER_CN.md`

**Run identity:**

```text
stage3-stage7-calibration-r2
```

**Current status:** 正在服务器运行。不得因为中间点估计提前宣布某组参数胜出。

**Search candidates, not final values:**

```text
window_records = [100000, 300000, 500000]
W_ref quantile = [0.50, 0.75, 0.90]
r_pressure = [0.05, 0.10, 0.15, 0.20]
D_min = 8
alpha = [0.05, 0.10, 0.15, 0.20]
beta = [0.4, 0.5, 0.6]
b_max = [1, 2, 4, 8]
```

Dynamic watermark candidates:

```text
F_target(D) = clamp(round(alpha * D), 2, 16)
F_low(D) = max(1, round(beta * F_target(D)))
F_target(D) / D <= 0.25
```

**Server steps:** 继续严格使用 `docs/CAPD_PROACTIVE_STAGE3_STAGE7_SERVER_CN.md` 中已验证的命令和 resume 规则，不在本计划复制运行命令。

**Required outputs before review:**

```text
run_state.json
verification.json
pressure_coverage.json
oracle_headroom.json
validation_safety.json
pareto_frontier.json
selection_rationale.json
final_freeze_candidate.json
pressure_generation_contract_candidate.json
```

**Gate:** `all` 完成只表示候选生成完成，不得自动生成正式 freeze。

---

## 6. Task 2：审计 Stage 3 并显式冻结

**Input:** `outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/`

**Review checklist:**

- [ ] R1 input identity、配置 SHA 和代码 SHA 一致。
- [ ] 全部输入只含 Train/Validation。
- [ ] Train 各 block 有足够 pressure coverage。
- [ ] 全局 Oracle headroom 非零。
- [ ] Reactive/Proactive/Oracle 使用相同 trace、容量、初始状态和 cost profile。
- [ ] Validation safety 没有 weighted-cost regression、过高 early reuse 或无意义降级。
- [ ] Pareto 候选与选择理由可以由保存的逐窗统计复算。
- [ ] 候选没有引用 Test、Stage 8 或 Pressure 结果。

**Human gate:** 向用户展示候选、门禁和 trade-off，等待明确同意。没有明确同意时停止，不能执行 freeze。

**Formal outputs after approval:**

```text
final_freeze.json
pressure_generation_contract.json
```

二者必须包含自身 SHA 链并固定：窗口、步长、每 workload 容量、水位函数/结果、`b_max`、资格规则和 Reactive-LRU tie-break。

**Failure rule:** 若无候选通过，保留本轮失败结果；只能回到 Train/Validation 设计新的 Stage 3 搜索合同并使用新 run ID，禁止查看 Test 后调参。

---

## 7. Task 3：实现本地 Pressure 派生工具

**Target files:**

- Create: `configs/finals/capd_proactive_pressure_stage7.json`
- Create: `qmap/proactive_pressure_stage7.py`
- Create: `scripts/run_capd_proactive_pressure_stage7.py`
- Create: `tests/test_capd_proactive_pressure_stage7.py`
- Create: `docs/CAPD_PROACTIVE_PRESSURE_STAGE7_LOCAL_CN.md`

文件名是目标接口；实现时若仓库已有更合适的模块边界，可调整名称，但必须同步文档和 manifest schema。

**Implementation requirements:**

- [ ] 从 Stage 3 正式 `pressure_generation_contract.json` 读取全部规则。
- [ ] 拒绝 candidate 合同、缺 SHA 合同和未 freeze 合同。
- [ ] 原 Test 只读，派生窗口必须逐行等于声明的连续源区间。
- [ ] 保存所有候选窗口统计，而非只保存获选窗口。
- [ ] 排序只允许 Reactive-LRU replacements、unique pages 和冻结 tie-break。
- [ ] 禁止导入 CAPD checkpoint 或读取 CAPD/Oracle/TPP cost。
- [ ] 无合格窗口时写 `pressure_eligible=false`。
- [ ] 生成 source/derived SHA 和不可变 lock。

**Tests first:**

- [ ] 非冻结合同被拒绝。
- [ ] Stage 3 contract SHA 不匹配被拒绝。
- [ ] 选窗确定性测试通过。
- [ ] 派生 CSV 与源连续区间逐行一致。
- [ ] CAPD/Oracle/weighted-cost 字段参与排序时测试失败。
- [ ] 无合格窗口正常输出 false，不人工放宽规则。

**Gate:** 本任务只实现和本地测试，不在 Stage 3 freeze 前生成正式 Pressure 产物。

---

## 8. Task 4：实现 Stage 4 Stage 7 专用搜索

**Target files:**

- Create: `configs/finals/capd_proactive_stage4_stage7_search.json`
- Create: `qmap/proactive_stage4_stage7.py`
- Create: `scripts/run_capd_proactive_stage4_stage7.py`
- Create: `tests/test_capd_proactive_stage4_stage7.py`
- Create: `docs/CAPD_PROACTIVE_STAGE4_STAGE7_SERVER_CN.md`

**Reuse boundary:** `configs/finals/capd_proactive_stage4.json` 和既有 Stage 4 代码可以提供 dataset、model、trainer、checkpoint 基础设施，但其中旧 grid 与选中值均不具有权威性。

**Search contract to define before server execution:**

- [ ] `L` 候选及其含义。
- [ ] `H` 候选及其与标签生成的关系。
- [ ] `K` 候选及其与 Stage 3 `b_max` 的合法性约束。
- [ ] `lambda` 候选与损失聚合规则。
- [ ] 模型结构、隐藏维度、层数、dropout/regularization 候选。
- [ ] learning rate、batch size、epoch、early stopping。
- [ ] 三个训练 seed。
- [ ] 六 workload Validation 聚合指标和确定性 tie-break。
- [ ] 资源上限、断点续跑和 candidate checkpoint 保留策略。

此处不预填最终值。若复用旧 grid，必须在新合同中说明每个候选的 Stage 7 Train/Validation 依据；不能因为旧实验曾使用它就直接冻结。

**Implementation requirements:**

- [ ] 输入 manifest 正好包含六个 Train 和六个 Validation。
- [ ] Test、Pressure、Stage 8 路径硬拒绝。
- [ ] 引用 Stage 3 `final_freeze.json` 与 SHA。
- [ ] 训练样本和 page/PC 词表只由六个 Train 构建。
- [ ] 六个 workload 训练一个统一模型，而非逐 workload 独立模型。
- [ ] Validation 可搜索超参数和选 checkpoint，但不可扩词表。
- [ ] 每个 seed 独立训练，不选择“最好 seed”代替 seed 汇总。
- [ ] 候选配置、输入、代码、词表和 checkpoint 全部记录 SHA。

**Tests first:**

- [ ] Test/Pressure 输入拒绝测试。
- [ ] Stage 3 freeze SHA 约束测试。
- [ ] Train-only vocabulary 测试。
- [ ] 六 workload manifest 完整性测试。
- [ ] 候选复现与 tie-break 测试。
- [ ] resume 身份不一致拒绝测试。

---

## 9. Task 5：本地生成并冻结 Pressure Test

**Precondition:** Stage 3 已正式 freeze；Task 3 测试通过。

**Local actions:**

- [ ] 验证 Stage 3 freeze 和 R1 SHA。
- [ ] 扫描原 Standard Test 中的全部连续候选窗口。
- [ ] 按冻结 Reactive-LRU 规则选择或判定不合格。
- [ ] 导出派生连续 CSV。
- [ ] 验证逐行一致性、行数和 source interval。
- [ ] 生成 manifest、lock 和 SHA 清单。

**Required outputs:**

```text
pressure_candidates.csv
pressure_window_manifest.json
pressure_test_lock.json
derived_pressure/<workload>/<capacity>.csv
local_pressure_bundle_manifest.json
verification.json
```

**Server acceptance:** 上传后服务器只重算 SHA、行数和逐行来源证明；不得重新扫描或替换窗口。

**No feedback gate:** Pressure 生成结果无论好坏，都不得反馈到 Stage 3/4。若合同本身存在代码错误，应修复工具、递增 Pressure run ID 并保留旧产物；不得改变冻结选择规则。

---

## 10. Task 6：服务器运行 Stage 4 搜索、训练与冻结

**Preconditions:**

- Stage 3 正式 freeze；
- Task 4 代码、测试和搜索合同完成；
- 服务器代码身份与本地审核版本一致。

**Server sequence:**

```text
preflight
  -> build Train-only vocabulary and datasets
  -> execute hyperparameter search
  -> aggregate six Validation workloads
  -> train/evaluate all required seeds
  -> select per-seed checkpoints by frozen rule
  -> verify candidate freeze
  -> human review
  -> explicit freeze
```

**Required outputs:**

```text
input_manifest.json
stage3_freeze_identity.json
vocabulary_manifest.json
dataset_manifest.json
search_contract.json
candidate_results.jsonl
validation_summary.json
selected_hyperparameters_candidate.json
checkpoint_manifest_candidate.json
verification.json
```

**Human gate:** Stage 4 runner 不得自动 freeze。人工确认 Validation 结果、seed 稳定性、OOV、训练完整性和选择规则后，才生成：

```text
selected_hyperparameters.json
checkpoint_manifest.json
final_freeze.json
```

**Failure rule:** 若搜索失败，只能在 Train/Validation 范围内修订 Stage 4 合同并使用新 run ID；不得读取 Standard/Pressure Test。

---

## 11. Task 7：生成并冻结 Stage 8 执行计划

**Target files:** 根据仓库现有 Stage 8 模块边界修改或新增 Stage 7 final runner、config 和测试。不得覆盖旧 Stage 8 目录。

**Plan inputs:**

- R1 raw/split identity；
- Stage 3 `final_freeze.json`；
- Stage 4 `final_freeze.json`；
- Train-only vocabulary manifest；
- 三个 seed checkpoint manifest；
- Standard Test lock；
- Pressure Test lock 和 eligibility manifest。

**Plan requirements:**

- [ ] 所有输入写入路径、SHA、schema 和 run ID。
- [ ] Standard 与 Pressure job 使用不同 `evaluation_track`。
- [ ] 两轨使用各自冻结 trace，但相同单元内所有策略共享容量、初始状态和 cost profile。
- [ ] CAPD seed job 与 deterministic baseline job 数量可复算。
- [ ] Standard 容量来自本轮冻结合同，不以旧实验可比为理由。
- [ ] Pressure 仅包含 eligible 单元，同时保留完整资格分母。
- [ ] `pressure_overhead_claims_allowed=false`。
- [ ] Test lock 后禁止改变参数、词表和 checkpoint。

**Gate:** 计划 verification 通过并人工审核 job matrix 后，才允许第一次正式 Test replay。

---

## 12. Task 8：服务器执行 Stage 8

### 12.1 Standard track

- [ ] 先验证完整未筛选 Test 的 lock 和 SHA。
- [ ] 对每个冻结 workload/capacity/strategy/seed 执行 replay。
- [ ] 保存逐 job metrics、日志和失败状态。
- [ ] 输出 OOV、fallback/emergency 路径和完整性指标。

Standard 用于总体性能和同步 replay 范围内的开销统计。真实异步前台延迟仍需独立实验。

### 12.2 Pressure track

- [ ] 只读取本地冻结且服务器验签通过的 Pressure CSV。
- [ ] 不重新选窗，不跳过不利 eligible 单元。
- [ ] 对全部冻结策略使用同一窗口、容量和初始状态。
- [ ] 将内存、推理时间、CPU、总运行时间、前台阻塞等开销字段置为 `null` 或明确 `not_reported_for_overhead_claim`。

Pressure 用于机制压力分析，不用于系统开销结论。

### 12.3 Resume 与失败

- [ ] 只在输入、配置、代码和 checkpoint SHA 完全一致时 resume。
- [ ] 任何身份变化都使用新 run ID。
- [ ] 不删除失败目录后假装首次成功。
- [ ] 最终结果必须列出缺失和失败 job。

---

## 13. Task 9：分轨聚合与最终结论

**Output layout:**

```text
artifacts/standard/
artifacts/pressure/
artifacts/integrity/
```

**Standard report:**

- 全部 workload/capacity 的配对结果；
- 三 seed 均值、方差和逐 seed 方向；
- paired difference 与 bootstrap confidence interval；
- OOV、fallback、失败/缺失 job；
- 不把点估计直接写成稳定优势。

**Pressure report:**

- eligible/total coverage；
- replacement decisions 与 Oracle headroom；
- proactive demotions、early reuse、free-frame 指标；
- weighted cost 和逐单元 paired results；
- 所有 ineligible 单元及原因；
- 明确禁止的开销字段不参与统计。

**Prohibited aggregation:**

- [ ] 不合并 Standard 与 Pressure macro average。
- [ ] 不与旧 Stage 8 或旧数据集做表格对比。
- [ ] 不只挑选 CAPD 获胜单元。
- [ ] 不把 Pressure 派生窗口称为独立采集 Test。
- [ ] 不把同步 replay 结论外推为真实异步延迟收益。

---

## 14. 完成定义

本计划只有在以下项目全部满足后才完成：

- [ ] R1 审计证据保持通过。
- [ ] Stage 3 在服务器完成、人工复核并正式 freeze。
- [ ] Pressure Test 按 Stage 3 合同在本地派生、冻结和验签。
- [ ] Stage 4 使用六个 Train/Validation 完成搜索、统一训练和人工 freeze。
- [ ] Stage 8 job matrix、Test lock、checkpoint 和全部 SHA 冻结。
- [ ] Standard 和 Pressure 两轨完成或完整披露失败项。
- [ ] 统计分析包含配对差值、seed 稳定性和不确定性。
- [ ] 最终材料不含旧实验性能对比。
- [ ] Pressure 未被用于算法内存、时间或系统开销结论。
- [ ] 结论严格限定在实际实验能够支持的证据范围内。
