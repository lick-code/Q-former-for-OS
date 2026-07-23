# CAPD 阶段5实现符合性报告

状态：`STAGE5_IMPLEMENTED_UNVERIFIED`

## 已实现

- 新增统一阶段5入口，固定348个required jobs及12个可选学习基线jobs；
- 主实验强制CAPD三模型seed、Random三回放seed及LRU/LFU/CLOCK公平绑定；
- 新增严格变体配置通道，Full官方加载器仍拒绝非sinusoidal或错误结构checkpoint；
- 实现无筛选、五个冻结LOO selector、无位置编码、无候选状态、历史masked-mean/no-cross-attention、无未来写风险；
- 实现B/K/H/Hc/L预注册网格、默认Full复用及B8/no-filter工件共享；
- 实现改善率方向、样本标准差、最佳外部基线、同seed配对delta、pilot/official隔离、macro/micro标签和必需seed硬门禁；
- 实现学习基线逐项公平性记录与不可进入主表时的排除原因；
- 实现阶段4偏移—阶段5波动描述性交叉表；
- 新增Linux服务器完整验收脚本、原子job manifest、无自动重试和单写者续跑规则。

## 测试覆盖

- `tests/test_capd_stage5_variants.py`：变体唯一差异、Full加载拒绝、无筛选身份、阶段3 LOO权重、uniform identity；
- `tests/test_capd_stage5_results.py`：改善率方向、均值/样本标准差/min/max、主表seed完整性、Random seed覆盖、最佳基线、配对delta、pilot/official隔离；
- `tests/test_capd_stage5_end_to_end.py`：348-job矩阵与服务器opt-in临时目录mini E2E；
- 既有回归继续覆盖统一ReplayStats成本手算、未来标签隔离、基线不加载CAPD selector/标签以及Full checkpoint严格加载。

## 尚未完成的验收

本地没有正式Python/PyTorch运行环境，本轮未运行训练、Trace Replay、正式主实验、正式消融或敏感性实验。服务器尚未产生本阶段official结果，因此：

- 当前状态不能提升为 `STAGE5_VERIFIED`；
- 不能形成CAPD优于或劣于任何基线的性能结论；
- 没有使用test选择selector、标签权重、模型结构、checkpoint、seed或默认参数；
- 没有进入阶段6的容量、成本权重、延迟、内存或真实平台验证。

完整服务器门禁见 `docs/CAPD_STAGE5_SERVER_VALIDATION_CN.md`。
