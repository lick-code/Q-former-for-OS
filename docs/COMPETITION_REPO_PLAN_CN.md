# CAPD 比赛仓库文件选择与目录规划

本文根据以下材料整理：

- `2026年计算机系统能力大赛-章程.pdf`
- `2026年计算机系统能力大赛-技术方案.pdf`
- 最新论文 `HotStorage论文.pdf`
- 当前 `cache_replacement` 项目代码和实验结果

结论：比赛仓库应围绕 **CAPD 的可运行、可测试、可复现闭环** 组织，不应直接复制整个论文项目。

当前本地代码仍普遍使用 `qmap`、`QMAP-CrossAttn` 等历史名称。本文的文件筛选只依据
代码实际职责与最新 CAPD 论文主线，不以文件名判断是否保留。本阶段不修改文件名、
类名、命令行参数或 import；文中的比赛仓库建议位置是后续整理目标。

## 1. 比赛要求对仓库的直接约束

功能挑战赛提交内容必须覆盖：

1. 可执行的完整项目源代码。
2. 功能、性能和创新性测试结果，以及同类方法对比。
3. 设计方案、源码分析、问题与解决方法等开发文档。
4. 进展汇报幻灯片和演示视频。
5. 第三方代码来源、许可证和本队增量贡献说明。
6. AI 工具、模型、使用场景、产出和交互记录说明。
7. 真实、连续的开发提交记录。

重要日期：

- 初赛作品提交截止：2026 年 6 月 30 日。
- 初赛阶段要求不少于 8 次提交记录。
- 阶段性决赛作品提交截止：2026 年 8 月 12 日（暂定）。
- 决赛作品提交截止：2026 年 8 月 18 日（暂定）。
- 决赛阶段要求不少于 4 次提交记录。

## 2. CAPD 主线

最新论文中的 CAPD 主线是：

```text
PC / page address / R/W access records
-> multidimensional access embedding
-> one-layer Transformer encoder
-> DRAM LRU-tail candidate page construction
-> candidate-page cross-attention over encoded access history
-> MLP demotion score
-> replay-derived candidate ranking labels
-> listwise approximate-NDCG optimization
-> trace-replay comparison against baselines
```

论文主实验包括：

- 1M PARSEC-derived traces。
- blackscholes、streamcluster-pressure、dedup-pressure。
- LRU、Random、LFU、CLOCK、Kleio-lite、PatternS-lite 对比。
- DRAM capacity sensitivity。
- seed stability。
- cost-weight robustness。

旧 Q-Former、mean pooling、encoder-depth sweep、candidate-count sweep、
canneal tuning 和旧 QMAP 消融不属于最新论文主线。

## 3. 必须迁移的现有文件

### 3.1 CAPD 核心实现

| 当前文件 | 比赛仓库建议位置 | 用途 |
|---|---|---|
| `policy_learning/cache_model/embed.py` | `src/capd/embedding.py` | page address、PC、R/W 嵌入 |
| `policy_learning/cache_model/model.py` | `src/capd/model.py` | Transformer、candidate cross-attention、MLP scorer |
| `policy_learning/cache_model/loss.py` | `src/capd/legacy_ranking_loss.py` | 当前 `model.py` 的直接依赖，清理依赖前必须保留 |
| `policy_learning/cache_model/qmap_loss.py` | `src/capd/ranking_loss.py` | replay-derived listwise ranking loss |
| `policy_learning/cache_model/qmap_data.py` | `src/capd/dataset.py` | 数据集和 batch 组织 |
| `qmap/qmap_generator.py` | `src/capd/data_builder.py` | 候选页、状态特征和 replay 标签构造 |
| `qmap/qmap_train.py` | `src/capd/train.py` | CAPD 离线训练入口 |
| `qmap/qmap_eval.py` | `src/capd/evaluate.py` | DRAM/NVM replay 和基线评测 |
| `qmap/learned_baselines.py` | `src/capd/baselines.py` | Kleio-lite、PatternS-lite |
| `qmap/trace_builder.py` | `src/capd/synthetic_trace.py` | 无真实 trace 时生成演示数据 |

