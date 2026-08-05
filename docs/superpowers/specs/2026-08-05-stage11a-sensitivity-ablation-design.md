# CAPD Stage11A 敏感性与消融设计

## 文档状态

- 状态：设计草案，等待用户复核。
- 本文档的批准范围：允许编写和自审 Stage11A 设计，不批准正式 Stage11 实验、服务器测量、结果发布、自动 commit 或 push。
- Stage11A 所有输出必须区分 `implemented`、`candidate-ready`、`formally_verified`、`BLOCKED` 和 `NOT_VERIFIABLE`。实现代码存在不等于实验结果已验证。

## 1. 目标与非目标

Stage11A 为 CAPD 当前 Stage8 权威结果建立独立的敏感性、消融、历史筛选器负向结果和 Stage9/Stage10 外部门禁接口。目标是让可以在本地完成的离线重算和同步候选分析可重复、可审计，并让不能在当前环境验证的真实系统开销和异步行为明确失败关闭。

本阶段不重新训练模型，不选择新的主 checkpoint，不从 Test 结果反向修改主配置，不伪造或估计 CPU latency、cycles、instructions、task-clock、RSS、模型内存、真实并发或异步开销，不改写 Stage8、Stage9 failed/immutable evidence 或 Stage4/7 冻结 checkpoint。

## 2. 证据权威与不可变边界

### 2.1 Stage8 输入

唯一的正式同步输入是：

`outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`

Stage11A 必须按 Stage8 自己的契约校验这个目录，而不能假设每个阶段都有相同的根目录文件。当前需绑定的事实包括：

- `run_state.json.status == stage8_sync_replay_verified`；
- `run_state.json.contract_id == CAPD-PROACTIVE-STAGE8-2.0`；
- `verification.json.status == stage8_sync_replay_verified`；
- `verification.json.formal_job_count == 80`，其中 Standard 为 48、Pressure 为 32；
- `verification.json.job_results_verified == true`、`statistics_verified == true`、`frozen_parameters_changed == false`、`test_used_for_parameter_selection == false`；
- `artifacts/per_workload_raw.csv` 只作为聚合索引和已保存计数的交叉检查；它不被单独视为完整事件来源。它的每一行通过 `job_id` 连接对应的 `jobs/<job_id>/result.json`；
- 根 `job_manifest.json`、`run_identity.json`、`resolved_config.json` 和 Stage8 自身 verification SHA 链与输入路径一起记录；根 manifest 的 80 个 job 计划必须覆盖 CSV 的 `job_id`；
- 每个 `jobs/<job_id>/job_manifest.json` 必须为 `status == completed`，并提供 `result_sha256` 和 `semantic_result_sha256`。Stage11A 重新计算 `result.json` 的文件 SHA，与 `result_sha256` 比较，再按 Stage8 contract 重新计算/校验 semantic result SHA；
- `jobs/<job_id>/result.json.metrics` 是 `raw_access_count`、`reactive_demotions`、`dram_hits`、`nvm_reads`、`nvm_writes`、demotion breakdown 和其他同步指标的权威字段。Stage11A 不通过浮点 `weighted_cost_per_access` 反推访问数；
- Stage11A 结果行保存 `source_job_id`，并同时保存该 job result 的文件 SHA 和 semantic result SHA。任何 join 缺失、重复、错配或篡改都使 offline lane 失败关闭。

Stage8 的同步解释边界必须原样保留：它支持 page-ranking quality、NVM events、weighted cost 和同步状态轨迹，不支持真实后台并发、foreground latency、CPU overhead 或 memory overhead。

### 2.2 冻结目录

Stage11A 只创建新的 Stage11 输出目录：

`outputs/capd_proactive_stage11/`

禁止写入或删除下列目录中的任何文件：

- `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`
- `outputs/capd_proactive_stage9/stage9-overhead-r1/`
- 已冻结的 Stage4/7 checkpoint 目录。

运行前后应对冻结目录做文件路径、大小和 SHA256 快照比较；任何差异都使 Stage11A 运行失败。

## 3. 总体架构

Stage11A 使用一个独立 runner 和三个相互独立的证据通道。通道之间共享只读的配置和证据 envelope，但不共享“已验证”状态。

