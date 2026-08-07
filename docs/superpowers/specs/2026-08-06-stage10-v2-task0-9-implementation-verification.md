# CAPD Stage10 v2 Task 0–9 实施验证报告

**Status:** Task 0–9 implemented and locally verified; Task 10 formal simulation is not authorized and has not been executed.

## 1. 审批和证据边界

本轮只执行获批实施计划的 Task 0–9。未运行正式 60 场景命令，未创建 `outputs/capd_proactive_stage10/stage10-async-simulator-v2-r1/`，未产生可作为正式证据的 `stage10_async_simulation_verified` run，未修改 Stage11A 正向门禁，未 commit 或 push。

绑定的 approved design SHA 为 `2cdd4a647de2d0441b2ae70e476f61ec6cd4488f2d5669337e6de8723b76aebd`；recovery audit SHA 为 `94a68bfccfa6fec3a947b6ed35f83cca04a09bfe708b9390385d7476e0c5bc64`。实施前后两文件 SHA 均未变化。

## 2. 已实现文件

新增：

- `configs/finals/capd_proactive_stage10_v2.json`
- `configs/finals/capd_proactive_stage10_result_schema_v2.json`
- `qmap/proactive_stage10_v2.py`
- `scripts/run_capd_proactive_stage10_v2.py`
- `tests/test_capd_proactive_stage10_v2.py`
- `tests/stage10_v2_test_support.py`
- `docs/CAPD_PROACTIVE_STAGE10_V2_PROTOCOL_CN.md`
- `docs/CAPD_PROACTIVE_STAGE10_V2_STATUS_CN.md`

扩展：

- `scripts/run_capd_proactive_stage10.py`：保留原 v1 verifier 行为并增加按 `config.json.contract_id` 的严格 v1/v2 分派。

保持不变：

- `qmap/proactive_stage10.py` 事件引擎；
- Stage10A config、schema、测试和历史输出；
- Stage11A 设计、配置、源码、测试和输出；
- Stage8/Stage9 测量及其验证状态。

## 3. 合同实现

v2 config 绑定 `CAPD-PROACTIVE-STAGE10-2.0`、`deterministic_async_simulation`、固定 run id、approved design、recovery audit、Stage9 r3 全部权威 SHA 和 v2 result schema SHA。模块再次固定 Stage9 config、schema、verification、run state、checkpoint、latency、run identity 和 Stage8 receipt 摘要，旧 config SHA 或调用方替换失败关闭。

Stage9 只读门禁使用其真实 result schema 和 19-key `verification.json.artifact_sha256`，不要求根目录 manifest/SHA256SUMS。门禁验证路径 containment、直接子目录身份、符号链接、run state、verification、resolved config、run identity、Stage8 receipt、Linux environment、preflight、perf、RSS、server regression、capacity CSV 和 measurement checkpoint。Checkpoint 使用完整 `(track,workload,seed,b_max)` 身份集合比较 90 个 quality cells 与 30 个 formal instrumentation cells。

Timing 使用 Decimal parser 和 `ROUND_HALF_UP`，得到 mean/p50/p95/p99 inference 以及三档 migration scenario。60 条矩阵严格拆分 `fixed_arrival` 和 `capacity_normalized`；到达率、normalized ratio 使用不可约 Fraction，fixed-arrival 六个 timing profiles 复用相同 timestamp、page ID 和 stream SHA。

v2 wrapper 只复用已覆盖测试的 v1 事件引擎，重写 result identity 和 interpretation。所有结果均明确否定真实 NVM、真实内核并发、真实前台端到端延迟和真实系统异步性能结论。

Runner 在 mkdir 前完成 config/design/schema/Stage9/test-log preflight，拒绝 run id 和输出根覆盖。临时 synthetic 成功路径写 16 个精确 artifacts，verifier 独立重算 Stage9 gate、timing、arrival streams、60-row matrix、每条仿真结果、test evidence、run identity、manifest 和 SHA256SUMS。Synthetic API 被限制在其外部临时 project root，不能指向仓库生产输出。

## 4. TDD 和回归结果

最终命令：

