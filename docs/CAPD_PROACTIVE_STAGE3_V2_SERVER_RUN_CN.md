# CAPD 主动降级阶段 3：capacity_rule_v2 服务器运行

## 数据前提

下面三个 Validation CSV 必须满足：

- 在 `capacity_rule_v2` 冻结后才被选作本轮 Validation；
- 未参与 v1 结果分析或 v2 阈值设计；
- 不是 formal Test，也不是从 formal Test 重命名或复制得到；
- CSV 契约为 `pc,address,rw`，4 KiB 页面使用 `page_shift=12`。

程序会自动拒绝与 `stage3-real-001` 中任一旧 Validation SHA-256 相同的文件。语义上的数据来源仍需实验负责人确认。

## 一次性运行命令

先把三个新 Validation 路径替换为服务器真实绝对路径：

```bash
set -euo pipefail
cd "$HOME/Q-former-for-OS"

PREVIOUS_RUN="$PWD/outputs/capd_proactive_calibration/stage3/stage3-real-001"
V2_MANIFEST="$PWD/stage3_manifest_v2.json"

CANNEAL_V2="/absolute/path/to/fresh/canneal_validation.csv"
STREAMCLUSTER_V2="/absolute/path/to/fresh/streamcluster_pressure_validation.csv"
DEDUP_V2="/absolute/path/to/fresh/dedup_pressure_validation.csv"

test -f "$PREVIOUS_RUN/input_manifest.json"
test -f "$CANNEAL_V2"
test -f "$STREAMCLUSTER_V2"
test -f "$DEDUP_V2"
test ! -e "$V2_MANIFEST"

python3 scripts/prepare_capd_proactive_stage3_v2_manifest.py \
  --previous-run-directory "$PREVIOUS_RUN" \
  --validation "canneal=$CANNEAL_V2" \
  --validation "streamcluster_pressure=$STREAMCLUSTER_V2" \
  --validation "dedup_pressure=$DEDUP_V2" \
  --output "$V2_MANIFEST" \
  --project-root "$PWD"

STAGE3_INPUT_MANIFEST="$V2_MANIFEST" \
STAGE3_RUN_ID="stage3-v2-real-001" \
bash scripts/validate_capd_proactive_stage3_server.sh
```

不要把旧 `valid.csv` 或任何 Test 文件填入三个 `*_V2` 变量。manifest 生成器拒绝覆盖已有 `stage3_manifest_v2.json`；需要修正路径时请换一个新 manifest 文件名，以保留失败尝试的 provenance。

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