```text
Stage8 r5 authority
        |
        +--> Stage8-specific validator --> offline_recompute
        |                                      |
        |                                      +--> cost profiles / raw-counter report
        |
        +--> frozen Stage11 grid ----------> sync_candidate
        |                                      |
        |                                      +--> synchronous replay rows
        |
        +--> stage-specific external gates -> Stage9 gate
                                               Stage10 gate
```

### 3.1 `offline_recompute`

该通道只接受 Stage8 r5 已通过自身 verification 的 raw counters。它不重放 trace、不改写事件计数、不读取 Stage9/Stage10 产物，也不推断系统延迟。

对每一行使用：

```text
weighted_cost =
    dram_hit * dram_hits
  + nvm_read * nvm_reads
  + nvm_write * nvm_writes
  + demotion * total_demotions
```

`weighted_cost_per_access = weighted_cost / raw_access_count` 仅在 job result 提供 `raw_access_count > 0` 时计算；空 trace 或缺失计数写入 JSON `null`，CSV/Markdown 显示 `N/A`。禁止从已有浮点 weighted cost 或 weighted cost per access 反向推导 `raw_access_count`。

其中 `nvm_write` 明确表示 NVM 写访问成本，`demotion` 明确表示 DRAM -> NVM 迁移成本。默认 profile 固定为 `1:2:8:10`；敏感性 profile 固定为：

- `1:2:4:8`
- `1:2:8:10`
- `1:2:12:10`
- `1:2:8:20`

该通道可以产生 `candidate-ready` 的离线结果，但不能把离线 weighted cost 转写为 CPU、RSS、真实并发或异步延迟结论。

### 3.2 `sync_candidate`

该通道定义并执行同步 Replay 候选任务。运行前将完整 grid 展开为稳定排序的 job records，计算 `frozen_grid_sha256`，并在任何结果写入前保存 grid、配置和输入 SHA。运行时不得根据已生成结果删除、增加、重排或选择参数。

主配置的正式 `b_max=2` 是不可变控制值。`b_max=1/2/4` 只能出现在标记为 sensitivity 或 batch ablation 的分析行中，不能覆盖主配置。

当某一同步 replay 真正执行并通过独立重算时，其状态最多为 `candidate-ready`；Stage11A v1.0 不会把任何同步或 Stage10A fixture 行升级为 `formally_verified`。若只有代码、配置和 fixture 而没有真实 Stage8 输入重放，状态为 `implemented` 或 `NOT_VERIFIABLE`，不得填入估计指标。

### 3.3 `external_gates`

该通道包含两个不同的 validator，分别遵守 Stage9 和 Stage10 的实际契约。它们不使用统一的“manifest + SHA256SUMS”假设。

#### Stage9 validator

Stage9 只有同时满足下列条件才可向 Stage11A 提供 `stage9_overhead_verified` 输入：

- `run_state.json.status == stage9_overhead_verified`；
- result schema 要求的全部 artifacts 存在，包括 `run_identity.json`、`resolved_config.json`、`stage8_compatibility_receipt.json`、`environment.json`、raw latency、perf、memory、quality、capacity、`verification.json` 和 `run_state.json`；
- `environment.json` 证明真实 Linux CPU 测量；
- `verification.json` 的 required verification fields、服务器证据和 schema 约束全部通过；
- `verification.json.artifact_sha256` 对 Stage9 runner 实际纳入映射的 schema artifacts 逐项重新计算并匹配；该映射按现有实现排除 `verification.json` 自身和 `run_state.json`，Stage11A 另外在自己的输入 envelope 中记录这两个文件的 SHA；
- `stage8_compatibility_receipt.json` 绑定 Stage8 r5 的 contract、run identity、输入 SHA 和 checkpoint SHA；
- perf cycles/instructions/task-clock、latency、RSS、memory breakdown、capacity 和 regression evidence 均可独立验证。

Stage9 的主要契约不是根目录 `manifest.json + SHA256SUMS`。Stage11A 不得因为缺少这两个文件而把一个符合 Stage9 自身 schema 的目录判为无效，也不得仅凭文件存在而跳过 `artifact_sha256` 和 verification 内容校验。当前 `stage9-overhead-r1` 的 failed/immutable 证据必须被拒绝为正式 Stage9 输入。

