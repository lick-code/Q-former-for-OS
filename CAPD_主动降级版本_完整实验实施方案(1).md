# CAPD 主动降级版本实验实施方案
## ——基于 Trace Replay 的完整实验路线、边界定义与执行顺序

> **文档用途**  
> 本文用于指导 CAPD 决赛阶段后续实验实施。当前不再继续扩展候选池筛选器，也不进行完整 Linux 内核集成，而是围绕最新的“水位触发、后台主动降级、有界批量选择”版本 CAPD，构建一套完整、可复现、边界清晰的 Trace Replay 实验体系。
>
> 正式主线采用收缩后的六种方法：Reactive-LRU、Proactive-LRU、Proactive-CLOCK、TPP-inspired、CAPD 和 Oracle。已有的 Kleio-lite、PatternS-lite 仅作为时间允许时的扩展结果，不阻塞主实验；不再实现 FlexMem-Demotion-inspired。
>
> **最终目标**  
> 证明 CAPD 不仅能够对候选页面进行更准确的主动降级排序，而且能够：
>
> 1. 在 DRAM 空闲页框耗尽前主动恢复页框储备；
> 2. 减少紧急降级及其可能造成的前台阻塞；
> 3. 控制提前误降带来的 NVM 访问和迁移开销；
> 4. 通过 Top-\(b_t\) 批量降级降低平均到单页上的模型推理开销；
> 5. 在更合理的 DRAM 容量、更多 workload 和更强 baseline 下保持竞争力。

---

# 1. 当前正式方法与实验对象

## 1.1 正式方法

当前 CAPD 不再采用“DRAM 已满后为当前请求淘汰一个页面”的执行方式，而是采用主动降级机制。

设：

- \(F_t\)：时刻 \(t\) 的 DRAM 空闲页框数量；
- \(F_{\mathrm{low}}\)：主动降级触发水位；
- \(F_{\mathrm{target}}\)：目标恢复水位；
- \(K\)：每轮候选页面数量；
- \(b_{\max}\)：单轮最大主动降级页面数量。

满足：

\[
0<F_{\mathrm{low}}<F_{\mathrm{target}}.
\]

系统行为定义为：

```text
F_t >= F_low
→ 正常运行，不执行主动降级

0 < F_t < F_low
→ 启动 CAPD 主动降级周期

F_t = 0 且有页面需要进入 DRAM
→ 跳过 CAPD，使用 LRU 等轻量策略紧急降级
```

在一轮主动降级中：

\[
b_t=
\min\left(
b_{\max},
F_{\mathrm{target}}-F_t
\right).
\]

CAPD 从当前 DRAM 驻留页面的 LRU 尾部构造固定规模候选集合 \(K\)，对候选页面进行评分，并选择 Top-\(b_t\) 页面主动降级。

完成一轮后：

1. 更新 DRAM/NVM 页面集合；
2. 更新页面状态；
3. 更新 LRU 顺序；
4. 更新空闲页框数 \(F_t\)；
5. 若 \(F_t<F_{\mathrm{target}}\)，重新构造候选集合并继续下一轮；
6. 直到空闲页框数达到 \(F_{\mathrm{target}}\)。

---

## 1.2 页面进入 DRAM 的统一定义

实验中不区分页面以何种来源进入 DRAM。

统一规定：

```text
任何页面进入 DRAM
→ 占用一个空闲页框
→ F_t = F_t - 1
```

这里的 `page_enter_dram` 是实验层面的统一容量事件。无论页面在真实系统中属于首次进入、重新装入或其他来源，只要该事件使一个页面进入 DRAM，就统一记为占用一个空闲页框。Replay 不记录、区分或讨论该事件是否属于 promotion，也不为不同来源设置不同处理路径。

主动或紧急降级一个 DRAM 页面：

```text
一个 DRAM 页面降级到 NVM
→ 释放一个空闲页框
→ F_t = F_t + 1
```

实验不单独讨论：

- 页面首次放置；
- NVM 到 DRAM promotion 的独立语义；
- Placify；
- 页面进入 DRAM 的来源差异。

Replay 只需要处理两个与容量有关的基本事件：

```text
page_enter_dram
page_demote_from_dram
```

因此，本实验只评价 DRAM 容量占用和 DRAM→NVM 主动降级，不评价 promotion 策略本身，也不报告依赖 promotion 语义的迁移往返指标。

---

## 1.3 正式研究范围

当前项目只研究：

```text
单线程
单进程
单 workload
单应用顺序访存 Trace
```

不研究：

- 多线程调度交织；
- 多进程地址空间竞争；
- 多 workload 并发；
- mixed workload；
- 多租户内存管理；
- Placify 与 CAPD 联合优化；
- 完整 Linux 内核集成；
- 旧 Reactive-CAPD 与当前 CAPD 的对比。

最终文档需要主动限定：

> 本项目聚焦单线程、单进程、单 workload 场景下的 DRAM 主动页面降级问题。所有训练和测试均基于单应用顺序访存轨迹，不讨论多线程调度交织、多进程竞争及混合 workload 下的联合内存管理。

---

## 1.4 筛选器的处理方式

原决赛候选扩展筛选器不再属于正式方法。

最终方法中不包含：

```text
LRU tail 扩大到 B
→ 粗筛回 K
```

筛选器只在实验中的“负向探索/设计取舍”部分简要说明：

> 我们曾尝试扩大 LRU-tail 候选池并增加轻量筛选器，但在验证数据中未观察到 K 外严格更优的 oracle 页面；该组件没有改善 weighted cost，并增加约 11% 决策延迟，因此最终系统未采用该设计。

不需要在新的主动降级框架下重新运行完整筛选器实验。

---

# 2. 实验需要回答的核心问题

整个实验章节围绕以下问题组织。

## Q1：CAPD 的页面排序是否优于其他主动降级策略？

在相同的：

- DRAM 容量；
- 水位；
- 候选集合；
- 批量大小；
- 页面进入规则；
- 紧急回退规则；

下，只改变候选页面排序方法，比较 CAPD 与其他策略。

---

## Q2：主动降级是否能够有效维护空闲页框储备？

需要证明：

- 空闲页框耗尽次数减少；
- 紧急回退次数减少；
- 最小空闲页框数提高；
- 系统能在页面持续进入 DRAM 时维持合理储备。

---

## Q3：主动降级是否造成了过度提前迁移？

主动降级不是免费收益。

如果水位过高或批量过大，可能出现：

```text
页面被主动降级
→ 很快再次访问
→ 增加 NVM 访问
```

因此需要衡量：

