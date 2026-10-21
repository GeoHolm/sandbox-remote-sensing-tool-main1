#!/usr/bin/env python3
"""One tidy row per field and crop year, for research use.

    python project-level-tests/export_flash_findings.py

Writes project-FLASH/flash_field_year_findings.csv plus a data dictionary.
Everything is read from the warm cache, so this is fast and makes no network
calls.

HOW A ROW IS ALIGNED
A row is a cash crop year. The off-season and ground-cover measurements
attached to it are the ones that *precede* that crop:

    harvest Y-1  ->  winter Y-1/Y  ->  spring window  ->  planting Y
                     cover crop         soil armor       cash crop Y

So crop year 2026 carries the 2025-26 winter verdict and the spring 2026 armor
reading, which is the window running from the 2025 harvest to the 2026
planting. Both describe the ground that crop went into.

WHAT IS DELIBERATELY NOT IN HERE
Farm names and field boundaries. The key is a geometry hash; county and a
centroid rounded to 0.1 degrees (about 11 km) are included because climate and
latitude matter for every question this dataset raises, while a precise
coordinate would identify the farm. The boundaries are on disk for anyone who
needs them and are not committed.
"""
import csv
import hashlib
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402

from fieldrs import analyze_field  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJ = HERE / "project-FLASH"
OUT = PROJ / "flash_field_year_findings.csv"
DICT = PROJ / "flash_field_year_dictionary.csv"
YEARS = range(2022, 2027)

