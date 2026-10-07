"""What data exists for this field, and when.

Port of R/catalog.R. Metadata only: these are catalogue queries, not pixel
reads, so a multi-sensor sweep across the whole record takes seconds. That
makes it a good opening view -- it answers "how much do we actually have to
work with for this field" before anyone waits on an extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import geopandas as gpd
import pandas as pd
import pystac_client

from .aoi import field_bounds
from .cache import cache_get, cache_key, cache_put
from .imagery import PC_STAC


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    kind: str
    res: str
    revisit: str
    note: str


# All free and open, none needs an account. Ordered coarse-to-fine so the
# timeline reads sensibly top to bottom.
CATALOG_SOURCES: list[Source] = [
    Source("sentinel-2-l2a", "Sentinel-2 L2A", "Optical", "10 m", "~5 days",
          "Primary workhorse. Red/NIR for NDVI, SCL for cloud masking."),
    Source("landsat-c2-l2", "Landsat 8/9", "Optical", "30 m", "~8 days (two sats)",
          "Coarser but the archive runs back to 1982 -- the route to long baselines."),
    Source("hls2-s30", "HLS Sentinel-2", "Optical", "30 m", "~5 days",
          "NASA harmonised product; Sentinel-2 resampled to the Landsat grid."),
    Source("hls2-l30", "HLS Landsat", "Optical", "30 m", "~8 days",
          "Landsat side of the harmonised pair. Combine the two for a dense series."),
    Source("sentinel-1-rtc", "Sentinel-1 radar", "Radar", "10 m", "~12 days",
          "Sees through cloud. Independent of the weather that thins optical winter coverage."),
    Source("modis-13Q1-061", "MODIS NDVI 16-day", "Composite", "250 m", "16 days",
          "Too coarse for one field, but a consistent 2000-present reference."),
    Source("naip", "NAIP aerial", "Aerial", "0.6 m", "2-3 years",
          "Sub-metre true colour + NIR. Good for showing leadership what a field looks like."),
]


def catalog_availability(
    aoi: gpd.GeoDataFrame,
    start: str = "2020-01-01",
    end: str | None = None,
    sources: list[Source] = CATALOG_SOURCES,
    refresh: bool = False,
    only_cached: bool = False,
    progress=None,
) -> pd.DataFrame | None:
    """Every acquisition over the field, per source.

    Returns a DataFrame of source, label, kind, res, date and cloud (NaN
    where the source does not report it, e.g. radar or CDL).
    """
    end = end or date.today().isoformat()

    key = cache_key(aoi, start, end, [s.id for s in sources], "catalog_v1")
    if not refresh:
        hit = cache_get(key, "catalog")
        if hit is not None:
            return hit
    if only_cached:
        return None

    bbox = field_bounds(aoi)
    catalog = pystac_client.Client.open(PC_STAC)
    rows: list[dict] = []

    for k, src in enumerate(sources):
        if progress:
            progress(k + 1, len(sources), f"Querying {src.label}")
        try:
            search = catalog.search(
                collections=[src.id], bbox=bbox,
                datetime=f"{start}T00:00:00Z/{end}T23:59:59Z", limit=500,
            )
            items = list(search.items())
        except Exception:                              # noqa: BLE001
            continue
        if not items:
            continue

        for it in items:
            dt = it.properties.get("datetime") or it.properties.get("start_datetime")
            if not dt:
                continue
            cloud = it.properties.get("eo:cloud_cover")
            rows.append({
                "source": src.id, "label": src.label, "kind": src.kind,
                "res": src.res, "date": dt[:10],
                "cloud": float("nan") if cloud is None else float(cloud),
            })

    # CDL is annual and comes from CropScape rather than STAC, so it is added
    # by hand. It is published for year Y in the first months of Y+1.
    y_from, y_to = int(start[:4]), int(end[:4])
    last_cdl = date.today().year - 1
    for y in range(y_from, min(y_to, last_cdl) + 1):
        rows.append({
            "source": "usda-cdl", "label": "USDA CDL", "kind": "Crop type",
            "res": "30 m", "date": f"{y}-07-01", "cloud": float("nan"),
        })

    if not rows:
        out = pd.DataFrame(columns=["source", "label", "kind", "res", "date", "cloud"])
    else:
        out = pd.DataFrame(rows)
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values(["label", "date"]).reset_index(drop=True)

    cache_put(key, out, "catalog")
    return out


def catalog_summary(avail: pd.DataFrame) -> pd.DataFrame:
    """Per-source summary: how many acquisitions, how often, how many usable."""
    if avail is None or not len(avail):
        return pd.DataFrame()

    rows = []
    for label, d in avail.groupby("label"):
        d = d.sort_values("date")
        gaps = d["date"].diff().dt.days.dropna()
        cloud_known = d["cloud"].notna().any()
        rows.append({
            "Source": label, "Type": d["kind"].iloc[0], "Resolution": d["res"].iloc[0],
            "Acquisitions": len(d),
            "Clear (<20% cloud)": int((d["cloud"] < 20).sum()) if cloud_known else None,
            "Median gap (days)": round(float(gaps.median()), 1) if len(gaps) else None,
            "First": d["date"].min().strftime("%Y-%m-%d"),
            "Last": d["date"].max().strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows).sort_values("Acquisitions", ascending=False).reset_index(drop=True)
