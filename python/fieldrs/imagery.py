"""Find and load optical surface reflectance over a field.

Source: Microsoft Planetary Computer's STAC API. Two imagery sources, both free
and needing no account:

``sentinel2`` (the original)
    Sentinel-2 L2A at 10 m, cloud-masked with ESA's Scene Classification Layer.

``hls``
    NASA's Harmonized Landsat Sentinel-2 v2.0: Sentinel-2 (S30) and Landsat 8/9
    (L30) on one 30 m grid, with bandpass and BRDF adjustment so the two
    sensors read alike, cloud-masked with Fmask. Adding Landsat roughly halves
    the longest cloud gaps at crop transitions, which is what limits the
    confidence of the season dates. Coarser pixels are the price -- see
    HLS_EDGE_M. Planetary Computer holds HLS v2 from 2020 on.
 Imagery is read straight from cloud-optimised GeoTIFFs
over HTTP, so only the pixels covering the field are ever transferred.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field as dc_field
from datetime import date as Date
from typing import Iterable, Sequence

import geopandas as gpd
import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds, intersection
from shapely.geometry import shape

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

# How this client identifies itself to Planetary Computer.
#
# Sending nothing makes us anonymous traffic indistinguishable from a scraper,
# and anonymous traffic is what a service throttles first and contacts never.
# Identifying costs nothing. GDAL sends it on every COG range read, which is
# where nearly all the volume goes, and pystac_client sends it on every
# catalogue call.
#
# Unlike the R side, this is not set as a global: it rides in GDAL_ENV, which
# is scoped to the rasterio.Env blocks around our own reads, and in the headers
# of our own STAC client. A library that is going to be lifted into somebody
# else's platform should not be reaching into the host process at import to
# change its GDAL configuration. pc_identify() is there for callers who do want
# that, and nothing here needs it.
PC_CLIENT = "field-to-market-remote-sensing/1.0 (+https://fieldtomarket.org)"


def pc_identify() -> str:
    """Set the Planetary Computer user agent process-wide.

    Not needed for anything in this package -- our own reads and searches
    already carry it. Call it when other code in the same process reads
    Planetary Computer through GDAL and should identify itself too.
    """
    os.environ["GDAL_HTTP_USERAGENT"] = PC_CLIENT
    return PC_CLIENT


# Friendly name -> Sentinel-2 asset key on Planetary Computer.
S2_BANDS = {
    "coastal": "B01", "blue": "B02", "green": "B03", "red": "B04",
    "rededge1": "B05", "rededge2": "B06", "rededge3": "B07",
    "nir": "B08", "nir08": "B8A", "swir16": "B11", "swir22": "B12",
    "scl": "SCL",
}

# Native ground sample distance, metres. Picks the reference grid.
S2_RES = {
    "coastal": 60, "blue": 10, "green": 10, "red": 10,
    "rededge1": 20, "rededge2": 20, "rededge3": 20,
    "nir": 10, "nir08": 20, "swir16": 20, "swir22": 20, "scl": 20,
}

# --- HLS ---------------------------------------------------------------------
# Friendly name -> HLS asset key, per collection. In S30 the NIR band is B8A,
# not B08: B8A is the narrow NIR that HLS bandpass-adjusts to match Landsat's
# B05, so it is the one that makes the two sensors comparable. L30 has no red
# edge, so indices needing one cannot be computed from it.
HLS_BANDS = {
    "hls2-s30": {"coastal": "B01", "blue": "B02", "green": "B03", "red": "B04",
                 "rededge1": "B05", "rededge2": "B06", "rededge3": "B07",
                 "nir": "B8A", "nir08": "B8A", "swir16": "B11", "swir22": "B12",
                 "fmask": "Fmask"},
    "hls2-l30": {"coastal": "B01", "blue": "B02", "green": "B03", "red": "B04",
                 "nir": "B05", "nir08": "B05", "swir16": "B06", "swir22": "B07",
                 "fmask": "Fmask"},
}
HLS_SCALE = 0.0001
HLS_NODATA = -9999

# HLS keeps slightly negative surface reflectance (over snow, in shadow). Where
# red and NIR are both near zero, NDVI = (nir - red) / (nir + red) explodes:
# one February scene over the Iowa field had a field mean of 0.79 from a
# handful of such pixels against a 90th percentile of 0.44. A pixel with any
# band at or below zero is not a usable surface reading, so it is dropped.
HLS_MIN_REFLECTANCE = 0.0

# Fmask is bit-packed: 1 cloud, 2 adjacent to cloud/shadow, 3 cloud shadow,
# 4 snow/ice, 5 water, 6-7 aerosol level. Drop 1-4, the same things SCL drops.
# Water stays, as SCL keeps class 6. Aerosol is NOT masked: "high aerosol" is
# set on plenty of clear summer scenes, and masking it would empty the season.
FMASK_DROP_BITS = (1, 2, 3, 4)

# Edge pixels at 30 m straddle the boundary and mix in the neighbour -- a
# road, a treeline, the next field. Pixels are kept only if their centre sits
# this far inside the boundary, i.e. half a pixel, so each kept pixel lies
# essentially inside the field. Falls back to the whole boundary when that
# would leave fewer than HLS_MIN_PIXELS (a very small or narrow field).
HLS_EDGE_M = 15.0
HLS_MIN_PIXELS = 10

# Imagery source -> STAC collections searched.
SOURCES = {
    "sentinel2": ("sentinel-2-l2a",),
    "hls": ("hls2-s30", "hls2-l30"),
}
SOURCE_LABELS = {
    "sentinel2": "Sentinel-2 L2A, 10 m",
    "hls": "HLS v2 (Sentinel-2 + Landsat 8/9), 30 m",
}


def sensor_of(item) -> str:
    """Short sensor label for a STAC item: S2, HLS-S30 or HLS-L30."""
    return {"sentinel-2-l2a": "S2", "hls2-s30": "HLS-S30",
            "hls2-l30": "HLS-L30"}.get(getattr(item, "collection_id", None), "?")


# Scene Classification Layer classes worth keeping: 4 vegetation, 5 bare soil,
# 6 water, 7 unclassified. The rest are cloud, shadow, cirrus, snow or noise.
SCL_KEEP_DEFAULT = (4, 5, 6, 7)

# GDAL settings that matter a great deal for COG-over-HTTP throughput. Without
# DISABLE_READDIR_ON_OPEN, GDAL lists the whole container on every open.
GDAL_ENV = {
    "GDAL_HTTP_USERAGENT": PC_CLIENT,
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "1",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "10000000",
}


@dataclass
class Scene:
    """One catalogue entry, before any pixels are read."""
    item: object            # pystac.Item, kept unsigned
    date: Date
    cloud: float
    scene_id: str


@dataclass
class SceneData:
    """One scene's pixels, clipped to the field, as surface reflectance."""
    bands: dict[str, np.ndarray]
    date: Date
    scene_id: str
    cloud: float
    n_field: int            # pixels inside the boundary, regardless of cloud
    transform: object = None
    crs: object = None
    meta: dict = dc_field(default_factory=dict)

    @property
    def valid_fraction(self) -> float:
        """Share of *field* pixels that survived masking, 0-1.

        Measured against the boundary footprint, not the bounding box, so a
        completely clear scene reads 1.0 whatever shape the field is. The
        catalogue's cloud percentage covers a 110 km tile and says little about
        any one field.
        """
        if not self.bands or self.n_field == 0:
            return 0.0
        arr = next(iter(self.bands.values()))
        return min(1.0, float(np.isfinite(arr).sum()) / self.n_field)


