# CAPD 主动降级阶段 4 当前状态

## 当前状态

`stage4_implemented_awaiting_training_inputs`

代码、正式配置、严格输入 manifest、主动轨迹样本生成、标签诊断/重算、
多 workload/seed 训练与汇总、变量 Top-`b_t` 指标、全局参数选择、最终重建、
checkpoint 指纹、原子写入、断点续跑、污染审计、服务器验收脚本、中文协议和测试
已经写入仓库。

本地没有可用的 Python/PyTorch 执行环境，因此尚未运行真实 Train/Validation
全量训练，也没有伪造数值结果。当前不得标记
`stage4_results_ready_for_freeze` 或 `stage4_verified`。

## 旧阶段 4 冲突审计

历史阶段 4 的以下语义不能进入当前正式流程：

- `finals_v3` 数据/配置/合同身份；
- `B=64 → selector → K=8`；
- 候选筛选器参数和 selector fingerprint；
- full-DRAM 单 victim 决策点；
- 固定 `L=256/K=8` 的旧结论；
- 旧 `STAGE4_VERIFIED` 状态；
- `outputs/results/finals_v3_official/stage4_audits/` 的结果。

可以复用的只有通用模型、ranking loss、训练循环、每 epoch checkpoint、Validation
loss 选 best、RNG 状态恢复、checkpoint manifest、统计工具和 SHA-256 思路。当前
流程对这些复用部件增加了主动 Stage4 contract 和 Train-only 词表冻结。

## 已冻结与待决定

已冻结：

- Working Set 定义；
- DRAM 比例 20%（条件工程默认，非容量门槛通过）；
- `F_low=2`、`F_target=4`、`b_max=4`；
- LRU-tail 候选、selector disabled、low-watermark、LRU fallback；
- 默认 Cost；
- 候选网格、seed、阶段顺序、数值容差和 tie-break；
- 当前 H=10，因此 H 网格为 5/10/20；
- `b_max=4`，因此正式 K 网格为 8/16，K=4 被配置和测试硬拒绝。

等待真实 Validation 决定：

- Lookahead L；
- 标签权重；
- K；
- H；
- 最终三个 seed checkpoint 及其 SHA-256。

## 下一状态的门槛

真实 Train/Validation 的 4-B～4-E 完成并生成最终冻结候选后，状态为
`stage4_results_ready_for_freeze`。阶段 1～4 回归测试、最终工件一致性、
Test 污染和历史产物污染审计全部通过后，才可进入 `stage4_verified`。

