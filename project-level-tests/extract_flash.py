#!/usr/bin/env python3
"""Pull the FLASH Fieldprint payloads apart into something the pipeline can run.

    python project-level-tests/extract_flash.py

Writes, next to the archive:
  fields.csv        one row per distinct boundary
  cover_truth.csv   one row per (boundary, winter) the grower reported on
  boundaries/*.geojson

WHAT COUNTS AS A FIELD
A Fieldprint payload is one field-year, and the same physical field appears
once per crop year under a different numeric id -- Home Farm is 174009 in 2025
and 174008 in 2026. Keying on that id would run the pipeline twice over
identical ground and then report the two runs as independent agreement.
Boundaries are therefore deduplicated on the geometry itself.

WHAT COUNTS AS A REPORTED COVER CROP
A `planting_cover` activity inside a crop interval, carrying its own planting
and termination dates. The planting date decides the winter: sown in autumn of
year Y, it belongs to winter Y/Y+1, which is `fall_year = Y` in the pipeline's
terms.

Absence is the harder half. No `planting_cover` in an interval means the grower
did not report one *for that interval*, which is a real negative -- but only
for winters an interval actually covers. A winter with no interval on either
side is silence, not a negative, and is written out as such rather than being
counted as "no cover crop".
"""
import hashlib
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ZIP = next((HERE / "project-FLASH" / "Fieldprint-payloads").glob("*.zip"))
OUT = HERE / "project-FLASH"
BND = OUT / "boundaries"
BND.mkdir(parents=True, exist_ok=True)

CROPS = {"10401": "Corn (grain)", "10402": "Corn (silage)", "11101": "Soybeans",
         "11303": "Wheat", "10101": "Barley", "20781": "Cover crop mix",
         "40141": "Alfalfa", "40061": "Hay", "20838": "Rye"}


def geom_key(g):
    """Stable id for a geometry, so one field is one field."""
    return hashlib.sha1(
        json.dumps(g, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]


z = zipfile.ZipFile(ZIP)
payloads = sorted(n for n in z.namelist() if n.endswith("API Payload.json"))

fields = {}                                   # geom key -> field record
reported = defaultdict(dict)                  # geom key -> fall_year -> record
intervals = defaultdict(set)                  # geom key -> harvest years seen

for n in payloads:
    d = json.loads(z.read(n))
    f = d["field"]
    k = geom_key(f["geometry"])
    stem = n.rsplit(" - API Payload.json", 1)[0]
    parts = [p.strip() for p in stem.split(" - ")]
    fid = parts[1] if len(parts) > 1 else ""

    rec = fields.setdefault(k, {
        "key": k, "field_name": f.get("field_name", ""),
        "location": f.get("location", ""),
        "acres": round(f.get("plantable_acres", {}).get("value", float("nan")), 2),
        "fieldprint_ids": set(), "payloads": 0,
    })
    rec["fieldprint_ids"].add(fid)
    rec["payloads"] += 1

    if not (BND / f"{k}.geojson").exists():
        (BND / f"{k}.geojson").write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature",
                          "properties": {"field_id": k,
                                         "field_name": rec["field_name"]},
                          "geometry": f["geometry"]}],
        }), encoding="utf-8")

    for ci in d.get("crop_intervals", []):
        hy = int(ci["harvest_year"])
        intervals[k].add(hy)
        acts = ci.get("activities", [])
        cash = [a for a in acts if a["type"] == "planting_cash"]
        harv = [a for a in acts if a["type"] == "harvest"]
        till = [a for a in acts if a["type"] == "tillage"]

        # The winter *before* this cash crop: autumn of hy-1 into spring hy.
        row = reported[k].setdefault(hy - 1, {
            "key": k, "fall_year": hy - 1, "winter": f"{hy - 1}-{str(hy)[2:]}",
            "reported": "no", "cover_crop_id": "", "planted": "", "terminated": "",
            "next_crop": CROPS.get(ci["crop_id"], ci["crop_id"]),
            "next_crop_planted": cash[0]["date"] if cash else "",
            "tillage_passes_before_planting": sum(
                1 for a in till if cash and a["date"] <= cash[0]["date"]),
        })
        for a in acts:
            if a["type"] != "planting_cover":
                continue
            # Belongs to the winter its planting date falls into.
            y = int(a["date"][:4])
            fy = y if int(a["date"][5:7]) >= 7 else y - 1
            r = reported[k].setdefault(fy, {
                "key": k, "fall_year": fy, "winter": f"{fy}-{str(fy + 1)[2:]}",
                "reported": "no", "cover_crop_id": "", "planted": "",
                "terminated": "", "next_crop": "", "next_crop_planted": "",
                "tillage_passes_before_planting": "",
            })
            r["reported"] = "yes"
            r["cover_crop_id"] = a["inputs"].get("cover_crop_id", "")
            r["planted"] = a["date"]
            r["terminated"] = a["inputs"].get("termination_date", "")

        if harv:
            row["prev_crop_harvested"] = harv[0]["date"]

# A winter is only a negative if an interval actually spanned it.
rows = []
for k, byyear in reported.items():
    for fy, r in byyear.items():
        r["covered_by_interval"] = "yes" if (fy + 1) in intervals[k] else "no"
        rows.append(r)

import csv

with open(OUT / "cover_truth.csv", "w", newline="", encoding="utf-8") as fh:
    cols = ["key", "fall_year", "winter", "reported", "covered_by_interval",
            "cover_crop_id", "planted", "terminated", "next_crop",
            "next_crop_planted", "prev_crop_harvested",
            "tillage_passes_before_planting"]
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in sorted(rows, key=lambda r: (r["key"], r["fall_year"])):
        w.writerow(r)

with open(OUT / "fields.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["key", "field_name", "location", "acres", "payloads",
                "fieldprint_ids", "interval_years"])
    for k, r in sorted(fields.items(), key=lambda kv: kv[1]["field_name"]):
        w.writerow([k, r["field_name"], r["location"], r["acres"], r["payloads"],
                    " ".join(sorted(r["fieldprint_ids"])),
                    " ".join(str(y) for y in sorted(intervals[k]))])

print("payloads              :", len(payloads))
print("distinct boundaries   :", len(fields))
print("boundary files written:", len(list(BND.glob('*.geojson'))))
print("winters with a record :", len(rows))
rep = sum(1 for r in rows if r["reported"] == "yes")
cov = sum(1 for r in rows if r["covered_by_interval"] == "yes")
print("  reported cover crop :", rep)
print("  spanned by interval :", cov)
print("acres: min %.0f  median %.0f  max %.0f"
      % tuple(__import__("statistics").quantiles(
          [f["acres"] for f in fields.values()], n=2) * 0 +
          [min(f["acres"] for f in fields.values()),
           __import__("statistics").median([f["acres"] for f in fields.values()]),
           max(f["acres"] for f in fields.values())]))
