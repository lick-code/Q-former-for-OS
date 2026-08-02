# CAPD Stage 7 数据链与最终实验修复流程指南

## 0. 文档状态与目标

本文档定义 CAPD 最终实验的当前唯一流程。此前以固定水位、固定模型超参数和旧 checkpoint 为前提的修复方案已经废止，不再作为执行依据。



最终目标是：

1. 只用六个 Stage 7 Train/Validation （所在路径--dataset\raw_traces\capd_proactive_stage7\stage7-local-collection-r1）重新选择控制器、容量和模型超参数；
2. 用六个 Train 训练一个统一 CAPD，用六个 Validation 选择 checkpoint；
3. 在未参与选择的完整 Standard Test 上评测一般表现；
4. 在按冻结规则派生的连续 Pressure Test 上评测有替换压力时的机制表现；
5. Standard 与 Pressure 分开报告，不与任何旧实验结果进行性能对比。

工程实现计划见：

`docs/superpowers/plans/2026-08-01-capd-stage7-refit-pressure-repair.md`

---

## 1. 为什么必须重跑 Stage 3 和 Stage 4

旧 Stage 8 使用了老 trace 上选出的参数与 checkpoint，却在 Stage 7 新 trace 上评测。该数据链导致身份特征大面积 OOV，同时旧的容量、水位和批量机制也不适合 Stage 7 trace 的工作集与页面进入强度。

因此，本轮不是在旧参数下简单重训，而是分两层重新校准：

```text
Stage 3：选择工作集定义、窗口、容量、水位和批量控制机制
Stage 4：在 Stage 3 冻结合同下选择 L、H、K、lambda、模型结构及训练配置
```

Stage 3 和 Stage 4 的选择数据只能来自 Stage 7 Train/Validation。Test、Pressure Test、旧 Stage 8 结果和旧 checkpoint 均不得参与选择。

---

## 2. 唯一有效的数据流

```text
R1 原始 trace 与 SHA 审计（已完成）
  |
  v
Stage 3 服务器校准
  - 只读六个 Train/Validation
  - 搜索 working set、窗口、容量、水位、b_max
  - Reactive-LRU / Proactive-LRU / Oracle 门禁
  |
  v
人工复核 Stage 3 候选并显式 freeze
  - final_freeze.json
  - pressure_generation_contract.json
  |
  +-------------------------------+
  |                               |
  v                               v
本地派生 Pressure Test             服务器实施并运行 Stage 4
  - 只按冻结合同扫描 Test           - 只读六个 Train/Validation
  - 连续时间片，不改访问内容         - 搜索模型与训练超参数
  - 冻结来源区间与 SHA              - 训练统一 CAPD
  |                               - Validation 选 checkpoint
  |                               |
  +---------------+---------------+
                  v
          冻结 Stage 8 执行计划
          - Standard Test
          - Pressure Test
                  |
                  v
          服务器执行 Stage 8
                  |
                  v
          分轨聚合、统计和结论
```

Stage 3 freeze 是不可逆选择边界。Pressure 派生后，禁止根据 Pressure 是否好看返回 Stage 3 或 Stage 4 调参；如果合同执行正确但某 workload 没有合格窗口，应如实标记 `pressure_eligible=false`。

---

## 3. 参数状态：候选不等于冻结值

以下旧值不再是最终参数：

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

它们可以出现在历史文件、旧实现或搜索候选中，但不得写入最终实验合同，除非新 Stage 3/4 在 Stage 7 Train/Validation 上独立选中这些值。

### 3.1 Stage 3 当前搜索空间

权威配置：

`configs/finals/capd_proactive_stage3_stage7_calibration.json`

当前搜索包括：

```text
window_records = 100000 / 300000 / 500000
W_ref quantile = 0.50 / 0.75 / 0.90
r_pressure = 0.05 / 0.10 / 0.15 / 0.20
D_min = 8
alpha = 0.05 / 0.10 / 0.15 / 0.20
beta = 0.4 / 0.5 / 0.6
b_max = 1 / 2 / 4 / 8
```

水位按容量动态计算：

```text
F_target(D) = clamp(round(alpha * D), 2, 16)
F_low(D) = max(1, round(beta * F_target(D)))
F_target(D) / D <= 0.25
```

