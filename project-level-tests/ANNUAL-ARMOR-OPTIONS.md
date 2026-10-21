# A calendar-year soil armor score: five options, tested

The shipped armor score covers the pre-planting window only. On the Sumner
County cohort that forced every comparison to be stratified, because on a
winter wheat field the pre-planting window contains a living cash crop and
the score ends up ranking cropping systems (Cohen's d = **2.73** between
winter-crop and summer-only field-years).

This tests whether a calendar-year score fixes that or just annualizes it.

Nothing was re-downloaded. `ARMOR_SPAN` is already `01-01` to `12-31`, so
the per-date cover fractions for whole calendar years were already cached
from the benchmark run — 505 field-years over 101 fields, 32–48 clear dates
per year, 19 seconds to read.

> **Update, 20 October 2026.** Re-run in Champaign County, Illinois and
> Mitchell County, Georgia. The two-score recommendation holds in all three,
> but the crop-bias argument below is wheat-specific: neither of the other
> counties has a winter-crop stratum to be biased by. In the Corn Belt the
> argument for the calendar-year scores is coverage instead — the pre-plant
> window fails on 26% of Illinois field-years and rests on a median of three
> observations where it succeeds. See
> [`COUNTY-COMPARISON.md`](COUNTY-COMPARISON.md).

## The candidates

| | what it is |
|---|---|
| `preplant` | **the shipped score.** Time-weighted mean armor over the pre-planting window. The baseline to beat. |
| `mean` | time-weighted mean armor across the whole calendar year |
| `exposure` | days in the year with armor below 0.50 — a count of how long the ground was more bare than covered, not an average |
| `worst` | the 10th percentile of armor through the year: a robust annual minimum |
| `nongrow` | time-weighted mean armor outside the detected growing season |
| `residue` | time-weighted annual mean of `f_npv` alone — surface residue, excluding living cover |

All use the trapezoidal average `armor_summary` already argues for: soil is
exposed to erosion over *time*, so what matters is average cover through a
period, not the middle value of however many scenes happened to be clear.

## Results

| score | coverage | crop bias (d) | vs winter green (r) | stability (ICC) | spread (IQR) |
|---|---|---|---|---|---|
| `preplant` | 496/505 | **2.73** | **0.91** | 0.24 | 0.402 |
| `mean` | 505/505 | 1.24 | 0.68 | 0.23 | 0.145 |
| `exposure` | 505/505 | −1.29 | −0.66 | 0.22 | 98 days |
| `nongrow` | **330**/505 | 1.58 | 0.71 | 0.31 | 0.167 |
| `worst` | 505/505 | 0.51 | 0.44 | 0.28 | 0.221 |
| `residue` | 505/505 | **0.36** | **0.23** | **0.31** | 0.078 |

- **crop bias** — standardized gap between winter-crop and summer-only
  field-years. A soil-cover score should not know what crop was grown.
  Smaller is better.
- **vs winter green** — |r| against off-season peak NDVI. The benchmark
  found the shipped score is largely a restatement of winter greenness.
  Smaller means it carries information NDVI does not.
- **stability** — share of variance between fields rather than within a
  field across years. Higher means more like a persistent field property.
- **spread** — interquartile range in the score's own units.

## What it says

**`residue` is the clear winner on crop-neutrality.** Cohen's d falls from
2.73 to **0.36**, a 7½-fold reduction, and correlation with winter greenness
falls from 0.91 to **0.23**. That is not a surprise once stated: `f_npv` is
non-photosynthetic vegetation, so a living wheat crop contributes to `f_pv`
and is excluded by construction. It is the only candidate that measures
"something was left on this field" rather than "something was growing on
it", and it has full coverage and the joint-best stability.

