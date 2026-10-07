"""Field remote sensing explorer -- Streamlit port of r/app.R.

    streamlit run app.py

Upload a field boundary, see what satellite data exists for it, and read the
management story back out of the NDVI record: crop rotation, planting and
harvest windows, and off-season cover.

Same 7 views as the R Shiny app: Field, CDL, Data availability, Imagery,
Season analysis, Cover crops, Summary. Same underlying fieldrs pipeline and
disk cache -- a field warmed from the CLI or the R app opens instantly here
too, because both key on the same field geometry + query.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import folium
import matplotlib
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

matplotlib.use("Agg")

from fieldrs import analyze_field, apply_rain_check, geometry_from_geojson, load_field
from fieldrs.aoi import UPLOAD_TYPES, field_bounds, read_upload, single_field
from fieldrs.catalog import catalog_availability, catalog_summary
from fieldrs.cdl_local import available_years, cdl_root, use_local
from fieldrs.climate import FORECAST_DAYS, HEAVY_RAIN_MM, HEAVY_RAIN_WET_DAYS, WIND_MAX_KMH
from fieldrs.imagery import SOURCE_FIRST_YEAR, SOURCE_LABELS
from fieldrs.cropland import cdl_summary
from fieldrs.thumbnails import available_periods, build_scene_grid, plot_scene_grid, scenes_in_period
from fieldrs.imagery import search_scenes
from fieldrs import viz
from fieldrs.armor import armor_all_years, armor_band, armor_series
from fieldrs.phenology import residue_window

# ------------------------------------------------------------- config ---

# resolve(): __file__ is relative when Streamlit is started with a relative path.
FIELDS_DIR = Path(__file__).resolve().parent.parent / "data" / "fields"
YEAR_MIN = 2018          # earliest selectable: Sentinel-2 from 2018 (SOURCE_FIRST_YEAR)
DEFAULT_START = 2020     # the library is pre-computed from 2020, so that stays the default
IMG_MAX_CLOUD = 90

# Directory of local NASS_<year>.tif CONUS CDL mosaics, used instead of the
# CropScape network service (which times out on some networks). Handed to
# fieldrs.cdl_local through CDL_DIR; an explicit CDL_DIR in the environment
# wins. Any year missing locally falls back to CropScape automatically.
LOCAL_CDL = "/mnt/cephfs/csip-data/csip-lamps/CropScape_CDL"
if Path(LOCAL_CDL).is_dir():
    os.environ.setdefault("CDL_DIR", LOCAL_CDL)

DEMO_LABELS = {
    "example_field": "Iowa · Story Co.",
    "clinton-iowa": "Iowa · Clinton Co.",
    "kansas-rainfed": "Kansas · rainfed",
    "example_field_covercrop": "Maryland · cover cropped",
    "eldorado-georgia": "Georgia · El Dorado",
    "tifton-georgia": "Georgia · Carpenter Rd",
    "arkansas-rice": "Arkansas · rice",
    "lubbock-pivot": "Texas · Lubbock pivot",
    "washington-pivot": "Washington · pivot",
    "california-central": "California · Central Valley",
    "example_field_overgrown": "Iowa · too-wide boundary",
    "akron-co-wheat-fallow-even": "Colorado · wheat-fallow (wheat even yrs)",
    "akron-co-wheat-fallow-odd": "Colorado · wheat-fallow (wheat odd yrs)",
}

st.set_page_config(page_title="Field Remote Sensing Explorer", layout="wide")


# --------------------------------------------------------------- data ---

@st.cache_data(show_spinner=False)
def _library_table() -> pd.DataFrame:
    """Every boundary in data/fields/, as the R app lists them.

    Label and "what it shows" come from data/fields/library.csv, in its order
    (anything not listed sorts after, by name); crops from the warmed-library
    table python/outputs/demo_library_python.csv, falling back to the field's
    cached CDL so a newly added field is not left blank.
    """
    from fieldrs.cropland import cdl_history_from_stack, cdl_stack
    files = sorted(FIELDS_DIR.glob("*.geojson"))
    try:
        man = pd.read_csv(FIELDS_DIR / "library.csv", dtype=str).fillna("")
    except Exception:                                 # noqa: BLE001
        man = pd.DataFrame(columns=["stem", "label", "shows"])
    try:
        meta = pd.read_csv(Path(__file__).resolve().parent / "outputs" / "demo_library_python.csv",
                           dtype=str).fillna("")
        crops_by_file = dict(zip(meta["file"], meta["crops"]))
    except Exception:                                 # noqa: BLE001
        crops_by_file = {}
    order = {s: i for i, s in enumerate(man["stem"])}
    rows = []
    for f in files:
        m = man[man["stem"] == f.stem]
        label = (m["label"].iloc[0] if len(m) and m["label"].iloc[0]
                 else DEMO_LABELS.get(f.stem, f.stem.replace("-", " ").replace("_", " ").title()))
        crops = crops_by_file.get(f.name, "")
        if not crops:
            try:
                st_ = cdl_stack(load_field(f), list(range(YEAR_MIN, date.today().year)),
                                only_cached=True)
                if st_ is not None:
                    seen = cdl_history_from_stack(st_)["crop"]
                    crops = "/".join(dict.fromkeys(c for c in seen if isinstance(c, str)))
            except Exception:                         # noqa: BLE001
                pass
        rows.append({"stem": f.stem, "label": label, "crops": crops,
                     "shows": m["shows"].iloc[0] if len(m) else "",
                     "_o": order.get(f.stem, len(order))})
    if not rows:
        return pd.DataFrame(columns=["stem", "label", "crops", "shows"])
    return (pd.DataFrame(rows).sort_values(["_o", "stem"]).drop(columns="_o")
            .reset_index(drop=True))


@st.cache_data(show_spinner=False)
def _demo_library() -> list[tuple[str, str]]:
    """(stem, label) pairs for the field picker, in library order."""
    t = _library_table()
    return list(zip(t["stem"], t["label"]))


@st.cache_data(show_spinner=False)
def _library_cards() -> pd.DataFrame:
    return _library_table()


def _pick_field(stem: str) -> None:
    """Gallery card click: select that field (runs before the widgets rebuild)."""
    st.session_state.field_pick = stem


def _fmt_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Datetime columns as plain YYYY-MM-DD strings for display -- st.dataframe
    otherwise shows the full '00:00:00' timestamp, which is just noise here."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return out


def _load_boundary(stem: str | None, uploads) -> "gpd.GeoDataFrame | None":
    """The boundary to analyse, reduced to one field -- or a stop with the reason.

    Every path in (library pick or upload) goes through single_field(), as in
    the R app: slivers are dropped silently, but a boundary holding two real
    fields is refused, because everything downstream averages over the whole
    boundary and two fields give a season curve belonging to neither.
    """
    try:
        if uploads:
            raw = read_upload([(u.name, u.getvalue()) for u in uploads])
        elif stem is not None:
            raw = load_field(FIELDS_DIR / f"{stem}.geojson")
        else:
            return None
        one = single_field(raw)
    except Exception as exc:                          # noqa: BLE001
        st.error(f"**Cannot use this boundary.** {exc}")
        st.stop()
    if one.attrs.get("dropped"):
        st.sidebar.caption(f"Dropped {one.attrs['dropped']} sliver(s) from the "
                           "boundary; analysing the main field.")
    return one


def _dl_name(what: str) -> str:
    """File name for a download: field, what it is, today's date (as in R)."""
    stem = st.session_state.get("field_label", "field")
    return f"{stem}_{what}_{date.today().isoformat()}"


