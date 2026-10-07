"""The report pack: everything about one field in one zip.

Port of the R app's "Download report pack (ZIP)". It holds the charts as PNG,
every table as CSV, the raw per-date series behind them, the boundary, and a
written briefing (README.md) aimed at an AI assistant that will turn the pack
into a slide deck or short report -- including what it must NOT claim.

A chart or table that was not produced is left out rather than shipped blank:
an empty CSV reads as "we measured nothing", which is a different claim from
"we did not measure".
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Callable

import pandas as pd

# Figure name -> caption, in pack order. Names and captions follow the R app.
FIGURES = {
    "cdl-maps-by-year": "One CDL crop map per year, clipped to the field. One "
                        "color filling it every year means one management unit.",
    "boundary-disagreement": "Where the boundary disagrees with itself. Pale "
                             "agrees every year; a persistent red block is a second field.",
    "data-availability": "Every satellite acquisition over this field, by source. "
                         "Shows what exists, before cloud filtering.",
    "imagery-contact-sheet": "Every clear scene in one quarter. The visual proof "
                             "that the numbers come from real imagery.",
    "season-markers": "NDVI through each season with estimated planting and "
                      "harvest marked (dashed); solid lines are the weather-checked "
                      "final dates where that check ran.",
    "cover-crop-winters": "Every winter on a shared Oct-to-Jun axis. A hump above "
                          "the residue floor is off-season green cover.",
    "soil-armor-by-year": "Cover fractions through each calendar year. Teal is "
                          "living, tan is residue, white to the top is bare soil. "
                          "The shaded band is the pre-planting window the headline "
                          "figure averages over.",
}


def _png(fig) -> bytes:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def md_table(d: pd.DataFrame | None, cols: list[str] | None = None) -> str:
    """A table as Markdown -- R's md_table()."""
    if d is None or not len(d):
        return "_Not produced in this session._\n"
    d = d[[c for c in (cols or d.columns) if c in d.columns]].copy()

    def cell(x):
        if x is None or (not isinstance(x, str) and pd.isna(x)):
            return ""
        if isinstance(x, pd.Timestamp):
            return x.strftime("%Y-%m-%d")
        return str(x).replace("|", "/").strip()
    head = "| " + " | ".join(d.columns) + " |\n|" + "|".join("---" for _ in d.columns) + "|\n"
    body = "\n".join("| " + " | ".join(cell(x) for x in row) + " |"
                     for row in d.itertuples(index=False))
    return head + body + "\n"