- 提前误降率；
- 短期重新访问率；
- NVM read/write；
- 总降级数；
- 无效主动降级及其后续 NVM 访问。

---

## Q4：Top-\(b_t\) 是否真正摊薄了模型开销？

当前方法的重要系统动机之一是：

```text
一次模型评分
→ 选择多个页面
→ 平均每个降级页面的推理开销下降
```

实验需要比较：

- \(b_{\max}=1\)；
- \(b_{\max}=2\)；
- \(b_{\max}=4\)。

并同时观察：

- 每轮推理延迟；
- 每页摊销延迟；
- weighted cost；
- 提前误降率。

---

## Q5：扩大到合理内存规模后，CAPD 是否仍然有效？

原实验使用 8/16/32 个 4 KB 页面，无法代表真实容量。

新实验需要：

- 扩大 working set；
- 扩大 DRAM 绝对页面数；
- 使用多个 DRAM/working-set ratio；
- 观察高、中、低压力下 CAPD 的适用范围。

---

## Q6：CAPD 的后台速度和资源开销是否可接受？

由于当前没有时间完成真实 Linux 集成，使用：

```text
实测 CPU 模型延迟
+
Replay 事件数量
+
参数化异步时间模型
```

估计：

- 后台降级服务速率；
- 后台 CPU 占用；
- 是否能跟上页面进入 DRAM 的速率；
- 什么压力下会触发紧急回退。

---

# 3. 总体实验执行顺序

后续实验必须按依赖关系推进。

```text
阶段 0：冻结实验边界和统一配置格式
        ↓
阶段 1：改造主动降级 Replay 与日志
        ↓
阶段 2：标定最终评价 Cost 模型
        ↓
阶段 3：预冻结 working set、容量、水位与批量机制
        ↓
阶段 4：在冻结主动机制下选择训练标签、lookahead 与模型配置
        ↓
阶段 5：实现统一 Replay Baseline
        ↓
阶段 6：实现 TPP-inspired
        ↓
阶段 7：完成正式 workload、working set 和 DRAM 容量配置
        ↓
阶段 8：运行正式同步 Replay 主实验
        ↓
阶段 9：测量推理、CPU 和内存开销
        ↓
阶段 10：运行参数化异步 Replay
        ↓
阶段 11：完成敏感性、消融和负向实验
        ↓
阶段 12：整理最终图表与文档
```

前四个阶段会影响训练数据、checkpoint 和全部下游结果，必须优先完成并冻结。特别是 \(F_{\mathrm{low}}\)、\(F_{\mathrm{target}}\) 和 \(b_{\max}\) 会改变主动降级决策点及后续状态轨迹，因此必须先用规则策略和页面进入突发统计预冻结，再生成用于标签与模型选择的正式训练样本。

---

# 4. 阶段 0：冻结边界和配置

## 4.1 建立唯一正式方法配置

建议统一配置为：

```yaml
method: capd_proactive
selector: disabled
candidate_source: lru_tail
candidate_size: K
trigger_mode: low_watermark
fallback_policy: lru
single_process: true
single_thread: true
single_workload: true
```

所有实验必须保存完整配置，禁止只根据输出目录名猜测参数。

---

## 4.2 必须保存的全局配置

每次运行至少保存：

```text
workload
trace 文件
trace 起止范围
train/validation/test 划分
page size
working-set size
DRAM page 数
NVM 容量模型
F_low
F_target
K
b_max
H
L
lambda_1/lambda_2/lambda_3
Cost profile
policy 名称
随机种子
模型 checkpoint
代码版本或 commit
运行机器信息
```

---

## 4.3 数据划分规则

使用时间顺序划分：

```text
Train
→ Validation
→ Test
```

要求：

- 三个区间互不重叠；
- 任何参数选择只允许使用 Train/Validation；
- Test 只在参数冻结后运行；
- 不允许根据 Test 结果调整水位、标签权重或 benchmark 窗口。

---

# 5. 阶段 1：主动降级 Replay 改造

## 5.1 Replay 状态

Replay 至少维护：

```text
DRAM resident set
NVM resident set
DRAM capacity
F_t
F_low
F_target
LRU state
frequency state
dirty state
residency state
history window
active proactive cycle
```

---

## 5.2 页面访问流程

推荐统一执行顺序：

```text
处理一条访问
    ↓
判断页面是否进入 DRAM
    ↓
若进入 DRAM：
    F_t -= 1
    ↓
更新页面访问、dirty、frequency、LRU 和 history
    ↓
检查水位
```

水位处理：

```text
若 F_t >= F_low：
    不触发主动降级

若 0 < F_t < F_low：
    启动或继续主动降级周期
    当前策略选择 b_t 个页面
    完成一轮降级
    F_t += b_t
    更新全部状态
    若 F_t < F_target：
        重新构造候选并继续

若 F_t = 0 且下一页面需要进入 DRAM：
    使用 LRU 紧急降级一页
    释放页框后继续访问
```

需要注意初始化边界：

- DRAM 尚未装满时，候选页数量可能小于 \(K\)；
- 若当前 DRAM 驻留页数小于 \(K\)，候选集合取全部可用页；
- \(b_t\) 不能大于当前候选数量；
- \(b_t\) 不能大于当前实际缺口；
- \(b_t\) 不能使 DRAM 驻留页面数降为负数。

推荐实际实现：

\[
b_t=
\min\left(
b_{\max},
F_{\mathrm{target}}-F_t,
|\mathcal C_t|
\right).
\]

---

## 5.3 降级类型

记录三类：

```text
proactive_demotion
reactive_demotion
emergency_fallback_demotion
```

对于主动降级，再记录实际策略：

```text
Proactive-LRU
Proactive-CLOCK
TPP-inspired
CAPD
Oracle
```

Reactive-LRU 在无空闲页框时执行的正常按需降级记录为 `reactive_demotion`；主动策略意外耗尽空闲页框后调用 LRU 的安全回退记录为 `emergency_fallback_demotion`，两者不能混为同一事件。

---

## 5.4 主动降级轮次日志

每轮保存：

```text
decision_id
cycle_id
round_id
access_index
F_before
F_low
F_target
candidate_pages
candidate_features
policy_scores
selected_pages
b_t
F_after
feature_latency
inference_latency
selection_latency
migration_count
```

---

## 5.5 主动降级周期日志

每个周期保存：

```text
cycle_id
start_access
end_access
start_F
target_F
number_of_rounds
number_of_pages_demoted
minimum_F
total_inference_time
total_selection_time
是否发生 emergency fallback
```

---

