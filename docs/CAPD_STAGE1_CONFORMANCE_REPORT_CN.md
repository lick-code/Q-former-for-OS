# CAPD 阶段1语义对齐符合性报告

## 1. 报告状态

本地状态：`IMPLEMENTED_UNVERIFIED`

本报告只记录代码与测试代码的静态构造结果。本地没有执行 Python 语法检查、单元测试、torch 前向、数据生成、Trace Replay、模型训练、模型推理、selector 网格搜索、smoke test、benchmark、端到端回归或实验，因此不得把本报告解释为 `PASSED`、`VERIFIED`、`STAGE1_CONFORMANT` 或“阶段1已完成”。

2026-07-20 首轮服务器验收反馈的三项修订已写入代码和测试，但本地只完成静态审查，尚待服务器复验：五访问手算代价修正为 35；selector 正式 Recall/NRegret 统一使用有效验证决策点；微型端到端 trace 改为包含冷热重访和写访问的非平凡工作负载。

唯一方法—实现依据：`docs/CAPD_METHOD_IMPLEMENTATION_CONTRACT_CN.md` 中冻结的 `CAPD-MIC-1.0`。冻结合同的“实现状态”未被修改。

服务器验收命令：`docs/CAPD_STAGE1_SERVER_VALIDATION_CN.md`。

## 2. G01—G10 对齐记录

### G01：official 独立 train/valid/test

- 修改文件：`qmap/finals_config.py`、`qmap/finals_generator.py`、`qmap/qmap_train.py`、`qmap/qmap_eval.py`、`configs/finals/capd_direction1_v3.json`、`scripts/run_finals_v2.py`、`scripts/run_finals_v3.py`。
- 实现方式：新增独立 `capd_finals_v3_0`；official 固定 `independent_valid_trace`，train 仅拟合截断值/生成训练 JSONL/训练模型，valid 用于 selector 搜索和模型选择，test 只进入最终闭环回放；解析 resolved config 时拒绝重复 trace 路径，生成时再拒绝重复内容指纹。`train_trace_decision_holdout` 仅允许 `run_profile=smoke` 且工件强制为 `smoke_only`。
- 对应测试：`FutureSplitAndSnapshotTest.test_official_sources_are_independent_and_holdout_is_smoke_only`；server-only `FinalsV3MiniEndToEndTest.test_mini_pipeline_contract_chain`。
- 静态审查结果：official 与 smoke 的配置、工件身份和 runner 入口已分离；未运行。
- 待服务器验证：三 trace 指纹拒绝、official/smoke 交叉加载拒绝、完整生成/训练/回放链。

### G02：完整未来窗口

- 修改文件：`qmap/finals_generator.py`。
- 实现方式：新增 `has_complete_future_window(t,L,N)`；v3 的 FutureOracle、selector 验证样本和 train/valid 精排 JSONL 只在 `t+L<N` 时生成标签，窗口末端固定为 `t+L`，不采用截断窗口或较短分母。
- 对应测试：`FutureSplitAndSnapshotTest.test_future_window_boundary_and_exact_label`。
- 静态审查结果：`t+L=N-1` 接受、`t+L>=N` 拒绝的代码分支和数值标签断言已写入；未运行。
- 待服务器验证：真实 trace 尾部样本数及 FutureOracle 与朴素实现的一致性。

### G03：Recall any-hit 与 TieCoverage

- 修改文件：`qmap/selector_search.py`、`qmap/finals_generator.py`。
- 实现方式：selector 验证快照同时记录池内并列最优和全 DRAM 并列最优命中信息；`SelectorRecall@K` 改为任意命中即 1，原比例语义独立命名为 `TieCoverage@K`。
- 对应测试：`LruAndMetricSemanticsTest.test_any_hit_and_tie_coverage_are_distinct_numeric_metrics`。
- 静态审查结果：两个并列最优页命中一个时明确断言 `SelectorRecall@K=1`、`TieCoverage@K=0.5`；未运行。
- 待服务器验证：NumPy 批量实现、1001 组权重搜索与固定 tie-break 的数值一致性。

### G04：精排 LRU 方向

