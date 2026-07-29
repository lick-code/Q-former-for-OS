# CAPD 主动降级实验阶段 2 Cost 冻结报告

日期：2026-07-29

权威方案：`CAPD_主动降级版本_完整实验实施方案(1).md`

当前状态：`stage2_verified`

## 1. 阶段目标与结论

阶段 2 已完成独立实现及阶段 1 Replay summary 联调：

1. 冻结正式评价 Cost 公式；
2. 冻结 default 及三组敏感性 Cost profile；
3. 冻结规范化原始事件输入契约；
4. 实现严格配置加载和校验；
5. 实现单 profile 与多 profile 的纯离线整数重算；
6. 实现 JSON、JSONL 和 CSV 输入 CLI；
7. 提供合成 fixture、单元测试和服务器验证脚本；
8. 完成阶段 0、阶段 1、历史 Cost 和历史 Replay 记账语义回归；
9. 使用阶段 1 正式 `capd_proactive_stage1_log_v1_0` summary 完成薄适配；
10. 四个阶段 1 合成场景均通过 default 及三组敏感性 profile 重算；
11. 将公共配置中的阶段 2 Cost profile 状态冻结。

阶段 1 的主动 Replay 输出字段、三类 demotion 定义、汇总规则及 schema
已经冻结。阶段 2 联调直接运行阶段 1 Replay，并消费其实际生成的 summary，
不是手工构造或补写阶段 1 计数。因此当前代码和接口状态可标记为
`stage2_verified`。

本阶段没有改变 Replay 状态机、DRAM/NVM 页面位置语义、事件计数时机、
训练标签、模型、正式 workload 或历史实验结果。对
`qmap/proactive_replay.py` 的修改仅解除“公共 Cost 必须保持 pending”的
历史门禁；阶段 1 输出仍保持 `weighted_cost=null` 和
`weighted_cost_status=pending_stage2`，Cost 只由阶段 2 派生。

## 2. Cost 的用途边界

本报告中的 Cost 只用于实验结果评价。它读取已经完成 Replay 后保存的
原始事件汇总，不参与：

- Replay 决策；
- 页面排序；
- 水位或批量控制；
- 标签构造；
- 模型训练或推理；
- trace 读取。

Cost profile 权重改变时，只需对同一份原始计数离线重算，不重新运行
Replay，不改变策略轨迹，不重新训练。

训练标签权重则改变模型训练目标，修改后需要重新标注和训练。训练标签
权重属于后续阶段，不由本模块读取或修改。两类权重在代码、配置和报告中
保持隔离。

## 3. 正式 Cost 公式

正式评价 Cost 为：

\[
C =
w_{\mathrm{hit}}N_{\mathrm{DRAM-hit}}
+w_{\mathrm{read}}N_{\mathrm{NVM-read}}
+w_{\mathrm{write}}N_{\mathrm{NVM-write}}
+w_{\mathrm{demote}}N_{\mathrm{demotion}}.
\]

四个分量固定命名为：

```text
dram_hit_cost
nvm_read_cost
nvm_write_cost
demotion_cost
```

实现强制验证：

```text
weighted_cost
= dram_hit_cost
+ nvm_read_cost
+ nvm_write_cost
+ demotion_cost
```

全部权重和计数均为整数，计算只使用整数乘法和加法。

## 4. 方案 B 与 provenance

当前实验环境没有真实 NVM 平台，因此采用方案 B：

> 由于当前实验环境不具备真实 NVM 平台，本文根据目标分层存储系统中
> 不同事件的相对代价设置参数化 Cost profile。主实验采用位于所考察
> 参数区间中部的 1:2:8:10 作为默认配置，并进一步设置读代价较低、
> 写代价较高和迁移代价较高三种替代配置，通过离线重算检验实验结论
> 对 Cost 假设的敏感性。

机器可读 provenance 固定为：

```text
calibration_mode = parameterized_profile_set
normalization_basis = dram_hit_equals_1
platform_availability = no_real_nvm_platform
profile_source = parameterized_relative_cost_assumptions
selection_constraint = predeclared_before_capd_results
```

这些 profile 是预先声明的相对代价假设，不是真实硬件标定结果，也不能
被描述为由真实 NVM 平台测量得到。没有开发硬件延迟采集、P95 硬件统计
或测量值整数化工具。

## 5. 冻结的 Cost profile

