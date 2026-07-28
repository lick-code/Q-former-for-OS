# CAPD memory trace 数据质量系统审查

审查日期：2026-07-28  
审查状态：**ANALYZED（数据与代码已静态审查并完成本地重算；PID/TID、原始 drmemtrace 目录和跨运行稳定性未被现有材料验证）**

## 0. 结论先行

当前三组 trace **可以支持“同一次程序运行内、按时间顺序切分、页级访问流上的 CAPD 训练与回放”**。完整扫描未发现随机/步长抽样、事件去重、重复拼接、split 重叠、历史断裂或 future-label 越界；三组 source 共 5,000,000 条事件，processed split 与声明的 source 区间逐字节完全相等。B64 的 28,386 个 train/valid 决策样本经独立重算，历史、PC/RW、决策时点、候选驻留性和未来 256 条标签均为 0 错误。

但它们**不能单独证明跨重启、跨 ASLR 的泛化能力，也不能从最终 CSV 证明只有一个 PID/TID**。原因是：

1. `PC,Address,RW` 中没有 PID、TID、模块基址或运行编号；采集日志和原始 `.dir` 也未随数据保留。
2. 三个 workload 的 train/valid/test 都来自同一个 collection 的不同连续区间，而不是三次独立运行。因此没有事件级泄漏，却共享同一套绝对 PC/VPN 地址命名空间。
3. CSV 的 `Address` 默认已被 4 KiB 对齐，是**虚拟页基址**，不是原始字节级 VA，更不是物理地址。原始页内偏移已经不可恢复。
4. 现有模型输入仍包含绝对 `history_page_ids` 和绝对 PC。若论文声称跨运行泛化，当前设计和数据不足以排除模型记忆本次运行地址身份的可能。

因此，最终判断是：

- **trace 本体：可用，整体为 WARNING，不需要因为抽样、split、history 或 label 问题重采。**
- **当前实验包：适合限定为同一运行内的时序评估；不适合直接作为跨运行/跨 ASLR 泛化证据。**
- **优先处理方式：先改表示与方法描述，再决定是否补采。不要改采物理地址；物理帧号比虚拟地址更不稳定，也不能解决 ASLR。**
- **必须补采的情形：**若最终论点包含“程序重启后仍有效”“跨地址布局泛化”或需要严格证明单 PID/TID，则至少补采每个 workload 的第二次独立运行，并保留 PID/TID、模块映射、原始 drmemtrace 元数据和完整日志。

## 1. Material Passport 与审查边界

### 1.1 审查对象

| workload | source trace | collection | 事件数 | 官方 split |
|---|---|---:|---:|---|
| canneal | `dataset/raw_traces/finals_v3_recollect/candidate_500m_1m/canneal_native_pilot.csv` | `canneal-20260722T125000` | 1,000,000 | 600k / 200k / 200k |
| streamcluster_pressure | `dataset/raw_traces/finals_v3_recollect/candidate_5b_1m/streamcluster_native_pilot.csv` | `streamcluster_pressure-20260722T133000` | 1,000,000 | 600k / 200k / 200k |
| dedup_pressure | `dataset/raw_traces/finals_v3_recollect/candidate_native_100m_3m/dedup_native_pilot.csv` | `dedup_pressure-20260722T131403` | 3,000,000 | 1m / 1m / 1m |

collection、命令、source SHA-256 和 split 半开区间分别封存在：

- `dataset/metadata/finals_v3_official/canneal.json:7-59,83-164`
- `dataset/metadata/finals_v3_official/streamcluster_pressure.json:7-59,83-164`
- `dataset/metadata/finals_v3_official/dedup_pressure.json:7-59,83-164`

模型合同取自 `configs/finals/capd_direction1_v3.json:7-31`：D=64、H=10、L=256；三组 train/valid/test 路径位于该文件 `101-119` 行。

### 1.2 本次实际完成的检查