#### Stage10 validator

当前 Stage10 只有 Stage10A fixture 契约，没有 Stage10B 正向验收契约。现有 result schema 只允许 `mode=fixture`，现有 runner 和 verifier 要求 `stage10_formally_verified=false`。因此 Stage11A v1.0 只实现以下负向门禁：

- 按当前 Stage10A schema 识别 fixture result，并验证 result schema SHA binding；
- 验证 Stage10A 自己的 `manifest.json`：排除 `manifest.json` 和 `SHA256SUMS` 后，文件集合与 payload 完全一致，所有 digest 重新计算匹配；
- 验证 Stage10A 自己的 `SHA256SUMS`：包含 manifest、排除自身，且每一行 digest、路径和目录边界通过；
- 验证 `formal_gate.json.formal_authorized == false` 且状态为 `stage10_formal_blocked_by_stage9`；
- 验证 `run_state.json.status == stage10_simulator_tests_passed`、`stage10_simulator_implemented == true`、`stage10_simulator_tests_passed == true`、`stage10_formal_blocked_by_stage9 == true` 和 `stage10_formally_verified == false`；
- 将该输入记录为 Stage10A fixture/candidate evidence，并固定输出 `BLOCKED`，不得把 runner 内部 `verify_run()` 返回的 `status=verified` 解释为 Stage10 正式验证。

如果 Stage10A 目录缺失、输入为空、字段缺失、SHA 不匹配或内容被篡改，Stage11A 输出 `NOT_VERIFIABLE`。如果目录完整且准确证明它只是 fixture，Stage11A 输出 `BLOCKED`。两种情况都不产生正式异步结果。

Stage11A v1.0 不定义或猜测任何 Stage10B 正式状态名、字段、manifest 内容或正向接受规则。只有 Stage10B 正式契约另行冻结并获得设计批准后，才能通过新的 contract/schema version 增加正向验收逻辑。Stage10A 的 `manifest.json`、`SHA256SUMS` 和 `formal_gate.json` 要求不反向施加到 Stage9。

## 4. Stage11A 配置契约

实现阶段新增独立配置：

- `configs/finals/capd_proactive_stage11a.json`
- `configs/finals/capd_proactive_stage11a_result_schema.json`

配置使用独立 contract id `CAPD-PROACTIVE-STAGE11A-1.0`，不覆盖 Stage8/Stage9/Stage10 配置。配置记录：

- `stage8_authority_path`、Stage8 contract、run identity 和所有输入 artifact SHA；
- 代码版本标识、配置 SHA、result schema SHA、`run_id` 和创建时间；
- `F_low`、`F_target`、`F_target-F_low`、`D`、`K`、capacity、`b_max`、history、label weights、checkpoint policy 和 ablation 参数；
- `grid_frozen`、稳定排序后的完整 grid、`frozen_grid_sha256` 和 `test_used_for_parameter_selection=false`；
- cost profile 名称、四个非负整数权重及语义说明；
- Stage9/Stage10 输入路径、预期状态和 gate policy。

`code_version` 不能只保存人类可读版本名。它至少包含当前 Git commit SHA、worktree 是否 dirty，以及 Stage11 runner、纯函数模块、配置和 result schema 各自的 SHA256。dirty worktree 不自动判失败，但必须被完整披露，且相同 `run_id` 不得在代码内容变化后续写。

### 4.1 敏感性 grid

所有 grid 必须在运行前被展开并哈希。实现不得提供“运行后挑最优”的接口。

- 水位：逐 workload 记录 `F_low` 和 `F_target-F_low` 的候选值；每个值必须是配置中显式的整数，并通过 `0 <= F_low < F_target <= D` 和容量约束校验。
- 批量：`b_max=1/2/4`。主实验行永远保留正式 `b_max=2`，敏感性行带有独立 `analysis_only=true`。
- 容量：working set 的 `20%/40%/60%`，保存原始 working-set 页数、四舍五入规则和最终页数，禁止运行时隐式调整。
- label-weight：保存每一组权重向量和来源；主权重沿用冻结 checkpoint contract，附加权重只能是预先列出的分析行，不能由 Test 选择。
- cost profile：仅使用本节规定的四组 profile；默认 profile 仍为 `1:2:8:10`。

