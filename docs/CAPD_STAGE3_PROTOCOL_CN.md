# CAPD 阶段3候选筛选器独立验证协议

## 1. 身份与状态

- 合同：`CAPD-MIC-1.0`，文档修订 `R1`
- 输入 schema：`capd_finals_v3_0`
- 运行/工件身份：`official/official`
- 阶段0：`DONE_R1`
- 阶段1：`STAGE1_R1_VERIFIED`
- 阶段2：`VERIFIED_REUSABLE`
- 当前阶段3：`STAGE3_VERIFIED`（2026-07-22 Linux 服务器完整验收通过）

阶段3只独立验证轻量候选筛选器的覆盖行为，不训练精排模型、不运行 QMAP/CAPD test replay、不生成 checkpoint、不比较 LRU、Random、LFU、CLOCK，不报告端到端命中率或加权代价结论。

## 2. 唯一输入与硬门禁

固定 workload 为 `canneal`、`streamcluster_pressure`、`dedup_pressure`，固定 `B={8,16,32,64}`，所有实验固定 `K=8`。每个 workload/B 只读取：

```text
dataset/jsonl/finals_v3_official/<workload>/B<B>/
  resolved_config.json
  selector_params.json
  selector_validation_samples.jsonl
  generator_summary.json
```

其中分析数值只来自 `selector_params.json` 和 `selector_validation_samples.jsonl`；配置和生成摘要只用于身份、指纹、来源与阶段2审计复核。程序不打开 test trace、`train.jsonl`、`valid.jsonl` 或 checkpoint。

任一组存在以下情况即硬失败，并且不得进入跨 workload/B 汇总：

- 合同、schema、run profile、artifact class、workload 或目录 B 不匹配；
- `retained_K!=8`、`Hc!=256`、`L!=256`、`epsilon_y!=1e-8`；
- validation strategy 不是 `independent_valid_trace`；
- Recall 并列语义不是 `any_hit`，网格步长不是0.1，冻结网格不是1001点；
- selector、validation samples、resolved config、generator summary 指纹链不匹配；
- validation samples 未绑定独立 valid trace，行身份、形状、原始 LRU rank 或决策点不合法；
- v2、smoke 或 smoke-only 工件混入。

## 3. 指标与分母

- `PoolRecall@B`：`P_t` 是否命中全 DRAM 并列最优集合。
- `SelectorRecall@K`：`C_t` 是否命中 `P_t` 中任一并列最优页面，采用 any-hit。
- `EndToEndRecall@K`：`C_t` 是否命中全 DRAM 并列最优集合。
- `TieCoverage@K`：`C_t` 覆盖 `P_t` 并列最优集合的比例。
- `NRegret`：`P_t` 最佳相关性与 `C_t` 最佳相关性的归一化差距。

`SelectorRecall@K` 和 `NRegret` 只以 `R_t^y>epsilon_y` 的有效决策点为分母；`PoolRecall@B`、`EndToEndRecall@K` 和 `TieCoverage@K` 以全部完整未来窗口决策点为分母。每组同时报告 `total_complete_decision_points`、`effective_decision_points`、`nondiscriminative_ratio`、`mean_oracle_size`、`unique_oracle_ratio` 和 `fallback_uniform`。所有指标来源固定标记为 `valid_trace`，不同分母不得混成未标记总体比例。

## 4. Full、single-feature 与 leave-one-out

五个特征顺序固定为 `Delta,A,W,C,R`：`Delta` 是最近访问距离，`A` 是近期访问次数的反向特征，`W` 是近期写次数的反向特征，`C` 表示 clean 状态，`R` 表示原始 LRU 位置。

1. Full：重新计算五维非负、和为1、步长0.1的完整1001点网格；选择顺序固定为 `SelectorRecall@K` 降序、`NRegret` 升序、到 uniform 的平方距离升序、权重元组字典序。复算最优权重、五个指标、统计量和 fallback 必须与阶段2冻结 selector 一致，否则硬失败。
2. Single-feature：直接评价五个 one-hot 权重，不重搜。
3. Leave-one-out：每次将一个特征权重固定为0，在其余四维上重搜非负、和为1、步长0.1的286点子网格，沿用 Full 的四级选择规则；不得把 Full 权重删除后归一化。

每个消融报告相对 Full 的 `Delta SelectorRecall@K`、`Delta EndToEndRecall@K`、`Delta TieCoverage@K` 和 `Delta NRegret`。`PoolRecall@B` 与 selector 权重无关，只按 workload/B 报告一次，不把 PoolRecall 变化归因于特征消融。

## 5. B sweep 机械性检查

- K 始终为8。
- B=8 时 `P_t=C_t`；若存在有效点，`SelectorRecall@K=1`；`EndToEndRecall@K=PoolRecall@B`；`NRegret=0`。
- 相同 workload 的决策点集合必须对齐，较小 B 的 `P_t`、原始 rank 和全局 oracle mask 必须是 B=64 的前缀。
- 原样报告 PoolRecall；若不单调，保留异常并报告输入/决策点对齐诊断，不修改数据、指标或过滤样本。
- SelectorRecall、EndToEndRecall 和 NRegret 不要求随 B 单调。
- 明确报告 B=8 到 B=64 的 PoolRecall 绝对增量，并根据实际结果回答扩大观察范围是否提高覆盖。

## 6. 入口与输出

统一入口：

```bash
python scripts/run_capd_stage3_selector.py \
  --repo-root "$REPO" \
  --artifact-root dataset/jsonl/finals_v3_official \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --pool-sizes 8 16 32 64 \
  --output outputs/results/finals_v3_official/stage3_selector
```

加 `--audit-only` 时只审计12组输入，不搜索、不写结果。正式输出目录为 `outputs/results/finals_v3_official/stage3_selector/`，包含：

- `stage3_summary.json`
- `stage3_metrics.csv`
- `stage3_ablation.csv`
- `stage3_report.md`
- `input_audit.json`
- `details/<workload>_B<B>.json` 共12份

结果记录 schema、合同、workload、B/K、输入路径和 SHA-256、配置/selector/sample 指纹、代码 commit、完整命令、指标分母、搜索规则、fallback 和运行状态。先按 workload/B 报告；额外 macro average 明确标记为三个 workload 的不加权宏平均，不生成未标记 micro average。
