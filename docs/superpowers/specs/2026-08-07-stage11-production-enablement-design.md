# CAPD Stage11 v2 Production Enablement 设计

- Design Status: `DESIGN_APPROVED`
- Date: `2026-08-07`
- Contract: `CAPD-PROACTIVE-STAGE11-2.0`
- Design Scope: `PRODUCTION_ENABLEMENT_DESIGN_ONLY`
- Implementation Authorization: `NOT_GRANTED`
- Input-Audit Receipt Authorization: `NOT_GRANTED`
- Execution Authorization: `NOT_GRANTED`
- Production Generation Authorization: `NOT_GRANTED`
- Independent Verification Authorization: `NOT_GRANTED`
- Final Approval Authorization: `NOT_GRANTED`
- Final-Status Authorization: `NOT_GRANTED`

本文只设计 Stage11 v2 的 production enablement、Step 3 审计证据封存和后续审批链。本文不修改代码、配置、schema、状态文档或 source manifest，不创建 input-audit package，不签发任何 receipt，不运行 production，不创建正式结果，不 commit，不 push。

## 1. 目标

Stage11 v2 production 只完成一个边界明确的离线任务：从 Stage8 r5 的 48 个 Standard job 读取已经保存并通过 job-level SHA 绑定的原始整数事件计数，对四个预先固定的 Cost profile 逐项重算，生成恰好 192 行结果。

本设计解决以下问题：

1. 将已经人工确认但尚未封存的 Task 12 Step 3 结果转化为机器可消费的 input-audit package。
2. 让 production config、run identity 和 execution authorization 绑定新的 approved production-plan SHA。
3. 在 production 代码稳定后重新冻结 generation/verifier source manifests，避免授权回执与未来代码互相依赖。
4. 定义从 input audit 到 generation、independent verification、final approval、final-status 的无环、分阶段审批链。
5. 将正式输出严格限制为 48 个 Standard job 与四个 Cost profile 的笛卡尔积。
6. 保持 watermark、label-weight、容量/批量额外网格和模型组件消融为 `BLOCKED`，不生成占位数字。

## 2. 非目标

本阶段不设计或执行：

- 新的 Stage8 replay；
- 新的 Stage9 Linux/perf/RSS 测量；
- 新的 Stage10 异步模拟或真实系统异步测量；
- GPU 训练、重新训练、checkpoint 选择或 Test 驱动调参；
- watermark、label-weight、容量或 `b_max=1/4` 的正式敏感性运行；
- `CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState` 的正式组件消融；
- 服务器执行、代码同步、commit 或 push；
- 在没有独立 final-status receipt 的情况下产生 `stage11_formally_verified=true`。

正式 generation 只读取现有 raw counters 并进行确定性整数重算，本地即可执行。服务器仅在未来新增真实 Linux/perf/RSS 或真实系统异步测量时需要，这些测量不属于本 production 合同。

## 3. 当前证据状态与缺口

### 3.1 已人工确认的 Step 3 结果

2026-08-07 的交互式执行已经人工确认：

- 精确 15-class synthetic allowlist 为 `41/41 OK`；
- 六项 legacy semantic tests 为 `6/6 OK`；
- real-upstream audit 中 Stage8、Stage9、Stage10 三项输入门禁均通过；
- Stage10 诊断为：

```text
generation_source_set_match=true
repository_revision_match=false
sealed_dual_verifier_attestation=verified
current_live_replay_compatibility=NOT_VERIFIABLE
authorized_external_input=true
```

- 冻结树前后 `{path,length,sha256}` 记录一致；
- `outputs/capd_proactive_stage11_v2/` 未创建；
- 未签发 execution authorization，未运行 production。

这些结论目前只存在于交互式消息和临时目录中，不是仓库内可由后续 authorization validator 消费的封存证据。

### 3.2 状态文档仍是旧快照

`docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md` 仍记录：

```text
real-upstream semantic audit = NOT_RUN
```

该状态文档是实施阶段结束时的历史快照，不得在本设计阶段改写。只有 input-audit package 已生成、独立校验、获得外部 receipt SHA 批准后，才可以在单独授权下更新状态文档。状态文档本身不能替代 receipt、manifest 或 checksum。

### 3.3 当前代码仍是 synthetic-only

当前 runner 对非 `synthetic_test_only` 路径 fail closed，并要求 repository config 中 `production_execution_enabled=false`。当前 execution authorization schema 只覆盖此前 synthetic implementation 合同，没有 input-audit package、approved production-plan SHA 和 production-only scope 的完整绑定。

因此，Step 3 审计通过不等于 production 已启用，也不授权修改现有 config 中的布尔值。

## 4. 新身份与版本策略

### 4.1 合同与 production revision

顶层合同继续使用：

```text
CAPD-PROACTIVE-STAGE11-2.0
```

production enablement 使用独立 protocol revision：

```text
stage11-v2-production-r1
```

现有 synthetic config、synthetic authorization schema 和 41 项测试继续作为历史实现基线。production 不复用 synthetic receipt，也不通过修改 synthetic receipt 的布尔值获得授权。

### 4.2 Input-audit identity

首个封存审计包固定 identity：

```text
audit_id = stage11-input-audit-v2-r1
```

建议目录：

```text
outputs/capd_proactive_stage11_v2/
  input_audits/stage11-input-audit-v2-r1/
```

创建该目录需要单独的 input-audit capture/seal 授权，不由本设计批准。

### 4.3 Production run identity

首个 production run 固定新 run ID：

```text
run_id = stage11-standard-cost-profiles-v2-r1
```

正式 run 目录固定为：

```text
outputs/capd_proactive_stage11_v2/
  stage11-standard-cost-profiles-v2-r1/
```

不得复用 synthetic run ID、Stage11A run ID、历史 candidate run ID 或 input-audit ID。目标目录已存在时必须在任何写入前拒绝。

### 4.4 Approved production design 与 plan

本设计获批后：

1. 将本文状态改为 `DESIGN_APPROVED`。
2. 在本文外计算最终 approved production-design SHA。
3. 编写独立 production implementation plan。
4. 计划获批后改为 `PLAN_APPROVED`。
5. 在计划外计算最终 approved production-plan SHA。

