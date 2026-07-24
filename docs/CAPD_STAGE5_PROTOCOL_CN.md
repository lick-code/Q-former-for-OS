# CAPD 阶段5：端到端主实验与组件消融协议

状态：`STAGE5_VERIFIED`

## Material Passport

- 合同：`CAPD-MIC-1.0`，文档修订 `R1`
- schema：`capd_finals_v3_0`
- run profile / artifact class：`official / official`
- 前置门槛：阶段0—4均已通过；G11保留 `REVIEW_REQUIRED`
- 主指标：`weighted_access_cost`
- test职责：仅最终闭环回放；不用于selector、标签、结构、默认参数或checkpoint选择

## 1. 实现架构

统一入口为 `scripts/run_capd_stage5.py`，支持：

- `audit-inputs`：审计阶段4的9个Full checkpoint、G11/G12结果及阶段2/3输入；
- `plan`：生成固定job DAG和 `execution_plan.json`；
- `main`：运行CAPD与LRU/Random/LFU/CLOCK公平闭环；
- `learned-baselines`：审计并隔离运行Kleio-lite/PatternS-lite；
- `ablations`：生成隔离JSONL、重新训练并按seed回放；
- `sensitivity`：执行预注册B/K/H/Hc/L网格；
- `summarize`：执行seed完整性、公平性、配对统计、macro/micro标签和污染检查；
- `all`：按上述依赖顺序执行。

核心复用关系：

- `finals_config`继续负责合同、配置及工件指纹；阶段5只开放预注册变体通道，Full加载器仍保持冻结拒绝；
- `finals_generator`、`candidate_filter`继续生成统一决策快照和JSONL；
- `qmap_train`继续负责正式训练、train-only词表和valid-only checkpoint选择；
- `qmap_eval`及 `ReplayStats`继续负责所有策略的闭环状态与成本记账；
- `stage5_variants`冻结变体唯一差异和身份；
- `stage5_results`执行统计与污染门禁。

## 2. 正式主实验矩阵

每个workload均使用相同test fingerprint、D=64、空DRAM、无界NVM后备、page_shift、RW语义和固定成本模型。

| 策略 | 每workload运行 | 三个workload合计 |
|---|---:|---:|
| CAPD | 3个阶段4checkpoint seed：3136859、42、2026 | 9 |
| Random | 3个独立回放seed：0、1、2 | 9 |
| LRU | 1 | 3 |
| LFU | 1 | 3 |
| CLOCK | 1 | 3 |
| 合计 | 9 | 27 |

不得选择best seed。CAPD报告三seed原始值、均值、样本标准差、最小值和最大值；Random同样报告三回放seed的波动。改善率固定为：

```text
(baseline_cost - capd_cost) / baseline_cost * 100
```

正值代表CAPD降低成本，负值代表CAPD退化。逐workload分别对LRU、Random均值、LFU、CLOCK及最低成本外部基线报告。

## 3. 外部学习基线公平边界

Kleio-lite和PatternS-lite只有在以下绑定全部成立并完成隔离训练/回放时才进入结果表：同源train/valid/test、训练只读train、test仅最终回放、相同D/初始状态/成本、workload绑定checkpoint、闭环推进自身状态、无test调参、明确标记lite。

`learned_baseline_comparability.json`逐策略、逐workload记录每项条件。一个lite策略只有在三个workload均完成可比的隔离训练和回放后才进入主表；覆盖不完整时整项排除，已完成行也不与必需基线混表。未运行者标为 `ELIGIBLE_NOT_RUN`，不可比策略记录具体失败条件。任何排除都不阻塞四个必需传统基线。

## 4. 核心组件消融

所有核心消融使用Full相同test和成本，并为3136859、42、2026三个模型seed重新训练。

| variant_id | 唯一差异 |
|---|---|
| `no_filter_B8_K8` | B=K=8，P_t=C_t，显式绕过B到K筛选；与sensitivity_B8共享工件 |
| `selector_drop_Delta/A/W/C/R` | 使用阶段3 B=64冻结LOO权重，被移除特征权重为0 |
| `no_position_encoding` | Transformer前不添加位置编码；仅阶段5加载器接受 |
| `no_candidate_state` | 四维candidate state统一置零，保留候选page embedding |
| `history_mean_pool` | Transformer历史编码后masked mean；不调用candidate-to-history Cross-Attention |
| `no_future_write` | lambda_w=0，标签为d_hat+q_hat，L不变 |

Full冻结selector已是均匀 `(0.2,0.2,0.2,0.2,0.2)`，因此“均匀selector”只生成 `degenerate identity control`，验证身份与候选集合等价，不复制Full结果，不作为独立性能证据。

配对统计固定按相同模型seed计算 `variant_cost - full_cost`，并报告逐seed delta及均值、样本标准差、min/max。缺少任何核心seed硬失败，pilot与official不能混表。

## 5. 参数敏感性预注册网格

| 维度 | 网格 | 其他固定值 |
|---|---|---|
| B | 8,16,32,64 | K=8 |
| K | 4,8,16 | B=64 |
| H | 5,10,20 | B=64,K=8,Hc=256,L=256 |
| Hc | 64,128,256,512 | B=64,K=8,H=10,L=256 |
| L | 64,128,256,512 | B=64,K=8,H=10,Hc=256 |

默认点B64/K8/H10/Hc256/L256复用Full；B8复用 `no_filter_B8_K8`，不重复生成证据。其余12个非默认点先用canonical seed=3136859，标为 `single_seed_sensitivity`。若改变论文主结论，必须将 `needs_seed_confirmation=true` 并补跑42、2026；不得据test敏感性改动默认值。

## 6. Job数量与资源规模

- 主实验回放：27 jobs；
- uniform identity control：3 jobs；
- 核心消融：30数据生成 + 90训练 + 90回放 = 210 jobs；
- 额外敏感性：36数据生成 + 36训练 + 36回放 = 108 jobs；
- required逻辑job总数：348；
- 可选学习基线：2策略 × 3 workload × 训练/回放 = 12 jobs。

训练job需要单GPU；默认服务器脚本顺序训练，避免显存争抢。数据生成及传统/学习基线回放以CPU和内存为主。每个job使用原子manifest、真实退出码、单写者目录和无自动重试的续跑语义。

## 7. 统计与阶段4边界

先逐workload报告；跨workload只允许明确标记的unweighted macro improvement与total-cost micro aggregation。三个workload不做滥用显著性检验，三个模型seed不作为独立workload样本。

`stage4_boundary_crosswalk.csv`并列展示G11偏移严重程度、CAPD跨seed成本波动和相对最低成本外部基线的变化，仅作描述性关联，不声称因果，不触发闭环再训练。

## 8. 正式输出

- 主实验：`outputs/results/finals_v3_official/stage5_main/`
- 消融JSONL：`dataset/jsonl/finals_v3_official/stage5_ablation/<variant>/<workload>/`
- 消融checkpoint：`outputs/checkpoints/finals_v3_official/stage5_ablation/<variant>/<workload>/seed_<seed>/`
- 消融结果：`outputs/results/finals_v3_official/stage5_ablation/`
- 敏感性：`dataset/jsonl/finals_v3_official/stage5_sensitivity/`、`outputs/checkpoints/finals_v3_official/stage5_sensitivity/`、`outputs/results/finals_v3_official/stage5_sensitivity/`

服务器正式矩阵已完成348/348个required job并通过统一验收；阶段6启动门槛
已经满足。阶段5结果仍须遵守本协议中的适用边界，不得用test反向修改冻结方法。
