# CAPD 当前实验进展与结论笔记

更新时间：2026-07-27

## 1. 当前状态

截至目前，已经完成：

1. Stage 6 正式实验与服务器验收；
2. Bridge 桥接诊断实验；
3. Post-Stage 6 优化阶段 O0 输入审计；
4. O1 oracle headroom 诊断；
5. O2 参数组合搜索；
6. O3 多 seed 复核与配置锁定。

当前状态为：

```text
O3_CONFIGURATIONS_LOCKED_AWAITING_FRESH_HOLDOUT
```

O4 尚未开始。当前缺少三个 workload 对应的全新、独立且封存的
fresh holdout trace。

---

## 2. Stage 6：正式实验

Stage 6 已通过服务器验收：

```text
status = STAGE6_VERIFIED
required_jobs = 105
completed_required_jobs = 105
```

Stage 6 覆盖了：

- 运行开销与吞吐；
- D=128、D=256 的容量稳健性；
- 不同成本权重下的稳健性；
- workload 自然读写比例；
- 系统与平台验证。

实验满足以下约束：

- Stage 5 上游状态保持为 `STAGE5_VERIFIED`；
- test 数据未用于配置选择；
- CAPD 方法契约未被改变；
- 105 个必需任务全部完成。

Stage 6 的主要现象是：当前正式实验中的性能优势明显小于早期实验，
因此后续执行了 Bridge 桥接诊断。

---

## 3. Bridge：退化来源诊断

Bridge 实验已完成：

```text
status = BRIDGE_DIAGNOSTIC_COMPLETED
required_jobs = 33
completed_required_jobs = 33
```

五个桥接锚点的结果如下：

| 实验锚点 | D/B/K | QMAP 相对最佳传统策略的改善 |
|---|---:|---:|
| 旧 trace、论文配置 | 16/8/8 | +11.0754% |
| 旧 trace、当前执行管线 | 16/8/8 | +10.6109% |
| 旧 trace、当前 selector | 16/16/8 | +10.2241% |
| 官方新 trace、当前 selector | 16/16/8 | +3.7008% |
| 官方新 trace、完整正式配置 | 64/64/8 | +0.6325% |

逐因素归因：

| 因素 | 改善幅度变化 | 判断 |
|---|---:|---|
| 执行引擎和管线 | -0.4645 个百分点 | 影响较小 |
| candidate selector | -0.3868 个百分点 | 影响较小 |
| trace 来源变化 | -6.5234 个百分点 | 最大退化来源 |
| DRAM 容量和可行候选池 | -3.0683 个百分点 | 第二大退化来源 |

Bridge 实验支持以下结论：

1. 当前效果下降不是简单的代码运行错误；
2. selector 变化不是主要原因；
3. 最大影响来自官方新 trace 的数据分布变化；
4. 更大的 DRAM 容量和候选池进一步压缩了相对传统策略的优势；
5. Bridge 是事后诊断，不替代 Stage 6 正式结果。

---

## 4. O0：优化阶段输入审计

O0 的审计结果为：

```text
status = O0_READY_FOR_O1_O3
eligible_to_start_O1 = true
eligible_to_start_O4 = false
sealed_holdout_count = 0
blocked_o4_inputs = 3
test_used_for_selection = false
```

因此，可以在现有 train/valid 数据上完成 O1–O3，但在准备新的 sealed
holdout 之前不能开始 O4。

---

## 5. O1：Oracle Headroom 诊断

O1 使用 bounded-label oracle 测量现有配置和动作空间在验证 trace 上相对
最佳 LRU/CLOCK 的剩余优化空间。

每个 workload 的最大观测 headroom 为：

| workload | 最大 absolute headroom | 最大 relative headroom |
|---|---:|---:|
| canneal | 242 | 0.1069% |
| dedup_pressure | 11 | 0.0011% |
| streamcluster_pressure | 481 | 0.2078% |

O1 结论：

