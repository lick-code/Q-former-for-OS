# CAPD 桥接诊断结果

状态：`BRIDGE_DIAGNOSTIC_COMPLETED`。

> 这是事后诊断，不是新的正式调参阶段；test 未用于方法或参数选择，且结果不替换 `STAGE6_VERIFIED`。

## 五个桥接锚点

| case | source | D/B/K | QMAP cost（mean±std） | best classic | improvement |
|---|---|---:|---:|---:|---:|
| legacy_published_D16_B8K8 | legacy_pressure_window | 16/8/8 | 268345.000 ± 1663.080 | 301767.000 (clock) | +11.0754% |
| legacy_current_identity_D16_B8K8 | legacy_pressure_window | 16/8/8 | 269746.667 ± 2482.358 | 301767.000 (clock) | +10.6109% |
| legacy_current_selector_D16_B16K8 | legacy_pressure_window | 16/16/8 | 270914.000 ± 2820.408 | 301767.000 (clock) | +10.2241% |
| official_current_selector_D16_B16K8 | official_recollection | 16/16/8 | 235581.667 ± 76.009 | 244635.000 (lru) | +3.7008% |
| official_current_full_D64_B64K8 | official_recollection | 64/64/8 | 230628.000 ± 0.000 | 232096.000 (lru) | +0.6325% |

## 逐因素归因

| factor | left → right | improvement change | effect |
|---|---|---:|---|
| engine_and_pipeline | `legacy_published_D16_B8K8` → `legacy_current_identity_D16_B8K8` | -0.4645 pp | small, degrades_right_case |
| candidate_selector | `legacy_current_identity_D16_B8K8` → `legacy_current_selector_D16_B16K8` | -0.3868 pp | small, degrades_right_case |
| trace_source | `legacy_current_selector_D16_B16K8` → `official_current_selector_D16_B16K8` | -6.5234 pp | large, degrades_right_case |
| dram_capacity_and_feasible_pool | `official_current_selector_D16_B16K8` → `official_current_full_D64_B64K8` | -3.0683 pp | moderate, degrades_right_case |

## 判读边界

- 每一行只解释相邻锚点之间的匹配差异；不能外推为普遍因果。
- `bridge_diagnostics` 记录 QMAP/LRU victim 分歧、有限前瞻结果、score margin 与 victim sequence fingerprint。
- 若三个 seed 的 victim fingerprint 完全相同，说明随机训练没有改变最终决策序列；这属于诊断结果，不构成继续使用 test 调参的许可。
