# CAPD NoVPN 消融实现报告

## Material Passport

- ID：`capd-no-vpn-ablation-implementation-20260728`
- 类型：代码消融实现、服务器实验准备与本地验证
- 状态：`VERIFIED_LOCALLY`；完整 3 workload × 3 seed 训练尚未运行
- 正式方法基准：`configs/finals/capd_direction1_v3.json`
- 正式数据基准：`dataset/jsonl/finals_v3_official/<workload>/B64/`
- 主要变量：`model.use_page_id_embedding`
- 数据/trace 状态：未修改、未重新生成

## 1. 实现结论

CAPD-NoVPN 已实现为严格模型输入消融：

- `use_page_id_embedding` 缺省为 `true`，旧配置行为保持不变。
- `false` 时，历史 page embedding 和候选 page embedding 都变为相同形状的全零张量。
- PC、R/W、frequency、dirty、residency、归一化 LRU-tail rank、Transformer、candidate-to-history cross-attention、训练标签、候选生成与 replay 全部保留。
- embedding 参数、模型维度和 state-dict 键保持不变，full/NoVPN checkpoint 结构兼容。
- 正式 JSONL、selector、trace、future labels、代价权重和既有结果均未修改。

## 2. 正式配置与实验依据

采用 Direction-1 v3、B64 作为正式基准，依据如下：

- 正式方法配置为 `configs/finals/capd_direction1_v3.json`，schema 为 `capd_finals_v3_0`，profile 为 `official`。
- 三个 workload 的 sealed resolved config、selector 和训练/验证 JSONL 均位于 `dataset/jsonl/finals_v3_official/<workload>/B64/`。
- B64 配置固定 `D=64, B=64, K=8, H=10, Hc=256, L=256, Lres=256`。
- 正式训练参数为 10 epochs、batch size 32、learning rate `1e-4`；训练器仍使用原有 AdamW。
- `configs/seed_stability.yaml` 中现有训练种子集合为 `3136859, 42, 2026`，因此本消融按同一三种子集合运行。

NoVPN 没有改变 early stopping：正式路径当前没有单独 early-stopping 参数，仍以每个 epoch 的验证损失选择 `qmap_best.pth`。

## 3. 修改文件与目的

| 文件 | 目的 |
|---|---|
| `policy_learning/cache_model/embed.py` | 在历史访问 page embedding 和共享候选 page embedding 入口实现全零门控；缺省开启 page ID。 |
| `policy_learning/cache_model/model.py` | 候选 scorer 增加防御性 NoVPN 门控，覆盖共享、非共享和外部 embedding 路径。 |
| `qmap/finals_config.py` | 验证布尔配置、提供向后兼容读取函数，并支持 selector 使用 sealed data config、结果使用 variant config 的双契约校验。 |
| `qmap/no_vpn_ablation.py` | 定义唯一允许差异、校验正式 Full 克隆关系、校验 sealed 数据复用关系、生成 variant resolved config。 |
| `qmap/qmap_train.py` | 将开关传入训练模型；数据工件仍按原正式 config 校验；checkpoint 按 variant config 记录；增加可恢复训练。 |
| `qmap/qmap_eval.py` | 按 checkpoint/config 恢复开关；selector 按 sealed data config 校验；checkpoint/result 按 variant config 校验。 |
| `configs/finals/capd_direction1_v3_ablation_full.json` | 隔离输出的配对 Full CAPD 配置。 |
| `configs/finals/capd_direction1_v3_no_vpn.json` | 与 Full 仅在允许字段不同的 CAPD-NoVPN 配置。 |
| `scripts/check_no_vpn_config_diff.py` | 自动检查正式配置→Full、正式配置→NoVPN、Full→NoVPN 的差异白名单。 |
| `scripts/run_no_vpn_ablation.py` | 统一运行 full/no_vpn/both、三 workload、三 seed；支持 CUDA、resume、skip-existing、独立日志和结果。 |
| `scripts/summarize_no_vpn_ablation.py` | 生成 per-seed CSV、统计 CSV/JSON 和带解释框架的 Markdown 报告。 |
| `tests/test_no_vpn_ablation.py` | 覆盖默认兼容、身份不变、page 梯度、Full 路径、配置差异、CPU/GPU、resume、汇总与训练/加载/replay smoke。 |

