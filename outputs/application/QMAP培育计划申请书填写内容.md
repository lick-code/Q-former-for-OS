# 面向 DRAM/NVM 混合内存的代价感知学习型页面迁移策略研究



## 基本信息建议填写

- 资助类别：本科生项目

- 填报日期：2026 年 5 月 30 日

- 项目名称：面向 DRAM/NVM 混合内存的代价感知学习型页面迁移策略研究

- 英文名称：Cost-Aware Learning-Based Page Migration for DRAM/NVM Hybrid Memory

- 申请代码1：计算机系统结构方向（请按最新版国家自然科学基金申请代码核对后填写）

- 申请代码2：人工智能与系统软件交叉方向（可空白，待导师确认）

- 研究期限：2026.07—2027.06

- 研究方向：计算机系统结构；存储系统；智能内存管理；学习型系统

- 申请资助经费：按本科生项目资助额度上限申请（具体金额待学院通知确认）

- 中文关键词：混合内存；页面迁移；缓存替换；代价感知排序；学习型系统

- 英文关键词：Hybrid memory; Page migration; Cache replacement; Cost-aware ranking; Learned systems



## 中文摘要

随着高容量非易失性存储器（NVM）进入主存层次，DRAM/NVM 混合内存正在成为缓解容量、成本与能耗矛盾的重要系统形态。但 NVM 读写代价不对称、写入寿命敏感、页面迁移开销显著，使传统基于最近性或频率的 LRU、LFU、CLOCK 等策略难以同时优化命中率、写入代价与迁移代价。本项目拟研究一种面向混合内存的代价感知学习型页面迁移策略 QMAP：将一次 DRAM miss 触发的页面迁移建模为候选页面排序问题，利用访问历史、程序上下文、读写类型和候选页状态特征，学习选择最适合迁出 DRAM 的页面。现有原型已完成从真实访存 trace 采集、训练样本生成、模型训练到 trace-driven replay 评估的闭环，并在 PARSEC 真实 workload 的 streamcluster pressure window 上相较最佳传统基线降低 12.35% 加权访问代价、减少约 38.0% 迁移次数。本项目将在此基础上进一步研究更稳健的候选页排序、写敏感损失函数、压力窗口识别与在线自适应机制，形成可复现实验平台、核心算法原型和高水平论文成果。



## 英文摘要

DRAM/NVM hybrid memory is becoming a promising architecture for reconciling memory capacity, cost, and energy efficiency. However, NVM has asymmetric read/write costs and non-negligible migration overhead, so conventional recency- or frequency-based policies cannot fully optimize the system-level cost. This project studies QMAP, a cost-aware learned page-migration policy for hybrid memory. QMAP formulates migration as a candidate-page ranking problem: when a DRAM miss triggers replacement, the model scores candidate pages using access history, program context, read/write signals, and page-state features. Our current prototype has established an end-to-end pipeline from real trace collection and sample generation to model training and trace-driven replay. On a PARSEC streamcluster pressure window, QMAP reduces weighted access cost by 12.35% and migrations by about 38.0% compared with the best classical baseline. The proposed work will further improve ranking robustness, cost-aware objectives, pressure-window analysis, and online adaptation, producing a reproducible research platform, a deployable prototype, and publishable systems research results.



## 报告正文

### 1. 项目的立项依据（研究意义，以及对本研究领域现状的梳理和总结。附主要参考文献目录）；

研究意义。DRAM 具有低延迟和高带宽优势，但容量扩展成本高、能耗压力持续上升；NVM 具有更高密度和更好非易失性，但读写延迟、写入能耗和写入寿命均呈现明显非对称性。未来服务器、数据库、AI 数据处理和存储系统很可能长期处于 DRAM 与 NVM、甚至本地内存与远端内存并存的多层次形态。在这类系统中，页面何时保留在 DRAM、何时迁移到 NVM，不再只是传统缓存命中率问题，而是直接影响写放大、迁移次数、访问尾延迟和系统总成本的关键基础问题。

