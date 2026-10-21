#!/usr/bin/env python3
"""Benchmark a focus field against its cohort.

    python project-level-tests/analyse_cohort.py <project-dir>

Reads what run_cohort.py wrote and answers one question: on soil armor and
on off-season cover, does the focus field sit with its neighbors, above
them, or below?

The complication this county forces, and the reason the script is not just
a percentile:

  Sumner County is winter wheat country. Over half the cohort grows winter
  wheat or a wheat/soybean double crop. The pre-planting armor window runs
  from last harvest to this planting, so on a wheat field that window
  contains a LIVING CASH CROP, and armor comes back near 1 with f_pv high.
  The focus field reads 0.884 armor in 2024 with 71% living cover -- that
  is standing wheat, not conservation.

  Ranking raw armor across this cohort therefore sorts fields by cropping
  system, not by soil management, and would hand a "best armored" rosette
  to whoever grows the most wheat. Every comparison below is made within
  stratum: winter-crop years against winter-crop years, summer-only years
  against summer-only years.

The same applies to cover cropping. The pipeline already refuses to call a
winter cash crop a cover crop, which is correct, but it means a wheat field
is not scored either way. Cover-crop prevalence is reported over the years
where the question can actually be asked.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
pd.set_option("display.width", 200)

WINTER_CROPS = ("Winter Wheat", "Dbl Crop WinWht/Soybeans",
                "Dbl Crop WinWht/Sorghum", "Dbl Crop WinWht/Corn",
                "Rye", "Triticale", "Barley", "Oats", "Canola",
                "Dbl Crop WinWht/Cotton")


MIN_STRATUM_N = 10     # below this a stratum is a curiosity, not a comparison


def pct_rank(value, pool):
    """Share of the pool at or below `value`, as a percentile."""
    pool = np.asarray([p for p in pool if pd.notna(p)], dtype=float)
    if not len(pool) or pd.isna(value):
        return np.nan
    return round(100.0 * (pool <= value).mean(), 1)


def tie_frac(value, pool):
    """Share of the pool holding exactly this value.

    A percentile is meaningless when most of the cohort is tied with the
    field being ranked. Champaign County reports 82nd percentile for a focus
    field with zero positive winters, because 41 of its 50 neighbours also
    have zero: the rank is an artifact of counting ties as "at or below".
    """
    pool = np.asarray([p for p in pool if pd.notna(p)], dtype=float)
    if not len(pool) or pd.isna(value):
        return np.nan
    return round(100.0 * np.isclose(pool, value).mean(), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", help="project directory, e.g. champaign-il")
    a_ = ap.parse_args()
    PROJ = HERE / a_.proj

    armor = pd.read_csv(PROJ / "armor.csv")
    cover = pd.read_csv(PROJ / "covercrop.csv")
    hist = pd.read_csv(PROJ / "history.csv")
    fields = pd.read_csv(PROJ / "fields.csv")
    status = pd.read_csv(PROJ / "status.csv")
    meta = json.loads((PROJ / "cohort_meta.json").read_text())

    ok = status[status.status == "ok"].fid.tolist()
    armor = armor[armor.fid.isin(ok)].copy()
    cover = cover[cover.fid.isin(ok)].copy()
    hist = hist[hist.fid.isin(ok)].copy()
    n_fail = int((status.status != "ok").sum())

    print("=" * 76)
    print("%s -- hyper-local benchmark" % meta.get("county", a_.proj).upper())
    print("=" * 76)
    print("cohort radius   : %.1f km around the focus field" % (meta["radius_m"] / 1000))
    print("fields analyzed : %d of %d  (%d failed)"
          % (len(ok), len(status), n_fail))
    print("boundaries      : %s" % meta["source"])

    # ---- stratum: did CDL record a winter crop for that field-year? --------
    hist["winter_crop"] = hist.crop.isin(WINTER_CROPS)
    strat = hist.set_index(["fid", "year"]).winter_crop
    armor["winter_crop"] = [strat.get((f, y), np.nan)
                            for f, y in zip(armor.fid, armor.year)]
    armor["crop"] = [hist.set_index(["fid", "year"]).crop.get((f, y), "")
                     for f, y in zip(armor.fid, armor.year)]
    a = armor[armor.armor.notna()].copy()
    print("armor readings  : %d field-years with a value, of %d attempted"
          % (len(a), len(armor)))

    # CDL does not publish the current year, so 2026 has no crop and cannot be
    # put in a stratum. Dropping it is not optional: NaN is truthy, so an
    # unstratified row was being labelled "winter crop" and then matched
    # against zero peers, which read as a confident percentile of nothing.
    no_cdl = a.winter_crop.isna()
    if no_cdl.any():
        print("                  %d field-year(s) dropped from the stratified "
              "comparison:\n                  no CDL published yet for %s"
              % (int(no_cdl.sum()),
                 ", ".join(str(y) for y in sorted(a[no_cdl].year.unique()))))
        a = a[~no_cdl].copy()
    a["winter_crop"] = a.winter_crop.astype(bool)

    # ---- the confound, stated with numbers ---------------------------------
    print()
    print("-" * 76)
    print("DOES RAW ARMOR RANK THE CROPPING SYSTEM HERE?")
    print("-" * 76)
    g = a.groupby(a.winter_crop == True)                    # noqa: E712
    for key, sub in g:
        print("  %-28s n=%3d  median armor %.3f  median living cover %.3f"
              % ("winter crop in the window" if key else "summer-only rotation",
                 len(sub), sub.armor.median(), sub.f_pv.median()))
    w = a[a.winter_crop == True]                            # noqa: E712
    s = a[a.winter_crop == False]                           # noqa: E712
    if len(w) >= MIN_STRATUM_N and len(s) >= MIN_STRATUM_N:
        print("  gap between strata          : %.3f armor"
              % (w.armor.median() - s.armor.median()))
    else:
        thin = "winter-crop" if len(w) < len(s) else "summer-only"
        print("  NO STRATUM GAP REPORTED: the %s stratum has %d field-year(s),"
              % (thin, min(len(w), len(s))))
        print("  under the %d needed. This county grows essentially one"
              % MIN_STRATUM_N)
        print("  cropping system, so the confound that forces stratification")
        print("  elsewhere does not arise here -- and a gap computed from a")
        print("  handful of rows would be noise presented as a finding.")

    # ---- focus vs cohort, within stratum -----------------------------------
    print()
    print("-" * 76)
    print("SOIL ARMOR: FOCUS vs COHORT")
    print("-" * 76)
    rows = []
    for _, r in a[a.fid == "focus"].sort_values("year").iterrows():
        peers = a[(a.fid != "focus") & (a.year == r.year)
                  & (a.winter_crop == r.winter_crop)]
        rows.append({
            "year": int(r.year), "crop": r.crop,
            "stratum": "winter crop" if r.winter_crop else "summer only",
            "focus_armor": round(r.armor, 3),
            "peers_n": len(peers),
            "peer_median": round(peers.armor.median(), 3) if len(peers) else np.nan,
            "percentile": pct_rank(r.armor, peers.armor),
            "window_source": r.window_source, "n_obs": int(r.n_obs),
        })
    fa = pd.DataFrame(rows)
    print(fa.to_string(index=False))
    if len(fa):
        print()
        print("  focus mean percentile within stratum: %.0f"
              % fa.percentile.mean())

    # ---- cover crop --------------------------------------------------------
    print()
    print("-" * 76)
    print("OFF-SEASON COVER: FOCUS vs COHORT")
    print("-" * 76)
    ASKABLE = ("likely cover crop", "possible cover crop",
               "no cover crop detected",
               "green cover -- cover crop or small grain")
    cover["askable"] = cover.verdict.isin(ASKABLE)
    cover["positive"] = cover.verdict.isin(
        ("likely cover crop", "possible cover crop",
         "green cover -- cover crop or small grain"))
    print("verdict mix across the whole cohort:")
    print(cover.verdict.value_counts().to_string())
    ask = cover[cover.askable]
    print()
    print("  winters where the question can be asked : %d of %d (%.0f%%)"
          % (len(ask), len(cover), 100 * len(ask) / max(len(cover), 1)))
    print("  the rest are winter cash crops, which the pipeline correctly")
    print("  declines to score either way.")

    per = (ask.groupby("fid")
              .agg(askable=("positive", "size"), positive=("positive", "sum")))
    per["rate"] = per.positive / per.askable
    if "focus" in per.index:
        f = per.loc["focus"]
        peers = per.drop(index="focus")
        print()
        print("  focus  : %d of %d askable winters show off-season green"
              % (f.positive, f.askable))
        print("  cohort : median %.0f%% of askable winters, n=%d fields"
              % (100 * peers.rate.median(), len(peers)))
        pc, tf = pct_rank(f.rate, peers.rate), tie_frac(f.rate, peers.rate)
        print("  focus percentile : %.0f" % pc)
        if tf >= 40:
            print("  ...but %.0f%% of the cohort holds exactly the same value,"
                  % tf)
            print("  so that percentile ranks ties, not performance. Use the")
            print("  continuous off-season measure below instead.")
    print()
    print("  fields with at least one positive winter: %d of %d (%.0f%%)"
          % (int((per.positive > 0).sum()), len(per),
             100 * (per.positive > 0).mean()))

    # ---- the trend line ----------------------------------------------------
    print()
    print("-" * 76)
    print("THE TREND: ARMOR AGAINST OFF-SEASON GREEN")
    print("-" * 76)
    wint = cover.copy()
    wint["year"] = wint.winter.str[:4].astype(int) + 1
    key = wint.set_index(["fid", "year"]).max_ndvi
    a["winter_max_ndvi"] = [key.get((f, y), np.nan)
                            for f, y in zip(a.fid, a.year)]
    t = a[a.winter_max_ndvi.notna()].copy()
    if len(t) > 10:
        for label, sub in (("all field-years", t),
                           ("summer-only rotations", t[t.winter_crop == False])):  # noqa: E712
            if len(sub) < 10:
                continue
            b, c = np.polyfit(sub.winter_max_ndvi, sub.armor, 1)
            r = np.corrcoef(sub.winter_max_ndvi, sub.armor)[0, 1]
            print("  %-24s n=%3d  armor = %.3f x winter_ndvi + %.3f   r=%.2f"
                  % (label, len(sub), b, c, r))
        ff = t[t.fid == "focus"]
        if len(ff):
            sub = t[t.fid != "focus"]
            b, c = np.polyfit(sub.winter_max_ndvi, sub.armor, 1)
            ff = ff.assign(expected=(b * ff.winter_max_ndvi + c))
            ff = ff.assign(residual=ff.armor - ff.expected)
            print()
            print("  focus field against the cohort's own line:")
            print(ff[["year", "crop", "winter_max_ndvi", "armor", "expected",
                      "residual"]].round(3).to_string(index=False))
            print("  mean residual: %+.3f  (%s)"
                  % (ff.residual.mean(),
                     "above the line" if ff.residual.mean() > 0
                     else "below the line"))

    # ---- write -------------------------------------------------------------
    a.to_csv(PROJ / "armor_scored.csv", index=False)
    fa.to_csv(PROJ / "focus_vs_cohort_armor.csv", index=False)
    per.reset_index().to_csv(PROJ / "cover_by_field.csv", index=False)
    print()
    print("wrote armor_scored.csv, focus_vs_cohort_armor.csv, cover_by_field.csv")


if __name__ == "__main__":
    main()
