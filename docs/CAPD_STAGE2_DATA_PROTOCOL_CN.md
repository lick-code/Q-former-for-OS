# CAPD 阶段2正式数据协议

## Material Passport

- 依据：`CAPD-MIC-1.0` 第8节“阶段2：重新构造正式数据”
- 目标 schema：`capd_finals_v3_0`
- 数据 manifest schema：`capd_finals_v3_data_manifest_1`
- 数据审计 schema：`capd_finals_v3_data_audit_1`
- 当前实现状态：`VERIFIED_REUSABLE`（2026-07-22 Linux 服务器验收通过；R1 下继续有效）
- 适用范围：正式 train/valid/test trace、selector 验证样本和精排 JSONL

R1 统一阶段门禁：阶段0=`DONE_R1`；阶段1=`REOPENED_G13`；阶段2=`VERIFIED_REUSABLE`；阶段3必须等待 `STAGE1_R1_VERIFIED`，此前不得启动正式运行或结论汇总。

## 1. 阶段边界

阶段2只完成正式数据来源证明、切分、质量审计以及生成 selector 验证样本和精排 JSONL 所必需的机械性 selector 搜索。阶段2不训练精排模型，不运行 QMAP 正式测试，不比较 selector 方案，不执行 `B` sweep/消融，不输出性能结论。

`CAPD-MIC-1.0` 文档修订 R1 不改变本协议的数据语义：selector valid 标签仍覆盖扩展候选池 `P_t` 全部页面，精排 train/valid 标签仍只为筛选后的有效候选集合 `C_t` 构造并保存，两条路径仍只接收具有完整 `L` 条未来访问的决策点。R1 新增 G13 只影响闭环推理的最终 victim 单值选择，不影响已封存 trace、split、manifest、selector、JSONL 或审计指纹；既有工件不重采、不重切、不重生成。

以下工件不得读取、改写或迁移为 v3 official：

- `finals_v2_decision_holdout` JSONL；
- v2.1 selector、checkpoint、result 和 resolved config；
- 既有 smoke trace、微型 E2E trace；
- 无法证明真实 RW、来源身份和源区间独立性的旧 trace。

## 2. 来源 manifest 合同

每个 workload 使用一个 manifest。manifest 至少包含：

- `workload_id`、`artifact_schema=capd_finals_v3_0`、`contract_id=CAPD-MIC-1.0`；
- `git_commit`、`page_shift`、`run_profile=official`、`artifact_class=official`；
- 每次采集的 `collection_id`、采集工具、完整命令、采集时间或来源标识、环境说明；
- 每个原始 trace 的路径、文件 SHA-256、规范化记录 SHA-256、文件大小和原始访问总数；
- train/valid/test 的路径、文件 SHA-256、规范化记录 SHA-256、记录数；
- 每个 split 的 `collection_id` 和半开源区间 `[start_inclusive,end_exclusive)`；
- 切分策略、真实 RW 字段声明和质量门禁状态；
- 数据审计 profile、报告路径和报告指纹。

`scripts/create_finals_v3_source_spec.py` 负责生成明确的来源 spec；`scripts/build_finals_v3_manifest.py` 扫描原始 trace 与 split，验证记录数，并逐记录验证 split 内容确实等于声明的源区间。任何路径、文件指纹、记录指纹、记录数或源区间内容不一致均硬失败。

`scripts/split_finals_v3_trace.py` 可从一条带真实 `RW` 的原始 trace 一次扫描物化三个半开源区间。它不提供 RW fallback，输出固定进入 `dataset/processed/finals_v3_official/<workload>/`；随后仍必须用 manifest 构造器逐记录反向验证，不能把“脚本成功写文件”当成来源证明。

### 2.1 独立性判定

独立性只依据以下证据：

1. 同一 `collection_id` 内的 train/valid/test 使用互不重叠的半开源区间；或
2. split 来自不同独立采集，并具有不同 `collection_id`，每次采集分别记录原始文件指纹和采集身份。

仅有“路径不同”或“哈希不同”不能证明独立；正常 trace 中重复出现相同 PC/address/RW 模式也不构成泄漏证据。即使两个独立采集恰好产生相同内容，也以采集身份和源区间证据为准。