- 全量扫描 5,000,000 条 source 记录，而不是只抽样。
- 另以固定种子 `20260728` 对每个 workload 随机抽取 10,000 条做字段合法性检查。
- 以 50,000 条为窗口分析 unique page、unique PC、R/W 比例、相邻窗口 page/PC/top-20-page Jaccard 和 split 边界。
- 重算页频率、复用间隔、绝对 VPN 跳变分布。
- 对 9 个 processed CSV 做 source 区间逐字节比对和 SHA-256 比对。
- 按 UTF-8 解析 60 个主 JSON 配置/元数据文件，60/60 成功；解析 36 个主 JSONL，共 145,024 行，145,024/145,024 成功。
- 对 B64 的 6 个 train/valid JSONL 共 28,386 个决策样本逐条独立重放 LRU(D=64)，并从 CSV 直接重算 H=10 历史和 L=256 future labels，0 错误。
- 运行 `python -m unittest tests.test_generator_replay_feature_equivalence -v`，1/1 通过。

### 1.3 不能验证的材料

仓库没有本次 finals_v3 对应的原始 drmemtrace `.dir`、`serial_schedule.bin`、模块映射、PID/TID 清单或 `drmemtrace.view.log`。manifest 中记录的是当时 WSL 路径，不能在当前工作区回查。因此关于“实际生成了几个进程/线程文件”和“多线程事件如何被全局排序”只能给 WARNING，不能给 PASS。

## 2. 数据流与真实采集语义

实际链路为：

```text
PARSEC target
  -> drrun -t drmemtrace -offline
  -> drraw2trace
  -> drmemtrace view（串行文本流）
  -> 仅匹配 read/write 数据引用
  -> PC + 4KiB 对齐后的虚拟页基址 + R/W CSV
  -> 明确半开区间切分 train/valid/test
  -> 顺序 LRU 状态机生成 JSONL 历史、候选和 future labels
  -> 同一 split CSV 顺序回放
```

### 2.1 采集命令

collector 在 `scripts/collect_trace_drmemtrace.py:136-159` 构造：

```text
drrun -t drmemtrace -offline -outdir <work-dir>
      -trace_after_instrs <warmup>
      -exit_after_tracing <trace-ref-budget>
      -- <PARSEC target>
```

三组 manifest 的命令表明：

- canneal：500,000,000 条 instruction warm-up 后取 1,000,000 条 data refs；使用 `gcc-serial` binary。
- streamcluster：5,000,000,000 条 instruction warm-up 后取 1,000,000 条 data refs；pthread binary 的最后一个参数为 `1`。
- dedup：100,000,000 条 instruction warm-up，converter 再连续跳过前 100,000 条 data refs，然后取 3,000,000 条；命令显式为 `-t 1`。

这些 trace 是**稳态连续窗口**，不是完整程序执行。`trace-ref-multiplier=100` 只扩大 drmemtrace 捕获预算，因为 drmemtrace refs 还包括 instruction fetch（`scripts/collect_trace_drmemtrace.py:137-155`）；它不是“每 100 条取 1 条”。

### 2.2 采样、过滤、合并审查

converter 的正则只接受 `read|write ... @ address by PC pc`（`scripts/convert_drmemtrace_view.py:20-24`），因此 instruction fetch 被排除；匹配后的 data refs 按输入顺序计数，先连续跳过 `skip`，再连续写入到 `limit`（同文件 `34-59`）。

审查结论：

- 无 `random.sample`、`numpy.random.choice`、`train_test_split` 或等价随机抽样进入官方 trace 链路。
- 无 stride/downsample、周期抽样或“只保留 miss/page fault”的过滤。
- 无事件去重。
- 无多个 CSV 拼接；finalizer 只从一个声明 source 按区间物化。
- 有意过滤 instruction fetch，只保留 data read/write；这与 CAPD 页替换输入目标一致。
- dedup 的 `skip-records=100000` 是一次连续前缀裁剪，不破坏保留区间内部连续性。

一个实现风险是：若 work-dir 中找到多个 `.dir`，collector 只打印提示并选择 `trace_dirs[0]`（`scripts/collect_trace_drmemtrace.py:166-180`），不会验证另一个目录是不是 child process。官方 wrapper 会拒绝覆盖已有 work-dir（`scripts/collect_finals_v3_recollect.py:277-287`），降低了“陈旧目录混入”的概率，但由于原始目录未保留，无法事后证明当时只有一个 `.dir`。

### 2.3 地址到底是什么