- 三个 workload 的最大 headroom 都很小；
- dedup_pressure 几乎没有可利用空间；
- streamcluster_pressure 的数值最大，但仍不足 0.21%；
- 在当前 trace、动作定义和 oracle 定义下，仅调整 B、K、L、H 很难产生
  大幅性能提升；
- O1 的结果满足门禁要求，因此继续执行了 O2，但其支持强度有限。

注意：`0.2078%` 是当前验证 trace 上 bounded-label oracle 相对最佳传统
策略的最大观测 headroom，不是对所有数据和所有方法的普遍理论上限。

---

## 6. O2：参数组合搜索

O2 在固定 screening seed `3136859` 上搜索 B、K、L、H 的候选组合。

### 6.1 canneal

| 配置 | valid cost | 相对 `opt_full_control` |
|---|---:|---:|
| `opt_B32_K16_L512` | 226073 | 改善 1562，约 0.6862% |
| `opt_B32_K16_L512_H20` | 226139 | 改善 1496，约 0.6572% |
| `opt_full_control` | 227635 | 基准 |
| `opt_B32_K16` | 229978 | 退化 2343，约 1.0293% |

O2 shortlist：

```text
opt_B32_K16_L512
opt_B32_K16_L512_H20
```

canneal 是唯一出现清晰成本改善信号的 workload。L=512 是主要的正向配置
变化；H=20 没有进一步改善成本。

### 6.2 dedup_pressure

| 配置 | valid cost | 相对 `opt_full_control` |
|---|---:|---:|
| `opt_B32_K16_L512` | 1036899 | 改善 178，约 0.0172% |
| `opt_B32_K16` | 1036899 | 改善 178，约 0.0172% |
| `opt_B32_K16_L512_H20` | 1036972 | 改善 105，约 0.0101% |
| `opt_full_control` | 1037077 | 基准 |

O2 shortlist：

```text
opt_B32_K16_L512
opt_B32_K16
```

dedup_pressure 中 L=256 和 L=512 的系统成本完全相同。L=512 仅因 valid
loss 更低而在 O2 中排在前面，其实际系统成本并未更优。

### 6.3 streamcluster_pressure

八个候选配置的 valid cost 全部为：

```text
230227
```

O2 shortlist：

```text
opt_B32_K16_L512_H20
opt_B32_K16_L512
```

shortlist 由 valid loss 的次级排序决定。参数变化没有降低实际系统成本，
因此不能将 shortlist 排名解释为系统性能提升。

### 6.4 O2 总结

- canneal：存在小幅、可见的验证集改善；
- dedup_pressure：改善极小，基本没有工程意义；
- streamcluster_pressure：成本改善为 0；
- H=20 在三个 workload 上都没有形成成本优势；
- L=512 的效果具有 workload-specific 特征，不能统一推广。

O2 中的百分比是同一 screening seed 上的验证集比较，不是独立测试集结果，
也不是严格的三 seed 对照结果。

---

## 7. O3：多 Seed 复核与配置锁定

O3 对每个 workload 的两个 shortlist 配置执行三 seed 复核，并按照以下
规则锁定配置：

1. 三 seed valid cost 均值；
2. 样本标准差；
3. 配置复杂度；
4. config ID。

最终结果：

| workload | 锁定配置 | B | K | L | H | 三 seed valid cost |
|---|---|---:|---:|---:|---:|---:|
| canneal | `opt_B32_K16_L512` | 32 | 16 | 512 | 10 | 225009.67 ± 971.02 |
| dedup_pressure | `opt_B32_K16` | 32 | 16 | 256 | 10 | 1036715.33 ± 293.36 |
| streamcluster_pressure | `opt_B32_K16_L512` | 32 | 16 | 512 | 10 | 230227.00 ± 0.00 |

锁定原因：

- canneal：L=512 的成本明确低于 L=256；H=20 略差，因此选择 H=10；
- dedup_pressure：L=256 与 L=512 的三 seed 均值和标准差完全相同，因此
  根据较低复杂度选择 L=256；
- streamcluster_pressure：两个 shortlist 配置的成本完全相同，因此选择
  复杂度较低的 H=10。

O3 的保护条件均满足：

