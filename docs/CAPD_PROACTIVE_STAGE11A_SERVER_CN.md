# CAPD Stage11A Linux handoff

本文件只提供未来服务器执行入口；以下命令在当前环境没有执行，也没有生成新的 Stage9 或 Stage10 正式结果。不要覆盖或修复 `stage9-overhead-r1`。

先在获得真实 Stage9 v2 verified run 后，把路径替换为新的 run 目录，并在项目根目录执行只读门禁：

```bash
cd /path/to/cache_replacement
PYTHONPATH=. python -c 'from qmap.proactive_stage11 import audit_stage9_gate; import json; print(json.dumps(audit_stage9_gate("outputs/capd_proactive_stage9/<new-stage9-v2-run>"), ensure_ascii=False, indent=2))'
PYTHONPATH=. python -c 'from qmap.proactive_stage11 import audit_stage10_fixture; import json; print(json.dumps(audit_stage10_fixture("outputs/capd_proactive_stage10/<stage10-run>"), ensure_ascii=False, indent=2))'
```

只有 Stage9 自身 `verification.json`、`artifact_sha256`、兼容性 receipt、perf/RSS 和 run state 全部通过时，Stage9 receipt 才能是 `verified`；Stage10A fixture 仍只能是 `BLOCKED`。缺少任一真实输入必须保持 `NOT_VERIFIABLE`。这些命令不会写入 Stage8/Stage9/Stage10 树，不训练输入消融模型，也不选择 checkpoint。

