"""Cutting dates for alfalfa and other hay, from NDVI, radar and weather.

PROTOTYPE. Built by looking at one field, the Washington pivot (alfalfa
2020-2023 and 2025, potatoes 2024). Nothing here is checked against
grower-reported cutting dates, and every constant below is a first guess.

WHY A SEPARATE MODEL
An established alfalfa stand is never planted or harvested in the row-crop
sense, so phenology.py correctly refuses to date it. The field operation that
matters is the cutting: several a season under irrigation, each removing the
canopy in a day. NDVI shows each one plainly -- a drop from ~0.9 to 0.3-0.5
between two clear observations, then regrowth over three to five weeks.

HOW
1. NDVI finds the cuts. From a stand at or above CUT_STAND_MIN, a fall of at
   least CUT_DROP to the following trough -- the first low before regrowth --
   is a cut. Its date is bracketed by the first scene at least halfway down to
   the trough and the scene before it, so the bracket is as wide as the gap
   between clear scenes -- typically 5 to 10 days with Sentinel-2 in an
   irrigated summer.
2. Radar narrows the bracket when it can. Sentinel-1 VH drops when a canopy is
   removed; if the strongest VH drop overlapping the bracket stands out from
   the field's scene-to-scene noise (sar.SAR_SUPPORT_Z), the bracket shrinks to
   the part inside that radar interval. VH is used rather than VV because the
   rain-based moisture correction does not apply to an irrigated field, and VH
   is the less moisture-sensitive of the two.
3. Weather strikes out days nobody cuts hay on: rain days and the day after
   heavy rain (sar.workable_days, the same rule as the planting check).

A cut with no regrowth after it is flagged: the season's last cut before
dormancy, or the stand being taken out. A drop to bare soil is reported with
kind "to bare soil" -- tillage, reseeding or removal, not a hay cut.

ON THE WASHINGTON PIVOT (2020-2026)
20 hay cuts: 4 in 2020, 5 in 2021, 2 in 2022, 5 in 2025, 4 in 2026 so far.
Three drops to bare soil -- September 2022, June 2023 and October 2023 -- sit
around the stand being taken out and the reseeding the season model dates in
summer 2023, so 2023 has no hay cuts. 2022 is short because a cloud gap from
late April to late June hides its first cut. Radar narrowed 12 of the 20
brackets; the median bracket went from 5 days to 4, and 2 days or fewer for
several.

WHAT IT DOES NOT DO
Grazing looks like a slow cut and is not separated. Pasture (CDL
"Grass/Pasture") is left out for that reason. A cut inside a long cloudy gap
is found with a correspondingly wide bracket, or missed if regrowth happened
before the next clear scene.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# CDL classes cut for hay. Grass/Pasture is excluded: it is mostly grazed, and
# grazing is a slow decline rather than a cut.
FORAGE_CROPS = ("Alfalfa", "Other Hay/Non Alfalfa", "Clover/Wildflowers", "Vetch")

# --- provisional constants -----------------------------------------------------
# Only look for cuts in the growing season; winter dormancy, snow and frost-kill
# are drops too. Washington's first cut is usually mid-May, the last early
# October.
CUT_SEASON = ("04-01", "11-15")

# A cut starts from a stand at least this green ...
CUT_STAND_MIN = 0.60
# ... and NDVI falls at least this far to the trough. On the Washington pivot,
# scene-to-scene change on a full stand (both scenes > 0.85, <= 6 days apart,
# n = 56) has median 0.016 and 95th percentile 0.060. Clear cuts fell 0.3-0.8.
# 0.25 missed three shallower dips of 0.22-0.24 that sit where cuts are
# expected (May 2020, May and August 2025); 0.20 finds them, and 0.15 finds
# nothing more, so the dips are not noise creeping in.
CUT_DROP = 0.20
# A step down this large ends the stand: the cut search starts there.
CUT_ONSET = 0.10
# The trough has to come within this many days of the last stand observation.
CUT_TROUGH_DAYS = 21
# A rise this far above the lowest reading so far ends the trough: regrowth has
# started. About the 95th percentile of full-stand scene-to-scene noise (0.06).
CUT_RISE = 0.06
# Regrowth: NDVI recovers at least this much above the trough within this many
# days. Otherwise the cut is flagged as the last of the season or a removal.
CUT_REGROW = 0.15
CUT_REGROW_DAYS = 45

# A trough below this is bare soil, not stubble: the stand was tilled out,
# reseeded or removed. Reported, but labeled as such rather than as a cut. Same
# ceiling residue.py and sar.py use for "not green" would be 0.30; stubble after
# a cut on the Washington pivot bottomed at 0.31-0.62, and the two drops to
# 0.09 and 0.14 were followed by a replanting curve, hence the lower line.
CUT_BARE_NDVI = 0.20


def forage_years(phen: pd.DataFrame | None) -> list[int]:
    """Years read as hay: CDL says a forage crop, or -- for a year CDL has not
    published yet -- the previous year was forage and the season model found a
    perennial stand."""
    if phen is None or not len(phen):
        return []
    out = []
    crops = phen.set_index("year")["crop"].to_dict()
    for p in phen.itertuples():
        crop = p.crop if isinstance(p.crop, str) else None
        if crop in FORAGE_CROPS:
            out.append(int(p.year))
        elif crop is None and crops.get(p.year - 1) in FORAGE_CROPS \
                and "not an annual row crop" in str(getattr(p, "confidence", "")):
            out.append(int(p.year))
    return out


def ndvi_cuts(ndvi: pd.Series, year: int) -> list[dict]:
    """Cuts in one year's clear NDVI observations. See the module docstring."""
    lo, hi = (pd.Timestamp(f"{year}-{d}") for d in CUT_SEASON)
    s = ndvi[(ndvi.index >= lo) & (ndvi.index <= hi)].dropna().sort_index()
    # Regrowth may be read past the season end.
    after = ndvi[ndvi.index > lo].dropna().sort_index()
    cuts, i, n = [], 0, len(s)
    while i < n - 1:
        stand = s.iloc[i]
        if stand < CUT_STAND_MIN:
            i += 1
            continue
        # Walk to the last observation still at the stand level, so a stand that
        # keeps growing for a few scenes anchors on its final reading.
        j = i
        while j + 1 < n and s.iloc[j + 1] > s.iloc[j] - CUT_ONSET:
            j += 1
        if j + 1 >= n:
            break
        last_high, high = s.index[j], s.iloc[j]
        if high < CUT_STAND_MIN:
            # Drifted down in small steps from the starting stand.
            i = j + 1
            continue
        onset = s.index[j + 1]
        # The trough is the FIRST low after the drop, not the lowest point in a
        # fixed window: cuts can be under four weeks apart, and a window
        # minimum jumped from one cut's stubble to the next one's, swallowing
        # the cut between (August 2021 on the Washington pivot). Follow the
        # decline until NDVI rises clearly -- regrowth -- or the window ends.
        k = j + 1
        end = last_high + pd.Timedelta(days=CUT_TROUGH_DAYS)
        while (k + 1 < n and s.index[k + 1] <= end
               and s.iloc[k + 1] < s.iloc[j + 1:k + 1].min() + CUT_RISE):
            k += 1
        win = s.iloc[j + 1:k + 1]
        if high - win.min() < CUT_DROP:
            i = j + 1
            continue
        t_date, trough = win.idxmin(), float(win.min())
        # Date the cut by the first scene at least halfway down to the trough,
        # not by the first 0.10 step: a stand can sag a little before it is cut.
        # August 2021 on the Washington pivot read 0.91, 0.81, 0.59, 0.31 on
        # 7, 12, 22 and 27 August with a uniform field (p10-p90 within 0.09);
        # the first-step rule put the cut on 7-12 August, the halfway rule puts
        # it on 12-22 August -- cut, green windrows at 0.59, baled to 0.31.
        half = high - 0.5 * (high - trough)
        fall = s[(s.index > last_high) & (s.index <= t_date)]
        onset = fall[fall <= half].index[0]
        last_high = s[s.index < onset].index[-1]
        later = after[(after.index > t_date)
                      & (after.index <= t_date + pd.Timedelta(days=CUT_REGROW_DAYS))]
        regrew = bool(len(later) and later.max() - trough >= CUT_REGROW)
        cuts.append({"year": year, "ndvi_from": last_high, "ndvi_to": onset,
                     "ndvi_stand": round(float(high), 3),
                     "ndvi_trough": round(trough, 3), "trough_date": t_date,
                     "regrowth": regrew})
        # Continue from the trough: the next cut starts from the regrown stand.
        i = int(np.searchsorted(s.index.values, t_date.to_datetime64(), side="right"))
    for k, c in enumerate(cuts, 1):
        c["cut"] = k
    return cuts


