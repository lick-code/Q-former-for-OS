# CAPD 作品演示视频录制说明

## 演示定位

`scripts/run_capd_demo.py` 使用本次运行时生成的确定性合成访问序列，调用仓库中的真实 Replay 状态机、真实基线排序器、冻结 CAPD checkpoint 和独立 Cost 计算模块，完成一次便于录屏的小规模闭环演示。

该脚本只用于说明软件链路和结果形成过程。输出统一标记为 `non_formal_demo_only`，不读取正式 Test trace，不替代或复现正式实验结果，也不能用于证明真实 NVM 性能、前台访问时延或异步并发性能。

## 服务器预检查

在项目根目录执行：

```bash
test -f outputs/capd_proactive_stage4_stage7/stage4-stage7-unified-r2/checkpoints/opt-balanced/seed_3136859/qmap_best.pth
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
python -m unittest -v tests.test_capd_demo
```

第一条命令没有输出且退出码为 0，表示默认冻结 checkpoint 存在。最后一条测试命令只依赖 Python 标准库，不要求服务器额外安装 `pytest`。演示默认使用 CPU，以减少服务器型号差异对录制的影响。

## 建议录屏命令

先放大终端字体并清屏，再执行：

```bash
clear
python -u scripts/run_capd_demo.py --device cpu --pause 1
```

完整运行分为五步：

1. 校验配置、Cost 权重和冻结 checkpoint 的 SHA-256。
2. 生成独立合成访问序列，并显示访问数、唯一页数和输入摘要。
3. 在同一输入上运行 Reactive-LRU、Proactive-LRU、Proactive-CLOCK 和 CAPD。
4. 从原始事件计数重新计算加权 Cost，并检查访问、页进入、降级、容量和分层状态守恒关系。表格中的 `Rank changes` 表示 CAPD 在多少个决策轮次中没有直接采用该轮 LRU-tail 前 `b_t` 页，而是由冻结模型改变了选页顺序；这是模型参与决策的过程指标，不表示性能提升。
5. 重复运行并比较语义摘要，全部一致后输出 `DEMO_CLOSED_LOOP_PASS`。

脚本默认把产物写入 `outputs/capd_demo/demo-<UTC时间>/`。其中：

- `manifest.json` 记录输入、checkpoint 和 Cost 配置身份；
- `demo_trace.jsonl` 是本次生成的合成输入；
- `results/*.json` 保存各策略的原始计数、事件、轮次和状态；
- `summary.json` 是录屏中表格的结构化版本；
- `verification.json` 记录闭环检查结果和解释边界。

## 建议讲解词

“这里运行的是作品演示专用的小规模合成负载，不是论文正式 Test 数据。脚本首先校验冻结模型和成本配置，然后让多个策略共享同一个 Replay 状态机和同一条访问序列。CAPD 路径会真实加载冻结 checkpoint，只使用当前候选页和历史状态进行排序。随后，脚本从 DRAM 命中、NVM 读写和页迁移等原始事件重新计算加权成本，并检查各类计数与内存状态是否守恒。最后再完整运行一次，比较排除计时字段后的语义摘要；出现 `DEMO_CLOSED_LOOP_PASS`，说明本次演示的软件链路、指标计算和可复现性检查均已闭合。正式结论仍以提交材料中的正式实验及其证据链为准。”

## 录制注意事项

- 不要把演示表格中的数值称为论文结果或性能提升比例；这些数值只说明指标能够由真实运行链路产生。
- 建议保留开头和结尾的 `NON-FORMAL SYNTHETIC RUN`、`NOT formal experiment evidence` 提示。
- 若需要重录，直接再次执行命令即可；时间戳会创建新的演示目录，不覆盖之前的产物。
- 如使用 GPU，可将参数改为 `--device cuda`，但录屏前应先完整试跑一次，并保持正式口径仍为“同步回放演示”。
