"""Soil armor: how much of the surface is covered, by anything.

WHAT CHANGED AND WHY
This supersedes the minimum-NDTI approach in ``residue.py``. NDTI measures crop
residue, which is only half of soil armor: a field under a living cover crop or
a perennial stand is protected just as well as one under stubble, and NDTI
scores it as though it were bare. On this field library that error was not
subtle -- the Washington alfalfa pivot, a permanent stand and the best-protected
soil here, ranked last of eleven fields. It now ranks first.

HOW IT WORKS
Each pixel is placed in NDVI-DFI space and decomposed into three fractions that
sum to one:

    fPV    photosynthetic vegetation -- living green cover
    fNPV   non-photosynthetic vegetation -- residue, stubble, litter
    fBS    bare soil

Soil armor is ``1 - fBS``: cover from any source. NDVI alone cannot do this,
because residue and bare soil look nearly identical to it. DFI is what separates
them -- in the endmembers below, NPV and BS differ by 0.05 in NDVI and by 22 in
DFI.

DFI = 100 * (1 - SWIR2/SWIR1) * (Red/NIR), Cao et al. (2010). The first term is
the lignocellulose absorption near 2100 nm that residue has and soil does not;
the second suppresses green canopy.

WHAT IS STILL NOT CALIBRATED
The endmembers come from this library's own pixels, not from measured cover. The
fractions are internally consistent and comparable between these fields, but
they are not validated cover percentages. Line transects scoring green cover,
residue and bare soil separately are what would turn fBS into a defensible
number.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .extract import extract_field_series
from .indices import add_index
from .phenology import residue_window

# Triangle vertices in (NDVI, DFI), from 65,555 cloud-free pixels across six
# fields spanning permanent green, heavy residue and clean tilled soil.
#
# Water and deep shadow were excluded first, and that mattered: as NIR
# collapses, DFI's Red/NIR term explodes, so the highest-DFI pixels in the raw
# pool were flooded rice and cloud shadow rather than residue. Left in, they put
# the NPV vertex at NDVI -0.02, which is not a surface any crop field has.
ARMOR_ENDMEMBERS = {
    "pv":  (0.961, 1.212),      # pure living canopy
    "npv": (0.232, 25.642),     # pure residue
    "bs":  (0.183, 3.296),      # clean bare soil
}

# Below this NDVI the pixel is water or deep shadow, where DFI is meaningless.
# Masked rather than mixed, so it drops out of the field average instead of
# corrupting it.
ARMOR_WATER_NDVI = 0.05

ARMOR_INDICES = ("ndvi", "ndti", "dfi", "f_pv", "f_npv", "f_bs")
# The whole calendar year -- see the note in the R armor.R. The summary
# statistic is unchanged: armor_summary() still filters to the pre-planting
# window, so every validated number means what it did before.
ARMOR_SPAN = ("01-01", "12-31")
ARMOR_MIN_OBS = 3

_A = np.array([
    [ARMOR_ENDMEMBERS["pv"][0], ARMOR_ENDMEMBERS["npv"][0], ARMOR_ENDMEMBERS["bs"][0]],
    [ARMOR_ENDMEMBERS["pv"][1], ARMOR_ENDMEMBERS["npv"][1], ARMOR_ENDMEMBERS["bs"][1]],
    [1.0, 1.0, 1.0],
])
_AINV = np.linalg.inv(_A)


def cover_fractions(b) -> dict[str, np.ndarray]:
    """Per-pixel cover fractions from a dict of reflectance arrays."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (b["nir"] - b["red"]) / (b["nir"] + b["red"])
        dfi = 100.0 * (1.0 - b["swir22"] / b["swir16"]) * (b["red"] / b["nir"])

    f = [_AINV[i, 0] * ndvi + _AINV[i, 1] * dfi + _AINV[i, 2] for i in range(3)]
    # Spectral variability puts roughly one pixel in eight just outside the
    # triangle. Clamp and renormalise rather than discard: a pixel at -0.03 is
    # a pure endmember with noise on it, not a measurement failure.
    f = [np.clip(x, 0.0, 1.0) for x in f]
    s = f[0] + f[1] + f[2]
    with np.errstate(divide="ignore", invalid="ignore"):
        f = [x / s for x in f]
    bad = ~np.isfinite(ndvi) | (ndvi < ARMOR_WATER_NDVI)
    for x in f:
        x[bad] = np.nan
    return {"pv": f[0], "npv": f[1], "bs": f[2]}


add_index("f_pv", lambda b: cover_fractions(b)["pv"],
          ["red", "nir", "swir16", "swir22"], 0.0, 1.0,
          "Living green cover fraction (NDVI-DFI unmixing).")
add_index("f_npv", lambda b: cover_fractions(b)["npv"],
          ["red", "nir", "swir16", "swir22"], 0.0, 1.0,
          "Residue / non-photosynthetic cover fraction.")
add_index("f_bs", lambda b: cover_fractions(b)["bs"],
          ["red", "nir", "swir16", "swir22"], 0.0, 1.0,
          "Bare soil fraction. Soil armor is 1 - this.")
add_index("dfi",
          lambda b: 100.0 * (1.0 - b["swir22"] / b["swir16"]) * (b["red"] / b["nir"]),
          ["red", "nir", "swir16", "swir22"], -5.0, 45.0,
          "Dead Fuel Index (Cao 2010). Non-photosynthetic material.")

