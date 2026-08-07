# CAPD Stage10 正式异步仿真合同迁移设计

**Status:** design approved by user on 2026-08-06; implementation plan authorized; implementation and formal simulation are not authorized.

**Design target:** 在保留 Stage10A fixture 历史证据的前提下，新增一个只接受 Stage9 v2 r3 正式证据、可独立复算的确定性离散事件仿真合同。该合同证明的是“异步仿真已验证”，不是“真实系统异步性能已验证”。

## 1. 当前仓库审计结论

### 1.1 Stage9 r3 权威输入

唯一允许进入新 Stage10 合同的 Stage9 运行是：

`outputs/capd_proactive_stage9/stage9-overhead-v2-r3/`

当前仓库重新核验得到：

- `contract_id = CAPD-PROACTIVE-STAGE9-2.0`；
- `run_state.status = stage9_overhead_verified`；
- `run_state.stage10_entry_gate = satisfied`；
- `verification.status = stage9_overhead_verified`；
- `verification.stage10_entry_gate = satisfied`；
- `verification.stage8_entry_gate = satisfied`；
- `formal_b_max = 2`；
- result schema 的 21 个 required artifacts 全部存在；
- `verification.json.artifact_sha256` 实际包含 19 个映射，按 Stage9 合同排除 `verification.json` 和 `run_state.json`；恢复换行后 19/19 逐字节匹配；
- `measurement_checkpoint.status = completed`；
- checkpoint 包含 90 个唯一 completed cells，与 90 条 quality rows 的 `(track, workload, seed, b_max)` 集合完全一致；
- checkpoint 中 `b_max=2` 的 30 个 `(track, workload, seed)` 与 30 条 instrumentation jobs 完全一致；
- `raw_sha256` 同时匹配 `raw_latency_samples.csv` 和 verification 映射，`raw_partial_bytes` 也与文件长度一致；
- Linux CPU、perf required events、RSS、raw-to-summary 和 instrumentation verification 字段均为通过；
- Stage9 根目录没有 `manifest.json` 或 `SHA256SUMS`，这符合 Stage9 自身合同。

本设计绑定以下当前字节 SHA256：

| Artifact | SHA256 |
| --- | --- |
| `configs/finals/capd_proactive_stage9.json` | `642641d56fe52e3772bdaa0772d5c9fd250cc17976918ce99acd36d18a035922` |
| Stage9 result schema | `a07c1f4b192f76eff45d33fcbe6e37b325aec1a8648c5542538ead1b6ecda893` |
| `latency_summary.json` | `a4e28f6627b278258202d7ab71db72474f29f9e569ca432ebfc40e36baf12a09` |
| `verification.json` | `bc5dc7fc46247da5d2085dd302150361232ff0cd27cd9b911cb559072ef8635f` |
| `measurement_checkpoint.json` | `8ec44db66348aef3c65459ea48a3b87fc417d862102c85b4fe6bda958bf915d3` |
| `run_identity.json` 文件 | `3241d3df3b1ff701dcc0a571d05f0eacab8412becf1fc960e22df97ef433c2b2` |
| `run_identity.run_identity_sha256` | `cc662852fa7ee43209d721b5acaae062fb02d790f82e5245ec0511c443987454` |
| `run_state.json` | `c862886d04981e63569258e5605994c6bf14afca880122e39777903d30a3e1c3` |
| `stage8_compatibility_receipt.json` | `fc91e2538e6f88a65fc777ea79fc5d99581f47034a194507c599d58c2b6ba27d` |

Stage9 r1、v2-r1 和 v2-r2 不是该权威运行。新合同要求 `source_run_id` 精确等于 `stage9-overhead-v2-r3`，因此上述历史运行和任何其他目录都不能授权新 Stage10。

### 1.2 Stage9 r3 字节恢复

恢复记录位于：

`docs/superpowers/specs/2026-08-06-stage10-stage9-r3-byte-recovery.json`

恢复前后整树各记录 31 个文件的相对路径、长度和 SHA256。整树比较只允许并实际发现以下两个变化：

| Path | Before | After | 恢复动作 |
| --- | --- | --- | --- |
| `capacity_overhead.csv` | `12d0e041...e3a7`, 1031 bytes, LF | `aebc319f...02a`, 1038 bytes, CRLF | 仅将 7 个 LF 换为 CRLF |
| `perf/perf-stat.raw` | `2396689f...2df`, 299 bytes, CRLF | `aa946e5b...fd0`, 291 bytes, LF | 仅将 8 个 CRLF 换为 LF |

