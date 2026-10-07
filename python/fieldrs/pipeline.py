"""One call that runs everything for a field.

This is the entry point a platform would wrap. It does the same work, in the
same order, with the same cache keys as the R pipeline, and returns plain
pandas objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, replace
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

import geopandas as gpd
import pandas as pd

from .aoi import load_field
from .cache import analysis_window
from .climate import (DRY_PR_MM, FORECAST_DAYS, HEAVY_RAIN_MM, HEAVY_RAIN_WET_DAYS,
                      gridmet_daily, weather_free_events,
                      weather_free_phenology)
from .cdl_split import SplitAdvice, cdl_split_advice
from .covercrop import cover_crop_all_years
from .cropland import CdlStack, cdl_history_from_stack, cdl_stack, crop_lookup
from .extract import extract_field_series
from .irrigation import add_to_history, irrigation_history
from .phenology import phenology_all_years
from .armor import armor_all_years, armor_series

Progress = Callable[[int, int, str], None] | None


@dataclass
class FieldResult:
    """Everything the pipeline knows about one field."""
    aoi: gpd.GeoDataFrame
    start: str
    end: str
    series: pd.DataFrame                  # one row per scene per index
    history: pd.DataFrame | None          # CDL rotation
    phenology: pd.DataFrame | None        # planting / harvest per season
    covercrop: pd.DataFrame | None        # one row per winter
    advice: SplitAdvice | None            # boundary check
    cdl: CdlStack | None = dc_field(repr=False, default=None)
    residue: pd.DataFrame | None = None   # soil armor / cover fractions per season
    residue_series: pd.DataFrame | None = dc_field(repr=False, default=None)
    weather: pd.DataFrame | None = dc_field(repr=False, default=None)  # gridMET daily
    # Settings of the weather date check, or None when it did not run:
    # {"dry_mm": float, "wind_max_kmh": float | None}.
    weather_check: dict | None = None
    source: str = "sentinel2"             # imagery source of the series
    irrigation: pd.DataFrame | None = None  # USGS irrigated share per map year

    @property
    def area_ha(self) -> float:
        return float(self.aoi["area_ha"].sum())

    @property
    def summary(self) -> pd.DataFrame:
        """One row per season -- the table a platform would surface."""
        if self.phenology is None:
            return pd.DataFrame()
        p = self.phenology
        cc = self.covercrop

        def winter_for(y: int, col: str = "verdict"):
            if cc is None or col not in cc:
                return None
            m = cc[cc["fall_year"] == y]
            return None if m.empty else m[col].iloc[0]

        def irrigated_for(y: int):
            h = self.history
            if h is None or "irrigated" not in h:
                return None
            m = h[h["year"] == y]
            if m.empty or pd.isna(m["irrigation_map"].iloc[0]):
                return None
            return (f"{m['irrigated'].iloc[0]} ({int(m['irrigation_map'].iloc[0])} map; "
                    f"irrigated in {m['irrigated_maps'].iloc[0]} maps)")

        # Cover crop dates for the winter after each season: rain-free when
        # the check ran, estimates otherwise.
        seed_col = "seeding_date" if cc is not None and "seeding_date" in cc else "seeding_est"
        term_col = ("termination_date" if cc is not None and "termination_date" in cc
                    else "termination_est")

        # Rain-free final dates when the weather check ran, NDVI estimates
        # otherwise -- see climate.weather_free_phenology.
        rain = "planting_date" in p
        return pd.DataFrame({
            "year": p["year"],
            "crop": p["crop"],
            "planting_date": p["planting_date"] if rain else p["planting_est"],
            "harvest_date": p["harvest_date"] if rain else p["harvest_est"],
            **({"planting_shift_d": p["planting_shift_d"],
                "harvest_shift_d": p["harvest_shift_d"]} if rain else {}),
            "season_type": p.get("season_type"),
            "season_days": p["season_days"],
            "season_days_final": p.get("season_days_final"),
            "peak_ndvi": p["peak_ndvi"],
            "fallow_days": p.get("fallow_days"),
            "irrigated": [irrigated_for(int(y)) for y in p["year"]],
            "following_winter": [winter_for(int(y)) for y in p["year"]],
            "cover_seeding": pd.to_datetime([winter_for(int(y), seed_col) for y in p["year"]]),
            "cover_termination": pd.to_datetime([winter_for(int(y), term_col)
                                                 for y in p["year"]]),
            "confidence": p["confidence"],
        })

    # Tables that carry weather-checked dates, and so are written as two blocks.
    _BLOCK_TABLES = ("summary", "phenology", "covercrop")

    def table_csv(self, table: str) -> str:
        """``summary``, ``phenology`` or ``covercrop`` as CSV text, for download
        or for ``<table>.csv``.

        Without the weather check this is the table as it stands. With it, two
        blocks one under the other, each with its own title row and header:
        first the table without the weather check (the NDVI estimates), then
        the weather-checked one with the shifted dates -- so the two can be
        read side by side in a spreadsheet. A blank line separates them.
        """
        if table not in self._BLOCK_TABLES:
            raise ValueError(f"table must be one of {self._BLOCK_TABLES}")
        checked = getattr(self, table)
        if checked is None:
            return ""
        if self.weather_check is None:
            return checked.to_csv(index=False)
        unchecked = getattr(apply_rain_check(self, rain_free=False), table)
        wc = self.weather_check
        rule = f"rain <= {wc['dry_mm']:g} mm"
        if wc.get("wind_max_kmh") is not None:
            rule += f" and daily-mean wind < {wc['wind_max_kmh']:g} km/h"
        if wc.get("forecast_days") is not None:
            rule += (f"; moved earlier by at most {wc['forecast_days']} d "
                     "(forecast horizon), else after")
        if wc.get("heavy_mm") is not None and wc.get("wet_days"):
            rule += (f"; not within {wc['wet_days']} d after >= {wc['heavy_mm']:g} mm "
                     "(wet soil)")
        title2 = (f"Weather-checked dates (gridMET: {rule}; moved to the last such "
                  "day before the weather, inside the uncertainty window)")
        if self.weather is None:
            title2 += " -- gridMET was unavailable, dates NOT checked"
        elif self.weather.attrs.get("errors"):
            title2 += (" -- gridMET unavailable for "
                       f"{', '.join(map(str, self.weather.attrs['errors']))}, those "
                       "seasons NOT checked")
        blocks = [("Dates without weather check (NDVI estimates)", unchecked),
                  (title2, checked)]
        return "\n".join(f"{_csv_cell(t)}\n{df.to_csv(index=False)}"
                         for t, df in blocks)

    def summary_csv(self) -> str:
        """:meth:`table_csv` for the summary."""
        return self.table_csv("summary")

    def write(self, out_dir: str | Path) -> list[Path]:
        """Write every table to CSV. Returns the paths written."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        tables = {
            "summary.csv": self.summary,
            "series.csv": self.series,
            "cdl_history.csv": self.history,
            "phenology.csv": self.phenology,
            "covercrop.csv": self.covercrop,
            "cdl_by_year.csv": None if self.advice is None else self.advice.per_year,
            "soil_armor.csv": self.residue,
            "irrigation.csv": self.irrigation,
            "weather_gridmet.csv": self.weather,
        }
        for name, df in tables.items():
            if df is None or len(df) == 0:
                continue
            path = out / name
            if name[:-4] in self._BLOCK_TABLES:
                path.write_text(self.table_csv(name[:-4]))
            else:
                df.to_csv(path, index=False)
            written.append(path)
        return written


