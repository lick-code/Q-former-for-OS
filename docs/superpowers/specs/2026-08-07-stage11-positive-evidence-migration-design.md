# CAPD Stage11 正向证据迁移设计

## Material Passport

- Artifact Type: Experiment design specification
- Artifact ID: `capd-stage11-positive-evidence-migration-design-20260807`
- Version Label: `design-v3-approved`
- Origin Skill: `experiment-agent`
- Origin Mode: `plan`
- Verification Status: `DESIGN_REVIEW_APPROVED`
- Design Status: `DESIGN_APPROVED`
- Approved Scope: `IMPLEMENTATION_PLAN_ONLY`
- Implementation Authorization: `NOT_GRANTED`
- Formal Experiment Authorization: `NOT_GRANTED`
- Evidence Date: `2026-08-07`
- Repository HEAD Audited: `f8aad2c3f166ce900353c0b6061c7dc207d1200e`

`DESIGN_REVIEW_APPROVED` 只表示本文的设计边界已通过评审，不是实验结果、实现证据或正式验证回执。批准范围仅为编写独立实施计划；本文不授权修改源码、创建 execution authorization receipt、执行实验、冻结参数、生成生产结果、签发 final approval/final-status、提交或推送。

## 1. 目标与非目标

本文设计一个独立、版本化的 Stage11 正向证据迁移合同，使已经封存的 Stage9 v2-r3 和 Stage10 v2-r2 能被严格校验为 Stage11 的外部输入，同时确保它们不会自动授权 Stage11 执行，也不会自动把 Stage11 行升级为 `formally_verified`。

本文不修改 `CAPD-PROACTIVE-STAGE11A-1.0`，不修改任何 Stage8/9/10 实现或证据，不生成 Stage11 生产输出，不冻结 watermark 或 label-weight 网格，不训练模型，不选择 checkpoint，也不进入实施计划。

三个状态必须独立：

1. `authorized_external_input`：上游证据通过其自身合同，可被下游引用。
2. `stage11_execution_authorized`：独立的下游审批回执允许执行一个精确绑定的 Stage11 run。
3. `stage11_formally_verified`：该 run 完成、产物闭合、独立验证通过且最终批准回执存在。

允许的典型组合是：

```text
authorized_external_input = true
stage11_execution_authorized = false
stage11_formally_verified = false
```

Stage10 验证通过只满足第一项，绝不蕴含后两项。

## 2. 当前仓库审计

### 2.1 仓库与历史 Stage11A

现场审计结果如下：

| 项目 | 当前事实 |
|---|---|
| 分支 | `main` |
| HEAD | `f8aad2c3f166ce900353c0b6061c7dc207d1200e` |
| Stage11A 合同 | `CAPD-PROACTIVE-STAGE11A-1.0` |
| Stage11A 基线 | `22 tests`，全部 `OK` |
| Stage11 生产输出 | `outputs/capd_proactive_stage11/` 下无生产文件 |
| v1 执行授权 | `execution_authorized=false` |
| v1 网格状态 | `grid_frozen=false` |
| v1 正式主配置 | `b_max=2` |
| v1 分析批量网格 | `b_max=1/2/4`，仅 `analysis-only` |
| v1 未批准网格 | `watermark_candidates=[]`，`label_weight_candidates=[]` |
| v1 输入组件消融 | `CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState` 均为 `BLOCKED` |
| v1 Stage10 行为 | 只识别 Stage10A fixture；完整 fixture 为 `BLOCKED` |
| v1 正式状态 | validator 明确拒绝生成 `formally_verified` |

`qmap/proactive_stage11.py::load_stage8_rows()` 会加载 Stage8 r5 根清单中的全部 80 个 job；`scripts/run_capd_proactive_stage11.py::run_offline()` 对这些行逐一重算四个 Cost profile，没有 track 过滤。现场计数为 48 个 Standard job 和 32 个 Pressure job。因此 v1.0 是 dual-track candidate 路径，不能被静默解释为 Standard-only 正式汇总。

### 2.2 Stage8 r5

唯一 Stage8 权威输入仍是：

```text
outputs/capd_proactive_stage8/
  stage8-dual-track-20260804-r5-post-evidence-commit/
```

其合同为 `CAPD-PROACTIVE-STAGE8-2.0`，状态为 `stage8_sync_replay_verified`。Stage11A 已按 `job_id` 将 `artifacts/per_workload_raw.csv` 连接到 `jobs/<job_id>/result.json`，并校验 `job_manifest.json.result_sha256` 与 `semantic_result_sha256` 后读取整数 raw counters。该 join 规则必须进入 vNext，禁止通过浮点结果反推访问数。

### 2.3 Stage9 v2-r3

当前 Stage9 正向输入为：

```text
outputs/capd_proactive_stage9/stage9-overhead-v2-r3/
```

按 Stage9 自有合同现场审计得到：

- `run_state.json.status=stage9_overhead_verified`；
- `verification.json.status=stage9_overhead_verified`；
- `verification.json.stage10_entry_gate=satisfied`；
- Linux CPU、perf、memory 证据字段均通过；
- `formal_b_max=2`；
- `stage8_compatibility_receipt.json` 通过；
- `verification.json.artifact_sha256` 与 required artifacts 闭合；
- Stage11A 当前 gate 返回 `verified` 和 `formal_authorized=true`，这里只表示可作为外部输入。

关键 SHA 为：

| Artifact | SHA256 |
|---|---|
| Stage9 `run_state.json` | `c862886d04981e63569258e5605994c6bf14afca880122e39777903d30a3e1c3` |
| Stage9 `verification.json` | `bc5dc7fc46247da5d2085dd302150361232ff0cd27cd9b911cb559072ef8635f` |
| Stage8 compatibility receipt | `fc91e2538e6f88a65fc777ea79fc5d99581f47034a194507c599d58c2b6ba27d` |

