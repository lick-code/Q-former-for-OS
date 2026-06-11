"""Generate a compact HotStorage-style main-results figure for CAPD.

The design intentionally avoids repeating four full grouped-bar panels.  It
uses a cost leaderboard for all policies and a dense outcome matrix for CAPD's
secondary effects.  Outputs are written to outputs/figures:
  - capd_main_results.pdf
  - capd_main_results.svg
  - capd_main_results.png
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "results" / "ml_baselines" / "summary.csv"
OUT_DIR = ROOT / "outputs" / "figures"

WORKLOADS = [
    ("blackscholes", "blackscholes"),
    ("streamcluster_pressure", "streamcluster\npressure"),
    ("dedup_pressure", "dedup\npressure"),
]

POLICIES = [
    "lru",
    "random",
    "lfu",
    "clock",
    "kleio_lite",
    "patterns_lite",
    "qmap",
]

DISPLAY = {
    "lru": "LRU",
    "random": "Random",
    "lfu": "LFU",
    "clock": "CLOCK",
    "kleio_lite": "Kleio-lite",
    "patterns_lite": "PatternS-lite",
    "qmap": "CAPD",
}

STYLE = {
    "lru": dict(color="#FFFFFF", marker="o", size=34, edge="#111111", linewidth=0.9),
    "random": dict(color="#D2D2D2", marker="o", size=34, edge="#111111", linewidth=0.55),
    "lfu": dict(color="#777777", marker="s", size=34, edge="#111111", linewidth=0.55),
    "clock": dict(color="#344552", marker="D", size=34, edge="#111111", linewidth=0.55),
    "kleio_lite": dict(color="#62A8D1", marker="^", size=39, edge="#111111", linewidth=0.55),
    "patterns_lite": dict(color="#35B6BC", marker="v", size=39, edge="#111111", linewidth=0.55),
    "qmap": dict(color="#EF3B2C", marker="s", size=54, edge="#111111", linewidth=0.75),
}

CAPD_RED = "#EF3B2C"
LIGHT_RED = "#FCE7E4"
GRID = "#D9D9D9"
TEXT = "#111111"


@dataclass(frozen=True)
class Metric:
    label: str
    column: str
    from_hit_rate: bool = False


METRICS = [
    Metric("Weighted\ncost", "weighted_access_cost"),
    Metric("Miss\nrate", "hit_rate_percent", from_hit_rate=True),
    Metric("NVM\nwrites", "nvm_writes"),
    Metric("Migrations", "migrations"),
]


def configure_matplotlib() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "font.family": "Arial",
            "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 8.8,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 7.0,
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.65,
            "ytick.major.width": 0.65,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def value(row: pd.Series, metric: Metric) -> float:
    raw = float(row[metric.column])
    if metric.from_hit_rate:
        return 100.0 - raw
    return raw


def pct_delta(new: float, base: float) -> float:
    if base == 0.0:
        return 0.0 if new == 0.0 else np.nan
    return (new - base) * 100.0 / base


def load_data() -> pd.DataFrame:
    data = pd.read_csv(SOURCE)
    wanted_workloads = {name for name, _ in WORKLOADS}
    data = data[data["workload"].isin(wanted_workloads) & data["policy"].isin(POLICIES)].copy()

    missing = []
    for workload, _ in WORKLOADS:
        for policy in POLICIES:
            if data[(data["workload"] == workload) & (data["policy"] == policy)].empty:
                missing.append(f"{workload}/{policy}")
    if missing:
        raise RuntimeError("Missing rows in main-result CSV: " + ", ".join(missing))
    return data


def row_for(data: pd.DataFrame, workload: str, policy: str) -> pd.Series:
    return data[(data["workload"] == workload) & (data["policy"] == policy)].iloc[0]


def cost_delta_vs_lru(data: pd.DataFrame, workload: str, policy: str) -> float:
    lru = float(row_for(data, workload, "lru")["weighted_access_cost"])
    cost = float(row_for(data, workload, policy)["weighted_access_cost"])
    return pct_delta(cost, lru)


def capd_metric_delta_vs_lru(data: pd.DataFrame, workload: str, metric: Metric) -> float:
    lru = value(row_for(data, workload, "lru"), metric)
    capd = value(row_for(data, workload, "qmap"), metric)
    return pct_delta(capd, lru)


def best_non_capd_cost_policy(data: pd.DataFrame, workload: str) -> str:
    candidates = [p for p in POLICIES if p != "qmap"]
    return min(candidates, key=lambda p: float(row_for(data, workload, p)["weighted_access_cost"]))


def draw_leaderboard(ax: plt.Axes, data: pd.DataFrame) -> None:
    y_base = np.arange(len(WORKLOADS))[::-1].astype(float)
    offsets = np.linspace(0.27, -0.27, len(POLICIES))
    offset_by_policy = dict(zip(POLICIES, offsets))

    for idx, (workload, label) in enumerate(WORKLOADS):
        base = y_base[idx]
        ax.axhspan(base - 0.43, base + 0.43, color="#FAFAFA" if idx % 2 == 0 else "#FFFFFF", zorder=0)
        ax.hlines(base, -16.0, 22.0, color="#EEEEEE", linewidth=0.7, zorder=0)

        deltas = {policy: cost_delta_vs_lru(data, workload, policy) for policy in POLICIES}
        best_policy = best_non_capd_cost_policy(data, workload)
        best_delta = deltas[best_policy]
        capd_delta = deltas["qmap"]

        # Show the distance from the strongest non-CAPD result to CAPD.
        bracket_y = base + 0.38
        ax.plot(
            [best_delta, capd_delta],
            [bracket_y, bracket_y],
            color=CAPD_RED,
            linewidth=1.0,
            solid_capstyle="round",
            zorder=2,
        )
        ax.plot([best_delta, best_delta], [bracket_y - 0.035, bracket_y + 0.035], color=CAPD_RED, linewidth=0.9)
        ax.plot([capd_delta, capd_delta], [bracket_y - 0.035, bracket_y + 0.035], color=CAPD_RED, linewidth=0.9)

        best_cost = float(row_for(data, workload, best_policy)["weighted_access_cost"])
        capd_cost = float(row_for(data, workload, "qmap")["weighted_access_cost"])
        gain = pct_delta(capd_cost, best_cost)
        gain_text = "tie" if abs(gain) < 0.01 else f"{abs(gain):.1f}% lower"
        mid = (best_delta + capd_delta) / 2.0
        ax.text(
            mid,
            bracket_y + 0.075,
            gain_text,
            ha="center",
            va="bottom",
            fontsize=6.5,
            color=CAPD_RED,
            fontweight="bold",
        )

        for policy in POLICIES:
            style = STYLE[policy]
            y = base + offset_by_policy[policy]
            x = deltas[policy]
            ax.scatter(
                x,
                y,
                s=style["size"],
                marker=style["marker"],
                facecolor=style["color"],
                edgecolor=style["edge"],
                linewidth=style["linewidth"],
                zorder=4,
            )
            if policy == best_policy:
                ax.scatter(
                    x,
                    y,
                    s=style["size"] + 62,
                    marker="o",
                    facecolor="none",
                    edgecolor="#111111",
                    linewidth=0.85,
                    zorder=3,
                )
            if policy == "qmap":
                ax.text(
                    x,
                    y - 0.105,
                    f"{x:.1f}",
                    ha="center",
                    va="top",
                    fontsize=6.5,
                    color=CAPD_RED,
                    fontweight="bold",
                    zorder=5,
                )

    ax.axvline(0.0, color="#111111", linewidth=0.85, linestyle=(0, (4, 2)), zorder=1)
    ax.set_xlim(-16.0, 22.0)
    ax.set_ylim(-0.55, len(WORKLOADS) - 0.45)
    ax.set_xticks([-15, -10, -5, 0, 5, 10, 15, 20])
    ax.set_yticks(y_base)
    ax.set_yticklabels([label for _, label in WORKLOADS])
    ax.set_xlabel("Weighted cost delta vs. LRU (%)")
    ax.set_title("(a) Cost leaderboard", loc="left", fontweight="bold", pad=4.0)
    ax.grid(axis="x", color=GRID, linewidth=0.5, linestyle="-", alpha=0.85)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(axis="y", length=0)


def cell_color(delta: float, scale: float) -> tuple[float, float, float, float]:
    if abs(delta) < 0.01:
        return (0.96, 0.96, 0.96, 1.0)
    if delta < 0:
        alpha = min(0.92, max(0.22, abs(delta) / scale))
        base = np.array(mpl.colors.to_rgb(CAPD_RED))
        white = np.array([1.0, 1.0, 1.0])
        rgb = white * (1.0 - alpha) + base * alpha
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)

    alpha = min(0.85, max(0.2, delta / scale))
    base = np.array(mpl.colors.to_rgb("#6B6B6B"))
    white = np.array([1.0, 1.0, 1.0])
    rgb = white * (1.0 - alpha) + base * alpha
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)


def draw_impact_matrix(ax: plt.Axes, data: pd.DataFrame) -> None:
    ax.set_xlim(0.0, len(WORKLOADS))
    ax.set_ylim(0.0, len(METRICS))
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_title("(b) CAPD effect profile", loc="left", fontweight="bold", pad=20.0)

    # Per-row scales keep both small cost improvements and large write cuts visible.
    row_scales = {
        "Weighted\ncost": 15.0,
        "Miss\nrate": 55.0,
        "NVM\nwrites": 80.0,
        "Migrations": 55.0,
    }

    for row_idx, metric in enumerate(METRICS):
        ax.text(
            -0.12,
            row_idx + 0.5,
            metric.label,
            ha="right",
            va="center",
            fontsize=7.2,
            color=TEXT,
            linespacing=0.95,
        )
        for col_idx, (workload, _) in enumerate(WORKLOADS):
            delta = capd_metric_delta_vs_lru(data, workload, metric)
            color = cell_color(delta, row_scales[metric.label])
            rect = Rectangle(
                (col_idx + 0.04, row_idx + 0.08),
                0.92,
                0.84,
                facecolor=color,
                edgecolor="#111111",
                linewidth=0.45,
            )
            ax.add_patch(rect)
            label = "tie" if abs(delta) < 0.01 else f"{delta:.1f}%"
            rgb = np.array(color[:3])
            luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
            ax.text(
                col_idx + 0.5,
                row_idx + 0.5,
                label,
                ha="center",
                va="center",
                fontsize=7.4,
                color="white" if luminance < 0.56 else TEXT,
                fontweight="bold" if abs(delta) > 0.01 else "normal",
            )

    for col_idx, (_, label) in enumerate(WORKLOADS):
        ax.text(
            (col_idx + 0.5) / len(WORKLOADS),
            1.015,
            label,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=7.0,
            linespacing=0.92,
            color=TEXT,
            clip_on=False,
        )

    ax.text(
        1.5,
        len(METRICS) + 0.26,
        "Cells show CAPD delta vs. LRU; lower is better.",
        ha="center",
        va="bottom",
        fontsize=6.7,
        color="#333333",
    )


def build_legend(fig: plt.Figure) -> None:
    handles = []
    for policy in POLICIES:
        style = STYLE[policy]
        handles.append(
            Line2D(
                [0],
                [0],
                marker=style["marker"],
                linestyle="none",
                markersize=np.sqrt(style["size"]) * 0.72,
                markerfacecolor=style["color"],
                markeredgecolor=style["edge"],
                markeredgewidth=style["linewidth"],
                label=DISPLAY[policy],
            )
        )
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markersize=6.2,
            markerfacecolor="none",
            markeredgecolor="#111111",
            markeredgewidth=0.9,
            label="best non-CAPD",
        )
    )
    fig.legend(
        handles=handles,
        loc="upper center",
        ncol=8,
        frameon=False,
        bbox_to_anchor=(0.5, 1.01),
        handletextpad=0.42,
        columnspacing=0.82,
    )


def print_headlines(data: pd.DataFrame) -> None:
    print("Weighted-cost delta vs best non-CAPD:")
    for workload, label in WORKLOADS:
        best_policy = best_non_capd_cost_policy(data, workload)
        best_cost = float(row_for(data, workload, best_policy)["weighted_access_cost"])
        capd_cost = float(row_for(data, workload, "qmap")["weighted_access_cost"])
        delta = pct_delta(capd_cost, best_cost)
        print(f"  {label.replace(chr(10), '-')}: {delta:+.2f}% vs {DISPLAY[best_policy]}")

    print("CAPD deltas vs LRU:")
    for workload, label in WORKLOADS:
        values = [capd_metric_delta_vs_lru(data, workload, metric) for metric in METRICS]
        numbers = ", ".join(f"{metric.label.replace(chr(10), ' ')}={delta:+.1f}%" for metric, delta in zip(METRICS, values))
        print(f"  {label.replace(chr(10), '-')}: {numbers}")


def main() -> None:
    configure_matplotlib()
    data = load_data()

    fig = plt.figure(figsize=(7.1, 3.05))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.66, 1.0], wspace=0.34)
    ax_leaderboard = fig.add_subplot(gs[0, 0])
    ax_matrix = fig.add_subplot(gs[0, 1])

    draw_leaderboard(ax_leaderboard, data)
    draw_impact_matrix(ax_matrix, data)
    build_legend(fig)

    fig.subplots_adjust(left=0.085, right=0.988, top=0.80, bottom=0.17)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        OUT_DIR / "capd_main_results.pdf",
        OUT_DIR / "capd_main_results.svg",
        OUT_DIR / "capd_main_results.png",
    ]:
        pad = 0.02 if path.suffix == ".pdf" else 0.045
        fig.savefig(path, bbox_inches="tight", pad_inches=pad)
        print(path)
    plt.close(fig)
    print_headlines(data)


if __name__ == "__main__":
    main()
