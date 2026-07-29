# CAPD 主动降级实验阶段 1 冻结报告

日期：2026-07-29

状态：`STAGE1_IMPLEMENTED_AWAITING_SERVER_VALIDATION`

权威方案：`CAPD_主动降级版本_完整实验实施方案(1).md`

基础契约：`configs/finals/capd_proactive_stage0.json`

## 1. 阶段边界与当前结论

本阶段只实现确定性同步 Trace Replay 的状态机、统一候选排序接口、日志、
原始事件计数、合成 fixture 和正确性测试。没有选择正式参数，没有生成
正式训练样本，没有训练或修改 CAPD 模型，没有运行正式 workload，也没有
进入阶段 2。

当前代码实现已经完成；由于本地没有 Python 项目运行环境，服务器验收尚未
执行。因此：

- `freeze_status.stage1_replay` 仍保持 `pending`；
- 本报告暂不声称相关测试已经通过；
- 只有服务器脚本输出 `STAGE1_VERIFIED` 后，才能把报告状态和门禁更新为
  `frozen`。

用户已确认阶段 0 执行完毕。仓库中的阶段 0 报告仍带有
`STAGE0_IMPLEMENTED_AWAITING_SERVER_VALIDATION` 旧文字，仓库内未发现对应
服务器日志，所以本阶段没有仅凭旧状态文字重做阶段 0，也没有无证据改写
该报告。

## 2. 实际修改的 Replay 路径

新增隔离实现：

```text
qmap/proactive_replay.py
```

历史 `qmap/qmap_eval.py`、`qmap/qmap_generator.py` 和
`qmap/finals_generator.py` 均未改变。新模块沿用现有 LRU 方向：

```text
index 0 = MRU
list 尾部 = LRU
主动候选按最旧到较新的顺序构造
```

隔离的原因是历史 Replay 使用“DRAM 满时选择一个 victim”的语义；直接在
该路径内加入水位周期会改变旧配置和历史实验行为。

## 3. 配置消费与 fixture 边界

Replay 启动时首先通过 `qmap/finals_config.py` 加载并验证：

```text
schema_version = capd_proactive_v1_0
contract.id = CAPD-PROACTIVE-STAGE0-1.0
method.selector = disabled
page_enter_dram = occupies_one_free_frame_regardless_of_source
```

阶段 1 合成值位于：

```text
configs/finals/capd_proactive_stage1_fixture.json
```

fixture 被明确标记为：

```text
fixture_status = non_formal_synthetic_only
parameter_status = non_formal_fixture
```

它没有覆盖阶段 0 模板，也没有向正式字段写入
`F_low/F_target/b_max/K`。阶段 0 模板中的阶段 2/3/4/7 字段继续保持
`null/pending`。

## 4. Replay 状态

状态机维护：

- DRAM resident set；
- NVM resident set；
- DRAM 容量和实时 `F_t`；
- MRU→LRU 顺序；
- frequency、dirty、residency 和最近访问状态；
- DRAM 进入时刻；
- 固定长度 history window；
- active proactive cycle；
- access、decision、cycle、round 和 raw event counters；
- 主动降级页面的短期复用诊断状态。

NVM 是足够大的 backing tier。首次出现的页面先注册为 NVM resident；当
该访问需要页面进入 DRAM 时，统一执行 `page_enter_dram`。

## 5. 页面访问与容量更新顺序

每条访问严格按以下顺序处理：

```text
读取访问前位置
→ 若 DRAM hit，更新 MRU
→ 若页面需要进入 DRAM 且 F_t = 0，先执行 Reactive 或 Emergency 降级
→ page_enter_dram，F_t 精确减 1
→ 更新 frequency / dirty / residency / LRU / history
→ 检查主动水位
→ 完成同步主动周期
→ 记录访问日志
```

任何 `page_enter_dram` 执行前都必须已经有空闲页框。状态机不会先把
`F_t` 减为负数再修正。

访问级 NVM 原始计数定义为：