Stage9 不采用 Stage10 式根目录 `manifest.json + SHA256SUMS` 作为主要合同。vNext gate 必须读取 Stage9 result schema 的 `required_run_artifacts`，校验 `verification.json.artifact_sha256`、Linux CPU/perf/RSS 证据和 Stage8 compatibility receipt，不得套用 Stage10 文件规则。

### 2.4 Stage10 v2-r2 sealed evidence

正式目录为：

```text
outputs/capd_proactive_stage10/stage10-async-simulator-v2-r2/
```

外部锚点为：

| Anchor | SHA256 |
|---|---|
| Generation freeze receipt | `3f4ce4ff71006777e18ded8d6b2e453c679b4a3d3ba2723d5892d7e310ac61f2` |
| Readiness receipt | `f7382904de7252ceb00159d155aa8bd4a4d423d718ae5b45ade916c911cf1bac` |
| Final-status receipt | `6570344bbcf273b57d1bd754b053e7979e5aa0c6edc35c25e528881c5d4288e7` |

Generation 关键 artifact SHA 为：

| Artifact | SHA256 |
|---|---|
| `run_identity.json` | `3c7eb24390a4f05a9339e467776765ea47f5fc146c5d89d59648b9d04698b908` |
| `run_state.json` | `c783c5d6a59383e07c6de80f6e40b4ebaeb0e996e365ec7fae8165402c6a29be` |
| `verification.json` | `fe903efc6b00d77df4b66bfaf3917a5302481deea3da98c24d01c9cacbaa56db` |
| `stage9_input_receipt.json` | `a4e7297d638f23eae5e16da543da1dd7b9e444162c51b745bb822c1c3286c317` |
| `scenario_matrix.json` | `a5b495048d90dabd51ac74f8bf1008568cde5a31ab85e5d03509b53b385c5e13` |
| `simulation_results.jsonl` | `e2cb520543e44b527f0e2db0f3076b388e0609f18ade1954f1f08d58cd0b138e` |
| `manifest.json` | `337e9866d80d5956b4479ac64f3a4e6cbc73c129e408cd32d7b7d28f21f5334f` |
| `SHA256SUMS` | `dba5ce4a96ed092adaa5feefdac31defec935b14f883f4677219c9317231735a` |

现场结构审计确认 generation 为 17 个 manifest payload、18 个 checksum 条目；readiness 为 10 个 payload、11 个 checksum 条目；final-status 为 6 个 payload、7 个 checksum 条目。三个阶段的文件集合、manifest 和 checksum 关系闭合，60 个 matrix row 与 60 个 JSONL result 的 `scenario_id` 完整、唯一且集合一致。

封存状态为：

- generation：`stage10_async_simulation_verified`；
- readiness：`stage10_release_readiness_verified`；
- final-status：`stage10_final_status_evidence_verified`；
- evidence mode：`deterministic_async_simulation`；
- readiness 封存的 dispatcher verifier 和 r2 native verifier 均为 `stage10_async_simulation_verified`；
- `synthetic_test_only=false`；
- `real_nvm_measurement_verified=false`；
- `kernel_behavior_verified=false`；
- `real_concurrency_verified=false`；
- `real_foreground_end_to_end_latency_verified=false`；
- `real_system_async_performance_verified=false`。

readiness 中的 `stage11_positive_migration_authorized=false` 是 Stage10 release 时的不可变快照。不得修改它，也不得把它解释为当前 Stage11 已获授权。新的授权只能来自独立的 Stage11 下游审批回执。

### 2.5 当前 HEAD 的 replay compatibility

Stage10 r2 `run_identity.json` 绑定生成 commit：

```text
b1019c3f4e3dbdfc8b699f40fdde6b8bf417c50a
```

在当前 HEAD `f8aad2c...` 使用精确 freeze SHA 运行 r2 native verifier，现场返回：

```text
Run identity does not match the complete independently constructed object.
```

现场逐项重算 `generation_source_manifest.json` 中 11 个源码文件的 SHA，结果为 `11/11` 完全匹配。失败不是 generation source set 内容变化，而是 live verifier 用当前仓库 revision 重建完整 run identity；sealed identity 绑定 `b1019c3f...`，当前 repository revision 为 `f8aad2c3...`。因此必须记录：

```text
generation_source_set_match = true
repository_revision_match = false
sealed_dual_verifier_attestation = verified
current_live_replay_compatibility = NOT_VERIFIABLE
```

对应 reason code 为 `repository_revision_differs_from_sealed_generation_revision`，不能使用 `current_source_identity_differs_from_generation_source`，也不能描述为 sealed evidence 被篡改。

设计必须区分：

- `sealed_dual_verifier_attestation`：由精确 readiness 外部锚点、release manifest/checksum 和封存字段证明发布时两个 verifier 均通过；
- `generation_source_set_match`：只比较 generation source manifest 中 11 个路径及其文件 SHA，不包含 Git revision；
- `repository_revision_match`：单独比较 sealed `run_identity.json.git.commit` 与当前 HEAD；
- `current_live_replay_compatibility`：当前 HEAD 能否再次执行历史 verifier；
- `artifact_integrity`：当前 sealed 文件是否与外部锚点一致。

Stage11 v2 gate 选择 sealed-attestation-only 语义：它不使用当前 HEAD 调用 Stage10 verifier 来重构历史 run identity，也不把当前 Git revision 注入 sealed identity。它从封存的 `run_identity.json` 读取 generation revision，校验该文件的精确外部锚点和整条 release chain，并以精确 readiness receipt 中的双 verifier 状态作为发布时证明。

