# Codex 账号迁移交接文件

生成时间：2026-05-15  
项目路径：`D:\计算机系统大赛\功能赛道\cache_replacement`  
当前分支：`main`  
当前最新提交：`2a67af5 del`  
当前工作区状态：`git status --short` 为空，说明当前没有未提交改动。

## 换号后怎么接着做

聊天记录本身通常绑定当前账号，不能保证原样迁移到新账号。这个文件用于把关键上下文落到项目目录里。换号后，在 Codex 里打开同一个项目目录，然后把下面这段发给新会话：

```text
请先阅读项目根目录下的 CHAT_HANDOFF.md 和 README.md，然后接着处理这个 QMAP cache replacement 项目。

当前目标：继续完善面向 DRAM/NVM 混合内存的 QMAP 页面迁移原型、实验结果和论文材料。请先检查 git status，不要覆盖已有文件，不要删除 outputs/checkpoints、outputs/results、dataset 下的实验产物。

如果我要你继续实验或写论文，请优先参考 CHAT_HANDOFF.md 中的“推荐下一步”和 README.md 中的实验结论。
```

## 项目一句话说明

这是一个面向 DRAM/NVM 混合内存系统的页面迁移策略原型，名字叫 QMAP。项目把页面迁移建模为候选页面排序问题：DRAM 满且发生 miss 时，从候选页面里选出更适合从 DRAM 降级到 NVM 的页面。

目前完整 pipeline 已跑通：

```text
trace -> JSONL -> training -> replay evaluation -> summary
```

## 当前关键结论

- QMAP 在 writeheavy workload 上表现最好：hit rate 最高、NVM writes 最少、weighted access cost 最低。
- QMAP 不是所有 workload 都优于 LFU。hotset、phasechange、pcrwstress 上 LFU 仍然很强。
- 当前最诚实的论文叙事是：QMAP 在写密集场景下能降低 NVM writes 和 weighted access cost，但在稳定热点或 LFU 友好 workload 上优势有限。
- Q-Former 不建议写成当前最强贡献点。现有实验显示 mean pooling / QMAP-Pool 在 phasechange 和 pcrwstress 上更稳。
- 如果后续只能保留一个最终实现，更推荐继续打磨 QMAP-Pool，也就是 Transformer encoder + mean pooling。

## 已完成实验与结果位置

重点结果都已经在 `outputs/results/` 下：

- 原型主实验：`outputs/results/try_prototype/summary.md`
- Checkpoint sweep：`outputs/results/checkpoint_sweep/summary.md`
- 多 workload：`outputs/results/workload_suite/summary.md`
- pcrwstress workload：`outputs/results/workload_suite_pcrwstress/summary.md`
- 参数敏感性：`outputs/results/qmap_parameter_sensitivity/summary.md`
- try trace 消融：`outputs/results/qmap_ablation/summary.md`
- writeheavy 消融：`outputs/results/qmap_ablation/writeheavy/summary.md`
- phasechange 消融：`outputs/results/qmap_ablation/phasechange/summary.md`
- pcrwstress 消融：`outputs/results/qmap_ablation_pcrwstress/summary.md`
- cost-aware 权重实验：`outputs/results/qmap_cost_w8_m4_writeheavy/summary.md`
- Q-Former 对照：`outputs/results/qmap_qformer_comparison_writeheavy/summary.md`
- Q-Former K sweep：`outputs/results/qmap_qformer_k_sweep_writeheavy/summary.md`
- Encoder 层数对照：`outputs/results/qmap_encoder_depth_comparison_writeheavy/summary.md`
- 汇总表：`outputs/results/final_tables.md`

## 重要目录

```text
qmap/
  trace_builder.py              synthetic trace 构造
  qmap_generator.py             从 CSV trace 生成 QMAP JSONL 样本
  qmap_train.py                 训练 QMAP checkpoint
  qmap_eval.py                  replay 评估 LRU / Random / LFU / CLOCK / QMAP
  qmap_integration_test.py      模型和 loss 的 smoke test

policy_learning/cache_model/
  embed.py                      QMAP embedding
  model.py                      Transformer、Q-Former、mean pooling、候选页 scorer
  qmap_loss.py                  cost-aware ranking loss
  qmap_data.py                  JSONL dataset 和 collate 逻辑

scripts/
  run_prototype_experiment.py          单 workload 原型实验
  run_qmap_checkpoint_sweep.py         checkpoint sweep
  build_workload_suite.py              生成多 workload trace
  run_workload_suite.py                多 workload 训练和评估
  run_qmap_parameter_sensitivity.py    参数敏感性实验
  run_qmap_ablation.py                 消融实验
  run_qmap_qformer_comparison.py       Q-Former / mean_pool 对照实验
  run_qmap_qformer_k_sweep.py          Q-Former query 数 K 的 sweep
  run_qmap_encoder_depth_comparison.py mean_pool 下 encoder 层数对照

dataset/
  raw_traces/                   原始 synthetic traces
  processed/                    train / valid / test CSV traces
  jsonl/                        QMAP 训练样本
  metadata/                     trace schema、split 和 workload manifest

outputs/
  checkpoints/                  已训练模型 checkpoint
  results/                      JSON / CSV / Markdown 实验结果

docs/
  QMAP_README.md
  QMAP_README_CN.md
  QMAP_TRAINING_GUIDE.md
  QMAP_GAPS_ROADMAP.md

hotstorage26_overleaf_template/
  main.tex
  references.bib
  figures/
```

## 常用查看命令

```powershell
git status --short
git branch --show-current
Get-Content README.md
Get-Content outputs/results/final_tables.md
Get-Content outputs/results/workload_suite/summary.md
Get-Content outputs/results/qmap_ablation/writeheavy/summary.md
```

