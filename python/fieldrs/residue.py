"""Crop residue and tillage intensity from SWIR indices.

WHAT THE SIGNAL IS
Crop residue and bare soil are both bright in the shortwave infrared, but
residue contains cellulose and lignin, which absorb near 2100 nm. NDTI --
(SWIR16 - SWIR22) / (SWIR16 + SWIR22) -- picks up the resulting slope
difference, so a field left in heavy residue reads higher than one that has
been ploughed clean.

WHY THIS MODULE REPORTS INDICES AND NOT A TILLAGE CLASS
Two things measured on this field library, not taken from the literature:

1. Soil moisture moves NDTI more than tillage does. On the Iowa field,
   18 and 20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 -- a
   four-fold swing from rain, two days apart, with no change in residue. A
   single date is not usable. That is why everything here is computed over a
   window, and why the minimum is reported alongside the median.
2. NDTI does not separate residue from green vegetation, because a green
   canopy absorbs strongly in the SWIR too. The Maryland cover-cropped field
   reads NDTI 0.15-0.24 in spring on green cover, not residue. Dates greener
   than RESIDUE_GREEN_MAX are therefore screened out and counted separately.

Published field-level accuracy for multispectral tillage classification is
roughly 73-80%, against >90% for hyperspectral CAI, which Sentinel-2 cannot
compute. Calibrating against residue line-transect measurements is what would
turn any of this into a class. Until then: numbers, not verdicts.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .extract import extract_field_series
from .phenology import residue_window

# Above this NDVI the surface is green cover, and NDTI is reading canopy rather
# than residue. Same threshold the cover crop module calls "sustained green".
RESIDUE_GREEN_MAX = 0.30

# Fewer clear, non-green observations than this and a minimum is just the
# noisiest of very few numbers.
RESIDUE_MIN_OBS = 3

# The window the warmed series covers. Wider than any single residue window so
# that one extraction serves every year, and fixed rather than derived from
# phenology so the cache key cannot move when a planting date shifts by a day.
RESIDUE_SPAN = ("03-01", "06-30")

RESIDUE_INDICES = ("ndvi", "ndti", "ndsvi", "ndi7")

# --- provisional reference bands ---------------------------------------------
# Breakpoints for reading min_ndti. The R app draws them; nothing writes them
# into an output table. They come from this library's own distribution across
# 64 seasons -- p33 and p75, rounded -- and express rank within these eleven
# fields. They are not crop residue cover, and nothing converts them to one.
#
# What replaces them: line-transect residue on 30-50 fields spanning the range,
# fitted as CRC ~ min_ndti and inverted at the CTIC class boundaries
# (conventional <15% cover, reduced 15-30%, conservation >30%). Published
# minNDTI regressions reach R2 ~ 0.89 with RMSD ~ 10.6 points of cover --
# comparable to the width of the reduced class -- so even calibrated, fields
# near a boundary will flip.
#
# Stratify before trusting one cut. Spring residue is the PREVIOUS crop's, and
# across this library median min_ndti runs Corn 0.078, Peanuts 0.067,
# Soybeans 0.066, Cotton 0.062, Rice 0.051, double-crop 0.014. A single global
# threshold would sort fields by crop rather than by management.
RESIDUE_BREAKS = (0.05, 0.09)
RESIDUE_BAND_LABELS = ("less residue", "intermediate", "more residue")


def residue_band(x: float | None) -> str | None:
    """Which provisional band a ``min_ndti`` value falls in.

    Here so the numbers live in code rather than only in a README. Not called
    by :func:`residue_summary` on purpose -- the tables report measurements,
    not classes, until there is ground truth behind the cuts.
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    lo, hi = RESIDUE_BREAKS
    return (RESIDUE_BAND_LABELS[0] if x < lo
            else RESIDUE_BAND_LABELS[1] if x < hi
            else RESIDUE_BAND_LABELS[2])


def residue_series(aoi, years: tuple[int, int] = (2020, None), *,
                   workers: int = 8, only_cached: bool = False,
                   refresh: bool = False, progress=None) -> pd.DataFrame | None:
    """Spring index series for the residue window, one extraction per year.

    Deliberately not the year-round series. NDTI is only interpretable on bare
    ground, so reading the whole year would quadruple the cost to throw most of
    it away -- and it would also mean re-reading every scene the NDVI series
    already covers, since the cache key includes the index list.

    Returns ``None`` if ``only_cached`` and any year is missing.
    """
    y_from, y_to = years
    y_to = y_to or date.today().year
    frames = []
    yrs = list(range(y_from, y_to + 1))
    for i, y in enumerate(yrs):
        df = extract_field_series(
            aoi, f"{y}-{RESIDUE_SPAN[0]}", f"{y}-{RESIDUE_SPAN[1]}",
            indices=RESIDUE_INDICES, workers=workers,
            only_cached=only_cached, refresh=refresh,
        )
        if df is None:
            if only_cached:
                return None
            continue
        frames.append(df)
        if progress is not None:
            progress(i + 1, len(yrs), f"Residue year {y}")
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["index", "date"]).reset_index(drop=True)


