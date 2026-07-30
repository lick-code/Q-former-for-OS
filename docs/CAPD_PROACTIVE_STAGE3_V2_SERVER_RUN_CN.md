# CAPD 主动降级阶段 3：capacity_rule_v2 服务器运行

## 已废止的数据选择

不要再用 `dataset/processed/real_workload_suite/5m` 做正式 v2
Validation。该目录元数据虽然含 `limit=5000000`，实际每个 workload
只有 100000 条记录，Train/Validation 分别为 80000/10000。正式运行
`stage3-v2-real-003` 已证明其 Validation 活跃集无法形成预声明容量压力。

`real_workload_suite/1m` 仍在仓库中，实际为 1000000 条记录，切分为
800000/100000/100000；它没有丢失。但其连续 Validation 尾段只有
30/54/10 个活跃页。诊断结果表明它在当前全局 Working Set 容量定义下
同样无法通过 v2，因此不能仅把路径从 `5m` 换成 `1m` 后重跑。

以上两套数据都不得再声称是本轮规则修改后的“全新 Validation”。
任何 `test.csv` 均不得用于参数选择。

## 修复后的防返工机制

`preflight_capd_proactive_stage3_inputs.py` 会在正式 Reactive-LRU 回放前检查：

- 只接受 Train/Validation，拒绝 Test；
- 中档绝对容量是否已经能容纳整个 Validation 活跃页集合；
- 每个 profile 是否对所有 Validation workload 都具备结构上的可达性。

若两个 profile 都结构不可达，脚本返回 3，写出
`<run-id>-input-preflight.json`，并跳过耗时回放。

## 唯一正式运行入口

先同步最新代码，然后在服务器终端执行。不要用 `source` 执行脚本，也不要
在交互终端设置 `set -e`。

```bash
cd "$HOME/Q-former-for-OS"
conda activate capd

bash scripts/run_capd_proactive_stage3_fresh_server.sh \
  --phase stage3_v2_fresh_001
```

脚本按顺序完成：

1. 自动寻找采集运行时并一次性核对 DynamoRIO、PARSEC 二进制和输入；
2. 对 canneal、streamcluster、dedup 各重新采集恰好 1M 条真实 RW；
3. 每个 workload 只切 600k Train 和 400k Validation，不创建 Test；
4. 生成带旧 Stage-3 输入指纹拒绝列表的 v2 manifest；
5. 先做容量可达性预检；
6. 预检通过后才执行 Reactive-LRU、burst、水位与 `b_max`。

若运行时不在自动搜索位置，显式指定一次：

```bash
bash scripts/run_capd_proactive_stage3_fresh_server.sh \
  --phase stage3_v2_fresh_001 \
  --qmap-root /absolute/path/to/qmap-work
```

这里的 `qmap-work` 必须同时包含：

- `parsec-3.0/`
- `tools/extern/DynamoRIO-Linux-11.91.20581/`
- `parsec-inputs/finals_v3_recollect/`

缺失时脚本只打印一条 `FINALS_V3_RECOLLECT_ERROR` 并返回，不会关闭当前终端，
也不会开始长时间实验。

## 结束标志

正式候选形成：

```text
STAGE3_V2_FREEZE_CANDIDATE_READY profile=primary
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
STAGE3_FRESH_SERVER_FINISHED status=0
```

或 fallback：

```text
STAGE3_V2_FREEZE_CANDIDATE_READY profile=fallback
STAGE3_CALIBRATION_RESULTS_READY_FOR_FREEZE
STAGE3_FRESH_SERVER_FINISHED status=0
```

新数据在昂贵回放前被拒绝：

```text
STAGE3_V2_INPUT_PREFLIGHT_BLOCKED
STAGE3_FRESH_TRACE_REJECTED_BEFORE_EXPENSIVE_REPLAY
```

此时保留新采集 trace、Train/Validation pair、manifest 和 preflight JSON，
但不冻结任何容量、水位或 `b_max`。
