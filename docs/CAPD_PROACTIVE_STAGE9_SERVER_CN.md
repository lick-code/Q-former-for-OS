# CAPD 主动降级 Stage9 Ubuntu 服务器运行交接

## 1. 运行前检查

从仓库根目录运行。必须保留 Stage8 r3 权威目录，不要重新运行或覆盖 Stage8。服务器需要 Python/PyTorch 项目环境、Linux `taskset` 与 `perf`。Stage9 默认绑定 CPU 0；先确认当前 shell 的 cpuset 包含 0：

```bash
grep Cpus_allowed_list /proc/self/status
```

若不包含 0，在任何正式 run 之前把 `configs/finals/capd_proactive_stage9.json` 的 `measurement.cpu_affinity` 改成一个允许的单独逻辑 CPU。脚本会从 JSON 读取该值并用于所有 `taskset`，不再需要同步修改多处命令。此修改必须发生在看任何 Stage9 结果之前；preflight 会冻结并记录新 config SHA。不要复用曾失败或运行中的 run ID。

`stage9-overhead-r1` 已永久失败，且其 0.40 容量测量没有产生正式延迟样本；必须原样保留该目录，禁止续跑、覆盖或导入。修复后的第一次运行至少使用 `stage9-overhead-r2`。

## 2. 一键正式运行

```bash
cd /path/to/Q-former-for-OS
chmod +x scripts/validate_capd_proactive_stage9_server.sh
RUN_ID="stage9-overhead-r2"
PYTHON_BIN=python3 bash scripts/validate_capd_proactive_stage9_server.sh "${RUN_ID}"
```

该脚本首先在不创建 run 目录的情况下验证配置中的 CPU affinity、perf FIFO control 能力以及 cycles/instructions/task-clock 的真实可用性。探针通过后，才顺序执行 Stage8 入口/SHA preflight、静态编译、Stage1-9 全量 unittest、测试回执、延迟/质量/内存、受控 perf、perf 解析和独立验证。成功时最后一行必须且只能由 verify 打印：

```text
[FINAL] STAGE9_OVERHEAD_VERIFIED
```

## 3. 展开的可复制命令

以下命令等价，适合逐步诊断：

```bash
cd /path/to/Q-former-for-OS
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export PYTHONHASHSEED=0
RUN_ID="stage9-overhead-r2"
RUN_ROOT="outputs/capd_proactive_stage9/${RUN_ID}"
CPU_AFFINITY="$(python3 -c 'import json; print(json.load(open("configs/finals/capd_proactive_stage9.json"))["measurement"]["cpu_affinity"][0])')"

taskset -c "${CPU_AFFINITY}" /bin/true
perf stat -h 2>&1 | grep -- '--control'
perf stat -e cycles,instructions,task-clock -- \
  taskset -c "${CPU_AFFINITY}" /bin/true

taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
  --project-root "$PWD" --run-id "${RUN_ID}" preflight

python3 -m py_compile \
  qmap/proactive_stage9.py \
  scripts/run_capd_proactive_stage9.py

mkdir -p "${RUN_ROOT}/logs"
python3 -m unittest discover -s tests -p 'test*.py' -v \
  2>&1 | tee "${RUN_ROOT}/logs/stage1_stage9_regression.log"

taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
  --project-root "$PWD" --run-id "${RUN_ID}" \
  record-tests --test-log "${RUN_ROOT}/logs/stage1_stage9_regression.log"

taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
  --project-root "$PWD" --run-id "${RUN_ID}" measure

mkdir -p "${RUN_ROOT}/perf"
CONTROL_FIFO="${RUN_ROOT}/perf/control.fifo"
ACK_FIFO="${RUN_ROOT}/perf/ack.fifo"
rm -f "${CONTROL_FIFO}" "${ACK_FIFO}"
mkfifo "${CONTROL_FIFO}" "${ACK_FIFO}"

perf stat \
  --delay=-1 \
  --control="fifo:${CONTROL_FIFO},${ACK_FIFO}" \
  -x ';' \
  -e cycles,instructions,task-clock,context-switches,cpu-migrations,page-faults \
  -o "${RUN_ROOT}/perf/perf-stat.raw" \
  -- taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
    --project-root "$PWD" --run-id "${RUN_ID}" \
    perf-workload --perf-control-fifo "${CONTROL_FIFO}" \
    --perf-ack-fifo "${ACK_FIFO}" \
  2> "${RUN_ROOT}/perf/perf-stderr.log"

taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
  --project-root "$PWD" --run-id "${RUN_ID}" parse-perf

taskset -c "${CPU_AFFINITY}" python3 scripts/run_capd_proactive_stage9.py \
  --project-root "$PWD" --run-id "${RUN_ID}" verify
```

## 4. perf 权限失败

先只读检查：

```bash
perf --version
cat /proc/sys/kernel/perf_event_paranoid
CPU_AFFINITY="$(python3 -c 'import json; print(json.load(open("configs/finals/capd_proactive_stage9.json"))["measurement"]["cpu_affinity"][0])')"
perf stat -e cycles,instructions,task-clock -- \
  taskset -c "${CPU_AFFINITY}" /bin/true
```

如果看到 `perf_event_paranoid=4` 或 “No supported events found”，请由服务器管理员按安全策略授权，例如本次启动前临时执行 `sudo sysctl -w kernel.perf_event_paranoid=0`，或通过具备 `CAP_PERFMON` 等相应 capability 的 perf 环境运行。授权后必须先让上面的只读探针成功。不要把墙钟时间乘频率当 cycles，也不要把 `<not supported>` 写成已验证。脚本自己的前置探针失败不会创建 run 目录；若正式 run 已开始后失败，则必须换新 run ID。

## 5. 成功判据与产物

成功目录为 `outputs/capd_proactive_stage9/<run_id>/`。至少应包含：

- `verification.json`：`status=stage9_overhead_verified`、`stage10_entry_gate=satisfied`、`perf_cycles_verified=true`。
- `run_state.json`：同一 verified 状态，无 failure。
- `environment.json`：Linux、CPU 型号、逻辑/物理核、实际 affinity、线程、governor/turbo 可读值或明确 unavailable 原因。
- `raw_latency_samples.csv` 与两个 summary：可由原始样本重算一致。
- `quality_summary.json`：b_max 1/2/4 均有 18 个质量单元，其中 9 个有效 round、9 个零 round，并保留 weighted cost 与 Early-Reuse，purpose 为 analysis only。
- `perf/perf-stat.raw`、`perf_parsed.json`、`perf_scope_counts.json`：9 个有效 snapshot、9 个零 round job，cycles 来自 1800 个受控 round 的硬件 counter 区间，cycles/instructions/task-clock 均为 `ok`。
- `memory_breakdown.json`、`capacity_overhead.csv`、`artifacts/report_cn.md`。

若脚本在任一步失败，trap 会写 `stage9_not_verified` 和失败步骤。不要删除、覆盖或续跑该目录；换成 `stage9-overhead-r2` 等全新 run ID。只有完整新 run 可以进入验证。