本文和未来 plan 均不得引用自身 SHA。production config、input-audit receipt、execution authorization 和 run identity 必须从外部批准值绑定最终 SHA，不能从文件名、Git commit message 或状态文档推断。

## 5. 无环依赖顺序

必须按以下顺序推进：

```text
approved production design
  -> approved production plan
  -> production code/schema/tests implemented, production still disabled
  -> generation/verifier source dependency closure fixed
  -> final generation/verifier source manifests frozen
  -> separately authorized Step 3 evidence recapture and package seal
  -> input-audit package independently verified
  -> input-audit receipt external SHA approved
  -> execution authorization receipt prepared and external SHA approved
  -> separately authorized production generation
  -> separately authorized independent verification
  -> separately issued final approval receipt
  -> separately authorized final-status seal
```

禁止以下环：

- source manifest 不包含 input-audit logs、status 文档、release 文档或 receipt；
- input-audit receipt 不包含其 package manifest 或 `SHA256SUMS` 的未来 SHA；
- execution authorization 不包含未来 generation result、run manifest、verification、final approval 或 final-status SHA；
- generation run identity 可以反向引用已存在的 execution authorization SHA；
- verification 可以引用已存在的 generation SHA；
- final approval 可以引用已存在的 verification SHA；
- final-status 可以引用已存在的 final approval SHA。

## 6. Source identity 冻结

### 6.1 冻结时点

production 代码、production config/schema、input-audit validator、production writer、independent verifier 和对应 synthetic tests 全部稳定后，才生成最终 source manifests。之后不得再修改 source manifest 成员字节并继续使用旧 authorization。

任何 source member 变化均要求：

1. 重新运行 fixture-only tests；
2. 重新生成 generation/verifier source manifests；
3. 重新执行并封存 input audit；
4. 重新批准 input-audit receipt 外部 SHA；
5. 重新签发 execution authorization。

### 6.2 Generation source closure

generation manifest 至少包含：

- production runner；
- Stage11 v2 generation contract；
- output path capability guard；
- Cost 重算 helper；
- production config 与 schema；
- result、run identity、run state、input receipt、input-audit receipt、execution authorization 和 release manifest schemas；
- Stage8/Stage9/Stage10 gate 所直接使用的 schemas；
- 本地 import 的完整传递闭包。

### 6.3 Verifier source closure

verifier manifest 至少包含：

- independent verifier CLI；
- independent verifier contract；
- output path capability guard 的只读部分；
- production config/result/receipt/run/release schemas；
- Stage8/Stage9/Stage10 输入 schema；
- 本地 import 的完整传递闭包。

verifier 不得导入 generation contract、generation runner 或 Cost helper。它必须独立实现 raw-counter 重算和 exact member-set 校验。

### 6.4 明确排除项

两个 source manifests 都明确排除：

- `outputs/`；
- input-audit logs 与 receipts；
- generation/verification/final release receipts；
- status 文档和 release 后更新文档；
- tests 与 fixtures；
- `__pycache__`、临时文件和运行日志。

tests 从 generation/verifier source manifests 排除，不表示测试源码不受身份约束。第 7 节使用独立的 `test_source_identity.json` 封存精确测试模块及其本地传递依赖，避免运行结果与测试字节脱钩。其他排除项不得被 import closure 实际加载。执行前后分别记录 source snapshot；任一成员路径、长度或 SHA 变化都必须失败并删除尚未发布的临时 run。

### 6.5 精确成员治理

production implementation plan 必须在实现前给出 generation 和 verifier 的完整、排序、唯一 POSIX path 白名单，不得只写角色或目录 glob。实现只能在第 6.2、6.3 节定义的角色范围内补全实际文件名；若后来新增本地 import、helper 或 schema，必须先修订并重新批准 plan，再更新白名单。source manifest 的成员集合必须与批准 plan 的白名单逐项相等。

production source manifest 必须绑定本 production design SHA 和 approved production-plan SHA，不得继续沿用 synthetic baseline manifest 中的旧 design/plan identity。

## 7. Step 3 Input-Audit Package

### 7.1 精确目录与成员

审计包目录固定为：

```text
outputs/capd_proactive_stage11_v2/
  input_audits/stage11-input-audit-v2-r1/
    audit_identity.json
    audit_commands.json
    synthetic_allowlist.log
    production_enablement_tests.log
    legacy_semantic_tests.log
    real_upstream_audit_stdout.json
    stage8_standard_input_receipt.json
    stage9_input_receipt.json
    stage10_input_receipt.json
    standard_source_manifest.json
    frozen_tree_before.json
    frozen_tree_after.json
    frozen_tree_comparison.json
    source_identity.json
    test_source_identity.json
    input_audit_receipt.json
    manifest.json
    SHA256SUMS
```

成员集合必须精确。不得加入临时日志、重试日志、环境转储或 production result。

### 7.2 命令身份

`audit_commands.json` 记录 argv 数组、Python executable SHA/版本、cwd、开始/结束状态、退出码、自动重试状态和日志 SHA。包含四条逻辑命令：

1. 精确 15-class synthetic allowlist，类名集合与批准计划逐项相等；
2. production implementation plan 冻结的独立 production-enablement fixture-only test module；
3. `scripts/run_capd_proactive_stage11_v2.py --audit-inputs --allow-real-upstream-audit`，使用最终 production config 的只读 audit profile；
4. 精确六项 legacy semantic tests：

```text
tests.test_capd_proactive_stage10.Stage10FormalGateTest.test_historical_r1_run_directory_is_rejected
tests.test_capd_proactive_stage10_v2.Stage10V2Stage9GateTest.test_real_stage9_r3_passes_complete_read_only_gate
tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_dispatch_still_verifies_historical_fixture
tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_and_v2_verifiers_are_bidirectionally_incompatible
tests.test_capd_proactive_stage11.Stage11GateTest.test_complete_stage10a_fixture_is_blocked
tests.test_capd_proactive_stage11.Stage11GateTest.test_historical_stage9_run_is_not_verifiable
```