- 修改文件：`qmap/candidate_filter.py`、`qmap/qmap_generator.py`、`tests/test_candidate_filter.py`。
- 实现方式：新增唯一 `lru_preference(rank,B_t)`，筛选器和精排四维候选状态统一使用 `1-rank/max(B_t-1,1)`；精排始终使用筛选前原始 `B_t` 和 `original_pool_rank`，不按 `K_t` 重新编号。
- 对应测试：`LruAndMetricSemanticsTest.test_lru_direction_uses_original_B_t_not_filtered_K_t`、`CandidateFilterTest.test_selector_score_not_in_state_and_original_rank_survives`。
- 静态审查结果：rank 0 数值为 1、rank `B_t-1` 为 0、中间 rank 按原始 B_t 归一化；未运行。
- 待服务器验证：所有 legacy/official 调用点是否均经过统一 helper。

### G05：history/candidate 共享页面词表与嵌入

- 修改文件：`policy_learning/cache_model/embed.py`、`policy_learning/cache_model/model.py`、`qmap/qmap_train.py`、`qmap/qmap_eval.py`。
- 实现方式：历史页嵌入由 `QMAPAccessFeatureEmbedder.page_embedder` 唯一持有；v3 候选 scorer 不再注册第二张页面嵌入表，而是接收同一 embedder 产生的 candidate embedding；checkpoint 只通过 feature embedder 保存共享页表。
- 对应测试：`SharedVocabAndEmbeddingTest.test_history_and_candidate_paths_share_the_exact_embedding_row`。
- 静态审查结果：测试检查同一 page ID 的张量完全相同、权重 data pointer 相同且 scorer 内部页表为空；未运行。
- 待服务器验证：torch state dict 装载后参数共享路径和 optimizer 参数集合。

### G06：train-only 冻结词表与 OOV

- 修改文件：`policy_learning/cache_model/embed.py`、`qmap/qmap_train.py`、`qmap/qmap_eval.py`。
- 实现方式：`DynamicVocabEmbedder` 增加显式 `fit/freeze/indices`；页面词表遍历完整 train trace 的 `page_id`，PC 词表遍历完整 train trace 的 PC；两者在任何 validation DataLoader 前向前冻结，valid/test 未见值映射到 `UNK=0`；冻结状态、映射和指纹写入 checkpoint 并在回放加载时硬校验。
- 对应测试：`SharedVocabAndEmbeddingTest.test_train_fit_freeze_oov_and_valid_forward_do_not_mutate_vocab`。
- 静态审查结果：测试断言 OOV 索引为 0，valid/test 风格前向前后词表大小和映射完全不变；未运行。
- 待服务器验证：大 trace 词表容量边界、checkpoint round-trip 和 valid/test OOV 分布。

### G07：固定正弦位置编码

- 修改文件：`policy_learning/cache_model/model.py`、`qmap/qmap_train.py`、`qmap/qmap_eval.py`、`configs/finals/capd_direction1_v3.json`。
- 实现方式：新增不可训练的 `SinusoidalPositionEncoding` buffer；按旧到新 `0..H-1` 在 Transformer 前相加，运行时转到输入相同 device/dtype；history padding mask 同时传给 Transformer 和候选页到历史的 cross-attention。legacy checkpoint 可显式使用 `position_encoding=none`，v3 checkpoint 必须为 `sinusoidal`。
- 对应测试：`PositionAndLossTest.test_fixed_sinusoidal_positions_have_exact_dtype_device_and_values`、`PositionAndLossTest.test_history_padding_cannot_change_valid_transformer_tokens`。
- 静态审查结果：位置0精确值、不同位置、dtype/device 和不可训练性断言已写入；未运行。
- 待服务器验证：不同 PyTorch 版本的 mask API、checkpoint buffer 装载和 GPU dtype/device 行为。

### G08：ApproxNDCG 排除自身和 padding

- 修改文件：`policy_learning/cache_model/qmap_loss.py`、`qmap/qmap_train.py`。
- 实现方式：pair mask 显式与非对角矩阵相交；padding 的 i/j 均排除；有效候选内部 min-max 归一化保持不变；只有至少一个有效候选的样本进入批均值；alpha 从 v3 配置固定为 10。
- 对应测试：`PositionAndLossTest.test_approx_positions_exclude_diagonal_and_padding_exactly`、`PositionAndLossTest.test_padding_values_do_not_change_approx_ndcg`。
- 静态审查结果：两候选的近似位置按 `1+sigmoid(±20)` 精确断言，第三个任意高分 padding 不改变损失；未运行。
- 待服务器验证：反向梯度、全 padding 非法输入和混合精度。

### G09：初始驻留与首次访问记账

