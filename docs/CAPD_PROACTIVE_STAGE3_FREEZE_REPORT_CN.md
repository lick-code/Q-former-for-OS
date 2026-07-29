# CAPD 主动降级阶段 3 真实结果审计与待冻结报告

## Material Passport

- ID：`CAPD-STAGE3-REAL-001-REVIEW`
- 类型：实验结果验证报告
- 数据：`outputs/capd_proactive_calibration/stage3/stage3-real-001/`
- Verification Status：`ANALYZED`
- 原因：已完成产物 hash、原始计数、burst 窗口和选择规则重算，但未从干净 commit 完整重跑实验
- 数据边界：仅 Train/Validation；Test 未参与；CAPD 未参与参数选择

## 结论摘要

服务器真实运行和产物同步完整，水位与批量结论可从原始结果精确重算：

- 水位推荐：`F_low=2, F_target=4`；
- 批量推荐：`b_max=4`；
- K 代理：8 和 16 均选择 Medium 水位与 `b_max=4`，不变性通过；
- 正式 `method.candidate_size_K`：继续保持 `null/pending`。

容量比例不能按当前预声明规则冻结。20/40/60 和 10/20/40 都未满足“所有 workload × split 可区分”的绝对压力阈值，因此运行生成的 `freeze_candidate.status` 正确为 `not_freezable`。阶段 0 主配置暂不修改，`freeze_status.stage3_active_mechanism` 继续为 `pending`。

## 产物完整性

| 检查项 | 结果 |
|---|---:|
| `run_state.status` | `completed` |
| 独立 replay checkpoint | 132 |
| progress 中 `replay_completed` | 132 |
| 真实校准 wall time | 约 19 分 49 秒 |
| Reactive 结果 | 36 行 |
| Watermark 结果 | 54 行 |
| `b_max` 结果 | 54 行 |
| burst 统计组 | 108 |
| burst 原始窗口 | 280,800 行 |
| 顶层产物 SHA-256/size | 全部匹配 provenance |
| 本地 6 个原始 trace fingerprint | 全部匹配 provenance |
| 合法性与结束态全量不变量检查 | 全部通过 |
| 原始访问、迁移和 Cost 计数重算 | 无差异 |
| burst P50/P95/P99/max 重算 | 无差异 |
| 容量、水位、`b_max` 决策重算 | 与 `selection_decision.json` 完全一致 |

`stage3_validation.log` 中的 Traceback 是验收脚本故意提交 Test 条目并确认其被拒绝，不是实验失败。日志最终两次输出：

```text
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
```

## 数据边界与复现状态

- run id：`stage3-real-001`；
- 服务器基础 commit：`dfe47f1d52aaf034fbd919762bdad4e76bc4eae5`；
- 运行时 worktree：`dirty=true`，dirty fingerprint 已记录；
- 6 个输入均为 4 KiB 页面、真实 RW 列、Train/Validation 原始访问 trace；
- 总访问数：3,600,000；
- Test 使用：否；
- CAPD 使用：否；
- candidate filter：disabled。

数值产物本身完整，但运行来自 dirty worktree。推进正式冻结前应保存当前代码 diff 或提交当前实现；若要求最高等级的可复现 provenance，应从干净 commit 再运行一次并核对数值结果。

## Working Set

冻结候选定义：

```text
active_unique_pages_from_train_and_validation
```

| workload | Train unique | Validation unique | Union W | overlap | Train accesses | Validation accesses |
|---|---:|---:|---:|---:|---:|---:|
| canneal | 2,239 | 1,096 | 2,560 | 775 | 600,000 | 200,000 |
| dedup_pressure | 4,466 | 2,528 | 6,945 | 49 | 1,000,000 | 1,000,000 |
| streamcluster_pressure | 7,316 | 2,685 | 9,303 | 698 | 600,000 | 200,000 |

## Capacity 审计

### Validation 上的绝对容量与 Reactive-LRU 降级率