配置中的 `standard_capacity.ratios=[0.20,0.40,0.60]` 当前只属于 Stage 3 的参考 profile 输入，不能解释为为了与旧实验对比，也不能自动成为最终 Stage 8 容量矩阵。最终容量必须由本轮 Stage 3 freeze 和后续 Stage 8 合同明确生成。

Stage 3 内部暂用的候选集大小、历史长度和 Oracle 标签权重只服务于控制器校准与上界审计，不自动冻结为最终 Stage 4 模型超参数。

### 3.2 Stage 4 待建立搜索合同

新 Stage 4 必须在运行前建立 Stage 7 专用配置，至少明确搜索或固定依据：

- `L`：候选历史长度或特征时间尺度；
- `H`：预测范围；
- `K`：候选页集合大小；
- `lambda`：标签或损失权重；
- 模型结构、隐藏维度、层数和正则化；
- 学习率、batch size、epoch 与 early stopping；
- 三个训练 seed 和 checkpoint 选择规则。

现有 `configs/finals/capd_proactive_stage4.json` 及旧 Stage 4 代码只能作为可复用的搜索基础设施，不能作为本轮冻结参数的证据。任何最终值都必须由六个 Stage 7 Train/Validation 产生。

---

## 4. 不可违反的数据边界

### 4.1 原始 trace 只读

允许：

- 校验原始文件和 split 的 SHA；
- 按既有时间顺序读取 Train/Validation；
- 在 Stage 3 freeze 后，从原 Test 复制一个连续区间作为 Pressure Test；
- 保存来源文件、起止索引、行数和派生文件 SHA。

禁止：

- 修改 PC、Address、RW 或时间顺序；
- 删除不利访问、复制访问、重排或合成访问；
- 为适配模型而改变 workload 行为；
- 把派生 Pressure Test 宣称为独立重新采集的 Test。

统一表述：

> Pressure Test 是从真实采集 trace 中，按照 Stage 3 预先冻结的、只依赖 Reactive-LRU 压力统计的规则派生出的连续时间片。

### 4.2 Test 隔离

Stage 3 和 Stage 4 均禁止：

- 读取 Standard Test 或 Pressure Test；
- 使用 Test loss、准确率、weighted cost 或 OOV 选择参数；
- 使用 Test 扩词表、选择 seed 或 checkpoint；
- 根据 Test 结果改变 workload、容量、水位或 Pressure 资格规则。

Stage 3 freeze 后允许本地工具按 `pressure_generation_contract.json` 访问 Test，但该访问只用于生成已冻结的 Pressure 轨道，不得反馈到 Stage 3/4。

### 4.3 旧产物的地位

旧输出可以留在磁盘上用于追溯，但必须从本轮正式流程中隔离：

- 不参与参数选择；
- 不作为 checkpoint 来源；
- 不进入最终图表或汇总表；
- 不与新结果做性能高低对比；
- 不用于论证本轮方法改善。

最终报告只描述当前最终方法和 Stage 7 数据链上的新结果。

---

## 5. Stage 3：服务器重新校准控制器

### 5.1 当前实现

已实现文件：

```text
configs/finals/capd_proactive_stage3_stage7_calibration.json
qmap/proactive_stage3_stage7.py
scripts/run_capd_proactive_stage3_stage7.py
tests/test_capd_proactive_stage3_stage7.py
docs/CAPD_PROACTIVE_STAGE3_STAGE7_SERVER_CN.md
```

权威 run ID：

```text
stage3-stage7-calibration-r2
```

服务器执行命令、断点续跑和产物检查以 `docs/CAPD_PROACTIVE_STAGE3_STAGE7_SERVER_CN.md` 为准，本文不复制可能漂移的命令。

### 5.2 输入与计算

Stage 3 正好读取：

```text
6 Train + 6 Validation + 0 Test
```

主要工作：

1. 对 Train 做连续 blocked calibration，Validation 保持独立；
2. 统计窗口 working set、page-entry、reuse 与 Reactive-LRU 替换压力；
3. 搜索容量、动态水位和 `b_max`；
4. 在相同 trace、容量和初始状态下运行 Reactive-LRU、Proactive-LRU 和 Oracle；
5. 检查压力覆盖、Oracle 非零优化空间、Validation 安全性和 Pareto 前沿。

