# CAPD 主动降级阶段 4 协议

## 1. 身份与边界

本协议只适用于 `CAPD-PROACTIVE-STAGE4-1.0`。它与历史
`finals_v3/B=64` 阶段 4 完全隔离；历史
`scripts/run_capd_stage4.py`、`qmap/stage4_*`、旧报告和
`outputs/results/finals_v3_official/stage4_audits/` 均不能满足本协议，也不能作为本流程的输入。

阶段 4 只读取 Train 和 Validation。程序同时检查 manifest 的 split、role、
`formal_test`、文件名 Test 标记、文件 SHA-256、源轨迹身份和半开源区间。
`split=test`、Test 路径、Train/Validation 内容相同、同源区间重叠都会硬失败。

## 2. 继承且不得修改的阶段 3 状态

- Working Set：Train 与 Validation 活跃唯一页并集；
- DRAM/Working Set：20%；
- `F_low=8`、`F_target=16`、`b_max=4`；
- `candidate_source=lru_tail`；
- `selector=disabled`；
- `trigger_mode=low_watermark`；
- `fallback_policy=lru`；
- Cost：DRAM Hit 1、NVM Read 2、NVM Write 8、Demotion 10。

20% 和 `(8,16)` 是用户接受的条件工程默认，不是 `capacity_rule_v2`
或新水位矩阵通过后得到的最优值。阶段 4 不修改容量、水位或 `b_max`。

当前正式 `H=10` 已由阶段 3 配置确认，因此历史窗口网格固定为 `5/10/20`。
由于 `b_max=4` 且正式方法要求 `b_max<K`，旧实施方案示例中的 `K=4`
不合法；本协议在结果产生前把正式 K 网格修正为 `8/16`。

## 3. 主动降级训练样本

样本仅在主动状态机的真实轮次产生：

1. 页面进入 DRAM 后若 `F_t<F_low`，启动主动周期；
2. 从当前 LRU tail 直接构造最多 K 个候选，不存在 B=64 扩展池和筛选器；
3. 本轮 `b_t=min(b_max,F_target-F_t,有效候选数)`；
4. 训练数据轨迹由预声明的 Proactive-LRU 排序推进，避免“模型决定其自身训练状态”以及标签权重之间的循环依赖；
5. 每轮降级后由阶段 1 状态机刷新 DRAM/NVM、页状态、空闲页框和 LRU；
6. 未达到 `F_target` 时重新构造候选并进入下一轮；
7. emergency fallback 使用独立事件类型，不写成普通主动降级。

每条样本保存 H 长度历史、mask、候选页、4 维候选状态、候选 mask、动态
`b_t`、`F_t`、标签分量、复合标签、L/K/H、workload、split、周期与轮次身份。
候选不足 K 时只做 mask padding，不伪造候选。

不完整 Lookahead 尾部轮次不进入训练，但在数据诊断中单独统计。无未来复用、
零未来窗口、标签全并列和非唯一 Oracle 集合都有显式状态。

## 4. 标签与参数顺序

标签为：

\[
y_t(l)=\lambda_1\hat d_t(l)+\lambda_2\hat q_t(l)-\lambda_3\hat w_t(l).
\]

执行顺序不可更改：

1. 4-B：固定 `lambda=(1,1,4),K=8,H=10`，比较 `L=256/512/1024`；
2. 4-C：固定已选 L 和参考 K/H，逐组重新计算复合标签、重新训练，比较六组权重；
3. 4-D：固定已选 L/权重，比较 `K=8/16 × H=5/10/20`；
4. 4-E：按最终 L/权重/K/H 重新生成完整 Train/Validation 数据并重新训练三个 seed。

所有 workload 共享同一组 L/权重/K/H。每个 seed 训练一个跨 workload
的全局模型；seed 固定为 `3136859/42/2026`。模型 checkpoint 只按 Validation
loss 选择，完全并列时保留更早 epoch；参数配置只按 Validation 闭环结果选择。
训练子进程固定 Python hash seed、PyTorch/CUDA seed，并启用确定性算法。
Test 不得用于任何选择。

## 5. 预声明全局选择规则

主指标为各 Validation workload 等权宏平均 weighted cost/access。先保留距主指标
最小值 1% 以内的候选，再检查相对本阶段参考配置：

- 最差 workload weighted cost 退化不超过 5%；
- 任一 workload NVM write 增长不超过 5%。

合格候选依次按以下规则确定唯一结果：更低最差 workload 退化、更低 NVM write
退化、更高 `NDCG@b_t`、更高 Top-`b_t` overlap、更低 Top-`b_t`
regret、更低每页摊销 latency、更低复杂度、1% 近似并列带内更低宏平均
weighted cost、实验 ID 字典序。这样完全或近似并列时不会为了极小的 Cost
差异选择更大配置。若约束使 1% 集合为空，程序保留 1% 主指标集合并记录
`fallback_used=true`，不临时修改阈值。

## 6. Validation 指标

每个 workload、seed 和聚合层都保存：

- `NDCG@1`、`NDCG@b_t`；
- Top-`b_t` overlap、Top-`b_t` regret；
- weighted cost、DRAM hit、NVM read/write、总降级数；
- Early-reuse 数量/比例；
- emergency fallback 数量/比例；
- exhaustion 数量/比例；
- 主动周期数和主动轮次数；
- 决策 latency 的 mean/P50/P95/P99；
- 每页摊销 latency。

Top-b regret 定义为 Oracle Top-b 标签和减去预测 Top-b 标签和。Oracle
边界并列时，overlap 使用所有达到边界标签的可接受 Oracle 集合；regret
使用确定性 LRU-rank tie-break，但并列选择的标签和相同。全标签并列时
NDCG 记 1，并标记 `indistinguishable_all_labels_tied`。

三个 seed 报告均值、样本标准差和可计算时的 t 区间，只解释为稳定性描述，
不包装成强统计显著性结论。选择文件同时保存与本阶段参考配置的 workload/seed
配对差值。

## 7. 工件、续跑与状态

每个运行目录至少包含：

- `resolved_config.json`、`provenance.json`、`run_identity.json`；
- `input_manifest.json`、`input_artifacts.json`、`working_set_summary.json`；
- 每个候选的 dataset manifest、Train/Validation JSONL 和标签诊断；
- 每个 seed 的 training contract、checkpoint manifest、checkpoint 和训练日志；
- workload/seed 原始闭环指标、轮次指标和聚合指标；
- 三个阶段选择文件；
- 最终重建数据、最终 checkpoint 列表及 SHA-256；
- `run_state.json`、测试回执、最终 verification。

原子写入使用同目录临时文件和 `os.replace`。已完成数据、训练、Validation
只有在合同和 SHA-256 一致时才复用；中断训练通过 `qmap_last.pth` 恢复，并核对
seed、训练合同和 Train/Validation 指纹。

状态严格分为：

- `stage4_implemented_awaiting_training_inputs`；
- `stage4_results_ready_for_freeze`；
- `stage4_verified`。

只有服务器回归测试、全部真实 Train/Validation 实验、最终重建、checkpoint
指纹和污染审计均通过后，`verify` 才输出 `[FINAL] STAGE4_VERIFIED`。
