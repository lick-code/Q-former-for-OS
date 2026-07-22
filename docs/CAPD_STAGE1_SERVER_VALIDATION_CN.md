# CAPD 阶段1 R1 服务器验收说明

## 1. 当前状态与边界

当前阶段状态：`STAGE1_R1_IMPLEMENTED_UNVERIFIED`。

2026-07-20 的原阶段1 Linux 服务器验收覆盖 G01--G10，既有测试数量、退出码和仓库卫生证据继续有效。2026-07-22 的 `CAPD-MIC-1.0` 文档修订 R1 只新增 G13；本地已完成代码、测试和本交接文档的静态构造，但没有执行 Python、pytest、数据生成、Trace Replay、训练、推理或实验。

R1 不改变 `CAPD-MIC-1.0` 合同 ID、`capd_finals_v3_0` schema、配置、selector、标签、损失、JSONL、trace/split、manifest 或阶段2审计工件。阶段2保持 `VERIFIED_REUSABLE`。只有本文件全部服务器验收通过并回填证据后，阶段1才可更新为 `STAGE1_R1_VERIFIED`，随后才能进入阶段3。

G13 验收口径：

1. 只考虑冻结 snapshot 中 `candidate_mask=1` 的候选；
2. 使用完成全部正式分数修正后的 reranker score；
3. 最高分精确并列时只按 `original_pool_rank` 升序破并列；
4. 不读取 selector score、候选张量位置或当前请求插入后的 LRU；
5. padding 不得胜出；有效 NaN/正负 Inf、空有效 mask、非法 rank 和 shape 不一致必须硬失败；
6. v2.1/legacy 继续保留原行为。

## 2. 统一 Bash 环境与仓库外临时目录

以下命令必须在同一个 Bash 会话中执行。不要启用全局 `set -e`；下面的 `capd_run` 会记录命令自身的真实退出码并返回该退出码，但不会主动退出交互终端。

```bash
export REPO=/absolute/path/to/cache_replacement
cd "$REPO"

export CAPD_STAGE1_TMP="$(mktemp -d /tmp/capd-stage1-r1-XXXXXX)"
mkdir -p \
  "$CAPD_STAGE1_TMP/tmp" \
  "$CAPD_STAGE1_TMP/pycache" \
  "$CAPD_STAGE1_TMP/cache" \
  "$CAPD_STAGE1_TMP/torch" \
  "$CAPD_STAGE1_TMP/logs" \
  "$CAPD_STAGE1_TMP/status"

export TMPDIR="$CAPD_STAGE1_TMP/tmp"
export PYTHONPYCACHEPREFIX="$CAPD_STAGE1_TMP/pycache"
export XDG_CACHE_HOME="$CAPD_STAGE1_TMP/cache"
export TORCH_HOME="$CAPD_STAGE1_TMP/torch"
export CUDA_CACHE_PATH="$CAPD_STAGE1_TMP/cache/cuda"
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -p no:cacheprovider"
export PYTHONPATH="$REPO"

capd_run() {
  label="$1"
  shift
  log="$CAPD_STAGE1_TMP/logs/${label}.log"
  "$@" 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}
  printf '[CAPD][%s] exit_code=%d\n' "$label" "$rc" | tee -a "$log"
  return "$rc"
}

capd_status_snapshot() {
  label="$1"
  output="$2"
  log="$CAPD_STAGE1_TMP/logs/${label}.log"
  git status --porcelain=v1 > "$output"
  rc=$?
  cat "$output" | tee "$log"
  printf '[CAPD][%s] exit_code=%d\n' "$label" "$rc" | tee -a "$log"
  return "$rc"
}

printf '[CAPD] repo=%s\n' "$REPO"
printf '[CAPD] temp=%s\n' "$CAPD_STAGE1_TMP"
capd_status_snapshot \
  00_git_status_before \
  "$CAPD_STAGE1_TMP/status/git-status.before"
```

