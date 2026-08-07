# CAPD Stage10 v2 确定性异步仿真协议

## 合同身份

- contract：`CAPD-PROACTIVE-STAGE10-2.0`
- evidence mode：`deterministic_async_simulation`
- 仿真验证成功状态名：`stage10_async_simulation_verified`
- 预留正式 run id：`stage10-async-simulator-v2-r1`

该成功状态只表示绑定输入、事件流、离散事件模型、结果产物和独立重算均通过验证。它不表示真实 NVM 测量、真实内核并发、真实前台端到端延迟或真实系统异步性能已经验证。

## Stage9 输入门禁

v2 只接受 `stage9-overhead-v2-r3`。门禁读取 Stage9 自有的 `run_state.json`、`verification.json`、`artifact_sha256`、result schema、`measurement_checkpoint.json` 和 Stage8 compatibility receipt，不要求 Stage9 根目录虚构 `manifest.json` 或 `SHA256SUMS`。

门禁逐项复算 19 个 Stage9 artifact SHA，并单独绑定 Stage9 config、result schema、verification、run state、measurement checkpoint、latency summary、run identity 和字节恢复审计。缺失、路径逃逸、符号链接、旧 run id、状态错误、换行字节变化或调用方自报 receipt 均失败关闭。

## Timing provenance

`T_inference_ns` 从 Stage9 r3 的 `latency_summary.json` 派生，字段为 `by_b_max["2"].stages.total_round_latency_ns`。JSON 小数使用 Decimal 解析，整数转换规则为 `ROUND_HALF_UP`。主 reference 使用 mean；p50、p95、p99 只作为预声明 sensitivity。

`T_migration_ns` 是相对于 mean inference 的 `0.01/0.10/1.00` 模拟参数。`migration-ratio-0p10` 只是 reference simulator scenario，不是典型值、最优值或硬件标定值。Cost profile 的 demotion 权重 10 不参与纳秒推导。

## 60 条双通道场景

六个 timing profiles、五个 arrival profiles 和两个 comparison channels 构成固定的 60 条场景。

- `fixed_arrival`：每个 arrival profile 仅用 reference timing 生成一次 `(timestamp_ns,page_id)` 流，六个 timing profiles 完全复用。它只支持冻结仿真模型内的 timing sensitivity。
- `capacity_normalized`：每个 timing profile 按自身 `mu_demote` 生成流，只报告相对容量压力曲线，不允许作纯 timing 因果解释。

每条结果保存 exact-rational absolute arrival rate、normalized load ratio、arrival reference、canonical stream SHA 和跨 profile 比较权限。Uniform 与 burst 均保留基础流；burst 区间为分段 rate object。

## 事件与结果边界

v2 复用已有测试覆盖的整数纳秒事件引擎，包括事件优先级、`reserved_page_ids` 互斥、容量不变量、LRU tail、MRU admission、FIFO blocking、emergency fallback 和 `F_t=0` 时间积分。无完成阻塞样本时 JSON mean/p95 为 `null`，报告为 `N/A`。

结果 schema 强制声明：真实 NVM、真实内核并发、真实前台端到端延迟和真实系统异步性能均未验证。`stage10_async_simulation_verified` 不能被改写为真实系统 formally verified。

## 版本隔离

Stage10A fixture 继续使用 `CAPD-PROACTIVE-STAGE10-1.0`，v1/v2 verifier 双向拒绝。Stage11A 当前仍是 fixture-only 负向门禁；它必须对 v2 返回 `NOT_VERIFIABLE`，不得获得正向迁移。Stage11A 正向支持需要独立设计和新合同。

## 产物与不可变性

正式 v2 run 只能在单独获得 Task 10 批准后创建。runner 在所有 preflight 通过前不得创建目录；创建后失败则保留 `stage10_async_simulation_not_verified`，同一 run id 不得续写或覆盖。Manifest 排除自身和 `SHA256SUMS`，后者包含 manifest 并排除自身；verifier 拒绝任何额外或缺失文件。
