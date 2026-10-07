"""Disk cache and the analysis window.

A six-year NDVI history over one field is several hundred HTTP reads. That is
fine to wait for once and intolerable to wait for twice, so every expensive
result is keyed on the field geometry plus the query and pickled to ``cache/``.
"""

from __future__ import annotations

import hashlib
import os
import pickle
from datetime import date
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd

# Anchored to the package, not the working directory.
#
# This was `Path("cache")`, which resolves against wherever you happen to be
# standing. Running anything from the repo root instead of python/ therefore
# created a second, empty cache there and silently re-downloaded the lot --
# and because a miss looks exactly like a cold field, the symptom was
# "only_cached returned None" rather than anything pointing at the real cause.
#
# Set FIELDRS_CACHE to override, which is what you want if fieldrs is
# installed into site-packages rather than run from a checkout.
CACHE_DIR = Path(os.environ.get("FIELDRS_CACHE")
                 or Path(__file__).resolve().parent.parent / "cache")


def analysis_window(year_from: int, year_to: int) -> tuple[str, str]:
    """Start and end dates for a year range, as ``YYYY-MM-DD``.

    The end is floored to the first of the current month rather than "today".
    Cache keys include the window, so an end date of today would mint a new key
    every day and a pre-computed library would go cold overnight.

    The cost is excluding the current month. Against a multi-year series whose
    final season is incomplete anyway that changes nothing material.
    """
    today = date.today()
    month_start = today.replace(day=1)
    end = min(month_start, date(year_to, 12, 31))
    return f"{year_from}-01-01", end.isoformat()


def cache_key(aoi: gpd.GeoDataFrame, *parts: Any) -> str:
    """Stable key for a field plus a query.

    Coordinates are rounded to the metre in an equal-area projection before
    hashing, so re-exporting the same boundary still hits the same entry while a
    genuinely edited one does not.
    """
    geom = aoi.to_crs(5070).geometry.union_all()
    coords = []
    for poly in getattr(geom, "geoms", [geom]):
        coords.extend((round(x), round(y)) for x, y in poly.exterior.coords)
    payload = repr((sorted(coords), [repr(p) for p in parts])).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _path(key: str, tag: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{tag}_{key}.pkl"


def cache_get(key: str, tag: str = "obj") -> Any | None:
    p = _path(key, tag)
    if not p.exists():
        return None
    try:
        with p.open("rb") as fh:
            return pickle.load(fh)
    except Exception:
        return None


def cache_put(key: str, value: Any, tag: str = "obj") -> Any:
    with _path(key, tag).open("wb") as fh:
        pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return value


def cached(key: str, fn: Callable[[], Any], tag: str = "obj",
           refresh: bool = False) -> Any:
    """Run ``fn`` unless a cached result exists."""
    if not refresh:
        hit = cache_get(key, tag)
        if hit is not None:
            return hit
    return cache_put(key, fn(), tag)


def cache_clear() -> None:
    if CACHE_DIR.exists():
        for p in CACHE_DIR.glob("*.pkl"):
            p.unlink()