# ---------------------------------------------------------------- search ---

# How often the catalogue is asked again before giving up, and how long to
# wait in between.
#
# Planetary Computer's STAC endpoint rate-limits, and when it does it answers
# with an HTML error page rather than JSON. Unguarded, one such reply killed a
# six-year soil armor run on the R side that had already read three years --
# the request that failed was the fourth in quick succession, which is exactly
# when a throttle fires. Python had the same exposure and no handler.
STAC_TRIES = 4
STAC_BACKOFF = (2, 6, 15)       # seconds before attempts 2, 3 and 4

_RETRY_AFTER = re.compile(r"retry-?after[^0-9]*([0-9]+)", re.I)


def _retry_after(exc: Exception) -> float | None:
    """Seconds the service asked us to wait, if it said.

    Their number beats our schedule: a service under load knows better than a
    hard-coded backoff, and ignoring the hint is how a polite retry turns into
    hammering. Read from the response header when the exception carries one,
    and otherwise off the message text, which is where pystac_client puts the
    body it could not parse.
    """
    resp = getattr(exc, "response", None)
    raw = None
    if resp is not None:
        try:
            raw = resp.headers.get("Retry-After")
        except Exception:
            raw = None
    if raw is None:
        m = _RETRY_AFTER.search(str(exc))
        raw = m.group(1) if m else None
    try:
        wait = float(raw)
    except (TypeError, ValueError):
        return None
    # A Retry-After in date form, or an implausible one, is not worth honoring
    # literally -- fall back to our own schedule rather than sleeping for hours.
    return wait if 0 < wait <= 120 else None


