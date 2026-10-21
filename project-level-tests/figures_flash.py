#!/usr/bin/env python3
"""Figures for the Illinois (FLASH) case study report.

Palette follows the dataviz skill: a validated 3-step ordinal ramp in Field to
Market's Deep Current for anything with an order, and a validated two-colour
pair for the binary splits. Both were checked with the skill's six checks
(ported to Python -- node is not installed here) rather than eyeballed:

  ordinal   #10427C / #2f74c4 / #85b6ef   dL >= 0.06 each step, lightest 2.11:1
  binary    #165bac / #F46C09             CVD dE 27.4, normal dE 38.6, both >= 3:1
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.stdout.reconfigure(encoding="utf-8")

from fieldrs import analyze_field  # noqa: E402

PROJ = Path(__file__).resolve().parent / "project-FLASH"
FIG = PROJ / "figures"
FIG.mkdir(exist_ok=True)

INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
RAMP = ["#10427C", "#2f74c4", "#85b6ef"]
BLUE, ORANGE = "#165bac", "#F46C09"
GRID = "#e6e6e6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
})


def finish(ax, title=None, sub=None, ylab=None, xlab=None):
    if title:
        ax.set_title(title, color=INK, fontsize=13, fontweight="bold",
                     loc="left", pad=18 if sub else 10)
    if sub:
        ax.text(0, 1.015, sub, transform=ax.transAxes, color=INK2, fontsize=10,
                va="bottom")
    ax.set_ylabel(ylab or "", fontsize=10)
    ax.set_xlabel(xlab or "", fontsize=10)
    ax.tick_params(length=0)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  wrote", name)


# ---------------------------------------------------------------- load ------
rs = pd.read_csv(PROJ / "rs_covercrop.csv")
runs = pd.read_csv(PROJ / "rs_fields.csv")
fields = pd.read_csv(PROJ / "fields.csv")
LOOSE = ["likely cover crop", "possible cover crop",
         "green cover -- cover crop or small grain"]
rs["detected"] = rs.verdict.isin(LOOSE)
rs["strong"] = rs.verdict == "likely cover crop"

print("loading cached series for 98 fields ...")
series = []
for p in sorted((PROJ / "boundaries").glob("*.geojson")):
    r = analyze_field(p, years=(2022, 2026), only_cached=True)
    if r is None or r.series is None:
        continue
    s = r.series[["date", "mean"]].copy()
    s["key"] = p.stem
    series.append(s)
ts = pd.concat(series, ignore_index=True)
ts["date"] = pd.to_datetime(ts["date"])
ts["doy"] = ts.date.dt.dayofyear
ts["year"] = ts.date.dt.year
print("  %d observations across %d fields" % (len(ts), ts.key.nunique()))

# ------------------------------------------------- 1. field size -----------
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.hist(fields.acres, bins=np.arange(0, 320, 20), color=BLUE,
        edgecolor="white", linewidth=1.5)
ax.axvline(fields.acres.median(), color=ORANGE, lw=2)
ax.text(fields.acres.median() + 6, ax.get_ylim()[1] * 0.88,
        "median %.0f acres" % fields.acres.median(), color=ORANGE, fontsize=10,
        fontweight="bold")
finish(ax, "Field size", "98 boundaries, 6 to 291 acres", "fields", "acres")
save(fig, "01_field_size.png")

# ------------------------------------------------- 2. boundary quality -----
bv = runs.boundary_verdict.value_counts().reindex(
    ["single unit", "trim", "split"]).fillna(0)
fig, ax = plt.subplots(figsize=(7.2, 2.8))
left = 0
for (lab, v), col in zip(bv.items(), RAMP):
    ax.barh(0, v, left=left, color=col, height=0.55, edgecolor="white", lw=2)
    if v:
        ax.text(left + v / 2, 0, "%s\n%d" % (lab, v), ha="center", va="center",
                color="white" if col != RAMP[2] else INK, fontsize=10,
                fontweight="bold")
    left += v
ax.set_xlim(0, 98); ax.set_ylim(-0.5, 0.5); ax.set_yticks([])
ax.grid(False)
finish(ax, "Boundary quality",
       "29 of 98 boundaries are not a single management unit", None, "fields")
save(fig, "02_boundary_quality.png")

# ------------------------------------------------- 3. in-season curve ------
fig, ax = plt.subplots(figsize=(7.6, 4.0))
g = ts.groupby("doy")["mean"]
med, p25, p75 = g.median(), g.quantile(.25), g.quantile(.75)
idx = med.index
ax.fill_between(idx, p25, p75, color=BLUE, alpha=0.18, lw=0)
ax.plot(idx, med, color=BLUE, lw=2)
for m, d in [("Apr", 91), ("Jun", 152), ("Aug", 213), ("Oct", 274), ("Dec", 335)]:
    ax.axvline(d, color=GRID, lw=0.8, zorder=0)
ax.set_xticks([15, 74, 135, 196, 258, 319])
ax.set_xticklabels(["Jan", "Mar", "May", "Jul", "Sep", "Nov"])
ax.set_xlim(1, 366); ax.set_ylim(0, 1)
ax.text(200, 0.90, "cash crop canopy", color=BLUE, fontsize=10, fontweight="bold")
ax.annotate("off-season: where the cover crop\nquestion is decided",
            xy=(350, 0.25), xytext=(250, 0.12), color=ORANGE, fontsize=10,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.6))
finish(ax, "The season, all 98 fields pooled",
       "Median NDVI by day of year, 2022-2026; band is the 25th-75th percentile",
       "NDVI")
save(fig, "03_season_curve.png")

# ------------------------------------------------- 4. off-season curve -----
# Only dates where at least 20 of the 98 fields were clear. 17 of the 53
# dates in this window rest on fewer, and some on a single field -- a median
# drawn through those is a picture of one farm, not of the cohort.
MIN_FIELDS = 20
fig, ax = plt.subplots(figsize=(7.6, 4.0))
lab = rs[rs.winter == "2025-26"][["key", "detected"]]
off = ts[(ts.date >= "2025-10-15") & (ts.date <= "2026-05-10")].merge(
    lab, on="key", how="left")
depth = off.groupby("date").key.nunique()
keep = depth[depth >= MIN_FIELDS].index
thin = sorted(set(depth.index) - set(keep))
off = off[off.date.isin(keep)]

for flag, col, name in [(True, BLUE, "detector said cover crop (63)"),
                        (False, ORANGE, "detector said none (35)")]:
    gg = off[off.detected == flag].groupby("date")["mean"].median()
    ax.plot(gg.index, gg.values, "-o", color=col, lw=2.2, ms=4.5,
            mec="white", mew=1, label=name)

ax.axhline(0.30, color=INK2, lw=1.4, ls=(0, (5, 4)))
ax.text(pd.Timestamp("2025-10-18"), 0.315, "CC_GREEN_MIN = 0.30", color=INK2,
        fontsize=9.5, fontweight="bold")
ax.set_ylim(0, 0.52)
ax.tick_params(axis="x", rotation=25)
ax.legend(frameon=False, loc="lower right", fontsize=10)
finish(ax, "Winter 2025-26: every one of these fields was sown to a cover crop",
       "Cohort median; %d of 53 dates dropped as too thin" % len(thin),
       "NDVI")
save(fig, "04_offseason_curve.png")

# ------------------------------------------------- 5. peak NDVI dist -------
lab25 = rs[rs.winter == "2025-26"]
fig, ax = plt.subplots(figsize=(7.6, 3.8))
bins = np.arange(0.15, 0.80, 0.025)
ax.hist(lab25[lab25.max_ndvi < 0.30].max_ndvi, bins=bins, color=ORANGE,
        edgecolor="white", lw=1.2, label="below threshold -- missed (35)")
ax.hist(lab25[lab25.max_ndvi >= 0.30].max_ndvi, bins=bins, color=BLUE,
        edgecolor="white", lw=1.2, label="at or above threshold (63)")
ax.axvline(0.30, color=INK, lw=2)
ax.text(0.305, ax.get_ylim()[1] * 0.92, "0.30", color=INK, fontsize=10,
        fontweight="bold")
ax.legend(frameon=False, fontsize=10)
finish(ax, "Peak off-season NDVI, winter 2025-26",
       "All 98 fields were sown to a cover crop",
       "fields", "peak NDVI in the window")
save(fig, "05_peak_ndvi.png")

# ------------------------------------------------- 6. prevalence -----------
prev = rs.groupby("winter").agg(any_green=("detected", "mean"),
                                strong=("strong", "mean")).reset_index()
fig, ax = plt.subplots(figsize=(7.2, 3.8))
x = np.arange(len(prev))
ax.bar(x, prev.any_green, width=0.52, color=RAMP[2], edgecolor="white", lw=2,
       label="any green detected")
ax.bar(x, prev.strong, width=0.52, color=RAMP[0], edgecolor="white", lw=2,
       label="likely cover crop")
for i, (a, s) in enumerate(zip(prev.any_green, prev.strong)):
    ax.text(i, a + .02, "%.0f%%" % (100 * a), ha="center", color=INK,
            fontsize=10, fontweight="bold")
    ax.text(i, s / 2, "%.0f%%" % (100 * s), ha="center", va="center",
            color="white", fontsize=10, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(prev.winter)
ax.yaxis.set_major_formatter(PercentFormatter(1.0))
ax.set_ylim(0, 0.78)
ax.legend(frameon=False, fontsize=10, loc="upper left")
finish(ax, "What the satellite reports, four winters",
       "Only 2025-26 carries a grower label",
       "share of the 98 fields")
save(fig, "06_prevalence.png")

# ------------------------------------------------- 7. threshold curve ------
ths = np.arange(0.18, 0.46, 0.005)
sens = [(lab25.max_ndvi >= t).mean() for t in ths]
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.plot(ths, sens, color=BLUE, lw=2.4)
ax.axvline(0.30, color=ORANGE, lw=2)
ax.plot([0.30], [(lab25.max_ndvi >= 0.30).mean()], "o", ms=9, color=ORANGE,
        mec="white", mew=2, zorder=5)
ax.text(0.305, (lab25.max_ndvi >= .30).mean() + .05,
        "shipped 0.30\n64% caught", color=ORANGE, fontsize=10, fontweight="bold")
ax.plot([0.25], [(lab25.max_ndvi >= 0.25).mean()], "o", ms=8, color=INK2,
        mec="white", mew=2, zorder=5)
ax.text(0.205, (lab25.max_ndvi >= .25).mean() + .04, "0.25 -> 82%", color=INK2,
        fontsize=10, fontweight="bold")
ax.yaxis.set_major_formatter(PercentFormatter(1.0))
ax.set_ylim(0, 1.05)
finish(ax, "Sensitivity against the threshold",
       "98 known-positive fields",
       "cover crops caught", "peak-NDVI threshold")
save(fig, "07_threshold.png")

# ------------------------------------------------- 8. observations --------
m = lab25.merge(runs[["key", "boundary_verdict"]], on="key")
m["band"] = pd.cut(m.n_obs, [0, 10, 15, 20, 100],
                   labels=["<=10", "11-15", "16-20", ">20"])
rate = m.groupby("band", observed=True).detected.mean()
cnt = m.groupby("band", observed=True).size()
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.bar(range(len(rate)), rate, width=0.55, color=BLUE, edgecolor="white", lw=2)
for i, (v, n) in enumerate(zip(rate, cnt)):
    ax.text(i, v + .02, "%.0f%%" % (100 * v), ha="center", color=INK,
            fontsize=10, fontweight="bold")
    ax.text(i, 0.02, "n=%d" % n, ha="center", color="white", fontsize=9.5)
ax.set_xticks(range(len(rate))); ax.set_xticklabels(rate.index)
ax.yaxis.set_major_formatter(PercentFormatter(1.0)); ax.set_ylim(0, 1.0)
finish(ax, "Thin winters hide cover crops",
       "Detection rate by clear observations in the window",
       "detected", "clear observations, Oct to May")
save(fig, "08_observations.png")

# ------------------------------------------------- 9. boundary effect -----
rate2 = m.groupby("boundary_verdict").detected.mean().reindex(
    ["single unit", "trim", "split"])
cnt2 = m.groupby("boundary_verdict").size().reindex(
    ["single unit", "trim", "split"])
fig, ax = plt.subplots(figsize=(7.2, 3.6))
cols = [BLUE, ORANGE, ORANGE]
ax.bar(range(3), rate2, width=0.55, color=cols, edgecolor="white", lw=2)
for i, (v, n) in enumerate(zip(rate2, cnt2)):
    ax.text(i, v + .02, "%.0f%%" % (100 * v), ha="center", color=INK,
            fontsize=10, fontweight="bold")
    ax.text(i, 0.02, "n=%d" % n, ha="center", color="white", fontsize=9.5)
ax.set_xticks(range(3)); ax.set_xticklabels(rate2.index)
ax.yaxis.set_major_formatter(PercentFormatter(1.0)); ax.set_ylim(0, 1.0)
finish(ax, "Impure boundaries detect more, not less",
       "Boundaries flagged as more than one management unit",
       "detected")
save(fig, "09_boundary_effect.png")

# ------------------------------------------------- 10. example fields -----
# Labelled by what the detector concluded, not by what grew. The early-autumn
# values in both panels are the cash crop senescing, not the cover crop, and
# NDVI cannot tell a sown cover from volunteer regrowth.
ex = [("018af5ffc0ca", "detector: likely cover crop", BLUE),
      ("09d2bc91439b", "detector: none detected", ORANGE)]
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.6), sharey=True)
for axx, (k, cap, col) in zip(axes, ex):
    s = ts[(ts.key == k) & (ts.date >= "2025-09-15") & (ts.date <= "2026-06-01")]
    axx.plot(s.date, s["mean"], "-o", color=col, lw=2, ms=5, mec="white", mew=1.2)
    axx.axhline(0.30, color=INK2, lw=1.3, ls=(0, (5, 4)))
    axx.set_title(cap, color=col, fontsize=11, fontweight="bold", loc="left")
    axx.tick_params(axis="x", rotation=30, length=0)
    axx.tick_params(axis="y", length=0)
    axx.set_ylim(0, 0.75)
axes[0].set_ylabel("NDVI", fontsize=10)
fig.text(0.005, 0.99, "Dashed line is CC_GREEN_MIN = 0.30; the high autumn "
         "values are the cash crop coming off.",
         color=INK2, fontsize=10.5, ha="left", va="top")
save(fig, "10_examples.png")

# ------------------------------- 11. every field, off-season 2025-26 -------
# One line per field rather than a cohort median. The median hides that the
# two groups overlap heavily and that the separation is a late, brief spring
# divergence rather than a whole-winter difference.
fig, ax = plt.subplots(figsize=(11.6, 4.6))
lab = rs[rs.winter == "2025-26"].set_index("key")
win = ts[(ts.date >= "2025-10-15") & (ts.date <= "2026-05-10")]
n_det = n_mis = 0
for k, g in win.groupby("key"):
    if k not in lab.index:
        continue
    g = g.sort_values("date")
    det = bool(lab.loc[k, "detected"])
    ax.plot(g.date, g["mean"], color=BLUE if det else ORANGE, lw=0.9,
            alpha=0.42, solid_capstyle="round", zorder=2 if det else 3)
    n_det += det
    n_mis += not det

# Medians on top, so the cohort shape is readable through the spaghetti.
for flag, col, name in [(True, BLUE, f"detected ({n_det} fields)"),
                        (False, ORANGE, f"not detected ({n_mis} fields)")]:
    sub = win[win.key.isin(lab.index[lab.detected == flag])]
    depth = sub.groupby("date").key.nunique()
    gg = sub[sub.date.isin(depth[depth >= 20].index)].groupby("date")["mean"].median()
    # Markers show which dates actually carried >=20 clear fields; the line
    # between two distant markers is bridging dropped dates, not data.
    ax.plot(gg.index, gg.values, "-o", color=col, lw=3.4, ms=5.5,
            mec="white", mew=1.4, zorder=5,
            path_effects=[pe.Stroke(linewidth=6, foreground="white"), pe.Normal()],
            label=name)

ax.axhline(0.30, color=INK, lw=1.6, ls=(0, (5, 4)), zorder=4)
ax.text(pd.Timestamp("2026-01-05"), 0.325, "CC_GREEN_MIN = 0.30", color=INK,
        fontsize=10.5, fontweight="bold", zorder=6,
        bbox=dict(fc="white", ec="none", pad=2.5))
ax.set_ylim(0, 0.95)
ax.tick_params(axis="x", rotation=0)
ax.legend(frameon=False, loc="upper right", fontsize=11)
# No title inside the figure: the slide carries it, and repeating it wastes
# a line and widens the PNG under bbox_inches="tight".
finish(ax, None, None, "NDVI")
save(fig, "11_all_fields_offseason.png")

# ============================== soil armor ================================
# LIVING / RESIDUE validated with the skill's checks: chroma >= 0.10, CVD dE
# 10.4, normal dE 18.4, both >= 3:1 on white. Bare is the remainder drawn
# empty, the way plot_armor() does it, so no third colour is needed.
LIVING, RESIDUE = "#0d9a80", "#b5792e"

arm = pd.read_csv(PROJ / "rs_armor.csv")
cc25 = rs[rs.winter == "2025-26"][["key", "detected"]]

# ------------------------------------------- 12. readability by year -------
t = arm.groupby("year").agg(n=("armor", "size"), ok=("armor", "count"),
                            obs=("n_obs", "median"))
t["pct"] = t.ok / t.n
fig, ax = plt.subplots(figsize=(7.4, 3.7))
ax.bar(t.index, t.pct, width=0.6, color=BLUE, edgecolor="white", lw=2)
for y, r in t.iterrows():
    ax.text(y, r.pct + .02, "%.0f%%" % (100 * r.pct), ha="center", color=INK,
            fontsize=10.5, fontweight="bold")
    ax.text(y, 0.03, "%d obs" % r.obs, ha="center", color="white", fontsize=9.5)
ax.yaxis.set_major_formatter(PercentFormatter(1.0))
ax.set_ylim(0, 1.12)
ax.set_xticks(list(t.index))
finish(ax, "Armor cannot always be read",
       "Share of the 98 fields with enough clear spring dates; median observations in white",
       "field-years with a reading")
save(fig, "12_armor_readable.png")

# ------------------------------- 13. armor against the winter verdict ------
m = arm[arm.year == 2026].merge(cc25, on="key")
m = m[m.armor.notna()]
fig, ax = plt.subplots(figsize=(7.4, 4.0))
for i, (flag, col, name) in enumerate([(False, ORANGE, "detector said\nno cover crop"),
                                       (True, BLUE, "detector said\ncover crop")]):
    v = m[m.detected == flag].armor.values
    x = np.random.default_rng(0).normal(i, 0.055, len(v))
    ax.plot(x, v, "o", ms=6, color=col, alpha=0.5, mec="white", mew=0.8)
    ax.plot([i - .22, i + .22], [np.median(v)] * 2, color=INK, lw=3, zorder=5)
    ax.text(i + .28, np.median(v), "%.3f" % np.median(v), color=INK,
            fontsize=11, fontweight="bold", va="center")
    ax.text(i, -0.06, "%s\n(n=%d)" % (name, len(v)), ha="center", va="top",
            color=col, fontsize=10.5, fontweight="bold")
ax.set_xlim(-0.5, 1.6); ax.set_xticks([])
ax.set_ylim(0, 1.0)
finish(ax, "Spring 2026 ground cover, split by the winter verdict",
       "Each dot is a field; bars are medians", "soil armor (1 - bare soil)")
save(fig, "13_armor_vs_verdict.png")

# ------------------------------------------- 14. where the cover is --------
# Segments carry their own names on the top bar -- direct labelling rather than
# a legend, which collided with the title at every position tried.
g = m.groupby("detected")[["f_pv", "f_npv", "f_bs"]].median()
fig, ax = plt.subplots(figsize=(8.6, 3.2))
for i, flag in [(1, True), (0, False)]:
    r = g.loc[flag]
    segs = [(r.f_pv, LIVING, "living", "white"),
            (r.f_npv, RESIDUE, "residue", "white"),
            (r.f_bs, "white", "bare", INK2)]
    left = 0.0
    for val, col, name, txt in segs:
        ax.barh(i, val, left=left, color=col, height=0.44,
                edgecolor="white" if col != "white" else "#cfcfcf",
                lw=2 if col != "white" else 1.4)
        # The name only fits on a wide segment; 0.11 with a word after it
        # overran its own bar and clipped against the axis.
        shown = ("%.2f %s" % (val, name)) if (i == 1 and val >= 0.20)             else ("%.2f" % val)
        if val >= 0.09:
            ax.text(left + val / 2, i, shown, ha="center", va="center",
                    color=txt, fontsize=10.5,
                    fontweight="bold" if col != "white" else "normal")
        else:
            # Too narrow to hold text; set it just outside, in its own colour.
            ax.text(left + val + 0.012, i, shown, ha="left", va="center",
                    color=col, fontsize=10.5, fontweight="bold")
        left += val
ax.set_yticks([0, 1])
ax.set_yticklabels(["detector said\nno cover crop", "detector said\ncover crop"],
                   fontsize=11)
ax.set_ylim(-0.5, 1.5)
ax.set_xlim(0, 1)
ax.grid(False)
# Slide carries the headline; figure keeps only the scope note.
finish(ax, None, "Median cover fractions, spring 2026", None,
       "fraction of the surface")
save(fig, "14_armor_fractions.png")

print("\nfigures in", FIG)
