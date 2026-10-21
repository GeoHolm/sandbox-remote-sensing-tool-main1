#!/usr/bin/env python3
"""Run the pipeline over a focus field and its cohort.

    python project-level-tests/run_cohort.py <project-dir> [--years 2022 2026]

One pass per field with residue=True, which returns the cover-crop verdicts
and the soil armor readings together rather than reading the archive twice.

Writes incrementally and skips any field already in status.csv, so the run
resumes after an interruption. That matters here: 101 fields is a few hours,
and the shortwave read is the expensive half.

Soil armor is a COVER metric -- the share of ground covered by anything,
living or residue. It is not a tillage metric. Validation against 347
farmer-reported field-years showed its apparent tillage signal running
almost entirely through cover crop adoption.
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

ARMOR = ["fid", "year", "window_start", "window_end", "window_source", "n_obs",
         "armor", "armor_lo", "armor_hi", "f_pv", "f_npv", "f_bs", "min_ndti",
         "ndvi_med", "note"]
COVER = ["fid", "winter", "n_obs", "max_ndvi", "mean_ndvi", "green_days",
         "verdict", "notes"]
PHEN = ["fid", "year", "crop", "planting_est", "harvest_est", "season_days",
        "peak_ndvi", "n_obs", "confidence"]
HIST = ["fid", "year", "crop", "pct", "is_crop", "n_classes"]
FIELD = ["fid", "area_ha", "acres", "clear_obs", "boundary_verdict",
         "cdl_mean_purity_pct", "minutes"]
SCOLS = ["fid", "status", "clear_obs", "armor_years", "cover_winters",
         "minutes", "error"]

OUTS = {"armor.csv": ARMOR, "covercrop.csv": COVER, "phenology.csv": PHEN,
        "history.csv": HIST, "fields.csv": FIELD}


def done(STATUS):
    if not STATUS.exists():
        return set()
    with open(STATUS, encoding="utf-8") as fh:
        return {r["fid"] for r in csv.DictReader(fh)}


def append(PROJ, name, cols, rows):
    path = PROJ / name
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def frame_rows(df, fid, cols):
    if df is None or not len(df):
        return []
    out = []
    for _, o in df.iterrows():
        d = {c: o.get(c) for c in cols if c in df.columns}
        d["fid"] = fid
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", help="project directory, e.g. champaign-il")
    ap.add_argument("--years", nargs=2, type=int, default=[2022, 2026])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    PROJ = HERE / a.proj
    STATUS = PROJ / "status.csv"

    files = sorted((PROJ / "boundaries").glob("*.geojson"))
    # focus first, so a run cut short still has the field the study is about
    files.sort(key=lambda p: (p.stem != "focus", p.stem))
    skip = done(STATUS)
    todo = [p for p in files if p.stem not in skip]
    print("%d boundaries, %d done, %d to run  (years %d-%d)"
          % (len(files), len(skip), len(todo), *a.years), flush=True)

    t_all = time.time()
    failed = 0
    for i, p in enumerate(todo, 1):
        fid = p.stem
        t0 = time.time()
        print("-" * 68, flush=True)
        print("[%d/%d] %s" % (i, len(todo), fid), flush=True)
        try:
            r = analyze_field(p, years=tuple(a.years), workers=a.workers,
                              residue=True)
            mins = (time.time() - t0) / 60

            append(PROJ, "armor.csv", ARMOR, frame_rows(r.residue, fid, ARMOR))
            append(PROJ, "covercrop.csv", COVER, frame_rows(r.covercrop, fid, COVER))
            append(PROJ, "phenology.csv", PHEN, frame_rows(r.phenology, fid, PHEN))
            append(PROJ, "history.csv", HIST, frame_rows(r.history, fid, HIST))
            append(PROJ, "fields.csv", FIELD, [{
                "fid": fid, "area_ha": round(r.area_ha, 2),
                "acres": round(r.area_ha * 2.47105, 1),
                "clear_obs": len(r.series),
                "boundary_verdict": "" if r.advice is None else r.advice.verdict,
                "cdl_mean_purity_pct": ("" if r.advice is None else
                                        round(r.advice.per_year.pct.mean(), 1)),
                "minutes": round(mins, 2)}])

            n_arm = (0 if r.residue is None or not len(r.residue)
                     else int(r.residue["armor"].notna().sum()))
            n_cov = 0 if r.covercrop is None else len(r.covercrop)
            append(PROJ, "status.csv", SCOLS, [{
                "fid": fid, "status": "ok", "clear_obs": len(r.series),
                "armor_years": n_arm, "cover_winters": n_cov,
                "minutes": round(mins, 2), "error": ""}])
            print("    ok  %.1f min, %d clear obs, %d armor year(s), "
                  "%d winter(s)" % (mins, len(r.series), n_arm, n_cov),
                  flush=True)
        except Exception as exc:                            # noqa: BLE001
            failed += 1
            mins = (time.time() - t0) / 60
            msg = ("%s: %s" % (type(exc).__name__, exc)).splitlines()[0][:300]
            append(PROJ, "status.csv", SCOLS, [{
                "fid": fid, "status": "FAILED", "clear_obs": "",
                "armor_years": "", "cover_winters": "",
                "minutes": round(mins, 2), "error": msg}])
            print("    FAILED after %.1f min -- %s" % (mins, msg), flush=True)
            traceback.print_exc(limit=2)

        el = (time.time() - t_all) / 60
        if i < len(todo):
            print("    %.0f min elapsed, ~%.0f min left"
                  % (el, el / i * (len(todo) - i)), flush=True)

    print("=" * 68, flush=True)
    print("done: %d run, %d failed, %.0f min total"
          % (len(todo), failed, (time.time() - t_all) / 60), flush=True)


if __name__ == "__main__":
    main()
