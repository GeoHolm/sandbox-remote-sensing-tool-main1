"""Look at the imagery.

Port of R/plotting.R + the plotting halves of R/cdl_split.R, R/phenology.R and
R/covercrop.R. Every function here returns a matplotlib Figure -- the natural
fit for Streamlit's ``st.pyplot`` -- rather than writing a PNG like the R
originals, since there is no app-less reason for this module to exist; it
exists to be looked at.
"""

from __future__ import annotations

from datetime import timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Rectangle

from .cropland import CDL_CLASSES, cdl_name, cdl_summary

# ------------------------------------------------------------- palettes ---

# Brown (bare) through to dark green -- same stops as R's veg_palette().
VEG_PALETTE = LinearSegmentedColormap.from_list(
    "veg", ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"]
)

# A few familiar CDL colours so plots of common crops look conventional; the
# rest are assigned from a categorical colormap per-plot.
CDL_COLOURS = {
    1: "#ffd300", 5: "#267000", 24: "#a57000", 36: "#ffa5e2",
    37: "#a5f28c", 61: "#bfbf77", 111: "#4970a3",
    121: "#9c9c9c", 122: "#9c9c9c", 123: "#9c9c9c", 124: "#9c9c9c",
    141: "#93cc93", 176: "#e8ffbf", 190: "#7fb2b2", 195: "#7fb2b2",
}


def _stretch(arr: np.ndarray, q=(0.02, 0.98), gamma: float = 0.8) -> np.ndarray:
    """Percentile-stretch a band to 0-1 for display, then a tone curve.

    Raw reflectance is mostly dark values; a straight linear map to 0-1 gives
    a near-black image. Clipping at the 2nd/98th percentile is what makes
    satellite RGB look like a photograph. Display only -- never touches the
    values anything downstream analyses.
    """
    v = arr[np.isfinite(arr)]
    if v.size == 0:
        return np.zeros_like(arr)
    lo, hi = np.percentile(v, [q[0] * 100, q[1] * 100])
    if hi <= lo:
        lo, hi = float(v.min()), float(v.max())
    if hi <= lo:
        return np.zeros_like(arr)
    out = np.clip((arr - lo) / (hi - lo), 0, 1)
    return np.clip(out ** gamma, 0, 1)


def _composite(bands: dict[str, np.ndarray], order: list[str]) -> np.ndarray:
    chans = [_stretch(bands[b]) for b in order]
    rgb = np.stack(chans, axis=-1)
    na = ~np.isfinite(bands[order[0]])
    for b in order[1:]:
        na |= ~np.isfinite(bands[b])
    rgb[na] = 0.92          # masked pixels read as pale grey, matching R
    return rgb


def plot_rgb(bands: dict[str, np.ndarray], date=None, title: str | None = None):
    """True-colour composite. ``bands`` needs red, green, blue."""
    need = ["red", "green", "blue"]
    missing = [b for b in need if b not in bands]
    if missing:
        raise KeyError(f"RGB needs band(s): {', '.join(missing)}")
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.imshow(_composite(bands, need))
    ax.set_title(title or f"True colour  |  {date or ''}")
    ax.axis("off")
    fig.tight_layout()
    return fig


def plot_false_colour(bands: dict[str, np.ndarray], date=None, title: str | None = None):
    """False-colour infrared composite (NIR-red-green). Healthy canopy glows red."""
    need = ["nir", "red", "green"]
    missing = [b for b in need if b not in bands]
    if missing:
        raise KeyError(f"False colour needs band(s): {', '.join(missing)}")
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.imshow(_composite(bands, need))
    ax.set_title(title or f"False colour (NIR)  |  {date or ''}")
    ax.axis("off")
    fig.tight_layout()
    return fig


def plot_index_map(idx: np.ndarray, name: str = "ndvi", date=None,
                   vrange: tuple[float, float] = (-1, 1)):
    """Map of a computed index array."""
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(idx, cmap=VEG_PALETTE, vmin=vrange[0], vmax=vrange[1])
    ax.set_title(f"{name.upper()}  |  {date or ''}")
    ax.axis("off")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    return fig


def plot_index_hist(idx: np.ndarray, name: str = "ndvi", date=None):
    """Histogram of index values inside the field, with the mean marked."""
    v = idx[np.isfinite(idx)]
    if v.size == 0:
        raise ValueError("No valid pixels to plot.")
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.hist(v, bins=40, color="#5ab4ac", edgecolor="white")
    ax.axvline(v.mean(), color="#8c510a", lw=2, ls="--",
              label=f"mean {v.mean():.3f}\nsd {v.std():.3f}\nn {v.size}")
    ax.set_title(f"{name.upper()} distribution  |  {date or ''}")
    ax.set_xlabel(name.upper())
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- CDL ---

