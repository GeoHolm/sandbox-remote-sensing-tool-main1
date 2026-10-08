#!/usr/bin/env python
"""Diff the Python port against the R reference implementation.

    # in r/:      Rscript export_r_reference.R
    # in python/: python warm_cache.py
    python compare_with_r.py

Both sides read only from their caches, so this is fast and cannot change what
it is comparing. Exits non-zero if anything disagrees beyond tolerance.

Tolerances reflect what the two implementations can legitimately differ on:
season dates by a day or two (the smoothers pick slightly different penalties),
observation counts by one scene (bounding-box rounding at the catalogue query).
Verdicts and crop names must match exactly -- those are decisions, not estimates.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

from fieldrs import analyze_field
from fieldrs.cache import analysis_window

DATE_TOL_DAYS = 3        # season markers
OBS_TOL = 2              # scenes
NDVI_TOL = 0.02          # peak NDVI
NDTI_TOL = 0.02          # residue indices, same reasoning
ARMOR_TOL = 0.03         # cover fractions are 0-1; 3 points is the tolerance


def _fields_dir() -> Path:
    for c in (Path("data/fields"), Path("../data/fields")):
        if c.is_dir():
            return c
    raise FileNotFoundError("Could not find data/fields.")


def _ref_dir() -> Path:
    for c in (Path("../r/outputs/r_reference"), Path("r/outputs/r_reference"),
              Path("outputs/r_reference")):
        if c.is_dir():
            return c
    raise FileNotFoundError(
        "No R reference found. Run `Rscript export_r_reference.R` in r/ first."
    )


def main() -> int:
    ref = _ref_dir()
    r_phen = pd.read_csv(ref / "phenology.csv", parse_dates=["planting_est", "harvest_est"])
    r_cc = pd.read_csv(ref / "covercrop.csv")
    r_adv = pd.read_csv(ref / "boundary.csv")
    res_path = ref / "soil_armor.csv"
    r_res = pd.read_csv(res_path) if res_path.exists() else None
    r_hist = pd.read_csv(ref / "cdl_history.csv")

    years = (2020, date.today().year)
    issues: list[str] = []
    rows: list[dict] = []

    for p in sorted(_fields_dir().glob("*.geojson")):
        name = p.stem
        res = analyze_field(p, years=years, only_cached=True,
                            residue=r_res is not None)
        if res is None and r_res is not None:
            # Residue is warmed separately; fall back so a half-warmed cache
            # still reports on everything else rather than going silent.
            res = analyze_field(p, years=years, only_cached=True)
        if res is None:
            issues.append(f"{name}: not cached in Python -- run warm_cache.py")
            continue

        rp = r_phen[r_phen["field"] == name]
        rc = r_cc[r_cc["field"] == name]
        ra = r_adv[r_adv["field"] == name]
        rh = r_hist[r_hist["field"] == name]
        if rp.empty and ra.empty:
            issues.append(f"{name}: missing from the R reference")
            continue

        rec = {"field": name}

        # --- observations -------------------------------------------------
        r_obs = int(rp["n_obs_total"].iloc[0]) if not rp.empty else None
        p_obs = len(res.series)
        rec["obs_R"], rec["obs_PY"] = r_obs, p_obs
        if r_obs is not None and abs(r_obs - p_obs) > OBS_TOL:
            issues.append(f"{name}: observations {r_obs} (R) vs {p_obs} (Py)")

        # --- boundary verdict ---------------------------------------------
        r_verdict = ra["verdict"].iloc[0] if not ra.empty else None
        p_verdict = res.advice.verdict if res.advice else None
        rec["boundary_R"], rec["boundary_PY"] = r_verdict, p_verdict
        if r_verdict != p_verdict:
            issues.append(f"{name}: boundary '{r_verdict}' (R) vs '{p_verdict}' (Py)")
        if not ra.empty and res.advice is not None:
            d = abs(float(ra["area_ha"].iloc[0]) - res.advice.area_ha)
            rec["flagged_dha"] = round(d, 2)
            if d > 0.5:
                issues.append(f"{name}: flagged area differs by {d:.2f} ha")

        # --- CDL crop names must match exactly ----------------------------
        if not rh.empty and res.history is not None:
            merged = rh.merge(res.history, on="year", suffixes=("_r", "_py"))
            bad = merged[merged["crop_r"] != merged["crop_py"]]
            rec["crop_mismatch"] = len(bad)
            for _, b in bad.iterrows():
                issues.append(f"{name} {int(b.year)}: crop '{b.crop_r}' (R) vs "
                              f"'{b.crop_py}' (Py)")

        # --- season markers -----------------------------------------------
        worst_plant = worst_harv = 0
        worst_ndvi = 0.0
        if not rp.empty and res.phenology is not None:
            m = rp.merge(res.phenology, on="year", suffixes=("_r", "_py"))
            for col, label in (("planting_est", "planting"), ("harvest_est", "harvest")):
                a = pd.to_datetime(m[f"{col}_r"], errors="coerce")
                b = pd.to_datetime(m[f"{col}_py"], errors="coerce")
                both = a.notna() & b.notna()
                if both.any():
                    dd = (a[both] - b[both]).dt.days.abs()
                    worst = int(dd.max())
                    if label == "planting":
                        worst_plant = worst
                    else:
                        worst_harv = worst
                    if worst > DATE_TOL_DAYS:
                        yr = int(m.loc[dd.idxmax(), "year"])
                        issues.append(f"{name} {yr}: {label} differs by {worst} days")
                # one side estimated a date and the other did not
                only = a.notna() ^ b.notna()
                for _, o in m[only].iterrows():
                    issues.append(f"{name} {int(o.year)}: {label} present in "
                                  f"{'R' if pd.notna(o[f'{col}_r']) else 'Py'} only")
            nd = (m["peak_ndvi_r"] - m["peak_ndvi_py"]).abs()
            worst_ndvi = float(nd.max())
            if worst_ndvi > NDVI_TOL:
                yr = int(m.loc[nd.idxmax(), "year"])
                issues.append(f"{name} {yr}: peak NDVI differs by {worst_ndvi:.3f}")
        rec["plant_dmax"] = worst_plant
        rec["harv_dmax"] = worst_harv
        rec["ndvi_dmax"] = round(worst_ndvi, 3)

        # --- cover crop verdicts ------------------------------------------
        mismatches = 0
        if not rc.empty and res.covercrop is not None:
            m = rc.merge(res.covercrop, on="winter", suffixes=("_r", "_py"))
            bad = m[m["verdict_r"] != m["verdict_py"]]
            mismatches = len(bad)
            for _, b in bad.iterrows():
                issues.append(f"{name} {b.winter}: cover '{b.verdict_r}' (R) vs "
                              f"'{b.verdict_py}' (Py)")
        rec["cover_mismatch"] = mismatches

        # --- residue indices ----------------------------------------------
        if r_res is not None and res.residue is not None:
            rr = r_res[r_res["field"] == name]
            if not rr.empty:
                m = rr.merge(res.residue, on="year", suffixes=("_r", "_py"))
                # n_bare drives whether a minimum is reported at all, so a
                # disagreement there is more serious than a small numeric one.
                nb = (m["n_obs_r"] - m["n_obs_py"]).abs()
                if (nb > OBS_TOL).any():
                    yr = int(m.loc[nb.idxmax(), "year"])
                    issues.append(f"{name} {yr}: armor observation count "
                                  f"{int(m.loc[nb.idxmax(), 'n_obs_r'])} (R) vs "
                                  f"{int(m.loc[nb.idxmax(), 'n_obs_py'])} (Py)")
                # The window the statistic was taken over, which until now was
                # never compared at all -- it was not in the R export. Both
                # sides compute it and a silent disagreement here would move
                # every number below without explaining any of them.
                #
                # window_source must match exactly: it is the flag saying
                # whether the window came from phenology, one end of it, or
                # neither, and METHODS.md tells a caller to report it next to
                # the figure. The dates get the season-marker tolerance rather
                # than equality, because the window ends at planting minus
                # three days and so inherits whatever planting disagreement
                # already exists -- which is reported separately.
                if "window_source_r" in m:
                    # fillna before comparing: a row with no window has no
                    # source on either side, and NA never equals NA, so the
                    # straight comparison reported every such row as a
                    # disagreement between two identical blanks.
                    ws = (m["window_source_r"].fillna("").astype(str)
                          .ne(m["window_source_py"].fillna("").astype(str)))
                    for _, o in m[ws].iterrows():
                        issues.append(
                            f"{name} {int(o.year)}: window source "
                            f"'{o.window_source_r}' (R) vs "
                            f"'{o.window_source_py}' (Py)")
                for col in ("window_start", "window_end"):
                    if f"{col}_r" not in m:
                        continue
                    a = pd.to_datetime(m[f"{col}_r"], errors="coerce")
                    b = pd.to_datetime(m[f"{col}_py"], errors="coerce")
                    both = a.notna() & b.notna()
                    if not both.any():
                        continue
                    dd = (a[both] - b[both]).abs().dt.days
                    if dd.max() > DATE_TOL_DAYS:
                        yr = int(m.loc[dd.idxmax(), "year"])
                        issues.append(f"{name} {yr}: {col} differs by "
                                      f"{int(dd.max())} days")

                # Every cover fraction, not just the headline -- two of them can
                # trade against each other and leave armor looking identical.
                worst = 0.0
                for col, tol in (("armor", ARMOR_TOL), ("f_pv", ARMOR_TOL),
                                 ("f_npv", ARMOR_TOL), ("f_bs", ARMOR_TOL),
                                 ("ndvi_med", ARMOR_TOL)):
                    a = pd.to_numeric(m[f"{col}_r"], errors="coerce")
                    b = pd.to_numeric(m[f"{col}_py"], errors="coerce")
                    both = a.notna() & b.notna()
                    if not both.any():
                        continue
                    d = (a[both] - b[both]).abs()
                    worst = max(worst, float(d.max()))
                    if d.max() > tol:
                        yr = int(m.loc[d.idxmax(), "year"])
                        issues.append(f"{name} {yr}: {col} differs by {d.max():.3f}")
                    only = a.notna() ^ b.notna()
                    for _, o in m[only].iterrows():
                        issues.append(f"{name} {int(o.year)}: {col} present in "
                                      f"{'R' if pd.notna(o[f'{col}_r']) else 'Py'} only")
                rec["armor_dmax"] = round(worst, 4)
        rows.append(rec)

    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 78)
    print("R vs PYTHON  (dmax = largest disagreement across seasons)")
    print("=" * 78)
    print(out.to_string(index=False))

    print("\n" + "-" * 78)
    if issues:
        print(f"{len(issues)} DISAGREEMENT(S):\n")
        for i in issues:
            print("  -", i)
        return 1
    print("No disagreements beyond tolerance "
          f"(dates +/-{DATE_TOL_DAYS}d, obs +/-{OBS_TOL}, peak NDVI +/-{NDVI_TOL}). "
          "Verdicts and crop names matched exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