第一阶段按当前路径和文件名原样迁移并跑通测试。确认功能闭环后，再用独立提交完成
CAPD 对外命名、目录重排和 import 修正；不要在一次提交里同时搬迁、重命名和重构。

### 3.2 一键运行与论文实验

| 当前文件 | 比赛仓库建议位置 |
|---|---|
| `scripts/run_prototype_experiment.py` | `scripts/run_demo.py` |
| `scripts/run_real_pilot.py` | `scripts/run_real_pipeline.py` |
| `scripts/run_real_workload_suite.py` | `scripts/run_main_results.py` |
| `scripts/run_learned_baselines.py` | `scripts/run_learned_baselines.py` |
| `scripts/run_capacity_sensitivity.py` | `scripts/run_capacity_sensitivity.py` |
| `scripts/run_seed_stability.py` | `scripts/run_seed_stability.py` |
| `scripts/run_cost_weight_sensitivity.py` | `scripts/run_cost_weight_robustness.py` |
| `scripts/plot_capd_main_results.py` | `scripts/plot_main_results.py` |

### 3.3 Trace 采集与处理

| 当前文件 | 比赛仓库建议位置 |
|---|---|
| `scripts/collect_trace_drmemtrace.py` | `tools/trace/collect_drmemtrace.py` |
| `scripts/convert_drmemtrace_view.py` | `tools/trace/convert_drmemtrace.py` |
| `scripts/prepare_real_trace.py` | `tools/trace/prepare_trace.py` |
| `scripts/scan_pressure_windows.py` | `tools/trace/scan_pressure_windows.py` |
| `scripts/prepare_pressure_split.py` | `tools/trace/prepare_pressure_split.py` |
| `scripts/collect_parsec_1m_wsl.ps1` | `tools/trace/collect_parsec_wsl.ps1` |
| `tools/trace_collectors/dynamorio/README.md` | `tools/trace/README.md` |

这些文件证明真实 trace 如何采集、压力窗口如何仅依据 LRU 降级次数预先选择，属于可复现性的重要部分。

### 3.4 自动测试

| 当前文件 | 比赛仓库建议位置 |
|---|---|
| `qmap/qmap_integration_test.py` | `tests/test_pipeline_smoke.py` |
| `tests/test_qmap_cross_attention.py` | `tests/test_capd_cross_attention.py` |
| `tests/test_learned_baselines.py` | `tests/test_learned_baselines.py` |
| `tests/test_capacity_sensitivity.py` | `tests/test_capacity_sensitivity.py` |
| `tests/test_seed_stability.py` | `tests/test_seed_stability.py` |
| `tests/test_cost_weight_sensitivity.py` | `tests/test_cost_weight_robustness.py` |

## 4. 建议迁移的数据与结果

### 4.1 放入仓库

- `dataset/raw_traces/try.csv`：作为小型演示 trace，可改名为 `data/examples/capd_demo.csv`。
- `dataset/metadata/trace_schema.json`。
- `dataset/metadata/real_workload_suite_1m_manifest.json`。
- `dataset/metadata/real_workload_suite_pressure_manifest.json`。
- 以下结果目录中的 `summary.md`、`summary.csv` 和必要的 per-policy JSON：
  - `outputs/results/real_workload_suite/1m/`
  - `outputs/results/real_workload_suite_pressure/selected/`
  - `outputs/results/ml_baselines/`
  - `outputs/results/capacity_sensitivity/`
  - `outputs/results/seed_stability/`
  - `outputs/results/cost_weight_sensitivity/`
- `outputs/figures/capd_main_results.png`。
- `outputs/figures/capd_main_results.pdf`。

结果迁移到 `results/paper/` 后，应将结果中的 `QMAP-CrossAttn`、`qmap`
展示名称统一改为 `CAPD`，同时保留原始机器可读字段的兼容说明。

### 4.2 不直接放入仓库

- 2.6GB 的完整 `dataset/`。
- `dataset/jsonl/` 中约 1.7GB 的训练中间文件。
- 16.6GB 的 `outputs/checkpoints/`。
- 完整 1M raw/processed traces。
- 全部训练日志。

比赛仓库应提供采集、生成、切分和下载说明。若评委需要免训练演示，可只提供一个约
23MB 的 demo checkpoint，或放在 Release/对象存储中并记录 SHA-256，不要提交全部 epoch。