所有命令必须单次执行、`exit_code=0`、`timed_out=false`、`automatic_retry_performed=false`。日志必须保存完整 stdout/stderr，不得只保存人工摘要。production 专用测试必须放在新的 test module 中，不能通过向既有 15-class allowlist 增加方法改变 `41/41` 基线。第一条测试命令前与第四条测试命令后分别重建 test-source snapshot；两者必须与 `test_source_identity.json` 中的精确成员集合逐项相等。

### 7.3 Canonical 上游对象

capture runner 必须从真实上游独立生成以下四个 canonical 对象，并把生成后的原始字节作为第 7.1 节审计包成员封存：

```text
stage8_standard_input_receipt.json
stage9_input_receipt.json
stage10_input_receipt.json
standard_source_manifest.json
```

四个对象统一使用 UTF-8、无 BOM、JSON object key 递归字典序、紧凑分隔符、文件末尾单个 LF。数组使用各自 schema 定义的 canonical 顺序；`standard_source_manifest.json` 的 job 成员按 `job_id` 排序。对象中不得包含捕获时间、绝对临时路径或其他会破坏确定性重建的环境字段。

独立 input-audit verifier 不得信任 capture runner 的内存对象或摘要。它必须从真实 Stage8/9/10 上游重新执行各自 schema、manifest、receipt、artifact SHA 与 semantic SHA 门禁，在系统临时目录重建四个对象，并要求重建字节与 package 成员逐字节相等。只比较字段子集、解析后的语义相等、成员数量或 receipt 中声明的 SHA 均不足以通过。`input_audit_receipt.json` 中四个对应 SHA 必须是这些 sealed package member 的文件 SHA。

### 7.4 必需审计结论

`real_upstream_audit_stdout.json` 必须是 runner stdout 的 strict JSON。所需字段与值为：

| Field | Required value |
|---|---|
| `real_upstream_audit` | `"COMPLETED"` |
| `stage8_input_verified` | `true` |
| `stage9_input_authorized` | `true` |
| `stage10_input_authorized` | `true` |
| `generation_source_manifest_verified` | `true` |
| `verifier_source_manifest_verified` | `true` |
| `generation_source_set_match` | `true` |
| `repository_revision_match` | 实测 JSON boolean |
| `current_live_replay_compatibility` | `"NOT_VERIFIABLE"` |
| `stage11_execution_authorized` | `false` |
| `stage11_formally_verified` | `false` |

`repository_revision_match` 必须记录重新捕获时的实际布尔值，并与独立 verifier 的重算结果相等；它不属于 input authorization 的通过条件。当前重新捕获可能仍为 `false`，未来也可能为 `true`，两种值都只表示 current-tree repository revision 诊断，不得改写为 source-set mismatch、sealed tamper 或 Stage10 未验证。即使该值为 `true`，`current_live_replay_compatibility=NOT_VERIFIABLE` 也不得自动升级为 verified。

### 7.5 测试日志与测试源码合同

`synthetic_allowlist.log` 必须证明：

- 精确 15 个批准 class；
- 精确 `41` 个 test；
- `OK`；
- synthetic test audit hook 对真实 Stage8/9/10/11/checkpoint 的 successful-open count 为 0；
- denied-open 负向 case 只证明 fail closed。

`legacy_semantic_tests.log` 必须证明：

- 测试 ID 精确等于第 7.2 节六项；
- 精确 `6` 个 test；
- `OK`；
- 未运行其他 legacy semantic test。

`production_enablement_tests.log` 必须证明 production implementation plan 冻结的精确 module、test ID 集合和 test count 全部通过。该日志只使用系统临时 fixture，不读取真实上游。

既有 synthetic 基线数量变化不能由 parser 自动接受。production 新增测试必须由 production plan 单独冻结，不得混入 41-test 基线。

`test_source_identity.json` 至少封存以下五个必需入口文件：

```text
tests/test_capd_proactive_stage11_v2.py
tests/test_capd_proactive_stage11_v2_production.py
tests/test_capd_proactive_stage10.py
tests/test_capd_proactive_stage10_v2.py
tests/test_capd_proactive_stage11.py
```

production implementation plan 必须冻结完整、排序、唯一的 POSIX path 成员白名单。该集合除五个入口文件外，还必须包含它们在收集和执行上述精确测试时加载的全部本地直接与传递 import，包括 test helper；与 generation/verifier source manifests 重复的生产模块仍可重复记录，不得以“已由另一 manifest 覆盖”为由省略测试执行闭包。禁止目录 glob、运行时自动扩展白名单或静默忽略缺失文件。

新增 schema `configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json`。`test_source_identity.json` 的 exact field set 为：

```text
schema_version
contract_id
audit_id
approved_production_design_sha256
approved_production_plan_sha256
members
members_sha256
member_count
test_source_pre_snapshot_sha256
test_source_post_snapshot_sha256
test_sources_unchanged
```

`members` 保存每个成员的精确 `{path,length,sha256}`。前后 snapshot 的成员集合必须与批准 plan 白名单逐项相等，并且每条记录完全相同。测试入口或 helper 在执行前后发生新增、删除、替换、长度或 SHA 变化时，审计失败；`41/41` 或 `6/6` 文本不能覆盖该失败。

### 7.6 冻结树合同

`frozen_tree_before.json` 与 `frozen_tree_after.json` 对以下树保存按 POSIX 相对路径排序的精确 `{path,length,sha256}`：

- Stage8 r5 权威目录；
- Stage9 root，包含 immutable/failed evidence；
- Stage10 root，包含 generation 与外置 release receipts；
- Stage11 v1 output；
- Stage4/7 frozen checkpoints。

`frozen_tree_before.json` 与 `frozen_tree_after.json` 使用同一 deterministic snapshot schema，只包含五棵命名树及其排序记录，不包含时间戳、阶段名或绝对路径。`frozen_tree_comparison.json` 必须记录每棵树的 before/after record count、canonical snapshot SHA 和 `identical=true`。任一成员新增、删除、长度变化或 SHA 变化都使 input audit 失败。

