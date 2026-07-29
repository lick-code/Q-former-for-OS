# CAPD 主动降级阶段 3 待冻结报告

## 当前状态

`stage3_implemented_awaiting_calibration_inputs`

阶段 3 的独立配置、核心模块、校准入口、合成测试、服务器验收脚本和输出契约已实现。本地没有正式服务器 Train/Validation 原始访问 trace，因此本报告不填写正式容量比例、`F_low`、`F_target` 或 `b_max`，不将阶段 3 标记为 frozen，也不允许进入阶段 4。

## 新增文件

| 路径 | 用途 |
|---|---|
| `configs/finals/capd_proactive_stage3_active_mechanism.json` | 预声明阶段 3 数据边界、容量压力规则、水位/批量候选与选择顺序 |
| `configs/finals/capd_proactive_stage3_input_manifest.example.json` | 正式 Train/Validation 输入 manifest 模板 |
| `qmap/proactive_stage3.py` | Working Set、容量、burst、矩阵、选择、K 代理不变性和产物生成 |
| `scripts/run_capd_proactive_stage3_calibration.py` | 配置校验与校准 CLI |
| `scripts/validate_capd_proactive_stage3_server.sh` | 阶段 0–3 回归、合成 smoke、Test 拒绝和可重复性验收 |
| `tests/test_capd_proactive_stage3.py` | 阶段门禁、统计、选择和端到端合成测试 |
| `docs/CAPD_PROACTIVE_STAGE3_PROTOCOL_CN.md` | 阶段 3 正式实施协议 |
| `docs/CAPD_PROACTIVE_STAGE3_FREEZE_REPORT_CN.md` | 本待冻结报告 |

未修改历史 Stage 1 Replay、Stage 2 Cost、CAPD 模型、训练代码、标签生成器、候选筛选器、历史 Test 结果或阶段 0 主配置。

## 数据边界

- 当前仅使用代码内构造的 synthetic Train/Validation trace 验证工具链；
- 未读取真实 Train、真实 Validation 或任何 Test；
- 未将历史 Test 重命名为 Validation；
- 未用旧训练 JSONL 的候选页集合代替 Working Set；
- 正式输入 fingerprint：待服务器 manifest 与真实 trace 提供后生成。

## Working Set

冻结定义候选为：

```text
active_unique_pages_from_train_and_validation
```

真实统计结果待服务器运行。每个 workload 必须回填：

| workload | Train unique | Validation unique | Union | overlap | Train accesses | Validation accesses |
|---|---:|---:|---:|---:|---:|---:|
| 待运行 | — | — | — | — | — | — |

## Capacity

首先审计 20/40/60；只有其不能产生可区分压力时才允许建议 10/20/40。两组比例的绝对页数和 Reactive-LRU 压力表待服务器结果：

| workload | profile | ratio | DRAM pages | page-enter rate | NVM read/write | exhaustion | reactive demotions | distinguishable |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 待运行 | — | — | — | — | — | — | — | — |

当前不推荐切换容量集合。真实运行后应依据 `capacity_pressure_audit.json` 的预声明阈值给出建议，并由用户确认。

## Burst

Reactive-LRU 将对每个 workload × split × capacity 生成 100/500/1000 非重叠访问窗口。真实 mean/P50/P95/P99/max 尚未运行：

| workload | split | capacity | window | count | mean | P50 | P95 | P99 | max | tail |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 待运行 | — | — | — | — | — | — | — | — | — | — |

## Watermark

Small/Medium/Large 根据 Validation 的 100 访问窗口 P50/P95/P99 机器生成；方案中的 `(4,8)/(8,16)/(16,32)` 未被直接当作正式结果。实际候选、逐项指标、macro average、worst case 和推荐值待服务器运行。

| candidate | F_low | F_target | legal all runs | exhaustion | emergency | early reuse | total demotions | NVM I/O | decision |
|---|---:|---:|---|---:|---:|---:|---:|---:|---|
| Small | — | — | — | — | — | — | — | — | — |
| Medium | — | — | — | — | — | — | — | — | — |
| Large | — | — | — | — | — | — | — | — | — |

## b_max

只有默认水位产生合法推荐后才运行 `1/2/4`。真实 default weighted cost、原始事件数、NVM writes、early reuse、round count 和推荐值待服务器运行：

| b_max | feasible | default cost/access | NVM write | early reuse | rounds | emergency | exhaustion | decision |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | — | — | — | — | — | — | — | — |
| 2 | — | — | — | — | — | — | — | — |
| 4 | — | — | — | — | — | — | — | — |

## K 代理

- 代理值：8、16；
- 状态：`non_formal_calibration_proxy`；
- 正式 `method.candidate_size_K`：保持 `null/pending`；
- 是否影响水位与 `b_max` 结论：待真实运行；
- 若两个代理值改变选择结论，阶段 3 不得冻结。

## 本地测试

执行命令：

```powershell
python -m unittest tests.test_capd_proactive_stage3 -v
```

结果：15 passed，0 failed。测试包含完整 synthetic Stage 3 smoke。`py_compile` 在本机默认写仓库 `qmap/__pycache__` 时因目录权限被拒绝；服务器脚本已通过 `PYTHONPYCACHEPREFIX` 将字节码重定向到临时目录，不影响正式验收。

## 服务器运行

1. 按 manifest 示例填写真实代表 workload 的 Train/Validation 原始 CSV；
2. 确认没有 Test 条目；
3. 执行：

```bash
cd ~/Q-former-for-OS
STAGE3_INPUT_MANIFEST=/absolute/path/stage3_manifest.json \
STAGE3_RUN_ID=stage3-real-001 \
bash scripts/validate_capd_proactive_stage3_server.sh
```

期望日志：仓库根目录 `stage3_validation.log`。期望最终标志：

```text
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
```

请回传：

- `stage3_validation.log`；
- `outputs/capd_proactive_calibration/stage3/stage3-real-001/` 完整目录；
- 服务器仓库当前 commit；
- 实际 manifest（可以将绝对服务器路径脱敏，但不能删除 split/role/fingerprint 信息）。

## 配置状态

- 阶段 0 主配置：未更新；
- `freeze_status.stage3_active_mechanism`：`pending`；
- `stage4_candidate`：`pending`；
- `stage4_training`：`pending`；
- `stage7_workload`：`pending`；
- `formal_test`：`pending`；
- 正式 `F_low/F_target/b_max`：未填写。

## 用户需要确认

真实结果回传后，需要确认：

1. 保留 20/40/60，还是依据压力审计切换 10/20/40；
2. 预声明规则给出的默认水位；
3. 预声明规则给出的默认 `b_max`；
4. K 代理不变性是否足够支持冻结；
5. 是否授权按最小更新规则写入阶段 0 主配置并把阶段 3 推进为 verified。

当前没有任何正式 Test 结论，也不声称 CAPD 优于 baseline、水位对所有 workload 最优、`b_max` 对所有场景最优或 sensitivity 已完成。