def _stac_client() -> pystac_client.Client:
    return pystac_client.Client.open(PC_STAC,
                                     headers={"User-Agent": PC_CLIENT})


def stac_search_retry(bbox, start: str, end: str, limit: int,
                      collections: Sequence[str] = ("sentinel-2-l2a",)) -> list:
    """Ask the STAC catalogue, retrying transient failures.

    The search is a read, so repeating it is safe, and extraction is cached per
    year, so even a final failure loses only the year in flight.
    """
    last = None
    for i in range(1, STAC_TRIES + 1):
        try:
            search = _stac_client().search(
                collections=list(collections),
                bbox=bbox,
                datetime=f"{start}/{end}",
                limit=limit,
            )
            # Paging happens here, not above, so the request that trips the
            # throttle is usually this one rather than the client open.
            return list(search.items())
        except Exception as exc:                     # noqa: BLE001
            last = exc
            if i == STAC_TRIES:
                break
            wait = _retry_after(exc) or STAC_BACKOFF[min(i, len(STAC_BACKOFF)) - 1]
            msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            print(f"  Catalogue request failed ({msg}). "
                  f"Retrying in {wait:g}s ({i + 1} of {STAC_TRIES})...",
                  flush=True)
            time.sleep(wait)

    msg = str(last).splitlines()[0] if str(last) else type(last).__name__
    raise RuntimeError(
        f"The imagery catalogue did not answer after {STAC_TRIES} attempts.\n"
        f"  Last error: {msg}\n"
        "  A reply in HTML rather than data means Planetary Computer "
        "rate-limited the request or is down. It is not a problem with this "
        "field.\n"
        "  Everything already read is cached, so running again resumes rather "
        "than starting over."
    ) from last


def search_scenes(aoi: gpd.GeoDataFrame, start: str, end: str,
                  max_cloud: float = 70, limit: int = 500,
                  source: str = "sentinel2") -> list[Scene]:
    """Search scenes covering a field, from one imagery source (see SOURCES).

    ``max_cloud`` is scene-level cloud over the whole tile, not over the field.
    A "60% cloudy" scene can be perfectly clear above one field, so keep this
    loose and filter later on :attr:`SceneData.valid_fraction`.
    """
    from .aoi import field_bounds

    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    bbox = field_bounds(aoi)
    items = stac_search_retry(bbox, start, end, min(limit, 500), SOURCES[source])
    if not items:
        raise RuntimeError(
            f"No {SOURCE_LABELS[source]} scenes found for that area and date range. "
            + ("Sentinel-2 starts 2015-06; coverage is best from 2017." if source == "sentinel2"
               else "HLS v2 on Planetary Computer starts 2020-01.")
        )

    scenes: list[Scene] = []
    for it in items:
        cloud = it.properties.get("eo:cloud_cover")
        cloud = float("nan") if cloud is None else float(cloud)
        if not np.isnan(cloud) and cloud > max_cloud:
            continue
        scenes.append(Scene(it, it.datetime.date(), cloud, it.id))

    if not scenes:
        raise RuntimeError(
            f"Found {len(items)} scenes but none under {max_cloud:.0f}% cloud. "
            "Raise max_cloud."
        )
    scenes.sort(key=lambda s: (s.date, s.scene_id))
    return scenes


def scene_groups(scenes: Sequence[Scene], aoi: gpd.GeoDataFrame) -> list[list[Scene]]:
    """Group same-date scenes into one ranked candidate list per date.

    Sentinel-2 tiles overlap and adjacent orbits revisit on the same day, so one
    date can appear several times. A field near a tile corner is the bad case:
    one 15 ha field returned 4,682 scenes for 664 distinct dates. Reading them
    all and deduplicating afterwards fetched four times more imagery than was
    kept, so the choice is made up front from metadata.

    Candidates are RANKED rather than reduced to one, because metadata alone
    cannot tell you whether a tile actually has pixels over the field. A STAC
    footprint is the whole 110 km tile, but a granule can be only partly filled:
    on 2021-07-20 all four tiles reported ``covers = True`` and the lowest-cloud
    one turned out to be 99% nodata over the field. Picking that one and
    stopping lost the date. The caller walks the list until a scene actually
    yields data, so the usual case still costs one read.

    Order: footprint covering the field first, then lowest cloud.
    """
    if not scenes:
        return []
    poly = aoi.to_crs(4326).geometry.union_all()

    def rank(s: Scene) -> tuple[int, float]:
        try:
            covers = shape(s.item.geometry).covers(poly)
        except Exception:
            covers = False
        cloud = 999.0 if np.isnan(s.cloud) else s.cloud
        return (0 if covers else 1, cloud)

    by_date: dict[Date, list[Scene]] = {}
    for s in scenes:
        by_date.setdefault(s.date, []).append(s)
    return [sorted(by_date[d], key=rank) for d in sorted(by_date)]


