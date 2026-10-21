#!/usr/bin/env python3
"""Run the pipeline on the four 4D farm boundaries and report the four things
asked for: CDL crop, NDVI, cover crop verdict, planting and harvest.

    python project-level-tests/run_4d_farm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd  # noqa: E402

from fieldrs import analyze_field  # noqa: E402

pd.set_option("display.width", 220)
PROJ = Path(__file__).resolve().parent / "4d-farm"
YEARS = (2022, 2026)

out_hist, out_phen, out_cc, out_ser, out_fld = [], [], [], [], []

for p in sorted((PROJ / "boundaries").glob("*.geojson")):
    t0 = time.time()
    print("=" * 74, flush=True)
    print(p.stem, flush=True)
    r = analyze_field(p, years=YEARS, workers=8)
    mins = (time.time() - t0) / 60

    # 10 m pixels: a small field is a small sample, and that gates everything.
    px = int(round(r.area_ha * 100))
    out_fld.append({"field": p.stem, "area_ha": round(r.area_ha, 2),
                    "acres": round(r.area_ha * 2.47105, 1),
                    "approx_10m_pixels": px,
                    "clear_obs": len(r.series),
                    "boundary_verdict": "" if r.advice is None else r.advice.verdict,
                    "boundary_flagged_ha": ("" if r.advice is None
                                            else round(r.advice.area_ha, 2)),
                    "cdl_mean_purity_pct": ("" if r.advice is None
                                            else round(r.advice.per_year.pct.mean(), 1)),
                    "minutes": round(mins, 2)})

    for df, bucket in ((r.history, out_hist), (r.phenology, out_phen),
                       (r.covercrop, out_cc)):
        if df is not None and len(df):
            d = df.copy(); d.insert(0, "field", p.stem); bucket.append(d)
    s = r.series.copy(); s.insert(0, "field", p.stem); out_ser.append(s)
    print("    %.1f min, %d clear observations" % (mins, len(r.series)), flush=True)

hist = pd.concat(out_hist, ignore_index=True)
phen = pd.concat(out_phen, ignore_index=True)
cc = pd.concat(out_cc, ignore_index=True)
ser = pd.concat(out_ser, ignore_index=True)
fld = pd.DataFrame(out_fld)

print("\n" + "=" * 74)
print("FIELD PROPERTIES")
print("=" * 74)
print(fld.to_string(index=False))

print("\n" + "=" * 74)
print("1. CDL CROP BY YEAR")
print("=" * 74)
print(hist.pivot(index="year", columns="field", values="crop").to_string())
print("\npurity, % of the boundary the dominant class covers:")
print(hist.pivot(index="year", columns="field", values="pct").to_string())

print("\n" + "=" * 74)
print("2. NDVI")
print("=" * 74)
ser["date"] = pd.to_datetime(ser["date"])
ser["year"] = ser.date.dt.year
g = ser.groupby(["field", "year"])["mean"]
print(pd.DataFrame({"n_obs": g.size(), "min": g.min().round(3),
                    "median": g.median().round(3), "max": g.max().round(3)})
      .reset_index().pivot(index="year", columns="field",
                           values=["n_obs", "median", "max"]).to_string())

print("\n" + "=" * 74)
print("3. COVER CROP")
print("=" * 74)
print(cc[["field", "winter", "n_obs", "max_ndvi", "green_days", "verdict"]]
      .to_string(index=False))

print("\n" + "=" * 74)
print("4. PLANTING AND HARVEST")
print("=" * 74)
for c in ("planting_est", "planting_lo", "planting_hi", "harvest_est",
          "harvest_lo", "harvest_hi"):
    phen[c] = pd.to_datetime(phen[c]).dt.strftime("%d %b %Y")
print(phen[["field", "year", "crop", "planting_est", "planting_lo",
            "planting_hi", "harvest_est", "harvest_lo", "harvest_hi",
            "season_days", "peak_ndvi", "n_obs", "confidence"]]
      .to_string(index=False))

PROJ.mkdir(exist_ok=True)
fld.to_csv(PROJ / "fields.csv", index=False)
hist.to_csv(PROJ / "cdl_by_year.csv", index=False)
phen.to_csv(PROJ / "season_markers.csv", index=False)
cc.to_csv(PROJ / "cover_crop.csv", index=False)
ser.to_csv(PROJ / "ndvi_series.csv", index=False)
print("\nwrote fields.csv, cdl_by_year.csv, season_markers.csv, "
      "cover_crop.csv, ndvi_series.csv to", PROJ)