### 2.2 RW 约束

official trace 必须具有显式 `RW` 列，且 manifest 声明：

```json
{"kind": "trace_column", "column": "RW", "verified_real": true}
```

`page & 1`、固定 `R`、默认值补全或任何模拟 RW 只允许 smoke，manifest 构造和 official 审计会直接拒绝。

## 3. 硬约束与数据验收 profile

方法硬约束与工程充分性分开：

- 硬约束失败：状态 `REJECTED`。包括 schema/合同/工作负载不一致、缺失真实 RW、源区间重叠、split 不等于声明源区间、任一 manifest/trace 指纹不一致、v2/v3 混用。
- 工程充分性失败：状态 `INSUFFICIENT`。包括 trace 太短、唯一页数不超过 `D`、无 victim decision、完整窗口或有效标签样本不足、词表超容量。
- 分布风险：默认产生 warning，不静默降低门槛。包括近乎全流式、热点过度集中、极端读写比例和明显 split 漂移。

配置文件为 `configs/finals/capd_stage2_data_profile.json`。当前推荐值如下：

| split | 最少访问 | 最少 victim decision | 最少完整窗口 decision | 最少有效标签 decision |
|---|---:|---:|---:|---:|
| train | 100,000 | 4,096 | 4,096 | 1,024 |
| valid | 100,000 | 1,024 | 1,024 | 256 |
| test | 100,000 | 1,024 | 不用于生成标签 | 不用于选择参数 |

依据：`D=64`、`L=256` 时，理论上至少需要 `D+L+1=321` 次访问才可能在填满 DRAM 后留下一个完整未来窗口；该理论下限不足以支持 K=8 的筛选和训练。当前 profile 进一步要求千级以上决策点，使 train/valid 分别保留足够的完整窗口和非平凡相关性样本，同时与当前 100k—800k split 规模一致。门槛是显式、可版本化的工程验收标准，不属于冻结方法公式；若要修改，必须更新 profile ID、理由和所有数据审计报告。

补充分布阈值：`nondiscriminative_ratio<=0.95`、reuse event ratio 至少 `0.01`、Top 1% 页面访问占比不高于 `0.90`；写比例低于 `0.01` 或高于 `0.99` 产生极端写比例诊断。train/valid/test 的写比例、决策密度和 Top 1% 热点占比跨度超过 `0.25` 产生漂移 warning。

## 4. 数据质量报告

统一入口为 `scripts/audit_finals_v3_data.py`。算法确定、无随机数，不调用训练或推理路径。每个 split 报告：

- 规模与身份：访问数、唯一页、唯一 PC、文件大小、文件 SHA-256、记录 SHA-256；
- 读写：读写数/比例、真实 RW 来源、每页写次数分布；
- D=64 LRU：hit/miss、miss ratio、victim decision、decision ratio、首次填满位置；
- 标签：`t+L<N` 完整窗口决策数、尾部丢弃数/比例、`R_t^y>epsilon_y` 有效决策数、无区分比例、并列最优集合大小；
- 候选：`B∈{8,16,32,64}` 的 `B_t` 分布和 K=8 的 `K_t` 分布；
- 热点长尾：页面访问数分位数、Top 1%/5%/10% 占比、单次页比例、等价重用间隔分位数；
- 诊断：低压力、近乎全流式、热点过度集中、极端写比例。

跨 split 报告：

- valid/test 相对 train 的 page/PC access OOV 和 unique OOV；
- train page/PC 词表是否超过配置容量；
- 明确记录 `train_only_valid_test_do_not_extend`；
- 读写比例、决策密度、热点占比的漂移；
- collection 身份和源区间独立性证据。

test 的未来标签统计只作为数据质量描述，不进入 selector、词表、阈值、模型选择或生成参数。正式 test replay 仍不读取未来信息。

## 5. 生成工件与依赖顺序

正式生成顺序固定为：

