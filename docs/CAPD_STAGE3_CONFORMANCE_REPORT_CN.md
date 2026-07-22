# CAPD 阶段3符合性报告

## 1. 当前状态

状态：`STAGE3_IMPLEMENTED_UNVERIFIED`

阶段3统一入口、硬门禁、指标复算、特征分析、B sweep、输出制品、测试和服务器验收命令已经实现；本地按任务边界未运行 Python、pytest、数据生成、训练、回放或正式实验。因此本报告不能标记为 `STAGE3_VERIFIED`，也不包含任何 selector 数值结论。

## 2. 实现覆盖

- 输入范围：三个 official workload、`B={8,16,32,64}`、`K=8`。
- 身份门禁：合同/schema/profile/artifact class/workload/B/config/selector/sample/summary 指纹链。
- 来源门禁：`independent_valid_trace` 与 frozen valid trace fingerprint；拒绝 v2/smoke。
- Full：1001点冻结网格、四级确定性选择，与阶段2 selector 强一致。
- Single-feature：五个 one-hot 直接评价。
- Leave-one-out：五个286点子网格分别重搜。
- 指标：PoolRecall、SelectorRecall any-hit、EndToEndRecall、TieCoverage、NRegret及各自明确分母。
- B sweep：K固定、B=8三个数值不变量、候选池前缀/决策点对齐、PoolRecall单调诊断和 B8 到 B64 绝对增量。
- 输出：summary、metrics CSV、ablation CSV、Markdown报告、input audit和12份详细JSON。
- 安全：分析入口不读 test trace、精排 train/valid JSONL 或 checkpoint；audit-only不写结果；正式输出拒绝进入阶段2目录并拒绝覆盖既有输出。

## 3. 针对性测试构造

`tests/test_capd_stage3_selector.py` 覆盖：

1. 完整网格精确1001点；
2. 五个 leave-one-out 子网格各精确286点；
3. 五个 one-hot 权重；
4. Recall、NRegret、uniform距离、字典序四级选择；
5. any-hit Recall 与 TieCoverage 的严格区分；
6. 无区分样本不进入 SelectorRecall/NRegret 分母；
7. 全部无区分时 uniform fallback；
8. B=8 的 `SelectorRecall=1`、`EndToEndRecall=PoolRecall`、`NRegret=0`；
9. `K!=8` 硬失败；
10. contract/schema/profile/artifact class/workload/B 不匹配硬失败；
11. validation sample 指纹不匹配硬失败；
12. 相同输入结果确定；
13. 输出进入阶段2目录被拒绝；
14. audit-only不写结果；
15. 小型合成样本完整验证 Full、single-feature 和 leave-one-out，且 Full 不一致时在消融前硬失败。

全部测试仅需 Python、NumPy、pytest/标准 unittest，不依赖 GPU 或模型训练。

## 4. 静态审查状态

开发完成后执行的本地检查只包括文本/代码静态审查、变更范围复核、`git diff --check` 和污染检查；未执行 Python 解释器或 pytest。服务器动态验收按 `docs/CAPD_STAGE3_SERVER_VALIDATION_CN.md` 执行并回填真实日志、退出码、12组数值结果及最终状态。

## 5. 结论边界

阶段3只回答扩展候选池的覆盖、固定 K 下的筛选保留、五个特征行为、leave-one-out退化以及权重稳定/fallback现象。任何结果均不得解释为 CAPD 优于基线、系统命中率提升、加权代价下降或端到端性能改善。
