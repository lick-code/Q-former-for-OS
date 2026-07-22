# CAPD 阶段3候选筛选器独立验证报告

状态：`STAGE3_IMPLEMENTED_UNVERIFIED`。本报告仅使用冻结的 valid trace selector 样本，不包含训练、test replay、端到端实验或基线比较。

## 制品身份

- 结果 schema：`capd_finals_v3_stage3_selector_1`
- 输入 schema：`capd_finals_v3_0`
- 合同：`CAPD-MIC-1.0`
- 代码 commit：`0e51d8193fdf94342faca29e7ca1ed2ef89a6880`
- 完整命令：`scripts/run_capd_stage3_selector.py --repo-root /home/likc/Q-former-for-OS --artifact-root dataset/jsonl/finals_v3_official --workloads canneal streamcluster_pressure dedup_pressure --pool-sizes 8 16 32 64 --output outputs/results/finals_v3_official/stage3_selector`

| workload | B | config SHA-256 | selector SHA-256 | samples SHA-256 | summary SHA-256 |
|---|---:|---|---|---|---|
| canneal | 8 | 99ade761ba07bebba7d81e660b5ce9765f8519ec33a38904c28b54a8e00bd13b | d2ebabba47a8ed17abeef45ddb610f8b69657ee9f228a0370106855b7b4b09d0 | b76105a54928adc769bb405d10c0f10dc673f71fddbefae40a14a754b52c478e | 6fa2fe6e0410f5cfc7b80b6438c8d37528b21ce1704b3ddb159bea146797ed17 |
| canneal | 16 | 3f7aca7af66dd69b006deabcb21ceaeb5f5775bab96f18d358fb266625e1dfb9 | a3d6331e3b3506cb8db608730dcfe19adaa5f311d3eee6a4c8cb59c52eda7b37 | f062b2d885f5d970cc20d9a1447f3de3889242ddab553cb4237d1cb215a17347 | 86b0cdfb9d1d634326d29a02e82218348edc941bd06f42028b67253633957275 |
| canneal | 32 | e73fb17b80abd283d6acc96b2683a1cb54767df2591c90a3167632f2c80cd957 | ccfadd577d500e019005b77d820d2e176513f163502258ea22cdafec60d193cf | 4cf3c751677dedd5227907e0fd56f59a62a27f695a8854aa5c0307ec5eef742b | d8d58f4ce00cfcf5031cf2d01e0ec5793a25321f66d09cc6fdcfbd64d2b57ade |
| canneal | 64 | a0c188ee7382724f112a1498976f80e84276312a2b692805c1056649a16c6aa8 | b205a3fca7f4265a1e4b6f978ecdc5322f431a3bf4ac01dc5d3664a6673b9b9f | 2befbf0e6348d9efc47083b0292cf66a5d46bf35090340b6c81ca19d5392a956 | 1b18e12fcf8d742ccdfee918f92740e3861163f1d1e21e156ae2423bb219ca20 |
| streamcluster_pressure | 8 | ada77eabb0c38a6f965c648a742fd64a4343ba6bbfec277e4df98bbfd0f99897 | bc772cc9cfac564938c1429ffcdf1f4c27ca40214d66a4ee90b2c59a85512f22 | f33c5560242cd77295273c9ac6aeadca62575cfd865a9870bf8c430548428a47 | 5a24af475d7aa0d59ea541fe1968e23f9a3aa1b043687b7a9ac6dd34111f8197 |
| streamcluster_pressure | 16 | d9745af682bb2305ea4990784130edd7e87fa990f39e76f30ae444bd25fef704 | 47da0438cc717e86b954e2f5cddb4e280f57b969f5b322795bf08e99044f933a | fb0134bb2abea32ada4dd798cdc49b2e4d243e3a583116c19ffe82ca6cd29de9 | a955f886916c2b8d0021a959bca01df7f371a89b834155f5a4038190ef725c5d |
| streamcluster_pressure | 32 | 97ba63237fcb470a047557d92630a090effa188660c98bdb406c01675751d4a3 | ba8f6ca350dfddf5bb11c7b0873de58c5266e61c7d8dcb7fac06e80ee9bc0bcc | 3c89fb6eaa5c7be56262175fd73d2e7a3f311de33e9496426d1612642c1829b2 | add94139d6caa92be4dc5e80a44a3248187da81634766b78b0d2eda70b4bde46 |
| streamcluster_pressure | 64 | a74324d1156492cd17d5be523518112b545642d7bcedcd78ad3f9d3f0e6efdae | 69e82f9d334684ce1b0c71fd7ea3d185a35c3b2fa247684390387b793b881145 | 404fb0e3cd325032b43e7bfbbad27e7a044af9b0e72103153de1d08229063219 | b6c23d624e76cdc783ab0717b30b17c4c3dc5e630a8a5a7467406c1677da8f0b |
| dedup_pressure | 8 | 5b1ee0395c7d9ed549fdfa193b44fc36984f86d40ebfc8a23c3ebd7829df99c8 | b4227503311a58df954d955324bf3d9a54a246ffff5897fa92f87381abea7b72 | a34b9e87412b2cf72e2cf8b60b77c2a2e918679f2a9d0fb3d97333346a02af65 | 6a10380ce432cd0df8012c7a7f6015920bbd99b07b1d0cec32d95e29b1b4eac8 |
| dedup_pressure | 16 | 811929ad4dbbbd7d56b982059cb003bc96ac0d67dc47a14a75c9e54f48a29271 | 13afbd0d5e394c744736b4851e6c32f838bcf43d8fcabd6ffec230eef5b42819 | be6e782ede95030d608fe18c8b8dd97be4a9931c07ba24b8d827c41acb055b09 | 8461a7f7fdf6025a55a54166be543d1c5625ffd9205b51c039fc87466175d0b7 |
| dedup_pressure | 32 | 350115b839f7179a96914d3fddc285d17c5d5eff189bd80beeff79a9252f653c | 2afc23ebb31b22528c722dbb0a12047750eeb8fa08e4359e765f23696656cc83 | fb3508a6d0d5d1959e42cd4604127d1a7ccd57216a1782fc925c92d0e16dc1c4 | 29ba34dc82f72e0c9fa7360b6580227415ddf3132640d3d44bcb682fad8c1e22 |
| dedup_pressure | 64 | 6efd54a1fa03f57aa8d6ca8c1a86878e32c591e01387b725416c19f1cd13d38f | 9b5417a3e88364d259622af5c63e3ef51da939f881903d56fcb2a012fa4958f9 | 5022f73e8c4a1ff3b0a909a55d464e3ef2d5d80793815efbd6bbf14d12c27527 | 4a7e1b17330ba5edc86de7cc0a1b7144bd2ab0391959967bfb2762308578a842 |