```powershell
python -m unittest tests.test_capd_proactive_stage10 tests.test_capd_proactive_stage10_v2 tests.test_capd_proactive_stage11 -v
```

结果：`Ran 74 tests`，最终状态 `OK`。

- Stage10A：30 项回归通过；独立 verifier 返回 5 条结果和 12 个 manifest payload。
- Stage10 v2：22 项测试通过，包含真实 Stage9 r3 只读正向集成、compact synthetic 负向篡改、Decimal timing、60-row 双通道、临时 runner、完整 metadata 独立重算和版本分派。
- Stage11A：22 项回归通过；完整 Stage10A fixture 仍为 `BLOCKED / stage10a_fixture_only`，v2 输入仍为 `NOT_VERIFIABLE`。
- 新增和修改的五个 Python 文件均通过源码 `compile()` 检查。

## 5. Stage9 和冻结目录审计

Stage9 r3 `artifact_sha256` 现场复算：19/19 匹配，0 缺失，0 mismatch。

| 冻结目录 | 文件数 | Task 0 tree SHA256 | Task 9 tree SHA256 | 结果 |
| --- | ---: | --- | --- | --- |
| Stage8 r5 | 181 | `e3f5a84ec3ba5884669a4c30f017cdbdef5b202f166f39fe545b6dfea05157bb` | `e3f5a84ec3ba5884669a4c30f017cdbdef5b202f166f39fe545b6dfea05157bb` | unchanged |
| Stage9 r3 | 31 | `3e05c00e5c157305d8d677188aa2acf18f0de63515d484fcafac3d88b939821d` | `3e05c00e5c157305d8d677188aa2acf18f0de63515d484fcafac3d88b939821d` | unchanged |
| Stage10A r1 | 14 | `9eb55b40a2453c9a3dfadbc1a2cc64a76e14fc386882dd501ded5ce1a6885401` | `9eb55b40a2453c9a3dfadbc1a2cc64a76e14fc386882dd501ded5ce1a6885401` | unchanged |

树指纹由每个文件的相对路径、长度和 SHA256 排序后形成 UTF-8 ledger，再计算 SHA256。

## 6. 实施期异常记录

在为 synthetic API 增加“禁止生产输出”负向测试时，guard 尚未实现，测试进入了预计算路径并短暂创建了生产目标的空目录。该测试被立即终止；现场检查确认目录为空、没有生成任何文件或结果。随后仅删除该空目录、加入生产输出 guard，并新增回归测试。最终审计确认目标目录不存在，Stage8/Stage9/Stage10A 树指纹均未变化。

## 7. 正式 verifier P1 复审修复

复审指出生产 config 只校验 arrival ID，以及 verifier 只比较部分 metadata 字段。修复采用以下 fail-closed 约束：

- `load_repository_config()` 绑定仓库 config 文件 SHA256 `0308139288c895cc98e3f96ee7dff25856a9334e48bf8aa226eb88f03a7e326c`；
- `validate_config()` 绑定完整 canonical config SHA256 `6bff8f92b70b6d2372dd6b480fb9e7fd2c1eab75fad6da39152db14dd6ab26e9`，因此 uniform ratio、burst interval/multiplier、timing source、output root 或任意其他字段变化均拒绝；
- synthetic verifier 只允许改变测试 horizon 和对应 burst 的 start/duration，替换 uniform ratio、burst multiplier 或其他正式字段仍拒绝；
- runner 和 verifier 共用纯构造函数生成完整 `run_identity.json`、`verification.json` 和 `run_state.json` 预期对象；verifier 不再只检查字段子集；
- 新增回归测试分别篡改 config、schema、design、Stage9、timing、test evidence SHA，以及 verification/state 身份和执行字段；即使攻击者重算 run identity self-hash、manifest 和 `SHA256SUMS`，验证仍失败。

## 8. 当前结论

Task 0–9 已实现并通过本地验证，未发现阻止申请 Task 10 单独审批的 P1/P2 实现问题。

正式 Stage10 v2 结果仍为 `N/A`。只有 Task 10 获得明确批准、正式 60 场景 run 被创建并由两个 verifier 独立复算通过后，才能报告 `stage10_async_simulation_verified`；该状态仍不能解释为真实系统异步性能验证。
