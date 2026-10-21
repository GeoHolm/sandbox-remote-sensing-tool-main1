#!/usr/bin/env python3
"""Pick a focus field in a county and the cohort of neighbors around it.

    python project-level-tests/select_cohort.py <clu_shapefile> <out-dir> [--n 50]

The input is a 2008 public release of the USDA Common Land Unit for one
county. Public CLU carries geometry and acreage only; every identifying
attribute was stripped before release, so nothing here can be traced to a
farm, and the boundaries are a 2008 snapshot that has had eighteen years to
go stale.

Three filters, then a radius:

  size        40 to 400 acres. Below 40 the Sentinel-2 sample gets thin and
              edge pixels start to dominate; above 400 a CLU polygon in this
              county is usually rangeland rather than a cropped field.
  shape       Polsby-Popper above 0.35. Grass waterways, terraces, road
              verges and field borders are all long and thin, and all of
              them are in the CLU as separate units.
  cropland    dominant CDL class is a crop, in at least 3 of 4 years, at
              60%+ purity each year. Screened against the local bulk CDL
              with one windowed read per year rather than one web request
              per field -- 25,576 polygons would be 100,000 requests.

The focus field is then the qualifying field with the most qualifying
neighbors nearby, so the cohort is a real neighborhood rather than a circle
reaching across half a county. The radius grows until it holds --n of them.

Writes boundaries/*.geojson (one per field, WGS84) and cohort.csv.
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

# Perennials and orchards are crops, and CDL_NONCROP rightly does not exclude
# them -- but they do not belong in a row-crop soil-cover cohort. An orchard
# has a permanent canopy and a grass floor, and an alfalfa stand is green for
# years at a time, so both score high armor all year for reasons that have
# nothing to do with the management this benchmark is comparing. Mitchell
# County put four pecan groves in a cohort of fifty before this existed.
#
# This lives here rather than in fieldrs/cropland.py on purpose: the library
# is right to treat pecans as a crop. It is this comparison that needs them
# out.
PERENNIAL = frozenset({
    36,    # Alfalfa
    37,    # Other Hay/Non Alfalfa
    66,    # Cherries
    67,    # Peaches
    68,    # Apples
    69,    # Grapes
    70,    # Christmas Trees
    71,    # Other Tree Crops
    72,    # Citrus
    74,    # Pecans
    75,    # Almonds
    76,    # Walnuts
    77,    # Pears
    204,   # Pistachios
    210,   # Prunes
    211,   # Olives
    212,   # Oranges
    215,   # Avocados
    217,   # Pomegranates
    218,   # Nectarines
    220,   # Plums
    223,   # Apricots
    242,   # Blueberries
    250,   # Cranberries
})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clu")
    ap.add_argument("out", help="project directory, e.g. champaign-il")
    ap.add_argument("--n", type=int, default=50,
                    help="cohort size, excluding the focus field")
    ap.add_argument("--county", default="", help="label for cohort_meta.json")
    a = ap.parse_args()
    PROJ = HERE / a.out

    g = gpd.read_file(a.clu).to_crs(EQUAL_AREA)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    g["acres"] = g.area / 4046.86
    g["compact"] = 4 * np.pi * g.area / g.length ** 2
    print("CLU polygons              : %6d" % len(g))

    cand = g[(g.acres >= AC_MIN) & (g.acres <= AC_MAX)
             & (g.compact >= COMPACT_MIN)].reset_index(drop=True)
    cand["fid"] = ["f%04d" % i for i in range(len(cand))]
    print("  %4.0f-%4.0f acres, compact : %6d" % (AC_MIN, AC_MAX, len(cand)))

    # ---- CDL screen: burn the polygons once per year, then bincount --------
    bounds = cand.total_bounds
    pur = {}
    crop_ok = np.zeros(len(cand), dtype=int)
    top = {}
    for yr in CDL_YEARS:
        tif = year_tif(yr)
        if tif is None:
            print("  CDL %d: not in the local store, skipped" % yr)
            continue
        with rasterio.open(tif) as src:
            win = from_bounds(*bounds, transform=src.transform)
            arr = src.read(1, window=win)
            tr = src.window_transform(win)
        ids = rasterize(((geom, i + 1) for i, geom in enumerate(cand.geometry)),
                        out_shape=arr.shape, transform=tr, fill=0,
                        dtype="int32")
        # one pass: (field, class) pair counts via a combined key
        valid = ids > 0
        key = (ids[valid].astype(np.int64) << 10) | arr[valid].astype(np.int64)
        uk, cnt = np.unique(key, return_counts=True)
        fi = (uk >> 10).astype(int) - 1
        cl = (uk & 1023).astype(int)
        best_n = np.zeros(len(cand))
        best_c = np.zeros(len(cand), dtype=int)
        tot = np.zeros(len(cand))
        for f, c, n in zip(fi, cl, cnt):
            tot[f] += n
            if n > best_n[f]:
                best_n[f], best_c[f] = n, c
        p = np.divide(best_n * 100.0, tot, out=np.zeros(len(cand)),
                      where=tot > 0)
        pur[yr] = p
        top[yr] = best_c
        is_crop = np.array([c not in CDL_NONCROP and c not in PERENNIAL
                            and c != 0 for c in best_c])
        crop_ok += (is_crop & (p >= PURITY_MIN)).astype(int)
        print("  CDL %d screened        : %6d cropland at >=%.0f%% purity"
              % (yr, int((is_crop & (p >= PURITY_MIN)).sum()), PURITY_MIN))

    cand["crop_years"] = crop_ok
    for yr in pur:
        cand["cdl_%d" % yr] = [cdl_name(int(c)) for c in top[yr]]
        cand["pct_%d" % yr] = pur[yr].round(1)
    ok = cand[cand.crop_years >= CROP_YEARS_MIN].reset_index(drop=True)
    print("  cropland in >=%d of %d yr : %6d  <- the pool"
          % (CROP_YEARS_MIN, len(pur), len(ok)))
    if len(ok) < a.n + 1:
        sys.exit("pool of %d is smaller than the %d asked for" % (len(ok), a.n))

    # The focus field is the centrepiece of the whole comparison, so it is
    # held to a stricter bar than its neighbours: cropland at full purity in
    # EVERY screened year, not three of four. Mitchell County otherwise put
    # forward a field whose 2023 read 49% pure, which is a boundary that no
    # longer matches the field.
    clean = ok[ok.crop_years == len(pur)].reset_index(drop=True)
    print("  clean in all %d years     : %6d  <- focus candidates"
          % (len(pur), len(clean)))
    if not len(clean):
        sys.exit("no field is cropland at full purity in every screened year")

    # ---- focus field: the one with the densest qualifying neighborhood -----
    cent = ok.geometry.centroid
    xy = np.c_[cent.x, cent.y]
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
    # distance to the n-th nearest qualifying field: small = dense
    kth = np.sort(d, axis=1)[:, a.n]
    # ...but only a clean field may be the focus
    is_clean = (ok.crop_years == len(pur)).to_numpy()
    kth_masked = np.where(is_clean, kth, np.inf)
    focus_i = int(np.argmin(kth_masked))
    radius = float(kth[focus_i])
    order = np.argsort(d[focus_i])[:a.n + 1]

    sel = ok.iloc[order].copy().reset_index(drop=True)
    sel["dist_m"] = d[focus_i][order].round(0)
    sel["role"] = ["focus"] + ["cohort"] * (len(sel) - 1)
    sel["fid"] = ["focus" if r == "focus" else f
                  for r, f in zip(sel.role, sel.fid)]

    print()
    print("focus field  : %s, %.0f acres" % (sel.fid[0], sel.acres[0]))
    print("cohort       : %d fields within %.0f m (%.1f km)"
          % (len(sel) - 1, radius, radius / 1000))
    print("cohort acres : median %.0f (range %.0f-%.0f)"
          % (sel.acres[1:].median(), sel.acres[1:].min(), sel.acres[1:].max()))
    print()
    print("focus field rotation:")
    for yr in sorted(pur):
        print("   %d  %-22s %5.1f%% pure"
              % (yr, sel["cdl_%d" % yr][0], sel["pct_%d" % yr][0]))
    print()
    print("cohort crop mix, most recent screened year:")
    last = max(pur)
    print(sel["cdl_%d" % last][1:].value_counts().to_string())

    # ---- write ------------------------------------------------------------
    bdir = PROJ / "boundaries"
    bdir.mkdir(parents=True, exist_ok=True)
    for old in bdir.glob("*.geojson"):
        old.unlink()
    wgs = sel.to_crs(4326)
    for fid, geom in zip(sel.fid, wgs.geometry):
        (bdir / ("%s.geojson" % fid)).write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"fid": fid},
                          "geometry": geom.__geo_interface__}],
        }), encoding="utf-8")
    # Centroid in the equal-area CRS, then projected: taking it from the
    # WGS84 geometry averages degrees, which is not where the field is.
    c = sel.geometry.centroid.to_crs(4326)
    out = sel.drop(columns="geometry").copy()
    out["lon"] = c.x.round(6)
    out["lat"] = c.y.round(6)
    out["acres"] = out.acres.round(1)
    out["compact"] = out.compact.round(3)
    out.to_csv(PROJ / "cohort.csv", index=False)
    (PROJ / "cohort_meta.json").write_text(json.dumps({
        "source": "USDA FSA Common Land Unit, public release 2008-02-04",
        "county": a.county or a.out,
        "clu_polygons": int(len(g)),
        "pool_after_filters": int(len(ok)),
        "cohort_n": int(len(sel) - 1),
        "radius_m": round(radius),
        "filters": {"acres": [AC_MIN, AC_MAX], "polsby_popper": COMPACT_MIN,
                    "cdl_purity_pct": PURITY_MIN,
                    "cropland_years_required": CROP_YEARS_MIN,
                    "cdl_years_screened": sorted(pur)},
    }, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %d boundaries, cohort.csv, cohort_meta.json to %s"
          % (len(sel), PROJ))


if __name__ == "__main__":
    main()
