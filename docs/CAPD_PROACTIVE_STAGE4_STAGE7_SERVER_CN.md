# CAPD 主动降级 Stage 4（Stage 7 / R4）服务器流程

## 1. 状态与证据边界

本入口是 `stage4-stage7-unified-r1`，输出根为
`outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r1`。它不覆盖、
不读取也不比较 `outputs/capd_proactive_stage4/` 下的历史 Stage 4 结果。

Stage 3 的唯一权威是：

- `outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json`
  (`02904916ad26273e1c01cda540bbae121e2f0a0e3b6914cfa6e2904068e7f0c1`)
- 同目录 `pressure_generation_contract.json`
  (`1c4582c20098425f9e8a155e832aad737e35160e8d254808a09706ca45394761`)
- 同目录 `run_state.json`
  (`71da1d6386d7f1f7e62ef4965d3d41abc7c5b775350760cb249dabbece8a0f63`)

入口同时要求 `formal_freeze=true`、`stage4_entry_allowed=true`，且
`run_state.status=derived_selection_formally_frozen`。旧 `verification.json`
不是入口证据，不会被读取。

数据唯一登记表为
`outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/input_manifest.json`
(`108b2c34b5809e911b8b92864b111fc117caea8566997c101607928c590ed85f`)。
必须恰好包含六个 Train、六个 Validation，不得包含 Test 或 Pressure 派生输入。

## 2. 冻结参数

| workload | D | F_low | F_target |
|---|---:|---:|---:|
| canneal | 120 | 6 | 16 |
| streamcluster_pressure | 22 | 1 | 3 |
| dedup_pressure | 21 | 1 | 3 |
| blackscholes | 8 | 1 | 2 |
| swaptions | 8 | 1 | 2 |
| fluidanimate | 22 | 1 | 3 |

共同冻结值为 `K=8`、`b_max=2`、500000-record 窗口、每窗口空 DRAM
初态、`capacity_ratio=0.10`、`alpha=0.15`、`beta=0.40`。回放成本直接取
R4：DRAM hit 1、NVM read 2、NVM write 8、demotion 10。Stage 4 不重新计算
容量，不搜索 K、水位、D 或其他 Stage 3 参数。

## 3. 本轮搜索合同草案（尚未确认）

搜索配置是
`configs/finals/capd_proactive_stage4_stage7_search.json`，状态为
`draft_awaiting_human_confirmation`。搜索按固定顺序进行：

1. semantic：7 个候选，搜索 L、H、lambda；
2. architecture：继承 semantic 胜者，4 个候选；
3. optimization：继承 architecture 胜者，4 个候选。

共 15 个候选配置。每个候选训练 3136859、42、2026 三个 seed，共 45 次
GPU 训练。每个 seed 独立按最小 Validation loss 选择 checkpoint；相同 loss
取更早 epoch。不得选择“最佳 seed”，三个 seed 的 checkpoint 全部保留。

主指标是先对六个 workload 等权宏平均 Validation weighted cost/access，再对
三个 seed 等权平均。候选 tie-break 依次为：较小的最差 workload 成本、较高
macro NDCG@b_t、较小 mean best Validation loss、较小模型复杂度、candidate ID
字典序。任一 seed/workload 缺失、无有效决策、训练非零退出或出现 NaN/Inf，
整候选失败，搜索空间不得临时修改。

这只是可执行草案，并非正式冻结合同。运行完整真实搜索前必须人工确认。

## 4. 数据、词表和统一模型

样本按 workload、split、500000-record 窗口独立回放；每个窗口从空 DRAM
开始，history/future 不跨 workload、split 或窗口。缓存身份包含 L/H/lambda、
R4 SHA、R2 SHA、输入 manifest SHA、K 和 b_max；模型结构、学习率、batch、
epoch 或 seed 改变时复用同一语义样本，L/H/lambda 改变时不复用。

page/PC 词表按固定 workload 顺序只扫描六个 Train，保留 UNK=0 并冻结；之后
才统计六个 Validation 的 page/PC OOV。Validation、Test、Pressure 都不能参与
fit。词表 SHA 写入样本 manifest、训练合同和 checkpoint；所有 seed 使用同一
语义数据集的同一词表，resume 必须保持词表和样本 SHA 不变。

最终模型是六个 workload 合并 Train 上的统一 CAPD；六个 Validation 分别保存
回放结果再做宏平均。不存在 per-workload 最终模型或 per-workload 超参。

## 5. 上传后环境与只读检查

以下命令可在人工确认搜索合同之前执行：

```bash
cd ~/Q-former-for-OS
conda activate capd
git status --short
git rev-parse HEAD
nvidia-smi
python3 - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_devices", torch.cuda.device_count())
if torch.cuda.is_available():
    print("device0", torch.cuda.get_device_name(0))
PY
sha256sum \
  outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json \
  outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/pressure_generation_contract.json \
  outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/run_state.json \
  outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/input_manifest.json
```

## 6. 编译、单元测试和 synthetic e2e

```bash
cd ~/Q-former-for-OS
conda activate capd
python3 -m py_compile \
  qmap/proactive_stage4_stage7.py \
  scripts/prepare_capd_proactive_stage4_stage7_manifest.py \
  scripts/run_capd_proactive_stage4_stage7.py

python3 -m unittest \
  tests.test_capd_proactive_stage4_stage7 \
  tests.test_capd_proactive_stage4_stage7_e2e \
  tests.test_capd_proactive_stage4 \
  tests.test_capd_proactive_stage4_e2e \
  -v
```

