# CAPD 主动降级阶段 6：TPP-inspired 协议

## 定位与边界

正式名称始终为 `TPP-inspired`。这是 Replay-compatible adaptation，只保留：

- DRAM 未耗尽时以统一低水位主动建立 headroom；
- 轻量 epoch 的 Hot/Warm/Cold 状态；
- 当前统一 LRU-tail `K=8` 候选内的冷页优先排序；
- 阶段 5 的 `F_low=8`、`F_target=16`、`b_max=4` 和批量降级。

它不是 Linux TPP 或内核复现。不实现 NVM 热页 promotion、hint fault、完整
reclaim/kswapd、CXL/NUMA 节点管理、完整 active/inactive list、并发回收、内核锁/
阻塞/调度开销、真实后台迁移时序、多进程或多线程共享页。

阶段 5 合同不变：在 Stage5 配置和注册表中 TPP-inspired 仍为
`pending_stage6`，调用时仍抛出 `PendingStage6Error`。只有
`CAPD-PROACTIVE-STAGE6-TPP-1.0` 合同允许运行。

仓库中的旧 `qmap/stage6_variants.py`、`scripts/run_capd_stage6.py`、
`docs/CAPD_STAGE6_*` 和 `outputs/results/finals_v3_official/stage6*` 属于旧
full-DRAM、B=64、Random/LFU/CLOCK、容量/开销稳健性体系，与当前主动降级阶段编号和
方法语义冲突。它们保留为历史记录但不被导入、不作为入口证据，旧
`STAGE6_VERIFIED` 不能满足本合同门禁。

## 统一 Replay

TPP-inspired 直接安装为 `qmap.proactive_replay.ProactiveReplay` 的 ranker，不复制
状态机。候选、周期、事件、页框、LRU、dirty 和 Cost 记账均沿用阶段 5：

- `F_t >= 8` 不触发；`0 < F_t < 8` 启动主动周期；
- 每轮重新构造当前 LRU-tail 最多 8 页，不填充，不复用旧快照；
- `b_t=min(4,16-F_t,|C_t|)`；
- Top-`b_t` 严格属于本轮 `C_t`；
- `F_t=0` 的页面进入只使用共享 LRU emergency fallback，事件为
  `emergency_fallback_demotion`，不算 TPP 选择；
- 仅执行 DRAM→NVM demotion，不执行 promotion，不读取未来信息。

## 页面状态与 epoch

半开 epoch 定义为：

`epoch_id = access_index // epoch_length`

每次进入 DRAM 创建全新 residence lifecycle：

- `referenced_current_epoch=1`
- `referenced_previous_epoch=0`
- `last_access_epoch=current_epoch`
- dirty 由当前访问更新

DRAM 命中设置 current bit、last epoch 和 dirty。降级立即删除该生命周期状态；再次进入
不继承旧 bit。跨一个 epoch 时 previous=current、current=0；跨两个或更多空 epoch 时
两个 bit 均衰减为 0，这与逐 epoch 推进一致。

`cold_threshold=1`：current=1 为 Hot，否则 Cold，Warm 为空但保留统计字段。

`cold_threshold=2`：current=1 为 Hot；current=0、previous=1 为 Warm；两个 bit
均为 0 为 Cold。

正常 Replay 中每个 DRAM 页都有状态。若外部构造的合法驻留候选缺失状态，采用确定的
`last_access_epoch=null`、两个 bit 为 0、最老年龄哨兵并记录计数；非驻留候选硬拒绝。

## 排序

dirty tie-break 开启时类别依次为：

1. Cold clean
2. Cold dirty
3. Warm clean
4. Warm dirty
5. Hot clean
6. Hot dirty

关闭时 dirty 完全不进入排序。类别内统一按更久未访问、LRU-tail 更靠后（候选 rank
更小）、page id 更小。每个候选保存完整 `ranking_key`、reference bits、last epoch、
age、temperature、dirty、LRU rank 和 lifecycle id。

## Validation 网格与选择

网格在结果前冻结为 `3×2×2=12`：

- epoch length：64/256/1024 accesses
- cold threshold：1/2 epochs
- dirty tie-break：off/on

每个正式 workload 必须运行完整冻结 Validation 区间，4096 accesses 仅用于合成/
公平性验收。所有 workload 共享唯一参数。

主指标为各 workload `weighted_cost/access` 的无权宏平均。预声明异常门禁为：

- emergency 和 free-frame exhaustion 必须为 0；
- 最差 workload 相对该 workload 网格最优的差距不超过 10%；
- NVM write rate 不超过网格最小值的 1.10 倍加 `1e-6`；
- early reuse rate 与 Cold short-reuse rate 分别不超过网格最小值加 0.05。

在合格配置中取宏平均 Cost 的 1% near-best 集合，再依次比较最差 workload、NVM
write、early reuse、Cold short reuse、demotion、epoch transition、预声明复杂度和
experiment ID。复杂度优先 dirty off、threshold 1、epoch 1024/256/64。没有配置通过
门禁时必须失败并保留现场，不得事后修改阈值。

mean/P50/P95/P99 同步选择耗时完整保存，但不直接参与跨机器参数选择，避免计时噪声
破坏确定性；确定性的 epoch transition rate 与预声明复杂度次序承担开销 tie-break。

Cold short-reuse 沿用冻结的 64-access early-reuse 窗口。

## 公平性和解释边界

Stage6 实验 A 包含 Proactive-LRU、Proactive-CLOCK、TPP-inspired、CAPD 三个独立
seed 和 Oracle。公平性验收用阶段 5 r4 的同一 4096-access Validation 片段，并新跑
TPP；所有公共字段、候选构造合同和相同决策前状态的候选指纹必须一致。策略选择造成的
后续轨迹分叉是合法的。

同步 Replay 只表示排序质量、NVM 事件、weighted cost、状态轨迹和同步选择开销，不是
真实后台执行或前台延迟。本阶段不运行正式 Test，不产生 CAPD 优于任何 baseline 的
结论。