| profile | DRAM Hit | NVM Read | NVM Write | Demotion | 用途 |
|---|---:|---:|---:|---:|---|
| `read_light` | 1 | 2 | 4 | 8 | 后续敏感性实验 |
| `default` | 1 | 2 | 8 | 10 | 主实验 |
| `write_expensive` | 1 | 2 | 12 | 10 | 后续敏感性实验 |
| `migration_expensive` | 1 | 2 | 8 | 20 | 后续敏感性实验 |

`default_profile` 固定指向 `default`。

default 采用 1:2:8:10 的原因只作如下表述：

> 该配置位于所考察参数区间的中部，用于表示目标分层存储系统的一组
> 中间相对代价假设。

阶段 2 只冻结了用于后续敏感性实验的三组替代 Cost profile。正式敏感性
实验尚未执行，当前不能声称主要结论已经证明不依赖单一 profile。

## 6. 原始事件输入契约

配置 schema：

```text
schema_name = capd_proactive_stage2_cost_profiles
schema_version = capd_proactive_stage2_cost_profiles_v1_0
contract_version = capd_proactive_raw_events_v1_0
```

规范化必需字段：

```text
dram_hits
nvm_reads
nvm_writes
```

demotion 信息必须采用以下两种形式之一：

```text
total_demotions
```

或完整三分类：

```text
proactive_demotions
reactive_demotions
emergency_demotions
```

若只提供完整三分类，阶段 2 明确计算：

```text
total_demotions =
    proactive_demotions
  + reactive_demotions
  + emergency_demotions
```

若 total 与三分类同时存在，必须精确相等。只出现一部分分类字段时立即
失败，不允许将缺失类别猜成 0。

所有计数必须是大于等于 0 的整数。布尔值、负数、浮点数、字符串、
NaN、Infinity、缺失字段和重复 JSON key 均拒绝。JSON 输入绝不把字符串
静默转成数字。CSV 没有原生类型，因此 CLI 只对计数字段执行显式、严格
的十进制非负整数字面量解析；`1.0`、`+1`、空白和负数均拒绝。

## 7. 身份字段与输出契约

输入中的所有字段先深拷贝到输出，阶段 2 只新增顶层
`stage2_cost` 命名空间。因而以下实验身份字段及任何其他阶段 1 字段的
原值不会被修改：

```text
workload
policy
seed
capacity_ratio
run_id
schema_version
```

若输入已经包含 `stage2_cost`，工具拒绝覆盖。

每个 profile 的结果至少包含：

```text
profile_name
raw_counts
weights
component_costs
weighted_cost
```

`stage2_cost` 还包含 schema/contract/status、所选 profile、规范化原始
计数和 `cost_results`。当 default 被计算时，同时输出
`default_weighted_cost` 作为主评价 Cost。

## 8. NVM write 与 demotion 记账边界

本阶段没有重新选择记账语义，而是依据现有代码和冻结测试记录现状。

现有 `qmap/qmap_eval.py` 的行为是：

1. 页面访问前已在 DRAM，则增加 `hit_count`，按 DRAM access cost 计费；
2. 页面不在 DRAM，则该次访问按 RW 增加 `nvm_read_count` 或
   `nvm_write_count`，并按 NVM access cost 计费；
3. DRAM 满时选出 victim，页面由 DRAM 移至 NVM，单独增加
   `migration_count` 和 migration cost；
4. victim 是否 dirty 不会额外增加 `nvm_write_count`。

`qmap/finals_config.py` 将 `dirty_demotion_nvm_write` 冻结为 `none`；
`tests/test_dirty_accounting.py` 和
`tests/test_capd_stage1_v3_semantics.py` 均以手算用例验证了该语义。

因此在当前仓库口径下：

- `N_NVM_write` 表示写访问由 NVM 服务的介质访问事件；
- `N_demotion` 表示一次独立 DRAM→NVM 页面迁移操作；
- demotion cost 是迁移操作的独立附加成本；
- dirty demotion 不额外制造一笔 NVM write；
- 公式同时包含 NVM write 与 demotion 是有意识地评价两类不同事件，
  不是对同一次 dirty demotion 的重复计费。

阶段 1 联调已经重新核对并保持这一边界：四个场景的 `nvm_writes`、
`dirty_demotions` 和三类 demotion 原始计数均由 Replay 直接生成，阶段 2
适配层不补数、不改数，也不把 dirty demotion 转换为 NVM write。

## 9. 历史 Cost 实现审计

