# CAPD Stage11 v2 正向证据迁移实施计划

## Material Passport

- Artifact Type: Implementation plan
- Artifact ID: `capd-stage11-v2-positive-evidence-migration-plan-20260807`
- Version Label: `plan-v1-approved`
- Origin Skill: `experiment-agent`
- Origin Mode: `plan`
- Verification Status: `PLAN_REVIEW_APPROVED`
- Plan Status: `PLAN_APPROVED`
- Approved Design: `docs/superpowers/specs/2026-08-07-stage11-positive-evidence-migration-design.md`
- Approved Design SHA256: `0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160`
- Repository HEAD Audited: `f8aad2c3f166ce900353c0b6061c7dc207d1200e`
- Implementation Authorization: `GRANTED_TASKS_1_12_SYNTHETIC_ONLY_EXCLUDING_STEP_3`
- Formal Experiment Authorization: `NOT_GRANTED`

`PLAN_REVIEW_APPROVED` 只表示本计划获准执行 Tasks 1-12 的代码实现、synthetic fixture 测试和非语义完整性检查，不是 execution authorization receipt、实验结果或正式验证回执。Task 12 Step 3、production generation、execution/final approval/final-status receipt 签发、正式 Stage11 状态、commit 和 push 均未授权。

## 1. 目标

实现独立的 `CAPD-PROACTIVE-STAGE11-2.0` 合同及其本地可测试基础设施，完成：

- 精确 Standard-only Stage8 job-level 输入校验；
- Stage9 v2-r3 自有合同 gate；
- Stage10 v2-r2 sealed-attestation-only positive gate；
- execution authorization 的 schema、读取器和 fail-closed preflight；
- generation、independent verification、final approval、final-status 的无环 artifact contract；
- 只读 `--audit-inputs` 和受 authorization 约束的 generation runner；
- synthetic fixture、负向测试和 v1.0 兼容测试。

实施阶段不签发真实 execution authorization receipt，不运行正式 Stage11，不创建生产 run，不签发 final approval/final-status，不训练模型，不选择 checkpoint，不修改上游证据，不 commit，不 push。

## 2. 架构

新增一个 generation 合同模块 `qmap/proactive_stage11_v2.py`，负责严格 JSON、canonical hashing、Standard source set、Stage9/10 gate、authorization、输出路径 guard 和 generation release envelope。新增 generation runner `scripts/run_capd_proactive_stage11_v2.py`，显式提供两类操作：

```text
--audit-inputs   只读，输出 stdout，不创建 run 目录
--execute        必须提供精确 execution authorization receipt 和外部预期 SHA
```

独立 verification 使用不导入 generation 模块的 `qmap/proactive_stage11_v2_verifier.py` 和 `scripts/verify_capd_proactive_stage11_v2.py`。generation 与 verifier 分别绑定静态 source manifest；两个 manifest 都由本地 import 闭包检查和执行前后源码快照约束。final approval receipt 由外部独立审批动作提供，runner 不自动签发。final-status 接口只消费已经存在且具有外部预期 SHA 的 final approval receipt；实现阶段只用 synthetic temporary fixtures 测试，不对真实证据执行。

## 3. 技术栈

- Python 3 标准库；
- generation 侧现有 `qmap.proactive_cost`；
- Stage11 v2 自有的只读 Stage8 persisted-evidence validator，不导入现有 Stage8 contract helper；
- 现有 Stage9 result schema；
- Stage10 v2-r2 sealed artifacts、release manifests 和 receipts；
- `unittest`；
- UTF-8 strict JSON、CSV、SHA256；
- PowerShell 本地验证命令。

不新增第三方依赖，不调用网络，不执行 Linux/server 命令。

## 4. 审批与只读边界

以下目录在实现和测试中始终只读：

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`；
- `outputs/capd_proactive_stage9/`，尤其 `stage9-overhead-v2-r3/`；
- `outputs/capd_proactive_stage10/`，尤其 v2-r2 generation/readiness/final-status；
- `outputs/capd_proactive_stage11/` 及所有 v1.0 历史 artifact；
- Stage4/7 冻结 checkpoint；
- 设计文档及其 approved-design SHA。

计划获批后允许新增或修改的范围仅为 Stage11 v2 自有代码、config、schema、tests、fixture 文档和协议文档。生产 output root `outputs/capd_proactive_stage11_v2/` 在本实施阶段必须保持不存在；测试 run 只能位于系统临时目录。

计划批准本身不授权语义解析真实上游。Tasks 1-12 在另行获得 real-upstream audit 明确批准前，对 Stage8 r5、Stage9、Stage10、Stage11 v1 output 和冻结 checkpoint 只允许：枚举文件、读取长度、按原始字节计算 SHA256，并生成 `{path,length,sha256}` 完整性快照；不得加载其 JSON/CSV/JSONL/Markdown 内容，不得调用会解释这些内容的 gate/verifier，也不得执行任何旧 Stage8/9/10/11 测试模块。哈希扫描不是语义验证，报告中只能写 `integrity_snapshot_match`。

所有 v2 synthetic tests 在进程启动时安装 Python audit hook，拦截 `open`/`os.open` 等文件打开事件，并对解析后的真实 `outputs/capd_proactive_stage8/9/10/11` 与冻结 checkpoint 路径 fail closed；fixture 必须位于当前测试独占的系统临时根。测试还要拒绝通过 subprocess 启动旧测试模块或 legacy runner 来绕过 hook。该限制独立于 v2 writer capability guard，因为旧测试不受 writer guard 控制。

## 5. 文件图

计划获批后建议新增：

- `qmap/proactive_stage11_v2.py`
- `qmap/proactive_stage11_v2_guard.py`
- `qmap/proactive_stage11_v2_verifier.py`
- `scripts/run_capd_proactive_stage11_v2.py`
- `scripts/verify_capd_proactive_stage11_v2.py`
- `configs/finals/capd_proactive_stage11_v2.json`
- `configs/finals/capd_proactive_stage11_v2_config_schema.json`
- `configs/finals/capd_proactive_stage11_v2_result_schema.json`
- `configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json`
- `configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json`
- `configs/finals/capd_proactive_stage11_v2_generation_source_manifest_schema.json`
- `configs/finals/capd_proactive_stage11_v2_verifier_source_manifest.json`
- `configs/finals/capd_proactive_stage11_v2_verifier_source_manifest_schema.json`
- `configs/finals/capd_proactive_stage11_v2_verification_receipt_schema.json`
- `configs/finals/capd_proactive_stage11_v2_final_approval_receipt_schema.json`
- `configs/finals/capd_proactive_stage11_v2_final_status_evidence_receipt_schema.json`
- `configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json`
- `tests/test_capd_proactive_stage11_v2.py`
- `tests/fixtures/stage11_v2/README.md`
- `docs/CAPD_PROACTIVE_STAGE11_V2_PROTOCOL_CN.md`
- `docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md`

除兼容测试读取外，不修改 v1 文件：

- `qmap/proactive_stage11.py`
- `scripts/run_capd_proactive_stage11.py`
- `configs/finals/capd_proactive_stage11a.json`
- `configs/finals/capd_proactive_stage11a_result_schema.json`
- `tests/test_capd_proactive_stage11.py`

## Task 1：冻结基线并建立失败测试骨架

**文件：**

- Create: `tests/test_capd_proactive_stage11_v2.py`
- Create: `tests/fixtures/stage11_v2/README.md`
- Temporary only: `$env:TEMP/capd-stage11-v2-<id>/frozen-before.json`

- [ ] **Step 1：验证 approved design 与 approved plan**

测试启动前必须计算设计 SHA，并要求：

```text
0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160
```

同时解析 Material Passport，要求 `Design Status=DESIGN_APPROVED` 和 `Approved Scope=IMPLEMENTATION_PLAN_ONLY`。SHA 或状态不一致则所有 v2 测试/命令 fail closed。

本计划本轮保持 `Plan Status=READY_FOR_PLAN_REVIEW`，不得在本文中写入自身 SHA。用户未来明确批准后，先把 Material Passport 的状态改为 `PLAN_APPROVED`，再由文档外部计算并提供最终 `approved_plan_sha256`；该 SHA 不回写本文。实施入口必须同时接收 approved-plan path 和这个外部 SHA，重新计算文件 SHA，并解析 `Plan Status=PLAN_APPROVED`。缺失 SHA、SHA 错误、仍为 `READY_FOR_PLAN_REVIEW` 或任何其他状态时，所有 v2 实现命令均在读取真实上游和创建目录之前 fail closed。

- [ ] **Step 2：记录冻结树快照**

对 Stage8 r5、Stage9 root、Stage10 root、Stage11 v1 output、冻结 checkpoint 生成按相对路径排序的 `{path,length,sha256}` 快照，只写系统临时目录。不得在任何 output tree 写 snapshot。

- [ ] **Step 3：冻结 v1.0 非语义基线**

只记录 `qmap/proactive_stage11.py`、`scripts/run_capd_proactive_stage11.py`、v1 config/schema/test 文件和 Stage11 v1 output 的 `{path,length,sha256}`。此前评审记录中的 Stage11A `22/22 OK` 仅作为计划审查背景，不在实施阶段独立授权前复跑，也不作为本次实现验收结果。

- [ ] **Step 4：写 v2 公共接口的失败测试**

测试先导入：

```python
from qmap import proactive_stage11_v2 as stage11_v2
```

建立 `Stage11V2NoRealUpstreamAccessTest`、`Stage11V2ApprovalChainTest`、`Stage11V2ConfigTest`、`Stage11V2SourceClosureTest`、`Stage11V2PrimitiveTest`、`Stage11V2StandardInputTest`、`Stage11V2Stage9GateTest`、`Stage11V2Stage10GateTest`、`Stage11V2AuthorizationTest`、`Stage11V2PathGuardTest`、`Stage11V2RunnerTest`、`Stage11V2VerificationTest`、`Stage11V2ReleaseTest`、`Stage11V2DocumentationTest` 和 `Stage11V2CompatibilityTest`。除 `NoRealUpstreamAccessTest` 验证拒绝行为外，所有输入均由测试在系统临时目录中构造，不得复制、读取或派生自真实 Stage8/9/10 output。

- [ ] **Step 5：确认 RED 状态**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2 -v
```

Expected: 因 v2 module/config/schema 尚不存在而失败；无 output 目录被创建。

fixture README 必须声明：所有 fixture 均为 synthetic、只能测试 parser/gate、不得作为 external input、execution authorization、final approval、formal status 或论文证据。

## Task 2：定义 config、source manifest 与 schema family

**文件：**

- Create: `configs/finals/capd_proactive_stage11_v2.json`
- Create: 九个 v2 schema 文件；定义两个静态 source manifest 的精确成员合同，实体文件延后到 Task 11 冻结
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：先写 config/schema 负向测试**

覆盖：错误 contract、错误 approved-design SHA、缺失/错误 approved-plan SHA、plan 状态不是 `PLAN_APPROVED`、未知字段、重复 JSON key、非有限数、主 `b_max != 2`、Cost profile 不精确、未批准 watermark/label-weight、Test selection、配置自行声明 execution authorized、缺失 external anchor。

- [ ] **Step 2：写 repository config template**

config 固定：

- `contract_id=CAPD-PROACTIVE-STAGE11-2.0`；
- approved-design path/SHA；
- approved-plan path 与外部提供的 `approved_plan_sha256`；
- Stage8 r5、Stage9 v2-r3、Stage10 v2-r2 路径；
- Stage10 freeze/readiness/final-status 三个精确 SHA；
- 四个 Cost profile；
- 主 `b_max=2`，`1/4` analysis-only；
- Standard-only workload allowlist；
- watermark/label-weight 为空且未授权；
- model component ablation 为 `BLOCKED`；
- output root 为 `outputs/capd_proactive_stage11_v2`；
- execution authorization receipt path 和 expected SHA 均为 `null`；
- `test_used_for_parameter_selection=false`。

repository config 不能单独授权执行。运行时 authorization 只能来自外部 receipt 与外部预期 SHA。approved-plan SHA 必须来自计划批准后的外部计算值；config 不得从计划正文、Git commit message 或文件名推断它。

- [ ] **Step 3：写 source manifest schema、精确成员合同与 synthetic tests**

两个静态 source manifest 均要求 `contract_id`、`role`、approved-design SHA、approved-plan SHA、按 POSIX 相对路径排序且唯一的 `{path,sha256}`、`member_count`、`members_sha256`、`local_import_closure_complete=true` 和明确 exclusions。Task 2 先以 synthetic member files 测试 schema/closure builder；仓库静态 manifest 要等 Task 10 的代码闭合后由 Task 11 一次生成。manifest 文件不保存自身 SHA，也不把自身列入 members；外部消费者计算 manifest 文件 SHA，execution authorization 和 run identity 将该文件 SHA 与 `members_sha256` 分别绑定。repository config 只记录两个 manifest 的路径，不反向记录其 SHA，避免 config/manifest 循环哈希。精确成员白名单为：

```text
generation:
  scripts/run_capd_proactive_stage11_v2.py
  qmap/proactive_stage11_v2.py
  qmap/proactive_stage11_v2_guard.py
  qmap/proactive_cost.py
  configs/finals/capd_proactive_stage11_v2.json
  configs/finals/capd_proactive_stage11_v2_config_schema.json
  configs/finals/capd_proactive_stage11_v2_result_schema.json
  configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json
  configs/finals/capd_proactive_stage11_v2_generation_source_manifest_schema.json
  configs/finals/capd_proactive_stage11_v2_verifier_source_manifest_schema.json
  configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json
  configs/finals/capd_proactive_stage9_result_schema.json
  configs/finals/capd_proactive_stage10_result_schema_v2.json
  configs/finals/capd_proactive_stage10_v2_r2_config_schema.json
  configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json
  configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json
  configs/finals/capd_proactive_stage10_verification_schema_v2_1.json
  configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json
  configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json
  configs/finals/capd_proactive_stage10_release_manifest_schema.json
  configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json
  configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json

verifier:
  scripts/verify_capd_proactive_stage11_v2.py
  qmap/proactive_stage11_v2_verifier.py
  qmap/proactive_stage11_v2_guard.py
  configs/finals/capd_proactive_stage11_v2.json
  configs/finals/capd_proactive_stage11_v2_config_schema.json
  configs/finals/capd_proactive_stage11_v2_result_schema.json
  configs/finals/capd_proactive_stage11_v2_execution_authorization_schema.json
  configs/finals/capd_proactive_stage11_v2_generation_source_manifest_schema.json
  configs/finals/capd_proactive_stage11_v2_verifier_source_manifest_schema.json
  configs/finals/capd_proactive_stage11_v2_verification_receipt_schema.json
  configs/finals/capd_proactive_stage11_v2_final_approval_receipt_schema.json
  configs/finals/capd_proactive_stage11_v2_final_status_evidence_receipt_schema.json
  configs/finals/capd_proactive_stage11_v2_release_manifest_schema.json
  configs/finals/capd_proactive_stage9_result_schema.json
  configs/finals/capd_proactive_stage10_result_schema_v2.json
  configs/finals/capd_proactive_stage10_v2_r2_config_schema.json
  configs/finals/capd_proactive_stage10_run_identity_schema_v2_1.json
  configs/finals/capd_proactive_stage10_run_state_schema_v2_1.json
  configs/finals/capd_proactive_stage10_verification_schema_v2_1.json
  configs/finals/capd_proactive_stage10_generation_freeze_receipt_schema.json
  configs/finals/capd_proactive_stage10_generation_source_manifest_schema.json
  configs/finals/capd_proactive_stage10_release_manifest_schema.json
  configs/finals/capd_proactive_stage10_release_readiness_receipt_schema.json
  configs/finals/capd_proactive_stage10_final_status_evidence_receipt_schema.json
```

generation 模块仅允许导入标准库、`qmap.proactive_cost` 与共享的纯路径 guard `qmap.proactive_stage11_v2_guard`；不得导入 `qmap.proactive_stage8_contract`，从而避免其 `proactive_stage7_workloads -> proactive_stage4 -> finals_config/proactive_replay/proactive_stage3/qmap_generator` 传递闭包。verifier 模块仅允许导入标准库与这个共享路径 guard，不得导入 generation 模块或 `proactive_cost`，其 Cost 重算独立使用 schema 固定的四个整数 counter 和 profile 系数。guard 只能处理路径/capability，不得含 evidence parsing、Cost 或结果逻辑。AST import closure 检查必须证明所有本地 import 都在对应 manifest，manifest 中也不得有未使用的 Python dependency。

仓库当前 `qmap` 是 namespace package，不存在 `qmap/__init__.py`，因此两个 manifest 均不得虚构该成员。两个 CLI 的 project-root bootstrap 必须写在各自脚本内，不得依赖未列出的本地启动 helper。

以下内容明确排除 source identity：`docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md`、协议/发布说明、设计/计划正文、`tests/`、`tests/fixtures/`、任何 output/release receipt、缓存和临时文件。approved design/plan 通过独立 SHA 字段绑定；排除的文档或测试不得被运行时代码 import。新增“遗漏一个传递依赖”“manifest 混入 `qmap/proactive_stage11.py` 或其他 Stage11 v1 路径”“Stage11 v2 源码 import v1”“多列/少列成员”的负向测试。

- [ ] **Step 4：写 result 与 receipt schemas**

`result_schema` 定义 generation row、run identity、run state、Standard source manifest、input receipts、JSON `null` 和 CSV/Markdown `N/A`。其余 schema 分别定义 execution authorization、verification receipt、final approval receipt、final-status receipt 和 phase-aware release manifest。

所有 receipt schema 要求精确 `run_id`、contract、approved-design SHA、approved-plan SHA、上游 SHA、`synthetic_test_only`、Test isolation 和能力边界。execution authorization 还必须绑定 generation/verifier source manifest 文件 SHA 与各自 `members_sha256`；final approval/final-status receipt 不含自身 SHA或未来阶段 SHA。

- [ ] **Step 5：运行 schema/source-closure tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2ConfigTest -v
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2SourceClosureTest -v
```

Expected: config/schema tests 通过；execution 仍未授权。

## Task 3：实现严格 JSON、canonical hash 与 release envelope primitives

**文件：**

- Create: `qmap/proactive_stage11_v2.py`
- Create: `qmap/proactive_stage11_v2_guard.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写 hashing/envelope 失败测试**

覆盖 duplicate key、NaN/Infinity、路径逃逸、重复 checksum、额外文件、缺失文件、manifest 自引用、checksum 自引用、大小写/路径分隔符歧义和篡改字节。

- [ ] **Step 2：实现公共 primitives**

实现：

```python
load_json_strict(path)
canonical_json_bytes(value)
sha256_file(path)
sha256_value(value)
validate_external_anchor(path, expected_sha256)
authorize_write_context(mode, requested_root, run_id, test_temp_root, authorization)
build_manifest(write_context, phase, excluded)
write_checksums(write_context, members)
verify_release_envelope(root, phase, expected_receipt_sha256)
```

canonical JSON 固定 UTF-8、sorted keys、紧凑 separators、拒绝 non-finite number。manifest 排除自身和 `SHA256SUMS`；checksums 包含 manifest、排除自身；目录成员集合必须精确。Task 3 先实现 capability guard 的 fail-closed 核心和 synthetic temporary-root 分支，所有会写文件的 primitive 从首次出现起就拒绝裸路径；Task 8 再覆盖完整 CLI/library lifecycle 和禁用的 production 分支。

- [ ] **Step 3：验证重哈希攻击失败**

修改 receipt 后同时重算内部 self-hash、manifest 和 checksums，仍必须因外部 expected receipt SHA 不匹配而失败。

- [ ] **Step 4：运行 primitive tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2PrimitiveTest -v
```

## Task 4：实现 Stage8 Standard-only 精确输入合同

**文件：**

- Modify: `qmap/proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写精确成员负向测试**

覆盖：

- Pressure row；
- workload 不等于六项 allowlist；
- job ID 重复；
- 数量不是 48；
- 仍为 48 行但复制一个 job、遗漏另一个 job；
- 每 workload 仍为 8 行但 policy/seed multiset 错误；
- baseline seed 非 null；
- CAPD seed 不等于 `42/2026/3136859`；
- result SHA、semantic SHA、job identity SHA、raw counter 缺失或篡改；
- 通过浮点 cost 反推访问数。

- [ ] **Step 2：实现 authority subset derivation**

从 Stage8 r5 root `job_manifest.json` 过滤 `track == "standard"` 得到 expected job ID set。实际 CSV/job join 的集合必须与其逐项相等且唯一。

每 workload 的 multiset 必须精确为：

```text
reactive_lru:null
proactive_lru:null
proactive_clock:null
tpp_inspired:null
oracle:null
capd:42
capd:2026
capd:3136859
```

- [ ] **Step 3：实现 job-level SHA join**

在 `qmap/proactive_stage11_v2.py` 内实现最小只读 persisted-evidence validator，直接校验 Stage8 r5 的 root plan、per-job manifest、result bytes、semantic payload、trace/checkpoint binding 和权威 SHA，不 import 或调用 Stage8 runner/helper。semantic payload 规则在 v2 内按 Stage8 r5 已封存合同独立实现并由 fixture parity test 锁定。raw counters 只从 `result.json.metrics` 读取，CSV 仅作为索引。

这样 generation 的本地 import 闭包保持为 `runner -> proactive_stage11_v2 -> {proactive_cost, proactive_stage11_v2_guard}`；Stage8 helper 的深层训练/replay 依赖不会进入 Stage11 v2 source identity。若实现为了便利新增任何本地 import，source-closure test 必须先更新精确白名单并重新审批，不能在运行时自动扩张 manifest。

- [ ] **Step 4：生成 canonical Standard source identity**

按 `job_id` 排序生成 immutable records，计算：

- `standard_source_manifest_sha256`；
- `sorted_job_ids_sha256`；
- 48-job count；
- 六 workload identity；
- policy/seed multiset identity。

- [ ] **Step 5：运行 Standard input tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2StandardInputTest -v
```

## Task 5：实现 Stage9-native gate

**文件：**

- Modify: `qmap/proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写 Stage9 schema-specific tests**

测试 v2-r3 正向 fixture 和以下负向项：required artifact 缺失、`artifact_sha256` key set 错误、Linux CPU/perf/RSS 字段错误、Stage8 compatibility receipt 错误、`formal_b_max != 2`、Test selection、错误 run ID/version。

- [ ] **Step 2：实现 gate**

加载 `capd_proactive_stage9_result_schema.json`，按其 `required_run_artifacts`、`verification_required` 和 `verification.json.artifact_sha256` 校验。不得要求 Stage10 式根 `manifest.json + SHA256SUMS`。

返回独立 receipt：

```text
stage9_input_authorized
run_state_sha256
verification_sha256
stage8_compatibility_receipt_sha256
artifact_verified_count
population_scope
```

Stage9 gate 通过只表示 external input authorized，不表示 Stage11 execution 或 formal status。

- [ ] **Step 3：运行 Stage9 tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2Stage9GateTest -v
```

## Task 6：实现 Stage10 v2-r2 sealed positive gate

**文件：**

- Modify: `qmap/proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：把设计 T01-T14、T31-T33 写成失败测试**

必须覆盖 Stage10A、v2-r1、缺 release phase、freeze/run/result/scenario/receipt/manifest/checksum 篡改、重哈希攻击、仅一个 sealed verifier 通过、real-system flag 被改为 true。

- [ ] **Step 2：实现 sealed-attestation-only decision**

positive decision 只读取：

- 精确 freeze/readiness/final-status 外部 SHA；
- sealed generation/readiness/final-status payload；
- 三个 phase 的 manifest/checksum；
- sealed readiness 中 native 与 dispatcher 两个 verifier 状态；
- 60 条完整 scenario identity；
- Stage9 input receipt；
- 五个 false 的 real-system capability flags。

不得调用当前 HEAD 的 Stage10 verifier，不得用当前 revision 重构历史 run identity。

- [ ] **Step 3：实现 current-tree compatibility diagnostic**

单独计算：

```text
generation_source_set_match
repository_revision_match
current_live_replay_compatibility
```

当前预期为 `true/false/NOT_VERIFIABLE`。这些字段不参与 sealed positive decision，不得合并为 source identity。

- [ ] **Step 4：校验 60 个 scenario**

要求 matrix、verification 和 JSONL count、顺序/集合、唯一性、scenario identity、arrival/timing binding 与确定性结果均满足 Stage10 r2 原合同。只比较 `result_count=60` 不足以通过。

- [ ] **Step 5：运行 Stage10 tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2Stage10GateTest -v
```

## Task 7：实现 execution authorization validator 与 global preflight

**文件：**

- Modify: `qmap/proactive_stage11_v2.py`
- Modify: `scripts/run_capd_proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写 authorization fail-closed tests**

覆盖 receipt 缺失、expected SHA 缺失、wrong SHA、wrong run ID、wrong config/schema/source-set/design SHA、缺失/错误 approved-plan SHA、plan 未处于 `PLAN_APPROVED`、generation/verifier source manifest SHA 错误、错误 upstream anchor、未来 output SHA、Test selection、非 `b_max=2`、未批准 grid 和重复 run ID。

- [ ] **Step 2：实现纯 validator**

`validate_execution_authorization()` 只读取外部 receipt 和显式 expected SHA。receipt 必须绑定设计 SHA、外部 approved-plan SHA、run ID、config/schema SHA、generation/verifier source manifest 文件 SHA 与 `members_sha256`、Standard input identity、Stage9/10 anchors、frozen-grid identity 和审批范围；禁止绑定未来 result/manifest/verification/final-status SHA。validator 必须现场重算 design、plan、config、schema 和两个 source manifest，且要求 plan Material Passport 为 `PLAN_APPROVED`；任一值不一致均 fail closed。

- [ ] **Step 3：实现 global preflight 顺序**

顺序固定：

1. approved design 与外部 approved-plan SHA/status；
2. config/schema；
3. generation/verifier source manifest、精确 import closure 与 source snapshot-before；
4. output containment、synthetic/production mode 和 run ID absence；
5. Stage8 Standard source set；
6. Stage9 gate；
7. Stage10 sealed gate；
8. execution authorization。

任一失败均发生在 `mkdir` 前。外部 gate 通过但 authorization 缺失时返回 `BLOCKED`，不得创建 production 或 temporary generation run。

- [ ] **Step 4：实现 `--audit-inputs`**

该模式执行步骤 1-3 后，只有获得单独 real-upstream audit 批准才执行步骤 5-7；否则不打开真实 Stage8/9/10，输出 `real_upstream_audit=NOT_RUN`。它只向 stdout 输出 diagnostic JSON，固定：

```text
stage11_execution_authorized=false
stage11_formally_verified=false
```

它不得创建 input receipt、run directory、manifest 或 checksums。

- [ ] **Step 5：运行 authorization/preflight tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2AuthorizationTest -v
```

## Task 8：实现 generation runner 与 Standard-only candidate outputs

**文件：**

- Modify: `scripts/run_capd_proactive_stage11_v2.py`
- Modify: `qmap/proactive_stage11_v2.py`
- Modify: `qmap/proactive_stage11_v2_guard.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：先写 lifecycle 与路径隔离 tests**

测试无 authorization 不创建 run、已有 run ID 不覆盖、Pressure 不进入结果、row source identity 完整、异常时 atomic cleanup、generation 不写 formal status，并必须拒绝：

- synthetic API 或 CLI 将 output root 指向 `outputs/capd_proactive_stage11_v2/` 或其任一子目录；
- production config/CLI 接受 `synthetic_test_only=true` 的 authorization、input receipt、source manifest 或 release receipt；
- fixture output 使用 `..`、绝对路径、大小写/分隔符别名、symlink、junction 或 Windows reparse point 逃逸每个测试独占的系统临时根目录；
- 未获得 real-upstream audit 单独批准的 test config 打开真实 Stage8/9/10 路径；
- 绕过 CLI 直接调用任一 JSON/CSV/Markdown/manifest/checksum/receipt writer 写入 production root。

- [ ] **Step 2：实现所有 writer 共用的 capability guard**

实现单一 `authorize_write_context(mode, requested_root, run_id, test_temp_root, authorization)`。它先做 lexical normalization，再解析所有已存在父目录并拒绝 symlink/junction/reparse escape，最后按模式签发不可由外部直接构造的 write capability：

```text
synthetic:
  requested_root 必须严格位于 tempfile 创建且由当前 test 持有的独占根目录下
  requested_root 不得等于或位于 production root 下
  authorization 及所有 receipt 必须 synthetic_test_only=true

production:
  requested_root 必须精确为配置中的 outputs/capd_proactive_stage11_v2/<run_id>
  authorization 及所有上游/阶段 receipt 必须 synthetic_test_only=false
  本实施批准不允许进入该分支
```

所有 public/private writer 都必须接收并重新验证该 capability；不得暴露接受裸路径即可写入的后门函数。CLI、library API、atomic staging、manifest/checksum 和 release writer 走同一 guard。负向测试直接调用底层 writer，证明无 capability、伪造 capability、路径变更或 production target 均在第一次写入前失败。

- [ ] **Step 3：实现受控 `--execute`**

只有 preflight 全通过才创建 `<output-root>/<run_id>/`。实现阶段测试只允许 synthetic fixture authorization 和系统临时 output root；真实 execution authorization receipt 及其外部 SHA 不存在，因此本阶段不得调用 production output root。

- [ ] **Step 4：写 generation artifacts 并绑定 source snapshot**

在任何输入读取和写入前，从 generation source manifest 重算 `source_snapshot_before`。按设计写 config snapshot、run identity/state、三个 input receipts、authorization reference、Standard source manifest、frozen grid、JSON/CSV/report、manifest、checksums。run identity 必须绑定 approved-design SHA、approved-plan SHA、generation/verifier source manifest SHA 与 `members_sha256`、repository revision、input/authorization SHA 和 frozen-grid identity。JSON 缺失数值为 `null`；CSV/Markdown 为 `N/A`。

完成 staging 但在 publish/rename 前重新计算 `source_snapshot_after`，要求成员集合、每个文件 SHA 和 aggregate identity 与 before 完全相等。运行中任一源码/config/schema/helper 变化时，generation 失败且不得发布 run；测试还必须覆盖只修改一个源文件、替换相同长度字节和运行中新增本地 import。状态/发布文档或测试文件在运行后变化不影响 source identity，但运行时代码若 import 它们仍因 closure 违规失败。

run state 固定：

```text
stage11_generation_complete_pending_verification
stage11_formally_verified=false
```

- [ ] **Step 5：实现允许的离线结果**

四个 Cost profile 从 Standard job raw integer counters 重算。主 `b_max=2` 不被 analysis-only `1/4` 覆盖。watermark/label-weight 和 model component ablation 未批准时只记录 `BLOCKED`，不生成伪数值。

- [ ] **Step 6：运行 runner/path-guard tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2RunnerTest -v
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2PathGuardTest -v
```

Expected: 只在 temporary fixture root 产生 synthetic generation；没有生产 output。

## Task 9：实现 independent generation verification

**文件：**

- Create: `qmap/proactive_stage11_v2_verifier.py`
- Create: `scripts/verify_capd_proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写 independent verification tests**

覆盖 generation run identity/state/result/manifest/checksum、Standard source set、Cost 重算、input receipts、authorization SHA、approved design/plan SHA、generation/verifier source manifest、代码版本和 row count。修改任意 byte 必须失败；verifier import generation 模块、source manifest 遗漏本地依赖、混入 Stage11 v1、verification 运行中源码变化也必须失败。

- [ ] **Step 2：实现 `verify_generation()`**

verifier 必须从原始 Stage8 fixture 重新构造 Standard identity 和 Cost，不信任 generation summary，也不调用 generation 模块或 `qmap.proactive_cost`。它在读取 generation 前验证 approved design/plan、verifier source manifest 与完整本地 import closure，记录 `verifier_source_snapshot_before`；在 verification envelope publish 前重算 `verifier_source_snapshot_after`，两者必须逐文件相等。验证成功只得到 `stage11_generation_verified=true`，formal status 仍为 false。

- [ ] **Step 3：实现 verification release envelope**

只在显式 `--emit-verification-receipt` 且输出为系统临时 fixture root 时测试 writer。receipt 绑定 approved-plan SHA、generation、authorization、inputs、negative-test identity、generation source identity 和 verifier source identity；release manifest/checksum 精确闭合。verification writer 复用 Task 8 的 capability guard，直接调用 writer、路径逃逸、production target 或 synthetic/production receipt 混用都必须在写入前失败。

真实 verification receipt 的签发不属于本实施执行范围。

- [ ] **Step 4：运行 verification tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2VerificationTest -v
```

## Task 10：实现 final approval/final-status 消费合同

**文件：**

- Modify: `qmap/proactive_stage11_v2_verifier.py`
- Modify: `scripts/verify_capd_proactive_stage11_v2.py`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：写设计 T36-T41 失败测试**

覆盖 final approval/final-status 缺失、错 contract/run ID、错 approved-plan SHA、错 generation/verification SHA、缺外部 expected SHA、内部重哈希后外部 SHA 不匹配、额外文件、错误 phase、synthetic fixture 冒充 formal、production config 接受任一 synthetic authorization/receipt，以及直接调用 release writer 指向 production root。

- [ ] **Step 2：实现 final approval validator，不实现自动签发**

`validate_final_approval()` 接收 receipt directory 和 `approved_final_approval_receipt_sha256`。校验三文件 exact set、schema、上游 SHA、approval metadata、evidence scope 和 Test isolation。runner 不提供自动创建真实 final approval receipt 的命令。

- [ ] **Step 3：实现 guarded final-status builder/consumer**

builder 只有在 valid final approval 外部 SHA 存在时才可构造 final-status envelope；consumer 还必须接收目录外的 `approved_final_status_receipt_sha256`。任何 `synthetic_test_only=true` 输入都不得进入 production mode 或派生 effective formally verified。所有 final approval/final-status writer 与 consumer 复用 Task 8 capability guard；不得因绕过 CLI 而放宽目录或 mode 检查。

- [ ] **Step 4：强制无环引用**

逐阶段检查：

```text
execution authorization
  -> generation
  -> verification
  -> final approval
  -> final-status
```

拒绝自身 SHA、右侧未来 SHA 和回写上游目录。

- [ ] **Step 5：运行 release tests**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2ReleaseTest -v
```

Expected: synthetic 结构测试可通过；effective formal status 始终 false，未签发真实 receipt。

## Task 11：协议文档、状态文档与 v1 兼容性

**文件：**

- Create: `configs/finals/capd_proactive_stage11_v2_generation_source_manifest.json`
- Create: `configs/finals/capd_proactive_stage11_v2_verifier_source_manifest.json`
- Create: `docs/CAPD_PROACTIVE_STAGE11_V2_PROTOCOL_CN.md`
- Create: `docs/CAPD_PROACTIVE_STAGE11_V2_STATUS_CN.md`
- Modify: `tests/test_capd_proactive_stage11_v2.py`

- [ ] **Step 1：冻结 repository source manifests**

在 Tasks 3-10 的代码、config 和 schema focused tests 全部通过后，按 Task 2 的精确白名单逐文件计算 SHA，生成 generation/verifier 两个静态 manifest。先执行 AST closure、Stage11 v1 leakage 和 exclusion tests，再写 manifest；生成后不再修改任一 member。若后续测试发现必须修改 member，两个 manifest 均作废并在修复完成后重新生成，旧 manifest 不得用于 authorization。

- [ ] **Step 2：写文档 contract tests**

要求文档包含 approved design SHA、外部 approved-plan SHA、三层授权状态、generation/verifier source closure、sealed-only Stage10、Standard 48-job exact identity、Stage9 自有 gate、null/N/A、四个 Cost profile、synthetic/production 路径隔离、无环 release、当前未授权项和论文能力边界。

- [ ] **Step 3：写协议文档**

说明 CLI、schemas、input gates、hash relations、failure semantics 和未来独立审批步骤。不得提供自动签发 execution authorization/final approval 的命令。

- [ ] **Step 4：写状态文档**

只报告 implemented interfaces 和 local synthetic tests。Stage9/10 可标为 authorized external input audit capability，但不得声称 Stage11 execution、generation、final approval 或 formal verification 已发生。

- [ ] **Step 5：运行 fixture-only v1/v2 兼容测试**

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2DocumentationTest tests.test_capd_proactive_stage11_v2.Stage11V2CompatibilityTest tests.test_capd_proactive_stage11_v2.Stage11V2NoRealUpstreamAccessTest -v
```

兼容测试只可使用系统临时目录中的 synthetic v1-shaped fixture，并比较 v1 code/config/schema 的静态 SHA；不得执行 `tests.test_capd_proactive_stage11`，不得解析真实 Stage10A、历史 Stage9 或 Stage11 v1 output。真实 v1 语义回归必须留到 Task 12 Step 3 的独立审批门之后。

## Task 12：完整本地验证与冻结树复核

**文件：**

- Modify only if tests reveal a v2 contract defect
- Temporary only: synthetic fixture runs and before/after snapshots

- [ ] **Step 1：复核非语义完整性与测试 allowlist**

重新计算 approved design/plan、两个 source manifest、v1 code/config/schema 和所有冻结树的 `{path,length,sha256}`。静态扫描 `tests/test_capd_proactive_stage11_v2.py`，要求测试类集合与 Step 2 allowlist 精确相等，且没有 subprocess 启动 legacy test/runner 的路径。此步骤不得导入或执行任何 Stage8/9/10/11 旧测试模块。

- [ ] **Step 2：运行精确 fixture-only v2 allowlist**

只允许运行以下 15 个新 v2 test class，不得用 module discovery、通配符或追加旧模块：

```powershell
python -m unittest tests.test_capd_proactive_stage11_v2.Stage11V2NoRealUpstreamAccessTest tests.test_capd_proactive_stage11_v2.Stage11V2ApprovalChainTest tests.test_capd_proactive_stage11_v2.Stage11V2ConfigTest tests.test_capd_proactive_stage11_v2.Stage11V2SourceClosureTest tests.test_capd_proactive_stage11_v2.Stage11V2PrimitiveTest tests.test_capd_proactive_stage11_v2.Stage11V2StandardInputTest tests.test_capd_proactive_stage11_v2.Stage11V2Stage9GateTest tests.test_capd_proactive_stage11_v2.Stage11V2Stage10GateTest tests.test_capd_proactive_stage11_v2.Stage11V2AuthorizationTest tests.test_capd_proactive_stage11_v2.Stage11V2PathGuardTest tests.test_capd_proactive_stage11_v2.Stage11V2RunnerTest tests.test_capd_proactive_stage11_v2.Stage11V2VerificationTest tests.test_capd_proactive_stage11_v2.Stage11V2ReleaseTest tests.test_capd_proactive_stage11_v2.Stage11V2DocumentationTest tests.test_capd_proactive_stage11_v2.Stage11V2CompatibilityTest -v
```

audit hook 必须记录所有 file-open 事件的 resolved path，并在测试结束断言：真实 Stage8/9/10/11 output 与冻结 checkpoint 的 successful-open count 均为 0；denied-open 负向测试只证明 fail closed，不读取内容。任何新增测试类、真实上游 open、legacy subprocess 或 fixture 逃逸都使 Step 2 失败并停止，不能通过修改 allowlist 自动放行。

- [ ] **Step 3：在单独明确批准后执行 real upstream 的只读 audit**

本步骤是独立审批点。若用户只批准代码与 fixture tests 而未明确批准 real upstream audit，则以下所有命令和旧回归均记录 `NOT_RUN` 并跳过，不影响 fixture-only 实现测试结论。

获得明确批准后，先运行 `--audit-inputs`，stdout 预期包含：

```text
stage8_input_verified=true
stage9_input_authorized=true
stage10_input_authorized=true
generation_source_set_match=true
repository_revision_match=false
current_live_replay_compatibility=NOT_VERIFIABLE
stage11_execution_authorized=false
stage11_formally_verified=false
```

命令前后确认 `outputs/capd_proactive_stage11_v2/` 不存在。不得传 `--execute`，不得重定向为 production receipt。

随后才允许运行当前审计识别出的只读 legacy semantic cases：

```powershell
python -m unittest tests.test_capd_proactive_stage10.Stage10FormalGateTest.test_historical_r1_run_directory_is_rejected tests.test_capd_proactive_stage10_v2.Stage10V2Stage9GateTest.test_real_stage9_r3_passes_complete_read_only_gate tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_dispatch_still_verifies_historical_fixture tests.test_capd_proactive_stage10_v2.Stage10V2VerifierDispatchTest.test_v1_and_v2_verifiers_are_bidirectionally_incompatible tests.test_capd_proactive_stage11.Stage11GateTest.test_complete_stage10a_fixture_is_blocked tests.test_capd_proactive_stage11.Stage11GateTest.test_historical_stage9_run_is_not_verifiable -v
```

执行前必须重新静态扫描旧测试中的真实 output 引用；若出现上述六项之外的新 semantic case，停止并请求扩展审批，不得自动加入。不得直接运行旧模块全集，因为其中存在向真实 output root 创建 temporary directory 的测试。若后续确需完整旧回归，只能在另行批准后使用系统临时目录中的仓库镜像，并先证明镜像 artifact SHA 与真实上游一致；任何写入只能发生在镜像内。

- [ ] **Step 4：比较冻结树 before/after snapshot**

要求 Stage8 r5、Stage9、Stage10、Stage11 v1、checkpoint 所有 `{path,length,sha256}` 完全一致。任何差异均为失败，不自动修复或回滚用户文件。

同时比较 generation/verifier source manifest 的实现开始、各 synthetic lifecycle 开始、结束与最终检查快照。每个 manifest 的成员集合与 SHA 必须在单次 lifecycle 前后完全一致；source manifest 自身、approved design 和 approved plan 的 SHA/status 也必须重新校验。状态/发布文档和 tests 按明确 exclusions 不进入历史 source identity。

- [ ] **Step 5：机械检查**

执行：

```powershell
git diff --check
git status --short
```

并检查所有新增文本无尾随空白、制表符、占位标记、未闭合围栏，均以最终换行结束。

- [ ] **Step 6：最终结果分类**

最终汇报必须分开：

1. `implemented`：代码/schema/tests/docs；
2. `authorized_external_input audit`：只读 gate 结果；
3. `BLOCKED`：execution authorization 不存在；
4. `NOT_RUN`：正式 Stage11 generation；
5. `NOT_AVAILABLE`：final approval、final-status、formally verified；
6. unsupported paper claims。

不得 commit 或 push。

## 6. 任务依赖与检查点

```text
Task 1 baseline/TDD
  -> Task 2 config/schema
  -> Task 3 primitives
  -> Task 4 Stage8 Standard input
  -> Task 5 Stage9 gate
  -> Task 6 Stage10 sealed gate
  -> Task 7 authorization/preflight
  -> Task 8 generation lifecycle
  -> Task 9 independent verification
  -> Task 10 final approval/final-status contracts
  -> Task 11 docs/compatibility
  -> Task 12 full verification
```

每个 Task 完成后先运行对应 focused tests 并检查 Git 变更范围，再进入下一 Task。不得在前置 RED/GREEN 证据缺失时跨任务实现。

## 7. 计划自审

- 设计 SHA 已绑定为 `0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160`。
- approved-plan SHA 在计划获批并改为 `PLAN_APPROVED` 后由外部计算；本文不自引用，config、run identity、authorization、source manifests 和 preflight 均须绑定该外部 SHA。
- Task 2 定义了 generation/verifier 两个精确 source manifest、互不导入的闭包、明确 exclusions 和运行前后源码快照。
- Task 4 覆盖 48 个精确 Standard job、六 workload、唯一性和 policy/seed multiset。
- Task 5 保持 Stage9 自有 schema，不引入 Stage10 manifest 规则。
- Task 6 明确 sealed-attestation-only，并分离 source-set/repository revision diagnostics。
- Task 7 确保 external input 不自动授权 execution，错误或未批准的 plan SHA 在读取真实上游和 `mkdir` 前 fail closed。
- Task 8/9 通过所有 writer 共用的 capability guard 只允许 temporary synthetic lifecycle，拒绝路径逃逸、直接 writer 绕过和 synthetic receipt 进入 production。
- Task 10 补齐 final approval/final-status schema、外部 SHA、manifest/checksum、重哈希攻击和无环引用。
- Task 11 只对 v1.0 做字节快照和 synthetic-shaped 兼容测试，未授权时不执行 v1 真实语义测试。
- Task 12 在独立批准前只运行精确的 15-class fixture allowlist，并以 audit hook 证明真实上游 successful-open count 为 0；真实 upstream audit 和六项只读 legacy semantic cases 均位于同一独立审批门之后。
- 未冻结 watermark/label-weight，未批准组件消融训练，未使用 Test 调参。
- 未包含 commit、push、server execution、checkpoint selection 或 receipt signing 命令。

## 8. 审批门

当前状态：

```text
Approved Design: DESIGN_APPROVED
Plan Status: PLAN_APPROVED
Approved Plan SHA256: EXTERNALLY_REPORTED_NOT_EMBEDDED
Implementation Authorization: GRANTED_TASKS_1_12_SYNTHETIC_ONLY_EXCLUDING_STEP_3
Execution Authorization Receipt: NOT_AVAILABLE
Formal Experiment Authorization: NOT_GRANTED
Final Approval: NOT_AVAILABLE
Stage11 Formal Verification: NOT_AVAILABLE
```

本计划已获明确批准。最终 approved-plan SHA 必须在本文之外计算和报告，本文不得包含自身 SHA。当前授权仅覆盖计划中列出的本地实现、synthetic fixture 测试和非语义完整性检查；real upstream audit、production generation、receipt 签发、commit 和 push 仍须分别获得明确批准。
