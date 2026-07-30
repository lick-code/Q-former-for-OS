# CAPD 主动降级阶段 5 Linux 服务器运行说明

## 前置条件

1. 当前分支必须为 `main`；
2. 阶段 4 `stage4-f8-f16-r3` 正式目录和三个 `.pth` 已同步；
3. 阶段 4 Train/Validation 原始 Trace 位于当前仓库 `dataset/...` 的冻结相对位置；
4. Python 环境能导入项目所需 PyTorch；
5. 不要使用已经有 failed/running job 的 run ID；失败后保留现场并换新 run ID。

## 一键验收

CPU：

```bash
cd /home/likc/Q-former-for-OS
export PYTHON_BIN=python3
bash scripts/validate_capd_proactive_stage5_server.sh stage5-baseline-r4 cpu
```

CUDA：

```bash
cd /home/likc/Q-former-for-OS
export PYTHON_BIN=python3
bash scripts/validate_capd_proactive_stage5_server.sh stage5-baseline-r4 cuda:0
```

脚本依次执行：

1. main 分支、Python、PyTorch/CUDA 和冻结输入检查；
2. 新代码 `py_compile`；
3. 阶段 4 verification/freeze/checkpoint SHA 链审计；
4. selector、20% 容量声明、旧 finals_v3 Stage4/5、Test、TPP fallback 污染检查；
5. 阶段 1～5回归测试并保存原始日志；
6. 含真实三个 CAPD checkpoint 推理的小型合成实验 A/B；
7. 每个 workload 的预声明 Validation 4096-access 框架验收 Replay；
8. 实验 A/B 公平性审计；
9. 记录测试 receipt；
10. 最终 verification。

仅当前面所有命令都真实返回 0 时，最后打印：

```text
[FINAL] STAGE5_BASELINE_FRAMEWORK_VERIFIED
```

## 分步排障

```bash
python3 scripts/run_capd_proactive_stage5.py preflight \
  --run-id stage5-debug-r1 --project-root "$PWD" --device cpu

python3 -m unittest -v \
  tests.test_capd_proactive_config \
  tests.test_capd_proactive_replay \
  tests.test_capd_proactive_cost \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  tests.test_capd_proactive_stage5_contract \
  tests.test_capd_proactive_stage5_replay \
  tests.test_capd_proactive_stage5_e2e

python3 scripts/run_capd_proactive_stage5.py synthetic \
  --run-id stage5-debug-r1 --project-root "$PWD" --device cpu

python3 scripts/run_capd_proactive_stage5.py run-acceptance \
  --run-id stage5-debug-r1 --project-root "$PWD" --device cpu

python3 scripts/run_capd_proactive_stage5.py fairness \
  --run-id stage5-debug-r1 --project-root "$PWD" --device cpu
```

分步命令不会自动重试 failed job。`verify` 之前仍需把真实回归日志和测试进程退出码
通过 `record-tests --test-log <path> --test-exit-code 0` 记录。

## 失败处理

- 验收脚本失败：若 run 目录已经建立，脚本会原子记录
  `status=stage5_not_verified`、`failure_step` 和 `failure_history`；
- checkpoint/Trace SHA 失败：不要改冻结 JSON；先修复服务器文件同步；
- 绝对路径解析失败：确认冻结路径中含仓库内的 `outputs/...` 或 `dataset/...` 后缀；
- existing failed/running job：保留该 run 目录，使用新 run ID；
- 公平性单字段失败：不得跳过检查或手改结果；
- TPP 请求失败且显示 `pending_stage6`：这是阶段 5 的预期硬拒绝；
- 任一失败均不得手工创建 verification 或打印最终标记。

`stage5-baseline-r1`、`stage5-baseline-r2`、`stage5-baseline-r3` 分别在历史
工件自测、Stage-0 策略映射和回归 receipt 解析处失败。三者都必须保留现场，不得续跑
或当作完成证据。修复后的下一次运行使用 `stage5-baseline-r4`。
