# CAPD 主动降级阶段 3：capacity_rule_v2 服务器运行

## 数据选择

不再调用依赖 `/root/qmap-work` 的重新采集脚本。v2 固定使用仓库中现有但未参与本次 v2 规则设计的 `real_workload_suite/5m` Train/Validation 对：

- `parsec_canneal_train.csv` / `parsec_canneal_valid.csv`；
- `parsec_streamcluster_train.csv` / `parsec_streamcluster_valid.csv`；
- `parsec_dedup_train.csv` / `parsec_dedup_valid.csv`。

同一 workload 的 Train/Validation 来自同一套 trace 划分，避免跨运行绝对地址使 Working Set 并集失真。任何 `test.csv` 都不使用。程序还会拒绝把 `stage3-real-001` 的旧 Train/Validation 直接复用到 v2。

## 一次性运行命令

所有命令在服务器终端执行；不要在交互终端设置 `set -e`。

```bash
cd "$HOME/Q-former-for-OS"

PREVIOUS_RUN="$PWD/outputs/capd_proactive_calibration/stage3/stage3-real-001"
V2_MANIFEST="$PWD/stage3_manifest_v2_003.json"
SUITE="$PWD/dataset/processed/real_workload_suite/5m"

python3 scripts/prepare_capd_proactive_stage3_v2_manifest.py \
  --previous-run-directory "$PREVIOUS_RUN" \
  --train "canneal=$SUITE/parsec_canneal_train.csv" \
  --validation "canneal=$SUITE/parsec_canneal_valid.csv" \
  --train "streamcluster_pressure=$SUITE/parsec_streamcluster_train.csv" \
  --validation "streamcluster_pressure=$SUITE/parsec_streamcluster_valid.csv" \
  --train "dedup_pressure=$SUITE/parsec_dedup_train.csv" \
  --validation "dedup_pressure=$SUITE/parsec_dedup_valid.csv" \
  --output "$V2_MANIFEST" \
  --project-root "$PWD"

if [ $? -eq 0 ] && [ -f "$V2_MANIFEST" ]; then
  export STAGE3_INPUT_MANIFEST="$V2_MANIFEST"
  export STAGE3_RUN_ID="stage3-v2-real-003"
  printf 'manifest=%s\nrun_id=%s\n' \
    "$STAGE3_INPUT_MANIFEST" "$STAGE3_RUN_ID"
  bash scripts/validate_capd_proactive_stage3_server.sh
else
  echo "V2 manifest 生成失败；当前终端保留，请检查上方第一条错误。"
fi
```

manifest 生成器拒绝覆盖已有文件；若 `stage3_manifest_v2_003.json` 已存在，请把 manifest 文件名和 run id 的 `003` 同时换成新的编号。

## 运行状态

另开终端：

```bash
cd "$HOME/Q-former-for-OS"
tail -f stage3_validation.log
```

查看持久化进度：

```bash
cd "$HOME/Q-former-for-OS"
tail -f \
  outputs/capd_proactive_calibration/stage3/stage3-v2-real-001.incomplete/logs/progress.jsonl
```

如果运行中断且 `.incomplete` 存在，输入和代码都没有变化时恢复：

```bash
cd "$HOME/Q-former-for-OS"
STAGE3_INPUT_MANIFEST="$PWD/stage3_manifest_v2.json" \
STAGE3_RUN_ID="stage3-v2-real-001" \
STAGE3_RESUME=1 \
bash scripts/validate_capd_proactive_stage3_server.sh
```

## 结束标志

成功形成可审阅冻结候选：

```text
STAGE3_V2_FREEZE_CANDIDATE_READY profile=primary
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
```

或：

```text
STAGE3_V2_FREEZE_CANDIDATE_READY profile=fallback
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
```

若容量门槛仍未通过：

```text
STAGE3_V2_CAPACITY_NOT_FREEZABLE
```

此时脚本以状态码 3 结束，但 Reactive 容量审计目录已经完整落盘，不会运行水位和 `b_max` 的 Proactive-LRU。

若容量通过但水位、`b_max` 或 K 代理不变性未形成完整候选：

```text
STAGE3_V2_PROACTIVE_NOT_FREEZABLE
```

此时脚本以状态码 4 结束，保留全部已完成产物。

## 需要同步回本地

```text
stage3_manifest_v2.json
stage3_validation.log
outputs/capd_proactive_calibration/stage3/stage3-v2-real-001/
```

最终冻结只在本地复核 `capacity_pressure_audit.json`、`selection_decision.json`、`freeze_candidate.json`、水位/批量原始结果和 provenance 后进行。
