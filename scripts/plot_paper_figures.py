"""Generate paper figures for QMAP evaluation.

Outputs single-column vector PDFs suitable for conference papers:
  figures/qmap_cost_delta.pdf
  figures/qmap_seed_stability.pdf

For visual inspection before final PDF export, it can also emit PNG previews:
  figures/qmap_cost_delta_preview.png
  figures/qmap_seed_stability_preview.png
"""

from __future__ import annotations

import math
import os

import matplotlib.pyplot as plt
import numpy as np


FIGURE_DIR = "figures"


def cost_delta(qmap_cost: float, baseline_cost: float) -> float:
    return (qmap_cost - baseline_cost) * 100.0 / baseline_cost


def configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "hatch.linewidth": 0.5,
        }
    )


def save_pdf(fig: plt.Figure, filename: str) -> None:
    os.makedirs(FIGURE_DIR, exist_ok=True)
    path = os.path.join(FIGURE_DIR, filename)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.025)
    plt.close(fig)
    print(path)


def save_png(fig: plt.Figure, filename: str) -> None:
    os.makedirs(FIGURE_DIR, exist_ok=True)
    path = os.path.join(FIGURE_DIR, filename)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print(path)


def plot_cost_delta(output_format: str = "pdf") -> None:
    labels = ["blackscholes", "streamcluster\npressure", "dedup\npressure", "canneal"]
    values = [
        cost_delta(105_983, 106_952),
        cost_delta(264_501, 301_767),
        cost_delta(201_567, 201_567),
        cost_delta(150_559, 126_178),
    ]

    # Colorblind-safe blue for wins, orange for losses, neutral gray for ties.
    win_color = "#0072B2"
    loss_color = "#D55E00"
    tie_color = "#7A7A7A"
    colors = [win_color if v < -0.05 else loss_color if v > 0.05 else tie_color for v in values]

    fig, ax = plt.subplots(figsize=(3.35, 2.05))
    y = np.arange(len(labels))
    bars = ax.barh(y, values, height=0.58, color=colors, edgecolor="black", linewidth=0.55)

    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Cost delta vs. best baseline (%)")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(-15.5, 22.5)
    ax.set_xticks([-15, -10, -5, 0, 5, 10, 15, 20])
    ax.grid(axis="x", color="#D0D0D0", linewidth=0.45, linestyle="-", alpha=0.65)
    ax.set_axisbelow(True)

    for bar, value in zip(bars, values):
        label = f"{value:+.2f}%"
        if value < -3.0:
            ax.text(
                value / 2.0,
                bar.get_y() + bar.get_height() / 2,
                label,
                ha="center",
                va="center",
                fontsize=7,
                color="white",
                fontweight="bold",
            )
        elif value < 0:
            ax.text(
                value - 0.65,
                bar.get_y() + bar.get_height() / 2,
                label,
                ha="right",
                va="center",
                fontsize=7,
            )
        elif math.isclose(value, 0.0, abs_tol=0.005):
            ax.text(
                0.55,
                bar.get_y() + bar.get_height() / 2,
                "0.00%",
                ha="left",
                va="center",
                fontsize=7,
            )
        elif value > 3.0:
            ax.text(
                value / 2.0,
                bar.get_y() + bar.get_height() / 2,
                label,
                ha="center",
                va="center",
                fontsize=7,
                color="white",
                fontweight="bold",
            )
        else:
            ax.text(
                value + 0.65,
                bar.get_y() + bar.get_height() / 2,
                label,
                ha="left",
                va="center",
                fontsize=7,
            )

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    if output_format == "png":
        save_png(fig, "qmap_cost_delta_preview.png")
    else:
        save_pdf(fig, "qmap_cost_delta_final.pdf")


def plot_seed_stability(output_format: str = "pdf") -> None:
    workloads = ["streamcluster\npressure", "blackscholes", "canneal"]
    data = {
        "streamcluster\npressure": [
            cost_delta(264_501, 301_767),
            cost_delta(270_304, 301_767),
            cost_delta(265_585, 301_767),
        ],
        "blackscholes": [
            cost_delta(105_983, 106_952),
            cost_delta(104_707, 106_952),
            cost_delta(105_002, 106_952),
        ],
        "canneal": [
            cost_delta(150_559, 126_178),
            cost_delta(152_154, 126_178),
            cost_delta(147_212, 126_178),
        ],
    }

    fig, ax = plt.subplots(figsize=(3.35, 2.05))
    y = np.arange(len(workloads))
    jitter = np.array([-0.10, 0.0, 0.10])

    point_color = "#4D4D4D"
    mean_color = "#0072B2"
    fail_color = "#D55E00"

    for i, workload in enumerate(workloads):
        vals = np.array(data[workload])
        ax.scatter(
            vals,
            np.full_like(vals, y[i], dtype=float) + jitter,
            s=18,
            facecolor="white",
            edgecolor=point_color,
            linewidth=0.75,
            zorder=3,
        )
        mean = vals.mean()
        std = vals.std(ddof=1)
        color = fail_color if mean > 0 else mean_color
        ax.scatter(
            mean,
            y[i],
            marker="D",
            s=20,
            color=color,
            zorder=4,
        )
        # Draw a horizontal std. range around the mean. Matplotlib's xerr is
        # clearer for this horizontal layout than the default vertical errorbar.
        ax.errorbar(
            mean,
            y[i],
            xerr=std,
            fmt="none",
            ecolor=color,
            elinewidth=1.0,
            capsize=3,
            capthick=1.0,
            zorder=3,
        )
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Cost delta vs. best baseline (%)")
    ax.set_yticks(y)
    ax.set_yticklabels(workloads)
    ax.invert_yaxis()
    ax.set_xlim(-15.5, 23.0)
    ax.set_xticks([-15, -10, -5, 0, 5, 10, 15, 20])
    ax.grid(axis="x", color="#D0D0D0", linewidth=0.45, linestyle="-", alpha=0.65)
    ax.set_axisbelow(True)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    if output_format == "png":
        save_png(fig, "qmap_seed_stability_preview.png")
    else:
        save_pdf(fig, "qmap_seed_stability_final.pdf")


def main() -> None:
    configure_matplotlib()
    plot_cost_delta("png")
    plot_seed_stability("png")
    plot_cost_delta("pdf")
    plot_seed_stability("pdf")


if __name__ == "__main__":
    main()