两次转换都在写入前于内存中精确命中 `verification.json` 的期望 SHA。UTF-8 文本内容不变。未修改 Stage9 `verification.json`、`run_state.json` 或任何测量字段。

根配置原为 `core.autocrlf=true`、`*.csv text eol=lf`，而 `.raw` 无显式规则。为防止下一次 Git checkout 再破坏正式字节，并避免将权威 CRLF 误报为 trailing whitespace，`.gitattributes` 对上述两个精确路径使用 `binary !eol`；其他文件的规则不变。

### 1.3 旧 Stage10A 和 Stage11A

`stage10-async-simulator-r1` 是 `CAPD-PROACTIVE-STAGE10-1.0` fixture。当前独立 verifier 仍返回 5 个 fixture results 和 12 个 manifest payloads 均通过，但其正式状态必须保持：

```text
mode = fixture
run_state.status = stage10_simulator_tests_passed
formal_gate.status = stage10_formal_blocked_by_stage9
stage10_formally_verified = false
```

现有 Stage11A 先要求 `config.mode == fixture`，再调用 Stage10A verifier，并将完整 fixture 固定解释为 `BLOCKED / stage10a_fixture_only`。缺失或篡改的 fixture 为 `NOT_VERIFIABLE`。本迁移不改变 Stage11A 的该行为，也不为 Stage11A 增加新合同的正向验收。

## 2. 新旧合同关系

### 2.1 冻结标识

本设计建议并冻结以下新标识，等待用户批准：

```text
contract_id                 = CAPD-PROACTIVE-STAGE10-2.0
config_schema_version       = capd_proactive_stage10_v2_0
result_schema_version       = capd_proactive_stage10_result_v2_0
run_identity_schema_version = capd_proactive_stage10_run_identity_v2_0
run_state_schema_version    = capd_proactive_stage10_run_state_v2_0
verification_schema_version = capd_proactive_stage10_verification_v2_0
manifest_schema_version     = capd_proactive_stage10_manifest_v2_0
stage9_receipt_schema       = capd_proactive_stage10_stage9_input_receipt_v2_0
evidence_mode               = deterministic_async_simulation
success_status              = stage10_async_simulation_verified
failure_status              = stage10_async_simulation_not_verified
stage9_gate_status          = stage10_stage9_input_verified
```

`stage10_async_simulation_verified` 的中文语义固定为“Stage10 确定性异步仿真已验证”。名称中不使用 `formally_verified`，避免与真实系统测量混淆。

### 2.2 双向不兼容

- v1 fixture 只允许 `CAPD-PROACTIVE-STAGE10-1.0`、`mode=fixture` 和 `fixture_results.jsonl`；它不能被 v2 verifier 升级。
- v2 只允许新 contract/schema、`evidence_mode=deterministic_async_simulation` 和 `simulation_results.jsonl`；它不能被 v1 fixture verifier 接受。
- 新 runner/verifier 通过 `config.json.contract_id` 精确分派；未知版本立即失败。
- `stage10-async-simulator-r1` 不修改、不补字段、不重算、不覆盖。
- 新 run id 冻结为 `stage10-async-simulator-v2-r1`。目录已存在时拒绝覆盖或续写。

## 3. 证据状态机

新合同将四件事分开：

```text
Stage9 input audit
  -> stage10_stage9_input_verified
  -> parameter and scenario preflight
  -> stage10_async_simulation_running
  -> stage10_async_simulation_completed
  -> independent recomputation
  -> stage10_async_simulation_verified
```

规则如下：

1. Stage9 input gate 通过只产生 Stage10-owned input receipt，不产生 Stage10 成功状态。
2. Stage9 gate、配置、schema、设计绑定、迁移参数或 run-id preflight 任一失败时，不创建目标输出目录。
3. 输出目录创建后发生的执行或验证失败写 `stage10_async_simulation_not_verified`，该 run id 不得续写或升级。
4. 成功状态必须同时满足：仿真已执行、全部 artifacts 已落盘、manifest/SHA256SUMS 通过、结果可从绑定输入和配置独立重算、解释边界字段通过。
5. verifier 是只读的。它不修改 `verification.json`、`run_state.json` 或上游 artifacts。
6. CLI 参数不能直接设置或升级状态。