### 5.3 Stage 3 人工冻结门禁

`all` 只能生成候选，不能自动冻结。必须先人工检查：

```text
pressure_coverage.json
oracle_headroom.json
validation_safety.json
pareto_frontier.json
selection_rationale.json
final_freeze_candidate.json
pressure_generation_contract_candidate.json
```

确认后才显式生成：

```text
final_freeze.json
pressure_generation_contract.json
```

若 Oracle headroom 全为 0、压力覆盖不足或 Validation 安全门禁失败，Stage 3 必须阻断。不得查看 Test 后补调参数。

---

## 6. Pressure Test：Stage 3 freeze 后在本地派生

### 6.1 派生合同

本地派生工具必须逐项读取 Stage 3 正式合同，而不是在脚本中再次硬编码：

- 冻结窗口长度和扫描步长；
- 每 workload 的冻结容量；
- 动态 `F_low/F_target`；
- 冻结 `b_max`；
- unique-page 与最小 replacement 资格规则；
- 只使用 Reactive-LRU 的确定性排序规则；
- 平局时的固定 tie-break。

选择过程中禁止使用 CAPD、TPP、Oracle、weighted cost、模型准确率或 Stage 8 结果。

### 6.2 冻结产物

至少生成：

```text
pressure_candidates.csv
pressure_window_manifest.json
pressure_test_lock.json
derived_pressure/<workload>/<capacity>.csv
local_pressure_bundle_manifest.json
```

每个派生文件必须能追溯到原 Test 的：

```text
source trace ID
source SHA256
start index
end index
row count
derived SHA256
Stage 3 contract SHA256
```

服务器只验签和读取本地冻结包，不得重新扫描、重选或再生成 Pressure 窗口。

### 6.3 Pressure 不是开销数据集

Pressure Test 只用于分析在明确页面替换压力下的策略行为，例如：

- DRAM hit、NVM read/write；
- demotion、early reuse；
- empty-frame exhaustion 与 minimum free frames；
- weighted cost 与 Oracle headroom；
- proactive cycle/round 和 replacement decisions。

Pressure Test 不得用于声称：

- 模型或 metadata 内存开销；
- 推理时间、CPU cycles 或总运行时间；
- 前台阻塞时间；
- 端到端系统开销。

这些开销只能来自未按压力筛选的 Standard Test、固定微基准或后续真实异步实验。同步 Replay 本身也不能证明异步后台执行或前台延迟收益。

---

## 7. Stage 4：本地改代码，服务器搜索和训练

### 7.1 实施前置条件

Stage 4 只有在下列条件成立后才能执行：

- Stage 3 已人工确认并正式 freeze；
- Stage 4 输入 manifest 只含六个 Train/Validation；
- Stage 4 配置引用 Stage 3 `final_freeze.json` 及 SHA；
- 新的 Stage 7 专用搜索空间、选择指标和 tie-break 已写入版本化配置；
- Test/Pressure 路径硬拒绝已实现并有测试。

### 7.2 训练与选择原则

Stage 4 必须：

- 用六个 Stage 7 Train 生成训练样本和 Train-only page/PC 词表；
- 训练一个覆盖六个 workload 的统一 CAPD；
- 用六个 Validation 完成模型超参数搜索和每个 seed 的 checkpoint 选择；
- 冻结后不扩展词表；
- 保存每个候选、seed、checkpoint、配置和输入的 SHA；
- 预先定义聚合指标与 tie-break，不手选“最好看的 seed”。

Stage 4 不得把 Pressure Test 作为 Validation，也不得因 Pressure 资格或 Stage 8 表现改模型。

### 7.3 Stage 4 输出

目标输出至少包括：

```text
stage4_input_manifest.json
stage4_search_contract.json
candidate_results.jsonl
validation_summary.json
selected_hyperparameters.json
checkpoint_manifest.json
final_freeze.json
verification.json
```

当前这些目标接口尚未实现。实施时必须使用新的 run ID，不得沿用旧 refit 计划中的占位 run ID。

---

## 8. Stage 8：两条独立 Test 轨道

### 8.1 执行前冻结

Stage 8 执行计划必须同时锁定：

