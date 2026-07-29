# CAPD 主动降级阶段 3 校准报告

- 状态：`stage3_calibration_results_ready_for_freeze`
- 数据类型：`real_train_validation`
- Test 是否用于选择：否
- CAPD 是否用于参数选择：否
- 标定策略：Reactive-LRU（突发/压力）与 Proactive-LRU（水位/b_max）

## Working Set

- canneal: Train=2239, Validation=1096, Union=2560, overlap=775
- dedup_pressure: Train=4466, Validation=2528, Union=6945, overlap=49
- streamcluster_pressure: Train=7316, Validation=2685, Union=9303, overlap=698

## 容量规则

- 推荐：`None`
- 原因：`neither_capacity_profile_passed_predeclared_pressure_rule`
- 仍需用户确认：是

## 水位与 b_max

- 水位建议：`{'label': 'medium', 'F_low': 2, 'F_target': 4, 'source_window': 100, 'source_split': 'validation', 'source_quantile': 'p95', 'source_aggregate': 'maximum_across_workload_capacity_runs', 'source_value': 4, 'generation_rule': 'target=max(2,ceil(source),previous_target+1);low=ceil(target/2)'}`
- b_max 建议：`4`
- K 代理不变性：`passed`
- K 代理不进入正式 method.candidate_size_K。

## 边界

- 未读取 Test，未运行 CAPD，未训练模型，未修改阶段 0 主配置。
- 该报告只给出预声明规则产生的冻结候选；在用户确认和服务器回归完成前不得标记 stage3_verified。
