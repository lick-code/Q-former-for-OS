# CAPD 主动降级阶段 3 协议：Working Set、容量比例、水位与批量

## 1. 阶段目标与边界

阶段 3 在生成主动降级训练样本之前冻结运行时控制机制。它只回答四个问题：

1. 如何由 Train 与 Validation 定义 Active Working Set；
2. 采用哪一组统一 DRAM/Working-Set 容量比例；
3. Proactive-LRU 使用哪组统一的 `F_low/F_target`；
4. 在默认水位下使用哪个 `b_max`。

阶段 3 不训练 CAPD、不加载 checkpoint、不使用 CAPD 结果、不使用候选页筛选器，也不读取 Test。正式候选数 `K` 属于阶段 4；本阶段的 `stage3_calibration_candidate_bound` 只是保证 Top-`b_t` 不被截断的非正式代理，不得写入 `method.candidate_size_K`。

阶段 0、1、2 必须分别保持已冻结状态。阶段 3 未确认前，阶段 0 主配置中的 `stage3_active_mechanism`、Working Set 规则、容量比例、`F_low`、`F_target`、`b_max` 均保持待定，阶段 4、阶段 7 和 formal Test 继续保持 `pending`。

## 2. 数据身份与输入契约

输入由独立 manifest 声明，不能只根据文件名推断 split。每个 workload 必须同时提供：

- `split=train, role=training_and_fit`；
- `split=validation, role=parameter_selection`；
- `source_kind=raw_access_trace`；
- `formal_test=false`。

manifest 顶层必须声明 `test_used_for_parameter_selection=false`。任何 `split=test`、`formal_test=true`、缺少正式 role、重复 workload/split 或缺少 Train/Validation 的输入都会在读取 trace 前被拒绝。

原始 trace 使用仓库现有 `pc,address[,rw]` CSV 解析契约，`page_shift=12` 对应 4 KiB 页。每个输入保存 SHA-256 fingerprint、访问数、RW 来源和解析后的 split 身份。空 trace、负页面 ID 和非法 RW 会失败。Working Set 必须来自原始访问页，不能用历史训练 JSONL 中筛选后的候选集合代替。

示例 manifest：`configs/finals/capd_proactive_stage3_input_manifest.example.json`。正式运行前复制该文件并为每个代表 workload 填入真实 Train/Validation 路径；不得加入 Test。

## 3. Working Set 冻结口径

统一定义：

```text
working_set_definition =
active_unique_pages_from_train_and_validation
```

对每个 workload，分别统计 Train 唯一页、Validation 唯一页、二者交集和二者并集。每页只计一次，页面大小固定为 4096 B。用于容量换算的 Working Set 是 Train/Validation 并集页数。输出同时保留两段 trace 的访问数和 fingerprint。

## 4. 容量比例与确定性取整

首先审计主容量集合：

```text
0.2 / 0.4 / 0.6 Working Set
```

只有主集合不满足预声明压力可区分规则时，才考虑：

```text
0.1 / 0.2 / 0.4 Working Set
```

两组都会由 Reactive-LRU 运行，以便给出审计证据；选择过程不使用 CAPD。每个 workload 使用相同的比例集合，不允许为某个 workload 或策略单独调容量。

绝对页数使用十进制定点乘法后向上取整：

```text
D = ceil_decimal(W * ratio)
```

结果至少为 1 页，且不得超过 Working Set。实现不使用 Python banker rounding，也不做静默 clamp；输出保存比例、十进制原始乘积、整数页数和规则名。

### 4.1 预声明压力判定

配置在查看结果前冻结以下阈值：

- 每个 run 至少 100 次访问；
- 相邻容量的单调容差为 0.01；
- page-enter、NVM access、demotion、reactive-demotion 四类比率中至少三类随容量降低总体增强；
- NVM access rate 或 demotion rate 的三档跨度至少 0.05；
- 所有容量的 demotion rate 都小于 0.01 时判为“几乎无迁移”；
- 所有容量的 exhaustion rate 都大于 0.1 时判为“长期耗尽”。

只有长度可靠、至少三类指标满足顺序、至少一个压力跨度达到阈值、且不属于“所有容量几乎无迁移”或“所有容量长期耗尽”时，该 workload/split 的三档压力才可区分。主容量集合对全部代表 workload 的 Train/Validation 均通过时，建议保留 20/40/60；否则检查 10/20/40。无论推荐哪组，真实结果仍需用户确认后才能更新主配置。

## 5. page_enter_dram 突发统计

水位之前没有可用的主动控制参数，因此使用 Reactive-LRU 生成 `page_enter_dram` 布尔序列。它不需要 `F_low/F_target/b_max`，从而避免“先假设水位，再用该水位产生的数据选择自己”的循环。此阶段不使用 CAPD。

分别按访问下标 0 对齐的非重叠 100、500、1000 访问窗口统计进入 DRAM 的页面数。完整窗口进入 mean/P50/P95/P99/max，尾部窗口单独保存但不进入分位数。分位数固定使用 nearest-rank：

```text
rank = max(1, ceil(p * n))
```

输出保留每个原始窗口，不只保存汇总分位数。

## 6. 水位候选生成与合法性

只使用推荐容量集合中的 Validation、100 访问窗口。对每个 workload × capacity run 先得到 P50/P95/P99，再跨 run 取最大值。三档含义为：

- Small：P50 所对应的典型短突发储备；
- Medium：P95 所对应的高分位短突发储备；
- Large：P99 所对应的尾部短突发储备。

候选生成规则为：

```text
F_target = max(2, ceil(source), previous_F_target + 1)
F_low    = ceil(F_target / 2)
```