新增通用 schema：

```text
configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json
configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json
```

snapshot exact field set 为 `schema_version`、`contract_id`、`roots`。`roots` 固定为五个按 `root_id` 排序的对象；每个对象的 exact field set 为 `root_id`、`repository_relative_root`、`exists`、`members`，其中 `members` 是按 POSIX path 排序的 `{path,length,sha256}`。不存在的声明根使用 `exists=false` 与空 `members`，不得与存在但为空的根混淆。comparison exact field set 为 `schema_version`、`contract_id`、`comparisons`、`identical`；每个 comparison 的 exact field set 为 `comparison_id`、`baseline_snapshot_sha256`、`observed_snapshot_sha256`、`per_root_comparison`、`identical`。input audit 使用一项 before/after comparison，generation 与 verification 各使用 sealed/pre 和 sealed/post 两项 comparison。phase 与 wall-clock 信息只能写入 run state 或 command log，不进入 deterministic snapshot。

此前人工观察到的记录数为 Stage8 `181`、Stage9 `64`、Stage10 `69`、Stage11 v1 `0`、Stage4/7 `732`。这些数值只作为重新捕获时的预期检查，不替代重新保存的完整记录和 SHA。

### 7.7 Source identity 证据

`source_identity.json` 必须绑定：

- approved production-design SHA；
- approved production-plan SHA；
- production config SHA；
- result schema SHA；
- generation source manifest path、file SHA、`members_sha256`、member count；
- verifier source manifest path、file SHA、`members_sha256`、member count；
- source pre/post snapshot SHA；
- Git commit 和工作树 dirty 诊断；
- source pre/post snapshot 完全一致。

source manifest file SHA 与 `members_sha256` 是两个独立字段，不能互相替代。

### 7.8 Input-audit receipt schema

新增独立 schema：

```text
configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json
```

`input_audit_receipt.json` 的 exact field set 固定为：

```text
schema_version
contract_id
audit_id
approved_production_design_sha256
approved_production_plan_sha256
production_config_sha256
production_result_schema_sha256
generation_source_manifest_sha256
generation_source_members_sha256
generation_source_member_count
verifier_source_manifest_sha256
verifier_source_members_sha256
verifier_source_member_count
test_source_identity_sha256
test_source_pre_snapshot_sha256
test_source_post_snapshot_sha256
test_sources_unchanged
audit_commands_sha256
synthetic_allowlist_log_sha256
production_enablement_tests_log_sha256
legacy_semantic_tests_log_sha256
real_upstream_audit_stdout_sha256
synthetic_test_count
production_enablement_test_count
legacy_semantic_test_count
stage8_input_verified
stage9_input_authorized
stage10_input_authorized
stage8_input_receipt_sha256
stage9_input_receipt_sha256
stage10_input_receipt_sha256
standard_source_manifest_sha256
sorted_job_ids_sha256
standard_job_count
standard_workload_count
frozen_tree_before_sha256
frozen_tree_after_sha256
frozen_tree_comparison_sha256
frozen_trees_unchanged
generation_source_set_match
repository_revision_match
sealed_dual_verifier_attestation
current_live_replay_compatibility
input_audit_verified
stage11_execution_authorized
stage11_formally_verified
test_used_for_parameter_selection
synthetic_test_only
```

固定值为：schema `capd_proactive_stage11_v2_input_audit_receipt_v1_0`、contract `CAPD-PROACTIVE-STAGE11-2.0`、audit ID `stage11-input-audit-v2-r1`、synthetic count `41`、legacy count `6`、Standard job/workload count `48/6`。三项 input gate、四个 canonical 上游对象的独立逐字节重建、`test_sources_unchanged`、`frozen_trees_unchanged`、`generation_source_set_match`、sealed attestation 和 `input_audit_verified` 必须通过；live replay 为 `NOT_VERIFIABLE`、execution/formal 状态 false、Test selection false、synthetic false。`repository_revision_match` 保存实际布尔值并要求 capture/verifier 一致，但明确排除在 authorization predicate 外。

该 receipt 不能包含 execution authorization SHA、future run SHA、verification、final approval 或 final-status SHA。

### 7.9 Package manifest 与外部 SHA

package 使用以下规则：

- `manifest.json` 包含 schema、contract、phase=`input_audit` 和包括四个 canonical 上游对象、`test_source_identity.json` 在内的全部 payload SHA；
- manifest 排除自身和 `SHA256SUMS`；
- `SHA256SUMS` 包含 manifest 和全部 payload，排除自身；
- exact member set、排序、重复条目、路径规范和每个 SHA 均独立重算；
- input-audit receipt SHA、manifest SHA 和 checksums SHA 均由 package 外部报告；
- execution authorization 必须同时绑定这三个外部值。

篡改 receipt 或任一日志后，即使重算 package manifest/checksums，也必须因外部预期 receipt/package SHA 不匹配而失败。

## 8. Production Config

新增独立 config 与 schema，不覆盖 synthetic 基线：

```text
configs/finals/capd_proactive_stage11_v2_production.json
configs/finals/capd_proactive_stage11_v2_production_config_schema.json
```

production schema family 同时新增并冻结：

```text
configs/finals/capd_proactive_stage11_v2_production_result_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json
configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json
configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json
configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json
configs/finals/capd_proactive_stage11_v2_production_verification_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_approval_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json
```

这些 schema 是现有 v2 synthetic schema 的 production-specific 后继，不修改或放宽历史 synthetic schema。

production config 必须固定：

- contract 与 production revision；
- approved production-design path/SHA/status；
- approved production-plan path/SHA/status；
- `run_id=stage11-standard-cost-profiles-v2-r1`；
- Stage8 r5、Stage9 v2-r3、Stage10 v2-r2 精确路径；
- Stage10 三个外部 anchor SHA；
- input-audit package identity、预期目录和 receipt schema；
- generation/verifier source manifest paths；
- Standard 48-job exact membership；
- 四个 Cost profile；
- `main_b_max=2`；
- `authorized_scope=offline_cost_profiles_only`；
- `expected_result_rows=192`；
- watermark、label-weight、额外批量/容量敏感性、模型组件消融为 `BLOCKED`；
- `test_used_for_parameter_selection=false`。

