# CAPD 阶段2 Linux 服务器验收说明

## 1. 状态与边界

执行前状态必须为 `IMPLEMENTED_UNVERIFIED`。以下命令只验收正式数据、机械性 selector 样本和 reranker JSONL；不训练精排模型，不运行 QMAP 正式测试，不执行性能比较，不把 selector 数值解释为阶段3结论。

命令固定使用 `REPO="$HOME/Q-former-for-OS"`，不使用 `set -e`，每组命令单独记录退出码并继续保留交互终端。日志、pytest cache、pycache 与 resolved config 均写入仓库外 `mktemp` 目录。正式 source spec、manifest、审计报告和工件审计报告属于可复核交付物；大 trace 和 JSONL 位于已隔离/忽略的 v3 official 目录。

## 2. 初始化与安全执行函数

整段复制：

```bash
REPO="$HOME/Q-former-for-OS"
CAPD_STAGE2_TMP="$(mktemp -d -t capd-stage2-v3-XXXXXX 2>/dev/null)"
CAPD_STAGE2_READY=0

if [ -n "$CAPD_STAGE2_TMP" ]; then
  mkdir -p "$CAPD_STAGE2_TMP/logs" "$CAPD_STAGE2_TMP/rc" \
    "$CAPD_STAGE2_TMP/resolved" "$CAPD_STAGE2_TMP/pycache"
  printf '[INFO] temporary evidence: %s\n' "$CAPD_STAGE2_TMP"
else
  printf '[FAIL] mktemp failed; later command groups will be skipped.\n'
fi

if [ -d "$REPO/.git" ] && [ -n "$CAPD_STAGE2_TMP" ]; then
  cd "$REPO" || printf '[FAIL] cannot cd to %s\n' "$REPO"
  if [ "$(pwd -P)" = "$(cd "$REPO" 2>/dev/null && pwd -P)" ]; then
    CAPD_STAGE2_READY=1
    git status --short >"$CAPD_STAGE2_TMP/status.before.txt" 2>&1
    printf '[OK] repository: %s\n' "$(pwd -P)"
  fi
else
  printf '[FAIL] repository not found: %s\n' "$REPO"
fi

run_logged() {
  capd_name="$1"
  shift
  if [ "$CAPD_STAGE2_READY" -ne 1 ]; then
    printf '[SKIP] %s: initialization is not ready\n' "$capd_name"
    return 0
  fi
  "$@" >"$CAPD_STAGE2_TMP/logs/$capd_name.log" 2>&1
  capd_rc=$?
  printf '%s\n' "$capd_rc" >"$CAPD_STAGE2_TMP/rc/$capd_name.rc"
  printf '[RC=%s] %s (log: %s)\n' \
    "$capd_rc" "$capd_name" "$CAPD_STAGE2_TMP/logs/$capd_name.log"
  return 0
}
```

预期：打印仓库绝对路径和临时证据目录。失败处理：修正仓库路径或 `/tmp` 权限后重建一个新终端会话；不要在错误目录继续，也不要删除当前临时目录。

## 3. 环境预检

```bash
run_logged env_git git --version
run_logged env_python python --version
run_logged env_imports env PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
  python -c 'import json, numpy, pytest, torch; from qmap import finals_config, finals_data; print("imports_ok")'
run_logged env_commit git rev-parse HEAD
run_logged env_diff_check git diff --check

for capd_name in env_git env_python env_imports env_commit env_diff_check; do
  if [ -f "$CAPD_STAGE2_TMP/rc/$capd_name.rc" ]; then
    printf '%s rc=%s\n' "$capd_name" "$(cat "$CAPD_STAGE2_TMP/rc/$capd_name.rc")"
  fi
done
```

预期：五项均为 `rc=0`，import 日志含 `imports_ok`。数据审计/生成本身不调用精排训练，但完整回归需要现有 PyTorch 测试环境。失败处理：先修环境或代码差异，再从本节重跑；不得用跳过测试或降低 profile 代替修复。

## 4. 数据 inventory 与旧工件边界

```bash
run_logged inventory_metadata find dataset/metadata -maxdepth 4 -type f -print
run_logged inventory_processed find dataset/processed -maxdepth 5 -type f -print
run_logged inventory_raw find dataset/raw_traces -maxdepth 5 -type f -print
run_logged inventory_v2_tracked git ls-files \
  dataset/jsonl/finals_v2_decision_holdout \
  outputs/checkpoints/finals_v2_decision_holdout \
  outputs/results/finals_v2_decision_holdout
run_logged inventory_candidate cat configs/finals/capd_stage2_candidate_inventory.json
run_logged inventory_profile cat configs/finals/capd_stage2_data_profile.json
```