正向授权判定只消费 sealed generation/readiness/final-status artifacts、三个外部 receipt anchor、封存 manifest/checksum 和封存双 verifier 状态。`generation_source_set_match` 与 `repository_revision_match` 是可选 current-tree compatibility audit 的两个独立输出，不参与 `authorized_external_input` 布尔判定，也不重写历史 identity。任一诊断为 false 时，`current_live_replay_compatibility=NOT_VERIFIABLE`；sealed input 仍按其外部锚点独立判断。

因此，`artifact_integrity` 与 `sealed_dual_verifier_attestation` 通过时，精确 Stage10 r2 可以成为 authorized external input。若 sealed readiness 中只有一个 verifier 通过，或任一 sealed anchor、封存 payload、封存 manifest/checksum 不匹配，则 positive gate 必须失败。当前 11 个源码 SHA 或 repository revision 的变化只能改变 compatibility audit，不能被误称为 sealed evidence 篡改。

## 3. vNext 版本策略

建议冻结新合同为：

```text
CAPD-PROACTIVE-STAGE11-2.0
```

建议的未来实现边界如下，本文不创建这些文件：

| 类别 | v1.0 历史路径 | v2 建议路径 |
|---|---|---|
| 合同模块 | `qmap/proactive_stage11.py` | `qmap/proactive_stage11_v2.py` |
| runner | `scripts/run_capd_proactive_stage11.py` | `scripts/run_capd_proactive_stage11_v2.py` |
| config | `configs/finals/capd_proactive_stage11a.json` | `configs/finals/capd_proactive_stage11_v2.json` |
| result schema | `configs/finals/capd_proactive_stage11a_result_schema.json` | `configs/finals/capd_proactive_stage11_v2_result_schema.json` |
| authorization schema | 不存在 | `configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json` |
| verification schema | v1 内建负向验证 | `configs/finals/capd_proactive_stage11_v2_verification_receipt_schema.json` |
| final approval schema | 不存在 | `configs/finals/capd_proactive_stage11_v2_final_approval_receipt_schema.json` |
| final-status schema | 不存在 | `configs/finals/capd_proactive_stage11_v2_final_status_evidence_receipt_schema.json` |
| release manifest schema | 不存在 | `configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json` |
| output root | `outputs/capd_proactive_stage11/` | `outputs/capd_proactive_stage11_v2/` |

不得在 v1 runner 中自动猜测合同版本，不得原地放宽 `audit_stage10_fixture()`，不得让 v2 schema 接受 v1 行。调用者必须显式选择 v2 runner；v2 只写新的 output root。所有 v1 文件、测试和历史 candidate artifact 保持字节和语义不变。

## 4. 证据状态机

### 4.1 状态字段

v2 顶层合同至少包含：

| 字段 | 含义 | 谁能置为 true |
|---|---|---|
| `stage8_input_verified` | Standard-only Stage8 输入集合闭合 | v2 输入 verifier |
| `stage9_input_authorized` | Stage9 v2-r3 按其自有合同通过 | v2 Stage9 gate |
| `stage10_input_authorized` | 精确 Stage10 v2-r2 sealed chain 通过 | v2 Stage10 r2 gate |
| `authorized_external_input` | 前三项按用途要求组合通过 | v2 preflight |
| `stage11_execution_authorized` | 独立下游 execution authorization receipt 通过 | 审批者签发的回执 |
| `stage11_generation_verified` | 生产产物与配置、输入、代码和结果闭合 | 独立 v2 verifier |
| `stage11_final_approval_verified` | 最终批准回执与 generation/verification 精确绑定 | final-status gate |
| `stage11_final_status_evidence_verified` | final-status receipt 及其 release envelope 闭合 | final-status gate |
| `stage11_formally_verified` | 所有必需门禁均通过 | final-status gate 派生，不由 runner 直接写入 |

### 4.2 转移规则

```text
DESIGN_ONLY
  -> IMPLEMENTED_NOT_AUTHORIZED
  -> EXTERNAL_INPUTS_AUTHORIZED
  -> EXECUTION_AUTHORIZED
  -> GENERATION_COMPLETE_PENDING_VERIFICATION
  -> GENERATION_VERIFIED_PENDING_FINAL_APPROVAL
  -> FINAL_APPROVAL_GRANTED_PENDING_FINAL_STATUS
  -> STAGE11_FORMALLY_VERIFIED
```

任意箭头只能由对应的独立回执推动。禁止跳级，禁止 Stage10 gate 直接推动最后两个状态，禁止 runner 自行签发执行授权或最终批准。

`stage11_formally_verified=true` 的必要条件为：

```text
authorized_external_input == true
and stage11_execution_authorized == true
and stage11_generation_verified == true
and stage11_final_approval_verified == true
and stage11_final_status_evidence_verified == true
and test_used_for_parameter_selection == false
and standard_only_input_verified == true
```

任一条件缺失时均为 false。布尔值缺失不得按 false/default 后继续执行，而应视为合同不完整。

## 5. 无循环的 Stage11 执行授权

Stage11 execution authorization 必须是独立、下游、在生成前签发的审批回执。建议放在审批文档树，而不是未来 run 输出目录，例如：

```text
docs/superpowers/specs/<approved-stage11-v2-execution-authorization>.json
```

runner 必须通过命令行接收该回执的外部预期 SHA，不能只信任文件内部 self-hash。回执至少绑定：

