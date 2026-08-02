# CAPD Stage 3 适配 Stage 7 六 Workload 服务器执行指南

本文只执行 Stage 3 Train/Validation 校准。禁止把任何 Test、Pressure Test、
Stage 8 结果或旧 CAPD/Oracle Test 指标传给本 runner。本文不执行 Stage 4，
不训练模型，也不生成 Pressure CSV 或 Pressure Test lock。

2026-08-01 的 `stage3-stage7-calibration-r1` 应在旧实现的 `profile` 阶段人工中止。
中止后必须保留其失败目录用于审计，不能用修改后的代码 resume。优化后的代码使用新的
run ID，输入和实验选择规则均未改变。

固定 run ID：

```text
stage3-stage7-calibration-r2
```

固定输出目录：

```text
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/
```

以下命令逐段复制执行。不要在交互终端前置 `set -e`；这样某条命令失败时
终端仍保留，便于查看错误和继续排查。

## 1. 进入仓库并激活环境

```bash
cd "$HOME/Q-former-for-OS"
conda activate capd
pwd
```

## 2. 检查 Git 状态

```bash
git status --short
git rev-parse HEAD
```

工作区可以包含本轮 Stage 3 未提交文件，但不得覆盖旧 Stage 3、R1 或其他
已验证输出。

## 3. 检查 Python、PyTorch 和 CUDA

```bash
python3 -c 'import sys; print(sys.version)'
python3 -c 'import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.device_count())'
```

Stage 3 Replay 本身使用 CPU；这里检查 CUDA 只是确认服务器环境完整，不会
启动 Stage 4 训练。

## 4. 编译本轮新增和修改的 Python

```bash
python3 -m py_compile \
  qmap/proactive_stage3_stage7.py \
  qmap/proactive_replay.py \
  scripts/run_capd_proactive_stage3_stage7.py \
  tests/test_capd_proactive_stage3_stage7.py
```

任何编译错误都先停止，不要创建或删除实验目录来绕过。

## 5. 运行新 Stage 3 测试

```bash
python3 -m unittest tests.test_capd_proactive_stage3_stage7 -v
```

## 6. 运行旧 Stage 3 和共享 Replay 回归测试

```bash
python3 -m unittest \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_replay \
  tests.test_capd_proactive_stage4 -v
```

必须同时验证旧 Stage 3 接口。`proactive_replay` 的新开关只允许新 Stage 3
显式测试 `b_max=K=8`；旧调用仍执行原来的 `b_max < K` 合同。

## 7. 执行 preflight

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py preflight \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD"
```

该阶段只接受 R1 权威链中的 6 Train + 6 Validation。它会校验 R1
`raw_identity_audit.json`、`verification.json`、12 个 split SHA、配置 SHA 和
代码 SHA。任何 Test role、`formal_test=true`、`standard_test_lock`、
`pressure_test` 或 `stage8` 路径都会立即失败。

查看输入合同：

```bash
python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/input_manifest.json
```

确认 `input_entry_count` 的实际含义为 12 项，且只出现 `train`、
`validation`。

## 8. 执行 profile

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py profile \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD"
```

该阶段保存所有 100k/300k/500k 连续窗口。Train 被划分为三个连续 block；
Validation 保持独立，不跨 split 或 block。每个窗口以空 DRAM 开始，不
shuffle。窗口 LRU stack-distance 只计算一次，并同时解析所有候选容量，避免
对每个容量重复扫描整个窗口。三个 workload worker 并行执行；每个窗口的 base
profile 和容量指标分别原子写入 checkpoint，中断后可在代码、配置和输入 SHA
不变时恢复。

另开一个终端查看 profile 进度：

```bash
tail -f outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/logs/profile/*.jsonl
```

每个 workload 的首条 `profile_workload_started` 会给出 `total_task_count`；
`profile_task_completed` 给出单任务实际秒数，不再靠无输出等待猜测进度。
主日志中的 `profile_plan_created` 会在读取 trace 前给出全部 workload 的
`total_window_count` 和 `total_task_count`。

统计已完成的 profile 子任务：