def _show(fig, name: str) -> None:
    """Draw a figure with a PNG download under it -- R's dl_header() button.

    The PNG is also kept for the report pack, so the pack holds exactly the
    charts this session drew.
    """
    import io
    import matplotlib.pyplot as plt
    st.pyplot(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    png = buf.getvalue()
    st.session_state.setdefault("figs", {})[name] = png
    st.download_button("PNG", png, f"{_dl_name(name)}.png", "image/png",
                       key=f"png_{name}")


@st.cache_data(show_spinner=False)
def _search_scenes_cached(_aoi, start: str, end: str, max_cloud: float, bust: tuple):
    """search_scenes() has no disk cache of its own (see python/README.md --
    it's only ever called from behind the series cache elsewhere), so a bare
    call here would re-hit Planetary Computer on every unrelated Streamlit
    rerun. Cache on the Streamlit side instead, keyed on `bust` since the
    leading underscore tells Streamlit not to try hashing the GeoDataFrame."""
    return search_scenes(_aoi, start, end, max_cloud=max_cloud)


# -------------------------------------------------------------- sidebar ---

st.sidebar.title("Field Remote Sensing Explorer")

library = _demo_library()
upload = st.sidebar.file_uploader(
    "Upload a boundary", type=list(UPLOAD_TYPES), accept_multiple_files=True,
    help="GeoJSON, KML, GeoPackage, or a zipped shapefile. For a loose shapefile "
         "select the .shp, .shx, .dbf and .prj together.")
field_stem = st.sidebar.selectbox(
    "Or pick a demo field", options=[s for s, _ in library],
    format_func=lambda s: dict(library)[s], disabled=bool(upload), key="field_pick",
)

years = st.sidebar.slider("Years", YEAR_MIN, date.today().year,
                          (DEFAULT_START, date.today().year),
                          help="Sentinel-2 from 2018, HLS from 2020. The field library "
                               "is pre-computed from 2020; an earlier start reads the "
                               "field again once (about two minutes), then it is cached.")

source = st.sidebar.radio(
    "Imagery", list(SOURCE_LABELS), format_func={
        "sentinel2": "Sentinel-2 (10 m, original)",
        "hls": "HLS: Sentinel-2 + Landsat (30 m)"}.get,
    help="Sentinel-2 L2A at 10 m is the original series. HLS v2 adds Landsat 8/9, "
         "harmonised with Sentinel-2 on a 30 m grid: more clear images, so shorter "
         "cloud gaps at planting and harvest, at coarser resolution. Each source "
         "is analysed and cached on its own.")
if years[0] < SOURCE_FIRST_YEAR[source]:
    st.sidebar.warning(f"{SOURCE_LABELS[source]} starts in {SOURCE_FIRST_YEAR[source]}; "
                       f"analysing {SOURCE_FIRST_YEAR[source]}-{years[1]}.")
    years = (SOURCE_FIRST_YEAR[source], max(years[1], SOURCE_FIRST_YEAR[source]))

@st.cache_data(show_spinner=False)
def _local_cdl_years(root: str) -> list[int]:
    return available_years()


if use_local() and _local_cdl_years(str(cdl_root())):
    yrs = _local_cdl_years(str(cdl_root()))
    st.sidebar.caption(f"CDL: local ({cdl_root().name}, {yrs[0]}-{yrs[-1]})")
else:
    st.sidebar.caption("CDL: CropScape (network)")

rain_check = st.sidebar.toggle(
    "Weather check on field-work dates (gridMET)", value=True,
    help="When a planting, harvest, cover seeding or termination estimate falls on "
         "a day unfit for field work, move it to the last fit day before it, inside "
         "its uncertainty window, using daily gridMET weather at the field centroid. "
         "Off: the dates are the NDVI estimates.")
wx_mode = st.sidebar.radio(
    "Check", ["Rain only", "Rain and wind"], horizontal=True, disabled=not rain_check)
wind_check = rain_check and wx_mode == "Rain and wind"
dry_mm = st.sidebar.number_input(
    "Max rain on a rain-free day (mm)", min_value=0.0, max_value=10.0, value=0.0,
    step=0.5, disabled=not rain_check)
wind_kmh = st.sidebar.number_input(
    "Max daily-mean wind (km/h)", min_value=5.0, max_value=80.0, value=WIND_MAX_KMH,
    step=1.0, disabled=not wind_check,
    help="30 km/h is about 20 mph. gridMET provides only the daily MEAN wind at "
         "10 m -- no daily maximum and no gusts -- so the limit applies to the mean. "
         "That rules out clearly windy days; a day averaging 30 km/h gusts far higher.")
st.sidebar.caption(f"= {wind_kmh / 1.609:.0f} mph daily mean" if wind_check else "")
forecast_days = st.sidebar.number_input(
    "Forecast horizon (days)", min_value=0, max_value=14, value=FORECAST_DAYS, step=1,
    disabled=not rain_check,
    help="A planting, harvest, seeding or termination date moves earlier than its "
         "estimate by at most this many days -- a weather forecast is good for about "
         "five. If the last workable day is further back, the date moves to the "
         "first workable day after the estimate instead.")
heavy_mm = st.sidebar.number_input(
    "Heavy rain (mm/day)", min_value=5.0, max_value=100.0, value=HEAVY_RAIN_MM,
    step=5.0, disabled=not rain_check,
    help="After a day with at least this much rain the soil is too wet to work: "
         "the following day(s) do not count as field-work days even when dry. "
         "25 mm is one inch.")
wet_days = st.sidebar.number_input(
    "Days too wet after heavy rain", min_value=0, max_value=7,
    value=HEAVY_RAIN_WET_DAYS, step=1, disabled=not rain_check)
wind_max = wind_kmh if wind_check else None

analyze_clicked = st.sidebar.button("Analyze", type="primary", use_container_width=True)

st.sidebar.divider()
st.sidebar.caption(
    "Nothing is calibrated -- every threshold and crop lag is a "
    "literature-typical starting value, not fitted to ground truth. "
    "See python/README.md before quoting a number."
)

aoi = _load_boundary(None if upload else field_stem, upload)
st.session_state.field_label = (Path(upload[0].name).stem if upload else field_stem)
if aoi is None:
    st.stop()

field_key = ("+".join(sorted(f"{u.name}:{u.size}" for u in upload)) if upload
             else field_stem, years, source)
# The climate check is applied on top of the pipeline result, not inside it, so
# switching it on/off or changing the threshold never re-runs the pipeline and
# cannot turn a loaded field back into "not cached" -- see apply_rain_check().
rain_key = (rain_check, dry_mm, wind_max, forecast_days, heavy_mm, wet_days)

# ------------------------------------------------------- run / fetch ---

if "field_key" not in st.session_state or st.session_state.field_key != field_key:
    # Selection changed: try the instant path first, exactly like the R app
    # opening a pre-warmed field -- only a press of Analyze does real work.
    st.session_state.field_key = field_key
    st.session_state.figs = {}          # charts belong to a field
    st.session_state.pop("pack", None)
    st.session_state.base = analyze_field(aoi, years=years, only_cached=True,
                                          rain_free=False, source=source)
    st.session_state.rain_key = None

if analyze_clicked:
    prog = st.sidebar.progress(0.0, text="Starting...")

    def _progress(done: int, total: int, msg: str) -> None:
        prog.progress(min(done / max(total, 1), 1.0), text=msg)

    with st.spinner("Running the pipeline -- first run for a field reads several "
                    "hundred scenes and can take a few minutes."):
        st.session_state.base = analyze_field(aoi, years=years, progress=_progress,
                                              rain_free=False, source=source)
    st.session_state.rain_key = None

if st.session_state.rain_key != rain_key:
    base = st.session_state.base
    with st.spinner("Checking gridMET weather..." if rain_check else "Updating..."):
        st.session_state.result = (None if base is None else
                                   apply_rain_check(base, rain_check, dry_mm, wind_max,
                                                    int(forecast_days), heavy_mm,
                                                    int(wet_days)))
    st.session_state.rain_key = rain_key

result = st.session_state.result

# How the weather check reads in captions.
wx_what = ("rain-free day with daily-mean wind below "
           f"{wind_kmh:.0f} km/h" if wind_check else "rain-free day")
wx_ahead = "rain or wind" if wind_check else "rain"

if result is None:
    st.info(
        f"Not cached for this field, year range and imagery ({SOURCE_LABELS[source]}) "
        "yet. Press **Analyze** in the "
        "sidebar to compute it -- first run reads several hundred scenes and "
        "takes a few minutes; every later run against the same field and years "
        "is instant."
    )
    st.stop()

# --------------------------------------------------------------- tabs ---

tab_field, tab_cdl, tab_avail, tab_imagery, tab_season, tab_cover, tab_armor, tab_summary = st.tabs(
    ["Field", "CDL", "Data availability", "Imagery", "Season analysis", "Cover crops",
     "Soil armor", "Summary"]
)

# Soil armor is its own pass over four bands, so like the Imagery tab it runs
# on a button. A run is kept per field and year range; the Summary column reads
# the cache only, so a warmed field fills it without a press.
armor_key = (field_key[0], field_key[1])
if "armor" not in st.session_state:
    st.session_state.armor = {}


@st.cache_data(show_spinner=False)
def _armor_cached(_aoi, key, _phen_bust):
    ts = armor_series(_aoi, key[1], only_cached=True)
    return ts


armor_ts_cached = _armor_cached(aoi, armor_key, None)
armor_run = st.session_state.armor.get(armor_key)
armor_res = (armor_run["res"] if armor_run is not None else
             armor_all_years(armor_ts_cached, result.phenology, "spring")
             if armor_ts_cached is not None else None)

# ---- 1. Field ---------------------------------------------------------

with tab_field:
    cards = _library_cards()
    q = st.session_state.get("gallery_q", "")
    shown = cards
    if q.strip():
        # Every word has to appear somewhere, so "georgia cotton" narrows rather
        # than widening the way an OR would -- as in the R app.
        hay = (cards["label"] + " " + cards["crops"] + " " + cards["shows"]).str.lower()
        for w in q.lower().split():
            shown = shown[hay[shown.index].str.contains(w, regex=False)]
    n_all = len(cards)
    with st.expander(f"Field library -- {len(shown)} of {n_all} fields" if q.strip()
                     else f"Field library -- {n_all} fields", expanded=False):
        st.text_input("Filter", key="gallery_q", placeholder="Filter: crop, state, practice",
                      label_visibility="collapsed")
        if shown.empty:
            st.caption("No field matches that. Clear the filter to see them all.")
        cols = st.columns(3)
        for i, (_, c) in enumerate(shown.iterrows()):
            with cols[i % 3].container(border=True):
                active = (not upload) and c["stem"] == field_stem
                st.markdown(f"**{c['label']}**" + ("  \u2713" if active else ""))
                if c["crops"]:
                    st.caption(c["crops"] if len(c["crops"]) <= 40 else c["crops"][:39] + "\u2026")
                if c["shows"]:
                    st.markdown(f"<span style='font-size:0.8em'>{c['shows']}</span>",
                                unsafe_allow_html=True)
                st.button("Loaded" if active else "Load", key=f"pick_{c['stem']}",
                          disabled=active or bool(upload), on_click=_pick_field,
                          args=(c["stem"],), use_container_width=True)

    col_map, col_rot = st.columns([7, 5])
    with col_map:
        st.subheader("Boundary")
        minx, miny, maxx, maxy = field_bounds(aoi, buffer_m=0)
        m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=15,
                       tiles="Esri.WorldImagery")
        folium.GeoJson(json.loads(aoi.to_json()), name="field",
                      style_function=lambda _: {"color": "#ffd60a", "weight": 3, "fillOpacity": 0.05}
                      ).add_to(m)
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        st_folium(m, height=460, use_container_width=True, returned_objects=[])
    with col_rot:
        st.subheader("Crop rotation (USDA CDL)")
        if result.history is not None:
            st.dataframe(result.history, hide_index=True, use_container_width=True)
            st.caption("Dominant crop per year, with the share of the field it covers. "
                      "A low share means the boundary spans more than one management unit."
                      + (" Irrigation is the share of the field mapped irrigated in the "
                         "USGS irrigated-agriculture map nearest at or before that year "
                         "(irrigation_map) -- maps exist for 2002, 2007, 2012 and 2017 "
                         "only, so recent years read 'as mapped in 2017'. irrigated_maps says in how "
                         "many of the four maps the field is irrigated: single maps are "
                         "unreliable for one field, so trust agreement, not one map."
                         if "irrigated" in result.history else ""))
        else:
            st.caption("No CDL for these years.")

    st.subheader("Field summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Area", f"{result.area_ha:.1f} ha")
    c2.metric("Fields", len(result.aoi))
    c3.metric("Clear obs.", result.series["date"].nunique() if result.series is not None else 0)
    c4.metric("Seasons", len(result.phenology) if result.phenology is not None else 0)
    if result.series is not None and "sensor" in result.series:
        per = (result.series.drop_duplicates("date")["sensor"].value_counts()
               .rename({"S2": "Sentinel-2", "HLS-S30": "HLS Sentinel-2",
                        "HLS-L30": "HLS Landsat"}))
        st.caption(f"Imagery: {SOURCE_LABELS[result.source]} -- clear dates by sensor: "
                   + ", ".join(f"{k} {v}" for k, v in per.items()))
    else:
        st.caption(f"Imagery: {SOURCE_LABELS[result.source]}")