- `contract_id=CAPD-PROACTIVE-STAGE11-2.0`；
- 唯一且预声明的 `run_id`；
- v2 config SHA；
- v2 result schema SHA；
- v2 runner、合同模块和 verifier source-set identity/SHA；
- Stage8 r5 authority identity；
- 精确 Standard-only source-set SHA；
- Stage9 v2-r3 关键 receipt SHA；
- Stage10 r2 freeze/readiness/final-status 三个外部锚点 SHA；
- `b_max=2` 主配置与 analysis-only `1/2/4` 约束；
- frozen-grid identity；
- `test_used_for_parameter_selection=false`；
- `stage11_execution_authorized=true`；
- 审批范围和签发身份。

回执不得绑定尚不存在的 result、generation manifest、verification receipt 或 final-status hash。这样授权不依赖未来输出，不产生循环哈希。未来生成产物反向引用 authorization receipt SHA。

若 watermark 或 label-weight 网格仍为空，execution authorization 不得假设或补全数值。若审批范围只允许 Cost profile 离线迁移，则 run 必须仅执行该范围；未批准 lane 必须保持 `BLOCKED`，不能生成伪数值行。

## 6. 输入合同

### 6.1 Stage8 Standard-only 合同

v2 必须从 Stage8 r5 的 job-level 证据构造一个新的、只读的 Standard source set：

1. 校验 Stage8 r5 合同、状态、根清单和权威 artifact SHA。
2. 读取 `artifacts/per_workload_raw.csv`，按 `job_id` 连接根 job manifest 与 `jobs/<job_id>/job_manifest.json`。
3. 对每个 job 校验 `result_sha256` 与 `semantic_result_sha256`，再读取 `result.json.metrics` 中的整数 raw counters。
4. 只接受 `track == "standard"`。
5. 从 Stage8 权威根 manifest 中过滤 `track == "standard"` 得到 `expected_standard_jobs`；要求 `job_id` 唯一，过滤后的实际 job ID 集合与该权威子集逐项相等，而不只比较数量。
6. 要求恰好 48 个唯一 Standard job，且每个 workload 恰好 8 个 job。
7. 每个 workload 的 `(policy, seed)` 多重集合必须精确等于：

```text
(reactive_lru, null)
(proactive_lru, null)
(proactive_clock, null)
(tpp_inspired, null)
(oracle, null)
(capd, 42)
(capd, 2026)
(capd, 3136859)
```

8. workload 集合必须精确等于：

```text
blackscholes
canneal
dedup_pressure
fluidanimate
streamcluster_pressure
swaptions
```

9. 任何 `track == "pressure"` 行在进入 v2 聚合前必须被拒绝。
10. 不得读取或复用 Stage8 dual-track aggregate 作为 Standard-only 汇总。
11. Standard source manifest 按 `job_id` 稳定排序，记录 `job_id`、track、workload、seed、policy、result SHA、semantic result SHA，并对 canonical JSON 计算 source-set SHA。execution authorization 必须绑定该 source-set SHA 和 48 个排序后的 job ID digest。
12. verifier 必须同时比较集合相等、唯一性和 `(workload, policy, seed)` 多重集合；“仍为 48 行但复制一个 job 并遗漏另一个 job”必须失败。
13. Test 只能在冻结配置的最终报告阶段使用；不得用于参数选择、网格修改、checkpoint 选择或方法重设计。

`dedup_pressure` 和 `streamcluster_pressure` 是 workload 名称，不代表 Pressure track。track 字段是唯一分类依据，随后再校验六 workload 白名单。

### 6.2 Stage9-native gate

Stage9 gate 必须按 `configs/finals/capd_proactive_stage9_result_schema.json` 执行：

- required artifacts 全部存在；
- `run_state.json` 与 `verification.json` 的合同、schema 和状态一致；
- `verification.json.artifact_sha256` 的 key set 与 Stage9 schema 要求一致；
- 每个 artifact 的实际 SHA 与记录值一致；
- `stage8_compatibility_receipt.json` 的 entry gate、Stage8 合同、状态、job/statistics/run-state/read-only/Test-isolation 字段通过；
- `environment.json` 证明 Linux CPU 环境；
- perf events、cycles、instructions、task-clock、RSS/memory、raw-to-summary 与 instrumentation semantics 均满足 Stage9 verification contract；
- `formal_b_max=2`，`test_used_for_parameter_selection=false`。

Stage9 gate 不要求不存在的根 `manifest.json + SHA256SUMS`。缺少、篡改或 schema 不一致时返回 `NOT_VERIFIABLE`；完整但明确未获下游用途批准时返回 `BLOCKED`。

当前 Stage9 v2-r3 latency summary 是跨现有 Stage9 测量集合的 `b_max` 聚合，没有提供可直接验证的 Standard-only workload 分组。它可以证明 Stage9 自身真实 Linux CPU/perf/RSS 开销合同，也可以解释 Stage10 r2 的 timing provenance；但在没有新的 Standard-only provenance receipt 前，不能进入六 workload 主表的 Standard-only latency aggregate。

### 6.3 Stage10 r2 gate

v2 只接受精确 `stage10-async-simulator-v2-r2`，不接受 Stage10A fixture 或 v2-r1。gate 顺序如下：

