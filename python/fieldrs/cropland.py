"""USDA Cropland Data Layer (CDL).

The CDL is USDA NASS's annual 30 m crop-type map of the US: what was actually
planted in each field each year, which is what turns a generic NDVI curve into
"this is the corn signal".

Delivered by CropScape, a web service hosted at George Mason University under
cooperative agreement with NASS. No account needed. It is a public service and
is sometimes slow, hence the generous timeout -- but a published CDL year never
changes, so a field pays for it once and the cache is permanent.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import reproject

from .cache import cache_get, cache_key, cache_put

CROPSCAPE_URL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"
CDL_CRS = 5070          # CONUS Albers, the CDL's native projection


def _session() -> requests.Session:
    """A requests session that can actually reach CropScape.

    CropScape serves an incomplete certificate chain: it omits an intermediate,
    and clients that will not chase the issuer themselves reject it. Browsers
    and libcurl paper over this using the OS trust store, which is why the R
    pipeline never hit it; Python's ``requests`` uses certifi's bundle and fails
    with CERTIFICATE_VERIFY_FAILED.

    ``truststore`` routes verification through the operating system's store,
    which is the same thing curl does. Verification stays ON -- we do not pass
    ``verify=False``, which would accept any certificate at all.
    """
    session = requests.Session()
    try:
        import ssl
        import truststore

        class _OSTrustAdapter(requests.adapters.HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                return super().init_poolmanager(*args, **kwargs)

        session.mount("https://", _OSTrustAdapter())
    except ImportError:
        pass        # fall through; the error below explains the fix
    return session


def _ssl_help(exc: Exception) -> str:
    return (
        f"CropScape TLS verification failed ({exc}). The service serves an "
        "incomplete certificate chain. Install `truststore` (pip install "
        "truststore) so verification uses the OS certificate store, which is "
        "what curl and the R pipeline do."
    )


@dataclass
class CdlStack:
    """Every year's CDL for one field, on one aligned grid."""
    years: list[int]
    data: np.ndarray        # (n_years, height, width), NaN outside the field
    transform: object
    crs: object

    @property
    def pixel_ha(self) -> float:
        a, e = abs(self.transform.a), abs(self.transform.e)
        return a * e / 1e4

    def year(self, y: int) -> np.ndarray:
        return self.data[self.years.index(y)]


def get_cdl(aoi: gpd.GeoDataFrame, year: int, clip: bool = True,
            timeout: int = 180) -> tuple[np.ndarray, object, object]:
    """One year's CDL clipped to the field.

    Reads the local bulk store when one is present, and falls back to the
    CropScape API when it is not. The store is preferred because CropScape is a
    public web service that throttles and times out under load, not because it
    is more accurate -- measured against polygon geometric area on 347
    field-years the API's pixel counts were already faithful to +0.06% mean.
    Set ``FIELDRS_CDL_LOCAL=0`` to force the API.
    """
    from .cdl_local import get_cdl_local, use_local

    if use_local():
        try:
            return get_cdl_local(aoi, year, clip=clip)
        except FileNotFoundError:
            # That year is not downloaded; the API can still answer for it.
            pass

    bounds = aoi.to_crs(CDL_CRS).geometry.union_all().buffer(100).bounds
    url = (f"{CROPSCAPE_URL}?year={year}"
           f"&bbox={bounds[0]:f},{bounds[1]:f},{bounds[2]:f},{bounds[3]:f}")

    print(f"  Requesting CDL {year} from CropScape...", flush=True)
    session = _session()
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.SSLError as exc:
        raise RuntimeError(_ssl_help(exc)) from exc

    m = re.search(r"<returnURL>(.*?)</returnURL>", resp.text)
    if not m:
        raise RuntimeError(
            "Could not parse a GeoTIFF URL from the CropScape response. Most "
            f"often CDL has no data for {year} yet, or the area is outside the "
            f"US. Response began: {resp.text[:200]}"
        )

    tif = session.get(m.group(1), timeout=timeout)
    tif.raise_for_status()

    with rasterio.open(io.BytesIO(tif.content)) as src:
        arr = src.read(1).astype("float32")
        transform, crs = src.transform, src.crs

    if clip:
        geom = aoi.to_crs(crs).geometry.union_all()
        inside = geometry_mask([geom], out_shape=arr.shape, transform=transform,
                               invert=True)
        arr = np.where(inside, arr, np.nan)
    return arr, transform, crs


