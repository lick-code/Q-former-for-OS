# CAPD 主动降级阶段 3 校准报告

- 状态：`stage3_calibration_results_ready_for_freeze`
- 数据类型：`real_train_fresh_validation_v2`
- Test 是否用于选择：否
- CAPD 是否用于参数选择：否
- 标定策略：Reactive-LRU（突发/压力）与 Proactive-LRU（水位/b_max）

## Working Set

- canneal: Train=156, Validation=40, Union=156, overlap=40
- dedup_pressure: Train=111, Validation=10, Union=116, overlap=5
- streamcluster_pressure: Train=155, Validation=40, Union=155, overlap=40

## 容量规则

- 推荐：`None`
- 原因：`neither_capacity_profile_passed_predeclared_capacity_rule_v2`
- 仍需用户确认：是

## 水位与 b_max

- 水位建议：`None`
- b_max 建议：`None`
- K 代理不变性：`failed_proxy_K_changes_selection`
- K 代理不进入正式 method.candidate_size_K。

## 边界

- 未读取 Test，未运行 CAPD，未训练模型，未修改阶段 0 主配置。
- 该报告只给出预声明规则产生的冻结候选；在用户确认和服务器回归完成前不得标记 stage3_verified。