研究现状。经典替换策略如 LRU、LFU、CLOCK 具有低开销、易部署的优点，但其核心假设主要来自单一层次缓存：页面价值通常由最近访问或访问频率刻画。这类策略很少显式建模 NVM 写入代价、页面迁移代价和程序上下文。近年来学习型缓存替换、Belady 近似和系统 trace 驱动优化成为热点，但多数工作聚焦 CPU cache、对象缓存或通用存储缓存，对 DRAM/NVM 混合内存中的页面级迁移问题仍缺少兼顾可训练性、在线开销和真实 trace 验证的统一框架。

问题缺口。现有方法存在三个突出不足：第一，评价指标仍容易偏向命中率，无法充分反映 NVM 写入和迁移代价；第二，策略决策往往只利用页面最近性或频率，缺少对 PC、读写类型、候选页状态等多维信号的联合建模；第三，真实 workload 中不同阶段的迁移压力差异很大，标准切分可能掩盖策略差异，导致算法结论不稳定。本项目拟围绕这些缺口开展基础研究，将页面迁移重构为“代价感知候选排序”问题，为混合内存系统提供更具解释性和可复现性的策略框架。

主要参考文献目录：
[1] L. A. Belady. A study of replacement algorithms for a virtual-storage computer. IBM Systems Journal, 1966.
[2] E. J. O'Neil, P. E. O'Neil, and G. Weikum. The LRU-K page replacement algorithm for database disk buffering. SIGMOD, 1993.
[3] S. Jiang and X. Zhang. LIRS: An efficient low inter-reference recency set replacement policy. SIGMETRICS, 2002.
[4] N. Megiddo and D. S. Modha. ARC: A self-tuning, low overhead replacement cache. FAST, 2003.
[5] M. K. Qureshi et al. Scalable high performance main memory system using phase-change memory technology. ISCA, 2009.
[6] B. C. Lee et al. Architecting phase change memory as a scalable DRAM alternative. ISCA, 2009.
[7] C. Bienia et al. The PARSEC benchmark suite: Characterization and architectural implications. PACT, 2008.
[8] N. Beckmann and D. Sanchez. Jigsaw: Scalable software-defined caches. PACT, 2013.
[9] A. Jain and C. Lin. Back to the future: Leveraging Belady's algorithm for improved cache replacement. ISCA, 2016.
[10] D. Berg et al. CacheLib: A general-purpose caching engine. OSDI, 2020.



### 2. 项目的研究内容、研究目标，以及拟解决的关键科学问题（此部分为重点阐述内容）；

研究内容一：代价感知页面迁移建模。项目将 DRAM/NVM 页面迁移抽象为候选页面排序问题：当 DRAM miss 且 DRAM 已满时，从 LRU 尾部或受限候选集合中选取若干候选页，综合页面未来冷度、写敏感性、驻留时间、迁移代价和访问上下文，学习每个候选页的迁出优先级。该建模方式使策略不再局限于“最近是否访问”，而能围绕混合内存真正关心的加权访问代价进行优化。

研究内容二：QMAP-Pool 学习型策略。现有原型已经将最终模型收敛为 QMAP-Pool，即 Transformer Encoder 编码最近访存序列，再通过 mean pooling 获得访问模式表示，最后由候选页 scorer 输出迁移分数。后续将继续研究特征表达、代价感知 ApproxNDCG 排序损失、候选集合构造和保守迁移门控，使模型在保持较低在线推理开销的同时提升跨 workload 稳健性。

研究内容三：真实 trace 驱动的实验体系。项目已基于 DynamoRIO/drmemtrace 采集 PARSEC benchmark 的 PC、Address、RW 访存 trace，并建立 1M 标准切分、pressure window、真实消融和多随机种子稳定性实验。后续将进一步完善数据质量统计、压力窗口识别、跨 workload 对比和失败案例诊断，形成可复现的混合内存页面迁移评测框架。

研究目标。项目计划在 12 个月内形成一套可复现实验平台和一类可解释的学习型页面迁移算法：在具有明显迁移压力的真实 workload 中，力争相较最佳传统基线进一步降低加权访问代价和迁移次数；在工作集较小或策略空间有限的 workload 中保持不劣于强基线；在 canneal 等已暴露负例中识别过度迁移原因并提出抑制机制。最终产出包括算法原型、实验数据与脚本、论文初稿/投稿版本，以及面向后续系统落地的技术路线。

