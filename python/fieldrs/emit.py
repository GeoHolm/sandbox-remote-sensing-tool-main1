"""Crop residue snapshots from NASA EMIT hyperspectral scenes: the Cellulose
Absorption Index (CAI).

PROTOTYPE. Not calibrated against measured residue cover.

WHY A SECOND SENSOR
CAI (Daughtry 2001) reads the lignocellulose absorption near 2100 nm that dry
plant material has and soil does not: CAI = 100 x (0.5 (R2031 + R2211) - R2101).
It needs three narrow bands inside that feature. Sentinel-2, Landsat and HLS
have one broad band there, so the rest of this package uses broadband stand-ins
(NDTI, the Dead Fuel Index in the armor unmixing). EMIT, an imaging spectrometer
on the International Space Station, has 285 bands at ~7.4 nm, so CAI can be
computed as defined.

WHAT IT CAN AND CANNOT DO
EMIT is not a time series. The ISS orbit visits a field irregularly -- a
handful of scenes a year at mid-latitudes, many of them cloudy -- at 60 m, so a
small field is a few dozen pixels. Each clear scene is a snapshot. Read it
against the season it falls in: CAI is a residue reading only on soil that is
not green (NDVI below CAI_GREEN_NDVI); green canopy and wet soil both pull it
down.

DATA ACCESS
Scenes are found through NASA's CMR search (public) and read from LP DAAC
(Earthdata login required -- see :func:`earthdata_session`). Files are ~2 GB;
only the parts covering the field are read over HTTP range requests, a few tens
of megabytes per scene. Results are cached per field and scene.

Version 001 granules come with a cloud mask (EMIT_L2A_MASK, "Aggregate Flag").
Version 002 reprocessed the reflectance but ships no mask, so for a scene only
in version 002 a simple test stands in: blue reflectance above
EMIT_V2_CLOUD_BLUE is called cloud. Where both versions exist, 001 is used.
"""

from __future__ import annotations

import io
import netrc
import os
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely

from .aoi import field_bounds
from .cache import cache_get, cache_key, cache_put

CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
EMIT_COLLECTION = "EMITL2ARFL"
EARTHDATA_HOST = "urs.earthdata.nasa.gov"

# --- provisional constants -----------------------------------------------------

# Scenes the CMR rates cloudier than this over their whole ~75 km swath are not
# read. Field-level cloud is decided per pixel afterwards; this only saves
# reading scenes that are almost certainly cloud.
EMIT_MAX_SCENE_CLOUD = 80

# CAI band centers (nm) and the half-width averaged around each. Daughtry's
# definition uses ~10 nm bands at 2031, 2101 and 2211 nm.
CAI_BANDS_NM = (2031.0, 2101.0, 2211.0)
CAI_HALF_NM = 10.0

# A scene is reported only when at least this share of the field's pixels is
# cloud-free, and the field has at least EMIT_MIN_PIXELS pixel centers inside.
EMIT_MIN_CLEAR = 0.8
EMIT_MIN_PIXELS = 4

# Version 002 has no cloud mask: blue (450-470 nm) reflectance above this is
# called cloud. Bright, but crude -- bright soil or snow can trip it.
EMIT_V2_CLOUD_BLUE = 0.20

# Snow: NDSI (560 vs 1610 nm) above this, with NIR above EMIT_SNOW_NIR, the
# MODIS snow test. Snow pixels are left out like cloud -- a snow-covered field
# says nothing about its residue.
EMIT_SNOW_NDSI = 0.40
EMIT_SNOW_NIR = 0.11

# A scene that sees less than this share of the field's expected pixels (field
# area over 60 m x 60 m) is reported, with a note that it covers part of it.
EMIT_MIN_COVER = 0.8

# CAI reads residue only on ground that is not green. Same ceiling the rest of
# the package uses for "not green" (residue.py, sar.py).
CAI_GREEN_NDVI = 0.30


class EarthdataAuthError(RuntimeError):
    """No Earthdata login configured."""


