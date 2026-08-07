# CAPD Stage11 v2 Production Enablement 实施计划

## Material Passport

- Artifact Type: Implementation plan
- Artifact ID: `capd-stage11-v2-production-enablement-plan-20260807`
- Version Label: `plan-v1-draft`
- Origin Skill: `experiment-agent`
- Origin Mode: `plan`
- Verification Status: `PLAN_REVIEW_PENDING`
- Plan Status: `PLAN_APPROVED`
- Approved Design: `docs/superpowers/specs/2026-08-07-stage11-production-enablement-design.md`
- Approved Design SHA256: `ec00fdaeac4084f638fbf6da866d4444badd26dfac95eef061e137a5a26ba356`
- Approved Plan SHA256: `EXTERNALLY_REPORTED_AFTER_PLAN_APPROVAL`
- Implementation Authorization: `NOT_GRANTED`
- Source-Manifest Freeze Authorization: `NOT_GRANTED`
- Input-Audit Capture/Seal Authorization: `NOT_GRANTED`
- Execution Authorization Receipt Issuance: `NOT_GRANTED`
- Production Generation Authorization: `NOT_GRANTED`
- Independent Verification Authorization: `NOT_GRANTED`
- Final Approval Authorization: `NOT_GRANTED`
- Final-Status Authorization: `NOT_GRANTED`

本文只规定 production enablement 的实施顺序、精确文件边界、测试合同和后续审批门。`PLAN_REVIEW_PENDING` 不授权修改 Stage11 实现、运行测试或审计、冻结 source manifests、创建 `outputs/capd_proactive_stage11_v2/`、签发 receipt、执行 production、commit 或 push。

计划获批后必须先把状态改为 `PLAN_APPROVED`，再在本文之外计算最终 approved-plan SHA。本文不引用自身 SHA；所有 production config、source manifest、input-audit receipt、execution authorization、run identity 和 release receipt 都从外部提供的 approved-plan SHA 绑定。

## 1. 目标与成功条件

本计划把当前 synthetic-only Stage11 v2 迁移为仍然 fail closed 的 production-capable 实现。唯一 production 数据任务是读取 Stage8 r5 的精确 48 个 Standard job 原始整数计数，对四个预先固定的 Cost profile 生成 `48 x 4 = 192` 行离线结果。

实施成功必须同时满足：

1. 历史 Stage11 v2 五个源码文件、synthetic config/schema/source manifests 与 41-test 基线全部保持逐字节兼容；
2. production 使用独立 config、schema、source manifests、authorization 和 output identity；
3. input-audit package 封存四个 canonical 上游对象，并由独立 verifier 从真实上游逐字节重建；
4. 测试日志绑定精确 test-source whitelist、传递依赖和执行前后源码 snapshot；
5. generation/verification 在四个时点逐文件比较全部五棵冻结树；
6. production preflight 在任何 output `mkdir` 前验证 approved design/plan、source identity、input audit、execution authorization 与 upstream continuity；
7. generation 只产生 candidate-ready 的 192 行，不产生 formally verified 状态；
8. verification、final approval、final-status 使用三个独立 release package 和三个后续审批门；
9. watermark、label-weight、capacity、额外 batch、Top-1/Top-b、组件消融及新增 Stage9/10 测量保持 `BLOCKED`；
10. Test 不参与 profile、参数或 checkpoint 选择。

## 2. 非目标与环境

不重新训练、不选择 checkpoint、不运行 Stage8 replay、不新增 Stage9 Linux/perf/RSS 测量、不新增 Stage10 异步 scenario，不访问网络，不需要 GPU 或服务器。

技术栈保持 Python 3 标准库、`unittest`、UTF-8 strict JSON、CSV、SHA256 和 PowerShell。正式 generation 是本地确定性整数重算；服务器不属于本合同。

所有 fixture-only 测试使用系统临时目录并安装文件访问 audit hook。除获得独立 input-audit capture/seal 授权外，任何命令不得语义解析真实 Stage8/9/10、Stage11 v1 或 Stage4/7 checkpoint。

## 3. 写入与只读边界

