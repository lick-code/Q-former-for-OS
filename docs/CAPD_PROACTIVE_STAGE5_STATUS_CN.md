# CAPD 主动降级阶段 5 当前状态

## 当前状态

`stage5_implemented`

统一 Replay、五个当前可运行策略、TPP-inspired 阶段 6 接口占位、两类公平性合同、事件/结果 schema、原子 job manifest、安全续跑、合成 E2E、单元测试和 Linux 验收脚本已经实现。

本地没有执行 Python/PyTorch/Replay。当前文档不宣称任何测试通过，不写
`stage5_baseline_framework_verified`，也没有产生正式 Test 或性能结论。

## `stage5-baseline-r1` 服务器现场

服务器已真实完成环境检查、CUDA 检查、阶段 5 preflight，以及阶段 4
checkpoint/Trace/dataset/freeze SHA 链校验；随后在“旧阶段 5 工件必须被拒绝”的
自测中失败：

`AssertionError: historical Stage-5 artifact was not rejected`

根因是旧工件正则只识别目录名恰好为 `stage4` 或 `stage5`，没有识别历史实际使用的
`stage5_main` 等带后缀目录。该失败发生在 Replay、CAPD 推理、回归测试和公平性审计
之前，因此 `stage5-baseline-r1` 不是已验证运行，也不包含任何性能证据。

修复后同时覆盖 `stage4/stage5` 的精确目录和 `_`、`-`、`.` 后缀目录，并为整个
Linux 验收脚本增加统一失败捕获。只要输出目录已经建立，后续任一门禁失败都会原子写入
`stage5_not_verified`、失败步骤和失败历史。`stage5-baseline-r1` 现场保留，不续跑；
修复后的验收必须使用新 run ID。

## `stage5-baseline-r2` 服务器现场

r2 已通过环境、CUDA、preflight、阶段 4 权威链和污染审计，并真实执行了阶段
1～5 的 125 项回归测试。失败集中在阶段 5 Replay 的策略到 Stage-0 运行合同适配：

- Proactive-LRU、Proactive-CLOCK 没有声明
  `stage4_training=not_applicable`；
- Reactive-LRU 继承了主动策略的 `F_low/F_target/b_max`；
- Oracle 继承了 CAPD 的 `pending_stage4` checkpoint 表示。

因此这 10 个 error 是同一适配器的三种缺失映射，不是 Replay 状态机、阶段 4
checkpoint 或 Trace 损坏。r2 已由验收脚本正确原子标记为
`stage5_not_verified`，发生在任何阶段 5 Replay、CAPD 推理、实验 A/B
和性能结论之前。

当前修复为五个可运行策略分别生成完整、可验证的 Stage-0 运行合同，并在正式回归前
增加五策略映射自检。r2 保留现场且不得续跑；下一次验收使用
`stage5-baseline-r3`。

## `stage5-baseline-r3` 服务器现场

r3 已真实完成并通过：

- 126 项阶段 1～5 回归测试，标准 unittest 结果为 `OK`；
- 含三个正式 checkpoint/seed 的 CAPD 合成 Replay；
- 合成实验 A/B；
- 三个 workload 共 21 个正式 Validation 验收 job；
- 实验 A/B 公平性审计。

r3 的 28 个 job manifest 全部为 `completed` 且结果 SHA 匹配，其中 21 个为
workload 验收、7 个为合成 E2E；不存在 TPP 伪结果或错误 checkpoint 绑定。

失败仅发生在 `record_tests`：旧代码要求整个日志文本以 `OK` 结尾，但 unittest
打印标准 `OK` 后，测试夹具又打印了三行 job/续跑信息，导致真实成功日志被误判。
该错误不影响已经完成的 Replay 或公平性结果，但按照不可自动续跑合同，r3 仍正确标记为
`stage5_not_verified`。

当前 receipt 改为同时验证测试进程退出码、标准 `Ran N tests`/`OK` 摘要和日志
SHA-256；允许标准摘要之后存在测试输出。receipt 会在回归成功后立即记录，最终
verification 会再次校验日志路径、SHA 和摘要。下一次验收使用
`stage5-baseline-r4`。

## 进入阶段 6 的门禁

当前尚未满足。必须在 Linux 服务器执行
`scripts/validate_capd_proactive_stage5_server.sh`，并真实看到：

`[FINAL] STAGE5_BASELINE_FRAMEWORK_VERIFIED`

服务器成功后，完成证据位于新 run ID 的：

- `outputs/capd_proactive_stage5/<RUN_ID>/verification.json`
- `outputs/capd_proactive_stage5/<RUN_ID>/run_state.json`
- `outputs/capd_proactive_stage5/<RUN_ID>/fairness_audit.json`
- `outputs/capd_proactive_stage5/<RUN_ID>/synthetic_e2e_receipt.json`
- `outputs/capd_proactive_stage5/<RUN_ID>/server_test_receipt.json`

TPP-inspired 在上述成功状态下仍必须是 `pending_stage6`。

## 声明边界

- DRAM 20% 是条件工程默认，不是 `capacity_rule_v2` 通过；
- 没有读取 Test；
- 没有选择 CAPD best seed；
- 没有复用旧 `STAGE5_VERIFIED`；
- 没有形成 CAPD 优于其他方法的结论；
- 没有提前实现阶段 6、7、8 或阶段 11。