## 5.6 Workload 汇总日志

除原有事件外，保存：

```text
DRAM hits
NVM reads
NVM writes
total demotions
proactive demotions
emergency demotions
number of proactive cycles
number of proactive rounds
mean b_t
rounds per cycle
minimum free frames
average free frames
free-frame exhaustion count
accesses below F_low
early-reuse count
weighted cost
decision count
total decision time
```

必须保存原始事件数，不能只保存 weighted cost。

---

## 5.7 同步 Replay 的定位

同步 Replay 用于：

- 训练样本生成；
- 策略选择质量；
- 主结果对比；
- 参数选择；
- NVM 事件统计；
- weighted cost。

同步 Replay 假设：

```text
当前轮推理与降级完成后
→ 才处理下一条访问
```

因此它不能直接证明真实后台运行一定来得及，也不能将其结果描述为真实前台延迟。

后台服务能力由后续异步实验单独评估。

---

# 6. 阶段 2：最终评价 Cost 模型标定

## 6.1 当前 Cost

默认评价指标为：

\[
C=
1N_{\mathrm{hit}}
+
2N_{\mathrm{NVM-read}}
+
8N_{\mathrm{NVM-write}}
+
10N_{\mathrm{demotion}}.
\]

即：

```text
Hit : NVM Read : NVM Write : Demotion
= 1 : 2 : 8 : 10
```

Reviewer 的核心质疑不是公式不能使用，而是：

> 为什么这些系数合理？

---

## 6.2 Cost 权重与标签权重必须区分

Cost 权重：

- 用于最终评价；
- 不直接参与模型训练；
- 保存原始事件数后可以离线重算。

标签权重：

- 直接改变训练目标；
- 每组权重都要重新构造标签并训练。

因此先标定 Cost profile，再选择训练标签权重。

---

## 6.3 默认 Cost 的确定原则

不能根据：

> 哪一组 Cost 能让 CAPD 提升最大

来选择权重。

正确选择依据应是：

> 哪一组权重最接近目标混合内存系统中各事件的相对代价。

---

## 6.4 可执行的标定方案


### 方案 B：没有真实 NVM 平台

使用当前模拟器或目标硬件参数设置多个合理 Cost profile：

| Profile | Hit | NVM Read | NVM Write | Demotion |
|---|---:|---:|---:|---:|
| Read-light | 1 | 2 | 4 | 8 |
| Default | 1 | 2 | 8 | 10 |
| Write-expensive | 1 | 2 | 12 | 10 |
| Migration-expensive | 1 | 2 | 8 | 20 |

默认采用位于合理参数区间中部的：

```text
1 : 2 : 8 : 10
```

然后通过敏感性实验说明主要结论不依赖单一 Cost profile。

---

## 6.5 此阶段的完成标准

在运行正式 Test 前，必须冻结：

```text
default_cost_profile = 1:2:8:10
sensitivity_profiles = 预先定义的其他三组
```

最终文档建议表述：

> 根据目标混合内存事件的相对代价范围，本项目采用 \(1:2:8:10\) 作为默认整数化 Cost profile。进一步的多 Cost-profile 敏感性实验表明，CAPD 的主要结论在合理的读、写和迁移代价范围内保持稳定。

不能表述为：

> 因为该权重下 CAPD 提升最大，所以采用该权重。

---

# 7. 阶段 3：预冻结 Working Set、容量、水位与批量机制

本阶段先固定会改变训练决策点和状态轨迹的主动控制参数。此时不使用 CAPD 模型结果选择水位或批量大小，而是基于 Train/Validation 的页面进入突发统计和 Proactive-LRU 确定统一默认配置，从而避免“先用未冻结水位生成训练样本，再根据模型结果修改水位”的循环依赖。

## 7.1 预冻结 Working Set 与容量口径

先在 Train/Validation 上确定统一的 active working-set 统计口径，并为代表 workload 建立：

```text
working-set page 数
DRAM/working-set ratio
对应的 DRAM 绝对页面数
page_enter_dram 事件序列
```

默认容量候选沿用：

```text
20% / 40% / 60% working set
```

若该组比例无法形成可区分的压力层次，可仅根据 Train/Validation 改为：

```text
10% / 20% / 40%
```

一旦确定 working-set 口径和容量比例规则，后续训练样本生成、Validation、Test 及所有 baseline 均使用同一规则。

---

## 7.2 页面进入 DRAM 的突发性统计

在代表 Train/Validation workload 上统计：

```text
每 100 次访问的 page_enter_dram 数
每 500 次访问的 page_enter_dram 数
每 1000 次访问的 page_enter_dram 数
```

每种窗口报告：

```text
mean
P50
P95
P99
max
```

这些数据只用于确定默认页框储备规模，不使用 Test 数据，也不查看 CAPD 的效果。

---

## 7.3 水位候选

根据页面进入突发和 DRAM 绝对页面数构造 Small、Medium、Large 三种储备强度，例如：

```text
(F_low, F_target) =
(4, 8)
(8, 16)
(16, 32)
```

使用 Proactive-LRU 在 Validation 上比较：

```text
free-frame exhaustion
emergency fallback
total demotions
early-reuse rate
NVM read/write
```

选择能够维持基本页框储备、且不过度增加提前降级的统一默认水位。不得根据 CAPD 相对 baseline 的提升幅度选择水位，也不为不同策略单独设置统一比较实验中的水位。

---

## 7.4 批量大小

在已经选定的默认水位下，使用 Proactive-LRU 测试：

```text
b_max = 1 / 2 / 4
```

评价：

```text
weighted cost
NVM read/write
early-reuse rate
round count
emergency fallback
```

此阶段选择的是训练数据生成和正式统一比较所使用的默认 \(b_{\max}\)，不使用 CAPD 推理延迟或 CAPD Test 结果作为选择依据。

---

## 7.5 主动机制预冻结输出

本阶段结束时冻结：

```text
working-set 统计口径
DRAM/working-set ratio 规则
F_low
F_target
b_max
训练数据生成所用的 Proactive-LRU 状态推进规则
```

随后才在该固定主动机制下重新生成主动降级训练样本，并进入标签与模型配置选择。后续水位和批量实验属于敏感性分析，不再用于反向修改正式训练样本。

---

# 8. 阶段 4：在冻结主动机制下选择训练标签、Lookahead 与模型配置

## 8.1 当前标签

\[
y_t(l)
=
\lambda_1\hat d_t(l)
+
\lambda_2\hat q_t(l)
-
\lambda_3\hat w_t(l).
\]

当前默认：