config 不保存 input-audit receipt、manifest 或 checksum 的实际 SHA。这三个值在 source manifest 冻结之后才产生，必须由 execution authorization 和运行时 CLI 外部提供。否则 config 会通过 source manifest 反向依赖未来 audit package，形成循环。

config 中的 `production_branch_available=true` 只表示代码具备 production preflight，不是执行授权。真正授权只能来自命令行提供的 execution authorization receipt 和外部 expected SHA。config 不保存 authorization receipt 文件本身，也不允许仅通过把现有 `production_execution_enabled` 改为 true 启动 production。

## 9. Execution Authorization

### 9.1 独立 schema 与目录

新增 production-only schema：

```text
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json
```

建议 receipt package：

```text
outputs/capd_proactive_stage11_v2/
  authorization_receipts/stage11-standard-cost-profiles-v2-r1/execution/
    execution_authorization_receipt.json
    manifest.json
    SHA256SUMS
```

签发该 receipt 和批准其外部 SHA 是独立审批动作，本设计不授权。

### 9.2 必需绑定

execution authorization receipt 的 exact field set 固定为：

```text
schema_version
contract_id
production_revision
run_id
approved_production_design_sha256
approved_production_plan_sha256
production_config_sha256
production_result_schema_sha256
production_run_identity_schema_sha256
production_run_state_schema_sha256
release_manifest_schema_sha256
generation_source_manifest_sha256
generation_source_members_sha256
generation_source_member_count
verifier_source_manifest_sha256
verifier_source_members_sha256
verifier_source_member_count
test_source_identity_sha256
test_source_pre_snapshot_sha256
test_source_post_snapshot_sha256
test_sources_unchanged
input_audit_receipt_sha256
input_audit_manifest_sha256
input_audit_checksums_sha256
sealed_frozen_tree_after_sha256
standard_source_manifest_sha256
sorted_job_ids_sha256
standard_job_count
standard_workload_count
stage8_input_receipt_sha256
stage9_input_receipt_sha256
stage10_input_receipt_sha256
stage10_generation_freeze_receipt_sha256
stage10_readiness_receipt_sha256
stage10_final_status_receipt_sha256
frozen_cost_profiles_sha256
main_b_max
authorized_scope
expected_result_rows
blocked_lanes
stage11_execution_authorized
synthetic_test_only
test_used_for_parameter_selection
future_output_hashes_absent
approval_authority
approval_reference
```

固定值为 production revision `stage11-v2-production-r1`、run ID `stage11-standard-cost-profiles-v2-r1`、Standard count `48/6`、`main_b_max=2`、scope `offline_cost_profiles_only`、row count `192`、execution true、synthetic false、Test selection false、test sources unchanged true、future output hashes absent true。`blocked_lanes` 必须与第 10.3 节集合精确相等。`sealed_frozen_tree_after_sha256` 必须等于已获外部 SHA 批准的 input-audit receipt 所绑定 package member SHA。

receipt 不得绑定尚不存在的 result、run manifest、verification receipt、final approval 或 final-status SHA。

### 9.3 Preflight 顺序

runner 必须在任何 production `mkdir` 前依次完成：

1. config exact schema/status/SHA；
2. approved production design/plan external SHA；
3. generation/verifier source manifest exact closure 与当前字节匹配；
4. input-audit receipt/package 的三个外部 SHA 与全部语义字段；
5. execution authorization receipt/package 外部 SHA；
6. receipt 与 config/run/source/input bindings 逐项相等；
7. Stage8/9/10 input receipt、Standard source manifest 与四个 sealed canonical member SHA 再校验；
8. 从当前真实只读上游重建五棵树的 deterministic snapshot，在内存中与 sealed `frozen_tree_after.json` 逐文件、逐长度、逐 SHA 相等，并得到 `pre_generation_continuity_snapshot_sha256`；
9. output path capability、唯一 run ID、目标不存在；
10. pre-source snapshot；
11. 只有全部通过后才创建临时 generation 目录，并把已校验的 pre-generation snapshot 字节写入临时目录。

任一失败返回 `BLOCKED` 或 `NOT_VERIFIABLE`，且 production run 目录不存在。

## 10. Production Generation Contract

### 10.1 精确结果集合

结果必须是：

```text
48 Standard jobs x 4 Cost profiles = 192 rows
```

每个 `(source_job_id, cost_profile)` 组合必须恰好出现一次。禁止仅校验总数；必须比较完整笛卡尔积、job ID 唯一性、workload/policy/seed 多重集合和 profile 名称集合。

四个 profile 固定为：

| Profile | DRAM hit | NVM read | NVM write | Demotion |
|---|---:|---:|---:|---:|
| `read_light` | 1 | 2 | 4 | 8 |
| `default` | 1 | 2 | 8 | 10 |
| `write_expensive` | 1 | 2 | 12 | 10 |
| `migration_expensive` | 1 | 2 | 8 | 20 |

`NVM write` 是 NVM 写访问成本；`demotion` 是 DRAM 到 NVM 迁移成本。

### 10.2 重算语义

每行只能使用对应 Stage8 job `result.json.metrics` 的整数：

```text
dram_hits
nvm_reads
nvm_writes
total_demotions
raw_access_count
reactive_demotions
proactive_demotions
emergency_demotions
```

weighted cost 由四项整数计数与 profile 权重直接计算。`weighted_cost_per_access` 只在 `raw_access_count>0` 时计算；否则 JSON 为 `null`，CSV/Markdown 为 `N/A`。禁止从浮点均值反推访问数，禁止以 0 替代缺失值，禁止估计 Stage9/Stage10 数值。

### 10.3 明确阻塞的 lanes

production result 只能包含 `offline_cost_profiles` lane。以下内容只出现在 run state/report 的阻塞列表，不生成数值行：

