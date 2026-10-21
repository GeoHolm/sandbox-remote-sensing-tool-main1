"""Results viewer for the field studies in project-level-tests/.

The studies ship their derived tables and figures but not their boundaries --
the FLASH and 4D farm outlines are grower data, and the county cohorts were cut
from a 2008 public CLU release that is not in the repository. So a study field
cannot be re-analyzed here; this page shows what the study already computed
for it. Nothing in this module reads imagery or touches the pipeline cache.

Farm names in project-FLASH/flash_comparison.csv are deliberately never read:
FLASH fields are shown by geometry hash and county only.
"""

from __future__ import annotations

import json
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

STUDIES_DIR = Path(__file__).resolve().parent.parent / "project-level-tests"

COHORTS = {
    "sumner-ks": "Sumner County, Kansas",
    "champaign-il": "Champaign County, Illinois",
    "mitchell-ga": "Mitchell County, Georgia",
}

# label -> (kind, directory, findings write-up)
STUDIES = {
    "Hyper-local benchmark · Sumner Co. KS": ("cohort", "sumner-ks", "SUMNER-FINDINGS.md"),
    "Hyper-local benchmark · Champaign Co. IL": ("cohort", "champaign-il", "COUNTY-COMPARISON.md"),
    "Hyper-local benchmark · Mitchell Co. GA": ("cohort", "mitchell-ga", "COUNTY-COMPARISON.md"),
    "Benchmark comparison across counties": ("across", "_across", "COUNTY-COMPARISON.md"),
    "FLASH project · 98 Illinois fields": ("flash", "project-FLASH", "FLASH-FINDINGS.md"),
    "4D farm · 4 Georgia fields": ("4d", "4d-farm", None),
    "Alfalfa cuttings · San Juan Co. NM": ("alfalfa", "alfalfa-nm", "ALFALFA-FINDINGS.md"),
}

NO_STUDY = "(none -- use the field library)"


def available_studies() -> list[str]:
    return [k for k, (_, d, _) in STUDIES.items() if (STUDIES_DIR / d).is_dir()]


@st.cache_data(show_spinner=False)
def _csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def _read(study_dir: str, name: str) -> pd.DataFrame | None:
    p = STUDIES_DIR / study_dir / name
    return _csv(str(p)) if p.exists() else None


def _percentile(value: float, others: pd.Series) -> float:
    """Share of the other fields below this one, ties counted half (0-100)."""
    o = others.dropna()
    if pd.isna(value) or o.empty:
        return np.nan
    return 100.0 * ((o < value).sum() + 0.5 * (o == value).sum()) / len(o)


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the 00:00:00 the study scripts wrote onto plain dates."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object and df[c].astype(str).str.endswith(" 00:00:00").any():
            df[c] = df[c].astype(str).str.replace(" 00:00:00", "", regex=False)
    return df


def _figures(study_dir: str) -> None:
    figs = sorted((STUDIES_DIR / study_dir / "figures").glob("*.png"))
    if not figs:
        figs = sorted((STUDIES_DIR / study_dir).glob("*.png"))
    if not figs:
        st.caption("This study has no figures.")
        return
    cols = st.columns(2)
    for i, f in enumerate(figs):
        with cols[i % 2]:
            st.image(str(f), caption=f.stem.replace("_", " "), width="stretch")


def _reports(study_dir: str, findings: str | None) -> None:
    for f in sorted((STUDIES_DIR / study_dir).glob("*.pdf")) + \
            sorted((STUDIES_DIR / study_dir).glob("*.pptx")):
        st.download_button(f"Download {f.name}", f.read_bytes(), file_name=f.name,
                           key=f"dl_{study_dir}_{f.name}")
    if findings and (STUDIES_DIR / findings).exists():
        with st.expander(f"Findings write-up ({findings})"):
            st.markdown((STUDIES_DIR / findings).read_text(encoding="utf-8"))


def _not_shared_note() -> None:
    st.caption("Results from a field study in project-level-tests/. The field "
               "boundaries were not shared, so this field cannot be re-analyzed or "
               "shown on imagery; everything below is what the study computed.")


# ------------------------------------------------------------ cohorts ---

