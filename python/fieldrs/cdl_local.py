"""USDA CDL read from a local bulk copy instead of the CropScape API.

WHY THIS EXISTS
CropScape is a public web service and behaves like one: our 347-field-year
validation run took 52 minutes and was one request away from failing at any
point. It also serves an incomplete TLS chain (see ``cropland._session``). A
published CDL year never changes, so paying for it once per machine and reading
a file thereafter is strictly better.

WHAT IT DOES NOT FIX
Accuracy. Measured against the polygon's own geometric area on those same 347
field-years, CropScape's pixel counts were already faithful -- mean +0.06%,
median +0.05%. The residual error sits in fields under 10 ha and is 30 m
pixel-edge quantisation, which reading the same grid locally cannot remove.
Go local for reliability and speed, not for better numbers.

THE STORE
Lives outside the repository so a multi-gigabyte download can never be
committed, and so every project on the machine shares one copy. Years are
looked for in ``national/`` first and ``tif/`` second, because a store built by
an earlier project may already be on the machine using either name:

    ~/geodata/cdl/national/   extracted national GeoTIFFs, one per year
    ~/geodata/cdl/tif/        same, alternative name
    ~/geodata/cdl/raw/        the published zips, as downloaded
    ~/geodata/cdl/tmp/        staging; anything here is incomplete

A flat directory of ``NASS_<year>.tif`` mosaics, the layout of the shared
CSIP copy, is read too -- point ``CDL_DIR`` straight at it:

    /mnt/cephfs/csip-data/csip-lamps/CropScape_CDL/NASS_2024.tif

``NASS_<year>_10m.tif`` files in that directory are a different (10 m) product
on a different grid and are skipped.

Override the root with ``CDL_DIR``. Coverage is CONUS only, matching the
published national rasters; Alaska and Hawaii ship separately and are not
handled here.

The ``.ovr`` pyramid files some years ship are display overviews. Nothing here
reads them and they can be deleted to reclaim several GB per year.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds

CDL_CRS = 5070          # CONUS Albers, the CDL's native projection
CDL_URL = ("https://www.nass.usda.gov/Research_and_Science/Cropland/Release/"
           "datasets/{year}_30m_cdls.zip")

# The publisher is not consistent between releases: some years ship the GeoTIFF
# at the archive root, some inside a folder, and the stem is not always
# "<year>_30m_cdls". Resolve by globbing rather than by assuming a name.
TIF_GLOB = "*.tif"


def cdl_root() -> Path:
    """Where the local store lives. ``CDL_DIR`` overrides."""
    return Path(os.environ.get("CDL_DIR", Path.home() / "geodata" / "cdl"))


# Subdirectories that may hold the extracted national rasters, in priority
# order. Checking both means a store an earlier project already built is picked
# up as it stands, rather than duplicated alongside at several GB per year.
TIF_DIRS = ("national", "tif")

# Flat NASS_<year>.tif files directly under the root. The pattern is anchored at
# both ends so NASS_<year>_10m.tif, a 10 m product on another grid, never matches.
NASS_RE = re.compile(r"^NASS_(\d{4})\.tif$", re.I)


def _year_of(p: Path) -> int | None:
    """Year a candidate GeoTIFF holds, or None if it is not a 30 m national CDL."""
    if p.name.lower().endswith(".ovr.tif"):
        return None
    m = NASS_RE.match(p.name)
    if m:
        return int(m.group(1))
    stem = p.stem[:4]
    return int(stem) if stem.isdigit() else None


def year_tif(year: int) -> Path | None:
    """The extracted national GeoTIFF for one year, or None if absent."""
    for sub in TIF_DIRS:
        hits = sorted(p for p in (cdl_root() / sub).glob(f"{year}{TIF_GLOB}")
                      if not p.name.endswith(".ovr.tif"))
        if hits:
            return hits[0]
    flat = cdl_root() / f"NASS_{year}.tif"
    return flat if flat.exists() else None


def readable(path: Path | None) -> bool:
    """A file that exists is not necessarily a file that opens.

    A half-written or truncated GeoTIFF passes ``exists()`` and then fails three
    steps into an extraction, where the error says nothing useful. Check here
    instead.
    """
    if path is None or not path.exists():
        return False
    try:
        with rasterio.open(path) as src:
            if not (src.height > 0 and src.width > 0):
                return False
            # Dimensions come from the header, which is written early, so a
            # truncated file reports a plausible size and fails only when the
            # last strips are read. Touch the far corner to find out now
            # rather than part-way through an extraction run.
            n = min(256, src.height, src.width)
            src.read(1, window=Window(src.width - n, src.height - n, n, n))
            return True
    except Exception:                                     # noqa: BLE001
        return False


def available_years() -> list[int]:
    """Years present in the store and actually openable."""
    return list(_available_years(str(cdl_root())))


@lru_cache(maxsize=None)
def _available_years(root: str) -> tuple[int, ...]:
    # Memoised per root: use_local() asks on every get_cdl() call, and
    # readable() touches the far corner of each national raster -- some thirty
    # multi-GB files on the network share.
    out = []
    for d in [Path(root) / sub for sub in TIF_DIRS] + [Path(root)]:
        if not d.is_dir():
            continue
        for p in sorted(d.glob(TIF_GLOB)):
            y = _year_of(p)
            if y is not None and y not in out and readable(p):
                out.append(y)
    return tuple(sorted(out))


def clips_dir() -> Path:
    """Pre-clipped CDL, one small GeoTIFF per field-year. ``CDL_CLIPS`` overrides.

    The R app ships these so the deployed demo needs no national raster: 88
    clips for the eleven-field library come to 1.4 MB against ~25 GB. Generated
    by ``r/make_cdl_clips.R``. Python reads them too so the two implementations
    resolve CDL the same way.
    """
    env = os.environ.get("CDL_CLIPS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "r" / "cdl_clips"


def _clip_path(aoi: gpd.GeoDataFrame, year: int) -> Path | None:
    from .cache import cache_key

    p = clips_dir() / f"{cache_key(aoi, 'cdlclip')}_{year}.tif"
    return p if p.exists() else None


def get_cdl_local(aoi: gpd.GeoDataFrame, year: int,
                  clip: bool = True) -> tuple[np.ndarray, object, object]:
    """One year's CDL clipped to the field, read from the local store.

    Signature and return match :func:`cropland.get_cdl` so the two are
    interchangeable, including the float32 array with NaN outside the polygon.

    Reads only the window covering the field, so cost is set by field size
    rather than by the 1.9 GB national raster behind it.
    """
    # A pre-made clip answers without the national raster being present at all.
    cp = _clip_path(aoi, year)
    if cp is not None:
        with rasterio.open(cp) as src:
            return (src.read(1).astype("float32"), src.transform,
                    src.crs or rasterio.crs.CRS.from_epsg(CDL_CRS))

    path = year_tif(year)
    if not readable(path):
        raise FileNotFoundError(
            f"No usable local CDL for {year} in {cdl_root()}. "
            f"Run `python download_cdl.py --years {year}` first, or unset "
            f"FIELDRS_CDL_LOCAL to fall back to the CropScape API."
        )

    with rasterio.open(path) as src:
        # Some published years carry no CRS tag at all. Untagged, the reprojected
        # geometry lands nowhere near the raster and the read comes back empty
        # rather than failing, so assert the known projection instead.
        crs = src.crs or rasterio.crs.CRS.from_epsg(CDL_CRS)
        geom = aoi.to_crs(crs).geometry.union_all()

        # A one-pixel margin so the window cannot exclude a boundary pixel whose
        # centre is inside the polygon.
        b = geom.bounds
        win = from_bounds(b[0] - 30, b[1] - 30, b[2] + 30, b[3] + 30,
                          transform=src.transform)
        arr = src.read(1, window=win).astype("float32")
        transform = src.window_transform(win)

    if arr.size == 0:
        raise ValueError(
            f"The field does not overlap the {year} CDL raster. CONUS only -- "
            "Alaska and Hawaii ship as separate products."
        )

    if clip:
        inside = geometry_mask([geom], out_shape=arr.shape, transform=transform,
                               invert=True)
        arr = np.where(inside, arr, np.nan)
    return arr, transform, crs


def use_local() -> bool:
    """Whether the pipeline should prefer the local store.

    On by default once any year is present, so the reliable path is the one you
    get without asking. ``FIELDRS_CDL_LOCAL=0`` forces the API back.
    """
    flag = os.environ.get("FIELDRS_CDL_LOCAL")
    if flag is not None:
        return flag not in ("0", "false", "False", "")
    return bool(available_years()) or clips_dir().is_dir()
