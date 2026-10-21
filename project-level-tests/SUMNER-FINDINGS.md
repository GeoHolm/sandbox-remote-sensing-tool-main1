# Hyper-local benchmark: one field against 100 neighbors

Sumner County, Kansas. A focus field and the 100 nearest qualifying cropland
fields, all read from free satellite imagery, 2022–2026. 101 fields, 0
failures, 277 minutes.

The question: does the focus field sit with its neighbors, above them, or
below, on soil armor and on cover cropping?

> **Update, 20 October 2026.** This study has since been repeated in
> Champaign County, Illinois and Mitchell County, Georgia. Two conclusions
> below are narrower than they look: the crop-bias problem that forces
> stratification is specific to winter-cereal country — neither of the other
> counties grows a winter crop at all — and so is the finding that armor
> restates off-season greenness (r falls from 0.91 here to 0.38 in Illinois).
> See [`COUNTY-COMPARISON.md`](COUNTY-COMPARISON.md).

## Short answer

**On soil armor it has no settled position** — 4th percentile in 2022, 80th
in 2024, 64th in 2025, mean 49. Whatever the pipeline is measuring year to
year, it is not a stable property of this field.

**On off-season cover it is genuinely low** — 13th percentile of 101 fields
on the continuous measure, 0.286 mean off-season peak NDVI against a cohort
median of 0.448. That ranking holds whether or not a threshold is applied.

**And the benchmark itself needs a correction before it is used.** Raw armor
in this county ranks cropping systems, not management.

## Where the fields came from

| | |
|---|---|
| Source | USDA FSA Common Land Unit, public release 2008-02-04 |
| County | Sumner County, Kansas |
| CLU polygons | 25,576 |
| After 40–400 acres and Polsby-Popper > 0.35 | 4,840 |
| After CDL cropland at ≥60% purity in ≥3 of 2022–2025 | **3,610** |
| Cohort | the 100 nearest, which lands at a 4.3 km radius |

Public CLU carries geometry and acreage only — every identifying attribute
was stripped before release, so nothing here traces to a farm. The boundaries
are an 18-year-old snapshot; the purity filter doubles as a staleness check,
since a field since split or converted shows low purity and drops out.

CDL was screened against the local bulk store with one windowed read per
year. Per-field CropScape calls would have been about 100,000 requests.

**Focus field:** 168 acres at −97.6172, 37.2311, picked as the qualifying
field with the densest qualifying neighborhood. Corn (2022) → Winter Wheat
(2023) → Wheat/Soybean double crop (2024) → Cotton (2025), 94–99% purity.
It is larger than the cohort median of 78 acres.

## Finding 1: raw armor cannot be ranked here

The pre-planting armor window runs from last harvest to this planting. On a
winter wheat field that window contains a **living cash crop**:

| Stratum | field-years | median armor | median living cover (`f_pv`) |
|---|---|---|---|
| Summer-only rotation | 168 | 0.364 | 0.046 |
| Winter crop in the window | 227 | **0.759** | **0.455** |

A 0.395 gap in armor, with ten times the living cover. The focus field's own
2024 reading of 0.884 is 71% living cover — standing wheat before the soybean
double crop, not conservation.

Over half this cohort grows wheat or a wheat double crop. Sorting 101 fields
by raw armor sorts them by cropping system and hands "best armored" to
whoever grows the most wheat. **Every comparison here is therefore made
within stratum**, and the stratum gap is reported rather than hidden.

## Finding 2: the focus field has no settled armor position

Against peers in the same stratum and the same year:

| Year | Crop | Stratum | Armor | Peer median | Percentile | n peers |
|---|---|---|---|---|---|---|
| 2022 | Corn | summer only | 0.191 | 0.421 | **4** | 49 |
| 2024 | Dbl Crop WinWht/Soybeans | winter crop | 0.884 | 0.798 | **80** | 50 |
| 2025 | Cotton | summer only | 0.391 | 0.334 | **64** | 44 |

Mean 49 — dead average, by way of near-bottom and near-top. 2023 produced no
reading at all (2 usable observations in the window), and 2026 is excluded
because CDL has not published, so this rests on three field-years against a
cohort median of four.

One caution on the 2022 reading: it came from a 5-observation window, and
across the whole cohort the thinnest windows skew low (median armor 0.483 at
≤5 observations against 0.66–0.67 above that). The 4th percentile is probably
partly an artifact of a thin window.

## Finding 3: off-season cover — low, and the ranking survives the threshold

Of 404 winters, **221 (55%) can be scored at all**. The rest are winter cash
crops, which the pipeline correctly declines to call cover crops either way.

