# CAPD 阶段6实现符合性报告

状态：`STAGE6_VERIFIED`

## 已实现并验收

- Stage 5 `STAGE5_VERIFIED` 与 348/348 job 的硬前置审计；
- source manifest及train/valid/test processed trace存在性和内容指纹硬门禁；
- 27个正式开销回放任务：三workload、三CAPD seed、三Random seed、
  LRU/LFU/CLOCK；
- QMAP selector、tensor/embedding、Transformer、
  Cross-Attention scorer、victim selection及完整决策的同步逐决策计时；
- mean/P50/P95/P99/max、吞吐、模型静态字节、进程RSS和CUDA峰值内存；
- 相对最快经典基线的吞吐下降，以及相对最低计数经典基线的迁移和
  NVM写入绝对/百分比变化；
- `D=128/256` 容量变体的独立selector/JSONL/三seed训练与公平回放，
  连同Stage 5的`D=64`组成正式容量矩阵；
- 四套成本模型的Stage 5 official计数精确重加权；
- 成本与自然读写比例汇总严格限定预注册经典基线，不让可选学习基线
  改写Stage 6参照口径；
- 三个official workload自然读写比例与Stage 5结果的描述性交叉表；
- 真实混合内存平台缺失时生成显式 `CONDITIONAL_NOT_RUN` 证据与局限性报告；
- 105个required job的指纹计划、原子manifest、单写者续跑和失败不自动重试；
- 纯Python结果/计划测试和服务器opt-in torch mini E2E；
- Linux服务器统一验收入口。

## 正式服务器验收

2026-07-26 在 CUDA/PyTorch 服务器执行统一验收脚本
`scripts/validate_capd_stage6_server.sh`。最终验收日志为
`stage6_validation_retry.log`，服务器证据目录为
`/tmp/capd-stage6.Q0AKVm`。目标测试、torch mini E2E、完整 pytest、
计划生成、GPU profile、容量矩阵、汇总、provenance 检查和
`git diff --check` 均返回 `exit_code=0`，最终输出
`[FINAL] STAGE6_VERIFIED`。

首次验收日志 `stage6_validation.log` 保留了当时未通过的执行记录；
完成修正后的统一重跑是本报告采用的最终验收依据。

`run_manifest.json` 的最终门禁为：

- `status=STAGE6_VERIFIED`；
- `required_jobs=completed_required_jobs=105`；
- `stage5_status=STAGE5_VERIFIED`；
- `test_used_for_selection=false`；
- `method_contract_changed=false`；
- `server_gate_ready=true`；
- `verified_by=scripts/validate_capd_stage6_server.sh`。

## 产物完整性

- 输入审计：56/56项通过，Stage 4 Full checkpoint为9/9；
- 执行计划：27个profile replay、6个容量数据任务、18个容量训练任务和
  54个容量回放任务，共105个required job；
- profile：27行正式结果，覆盖三个workload、三个CAPD模型seed、
  Random三个回放seed及LRU/LFU/CLOCK；
- capacity：81行结果，完整覆盖 `D={64,128,256}`、三个workload和
  预注册策略/seed；
- cost robustness：108行结果，覆盖四套冻结成本模型；
- natural RW robustness：3行结果，覆盖三个official workload的真实
  Trace读写比例；
- profile summary包含逐决策mean/P50/P95/P99/max、吞吐、迁移、
  NVM写入、模型静态内存、进程RSS和CUDA峰值内存；正式设备为
  NVIDIA GeForce RTX 3060 Ti，PyTorch版本为1.13.1+cu117；
- manifest声明的17个汇总输出全部存在。

## 条件项与最终结论

本轮未提供真实混合内存平台，因此
`system_platform_validation=CONDITIONAL_NOT_RUN`。软件测量没有被重新
标记为硬件实测。根据冻结协议，该项为条件项，不阻塞软件阶段6验收，
但必须在论文和最终报告中明确披露。

阶段6的强制软件实验、可追溯性检查和服务器门禁已经完成，认定为
`STAGE6_VERIFIED`。完整命令见
`docs/CAPD_STAGE6_SERVER_VALIDATION_CN.md`。
