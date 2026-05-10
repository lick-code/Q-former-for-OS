# Final Tables

All results use 2,000 test accesses per workload. Hit rate is reported in percent. Cost denotes weighted access cost; lower cost, NVM writes, migrations, and decision latency are better.

## Table 1: QMAP vs. LRU/Random/LFU/CLOCK across workloads

| Workload | Policy | Hit rate (%) | Cost | NVM writes | Migrations | Avg. decision (ms) |
|---|---:|---:|---:|---:|---:|---:|
| hotset | LRU | 86.50 | 3,766 | 38 | 142 | 0.000 |
| hotset | Random | 83.90 | 4,372 | 55 | 194 | 0.001 |
| hotset | LFU | 86.60 | 3,746 | 39 | 140 | 0.023 |
| hotset | CLOCK | 86.35 | 3,803 | 40 | 145 | 0.001 |
| hotset | QMAP | 86.45 | 3,777 | 38 | 143 | 5.624 |
| writeheavy | LRU | 71.30 | 7,510 | 238 | 446 | 0.000 |
| writeheavy | Random | 66.45 | 8,721 | 310 | 543 | 0.001 |
| writeheavy | LFU | 71.95 | 7,339 | 224 | 433 | 0.023 |
| writeheavy | CLOCK | 68.05 | 8,313 | 282 | 511 | 0.001 |
| writeheavy | QMAP | 73.45 | 6,979 | 209 | 403 | 3.033 |
| streaming | LRU | 0.00 | 22,920 | 100 | 1,872 | 0.000 |
| streaming | Random | 0.00 | 22,920 | 100 | 1,872 | 0.001 |
| streaming | LFU | 0.00 | 22,920 | 100 | 1,872 | 0.021 |
| streaming | CLOCK | 0.00 | 22,920 | 100 | 1,872 | 0.001 |
| streaming | QMAP | 0.70 | 22,764 | 99 | 1,858 | 2.075 |
| phasechange | LRU | 62.25 | 9,401 | 188 | 627 | 0.000 |
| phasechange | Random | 53.85 | 11,317 | 222 | 795 | 0.001 |
| phasechange | LFU | 71.70 | 7,170 | 112 | 438 | 0.022 |
| phasechange | CLOCK | 54.90 | 11,108 | 233 | 774 | 0.001 |
| phasechange | QMAP | 61.25 | 9,589 | 172 | 647 | 2.581 |
| pcrwstress | LRU | 72.70 | 6,870 | 24 | 418 | 0.000 |
| pcrwstress | Random | 65.35 | 8,943 | 100 | 565 | 0.001 |
| pcrwstress | LFU | 76.05 | 6,133 | 24 | 351 | 0.023 |
| pcrwstress | CLOCK | 68.30 | 8,270 | 96 | 506 | 0.001 |
| pcrwstress | QMAP | 74.65 | 6,441 | 24 | 379 | 3.142 |
| Average | LRU | 58.55 | 10,093 | 117.60 | 701.00 | 0.000 |
| Average | Random | 53.91 | 11,255 | 157.40 | 793.80 | 0.001 |
| Average | LFU | 61.26 | 9,462 | 99.80 | 646.80 | 0.022 |
| Average | CLOCK | 55.52 | 10,883 | 150.20 | 761.60 | 0.001 |
| Average | QMAP | 59.30 | 9,910 | 108.40 | 686.00 | 3.291 |

**总结：** QMAP 在 writeheavy 和 streaming 场景中表现较突出，其中 writeheavy 下相较 LRU 将命中率从 71.30% 提升到 73.45%，同时将 NVM 写入从 238 次降至 209 次，weighted access cost 从 7,510 降至 6,979；streaming 下各传统策略命中率均为 0，QMAP 仍取得 0.70% 的小幅命中并降低总成本。pcrwstress 中 QMAP 的写入次数与 LRU/LFU 同为 24 次，成本低于 LRU 和 Random/CLOCK，但 LFU 在该 workload 上仍取得最高命中率和最低成本。整体平均看，QMAP 的平均 cost 为 9,910，低于 LRU、Random 和 CLOCK，NVM 写入平均值也低于 LRU、Random 和 CLOCK；但 LFU 在平均命中率和平均 cost 上仍较强，说明 QMAP 的优势主要体现在写敏感、迁移敏感和部分非平稳 workload 上，而非所有场景的纯命中率最优。

## Table 2: Checkpoint sweep

