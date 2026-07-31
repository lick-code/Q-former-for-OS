# CAPD 主动降级阶段 7 协议

## 定位

阶段 7 冻结六个正式 workload、时间顺序 split、Working Set、20/40/60% 容量矩阵、
Standard Test 身份和阶段 8 执行计划。阶段 7 不训练模型、不重选阶段 3～6 参数，也不
在 Test 上执行任何策略。

权威入口为 `stage6-tpp-r1` 的 `stage6_tpp_inspired_verified`，其
`stage7_entry_gate=satisfied`。历史提交 `b714ad0 stage7_result` 只包含
`outputs/capd_proactive_stage6/stage6-tpp-r1/` 工件及同次 Stage6 控制台日志，不是
阶段 7 完成证据。

## 冻结继承

- Working Set：`active_unique_pages_from_train_and_validation`
- 主默认容量：20%，属于用户接受的条件工程默认，不声称 `capacity_rule_v2` 通过
- 容量比较：20%/40%/60%，统一十进制向上取整
- `F_low=8`、`F_target=16`、`b_max=4`、`K=8`
- `candidate_source=lru_tail`、`selector=disabled`
- `fallback_policy=lru`、`trigger_mode=low_watermark`
- CAPD：`L=256`、`lambda=(1,1,2)`、`H=20`，三个 seed 全部运行
- TPP-inspired：`epoch_length=1024`、`cold_threshold=1`、
  `dirty_tie_break=false`，不 promotion
- Cost：DRAM Hit 1、NVM Read 2、NVM Write 8、Demotion 10
- 4 KB page，NVM 为 `unbounded_backing_tier`

所有容量继续使用相同水位，不按容量同比缩放。

## Workload角色与确认门禁

正式 seen 集合不可变：

1. canneal
2. streamcluster_pressure
3. dedup_pressure

正式 unseen 名单已由用户确认为 blackscholes、swaptions、fluidanimate；blackscholes
即使存在历史 Trace，也固定标记为 `held_out_unseen_workload`。配置中的
`suite_confirmation.confirmed=true` 仅解除正式采集门禁；Test lock 和最终
verification 仍必须等待六条 Trace、split、Working Set、容量矩阵和回归全部通过。

候选只能依据方法无关特征和 Train/Validation Reactive-LRU 诊断选择。CAPD、TPP、
Oracle 和任何 Test 结果不得参与候选筛选。

| workload | 预计采集成本 | 主要资格风险 |
|---|---|---|
| canneal | 中 | 必须实测为单 PID、单 TID |
| streamcluster_pressure | 高 | pthreads 的 `1` 线程配置仍须用实际 TID 集合证明 |
| dedup_pressure | 高 | pipeline 可能创建多个 TID；若无法获得真正单线程执行则硬失败 |
| blackscholes | 低至中 | 历史 Test 已有旧结果，必须使用新的 Trace 身份 |
| swaptions | 中 | `-nt 1` 仍须通过实际 TID 审计 |
| fluidanimate | 中至高 | 线程参数与 native 输入采集成本均须预检 |

## Trace资格

正式 Trace 使用：

`PID,TID,PC,Address,RW`

且必须实际观测到恰好一个 PID、一个 TID。`page_shift=12`，RW 必须来自真实采集列。
采集记录必须保存二进制、输入、命令、DynamoRIO、时间、主机、CPU、内存、OS、
Git、ASLR、退出码、日志、超时、截断和丢失事件状态。

旧 seen Trace 有真实 RW、顺序 split 和较完整来源，但没有实际 PID/TID 集合、ASLR、
超时/截断/丢失事件字段，而且其 Test 曾用于旧 `finals_v3` 实验。因此当前只能作为
条件复用候选，不能直接满足主动版阶段 7 最终门禁。除非获得可独立验证的补充证据，
应重新采集。

原始 Trace 只读保存。处理前后 SHA 必须一致；split 写入独立输出目录。

## Split与Test边界

每个 source Trace 使用按访问顺序的半开区间：

`Train → Validation → Test`

新采集预声明 3,000,000 条访问：

- Train `[0,1800000)`
- Validation `[1800000,2400000)`
- Test `[2400000,3000000)`

若正式确认前调整采集长度，必须先修改预声明配置，不能看 Test 结果后更换窗口。

阶段 7 为生成 split 和 SHA 可以读取 Test payload，但必须记录：

- `test_payload_read_for_integrity=true`
- `test_used_for_parameter_selection=false`
- `test_policy_replay_executed=false`
- `test_performance_inspected=false`

Test 不参与 Working Set、压力 profile、workload选择或参数选择。

## Working Set、容量与profile

每个 workload：

`W = |UniquePages(Train ∪ Validation)|`

保存 Train unique、Validation unique、交集和并集。Test 新页面不扩充 W。

容量：

`D(r)=ceil_decimal(r×W)`，`r∈{0.20,0.40,0.60}`

`D_20 <= max(F_target,K)` 硬拒绝；`D_20 < 100` 产生正式警告。NVM resident 上界按
`max(0,W-D)` 报告。

压力描述只运行 Train 后接 Validation、初始空 DRAM 的 Reactive-LRU。burst 窗口沿用
阶段 3 的 100 accesses，分位数使用 nearest-rank。Test 不进入该 Replay。

## 阶段8计划

六个 workload × 三个容量下：

- Reactive-LRU、Proactive-LRU、Proactive-CLOCK、TPP-inspired、Oracle 各一次；
- CAPD 三个冻结 checkpoint seed 各一次。

总计 `6×3×(5+3)=144` job。阶段 7 只写
`execution_status=planned_not_executed`，不保存任何性能结果。

冻结产物同时提供机器可读的 `workload_profiles.json`、
`workload_profiles.csv` 和供人工复核的 `workload_table_cn.md`。三者均由同一份
已审计统计生成；CSV/中文表不允许成为另一套独立计算路径。

实验 A 为 Proactive-LRU、Proactive-CLOCK、TPP-inspired、CAPD、Oracle；实验 B 只为
Reactive-LRU 与 Proactive-LRU。

held-out workload 必须直接使用阶段 4 冻结 checkpoint。Stage8 计划固定
`frozen_checkpoint_unk_index_0`，禁止扩展 page/PC 词表，并要求保存 page/PC 的
access/unique OOV count 与 ratio；结果必须分别保留 seen、unseen、六 workload macro
和逐 workload 原始值。

## 状态

- `stage7_implemented_awaiting_collection`
- `stage7_collection_complete_awaiting_freeze`
- `stage7_workload_suite_verified`
- `stage7_not_verified`

只有真实 Linux 验收全部返回 0 后才能打印：

`[FINAL] STAGE7_WORKLOAD_SUITE_VERIFIED`

该标记只表示数据和阶段 8 配置冻结，不表示正式 Test 已运行或任何性能结论成立。