1. 精确匹配 freeze receipt 外部 SHA `3f4ce4...ac61f2`。
2. 校验 generation 的完整文件集合、manifest payload set 和 `SHA256SUMS`；manifest 排除自身和 `SHA256SUMS`，checksums 包含 manifest 并排除自身。
3. 校验 generation 的 `run_identity.json`、`run_state.json`、`verification.json` 与本文第 2.4 节的精确 SHA 和合同状态。
4. 校验 run ID、contract ID、evidence mode、source-set identity、封存 generation commit 和 self-hash；封存 revision 从 sealed run identity 读取，不用当前 HEAD 替换。
5. 可选 compatibility audit 逐项重算 generation source manifest 的 11 个当前路径/SHA，输出 `generation_source_set_match`；另行比较当前 HEAD，输出 `repository_revision_match`。两者不得合并为一个 source identity 字段，也不得参与 sealed positive decision。
6. 校验 `stage9_input_receipt.json` 及其绑定的 Stage9 v2-r3 config、verification、checkpoint、latency summary、run identity 与 Stage8 compatibility receipt。
7. 校验 scenario matrix 为 60 行，results 为 60 行，ID 唯一；matrix、verification 与 JSONL 的 scenario ID 顺序/集合满足原合同。
8. 校验每个结果的完整 scenario identity、输入 binding、确定性重算字段和结果 schema，不能只比较计数。
9. 精确匹配 readiness receipt 外部 SHA `f73829...f1bac`，校验 readiness manifest 与 checksums。
10. 要求 sealed readiness 中 native 和 dispatcher 两个 verifier 状态均为 `stage10_async_simulation_verified`，且 `synthetic_test_only=false`。
11. 精确匹配 final-status receipt 外部 SHA `657034...28e8e7`，校验 final-status manifest 与 checksums，并要求状态为 `stage10_final_status_evidence_verified`。
12. 要求五个真实系统能力标志全部为 false；任何一个错误变为 true 都是合同不一致。
13. 原样检查 `stage11_positive_migration_authorized=false`，但不把该历史字段用于当前授权判断。
14. Stage11 positive gate 不执行 live verifier；可选诊断命令单独记录 current live replay compatibility，且不能替代 sealed dual-verifier attestation。

gate 输出建议包含：

```json
{
  "stage": "stage10",
  "contract_id": "CAPD-PROACTIVE-STAGE10-2.0",
  "run_id": "stage10-async-simulator-v2-r2",
  "artifact_integrity": "verified",
  "generation_source_set_match": true,
  "repository_revision_match": false,
  "sealed_dual_verifier_attestation": "verified",
  "current_live_replay_compatibility": "NOT_VERIFIABLE",
  "authorized_external_input": true,
  "stage11_execution_authorized": false,
  "stage11_formally_verified": false
}
```

示例只表达当前证据类型关系，不是本轮生成的生产结果。

### 6.4 Cost、批量和消融边界

v2 保留四个 Cost profile：`1:2:4:8`、`1:2:8:10`、`1:2:12:10`、`1:2:8:20`。`NVM write` 是 NVM 写访问成本，`demotion` 是 DRAM 到 NVM 迁移成本。离线重算必须使用 Stage8 job-level 原始整数计数；JSON 缺失数值用 `null`，CSV/Markdown 用 `N/A`。

正式主配置继续固定 `b_max=2`。`b_max=1/4` 只允许 analysis-only，不能覆盖主配置。Top-1 与 Top-b 必须使用相同主动水位和其他配置，只改变每轮选择数量，且不得写成“新旧 CAPD”比较。

watermark 和 label-weight 网格未经单独批准不得生成、冻结或执行。`CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState` 只有接口；没有固定训练协议、配对训练 receipt 和 Validation-only checkpoint selection receipt 时必须为 `BLOCKED`。推理时遮蔽只能标为诊断，不能标为模型组件消融。

## 7. Standard-only 与 Stage10 证据的用途隔离

v2 结果必须提供 `population_scope` 和 `provenance_scope`：

| 证据 | 当前可声明范围 | 禁止用途 |
|---|---|---|
| Stage8 r5 过滤后的 48 job | 六 workload Standard-only 同步质量/事件计数/离线 Cost | Pressure track 汇总、真实延迟、异步性能 |
| Stage9 v2-r3 | 真实 Linux CPU/perf/RSS 开销与其现有聚合范围 | 未经证明的 Standard-only latency aggregate |
| Stage10 v2-r2 | 已验证的确定性异步仿真 scenario sensitivity | 真实 NVM、kernel、并发、前台端到端延迟、真实系统异步性能 |

Stage10 r2 的 timing provenance 使用 Stage9 `by_b_max["2"]` 聚合，并不按六个 Standard workload 提供可验证拆分。因此它可以作为 Stage11 的 authorized external input 和单独的“确定性异步仿真”证据块，但不能与 Standard-only 主结果表静默合并。若论文要求 Standard-only 异步数值，必须另行设计并批准新的 Standard-only timing/simulation evidence；不在本文授权范围内。

## 8. 输出与哈希合同

### 8.1 建议目录

未来 v2 只允许写：

```text
outputs/capd_proactive_stage11_v2/
  <run_id>/
  release_receipts/<run_id>/verification/
  release_receipts/<run_id>/final-approval/
  release_receipts/<run_id>/final-status/
```

不得写入 Stage8、Stage9、Stage10、`outputs/capd_proactive_stage11/` 或冻结 checkpoint。已存在 `run_id` 必须拒绝，禁止覆盖、追加或修复原目录。

### 8.2 Generation artifacts

建议 generation 至少包含：

- `stage11_v2_config.json`；
- `run_identity.json`；
- `run_state.json`；
- `stage8_standard_input_receipt.json`；
- `stage9_input_receipt.json`；
- `stage10_input_receipt.json`；
- `execution_authorization_receipt.json` 的只读副本或精确引用；
- `standard_source_manifest.json`；
- `frozen_grid.json`；
- `stage11_v2_results.json`；
- `stage11_v2_results.csv`；
- `stage11_v2_report.md`；
- `manifest.json`；
- `SHA256SUMS`。