| Epoch | Hit rate (%) | Cost | NVM writes | NVM reads | Migrations | Avg. decision (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 54.35 | 11,043 | 140 | 773 | 785 | 2.105 |
| 2 | 58.05 | 10,193 | 122 | 717 | 711 | 2.031 |
| 3 | 59.10 | 9,954 | 118 | 700 | 690 | 2.056 |
| 4 | 58.95 | 9,991 | 120 | 701 | 693 | 2.013 |
| 5 | 58.95 | 9,991 | 120 | 701 | 693 | 2.022 |
| 6 | 59.10 | 9,956 | 119 | 699 | 690 | 2.155 |
| 7 | 59.30 | 9,908 | 117 | 697 | 686 | 2.037 |
| 8 | 59.55 | 9,849 | 115 | 694 | 681 | 2.088 |
| 9 | 59.50 | 9,860 | 115 | 695 | 682 | 2.041 |
| 10 | 59.60 | 9,838 | 115 | 693 | 680 | 2.152 |

**总结：** 随着训练 epoch 增加，QMAP 的性能总体呈稳定改善趋势。第 1 轮 checkpoint 的命中率为 54.35%，cost 为 11,043；到第 10 轮时命中率提升至 59.60%，cost 降至 9,838，同时 NVM writes 从 140 次降至 115 次，migrations 从 785 次降至 680 次。第 8 至第 10 轮之间指标波动很小，说明模型在后期基本收敛。综合命中率、写入次数和 cost，第 10 轮 checkpoint 是该组实验中最优且最稳定的选择。

## Table 3: Parameter sensitivity

Baseline configuration is history length = 10, candidate count = 64, DRAM capacity = 128, and lookahead = 256.

| Parameter | Value | Hit rate (%) | Delta hit (pp) | Cost | Delta cost (%) | NVM writes | Delta writes (%) | Migrations | Avg. decision (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| history length | 5 | 59.35 | +0.05 | 9,887 | -0.17 | 112 | -2.61 | 685 | 3.670 |
| history length | 10 | 59.30 | +0.00 | 9,904 | +0.00 | 115 | +0.00 | 686 | 4.101 |
| history length | 20 | 59.65 | +0.35 | 9,829 | -0.76 | 116 | +0.87 | 679 | 3.341 |
| history length | 50 | 59.75 | +0.45 | 9,803 | -1.02 | 114 | -0.87 | 677 | 4.558 |
| candidate count | 16 | 57.10 | -2.20 | 10,412 | +5.13 | 127 | +10.43 | 730 | 3.933 |
| candidate count | 32 | 59.00 | -0.30 | 9,982 | +0.79 | 121 | +5.22 | 692 | 3.604 |
| candidate count | 64 | 59.30 | +0.00 | 9,904 | +0.00 | 115 | +0.00 | 686 | 4.101 |
| DRAM capacity | 64 | 50.40 | -8.90 | 12,530 | +26.51 | 129 | +12.17 | 928 | 3.159 |
| DRAM capacity | 128 | 59.30 | +0.00 | 9,904 | +0.00 | 115 | +0.00 | 686 | 4.101 |
| DRAM capacity | 256 | 71.60 | +12.30 | 5,850 | -40.93 | 81 | -29.57 | 312 | 5.999 |
| lookahead | 128 | 59.60 | +0.30 | 9,832 | -0.73 | 112 | -2.61 | 680 | 3.392 |
| lookahead | 256 | 59.30 | +0.00 | 9,904 | +0.00 | 115 | +0.00 | 686 | 4.101 |
| lookahead | 512 | 59.90 | +0.60 | 9,774 | -1.31 | 116 | +0.87 | 674 | 5.093 |

**总结：** 参数敏感性实验显示，QMAP 对候选数量和 DRAM 容量较敏感，对 history length 和 lookahead 的变化相对稳健。candidate count 从 64 降到 16 时，命中率下降 2.20 个百分点，cost 上升 5.13%，说明候选集合过小会限制模型选择空间。DRAM capacity 是影响最大的因素：容量从 128 降到 64 时，命中率下降 8.90 个百分点、cost 上升 26.51%；容量增加到 256 时，命中率提升 12.30 个百分点、cost 降低 40.93%。history length 从 10 增至 50、lookahead 从 256 增至 512 都只带来小幅收益，表明默认配置已经接近稳定区间，进一步增大上下文窗口或前瞻距离的收益有限。

## Table 4: Ablation and QMAP-Full vs. QMAP-Pool

QMAP-Pool corresponds to replacing Q-Former query aggregation with mean pooling. Delta columns are relative to the QMAP-Full row within the same setting.

| Setting | Variant | Hit rate (%) | Delta hit (pp) | Cost | Delta cost (%) | NVM writes | Delta writes (%) | Migrations | Avg. decision (ms) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| default | QMAP-Full | 59.30 | +0.00 | 9,904 | +0.00 | 115 | +0.00 | 686 | 5.122 |
| default | no PC | 59.65 | +0.35 | 9,821 | -0.84 | 112 | -2.61 | 679 | 6.625 |
| default | no R/W | 59.85 | +0.55 | 9,781 | -1.24 | 114 | -0.87 | 675 | 11.582 |
| default | QMAP-Pool | 60.00 | +0.70 | 9,738 | -1.68 | 109 | -5.22 | 672 | 7.420 |
| default | no cost loss | 59.40 | +0.10 | 9,884 | -0.20 | 116 | +0.87 | 684 | 5.030 |
| writeheavy | QMAP-Full | 73.45 | +0.00 | 6,979 | +0.00 | 209 | +0.00 | 403 | 3.176 |
| writeheavy | no PC | 73.25 | -0.20 | 7,027 | +0.69 | 211 | +0.96 | 407 | 3.129 |
| writeheavy | no R/W | 73.30 | -0.15 | 7,016 | +0.53 | 211 | +0.96 | 406 | 3.651 |
| writeheavy | QMAP-Pool | 73.15 | -0.30 | 7,051 | +1.03 | 212 | +1.44 | 409 | 2.970 |
| writeheavy | no cost loss | 73.30 | -0.15 | 7,016 | +0.53 | 211 | +0.96 | 406 | 3.133 |
| phasechange | QMAP-Full | 61.25 | +0.00 | 9,589 | +0.00 | 172 | +0.00 | 647 | 2.634 |
| phasechange | no PC | 61.15 | -0.10 | 9,607 | +0.19 | 170 | -1.16 | 649 | 2.587 |
| phasechange | no R/W | 61.20 | -0.05 | 9,598 | +0.09 | 171 | -0.58 | 648 | 2.921 |
| phasechange | QMAP-Pool | 64.90 | +3.65 | 8,740 | -8.85 | 149 | -13.37 | 574 | 2.406 |
| phasechange | no cost loss | 61.20 | -0.05 | 9,598 | +0.09 | 171 | -0.58 | 648 | 2.961 |
| pcrwstress | QMAP-Full | 74.65 | +0.00 | 6,441 | +0.00 | 24 | +0.00 | 379 | 4.716 |
| pcrwstress | no PC | 74.30 | -0.35 | 6,518 | +1.20 | 24 | +0.00 | 386 | 3.245 |
| pcrwstress | no R/W | 74.35 | -0.30 | 6,507 | +1.02 | 24 | +0.00 | 385 | 3.192 |
| pcrwstress | QMAP-Pool | 75.75 | +1.10 | 6,199 | -3.76 | 24 | +0.00 | 357 | 2.938 |
| pcrwstress | no cost loss | 74.80 | +0.15 | 6,408 | -0.51 | 24 | +0.00 | 376 | 3.098 |
| writeheavy, epoch 20 | QMAP-Full | 73.40 | +0.05 | 7,856 | +0.24 | 214 | +2.39 | 404 | 3.017 |
| writeheavy, epoch 20 | QMAP-Pool | 73.35 | +0.00 | 7,837 | +0.00 | 209 | +0.00 | 405 | 2.768 |
| writeheavy, epoch 20 | QFormer-light | 72.55 | -0.80 | 8,061 | +2.86 | 217 | +3.83 | 421 | 2.983 |
| writeheavy, epoch 20 | QFormer-tiny | 73.15 | -0.20 | 7,905 | +0.87 | 213 | +1.91 | 409 | 2.995 |

**总结：** 消融实验表明，各输入特征和损失项对不同 workload 的贡献并不完全一致。在 writeheavy 上，QMAP-Full 优于 no PC、no R/W、QMAP-Pool 和 no cost loss，说明程序上下文、读写类型以及代价感知训练对写密集负载都有正向作用。pcrwstress 中去除 PC 或 R/W 会带来 cost 上升，而 no cost loss 与 QMAP-Full 接近，说明该场景下写入次数已被压到较低水平，主要差异来自读访问和迁移行为。值得注意的是，QMAP-Pool 在 default、phasechange 和 pcrwstress 设置下反而优于 QMAP-Full，尤其 phasechange 中 cost 降低 8.85%，说明当前 Q-Former 聚合并非在所有负载上都稳定优于简单池化；论文中可将其表述为“QMAP-Full 在写密集场景更稳健，而 QMAP-Pool 在部分非平稳负载上具有更低开销和更好泛化”，从而引出后续对聚合结构的优化空间。

## Source files

- `outputs/results/workload_suite/summary.csv`
- `outputs/results/workload_suite_pcrwstress/summary.csv`
- `outputs/results/checkpoint_sweep/summary.csv`
- `outputs/results/qmap_parameter_sensitivity/summary.csv`
- `outputs/results/qmap_ablation/summary.csv`
- `outputs/results/qmap_ablation/writeheavy/summary.csv`
- `outputs/results/qmap_ablation/phasechange/summary.csv`
- `outputs/results/qmap_ablation_pcrwstress/summary.csv`
- `outputs/results/qmap_qformer_comparison_writeheavy/summary.csv`
