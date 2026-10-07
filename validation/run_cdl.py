#!/usr/bin/env python
"""Score CDL's crop label against what the grower said they planted.

    python validation/run_cdl.py

CDL is an input to everything downstream -- phenology picks its crop lags from
it, and the cover crop logic keys off it -- so its error rate bounds every
other number in the validation. This is the cheapest check in the project: no
Sentinel-2 reads, one CropScape clip per surveyed field-year.

Writes validation/cdl.csv, one row per field-year. Resumable: rows already in
the file are skipped, so an interrupted run picks up where it stopped.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))

from fieldrs.cropland import cdl_stack, cdl_summary  # noqa: E402

OUT = HERE / "cdl.csv"


def main() -> int:
    truth = pd.read_csv(HERE / "truth.csv")
    done = set()
    if OUT.exists():
        done = set(pd.read_csv(OUT)["key"])
        print(f"resuming: {len(done)} rows already scored")

    todo = truth[~truth["key"].isin(done)]
    # One stack per field covering only the years that field was surveyed.
    # The boundaries were checked identical across a field's repeat years.
    by_field = list(todo.groupby("field_id"))
    print(f"{len(todo)} field-years across {len(by_field)} fields\n", flush=True)

    rows, t0 = [], time.time()
    for i, (fid, grp) in enumerate(by_field, 1):
        years = sorted(grp["year"].unique())
        aoi = gpd.read_file(HERE / "boundaries" / f"{grp['key'].iloc[0]}.geojson")
        try:
            stack = cdl_stack(aoi, years)
        except Exception as exc:                              # noqa: BLE001
            print(f"  {fid}: FAILED {type(exc).__name__}: {exc}", flush=True)
            continue

        for r in grp.itertuples():
            if r.year not in stack.years:
                continue
            s = cdl_summary(stack.year(r.year), stack.pixel_ha)
            # How much of the field CDL calls the grower's crop, whether or not
            # it is the dominant class. A field at 45% cotton / 47% peanuts is
            # a different kind of wrong from one at 3%.
            hit = s.loc[s["crop"] == r.crop, "pct"]
            rows.append({
                "key": r.key, "field_id": fid, "year": r.year,
                "survey_crop": r.crop,
                "cdl_crop": s["crop"].iloc[0],
                "cdl_pct": float(s["pct"].iloc[0]),
                "cdl_2nd": s["crop"].iloc[1] if len(s) > 1 else None,
                "cdl_2nd_pct": float(s["pct"].iloc[1]) if len(s) > 1 else 0.0,
                "survey_crop_pct": float(hit.iloc[0]) if len(hit) else 0.0,
                "n_classes": int(len(s)),
                "n_pixels": int(s["n_pixels"].sum()),
            })

        if i % 10 == 0 or i == len(by_field):
            el = (time.time() - t0) / 60
            print(f"  {i}/{len(by_field)} fields, {len(rows)} rows, "
                  f"{el:.1f} min elapsed", flush=True)
            _flush(rows)

    _flush(rows)
    total = len(pd.read_csv(OUT)) if OUT.exists() else 0
    print(f"\n{total} of {len(truth)} field-years scored -> {OUT}")
    return 0 if total else 1


def _flush(rows: list[dict]) -> None:
    """Append and clear, so a crash costs at most the last ten fields."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
    rows.clear()


if __name__ == "__main__":
    sys.exit(main())
