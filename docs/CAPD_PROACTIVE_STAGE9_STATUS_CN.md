# CAPD 主动降级 Stage9 当前状态

## 当前结论

状态：`stage9_implemented_awaiting_server_measurement`（r1 失败证据已保留，等待全新 r2）

Stage8 r3 入口已在开发前检查，权威文件显示：

- `status=stage8_sync_replay_verified`
- `stage9_entry_gate=satisfied`
- 正式任务 144/144
- Test 未用于参数选择

Stage9 的代码、冻结配置、结果 schema、测试、协议、服务器脚本和输出契约已经实现。开发未重新运行、覆盖或修改 Stage8 r3 正式结果，也未训练模型、修改算法、扩展词表、处理 OOV、选择 best seed 或改变正式 `b_max=4`。

服务器 r1 的直接失败证据是 `kernel.perf_event_paranoid=4`，`perf-stderr.log` 报告 “No supported events found”。进一步审计发现 r1 的 `raw_latency_samples.csv` 只有 333-byte 表头，三个 b_max 的正式样本数均为 0；根因是旧 Stage9 配置误用了 0.40 容量，而 Stage7 在 Test 前冻结的 `default_ratio`/`is_main_default` 是 0.20。r1 因此不仅缺 perf cycles，延迟结果也无效，不能续跑或复用。

修复后，服务器脚本在创建 run 目录前实际探测 CPU affinity、perf FIFO 能力和 cycles/instructions/task-clock 权限；测量改用 Stage7 预冻结主默认 0.20 容量，并强制 9 个有效 round 单元、9 个零 round 单元及其 workload 身份。空延迟样本会在发布 summary 前 fail-closed，零 round 单元仅保留质量，不进入延迟或 perf 除法。

## 已具备能力

- Linux CPU-only、eval/no_grad、线程与实际 affinity 的 fail-closed 检查。
- `perf_counter_ns` exclusive 六阶段逐 round 原始样本和 Mean/P50/P95/P99。
- warmup 排除、3 次正式重复、b_t=0 安全处理、摊销和吞吐。
- b_max=1/2/4 预声明分析及 weighted cost/Early-Reuse 质量护栏。
- Stage9 正式 b_max=4 插桩轨迹与同 CPU 未插桩参考 Replay 的 Top-b/最终状态逐 job 对比；两者共同受 Stage8 r3 Trace/checkpoint/config 权威约束。
- 运行前真实 perf 权限探针；perf FIFO 控制的真实 hardware cycles、instructions、task-clock 原始/解析产物及 cycles/round/page。
- 参数/embedding/Transformer/history/candidate/metadata/RSS 分层内存口径。
- 所有 workload/容量的 4KB 向上取整和有效 DRAM 页扣减表。
- 原子写入、失败现场、新 run ID 隔离和独立 verification。

## 尚未完成

尚未产生修复后 0.20 主默认容量的真实 Ubuntu CPU latency、perf cycles、OS RSS peak 和正式统计。r1 的零样本 latency/memory 与失败 perf 不得作为 Stage9 结果。公平容量的代表 workload Replay 复算按协议为 `deferred`；当前只实现不覆盖 Stage8 的扣减计算工具。

因此当前不允许写：

- `status=stage9_overhead_verified`
- `stage10_entry_gate=satisfied`
- `[FINAL] STAGE9_OVERHEAD_VERIFIED`

只有服务器脚本完整成功后，上述状态才由独立 verify 写入。