**`worst` is a reasonable second** — d = 0.51, r = 0.44, and it keeps a
usable spread (IQR 0.221 against residue's 0.078). It answers a different
question: not how covered the field was on average, but how bare it got at
its worst, which is closer to how erosion actually works.

**`exposure` is the most communicable** — "this field was more bare than
covered for 148 days" needs no explanation. But it carries the crop bias
(d = −1.29), so it is a reporting format, not a benchmark.

**`nongrow` failed, and the reason is worth recording.** It looked like the
principled option and came out worse than a plain annual mean (d = 1.58).
Two causes, both verified against the data rather than assumed:

- The phenology detector finds the **summer** crop. For winter-crop years
  that produce a season at all, the median detected planting is day 180
  (late June) and harvest day 288. Winter wheat grows October to June —
  *outside* that window — so the wheat is counted as "non-growing" and
  inflates the score. Exactly backwards.
- It has no season to work with in 106 of 234 winter-crop field-years,
  dropping coverage to 330/505 and biasing which years survive.

Using phenology to exclude the cash crop cannot work until phenology
handles winter crops. `residue` reaches the same goal without needing it.

## How far each moves the answer

Correlation with the shipped pre-plant score, over the 496 field-years both
produce:

| | r |
|---|---|
| `nongrow` | +0.85 |
| `mean` | +0.76 |
| `exposure` | −0.72 |
| `worst` | +0.52 |
| `residue` | **+0.42** |

`residue` is the one that genuinely says something different.

And the focus field's standing moves with it — percentile among the 101
fields, higher = better covered, exposure inverted so all read the same way:

| score | percentile |
|---|---|
| `preplant` | **8** |
| `mean` | 14 |
| `nongrow` | 15 |
| `exposure` | 19 |
| `worst` | 26 |
| `residue` | **30** |

Below median on every one, which is reassuring — the earlier conclusion that
this field is poorly covered is not an artifact of the pre-plant window. But
it is a bottom-decile field under the shipped score and a merely
below-average one under a crop-neutral score, and that difference would
matter to anyone on the receiving end of it.

## Recommendation

Report **two numbers per calendar year**, not one:

1. **`residue`** — annual time-weighted mean `f_npv`, as the crop-neutral
   cover score. It is the only candidate tested that does not rank the
   cropping system.
2. **`worst`** — the 10th percentile of annual armor, as the exposure
   companion. Averages hide the weeks that do the damage.

Keep `preplant` as well. It answers a real and different question — how
covered was the ground at the moment of planting — and it is the one that
maps to a tillage conversation. It just cannot be used to compare fields
that grow different crops, and nothing here changes that.

Use `exposure` days for communicating to a grower, with the crop caveat
attached.

## What this does not establish

- **No ground truth.** There is no measured residue cover for any field in
  this cohort, or anywhere in this repository. These criteria say which
  candidates *behave* like a management signal — crop-neutral, independent
  of greenness, persistent year to year. None of them says which is right.
- **`residue` has the smallest spread** of any candidate (IQR 0.078 on a
  0–1 scale). Crop-neutral and low-contrast at the same time: it will need
  good observation density, and in a cloudier region it may not separate
  fields at all. Worth re-running where clear dates are scarcer.
- **`f_npv` comes from the ternary unmixing**, whose endmembers were fitted
  on eleven fields. `residue` inherits that uncertainty directly — it is
  exactly as provisional as the armor index it is derived from, and
  `METHODS.md` says which constants are provisional.
- **Stability may not mean management.** A score can look persistent
  because it tracks a field's permanent soil color or slope rather than
  anything the grower did. Nothing here separates those.
- **One county, one year-range, 101 fields,** in a wheat system. The
  ranking of these candidates is not guaranteed to hold in the Corn Belt or
  the South.

## Files

| | |
|---|---|
| `annual_armor_options.py` | computes all six scores from cache and runs the comparison |
| `figures_annual_armor.py` | figures 06 and 07; `--bare` for slides |
| `sumner-ks/annual_armor_options.csv` | all six scores, 505 field-years |
| `sumner-ks/figures/06_annual_candidates.png` | crop bias, all six side by side |
| `sumner-ks/figures/07_focus_under_each.png` | the focus field under each score |
