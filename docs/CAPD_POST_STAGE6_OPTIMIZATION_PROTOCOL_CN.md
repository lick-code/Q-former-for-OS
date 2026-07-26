# CAPD Stage 6 后冻结方法配置优化协议

状态：`O1_O3_IMPLEMENTED_SERVER_EXECUTION_PENDING`

本轨道用于在不改变 `CAPD-MIC-1.0` 方法设计的前提下，检查验证集系统
成本选 checkpoint、已有参数配置以及多 seed 确认能否改善正式结果。
它不覆盖 `STAGE5_VERIFIED`、`STAGE6_VERIFIED` 或
`BRIDGE_DIAGNOSTIC_COMPLETED`。

仓库历史 README 已使用“Stage 7”表示旧版 seed stability。为避免把两套
证据混为一谈，本轨道不复用该编号，统一使用 `O0`—`O4`。

## 1. 不变项与允许项

冻结不变：

- 架构：`QMAP-CrossAttn`；
- selector 的五个特征、方向、权重约束与确定性并列规则；
- 代理标签公式与 `QMAPCostAwareRankingLoss`；
- 首次访问、迁移、dirty 页和加权成本记账；
- 每 workload 独立训练；
- official 成本配置；
- 外部基线：LRU、Random、LFU、CLOCK。

允许优化：

- 已有配置字段 `B/K/L/H`；
- 训练 epoch 中 checkpoint 的选择规则；
- 模型随机种子稳定性；
- 实验 workload、配置和容量的分层报告。

固定 `D=64,Hc=256,Lres=256`。本轨道不加入 on-policy 数据聚合、
新标签、新损失、安全回退、ensemble 或新模型层；这些都属于新方法版本。

## 2. O0：协议、输入审计与新 holdout 封存

任务：

1. 验证 Stage 6 为 `STAGE6_VERIFIED`、105/105；
2. 验证桥接诊断为 `BRIDGE_DIAGNOSTIC_COMPLETED`、33/33；
3. 记录全部 official train/valid/test 与源采集指纹；
4. 审计是否存在从未参与采集选择、参数选择或结果查看的新 trace；
5. 为三 workload 建立独立 holdout manifest，只读取元数据、行数和
   SHA-256，不计算任何策略指标；
6. 封存后禁止 O1—O3 打开 holdout 行内容。

现有三条 official 源采集已被完整分配：

- Canneal：`[0,600000)` train、`[600000,800000)` valid、
  `[800000,1000000)` test；
- Streamcluster：同上；
- DEDUP：`[0,1000000)` train、`[1000000,2000000)` valid、
  `[2000000,3000000)` test。

因此不能从现有 official 采集中再切出“新 final”，也不得复制或重命名旧
test 冒充新数据。缺少新 holdout 不阻塞只读取 train/valid 的 O1—O3；
它只阻塞 O4 的一次性最终评估。

O1—O3 启动门槛：协议、Stage 6、桥接证据和 official 数据来源审计通过。

O4 额外门槛：三个新采集均 provenance-complete、与所有 official split
指纹不同、满足最小访问数并写入 `sealed=true`、
`used_for_selection=false`、`eligible_for_final_holdout=true`。

## 3. O1：Oracle headroom 审计

只使用 train/valid。禁止读取 official test 和新 holdout。

对预注册配置执行验证集 `bounded_label_oracle`：每次决策只在冻结
`B→K` 候选中使用未来代理标签选择 victim，再对整条 valid trace 计算
真实 `weighted_access_cost`。输出：

- LRU/Clock 与候选内 Oracle 的绝对和相对成本差；
- 有效决策数、并列比例、候选内可改善决策比例；
- 每 workload/config 的 headroom 判定；
- 保留 Full control，删除无可测 headroom 的非默认训练点。

该 Oracle 是“现有候选与代理标签能否产生系统收益”的诊断策略，不是
可部署策略，也不是全局最优替换策略的数学严格上界。如果它低于
LRU/CLOCK，说明该配置存在可学习的代理 headroom；如果它更差，则不得
仅凭标签排序差异宣称存在系统成本上界。

## 4. O2：配置搜索与 checkpoint 选择

只使用 train/valid。每个训练 epoch 保存 checkpoint，并在 valid trace
闭环回放。checkpoint 选择顺序固定为：

1. 最低 valid `weighted_access_cost`；
2. 若成本完全相同，最低 valid ApproxNDCG loss；
3. 若仍相同，选择更早 epoch。

预注册八个配置：

| config | B | K | L | H |
|---|---:|---:|---:|---:|
| `opt_full_control` | 64 | 8 | 256 | 10 |
| `opt_B32` | 32 | 8 | 256 | 10 |
| `opt_K16` | 64 | 16 | 256 | 10 |
| `opt_L512` | 64 | 8 | 512 | 10 |
| `opt_H20` | 64 | 8 | 256 | 20 |
| `opt_B32_K16` | 32 | 16 | 256 | 10 |
| `opt_B32_K16_L512` | 32 | 16 | 512 | 10 |
| `opt_B32_K16_L512_H20` | 32 | 16 | 512 | 20 |

先运行 seed `3136859`。每 workload 只按 valid cost 保留前两名；test
结果、旧敏感性 test 表和桥接 test 均不得参与排序。

## 5. O3：多 seed 确认与配置锁定

对每 workload 的前两名补 seed `42`、`2026`。唯一最终配置按以下顺序
锁定：

1. 三 seed valid cost 均值最低；
2. 均值相同则样本标准差最低；
3. 仍相同则选计算复杂度较低者；
4. 最后按 `config_id` 字典序确定。

锁定文件必须包含配置、三个 checkpoint、输入和代码指纹。锁定后不得因
任何 final holdout 数字更换配置或 checkpoint。

## 6. O4：封存 holdout 一次性最终评估

每个锁定 QMAP checkpoint 和预注册经典基线各执行一次规定回放。Random
仍使用冻结 seed `0,1,2`。O4 开始后：

- 不允许重新训练；
- 不允许修改配置或成本；
- 不允许只保留“更好”的 workload；
- 不允许覆盖 Stage 5/6 目录；
- 无论结果好坏都必须完整汇总。

输出根目录：

```text
dataset/jsonl/capd_post_stage6_optimization/
outputs/checkpoints/capd_post_stage6_optimization/
outputs/results/capd_post_stage6_optimization/
```

最终状态只有所有门禁和一次性评估全部完成后才可写为
`CAPD_OPTIMIZATION_COMPLETED`。

## 7. 当前执行边界

当前允许实现并执行 O1—O3。它们只能读取 train/valid；official test
不能参与 checkpoint、配置或 workload 的选择。仓库内尚无合格的新
holdout，因此 O4 暂不启动。O3 锁定配置后，即使查看任何事后 test
对照，也不得返回修改配置或 checkpoint。

本地 O1 端到端已经通过；正式 O1—O3 结果仍须在服务器执行。统一验收
命令为：

```bash
set -o pipefail
bash scripts/validate_capd_optimization_server.sh 2>&1 \
  | tee capd_optimization_validation.log
rc=${PIPESTATUS[0]}
echo "optimization_exit_code=$rc"
```

该脚本依次执行 O0 审计、定向测试、O1 的 54 个 CPU 任务、O2 单 seed
训练与逐 epoch valid replay、O3 额外两个 seed 的确认及配置锁定。所有
任务均带原子 job manifest，可在失败后重新运行同一命令断点续跑。
