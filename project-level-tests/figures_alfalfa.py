#!/usr/bin/env python3
"""Figures for the New Mexico alfalfa cutting-detection case study.

    python project-level-tests/figures_alfalfa.py

Reads the report pack and the cuttings detected by detect_alfalfa_cuttings.py,
and writes six PNGs to alfalfa-nm/figures/.

Palette is the one already validated for this repository in figures_flash.py,
against the dataviz skill's six checks -- reused rather than re-chosen, so the
two case studies read as one body of work:

  ordinal   #10427C / #2f74c4 / #85b6ef   dL >= 0.06 each step, lightest 2.11:1
  binary    #165bac / #F46C09             CVD dE 27.4, normal dE 38.6, both >= 3:1

Orange is reserved throughout for one meaning: a cutting. Blue is the NDVI
series itself. Nothing else is coloured, because on these charts every other
distinction is carried by position.
"""
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parent / "alfalfa-nm"
PACK = PROJ / "pack"

# Two renderings of the same six charts. The titled set in figures/ stands on
# its own -- in a README, an email, a different document. The bare set in
# figures/deck/ drops the chart title and subtitle because the slide around
# it already carries them, and on a 7.5in page that duplicated heading is not
# just redundant: it pushed the cutting calendar's last line under the brand
# bar and cropped the 2026 axis off the bottom of the five-panel chart.
BARE = "--bare" in sys.argv
FIG = PROJ / "figures" / "deck" if BARE else PROJ / "figures"
FIG.mkdir(parents=True, exist_ok=True)

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


def finish(ax, title=None, sub=None, ylab=None, xlab=None):
    if BARE:
        title = sub = None
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
    # Retry: this repository lives under Documents, where the indexer or
    # OneDrive intermittently holds a just-written PNG open and the next
    # write fails with EINVAL. A rerun used to "fix" it by failing on a
    # different figure instead.
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


# ---------------------------------------------------------------- load -----
s = pd.read_csv(PACK / "series" / "ndvi-by-date.csv", parse_dates=["date"])
s = s.sort_values("date").reset_index(drop=True)
s["year"] = s.date.dt.year
cut = pd.read_csv(PROJ / "cuttings.csv",
                  parse_dates=["last_standing", "first_cut_obs"])
summ = pd.read_csv(PROJ / "cutting_summary.csv")
sm = pd.read_csv(PACK / "tables" / "season-markers.csv")
ALFA = [2022, 2023, 2024, 2025]


def doy(d):
    """Day of year as a 2001 date, so every year plots on one axis."""
    return pd.Timestamp(2001, 1, 1) + pd.to_timedelta(d.dt.dayofyear - 1, "D")


# -- 1 ------------------------------------------------- the sawtooth, 2023 --
y = s[s.year == 2023]
c = cut[cut.year == 2023]
fig, ax = plt.subplots(figsize=(12.4, 5.0))
ax.plot(y.date, y["mean"], "-", color=BLUE, lw=1.5, zorder=3)
ax.plot(y.date, y["mean"], "o", color=BLUE, ms=3.4, zorder=4)
for k, (_, e) in enumerate(c.iterrows(), 1):
    ax.annotate("", xy=(e.first_cut_obs, e.ndvi_after),
                xytext=(e.last_standing, e.ndvi_standing),
                arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2.4,
                                shrinkA=0, shrinkB=0, mutation_scale=17),
                zorder=6)
    ax.text(e.last_standing - pd.Timedelta(days=3), e.ndvi_standing + 0.035,
            "cutting %d" % k, color=ORANGE, fontsize=11, fontweight="bold",
            ha="right", va="bottom", zorder=7)
ax.set_ylim(0, 1.09)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
finish(ax, "One alfalfa field, 2023: four cuttings in one season",
       "Each arrow is a fall from full canopy to stubble between two clear "
       "satellite passes. 100 clear observations, one every three days.",
       "NDVI  (greenness)")
save(fig, "01_sawtooth_2023.png")

# -- 2 ------------------------------------------- every year, same pattern --
yrs = [2022, 2023, 2024, 2025, 2026]
# Wider and shorter for the deck: on a 7.5in slide this chart is
# height-constrained, and the standalone 12.4x8.2 shape then leaves
# it squeezed into the middle third of the page.
fig, axes = plt.subplots(len(yrs), 1, sharex=True,
                         figsize=(13.6, 6.1) if BARE else (12.4, 8.2))
for ax, yr in zip(axes, yrs):
    y = s[s.year == yr]
    c = cut[cut.year == yr]
    ax.plot(doy(y.date), y["mean"], "-", color=BLUE, lw=1.3, zorder=3)
    for _, e in c.iterrows():
        ax.axvline(doy(pd.Series([e.first_cut_obs])).iloc[0], color=ORANGE,
                   lw=2.0, alpha=.85 if not e.uncertain else .45,
                   ls="-" if not e.uncertain else (0, (3, 2)), zorder=2)
    n, nf = len(c), int(c.uncertain.sum())
    ax.text(.006, .86, "%d" % yr, transform=ax.transAxes, fontsize=13,
            fontweight="bold", color=INK)
    ax.text(.065, .865, "%d cutting%s%s" % (n, "" if n == 1 else "s",
            "  (%d flagged)" % nf if nf else ""), transform=ax.transAxes,
            fontsize=11, color=ORANGE, fontweight="bold")
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, .5, 1])
    if yr == 2026:
        ax.text(.985, .80, "part year, to 20 Sep", transform=ax.transAxes,
                fontsize=9.5, color=MUTED, ha="right")
axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
if not BARE:
    axes[0].set_title("The same rhythm, every year", color=INK, fontsize=13,
                      fontweight="bold", loc="left", pad=20)
    axes[0].text(0, 1.03, "NDVI through each year. Each orange line is a "
                 "detected cutting; dashed lines are flagged as uncertain.",
                 transform=axes[0].transAxes, color=INK2, fontsize=10,
                 va="bottom")
fig.supylabel("NDVI", fontsize=10, color=INK2, x=.025)
fig.tight_layout()
save(fig, "02_all_years.png")

# -- 3 -------------------------------------------- wheat against alfalfa ---
fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.5), sharey=True)
for ax, (yr, lab) in zip(axes, [(2021, "Winter wheat, 2021"),
                                (2023, "Alfalfa, 2023")]):
    y = s[s.year == yr]
    c = cut[cut.year == yr]
    ax.plot(doy(y.date), y["mean"], "-", color=BLUE, lw=1.6, zorder=3)
    ax.plot(doy(y.date), y["mean"], "o", color=BLUE, ms=2.8, zorder=4)
    for _, e in c.iterrows():
        ax.axvline(doy(pd.Series([e.first_cut_obs])).iloc[0], color=ORANGE,
                   lw=2.2, zorder=2)
    ax.set_ylim(0, 1.12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.set_title(lab, color=INK, fontsize=12, fontweight="bold", loc="left",
                 pad=8)
    ax.text(.03, .055, "%d biomass removal%s detected"
            % (len(c), "" if len(c) == 1 else "s"), transform=ax.transAxes,
            fontsize=11, color=ORANGE, fontweight="bold")
    ax.tick_params(length=0)
axes[0].set_ylabel("NDVI", fontsize=10)
fig.tight_layout(rect=(0, 0, 1, 1 if BARE else 0.86))
if not BARE:
    fig.suptitle("The same field, the same method, two different crops",
                 color=INK, fontsize=13, fontweight="bold", x=.065,
                 ha="left", y=.99)
    fig.text(.065, .925, "An annual grain is cut once. A perennial forage is "
             "cut again and again. Nothing about the method changed between "
             "these two panels.", color=INK2, fontsize=10, ha="left",
             va="top")
save(fig, "03_wheat_vs_alfalfa.png")

# -- 4 ----------------------------------------------- the cutting calendar -
fig, ax = plt.subplots(figsize=(12.4, 4.3))
yrs = [2022, 2023, 2024, 2025, 2026]
for row, yr in enumerate(yrs):
    c = cut[cut.year == yr].sort_values("first_cut_obs")
    xs = [doy(pd.Series([d])).iloc[0] for d in c.first_cut_obs]
    ax.plot([pd.Timestamp(2001, 1, 1), pd.Timestamp(2001, 12, 31)],
            [row, row], "-", color=GRID, lw=1.3, zorder=1)
    if len(xs) > 1:
        ax.plot(xs, [row] * len(xs), "-", color=ORANGE, lw=1.4, alpha=.45,
                zorder=2)
        for a, b in zip(xs[:-1], xs[1:]):
            ax.text(a + (b - a) / 2, row + .20, "%d d" % (b - a).days,
                    ha="center", va="bottom", fontsize=9, color=MUTED)
    for x, (_, e) in zip(xs, c.iterrows()):
        ax.plot(x, row, "o", ms=12, zorder=4,
                mfc="white" if e.uncertain else ORANGE,
                mec=ORANGE, mew=2.2)
    ax.text(pd.Timestamp(2001, 1, 2), row + .28, "%d" % yr, fontsize=11.5,
            fontweight="bold", color=INK, va="bottom")
ax.set_yticks([])
ax.set_ylim(-.6, len(yrs) - .35)
ax.invert_yaxis()
ax.set_xlim(pd.Timestamp(2001, 1, 1), pd.Timestamp(2001, 12, 31))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.grid(axis="y", visible=False)
ax.plot([], [], "o", ms=10, mfc=ORANGE, mec=ORANGE, label="cutting")
ax.plot([], [], "o", ms=10, mfc="white", mec=ORANGE, mew=2,
        label="flagged: after 1 Oct, a freeze would look the same")
ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(.5, -.30),
          ncol=2, fontsize=10)
finish(ax, "A cutting calendar built from satellite imagery alone",
       "Every detected cutting, 2022 to 2026, with the gap between them. "
       "2026 runs to 20 September only.")
save(fig, "04_cutting_calendar.png")