def _csv_cell(text: str) -> str:
    """One CSV cell, quoted -- block titles contain commas and semicolons."""
    return '"' + text.replace('"', '""') + '"'


def analyze_field(
    field: str | Path | gpd.GeoDataFrame,
    years: tuple[int, int] = (2020, None),
    indices: Sequence[str] = ("ndvi",),
    workers: int = 8,
    only_cached: bool = False,
    residue: bool = False,
    rain_free: bool = True,
    dry_mm: float = DRY_PR_MM,
    wind_max_kmh: float | None = None,
    forecast_days: int | None = FORECAST_DAYS,
    heavy_mm: float | None = HEAVY_RAIN_MM,
    wet_days: int = HEAVY_RAIN_WET_DAYS,
    progress: Progress = None,
    source: str = "sentinel2",
) -> FieldResult | None:
    """Run the whole pipeline for one field.

    ``only_cached=True`` returns ``None`` unless every stage is already cached,
    which is how a UI opens a pre-computed field without starting a long read.

    ``source`` picks the imagery: ``"sentinel2"`` (the original, 10 m) or
    ``"hls"`` (Sentinel-2 + Landsat 8/9 harmonised, 30 m; denser in time,
    coarser in space -- see imagery.py). CDL and the residue indices are not
    affected; residue reads Sentinel-2 either way.

    ``residue=True`` adds the SWIR residue/tillage indices. It is off by
    default because it is a second extraction over a second set of bands --
    see residue.py -- and the numbers it produces are uncalibrated.

    ``rain_free=True`` (the default) reads daily gridMET precipitation at the
    field centroid and moves each planting or harvest date that falls on a
    rain day (more than ``dry_mm``) to the last dry day before the rain, inside
    its uncertainty window -- see
    climate.py. A weather service failure does not stop the run; the dates are
    then left as NDVI estimates and the notes say so. ``wind_max_kmh`` adds
    the wind check: a day whose gridMET daily-mean wind reaches it is not a
    field-work day either (climate.WIND_MAX_KMH is about 20 mph).
    """
    aoi = field if isinstance(field, gpd.GeoDataFrame) else load_field(field)

    y_from, y_to = years
    y_to = y_to or date.today().year
    start, end = analysis_window(y_from, y_to)
    cdl_years = list(range(y_from, min(y_to, date.today().year - 1) + 1))

    stack = cdl_stack(aoi, cdl_years, only_cached=only_cached) if cdl_years else None
    if only_cached and cdl_years and stack is None:
        return None

    series = extract_field_series(aoi, start, end, indices=indices,
                                  workers=workers, only_cached=only_cached,
                                  progress=progress, source=source)
    if series is None:
        return None

    history = cdl_history_from_stack(stack) if stack is not None else None
    # Irrigation is a local read and never blocks the run.
    try:
        irr = irrigation_history(aoi)
    except Exception as exc:                          # noqa: BLE001
        print(f"  Irrigation maps unreadable, skipped: {exc}", flush=True)
        irr = None
    history = add_to_history(history, irr)
    crops = crop_lookup(history) if history is not None else {}
    phen = phenology_all_years(series, crops)
    cc = cover_crop_all_years(series, phen, crops)
    advice = cdl_split_advice(stack) if stack is not None else None

    res_ts = res = None
    if residue:
        res_ts = armor_series(aoi, (y_from, y_to), workers=workers,
                              only_cached=only_cached, progress=progress)
        if res_ts is None and only_cached:
            return None
        if res_ts is not None:
            res = armor_all_years(res_ts, phen)

    result = FieldResult(aoi=aoi, start=start, end=end, series=series,
                         history=history, phenology=phen, covercrop=cc,
                         advice=advice, cdl=stack, residue=res,
                         residue_series=res_ts, source=source, irrigation=irr)
    return apply_rain_check(result, rain_free, dry_mm, wind_max_kmh, forecast_days,
                            heavy_mm, wet_days)