- R1 原始数据身份及 SHA；
- Stage 3 freeze 及 SHA；
- Stage 4 模型配置、词表、checkpoint 及 SHA；
- Standard Test lock；
- Pressure Test lock；
- workload、容量、策略、seed 和 cost profile；
- 每条轨道允许报告的指标。

缺少任一锁文件或 SHA 不匹配时立即停止。

### 8.2 Standard 轨道

Standard Test 是未经压力窗口选择的完整时间隔离 Test。它用于回答：最终方法在正常、未筛选测试区间上的总体表现如何。

Standard 的容量矩阵必须由本轮正式合同定义，不能因“与旧实验可比”而保留某组容量，也不能在看过 Test 后调整。

### 8.3 Pressure 轨道

Pressure Test 只运行 `pressure_eligible=true` 的冻结单元。它用于回答：当确实存在页面替换机会和 Oracle headroom 时，控制器与模型能否有效利用这些机会。

未通过资格门禁的 workload/capacity 必须保留在资格汇总中，不能从分母或覆盖率报告中消失。

### 8.4 结果报告

必须分别输出：

```text
artifacts/standard/
artifacts/pressure/
```

禁止：

- 将两条轨道混成一个 macro average；
- 只报告有利的 Pressure 单元；
- 用 Pressure 结果回答开销问题；
- 与旧 Stage 8、旧 checkpoint 或旧数据集结果做性能比较；
- 由点估计直接声称稳定优势。

报告应包含配对差值、seed 波动、置信区间、压力覆盖率、OOV、Oracle headroom 和失败单元。证据只支持同步 Replay 时，结论也必须限定在同步 Replay。

---

## 9. 执行位置与可并行关系

### 9.1 本地执行

- 修改和评审 Stage 3/4/Pressure/Stage 8 代码；
- R1 原始 trace 审计（已完成）；
- Stage 3 freeze 后派生并冻结 Pressure Test；
- 生成来源清单和 SHA 包。

### 9.2 服务器执行

- Python 编译与测试；
- Stage 3 profile、search、select、verify；
- Stage 3 人工确认后的 freeze 命令；
- Stage 4 数据生成、词表、搜索、训练和 checkpoint 选择；
- Stage 8 Standard/Pressure Replay、聚合和统计。

### 9.3 依赖关系

严格串行：

```text
R1 -> Stage 3 run -> Stage 3 review -> Stage 3 freeze
Stage 3 freeze -> Stage 4
Stage 3 freeze -> Pressure generation
Stage 4 freeze + Pressure freeze -> Stage 8
```

可并行：

```text
Stage 3 freeze 后：
  本地派生 Pressure Test
  服务器运行 Stage 4
```

没有任何时间表或耗时承诺；是否继续只由产物门禁决定。

---

## 10. 失败处理

- Stage 3 没有合格候选：保留失败产物，重新审查 Train/Validation 上的机制假设；禁止用 Test 救场。
- 某 workload 没有 Pressure 窗口：标记 `pressure_eligible=false`，不修改 trace，不放宽规则。
- Stage 4 没有稳定模型候选：保留搜索结果，在 Train/Validation 范围内修订模型合同并使用新 run ID。
- SHA 或代码身份改变：原目录保持不动，递增 run ID，禁止跨身份 resume。
- Stage 8 单元失败：保留成功和失败清单，不用删目录重跑伪装首次成功。
- 任何选择规则发生变化：回到对应阶段重新冻结其下游全部产物，但不得改写历史产物。

---

## 11. 最终完成门禁

只有全部满足时，本轮最终实验才算完成：

- R1 身份审计通过；
- Stage 3 正式 freeze，控制器参数来自 Stage 7 Train/Validation；
- Pressure Test 按 Stage 3 合同派生并完成 SHA 冻结；
- Stage 4 正式 freeze，统一 CAPD 与 checkpoint 来自 Stage 7 Train/Validation；
- Stage 8 计划锁定全部输入、参数和 checkpoint；
- Standard 与 Pressure 两条轨道分别完成或明确列出失败单元；
- Test 没有参与任何参数、词表或 checkpoint 选择；
- 最终报告不含新旧实验性能对比；
- Pressure 未被用于时间、内存或端到端开销结论；
- 所有结论与同步/异步证据边界一致。