本文档不擅自指定尚未获批的水位候选整数或附加 label-weight 候选。实现可以完成相应 schema、解析器、稳定展开和 synthetic fixture 测试，但真实 `sync_candidate` runner 必须在未来获得一份显式枚举这些值、带 `grid_frozen=true` 和有效 `frozen_grid_sha256` 的配置后才允许运行。缺少该配置时状态为 `BLOCKED`，不得从 Stage8 Test 结果或运行后的结果自动生成候选值。

### 4.2 消融 grid

消融 ID 固定为：

- `CAPD-Full`
- `CAPD-NoVPN`
- `CAPD-NoContext`
- `CAPD-NoPageState`
- `Proactive-CAPD-Top-1`
- `Proactive-CAPD-Top-b`

输入消融接口必须区分“推理时遮蔽诊断”和“模型组件消融”。Stage11A v1.0 不执行或宣称完成后者：`CAPD-NoVPN`、`CAPD-NoContext` 和 `CAPD-NoPageState` 的结果行只定义 schema/interface，并标记 `BLOCKED`。把 Full checkpoint 的输入字段屏蔽后得到的结果，若未来获批执行，只能标记 `inference_masking_diagnostic`，不能称为模型组件消融。

现有 NoVPN runner 会单独训练并选择 Validation checkpoint；它是历史配对实验的证据，不是当前 Stage11A 可直接复用的正式消融结果。未来要形成正式输入消融，必须另行批准固定的变体训练协议、Train-only 训练数据、Validation-only checkpoint 选择规则、seed 集合和 SHA-bound 配对结果；Test 不得参与选择。当前 Stage11A 只保留这些接口和 `BLOCKED` 门禁。

`Proactive-CAPD-Top-1` 与 `Proactive-CAPD-Top-b` 必须共享相同主动水位、checkpoint、trace、label weights、capacity 和其他配置，唯一变化是每轮选择数量。报告不得把它们写成“新旧 CAPD”比较。

筛选器负向探索只接入已保存的既有证据，保持在 `historical` evidence mode，不进入正式方法矩阵。报告可复述已有的 oracle headroom=0、weighted cost 无改善和延迟增加；若无法从实际 artifact 绑定相应字段，必须输出 `N/A/NOT_VERIFIABLE`。

## 5. 结果与运行状态契约

实现阶段的 Stage11A 输出根目录为 `outputs/capd_proactive_stage11/<run_id>/`，计划包含：

- `stage11a_config.json`
- `stage11a_manifest.json`
- `stage11a_results.csv`
- `stage11a_results.json`
- `stage11a_report.md`
- `verification.json`
- `SHA256SUMS`
- `run_state.json`

每一个结果行至少携带：

```text
run_id
row_id
source_job_id
source_result_sha256
source_semantic_result_sha256
lane
evidence_status
evidence_mode
parameter_family
grid_cell_id
frozen_grid_sha256
track
workload
seed
policy_or_ablation
D
F_low
F_target
F_target_minus_F_low
capacity_working_set_fraction
b_max
label_weights
cost_profile
dram_hits
nvm_reads
nvm_writes
proactive_demotions
reactive_demotions
emergency_demotions
total_demotions
raw_access_count
weighted_cost
weighted_cost_per_access
input_artifact_path
input_artifact_sha256
config_sha256
code_version
```

只有确实有数据的字段才能填写数值。JSON 中缺失的数值字段使用 `null`；CSV 和 Markdown 将 `null` 显示为 `N/A`，并同时说明阻塞原因。`0` 只表示实际计数为零，不表示缺失。同步或异步延迟、CPU、RSS、模型内存和并发字段在没有对应 verified evidence 时必须为 `null`/`N/A`。

建议的 `run_state.json` 状态集合为：

- `stage11a_implemented`
- `stage11a_candidate_ready`
- `stage11a_blocked`
- `stage11a_not_verifiable`