拟解决的关键科学问题包括：第一，如何在有限在线上下文中刻画页面的“未来冷度”和“写敏感性”，使学习目标与真实混合内存代价一致；第二，如何在候选页数量有限、workload 相位变化明显的情况下学习稳健排序，而不是过拟合单一 trace；第三，如何在收益与在线开销之间取得平衡，使学习型策略具备系统可部署性；第四，如何用真实 trace、压力窗口、消融和多 seed 共同构成可信证据链，避免只报告偶然正例。



### 3. 拟采取的研究方案及可行性分析（包括研究方法、技术路线、实验手段、关键技术等说明）；

总体技术路线为“真实 trace 采集—训练样本构建—代价感知排序学习—trace-driven replay 评估—失败边界诊断—稳健策略优化”。首先，使用 DynamoRIO/drmemtrace 采集用户态访存记录并转换为 PC,Address,RW 格式；其次，按时间顺序切分训练、验证和测试数据，并在存在迁移压力的阶段构造 pressure window；再次，生成包含访问历史、候选页状态、读写类型和代价标签的 JSONL 样本；随后训练 QMAP-Pool，并与 LRU、Random、LFU、CLOCK 进行统一 replay 对比；最后通过消融、参数敏感性和多随机种子验证收益来源与稳定性。

核心方法一：代价感知排序损失。项目将页面迁移决策从二分类或单点回归扩展为候选列表排序，综合 inactivity、coldness、write_sensitivity 和 migration_cost 构造相关性标签，并采用可微 ApproxNDCG 损失优化整个候选列表。这一方法更符合替换决策的本质：系统真正需要的是在一组候选页中找到最值得迁出的页面，而不是孤立判断单个页面好坏。

核心方法二：轻量化序列编码与候选页打分。现有实验表明，较复杂的 Q-Former 在当前数据规模下并不稳定，mean pooling 结构更简单、推理开销更低、结论更清晰。因此本项目采用单层 Transformer Encoder 加 mean pooling 的 QMAP-Pool 作为主线，并重点优化候选页特征、排序损失和保守门控，而不是盲目堆叠模型复杂度。

核心方法三：真实工作负载与压力窗口评估。标准测试段在某些 workload 中可能缺少 eviction 压力，例如 streamcluster 标准测试段所有策略几乎完全相同。项目将引入 pressure window 分析，专门评估有大量迁移决策的阶段。现有结果显示，在 streamcluster pressure window 上，QMAP-Pool 相较最佳 baseline CLOCK 将加权访问代价从 301,767 降至 264,501，降低 12.35%；迁移次数从 8,937 降至 5,541，降低约 38.0%，说明该路线已经具备扎实可行性。

可行性基础。当前仓库已经完成 qmap_generator、qmap_train、qmap_eval、run_real_workload_suite、run_real_ablation、run_seed_stability 等核心脚本，具备从 trace 到结果表格的闭环；已经完成合成 workload、PARSEC 1M 真实 trace、pressure window、真实消融和多 seed 实验；已明确 QMAP-Pool 在 streamcluster pressure window 和 blackscholes 上稳定优于最佳 baseline，在 dedup 上基本持平，在 canneal 上稳定失败。上述正例、边界和负例共同说明项目不是空泛设想，而是具备明确问题、原型基础、数据基础和继续攻关空间的研究课题。



### 4. 年度研究计划及预期研究结果。

2026 年 7 月—2026 年 9 月：完成研究口径冻结与数据体系整理。重点完善 PARSEC trace 采集与清洗规范、训练/验证/测试切分、数据统计报告和实验配置管理；形成可复现实验手册和第一版技术报告。

2026 年 10 月—2026 年 12 月：开展核心算法优化。重点研究候选页排序稳定性、代价感知损失权重、过度迁移抑制机制、QMAP 与 LRU/LFU/CLOCK 的混合选择策略；在 streamcluster、blackscholes、dedup、canneal 等 workload 上完成系统消融和失败案例诊断。

2027 年 1 月—2027 年 3 月：扩展评估与论文撰写。补充更多真实 workload 或更长 trace，完善多 seed、参数敏感性和在线开销评估；形成完整论文实验章节、图表和方法描述，准备向系统/存储方向会议或研讨会投稿。

