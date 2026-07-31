# CAPD 主动降级 Stage 8 当前状态

## 当前准确状态

`stage8_implemented_awaiting_formal_replay`

Stage8 的冻结配置、入口审计、正式 runner、结果 schema、Early-Reuse/OOV 指标、聚合统计、公平性审计、失败/续跑合同、单元测试和 Linux 验收脚本已经实现。本地尚未真实执行 Stage7 Standard Test 的 144 个正式 job，因此当前不能写 `stage8_sync_replay_verified`，也不能宣称 Stage8 已完成。

服务器首次正式尝试 `stage8-sync-replay-r1` 已保留为失败证据：5 个 canneal/20% 确定性 job 完成，首个 CAPD job 因未在 Python 启动前设置 CUDA cuBLAS 确定性 workspace 而失败。当前实现已将 `CUBLAS_WORKSPACE_CONFIG=:4096:8`、`PYTHONHASHSEED=0` 和三个 checkpoint 的 Test 前 CUDA 推理烟测纳入硬门禁；`r1` 不得复用，修复后须使用新 run ID。

## 已冻结内容

- 唯一调度源：Stage7 `stage8_execution_plan.json`。
- 144 个 job，无复制确定性 baseline、无 best-seed 选择。
- 表 A/表 B 成员资格及公平性合同。
- CAPD 三 checkpoint SHA、冻结 OOV/UNK=0 行为。
- TPP Stage6 最终参数。
- Early-Reuse 64/256/1024、FallbackRate 分母和零分母语义。
- bootstrap seed=20260801、10000 次、18 个 workload×capacity 单元重采样。
- 同步 Replay 解释边界。

## 已完成的本地验证

- 新 Stage8 Python 文件静态编译通过。
- Stage8 非 Test 合成统计/Early-Reuse E2E 通过。
- `tests.test_capd_proactive_stage8`：21 项通过。

本地 WSL 没有完整正式 Test split/PyTorch-CUDA 执行条件；未伪造 CAPD 推理、Test 结果、聚合报告或 verified 标记。

## 服务器完成门禁

只有 Linux 验收脚本真实完成环境检查、Stage1～8 回归、preflight、144 job、聚合和独立 verification，并打印：

`[FINAL] STAGE8_SYNC_REPLAY_VERIFIED`

之后才能将状态判断为 `stage8_sync_replay_verified`，并进入 Stage9。任何失败状态为 `stage8_not_verified`，失败 run ID 不得自动重试。
