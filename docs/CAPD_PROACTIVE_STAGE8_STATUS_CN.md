# CAPD 主动降级 Stage 8 当前状态

## 当前准确状态

`stage8_sync_replay_verified`

Stage8 已于 Linux/CUDA 服务器通过正式验收。权威成功运行是
`outputs/capd_proactive_stage8/stage8-sync-replay-r3/`，最终标记为：

`[FINAL] STAGE8_SYNC_REPLAY_VERIFIED`

`verification.json` 和 `run_state.json` 均记录
`stage8_sync_replay_verified`；`stage9_entry_gate=satisfied`。

## 正式完成证据

- Stage7 入口门禁：`satisfied`。
- Standard Test lock：`sealed_for_stage8`。
- 正式 job：144/144 completed，144 个 job ID 无重复，144 个 result SHA 均与 manifest 一致。
- CAPD：三个冻结 checkpoint（seed 3136859、42、2026）均通过 Test 前 CUDA 烟测并独立运行；未选择 best seed。
- 回归：Stage1～8 共运行 436 项测试，整体结果为 OK，其中 10 项按预声明条件跳过。
- 聚合：18 个 workload×capacity 单元、表 A、表 B、逐项原始结果及配对统计均已生成。
- 公平性：实验 A、实验 B 的 18 个单元全部通过；相同决策前状态下候选身份合同通过。
- 污染审计：冻结参数未改变，未使用旧 `finals_v3`，Test 未用于参数选择。
- 统计：固定 seed=20260801、10000 次、以 workload×capacity 单元为重采样单位的 95% percentile bootstrap 已通过独立校验。
- 产物：聚合 JSON/CSV/中文报告 SHA、runtime smoke SHA 和服务器验收收据均已记录。

服务器早期失败运行 `stage8-sync-replay-r1`、`stage8-sync-replay-r2` 仍仅作为失败现场保留，不能作为完成证据，也未被 r3 续跑复用。

## 正式结果摘要

主比较 CAPD 相对 TPP-inspired：

- 18 单元 CAPD−TPP weighted cost 均值：`-310.296296`。
- 平均相对改善：`0.040231%`。
- 95% bootstrap CI：`[-930.888889, 0.000000]`。
- 单元方向：CAPD 较低 1 个、持平 17 个、较高 0 个。
- 预声明判定：`ci_includes_zero_no_single_direction_claim`，不能据此声称 CAPD 在正式套件上具有确定的全面优势。

唯一出现页面排序差异的单元是 held-out `blackscholes@20%`：CAPD 三 seed weighted cost 为 `765706.666667 ± 7889.360071`，TPP-inspired 为 `771292`，CAPD 平均降低 `5585.333333`（`0.724153%`）；Oracle 为 `757796`。其余 17 个单元 CAPD、TPP-inspired 与最佳非 Oracle 主动 baseline 的 weighted cost 相同。

主动储备机制比较 Proactive-LRU 相对 Reactive-LRU：15 个单元持平，3 个单元成本更高，0 个单元更低。差异分别为 `blackscholes@20% +171252`、`canneal@20% +130`、`dedup_pressure@20% +160`；40%/60% 容量单元均持平。因此，本次同步 Replay 没有给出低水位主动储备降低 weighted cost 的证据。

全部 144 个 job 的 emergency demotion 和 FallbackRate 均为 0。该结果只表示同步功能正确性环境中的轨迹观察，不能外推为异步系统中 fallback 必然为零。

CAPD 的 18 个单元均记录 page/PC access 与 unique OOV ratio 为 100%，并按冻结合同映射到 `UNK index 0`，且 `vocabulary_expansion_allowed=false`。这说明 Stage7 正式 Test 的原始页面和 PC 标识均不在 Stage4 冻结词表中，是解释 CAPD 泛化结果时必须保留的限制；不得在看到 Test 后扩展词表或重训 checkpoint。

完整结果解释见 `docs/CAPD_PROACTIVE_STAGE8_RESULTS_CN.md`；机器可读权威结果为 `artifacts/aggregate.json` 和 `verification.json`。

## 阶段边界与下一步

Stage8 已完成，允许进入 Stage9。Stage8 的同步 Replay 只衡量页面排序质量、NVM 事件、weighted cost、状态轨迹和同步决策开销；它不代表真实后台并发或真实前台延迟。Stage9 的真实 CPU、内存和推理开销测量尚未完成。
