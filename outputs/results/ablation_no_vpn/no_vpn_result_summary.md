# Full CAPD vs CAPD-NoVPN 消融实验结果

## 结论摘要

- 结果齐全：实际找到预期的 3 个 workload、3 个 seed、2 个 variant，共 18 份最终 test/replay JSON；9 个 Full–NoVPN 配对均为 `COMPLETE`。
- 没有缺失或失败组合。18 份结果均可解析、测试指标完整、所引用的 best checkpoint 存在；36 份 train/eval 日志未命中 Traceback、CUDA OOM、NaN、Exception、FAILED 等失败信号。
- `canneal`：NoVPN 的平均 cost 增加 `0.301684%`，但三个 seed 的方向为两差一好，整体应视为“基本不变、方向不稳定”。
- `streamcluster_pressure`：NoVPN 的 cost 在三个 seed 均增加 `0.486498%`，属于稳定但幅度较小的变差。三个 seed 的记录值完全相同。
- `dedup_pressure`：NoVPN 的 cost 在三个 seed 均略增，平均仅 `0.007397%`，可视为基本不变。
- 综合三类 workload，去掉 VPN embedding 没有造成明显、跨 workload 稳定的大幅退化；现有结果不支持“CAPD 明显依赖 VPN embedding”的判断。

## 实际找到的目录

- 测试结果根目录：`outputs/results/ablation_no_vpn/`
- Full 测试结果：`outputs/results/ablation_no_vpn/full/`
- NoVPN 测试结果：`outputs/results/ablation_no_vpn/no_vpn/`
- Checkpoint：`outputs/checkpoints/ablation_no_vpn/`
- 日志：`outputs/logs/ablation_no_vpn/`

实际 workload 为 `canneal`、`streamcluster_pressure`、`dedup_pressure`；实际 seed 为 `3136859`、`42`、`2026`，与预期一致。

## 完整性检查

| workload | seed | full result | no_vpn result | status |
|---|---:|---|---|---|
| canneal | 3136859 | `full/canneal/seed_3136859/qmap.json` | `no_vpn/canneal/seed_3136859/qmap.json` | COMPLETE |
| canneal | 42 | `full/canneal/seed_42/qmap.json` | `no_vpn/canneal/seed_42/qmap.json` | COMPLETE |
| canneal | 2026 | `full/canneal/seed_2026/qmap.json` | `no_vpn/canneal/seed_2026/qmap.json` | COMPLETE |
| streamcluster_pressure | 3136859 | `full/streamcluster_pressure/seed_3136859/qmap.json` | `no_vpn/streamcluster_pressure/seed_3136859/qmap.json` | COMPLETE |
| streamcluster_pressure | 42 | `full/streamcluster_pressure/seed_42/qmap.json` | `no_vpn/streamcluster_pressure/seed_42/qmap.json` | COMPLETE |
| streamcluster_pressure | 2026 | `full/streamcluster_pressure/seed_2026/qmap.json` | `no_vpn/streamcluster_pressure/seed_2026/qmap.json` | COMPLETE |
| dedup_pressure | 3136859 | `full/dedup_pressure/seed_3136859/qmap.json` | `no_vpn/dedup_pressure/seed_3136859/qmap.json` | COMPLETE |
| dedup_pressure | 42 | `full/dedup_pressure/seed_42/qmap.json` | `no_vpn/dedup_pressure/seed_42/qmap.json` | COMPLETE |
| dedup_pressure | 2026 | `full/dedup_pressure/seed_2026/qmap.json` | `no_vpn/dedup_pressure/seed_2026/qmap.json` | COMPLETE |

表中的结果路径均相对于 `outputs/results/ablation_no_vpn/`。所有 18 份结果均满足 `evaluation_split=test`、`test_trace_opened=true`、`test_used_for_selection=false`，因此使用的是最终 test/replay 指标，而不是训练 loss。

## 逐 seed 核心结果