- 修改文件：`configs/finals/capd_direction1_v3.json`、`qmap/finals_config.py`、`qmap/qmap_eval.py`。
- 实现方式：配置显式冻结 DRAM 初始为空、所有 trace 页面由 NVM 后备、首次访问计 NVM、NVM 容量无界、dirty 降级不增加 NVM 写；replay 初始化显式 NVM 页面全集，miss 按 rw 计一次 NVM 读/写，降级只增加固定迁移代价。
- 对应测试：`ReplayAccountingTest.test_first_read_write_hit_nvm_revisit_and_demotion_costs`、`DirtyAccountingTest.test_dirty_and_clean_victim_each_migrate_once_without_writeback_count`。
- 静态审查结果：五访问 trace 精确断言 1 hit、4 miss、3 NVM read、1 NVM write、2 migration，总代价为 `2+1+8+(2+10)+(2+10)=35`；clean/dirty 降级均只迁移一次；未运行。`qmap_eval.py` 回放记账实现未因本次修订改动。
- 待服务器验证：CLOCK/Random/LFU/QMAP 各策略共用记账路径且结果字段一致。

### G10：三级覆盖指标与 NRegret

- 修改文件：`qmap/selector_search.py`、`qmap/finals_generator.py`、`qmap/finals_config.py`、`qmap/qmap_eval.py`。
- 实现方式：独立计算并写入 selector 参数 `PoolRecall@B`、`SelectorRecall@K`、`EndToEndRecall@K`、`TieCoverage@K`、`NRegret`。权重选择及正式 `SelectorRecall@K`、`NRegret` 只在 `R_t^y>epsilon_y` 的有效验证决策点集合上累计和归一化，无区分样本不进入二者分母；Pool、EndToEnd 和 TieCoverage 仍作为全部完整窗口上的覆盖诊断。result 以 `valid_trace` 为明确来源记录这些指标，避免伪装成 test 未来标签。
- 对应测试：`LruAndMetricSemanticsTest.test_pool_selector_end_to_end_and_regret_are_separate`、`LruAndMetricSemanticsTest.test_any_hit_and_tie_coverage_are_distinct_numeric_metrics`、`SelectorWeightSearchTest.test_nondiscriminative_sample_is_excluded_from_selector_recall`。
- 静态审查结果：原构造样本继续精确断言四项覆盖率分别为 0.5、0.5、0.5、0.25，NRegret 为 0.5；新增“一个有效样本+一个无区分样本”断言 `effective_decision_points=1`、`nondiscriminative_ratio=0.5`、`SelectorRecall@K=0.0`、`NRegret=1.0`，防止错误得到 0.5；未运行。
- 待服务器验证：大 valid trace 上的批处理累计、无区分样本 fallback 和 JSON 序列化。

## 3. 工件合同与不兼容边界

- `capd_finals_v3_0` 配置、selector、JSONL metadata、checkpoint、result 均绑定：schema、`CAPD-MIC-1.0`、run profile、artifact class、workload ID、配置指纹和代码提交标识。
- selector 指纹还绑定 train/valid trace 指纹、验证样本指纹、截断值、五维权重、五项指标和选择规则。
- checkpoint 绑定 selector、train/valid JSONL、共享冻结词表及其指纹、模型结构、seed、best epoch/validation loss。
- result 绑定 selector、checkpoint、test trace、成本模型和回放初始语义；official 汇总器拒绝 `smoke_only`。
- v3 JSONL 必须使用 `history_page_ids` 和 `history_mask`；只要 v3 样本带有旧 `physical_address` 字段即硬失败。
- `scripts/run_finals_v2.py` 明确只接受 `capd_finals_v2_1`；`scripts/run_finals_v3.py` 明确只接受 official `capd_finals_v3_0`。
- 没有迁移、重写或重新生成任何 v2.1 resolved config、JSONL、checkpoint 或 result；v2.1 与 v3 不允许交叉加载。

对应测试：`ArtifactIdentityTest.test_checkpoint_contract_config_workload_selector_mismatches_hard_fail`、`ArtifactIdentityTest.test_jsonl_metadata_and_result_mismatches_hard_fail`、`ArtifactIdentityTest.test_v2_and_v3_artifacts_are_mutually_incompatible`、`V3JsonlSchemaTest.test_v3_accepts_history_page_ids_and_rejects_old_field`。

## 4. Gate C1—C3 测试构造覆盖