## 5. 不应迁移的文件

### 5.1 论文写作和临时材料

- `HotStorage论文.pdf`
- `1_1_tmp.pdf`
- `1_1_extract.txt`
- `current_pdf_extract_for_review.txt`
- `tmp_paper_extract.txt`
- `hotstorage26_overleaf_template/`
- `hotstorage26_overleaf_template.zip`
- `paper_rewriting_output/`
- `提交截图.png`
- `CHAT_HANDOFF.md`
- `tmp/`、`tmp_codex_test_dir/`、`_codex_write_probe/`

比赛需要独立的设计方案文档，不能用论文写作目录代替工程文档。

### 5.2 不属于最新 CAPD 主线的实验

- `scripts/run_qmap_qformer_comparison.py`
- `scripts/run_qmap_qformer_k_sweep.py`
- `scripts/run_qmap_encoder_depth_comparison.py`
- `scripts/run_qmap_ablation.py`
- `scripts/run_real_ablation.py`
- `scripts/run_candidate_sensitivity.py`
- `scripts/run_canneal_epoch_sweep.py`
- `scripts/run_canneal_tuned_eval.py`
- `scripts/run_qmap_checkpoint_sweep.py`
- `scripts/run_qmap_parameter_sensitivity.py`
- 与上述脚本对应的测试和结果目录
- `figures/qmap_cost_delta*`
- `figures/qmap_seed_stability*`
- `outputs/figures/overall_*`

这些内容可保留在论文研发仓库，但不要进入比赛仓库主分支。确需展示方法演进时，只在
`docs/development_history.md` 中概述，不复制全部历史实验。

### 5.3 第三方二进制

- `tools/extern/DynamoRIO-Windows-11.91.20581/`
- `tools/extern/DynamoRIO-Windows-11.91.20581.zip`

只保留安装说明、版本号、官方下载地址和调用脚本。

## 6. 推荐比赛仓库结构

```text
capd-oscomp/
├─ README.md
├─ LICENSE
├─ LICENSE-DOCS
├─ NOTICE
├─ AUTHORS
├─ CONTRIBUTORS.md
├─ THIRD_PARTY.md
├─ requirements.txt
├─ requirements-plot.txt
├─ pyproject.toml
├─ Dockerfile
├─ .gitignore
│
├─ src/
│  └─ capd/
│     ├─ __init__.py
│     ├─ embedding.py
│     ├─ model.py
│     ├─ ranking_loss.py
│     ├─ legacy_ranking_loss.py
│     ├─ dataset.py
│     ├─ data_builder.py
│     ├─ train.py
│     ├─ evaluate.py
│     ├─ baselines.py
│     └─ synthetic_trace.py
│
├─ scripts/
│  ├─ run_demo.py
│  ├─ run_real_pipeline.py
│  ├─ run_main_results.py
│  ├─ run_learned_baselines.py
│  ├─ run_capacity_sensitivity.py
│  ├─ run_seed_stability.py
│  ├─ run_cost_weight_robustness.py
│  └─ plot_main_results.py
│
├─ tools/
│  └─ trace/
│     ├─ README.md
│     ├─ collect_drmemtrace.py
│     ├─ convert_drmemtrace.py
│     ├─ prepare_trace.py
│     ├─ scan_pressure_windows.py
│     ├─ prepare_pressure_split.py
│     └─ collect_parsec_wsl.ps1
│
├─ configs/
│  ├─ demo.yaml
│  ├─ paper_main.yaml
│  ├─ capacity.yaml
│  ├─ seed_stability.yaml
│  └─ cost_weight.yaml
│
├─ data/
│  ├─ README.md
│  ├─ examples/
│  │  └─ capd_demo.csv
│  └─ metadata/
│     ├─ trace_schema.json
│     ├─ main_1m_manifest.json
│     └─ pressure_window_manifest.json
│
├─ tests/
│  ├─ test_pipeline_smoke.py
│  ├─ test_capd_cross_attention.py
│  ├─ test_learned_baselines.py
│  ├─ test_capacity_sensitivity.py
│  ├─ test_seed_stability.py
│  └─ test_cost_weight_robustness.py
│
├─ results/
│  └─ paper/
│     ├─ main/
│     ├─ pressure/
│     ├─ learned_baselines/
│     ├─ capacity/
│     ├─ seed_stability/
│     ├─ cost_weight/
│     └─ figures/
│
├─ docs/
│  ├─ design.md
│  ├─ architecture.md
│  ├─ source_analysis.md
│  ├─ experiments.md
│  ├─ reproduction.md
│  ├─ development_history.md
│  ├─ problems_and_solutions.md
│  ├─ contribution_vs_parrot.md
│  ├─ ai_usage.md
│  └─ ai_interactions/
│
├─ presentation/
│  ├─ progress_report.pdf
│  └─ final_defense.pdf
│
└─ demo/
   ├─ README.md
   ├─ demo_script.md
   └─ video_link.md
```