```bash
find outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/checkpoints/profile \
  -name '*.json' -type f | wc -l
```

默认 R1 manifest 下预计为 2232 个窗口、4464 个 profile 子任务；checkpoint
计数除以 4464 即为完成比例。该数字是 manifest 计划，不是删减窗口后的近似值。

## 9. 执行 search

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py search \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD"
```

search 可能是本轮耗时最长的阶段。相同 Replay 身份先使用进程内缓存，跨进程
重启时再读取磁盘 checkpoint，不改变任何策略结果。进度和逐任务 checkpoint 位于：

```bash
tail -f outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/logs/progress.jsonl
```

另开一个终端执行 `tail -f`；原执行终端保持不动。窗口哨兵只按
Reactive-LRU replacement decisions、unique pages、起点顺序选择。Oracle、
weighted cost 和任何模型结果不参与选窗。

## 10. 执行 select

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py select \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD"
```

该阶段依次应用压力覆盖、Oracle 非零 headroom、主动机制效果、Validation
安全门禁和 Pareto frontier。它只生成候选，不正式 freeze。

## 11. 执行 verify

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py verify \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD"
```

成功候选的状态应为：

```text
STAGE3_STAGE7_FREEZE_CANDIDATE_VERIFIED
```

如果输出 `STAGE3_STAGE7_GATES_BLOCKED`，说明代码和产物验证完成，但数据没有
通过进入 Stage 4 的机制门禁；此时禁止 freeze，也禁止通过查看 Test 调参。

## 12. 查看 Pressure coverage

```bash
python3 -c 'import json; p="outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_coverage.json"; d=json.load(open(p)); print("rows",len(d["rows"])); [(print(r["coverage_id"],r["workload"],r["train_pressure_window_count"],r["train_pressure_coverage"],r["validation_pressure_window_count"],r["validation_pressure_coverage"])) for r in d["rows"][:30]]'
```

完整数据保留在 JSON 中，以上只打印前 30 行用于快速检查。

## 13. 查看 Oracle headroom

```bash
python3 -c 'import json; p="outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/oracle_headroom.json"; d=json.load(open(p)); print(json.dumps(d["gate"],indent=2)); print("rows",len(d["rows"]))'
```

若所有合格窗口 headroom 都为 0，Stage 3 必须阻止进入 Stage 4。

## 14. 查看 Validation safety

```bash
python3 -c 'import json,collections; p="outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/validation_safety.json"; d=json.load(open(p)); c=collections.Counter(reason for row in d["rows"] if not row["passed"] for reason in row["reasons"]); print("rows",len(d["rows"])); print(c)'
```

重点检查 `meaningless_proactive_demotions`、`weighted_cost_regression`、
`high_early_reuse` 和 `normal_dram_residency_degraded`。

## 15. 查看 Pareto frontier

```bash
python3 -c 'import json; p="outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pareto_frontier.json"; d=json.load(open(p)); print("frontier",len(d["frontier"])); [print(r) for r in d["frontier"]]'
```

## 16. 查看 final freeze candidate

```bash
python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze_candidate.json

python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract_candidate.json
```

检查实际逐 workload `D_pressure/F_low/F_target`、窗口长度、W_ref 分位数、
`b_max`、所有门禁和选择理由。此时以下文件必须仍不存在：

```bash
test ! -e outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze.json
test ! -e outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract.json
```

## 17. 人工确认后显式 freeze

只有人工复核候选并同意后，才执行：

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py freeze \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD" \
  --candidate outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze_candidate.json \
  --confirm-stage3-stage7-freeze
```

缺少候选路径或确认参数时必须失败。`all` 命令永远不会代替这一步。

## 18. freeze 后验证

```bash
python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze.json

python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract.json

sha256sum \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze.json \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract.json
```

正式合同仍只描述以后如何生成 Pressure；本 runner 不生成 Pressure CSV 或
Pressure Test lock。

## 19. 断点续跑

某阶段中断后，保留原目录，使用同一命令加 `--resume`。例如：

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py search \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD" \
  --resume
