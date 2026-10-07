#!/usr/bin/env python
"""Put a boundary into the field library, end to end -- port of r/add_field.R.

    python add_field.py <boundary> --stem mitchell-ga --label "Georgia - Mitchell Co." \\
                                   --shows "conservation till with a cover crop"
    python add_field.py <boundary> ... --hls      # also read the HLS series
    python add_field.py --status                  # what is in the library, and warm?

Checks the boundary is one field (single_field), copies it into
data/fields/<stem>.geojson, records it in data/fields/library.csv, and warms
every cache the app reads -- Sentinel-2 series and season analysis, CDL,
soil armor, the data-availability catalogue, gridMET weather and irrigation --
so the field opens instantly in the app. Prints what to commit.

Re-running on an existing stem refreshes its caches; the boundary file and the
library entry are only replaced with --force. CDL clips for the R app are still
cut by r/make_cdl_clips.R.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

from fieldrs import analyze_field, load_field, single_field
from fieldrs.armor import armor_series
from fieldrs.catalog import catalog_availability
from fieldrs.cdl_local import use_local

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ROOT / "data" / "fields"
LIB = FIELDS / "library.csv"
META = Path(__file__).resolve().parent / "outputs" / "demo_library_python.csv"
CONUS = (-125.0, 24.0, -66.0, 50.0)


def read_manifest() -> pd.DataFrame:
    if not LIB.exists():
        return pd.DataFrame(columns=["stem", "label", "shows", "added"])
    return pd.read_csv(LIB, dtype=str).fillna("")


def write_manifest(m: pd.DataFrame) -> None:
    m.to_csv(LIB, index=False, quoting=csv.QUOTE_ALL)


def status() -> int:
    m = read_manifest()
    rows = []
    for f in sorted(FIELDS.glob("*.geojson")):
        aoi = single_field(load_field(f))
        r = analyze_field(aoi, only_cached=True, rain_free=False)
        a = armor_series(aoi, (2020, date.today().year), only_cached=True)
        rows.append({"stem": f.stem, "in library.csv": f.stem in set(m["stem"]),
                     "ha": round(aoi.attrs["area_ha"], 1),
                     "season analysis": "warm" if r is not None else "-",
                     "soil armor": "warm" if a is not None else "-"})
    print(pd.DataFrame(rows).to_string(index=False))
    missing = set(m["stem"]) - {f.stem for f in FIELDS.glob("*.geojson")}
    if missing:
        print(f"\nIn library.csv but no boundary file: {', '.join(sorted(missing))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boundary", nargs="?", help="GeoJSON, KML, GeoPackage or shapefile")
    ap.add_argument("--stem", help="file name in data/fields (default: from the boundary)")
    ap.add_argument("--label", default="", help="display name in the app")
    ap.add_argument("--shows", default="", help="what this field demonstrates")
    ap.add_argument("--years", nargs=2, type=int, default=[2020, date.today().year])
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--hls", action="store_true", help="also warm the HLS series")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing boundary file / library entry")
    ap.add_argument("--status", action="store_true", help="list the library and exit")
    args = ap.parse_args(argv)

    if args.status:
        return status()
    if not args.boundary:
        ap.error("a boundary file is required (or --status)")

    src = Path(args.boundary)
    stem = args.stem or src.stem.lower().replace(" ", "-")
    aoi = single_field(load_field(src))          # refuses two fields in one boundary
    b = aoi.to_crs(4326).total_bounds
    if not (CONUS[0] <= b[0] and b[2] <= CONUS[2] and CONUS[1] <= b[1] and b[3] <= CONUS[3]):
        print("Boundary is outside the conterminous US; CDL and gridMET do not cover it.")
        return 1
    print(f"{stem}: {aoi.attrs['area_ha']:.1f} ha"
          + (f", dropped {aoi.attrs['dropped']} sliver(s)" if aoi.attrs.get("dropped") else ""))

    dest = FIELDS / f"{stem}.geojson"
    if dest.exists() and not args.force:
        print(f"  {dest.name} exists -- keeping it (use --force to replace)")
        aoi = single_field(load_field(dest))
    else:
        aoi[["geometry"]].to_crs(4326).to_file(dest, driver="GeoJSON")
        print(f"  wrote {dest.relative_to(ROOT)}")

    m = read_manifest()
    if stem in set(m["stem"]) and not args.force:
        print("  already in library.csv -- keeping its entry (use --force to replace)")
    else:
        m = m[m["stem"] != stem]
        row = {"stem": stem, "label": args.label or stem.replace("-", " ").title(),
               "shows": args.shows, "added": date.today().isoformat()}
        write_manifest(pd.concat([m, pd.DataFrame([row])], ignore_index=True))
        print(f"  recorded in {LIB.relative_to(ROOT)}")

    if not use_local():
        print("  note: no local CDL store found -- CDL comes from CropScape")
    yrs = tuple(args.years)
    t = time.time()
    print("  warming: Sentinel-2 series, CDL, season analysis, weather, irrigation ...", flush=True)
    r = analyze_field(aoi, years=yrs, workers=args.workers)
    print(f"    {r.series['date'].nunique()} clear dates, "
          f"{0 if r.phenology is None else len(r.phenology)} seasons", flush=True)
    print("  warming: soil armor (shortwave series) ...", flush=True)
    armor_series(aoi, yrs, workers=args.workers)
    print("  warming: data availability catalogue ...", flush=True)
    try:
        catalog_availability(aoi, start=r.start, end=r.end)
    except Exception as exc:                          # noqa: BLE001
        print(f"    skipped: {exc}")
    if args.hls:
        print("  warming: HLS series ...", flush=True)
        from fieldrs.imagery import SOURCE_FIRST_YEAR
        analyze_field(aoi, years=(max(yrs[0], SOURCE_FIRST_YEAR["hls"]), yrs[1]),
                      workers=args.workers, rain_free=False, source="hls")

    crops = "/".join(dict.fromkeys(c for c in (r.history["crop"] if r.history is not None
                                                 else []) if isinstance(c, str)))
    meta = pd.read_csv(META) if META.exists() else pd.DataFrame()
    meta = meta[meta.get("file", pd.Series(dtype=str)) != dest.name] if len(meta) else meta
    new = {"file": dest.name, "area_ha": round(r.area_ha, 1), "obs": len(r.series),
           "seasons": 0 if r.phenology is None else len(r.phenology), "crops": crops,
           "boundary": "" if r.advice is None else r.advice.verdict,
           "cover_winters": 0 if r.covercrop is None else
           int(r.covercrop["verdict"].str.contains("likely|small grain").sum()),
           "mins": round((time.time() - t) / 60, 1)}
    meta = pd.concat([meta, pd.DataFrame([new])], ignore_index=True).sort_values("file")
    META.parent.mkdir(exist_ok=True)
    meta.to_csv(META, index=False)
    print(f"  done in {(time.time() - t) / 60:.1f} min; crops: {crops or '-'}")
    print(f"\nCommit: data/fields/{dest.name}, data/fields/library.csv, "
          f"python/outputs/{META.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
