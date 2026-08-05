# CAPD Stage10A 协议

Stage10A 是确定性的、单线程的离散事件 fixture 模拟器，不宣称真实 Linux、内核或端到端前台延迟行为。

## 时间与事件

所有时间使用整数纳秒。事件堆键为 `(timestamp_ns, event_priority, event_id)`，优先级从高到低固定为：`demotion_finish`、`capd_inference_finish`、`capd_round_start`、`emergency_fallback`、`page_enter_dram`。`event_id` 单调递增，用于同优先级事件的确定性排序。

初始 resident 数为 `dram_capacity_frames - initial_free_frames`，页面 ID 固定为 `0..count-1`，LRU 顺序是 MRU 到 LRU 的 `[0, 1, ..., count-1]`。候选源固定为 `candidate_source=lru_tail`，同一尾部顺序下按 page ID 稳定处理。

## 状态与迁移

`reserved_page_ids` 统一包含 active inference、active migration、pending normal migration 和 pending emergency migration。四个集合必须互不相交；任何 page ID 不得被重复调度。后台服务严格串行：`idle -> inference -> migration -> idle`。普通任务和 emergency 任务共享服务槽位，emergency 只插入待处理队列头，不抢占正在运行的服务。

有空闲帧时的新页面，以及解除阻塞后的页面，都插入 MRU 头部。释放页面必须先清除其 reservation，再恢复一个 free frame。

## 到达模型

默认使用参数化 uniform 和 burst 到达模型。uniform 使用固定间隔；burst 覆盖完整模拟区间，burst 外使用基础到达率，burst 内使用基础率乘 multiplier；合并后按时间排序并重新分配连续 page ID。可靠 Trace 时间戳 replay 需要单独的时间单位、单调性和 provenance 契约，属于后续输入选项，当前不启用。

`mu_demote` 使用场景级 `b_t_reference` 计算；运行中每轮实际 `b_t` 独立记录。`foreground_blocking_time_mean` 和 P95 在没有完成阻塞样本时为 JSON `null`，报告显示 `N/A`。`free_frame_exhaustion_duration` 是 `[0, simulation_horizon]` 内 `F_t=0` 的时间积分，包含初始和末尾区间。
