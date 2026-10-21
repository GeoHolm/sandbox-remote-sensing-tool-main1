#!/usr/bin/env python3
"""Run the remote sensing pipeline over every FLASH boundary.

    python project-level-tests/run_flash.py [--years 2022 2026] [--workers 8]

Writes incrementally to project-FLASH/rs_covercrop.csv and rs_fields.csv, and
skips boundaries already present, so an interrupted run resumes rather than
starting over. Per-field failures are caught and recorded; one bad boundary
must not abandon the other ninety-seven.
"""
import argparse
import csv
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.stdout.reconfigure(encoding="utf-8")

from fieldrs import analyze_field  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJ = HERE / "project-FLASH"
CC_OUT = PROJ / "rs_covercrop.csv"
FLD_OUT = PROJ / "rs_fields.csv"

CC_COLS = ["key", "winter", "fall_year", "window_start", "window_end", "n_obs",
           "max_ndvi", "mean_ndvi", "peak_date", "green_days", "verdict", "notes"]
FLD_COLS = ["key", "status", "area_ha", "obs", "seasons", "winters", "crops",
            "boundary_verdict", "minutes", "error"]


def done_keys():
    if not FLD_OUT.exists():
        return set()
    with open(FLD_OUT, encoding="utf-8") as fh:
        return {r["key"] for r in csv.DictReader(fh)}


def append(path, cols, rows):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs=2, type=int, default=[2022, 2026])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    files = sorted((PROJ / "boundaries").glob("*.geojson"))
    skip = done_keys()
    todo = [p for p in files if p.stem not in skip]
    print(f"{len(files)} boundaries, {len(skip)} already done, {len(todo)} to run",
          flush=True)
    print(f"window {a.years[0]}-{a.years[1]}, {a.workers} workers\n", flush=True)

    t_all = time.time()
    failed = 0
    for i, p in enumerate(todo, 1):
        t0 = time.time()
        print("-" * 70, flush=True)
        print(f"[{i}/{len(todo)}] {p.stem}", flush=True)
        try:
            r = analyze_field(p, years=tuple(a.years), workers=a.workers)
            mins = (time.time() - t0) / 60
            cc = r.covercrop
            if cc is not None and len(cc):
                rows = []
                for _, o in cc.iterrows():
                    d = {c: o.get(c) for c in CC_COLS if c in cc.columns}
                    d["key"] = p.stem
                    rows.append(d)
                append(CC_OUT, CC_COLS, rows)
            crops = ""
            if r.history is not None and len(r.history):
                crops = "/".join(dict.fromkeys(
                    str(c) for c in r.history["crop"] if isinstance(c, str)))
            append(FLD_OUT, FLD_COLS, [{
                "key": p.stem, "status": "ok",
                "area_ha": round(r.area_ha, 2),
                "obs": len(r.series),
                "seasons": 0 if r.phenology is None else len(r.phenology),
                "winters": 0 if cc is None else len(cc),
                "crops": crops,
                "boundary_verdict": "" if r.advice is None else r.advice.verdict,
                "minutes": round(mins, 2), "error": "",
            }])
            print(f"    ok  {mins:.1f} min, {len(r.series)} obs, "
                  f"{0 if cc is None else len(cc)} winters", flush=True)
        except Exception as exc:                            # noqa: BLE001
            failed += 1
            mins = (time.time() - t0) / 60
            msg = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
            append(FLD_OUT, FLD_COLS, [{
                "key": p.stem, "status": "FAILED", "area_ha": "", "obs": "",
                "seasons": "", "winters": "", "crops": "", "boundary_verdict": "",
                "minutes": round(mins, 2), "error": msg,
            }])
            print(f"    FAILED after {mins:.1f} min -- {msg}", flush=True)
            traceback.print_exc(limit=2)

    el = (time.time() - t_all) / 60
    print("\n" + "=" * 70, flush=True)
    print(f"Total {el:.1f} min. {len(todo) - failed} ok, {failed} failed.",
          flush=True)
    print(f"Wrote {CC_OUT.name} and {FLD_OUT.name}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
