#!/usr/bin/env python3
"""Soil armor pass over the FLASH boundaries.

    python project-level-tests/run_flash_armor.py [--years 2022 2026]

A second read of the archive on the shortwave bands, so it costs roughly twice
what the NDVI pass did. Writes incrementally to rs_armor.csv and skips
boundaries already present, so an interrupted run resumes.

Soil armor is a COVER metric -- the share of ground covered by anything, living
or residue. It is not a tillage metric. Validation against 347 farmer-reported
field-years showed its apparent tillage signal running almost entirely through
cover crop adoption.
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

PROJ = Path(__file__).resolve().parent / "project-FLASH"
OUT = PROJ / "rs_armor.csv"
STATUS = PROJ / "rs_armor_status.csv"

COLS = ["key", "year", "window_start", "window_end", "window_source", "n_obs",
        "armor", "armor_lo", "armor_hi", "f_pv", "f_npv", "f_bs", "min_ndti",
        "ndvi_med", "note"]
SCOLS = ["key", "status", "years_with_armor", "minutes", "error"]


def done():
    if not STATUS.exists():
        return set()
    with open(STATUS, encoding="utf-8") as fh:
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
    skip = done()
    todo = [p for p in files if p.stem not in skip]
    print(f"{len(files)} boundaries, {len(skip)} done, {len(todo)} to run",
          flush=True)
    t_all = time.time()
    failed = 0

    for i, p in enumerate(todo, 1):
        t0 = time.time()
        print("-" * 68, flush=True)
        print(f"[{i}/{len(todo)}] {p.stem}", flush=True)
        try:
            r = analyze_field(p, years=tuple(a.years), workers=a.workers,
                              residue=True)
            mins = (time.time() - t0) / 60
            res = r.residue
            n_ok = 0
            if res is not None and len(res):
                rows = []
                for _, o in res.iterrows():
                    d = {c: o.get(c) for c in COLS if c in res.columns}
                    d["key"] = p.stem
                    rows.append(d)
                append(OUT, COLS, rows)
                n_ok = int(res["armor"].notna().sum())
            append(STATUS, SCOLS, [{"key": p.stem, "status": "ok",
                                    "years_with_armor": n_ok,
                                    "minutes": round(mins, 2), "error": ""}])
            print(f"    ok  {mins:.1f} min, {n_ok} year(s) with a reading",
                  flush=True)
        except Exception as exc:                            # noqa: BLE001
            failed += 1
            mins = (time.time() - t0) / 60
            msg = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
            append(STATUS, SCOLS, [{"key": p.stem, "status": "FAILED",
                                    "years_with_armor": "",
                                    "minutes": round(mins, 2), "error": msg}])
            print(f"    FAILED after {mins:.1f} min -- {msg}", flush=True)
            traceback.print_exc(limit=2)

    print("\n" + "=" * 68, flush=True)
    print(f"Total {(time.time() - t_all) / 60:.1f} min. "
          f"{len(todo) - failed} ok, {failed} failed.", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