def _cohort_field_label(row: pd.Series) -> str:
    if row["role"] == "focus":
        return f"Focus field · {row['acres']:.0f} ac"
    return f"{row['fid']} · {row['acres']:.0f} ac · {row['dist_m'] / 1000:.1f} km from focus"


def _cohort(d: str) -> None:
    cohort = _read(d, "cohort.csv")
    labels = {r["fid"]: _cohort_field_label(r) for _, r in cohort.iterrows()}
    fid = st.sidebar.selectbox("Study field", cohort["fid"].tolist(),
                               format_func=labels.get, key=f"study_field_{d}")
    me = cohort.set_index("fid").loc[fid]
    meta = json.loads((STUDIES_DIR / d / "cohort_meta.json").read_text())

    st.header(f"{COHORTS[d]} · {'focus field' if fid == 'focus' else fid}")
    _not_shared_note()
    status = _read(d, "status.csv")
    st_row = status.set_index("fid").loc[fid] if status is not None and fid in set(status["fid"]) else None
    c = st.columns(4)
    c[0].metric("Acres", f"{me['acres']:.0f}")
    c[1].metric("From focus field", f"{me['dist_m'] / 1000:.1f} km")
    c[2].metric(f"Fields within {meta['radius_m'] / 1000:.1f} km", f"{len(cohort)}")
    c[3].metric("Clear observations", "--" if st_row is None else f"{st_row['clear_obs']:.0f}")

    tab_map, tab_crops, tab_cover, tab_armor, tab_rank, tab_figs = st.tabs(
        ["Location", "Crops & seasons", "Cover crops", "Soil armor",
         "Rank vs neighbors", "Study figures"])

    with tab_map:
        m = folium.Map(location=[me["lat"], me["lon"]], zoom_start=13,
                       tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
                             "World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri")
        for _, r in cohort.iterrows():
            sel = r["fid"] == fid
            folium.CircleMarker(
                [r["lat"], r["lon"]], radius=9 if sel else 5,
                color="#F46C09" if sel else ("#ffffff" if r["role"] == "focus" else "#85b6ef"),
                fill=True, fill_opacity=0.9 if sel else 0.6,
                tooltip=f"{r['fid']} · {r['acres']:.0f} ac").add_to(m)
        st_folium(m, height=480, use_container_width=True, returned_objects=[],
                  key=f"study_map_{d}")
        st.caption("Field centers only (the outlines were not shared). Orange is the "
                   "selected field, white the focus field. Boundaries: "
                   f"{meta['source']}.")

    with tab_crops:
        st.subheader("Crop by year (CDL)")
        hist = _read(d, "history.csv")
        st.dataframe(hist[hist["fid"] == fid].drop(columns="fid"), hide_index=True,
                     width="stretch")
        st.subheader("Season estimates")
        phen = _read(d, "phenology.csv")
        st.dataframe(_dates(phen[phen["fid"] == fid].drop(columns="fid")),
                     hide_index=True, width="stretch")

    with tab_cover:
        cc = _read(d, "covercrop.csv")
        st.dataframe(_dates(cc[cc["fid"] == fid].drop(columns="fid")),
                     hide_index=True, width="stretch")
        st.warning("The cover crop threshold is not regional: the same cutoff calls "
                   "6% of Champaign winters green, 61% of Sumner's and 88% of "
                   "Mitchell's. Read max_ndvi as a continuous measure rather than "
                   "trusting the verdict (COUNTY-COMPARISON.md).")

    with tab_armor:
        st.subheader("Pre-planting window (the shipped score)")
        ar = _read(d, "armor.csv")
        st.dataframe(_dates(ar[ar["fid"] == fid].drop(columns="fid")),
                     hide_index=True, width="stretch")
        st.subheader("Calendar-year scores")
        ao = _read(d, "annual_armor_options.csv")
        mine = ao[ao["fid"] == fid][["year", "crop", "n_obs", "preplant", "residue",
                                     "worst", "mean", "exposure"]]
        st.dataframe(mine.rename(columns={"residue": "annual_residue",
                                          "worst": "annual_worst",
                                          "exposure": "exposure_days"}).round(3),
                     hide_index=True, width="stretch")

    with tab_rank:
        ao = _read(d, "annual_armor_options.csv")
        rows = []
        for _, r in ao[ao["fid"] == fid].iterrows():
            peers = ao[(ao["year"] == r["year"]) & (ao["fid"] != fid)]
            same = peers[peers["crop"] == r["crop"]]
            row = {"year": r["year"], "crop": r["crop"]}
            for col, name in [("preplant", "pre-plant armor"),
                              ("residue", "annual residue"), ("worst", "annual worst")]:
                row[f"{name} · all"] = _percentile(r[col], peers[col])
                row[f"{name} · same crop"] = _percentile(r[col], same[col])
            row["same-crop peers"] = len(same)
            rows.append(row)
        st.dataframe(pd.DataFrame(rows).round(0), hide_index=True,
                     width="stretch")
        st.caption("Percentile of this field among the other cohort fields in the same "
                   "year (100 = most cover). 'Same crop' compares only against "
                   "neighbors growing the same CDL crop that year; with few peers it "
                   "is noisy. In wheat country pre-plant armor mostly ranks the crop, "
                   "not the management -- prefer the annual scores there.")

    with tab_figs:
        _figures(d)
        _reports(d, next(f for _, sd, f in STUDIES.values() if sd == d))