# Columns rain_free_phenology() adds; stripped before re-applying so the check
# can be switched on, off and on again on the same result.
# Columns the rain step adds; stripped before re-applying so the check can be
# switched on, off and on again on the same result.
def _rain_cols(events):
    return [f"{ev}_{c}" for ev in events
            for c in ("date", "shift_d", "pr_mm", "wind_kmh", "weather_note")]


_RAIN_COLS = _rain_cols(("planting", "harvest")) + ["season_days_final"]
_CC_RAIN_COLS = _rain_cols(("seeding", "termination")) + ["cover_days_final"]


def _days(a: pd.Series, b: pd.Series) -> pd.Series:
    return (pd.to_datetime(b) - pd.to_datetime(a)).dt.days.astype("Int64")


def apply_rain_check(result: FieldResult, rain_free: bool = True,
                     dry_mm: float = DRY_PR_MM,
                     wind_max_kmh: float | None = None,
                     forecast_days: int | None = FORECAST_DAYS,
                     heavy_mm: float | None = HEAVY_RAIN_MM,
                     wet_days: int = HEAVY_RAIN_WET_DAYS) -> FieldResult:
    """The weather date step (rain, optionally wind) on its own, as a new result.

    It is the last step of :func:`analyze_field` and touches nothing upstream:
    the NDVI series, CDL, phenology and cover crop estimates are the same either
    way. So a UI switching the check on or off calls this on the result it
    already has instead of running the pipeline again -- that is instant, and
    cannot come back "not cached". The input is never modified, and calling it
    on a result that already had the check applied replaces the earlier one.

    Dates covered: cash crop planting and harvest (phenology table) and cover
    crop seeding and termination (cover crop table). A cover crop's seeding
    window never opens before the cash crop's final harvest date.

    ``wind_max_kmh=None`` checks rain only; a number also rules out days whose
    gridMET daily-mean wind reaches it. Every date moves earlier by at most
    ``forecast_days`` (a forecast is good for about five days); beyond that it
    moves after the weather instead. The ``wet_days`` day(s) after a rain of at
    least ``heavy_mm`` are not workable either (wet soil). Both modes use the same cached weather,
    so switching between them is as instant as switching the check off.

    Also sets ``season_days_final`` (planting to harvest) and
    ``cover_days_final`` (seeding to termination) on the final dates -- the
    rain-free ones when the check is on, the estimates when it is off.
    ``season_days`` is unchanged either way; it is NDVI green-up to the
    harvest estimate, the canopy season the imagery measures.
    """
    phen, cc = result.phenology, result.covercrop
    if phen is not None:
        phen = phen.drop(columns=[c for c in _RAIN_COLS if c in phen])
    if cc is not None:
        cc = cc.drop(columns=[c for c in _CC_RAIN_COLS if c in cc])
    weather = None
    if rain_free and phen is not None:
        try:
            weather = gridmet_daily(result.aoi, result.start, result.end)
        except Exception as exc:                      # noqa: BLE001
            print(f"  gridMET unavailable, dates left as estimates: {exc}",
                  flush=True)
        else:
            for y, msg in weather.attrs.get("errors", {}).items():
                print(f"  gridMET {y} unavailable, that year's dates left as "
                      f"estimates: {msg}", flush=True)
        phen = weather_free_phenology(phen, weather, dry_mm, wind_max_kmh, forecast_days,
                                      heavy_mm, wet_days)
        if cc is not None and "seeding_est" in cc:
            harv = phen.set_index("year")["harvest_date"]
            cc = weather_free_events(cc, weather, ("seeding", "termination"), dry_mm,
                                     wind_max_kmh,
                                     not_before={"seeding": cc["fall_year"].map(harv)},
                                     forecast_days=forecast_days,
                                     heavy_mm=heavy_mm, wet_days=wet_days)
    if phen is not None:
        phen["season_days_final"] = _days(
            phen["planting_date"] if "planting_date" in phen else phen["planting_est"],
            phen["harvest_date"] if "harvest_date" in phen else phen["harvest_est"])
    if cc is not None and "seeding_est" in cc:
        cc["cover_days_final"] = _days(
            cc["seeding_date"] if "seeding_date" in cc else cc["seeding_est"],
            cc["termination_date"] if "termination_date" in cc else cc["termination_est"])
    check = ({"dry_mm": dry_mm, "wind_max_kmh": wind_max_kmh,
              "forecast_days": forecast_days, "heavy_mm": heavy_mm,
              "wet_days": wet_days}
             if rain_free and phen is not None else None)
    return replace(result, phenology=phen, covercrop=cc, weather=weather,
                   weather_check=check)