共享训练器 `qmap/qmap_train.py` 有向后兼容修改，所以旧 Stage 4 两组回归测试
必须同时通过。也可在 manifest 生成后运行集成验证脚本：

```bash
bash scripts/validate_capd_proactive_stage4_stage7_server.sh "$PWD"
```

## 7. 生成严格 manifest 与 preflight

```bash
cd ~/Q-former-for-OS
conda activate capd
RUN_ID=stage4-stage7-unified-r1

python3 scripts/prepare_capd_proactive_stage4_stage7_manifest.py \
  --source-manifest outputs/capd_proactive_stage3/stage3-stage7-calibration-r2/input_manifest.json \
  --stage3-freeze outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json \
  --output outputs/capd_proactive_stage4_stage7/${RUN_ID}/input_manifest.json \
  --project-root "$PWD"

python3 scripts/run_capd_proactive_stage4_stage7.py preflight \
  --config configs/finals/capd_proactive_stage4_stage7_search.json \
  --stage3-freeze outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json \
  --input-manifest outputs/capd_proactive_stage4_stage7/${RUN_ID}/input_manifest.json \
  --run-id "$RUN_ID" \
  --project-root "$PWD" \
  --device cuda --require-cuda \
  --train-workers 4 --sample-workers 6 --replay-workers 6
```

preflight 只读校验输入并写证据，不生成正式候选，不训练，不 freeze。CUDA 不可用
或可见 GPU 不是恰好一张时立即失败，不会退回 CPU。

## 8. 可选：确认前生成语义样本缓存

```bash
python3 scripts/run_capd_proactive_stage4_stage7.py samples \
  --config configs/finals/capd_proactive_stage4_stage7_search.json \
  --stage3-freeze outputs/capd_proactive_stage3/stage3-stage7-unified-contract-r4/final_freeze.json \
  --input-manifest outputs/capd_proactive_stage4_stage7/${RUN_ID}/input_manifest.json \
  --run-id "$RUN_ID" --project-root "$PWD" \
  --device cuda --require-cuda \
  --train-workers 4 --sample-workers 6 --replay-workers 6
```

这一步只为 semantic 阶段的七种 L/H/lambda 生成样本和 Train-only 词表，按
workload 使用多进程临时文件后按固定顺序合并；不会启动训练。

## 9. 人工确认门、搜索与 resume

在负责人明确确认本文件第 3 节的 15 候选、45 次训练、主指标、tie-break、
失败规则及三个正式 seed 之前停止。当前不提供可直接启动完整真实搜索的命令。

确认后执行流程分为两个动作：先运行 `confirm-contract` 并带显式
`--confirm-stage4-search`，它只记录确认、不训练；再运行 `search`。完整可复制
命令应在确认后由本任务回填，防止当前草案被误启动。
确认动作会生成 `confirmed_search_contract.json` 与
`search_contract_confirmation.json`，搜索前必须同时校验两者及源配置 SHA。

中断后使用同一 config、R4、manifest、run ID、device 和 worker 参数运行
`resume`。它逐层验证训练合同、样本 SHA、词表 SHA、checkpoint SHA 后继续；
不兼容缓存会失败而不是覆盖。单张 3060 Ti 始终只有一个训练子进程；candidate
和 seed 串行训练，样本生成与 CPU Validation replay 才按 workload 多进程。

`all` 仍要求搜索确认文件，且最多生成 candidate 产物，绝不会自动 formal freeze。

## 10. candidate 验证与显式 formal freeze

搜索完成后先运行 `candidate` 只读验证。期望存在：

- `stage4_candidate.json`
- `validation_selection_report.json`
- `checkpoint_manifest.json`
- `verification.json`

此时 `run_state.formal_freeze=false`，且不得存在 `final_stage4_freeze.json`。

只有负责人检查真实结果并再次明确确认后，才运行 `freeze`，必须同时给出选中
candidate ID 和 `--confirm-stage4-freeze`。该命令才会生成：

- `final_stage4_freeze.json`
- `stage8_model_contract.json`
- `formal_checkpoint_manifest.json`
- `run_state.json` 中 `formal_freeze=true`

由于当前尚未完成真实搜索，也尚无真实 candidate ID，本版不提供可直接执行的
freeze 命令。冻结命令将在结果确认后回填。

## 11. 完成判据与 Stage 8 输入

Stage 4 只有在以下条件全部满足时才算完成：服务器新旧测试通过；三份 R4 与 R2
SHA 均匹配；12 个输入逐项通过；15 个候选按原合同完成或按失败规则记录；每个
候选覆盖三个 seed 和六个 Validation；选中配置的三个 seed checkpoint 全部保留；
候选报告经人工确认；显式 freeze 成功；最终 verification 和 SHA 链通过。

Stage 8 只接收 `final_stage4_freeze.json`、`stage8_model_contract.json` 和
`formal_checkpoint_manifest.json`。Standard 与 Pressure 必须绑定相同模型配置、
checkpoint SHA、seed、D/水位、K、b_max、初态、成本和状态机；唯一差异只能是
evaluation interval。Stage 4 全程不读取或等待 Pressure Test。