# ------------------------------------------------------------- across ---

def _across(d: str) -> None:
    st.header("Hyper-local benchmarks across three counties")
    st.caption("Sumner Co. KS, Champaign Co. IL and Mitchell Co. GA compared. These "
               "results describe the cohorts rather than one field.")
    for name, title in [("compare_counties.csv", "County summary"),
                        ("benchmark_scale.csv", "How much variation sits between counties"),
                        ("match_focus.csv", "Focus fields under rotation matching")]:
        t = _read(d, name)
        if t is not None:
            st.subheader(title)
            st.dataframe(t, hide_index=True, width="stretch")
    st.subheader("Figures")
    _figures(d)
    _reports(d, "COUNTY-COMPARISON.md")


# -------------------------------------------------------------- FLASH ---

FLASH_GROUPS = {
    "Crop & season": ["crop_year", "cdl_crop", "cdl_crop_pct", "planting_est",
                      "harvest_est", "season_days", "peak_ndvi", "season_confidence"],
    "Cover crop": ["crop_year", "winter", "winter_n_obs", "winter_max_ndvi",
                   "winter_green_days", "cover_verdict", "cover_verdict_note",
                   "entered_cover_crop", "entered_cover_planted",
                   "entered_cover_terminated"],
    "Soil armor": ["crop_year", "armor_window_start", "armor_window_end", "armor_n_obs",
                   "armor", "f_pv_living", "f_npv_residue", "f_bs_bare", "armor_note"],
    "What was entered": ["crop_year", "entered_planting", "entered_harvest",
                         "entered_yield", "entered_yield_unit",
                         "entered_tillage_passes_pre_plant",
                         "entered_planting_shared_by_n_fields"],
}


def _flash(d: str) -> None:
    t = _read(d, "flash_field_year_findings.csv")
    fields = (t.groupby("field_key")
               .agg(county=("county", "first"), area_ha=("area_ha", "first"))
               .reset_index().sort_values(["county", "area_ha"]))
    lab = {r.field_key: f"{r.county.replace(' County', ' Co.')} · {r.area_ha:.0f} ha · "
                        f"{r.field_key[:6]}" for r in fields.itertuples()}
    key = st.sidebar.selectbox("Study field", fields["field_key"].tolist(),
                               format_func=lab.get, key="study_field_flash")
    mine = t[t["field_key"] == key].sort_values("crop_year")
    first = mine.iloc[0]

    st.header(f"FLASH · {first['county']} · field {key}")
    _not_shared_note()
    c = st.columns(4)
    c[0].metric("Area", f"{first['area_ha']:.1f} ha")
    c[1].metric("Boundary", str(first["boundary_verdict"]))
    c[2].metric("Location (0.1°)", f"{first['lat_0p1deg']:.1f}, {first['lon_0p1deg']:.1f}")
    c[3].metric("Crop years", f"{len(mine)}")

    tabs = st.tabs(list(FLASH_GROUPS) + ["All columns", "Study figures"])
    for tab, (name, cols) in zip(tabs, FLASH_GROUPS.items()):
        with tab:
            st.dataframe(mine[[c for c in cols if c in mine]], hide_index=True,
                         width="stretch")
    with tabs[-2]:
        st.dataframe(mine, hide_index=True, width="stretch")
        dic = _read(d, "flash_field_year_dictionary.csv")
        if dic is not None:
            with st.expander("What each column means"):
                st.dataframe(dic, hide_index=True, width="stretch")
    with tabs[-1]:
        st.caption("'entered_cover_crop' is yes / not_recorded: before 2026 a missing "
                   "cover crop is a record never kept, not a negative.")
        _figures(d)
        _reports(d, "FLASH-FINDINGS.md")


