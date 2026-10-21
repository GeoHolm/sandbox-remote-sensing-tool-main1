# The hyper-local benchmark in three counties

Same method, same years, same filters, three rotations. 203 fields, 1,015
field-years, 0 failures.

| | Champaign, IL | Sumner, KS | Mitchell, GA |
|---|---|---|---|
| Rotation | corn / soybeans | winter wheat, double crop, milo, cotton | peanuts / cotton |
| Cohort | 50 fields in 2.5 km | 100 fields in 4.3 km | 50 fields in 3.9 km |
| Focus field | 79 ac, soy↔corn | 168 ac, corn→wheat→dbl→cotton | 160 ac, peanuts/cotton |
| Field-years with a winter crop | **0.0%** | **57.9%** | **0.5%** |
| Landscape | section grid, town, interstate | section grid, riparian corridor | wall-to-wall center pivots |

The runs took 77, 277 and 139 minutes. Mitchell is the slowest per field
(2.73 min) and Champaign the fastest (1.50).

## Finding 1: the crop-bias problem is a wheat-country problem

The Sumner study concluded that raw pre-plant armor "ranks cropping systems,
not management" — 2.73 standard deviations between winter-crop and
summer-only field-years. That conclusion does not generalize, and the reason
is simple: **neither of the other two counties grows a winter crop at all.**

Champaign has 0 winter-crop field-years out of 204. Mitchell has 1 out of
190. With one stratum there is no confound to correct, and the analysis now
says so explicitly rather than printing a gap computed from a handful of
rows.

So the stratification that dominated the Sumner write-up is **necessary in
wheat and double-crop country and irrelevant in the Corn Belt and the
southern peanut belt**. A production implementation should stratify where
the rotation calls for it, not everywhere.

The same qualification applies to "armor is largely a restatement of
off-season greenness". Correlation with off-season peak NDVI:

| | Champaign | Sumner | Mitchell |
|---|---|---|---|
| `preplant` | 0.38 | **0.91** | 0.70 |
| `worst` | 0.38 | 0.44 | 0.33 |
| `residue` | **0.25** | **0.23** | **0.16** |

The 0.91 was the living winter crop showing up inside the pre-planting
window. Strip the winter crop out of the county and it falls to 0.38.

## Finding 2: one cover-crop threshold, three different answers

This is the result that matters most, and it is not subtle.

| | Champaign | Sumner | Mitchell |
|---|---|---|---|
| Winters where the question can be asked | 100% | 54.7% | 100% |
| **Scored as off-season green** | **6.4%** | **61.1%** | **88.2%** |
| Fields with at least one such winter | 17.6% | 89.1% | **100%** |
| Median off-season peak NDVI | 0.231 | 0.347 | 0.436 |

The median off-season greenness climbs monotonically across the three
counties — 0.231, 0.347, 0.436 — while the threshold stays where it is. One
number cannot sit in the right place in all three distributions, and it
doesn't.

**Mitchell is the strong claim, because the repository already has ground
truth there.** Mitchell County is the second-largest site in the Georgia
validation cohort, 28 farmer-reported field-years, and that validation
measured **7.1% specificity** at the shipped threshold — 144 false positives
against 11 true negatives. A result of "100% of fields show a cover crop in
at least one winter" in that county is not a measurement of adoption. It is
the false-positive rate, reproduced on new fields.

Champaign is the mirror image. 6.4% of winters positive and 17.6% of fields
is low for central Illinois, and the same validation measured substantial
false negatives in the Corn Belt.

**The benchmark should not report cover-crop verdicts at all until the
thresholds are regional.** Rank the continuous off-season measure instead —
it needs no threshold, and the Sumner study already showed the ranking
survives when the threshold is removed.

## Finding 3: the calendar-year scores earn their place on coverage

| | Champaign | Sumner | Mitchell |
|---|---|---|---|
| `preplant` coverage | **73.7%** | 98.2% | 93.3% |
| calendar-year coverage | **100%** | **100%** | **100%** |
| median observations in the pre-plant window | **3** | 11 | 10 |

Champaign is the case for the annual scores on its own. An Illinois spring
is cloudy, the pre-planting window is short, and the median field-year gets
**three usable observations** — from which the shipped pipeline computes a
trapezoidal average and reports a number. A quarter of field-years get no
reading at all.

