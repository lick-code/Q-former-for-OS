# CAPD 阶段 3 v2 容量失败诊断

## Material Passport

- ID：`CAPD-STAGE3-V2-REAL-003-DIAGNOSIS`
- 类型：实验结果验证与失败根因审计
- 正式产物：`outputs/capd_proactive_calibration/stage3/stage3-v2-real-003/`
- Verification Status：`ANALYZED`
- 数据边界：只使用 Train/Validation；Test 未使用；CAPD 未参与选择
- 冻结状态：`not_freezable`，阶段 3 主配置保持 `pending`

## 结论

`stage3-v2-real-003` 不是死循环、崩溃或服务器环境差异。24 个去重
Reactive-LRU 任务在 17 秒内正常完成，随后因为 primary 和 fallback
都未通过 `capacity_rule_v2` 而按协议停止。水位与 `b_max` 未运行是正确的
短路行为。

服务器正式产物与本地独立复现的以下文件 SHA-256 完全一致：

| 文件 | SHA-256 |
|---|---|
| `capacity_pressure_audit.json` | `7B41302319442F860DF3DC14B8D1F6B2993164BCFBE45F72E37CA5EED356E08C` |
| `reactive_results.jsonl` | `C840A33E4AB0171FDAB8FE14AE32D43762A526F66C91ECBF2030C60BF67255E2` |
| `working_set_summary.json` | `B5AF397B34FC4994821ED3082BC70AE5200D2D8E7BA4343A00E59F5C350C96F1` |
| `selection_decision.json` | `2F9E56D13DA223CEB4D4F53F8A02ADDD6A0EBB977618573FED3C64F4A2BF1E6B` |
| `freeze_candidate.json` | `8B9CEFD0F7C2348E57667BDD82CBD2C6BC5660487115E4FECEAE8AE81FB0CC95` |

## 5m 正式输入为什么必然失败

`real_workload_suite/5m` 的元数据字段虽然含 `limit=5000000`，实际每个
workload 只有 100000 条记录，Train/Validation 为 80000/10000。其
Validation 活跃页集合远小于 Train/Validation 并集 W：

| workload | Union W | Validation unique | Validation/W |
|---|---:|---:|---:|
| canneal | 156 | 40 | 25.64% |
| dedup_pressure | 116 | 10 | 8.62% |
| streamcluster_pressure | 155 | 40 | 25.81% |

Primary 20/40/60 的 Validation replacement fraction：

| workload | 20% | 40% | 60% | 40% page-enter/demotion | 结果 |
|---|---:|---:|---:|---:|---|
| canneal | 0.272727 | 0 | 0 | 40 / 0 | fail |
| dedup_pressure | 0 | 0 | 0 | 10 / 0 | fail |
| streamcluster_pressure | 0.279070 | 0 | 0 | 40 / 0 | fail |

Fallback 10/20/40：

| workload | 10% | 20% | 40% | 20% page-enter/demotion | 结果 |
|---|---:|---:|---:|---:|---|
| canneal | 0.961353 | 0.272727 | 0 | 44 / 12 | fail |
| dedup_pressure | 0 | 0 | 0 | 10 / 0 | fail |
| streamcluster_pressure | 0.961165 | 0.279070 | 0 | 43 / 12 | fail |

v2 要求中档至少 100 次 page-enter 和 100 次 reactive demotion。Primary
中档容量 63/47/62 页已经分别大于 Validation 的 40/10/40 个活跃页，
因此中档 reactive demotion 必为 0。Fallback 的 dedup 中档容量 24 页
也已经大于其 10 个活跃页；canneal 和 streamcluster 虽有压力，但各只有
12 次中档驱逐。两组 profile 因而都不可能整体通过。

## 1m 没有丢失，但直接替换仍然失败

`real_workload_suite/1m` 实际包含每个 workload 1000000 条记录，
Train/Validation 为 800000/100000。它仍在仓库中。诊断重放未读取 Test，
但结果仍不满足 v2：

| workload | Union W | Validation unique | Primary 20/40/60 | Fallback 10/20/40 |
|---|---:|---:|---|---|
| canneal | 247 | 30 | 0 / 0 / 0 | 0.943567 / 0 / 0 |
| dedup_pressure | 444 | 54 | 0 / 0 / 0 | 0.166667 / 0 / 0 |
| streamcluster_pressure | 764 | 10 | 0 / 0 / 0 | 0 / 0 / 0 |

1m 更长，但其连续 Validation 尾段出现了更强的 phase collapse。问题不是
记录数本身，而是程序用 Train/Validation 并集 W 换算绝对容量，却只在
活跃集很小的 Validation 相位上判定压力。仅把路径改为 1m 会再次失败。

1m 已用于本次诊断，不能再声称它是规则修改后的全新正式 Validation。

## 防返工修复

已实现：

1. `capacity_input_preflight`：正式回放前检查中档容量是否已经容纳整个
   Validation 活跃集；
2. `preflight_capd_proactive_stage3_inputs.py`：结构不可达时返回 3，写出
  逐 workload JSON，并跳过昂贵回放；
3. 采集器支持自动发现或显式 `--qmap-root`，不再硬编码
   `/root/qmap-work`；
4. 新鲜 pair 工具只生成 Train/Validation，不创建 Test；
5. 一次性服务器入口重新采集每个 workload 恰好 1M 条真实 RW，切分
   600k Train + 400k Validation，预检通过后才运行完整 Stage 3；
6. 中断时保留采集产物和 Stage-3 checkpoint，可按相同 phase 恢复。

本次修复没有降低 `capacity_rule_v2` 的任何阈值，没有把 Test 改名为
Validation，也没有修改主配置或提前冻结水位、容量和 `b_max`。
