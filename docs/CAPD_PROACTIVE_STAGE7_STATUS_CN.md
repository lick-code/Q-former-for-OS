# CAPD 主动降级阶段 7 当前状态

## 当前状态

`stage7_collection_complete_awaiting_freeze`

阶段 7 的正式六 workload Trace 已在本地 WSL 采集并完成 suite 准备，
但本地 WSL 缺少 PyTorch，尚未通过阶段 1～7 的完整回归门禁。因此不得
写 `stage7_workload_suite_verified`，也不得提前运行阶段 8 的正式 Test
策略 Replay。

## 正式名单

| workload | 角色 | 覆盖类型 |
|---|---|---|
| canneal | seen calibration | 不规则、局部性敏感 |
| streamcluster_pressure | seen calibration | 高容量压力、突发进入 |
| dedup_pressure | seen calibration | 写密集、高容量压力 |
| blackscholes | held-out unseen | 稳定局部性 |
| swaptions | held-out unseen | 计算主导、稳定局部性 |
| fluidanimate | held-out unseen | 不规则、突发进入 |

备用 unseen 为 bodytrack、facesim，不进入本次正式名单。

## 本地采集回执

- collection run ID：`stage7-local-collection-r1`；
- collector：DynamoRIO drmemtrace 11.91.20581；
- 每个 workload：3,000,000 条数据访问；
- Trace schema：`PID,TID,PC,Address,RW`，4 KB page；
- split：Train `[0,1800000)`，Validation `[1800000,2400000)`，
  Test `[2400000,3000000)`；
- 六条正式 Trace 均通过单 PID、单 TID、访问数、输入/二进制身份和
  SHA-256 检查；
- Test 只为完整性封存，未用于参数选择，未运行策略 Replay，未检查
  Test 性能。

swaptions 的 PARSEC `gcc-pthreads` 构建即使传入 `-nt 1` 仍产生两个
TID，失败证据保存在当前 collection run 的 `failed_attempts` 目录。
正式 Trace 使用相同 PARSEC 3.0 源码的 serial 构建，并在完整 3,000,000
条访问上确认单 PID/单 TID。

## Working Set 与容量准备

suite run ID：`stage7-local-suite-r1`。

| workload | Working Set pages | D20 pages | D40 pages | D60 pages |
|---|---:|---:|---:|---:|
| canneal | 4443 | 889 | 1778 | 2666 |
| streamcluster_pressure | 1921 | 385 | 769 | 1153 |
| dedup_pressure | 982 | 197 | 393 | 590 |
| blackscholes | 110 | 22 | 44 | 66 |
| swaptions | 297 | 60 | 119 | 179 |
| fluidanimate | 27720 | 5544 | 11088 | 16632 |

Working Set 定义固定为
`active_unique_pages_from_train_and_validation`，不读取 Test 页面集合参与
计算。已生成 18 个容量行、Standard Test lock 和 144-job Stage 8
执行计划。20% DRAM 仍是条件工程默认值，不是 `capacity_rule_v2` 的
形式化标定结论；水位 `F_low=8/F_target=16` 不随容量缩放。

blackscholes 的 D20 为 22 页，满足 `D20 > max(F_target,K)=16` 的硬门禁，
但低于 100 页，按预声明规则保留
`D_20_below_100_evaluate_recollection_or_replacement` 警告。该警告不是
依据 Test 性能作出的。

## 已执行测试

- 阶段 7 专项单元/合成测试：47/47 通过；
- 六 workload 本地正式采集：6/6 完成；
- suite 准备：6 workload、18 capacity rows、144 Stage 8 jobs；
- 阶段 1～7 回归（WSL 系统 Python）：269 项，13 个错误均为缺少
  NumPy 的导入错误；
- 阶段 1～7 回归（本地 NumPy venv）：351 项，仅 1 个错误，为旧阶段 4
  训练测试导入 PyTorch 失败。

上述依赖错误不代表阶段 7 语义失败，但也不能被跳过或伪造为通过。

## 下一门禁

在具备 NumPy 和 PyTorch 的 Linux 环境执行：

```bash
export PYTHON_BIN=python3
export CAPD_DIRTY_WORKTREE=true
bash scripts/validate_capd_proactive_stage7_server.sh \
  stage7-local-suite-r1 \
  outputs/capd_proactive_stage7/collections/stage7-local-collection-r1/collection_manifest.json
```

只有同时出现以下两行，阶段 7 才可判定为完成并允许进入阶段 8：

```text
[FINAL] STAGE7_WORKLOAD_SUITE_VERIFIED
validator_exit=0
```