采集命令没有启用 DynamoRIO 的 physical-address 转换。DynamoRIO 官方说明普通 drmemtrace 使用虚拟地址，只有专门的 physical-address 流程才会转换；参见 [DynamoRIO Physical Addresses](https://dynamorio.org/sec_drcachesim_phys.html)。

随后 converter 默认执行：

```python
address = address & ~((1 << 12) - 1)
```

证据位于 `scripts/convert_drmemtrace_view.py:27-31,50-55`。因此 CSV 的 `Address` 是 4 KiB 对齐的**虚拟页基址**。`qmap/qmap_generator.py:140-156` 再执行 `page = address >> 12`，得到 VPN；这不是错误的“双重分页”，而是从页基址得到页号。

后果：

- 页级回放语义正确。
- `unique Address` 等于 `unique VPN`；原始字节级 VA 的 unique 数量和页内 offset 分布不可恢复。
- 不能把当前字段称为 physical address，也不应在论文里声称保留了完整 `(PC, raw VA, R/W)`。

## 3. 单次运行、单进程与线程来源

### 3.1 单次运行一致性

每个 workload manifest 只有一个 collection ID、一个 collector command、一个 source trace 和一个 source SHA-256；finalizer 从这个 source 生成所有 split。源码没有把多次运行 CSV 合并的路径。首尾记录及固定 33-byte 记录宽度连续存在：

| workload | first record | last record |
|---|---|---|
| canneal | `0x7483b47f4113,0x7fffc529b000,W` | `0x7483b47f4200,0x7483b66dc000,R` |
| streamcluster_pressure | `0x747bb4bf4c3a,0x74796eb23000,R` | `0x747bb4bf4b48,0x747970558000,R` |
| dedup_pressure | `0x7925917a0e8f,0x7922f9d3a000,W` | `0x79258dfd99b9,0x792318000000,R` |

没有发现某个 split 边界同时发生 PC 命名空间整体平移、地址范围整体替换和 R/W 模式重置的组合证据。A 项给 PASS。

### 3.2 单进程/单线程不能被最终 CSV 证明

DynamoRIO 的原始 `memref_t` 含 PID/TID，offline trace 通常按软件线程保存，再由分析器形成串行 interleaved stream；参见 [Trace Format](https://dynamorio.org/sec_drcachesim_format.html) 与 [Creating New Analysis Tools](https://dynamorio.org/sec_drcachesim_newtool.html)。调试文档还说明每线程缓冲区、timestamp/CPU header 等会参与离线调度重建，参见 [Debugging Traces](https://dynamorio.org/page_debug_memtrace.html)。

本项目通过 `view` 文本再用正则只提取 PC、address、R/W，PID/TID 被永久丢弃。因此：

- canneal 的 serial binary 是强证据，但仍没有最终 PID/TID 字段。
- streamcluster 和 dedup 都配置了 1 个 worker，是降低风险的证据；但 pthread runtime/helper thread 是否产生 data refs 无法从 CSV 检查。
- 若原 trace 有多线程，当前 CSV 是工具给出的 merged stream；不能把它表述为经过硬件级全序证明的单线程流。

所以 B 项三者均为 WARNING；C 项 canneal 为 PASS，另外两者为 WARNING。

## 4. PC、VA、R/W 完整统计

### 4.1 基本字段

| workload | refs | unique PC | top-20 PC share | unique aligned VA/VPN | R | W | W ratio | zero PC/address | invalid RW |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| canneal | 1,000,000 | 900 | 39.2653% | 2,836 | 737,968 | 262,032 | 26.2032% | 0 / 0 | 0 |
| streamcluster_pressure | 1,000,000 | 28 | 91.6467% | 11,113 | 987,615 | 12,385 | 1.2385% | 0 / 0 | 0 |
| dedup_pressure | 3,000,000 | 1,324 | 33.9228% | 10,066 | 2,166,910 | 833,090 | 27.7697% | 0 / 0 | 0 |

PC 与地址范围：

| workload | PC min–max | aligned VA min–max |
|---|---|---|
| canneal | `0x7483b47f2324`–`0x7483b7f4ebfc` | `0x7481655b0000`–`0x7fffc529b000` |
| streamcluster_pressure | `0x747bb4bf4b00`–`0x747bb4bf5590` | `0x747968000000`–`0x747bb84cb000` |
| dedup_pressure | `0x79258dfd82e4`–`0x7925917a110a` | `0x7922f9d37000`–`0x7ffdc969b000` |

全量记录均为低半区 canonical user-space 数值，且地址全部 4 KiB 对齐。固定种子 10,000 条/工作负载抽样再次得到：zero PC=0、zero address=0、unaligned=0、invalid RW=0。

解释：streamcluster 只有 28 个 PC 且 top-20 占 91.65%，从“字段有效”角度不是错误；其 20 个 50k 窗口的 PC 集合完全相同（相邻 PC Jaccard=1），符合小型紧循环扫描大量数据页的行为。但这意味着 PC 信号熵很低，模型对该 workload 的 PC embedding 贡献可能有限，应该在 no-PC ablation 中验证。

### 4.2 绝对 PC/VPN 的 ASLR 风险

PC 与 VPN 在本次运行内部稳定，因此同一 source 的 chronological split 会共享绝对地址命名空间。这不构成事件重复泄漏，却使模型有机会学习 run-specific identity。配置把 valid 称为 `independent_valid_trace`（`configs/finals/capd_direction1_v3.json:50-58`），而 manifests 明确表明 train/valid/test 使用同一个 collection ID；这里的 “independent” 只能解释为**不重叠区间**，不能解释为独立运行。

建议的长期方法不是采物理地址，而是：

1. 主路径由 absolute page identity 转向 candidate-relative / behavior-based features：近期访问次数、距离上次访问、是否在最近 H 次出现、读写比例、dirty、residency、reuse、region/relative relation。
2. PC 若保留，优先记录模块映射并使用 `module_id + module-relative offset`；没有模块映射时，不应声称绝对 PC 跨运行稳定。
3. 在第二次独立运行上做 Run-1 train / Run-2 test；这是检验 ASLR 稳健性的实验，不应被同一 run 的 valid 替代。
4. 论文方法描述需要相应调整：当前实现应准确描述为“绝对 VPN/PC 的同运行序列建模”；完成行为化表示后，才描述为地址身份不变的候选页行为建模。

## 5. 页面学习信号与复用丰富度

### 5.1 页访问频次

| workload | median | P90 | P95 | P99 | max | one-touch | pages ≥2 / ≥5 / ≥10 | top-1% page share |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| canneal | 30 | 105 | 250.75 | 1,718.35 | 554,973 | 33 (1.1636%) | 2,803 / 2,674 / 2,561 | 80.6152% |
| streamcluster_pressure | 32 | 64 | 64 | 189.84 | 396,374 | 978 (8.8005%) | 10,135 / 10,134 / 10,134 | 60.3419% |
| dedup_pressure | 128 | 128 | 128 | 1,012 | 774,848 | 3 (0.0298%) | 10,063 / 10,020 / 10,011 | 57.1077% |

### 5.2 复用间隔（以事件数计）

| workload | reuse events | ratio | median | P90 | P95 | P99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| canneal | 997,164 | 99.7164% | 2 | 31 | 180 | 1,852 | 946,201 |
| streamcluster_pressure | 988,887 | 98.8887% | 3 | 9 | 12 | 405 | 980,739 |
| dedup_pressure | 2,989,934 | 99.6645% | 1 | 29 | 29 | 29 | 1,276,653 |

三组数据都不是“几乎全 streaming、没有 reuse”的退化 trace。短期复用非常强，同时保留长尾复用；这对学习 recency/frequency/future reuse 是充足信号。高热点集中度是真实负载特征，但也意味着应同时报告 LRU/LFU 等简单基线，防止把热点可预测性误当成模型独有能力。

## 6. 50k 时间窗口与突变分析

| workload | windows | unique pages/window median (max) | unique PCs/window median (max) | W ratio min–median–max | adjacent page Jaccard min/median | adjacent PC Jaccard min/median |
|---|---:|---:|---:|---:|---:|---:|---:|
| canneal | 20 | 415 (432) | 767 (836) | 0.26016–0.26205–0.26356 | 0.1853 / 0.2130 | 0.9115 / 0.9909 |
| streamcluster_pressure | 20 | 710 (724) | 28 (28) | 0.01236–0.01238–0.01240 | 0.0185 / 0.0248 | 1.0000 / 1.0000 |
| dedup_pressure | 60 | 216 (377) | 477.5 (906) | 0.04436–0.26776–0.46186 | 0.0054 / 0.0494 | 0.0586 / 0.6163 |

解释：

- canneal 的页集合缓慢轮换，但 PC 与写比例稳定；20 个窗口的 PC min/max 完全相同。
- streamcluster 的页 Jaccard 很低，但 28 个 PC 在每个窗口完全相同，写比例几乎恒定。这是固定循环扫描不同数据块的典型表现，不像重新启动后 PC 命名空间整体变化。
- dedup 存在显著阶段行为；最大相邻窗口写比例变化为 0.38872，最低 PC Jaccard 为 0.0586。其变化发生在多个内部位置，而非只发生在 split 边界，符合压缩/哈希/I/O pipeline 阶段切换。split=1,000,000 处 PC Jaccard=0.6366，split=2,000,000 处为 0.8496，均不是全 trace 最低值。

split 边界本身：

| workload | boundary | page Jaccard | PC Jaccard | W-ratio delta |
|---|---:|---:|---:|---:|
| canneal | 600k / 800k | 0.2255 / 0.2127 | 0.9909 / 0.9974 | 0.00068 / 0.00058 |
| streamcluster_pressure | 600k / 800k | 0.0245 / 0.0229 | 1.0000 / 1.0000 | 0 / 0 |
| dedup_pressure | 1m / 2m | 0.0665 / 0.3684 | 0.6366 / 0.8496 | 0.25122 / 0.02872 |

dedup 在 1m 边界附近确有 workload phase 变化，但 raw source 在该处字节连续，PC 地址仍处于同一全局范围，且更强变化在其他内部位置也出现；证据支持“正常 phase boundary”，不支持“多次运行拼接”。

## 7. 相邻 VPN 跳变分析

| workload | median | P90 | P95 | P99 | max pages |
|---|---:|---:|---:|---:|---:|
| canneal | 13,338 | 3,082,881,694 | 3,082,881,694 | 3,085,300,344 | 3,085,303,019 |
| streamcluster_pressure | 6,511 | 2,374,451.6 | 2,387,041 | 2,421,240 | 2,421,321 |
| dedup_pressure | 0 | 96,930 | 131,023 | 213,060 | 1,839,900,319 |

这些大跳变本身不能被当成拼接证据：

- canneal 约 49.05% 的相邻事件跨越十亿页，最大跳变反复发生在 `0x7481655b0000` 与栈页 `0x7fffc529b000` 之间，PC 仍在同一稳定范围；这是不同虚拟区间交替访问。
- streamcluster 最大跳变反复发生在 `0x747968000000` 与 `0x747bb7249000`，同时其每个窗口 PC 集合完全相同。
- dedup 超过十亿页的跳变只有 40 次（0.0013%），主要是 `0x79231effc000` 与栈页 `0x7ffdc969b000` 之间切换。

真正可疑的 namespace change 应同时表现为：边界后 PC 集合整体平移、地址区间整体替换、前后窗口几乎无稳定热点且出现一次性重置。当前三组数据未出现该组合。但没有 PID/TID/module map，结论仍是统计支持而非身份级证明。

## 8. split 正确性与泄漏

finalizer 接收明确区间，验证区间合法后调用 `materialize_source_intervals`（`scripts/finalize_finals_v3_recollect.py:189-215`）。物化函数按原 source 的 `enumerate` 顺序逐条写入相应半开区间，不 shuffle（`qmap/finals_data.py:258-304`）。manifest 构建时再次比较 split 的 record hash 与 source range 的 record hash（同文件 `483-504`）。

本次独立逐字节比对结果：

| workload | train | valid | test |
|---|---|---|---|
| canneal | `[0,600000)` exact | `[600000,800000)` exact | `[800000,1000000)` exact |
| streamcluster_pressure | `[0,600000)` exact | `[600000,800000)` exact | `[800000,1000000)` exact |
| dedup_pressure | `[0,1000000)` exact | `[1000000,2000000)` exact | `[2000000,3000000)` exact |

9/9 split 均同时满足 byte-exact 和 manifest SHA-256。事件索引不重叠、顺序未改变，J 项 PASS。

必须区分两种“独立”：

- **事件独立/无 overlap：已证明。**
- **运行独立/跨 ASLR：未满足。** 三个 split 共享同一 collection。

## 9. 历史窗口与 future labels

### 9.1 历史连续性

`LRUBehaviorState` 以 `deque(maxlen=H)` 维护按事件顺序的历史；决策时使用“之前的历史 + 当前 miss”的最后 H 条（`qmap/finals_generator.py:99-137`）。JSONL 生成器对 split trace 逐条 `enumerate`，生成样本后才 `state.advance`（同文件 `375-465`）。

B64 全量独立核对：

| workload/split | trace refs | JSONL decisions | expected LRU decisions | history/PC/RW errors |
|---|---:|---:|---:|---:|
| canneal train / valid | 600,000 / 200,000 | 7,215 / 2,377 | 7,215 / 2,377 | 0 / 0 |
| streamcluster train / valid | 600,000 / 200,000 | 8,694 / 2,839 | 8,694 / 2,839 | 0 / 0 |
| dedup train / valid | 1,000,000 / 1,000,000 | 4,607 / 2,654 | 4,607 / 2,654 | 0 / 0 |

所有 `decision_index` 严格递增；每个 `history_page_ids/pc/rw` 都精确等于该 split 中 `[t-H+1,t]` 的连续事件（不足 H 时才左补零）。没有跨 split 取历史，也没有随机取历史。

### 9.2 future label 连续性

`FutureOracle` 的右边界为 `current+1+L`，因此标签只看 `[t+1,t+L]`；`t+L >= N` 的尾部决策被拒绝（`qmap/finals_generator.py:31-96`）。本次对 28,386 个 B64 样本、每个有效候选重新从 CSV 切片计算：

- next-use / inactivity：0 错误；
- frequency / coldness：0 错误；
- future write count / write sensitivity：0 错误；
- tail 越界：0；
- 非驻留候选：0；
- 决策遗漏或额外决策：0。

每个 split 独立创建 state 和 oracle，所以 future label 不跨 train/valid/test 边界。L 项 PASS。

## 10. 测试与回放是否使用同一事件流

`qmap/qmap_eval.py:1013-1029` 直接从传入的 `trace_path` 读取完整顺序流；主循环为 `for access_index, access in enumerate(trace)`（同文件 `1111-1204`）。QMAP 决策历史同样使用 `(history + [current])[-H:]`（`1150-1161`）。官方 config 将每个 workload 的 replay 输入绑定到相应 processed split（`configs/finals/capd_direction1_v3.json:101-119`）。

此外，`tests/test_generator_replay_feature_equivalence.py:15-53` 显式比较 generator 和 replay 的 `P_t/B_t/K_t`、candidate pages、candidate features、mask 与 ranks；本次直接运行 1/1 通过。

结论：从代码合同和测试看，训练样本生成与 replay 使用同一类按行顺序事件流，未发现 replay 端重采样、重排或换用另一份 trace。M 项 PASS。

## 11. 与学习型缓存替换基本原则的关系

不对 PARROT 论文作逐句复现；这里只检查通用原则：

| 原则 | 当前状态 | 说明 |
|---|---|---|
| chronological access stream | 满足 | source、split、JSONL、replay 均保持顺序 |
| history from real recent accesses | 满足 | H=10 连续历史，含当前 miss |
| future supervision from contiguous lookahead | 满足 | 精确 `[t+1,t+256]`，尾部丢弃 |
| no event overlap between train/valid/test | 满足 | 半开区间与逐字节比对已证明 |
| train/test run independence | 不满足 | 同一 collection 的不同区间 |
| stable identity across ASLR | 未解决 | absolute VPN/PC，且无 module map |
| replay matches generation state contract | 满足 | 静态代码、全量 B64 重算和单测支持 |

## 12. A–M 分项结论

### 12.1 汇总表

| 项 | canneal | streamcluster_pressure | dedup_pressure |
|---|---|---|---|
| A. Single-run consistency | PASS | PASS | PASS |
| B. Single-process consistency | WARNING | WARNING | WARNING |
| C. Temporal continuity | PASS | WARNING | WARNING |
| D. No harmful sampling | PASS | PASS | PASS |
| E. PC validity | WARNING | WARNING | WARNING |
| F. VA validity | WARNING | WARNING | WARNING |
| G. R/W validity | PASS | PASS | PASS |
| H. Reuse richness | PASS | PASS | PASS |
| I. Temporal locality | PASS | PASS | PASS |
| J. Split correctness | PASS | PASS | PASS |
| K. History correctness | PASS | PASS | PASS |
| L. Future-label correctness | PASS | PASS | PASS |
| M. Replay consistency | PASS | PASS | PASS |
| **总体** | **WARNING** | **WARNING** | **WARNING** |

### 12.2 WARNING 的精确定义

- B：CSV 不含 PID/TID，原始 `.dir`/log 未保留，不能证明单进程。
- C：canneal 使用 serial binary；streamcluster/dedup 虽配置 1 worker，但最终流不能排除 helper thread，也不能检查 thread merge。
- E：PC 数值有效且非零，但为绝对虚拟 PC；无模块映射，跨 ASLR 稳定性未知。
- F：地址数值有效且非零，但已页对齐且为绝对虚拟页基址；raw VA/offset/PID 丢失，跨运行页身份不稳定。

这些 WARNING 不表示发现了数据拼接或标签错误；它们表示当前证据不足以支持更强的进程身份与跨运行泛化结论。

## 13. 风险排序与处置建议

### 高优先级

1. **绝对 VPN/PC 的 run-specific shortcut。** train/valid/test 同 run，当前实验不能回答 reviewer 的 ASLR 问题。优先改成 candidate-relative/behavior-based 表示，并增加 no-page-ID、no-PC ablation。
2. **PID/TID provenance 丢失。** 下一版 collector 应在最终事件中保留 `run_id,pid,tid,event_index,pc,raw_va,page_id,rw`，并封存 module map、原始 trace 目录摘要和 view log。
3. **“independent valid trace”措辞过强。** 当前只能写“same-run disjoint chronological validation interval”。若保留 “independent run”，必须补采。

### 中优先级

4. collector 在多个 `.dir` 时选择第一个而非失败。下一版应要求恰好一个目标进程，或显式记录/合并被允许的 PID，并对未知 child process 直接失败。
5. CSV 字段名 `Address` 容易被理解成 raw VA。建议元数据中明确 `address_semantics=page_aligned_virtual_base`；若未来需要 region/module 分析，同时保留 raw VA。
6. streamcluster 的 PC 信号只有 28 个值、top-20 占 91.65%；应通过 no-PC ablation 说明模型收益不是由少数 PC 模式独占。

### 低优先级/正常现象

7. canneal/streamcluster 的大 VPN 跳变主要来自稳定虚拟区间间的反复切换，不是自动的拼接证据。
8. dedup 的阶段突变在多个内部窗口出现，符合 pipeline phase；1m split 附近的变化应在论文中作为 distribution shift 说明，而不是删掉。
9. 高热点与短 reuse 是正常且有利于学习的负载结构；需要强 baseline 和 ablation，而不是重新采成更“平滑”的数据。

## 14. 是否需要重采

| 目标 | 是否重采 | 原因 |
|---|---|---|
| 修复抽样/顺序/split/history/future label | 否 | 当前链路已通过全量审查 |
| 将 absolute VPN 改成行为特征 | 否 | 可由当前连续 trace 重预处理 |
| 去除/消融 absolute PC/VPN | 否 | 可由当前 trace 与模型配置完成 |
| 恢复 raw byte VA、PID/TID、module-relative PC | 是 | 当前 CSV 已丢失，无法后处理恢复 |
| 证明单 PID/TID | 是，或找回原始 `.dir`/log | 当前 manifest 不含身份级证据 |
| 证明跨重启/ASLR 泛化 | 是 | 至少需要独立 Run 2；物理地址不是替代方案 |

建议的最小补采协议：每个 workload 至少两次独立启动；每次使用唯一 `run_id`，保留 PID/TID 和模块映射；原始事件保持连续，不做 stride/random sampling；train 用 Run 1，最终 ASLR robustness test 用 Run 2。若只做同 run 页替换实验，当前 trace 可继续使用，但必须收紧论文结论。

## 15. 验证记录与限制

本地 `scripts/verify_finals_v3_stage2.py` 在本次运行中通过了 generation ancestor、3 个 sealed manifest、3 个 data audit、12 个 B artifact audit、`git diff --check` 和 clean-worktree 检查。总命令最终返回非零，原因是当前 Python 环境缺少 `pytest`，并且仓库已存在后续阶段的 `outputs/checkpoints/finals_v3_official` 与 `outputs/results/finals_v3_official`；后者违反该脚本“阶段 2 时不得已有训练输出”的历史门禁。这两个失败不属于 trace 数据错误，因此本报告不把整套脚本标为全绿，也不把它们误判为数据失败。

本报告的统计为本地重算结果，未写回数据文件。除本报告外，没有修改代码、配置、trace、manifest、JSONL 或实验输出。
