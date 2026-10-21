#!/usr/bin/env python3
"""What changes when you benchmark a field locally instead of nationally.

    python project-level-tests/benchmark_scale.py

The member complaint this whole exercise came from is that a national or
state comparison is not a comparison. This puts a number on it, using the
only three counties we have:

  * where each county's TYPICAL field sits in the pooled distribution --
    if a county's median field is at the 20th percentile of the pool, then
    four out of five growers in that county are told they are below average
    for reasons that have nothing to do with how they farm;
  * how a focus field's standing moves between a local cohort and the
    pooled one;
  * how much of the total variation is between counties rather than
    between neighbouring fields.

Writes _across/benchmark_scale.csv and the figures the deck uses.
"""
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
OUT.mkdir(parents=True, exist_ok=True)
DIRS = ["champaign-il", "sumner-ks", "mitchell-ga"]
SCORES = ["preplant", "residue", "worst"]
LABEL = {"preplant": "pre-plant armor", "residue": "annual residue",
         "worst": "worst 10% of year"}

INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
BLUE, ORANGE = "#165bac", "#F46C09"
RAMP = ["#10427C", "#2f74c4", "#85b6ef"]
GRID = "#e6e6e6"
CCOL = {"Champaign": "#85b6ef", "Sumner": "#2f74c4", "Mitchell": "#10427C"}

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
})


def short(c):
    return c.split(" County")[0]


frames = []
for d in DIRS:
    meta = json.loads((HERE / d / "cohort_meta.json").read_text())
    a = pd.read_csv(HERE / d / "annual_armor_options.csv")
    a["county"] = short(meta.get("county", d))
    a["dir"] = d
    frames.append(a)
A = pd.concat(frames, ignore_index=True)

# field-level means, which is what a benchmark would actually compare
F = (A.groupby(["dir", "county", "fid"])[SCORES].mean().reset_index())
print("%d fields across %d counties" % (len(F), F.county.nunique()))

rows = []
for s in SCORES:
    pool = F[s].dropna()
    for cty, sub in F.groupby("county"):
        med = sub[s].median()
        rows.append({
            "score": s, "county": cty, "n": len(sub),
            "county_median": round(med, 3),
            "pooled_median": round(pool.median(), 3),
            "county_median_pctile_in_pool": round(100 * (pool <= med).mean(), 1),
            "share_below_pooled_median": round(
                100 * (sub[s] <= pool.median()).mean(), 1),
        })
T = pd.DataFrame(rows)
T.to_csv(OUT / "benchmark_scale.csv", index=False)

print()
print("=" * 92)
print("WHERE EACH COUNTY'S TYPICAL FIELD SITS IN A POOLED BENCHMARK")
print("=" * 92)
for s in SCORES:
    print("\n%s:" % LABEL[s])
    print(T[T.score == s][["county", "n", "county_median", "pooled_median",
                           "county_median_pctile_in_pool",
                           "share_below_pooled_median"]].to_string(index=False))

print()
print("=" * 92)
print("THE SAME FIELD, TWO BENCHMARKS")
print("=" * 92)
print("%-12s %-18s %8s %8s %8s" % ("county", "score", "local", "pooled", "move"))
mv = []
for d in DIRS:
    sub = F[F.dir == d]
    cty = sub.county.iloc[0]
    for s in SCORES:
        f = sub.loc[sub.fid == "focus", s]
        if not len(f) or pd.isna(f.iloc[0]):
            continue
        f = float(f.iloc[0])
        loc = 100 * (sub.loc[sub.fid != "focus", s] <= f).mean()
        poo = 100 * (F.loc[F.fid != "focus", s].dropna() <= f).mean()
        mv.append({"county": cty, "score": s, "local": round(loc),
                   "pooled": round(poo), "move": round(poo - loc)})
        print("%-12s %-18s %8.0f %8.0f %+8.0f"
              % (cty, LABEL[s], loc, poo, poo - loc))
M = pd.DataFrame(mv)
print("\nlargest move: %+d percentile points" % M.move.abs().max())

print()
print("=" * 92)
print("HOW MUCH OF THE VARIATION IS BETWEEN COUNTIES?")
print("=" * 92)
for s in SCORES:
    v = F.dropna(subset=[s])
    grand = v[s].var()
    within = v.groupby("county")[s].var().mean()
    print("  %-18s total variance %.4f  |  within-county %.4f  |  "
          "between-county share %.0f%%"
          % (LABEL[s], grand, within, 100 * (1 - within / grand)))

# ---------------------------------------------------------------- figure --
fig, axes = plt.subplots(1, len(SCORES), figsize=(13.0, 4.8), sharey=False)
for ax, s in zip(axes, SCORES):
    pool = F[s].dropna()
    pooled_med = pool.median()
    for i, cty in enumerate(["Champaign", "Sumner", "Mitchell"]):
        sub = F[F.county == cty][s].dropna()
        ax.scatter(np.full(len(sub), i) + (np.random.default_rng(5)
                   .random(len(sub)) - .5) * .55, sub, s=18,
                   color=CCOL[cty], alpha=.75, linewidths=0, zorder=2)
        m = sub.median()
        ax.plot([i - .33, i + .33], [m, m], "-", color=INK, lw=3, zorder=4)
    ax.axhline(pooled_med, color=ORANGE, lw=2.2, ls=(0, (5, 4)), zorder=5)
    ax.set_xticks(range(3))
    ax.set_xticklabels(["Champaign", "Sumner", "Mitchell"], fontsize=10.5)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.set_title(LABEL[s], color=INK, fontsize=12, fontweight="bold",
                 loc="left", pad=10)
    if s == SCORES[0]:
        ax.set_ylabel("field mean", fontsize=10)