```

也可以从头按阶段自动跳过已完成项：

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py all \
  --config configs/finals/capd_proactive_stage3_stage7_calibration.json \
  --run-id stage3-stage7-calibration-r2 \
  --project-root "$PWD" \
  --resume
```

`all` 的顺序固定为 `preflight -> profile -> search -> select -> verify`，结束
标记为：

```text
STAGE3_STAGE7_ALL_COMPLETE_FREEZE_NOT_EXECUTED
```

## 20. 失败处理

- 不删除失败目录，不用删除后重跑伪装首次成功。
- 输入 SHA、配置 SHA 和代码 SHA 完全一致：使用 `--resume`。
- 本次旧代码身份的 r1 必须保留；修改后的实现必须使用 r2，禁止跨代码身份 resume。
- 后续任一 SHA 或代码身份再次改变：保留原目录并递增 run ID。
- R1 SHA/状态失败：立即停止，不绕过、不重跑 R1。
- Oracle 全零 headroom：保留失败门禁，不进入 Stage 4。
- Validation safety 失败：保留逐候选原因，不查看 Test 后调参。
- 不执行 Stage 4、Stage 8、模型训练或 Pressure Test 生成来“补救”Stage 3。

查看失败状态：

```bash
python3 -m json.tool \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/run_state.json

tail -n 100 \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/logs/progress.jsonl
```

## 21. 打包结果并计算 SHA256

在 freeze 前返回候选也可以；若已正式 freeze，则两个正式文件会一并打包。

```bash
tar -czf capd-stage3-stage7-calibration-r2-results.tar.gz \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2

sha256sum capd-stage3-stage7-calibration-r2-results.tar.gz \
  > capd-stage3-stage7-calibration-r2-results.tar.gz.sha256

cat capd-stage3-stage7-calibration-r2-results.tar.gz.sha256
```

## 22. 带回本地的产物

需要带回：

```text
capd-stage3-stage7-calibration-r2-results.tar.gz
capd-stage3-stage7-calibration-r2-results.tar.gz.sha256
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/run_state.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/verification.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_coverage.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/oracle_headroom.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/validation_safety.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pareto_frontier.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/selection_rationale.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze_candidate.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract_candidate.json
```

若已人工 freeze，再额外带回：

```text
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/final_freeze.json
outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/pressure_generation_contract.json
```

## 23. R2 门禁修复：只派生重选，不重跑 profile/search

R2 已完整执行，但旧选择规则把同步 `Proactive-LRU - Reactive-LRU` 成本、
DRAM hit 和 early reuse 同时作为所有 Validation 窗口的硬门禁。这不符合本项目的
主要比较口径：Reactive-LRU 只负责压力资格和描述性参照，正式比较关注相同主动降级
控制器下的不同 baseline；同步 Replay 只用于机制、排序和风险审计，效率结论必须由
前台程序与后台计算/降级并行的异步实验给出。

本修复不会修改或删除 R2，也不会打开 trace、重新 profile、重新 search、训练模型、
读取 Test 或生成 Pressure Test。它校验 R2 run identity 和关键产物 SHA 后，在新目录中
重新计算角色化 Validation 门禁、主动 LRU 对主动 Oracle 的 headroom 和 Pareto 选择。
这是公开披露的 Validation 后工程校准，不冒充独立 Validation 或正式重跑。

固定来源和新 run ID：

```bash
cd "$HOME/Q-former-for-OS"
conda activate capd

SOURCE_RUN="$PWD/outputs/capd_proactive_stage3/stage3-stage7-calibration-r2"
REPAIR_RUN_ID="stage3-stage7-selection-repair-r3"
REPAIR_CONFIG="configs/finals/capd_proactive_stage3_stage7_selection_repair.json"

test -f "$SOURCE_RUN/run_state.json"
test -f "$SOURCE_RUN/policy_results.json"
test -f "$SOURCE_RUN/validation_safety.json"
test ! -e "$PWD/outputs/capd_proactive_stage3/$REPAIR_RUN_ID"
```

先编译和运行新旧回归测试：

