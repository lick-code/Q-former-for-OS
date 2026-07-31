# CAPD 主动降级 Stage 8 正式同步 Replay 报告

状态：聚合完成，须以独立 verification 为最终门禁。

本报告与 JSON/CSV 来自同一份已审计聚合对象；Test 未用于参数选择。

## 表 A：统一主动机制下的页面选择

| Workload | 容量 | 方法 | weighted cost（mean ± sample std） |
|---|---:|---|---:|
| blackscholes | 0.20 | proactive_lru | 771292.000000 ± 0.000000 |
| blackscholes | 0.20 | proactive_clock | 771424.000000 ± 0.000000 |
| blackscholes | 0.20 | tpp_inspired | 771292.000000 ± 0.000000 |
| blackscholes | 0.20 | capd | 765706.666667 ± 7889.360071 |
| blackscholes | 0.20 | oracle | 757796.000000 ± 0.000000 |
| blackscholes | 0.40 | proactive_lru | 600040.000000 ± 0.000000 |
| blackscholes | 0.40 | proactive_clock | 600040.000000 ± 0.000000 |
| blackscholes | 0.40 | tpp_inspired | 600040.000000 ± 0.000000 |
| blackscholes | 0.40 | capd | 600040.000000 ± 0.000000 |
| blackscholes | 0.40 | oracle | 600040.000000 ± 0.000000 |
| blackscholes | 0.60 | proactive_lru | 600040.000000 ± 0.000000 |
| blackscholes | 0.60 | proactive_clock | 600040.000000 ± 0.000000 |
| blackscholes | 0.60 | tpp_inspired | 600040.000000 ± 0.000000 |
| blackscholes | 0.60 | capd | 600040.000000 ± 0.000000 |
| blackscholes | 0.60 | oracle | 600040.000000 ± 0.000000 |
| canneal | 0.20 | proactive_lru | 615612.000000 ± 0.000000 |
| canneal | 0.20 | proactive_clock | 615612.000000 ± 0.000000 |
| canneal | 0.20 | tpp_inspired | 615612.000000 ± 0.000000 |
| canneal | 0.20 | capd | 615612.000000 ± 0.000000 |
| canneal | 0.20 | oracle | 615612.000000 ± 0.000000 |
| canneal | 0.40 | proactive_lru | 610032.000000 ± 0.000000 |
| canneal | 0.40 | proactive_clock | 610032.000000 ± 0.000000 |
| canneal | 0.40 | tpp_inspired | 610032.000000 ± 0.000000 |
| canneal | 0.40 | capd | 610032.000000 ± 0.000000 |
| canneal | 0.40 | oracle | 610032.000000 ± 0.000000 |
| canneal | 0.60 | proactive_lru | 610032.000000 ± 0.000000 |
| canneal | 0.60 | proactive_clock | 610032.000000 ± 0.000000 |
| canneal | 0.60 | tpp_inspired | 610032.000000 ± 0.000000 |
| canneal | 0.60 | capd | 610032.000000 ± 0.000000 |
| canneal | 0.60 | oracle | 610032.000000 ± 0.000000 |
| dedup_pressure | 0.20 | proactive_lru | 602773.000000 ± 0.000000 |
| dedup_pressure | 0.20 | proactive_clock | 602773.000000 ± 0.000000 |
| dedup_pressure | 0.20 | tpp_inspired | 602773.000000 ± 0.000000 |
| dedup_pressure | 0.20 | capd | 602773.000000 ± 0.000000 |
| dedup_pressure | 0.20 | oracle | 602773.000000 ± 0.000000 |
| dedup_pressure | 0.40 | proactive_lru | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.40 | proactive_clock | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.40 | tpp_inspired | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.40 | capd | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.40 | oracle | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.60 | proactive_lru | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.60 | proactive_clock | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.60 | tpp_inspired | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.60 | capd | 601873.000000 ± 0.000000 |
| dedup_pressure | 0.60 | oracle | 601873.000000 ± 0.000000 |
| fluidanimate | 0.20 | proactive_lru | 600015.000000 ± 0.000000 |
| fluidanimate | 0.20 | proactive_clock | 600015.000000 ± 0.000000 |
| fluidanimate | 0.20 | tpp_inspired | 600015.000000 ± 0.000000 |
| fluidanimate | 0.20 | capd | 600015.000000 ± 0.000000 |
| fluidanimate | 0.20 | oracle | 600015.000000 ± 0.000000 |
| fluidanimate | 0.40 | proactive_lru | 600015.000000 ± 0.000000 |
| fluidanimate | 0.40 | proactive_clock | 600015.000000 ± 0.000000 |
| fluidanimate | 0.40 | tpp_inspired | 600015.000000 ± 0.000000 |
| fluidanimate | 0.40 | capd | 600015.000000 ± 0.000000 |
| fluidanimate | 0.40 | oracle | 600015.000000 ± 0.000000 |
| fluidanimate | 0.60 | proactive_lru | 600015.000000 ± 0.000000 |
| fluidanimate | 0.60 | proactive_clock | 600015.000000 ± 0.000000 |
| fluidanimate | 0.60 | tpp_inspired | 600015.000000 ± 0.000000 |
| fluidanimate | 0.60 | capd | 600015.000000 ± 0.000000 |
| fluidanimate | 0.60 | oracle | 600015.000000 ± 0.000000 |
| streamcluster_pressure | 0.20 | proactive_lru | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.20 | proactive_clock | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.20 | tpp_inspired | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.20 | capd | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.20 | oracle | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.40 | proactive_lru | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.40 | proactive_clock | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.40 | tpp_inspired | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.40 | capd | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.40 | oracle | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.60 | proactive_lru | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.60 | proactive_clock | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.60 | tpp_inspired | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.60 | capd | 600138.000000 ± 0.000000 |
| streamcluster_pressure | 0.60 | oracle | 600138.000000 ± 0.000000 |
| swaptions | 0.20 | proactive_lru | 600049.000000 ± 0.000000 |
| swaptions | 0.20 | proactive_clock | 600049.000000 ± 0.000000 |
| swaptions | 0.20 | tpp_inspired | 600049.000000 ± 0.000000 |
| swaptions | 0.20 | capd | 600049.000000 ± 0.000000 |
| swaptions | 0.20 | oracle | 600049.000000 ± 0.000000 |
| swaptions | 0.40 | proactive_lru | 600049.000000 ± 0.000000 |
| swaptions | 0.40 | proactive_clock | 600049.000000 ± 0.000000 |
| swaptions | 0.40 | tpp_inspired | 600049.000000 ± 0.000000 |
| swaptions | 0.40 | capd | 600049.000000 ± 0.000000 |
| swaptions | 0.40 | oracle | 600049.000000 ± 0.000000 |
| swaptions | 0.60 | proactive_lru | 600049.000000 ± 0.000000 |
| swaptions | 0.60 | proactive_clock | 600049.000000 ± 0.000000 |
| swaptions | 0.60 | tpp_inspired | 600049.000000 ± 0.000000 |
| swaptions | 0.60 | capd | 600049.000000 ± 0.000000 |
| swaptions | 0.60 | oracle | 600049.000000 ± 0.000000 |

