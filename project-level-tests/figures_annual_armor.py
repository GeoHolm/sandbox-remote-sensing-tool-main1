#!/usr/bin/env python3
"""Figures comparing the calendar-year soil armor candidates.

    python project-level-tests/figures_annual_armor.py <project-dir> [--bare]

Writes 06_annual_candidates.png and 07_focus_under_each.png.
Palette as in figures_cohort.py. Orange is the focus field, and in figure
06 orange marks the stratum that should NOT be separable.
"""
import argparse
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
BLUE, ORANGE = "#165bac", "#F46C09"
RAMP = ["#10427C", "#2f74c4", "#85b6ef"]
GRID = "#e6e6e6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
})

ap = argparse.ArgumentParser()
ap.add_argument("proj", help="project directory, e.g. champaign-il")
ap.add_argument("--bare", action="store_true")
A = ap.parse_args()
PROJ = HERE / A.proj
FIG = PROJ / "figures" / "deck" if A.bare else PROJ / "figures"
FIG.mkdir(parents=True, exist_ok=True)

LABELS = {
    "preplant": "pre-plant window\n(shipped today)",
    "mean": "annual mean\narmor",
    "exposure": "days below\n50% cover",
    "worst": "worst 10%\nof the year",
    "nongrow": "outside the\ndetected season",
    "residue": "annual mean\nresidue only",
}
ORDER = ["preplant", "mean", "exposure", "nongrow", "worst", "residue"]


def save(fig, name):
    for attempt in range(6):
        try:
            fig.savefig(FIG / name, dpi=170, bbox_inches="tight",
                        facecolor="white")
            break
        except OSError:
            if attempt == 5:
                raise
            time.sleep(0.6)
    plt.close(fig)
    print("  wrote", name)


full = pd.read_csv(PROJ / "annual_armor_options.csv")
# 2026 has no CDL, so it cannot be put in a stratum -- but it is a perfectly
# good field-year for ranking fields against each other. Figure 6 needs the
# stratified subset; figure 7 must use everything, or its percentiles stop
# matching the ones analyse_cohort.py prints.
a = full[full.winter_crop.notna()].copy()
a["winter_crop"] = a.winter_crop.astype(bool)
rng = np.random.default_rng(11)

# -- 6 ------------------------------------------- does it rank the crop? --
fig, axes = plt.subplots(2, 3, figsize=(12.6, 7.0))
for ax, s in zip(axes.ravel(), ORDER):
    v = a.dropna(subset=[s])
    z = (v[s] - v[s].mean()) / v[s].std()
    w, m = z[v.winter_crop], z[~v.winter_crop]
    sd = np.sqrt(((len(w) - 1) * w.var() + (len(m) - 1) * m.var())
                 / max(len(w) + len(m) - 2, 1))
    d = (w.mean() - m.mean()) / sd
    for i, (lab, sub, col) in enumerate((("summer\nonly", m, RAMP[2]),
                                         ("winter\ncrop", w, ORANGE))):
        ax.scatter(sub + rng.normal(0, .0, len(sub)),
                   i + (rng.random(len(sub)) - .5) * .55,
                   s=9, color=col, alpha=.5, linewidths=0, zorder=2)
        ax.plot([sub.mean(), sub.mean()], [i - .36, i + .36], "-",
                color=RAMP[0] if i == 0 else "#b3500a", lw=2.6, zorder=4)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["summer\nonly", "winter\ncrop"], fontsize=9.5)
    ax.set_ylim(-.7, 1.7)
    ax.set_xlim(-3.2, 3.2)
    ax.grid(axis="y", visible=False)
    ax.tick_params(length=0)
    ax.set_title(LABELS[s], fontsize=11, color=INK, fontweight="bold",
                 loc="left", pad=16)
    good = abs(d) < 0.6
    ax.text(1.0, 1.045, "crop bias  d = %+.2f" % d, transform=ax.transAxes,
            ha="right", fontsize=10.5, fontweight="bold",
            color="#1a7f37" if good else ORANGE)
    ax.set_xlabel("standard deviations", fontsize=9)
if not A.bare:
    fig.suptitle("Which annual score stops ranking the cropping system?",
                 x=.055, ha="left", y=1.035, fontsize=13, fontweight="bold",
                 color=INK)
    fig.text(.055, .995, "505 field-years. The two rows should sit on top of "
             "each other: a soil-cover score ought not to know whether a "
             "winter crop was grown.", fontsize=10, color=INK2, ha="left",
             va="top")
fig.tight_layout()
save(fig, "06_annual_candidates.png")

# -- 7 ----------------------------------------- focus under each score ----
rows = []
for s in ORDER:
    v = full.dropna(subset=[s])
    m = v.groupby("fid")[s].mean()
    if "focus" not in m.index:
        continue
    f, peers = m.loc["focus"], m.drop(index="focus")
    pct = 100 * (peers <= f).mean()
    if s == "exposure":          # more exposure is worse: flip to "cover rank"
        pct = 100 - pct
    rows.append({"score": s, "pct": pct, "n": len(m)})
r = pd.DataFrame(rows)

fig, ax = plt.subplots(figsize=(9.8, 4.4))
cols = [ORANGE if s in ("preplant",) else RAMP[1] for s in r.score]
ax.barh(range(len(r)), r.pct, color=cols, height=.62, linewidth=0)
ax.axvline(50, color=INK2, lw=1.4, ls=(0, (5, 4)), zorder=4)
ax.text(50.8, -0.45, "cohort median", fontsize=10, color=INK2,
        va="center")
for i, (_, row) in enumerate(r.iterrows()):
    ax.text(row.pct + 1.2, i, "%.0f" % row.pct, va="center", fontsize=10.5,
            fontweight="bold", color=INK)
ax.set_yticks(range(len(r)))
ax.set_yticklabels([LABELS[s].replace("\n", " ") for s in r.score],
                   fontsize=10.5)
ax.invert_yaxis()
ax.set_xlim(0, 100)
ax.grid(axis="y", visible=False)
ax.tick_params(length=0)
if not A.bare:
    ax.set_title("The focus field's standing depends on which score you pick",
                 color=INK, fontsize=13, fontweight="bold", loc="left", pad=20)
    ax.text(0, 1.015, "Percentile among 101 fields, higher = better covered. "
            "Exposure days inverted so every bar reads the same way.",
            transform=ax.transAxes, color=INK2, fontsize=10, va="bottom")
ax.set_xlabel("percentile among the 101 fields", fontsize=10)
save(fig, "07_focus_under_each.png")

print("\nwrote to %s" % FIG)
