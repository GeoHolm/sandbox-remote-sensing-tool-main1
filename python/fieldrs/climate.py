"""Daily gridMET weather for a field, and rain-free (and calm) field-work dates.

WHERE THE DATA COMES FROM
gridMET (Abatzoglou 2013) is a 4 km daily surface meteorology grid for CONUS,
1979 to roughly two days ago. It is read through the CSIP climate service at
Colorado State, which takes one point and a date range and answers with a daily
table -- see :data:`GRIDMET_URL`. The point is the field centroid; at 4 km a
field almost always sits inside one grid cell, so the centroid is the field.

WHY RAIN-FREE DATES
NDVI dates the canopy, not the planter or the combine, and lands within about
two weeks (phenology.py). Fieldwork does not happen on a rain day, so within
that uncertainty window a rain day is the least likely answer. The final dates
are therefore the NDVI estimate moved, when it falls on a rain day, to the
last rain-free day before that rain -- a farmer reads the forecast and acts
ahead of it. Only if the window has no dry day before the rain does the date
move after it instead. It never leaves its own window, so the weather cannot
override the imagery.

WIND, OPTIONALLY
With a wind limit set, a workable day must also be calm: its gridMET wind below
the limit (default :data:`WIND_MAX_KMH`, about 20 mph). The date moves ahead of
the windy day exactly as it moves ahead of rain.

gridMET has one wind variable, ``vs``: the DAILY MEAN speed at 10 m. It has no
daily maximum and no gusts, and nothing else in the CSIP climate catalogue
gives historical gusts at a point. The limit is therefore applied to the daily
mean. That catches the clearly windy days -- a day averaging 30 km/h gusts far
higher -- but not a moderate day with gusty spells. In Iowa the daily mean
reaches 30 km/h on about 8% of April-May days; in south Georgia almost never.

WHAT IT DOES NOT DO
It does not model soil workability: a dry day straight after 40 mm is still
too wet to plant. "Rain-free" here means the day's own gridMET precipitation
is at or below :data:`DRY_PR_MM`, nothing more.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import time
from datetime import date, timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
from csip import Client

from .cache import cache_get, cache_put

GRIDMET_URL = os.environ.get(
    "GRIDMET_URL", "https://csip.engr.colostate.edu:9088/csip-climate/d/gridmet/2.0")

# A day counts as rain-free at or below this daily total (mm). Zero is the
# literal reading of "rain-free"; gridMET reports to 0.1 mm.
DRY_PR_MM = 0.0

# A day is too windy at or above this daily-mean wind (km/h); 30 km/h is about
# 20 mph. Only used when the wind check is on -- see the module docstring for
# why it is a daily mean and not a gust.
WIND_MAX_KMH = 30.0

# Requested every time the weather check runs, so switching between "rain" and
# "rain and wind" never needs a second request.
GRIDMET_OUTPUTS = ("pr", "vs")

# How far ahead a farmer can plan from a forecast. A weather forecast is
# usable for about five days, so a planting or seeding brought forward ahead of
# rain is brought forward at most this far; if the last workable day is further
# back than that, the farmer would not have known to go early, and waits until
# after the weather instead. Applies to every field operation dated here.
FORECAST_DAYS = 5
FORECAST_EVENTS = ("planting", "seeding", "harvest", "termination")

# After a heavy rain the soil stays too wet to carry equipment for a while, so
# the day(s) after it are not workable even when dry. 25 mm is one inch -- the
# usual rule-of-thumb line for "too wet to get in tomorrow".
HEAVY_RAIN_MM = 25.0
HEAVY_RAIN_WET_DAYS = 1

GRIDMET_FIRST_YEAR = 1979

# gridMET publishes with a few days' lag and replaces its provisional recent
# days for a while after. A year is cached for good only once this many days of
# the following year have passed; before that it is cached per day like the
# current year, so a year fetched on 2 January does not keep a hole at the end
# of December forever.
GRIDMET_SETTLE_DAYS = 60


def field_centroid(aoi: gpd.GeoDataFrame) -> tuple[float, float]:
    """(lon, lat) of the field centroid, taken in an equal-area projection."""
    c = aoi.to_crs(5070).geometry.union_all().centroid
    p = gpd.GeoSeries([c], crs=5070).to_crs(4326).iloc[0]
    return float(p.x), float(p.y)


class GridmetError(RuntimeError):
    """A gridMET request that did not produce usable weather.

    ``transient`` is True for failures worth retrying (timeouts, connection
    errors, HTTP 429/5xx) and False for ones that will fail the same way again
    (a 4xx, a service-side failure, an empty reply).
    """

    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


# csip.Client does not raise on failure: it returns a client whose http_status
# is the HTTP code, or one of these negative codes for transport errors.
_CSIP_HTTP = {-1: "timed out", -2: "connection error",
              -3: "request error or invalid reply", -4: "HTTP error"}
_TRANSIENT_HTTP = {-1, -2, 429, 500, 502, 503, 504}

# Our own retry, with a pause between attempts. The client's built-in retry
# fires again immediately, which does not help with a service that is briefly
# down, and it does not retry 5xx at all -- so it is turned off (http_retry=1).
GRIDMET_TRIES = 3
GRIDMET_BACKOFF = (2, 5)        # seconds before attempts 2 and 3


def _execute(c: Client, timeout: float) -> Client:
    """One POST through the client, with its console chatter captured.

    On a connection error the client prints the underlying exception to stdout
    -- once per attempt -- and returns only a status code. Capture it, so it
    neither clutters the app's log nor gets lost: it goes into the error.
    """
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            r = c.execute(GRIDMET_URL, conf={"http_conn_timeout": min(timeout, 10),
                                             "service_timeout": timeout,
                                             "http_retry": 1})
    except Exception as exc:                          # noqa: BLE001
        # Not expected from the client, but it is third-party code; anything
        # it raises is a failed request, not a crash of the pipeline.
        raise GridmetError(f"gridMET request failed: {exc}", transient=True) from exc

    http = r.get_http_status()
    if http != 200:
        detail = buf.getvalue().strip().splitlines()
        cause = f" -- {detail[-1][:200]}" if detail else ""
        raise GridmetError(
            f"gridMET service unreachable: {_CSIP_HTTP.get(http, f'HTTP {http}')} "
            f"({GRIDMET_URL}){cause}", transient=http in _TRANSIENT_HTTP)
    if r.is_failed():
        raise GridmetError(f"gridMET service failed: {r.get_error() or 'no message'}")
    if not r.is_finished():
        raise GridmetError(f"gridMET service did not finish: status {r.get_status()}")
    return r


def _request(lon: float, lat: float, start: str, end: str,
             outputs: tuple[str, ...], timeout: float) -> pd.DataFrame:
    """One gridMET request through the CSIP client library (``pip install csip``).

    Raises :class:`GridmetError` rather than returning anything that should not
    be cached -- which matters because the service answers "Finished" with an
    empty table for a point outside CONUS, dates outside its record or a
    malformed date, and with all-null columns for an unknown variable.
    """
    c = Client()
    c.add_data("location", {"type": "Point", "coordinates": [lon, lat]})
    c.add_data("outputs", list(outputs))
    c.add_data("units", "metric")
    # geojson returns the table inline; "file" returns a link to fetch.
    c.add_data("output_type", "geojson")
    c.add_data("start_date", start)
    c.add_data("end_date", end)

    for attempt in range(1, GRIDMET_TRIES + 1):
        try:
            r = _execute(c, timeout)
            break
        except GridmetError as exc:
            if not exc.transient or attempt == GRIDMET_TRIES:
                raise
            time.sleep(GRIDMET_BACKOFF[attempt - 1])

    data = r.get_data_value("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise GridmetError("gridMET reply has no data table.")
    header, rows = data[0], data[1:]
    if not rows:
        raise GridmetError(
            f"gridMET returned no days for ({lon:.4f}, {lat:.4f}) {start} to {end}. "
            "gridMET covers CONUS land only, 1979 to about two days ago.")

    df = pd.DataFrame(rows, columns=header)
    # "pr (mm)" -> "pr_mm", "vs (m/s)" -> "vs_ms", "tmmx (K)" -> "tmmx_k"
    def _name(h: str) -> str:
        var, _, unit = h.partition(" (")
        unit = re.sub(r"[^a-z0-9]+", "", unit.lower())
        return f"{var.lower()}_{unit}" if unit else var.lower()
    df.columns = ["date"] + [_name(c) for c in header[1:]]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for v in outputs:
        col = next((k for k in df.columns if k.split("_")[0] == v), None)
        if col is None or pd.to_numeric(df[col], errors="coerce").isna().all():
            raise GridmetError(f"gridMET returned no values for '{v}' "
                               f"({start} to {end}) -- unknown variable or no coverage.")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def gridmet_daily(aoi: gpd.GeoDataFrame, start: str, end: str,
                  outputs: tuple[str, ...] = GRIDMET_OUTPUTS,
                  timeout: float = 60.0) -> pd.DataFrame:
    """Daily gridMET at the field centroid, ``start`` to ``end`` inclusive.

    Fetched one calendar year per request. Settled years are cached for good;
    the current year -- and the previous one, until :data:`GRIDMET_SETTLE_DAYS`
    into the new year -- is cached per day, so it is asked again at most once a
    day as new and revised days arrive. A failed request caches nothing.

    A year that fails is skipped rather than sinking the rest: its seasons get
    "no gridMET data" notes, and ``.attrs["errors"]`` maps year -> message.
    Raises :class:`GridmetError` only when every year failed.
    """
    lon, lat = field_centroid(aoi)
    today = date.today()
    s, e = pd.Timestamp(start).date(), min(pd.Timestamp(end).date(), today)
    parts, errors = [], {}
    for y in range(max(s.year, GRIDMET_FIRST_YEAR), e.year + 1):
        ys, ye = date(y, 1, 1), min(date(y, 12, 31), today)
        settled = today >= date(y + 1, 1, 1) + timedelta(days=GRIDMET_SETTLE_DAYS)
        stamp = "final" if settled else today.isoformat()
        key = f"{lon:.4f}_{lat:.4f}_{y}_{'-'.join(outputs)}_{stamp}"
        df = cache_get(key, "gridmet")
        if df is None:
            try:
                df = cache_put(key, _request(lon, lat, ys.isoformat(), ye.isoformat(),
                                             outputs, timeout), "gridmet")
            except GridmetError as exc:
                errors[y] = str(exc)
                continue
        parts.append(df)
    if not parts:
        if errors:
            first = next(iter(errors.values()))
            raise GridmetError(f"no gridMET data for any year: {first}")
        return pd.DataFrame(columns=["date"])
    out = pd.concat(parts, ignore_index=True)
    out = out[(out["date"] >= pd.Timestamp(s)) & (out["date"] <= pd.Timestamp(e))] \
        .reset_index(drop=True)
    if "vs_ms" in out:
        out["wind_kmh"] = (out["vs_ms"] * 3.6).round(1)
    out.attrs["errors"] = errors
    return out


def _wet_soil(weather: pd.DataFrame, heavy_mm: float | None,
              wet_days: int) -> pd.DataFrame:
    """Per day: the heavy rain (mm, date) that leaves the soil too wet, if any.

    A day is blocked when one of the ``wet_days`` days before it had at least
    ``heavy_mm``. The most recent such day is reported.
    """
    out = pd.DataFrame({"wet_mm": np.nan, "wet_on": pd.NaT}, index=weather.index)
    if heavy_mm is None or wet_days <= 0 or "pr_mm" not in weather:
        return out
    pr = weather["pr_mm"]
    for k in range(wet_days, 0, -1):          # nearest last, so it wins
        prev = pr.shift(k, freq="D").reindex(weather.index)
        hit = prev >= heavy_mm
        out.loc[hit, "wet_mm"] = prev[hit]
        out.loc[hit, "wet_on"] = weather.index[hit] - pd.Timedelta(days=k)
    return out


def workable_day_before(est, lo, hi, weather: pd.DataFrame,
                        dry_mm: float = DRY_PR_MM,
                        wind_max_kmh: float | None = None,
                        max_lead: int | None = None,
                        heavy_mm: float | None = HEAVY_RAIN_MM,
                        wet_days: int = HEAVY_RAIN_WET_DAYS
                        ) -> tuple[pd.Timestamp | None, str]:
    """Field-work day for an event estimated at ``est``, within ``[lo, hi]``.

    A day is workable when its rain is at most ``dry_mm`` and, if
    ``wind_max_kmh`` is set, its daily-mean wind is below it. A workable ``est``
    stays put. Otherwise the date moves to the last workable day *before* it --
    a farmer working from the forecast acts ahead of the rain or wind, not
    after. Only when the window has no workable day before ``est`` does it move
    to the first one after, and the note says so.

    ``max_lead`` (days) is the forecast horizon: the date moves earlier by at
    most that much. If the last workable day before ``est`` is further back,
    it moves to the first workable day after instead -- and only if there is
    none after either does it take the earlier day, noting it is beyond the
    forecast.

    ``heavy_mm`` / ``wet_days``: a day within ``wet_days`` after a day with at
    least ``heavy_mm`` of rain is not workable either -- the soil is too wet --
    wherever the date would land.

    ``weather`` is indexed by date with ``pr_mm`` (and ``wind_kmh`` for the wind
    check). Returns the date and a short note, or ``(None, note)`` when the
    window has no weather data or no workable day at all.
    """
    if est is None or pd.isna(est):
        return None, ""
    est = pd.Timestamp(est)
    lo = pd.Timestamp(lo) if lo is not None and pd.notna(lo) else est
    hi = pd.Timestamp(hi) if hi is not None and pd.notna(hi) else est
    wind = wind_max_kmh is not None
    cols = ["pr_mm", "wind_kmh"] if wind else ["pr_mm"]
    if any(c not in weather for c in cols):
        return None, "no gridMET data for window"
    wet = (weather[["wet_mm", "wet_on"]] if "wet_mm" in weather
           else _wet_soil(weather, heavy_mm, wet_days))
    w = weather.loc[(weather.index >= lo) & (weather.index <= hi), cols].dropna()
    if w.empty:
        return None, "no gridMET data for window"
    ok = w["pr_mm"] <= dry_mm
    if wind:
        ok &= w["wind_kmh"] < wind_max_kmh
    ok &= wet["wet_mm"].reindex(w.index).isna()
    good = w.index[ok]
    what = "rain-free and calm" if wind else "rain-free"
    if good.empty:
        return None, f"no {what} day in window ({len(w)} d)"
    if est in good:
        return est, what

    # Why the estimate itself was not workable.
    why, ahead = [], []
    if est in w.index:
        pr = w.at[est, "pr_mm"]
        if pr > dry_mm:
            why.append(f"{pr:.1f} mm"); ahead.append("rain")
        if wind and w.at[est, "wind_kmh"] >= wind_max_kmh:
            why.append(f"{w.at[est, 'wind_kmh']:.0f} km/h mean wind"); ahead.append("wind")
        why = f"{', '.join(why)} on estimate" if why else ""
        wmm = wet["wet_mm"].get(est, np.nan)
        if pd.notna(wmm):
            soil = f"soil wet after {wmm:.0f} mm on {wet['wet_on'][est]:%m-%d}"
            why = f"{why}; {soil}" if why else soil
            if "rain" not in ahead:
                ahead.append("rain")
    else:
        why, ahead = "no data on estimate", ["weather"]
    ahead = " and ".join(ahead)

    before = good[good < est]
    after = good[good > est]
    near = (before if max_lead is None
            else before[before >= est - pd.Timedelta(days=max_lead)])
    if len(near):
        best = near.max()
        return best, f"moved {int((best - est).days):+d} d, ahead of {ahead} ({why})"
    if len(after):
        best = after.min()
        reason = (f"no {what} day within the {max_lead}-day forecast before it"
                  if len(before) else f"no {what} day before it in window")
        return best, (f"moved {int((best - est).days):+d} d, after {ahead} -- "
                      f"{reason} ({why})")
    best = before.max()
    return best, (f"moved {int((best - est).days):+d} d, ahead of {ahead} -- beyond the "
                  f"{max_lead}-day forecast, but no {what} day after it in window ({why})")


def dry_day_before_rain(est, lo, hi, rain: pd.Series,
                        dry_mm: float = DRY_PR_MM) -> tuple[pd.Timestamp | None, str]:
    """Rain-only :func:`workable_day_before`, given daily rain (mm) by date."""
    return workable_day_before(est, lo, hi, rain.rename("pr_mm").to_frame(), dry_mm)


def weather_free_events(df: pd.DataFrame | None, weather: pd.DataFrame | None,
                        events: tuple[str, ...], dry_mm: float = DRY_PR_MM,
                        wind_max_kmh: float | None = None,
                        not_before: dict[str, pd.Series] | None = None,
                        forecast_days: int | None = FORECAST_DAYS,
                        heavy_mm: float | None = HEAVY_RAIN_MM,
                        wet_days: int = HEAVY_RAIN_WET_DAYS
                        ) -> pd.DataFrame | None:
    """Add final field-work dates for each ``<event>_est`` / ``_lo`` / ``_hi``.

    New columns, per event:

    - ``<event>_date``  final date: the estimate, or if that day is rainy (or
      windy, with ``wind_max_kmh``) the last workable day before it inside
      ``<event>_lo``..``<event>_hi`` (see :func:`workable_day_before`). Left as
      the estimate when no workable day can be found, and the note says so.
    - ``<event>_shift_d``  days moved from the estimate.
    - ``<event>_pr_mm``  gridMET precipitation on the final date.
    - ``<event>_wind_kmh``  gridMET daily-mean wind on the final date.
    - ``<event>_weather_note``  what happened.

    ``not_before`` optionally raises an event's window start per row -- a cover
    crop cannot be sown before the cash crop's final harvest date, whichever
    way that harvest moved. ``forecast_days`` limits how far any event in
    FORECAST_EVENTS moves earlier; None removes the limit. ``heavy_mm`` and
    ``wet_days`` keep dates off the wet day(s) after a heavy rain; None for
    ``heavy_mm`` turns that off. The estimate columns are never modified.
    """
    if df is None or not len(df):
        return df
    out = df.copy()
    wx = (pd.DataFrame(columns=["pr_mm", "wind_kmh"]) if weather is None
          else weather.set_index("date"))
    if weather is not None:
        wx = wx.join(_wet_soil(wx, heavy_mm, wet_days))
    not_before = not_before or {}

    def _at(day, col):
        v = wx[col].get(day, np.nan) if col in wx else np.nan
        return None if pd.isna(v) else float(v)

    for ev in events:
        finals, shifts, prs, winds, notes = [], [], [], [], []
        floor = not_before.get(ev)
        for i, r in out.iterrows():
            est = r.get(f"{ev}_est")
            if est is None or pd.isna(est):
                finals.append(pd.NaT); shifts.append(None); prs.append(None)
                winds.append(None); notes.append(None)
                continue
            lo = r.get(f"{ev}_lo")
            if floor is not None and pd.notna(floor.get(i)):
                lo = max(pd.Timestamp(lo), floor[i]) if pd.notna(lo) else floor[i]
            if weather is None:
                d, note = None, "gridMET unavailable"
            else:
                d, note = workable_day_before(
                    est, lo, r.get(f"{ev}_hi"), wx, dry_mm, wind_max_kmh,
                    forecast_days if ev in FORECAST_EVENTS else None,
                    heavy_mm, wet_days)
            final = d if d is not None else pd.Timestamp(est)
            finals.append(final)
            shifts.append(int((final - pd.Timestamp(est)).days))
            prs.append(_at(final, "pr_mm"))
            winds.append(_at(final, "wind_kmh"))
            notes.append(note)
        out[f"{ev}_date"] = pd.to_datetime(pd.Series(finals, index=out.index))
        out[f"{ev}_shift_d"] = pd.array(shifts, dtype="Int64")
        out[f"{ev}_pr_mm"] = prs
        out[f"{ev}_wind_kmh"] = winds
        out[f"{ev}_weather_note"] = notes
    return out


def weather_free_phenology(phen: pd.DataFrame | None, weather: pd.DataFrame | None,
                           dry_mm: float = DRY_PR_MM,
                           wind_max_kmh: float | None = None,
                           forecast_days: int | None = FORECAST_DAYS,
                           heavy_mm: float | None = HEAVY_RAIN_MM,
                           wet_days: int = HEAVY_RAIN_WET_DAYS) -> pd.DataFrame | None:
    """Final planting and harvest dates -- :func:`weather_free_events` on the
    phenology table. ``planting_est`` / ``harvest_est`` are left untouched; they
    are the imagery's answer, and everything else in the package keys off them.
    """
    return weather_free_events(phen, weather, ("planting", "harvest"), dry_mm,
                               wind_max_kmh, forecast_days=forecast_days,
                               heavy_mm=heavy_mm, wet_days=wet_days)


# Earlier names, kept so code written against them keeps working.
rain_free_events = weather_free_events
rain_free_phenology = weather_free_phenology