## 表 B：主动储备机制对照

| Workload | 容量 | 方法 | weighted cost | fallback rate |
|---|---:|---|---:|---:|
| blackscholes | 0.20 | reactive_lru | 600040.000000 | 0.000000 |
| blackscholes | 0.20 | proactive_lru | 771292.000000 | 0.000000 |
| blackscholes | 0.40 | reactive_lru | 600040.000000 | 0.000000 |
| blackscholes | 0.40 | proactive_lru | 600040.000000 | 0.000000 |
| blackscholes | 0.60 | reactive_lru | 600040.000000 | 0.000000 |
| blackscholes | 0.60 | proactive_lru | 600040.000000 | 0.000000 |
| canneal | 0.20 | reactive_lru | 615482.000000 | 0.000000 |
| canneal | 0.20 | proactive_lru | 615612.000000 | 0.000000 |
| canneal | 0.40 | reactive_lru | 610032.000000 | 0.000000 |
| canneal | 0.40 | proactive_lru | 610032.000000 | 0.000000 |
| canneal | 0.60 | reactive_lru | 610032.000000 | 0.000000 |
| canneal | 0.60 | proactive_lru | 610032.000000 | 0.000000 |
| dedup_pressure | 0.20 | reactive_lru | 602613.000000 | 0.000000 |
| dedup_pressure | 0.20 | proactive_lru | 602773.000000 | 0.000000 |
| dedup_pressure | 0.40 | reactive_lru | 601873.000000 | 0.000000 |
| dedup_pressure | 0.40 | proactive_lru | 601873.000000 | 0.000000 |
| dedup_pressure | 0.60 | reactive_lru | 601873.000000 | 0.000000 |
| dedup_pressure | 0.60 | proactive_lru | 601873.000000 | 0.000000 |
| fluidanimate | 0.20 | reactive_lru | 600015.000000 | 0.000000 |
| fluidanimate | 0.20 | proactive_lru | 600015.000000 | 0.000000 |
| fluidanimate | 0.40 | reactive_lru | 600015.000000 | 0.000000 |
| fluidanimate | 0.40 | proactive_lru | 600015.000000 | 0.000000 |
| fluidanimate | 0.60 | reactive_lru | 600015.000000 | 0.000000 |
| fluidanimate | 0.60 | proactive_lru | 600015.000000 | 0.000000 |
| streamcluster_pressure | 0.20 | reactive_lru | 600138.000000 | 0.000000 |
| streamcluster_pressure | 0.20 | proactive_lru | 600138.000000 | 0.000000 |
| streamcluster_pressure | 0.40 | reactive_lru | 600138.000000 | 0.000000 |
| streamcluster_pressure | 0.40 | proactive_lru | 600138.000000 | 0.000000 |
| streamcluster_pressure | 0.60 | reactive_lru | 600138.000000 | 0.000000 |
| streamcluster_pressure | 0.60 | proactive_lru | 600138.000000 | 0.000000 |
| swaptions | 0.20 | reactive_lru | 600049.000000 | 0.000000 |
| swaptions | 0.20 | proactive_lru | 600049.000000 | 0.000000 |
| swaptions | 0.40 | reactive_lru | 600049.000000 | 0.000000 |
| swaptions | 0.40 | proactive_lru | 600049.000000 | 0.000000 |
| swaptions | 0.60 | reactive_lru | 600049.000000 | 0.000000 |
| swaptions | 0.60 | proactive_lru | 600049.000000 | 0.000000 |

## 预声明配对统计

CAPD 三 seed 先在每个 workload×capacity 单元内取均值，再与 TPP-inspired 配对。
18 单元 CAPD−TPP weighted cost 的均值为 -310.296296，95% percentile bootstrap CI 为 [-930.888889, 0.000000]（seed=20260801，10000 次）。
逐单元方向：CAPD 较低 1 个、相同 17 个、较高 0 个；预声明 CI 判定为 `ci_includes_zero_no_single_direction_claim`，平均相对改善为 0.040231%。
该描述同时保留逐 workload 方向、CI 与效应量，不依据单一 p-value 或总体均值下结论。

## 解释边界

Synchronous Replay measures page-ranking quality, NVM events, weighted cost, state trajectory, and synchronous decision overhead; it is not real background concurrency or foreground latency.
fallback 很少或为零仅说明同步功能正确性环境中的观察，不能外推到异步系统。
Stage 8 不包含 Stage 9 的真实 CPU、内存或推理开销测量。