def _cdl_colour_map(codes: list[int]) -> dict[int, str]:
    codes = sorted(codes)
    cmap = plt.get_cmap("Set3", max(len(codes), 2))
    cols = {c: cmap(i / max(len(codes) - 1, 1)) for i, c in enumerate(codes)}
    for c in codes:
        if c in CDL_COLOURS:
            cols[c] = CDL_COLOURS[c]
    return cols


def _cdl_to_rgb(arr: np.ndarray, cols: dict[int, str]) -> np.ndarray:
    from matplotlib.colors import to_rgb
    out = np.full(arr.shape + (3,), 0.95, dtype="float32")   # "#f2f2f2" no-data
    for code, col in cols.items():
        out[arr == code] = to_rgb(col)
    return out


def plot_cdl_map(arr: np.ndarray, year: int, crop: str, pct: float,
                 cols: dict[int, str] | None = None):
    """One year's CDL, coloured by class."""
    codes = sorted({int(c) for c in np.unique(arr[np.isfinite(arr)])})
    cols = cols or _cdl_colour_map(codes)
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(_cdl_to_rgb(arr, cols))
    ax.set_title(f"{year}  -  {crop} ({pct:.0f}%)", fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    return fig


def plot_cdl_matrix(stack, min_pct: float = 1.0, ncol: int = 3):
    """Every year's CDL as a grid of maps with one shared legend."""
    years = list(stack.years)
    codes: set[int] = set()
    summaries = {}
    for y in years:
        s = cdl_summary(stack.year(y), stack.pixel_ha)
        summaries[y] = s
        codes |= set(s.loc[s["pct"] >= min_pct, "code"].astype(int))
    cols = _cdl_colour_map(sorted(codes))

    nc = min(ncol, len(years))
    nr = int(np.ceil(len(years) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(3.2 * nc, 3.2 * nr + 1), squeeze=False)
    for i, y in enumerate(years):
        ax = axes[i // nc][i % nc]
        s = summaries[y]
        ax.imshow(_cdl_to_rgb(stack.year(y), cols))
        ax.set_title(f"{y}  -  {s.crop[0]} ({s.pct[0]:.0f}%)", fontsize=10)
        ax.axis("off")
    for i in range(len(years), nr * nc):
        axes[i // nc][i % nc].axis("off")

    handles = [Rectangle((0, 0), 1, 1, color=cols[c]) for c in sorted(codes)]
    labels = [cdl_name(c) for c in sorted(codes)]
    fig.legend(handles, labels, loc="lower center", ncol=min(4, len(codes)),
              frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.02 / nr))
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def plot_cdl_split(advice):
    """Map of the area flagged as persistently different from the field's
    dominant crop -- SplitAdvice.persist, with the flagged region outlined.
    """
    fig, ax = plt.subplots(figsize=(6.5, 5))
    pal = LinearSegmentedColormap.from_list("split", ["#f7f7f7", "#fdd49e", "#d7301f"])
    im = ax.imshow(advice.persist, cmap=pal, vmin=0, vmax=1)
    if advice.flagged is not None and advice.flagged.any():
        ax.contour(advice.flagged.astype(float), levels=[0.5], colors="#d7301f", linewidths=2)
    ax.set_title(
        f"Share of years each pixel differs from the field's dominant crop\n"
        f"({min(advice.years)}-{max(advice.years)})", fontsize=10,
    )
    ax.axis("off")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------- catalogue ---

_TIMELINE_ORDER = ["NAIP aerial", "USDA CDL", "MODIS NDVI 16-day", "Sentinel-1 radar",
                   "HLS Landsat", "HLS Sentinel-2", "Landsat 8/9", "Sentinel-2 L2A"]


def plot_catalog_timeline(avail: pd.DataFrame, title: str | None = None):
    """One row per source, one mark per acquisition, shaded by cloud cover."""
    fig, ax = plt.subplots(figsize=(9, 0.55 * max(len(avail["label"].unique()), 1) + 1))
    if avail is None or not len(avail):
        ax.text(0.5, 0.5, "No acquisitions found", ha="center", va="center")
        ax.axis("off")
        return fig

    present = list(avail["label"].unique())
    labs = [l for l in _TIMELINE_ORDER if l in present] + \
           [l for l in present if l not in _TIMELINE_ORDER]

    ramp = LinearSegmentedColormap.from_list("cloud", ["#01665e", "#d8b365"])
    for k, lab in enumerate(labs):
        d = avail[avail["label"] == lab]
        cl = d["cloud"].to_numpy()
        na = ~np.isfinite(cl)
        colors = [ramp(min(max(c, 0), 100) / 100) if not n else "#2c7fb8"
                 for c, n in zip(np.nan_to_num(cl), na)]
        ax.scatter(d["date"], [k] * len(d), marker="|", s=110, c=colors, linewidths=1.3)

    ax.set_yticks(range(len(labs)))
    ax.set_yticklabels(labs, fontsize=9)
    ax.set_ylim(-0.5, len(labs) - 0.5)
    ax.grid(axis="x", color="#eeeeee")
    ax.set_title(title or "Data available for this field")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))

    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], marker="|", color=c, linestyle="", markersize=10)
              for c in ["#01665e", "#d8b365", "#2c7fb8"]]
    ax.legend(handles, ["clear", "cloudy", "no cloud metric (radar/annual)"],
             loc="upper left", bbox_to_anchor=(0, 1.18), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------- phenology ---

def plot_phenology(ts: pd.DataFrame, year: int, phen: pd.Series | dict | None = None,
                   crop: str | None = None, index: str = "ndvi",
                   weather: pd.DataFrame | None = None,
                   wind_max_kmh: float | None = None):
    """One season's NDVI curve with planting/harvest markers and windows.

    With ``weather`` (gridMET daily, ``pr_mm``), daily rain is drawn as bars on
    a second axis, and the rain-free final dates (``planting_date`` /
    ``harvest_date``) as solid lines beside the dashed NDVI estimates.
    With ``wind_max_kmh`` as well, days whose daily-mean wind reaches it are
    marked with grey ticks along the bottom.
    """
    from .phenology import daily_series

    def _get(k):
        if phen is None:
            return None
        try:
            return phen.get(k) if isinstance(phen, dict) else phen[k]
        except KeyError:
            return None

    # A winter crop's season starts in the autumn before its harvest year.
    winter = str(_get("season_type") or "").startswith("winter")
    lo = pd.Timestamp(f"{year - 1}-08-01") if winter else pd.Timestamp(f"{year}-01-01")
    hi = pd.Timestamp(f"{year}-10-31") if winter else pd.Timestamp(f"{year}-12-31")
    d = ts[(ts["index"] == index) & (ts["date"] >= lo) & (ts["date"] <= hi)]
    fig, ax = plt.subplots(figsize=(7, 4))
    if len(d) < 5:
        ax.text(0.5, 0.5, "Not enough data", ha="center", va="center")
        ax.axis("off")
        return fig

    try:
        curve = daily_series(d, index)
    except ValueError:
        curve = None

    ax.set_ylim(0, 1)
    ax.grid(color="#eeeeee")
    title = f"{year - 1}-{str(year)[2:]}" if winter else f"{year}"
    if pd.notna(crop):
        title += f"  |  {crop}"
    stype = _get("season_type")
    if stype and stype != "summer":
        title += f"  ({stype})"
    ax.set_title(title)
    ax.set_ylabel(index.upper())

    plant = _get("planting_est")
    if plant is not None and pd.notna(plant):
        ax.axvspan(_get("planting_lo"), _get("planting_hi"), color="#2c7fb8", alpha=0.13)
        harvest = _get("harvest_est")
        if harvest is not None and pd.notna(harvest):
            ax.axvspan(_get("harvest_lo"), _get("harvest_hi"), color="#d95f0e", alpha=0.13)

    if curve is not None:
        ax.plot(curve["date"], curve["value"], color="#01665e", lw=2)
    ax.scatter(d["date"], d["mean"], color="#01665e", s=18, zorder=5)

    if weather is not None and "pr_mm" in weather and len(weather):
        w = weather[(weather["date"] >= lo) & (weather["date"] <= hi)]
        if len(w):
            ax2 = ax.twinx()
            ax2.bar(w["date"], w["pr_mm"], width=1.0, color="#6a8caf", alpha=0.45)
            ax2.set_ylim(0, max(float(w["pr_mm"].max()), 1.0) * 3)  # keep bars low
            ax2.invert_yaxis()                                     # hang from the top
            ax2.set_ylabel("rain (mm/day)", color="#6a8caf")
            ax2.tick_params(axis="y", colors="#6a8caf")
            if wind_max_kmh is not None and "wind_kmh" in w:
                windy = w.loc[w["wind_kmh"] >= wind_max_kmh, "date"]
                ax.scatter(windy, np.full(len(windy), 0.012), marker="|", s=60,
                           color="#777777", zorder=6)

    def _final(k):
        try:
            v = _get(k)
        except KeyError:
            return None
        return v if v is not None and pd.notna(v) else None

    for ev, colour in (("planting", "#2c7fb8"), ("harvest", "#d95f0e")):
        est = _final(f"{ev}_est")
        if est is None:
            continue
        final = _final(f"{ev}_date")
        ax.axvline(est, color=colour, lw=1.5 if final is not None else 2, ls="--")
        if final is not None:
            ax.axvline(final, color=colour, lw=2.5)
        ax.text(final if final is not None else est, 0.03, f" {ev}",
                color=colour, fontsize=9)

    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


# --------------------------------------------------------- cover crop ---

def _verdict_tone(v: str) -> str:
    if v.startswith("likely"):
        return "#01665e"
    if "small grain" in v or "possible" in v:
        return "#b8860b"
    if "winter cash" in v:
        return "#7570b3"
    return "#8c510a"


def plot_cover_crop(ts: pd.DataFrame, cc: pd.Series | dict, index: str = "ndvi"):
    """One off-season window with the residue and green thresholds drawn on."""
    from .covercrop import CC_GREEN_MIN, CC_RESIDUE_MAX

    def _get(k):
        return cc.get(k) if isinstance(cc, dict) else cc[k]

    ws, we = _get("window_start"), _get("window_end")
    pad = timedelta(days=30)
    d = ts[(ts["index"] == index) & (ts["date"] >= ws - pad) & (ts["date"] <= we + pad)]

    fig, ax = plt.subplots(figsize=(7, 4))
    if len(d) < 3:
        ax.text(0.5, 0.5, "Not enough off-season data", ha="center", va="center")
        ax.axis("off")
        return fig

    tone = _verdict_tone(_get("verdict"))
    ax.set_ylim(0, 1)
    ax.set_ylabel(index.upper())
    ax.set_title(f"Off-season {_get('winter')}  |  {_get('verdict')}", fontsize=10)
    ax.axvspan(ws, we, color=tone, alpha=0.13)
    ax.axhline(CC_RESIDUE_MAX, color="#8c510a", ls=":", lw=1)
    ax.axhline(CC_GREEN_MIN, color="#01665e", ls=":", lw=1)
    ax.plot(d["date"], d["mean"], color="#01665e", lw=1.5)
    ax.scatter(d["date"], d["mean"], color="#01665e", s=14, zorder=5)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def plot_cover_crop_matrix(ts: pd.DataFrame, cc: pd.DataFrame, index: str = "ndvi", ncol: int = 3):
    """Every winter's off-season window, on a shared Oct->Jun axis.

    Cover crop seeding (purple) and termination (magenta) are drawn where
    estimated: dashed at the NDVI estimate, solid at the final (rain-free) date
    when the rain check ran.
    """
    from .covercrop import CC_GREEN_MIN, CC_RESIDUE_MAX

    if cc is None or not len(cc):
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "No off-season windows", ha="center", va="center")
        ax.axis("off")
        return fig

    n = len(cc)
    nc = min(ncol, n)
    nr = int(np.ceil(n / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(4.2 * nc, 3 * nr), squeeze=False)
    ticks = [0, 61, 122, 182, 243]
    labs = ["Oct", "Dec", "Feb", "Apr", "Jun"]

    # Shared y-axis across every panel, so winters stay visually comparable --
    # but sized to what the data actually needs. A fixed 0-0.8 (R's original)
    # clips winters with a strong cash crop or double-crop green-up: this
    # field's California winter reaches 0.95, well above that ceiling.
    windows = []
    for _, r in cc.iterrows():
        ref = pd.Timestamp(f"{int(r['fall_year'])}-10-01")
        d = ts[(ts["index"] == index) & (ts["date"] >= ref - timedelta(days=20)) &
              (ts["date"] <= ref + timedelta(days=260))]
        windows.append(d)
    obs_max = max((d["mean"].max() for d in windows if len(d)), default=0.8)
    ymax = min(1.0, max(0.8, obs_max * 1.1))

    for i, (r, d) in enumerate(zip((row for _, row in cc.iterrows()), windows)):
        ax = axes[i // nc][i % nc]
        ref = pd.Timestamp(f"{int(r['fall_year'])}-10-01")
        x = (d["date"] - ref).dt.days

        tone = _verdict_tone(r["verdict"])
        ax.set_xlim(-20, 260)
        ax.set_ylim(0, ymax)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labs, fontsize=8)
        ax.axvspan((r["window_start"] - ref).days, (r["window_end"] - ref).days,
                  color=tone, alpha=0.13)
        ax.axhline(CC_RESIDUE_MAX, color="#8c510a", ls=":", lw=1)
        ax.axhline(CC_GREEN_MIN, color="#01665e", ls=":", lw=1)
        if len(d):
            ax.plot(x, d["mean"], color="#01665e", lw=1.5)
            ax.scatter(x, d["mean"], color="#01665e", s=10, zorder=5)
        for ev, colour in (("seeding", "#7b3294"), ("termination", "#c51b7d")):
            est, final = r.get(f"{ev}_est"), r.get(f"{ev}_date")
            if est is None or pd.isna(est):
                continue
            ax.axvline((est - ref).days, color=colour, lw=1.2, ls="--")
            if final is not None and pd.notna(final):
                ax.axvline((final - ref).days, color=colour, lw=2.2)
        ax.set_title(r["winter"], fontsize=10)
        ax.text(0.02, 0.9, f"{r['verdict'][:28]}  (max {r['max_ndvi']:.2f}, n={r['n_obs']})",
               transform=ax.transAxes, fontsize=7, color=tone)

    for i in range(n, nr * nc):
        axes[i // nc][i % nc].axis("off")
    fig.tight_layout()
    return fig


# --------------------------------------------------------------- soil armor ---

def plot_armor(ts: pd.DataFrame, res: pd.DataFrame, ncol: int = 4):
    """Cover fractions through each calendar year, pre-planting window shaded.

    Port of R ``plot_armor()``. Teal is living cover, tan is residue, and the
    white gap to the top is bare soil -- the quantity being measured, so it is
    left as empty space rather than read off a legend. The dashed, shaded band
    is the pre-planting window the reported armor figure is averaged over.
    """
    years = sorted(int(y) for y in res["year"].unique())
    if not years:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "No season had a readable residue window", ha="center")
        ax.axis("off")
        return fig
    nc = min(ncol, len(years))
    nr = int(np.ceil(len(years) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(3.6 * nc, 2.7 * nr), squeeze=False)

    w = (ts.pivot_table(index="date", columns="index", values="mean")
           .sort_index())
    for i, y in enumerate(years):
        ax = axes[i // nc][i % nc]
        r = res[res["year"] == y].iloc[0]
        lo, hi = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        d = (w[(w.index >= lo) & (w.index <= hi)].dropna(subset=["f_bs"])
             if "f_bs" in w else pd.DataFrame())
        ax.set_xlim(lo, hi)
        ax.set_ylim(0, 1)
        armor = r.get("armor")
        ax.set_title(f"{y}" + ("  (no reading)" if armor is None or pd.isna(armor)
                               else f"   armor {armor:.2f}"), fontsize=9)
        if len(d) > 1:
            pv = d["f_pv"].clip(0, 1)
            top = (d["f_pv"] + d["f_npv"]).clip(0, 1)
            ax.fill_between(d.index, 0, pv, color="#5ab4ac", lw=0)
            ax.fill_between(d.index, pv, top, color="#d8b365", lw=0)
            ax.plot(d.index, top, color="#4d4d4d", lw=1.2)
            ax.scatter(d.index, top, s=6, color="#333333", zorder=5)
        ws, we = r.get("window_start"), r.get("window_end")
        if ws is not None and pd.notna(ws):
            ax.axvspan(ws, we, color="black", alpha=0.05, lw=0)
            for v in (ws, we):
                ax.axvline(v, color="#595959", ls="--", lw=1)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=range(1, 13, 2)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.tick_params(labelsize=7)
        if i % nc == 0:
            ax.set_ylabel("cover fraction", fontsize=8)
        if i == 0:
            from matplotlib.patches import Patch
            ax.legend(handles=[Patch(color="#5ab4ac", label="living"),
                               Patch(color="#d8b365", label="residue"),
                               Patch(facecolor="white", edgecolor="#999999", label="bare")],
                      loc="lower left", ncol=3, fontsize=6, frameon=False)
    for j in range(len(years), nr * nc):
        axes[j // nc][j % nc].axis("off")
    fig.tight_layout()
    return fig


# ----------------------------------------------------------- whole record ---

def plot_phenology_timeline(ts: pd.DataFrame, phen: pd.DataFrame | None = None,
                            index: str = "ndvi", panels: int = 2,
                            shade_offseason: bool = True):
    """The whole record, optionally split across stacked panels.

    Port of R ``plot_phenology_timeline()``. A season at a time hides what the
    multi-year record shows best: the rotation, how planting moves year to
    year, and whether anything grows between seasons. The smoothed curve is
    fitted per year, never across the whole span -- one smoothing parameter
    cannot represent seven annual cycles.

    Dashed lines are the NDVI estimates; where the weather check has run, solid
    lines mark the final (weather-checked) dates. Shading is the off-season,
    from the previous harvest to this season's planting -- for a winter crop
    that is its autumn sowing.
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from .phenology import daily_series

    d = ts[ts["index"] == index]
    if len(d) < 10:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "Not enough data", ha="center", va="center")
        ax.axis("off")
        return fig

    years = sorted(int(y) for y in d["date"].dt.year.unique())
    panels = max(1, min(panels, len(years)))
    per = int(np.ceil(len(years) / panels))
    groups = [years[i:i + per] for i in range(0, len(years), per)]
    fig, axes = plt.subplots(len(groups), 1, figsize=(13, 3.3 * len(groups)),
                             squeeze=False)
    p_by = {} if phen is None else {int(r["year"]): r for _, r in phen.iterrows()}
    harvests = ([] if phen is None else
                [pd.Timestamp(h) for h in phen["harvest_est"] if pd.notna(h)])

    def _v(r, k):
        v = r.get(k) if r is not None else None
        return None if v is None or pd.isna(v) else pd.Timestamp(v)

    for ax, grp in zip(axes[:, 0], groups):
        lo, hi = pd.Timestamp(f"{min(grp)}-01-01"), pd.Timestamp(f"{max(grp)}-12-31")
        dd = d[(d["date"] >= lo) & (d["date"] <= hi)]
        ax.set_xlim(lo, hi)
        ax.set_ylim(0, 1)
        ax.set_ylabel(index.upper())
        ax.set_title(str(grp[0]) if len(grp) == 1 else f"{min(grp)} - {max(grp)}",
                     fontsize=11)
        ax.grid(axis="y", color="#eeeeee")
        for y in grp:
            p = p_by.get(y)
            plant = _v(p, "planting_est")
            if shade_offseason and plant is not None:
                # From the most recent harvest before this planting, in any
                # year: before a wheat sowing the previous year is fallow, and
                # the off-season runs back to the wheat harvest before it.
                earlier = [h for h in harvests if h < plant]
                left = max(earlier) if earlier else pd.Timestamp(f"{y - 1}-11-01")
                if left < plant:
                    ax.axvspan(max(left, lo), plant, color="#5ab4ac", alpha=0.10, lw=0)
            dy = dd[dd["date"].dt.year == y]
            if len(dy) >= 8:
                try:
                    cur = daily_series(dy, index)
                    ax.plot(cur["date"], cur["value"], color="#01665e", lw=1.8)
                except ValueError:
                    pass
            ax.axvline(pd.Timestamp(f"{y}-01-01"), color="#cccccc", ls=":", lw=1)
            if p is None:
                continue
            for ev, colour in (("planting", "#2c7fb8"), ("harvest", "#d95f0e")):
                est, final = _v(p, f"{ev}_est"), _v(p, f"{ev}_date")
                if est is not None and lo <= est <= hi:
                    ax.axvline(est, color=colour, lw=1.6, ls="--")
                if final is not None and lo <= final <= hi:
                    ax.axvline(final, color=colour, lw=2.2)
            crop = p.get("crop")
            if isinstance(crop, str):
                ax.text(pd.Timestamp(f"{y}-07-01"), 0.045, crop, ha="center",
                        fontsize=8, color="#404040")
        ax.scatter(dd["date"], dd["mean"], s=5, color="#01665e", zorder=5)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.tick_params(axis="x", labelsize=8)

    axes[-1, 0].legend(handles=[
        Line2D([], [], color="#2c7fb8", ls="--", lw=1.6, label="planting"),
        Line2D([], [], color="#d95f0e", ls="--", lw=1.6, label="harvest"),
        Patch(color="#5ab4ac", alpha=0.25, label="off-season")],
        loc="lower right", ncol=3, fontsize=8, frameon=False)
    fig.tight_layout()
    return fig
