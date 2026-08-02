# CAPD Stage 7：从 Standard Test 派生 Pressure Test（本地、fail closed）

本流程只允许从已冻结的 Stage 7 Standard Test 复制连续区间。它不运行
Stage 4、Stage 8、模型训练、checkpoint/seed 选择或服务器任务，也不读取旧
`stage7-repair-r1` 中已经失效的 Pressure、容量、窗口、lock 和 bundle 产物。
R1 目录只有 `raw_identity_audit.json` 与 `verification.json` 可作为身份依据。

## 当前合同结论

R4 `pressure_generation_contract.json` 已冻结窗口长度、扫描步长、统一容量、
水位、`b_max`、Reactive-LRU 资格规则和禁止特征，但未冻结多个 eligible Test
窗口之间的完整总排序及 tie-break。因此当前合法状态是：

`PRESSURE_DERIVATION_IMPLEMENTED_BUT_CONTRACT_BLOCKED`

此状态下允许生成候选统计与合同缺口报告；禁止生成正式
`derived_pressure/*/pressure.csv`、`pressure_test_lock.json` 和正式 bundle。

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

## 解除合同阻断所需的最小正式 addendum

必须由用户先明确批准、再写入权威冻结合同；本实现不会自行选择具体排序。
addendum 至少需要在 `pressure_window_selection_order` 明确给出：

- `total_order: true`；
- `ordered_keys`：逐项写明允许资格字段及 `ascending`/`descending` 方向；
- 最终唯一 tie-break 为 `split_relative_start`，并明确其方向；
- `manual_override_allowed: false`；
- `random_selection_allowed: false`。

允许的排序字段仅限 `reactive_lru_replacement_decisions`、`unique_pages` 和
`split_relative_start`。排序字段的顺序及方向本身是待审批决定，不能依据本次
Test 候选统计、CAPD/Oracle/TPP 表现或“结果最好”来补定。

addendum 正式冻结后必须更新 config 中对应权威文件 SHA，并使用新的 run ID；
不得复用本次 blocked run 的 checkpoint 或派生产物。

## 验证

```powershell
python -m unittest tests.test_capd_proactive_pressure_stage7 -v
python -m unittest tests.test_capd_proactive_stage3_stage7 -v
python -m unittest tests.test_capd_proactive_replay -v
```

`verification.json` 是当前 run 的最终状态入口。合同缺口分支还必须存在
`pressure_contract_gap_report.json`，并且不得存在 `derived_pressure` 目录或
`pressure_test_lock.json`。
