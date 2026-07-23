# CAPD 方法—实现合同

## Material Passport

- 合同编号：`CAPD-MIC-1.0`
- 文档修订：`R1`（兼容性勘误修订）
- 目标实现模式：`official`
- 目标工件模式：`capd_finals_v3_0`
- 冻结日期：2026-07-20
- 修订日期：2026-07-22
- 合同状态：`FROZEN`
- 实现状态：`STAGE1_R1_VERIFIED`（G01--G10、G13 均已完成服务器验收）
- 数据状态：`STAGE2_VERIFIED_REUSABLE`（R1 不改变 trace、split、标签、selector 或 JSONL 内容语义）
- 阶段状态：阶段3 `STAGE3_VERIFIED`；阶段4 `STAGE4_VERIFIED`；阶段5启动门槛已满足
- 实证状态：`UNVERIFIED`（本合同冻结方法与验收口径，不代表实验已经证明方法有效）
- 来源：2026-07-20 中文 CAPD 完整方法稿、2026-07-22 更新稿、当前仓库代码与配置审查

## 1. 合同地位与适用范围

本合同把当前 CAPD 方法转换为可以落实到配置、代码、数据工件和测试断言的实现规范。正式代码、正式数据和正式实验必须遵守本合同。

若中文方法稿、配置默认值和代码行为之间发生冲突，在中文方法稿完成同步修订前，以本合同中标记为“冻结”的定义为准。任何改变冻结语义的修改都必须提升合同版本，并重新生成受影响的数据、检查点和实验结果。

R1 的修订分类为“兼容性勘误”，不提升合同编号或工件 schema。2026-07-22 更新稿没有改变特征、标签、损失、数据切分、未来窗口、候选预算或工件字段，只进一步明确了决策快照时序、候选筛选并列顺序、精排输出并列顺序以及完整未来窗口的适用集合。其中前述快照时序、候选筛选顺序和完整窗口规则已经由原合同冻结并由现有实现覆盖；R1 新增的唯一实现缺口 G13“精排最高分并列时按决策前原始 LRU 顺序选择最老页面”已经完成代码补齐和服务器验收。该修订不改变阶段2 已生成 selector/JSONL 的内容，因此阶段2数据与工件继续使用，阶段3启动门槛已经满足。

本合同仅覆盖当前 CAPD 方法：

- 从 DRAM LRU 尾部构造大小至多为 `B` 的扩展候选池；
- 使用五维轻量历史元数据从 `B_t` 个页面筛选出 `K_t` 个页面；
- 使用近期访存上下文和候选页状态对 `K_t` 个页面进行精排；
- 在 DRAM 容量压力触发时选择一个页面从 DRAM 降级至 NVM；
- 按工作负载独立确定筛选器参数并训练精排模型。

本合同不把 CAPD 描述为完整的页面放置或双向迁移系统，也不主张当前代理标签等价于全局最优系统代价。

## 2. 冻结后的端到端决策时序

对访问时刻 `t`，正式回放必须按以下顺序执行：

1. 读取当前请求的 `page_id`、`pc` 和 `rw`。请求在此时已经可观测。
2. 若请求页位于 DRAM，按读写类型记录 DRAM 访问代价，更新页面修改状态、LRU 顺序和历史窗口；不触发页面降级。
3. 若请求页不在 DRAM，按读写类型记录一次 NVM 访问。所有 trace 中出现的页面在回放开始时都被视为由 NVM 后备，因此首次访问也属于 NVM 访问。
4. 若 DRAM 尚有空位，将请求页提升至 DRAM，再更新驻留状态、修改状态、LRU 顺序和历史窗口；不触发 victim 选择。
5. 若 DRAM 已满，在请求页插入 DRAM 之前冻结决策快照：
   - 候选筛选特征只使用 `t` 之前已经完成状态更新的历史；
   - 候选页驻留状态和 LRU 位置均为请求页插入前状态；
   - 当前请求进入精排模型的长度为 `H` 的上下文窗口，但不进入候选筛选历史统计；
   - 从当前 DRAM LRU 最久未访问端构造 `P_t`，完成 `B_t -> K_t` 筛选和精排；筛选得分并列时保留原始 LRU 顺序中更靠近最久未访问端的页面；
   - 将精排得分最高的页面降级至 NVM；若最高分并列，选择决策前原始 LRU 顺序中最久未访问的页面，不得依赖筛选得分排序后的候选张量位置；随后记录一次固定迁移代价，dirty 状态不额外增加一次 NVM 写入；
   - 将当前请求页插入 DRAM，然后更新驻留状态、修改状态、LRU 顺序和两个历史窗口。
