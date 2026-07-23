# CAPD 阶段5 Linux服务器验收

当前状态：`STAGE5_IMPLEMENTED_UNVERIFIED`

## 1. 完整入口

```bash
cd "$HOME/Q-former-for-OS"
bash scripts/validate_capd_stage5_server.sh --plan
bash scripts/validate_capd_stage5_server.sh
```

`--plan`/`--dry-run`只审计输入、运行测试并列出完整矩阵，不运行正式训练或回放。完整命令依次执行输入审计、阶段5针对性pytest、完整pytest、临时目录mini E2E、计划审计、主实验、学习基线公平性、核心消融、敏感性、汇总、来源与污染检查及 `git diff --check`。

## 2. 单阶段与单job续跑

```bash
python3 scripts/run_capd_stage5.py --stage audit-inputs
python3 scripts/run_capd_stage5.py --stage plan
python3 scripts/run_capd_stage5.py --stage main --execute
python3 scripts/run_capd_stage5.py --stage ablations --job-id \
  ablation:train:no_position_encoding:canneal:3136859
python3 scripts/run_capd_stage5.py --stage sensitivity --execute
python3 scripts/run_capd_stage5.py --stage summarize
```

不带 `--execute` 或 `--job-id` 时，正式实验阶段只显示计划。已完成job仅在原子manifest状态、job fingerprint和非空目标输出全部一致时复用；失败job不自动重试。部分checkpoint、空目录、指纹不一致或依赖未完成均硬失败。

## 3. 资源与隔离

- `REPO="${REPO:-$HOME/Q-former-for-OS}"`；
- 日志、pytest cache、pycache及临时E2E证据位于仓库外 `mktemp`；
- 正式JSONL/checkpoint/result只写阶段5隔离目录；
- shell脚本不使用全局 `set -e`，每组命令记录起止时间、完整命令、日志和真实退出码；
- 默认单GPU顺序训练，禁止两个进程写相同variant/workload/seed目录；
- test replay只在对应checkpoint及其manifest完成后运行；
- 汇总前必须完成全部348个required jobs。

## 4. 最终门禁

只有针对性测试、完整pytest、mini E2E、27个主回放、全部三seed核心消融、完整single-seed敏感性网格、学习基线纳入或排除说明、G11边界披露、工件指纹链、污染检查及diff检查全部通过，脚本才打印：

```text
[FINAL] STAGE5_VERIFIED
```

任一失败打印：

```text
[FINAL] STAGE5_NOT_VERIFIED
```

验收过程不允许best-seed筛选、test调参、旧CAPD比较、阶段2—4覆盖或阶段6实验。