- 非 DRAM 读访问计入 `nvm_reads`；
- 非 DRAM 写访问计入 `nvm_writes`；
- dirty 页面降级单独计入 `dirty_demotions`，阶段 1 不擅自将其折算为
  Cost 或新增正式写回权重。

## 6. 水位状态机

Reactive-LRU：

- 不定义 `F_low/F_target/b_max/K`；
- 只在 `page_enter_dram` 前发现 `F_t = 0` 时降级 LRU 页；
- 不创建 proactive cycle 或 round。

主动策略：

```text
F_t >= F_low
→ 不启动主动周期

0 < F_t < F_low
→ 启动同步主动周期

主动策略遇到 F_t = 0 且页面需要进入 DRAM
→ 先执行 LRU emergency fallback
→ 完成 page_enter_dram
→ 强制重新检查并恢复到 F_target
```

每轮重新构造当前实际候选集合并计算：

```text
K_t = 当前实际可降级候选数
b_t = min(b_max, F_target - F_t, K_t)
```

完成 Top-`b_t` 降级后更新所有状态；若仍未达到 `F_target`，下一轮必须
重新读取当前 LRU 和 resident set，不能复用上一轮候选快照。

## 7. 统一候选与排序接口

阶段 1 的最小接口为：

```text
build_candidates()
ranking_policy.rank_candidates(...)
select_top_b(ranking, b_t)
```

已实现：

- `ProactiveLRURanking`；
- `DeterministicStubRanking`，只用于合成 Top-b 测试；
- Reactive-LRU 独立按需路径。

状态机不包含 Transformer、未来标签或 checkpoint 逻辑。对 CAPD、
Proactive-CLOCK、TPP-inspired 或 Oracle，如果没有显式提供对应排序器，
构造 Replay 时会直接失败，不会使用 LRU 伪造其结果。

## 8. 三类降级事件

每次页面离开 DRAM 都生成独立事件：

| 事件 | 触发条件 | 是否属于主动 round |
|---|---|---|
| `reactive_demotion` | Reactive-LRU 在页面进入前发现无空闲页框 | 否 |
| `proactive_demotion` | 主动周期的 Top-b 选择 | 是 |
| `emergency_fallback_demotion` | 主动策略在页面进入前发现无空闲页框 | 否 |

事件日志包含 event id、访问位置、页面、策略、cycle/round 关联、降级前后
`F_t` 和 dirty 状态。三类事件使用互斥枚举，并由 summary 分别计数。

## 9. 循环终止与立即失败

正常周期在 `F_t >= F_target` 时以 `target_reached` 终止。

防死循环路径包括：

- `candidate_set_empty`；
- `b_t_zero`；
- `no_state_progress`；
- `max_rounds_exceeded`；
- `target_already_reached`。

候选数小于 K 时使用实际候选数，不 padding。候选为空或目标暂时不可达时，
周期写出明确 termination reason 后停止，不循环等待。排名重复、排名集合
与候选集合不一致、选中非候选页、容量或驻留守恒失败时立即抛出
`ReplayInvariantError`，不静默修复。

## 10. 持续验证的不变量

每次页面进入、页面降级、每轮和每条访问后均检查：

```text
F_t = DRAM capacity - |DRAM resident set|
0 <= F_t <= DRAM capacity
DRAM 与 NVM resident set 不重叠
每个已知 resident page 的位置唯一
LRU 集合与 DRAM resident set 完全一致
LRU 不含重复页
selected pages ⊆ 当前 candidate set
b_t = |selected pages|
b_t <= |candidate set|
b_t <= b_max
b_t <= F_target - F_before
```

## 11. 日志 Schema 与输出

日志版本：

```text
capd_proactive_stage1_log_v1_0
```

机器可读最低字段定义：

```text
configs/finals/capd_proactive_stage1_log_schema.json
```

包含：

- access 日志；
- 三类 demotion event 日志；
- proactive round 日志；
- proactive cycle 日志；
- workload summary。

阶段 1 不测量真实模型延迟，因此：

