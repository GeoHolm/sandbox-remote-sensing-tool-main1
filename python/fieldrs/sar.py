"""Sentinel-1 radar backscatter over a field, and radar-bracketed operation dates.

PROTOTYPE. Nothing here is calibrated against grower-reported operation dates.
It was built and looked at on one field (Story Co., Iowa, 2020-2026); every
constant below is a first guess on that field.

WHAT THE SIGNAL IS
C-band backscatter from bare soil depends on how rough the surface is and how
wet it is. Field operations change roughness -- a chisel pass roughens and
brightens VV, a field cultivator or planter smooths a seedbed and darkens it --
and harvest removes a standing canopy, which drops VH sharply. Radar sees
through cloud, which is exactly where the NDVI series has its gaps.

THE CONFOUNDER IS SOIL MOISTURE
Wetting the top few centimeters brightens VV just as roughening does -- the same
problem that makes single-date NDTI unusable (residue.py). Here it is handled
by regressing bare-soil VV on an antecedent precipitation index from gridMET
and working with the residual (:func:`moisture_adjust`). Frozen soil reads
dark like a smoothing pass, so frozen dates are dropped. Snowmelt is not rain
and is not removed.

WHAT CAME OUT ON THE IOWA FIELD (2020-2026)
Harvest: the largest VH drop near the NDVI harvest window fell inside it in 3
of 6 seasons, and the two soybean harvests were unmistakable (-5 to -6 dB in
one interval). For corn the radar step came weeks after the NDVI date in 2021
and 2025, which fits NDVI dating senescence rather than the combine.
Planting: the largest seedbed-smoothing drop fell inside the NDVI window in 3
of 7 seasons -- no better than chance for a search span about two and a half
times the window. Several early-April drops recur across years and may be
pre-plant tillage or spring drying; nothing here can tell which.

DATA
Planetary Computer ``sentinel-1-rtc``: terrain-corrected gamma0, 10 m, linear
power. Sentinel-1B failed in December 2021, so most years have one satellite;
each relative orbit revisits every 12 days. The Iowa field sits under two
ascending orbits (63 and 165), and once the orbit offset is removed the two are
read as one series with an acquisition about every 6 days.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds, intersection
from shapely.geometry import shape

from .aoi import field_bounds
from .cache import cache_get, cache_key, cache_put
from .imagery import GDAL_ENV, _sign, stac_search_retry

S1_COLLECTION = "sentinel-1-rtc"
S1_NODATA = -32768.0

# The RTC assets end in ".tiff", which the optical GDAL_ENV's extension filter
# (".tif") rejects outright -- every open fails as "does not exist".
S1_GDAL_ENV = {**GDAL_ENV, "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff"}

# Pixels kept only if their center sits this far inside the boundary: about one
# 10 m pixel, which keeps the field edge (headland, road, fence line) out.
S1_EDGE_M = 10.0

# --- provisional detection constants ------------------------------------------
# None of these is fitted to grower-reported dates. They were chosen by looking
# at one field (Story Co., Iowa, 2020-2026) and should be treated as such.

# Antecedent precipitation index: yesterday's rain counts 0.7, the day before
# 0.49, and so on. Of 0.7 / 0.8 / 0.9 on the Iowa field, 0.7 correlated best
# with bare-soil VV on both orbits (r = 0.35 and 0.62).
SAR_API_DECAY = 0.7

# Frozen soil has a low dielectric constant and reads several dB dark,
# indistinguishable from a smoothing pass. Acquisitions whose 3-day mean air
# temperature (gridMET) is at or below this are dropped from detection.
SAR_FROZEN_C = 1.0

# Bare field: NDVI below this on the nearest optical observation. Same ceiling
# residue.py uses for "not green". The moisture fit uses bare dates only.
SAR_BARE_NDVI = 0.30

# Where each event is searched for, relative to the NDVI estimate. Planting:
# from 1 April to a week after the NDVI window closes, since seedbed work comes
# before the planter. Harvest: two weeks before the window to four after,
# because NDVI dates senescence, and corn in particular stands dry for weeks
# before the combine.
SAR_PLANT_FROM = "04-01"
SAR_PLANT_AFTER_D = 7
SAR_HARVEST_BEFORE_D = 14
SAR_HARVEST_AFTER_D = 28

# gridMET variables the moisture and freeze screens need.
SAR_GRIDMET = ("pr", "vs", "tmmn", "tmmx")


# ---------------------------------------------------------------- extract ---

def _db(x: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(x)


def _read_s1(item, aoi: gpd.GeoDataFrame) -> dict | None:
    """Field statistics for one acquisition, VV and VH, in dB."""
    out: dict = {}
    with rasterio.Env(**S1_GDAL_ENV):
        for pol in ("vv", "vh"):
            if pol not in item.assets:
                return None
            with rasterio.open(_sign(item.assets[pol].href)) as src:
                geom = aoi.to_crs(src.crs).geometry.union_all()
                win = from_bounds(*geom.buffer(30).bounds, transform=src.transform)
                win = win.round_offsets().round_lengths()
                win = intersection(win, Window(0, 0, src.width, src.height))
                if win.width < 1 or win.height < 1:
                    return None
                arr = src.read(1, window=win).astype("float32")
                transform = src.window_transform(win)
            inner = geom.buffer(-S1_EDGE_M)
            inside = geometry_mask([inner if not inner.is_empty else geom],
                                   out_shape=arr.shape, transform=transform,
                                   invert=True)
            ok = inside & (arr != S1_NODATA) & np.isfinite(arr) & (arr > 0)
            n_field = int(inside.sum())
            if n_field == 0 or ok.sum() < 0.8 * n_field:
                # A slice edge or partial granule over the field.
                return None
            v = arr[ok]
            # Averaging is done in linear power, then converted: the mean of
            # dB values is biased low on speckle.
            out[f"{pol}_db"] = float(_db(np.mean(v)))
            out[f"{pol}_median_db"] = float(_db(np.median(v)))
            out[f"{pol}_p10_db"] = float(_db(np.percentile(v, 10)))
            out[f"{pol}_p90_db"] = float(_db(np.percentile(v, 90)))
            out[f"{pol}_pixels"] = np.where(ok, arr, np.nan)
            out["n_pixels"] = int(ok.sum())
    out["vh_vv_db"] = out["vh_db"] - out["vv_db"]
    return out


def s1_series(aoi: gpd.GeoDataFrame, start: str, end: str, *, workers: int = 8,
              only_cached: bool = False, refresh: bool = False,
              keep_pixels: bool = True) -> pd.DataFrame | None:
    """One row per Sentinel-1 acquisition over the field, ``start`` to ``end``.

    Acquisitions are deduplicated per (date, relative orbit): adjacent slices of
    one pass overlap, so the same overpass can appear twice in the catalog.
    """
    key = cache_key(aoi, start, end, "s1_series_v1")
    if not refresh:
        hit = cache_get(key, "s1")
        if hit is not None:
            return hit if keep_pixels else hit.drop(columns=["vv_pixels", "vh_pixels"])
    if only_cached:
        return None

    items = stac_search_retry(field_bounds(aoi), start, end, 500, (S1_COLLECTION,))
    poly = aoi.to_crs(4326).geometry.union_all()
    groups: dict[tuple, list] = {}
    for it in items:
        k = (it.datetime.date(), it.properties.get("sat:relative_orbit"))
        groups.setdefault(k, []).append(it)
    # Slices whose footprint covers the field first.
    for k, g in groups.items():
        g.sort(key=lambda it: 0 if shape(it.geometry).covers(poly) else 1)

    def one(k, g):
        for it in g:
            try:
                r = _read_s1(it, aoi)
            except Exception:                        # noqa: BLE001
                r = None
            if r is not None:
                return {"date": pd.Timestamp(k[0]), "orbit": int(k[1]),
                        "platform": str(it.properties.get("platform", "")).upper(),
                        "scene_id": it.id, **r}
        return None

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, k, g) for k, g in groups.items()]
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                rows.append(r)
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values(["date", "orbit"]).reset_index(drop=True)
    cache_put(key, df, "s1")
    return df if keep_pixels else df.drop(columns=["vv_pixels", "vh_pixels"])


# ----------------------------------------------------------------- detect ---

def s1_context(s1: pd.DataFrame, weather: pd.DataFrame,
               ndvi: pd.Series | None) -> pd.DataFrame:
    """Add the moisture, freeze and greenness state of each acquisition.

    Acquisitions over Iowa are at about 00:06 UTC, i.e. around 6 pm local the
    day before, so weather is read for the UTC date minus one day.

    Adds ``api_mm``, ``tmean3_c``, ``frozen``, ``ndvi``, ``bare`` and the
    moisture-adjusted ``vv_adj`` (see :func:`moisture_adjust`) and
    orbit-centered ``vh_c``.
    """
    s1 = s1.drop(columns=["vv_pixels", "vh_pixels"], errors="ignore").copy()
    w = weather.set_index("date").asfreq("D")
    k = SAR_API_DECAY
    api = w["pr_mm"].fillna(0).ewm(alpha=1 - k, adjust=False).mean() / (1 - k)
    tmean3 = ((w["tmmx_degc"] + w["tmmn_degc"]) / 2).rolling(3).mean()
    local = s1["date"] - pd.Timedelta(days=1)
    s1["api_mm"] = api.reindex(local).to_numpy()
    s1["tmean3_c"] = tmean3.reindex(local).to_numpy()
    s1["frozen"] = s1["tmean3_c"] <= SAR_FROZEN_C
    s1["ndvi"] = [_ndvi_at(ndvi, d) for d in s1["date"]]
    s1["bare"] = s1["ndvi"] < SAR_BARE_NDVI
    s1["vh_c"] = s1["vh_db"] - s1.groupby("orbit")["vh_db"].transform("median")
    return moisture_adjust(s1)


def moisture_adjust(s1: pd.DataFrame) -> pd.DataFrame:
    """VV with the rain-driven part and the orbit offset taken out.

    Per orbit, VV on bare unfrozen dates is regressed on log(1 + API) and the
    residual kept as ``vv_adj``. That does two jobs. It removes the brightening
    that follows rain, which otherwise swamps any roughness signal. And it
    removes the per-orbit offset -- the two orbits over the Iowa field sit
    about 1.6 dB apart from incidence angle alone -- so both orbits can be read
    as one series, with an acquisition every ~6 days instead of every 12.

    PROVISIONAL, and fitted per field: a field tilled on most wet dates would
    have some of its tillage signal absorbed into the moisture slope. On the
    Iowa field the slope was 0.67 dB (orbit 63) and 1.13 dB (orbit 165) per
    unit of log(1 + API mm). The fit is stored in ``.attrs["moisture_fit"]``.
    Snowmelt and thaw are not rain, so late-winter wetting is not removed.
    """
    s1 = s1.copy()
    s1["vv_adj"] = np.nan
    fits = {}
    for orbit, g in s1.groupby("orbit"):
        fit = g[g["bare"] & ~g["frozen"]].dropna(subset=["api_mm", "vv_db"])
        if len(fit) < 10:
            continue
        slope, icpt = np.polyfit(np.log1p(fit["api_mm"]), fit["vv_db"], 1)
        r = np.corrcoef(np.log1p(fit["api_mm"]), fit["vv_db"])[0, 1]
        fits[int(orbit)] = {"intercept": round(float(icpt), 3),
                            "slope": round(float(slope), 3),
                            "r": round(float(r), 3), "n": len(fit)}
        s1.loc[g.index, "vv_adj"] = g["vv_db"] - (icpt + slope * np.log1p(g["api_mm"]))
    s1.attrs["moisture_fit"] = fits
    return s1


def _ndvi_at(ndvi: pd.Series | None, day: pd.Timestamp) -> float:
    """NDVI on the nearest optical observation, within 10 days, or NaN."""
    if ndvi is None or ndvi.empty:
        return float("nan")
    gap = (ndvi.index - day).days
    i = int(np.argmin(np.abs(gap)))
    return float(ndvi.iloc[i]) if abs(gap[i]) <= 10 else float("nan")


def s1_intervals(ctx: pd.DataFrame) -> pd.DataFrame:
    """Consecutive unfrozen acquisitions, both orbits merged, with the change.

    ``d_vv_adj`` is the step in moisture-adjusted VV; ``d_vh`` the step in
    orbit-centered VH. The operation, if any, happened between ``date_a`` and
    ``date``.
    """
    # An orbit with too few bare dates gets no moisture fit, and its VV_adj is
    # NaN. Left in, one stray acquisition (a single orbit-128 pass over the
    # Mitchell Co. fields) blanks the two intervals either side of it.
    m = (ctx[~ctx["frozen"] & ctx["vv_adj"].notna()]
         .sort_values("date").reset_index(drop=True))
    m["date_a"] = m["date"].shift()
    m["d_vv_adj"] = m["vv_adj"].diff()
    m["d_vh"] = m["vh_c"].diff()
    m["bare_both"] = m["bare"] & m["bare"].shift(fill_value=False)
    return m.iloc[1:].reset_index(drop=True)


def s1_events(ctx: pd.DataFrame, phen: pd.DataFrame) -> pd.DataFrame:
    """Radar-bracketed planting and harvest candidates, one row per event.

    Planting: the largest DROP in moisture-adjusted VV while bare -- a seedbed
    pass or the planter smoothing the surface. Harvest: the largest drop in VH
    -- standing crop removed. Each is reported as the interval it falls in
    (``s1_from`` to ``s1_to``), next to the NDVI window it is meant to narrow.

    ``in_ndvi_window`` is a CONSISTENCY check, not validation: both could be
    wrong together. Grower-reported dates are what would validate either.
    """
    iv = s1_intervals(ctx)
    D = pd.Timedelta
    rows = []
    for p in phen.itertuples():
        y = int(p.year)
        specs = []
        if pd.notna(p.planting_lo):
            lo = pd.Timestamp(f"{y}-{SAR_PLANT_FROM}")
            hi = p.planting_hi + D(days=SAR_PLANT_AFTER_D)
            w = iv[(iv["date_a"] >= lo) & (iv["date"] <= hi) & iv["bare_both"]]
            specs.append(("planting", w, "d_vv_adj", p.planting_lo, p.planting_hi,
                          getattr(p, "planting_date", p.planting_est)))
        if pd.notna(p.harvest_lo):
            lo = p.harvest_lo - D(days=SAR_HARVEST_BEFORE_D)
            hi = p.harvest_hi + D(days=SAR_HARVEST_AFTER_D)
            w = iv[(iv["date_a"] >= lo) & (iv["date"] <= hi)]
            specs.append(("harvest", w, "d_vh", p.harvest_lo, p.harvest_hi,
                          getattr(p, "harvest_date", p.harvest_est)))
        for event, w, col, nlo, nhi, nest in specs:
            row = {"year": y, "crop": p.crop, "event": event,
                   "ndvi_lo": nlo, "ndvi_date": nest, "ndvi_hi": nhi,
                   "s1_from": pd.NaT, "s1_to": pd.NaT, "signal": col,
                   "step_db": None, "n_intervals": None,
                   "in_ndvi_window": None}
            # Only a drop counts. With two or three intervals in the window the
            # "largest drop" can otherwise be a rise.
            w = w[w[col] < 0]
            row["n_intervals"] = len(w)
            if len(w):
                e = w.loc[w[col].idxmin()]
                row.update(s1_from=e["date_a"], s1_to=e["date"],
                           step_db=round(float(e[col]), 2),
                           in_ndvi_window=bool(e["date"] >= nlo and e["date_a"] <= nhi))
            rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- refine ---
#
# s1_events() searches beyond the NDVI window and asks whether radar lands
# inside it. On three fields, physical filters that do not look at NDVI --
# requiring a workable day in the interval, a similar soil moisture state at
# both ends, or a step that persists -- did not raise that agreement (planting
# 7/17 -> 4/12 at best, harvest 12/18 -> 13/18 at best). So the radar is not
# made to agree by tuning; instead s1_refine() takes the NDVI window as given
# and asks what the radar and the weather can add inside it.
#
# Because the search is confined to the window, "inside the window" is true by
# construction and is NOT reported as a result. What is reported is how much
# the window narrows, whether the radar step that narrowed it stands out from
# the field's own scene-to-scene noise, and whether a stronger step sat outside
# the window (a disagreement worth a look, not something to resolve here).

# A radar step "supports" a narrowing when it is at least this many robust
# standard deviations of the field's interval-to-interval change. 2.0 is a
# conventional first cut, not fitted.
SAR_SUPPORT_Z = 2.0

# A step outside the window this much stronger (in z) than the best one inside
# is flagged as a conflict.
SAR_CONFLICT_DZ = 1.0


def workable_days(weather: pd.DataFrame) -> pd.Series:
    """Per local day: could equipment have been in the field?

    The same rules as the rain check in climate.py -- rain at or below
    DRY_PR_MM, and not the day after HEAVY_RAIN_MM or more -- plus not frozen,
    so the two features cannot disagree about what a workable day is.
    """
    from .climate import DRY_PR_MM, HEAVY_RAIN_MM, HEAVY_RAIN_WET_DAYS

    w = weather.set_index("date").asfreq("D")
    ok = w["pr_mm"].fillna(0) <= DRY_PR_MM
    for k in range(1, HEAVY_RAIN_WET_DAYS + 1):
        ok &= ~(w["pr_mm"].shift(k) >= HEAVY_RAIN_MM).fillna(False)
    if {"tmmx_degc", "tmmn_degc"} <= set(w.columns):
        ok &= ((w["tmmx_degc"] + w["tmmn_degc"]) / 2) > SAR_FROZEN_C
    return ok


def _robust_sd(x: pd.Series) -> float:
    x = x.dropna()
    return float(1.4826 * (x - x.median()).abs().median()) if len(x) >= 10 else float("nan")


def s1_refine(ctx: pd.DataFrame, phen: pd.DataFrame,
              weather: pd.DataFrame) -> pd.DataFrame:
    """Narrow each NDVI planting and harvest window with radar and weather.

    Per event and season:

    1. Radar intervals that overlap the NDVI window are candidates. Planting
       reads drops in moisture-adjusted VV on bare ground; harvest reads drops
       in VH.
    2. The strongest is scored as ``z``: its drop over the robust SD of every
       interval of the same kind on this field.
    3. If ``z >= SAR_SUPPORT_Z`` the window narrows to the workable days that
       fall both in the window and in that interval (``basis = "radar +
       weather"``). Otherwise the radar adds nothing and the window narrows to
       its workable days only (``basis = "weather only"``).

    ``candidate_days`` counts the days left; ``span_days`` is first to last of
    them. They differ a lot for "weather only", where rain days are struck out
    of the window but its ends barely move -- read the span, not the count, as
    how far the date has actually been pinned down.
    4. ``conflict`` is set when a step more than SAR_CONFLICT_DZ stronger sits
       in the wider search span outside the window. The NDVI window is kept
       either way; the flag says the two disagree.

    Days are local: an acquisition dated D (UTC, ~00:06) was taken the evening
    of D - 1, so an interval from A to B covers field days A .. B - 1.
    """
    iv = s1_intervals(ctx)
    work = workable_days(weather)
    D = pd.Timedelta
    sd = {"d_vv_adj": _robust_sd(iv.loc[iv["bare_both"], "d_vv_adj"]),
          "d_vh": _robust_sd(iv["d_vh"])}
    rows = []
    for p in phen.itertuples():
        y = int(p.year)
        for event in ("planting", "harvest"):
            lo, hi = getattr(p, f"{event}_lo"), getattr(p, f"{event}_hi")
            if pd.isna(lo) or pd.isna(hi):
                continue
            col = "d_vv_adj" if event == "planting" else "d_vh"
            pool = iv[iv["bare_both"]] if event == "planting" else iv
            if event == "planting":
                span = (pd.Timestamp(f"{y}-{SAR_PLANT_FROM}"), hi + D(days=SAR_PLANT_AFTER_D))
            else:
                span = (lo - D(days=SAR_HARVEST_BEFORE_D), hi + D(days=SAR_HARVEST_AFTER_D))
            # Field days of an interval are date_a .. date - 1.
            first, last = pool["date_a"], pool["date"] - D(days=1)
            inside = pool[(last >= lo) & (first <= hi) & (pool[col] < 0)]
            wider = pool[(first >= span[0]) & (last <= span[1]) & (pool[col] < 0)
                         & ~pool.index.isin(inside.index)]

            win_days = pd.date_range(lo, hi)
            win_work = [d for d in win_days if work.get(d, False)]
            row = {"year": y, "crop": p.crop, "event": event,
                   "ndvi_lo": lo, "ndvi_hi": hi, "ndvi_days": len(win_days),
                   "workable_days": len(win_work),
                   "s1_from": pd.NaT, "s1_to": pd.NaT, "step_db": None, "z": None,
                   "basis": "weather only", "refined_lo": pd.NaT, "refined_hi": pd.NaT,
                   "span_days": None, "candidate_days": None,
                   "conflict": False, "note": None}

            best_z = None
            if len(inside) and sd[col] and np.isfinite(sd[col]):
                e = inside.loc[inside[col].idxmin()]
                best_z = float(-e[col] / sd[col])
                row.update(s1_from=e["date_a"], s1_to=e["date"],
                           step_db=round(float(e[col]), 2), z=round(best_z, 2))
                if best_z >= SAR_SUPPORT_Z:
                    days = [d for d in pd.date_range(max(lo, e["date_a"]),
                                                     min(hi, e["date"] - D(days=1)))
                            if work.get(d, False)]
                    if days:
                        row.update(basis="radar + weather",
                                   refined_lo=days[0], refined_hi=days[-1],
                                   candidate_days=len(days))
                    else:
                        row["note"] = ("radar step stands out but its interval has "
                                       "no workable day inside the window")
            if row["basis"] == "weather only" and win_work:
                row.update(refined_lo=win_work[0], refined_hi=win_work[-1],
                           candidate_days=len(win_work))
            if row["candidate_days"] is None:
                row.update(refined_lo=lo, refined_hi=hi, candidate_days=len(win_days),
                           basis="NDVI only", note=row["note"] or "no workable day in window")
            row["span_days"] = (row["refined_hi"] - row["refined_lo"]).days + 1

            if len(wider) and sd[col] and np.isfinite(sd[col]):
                out_z = float(-wider[col].min() / sd[col])
                if out_z >= SAR_SUPPORT_Z and (best_z is None
                                               or out_z - best_z > SAR_CONFLICT_DZ):
                    o = wider.loc[wider[col].idxmin()]
                    row["conflict"] = True
                    msg = (f"stronger step outside window: {o['date_a']:%m-%d} to "
                           f"{o['date']:%m-%d}, z {out_z:.1f}")
                    row["note"] = msg if row["note"] is None else f"{row['note']}; {msg}"
            rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["noise_sd_db"] = {k: round(v, 2) for k, v in sd.items()}
    return out


# --------------------------------------------------------------- one call ---

def s1_analysis(aoi: gpd.GeoDataFrame, result, *, only_cached: bool = False,
                workers: int = 8) -> dict | None:
    """Everything the radar view needs for one field, in one call.

    ``result`` is the field's NDVI pipeline result (a FieldResult, or anything
    with ``start``, ``end``, ``series`` and ``phenology``): the radar is read
    over the same dates and against the same planting and harvest windows.

    Returns ``None`` when ``only_cached`` and the Sentinel-1 series is not
    cached, or when there are no acquisitions over the field. Weather comes
    from gridMET, so a field outside CONUS raises climate.GridmetError.
    """
    from .climate import gridmet_daily

    s1 = s1_series(aoi, result.start, result.end, workers=workers,
                   only_cached=only_cached, keep_pixels=False)
    if s1 is None or s1.empty:
        return None
    series = result.series
    ndvi = (series[series["index"] == "ndvi"].set_index("date")["mean"].sort_index()
            if series is not None and len(series) else None)
    weather = gridmet_daily(aoi, result.start, result.end, outputs=SAR_GRIDMET)
    ctx = s1_context(s1, weather, ndvi)
    from .forage import forage_cuts

    phen = result.phenology
    if phen is None or not len(phen):
        events = refined = pd.DataFrame()
    else:
        events = s1_events(ctx, phen)
        refined = s1_refine(ctx, phen, weather)
    cuts = forage_cuts(ndvi, phen, ctx, weather)
    return {"s1": s1, "ctx": ctx, "weather": weather, "ndvi": ndvi,
            "events": events, "refined": refined, "cuts": cuts,
            "orbits": sorted(int(o) for o in s1["orbit"].unique())}
