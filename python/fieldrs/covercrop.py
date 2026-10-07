"""Off-season green cover from NDVI.

WHAT THE SIGNAL IS
After a corn or soybean harvest a Midwest field is crop residue: NDVI settles
around 0.10-0.25 and stays there until spring. A planted cover crop -- cereal
rye being the common one -- establishes in autumn, goes near-dormant over
winter, and greens up again before termination. That shows as a distinct
off-season hump above the residue floor.

WHAT IT IS NOT
NDVI sees green, not intent. It cannot by itself separate a planted cover crop
from volunteer grain, winter annual weeds, or a grassed waterway inside the
boundary. This module reports evidence and names the confounders rather than
asserting a practice, and the thresholds are literature-typical starting points
that should be calibrated against known cover-cropped fields before anyone leans
on the output.

Snow is handled upstream: the SCL mask drops snow-covered pixels, so snowy dates
disappear from the record rather than reading as bare soil. That is right, but
it thins winter coverage -- which is why ``n_obs`` is reported every time.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .phenology import daily_series

CC_RESIDUE_MAX = 0.25       # NDVI ceiling for crop residue
CC_GREEN_MIN = 0.30         # sustained green has to reach this
CC_STRONG = 0.35

# Open water reads as negative NDVI. Rice ground is commonly flooded through the
# winter -- for waterfowl habitat and to rot down residue -- and you cannot see
# a cover crop under water. Reporting "no cover crop detected" there would be
# misleading: nothing was detectable either way.
CC_WATER_NDVI = 0.05
CC_WATER_SHARE = 0.25       # share of window observations under water


def detect_cover_crop(ts: pd.DataFrame, fall_year: int,
                      phen: pd.DataFrame | None = None,
                      next_crop: str | None = None,
                      index: str = "ndvi") -> dict | None:
    """Assess off-season green cover for the winter following ``fall_year``.

    The window runs from that autumn's harvest to the next spring's planting,
    taken from the phenology table where available and falling back to fixed
    dates where not.
    """
    win_start = pd.Timestamp(f"{fall_year}-10-15")
    win_end = pd.Timestamp(f"{fall_year + 1}-05-10")
    late_planting = None
    winter = f"{fall_year}-{str(fall_year + 1)[2:]}"

    if phen is not None and len(phen):
        h = phen[phen["year"] == fall_year]
        if len(h) == 1 and pd.notna(h["harvest_est"].iloc[0]):
            win_start = h["harvest_est"].iloc[0] + timedelta(days=7)
        p = phen[phen["year"] == fall_year + 1]

        # A winter cash crop occupies the off-season: it is sown in the autumn,
        # so there is no gap before it to look for a cover crop in. Caught here,
        # before the window is built from its (autumn) planting date -- which
        # would close the window and drop the winter -- whether CDL names it or
        # the season model read it from the curve because CDL is not out yet.
        stype = (str(p["season_type"].iloc[0])
                 if len(p) == 1 and "season_type" in p else "")
        if stype.startswith("winter"):
            d = ts[(ts["index"] == index) & (ts["date"] >= win_start) &
                   (ts["date"] <= win_end)]
            sown = p["planting_est"].iloc[0]
            when = f" sown about {sown:%d %b %Y}" if pd.notna(sown) else ""
            src = (f"CDL records {next_crop} for {fall_year + 1}"
                   if next_crop else
                   f"CDL for {fall_year + 1} is not published yet; the NDVI curve "
                   "shows an autumn emergence, a spring peak and an early-summer "
                   "senescence -- a winter grain")
            return _row(winter, fall_year, win_start, win_end, len(d),
                        float(d["mean"].max()) if len(d) else None,
                        float(d["mean"].mean()) if len(d) else None,
                        d.loc[d["mean"].idxmax(), "date"] if len(d) else None,
                        None, "winter cash crop, not a cover crop",
                        f"{src}{when}. The green signal is that crop.")
        if len(p) == 1 and pd.notna(p["planting_est"].iloc[0]):
            win_end = p["planting_est"].iloc[0] - timedelta(days=3)
            late_planting = int(p["planting_est"].iloc[0].dayofyear)

    if win_end <= win_start:
        return None

    d = ts[(ts["index"] == index) & (ts["date"] >= win_start) & (ts["date"] <= win_end)]

    if len(d) < 4:
        return _row(winter, fall_year, win_start, win_end, len(d), None, None,
                    None, None, "insufficient data",
                    f"Only {len(d)} clear observations in the window; winter "
                    "cloud and snow often leave too little to judge.")

    max_ndvi = float(d["mean"].max())
    mean_ndvi = float(d["mean"].mean())
    peak_date = d.loc[d["mean"].idxmax(), "date"]
    n_green = int((d["mean"] >= CC_GREEN_MIN).sum())

    # Days of sustained green, from the smoothed curve. Fitted to the window
    # plus a margin, never to the whole multi-year record: one smoothing
    # parameter cannot represent several annual cycles at once, and fitting
    # globally would flatten exactly the hump being measured.
    green_days = None
    local = ts[(ts["index"] == index) &
               (ts["date"] >= win_start - timedelta(days=45)) &
               (ts["date"] <= win_end + timedelta(days=45))]
    try:
        curve = daily_series(local, index)
        w = curve[(curve["date"] >= win_start) & (curve["date"] <= win_end)]
        green_days = int((w["value"].dropna() >= CC_GREEN_MIN).sum())
    except ValueError:
        pass

    # A perennial is green all year, so "off-season cover" is not a meaningful
    # question -- what is green in January is the same stand that was green in
    # July, not a cover crop planted after harvest.
    if phen is not None and len(phen):
        h = phen[phen["year"] == fall_year]
        if len(h) == 1 and "not an annual row crop" in str(h["confidence"].iloc[0]):
            return _row(winter, fall_year, win_start, win_end, len(d), max_ndvi,
                        mean_ndvi, peak_date, green_days,
                        "perennial stand -- off-season cover not applicable",
                        "The season analysis found no bare-soil period for "
                        f"{fall_year}, so this field carries a perennial or "
                        "multi-cut stand. Winter greenness is that stand, not a "
                        "cover crop sown after harvest.")

    # Standing water: if much of the window is flooded there may be nothing to
    # see, which is a different answer from "bare ground". But only call it
    # undetectable when no real green showed up -- a window that reaches 0.64
    # plainly did detect something, whatever else was under water earlier.
    n_water = int((d["mean"] < CC_WATER_NDVI).sum())
    flooded = n_water / len(d) >= CC_WATER_SHARE
    if flooded and max_ndvi < CC_STRONG:
        return _row(winter, fall_year, win_start, win_end, len(d), max_ndvi,
                    mean_ndvi, peak_date, green_days,
                    "off-season flooded -- cover crop not detectable",
                    f"{n_water} of {len(d)} observations are open water "
                    f"(NDVI below {CC_WATER_NDVI:.2f}), typical of rice ground "
                    "held flooded over winter, and nothing green rose above "
                    f"{CC_STRONG:.2f}. A cover crop could not have been seen "
                    "under water, so this is 'unknown', not 'none'.")
    water_note = ""
    if flooded:
        water_note = (f" Note: {n_water} of {len(d)} observations are open "
                      "water, so part of this window was flooded and any "
                      "earlier establishment would have been hidden.")

    winter_cash = bool(next_crop) and any(
        k in next_crop for k in ("Winter Wheat", "Triticale", "Rye", "Barley",
                                 "Canola", "Dbl Crop"))
    # A cash crop going in after about 10 June, on the back of a strong spring
    # green-up, is the signature of double cropping after a small grain rather
    # than a terminated cover crop. CDL often labels the field by the summer
    # crop alone, so the crop name will not catch this.
    double_crop = (late_planting is not None and late_planting > 161
                   and max_ndvi >= CC_STRONG)

    if winter_cash:
        verdict = "winter cash crop, not a cover crop"
        notes = (f"CDL records {next_crop} for {fall_year + 1}, a harvested "
                 "winter crop. The green signal is that crop.")
    elif double_crop:
        verdict = "green cover -- cover crop or small grain"
        notes = (f"Off-season NDVI peaks at {max_ndvi:.2f} on "
                 f"{peak_date:%d %b}, but the next cash crop does not go in "
                 "until late June. That late planting after a strong spring "
                 "green-up is equally consistent with a harvested small grain "
                 "followed by double-crop soybeans. Needs the grower record to "
                 "separate.")
    elif max_ndvi >= CC_STRONG and n_green >= 2:
        verdict = "likely cover crop"
        notes = (f"Off-season NDVI peaks at {max_ndvi:.2f} on {peak_date:%d %b} "
                 f"with {n_green} observations above {CC_GREEN_MIN:.2f} -- well "
                 f"clear of the {CC_RESIDUE_MAX:.2f} residue ceiling.")
    elif max_ndvi >= CC_GREEN_MIN:
        verdict = "possible cover crop"
        notes = (f"Off-season NDVI reaches {max_ndvi:.2f}, above residue but not "
                 f"sustained ({n_green} observation(s) above {CC_GREEN_MIN:.2f}). "
                 "Volunteer grain or winter weeds look like this too.")
    else:
        verdict = "no cover crop detected"
        notes = (f"Off-season NDVI stays at or below {max_ndvi:.2f}, consistent "
                 "with bare soil and crop residue.")

    nxt = (phen[phen["year"] == fall_year + 1] if phen is not None and len(phen)
           and "season_type" in phen else None)
    if (nxt is not None and len(nxt) == 1
            and str(nxt["season_type"].iloc[0]).startswith("fallow")
            and verdict in ("likely cover crop", "possible cover crop")):
        notes += (f" {fall_year + 1} is a fallow year, so green growth after the "
                  "summer harvest is more often volunteer grain or weeds than a "
                  "planted cover -- unless a cover crop was sown into the fallow.")
    elif next_crop is None and verdict != "no cover crop detected":
        notes += (f" CDL for {fall_year + 1} is not published yet, and a winter grain "
                  "sown in the autumn would look much the same until its spring "
                  "peak and summer harvest show -- check again then.")
    return _row(winter, fall_year, win_start, win_end, len(d), max_ndvi,
                mean_ndvi, peak_date, green_days, verdict, notes + water_note)


def _row(winter, fall_year, ws, we, n_obs, mx, mn, pk, gd, verdict, notes) -> dict:
    return {
        "winter": winter, "fall_year": fall_year,
        "window_start": ws, "window_end": we, "n_obs": n_obs,
        "max_ndvi": None if mx is None else round(mx, 3),
        "mean_ndvi": None if mn is None else round(mn, 3),
        "peak_date": pk, "green_days": gd,
        "verdict": verdict, "notes": notes,
    }


# --- seeding and termination dates -------------------------------------------
# Inferred the same way the cash crop dates are: from where the curve turns, not
# from anything that sees the drill or the sprayer. The lags and thresholds are
# literature-typical starting values, set by eye against the cover-cropped
# fields in data/fields/ -- none is fitted to recorded seeding or termination
# dates. Treat the dates as low-to-medium confidence until they are.
#
# Seeding: after the cash harvest the curve falls to a trough (residue), then
# rises as the cover establishes. The 20% point of that rise, minus the time a
# small grain takes to emerge and cover enough soil to move NDVI, is seeding.
# A cover sown into the standing crop (aerial or high-clearance interseeding)
# is already green at harvest and has no post-harvest trough to date from; a
# late-sown one may show nothing until spring. Both are reported, not guessed.
#
# Termination: before the cash crop the curve falls from the cover's last
# spring hump to bare soil. The midpoint of that decline, minus the lag between
# spraying and browning, is termination. Burndown herbicide takes one to two
# weeks to read in NDVI; tillage, mowing or a roller-crimper reads within days,
# so the lag is a compromise and the uncertainty window covers both.
COVER_SEED_LAG = 14         # days: seeding to the 20% point of the fall rise
COVER_TERM_LAG = 7          # days: termination to the midpoint of the decline
COVER_TROUGH_SEARCH = (-7, 45)   # days around cash harvest to find the trough
COVER_FALL_SEARCH = 100     # days after the trough to find the fall peak
COVER_SEED_MAX = 90         # fall rise must start within this many days of harvest
COVER_SEED_LAST = "01-31"   # ...and by this date; later is spring regrowth
COVER_MIN_RISE = 0.08       # NDVI rise that counts as establishment
COVER_PEAK_SEARCH = 100     # days before the pre-plant trough to find the last hump
COVER_MIN_DROP = 0.10       # NDVI fall that counts as termination

# Verdicts for which the green signal is (or may be) a cover crop.
_DATED_VERDICTS = ("likely cover crop", "possible cover crop",
                   "green cover -- cover crop or small grain")

_DATE_KEYS = ["seeding_est", "seeding_lo", "seeding_hi",
              "termination_est", "termination_lo", "termination_hi",
              "cover_days", "dates_confidence", "dates_note"]


def _obs_gap(obs: pd.Series, at: pd.Timestamp) -> float:
    before, after = obs[obs <= at], obs[obs >= at]
    if before.empty or after.empty:
        return 60.0
    return float((after.min() - before.max()).days)


def _phen_value(phen, year, col):
    if phen is None or not len(phen) or col not in phen:
        return None
    r = phen[phen["year"] == year]
    if len(r) != 1 or pd.isna(r[col].iloc[0]):
        return None
    return pd.Timestamp(r[col].iloc[0])


def cover_crop_dates(ts: pd.DataFrame, cc_row: dict, phen: pd.DataFrame | None,
                     index: str = "ndvi") -> dict:
    """Seeding and termination estimates for one off-season.

    Returns the keys in ``_DATE_KEYS``; dates are ``None`` where the curve does
    not support one, with the reason in ``dates_note``. Only winters whose
    verdict is a (possible) cover crop are dated.
    """
    out = dict.fromkeys(_DATE_KEYS)
    if cc_row.get("verdict") not in _DATED_VERDICTS:
        return out
    y = int(cc_row["fall_year"])
    notes = []
    harvest = _phen_value(phen, y, "harvest_est")
    planting = _phen_value(phen, y + 1, "planting_est")
    greenup = _phen_value(phen, y + 1, "greenup_date")
    ws, we = pd.Timestamp(cc_row["window_start"]), pd.Timestamp(cc_row["window_end"])

    # The cash crop's green-up closes the off-season; without one, a month past
    # the window end stands in for it.
    seg_end = greenup or (planting + timedelta(days=21) if planting else we + timedelta(days=30))
    seg_start = (harvest or ws) + timedelta(days=COVER_TROUGH_SEARCH[0])
    d = ts[(ts["index"] == index) &
           (ts["date"] >= seg_start - timedelta(days=45)) &
           (ts["date"] <= seg_end + timedelta(days=45))]
    try:
        curve = daily_series(d, index).dropna(subset=["value"])
    except ValueError:
        out["dates_note"] = "too few observations to date"
        return out
    curve = curve[(curve["date"] >= seg_start) & (curve["date"] <= seg_end)]
    if len(curve) < 30:
        out["dates_note"] = "too few observations to date"
        return out
    obs = d["date"]
    gaps = []

    # --- seeding ---------------------------------------------------------------
    anchor = harvest or ws
    tr = curve[(curve["date"] >= anchor + timedelta(days=COVER_TROUGH_SEARCH[0])) &
               (curve["date"] <= anchor + timedelta(days=COVER_TROUGH_SEARCH[1]))]
    seed = None
    if not tr.empty:
        t = tr.loc[tr["value"].idxmin()]
        fall = curve[(curve["date"] >= t["date"]) &
                     (curve["date"] <= t["date"] + timedelta(days=COVER_FALL_SEARCH))]
        rise = float(fall["value"].max() - t["value"]) if len(fall) else 0.0
        if rise >= COVER_MIN_RISE and fall["value"].max() >= CC_GREEN_MIN:
            thr = t["value"] + 0.20 * rise
            up = fall[fall["value"] >= thr]
            cross = up["date"].iloc[0]
            last = min(anchor + timedelta(days=COVER_SEED_MAX),
                       pd.Timestamp(f"{y + 1}-{COVER_SEED_LAST}"))
            if cross <= last:
                seed = cross - timedelta(days=COVER_SEED_LAG)
                if harvest is not None and seed < harvest:
                    seed = harvest
                    notes.append("fall rise starts at harvest -- seeded at harvest, "
                                 "or interseeded into the standing crop (not separable)")
                gaps.append(_obs_gap(obs, cross))
            else:
                notes.append("fall rise too late to be establishment -- seeding not "
                             "dated (late-sown, or green-up only in spring)")
        else:
            notes.append("no fall green-up after harvest -- seeding not dated "
                         "(late-sown, or established only in spring)")
    else:
        notes.append("no post-harvest trough -- seeding not dated")

    # --- termination -----------------------------------------------------------
    term = None
    pre = curve[curve["date"] >= seg_end - timedelta(days=120)]
    if seed is not None:
        pre = pre[pre["date"] > seed]
    if not pre.empty:
        fl = pre.loc[pre["value"].idxmin()]
        hump = curve[(curve["date"] >= fl["date"] - timedelta(days=COVER_PEAK_SEARCH)) &
                     (curve["date"] < fl["date"])]
        # The hump has to be the cover: after it was sown, and inside the
        # off-season window -- never the tail of the cash crop before it.
        hump = hump[hump["date"] >= ws]
        if seed is not None:
            hump = hump[hump["date"] > seed]
        if not hump.empty:
            pk = hump.loc[hump["value"].idxmax()]
            drop = float(pk["value"] - fl["value"])
            if fl["value"] < CC_WATER_NDVI:
                # The fall ends in open water: a flooded field, not a terminated
                # cover. Dating it would put a spray date on a flood.
                notes.append("decline ends in standing water -- flooding, not "
                             "termination; not dated")
            elif drop >= COVER_MIN_DROP and pk["value"] >= CC_GREEN_MIN:
                mid = fl["value"] + 0.5 * drop
                dec = curve[(curve["date"] > pk["date"]) & (curve["date"] <= fl["date"]) &
                            (curve["value"] <= mid)]
                cross = dec["date"].iloc[0]
                term = max(cross - timedelta(days=COVER_TERM_LAG), pk["date"])
                gaps.append(_obs_gap(obs, cross))
                if planting is not None and term > planting:
                    notes.append("terminated after cash planting -- planted green")
            else:
                notes.append("no clear spring decline -- termination not dated "
                             "(cover ran into the cash crop, or too little green)")
    if term is None and not any("termination" in n for n in notes):
        notes.append("termination not dated")

    if cc_row["verdict"].startswith("green cover"):
        notes.append("if this was a small grain rather than a cover, these are its "
                     "planting and harvest")

    def _win(est, gap):
        w = max(14, int(np.ceil(gap)))
        return est - timedelta(days=w), est + timedelta(days=w)

    gi = iter(gaps)
    if seed is not None:
        out["seeding_est"] = seed
        out["seeding_lo"], out["seeding_hi"] = _win(seed, next(gi))
        if harvest is not None:
            out["seeding_lo"] = max(out["seeding_lo"], harvest)
    if term is not None:
        out["termination_est"] = term
        out["termination_lo"], out["termination_hi"] = _win(term, next(gi))
    if seed is not None and term is not None:
        out["cover_days"] = int((term - seed).days)

    # Never "high": nothing here is fitted to recorded dates yet.
    if gaps:
        out["dates_confidence"] = ("medium" if max(gaps) <= 14 and
                                   cc_row["verdict"] == "likely cover crop" else "low")
    out["dates_note"] = "; ".join(notes) or None
    return out


def cover_crop_all_years(ts: pd.DataFrame, phen: pd.DataFrame | None = None,
                         crops: dict[int, str] | None = None,
                         index: str = "ndvi") -> pd.DataFrame | None:
    """Run cover crop detection across every winter in the series.

    Each winter also gets seeding / termination estimates -- see
    :func:`cover_crop_dates`.
    """
    crops = crops or {}
    years = sorted(ts["date"].dt.year.unique())[:-1]   # last year has no spring yet
    rows = []
    for y in years:
        r = detect_cover_crop(ts, int(y), phen, crops.get(int(y) + 1), index)
        if r is not None:
            r.update(cover_crop_dates(ts, r, phen, index))
            rows.append(r)
    if not rows:
        return None
    out = pd.DataFrame(rows)
    for c in _DATE_KEYS:
        if c.endswith(("_est", "_lo", "_hi")):
            out[c] = pd.to_datetime(out[c])
    out["cover_days"] = out["cover_days"].astype("Int64")
    return out
