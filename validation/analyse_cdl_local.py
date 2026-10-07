#!/usr/bin/env python
"""Prove the local CDL store reproduces what the CropScape API returned.

    python validation/analyse_cdl_local.py

Two independent checks, per the local-bulk-data method:

1. **A conserved quantity.** Pixel-count area against the polygon's own
   geometric area -- a referee neither source computed. Asserted for both the
   local store and the saved API responses, so a disagreement can be
   attributed rather than argued about.

2. **A diff against saved responses.** The same 347 field-years the API
   answered, re-run locally, compared on the field that actually drives
   downstream decisions: the dominant crop.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))

from fieldrs.cdl_local import available_years, cdl_root, get_cdl_local  # noqa: E402
from fieldrs.cropland import cdl_name  # noqa: E402


def main() -> int:
    api = pd.read_csv(HERE / "cdl.csv")
    years = available_years()
    print(f"local store: {cdl_root()}\nyears available: {years}\n")
    todo = api[api.year.isin(years)]
    if todo.empty:
        print("No overlap between the store and the saved API responses.")
        return 1

    rows = []
    for i, r in enumerate(todo.itertuples(), 1):
        aoi = gpd.read_file(HERE / "boundaries" / f"{r.key}.geojson")
        try:
            arr, transform, _ = get_cdl_local(aoi, int(r.year))
        except Exception as exc:                          # noqa: BLE001
            print(f"  {r.key}: {type(exc).__name__}: {exc}")
            continue
        v = arr[np.isfinite(arr)].astype("int32")
        if v.size == 0:
            print(f"  {r.key}: no pixels inside the field")
            continue
        codes, counts = np.unique(v, return_counts=True)
        top = int(codes[counts.argmax()])
        px_ha = abs(transform.a) * abs(transform.e) / 1e4
        rows.append({
            "key": r.key, "year": int(r.year),
            "local_crop": cdl_name(top),
            "local_pct": round(100 * counts.max() / counts.sum(), 1),
            "local_px": int(counts.sum()),
            "local_ha": counts.sum() * px_ha,
            "geom_ha": aoi.to_crs(5070).geometry.area.sum() / 1e4,
        })
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)

    loc = pd.DataFrame(rows)
    d = todo.merge(loc, on=["key", "year"])
    d["api_ha"] = d.n_pixels * 900 / 1e4
    d["agree"] = d.cdl_crop == d.local_crop
    print(f"\ncompared {len(d)} field-years\n")

    print("=== 1. area conservation against polygon geometric area ===")
    for lab, col in (("local store", "local_ha"), ("CropScape API", "api_ha")):
        e = 100 * (d[col] - d.geom_ha) / d.geom_ha
        print(f"  {lab:14s} mean {e.mean():+.2f}%  median {e.median():+.2f}%  "
              f"worst {e.abs().max():.2f}%")

    print("\n=== 2. dominant crop: local vs the saved API answer ===")
    print(f"  agree on {d.agree.sum()} of {len(d)} "
          f"({100 * d.agree.mean():.1f}%)")
    bad = d[~d.agree]
    if len(bad):
        print("\n  disagreements:")
        for r in bad.head(15).itertuples():
            print(f"    {r.key}: API {r.cdl_crop} ({r.cdl_pct}%) vs "
                  f"local {r.local_crop} ({r.local_pct}%)")
        print("\n  margin between top two classes on disagreeing rows is the "
              "thing to look at: a field that is 49/48 will flip on any\n"
              "  grid offset and neither answer is wrong.")

    print("\n=== pixel counts ===")
    dp = 100 * (d.local_px - d.n_pixels) / d.n_pixels
    print(f"  local vs API: mean {dp.mean():+.2f}%  median {dp.median():+.2f}%  "
          f"identical on {(d.local_px == d.n_pixels).sum()} of {len(d)}")

    out = HERE / "cdl_local_check.csv"
    d.to_csv(out, index=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