旧版 Cost 和重算逻辑位于：

- `qmap/qmap_eval.py`：Replay 内在线累计原始计数和
  `weighted_access_cost`；
- `qmap/finals_config.py`：历史 v2.1/v3 配置冻结
  `1:2:8:10` 及 Replay 记账语义；
- `scripts/run_cost_weight_sensitivity.py`：读取历史结果 JSON，以
  `hits/nvm_reads/nvm_writes/migrations` 离线重算；
- `qmap/stage6_results.py`：历史阶段 6 Cost robustness 重算；
- `configs/cost_weight.yaml`：历史文档型敏感性配置；
- `tests/test_cost_weight_sensitivity.py`、
  `tests/test_cost_weight_robustness.py`、
  `tests/test_capd_stage6_results.py`：历史重算回归；
- `tests/test_dirty_accounting.py`、
  `tests/test_capd_stage1_v3_semantics.py`：事件计数语义回归。

旧版默认已经使用 1:2:8:10，但旧敏感性集合包含 1:2:4:5、
1:2:16:10 等历史取值，与当前冻结集合不同。旧工具还使用 float 和
`int()` 转换，不满足阶段 2 严格输入契约。

可复用的是“保存原始计数、离线重算、不重放、不重训”的实验原则和
历史计数语义。历史脚本、配置、结果及 `qmap_eval` 行为均不直接改写，
以避免改变已完成实验。

## 10. 离线重算流程

```text
阶段 1 原始 summary
  → 薄字段适配（当前等待阶段 1）
  → 严格原始计数校验
  → demotion total/分类一致性校验
  → 一次规范化
  → 同一 RawEventCounts 分别应用四组权重
  → 分量和 weighted_cost 一致性校验
  → 保留原记录并追加 stage2_cost
  → 输出 JSON
```

工具示例：

```bash
python3 scripts/recompute_proactive_cost.py \
  --input raw_summary.json \
  --profile default

python3 scripts/recompute_proactive_cost.py \
  --input raw_summary.jsonl \
  --all-profiles \
  --output reweighted.json
```

工具支持单个 JSON 对象、JSON 对象数组、JSONL 多记录和 CSV 多记录；
输出为机器可读 JSON。输入与输出路径相同会失败，非法输入返回非零退出码，
所有记录先完成计算后才写输出，不会用半成品覆盖结果。

## 11. 新增实现

| 文件 | 用途 |
|---|---|
| `configs/finals/capd_proactive_stage2_cost_profiles.json` | profile、schema、provenance、原始计数和公式冻结 |
| `qmap/proactive_cost.py` | 纯数据结构、严格校验、单/多 profile 整数计算、阶段 1 summary 薄适配、结果序列化 |
| `scripts/recompute_proactive_cost.py` | JSON/JSONL/CSV 离线重算 CLI；自动识别并走阶段 1 summary 薄适配 |
| `tests/fixtures/capd_proactive_stage2_raw_events.json` | 合法合成原始事件记录 |
| `tests/fixtures/capd_proactive_stage2_invalid_raw_events.json` | 非法输入失败 fixture |
| `tests/test_capd_proactive_cost.py` | 阶段 2 冻结、算术、边界、不变性和 CLI 测试 |
| `tests/test_capd_stage1_stage2_integration.py` | 阶段 1 Replay summary 到阶段 2 四 profile 的永久联调测试 |
| `scripts/validate_capd_proactive_stage2_server.sh` | 服务器一键验收入口 |
| `docs/CAPD_PROACTIVE_STAGE2_COST_FREEZE_REPORT_CN.md` | 本冻结报告 |

收尾阶段将 `configs/finals/capd_proactive_stage0.json` 中的默认 Cost
profile 和 `freeze_status.stage2_cost_profile` 更新为 frozen。没有修改
`qmap/finals_config.py`、`qmap/qmap_eval.py` 或 Replay 状态机语义。

## 12. 测试与验证结果

Windows 本机使用 Python 3.13.6 执行：

```text
python -B -m unittest discover -s tests -p test_capd_proactive_cost.py -v
python -B -m unittest discover -s tests -p test_capd_proactive_config.py -v
python -B -m unittest discover -s tests -p test_capd_proactive_replay.py -v
python -B -m unittest discover -s tests -p test_capd_stage1_stage2_integration.py -v
python -B -m unittest discover -s tests -p test_cost_weight_sensitivity.py -v
python -B -m unittest discover -s tests -p test_cost_weight_robustness.py -v
python -B -m unittest discover -s tests -p test_dirty_accounting.py -v
python -B -m unittest discover -s tests -p test_capd_stage6_results.py -v
python -B -m unittest discover -s tests -p test_capd_stage1_v3_semantics.py -v
```

