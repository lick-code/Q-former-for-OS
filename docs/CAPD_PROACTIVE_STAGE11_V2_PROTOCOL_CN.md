# CAPD Stage11 v2 正向证据迁移协议

## 1. 合同身份与边界

- 合同：`CAPD-PROACTIVE-STAGE11-2.0`
- Production revision：`stage11-v2-production-r1`
- Production run ID：`stage11-standard-cost-profiles-v2-r1`
- Approved production-design SHA256：`ec00fdaeac4084f638fbf6da866d4444badd26dfac95eef061e137a5a26ba356`
- Approved production-plan SHA256：`5ada02d3cd2f14c116dccbf4336dc833c460c3d7198e58eb17efd72f0bc66143`
- 历史 synthetic approved-design SHA256：`0e2faa13c02172a16b40eae83a8556300bad761b7de3dfd1b51d49276c7d5160`
- 历史 synthetic approved-plan SHA256：`64a8c99acd0f2475a5a792fe732439691b6667ed11890578da74ca0707832870`
- 生产输出根：`outputs/capd_proactive_stage11_v2/`

Stage11 v2 与 Stage11A/v1.0 隔离。历史 synthetic 五个源码文件、两份 source
manifest 与 41-test 基线保持逐字节不变；production 使用五个独立的
`*_production` 模块与独立 schema family。当前 `Gate A` 只授权代码、schema、
56 项 production fixture 测试和冻结树非语义完整性检查。它不授权 source
manifest freeze、真实上游语义审计、production generation、receipt 签发、
正式实验、commit 或 push。

授权状态分为三层，不能互相替代：

1. `authorized_external_input`：Stage9/Stage10 上游 gate 已通过；
2. `stage11_execution_authorized`：独立 execution authorization receipt 及其
   外部预期 SHA 已通过；
3. `stage11_formally_verified`：generation、verification、final approval 和
   final-status 的完整无环证据链已通过。

Synthetic fixture 在任何情况下都不能把上述字段升级为生产授权或正式状态。

## 2. 固定配置与 Standard 输入

production repository config 固定主配置 `b_max=2`，唯一授权 lane 是
`offline_cost_profiles`。watermark、label-weight、capacity、`b_max=1/4`、
Top-1/Top-b、组件消融、新 Stage9 开销和新 Stage10 异步场景全部记录为
`BLOCKED`，不生成占位数值行。历史 synthetic config 中记录的分析网格不构成
production 授权。Test 不用于参数、checkpoint 或网格选择。

Stage8 r5 是同步离线输入的唯一权威来源。v2 从权威 `job_manifest.json` 过滤
`track=standard`，再通过 `job_id` 连接 `artifacts/per_workload_raw.csv`、
`jobs/<job_id>/job_manifest.json` 和 `result.json`。每个 result bytes SHA、
semantic SHA、plan identity 和原始 counters 都必须闭合。

Standard 子集必须为 48 个唯一 job、6 个 workload。每个 workload 的精确成员为：

- `reactive_lru`、`proactive_lru`、`proactive_clock`、`tpp_inspired`、`oracle`
  各一个无 seed job；
- `capd` 的 seed 精确为 `42`、`2026`、`3136859`。

即使总数仍为 48，重复一个 job 并遗漏另一个 job 也必须拒绝。访问数只能读取
`raw_access_count`，不得从浮点 Cost 反推。

## 3. 离线 Cost 合同

四个 profile 在运行前固定：

| profile | DRAM hit | NVM read | NVM write | demotion |
|---|---:|---:|---:|---:|
| `read_light` | 1 | 2 | 4 | 8 |
| `default` | 1 | 2 | 8 | 10 |
| `write_expensive` | 1 | 2 | 12 | 10 |
| `migration_expensive` | 1 | 2 | 8 | 20 |

`NVM write` 是 NVM 写访问成本；`demotion` 是 DRAM 到 NVM 的迁移成本。
离线重算只产生 `candidate-ready`。JSON 缺失数值使用 `null`，CSV/Markdown
显示 `N/A`，不使用零值替代缺失证据。

## 4. Stage9 与 Stage10 gate

Stage9 按自身 v2 schema 验证 `run_state.json`、`verification.json`、
`stage8_compatibility_receipt.json`、`verification.json.artifact_sha256`、
Linux CPU 环境、原始 latency、perf `cycles/instructions/task-clock`、scope 和
RSS/memory 字段。Stage9 不采用 Stage10 式根 `manifest.json + SHA256SUMS`。
缺失、字段错误或 SHA 不一致返回 `NOT_VERIFIABLE`。

Stage10 只消费 v2-r2 的 sealed envelope 与三个外部 receipt SHA。判断拆分为：

- `generation_source_set_match`：generation source manifest 的成员 SHA 集合；
- `repository_revision_match`：封存 revision 与当前仓库 revision；
- `sealed_dual_verifier_attestation`：封存 native/dispatcher attestation；
- `current_live_replay_compatibility`：当前代码重放兼容性。