状态转换由通道证据决定，不允许通过命令行参数直接升级。只要 Stage9 或 Stage10 gate 缺失，相关 lane 必须保持 `BLOCKED/NOT_VERIFIABLE`，不影响 offline lane 的 `candidate-ready`。

`formally_verified` 保留为跨阶段 evidence vocabulary，但不是 Stage11A v1.0 的可生成状态。Stage11A v1.0 不会写 `stage11a_formally_verified`，也不会接受 Stage10B 正向状态；未来 Stage10B 契约和 Stage11 正式执行批准必须通过新的 schema version 才能扩展状态集合。

## 6. 数据流与写入安全

1. 读取独立 Stage11A 配置，校验 Stage11 schema、配置 SHA、输出路径边界和冻结 grid。配置、Stage8 authority 或输出路径失败是全局致命 preflight，运行目录不得创建。
2. 按 Stage8 自身契约读取并验证 r5 authority；记录每个输入文件的 SHA，不复制或修改输入。
3. 建立只读 evidence envelope，包含 input SHA、config SHA、schema SHA、code version、run identity 和 frozen grid identity。
4. 通过全局 preflight 后立即创建新的 Stage11 run directory；拒绝已有 run id，禁止覆盖或续写失败 run。Stage9/Stage10 尚未在此步骤作为全局前置条件。
5. 在已创建的 Stage11 run directory 内分别运行 `offline_recompute`、`sync_candidate` 和 `external_gates`。Stage9/Stage10 是局部门禁：缺失或失败只写对应 lane 的 `BLOCKED/NOT_VERIFIABLE`，不能阻止 offline lane 写出真实的 `candidate-ready` 离线结果。
6. 独立重算选定 raw counters、weighted cost、行数、grid digest 和状态字段，生成 Stage11 `verification.json`。
7. Stage11 自己可以生成 `stage11a_manifest.json` 和 `SHA256SUMS` 作为 Stage11 输出完整性工具：前者排除自身和 `SHA256SUMS`，后者包含 manifest、排除自身；两者均不得递归哈希。这不改变 Stage9 的输入契约，也不代表 Stage9/10 已 verified。
8. 原子写入 `run_state.json`，最后写报告，报告按“已实现、candidate-ready、Stage9 阻塞、Stage10 阻塞、不能支持的论文结论”分节。

## 7. 错误处理与 fail-closed 规则

以下情况必须失败关闭且不得写出正式 verified 结果：

- Stage8 路径不存在、状态错误、contract 错误、raw counter 缺字段或 SHA 不匹配；
- 输入 CSV/JSON 为空、重复 identity、数值类型错误、计数为负或事件总数不一致；
- grid 未冻结、grid digest 改变、主 `b_max=2` 被敏感性行覆盖、Top-1/Top-b 除选择数量外存在配置差异；
- Stage9 缺任一 schema artifact、非 Linux CPU、perf/RSS 证据缺失、`artifact_sha256` 不匹配、Stage8 receipt 不匹配或状态为 `stage9_not_verified`；
- Stage10 缺 manifest、SHA256SUMS、formal gate、Stage9 receipt、verified run state，或 manifest/checksum/result 任何一项被篡改；
- 发现输出路径解析到 Stage8/Stage9/Stage4/7 冻结目录；
- 报告试图把 fixture、设计文档、测试日志或历史 selector 结果描述为正式 Stage9/Stage10 证据。

错误报告应说明对应 lane 的 `BLOCKED` 与 `NOT_VERIFIABLE` 原因，不用零值替代缺失，不自动重试或改变参数。

## 8. 测试设计

实现阶段新增 `tests/test_capd_proactive_stage11.py` 和 `tests/fixtures/stage11a/`，优先使用当前仓库可用的 `python -m unittest` / `PYTHONPATH` 方式。测试覆盖：

