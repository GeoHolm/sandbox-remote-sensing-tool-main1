#!/usr/bin/env python3
"""A focus field and its cohort, on aerial imagery with a county inset.

    python project-level-tests/figure_cohort_map.py <project-dir> [--bare]

Writes 01_cohort_map.png. Needs the network: NAIP from the Planetary
Computer and county outlines from the Census.

Four NAIP quarter-quads cover the cohort, all flown 22 July 2023 at 0.3 m
and all in EPSG:26914, so the mosaic is a straight merge with no warp. They
are read down to about 3.5 m on the way in -- the panel is 9 km across and
nothing here needs 30,000 pixels of it.

The inset is Kansas with Sumner County filled. The county is read from the
Census polygon containing the focus centroid rather than asserted, the same
check used for the New Mexico field.

The dashed circle is the selection rule made visible: the radius that had
to be reached to collect 100 qualifying fields. Fields inside it that are
NOT outlined failed one of the filters -- too small, too thin, or not
cropland in at least three of the last four CDL years -- and showing the
circle is the honest way to say that the cohort is a filtered subset of the
neighborhood, not every field in it.
"""
import argparse
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import planetary_computer  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.merge import merge  # noqa: E402
from shapely.geometry import Point  # noqa: E402

HERE = Path(__file__).resolve().parent

CENSUS = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_%s_20m.zip"
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
BLUE, ORANGE = "#165bac", "#F46C09"
GRID = "#e6e6e6"
TARGET_RES = 3.5          # metres per pixel in the mosaic