## 4. 原 page identity 前向路径

实际神经网络前向中发现两条绝对 page identity 路径：

1. 历史路径：`history_page_ids -> DynamicVocabEmbedder -> history page embedding -> 与 PC/RW embedding 拼接 -> Transformer`。
2. 候选路径：`candidate_pages -> 同一个共享 DynamicVocabEmbedder -> candidate page embedding -> 与四维 candidate state 拼接 -> candidate projector -> candidate-to-history cross-attention -> scoring MLP`。

没有发现以下额外模型侧通道：

- raw page ID 数值直接拼接；
- page ID hash、one-hot 或独立 lookup；
- candidate/history page equality mask；
- 由绝对 VPN 数值计算并送入网络的连续特征。

Replay 中仍使用 page ID 维护 frequency、dirty、residency、LRU、resident set、候选生成和评价指标。这些属于明确允许保留的系统状态，不是绝对 page embedding。

## 5. NoVPN 如何保证两处 embedding 失效

`QMAPAccessFeatureEmbedder` 在 `use_page_id_embedding=false` 时：

```text
history_page_embedding = zeros_like(original_history_page_embedding)
candidate_page_embedding = zeros_like(original_candidate_page_embedding)
```

候选 scorer 还会再次对候选 embedding 做全零门控，防止未来改成非共享 embedding 或外部 embedding 后重新暴露 page identity。

由于 `zeros_like` 结果不连接 embedding 权重，page embedding 对 loss 的梯度为 `None` 或全零；PC/RW embedding 梯度仍存在。拼接维度仍为 18，候选输入维度、Transformer、attention head、FFN 和 scorer 结构均未改变。

## 6. Sealed 数据复用与配置身份

正式 JSONL/selector 已绑定原 resolved config 指纹，不能改文件或重新生成。实现采用双身份校验：

- 数据身份：继续使用 `dataset/jsonl/finals_v3_official/<workload>/B64/resolved_config.json` 校验 selector、JSONL、manifest 和 split fingerprints。
- 实验身份：Full/NoVPN resolved config 只覆盖 experiment name、page-ID 开关和隔离输出路径；checkpoint/result 记录各自独立 config hash。
- `qmap/no_vpn_ablation.py` 在训练前证明实验 config 是 sealed data config 的 model/output-only 派生物，否则硬失败。

这避免了放松 trace、标签、候选池或 replay 契约，也不需要修改正式数据工件。

## 7. 配置差异

自动检查确认 Full 与 NoVPN 只有以下五处叶子字段不同：

1. `experiment_name`
2. `model.use_page_id_embedding`
3. `outputs.checkpoint_root`
4. `outputs.result_root`
5. `outputs.log_root`

两份配置分别与正式 `capd_direction1_v3.json` 比较时，也只有同一白名单字段发生新增或变化。其余数据路径、split、D/B/K/H/Hc/L/Lres、embedding 维度、Transformer、loss、optimizer 路径、learning rate、epochs、batch size、seeds、代价模型、replay 和 baseline 语义不变。

## 8. 本地测试结果

### 新增测试

- CPU：10 个测试运行，9 通过，1 个 CUDA-only 测试按预期跳过。
- GPU：10/10 通过，PyTorch 2.9.0+cu130。
- Full 与 NoVPN smoke 均完成：加载最小 JSONL、一次 forward/backward、保存 checkpoint、加载 checkpoint、24 次访问的 replay。
- NoVPN 两组完全不同 page IDs 的 score 最大绝对差小于 `1e-6`。
- NoVPN page embedding 梯度为 `None` 或全零；PC/RW 梯度存在。
- resume 状态、汇总 delta 方向与 sample standard deviation 路径通过。

### 既有相邻回归测试

以下测试合计 17/17 通过：

- `tests.test_capd_stage1_v3_model`
- `tests.test_capd_cross_attention`
- `tests.test_checkpoint_config_contract`

