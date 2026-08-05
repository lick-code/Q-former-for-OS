# CAPD Stage11A 状态说明

本阶段的状态分为代码状态、候选状态和门禁状态。`implemented` 表示代码或契约存在；`candidate-ready` 只表示 Stage8 raw counters 的离线重算或未来通过独立检查的同步候选；`BLOCKED` 表示前置条件明确未满足；`NOT_VERIFIABLE` 表示输入缺失、结构错误或 SHA 不一致；`formally_verified` 仅保留为跨阶段词汇，Stage11A v1.0 不生成它。

当前本地可支持的结果是 Stage8 r5 上的离线 weighted cost profile 重算，以及配置明确冻结后才可执行的同步候选接口。同步 Replay 不能支持 CPU latency、cycles、instructions、task-clock、RSS、模型内存、真实并发或异步收益结论。

Stage9 真实系统开销仍因 Linux `perf_event_paranoid=4` 和 `No supported events found` 阻塞。不能用 wall time、CPU 频率、fixture 或设计文档估计这些指标。Stage10A 目录是 fixture；其完整性可以验证，但不能升级为正式异步结果。当前报告中的缺失数字使用 `N/A`，不会填零。

筛选器历史负向证据只作为附录性输入；不进入正式方法矩阵，也不重新训练或从 Test 结果调参。