# ---- 2. CDL -------------------------------------------------------------

with tab_cdl:
    st.subheader("Is this one field?")
    if result.advice is not None:
        adv = result.advice
        tone = {"single unit": "success", "trim": "warning", "split": "error"}[adv.verdict]
        getattr(st, tone)(f"**{adv.headline}**\n\n{adv.detail}")
        st.dataframe(adv.per_year, hide_index=True, use_container_width=True)
    else:
        st.caption("No CDL for these years.")

    st.subheader("Crop type by year (USDA CDL, 30 m)")
    if result.cdl is not None:
        _show(viz.plot_cdl_matrix(result.cdl), "cdl-maps-by-year")
        st.caption("One map per year, clipped to the boundary, coloured by CDL class. "
                  "A boundary that is one management unit shows one colour filling it every year.")

    st.subheader("Where the boundary disagrees with itself")
    if result.advice is not None:
        _show(viz.plot_cdl_split(result.advice), "boundary-disagreement")
        st.caption("Share of years each pixel carried a different crop from the boundary's "
                  "dominant crop that year. A persistent block outlined in red is a "
                  "sub-area being farmed separately -- one red year is classification "
                  "noise, several is a second field.")

# ---- 3. Data availability -----------------------------------------------

with tab_avail:
    st.subheader("Every acquisition over this field")
    with st.spinner("Querying catalogues (metadata only, a few seconds)..."):
        avail = catalog_availability(aoi, start=result.start, end=result.end)
    _show(viz.plot_catalog_timeline(avail), "data-availability")
    st.caption("Catalogue metadata only, so this is fast. Optical marks are shaded by scene "
              "cloud cover. The density is the point -- Sentinel-2 alone has looked at this "
              "field hundreds of times in these years, and radar adds a stream that weather "
              "cannot interrupt.")

    st.subheader("By source")
    st.dataframe(catalog_summary(avail), hide_index=True, use_container_width=True)

    with st.expander("What each source is for"):
        st.markdown(
            "- **Sentinel-2 L2A** -- primary workhorse. Red/NIR for NDVI, SCL for cloud masking.\n"
            "- **Landsat 8/9** -- coarser but the archive runs back to 1982.\n"
            "- **HLS Sentinel-2 / HLS Landsat** -- NASA's harmonised pair on one grid; "
            "combine both for a denser series.\n"
            "- **Sentinel-1 radar** -- sees through cloud, independent of the weather "
            "that thins optical winter coverage.\n"
            "- **MODIS NDVI 16-day** -- too coarse for one field, but a consistent "
            "2000-present reference.\n"
            "- **NAIP aerial** -- sub-metre true colour + NIR, every 2-3 years.\n"
            "- **USDA CDL** -- annual crop type, not from this STAC catalogue (CropScape)."
        )

