#!/usr/bin/env python
"""Run the pipeline for one field boundary and write CSVs.

    python run_field.py path/to/field.geojson
    python run_field.py field.geojson --years 2020 2026 --out results/iowa
    python run_field.py field.geojson --workers 12 --indices ndvi ndmi

First run for a field reads several hundred scenes and takes a few minutes.
Everything is cached under ``cache/``, so re-running is instant.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from fieldrs import analyze_field


def _fmt(df: pd.DataFrame | None, cols: list[str]) -> str:
    if df is None or len(df) == 0:
        return "  (none)"
    keep = [c for c in cols if c in df.columns]
    out = df[keep].copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return out.to_string(index=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boundary", help="GeoJSON, Shapefile, GeoPackage or KML")
    ap.add_argument("--years", nargs=2, type=int, metavar=("FROM", "TO"),
                    default=[2020, date.today().year])
    ap.add_argument("--indices", nargs="+", default=["ndvi"],
                    help="registered index names (default: ndvi)")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel scene reads (default: 8)")
    ap.add_argument("--out", default=None,
                    help="output directory (default: results/<boundary name>)")
    ap.add_argument("--source", choices=["sentinel2", "hls"], default="sentinel2",
                    help="imagery: sentinel2 (original, 10 m) or hls (Sentinel-2 + "
                         "Landsat 8/9 harmonised, 30 m, denser in time)")
    ap.add_argument("--residue", action="store_true",
                    help="also read the SWIR residue/tillage indices "
                         "(a second pass over the archive; uncalibrated)")
    ap.add_argument("--no-rain-check", action="store_true",
                    help="skip the gridMET rain-free adjustment of planting/harvest dates")
    ap.add_argument("--dry-mm", type=float, default=0.0,
                    help="max daily rain (mm) for a day to count as rain-free (default: 0)")
    ap.add_argument("--forecast-days", type=int, default=5, metavar="DAYS",
                    help="move a date earlier than its estimate by at most DAYS "
                         "(forecast horizon); beyond that, move after the weather "
                         "(default: 5; 0 = never earlier)")
    ap.add_argument("--heavy-mm", type=float, default=25.0, metavar="MM",
                    help="a day with at least MM of rain leaves the soil too wet "
                         "for the next --wet-days day(s) (default: 25 = 1 inch)")
    ap.add_argument("--wet-days", type=int, default=1, metavar="DAYS",
                    help="days not workable after a heavy rain (default: 1; 0 = off)")
    ap.add_argument("--wind-kmh", type=float, default=None, metavar="KMH",
                    help="also require gridMET daily-mean wind below KMH (e.g. 30, "
                         "about 20 mph); default: rain only")
    ap.add_argument("--only-cached", action="store_true",
                    help="exit rather than compute if results are not cached")
    ap.add_argument("--cdl-dir", default=None,
                    help="local CDL store (sets CDL_DIR), e.g. a directory of "
                         "NASS_<year>.tif CONUS mosaics -- see fieldrs/cdl_local.py")
    args = ap.parse_args(argv)
    if args.cdl_dir:
        os.environ["CDL_DIR"] = args.cdl_dir

    out_dir = Path(args.out) if args.out else Path("results") / Path(args.boundary).stem

    def progress(done: int, total: int, msg: str) -> None:
        pct = 100 * done / max(total, 1)
        print(f"\r  {msg} ({pct:.0f}%)", end="", flush=True)
        if done >= total:
            print()

    result = analyze_field(args.boundary, years=tuple(args.years),
                           residue=args.residue,
                           rain_free=not args.no_rain_check, dry_mm=args.dry_mm,
                           wind_max_kmh=args.wind_kmh,
                           forecast_days=args.forecast_days,
                           heavy_mm=args.heavy_mm, wet_days=args.wet_days,
                           source=args.source,
                           indices=args.indices, workers=args.workers,
                           only_cached=args.only_cached, progress=progress)
    if result is None:
        print("Not cached. Re-run without --only-cached to compute.")
        return 1

    print(f"\n{'=' * 72}")
    print(f"{Path(args.boundary).name}  |  {result.area_ha:.1f} ha  |  "
          f"{result.start} to {result.end}  |  {len(result.series)} observations")
    print("=" * 72)

    print("\nCROP ROTATION (USDA CDL)")
    print(_fmt(result.history, ["year", "crop", "pct", "n_classes",
                                "irrigated", "irrigated_pct", "irrigation_map",
                                "irrigated_maps"]))

    if result.advice is not None:
        print(f"\nBOUNDARY CHECK: {result.advice.verdict}")
        print(f"  {result.advice.headline}")
        print(f"  {result.advice.detail}")

    print("\nSEASON MARKERS (final dates checked against gridMET weather)")
    print(_fmt(result.phenology,
               ["year", "crop", "planting_est", "planting_date", "planting_shift_d",
                "harvest_est", "harvest_date", "harvest_shift_d", "season_days",
                "season_days_final",
                "peak_ndvi", "confidence"]))

    print("\nOFF-SEASON COVER")
    print(_fmt(result.covercrop,
               ["winter", "n_obs", "max_ndvi", "green_days", "verdict",
                "seeding_est", "seeding_date", "termination_est", "termination_date",
                "cover_days_final", "dates_confidence"]))

    written = result.write(out_dir)
    print(f"\nWrote {len(written)} files to {out_dir}/")
    for p in written:
        print(f"  {p.name}")

    print("\nNote: thresholds are literature-typical starting values, not "
          "calibrated against ground truth. See README.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