\[
(\lambda_1,\lambda_2,\lambda_3)=(1,1,4).
\]

该权重决定：

- future inactivity；
- future access coldness；
- future write pressure；

在训练目标中的相对重要性。

---

## 8.2 权重选择必须在 Validation 完成

候选网格建议控制在小范围：

```text
(1,1,1)
(1,1,2)
(1,1,4)
(1,1,8)
(1,2,4)
(2,1,4)
```

每一组都需要：

```text
使用阶段 3 冻结的水位、批量和状态推进规则生成样本
→
重新生成 label
→ 重新训练模型
→ 在 Validation 上评估
```

不能只在测试阶段修改公式。

---

## 8.3 主动降级下的训练指标

由于在线选择 Top-\(b_t\)，Validation 不应只看 Top-1。

至少报告：

```text
NDCG@1
NDCG@b
Top-b overlap
Top-b regret
Validation weighted cost
NVM read
NVM write
Early-reuse rate
```

其中：

\[
\mathrm{Top\text{-}b\ Regret}
=
\sum_{l\in\mathrm{OracleTop}b} y_t(l)
-
\sum_{l\in\mathrm{PredTop}b} y_t(l).
\]

---

## 8.4 统一权重选择规则

推荐使用统一全局配置，不允许每个 workload 单独选择标签权重。

选择原则：

1. 多个 Validation workload 平均 weighted cost 较低；
2. NVM write 没有异常增加；
3. NDCG@b 和 Top-b regret 较好；
4. 不依赖单个 workload；
5. 三个 seed 结果稳定。

如果 \((1,1,4)\) 最终最好，可以写：

> 在预设标签权重网格中，\((1,1,4)\) 在 Validation 上取得最低或接近最低的平均系统代价，同时能够更好地抑制 NVM 写入，因此作为全部 workload 的统一默认权重。

---

## 8.5 Lookahead \(L\)

筛选器分析发现 \(L=256\) 下可能存在较多标签并列。

因此在正式全量训练前测试：

```text
L = 256 / 512 / 1024
```

先统计：

```text
label 方差
并列标签比例
oracle set size
无未来复用比例
```

再在代表 workload 上进行训练验证。

选择原则：

- 标签区分度提高；
- 训练数据生成时间可接受；
- Validation weighted cost 更稳定；
- 不出现明显未来信息过远导致的目标失真。

确定后，Train/Validation/Test 全部使用同一 \(L\)。

---

## 8.6 候选数 \(K\)

只做必要范围：

```text
K = 4 / 8
```

若时间允许增加：

```text
K = 16
```

不要重新引入 B=64 筛选器。

选择标准：

- weighted cost；
- NDCG@b；
- 每轮 latency；
- 每页摊销 latency。

---

## 8.7 历史窗口 \(H\)

建议仅测试：

```text
H = 当前值
H = 一个较小值
H = 一个较大值
```

例如：

```text
H = 5 / 10 / 20
```

避免大规模超参数搜索。

---

## 8.8 阶段 4 完成标准

本阶段只在阶段 3 已冻结的主动机制下选择模型相关配置：

```text
先确定 L 和标签权重
→ 再确定 K/H
→ 重新生成完整主动降级训练样本
→ 训练最终 checkpoint
```

本阶段结束时冻结：

```text
L
lambda_1 / lambda_2 / lambda_3
K
H
最终训练数据版本
最终 checkpoint 选择规则
```

不得因为模型在某个 Test 配置上的结果而返回阶段 3 修改水位或批量大小。水位与批量的其他取值只作为后续敏感性实验，不参与重新选择正式模型。

---

# 9. 阶段 5：确定最终 Baseline 体系

## 9.1 最终 Baseline 数量与组成

最终主线固定使用以下 6 种方法：

| 类型 | 方法 |
|---|---|
| 主动机制对照 | Reactive-LRU |
| 基础规则主动降级 | Proactive-LRU |
| 基础规则主动降级 | Proactive-CLOCK |
| 原生主动降级思想适配 | TPP-inspired |
| 本项目方法 | CAPD |
| 分析上界 | Oracle |

以下方法不属于正式主线：

```text
Random
LFU
AutoNUMA-inspired
PET-inspired
FlexMem-Demotion-inspired
Reactive-CAPD
旧 CAPD
```

原因如下：

1. Reactive-LRU 与 Proactive-LRU 用于隔离主动储备机制的贡献；
2. Proactive-LRU 与 Proactive-CLOCK 提供轻量规则基线；
3. TPP-inspired 作为唯一正式的原生主动降级强基线；
4. CAPD 与 Oracle 分别代表本项目方法和候选集合内分析上界；
5. Random、LFU 和第二个原生 inspired baseline 提供的新增信息不足以抵消实现与全量实验成本；
6. 当前项目只评价最新主动 CAPD，不与历史 CAPD 版本比较。

已有的 Proactive-Kleio-lite 和 Proactive-PatternS-lite 可在其实现已经稳定、且不影响主实验进度时放入扩展表。它们不是正式主线的完成条件，不参与主结论所依赖的最小 baseline 集合。

---

## 9.2 两类比较原则

正式实验分别隔离页面排序质量和主动储备机制，避免将两类收益混在同一比较中。

### 实验 A：统一主动框架下的页面选择比较（必须完成）

所有方法统一使用：

```text
相同 DRAM 容量
相同 NVM 模型
相同 F_low / F_target
相同候选规模 K
相同 b_max 与 b_t 计算规则
相同 emergency fallback
相同 Trace、数据区间和 Cost profile
```

仅改变：

> 如何为候选页面排序，并选择 Top-\(b_t\)。

在该实验中：

- Proactive-LRU 使用 LRU 顺序；
- Proactive-CLOCK 使用 CLOCK/reference-bit 规则；
- TPP-inspired 使用其冷热状态排序；
- CAPD 使用上下文感知评分；
- Oracle 使用未来标签。

该实验用于隔离：

> **页面选择质量本身的差异。**

### 实验 B：主动储备机制比较（必须完成）

比较：

```text
Reactive-LRU
vs
Proactive-LRU
```

两者使用相同的：

```text
DRAM/NVM 容量
页面进入规则
LRU 页面顺序
Trace、数据区间和 Cost profile
```

区别仅在于：

```text
Reactive-LRU：
只在无空闲页框且页面需要进入 DRAM 时降级一页

Proactive-LRU：
使用阶段 3 冻结的 F_low / F_target / b_max 主动建立页框储备
```

该实验用于隔离：

> **低水位主动储备机制本身相对于按需反应式降级的作用。**

