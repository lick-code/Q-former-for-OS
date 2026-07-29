# CAPD 主动降级实验阶段 0 冻结报告

日期：2026-07-29

状态：`STAGE0_IMPLEMENTED_AWAITING_SERVER_VALIDATION`

权威方案：`CAPD_主动降级版本_完整实验实施方案(1).md`

## 1. 阶段边界

本阶段只冻结研究边界、配置形状、数据划分、运行快照和 provenance
契约，以及可供后续阶段复用的配置验证入口。没有改造 Replay 状态机，
没有生成数据、训练模型、选择参数或运行正式实验。

仓库没有 `AGENTS.md`。现有配置系统使用 JSON，由
`qmap/finals_config.py` 统一加载、验证、生成指纹并写出
`resolved_config.json`。本阶段在该模块中加入
`capd_proactive_v1_0` 分支；历史 `capd_finals_v2_1` 和
`capd_finals_v3_0` 分支保持独立，不建立第二套加载系统。

唯一正式主动 CAPD 配置模板为：

```text
configs/finals/capd_proactive_stage0.json
```

其固定标识为：

```text
schema_version = capd_proactive_v1_0
config_version = 1
contract.id = CAPD-PROACTIVE-STAGE0-1.0
contract.status = stage0_frozen
method.name = capd_proactive
evaluation.policy_name = capd
```

## 2. 已冻结的研究边界

机器可读配置和验证器共同固定以下边界：

- `method.selector = disabled`，不实现扩大候选池后粗筛回 K。
- `method.candidate_source = lru_tail`。
- 主动策略使用 `trigger_mode = low_watermark`。
- 主动策略紧急回退固定为 `fallback_policy = lru`。
- `single_process = true`、`single_thread = true`、
  `single_workload = true`。
- Trace 执行语义为单应用顺序访存：
  `single_application_sequential_access`。
- `page_enter_dram` 统一语义为
  `occupies_one_free_frame_regardless_of_source`。
- `promotion_mode = not_studied`。
- 完整 Linux 内核集成为 `out_of_scope`。
- 页面大小固定为 4096 bytes。
- NVM 容量模型固定为 `unbounded_backing_tier`，不引入 NVM 淘汰。

## 3. 正式方法集合

机器可读 policy 标识与论文名称映射如下：

| `policy_name` | 正式名称 | `method.name` |
|---|---|---|
| `reactive_lru` | Reactive-LRU | `reactive_lru` |
| `proactive_lru` | Proactive-LRU | `proactive_lru` |
| `proactive_clock` | Proactive-CLOCK | `proactive_clock` |
| `tpp_inspired` | TPP-inspired | `tpp_inspired` |
| `capd` | CAPD | `capd_proactive` |
| `oracle` | Oracle | `oracle` |

上述六种是唯一正式主线集合。Kleio-lite 和 PatternS-lite 只允许进入
时间许可的扩展结果；FlexMem-Demotion-inspired、旧 CAPD、
Reactive-CAPD 和初赛 CAPD 不属于正式对照。

Reactive-LRU 的配置语义与主动策略分开验证：

- Reactive-LRU 使用 `on_demand_no_free_frame`，不定义
  `F_low/F_target/b_max/K`，不创建主动周期；
- 主动策略必须使用低水位触发、LRU 紧急回退，并在对应冻结点完成后
  提供 `F_low/F_target/b_max/K`；
- 共同的 Trace、容量、页面进入和 Cost 契约保持一致。

## 4. 配置字段与冻结阶段

现有字段命名被保留并映射到新的分组式配置：

| 实施方案字段 | 配置路径 | 阶段 0 状态 |
|---|---|---|
| `config_version` | `config_version` | 已冻结为 1 |
| `experiment_stage` | `experiment_stage` | 模板为 `stage0`；运行时取 `stage0..stage12` |
| method/selector/source/trigger/fallback | `method.*` | 已冻结 |
| `K` | `method.candidate_size_K` | `null`，阶段 4 |
| 单进程/线程/workload | `scope.*` | 已冻结 |
| `page_enter_dram`/promotion | `scope.*` | 已冻结 |
| workload/trace/ranges | `data.*` | `null`，阶段 7 |
| page size/NVM model | `memory.*` | 已冻结 |
| working-set definition/ratio | `memory.*` | `null`，阶段 3 |
| working-set size/DRAM pages | `memory.*` | `null`，阶段 7 |
| `F_low/F_target/b_max` | `active_demotion.*` | `null`，阶段 3 |
| `H/L/lambda_1..3` | `model.*` | `null`，阶段 4 |
| Cost profile | `evaluation.cost_profile` | `pending_stage2` |
| policy/seed | `evaluation.*` | policy 已冻结；seed 阶段 4 |
| checkpoint | `model.model_checkpoint` | `pending_stage4` |
| commit/dirty/machine/run/output/time | `run.*` | 每次 resolved run 注入 |

`freeze_status` 明确记录阶段 0、Replay、Cost、主动机制、候选与训练、
workload 和正式 Test 各门禁状态。尚未到冻结阶段的值必须保持 `null`；
验证器拒绝在 `pending` 状态下提前填入数值。

## 5. 时间顺序数据划分契约

Trace 与三个 split 统一使用访问序号的半开区间 `[start, end)`：

```text
Trace:      [trace_start, trace_end)
Train:      [train_start, train_end)
Validation: [validation_start, validation_end)
Test:       [test_start, test_end)
```

验证器保证：