- 工作目录：`$REPO`。
- 环境要求：Linux Bash、Git、可写的 `/tmp`；后续需要 Python 3.10+、NumPy、PyTorch 和 pytest。
- 预期成功条件：打印的仓库路径正确；临时目录位于仓库外；`00_git_status_before` 打印真实退出码 0。
- 失败时重点检查：`REPO` 路径、`/tmp` 权限和磁盘空间。
- 临时文件：环境初始化、缓存目录、日志和初始状态快照全部位于 `$CAPD_STAGE1_TMP`。

## 3. 可直接复制执行的验收命令

### 3.1 Python 语法检查

```bash
cd "$REPO"
capd_run 01_py_compile python -m py_compile \
  qmap/finals_config.py \
  qmap/finals_generator.py \
  qmap/selector_search.py \
  qmap/candidate_filter.py \
  qmap/qmap_generator.py \
  qmap/qmap_train.py \
  qmap/qmap_eval.py \
  policy_learning/cache_model/embed.py \
  policy_learning/cache_model/model.py \
  policy_learning/cache_model/qmap_loss.py \
  tests/test_capd_stage1_v3_semantics.py \
  tests/test_capd_stage1_v3_model.py \
  tests/test_capd_stage1_v3_end_to_end.py \
  tests/test_generator_replay_feature_equivalence.py
```

- 工作目录：`$REPO`。
- 环境要求：Python 3.10+；不要求 GPU。
- 预期成功条件：`[CAPD][01_py_compile] exit_code=0`，无语法或缩进错误。
- 失败时重点检查：`qmap/qmap_eval.py` 的 helper/v3 分支和新增测试的多行参数。
- 临时文件：字节码只能写入 `$PYTHONPYCACHEPREFIX`；日志写入 `$CAPD_STAGE1_TMP/logs/01_py_compile.log`。

### 3.2 G13 针对性非 torch 测试

```bash
cd "$REPO"
capd_run 02_g13_non_torch python -m pytest -q \
  tests/test_capd_stage1_v3_semantics.py::V3RerankerVictimSelectionTest \
  tests/test_generator_replay_feature_equivalence.py::GeneratorReplayFeatureEquivalenceTest::test_same_state_produces_identical_snapshot
```

- 工作目录：`$REPO`。
- 环境要求：Python、pytest、NumPy；不应进入模型前向或训练。
- 预期成功条件：退出码 0；唯一最高分、精确并列按最小 rank、selector score 隔离、padding、NaN/Inf、非法 mask/rank/shape、selector TopK page ID 不变性和 generator/replay snapshot 等价全部通过。
- 失败时重点检查：`select_v3_reranker_victim`、`select_from_pool_records`、`build_filtered_candidate_snapshot`。
- 临时文件：仅 pytest 临时文件和日志，全部位于 `$CAPD_STAGE1_TMP`。

### 3.3 G13 针对性 torch 测试

```bash
cd "$REPO"
capd_run 03_g13_torch python -m pytest -q \
  tests/test_capd_stage1_v3_model.py::V3VictimSelectionTorchTest
```

- 工作目录：`$REPO`。
- 环境要求：可导入 PyTorch；CPU 足够。
- 预期成功条件：退出码 0；最终修正后的 torch 分数精确并列时选择 rank 0 页面，极高 padding 不胜出，torch NaN/正负 Inf 均硬失败。
- 失败时重点检查：tensor 的 `detach/cpu/tolist` 转换、分数修正后的调用顺序和有限性检查。
- 临时文件：PyTorch cache、pytest 临时文件和日志均位于 `$CAPD_STAGE1_TMP`；不生成 checkpoint。

### 3.4 原阶段1非 torch 语义回归

```bash
cd "$REPO"
capd_run 04_stage1_semantics python -m pytest -q \
  tests/test_capd_stage1_v3_semantics.py \
  tests/test_candidate_filter.py \
  tests/test_selector_weight_search.py \
  tests/test_decision_holdout.py \
  tests/test_dirty_accounting.py \
  tests/test_generator_replay_feature_equivalence.py \
  tests/test_checkpoint_config_contract.py
```

