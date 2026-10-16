"""Suspect NDVI observations: flagged, never removed.

WHAT THIS IS FOR
The cloud mask (Sentinel-2 SCL, HLS Fmask) misses some snow, thin cloud and
shadow, and a reading taken through them is false. This marks readings that look
like that, so a chart or a download can show them. It deletes nothing and
changes no season date, verdict or cut -- the analysis runs on every reading.

WHY NOT DELETE THEM
Tested on the field library (17 fields, 5,216 Sentinel-2 observations):
- The HLS spike filter (extract.despike) applied year-round would remove 87
  readings, 20 of them hay-cut troughs on the Washington pivot -- a single low
  reading between two full stands is exactly what a cut looks like.
- Distance from the fitted curve flags 9% of readings, mostly June-September:
  the fixed-stiffness smoother failing to follow real harvests and cuts, not
  bad data.
- Even a winter-only filter removed open water on the Arkansas rice field
  (NDVI -0.60 and -0.33), turning "off-season flooded -- cover crop not
  detectable" into "no cover crop detected", and shifted two planting dates by
  up to 7 days.

THE TEST
Same as extract.despike, so the two cannot disagree about what a spike is:
- two-sided: more than SPIKE_NDVI from the nearest reading on BOTH sides, in
  the same direction, both within SPIKE_DAYS;
- one-sided, November to March only: no neighbour within SPIKE_DAYS on one
  side, and more than SPIKE_NDVI from the median of at least two readings on
  the other side that agree to SPIKE_NDVI / 2.

PROTECTIONS -- never flagged
- water: a reading below CC_WATER_NDVI is open water, a real state (flooded
  rice, a wet fallow), whatever its neighbours read;
- hay cuts: in a year read as hay (forage.forage_years), nothing inside the
  cutting season (forage.CUT_SEASON) is flagged. A reading below its
  neighbours is a cut trough, and one above them is the regrown stand between
  two cuts (Washington pivot, 7 August 2021: 0.913 between cuts at 0.61 and
  0.81 -- real). A cloud dip there cannot be told from a cut.

Port: r/R/outliers.R. Keep the two in step.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .covercrop import CC_WATER_NDVI
from .extract import SPIKE_DAYS, SPIKE_NDVI, SPIKE_WINTER_MONTHS
from .forage import CUT_SEASON, forage_years


def _spikes(dates: np.ndarray, v: np.ndarray, months: np.ndarray,
            jump: float = SPIKE_NDVI, days: int = SPIKE_DAYS) -> dict[int, tuple[str, int]]:
    """Position -> (reason, direction) for every spike, by extract.despike's rules.
    direction is +1 for a reading above its neighbours, -1 below."""
    gap = np.timedelta64(days, "D")
    out = {}
    for k in range(len(v)):
        before = [j for j in range(k - 1, -1, -1) if dates[k] - dates[j] <= gap]
        after = [j for j in range(k + 1, len(v)) if dates[j] - dates[k] <= gap]
        if before and after:
            dp, dn = v[k] - v[before[0]], v[k] - v[after[0]]
            if dp > jump and dn > jump:
                out[k] = ("spike above both neighbours", 1)
            elif dp < -jump and dn < -jump:
                out[k] = ("dip below both neighbours", -1)
        elif months[k] in SPIKE_WINTER_MONTHS:
            side = before or after
            if len(side) >= 2:
                ref = v[side]
                if ref.max() - ref.min() <= jump / 2 and abs(v[k] - np.median(ref)) > jump:
                    d = 1 if v[k] > np.median(ref) else -1
                    out[k] = ("winter reading off a steady run of neighbours", d)
    return out


def flag_outliers(ts: pd.DataFrame, phen: pd.DataFrame | None = None,
                  index: str = "ndvi") -> pd.DataFrame:
    """``ts`` with ``suspect`` (bool) and ``suspect_reason`` added to the
    ``index`` rows (other indices get False / None). Nothing is removed."""
    out = ts.copy()
    out["suspect"] = False
    out["suspect_reason"] = None
    d = out[out["index"] == index].sort_values("date")
    if len(d) < 3:
        return out
    dates = d["date"].to_numpy()
    v = d["mean"].to_numpy(dtype=float)
    months = d["date"].dt.month.to_numpy()
    md = d["date"].dt.strftime("%m-%d").to_numpy()
    years = d["date"].dt.year.to_numpy()
    hay = set(forage_years(phen))
    for k, (reason, direction) in _spikes(dates, v, months).items():
        if v[k] < CC_WATER_NDVI:
            continue                                  # open water is real
        if int(years[k]) in hay and CUT_SEASON[0] <= md[k] <= CUT_SEASON[1]:
            continue                                  # a cut, or regrowth between cuts
        i = d.index[k]
        out.at[i, "suspect"] = True
        out.at[i, "suspect_reason"] = reason
    return out
