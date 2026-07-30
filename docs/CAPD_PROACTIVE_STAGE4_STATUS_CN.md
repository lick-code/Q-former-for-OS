# CAPD 主动降级阶段 4 当前状态

## 当前状态

`stage4_verified`

2026-07-30，Linux 服务器正式运行
`outputs/capd_proactive_stage4/stage4-f8-f16-r3/` 已完成并输出
`[FINAL] STAGE4_VERIFIED`。本地只审计服务器同步工件，没有重新执行 Python、
PyTorch、训练、推理或 Trace Replay。

正式运行的 `run_state.json` 已记录以下七项全部完成：

- `preflight`；
- `lookahead`；
- `label_weights`；
- `candidate_history`；
- `final_rebuild`；
- `server_tests`；
- `verification`。

服务器阶段 1～4 回归共运行 113 项测试并通过。最终验证同时确认：

- Test 未参与数据生成、训练、参数选择或 checkpoint 选择；
- 未使用历史 `finals_v3` Stage 4 工件；
- selector 保持 disabled；
- Train/Validation 来源区间互不重叠；
- 最终冻结候选、测试回执、数据集和 checkpoint 指纹链一致；
- 三个 seed 均未检测到 NaN 或 Inf。

## 旧阶段 4 冲突审计

历史阶段 4 的以下语义不能进入当前正式流程：

- `finals_v3` 数据/配置/合同身份；
- `B=64 → selector → K=8`；
- 候选筛选器参数和 selector fingerprint；
- full-DRAM 单 victim 决策点；
- 固定 `L=256/K=8` 的旧结论；
- 旧 `STAGE4_VERIFIED` 状态；
- `outputs/results/finals_v3_official/stage4_audits/` 的结果。

可以复用的只有通用模型、ranking loss、训练循环、每 epoch checkpoint、Validation
loss 选 best、RNG 状态恢复、checkpoint manifest、统计工具和 SHA-256 思路。当前
流程对这些复用部件增加了主动 Stage4 contract 和 Train-only 词表冻结。

## 正式冻结结果

阶段 4 按预声明的全局 Validation 规则选择并冻结：

- Lookahead：`L=256`；
- 标签权重：`lambda=(1,1,2)`；
- 正式候选数：`K=8`；
- 历史长度：`H=20`；
- 页面状态维度：4；
- 模型上下文：cross-attention；
- 训练 seed：`3136859/42/2026`。

主动降级机制继续冻结为：

- `F_low=8`、`F_target=16`、`b_max=4`；
- low-watermark 触发；
- LRU-tail 候选；
- selector disabled；
- LRU emergency fallback；
- Proactive-LRU 训练轨迹。

DRAM 比例 20% 仍是条件工程默认，不解释为 `capacity_rule_v2` 已通过。
三个 seed 用于描述稳定性，不解释为强统计显著性结论。当前数据上标签存在较多并列，
因此 `lambda=(1,1,2)` 是在既定网格与 tie-break 下的正式冻结结果，不外推为普遍最优。

## 正式工件

- 运行清单：
  `outputs/capd_proactive_stage4/manifests/stage4-f8-f16-r3.json`；
- 最终运行目录：
  `outputs/capd_proactive_stage4/stage4-f8-f16-r3/`；
- 选择记录：`selections/lookahead.json`、`selections/label_weights.json`、
  `selections/candidate_history.json`；
- 最终重建：`final_rebuild/L256_lam1-1-2_K8_H20/`；
- 冻结候选：`final_freeze_candidate.json`；
- 测试回执：`server_test_receipt.json`；
- 最终验证：`verification.json`。

两个失败运行 `stage4-f8-f16-001`、`stage4-f8-f16-r2` 及其 manifest 已从本地
正式工件树移除；数值修复包和编排修复包也已移除。部署归档不属于正式证据链，
阶段状态只以本次 `r3` 的 `run_state.json`、冻结候选和 `verification.json` 为准。

## 封存边界

阶段 4 的实现、真实 Train/Validation 训练、参数选择、最终重建、服务器测试、
指纹审计和污染审计均已完成，可正式封存，不需要继续训练或重跑。

`configs/finals/capd_proactive_stage4.json` 是运行前预声明协议，代码要求其中
`stage_status` 保持 `stage4_implemented_awaiting_training_inputs`，不得把它当作
动态状态文件回写。阶段 0/3 中的 `pending` 同样是历史阶段快照，不应修改。
若以后改变输入数据、源码、冻结水位、标签网格或训练合同，必须使用新 run ID
重新执行并生成新的独立验证链，不得覆盖本次 `r3` 工件。