`run_identity.json` 必须绑定 run ID、config/schema/source-set SHA、代码版本、authorization receipt SHA、Stage8/9/10 input receipt SHA、Standard source-set SHA 和 frozen-grid identity。

Generation `manifest.json` 排除自身与 `SHA256SUMS`；`SHA256SUMS` 包含 manifest 并排除自身。manifest payload set、checksum set 和实际文件 set 必须精确相等，不允许额外未声明文件。

Generation runner 只能写：

```text
stage11_generation_complete_pending_verification
stage11_formally_verified = false
```

它不能自行写 `stage11_formally_verified=true`。

### 8.3 Independent verification receipt

独立 verifier 在 generation 完成后只读校验，并写入单独 release receipt 目录。verification receipt 必须绑定：

- execution authorization receipt SHA；
- generation `run_identity.json` SHA；
- generation `run_state.json` SHA；
- generation `manifest.json` SHA；
- generation `SHA256SUMS` SHA；
- result JSON/CSV/report SHA；
- Standard source manifest SHA 和 48-job/六-workload断言；
- Stage8/9/10 input receipt SHA；
- 独立 verifier source identity；
- negative-test evidence identity；
- `stage11_generation_verified=true`。

verification release manifest 排除自身和 checksums；checksums 包含 manifest、排除自身，规则与 generation 相同。

### 8.4 Final approval receipt

final approval 是 generation 和 independent verification 之后的独立人工审批动作，只能写入：

```text
outputs/capd_proactive_stage11_v2/
  release_receipts/<run_id>/final-approval/
    final_approval_receipt.json
    manifest.json
    SHA256SUMS
```

`final_approval_receipt.json` 必须满足 `capd_proactive_stage11_v2_final_approval_receipt_schema`，至少包含：

- `schema_version`、`contract_id`、精确 `run_id`；
- `approval_decision=approved_for_stage11_finalization`；
- approval authority、approval reference 和 approval timestamp；
- execution authorization receipt SHA；
- generation `run_identity.json`、`run_state.json`、`manifest.json`、`SHA256SUMS` SHA；
- generation result JSON/CSV/report SHA；
- verification receipt、verification manifest 和 verification `SHA256SUMS` SHA；
- Standard source manifest SHA、排序 job ID digest、48-job 和六-workload identity；
- Stage8/9/10 input receipt SHA；
- `stage11_generation_verified=true`；
- `stage11_final_approval_granted=true`；
- `test_used_for_parameter_selection=false`；
- 明确批准的 evidence scope 与明确排除的 real-system/未授权消融结论。

final approval receipt 不得包含 final-status receipt、final-status manifest、未来输出 SHA 或自身 SHA。其 `manifest.json` 的 `phase` 必须为 `final_approval`，payload set 精确为 `final_approval_receipt.json`；manifest 排除自身和 `SHA256SUMS`，checksums 包含 receipt 与 manifest、排除自身，目录不得有额外文件。

final approval 动作完成后，审批者必须在该目录之外给出精确 receipt SHA。final-status 构建器必须通过显式参数，例如 `--approved-final-approval-receipt-sha256`，接收此外部预期 SHA；禁止从 receipt、manifest、文件名或当前目录自行推断。receipt 被篡改后，即使重算 manifest 与 checksums，也会因此外部预期 SHA 不匹配而失败。

### 8.5 Final-status evidence receipt

final-status 只能在精确 final approval receipt 及其外部预期 SHA 通过后生成，目录为：

```text
outputs/capd_proactive_stage11_v2/
  release_receipts/<run_id>/final-status/
    final_status_evidence_receipt.json
    manifest.json
    SHA256SUMS
```

`final_status_evidence_receipt.json` 必须满足 `capd_proactive_stage11_v2_final_status_evidence_receipt_schema`，至少包含：

- `schema_version`、`contract_id`、精确 `run_id`；
- `status=stage11_formally_verified`；
- execution authorization receipt SHA；
- generation run identity、run state、manifest、checksums 和 result SHA；
- verification receipt、manifest、checksums SHA；
- final approval receipt、manifest、checksums SHA；
- Standard source manifest SHA、排序 job ID digest、48-job/六-workload断言；
- `authorized_external_input=true`；
- `stage11_execution_authorized=true`；
- `stage11_generation_verified=true`；
- `stage11_final_approval_verified=true`；
- `stage11_final_status_evidence_verified=true`；
- `stage11_formally_verified=true`；
- Test isolation、主 `b_max=2` 与论文能力边界字段。

final-status receipt 不得绑定自身 SHA，也不得回写任一上游目录。其 `manifest.json` 的 `phase` 必须为 `final_status`，payload set 精确为 `final_status_evidence_receipt.json`；manifest 和 checksums 规则与 final approval 相同。

final-status 生成后，Stage11 消费 gate 必须从 release 目录之外接收 `--approved-final-status-receipt-sha256` 或等价冻结配置字段。没有这个外部预期 SHA，即使 final-status 三文件内部自洽，也只能是 `NOT_VERIFIABLE`，不得产生有效 formal status。

### 8.6 无环顺序与有效状态

证据创建顺序固定为：

```text
execution authorization
  -> generation
  -> independent verification
  -> final approval
  -> final-status evidence
  -> downstream consumption
```

每一阶段只引用左侧已经存在的 artifact SHA。receipt 外部预期 SHA 在该 receipt 创建并经独立审批后，作为下一阶段或 downstream consumer 的输入；任何 receipt 都不引用自身 SHA，也不引用右侧未来阶段，因此不存在循环依赖。

为了保持 generation 不可变，原始 result 行在 generation 中可以保留 `candidate-ready` 或 `pending-formalization`；消费者只有在 final-status receipt、manifest、checksums 和外部预期 SHA 全部通过后，才可派生 `effective_evidence_status=formally_verified`。不得回写 generation result、run state 或 manifest。

