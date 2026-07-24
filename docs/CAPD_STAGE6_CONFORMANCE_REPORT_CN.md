# CAPD 阶段6实现符合性报告

状态：`STAGE6_IMPLEMENTED_UNVERIFIED`

## 已实现

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

## 当前验收边界

本地 Python 3.13 环境没有 PyTorch，因此本轮不能执行：

- 27个profile replay；
- 18个高容量训练和54个高容量replay；
- torch-backed Stage 6 mini E2E；
- CUDA延迟和峰值显存实测。

本地初检曾发现三个workload绑定的9个processed trace不在配置目标路径。
仓库的 `dataset/raw_traces/finals_v3_official/` 中存在同字节封存副本；
逐文件SHA-256确认与official manifest一致后，已无转换恢复到
`dataset/processed/finals_v3_official/`。修正后的输入审计共56项检查，
当前为 `PASSED`。

在服务器正式矩阵与完整门禁成功前，状态不得提升为
`STAGE6_VERIFIED`，不得形成高容量或P95/P99性能结论。

真实混合内存平台是条件项；未提供平台时保留
`system_platform_validation=CONDITIONAL_NOT_RUN`，不能伪造实测数据。

完整命令见 `docs/CAPD_STAGE6_SERVER_VALIDATION_CN.md` 和
`scripts/validate_capd_stage6_server.sh`。
