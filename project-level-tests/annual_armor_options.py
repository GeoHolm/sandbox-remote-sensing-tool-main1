#!/usr/bin/env python3
"""Five ways to score soil armor over a calendar year, tested side by side.

    python project-level-tests/annual_armor_options.py <project-dir>

The shipped score covers only the pre-planting window, which is why the
Sumner benchmark had to be stratified: on a winter wheat field that window
contains a living cash crop, so the number ranks cropping systems. A
calendar-year score could fix that, or could just annualize the same
problem. This runs five candidates over a cohort and asks which.

Everything reads from cache -- armor_series already spans 01-01 to 12-31,
so the per-date cover fractions for the whole year are already on disk from
the benchmark run. Nothing is re-downloaded.

THE CANDIDATES

  preplant    the shipped score. Time-weighted mean armor over the
              pre-planting window only. Included as the baseline.
  mean        time-weighted mean armor across the whole calendar year.
              The direct extension, and it reuses the trapezoidal average
              armor_summary already argues for: soil is exposed to erosion
              over time, so what matters is average cover through a period,
              not the middle value of however many scenes were clear.
  exposure    days in the year with armor below 0.50, time-weighted. Not
              an average at all -- a count of how long the ground was more
              bare than covered. Erosion is driven by when the soil is
              open, not by the annual mean.
  worst       the 10th percentile of armor through the year. A robust
              minimum: the worst the field got, without letting one bad
              scene decide it.
  nongrow     time-weighted mean armor outside the detected growing
              season, using the phenology planting and harvest dates.
              The conservation-relevant period, with the cash crop cut out
              of the measurement rather than left in it.
  residue     time-weighted mean of f_npv alone across the year -- crop
              residue on the surface, excluding living cover. Isolates
              "something was left on this field" from "something was
              growing on it".

HOW THEY ARE JUDGED

  coverage    field-years that get a value at all.
  crop bias   standardized gap between winter-crop years and summer-only
              years (Cohen's d). This is the failure mode of the shipped
              score, so a good annual score should show a SMALL one.
  vs green    |r| against off-season peak NDVI. The benchmark found the
              pre-plant score is largely a restatement of winter greenness
              (r = 0.91). Lower here means the score carries information
              that NDVI does not.
  stability   share of variance that sits between fields rather than
              within a field across years. A management signal should
              persist year to year; weather and crop choice should not.
              Higher is better, but see the caveat printed at the end.
  spread      interquartile range, in the score's own units. A score that
              cannot separate fields is useless however unbiased it is.

None of this says which score is CORRECT. There is no ground truth for
soil cover in this cohort, or anywhere else in this repository. It says
which candidates behave like a management signal and which behave like a
restatement of what crop was grown.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from fieldrs.aoi import load_field  # noqa: E402
from fieldrs.armor import armor_series  # noqa: E402

HERE = Path(__file__).resolve().parent
YEARS = (2022, 2026)
BARE_BELOW = 0.50        # "more bare than covered"
WORST_Q = 0.10           # robust minimum
MIN_OBS = 8              # a year needs this many clear dates to be scored

WINTER_CROPS = ("Winter Wheat", "Dbl Crop WinWht/Soybeans",
                "Dbl Crop WinWht/Sorghum", "Dbl Crop WinWht/Corn",
                "Rye", "Triticale", "Barley", "Oats", "Canola",
                "Dbl Crop WinWht/Cotton")


def tw_mean(dates, y):
    """Trapezoidal average over observation dates -- armor._time_weighted."""
    x = np.asarray(pd.DatetimeIndex(dates).map(pd.Timestamp.toordinal),
                   dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 2 or x.max() == x.min():
        return float(np.mean(y)) if len(y) else np.nan
    return float(np.trapezoid(y, x) / (x.max() - x.min()))


def tw_days_below(dates, y, thresh):
    """Days the series sits below `thresh`, by linear interpolation.

    Counting observations instead would make the answer depend on how the
    clear dates happened to fall, which is cloud, not cover.
    """
    x = np.asarray(pd.DatetimeIndex(dates).map(pd.Timestamp.toordinal),
                   dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 2:
        return np.nan
    below = (y < thresh).astype(float)
    # trapezoid of the indicator, scaled back to days over the spanned period
    return float(np.trapezoid(below, x))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", help="project directory, e.g. champaign-il")
    PROJ = HERE / ap.parse_args().proj

    hist = pd.read_csv(PROJ / "history.csv")
    hist["winter_crop"] = hist.crop.isin(WINTER_CROPS)
    crop_of = hist.set_index(["fid", "year"]).crop
    wint_of = hist.set_index(["fid", "year"]).winter_crop

    phen = pd.read_csv(PROJ / "phenology.csv",
                       parse_dates=["planting_est", "harvest_est"])
    phen_of = phen.set_index(["fid", "year"])

    cov = pd.read_csv(PROJ / "covercrop.csv")
    cov["year"] = cov.winter.str[:4].astype(int) + 1
    green_of = cov.set_index(["fid", "year"]).max_ndvi

    pre = pd.read_csv(PROJ / "armor.csv")
    pre_of = pre.set_index(["fid", "year"]).armor

    files = sorted((PROJ / "boundaries").glob("*.geojson"))
    rows, miss = [], 0
    t0 = time.time()
    for i, p in enumerate(files, 1):
        ts = armor_series(load_field(p), YEARS, only_cached=True)
        if ts is None:
            miss += 1
            continue
        ts["date"] = pd.to_datetime(ts["date"])
        wide = ts.pivot_table(index="date", columns="index", values="mean")
        if "f_bs" not in wide:
            miss += 1
            continue
        wide["armor"] = 1.0 - wide["f_bs"]
        for yr, w in wide.groupby(wide.index.year):
            w = w.dropna(subset=["armor"]).sort_index()
            if len(w) < MIN_OBS:
                continue
            d = w.index
            row = {
                "fid": p.stem, "year": int(yr), "n_obs": len(w),
                "crop": crop_of.get((p.stem, yr), ""),
                "winter_crop": wint_of.get((p.stem, yr), np.nan),
                "winter_max_ndvi": green_of.get((p.stem, yr), np.nan),
                "preplant": pre_of.get((p.stem, yr), np.nan),
                "mean": tw_mean(d, w.armor),
                "exposure": tw_days_below(d, w.armor, BARE_BELOW),
                "worst": float(np.quantile(w.armor, WORST_Q)),
                "residue": (tw_mean(d, w["f_npv"]) if "f_npv" in w else np.nan),
            }
            # non-growing-season: everything outside planting..harvest
            pl = hv = pd.NaT
            if (p.stem, yr) in phen_of.index:
                pr = phen_of.loc[(p.stem, yr)]
                pl, hv = pr.planting_est, pr.harvest_est
            if pd.notna(pl) and pd.notna(hv):
                off = w[(d < pl) | (d > hv)]
                row["nongrow"] = (tw_mean(off.index, off.armor)
                                  if len(off) >= 3 else np.nan)
            else:
                row["nongrow"] = np.nan
            rows.append(row)
        if i % 25 == 0:
            print("  %d/%d fields (%.0fs)" % (i, len(files), time.time() - t0),
                  flush=True)

    a = pd.DataFrame(rows)
    print("\n%d field-years from %d fields (%d cache misses)"
          % (len(a), a.fid.nunique(), miss))
    a.to_csv(PROJ / "annual_armor_options.csv", index=False)

    SCORES = ["preplant", "mean", "exposure", "worst", "nongrow", "residue"]
    poss = a.fid.nunique() * 5

    print()
    print("=" * 94)
    print("CANDIDATE SCORES, %d fields x %d years"
          % (a.fid.nunique(), a.year.nunique()))
    print("=" * 94)
    print("%-10s %9s %6s %6s %10s %9s %10s %9s  %s"
          % ("score", "coverage", "n_win", "n_sum", "crop bias", "vs green",
             "stability", "spread", "units"))
    print("-" * 104)
    out = []
    for s in SCORES:
        v = a[s]
        ok = v.notna()
        sub = a[ok & a.winter_crop.notna()]
        w = sub.loc[sub.winter_crop.astype(bool), s]
        m = sub.loc[~sub.winter_crop.astype(bool), s]
        sd = np.sqrt(((len(w) - 1) * w.var() + (len(m) - 1) * m.var())
                     / max(len(w) + len(m) - 2, 1))
        d = (w.mean() - m.mean()) / sd if sd > 0 else np.nan
        g = a[ok & a.winter_max_ndvi.notna()]
        r = (np.corrcoef(g[s], g.winter_max_ndvi)[0, 1]
             if len(g) > 10 else np.nan)
        # between-field share of variance
        grp = a[ok].groupby("fid")[s]
        between = grp.mean().var()
        within = grp.var().mean()
        icc = between / (between + within) if (between + within) > 0 else np.nan
        iqr = v.quantile(.75) - v.quantile(.25)
        out.append({"score": s, "n": int(ok.sum()), "d": d, "r": r,
                    "icc": icc, "iqr": iqr})
        print("%-10s %4d/%-4d %6d %6d %10.2f %9.2f %10.2f %9s  %s"
              % (s, ok.sum(), poss, len(w), len(m), d, r, icc,
                 "%.0f" % iqr if s == "exposure" else "%.3f" % iqr,
                 "days" if s == "exposure" else "armor 0-1"))

    print()
    print("crop bias = Cohen's d, winter-crop years minus summer-only. The")
    print("shipped pre-plant score is the thing to beat.")

    # ---- what the alternatives agree and disagree with --------------------
    print()
    print("=" * 94)
    print("HOW FAR EACH CANDIDATE MOVES THE ANSWER")
    print("=" * 94)
    base = a.dropna(subset=["preplant"])
    for s in SCORES[1:]:
        sub = base.dropna(subset=[s])
        if len(sub) < 20:
            continue
        r = np.corrcoef(sub.preplant, sub[s])[0, 1]
        print("  %-9s vs pre-plant: r = %+.2f  (n=%d)" % (s, r, len(sub)))

    # ---- where the focus field lands under each ---------------------------
    print()
    print("=" * 94)
    print("THE FOCUS FIELD UNDER EACH SCORE  (percentile among fields, "
          "field means)")
    print("=" * 94)
    for s in SCORES:
        m = a.dropna(subset=[s]).groupby("fid")[s].mean()
        if "focus" not in m.index or len(m) < 20:
            continue
        f = m.loc["focus"]
        peers = m.drop(index="focus")
        pct = 100 * (peers <= f).mean()
        # exposure is "more is worse", so flip it for a like-for-like read
        note = "  (more exposure = worse)" if s == "exposure" else ""
        print("  %-9s focus %8.3f   cohort median %8.3f   percentile %3.0f%s"
              % (s, f, peers.median(), pct, note))

    print()
    print("stability caveat: a score can look stable because it tracks a")
    print("field's permanent soil or slope rather than its management, and")
    print("nothing here separates those.")
    print()
    print("wrote annual_armor_options.csv")


if __name__ == "__main__":
    main()
