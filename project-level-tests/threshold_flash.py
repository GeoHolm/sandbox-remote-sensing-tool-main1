#!/usr/bin/env python3
"""What would a recalibrated threshold buy on the FLASH cohort?

Sensitivity only -- there are no labelled negatives, so this cannot find an
optimum. It can say what the current threshold costs, which is the question
the 35 misses raise.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
PROJ = Path(__file__).resolve().parent / "project-FLASH"

rs = pd.read_csv(PROJ / "rs_covercrop.csv")
runs = pd.read_csv(PROJ / "rs_fields.csv")
lab = rs[rs.winter == "2025-26"].merge(
    runs[["key", "boundary_verdict", "obs"]], on="key")

print("=== winter 2025-26, 98 fields, every one a reported cover crop ===")
print("peak winter NDVI distribution:")
for q in (0, 10, 25, 50, 75, 90, 100):
    print("   p%-3d  %.3f" % (q, np.percentile(lab.max_ndvi, q)))

print("\n=== sensitivity against a peak-NDVI threshold ===")
print("  (CC_GREEN_MIN is 0.30 today; CC_STRONG 0.35)")
for t in (0.20, 0.22, 0.25, 0.28, 0.30, 0.32, 0.35, 0.40):
    hit = (lab.max_ndvi >= t).sum()
    mark = "   <- shipped" if abs(t - 0.30) < 1e-9 else ""
    print("   >= %.2f   %2d / 98 = %5.1f%%%s" % (t, hit, 100 * hit / 98, mark))

print("\n=== are the misses bare, or just under the line? ===")
miss = lab[lab.max_ndvi < 0.30]
print("  misses: %d   peak NDVI range %.3f to %.3f"
      % (len(miss), miss.max_ndvi.min(), miss.max_ndvi.max()))
print("  how many misses are below 0.15 (genuinely bare)? %d"
      % (miss.max_ndvi < 0.15).sum())
print("  how many sit in 0.20-0.30 (green, under threshold)?  %d"
      % miss.max_ndvi.between(0.20, 0.30).sum())

print("\n=== does boundary quality explain the misses? ===")
lab["hit"] = lab.max_ndvi >= 0.30
ct = pd.crosstab(lab.boundary_verdict, lab.hit)
ct.columns = ["missed", "detected"]
ct["detection rate"] = (100 * ct["detected"] / ct.sum(axis=1)).round(1)
print(ct.to_string())

print("\n=== does observation count explain them? ===")
lab["obs_band"] = pd.cut(lab.n_obs, [0, 10, 15, 20, 100],
                         labels=["<=10", "11-15", "16-20", ">20"])
ct2 = pd.crosstab(lab.obs_band, lab.hit)
ct2.columns = ["missed", "detected"]
ct2["detection rate"] = (100 * ct2["detected"] / ct2.sum(axis=1)).round(1)
print(ct2.to_string())

print("\n=== adoption trend the detector reports across four winters ===")
LOOSE = ["likely cover crop", "possible cover crop",
         "green cover -- cover crop or small grain"]
for w in sorted(rs.winter.unique()):
    g = rs[rs.winter == w]
    print("   %s  any green %5.1f%%   peak NDVI median %.3f"
          % (w, 100 * g.verdict.isin(LOOSE).mean(), g.max_ndvi.median()))
print("\n  Only the last winter is labelled. The trend is what a cohort")
print("  progressively adopting cover crops would look like -- which is what")
print("  a soil health project is -- but nothing here can separate that from")
print("  a detector drifting.")
