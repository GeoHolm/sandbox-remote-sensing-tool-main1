"""Spectral indices.

This is the "try a different algorithm" surface. An index is a function of a
dict of reflectance arrays. Register one with :func:`add_index` and everything
downstream picks it up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

BandDict = dict[str, np.ndarray]


@dataclass(frozen=True)
class Index:
    name: str
    fn: Callable[[BandDict], np.ndarray]
    bands: tuple[str, ...]
    vmin: float = -1.0
    vmax: float = 1.0
    desc: str = ""


INDICES: dict[str, Index] = {}


def add_index(name: str, fn: Callable[[BandDict], np.ndarray], bands,
              vmin: float = -1.0, vmax: float = 1.0, desc: str = "") -> str:
    INDICES[name] = Index(name, fn, tuple(bands), vmin, vmax, desc)
    return name


def bands_for(names) -> list[str]:
    """Bands needed by a set of indices, so each is fetched once."""
    if isinstance(names, str):
        names = [names]
    unknown = [n for n in names if n not in INDICES]
    if unknown:
        raise KeyError(
            f"Unknown index/indices: {', '.join(unknown)}. "
            f"Registered: {', '.join(sorted(INDICES))}"
        )
    out: list[str] = []
    for n in names:
        for b in INDICES[n].bands:
            if b not in out:
                out.append(b)
    return out


def compute_index(bands: BandDict, name: str = "ndvi") -> np.ndarray:
    """Evaluate an index over a dict of band arrays."""
    if name not in INDICES:
        raise KeyError(
            f"Unknown index: {name}. Registered: {', '.join(sorted(INDICES))}"
        )
    spec = INDICES[name]
    missing = [b for b in spec.bands if b not in bands]
    if missing:
        raise KeyError(
            f"Index '{name}' needs band(s) not loaded: {', '.join(missing)}. "
            f"Have: {', '.join(bands)}"
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        return spec.fn({b: bands[b] for b in spec.bands})


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    out = np.divide(num, den, out=np.full_like(num, np.nan, dtype="float32"),
                    where=den != 0)
    return out


# ------------------------------------------------------------ built-ins ---

add_index("ndvi", lambda b: _safe_div(b["nir"] - b["red"], b["nir"] + b["red"]),
          ["nir", "red"], -0.2, 1.0,
          "Normalised Difference Vegetation Index. The workhorse. Saturates over dense canopy.")

add_index("evi2", lambda b: 2.5 * _safe_div(b["nir"] - b["red"], b["nir"] + 2.4 * b["red"] + 1),
          ["nir", "red"], -0.2, 1.2,
          "Two-band EVI. Keeps responding after NDVI saturates; no blue band needed.")

add_index("ndwi", lambda b: _safe_div(b["green"] - b["nir"], b["green"] + b["nir"]),
          ["green", "nir"], -1.0, 1.0,
          "McFeeters NDWI. Surface water; positive over open water.")

add_index("ndmi", lambda b: _safe_div(b["nir"] - b["swir16"], b["nir"] + b["swir16"]),
          ["nir", "swir16"], -1.0, 1.0,
          "Normalised Difference Moisture Index. Canopy water content / drought stress.")

# --- residue and tillage ---
# The three multispectral indices evaluated in Sonmez & Slater (2016). They are
# registered because the bands are already fetched and the arithmetic is
# trivial -- not because any is calibrated here. Two things to know first:
#
#   1. Soil moisture moves NDTI more than tillage does. On the Iowa field,
#      18 and 20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 --
#      a four-fold swing from rain, no change in residue. Single-date NDTI is
#      not usable; the validated approach is multitemporal (minNDTI over the
#      residue window, Zheng et al. 2013).
#   2. None of them separates residue from green vegetation. NDTI reads high
#      over a cover crop because green canopy absorbs in the SWIR. Restrict to
#      low-NDVI dates -- see residue_window() in phenology.py.
#
# CAI, the hyperspectral index that paper found best, cannot be computed from
# Sentinel-2: it needs three narrow bands inside the 2000-2200 nm cellulose
# feature and B12 is one 180 nm-wide band covering all of it.

add_index("ndti", lambda b: _safe_div(b["swir16"] - b["swir22"], b["swir16"] + b["swir22"]),
          ["swir16", "swir22"], -0.2, 0.6,
          "Normalised Difference Tillage Index. Crop residue cover -- conservation tillage.")

add_index("ndi7", lambda b: _safe_div(b["nir"] - b["swir22"], b["nir"] + b["swir22"]),
          ["nir", "swir22"], -1.0, 1.0,
          "Normalised Difference Index 7. Residue against bare soil; reported alongside NDTI.")

add_index("ndsvi", lambda b: _safe_div(b["swir16"] - b["red"], b["swir16"] + b["red"]),
          ["swir16", "red"], -1.0, 1.0,
          "Normalised Difference Senescent Vegetation Index. Standing senesced material.")

add_index("ndre", lambda b: _safe_div(b["nir"] - b["rededge1"], b["nir"] + b["rededge1"]),
          ["nir", "rededge1"], -0.2, 1.0,
          "Normalised Difference Red Edge. More sensitive than NDVI in dense canopy.")

add_index("savi", lambda b: 1.5 * _safe_div(b["nir"] - b["red"], b["nir"] + b["red"] + 0.5),
          ["nir", "red"], -0.2, 1.2,
          "Soil Adjusted Vegetation Index (L=0.5). Damps soil background at low cover.")

add_index("gcvi", lambda b: _safe_div(b["nir"], b["green"]) - 1,
          ["nir", "green"], 0.0, 12.0,
          "Green Chlorophyll Vegetation Index. Tracks leaf chlorophyll; used in yield models.")


def list_indices() -> list[dict[str, str]]:
    return [
        {"index": k, "bands": ", ".join(v.bands), "desc": v.desc}
        for k, v in sorted(INDICES.items())
    ]