- watermark sensitivity；
- label-weight sensitivity；
- capacity sensitivity；
- `b_max=1/4` batch sensitivity；
- Top-1/Top-b 额外 replay；
- `CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState`；
- inference masking diagnosis；
- Stage9 CPU/perf/RSS 新测量；
- Stage10 新异步 scenario；
- 真实系统开销或真实异步性能。

主配置 `b_max=2` 作为输入 provenance 保持不变。它不能被 analysis-only grid 覆盖。

### 10.4 Generation 状态

generation 成功只能产生：

```text
stage11_generation_complete_pending_independent_verification
```

runner 不得写 `stage11_generation_verified=true`、`stage11_final_approval_verified=true` 或 `stage11_formally_verified=true`。192 行继续使用 `evidence_status=candidate-ready` 和 `evidence_mode=offline_raw_counter_recompute`。后续 independent verification 与 final-status 只新增独立 receipt，不改写 result 文件字节。

### 10.5 上游连续性

upstream continuity 的权威基线是 input-audit package 中 sealed `frozen_tree_after.json` 的原始 canonical 字节。production preflight、generation 完成后、independent verification 开始前和 independent verification 完成后都必须重新扫描以下全部五棵树，而不是只重查 Stage8/9/10 receipt：

1. Stage8 r5；
2. Stage9 root；
3. Stage10 root；
4. Stage11 v1 output；
5. Stage4/7 frozen checkpoints。

每次 snapshot 都使用第 7.6 节相同的 deterministic schema，并逐项比较 exact root identity、成员集合、`path`、`length` 与 `sha256`。只比较记录数、根目录摘要或 receipt SHA 不足以通过。pre-generation snapshot 必须在任何 production `mkdir` 前在内存中通过；post-generation snapshot 必须在发布 run 目录前通过。任一差异都令 generation fail closed，临时 run 不得 seal 或提升为正式 run。

## 11. Production Artifacts

run 目录 exact artifacts 固定为：

```text
stage11_v2_config.json
run_identity.json
run_state.json
input_audit_binding.json
input_audit_receipt.json
execution_authorization_binding.json
execution_authorization_receipt.json
stage8_standard_input_receipt.json
stage9_input_receipt.json
stage10_input_receipt.json
standard_source_manifest.json
frozen_grid.json
generation_source_manifest.json
verifier_source_manifest.json
sealed_frozen_tree_after.json
pre_generation_continuity_snapshot.json
post_generation_continuity_snapshot.json
generation_continuity_comparison.json
stage11_v2_results.json
stage11_v2_results.csv
stage11_v2_report.md
manifest.json
SHA256SUMS
```

不得增加、缺失或重命名成员。manifest 排除自身与 `SHA256SUMS`；checksums 包含 manifest、排除自身。所有输入 receipt 与 sealed snapshot 都是只读副本或 canonical 对象，不得修改上游原件或 input-audit package 原件。`generation_continuity_comparison.json` 必须把 sealed、pre-generation、post-generation 三份 snapshot 的 file SHA、每棵树 record count 和 `identical=true` 逐项绑定。

`input_audit_binding.json` 精确记录 audit ID、原 package path、receipt SHA、manifest SHA 和 checksums SHA。`execution_authorization_binding.json` 对 execution authorization package 记录同样的三重外部 SHA。两个 binding 都必须满足各自 production schema。

`run_identity.json` 必须绑定：

- run ID、contract、production revision；
- approved production design/plan SHA；
- config/result schema SHA；
- input-audit receipt/package SHA；
- execution authorization receipt/package SHA；
- generation/verifier source identity；
- Stage8/9/10 input receipt SHA；
- Standard source manifest 与 sorted job IDs SHA；
- frozen Cost profile/grid SHA；
- `sealed_frozen_tree_after_sha256`；
- `pre_generation_continuity_snapshot_sha256`；
- Git commit 与 source snapshot；
- `expected_result_rows=192`；
- `test_used_for_parameter_selection=false`。

`run_identity.json` 在 generation 前固定，因此不得绑定尚未产生的 post-generation snapshot。最终 `run_state.json` 必须绑定 `sealed_frozen_tree_after_sha256`、pre/post-generation snapshot SHA、`generation_continuity_comparison_sha256` 和 `upstream_continuity_verified=true`；这组字段与 manifest/checksums 一起在 generation seal 时固定。

## 12. Independent Verification

independent verifier 必须在单独批准后运行，并且：

1. 不导入 generation module、runner 或 Cost helper。
2. 独立重建 verifier source manifest 和 closure。
3. 校验 input-audit 与 execution authorization 的外部 SHA。
4. 在创建 verification package 目录前重建五棵真实上游树并与 sealed snapshot 逐项相等，保存为 pre-verification snapshot。
5. 独立读取 Stage8 r5，重建精确 48-job Standard source set。
6. 独立校验每个 job result SHA、semantic SHA 和原始整数计数。
7. 独立计算四个 Cost profile 的 192 行。
8. 比较完整 `(source_job_id, cost_profile)` 集合，不只比较数量或 aggregate。
9. 校验 JSON/CSV 一致、`null`/`N/A` 语义、manifest/checksums 和 run identity/run state continuity bindings。
10. 校验所有 blocked lanes 没有数值结果。
11. 校验 generation 前后 source snapshot 一致。
12. verifier 完成后再次重建五棵真实上游树，与 sealed snapshot 和 pre-verification snapshot 逐项相等。

verification 成功只能产生 `stage11_generation_verified_pending_final_approval`，并写入独立 verification receipt package。它不自动签发 final approval。

verification package 的 exact member set 固定为：

```text
verification_receipt.json
sealed_frozen_tree_after.json
pre_verification_continuity_snapshot.json
post_verification_continuity_snapshot.json
verification_continuity_comparison.json
manifest.json
SHA256SUMS
```

pre-verification snapshot 必须在 verification package `mkdir` 前在内存中通过，随后才可写入临时 package。post-verification 不一致时 package 不得发布。`verification_continuity_comparison.json` 必须绑定 sealed、pre-verification、post-verification 三份 snapshot SHA、每棵树 record count 与 `identical=true`。verification manifest 排除自身和 `SHA256SUMS`；checksums 包含 manifest 与全部 payload、排除自身；exact member set、排序和 SHA 均由 verifier 重新检查。