- `test_trace_opened = false`；
- `test_used_for_selection = false`；
- `method_contract_changed = false`；
- `official_stage6_replaced = false`。

---

## 8. 当前能够得出的总论

### 8.1 实验流程方面

实验流程已经取得明确进展：

- Stage 6 正式实验完整完成；
- Bridge 成功定位了早期结果与当前结果之间的主要差异来源；
- O1–O3 完成了参数空间诊断、候选搜索和多 seed 配置锁定；
- 实验过程中没有使用 test 数据进行选择；
- 上游 Stage 6 和方法契约保持不变。

### 8.2 性能方面

当前没有取得整体性的显著性能突破：

- canneal 出现约 0.6862% 的同 seed 验证集改善信号；
- dedup_pressure 只有约 0.0172% 的改善，基本可以忽略；
- streamcluster_pressure 的系统成本改善为 0；
- 参数扩展不是当前效果不佳的主要瓶颈；
- 继续盲目增大 D、B、K、L 或 H 的预期收益很低。

### 8.3 科学结论方面

目前可以说：

> 在当前验证数据上，参数优化对 canneal 有小幅正向信号，但对
> dedup_pressure 和 streamcluster_pressure 没有实质改善。

目前不能说：

> O3 锁定配置已经在独立数据上证明了整体泛化提升。

原因包括：

1. O1–O3 的数字都参与了配置筛选；
2. 尚未执行独立 fresh holdout；
3. 原始配置缺少严格匹配的三 seed 对照；
4. canneal 的改善尚不能确认超过训练随机性；
5. 另外两个 workload 没有提供整体改善证据。

---

## 9. O4 待完成内容

O4 的目标是对 O3 锁定配置进行一次独立、不可回退的泛化验证。

需要完成：

1. 为 canneal、dedup_pressure、streamcluster_pressure 分别采集全新的
   holdout trace；
2. 固定采集协议、workload 参数、运行环境和文件哈希；
3. 在查看任何策略结果之前封存 trace；
4. 冻结 O3 的配置、checkpoint、seed 和 fingerprint；
5. 在同一 holdout 上评估：
   - O3 锁定配置；
   - 原始 `opt_full_control`；
   - LRU；
   - CLOCK；
6. 报告逐 seed 结果、均值、样本标准差、绝对改善和百分比改善；
7. 不允许使用 holdout 重新训练、选择 checkpoint 或调整配置；
8. 无论三个 workload 的结果好坏，都必须完整报告。

O4 可能形成的结论：

- 三个 workload 均稳定改善：支持整体参数优化有效；
- 只有 canneal 改善：结论必须限制为 workload-specific；
- canneal 改善也未复现：O1–O3 的信号可能来自验证集选择或随机波动。

---

## 10. 关键结果文件

- Stage 6 manifest：
  `outputs/results/finals_v3_official/stage6/run_manifest.json`
- Bridge 报告：
  `outputs/results/capd_bridge_diagnostic/bridge_report.md`
- Bridge manifest：
  `outputs/results/capd_bridge_diagnostic/run_manifest.json`
- O0 输入审计：
  `outputs/results/capd_post_stage6_optimization/stage0_input_audit.json`
- O1 headroom：
  `outputs/results/capd_post_stage6_optimization/o1/headroom_summary.json`
- O1 门禁：
  `outputs/results/capd_post_stage6_optimization/o1/headroom_gate.json`
- O2 搜索结果：
  `outputs/results/capd_post_stage6_optimization/o2/search_results.csv`
- O2 shortlist：
  `outputs/results/capd_post_stage6_optimization/o2/search_shortlist.json`
- O2 checkpoint 选择：
  `outputs/results/capd_post_stage6_optimization/o2/selected_checkpoints.csv`
- O3 多 seed 汇总：
  `outputs/results/capd_post_stage6_optimization/o3/multiseed_results.csv`
- O3 锁定配置：
  `outputs/results/capd_post_stage6_optimization/o3/locked_configurations.json`
- O3 manifest：
  `outputs/results/capd_post_stage6_optimization/o3/run_manifest.json`

