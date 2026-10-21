#!/usr/bin/env python3
"""Where the alfalfa field is: a locator map and the boundary on NAIP imagery.

    python project-level-tests/figure_alfalfa_location.py [--bare]

Writes 07_location.png. Kept out of figures_alfalfa.py because this one needs
the network -- NAIP from the Planetary Computer, county outlines from the
Census -- and the other six run entirely from the report pack.

Two panels:

  left    New Mexico, its 33 counties faint, San Juan filled, the field
          marked. The county is read from the Census polygon that contains
          the centroid, not asserted.
  right   USDA NAIP aerial imagery at 0.6 m, May 2022, with the boundary
          drawn over it.

NAIP rather than a web basemap: it is public-domain USDA imagery, it is
already in the catalog this pipeline reads, and at 0.6 m it resolves the
crop rows. The Sentinel-2 pixels every number in this deck comes from are
10 m -- about 17 NAIP pixels across -- so the imagery here is far sharper
than the data, and the panel says so.

The boundary is an axis-aligned rectangle with field_id "drawn": it was
drawn by hand in the Shiny app, not digitized from a field record. On the
imagery that is obvious, and the caption says it outright rather than
letting the slide imply a surveyed outline.
"""
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd  # noqa: E402
import planetary_computer  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402
from shapely.geometry import Point, shape  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJ = HERE / "alfalfa-nm"
BARE = "--bare" in sys.argv
FIG = PROJ / "figures" / "deck" if BARE else PROJ / "figures"
FIG.mkdir(parents=True, exist_ok=True)

CENSUS = ("https://www2.census.gov/geo/tiger/GENZ2023/shp/"
          "cb_2023_us_%s_20m.zip")
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
BLUE, ORANGE = "#165bac", "#F46C09"
GRID = "#e6e6e6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 11,
    "text.color": INK, "axes.edgecolor": GRID,
})

# ------------------------------------------------------------ boundary -----
gj = json.loads((PROJ / "boundaries" / "field.geojson").read_text())
feat = gj["features"][0]
poly = shape(feat["geometry"])
fld = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
lon, lat = poly.centroid.x, poly.centroid.y
area_ha = feat["properties"]["area_ha"]
xs = sorted({round(c[0], 9) for c in feat["geometry"]["coordinates"][0]})
ys = sorted({round(c[1], 9) for c in feat["geometry"]["coordinates"][0]})
is_box = len(xs) == 2 and len(ys) == 2
print("boundary: %.5f, %.5f  %.1f ha  %s"
      % (lon, lat, area_ha,
         "axis-aligned rectangle (drawn by hand)" if is_box else "polygon"))

# ------------------------------------------------------------- county ------
print("reading Census boundaries ...")
cty = gpd.read_file("zip+" + CENSUS % "county")
st = gpd.read_file("zip+" + CENSUS % "state")
hit = cty[cty.contains(Point(lon, lat))]
if len(hit) != 1:
    sys.exit("expected exactly one county to contain the field, got %d" % len(hit))
COUNTY = hit.NAME.iloc[0]
STATE = hit.STATE_NAME.iloc[0]
STUSPS = hit.STUSPS.iloc[0]
print("located in %s County, %s" % (COUNTY, STATE))
state_poly = st[st.STUSPS == STUSPS]
state_cty = cty[cty.STUSPS == STUSPS]

# --------------------------------------------------------------- NAIP ------
print("searching NAIP ...")
cat = pystac_client.Client.open(PC_STAC)
items = sorted(cat.search(collections=["naip"], bbox=list(poly.bounds)).items(),
               key=lambda i: i.datetime)
if not items:
    sys.exit("no NAIP coverage for this field")
item = items[-1]
flown = item.datetime.date()
gsd = item.properties.get("gsd")
print("using %s  (%s, %s m)" % (item.id, flown, gsd))

# Pad the read so the field sits in its surroundings rather than filling the
# frame edge to edge: a boundary with nothing around it shows nothing about
# whether the box was drawn in the right place.
PAD = 1.35
with rasterio.open(planetary_computer.sign(item.assets["image"].href)) as src:
    fld_m = fld.to_crs(src.crs)
    x0, y0, x1, y1 = fld_m.total_bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = max(x1 - x0, y1 - y0) / 2 * PAD
    bounds = (cx - half, cy - half, cx + half, cy + half)
    win = from_bounds(*bounds, transform=src.transform)
    for attempt in range(4):
        try:
            rgb = src.read((1, 2, 3), window=win,
                           out_shape=(3, 1500, 1500), boundless=True,
                           fill_value=0)
            break
        except Exception as e:                       # transient COG read
            if attempt == 3:
                raise
            print("   read failed (%s), retrying" % type(e).__name__)
            time.sleep(3)
    crs_m = src.crs

img = np.transpose(rgb, (1, 2, 0)).astype(float) / 255.0
extent = (bounds[0], bounds[2], bounds[1], bounds[3])

# -------------------------------------------------------------- render -----
# Shorter for the deck, where the panel is height-constrained and
# the slide supplies its own heading.
fig = plt.figure(figsize=(13.4, 4.6) if BARE else (13.4, 5.5))
gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.62], wspace=.06)

