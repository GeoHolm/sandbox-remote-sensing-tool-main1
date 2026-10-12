"""Sentinel-1 prototype: radar-bracketed planting and harvest for one field.

    python run_s1_prototype.py ../data/fields/example_field.geojson --from 2018

Uses the field's cached NDVI pipeline for the same start year; --compute runs
it first when it is not cached (a few minutes for a cold field). Writes, per
start year Y:
outputs/<stem>_s1_<Y>_events.csv (radar searched beyond the NDVI windows),
outputs/<stem>_s1_<Y>_refined.csv (NDVI windows narrowed by radar and weather)
and outputs/<stem>_s1_<Y>.png. The app tabs pick the chart matching the
sidebar's start year. See fieldrs/sar.py for
what the numbers mean and how far to trust them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fieldrs import analyze_field, viz
from fieldrs.sar import s1_analysis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("field")
    ap.add_argument("--from", dest="y_from", type=int, default=2020)
    ap.add_argument("--compute", action="store_true",
                    help="run the NDVI pipeline if it is not cached for this start year")
    args = ap.parse_args()

    stem = Path(args.field).stem
    r = analyze_field(args.field, years=(args.y_from, None), only_cached=True)
    if r is None and args.compute:
        print(f"NDVI pipeline not cached for {stem} from {args.y_from}; computing...",
              flush=True)
        r = analyze_field(args.field, years=(args.y_from, None))
    if r is None:
        raise SystemExit(f"No cached NDVI pipeline for {stem} from {args.y_from}. "
                         "Run it in the app with that start year, or pass --compute.")
    tag = f"{stem}_s1_{args.y_from}"
    res = s1_analysis(r.aoi, r)
    if res is None:
        raise SystemExit("No Sentinel-1 acquisitions over this field.")
    s1, ctx, weather, ndvi = res["s1"], res["ctx"], res["weather"], res["ndvi"]
    events, refined, cuts = res["events"], res["refined"], res["cuts"]

    out = Path(__file__).resolve().parent / "outputs"
    out.mkdir(exist_ok=True)
    events.to_csv(out / f"{tag}_events.csv", index=False)
    refined.to_csv(out / f"{tag}_refined.csv", index=False)
    if len(cuts):
        cuts.to_csv(out / f"{tag}_cuts.csv", index=False)
    fig = viz.plot_s1(ctx, weather, ndvi, r.phenology, events, refined,
                      f"{stem}: Sentinel-1 backscatter against NDVI phenology, "
                      f"from {args.y_from}", cuts=cuts)
    fig.savefig(out / f"{tag}.png", dpi=90)
    plt.close(fig)

    print(f"{len(s1)} acquisitions, orbits {sorted(s1['orbit'].unique())}")
    print("moisture fit per orbit:", ctx.attrs.get("moisture_fit"))
    show = events.copy()
    for c in ("ndvi_lo", "ndvi_date", "ndvi_hi", "s1_from", "s1_to"):
        show[c] = pd.to_datetime(show[c]).dt.strftime("%m-%d")
    print(show.drop(columns=["signal"]).to_string(index=False))
    for ev in ("planting", "harvest"):
        e = events[(events["event"] == ev) & events["in_ndvi_window"].notna()]
        print(f"{ev}: radar interval inside NDVI window in "
              f"{int(e['in_ndvi_window'].sum())} of {len(e)} seasons")
    print("\nNDVI windows narrowed inside (agreement is by construction here):")
    print("noise SD per interval, dB:", refined.attrs.get("noise_sd_db"))
    show = refined.copy()
    for c in ("ndvi_lo", "ndvi_hi", "s1_from", "s1_to", "refined_lo", "refined_hi"):
        show[c] = pd.to_datetime(show[c]).dt.strftime("%m-%d")
    print(show.drop(columns=["note"]).to_string(index=False))
    for ev in ("planting", "harvest"):
        e = refined[refined["event"] == ev]
        rw = e[e["basis"] == "radar + weather"]
        msg = (f"median span {int(rw['ndvi_days'].median())} -> "
               f"{int(rw['span_days'].median())} days" if len(rw) else "no narrowing")
        print(f"{ev}: radar supports a narrowing in {len(rw)} of {len(e)} seasons "
              f"({msg}); {int(e['conflict'].sum())} conflict(s)")
    print(f"wrote {tag}_events.csv, {tag}_refined.csv and {tag}.png in {out}")


if __name__ == "__main__":
    main()