def cdl_stack(aoi: gpd.GeoDataFrame, years=None, refresh: bool = False,
              only_cached: bool = False) -> CdlStack | None:
    """Every year's CDL on one aligned grid.

    This is the primitive the rotation table and the boundary check both read,
    so a field costs one CropScape round trip per year and no more.
    """
    if years is None:
        years = list(range(2020, date.today().year))
    years = list(years)

    key = cache_key(aoi, years, "cdl_stack_v2")
    if not refresh:
        hit = cache_get(key, "cdlstack")
        # A stack pickled under affine 2.x (a namedtuple) unpickles under 3.x
        # as an Affine with no coefficients, and only fails later on first
        # use. Treat it as a miss so it is rebuilt with the installed version.
        if hit is not None and hasattr(hit.transform, "a"):
            return hit
    if only_cached:
        return None

    layers: list[np.ndarray] = []
    kept: list[int] = []
    ref_transform = ref_crs = None
    ref_shape: tuple[int, int] | None = None

    for y in years:
        try:
            arr, transform, crs = get_cdl(aoi, y)
        except Exception as exc:                      # noqa: BLE001
            print(f"  CDL {y} unavailable: {exc}", flush=True)
            continue

        if ref_shape is None:
            ref_transform, ref_crs, ref_shape = transform, crs, arr.shape
        elif arr.shape != ref_shape:
            # CropScape clips each request independently, so grids can differ by
            # a pixel. Snap to the first year so years compare pixel for pixel.
            # Classes are categorical: nearest neighbour only.
            dst = np.full(ref_shape, np.nan, dtype="float32")
            reproject(arr, dst, src_transform=transform, src_crs=crs,
                      dst_transform=ref_transform, dst_crs=ref_crs,
                      resampling=Resampling.nearest,
                      src_nodata=np.nan, dst_nodata=np.nan)
            arr = dst
        layers.append(arr)
        kept.append(y)

    if not layers:
        raise RuntimeError(
            f"CropScape returned no CDL for {min(years)}-{max(years)}. The "
            "service may be down, or the field may be outside the US."
        )

    stack = CdlStack(kept, np.stack(layers), ref_transform, ref_crs)
    cache_put(key, stack, "cdlstack")
    return stack


def cdl_summary(arr: np.ndarray, pixel_ha: float = 0.09) -> pd.DataFrame:
    """Break one year down by CDL class, sorted by area."""
    v = arr[np.isfinite(arr)].astype("int32")
    if v.size == 0:
        raise ValueError("No CDL pixels inside the field.")
    codes, counts = np.unique(v, return_counts=True)
    df = pd.DataFrame({
        "code": codes.astype(int),
        "crop": [cdl_name(int(c)) for c in codes],
        "n_pixels": counts.astype(int),
    })
    df["area_ha"] = (df["n_pixels"] * pixel_ha).round(2)
    df["pct"] = (100 * df["n_pixels"] / df["n_pixels"].sum()).round(1)
    df["is_crop"] = ~df["code"].isin(CDL_NONCROP)
    return df.sort_values("n_pixels", ascending=False).reset_index(drop=True)


def cdl_history_from_stack(stack: CdlStack) -> pd.DataFrame:
    """Rotation table: the dominant crop for each year."""
    rows = []
    for y in stack.years:
        s = cdl_summary(stack.year(y), stack.pixel_ha)
        rows.append({"year": y, "crop": s.crop[0], "pct": s.pct[0],
                     "is_crop": bool(s.is_crop[0]), "n_classes": len(s)})
    return pd.DataFrame(rows)


def crop_lookup(hist: pd.DataFrame) -> dict[int, str]:
    """year -> crop, the shape phenology and cover crop code want."""
    return {int(r.year): r.crop for r in hist.itertuples() if isinstance(r.crop, str)}