预期：inventory 只做清点，不产生文件。`canneal` 与 `dedup_pressure` 的 legacy 数据仍是 `REJECTED`，`streamcluster_pressure` 仍是 `INSUFFICIENT`，除非已有新的正式来源证据和审计。失败处理：缺文件先查采集/同步过程；禁止从 v2 JSONL、selector、checkpoint 或 result 反向恢复 v3 数据。

## 5. 来源准备的人工门禁

每个 workload 必须先得到真实 source spec：

```text
dataset/metadata/finals_v3_source_specs/canneal.json
dataset/metadata/finals_v3_source_specs/streamcluster_pressure.json
dataset/metadata/finals_v3_source_specs/dedup_pressure.json
```

source spec 必须由实际采集记录填写，不能从文件名猜测 `collection_id`、采集命令或时间。重新采集时可复用 `scripts/collect_trace_drmemtrace.py` 和 `scripts/convert_drmemtrace_view.py`；前者的完整 argv、DynamoRIO 版本、目标 workload argv、采集时间和环境必须作为 provenance 保存。旧 `prepare_pressure_split.py` 允许 RW fallback，不能单独作为 official 证据。

得到真实源 trace 和明确区间后，先查看两个入口的完整参数合同；下列命令可直接复制，不含占位路径：

```bash
run_logged source_split_help python scripts/split_finals_v3_trace.py --help
run_logged source_spec_help python scripts/create_finals_v3_source_spec.py --help
```

随后按本次真实记录填写参数：split 入口需要真实源 CSV、official workload 输出目录和三个整数半开区间；spec 入口需要同一组路径/区间及真实 collection ID、工具版本、完整命令、时间、环境和切分策略。由于这些值本身是待验收证据，本文件不会用占位值替用户伪造一条可运行命令。实际自动验收块从已完成的 source spec 开始，并对缺失项安全标记 `BLOCKED`，不会退出终端：

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  mkdir -p dataset/metadata/finals_v3_official/reports \
    dataset/metadata/finals_v3_official/artifact_audits
  CAPD_STAGE2_COMMIT="$(git rev-parse HEAD 2>/dev/null)"
  printf '%s\n' "$CAPD_STAGE2_COMMIT" >"$CAPD_STAGE2_TMP/commit.txt"
  for workload in canneal streamcluster_pressure dedup_pressure; do
    spec="dataset/metadata/finals_v3_source_specs/$workload.json"
    if [ -f "$spec" ]; then
      printf '[READY] %s source spec: %s\n' "$workload" "$spec"
    else
      printf '[BLOCKED] %s: missing truthful source spec %s\n' "$workload" "$spec"
    fi
  done
fi
```

预期：三个 workload 均显示 `READY` 才能继续完整验收。失败处理：对 `REJECTED` 数据重新选择/采集，对缺 provenance 的数据补真实记录；不得伪造 source spec，也不得降低阈值。

## 6. manifest 构造与来源区间验证

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  for workload in canneal streamcluster_pressure dedup_pressure; do
    spec="dataset/metadata/finals_v3_source_specs/$workload.json"
    manifest="dataset/metadata/finals_v3_official/$workload.json"
    if [ -f "$spec" ]; then
      run_logged "manifest_$workload" env \
        PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
        python scripts/build_finals_v3_manifest.py \
        --spec "$spec" --output "$manifest" \
        --git-commit "$CAPD_STAGE2_COMMIT" --repo-root "$REPO"
    else
      printf '[SKIP] manifest_%s: source spec missing\n' "$workload"
    fi
  done
fi
```

预期：每个 `manifest_*` 为 `rc=0`，日志给出 manifest 文件和 SHA-256；构造器会逐记录验证 split 等于源区间。失败处理：按错误修正 RW、区间、记录数、路径或指纹；不要手改 manifest 哈希，也不要继续审计失败 workload。

## 7. 合成测试

```bash
run_logged stage2_synthetic_tests env \
  PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
  python -m pytest -q -p no:cacheprovider tests/test_capd_stage2_data.py
run_logged stage2_regression env \
  CAPD_RUN_STAGE1_E2E=0 \
  PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
  python -m pytest -q -p no:cacheprovider
```