```text
真实采集/切分
  -> source spec
  -> source manifest + 源区间逐记录验证
  -> 数据质量审计并将 manifest 封为 PASSED
  -> resolved v3 config（绑定 manifest/profile/report/split 指纹）
  -> train 截断值
  -> 独立 valid 上的固定快照与机械性 1001 组 selector 搜索
  -> 冻结 selector
  -> train/valid reranker JSONL
  -> 工件指纹复核
```

精排 JSONL 依赖 selector 权重，因此 selector 搜索先于 JSONL。这里的搜索只为生成 K=8 候选所必需；结果不得解释为阶段3 selector 性能结论。

selector、验证样本、JSONL metadata、generator summary、后续 checkpoint/result 都必须绑定：封存后 source manifest 文件指纹、三个 split 指纹、data profile ID 与 profile 指纹、data report 指纹、配置指纹、合同、workload、run profile 和 git commit。审计报告使用排除可变 `quality_gate` 的稳定源数据身份指纹，避免“报告哈希写回 manifest 后又改变报告输入”的循环；生成工件则绑定封存后的 manifest 整文件指纹。`scripts/verify_finals_v3_artifacts.py` 流式复核 JSONL schema，拒绝 `physical_address` 等 v2 字段，并验证 metadata/selector/manifest 指纹链。

正式 trace、manifest、JSONL、checkpoint 和 result 的目录均带 `finals_v3_official`，不得在原位置覆盖 legacy/v2 文件。旧 processed trace 只能作为静态候选或来源线索；通过重新物化、来源验证和审计之前，不是 official 输入。

## 6. 验收前候选数据静态初判（历史记录）

本节保留阶段2实施前对 legacy 候选数据的静态判断，用于解释为何需要后续正式采集、切分和审计；它不表示 2026-07-22 已封存的 official 数据当前仍为 `REJECTED/INSUFFICIENT`。最终 official 状态以三份 `PASSED` source manifest、数据审计报告和阶段2符合性报告为准。

| workload | 静态状态 | 依据 |
|---|---|---|
| canneal | `REJECTED` | legacy manifest 中 valid 只有 30 个唯一页，`30<=D=64`，不可能产生 victim decision |
| streamcluster_pressure | `INSUFFICIENT` | train/valid/test 唯一页分别为 102/91/193，具备最低表面压力；但缺采集命令、采集身份和原始/split 指纹，且尚未服务器审计 |
| dedup_pressure | `REJECTED` | legacy manifest 中 valid 只有 54 个唯一页，`54<=D=64`，不可能产生 victim decision；精确 0.5 写比例也需来源审计而不能仅凭表面接受 |

这些判断只来自现有 metadata 和少量 trace 头部，不替代服务器全量审计。若重新切分无法让每个 split 通过 profile，应重新采集；不得降低门槛、伪造来源或把 smoke 数据提升为 official。

## 7. 状态门禁

阶段2仅在以下条件全部满足时进入 `VERIFIED`；R1 收口后对外状态记为 `VERIFIED_REUSABLE`：

1. 来源 manifest 结构、真实 RW、源区间和全部指纹验证通过；
2. 三个 split 的审计状态均汇总为 `PASSED`，无硬失败或充分性失败；
3. 合成测试通过；
4. resolved v3 config 成功绑定封存后的 manifest 和报告；
5. selector 样本与 train/valid JSONL 生成成功；
6. `verify_finals_v3_artifacts.py` 通过，重新计算的指纹与所有 metadata 一致；
7. 仓库没有 v2 工件改写或意外运行工件污染；
8. 阶段2符合性报告根据服务器证据由 `IMPLEMENTED_UNVERIFIED` 人工更新为 `VERIFIED`。

以上门禁已由 `python scripts/verify_finals_v3_stage2.py` 一次性验收全部通过；最终标志为 `[FINAL] STAGE2_VERIFIED`，完整回归结果为 `78 passed, 2 skipped`。这些既有服务器事实保持不变。当前阶段2状态为 `VERIFIED_REUSABLE`；在阶段1 G13 修复并达到 `STAGE1_R1_VERIFIED` 前，不得启动阶段3正式运行或结论汇总，但无需重新执行本协议的数据采集、切分或生成步骤。
