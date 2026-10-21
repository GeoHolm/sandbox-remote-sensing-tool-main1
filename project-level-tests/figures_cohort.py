#!/usr/bin/env python3
"""Benchmark figures for a focus field and its cohort.

    python project-level-tests/figures_cohort.py <project-dir> [--bare]

Writes 02..05 into sumner-ks/figures (the cohort map, 01, is built by
figure_cohort_map.py, which needs the network). `--bare` drops the chart
titles for slide use.

Palette is the one already validated for this repository in
figures_flash.py against the dataviz skill's six checks:

  ordinal   #10427C / #2f74c4 / #85b6ef   dL >= 0.06 each step
  binary    #165bac / #F46C09             CVD dE 27.4, normal dE 38.6

Orange means the focus field and nothing else, in every panel.
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

ASK = ["likely cover crop", "possible cover crop", "no cover crop detected",
       "green cover -- cover crop or small grain"]
POS = ["likely cover crop", "possible cover crop",
       "green cover -- cover crop or small grain"]


def finish(ax, title=None, sub=None, ylab=None, xlab=None):
    if not A.bare:
        if title:
            ax.set_title(title, color=INK, fontsize=13, fontweight="bold",
                         loc="left", pad=20 if sub else 10)
        if sub:
            ax.text(0, 1.015, sub, transform=ax.transAxes, color=INK2,
                    fontsize=10, va="bottom")
    ax.set_ylabel(ylab or "", fontsize=10)
    ax.set_xlabel(xlab or "", fontsize=10)
    ax.tick_params(length=0)


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


def jitter(n, w=0.17):
    return (np.random.default_rng(7).random(n) - 0.5) * 2 * w


a = pd.read_csv(PROJ / "armor_scored.csv")
cov = pd.read_csv(PROJ / "covercrop.csv")
ask = cov[cov.verdict.isin(ASK)].copy()
ask["positive"] = ask.verdict.isin(POS)

# -- 2 --------------------------------------------- the stratum confound --
fig, ax = plt.subplots(figsize=(9.2, 4.6))
groups = [("summer-only rotation", a[~a.winter_crop]),
          ("winter crop standing\nin the window", a[a.winter_crop])]
for i, (lab, sub) in enumerate(groups):
    ax.scatter(i + jitter(len(sub)), sub.armor, s=17, color=RAMP[2],
               alpha=.75, linewidths=0, zorder=2)
    med = sub.armor.median()
    ax.plot([i - .32, i + .32], [med, med], "-", color=RAMP[0], lw=3, zorder=4)
    # Median label to the LEFT, focus callouts to the right. With both on
    # the right they printed on top of each other.
    ax.text(i - .40, med, "median\n%.3f" % med, fontsize=10.5, va="center",
            ha="right", color=RAMP[0], fontweight="bold")
    ax.text(i, -.175, "n = %d field-years" % len(sub), ha="center",
            fontsize=10, color=INK2, transform=ax.get_xaxis_transform())
f = a[a.fid == "focus"]
for _, r in f.iterrows():
    x = 1 if r.winter_crop else 0
    ax.plot(x, r.armor, "o", ms=13, mfc=ORANGE, mec="white", mew=2, zorder=6)
    ax.annotate("%d  %s" % (r.year, r.crop.split()[0]),
                xy=(x, r.armor), xytext=(x + .40, r.armor),
                fontsize=10, color=ORANGE, fontweight="bold", va="center",
                arrowprops=dict(arrowstyle="-", color=ORANGE, lw=1.3))
ax.set_xticks([0, 1])
ax.set_xticklabels([g[0] for g in groups], fontsize=11)
ax.set_xlim(-1.05, 1.95)
ax.set_ylim(0, 1.05)
ax.grid(axis="x", visible=False)
finish(ax, "Soil armor in this county measures the cropping system",
       "Every pre-planting armor reading, 2022-2025. Orange is the focus "
       "field.", "soil armor  (1 - bare soil fraction)")
save(fig, "02_armor_strata.png")

# -- 3 ------------------------------------- focus vs cohort, year by year --
yrs = sorted(f.year.unique())
fig, axes = plt.subplots(1, len(yrs), figsize=(3.3 * len(yrs), 4.4),
                         sharey=True)
axes = np.atleast_1d(axes)
for ax, yr in zip(axes, yrs):
    r = f[f.year == yr].iloc[0]
    peers = a[(a.fid != "focus") & (a.year == yr)
              & (a.winter_crop == r.winter_crop)]
    ax.scatter(jitter(len(peers), .26), peers.armor, s=20, color=RAMP[2],
               alpha=.8, linewidths=0, zorder=2)
    med = peers.armor.median()
    ax.plot([-.36, .36], [med, med], "-", color=RAMP[0], lw=3, zorder=4)
    ax.plot(0, r.armor, "o", ms=14, mfc=ORANGE, mec="white", mew=2, zorder=6)
    pctl = 100 * (peers.armor <= r.armor).mean()
    ax.set_title("%d  %s" % (yr, r.crop if len(r.crop) < 18
                             else r.crop[:16] + "..."),
                 fontsize=11.5, color=INK, fontweight="bold", pad=24)
    ax.text(.5, 1.045, "%s · n=%d peers"
            % ("winter crop" if r.winter_crop else "summer only", len(peers)),
            transform=ax.transAxes, ha="center", fontsize=9.5, color=MUTED)
    ax.text(.5, .035, "focus at the %.0fth percentile" % pctl,
            transform=ax.transAxes, ha="center", fontsize=11,
            color=ORANGE, fontweight="bold")
    ax.set_xticks([])
    ax.set_xlim(-.55, .55)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
axes[0].set_ylabel("soil armor", fontsize=10)
if not A.bare:
    fig.suptitle("The focus field has no settled position", x=.055, ha="left",
                 y=1.06, fontsize=13, fontweight="bold", color=INK)
    fig.text(.055, 1.005, "Compared only against peers in the same stratum "
             "and the same year, it swings from the 4th percentile to the "
             "80th.", fontsize=10, color=INK2, ha="left", va="top")
fig.tight_layout()
save(fig, "03_focus_by_year.png")

# -- 4 ---------------------------------- continuous off-season benchmark ---
m = ask.groupby("fid").max_ndvi.mean().sort_values()
focus_v = m.loc["focus"]
peers = m.drop(index="focus")
pctl = 100 * (peers <= focus_v).mean()
fig, ax = plt.subplots(figsize=(9.6, 4.4))
colors = [ORANGE if i == "focus" else RAMP[2] for i in m.index]
ax.bar(range(len(m)), m.values, color=colors, width=.92, linewidth=0)
ax.axhline(peers.median(), color=RAMP[0], lw=2, zorder=5)
ax.text(len(m) - 1, peers.median() + .015, "cohort median %.2f"
        % peers.median(), ha="right", fontsize=10.5, color=RAMP[0],
        fontweight="bold")
ax.axhline(0.30, color=MUTED, lw=1.4, ls=(0, (5, 4)), zorder=4)
ax.text(1, 0.305, "the 0.30 cover-crop threshold", fontsize=9.5,
        color=MUTED, va="bottom")
fx = list(m.index).index("focus")
ax.annotate("focus field\n%.2f  ·  %.0fth percentile" % (focus_v, pctl),
            xy=(fx, focus_v), xytext=(fx + len(m) * .07, focus_v + .26),
            fontsize=11, color=ORANGE, fontweight="bold",
            arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2))
ax.set_xticks([])
ax.set_xlim(-1, len(m))
finish(ax, "Off-season greenness, every field ranked",
       "Mean peak NDVI over the winters where the question can be asked "
       "(a winter cash crop is not scored either way).",
       "mean off-season peak NDVI", "101 fields, lowest to highest")
save(fig, "04_cover_ranked.png")

# -- 5 ------------------------------------------ armor against greenness ---
wint = cov.copy()
wint["year"] = wint.winter.str[:4].astype(int) + 1
key = wint.set_index(["fid", "year"]).max_ndvi
a["winter_max_ndvi"] = [key.get((fid, yr), np.nan)
                        for fid, yr in zip(a.fid, a.year)]
t = a[a.winter_max_ndvi.notna()].copy()
fig, ax = plt.subplots(figsize=(8.8, 5.0))
for lab, sub, col in (("summer-only rotation", t[~t.winter_crop], RAMP[2]),
                      ("winter crop in the window", t[t.winter_crop], RAMP[1])):
    ax.scatter(sub.winter_max_ndvi, sub.armor, s=20, color=col, alpha=.75,
               linewidths=0, label=lab, zorder=2)
pk = t[t.fid != "focus"]
b, c = np.polyfit(pk.winter_max_ndvi, pk.armor, 1)
r = np.corrcoef(pk.winter_max_ndvi, pk.armor)[0, 1]
xs = np.linspace(t.winter_max_ndvi.min(), t.winter_max_ndvi.max(), 50)
ax.plot(xs, b * xs + c, "-", color=RAMP[0], lw=2.6, zorder=5,
        label="cohort fit  r = %.2f" % r)
ff = t[t.fid == "focus"]
ax.scatter(ff.winter_max_ndvi, ff.armor, s=150, color=ORANGE,
           edgecolors="white", linewidths=2, zorder=7, label="focus field")
ax.set_xlim(0, 1.0)
ax.set_ylim(0, 1.05)
ax.legend(frameon=False, fontsize=10, loc="upper left")
finish(ax, "Soil armor is largely a restatement of off-season greenness",
       "%d field-years. The fit is on the 100 cohort fields; r = %.2f."
       % (len(t), r), "soil armor", "off-season peak NDVI")
save(fig, "05_armor_vs_green.png")

print("\nwrote to %s" % FIG)
