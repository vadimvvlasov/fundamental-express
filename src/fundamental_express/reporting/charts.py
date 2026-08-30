"""Matplotlib chart generators used by the three PDF report builders (FCF
for Ordinary, NII for Bank, FFO/AFFO for REIT). Each renders a PNG to
SCRATCH_DIR and returns its path. Moved verbatim out of
financial_analyzer.py (docs/spec/refactor-tasks.md T05).
"""

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# src/fundamental_express/reporting/charts.py -> repo root is 3 parents up.
SCRIPT_DIR = Path(__file__).resolve().parents[3]
SCRATCH_DIR = str(SCRIPT_DIR / "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)


# ── CHART GENERATOR ─────────────────────────────────────────────────────
def generate_fcf_chart(years, hist_fcf, proj_years, proj_fcf, ticker):
    fig, ax = plt.subplots(figsize=(7, 3))

    fig.patch.set_facecolor("white")
    ax.set_facecolor("#F8FAFC")

    hist_x = list(range(len(years)))
    ax.bar(
        hist_x,
        [val / 1e9 for val in hist_fcf],
        color="#0F766E",
        label="Исторический FCF",
        width=0.4,
    )

    proj_x = list(range(len(years), len(years) + len(proj_years)))
    ax.bar(
        proj_x,
        [val / 1e9 for val in proj_fcf],
        color="#0284C7",
        label="Прогнозный FCF",
        width=0.4,
    )

    ax.set_title(
        f"Свободный денежный поток (FCF) компании {ticker} (в млрд. USD)",
        fontsize=10,
        fontweight="bold",
        color="#1E293B",
    )
    all_years = list(years) + [f"Y{i}" for i in proj_years]
    ax.set_xticks(range(len(all_years)))
    ax.set_xticklabels(all_years, fontsize=8)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#64748B")
    ax.spines["bottom"].set_color("#64748B")
    ax.tick_params(colors="#334155", labelsize=8)
    ax.legend(frameon=True, facecolor="white", edgecolor="none", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color="#64748B")

    plt.tight_layout()
    chart_path = os.path.join(SCRATCH_DIR, f"{ticker}_fcf_chart.png")
    plt.savefig(chart_path, dpi=300, bbox_inches="tight")
    plt.close()
    return chart_path


def generate_nii_chart(years, nii_values, ticker):
    """Historical-only NII bar chart - unlike generate_fcf_chart() there is
    no projected-NII bar: the DDM/ROE-P-B models forecast DPS or apply a
    static ROE multiple, never a forward NII path, so a projection bar here
    would be invented data.
    """
    fig, ax = plt.subplots(figsize=(7, 3))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#F8FAFC")
    ax.bar(range(len(years)), [v / 1e9 for v in nii_values], color="#0F766E", width=0.4)
    ax.set_title(
        f"Чистый процентный доход (NII) банка {ticker} (в млрд. USD)",
        fontsize=10, fontweight="bold", color="#1E293B",
    )
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#64748B")
    ax.spines["bottom"].set_color("#64748B")
    ax.tick_params(colors="#334155", labelsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color="#64748B")
    plt.tight_layout()
    chart_path = os.path.join(SCRATCH_DIR, f"{ticker}_nii_chart.png")
    plt.savefig(chart_path, dpi=300, bbox_inches="tight")
    plt.close()
    return chart_path


def generate_ffo_chart(years, ffo_values, affo_values, ticker):
    """Historical-only FFO/AFFO bar chart - like generate_nii_chart(), no
    projection bar: the NAV model doesn't forecast a forward FFO/AFFO path,
    it capitalizes the latest NOI at a static Cap Rate."""
    fig, ax = plt.subplots(figsize=(7, 3))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#F8FAFC")
    x = range(len(years))
    width = 0.35
    ax.bar([i - width / 2 for i in x], [v / 1e9 for v in ffo_values], width=width, color="#0F766E", label="FFO")
    ax.bar([i + width / 2 for i in x], [v / 1e9 for v in affo_values], width=width, color="#0284C7", label="AFFO")
    ax.set_title(f"FFO / AFFO REIT {ticker} (в млрд. USD)", fontsize=10, fontweight="bold", color="#1E293B")
    ax.set_xticks(list(x))
    ax.set_xticklabels(years, fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#64748B")
    ax.spines["bottom"].set_color("#64748B")
    ax.tick_params(colors="#334155", labelsize=8)
    ax.legend(frameon=True, facecolor="white", edgecolor="none", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color="#64748B")
    plt.tight_layout()
    chart_path = os.path.join(SCRATCH_DIR, f"{ticker}_ffo_chart.png")
    plt.savefig(chart_path, dpi=300, bbox_inches="tight")
    plt.close()
    return chart_path
