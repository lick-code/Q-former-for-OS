# CAPD 阶段4 Linux 服务器验收

当前状态：`STAGE4_VERIFIED`。2026-07-23 Linux服务器已完成正式验收；本地仅核对同步工件和更新状态，未运行 Python、pytest、JSONL 生成、训练、模型推理、Trace Replay 或正式实验。

在 Linux 服务器执行：

```bash
REPO="$HOME/Q-former-for-OS"
cd "$REPO"
bash scripts/validate_capd_stage4_server.sh
```

G11 默认使用3个spawn进程并发；每个workload/seed使用全新进程，完成后立即退出，避免PyTorch原生状态和大trace内存跨任务累积。worker先完成train分布并释放train trace，再加载valid trace。实时打印trace加载、LRU分布、CAPD闭环回放、分布统计、每500个闭环决策以及每个workload/seed的完成进度，最长3小时；每个完成组合独立原子落盘，超时或断线后可续跑。连续特征统计只对每列排序一次，再线性计算KS、Wasserstein-1和越界比例，禁止在分位点或样本循环内重复排序、重复扫描参考分布。可通过 `CAPD_STAGE4_DISTRIBUTION_WORKERS` 调整并行度；正式验收建议保持3。

只重跑G11并生成汇总时使用：

```bash
cd "$REPO"
CAPD_STAGE4_DISTRIBUTION_WORKERS=3 timeout 3h python3 scripts/run_capd_stage4.py \
  --stage distribution-audit --repo-root "$REPO" \
  --distribution-workers 3 --device cuda
python3 scripts/run_capd_stage4.py --stage summarize --repo-root "$REPO"
```

脚本把日志、pytest cache、pycache 和临时证据写到仓库外 `mktemp` 目录；无全局 `set -e`；每组命令记录开始、结束、真实退出码和日志路径；失败不自动重试，也不删除现场。任一必需阶段失败后立即停止依赖阶段，并把失败日志最后 80 行直接打印到终端，避免生成级联失败噪声或隐藏首个 traceback。顺序为输入身份审计、阶段4针对性测试、完整 pytest、微型 E2E、三个 workload 的 JSONL 重建、9 个模型串行训练、G12、G11、汇总和污染检查。训练单进程最长 21600 秒，整体训练组最长 18 小时。输入审计可安全刷新；完整且身份一致的 checkpoint 可复用；上次失败留下的空 checkpoint 目录可直接续跑。

验收脚本只有在所有命令退出码均为 0 时打印：

```text
[FINAL] STAGE4_VERIFIED
```

否则打印 `[FINAL] STAGE4_NOT_VERIFIED`。审计数值不理想不是实现失败；数值边界应标为 `REVIEW_REQUIRED`。人工确认 9/9 checkpoint、三个 workload 的 G12、三 workload×三 seed 的 G11、指纹链、无 test 读取和无阶段2/3污染后，才可更新阶段状态。

## 2026-07-23服务器验收回填

服务器证据目录：`/tmp/capd-stage4.pDQyrs`。

- `input_audit`、`targeted_tests`、`full_pytest`、`mini_e2e`、`generate`、
  `train_9`、`counterfactual_g12`、`distribution_g11`、`summarize`、
  `pollution_check`、`diff_check`均退出0。
- `train_9`复用9/9完整且身份一致的checkpoint。
- G11计划为 `jobs=9 workers=3 reused=9 pending=0 device=cuda`。
- 验收脚本最终打印 `[FINAL] STAGE4_VERIFIED`。
- 本次截图未给出pytest的精确passed/collected数量，报告只记录真实退出码，
  不臆造测试数量。
