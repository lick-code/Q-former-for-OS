# CAPD 主动降级阶段 3：条件工程默认决策

## 决策

2026-07-30，项目停止继续采集和补跑 Stage 3，并采用以下条件工程默认：

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

主配置中的 `stage3_active_mechanism` 标记为 `frozen`，表示项目不再改动这组工程参数。它不表示 `capacity_rule_v2` 已通过统计或形式化门槛。

## 证据与选择理由

- `stage3-real-001` 的预声明水位规则选择 Medium 水位，即 `F_low=2`、`F_target=4`。
- 同一轮结果选择 `b_max=4`；代理 `K=8` 和 `K=16` 下选择一致，但代理结果不进入正式 `candidate_size_K`，因此 `K` 继续为 `null`，Stage 4 继续为 `pending`。
- 20% 容量下三个 Validation workload 均出现非零降级压力，因此将 20% 作为工程默认。
- `stage3-real-001` 的容量规则和后续 `capacity_rule_v2` 均未形成可正式冻结的容量结论。该限制必须保留，不得表述为“容量门槛验证通过”。
- 参数选择没有使用 Test，也没有使用 CAPD 结果。

## 本次失败的含义

最后一次 `stage3_v2_fresh_001` 尝试在采集前预检阶段退出：服务器未找到包含 DynamoRIO、PARSEC 二进制及输入的 `qmap-work` 运行时。因此该尝试没有开始新 trace 采集，也没有开始 Stage 3 回放；它既不支持也不推翻上述工程默认。

项目决定不再修复或重跑这条 fresh-collection 流程。以后若主动恢复正式容量验证，应作为独立后续工作，不得覆盖本决策的审计记录。

## Material Passport

- 数据：`stage3-real-001` 的 Train/Validation；`stage3-v2-real-003` 仅用于记录 v2 不可冻结结果。
- 代码：当前仓库的 Stage 3 Reactive-LRU / Proactive-LRU 校准实现。
- 环境：服务器回放产物已同步至本地；最后一次 fresh 尝试未进入采集或回放。
- 随机性：本决策引用确定性 replay 输出；未新增随机实验。
- 泄漏控制：Test 未参与参数选择。
- 状态：`ANALYZED`，参数作为用户确认的条件工程默认写入主配置；不声称容量规则正式通过。

## 后续边界

- Stage 3 参数不再补跑。
- `candidate_size_K` 保持 `null`；不得用代理 K 冒充正式 K。
- Stage 4 candidate/training、Stage 7 workload 和 formal Test 继续保持 `pending`。
- 论文和答辩材料应使用“条件工程默认”或“工程冻结值”，不得写成“capacity_rule_v2 验证通过”。
