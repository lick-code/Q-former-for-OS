# CAPD Stage10 v2-r2 Task 0–9 实施验证报告

## Material Passport

- 类型：Stage10 v2-r2 实施与生成冻结候选
- 状态：`TASKS_0_9_VERIFIED_FREEZE_APPROVAL_PENDING`
- 授权范围：Tasks 0–9
- 下一门禁：精确 freeze-receipt SHA 审批

## 1. 审批和边界

本轮绑定 approved design SHA `e967307c7cc9c3548424c646ca2c442c01ef738da0995fbda9037044567f3cc2` 和 approved implementation-plan SHA `3ed8f1760c1a9f93f06c1d6c9897485b2169be88844f63b0183bdca2351bee23`。初始 Tasks 0–9 完成后，用户曾批准旧 freeze receipt SHA 并单独授权 Task 10；该次 Task 10 在创建正式目录前的 controlled generation preflight 失败。本次授权仅用于修复该根因并重新完成 Tasks 8–9 freeze candidate。

未创建 `stage10-async-simulator-v2-r2` 正式运行目录，未执行正式 60 场景仿真，未生成 readiness/final-status release evidence，未解锁 Stage11，未 commit 或 push。正式指标为 `N/A`，`generation_verified=false`，`real_system_async_performance_verified=false`。旧 freeze receipt SHA `4ee1e17360ae147039fd429d67ffea30ac842cba13102725d654403a710c71dd` 已被本次源代码、source manifest、config 和 receipt 更新永久取代，不能继续授权 Task 10。

## 2. 已实现合同

- r2 使用 `CAPD-PROACTIVE-STAGE10-2.0`、`deterministic_async_simulation` 和 v2.1 metadata envelope。
- generation source manifest 校验完整本地依赖闭包、规范路径、文件 SHA、静态导入和实际模块加载，且禁止 Stage11 进入 generation identity。
- config 完整绑定旧 v2 仿真语义、approved design/plan、source manifest、14 个 metadata schema、受控执行和 release contract。
- 正式 runner、dispatcher、native verifier 和 release 入口均要求外部 `--approved-freeze-receipt-sha256`。
- freeze receipt 由当前仓库独立构造完整预期对象，绑定 design、plan、config、source manifest、result/metadata schemas、命令、71 个有序测试身份、protocol、release module、环境合同、Stage9 authority 和创建时授权状态。
- generation/release 测试由受控 runner 执行并保存前后源码快照、环境、timeout、命令、测试身份和结果。
- Stage11A 负向审计移至 readiness，冻结精确结果三元组和独立依赖快照；Stage11 不进入 generation source set。
- r1 保留为 `candidate_evidence`，r2、r1 和 Stage10A 严格版本隔离。

实施末期自审发现仅比较外部 receipt 文件 SHA、但未重构 receipt 内部完整绑定的缺口。已在冻结前修复：production run、r2 verifier、release verifier 和 Stage11 audit worker 都会重算完整 receipt；新增测试证明把创建时授权字段篡改为 `true` 后，即使形成新的合法 JSON 文件也会失败关闭。

首次 Task 10 controlled generation preflight 还暴露了测试身份解析不一致：Python verbose unittest 日志使用 `test_name (tests.module.Class.test_name)`，旧解析器保留整段显示标签，而 freeze receipt 保存规范化的 `tests.module.Class.test_name`，因此 runner 正确停止并报告 `Controlled generation test identities differ from the freeze.`。修复后的解析器只提取括号内规范测试 ID，并忽略 `setUpClass` 等非测试诊断行；新增回归测试固定该行为。该修复不改变 Stage9 输入、60 场景矩阵、仿真参数或结果语义。

## 3. Generation source freeze

- source set：`stage10-v2-r2-generation-core-v1`
- entry count：11
- Stage11 dependency count：0
- source manifest SHA256：`5b7c2e78d9e0823235b398460ecdb72834ceb05329807051c6ec3b6513917858`
- source fingerprint SHA256：`c857374350d45fec7ed90af99fdfe4bf1689973e2435b70f26133634cde92d25`
- r2 config SHA256：`bdeebdd2ff3e5e7416171832058074b068ebfa6c851dd9ced7653d36755c376f`
- r2 config canonical SHA256：`11c40dfc8038d7b008e68e5eba76216c8897b972f4579621d6698d4d8864182f`
- freeze receipt SHA256：`3f4ce4ff71006777e18ded8d6b2e453c679b4a3d3ba2723d5892d7e310ac61f2`