输入文件路径与上述完整哈希同时记录在 `input_audit.json`。

## B sweep

| workload | B | PoolRecall@B | SelectorRecall@K | EndToEndRecall@K | TieCoverage@K | NRegret | weights (Delta,A,W,C,R) |
|---|---:|---:|---:|---:|---:|---:|---|
| canneal | 8 | 1 | 1 | 1 | 1 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| canneal | 16 | 1 | 1 | 1 | 0.500010016628 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| canneal | 32 | 1 | 1 | 1 | 0.256512952798 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| canneal | 64 | 1 | 1 | 1 | 0.162966096134 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| streamcluster_pressure | 8 | 1 | 1 | 1 | 1 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| streamcluster_pressure | 16 | 1 | 1 | 1 | 0.501786214255 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| streamcluster_pressure | 32 | 1 | 1 | 1 | 0.252160378582 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| streamcluster_pressure | 64 | 1 | 1 | 1 | 0.13847586672 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| dedup_pressure | 8 | 1 | 1 | 1 | 1 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| dedup_pressure | 16 | 1 | 1 | 1 | 0.499974880683 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| dedup_pressure | 32 | 1 | 1 | 1 | 0.250102191782 | 0 | 0.2,0.2,0.2,0.2,0.2 |
| dedup_pressure | 64 | 1 | 1 | 1 | 0.135632920476 | 0 | 0.2,0.2,0.2,0.2,0.2 |

## 观察范围扩展结论

- `canneal`：B=8 到 B=64 的 PoolRecall 绝对增量为 `0`；扩大观察范围是否实际提高覆盖：**否**。
- `streamcluster_pressure`：B=8 到 B=64 的 PoolRecall 绝对增量为 `0`；扩大观察范围是否实际提高覆盖：**否**。
- `dedup_pressure`：B=8 到 B=64 的 PoolRecall 绝对增量为 `0`；扩大观察范围是否实际提高覆盖：**否**。

## 权重稳定、退化与 fallback

- `canneal`：跨B权重完全相同=`True`，相邻B最大L1距离=`0`，uniform fallback=`无`，leave-one-out出现退化的组合数=`10`。
- `streamcluster_pressure`：跨B权重完全相同=`True`，相邻B最大L1距离=`0`，uniform fallback=`无`，leave-one-out出现退化的组合数=`3`。
- `dedup_pressure`：跨B权重完全相同=`True`，相邻B最大L1距离=`0`，uniform fallback=`无`，leave-one-out出现退化的组合数=`0`。

## 指标分母

`SelectorRecall@K` 与 `NRegret` 只统计 `R_t^y > epsilon_y` 的有效决策点；`PoolRecall@B`、`EndToEndRecall@K` 与 `TieCoverage@K` 统计全部完整未来窗口决策点。所有指标来源均为 `valid_trace`，不同分母不合并解释。

## 消融说明

完整 selector 在五维 1001 点网格上重搜；single-feature 直接评估五个 one-hot；leave-one-out 将一个特征权重固定为0，并在其余四维的286点子网格上按同一四级规则重搜。逐项结果与相对 Full 的绝对变化见 `stage3_ablation.csv`。PoolRecall 与 selector 权重无关，每个 workload/B 只解释一次。

## 边界

这些结果只验证候选池和轻量筛选器的覆盖行为，不代表系统性能、加权代价或命中率提升。
