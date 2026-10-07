"""Multi-year field statistics, in parallel.

Phenology and cover crop detection need several years of year-round
observations: several hundred HTTP reads, a couple of seconds each, so roughly
20 minutes if done one at a time.

Each read is network-bound rather than CPU-bound, and GDAL releases the GIL
while waiting on HTTP, so a thread pool gets most of the speed-up without the
pickling and process-startup costs of multiprocessing. Results are cached, so a
field pays the cost once.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from .cache import cache_get, cache_key, cache_put
from .imagery import SOURCES, Scene, read_scene, scene_groups, search_scenes, sensor_of
from .indices import bands_for, compute_index

Progress = Callable[[int, int, str], None] | None

# --- HLS -> Sentinel-2 NDVI transfer ------------------------------------------
# Every NDVI threshold in this package (residue ceiling, green floor, the
# phenology amplitude guards) was set on Sentinel-2 L2A. HLS reads higher over
# bare and residue-covered ground: HLS-S30 uses the narrow NIR band (B8A, not
# B08), LaSRC rather than Sen2Cor atmospheric correction, and BRDF
# normalisation. Left alone, HLS bare soil sits on the 0.25 residue ceiling and
# fields with no cover crop read as "likely cover crop".
#
# So HLS NDVI is mapped onto the Sentinel-2 scale, ndvi_s2 = a * ndvi_hls + b,
# per HLS sensor. FITTED, not assumed: least squares on same-day field medians
# from Sentinel-2 L2A and HLS-S30 -- the same satellite pass, so the difference
# is processing alone -- across the field library. See HLS_TRANSFER_FIT.
# L30 is harmonised to S30 by HLS itself and gets the S30 transfer unless its
# own near-coincident pairs say otherwise.
HLS_TRANSFER = {
    "HLS-S30": (1.0733, -0.0758),
    "HLS-L30": (1.0707, -0.0686),
}
# Fitted 2026-10-06 on the 15 fields in data/fields/, 2020-01 to 2026-09,
# field-median NDVI, dates with valid_frac >= 0.9 and within-field sd < 0.15,
# one refit without residuals beyond 3 robust SDs:
#   S30: 2,941 same-day pairs with Sentinel-2 L2A, residual RMSE 0.026
#   L30:   818 pairs within one day of a Sentinel-2 date, RMSE 0.024
# Bias HLS minus S2 before -> after, by S2 NDVI:
#   S30  < 0.3 +0.055 -> -0.003   0.3-0.6 +0.052 -> +0.011   >= 0.6 +0.011 -> -0.003
#   L30  < 0.3 +0.049 -> -0.009   0.3-0.6 +0.039 -> -0.002   >= 0.6 +0.003 -> -0.010
# The bare-soil offset was +0.035 to +0.072 on every one of the 15 fields --
# a processing difference, not a site effect -- which is why one transfer is
# applied everywhere. Refit if the library grows into other regions.
HLS_TRANSFER_FIT = "15 library fields, 2020-2026; 2,941 S30 and 818 L30 pairs"
_STAT_COLS = ("mean", "median", "p10", "p90")


# --- HLS spike filter -----------------------------------------------------------
# HLS's Fmask misses some partial snow and thin cloud that Sentinel-2's SCL
# catches. On the library's no-cover-crop fields every winter HLS reading
# above NDVI 0.30 was a single-date spike, 0.11-0.23 above its neighbours,
# mostly on passes SCL had rejected outright -- and one such spike is enough
# for a "possible cover crop" verdict. A reading more than SPIKE_NDVI from the
# nearest reading on BOTH sides, in the same direction, within SPIKE_DAYS, is
# dropped. A real green-up or harvest moves one way and stays there, so it
# survives. HLS only: the Sentinel-2 series is left exactly as validated.
SPIKE_NDVI = 0.10
SPIKE_DAYS = 20


# Winter rule. Snow season leaves long gaps, and a spike next to one has no
# near neighbour on that side for the two-sided test -- three of the Iowa
# no-cover-crop field's winter spikes survived it that way. From November to
# March only, a reading with no neighbour within SPIKE_DAYS on one side is
# judged against the other side alone, if that side has at least two readings
# within SPIKE_DAYS that agree to SPIKE_NDVI / 2. A green-up or a cover crop's
# spring growth is a trend, not a plateau, so it fails that test and is kept;
# confining it to winter keeps it clear of harvest drops after a cloudy spell.
SPIKE_WINTER_MONTHS = (11, 12, 1, 2, 3)


def despike(df: pd.DataFrame, index: str = "ndvi", jump: float = SPIKE_NDVI,
            days: int = SPIKE_DAYS) -> pd.DataFrame:
    """Drop single-date spikes from one index's series (see SPIKE_NDVI).

    Judged on field means. Two-sided: more than ``jump`` from the nearest
    reading on each side, same direction, both within ``days``. One-sided,
    winter only: see SPIKE_WINTER_MONTHS.
    """
    d = df[df["index"] == index].sort_values("date")
    if len(d) < 3:
        return df
    v = d["mean"].to_numpy()
    t = d["date"].to_numpy()
    month = d["date"].dt.month.to_numpy()
    gap = np.timedelta64(days, "D")
    drop = []
    for k in range(len(d)):
        before = [j for j in range(k - 1, -1, -1) if t[k] - t[j] <= gap]
        after = [j for j in range(k + 1, len(d)) if t[j] - t[k] <= gap]
        if before and after:
            dp, dn = v[k] - v[before[0]], v[k] - v[after[0]]
            if (dp > jump and dn > jump) or (dp < -jump and dn < -jump):
                drop.append(k)
        elif month[k] in SPIKE_WINTER_MONTHS:
            side = before or after
            if len(side) >= 2:
                ref = v[side]
                if ref.max() - ref.min() <= jump / 2 and abs(v[k] - np.median(ref)) > jump:
                    drop.append(k)
    return df.drop(index=d.index[drop])


def harmonize_to_s2(df: pd.DataFrame) -> pd.DataFrame:
    """HLS NDVI rows mapped onto the Sentinel-2 L2A scale (see HLS_TRANSFER).

    Only NDVI is transferred -- the other indices have no fitted transfer and
    are left as HLS reads them. The untransformed values are kept in
    ``<stat>_raw`` columns. Rows from Sentinel-2 L2A pass through unchanged.
    """
    if "sensor" not in df or not df["sensor"].isin(HLS_TRANSFER).any():
        return df
    out = df.copy()
    for c in _STAT_COLS:
        out[f"{c}_raw"] = out[c]
    for sensor, (a, b) in HLS_TRANSFER.items():
        m = (out["sensor"] == sensor) & (out["index"] == "ndvi")
        for c in _STAT_COLS:
            out.loc[m, c] = a * out.loc[m, f"{c}_raw"] + b
        out.loc[m, "sd"] = abs(a) * out.loc[m, "sd"]
    return out


def extract_field_series(
    aoi: gpd.GeoDataFrame,
    start: str,
    end: str,
    indices: Sequence[str] | str = ("ndvi",),
    max_cloud: float = 70,
    min_valid: float = 0.75,
    workers: int = 8,
    refresh: bool = False,
    only_cached: bool = False,
    progress: Progress = None,
    source: str = "sentinel2",
    harmonize: bool = True,
) -> pd.DataFrame | None:
    """Year-round index statistics for a field.

    ``max_cloud`` is deliberately loose: winter scenes are often flagged cloudy
    over the tile while the field itself is clear, and those off-season
    observations are exactly what cover crop detection needs.

    ``only_cached=True`` returns ``None`` on a cache miss instead of computing,
    so a UI can open a pre-computed field without kicking off a long read.

    ``source`` is ``"sentinel2"`` (the original, 10 m) or ``"hls"`` (Sentinel-2
    and Landsat harmonised, 30 m) -- see imagery.SOURCES. Each row's ``sensor``
    says which instrument it came from. With ``harmonize`` (the default),
    HLS NDVI is mapped onto the Sentinel-2 scale -- see HLS_TRANSFER; turn it
    off only to inspect raw HLS values.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    if isinstance(indices, str):
        indices = [indices]
    indices = list(indices)

    # The source joins the key only when it is not the original, so every
    # Sentinel-2 series cached before HLS existed is still found.
    # "hls", 2: second HLS read, with non-positive reflectance masked.
    extra = () if source == "sentinel2" else (source, 2)
    key = cache_key(aoi, start, end, indices, max_cloud, min_valid, "field_series_v3",
                    *extra)
    if not refresh:
        hit = cache_get(key, "series")
        if hit is not None:
            return _hls_post(hit) if harmonize else hit
    if only_cached:
        return None

    bands = bands_for(indices)
    scenes = search_scenes(aoi, start, end, max_cloud=max_cloud, source=source)
    n_raw = len(scenes)
    groups = scene_groups(scenes, aoi)
    if n_raw > len(groups):
        print(f"  {n_raw - len(groups)} duplicate same-date scenes deferred "
              "(used only if the preferred one has no data).", flush=True)
    total = len(groups)
    print(f"  Extracting {total} dates across {workers} threads...", flush=True)

    rows: list[dict] = []
    errors: list[str] = []
    n_cloudy = 0

    def one(group: list[Scene]) -> tuple[str, list[dict] | str]:
        """Read one date, trying its candidate scenes in preference order.

        Returns a status so that 'too cloudy' and 'the read failed' can be told
        apart -- silently treating a network failure as cloud would quietly thin
        the series with no sign anything was wrong.
        """
        last_err = None
        for scene in group:
            try:
                sd = read_scene(scene, aoi, bands=bands, mask_clouds=True, clip=True)
            except Exception as exc:                  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
                continue
            vf = sd.valid_fraction
            if vf < min_valid:
                # Could be genuine cloud, or a granule that is nodata over this
                # field despite its footprint claiming to cover it. Either way
                # the next candidate for this date is worth trying.
                continue
            out = []
            for name in indices:
                vals = compute_index(sd.bands, name)
                v = vals[np.isfinite(vals)]
                if v.size == 0:
                    continue
                out.append({
                    "date": sd.date, "index": name,
                    "mean": float(v.mean()), "median": float(np.median(v)),
                    "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
                    "p10": float(np.percentile(v, 10)),
                    "p90": float(np.percentile(v, 90)),
                    "n_pixels": int(v.size), "valid_frac": float(vf),
                    "cloud": float(sd.cloud), "scene_id": sd.scene_id,
                    "sensor": sensor_of(scene.item),
                })
            if out:
                return "ok", out
        return ("error", last_err) if last_err else ("cloudy", [])

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, g): g for g in groups}
        for fut in as_completed(futures):
            status, payload = fut.result()
            if status == "ok":
                rows.extend(payload)
            elif status == "cloudy":
                n_cloudy += 1
            else:
                errors.append(payload)
            done += 1
            if progress and (done % max(1, workers) == 0 or done == total):
                progress(done, total, f"Reading imagery: scene {done} of {total}")

    if errors:
        print(f"  WARNING: {len(errors)} of {total} scenes failed to read and were "
              f"dropped. First error: {errors[0]}", flush=True)

    if not rows:
        raise RuntimeError(
            f"No scenes passed the quality filter between {start} and {end}. "
            f"{n_cloudy} were too cloudy over the field and {len(errors)} failed "
            "to read. Try raising max_cloud or lowering min_valid."
        )

    df = pd.DataFrame(rows)
    # Belt and braces: dedupe_scenes should have removed same-date duplicates
    # already, but a duplicate here would double-weight that date in the spline.
    df = (df.sort_values(["index", "date", "valid_frac", "cloud"],
                         ascending=[True, True, False, True])
            .drop_duplicates(["index", "date"])
            .sort_values(["index", "date"])
            .reset_index(drop=True))
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["doy"] = df["date"].dt.dayofyear

    print(f"  Kept {df['date'].nunique()} of {total} scenes ({len(df)} observations).", flush=True)
    cache_put(key, df, "series")      # raw: the transfer is applied on the way out
    return _hls_post(df) if harmonize else df


def _hls_post(df: pd.DataFrame) -> pd.DataFrame:
    """Transfer to the Sentinel-2 scale, then drop spikes -- HLS series only.

    Applied on the way out of the cache, so the cached series stays raw and
    either step can be refined without re-reading imagery.
    """
    if "sensor" not in df or not df["sensor"].isin(HLS_TRANSFER).any():
        return df
    return despike(harmonize_to_s2(df)).reset_index(drop=True)
