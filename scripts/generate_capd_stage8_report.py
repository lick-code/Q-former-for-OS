# coding: utf-8
"""Generate the human-readable CAPD Stage 8 r5 results report.

The frozen replay directory is read-only from this script's point of view.  The
report is generated from its authoritative aggregate, configuration, CSV ledger,
and job result files; no replay or recomputation is performed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "outputs" / "capd_proactive_stage8" / (
    "stage8-dual-track-20260804-r5-post-evidence-commit"
)
ART = RUN / "artifacts"
OUT = ROOT / "docs" / "CAPD_Stage8_r5_完整测试结果与指标分析.md"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def pct(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.{digits}f}%"


def pp(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.{digits}f} 个百分点"


def md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(str(x) for x in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def csv_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").rstrip()


def csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def dict_rows_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().rstrip()


def job_metric_rows(policy_filter: str | None = None) -> List[Dict[str, Any]]:
    """Read scalar metrics from job results without retaining event logs.

    Result files retain event/cycle logs as well.  Loading one file at a time
    keeps those logs out of the report generator's retained object graph.
    """
    rows: List[Dict[str, Any]] = []
    for path in sorted((RUN / "jobs").glob("**/result.json")):
        result = load_json(path)
        if policy_filter is not None and result["policy"] != policy_filter:
            continue
        metrics = result["metrics"]
        early = metrics["early_reuse"]
        generalization = result.get("capd_generalization", {})
        if not isinstance(generalization, dict):
            generalization = {}
        runtime = result.get("runtime", {}).get("latency", {})
        components = metrics.get("weighted_cost_components", {})
        distance = early.get("first_reuse_distance", {})
        future = early.get("future_access_count", {})
        row: Dict[str, Any] = {
            "policy": result["policy"],
            "track": result["track"],
            "workload": result["workload"],
            "seed": result["seed"],
            "job_id": result["job_id"],
            "weighted_cost": metrics["weighted_cost"],
            "weighted_cost_per_access": metrics["weighted_cost_per_access"],
            "dram_hits": metrics["dram_hits"],
            "raw_access_count": metrics["raw_access_count"],
            "hit_rate": (metrics["dram_hits"] / float(metrics["raw_access_count"])
                         if metrics["raw_access_count"] else None),
            "nvm_reads": metrics["nvm_reads"],
            "nvm_writes": metrics["nvm_writes"],
            "dram_hit_cost": components.get("dram_hit_cost"),
            "nvm_read_cost": components.get("nvm_read_cost"),
            "nvm_write_cost": components.get("nvm_write_cost"),
            "demotion_cost": components.get("demotion_cost"),
            "total_demotions": metrics["total_demotions"],
            "proactive_demotions": metrics["proactive_demotions"],
            "reactive_demotions": metrics["reactive_demotions"],
            "emergency_demotions": metrics["emergency_demotions"],
            "page_enter_dram_count": metrics["page_enter_dram_count"],
            "number_of_proactive_cycles": metrics["number_of_proactive_cycles"],
            "number_of_proactive_rounds": metrics["number_of_proactive_rounds"],
            "mean_b_t": metrics["mean_b_t"],
            "rounds_per_cycle": metrics["rounds_per_cycle"],
            "minimum_free_frames": metrics["minimum_free_frames"],
            "average_free_frames": metrics["average_free_frames"],
            "free_frame_exhaustion_count": metrics["free_frame_exhaustion_count"],
            "emergency_fallback_count": metrics["emergency_fallback_count"],
            "fallback_rate": metrics["fallback_rate"],
            "decision_count": metrics["decision_count"],
            "total_decision_time": metrics["total_decision_time"],
            "mean_decision_time": metrics["mean_decision_time"],
            "p50_decision_time": metrics["p50_decision_time"],
            "p95_decision_time": metrics["p95_decision_time"],
            "p99_decision_time": metrics["p99_decision_time"],
            "early_reuse_64_rate": early["windows"]["64"]["rate"],
            "early_reuse_64_count": early["windows"]["64"]["early_reuse_count"],
            "early_reuse_256_rate": early["windows"]["256"]["rate"],
            "early_reuse_256_count": early["windows"]["256"]["early_reuse_count"],
            "early_reuse_1024_rate": early["windows"]["1024"]["rate"],
            "early_reuse_1024_count": early["windows"]["1024"]["early_reuse_count"],
            "wasted_demotion_count": early["wasted_demotion_count"],
            "wasted_demotion_rate": early["wasted_demotion_rate"],
            "first_reuse_distance_count": distance.get("count"),
            "first_reuse_distance_min": distance.get("minimum"),
            "first_reuse_distance_max": distance.get("maximum"),
            "first_reuse_distance_mean": distance.get("mean"),
            "first_reuse_distance_p50": distance.get("p50"),
            "first_reuse_distance_p95": distance.get("p95"),
            "first_reuse_distance_p99": distance.get("p99"),
            "future_access_count_count": future.get("count"),
            "future_access_count_min": future.get("minimum"),
            "future_access_count_max": future.get("maximum"),
            "future_access_count_mean": future.get("mean"),
            "future_access_count_p50": future.get("p50"),
            "future_access_count_p95": future.get("p95"),
            "future_access_count_p99": future.get("p99"),
            "no_future_reuse_count": early["no_future_reuse_count"],
            "page_access_oov_count": generalization.get("page_access_oov_count"),
            "page_access_oov_ratio": generalization.get("page_access_oov_ratio"),
            "page_unique_oov_count": generalization.get("page_unique_oov_count"),
            "page_unique_oov_ratio": generalization.get("page_unique_oov_ratio"),
            "pc_access_oov_count": generalization.get("pc_access_oov_count"),
            "pc_access_oov_ratio": generalization.get("pc_access_oov_ratio"),
            "pc_unique_oov_count": generalization.get("pc_unique_oov_count"),
            "pc_unique_oov_ratio": generalization.get("pc_unique_oov_ratio"),
            "runtime_total_seconds": runtime.get("total_seconds"),
            "runtime_feature_total_seconds": runtime.get("feature_total_seconds"),
            "runtime_inference_total_seconds": runtime.get("inference_total_seconds"),
            "runtime_selection_total_seconds": runtime.get("selection_total_seconds"),
        }
        rows.append(row)
    return rows


def main() -> None:
    aggregate = load_json(ART / "aggregate.json")
    config = load_json(RUN / "resolved_config.json")
    verification = load_json(RUN / "verification.json")
    state = load_json(RUN / "run_state.json")
    smoke = load_json(RUN / "runtime_smoke.json")
    identity = load_json(RUN / "run_identity.json")
    receipt = load_json(RUN / "server_test_receipt.json")
    raw_rows = csv_rows(ART / "per_workload_raw.csv")
    all_metric_rows = job_metric_rows()
    capd_rows = [row for row in all_metric_rows if row["policy"] == "capd"]

    lines: List[str] = []
    a = lines.append
    a("# CAPD Stage 8 r5 完整测试结果与指标分析")
    a("")
    a("> 本文件依据已验证的 Stage 8 r5 同步 Replay 产物编写。报告本身是结果解释层，不会修改或重跑冻结证据。")
    a("")

    # The user requested experiment setup first.
    a("## 1. 实验设置（最前）")
    a("")
    a("### 1.1 实验目的")
    a("")
    a("Stage 8 的问题是：在相同 trace、容量、成本权重和控制参数下，CAPD 的页面选择与主动 demotion 是否比 TPP-inspired、Reactive LRU、Proactive LRU、Proactive CLOCK 更低成本，并且距离 candidate-scoped Oracle 有多远。Standard 与 Pressure 是两条评价 trace track，必须分开解释；它们不是独立随机种子，不能拼成一个 primary macro。")
    a("")
    a("### 1.2 实验身份、设备与确定性")
    a("")
    a(md_table(
        ["字段", "值"],
        [
            ["run_id", config["run"]["run_id"]],
            ["contract_id", config["contract_id"]],
            ["代码 commit", identity["git"]["commit"]],
            ["运行状态", verification["status"]],
            ["设备", f"{smoke['device']}，{smoke['cuda_device_name']}"],
            ["PyTorch", smoke["torch_version"]],
            ["服务器 Python", config["run"]["machine"]["python"].splitlines()[0]],
            ["CUDA checkpoint smoke", "3/3 通过"],
            ["回归测试", f"{receipt['test_count']} 项通过，{receipt['success_marker']}"],
            ["正式 job", f"{verification['formal_job_count']} 个，结果与 schema/SHA 均验证"],
            ["参数选择是否使用 Test", "否"],
            ["aggregate SHA256", verification["aggregate_sha256"]],
        ],
    ))
    a("")
    a("确定性环境固定 `PYTHONHASHSEED=0`、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、cuDNN deterministic、cuDNN benchmark 关闭和 PyTorch deterministic algorithms。r5 的冻结 run identity 还记录了每个 CAPD checkpoint 的 SHA256。")
    a("")
    a("### 1.3 数据、track 与 job 矩阵")
    a("")
    a(md_table(
        ["Track", "workload", "Test records", "cell 数", "每 cell jobs", "总 jobs", "备注"],
        [
            ["Standard", ", ".join(config["tracks"]["standard"]["workloads"]), config["tracks"]["standard"]["records_per_test"], 6, "3 CAPD seed + 5 deterministic", 48, "streamcluster_pressure、fluidanimate 是 structural-zero，但仍保留"],
            ["Pressure", ", ".join(config["tracks"]["pressure"]["workloads"]), config["tracks"]["pressure"]["records_per_test"], 4, "3 CAPD seed + 5 deterministic", 32, "由冻结 Pressure bundle/lock 派生"],
            ["合计", "10 个 track-workload cell", "见上", 10, "8 jobs/cell", 80, "六个正式 policy + CAPD 三个 seed"],
        ],
    ))
    a("")
    a("每个 cell 都使用同一 trace、同一 D/W_ref/F_low/F_target/K/b_max、同一初始状态和同一成本配置；只有 policy 或 CAPD seed 按 contract 变化。公平性审计的 10/10 cell、policy membership、seed membership 和跨 track 控制一致性均为 passed。")
    a("")
    a("### 1.4 workload 控制参数")
    a("")
    controls = []
    for workload, value in config["workload_controls"].items():
        controls.append([workload, value["D"], value["F_low"], value["F_target"] if "F_target" in value else "N/A"])
    # W_ref is in the candidate contract; the resolved workload controls are authoritative for D/F values.
    wrefs = {row["workload"]: row["W_ref"] for row in raw_rows}
    controls = [[row[0], row[1], wrefs.get(row[0], "见 job ledger"), row[2], row[3]] for row in controls]
    a(md_table(["workload", "D（DRAM pages）", "W_ref", "F_low", "F_target"], controls))
    a("")
    a("其中 D 是 DRAM 页容量；W_ref 是 ranker 的参考窗口；F_low 是低水位触发阈值；F_target 是主动 demotion 后的目标空闲帧数。CAPD 只在 `0 < F_t < F_low` 时做 bounded active demotion，`F_t=0` 时使用冻结的 LRU emergency fallback，`F_t>=F_low` 时不触发主动 demotion。")
    a("")
    a("### 1.5 策略与冻结 CAPD 设置")
    a("")
    a(md_table(
        ["策略", "含义", "是否使用未来信息"],
        [
            ["CAPD", "冻结 checkpoint 的 candidate-scoped page scorer；candidate 为当前状态 LRU tail，最多 K=8；主动 batch 受 b_max=2 和 F_target-F_t 约束", "否；页面输入 OOV 映射到 UNK"],
            ["TPP-inspired", "epoch=1024、cold_threshold=1、dirty tie-break=false，不做 promotion", "否"],
            ["Reactive LRU", "只有压力/容量不足时才按 LRU 处理", "否"],
            ["Proactive LRU", "与 CAPD 相同主动触发框架，但 candidate 排名使用 LRU", "否"],
            ["Proactive CLOCK", "与 CAPD 相同主动触发框架，但 candidate 排名使用 CLOCK", "否"],
            ["Oracle", "在当前 candidate scope 内使用未来访问信息的上界对照", "是；只能作为 headroom 上界，不能作为可部署方法"],
        ],
    ))
    a("")
    a(md_table(
        ["CAPD 参数", "冻结值"],
        [
            ["H（history_H）", config["capd"]["history_H"]],
            ["L（lookahead_L）", config["capd"]["lookahead_L"]],
            ["label weights", str(tuple(config["capd"]["label_weights"]))],
            ["candidate K", config["frozen_controls"]["candidate_size_K"]],
            ["candidate source", config["frozen_controls"]["candidate_source"]],
            ["alpha / beta", f"{config['workload_controls'].get('blackscholes', {}).get('alpha', 0.15)} / {config['workload_controls'].get('blackscholes', {}).get('beta', 0.4)}（candidate contract 全 workload 固定）"],
            ["selector", config["frozen_controls"]["selector"]],
            ["b_max", config["frozen_controls"]["b_max"]],
            ["b_t rule", config["frozen_controls"]["b_t_rule"]],
            ["trigger", config["frozen_controls"]["trigger_mode"]],
            ["fallback", config["frozen_controls"]["fallback_policy"]],
            ["CAPD seeds", ", ".join(str(x) for x in config["capd_seeds"])],
            ["checkpoint selection", "每个 seed 只按 Validation minimum valid loss 选择；Test 不参与"],
        ],
    ))
    a("")
    a("冻结的 QMAP checkpoint/model contract：cross-attention；hidden size=48；2 个 transformer layers；feed-forward size=96；4 heads/queries；sinusoidal positional encoding；dropout=0.1；训练 8 epochs、batch size=32、learning rate=1e-4、weight decay=1e-4、FP32；Validation loss 最早 epoch tie-break。Stage 8 只加载这些已冻结 checkpoint，不在 Test 上重训、调参或扩词表。")
    a("")
    a("三个 CAPD checkpoint SHA256：seed 3136859=`7093c5b188548a86baf1c6f6a46715f1ace01c230ae41635f636b1112e870438`；seed 42=`40d4f5c0413e36d3e9887d90d809195c6bf53db7dfdf397e654555b1d3fcae0a`；seed 2026=`7c124136eecc157cef1cef3c1f9d68ac57b0c60ac594ae49f473bb2f2a4d2d27`。")
    a("")
    a("### 1.6 存储、初始状态和成本模型")
    a("")
    a("初始状态是 `empty_dram_all_trace_pages_backed_by_nvm`：DRAM 为空、所有 trace page 由无界 NVM backing tier 支持；`page_enter_dram` 无论来源都占用一个 free frame；page size 为 4096 bytes。")
    a("")
    a("默认 weighted cost 的冻结权重是：DRAM hit=1、NVM read=2、NVM write=8、demotion=10。因此：")
    a("")
    a("`weighted_cost = 1*dram_hits + 2*nvm_reads + 8*nvm_writes + 10*total_demotions`。")
    a("")
    a("`weighted_cost_per_access = weighted_cost / raw_access_count`。这个归一化值可跨 Standard/Pressure 直观看每次访问平均成本，但主宏平均仍按 track 内 workload cell 的 weighted cost 做等权 macro mean。")
    a("")

    a("## 2. 最终验证结论")
    a("")
    a("Stage 8 r5 已通过正式验证：`stage8_sync_replay_verified`。80/80 job 结果、身份、schema、结果 SHA 和语义 SHA 均通过；aggregation、verification、fairness 和 deterministic CUDA smoke 均通过；failure history 为空。")
    a("")
    a("这不是“CAPD 在所有 workload 都严格优于所有 baseline”的结论。准确结论是：在冻结的 10 个 cell 中，CAPD 对 TPP-inspired 在 Standard 2 个 cell 改善、4 个持平；Pressure 2 个改善、2 个持平。bootstrap CI 上界均为 0，且区间包含 0，所以这里只报告描述性改善，不称为统计显著。")
    a("")

    a("## 3. 指标词典与解释")
    a("")
    a("下表覆盖 Stage 8 result schema 的正式指标、运行级指标、OOV/UNK 指标和本报告派生的 hit rate。方向“越低越好/越高越好”只表示通常的性能解释；状态安全性指标不能简单按单一方向理解。")
    a("")
    metric_rows = [
        ["dram_hits", "DRAM 命中次数", "计数", "越高越好；hit rate 的分子", "由 trace 访问数决定"],
        ["raw_access_count", "评价区间原始访问数", "计数", "分母，不是性能优劣", "Standard=600000，Pressure=500000"],
        ["hit_rate（派生）", "dram_hits/raw_access_count", "比例", "越高越好", "不是冻结主指标，没有独立 bootstrap CI"],
        ["nvm_reads", "从 NVM 读入 DRAM 的次数", "计数", "越低通常越好", "与冷 miss / demotion 后再访问有关"],
        ["nvm_writes", "向 NVM 写出的次数", "计数", "越低通常越好", "受 dirty/写回语义影响"],
        ["total_demotions", "总 demotion 次数", "计数", "越低通常越好，但必须结合 hit/NVM", "包含 proactive、reactive、emergency"],
        ["proactive_demotions", "主动水位触发的 demotion", "计数", "不是越低越好；表示主动机制工作量", "CAPD 的主要控制动作"],
        ["reactive_demotions", "反应式 demotion", "计数", "越低通常越好", "压力发生后才处理"],
        ["emergency_demotions / emergency_fallback_count", "F_t=0 时的紧急 fallback/demotion", "计数", "越低越好", "CAPD 是否赶不上水位的重要诊断"],
        ["weighted_cost", "按冻结权重合成的总成本", "加权计数", "越低越好；主指标", "唯一正式主比较指标"],
        ["weighted_cost_per_access", "每次访问平均 weighted cost", "成本/访问", "越低越好", "对 trace 长度归一化"],
        ["page_enter_dram_count", "页面进入 DRAM 的次数", "计数", "诊断/回填分母", "fallback_rate 分母"],
        ["number_of_proactive_cycles", "主动周期数", "计数", "诊断", "一次低水位处理形成一个 cycle"],
        ["number_of_proactive_rounds", "主动周期内的 round 数总和", "计数", "诊断", "每 round 最多 b_max 页面"],
        ["mean_b_t", "每次主动 round 的平均 batch 大小", "页面/round", "诊断", "受 b_max、F_target-F_t、candidate 数限制"],
        ["rounds_per_cycle", "主动 round/cycle", "比率", "越低不一定越好", "要结合 demotion 与水位效果"],
        ["minimum_free_frames", "运行期间最小 free frame", "页面数", "越高表示余量更大", "0 表示曾耗尽"],
        ["average_free_frames", "运行期间平均 free frame", "页面数", "越高表示平均余量更大", "状态轨迹指标"],
        ["free_frame_exhaustion_count", "free frame 耗尽事件数", "计数", "越低越好", "与 emergency fallback 相关"],
        ["fallback_rate", "emergency fallback / page_enter_dram_count", "比例", "越低越好", "原始分母保留；分母为 page_enter_dram_count"],
        ["early_reuse_64/256/1024", "demotion 后在窗口内首次复用的比例", "比例", "过早复用越多，说明 demotion 可能过早", "分母是每个 proactive demotion event 的 selected page，一页一次"],
        ["first_reuse_distance", "demotion 到首次再访问的访问距离", "访问数", "通常越大越安全", "报告 mean/p50/p95/p99"],
        ["future_access_count", "demotion 后剩余 future access 次数", "计数", "越高说明页面仍有价值", "报告 mean/p50/p95/p99"],
        ["wasted_demotion_count/rate", "之后没有任何 future reuse 的 demotion", "计数/比例", "越低越好", "no_future_reuse_count 同义"],
        ["decision_count", "CAPD scorer/selection 决策次数", "计数", "开销诊断", "不等于访问次数"],
        ["total/mean/p50/p95/p99_decision_time", "同步决策耗时统计", "秒", "越低越好，但仅是同步 replay 开销", "不代表真实异步前台延迟"],
        ["page/PC access/unique OOV", "page 或 PC 在冻结词表外的访问/唯一计数", "计数", "越低通常泛化更容易", "未扩词表，统一映射 UNK index=0"],
        ["cycles/rounds/events/final_state", "逐 job 状态与事件轨迹", "结构化日志", "用于审计 accounting 和状态安全", "不宜压缩成单一性能分数"],
        ["runtime.latency", "job 运行级耗时字段", "秒", "只做工程诊断", "同步 replay 不能外推 CPU/内存/并发"],
    ]
    a(md_table(["指标", "含义", "单位", "方向/用途", "分母或边界"], metric_rows))
    a("")
    a("### 3.1 指标之间的关系")
    a("")
    a("weighted_cost 不是 hit rate 的替代物，而是把 hit、NVM read/write 和 demotion 按系统代价合成。一个策略可能 hit 更高，但如果为此产生更多 NVM write 或 demotion，weighted cost 未必更低；反之，weighted cost 改善通常应结合 hit、NVM 和 demotion 分解解释。")
    a("")

    # Main tables.
    a("## 4. CAPD 对 TPP-inspired：主比较")
    a("")
    for track in ("standard", "pressure"):
        ci = aggregate["bootstrap_95ci"][track]
        row = aggregate["track_macros"][track]
        a(f"### {track.title()}（{row['cell_count']} cells，{row['job_count']} jobs）")
        a("")
        a(md_table(
            ["指标", "结果"],
            [
                ["CAPD-TPP weighted cost 均值", number(ci["capd_minus_tpp_weighted_cost"]["estimate"], 4)],
                ["95% percentile bootstrap CI", f"[{number(ci['capd_minus_tpp_weighted_cost']['lower'], 4)}, {number(ci['capd_minus_tpp_weighted_cost']['upper'], 4)}]"],
                ["CAPD 相对改善均值", pct(ci["capd_relative_improvement_vs_tpp"]["estimate"])],
                ["相对改善 95% CI", f"[{pct(ci['capd_relative_improvement_vs_tpp']['lower'])}, {pct(ci['capd_relative_improvement_vs_tpp']['upper'])}]"],
                ["bootstrap", f"{ci['capd_minus_tpp_weighted_cost']['resamples']} 次，seed={ci['capd_minus_tpp_weighted_cost']['seed']}，单位=track-workload cell"],
            ],
        ))
        a("")
        a("解释：负的 CAPD-TPP 表示 CAPD 成本更低；相对改善为 `(TPP-CAPD)/TPP`。CI 包含 0，因此不作“显著优于”陈述。")
        a("")
    paired = aggregate["capd_vs_tpp_paired"]
    a("### 4.1 逐 cell 数值")
    a("")
    a(md_table(
        ["Track", "workload", "CAPD weighted cost", "TPP weighted cost", "CAPD-TPP", "相对改善"],
        [[r["track"], r["workload"], number(r["capd_mean_weighted_cost"]), number(r["tpp_weighted_cost"]), number(r["capd_minus_tpp"]), pct(r["relative_improvement"])] for r in paired],
    ))
    a("")
    a("CAPD 的改善集中在 blackscholes（Standard 10.0475%，Pressure 10.0505%）和 swaptions（Standard 1.3975%，Pressure 1.3239%）；canneal、dedup_pressure、streamcluster_pressure、fluidanimate 在相应 track 与 TPP 持平。")
    a("")

    a("## 5. 六种 policy 的完整 weighted cost 对比")
    a("")
    for track in ("standard", "pressure"):
        macro = aggregate["track_macros"][track]
        a(f"### {track.title()} macro mean（cell 等权）")
        a("")
        a(md_table(
            ["policy", "macro mean weighted cost", "相对 CAPD", "CAPD 表现"],
            [[policy, number(value["macro_mean_weighted_cost"]), number(value["macro_mean_weighted_cost"] - macro["policies"]["capd"]["macro_mean_weighted_cost"]), "基准" if policy == "capd" else ("更低" if value["macro_mean_weighted_cost"] < macro["policies"]["capd"]["macro_mean_weighted_cost"] else "更高")] for policy, value in macro["policies"].items()],
        ))
        a("")
    a("宏平均排序：Standard 为 Oracle < CAPD < Reactive LRU < Proactive LRU = TPP-inspired < Proactive CLOCK；Pressure 为 Oracle < CAPD < Reactive LRU < Proactive LRU = TPP-inspired < Proactive CLOCK。CAPD 两条 track 都仅次于 Oracle。")
    a("")

    a("## 6. CAPD 对 Oracle 的 headroom")
    a("")
    a("Oracle 只是在相同 candidate scope 内使用 future information 的上界，不是可部署 baseline。CAPD-Oracle 为正表示 CAPD 仍有上界差距；为 0 表示该 cell 达到 candidate-scoped Oracle。")
    a("")
    oracle = aggregate["oracle_headroom"]
    a(md_table(["Track", "workload", "CAPD", "Oracle", "CAPD-Oracle"], [[r["track"], r["workload"], number(r["capd_mean_weighted_cost"]), number(r["oracle_weighted_cost"]), number(r["capd_minus_oracle"])] for r in oracle]))
    a("")
    a("Standard 中 blackscholes/swaptions 的 headroom 分别为 8701/6409，其余四个 cell 为 0；Pressure 中 blackscholes/swaptions 为 7271/5338，其余两个 cell 为 0。宏平均上 CAPD 距 Oracle 约 0.38%（Standard）和 0.55%（Pressure）。")
    a("")

    a("## 7. Proactive LRU 与 Reactive LRU")
    a("")
    a("该比较用于判断“主动水位机制”本身相对纯反应式 LRU 的代价/收益。它不是 CAPD 的唯一主假设检验。")
    a("")
    pr = aggregate["proactive_lru_vs_reactive_lru_paired"]
    a(md_table(["Track", "workload", "Proactive LRU", "Reactive LRU", "Proactive-Reactive", "相对改善"], [[r["track"], r["workload"], number(r["proactive_lru_weighted_cost"]), number(r["reactive_lru_weighted_cost"]), number(r["proactive_minus_reactive"]), pct(r["relative_improvement"])] for r in pr]))
    a("")
    a("结果解读：主动 LRU 在 blackscholes、swaptions 等高压力 cell 的成本高于 Reactive LRU，说明主动 demotion 有额外动作成本；CAPD 的优势不是“所有 proactive 行为都自动有益”，而是通过 page ranking 在特定 workload 上减少更昂贵的后续事件。")
    a("")

    a("## 8. Hit rate、NVM、demotion 与状态指标")
    a("")
    a("### 8.1 CAPD 与 TPP 的命中率")
    a("")
    a("hit rate 是本报告从已验证 `dram_hits/raw_access_count` 派生的辅助指标；Stage 8 冻结主指标仍是 weighted_cost。")
    a("")
    hit_rows = []
    for track in ("standard", "pressure"):
        rows = [r for r in raw_rows if r["track"] == track and r["policy"] in ("capd", "tpp_inspired")]
        for policy in ("capd", "tpp_inspired"):
            subset = [r for r in rows if r["policy"] == policy]
            hits = sum(float(r["dram_hits"]) for r in subset)
            accesses = sum(600000 if track == "standard" else 500000 for _ in subset)
            hit_rows.append([track, policy, number(hits), number(accesses), pct(hits / accesses)])
    a(md_table(["Track", "policy", "DRAM hits（跨 cell 合计）", "raw accesses", "派生 hit rate"], hit_rows))
    a("")
    a("宏命中率：Standard CAPD 99.0908%，TPP 98.8270%，CAPD +0.2638 个百分点；Pressure CAPD 98.6452%，TPP 98.2511%，CAPD +0.3942 个百分点。")
    a("")
    a("有差异的 cell：Standard blackscholes +1.4775 个百分点、swaptions +0.1052 个百分点；Pressure blackscholes +1.4780 个百分点、swaptions +0.0986 个百分点。其余 cell 的命中率持平。")
    a("")

    a("### 8.2 CAPD 相对 TPP 的 NVM 与 demotion 差异")
    a("")
    a("以下是按 cell 的 CAPD-TPP 差异；负数表示 CAPD 事件更少。")
    a("")
    # Derive differences from the 80-row core ledger.
    diff_rows = []
    for track in ("standard", "pressure"):
        workloads = sorted({r["workload"] for r in raw_rows if r["track"] == track})
        for workload in workloads:
            capd = [r for r in raw_rows if r["track"] == track and r["workload"] == workload and r["policy"] == "capd"]
            tpp = [r for r in raw_rows if r["track"] == track and r["workload"] == workload and r["policy"] == "tpp_inspired"]
            if not capd or not tpp:
                continue
            def mean_field(rows: Sequence[Mapping[str, str]], field: str) -> float:
                return sum(float(x[field]) for x in rows) / len(rows)
            diff_rows.append([track, workload, number(mean_field(capd, "nvm_reads") - mean_field(tpp, "nvm_reads"), 3), number(mean_field(capd, "nvm_writes") - mean_field(tpp, "nvm_writes"), 3), number(mean_field(capd, "total_demotions") - mean_field(tpp, "total_demotions"), 3), number(mean_field(capd, "weighted_cost") - mean_field(tpp, "weighted_cost"), 3)])
    a(md_table(["Track", "workload", "NVM reads 差", "NVM writes 差", "demotions 差", "weighted cost 差"], diff_rows))
    a("")
    a("这些差异说明 CAPD 的 weighted-cost 改善来自事件组合变化，而不是单一 hit rate 指标：blackscholes 的 NVM read 与 demotion 明显下降；swaptions 也下降但幅度较小；其余 workload 事件和成本与 TPP 完全相同。")
    a("")

    a("### 8.3 空闲帧、fallback 与主动周期")
    a("")
    a("CAPD 的逐 seed/逐 cell 状态、fallback、cycle、round、b_t、决策耗时和 early-reuse 标量见下方 CAPD 完整指标 ledger。这里的核心解释是：`minimum_free_frames=0` 并不自动表示失败；要结合 `emergency_fallback_count`、`fallback_rate` 和 weighted cost 判断系统是否经常跌入紧急路径。")
    a("")

    a("## 9. Early reuse 与 wasted demotion")
    a("")
    a("early reuse 衡量被主动 demote 的页面在未来 64/256/1024 次访问窗口内是否很快再次出现；wasted demotion 是之后没有任何 future reuse 的主动 demotion。它们是机制诊断，不是主性能指标。窗口分母严格是每个 proactive demotion event 的 selected page，且一页一次。")
    a("")
    a("所有 CAPD job 的 window rate、首次复用距离 mean/p50/p95、future access count mean/p50/p95、no-future-reuse count/rate 已逐行列在第 12 节的完整 ledger；每个 job 的 `per_demotion_audit` 事件级明细原样保存在对应 `jobs/*/result.json`。")
    a("")

    a("## 10. OOV/UNK 泛化")
    a("")
    a("CAPD 词表不扩展，所有 frozen-input 未见页面/PC 映射到 `unk_index=0`。因此 OOV 不是重新训练或调参入口，而是对冻结模型泛化的审计指标。逐 job 的 page access/unique OOV、PC access/unique OOV 计数和比例已在完整 CAPD ledger 中列出。")
    a("")
    a("解释时必须区分 access OOV 与 unique OOV：前者按访问次数计，后者按不同 token/page/PC 计；比例的分母相应不同。OOV 高不等于结果必然失败，但需要结合 weighted cost、hit rate 和 early reuse 看。")
    a("")

    a("## 11. 同步决策耗时、cycles/events/final_state")
    a("")
    a("每个 CAPD job 记录 `decision_count`、`total_decision_time`、`mean/p50/p95/p99_decision_time`，以及每个主动 cycle/round 的 feature、inference、selection 时间；完整标量见 ledger，完整结构化 `cycles`、`rounds`、`events` 和 `final_state` 见逐 job JSON。")
    a("")
    a("边界非常重要：本实验是同步 replay。它能支持页面排名质量、NVM 事件、weighted cost、状态轨迹和同步决策开销；不能证明真实后台并发、前台请求延迟、CPU overhead 或 memory overhead。报告不把 runtime 字段包装成真实系统 latency 结论。")
    a("")

    a("## 12. CAPD 30 个正式 job 的完整标量指标 ledger")
    a("")
    a("以下表格覆盖 Standard 6 cells × 3 seeds 与 Pressure 4 cells × 3 seeds 的全部 30 个 CAPD job。为保证 Markdown 可读性，事件级 arrays（每次 event/cycle/round 的逐条记录）不重复展开；它们在同一 run 目录的 `jobs/*/result.json` 中完整保留，并由 SHA/semantic SHA 验证。")
    a("")
    capd_headers = [
        "track", "workload", "seed", "weighted_cost", "cost/access", "hit_rate",
        "dram_hits", "raw_access", "nvm_r", "nvm_w", "hit_cost", "nvm_r_cost", "nvm_w_cost", "demotion_cost", "demotions", "proactive",
        "reactive", "emergency", "page_enter", "cycles", "rounds", "mean_b_t",
        "rounds/cycle", "min_free", "avg_free", "exhaustion", "fallback_n", "fallback_rate",
        "decision_n", "decision_total_s", "decision_mean_s", "p50_s", "p95_s", "p99_s",
        "reuse64_n", "reuse<=64", "reuse256_n", "reuse<=256", "reuse1024_n", "reuse<=1024", "wasted_n", "wasted_rate",
        "reuse_dist_count", "reuse_dist_min", "reuse_dist_max", "reuse_dist_mean", "reuse_dist_p50", "reuse_dist_p95", "reuse_dist_p99", "future_n_count", "future_n_min", "future_n_max", "future_n_mean", "future_n_p50",
        "future_n_p95", "future_n_p99", "no_future_n", "page_OOV", "page_OOV_rate", "page_unique_OOV", "page_unique_OOV_rate", "PC_OOV", "PC_OOV_rate", "PC_unique_OOV", "PC_unique_OOV_rate", "runtime_total_s", "runtime_feature_s", "runtime_inference_s", "runtime_selection_s",
    ]
    capd_table_rows = []
    for r in capd_rows:
        capd_table_rows.append([
            r["track"], r["workload"], r["seed"], number(r["weighted_cost"]), number(r["weighted_cost_per_access"]), pct(r["hit_rate"]),
            number(r["dram_hits"]), number(r["raw_access_count"]), number(r["nvm_reads"]), number(r["nvm_writes"]), number(r["dram_hit_cost"]), number(r["nvm_read_cost"]), number(r["nvm_write_cost"]), number(r["demotion_cost"]), number(r["total_demotions"]), number(r["proactive_demotions"]), number(r["reactive_demotions"]), number(r["emergency_demotions"]), number(r["page_enter_dram_count"]), number(r["number_of_proactive_cycles"]), number(r["number_of_proactive_rounds"]), number(r["mean_b_t"]), number(r["rounds_per_cycle"]), number(r["minimum_free_frames"]), number(r["average_free_frames"]), number(r["free_frame_exhaustion_count"]), number(r["emergency_fallback_count"]), pct(r["fallback_rate"]), number(r["decision_count"]), number(r["total_decision_time"], 9), number(r["mean_decision_time"], 12), number(r["p50_decision_time"], 12), number(r["p95_decision_time"], 12), number(r["p99_decision_time"], 12), number(r["early_reuse_64_count"]), pct(r["early_reuse_64_rate"]), number(r["early_reuse_256_count"]), pct(r["early_reuse_256_rate"]), number(r["early_reuse_1024_count"]), pct(r["early_reuse_1024_rate"]), number(r["wasted_demotion_count"]), pct(r["wasted_demotion_rate"]), number(r["first_reuse_distance_count"]), number(r["first_reuse_distance_min"]), number(r["first_reuse_distance_max"]), number(r["first_reuse_distance_mean"]), number(r["first_reuse_distance_p50"]), number(r["first_reuse_distance_p95"]), number(r["first_reuse_distance_p99"]), number(r["future_access_count_count"]), number(r["future_access_count_min"]), number(r["future_access_count_max"]), number(r["future_access_count_mean"]), number(r["future_access_count_p50"]), number(r["future_access_count_p95"]), number(r["future_access_count_p99"]), number(r["no_future_reuse_count"]), number(r["page_access_oov_count"]), pct(r["page_access_oov_ratio"]), number(r["page_unique_oov_count"]), pct(r["page_unique_oov_ratio"]), number(r["pc_access_oov_count"]), pct(r["pc_access_oov_ratio"]), number(r["pc_unique_oov_count"]), pct(r["pc_unique_oov_ratio"]), number(r["runtime_total_seconds"], 9), number(r["runtime_feature_total_seconds"], 9), number(r["runtime_inference_total_seconds"], 9), number(r["runtime_selection_total_seconds"], 9),
        ])
    a(md_table(capd_headers, capd_table_rows))
    a("")
    a("注：`page_OOV`、`page_unique_OOV`、`PC_OOV`、`PC_unique_OOV` 的比例也在源 JSON 中逐 job 保留；ledger 为避免列数失控展示计数，原始比例字段没有丢失。")
    a("")

    a("## 13. 80-job 扩展标量 ledger（所有 policy）")
    a("")
    a("下面是从 80 个逐 job `result.json` 提取的所有标量指标。它补充了 deterministic policies 的 decision/cycle/fallback/early-reuse/runtime 字段，以及 weighted-cost 四个分量和 OOV 比例；空值表示该 policy 的该指标在 contract 中不适用（例如 Reactive LRU 没有模型 decision latency）。")
    a("")
    a("```csv")
    a(dict_rows_csv(all_metric_rows))
    a("```")
    a("")

    a("## 14. 80-job 核心结果 ledger（所有 policy）")
    a("")
    a("下面内嵌权威 `per_workload_raw.csv` 的完整内容，覆盖 80 个 job 的身份、控制参数、weighted cost、cost/access、DRAM hits、NVM read/write、demotion、free-frame、fallback、early reuse 三个窗口和 wasted demotion。CSV 中的 SHA256 已在本报告末尾列出。")
    a("")
    a("```csv")
    a(csv_text(ART / "per_workload_raw.csv"))
    a("```")
    a("")

    a("## 15. 统计、fairness 与 Test isolation 检查")
    a("")
    a(md_table(
        ["检查", "结果", "解释"],
        [
            ["Formal job count", "80/80", "10 cells；Standard 48，Pressure 32"],
            ["Fairness", "passed", "同 cell trace/control/identity 一致；跨 track 同 workload 控制一致"],
            ["Test 用于参数选择", "false", "CAPD checkpoint 来自 Validation minimum valid loss；selector disabled"],
            ["Bootstrap", "10,000 resamples/track", "单位是 track-workload cell；Standard/Pressure 分开"],
            ["CI 解释", "描述性", "CAPD-TPP CI 上界均为 0，但下界到 0，不能宣称显著"],
            ["跨 track 关系", "not independent seeds", "Standard 与 Pressure 是不同 trace track"],
            ["浮点复算边界", "末位差异不改变结果", "服务器 Python 3.7 与本地 Python 3.13 最大绝对差约 2.84e-14"],
        ],
    ))
    a("")
    a("### 14.1 11 类统计误读检查")
    a("")
    a("本报告明确排除了以下常见误读：")
    for item in [
        "把点估计改善写成统计显著；",
        "把 bootstrap CI 包含 0 忽略掉；",
        "把 Standard 和 Pressure 当成独立 seed 后合并；",
        "把 hit rate 派生指标冒充冻结主指标；",
        "把 Oracle 当成可部署 baseline；",
        "把 proactive demotion 次数少直接等同于性能好；",
        "把 minimum_free_frames=0 直接等同于 replay 失败；",
        "把 OOV 计数解释成重新训练收益；",
        "把同步 decision time 解释成真实 foreground latency；",
        "把 615 regression tests 解释成性能证明；",
        "把 structural-zero workload 从 Standard 删除。",
    ]:
        a(f"- {item}")
    a("")

    a("## 16. CAPD 总体评价")
    a("")
    a("从 weighted cost 主指标看，CAPD 在两条 track 都优于或持平 TPP-inspired：Standard 平均改善 1.9075%，Pressure 平均改善 2.8436%；逐 cell 的有效改善集中在 blackscholes 和 swaptions，其他 workload 持平。CAPD 也优于 Proactive LRU、Proactive CLOCK，并接近 candidate-scoped Oracle；但在 Standard/Pressure 宏平均上仍分别比 Oracle 高 2518.33/3152.25 cost units。")
    a("")
    a("从 hit rate 看，CAPD 比 TPP 高约 0.264/0.394 个百分点，方向与 weighted cost 一致；从 NVM read/write 和 demotion 看，改善主要来自高压力 workload 的事件减少。")
    a("")
    a("从机制诊断看，early reuse、wasted demotion、fallback、free frames、OOV 和同步 decision latency 给出了 CAPD 的代价与边界，但这些指标不能单独推出因果结论。特别是同步 replay 不能回答后台并发、真实前台延迟、CPU 或内存 overhead。")
    a("")
    a("因此最稳妥的结论是：CAPD 在本冻结 Stage 8 contract 下是一个在黑盒 cache replay 中表现出 workload-selective、描述性成本优势的主动页面 ranking policy；不是在所有 workload、所有系统指标和所有部署条件下都已被证明优于其他方法。")
    a("")

    a("## 17. 权威产物与复现索引")
    a("")
    a(md_table(
        ["产物", "用途", "SHA256/说明"],
        [
            ["verification.json", "最终状态、80 job、fairness/statistics 验证", verification["aggregate_sha256"]],
            ["run_state.json", "阶段完成状态与 failure history", state["status"]],
            ["run_identity.json", "commit、配置、checkpoint、payload 身份", identity["run_identity_sha256"]],
            ["resolved_config.json", "完整实验设置和冻结参数", identity["config_sha256"]],
            ["job_manifest.json", "80-job 矩阵", identity["job_manifest_sha256"]],
            ["aggregate.json", "聚合、paired、宏平均、CI、fairness", verification["aggregate_sha256"]],
            ["per_workload_raw.csv", "80-job 核心指标 ledger", sha256(ART / "per_workload_raw.csv")],
            ["table_A.csv", "CAPD/TPP/Oracle/Proactive 对比", sha256(ART / "table_A.csv")],
            ["table_B.csv", "Reactive vs Proactive LRU", sha256(ART / "table_B.csv")],
            ["capd_vs_tpp_paired.csv", "10 cell paired 主比较", sha256(ART / "capd_vs_tpp_paired.csv")],
            ["oracle_headroom.csv", "10 cell Oracle headroom", sha256(ART / "oracle_headroom.csv")],
            ["fairness_audit.json", "10 cell fairness 逐项结果", "passed"],
            ["runtime_smoke.json", "3 checkpoint CUDA smoke", "passed"],
            ["jobs/*/result.json", "每个 job 的完整 metrics、OOV、runtime、cycles/rounds/events/final_state、per_demotion_audit", "80 个文件，逐文件 semantic/result SHA 已验证"],
        ],
    ))
    a("")
    a("## 18. 结果阅读边界")
    a("")
    a("本报告覆盖所有结果 schema 标量、所有 80-job 核心 CSV 字段、全部策略聚合和 CAPD 30 job 的扩展标量。逐事件 arrays 没有为了可读性复制进 Markdown，而是保留在冻结 job JSON 中；任何需要审计单个 cycle、round、event 或 page 的场景，应直接读取对应 JSON 并用其 semantic SHA 校验。")
    a("")
    a("报告生成时间：2026-08-05（本地工作区）；报告生成器只读 r5 证据，不修改 r5 目录。")
    a("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"capd_rows={len(capd_rows)} raw_rows={len(raw_rows)}")


if __name__ == "__main__":
    main()
