#!/usr/bin/env python3
"""Soil armor on the FLASH boundaries, and the one comparison this data allows.

    python project-level-tests/analyse_flash_armor.py

Soil armor is 1 - bare soil fraction: the share of the surface covered by
anything, living or residue. It is a COVER metric. It is not a tillage metric,
and the Georgia validation showed its apparent tillage signal running almost
entirely through cover crop adoption.

That matters here because this cohort cannot test it against tillage anyway:
95% of field-years report the identical pair of tillage operations.
"""
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 200)
PROJ = Path(__file__).resolve().parent / "project-FLASH"

a = pd.read_csv(PROJ / "rs_armor.csv")
rs = pd.read_csv(PROJ / "rs_covercrop.csv")
runs = pd.read_csv(PROJ / "rs_fields.csv")
LOOSE = ["likely cover crop", "possible cover crop",
         "green cover -- cover crop or small grain"]
rs["detected"] = rs.verdict.isin(LOOSE)

print("=" * 72)
print("SOIL ARMOR -- 98 Illinois fields, spring pre-planting window")
print("=" * 72)
print("field-years        : %d" % len(a))
print("with a reading     : %d (%.0f%%)" % (a.armor.notna().sum(),
                                            100 * a.armor.notna().mean()))
print("median armor       : %.3f" % a.armor.median())
print("median f_pv (living): %.3f   f_npv (residue): %.3f   f_bs (bare): %.3f"
      % (a.f_pv.median(), a.f_npv.median(), a.f_bs.median()))

print("\n--- readability by year ---")
t = a.groupby("year").agg(field_years=("armor", "size"),
                          readable=("armor", "count"),
                          median_armor=("armor", "median"),
                          median_obs=("n_obs", "median"))
t["pct_readable"] = (100 * t.readable / t.field_years).round(0)
print(t.to_string())
print("\n  Unreadable years are almost all too few clear dates in the window:")
print(a[a.armor.isna()].note.str.slice(0, 50).value_counts().to_string())

# ---------------------------------------------------------------------------
# The one cross-check this cohort supports: spring 2026 armor against what the
# cover crop detector concluded about the winter that preceded it.
print("\n--- spring 2026 armor against the 2025-26 cover crop verdict ---")
m = (a[a.year == 2026]
     .merge(rs[rs.winter == "2025-26"][["key", "verdict", "detected",
                                        "max_ndvi"]], on="key")
     .merge(runs[["key", "boundary_verdict"]], on="key"))
m = m[m.armor.notna()]
g = m.groupby("detected").agg(n=("armor", "size"), armor=("armor", "median"),
                              f_pv=("f_pv", "median"), f_npv=("f_npv", "median"),
                              f_bs=("f_bs", "median"))
g.index = ["detector said none", "detector said cover crop"]
print(g.round(3).to_string())
d = (m[m.detected].armor.median() - m[~m.detected].armor.median())
print("\n  difference in median armor: %+.3f" % d)

from scipy import stats  # noqa: E402
u = stats.mannwhitneyu(m[m.detected].armor, m[~m.detected].armor,
                       alternative="two-sided")
auc = u.statistic / (m.detected.sum() * (~m.detected).sum())
print("  Mann-Whitney AUC %.3f, p = %.3f  (0.5 would be no separation)"
      % (auc, u.pvalue))

print("\n--- where the cover actually is ---")
print("  Living cover (f_pv) is only %.3f at the median, against %.3f residue."
      % (a.f_pv.median(), a.f_npv.median()))
print("  Terminations were late April to 20 May and the window closes three days")
print("  before planting, so much of a terminated cover crop is already counted")
print("  as residue rather than as living cover.")

print("\n--- what cannot be tested here ---")
print("  465 of 490 field-years report the identical pair of tillage operations")
print("  and only 23% of tillage activities carry a diesel figure. There is no")
print("  contrast in reported tillage for armor to be scored against.")

out = PROJ / "armor_comparison.csv"
m.to_csv(out, index=False)
print("\nwrote %s" % out.name)