`Cost Δ% = (NoVPN cost - Full cost) / Full cost × 100`；hit 以百分比显示。`Hit Δ` 使用百分点（pp），其底层计算为 NoVPN hit rate 减 Full hit rate。

| workload | seed | Full cost | NoVPN cost | Cost Δ% | Full hit | NoVPN hit | Hit Δ (pp) | Read Δ | Write Δ | Demotion Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| canneal | 3136859 | 229156 | 227418 | -0.758435% | 98.6500% | 98.7290% | +0.0790 | -158 | 0 | -158 |
| canneal | 42 | 226318 | 227396 | +0.476321% | 98.7790% | 98.7300% | -0.0490 | +98 | 0 | +98 |
| canneal | 2026 | 227011 | 229706 | +1.187167% | 98.7475% | 98.6250% | -0.1225 | +245 | 0 | +245 |
| streamcluster_pressure | 3136859 | 230628 | 231750 | +0.486498% | 98.5790% | 98.5280% | -0.0510 | +102 | 0 | +102 |
| streamcluster_pressure | 42 | 230628 | 231750 | +0.486498% | 98.5790% | 98.5280% | -0.0510 | +102 | 0 | +102 |
| streamcluster_pressure | 2026 | 230628 | 231750 | +0.486498% | 98.5790% | 98.5280% | -0.0510 | +102 | 0 | +102 |
| dedup_pressure | 3136859 | 1045555 | 1045583 | +0.002678% | 99.6641% | 99.6639% | -0.0002 | +1 | +1 | +2 |
| dedup_pressure | 42 | 1045275 | 1045308 | +0.003157% | 99.6667% | 99.6664% | -0.0003 | +3 | 0 | +3 |
| dedup_pressure | 2026 | 1045434 | 1045605 | +0.016357% | 99.6652% | 99.6637% | -0.0015 | +14 | +1 | +15 |

## Workload 汇总

均值与标准差由三个 seed 的原始 cost 计算；标准差为 sample std（样本标准差，分母为 `n-1`）。`Mean Cost Δ%` 是三个配对 seed 的 Cost Δ% 算术平均。

| workload | Full cost mean±std | NoVPN cost mean±std | Mean Cost Δ% | 方向是否稳定 |
|---|---:|---:|---:|---|
| canneal | 227495.00 ± 1479.61 | 228173.33 ± 1327.37 | +0.301684% | 否：两次变差、一次变好 |
| streamcluster_pressure | 230628.00 ± 0.00 | 231750.00 ± 0.00 | +0.486498% | 是：三个 seed 均变差 |
| dedup_pressure | 1045421.33 ± 140.43 | 1045498.67 ± 165.49 | +0.007397% | 是：三个 seed 均略差 |

## 测试指标与产物路径