- 所有边界必须同时为空或同时定义；
- 每个区间非空并位于 Trace 声明范围内；
- `train_end <= validation_start`；
- `validation_end <= test_start`；
- Train、Validation、Test 的固定角色不可互换；
- 参数选择集合只能是 `["train", "validation"]`；
- `test_used_for_parameter_selection` 必须为 `false`；
- 正式 Test 必须在 Replay、Cost、主动机制、workload，以及适用的
  候选/训练配置全部冻结后才能申请。

区间之间允许预先声明的空隙，但不允许重叠或改变时间顺序。

## 6. resolved config 与 provenance 契约

每次后续运行必须创建独立输出目录：

```text
<output_root>/<experiment_stage>/<run_id>/
├─ resolved_config.json
├─ provenance.json
├─ artifacts/
└─ logs/
```

`resolved_config.json` 使用 UTF-8 JSON，必须是完整展开后的配置，不能只
保存增量 override，也不能依赖目录名反推参数。现有
`config_fingerprint()` 继续对去除自身指纹字段后的完整配置计算
SHA-256。

`run_id` 固定表示为：

```text
YYYYMMDDTHHMMSSZ__<policy>__<workload>__seed-<seed|na>__<config_fp_12>
```

其中时间使用 UTC，workload 只使用文件系统安全字符，确定性或不适用
策略使用 `seed-na`，末尾为 resolved config 指纹前 12 位。

`provenance.json` 使用 UTF-8 JSON，schema 为
`capd_proactive_provenance_v1_0`。模板中的
`outputs.provenance.required_fields` 机器可读地固定以下最低字段：

```text
schema_version
config_schema_version
config_version
contract_id
run_id
created_at
resolved_config_filename
resolved_config_fingerprint
code_commit
dirty_worktree
dirty_diff_fingerprint
machine_information
command
model_checkpoint
input_artifacts
output_artifacts
status
```

代码版本使用 Git commit；`dirty_worktree` 必须为布尔值。若工作树为
dirty，`dirty_diff_fingerprint` 记录运行前 diff 的 SHA-256；clean
运行用 `null`。机器信息至少包含 hostname、操作系统、架构、CPU
型号、逻辑 CPU 数、内存字节数、runtime 和 runtime 版本。

CAPD checkpoint 使用 `{status: frozen, path, fingerprint}`。尚未进入
阶段 4 时使用 `{status: pending_stage4, path: null, fingerprint: null}`；
规则策略或不适用情形使用
`{status: not_applicable, path: null, fingerprint: null}`，禁止使用空字符串
表达不适用。

## 7. 已实现的验证规则

`qmap/finals_config.py` 现已验证：

- 必需字段完整性和 schema/contract 版本；
- 正式研究边界及 `page_enter_dram`/promotion/NVM 语义；
- selector 必须关闭；
- 正式 policy 白名单及 policy-method 对应关系；
- Reactive-LRU 与主动策略的字段差异；
- pending 字段不得提前填值；
- 半开区间、范围、顺序、互斥和固定 split 角色；
- Test 不参与参数选择；
- `0 < F_low < F_target`、`1 <= b_max < K`；
- 正式 Test 的全冻结门禁；
- resolved run 的 run_id、时间、commit、dirty、command 和机器信息；
- `resolved_config.json`、`provenance.json` 与最低输出目录结构。

对应最小测试位于 `tests/test_capd_proactive_config.py`，覆盖：

1. 合法阶段 0 CAPD 模板通过；
2. 主动机制字段冻结后的合法配置通过；
3. 缺少必需字段失败；
4. Train/Validation/Test 重叠失败；
5. split 角色互换失败；
6. Test 用于参数选择失败；
7. selector 非 disabled 失败；
8. 单线程、单进程或单 workload 边界失败；
9. 未冻结参数申请正式 Test 失败；
10. 非法 policy 失败；
11. 正式六方法集合不可漂移；
12. Reactive-LRU 与主动策略字段要求可区分；
13. 非学习主动策略只要求共享主动机制字段。

## 8. 仍为 pending 的字段

- 阶段 1：Replay 状态机、日志和事件计数实现是否冻结；
- 阶段 2：Cost profile 名称及权重；
- 阶段 3：active working-set 定义、DRAM/working-set ratio 规则、
  `F_low`、`F_target`、`b_max`；
- 阶段 4：`K`、`H`、`L`、`lambda_1..3`、随机种子、训练数据版本和
  checkpoint；
- 阶段 7：正式 workload、trace 路径与范围、三个 split 的实际边界、
  working-set page 数和 DRAM page 数；
- 每次运行：run_id、输出目录、UTC 时间、commit、dirty 状态、机器
  信息、命令和输入/输出 artifact 指纹。

阶段 0 没有为上述字段填写经验默认值。

## 9. 验证状态与服务器命令

按当前工作站约束，本地不执行 Python 项目代码、Replay、数据生成、
训练或正式实验。服务器验收入口为：

```bash
REPO=/path/to/cache_replacement \
  bash scripts/validate_capd_proactive_stage0_server.sh
```

该脚本只运行配置契约测试、一个模板加载/指纹检查、历史配置契约回归
测试和 `git diff --check`，不会运行 Replay 或任何正式实验。只有脚本
输出 `STAGE0_VERIFIED` 后，本报告状态才能更新为 `STAGE0_VERIFIED`。

## 10. 阶段 1 输入条件

进入阶段 1 前需要：

1. 服务器阶段 0 验证输出 `STAGE0_VERIFIED`；
2. `capd_proactive_v1_0`、正式 policy 集合和研究边界不再变化；
3. Replay 实现消费本模板，不重新定义配置系统；
4. Replay 使用已冻结的 `page_enter_dram` 和 DRAM→NVM 语义；
5. 阶段 1 只实现和测试状态机、日志、事件计数及快照写出；
6. 阶段 1 不填写或选择阶段 2/3/4/7 的 pending 参数。