# ---- 4. Imagery -----------------------------------------------------------

with tab_imagery:
    st.subheader("Pick a quarter")
    col_a, col_b, col_c = st.columns([4, 5, 3])
    with col_a:
        img_start = f"{years[0]}-01-01"
        img_end = f"{min(years[1], date.today().year)}-12-31"
        with st.spinner("Searching the catalogue..."):
            scenes = _search_scenes_cached(aoi, img_start, img_end, IMG_MAX_CLOUD,
                                           bust=(field_key, img_start, img_end))
        periods = available_periods(scenes, "quarter")
        period = st.selectbox("Quarter", periods)
    with col_b:
        view = st.radio("View", ["rgb", "fc", "ndvi", "armor"], horizontal=True,
                        format_func={"rgb": "True colour", "fc": "False colour (NIR)",
                                     "ndvi": "NDVI", "armor": "Soil armor"}.get)
    with col_c:
        st.write("")
        show = st.button("Show imagery", type="primary", use_container_width=True)

    st.caption("Every acquisition in the quarter, on one sheet. Grey means the pixel was "
              "masked as cloud, shadow or snow. Nothing is read until you press the button, "
              "and once a quarter has been read it stays cached for good.")
    if view == "armor":
        st.caption("**The Soil armor view is per-pixel cover.** Each pixel is unmixed "
                   "into living green, crop residue and bare soil, and the sheet shows "
                   "**1 - bare soil**: brown is exposed ground, teal is covered by "
                   "something, cream around the halfway mark. **It shows how much "
                   "cover, not what kind** -- half living/half bare and half residue/"
                   "half bare look the same. For the split, read the Soil armor tab. "
                   "Always Sentinel-2 (it needs the shortwave bands).")

    if show:
        subset = scenes_in_period(scenes, period, aoi, "quarter")
        prog = st.progress(0.0, text="Loading...")

        def _iprog(done, total, msg):
            prog.progress(min(done / max(total, 1), 1.0), text=msg)

        with st.spinner(f"Reading {len(subset)} scenes..."):
            grid = build_scene_grid(subset, aoi, view=view, workers=8, progress=_iprog)
        prog.empty()
        _show(plot_scene_grid(grid, view=view, title=period), "imagery-contact-sheet")