- 配置解析、cost profile 语义和四组 profile 离线重算；
- watermark、batch、capacity、label-weight、ablation grid 的显式展开、稳定排序和 digest 固定；
- 主 `b_max=2` 不被敏感性覆盖；Top-1/Top-b 的唯一差异检查；
- Stage8 raw counter 空输入、缺字段、重复 identity、非法计数和篡改 SHA；CSV `job_id` 到每个 job 的 `job_manifest.json`/`result.json` join、`result_sha256` 和 `semantic_result_sha256` 篡改；
- `raw_access_count` 和 `reactive_demotions` 只能来自 job result；禁止通过浮点 weighted cost 反推访问数；
- Stage11 manifest/SHA 生成与独立校验，并确认 manifest 排除自身和 `SHA256SUMS`、`SHA256SUMS` 包含 manifest 且排除自身；
- Stage9 validator 接受其真实 schema 所需 artifacts 和 `verification.json.artifact_sha256`，但不要求根目录 manifest；
- Stage10 validator 只识别当前 Stage10A fixture schema，要求其自身 manifest、SHA256SUMS、formal gate 和 `stage10_formally_verified=false`，并对完整 fixture 返回 `BLOCKED`；拒绝缺失或篡改文件；
- 全局 Stage8/config/output preflight 失败时不创建 run；Stage9/Stage10 局部门禁失败时仍创建 run，并确认 offline lane 可写出 `candidate-ready`；
- 缺少正式 Stage9/Stage10 产物时输出 `BLOCKED/NOT_VERIFIABLE`；fixture、设计文档和测试日志不能升级状态；
- `CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState` 输入消融接口行固定为 `BLOCKED`；推理时遮蔽诊断不得命名为模型组件消融；
- JSON 缺失数值为 `null`，CSV/Markdown 显示 `N/A`；
- 运行前后 Stage8 r5、Stage9 immutable evidence 和冻结 checkpoint 树完全不变；
- 测试结果只标记 `implemented` 或 `candidate-ready`，绝不写 `formally_verified`。

测试 fixture 的目的只是验证解析、重算和门禁逻辑。fixture 不得作为正式 Stage9/Stage10 输入，也不得进入论文结果表。

## 9. 报告边界与不能支持的论文结论

Stage11A 报告必须分成五个部分：

1. 已实现的代码、配置、schema、validator 和测试；
2. 基于 Stage8 raw counters 的 `candidate-ready` 离线结果，以及真正完成的同步 Replay 候选结果；
3. 因 Stage9 缺少真实 Linux perf/RSS/服务器证据而阻塞的 CPU latency、cycles、instructions、task-clock、RSS 和模型/管理内存结果；
4. 因 Stage10 缺少 verified Stage9 输入或异步验证而阻塞的队列压力、foreground blocking、后台利用率、并发和异步 fallback 结果；
5. 当前不能支持的论文结论。

在 Stage9/Stage10 正式门禁通过前，Stage11A 不能声称 CAPD 的真实 CPU 开销、内存开销、前台延迟、后台并发吞吐或异步系统优势。同步 weighted cost 结果只能作为同步 Replay/离线证据，不能替代真实系统测量。筛选器负向结果只能作为历史负向证据，不能加入正式方法矩阵。

## 10. 实施验收条件

进入实现阶段后，只有以下条件全部满足才可称为 Stage11A 代码完成：

- 独立 Stage11A config、result schema、runner、纯函数模块和 fixture 测试存在；
- 四组 cost profile、所有参数字段和 frozen grid digest 可复现；
- offline、sync candidate、Stage9 gate、Stage10 gate 的状态不会互相污染；
- Stage9 validator 按 Stage9 schema 和 `artifact_sha256` 工作，不强制 manifest/SHA256SUMS；
- Stage10 validator 按当前 Stage10A fixture manifest、SHA256SUMS、formal_gate 和 run_state 工作，只提供负向 `BLOCKED` 识别；Stage10B 正向契约必须另行冻结后才可扩展；
- 缺输入、缺字段和篡改输入均 fail closed；
- Stage8 r5、Stage9 failed/immutable evidence 和冻结 checkpoint 无任何文件变化；
- 报告没有把 candidate-ready 或 fixture 结果写成 formally verified；
- 本地可执行测试通过，并明确列出尚需 Linux 服务器执行的命令和阻塞条件。

本文档自审结论：没有使用统一 Stage9/Stage10 manifest 要求；没有把 Stage9/Stage10 缺失产物转成估计值；没有授权正式实验或冻结配置变更；所有结果状态和输入绑定均有明确归属。