## 7. 必须新建或重写的文件

当前项目缺少或不适合直接复用的比赛文件：

1. `README.md`：重写为 CAPD 项目首页，控制在可快速阅读的长度。
2. `LICENSE`：源代码选择比赛允许的 Apache-2.0 等协议，并补齐许可证正文。
3. `LICENSE-DOCS`：设计文档、PPT、视频使用 CC-BY-SA 4.0。
4. `NOTICE` 和 `THIRD_PARTY.md`：说明 PARROT、DynamoRIO、PARSEC 等来源和用途。
5. `CONTRIBUTORS.md`：列出本队成员及贡献。
6. `docs/contribution_vs_parrot.md`：说明基础版本、沿用部分和 CAPD 增量贡献。
7. `docs/ai_usage.md`：披露 Codex/ChatGPT 等工具、模型、用途和人工审核方式。
8. `requirements.txt`：只保留 CAPD 运行所需依赖，不能继续使用当前旧 PARROT 的大依赖清单。
9. `Dockerfile`：固定 Python、PyTorch 和运行命令。
10. `configs/*.yaml`：把论文参数从脚本常量中抽出，避免多个脚本口径不一致。

## 8. 开源与归属风险

当前 `AUTHORS` 只列出了原 PARROT/Google 作者，不能作为比赛仓库的唯一作者文件。

部分文件仍写有：

```text
Copyright 2026 The Google Research Authors.
Licensed under the Apache License, Version 2.0
```

迁移前必须逐文件核对：

- 原 PARROT 代码保留原版权和 Apache 2.0 声明。
- 本队修改的文件增加修改说明和本队版权信息。
- 完全由本队新增的 CAPD 文件不要错误声明为 Google 原作。
- 根目录补齐 Apache 2.0 许可证正文。
- `THIRD_PARTY.md` 写明上游项目、URL、提交版本、许可证、采用文件和修改内容。

不要删除原作者归属来“简化”仓库，这会同时违反开源协议和比赛披露要求。

## 9. 提交历史建议

不要把筛选后的文件一次性复制成一个大提交。优先从当前仓库做保留历史的路径过滤，
然后按真实工作分阶段提交：

1. 导入 CAPD 核心代码和上游归属。
2. 增加最小 demo pipeline。
3. 增加自动测试。
4. 统一 QMAP 到 CAPD 的对外命名。
5. 增加真实 trace 工具和数据说明。
6. 增加主实验与基线结果。
7. 增加设计方案、源码分析和问题记录。
8. 增加 AI 使用说明、PPT 和视频材料。

截至 2026 年 6 月 14 日，距离 2026 年 6 月 30 日初赛截止还有 16 天。
应保留当前仓库已有真实历史，并完成不少于 8 次有明确说明的增量提交；不要伪造或回填日期。

## 10. 最小可执行验收标准

比赛仓库至少应支持：

```text
1. 安装依赖或构建 Docker 镜像。
2. 运行单元测试和 pipeline smoke test。
3. 生成小型 demo trace。
4. 从 trace 生成 replay ranking 样本。
5. 训练一个小型 CAPD 模型。
6. 对 LRU / Random / LFU / CLOCK / CAPD 做 replay。
7. 输出 summary.csv、summary.md 和主结果图。
```

评委在没有完整 1M traces 和全部 checkpoints 的情况下，也应能验证 CAPD 的完整功能链路。