2027 年 4 月—2027 年 6 月：完成成果凝练与结题材料。整理开源代码、实验脚本、数据说明和复现文档；形成最终研究报告、论文投稿版本和后续系统落地计划。预期成果包括：1 篇高质量系统方向论文初稿或投稿；1 套可复现 QMAP 原型与实验平台；若条件成熟，进一步申请软件著作权、专利或参与相关竞赛/科研展示。



### （二）研究基础（与本项目相关的研究工作积累，以及为开展本项目研究做的思考和准备）。

本项目已具有较强前期积累。申请人所在团队已经完成 QMAP 原型的最小可训练闭环：CSV trace 经过 qmap_generator 生成训练样本，qmap_train 训练得到 checkpoint，qmap_eval 进行 trace-driven replay，并统一输出命中率、NVM 写入次数、迁移次数、加权访问代价和决策延迟等指标。项目已支持 LRU、Random、LFU、CLOCK 与 QMAP-Pool 的统一比较，具备开展系统研究所需的实验基础设施。

在数据与实验方面，项目已经从早期合成 trace 扩展到真实 PARSEC workload。现有数据包括 blackscholes、canneal、streamcluster、dedup 的 1M 真实访存 trace，并记录 unique pages、unique PCs、写比例和 reuse ratio 等统计信息。已完成标准时间切分、pressure window、真实消融和多随机种子稳定性实验。其中 streamcluster pressure window 是最强真实正结果，QMAP-Pool 相较最佳传统基线降低 12.35% 加权访问代价；blackscholes 在三个随机种子下稳定小幅优于 LFU；canneal 则构成稳定负例，为后续研究过度迁移抑制提供了明确靶点。

在模型与方法方面，项目已经从较复杂的 Q-Former 路线收敛到更稳健、更轻量的 QMAP-Pool。该选择不是简单降级，而是基于消融和结构对比得到的系统性判断：mean pooling 在多个场景中更稳定，在线开销更低，论文主线也更清晰。当前思考重点已经从“能否训练出一个模型”转向“如何让模型在真实 workload 的迁移压力阶段稳健有效”，这体现了项目从工程原型向基础研究问题的提升。

申请人已围绕本课题完成代码阅读、实验脚本整理、真实 trace 数据处理、实验结果汇总和论文雏形构建等工作，具备继续推进该项目所需的编程、系统实验和学术写作基础。下一阶段的核心准备是把现有结果进一步理论化、系统化和可复现化，明确学习型页面迁移策略的适用边界与优化方向。



### （三）已（拟）确定的论文题目及概要（如尚未确定论文题目本项可空白）。

拟定论文题目：QMAP: Cost-Aware Learned Page Migration for DRAM/NVM Hybrid Memory（中文题目：QMAP：面向 DRAM/NVM 混合内存的代价感知学习型页面迁移）。

论文概要：论文拟围绕 DRAM/NVM 混合内存中的页面迁移问题展开，指出传统替换策略以最近性或频率为核心，难以同时处理 NVM 写入代价、页面迁移代价和 workload 相位变化。论文提出 QMAP，将页面迁移建模为候选页排序问题，利用访问历史、程序上下文、读写类型和候选页状态特征学习迁移优先级，并通过代价感知排序损失优化系统级加权访问代价。实验部分将基于 PARSEC 真实 trace、pressure window、真实消融和多 seed 稳定性进行评估。论文将采取克制但有说服力的主张：QMAP 不是在所有 workload 上替代经典策略，而是在具有明显迁移压力和写敏感性的真实阶段中，能够显著降低加权访问代价，并揭示学习型页面迁移策略的收益条件与失败边界。



### （四）本项目的特色与创新之处。如有论文题目需阐明与论文研究内容的不同，或在论文基础上的实质性拓展延伸之处。

第一，问题建模具有创新性。项目不是简单把机器学习模型套用到缓存替换，而是从 DRAM/NVM 混合内存的物理代价出发，将页面迁移建模为代价感知候选排序问题，使训练目标、系统指标和决策动作保持一致。

第二，特征体系更贴近真实系统。QMAP 同时利用页面地址、程序计数器、读写类型、候选页状态、驻留时间和 LRU 候选排名等信号，能够捕获传统 LRU/LFU/CLOCK 难以表达的访问上下文和写敏感性，为混合内存页面迁移提供更细粒度的决策依据。