6. 训练样本生成、验证样本生成、测试回放和在线模拟必须复用同一决策快照构造函数，禁止复制出语义不同的第二套实现。

## 3. 冻结的逻辑口径

### 3.1 工作负载应用边界

- 每个工作负载 `omega` 独立计算 `c_Delta,omega`、`c_A,omega`、`c_W,omega` 和 `w*_omega`。
- 每个工作负载独立训练一个上下文精排模型及页面词表。
- 筛选参数、页面词表和模型检查点只能用于相同工作负载的 valid/test trace。
- 正式主实验不宣称跨工作负载泛化。跨工作负载迁移只能作为独立扩展实验，不能与工作负载内正式结果混用。
- 工件必须记录 `workload_id`，加载时不匹配即拒绝执行。

### 3.2 正式训练、验证和测试划分

正式模式冻结为 `independent_valid_trace`：

- `train_trace`：只用于计算特征截断值、在筛选器冻结后生成精排训练样本和拟合模型参数；
- `valid_trace`：只用于筛选权重网格搜索、模型选择、早停和超参数选择；
- `test_trace`：只用于最终闭环回放和结果报告；
- 三个 trace 必须在来源和时间范围上互不重叠；任何 test 信息都不得用于截断值、权重、词表、模型或阈值选择。

当前 `train_trace_decision_holdout` 仅保留为 `development/smoke` 备用模式。由该模式产生的检查点和结果必须标记为 `smoke_only`，不得进入正式表格、正式结论或系统效果比较。

### 3.3 未来窗口与尾部样本

未来窗口严格定义为：

```text
F_t = {t+1, t+2, ..., t+L}
```

若 trace 长度为 `N`，只有满足下式的决策点才允许生成筛选器验证标签或精排训练/验证标签：

```text
t + L < N
```

也就是必须真实存在完整的 `L` 条未来访问。尾部不足 `L` 的决策点直接丢弃，不得截断窗口后仍使用固定分母 `L` 计算标签，也不得改用较短分母。

该规则适用于 train 和 valid 的所有标签生成。test 闭环回放不生成未来标签，因此保留全部访问和全部实际降级决策。

在 selector 权重搜索的 valid 决策点上，必须为扩展候选池 `P_t` 中的全部页面构造 `y_t(i)`，以定义池内最优集合、筛选覆盖率和 NRegret；在精排 train/valid JSONL 中，只需为筛选后的有效候选集合 `C_t` 构造并保存训练标签。两条路径都必须服从相同的完整未来窗口门禁。

### 3.4 初始驻留与首次访问记账

正式 Trace Replay 的初始状态冻结为：

```text
DRAM = empty
NVM  = all pages referenced by the trace, conceptually
NVM capacity = unbounded
```

因此：

- 页面首次出现且尚未进入 DRAM时，按一次 NVM read/write 记账；
- 首次访问后，页面按统一准入规则提升至 DRAM；
- 若 DRAM 已满，先选择并降级 victim，再插入当前页面；
- 不单独建模磁盘、缺页中断或“尚未分配”代价；
- `nvm_pages` 可以采用显式全集或隐式后备实现，但两种实现的访问计数和加权代价必须完全相同。

### 3.5 LRU 位置定义