## 4. Stage9 输入门禁

### 4.1 目录和身份

门禁只接受仓库内、`outputs/capd_proactive_stage9` 的直接子目录，且 basename 精确为 `stage9-overhead-v2-r3`。所有 required paths 在解析符号链接和 `..` 后必须仍位于该 run root 内。

门禁从可信仓库路径读取 Stage9 config 和 result schema，不接受调用方传入 receipt。Stage10 在验证原始 Stage9 artifacts 后自行生成 `stage9_input_receipt.json`。

必须校验：

- Stage9 config 文件 SHA、contract/schema 和 result schema SHA；
- `run_identity.json` 的 run id、config SHA、result schema SHA、formal `b_max=2`、Stage8/Stage4 bindings、runtime binding 和内部 `run_identity_sha256`；
- `resolved_config.json` 与可信 config、run id 和 run identity 一致；
- `run_state.json` 的 contract/schema/status、`stage10_entry_gate=satisfied`、`failure=null` 和 completed steps；
- `verification.json` 的 contract/schema/status、两个 entry gates、Linux CPU、perf、RSS、raw-to-summary、instrumentation、Stage8 compatibility、Test isolation、formal b_max 和 interpretation boundary；
- `stage8_compatibility_receipt.json` 的 Stage8 r5 contract/status/counts、job/statistics、Stage4 SHA chain、read-only 和 Test isolation；
- `environment.json`、perf、memory/RSS、capacity、quality、instrumentation、server test receipt 和 preflight 的 Stage9-specific fields；
- `verification.json.artifact_sha256` 的 key set精确等于 Stage9 result schema required artifacts 减去 `verification.json` 和 `run_state.json`，当前应为 19 项；
- 19 个路径逐项进行 path containment、存在性和 SHA256 重算；不要求根 manifest/SHA256SUMS。

### 4.2 Measurement checkpoint

`measurement_checkpoint.json` 是 v2 Stage10 required input，必须检查：

```text
schema_version = capd_proactive_stage9_measurement_checkpoint_v2_0
status = completed
failure = null
raw_partial_path = raw_latency_samples.csv
raw_sha256 = SHA256(raw_latency_samples.csv)
raw_partial_bytes = file length
quality_row_count = 90
instrumentation_audit_count = 30
completed_cells count = 90
```

completed cells 必须唯一，并与 `quality_summary.rows` 的 `(track, workload, seed, b_max)` 集合相等。其 `b_max=2` 投影必须与 30 条 instrumentation job identities 相等。计数还必须符合可信 Stage9 config 的 `measurement_matrix`。

任一 SHA、字段、集合、计数、路径或身份不匹配均 fail closed。不能改成忽略换行的 semantic hash。

## 5. `T_inference_ns` 派生和绑定

新配置不保存一个无来源的自由常量。runner 必须从已通过门禁的 Stage9 artifact 读取：

```text
source_run_id = stage9-overhead-v2-r3
source_artifact = latency_summary.json
formal_b_max = 2
field = by_b_max["2"].stages.total_round_latency_ns.mean
original_value = 2252304.4582606885
sample_count = 182394
```

JSON 浮点使用十进制 parser 读取，禁止先变成二进制 float。整数规则冻结为 `Decimal ROUND_HALF_UP to integral nanoseconds`。因此主值为：

```text
T_inference_ns = 2252304
```

该时间边界是 Stage9 的 user-space Linux CPU 同步 CAPD decision round，从 watermark check 开始到 top-b result；它排除 page migration、Replay state update、invariant checks、quality metrics 和 artifact serialization。不得写成内核端到端延迟。

预声明的 inference sensitivity 只用于分析，不用于选择主值：

| Source statistic | Original | Converted ns |
| --- | ---: | ---: |
| p50 | 2192418 | 2192418 |
| mean, primary | 2252304.4582606885 | 2252304 |
| p95 | 2625519 | 2625519 |
| p99 | 2938056.360000004 | 2938056 |

每个 timing provenance artifact 必须同时保存 latency summary SHA、Stage9 verification SHA、measurement checkpoint SHA、run identity 文件 SHA、内部 run identity SHA、Stage9 config SHA、source field、original decimal、conversion rule 和 sample count。