def forage_cuts(ndvi: pd.Series | None, phen: pd.DataFrame | None,
                ctx: pd.DataFrame | None = None,
                weather: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every cut in every forage year, with radar and weather narrowing.

    ``ndvi`` is the field's clear-observation NDVI series (date index).
    ``ctx`` is sar.s1_context output; ``weather`` daily gridMET. Either may be
    None, and the cut then keeps its NDVI bracket.

    Columns: year, crop, cut, ndvi_from / ndvi_to (the NDVI bracket),
    ndvi_stand / ndvi_trough, regrowth, s1_from / s1_to / step_db / z for the
    strongest overlapping VH drop, basis, refined_lo / refined_hi, span_days,
    candidate_days, note.
    """
    from .sar import SAR_SUPPORT_Z, _robust_sd, workable_days

    cols = ["year", "crop", "cut", "kind", "ndvi_from", "ndvi_to", "ndvi_days",
            "ndvi_stand", "ndvi_trough", "regrowth", "s1_from", "s1_to",
            "step_db", "z", "basis", "refined_lo", "refined_hi", "span_days",
            "candidate_days", "note"]
    years = forage_years(phen)
    if ndvi is None or ndvi.empty or not years:
        return pd.DataFrame(columns=cols)
    crops = phen.set_index("year")["crop"].to_dict()

    # VH from every orbit, each centered on its own median. Unlike
    # sar.s1_intervals this does not need the VV moisture fit, which an
    # irrigated stand that is never bare usually cannot get.
    iv, sd = None, float("nan")
    if ctx is not None and len(ctx):
        m = (ctx[~ctx["frozen"]].sort_values(["date", "orbit"], kind="mergesort")
             .reset_index(drop=True))
        m["date_a"] = m["date"].shift()
        m["d_vh"] = m["vh_c"].diff()
        iv = m.iloc[1:]
        iv = iv[iv["date"] > iv["date_a"]].reset_index(drop=True)   # no same-day pairs
        season = iv[iv["date"].dt.strftime("%m-%d").between(*CUT_SEASON)]
        sd = _robust_sd(season["d_vh"])
    work = workable_days(weather) if weather is not None and len(weather) else None

    rows = []
    for y in years:
        for c in ndvi_cuts(ndvi, y):
            lo, hi = c["ndvi_from"], c["ndvi_to"]
            row = {**{k: None for k in cols}, **c, "crop": crops.get(y),
                   "ndvi_days": (hi - lo).days, "basis": "NDVI only",
                   "s1_from": pd.NaT, "s1_to": pd.NaT}
            bare = c["ndvi_trough"] < CUT_BARE_NDVI
            row["kind"] = "to bare soil" if bare else "cut"
            notes = []
            if bare:
                notes.append("fell to bare soil: tillage, reseeding or stand removal "
                             "rather than a hay cut")
            if not c["regrowth"]:
                notes.append("no regrowth after: last cut of the season, or the "
                             "stand removed")
            note = "; ".join(notes) or None
            # The cut happened after the last high scene and on or before the
            # first low one.
            days = list(pd.date_range(lo + pd.Timedelta(days=1), hi))
            if iv is not None and np.isfinite(sd) and sd > 0:
                first, last = iv["date_a"], iv["date"] - pd.Timedelta(days=1)
                over = iv[(last >= days[0]) & (first <= days[-1]) & (iv["d_vh"] < 0)]
                if len(over):
                    e = over.loc[over["d_vh"].idxmin()]
                    z = float(-e["d_vh"] / sd)
                    row.update(s1_from=e["date_a"], s1_to=e["date"],
                               step_db=round(float(e["d_vh"]), 2), z=round(z, 2))
                    if z >= SAR_SUPPORT_Z:
                        narrowed = [d for d in days
                                    if e["date_a"] <= d <= e["date"] - pd.Timedelta(days=1)]
                        if narrowed:
                            days, row["basis"] = narrowed, "NDVI + radar"
            if work is not None:
                dry = [d for d in days if work.get(d, False)]
                if dry:
                    days = dry
                    row["basis"] = row["basis"] + " + weather"
                else:
                    extra = "no rain-free day in the bracket"
                    note = extra if note is None else f"{note}; {extra}"
            row.update(refined_lo=days[0], refined_hi=days[-1],
                       span_days=(days[-1] - days[0]).days + 1,
                       candidate_days=len(days), note=note)
            rows.append(row)
    return pd.DataFrame(rows, columns=cols)
