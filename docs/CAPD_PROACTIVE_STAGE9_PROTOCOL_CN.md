# CAPD 主动降级 Stage9：CPU 推理与内存开销测量协议

## 1. 状态与边界

Stage9 的唯一目标是测量冻结 CAPD 的用户态 Linux CPU 同步决策开销。它不改进 Stage8 效果，不训练模型，不扩展 page/PC vocabulary，不处理 OOV，不选择 best seed，不更改 `page_enter_dram`，不执行 promotion，也不声称完成 Linux 内核集成、真实页面迁移或前台端到端加速。

权威入口固定为 `outputs/capd_proactive_stage8/stage8-dual-track-20260804-r5-post-evidence-commit/`。preflight 必须验证 Stage8 v2 的 verification、run identity、resolved config、root job manifest、run state、正式配置及 Stage4 冻结/checkpoint/model contract SHA 链，并交叉核对：

- `status=stage8_sync_replay_verified`
- `contract_id=CAPD-PROACTIVE-STAGE8-2.0`
- `formal_job_count=80`、`standard_job_count=48`、`pressure_job_count=32`
- `fairness=passed`
- `job_results_verified=true`、`statistics_verified=true`
- `test_used_for_parameter_selection=false`
- `frozen_parameters_changed=false`

Stage8 r5 目录全程只读。Stage9 preflight 在自己的新 run 目录写 `stage8_compatibility_receipt.json` 并记录 `stage9_entry_gate=satisfied`，不得向 Stage8 证据补字段。Stage9 只写 `outputs/capd_proactive_stage9/<run_id>/`。

## 2. 冻结配置

正式配置为 `b_max=2`、`K=8`、`H=20`、`L=256`、`lambda=(1,1,2)`、selector disabled、候选为当前 LRU tail、fallback 为 LRU、cost 为 `1:2:8:10`。`D/F_low/F_target/trace/checkpoint` 不使用全局默认值，逐 job 直接取自 Stage8 r5 CAPD job manifest 的 `plan_job`。三个冻结 checkpoint seed 全部参与：3136859、42、2026；禁止 best-seed 选择。

在线设备只能是 CPU；batch 是一个主动降级 round；模块必须 `eval()`，推理必须位于 `torch.no_grad()`。默认线程配置为 PyTorch intra-op 1、inter-op 1、`OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`。默认 affinity 为 CPU 0，preflight 会调用并读取 `sched_setaffinity`，请求值与实际值不一致即失败。

如果服务器 cpuset 不允许 CPU 0，只能在任何正式 run 开始前修改 Stage9 配置中的 affinity，并使用新 run ID 运行 preflight；preflight 记录修改后的配置 SHA。不得在观察测量结果后更换 affinity、线程、冻结的 20-round warmup 上限或 3 次正式重复。

测量矩阵来自 Stage8 r5 root job manifest 和 30 个 CAPD job manifest 的 `plan_job`。正式身份键为 `(track, workload, seed)`：Standard 18 个、Pressure 12 个。`b_max=1/2/4` 共 90 个质量 job；1/2/4 只用于预声明敏感性分析，正式值始终为 2。Test 不能用于参数、checkpoint 或正式 `b_max` 选择。

每个 b_max 必须为 27 个 active job 和 3 个零 round job。零 round 身份只能是 `standard|fluidanimate|3136859`、`standard|fluidanimate|42`、`standard|fluidanimate|2026`。全部 30 个 job 都保留 weighted cost 和 Early-Reuse 质量结果；延迟、摊销和吞吐只对 27 个 active job 统计。若任一 b_max 改变 27/3 或零 round 身份，整次 run fail-closed。

## 3. 延迟边界

时钟固定为单调高精度 `time.perf_counter_ns()`。一次 round 的 `total_round_latency` 从水位条件检查开始，到 Top-b 列表产生结束。六个子阶段均为 exclusive：

1. `watermark_check`：计算本 round 是否仍需恢复到 `F_target`。
2. `candidate_construction`：按当前 LRU tail 构造最多 K=8 个候选，排除当前正在进入 DRAM 的页。
3. `feature_construction`：Replay 候选状态、历史 padding/mask、CPU tensor 构造、Page/PC/RW embedding 及候选 embedding。
4. `transformer_encoding`：完整 macroscopic extractor，包括冻结 checkpoint 配置的 Transformer 与 Q-Former/pooling。
5. `candidate_scoring`：candidate scorer forward、CPU 标量转换和确定性得分排序。
6. `top_b_selection`：按 `min(b_max,F_target-F_t,|C_t|)` 取唯一 Top-b。

页迁移、Replay 状态更新、不变量检查、Early-Reuse/weighted-cost 计算和文件写入不属于总 round latency。`total` 与六项之和的真实差值写入 `unattributed_framework_overhead_ns`，绝不回填或伪造相等。

配置中的 20 是冻结 warmup 上限，不再假定每个 job 都有至少 20 个自然 round。每个 Stage9 job 先读取对应 Stage8 r5 `b_max=2` 结果中的 round 数和主动驱逐数，按当前 `b_max=1/2/4` 推导 `effective_warmup_rounds`；若观测到的自然 round 仍不足以留下测量样本，该 job 自动以少一轮 warmup 重放一次。有效 warmup 始终小于正 round job 的自然 round，零 round job 的有效 warmup 为 0。有效 warmup 标记为 `warmup`，不进入正式统计；其余每个逻辑 round 在同一状态上重复 3 次完整决策，候选顺序、ranking 和 Top-b 必须逐次相同，随后只执行一次状态迁移。原始样本保存在 `raw_latency_samples.csv`，并逐样本记录四个 warmup provenance 字段；每阶段报告 Mean/P50/P95/P99。验证器从原始 CSV 独立重算汇总。