TPP-inspired、Proactive-CLOCK、CAPD 和 Oracle 继续使用统一主动框架。已有 Kleio-lite/PatternS-lite 若进入扩展表，也只参加实验 A，不改变正式主线。

---

## 9.3 基础规则方法

### Reactive-LRU

Reactive-LRU 不设置主动水位，也不启动主动降级周期。仅当空闲页框不足且当前 `page_enter_dram` 事件需要占用页框时，选择 LRU 尾部页面降级，以释放一个页框。该方法是主动储备机制的外部对照，不是旧 CAPD 或 Reactive-CAPD。

### Proactive-LRU

在主动降级触发后，从当前候选集合中选择最靠近 LRU 尾部的 \(b_t\) 个页面。

### Proactive-CLOCK

使用 reference bit 和 CLOCK 指针进行页面选择。

批量选择时应明确：

1. 指针连续扫描；
2. reference bit 为 1 时清零并跳过；
3. reference bit 为 0 时选择该页；
4. 直到选满 \(b_t\) 个页面；
5. 降级完成后保留更新后的 CLOCK 指针。

---

## 9.4 可选的学习型 Replay 扩展 Baseline

本节方法不属于主实验完成条件。只有在现有实现能够直接适配统一主动水位和 Top-\(b_t\) 框架，且不会延误六种正式方法时才运行。

### Proactive-Kleio-lite

保留当前 Replay-compatible adaptation，并适配到统一主动水位和 Top-\(b_t\) 执行框架。

最终文档必须说明：

- 保留了原方法中哪些与页面降级相关的核心思想；
- 省略了哪些完整系统组件；
- 如何生成 Top-\(b_t\) 排序；
- 该方法不是完整原系统复现。

### Proactive-PatternS-lite

采用相同说明方式，明确其为统一 Replay 环境下的适配版本。

Kleio-lite 和 PatternS-lite 不能与完整原论文系统实现混称，结果仅放入扩展表或附录，不作为主结论的必要证据。

---

## 9.5 CAPD

CAPD 使用：

```text
近期访问上下文
候选页状态
单层 Transformer 编码
候选页相关交叉注意力
MLP 降级优先级评分
Top-b_t 主动选择
```

CAPD 是正式方法，所有结果以当前主动版本为准。

---

## 9.6 Oracle 上界

Oracle 在当前候选集合中直接使用未来 reference label 选择 Top-\(b_t\)。

Oracle 只用于分析：

- 当前候选集合的理论 headroom；
- CAPD 与候选集合内最优排序之间的差距；
- 不同水位和批量配置下的理论上限。

不能将 Oracle 描述为在线可部署方法。

---

## 9.7 Baseline 公平性检查

每次正式实验前自动检查：

```text
是否使用同一 Trace 范围
是否使用同一 DRAM/NVM 容量
是否使用同一页面进入规则
统一比较中是否使用同一水位和 b_t
是否使用同一候选集合 K
是否保存相同原始事件数
是否在 Test 前冻结参数
```

对于 Reactive-LRU，额外检查：

```text
是否只在 page_enter_dram 无可用页框时触发
是否每次只释放满足当前进入事件所需的页框
是否未创建 proactive cycle
```

对于 TPP-inspired，保存 sampling epoch 和冷热阈值，避免将参数差异隐藏在实现内部。

---

# 10. 阶段 6：实现 TPP-inspired

## 10.1 命名与复现边界

由于当前不进行真实 Linux 内核集成，最终名称必须使用：

```text
TPP-inspired
```

不能写成：

```text
Linux TPP
```

统一声明：

> 当前实验平台只复现相关论文中与主动降级、快速内存 headroom、页面冷热识别和降级速率控制有关的核心思想，不复现完整 Linux 内核中的页面提升、hint fault、NUMA/CXL 节点管理、并发回收、锁开销和任务调度机制。

该方法属于 Replay-compatible adaptation，作用是提供更贴近原生主动降级研究的强 baseline。

---

## 10.2 TPP-inspired：保留的核心思想

TPP-inspired 主要保留：

1. 在快速内存尚未完全耗尽前主动回收冷页；
2. 为后续页面进入 DRAM 保留 headroom；
3. 使用轻量的页面冷热状态区分活跃页与可降级页；
4. 优先降级长期未访问的冷页面。

不实现：

```text
慢速内存热页 promotion
完整 Linux reclaim/kswapd
CXL/NUMA 节点机制
内核 active/inactive list 的全部细节
真实迁移并发、锁与阻塞开销
```

---

## 10.3 TPP-inspired 页面状态

为每个 DRAM 页面维护：

```text
referenced_current_epoch
referenced_previous_epoch
last_access_epoch
dirty
LRU position
```

将访问序列按固定长度划分为 sampling epoch。

冷热状态定义建议为：

```text
Hot：
当前 epoch 被访问

Warm：
当前 epoch 未访问，但前一个 epoch 被访问

Cold：
连续两个或更多 epoch 未访问
```

每次页面被访问时：

```text
referenced_current_epoch = 1
last_access_epoch = current_epoch
```

epoch 切换时：

```text
referenced_previous_epoch = referenced_current_epoch
referenced_current_epoch = 0
```

---

## 10.4 TPP-inspired 排序规则

统一页面选择实验中，在相同候选集合 \(K\) 内按以下顺序排序：

```text
Cold + clean
→ Cold + dirty
→ Warm + clean
→ Warm + dirty
→ Hot + clean
→ Hot + dirty
```

同一类别内使用：

```text
更久未访问
→ 更靠近 LRU tail
```

作为 tie-break。

正式主实验中，TPP-inspired 使用阶段 3 冻结的统一水位与批量机制，仅用上述 epoch 冷热状态替换候选页排序规则。这样可以把 TPP-inspired 作为强主动降级排序基线，同时避免再次引入一套独立控制器。它仍需遵守项目统一边界：

- 只进行 DRAM→NVM 降级；
- 不进行 promotion；
- 紧急回退统一使用 LRU；
- 不能访问未来信息。

---

## 10.5 TPP-inspired 参数

Validation 中测试：

```text
epoch length = 64 / 256 / 1024 accesses
cold threshold = 连续 1 / 2 个 epoch 未访问
dirty tie-break = on / off
```

选择统一参数，不允许每个 Test workload 单独调参。

需要保存：

```text
各冷热类别页面数量
最终选中页面的冷热类别分布
Cold 页面短期重新访问率
TPP-inspired 的 proactive cycle 和 demotion 数量
```

---

## 10.6 实现正确性检查

### TPP-inspired

检查：