## 6. `T_migration_ns` 模拟参数边界

本仓库没有真实 NVM 平台测量。Cost profile 的 demotion 权重 `10` 不是时间，绝不参与 `T_migration_ns` 派生。

为避免伪装硬件知识，本设计使用相对于主 `T_inference_ns` 的预声明无量纲场景，而不是声称某个 NVM 设备实测值。冻结建议为：

| Scenario | Ratio to reference inference | `T_migration_ns` | Role |
| --- | ---: | ---: | --- |
| `migration-ratio-0p01` | 0.01 | 22523 | sensitivity only |
| `migration-ratio-0p10` | 0.10 | 225230 | reference simulator scenario |
| `migration-ratio-1p00` | 1.00 | 2252304 | sensitivity only |

转换仍使用 Decimal `ROUND_HALF_UP`。这些值的 source 固定写为 `predeclared_simulator_scenario_ratio_not_hardware_measurement`。设计批准等于批准这组模拟场景，但不把它们升级为真实 NVM 测量。任何运行后根据 Stage10 结果改变 reference 或范围的行为都被禁止。

在本设计未批准、设计文档 SHA 未写入新配置、或者 migration scenario binding 缺失时，正式执行 preflight 必须失败且不得创建输出目录。schema、parser、gate 和 synthetic tests 可以在后续获批实施中完成，但不能生成 v2 正式仿真结果。

## 7. 场景矩阵和仿真语义

### 7.1 固定状态参数

新 v2 场景仍是抽象 DRAM/NVM-tier 模型，不是硬件容量复刻。冻结建议：

```text
b_max = 2
b_t_reference = 2
dram_capacity_frames = 64
initial_free_frames = 16
F_low = 16
F_target = 24
K = 8
candidate_source = lru_tail
seed = 3136859
simulation_horizon_ns = 10000000000
```

这些容量和水位来自既有 Stage10A 抽象模型结构，只作为 v2 simulator scenario parameters。它们不声明真实机器页数或容量。

事件优先级、`reserved_page_ids` 四集合互斥、容量不变量、LRU tail、MRU admission、FIFO blocking、emergency fallback 和 `null`/`N/A` 语义沿用已验证引擎，不因合同迁移改变。

### 7.2 Timing profiles、arrival profiles 和比较通道

Reference timing profile 为 `mean inference + migration-ratio-0p10`。`0.10` 没有硬件标定依据；reference 只表示预先冻结的报告基准，不表示最真实、典型或推荐的 NVM 参数。Sensitivity 采用 one-factor-at-a-time：

- inference sensitivity：p50、p95、p99，migration 固定 reference 值；
- migration sensitivity：0.01 和 1.00，inference 固定 mean；
- 不生成并从全交叉矩阵中选择“最好”结果。

固定 arrival profiles 为：

- uniform load ratios：`0.5, 0.8, 1.0, 1.2`；
- burst：完整 10 秒 horizon 上 base ratio `0.5`，`[2s,3s)` 使用 `2.0x`，`[6s,7s)` 使用 `1.6x`，区间外保留 base flow。

`mu_demote = b_t_reference / (T_inference + b_t_reference * T_migration)` 只用于构造场景负载；实际每轮 `b_t` 继续由 `min(b_max, F_target-F_t, candidate_count)` 计算并记录。

为避免 timing 与绝对到达率同时变化，场景矩阵必须拆成两个显式通道。

#### `fixed_arrival`

这是正式 timing sensitivity 的主通道。每个 arrival profile 只使用 reference timing profile 的 `mu_demote` 生成一次到达流。随后所有 timing profiles 复用完全相同的 `(timestamp_ns, page_id)` 序列，不得重新采样、重新计算 period 或改变 phase。

因此同一 arrival profile 内，跨 timing profile 只改变 `T_inference_ns` 或 `T_migration_ns`。queue、fallback、blocking 和 utilization 的跨 profile 差异可解释为冻结仿真模型内的 timing sensitivity，但仍不是现实硬件因果测量。

#### `capacity_normalized`

这是补充压力曲线通道。每个 timing profile 使用自己的 `mu_demote` 生成 `0.5/0.8/1.0/1.2` 和 burst 到达流，所以绝对到达率随 timing profile 改变。该通道只允许比较相对于各自模型容量的压力响应，不允许把跨 profile 差异解释为纯 timing sensitivity。