EARTHDATA_SETUP = (
    "EMIT data needs a free NASA Earthdata login. Either put it in ~/.netrc as\n"
    "    machine urs.earthdata.nasa.gov login <username> password <password>\n"
    "(chmod 600 ~/.netrc), or set EARTHDATA_TOKEN to a token generated at "
    "https://urs.earthdata.nasa.gov under Generate Token.")


def earthdata_session() -> requests.Session:
    """A requests session that can read LP DAAC: a bearer token from
    EARTHDATA_TOKEN if set, otherwise the ~/.netrc entry for
    urs.earthdata.nasa.gov (requests reads it on the login redirect)."""
    s = requests.Session()
    token = os.environ.get("EARTHDATA_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
        return s
    path = Path(os.environ.get("NETRC", Path.home() / ".netrc"))
    try:
        has = path.exists() and netrc.netrc(path).authenticators(EARTHDATA_HOST) is not None
    except (netrc.NetrcParseError, OSError):
        has = False
    if not has:
        raise EarthdataAuthError(EARTHDATA_SETUP)
    return s


# ------------------------------------------------------------------ search ---

def emit_search(aoi: gpd.GeoDataFrame, start: str, end: str) -> pd.DataFrame:
    """EMIT L2A reflectance scenes over the field, one row per acquisition.

    Columns: ``scene`` (acquisition time, e.g. 20230620T175946), ``date``,
    ``version``, ``cloud_pct`` (whole scene, CMR), ``rfl_url``, ``mask_url``
    (version 001 only). Where an acquisition exists in both versions, 001 is
    kept for its cloud mask.
    """
    w, s_, e, n = field_bounds(aoi)
    rows = []
    for version in ("001", "002"):
        page = 1
        while True:
            r = requests.get(CMR_GRANULES, params={
                "short_name": EMIT_COLLECTION, "version": version,
                "bounding_box": f"{w},{s_},{e},{n}",
                "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                "page_size": 200, "page_num": page}, timeout=60)
            r.raise_for_status()
            entries = r.json()["feed"]["entry"]
            for g in entries:
                links = [lk["href"] for lk in g.get("links", [])
                         if lk["href"].startswith("https://") and lk["href"].endswith(".nc")]
                # Match on the file name: the folder of every file in a
                # granule is named EMIT_L2A_RFL_..., the MASK one included.
                rfl = next((u for u in links if "_L2A_RFL_" in u.rsplit("/", 1)[-1]), None)
                if rfl is None:
                    continue
                m = re.search(r"_(\d{8}T\d{6})", rfl.rsplit("/", 1)[-1])
                rows.append({"scene": m.group(1) if m else g["id"],
                             "date": pd.Timestamp(g["time_start"][:10]),
                             "version": version,
                             "cloud_pct": float(g.get("cloud_cover", np.nan)),
                             "rfl_url": rfl,
                             "mask_url": next((u for u in links
                                               if "_L2A_MASK_" in u.rsplit("/", 1)[-1]), None)})
            if len(entries) < 200:
                break
            page += 1
    cols = ["scene", "date", "version", "cloud_pct", "rfl_url", "mask_url"]
    if not rows:
        return pd.DataFrame(columns=cols)
    # Both versions carry the same acquisition time in the file name; keep 001.
    # Neighbouring ~11 s tiles of one pass have different times and are both
    # kept -- the one the field is not in reports that and costs one read.
    df = pd.DataFrame(rows).sort_values(["scene", "version"])
    df = df.drop_duplicates("scene", keep="first")
    return df.sort_values("date").reset_index(drop=True)[cols]


# -------------------------------------------------------------------- read ---

class _HTTPRange(io.RawIOBase):
    """A read-only file over HTTP range requests, for h5py. Resolves the LP DAAC
    login redirect once and then reads the signed URL directly."""

    def __init__(self, url: str, session: requests.Session):
        r = session.get(url, headers={"Range": "bytes=0-0"}, timeout=120)
        if r.status_code in (401, 403):
            raise EarthdataAuthError("Earthdata refused the login.\n" + EARTHDATA_SETUP)
        r.raise_for_status()
        self._s, self._url = session, r.url
        self.size = int(r.headers["Content-Range"].split("/")[1])
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, off, whence=0):
        self._pos = off if whence == 0 else self._pos + off if whence == 1 else self.size + off
        return self._pos

    def readinto(self, b):
        n = min(len(b), self.size - self._pos)
        if n <= 0:
            return 0
        r = self._s.get(self._url, headers={"Range": f"bytes={self._pos}-{self._pos + n - 1}"},
                        timeout=120)
        r.raise_for_status()
        b[:n] = r.content
        self._pos += n
        return n


def _open(url: str, session: requests.Session):
    import h5py
    return h5py.File(io.BufferedReader(_HTTPRange(url, session), buffer_size=1 << 18), "r")


def _band_mean(refl: np.ndarray, wl: np.ndarray, center: float, half: float) -> np.ndarray:
    idx = np.where(np.abs(wl - center) <= half)[0]
    return np.nanmean(refl[..., idx], axis=-1)


def _field_window(h5, aoi: gpd.GeoDataFrame):
    """Rows, columns and the in-field pixel mask of the smallest raw-geometry
    window holding every pixel center inside the field."""
    geom = aoi.to_crs(4326).geometry.union_all()
    w, s_, e, n = geom.bounds
    pad = 0.001                                  # ~100 m, so edge pixels are found
    lat, lon = h5["location/lat"][()], h5["location/lon"][()]
    near = (lat >= s_ - pad) & (lat <= n + pad) & (lon >= w - pad) & (lon <= e + pad)
    if not near.any():
        return None
    rr, cc = np.where(near)
    r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1
    inside = shapely.contains_xy(geom, lon[r0:r1, c0:c1], lat[r0:r1, c0:c1])
    return (r0, r1, c0, c1), inside


def emit_scene_cai(scene: pd.Series, aoi: gpd.GeoDataFrame,
                   session: requests.Session | None = None) -> dict:
    """CAI and NDVI over the field for one scene (a row of :func:`emit_search`)."""
    session = session or earthdata_session()
    out = {"scene": scene["scene"], "date": scene["date"], "version": scene["version"],
           "cloud_pct": scene["cloud_pct"], "n_pixels": 0, "field_cover": np.nan,
           "clear_frac": np.nan, "snow_frac": np.nan,
           "cai_median": np.nan, "cai_p10": np.nan, "cai_p90": np.nan,
           "ndvi_median": np.nan, "reading": None, "note": None}
    with _open(scene["rfl_url"], session) as h5:
        win = _field_window(h5, aoi)
        if win is None:
            out["note"] = "field not inside this scene's footprint"
            return out
        (r0, r1, c0, c1), inside = win
        out["n_pixels"] = int(inside.sum())
        expected = aoi.to_crs(5070).area.sum() / 3600.0
        out["field_cover"] = round(min(out["n_pixels"] / expected, 1.0), 2)
        if out["n_pixels"] < EMIT_MIN_PIXELS:
            out["note"] = f"only {out['n_pixels']} pixel center(s) inside the field"
            return out
        wl = h5["sensor_band_parameters/wavelengths"][()]
        refl = h5["reflectance"][r0:r1, c0:c1, :].astype("float32")
    refl[refl < -1] = np.nan                                  # -9999 fill

    if scene["version"] == "001" and scene.get("mask_url"):
        with _open(scene["mask_url"], session) as hm:
            names = [n.decode() if isinstance(n, bytes) else str(n)
                     for n in hm["sensor_band_parameters/mask_bands"][()]]
            k = next(i for i, n in enumerate(names) if "aggregate" in n.lower())
            cloud = hm["mask"][r0:r1, c0:c1, k] > 0
        how = "EMIT aggregate cloud flag"
    else:
        cloud = _band_mean(refl, wl, 460.0, 10.0) > EMIT_V2_CLOUD_BLUE
        how = f"blue reflectance > {EMIT_V2_CLOUD_BLUE:g} (version 002 has no mask)"

    green, swir = _band_mean(refl, wl, 560.0, 10.0), _band_mean(refl, wl, 1610.0, 15.0)
    nir = _band_mean(refl, wl, 860.0, 10.0)
    snow = ((green - swir) / (green + swir) > EMIT_SNOW_NDSI) & (nir > EMIT_SNOW_NIR)
    valid = inside & np.isfinite(refl[..., 0])
    ok = valid & ~cloud & ~snow
    out["clear_frac"] = round(float(ok.sum() / inside.sum()), 3)
    out["snow_frac"] = round(float((valid & ~cloud & snow).sum() / inside.sum()), 3)
    if out["clear_frac"] < EMIT_MIN_CLEAR:
        why = ("snow" if out["snow_frac"] >= 1 - EMIT_MIN_CLEAR else f"cloud ({how})")
        out["note"] = f"only {out['clear_frac']:.0%} of the field clear -- {why}"
        return out
    b0, b1, b2 = (_band_mean(refl, wl, c, CAI_HALF_NM) for c in CAI_BANDS_NM)
    cai = (100 * (0.5 * (b0 + b2) - b1))[ok]
    red, nir = _band_mean(refl, wl, 660.0, 10.0), _band_mean(refl, wl, 860.0, 10.0)
    ndvi = ((nir - red) / (nir + red))[ok]
    out.update(cai_median=round(float(np.nanmedian(cai)), 2),
               cai_p10=round(float(np.nanpercentile(cai, 10)), 2),
               cai_p90=round(float(np.nanpercentile(cai, 90)), 2),
               ndvi_median=round(float(np.nanmedian(ndvi)), 3))
    out["reading"] = ("green canopy -- CAI is not a residue reading"
                      if out["ndvi_median"] >= CAI_GREEN_NDVI else
                      "not green -- CAI reads dry residue")
    out["note"] = f"cloud screen: {how}"
    if out["field_cover"] < EMIT_MIN_COVER:
        out["note"] += (f"; the scene covers only {out['field_cover']:.0%} of the field "
                        "(swath edge)")
    return out


def emit_cai(aoi: gpd.GeoDataFrame, start: str, end: str, *, only_cached: bool = False,
             progress=None) -> pd.DataFrame | None:
    """Every EMIT scene over the field between ``start`` and ``end``, with CAI.

    One row per scene read (cloudy and unusable scenes included, with the reason
    in ``note``). With ``only_cached`` it returns None unless the scene list and
    every scene are cached. ``progress(done, total, message)`` is optional.
    """
    skey = cache_key(aoi, start, end, "emit_search_v2")
    scenes = cache_get(skey, "emit")
    if scenes is None:
        if only_cached:
            return None
        scenes = cache_put(skey, emit_search(aoi, start, end), "emit")
    scenes = scenes[scenes["cloud_pct"].fillna(0) <= EMIT_MAX_SCENE_CLOUD]
    rows, session = [], None
    for i, sc in enumerate(scenes.itertuples(index=False)):
        sc = pd.Series(sc._asdict())
        key = cache_key(aoi, sc["scene"], sc["version"], "emit_cai_v2")
        hit = cache_get(key, "emit")
        if hit is None:
            if only_cached:
                return None
            if progress:
                progress(i, len(scenes), f"Reading EMIT scene {sc['date']:%Y-%m-%d}")
            session = session or earthdata_session()
            try:
                hit = emit_scene_cai(sc, aoi, session)
            except EarthdataAuthError:
                raise
            except Exception as exc:                          # noqa: BLE001
                hit = {"scene": sc["scene"], "date": sc["date"], "version": sc["version"],
                       "cloud_pct": sc["cloud_pct"], "note": f"read failed: {exc}"}
            else:
                cache_put(key, hit, "emit")
        rows.append(hit)
    if progress:
        progress(len(scenes), len(scenes), "EMIT done")
    cols = ["date", "scene", "version", "cloud_pct", "n_pixels", "field_cover",
            "clear_frac", "snow_frac",
            "cai_median", "cai_p10", "cai_p90", "ndvi_median", "reading", "note"]
    return pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)
