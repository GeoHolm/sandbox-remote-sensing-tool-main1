#!/usr/bin/env python3
"""Recompute every cohort statistic the cotton pitch deck quotes, from the
validation CSVs, and print claimed against recomputed.

    python validation/sweep_deck_cohorts.py

Nothing here reads the deck. The claims are transcribed by hand from the
rendered slides, so an error in the deck cannot propagate into its own check.
Run it after changing anything in validation/, or before sending the deck out.

Two reconstruction traps, both hit on the first pass and both recorded here so
the next person does not have to find them again:

  * The cover crop verdict stored in cover_scored.csv was produced at the old
    NDVI 0.35 threshold and carries extra rules (green days, winter cash crop).
    The deck quotes the refit 0.449 detector, so the check has to apply the
    threshold rather than read the verdict column.
  * Tillage has no stored prediction at all. The deck's 76.4% comes from an
    armor threshold of 0.4441. Searching for the *best* split finds 0.4369 at
    77.0%, which is a different and slightly better number -- not the claim.
"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 220)

V = "validation/"
truth = pd.read_csv(V + "truth.csv")
metrics = pd.read_csv(V + "metrics.csv")
cdl = pd.read_csv(V + "cdl_scored.csv")
cover = pd.read_csv(V + "cover_scored.csv")

d = truth.merge(metrics, on="key", how="left")
cot = d[d.crop == "Cotton"].copy()

# The two constants the deck's classifier claims rest on.
CC_THRESHOLD = 0.449      # refit max-NDVI cut for cover crop, cotton
TILL_THRESHOLD = 0.4441   # armor cut behind the 76.4% tillage figure

rows = []


def chk(slide, what, claimed, actual, fmt="{:.3f}", note=""):
    """Record one claim. `claimed=None` computes a figure the deck does not
    quote, for context."""
    if claimed is None:
        ok = "--"
    elif isinstance(claimed, str) or isinstance(actual, str):
        ok = "OK" if str(claimed) == str(actual) else "MISMATCH"
    else:
        # A slide prints a rounded figure, so it is right when it rounds
        # right. Judge it at its own precision -- half a unit in the last
        # place the format shows -- rather than at some fixed tolerance,
        # which either lets 0.53-for-0.50 pass or fails 0.50-for-0.504.
        places = int(fmt.split(".")[1].split("f")[0])
        # The epsilon is not slack: medians of even-sized groups land on
        # exact ties like 0.3445, where the subtraction overshoots half a
        # unit by one float ulp and a correct rounding reads as wrong.
        ok = ("OK" if abs(claimed - actual) <= 0.5 * 10 ** -places + 1e-9
              else "MISMATCH")
    rows.append({
        "slide": slide, "claim": what,
        "deck": claimed if isinstance(claimed, str) else
                (fmt.format(claimed) if claimed is not None else "--"),
        "recomputed": actual if isinstance(actual, str) else fmt.format(actual),
        "verdict": ok, "note": note,
    })


# ------------------------------------------------------- slides 1 and 8 -----
chk(1, "cotton field-years", 183, len(cot), "{:.0f}")
chk(1, "survey years", "2018-2021", "%d-%d" % (cot.year.min(), cot.year.max()))
chk(8, "distinct cotton fields", 144, cot.field_id.nunique(), "{:.0f}")
chk(8, "distinct locations", 34, cot.Location.nunique(), "{:.0f}")
chk(8, "total cotton acres", 21129, cot.acres.sum(), "{:.0f}")
chk(8, "median field acres", 82, cot.acres.median(), "{:.0f}")
chk(8, "% irrigated", 78, 100 * (cot.irrigated == "Yes").mean(), "{:.0f}",
    "77.6 unrounded")

# ------------------------------------- slide 7: armor by reported residue ---
LAB = {"< 15%": "Conventional", "15-30%": "Reduced", "> 30%": "Conservation"}
for k, (cv, cn) in {"< 15%": (0.408, 48), "15-30%": (0.508, 9),
                    "> 30%": (0.594, 126)}.items():
    g = cot[cot.till == k]
    chk(7, "%s median armor" % LAB[k], cv, g.armor.median())
    chk(7, "%s n" % LAB[k], cn, len(g), "{:.0f}")

# --------------------------------------------------- slide 9: scorecard -----
crop_rows = cdl[cdl.crop == "Cotton"]
chk(9, "crop n", 183, len(crop_rows), "{:.0f}")
chk(9, "crop accuracy %", 85.2, 100 * crop_rows.agree.mean(), "{:.1f}")
chk(9, "crop hits", "156 of 183",
    "%d of %d" % (crop_rows.agree.sum(), len(crop_rows)))

cc = cover[(cover.crop == "Cotton") & (cover.verdict != "ERROR")].copy()
cc["pred"] = cc.max_ndvi >= CC_THRESHOLD
tp = int((cc.pred & cc.truth).sum())
fp = int((cc.pred & ~cc.truth).sum())
pos = int(cc.truth.sum())
chk(9, "cover n", 182, len(cc), "{:.0f}")
chk(9, "cover accuracy %", 75.3, 100 * (cc.pred == cc.truth).mean(), "{:.1f}")
chk(9, "cover recall", "111 of 114", "%d of %d" % (tp, pos))
chk(9, "cover false alarms", 42, fp, "{:.0f}")
chk(9, "cover crop catch rate %", 97, 100 * tp / pos, "{:.0f}")

til = cot[cot.till.isin(["< 15%", "> 30%"])].copy()
til["cons"] = til.till == "> 30%"
til["pred"] = til.armor >= TILL_THRESHOLD
chk(9, "tillage n", 174, len(til), "{:.0f}")
chk(9, "tillage accuracy %", 76.4, 100 * (til.pred == til.cons).mean(), "{:.1f}")
chk(9, "tillage recall", "105 of 126",
    "%d of %d" % (int((til.pred & til.cons).sum()), int(til.cons.sum())))
chk(9, "conservation catch rate %", 83,
    100 * (til.pred & til.cons).sum() / til.cons.sum(), "{:.0f}")
chk(9, "tillage false alarms", 20, int((til.pred & ~til.cons).sum()), "{:.0f}")
chk(9, "best available tillage split %", None,
    max(100 * ((til.armor >= t) == til.cons).mean()
        for t in til.armor.dropna().unique()), "{:.1f}",
    "deck uses 0.4441, not the best split")

# ----------------------------------------------- slide 10: purity bands -----
for lab, lo, hi, cacc, cn in [("Under 60% one crop", -1, 60, 12.9, 31),
                              ("60-75% one crop", 60, 75, 72.0, 25),
                              ("75-90% one crop", 75, 90, 90.0, 90),
                              ("Over 90% one crop", 90, 100, 88.1, 201)]:
    g = cdl[(cdl.cdl_pct > lo) & (cdl.cdl_pct <= hi)]
    chk(10, "%s accuracy %%" % lab, cacc, 100 * g.agree.mean(), "{:.1f}")
    chk(10, "%s n" % lab, cn, len(g), "{:.0f}")
keep = cdl[cdl.cdl_pct > 75]
chk(10, "accuracy, all 347 %", 80.7, 100 * cdl.agree.mean(), "{:.1f}")
chk(10, "accuracy after refusing the worst %", 88.7, 100 * keep.agree.mean(), "{:.1f}")
chk(10, "share refused %", 16, 100 * (1 - len(keep) / len(cdl)), "{:.0f}",
    "16.1 unrounded")

# -------------------------------------------- slide 11: the recalibration ---
nocov = cc[~cc.truth]
chk(11, "cotton fields with no cover crop", 68, len(nocov), "{:.0f}")
chk(11, "false alarms at NDVI 0.35", 60, int((nocov.max_ndvi >= 0.35).sum()), "{:.0f}")
chk(11, "false alarms at NDVI 0.449", 42, int((nocov.max_ndvi >= 0.449).sum()), "{:.0f}")
chk(11, "false alarms removed", 18,
    int((nocov.max_ndvi >= 0.35).sum() - (nocov.max_ndvi >= 0.449).sum()), "{:.0f}")
chk(11, "accuracy at 0.35 %", 67, 100 * ((cc.max_ndvi >= 0.35) == cc.truth).mean(), "{:.0f}")
chk(11, "accuracy at 0.449 %", 75, 100 * ((cc.max_ndvi >= 0.449) == cc.truth).mean(), "{:.0f}")
chk(11, "median peak NDVI, no cover, cotton", 0.50, nocov.max_ndvi.median(), "{:.2f}")
chk(11, "median peak NDVI, no cover, all crops", 0.53,
    cover[~cover.truth].max_ndvi.median(), "{:.2f}",
    "slide quotes both; peanuts pull the pooled figure up")

# ----------------------------------------------------- slide 12: the 2x2 ----
cell = {}
for tk, tl in [("< 15%", "Conventional"), ("> 30%", "Conservation")]:
    for ck in ["No", "Yes"]:
        g = til[(til.till == tk) & (til.cover == ck)]
        cell[(tl, ck)] = (g.armor.median(), len(g))
for (tl, ck), cv, cn in [(("Conventional", "No"), 0.344, 35),
                         (("Conventional", "Yes"), 0.604, 13),
                         (("Conservation", "No"), 0.507, 31),
                         (("Conservation", "Yes"), 0.625, 95)]:
    chk(12, "%s / cover=%s median" % (tl, ck), cv, cell[(tl, ck)][0])
    chk(12, "%s / cover=%s n" % (tl, ck), cn, cell[(tl, ck)][1], "{:.0f}")

ce_conv = cell[("Conventional", "Yes")][0] - cell[("Conventional", "No")][0]
ce_cons = cell[("Conservation", "Yes")][0] - cell[("Conservation", "No")][0]
te_no = cell[("Conservation", "No")][0] - cell[("Conventional", "No")][0]
te_yes = cell[("Conservation", "Yes")][0] - cell[("Conventional", "Yes")][0]
# The slide quoted 0.26 against 0.02 until September 2026. Those are the
# largest cover cell and the smallest tillage cell, taken from opposite
# corners. All four stay here, unclaimed, so the spread remains visible.
chk(12, "cover effect, conventional row", None, ce_conv, "{:.3f}")
chk(12, "cover effect, conservation row", None, ce_cons, "{:.3f}")
chk(12, "tillage effect, with-cover column", None, te_yes, "{:.3f}")
chk(12, "tillage effect, no-cover column", None, te_no, "{:.3f}")
chk(12, "cover effect, mean of both rows", None, (ce_conv + ce_cons) / 2, "{:.3f}")
chk(12, "tillage effect, mean of both columns", None, (te_no + te_yes) / 2, "{:.3f}")
chk(12, "cover-to-tillage ratio, opposite corners", None, 0.26 / 0.02, "{:.1f}",
    "what the retired 0.26-against-0.02 line implied")
chk(12, "cover-to-tillage ratio, means", None,
    ((ce_conv + ce_cons) / 2) / ((te_no + te_yes) / 2), "{:.1f}")
chk(12, "marginal median gap, cover", None,
    til[til.cover == "Yes"].armor.median() - til[til.cover == "No"].armor.median(),
    "{:.3f}")
chk(12, "marginal median gap, tillage", None,
    til[til.cons].armor.median() - til[~til.cons].armor.median(), "{:.3f}")
chk(12, "% of conservation-tilled with a cover crop", 75,
    100 * cell[("Conservation", "Yes")][1] /
    (cell[("Conservation", "Yes")][1] + cell[("Conservation", "No")][1]), "{:.0f}")
chk(12, "field-years with a reported tillage class", 174, len(til), "{:.0f}")

# --------------------------------------------------------- slide 13 --------
chk(13, "reduced-till cotton fields", 9, int((cot.till == "15-30%").sum()), "{:.0f}")

out = pd.DataFrame(rows)
print(out.to_string(index=False))
bad = out[out.verdict == "MISMATCH"]
print("\n%d claims checked, %d mismatches, %d context figures the deck does "
      "not quote" % ((out.verdict != "--").sum(), len(bad), (out.deck == "--").sum()))
if len(bad):
    print("\n==== MISMATCHES ====")
    print(bad.to_string(index=False))
out.to_csv(V + "deck_cohort_sweep.csv", index=False)
print("\nwritten: " + V + "deck_cohort_sweep.csv")