`verification_receipt.json` 除现有 generation/result/source 绑定外，必须包含：

```text
sealed_frozen_tree_after_sha256
pre_generation_continuity_snapshot_sha256
post_generation_continuity_snapshot_sha256
pre_verification_continuity_snapshot_sha256
post_verification_continuity_snapshot_sha256
generation_continuity_comparison_sha256
verification_continuity_comparison_sha256
upstream_continuity_verified
```

其中所有 SHA 必须逐项等于 sealed generation/verification package 成员，`upstream_continuity_verified` 只有在四个时点的五棵树全部逐文件相等时才能为 true。

## 13. 四个独立审批门

### Gate 1: Production generation

前置条件：approved production plan、最终 source manifests、approved input-audit receipt SHA、approved execution authorization receipt SHA 全部存在并通过。批准只允许一次本地离线 generation。

### Gate 2: Independent verification

前置条件：generation 目录 sealed，精确 generation manifest/checksums/result/run identity SHA 已外部报告。批准只允许运行 independent verifier 和生成 verification package。

### Gate 3: Final approval

前置条件：verification receipt/package 已获得外部预期 SHA。final approval 由独立审批者签发，runner/verifier 不得自动生成。

### Gate 4: Final-status

前置条件：final approval receipt/package 已获得外部预期 SHA。final-status consumer 独立校验 generation、verification、approval 全链后，才能产生 `stage11_formally_verified=true`。

任何 Gate 的批准不自动批准下一 Gate。失败不得修补既有 sealed 目录；必须使用新 revision/run ID 重新开始。

### 13.5 Release receipt 共同绑定

production verification、final approval 和 final-status receipt 都必须在各自现有 v2 无环字段基础上额外绑定：

- approved production-design SHA；
- approved production-plan SHA；
- production revision 与唯一 run ID；
- input-audit receipt、manifest、checksums SHA；
- execution authorization receipt、manifest、checksums SHA；
- production config/result/source identity；
- Standard source manifest、sorted job IDs、48-job/六-workload断言；
- sealed frozen-tree baseline、generation/verification 四个 continuity snapshot SHA 与 continuity comparison SHA；
- `upstream_continuity_verified=true`；
- `test_used_for_parameter_selection=false`；
- `synthetic_test_only=false`。

verification 再绑定 generation run identity/state/result/manifest/checksums；final approval 再绑定 verification receipt/manifest/checksums；final-status 再绑定 final approval receipt/manifest/checksums。每个 package 都要求 receipt 外部 expected SHA，且不得由上一步工具自动签发。

## 14. Fail-Closed 状态语义

| 条件 | 状态 | 行为 |
|---|---|---|
| Step 3 只有聊天确认，无 package | `NOT_VERIFIABLE` | 不签发 execution authorization |
| input-audit receipt/package 缺失或 SHA 错 | `NOT_VERIFIABLE` | 不创建 production run |
| 四个 canonical 上游对象缺失、非 canonical 或独立重建字节不同 | `NOT_VERIFIABLE` | input audit 失败 |
| test-source 白名单、前后 snapshot 或 helper closure 不一致 | `NOT_VERIFIABLE` | input audit 失败 |
| input audit 完整但 execution receipt 未批准 | `BLOCKED` | 不创建 production run |
| approved production-plan SHA 错或 plan 未批准 | `NOT_VERIFIABLE` | preflight 失败 |
| source manifest 与当前代码不一致 | `NOT_VERIFIABLE` | 重新冻结并重做 audit/authorization |
| `repository_revision_match` 为实际 true 或 false 且其余 sealed Stage10 chain 完整 | 仅记录诊断 | 不参与授权，保持 live replay `NOT_VERIFIABLE` |
| production 前、generation 后或 verification 前后任一 frozen-tree 记录不同 | `NOT_VERIFIABLE` | 不创建或不发布对应 package |
| production run ID 已存在 | `BLOCKED` | 不覆盖、不追加、不修补 |
| 结果不是精确 192 行笛卡尔积 | generation failed | 不 seal |
| 未批准 lane 产生数值行 | generation failed | 不 seal |
| generation 完成但 verification 未批准 | pending | formal status 为 false |
| verification 完成但 final approval 缺失 | pending | formal status 为 false |
| final approval 存在但 final-status 未批准 | pending | formal status 为 false |

## 15. 负向测试矩阵

implementation plan 至少覆盖：

