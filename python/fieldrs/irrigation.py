"""Irrigated or not, from USGS irrigated-agriculture maps.

WHAT THE MAPS ARE
Binary CONUS rasters, 1 = irrigated agriculture, in the CDL's own projection
(CONUS Albers, EPSG:5070): 2002 and 2007 at 50 m, 2012 and 2017 at 30 m. They
are read in place from a local folder, one small window per field, exactly as
the local CDL is -- see cdl_local.py.

THE LIMITS
At field level single maps are not reliable. Across the 17 library fields the
Central Valley field reads 98-100% irrigated in 2002-2012 and 9.6% in 2017; a
Kansas field named rainfed reads ~60% in 2007 and 2012 only; Georgia fields
flip between maps. So every year also carries ``irrigated_maps`` -- in how
many of the maps the field is irrigated -- and one map disagreeing with the
rest is visible rather than silently believed.

There is a map every five years and none after 2017. A CDL year is given the
nearest map at or before it, and says which one, so 2020-2025 read "as mapped
in 2017". A field irrigated since then, or taken out of irrigation, will not
show. Before 2002 there is nothing to go on.

Point ``IRRIGATION_DIR`` at the folder; files are found by the year in their
name (``irri17_30lzw.tif`` -> 2017).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds

from .cache import cache_get, cache_key, cache_put

IRRIGATION_DIR_DEFAULT = "/mnt/cephfs/csip-data/csip-lamps/GIS_analysis_data"
_NAME = re.compile(r"^irri(\d{2})_\d+\w*\.tif$", re.I)

# Share of the field (%) mapped irrigated for each label.
IRRIGATED_PCT = 50.0
PARTLY_PCT = 10.0


def irrigation_dir() -> Path:
    return Path(os.environ.get("IRRIGATION_DIR", IRRIGATION_DIR_DEFAULT))


def map_files() -> dict[int, Path]:
    """Map year -> raster, for every irrigation map in the folder."""
    d = irrigation_dir()
    if not d.is_dir():
        return {}
    out = {}
    for p in d.iterdir():
        m = _NAME.match(p.name)
        if m:
            out[2000 + int(m.group(1))] = p
    return dict(sorted(out.items()))


def _irrigated_pct(aoi: gpd.GeoDataFrame, path: Path) -> tuple[float, int]:
    """Share (%) of the field's pixels mapped irrigated, and the pixel count."""
    with rasterio.open(path) as src:
        geom = aoi.to_crs(src.crs).geometry.union_all()
        b = geom.bounds
        r = src.res[0]
        win = from_bounds(b[0] - r, b[1] - r, b[2] + r, b[3] + r, transform=src.transform)
        win = win.round_offsets().round_lengths()
        arr = src.read(1, window=win, boundless=True, fill_value=0)
        inside = geometry_mask([geom], out_shape=arr.shape,
                               transform=src.window_transform(win), invert=True)
        if inside.sum() == 0:
            # Field smaller than a pixel: take the pixel under its centre.
            inside = geometry_mask([geom.centroid.buffer(r / 2)], out_shape=arr.shape,
                                   transform=src.window_transform(win), invert=True)
    n = int(inside.sum())
    return (100.0 * float((arr[inside] == 1).sum()) / n if n else np.nan), n


def irrigation_history(aoi: gpd.GeoDataFrame) -> pd.DataFrame | None:
    """Irrigated share of the field in every available map year (cached)."""
    files = map_files()
    if not files:
        return None
    key = cache_key(aoi, "irrigation_v1", sorted(files))
    hit = cache_get(key, "irrig")
    if hit is not None:
        return hit
    rows = []
    for y, p in files.items():
        pct, n = _irrigated_pct(aoi, p)
        rows.append({"map_year": y, "irrigated_pct": round(pct, 1),
                     "irrigated": label(pct), "n_pixels": n,
                     "resolution_m": 50 if y < 2012 else 30})
    return cache_put(key, pd.DataFrame(rows), "irrig")


def label(pct: float) -> str | None:
    if pct is None or np.isnan(pct):
        return None
    return ("irrigated" if pct >= IRRIGATED_PCT else
            "partly irrigated" if pct >= PARTLY_PCT else "not irrigated")


def add_to_history(history: pd.DataFrame | None,
                   irr: pd.DataFrame | None) -> pd.DataFrame | None:
    """Irrigation columns on the CDL rotation table, one map per CDL year.

    Each year gets the nearest map at or before it: ``irrigated``,
    ``irrigated_pct`` and ``irrigation_map`` (the map year it came from), plus
    ``irrigated_maps``, e.g. "3 of 4": how many maps, of all years, show the
    field irrigated -- the check on any one map.
    """
    if history is None or irr is None or not len(irr):
        return history
    out = history.copy()
    years = irr["map_year"].to_numpy()
    by_year = irr.set_index("map_year")
    lab, pct, src = [], [], []
    for y in out["year"]:
        prior = years[years <= int(y)]
        if not len(prior):
            lab.append(None); pct.append(None); src.append(None)
            continue
        m = int(prior.max())
        lab.append(by_year.at[m, "irrigated"])
        pct.append(by_year.at[m, "irrigated_pct"])
        src.append(m)
    out["irrigated"] = lab
    out["irrigated_pct"] = pct
    out["irrigation_map"] = pd.array(src, dtype="Int64")
    n_irr = int((irr["irrigated_pct"] >= IRRIGATED_PCT).sum())
    out["irrigated_maps"] = f"{n_irr} of {len(irr)}"
    return out