```bash
python3 -m py_compile \
  qmap/proactive_stage3_stage7.py \
  scripts/run_capd_proactive_stage3_stage7.py \
  tests/test_capd_proactive_stage3_stage7.py

python3 -m unittest tests.test_capd_proactive_stage3_stage7 -v

python3 -m unittest \
  tests.test_capd_proactive_stage3 \
  tests.test_capd_proactive_replay \
  tests.test_capd_proactive_stage4 -v
```

执行派生重选和验证；这两步只解析既有 JSON，正常不应再次运行数小时 Replay：

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py reselect \
  --selection-config "$REPAIR_CONFIG" \
  --source-run-directory "$SOURCE_RUN" \
  --run-id "$REPAIR_RUN_ID" \
  --project-root "$PWD"

python3 scripts/run_capd_proactive_stage3_stage7.py verify-reselection \
  --selection-config "$REPAIR_CONFIG" \
  --source-run-directory "$SOURCE_RUN" \
  --run-id "$REPAIR_RUN_ID" \
  --project-root "$PWD"
```

成功标志应为：

```text
reselect_complete
STAGE3_STAGE7_DERIVED_SELECTION_CANDIDATE_VERIFIED
```

查看门禁、主动 Oracle headroom、Pareto 和候选：

```bash
export REPAIR_RUN="$PWD/outputs/capd_proactive_stage3/$REPAIR_RUN_ID"

python3 -c 'import json,os; p=os.path.join(os.environ["REPAIR_RUN"],"selection_rationale.json"); d=json.load(open(p)); print("pareto",d["pareto_candidate_count"]); print("selected",d["selected_candidate_id"]); print("reactive_primary",d["reactive_lru_is_primary_comparison_baseline"]); print("sync_efficiency_evidence",d["synchronous_replay_is_efficiency_evidence"])'

python3 -c 'import json,os; p=os.path.join(os.environ["REPAIR_RUN"],"active_oracle_headroom.json"); print(json.dumps(json.load(open(p))["gate"],indent=2))'

python3 -m json.tool "$REPAIR_RUN/final_freeze_candidate.json"
python3 -m json.tool "$REPAIR_RUN/verification.json"

test ! -e "$REPAIR_RUN/final_freeze.json"
test ! -e "$REPAIR_RUN/pressure_generation_contract.json"
```

把以下 R3 派生产物先同步回本地人工复核：

```text
resolved_selection_config.json
selection_run_identity.json
source_run_reference.json
validation_safety_reinterpreted.json
active_oracle_headroom.json
pareto_frontier.json
selection_rationale.json
final_freeze_candidate.json
pressure_generation_contract_candidate.json
verification.json
run_state.json
```

人工确认后才能执行派生冻结：

```bash
python3 scripts/run_capd_proactive_stage3_stage7.py freeze-reselection \
  --selection-config "$REPAIR_CONFIG" \
  --source-run-directory "$SOURCE_RUN" \
  --run-id "$REPAIR_RUN_ID" \
  --project-root "$PWD" \
  --candidate "$REPAIR_RUN/final_freeze_candidate.json" \
  --confirm-stage3-stage7-freeze
```

freeze 后检查边界声明：

```bash
python3 -c 'import json,os; p=os.path.join(os.environ["REPAIR_RUN"],"verification.json"); d=json.load(open(p)); keys=["test_payload_opened","test_used_for_selection","stage8_results_used","pressure_test_generated","source_profile_or_search_rerun","synchronous_efficiency_claims_allowed","asynchronous_runtime_evaluation_required"]; print({k:d[k] for k in keys})'

sha256sum \
  "$REPAIR_RUN/final_freeze.json" \
  "$REPAIR_RUN/pressure_generation_contract.json"