第三，评价方法强调可信证据链。项目不仅报告标准测试集结果，还引入 pressure window 解决真实 trace 中迁移压力不足的问题，并通过消融实验和多随机种子验证收益来源与稳定性。这种评价设计比单一平均命中率更符合系统研究规范，也能避免过度包装偶然正例。

第四，项目具有清晰的边界意识和继续拓展价值。现有结果既包含 streamcluster pressure window 的显著正例，也包含 canneal 的稳定负例。项目将负例转化为关键科学问题，进一步研究保守迁移门控、混合策略选择和在线自适应机制。这使本项目不仅能形成一篇论文，还能发展为学习型内存管理策略的持续研究方向。



### （五）其他需要说明的情况。

本项目不涉及国家秘密、个人敏感信息或不适宜公开传播的内容。实验数据主要来自公开 benchmark 的访存 trace 和项目自建合成 workload，研究过程以 trace-driven replay 和开源工具链为主，不涉及人体试验或伦理风险。

项目申请经费拟主要用于实验计算资源、数据存储、论文版面/投稿相关支出、学术交流和必要的软件/硬件测试环境维护。项目将坚持可复现原则，尽量保留配置、脚本、随机种子、结果表格和失败案例记录，确保结题材料和论文成果具有可核验性。



## 申请人简历

### 山东大学， 学院，本科生/研究生

山东大学，计算机科学与技术学院，人工智能专业 2023 级本科生。



### （一）教育经历（从本科开始）；

2023.09—至今，山东大学计算机科学与技术学院，人工智能专业本科在读。系统学习程序设计、数据结构、计算机系统、人工智能、机器学习等课程，具备计算机系统实验、Python/PyTorch 编程和科研写作基础。



### （二）曾参与的科研项目或科技活动；

深度参与 QMAP 混合内存页面迁移策略研究，完成真实访存 trace 处理、QMAP 训练与 replay 评估脚本整理、baseline 对比、消融实验、多随机种子稳定性实验和论文材料准备。项目已形成从数据采集、样本生成、模型训练到实验汇总的完整闭环。



### （三）本科以来学业成绩，发表论文或专利，以及获得奖励情况。

本科以来学业成绩、绩点/排名、奖学金、竞赛奖励、论文或专利情况请申请人补充。建议突出与计算机系统、人工智能、科研训练、数学基础和工程实现能力相关的课程成绩与获奖经历。



## 推荐意见草稿

### advisor

【以下为推荐意见草稿，需导师/指导教师本人审阅修改后签名】
李康诚同学在本项目中表现出较强的系统研究兴趣、工程实现能力和持续攻关能力。项目选题聚焦 DRAM/NVM 混合内存中的页面迁移策略，具有明确基础研究价值和系统应用前景。申请人已完成真实 trace 处理、模型训练、baseline 对比、压力窗口实验和多随机种子稳定性分析等前期工作，说明其具备开展本项目的必要基础。该项目目标清晰、技术路线可行、已有结果扎实，若获得培育支持，有望形成高质量论文和可复现实验平台。本人同意推荐。



### expert1

【以下为推荐意见草稿，需专家本人审阅修改后签名】
该项目面向 DRAM/NVM 混合内存体系中的页面迁移问题，抓住了新型存储介质进入主存层次后带来的关键系统挑战。项目将页面迁移建模为代价感知候选排序问题，能够同时考虑访问历史、程序上下文、读写类型、NVM 写入代价和迁移代价，具有较好的问题意识和创新性。申请团队已经完成真实 PARSEC trace、压力窗口、消融和稳定性实验，前期基础较扎实。项目预期成果明确，具备继续培育为高水平系统研究论文的潜力。建议予以支持。



### expert2

【以下为推荐意见草稿，需专家本人审阅修改后签名】
本项目具有鲜明的交叉特点，将机器学习中的排序建模方法用于计算机系统中的混合内存页面迁移决策，研究内容兼具理论问题和系统验证价值。与单纯追求缓存命中率的替换策略不同，项目强调加权访问代价、NVM 写入次数和迁移次数等系统级指标，评价体系较为严谨。申请人已取得初步实验结果，并能够客观分析正例、边界案例和失败场景，体现出较好的科研判断力。项目方案可行，建议推荐立项培育。

