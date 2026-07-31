# CAPD 主动降级阶段 7 当前状态

## 当前状态

`stage7_workload_suite_verified`

阶段 7 已于 2026-07-31 通过真实 Linux 服务器验收。正式服务器 run ID 为
`stage7-server-suite-r1`，验收脚本真实打印：

```text
[FINAL] STAGE7_WORKLOAD_SUITE_VERIFIED
validator_exit=0
```

`stage8_entry_gate=satisfied`。这只表示六 workload 数据、Working Set、容量矩阵、
Standard Test lock 和阶段 8 运行计划已经冻结；不表示阶段 8 Test 已执行，也不构成
任何方法性能结论。

## 正式名单

| workload | 角色 | 覆盖类型 |
|---|---|---|
| canneal | seen calibration | 不规则、局部性敏感 |
| streamcluster_pressure | seen calibration | 高容量压力、突发进入 |
| dedup_pressure | seen calibration | 写密集、高容量压力 |
| blackscholes | held-out unseen | 稳定局部性 |
| swaptions | held-out unseen | 计算主导、稳定局部性 |
| fluidanimate | held-out unseen | 不规则、突发进入 |

备用 unseen 为 bodytrack、facesim，不进入本次正式名单。

## Trace 采集回执

- collection run ID：`stage7-local-collection-r1`；
- collector：DynamoRIO drmemtrace 11.91.20581；
- 六个 workload 各 3,000,000 条数据访问，共 18,000,000 条；
- schema：`PID,TID,PC,Address,RW`，page size 为 4 KB；
- split：Train `[0,1800000)`，Validation `[1800000,2400000)`，
  Test `[2400000,3000000)`；
- 六条正式 Trace 均为单 PID、单 TID；
- 输入、benchmark 二进制、访问数和原始 Trace SHA-256 均已封存；
- Test 未用于参数选择、未运行策略 Replay、未查看性能。

swaptions 的 PARSEC `gcc-pthreads -nt 1` 在完整 Trace 中产生两个 TID，已被门禁
正确拒绝；失败证据保存在 `failed_attempts/swaptions-pthreads-two-tids`。正式结果
使用同一 PARSEC 3.0 源码的 serial 构建，并在完整 3,000,000 条访问上确认单 TID。

## Working Set 与容量冻结

Working Set 定义为 `active_unique_pages_from_train_and_validation`，不使用 Test 页面
集合计算。正式结果为：

| workload | Working Set pages | D20 pages | D40 pages | D60 pages |
|---|---:|---:|---:|---:|
| canneal | 4443 | 889 | 1778 | 2666 |
| streamcluster_pressure | 1921 | 385 | 769 | 1153 |
| dedup_pressure | 982 | 197 | 393 | 590 |
| blackscholes | 110 | 22 | 44 | 66 |
| swaptions | 297 | 60 | 119 | 179 |
| fluidanimate | 27720 | 5544 | 11088 | 16632 |

共冻结 18 个容量行。20% DRAM 仍是条件工程默认值，不是 `capacity_rule_v2` 的
形式化标定结论；`F_low=8`、`F_target=16`、`K=8`、`b_max=4` 均未改变且不随
容量缩放。

blackscholes 的 D20 为 22 页，满足 `D20 > max(F_target,K)=16` 的硬门禁，但低于
100 页，因此按预声明规则保留
`D_20_below_100_evaluate_recollection_or_replacement` 警告。该警告与 Test 性能无关。

## 服务器验收证据

- 阶段 1～7 回归：361 项，耗时 33.312 秒，返回 `OK (skipped=10)`；
- regression runner exit code：0；
- workload registry：`frozen`，6/6 workload eligible；
- capacity matrix：3 个比例、18 行；
- Standard Test：`sealed_for_stage8`；
- 阶段 8 计划：`frozen_plan_not_executed`，共 144 job；
- `performance_results=null`；
- verification 中 12 个证据文件 SHA-256 已在同步回本地后重新计算，0 个不一致；
- `frozen_parameters_changed=false`；
- `test_used_for_parameter_selection=false`；
- `test_policy_replay_executed=false`；
- `test_performance_inspected=false`；
- `formal_test_performance_conclusion=null`。

权威完成证据：

- `outputs/capd_proactive_stage7/stage7-server-suite-r1/run_state.json`
- `outputs/capd_proactive_stage7/stage7-server-suite-r1/verification.json`
- `outputs/capd_proactive_stage7/stage7-server-suite-r1/server_test_receipt.json`
- `outputs/capd_proactive_stage7/stage7-server-suite-r1/provenance.json`

## 阶段 8 入口

阶段 7 已满足进入阶段 8 的技术门禁。阶段 8 必须严格使用冻结的
`stage8_execution_plan.json`、`standard_test_lock.json`、容量矩阵、六 workload 和
三个 CAPD checkpoint seed。不得重新采集或重选 workload，不得根据 Test 返回阶段
3～7 调参，也不得把阶段 7 的同步准备结果写成性能结论。