def residue_summary(ts: pd.DataFrame, phen: pd.DataFrame | None, year: int,
                    season: str = "spring") -> dict:
    """Residue indices over one season's pre-planting window.

    ``min_ndti`` is the headline number: the minimum across the window is the
    statistic the minNDTI literature validates, because a single date is at the
    mercy of whatever the soil moisture was that morning.

    Always returns a row, including for years with nothing to report. Returning
    ``None`` for those made the app's residue table silently shorter than its
    summary table for the same field, and "this year is absent" is
    indistinguishable from "this year was never computed". The reason belongs
    in the row, in ``note``.
    """
    def _row(w=None, n_obs=0, n_bare=0, n_green=0, ndvi_max=None, **kw) -> dict:
        base = {
            "year": int(year), "season": season,
            "window_start": None if w is None else w["start"],
            "window_end": None if w is None else w["end"],
            "window_source": None if w is None else w["source"],
            "n_obs": n_obs, "n_bare": n_bare, "n_green": n_green,
            "ndvi_max": ndvi_max,
        }
        fill = {"min_ndti": None, "median_ndti": None, "max_ndti": None,
                "min_ndti_date": None, "median_ndsvi": None,
                "median_ndi7": None, "note": None}
        fill.update(kw)
        return {**base, **fill}

    w = residue_window(phen, year, season)
    if w is None:
        return _row(note=(
            "no window: planting falls at or before the start of the window, "
            "so there is no pre-planting period to measure. Common on fields "
            "that go in during the first days of March."))

    d = ts[(ts["date"] >= w["start"]) & (ts["date"] <= w["end"])]
    wide = pd.DataFrame()
    if not d.empty:
        x = d.pivot_table(index="date", values="mean", columns="index")
        if "ndti" in x and "ndvi" in x:
            wide = x.dropna(subset=["ndti", "ndvi"])

    n_obs = len(wide)
    if not n_obs:
        return _row(w, note=(
            "no usable observations: the window exists but no clear scene "
            "inside it carried both NDTI and NDVI."))

    bare = wide[wide["ndvi"] < RESIDUE_GREEN_MAX]
    n_green = n_obs - len(bare)
    ndvi_max = round(float(wide["ndvi"].max()), 3)

    if len(bare) < RESIDUE_MIN_OBS:
        why = (f"only {len(bare)} non-green observation(s) in the window"
               if n_green == 0 else
               f"{n_green} of {n_obs} observations were green "
               f"(NDVI at or above {RESIDUE_GREEN_MAX:.2f}), leaving {len(bare)}")
        return _row(w, n_obs, len(bare), n_green, ndvi_max,
                    note=f"not enough bare ground to read: {why}.")

    note = None
    if n_green:
        note = (f"{n_green} of {n_obs} observations screened out as green "
                "cover; NDTI reads canopy, not residue, on those dates.")
    if w["source"] != "phenology":
        extra = "window ends fall back to fixed dates; phenology had no estimate."
        note = extra if note is None else f"{note} Also, {extra}"

    return _row(
        w, n_obs, len(bare), n_green, ndvi_max,
        min_ndti=round(float(bare["ndti"].min()), 4),
        median_ndti=round(float(bare["ndti"].median()), 4),
        max_ndti=round(float(bare["ndti"].max()), 4),
        min_ndti_date=bare["ndti"].idxmin(),
        median_ndsvi=(round(float(bare["ndsvi"].median()), 4)
                      if "ndsvi" in bare else None),
        median_ndi7=(round(float(bare["ndi7"].median()), 4)
                     if "ndi7" in bare else None),
        note=note)


def residue_all_years(ts: pd.DataFrame, phen: pd.DataFrame | None,
                      season: str = "spring") -> pd.DataFrame | None:
    """:func:`residue_summary` for every year the series covers."""
    if ts is None or not len(ts):
        return None
    rows = [residue_summary(ts, phen, int(y), season)
            for y in sorted(ts["date"].dt.year.unique())]
    return pd.DataFrame(rows) if rows else None