The calendar-year scores cover every field-year in all three counties,
because a whole year always has enough clear dates even when a six-week
window does not. That argument holds everywhere and is strongest exactly
where the window score is weakest.

## Finding 4: `residue` and `worst` hold up, for different reasons

Between-field share of variance — how much of the signal is a persistent
property of the field rather than year-to-year noise:

| | Champaign | Sumner | Mitchell |
|---|---|---|---|
| `preplant` | 0.35 | 0.24 | 0.26 |
| `worst` | 0.35 | 0.28 | **0.40** |
| `residue` | **0.42** | **0.31** | 0.32 |

`residue` is the most stable in Champaign and Sumner, `worst` in Mitchell,
and both beat the window score in five of six comparisons. Combined with the
independence table above and complete coverage, the two-score
recommendation from the Sumner study survives contact with two more
rotations — but the *reason* changes by region:

- **Corn Belt:** coverage is the whole argument. Crop bias does not exist
  there and the window score is only mildly tied to greenness.
- **Wheat country:** crop neutrality is the whole argument.
- **Peanut belt:** stability and independence, with a modest coverage gain.

One caveat that holds everywhere: `residue` always has the smallest spread
(IQR 0.056 / 0.078 / 0.083). It is crop-neutral and low-contrast at once.

## The three focus fields

Percentile among the cohort, higher = better covered, exposure inverted:

| score | Champaign | Sumner | Mitchell |
|---|---|---|---|
| `preplant` | 82 | 8 | 44 |
| `mean` | 86 | 14 | 24 |
| `exposure` | 74 | 19 | 8 |
| `worst` | 88 | 26 | 28 |
| `residue` | **94** | 30 | **8** |

Champaign's focus field is well covered by local standards on every measure;
Sumner's and Mitchell's are below median on nearly all. Note Mitchell, where
the window score says 44th percentile and annual residue says 8th — the
largest disagreement between the two scores anywhere in the three counties,
and a reminder that which score you pick is a decision about what you are
measuring, not a detail.

## What this means for a deck

Three things are now solid enough to present:

1. **Coverage.** The pre-plant window fails on a quarter of Illinois
   field-years and rests on three observations where it succeeds. The
   calendar-year scores fix that everywhere.
2. **Regional calibration of cover crops.** 6% / 61% / 88% from one
   threshold, with the Georgia end corroborated by the project's own ground
   truth. This is a finding, not a caveat.
3. **Stratify only where the rotation demands it.** The Sumner crop-bias
   result is real and is specific to winter-cereal country.

One thing is not ready: any claim that a particular field is well or badly
managed. Three counties of internal consistency is not validation, and
nothing here has been checked against a grower record.

## What has not been established

- **No ground truth for soil cover anywhere**, in any of the three counties.
  Every criterion used to rank the scores — crop neutrality, independence
  from greenness, stability, coverage — measures *behavior*, not accuracy.
- **The Georgia cover-crop comparison leans on existing validation** of the
  threshold, not on new ground truth for these 51 fields.
- **Boundaries are the 2008 public CLU** in all three counties, eighteen
  years stale. The purity filter removes the worst drift and cannot fix a
  field split along a line CDL still reads as uniform.
- **One focus field per county**, each chosen for a dense neighborhood
  rather than for being typical. Two of three are well above their cohort's
  median size.
- **Three counties is three counties.** No irrigated west, no Delta, no
  Northern Plains, no specialty crops.

## Files

| | |
|---|---|
| `compare_counties.py` | the cross-county table and both figures |
| `_across/compare_counties.csv` | every number in this document |
| `_across/A_cover_by_county.png` | 6% / 61% / 88%, and the distributions behind it |
| `_across/B_coverage_independence.png` | coverage and independence, all three |
| `<county>/figures/01..07` | the per-county set, as in `SUMNER-FINDINGS.md` |

Per-county detail: [`SUMNER-FINDINGS.md`](SUMNER-FINDINGS.md) and
[`ANNUAL-ARMOR-OPTIONS.md`](ANNUAL-ARMOR-OPTIONS.md).
