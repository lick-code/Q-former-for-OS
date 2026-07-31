# CAPD 主动降级 Stage 8 Linux 服务器运行说明

## 前提

在仓库 `main` 分支运行。Stage7 的 `stage7-server-suite-r1/splits/*/test.csv`、三个 Stage4 checkpoint 及 Stage4～7 权威证据必须完整存在。脚本不会重新采集 Trace、训练模型或选择参数。

脚本会自行固定 `CUBLAS_WORKSPACE_CONFIG=:4096:8` 和 `PYTHONHASHSEED=0`，并在解析 Standard Test 前执行三个 CAPD checkpoint 的 CUDA 推理烟测。不要删除或覆盖这两个环境设置。

## 唯一正式命令

```bash
cd /home/likc/Q-former-for-OS
git switch main
test "$(git branch --show-current)" = "main"

export PYTHON_BIN=python3
RUN_ID=stage8-sync-replay-r2

set -o pipefail
bash scripts/validate_capd_proactive_stage8_server.sh \
  "${RUN_ID}" cuda:0 2>&1 | tee "stage8-${RUN_ID}-console.log"
```

`RUN_ID` 只是本次验收产物目录名，不需额外配置。成功产物位于 `outputs/capd_proactive_stage8/${RUN_ID}/`。如果失败，原 run ID 会被标记 `stage8_not_verified` 并保留现场；修复代码后必须换一个新 run ID，例如 `stage8-sync-replay-r2`。

## 成功判断

必须同时满足：

- shell 返回码为 0；
- 终端最后出现唯一标记 `[FINAL] STAGE8_SYNC_REPLAY_VERIFIED`；
- `verification.json.status=stage8_sync_replay_verified`；
- `run_state.json.status=stage8_sync_replay_verified`；
- 144 个 job manifest 均为 completed，result 文件 SHA 和 semantic SHA 通过；
- 聚合 JSON/CSV/中文报告、公平性审计和 Stage1～8 测试收据齐全。

仅看到若干 `[OK]`、仅完成 preflight 或仅生成部分 job，不代表成功。

## 关键产物

- `run_identity.json`、`preflight.json`、`server_test_receipt.json`
- `runtime_smoke.json`（三个 CAPD checkpoint 的 Test 前 CUDA 烟测）
- `jobs/<job_id>/job_manifest.json`、`result.json`
- `artifacts/aggregate.json`
- `artifacts/per_workload_raw.csv`
- `artifacts/capd_vs_tpp_paired.csv`
- `artifacts/proactive_vs_reactive_paired.csv`
- `artifacts/table_A.csv`、`artifacts/table_B.csv`
- `artifacts/fairness_audit.json`
- `artifacts/report_cn.md`
- `verification.json`、`run_state.json`