ARMOR_BREAKS = (0.40, 0.75)
ARMOR_LABELS = ("mostly bare", "partly covered", "well covered")


def armor_band(x) -> str | None:
    """Which band a soil armor value falls in."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    lo, hi = ARMOR_BREAKS
    return (ARMOR_LABELS[0] if x < lo
            else ARMOR_LABELS[1] if x < hi
            else ARMOR_LABELS[2])


def armor_series(aoi, years: tuple[int, int] = (2020, None), *,
                 workers: int = 8, only_cached: bool = False,
                 refresh: bool = False, progress=None) -> pd.DataFrame | None:
    """Spring index series for the armor window, one extraction per year."""
    y_from, y_to = years
    y_to = y_to or date.today().year
    frames = []
    yrs = list(range(y_from, y_to + 1))
    for i, y in enumerate(yrs):
        df = extract_field_series(
            aoi, f"{y}-{ARMOR_SPAN[0]}", f"{y}-{ARMOR_SPAN[1]}",
            indices=ARMOR_INDICES, workers=workers,
            only_cached=only_cached, refresh=refresh)
        if df is None:
            if only_cached:
                return None
            continue
        frames.append(df)
        if progress is not None:
            progress(i + 1, len(yrs), f"Armor year {y}")
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["index", "date"]).reset_index(drop=True)


def _time_weighted(dates, y) -> float:
    """Trapezoidal average of ``y`` over ``dates``."""
    x = np.asarray(pd.DatetimeIndex(dates).map(pd.Timestamp.toordinal), dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 2 or x.max() == x.min():
        return float(np.mean(y))
    return float(np.trapezoid(y, x) / (x.max() - x.min()))


def armor_summary(ts: pd.DataFrame, phen: pd.DataFrame | None, year: int,
                  season: str = "spring") -> dict:
    """Soil armor over one season's pre-planting window.

    Time-weighted, not the median, and not the minimum.

    Minimum was right for NDTI, where a single wet morning could quadruple the
    reading. A cover fraction is a different quantity, so this started as a
    median -- but the cross-implementation check caught that being fragile. On
    the Georgia field in 2026 the two implementations saw 7 and 8 observations
    of a steeply falling series, and the one extra date moved the median from
    0.59 to 0.72.

    A trapezoidal average over the observation dates is the right answer
    anyway: soil is exposed to erosion over *time*, so what matters is average
    cover through the window, not the middle value of however many scenes
    happened to be clear.
    """
    def _row(w=None, n_obs=0, **kw) -> dict:
        base = {"year": int(year), "season": season,
                "window_start": None if w is None else w["start"],
                "window_end": None if w is None else w["end"],
                "window_source": None if w is None else w["source"],
                "n_obs": n_obs}
        fill = {"armor": None, "armor_lo": None, "armor_hi": None,
                "f_pv": None, "f_npv": None, "f_bs": None,
                "min_ndti": None, "ndvi_med": None, "note": None}
        fill.update(kw)
        return {**base, **fill}

    w = residue_window(phen, year, season)
    if w is None:
        cur = (phen[phen["year"] == year] if phen is not None and len(phen)
               and "season_type" in phen else None)
        if cur is not None and len(cur) == 1 and \
                str(cur["season_type"].iloc[0]).startswith("winter"):
            return _row(note=("no window: a winter crop, sown the autumn before, "
                              "so its spring is canopy rather than a pre-planting "
                              "period."))
        return _row(note=("no window: planting falls at or before the start of "
                          "the window, so there is no pre-planting period to "
                          "measure."))

    d = ts[(ts["date"] >= w["start"]) & (ts["date"] <= w["end"])]
    wide = pd.DataFrame()
    if not d.empty:
        wide = d.pivot_table(index="date", values="mean", columns="index")
    need = ["f_pv", "f_npv", "f_bs"]
    if not all(c in wide for c in need):
        return _row(w, note="cover fractions not present in this series.")
    wide = wide.dropna(subset=need)
    n_obs = len(wide)

    if n_obs < ARMOR_MIN_OBS:
        return _row(w, n_obs, note=(
            f"only {n_obs} usable observation(s) in the window; too few to "
            "summarise."))

    wide = wide.sort_index()
    a = 1.0 - wide["f_bs"]
    note = None
    if w["source"] != "phenology":
        note = "window ends fall back to fixed dates; phenology had no estimate."

    return _row(
        w, n_obs,
        armor=round(_time_weighted(wide.index, a), 3),
        armor_lo=round(float(a.min()), 3),
        armor_hi=round(float(a.max()), 3),
        f_pv=round(_time_weighted(wide.index, wide["f_pv"]), 3),
        f_npv=round(_time_weighted(wide.index, wide["f_npv"]), 3),
        f_bs=round(_time_weighted(wide.index, wide["f_bs"]), 3),
        min_ndti=(round(float(wide["ndti"].min()), 4) if "ndti" in wide else None),
        ndvi_med=(round(float(wide["ndvi"].median()), 3) if "ndvi" in wide else None),
        note=note)


def armor_all_years(ts: pd.DataFrame, phen: pd.DataFrame | None,
                    season: str = "spring") -> pd.DataFrame | None:
    """:func:`armor_summary` for every year the series covers."""
    if ts is None or not len(ts):
        return None
    rows = [armor_summary(ts, phen, int(y), season)
            for y in sorted(ts["date"].dt.year.unique())]
    return pd.DataFrame(rows) if rows else None