如果在 Linux / WSL / 服务器上：

```bash
cat README.md
cat outputs/results/final_tables.md
cat outputs/results/workload_suite/summary.md
cat outputs/results/qmap_ablation/writeheavy/summary.md
```

## 常用实验命令模板

README.md 里已经保留了完整命令。下面是最常用的几个入口。

writeheavy 消融：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --variants full,no_pc,no_rw,mean_pool,no_cost \
  --result_dir outputs/results/qmap_ablation/writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_ablation/writeheavy \
  --jsonl_root dataset/jsonl/qmap_ablation/writeheavy \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 10 \
  --batch_size 32 \
  --device cuda
```

Q-Former / mean_pool 对照：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_qformer_comparison.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --result_dir outputs/results/qmap_qformer_comparison_writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_qformer_comparison_writeheavy \
  --jsonl_root dataset/jsonl/qmap_qformer_comparison_writeheavy \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 20 \
  --batch_size 32 \
  --device cuda
```

Q-Former K sweep：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_qformer_k_sweep.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --k_values 1,2,3,4,5,6,8 \
  --result_dir outputs/results/qmap_qformer_k_sweep_writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_qformer_k_sweep_writeheavy \
  --jsonl_path dataset/jsonl/qmap_qformer_k_sweep_writeheavy/train.jsonl \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 20 \
  --batch_size 32 \
  --device cuda
```

Encoder 层数对照：

```bash
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_encoder_depth_comparison.py \
  --train_trace dataset/processed/writeheavy_train.csv \
  --test_trace dataset/processed/writeheavy_test.csv \
  --layers 1,2,3 \
  --result_dir outputs/results/qmap_encoder_depth_comparison_writeheavy \
  --checkpoint_root outputs/checkpoints/qmap_encoder_depth_comparison_writeheavy \
  --jsonl_root dataset/jsonl/qmap_encoder_depth_comparison_writeheavy \
  --page_shift 12 \
  --dram_capacity 128 \
  --history_length 10 \
  --candidate_count 64 \
  --lookahead 256 \
  --epochs 20 \
  --batch_size 32 \
  --write_sensitivity_weight 4 \
  --migration_cost_weight 2 \
  --nvm_write_cost 8 \
  --device cuda
```

## 推荐下一步

1. 先不要盲目加新模块。更现实的下一步是“收敛版本 + 增强可信度”。
2. 明确命名：
   - `QMAP-Full`：原始 Q-Former 版本。
   - `QMAP-Pool`：Transformer encoder + mean pooling 版本。
3. 建议对以下实验做至少 3 个 seed 的重复实验：
   - `qmap_ablation/writeheavy`
   - `qmap_ablation/phasechange`
   - `qmap_ablation_pcrwstress`
   - `qmap_qformer_comparison_writeheavy`
   - `qmap_qformer_k_sweep_writeheavy`
4. 建议 seed：
   - `3136859`
   - `42`
   - `2026`
5. 暂时不建议继续投入太多时间强化 cost-aware，因为当前收益很小：full 只比 no_cost 少 1 次 NVM write，cost 低 6。
6. 论文最终建议保留 4 张表：
   - Table 1: QMAP vs LRU/Random/LFU/CLOCK across workloads
   - Table 2: checkpoint sweep
   - Table 3: parameter sensitivity
   - Table 4: ablation, QMAP-Full vs QMAP-Pool, and Q-Former K sensitivity

## 需要保护的文件和目录

不要删除这些关键产物：

```text
outputs/results/
outputs/checkpoints/
dataset/processed/
dataset/raw_traces/
dataset/jsonl/
dataset/metadata/
hotstorage26_overleaf_template/
hotstorage26_overleaf_template.zip
```

尤其不要删除这些 checkpoint：

```text
outputs/checkpoints/try_prototype/qmap_epoch_10.pth
outputs/checkpoints/workload_suite/*/qmap_epoch_10.pth
outputs/checkpoints/workload_suite_pcrwstress/*/qmap_epoch_10.pth
outputs/checkpoints/qmap_ablation/**/qmap_epoch_10.pth
outputs/checkpoints/qmap_qformer_comparison_writeheavy/**/qmap_epoch_20.pth
outputs/checkpoints/qmap_qformer_k_sweep_writeheavy/k*/qmap_epoch_20.pth
outputs/checkpoints/qmap_encoder_depth_comparison_writeheavy/layers_*/qmap_epoch_20.pth
```

## 环境注意事项

- `requirements.txt` 里有一批较老依赖，比如 TensorFlow 2.1.0、torch 1.13.1 等。换机器或换 Python 版本时可能不能直接安装成功。
- 当前目录里出现过 Python 3.13 的 `__pycache__`，但依赖未必完全适配 3.13。跑实验前先做小规模 smoke test。
- 如果在服务器上跑较长实验，建议使用 `tmux`：

```bash
tmux new -s qmap
CUDA_VISIBLE_DEVICES=2 python scripts/run_qmap_ablation.py ...
```

断开：

```text
Ctrl-b 然后按 d
```

重新进入：

```bash
tmux attach -t qmap
```

## 给新 Codex 的工作约束

- 先读 `CHAT_HANDOFF.md`、`README.md` 和相关 summary 文件，再改代码。
- 开始前必须看 `git status --short`。
- 不要覆盖用户已有改动。
- 不要删除数据集、checkpoint、实验输出和论文模板。
- 如果继续实验，优先复现实验，再考虑改模型。
- 如果继续写论文，使用谨慎表述：强调 writeheavy 上有效，不要夸大 Q-Former 或 cost-aware 的贡献。
