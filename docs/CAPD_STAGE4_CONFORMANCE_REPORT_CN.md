# CAPD 阶段4实现符合性报告

状态：`STAGE4_VERIFIED`

阶段4已于2026-07-23在 Linux 服务器完成正式验收。验收证据目录为
`/tmp/capd-stage4.pDQyrs`；输入审计、阶段4针对性测试、完整 pytest、
非平凡微型 E2E、冻结 selector 数据重建、9模型检查/复用、G12、G11、
汇总、污染检查和 `git diff --check` 的真实退出码均为0，验收脚本最终
打印 `[FINAL] STAGE4_VERIFIED`。本次回填未提供 pytest 的精确
passed/collected 数量，因此不臆造该数字，以服务器原始日志为准。

## 完成项

- 输入身份审计状态为 `PASSED`，严格绑定 `CAPD-MIC-1.0`、
  `capd_finals_v3_0`、official、B=64、K=8和三个冻结 workload。
- 9/9模型 checkpoint 完整；三个 workload 各使用
  `3136859、42、2026` 三个独立 seed；best checkpoint 只按最小 valid
  loss选择；checkpoint SHA-256全部匹配，未出现NaN/Inf。
- G12完成三个 workload 的valid反事实窗口审计和九组标签敏感性。
  base宏平均 Spearman为0.985862、top-1 any-hit为1.0、NDCG为
  0.999735；反事实成本无区分比例为0.974026，作为适用边界原样保留。
- G11完成3 workload × 3 seed共9/9组闭环分布审计，生成351行分布指标；
  所有 partial 均为 `COMPLETED`，最终验收复用9组、待计算0组。
- G11检测到36项large和9项moderate工程告警，因此保留
  `REVIEW_REQUIRED`。该标记是方法适用边界，不是实现失败，也不触发
  重新训练、selector重选或标签修改。
- 所有阶段4审计工件均记录 `test_trace_opened=false`；没有进入阶段5，
  没有生成或报告基线比较或端到端性能结论。

## 状态解释

`STAGE4_VERIFIED`只表示阶段4的实现、计算、工件身份和闭环审计门禁全部
通过，不表示CAPD优于任何基线。阶段5正式系统实验及其性能结论仍需独立
执行和验收。

本地仅核对同步工件、指纹、状态和仓库卫生，没有在本地运行Python、
pytest、训练、模型推理、Trace Replay或正式实验。
