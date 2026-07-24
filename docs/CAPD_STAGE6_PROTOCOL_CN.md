# CAPD 阶段6稳健性、开销与系统验证协议

状态：`FROZEN_FOR_EXECUTION`

上游门禁：Stage 5 必须为 `STAGE5_VERIFIED`，348/348 个 required job
完成，且 `test_used_for_selection=false`。

Stage 5结果文件存在并不等于Stage 6输入可执行。输入审计还必须逐workload
验证source manifest和train/valid/test processed trace均存在，且三个split
的内容指纹与resolved config完全一致；缺少原始绑定数据时禁止启动任务。

## 1. 阶段目标

阶段6不修改 CAPD-MIC-1.0，不重新选择 Stage 5 的模型结构、selector、
标签权重或默认参数。它只回答以下问题：

1. CAPD 在不同真实 workload、训练 seed、DRAM 容量和成本权重下是否稳健；
2. selector、Transformer、Cross-Attention scorer 和完整决策的
   mean/P50/P95/P99/max 延迟是多少；
3. 模型静态内存、进程峰值 RSS 和 CUDA 峰值内存是多少；
4. 相对经典基线的吞吐、迁移次数和 NVM 写入代价是什么；
5. 在有真实混合内存平台时，软件回放结论是否能获得额外系统证据。

## 2. 冻结输入

- workload：`canneal`、`streamcluster_pressure`、`dedup_pressure`；
- Stage 5 Full checkpoint seed：`3136859, 42, 2026`；
- Random replay seed：`0, 1, 2`；
- 默认配置：`D/B/K/H/Hc/L/Lres=64/64/8/10/256/256/256`；
- 外部基线：LRU、Random、LFU、CLOCK；
- 主指标：`weighted_access_cost`；
- 开销时钟：`time.perf_counter`；
- QMAP CUDA计时：每个组件边界同步；
- latency warmup：前20个决策不进入分位数。

任何 test trace 都只能用于最终回放和测量，不能用于参数、checkpoint、
cost profile 或容量点选择。

## 3. 容量稳健性

正式容量点为 `D in {64,128,256}`。`D=64`直接引用 Stage 5 Full；
`D=128/256`固定 `B=64,K=8,H=10,Hc=256,L=Lres=256`，因此只改变
DRAM容量。

由于容量改变会改变行为状态分布，`D=128/256`必须分别：

```text
train/valid trace
-> selector重新拟合
-> train/valid JSONL重新生成
-> 三模型seed重新训练
-> 同容量test trace闭环回放
```

每个容量和 workload 保留三 CAPD seed、三 Random seed以及
LRU/LFU/CLOCK。不得把 `D=64` checkpoint 直接当成高容量正式模型。

## 4. 成本权重稳健性

从 Stage 5 official 原始计数精确重加权，不重新训练、不重新选择模型：

| profile | DRAM R/W | NVM R | NVM W | migration |
|---|---:|---:|---:|---:|
| official | 1/1 | 2 | 8 | 10 |
| write_cost_low | 1/1 | 2 | 4 | 10 |
| write_cost_high | 1/1 | 2 | 16 | 10 |
| migration_cost_high | 1/1 | 2 | 8 | 20 |

重加权恒等式：

```text
J = hits*c_dram + nvm_reads*c_nr + nvm_writes*c_nw
    + migrations*c_migration
```

DRAM读写成本保持相同，现有计数不存在不可辨识项。

## 5. 真实读写比例

读写比例使用三个 official test trace 的真实 `RW` 列和 Stage 2 数据报告。
该证据用于展示自然 workload 覆盖，不是受控读写比例干预，不作因果解释。

## 6. 开销测量

QMAP逐决策记录：

- `selector`；
- `tensor_and_embedding`；
- `transformer_encoder`；
- `cross_attention_scorer`；
- `victim_selection`；
- `full_decision`。

所有分位数必须从原始逐决策样本合并后计算，禁止平均各运行的P95/P99。
同时报告完整 replay wall time、accesses/s、模型参数与buffer字节数、
进程峰值RSS、CUDA设备名、PyTorch版本及CUDA peak allocated/reserved。
正式QMAP profile必须在CUDA设备上运行；CPU mini E2E只验证测量链路，
不能替代正式开销结果。

吞吐下降以同workload下吞吐最高的预注册经典基线为参照；迁移次数和
NVM写入变化分别以对应计数最低的预注册经典基线为参照。报告参照策略、
绝对差和百分比；参照值为0时百分比记为不可定义，不以0替代。

## 7. 系统平台边界

真实混合内存平台验证为条件项：

- 有可用平台时，记录硬件、内核、NUMA/内存绑定、采样命令和原始日志；
- 无平台时，状态必须为 `CONDITIONAL_NOT_RUN`，不得伪造系统吞吐或延迟；
- 软件 Stage 6 可以独立验收，但论文必须把该限制写入局限性。

## 8. 正式输出

输出根目录：`outputs/results/finals_v3_official/stage6/`。

必须包含 profile、capacity、cost robustness、natural RW robustness
四组 CSV/JSON/报告、显式的system platform状态JSON/报告，以及
`input_audit.json`、`execution_plan.json` 和 `run_manifest.json`。
