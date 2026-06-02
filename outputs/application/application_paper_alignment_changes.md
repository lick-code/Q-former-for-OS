# QMAP 申请书按论文核对后的修改说明

依据 `D:/下载/HotStorage_2022_Concise_Paper_Template__李康诚_.pdf` 对申请书草稿进行了重新生成式修订，主要变化如下：

1. 将项目定位从较宽泛的“页面迁移”收窄为论文中的“DRAM 容量压力下页驱逐 / victim selection”。
2. 统一方法简称为 QMAP；没有在申请书中采用 PDF 摘要里暂存的 CARVE 名称。
3. 将模型描述更新为“地址、PC、读写标志嵌入 + 单层 Transformer + mean pooling + 候选页状态 MLP scorer”。
4. 将候选页状态更新为论文中的页标识嵌入、近期访问频率、dirty 状态和驻留时间，不再把 LRU 候选排名作为核心论文特征来写。
5. 将实验描述更新为论文口径：PARSEC 1M trace、chronological split、LRU-tail candidate count 8、DRAM capacity 16、lookahead 256、10 epochs。
6. 强化 pressure window 的可信性表述：窗口按 eviction frequency 预先选择，不按 QMAP 表现筛选。
7. 更新核心结果：streamcluster pressure window 降低 12.35% weighted cost，并比 CLOCK 少 3396 次 DRAM-to-NVM eviction；blackscholes 小幅优于 LFU；dedup pressure 与 LRU 持平；canneal 是稳定负例。
8. 增加论文限制和后续方向：candidate selection、over-eviction control、lower-overhead runtime integration。
9. 将参考文献替换为更贴近当前论文引用体系的 hybrid memory、learning memory access patterns、RRIP、PARSEC 等文献。