| workload | 10% pages/rate | 20% pages/rate | 40% pages/rate | 60% pages/rate |
|---|---:|---:|---:|---:|
| canneal | 256 / 0.6020% | 512 / 0.3520% | 1,024 / 0.0375% | 1,536 / 0% |
| dedup_pressure | 695 / 0.1844% | 1,389 / 0.1141% | 2,778 / 0% | 4,167 / 0% |
| streamcluster_pressure | 931 / 0.9040% | 1,861 / 0.4205% | 3,722 / 0% | 5,582 / 0% |

所有 workload × split 的四个压力指标均随容量单调变化，`ordered_indicators=4/4`，没有慢性耗尽；但两组 profile 都失败：

| profile | ratios | 结果 | 主要原因 |
|---|---|---|---|
| primary | 20/40/60 | fail | 多个 Validation 在 40/60% 已无降级；绝对 NVM/demotion range 未达到 5% |
| fallback | 10/20/40 | fail | 压力更强但仍未达到绝对 5% range；多数 run 的最大降级率仍低于 1% |

该失败不是文件损坏或非单调结果。当前 trace 的 NVM access rate 本身只有约 0.25%–1.37%，因此“最小绝对 range=5%”对这些 workload 不可达，“最大降级率低于 1% 即 near-no-migration”也会把低 admission base rate 的 workload 系统性判失败。这说明预声明容量门槛使用绝对比例时未适配 workload base rate。

### 容量结论

按冻结协议，不能事后调低阈值并把同一结果改判为通过。因此正式容量推荐保持 blocked。

若项目进度要求先给出工程候选，20% Working Set 是当前最有证据的默认点：

- 三个 Validation workload 在 20% 都产生非零降级压力；
- 20% 同时存在于两组 profile；
- 水位与 `b_max` 的 Proactive-LRU 矩阵覆盖了 20%；
- 40/60% 对 dedup 和 streamcluster 的 Validation 已基本无压力；
- 10% 只有 Reactive-LRU 压力结果，未完成对应的 Proactive-LRU 水位/批量矩阵。

因此 `dram_working_set_ratio=0.20` 只能标记为“条件工程默认”，不能标记为“通过预声明容量门槛的正式冻结值”。

## Burst

Validation、100-access 窗口的主要分位数：

| workload | profile/ratio | P50 | P95 | P99 | max |
|---|---|---:|---:|---:|---:|
| canneal | primary 20% | 0 | 4 | 7 | 13 |
| dedup_pressure | primary 20% | 0 | 1 | 7 | 10 |
| streamcluster_pressure | primary 20% | 1 | 2 | 3 | 7 |
| canneal | fallback 10% | 0 | 5 | 8 | 13 |
| dedup_pressure | fallback 10% | 0 | 1 | 7 | 10 |
| streamcluster_pressure | fallback 10% | 1 | 2 | 3 | 7 |

容量门槛未通过时实现按确定性兜底行为继续用 primary profile 产生水位矩阵，因此正式水位候选来自 primary Validation 的聚合 P50/P95/P99：1、4、7。

## Watermark

K=8 和 K=16 的汇总完全相同：

| candidate | F_low | F_target | legal | avg exhaustion | worst exhaustion | avg emergency | avg early reuse | avg demotions | cost/access | 决策 |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| Small | 1 | 2 | 是 | 205.11 | 762 | 102.44 | 0 | 307.33 | 1.020124 | 拒绝 |
| Medium | 2 | 4 | 是 | 0 | 0 | 0 | 0 | 308.00 | 1.020157 | 推荐 |
| Large | 4 | 7 | 是 | 0 | 0 | 0 | 0.000351 | 309.78 | 1.020224 | 备选 |

Small 虽然 Cost 略低，但出现 free-frame exhaustion 和 emergency fallback，按预声明选择顺序必须先淘汰。Medium 与 Large 都消除 exhaustion/emergency；Medium 的 early reuse、迁移量、NVM I/O、Cost 和保留水位更优，因此推荐：

```text
F_low = 2
F_target = 4
```

保守备选为 `(F_low=4, F_target=7)`，但当前数据没有显示其额外 reserve 能带来收益。

