# CAPD Stage 7：从 Standard Test 派生 Pressure Test（本地、fail closed）

本流程只允许从已冻结的 Stage 7 Standard Test 复制连续区间。它不运行
Stage 4、Stage 8、模型训练、checkpoint/seed 选择或服务器任务，也不读取旧
`stage7-repair-r1` 中已经失效的 Pressure、容量、窗口、lock 和 bundle 产物。
R1 目录只有 `raw_identity_audit.json` 与 `verification.json` 可作为身份依据。

## 原始 R4 与 blocked 审计证据

R4 `pressure_generation_contract.json` 已冻结窗口长度、扫描步长、统一容量、
水位、`b_max`、Reactive-LRU 资格规则和禁止特征，但未冻结多个 eligible Test
窗口之间的完整总排序及 tie-break。因此原 blocked run 的合法状态是：

`PRESSURE_DERIVATION_IMPLEMENTED_BUT_CONTRACT_BLOCKED`

该 run 永久保留为缺口审计证据；其中只允许有候选统计与合同缺口报告，禁止补写正式
`derived_pressure/*/pressure.csv`、`pressure_test_lock.json` 和正式 bundle。

用户于 `2026-08-02T21:23:44+08:00` 正式批准独立 addendum：

`outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4-pressure-addendum-r1/pressure_window_selection_addendum.json`

它没有修改或覆盖原 R4，而是把唯一选择规则冻结为
`earliest_eligible_window_in_source_trace`。当前状态为
`ADDENDUM_FROZEN_AWAITING_FORMAL_DERIVE_CONFIRMATION`；在用户再次确认前不得
启动新的 `stage7-pressure-derive-r2` 数据阶段。

## 命令

在仓库根目录执行：

```powershell
python scripts/run_capd_proactive_pressure_stage7.py preflight `
  --config configs/finals/capd_proactive_pressure_stage7_r4.json `
  --run-id stage7-pressure-from-r4-r1 `
  --project-root .

python scripts/run_capd_proactive_pressure_stage7.py scan `
  --config configs/finals/capd_proactive_pressure_stage7_r4.json `
  --run-id stage7-pressure-from-r4-r1 `
  --project-root .

python scripts/run_capd_proactive_pressure_stage7.py verify `
  --config configs/finals/capd_proactive_pressure_stage7_r4.json `
  --run-id stage7-pressure-from-r4-r1 `
  --project-root .
```

`derive` 在排序合同不完整时必须以退出码 2 拒绝。`all` 的固定顺序为
`preflight -> scan -> derive（仅合同完整时） -> verify`；当前会自动跳过
`derive`，执行合同缺口验证。

已经完成的同一 run 可加 `--resume`。仅当输入身份、config SHA 和 code SHA
全部与 `run_state.json` 一致，且已完成阶段的产物 SHA 未改变时才允许续跑。
失败目录保留，不以删除目录伪装首次成功。

用户再次确认后，新的正式运行从以下命令开始，不加 `--resume`：

```powershell
python scripts/run_capd_proactive_pressure_stage7.py all `
  --config configs/finals/capd_proactive_pressure_stage7_r4_addendum_r1.json `
  --run-id stage7-pressure-derive-r2 `
  --project-root .
```

确认前不得执行该命令。

## 扫描边界

- 只打开 `canneal`、`dedup_pressure`、`blackscholes`、`swaptions` 的 Test；
- `streamcluster_pressure`、`fluidanimate` 只进入排除清单，选窗扫描不会打开
  它们的 Test；
- Test 为 600,000 行，窗口为 500,000 行，步长为 10,000 行，每个允许
  workload 恰有 11 个候选；
- 每个候选独立从空 DRAM 开始，只计算 Reactive-LRU；
- `Address >> 12` 得到页面；
- 资格条件为 `unique_pages > D + F_target` 且
  `reactive_lru_replacement_decisions >= 100`；
- 候选统计不得包含 CAPD、Oracle、TPP、weighted cost、Stage 4/8、模型、
  checkpoint 或 seed 结果。

## 已批准并冻结的 addendum 规则

资格过滤仍完全使用原 R4：

- `unique_pages > D + F_target`；
- `reactive_lru_replacement_decisions >= 100`。

过滤后按以下键升序排序，每个 workload 只取 rank 1：

1. `source_interval.start_inclusive`；
2. `source_interval.end_exclusive`；
3. `source_trace_id`；
4. `candidate_content_sha256`。

`candidate_content_sha256` 只哈希源 Test 身份和连续区间身份，不包含
`unique_pages`、replacement decisions 或任何方法性能指标。资格统计不参与
eligible 窗口之间的排名。无 eligible 窗口时如实排除，不补造数据。

正式运行必须使用新配置
`configs/finals/capd_proactive_pressure_stage7_r4_addendum_r1.json` 和新 run ID
`stage7-pressure-derive-r2`，从头重扫；不得续跑或升级原 blocked run。

## 验证

```powershell
python -m unittest tests.test_capd_proactive_pressure_stage7 -v
python -m unittest tests.test_capd_proactive_stage3_stage7 -v
python -m unittest tests.test_capd_proactive_replay -v
```

`verification.json` 是当前 run 的最终状态入口。合同缺口分支还必须存在
`pressure_contract_gap_report.json`，并且不得存在 `derived_pressure` 目录或
`pressure_test_lock.json`。