# -- locator ----------------------------------------------------------------
axl = fig.add_subplot(gs[0, 0])
state_cty.boundary.plot(ax=axl, color="#cfd4da", linewidth=.7, zorder=2)
hit.plot(ax=axl, color="#cfe0f5", edgecolor=BLUE, linewidth=1.6, zorder=3)
state_poly.boundary.plot(ax=axl, color=INK2, linewidth=1.5, zorder=4)
axl.plot(lon, lat, "o", ms=11, mfc=ORANGE, mec="white", mew=2, zorder=6)
axl.annotate("the field", xy=(lon, lat), xytext=(lon + 1.15, lat + 0.55),
             fontsize=12, fontweight="bold", color=ORANGE, zorder=7,
             arrowprops=dict(arrowstyle="-", color=ORANGE, lw=1.6))
cen = hit.geometry.iloc[0].centroid
axl.text(cen.x - 0.15, cen.y - 0.42, "%s County" % COUNTY, fontsize=11.5,
         fontweight="bold", color=BLUE, ha="center", zorder=7)
axl.text(.5, .055, "  ".join(STATE.upper()), transform=axl.transAxes,
         fontsize=12, fontweight="bold", color=INK2, ha="center")
axl.set_aspect(1 / np.cos(np.radians(lat)))
axl.set_axis_off()
axl.margins(.03)

# -- imagery ----------------------------------------------------------------
axr = fig.add_subplot(gs[0, 1])
axr.imshow(img, extent=extent, origin="upper", interpolation="bilinear")
fld_m.boundary.plot(ax=axr, color=ORANGE, linewidth=2.6, zorder=5)
axr.set_xlim(extent[0], extent[1])
axr.set_ylim(extent[2], extent[3])
axr.set_xticks([]); axr.set_yticks([])
for sp in axr.spines.values():
    sp.set_edgecolor("#b9bcc0")

# scale bar, in metres because NAIP is projected
span = extent[1] - extent[0]
bar = 200.0 if span > 700 else 100.0
bx = extent[0] + span * .055
by = extent[2] + span * .055
axr.plot([bx, bx + bar], [by, by], "-", color="white", lw=4.5, zorder=7,
         solid_capstyle="butt")
axr.plot([bx, bx + bar], [by, by], "-", color=INK, lw=2.0, zorder=8,
         solid_capstyle="butt")
axr.text(bx + bar / 2, by + span * .018, "%d m" % bar, ha="center",
         va="bottom", fontsize=10, color="white", fontweight="bold", zorder=9)
axr.text(bx + bar / 2, by + span * .018, "%d m" % bar, ha="center",
         va="bottom", fontsize=10, color=INK, fontweight="bold", zorder=10)

# One Sentinel-2 pixel, drawn to scale. The whole deck is built from 10 m
# pixels and this imagery is 0.6 m, so without this square the picture
# flatters the data by about seventeen times. Placed on the uniform crop
# left of centre, where a small white marker actually reads -- at the
# bottom-right corner, over the pivot edge and the scale bar, it was
# illegible once the figure was scaled onto a slide.
px = 10.0
pxx = extent[0] + span * .085
pxy = extent[2] + span * .50
for col, lw, z in (("white", 3.4, 7), (INK, 1.4, 8)):
    axr.add_patch(mpatches.Rectangle((pxx, pxy), px, px, facecolor="none",
                                     edgecolor=col, lw=lw, zorder=z))
for col, lw, z in (("white", 2.6, 8), (INK, 1.0, 9)):
    axr.annotate("one Sentinel-2 pixel\n10 m, the data in this deck",
                 xy=(pxx + px / 2, pxy + px), xytext=(pxx - span * .015,
                 pxy + span * .145), fontsize=10.5, color=col,
                 fontweight="bold", ha="left", va="bottom", zorder=z,
                 arrowprops=dict(arrowstyle="-", color=col, lw=lw))

axr.text(.015, .975, "USDA NAIP  ·  %s  ·  %s m"
         % (flown.strftime("%B %Y"), gsd), transform=axr.transAxes,
         fontsize=10, color="white", fontweight="bold", va="top", zorder=9)

if not BARE:
    fig.suptitle("Where the field is", x=.055, ha="left", y=1.02,
                 fontsize=13, fontweight="bold", color=INK)
    fig.text(.055, .965, "%.0f acres near Farmington, in the irrigated San "
             "Juan valley of northwestern %s." % (area_ha * 2.47105, STATE),
             fontsize=10, color=INK2, ha="left", va="top")

for attempt in range(6):
    try:
        fig.savefig(FIG / "07_location.png", dpi=170, bbox_inches="tight",
                    facecolor="white")
        break
    except OSError:
        if attempt == 5:
            raise
        time.sleep(0.6)
plt.close(fig)
print("wrote", FIG / "07_location.png")

(PROJ / "location.json").write_text(json.dumps({
    "lon": round(lon, 5), "lat": round(lat, 5),
    "county": COUNTY, "state": STATE,
    "acres": round(area_ha * 2.47105, 1), "hectares": round(area_ha, 1),
    "boundary_is_drawn_rectangle": bool(is_box),
    "naip_item": item.id, "naip_flown": str(flown), "naip_gsd_m": gsd,
}, indent=2) + "\n", encoding="utf-8")
print("wrote location.json")