- 工作目录：`$REPO`。
- 环境要求：Python、NumPy、pytest。
- 预期成功条件：退出码 0；G01--G10 原语义继续通过，`SelectorRecall@K` 有效集口径、回放代价 35、工件硬失败和 snapshot 等价均保持不变。
- 失败时重点检查：先区分新增 G13 失败与原 G01--G10 回归；不得通过修改 selector、标签或工件字段规避失败。
- 临时文件：全部由 `$TMPDIR`、`$PYTHONPYCACHEPREFIX` 和日志目录承载。

### 3.5 原阶段1 torch 模型回归

```bash
cd "$REPO"
capd_run 05_stage1_model python -m pytest -q \
  tests/test_capd_stage1_v3_model.py \
  tests/test_qmap_cross_attention.py \
  tests/test_capd_cross_attention.py
```

- 工作目录：`$REPO`。
- 环境要求：PyTorch CPU 环境、pytest。
- 预期成功条件：退出码 0；共享页面嵌入、冻结词表/OOV、位置编码、padding mask、ApproxNDCG 和 G13 torch 测试全部通过。
- 失败时重点检查：模型 API、dtype/device、共享嵌入 state dict，以及 G13 helper 的 tensor 输入。
- 临时文件：仅仓库外 cache、pytest 临时文件和日志；不生成正式模型。

### 3.6 非平凡微型 E2E：完整合同链

```bash
cd "$REPO"
capd_run 06_e2e_contract env CAPD_RUN_STAGE1_E2E=1 \
  python -m pytest -q \
  tests/test_capd_stage1_v3_end_to_end.py::FinalsV3MiniEndToEndTest::test_mini_pipeline_contract_chain
```

- 工作目录：`$REPO`。
- 环境要求：PyTorch CPU 环境；可由 `sys.executable` 启动 generator/train/eval 子进程。
- 预期成功条件：退出码 0；440-access 冷热重访/写混合 trace 的 `trace -> selector -> JSONL -> 1 epoch -> replay -> result` 全链通过，selector 非 fallback、有效点大于 0、relevance range 非零、loss/梯度有限且梯度非零、至少一个参数改变。
- 失败时重点检查：v3 `QMAPPolicy.choose_victim` 接入、snapshot ranks/mask、工件身份和临时 trace 长度。
- 临时文件：三条 trace、selector、JSONL、checkpoint、result 和日志全部位于 `$CAPD_STAGE1_TMP`，不得复制到正式目录。

### 3.7 非平凡微型 E2E：两次固定种子确定性

```bash
cd "$REPO"
capd_run 07_e2e_determinism env CAPD_RUN_STAGE1_E2E=1 \
  python -m pytest -q \
  tests/test_capd_stage1_v3_end_to_end.py::FinalsV3MiniEndToEndTest::test_two_run_fixed_seed_determinism
```

- 工作目录：`$REPO`。
- 环境要求：与 3.6 相同，建议固定使用 CPU。
- 预期成功条件：退出码 0；两次运行的 train/valid JSONL、selector、三个模型组件 state dict 及回放计数/代价一致。
- 失败时重点检查：候选并列顺序、随机种子、DataLoader shuffle、词表拟合顺序和平台级确定性。
- 临时文件：两个完整运行目录及日志均位于 `$CAPD_STAGE1_TMP`。

### 3.8 `CAPD_RUN_STAGE1_E2E=0` 完整 pytest

```bash
cd "$REPO"
capd_run 08_full_pytest env CAPD_RUN_STAGE1_E2E=0 \
  python -m pytest -q
```

- 工作目录：`$REPO`。
- 环境要求：完整项目测试依赖；PyTorch 可导入。
- 预期成功条件：退出码 0；两个 server-only E2E 按环境变量预期 skip，其余测试无失败。
- 失败时重点检查：用 3.2--3.5 的日志定位；特别确认 v2.1/legacy 仍走原 `argmax` 分支。
- 临时文件：缓存、pytest 临时文件和日志全部位于 `$CAPD_STAGE1_TMP`。

