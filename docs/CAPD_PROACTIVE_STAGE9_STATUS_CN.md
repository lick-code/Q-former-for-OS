# CAPD 主动降级 Stage9 当前状态

## 当前结论

状态：`stage9_implemented_awaiting_server_measurement`

Stage8 r3 入口已在开发前检查，权威文件显示：

- `status=stage8_sync_replay_verified`
- `stage9_entry_gate=satisfied`
- 正式任务 144/144
- Test 未用于参数选择

Stage9 的代码、冻结配置、结果 schema、测试、协议、服务器脚本和输出契约已经实现。开发未重新运行、覆盖或修改 Stage8 r3 正式结果，也未训练模型、修改算法、扩展词表、处理 OOV、选择 best seed 或改变正式 `b_max=4`。

## 已具备能力

- Linux CPU-only、eval/no_grad、线程与实际 affinity 的 fail-closed 检查。
- `perf_counter_ns` exclusive 六阶段逐 round 原始样本和 Mean/P50/P95/P99。
- warmup 排除、3 次正式重复、b_t=0 安全处理、摊销和吞吐。
- b_max=1/2/4 预声明分析及 weighted cost/Early-Reuse 质量护栏。
- Stage9 正式 b_max=4 插桩轨迹与同 CPU 未插桩参考 Replay 的 Top-b/最终状态逐 job 对比；两者共同受 Stage8 r3 Trace/checkpoint/config 权威约束。
- perf FIFO 控制的真实 hardware cycles、instructions、task-clock 原始/解析产物及 cycles/round/page。
- 参数/embedding/Transformer/history/candidate/metadata/RSS 分层内存口径。
- 所有 workload/容量的 4KB 向上取整和有效 DRAM 页扣减表。
- 原子写入、失败现场、新 run ID 隔离和独立 verification。

## 尚未完成

尚未产生真实 Ubuntu CPU latency、perf cycles、OS RSS peak 和正式统计。公平容量的代表 workload Replay 复算按协议为 `deferred`；当前只实现不覆盖 Stage8 的扣减计算工具。

因此当前不允许写：

- `status=stage9_overhead_verified`
- `stage10_entry_gate=satisfied`
- `[FINAL] STAGE9_OVERHEAD_VERIFIED`

只有服务器脚本完整成功后，上述状态才由独立 verify 写入。
