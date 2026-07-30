# CAPD 主动降级阶段 5 统一 Replay Baseline 协议

## 1. 状态与边界

本协议标识为 `CAPD-PROACTIVE-STAGE5-1.0`。源配置状态固定为
`stage5_implemented`；它是不可回写的预声明/实现状态。只有 Linux 服务器验收脚本中的全部真实命令返回 0，独立运行目录才可产生
`stage5_baseline_framework_verified`。

阶段 5 只实现和验收 Baseline 框架，不运行正式 Test，不形成 CAPD 优于其他方法的性能结论，不重新选择阶段 3/4 参数，不训练或重选 checkpoint，不实现 TPP-inspired。

同步 Replay 只表示策略选择质量、NVM 事件、weighted cost、状态轨迹和同步决策开销；不表示真实后台执行或真实前台延迟。

## 2. 历史阶段 5 隔离

以下历史路径不构成当前阶段 5 的依赖或完成证据：

- `qmap/stage5_variants.py`
- `qmap/stage5_results.py`
- `scripts/run_capd_stage5.py`
- `docs/CAPD_STAGE5_*`
- `outputs/results/finals_v3_official/stage5_*`

这些实现包含旧 `B=64 -> selector -> K=8`、旧 full-DRAM 单页淘汰决策点、Random、LFU、传统 CLOCK 和旧 CAPD。当前路径硬拒绝旧 Stage4/Stage5 工件、旧 selector、`B=64`、Reactive-CAPD 和用旧
`STAGE5_VERIFIED` 充当完成证据。

安全复用范围只有：

- 阶段 1 的 `ProactiveReplay` 状态推进、三类事件计数、LRU、dirty、history 和不变量；
- 阶段 2 的 `proactive_cost.compute_weighted_cost`；
- 阶段 4 的严格 JSON、SHA-256、原子写入、Trace 解析、标签定义、QMAP 推理接口和 checkpoint 内部合同验证。

阶段 1 状态机新增的生命周期 hook 对旧 ranker 是 no-op；阶段 5 用它维护 CLOCK 状态。阶段 5 没有复制五套 Replay。

## 3. 冻结参数

- working set：Train 与 Validation 的 active unique pages；
- DRAM 比例：20%，仅为用户接受的条件工程默认，`capacity_rule_v2` 未通过；
- `F_low=8`，`F_target=16`，`b_max=4`；
- 候选：当前 DRAM LRU-tail，`K=8`，oldest-to-newest；
- selector：disabled；
- emergency fallback：LRU；
- `page_enter_dram`：无论来源，进入 DRAM 都消耗一个空闲页框；
- `L=256`，`lambda=(1,1,2)`，`K=8`，`H=20`；
- CAPD seed：`3136859 / 42 / 2026`；
- checkpoint：最小 Validation loss，平局取更早 epoch；
- Cost：DRAM hit 1、NVM read 2、NVM write 8、demotion 10。

阶段 4 freeze 中的服务器绝对路径不直接使用。适配器只接受位于当前仓库允许前缀内的原路径，或从记录路径中提取
`outputs/capd_proactive_stage4/...` / `dataset/...` 后在当前仓库安全重定位；随后逐文件校验冻结 SHA-256。路径逃逸和旧 Stage4/Stage5 结果树均被拒绝。

## 4. 统一状态推进

每次访问顺序：

1. 解析一条访问，确认页面当前位置；
2. DRAM hit 更新 LRU；NVM 访问记录 read/write；
3. 若页面要进入 DRAM 且 `F_t=0`：Reactive-LRU 产生
   `reactive_demotion`，主动策略产生
   `emergency_fallback_demotion`，victim 均为合法 LRU 尾页；
4. `page_enter_dram` 精确消耗一个页框；
5. 更新 frequency、dirty、recent history 和策略生命周期状态；
6. 主动策略仅在水位合同满足时执行主动周期；
7. 每轮重新从更新后的状态构造候选，计算
   `b_t=min(b_max,F_target-F_t,|C_t|)`，选 Top-`b_t` 并更新全部状态；
8. 达到目标水位或没有合法候选时结束周期。

初始化或候选不足 K 时不填充，`b_t` 不超过合法候选数。当前刚执行
`page_enter_dram` 的页面在该访问触发的主动周期中不属于合法候选。每轮保存候选页 SHA、候选前状态 SHA；相同前状态必须精确产生相同候选身份。不同策略选择会合法地改变后续驻留/LRU 轨迹，因此公平性检查同时区分：

- 全策略必须相同的候选构造合同；
- 每个决策实际收到的不可变候选快照；
- 任意相同前状态下必须完全相同的候选页序列。

