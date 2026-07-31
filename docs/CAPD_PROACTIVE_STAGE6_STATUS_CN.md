# CAPD 主动降级阶段 6 当前状态

## 当前状态

`stage6_implemented_awaiting_validation`

TPP-inspired Stage6 合同、epoch 页面状态、排序 ranker、统一 Replay 适配、12 组网格、
全局选择规则、确认 Replay、实验 A 公平性扩展、原子 job manifest、安全续跑、回归
收据和 Linux 验收脚本已经实现。

本地只允许进行静态、单元和合成检查。尚未声称 12 组真实完整 Validation 已完成，
尚未冻结最终 epoch length/cold threshold/dirty tie-break，也不写
`stage6_tpp_inspired_verified`。

## 阶段 5 入口审计

权威入口是只读的 `stage5-baseline-r4`：

- `status=stage5_baseline_framework_verified`
- `stage6_entry_gate=satisfied`
- `tpp_inspired_status=pending_stage6`
- Test 未打开，旧 Stage4/5 工件未使用

阶段 5 状态文档此前仍停留在 r3 失败，是文档滞后而非 r4 证据失效。该审计发现已在
阶段 5 状态文档中更正；r4 的 verification、run_state、fairness 和其他原始证据均未
修改，也未重跑或覆盖。

## 旧阶段 6 隔离

旧 `qmap/stage6_variants.py`、`scripts/run_capd_stage6.py`、
`docs/CAPD_STAGE6_*` 和 `outputs/results/finals_v3_official/stage6*` 使用旧
finals_v3、B=64、Random/LFU/传统 CLOCK 和容量/开销稳健性语义。当前实现不导入或
覆盖这些文件；污染检查明确拒绝旧 Stage6/TPP 工件，历史 `STAGE6_VERIFIED` 不是
当前主动 TPP-inspired 的证据。

## 状态门禁

- 完成全部 36 个 workload/config 正式 Validation job 并生成唯一选择后：
  `stage6_results_ready_for_freeze`
- 选定配置完整 Validation 确认、阶段 1～6 回归、实验 A、公平性/污染/SHA 全部通过后：
  `stage6_tpp_inspired_verified`
- 任一必要门禁失败：`stage6_not_verified`，保留现场且必须换 run ID

仅最终验收脚本可打印：

`[FINAL] STAGE6_TPP_INSPIRED_VERIFIED`

该状态不表示正式 Test 完成、CAPD 优于 TPP-inspired 或完整 Linux TPP 已复现。

## 明确省略

不实现 promotion、hint fault、完整 reclaim/kswapd、CXL/NUMA、完整内核
active/inactive list、并发回收、锁/阻塞/调度开销、真实后台迁移和共享页并发行为。
DRAM 20% 仍是条件工程默认，不是 `capacity_rule_v2` 通过。
