# CAPD Stage11A 协议

Stage11A 使用三个独立证据通道：`offline_recompute`、`sync_candidate` 和 `external_gates`。本阶段只写入 `outputs/capd_proactive_stage11/`，不修改 Stage8 r5、Stage9 failed evidence、Stage10 fixture 或冻结 checkpoint。

## Stage8 输入

唯一正式同步输入是 Stage8 r5：先读取 `artifacts/per_workload_raw.csv` 作为索引，再按 `job_id` 连接 `jobs/<job_id>/job_manifest.json` 和 `result.json`。每个 job 必须通过 `result_sha256`、`semantic_result_sha256` 和 Stage8 自身 result audit。`raw_access_count`、`reactive_demotions` 等计数直接读取 `result.json.metrics`，禁止用浮点结果反推访问数。结果行记录 `source_job_id` 和两级 SHA。

## Cost profile 与 grid

默认 Cost profile 是 `DRAM hit:NVM read:NVM write:demotion = 1:2:8:10`。敏感性 profiles 为 `1:2:4:8`、`1:2:8:10`、`1:2:12:10`、`1:2:8:20`；NVM write 表示 NVM 写访问成本，demotion 表示 DRAM 到 NVM 迁移成本。主配置 `b_max=2` 永不被敏感性 grid 覆盖。水位、`b_max=1/2/4`、working-set 容量 `20%/40%/60%`、label-weight 和 cost profile 必须在运行前显式冻结并产生 `frozen_grid_sha256`。

JSON 缺失数值使用 `null`；CSV 和 Markdown 显示 `N/A`。

## 消融边界

`CAPD-Full`、`CAPD-NoVPN`、`CAPD-NoContext`、`CAPD-NoPageState` 目前仅是 schema/interface，状态固定为 `BLOCKED`。没有重新训练或 checkpoint 选择。`Proactive-CAPD-Top-1` 与 `Proactive-CAPD-Top-b` 共享其他配置，只改变每轮选择数量，不能写成新旧 CAPD 比较。

## 外部门禁

Stage9 按自身 result schema、`required_run_artifacts`、`run_state.json`、`verification.json.artifact_sha256`、Stage8 compatibility receipt、Linux CPU/perf/RSS 证据校验，不要求根目录 `manifest.json + SHA256SUMS`。当前 `stage9-overhead-r1` 是失败且不可变证据，必须拒绝。

Stage10A 只接受自身 `manifest.json`、`SHA256SUMS`、`formal_gate.json` 和 fixture run state；完整 fixture 返回 `BLOCKED`，缺失或篡改返回 `NOT_VERIFIABLE`。Stage11A v1.0 不实现 Stage10B 正向契约，也不生成 `formally_verified`。