## 5. 策略精确定义

### Reactive-LRU

不携带 `F_low/F_target/K/b_max`，不创建主动周期/轮次。只在当前
`page_enter_dram` 无空闲页框时释放一个合法 LRU 尾页，只记录
`reactive_demotion`。

### Proactive-LRU

使用统一水位和候选，按当前 LRU-tail 的冷到热顺序选择 Top-`b_t`。

### Proactive-CLOCK

每个 DRAM 页有 reference bit。新进入 DRAM 的页面初始化为 1；每次合法访问设为 1；降级后删除该页状态。持久指针表示为非负
`pointer_slot`，每轮映射到 `pointer_slot % |C_t|` 的候选槽。扫描范围严格限制为当轮 LRU-tail K：

- bit=1：清零并跳过；
- bit=0：选择；
- 同轮不重复选择；
- 最多扫描两个完整候选轮次；
- 扫描结束后保存下一槽为持久 pointer。

每轮保存完整扫描轨迹，证明没有扩大候选集合。

### CAPD

三个冻结 checkpoint 独立运行、独立输出；不存在 best-seed 汇总或选择。适配器构造函数不接收 Trace 或 future label，只把当前候选、过去 history、当前访问索引、过去 DRAM 进入时间和当前 dirty 状态交给阶段 4 QMAP 推理接口。selector 始终 disabled。

同一 checkpoint、同一设备和确定性配置要求 Top-`b_t` 及语义结果一致。跨 CPU/GPU 的 score 预声明容差为 `atol=1e-6`、`rtol=1e-5`；只有处于该容差内的近并列才允许 score 数值差异，否则 Top-`b_t` 必须一致。决策耗时不进入语义结果 SHA。

### Oracle

只在当前候选内计算阶段 4 冻结的未来 composite label。尾部 lookahead 不完整时使用实际可用后缀，并记录
`effective_lookahead` 和 `complete_future_window=false`。排序为：更高 label、再按更冷 LRU-tail rank、再按更小 page id。Oracle 是候选集合内分析上界，不是在线方法。

### TPP-inspired

注册表和状态 schema 已冻结，能够容纳 sampling epoch、冷热状态、reference 状态和 sampling 参数。状态固定为
`pending_stage6`。任何运行请求都抛出 `PendingStage6Error`，不得产生结果，不得回退到 LRU。完整实现属于阶段 6。

## 6. 实验合同

实验 A 的阶段 5 可运行集合为 Proactive-LRU、Proactive-CLOCK、三个独立 CAPD seed 和 Oracle；TPP 明确记为
`pending_stage6`。公平性字段包括 Trace SHA/范围、split/role、DRAM/NVM、页大小、working set、页面进入语义、初始状态、Cost、水位、K、`b_max`、`b_t`、fallback、原始访问数和候选合同/快照身份。唯一策略差异是 rank 和 Top-`b_t`。

实验 B 恰好比较 Reactive-LRU 与 Proactive-LRU。两者共享 Trace、范围、容量、初始状态、LRU、页面进入语义、Cost 和原始访问数；公平性检查有意不要求 Reactive-LRU 携带主动水位字段。

阶段 5 服务器验收使用配置中预声明的 Validation 前 4096 次访问作为框架验收范围，并另外运行小型合成 A/B。该范围不是正式 Test，不用于性能结论。

## 7. 事件、结果与续跑

每轮包含阶段 1 必需字段，并新增候选页 SHA 和候选前状态 SHA。每周期额外汇总 feature/inference/selection 时间。每结果保存全部原始访问/迁移计数、early reuse rate、平均/最小 free frame、cycle/round、mean `b_t`、P50/P95/P99、默认 weighted cost 及四个成本分量。

每个 job 先原子写 `running` manifest，成功后原子写 result 并封存 SHA。续跑只复用 job identity 完全一致且结果 SHA 正确的 completed job。已有 running/failed/corrupt job保留现场并拒绝自动重试；应使用新 run ID。

规则策略在关闭耗时测量时，其 `semantic_result_sha256` 必须精确一致。耗时字段从语义 SHA 中排除。

## 8. 状态门禁

- 源代码完成但服务器未验收：`stage5_implemented`；
- 所有框架、语义、公平性、checkpoint、污染和阶段 1～5 回归真实通过：
  `stage5_baseline_framework_verified`；
- 任一必要门禁失败：`stage5_not_verified`，且失败 job 保留。

只有验收脚本最后的 verify 命令可打印：

`[FINAL] STAGE5_BASELINE_FRAMEWORK_VERIFIED`

该状态只允许进入阶段 6，不表示 TPP 已实现、正式六方法主实验完成或 CAPD 性能结论成立。

