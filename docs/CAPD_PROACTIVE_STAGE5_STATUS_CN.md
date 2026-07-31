# CAPD 主动降级阶段 5 当前状态

## 当前权威状态

`stage5_baseline_framework_verified`

Linux 服务器运行 `stage5-baseline-r4` 已真实打印：

`[FINAL] STAGE5_BASELINE_FRAMEWORK_VERIFIED`

权威证据位于
`outputs/capd_proactive_stage5/stage5-baseline-r4/`。其中 verification、
run_state、fairness、合成 E2E、回归收据、28 个 Replay job 和阶段 4 checkpoint
SHA 链均已通过审计：

- 阶段 1～5 共 128 项回归测试为 `OK`；
- 三个 workload 的实验 A/B 公平性均为 `passed`；
- CAPD 三个 seed/checkpoint 独立保留；
- `test_trace_opened=false`；
- `old_finals_v3_stage_artifacts_used=false`；
- `performance_conclusion=null`；
- `tpp_inspired_status=pending_stage6`；
- `stage6_entry_gate=satisfied`。

## 文档滞后审计发现

本文件此前停留在 r3 的 `stage5_not_verified` 和“尚未满足阶段 6 门禁”，落后于 r4
权威结果。现仅更新状态说明；没有手工修改、重跑或覆盖 r4 的 verification、
run_state、fairness 或任何原始结果。r1/r2/r3 失败输出目录已在 r4 完整核验后删除，
失败原因仍保留在 Git 历史中。

源配置中的 `stage_status=stage5_implemented` 是服务器验收前的预声明合同状态，保持
不变；验收后的权威状态由 r4 verification 给出。

## 阶段 6 边界

阶段 5 合同中的 TPP-inspired 必须永久保持 `pending_stage6`，请求时抛出
`PendingStage6Error`，不得静默回退 LRU。Stage6 通过独立合同覆盖层启用
TPP-inspired，不修改阶段 5 注册表或历史证据。

## 声明边界

- DRAM 20% 是条件工程默认，不是 `capacity_rule_v2` 通过；
- 没有读取正式 Test；
- 没有选择 CAPD best seed；
- 没有复用旧 `STAGE5_VERIFIED`；
- 没有形成 CAPD 优于其他方法的结论；
- 阶段 5 完成只表示统一 baseline 框架可进入阶段 6。