# -- 5 ------------------------------------------------- regrowth, overlaid -
fig, ax = plt.subplots(figsize=(8.4, 4.8))
SPAN = 35
tracks, recov = [], []
alfa = cut[cut.crop == "Alfalfa"].sort_values("first_cut_obs")
for _, e in alfa.iterrows():
    # Stop at the NEXT cutting. Without this the tail of each track is the
    # following cutting's collapse, and the median turns down at day 40 --
    # which would read as the stand dying back rather than being mown again.
    nxt = alfa[alfa.first_cut_obs > e.first_cut_obs].first_cut_obs
    end = min(e.first_cut_obs + pd.Timedelta(days=SPAN),
              (nxt.iloc[0] - pd.Timedelta(days=1)) if len(nxt)
              else e.first_cut_obs + pd.Timedelta(days=SPAN))
    w = s[(s.date >= e.first_cut_obs) & (s.date <= end)]
    if len(w) < 4:
        continue
    d = (w.date - e.first_cut_obs).dt.days.to_numpy()
    ax.plot(d, w["mean"].to_numpy(), "-", color=RAMP[2], lw=1.3, alpha=.85,
            zorder=2)
    tracks.append(pd.Series(w["mean"].to_numpy(), index=d))
    hit = w[w["mean"] >= 0.80]
    if len(hit):
        recov.append((hit.date.iloc[0] - e.first_cut_obs).days)
grid = np.arange(0, SPAN + 1)
med = pd.concat([t.reindex(grid).interpolate(limit_area="inside")
                 for t in tracks], axis=1).median(axis=1)
ax.plot(grid, med, "-", color=RAMP[0], lw=3.2, zorder=5, label="median")
ax.axhline(0.80, color=MUTED, lw=1.1, ls=(0, (4, 3)), zorder=1)
ax.text(.4, .815, "full canopy", ha="left", va="bottom", fontsize=9.5,
        color=MUTED)
mr = int(np.median(recov))
ax.plot([mr, mr], [0, 0.80], color=ORANGE, lw=2.0, ls=(0, (3, 2)), zorder=4)
ax.text(mr + 1, .14, "median %d days\nback to full canopy" % mr, fontsize=10.5,
        color=ORANGE, fontweight="bold", va="bottom")
ax.set_ylim(0, 1.05)
ax.set_xlim(0, SPAN)
finish(ax, "How fast the stand comes back",
       "Every cutting aligned at day zero, and stopped at the next one. "
       "%d of %d cuttings, 2022 to 2026." 
       % (len(tracks), int((cut.crop == "Alfalfa").sum())),
       "NDVI", "days since the cutting")
save(fig, "05_regrowth.png")

# -- 6 ----------------------------------- what the annual-crop model sees ---
fig, ax = plt.subplots(figsize=(12.4, 4.6))
yrs = [2022, 2023, 2024, 2025, 2026]
for row, yr in enumerate(yrs):
    r = sm[sm.year == yr].iloc[0]
    p = doy(pd.Series([pd.to_datetime(r.planting_est)])).iloc[0]
    h = doy(pd.Series([pd.to_datetime(r.harvest_est)])).iloc[0]
    ax.plot([p, h], [row, row], "-", color=RAMP[1], lw=11, alpha=.40,
            solid_capstyle="butt", zorder=2)
    ax.text(p - pd.Timedelta(days=4), row, "%d d" % r.season_days, ha="right",
            va="center", fontsize=10, color=RAMP[0], fontweight="bold")
    ax.plot(h, row, "v", ms=11, color=RAMP[0], zorder=5)
    c = cut[cut.year == yr]
    for _, e in c.iterrows():
        ax.plot(doy(pd.Series([e.first_cut_obs])).iloc[0], row, "o", ms=10,
                mfc=ORANGE, mec=ORANGE, zorder=4)
    ax.text(pd.Timestamp(2001, 1, 2), row + .30, "%d" % yr, fontsize=11.5,
            fontweight="bold", color=INK, va="bottom")
ax.set_yticks([])
ax.set_ylim(-.62, len(yrs) - .30)
ax.invert_yaxis()
ax.set_xlim(pd.Timestamp(2001, 1, 1), pd.Timestamp(2001, 12, 31))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.grid(axis="y", visible=False)
ax.plot([], [], "v", ms=10, color=RAMP[0], label='the pipeline\'s one "harvest"')
ax.plot([], [], "-", color=RAMP[1], lw=9, alpha=.4, label="its single season")
ax.plot([], [], "o", ms=9, color=ORANGE, label="cuttings actually detected")
ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(.5, -.30),
          ncol=3, fontsize=10)
finish(ax, "What an annual-crop model makes of a perennial",
       "The pipeline reports one planting and one harvest per year. On "
       "alfalfa it lands on a different cutting each time, and the season "
       "length swings from 63 to 264 days.")
save(fig, "06_pipeline_vs_cuttings.png")

print("\nwrote %d figures to %s" % (len(list(FIG.glob('*.png'))), FIG))
