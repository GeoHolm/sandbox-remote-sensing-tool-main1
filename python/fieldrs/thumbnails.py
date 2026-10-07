"""Contact sheets: every scene in a period, side by side.

Port of R/thumbnails.R. Picking one scene at a time from a list of several
hundred is no way to look at imagery; a month or a quarter rendered as a grid
shows the field changing, and shows at a glance which dates were actually
usable.

Scene reads run on a thread pool -- same rationale as extract.py: the work is
network-bound and GDAL releases the GIL during HTTP.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date as Date
from typing import Callable

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np

from .imagery import Scene, dedupe_scenes, read_scene
from .viz import VEG_PALETTE

Progress = Callable[[int, int, str], None] | None


def _period_key(d: Date, period: str) -> str:
    if period == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return f"{d.year}-{d.month:02d}"


def available_periods(scenes: list[Scene], period: str = "month") -> list[str]:
    """Every period present in a scene list, newest first."""
    return sorted({_period_key(s.date, period) for s in scenes}, reverse=True)


def scenes_in_period(scenes: list[Scene], key: str, aoi: gpd.GeoDataFrame,
                     period: str = "month") -> list[Scene]:
    """Scenes falling in a given period, one per date (best candidate)."""
    in_period = [s for s in scenes if _period_key(s.date, period) == key]
    return dedupe_scenes(in_period, aoi)


# ---------------------------------------------------------------- grid ---

@dataclass
class GridCell:
    date: Date
    cloud: float
    valid: float
    arr: np.ndarray          # HxWx3 (rgb/fc) or HxW (ndvi), or None on failure
    status: str = "ok"
    error: str | None = None


# Views that are one index per pixel rather than three reflectance bands.
INDEX_VIEWS = ("ndvi", "armor")


def _bands_for_view(view: str) -> list[str]:
    return {"ndvi": ["red", "nir"], "fc": ["green", "red", "nir"],
            "armor": ["red", "nir", "swir16", "swir22"]}.get(view, ["blue", "green", "red"])


def _downsample(arr: np.ndarray, max_px: int) -> np.ndarray:
    """Block-mean downsample so the longest edge is roughly max_px.

    A contact-sheet cell is ~180 px; shipping full resolution back would be
    wasted memory. Pads to a multiple of the block factor before reshaping so
    this works for any input shape, not just evenly-divisible ones.
    """
    h, w = arr.shape[:2]
    f = max(1, int(np.ceil(max(h, w) / max_px)))
    if f == 1:
        return arr
    ph, pw = (-h) % f, (-w) % f
    pad_width = [(0, ph), (0, pw)] + [(0, 0)] * (arr.ndim - 2)
    padded = np.pad(arr, pad_width, constant_values=np.nan)
    nh, nw = padded.shape[0] // f, padded.shape[1] // f
    shape = (nh, f, nw, f) + padded.shape[2:]
    reshaped = padded.reshape(shape)
    with np.errstate(invalid="ignore"):
        return np.nanmean(reshaped, axis=(1, 3))


def build_scene_grid(scenes: list[Scene], aoi: gpd.GeoDataFrame, view: str = "rgb",
                     max_px: int = 180, workers: int = 6,
                     progress: Progress = None) -> list[GridCell]:
    """Read a set of scenes as small arrays ready for a contact sheet."""
    bands = _bands_for_view(view)

    def one(scene: Scene) -> GridCell:
        try:
            sd = read_scene(scene, aoi, bands=bands, mask_clouds=True, clip=True, buffer_m=30)
            valid = sd.valid_fraction
            if view == "ndvi":
                with np.errstate(divide="ignore", invalid="ignore"):
                    v = (sd.bands["nir"] - sd.bands["red"]) / (sd.bands["nir"] + sd.bands["red"])
                arr = _downsample(v, max_px)
            elif view == "armor":
                # Soil armor per pixel: 1 - bare soil from the same NDVI-DFI
                # unmixing as the Soil armor tab (port of the R view).
                from .armor import cover_fractions
                arr = _downsample(1.0 - cover_fractions(sd.bands)["bs"], max_px)
            else:
                order = ["nir", "red", "green"] if view == "fc" else ["red", "green", "blue"]
                stacked = np.stack([sd.bands[b] for b in order], axis=-1)
                arr = _downsample(stacked, max_px)
            return GridCell(date=scene.date, cloud=scene.cloud, valid=valid, arr=arr)
        except Exception as exc:                       # noqa: BLE001
            return GridCell(date=scene.date, cloud=scene.cloud, valid=0.0, arr=None,
                            status="error", error=f"{type(exc).__name__}: {exc}")

    results: list[GridCell] = []
    total = len(scenes)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, s): s for s in scenes}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if progress:
                progress(done, total, f"Loading scene {done} of {total}")

    ok = [r for r in results if r.status == "ok"]
    ok.sort(key=lambda r: r.date)
    return ok


# ------------------------------------------------------------ rendering ---

def _grid_limits(view: str) -> tuple[float, float]:
    """Fixed reflectance range per view -- see thumbnails.R for why fixed
    beats per-image or per-band adaptive stretching for a comparable grid."""
    return (0, 0.45) if view == "fc" else (0, 0.30)


def _cell_to_rgb(arr: np.ndarray, view: str, gamma: float = 0.8) -> np.ndarray:
    if view in INDEX_VIEWS:
        lo = -0.2 if view == "ndvi" else 0.0     # armor: 0 bare .. 1 covered
        norm = np.clip((arr - lo) / (1 - lo), 0, 1)
        rgb = VEG_PALETTE(norm)[..., :3]
        rgb[~np.isfinite(arr)] = 0.93
        return rgb
    lo, hi = _grid_limits(view)
    chans = [np.clip((arr[..., k] - lo) / (hi - lo), 0, 1) ** gamma for k in range(3)]
    out = np.stack(chans, axis=-1)
    na = ~np.isfinite(arr).all(axis=-1)
    out[na] = 0.92
    return out


def plot_scene_grid(grid: list[GridCell], view: str = "rgb", ncol: int | None = None,
                    title: str | None = None):
    """Draw a contact sheet from build_scene_grid()'s output."""
    if not grid:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "No scenes in this period", ha="center", va="center")
        ax.axis("off")
        return fig

    n = len(grid)
    nc = ncol or min(6, int(np.ceil(np.sqrt(n) * 1.3)))
    nr = int(np.ceil(n / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(2.2 * nc, 2.5 * nr))
    axes = np.atleast_2d(axes)

    for i, cell in enumerate(grid):
        ax = axes[i // nc][i % nc]
        ax.imshow(_cell_to_rgb(cell.arr, view))
        ax.set_title(cell.date.strftime("%d %b"), fontsize=9)
        ax.text(0.5, -0.08, f"{cell.valid * 100:.0f}% clear | tile {cell.cloud:.0f}% cloud",
               transform=ax.transAxes, ha="center", fontsize=6.5, color="#595959")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor("#d9d9d9")

    for i in range(n, nr * nc):
        axes[i // nc][i % nc].axis("off")

    if title:
        fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig
