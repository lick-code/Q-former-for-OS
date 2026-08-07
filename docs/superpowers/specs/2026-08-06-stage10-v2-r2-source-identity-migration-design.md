# CAPD Stage10 v2-r2 生成源码身份迁移设计

**Status:** design approved; implementation, formal execution, Stage11 migration, commit, and push are not authorized.

**Design scope:** 修复 `stage10-async-simulator-v2-r1` 将运行后可变文档测试绑定进生成身份所造成的生命周期冲突。在不改变 Stage9 输入、60 场景矩阵、离散事件语义和解释边界的前提下，新增 `stage10-async-simulator-v2-r2`，把运行前 generation identity 与运行后 release evidence 分开；Stage11 依赖只进入独立 readiness 审计，并为全部受控执行冻结 timeout 与环境证据。

## 1. 审批边界

本设计修订阶段只允许只读审计和修改本文。当前不允许修改源码、测试、配置、schema、状态文档或任何运行产物，不允许创建 r2 输出、解锁 Stage11A、commit 或 push。

设计通过后先编写独立实施计划并再次等待批准。源码实施和 r2 正式运行分别设置显式审批门。

## 2. 当前仓库审计

### 2.1 `v2-r1` 已完成的事实

现有目录 `outputs/capd_proactive_stage10/stage10-async-simulator-v2-r1/` 的只读复算结果为：

- `simulation_results.jsonl` 包含 60 条非空结果；
- 14 个 manifest payload 的 SHA256 全部匹配；
- `SHA256SUMS` 的 15 个条目全部匹配；
- Stage9 r3 的 artifact SHA 仍为 19/19；
- 产物内 `run_state.json` 和 `verification.json` 均保存 `stage10_async_simulation_verified`；
- 生成时 `run_identity.json.source_sha256.v2_tests` 为 `612d1119b52bc76317ced55917244668169644c3c1e7c3f8b06a4d8d69b06701`。

这些事实只证明仿真执行和产物生成已经发生，不足以关闭当前正式门禁。

### 2.2 当前独立复验失败

以下两个命令当前均失败：

```powershell
python scripts\run_capd_proactive_stage10.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r1
python scripts\run_capd_proactive_stage10_v2.py --verify outputs\capd_proactive_stage10\stage10-async-simulator-v2-r1
```

共同错误为 `Run identity does not match the complete independently constructed object.`。

当前 `tests/test_capd_proactive_stage10_v2.py` SHA256 为 `0e772481dfd6182aa763edbd4cfea4ddde8b186ecebccefa1b44270891f007a4`，修改时间晚于正式 run identity。只在内存中反向恢复运行后文档断言，可以精确重建生成时 SHA `612d1119...6701`；其他三个 source binding 当前仍与 run identity 相同。

### 2.3 生命周期冲突

`scripts/run_capd_proactive_stage10_v2.py::_source_hashes()` 把整个 v2 测试模块放入 generation identity。该模块在生成时要求状态文档写“Task 10 未获授权 / 正式结果 N/A”，运行后又必须改为断言“Task 10 已完成 / 正式结果已验证”。verifier 每次从当前工作区重算整个文件 SHA。

因此以下三项无法在稳定工作区同时成立：

1. 当前测试文件等于 generation identity 中的旧字节；
2. 状态文档准确描述运行后事实且文档测试通过；
3. 当前完整回归和 generation verifier 同时通过。

恢复错误状态、插入历史字符串迎合测试、或信任 run identity 自报 SHA 都被禁止。

## 3. `v2-r1` 的永久分类

`v2-r1` 永久保留，禁止修改、删除、覆盖、续写或升级。其外部分类冻结为：

```text
execution = completed
artifacts = generated_and_self_consistent
current_independent_verification = failed
formal_gate = not_satisfied
evidence_class = candidate_evidence
reason_code = generation_source_identity_lifecycle_conflict
```

不得修改 r1 的 `run_state.json` 或 `verification.json` 迎合该分类。未来状态文档应同时说明产物内生成时状态和当前外部 verifier 失败，并以后者决定正式门禁。r1 数值只能用于内部诊断和 r1/r2 一致性检查，不能授权 Stage11。

## 4. `v2-r2` 冻结标识

仿真合同语义保持不变：

```text
contract_id     = CAPD-PROACTIVE-STAGE10-2.0
evidence_mode   = deterministic_async_simulation
success_status  = stage10_async_simulation_verified
failure_status  = stage10_async_simulation_not_verified
run_id          = stage10-async-simulator-v2-r2
```

身份和证据 envelope 升级：

```text
config_schema_version             = capd_proactive_stage10_v2_1
run_identity_schema_version       = capd_proactive_stage10_run_identity_v2_1
run_state_schema_version          = capd_proactive_stage10_run_state_v2_1
verification_schema_version       = capd_proactive_stage10_verification_v2_1
manifest_schema_version           = capd_proactive_stage10_manifest_v2_1
generation_source_manifest_schema = capd_proactive_stage10_generation_source_manifest_v1_0
generation_freeze_receipt_schema  = capd_proactive_stage10_generation_freeze_receipt_v1_0
generation_test_evidence_schema   = capd_proactive_stage10_generation_test_evidence_v1_0
execution_environment_schema      = capd_proactive_stage10_execution_environment_v1_0
release_readiness_receipt_schema  = capd_proactive_stage10_release_readiness_receipt_v1_0
release_test_evidence_schema      = capd_proactive_stage10_release_test_evidence_v1_0
stage11_audit_evidence_schema      = capd_proactive_stage10_stage11_negative_audit_evidence_v1_0
final_status_evidence_schema      = capd_proactive_stage10_final_status_evidence_receipt_v1_0
release_manifest_schema           = capd_proactive_stage10_release_manifest_v1_0
```

以下 payload schema 保持 v2.0：result、scenario matrix、timing provenance 和 Stage9 input receipt。保留 contract id 是因为事件、参数和结果语义不变；metadata 版本升级使 verifier 能严格区分 r1/r2，不能只依据共同 contract id 分派。

## 5. 文件和版本边界

### 5.1 保留不改

- r1、Stage10A、Stage8 r5 和 Stage9 r3 输出；
- `qmap/proactive_stage10.py` 的事件语义；
- `qmap/proactive_stage10_v2.py` 的 Stage9 audit、timing、arrival matrix 和 simulation wrapper 语义；
- v2 result schema、approved v2 设计和 Stage9 byte-recovery audit。

### 5.2 建议新增

- `configs/finals/capd_proactive_stage10_v2_r2.json`；
- `configs/finals/capd_proactive_stage10_v2_r2_source_manifest.json`；
- source-manifest、freeze-receipt 和 release-receipt schema；
- `docs/superpowers/specs/2026-08-06-stage10-v2-r2-generation-freeze.json`；
- `scripts/run_capd_proactive_stage10_v2_r2.py`；
- `tests/test_capd_proactive_stage10_v2_r2.py`；
- `tests/test_capd_proactive_stage10_v2_release.py`；
- `docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md`。

### 5.3 建议扩展

- v1 dispatcher 增加 r2 精确分派；
- 将现有文档状态测试移出 generation test module；
- 状态文档先改为 r1 candidate / r2 pending；readiness 独立复验产生状态最终化决定后更新，再由 final-status evidence 封存。

legacy r1 verifier 保持其解释；r2 使用独立 runner/verifier，避免用条件分支悄悄升级旧 run。最终文件表和 SHA 在实施计划中冻结，设计批准本身不授权创建文件。

## 6. Generation source manifest

### 6.1 可信来源

可信仓库文件为 `configs/finals/capd_proactive_stage10_v2_r2_source_manifest.json`。r2 config 必须绑定其 path、file SHA、schema 和 `source_set_id=stage10-v2-r2-generation-core-v1`。

为避免 `source code SHA -> source manifest SHA -> config SHA -> source code constant` 的哈希环，r2 generation core 不得硬编码 r2 config 文件 SHA、source-manifest 文件 SHA 或 freeze-receipt 文件 SHA。冻结顺序固定为：

```text
final generation core bytes
  -> source manifest
  -> r2 config
  -> generation freeze receipt
  -> explicit user approval of freeze-receipt SHA
```

结构化 generation freeze receipt 必须绑定 approved design SHA、approved implementation-plan SHA、r2 config SHA、source-manifest SHA/fingerprint/count、result schema SHA、所有新增 metadata schema SHA、固定 release-test module SHA，以及 generation、formal-simulation worker、readiness、Stage11 negative audit 和 final-status 的精确 argv/module identity。它还必须绑定下列不可由运行时放宽的 hard timeout：

```text
generation_core_test_timeout_seconds = 1800
formal_simulation_timeout_seconds = 1800
release_readiness_test_timeout_seconds = 600
stage11_negative_audit_timeout_seconds = 600
final_status_test_timeout_seconds = 600
monitor_check_interval_seconds = 30
```

release-test module 必须在冻结前一次性支持 pending 与 post-decision 两个测试组；之后不得为了改变状态断言而修改其字节。freeze receipt 同时绑定运行环境 schema、必须记录的环境字段和非标准库依赖名称集合；实际环境值由每次受控执行现场记录，不能提前伪造。

freeze receipt 在正式运行审批前生成，用户批准其精确文件 SHA 后成为外部信任锚。批准值不得从仓库文件、run identity 或 receipt 自身推断，所有 r2 入口必须由调用方显式提供：

```text
--approved-freeze-receipt-sha256 <exact-lowercase-64-hex-sha256>
```

该参数对正式 r2 runner、v1 dispatcher 验证 r2、r2 native verifier、release-readiness runner/verifier 和 final-status runner/verifier 均为必填。缺失、格式错误或不匹配必须在任何输出目录创建或状态更新前 fail closed。每个入口都必须把该外部值与固定仓库路径上 receipt 的现场 SHA 比较；run 已存在时还必须与 run copy 的字节和 SHA 比较。参数值随后写入 run identity、verification 和两阶段 release receipt 只是证据记录，不能用这些自报字段代替 CLI 外部信任输入。任何 freeze receipt 变化都要求重新审批，不允许自动追认。

runner 在 mkdir 前验证可信 manifest，并将完全相同的字节保存为 run artifact `generation_source_manifest.json`。不接受调用方传入的替代 manifest。

### 6.2 Entry 合同

每个 entry 精确包含：

```text
logical_name
path
role
sha256
generation_identity
generation_test_groups
```

规则：

- path 是 project-root 相对 POSIX 路径；
- 禁止绝对路径、空路径、`.`、`..`、反斜杠、重复路径和重复 logical name；
- 解析后仍须位于 project root 且为普通文件；
- 拒绝 symlink、junction 和 reparse point；
- entries 按 path 字节序排序；
- SHA 为小写 64 位十六进制；
- role 和 test group 使用精确枚举。

核心集合至少包括：

```text
qmap/proactive_stage10.py
qmap/proactive_stage10_v2.py
scripts/run_capd_proactive_stage10.py
scripts/run_capd_proactive_stage10_v2_r2.py
tests/test_capd_proactive_stage10.py
tests/test_capd_proactive_stage10_v2.py
tests/test_capd_proactive_stage10_v2_r2.py
```

如果实施新增 r2-owned qmap 模块，必须在计划中预先加入。明确排除 generation identity：

```text
tests/test_capd_proactive_stage10_v2_release.py
tests/test_capd_proactive_stage11.py
docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md
任何运行后报告或发布文档
```

排除不等于不测试；这些文件进入独立 release evidence。

generation source set 进一步禁止任何 Stage11 代码依赖。`tests/test_capd_proactive_stage10_v2.py` 中现有的 Stage11 导入和断言必须全部移到 release test module；generation tests、runner 和其完整本地传递依赖闭包不得导入、动态加载或执行 `qmap.proactive_stage11`、`scripts.run_capd_proactive_stage11`、`tests.test_capd_proactive_stage11` 或其他 Stage11-owned module/config/schema。source-manifest validator 必须对路径集合、静态 import graph 和受控测试期间的实际本地 module load 集合执行该禁令。Stage11 负向兼容性只在 readiness 阶段审计。

### 6.3 Verifier 双重校验

每次验证必须：

1. 强制解析 `--approved-freeze-receipt-sha256`，拒绝缺失值、非小写 64 位十六进制值和重复参数；
2. 从固定仓库路径读取 generation freeze receipt，重算 SHA，并与 CLI 批准值精确比较；
3. 按 receipt 重算 r2 config、source manifest、design、plan、schema 和 release-test module SHA；
4. 从通过 receipt 验证的 r2 config 取得 source-manifest path、SHA 和 source set；
5. 要求 run copy 的 freeze receipt 和 source manifest 分别与可信仓库字节相同，并要求 run-copy receipt SHA 等于 CLI 批准值；
6. 验证 manifest schema、source set、精确 entry set、排序、路径和角色；
7. 对每个当前核心源码路径重新计算 SHA，并要求与 entry 完全相同；
8. 要求 run identity 和 verification 中的 approved CLI SHA、freeze-receipt SHA、manifest SHA、source-set fingerprint 和 entry count 一致；
9. 要求 run manifest 和 `SHA256SUMS` 正确绑定 freeze receipt 和 source manifest。

所以即使攻击者修改 source manifest、核心源码、run identity、verification、manifest 和 checksums 并重算下游摘要，仍会因可信 manifest binding 或精确集合不匹配而失败。

正式运行至两个 generation verifier 完成前不得改核心源码。运行后只允许改不在 generation identity 中的 docs/release 文件。未来核心源码合法变化会使历史 r2 verifier fail closed；不能用自报 manifest 绕过，应使用冻结工作区或新版本合同。

## 7. 测试生命周期分组

### 7.1 `generation_core`

运行前执行并进入 generation identity：

- Stage10A 回归和版本隔离；
- Stage9 r3 真实只读门禁；
- config、schema、timing、60 场景和 simulator invariants；
- r2 source manifest、metadata、checksum 和篡改负向测试；
- runner preflight、唯一 run id 和失败状态测试。

调用方提供的测试日志或 `passed=true` 不得授权正式执行。正式 runner 必须在创建 r2 root 前完成以下受控步骤：

1. 验证 CLI 批准 SHA、freeze receipt 和当前 generation source set；
2. 计算测试前的完整 path/SHA map、entry count 和 source-set fingerprint，要求与 approved source manifest 精确相同；
3. 以 project root 为 cwd、不经 shell expansion，亲自执行 freeze receipt 中冻结的精确 argv 和 module set，并应用 `generation_core_test_timeout_seconds=1800`；
4. 在 subprocess 返回后立即重算同一 generation source set，要求测试后 snapshot 与测试前 snapshot 及 approved manifest 三者完全相同；
5. 要求 exit code 为 0、测试数等于冻结的精确值、唯一 `Ran N tests`、逐项 verbose result 完整且末行是 `OK`；
6. 生成 runner-owned `generation_test_log.txt` 和 `generation_test_evidence.json`，不得接收调用方替代文件。

`generation_test_evidence.json` 必须绑定 approved freeze-receipt SHA、source-manifest SHA/fingerprint/count、精确 argv、cwd、module set、timeout、测试前后两个完整源码 snapshot、log SHA、测试数、最终状态、进程 exit code、墙钟开始/结束/持续时间和执行环境。测试期间源码变化、Stage11 module load、另一源码版本产生的合法日志、命令替换、或重哈希 evidence 中不一致的前后 snapshot 都必须在 r2 root 创建前失败。通过的临时日志/evidence 仅在全部 preflight 成功后按完全相同字节写入新建 r2 root，并进入 run identity 和 checksum 链。

正式 60 场景仿真必须由 runner 通过独立 worker subprocess 执行，并应用 `formal_simulation_timeout_seconds=1800`；不能用无法中止的 runner 内部循环冒充 hard timeout。确定性结果和产物仍要求逐字节一致，墙钟开始/结束/持续时间只作为观察字段，不进入结果相等或性能结论。

### 7.2 `release_readiness_pending`

run 生成且两个 generation verifier 通过后执行，不进入 generation identity：

- 状态文档准确记录 r1 candidate、r2 generation 已验证，以及“Stage10 对外完成尚待 release-readiness 和 final-status 封存”的 pending 状态；
- 文档保持真实系统解释边界；
- Stage10A verifier 仍通过；
- Stage11A 负向兼容性由独立审计产生：Stage10A 输入仍为 `BLOCKED / stage10a_fixture_only`，r2 输入必须为非授权状态且不能出现正向迁移；
- pending docs 更新后 generation verifier 仍通过；
- 完整回归、Stage9、冻结目录和 git 边界审计。

运行后文档测试必须在独立模块，不能再次放回 generation source manifest。该模块的固定字节和两个精确 test-group argv 已由 approved freeze receipt 绑定，因此它既不改变 generation source-set fingerprint，也不能在运行后被替换成宽松测试。

release runner 必须先重新验证 CLI 批准 SHA 和当前 generation source set，再对 release-test module、protocol 和 pending status 文档计算测试前 snapshot；随后亲自执行冻结的 pending test-group，并应用 `release_readiness_test_timeout_seconds=600`，立即计算测试后 snapshot。测试前后必须逐字节一致，release-test module SHA 还必须等于 freeze receipt 的批准值。runner-owned 日志和 evidence 必须绑定精确 argv/modules、timeout、前后 snapshot、log SHA、测试数、末行 `OK`、exit code、墙钟观察值和执行环境；不接受调用方日志。

readiness runner 还必须以独立受控 subprocess 执行 Stage11 负向审计，应用 `stage11_negative_audit_timeout_seconds=600`。该命令只能调用 Stage11A 的只读 audit interface；不得运行 Stage11 实验、写 Stage11 状态或创建任何 Stage11 output。执行前后分别计算此次审计实际使用的 Stage11-owned 本地传递依赖 path/SHA map 和 fingerprint，要求同一次审计的 pre/post snapshot 完全相同。审计结构化结果同时覆盖 Stage10A 的 `BLOCKED / stage10a_fixture_only` 和 r2 的非授权状态。该 Stage11 snapshot 不进入 generation identity。

### 7.3 `final_status_post_decision`

release-readiness receipt 经独立 verifier 通过后，才产生 `completion_decision=approved_for_status_finalization`。该决定只授权把正式状态文档从 pending 更新为“completion decision 已批准”，本身不宣称 final-status evidence 已封存，也不单独关闭 Stage10 对外门禁。

状态文档更新后，final-status runner 必须再次验证同一个 CLI 批准 SHA、当前 generation source set 和已通过的 release-readiness receipt，并对 release-test module、protocol 和最终状态文档执行与 7.2 相同的受控 pre/post snapshot 检查。它亲自执行冻结的 post-decision test-group，应用 `final_status_test_timeout_seconds=600`，生成独立 runner-owned log/evidence。正式状态文档只记录已经发生的 completion decision 和固定 final-status receipt 路径；final-status receipt 的通过状态由 receipt 自身表达，避免要求文档预先声明尚未发生的验证结果。

### 7.4 Timeout 和执行环境合同

所有受控 test/simulation/audit subprocess 每 30 秒记录 process-alive monitor 状态。普通 output stall 只产生 advisory observation，不自动终止；达到 hard timeout 时先请求正常终止，等待 10 秒后仍存活则强制终止整个子进程树，随后等待回收并 fail closed。evidence 记录 `timed_out=true`、冻结 timeout、monitor interval/observations、已用墙钟时间、exit/signal 或平台等价状态及 stderr SHA。禁止自动重试；只有用户新的明确指令才能再次尝试。若 production root 尚未创建，timeout 通过结构化 stderr/runner return 记录且不得创建 root；若 run/release root 已创建，则写入不可变 failure state 并禁止复用 id。

每次 evidence 的环境对象至少记录：

```text
python_version
python_implementation
python_cache_tag
python_executable
os_name
platform_system
platform_release
platform_version
machine
architecture
required_dependency_versions
```

`required_dependency_versions` 对 freeze receipt 声明的所有非标准库包使用排序映射；纯标准库路径必须显式记录空映射及 `dependency_policy=stdlib_only`。generation verification 在同一正式证据闭合期间要求当前环境对象与 run artifact 完全一致。未来环境漂移不能被静默忽略；应使用冻结环境复验或新合同。墙钟字段只记录，不作为确定性结果相等条件或论文性能指标。

run artifact `execution_environment.json` 精确保存 generation test 和 formal-simulation worker 两个环境对象、对应 timeout、timed-out 状态与墙钟观察值；release test 和 Stage11 audit 环境分别保存在其 phase-owned evidence 中。所有环境对象均进入各自 manifest/checksum 和上层 receipt binding。

## 8. 两阶段 release evidence

### 8.1 Phase A：release readiness

pending/readiness evidence 使用独立目录：

`outputs/capd_proactive_stage10/release_receipts/stage10-async-simulator-v2-r2/readiness/`

它不是 simulation run id，不得写入或修改 r2 run root。目录已存在时拒绝覆盖或续写。精确 payload 为：

```text
release_readiness_test_log.txt
release_test_source_snapshot.py
protocol_pending_snapshot.md
status_pending_snapshot.md
release_readiness_test_evidence.json
stage11_negative_audit_log.txt
stage11_negative_audit_source_snapshot.json
stage11_negative_audit_result.json
stage11_negative_audit_evidence.json
release_readiness_receipt.json
manifest.json
SHA256SUMS
```

receipt 至少绑定：

- r2 contract/run/evidence mode；
- r2 run identity、verification、run state、manifest 和 checksums SHA；
- 两个 generation verifier 的命令、退出状态和结构化返回；
- CLI 提供的 approved freeze-receipt SHA 及其与 repository/run-copy receipt 的比较结果；
- release test 精确 argv、modules、count、末行 OK、exit code、log SHA 和 approved release-test source SHA；
- release-test source、protocol 和 pending status 的仓库路径、测试前后 SHA map 及 snapshot SHA；
- generation、readiness、Stage11 audit、final-status 和 formal simulation 的全部冻结 timeout；
- readiness test 与 Stage11 audit 的执行环境、墙钟观察值和 timeout 状态；
- Stage10A verifier 的 status/result/manifest counts；
- Stage11 audit 的精确命令、传递依赖 pre/post path/SHA map/fingerprint、log SHA、evidence SHA 和结构化 result SHA；
- Stage10A 的 `BLOCKED / stage10a_fixture_only`、r2 的非授权结果，以及 `stage11_positive_migration_authorized=false`；
- Stage9 19/19 audit；
- Stage8、Stage9、Stage10A 和 r1 的冻结树比较；
- 全部 real-system false 边界；
- `release_status=stage10_release_readiness_verified`；
- `completion_decision_on_independent_verification=approved_for_status_finalization`。

创建 receipt 前，release runner 必须完成第 7.2 节的受控执行并要求 release 三个 snapshot 与测试前后仓库文件逐字节相同，同时要求 Stage11 审计传递依赖 pre/post snapshot 相同。封存后，readiness receipt 不进入 generation identity，通过自己的 manifest/checksum 保证不可无声修改。readiness verifier 必须接收 CLI 批准 SHA，重新验证当前 generation source set、release snapshot、Stage11 audit snapshot、日志、test/audit evidence、结构化结果、receipt 和 generation run binding，不能只读取 receipt 自报状态。首次 readiness 验证至 final-status 封存完成期间，当前 Stage11 审计依赖必须仍与 snapshot 相同；只有其结构化返回为 `stage10_release_readiness_verified` 时，才形成状态最终化决定。

### 8.2 Phase B：final-status evidence

顺序固定且不可交换：

```text
pending status snapshot
  -> release-readiness receipt verification
  -> completion decision approved_for_status_finalization
  -> update official status document
  -> controlled post-decision documentation tests
  -> seal and verify final-status evidence
```

final-status evidence 使用另一个唯一目录：

`outputs/capd_proactive_stage10/release_receipts/stage10-async-simulator-v2-r2/final-status/`

精确 payload 为：

```text
final_status_test_log.txt
release_test_source_snapshot.py
protocol_final_snapshot.md
status_final_snapshot.md
final_status_test_evidence.json
final_status_evidence_receipt.json
manifest.json
SHA256SUMS
```

final-status receipt 必须绑定 CLI 批准 SHA、完整 r2 run chain、已验证 readiness receipt/manifest/checksums SHA、readiness verifier 的精确命令/exit/status、`approved_for_status_finalization` 决定、post-decision 测试的精确 argv/modules/timeout、测试前后 snapshot、log SHA/count/OK/exit code、执行环境和墙钟观察值，以及最终 protocol/status snapshot。final-status verifier 同样强制接收 CLI 批准 SHA、重算当前 generation source set，并独立重算全部两阶段绑定；自报或重哈希 receipt 不能替代这些比较。

两个 release 子目录均唯一创建、禁止覆盖或续写；Phase B 失败必须保留失败 evidence，不能回写 r2 run 或覆盖 Phase A。历史 receipt 不永久依赖当前可变文档或 Stage11 源码。final-status 封存完成后，未来 Stage11 正向迁移或报告阶段合法修改当前 Stage11/status/protocol 时，verifier 可以报告 `current_stage11_audit_source_drift=true` 或 `current_document_drift=true`；只要封存的 Stage11/release snapshot、结构化负向结果和证据链未变，不得反向撤销已验证的历史审计。当前 generation core 漂移仍必须 fail closed，并要求冻结工作区或新合同。

Stage10 对外完成必须同时满足：

```text
r2 run_state.status = stage10_async_simulation_verified
r2 verification.status = stage10_async_simulation_verified
v1 dispatcher verification = passed
r2 native verification = passed
release readiness verification = stage10_release_readiness_verified
final-status evidence verification = stage10_final_status_evidence_verified
```

任一缺失或失败都只能报告“仿真可能已执行，但 Stage10 正式门禁未闭合”。

## 9. Run identity 和 checksum 链

run identity v2.1 用以下字段替换自由 `source_sha256` map：

```text
generation_source_manifest_schema
generation_source_manifest_sha256
generation_source_set_id
generation_source_set_fingerprint_sha256
generation_source_entry_count
generation_freeze_receipt_schema
approved_freeze_receipt_sha256
generation_freeze_receipt_sha256
generation_test_evidence_sha256
execution_environment_schema
execution_environment_sha256
```

source-set fingerprint 对完整 entries canonical JSON 计算；canonical 规则和独立测试向量必须在实施计划中冻结。run identity 内部 hash 仍对去除自身字段后的完整对象计算。

verification v2.1 重复绑定 run-identity hash、CLI approved freeze-receipt SHA、repository/run-copy freeze-receipt SHA、source-manifest SHA/fingerprint/count、generation-test evidence SHA、执行环境 SHA 和全部 frozen timeout，并要求：

```text
current_generation_sources_recomputed = true
generation_tests_verified = true
```

同时保留 Stage9 gate、simulation executed、60 result count、scenario ids、independent recomputation 和解释边界。

run manifest payload set 精确包含 `generation_freeze_receipt.json`、`generation_source_manifest.json` 和 `execution_environment.json`；`SHA256SUMS` 包含 manifest 且排除自身。预计为 17 个 manifest payload、18 个 checksum 条目、19 个总文件，实施计划必须按最终文件名重新确认而不能只断言计数。

绑定链为：

```text
CLI explicitly approved generation freeze-receipt SHA
  -> repository generation freeze receipt exact SHA
  -> repository config/design/plan/schema SHA
  -> repository source-manifest SHA/fingerprint
  -> run generation_freeze_receipt.json
  -> run generation_source_manifest.json
  -> run execution_environment.json
  -> run_identity.json
  -> verification.json
  -> manifest.json
  -> SHA256SUMS
```

readiness receipt 绑定完整 run chain；final-status receipt 再绑定 readiness chain。两者都不反向修改 generation run。

## 10. 版本分派

v1 dispatcher 必须按 `contract_id + run_id + config schema + run-identity schema` 精确分派：

- Stage10A fixture 继续进入 v1 verifier；
- v2-r1 进入 legacy verifier，当前失败保持可见；
- v2-r2 只进入 r2 verifier；
- 未知组合、schema swap 或 run-id swap 均失败。

r2 相关入口统一使用同一个批准参数。抽象 CLI 冻结为：

```powershell
python scripts\run_capd_proactive_stage10_v2_r2.py --run --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10.py --verify <r2-run-root> --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10_v2_r2.py --verify <r2-run-root> --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10_v2_r2.py --create-release-readiness <r2-run-root> --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10_v2_r2.py --verify-release-readiness <readiness-root> --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10_v2_r2.py --seal-final-status <readiness-root> --approved-freeze-receipt-sha256 <exact-sha>
python scripts\run_capd_proactive_stage10_v2_r2.py --verify-final-status <final-status-root> --approved-freeze-receipt-sha256 <exact-sha>
```

实施计划必须补全 `--run` 的 config/output 参数，但不得改变批准 SHA 参数的名称、必填性或比较语义。v1 dispatcher 仅在目标被识别为 r2 时要求该参数；Stage10A 和 v2-r1 继续使用各自历史入口，不能伪造 r2 freeze receipt。r2 native 入口必须拒绝 Stage10A、v2-r1、未知 run id 和临时测试合同。fixture 和 r1 都不能被 r2 升级。Stage11A 保留现有负向识别，r2 成功不自动产生 Stage11 正向 receipt。

## 11. 状态机和失败规则

```text
design approved
  -> implementation plan approved
  -> implementation/tests approved
  -> source set, config, schemas and freeze receipt finalized and hashed
  -> freeze-receipt SHA explicitly approved
  -> formal r2 run separately approved
  -> all preflight checks
  -> runner-owned generation tests with matching pre/post source snapshots and hard timeout
  -> unique r2 run creation and unchanged 60 scenarios
  -> formal-simulation worker with hard timeout and no automatic retry
  -> internal + v1-dispatch + r2-native generation verification
  -> update official status document to truthful pending state
  -> controlled release-readiness tests with matching pre/post snapshots
  -> seal and independently verify readiness receipt
  -> completion decision approved_for_status_finalization
  -> update official status document with that decision
  -> controlled post-decision tests with matching pre/post snapshots
  -> seal and independently verify final-status evidence
  -> rerun both generation verifiers and final frozen-tree audit
  -> Stage10 external gate closed
```

- preflight 失败不创建 r2 root；
- generation test timeout 在 mkdir 前以结构化 runner failure 记录且不创建 r2 root，禁止自动重试；
- r2 root 创建后发生 simulation timeout 或其他失败，保留 `stage10_async_simulation_not_verified` 和精确 reason/timeout/environment，不得删除、覆盖、续写或复用；
- 任一 release 子目录创建后发生 timeout 或其他失败，保留 failure evidence 和精确 reason/timeout/environment，不修改 r2 run、另一阶段 receipt 或复用该目录；
- 任一 source/path/SHA/schema/test-group mismatch 都 fail closed；
- 不允许从 r1 复制 metadata 将 r2 标成功；
- 不允许只因 r1/r2 数值相同而跳过正式运行和 verifier。

## 12. 保持不变的 Stage9 和仿真语义

r2 逐字段复用已批准 v2 语义：

- 唯一 Stage9 输入仍为 `stage9-overhead-v2-r3`，真实 19-key map 和 checkpoint/perf/RSS 门禁不变；
- inference 仍从 Stage9 mean/p50/p95/p99 以 Decimal `ROUND_HALF_UP` 派生；
- migration ratios `0.01/0.10/1.00` 和非硬件边界不变；
- `b_max=2`、64 frames、水位、K、seed、10 秒 horizon 不变；
- uniform `0.5/0.8/1.0/1.2`、burst、六 timing、五 arrival、双通道共 60 条不变；
- fixed-arrival identity、capacity-normalized 边界和 exact-rational rate 不变；
- event priority、reserved pages、容量不变量、LRU tail、MRU admission、FIFO blocking、fallback 和 null/N/A 不变；
- result schema 和全部 real-system false 字段不变。

实施必须加入 r1/r2 scenario ids、matrix、timing 和 results 的 canonical 一致性测试。任何数值差异都视为意外语义变化并停止，不得根据 r2 结果调参。

## 13. TDD 负向矩阵

至少覆盖：

- source manifest 缺失、额外、重复、乱序 entry；
- absolute path、`..`、反斜杠、路径逃逸、symlink/junction/reparse point；
- logical name、role、test group、source set 或 schema 篡改；
- 核心文件缺失或 SHA 改变；
- release/docs 错误加入 generation identity，或 core 错误移出；
- generation tests/runner/import closure 引入任何 Stage11-owned module/config/schema，或受控执行实际加载 Stage11 module；
- 篡改 source manifest 后重算 run identity、verification、manifest/checksums 仍失败；
- 同时篡改核心源码和全部摘要仍失败；
- config/source-manifest/source-code hash dependency 不得成环；
- 正式 runner、v1 r2 dispatch、native verifier、readiness runner/verifier 和 final-status runner/verifier 任一缺失、格式错误或错用 approved SHA 均失败；
- CLI approved SHA 与 repository receipt、run-copy receipt 或 release receipt 任一不匹配均失败；
- freeze receipt 缺失、未批准、SHA 改变或绑定字段篡改失败；
- 调用方自报 source manifest 失败；
- 调用方提供 generation/release 日志或 evidence 不能授权执行；
- generation log 空、失败、错命令、错模块、测试数不足、非末行 OK 或来自另一源码 revision；
- generation 测试期间源码变化，或 pre/post snapshot/evidence 重哈希后不一致；
- 正确日志配错误 approved SHA、命令/module substitution 或 subprocess 非零退出；
- readiness/final-status 测试期间 release source、protocol 或 status 变化；
- Stage11 audit 依赖闭包缺失、路径逃逸、pre/post SHA 改变、结构化结果篡改、正向授权或封存后历史证据变化；
- readiness/final-status receipt 空、失败、篡改、错 run binding、错阶段顺序或重哈希后仍与 snapshot 不一致；
- 任一 frozen timeout 缺失、被调用方覆盖、超时后自动重试、timeout 状态未记录或 worker 未终止；
- Python implementation/version/cache tag、OS/architecture 或 required dependency evidence 缺失、篡改或与当前闭合环境不一致；
- 把墙钟时间纳入确定性结果相等判断或写成性能结论；
- final status 在 readiness verifier 决定前提前声明，或 readiness receipt 要求已完成状态；
- docs-only 更新后双 generation verifier 仍通过；core 更新后均失败；
- metadata 全对象比较和 rehashed tamper；
- r1/r2 schema/run-id swap；
- source manifest 未进入 run identity、verification 或 checksum 链；
- Stage9 19/19、60 scenario ids、Stage10A 5/12 和 Stage11A BLOCKED 保持；
- Stage8、Stage9、Stage10A 和 r1 冻结树不变；
- preflight 失败不创建 production r2/release 目录。

## 14. 输出和解释边界

r2 run root：`outputs/capd_proactive_stage10/stage10-async-simulator-v2-r2/`。

r2 release base：`outputs/capd_proactive_stage10/release_receipts/stage10-async-simulator-v2-r2/`，其下只允许唯一 `readiness/` 和 `final-status/` 两个封存目录。

r2 run root 和两个 release 子目录都唯一创建、禁止覆盖；release base 不能位于 run root 内。

在双 generation verifier、readiness verifier 和 final-status verifier 全部通过前，Stage10 只能报告实现或执行进度，r1 指标不能作为正式结果，74/74 回归不能替代 run identity gate，Stage11A 不得解锁。

全部通过后只能声称“Stage10 确定性异步仿真已验证”，仍不能声称真实 NVM、真实内核并发、真实前台端到端延迟或真实系统异步性能已验证。Stage11 正向迁移必须另行设计和批准。

## 15. 自审清单

- [x] r1 永久保留并分类为 candidate evidence。
- [x] r2 run id 固定。
- [x] identity/source-manifest schema 升级。
- [x] source manifest 包含核心路径和 SHA，verifier 重算当前源码。
- [x] generation core 与 release/docs 测试分离。
- [x] source manifest 进入 run identity、verification 和 checksum 链。
- [x] generation freeze receipt 提供无环的外部批准锚并进入证据链。
- [x] 外部批准 SHA 通过必填 CLI 参数进入 runner、dispatcher 和全部 r2/release verifier，缺失即失败。
- [x] generation/release 测试由受控 runner 执行，并绑定批准源码及测试前后 snapshot。
- [x] generation source set 禁止 Stage11 依赖；Stage11 负向审计及传递依赖快照只进入 readiness evidence。
- [x] Stage11 未来合法漂移只报告 informational drift，不反向破坏 Stage10 generation identity。
- [x] generation、formal simulation、readiness/Stage11 audit 和 final-status timeout 已固定，超时 fail closed 且禁止自动重试。
- [x] Python/OS/architecture/dependency 环境进入证据链，墙钟时间仅观察不参与确定性相等。
- [x] readiness 与 final-status 两阶段 evidence 独立于 generation run root，完成顺序无状态环。
- [x] Stage9、60 场景和仿真语义不变。
- [x] path/SHA/group/rehashed tamper 均有负向测试。
- [x] 正式运行保留独立审批门。
- [x] Stage10 完成要求双 generation verifier、两阶段 release verifier、回归和冻结审计。
- [x] Stage11A 继续阻塞并需单独批准。
- [x] 本文未授权源码、r2 run、commit 或 push。

## 16. 审批后的下一步

设计获明确批准后，先将状态更新为 `design approved` 并计算最终 approved-design SHA，再编写绑定该 SHA 的独立实施计划，然后停止等待实施计划批准。实施完成后仍须在正式 r2 运行审批门停止。