```text
页面被访问后能否进入 Hot
连续未访问后能否正确变为 Cold
epoch 切换是否正确清零 reference 状态
批量选择是否严格遵循冷热优先级
```

## 10.7 最终 Baseline 说明表

| 方法 | 保留的核心机制 | 省略或不研究的部分 |
|---|---|---|
| Reactive-LRU | 无空闲页框时按需降级 LRU 页 | 主动水位与页框储备 |
| Proactive-LRU | LRU 冷页顺序 | 无学习、无动态冷热建模 |
| Proactive-CLOCK | reference bit 与 CLOCK 扫描 | 完整 OS 回收路径 |
| TPP-inspired | 主动 headroom、epoch 冷热状态、冷页降级 | promotion、完整 Linux reclaim、CXL/NUMA 内核机制 |
| CAPD | 上下文感知排序与有界批量主动降级 | 真实 Linux runtime |
| Oracle | 候选集合内未来最优 Top-b | 在线不可部署 |

若时间允许加入扩展结果，可在附表中另列 Proactive-Kleio-lite 和 Proactive-PatternS-lite，但不得改变上述六种正式主线方法。

---
# 11. 阶段 7：Workload、Working Set 与容量

阶段 3 已经基于 Train/Validation 建立统一 working-set 口径、容量比例规则和默认主动机制。本阶段不重新选择这些规则，而是将冻结规则应用到六个正式 workload，补齐全部 workload 描述、绝对容量和正式运行配置。

## 11.1 Workload 范围

全部满足：

```text
单线程
单进程
单 workload
```

不加入 mixed workload 或多进程。

---

## 11.2 Workload 数量

正式主实验固定使用：

```text
6 个有效 workload
```

覆盖：

| 类型 | 目的 |
|---|---|
| 局部性稳定 | 检查主动降级是否误伤热页 |
| 高容量压力 | 检查 headroom 维护能力 |
| 突发页面进入 | 检查后台是否跟得上 |
| 写密集 | 检查是否减少 NVM 写入 |
| 不规则访问 | 检查上下文排序优势 |
| CAPD 负面 workload | 如实展示适用边界 |

不要求每个 workload 都获胜。

若已有额外 workload 且无需新增适配，可放入扩展结果；不得因为追求 workload 数量而延迟六个正式 workload 的完整容量、seed 和开销实验。

---

## 11.3 每个 Workload 的描述指标

必须报告：

```text
Trace 总访问数
Unique page 数
Active working-set page 数
读写比例
页面进入 DRAM 的平均速率
页面进入 DRAM 的 P95/P99 burst
训练/验证/测试区间
```

---

## 11.4 DRAM 容量

继续使用真实 4 KB page 语义。

不允许在没有实现 huge page 聚合的情况下，将 16 个 4 KB page 描述成“大页”。

建议使用 active working set 比例：

```text
高压力：DRAM = 20% W
中压力：DRAM = 40% W
低压力：DRAM = 60% W
```

若 20%/40%/60% 不适合，可以在 Validation 上使用：

```text
10%/20%/40%
```

但所有 workload 应遵循同一套比例规则。

绝对 DRAM 页面数尽量达到：

```text
数百到数千个 4 KB pages
```

---

## 11.5 NVM 容量模型

如果 Replay 中 NVM 不会满，统一定义：

> NVM 作为足够大的 backing tier，能够容纳所有未驻留于 DRAM 的页面。

报告实际：

```text
NVM-resident pages
NVM:DRAM ratio
```

不要额外引入 NVM 淘汰机制。

---

## 11.6 Standard 与 Pressure Test

### Standard Test

使用固定时间顺序 Test 区间，不人为挑选高压力窗口。

主结果优先使用 Standard Test。

### Pressure Test

可以额外选择压力较高的区间，但必须：

- 只使用 LRU；
- 只查看 Train/Validation；
- 根据 page-entry/demotion rate 选择；
- 所有策略使用相同区间；
- 不能根据 CAPD Test 结果挑选。

---

## 11.7 随机种子

学习策略：

```text
至少 3 个 seed
```

报告：

```text
mean ± standard deviation
```

规则确定性策略可运行一次，但仍使用完全相同 Trace 和配置。

---

# 12. 阶段 8：正式同步 Replay 主实验

## 12.1 主结果方法

正式主结果固定包含 6 种方法：

```text
Reactive-LRU
Proactive-LRU
Proactive-CLOCK
TPP-inspired
CAPD
Oracle
```

主实验建议同时报告两张结果表：

### 表 A：统一主动机制下的页面选择结果

所有方法使用相同的：

```text
F_low / F_target
K
b_max / b_t
```

用于比较页面排序质量。

该表不包含 Reactive-LRU，因为 Reactive-LRU 不使用主动水位。表中固定包含：

```text
Proactive-LRU
Proactive-CLOCK
TPP-inspired
CAPD
Oracle
```

### 表 B：主动储备机制对照

比较 Reactive-LRU 与 Proactive-LRU，在页面排序同为 LRU 的条件下隔离低水位主动储备机制的作用。表 B 同时报告页面代价、fallback、空闲页框和主动降级事件，不与旧 CAPD 进行比较。

Proactive-Kleio-lite 和 Proactive-PatternS-lite 若完成，只放入扩展表，不改变表 A、表 B 及主结论结构。

---

## 12.2 页面代价指标

每个 workload 报告：

```text
DRAM hits
NVM reads
NVM writes
total demotions
proactive demotions
emergency demotions
weighted cost
```

主文不能只报告 weighted cost。

---

## 12.3 主动降级有效性指标

报告：

```text
number of proactive cycles
number of proactive rounds
mean b_t
rounds per cycle
minimum free frames
average free frames
free-frame exhaustion count
emergency fallback rate
```

定义：

\[
\mathrm{FallbackRate}
=
\frac{
N_{\mathrm{emergency\ fallback}}
}{
N_{\mathrm{page\ enter\ DRAM}}
}.
\]

同步 Replay 中 fallback 可能很少，这一结果需要明确解释为功能正确性环境，不代表异步系统中必然为 0。

---

## 12.4 提前误降指标

定义 Early-Reuse Rate：

\[
\mathrm{EarlyReuse}(\Delta)
=
\frac{
\text{主动降级后 }\Delta\text{ 次访问内重新访问的页面数}
}{
\text{主动降级页面总数}
}.
\]

建议：

```text
Delta = 64 / 256 / 1024 accesses
```

还可以报告：

```text
主动降级后首次复用距离
被主动降级页面的未来访问次数
wasted demotion count
```