### 其他检查

- `scripts/check_no_vpn_config_diff.py`：通过。
- launcher `--prepare-only`：三个 workload 的 Full/NoVPN resolved config 生成与严格差异检查通过。
- launcher 单组合 `--dry-run`：训练与 test replay 命令生成通过。
- 10 个改动 Python 文件 AST 语法检查：通过。

本地未运行正式三 workload × 三 seed 长训练，符合服务器执行范围。

## 9. 服务器完整运行命令

从仓库根目录执行：

```bash
python scripts/check_no_vpn_config_diff.py

python scripts/run_no_vpn_ablation.py \
  --variant both \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --seeds 3136859 42 2026 \
  --device cuda \
  --resume \
  --skip-existing
```

行为说明：

- `--variant both` 在同一代码 revision 下重新运行 Full 和 NoVPN。
- `--resume`：若存在未完成的 `qmap_last.pth`，从下一 epoch 恢复；若训练 manifest 已完成则直接进入评估。
- `--skip-existing`：只跳过 variant/workload/seed/config metadata 完整匹配的有效结果。
- 任一训练或评估子进程失败时，launcher 返回非零状态。
- 不调用 generator，不修改或重生成 JSONL/trace。

如需分别运行：

```bash
python scripts/run_no_vpn_ablation.py \
  --variant full \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --seeds 3136859 42 2026 \
  --device cuda --resume --skip-existing

python scripts/run_no_vpn_ablation.py \
  --variant no_vpn \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --seeds 3136859 42 2026 \
  --device cuda --resume --skip-existing
```

## 10. 结果汇总命令

完整训练和 test replay 结束后执行：

```bash
python scripts/summarize_no_vpn_ablation.py \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --seeds 3136859 42 2026
```

delta 定义统一为：

```text
absolute_delta = no_vpn - full
relative_delta_percent = (no_vpn - full) / full * 100
```

weighted cost 正 delta 表示 NoVPN 更差；hit rate 正 delta 表示 NoVPN hit rate 更高。统计量为 mean、sample standard deviation（ddof=1）、min、max。

## 11. 预期输出

Checkpoint：

```text
outputs/checkpoints/ablation_no_vpn/full/<workload>/seed_<seed>/
outputs/checkpoints/ablation_no_vpn/no_vpn/<workload>/seed_<seed>/
```

逐次结果：

```text
outputs/results/ablation_no_vpn/full/<workload>/seed_<seed>/qmap.json
outputs/results/ablation_no_vpn/no_vpn/<workload>/seed_<seed>/qmap.json
```

日志与 resolved config：

```text
outputs/logs/ablation_no_vpn/full/
outputs/logs/ablation_no_vpn/no_vpn/
```

汇总：

```text
outputs/results/ablation_no_vpn/no_vpn_ablation_per_seed.csv
outputs/results/ablation_no_vpn/no_vpn_ablation_summary.csv
outputs/results/ablation_no_vpn/no_vpn_ablation_summary.json
outputs/results/ablation_no_vpn/no_vpn_ablation_report.md
```

每个 `qmap.json` 会附加 variant、workload、seed、config path/hash、sealed data config/hash、data manifest/hash、checkpoint path/hash、当前 git commit/dirty 状态、best epoch、validation metric、training time 和 test metrics。

评估器原字段 `migrations` 在汇总中同时记作 `demotions`；没有伪造新的计时指标，使用现有 `decision_time_seconds` 和 `avg_decision_time_ms`。

## 12. 当前限制

- 正式训练和 test replay 尚未运行，因此当前没有 Full/NoVPN 性能结论。
- 结果解释模板只给出方向框架，不包含固定百分比阈值，也不会在没有 test replay 数据时提前下结论。
- `--resume` 在 epoch 边界恢复模型、optimizer、最佳验证状态、loss curve 和随机数状态；已完成 epoch 内的 batch 不做中点恢复。
- 服务器必须使用支持目标 GPU 架构的 PyTorch/CUDA 构建；本地 GPU 验证使用了 PyTorch 2.9.0+cu130。