扩展候选池按“最久未访问到相对最近访问”排列，并定义：

```text
rho_LRU(i) = 0                 表示池中最久未访问页面
rho_LRU(i) = B_t - 1           表示池中相对最近访问页面
R_LRU(i) = 1 - rho_LRU(i) / max(B_t - 1, 1)
```

该定义同时用于轻量筛选器和精排候选页四维状态。因此越靠近 LRU 最久未访问端，`R_LRU` 越大。精排阶段不得改用 `rho_LRU/max(B_t-1,1)`，不得根据筛选后的 `K_t` 重新编号。

### 3.6 Recall 并列语义与两阶段覆盖率

定义：

```text
O_t^D = argmax_{i in D_t} y_t(i)       # 当前全部可降级 DRAM 页中的并列最优集合
O_t^P = argmax_{i in P_t} y_t(i)       # 扩展候选池中的并列最优集合
```

正式指标冻结为：

```text
PoolRecall@B
  = mean_t I[P_t intersects O_t^D]

SelectorRecall@K
  = mean_t I[C_t intersects O_t^P]

EndToEndRecall@K
  = mean_t I[C_t intersects O_t^D]

TieCoverage@K
  = mean_t |C_t intersects O_t^P| / |O_t^P|
```

其中 `SelectorRecall@K` 采用“任意命中”语义：只要 `K_t` 个保留页面中包含任意一个并列最优页面，该决策点就记为 `1`，否则为 `0`。当前实现采用的“命中的并列最优页数量除以并列集合大小”属于 `TieCoverage@K`，不得再命名为 `Recall@K`。

`NRegret` 仍按扩展候选池最佳相关性与筛选后最佳相关性之差计算，并只在 `R_t^y > epsilon_y` 的有效决策点上统计。

#### 3.6.1 候选筛选与最终精排的确定性并列顺序

候选筛选和最终 victim 选择采用两套相互独立的并列规则：

```text
selector TopK:
  selector_score 降序 -> original_pool_rank 升序

reranker victim:
  reranker_score 降序 -> original_pool_rank 升序
```

- `original_pool_rank=0` 表示决策前扩展候选池中最久未访问的页面；同一候选池内该排名唯一，因此足以确定单值结果。
- selector 的并列规则只决定哪些页面进入 `C_t`，不得作为精排分数并列时的隐式次序。
- 精排必须先排除 `candidate_mask=0` 的 padding，再在所有取得相同最高精排分数的有效候选中选择 `original_pool_rank` 最小者。
- “相同最高分”按模型完成全部正式分数修正后的实际数值精确相等判定，不额外引入未写入配置的 epsilon；任何有效候选分数为 NaN/Inf 时必须硬失败。
- 实现不得直接假设 `torch.argmax` 返回的首个候选就是 LRU 最老页面，因为正式候选张量按 selector 排序，未按原始 LRU 排序。

### 3.7 页面标识嵌入

历史访问页面和候选页面必须使用同一页面级标识和同一可学习页面嵌入表：

```text
page_id = physical_address >> page_shift
e_m(history_page_id) and e_m(candidate_page_id) share parameters and vocabulary
```

正式模式冻结为：

- 页面词表只使用当前工作负载的 train trace 拟合；
- 页面词表完成拟合后立即冻结；
- valid/test/在线回放中的未见页面统一映射到 `UNK=0`；
- 禁止在验证或测试前向过程中动态扩充词表；
- 页面词表、`UNK` 规则和嵌入权重必须写入检查点并参与指纹校验；
- PC 使用独立的训练集词表，读写标志继续使用二值嵌入。

JSONL 中历史页面字段应改为无歧义的 `history_page_ids`；旧字段 `physical_address` 不再作为正式页面嵌入输入。

### 3.8 位置编码

历史访问序列在进入单层 Transformer 前必须加入固定正弦位置编码：

```text
X_t_tilde = X_t + P_sinusoidal
```

