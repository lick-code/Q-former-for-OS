# CAPD Stage 4 r2 有效 Validation 集合协议修复报告

## 修复结论

`stage4-stage7-unified-r1` 在训练前样本结构门发现七套 semantic 缓存均具有同一结构：

- `streamcluster_pressure/train > 0`，`validation = 0`；
- `fluidanimate/train > 0`，`validation = 0`；
- 其余四个 workload 的 Train/Validation 均大于 0。

r1 保持原文件和原状态，不覆盖、不确认、不训练、不 freeze。r2 新身份为
`stage4-stage7-unified-r2`，合同版本为 `CAPD-PROACTIVE-STAGE4-STAGE7-1.1`。

## r2 范围

- 统一模型训练：六个 workload 全部保留；
- checkpoint Validation loss：只合并 `canneal`、`dedup_pressure`、`blackscholes`、
  `swaptions`；
- candidate 主成本、最差 workload 成本、macro NDCG 和全部 tie-break：只使用上述四个
  active selection workload；
- `streamcluster_pressure`、`fluidanimate`：Validation 指标写为 JSON `null`/`N/A`，
  `valid_decision_count=0`、`model_invoked=false`、`selection_eligible=false`；
- 结构性零决策集合必须严格等于这两个 workload。二者任一突然非零，或四个 active workload
  任一为零，都 fail closed；
- Stage 8 Standard 保留六个 workload；Stage 8 Pressure 保留四个正式派生 workload。

## 审计边界

修复发生在任何模型训练、checkpoint、candidate 性能、Test 或 Pressure 访问之前。该规则不是 r1
原搜索合同的预注册规则，r2 在再次人工确认前保持 `search_contract_confirmed=false` 和
`formal_freeze=false`。

r2 搜索配置：`configs/finals/capd_proactive_stage4_stage7_search_r2.json`。
本地 SHA-256：`86b5a7341e8c7eceb9df9827dbbeaa2c4e131531b00fded5ffb1afc4a488ca3a`。

r2 preflight 不再重复逐行解析与 r1 完全相同的 14,400,000 条 Train/Validation
记录。它仍先对当前 12 个源文件逐一验证 SHA-256，然后验证固定 SHA
`697024bca51f2ceeb5cf4b7acd839fdb7ee293848a25968a27a71eca022db851`
对应的 r1 `resolved_config.json`，并逐项绑定 r1 已完成的 12 份完整轨迹解析证据。
这只消除重复解析，不放宽源文件身份、访问数、RW 来源或 Test/Pressure 隔离检查。

## 缓存处理

r2 通过 `external_cache_reference.json` 只读引用 r1 的约 7.2 GB 缓存。服务器复核逐文件验证
R4、R2 manifest、prepared input manifest、L/H/lambda、D/F_low/F_target、`b_max=2`、
`K=8`、Train/Validation 源、词表及样本 SHA。r2 的 `datasets/` 与 `vocabulary/` 不应出现
复制文件。

服务器操作以 `docs/CAPD_PROACTIVE_STAGE4_STAGE7_R2_SERVER_CN.md` 为唯一 r2 手册。
