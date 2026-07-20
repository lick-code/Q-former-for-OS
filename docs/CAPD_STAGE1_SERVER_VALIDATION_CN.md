# CAPD 阶段1服务器验收说明

## 1. 当前状态与边界

最终阶段状态：`STAGE1_VERIFIED`。

本文件中的命令仅供以后在具备 Python/PyTorch 环境的服务器执行。本地未执行任何语法检查、单元测试、数据生成、Trace Replay、训练、推理、网格搜索、smoke test 或端到端实验。

服务器验收仍只验证 `CAPD-MIC-1.0` 的阶段1实现一致性，不得把结果解释为方法性能结论，也不得把测试产生的临时工件复制到 `dataset/`、`outputs/`、`results/`、`logs/` 或正式 checkpoint 目录。

## 2. 统一环境与临时目录

- 工作目录：服务器上的 `cache_replacement` 仓库根目录。
- 环境要求：Linux shell；Git；Python 3.10 或以上；与 `requirements.txt` 兼容的 NumPy、PyTorch、pytest；CPU 即可完成语义测试，微型端到端回归建议至少 8 GB 可用内存。
- 临时目录：所有缓存和端到端工件必须放在仓库外的 `CAPD_STAGE1_TMP`。

```bash
export REPO=/absolute/path/to/cache_replacement
cd "$REPO"
export CAPD_STAGE1_TMP="$(mktemp -d /tmp/capd-stage1-v3-XXXXXX)"
mkdir -p "$CAPD_STAGE1_TMP/tmp" "$CAPD_STAGE1_TMP/pycache"
export TMPDIR="$CAPD_STAGE1_TMP/tmp"
export PYTHONPYCACHEPREFIX="$CAPD_STAGE1_TMP/pycache"
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -p no:cacheprovider"
export PYTHONPATH="$REPO"
```

预期成功条件：`pwd` 指向仓库根目录，`CAPD_STAGE1_TMP` 位于 `/tmp` 等仓库外临时位置，pytest cache provider 已禁用。失败时重点检查目录权限、磁盘空间和环境变量引用。该步骤会创建临时目录；不会修改正式数据。

## 3. 验收命令

### 3.1 Python 语法检查

```bash
cd "$REPO"
python -m py_compile \
  qmap/finals_config.py \
  qmap/finals_generator.py \
  qmap/selector_search.py \
  qmap/candidate_filter.py \
  qmap/qmap_generator.py \
  qmap/qmap_train.py \
  qmap/qmap_eval.py \
  qmap/learned_baselines.py \
  policy_learning/cache_model/embed.py \
  policy_learning/cache_model/model.py \
  policy_learning/cache_model/qmap_loss.py \
  scripts/run_finals_v2.py \
  scripts/run_finals_v3.py \
  tests/test_capd_stage1_v3_semantics.py \
  tests/test_capd_stage1_v3_model.py \
  tests/test_capd_stage1_v3_end_to_end.py
```

- 工作目录：`$REPO`。
- 环境要求：Python 可执行；不要求 GPU。
- 预期成功条件：退出码为 0，无 `SyntaxError` 或 `IndentationError`。
- 失败时重点检查：上述报错文件和行号，尤其是 v3 分支、字典字段及多行条件表达式。
- 临时文件：字节码只能写入 `$PYTHONPYCACHEPREFIX`；不得在源码目录生成 `__pycache__`。

### 3.2 非 torch 单元测试

```bash
cd "$REPO"
python -m pytest -q \
  tests/test_capd_stage1_v3_semantics.py \
  tests/test_candidate_filter.py \
  tests/test_selector_weight_search.py \
  tests/test_decision_holdout.py \
  tests/test_dirty_accounting.py \
  tests/test_generator_replay_feature_equivalence.py \
  tests/test_checkpoint_config_contract.py
```