位置索引按历史窗口从旧到新固定为 `0..H-1`。位置编码不参与训练，但必须随输入张量移动到相同 device/dtype。padding 位置不得产生有效注意力贡献。

### 3.9 LRU 行为策略与闭环分布

- 筛选器训练统计、筛选器验证样本和精排训练/验证样本的状态转移由 LRU 行为策略驱动。
- LRU 只负责离线样本状态推进，不参与 CAPD 正式测试阶段的 victim 选择。
- 所有候选权重必须在同一批预生成 valid 决策快照上比较，网格搜索不得反过来改变 valid 的状态转移。
- CAPD 正式测试必须闭环推进自身选择造成的 DRAM/NVM 和 LRU 状态。
- 正式实验必须报告 LRU 离线样本与 CAPD 闭环状态之间的分布偏移诊断；该诊断是方法适用边界证据，不得省略。

闭环分布诊断至少覆盖五个筛选特征、四个精排状态特征、`B_t/K_t`、dirty 比例和决策间隔。每个连续特征至少报告训练分布与闭环分布的分位数、KS 统计量或等价分布距离。

### 3.10 代理标签与真实系统代价

代理标签保持当前定义：

```text
d_hat(i) = first future reuse distance / L; no reuse gives 1
q_hat(i) = 1 - min(future access count / L, 1)
w_hat(i) = min(future write count / L, 1)
y(i)     = d_hat(i) + q_hat(i) - 4 * w_hat(i)
```

`y(i)` 的语义是离线参考相关性，不是已经证明的真实系统代价。论文和报告中只能表述为“代理目标”或“参考排序目标”。

正式实验必须增加标签一致性审计：在抽样决策点克隆状态，分别强制每个候选页作为首次 victim，并在后续 `L` 条访问中使用固定 LRU 延续策略，计算加权回放代价 `J_t^L(i)`。至少报告：

- `Spearman(y_t(i), -J_t^L(i))`；
- 代理标签 top-1 与最低真实窗口代价候选的一致率；
- 以 `-J_t^L(i)` 为相关性的 NDCG；
- 去除写风险项和改变 `(lambda_1, lambda_2, lambda_3)` 时的组件消融。

该审计用于验证代理目标的合理性，不允许用 test trace 的审计结果重新选择标签权重。

### 3.11 ApproxNDCG

近似排名严格定义为：

```text
rho(i) = 1 + sum_{j != i} sigmoid(alpha * (r(j) - r(i)))
alpha = 10
```

自身比较 `j=i` 必须排除，padding 候选也必须排除。相关性在当前有效候选集合内部执行 min-max 归一化，损失为批内有效样本 `-NDCG` 的均值。

## 4. 方法符号—配置—代码—测试映射

下表中的“目标配置字段”是下一阶段代码修改必须落实的字段名。当前 `capd_finals_v2_1` 配置不得直接改写后继续冒充相同 schema；目标实现应使用 `capd_finals_v3_0`。

