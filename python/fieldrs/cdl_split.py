"""Is this boundary one management unit?

Everything downstream averages NDVI over whatever the boundary contains. If a
boundary spans two fields farmed differently, the season curve is a blend of two
crops and the planting date belongs to neither. CDL catches that without a field
visit: if the same sub-area disagrees with the rest year after year, it is being
managed separately.

The test is persistence, not disagreement in any single year. One year of
disagreement is usually classification noise along the edges; the same block
disagreeing in four years out of six is a second field.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import numpy as np
import pandas as pd
from scipy import ndimage

from .cropland import CDL_NONCROP, CdlStack, cdl_name, cdl_summary

# A flagged region must be this big to be worth acting on, as a share of the
# field and in absolute terms. Below this it is edge noise or a farmstead.
SPLIT_MIN_FRAC = 0.12
SPLIT_MIN_HA = 2.0
SPLIT_PERSIST = 0.60        # share of years a pixel must disagree


@dataclass
class SplitAdvice:
    verdict: str            # "single unit" | "split" | "trim"
    headline: str
    detail: str
    per_year: pd.DataFrame
    flag_classes: pd.DataFrame | None
    frac: float
    area_ha: float
    biggest_ha: float
    mean_pct: float
    years: list[int]
    persist: np.ndarray = dc_field(repr=False, default=None)
    flagged: np.ndarray = dc_field(repr=False, default=None)


def cdl_split_advice(stack: CdlStack) -> SplitAdvice:
    """Assess whether a boundary should be split, trimmed, or left alone."""
    px_ha = stack.pixel_ha
    n_yr = len(stack.years)

    per_year = []
    doms: list[int] = []
    for y in stack.years:
        s = cdl_summary(stack.year(y), px_ha)
        doms.append(int(s.code[0]))
        per_year.append({
            "year": y, "dominant": s.crop[0], "pct": float(s.pct[0]),
            "n_classes": len(s),
            "noncrop_pct": float(s.loc[~s.is_crop, "pct"].sum()),
        })
    per_year = pd.DataFrame(per_year)

    # Disagreement with each year's own dominant class, then how persistent it is.
    vals = stack.data                                  # (n_yr, h, w)
    dis = np.where(np.isfinite(vals),
                   (vals != np.asarray(doms)[:, None, None]).astype("float32"),
                   np.nan)
    with np.errstate(invalid="ignore"):
        obs = np.isfinite(dis).sum(axis=0)
        persist = np.where(obs > 0, np.nansum(dis, axis=0) / np.maximum(obs, 1), np.nan)

    flagged = np.isfinite(persist) & (persist >= SPLIT_PERSIST)
    n_flag = int(flagged.sum())
    n_field = int(np.isfinite(persist).sum())
    frac = n_flag / n_field if n_field else 0.0
    area_ha = n_flag * px_ha

    # Largest contiguous block, so a scatter of stray pixels is not mistaken
    # for a second field.
    biggest_ha = 0.0
    if n_flag:
        # 8-connectivity, matching terra::patches(directions = 8) in the R
        # version. scipy's default is 4-connectivity, which would split a
        # diagonally-joined block into two and understate the largest patch.
        structure = np.ones((3, 3), dtype=int)
        lab, n_lab = ndimage.label(flagged, structure=structure)
        if n_lab:
            sizes = ndimage.sum_labels(flagged, lab, index=range(1, n_lab + 1))
            biggest_ha = float(sizes.max()) * px_ha

    flag_classes = None
    noncrop_share = 0.0
    if n_flag:
        sel = vals[:, flagged]
        v = sel[np.isfinite(sel)].astype("int32")
        if v.size:
            codes, counts = np.unique(v, return_counts=True)
            flag_classes = pd.DataFrame({
                "code": codes.astype(int),
                "crop": [cdl_name(int(c)) for c in codes],
                "pct": (100 * counts / counts.sum()).round(1),
            }).sort_values("pct", ascending=False).reset_index(drop=True)
            flag_classes["is_crop"] = ~flag_classes["code"].isin(CDL_NONCROP)
            noncrop_share = float(flag_classes.loc[~flag_classes.is_crop, "pct"].sum())

    mean_pct = round(float(per_year["pct"].mean()), 1)
    big_enough = frac >= SPLIT_MIN_FRAC and biggest_ha >= SPLIT_MIN_HA

    if not big_enough:
        verdict = "single unit"
        headline = (f"Looks like one management unit -- {mean_pct:.0f}% of the "
                    "boundary is the dominant crop on average.")
        detail = ("No sub-area disagrees with the rest of the field persistently "
                  "enough to suggest a second unit. Year-to-year variation is at "
                  "the scale of edge pixels, which is normal for a 30 m product "
                  "on a field boundary.")
    elif noncrop_share >= 60:
        top = ", ".join(flag_classes.loc[~flag_classes.is_crop, "crop"].head(2))
        verdict = "trim"
        headline = (f"Consider trimming the boundary -- {area_ha:.1f} ha "
                    f"({frac * 100:.0f}%) is persistently not cropland.")
        detail = (f"The flagged area is mostly {top}. That is farmstead, road, "
                  "water or woodland inside the boundary rather than a second "
                  "field. It drags field NDVI down all season; clipping it out "
                  "is worth more than splitting.")
    else:
        top = ", ".join(flag_classes.loc[flag_classes.is_crop, "crop"].head(2))
        verdict = "split"
        headline = (f"Consider splitting this boundary -- {area_ha:.1f} ha "
                    f"({frac * 100:.0f}%) is farmed differently, in most years.")
        detail = (f"A contiguous block of about {biggest_ha:.1f} ha carries a "
                  f"different crop from the rest in at least "
                  f"{SPLIT_PERSIST * 100:.0f}% of years -- mostly {top}. "
                  "Averaging NDVI across both means the season curve is a blend "
                  "of two crops, and the planting and harvest dates belong to "
                  "neither.")

    return SplitAdvice(verdict, headline, detail, per_year, flag_classes,
                       frac, area_ha, biggest_ha, mean_pct, list(stack.years),
                       persist, flagged)
