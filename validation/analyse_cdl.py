#!/usr/bin/env python
"""Score CDL's crop label against the grower-reported crop.

    python validation/analyse_cdl.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main() -> int:
    t = pd.read_csv(HERE / "truth.csv")
    c = pd.read_csv(HERE / "cdl.csv")
    d = t.merge(c.drop(columns=["field_id", "year"]), on="key")
    d["agree"] = d["crop"] == d["cdl_crop"]

    print(f"scored {len(d)} of {len(t)} field-years "
          f"({d['field_id'].nunique()} fields)\n")

    print("=== agreement with the grower ===")
    print(f"  overall           {100 * d['agree'].mean():.1f}%")
    for crop, g in d.groupby("crop"):
        print(f"  {crop:16s}  {100 * g['agree'].mean():.1f}%   (n={len(g)})")
    print()
    print("  by year")
    for y, g in d.groupby("year"):
        print(f"    {y}  {100 * g['agree'].mean():.1f}%   (n={len(g)})")

    print("\n=== confusion: grower (rows) vs CDL (cols) ===")
    x = pd.crosstab(d["crop"], d["cdl_crop"])
    keep = x.sum().sort_values(ascending=False).head(8).index
    print(x[keep].to_string())

    print("\n=== when CDL disagrees, what did it see? ===")
    bad = d[~d["agree"]]
    if len(bad):
        print(f"  {len(bad)} disagreements")
        print("  share of field CDL still calls the grower's crop:")
        print(f"    median {bad['survey_crop_pct'].median():.1f}%, "
              f"{(bad['survey_crop_pct'] == 0).sum()} rows at 0% "
              "(crop absent entirely)")
        print("  top CDL labels on disagreeing rows:")
        for k, v in bad["cdl_crop"].value_counts().head(6).items():
            print(f"    {k:22s} {v}")

    print("\n=== does boundary purity predict agreement? ===")
    d["purity"] = pd.cut(d["cdl_pct"], [0, 60, 75, 90, 100],
                         labels=["<60%", "60-75%", "75-90%", ">90%"])
    print(d.groupby("purity", observed=True)
           .agg(n=("agree", "size"), agreement=("agree", "mean"))
           .assign(agreement=lambda x: (100 * x["agreement"]).round(1))
           .to_string())

    print("\n=== does field size predict agreement? ===")
    d["size"] = pd.cut(d["acres"], [0, 50, 100, 200, 1e4],
                       labels=["<50ac", "50-100", "100-200", ">200"])
    print(d.groupby("size", observed=True)
           .agg(n=("agree", "size"), agreement=("agree", "mean"))
           .assign(agreement=lambda x: (100 * x["agreement"]).round(1))
           .to_string())

    out = HERE / "cdl_scored.csv"
    d.to_csv(out, index=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