六个 timing profiles、五个 arrival profiles 和两个通道构成 60 条预声明结果。不得根据结果删除通道、选择 profile 或改变 reference。

#### Arrival identity 和结果字段

到达流 SHA 固定计算为：将按 `(timestamp_ns, page_id)` 排序的完整事件数组序列化为 UTF-8 canonical JSON，使用 `sort_keys=true`、无额外空白，再计算 SHA256。`fixed_arrival` 中同一 arrival profile 的六个 timing profiles 必须具有相同 `arrival_stream_sha256`、timestamp 和 page ID。

v2 result schema 的每条结果必须在 `derived` 中要求 `comparison_channel`、`timing_profile_id` 和 `arrival_profile_id`。`comparison_channel` 只允许 `fixed_arrival` 或 `capacity_normalized`。其 `derived.arrival_binding` 必须要求：

```text
arrival_rate_basis
arrival_reference_profile
arrival_stream_sha256
absolute_arrival_rate
normalized_load_ratio
cross_profile_comparison_allowed
cross_profile_comparison_scope
```

字段语义冻结为：

- `arrival_rate_basis` 枚举为 `reference_profile_fixed` 或 `per_profile_mu_demote`；
- `comparison_channel=fixed_arrival` 必须与 `arrival_rate_basis=reference_profile_fixed` 成对；`comparison_channel=capacity_normalized` 必须与 `arrival_rate_basis=per_profile_mu_demote` 成对；
- `arrival_reference_profile` 在 `fixed_arrival` 中固定为 reference timing profile id，在 `capacity_normalized` 中为当前 timing profile id；
- `arrival_stream_sha256` 为上述 canonical event array SHA256；
- `absolute_arrival_rate` 是 exact-rational rate object，禁止使用舍入浮点。Uniform 形式为 `{kind: uniform, rate: {numerator, denominator, unit}}`；burst 形式为 `{kind: piecewise, base_rate: {...}, intervals: [{start_ns, end_ns, rate: {...}}]}`。每个 rate 均为不可约分数，`unit` 固定为 `pages_per_ns`；
- `normalized_load_ratio` 同样区分 uniform 和 piecewise。Uniform 形式为 `{kind: uniform, ratio: {numerator, denominator}, reference}`；burst 形式为 `{kind: piecewise, base_ratio: {...}, intervals: [{start_ns, end_ns, ratio: {...}}], reference}`。`reference` 必须明确是当前 timing profile 的 `mu_demote`；因此 `fixed_arrival` 下该比值会随 timing profile 改变，而 `capacity_normalized` 下等于预声明 load ratio 或 burst multiplier 后的分段 ratio；
- `cross_profile_comparison_allowed=true` 只用于 `fixed_arrival`，其 scope 固定为 `timing_sensitivity_within_simulator`；
- `capacity_normalized` 必须写 `cross_profile_comparison_allowed=false`，scope 固定为 `relative_capacity_pressure_only`。该 false 专指禁止纯 timing 因果比较，不禁止报告各 profile 的归一化压力曲线。

## 8. 输出目录和 run identity

获批实现后的新目录为：

`outputs/capd_proactive_stage10/stage10-async-simulator-v2-r1/`

计划 artifacts：

```text
config.json
run_identity.json
stage9_input_receipt.json
timing_provenance.json
scenario_matrix.json
simulation_results.jsonl
event_model.md
parameters.md
test_log.txt
test_evidence.json
report.md
verification.json
run_state.json
manifest.json
SHA256SUMS
README.md
```

Run identity 至少绑定：contract/schema、run id、Git commit/dirty flag、v2 module/runner/config/result schema SHA、共享 simulator engine SHA、Stage9 input receipt SHA、Stage9 config/run identity/verification/checkpoint/latency SHA、设计文档 SHA、scenario matrix SHA、conversion rule 和 evidence mode。

`scenario_matrix.json` 必须绑定两个 comparison channels、reference timing profile、60 个稳定排序 scenario ids，以及五个 reference arrival streams 的 canonical SHA。`simulation_results.jsonl` 的每条结果必须通过 v2 result schema 对 channel/profile identity 以及 `derived.arrival_binding` 的类型、枚举、分数约分、reference 和 cross-profile 权限做校验。

