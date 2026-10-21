#!/usr/bin/env python3
"""Compare the hyper-local benchmark across every county run so far.

    python project-level-tests/compare_counties.py [dir ...]

One county is an anecdote. Three are the beginning of a question: does the
benchmark behave the same way in a wheat rotation, a corn/soy rotation and
a peanut/cotton rotation? Writes compare_counties.csv and two figures into
project-level-tests/_across/.
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
BARE = "--bare" in sys.argv
OUT = HERE / "_across" / "deck" if BARE else HERE / "_across"
DEFAULT = ["champaign-il", "sumner-ks", "mitchell-ga"]

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

POS = ["likely cover crop", "possible cover crop",
       "green cover -- cover crop or small grain"]
WINTER_CROPS = ("Winter Wheat", "Dbl Crop WinWht/Soybeans",
                "Dbl Crop WinWht/Sorghum", "Dbl Crop WinWht/Corn",
                "Rye", "Triticale", "Barley", "Oats", "Canola",
                "Dbl Crop WinWht/Cotton")
SCORES = ["preplant", "mean", "exposure", "nongrow", "worst", "residue"]


def load(d):
    p = HERE / d
    meta = json.loads((p / "cohort_meta.json").read_text())
    cov = pd.read_csv(p / "covercrop.csv")
    hist = pd.read_csv(p / "history.csv")
    ann = pd.read_csv(p / "annual_armor_options.csv")
    arm = pd.read_csv(p / "armor.csv")
    return dict(dir=d, county=meta.get("county", d),
                radius_km=meta["radius_m"] / 1000, n=meta["cohort_n"],
                cov=cov, hist=hist, ann=ann, arm=arm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", default=DEFAULT)
    ap.add_argument("--bare", action="store_true",
                    help="drop chart titles; the slide supplies them")
    a = ap.parse_args()
    C = [load(d) for d in (a.dirs or DEFAULT)]

    rows = []
    for c in C:
        cov, ann, hist = c["cov"], c["ann"], c["hist"]
        cov["positive"] = cov.verdict.isin(POS)
        cov["askable"] = cov.verdict != "winter cash crop, not a cover crop"
        ask = cov[cov.askable]
        hist["winter"] = hist.crop.isin(WINTER_CROPS)
        pre_n = int(ann.preplant.notna().sum())
        rows.append({
            "county": c["county"], "fields": ann.fid.nunique(),
            "radius_km": round(c["radius_km"], 1),
            "field_years": len(ann),
            "winter_crop_pct": round(100 * hist.winter.mean(), 1),
            "preplant_coverage_pct": round(100 * pre_n / len(ann), 1),
            "annual_coverage_pct": round(100 * ann.residue.notna().mean(), 1),
            "preplant_median_obs": int(c["arm"].n_obs.median()),
            "cover_askable_pct": round(100 * len(ask) / max(len(cov), 1), 1),
            "cover_positive_pct": round(100 * ask.positive.mean(), 1),
            "fields_any_cover_pct": round(
                100 * (ask.groupby("fid").positive.any().mean()), 1),
            "offseason_median_ndvi": round(ask.max_ndvi.median(), 3),
        })
        for s in SCORES:
            v = ann.dropna(subset=[s])
            g = v[v.winter_max_ndvi.notna()]
            r = (np.corrcoef(g[s], g.winter_max_ndvi)[0, 1]
                 if len(g) > 10 else np.nan)
            grp = v.groupby("fid")[s]
            bet, wit = grp.mean().var(), grp.var().mean()
            rows[-1]["%s_r_green" % s] = round(abs(r), 2)
            rows[-1]["%s_icc" % s] = round(bet / (bet + wit), 2)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "compare_counties.csv", index=False)

    pd.set_option("display.width", 250)
    print("=" * 96)
    print("THREE COUNTIES, THREE ROTATIONS")
    print("=" * 96)
    print(t[["county", "fields", "radius_km", "winter_crop_pct",
             "preplant_coverage_pct", "annual_coverage_pct",
             "preplant_median_obs"]].to_string(index=False))
    print()
    print("COVER CROP: the same thresholds, three answers")
    print(t[["county", "cover_askable_pct", "cover_positive_pct",
             "fields_any_cover_pct", "offseason_median_ndvi"]]
          .to_string(index=False))
    print()
    print("INDEPENDENCE FROM OFF-SEASON GREENNESS  |r|")
    print(t[["county"] + ["%s_r_green" % s for s in SCORES]].to_string(index=False))
    print()
    print("BETWEEN-FIELD SHARE OF VARIANCE (stability)")
    print(t[["county"] + ["%s_icc" % s for s in SCORES]].to_string(index=False))

    # -- fig A: cover crop positive rate ------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    ax = axes[0]
    x = np.arange(len(t))
    ax.bar(x, t.cover_positive_pct, color=RAMP[1], width=.6, linewidth=0)
    for i, v in enumerate(t.cover_positive_pct):
        ax.text(i, v + 1.6, "%.0f%%" % v, ha="center", fontsize=12,
                fontweight="bold", color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([c.split(" County")[0] for c in t.county], fontsize=11)
    ax.set_ylim(0, 100)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.set_ylabel("winters scored as off-season green", fontsize=10)
    if not BARE:
        ax.set_title("The same threshold, three answers", color=INK, fontsize=12.5,
                 fontweight="bold", loc="left", pad=10)

    ax = axes[1]
    for i, c in enumerate(C):
        cov = c["cov"]
        ask = cov[cov.verdict != "winter cash crop, not a cover crop"]
        ax.scatter(np.full(len(ask), i) + (np.random.default_rng(3)
                   .random(len(ask)) - .5) * .5, ask.max_ndvi, s=8,
                   color=RAMP[2], alpha=.55, linewidths=0, zorder=2)
        m = ask.max_ndvi.median()
        ax.plot([i - .3, i + .3], [m, m], "-", color=RAMP[0], lw=3, zorder=4)
    ax.axhline(0.30, color=ORANGE, lw=2, ls=(0, (5, 4)), zorder=5)
    ax.text(len(C) - .5, .315, "the 0.30 threshold", ha="right",
            fontsize=10.5, color=ORANGE, fontweight="bold")
    ax.set_xticks(range(len(C)))
    ax.set_xticklabels([c["county"].split(" County")[0] for c in C],
                       fontsize=11)
    ax.set_ylim(0, 1.0)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.set_ylabel("off-season peak NDVI", fontsize=10)
    if not BARE:
        ax.set_title("...because the distributions sit in different places",
                 color=INK, fontsize=12.5, fontweight="bold", loc="left",
                 pad=10)
    if not BARE:
        fig.suptitle("Cover crop detection is a regional calibration problem",
                 x=.055, ha="left", y=1.045, fontsize=13.5, fontweight="bold",
                 color=INK)
    if not BARE:
        fig.text(.055, 1.0, "One threshold, three rotations. Each point is one "
             "field-winter where the question can be asked.", fontsize=10,
             color=INK2, ha="left", va="top")
    fig.tight_layout()
    fig.savefig(OUT / "A_cover_by_county.png", dpi=170, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print("\n  wrote A_cover_by_county.png")

    # -- fig B: coverage and independence -----------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    ax = axes[0]
    w = .36
    ax.bar(x - w / 2, t.preplant_coverage_pct, w, color=RAMP[2],
           label="pre-plant window", linewidth=0)
    ax.bar(x + w / 2, t.annual_coverage_pct, w, color=RAMP[0],
           label="calendar-year scores", linewidth=0)
    for i in range(len(t)):
        ax.text(i - w / 2, t.preplant_coverage_pct[i] + 1.5,
                "%.0f" % t.preplant_coverage_pct[i], ha="center", fontsize=10,
                color=INK2)
        ax.text(i + w / 2, t.annual_coverage_pct[i] + 1.5,
                "%.0f" % t.annual_coverage_pct[i], ha="center", fontsize=10,
                fontweight="bold", color=RAMP[0])
    ax.set_xticks(x)
    ax.set_xticklabels([c.split(" County")[0] for c in t.county], fontsize=11)
    ax.set_ylim(0, 112)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=10, loc="lower right")
    ax.set_ylabel("% of field-years that get a value", fontsize=10)
    if not BARE:
        ax.set_title("Coverage", color=INK, fontsize=12.5, fontweight="bold",
                 loc="left", pad=10)

    ax = axes[1]
    for i, s in enumerate(["preplant", "worst", "residue"]):
        ax.plot(x, t["%s_r_green" % s], "o-",
                color=[RAMP[2], RAMP[1], ORANGE][i], lw=2.4, ms=9,
                label=s, zorder=3 + i)
    ax.set_xticks(x)
    ax.set_xticklabels([c.split(" County")[0] for c in t.county], fontsize=11)
    ax.set_ylim(0, 1.0)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=10)
    ax.set_ylabel("|r| with off-season peak NDVI", fontsize=10)
    if not BARE:
        ax.set_title("Independence from greenness (lower is better)", color=INK,
                 fontsize=12.5, fontweight="bold", loc="left", pad=10)
    if not BARE:
        fig.suptitle("What holds across all three counties",
                 x=.055, ha="left", y=1.045, fontsize=13.5, fontweight="bold",
                 color=INK)
    if not BARE:
        fig.text(.055, 1.0, "The calendar-year scores always cover more "
             "field-years, and of these three, annual residue is always the "
             "least dependent on winter greenness. In Champaign the annual "
             "mean and exposure days are lower still.", fontsize=10,
             color=INK2, ha="left", va="top")
    fig.tight_layout()
    fig.savefig(OUT / "B_coverage_independence.png", dpi=170,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  wrote B_coverage_independence.png")
    print("\nwrote compare_counties.csv to %s" % OUT)


if __name__ == "__main__":
    main()
