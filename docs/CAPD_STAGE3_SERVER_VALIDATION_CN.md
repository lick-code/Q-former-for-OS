# CAPD 阶段3 Linux 服务器验收说明

本地开发阶段不执行以下命令。服务器仓库固定为 `REPO="$HOME/Q-former-for-OS"`。日志、Python cache、pytest cache、临时审计输出均放在仓库外的 `mktemp` 目录；脚本不使用全局 `set -e`，每组命令分别保存并打印真实退出码。

## 1. 可直接复制的完整命令

```bash
REPO="$HOME/Q-former-for-OS"
EVIDENCE="$(mktemp -d "${TMPDIR:-/tmp}/capd-stage3-acceptance.XXXXXX")"
export TMPDIR="$EVIDENCE/tmp"
export PYTHONPYCACHEPREFIX="$EVIDENCE/pycache"
export PYTEST_ADDOPTS="-p no:cacheprovider"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$PYTHONPYCACHEPREFIX" "$EVIDENCE/logs"
cd "$REPO" || exit 2

git status --porcelain --untracked-files=all \
  >"$EVIDENCE/worktree.before.status"
RC_PRESTATUS=$?
printf '[RC] worktree_pre_status=%s\n' "$RC_PRESTATUS"

find dataset/jsonl/finals_v3_official -type f -print0 \
  | sort -z | xargs -0 sha256sum >"$EVIDENCE/stage2.before.sha256"
RC_PREHASH=$?
printf '[RC] stage2_pre_hash=%s\n' "$RC_PREHASH"

python -m pytest -q tests/test_capd_stage3_selector.py \
  >"$EVIDENCE/logs/targeted.log" 2>&1
RC_TARGETED=$?
cat "$EVIDENCE/logs/targeted.log"
printf '[RC] targeted_stage3=%s\n' "$RC_TARGETED"

CAPD_RUN_STAGE1_E2E=0 python -m pytest -q \
  >"$EVIDENCE/logs/full_pytest.log" 2>&1
RC_FULL=$?
cat "$EVIDENCE/logs/full_pytest.log"
printf '[RC] full_pytest=%s\n' "$RC_FULL"

python scripts/run_capd_stage3_selector.py \
  --repo-root "$REPO" \
  --artifact-root dataset/jsonl/finals_v3_official \
  --workloads canneal streamcluster_pressure dedup_pressure \
  --pool-sizes 8 16 32 64 \
  --output "$EVIDENCE/audit-only-must-not-exist" \
  --audit-only >"$EVIDENCE/logs/input_audit.log" 2>&1
RC_AUDIT=$?
cat "$EVIDENCE/logs/input_audit.log"
printf '[RC] input_audit_12=%s\n' "$RC_AUDIT"

if [ "$RC_TARGETED" -eq 0 ] && [ "$RC_FULL" -eq 0 ] && [ "$RC_AUDIT" -eq 0 ]; then
  python scripts/run_capd_stage3_selector.py \
    --repo-root "$REPO" \
    --artifact-root dataset/jsonl/finals_v3_official \
    --workloads canneal streamcluster_pressure dedup_pressure \
    --pool-sizes 8 16 32 64 \
    --output outputs/results/finals_v3_official/stage3_selector \
    >"$EVIDENCE/logs/formal_analysis.log" 2>&1
  RC_FORMAL=$?
else
  RC_FORMAL=125
  printf '[SKIP] formal analysis blocked by a failed prerequisite\n' \
    >"$EVIDENCE/logs/formal_analysis.log"
fi
cat "$EVIDENCE/logs/formal_analysis.log"
printf '[RC] formal_stage3=%s\n' "$RC_FORMAL"

git diff --check >"$EVIDENCE/logs/diff_check.log" 2>&1
RC_DIFF=$?
cat "$EVIDENCE/logs/diff_check.log"
printf '[RC] git_diff_check=%s\n' "$RC_DIFF"

find dataset/jsonl/finals_v3_official -type f -print0 \
  | sort -z | xargs -0 sha256sum >"$EVIDENCE/stage2.after.sha256"
RC_POSTHASH=$?
cmp -s "$EVIDENCE/stage2.before.sha256" "$EVIDENCE/stage2.after.sha256"
RC_STAGE2_UNCHANGED=$?
printf '[RC] stage2_post_hash=%s\n' "$RC_POSTHASH"
printf '[RC] stage2_artifacts_unchanged=%s\n' "$RC_STAGE2_UNCHANGED"

git status --porcelain --untracked-files=all \
  | grep -v '^?? outputs/results/finals_v3_official/stage3_selector/' \
  >"$EVIDENCE/worktree.after.filtered.status"
cmp -s "$EVIDENCE/worktree.before.status" \
  "$EVIDENCE/worktree.after.filtered.status"
RC_POLLUTION=$?
diff -u "$EVIDENCE/worktree.before.status" \
  "$EVIDENCE/worktree.after.filtered.status" \
  >"$EVIDENCE/logs/unexpected_worktree_changes.log" 2>&1
cat "$EVIDENCE/logs/unexpected_worktree_changes.log"
printf '[RC] unexpected_worktree_pollution=%s\n' "$RC_POLLUTION"

find outputs/checkpoints/finals_v3_official -type f -print \
  >"$EVIDENCE/logs/checkpoint_files.log" 2>/dev/null
if [ -s "$EVIDENCE/logs/checkpoint_files.log" ]; then
  RC_CHECKPOINT=1
else
  RC_CHECKPOINT=0
fi
cat "$EVIDENCE/logs/checkpoint_files.log"
printf '[RC] unexpected_checkpoint=%s\n' "$RC_CHECKPOINT"

printf '%s\n' \
  "$RC_PRESTATUS" "$RC_PREHASH" "$RC_TARGETED" "$RC_FULL" \
  "$RC_AUDIT" "$RC_FORMAL" \
  "$RC_DIFF" "$RC_POSTHASH" "$RC_STAGE2_UNCHANGED" \
  "$RC_POLLUTION" "$RC_CHECKPOINT" \
  >"$EVIDENCE/exit_codes.txt"
if awk '$1 != 0 { bad=1 } END { exit bad }' "$EVIDENCE/exit_codes.txt"; then
  RC_ALL=0
  printf '[FINAL] STAGE3_VERIFIED\n'
else
  RC_ALL=1
  printf '[FINAL] STAGE3_NOT_VERIFIED\n'
fi
printf '[RC] overall=%s\n' "$RC_ALL"
printf '[INFO] evidence=%s\n' "$EVIDENCE"
```

## 2. 验收判定

只有以下条件全部成立，才能人工把状态从 `STAGE3_IMPLEMENTED_UNVERIFIED` 更新为 `STAGE3_VERIFIED`：

- 针对性测试退出码0；
- 完整 pytest 退出码0；
- 12/12 输入只读审计通过；
- 12/12 Full 重搜与冻结 selector 完全一致；
- 60个 single-feature 与60个 leave-one-out 结果（共120个）全部生成；
- 三组 B=8 机械性不变量全部通过；
- 输出身份、指纹链、分母和 metric source 审计通过；
- `git diff --check` 通过；
- 阶段2目录前后 SHA-256 清单完全一致；
- 除规定的阶段3结果外无工作区污染，无 checkpoint、训练日志或 test replay 结果。

若任一退出码非0，保留 `$EVIDENCE` 原始日志和结果，不手工修改输出来制造通过。
