#!/usr/bin/env python
"""Confusion counts for every validated category, taking the survey as truth.

    python validation/confusion.py

Reads the outputs of run_cdl.py, run_cover.R and the phase-2 armor run. The
tillage and recalibrated-cover thresholds are fitted IN SAMPLE, so these counts
are the optimistic view; the cross-validated accuracies are printed beside them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
POS = {"likely cover crop", "green cover -- cover crop or small grain"}


def cm(pred, truth, label, pos_means, neg_means, note=""):
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    tn = int((~pred & ~truth).sum())
    n = tp + fp + fn + tn
    print(f"\n  {label} {note}")
    print(f"    true positive  {tp:3d}   {pos_means}, called correctly")
    print(f"    false positive {fp:3d}   {neg_means}, called wrongly")
    print(f"    false negative {fn:3d}   {pos_means}, missed")
    print(f"    true negative  {tn:3d}   {neg_means}, called correctly")
    print(f"    correct {tp + tn}/{n} = {100 * (tp + tn) / n:.1f}%   "
          f"sensitivity {100 * tp / max(tp + fn, 1):.1f}%   "
          f"specificity {100 * tn / max(tn + fp, 1):.1f}%")


def main() -> int:
    t = pd.read_csv(HERE / "truth.csv")

    print("=" * 66, "\n1. CROP TYPE -- CDL dominant class vs grower\n", "=" * 66)
    c = pd.read_csv(HERE / "cdl_scored.csv")
    print(f"n = {len(c)}: correct {c.agree.sum()}, incorrect {(~c.agree).sum()} "
          f"({100 * c.agree.mean():.1f}%)")
    for crop in ("Cotton", "Peanuts"):
        cm(c.cdl_crop == crop, c.crop == crop, f'"{crop}" as positive class:',
           f"grower said {crop}", f"grower said something else")
    g = c[c.cdl_pct >= 75]
    print(f"\n  excluding CDL purity < 75% ({len(c) - len(g)} rows dropped): "
          f"{g.agree.sum()}/{len(g)} = {100 * g.agree.mean():.1f}% correct")

    print("\n" + "=" * 66, "\n2. COVER CROP -- off-season verdict vs grower\n", "=" * 66)
    d = pd.read_csv(HERE / "cover_scored.csv")
    d = d[d.verdict != "ERROR"].copy()
    d["truth"] = d.cover == "Yes"
    cm(d.verdict.isin(POS), d.truth, "SHIPPED thresholds (NDVI 0.35):",
       "cover crop grown", "no cover crop")
    for crop, th in (("Cotton", 0.449), ("Peanuts", 0.700)):
        s = d[d.crop == crop]
        cm(s.max_ndvi >= th, s.truth, f"RECALIBRATED {crop}, max NDVI >= {th}:",
           "cover crop grown", "no cover crop", "(fitted in sample)")

    print("\n" + "=" * 66, "\n3. TILLAGE -- soil armor vs reported residue class\n", "=" * 66)
    b = t.merge(pd.read_csv(HERE / "metrics.csv"), on="key")
    b = b[(b.n_obs > 0) & b["till"].isin(["< 15%", "> 30%"])].copy()
    b["truth"] = b["till"] == "> 30%"
    print(f"n = {len(b)}; the 16 rows in the 15-30% class are excluded -- too "
          f"few to fit or test.")
    for crop, th, cvacc in (("Cotton", 0.437, 73.8), ("Peanuts", 0.594, 83.4)):
        s = b[b.crop == crop]
        cm(s.armor >= th, s.truth, f"{crop}, soil armor >= {th}:",
           "conservation till (>30% residue)", "conventional till (<15%)",
           f"(fitted in sample; cross-validated {cvacc}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