| ID | 负向场景 | 预期 |
|---|---|---|
| P01 | 状态文档写通过但 input-audit receipt 不存在 | 拒绝 |
| P02 | 只提供聊天摘要或复制的 stdout | 拒绝 |
| P03 | synthetic log 不是精确 allowlist/count | 拒绝 |
| P04 | production fixture log 的 module/count/ID 与 plan 不同 | 拒绝 |
| P05 | legacy log 少一个、多一个或测试 ID 错 | 拒绝 |
| P06 | audit stdout 三项上游门禁任一不是 true | 拒绝 |
| P07 | before/after 数量相同但一个文件被替换 | 拒绝 |
| P08 | input-audit 期间 production run 目录被创建 | 拒绝 |
| P09 | 篡改 audit receipt 后重算 manifest/checksums | 外部 receipt SHA 拒绝 |
| P10 | 篡改日志后重算全部 package hash | 外部 package SHA 拒绝 |
| P11 | generation source manifest stale | 拒绝 |
| P12 | verifier source manifest 漏传递依赖 | 拒绝 |
| P13 | source 在 audit 或 generation 中变化 | 拒绝并清理临时目录 |
| P14 | 使用旧 approved-plan SHA | 拒绝 |
| P15 | 使用 synthetic authorization 进入 production | 拒绝 |
| P16 | execution receipt run ID 与 config 不同 | 拒绝 |
| P17 | execution receipt 未绑定 input-audit 三个外部 SHA | 拒绝 |
| P18 | authorization 绑定未来 result SHA | schema 拒绝 |
| P19 | 191 或 193 行结果 | 拒绝 |
| P20 | 192 行但重复一个 job/profile 并遗漏另一个 | 拒绝 |
| P21 | Pressure track job 混入 | 拒绝 |
| P22 | 第五个 Cost profile 混入 | 拒绝 |
| P23 | watermark/label-weight/组件消融生成数值 | 拒绝 |
| P24 | `raw_access_count=0` 时写 0.0 | 拒绝，必须为 `null` |
| P25 | `b_max=1/4` 覆盖主配置 | 拒绝 |
| P26 | Test 被用于选择 profile、参数或 checkpoint | 拒绝 |
| P27 | 任一实测 `repository_revision_match` 布尔值被当作 sealed Stage10 授权条件 | 诊断分类测试失败 |
| P28 | repository revision 相同后自动把 live replay 标 verified | 拒绝 |
| P29 | production writer 指向 Stage8/9/10/Stage11 v1/checkpoint | capability guard 拒绝 |
| P30 | 未批准 independent verification 就生成 verification receipt | 拒绝 |
| P31 | verification 自动签发 final approval/final-status | 拒绝 |
| P32 | 审计包缺少四个 canonical 上游对象中的任一个 | 拒绝 |
| P33 | 篡改 canonical input receipt 后重哈希整个 package | 独立上游重建逐字节比较拒绝 |
| P34 | canonical 对象解析后语义相同但 JSON 字节非 canonical | 拒绝 |
| P35 | 测试返回 `41/41`、`6/6`，但测试入口源码被弱化后重哈希 | test-source 外部 identity 拒绝 |
| P36 | test-source 成员漏一个本地传递 helper | exact plan whitelist/closure 拒绝 |
| P37 | test-source 前后数量相同但一个成员被替换 | 拒绝 |
| P38 | production `mkdir` 前五棵树中一条记录变化 | 拒绝且 run 目录不存在 |
| P39 | generation 后五棵树数量相同但替换一个文件 | generation 不 seal |
| P40 | verification 前或后上游 snapshot 与 sealed baseline 不同 | verification package 不发布 |
| P41 | continuity snapshot 被篡改后重算 package hash | receipt 与外部 package SHA 拒绝 |
| P42 | receipt 把实测 `repository_revision_match=true` 改写为 false，或反向改写 | capture/verifier 诊断不一致，拒绝 |
| P43 | `repository_revision_match=true` 时自动把 live replay 升为 verified | 拒绝 |

所有 synthetic production tests 必须写系统临时目录，并机械证明没有成功打开真实上游。真实 input audit 和 legacy semantic tests 只在未来独立 capture/seal 批准后执行。

## 16. 上游只读与输出路径

始终只读：

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`；
- `outputs/capd_proactive_stage9/`；
- `outputs/capd_proactive_stage10/`；
- `outputs/capd_proactive_stage11/`；
- Stage4/7 frozen checkpoints。

Stage11 v2 只允许写：

- 经单独批准的 `input_audits/<audit_id>/`；
- 经单独批准的 `authorization_receipts/<run_id>/execution/`；
- 经 execution authorization 批准的唯一 `<run_id>/`；
- 后续各自批准的 `release_receipts/<run_id>/verification|final-approval|final-status/`。

每类 writer 使用不同 capability，不得用 generation capability 写 audit/authorization/release 目录，也不得绕过 CLI 直接传裸路径。

## 17. 论文与报告边界

input-audit receipt 通过只能证明：

- 当前 Stage11 production 输入链可被机器校验；
- Stage8 Standard 48-job raw counters 可用于离线 Cost 重算；
- Stage9 在其现有合同范围内是 authorized input；
- Stage10 sealed deterministic simulation 是 authorized input；
- `repository_revision_match` 的实测诊断值已被记录；无论实际为 true 或 false，都不改变 sealed Stage10 evidence 的授权结论，也不升级 live replay compatibility。

它不能证明：

- Stage11 production generation 已完成；
- 192 行结果已独立验证或 formally verified；
- 新的真实 CPU latency、cycles、instructions、task-clock、RSS 或模型内存；
- 真实 NVM、kernel、并发、前台端到端延迟或真实系统异步性能；
- watermark、label-weight、容量或批量最优性；
- 正式模型组件消融；
- Stage9/Stage10 数值可直接写成六 workload Standard-only 主表 aggregate。

## 18. 设计验收条件

进入 production implementation plan 前，评审需要确认：

1. input-audit package 是 execution authorization 的强制前置输入，而不是状态文档替代品；
2. audit、production run 和四个 release gate 使用不同 identity、目录和 capability；
3. 新 run ID 和未来 approved production-plan SHA 均被 config/receipt/run identity 绑定；
4. source manifests 在 production 代码稳定后冻结，审计和 authorization 都引用最终值；
5. 四个 canonical 上游对象由 capture runner 封存，并由独立 verifier 从真实上游重建后逐字节比较；
6. 精确测试源码与本地传递 helper 由独立 test-source identity 及前后 snapshot 绑定；
7. production 与 verification 在四个时点对全部五棵冻结树执行逐文件连续性校验，并把 SHA 绑定进 run/release evidence；
8. 结果集合固定为 48 x 4 = 192，未批准 lanes 不生成数值；
9. Stage10 source-set/repository-revision/sealed-attestation/live-replay 四项语义保持分离；
10. input audit、generation、verification、final approval、final-status 之间不存在未来哈希循环；
11. 本地 execution 与服务器测量边界清楚；
12. 本文没有授权任何实现、receipt 签发或正式运行。

## 19. 下一审批门

当前只请求 production enablement 设计评审。若本文获批，下一步仅可：

1. 将本文状态改为 `DESIGN_APPROVED`；
2. 在本文外计算最终 approved production-design SHA；
3. 编写独立 production implementation plan 并提交审批。

在 implementation plan 再次明确获批前，不得修改 Stage11 源码、config、schema、source manifest 或状态文档，不得重新捕获/封存 Step 3，不得签发 input-audit/execution/final receipt，不得运行 production，不得 commit 或 push。
