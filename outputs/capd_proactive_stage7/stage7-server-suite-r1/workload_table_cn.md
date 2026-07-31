# 阶段7六-workload描述

| workload | 角色 | W页 | D20/D40/D60页 | 读/写比例(T/V) | 进入P50/P95/P99 | LRU降级率 | 资格/警告 |
|---|---|---:|---:|---:|---:|---:|---|
| canneal | seen_calibration_workload | 4443 | 889/1778/2666 | 0.280366/0.719634 | 0/1/1 | 0.001481 | True/none |
| streamcluster_pressure | seen_calibration_workload | 1921 | 385/769/1153 | 0.605856/0.394144 | 0/1/1 | 0.000645 | True/none |
| dedup_pressure | seen_calibration_workload | 982 | 197/393/590 | 0.341969/0.658031 | 0/0/1 | 0.000330 | True/none |
| blackscholes | held_out_unseen_workload | 110 | 22/44/66 | 0.654625/0.345375 | 0/0/1 | 0.000295 | True/D_20_below_100_evaluate_recollection_or_replacement |
| swaptions | held_out_unseen_workload | 297 | 60/119/179 | 0.774514/0.225486 | 0/0/1 | 0.000550 | True/D_20_below_100_evaluate_recollection_or_replacement |
| fluidanimate | held_out_unseen_workload | 27720 | 5544/11088/16632 | 0.817117/0.182883 | 0/21/22 | 0.009270 | True/none |