def build_report_pack(result, *, name: str = "Uploaded boundary", shows: str = "",
                      years: tuple[int, int] | None = None,
                      avail: pd.DataFrame | None = None,
                      armor_ts: pd.DataFrame | None = None,
                      armor_res: pd.DataFrame | None = None,
                      extra_figures: dict[str, bytes] | None = None,
                      progress: Callable[[float, str], None] | None = None) -> tuple[bytes, list[str]]:
    """Build the pack for one analysed field.

    ``result`` is a FieldResult (weather check applied or not). Charts are
    redrawn from the data so a pack does not depend on which tabs were opened,
    except the imagery contact sheet, which only exists if it was shown --
    pass it in ``extra_figures``. Returns the zip bytes and the figure names
    actually drawn.
    """
    from . import viz
    from .catalog import catalog_summary

    figs: dict[str, Callable[[], object]] = {
        "cdl-maps-by-year": (lambda: viz.plot_cdl_matrix(result.cdl)) if result.cdl is not None else None,
        "boundary-disagreement": (lambda: viz.plot_cdl_split(result.advice)) if result.advice is not None else None,
        "data-availability": (lambda: viz.plot_catalog_timeline(avail)) if avail is not None and len(avail) else None,
        "season-markers": (lambda: viz.plot_phenology_timeline(result.series, result.phenology, panels=2))
                          if result.series is not None else None,
        "cover-crop-winters": (lambda: viz.plot_cover_crop_matrix(result.series, result.covercrop))
                              if result.covercrop is not None and len(result.covercrop) else None,
        "soil-armor-by-year": (lambda: viz.plot_armor(armor_ts, armor_res))
                              if armor_res is not None and len(armor_res) else None,
    }
    extra_figures = extra_figures or {}
    out = io.BytesIO()
    drawn = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        names = list(FIGURES)
        for i, nm in enumerate(names):
            if progress:
                progress(0.6 * i / len(names), f"figure {nm}")
            png = extra_figures.get(nm)
            if png is None and figs.get(nm) is not None:
                try:
                    png = _png(figs[nm]())
                except Exception:                     # noqa: BLE001
                    png = None
            if png:
                z.writestr(f"figures/{nm}.png", png)
                drawn.append(nm)

        if progress:
            progress(0.7, "tables")

        def wr(d, path):
            if d is not None and len(d):
                z.writestr(path, d.to_csv(index=False))

        def wr_text(text, path):
            if text:
                z.writestr(path, text)

        wr(result.history, "tables/crop-rotation.csv")
        wr_text(result.table_csv("phenology"), "tables/season-markers.csv")
        wr_text(result.table_csv("covercrop"), "tables/cover-crops.csv")
        wr(armor_res, "tables/soil-armor.csv")
        wr(None if result.advice is None else result.advice.per_year, "tables/cdl-by-year.csv")
        try:
            wr(catalog_summary(avail) if avail is not None else None,
               "tables/data-availability.csv")
        except Exception:                             # noqa: BLE001
            pass
        wr_text(result.table_csv("summary"), "tables/field-summary.csv")
        wr(result.irrigation, "tables/irrigation-maps.csv")

        wr(result.series, "series/ndvi-by-date.csv")
        wr(armor_ts, "series/cover-fractions-by-date.csv")
        wr(avail, "series/acquisitions-by-source.csv")
        wr(result.weather, "series/weather-gridmet.csv")

        b = result.aoi[[c for c in ("field_id", "area_ha", "geometry") if c in result.aoi]]
        z.writestr("boundary.geojson", b.to_crs(4326).to_json())
        z.writestr("README.md", _briefing(result, name, shows, years, drawn, armor_res))
    if progress:
        progress(1.0, "done")
    return out.getvalue(), drawn