- 工作目录：`$REPO`。
- 环境要求：Python、NumPy、pytest；该组不应进入 torch 训练或模型前向路径。
- 预期成功条件：退出码为 0，所有收集到的测试通过；混合有效/无区分样本的 `SelectorRecall@K` 必须为 0.0 而非 0.5；不得出现把 v3 official 工件当作 holdout/smoke 工件接受的情况。
- 失败时重点检查：`qmap/finals_config.py`、`qmap/finals_generator.py`、`qmap/selector_search.py`、`qmap/candidate_filter.py`、`qmap/qmap_eval.py`。
- 临时文件：pytest 临时文件由 `$TMPDIR` 承载；测试中的 trace/JSONL 均使用 `tempfile.TemporaryDirectory()`，不得指定到正式目录。

### 3.3 torch 模型、共享嵌入、位置编码与 ApproxNDCG

```bash
cd "$REPO"
python -m pytest -q \
  tests/test_capd_stage1_v3_model.py \
  tests/test_qmap_cross_attention.py \
  tests/test_capd_cross_attention.py
```

- 工作目录：`$REPO`。
- 环境要求：可导入 PyTorch；CPU 可用；不要求 CUDA。
- 预期成功条件：共享页面词表/嵌入、冻结/OOV、正弦位置编码、history padding mask、ApproxNDCG 对角线与候选 padding 的数值断言全部通过。
- 失败时重点检查：`policy_learning/cache_model/embed.py`、`policy_learning/cache_model/model.py`、`policy_learning/cache_model/qmap_loss.py`、`qmap/qmap_train.py`。
- 临时文件：仅 pytest 临时 JSONL 和 `$PYTHONPYCACHEPREFIX`；不生成 checkpoint。

### 3.4 完整 pytest

```bash
cd "$REPO"
CAPD_RUN_STAGE1_E2E=0 python -m pytest -q
```

- 工作目录：`$REPO`。
- 环境要求：完整 `requirements.txt` 环境；PyTorch 可导入。
- 预期成功条件：退出码为 0；server-only 端到端用例因环境变量为 0 而明确 skip，其余测试无失败。
- 失败时重点检查：先按 3.2/3.3 缩小范围；同时检查是否有旧 v2.1 测试仍错误引用 v3 常量。
- 临时文件：由 `$TMPDIR` 和 `$PYTHONPYCACHEPREFIX` 承载；不得让测试输出落入正式目录。

### 3.5 微型合成 trace 端到端回归

```bash
cd "$REPO"
CAPD_RUN_STAGE1_E2E=1 python -m pytest -q \
  tests/test_capd_stage1_v3_end_to_end.py::FinalsV3MiniEndToEndTest::test_mini_pipeline_contract_chain
```

- 工作目录：`$REPO`。
- 环境要求：PyTorch CPU 环境；pytest；可通过 `sys.executable` 启动 `qmap.finals_generator`、`qmap.qmap_train` 和 `qmap.qmap_eval`。
- 预期成功条件：临时 `train/valid/test trace -> selector -> v3 JSONL -> 1 epoch train -> QMAP replay -> result audit` 全链路退出码为 0；result 为 `capd_finals_v3_0`、`CAPD-MIC-1.0`、`official`；selector 的 `fallback_uniform=false`、有效决策点大于 0，验证数据存在非零 relevance range；受控优化步的 loss/梯度有限、梯度非零且至少一个参数改变。
- 失败时重点检查：generator 的完整未来窗口过滤、selector 指纹、JSONL 元数据、冻结词表、checkpoint 身份、test result 身份及临时 trace 长度。
- 临时文件：测试用 3 条 440-access 冷热重访/写混合 trace、selector、JSONL、checkpoint 和 result 全部位于 pytest 的 `$TMPDIR` 子目录；测试结束自动删除。不得把路径改为 `dataset/` 或 `outputs/`。

### 3.6 两次固定种子确定性检查