## 9. 失败语义

| 条件 | 状态 | 行为 |
|---|---|---|
| 证据缺失、SHA 不符、schema 不符、版本错误 | `NOT_VERIFIABLE` | fail closed，不执行 |
| 完整证据明确表明未授权，例如 Stage10A fixture 或无 execution receipt | `BLOCKED` | fail closed，不执行 |
| Stage10 v2-r1 传入 v2-r2 gate | `NOT_VERIFIABLE` | `wrong_stage10_release` |
| `generation_source_set_match=true` 但 `repository_revision_match=false` | input 可授权；live replay 单列 `NOT_VERIFIABLE` | 不称 source mismatch、篡改或 live replay 通过 |
| 当前 generation source set 任一 SHA 不匹配 | live replay `NOT_VERIFIABLE` | sealed input 仍按外部锚点独立判断，不误报 sealed tamper |
| sealed readiness 中仅一个 Stage10 verifier 通过 | `NOT_VERIFIABLE` | 拒绝 external input |
| Stage10 任一 real-system flag 为 true | `NOT_VERIFIABLE` | `stage10_capability_contract_inconsistent` |
| external input 通过但 Stage11 execution authorization 缺失 | `BLOCKED` | 不创建 production run directory |
| generation 完成但 independent verification 缺失 | pending | `stage11_formally_verified=false` |
| verification 通过但 final approval 缺失 | pending | `stage11_formally_verified=false` |
| final approval 内部闭合但缺少外部预期 receipt SHA | `NOT_VERIFIABLE` | 不生成 final-status |
| final-status 内部闭合但缺少外部预期 receipt SHA | `NOT_VERIFIABLE` | 不产生有效 formal status |
| Pressure 行进入 Standard source set | `NOT_VERIFIABLE` | 拒绝整个 v2 run，不只丢弃该行 |
| 缺失数值 | JSON `null`；报告 `N/A` | 禁止替换为 0 或估计值 |

建议 v2 runner 提供只读 `--audit-inputs` 模式，将诊断打印到 stdout；只有所有全局 preflight、外部输入 gate 和 execution authorization 通过后才创建 production run directory。这样失败不会留下可被误认成正式结果的半成品目录。

## 10. TDD 负向矩阵

实施阶段必须先写失败测试，再写 gate。至少覆盖：

| ID | 负向场景 | 预期 |
|---|---|---|
| T01 | Stage10A fixture 走 v1.0 | 保持 `BLOCKED/stage10a_fixture_only` |
| T02 | Stage10 v2-r1 冒充 r2 | `NOT_VERIFIABLE` |
| T03 | r2 缺 generation、readiness 或 final-status 任一阶段 | `NOT_VERIFIABLE` |
| T04 | freeze receipt SHA 被改 | 拒绝 |
| T05 | run ID 或 contract version 被改 | 拒绝 |
| T06 | result count 不为 60 | 拒绝 |
| T07 | scenario ID 缺失、重复、乱配或 identity 字段被改 | 拒绝 |
| T08 | Stage9 input receipt 被改 | 拒绝 |
| T09 | readiness/final-status receipt 被改 | 拒绝 |
| T10 | generation/release manifest 文件集合或 hash 被改 | 拒绝 |
| T11 | `SHA256SUMS` 缺项、重复项、额外项或 hash 被改 | 拒绝 |
| T12 | 篡改 payload 后重算 self-hash、manifest 和 checksums | 因外部 anchor 不匹配仍拒绝 |
| T13 | 只有 dispatcher 或只有 native verifier 通过 | 拒绝 |
| T14 | 五个 real-system flag 任一被改为 true | 拒绝或报告合同不一致 |
| T15 | Stage10 gate 通过但 execution authorization 缺失 | `BLOCKED`，不创建 run |
| T16 | execution receipt 绑定不同 run ID/config/schema/source set | 拒绝 |
| T17 | Stage11 generation 试图直接写 formally verified | schema/validator 拒绝 |
| T18 | independent verification 或 final approval 缺失 | formal 状态保持 false |
| T19 | Stage8 source set 含 Pressure track | 拒绝整个 Standard-only run |
| T20 | Standard job 数不是 48、job ID 不唯一或 workload 集不精确 | 拒绝 |
| T21 | 使用 dual-track aggregate 代替 job-level Standard join | 拒绝 |
| T22 | `result_sha256` 或 `semantic_result_sha256` 被改 | 拒绝 |
| T23 | 从浮点 cost 反推 raw access count | 拒绝 |
| T24 | 正式主配置不是 `b_max=2` | 拒绝 |
| T25 | `b_max=1/4` 覆盖主结果 | 拒绝 |
| T26 | watermark/label-weight 未批准却生成 | `BLOCKED` |
| T27 | 推理遮蔽被标为正式组件消融 | schema 拒绝 |
| T28 | Test 被用于调参或 checkpoint 选择 | 拒绝 |
| T29 | 重用已存在 run ID | 拒绝且不修改原目录 |
| T30 | v1.0 runner/schema/tests 行为变化 | compatibility test 失败 |
| T31 | 11 个 source SHA 全匹配但 repository revision 不同 | `generation_source_set_match=true`、`repository_revision_match=false` |
| T32 | sealed evidence 完整且 source set 匹配、repository revision 不同 | input 可授权，live replay 为 `NOT_VERIFIABLE`，不误报 tamper |
| T33 | 当前 generation source manifest 任一路径或 SHA 不匹配 | `generation_source_set_match=false`、live replay `NOT_VERIFIABLE`；sealed decision 独立 |
| T34 | Standard 仍为 48 行，但重复一个 job 并遗漏另一个 job | 因 job ID 集合不等而拒绝 |
| T35 | 每 workload 仍为 8 行，但 policy/seed 多重集合错误 | 拒绝 |
| T36 | final approval receipt 缺失、错 run ID 或错 contract | `NOT_VERIFIABLE` |
| T37 | final approval receipt 绑定错误 verification receipt SHA | 拒绝 |
| T38 | 篡改 final approval 后重算其 manifest/checksums | 因外部预期 approval receipt SHA 不匹配而拒绝 |
| T39 | final-status receipt 绑定错误 run ID、generation、verification 或 approval SHA | 拒绝 |
| T40 | 篡改 final-status 后重算其 manifest/checksums | 因外部预期 final-status receipt SHA 不匹配而拒绝 |
| T41 | final approval 或 final-status 缺少外部预期 receipt SHA | `NOT_VERIFIABLE`，formal 状态保持 false |