### 3.9 Git 差异与工作区污染检查

```bash
cd "$REPO"
capd_run 09_git_diff_check git diff --check

capd_run 10_forbidden_path_status bash -c '
changes="$(git status --short -- \
  dataset outputs results logs configs scripts \
  qmap/candidate_filter.py qmap/finals_generator.py \
  qmap/selector_search.py qmap/qmap_train.py \
  policy_learning/cache_model \
  tests/test_capd_stage1_v3_end_to_end.py \
  docs/CAPD_STAGE2_CONFORMANCE_REPORT_CN.md \
  docs/CAPD_STAGE2_DATA_PROTOCOL_CN.md \
  docs/CAPD_STAGE2_SERVER_VALIDATION_CN.md)"
printf "%s" "$changes"
if [ -n "$changes" ]; then
  printf "\n"
  exit 1
fi
'

capd_status_snapshot \
  11_git_status_after \
  "$CAPD_STAGE1_TMP/status/git-status.after"

capd_run 12_worktree_pollution_diff diff -u \
  "$CAPD_STAGE1_TMP/status/git-status.before" \
  "$CAPD_STAGE1_TMP/status/git-status.after"

capd_run 13_review_target_diff git diff -- \
  qmap/qmap_eval.py \
  tests/test_capd_stage1_v3_semantics.py \
  tests/test_capd_stage1_v3_model.py \
  tests/test_capd_stage1_v3_end_to_end.py \
  tests/test_generator_replay_feature_equivalence.py \
  docs/CAPD_STAGE1_CONFORMANCE_REPORT_CN.md \
  docs/CAPD_STAGE1_SERVER_VALIDATION_CN.md
```

- 工作目录：`$REPO`。
- 环境要求：Git；不要求 Python。
- 预期成功条件：09、11、12、13 的真实退出码均为 0；10 无输出且退出码 0；测试前后 porcelain 状态完全一致；没有 dataset、outputs、results、logs、checkpoint、resolved config 或阶段2工件变化。
- 失败时重点检查：尾随空白、冲突标记、源码目录 `__pycache__`、pytest cache、E2E 输出路径和正式工件污染。若服务器基线本身有改动，必须以 00/11 的差异为准，不得 reset 或覆盖队友改动。
- 临时文件：状态快照和所有日志位于 `$CAPD_STAGE1_TMP`；Git 命令只读。

## 4. 验收结果回填规则

必须保存每个 `[CAPD][label] exit_code=...`、pytest 汇总数量、两个 E2E 结果、`git diff --check` 和工作区前后快照差异。任一组非零即保持 `STAGE1_R1_IMPLEMENTED_UNVERIFIED`，不得改写为 verified，也不得进入阶段3。

仅当 01--13 全部满足预期，才可：

1. 把阶段1符合性报告状态更新为 `STAGE1_R1_VERIFIED`；
2. 在报告中回填服务器环境、测试数量、每组真实退出码和仓库卫生证据；
3. 保持阶段2为 `VERIFIED_REUSABLE`，不重采、不重切、不重生成；
4. 解除阶段3启动门禁。

## 5. 原 G01--G10 与阶段2历史证据（继续有效）

2026-07-20 原阶段1服务器记录：目标语义测试 `16 passed`；非平凡微型 E2E `2 passed`；完整 pytest `64 passed, 2 skipped`；各组退出码 0；`git diff --check` 无错误。该记录只覆盖 G01--G10，不覆盖 G13。

阶段2随后完成独立服务器验收：3 个 workload、12 组工件、完整回归 `78 passed, 2 skipped`。R1 G13 不改变 trace、split、manifest、selector、JSONL、审计指纹或 schema，因此这些工件继续保持 `VERIFIED_REUSABLE`。

服务器临时目录确认不再需要后，只能人工核对 `CAPD_STAGE1_TMP` 的绝对路径确实位于仓库外 `/tmp/capd-stage1-r1-*`；本说明不提供自动删除命令，避免误删正式数据。