def dedupe_scenes(scenes: Sequence[Scene], aoi: gpd.GeoDataFrame) -> list[Scene]:
    """Best single scene per date. Kept for callers that want one per date."""
    return [g[0] for g in scene_groups(scenes, aoi)]


# ------------------------------------------------------------------ read ---

def _sign(href: str) -> str:
    """Sign a Planetary Computer asset URL.

    Signed at read time rather than at search time. Signatures expire after
    about an hour, and signing per read (the token is cached per container)
    removes a whole class of "it failed halfway through" bugs.
    """
    return planetary_computer.sign(href)


def _boa_offset(item) -> float:
    """Bottom-of-atmosphere additive offset for the scene's processing baseline.

    From baseline 04.00 (January 2022) ESA added a -1000 offset to stored
    values. Skipping it shifts NDVI by a few hundredths and puts a step change
    in early 2022 that looks like a real trend.
    """
    try:
        return -1000.0 if float(item.properties["s2:processing_baseline"]) >= 4 else 0.0
    except (KeyError, TypeError, ValueError):
        return 0.0


def read_scene(scene: Scene, aoi: gpd.GeoDataFrame,
               bands: Iterable[str] = ("blue", "green", "red", "nir"),
               mask_clouds: bool = True, clip: bool = True,
               buffer_m: float = 100,
               scl_keep: Sequence[int] = SCL_KEEP_DEFAULT) -> SceneData:
    """Load one scene, clipped to the field, as reflectance (0-1).

    Masked pixels come back as NaN. HLS scenes are read by :func:`_read_hls`;
    ``scl_keep`` applies to Sentinel-2 only.
    """
    if getattr(scene.item, "collection_id", None) in HLS_BANDS:
        return _read_hls(scene, aoi, bands, mask_clouds, clip, buffer_m)
    bands = list(bands)
    unknown = [b for b in bands if b not in S2_BANDS]
    if unknown:
        raise KeyError(
            f"Unknown band(s): {', '.join(unknown)}. "
            f"Available: {', '.join(S2_BANDS)}"
        )

    needed = list(dict.fromkeys(bands + (["scl"] if mask_clouds else [])))
    ref_band = min(needed, key=lambda b: S2_RES[b])
    item = scene.item

    with rasterio.Env(**GDAL_ENV):
        # The finest-resolution band defines the output grid.
        with rasterio.open(_sign(item.assets[S2_BANDS[ref_band]].href)) as src:
            crs = src.crs
            geom = aoi.to_crs(crs).geometry.union_all()
            win = from_bounds(*geom.buffer(buffer_m).bounds, transform=src.transform)
            win = win.round_offsets().round_lengths()
            win = intersection(win, Window(0, 0, src.width, src.height))
            if win.width < 1 or win.height < 1:
                raise ValueError("Field falls outside this scene's footprint.")
            out_shape = (int(win.height), int(win.width))
            transform = src.window_transform(win)
            bounds = rasterio.windows.bounds(win, src.transform)
            raw = {ref_band: src.read(1, window=win).astype("float32")}

        for b in needed:
            if b == ref_band:
                continue
            href = _sign(item.assets[S2_BANDS[b]].href)
            with rasterio.open(href) as src:
                w = from_bounds(*bounds, transform=src.transform)
                w = w.round_offsets().round_lengths()
                w = intersection(w, Window(0, 0, src.width, src.height))
                # SCL is categorical: nearest neighbour only, never interpolate
                # class codes onto the 10 m grid.
                resamp = Resampling.nearest if b == "scl" else Resampling.bilinear
                raw[b] = src.read(1, window=w, out_shape=out_shape,
                                  resampling=resamp).astype("float32")

    offset = _boa_offset(item)
    out: dict[str, np.ndarray] = {}
    for b in bands:
        out[b] = (raw[b] + offset) / 10000.0

    keep = np.ones(out_shape, dtype=bool)
    if mask_clouds:
        keep &= np.isin(raw["scl"].astype("int16"), np.asarray(scl_keep))

    if clip:
        footprint = geometry_mask([geom], out_shape=out_shape, transform=transform,
                                  invert=True)
        n_field = int(footprint.sum())
        keep &= footprint
    else:
        n_field = int(out_shape[0] * out_shape[1])

    for b in out:
        out[b] = np.where(keep, out[b], np.nan).astype("float32")
    if "scl" in bands:
        # SCL is returned clipped to the boundary but NOT cloud-masked -- it is
        # the thing that decides the cloud mask, so masking it by itself would
        # be circular. Matches the R pipeline's behaviour.
        inside = keep if not mask_clouds else (
            geometry_mask([geom], out_shape=out_shape, transform=transform, invert=True)
            if clip else np.ones(out_shape, dtype=bool)
        )
        out["scl"] = np.where(inside, raw["scl"], np.nan).astype("float32")

    return SceneData(bands=out, date=scene.date, scene_id=scene.scene_id,
                     cloud=scene.cloud, n_field=n_field,
                     transform=transform, crs=crs)