# ---- 5. Season analysis ----------------------------------------------------

with tab_season:
    st.subheader("Planting and harvest windows")
    if result.phenology is None or not len(result.phenology):
        st.caption("No seasons found.")
    else:
        phen_view = st.radio("View", ["split", "all", "one"], horizontal=True,
                             format_func={"split": "Whole record, split",
                                          "all": "Whole record, one axis",
                                          "one": "Single season"}.get)
        if phen_view == "one":
            yr = st.selectbox("Season", sorted(result.phenology["year"].unique(), reverse=True))
            row = result.phenology[result.phenology["year"] == yr].iloc[0]
            _show(viz.plot_phenology(result.series, int(yr), row, crop=row.get("crop"),
                                     weather=result.weather, wind_max_kmh=wind_max),
                  "season-markers")
        else:
            row = {}
            _show(viz.plot_phenology_timeline(result.series, result.phenology,
                                              panels=2 if phen_view == "split" else 1),
                  "season-markers")
        cap = ("Dashed lines are the NDVI-estimated planting (blue) and harvest (orange) "
               "dates; shading is the uncertainty window. NDVI sees the canopy, not the "
               "planter -- these are inferred from green-up and senescence and are good "
               "to roughly two weeks.")
        if str(row.get("season_type", "")).startswith("winter"):
            cap += (" This is a winter crop: the season runs from the autumn before, "
                    "'planting' is autumn sowing read from emergence, and the peak "
                    "and harvest are in spring and early summer.")
        if rain_check:
            cap += (f" Solid lines are the final dates: where the estimate fell on a day "
                    f"of {wx_ahead}, it moves to the last {wx_what} before it (gridMET, "
                    "field centroid) -- farmers act ahead of the forecast -- inside its "
                    "window. Bars hanging from the top are daily rain" +
                    ("; grey ticks along the bottom mark days at or over the wind limit."
                     if wind_check else "."))
        else:
            cap += " Weather check is off (sidebar)."
        st.caption(cap)
        if rain_check and result.weather is None:
            st.warning("gridMET weather was unavailable, so the dates are NDVI "
                       "estimates and have not been checked for weather.")
        elif rain_check and result.weather.attrs.get("errors"):
            bad = result.weather.attrs["errors"]
            st.warning(f"gridMET weather was unavailable for {', '.join(map(str, bad))}; "
                       "those seasons' dates are NDVI estimates, not checked for weather. "
                       f"First error: {next(iter(bad.values()))}")

        st.subheader("Season markers, all years")
        lead = ["year", "crop", "season_type", "planting_date", "planting_est", "planting_shift_d",
                "planting_weather_note", "harvest_date", "harvest_est", "harvest_shift_d",
                "harvest_weather_note", "season_days_final", "season_days",
                "fallow_start", "fallow_end", "fallow_days", "fallow_green_days"]
        cols = [c for c in lead if c in result.phenology] + \
               [c for c in result.phenology if c not in lead]
        st.dataframe(_fmt_dates(result.phenology[cols]), hide_index=True,
                     use_container_width=True)
        if rain_check:
            st.caption("The download holds two blocks, one under the other: the dates "
                   "without the weather check first, then the weather-checked dates "
                   "shown above.")
        st.download_button("Download phenology CSV", result.table_csv("phenology").encode(),
                           f"{_dl_name('season-markers')}.csv", "text/csv")