- Gate C1：LRU 方向、tie any-hit/TieCoverage、future guard、共享嵌入、冻结词表/OOV、正弦位置编码、ApproxNDCG 对角线与 padding 均有具体数值断言。
- Gate C2：生成器/回放共享候选快照已有逐字段等价测试；当前请求进入精排 history 而不提前进入 selector 有独立测试；首次读写、命中、再次 NVM 访问、clean/dirty 降级有手算计数和总代价测试。
- Gate C3：独立 trace 路径/内容指纹、official/smoke、schema/合同/配置/workload/selector/JSONL/checkpoint/result 硬失败及 v3 旧字段拒绝均有测试。
- Gate C4：server-only 微型端到端 trace 已改为 440 次访问，包含 DRAM 填充、流式冷页、分层热页重访和写访问；除全链路与两次固定种子断言外，还要求 selector 不使用 uniform fallback、有效决策点大于 0、验证样本存在非零 relevance range，并在生产模型路径的一次优化步中断言 loss/梯度有限、梯度非零且至少一个参数改变。默认 skip，只有服务器显式设置 `CAPD_RUN_STAGE1_E2E=1` 才执行，所有工件写入 pytest 临时目录。

新增或修改的主要测试文件：

- `tests/test_capd_stage1_v3_semantics.py`
- `tests/test_capd_stage1_v3_model.py`
- `tests/test_capd_stage1_v3_end_to_end.py`
- `tests/test_candidate_filter.py`
- `tests/test_checkpoint_config_contract.py`
- `tests/test_selector_weight_search.py`
- 复用现有 `tests/test_generator_replay_feature_equivalence.py`、`tests/test_dirty_accounting.py` 和 cross-attention 测试。

## 5. 静态无法确认及合同口径问题

### 5.1 必须由服务器确认

- 所有 Python 文件的语法和导入关系；
- NumPy selector 有效集 Recall/NRegret 累计及混合样本回归的实际数值；
- PyTorch Transformer mask API、共享 embedding 梯度与 state dict；
- 冻结词表 checkpoint round-trip；
- ApproxNDCG 前向/反向和数值稳定性；
- 非平凡微型端到端链、非 fallback selector、非零训练信号和固定种子确定性；
- 全量 pytest 对旧 v2.1 路径的回归影响；
- 真实 train/valid/test trace 的来源与时间范围是否确实不重叠。代码只能检查路径和内容指纹，无法仅凭文件静态证明采集时间边界。

### 5.2 合同内部张力

发现一处需要合同维护者确认的报告口径张力：第 3.3 节规定 test 闭环回放不生成未来标签，而第 5.5 节又要求正式结果报告四个候选覆盖指标与 NRegret。当前实现不在 test 偷看未来访问；result 明确记录来自 `valid_trace` 的 selector 覆盖指标并标注 `candidate_coverage_metric_source=valid_trace`。如果合同原意是要求 test 上的 oracle 覆盖率，则会与“test 不生成未来标签/不读取未来信息”的冻结语义冲突，需要提升或澄清合同后再改，不能静默推断。

除该报告来源口径外，静态阅读未发现 G01—G10 公式之间的直接矛盾。

G11（闭环分布偏移审计）和 G12（代理标签—反事实代价审计）仍按冻结合同属于后续阶段的正式实验/审计工作，本阶段未执行，也未声称实现验证。

## 6. 阶段2开始前必须满足的条件

1. 完整执行 `docs/CAPD_STAGE1_SERVER_VALIDATION_CN.md` 的 3.1—3.8，所有失败均修复并重新执行。
2. 对上述 test 覆盖指标来源张力给出合同维护者的书面确认；若改变冻结语义，先提升合同版本。
3. 确认 v3 official runner、smoke fallback 和 v2.1 runner 的互斥测试通过。
4. 确认共享词表在 valid/test 前后不变化，checkpoint round-trip 后 OOV 仍为 `UNK=0`。
5. 确认 generator/replay 候选快照和当前请求时序测试通过。
6. 确认首次访问、clean/dirty 降级和五访问手算代价测试通过。
7. 确认仓库没有新生成或改写 `dataset/`、`outputs/`、`results/`、`logs/`、resolved config、checkpoint 或 result。
8. 只有上述条件满足后，才可进入阶段2重新选择/采集并构造正式 train/valid/test 数据；不得复用 v2.1 JSONL 或 checkpoint。

## 7. 结论

当前阶段状态：`IMPLEMENTED_UNVERIFIED`