axes[-1].text(2.42, pooled_med, "pooled\nmedian", color=ORANGE, fontsize=10,
              fontweight="bold", va="center", ha="left")
if not BARE:
    fig.suptitle("A pooled benchmark grades the county, not the farmer",
             x=.045, ha="left", y=1.05, fontsize=13.5, fontweight="bold",
             color=INK)
if not BARE:
    fig.text(.045, 1.005, "Every field in three counties. The dashed line is the "
         "median of all 203 fields -- what a 'national' benchmark would be "
         "if these three counties were the nation.", fontsize=10, color=INK2,
         ha="left", va="top")
fig.tight_layout()
fig.savefig(OUT / "C_pooled_vs_local.png", dpi=170, bbox_inches="tight",
            facecolor="white")
plt.close(fig)
print("\n  wrote C_pooled_vs_local.png")

# -- D: the same field, two benchmarks --------------------------------------
fig, ax = plt.subplots(figsize=(9.0, 5.2))
for _, r in M.iterrows():
    col = CCOL[r.county]
    ax.plot([0, 1], [r.local, r.pooled], "-", color=col, lw=2.4, alpha=.9,
            zorder=3, solid_capstyle="round")
    ax.plot(0, r.local, "o", ms=10, color=col, zorder=4)
    ax.plot(1, r.pooled, "o", ms=10, color=col, zorder=4)
# A legend, not inline labels: Sumner's and Mitchell's lines start 5
# percentile points apart and the two county names printed on top of
# each other.
for cty in ["Champaign", "Sumner", "Mitchell"]:
    ax.plot([], [], "o-", color=CCOL[cty], lw=2.4, ms=9, label=cty)
ax.legend(frameon=False, fontsize=11, loc="lower left",
          bbox_to_anchor=(.02, .02))
big = M.iloc[M.move.abs().argmax()]
ax.annotate("Champaign's field falls\n%d percentile points\nwithout moving an inch"
            % abs(big.move), xy=(.52, 58), xytext=(.52, 86), ha="center",
            va="top", fontsize=11.5, fontweight="bold", color=ORANGE,
            arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=1.8,
                            mutation_scale=16))
ax.axhline(50, color=MUTED, lw=1.2, ls=(0, (4, 4)), zorder=1)
ax.text(1.065, 53, "median", fontsize=10, color=MUTED, va="bottom")
ax.set_xticks([0, 1])
ax.set_xticklabels(["compared with\nits 50-100 neighbors",
                    "compared with\nall 203 fields"], fontsize=11.5)
ax.set_xlim(-.30, 1.18)
ax.set_ylim(0, 100)
ax.grid(axis="x", visible=False)
ax.tick_params(length=0)
ax.set_ylabel("percentile  (higher = better covered)", fontsize=10)
if not BARE:
    ax.set_title("The same field, two benchmarks, two different verdicts",
             color=INK, fontsize=13, fontweight="bold", loc="left", pad=20)
if not BARE:
    ax.text(0, 1.015, "Each line is one focus field on one score. Nothing about "
        "the field changed, only who it was compared with.",
        transform=ax.transAxes, color=INK2, fontsize=10, va="bottom")
fig.tight_layout()
fig.savefig(OUT / "D_same_field_two_benchmarks.png", dpi=170,
            bbox_inches="tight", facecolor="white")
plt.close(fig)
print("  wrote D_same_field_two_benchmarks.png")

# -- E: the three focus fields, each against its own neighborhood -----------
fig, ax = plt.subplots(figsize=(9.6, 4.4))
w = .26
xs = np.arange(3)
for k, s in enumerate(SCORES):
    vals = []
    for d in DIRS:
        sub = F[F.dir == d]
        v = float(sub.loc[sub.fid == "focus", s].iloc[0])
        vals.append(100 * (sub.loc[sub.fid != "focus", s] <= v).mean())
    ax.bar(xs + (k - 1) * w, vals, w, color=[RAMP[2], ORANGE, RAMP[0]][k],
           label=LABEL[s], linewidth=0)
    for i, v in enumerate(vals):
        ax.text(i + (k - 1) * w, v + 1.6, "%.0f" % v, ha="center",
                fontsize=9.5, color=INK2)
ax.axhline(50, color=MUTED, lw=1.3, ls=(0, (4, 4)), zorder=1)
ax.text(2.46, 53, "cohort median", fontsize=10, color=MUTED, ha="right")
ax.set_xticks(xs)
ax.set_xticklabels([F[F.dir == d].county.iloc[0] for d in DIRS], fontsize=11.5)
ax.set_ylim(0, 105)
ax.grid(axis="x", visible=False)
ax.tick_params(length=0)
ax.legend(frameon=False, fontsize=10, ncol=3, loc="upper center",
          bbox_to_anchor=(.5, 1.17))
ax.set_ylabel("percentile among its own neighbors", fontsize=10)
if not BARE:
    ax.set_title("Three focus fields, each judged against its own neighborhood",
             color=INK, fontsize=13, fontweight="bold", loc="left", pad=44)
fig.tight_layout()
fig.savefig(OUT / "E_focus_by_county.png", dpi=170, bbox_inches="tight",
            facecolor="white")
plt.close(fig)
print("  wrote E_focus_by_county.png")
print("  wrote benchmark_scale.csv")