```

`synchronous_efficiency_claims_allowed=false` 必须保持不变。后续异步 Replay/运行时实验
需要真正同时运行前台 workload 与后台候选计算、降级执行，分别报告前台延迟/吞吐、
后台 CPU/GPU 开销、降级完成率、阻塞/回退和总系统成本；Stage 3 同步结果不能替代这些证据。

## 24. Standard/Pressure 统一合同与 b_max=2 人工复核修复

R3 候选不能直接 freeze，因为旧 Standard 矩阵使用全局 Train∪Validation working set
的 20/40/60%，而 Pressure 使用 500k Train 窗口 q50 的 10%。人工复核进一步确定：
Standard 与 Pressure 除区间选择外，容量矩阵、working-set 定义、水位、批量、模型、
checkpoint、seed、cost profile、初始状态和策略配置必须完全相同。

`b_max=1` 与 `b_max=2` 在 18 个既有 Replay 窗口上的同步成本、迁移总量、空闲页、
exhaustion 和 early reuse 相同；`b_max=2` 将 proactive rounds 从 124406 降到
62600，约减少 49.7%，而 active Oracle headroom 仅下降约 0.018%。因此统一合同显式
约束 `b_max=2`。这是人工复核后的工程选择，产物中必须公开记录，不能冒充原 R3 自动选择。

本步骤仍只重选既有 R2 JSON，不运行 profile、search 或 Replay：

```bash
cd "$HOME/Q-former-for-OS"
conda activate capd

SOURCE_RUN="$PWD/outputs/capd_proactive_stage3/stage3-stage7-calibration-r2"
UNIFIED_CONFIG="configs/finals/capd_proactive_stage3_stage7_unified_contract.json"
UNIFIED_RUN_ID="stage3-stage7-unified-contract-r4"

test -f "$SOURCE_RUN/run_state.json"
test ! -e "$PWD/outputs/capd_proactive_stage3/$UNIFIED_RUN_ID"

python3 -m py_compile \
  qmap/proactive_stage3_stage7.py \
  scripts/run_capd_proactive_stage3_stage7.py \
  tests/test_capd_proactive_stage3_stage7.py

python3 -m unittest tests.test_capd_proactive_stage3_stage7 -v

python3 scripts/run_capd_proactive_stage3_stage7.py reselect \
  --selection-config "$UNIFIED_CONFIG" \
  --source-run-directory "$SOURCE_RUN" \
  --run-id "$UNIFIED_RUN_ID" \
  --project-root "$PWD"

python3 scripts/run_capd_proactive_stage3_stage7.py verify-reselection \
  --selection-config "$UNIFIED_CONFIG" \
  --source-run-directory "$SOURCE_RUN" \
  --run-id "$UNIFIED_RUN_ID" \
  --project-root "$PWD"
```

核对统一合同；四个布尔表达式都必须输出 `True`，`b_max` 必须为 `2`：

```bash
export UNIFIED_RUN="$PWD/outputs/capd_proactive_stage3/$UNIFIED_RUN_ID"

python3 -c 'import json,os; p=os.path.join(os.environ["UNIFIED_RUN"],"final_freeze_candidate.json"); d=json.load(open(p)); print("candidate",d["selected_candidate_id"]); print("b_max",d["b_max"]); print("hard_principle",d["standard_pressure_hard_principle_satisfied"]); print("same_matrix",d["standard_capacity_matrix"]==d["pressure_capacity_matrix"]==d["unified_capacity_matrix"]); print("workloads",len(d["unified_capacity_matrix"])); print("watermarks",len(d["watermarks"]))'

python3 -c 'import json,os; p=os.path.join(os.environ["UNIFIED_RUN"],"verification.json"); d=json.load(open(p)); print("status",d["status"]); print("hard_principle",d["standard_pressure_hard_principle_satisfied"]); print("required_b_max",d["required_b_max"]); print("test_used",d["test_used_for_selection"]); print("rerun",d["source_profile_or_search_rerun"])'

test ! -e "$UNIFIED_RUN/final_freeze.json"
```

把整个 `stage3-stage7-unified-contract-r4/` 同步回本地人工复核。R4 复核完成前，
不要对 R3 或 R4 执行 freeze。正式 freeze 后，Stage 4 只能绑定一份模型 checkpoint
SHA 和 seed；Standard 与 Pressure 必须引用同一绑定，不允许分别训练或分别选 seed。