# ---- 6. Cover crops ---------------------------------------------------------

with tab_cover:
    st.subheader("Off-season green cover, every winter")
    if result.covercrop is None or not len(result.covercrop):
        st.caption("No off-season windows.")
    else:
        _show(viz.plot_cover_crop_matrix(result.series, result.covercrop), "cover-crop-winters")
        st.caption("Purple: cover crop seeding; magenta: termination. Dashed lines are the "
                   "NDVI estimates" + (f"; solid lines the final dates, moved ahead of "
                   f"{wx_ahead} like the cash crop dates." if rain_check else ".") +
                   " Dated only for winters judged a (possible) cover crop, and only where "
                   "the curve shows the turn -- see dates_note.")
        st.subheader("All winters")
        cc = result.covercrop
        lead = ["winter", "verdict", "seeding_date", "seeding_est", "seeding_shift_d",
                "termination_date", "termination_est", "termination_shift_d",
                "cover_days_final", "dates_confidence", "dates_note",
                "seeding_weather_note", "termination_weather_note"]
        cols = [c for c in lead if c in cc] + [c for c in cc if c not in lead]
        st.dataframe(_fmt_dates(cc[cols]), hide_index=True, use_container_width=True)
        if rain_check:
            st.caption("The download holds two blocks, one under the other: the dates "
                   "without the weather check first, then the weather-checked dates "
                   "shown above.")
        st.download_button("Download cover crop CSV", result.table_csv("covercrop").encode(),
                           f"{_dl_name('cover-crops')}.csv", "text/csv")

    with st.expander("How to read this", expanded=False):
        st.markdown(
            "**The signal:** bare residue sits around 0.10-0.25 NDVI all winter. A "
            "planted cover crop establishes in autumn and greens up again in early "
            "spring, showing as a hump above that floor.\n\n"
            "**The caveat:** NDVI sees green, not intent. Volunteer grain, winter "
            "annual weeds and a grassed waterway inside the boundary all look "
            "similar. Treat a verdict as evidence to check, not a finding.\n\n"
            "**Before relying on it:** calibrate the thresholds against fields "
            "where the practice is known.\n\n"
            "**Seeding and termination dates:** seeding is read from the rise "
            "after the cash harvest (20% point, minus 14 days for emergence); "
            "termination from the fall before the next cash crop (midpoint of "
            "the decline, minus 7 days for herbicide burndown). Neither is "
            "fitted to recorded dates, so confidence is never better than "
            "medium. A cover sown into the standing crop, or one that only "
            "greens up in spring, is reported as not dated rather than guessed."
        )

# ---- 7. Soil armor -----------------------------------------------------------

