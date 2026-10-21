#!/usr/bin/env python3
"""Spot test: how far must you go to find enough same-rotation neighbours?

    python project-level-tests/match_radius.py <clu.shp> <project-dir> [--year 2025]

match_rotation.py showed that matching on crop sequence explains most of
the spread the benchmark would otherwise call management -- and that
outside the Corn Belt it leaves a handful of peers. This asks whether the
answer is simply to look further.

Re-applies the same pool filters as select_cohort.py to the whole county,
then counts, at increasing radius from the committed focus field, how many
neighbours share the focus field's crop, its crop pair, and its triple.

No pipeline run and nothing written to the committed cohorts: this reads
CLU and the local CDL store only.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402
from shapely.geometry import Point  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from fieldrs.cdl_local import year_tif  # noqa: E402
from fieldrs.cropland import CDL_NONCROP, cdl_name  # noqa: E402

HERE = Path(__file__).resolve().parent
EQUAL_AREA = 5070
AC_MIN, AC_MAX = 40.0, 400.0
COMPACT_MIN = 0.35
CDL_YEARS = (2022, 2023, 2024, 2025)
PURITY_MIN = 60.0
CROP_YEARS_MIN = 3
MIN_PEERS = 10
RADII_KM = [2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25]

# same list as select_cohort.PERENNIAL
PERENNIAL = frozenset({36, 37, 66, 67, 68, 69, 70, 71, 72, 74, 75, 76, 77,
                       204, 210, 211, 212, 215, 217, 218, 220, 223, 242, 250})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clu")
    ap.add_argument("proj")
    ap.add_argument("--year", type=int, default=2025)
    a = ap.parse_args()
    PROJ = HERE / a.proj
    meta = json.loads((PROJ / "cohort_meta.json").read_text())
    coh = pd.read_csv(PROJ / "cohort.csv")
    f = coh[coh.fid == "focus"].iloc[0]

    g = gpd.read_file(a.clu).to_crs(EQUAL_AREA)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    g["acres"] = g.area / 4046.86
    g["compact"] = 4 * np.pi * g.area / g.length ** 2
    cand = g[(g.acres >= AC_MIN) & (g.acres <= AC_MAX)
             & (g.compact >= COMPACT_MIN)].reset_index(drop=True)

    bounds = cand.total_bounds
    top, pur = {}, {}
    for yr in CDL_YEARS:
        tif = year_tif(yr)
        if tif is None:
            continue
        with rasterio.open(tif) as src:
            win = from_bounds(*bounds, transform=src.transform)
            arr = src.read(1, window=win)
            tr = src.window_transform(win)
        ids = rasterize(((geom, i + 1) for i, geom in enumerate(cand.geometry)),
                        out_shape=arr.shape, transform=tr, fill=0, dtype="int32")
        valid = ids > 0
        key = (ids[valid].astype(np.int64) << 10) | arr[valid].astype(np.int64)
        uk, cnt = np.unique(key, return_counts=True)
        fi = (uk >> 10).astype(int) - 1
        cl = (uk & 1023).astype(int)
        best_n = np.zeros(len(cand)); best_c = np.zeros(len(cand), dtype=int)
        tot = np.zeros(len(cand))
        for i, c, n in zip(fi, cl, cnt):
            tot[i] += n
            if n > best_n[i]:
                best_n[i], best_c[i] = n, c
        top[yr] = best_c
        pur[yr] = np.divide(best_n * 100.0, tot, out=np.zeros(len(cand)),
                            where=tot > 0)

    ok_years = np.zeros(len(cand), dtype=int)
    for yr in top:
        is_crop = np.array([c not in CDL_NONCROP and c not in PERENNIAL
                            and c != 0 for c in top[yr]])
        ok_years += (is_crop & (pur[yr] >= PURITY_MIN)).astype(int)
    pool = cand[ok_years >= CROP_YEARS_MIN].copy()
    for yr in top:
        pool["c%d" % yr] = [cdl_name(int(c)) for c in np.asarray(top[yr])[
            (ok_years >= CROP_YEARS_MIN)]]
    print("%s: %d CLU polygons -> %d in the pool"
          % (meta.get("county", a.proj), len(g), len(pool)))

    y = a.year
    pool["crop"] = pool["c%d" % y]
    pool["pair"] = pool["c%d" % y] + " <- " + pool["c%d" % (y - 1)]
    pool["triple"] = (pool["c%d" % y] + " <- " + pool["c%d" % (y - 1)]
                      + " <- " + pool["c%d" % (y - 2)])

    fp = gpd.GeoDataFrame(geometry=[Point(f.lon, f.lat)],
                          crs=4326).to_crs(EQUAL_AREA).geometry.iloc[0]
    cen = pool.geometry.centroid
    pool["dist_km"] = np.sqrt((cen.x - fp.x) ** 2 + (cen.y - fp.y) ** 2) / 1000

    # the focus field is the pool member nearest the committed centroid
    me = pool.loc[pool.dist_km.idxmin()]
    print("focus field %d rotation: %s" % (y, me.triple))
    print()
    print("%6s %9s %11s %11s %11s" % ("radius", "in pool", "same crop",
                                      "same pair", "same triple"))
    print("-" * 52)
    hit = {}
    for r in RADII_KM:
        sub = pool[(pool.dist_km <= r) & (pool.index != me.name)]
        n_c = int((sub.crop == me.crop).sum())
        n_p = int((sub.pair == me.pair).sum())
        n_t = int((sub.triple == me.triple).sum())
        for k, v in (("crop", n_c), ("pair", n_p), ("triple", n_t)):
            if k not in hit and v >= MIN_PEERS:
                hit[k] = r
        print("%4d km %9d %11d %11d %11d" % (r, len(sub), n_c, n_p, n_t))
    print()
    for k in ("crop", "pair", "triple"):
        print("  %d+ peers on the same %-7s : %s"
              % (MIN_PEERS, k,
                 "%d km" % hit[k] if k in hit else "not reached by %d km"
                 % RADII_KM[-1]))


if __name__ == "__main__":
    main()