最终结果：

| 测试组 | 通过 | 失败 |
|---|---:|---:|
| 阶段 2 Cost | 28 | 0 |
| 阶段 0 配置回归 | 15 | 0 |
| 阶段 1 Replay | 19 | 0 |
| 阶段 1→2 联调 | 3 | 0 |
| 历史 Cost sensitivity/robustness | 4 | 0 |
| dirty/migration 记账 | 1 | 0 |
| 历史阶段 6 Cost | 6 | 0 |
| 历史 Replay/合同语义 | 17 | 0 |
| 合计 | 93 | 0 |

另执行了：

- Python 语法编译检查；
- 配置 CLI 校验；
- default 合成手算，结果为 190；
- 四 profile 同源计数批量重算；
- 四个阶段 1 Replay 场景经冻结 summary 接口重算；
- 阶段 1 schema、原始 pending Cost 状态和输入不变性检查；
- 非法 fixture，退出码为 2 且未产生输出；
- `git diff --check`；
- Cost 配置 CLI 校验返回 `status=stage2_verified`。

脚本内各 Python/CLI 门禁已在 Windows 环境逐项执行并通过。Linux
服务器仍需按下列命令完整执行，并留存退出码和日志；在日志返回
`STAGE2_VERIFIED` 前，不宣称 Linux 环境验证已经完成：

```bash
PYTHON_BIN=python3 bash scripts/validate_capd_proactive_stage2_server.sh
```

验证过程没有运行正式 workload、训练、模型读取或 GPU 代码。

## 13. 阶段 1 联调完成情况

阶段 1 已冻结并接入以下内容：

1. `capd_proactive_stage1_log_v1_0` summary schema；
2. `dram_hits`、`nvm_reads`、`nvm_writes`；
3. proactive、reactive、emergency 和 total demotions；
4. total 与三分类 demotion 之和一致；
5. NVM read/write 访问级计数规则；
6. `policy_name` 等原始身份字段；
7. 原始 `weighted_cost=null`、`weighted_cost_status=pending_stage2`。

薄适配入口为 `qmap.proactive_cost.recompute_stage1_summary()`。它先验证
阶段 1 schema 和原始 Cost 占位状态，再调用 Replay 无关的计算函数。
联调测试验证输入不被修改、三分类之和、default 手算结果、四 profile
同源重算和错误 schema 立即失败。

## 14. 公共配置冻结

联调完成后，`configs/finals/capd_proactive_stage0.json` 已完成最小更新：

```text
freeze_status.stage2_cost_profile = frozen
evaluation.cost_profile.status = frozen
evaluation.cost_profile.name = default
evaluation.cost_profile.weights = 1:2:8:10 对应字段
```

独立阶段 2 配置同时冻结为：

```text
raw_event_contract.stage1_adapter_status = verified_stage1_summary_v1_0
stage1_integration_completed = true
stage_status = stage2_verified
```

## 15. 阶段 3 门禁

阶段 3 的代码与接口门禁核对如下：

1. 阶段 1 Replay 状态机及原始计数契约已冻结；
2. 阶段 1 Replay 生成的四个合成 summary 已通过薄适配；
3. NVM write/demotion 语义已由用户确认并与代码一致；
4. default 和四 profile 的同源离线重算已通过；
5. 公共配置已完成最小合并；
6. 阶段 2 状态已更新为 `stage2_verified`；
7. Cost 仍只作评价，不参与阶段 3 水位、批量或训练决策。

进入阶段 3 前仅需在目标 Linux 服务器执行第 12 节的一键验证脚本，
确认环境内同样输出 `STAGE2_VERIFIED`。

## 16. 风险与阻塞

用户已经确认沿用现有 Cost 记账边界：NVM write cost 表示 NVM 写访问
成本，demotion cost 表示 DRAM→NVM 迁移成本；dirty demotion 不额外增加
NVM write。当前不存在待用户决定的阶段 2 Cost 口径问题。

剩余事项仅是目标 Linux 服务器上的可复现性验收和日志留存，不涉及方法、
参数或记账语义调整。
