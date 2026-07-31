# CAPD 主动降级阶段 6 Linux 验收

## 一次性命令

在 Linux 服务器仓库根目录、`main` 分支执行：

```bash
cd /home/likc/Q-former-for-OS
git switch main
test "$(git branch --show-current)" = "main"

export PYTHON_BIN=python3
RUN_ID=stage6-tpp-r1

set -o pipefail
bash scripts/validate_capd_proactive_stage6_server.sh \
  "${RUN_ID}" cpu 2>&1 | tee "stage6-${RUN_ID}-console.log"
```

TPP-inspired 是确定性规则策略，不需要 GPU；`DEVICE` 参数只作为统一运行元数据保留。

## 执行内容

脚本依次执行：

1. Git、Python、环境和权威文件检查；
2. Python 编译；
3. 阶段 5 r4 verification/run_state/fairness/evidence SHA 审计；
4. 阶段 5 TPP pending 硬拒绝与 Stage6 enable 合同检查；
5. 阶段 1～6 全部回归和合成 E2E；
6. 三个 workload × 12 配置的完整冻结 Validation Replay；
7. 预声明全局规则选择唯一配置；
8. 选定配置完整 Validation 确认重跑；
9. 加入 TPP-inspired 后的实验 A 公平性审计；
10. Test、promotion、旧工件和 TPP→LRU 伪回退审计；
11. 结果/日志/job/evidence SHA 校验和最终 verification。

只有所有必要命令真实返回 0 才打印：

`[FINAL] STAGE6_TPP_INSPIRED_VERIFIED`

## 失败与续跑

run ID 是一次验收现场的唯一目录名。失败会原子写入
`outputs/capd_proactive_stage6/<RUN_ID>/run_state.json` 的
`stage6_not_verified`，保留 running/failed job，不自动重试、不覆盖结果。失败后修复
代码并使用新的 run ID。

同一未失败 run ID 只复用 job identity、结果 SHA 和代码/数据身份完全一致的
`completed` job。任何身份不同、缺失或损坏都会硬拒绝。

成功后同步整个：

`outputs/capd_proactive_stage6/<RUN_ID>/`

其中关键证据包括 `selection_decision.json`、`final_tpp_config.json`、
`confirmation_receipt.json`、`fairness_audit.json`、`server_test_receipt.json`、
`verification.json` 和 `run_state.json`。