def _read_hls(scene: Scene, aoi: gpd.GeoDataFrame, bands: Iterable[str],
              mask_clouds: bool, clip: bool, buffer_m: float) -> SceneData:
    """One HLS (S30 or L30) scene, clipped to the field, as reflectance (0-1).

    All HLS bands share one 30 m grid, so every band reads the same window and
    nothing is resampled. Clipping keeps pixels whose centre is HLS_EDGE_M
    inside the boundary -- see there.
    """
    item = scene.item
    amap = HLS_BANDS[item.collection_id]
    bands = list(bands)
    unknown = [b for b in bands if b not in amap or b == "fmask"]
    if unknown:
        raise KeyError(
            f"Band(s) {', '.join(unknown)} not in {item.collection_id}. "
            f"Available: {', '.join(k for k in amap if k != 'fmask')}"
        )
    needed = list(dict.fromkeys(bands + (["fmask"] if mask_clouds else [])))

    raw: dict[str, np.ndarray] = {}
    with rasterio.Env(**GDAL_ENV):
        for i, b in enumerate(needed):
            with rasterio.open(_sign(item.assets[amap[b]].href)) as src:
                if i == 0:
                    crs = src.crs
                    geom = aoi.to_crs(crs).geometry.union_all()
                    win = from_bounds(*geom.buffer(buffer_m).bounds, transform=src.transform)
                    win = win.round_offsets().round_lengths()
                    win = intersection(win, Window(0, 0, src.width, src.height))
                    if win.width < 1 or win.height < 1:
                        raise ValueError("Field falls outside this scene's footprint.")
                    out_shape = (int(win.height), int(win.width))
                    transform = src.window_transform(win)
                raw[b] = src.read(1, window=win)

    keep = np.ones(out_shape, dtype=bool)
    out: dict[str, np.ndarray] = {}
    for b in bands:
        r = raw[b]
        keep &= (r != HLS_NODATA) & (r * HLS_SCALE > HLS_MIN_REFLECTANCE)
        out[b] = r.astype("float32") * HLS_SCALE
    if mask_clouds:
        fm = raw["fmask"].astype("uint8")
        bad = np.zeros(out_shape, dtype=bool)
        for bit in FMASK_DROP_BITS:
            bad |= (fm >> bit) & 1 == 1
        keep &= (fm != 255) & ~bad

    if clip:
        inner = geom.buffer(-HLS_EDGE_M)
        footprint = None
        if not inner.is_empty:
            footprint = geometry_mask([inner], out_shape=out_shape, transform=transform,
                                      invert=True)
            if footprint.sum() < HLS_MIN_PIXELS:
                footprint = None
        if footprint is None:
            footprint = geometry_mask([geom], out_shape=out_shape, transform=transform,
                                      invert=True)
        n_field = int(footprint.sum())
        keep &= footprint
    else:
        n_field = int(out_shape[0] * out_shape[1])

    for b in out:
        out[b] = np.where(keep, out[b], np.nan).astype("float32")
    return SceneData(bands=out, date=scene.date, scene_id=scene.scene_id,
                     cloud=scene.cloud, n_field=n_field,
                     transform=transform, crs=crs,
                     meta={"sensor": sensor_of(item)})