预期：两项均为 `rc=0`；新增阶段2测试通过，完整回归只保留受 `CAPD_RUN_STAGE1_E2E=0` 控制的预期 server-only E2E skip。失败处理：查看日志、修复实现并重跑对应测试及完整回归；不要改测试期望以迁就真实 bug。本节不运行正式训练或正式实验。

## 8. official 数据质量审计与 manifest 封存

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  for workload in canneal streamcluster_pressure dedup_pressure; do
    manifest="dataset/metadata/finals_v3_official/$workload.json"
    report="dataset/metadata/finals_v3_official/reports/$workload.json"
    if [ -f "$manifest" ]; then
      run_logged "audit_$workload" env \
        PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
        python scripts/audit_finals_v3_data.py \
        --manifest "$manifest" \
        --config configs/finals/capd_direction1_v3.json \
        --profile configs/finals/capd_stage2_data_profile.json \
        --output "$report" --update-manifest --repo-root "$REPO"
    else
      printf '[SKIP] audit_%s: manifest missing\n' "$workload"
    fi
  done
fi
```

预期：`PASSED` 返回 `rc=0`；`INSUFFICIENT` 返回 `rc=2`；硬约束 `REJECTED` 返回 `rc=3`；报告或 manifest 无法安全封存返回 `rc=4`。前三种状态会写报告并在 manifest 有效时封存，便于诊断。失败处理：只有 `rc=0` 的 workload 可进入生成；`rc=2/3` 必须重新选择/采集/切分，`rc=4` 必须修复封存链，再从 manifest 构造重跑；不得降 profile。

封存后复核报告、manifest、trace 和 profile 指纹链：

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  for workload in canneal streamcluster_pressure dedup_pressure; do
    manifest="dataset/metadata/finals_v3_official/$workload.json"
    if [ -f "$manifest" ]; then
      run_logged "sealed_$workload" env \
        PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
        python -c 'import os,sys; sys.path.insert(0, os.getcwd()); from qmap import finals_data; m=sys.argv[1]; w=sys.argv[2]; finals_data.load_source_manifest(m, os.getcwd(), verify_files=True, require_quality_pass=True, expected_workload=w); print("sealed_manifest_ok")' \
        "$manifest" "$workload"
    fi
  done
fi
```

预期：只有审计 `PASSED` 的 workload 得到 `rc=0` 和 `sealed_manifest_ok`。其他状态在此硬失败是正确门禁。

## 9. resolved config、机械性 selector 与 JSONL 生成

只对报告状态为 `PASSED` 的 workload 执行。B=8/16/32/64 分别生成隔离数据，是为阶段3准备输入，不在本阶段比较任何 selector 数值。

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  for workload in canneal streamcluster_pressure dedup_pressure; do
    report="dataset/metadata/finals_v3_official/reports/$workload.json"
    status="MISSING"
    if [ -f "$report" ]; then
      status="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", "MISSING"))' "$report" 2>/dev/null)"
    fi
    if [ "$status" != "PASSED" ]; then
      printf '[SKIP] generate_%s: audit status=%s\n' "$workload" "$status"
      continue
    fi
    for B in 8 16 32 64; do
      resolved="$CAPD_STAGE2_TMP/resolved/${workload}_B${B}.json"
      outdir="dataset/jsonl/finals_v3_official/$workload/B$B"
      run_logged "resolve_${workload}_B${B}" env \
        PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
        python scripts/resolve_finals_config.py \
        --base-config configs/finals/capd_direction1_v3.json \
        --workload "$workload" --pool-size-B "$B" --output "$resolved"
      resolve_rc="$(cat "$CAPD_STAGE2_TMP/rc/resolve_${workload}_B${B}.rc" 2>/dev/null)"
      if [ "$resolve_rc" = "0" ]; then
        run_logged "generate_${workload}_B${B}" env \
          PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
          python -m qmap.finals_generator \
          --config "$resolved" \
          --selector-output "$outdir/selector_params.json" \
          --validation-samples-output "$outdir/selector_validation_samples.jsonl" \
          --train-output "$outdir/train.jsonl" \
          --valid-output "$outdir/valid.jsonl" \
          --summary-output "$outdir/generator_summary.json"
      else
        printf '[SKIP] generate_%s_B%s: resolve failed\n' "$workload" "$B"
      fi
    done
  done
