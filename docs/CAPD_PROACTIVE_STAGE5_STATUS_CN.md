# CAPD 主动降级阶段 5 当前状态

## 当前状态

`stage5_implemented`

统一 Replay、五个当前可运行策略、TPP-inspired 阶段 6 接口占位、两类公平性合同、事件/结果 schema、原子 job manifest、安全续跑、合成 E2E、单元测试和 Linux 验收脚本已经实现。

本地没有执行 Python/PyTorch/Replay。当前文档不宣称任何测试通过，不写
`stage5_baseline_framework_verified`，也没有产生正式 Test 或性能结论。

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