---

## 12.5 稳定性与不确定性

CAPD 使用至少 3 个 seed，并与确定性 baseline 使用相同 Test 区间、容量比例和事件配置进行配对比较。

预先指定：

```text
页面排序主比较对象：TPP-inspired
主动机制主比较对象：Proactive-LRU / Reactive-LRU
主指标：weighted cost
辅助指标：NVM read/write、demotion、Early-Reuse、fallback
```

报告：

```text
每个 workload × capacity 的逐项结果
CAPD 三个 seed 的 mean ± standard deviation
相对 TPP-inspired 的配对差值
跨 workload × capacity 配对差值的 95% bootstrap confidence interval
相对最佳非 Oracle baseline 的描述性改善
```

三个 seed 主要用于评价模型随机性，不单独作为强统计显著性证据。最终不根据单一 \(p\)-value 下结论，而结合配对差值、95% 置信区间、逐 workload 方向和实际效应量解释稳定性。不得只报告总体平均。

---

# 13. 阶段 9：推理、CPU 和内存开销

## 13.1 推理测量条件

CAPD 在线推理按 CPU 环境测量：

```text
model.eval()
torch.no_grad()
batch size = 1 个主动降级 round
固定 CPU 线程数
固定 CPU affinity
预热
重复测量
```

不将 GPU 作为默认在线平台。

---

## 13.2 延迟拆解

保存：

```text
watermark check
candidate construction
feature construction
Transformer encoding
candidate scoring
Top-b selection
total round latency
```

报告：

```text
Mean
P50
P95
P99
```

---

## 13.3 批量摊销

核心指标：

\[
T_{\mathrm{amortized}}
=
\frac{
T_{\mathrm{round}}
}{
b_t
}.
\]

比较：

```text
b_max = 1 / 2 / 4
```

同时报告 weighted cost 和 Early-Reuse，避免只追求延迟。

---

## 13.4 吞吐量

报告：

```text
rounds / second
demoted pages / second
CPU cycles / round
CPU cycles / demoted page
```

---

## 13.5 内存开销

拆分：

```text
模型参数
Page embedding
PC embedding
Transformer activation
History buffer
Candidate tensor
每页 metadata
总 peak memory
```

报告：

```text
固定模型开销：xxx KB/MB
每页 metadata：xx bytes/page
总运行时开销：xxx MB
占 DRAM 容量：xx%
```

---

## 13.6 公平容量实验

可以额外计算：

```text
CAPD effective DRAM pages
=
baseline DRAM pages
-
ceil(CAPD management memory / 4KB)
```

重新计算一个代表 workload 的结果，说明管理开销是否改变结论。

---

# 14. 阶段 10：参数化异步 Replay

## 14.1 目的

同步 Replay 假设主动降级完成后才处理下一次访问。

异步实验用于回答：

> 当页面持续进入 DRAM 时，CAPD 后台推理和迁移是否能够及时释放页框？

---

## 14.2 异步事件

只建模：

```text
page_enter_dram
capd_round_start
capd_inference_finish
demotion_finish
emergency_fallback
```

不建模：

```text
Placify
promotion 来源
多进程
多线程
```

---

## 14.3 时间参数

需要：

```text
页面进入 DRAM 的到达时间或到达率
CAPD round inference latency
单页 migration latency
b_t
```

如果 Trace 有可靠时间戳，使用实际时间。

如果没有可靠时间戳，进行参数化负载实验。

---

## 14.4 参数化负载

定义后台释放能力：

\[
\mu_{\mathrm{demote}}
=
\frac{
b_t
}{
T_{\mathrm{inference}}
+
b_tT_{\mathrm{migration}}
}.
\]

设置页面进入负载为：

```text
0.5 × mu
0.8 × mu
1.0 × mu
1.2 × mu
```

还应加入 burst 到达，而不仅是均匀到达。

---

## 14.5 异步指标

报告：

```text
emergency fallback count
fallback rate
foreground blocking time
minimum free frames
free-frame exhaustion duration
background queue length
CAPD background utilization
```

明确说明：

> 该实验是基于实测推理延迟和参数化迁移时间的离散事件分析，不等同于完整 Linux runtime 的端到端实测。

---

# 15. 阶段 11：敏感性与消融

## 15.1 水位敏感性

测试不同：

```text
F_low
F_target - F_low
```

观察：

```text
fallback rate
early-reuse rate
NVM read/write
demotions
background overhead
```

---

## 15.2 批量敏感性

```text
b_max = 1 / 2 / 4
```

展示：

```text
weighted cost
amortized latency/page
early-reuse
fallback
```

---

## 15.3 容量敏感性

```text
20% / 40% / 60% working set
```

说明 CAPD 在何种压力范围内有效。

---

## 15.4 标签权重敏感性

主表选定统一标签权重后，附加其他候选权重的 Validation 结果。

不需要在 Test 上重新挑选。

---

## 15.5 Cost-profile 敏感性

使用已经保存的原始事件数，离线重算：

```text
1:2:4:8
1:2:8:10
1:2:12:10
1:2:8:20
```

观察主要方法排序是否稳定。

---

## 15.6 模型输入消融

建议：

```text
CAPD-Full
CAPD-NoVPN
CAPD-NoContext
CAPD-NoPageState
```

NoVPN 已有初步结果，新主动降级环境下只需要选择代表 workload 进行确认。

---

## 15.7 批量机制消融

比较：

```text
Proactive-CAPD Top-1
Proactive-CAPD Top-b
```

这不是新旧 CAPD 比较。

两者均使用当前主动水位，只改变单轮选择数量，用于证明批量执行的作用。



---

# 16. 最终图表规划

## 表 1：实验设置

| 项目 | 内容 |
|---|---|
| Workload | 名称 |
| Thread/Process | 1/1 |
| Trace accesses | 数量 |
| Working-set pages | 数量 |
| Write ratio | 比例 |
| DRAM pages | 数量 |
| DRAM/Working-set | 比例 |
| NVM model | 足够大的 backing tier |
| \(F_{\mathrm{low}}\) | 数值 |
| \(F_{\mathrm{target}}\) | 数值 |
| \(K\) | 数值 |
| \(b_{\max}\) | 数值 |
| \(H/L\) | 数值 |
| Label weights | 数值 |
| Cost profile | 数值 |

---

## 表 2：Baseline 定义

列出：

```text
主动触发机制
冷热特征
候选排序规则
是否学习
是否使用未来信息
是否为完整系统
```

---

## 表 3：主结果

```text
DRAM hit
NVM read
NVM write
Demotion
Weighted cost
```