### 3.1 始终只读

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`
- `outputs/capd_proactive_stage9/`
- `outputs/capd_proactive_stage10/`
- `outputs/capd_proactive_stage11/`
- Stage4/7 frozen checkpoints
- 现有 Stage11 v2 synthetic config/schema/source manifests
- 已批准 production design 及其外部 SHA

### 3.2 实施阶段允许新增或修改的候选文件

- Create: `qmap/proactive_stage11_v2_production.py`
- Create: `qmap/proactive_stage11_v2_production_guard.py`
- Create: `qmap/proactive_stage11_v2_production_verifier.py`
- Create: `scripts/run_capd_proactive_stage11_v2_production.py`
- Create: `scripts/verify_capd_proactive_stage11_v2_production.py`
- Create: `tests/test_capd_proactive_stage11_v2_production.py`
- Modify: `docs/CAPD_PROACTIVE_STAGE11_V2_PROTOCOL_CN.md`

以下历史文件及其现有 source manifests 在所有 production Tasks 中逐字节只读：

```text
qmap/proactive_stage11_v2.py
qmap/proactive_stage11_v2_guard.py
qmap/proactive_stage11_v2_verifier.py
scripts/run_capd_proactive_stage11_v2.py
scripts/verify_capd_proactive_stage11_v2.py
configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json
configs/finals/capd_proactive_stage11_v2_verifier_source_manifest.json
```

production 模块不得导入这三个历史 `qmap.proactive_stage11_v2*` 模块，也不得调用两个历史 script。`docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md` 在 input-audit package 已封存、独立验证并获得外部 SHA 批准前保持不变。实施阶段不修改现有 `tests/test_capd_proactive_stage11_v2.py` 的 15 个 class 或 41-test 基线；production tests 全部进入新模块。

### 3.3 新增 production config/schema 文件

```text
configs/finals/capd_proactive_stage11_v2_production.json
configs/finals/capd_proactive_stage11_v2_production_config_schema.json
configs/finals/capd_proactive_stage11_v2_production_result_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json
configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json
configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json
configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json
configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_verification_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_approval_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json
```

source manifest payload 文件只在 Task 12 的独立 freeze 授权后创建：

```text
configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest.json
configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest.json
```

## 4. 精确 Source Whitelists

source manifest 不包含自身、tests、fixtures、status/release 文档、`outputs/`、receipt、日志、`__pycache__` 或运行后会变化的文件。成员路径必须是排序、唯一的 POSIX repository-relative path；任一新增本地 import 或直接读取 schema 都要求先修订本计划并重新审批。

### 4.1 Production generation source whitelist

```text
configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json
configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json
configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json
configs/finals/capd_proactive_stage10_release_manifest_schema.json
configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json
configs/finals/capd_proactive_stage10_result_schema_v2.json
configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json
configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json
configs/finals/capd_proactive_stage10_v2_r2_config_schema.json
configs/finals/capd_proactive_stage10_verification_schema_v2_1.json
configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production.json
configs/finals/capd_proactive_stage11_v2_production_config_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json
configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_result_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json
configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json
configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json
configs/finals/capd_proactive_stage9_result_schema.json
qmap/proactive_cost.py
qmap/proactive_stage11_v2_production.py
qmap/proactive_stage11_v2_production_guard.py
scripts/run_capd_proactive_stage11_v2_production.py
```

精确成员数为 `30`。production runner 不得直接加载 verification/final approval/final-status schema，因此它们不进入 generation whitelist。

### 4.2 Production verifier source whitelist

```text
configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json
configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json
configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json
configs/finals/capd_proactive_stage10_release_manifest_schema.json
configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json
configs/finals/capd_proactive_stage10_result_schema_v2.json
configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json
configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json
configs/finals/capd_proactive_stage10_v2_r2_config_schema.json
configs/finals/capd_proactive_stage10_verification_schema_v2_1.json
configs/finals/capd_proactive_stage11_v2_frozen_tree_snapshot_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_binding_schema.json
configs/finals/capd_proactive_stage11_v2_input_audit_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production.json
configs/finals/capd_proactive_stage11_v2_production_config_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_binding_schema.json
configs/finals/capd_proactive_stage11_v2_production_execution_authorization_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_approval_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_final_status_evidence_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_generation_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_package_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_production_result_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_identity_schema.json
configs/finals/capd_proactive_stage11_v2_production_run_state_schema.json
configs/finals/capd_proactive_stage11_v2_production_verification_receipt_schema.json
configs/finals/capd_proactive_stage11_v2_production_verifier_source_manifest_schema.json
configs/finals/capd_proactive_stage11_v2_test_source_identity_schema.json
configs/finals/capd_proactive_stage11_v2_upstream_continuity_comparison_schema.json
configs/finals/capd_proactive_stage9_result_schema.json
qmap/proactive_stage11_v2_production_guard.py
qmap/proactive_stage11_v2_production_verifier.py
scripts/verify_capd_proactive_stage11_v2_production.py
```

精确成员数为 `32`。production verifier 不得导入或读取 `qmap/proactive_stage11_v2_production.py`、`qmap/proactive_cost.py` 或 production generation runner，也不得借用历史 `qmap/proactive_stage11_v2.py`；Cost 重算必须独立实现。

### 4.3 Test-source whitelist

```text
qmap/finals_config.py
qmap/proactive_cost.py
qmap/proactive_replay.py
qmap/proactive_stage10.py
qmap/proactive_stage10_v2.py
qmap/proactive_stage11.py
qmap/proactive_stage11_v2.py
qmap/proactive_stage11_v2_guard.py
qmap/proactive_stage11_v2_production.py
qmap/proactive_stage11_v2_production_guard.py
qmap/proactive_stage11_v2_production_verifier.py
qmap/proactive_stage11_v2_verifier.py
qmap/proactive_stage3.py
qmap/proactive_stage4.py
qmap/proactive_stage7_workloads.py
qmap/proactive_stage8_contract.py
qmap/qmap_generator.py
scripts/run_capd_proactive_stage10.py
scripts/run_capd_proactive_stage10_v2.py
scripts/run_capd_proactive_stage11_v2.py
scripts/run_capd_proactive_stage11_v2_production.py
scripts/verify_capd_proactive_stage11_v2.py
scripts/verify_capd_proactive_stage11_v2_production.py
tests/stage10_v2_test_support.py
tests/test_capd_proactive_stage10.py
tests/test_capd_proactive_stage10_v2.py
tests/test_capd_proactive_stage11.py
tests/test_capd_proactive_stage11_v2.py
tests/test_capd_proactive_stage11_v2_production.py
```

精确成员数为 `29`。该集合同时覆盖历史五个 Stage11 v2 文件、新增五个 production 文件、五个必需 test entry、Stage10 v2 test helper，以及 legacy tests 收集/执行时加载的本地传递闭包。production test 禁止新增白名单外本地 import；若确需新增，必须先修订并重新批准计划。

## 5. 实施任务

### Task 1：审批身份、历史基线与 RED 骨架

**文件：**

- Create: `tests/test_capd_proactive_stage11_v2_production.py`
- Read only: approved design、现有 v2 synthetic files

- [ ] 验证 approved design 状态为 `DESIGN_APPROVED` 且 SHA 精确等于本计划 Material Passport。
- [ ] 要求 approved plan 状态为 `PLAN_APPROVED`，但 SHA 只能由测试启动参数或环境中的外部值提供；错误、缺失或仍为 draft 时 fail closed。
- [ ] 对现有 synthetic config/schema/source manifests、15-class 名称和 41-test 数量保存字节 SHA baseline；任一文件缺失立即失败，不得条件跳过。
- [ ] 建立 production 测试模块和第 6 节精确 56-test allowlist，先证明 production 隔离、schema、capture、continuity、authorization、generation、monitoring 与 verification API 尚未满足合同。
- [ ] audit hook 拒绝 fixture-only 测试成功打开真实 Stage8/9/10/11/checkpoint 或 production root。

验收：RED 只来自尚未实现的 production 合同；历史 synthetic baseline 与真实上游均未改变。

### Task 2：Production config 与 schema family

**文件：**第 3.3 节全部 config/schema 文件。

- [ ] 新 config 固定 contract、`stage11-v2-production-r1`、run ID、approved design/plan identity、Stage8/9/10 路径、四个 Cost profile、`main_b_max=2`、192 rows 和 blocked lanes。
- [ ] config 不保存未来 input-audit package SHA、execution receipt SHA 或 generation result SHA。
- [ ] 所有 schema 使用 exact field set、`additionalProperties=false`、严格 enum/count/boolean/SHA 约束。
- [ ] package manifest schema 固定 phases：`input_audit`、`execution_authorization`、`generation`、`verification`、`final_approval`、`final_status`。
- [ ] generation run-state schema 与 verification receipt schema 固定 monitoring 子对象：`monitor_interval_seconds=5`、`hard_timeout_seconds=1800`、`termination_grace_seconds=10`、`attempt_count=1`、`automatic_retry_performed=false`、`timed_out`、`exit_code`、process-alive sample count 和 wall-clock diagnostics。
- [ ] JSON 缺失数值为 `null`；CSV/Markdown 显示 `N/A`。
- [ ] production schema 不修改或放宽现有 synthetic schema。

验收：fixture config 通过；错误 design/plan SHA、错误 run ID、第五 profile、非 192 rows、`b_max!=2` 和未阻塞 lane 均拒绝。

### Task 3：Canonical JSON、package 与 tree primitives

**文件：**

- Create: `qmap/proactive_stage11_v2_production.py`
- Create: `qmap/proactive_stage11_v2_production_verifier.py`
- Create: `qmap/proactive_stage11_v2_production_guard.py`

- [ ] canonical JSON 固定 UTF-8、无 BOM、递归 key 排序、紧凑分隔符和单个末尾 LF。
- [ ] package manifest 排除自身和 `SHA256SUMS`；checksums 包含 manifest 和全部 payload、排除自身。
- [ ] exact member set、排序、重复项、POSIX path、长度和 SHA 独立校验。
- [ ] frozen-tree snapshot 使用五个固定 root，区分 absent 与 present-empty，不写时间或绝对路径。
- [ ] comparison 支持 audit before/after、sealed/pre、sealed/post，逐 root 保存 record count 和 exact equality。
- [ ] guard 精确冻结六种不可互换 capability：`input_audit`、`execution_authorization`、`generation`、`verification`、`final_approval`、`final_status`。
- [ ] 每种 capability 同时绑定 phase、唯一 output root、audit/run ID、approved plan SHA 和一次性 nonce；writer 即使绕过 CLI 被直接调用，也必须重新校验全部绑定。
- [ ] capability 只允许写对应 phase 的 exact artifact set。任何较早 phase capability 写较晚 phase package、任何较晚 phase capability 回写较早 sealed package、不同 run/audit ID 复用均拒绝。

验收：非 canonical 等价 JSON、递归 hash、路径逃逸、symlink/reparse escape、重复 member 和 phase/capability 混用均拒绝；尤其 verification capability 不能写 final-approval/final-status，final-approval capability 不能写 final-status。

### Task 4：Input-audit capture 与独立重建接口

**文件：**

- Modify: `qmap/proactive_stage11_v2_production.py`
- Modify: `qmap/proactive_stage11_v2_production_verifier.py`
- Create: `scripts/run_capd_proactive_stage11_v2_production.py`
- Create: `scripts/verify_capd_proactive_stage11_v2_production.py`

- [ ] runner 增加 `--capture-input-audit`，默认拒绝真实上游；只有单独 capability、精确 audit ID 和显式 `--allow-real-upstream-audit` 才可读取真实 evidence。
- [ ] capture 从各自真实 gate 生成四个 canonical package member：Stage8/9/10 input receipts 与 Standard source manifest。
- [ ] capture 保存 commands、三类日志、source identity、test identity、frozen before/after/comparison 和 exact package envelope。
- [ ] independent verifier 增加 `--verify-input-audit`，不导入 generation module；从上游重新执行 Stage8 job SHA/semantic SHA、Stage9-native、Stage10 sealed-attestation gates。
- [ ] verifier 在临时目录重建四个 canonical 对象并逐字节比较，禁止仅比较 parsed semantics 或 receipt 自报 SHA。
- [ ] `repository_revision_match` 保存 capture/verifier 实测布尔值，不进入 authorization predicate；live replay 始终保持 `NOT_VERIFIABLE`。

验收：fixture-only positive package 通过；对象缺失、非 canonical、篡改后重哈希、错误 job set、错误 gate 和诊断值改写均 fail closed。

### Task 5：Test-source identity

**文件：**

- Modify: `qmap/proactive_stage11_v2_production.py`
- Modify: `qmap/proactive_stage11_v2_production_verifier.py`
- Modify: `tests/test_capd_proactive_stage11_v2_production.py`

- [ ] 实现第 4.3 节 29-member exact whitelist，不接受 glob、自动扩展或缺失文件跳过。
- [ ] 第一条测试命令前与最后一条 legacy test 后分别计算 `{path,length,sha256}` snapshot。
- [ ] `test_source_identity.json` 绑定 design/plan SHA、members SHA、member count、pre/post SHA 和 unchanged boolean。
- [ ] input-audit receipt 与 execution authorization 逐项绑定 test identity 和 pre/post snapshot SHA。
- [ ] 独立 verifier 重新扫描 whitelist 和本地 import closure；依赖遗漏、额外 import 或运行中源码变化均拒绝。
- [ ] 分别验证历史五个源码与两份历史 manifests 的当前字节仍满足历史 source identity，并验证五个 production 文件的 import closure 不引用历史 Stage11 v2 modules/scripts。

验收：测试输出仍显示相同 count，但测试或 helper 被弱化、替换、重哈希时 package 不通过；production import 泄漏或历史 source identity 漂移同样失败。

### Task 6：五棵冻结树连续性

**文件：**

- Modify: `qmap/proactive_stage11_v2_production.py`
- Modify: `qmap/proactive_stage11_v2_production_verifier.py`
- Modify: `scripts/run_capd_proactive_stage11_v2_production.py`
- Modify: `scripts/verify_capd_proactive_stage11_v2_production.py`

- [ ] input audit 保存五棵树的 deterministic before/after snapshot 和 comparison。
- [ ] production preflight 在任何 run `mkdir` 前于内存重算 pre-generation snapshot，并与 sealed after 逐记录相等。
- [ ] generation 结束、发布目录前生成 post-generation snapshot；差异时不 seal 临时 run。
- [ ] independent verification 在 package `mkdir` 前和 verifier 完成后重复同一检查。
- [ ] run identity 绑定 sealed baseline 与 pre-generation SHA；run state 绑定 generation pre/post/comparison；verification receipt 绑定四个 snapshot、两个 comparison 和 `upstream_continuity_verified=true`。

验收：成员数相同但替换文件、任一时点新增/删除/长度/SHA 变化、snapshot 篡改重哈希均拒绝。

### Task 7：Execution authorization 与 global preflight

**文件：**

- Modify: `qmap/proactive_stage11_v2_production.py`
- Modify: `qmap/proactive_stage11_v2_production_guard.py`
- Modify: `scripts/run_capd_proactive_stage11_v2_production.py`

- [ ] production-only execution schema 绑定 design/plan/config/result/run schemas、两份 source identity、input-audit 三个外部 SHA、test identity、sealed tree、Stage8/9/10 receipts、grid 与 blocked lanes。
- [ ] receipt 必须 `stage11_execution_authorized=true`、`synthetic_test_only=false`、`test_used_for_parameter_selection=false`、`future_output_hashes_absent=true`。
- [ ] runner 依照设计第 9.3 节顺序执行 preflight；任何失败时 production run 目录不存在。
- [ ] synthetic authorization/receipt、错误 run ID、旧 plan SHA、错误 audit SHA、未来 output hash 和 raw output path 均拒绝。

验收：fixture production capability 只能写测试临时根；production root、上游目录和 capability 绕过测试全部失败。

### Task 8：Production generation lifecycle

**文件：**

- Modify: `qmap/proactive_stage11_v2_production.py`
- Modify: `scripts/run_capd_proactive_stage11_v2_production.py`

- [ ] 增加 `--execute-production`，要求外部 execution receipt、receipt SHA、manifest SHA、checksums SHA 和 approved-plan SHA。
- [ ] 只读取 sealed Standard source manifest 对应的 48 个 Stage8 job integer counters。
- [ ] 独立连接 job manifest/result/semantic SHA，不从浮点均值反推访问数。
- [ ] 对四个 profile 生成精确 `(source_job_id,cost_profile)` 笛卡尔积 192 行。
- [ ] JSON/CSV/report、run identity/state、input bindings、frozen grid、continuity artifacts 和 package envelope 使用设计第 11 节 exact member set。
- [ ] public CLI 作为父进程 supervisor 只启动一个 generation worker；启动时及每 5 秒记录 process-alive，1800 秒硬超时后先请求终止，等待 10 秒仍存活则终止 worker process tree。
- [ ] worker 非零退出、monitor failure 或 timeout 时 `attempt_count=1`、`automatic_retry_performed=false`，不得自动重试、不得 seal run；私有 worker entry 不得绕过 supervisor/capability 直接调用。
- [ ] wall-clock start/end/duration、PID 与 alive samples 只写 `run_state.json.monitoring` 诊断，不进入 result rows、Cost 算术、source identity 或 deterministic result equality。
- [ ] 成功状态仅为 `stage11_generation_complete_pending_independent_verification`，rows 仅为 `candidate-ready`。

验收：191/193 rows、重复遗漏、Pressure job、第五 profile、blocked lane 数值、错误 demotion 语义、0 代替 null 和主 `b_max` 覆盖均拒绝。

### Task 9：Independent verification package

**文件：**

- Modify: `qmap/proactive_stage11_v2_production_verifier.py`
- Modify: `scripts/verify_capd_proactive_stage11_v2_production.py`

- [ ] verifier 不导入 generation runner/contract/Cost helper，独立实现 Standard set、integer counter 与 Cost 算术。
- [ ] 校验 generation exact artifacts、manifest/checksums、run identity/state、input/authorization bindings 和 blocked lanes。
- [ ] 重算完整 192-row JSON/CSV semantics，不只比较 aggregate/count。
- [ ] 保存 verification pre/post continuity artifacts 和 exact seven-member package。
- [ ] verification receipt 绑定 generation 与 verification continuity、generation result/run/package SHA 和 upstream identity。
- [ ] public verifier CLI 作为父进程 supervisor 只启动一个 verification worker，使用同一固定 `5/1800/10` 秒 monitor/timeout/grace 合同；timeout、非零退出或 monitor failure 不发布 verification package且不自动重试。
- [ ] verification receipt 的 monitoring 子对象记录单次执行与诊断；wall-clock/PID/alive samples 不参与独立 192-row equality 或正式结果相等判断。
- [ ] 成功状态仅为 `stage11_generation_verified_pending_final_approval`。

验收：generation module 泄漏、source manifest 空/多/少成员、错 members SHA、错 result row、错 continuity 或任一外部 SHA 均拒绝。

### Task 10：Final approval 与 final-status consumer

**文件：**

- Modify: `qmap/proactive_stage11_v2_production_verifier.py`
- Modify: `scripts/verify_capd_proactive_stage11_v2_production.py`
- Modify: production final receipt schemas

- [ ] final approval receipt 只由外部审批动作签发，绑定 verification receipt/manifest/checksums 与全部 inherited production identity。
- [ ] final-status consumer 校验 exact field set、schema、contract、design/plan、run identity、input audit、authorization、generation、verification、approval 和 Test isolation。
- [ ] verification、final approval、final-status 分别要求 `verification`、`final_approval`、`final_status` capability、exact manifest/checksum 和外部 expected receipt SHA；三者不得互换或向后继 phase 委托写权限。
- [ ] generation/verifier 不自动签发下一 gate receipt；fixture 只能产生 synthetic status，不能写 production root 或 formally verified 状态。

验收：错 run ID、错 verification SHA、字段缺失/增加、篡改后重哈希、synthetic receipt、自动签发和未来 hash cycle 全部拒绝；verification capability 写 final approval/final-status、final-approval capability 写 final-status 的交叉测试必须失败。

### Task 11：Protocol、fixture-only 验证与稳定化

**文件：**

- Modify: `docs/CAPD_PROACTIVE_STAGE11_V2_PROTOCOL_CN.md`
- Modify: `tests/test_capd_proactive_stage11_v2_production.py`
- Read only: historical v2 files and approved design/plan

- [ ] 协议文档分开记录 implemented、input-audit pending、execution blocked、generation pending、verification pending、final approval pending、final-status pending。
- [ ] 状态文档仍保留 `real-upstream semantic audit=NOT_RUN`，直到后续已批准 audit package 外部 SHA 存在。
- [ ] 运行第 6 节 15-class 41-test 基线和 56 个 production fixture tests；真实上游 successful-open count 必须为 0。
- [ ] 只允许对五棵只读树做 `{path,length,sha256}` 非语义前后扫描，且必须一致。
- [ ] 检查历史 synthetic config/schema/source manifests 字节 SHA 与 Task 1 baseline 相等。
- [ ] 检查 source pre/post snapshot；任何 implementation member 变化都返回 Task 2 重新验证。

验收：`41/41` 与 `56/56` 分开报告，均只表示 implemented/fixture-tested，不是 input audit、execution authorization 或 formally verified。

### Task 12：Production source manifests freeze

该 Task 需要独立 `SOURCE_MANIFEST_FREEZE_AUTHORIZED`，计划批准或 Task 11 通过都不自动授权。

- [ ] 确认代码/schema/tests 不再变化，Task 11 完整通过。
- [ ] 按第 4.1/4.2 节精确白名单生成两份新 production source manifests。
- [ ] 两份 manifest 绑定 approved design/plan SHA、member count、members SHA、完整 import closure 与 exclusions。
- [ ] 独立重建 member set，要求 generation `30/30`、verifier `32/32`。
- [ ] 保存执行前后 source snapshot，要求逐字节一致。
- [ ] 外部报告两份 manifest file SHA 与 members SHA；不写 input-audit package。

验收：依赖遗漏、Stage11 v1 泄漏、tests/status/release 输出混入、运行中 source 变化全部失败。完成后任何 source member 修改都使 freeze 失效并返回 Task 11。

### Task 13：Step 3 evidence recapture、seal 与独立 input-audit verification

该 Task 需要独立 `INPUT_AUDIT_CAPTURE_SEAL_AUTHORIZED`，并允许只读语义访问真实上游。

- [ ] 在任何 output 创建前保存 frozen-tree before snapshot。
- [ ] 单次运行精确 15-class `41/41`、production `56/56`、真实 `--audit-inputs` 和六项 legacy semantic tests。
- [ ] 保存完整 argv/stdout/stderr/exit/timeout/retry identity，禁止自动重试。
- [ ] 保存四个 canonical 上游对象、test-source identity、source identity、frozen after/comparison 和 exact package。
- [ ] 独立 verifier 从真实上游重建四对象并逐字节比较。
- [ ] 外部报告 input-audit receipt、manifest、checksums SHA；此 Task 不签发 execution authorization。

验收：41/41、56/56、6/6、三项上游 gate、source identities、test identity、five-tree equality 和 package hashes 全部通过。失败使用新 audit revision，不修补 sealed package。

### Task 14：Execution authorization receipt

该 Task 需要已批准 input-audit 三个外部 SHA 和独立 `EXECUTION_AUTHORIZATION_RECEIPT_ISSUANCE_AUTHORIZED`。

- [ ] 按 exact schema 签发 production-only receipt package。
- [ ] validator 重新校验 approved design/plan、source manifests、input audit、test identity、sealed tree 与 grid。
- [ ] 外部报告 receipt、manifest、checksums SHA。
- [ ] 不运行 generation，不写 run directory。

### Task 15：Production generation

该 Task 需要 execution authorization 三个外部 SHA 获批准及独立 `PRODUCTION_GENERATION_AUTHORIZED`。

- [ ] 在 `mkdir` 前完成全 preflight 与 pre-generation continuity。
- [ ] 由 production generation supervisor 本地启动唯一 run ID `stage11-standard-cost-profiles-v2-r1` 的单个 worker；每 5 秒采样 process-alive，hard timeout 为 1800 秒，termination grace 为 10 秒。
- [ ] `attempt_count=1`、`automatic_retry_performed=false`；timeout、crash、monitor failure 或 grace 后仍存活均 fail closed，不自动重试、不 seal、不复用 run ID。
- [ ] 生成并 seal 精确 192-row package，完成 post-generation continuity。
- [ ] wall-clock/PID/alive samples 只作为 run-state diagnostics；deterministic result equality 忽略这些诊断字段。
- [ ] 外部报告 generation result、run identity/state、manifest、checksums SHA。
- [ ] 停在 pending independent verification，不签发 verification receipt。

### Task 16：Independent verification

该 Task 需要 generation 外部 SHA 获批准及独立 `INDEPENDENT_VERIFICATION_AUTHORIZED`。

- [ ] verification `mkdir` 前完成 pre-verification continuity。
- [ ] 由 production verifier supervisor 启动单个 worker，固定每 5 秒 process-alive、1800 秒 hard timeout、10 秒 termination grace、单次执行且禁止自动重试。
- [ ] 独立重算、逐行比较并生成 exact verification package；timeout、crash 或 monitor failure 时 package 不发布。
- [ ] 完成 post-verification continuity。
- [ ] wall-clock/PID/alive samples 只作为 verification receipt diagnostics，不参与 192-row 或 deterministic artifact semantic equality。
- [ ] 外部报告 verification receipt、manifest、checksums SHA。
- [ ] 停在 pending final approval。

### Task 17：Final approval

该 Task 需要 verification 外部 SHA 获批准及独立 `FINAL_APPROVAL_RECEIPT_ISSUANCE_AUTHORIZED`。审批者签发 final approval package；runner/verifier 不得代签。完成后仍不得产生 `stage11_formally_verified=true`。

### Task 18：Final-status seal

该 Task 需要 final approval 外部 SHA 获批准及独立 `FINAL_STATUS_AUTHORIZED`。consumer 校验全链后才可生成 final-status evidence package；只有该 package 通过并获得外部 SHA，才允许报告 `stage11_formally_verified=true`。

## 6. 精确 Fixture Test Allowlists

### 6.1 历史 15-class / 41-test baseline

```text
tests.test_capd_proactive_stage11_v2.Stage11V2NoRealUpstreamAccessTest
tests.test_capd_proactive_stage11_v2.Stage11V2ApprovalChainTest
tests.test_capd_proactive_stage11_v2.Stage11V2ConfigTest
tests.test_capd_proactive_stage11_v2.Stage11V2SourceClosureTest
tests.test_capd_proactive_stage11_v2.Stage11V2PrimitiveTest
tests.test_capd_proactive_stage11_v2.Stage11V2StandardInputTest
tests.test_capd_proactive_stage11_v2.Stage11V2Stage9GateTest
tests.test_capd_proactive_stage11_v2.Stage11V2Stage10GateTest
tests.test_capd_proactive_stage11_v2.Stage11V2AuthorizationTest
tests.test_capd_proactive_stage11_v2.Stage11V2PathGuardTest
tests.test_capd_proactive_stage11_v2.Stage11V2RunnerTest
tests.test_capd_proactive_stage11_v2.Stage11V2VerificationTest
tests.test_capd_proactive_stage11_v2.Stage11V2ReleaseTest
tests.test_capd_proactive_stage11_v2.Stage11V2DocumentationTest
tests.test_capd_proactive_stage11_v2.Stage11V2CompatibilityTest
```

禁止新增、删除、重命名 class 或把 production tests 混入该模块来改变 41-test 基线。

### 6.2 Production fixture 56-test allowlist

```text
tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest.test_exact_schema_family_exists
tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest.test_config_binds_fixed_identity_grid_and_192_rows
tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest.test_receipt_schemas_reject_non_exact_fields
tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest.test_package_manifest_breaks_recursive_hash_cycle
tests.test_capd_proactive_stage11_v2_production.ProductionSchemaContractTest.test_missing_numeric_semantics_are_null_and_na
tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest.test_capture_emits_four_canonical_objects
tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest.test_independent_rebuild_matches_exact_bytes
tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest.test_missing_canonical_object_is_rejected
tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest.test_rehashed_tampered_object_is_rejected
tests.test_capd_proactive_stage11_v2_production.CanonicalUpstreamObjectTest.test_semantically_equal_noncanonical_json_is_rejected
tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest.test_exact_input_audit_member_set
tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest.test_external_receipt_manifest_checksums_sha_are_required
tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest.test_capture_does_not_create_production_run
tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest.test_wrong_log_ids_or_counts_are_rejected
tests.test_capd_proactive_stage11_v2_production.InputAuditPackageTest.test_failed_upstream_gate_fails_closed
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_exact_29_member_whitelist
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_pre_post_test_source_snapshots_match
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_missing_transitive_helper_is_rejected
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_weakened_test_rehashed_package_is_rejected
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_same_count_replaced_member_is_rejected
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_historical_five_sources_and_manifests_are_byte_unchanged
tests.test_capd_proactive_stage11_v2_production.TestSourceIdentityTest.test_production_modules_do_not_import_historical_contracts
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_snapshot_has_exact_five_roots
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_pre_generation_check_precedes_mkdir
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_pre_generation_drift_is_rejected
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_post_generation_drift_prevents_seal
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_pre_verification_drift_prevents_package
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_post_verification_drift_prevents_publish
tests.test_capd_proactive_stage11_v2_production.FrozenTreeContinuityTest.test_repository_revision_boolean_is_diagnostic_only
tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest.test_approved_plan_external_sha_is_required
tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest.test_input_audit_three_external_hashes_are_bound
tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest.test_test_identity_and_sealed_tree_are_bound
tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest.test_synthetic_authorization_is_rejected
tests.test_capd_proactive_stage11_v2_production.ProductionAuthorizationTest.test_future_output_hashes_are_rejected
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_exact_192_row_cartesian_product
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_duplicate_and_missing_pair_is_rejected
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_pressure_job_and_fifth_profile_are_rejected
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_blocked_lanes_emit_no_numeric_rows
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_zero_access_uses_null_not_zero
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_main_b_max_two_is_immutable
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_generation_monitor_enforces_single_attempt_and_timeout
tests.test_capd_proactive_stage11_v2_production.ProductionGenerationTest.test_generation_timeout_uses_fixed_termination_grace
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_verifier_has_no_generation_import
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_verifier_independently_recomputes_192_rows
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_generation_continuity_bindings_are_exact
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_verification_continuity_bindings_are_exact
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_exact_seven_member_verification_package
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_verification_monitor_enforces_single_attempt_and_timeout
tests.test_capd_proactive_stage11_v2_production.ProductionIndependentVerificationTest.test_wall_clock_diagnostics_are_excluded_from_result_equality
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_verification_stops_pending_final_approval
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_final_approval_requires_exact_external_binding
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_final_status_requires_complete_exact_chain
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_rehashed_release_tamper_is_rejected
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_no_gate_auto_issues_next_receipt
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_verification_capability_cannot_write_final_packages
tests.test_capd_proactive_stage11_v2_production.ProductionReleaseGateTest.test_final_approval_capability_cannot_write_final_status
```

精确 class 数为 `9`，test 数为 `56`。测试收集结果不等于这些固定值时 fail closed，不允许 parser 自动更新 expected count。

### 6.3 后续真实语义测试

只有 Task 13 获独立批准后才运行：

```text
tests.test_capd_proactive_stage10.Stage10FormalGateTest.test_historical_r1_run_directory_is_rejected
tests.test_capd_proactive_stage10_v2.Stage10V2Stage9GateTest.test_real_stage9_r3_passes_complete_read_only_gate
tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_dispatch_still_verifies_historical_fixture
tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_and_v2_verifiers_are_bidirectionally_incompatible
tests.test_capd_proactive_stage11.Stage11GateTest.test_complete_stage10a_fixture_is_blocked
tests.test_capd_proactive_stage11.Stage11GateTest.test_historical_stage9_run_is_not_verifiable
```

必须精确 `6/6 OK`，不得运行同模块其他测试。Task 1-12 的 fixture-only 验证必须机械证明这六项未启动且真实上游 successful-open count 为 0。

## 7. 任务依赖与审批门

```text
approved design
  -> approved production plan + external plan SHA
  -> Gate A: Tasks 1-11 implementation and fixture-only validation
  -> Gate B: Task 12 source-manifest freeze
  -> Gate C: Task 13 input-audit recapture/seal/independent verification
  -> Gate D: approve input-audit external SHA
  -> Gate E: Task 14 execution authorization issuance
  -> Gate F: approve execution authorization external SHA
  -> Gate G: Task 15 production generation
  -> Gate H: Task 16 independent verification
  -> Gate I: Task 17 final approval receipt
  -> Gate J: Task 18 final-status seal