```text
feature_latency = null
inference_latency = null
selection_latency = null
total_inference_time = null
total_selection_time = null
total_decision_time = null
decision_time_status = not_measured_stage1
```

阶段 2 Cost profile 未冻结，因此：

```text
weighted_cost = null
weighted_cost_status = pending_stage2
```

合成试运行输出遵循阶段 0 最低目录：

```text
<output_root>/stage1/<run_id>/
├─ resolved_config.json
├─ provenance.json
├─ artifacts/
└─ logs/
```

`resolved_config.json` 保存完整阶段 0 配置及显式的
`stage1_fixture` 快照；正式 pending 字段不被 fixture 值替换。

## 12. 已增加的测试

新增：

```text
tests/test_capd_proactive_replay.py
```

测试覆盖：

1. 阶段 0 与 fixture 契约隔离；
2. `F_t >= F_low` 不触发；
3. `0 < F_t < F_low` 触发并恢复目标水位；
4. 确定性 stub 的单轮 Top-b；
5. 多轮候选重建；
6. 实际候选数小于 K；
7. b_max、目标缺口和候选数三重上界；
8. DRAM/NVM/F_t、LRU、frequency、dirty、residency 和 history；
9. Reactive-LRU 不创建主动日志；
10. Reactive/Proactive/Emergency 不混记；
11. 无空闲页框时先释放后进入、`F_t` 不为负；
12. 空候选时明确终止；
13. round/cycle/summary 字段完整；
14. summary 与底层事件逐项核对；
15. 同 Trace 和配置结果完全一致；
16. weighted cost 保持 pending，selector 关闭，checkpoint 不需要；
17. 主动降级后的 early reuse 计数；
18. 非法 ranking 立即失败；
19. CAPD 无 checkpoint 时不会伪装为 LRU；
20. 全部声明的合成 scenario 可运行。

fixture 至少包含两个不同合成访问模式：

- `synthetic_locality_proactive_lru`；
- `synthetic_burst_reactive_lru`。

另外包含 emergency recovery 和 deterministic stub Top-b 场景。

## 13. 验证状态

本地已完成：

- 完整阅读权威实施方案和阶段 0 契约；
- 检查工作树初始状态为 clean；
- 代码、fixture、日志契约、测试和服务器脚本实现；
- JSON 文件的本地结构解析；
- `git diff --check` 静态检查。

本地未执行：

- Python 单元测试；
- Python 语法编译；
- 合成 Replay 试运行；
- 任何正式 workload、训练或模型推理。

服务器统一入口：

```bash
REPO=/path/to/cache_replacement \
  bash scripts/validate_capd_proactive_stage1_server.sh
```

脚本只运行阶段 0/1 契约测试、合成 fixture Replay、输出契约检查、
Python 语法检查和 `git diff --check`，不运行正式 workload。

当前等待服务器输出：

```text
[FINAL] STAGE1_VERIFIED
```

## 14. 仍为 pending 的字段

- 阶段 1：在服务器验收前，`freeze_status.stage1_replay`；
- 阶段 2：Cost profile；
- 阶段 3：working-set 口径、DRAM/working-set ratio、
  `F_low/F_target/b_max`；
- 阶段 4：`K/H/L/lambda`、训练数据、seed、checkpoint；
- 阶段 7：正式 workload、trace、split、working-set pages 和 DRAM pages；
- 正式 Test 门禁。

本阶段 fixture 中出现的数值不得引用为正式实验参数。

## 15. 阶段 2 输入条件

进入阶段 2 前必须同时具备：

1. 服务器脚本输出 `STAGE1_VERIFIED`；
2. 阶段 0 配置与历史配置回归继续通过；
3. Replay 状态、三类事件、round/cycle/summary 日志和原始计数冻结；
4. `freeze_status.stage1_replay` 有验证证据后更新为 `frozen`；
5. 保留所有原始事件数，使阶段 2 能独立标定 Cost profile；
6. 不使用本阶段合成 fixture 值作为阶段 3/4 的正式默认值。
