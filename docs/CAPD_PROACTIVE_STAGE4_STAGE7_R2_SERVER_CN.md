# CAPD Stage 4 有效 Validation 集合协议修复（r2）服务器手册

## 1. 协议状态

新运行身份为 `stage4-stage7-unified-r2`，配置为
`configs/finals/capd_proactive_stage4_stage7_search_r2.json`。r2 是在 r1 样本结构门发现
`streamcluster_pressure/validation` 和 `fluidanimate/validation` 均为零之后、任何模型训练、
checkpoint、candidate 性能、Test 或 Pressure 访问之前完成的协议修复。原 r1 不得覆盖，继续保留为
`sample_structure_gate_failed_before_training` 审计证据。

训练范围仍为六个 workload。Stage 4 checkpoint 与 candidate 选择只使用：

- `canneal`
- `dedup_pressure`
- `blackscholes`
- `swaptions`

`streamcluster_pressure` 与 `fluidanimate` 严格登记为
`structural_zero_decision_validation`：Train 保留；Validation 指标为 `N/A`/JSON `null`；
有效决策数单独记录为 0；模型不在这两个 Validation workload 上调用；不参与成本、最差 workload、
NDCG、Validation loss 或任何 tie-break 聚合。若二者任一 Validation 样本数或有效决策数变为非零，
必须停止；四个 active workload 任一个为零也必须停止。

Stage 8 Standard 仍执行六个 workload。Stage 8 Pressure 仍执行正式派生的四个 workload。
Standard 中两个结构性零决策 workload 不得删除，应报告模型未调用或策略结果持平。

## 2. r1 缓存只读复用

r2 不复制、不改写、也不伪装重新生成约 7.2 GB 的 r1 样本。`samples` 入口将执行：

1. 校验 r1 `run_state` 为样本门失败且训练、搜索、确认、freeze、Test、Pressure 均未发生；
2. 校验 r1 根级 input/sample/vocabulary/report/verification SHA；
3. 校验七个 semantic sample manifest 和 vocabulary manifest；
4. 逐文件校验 7 组 merged Train/Validation、84 个 workload/split 样本文件和 14 个词表文件；
5. 校验 R4 SHA、R2 manifest SHA、prepared input manifest SHA、L/H/lambda、D/F_low/F_target、
   `b_max=2`、`K=8`、源 trace SHA、vocabulary SHA 和 sample file SHA；
6. 在 r2 写入 `external_cache_reference.json`，其中只包含经过验证的 r1 绝对路径和 SHA。

任何身份不一致都会 fail closed，不会回退到重新生成、复制缓存或启动训练。

## 3. 上传代码后的单次 preflight 与缓存复核

下面的脚本会运行 Stage 4 相关测试、r2 preflight、7.2 GB 缓存逐文件 SHA 复核及结构门。
它不会执行 `confirm-contract`、`search`、`resume`、`all`、`freeze` 或 GPU 训练。

r2 preflight 会逐一验证当前 12 个 Train/Validation 源文件 SHA，但不会再次逐行解析
与 r1 相同的 14,400,000 条记录。它改为校验固定 SHA 的 r1
`resolved_config.json`，并将其中已通过的 12 份完整轨迹解析证据绑定到当前输入。
日志中的 `KeyboardInterrupt` 表示旧流程在重复解析期间收到外部 SIGINT；它不是测试、
CUDA 或合同断言失败。新流程在 `resolved_config.json` 中登记证据复用模式和来源 SHA。

```bash
cd ~/Q-former-for-OS
conda activate capd

tmux new-session -d -s capd-r2-gate-v2 \
  "cd '$PWD'; bash scripts/validate_capd_proactive_stage4_stage7_r2_server.sh '$PWD' > validation_logs/capd_stage4_r2_gate_v2.log 2>&1; rc=\$?; echo \$rc > validation_logs/capd_stage4_r2_gate_v2.exit; echo '[DONE] exit='\$rc; exec bash"

tmux attach -t capd-r2-gate-v2
```