Stage11 gate 不用当前 HEAD 重构历史 run identity，也不运行当前 Stage10 verifier。
`generation_source_set_match=true` 与 `repository_revision_match=false` 可以同时成立；
此时 sealed attestation 可被验证，而 live replay 仍为 `NOT_VERIFIABLE`。
Stage10 的 real-system flags 必须全部为 false，因此该证据不能支持真实并发、
真实 NVM、kernel 行为或前台端到端 latency 结论。

## 5. Source identity 与运行前后快照

generation 和 verifier 使用独立静态 source manifest。production 计划冻结的
精确成员数分别为 `30` 与 `32`，测试源码闭包为 `29`。每个 manifest 绑定
approved design/plan SHA、精确成员路径、成员 SHA、`members_sha256` 和本地
import closure。generation 只导入标准库、`qmap.proactive_cost` 和共享路径
guard；verifier 不导入 generation 或 Cost helper，独立使用整数公式重算。

测试、fixture、输出、release receipt、设计/计划、协议和状态文档不属于运行时
source identity。production 模块不得导入历史 Stage11 v2 模块或脚本。若运行时
代码导入被排除内容，closure 校验必须失败。每次
generation/verification 都在发布前比较 source snapshot before/after；成员缺失、
新增依赖、Stage11 v1 泄漏、相同长度字节变化或运行中源码变化均拒绝发布。

## 6. 路径能力、监控与 CLI

所有 writer 必须持有共享 guard 签发的 phase capability。六种能力
`input_audit`、`execution_authorization`、`generation`、`verification`、
`final_approval`、`final_status` 不可互换；verification capability 不能写
final-approval/final-status，final-approval capability 不能写 final-status。
每个 capability 同时绑定 phase、唯一输出根、audit/run ID、approved-plan SHA
和 nonce。直接调用 writer、`..` 逃逸、symlink/reparse point、跨 phase 写入、
不同 run ID 复用都会在写入前失败。

正式 generation 与 verification 均由 public CLI 作为 supervisor 启动唯一
worker。监控合同固定为每 5 秒 process-alive、1800 秒 hard timeout、10 秒终止
宽限、`attempt_count=1`、`automatic_retry_performed=false`。timeout、crash 或
monitor failure 不 seal package，也不自动重试。PID、alive sample 与 wall-clock
只进入运行诊断，不参与 192 行结果或确定性 artifact equality。

不读取真实上游的只读 preflight：

```powershell
python scripts/run_capd_proactive_stage11_v2_production.py
```

该命令默认输出 `real_upstream_audit=NOT_RUN`、input audit pending 和 generation
blocked。`--capture-input-audit --allow-real-upstream-audit`、
`--execute-production`、`--verify-input-audit`、`--verify-generation` 以及六项
legacy semantic tests 均位于各自独立审批门之后，当前不得执行。fixture-only
测试只在系统临时目录调用 contract API，不形成仓库 production 产物。

## 7. 无环 release 顺序

正式顺序只能是：

```text
approved design/plan
  -> production code/schema fixture validation
  -> generation/verifier source manifest freeze
  -> input-audit capture + independent verification
  -> execution authorization
  -> generation
  -> independent verification
  -> external final approval
  -> final-status evidence
```

每个 phase 的 `manifest.json` 排除自身和 `SHA256SUMS`；`SHA256SUMS` 包含
manifest、排除自身。receipt 本身不保存自身 SHA，也不引用未来阶段 SHA。
receipt 的预期 SHA 必须由 envelope 外部提供；篡改后重算内部 manifest/checksum
不能替代外部 anchor。

## 8. 失败语义与论文能力边界

- 缺少真实上游或外部 SHA：`NOT_VERIFIABLE`；
- 上游通过但 execution authorization 缺失：`BLOCKED`；
- synthetic 或离线输出：至多 `candidate-ready`；
- generation 完成但后续回执缺失：pending，`stage11_formally_verified=false`。

当前协议不能支持真实 CPU latency、cycles、instructions、task-clock、RSS、
模型内存、真实迁移开销、真实异步系统性能、正式组件消融或 Stage11 formally
verified 论文结论。NoVPN/NoContext/NoPageState 仍是 `BLOCKED` 接口，不得把
推理时遮蔽写成模型组件消融。

## 9. 当前 Gate A 状态

- `implemented`：production-specific config/schema、六能力 guard、input-audit
  package API、Stage8 SHA/semantic join、Stage9-native gate、Stage10 sealed gate、
  192 行整数 Cost 重算、generation/verification supervisor 与 release consumer。
- `fixture-tested`：历史 `41/41` 与 production `56/56` 必须分别通过；该状态不等于
  input audit、execution authorization 或 formally verified。
- `input-audit pending`：真实上游 semantic audit 仍以状态文档中的 `NOT_RUN` 为准，
  直到后续 Gate C 生成并独立验证 package 且外部 SHA 获批。
- `execution blocked`：Gate B source manifests 与 execution authorization receipt
  尚未签发。
- `generation pending`、`verification pending`、`final approval pending`、
  `final-status pending`：每项均需新的独立批准，不能由 Gate A 自动提升。