# Text over aerial imagery needs a halo or it disappears into whichever
# field happens to sit behind it.
HALO_W = [pe.withStroke(linewidth=2.8, foreground="#00000088")]
HALO_D = [pe.withStroke(linewidth=3.0, foreground="#ffffffcc")]

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 11,
    "text.color": INK, "axes.edgecolor": GRID,
})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", help="project directory, e.g. champaign-il")
    ap.add_argument("--bare", action="store_true")
    a = ap.parse_args()
    PROJ = HERE / a.proj
    fig_dir = PROJ / "figures" / "deck" if a.bare else PROJ / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # ---- boundaries -------------------------------------------------------
    parts = []
    for p in sorted((PROJ / "boundaries").glob("*.geojson")):
        g = gpd.read_file(p)
        g["fid"] = p.stem
        parts.append(g)
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    meta = pd.read_csv(PROJ / "cohort.csv")
    radius = float(pd.read_json(PROJ / "cohort_meta.json",
                                typ="series")["radius_m"])
    focus = g[g.fid == "focus"]
    cohort = g[g.fid != "focus"]
    print("%d polygons (1 focus, %d cohort), radius %.0f m"
          % (len(g), len(cohort), radius))

    lon = float(meta.loc[meta.fid == "focus", "lon"].iloc[0])
    lat = float(meta.loc[meta.fid == "focus", "lat"].iloc[0])

    # ---- county -----------------------------------------------------------
    print("reading Census boundaries ...")
    cty = gpd.read_file("zip+" + CENSUS % "county")
    st = gpd.read_file("zip+" + CENSUS % "state")
    hit = cty[cty.contains(Point(lon, lat))]
    if len(hit) != 1:
        sys.exit("expected one county to contain the focus field, got %d" % len(hit))
    COUNTY, STATE, STUSPS = (hit.NAME.iloc[0], hit.STATE_NAME.iloc[0],
                             hit.STUSPS.iloc[0])
    print("located in %s County, %s" % (COUNTY, STATE))

    # ---- NAIP mosaic ------------------------------------------------------
    print("searching NAIP ...")
    cat = pystac_client.Client.open(PC_STAC)
    items = list(cat.search(collections=["naip"],
                            bbox=list(g.total_bounds)).items())
    if not items:
        sys.exit("no NAIP coverage")
    newest = max(i.datetime for i in items).date()
    use = [i for i in items if i.datetime.date() == newest]
    print("using %d tile(s) flown %s at %s m"
          % (len(use), newest, use[0].properties.get("gsd")))

    crs_m = rasterio.crs.CRS.from_string(
        use[0].properties.get("proj:code")
        or "EPSG:%d" % use[0].properties["proj:epsg"])
    gm = g.to_crs(crs_m)
    x0, y0, x1, y1 = gm.total_bounds
    pad = 0.045 * max(x1 - x0, y1 - y0)
    bounds = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    srcs = []
    for it in use:
        for attempt in range(4):
            try:
                srcs.append(rasterio.open(
                    planetary_computer.sign(it.assets["image"].href)))
                break
            except Exception as exc:                        # transient COG
                if attempt == 3:
                    raise
                print("   open failed (%s), retrying" % type(exc).__name__)
                time.sleep(3)
    mos, tr = merge(srcs, bounds=bounds, res=TARGET_RES, indexes=[1, 2, 3],
                    resampling=Resampling.average)
    for s in srcs:
        s.close()
    img = np.transpose(mos, (1, 2, 0)).astype(float) / 255.0
    print("mosaic %d x %d px at %.1f m" % (img.shape[1], img.shape[0], TARGET_RES))
    extent = (bounds[0], bounds[2], bounds[1], bounds[3])

    # ---- render -----------------------------------------------------------
    fig, ax = plt.subplots(figsize=(11.6, 6.6) if a.bare else (11.6, 7.2))
    ax.imshow(img, extent=extent, origin="upper", interpolation="bilinear")

    fc = gm[gm.fid == "focus"]
    cm = gm[gm.fid != "focus"]
    cm.boundary.plot(ax=ax, color="white", linewidth=1.15, alpha=.95, zorder=4)
    fc.boundary.plot(ax=ax, color=ORANGE, linewidth=3.0, zorder=6)

    cen = fc.geometry.iloc[0].centroid
    # Black dashes over a white casing, the same two-pass treatment the scale
    # bar and the labels get. A single white circle vanished against Mitchell
    # County, which is wall-to-wall pale pivot; a single black one would do
    # the same against Champaign, which is dark green all summer. Drawn with
    # one dash pattern and two widths, the casing shows only as a thin
    # outline and the line reads on either.
    for col, lw, z in (("white", 4.2, 5), ("#141414", 1.9, 6)):
        ax.add_patch(mpatches.Circle((cen.x, cen.y), radius, fill=False,
                                     edgecolor=col, linewidth=lw,
                                     linestyle=(0, (7, 5)), alpha=.92,
                                     zorder=z))
    # Both annotations anchor INSIDE the axes. Pointing at a spot above the
    # circle put the label outside the frame, where matplotlib drew it
    # straight through the figure title.
    ang = np.radians(208)
    ax.annotate("%.1f km\nthe radius needed to reach\n%d qualifying fields"
                % (radius / 1000, len(cm)),
                xy=(cen.x + radius * np.cos(ang), cen.y + radius * np.sin(ang)),
                xytext=(cen.x - radius * .92, cen.y - radius * .30),
                fontsize=10, color="white", fontweight="bold", ha="left",
                va="top", zorder=9, path_effects=HALO_W,
                arrowprops=dict(arrowstyle="-", color="white", lw=1.4))
    ax.annotate("focus field\n%.0f acres"
                % float(meta.loc[meta.fid == "focus", "acres"].iloc[0]),
                xy=(cen.x, cen.y), xytext=(cen.x + radius * .26,
                cen.y - radius * .34), fontsize=12, color=ORANGE,
                fontweight="bold", ha="left", zorder=9, path_effects=HALO_D,
                arrowprops=dict(arrowstyle="-", color=ORANGE, lw=2.2))

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_edgecolor("#b9bcc0")

    span = extent[1] - extent[0]
    bar = 2000.0
    bx, by = extent[0] + span * .040, extent[2] + span * .040
    for col, lw in (("white", 5.0), (INK, 2.2)):
        ax.plot([bx, bx + bar], [by, by], "-", color=col, lw=lw, zorder=8,
                solid_capstyle="butt")
    for col in ("white", INK):
        ax.text(bx + bar / 2, by + span * .013, "2 km", ha="center",
                va="bottom", fontsize=10.5, color=col, fontweight="bold",
                zorder=8 if col == "white" else 9)
    ax.text(.985, .975, "USDA NAIP · %s · %s m"
            % (newest.strftime("%d %B %Y"), use[0].properties.get("gsd")),
            transform=ax.transAxes, fontsize=10, color="white",
            fontweight="bold", va="top", ha="right", zorder=9)

    # legend, drawn as proxies so it sits on the imagery
    ax.plot([], [], "-", color=ORANGE, lw=3, label="focus field")
    ax.plot([], [], "-", color="white", lw=1.5,
            label="cohort, %d fields" % len(cm))
    leg = ax.legend(loc="lower right", frameon=True, fontsize=10.5,
                    facecolor="black", edgecolor="none", framealpha=.45)
    for txt in leg.get_texts():
        txt.set_color("white")

    # ---- inset: the state, county filled ----------------------------------
    # Above the radius circle, and opaque. The inset's default z-order let
    # the circle draw straight across the state outline; with a thin white
    # dashed line that was invisible, and with a black one it is a dash
    # running through Illinois.
    ins = ax.inset_axes([0.012, 0.615, 0.265, 0.375], zorder=12)
    ins.set_facecolor("white")
    ins.patch.set_alpha(1.0)
    cty[cty.STUSPS == STUSPS].boundary.plot(ax=ins, color="#cfd4da", lw=.55)
    hit.plot(ax=ins, color="#cfe0f5", edgecolor=BLUE, lw=1.4)
    st[st.STUSPS == STUSPS].boundary.plot(ax=ins, color=INK2, lw=1.2)
    ins.plot(lon, lat, "o", ms=7, mfc=ORANGE, mec="white", mew=1.4)
    ins.set_aspect(1 / np.cos(np.radians(lat)))
    ins.set_xticks([]); ins.set_yticks([])
    for sp in ins.spines.values():
        sp.set_edgecolor("#9aa0a6")
    # Label inside the inset on a white strip: as a title it sat above the
    # inset axes, which means on top of the aerial imagery, in dark text.
    ins.set_title("")
    ins.text(0.5, -0.09, "%s County, %s" % (COUNTY, STATE),
             transform=ins.transAxes, ha="center", va="top", fontsize=9.5,
             color=INK, fontweight="bold",
             bbox=dict(boxstyle="square,pad=0.28", facecolor="white",
                       edgecolor="#9aa0a6", linewidth=.8))

    if not a.bare:
        ax.set_title("A hyper-local benchmark: one field against its "
                     "neighborhood", color=INK, fontsize=13,
                     fontweight="bold", loc="left", pad=20)
        ax.text(0, 1.012, "%d qualifying cropland fields within %.1f km of "
                "the focus field, from the 2008 public CLU."
                % (len(cm), radius / 1000), transform=ax.transAxes,
                color=INK2, fontsize=10, va="bottom")

    out = fig_dir / "01_cohort_map.png"
    for attempt in range(6):
        try:
            fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
            break
        except OSError:
            if attempt == 5:
                raise
            time.sleep(0.6)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    main()
