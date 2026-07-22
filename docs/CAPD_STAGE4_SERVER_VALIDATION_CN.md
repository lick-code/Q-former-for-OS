# CAPD 阶段4 Linux 服务器验收

当前状态：`STAGE4_IMPLEMENTED_UNVERIFIED`。本地未运行 Python、pytest、JSONL 生成、训练、模型推理、Trace Replay 或正式实验。

在 Linux 服务器执行：

```bash
REPO="$HOME/Q-former-for-OS"
cd "$REPO"
bash scripts/validate_capd_stage4_server.sh
```

脚本把日志、pytest cache、pycache 和临时证据写到仓库外 `mktemp` 目录；无全局 `set -e`；每组命令记录开始、结束、真实退出码和日志路径；失败不自动重试，也不删除现场。顺序为输入身份审计、阶段4针对性测试、完整 pytest、微型 E2E、三个 workload 的 JSONL 重建、9 个模型串行训练、G12、G11、汇总和污染检查。训练单进程最长 21600 秒，整体训练组最长 18 小时。

验收脚本只有在所有命令退出码均为 0 时打印：

```text
[FINAL] STAGE4_VERIFIED
```

否则打印 `[FINAL] STAGE4_NOT_VERIFIED`。审计数值不理想不是实现失败；数值边界应标为 `REVIEW_REQUIRED`。人工确认 9/9 checkpoint、三个 workload 的 G12、三 workload×三 seed 的 G11、指纹链、无 test 读取和无阶段2/3污染后，才可更新阶段状态。
