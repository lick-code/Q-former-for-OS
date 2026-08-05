# Stage10A Linux 交接

以下命令仅供未来 Linux 主机复制执行，当前未执行。`STAGE9_RUN_ROOT` 必须指向完整且新生成的 Stage9 v2 run directory，且其 receipt 状态为 `stage9_overhead_verified`。当前仓库的 `stage9-overhead-r1` 必须被拒绝。

```bash
set -o pipefail
export STAGE9_RUN_ROOT
test -d "$STAGE9_RUN_ROOT"
mkdir -p logs
TEST_LOG=logs/stage10-unit-tests.log
TEST_COMMAND='python3 -m unittest tests.test_capd_proactive_stage10 -v'
printf 'COMMAND: %s\n' "$TEST_COMMAND" > "$TEST_LOG"
python3 -m unittest tests.test_capd_proactive_stage10 -v 2>&1 |
  tee -a "$TEST_LOG"
TEST_LOG_SHA256=$(sha256sum "$TEST_LOG" | awk '{print $1}')
python3 scripts/run_capd_proactive_stage10.py \
  --config configs/finals/capd_proactive_stage10.json \
  --mode formal \
  --stage9-run-root "$STAGE9_RUN_ROOT" \
  --test-log-input "$TEST_LOG" \
  --test-log-sha256 "$TEST_LOG_SHA256" \
  --output-root outputs/capd_proactive_stage10 \
  --run-id stage10-async-simulator-r1-linux \
  2>&1 | tee logs/stage10-async-simulator-r1-linux.log
python3 scripts/run_capd_proactive_stage10.py \
  --verify outputs/capd_proactive_stage10/stage10-async-simulator-r1-linux
```

Stage10 会独立读取并 hash Stage9 的 `run_state.json`、`verification.json`、`artifact_sha256` map 和 `stage8_compatibility_receipt.json`，再生成自己的 compatibility receipt；不会接受调用者自带 receipt，也不会信任自报的 `sha_chain_verified` 字段。