```

每个 Gate 都需要新的明确批准。前一 Gate 通过不自动授权后一 Gate；失败不得修补 sealed package，必须使用新的 audit/revision/run identity 重新开始。

Gate A 也不自动包含 Task 12。若计划审批只批准 Tasks 1-11，则 source manifests、真实上游、production root 和所有 receipt 必须继续保持未创建。

## 8. 计划自审

- approved design 状态与外部 SHA 已明确绑定。
- approved-plan SHA 不在本文中自引用；计划批准后从外部提供。
- production 使用五个新模块；历史五个模块与两份 source manifests 逐字节只读，不需要 synthetic source-identity 迁移。
- 三份精确 source whitelist 已冻结为 generation `30`、verifier `32`、test-source `29` 个排序唯一成员。
- historical synthetic 15-class/41-test 与 production 9-class/56-test 分开冻结。
- 六种 writer capability 按 phase、output root、identity、plan SHA 和 nonce 隔离，并覆盖跨 phase 拒绝测试。
- generation/verification 均固定 5 秒 process-alive、1800 秒 hard timeout、10 秒 termination grace、单次执行和禁止自动重试；wall-clock 仅为诊断。
- 四个 canonical 上游对象进入 audit package，并要求独立逐字节重建。
- test-source identity 覆盖五个入口、helper 和完整本地传递闭包。
- 五棵冻结树在 audit、generation、verification 四个时点持续校验。
- `repository_revision_match` 是实测诊断，不是 authorization predicate。
- production preflight 失败发生在 `mkdir` 前。
- 结果合同固定为 Standard 48-job x 4 profile = 192 candidate-ready rows。
- Stage9/10 不产生新测量，blocked lanes 不生成占位数字。
- generation、verification、final approval、final-status 维持独立 gate。
- 未包含 commit、push、server execution、训练或 checkpoint selection。

## 9. 当前审批请求

当前只请求本 production implementation plan 的评审。若计划获批，评审必须明确批准哪些 Gate；不得从 `PLAN_APPROVED` 自动推断 Tasks 1-11、source freeze、input audit 或 production 已授权。

在获得下一条明确授权前，不修改 Stage11 实现/config/schema/tests/status/source manifests，不运行 fixture tests 或真实审计，不创建 production output，不签发 receipt，不 commit，不 push。
