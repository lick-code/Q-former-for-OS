# CAPD 主动降级阶段 7 Trace采集说明

## 当前门禁

先运行环境审计：

```bash
cd /home/likc/Q-former-for-OS
git switch main
test "$(git branch --show-current)" = "main"

export PYTHON_BIN=python3
export DYNAMORIO_HOME=/root/qmap-work/tools/extern/DynamoRIO-Linux-11.91.20581
export PARSEC_ROOT=/root/qmap-work/parsec-3.0
export CANNEAL_INPUT=/path/to/canneal/native/input.nets
export DEDUP_INPUT=/path/to/dedup/native/input.iso
export BLACKSCHOLES_INPUT=/path/to/blackscholes/native/input.txt
export FLUIDANIMATE_INPUT=/path/to/fluidanimate/native/input.fluid

bash scripts/preflight_capd_proactive_stage7_collection.sh stage7-impl-r1
```

六-workload名单已经用户明确确认，`suite_confirmation.confirmed=true`。正式采集已解除
名单门禁，但每条 Trace 仍必须通过实际单 PID、单 TID、完整访问数和无丢失事件门禁。
采集必须使用新的 collection run ID。

## 采集合同

统一调用：

```bash
bash scripts/collect_capd_proactive_stage7_trace.sh \
  RUN_ID WORKLOAD ROLE BINARY INPUT_NAME INPUT_PATH -- COMMAND...
```

`INPUT_PATH` 不适用时写 `-`。脚本固定：

- 3,000,000 条数据访问；
- 4 KB page；
- `PID,TID,PC,Address,RW`；
- DynamoRIO drmemtrace；
- 最长默认 4 小时；
- 原始 Trace 和失败现场不覆盖、不自动重试；
- `[0,1800000)` / `[1800000,2400000)` / `[2400000,3000000)`；
- 采集完成后重算 SHA 和 PID/TID，并原子更新 collection manifest。

名单确认后，访问数和 split 已不可修改：总数 3,000,000，Train end 1,800,000，
Validation end 2,400,000。环境变量若试图修改这三项会被硬拒绝。只允许按机器速度调整
超时，例如 `STAGE7_COLLECTION_TIMEOUT_SECONDS=14400`。

正式门禁要求观测到恰好一个 PID 和一个 TID。benchmark 即使传入线程参数 1，只要
Trace 中实际出现多个 PID/TID，仍会失败。

## 命令模板

以下模板现在可以执行。路径按实际 PARSEC 安装替换。

canneal：

```bash
RUN_ID=stage7-collection-r1
BIN="$PARSEC_ROOT/pkgs/kernels/canneal/inst/amd64-linux.gcc-serial/bin/canneal"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" canneal seen_calibration_workload \
  "$BIN" native "$CANNEAL_INPUT" -- \
  "$BIN" 1 15000 2000 "$CANNEAL_INPUT" 6000
```

streamcluster_pressure：

```bash
BIN="$PARSEC_ROOT/pkgs/kernels/streamcluster/inst/amd64-linux.gcc-pthreads/bin/streamcluster"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" streamcluster_pressure seen_calibration_workload \
  "$BIN" native_synthetic - -- \
  "$BIN" 10 20 128 1000000 200000 5000 none \
  "outputs/capd_proactive_stage7/collections/$RUN_ID/streamcluster.out" 1
```

dedup_pressure：

```bash
BIN="$PARSEC_ROOT/pkgs/kernels/dedup/inst/amd64-linux.gcc-pthreads/bin/dedup"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" dedup_pressure seen_calibration_workload \
  "$BIN" native "$DEDUP_INPUT" -- \
  "$BIN" -c -p -v -t 1 -i "$DEDUP_INPUT" \
  -o "outputs/capd_proactive_stage7/collections/$RUN_ID/dedup.out.ddp"
```

blackscholes：

```bash
BIN="$PARSEC_ROOT/pkgs/apps/blackscholes/inst/amd64-linux.gcc-serial/bin/blackscholes"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" blackscholes held_out_unseen_workload \
  "$BIN" native "$BLACKSCHOLES_INPUT" -- \
  "$BIN" 1 "$BLACKSCHOLES_INPUT" \
  "outputs/capd_proactive_stage7/collections/$RUN_ID/blackscholes.out"
```

swaptions：

```bash
BIN="${SWAPTIONS_BIN:?set this to a serial PARSEC swaptions binary}"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" swaptions held_out_unseen_workload \
  "$BIN" native_synthetic - -- \
  "$BIN" -ns 128 -sm 100000 -nt 1
```

注意：PARSEC 的 `gcc-pthreads` swaptions 即使传入 `-nt 1`，仍会创建
一个工作线程并与主线程形成两个 TID，不能满足本阶段的单 TID 合同。
正式路径必须使用未定义 `ENABLE_THREADS` 的同源码 serial 构建，并在
完整 3,000,000 条 Trace 上再次核对 TID，不能依据短 smoke 判断。

fluidanimate：

```bash
BIN="$PARSEC_ROOT/pkgs/apps/fluidanimate/inst/amd64-linux.gcc-pthreads/bin/fluidanimate"
bash scripts/collect_capd_proactive_stage7_trace.sh \
  "$RUN_ID" fluidanimate held_out_unseen_workload \
  "$BIN" native "$FLUIDANIMATE_INPUT" -- \
  "$BIN" 1 5 "$FLUIDANIMATE_INPUT" \
  "outputs/capd_proactive_stage7/collections/$RUN_ID/fluidanimate.out"
```

## 冻结与最终验收

六条 Trace 都成功后：

```bash
COLLECTION_MANIFEST="outputs/capd_proactive_stage7/collections/$RUN_ID/collection_manifest.json"
SUITE_RUN_ID=stage7-suite-r1

set -o pipefail
bash scripts/validate_capd_proactive_stage7_server.sh \
  "$SUITE_RUN_ID" "$COLLECTION_MANIFEST" \
  2>&1 | tee "stage7-${SUITE_RUN_ID}-console.log"
```

只有以下两行同时出现才是最终成功：

```text
[FINAL] STAGE7_WORKLOAD_SUITE_VERIFIED
validator_exit=0
```
