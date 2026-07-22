# CAPD 阶段4：精排模型与闭环审计协议

状态：`STAGE4_IMPLEMENTED_UNVERIFIED`

本阶段严格绑定 `CAPD-MIC-1.0`、R1、`capd_finals_v3_0`、official、B=64、K=8。只使用 train/valid；不打开 test，不进行基线性能比较，不形成端到端性能结论，也不进入阶段5。

## 实现架构

- `scripts/run_capd_stage4.py`：`audit-inputs/generate/train/counterfactual-audit/distribution-audit/summarize/all` 统一入口。
- `qmap/stage4_common.py`：并列秩 Spearman、NDCG、KS、Wasserstein-1、分位数及冻结身份常量。
- `qmap/stage4_counterfactual.py`：G12 逐候选强制首次 victim 的完整窗口代价审计。
- `qmap/stage4_distribution.py`：G11 A/B/C 三组分布采集与漂移比较。
- `qmap/qmap_train.py`：允许显式训练 seed 覆盖配置默认 seed，但不改变配置、selector 或 JSONL 身份。

阶段4重建结果与保留的阶段2 JSONL 按规范化 JSON 行逐行比较：忽略 CRLF/LF 和无语义 JSON 空白，但任何字段、数值、顺序或行数差异均硬失败并报告首个差异行。source manifest 的合同字段继续使用阶段2冻结的文本指纹，并以 LF/CRLF 兼容方式核验；另行记录 provenance identity 和当前原始文件 SHA，三者不得混用。

## 多随机种子

每个 workload 独立训练 `3136859、42、2026` 三个 seed，共 9 个模型。所有 seed 使用完全相同的阶段4 train/valid JSONL、epochs、batch size、learning rate、结构和损失。每个 epoch 记录 train/valid loss，只以最小 valid loss选择 best checkpoint；NaN/Inf 硬失败。汇总报告均值、样本标准差、最小值和最大值。

## G12 精确定义

对 valid trace 中每个具有完整 `L=256` 未来窗口的 LRU 行为决策点，构造冻结 B=64 selector 的 `C_t`。对每个有效候选克隆相同决策前状态，强制其为首次 victim、插入当前请求页，然后只用固定 LRU 回放后续 256 次访问。`J_t^L(i)` 包含强制迁移成本、未来 DRAM/NVM 访问成本和后续 LRU 迁移成本；dirty 降级不额外增加 NVM write，NVM 容量无界。当前触发 miss 已发生的 NVM 访问是候选公共常数，单列记录并排除于 `J` 的候选差异。

报告并列秩 Spearman、代理 top-1 集合与最低成本集合的 any-hit、基于当前候选内成本 min-max 相关性的 NDCG。成本全相同时将 NDCG 相关性向量统一设为 1、NDCG=1，并单列“无区分”比例；常量 y 或 J 的 Spearman 为 undefined，从均值排除但计数。

标签敏感性只重算已有 `d_hat/q_hat/w_hat`：`base=(1,1,4)`、`no_write=(1,1,0)`、`balanced_write=(1,1,1)`、`half_write=(1,1,2)`、`stronger_write=(1,1,8)`、`inactivity_only=(1,0,0)`、`coldness_only=(0,1,0)`、`no_inactivity=(0,1,4)`、`no_coldness=(1,0,4)`。不会重放状态或据此改正式权重。

## G11 三组分布

- A：train trace + LRU behavior policy，代表离线训练分布。
- B：valid trace + LRU behavior policy，隔离 split drift。
- C：valid trace + 每个 seed 的 CAPD closed-loop policy，表示策略自身选择诱发的状态分布。

主比较为 A/C；同时报告 A/B 和 B/C。selector 特征按 `P_t` 有效页展开，精排状态按 `C_t` 有效候选展开，B/K、dirty ratio、decision interval 按决策点统计；padding 永不进入统计。KS>=0.1/0.2 只标记工程诊断 moderate/large，不是显著性检验或自动再训练触发器。明显偏移原样报告并标记 `REVIEW_REQUIRED`，不修改方法。

## 正式路径

- JSONL：`dataset/jsonl/finals_v3_official/stage4_reranker/<workload>/B64/`
- checkpoint：`outputs/checkpoints/finals_v3_official/stage4_reranker/<workload>/seed_<seed>/`
- 审计：`outputs/results/finals_v3_official/stage4_audits/`

服务器未完成全部门禁前，状态只能是 `STAGE4_IMPLEMENTED_UNVERIFIED`。
