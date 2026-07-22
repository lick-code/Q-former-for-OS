# CAPD 阶段2符合性报告

## 1. 最终状态

状态：`VERIFIED_REUSABLE`（原服务器验收结论保持有效，R1 不要求重采、重切或重生成）

R1 统一阶段门禁：阶段0=`DONE_R1`；阶段1=`REOPENED_G13`；阶段2=`VERIFIED_REUSABLE`；阶段3必须等待 `STAGE1_R1_VERIFIED`，此前不得启动正式运行或结论汇总。

- 完成日期：2026-07-22
- 验收环境：Linux 服务器，仓库 `/home/likc/Q-former-for-OS`
- 生成代码身份：`2bd07f29a639d54db5180b57651842ce95dd3014`
- 跨平台验收修复：`c34f2bef25b752d10b8b78c7503c979ecc4a38ec`
- 最终命令：`python scripts/verify_finals_v3_stage2.py`
- 最终标志：`[FINAL] STAGE2_VERIFIED`
- 服务器证据目录：`/tmp/capd-stage2-acceptance-r6i_xzg8`

本报告依据 `CAPD-MIC-1.0` 文档修订 R1 和 `capd_finals_v3_0` 合同确认阶段2已经完成且工件可继续使用。R1 只新增闭环推理的 G13 精排最高分并列规则，不改变 trace、split、selector valid 标签域、精排 train/valid 标签域、完整未来窗口门禁、JSONL 内容或工件 schema，因此既有服务器验收和数据工件不重采、不重切、不重生成。该结论只覆盖正式数据来源、切分、质量审计、selector 机械性样本、train/valid JSONL 及其制品绑定，不包含精排训练或性能结论。

## 2. 正式数据验收结果

三个 official workload 均使用 DynamoRIO drmemtrace 采集的显式 `PC,Address,RW` trace，`page_shift=12`，并在 `D=64`、`L=256` 的冻结口径下通过来源、真实 RW、源区间、文件指纹、压力、标签充分性、分布与漂移审计。

| workload | 原始访问数 | train / valid / test | 原始 trace SHA-256 | 数据审计 |
|---|---:|---:|---|---|
| canneal | 1,000,000 | 600,000 / 200,000 / 200,000 | `f8dba14d3ca4271526b124f653917f0e874395b046fb0dc8a19df7da5e513efd` | `PASSED` |
| streamcluster_pressure | 1,000,000 | 600,000 / 200,000 / 200,000 | `ca6ea6cf3da47adfe6d0b3e198619f6bde63f0ffeb17a232acb592dafd75f8d6` | `PASSED` |
| dedup_pressure | 3,000,000 | 1,000,000 / 1,000,000 / 1,000,000 | `5ab03f12ca848ab5e3621af607229cebf6017ab514f3c38d5854574a7754ff32` | `PASSED` |

三个 source manifest 均通过封存复核：

- `sealed_manifest_canneal`
- `sealed_manifest_streamcluster_pressure`
- `sealed_manifest_dedup_pressure`

## 3. Selector 与 JSONL 制品

每个 workload 均完成 `B={8,16,32,64}` 四个相互隔离的制品集合，共 12 组。每组包含 resolved config、selector 参数、selector 验证样本、train/valid JSONL 及 metadata、generator summary；服务器重新计算的 12 份制品审计均与封存报告一致。

| workload | 每个 B 的 train 样本 | 每个 B 的 valid 样本 | B=8 | B=16 | B=32 | B=64 |
|---|---:|---:|---|---|---|---|
| canneal | 7,215 | 2,377 | `PASSED` | `PASSED` | `PASSED` | `PASSED` |
| streamcluster_pressure | 8,694 | 2,839 | `PASSED` | `PASSED` | `PASSED` | `PASSED` |
| dedup_pressure | 4,607 | 2,654 | `PASSED` | `PASSED` | `PASSED` | `PASSED` |

跨 Windows/Linux 的 Git 换行规范化和生成路径差异已经纳入验证逻辑：文本封存允许内容不变的 LF/CRLF 传输转换；二进制与 CSV trace 仍执行严格字节 SHA-256；resolved artifact 仍严格绑定其生成 commit、manifest、split、profile、报告和配置身份。

## 4. 服务器回归与仓库边界

最终一次性验收得到：

- 生成 commit 为当前 `HEAD` 的祖先：通过；
- 3/3 sealed manifest：通过；
- 3/3 数据审计：通过；
- 12/12 制品审计：通过；
- 完整回归：`78 passed, 2 skipped in 1.96s`；
- `git diff --check`：通过；
- 工作区清洁：通过；
- 阶段2训练/checkpoint/result 输出：不存在。

阶段2没有覆盖或迁移 v2.1 工件，也没有运行精排训练、QMAP 正式性能测试、B sweep、消融或策略比较。

## 5. 阶段3交付状态

三个 workload 均已具备阶段3所需的完整前置工件：

- `PASSED` source manifest 与数据审计报告；
- train/valid/test official split；
- 四个 B 的 resolved v3 config；
- 独立 valid selector 样本与冻结 selector 参数；
- train/valid reranker JSONL 与 metadata；
- generator summary 与 `PASSED` 制品审计报告。

因此阶段2保持正式关闭并标记为 `VERIFIED_REUSABLE`，上述前置工件继续有效。但当前阶段1因 G13 暂时重开；在 G13 修复、针对性测试和服务器验收完成并将阶段1更新为 `STAGE1_R1_VERIFIED` 前，不得启动阶段3正式运行或结论汇总。该门禁不要求重做阶段2。
