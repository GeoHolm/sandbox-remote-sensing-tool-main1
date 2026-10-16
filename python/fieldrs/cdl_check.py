"""Does the NDVI curve contradict the CDL label? A per-season flag.

WHY A FLAG AND NOT A CORRECTION
Crops cannot be told apart by how green they get: across the field library
corn, soybeans, rice and peanuts all peak at NDVI 0.85-0.93, and cotton and
peanuts also peak within days of each other with the same season length. So
the curve cannot say which crop it was. It can say when the label cannot be
right -- a summer crop with no summer canopy, a winter grain with no spring
canopy, a "cotton" harvested in June -- and that is all this module reports.
CDL stays the label; the flag says the season deserves a look. Ground truth
(the grower survey) decides which was wrong.

THE RULES, in order (the first that applies wins)
- winter grain label (WINTER_CROPS), but the winter model found no spring canopy
- fallow label, but the summer model found a canopy
- summer row-crop label (SUMMER_ROW_CROPS), but no summer canopy at all
- annual crop label, but green all year (the perennial test in phenology)
- hay or alfalfa label (FORAGE_CROPS), but an annual curve with a bare-soil
  period: reseeded, rotated, or a CDL error
- summer row-crop label, but planted before SUMMER_EARLIEST_PLANTING or
  harvested before SUMMER_EARLIEST_HARVEST: a winter or spring grain's season

Each gives ``cdl_flag_kind = "contradicts"``. Separately, a season whose CDL
dominant crop covers less than MIXED_PCT of the field gets ``"mixed"``: the
curve is a blend of what grows in the boundary, so it cannot confirm the label
either way. A contradiction outranks mixed.

ON THE LIBRARY (17 fields, 2020-2026)
The early-season rule fires once, on Mitchell Co. conventional 2022 "Cotton"
(harvest dated 25 June); the earliest legitimate summer-crop harvest was corn
in mid-July and the earliest planting cotton on 16 March. The hay rule fires
on the Washington pivot in 2022 and 2023, around the stand being removed and
reseeded; the fallow rule on one Lubbock season. Nothing here is checked
against grower records yet.

Port: r/R/cdl_check.R. Keep the two in step.
"""

from __future__ import annotations

import pandas as pd

from .forage import FORAGE_CROPS
from .phenology import FALLOW_CROPS, WINTER_CROPS

# Summer row crops whose calendar the early-season rule can judge. Double-crop
# labels are left out on purpose: they include a winter grain by definition.
SUMMER_ROW_CROPS = ("Corn", "Soybeans", "Cotton", "Peanuts", "Rice", "Sorghum",
                    "Sunflower", "Dry Beans")

# Earliest plausible dates for a summer row crop anywhere in CONUS. Generous on
# purpose -- a flag should mean "this cannot be that crop", not "unusual".
SUMMER_EARLIEST_PLANTING = "03-01"
SUMMER_EARLIEST_HARVEST = "07-01"

# Below this dominant-crop share (%) the curve is a blend of the boundary.
MIXED_PCT = 75.0


def _flag(row: pd.Series, pct: float | None) -> tuple[str | None, str | None]:
    crop = row.get("crop")
    crop = crop if isinstance(crop, str) and crop else None
    conf = str(row.get("confidence") or "")
    stype = str(row.get("season_type") or "")
    if crop is None:
        return None, None
    y = int(row["year"])
    plant, harv = row.get("planting_est"), row.get("harvest_est")

    if crop in WINTER_CROPS and conf.startswith("no winter crop"):
        return "contradicts", (f"CDL says {crop}, but there is no spring canopy -- "
                               "failed, not sown, or a CDL error")
    if crop in FALLOW_CROPS and "NDVI shows a summer canopy" in conf:
        return "contradicts", (f"CDL says {crop}, but a summer canopy grew -- "
                               "weeds, a crop, or a CDL error")
    if crop in SUMMER_ROW_CROPS and conf.startswith("no summer crop"):
        return "contradicts", (f"CDL says {crop}, but there is no summer canopy -- "
                               "failed, not planted, or a CDL error")
    if (crop not in FORAGE_CROPS and crop not in FALLOW_CROPS
            and conf.startswith("not an annual row crop")):
        return "contradicts", (f"CDL says {crop}, but the field is green all year -- "
                               "a perennial or hay stand, or a CDL error")
    if crop in FORAGE_CROPS and stype == "summer" and pd.notna(plant):
        return "contradicts", (f"CDL says {crop}, but the curve has a bare-soil period "
                               "and a single season -- reseeded, rotated, or a CDL error")
    if crop in SUMMER_ROW_CROPS and stype == "summer":
        if pd.notna(plant) and pd.Timestamp(plant) < pd.Timestamp(f"{y}-{SUMMER_EARLIEST_PLANTING}"):
            return "contradicts", (f"CDL says {crop}, but the season starts "
                                   f"{pd.Timestamp(plant):%d %b} -- too early for it; "
                                   "a winter or spring grain's calendar")
        if pd.notna(harv) and pd.Timestamp(harv) < pd.Timestamp(f"{y}-{SUMMER_EARLIEST_HARVEST}"):
            return "contradicts", (f"CDL says {crop}, but the season ends "
                                   f"{pd.Timestamp(harv):%d %b} -- too early for it; "
                                   "a winter or spring grain's calendar")
    if pct is not None and pd.notna(pct) and pct < MIXED_PCT:
        return "mixed", (f"CDL {crop} covers only {pct:.0f}% of the field -- the curve "
                         "blends what grows in the boundary and cannot confirm the label")
    return None, None


def cdl_check(phen: pd.DataFrame | None,
              history: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """``phen`` with ``cdl_flag_kind`` ("contradicts", "mixed" or None) and
    ``cdl_flag`` (the reason) added. ``history`` supplies the dominant-crop
    share for the mixed check; without it only contradictions are reported."""
    if phen is None or not len(phen):
        return phen
    pct = (history.set_index("year")["pct"].to_dict()
           if history is not None and "pct" in history else {})
    out = phen.copy()
    res = [_flag(r, pct.get(int(r["year"]))) for _, r in out.iterrows()]
    out["cdl_flag_kind"] = [k for k, _ in res]
    out["cdl_flag"] = [t for _, t in res]
    return out