# ------------------------------------------------------------ 4D farm ---

def _fourd(d: str) -> None:
    cover = _read(d, "cover_crop.csv")
    field = st.sidebar.selectbox("Study field", sorted(cover["field"].unique()),
                                 key="study_field_4d")
    st.header(f"4D farm, Georgia · {field}")
    _not_shared_note()

    tab_ndvi, tab_crops, tab_cover, tab_grower = st.tabs(
        ["NDVI record", "Crops & seasons", "Cover crops", "Grower record"])
    with tab_ndvi:
        s = _read(d, "ndvi_series.csv")
        s = s[s["field"] == field].assign(date=lambda x: pd.to_datetime(x["date"]))
        st.line_chart(s.set_index("date")[["median"]].rename(columns={"median": "NDVI"}))
        st.caption(f"Field-median NDVI on {len(s)} clear Sentinel-2 dates.")
    with tab_crops:
        for name, title in [("cdl_by_year.csv", "Crop by year (CDL)"),
                            ("season_markers.csv", "Season estimates")]:
            t = _read(d, name)
            st.subheader(title)
            st.dataframe(t[t["field"] == field].drop(columns="field"), hide_index=True,
                         width="stretch")
    with tab_cover:
        st.dataframe(cover[cover["field"] == field].drop(columns="field"),
                     hide_index=True, width="stretch")
    with tab_grower:
        anc = _read(d, "ancillary_summary.csv")
        st.dataframe(anc[anc["field"] == field].drop(columns="field"), hide_index=True,
                     width="stretch")
        st.caption("From the grower's 4D vendor export, kept apart from the satellite "
                   "estimates. The filled OpenET workbook is in project-level-tests/4d-farm/.")


# ------------------------------------------------------------ alfalfa ---

def _alfalfa(d: str) -> None:
    loc = json.loads((STUDIES_DIR / d / "location.json").read_text())
    st.header(f"Alfalfa cuttings · {loc['county']} County, {loc['state']}")
    st.caption(f"One {loc['acres']:.0f}-acre field, a hand-drawn rectangle inside a "
               "center pivot. Winter wheat 2020-21, alfalfa from 2022. The boundary "
               "and NDVI pack were not shared, so only the study's results are here.")
    tab_sum, tab_cuts, tab_figs = st.tabs(["Cuttings by year", "Every cutting",
                                           "Study figures"])
    with tab_sum:
        st.dataframe(_read(d, "cutting_summary.csv"), hide_index=True,
                     width="stretch")
        m = folium.Map(location=[loc["lat"], loc["lon"]], zoom_start=15,
                       tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
                             "World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri")
        folium.CircleMarker([loc["lat"], loc["lon"]], radius=8, color="#F46C09",
                            fill=True).add_to(m)
        st_folium(m, height=380, use_container_width=True, returned_objects=[],
                  key="study_map_alfalfa")
    with tab_cuts:
        st.dataframe(_read(d, "cuttings.csv"), hide_index=True, width="stretch")
    with tab_figs:
        _figures(d)
        _reports(d, "ALFALFA-FINDINGS.md")


# --------------------------------------------------------------- page ---

def render(label: str) -> None:
    """Draw the results page for one study (its field picker goes in the sidebar)."""
    kind, d, _ = STUDIES[label]
    {"cohort": _cohort, "across": _across, "flash": _flash, "4d": _fourd,
     "alfalfa": _alfalfa}[kind](d)
