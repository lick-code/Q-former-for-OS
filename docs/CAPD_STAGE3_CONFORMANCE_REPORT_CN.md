# CAPD 阶段3符合性报告

## 1. 最终状态

状态：`STAGE3_VERIFIED`

- 验收日期：2026-07-22
- 验收环境：Linux 服务器，仓库 `/home/likc/Q-former-for-OS`
- 验收代码：`0e51d8193fdf94342faca29e7ca1ed2ef89a6880`
- 服务器证据目录：`/tmp/capd-stage3-acceptance.MnWUnu`
- 最终标志：`[FINAL] STAGE3_VERIFIED`
- 总退出码：`[RC] overall=0`
- 正式输出：`outputs/results/finals_v3_official/stage3_selector/`

阶段3统一入口、硬门禁、Full复算、single-feature、leave-one-out、B sweep、输出制品及污染检查均已通过服务器验收。正式生成制品中的 `STAGE3_IMPLEMENTED_UNVERIFIED` 是进入外层验收前记录的运行时状态；制品生成后未被手工改写。本符合性报告依据外层验收日志完成阶段关闭，并作为 `STAGE3_VERIFIED` 的状态记录。

## 2. 动态验收结果

| 验收项 | 结果 | 退出码/数量 |
|---|---|---:|
| 阶段3针对性测试 | 通过 | `21 passed in 0.65s`，RC=0 |
| 完整pytest | 通过 | `108 passed, 2 skipped in 2.41s`，RC=0 |
| official输入审计 | 通过 | 12/12，RC=0 |
| Full 1001点重搜 | 通过 | 12/12与阶段2冻结selector一致 |
| single-feature | 通过 | 60/60 |
| leave-one-out 286点重搜 | 通过 | 60/60 |
| B=8机械性不变量 | 通过 | 3/3 workload |
| 正式阶段3分析 | 通过 | 12/12，RC=0 |
| `git diff --check` | 通过 | RC=0 |
| 阶段2工件前后SHA-256 | 完全一致 | RC=0 |
| 非预期工作区污染 | 无 | RC=0 |
| 非预期checkpoint | 无 | RC=0 |

输入审计覆盖合同/schema/profile/artifact class/workload/B/config/selector/sample/summary指纹链，并确认所有样本来自 `independent_valid_trace`。分析入口未读取 test trace、精排 train/valid JSONL 或 checkpoint，未运行训练或QMAP/CAPD闭环回放。

## 3. 输出制品复核

正式输出已经同步回本地并完成结构复核：

- `stage3_summary.json`；
- `stage3_metrics.csv`：132行，包含12个Full和120个single/leave-one-out结果；
- `stage3_ablation.csv`：120行；
- `stage3_report.md`；
- `input_audit.json`：状态 `PASSED`，审计12组输入；
- `details/<workload>_B<B>.json`：12份。

结果schema为 `capd_finals_v3_stage3_selector_1`，输入schema为 `capd_finals_v3_0`，合同为 `CAPD-MIC-1.0`，指标来源均标记为 `valid_trace`。每组结果记录配置、selector、validation samples和generator summary的路径及SHA-256，并记录代码commit与完整命令。

## 4. B sweep与筛选能力

| workload | B | PoolRecall@B | SelectorRecall@K | EndToEndRecall@K | TieCoverage@K | NRegret |
|---|---:|---:|---:|---:|---:|---:|
| canneal | 8 | 1 | 1 | 1 | 1 | 0 |
| canneal | 16 | 1 | 1 | 1 | 0.500010016628 | 0 |
| canneal | 32 | 1 | 1 | 1 | 0.256512952798 | 0 |
| canneal | 64 | 1 | 1 | 1 | 0.162966096134 | 0 |
| streamcluster_pressure | 8 | 1 | 1 | 1 | 1 | 0 |
| streamcluster_pressure | 16 | 1 | 1 | 1 | 0.501786214255 | 0 |
| streamcluster_pressure | 32 | 1 | 1 | 1 | 0.252160378582 | 0 |
| streamcluster_pressure | 64 | 1 | 1 | 1 | 0.138475866720 | 0 |
| dedup_pressure | 8 | 1 | 1 | 1 | 1 | 0 |
| dedup_pressure | 16 | 1 | 1 | 1 | 0.499974880683 | 0 |
| dedup_pressure | 32 | 1 | 1 | 1 | 0.250102191782 | 0 |
| dedup_pressure | 64 | 1 | 1 | 1 | 0.135632920476 | 0 |

三个workload的决策点集合和候选池前缀均正确对齐，PoolRecall随B非递减。B=8到B=64的PoolRecall绝对增量均为0，因此在这三个valid trace上，扩大观察范围没有进一步提高“是否命中全DRAM并列最优集合”的覆盖率；原因是B=8时PoolRecall已经达到1，不能据此声称更大的B无效于其他分布或系统指标。

固定 `K=8` 时，12组Full结果的 `SelectorRecall@K=1`、`EndToEndRecall@K=1`、`NRegret=0`，说明筛选后的 `C_t` 始终保留至少一个池内并列最优页面且没有最佳相关性遗憾。`TieCoverage@K` 随B增大而下降，表示K固定时对更大并列最优集合的覆盖比例降低；它与any-hit Recall语义不同，不构成上述Recall结果的矛盾。

## 5. 权重稳定性与特征消融

三个workload在 `B={8,16,32,64}` 下均选择 `(0.2,0.2,0.2,0.2,0.2)`，相邻B最大L1距离均为0，且没有发生 `fallback_uniform`。这里的均匀权重是四级确定性搜索选出的最优网格点，不是“全部样本无区分”触发的fallback。

leave-one-out相对Full出现退化的组合数为：

- canneal：10组；
- streamcluster_pressure：3组；
- dedup_pressure：0组。

五个one-hot单特征结果、每个leave-one-out的重选权重及相对Full的四项绝对变化均记录在 `stage3_metrics.csv`、`stage3_ablation.csv` 和12份detail JSON中。PoolRecall与selector权重无关，没有将其变化归因于任何特征消融。

## 6. 结论边界

阶段3已经回答扩展候选池覆盖、固定K下的筛选保留、五个特征行为、leave-one-out变化以及权重稳定/fallback问题。该阶段只验证冻结valid trace上的候选覆盖行为，不训练精排模型，不比较LRU、Random、LFU或CLOCK，也不证明系统命中率、加权代价或端到端性能改善。

因此阶段3正式关闭为 `STAGE3_VERIFIED`，阶段2继续保持 `VERIFIED_REUSABLE`，不需要修改或重新生成任何阶段2工件。