fi
```

预期：每个 resolve/generate 均为 `rc=0`；valid trace 独立，所有样本满足 `t+L<N`，输出只进入 `dataset/jsonl/finals_v3_official`。失败处理：检查对应日志和上游指纹链；禁止改用 v2 selector/JSONL，禁止以 smoke fallback 继续。

## 10. 工件指纹复核

```bash
if [ "$CAPD_STAGE2_READY" -eq 1 ]; then
  for workload in canneal streamcluster_pressure dedup_pressure; do
    for B in 8 16 32 64; do
      resolved="$CAPD_STAGE2_TMP/resolved/${workload}_B${B}.json"
      outdir="dataset/jsonl/finals_v3_official/$workload/B$B"
      audit="dataset/metadata/finals_v3_official/artifact_audits/${workload}_B${B}.json"
      if [ -f "$resolved" ] && [ -f "$outdir/generator_summary.json" ]; then
        run_logged "artifact_${workload}_B${B}" env \
          PYTHONPYCACHEPREFIX="$CAPD_STAGE2_TMP/pycache" \
          python scripts/verify_finals_v3_artifacts.py \
          --config "$resolved" \
          --selector "$outdir/selector_params.json" \
          --validation-samples "$outdir/selector_validation_samples.jsonl" \
          --train-jsonl "$outdir/train.jsonl" \
          --valid-jsonl "$outdir/valid.jsonl" \
          --summary "$outdir/generator_summary.json" \
          --output "$audit"
      else
        printf '[SKIP] artifact_%s_B%s: generation incomplete\n' "$workload" "$B"
      fi
    done
  done
fi
```

预期：所有目标为 `rc=0`，工件审计状态 `PASSED`，JSONL 行数、schema、metadata、selector、manifest、split、profile 和报告指纹一致。失败处理：任何不一致都应从上游重建；不得手工改哈希或 metadata。

## 11. Git 污染与阶段边界复核

```bash
run_logged final_diff_check git diff --check
run_logged final_status git status --short
run_logged final_v2_status git status --short -- \
  dataset/jsonl/finals_v2_decision_holdout \
  outputs/checkpoints/finals_v2_decision_holdout \
  outputs/results/finals_v2_decision_holdout
run_logged final_v2_diff git diff --name-only -- \
  dataset/jsonl/finals_v2_decision_holdout \
  outputs/checkpoints/finals_v2_decision_holdout \
  outputs/results/finals_v2_decision_holdout
run_logged final_ignored git check-ignore -v \
  dataset/processed/finals_v3_official \
  dataset/jsonl/finals_v3_official
run_logged final_no_training sh -c \
  'for d in outputs/checkpoints/finals_v3_official outputs/results/finals_v3_official; do if [ -d "$d" ]; then find "$d" -type f -print; fi; done'

printf '[INFO] status before:\n'
if [ -f "$CAPD_STAGE2_TMP/status.before.txt" ]; then
  cat "$CAPD_STAGE2_TMP/status.before.txt"
fi
printf '[INFO] evidence retained at %s\n' "$CAPD_STAGE2_TMP"
```

预期：`final_diff_check rc=0`；v2 status/diff 日志为空；正式大 trace 与 JSONL 被正确忽略；本阶段没有新增 checkpoint 或 result 文件。`final_status` 可出现预期的 source spec、manifest、数据审计和工件审计，以及本次代码/文档修改。失败处理：先区分正式证据与意外 cache/日志/训练工件；不要运行自动递归删除，人工核对绝对路径后再处理。

## 12. 状态转换

只有以下全部成立才可把阶段2报告从 `IMPLEMENTED_UNVERIFIED` 人工更新为 `VERIFIED`：

- 环境、合成测试、完整回归和 `git diff --check` 全部 `rc=0`；
- official 配置中的每个 workload 都有真实 source spec、`PASSED` manifest 和审计报告；
- 四个 B 的生成与工件复核全部 `rc=0`；
- v2 路径无修改，未产生训练 checkpoint 或正式 result；
- 日志中没有被忽略的 `BLOCKED`、`SKIP`、`INSUFFICIENT` 或 `REJECTED` workload。

若任一项未满足，保持 `IMPLEMENTED_UNVERIFIED`。服务器证据目录暂不自动删除；确认不再需要后，只能人工核对其绝对路径确实匹配 `/tmp/capd-stage2-v3-*` 再处理。
