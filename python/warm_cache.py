#!/usr/bin/env python
"""Pre-compute every boundary in the shared field library.

    python warm_cache.py
    python warm_cache.py --workers 12 --fields ../data/fields

Runs the full pipeline for each boundary so later calls are instant. Everything
lands in ``cache/``, keyed on field geometry plus the analysis window.

Re-run monthly: ``analysis_window()`` ends at the start of the current month, so
the cache stays valid for the rest of it and then needs pulling forward.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

from fieldrs import analyze_field, load_field, single_field
from fieldrs.cache import analysis_window


def default_fields_dir() -> Path:
    """The shared boundary library, whether run from the repo root or python/."""
    for c in (Path("data/fields"), Path("../data/fields")):
        if c.is_dir():
            return c
    raise FileNotFoundError("Could not find data/fields (tried ./ and ../).")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fields", default=None, help="directory of boundaries")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--years", nargs=2, type=int, default=[2020, date.today().year])
    ap.add_argument("--out", default="outputs", help="where to write the summary CSV")
    args = ap.parse_args(argv)

    fields_dir = Path(args.fields) if args.fields else default_fields_dir()
    files = sorted(fields_dir.glob("*.geojson"))
    if not files:
        print(f"No .geojson files in {fields_dir}")
        return 1

    start, end = analysis_window(args.years[0], args.years[1])
    print(f"\nWarming {len(files)} fields, window {start} -> {end}\n", flush=True)

    rows = []
    t_all = time.time()

    for p in files:
        print("-" * 70, flush=True)
        print(p.name, flush=True)
        t0 = time.time()
        try:
            # single_field: the same geometry the app analyses, so the cache key
            # matches what the app looks up (a dropped sliver changes the key).
            r = analyze_field(single_field(load_field(p)), years=tuple(args.years),
                              workers=args.workers, residue=True)
            crops = "/".join(dict.fromkeys(
                c for c in (r.history["crop"] if r.history is not None else [])
                if isinstance(c, str)))
            cover = 0
            if r.covercrop is not None:
                cover = int(r.covercrop["verdict"]
                            .str.contains("likely|small grain").sum())
            rows.append({
                "file": p.name,
                "area_ha": round(r.area_ha, 1),
                "obs": len(r.series),
                "seasons": 0 if r.phenology is None else len(r.phenology),
                "crops": crops,
                "boundary": "" if r.advice is None else r.advice.verdict,
                "cover_winters": cover,
                "mins": round((time.time() - t0) / 60, 1),
            })
        except Exception as exc:                          # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}", flush=True)
            rows.append({"file": p.name, "area_ha": None, "obs": None,
                         "seasons": None, "crops": None,
                         "boundary": f"ERROR: {exc}", "cover_winters": None,
                         "mins": round((time.time() - t0) / 60, 1)})
        print(f"  done in {rows[-1]['mins']:.1f} min", flush=True)

    out = pd.DataFrame(rows)
    print("\n" + "=" * 70 + "\nSUMMARY", flush=True)
    print(out.to_string(index=False), flush=True)

    cache = Path("cache")
    n_files = len(list(cache.glob("*.pkl"))) if cache.exists() else 0
    mb = sum(f.stat().st_size for f in cache.glob("*.pkl")) / 1e6 if cache.exists() else 0
    print(f"\nTotal {(time.time() - t_all) / 60:.1f} min. "
          f"Cache: {n_files} files, {mb:.1f} MB", flush=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / "demo_library_python.csv", index=False)
    print(f"Wrote {out_dir / 'demo_library_python.csv'}", flush=True)

    # Per-field failures are caught so one bad boundary does not abandon the
    # rest, but the exit code has to reflect them. This script once printed
    # "Total 0.0 min" and exited 0 after every field raised the same
    # NameError -- a warm that warmed nothing, indistinguishable from success.
    n_failed = sum(1 for r in rows if r["obs"] is None)
    if n_failed:
        print(f"\n{n_failed} of {len(rows)} fields FAILED -- cache is incomplete.",
              flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
