# CAPD 阶段2符合性报告

## 1. 当前状态

状态：`IMPLEMENTED_UNVERIFIED`

本地仅完成静态阅读、代码/配置/测试/文档修改和差异审查，没有执行 Python、pytest、数据生成、Trace Replay、selector 搜索、训练、推理或实验。因此本报告不声称任何正式 workload 已通过，不声称阶段2为 `VERIFIED`，也不产生性能结论。

唯一依据为 `docs/CAPD_METHOD_IMPLEMENTATION_CONTRACT_CN.md` 中冻结的 `CAPD-MIC-1.0`，目标 schema 为 `capd_finals_v3_0`。冻结合同的方法语义未修改。

## 2. 静态实现结果

### 2.1 来源、切分与真实 RW

- 新增 exact-slice 工具，从显式 `PC,Address,RW` 源 trace 物化互不重叠的半开区间，不接受 RW fallback；
- 新增 source spec 与 manifest 构造入口，记录采集身份、工具、完整命令、时间/来源标识、环境、原始与 split 双指纹、区间、记录数、page shift、合同、schema、commit 和质量门禁；
- manifest 构造与复核会逐记录证明 split 等于声明的源区间；独立性依据采集身份和源区间，不依据路径差异、文件哈希差异或重复访问值；
- official 配置只指向 `dataset/processed/finals_v3_official` 与 `dataset/metadata/finals_v3_official`，不把旧 processed 文件直接提升为 official。

### 2.2 确定性质量审计

`qmap/finals_data.py` 和 `scripts/audit_finals_v3_data.py` 已静态实现：规模与指纹、真实读写、D=64 LRU 压力、`t+L<N` 标签边界、有效 relevance、并列最优、B/K 分布、热点与重用、train-only 词表/OOV、split 漂移与来源独立性报告。

硬约束失败为 `REJECTED`；工程样本量/压力/有效标签不足为 `INSUFFICIENT`；分布风险按当前 profile 产生 warning。推荐门槛独立配置于 `configs/finals/capd_stage2_data_profile.json`，没有写入冻结方法公式。

### 2.3 工件隔离与绑定

- resolved v3 config 必须加载状态为 `PASSED` 的 manifest，并复核源文件、split、报告、profile 与当前 Git commit；
- selector、JSONL metadata、generator summary 以及后续 checkpoint/result 身份均携带 manifest、split、profile、报告、配置、合同、workload、run profile 与 commit 绑定；
- generator 在独立 valid trace 上按完整未来窗口生成机械性 selector 样本，再进行生成 K=8 JSONL 所必需的固定网格搜索，最后生成 train/valid JSONL；
- 新增工件复核入口，流式检查 JSONL 行、metadata 指纹和 v2/v3 混用；未修改或覆盖旧 v2.1 配置与工件。

### 2.4 合成测试构造

新增的小规模确定性测试覆盖：源区间重叠、路径不同仍重叠、缺失真实 RW、manifest/trace 指纹变化、短 trace、`unique_pages<=D`、无 victim decision、未来窗口边界与精确计数、报告可复现、OOV、无重用与极端写、报告封存、防篡改、JSONL 指纹变化和 v2/v3 绑定冲突。测试尚未在本地执行。

## 3. 当前三个候选的静态初判

| workload | 静态状态 | 依据与处理 |
|---|---|---|
| canneal | `REJECTED` | legacy valid 只有 30 个唯一页，`30<=D=64`，不可能产生 victim decision；必须重新选择高压力区间或重新采集 |
| streamcluster_pressure | `INSUFFICIENT` | legacy train/valid/test 唯一页为 102/91/193，只有表面压力条件；缺采集命令、采集身份、完整源/split 指纹和全量审计，不能提升为 official |
| dedup_pressure | `REJECTED` | legacy valid 只有 54 个唯一页，`54<=D=64`；精确 0.5 写比例还必须核验真实 RW 来源，不能仅凭旧 metadata 接受 |

静态状态记录在 `configs/finals/capd_stage2_candidate_inventory.json`。以上判断不替代全量服务器审计；`streamcluster_pressure` 也尚未被接受。

## 4. 尚未验证

- 新增 Python 的语法、导入与实际单元测试结果；
- 新采集/重新切分 trace 的真实来源、真实 RW、区间和全文件指纹；
- D=64、L=256 下实际压力、完整窗口、有效标签、OOV、热点、长尾和漂移；
- 机械性 selector 样本与 train/valid JSONL 的实际生成、规模和确定性；
- 封存后的 manifest/config/selector/JSONL 指纹链；
- 服务器执行后的 Git 污染情况。

阶段2明确不验证精排训练、QMAP 正式测试、B sweep、消融、系统性能或比较结论。

## 5. VERIFIED 门禁

只有 `docs/CAPD_STAGE2_SERVER_VALIDATION_CN.md` 的顺序全部完成，且每个保留在 official v3 配置中的 workload 都同时满足以下条件，阶段2状态才可由人工更新为 `VERIFIED`：

1. 合成测试通过；
2. source spec 具有真实、完整且可复核的采集记录；
3. manifest 的来源、真实 RW、区间、文件和记录指纹全部通过；
4. 数据审计状态为 `PASSED`，无硬失败或充分性失败；
5. manifest 用该报告封存后，resolved config 能重新加载并绑定当前 commit；
6. selector 验证样本、selector、train/valid JSONL 和 summary 生成成功；
7. 工件复核通过，所有指纹一致且无 v2 字段/工件混用；
8. 未覆盖 v2.1 工件，仓库没有意外 cache、日志、checkpoint、result 或 resolved config 污染。

在服务器证据回填前，状态保持 `IMPLEMENTED_UNVERIFIED`。

## 6. 阶段3前置工件

每个进入阶段3的 workload 必须具备：封存为 `PASSED` 的 source manifest、完整数据审计报告、绑定后的 resolved v3 config、独立 valid selector 样本、冻结 selector 参数、train/valid reranker JSONL、generator summary 和工件复核报告。不得携带 v2.1 JSONL、selector、checkpoint 或 result；阶段2不应产生精排 checkpoint 或正式性能 result。