| Verdict | winters |
|---|---|
| winter cash crop, not a cover crop | 183 |
| no cover crop detected | 86 |
| likely cover crop | 75 |
| green cover — cover crop or small grain | 33 |
| possible cover crop | 27 |

The focus field: **0 of its 2 askable winters positive**, against a cohort
median of 67%. Tenth percentile.

But that label is fragile. Its two winters peak at **0.296 and 0.277** NDVI,
against a 0.30 threshold — it is classified bare by 0.004. And the threshold
moves everything:

| Threshold | winters positive | fields with any |
|---|---|---|
| 0.26 | 190 of 221 (86%) | 99 of 101 |
| **0.30** (default) | 135 (61%) | 90 |
| 0.35 | 108 (49%) | 82 |
| 0.40 | 90 (41%) | 76 |

So the yes/no verdict should not be the benchmark. **Drop the threshold and
rank the continuous measure instead:**

- focus mean off-season peak NDVI: **0.286**
- cohort median: 0.448 (p25 0.346, p75 0.556)
- focus percentile: **13**

The ranking survives. The focus field really is at the low end of its
neighborhood for off-season green — it is the *label* "no cover crop" that
rests on four thousandths of an index, not the position.

A caveat that cuts the other way: the positives have a median peak NDVI of
0.49 and a p10 of 0.32, so many sit just above the line. In a county where
volunteer wheat after harvest is routine, some unknown share of the cohort's
"cover" is volunteer rather than planted. Nothing here separates the two, and
that is the same false-positive risk the Georgia validation found.

## Finding 4: armor is largely a restatement of off-season greenness

| Fit | n | slope | r |
|---|---|---|---|
| All field-years | 294 | 0.940 | **0.91** |
| Summer-only rotations | 118 | 0.590 | 0.60 |

The 0.91 is inflated by the two strata sitting at opposite ends of both axes.
Within summer-only rotations it falls to 0.60 — real, but far from
independent information. For practical purposes the armor index here is
re-measuring winter NDVI with extra steps, which echoes the validation
against 347 farmer-reported field-years where armor's apparent tillage signal
ran almost entirely through cover crop adoption.

**The focus field's residual from the cohort's fitted line is +0.081**, i.e.
slightly more armor than its off-season greenness predicts. It rests on two
points. It is not evidence of anything and should not be quoted.

## What this says about the hyper-local benchmark idea

The concept works, with three corrections:

1. **Stratify by cropping system, always.** Without it the ranking is a crop
   ranking. In a mixed county this is not a refinement, it is the difference
   between a result and an artifact.
2. **Benchmark continuous measures, not thresholded verdicts.** The yes/no
   cover-crop call moved the focus field's standing by a rounding error; the
   continuous rank did not move at all.
3. **Expect thin evidence per field.** Median 4 usable armor years and 2
   askable winters per field over five years. A single field against 100
   neighbors is a weak test; the cohort is well measured, the individual is
   not.

Honest summary for this field: **average on armor once you control for what
it grew, and in the bottom sixth of its neighborhood for off-season cover.**
The second is the finding worth acting on, and it is the one that does not
depend on a threshold.

## What has not been established

- **No ground truth.** No grower record, for this field or any other in the
  cohort. Nothing here has been checked against what was actually done.
- **Armor is a cover metric, not a tillage metric** — the share of ground
  covered by anything, living or residue.
- **Volunteer versus planted cover is not separable** from NDVI alone, and
  this is a wheat-stubble county.
- **Boundaries are from 2008.** The purity filter removes the worst of the
  drift but cannot fix a field that was split along a line CDL still reads as
  uniform.
- **The focus field is one field**, 168 acres against a cohort median of 78.

## Files

| | |
|---|---|
| `select_cohort.py` | filters CLU, screens CDL, picks focus + cohort |
| `run_cohort.py` | the pipeline pass, resumable, `residue=True` |
| `analyse_cohort.py` | the stratified benchmark |
| `figures_cohort.py` | figures 02–05; `--bare` for slides |
| `figure_cohort_map.py` | the cohort map (needs the network) |
| `sumner-ks/cohort.csv` | the 101 fields, with CDL rotation and distance |
| `sumner-ks/armor_scored.csv` | armor by field-year, with stratum |
| `sumner-ks/focus_vs_cohort_armor.csv` | the percentile table above |
| `sumner-ks/cover_by_field.csv` | askable winters and positives per field |

Boundaries are not committed: `project-level-tests/*/boundaries/` is
gitignored, as for the other project tests. Re-run `select_cohort.py`
against the CLU shapefile to regenerate them.
