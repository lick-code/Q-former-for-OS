# CAPD 主动降级 Stage9 当前状态

## 当前结论

状态：`stage9_implemented_awaiting_server_measurement`（旧 v1/r1 与 v2-r2 失败证据均保留，等待全新 v2-r3 run）

Stage8 r5 双轨入口已在开发时重新计算外层 SHA 并检查机器证据，权威文件显示：

- `status=stage8_sync_replay_verified`
- `contract_id=CAPD-PROACTIVE-STAGE8-2.0`
- 正式任务 80/80（Standard 48、Pressure 32）
- `fairness=passed`、`job_results_verified=true`、`statistics_verified=true`
- Test 未用于参数选择

Stage9 已迁移为 `CAPD-PROACTIVE-STAGE9-2.0`。开发未重新运行、覆盖或修改 Stage8 r5 正式结果，也未训练模型、修改算法、扩展词表、处理 OOV、选择 best seed 或改变正式 `b_max=2`。

旧 `stage9-overhead-r1` 的直接失败证据是 `kernel.perf_event_paranoid=4`，`perf-stderr.log` 报告 “No supported events found”；旧矩阵也没有正式延迟样本。该目录是 v1 历史失败证据，不能续跑、覆盖、导入或改写。

v2 脚本在创建 run 目录前实际探测 CPU affinity、perf FIFO 能力和 cycles/instructions/task-clock 权限。preflight 从 Stage8 r5 root/job manifests 取得 30 个 CAPD `plan_job`，Stage9 自有兼容性收据记录 80/48/32、30 个 CAPD job 及 Stage4 SHA 链。每个 b_max 强制 27 active/3 zero-round，零 round 只能是 standard fluidanimate 的三个 seed；零 round 只保留质量，不进入延迟、吞吐或 cycles 除法。每个 job 的 warmup 由 Stage8 b_max=2 round/主动驱逐证据推导，短轨迹不会被固定 20 轮 warmup 吃空。

## 已具备能力

- Linux CPU-only、eval/no_grad、线程与实际 affinity 的 fail-closed 检查。
- `perf_counter_ns` exclusive 六阶段逐 round 原始样本和 Mean/P50/P95/P99。
- warmup 排除、3 次正式重复、b_t=0 安全处理、摊销和吞吐。
- b_max=1/2/4 共 90 行预声明质量分析，并按 Standard、Pressure 和 10 个 track-workload 单元汇总。
- Stage9 正式 b_max=2 的 30 个插桩轨迹与同 CPU 未插桩参考 Replay 对比 Top-b/最终状态；逐 job 使用 Stage8 r5 `plan_job` 的 D/F_low/F_target/trace/checkpoint。
- 运行前真实 perf 权限探针；perf FIFO 控制的真实 hardware cycles、instructions、task-clock 原始/解析产物及 cycles/round/page。
- 参数/embedding/Transformer/history/candidate/metadata/RSS 分层内存口径。
- 6 个唯一 workload 冻结 D 的 4KB 向上取整和有效 DRAM 页扣减表；重复轨道不重复计费。
- 原子写入、逐 `(track,workload,seed,b_max)` checkpoint、失败现场、新 run ID 隔离和独立 verification。

## 尚未完成

尚未产生 v2 的真实 Ubuntu CPU latency、27 个 perf snapshot 的硬件 cycles、OS RSS peak 和正式统计。r1 的零样本 latency/memory 与失败 perf 不得作为 Stage9 结果。公平容量 Replay 复算按协议为 `deferred`；当前只实现不覆盖 Stage8 的扣减计算工具。

因此当前不允许写：

- `status=stage9_overhead_verified`
- `stage10_entry_gate=satisfied`
- `[FINAL] STAGE9_OVERHEAD_VERIFIED`

只有服务器脚本完整成功后，上述状态才由独立 verify 写入。

## 本地验证边界（2026-08-04）

- `python -m unittest tests.test_capd_proactive_stage8 tests.test_capd_proactive_stage9`：80 tests，全部通过。
- Stage9 定向测试可在 Windows 导入 runner；正式测量入口仍会拒绝非 Linux。
- Python AST、两个 JSON 配置、`git diff --check` 通过；Stage3/4/7/8 正式证据和旧 `stage9-overhead-r1` 无 diff。
- 全仓库 discover 在 10 分钟内未完成；fail-fast 首个错误是既有 bridge 测试无法写 `tmp/capd_bridge_plan_tests/execution_plan.json.tmp.*`（Windows `PermissionError`），不是 Stage9 断言失败。
- 本机 WSL Bash 与 Python bytecode cache 目录受 ACL 限制，因此 shell `bash -n` 和 `py_compile` 未取得成功证据；Ubuntu 脚本会在正式测量前执行真实静态编译。
