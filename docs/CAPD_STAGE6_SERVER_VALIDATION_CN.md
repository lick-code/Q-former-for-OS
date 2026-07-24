# CAPD 阶段6 Linux服务器验收

## 1. 前置条件

- Stage 5 manifest状态为`STAGE5_VERIFIED`；
- 9个Stage 4 Full checkpoint及其manifest完整；
- 三个official workload的B64 config、selector、train/valid JSONL完整；
- 三个official workload的train/valid/test processed trace完整，且内容
  指纹与各resolved config一致；
- CUDA/PyTorch环境可运行现有完整pytest。

## 2. 只读计划与输入审计

```bash
python3 scripts/run_capd_stage6.py --stage audit-inputs
python3 scripts/run_capd_stage6.py --stage plan
```

期望：

```text
profile_replay_jobs=27
capacity_data_jobs=6
capacity_training_jobs=18
capacity_replay_jobs=54
required_jobs=105
```

## 3. 测试

```bash
python3 -m pytest -q \
  tests/test_capd_stage6_results.py \
  tests/test_capd_stage6_plan.py \
  tests/test_capd_stage6_end_to_end.py

CAPD_STAGE6_E2E=1 python3 -m pytest -q \
  tests/test_capd_stage6_end_to_end.py::Stage6TorchMiniEndToEndTest

python3 -m pytest -q
```

## 4. 正式执行

建议在单GPU上依次执行：

```bash
python3 scripts/run_capd_stage6.py --stage profile --execute
python3 scripts/run_capd_stage6.py --stage capacity --execute
python3 scripts/run_capd_stage6.py --stage summarize
```

任务具有原子job manifest。已完成任务仅在job fingerprint和结果指纹
一致时复用；失败任务不自动重试。

## 5. 统一验收

```bash
bash scripts/validate_capd_stage6_server.sh
```

成功后 `run_manifest.json` 应满足：

```text
status == STAGE6_VERIFIED
required_jobs == completed_required_jobs == 105
stage5_status == STAGE5_VERIFIED
test_used_for_selection == false
method_contract_changed == false
server_gate_ready == true
```

`system_platform_validation`可以是`CONDITIONAL_NOT_RUN`，但论文和报告
必须如实披露。