正式 `b_max=2` 会在同一 Linux CPU 上对 30 个 job 运行未插桩参考 Replay，并与插桩 Replay 对比 Top-b 序列和最终状态 SHA，任何差异均阻断验证。参考与被测路径使用相同的 Stage8 r5 `plan_job` Trace、checkpoint 和逐 workload 控制量；不把 CUDA 与 CPU 的数值差异混入插桩审计。

## 4. 摊销与吞吐

仅对 `b_t>0` 计算：

`T_amortized = T_round / b_t`

`b_t=0` 单独计数，不参与除法。吞吐从正式样本的真实总 round 时间推导：

- `rounds_per_second = measured_rounds / total_round_seconds`
- `demoted_pages_per_second = sum(b_t) / total_round_seconds`

每个 b_max 分别保存 latency、摊销、吞吐、`b_t` 分布、weighted cost 和 Early-Reuse@64/256/1024。

## 5. CPU cycles

cycles 只能来自 Linux `perf stat` 的硬件计数器。验证脚本使用 perf FIFO control：模型加载、Trace 定位和每个 job 的 effective warmup 时计数器关闭；对 27 个 active `(track,workload,seed)` job 捕获首个 warmup 后 full-shape 决策状态，只在 200 次无状态改变的正式 `b_max=2` round 重复区间启用计数器。27 个 snapshot 的启用区间累加；另外 3 个零 round job ID 单独记录，scope 数量写入 `perf_scope_counts.json`。

perf 受控区间执行同一 stateless round，但移除 `perf_counter_ns` 调用和样本字典构造，避免把延迟插桩本身计入 cycles；候选构造、feature、模型推理、确定性排序、ranking 验证和 Top-b 均保留。原始 `perf -x ';'` 输出原样保存为 `perf/perf-stat.raw`，解析 `cycles`、`instructions`、`task-clock`、context switches、CPU migrations 和 page faults。cycles/round、cycles/page 只除以受控区间的实际 round/page 数。

服务器一键脚本会在创建 run 目录和执行昂贵 Replay 之前，实际运行一次 cycles、instructions、task-clock 硬件计数探针，并检查该 perf 版本支持 FIFO control。若 `perf_event_paranoid`、虚拟机或硬件限制导致 `<not supported>`、`<not counted>` 或权限错误，不消耗 run ID，直接要求管理员授权。正式计数若仍失败，run 必须变为 `stage9_not_verified`。cycles、instructions、task-clock 三项都必须可解析；禁止使用墙钟乘 CPU 频率估算 cycles。

## 6. 内存口径

内存同时给出三种不可混淆的证据：

- 精确 tensor/参数：`numel × element_size`，去重后统计全部参数、buffers、Page embedding、PC embedding、Transformer 参数、history/candidate 输入 tensor。
- 解析/估算：Transformer activation 为已物化输出 tensor 的下界；history packed layout 为 `20 × 24 bytes`；Python history/candidate 容器以递归 `sys.getsizeof` 估算并明确不是完整 native memory。
- OS 观测：`/proc/self/status` 的 baseline RSS 与 `getrusage(RUSAGE_SELF).ru_maxrss` peak，给出总 peak 和 Stage9 增量 peak。PyTorch native workspace、allocator cache 与碎片只由 RSS peak 覆盖；不使用 tracemalloc 冒充 PyTorch native 完整内存。

每页 metadata 采用预声明的 64 bytes/page 解析布局：residency/dirty 8、frequency 8、last access 8、DRAM entry 8、LRU links 16、alignment/reserve 16。它是目标实现的 packed 线性计费，不声称等于 Python dict 的浅层或完整大小。

`management_fixed_bytes` 包含模型参数/buffer、history packed bytes、candidate tensor 以及已物化 feature/Transformer/score activation。容量表只对 6 个唯一 workload 的冻结 D 执行；Standard/Pressure 重复 workload 仅通过 `tracks` 字段说明适用轨道，不重复计费：

`management_memory = management_fixed + dram_pages × 64`

`management_pages = ceil(management_memory / 4096)`

`CAPD effective DRAM pages = baseline DRAM pages - management_pages`

本阶段只生成扣减计算表。代表 workload 的公平容量正式 Replay 复算标记为 `deferred`，不得覆盖 Stage8 正式结果。

## 7. 状态机与验收

状态流为：

`stage9_implemented_awaiting_server_measurement → stage9_running → stage9_overhead_verified`

任何失败写成 `stage9_not_verified`，保留失败现场并永久烧毁该 run ID；禁止原地重试，必须换新 run ID。

只有以下条件全部满足，verify 才写 `stage9_overhead_verified`、`stage10_entry_gate=satisfied` 并打印唯一成功标记 `[FINAL] STAGE9_OVERHEAD_VERIFIED`：真实 Linux CPU 环境、实际 affinity/线程吻合、完整回归测试、原始延迟到汇总一致、三档 b_max 质量护栏、Stage8 正式轨迹一致、内存拆分完整、perf hardware cycles 可用、所有必需产物存在且 SHA 可复核。