| 合同项 | 方法符号/取值 | 目标配置字段 | 主要代码落点 | 必须存在的测试断言 |
|---|---|---|---|---|
| 合同版本 | `CAPD-MIC-1.0`，文档修订 `R1` | `contract.id` | `qmap/finals_config.py` | 配置、JSONL、检查点、结果的合同ID一致；R1不改变工件ID |
| DRAM容量 | `D=64`（当前正式配置） | `memory.dram_capacity_pages` | replay/generator | 超容量时才触发victim |
| NVM容量 | 无界 | `memory.nvm_capacity_pages=null` | `qmap/qmap_eval.py` | 不因NVM容量触发淘汰 |
| 初始驻留 | 全部页面NVM后备 | `replay.initial_residency=all_trace_pages_in_nvm` | `qmap/qmap_eval.py` | 首次读/写分别计NVM读/写 |
| 扩展池 | `B_t=min(B,|D_t|)` | `candidate.pool_size_B` | `candidate_filter.build_candidate_pool` | oldest-first、无padding |
| 精排预算 | `K_t=min(K,B_t)` | `candidate.retained_K` | `select_from_pool_records` | 大小和mask一致 |
| 筛选历史 | `H_c=256` | `candidate.selector_history_Hc` | `SelectorHistory` | 当前触发请求不进入筛选快照 |
| 精排历史 | `H=10` | `history.transformer_H` | generator/eval/model | 当前触发请求是最后一个token |
| 未来窗口 | `L=256` | `labels.future_lookahead_L` | `FutureOracle`、generator | 仅完整L窗口生成标签 |
| 驻留尺度 | `L_res=256` | `features.residency_scale_Lres` | candidate state | 与`L`分别校验 |
| 筛选截断 | train的0.99分位数，最小1 | `features.selector_clip_quantile=0.99` | `selector_search.clipping_values` | valid/test不改变截断值 |
| 筛选权重 | 五维非负、和为1、步长0.1，共1001组 | `selector.grid_step=0.1` | `selector_search.weight_grid` | 精确1001组且可复现 |
| 无区分样本 | `R_t^y <= epsilon_y` 排除 | `selector.epsilon_y` | selector search | 全部无区分时退化为均匀权重 |
| 权重选择 | Recall降序、NRegret升序、距均匀向量、字典序 | 固定规则 | `weight_choice_key` | 四级确定性顺序 |
| selector并列 | 筛选分数降序、原始LRU rank升序 | `candidate.selector_tie_break=lru_oldest`（代码冻结值） | `select_from_pool_records` | 同分时选原始rank更小页面，page ID不改变结果 |
| 并列Recall | any oracle hit | `metrics.selector_recall_tie=any_hit` | `evaluate_weight_batch` | 命中任意并列最优页即为1 |
| LRU位置 | `1-rank/max(B_t-1,1)` | `features.lru_direction=oldest_is_one` | selector + candidate state | rank 0为1，rank `B_t-1`为0 |
| 页面嵌入 | history/candidate共享 | `embedding.page.shared=true` | `embed.py`、train/eval/model | 相同page_id查到同一嵌入 |
| 词表策略 | train拟合、冻结、OOV到UNK | `embedding.page.vocab_fit=train_only`、`oov=unk` | embed/checkpoint | valid/test前向不改变词表大小 |
| 位置编码 | 固定正弦 | `model.position_encoding=sinusoidal` | `QMAPMacroscopicPatternExtractor` | 顺序交换改变编码结果 |
| 标签权重 | `(1,1,4)` | `labels.lambda_d/q/w` | generator/loss | 公式逐项数值测试 |
| 排序平滑 | `alpha=10` | `loss.approx_ndcg_alpha` | `qmap_loss.py` | 自身项和padding不计入位置 |
| 行为策略 | LRU | `selector.behavior_policy=lru` | `LRUBehaviorState` | 生成器状态可复现 |
| 正式验证 | 独立valid trace | `validation.strategy=independent_valid_trace` | config/generator/train | train、valid、test来源不重叠 |
| 尾部策略 | 丢弃不完整窗口 | `labels.tail_policy=drop_incomplete_window` | generator | `t+L>=N`不产生标签样本 |
| 开发备用 | train内部决策holdout | `validation.development_fallback=train_trace_decision_holdout` | dev runner | 工件强制标记`smoke_only` |
| 首次记账 | NVM access | `replay.first_touch_accounting=nvm_access` | evaluator | 三条手算trace总成本精确匹配 |
| 工作负载边界 | per-workload | `training.scope=per_workload` | config/checkpoint/eval | workload不一致拒绝加载 |
| 精排并列 | 最高精排分数并列时原始LRU rank最小者胜出 | `model.victim_tie_break=lru_oldest`（代码冻结值） | `QMAPPolicy.choose_victim` | 候选张量首项不是最老页且最高分并列时仍选择最老页；NaN/Inf硬失败 |

## 5. 正式工件合同

### 5.1 Trace

每条 trace 访问必须归一化为：

```json
{"page_id": 123, "pc": 4096, "rw": 0}
```

其中 `rw=0` 为读，`rw=1` 为写。若原始输入保存物理地址，必须在唯一入口按 `page_shift` 转换为 `page_id`，下游不得再次猜测字段语义。

### 5.2 Selector 参数

`selector_params.json` 至少记录：

- 合同ID、schema、workload、train/valid trace指纹；
- `c_Delta/c_A/c_W`；
- `w_Delta/w_A/w_W/w_C/w_R`；
- `PoolRecall@B`、`SelectorRecall@K`、`EndToEndRecall@K`、`TieCoverage@K`、`NRegret`；
- 有效决策点数、无区分样本比例、并列最优集合统计；
- LRU行为策略、完整未来窗口策略、selector TopK 并列规则和权重选择规则；
- 配置、代码提交和验证样本指纹。

### 5.3 精排 JSONL

每个样本至少记录：

```text
schema_version
contract_id
workload_id
decision_index
history_page_ids[H]
pc[H]
rw[H]
candidate_pages[K]
candidate_state_features[K][4]
candidate_mask[K]
original_pool_ranks[K]
inactivity[K]
coldness[K]
write_sensitivity[K]
```

padding 位置的 `candidate_mask=0`，不得参与 Cross-Attention victim 选择、相关性归一化、近似排名、DCG或损失计算。

### 5.4 检查点

检查点必须包含：

- 合同、配置、selector、train/valid JSONL和代码提交指纹；
- workload ID；
- 共享页面词表及其冻结状态；
- 页面嵌入、PC嵌入、Transformer、Cross-Attention和MLP参数；
- 模型结构参数、训练随机种子、最佳epoch和验证损失；
- 不允许在测试加载阶段自动补全缺失字段。

### 5.5 结果

正式结果至少报告：

- 总访问、DRAM hit/miss、NVM read/write、迁移次数、加权总代价；
- 每次实际降级决策平均与分位推理延迟；
- 候选筛选平均延迟、`B_t/K_t` 分布；
- 四个候选覆盖指标与 `NRegret`；
- 合同、配置、selector、检查点、test trace和代码提交指纹；
- 运行类型必须为 `official`，smoke结果不能被汇总器读取为正式结果。

## 6. 当前实现符合性与剩余缺口

| 编号 | 当前证据 | 合同要求 | 当前状态 |
|---|---|---|---|
| G01--G10 | 阶段1服务器验收：目标语义、非平凡微型E2E和完整回归均通过 | 独立valid、完整未来窗口、分层覆盖指标、统一LRU方向、共享冻结词表、位置编码、ApproxNDCG及首次访问记账 | `VERIFIED` |
| G11 | 阶段4已完成3 workload × 3 seed的正式LRU离线状态与CAPD闭环状态分布审计；保留36项large、9项moderate工程告警 | 正式实验必须报告分布偏移 | `VERIFIED`，保留 `REVIEW_REQUIRED` |
| G12 | 阶段4已完成三个workload的代理标签与窗口内反事实加权代价一致性审计 | 正式实验必须完成代理标签审计 | `VERIFIED` |
| G13 | `qmap/qmap_eval.py::QMAPPolicy.choose_victim` 已按冻结快照中的原始LRU rank处理精排最高分并列并拒绝NaN/Inf | 最高精排分数并列时，在有效候选中选择 `original_pool_rank` 最小者；NaN/Inf硬失败 | `VERIFIED`，阶段1 R1服务器验收通过 |

`capd_finals_v2_1` 工件仍只能视为原型/烟雾测试证据，不能进入当前正式流程。`capd_finals_v3_0` 阶段2 trace、selector 和 JSONL 不受 G13 影响，可以保留；G13 已关闭，阶段3启动门槛已满足。

## 7. 代码验收门槛

### Gate C1：纯函数与公式一致性

必须增加或修正以下单元测试：

- `R_LRU`：`B_t>1` 时rank 0严格为1、末位严格为0；筛选器与精排状态完全一致；
- selector TopK并列：同分时选择原始LRU rank更小的页面，改变page ID不得改变结果；
- 精排输出并列：候选张量首项不是最老页面且多个有效候选取得相同最高分时，选择原始LRU rank最小者；padding不得胜出，NaN/Inf硬失败；
- Recall并列：两个并列最优页中命中一个时`SelectorRecall@K=1`、`TieCoverage@K=0.5`；
- future guard：`t+L=N-1`可生成，`t+L>=N`拒绝生成；
- ApproxNDCG：对角线和padding不改变近似排名；
- position encoding：不同位置具有不同编码，device/dtype一致；
- 共享嵌入：相同page ID在history/candidate路径复用同一参数行；
- frozen vocab：valid/test前后词表大小和映射完全不变。

### Gate C2：回放状态一致性

- 生成器和评测器对同一状态产生完全相同的 `P_t/B_t/K_t`、五维筛选特征、候选集合、四维精排状态和mask；
- 当前触发请求只进入精排历史，不提前改变筛选统计或候选页状态；
- 精排并列决策只读取冻结快照中的 `original_pool_ranks/candidate_mask`，不读取更新后的LRU或selector分数；
- 首次读、首次写、DRAM命中、NVM再次访问、clean/dirty降级的手算计数和总代价精确匹配；
- test回放不读取任何未来访问或标签字段。

### Gate C3：数据和工件可追溯

- train/valid/test来源不重叠检查通过；
- 所有训练/验证标签均有完整L窗口；
- selector、JSONL、checkpoint和result的合同/配置/工作负载/数据指纹一致；
- 任一不匹配必须硬失败，不能警告后继续；
- smoke工件不能被official汇总器接收。

### Gate C4：最小端到端回归

使用一条可手算的小trace完成：

```text
trace -> selector fit -> JSONL -> train -> CAPD replay -> result audit
```

要求两次相同种子运行的数据指纹、候选选择和确定性工件一致；涉及神经网络的浮点指标按既定确定性容差比较。

## 8. 后续代码与实验分阶段计划

### 阶段0：冻结合同

- 状态：`DONE_R1`。
- 验收物：`CAPD-MIC-1.0` 文档修订 R1，以及新旧方法差异与影响分级。
- R1不改变工件schema、特征、标签、损失和阶段2数据语义，因此不提升合同ID；以后若改变这些冻结项，仍必须按第10节升版。
- 说明：阶段0只确定方法与验收标准，不代表新增G13已经由代码满足。

### 阶段1：语义对齐与测试

- 原 G01--G10 与 Gate C1--C4 已通过服务器验收，其证据继续有效。
- R1 曾将本阶段重新打开以补齐 G13；最终精排并列规则、NaN/Inf拒绝和对应的确定性单元/微型回归测试现已完成服务器验收。
- G13 修复不得改变候选池、selector排序、特征、标签、损失、JSONL字段或阶段2工件指纹；如实现过程中发现必须改变其中任一项，应停止并按第10节升级合同，而不是扩大本次兼容性勘误范围。
- 针对性测试、完整pytest和非平凡微型E2E均已通过，当前状态为 `STAGE1_R1_VERIFIED`。

### 阶段2：重新构造正式数据

- 状态：`VERIFIED_REUSABLE`（2026-07-22服务器验收通过）。
- 重新选择或采集互不重叠、压力充分的train/valid/test trace；
- 以完整未来窗口规则重新生成selector验证样本和精排JSONL；
- 生成数据质量报告：访问数、唯一页数、降级决策数、有效标签决策数、无区分比例、读写比例、热点/长尾统计；
- 不再使用旧 `finals_v2_decision_holdout` JSONL作为正式输入。
- R1只影响闭环推理中精排最高分并列时的单值选择，不影响本阶段已封存的trace、split、selector验证样本、selector参数或train/valid JSONL；因此不重新采集、不重新切分、不重新生成阶段2工件。若G13修复越界改变上述任一内容，则本结论自动失效并重新打开阶段2。

### 阶段3：候选筛选器独立验证

- 启动门槛：阶段0为 `DONE_R1`、阶段1为 `STAGE1_R1_VERIFIED`、阶段2保持 `VERIFIED_REUSABLE`；任一未满足时不得开始正式阶段3运行或结论汇总。
- 按工作负载搜索1001组权重；
- 报告 `B in {8,16,32,64}` 下的PoolRecall、SelectorRecall、EndToEndRecall、TieCoverage和NRegret；
- 报告五个特征权重和单特征/去特征消融；
- 确认扩大B确实提高观察覆盖，同时K固定为8。

### 阶段4：精排模型与闭环审计

- 状态：`STAGE4_VERIFIED`；G11的 `REVIEW_REQUIRED` 不阻塞阶段5启动，但必须作为阶段5结果的适用边界披露。
- 使用冻结selector重建训练/验证样本；
- 至少使用3个模型随机种子报告均值和波动；
- 完成代理标签—反事实窗口代价一致性审计；
- 完成LRU行为样本与CAPD闭环状态分布偏移审计；
- 若偏移明显且伴随性能退化，先记录为方法适用边界；任何迭代式数据聚合都属于新方法版本，不能静默加入本合同。

### 阶段5：端到端主实验与组件消融

启动门槛：已满足。阶段5开发完成但服务器正式矩阵尚未验收时，状态只能为 `STAGE5_IMPLEMENTED_UNVERIFIED`。

主对比使用统一trace、容量、初始状态和代价模型，对比外部策略：

- LRU、Random、LFU、CLOCK；
- 在实现和训练口径可比时加入Kleio-lite、PatternS-lite等外部学习策略。

组件消融围绕当前最终方法组织：

- 无轻量筛选（`B=K`）；
- 均匀筛选权重；
- 分别移除五个筛选特征；
- 无位置编码；
- 无候选页状态；
- 无Cross-Attention或改用历史池化；
- 无未来写风险项；
- `B/K/H/H_c/L`敏感性。

正式实验不把历史上的旧版CAPD作为比较对象。

### 阶段6：稳健性、开销与系统验证

- 工作负载类别、容量压力、读写比例、代价权重和随机种子稳健性；
- selector、Transformer、Cross-Attention和完整决策的平均/P95/P99延迟及内存开销；
- 吞吐下降、迁移次数和NVM写入变化；
- 在条件允许时增加真实混合内存平台或更接近系统的回放验证。

## 9. 实验报告边界

- 所有方法效果陈述必须来自阶段5或阶段6的official结果；
- 阶段1的单元测试只证明实现符合合同，不证明方法优于基线；
- 阶段3只证明候选覆盖行为，不替代端到端加权代价结果；
- 阶段4的代理标签和分布审计属于适用性证据，不能被包装为性能提升；
- 报告效果时同时给出绝对值、相对变化和跨种子/跨trace波动，避免只报告百分比；
- 主实验只与外部基线比较，方法内部差异放入组件消融。

## 10. 变更控制

下列任一修改都必须提升合同版本并重跑受影响阶段：

- 改变train/valid/test职责或未来窗口尾部处理；
- 改变首次访问、迁移或dirty页面记账；
- 改变五个筛选特征、方向、权重约束、Recall或NRegret定义；
- 改变selector TopK或精排最高分的确定性并列规则；
- 改变页面ID、词表、共享嵌入或OOV策略；
- 改变代理标签、权重或ApproxNDCG公式；
- 改变LRU行为策略或按工作负载独立训练边界。

参数扫描范围、训练epoch数或批大小等不改变方法语义的实验设置可以不提升合同版本，但必须修改配置指纹并保留完整运行记录。
