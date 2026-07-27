# CAPD R1 压力—Headroom 诊断协议

状态：`R1_IMPLEMENTED_AWAITING_SERVER_EXECUTION`

## 1. 目的

R1 用于回答：

> 当前正式结果的收益较小，究竟是因为 D=64 下缺少可影响系统成本的
> victim 决策机会，还是冻结的 CAPD-MIC-1.0 即使在更高压力下也没有
> 足够 headroom？

R1 是新的开发诊断轨道，不是 O4，不形成最终泛化结论，也不覆盖
`STAGE6_VERIFIED`、`BRIDGE_DIAGNOSTIC_COMPLETED` 或 O1—O3。

## 2. 数据边界

允许读取：

- 三个 official workload 的 train；
- 三个 official workload 的 valid；
- official source metadata 和冻结指纹。

禁止读取：

- official test 行和 test 策略指标；
- Bridge test 指标用于方法或容量选择；
- fresh final holdout 行和策略指标。

R1 的所有配置都使用 `diagnostic_only` 工件，并显式记录：

```text
method_selection_performed = false
bridge_test_used_for_selection = false
test_trace_opened = false
test_used_for_selection = false
method_contract_changed = false
```

## 3. 冻结矩阵

三个 workload：

- `canneal`
- `streamcluster_pressure`
- `dedup_pressure`

三个压力点：

| case | D | B | K |
|---|---:|---:|---:|
| `pressure_D16` | 16 | 16 | 8 |
| `pressure_D32` | 32 | 32 | 8 |
| `pressure_D64` | 64 | 64 | 8 |

其余方法项冻结为：

```text
H=10, Hc=256, L=256, Lres=256
selector=CAPD B-to-K selector
loss=QMAPCostAwareRankingLoss
cost=official
```

采用 `B=D,K=8` 是为了让三个点保持“完整 DRAM LRU 池进入同一个
K=8 selector”的匹配关系，避免把 O3 的 B/K 参数优化混入容量归因。

## 4. 每个压力点的任务

每个 workload × D 点执行：

1. 只用 train/valid 重新拟合对应 selector；
2. 在 valid 上回放 LRU；
3. 在 valid 上回放 CLOCK；
4. 在 valid 上执行 bounded-label oracle；
5. 对完整 L=256 窗口执行逐候选 forced-first-victim 反事实审计。

任务总数：

```text
data/selector = 9
bounded oracle = 9
opportunity audit = 9
LRU/CLOCK baseline = 18
required_jobs = 45
training_jobs = 0
```

## 5. 汇总指标

每个点报告：

- 最佳 LRU/CLOCK valid weighted access cost；
- bounded-label oracle valid weighted access cost；
- absolute/relative oracle headroom；
- eviction decision 数量；
- 完整未来窗口 decision 数量；
- 候选反事实成本有区分度的 decision 比例；
- 代理标签有区分度的 decision 比例；
- future-write 标签有区分度的 decision 比例；
- retained candidates 同时包含 clean/dirty 页的 decision 比例；
- 候选反事实成本 spread 的 mean/median/max。

R1 只描述 D16/D32/D64 的变化，不选择容量、配置或方法。

## 6. 完成判据与后续门禁

所有 45 个任务完成、测试与 provenance 门禁通过后，状态写为：

```text
R1_PRESSURE_HEADROOM_VERIFIED
```

后续根据 R1 分流：

1. D16/D32 headroom 明显而 D64 很小：进入压力分层的冻结方法实验；
2. oracle 有 headroom 但模型无法兑现：另立新方法版本研究训练/闭环偏移；
3. 三个 D 的 oracle headroom 均很小：停止模型调参，评估标签、动作空间
   或方法适用范围。

任何分流都不能使用 Bridge/test/O4 holdout 结果进行选择。

## 7. 执行入口

本地只读输入审计与计划：

```bash
python3 scripts/run_capd_r1.py --stage audit-inputs
python3 scripts/run_capd_r1.py --stage plan
python3 -m pytest -q \
  tests/test_capd_r1_plan.py \
  tests/test_capd_r1_results.py
```

服务器统一验收：

```bash
set -o pipefail
bash scripts/validate_capd_r1_server.sh 2>&1 | tee capd_r1_validation.log
rc=${PIPESTATUS[0]}
echo "r1_exit_code=$rc"
```