Small 的 `previous_F_target` 初值为 1。该规则保证三档严格递增并满足 `0 < F_low < F_target`。若某个候选的 `F_target` 超过某一运行的 DRAM 绝对页数，该组合标记为 `illegal`，不截断、不替换，也不参与全局选择。一个候选只有在全部 workload × capacity 组合上合法且状态机不变量全部通过，才是可行候选。

## 7. 水位矩阵与选择顺序

水位矩阵只在 Validation 上使用 Proactive-LRU，并固定 `b_max=1` 以避免在水位选择阶段同时优化批量。每个组合保存：

- free-frame exhaustion、emergency、total/proactive/reactive demotions；
- early-reuse count 与 `early_reuse_count / proactive_demotions`；
- proactive cycles/rounds、rounds per cycle；
- minimum/average free frames、accesses below `F_low`；
- NVM reads/writes、默认 weighted cost；
- 每轮实际候选数的最小值和最大值。

`proactive_demotions=0` 时 early-reuse rate 输出 `null`，状态为 `undefined_no_proactive_demotions`。

跨 workload 与 capacity 使用不加权 macro average，另报 worst case，不把不同长度 trace 的访问全部 pooled。预声明字典序为：

1. 排除不合法或状态机不变量失败候选；
2. worst-case、macro free-frame exhaustion；
3. worst-case、macro emergency demotions；
4. macro early-reuse rate；
5. macro total demotions；
6. macro NVM I/O；
7. 更小的 `F_target`、`F_low`。

此顺序不使用 CAPD 提升，不按 workload 分别选水位。

## 8. b_max 标定

默认水位产生候选后，才比较 `b_max=1/2/4`。仍只在 Validation 上运行 Proactive-LRU，使用相同 Working Set、容量集合、原始 trace、Replay 语义和阶段 2 默认代价：

```text
cost = dram_hits + 2*nvm_reads + 8*nvm_writes + 10*total_demotions
```

原始计数和各 Cost component 始终保存。选择顺序为：状态机与合法性、exhaustion、emergency、每 workload/run 的 default cost per access 的 macro average、NVM writes、early reuse、round count、较小 `b_max`。不用 CAPD 推理延迟、CAPD 结果或 Test。

## 9. K 代理不变性

配置固定使用代理边界 8 和 16，二者都大于最大 `b_max=4`。每轮实际候选数写入结果。分别在两个代理 K 下重复水位和 `b_max` 选择；只有二者得到相同水位标签和相同 `b_max`，不变性才通过。若结论变化，阶段 3 不可冻结，必须报告 `failed_proxy_K_changes_selection`。无论是否通过，代理 K 都不进入正式配置，阶段 4 的候选数继续为 `pending`。

## 10. 输出与不可覆盖性

每次运行使用独立 `run_id`：

```text
<output_root>/stage3/<run_id>/
```

目录包含 resolved config、provenance、resolved manifest、Working Set、容量压力、burst 汇总与原始窗口、水位与 b_max JSONL/CSV、选择决定、freeze candidate、日志目录、逐 replay checkpoint 和 Markdown 报告。JSON/JSONL 使用 UTF-8，禁止 NaN/Infinity。已有完整 run 默认拒绝覆盖；执行过程先写 `.incomplete` 临时目录，每个 replay 完成后原子写入 checkpoint，并向 `logs/progress.jsonl` 追加进度。中断或失败时保留 `.incomplete`，成功后原子改名，既不产生伪成功目录，也不丢失已完成计算。

Stage 3 大 trace 使用 primitive-array 紧凑输入、O(1) LRU 更新和轻量日志模式。热路径执行常数时间局部守卫；每个 replay 结束时仍执行一次全量状态不变量与计数审计。Stage 1 的默认全日志、逐访问全量检查接口保持不变。

## 11. 状态转换

- 仅完成代码、配置、合成验证：`stage3_implemented_awaiting_calibration_inputs`；
- 真实 Train/Validation 运行完成：`stage3_calibration_results_ready_for_freeze`；
- 用户确认唯一冻结候选、阶段 0–2 回归和服务器验证全部成功，并同步更新主配置后，才允许 `stage3_verified`。

当前实现不会自动写 `stage3_verified`，也不会自动修改阶段 0 主配置。真实结果需要人工审阅容量压力表、burst、水位、`b_max` 和 K 代理不变性后再冻结。

## 12. 服务器运行

仅做代码与合成验收：

```bash
cd ~/Q-former-for-OS
bash scripts/validate_capd_proactive_stage3_server.sh
```

加入真实 Train/Validation 校准：

```bash
cd ~/Q-former-for-OS
STAGE3_INPUT_MANIFEST=/absolute/path/stage3_manifest.json \
STAGE3_RUN_ID=stage3-real-001 \
bash scripts/validate_capd_proactive_stage3_server.sh
```

如果同一 `run_id` 的 `.incomplete` 已由新版程序建立，或是旧版留下的空目录，可原地恢复：

```bash
cd ~/Q-former-for-OS
STAGE3_INPUT_MANIFEST=/absolute/path/stage3_manifest.json \
STAGE3_RUN_ID=stage3-real-001 \
STAGE3_RESUME=1 \
bash scripts/validate_capd_proactive_stage3_server.sh
```

恢复前会核对配置、manifest、Stage 0/2 配置和所有 trace fingerprint；任一输入变化都会拒绝复用 checkpoint。运行时终端会逐项打印 `start/done/checkpoint reuse`，状态可查看：

```bash
tail -f outputs/capd_proactive_calibration/stage3/stage3-real-001.incomplete/logs/progress.jsonl
```

默认日志写入仓库根目录 `stage3_validation.log`。合成验收期望最后输出 `STAGE3_IMPLEMENTED_AWAITING_CALIBRATION_INPUTS`；真实输入成功运行后输出 `STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE`。脚本不运行 Test、不训练 CAPD、不需要 GPU。