def cdl_name(code: int) -> str:
    return CDL_CLASSES.get(code, f"class {code}")


# ------------------------------------------------------------ class table ---
# The classes covering essentially all US acreage, plus every non-crop class.
# Anything else falls back to "class <code>".
CDL_CLASSES: dict[int, str] = {
    1: "Corn", 2: "Cotton", 3: "Rice", 4: "Sorghum", 5: "Soybeans",
    6: "Sunflower", 10: "Peanuts", 11: "Tobacco", 12: "Sweet Corn",
    13: "Pop/Orn Corn", 14: "Mint", 21: "Barley", 22: "Durum Wheat",
    23: "Spring Wheat", 24: "Winter Wheat", 25: "Other Small Grains",
    26: "Dbl Crop WinWht/Soybeans", 27: "Rye", 28: "Oats", 29: "Millet",
    30: "Speltz", 31: "Canola", 32: "Flaxseed", 33: "Safflower",
    34: "Rape Seed", 35: "Mustard", 36: "Alfalfa",
    37: "Other Hay/Non Alfalfa", 38: "Camelina", 39: "Buckwheat",
    41: "Sugarbeets", 42: "Dry Beans", 43: "Potatoes", 44: "Other Crops",
    45: "Sugarcane", 46: "Sweet Potatoes", 47: "Misc Vegs & Fruits",
    48: "Watermelons", 49: "Onions", 50: "Cucumbers", 51: "Chick Peas",
    52: "Lentils", 53: "Peas", 54: "Tomatoes", 55: "Caneberries",
    56: "Hops", 57: "Herbs", 58: "Clover/Wildflowers", 59: "Sod/Grass Seed",
    60: "Switchgrass", 61: "Fallow/Idle Cropland",
    63: "Forest", 64: "Shrubland", 65: "Barren", 66: "Cherries",
    67: "Peaches", 68: "Apples", 69: "Grapes", 70: "Christmas Trees",
    71: "Other Tree Crops", 72: "Citrus", 74: "Pecans", 75: "Almonds",
    76: "Walnuts", 77: "Pears",
    81: "Clouds/No Data", 82: "Developed", 83: "Water", 87: "Wetlands",
    88: "Nonag/Undefined", 92: "Aquaculture",
    111: "Open Water", 112: "Perennial Ice/Snow",
    121: "Developed/Open Space", 122: "Developed/Low Intensity",
    123: "Developed/Med Intensity", 124: "Developed/High Intensity",
    131: "Barren", 141: "Deciduous Forest", 142: "Evergreen Forest",
    143: "Mixed Forest", 152: "Shrubland", 176: "Grass/Pasture",
    190: "Woody Wetlands", 195: "Herbaceous Wetlands",
    204: "Pistachios", 205: "Triticale", 206: "Carrots",
    207: "Asparagus", 208: "Garlic", 209: "Cantaloupes", 210: "Prunes",
    211: "Olives", 212: "Oranges", 214: "Broccoli", 216: "Peppers",
    217: "Pomegranates", 218: "Nectarines", 219: "Greens", 220: "Plums",
    221: "Strawberries", 222: "Squash", 223: "Apricots", 224: "Vetch",
    225: "Dbl Crop WinWht/Corn", 226: "Dbl Crop Oats/Corn", 227: "Lettuce",
    228: "Dbl Crop Triticale/Corn", 229: "Pumpkins",
    236: "Dbl Crop WinWht/Sorghum", 237: "Dbl Crop Barley/Corn",
    238: "Dbl Crop WinWht/Cotton", 239: "Dbl Crop Soybeans/Oats",
    240: "Dbl Crop Corn/Soybeans", 241: "Dbl Crop", 242: "Blueberries",
    243: "Cabbage", 244: "Cauliflower", 245: "Celery", 246: "Radishes",
    247: "Turnips", 250: "Cranberries", 254: "Dbl Crop Barley/Soybeans",
}

# Classes that are not agricultural land.
CDL_NONCROP = frozenset({
    63, 64, 65, 81, 82, 83, 87, 88, 92, 111, 112,
    121, 122, 123, 124, 131, 141, 142, 143, 152, 176, 190, 195,
})