测试必须对 Stage8 r5、Stage9、Stage10、旧 Stage11A 和冻结 checkpoint 做运行前后树 fingerprint 比较。fixture 只能证明负向路径，不能生成 production receipt 或 `formally_verified`。

## 11. 兼容策略

1. v1 合同、module、runner、config、schema 和 22 项测试保持原样。
2. v1 的 Stage10A fixture 行为仍为完整 fixture `BLOCKED`、缺失/篡改 `NOT_VERIFIABLE`。
3. v2 不复用 v1 `audit_stage10_fixture()` 作为 r2 positive gate。
4. v2 输出使用新根目录，禁止扫描或升级 v1 candidate artifact。
5. 历史 dual-track candidate 只按其生成时合同解释，不删除、不重写、不进入 Standard-only primary aggregate。
6. v2 verifier 必须以显式 contract/version dispatch，未知版本 fail closed。
7. v1 和 v2 都保留 JSON `null`、CSV/Markdown `N/A`、Test isolation、主 `b_max=2` 和未批准消融边界。

## 12. 论文结论边界

在 v2 完成正式执行和最终批准之前，论文不能声称 Stage11 正向迁移已完成或 Stage11 结果已 formally verified。

即使 Stage10 r2 被接受为 authorized external input，也只能支持：

- Stage10 的 60 个确定性异步仿真 scenario 已按 sealed release contract 验证；
- 这些 scenario 可作为独立的模拟器敏感性证据；
- Stage9 v2-r3 提供其合同范围内的 Linux CPU/perf/RSS 输入证据。

当前不能支持：

- 真实 NVM 测量；
- kernel behavior；
- 真实并发；
- 真实前台端到端延迟；
- 真实系统异步性能；
- Stage9/Stage10 数值已经是六 workload Standard-only aggregate；
- 未批准 watermark/label-weight 的最优性；
- 通过推理遮蔽得到的正式模型组件消融；
- Test 驱动的参数或 checkpoint 选择；
- Stage10 验证自动证明 Stage11 正式有效。

论文主实验的同步质量和离线 Cost 只能从精确 48-job Standard source set 聚合。Stage10 仿真若被引用，必须独立标注 `deterministic_async_simulation`，不得与真实系统结果或 Standard-only workload aggregate 混写。

## 13. P1/P2 关闭状态

### 13.1 本次设计修订已关闭的 P1

1. Stage10 replay identity 已拆为 `generation_source_set_match` 与 `repository_revision_match`；positive gate 明确采用 sealed-attestation-only，不再对 source identity 作双重解释。
2. final approval 与 final-status 已分别定义 schema、目录、外部预期 SHA、必需字段、manifest/checksum 规则、无环顺序和负向测试。
3. Standard-only 输入已从“48 行加六 workload”提升为权威 Standard job ID 子集逐项相等、唯一性和每 workload 精确 policy/seed 多重集合三重校验。

### 13.2 正式执行或论文声明前仍需关闭的 P1

1. Stage11 v2 execution authorization 的实际 schema 文件、审批回执和外部预期 SHA 尚不存在。没有这些内容不得创建 production run。
2. Stage9 latency summary 和 Stage10 r2 timing provenance 当前不是可验证的六 workload Standard-only 聚合。它们不能进入 Standard-only 主表；若论文需要 Standard-only async/latency 数值，必须新增独立证据合同并另行批准。
3. final approval 和 final-status receipt 只能在未来 generation/verification 完成并获得对应明确审批后产生；在此之前 `stage11_formally_verified` 必须为 false。

### 13.3 P2：实施或后续实验前关闭

1. v2 contract/config/result/execution-authorization/verification/final-approval/final-status/release-manifest schema、runner 和 tests 尚未实现。
2. watermark 和 label-weight 网格仍未冻结、未授权；相关 lane 必须保持 `BLOCKED`。
3. 正式输入组件消融缺少固定训练协议、配对训练 receipt 与 Validation-only checkpoint selection receipt。

## 14. 后续审批门

2026-08-07 的明确设计审批仅授权进入实施计划阶段。当前状态为：

```text
Design Status: DESIGN_APPROVED
Approved Scope: IMPLEMENTATION_PLAN_ONLY
Implementation Authorization: NOT_GRANTED
Formal Experiment Authorization: NOT_GRANTED
Stage11 Formal Verification: NOT_AVAILABLE
```

下一步是编写并提交独立实施计划。实施计划再次获得明确批准后，才能修改代码、config、schema、runner 或 tests。设计批准和未来实施完成都不自动授权正式 Stage11 run；execution authorization receipt、正式执行、final approval、final-status、commit 和 push 均需要各自明确授权。
