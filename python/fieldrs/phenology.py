"""Planting and harvest dates from the NDVI curve.

WHAT THIS IS
NDVI cannot see a planter or a combine. It sees the canopy: bare soil before
emergence, green-up as the canopy closes, senescence as the crop dries down,
residue after the field is cleared. Planting and harvest are inferred from those
transitions.

HOW GOOD IS IT
Published work using Sentinel-2/Landsat green-up against reported planting dates
for US corn and soy generally lands within about two weeks. That is the honest
resolution of this method and it is what these functions report. The offsets in
CROP_LAGS are literature-typical starting values, not calibrated against any
particular grower's records.

THE COVER CROP COMPLICATION
A cover-cropped field has a bimodal curve: a spring cover crop peak, a dip at
termination, then the cash crop peak. Anchoring the baseline on "spring NDVI"
reads the cover crop as an early cash crop. Everything below anchors on the
trough immediately before the cash crop peak, which is bare soil in both cases.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.interpolate import UnivariateSpline

try:                                    # scipy >= 1.10
    from scipy.interpolate import make_smoothing_spline
except ImportError:                     # pragma: no cover
    make_smoothing_spline = None

# Days from planting to the point where NDVI has risen 20% of the way to peak.
# Emergence is earlier; the canopy has to cover enough soil for the signal to
# move at all.
CROP_LAGS = {
    "Corn": 21, "Soybeans": 18, "Winter Wheat": 0, "Cotton": 24,
    "Sorghum": 20, "Rice": 20, "Peanuts": 20,
}
DEFAULT_LAG = 20

# Smoothing penalty for the daily curve, chosen to reproduce R's
# smooth.spline(spar = 0.35) -- the two implementations have to agree, and
# letting each pick its own is how they drift apart.
#
# Leaving scipy's GCV to choose per-series gave a systematically weaker penalty
# than R: peak NDVI differed by up to 0.081 across the field library, with 12 of
# 77 seasons outside the 0.02 comparison tolerance. Sweeping lam against the R
# reference, 50 lands the mean difference at 0.004 and the worst at 0.018, with
# none outside tolerance. It also reproduces R's behaviour at a plateau exactly:
# both smoothers sit slightly above the highest observation in 26 of the 77
# seasons, which is the spline rounding a flat top, not an error.
SMOOTH_LAM = 50.0

# Fallback smoothing strength, only used when scipy is too old to provide
# make_smoothing_spline. Expressed as an assumed observation noise SD.
FALLBACK_SMOOTH_SD = 0.045

# --- applicability limits -----------------------------------------------------
# This model assumes an annual row crop: bare soil, green-up, peak, senescence,
# residue. Two common systems break that assumption, and both are detectable
# from the curve itself.
#
# A perennial stand -- alfalfa, and other multi-cut forage -- is green all year
# and has no planting to find. The tempting test is "NDVI never reaches bare
# soil", but that alone does not work: a heavily cover-cropped Maryland corn
# field bottoms out at 0.31 and the alfalfa pivot at 0.33, which is not a gap
# you can put a threshold in. What does separate them is how much of the year
# is green. Across this library the alfalfa years sit above NDVI 0.50 for
# 86-95% of the year, while every genuine row crop year -- including the
# cover-cropped ones -- stays at or below 72%, because residue and the shoulder
# seasons pull the curve down even when a cover crop is present.
PERENNIAL_MIN_NDVI = 0.30      # never reaches bare soil
PERENNIAL_GREEN_FRAC = 0.80    # ...and is green for most of the year

# Negative NDVI is open water, not vegetation. Flooded rice reaches -0.60 at the
# annual minimum. Dates can still be estimated, but the flood confuses the
# baseline, so they are reported with the reason attached.
WATER_NDVI = 0.05


def applicability(year_min: float, green_frac: float) -> tuple[bool, str | None]:
    """Does the annual-row-crop model apply to this season's curve?

    ``green_frac`` is the share of the year the smoothed curve sits above
    NDVI 0.50. Returns ``(applicable, note)``. A note with ``applicable=True``
    is a caveat worth surfacing rather than a reason to withhold the estimate.
    """
    if year_min > PERENNIAL_MIN_NDVI and green_frac >= PERENNIAL_GREEN_FRAC:
        return False, (
            f"not an annual row crop -- NDVI never drops below {year_min:.2f} "
            f"and stays above 0.50 for {green_frac:.0%} of the year, so there "
            "is no bare-soil period to measure planting from (perennial or "
            "multi-cut, e.g. alfalfa)"
        )
    if year_min < WATER_NDVI:
        return True, (
            f"standing water in the off-season (NDVI reaches {year_min:.2f}); "
            "flooded rice or a wet fallow shifts the baseline, so treat the "
            "dates as indicative"
        )
    return True, None


def crop_lag(crop: str | None) -> int:
    if not crop:
        return DEFAULT_LAG
    return CROP_LAGS.get(crop, DEFAULT_LAG)


def daily_series(ts: pd.DataFrame, index: str = "ndvi", max_gap: int = 45,
                 lam: float | None = SMOOTH_LAM) -> pd.DataFrame:
    """Daily-interpolated index series.

    Observations are irregular -- cloud decides when you get one. A smooth daily
    curve makes threshold crossings well defined, at the cost of inventing
    detail between observations. Gaps longer than ``max_gap`` days are left as
    NaN rather than bridged, so a two-month winter hole never becomes a
    confident-looking line.

    Uses scipy's penalised smoothing spline, the direct analogue of R's
    ``smooth.spline``, at the fixed penalty :data:`SMOOTH_LAM` rather than
    letting GCV choose one per series -- see the note there. The obvious
    alternative, ``UnivariateSpline`` with a hand-set smoothing factor,
    overshoots badly at a plateau: on one season it put peak NDVI at 0.987 where
    the highest actual observation was 0.884, which is not a physically possible
    canopy value.
    """
    d = ts[ts["index"] == index].sort_values("date")
    if len(d) < 8:
        raise ValueError(f"Only {len(d)} observations for '{index}'; need 8 to smooth.")

    x = d["date"].map(pd.Timestamp.toordinal).to_numpy(dtype=float)
    y = d["mean"].to_numpy(dtype=float)
    grid = np.arange(x.min(), x.max() + 1)

    if make_smoothing_spline is not None:
        spline = make_smoothing_spline(x, y, lam=lam)
    else:
        spline = UnivariateSpline(x, y, s=len(x) * FALLBACK_SMOOTH_SD ** 2, k=3)
    vals = np.asarray(spline(grid), dtype=float)

    # Blank out stretches with no supporting observation.
    gap = np.abs(grid[:, None] - x[None, :]).min(axis=1)
    vals[gap > max_gap / 2] = np.nan

    return pd.DataFrame({
        "date": [pd.Timestamp.fromordinal(int(g)) for g in grid],
        "value": vals,
    })


def _nearest_gap(obs: pd.Series, at: pd.Timestamp) -> float:
    """Observation gap straddling a date -- how blind we are at that moment."""
    before = obs[obs <= at]
    after = obs[obs >= at]
    if before.empty or after.empty:
        return 60.0
    return float((after.min() - before.max()).days)


def estimate_phenology(ts: pd.DataFrame, year: int, crop: str | None = None,
                       index: str = "ndvi",
                       peak_window: tuple[str, str] = ("06-01", "09-15")) -> dict | None:
    """Season markers for one crop year, or ``None`` if the year is too sparse."""
    d = ts[(ts["index"] == index) & (ts["date"].dt.year == year)]
    if len(d) < 10:
        return None
    try:
        curve = daily_series(d, index)
    except ValueError:
        return None
    curve = curve.dropna(subset=["value"])
    if len(curve) < 60:
        return None

    lo = pd.Timestamp(f"{year}-{peak_window[0]}")
    hi = pd.Timestamp(f"{year}-{peak_window[1]}")
    inpk = curve[(curve["date"] >= lo) & (curve["date"] <= hi)]
    if len(inpk) < 10:
        return None
    pk = inpk.loc[inpk["value"].idxmax()]
    peak_val, peak_date = float(pk["value"]), pk["date"]

    base = {"year": year, "crop": crop, "season_type": "summer",
            "peak_date": peak_date, "peak_ndvi": round(peak_val, 3), "n_obs": len(d)}

    def _blank(reason: str) -> dict:
        return {**base, "planting_est": None, "planting_lo": None,
                "planting_hi": None, "greenup_date": None, "harvest_est": None,
                "harvest_lo": None, "harvest_hi": None, "season_days": None,
                "baseline_ndvi": None, "amplitude": None, "confidence": reason}

    # A field that never greens up had no summer crop -- fallow, or a failure.
    if peak_val < 0.45:
        return _blank("no summer crop detected")

    # Does the annual-row-crop model apply at all? Returning a confident-looking
    # planting date for a permanently green field is worse than returning none.
    year_min = float(curve["value"].min())
    green_frac = float((curve["value"] >= 0.50).mean())
    applies, note = applicability(year_min, green_frac)
    if not applies:
        return _blank(note)

    # Trough before the peak: bare soil at planting. Take the LAST near-minimum,
    # not the global one -- on a cover-cropped field the curve dips twice, and
    # the global minimum can be the winter dip, which reads the spring cover
    # crop green-up as crop emergence (a February planting date for corn).
    pre = curve[(curve["date"] >= pd.Timestamp(f"{year}-03-01")) &
                (curve["date"] <= peak_date - timedelta(days=20))]
    if len(pre) < 10:
        return None
    gmin = float(pre["value"].min())
    near = pre[pre["value"] <= gmin + 0.06]
    baseline = float(near["value"].iloc[-1])
    base_date = near["date"].iloc[-1]

    amp = peak_val - baseline
    if amp < 0.2:
        return None
    thr_up = baseline + 0.20 * amp

    rise = curve[(curve["date"] >= base_date) & (curve["date"] <= peak_date)]
    up = rise[rise["value"] >= thr_up]
    if up.empty:
        return None
    greenup = up["date"].iloc[0]
    plant = greenup - timedelta(days=crop_lag(crop))

    # Senescence, anchored on the post-peak minimum rather than on spring.
    # Where something green follows the cash crop -- a cover crop, a ratoon
    # flush -- NDVI never returns to the spring floor, and a spring-anchored
    # threshold reports no harvest at all.
    harvest = None
    fall = curve[curve["date"] >= peak_date]
    if len(fall) >= 10:
        post_trough = float(fall["value"].min())
        # The drop has to be a real one. In a season still under way the curve
        # has barely come off its peak; without this guard the shallow dip
        # reads as an early harvest.
        if (peak_val - post_trough) >= 0.35 * amp:
            thr_down = post_trough + 0.20 * (peak_val - post_trough)
            down = fall[fall["value"] <= thr_down]
            if not down.empty:
                harvest = down["date"].iloc[0]

    # Uncertainty from actual observation density: a crossing in the middle of a
    # three-week cloud gap is a guess, so widen the window rather than quoting a
    # flat +/- 14 days everywhere.
    obs = d["date"]
    gap_plant = _nearest_gap(obs, greenup)
    win_plant = max(14, int(np.ceil(gap_plant)))
    if harvest is None:
        conf = "low -- no clear senescence"
        win_harvest = None
    else:
        gap_h = _nearest_gap(obs, harvest)
        win_harvest = max(14, int(np.ceil(gap_h)))
        worst = max(gap_plant, gap_h)
        conf = ("high" if worst <= 10 else
                "medium" if worst <= 20 else
                "low -- sparse imagery near transitions")

    # A caveat from the applicability check rides along with the estimate, and
    # caps the confidence -- standing water at the baseline is a bigger source
    # of error than a few days of cloud.
    if note:
        conf = f"low -- {note}" if conf.startswith("high") or conf.startswith("medium") \
               else f"{conf}; {note}"

    return {
        **base,
        "greenup_date": greenup,
        "planting_est": plant,
        "planting_lo": plant - timedelta(days=win_plant),
        "planting_hi": plant + timedelta(days=win_plant),
        "harvest_est": harvest,
        "harvest_lo": None if harvest is None else harvest - timedelta(days=win_harvest),
        "harvest_hi": None if harvest is None else harvest + timedelta(days=win_harvest),
        "season_days": None if harvest is None else int((harvest - greenup).days),
        "baseline_ndvi": round(baseline, 3),
        "amplitude": round(amp, 3),
        "confidence": conf,
    }


# --- winter crops and fallow ---------------------------------------------------
# A winter small grain is sown in autumn, emerges, overwinters, greens up again
# in spring, peaks in May-June and is harvested in early summer. The summer
# model above looks for a June-September peak and reads spring green-up as
# planting, so for these crops it misses seasons and puts "planting" in April.
# Checked on two wheat-fallow fields near Akron, Colorado, where the summer
# model dated 3 of 6 wheat seasons, all with April-May "planting" dates.
#
# Season ``year`` is the HARVEST year; sowing is in the autumn before it.
WINTER_CROPS = ("Winter Wheat", "Rye", "Triticale")
FALLOW_CROPS = ("Fallow/Idle Cropland",)

WINTER_PEAK_WINDOW = ("03-15", "06-30")   # spring canopy peak, harvest year
WINTER_SOW_SEARCH = ("08-01", "10-31")    # bare-soil trough before emergence, prior year
WINTER_FALL_LAST = "12-15"                # emergence must show by then; later is spring
WINTER_FALL_MIN_RISE = 0.08               # NDVI rise that counts as emergence
WINTER_SOW_LAG = 14                       # days, sowing to the 20% point of the fall rise
WINTER_SOW_EARLIEST = "08-15"

# A fallow period is the field between one harvest and the next sowing. Green
# growth inside it is weeds or volunteer grain, which fallow exists to control.
FALLOW_GREEN = 0.30


def estimate_winter_phenology(ts: pd.DataFrame, year: int, crop: str | None = None,
                              index: str = "ndvi") -> dict | None:
    """Season markers for a winter crop harvested in ``year``.

    ``planting_est`` is autumn SOWING (in ``year - 1``), from the rise out of
    the bare-soil trough as the crop emerges, less WINTER_SOW_LAG.
    ``greenup_date`` is spring green-up, ``harvest_est`` the senescence after
    the spring peak. Returns ``None`` if the crop year is too sparse.
    """
    lo_all = pd.Timestamp(f"{year - 1}-07-01")
    hi_all = pd.Timestamp(f"{year}-10-31")
    d = ts[(ts["index"] == index) & (ts["date"] >= lo_all) & (ts["date"] <= hi_all)]
    if len(d) < 10:
        return None
    try:
        curve = daily_series(d, index).dropna(subset=["value"])
    except ValueError:
        return None
    pk_lo = pd.Timestamp(f"{year}-{WINTER_PEAK_WINDOW[0]}")
    pk_hi = pd.Timestamp(f"{year}-{WINTER_PEAK_WINDOW[1]}")
    inpk = curve[(curve["date"] >= pk_lo) & (curve["date"] <= pk_hi)]
    if len(inpk) < 10:
        return None
    pk = inpk.loc[inpk["value"].idxmax()]
    peak_val, peak_date = float(pk["value"]), pk["date"]
    crop_year = d[d["date"] >= pd.Timestamp(f"{year - 1}-08-01")]
    base = {"year": year, "crop": crop, "season_type": "winter",
            "peak_date": peak_date, "peak_ndvi": round(peak_val, 3),
            "n_obs": len(crop_year)}
    blank = {"planting_est": None, "planting_lo": None, "planting_hi": None,
             "greenup_date": None, "harvest_est": None, "harvest_lo": None,
             "harvest_hi": None, "season_days": None, "baseline_ndvi": None,
             "amplitude": None}
    if peak_val < 0.45:
        return {**base, **blank, "confidence": "no winter crop detected"}
    # Same perennial test as the summer model, over the crop year: alfalfa's
    # regrowth after a cutting can otherwise pass for autumn emergence.
    cy = curve[curve["date"] >= pd.Timestamp(f"{year - 1}-08-01")]
    applies, pnote = applicability(float(cy["value"].min()),
                                   float((cy["value"] >= 0.50).mean()))
    if not applies:
        return {**base, **blank, "confidence": pnote}
    notes = []
    obs = d["date"]
    gaps = []

    # Sowing: trough in late summer / autumn, then the emergence rise.
    sow = None
    tr = curve[(curve["date"] >= pd.Timestamp(f"{year - 1}-{WINTER_SOW_SEARCH[0]}")) &
               (curve["date"] <= pd.Timestamp(f"{year - 1}-{WINTER_SOW_SEARCH[1]}"))]
    if tr.empty:
        notes.append("no autumn imagery -- sowing not dated")
    else:
        t = tr.loc[tr["value"].idxmin()]
        fall = curve[(curve["date"] >= t["date"]) &
                     (curve["date"] <= pd.Timestamp(f"{year - 1}-12-31"))]
        rise = float(fall["value"].max() - t["value"]) if len(fall) else 0.0
        if rise >= WINTER_FALL_MIN_RISE:
            cross = fall[fall["value"] >= t["value"] + 0.20 * rise]["date"].iloc[0]
            if cross <= pd.Timestamp(f"{year - 1}-{WINTER_FALL_LAST}"):
                sow = max(cross - timedelta(days=WINTER_SOW_LAG),
                          pd.Timestamp(f"{year - 1}-{WINTER_SOW_EARLIEST}"))
                gaps.append(_nearest_gap(obs, cross))
            else:
                notes.append("autumn emergence too late to see -- sowing not dated")
        else:
            notes.append("no autumn emergence visible -- sowing not dated "
                         "(dry autumn, late sowing, or snow)")

    # Spring green-up: rise from the late-winter low to the peak.
    greenup = baseline = amp = None
    pre = curve[(curve["date"] >= pd.Timestamp(f"{year}-01-01")) &
                (curve["date"] <= peak_date - timedelta(days=20))]
    if len(pre) >= 10:
        gmin = float(pre["value"].min())
        near = pre[pre["value"] <= gmin + 0.06]
        baseline, base_date = float(near["value"].iloc[-1]), near["date"].iloc[-1]
        amp = peak_val - baseline
        up = curve[(curve["date"] >= base_date) & (curve["date"] <= peak_date) &
                   (curve["value"] >= baseline + 0.20 * amp)]
        if amp >= 0.10 and not up.empty:
            greenup = up["date"].iloc[0]

    # Harvest: senescence after the spring peak.
    harvest = None
    after = curve[(curve["date"] >= peak_date) &
                  (curve["date"] <= pd.Timestamp(f"{year}-09-30"))]
    if len(after) >= 10:
        trough = float(after["value"].min())
        drop = peak_val - trough
        if drop >= 0.20:
            down = after[after["value"] <= trough + 0.20 * drop]
            if not down.empty:
                harvest = down["date"].iloc[0]
                gaps.append(_nearest_gap(obs, harvest))

    def _win(est, gap):
        w = max(14, int(np.ceil(gap)))
        return est - timedelta(days=w), est + timedelta(days=w)

    gi = iter(gaps)
    plo = phi = hlo = hhi = None
    if sow is not None:
        plo, phi = _win(sow, next(gi))
    if harvest is not None:
        hlo, hhi = _win(harvest, next(gi))
    if harvest is None:
        conf = "; ".join(["low -- no clear senescence"] + notes)
    elif sow is None:
        conf = "low -- " + "; ".join(notes)
    else:
        worst = max(gaps)
        conf = ("high" if worst <= 10 else "medium" if worst <= 20 else
                "low -- sparse imagery near transitions")
    return {
        **base,
        "greenup_date": greenup,
        "planting_est": sow, "planting_lo": plo, "planting_hi": phi,
        "harvest_est": harvest, "harvest_lo": hlo, "harvest_hi": hhi,
        "season_days": None if (harvest is None or greenup is None)
                       else int((harvest - greenup).days),
        "baseline_ndvi": None if baseline is None else round(baseline, 3),
        "amplitude": None if amp is None else round(amp, 3),
        "confidence": conf,
    }


def _looks_winter(summer: dict | None, winter: dict | None) -> bool:
    """With no crop label, does the curve read as a winter crop?

    Only when the winter model resolves autumn emergence (sowing), a spring
    canopy and its harvest, and the summer model either found no crop or only
    caught that same canopy's tail at the start of its June window. Autumn
    emergence is the deciding evidence: a spring-sown crop in the South can
    peak in early June too, but it has nothing green the autumn before. A
    perennial the summer model refused stays refused.
    """
    if (not winter or winter.get("harvest_est") is None
            or winter.get("planting_est") is None or winter["peak_ndvi"] < 0.45):
        return False
    if summer and str(summer.get("confidence", "")).startswith("not an annual row crop"):
        return False
    if not summer or summer.get("planting_est") is None:
        return True
    tail = summer["peak_date"] <= pd.Timestamp(f"{summer['year']}-06-10")
    return tail and summer["peak_ndvi"] <= winter["peak_ndvi"] + 0.02


def _fallow_periods(rows: list[dict], ts: pd.DataFrame, index: str) -> None:
    """Fill fallow_start / fallow_end / fallow_days / green growth, in place."""
    by_year = {r["year"]: r for r in rows}
    for r in rows:
        if not str(r.get("season_type", "")).startswith("fallow"):
            continue
        y = r["year"]
        prev, nxt = by_year.get(y - 1), by_year.get(y + 1)
        start = prev.get("harvest_est") if prev else None
        end = nxt.get("planting_est") if nxt else None
        r["fallow_start"], r["fallow_end"] = start, end
        r["fallow_days"] = (int((end - start).days)
                            if start is not None and end is not None else None)
        lo = start or pd.Timestamp(f"{y}-01-01")
        hi = end or pd.Timestamp(f"{y}-12-31")
        d = ts[(ts["index"] == index) & (ts["date"] >= lo - timedelta(days=45)) &
               (ts["date"] <= hi + timedelta(days=45))]
        try:
            c = daily_series(d, index).dropna(subset=["value"])
            c = c[(c["date"] >= lo) & (c["date"] <= hi)]
            r["fallow_max_ndvi"] = round(float(c["value"].max()), 3) if len(c) else None
            r["fallow_green_days"] = int((c["value"] >= FALLOW_GREEN).sum())
        except ValueError:
            r["fallow_max_ndvi"] = r["fallow_green_days"] = None
        if r.get("fallow_green_days"):
            r["confidence"] += (f"; green growth during fallow on {r['fallow_green_days']} "
                                "days -- weeds or volunteer grain")


def phenology_all_years(ts: pd.DataFrame, crops: dict[int, str] | None = None,
                        index: str = "ndvi") -> pd.DataFrame | None:
    """Season markers for every year in the series.

    The CDL crop picks the model: winter crops (WINTER_CROPS) get
    :func:`estimate_winter_phenology`, fallow years (FALLOW_CROPS) a fallow row
    with the fallow period, everything else the summer model. A year with no
    CDL label yet is read from the curve -- see :func:`_looks_winter`.
    ``season_type`` says which: summer, winter, winter (from curve), fallow.
    """
    crops = crops or {}
    rows = []
    for y in sorted(ts["date"].dt.year.unique()):
        y = int(y)
        crop = crops.get(y)
        if crop in WINTER_CROPS:
            r = estimate_winter_phenology(ts, y, crop, index)
        elif crop in FALLOW_CROPS:
            r = estimate_phenology(ts, y, crop, index)
            if r is not None and r.get("planting_est") is not None:
                r["confidence"] += ("; CDL says fallow but NDVI shows a summer canopy "
                                    "-- weeds, or a CDL error")
            else:
                r = {**(r or {"year": y, "crop": crop, "peak_date": None,
                              "peak_ndvi": None, "n_obs": None}),
                     "season_type": "fallow", "confidence": "fallow (CDL)"}
        elif crop is None:
            summer = estimate_phenology(ts, y, None, index)
            winter = estimate_winter_phenology(ts, y, None, index)
            if _looks_winter(summer, winter):
                r = {**winter, "season_type": "winter (from curve)",
                     "confidence": winter["confidence"] +
                     "; no CDL for this year -- winter crop read from the NDVI curve"}
            elif (summer is not None and summer.get("planting_est") is None
                  and str(summer.get("confidence", "")).startswith("no summer crop")
                  and (winter is None or winter.get("harvest_est") is None)):
                # Neither a summer nor a winter canopy: fallow, or idle.
                r = {**summer, "season_type": "fallow (from curve)",
                     "confidence": "no crop in the NDVI and no CDL yet -- fallow "
                                   "or idle, read from the curve"}
            else:
                r = summer
        else:
            r = estimate_phenology(ts, y, crop, index)
        if r is not None:
            rows.append(r)
    if not rows:
        return None
    _fallow_periods(rows, ts, index)
    return pd.DataFrame(rows)


# --- residue window -----------------------------------------------------------
# Residue and tillage indices are read between one crop's harvest and the next
# crop's planting, when the surface is bare soil or residue rather than canopy.
# Choosing that window is the part the phenology table can already answer, and
# getting it wrong is a common reason field-level residue estimates disagree
# with what is on the ground.
#
# Nothing here computes a tillage class. The indices this window is meant for
# are registered in indices.py but are uncalibrated, and published field-level
# accuracy for multispectral tillage classification is around 73-80% -- roughly
# one field in four misclassified. Residue line-transect ground truth comes
# before any verdict.

RESIDUE_HARVEST_LAG = 7     # days after harvest before residue settles
RESIDUE_PLANT_LEAD = 3      # stop before planting disturbs the surface


def residue_window(phen: pd.DataFrame | None, year: int,
                   season: str = "spring") -> dict | None:
    """The bare-soil / residue window before ``year``'s planting.

    ``season="spring"`` (the default) starts no earlier than 1 March, the
    window minNDTI-style methods use, which excludes autumn tillage and most of
    the snow season. ``season="full"`` runs from the previous harvest, so it
    also covers fall tillage -- at the cost of a much longer window over which
    soil moisture varies far more.

    Returns ``None`` when the window is empty. ``source`` is ``"phenology"``
    when both ends came from the table, ``"partial"`` when one did and
    ``"fallback"`` when neither; a caller reporting numbers should say which.

    >>> w = residue_window(phen, 2024)
    >>> d = ts[(ts["index"] == "ndti") & ts["date"].between(w["start"], w["end"])]
    """
    if season not in ("spring", "full"):
        raise ValueError("season must be 'spring' or 'full'")
    year = int(year)
    from_phen = 0
    start = end = None

    if phen is not None and len(phen):
        # A winter crop was sown the autumn before: its spring is canopy, not a
        # pre-planting period -- even when the sowing date itself is unknown.
        cur = phen[phen["year"] == year]
        if (len(cur) == 1 and "season_type" in cur
                and str(cur["season_type"].iloc[0]).startswith("winter")):
            return None
        h = phen[phen["year"] == year - 1]
        if len(h) == 1 and pd.notna(h["harvest_est"].iloc[0]):
            start = pd.Timestamp(h["harvest_est"].iloc[0]) + timedelta(days=RESIDUE_HARVEST_LAG)
            from_phen += 1
        p = phen[phen["year"] == year]
        if len(p) == 1 and pd.notna(p["planting_est"].iloc[0]):
            end = pd.Timestamp(p["planting_est"].iloc[0]) - timedelta(days=RESIDUE_PLANT_LEAD)
            from_phen += 1

    # Same fallback dates the cover crop module uses, so the two agree on what
    # "the off-season" means when phenology could not pin it down.
    if start is None:
        start = pd.Timestamp(f"{year - 1}-10-15")
    if end is None:
        end = pd.Timestamp(f"{year}-05-10")

    if season == "spring":
        start = max(start, pd.Timestamp(f"{year}-03-01"))
    if end <= start:
        return None

    return {
        "start": start,
        "end": end,
        "n_days": int((end - start).days),
        "year": year,
        "season": season,
        "source": ("fallback", "partial", "phenology")[from_phen],
        "note": None if from_phen == 2 else
                "one or both ends fall back to fixed dates; phenology had no estimate",
    }


def residue_windows(phen: pd.DataFrame | None, years=None,
                    season: str = "spring") -> pd.DataFrame | None:
    """:func:`residue_window` for every year the phenology table covers."""
    if years is None:
        if phen is None or not len(phen):
            return None
        years = sorted(phen["year"].unique())
    rows = []
    for y in years:
        w = residue_window(phen, int(y), season)
        if w is not None:
            rows.append({k: w[k] for k in
                         ("year", "season", "start", "end", "n_days", "source")})
    return pd.DataFrame(rows) if rows else None