## b_max

默认 Medium 水位下，K=8 与 K=16 的结果相同：

| b_max | feasible | cost/access | avg NVM writes | avg early reuse | avg rounds | avg demotions | emergency | exhaustion | 决策 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 是 | 1.020157 | 406.33 | 0 | 308.00 | 308.00 | 0 | 0 | 第 3 |
| 2 | 是 | 1.020157 | 406.33 | 0 | 205.33 | 308.00 | 0 | 0 | 第 2 |
| 4 | 是 | 1.020157 | 406.33 | 0 | 102.67 | 308.00 | 0 | 0 | 推荐 |

三者的 Cost、写入、迁移和安全指标完全相同；`b_max=4` 将平均决策轮数相对 `b_max=1` 降低约 66.7%，因此推荐：

```text
b_max = 4
```

## K 代理不变性

- 代理值：8、16；
- K=8：Medium + `b_max=4`；
- K=16：Medium + `b_max=4`；
- 有主动轮次的 run 中实际候选数分别严格为 8 和 16；
- 每个 K 的 27 个水位 run 中，12 个有主动轮次、15 个因压力不足没有主动轮次；
- 代理 K 不进入正式 `method.candidate_size_K`。

预声明不变性规则通过，但证据主要来自 12 个真正触发主动循环的 run；不能据此把 K=8 或 K=16 冻结为正式候选数。

## 推荐配置

### 规则严格版本（正式推荐）

当前没有可完整冻结的阶段 3 配置：

```json
{
  "memory": {
    "dram_working_set_ratio": null,
    "working_set_definition": "active_unique_pages_from_train_and_validation"
  },
  "active_demotion": {
    "F_low": 2,
    "F_target": 4,
    "b_max": 4
  },
  "method": {
    "candidate_size_K": null
  },
  "freeze_status": {
    "stage3_active_mechanism": "pending"
  }
}
```

其中水位和 `b_max` 已形成有证据的冻结候选；容量比例仍是唯一阻塞项。

### 条件工程版本（若用户授权先推进）

```json
{
  "memory": {
    "dram_working_set_ratio": 0.2,
    "working_set_definition": "active_unique_pages_from_train_and_validation"
  },
  "active_demotion": {
    "F_low": 2,
    "F_target": 4,
    "b_max": 4
  },
  "method": {
    "candidate_size_K": null
  }
}
```

该版本的 20% 是工程默认，不是“容量门槛已通过”的正式结论。容量 sensitivity 可继续保留 10/20/40 作为诊断集合，但 10% 需要补 Proactive-LRU 水位/批量验证后才能与默认机制共同冻结。

## 方法学边界与 11 项谬误扫描

统计输出没有 p-value、置信区间或推断检验，本报告只解释确定性 replay 指标。

- Simpson、生态谬误：已按 workload/split 展开，未把 macro average 解释为每个 workload 都成立；
- Berkson/样本选择：三个代表 workload 的结论不能外推到未覆盖 workload，记为 CAUTION；
- collider：不适用；
- base-rate neglect：容量绝对阈值忽略 admission base rate，已发现，记为 CAUTION；
- regression-to-mean、survivorship：不适用；
- look-elsewhere、forking paths：候选和选择顺序运行前已声明；容量失败未事后改判；
- correlation/causation、reverse causality：未作因果或方向性统计声称。

覆盖：11/11。

## 下一门禁

在用户确认前：

- 不修改阶段 0 主配置；
- `stage3_active_mechanism` 保持 pending；
- Stage 4 candidate/training、Stage 7 workload、formal Test 继续 pending；
- 不声称 CAPD 优于外部 baseline；
- 不声称容量 profile 已通过正式压力门槛。

建议优先选择以下两条路径之一：

1. 严格路径：重新预声明相对压力规则（相对降级变化、相对 admission rate、非零默认压力），再运行容量校准；
2. 进度路径：用户明确接受 20% 为条件工程默认，写入 `F_low=2, F_target=4, b_max=4`，并在论文/报告中如实保留容量门槛未通过的限制。
