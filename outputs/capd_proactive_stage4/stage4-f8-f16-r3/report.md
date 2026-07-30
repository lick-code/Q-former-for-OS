# CAPD 主动降级阶段 4 结果待冻结报告

- 状态：`stage4_results_ready_for_freeze`
- Test 参与：否
- 候选筛选器：disabled
- 阶段 3 容量边界：20% 为条件工程默认；capacity_rule_v2 未通过

## 全局选择

- `L=256`
- `lambda=[1.0, 1.0, 2.0]`
- `K=8`
- `H=20`

## Validation 宏平均

| 指标 | 值 |
|---|---:|
| weighted cost/access | 1.0400873333333334 |
| NDCG@1 | 0.999537037037037 |
| NDCG@b_t | 0.9997052396116978 |
| Top-b overlap | 0.9997685185185186 |
| Top-b regret | 0.000877097800925926 |
| NVM read | 1745.0 |
| NVM write | 406.3333333333333 |
| proactive demotions | 909.0 |
| emergency fallback rate | 0.0 |
| exhaustion rate | 0.0 |
| early reuse rate | 0.00030864197530864197 |
| amortized latency/page (s) | 0.0014574175784076548 |

三个 seed 用于描述稳定性，不解释为强统计显著性结论。
本报告只有通过服务器测试和最终一致性审计后才可升级为 verified。
