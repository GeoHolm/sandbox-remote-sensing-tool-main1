#!/usr/bin/env python3
"""The cotton hyper-local benchmark figure for the cotton pitch.

    python project-level-tests/figure_cotton_benchmark.py

Writes pitch/cotton-2026/cotton_benchmark.png.

Mitchell County, Georgia, 2024: 22 cotton fields inside 3.9 km, 1,870 acres,
read from free imagery with no data from any grower. One of them is the
focus field.

Two panels, because the capability and its catch are the same picture:

  left   cotton against everything else in the same neighbourhood and the
         same year. Cotton holds roughly two and a half times the
         pre-planting cover of the peanut fields around it, which is a
         property of the crop -- peanut harvest inverts the row and leaves
         almost nothing -- not of the farmer.
  right  the focus field ranked among its 21 cotton peers. Against the
         mixed neighbourhood it reads 72nd percentile; against cotton it is
         47th. The 25-point difference is the crop, and it is the argument
         for cotton-specific calibration.

Palette is the one already validated for this repository in
figures_flash.py against the dataviz skill's six checks.
"""
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
PROJ = HERE / "mitchell-ga"
OUT = HERE.parent / "pitch" / "cotton-2026" / "cotton_benchmark.png"
YEAR = 2024

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

hist = pd.read_csv(PROJ / "history.csv")
ann = pd.read_csv(PROJ / "annual_armor_options.csv")
h = hist[hist.year == YEAR][["fid", "crop"]].rename(columns={"crop": "cdl"})
a = ann[ann.year == YEAR].merge(h, on="fid")
a["cotton"] = a.cdl.str.contains("Cotton", na=False)

SCORE = "preplant"
v = a.dropna(subset=[SCORE])
cot = v[v.cotton]
oth = v[~v.cotton]
focus = float(cot.loc[cot.fid == "focus", SCORE].iloc[0])
peers = cot[cot.fid != "focus"][SCORE]
pct_cot = 100 * (peers <= focus).mean()
pct_all = 100 * (v[v.fid != "focus"][SCORE] <= focus).mean()
print("cotton n=%d (focus included), other n=%d" % (len(cot), len(oth)))
print("focus %.3f | cotton pct %.0f | all-neighbour pct %.0f"
      % (focus, pct_cot, pct_all))

fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.6),
                         gridspec_kw={"width_ratios": [1, 1.25]})
rng = np.random.default_rng(4)

# -- left: cotton against the rest of the neighbourhood --------------------
ax = axes[0]
for i, (lab, sub, col) in enumerate(
        (("peanuts, corn\nand sweet corn", oth, RAMP[2]),
         ("cotton", cot, ORANGE))):
    ax.scatter(i + (rng.random(len(sub)) - .5) * .5, sub[SCORE], s=34,
               color=col, alpha=.8, linewidths=0, zorder=2)
    m = sub[SCORE].median()
    ax.plot([i - .34, i + .34], [m, m], "-", color=INK, lw=3, zorder=4)
    ax.text(i + .40, m, "%.2f" % m, va="center", fontsize=12,
            fontweight="bold", color=INK)
    # below the two-line tick label, not on top of it
    ax.text(i, -.215, "n = %d" % len(sub), ha="center", fontsize=10.5,
            color=INK2, transform=ax.get_xaxis_transform())
ax.set_xticks([0, 1])
ax.set_xticklabels(["peanuts, corn\nand sweet corn", "cotton"], fontsize=11.5)
ax.set_xlim(-.6, 1.75)
ax.set_ylim(0, .95)
ax.grid(axis="x", visible=False)
ax.tick_params(length=0)
ax.set_ylabel("pre-planting soil cover", fontsize=10.5)
ax.set_title("Cotton holds more cover than what surrounds it",
             color=INK, fontsize=12.5, fontweight="bold", loc="left", pad=10)

# -- right: the focus field among its cotton peers -------------------------
ax = axes[1]
srt = cot.sort_values(SCORE).reset_index(drop=True)
cols = [ORANGE if f == "focus" else RAMP[2] for f in srt.fid]
ax.bar(range(len(srt)), srt[SCORE], color=cols, width=.82, linewidth=0)
ax.axhline(peers.median(), color=RAMP[0], lw=2, zorder=5)
ax.text(len(srt) - .4, peers.median() + .018, "cotton median %.2f"
        % peers.median(), ha="right", fontsize=10.5, color=RAMP[0],
        fontweight="bold")
fx = int(srt.index[srt.fid == "focus"][0])
ax.annotate("this field\n%.0fth percentile among cotton" % pct_cot,
            xy=(fx, focus), xytext=(fx - 6.5, focus + .26), fontsize=11.5,
            color=ORANGE, fontweight="bold", ha="left",
            arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2,
                            mutation_scale=15))
ax.set_xticks([])
ax.set_xlim(-1, len(srt))
ax.set_ylim(0, .95)
ax.grid(axis="x", visible=False)
ax.tick_params(length=0)
ax.set_xlabel("%d cotton fields within 3.9 km, lowest to highest" % len(srt),
              fontsize=10.5)
ax.set_title("Against cotton, the same field is ordinary", color=INK,
             fontsize=12.5, fontweight="bold", loc="left", pad=10)

fig.tight_layout()
for attempt in range(6):
    try:
        fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
        break
    except OSError:
        if attempt == 5:
            raise
        time.sleep(0.6)
plt.close(fig)
print("wrote", OUT)
