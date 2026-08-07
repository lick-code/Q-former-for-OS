# CAPD Stage10 v2-r2 生成身份与发布协议

## 合同边界

- 合同：`CAPD-PROACTIVE-STAGE10-2.0`
- evidence mode：`deterministic_async_simulation`
- run id：`stage10-async-simulator-v2-r2`
- generation 成功状态：`stage10_async_simulation_verified`
- 真实系统异步性能：`real_system_async_performance_verified=false`

该合同验证的是确定性离散事件仿真，不是真实 NVM、真实内核并发或真实前台端到端性能测量。`stage10_async_simulation_verified` 只能在正式运行、双 generation verifier、readiness verifier 和 final-status verifier 全部通过后对外使用。

## r1 与 r2

`stage10-async-simulator-v2-r1` 永久保留为 `candidate_evidence`。其 60 条仿真结果已生成，但当前源码下的独立身份复验失败，原因是 generation identity 绑定了运行后会变化的测试文件。不得修改、覆盖、续写或升级 r1。

r2 保持 Stage9 输入、60 场景矩阵、事件语义、arrival channel 和解释边界不变，只升级 generation/source/release 证据封装。r2 与 Stage10A、v2-r1 双向不兼容。

## 外部冻结锚

正式 r2 runner、dispatcher、native verifier、readiness 和 final-status 入口必须由调用方提供：

```text
--approved-freeze-receipt-sha256 <exact-lowercase-64-hex-sha256>
```

该值必须与仓库固定路径下的 generation freeze receipt 现场 SHA 完全一致；已有 run 还必须验证 run copy 字节完全相同。产物中的自报字段不能代替外部参数。receipt 缺失、改变、未获批准或 SHA 不匹配时 fail closed。

## Generation identity

generation source manifest 保存完整核心运行与测试依赖闭包的规范路径和 SHA256。verifier 同时检查路径安全、entry 排序和唯一性、静态导入闭包、受控执行期间的本地模块加载集合及当前文件 SHA。generation source set 不得静态、动态或传递依赖任何 Stage11 模块。

运行前 generation tests 由 runner 使用当前 Python 解释器执行，测试前后重算完整 source snapshot，并验证固定命令、测试数、verbose test identity、退出码和最终 `OK`。调用方日志不能授权运行。

## 受控执行与环境

冻结超时如下：generation test 与正式仿真各 1800 秒，readiness、Stage11 负向审计和 final-status 各 600 秒；监控间隔 30 秒，终止宽限 10 秒，禁止自动重试。每次 evidence 记录 Python 版本、implementation、cache tag、解释器路径、OS、architecture 和依赖策略。墙钟耗时仅用于运行观察，不参与确定性结果相等，也不作为性能结论。

## Stage9 与仿真语义

Stage9 输入只接受 `stage9-overhead-v2-r3`，并按其 `verification.json.artifact_sha256` 对 19 个 artifact 逐项复算；不要求 Stage9 根目录存在 manifest 或 `SHA256SUMS`。`T_inference_ns` 从 formal `b_max=2` latency summary 按 Decimal `ROUND_HALF_UP` 派生。`T_migration_ns` 的三档 ratio 均为未做硬件标定的 simulator scenario parameter。

60 条场景继续由 6 个 timing profile、5 个 arrival profile 和 2 个 channel 构成。`fixed_arrival` 复用完全相同的 arrival stream，只支持仿真模型内 timing sensitivity；`capacity_normalized` 只支持相对容量压力解释。

## 两阶段 release

正式 generation run 通过不等于 Stage10 对外完成。发布顺序固定为：

```text
generation_verified
-> release_pending
-> readiness tests and independent Stage11A negative audit
-> completion_decision=approved_for_status_finalization
-> update official status
-> post-decision documentation test
-> final-status evidence seal
```

readiness 独立封存 Stage11A 对 Stage10A 的 `BLOCKED / stage10a_fixture_only / false` 和对 r2 的 `NOT_VERIFIABLE / invalid_stage10a_fixture / false`。Stage11 源码只属于该历史审计快照，后续 Stage11 合法变化仅记为 informational drift，不反向破坏 generation identity。Stage11 正向迁移仍需单独设计和批准。

当前 Task 0–9 阶段尚未执行正式 r2 仿真，`generation_verified=false`，`release_pending=true`。不得创建或宣称正式成功结果。