这里 `set -e` 只存在于独立子脚本中，不会退出当前登录 shell。无论成功或失败，外层命令最后都会
`exec bash`，因此 `capd-r2-gate` 会话会保留；退出码保存在
`validation_logs/capd_stage4_r2_gate.exit`，也不会影响其他 tmux 会话。

完成后检查：

```bash
cd ~/Q-former-for-OS
cat validation_logs/capd_stage4_r2_gate_v2.exit
tail -n 80 validation_logs/capd_stage4_r2_gate_v2.log

python3 - <<'PY'
import json
from pathlib import Path

root = Path("outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2")
for name in ("run_state.json", "search_state.json",
             "sample_structure_verification.json",
             "external_cache_reference.json", "protocol_repair.json"):
    value = json.loads((root / name).read_text(encoding="utf-8"))
    print(name, value.get("status"), value.get("formal_freeze"),
          value.get("search_contract_confirmed"))
PY
```

成功终点必须是：

- 日志含 `[FINAL] STAGE4_R2_PREFLIGHT_AND_EXTERNAL_CACHE_GATE_VERIFIED`；
- 日志含 `[GATE] STOPPED_BEFORE_HUMAN_SEARCH_CONTRACT_CONFIRMATION`；
- r2 `run_state.status=sample_structure_gate_passed_awaiting_search_confirmation`；
- r2 `search_state.status=not_started`；
- `search_contract_confirmed=false`、`formal_freeze=false`；
- 没有 checkpoint、candidate 或正式模型；
- r1 仍为 `sample_structure_gate_failed`。

## 4. 人工确认边界

服务器结果同步回本地并重新审核前，禁止运行：

- `confirm-contract`
- `search`
- `resume`
- `all`
- `freeze`

本手册不提供上述命令。只有 r2 preflight、外部缓存 SHA 复核和修复后结构门全部通过，并由负责人再次
明确确认新搜索合同后，才会单独提供正式搜索命令。

## 5. 2026-08-03 architecture 阶段编排修复与恢复

首次正式搜索已完成 semantic 阶段全部 `7 candidate x 3 seed = 21` 次训练，
随后四个 architecture candidate 在训练前统一失败，错误为：

```text
r1 semantic cache index identity mismatch: da0dab0afec1945a70ef
```

原因是旧校验同时要求缓存 owner 的 `candidate_id` 等于当前跨阶段 candidate ID。
architecture/optimization candidate 继承 semantic winner 的 `L/H/lambda`，其样本内容身份和
semantic key 不变，但显示 ID 必然不同。修复后仍要求 sample index 与 vocabulary index
具有同一个 canonical semantic owner，并继续校验 semantic key、sample contract、词表和
所有文件 SHA；仅取消错误的跨阶段显示 ID 相等要求。搜索配置、样本、词表、训练参数、
模型、seed、Validation 协议和 checkpoint 均不改变。

失败事件、四个 architecture `failure.json` 和原空的外层 search 日志均保留。
恢复脚本会先检查固定代码/config/合同/缓存/semantic phase SHA，执行 Stage 4 回归测试，
核验 21 份既有 training contract、manifest 及 best/last checkpoint SHA，然后写入
`orchestration_repair_resume_receipt.json` 并执行 `resume`。已完成的 21 次训练不会重跑；
semantic Validation replay 会重新执行，随后只启动剩余 24 次 GPU 训练。

在现有 tmux 窗口中执行：

```bash
cd ~/Q-former-for-OS
conda activate capd
bash scripts/resume_capd_proactive_stage4_stage7_r2_server.sh "$PWD"
```

日志和退出码分别写入：

```text
validation_logs/capd_stage4_r2_resume.log
validation_logs/capd_stage4_r2_resume.exit
```

成功终点必须同时满足：退出码为 `0`、45 份 per-seed checkpoint manifest 存在、
`search_state.status=completed_candidate_ready`、
`run_state.status=candidate_ready_awaiting_formal_freeze`，且
`final_stage4_freeze.json` 和 `stage8_model_contract.json` 均不存在。
