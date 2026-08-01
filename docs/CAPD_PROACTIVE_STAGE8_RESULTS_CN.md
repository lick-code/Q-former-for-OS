# CAPD 主动降级 Stage 8 正式结果说明

## 1. 权威证据与口径

权威运行目录：`outputs/capd_proactive_stage8/stage8-sync-replay-r3/`。

本说明只转述同目录 `artifacts/aggregate.json`、`artifacts/per_workload_raw.csv`、表 A/B、配对 CSV 和 `verification.json` 中已经独立审计的结果，不重新选择指标、workload、容量、checkpoint 或 CAPD seed。主指标为 weighted cost，越低越好。每个 Test trace 含 600000 次原始访问。

正式矩阵共 144 个 job：六个 workload、三个容量比例，以及五个确定性策略加三个独立 CAPD seed。18 个 workload×capacity 单元全部通过实验 A/B 公平性审计。

## 2. 实验 A：统一主动机制下的页面选择

### 2.1 主比较：CAPD 对 TPP-inspired

| 统计项 | 正式结果 |
|---|---:|
| 18 单元 CAPD−TPP weighted cost 均值 | -310.296296 |
| 18 单元平均相对改善 | 0.040231% |
| 95% percentile bootstrap CI | [-930.888889, 0.000000] |
| bootstrap | seed=20260801，10000 次，单元重采样 |
| 单元方向 | CAPD 较低 1 / 相同 17 / 较高 0 |

CI 包含 0，预声明判定为 `ci_includes_zero_no_single_direction_claim`。因此可以描述 CAPD 没有出现高于 TPP 的单元且宏平均略低，但不能声称它在六 workload 正式套件上具有统计上确定或普遍的优势。

### 2.2 唯一产生排序差异的单元

`blackscholes@20%`：

| 方法 | weighted cost |
|---|---:|
| Oracle | 757796 |
| CAPD（三 seed） | 765706.666667 ± 7889.360071 |
| Proactive-LRU | 771292 |
| TPP-inspired | 771292 |
| Proactive-CLOCK | 771424 |

CAPD 相对 TPP 平均降低 5585.333333，即 0.724153%；相对 Oracle 仍高 1.043905%。三个 CAPD seed 的原始 weighted cost 分别为：3136859=`760028`、42=`762377`、2026=`774715`。这里报告均值和 sample standard deviation，没有选择表现最好的 seed。

该单元 CAPD 三 seed 均值相对 TPP 的事件变化为：DRAM hits `+195.333`、NVM reads `+373`、NVM writes `-568.333`、proactive demotions `-198`。Cost 的净下降主要来自写入和降级事件减少，部分被 NVM read 增加抵消。

CAPD 的 Early-Reuse Rate 均值在 Δ=64/256/1024 时分别为 37.2702%/74.8068%/91.7924%；TPP 分别为 36.2185%/75.8454%/92.1095%。这些辅助指标方向并不完全一致，不能只取有利窗口下结论。

### 2.3 seen/unseen 与宏平均

| 分组 | CAPD | TPP-inspired | Oracle |
|---|---:|---:|---:|
| seen calibration（9 单元） | 604734.333333 | 604734.333333 | 604734.333333 |
| held-out unseen（9 单元） | 618442.074074 | 619062.666667 | 617563.111111 |
| all workloads macro（18 单元） | 611588.203704 | 611898.500000 | 611148.722222 |

held-out 宏平均的 0.100247% CAPD 相对改善完全由 `blackscholes@20%` 一个单元贡献；seen 的 9 个单元全部持平。不能将 held-out 宏平均写成跨 workload 的一致泛化优势。

## 3. 实验 B：主动储备机制

Proactive-LRU 相对 Reactive-LRU 的逐单元方向为：成本更低 0、相同 15、成本更高 3。

| 单元 | Reactive-LRU | Proactive-LRU | Proactive−Reactive | Proactive 相对成本变化 |
|---|---:|---:|---:|---:|
| blackscholes@20% | 600040 | 771292 | +171252 | +28.540097% |
| canneal@20% | 615482 | 615612 | +130 | +0.021122% |
| dedup_pressure@20% | 602613 | 602773 | +160 | +0.026551% |

其余 15 个单元持平。all-workloads macro 中 Proactive-LRU 为 611898.500000，Reactive-LRU 为 602368.388889，前者高 1.582107%，且差异主要由 `blackscholes@20%` 主导。本次同步 Replay 因而不支持“低水位主动储备降低 weighted cost”的结论；它确实维持了更多空闲页框，但在发生降级的单元引入了额外迁移，或使页面更早回到 NVM。

## 4. Fallback、提前误降与 OOV 诊断

- 144 个 job 的 emergency demotion 均为 0，FallbackRate 均为 0。
- `blackscholes@20%` 的主动方法存在大量短期复用；例如 CAPD 的 Δ=1024 Early-Reuse Rate 均值为 91.7924%。这表明在该压力单元中，不少主动降级页面很快再次访问。
- `canneal@20%` 和 `dedup_pressure@20%` 的主动 demotion 分别为 558 和 90，wasted demotion count 与之相同，表示这些被主动降级的页面在本 Test 区间内不再复用；这解释了相对 Reactive-LRU 的小幅额外 demotion cost。
- CAPD 在全部 18 个单元的 page/PC access OOV 与 unique OOV ratio 均为 100%。运行严格保持冻结词表、不扩展 vocabulary，并将未知标识映射到 UNK=0。这是正式结果的重要泛化限制，而不是允许查看 Test 后修改 Stage4 checkpoint 的理由。

## 5. 准确结论与解释边界

Stage8 工程和实验门禁已经完成，结果可复现且公平性合同通过。就性能而言，正式数据只显示 CAPD 在一个 held-out、20% 容量单元上有平均收益；其余 17 个单元与 TPP 持平，bootstrap CI 包含 0。主动储备机制在本同步 Replay 中没有降低 weighted cost，且在三个 20% 单元增加成本。

同步 Replay 只能解释页面排序质量、NVM 事件、weighted cost、状态轨迹和同步执行下的决策开销。它不是实际后台并发执行，也不是实际前台延迟、CPU 或内存开销测量；这些属于 Stage9。