---

## 表 4：主动降级状态

```text
Fallback rate
Minimum F
Average F
Cycles
Rounds/cycle
Early-reuse rate
```

---

## 表 5：系统开销

```text
Round latency
Amortized latency/page
Pages/s
CPU cycles
Memory overhead
```

---

## 图 1：Weighted Cost 主对比

按 workload 展示所有主要 baseline。

---

## 图 2：空闲页框轨迹

选择代表 workload，绘制：

```text
Reactive-LRU
Proactive-LRU
Proactive-CLOCK
TPP-inspired
CAPD
```

的 \(F_t\) 随访问进度变化曲线。

---

## 图 3：水位权衡

横轴：

```text
reserve size 或 F_low
```

纵轴：

```text
Fallback Rate
Early-Reuse Rate
```

---

## 图 4：批量权衡

横轴：

```text
b_max
```

纵轴：

```text
Amortized latency/page
Weighted cost
```

---

## 图 5：容量敏感性

横轴：

```text
DRAM/Working-set ratio
```

纵轴：

```text
CAPD 相对最佳 baseline 的改善
```

---

## 图 6：异步后台能力

横轴：

```text
page-entry load / background service capacity
```

纵轴：

```text
fallback rate
blocking time
```

---

# 17. 实际执行清单

## P0：必须先完成

- [ ] 冻结页面进入 DRAM 的统一语义；
- [ ] 完成水位状态机；
- [ ] 完成 Top-\(b_t\) 多轮主动降级；
- [ ] 区分 proactive 和 emergency demotion；
- [ ] 补齐事件级与周期级日志；
- [ ] 保存原始事件数；
- [ ] 用两个 workload 检查状态机正确性。

---

## P1：正式训练前必须完成

- [ ] 冻结默认 Cost profile；
- [ ] 冻结 active working-set 统计口径和 DRAM/working-set ratio 规则；
- [ ] 完成 page_enter_dram 突发性统计；
- [ ] 使用 Proactive-LRU 预冻结 \(F_{\mathrm{low}}/F_{\mathrm{target}}/b_{\max}\)；
- [ ] 完成标签权重小网格；
- [ ] 完成 \(L\) 的标签饱和分析；
- [ ] 确定 \(K/H\)；
- [ ] 重新生成主动降级训练样本；
- [ ] 训练最终 checkpoint。

---

## P2：主实验必须完成

- [ ] Reactive-LRU；
- [ ] Proactive-LRU；
- [ ] Proactive-CLOCK；
- [ ] TPP-inspired；
- [ ] CAPD；
- [ ] Oracle；
- [ ] 统一主动机制页面选择对比；
- [ ] Reactive-LRU 与 Proactive-LRU 主动机制对比；
- [ ] 6 个正式 workload；
- [ ] 3 seeds；
- [ ] 多个 DRAM/working-set ratio。

---

## P3：系统可信度必须完成

- [ ] CPU 推理延迟；
- [ ] 延迟拆解；
- [ ] 单页摊销延迟；
- [ ] CPU cycles；
- [ ] 模型内存；
- [ ] 每页 metadata；
- [ ] 参数化异步 Replay；
- [ ] fallback 与 blocking 分析。

---


# 18. 配置冻结与止损规则

为了避免下游重复适配，设置以下规则。

## 18.1 冻结点一：Replay 冻结

状态机、日志、事件计数通过测试后，不再改变页面进入和降级语义。

## 18.2 冻结点二：主动机制预冻结

确定：

```text
active working-set 统计口径
DRAM/working-set ratio 规则
F_low
F_target
b_max
训练状态推进规则
```

后再生成主动降级训练样本。不得先用临时水位训练 CAPD，再根据 CAPD 结果反向修改正式水位。

## 18.3 冻结点三：训练配置冻结

确定：

```text
lambda
L
H
K
训练数据版本
checkpoint 选择规则
```

后再生成全量训练数据、训练最终 checkpoint 并运行全部 baseline。水位与批量的其他取值只进入敏感性分析。

## 18.4 冻结点四：Test 冻结

开始正式 Test 后，不得根据结果修改参数。

只有发现明确代码 bug，才允许修复并全部重跑受影响实验。

---

# 19. 最终可以声称与不能声称的结论

## 19.1 可以声称

若实验支持，可以写：

- CAPD 在统一主动降级 Replay 中优于 Proactive-LRU、Proactive-CLOCK 和 TPP-inspired；
- Proactive-LRU 相比 Reactive-LRU 能减少空闲页框耗尽，并维持更稳定的页框储备；
- Top-\(b_t\) 能降低平均单页推理开销；
- CAPD 在高内存压力场景下更有价值；
- CAPD 的主要结果在多个 Cost profile 和标签权重附近保持稳定；
- 参数化异步实验表明 CAPD 在一定页面进入负载范围内能够及时补充页框。

---

## 19.2 不能声称

不能写：

- 已完成真实 Linux 系统集成；
- 已完整复现 Linux TPP；
- 已测得真实程序端到端加速；
- 已支持多进程/mixed workload；
- 已处理完整 promotion 机制；
- CAPD 在所有容量和 workload 下都优于 baseline；
- 参数化异步结果等同于真实内核运行结果。

---

# 20. 最终实验叙事

最终实验章节建议围绕下面的逻辑展开：

```text
第一步：
在统一主动降级水位下，
CAPD 是否比其他页面排序方法选得更好？

第二步：
更好的排序是否减少了 NVM 访问、
写入、无效降级和 weighted cost？

第三步：
主动水位是否能够提前建立页框储备，
减少空闲页框耗尽和紧急回退？

第四步：
Top-b 批量选择是否在保持质量的同时，
降低了平均单页推理开销？

第五步：
扩大到更合理容量、更多 workload、
更强 baseline 后，结论是否仍成立？

第六步：
结合实测 CPU 推理延迟和参数化异步模型，
CAPD 后台运行是否具有可行性？
```

最终正式结论应表述为：

> CAPD 在 DRAM 空闲页框低于触发水位时，利用近期访存上下文和候选页面状态进行主动页面降级排序，并通过有界批量选择逐步恢复目标页框储备。实验通过 Reactive-LRU 与 Proactive-LRU 隔离主动储备机制的作用，并从页面选择质量、空闲页框保障、提前误降风险、批量摊销开销、容量扩展、TPP-inspired 强基线和异步后台能力等方面进行验证，从而证明 CAPD 在单线程、单进程、单 workload 的统一 Trace Replay 场景下具有更完整的系统有效性和可实现性证据。
