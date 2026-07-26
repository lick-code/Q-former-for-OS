# CAPD 旧结果—Stage 6 桥接诊断

状态：`BRIDGE_DIAGNOSTIC_COMPLETED`（33/33 required jobs，服务器验收通过）

该实验用于解释旧论文 `streamcluster_pressure` 约 10.83% 的收益为何在
当前 Stage 6 中变为约 0.63%。它是 Stage 6 完成后的事后诊断，不是
Stage 7，不修改 `CAPD-MIC-1.0`，也不覆盖已经验收的
`STAGE6_VERIFIED`。

## 1. 科学问题

桥接矩阵依次只改变一个主要因素：

| 锚点 | trace | engine | D/B/K | 作用 |
|---|---|---|---:|---|
| `legacy_published_D16_B8K8` | 旧 pressure window | 旧论文流水线 | 16/8/8 | 冻结的旧结果 |
| `legacy_current_identity_D16_B8K8` | 旧 pressure window | 当前 MIC-1.0 | 16/8/8 | 检查当前引擎能否复现旧行为 |
| `legacy_current_selector_D16_B16K8` | 旧 pressure window | 当前 MIC-1.0 | 16/16/8 | 只引入当前 B→K selector |
| `official_current_selector_D16_B16K8` | 新 official recollection | 当前 MIC-1.0 | 16/16/8 | 只替换 trace 来源 |
| `official_current_full_D64_B64K8` | 新 official recollection | 当前 MIC-1.0 | 64/64/8 | 引用 Stage 5 Full，观察容量因素 |

相邻比较分别回答：

1. 旧实现到当前实现是否发生流水线语义漂移；
2. B→K selector 是否造成收益变化；
3. trace/pressure window 是否造成收益变化；
4. D=16 到 D=64 的压力减弱是否造成收益变化。

每个当前引擎的新训练点固定三个模型 seed：
`3136859, 42, 2026`。LRU、LFU、CLOCK各回放一次，Random固定
`0, 1, 2`三个回放 seed。所有 test 只用于最终诊断测量，不用于选择
模型、参数或后续方法。

## 2. 任务矩阵

新计算共33个required job：

- 3个独立数据/selector/JSONL任务；
- 9个训练任务；
- 9个QMAP回放任务；
- 12个匹配经典基线回放任务。

两个端点直接引用已有不可变证据：

- 旧论文三seed结果：
  `outputs/results/seed_stability/streamcluster_pressure/`；
- 当前D64三seed结果：
  `outputs/results/finals_v3_official/stage5_main/raw/streamcluster_pressure/`。

桥接输出使用独立目录：

```text
dataset/jsonl/capd_bridge_diagnostic/
outputs/checkpoints/capd_bridge_diagnostic/
outputs/results/capd_bridge_diagnostic/
```

不会写入：

```text
outputs/results/finals_v3_official/stage6/
```

## 3. 决策级诊断

新QMAP回放带 `--bridge_diagnostics`，额外记录：

- QMAP victim与LRU victim的分歧次数和比例；
- LRU victim是否仍在selector保留的K个候选中；
- 分歧决策下，有限L步next-use距离判定的
  `qmap_better/qmap_worse/equal`；
- QMAP victim相对LRU victim的有限next-use距离优势；
- top-1与top-2 eviction score margin；
- 每个seed的victim sequence SHA-256。

这些字段不改变victim选择、replay计数或weighted cost，只作为
post-hoc诊断。有限next-use证据不是完整反事实系统代价，报告中不得
把它写成普遍因果结论。

## 4. 数据与证据边界

桥接配置使用 `run_profile=diagnostic_bridge` 和
`artifact_class=diagnostic_only`。该profile保留独立train/valid trace，
但不会冒充manifest-bound official结果。

旧window的历史来源证据弱于finals_v3 official recollection，因此：

- 可用于解释旧数字到新数字的差异；
- 不可替换Stage 5/6 official主结果；
- 不可把旧window重新提升为正式主表；
- 不可根据bridge test结果继续修改默认方法。

## 5. 本地检查

本地无PyTorch/GPU时可以执行：

```bash
python3 scripts/run_capd_bridge.py --stage audit-inputs
python3 scripts/run_capd_bridge.py --stage plan
python3 -m pytest -q \
  tests/test_capd_bridge_plan.py \
  tests/test_capd_bridge_results.py \
  tests/test_capd_bridge_end_to_end.py
```

预期：

```text
input audit: PASSED
required_jobs: 33
job_counts: data=3, train=9, replay=9, baseline=12
```

## 6. 服务器正式执行

进入已激活 `capd` 环境的tmux后：

```bash
cd ~/Q-former-for-OS
set -o pipefail
bash scripts/validate_capd_bridge_server.sh 2>&1 | tee bridge_validation.log
rc=${PIPESTATUS[0]}
echo "bridge_exit_code=$rc"
```

脚本会依次完成输入审计、定向测试、torch mini E2E、完整pytest、
33-job矩阵、汇总、provenance检查、Stage 6不可变性检查和
`git diff --check`。所有门禁成功时最终输出：

```text
[FINAL] BRIDGE_DIAGNOSTIC_COMPLETED
bridge_exit_code=0
```

运行中可在另一个终端查看：

```bash
pgrep -af 'validate_capd_bridge|run_capd_bridge|qmap_train|qmap_eval|pytest'
tail -50 bridge_validation.log
nvidia-smi
```

## 7. 完成判据

`outputs/results/capd_bridge_diagnostic/run_manifest.json`必须满足：

```text
status == BRIDGE_DIAGNOSTIC_COMPLETED
required_jobs == 33
completed_required_jobs == 33
stage6_status == STAGE6_VERIFIED
official_stage6_replaced == false
method_contract_changed == false
test_used_for_selection == false
```

最终主要文件：

```text
bridge_results.csv
bridge_summary.json
bridge_attribution.csv
legacy_baseline_drift.csv
bridge_report.md
run_manifest.json
```
