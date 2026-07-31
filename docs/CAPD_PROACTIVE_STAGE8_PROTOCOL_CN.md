# CAPD 主动降级 Stage 8 正式同步 Replay 协议

## 1. 冻结定位

Stage 8 只执行 Stage 7 已封存的 Standard Test，同步比较 Reactive-LRU、Proactive-LRU、Proactive-CLOCK、TPP-inspired、CAPD 和 Oracle。它不重新采集 Trace、不训练模型、不选择 checkpoint、不改变 Stage 3～7 参数，也不将 Test 用于选择。

Stage 7 的 `stage8_execution_plan.json` 是唯一 job 调度源。矩阵为 6 workload × 3 capacity ×（5 个确定性方法 + 3 个独立 CAPD seed）= 144 job。确定性方法每个单元只运行一次；CAPD seed 为 3136859、42、2026，先在单元内报告 mean ± sample standard deviation，禁止选择“最好 seed”。

## 2. 入口与 Test 隔离

`preflight` 验证 Stage7 gate、Standard Test lock、执行计划 SHA 和 144-job 笛卡尔积、capacity、Test identity、Stage5/6 策略证据、三个 checkpoint 实体 SHA 及全部冻结字段。preflight 只逐字节计算 Test 文件 SHA-256，不解析访问记录、不运行策略、不汇总性能。

Standard Test CSV 只能由 `execute` 命令中的受控入口解析。合成测试、单元测试、preflight、聚合和 verification 都不打开 Test 性能。任一身份不一致均 fail closed。

CUDA 正式运行固定 `CUBLAS_WORKSPACE_CONFIG=:4096:8` 与 `PYTHONHASHSEED=0`。验收脚本在打开 Standard Test 前，使用非 Test 合成 Trace 对三个冻结 CAPD checkpoint 分别执行一次真实 CUDA Transformer 推理；该烟测同时验证 CUDA 设备、cuBLAS 确定性环境、checkpoint 加载和模型算子。3/3 checkpoint 未全部通过时不得进入正式 Test。

## 3. Replay 与策略语义

六种方法复用 `qmap.proactive_replay.ProactiveReplay`，不复制状态机：

- Reactive-LRU：仅在 page-enter 且无空闲帧时按 LRU 降级一页，不创建主动周期。
- Proactive-LRU：统一低水位循环，当前 LRU-tail K 内按冷到热选择。
- Proactive-CLOCK：Stage5 冻结 reference bit/pointer 语义，扫描严格限制在当前 LRU-tail K。
- TPP-inspired：Stage6 冻结参数 epoch_length=1024、cold_threshold=1、dirty_tie_break=false，不 promotion，不读取未来，不以 LRU 冒充策略选择。
- CAPD：每个 seed 绑定 Stage4 冻结 checkpoint；输入只有当前及过去；selector disabled；held-out 输入使用冻结词表 UNK=0，不扩词表。
- Oracle：仅在当前统一候选集合内使用冻结 future label，是候选集合内分析上界，不是在线方法。

主动参数固定 F_low=8、F_target=16、K=8、b_max=4，候选为每轮重新构造的 LRU tail。Cost 固定为 DRAM hit 1、NVM read 2、NVM write 8、demotion 10。

## 4. 指标定义

每个 job 保留原始事件计数、weighted cost 分量、round/cycle/event 审计、初末状态、候选合同和最终状态。

FallbackRate 严格为：

`emergency_fallback_count / page_enter_dram_count`

分母为零时 rate 固定为 0.0，同时保留原始分子、分母及分母语义。

Early-Reuse 以每个 proactive demotion 事件中每个被选页面为一次分母，分别统计首次复用距离不超过 64、256、1024 accesses 的比例。无未来访问定义为 wasted demotion。主动降级数为零时各 rate 固定为 0.0。结果同时保存首次复用距离、未来访问次数的描述统计和逐降级审计。

CAPD 保存 page/PC 的 access OOV 与 unique OOV 计数/比例、checkpoint seed/path/SHA、`vocabulary_expansion_allowed=false` 和 `unk_index=0`。

## 5. 两张正式表与统计

表 A 只含 Proactive-LRU、Proactive-CLOCK、TPP-inspired、CAPD、Oracle；共同字段包括 Trace、capacity、初始状态、Cost、水位、K、b_t、fallback 和候选构造合同。唯一策略差异是候选排序与 Top-b_t。

表 B 只含 Reactive-LRU 和 Proactive-LRU；在相同 Trace、capacity、初始状态、LRU 与 Cost 下隔离按需降级和主动储备的差异。Reactive-LRU 不被强制具有水位/K/b_max。

CAPD 相对 TPP-inspired 的主比较先在每个 workload×capacity 单元内平均三个 seed，再形成 18 个配对差值。95% CI 使用 percentile bootstrap，重采样单位为 workload×capacity 单元，seed=20260801，重采样 10000 次。同步输出 seen、held-out unseen、all-workloads macro 与逐 workload 原始结果。最佳非 Oracle baseline 的候选集合在查看 Test 前固定为 Proactive-LRU、Proactive-CLOCK、TPP-inspired。

## 6. 续跑与证据

每个 job 使用独立目录、原子 manifest/result、完整 identity SHA、文件 SHA 和 semantic SHA。semantic SHA 排除机器相关耗时。只有 completed、identity 完全一致、schema 合法、文件 SHA 与 semantic SHA 均正确的 job 可续跑。running、failed、corrupt 或 identity 不一致均保留现场并要求新 run ID，不自动重试、不覆盖。

## 7. 解释边界

同步 Replay 只能解释页面排序质量、NVM 事件、weighted cost、状态轨迹和同步决策开销。它不代表真实后台并发或真实前台延迟。fallback 很少或为零只是在该同步功能正确性环境中的结果，不能外推为异步系统必然为零。Stage8 完成也不等于 Stage9 的真实 CPU、内存和推理开销测量完成。