with tab_armor:
    st.subheader("Off-season soil cover")
    st.warning(
        "**Exploratory. These fractions are not calibrated cover percentages.** "
        "The three endmembers were derived from this library's own pixels, so the "
        "numbers are consistent and comparable between these fields but are not "
        "validated against measured cover. Shortwave reflectance also moves with "
        "soil moisture. Read the spread across the window, not a single date, and "
        "calibrate against line transects -- scoring green, residue and bare "
        "separately -- before reporting anything.")
    c1, c2, c3 = st.columns([5, 4, 3])
    c1.caption("How much of the surface is protected between harvest and the next "
               "planting -- by **anything**, living cover or crop residue. Each pixel "
               "is split into living green, residue and bare soil; **armor = 1 - bare "
               "soil.** Needs its own pass over the shortwave infrared, so it runs "
               "only when you ask.")
    c2.caption("**Charts: whole calendar years.** Fall tillage, cover crop "
               "establishment and overwinter residue loss are all visible. The "
               "**reported figure is the pre-planting window** -- shaded on each "
               "panel -- so the per-season table means what it always did.")
    with c3:
        st.write("")
        run_armor = st.button("Run soil armor analysis", type="primary",
                              use_container_width=True)
    if armor_ts_cached is not None or armor_run is not None:
        st.success("**Already loaded.** The shortwave series for this field is cached "
                   "-- it runs instantly.")
    else:
        st.info("**First load.** Not read yet. This is a second pass over the archive "
                "on four bands and takes **a few minutes** for a field this size. It "
                "is cached afterwards.")
    if source != "sentinel2":
        st.caption("Soil armor always reads Sentinel-2 L2A (it needs the 20 m "
                   "shortwave bands the endmembers were fitted on), whichever imagery "
                   "source is selected for the season analysis.")

    if run_armor:
        prog = st.progress(0.0, text="Reading shortwave infrared...")

        def _aprog(done, total, msg):
            prog.progress(min(done / max(total, 1), 1.0), text=msg)

        with st.spinner("Reading shortwave infrared..."):
            ts = armor_series(aoi, years, workers=8, progress=_aprog)
        prog.empty()
        if ts is None:
            st.error("No imagery found for this field.")
        else:
            st.session_state.armor[armor_key] = {
                "ts": ts, "res": armor_all_years(ts, result.phenology, "spring")}
            _armor_cached.clear()
            st.rerun()

    armor_run = st.session_state.armor.get(armor_key)
    if armor_run is None and armor_ts_cached is not None:
        armor_run = {"ts": armor_ts_cached, "res": armor_res}

    st.subheader("Calendar year, with the pre-planting window shaded")
    if armor_run is None:
        st.caption("Press **Run soil armor analysis** to read the shortwave infrared "
                   "for this field.")
    elif armor_run["res"] is None or not len(armor_run["res"]):
        st.caption("No season had a readable residue window.")
    else:
        _show(viz.plot_armor(armor_run["ts"], armor_run["res"]), "soil-armor-by-year")
        st.caption("Teal is living cover, tan is crop residue, and the white gap to the "
                   "top is **bare soil** -- the quantity being measured. One panel per "
                   "calendar year; the shaded band between the dashed lines is the "
                   "pre-planting window the headline armor figure is averaged over. "
                   "Nothing is screened out: a green date is cover, not an obstacle.")

        st.subheader("Per season")
        r = armor_run["res"]

        def _win(row):
            if row["window_start"] is None or pd.isna(row["window_start"]):
                return "--"
            return f"{row['window_start']:%d %b} to {row['window_end']:%d %b}"

        def _insight(row):
            lead = ("" if pd.isna(row["armor"])
                    else f"Provisional: {armor_band(row['armor'])}.")
            return " ".join(x for x in (lead, row["note"] if isinstance(row["note"], str) else "") if x)

        tbl = pd.DataFrame({
            "Year": r["year"],
            "Window": r.apply(_win, axis=1),
            "Clear obs": r["n_obs"],
            "Soil armor": r["armor"],
            "Range": [("" if pd.isna(a) else f"{lo:.2f}-{hi:.2f}")
                      for a, lo, hi in zip(r["armor"], r["armor_lo"], r["armor_hi"])],
            "Living": r["f_pv"], "Residue": r["f_npv"], "Bare": r["f_bs"],
            "Insights": r.apply(_insight, axis=1),
        })
        st.dataframe(tbl, hide_index=True, use_container_width=True)
        st.download_button("Download soil armor CSV", r.to_csv(index=False).encode(),
                           f"{_dl_name('soil-armor')}.csv", "text/csv")

    with st.expander("How to read this", expanded=False):
        st.markdown(
            "**The signal:** residue holds cellulose and lignin, which absorb near "
            "2100 nm. The Dead Fuel Index compares Sentinel-2 B11 (1610 nm) against B12 "
            "(2190 nm) to pick that up, and NDVI measures green. Together they place "
            "every pixel in a triangle whose corners are pure living cover, pure "
            "residue and clean bare soil -- so each pixel resolves into three "
            "fractions that sum to one.\n\n"
            "**Why not just residue:** this replaced a minimum-NDTI metric that "
            "measured residue only. A field under a living cover crop or a perennial "
            "stand is protected just as well as one under stubble, and the old metric "
            "scored it as bare -- the Washington alfalfa pivot, the best-covered soil "
            "in this library, ranked last of eleven. **Armor counts cover from any "
            "source.**\n\n"
            "**The confounders:** shortwave reflectance moves with soil moisture, so "
            "read the window rather than a single date. Water and deep shadow are "
            "masked out entirely -- as near-infrared collapses the index breaks down, "
            "and flooded ground would otherwise read as heavy residue.\n\n"
            "**What is not calibrated:** the three corners were fitted from this "
            "library's own pixels, so the fractions are comparable between these "
            "fields but are not validated cover percentages. Ground truth here means "
            "line transects scoring green, residue and bare separately -- which "
            "validates all three fractions at once.")

# ---- 8. Summary -------------------------------------------------------------