def _briefing(result, name, shows, years, drawn, armor_res) -> str:
    """README.md for the pack -- R's bundle_md(), plus what Python adds."""
    from .cache import analysis_window
    from .imagery import SOURCE_LABELS

    aoi4326 = result.aoi.to_crs(4326)
    b = aoi4326.total_bounds
    from .climate import field_centroid
    lon, lat = field_centroid(result.aoi)
    ha = float(result.area_ha)
    start, end = (analysis_window(*years) if years else (result.start, result.end))
    nobs = "--" if result.series is None else result.series["date"].nunique()
    wc = result.weather_check
    skipped = [n for n in FIGURES if n not in drawn]
    figs = ("\n".join(f"- `figures/{n}.png` -- {FIGURES[n]}" for n in drawn)
            or "_No figures in this pack._")
    adv = result.advice
    phen_cols = ["year", "crop", "season_type", "planting_est", "planting_lo", "planting_hi",
                 "planting_date", "harvest_est", "harvest_lo", "harvest_hi", "harvest_date",
                 "season_days", "season_days_final", "fallow_days", "peak_ndvi", "n_obs",
                 "confidence"]
    weather = ("The weather check was **off**: dates are the NDVI estimates."
               if wc is None else
               f"The weather check was **on** (gridMET daily weather at the field centroid): "
               f"a date on a day with more than {wc['dry_mm']:g} mm of rain"
               + (f", or daily-mean wind of {wc['wind_max_kmh']:g} km/h or more"
                  if wc.get("wind_max_kmh") is not None else "")
               + (f", or within {wc['wet_days']} day(s) after {wc['heavy_mm']:g} mm or more"
                  if wc.get("heavy_mm") is not None and wc.get("wet_days") else "")
               + f", moves to the last workable day before it -- at most "
                 f"{wc.get('forecast_days')} days earlier (the forecast horizon), otherwise "
                 "the first workable day after. `*_est` columns are the NDVI estimates, "
                 "`*_date` the final dates. In `tables/*.csv` the weather-checked tables "
                 "come as two blocks: without the check first, then with it.")
    return f"""# Field report pack: {name}

Generated {date.today():%d %B %Y} by the Field to Market remote sensing
demonstration pipeline (Python version). Everything in this pack is derived from
free public satellite imagery and public weather data. There was no field visit
and no grower input.

## If you are an AI assistant reading this, start here

You have been handed this pack to build a slide deck or a short report for a
**non-technical audience**. These rules are not optional.

1. **Soil armor is a cover metric, not a tillage metric.** It measures how much
   of the ground is covered by anything at all -- living plants or crop residue.
   Do not describe it as detecting tillage, no-till, or conservation practice.
2. **Cover crop verdicts are evidence, not findings.** The thresholds are Corn
   Belt values and they read badly in the South. Present them as indications,
   never as fact. Cover crop seeding and termination dates are estimates that
   have not been checked against any recorded date.
3. **Planting and harvest dates have never been validated** against a grower
   record anywhere. Present them as estimates, with their uncertainty window.
4. **Irrigation comes from USGS maps of 2002-2017 only** and single maps are
   unreliable for one field; `irrigated_maps` says in how many maps the field
   is irrigated. Do not present irrigation for 2018 onward as observed.
5. **Do not invent accuracy figures.** If a number is not in this pack, it does
   not exist. Say so rather than estimating one.

Lead with the figures. The tables are here so you can caption the figures
accurately, not to be reproduced wholesale onto slides.

## The field

| | |
|---|---|
| Name | {name} |
| Area | {ha:.1f} ha ({ha * 2.47105:.0f} acres) |
| Centroid (lon, lat) | {lon:.5f}, {lat:.5f} |
| Bounding box | {b[0]:.5f}, {b[1]:.5f} to {b[2]:.5f}, {b[3]:.5f} |
| Analysis window | {start} to {end} |
| Imagery | {SOURCE_LABELS.get(result.source, result.source)} |
| Clear observations | {nobs} |
{chr(10) + "**What this field was chosen to show.** " + shows + chr(10) if shows else ""}
## Is this one field?

{"_Boundary check not run._" if adv is None else f"**{adv.headline}**{chr(10)}{chr(10)}{adv.detail}"}

Every number below averages a measurement across whatever the boundary
contains, so a boundary holding two fields produces a season curve belonging to
neither of them.

## Crop rotation

{md_table(result.history)}
## Season markers

{md_table(result.phenology, phen_cols)}
Planting and harvest are estimates from the shape of the NDVI curve. The `_lo`
and `_hi` columns are the uncertainty window, set by how long the gaps between
clear images were. For a winter crop (`season_type` winter) planting is the
autumn sowing before the harvest year. {weather}

## Cover crop, winter by winter

{md_table(result.covercrop, ["winter", "n_obs", "max_ndvi", "green_days", "verdict",
                             "seeding_est", "seeding_date", "termination_est",
                             "termination_date", "dates_confidence", "notes"])}
## Soil armor before planting

{md_table(armor_res, ["year", "window_start", "window_end", "n_obs", "armor", "armor_lo",
                      "armor_hi", "f_pv", "f_npv", "f_bs", "note"])}
Armor is one minus the bare soil fraction. `f_pv` is living cover, `f_npv` is
crop residue, `f_bs` is bare ground, and the three sum to one. The window runs
from the previous crop's harvest to this season's planting, so the residue
being measured belongs to **last** year's crop, not the one named in the row.

## Figures

{figs}

## The rest of the pack

- `figures/` -- the charts above, PNG at print resolution
- `tables/` -- the tables above, as CSV
- `series/` -- the raw per-date measurements the tables were summarized from
- `boundary.geojson` -- the field outline, WGS84

A figure or table missing from the pack is one the app never produced, usually
because that tab was not run. It is not a failure of the field, and it is not
something to work around by describing the chart from the numbers.
{chr(10) + "Not produced this session, so do not refer to them: " + ", ".join(f"`{n}`" for n in skipped) + "." + chr(10) if skipped else ""}
## Method and provenance

Imagery: {SOURCE_LABELS.get(result.source, result.source)}, from Microsoft
Planetary Computer, cloud-masked. Crop type from the USDA Cropland Data Layer at
30 m. Weather from gridMET via the CSIP climate service. Every formula and
constant is written up in `METHODS.md` and `python/README.md` in the source
repository. This is a demonstration pipeline, not production software. Treat
every number here as provisional.
"""