| workload | seed | variant | weighted cost | hit rate | NVM reads | NVM writes | demotions | checkpoint path | result path |
|---|---:|---|---:|---:|---:|---:|---:|---|---|
| canneal | 3136859 | full | 229156 | 0.986500 | 2684 | 16 | 2636 | `outputs/checkpoints/ablation_no_vpn/full/canneal/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/canneal/seed_3136859/qmap.json` |
| canneal | 3136859 | no_vpn | 227418 | 0.987290 | 2526 | 16 | 2478 | `outputs/checkpoints/ablation_no_vpn/no_vpn/canneal/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/canneal/seed_3136859/qmap.json` |
| canneal | 42 | full | 226318 | 0.987790 | 2426 | 16 | 2378 | `outputs/checkpoints/ablation_no_vpn/full/canneal/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/canneal/seed_42/qmap.json` |
| canneal | 42 | no_vpn | 227396 | 0.987300 | 2524 | 16 | 2476 | `outputs/checkpoints/ablation_no_vpn/no_vpn/canneal/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/canneal/seed_42/qmap.json` |
| canneal | 2026 | full | 227011 | 0.987475 | 2489 | 16 | 2441 | `outputs/checkpoints/ablation_no_vpn/full/canneal/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/canneal/seed_2026/qmap.json` |
| canneal | 2026 | no_vpn | 229706 | 0.986250 | 2734 | 16 | 2686 | `outputs/checkpoints/ablation_no_vpn/no_vpn/canneal/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/canneal/seed_2026/qmap.json` |
| streamcluster_pressure | 3136859 | full | 230628 | 0.985790 | 2841 | 1 | 2778 | `outputs/checkpoints/ablation_no_vpn/full/streamcluster_pressure/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/streamcluster_pressure/seed_3136859/qmap.json` |
| streamcluster_pressure | 3136859 | no_vpn | 231750 | 0.985280 | 2943 | 1 | 2880 | `outputs/checkpoints/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_3136859/qmap.json` |
| streamcluster_pressure | 42 | full | 230628 | 0.985790 | 2841 | 1 | 2778 | `outputs/checkpoints/ablation_no_vpn/full/streamcluster_pressure/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/streamcluster_pressure/seed_42/qmap.json` |
| streamcluster_pressure | 42 | no_vpn | 231750 | 0.985280 | 2943 | 1 | 2880 | `outputs/checkpoints/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_42/qmap.json` |
| streamcluster_pressure | 2026 | full | 230628 | 0.985790 | 2841 | 1 | 2778 | `outputs/checkpoints/ablation_no_vpn/full/streamcluster_pressure/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/streamcluster_pressure/seed_2026/qmap.json` |
| streamcluster_pressure | 2026 | no_vpn | 231750 | 0.985280 | 2943 | 1 | 2880 | `outputs/checkpoints/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/streamcluster_pressure/seed_2026/qmap.json` |
| dedup_pressure | 3136859 | full | 1045555 | 0.996641 | 1818 | 1541 | 3295 | `outputs/checkpoints/ablation_no_vpn/full/dedup_pressure/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/dedup_pressure/seed_3136859/qmap.json` |
| dedup_pressure | 3136859 | no_vpn | 1045583 | 0.996639 | 1819 | 1542 | 3297 | `outputs/checkpoints/ablation_no_vpn/no_vpn/dedup_pressure/seed_3136859/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/dedup_pressure/seed_3136859/qmap.json` |
| dedup_pressure | 42 | full | 1045275 | 0.996667 | 1791 | 1542 | 3269 | `outputs/checkpoints/ablation_no_vpn/full/dedup_pressure/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/dedup_pressure/seed_42/qmap.json` |
| dedup_pressure | 42 | no_vpn | 1045308 | 0.996664 | 1794 | 1542 | 3272 | `outputs/checkpoints/ablation_no_vpn/no_vpn/dedup_pressure/seed_42/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/dedup_pressure/seed_42/qmap.json` |
| dedup_pressure | 2026 | full | 1045434 | 0.996652 | 1807 | 1541 | 3284 | `outputs/checkpoints/ablation_no_vpn/full/dedup_pressure/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/full/dedup_pressure/seed_2026/qmap.json` |
| dedup_pressure | 2026 | no_vpn | 1045605 | 0.996637 | 1821 | 1542 | 3299 | `outputs/checkpoints/ablation_no_vpn/no_vpn/dedup_pressure/seed_2026/qmap_best.pth` | `outputs/results/ablation_no_vpn/no_vpn/dedup_pressure/seed_2026/qmap.json` |

## 核验范围与限制

- 材料：18 份 `qmap.json`、18 份 checkpoint manifest、18 个结果引用的 best checkpoint，以及 36 份 train/eval 日志。
- 所有 manifest 均可解析且 `nan_or_inf_detected=false`；结果中的顶层指标与 `test_metrics` 对应字段一致且均为有限数值。
- 本报告只做描述性配对比较，未重新训练、未重放测试、未修改任何原始产物，也未进行显著性检验。
- `streamcluster_pressure` 的三个 seed 在 cost、hit、NVM reads/writes 和 demotions 上完全相同，因此其 sample std 为 0；“方向稳定”仅描述现有记录的一致性。