Manifest 规则与 v1 的完整性模式相似但 schema 不同：`manifest.json` 排除自身和 `SHA256SUMS`；`SHA256SUMS` 包含 manifest、排除自身。v2 verifier 要求精确文件集合并拒绝额外文件、路径逃逸、缺失和篡改。

## 9. Runner 和 verifier 分派

### 9.1 文件边界

必须保留不变：

- 历史 Stage10A 设计、实施计划、v1 config、v1 result schema；
- `outputs/capd_proactive_stage10/stage10-async-simulator-r1/`；
- Stage8/Stage9 历史运行和冻结 checkpoint；
- Stage11A 设计、配置、源码、测试和输出。

计划扩展：

- `scripts/run_capd_proactive_stage10.py`：仅增加严格的 contract dispatch，并把现有逻辑封装为 v1 fixture branch；
- 不改变 v1 branch 的成功条件和结果重算规则。

计划新增：

- `qmap/proactive_stage10_v2.py`：v2 config、Stage9 read-only gate、timing provenance、scenario matrix 和 v2 contract；
- `scripts/run_capd_proactive_stage10_v2.py`：v2 preflight、执行、artifact assembly 和 read-only verifier；
- `configs/finals/capd_proactive_stage10_v2.json`；
- `configs/finals/capd_proactive_stage10_result_schema_v2.json`；
- `tests/test_capd_proactive_stage10_v2.py`；
- v2 protocol/status 文档；
- 设计批准后另建 v2 implementation plan，不修改历史 Stage10A plan。

v2 可以复用 v1 中已覆盖测试的事件引擎类型和纯仿真函数，但不能复用 v1 的 config validator、旧 Stage9 gate、fixture interpretation 或 v1 run-state writer。v2 wrapper 必须重写 evidence interpretation，并在 run identity 中绑定共享引擎 SHA。

### 9.2 独立验证

v2 verifier 必须：

1. 按 contract id 分派并拒绝 v1/未知合同；
2. 重新执行 Stage9 gate，不信任已保存 receipt 自报状态；
3. 从 Stage9 latency artifact 重新派生 timing values；
4. 从 config 和 timing provenance 重新展开 scenario matrix；
5. 对每个 scenario 重新运行确定性仿真并逐字段比较 `simulation_results.jsonl`；
6. 验证 manifest、SHA256SUMS、test evidence、run identity、状态机和解释边界；
7. 确认没有字段声称真实 NVM、内核并发、真实 foreground end-to-end latency 或真实系统异步性能。

## 10. Fail-closed 规则

以下任一情况都不能产生 `stage10_async_simulation_verified`：

- Stage9 run id 不是精确 r3，或指向 r1/v2-r1/v2-r2；
- Stage9 config、schema、run identity、run state、verification、checkpoint 或任一 artifact SHA 不匹配；
- Stage9 required path 逃逸、缺失或出现意外 artifact key set；
- 误要求 Stage9 root manifest/SHA256SUMS，或反过来忽略 Stage9 自身 verification map；
- measurement checkpoint 缺失、篡改、未完成、raw SHA/长度不一致，或 90/30 identity sets 不一致；
- `T_inference_ns` 不是从绑定 Stage9 decimal field 按冻结规则派生；
- 使用 fixture 的 2000 ns，或把 Cost demotion weight 当作 `T_migration_ns`；
- migration scenario 未获设计批准、design SHA 未绑定或 reference 被运行结果改变；
- `fixed_arrival` 在不同 timing profiles 中重新生成、改变 timestamp/page ID 或产生不同 stream SHA；
- 把 `capacity_normalized` 结果标记为可作 timing sensitivity 因果比较；
- Stage9 gate 通过后没有执行仿真，却写 Stage10 success；
- v1/v2 verifier 交叉接受；
- preflight 失败后创建目标目录；
- run id 已存在、失败 run 被续写、历史输出被覆盖；
- manifest/SHA、结果重算、schema、状态或 interpretation boundary 不一致。

## 11. TDD 验收矩阵

实施计划必须按 TDD 拆分并至少覆盖：