# ----------------------------------------------------- Fieldprint side -----
zpath = next((PROJ / "Fieldprint-payloads").glob("*.zip"), None)
entered = defaultdict(dict)          # key -> crop year -> entered facts
county = {}
acres = {}
if zpath:
    z = zipfile.ZipFile(zpath)
    for n in sorted(x for x in z.namelist() if x.endswith("API Payload.json")):
        d = json.loads(z.read(n))
        f = d["field"]
        k = hashlib.sha1(json.dumps(f["geometry"], sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()[:12]
        county[k] = f.get("location", "")
        acres[k] = round(f.get("plantable_acres", {}).get("value", float("nan")), 1)
        for ci in d.get("crop_intervals", []):
            y = int(ci["harvest_year"])
            acts = ci.get("activities", [])
            cash = [a for a in acts if a["type"] == "planting_cash"]
            harv = [a for a in acts if a["type"] == "harvest"]
            till = [a for a in acts if a["type"] == "tillage"]
            cov = [a for a in acts if a["type"] == "planting_cover"]
            rec = entered[k].setdefault(y, {})
            rec.update({
                "entered_crop_id": ci["crop_id"],
                "entered_planting": cash[0]["date"] if cash else "",
                "entered_harvest": harv[0]["date"] if harv else "",
                "entered_yield": (harv[0]["inputs"].get("yield", {}).get("value")
                                  if harv else None),
                "entered_yield_unit": (harv[0]["inputs"].get("yield", {}).get("unit")
                                       if harv else ""),
                "entered_tillage_passes_pre_plant": sum(
                    1 for a in till if cash and a["date"] <= cash[0]["date"]),
                "entered_tillage_ops": "|".join(sorted(
                    a["inputs"].get("tillage_operation_id", "") for a in till)),
            })
            # A cover crop sown in autumn Y-1 belongs to crop year Y.
            for a in cov:
                yy = int(a["date"][:4])
                fy = yy if int(a["date"][5:7]) >= 7 else yy - 1
                e = entered[k].setdefault(fy + 1, {})
                e["entered_cover_crop"] = "yes"
                e["entered_cover_species_id"] = a["inputs"].get("cover_crop_id", "")
                e["entered_cover_planted"] = a["date"]
                e["entered_cover_terminated"] = a["inputs"].get("termination_date", "")
                e["entered_cover_is_legume"] = a["inputs"].get("is_legume", "")

# ---------------------------------------------------- remote sensing -------
rows = []
files = sorted((PROJ / "boundaries").glob("*.geojson"))
print("reading %d boundaries from cache ..." % len(files), flush=True)

for p in files:
    k = p.stem
    r = analyze_field(p, years=(2022, 2026), only_cached=True, residue=True)
    if r is None:
        print("  %s: not cached, skipped" % k)
        continue

    aoi = gpd.read_file(p).to_crs(4326)
    c = aoi.geometry.union_all().centroid
    # 0.1 degrees is about 11 km -- enough for climate, not enough to find a farm.
    lat, lon = round(c.y, 1), round(c.x, 1)

    hist = (r.history.set_index("year") if r.history is not None
            else pd.DataFrame())
    phen = (r.phenology.set_index("year") if r.phenology is not None
            else pd.DataFrame())
    arm = (r.residue.set_index("year") if r.residue is not None
           else pd.DataFrame())
    cc = (r.covercrop.set_index("fall_year") if r.covercrop is not None
          else pd.DataFrame())
    adv = (r.advice.per_year.set_index("year")
           if r.advice is not None and r.advice.per_year is not None
           else pd.DataFrame())
    ser = r.series.copy()
    ser["year"] = pd.to_datetime(ser["date"]).dt.year

    for y in YEARS:
        row = {
            "field_key": k, "crop_year": y,
            "county": county.get(k, ""), "lat_0p1deg": lat, "lon_0p1deg": lon,
            "area_ha": round(float(r.area_ha), 2),
            "acres_reported": acres.get(k, ""),
            "boundary_verdict": "" if r.advice is None else r.advice.verdict,
            "boundary_flagged_ha": ("" if r.advice is None
                                    else round(float(r.advice.area_ha), 2)),
            "clear_obs_year": int((ser.year == y).sum()),
        }

        if y in hist.index:
            h = hist.loc[y]
            row.update({"cdl_crop": h.crop, "cdl_crop_pct": h.pct,
                        "cdl_n_classes": h.n_classes})
        if y in adv.index:
            row["cdl_noncrop_pct"] = round(float(adv.loc[y].noncrop_pct), 1)

        if y in phen.index:
            q = phen.loc[y]
            row.update({
                "planting_est": q.planting_est, "planting_lo": q.planting_lo,
                "planting_hi": q.planting_hi, "harvest_est": q.harvest_est,
                "harvest_lo": q.harvest_lo, "harvest_hi": q.harvest_hi,
                "season_days": q.season_days, "peak_ndvi": q.peak_ndvi,
                "peak_date": q.peak_date, "baseline_ndvi": q.baseline_ndvi,
                "amplitude": q.amplitude, "season_n_obs": q.n_obs,
                "season_confidence": q.confidence})

        # The winter *before* this crop.
        fy = y - 1
        if fy in cc.index:
            w = cc.loc[fy]
            row.update({
                "winter": w.winter, "winter_window_start": w.window_start,
                "winter_window_end": w.window_end, "winter_n_obs": w.n_obs,
                "winter_max_ndvi": w.max_ndvi, "winter_mean_ndvi": w.mean_ndvi,
                "winter_peak_date": w.peak_date, "winter_green_days": w.green_days,
                "cover_verdict": w.verdict, "cover_verdict_note": w.notes})

        if y in arm.index:
            a = arm.loc[y]
            row.update({
                "armor_window_start": a.window_start,
                "armor_window_end": a.window_end,
                "armor_window_source": a.window_source,
                "armor_n_obs": a.n_obs, "armor": a.armor,
                "armor_lo": a.armor_lo, "armor_hi": a.armor_hi,
                "f_pv_living": a.f_pv, "f_npv_residue": a.f_npv,
                "f_bs_bare": a.f_bs, "min_ndti": a.min_ndti,
                "armor_ndvi_med": a.ndvi_med, "armor_note": a.note})

        e = entered.get(k, {}).get(y, {})
        row.update({c: e.get(c, "") for c in [
            "entered_crop_id", "entered_planting", "entered_harvest",
            "entered_yield", "entered_yield_unit",
            "entered_tillage_passes_pre_plant", "entered_tillage_ops",
            "entered_cover_crop", "entered_cover_species_id",
            "entered_cover_planted", "entered_cover_terminated",
            "entered_cover_is_legume"]})
        # Three states, not two. "no" would read as a confirmed negative, and
        # it is not one: planting_cover appears only in the 2026 intervals, so
        # an earlier interval without one is a record that was never kept
        # rather than a field that had no cover crop. Scoring specificity off
        # this column is the mistake the wording is there to prevent.
        row["entered_cover_crop"] = row["entered_cover_crop"] or (
            "not_recorded" if e else "")
        rows.append(row)

df = pd.DataFrame(rows)

# How many fields in the cohort share this exact entered date in this year.
#
# This matters more than it looks. Entered planting and harvest take only two
# to four distinct values per year across 98 fields in six counties -- in 2025,
# 63 fields share 6 May and 34 share 25 May. Those are project or per-grower
# templates, not per-field observations. Comparing a satellite estimate against
# them measures the offset from a template, not per-field accuracy, and anyone
# computing a date error from this file needs to see that before they start.
for col in ("entered_planting", "entered_harvest", "entered_cover_planted"):
    counts = (df[df[col].astype(str) != ""]
              .groupby(["crop_year", col]).field_key.nunique()
              .rename("n").reset_index())
    df = df.merge(counts, on=["crop_year", col], how="left")
    df = df.rename(columns={"n": col + "_shared_by_n_fields"})
# Stable, readable column order: identity, boundary, CDL, season, winter,
# armor, then what the grower entered.
order = ["field_key", "crop_year", "county", "lat_0p1deg", "lon_0p1deg",
         "area_ha", "acres_reported", "boundary_verdict", "boundary_flagged_ha",
         "clear_obs_year", "cdl_crop", "cdl_crop_pct", "cdl_n_classes",
         "cdl_noncrop_pct",
         "planting_est", "planting_lo", "planting_hi", "harvest_est",
         "harvest_lo", "harvest_hi", "season_days", "peak_ndvi", "peak_date",
         "baseline_ndvi", "amplitude", "season_n_obs", "season_confidence",
         "winter", "winter_window_start", "winter_window_end", "winter_n_obs",
         "winter_max_ndvi", "winter_mean_ndvi", "winter_peak_date",
         "winter_green_days", "cover_verdict", "cover_verdict_note",
         "armor_window_start", "armor_window_end", "armor_window_source",
         "armor_n_obs", "armor", "armor_lo", "armor_hi", "f_pv_living",
         "f_npv_residue", "f_bs_bare", "min_ndti", "armor_ndvi_med",
         "armor_note",
         "entered_crop_id", "entered_planting", "entered_harvest",
         "entered_yield", "entered_yield_unit",
         "entered_tillage_passes_pre_plant", "entered_tillage_ops",
         "entered_cover_crop", "entered_cover_species_id",
         "entered_cover_planted", "entered_cover_terminated",
         "entered_cover_is_legume",
         "entered_planting_shared_by_n_fields",
         "entered_harvest_shared_by_n_fields",
         "entered_cover_planted_shared_by_n_fields"]
df = df.reindex(columns=[c for c in order if c in df.columns])
df.to_csv(OUT, index=False)

DEFS = [
 ("field_key", "id", "SHA1 of the boundary geometry, first 12 hex. One physical field."),
 ("crop_year", "year", "Cash crop harvest year. Rows are aligned to this."),
 ("county", "text", "County and state from the Fieldprint payload."),
 ("lat_0p1deg / lon_0p1deg", "degrees", "Boundary centroid rounded to 0.1 deg (~11 km). Deliberately coarse."),
 ("area_ha", "ha", "Area of the boundary as the pipeline measured it."),
 ("acres_reported", "acres", "Plantable acres as entered in Fieldprint."),
 ("boundary_verdict", "category", "single unit | trim | split. Whether the outline holds one management unit."),
 ("boundary_flagged_ha", "ha", "Area flagged as disagreeing with the rest of the boundary."),
 ("clear_obs_year", "count", "Cloud-free Sentinel-2 observations in that calendar year."),
 ("cdl_crop", "text", "Dominant USDA CDL class for the crop year."),
 ("cdl_crop_pct", "%", "Share of the boundary the dominant class covers. Under 75 is a weak boundary."),
 ("cdl_n_classes", "count", "Distinct CDL classes inside the boundary."),
 ("cdl_noncrop_pct", "%", "Share of the boundary CDL calls non-cropland."),
 ("planting_est / harvest_est", "date", "ESTIMATED from the NDVI curve. Never validated against a grower record."),
 ("planting_lo / hi, harvest_lo / hi", "date", "Uncertainty window, set by the gaps between clear images."),
 ("season_days", "days", "Harvest minus planting, both estimated."),
 ("peak_ndvi / peak_date", "index / date", "Highest fitted NDVI in the season and when."),
 ("baseline_ndvi / amplitude", "index", "Fitted floor and the rise above it."),
 ("season_n_obs", "count", "Clear observations the season fit used."),
 ("season_confidence", "category", "high | medium | low, with the reason when low."),
 ("winter", "text", "The off-season PRECEDING this crop year, e.g. 2025-26 on crop year 2026."),
 ("winter_window_start / end", "date", "Off-season window actually scored."),
 ("winter_n_obs", "count", "Clear observations inside that window. Below ~10 the verdict is weak."),
 ("winter_max_ndvi", "index", "Peak off-season NDVI. The threshold CC_GREEN_MIN = 0.30 acts on this."),
 ("winter_mean_ndvi", "index", "Mean off-season NDVI."),
 ("winter_green_days", "days", "Days the daily-interpolated curve sits above 0.30."),
 ("cover_verdict", "category", "likely | possible | green cover | none | winter cash crop | not detectable."),
 ("cover_verdict_note", "text", "Why the verdict is what it is."),
 ("armor_window_start / end", "date", "Pre-planting window: previous harvest to this planting."),
 ("armor_window_source", "category", "phenology | partial | fallback -- how many ends came from estimated dates."),
 ("armor_n_obs", "count", "Usable observations in the armor window. Under 3 gives no reading."),
 ("armor", "0-1", "1 minus bare soil. GROUND COVER, not tillage. Provisional and uncalibrated."),
 ("armor_lo / hi", "0-1", "Minimum and maximum across the window."),
 ("f_pv_living", "0-1", "Living green cover fraction."),
 ("f_npv_residue", "0-1", "Crop residue fraction. A terminated cover crop lands here, not in f_pv."),
 ("f_bs_bare", "0-1", "Bare soil fraction. The three fractions sum to 1."),
 ("min_ndti", "index", "Minimum NDTI across the window. Reported, not used as a headline."),
 ("armor_ndvi_med", "index", "Median NDVI inside the armor window."),
 ("armor_note", "text", "Blank when the reading is clean; otherwise why it is missing or qualified."),
 ("entered_crop_id", "id", "Fieldprint crop id for the cash crop."),
 ("entered_planting / harvest", "date", "Dates the grower entered. Compare against the _est columns."),
 ("entered_yield / unit", "number", "Reported yield."),
 ("entered_tillage_passes_pre_plant", "count", "Tillage activities dated on or before cash planting."),
 ("entered_tillage_ops", "ids", "Pipe-joined tillage_operation_ids. 95% of rows are the same pair."),
 ("entered_cover_crop", "yes/not_recorded/blank", "yes where a planting_cover activity exists. not_recorded means an interval covered the year but held no cover crop activity -- this is NOT a confirmed negative; planting_cover appears only in 2026 intervals across the whole archive. Blank means no interval at all. Do not compute specificity from this column."),
 ("entered_cover_species_id", "id", "Fieldprint cover crop id."),
 ("entered_cover_planted / terminated", "date", "Sowing and termination dates the grower entered."),
 ("entered_cover_is_legume", "bool", "As entered."),
 ("entered_planting_shared_by_n_fields", "count",
  "How many of the 98 fields carry this exact entered planting date this year. "
  "Typically 30-65: the dates are templates, not per-field observations. "
  "A date error computed against them measures offset from a template, not accuracy."),
 ("entered_harvest_shared_by_n_fields", "count", "Same, for harvest."),
 ("entered_cover_planted_shared_by_n_fields", "count",
  "Same, for cover crop sowing. More varied than the cash crop dates but still clustered."),
]
with open(DICT, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["column", "unit", "meaning"])
    w.writerows(DEFS)

print("\nrows            : %d  (%d fields x %d crop years)"
      % (len(df), df.field_key.nunique(), len(YEARS)))
print("columns         : %d" % df.shape[1])
print("with a CDL crop : %d" % df.cdl_crop.notna().sum())
print("with season est : %d" % df.planting_est.notna().sum())
print("with a verdict  : %d" % df.cover_verdict.notna().sum())
print("with armor      : %d" % df.armor.notna().sum())
print("entered cover=yes: %d" % (df.entered_cover_crop == "yes").sum())
print("\nwrote %s\n      %s" % (OUT.name, DICT.name))