```bash
cd "$REPO"
CAPD_RUN_STAGE1_E2E=1 python -m pytest -q \
  tests/test_capd_stage1_v3_end_to_end.py::FinalsV3MiniEndToEndTest::test_two_run_fixed_seed_determinism
```

- 工作目录：`$REPO`。
- 环境要求：与 3.5 相同；在 CPU 上执行以减少平台级非确定性。
- 预期成功条件：两次运行的 train/valid JSONL 指纹、selector 指纹、`feature_embedder/extractor/scorer` state dict 逐项相同；访问计数、迁移、NVM 读写和加权总代价相同。
- 失败时重点检查：随机种子设置、DataLoader shuffle、候选排序 tie-break、词表拟合顺序、PyTorch 确定性设置和平台版本差异。若仅浮点差异，应先定位差异张量，不得直接放宽为“任意接近”。
- 临时文件：两个完整运行目录均位于 `$TMPDIR`，测试结束自动删除。

### 3.7 工件指纹和 schema 拒绝测试

```bash
cd "$REPO"
python -m pytest -q \
  tests/test_capd_stage1_v3_semantics.py::ArtifactIdentityTest \
  tests/test_capd_stage1_v3_model.py::V3JsonlSchemaTest
```

- 工作目录：`$REPO`。
- 环境要求：Python、pytest、PyTorch（第二个测试文件需要导入）。
- 预期成功条件：workload、合同、配置、selector、JSONL、checkpoint、result 任一不匹配均抛出硬错误；v3 拒绝 `physical_address`；v2.1 与 v3 双向不兼容。
- 失败时重点检查：`artifact_identity_from_config`、`validate_artifact_identity`、`selector_fingerprint`、`load_jsonl_metadata`、`validate_checkpoint_config_contract`、`validate_result_contract` 和 `QMAPAccessSequenceDataset._validate_sample`。
- 临时文件：仅临时 JSONL/metadata；使用 `$TMPDIR`，不会生成正式工件。

### 3.8 Git diff 与污染检查

```bash
cd "$REPO"
git status --short
git diff --check
git diff -- \
  qmap policy_learning/cache_model configs/finals scripts tests docs
```

- 工作目录：`$REPO`。
- 环境要求：Git；不要求 Python。
- 预期成功条件：`git diff --check` 退出码为 0；没有 `dataset/`、`outputs/`、`results/`、`logs/`、checkpoint 或 resolved_v3 工件变更；旧 `configs/finals/resolved*` 未被改写。
- 失败时重点检查：尾随空白、冲突标记、意外生成工件、源码目录中的 `__pycache__` 和旧 v2.1 工件修改。
- 临时文件：无。该组命令只读。

## 4. 验收完成后的状态转换记录

2026-07-20 已完成服务器验收并由阶段报告回填状态。记录如下：

- selector 有效集合：`SelectorRecall@K=0.0`、`effective_decision_points=1`、`nondiscriminative_ratio=0.5`、`fallback_uniform=false`；
- 目标语义测试：`16 passed`，退出码 0；
- 强化后的非平凡微型 E2E：`2 passed`，退出码 0；
- 完整 pytest：`64 passed, 2 skipped`，退出码 0；两个 skip 是 `CAPD_RUN_STAGE1_E2E=0` 下的预期 server-only E2E；
- `git diff --check`：无错误；
- 仓库卫生：`.capd_stage1_tmp/logs/semantics.log` 已不再受跟踪，`.capd_stage1_tmp/` 已进入 `.gitignore`。

状态由 `IMPLEMENTED_UNVERIFIED` 转换为 `STAGE1_VERIFIED`。该转换只确认阶段1语义与实现门禁，不确认正式数据、正式实验或性能结论；阶段2仍必须从 `IMPLEMENTED_UNVERIFIED` 开始并单独验收。

服务器临时目录确认不再需要后，可在人工核对绝对路径确实指向仓库外 `/tmp/capd-stage1-v3-*` 后删除；删除操作不应写入自动化脚本，避免误删正式数据。