- Stage9 r3 完整 gate 通过；恢复任一换行错误后 gate 失败；
- checkpoint 缺失、内容篡改、SHA 篡改、count/set mismatch 失败；
- 旧 Stage9 config SHA 和 r1/v2-r1/v2-r2 失败；
- 缺少 Stage9 root manifest/SHA256SUMS 不构成失败；
- `T_inference_ns` 来自 Stage9 mean，Decimal conversion 可重复，fixture 2000 ns 被拒绝；
- migration approval/design binding 缺失时不创建正式输出；
- `fixed_arrival` 同一 arrival profile 在全部 timing profiles 中 timestamp、page ID 和 `arrival_stream_sha256` 完全一致；
- `fixed_arrival` 的绝对到达率固定而各 timing profile 的 `normalized_load_ratio` 正确变化；
- `capacity_normalized` 使用各 profile 自己的 `mu_demote`，并强制 `cross_profile_comparison_allowed=false`；
- arrival binding 的 exact rational rate、reference profile、stream SHA、comparison scope 缺失或篡改时失败；
- comparison channel 与 arrival-rate basis 组合错误时失败；
- Stage9 gate pass 不自动产生 Stage10 success；
- v1 fixture 与 v2 双向不兼容，三种 evidence mode 不混淆；
- 原有 event priority、reservation、capacity、LRU/MRU、blocking null/N/A 测试继续通过；
- run-id immutability、失败 preflight、manifest、SHA256SUMS 和独立结果重算；
- 测试前后 Stage8、Stage9 r3 和旧 Stage10A 整树不变，其中本次已记录的两项 Stage9 字节恢复作为新基线。

## 12. 可支持和不可支持的论文结论

新合同通过后可支持：

- 在冻结的抽象状态、到达流、Stage9 同步 decision-round timing 和预声明 migration scenario 下，确定性离散事件仿真的 queue、fallback、blocking、utilization、free-frame exhaustion 和 demotion-rate 结果；
- 仿真结果可从绑定输入和代码独立重算；
- `fixed_arrival` 通道在完全相同到达事件流下的模拟 timing sensitivity；
- `capacity_normalized` 通道相对于各 timing profile 自身服务能力的补充压力曲线。

论文和报告不得把 `capacity_normalized` 的跨 timing profile 差异写成纯 timing sensitivity，也不得把 `migration-ratio-0p10` 写成典型、真实、最优或硬件标定参数。`fixed_arrival` 的 timing sensitivity 也只能表述为冻结离散事件模型内的条件性结果。

仍不可支持：

- 真实 NVM 页面迁移延迟或带宽；
- 真实内核后台线程、锁竞争、调度、DMA 或并发行为；
- 真实前台端到端延迟、吞吐或 tail latency；
- 真实系统 CPU/RSS 之外的异步整合成本；
- Stage11 正向异步结论或真实系统 `formally_verified` 状态。

报告必须把“Stage9 同步 CPU 测量”“Stage10 确定性异步仿真”和“未来真实系统异步测量”分成三类 evidence mode。

## 13. Stage11A 暂时不兼容边界

Stage11A v1.0 当前只识别完整 Stage10A fixture 并返回负向 `BLOCKED`。本任务不修改其代码、schema、状态集或报告。即使 v2 产生 `stage10_async_simulation_verified`，Stage11A v1.0 也必须拒绝或返回 `NOT_VERIFIABLE`，不得自行推断正向语义。

Stage11 正向迁移必须另建设计，显式绑定 `CAPD-PROACTIVE-STAGE10-2.0`、v2 artifacts、解释边界和它自己的新 schema version。

## 14. 自审和审批门禁

自审结论：

- 新旧 contract、schema、run identity 和文件名均分离；
- Stage9 input gate、simulation execution、independent verification 和 interpretation boundary 均分离；
- Stage9 r3 的真实 artifact contract 被保留，没有发明 root manifest/SHA256SUMS；
- `T_inference_ns` 有完整来源链，`T_migration_ns` 明确为非测量 scenario；
- timing sensitivity 使用 reference-generated `fixed_arrival`，与按各自容量生成的 `capacity_normalized` 压力曲线分离；
- Stage10A 和 Stage11A 历史边界不被升级；
- 未发现阻止进入实施计划的未解决 P1 合同矛盾。

用户已明确批准本设计及其中 migration scenario、状态名、schema 名、新 run id 和 60 条双通道场景矩阵。当前仅授权编写和自审独立实施计划；在实施计划再次获得明确批准前，不得修改 Stage10 实现或生成正式仿真结果。