freeze receipt 不包含自身 SHA，且保存：

```text
formal_run_authorized_at_receipt_creation=false
release_authorized_at_receipt_creation=false
stage11_positive_migration_authorized_at_receipt_creation=false
```

## 4. 测试和机械验证

完整 generation 命令：

```powershell
python -m unittest -v tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage10_v2 tests.test_capd_proactive_stage10_v2_r2
```

修复先以新增解析器测试复现失败，再修改实现；目标测试随后通过。完整受控 generation preflight 结果为 `Ran 71 tests`，0 skipped，最终 `OK`。71 个规范化 test identity 的顺序与 config 和 freeze receipt 完全一致，并记录：

```text
exit_code=0
timed_out=false
attempt_count=1
automatic_retry_performed=false
source_snapshots_equal=true
log_sha256=4862452beb1be97b2aeb6d354374d3c87234a160a78f9af4d1709d14f4fcd143
```

readiness 文档测试单独执行 1 项并通过。final-status 文档测试没有执行，因为它要求未来 readiness completion decision 和最终状态更新，属于未授权的 Tasks 11–12。release lifecycle、12-file readiness、8-file final-status、timeout、篡改和精确 Stage11 三元组均使用临时目录完成单元测试，没有创建生产 release evidence。

新增/修改的 r2 Python 文件均通过源码 `compile()` 检查。JSON 文件可严格 UTF-8 解析，receipt 现场重构与保存对象完整相等。

## 5. 上游和历史证据复核

- Stage9 r3：`verification.json.artifact_sha256` 19/19 复算匹配；checkpoint 为 `completed`，quality rows 90，instrumentation rows 30。
- Stage10A：独立 verifier 返回 `status=verified`、5 条结果和 12 个 manifest payload。
- v2-r1 dispatcher：退出码 1，`Run identity does not match the complete independently constructed object.`
- v2-r1 native verifier：退出码 1，同一 identity mismatch；r1 未被升级。
- Stage11A 当前 Stage10A 三元组：`BLOCKED / stage10a_fixture_only / false`。
- r2-shaped 临时输入测试三元组：`NOT_VERIFIABLE / invalid_stage10a_fixture / false`。
- 当前生产 r2 路径不存在时，Stage11A 正确返回 `NOT_VERIFIABLE / missing_stage10a_fixture / false`；这不是 readiness 的未来 r2 输入，也不被改写成已存在状态。

## 6. 冻结目录审计

Task 9 对每个文件重新读取字节并比较规范相对路径、长度和 SHA256。四棵树与 Task 0 baseline 的文件集合完全一致，0 missing、0 changed、0 extra：

| 冻结目录 | 文件数 | Task 0 fingerprint | Task 9 |
| --- | ---: | --- | --- |
| Stage8 r5 | 181 | `cedb6bc7ad51820cdccde0b8713c06e779c78fd0f2826f311e61a64b50ac2d73` | unchanged |
| Stage9 r3 | 31 | `19ee15fbf3966152332b56f3bcf130e86f2ff979db01383c51d6b2f3cfa12c74` | unchanged |
| Stage10A r1 | 14 | `ab712f91eab507add25ea0dff64703a1009fa412a9fa7867bc0558aea48a3913` | unchanged |
| Stage10 v2-r1 | 16 | `d928af7938c0f2ed2d2e6b9af9e5f00943181b0fa88a964bd2711d08af5859fe` | unchanged |

Task 0 baseline snapshot SHA256 为 `463744227aef96372972b07c60558d0945c9442f4e48c95924831871aebe14f0`。

## 7. 当前结论

Tasks 0–9 的小范围修复已实现并通过本地验证，替代 freeze candidate 已生成。精确待审批 SHA 为：

```text
3f4ce4ff71006777e18ded8d6b2e453c679b4a3d3ba2723d5892d7e310ac61f2
```

必须停在此门禁等待用户明确批准该 SHA。该批准本身仍不自动授权 Task 10；正式 60 场景仿真、release evidence 和 Stage11 正向迁移均需要后续独立批准。