with tab_summary:
    st.subheader("Management history inferred from satellite")
    summ = result.summary.copy()

    # Same wording as the R app. "Before planting": the window runs from the
    # PREVIOUS crop's harvest to this season's planting, so the residue is last
    # year's crop's, not this one's. Blank only means "not computed".
    def _armor_for(y):
        if armor_res is None:
            return None
        rr = armor_res[armor_res["year"] == y]
        if rr.empty:
            return ("no window" if residue_window(result.phenology, int(y), "spring")
                    is None else "no usable observations")
        rr = rr.iloc[0]
        if pd.isna(rr["armor"]):
            note = rr["note"] if isinstance(rr["note"], str) else ""
            return ("no window" if note.startswith("no window") else
                    "too few clear dates" if note.startswith("only ") else "not readable")
        return f"{armor_band(rr['armor'])} ({rr['armor']:.2f})"

    if len(summ):
        summ.insert(summ.columns.get_loc("confidence"),
                    "soil_armor_before_planting (provisional)",
                    [_armor_for(int(y)) for y in summ["year"]])
    st.dataframe(_fmt_dates(summ), hide_index=True, use_container_width=True)
    st.caption((f"Planting and harvest dates are field-work days: where the NDVI "
                f"estimate fell on a day of {wx_ahead}, it moved to the last {wx_what} "
                "before it (gridMET), inside its uncertainty window; the shift columns "
                "say by how many days. " if rain_check else
                "Planting and harvest dates are NDVI estimates (weather check off). ") +
               "season_days_final is planting to harvest on these dates; season_days is "
               "NDVI green-up to harvest estimate. "
               "Nothing here is calibrated -- every threshold and crop lag is a "
               "literature-typical starting value. See python/README.md. "
               "**Soil armor is provisional and uncalibrated** -- the fraction of the "
               "surface covered by anything, living or residue, from the previous "
               "crop's harvest to this season's planting. It fills automatically for "
               "fields whose shortwave series is cached; otherwise run the Soil armor "
               "tab first.")

    if rain_check:
        st.caption("The download holds two blocks, one under the other: the dates "
                   "without the weather check first, then the weather-checked dates "
                   "shown above.")
    csv = result.summary_csv().encode()
    st.download_button("Download summary CSV", csv, f"{_dl_name('field-summary')}.csv",
                       "text/csv")

    st.subheader("Take the whole session away")
    st.markdown(
        "One zip holding everything above: the charts as images, every table as CSV, "
        "the raw per-date measurements behind them, the field boundary, and a written "
        "briefing. It is built to be uploaded to an AI assistant and turned into a "
        "slide deck or a short report -- the briefing tells the assistant what each "
        "number means and, more to the point, what it is **not** allowed to claim "
        "from it.")
    if st.button("Build report pack", type="primary"):
        from fieldrs.report import build_report_pack
        cards_ = _library_cards()
        m_ = cards_[cards_["stem"] == field_stem] if not upload else cards_.iloc[0:0]
        bar = st.progress(0.0, text="Building the report pack")
        try:
            avail_ = catalog_availability(aoi, start=result.start, end=result.end)
        except Exception:                             # noqa: BLE001
            avail_ = None
        zb, drawn = build_report_pack(
            result, name=m_["label"].iloc[0] if len(m_) else "Uploaded boundary",
            shows=m_["shows"].iloc[0] if len(m_) else "", years=years, avail=avail_,
            armor_ts=armor_run["ts"] if armor_run else None, armor_res=armor_res,
            extra_figures={k: v for k, v in st.session_state.get("figs", {}).items()
                           if k == "imagery-contact-sheet"},
            progress=lambda f, m: bar.progress(min(f, 1.0), text=f"Building: {m}"))
        bar.empty()
        st.session_state.pack = (zb, drawn)
    if st.session_state.get("pack"):
        zb, drawn = st.session_state.pack
        st.download_button("Download report pack (ZIP)", zb,
                           f"{_dl_name('field-report-pack')}.zip", "application/zip")
        st.caption(f"{len(zb) / 1e6:.1f} MB, {len(drawn)} charts. Charts from tabs that "
                   "were not run (the imagery contact sheet, soil armor before it is "
                   "read) are left out rather than shipped blank.")

    with st.expander("Method and limits"):
        st.markdown(
            f"**Imagery:** {SOURCE_LABELS[result.source]}, read from Microsoft "
            "Planetary Computer. Clouds, shadow and snow removed with the scene "
            "classification band (Sentinel-2) or Fmask (HLS, transferred to the "
            "Sentinel-2 NDVI scale); scenes keeping less than 75% of field pixels are "
            "dropped.\n\n"
            "**Crop type:** USDA Cropland Data Layer, 30 m, the dominant class inside "
            "the boundary.\n\n"
            "**Planting:** where the smoothed NDVI curve crosses 20% of its seasonal "
            "amplitude on the rising limb, offset by a crop-specific lag; for winter "
            "crops, the autumn emergence. Good to about two weeks; the window widens "
            "where cloud left a gap near the transition.\n\n"
            "**Harvest:** the drop off the falling limb, measured against the lowest "
            "point after the peak. A season still under way is left blank.\n\n"
            "**Weather check:** gridMET rain (and optionally daily-mean wind) at the "
            "field centroid moves each date to a workable day -- see the sidebar.\n\n"
            "**Cover crops:** off-season NDVI above the residue floor. Evidence, not "
            "proof -- see the Cover crops tab.\n\n"
            "**Not yet calibrated.** Every threshold here is a literature-typical "
            "starting value. Validating against fields with known planting dates and "
            "known cover crop use is what would make these numbers defensible.")
