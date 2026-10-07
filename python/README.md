# fieldrs — field remote sensing in Python

A Python port of the R pipeline in the parent directory. Same data sources, same
algorithms, same cache semantics. No app — these are library modules and a CLI,
written to be lifted into a platform.

Given a field boundary it returns: what was grown each year, when it was planted
and harvested, whether anything grew over the winter, and whether the boundary
is actually one field.

## Install

```bash
cd python
pip install -r requirements.txt
```

## Run

```bash
python run_field.py ../data/fields/example_field.geojson
python run_field.py my_field.geojson --years 2020 2026 --out results/mine
python run_field.py my_field.geojson --indices ndvi ndmi --workers 12
```

First run for a field reads several hundred scenes and takes a few minutes.
Everything is cached to `cache/`, so re-running is instant.

## Use as a library

```python
from fieldrs import analyze_field

r = analyze_field("field.geojson", years=(2020, 2026))

r.summary        # one row per season: crop, planting, harvest, cover crop
r.series         # one row per scene: date, index, mean, sd, p10, p90, valid_frac
r.history        # CDL rotation per year
r.phenology      # season markers with uncertainty windows
r.covercrop      # one row per winter
r.advice         # boundary check: verdict, headline, detail
r.write("out/")  # every table to CSV
```

Each stage is independently importable if you want to wire them in separately:

```python
from fieldrs import (load_field, search_scenes, dedupe_scenes, read_scene,
                     extract_field_series, cdl_stack, cdl_split_advice,
                     phenology_all_years, cover_crop_all_years)
```

For platform code that already holds geometry in memory, skip the file:

```python
from fieldrs import geometry_from_geojson, analyze_field
aoi = geometry_from_geojson(geojson_dict)
r = analyze_field(aoi, years=(2020, 2026))
```

## Python-only additions

These exist here and not (yet) in the R version.

**App.** `streamlit run app.py` -- a Streamlit port of `r/app.R`, same seven
tabs, same cache.

**Local CDL.** Set `CDL_DIR` to a folder of national CDL GeoTIFFs --
`national/` or `tif/` subfolders, or flat `NASS_<year>.tif` files -- and CDL is
read from disk instead of CropScape (`fieldrs/cdl_local.py`). `run_field.py
--cdl-dir` sets it for one run; the app points it at the CSIP copy if present.

**Weather check on field-work dates** (`fieldrs/climate.py`). Daily gridMET at
the field centroid, through the CSIP climate service and the `csip` client
library. A planting, harvest, cover seeding or termination estimate that falls
on a rain day -- or, optionally, a day whose gridMET *daily-mean* wind reaches a
limit (gridMET has no gusts) -- moves to the last workable day before it, inside
its uncertainty window. On by default; `rain_free=False` / `--no-rain-check`
turns it off, `dry_mm` / `--dry-mm` and `wind_max_kmh` / `--wind-kmh` set the
limits. The estimates stay in `*_est`, the final dates are `*_date`, and
`summary.csv`, `phenology.csv` and `covercrop.csv` carry both as two blocks.

**Cover crop seeding and termination** (`covercrop.cover_crop_dates`). From the
post-harvest rise and the pre-plant decline of the NDVI curve. Never better
than medium confidence: none of it is fitted to recorded dates yet.

**HLS imagery** (`source="hls"`, `--source hls`, the app's Imagery switch).
See [HLS](#hls-sentinel-2--landsat) below.

## HLS: Sentinel-2 + Landsat

`source="hls"` reads NASA's Harmonized Landsat Sentinel-2 v2.0 instead of
Sentinel-2 L2A: Sentinel-2 (S30) and Landsat 8/9 (L30) on one 30 m grid,
cloud-masked with Fmask. Sentinel-2 stays the default and is unchanged -- its
series and season dates are identical to before HLS existed on all 15 library
fields. Each source is cached separately, so switching is instant once both
have been read.

**What is done to HLS before anything else sees it** (`fieldrs/extract.py`,
`fieldrs/imagery.py`):

1. *Edge pixels.* Only pixels whose centre is 15 m inside the boundary are
   used, so a 30 m pixel does not mix in the road or the next field. Falls
   back to the whole boundary below 10 pixels.
2. *Negative reflectance.* Pixels with any band at or below zero are dropped;
   near-zero red and NIR make NDVI explode.
3. *Transfer to the Sentinel-2 scale.* HLS reads about +0.05 NDVI higher than
   Sentinel-2 L2A over bare ground (+0.035 to +0.072 on every library field)
   and about +0.01 under full canopy. Every NDVI threshold here was set on
   Sentinel-2, so HLS NDVI is mapped with `S2 = 1.0733 * HLS - 0.0758` (S30)
   and `1.0707 * HLS - 0.0686` (L30), fitted on 2,941 same-day and 818
   near-coincident pairs. Residual bias is within +/-0.01 at every NDVI level.
   NDVI only; other indices are not transferred.
4. *Spike filter.* Fmask misses some partial snow and thin cloud that SCL
   catches. A reading more than 0.10 from its nearest neighbour on both sides,
   or -- November to March, next to a long gap -- from a stable run of readings
   on one side, is dropped.

The cache holds the raw series; steps 3 and 4 run on the way out, so either
can be refitted without re-reading imagery.

**Sentinel-2 vs HLS on the library** (15 fields, 2020-2026):

| | Sentinel-2 | HLS |
|---|---|---|
| Clear dates per field (median) | 257 | 366 |
| Median gap at harvest | 10 d | 5 d |
| Harvests with a gap over 20 d | 12 | 8 |
| Median gap at planting | 10 d | 10 d |
| Season confidence high / medium / low | 34 / 25 / 42 | 37 / 25 / 39 |
| Planting, HLS minus S2 | | median -1 d, half within 2 d |
| Harvest, HLS minus S2 | | median +2 d, half within 2 d |
| Cover crop verdict agreement | | 71 of 90 winters |

Use HLS for denser coverage around harvest and for cloudy regions. Its cover
crop verdicts are not better than Sentinel-2's: the remaining disagreements sit
at the 0.30 "possible cover crop" threshold, and with more observations a
single winter reading over it is more likely -- on the grower-confirmed
no-cover Georgia fields HLS says "possible" or "likely" slightly more often.
That is a property of the max-based verdict rule, not of HLS, and is not
changed here.

Planetary Computer holds HLS v2 from 2020 only. The residue indices
(`residue=True`) read Sentinel-2 whichever source is chosen.

## Module map

The layout mirrors the R package one-to-one, so the two can be read side by side.

| Python | R | Does |
|---|---|---|
| `fieldrs/aoi.py` | `R/aoi.R` | Boundary loading and cleaning |
| `fieldrs/imagery.py` | `R/imagery.R` | STAC search, dedupe, scene reads |
| `fieldrs/indices.py` | `R/indices.R` | NDVI and friends; add your own |
| `fieldrs/extract.py` | `R/extract.R` | Parallel multi-year series |
| `fieldrs/cache.py` | `R/cache.R` | Disk cache and analysis window |
| `fieldrs/cropland.py` | `R/cropland.R` | USDA CDL via CropScape |
| `fieldrs/cdl_split.py` | `R/cdl_split.R` | Boundary check: one field or two? |
| `fieldrs/phenology.py` | `R/phenology.R` | Planting and harvest |
| `fieldrs/covercrop.py` | `R/covercrop.R` | Off-season green cover |
| `fieldrs/pipeline.py` | (the Shiny server) | `analyze_field()` orchestration |

## Where this differs from the R version

**Threads, not processes.** R uses `future::multisession`. Here the scene reads
run on a `ThreadPoolExecutor`: the work is network-bound and GDAL releases the
GIL during HTTP, so threads get the speed-up without pickling or process
startup. Set `workers=1` to serialise for debugging.

**Signing happens per read.** `planetary_computer.sign()` is called when an
asset is opened rather than at search time. Tokens are cached per container, and
this removes the signature-expiry problem that a long run otherwise hits. This
turned out to be the better design: R signed the whole search result up front,
and on a six-year catalog that was 823 features and ~23 s of URL rewriting
before a single byte was read. R's contact sheet now signs only the slice it is
about to open, which is what this already did.

**The catalog search is not cached here, and is in R.** R's app has an Imagery
tab that re-searches on every restart, so `search_scenes()` there writes to
disk. In Python the only caller is `extract_field_series()`, which returns from
the series cache before it ever searches — so the search only runs on a
genuinely cold field, where 9 s sits inside a four-minute read. Add the cache if
you wire this to a UI; it is the same `cache_key` / `cache_put` pattern.

**CropScape needs `truststore`.** CropScape serves an incomplete TLS chain. curl
(and therefore R) papers over it with the OS trust store; `requests` uses
certifi and fails with `CERTIFICATE_VERIFY_FAILED`. `truststore` routes
verification through the OS store. Verification stays **on** — the code never
passes `verify=False`.

**GDAL tuning is explicit.** `imagery.GDAL_ENV` sets
`GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` and friends. Without it GDAL lists the
whole blob container on every open, which dominates runtime.

## Soil armor (residue cover)

`fieldrs/armor.py` reads the shortwave infrared through each season's
pre-planting window and decomposes every pixel into living green cover
(`f_pv`), crop residue (`f_npv`) and bare soil (`f_bs`), summing to one.
**Soil armor is `1 - f_bs`** — cover from any source.

It supersedes the minimum-NDTI metric in `residue.py`, which measured residue
only and therefore scored living cover as bare. `residue.py` is kept for the
NDTI numbers themselves; `armor.py` is what the pipeline and app now use. Off by default — it is a second pass over the archive on
different bands:

```python
r = analyze_field("field.geojson", (2020, 2026), residue=True)
r.residue          # one row per season
r.residue_series   # the underlying spring observations
```

```bash
python run_field.py field.geojson --residue
```

`residue_series()` extracts 1 Mar – 30 Jun per year rather than the whole year:
NDTI is only interpretable on bare ground, so a year-round read would cost
several times as much to discard most of it, and would re-read every scene the
NDVI series already covers because the cache key includes the index list.

Per season it reports the window and its `source`, the clear-observation count
split into bare and green, and min / median / max NDTI over the bare dates.
`min_ndti` is the headline: the minimum across a window is what the minNDTI
literature validates, because a single date is at the mercy of that morning's
soil moisture.

**No tillage class is produced, deliberately** — see the module docstring for
the two measurements behind that decision and `README.md` at the repo root for
the accuracy ceiling. Anything built on top of this needs calibrating against
residue line-transect data first.

## Things worth knowing before you trust the numbers

- **Nothing is calibrated.** Every threshold and crop lag is a
  literature-typical starting value, not fitted to ground truth. Regressing
  planting estimates against grower-reported dates is the highest-value next
  step.
- **Scene cloud is not field cloud.** The catalog figure covers a 110 km tile.
  Filtering is on `valid_fraction`, the share of *field* pixels surviving the
  mask. Keep `max_cloud` loose.
- **The 2022 reflectance offset.** From processing baseline 04.00 ESA added a
  −1000 offset. Handled per scene; pipelines that miss it show a step change in
  early 2022 that looks like a trend.
- **Same-date duplicates.** Overlapping tiles and orbits can return one date
  several times — one 15 ha field returned 4,682 scenes for 664 dates.
  `dedupe_scenes()` removes them *before* reading, preferring a footprint that
  fully covers the field, then lowest cloud.
- **The model only fits annual row crops, and says so when it doesn't.**
  Planting is inferred from a bare-soil-to-canopy transition, which a perennial
  stand never makes. `applicability()` in `phenology.py` withholds dates for a
  season that stays above NDVI 0.50 for 80%+ of the year *and* never drops below
  0.30 — on the Washington pivot that is 4 of 7 seasons, and CDL independently
  labels three of them Alfalfa. Flooded ground (NDVI below 0.05, i.e. rice) does
  not withhold the dates but caps confidence and attaches the reason, and the
  cover crop module reports "not detectable" rather than "none" for a winter
  spent under water.
- **Cover crop verdicts are evidence, not findings.** NDVI sees green, not
  intent; volunteer grain and winter weeds look similar. Double cropping after a
  small grain is flagged separately where the following crop goes in late.
- **The cache window is month-stable.** `analysis_window()` ends at the start of
  the current month so keys do not change daily. Re-run monthly to move it
  forward.

## Verified against the R pipeline

**Scene level.** Reading `S2A_MSIL2A_20240801T170851_R112_T15TVG` over the 66 ha
Iowa field, both implementations return identical values:

| | R | Python |
|---|---|---|
| red mean | 0.02191 | 0.02191 |
| nir mean | 0.57043 | 0.57043 |
| field pixels | 6593 | 6593 |

**Pipeline level.** Same field, 2020 → Sept 2026. Both produce **368
observations**, the same CDL rotation, the same boundary verdict and identical
cover crop verdicts. Season markers:

| Year | Planting (R / Py) | Harvest (R / Py) | Season | Peak NDVI |
|---|---|---|---|---|
| 2020 | 28 May / 28 May | 21 Sep / 22 Sep | 98 / 99 | 0.921 / 0.909 |
| 2021 | 17 May / 16 May | 1 Oct / 1 Oct | 116 / 117 | 0.873 / 0.872 |
| 2022 | 29 May / 29 May | 18 Oct / 17 Oct | 121 / 120 | 0.885 / 0.886 |
| 2023 | 10 May / 10 May | 25 Sep / 25 Sep | 117 / 117 | 0.939 / 0.935 |
| 2024 | 7 Jun / 6 Jun | 4 Oct / 3 Oct | 101 / 101 | 0.932 / 0.931 |
| 2025 | 11 May / 11 May | 9 Sep / 9 Sep | 100 / 100 | 0.924 / 0.921 |

Never more than one day apart, against a stated uncertainty of ±14 days.

**Whole library.** `compare_with_r.py` runs all 15 fields from both caches and
exits non-zero on any disagreement. It covers 105 seasons, 90 winters and 15
boundary verdicts. Tolerances are 3 days on season markers, 2 scenes on
observation counts, and 0.02 on peak NDVI; **verdicts and crop names must match
exactly**, because those are decisions rather than estimates.

The R side is a CSV export, not the live R cache. Regenerate it with `Rscript
export_r_reference.R` in `r/` whenever a field is added, or every new field
reports "missing from the R reference" and the real comparison hides behind the
noise.

> **It exits 1 on a clean checkout. That is the expected state, not a broken
> setup.** The known disagreements are listed below. Compare your run against
> that list — anything else is a real regression.

| | Result |
|---|---|
| Boundary verdicts | 15 / 15 match |
| CDL crop names | 0 mismatches of 90 |
| CDL flagged area | within 0.45 ha; 12 of 15 fields identical |
| Observation counts | within 2 everywhere (Clinton 366 = 366) |
| Season markers | 190 / 193 within 3 days, of 210 comparisons where both produced a date |
| Peak NDVI | within 0.021 everywhere |
| Cover crop verdicts | 89 / 90 match |

Measured 5 October 2026, both caches warmed against the window
2020-01-01 → 2026-10-01.

Largest `min_ndti` difference per field:

| Field | Δ | Field | Δ |
|---|---|---|---|
| washington-pivot | **0.0000** | example_field | 0.0010 |
| example_field_covercrop | 0.0002 | eldorado-georgia | 0.0020 |
| kansas-rainfed | 0.0004 | example_field_overgrown | 0.0024 |
| california-central | 0.0007 | tifton-georgia | 0.0039 |
| lubbock-pivot | 0.0008 | clinton-iowa | 0.0284 |
| arkansas-rice | 0.0009 | | |

### The eight expected disagreements

```
clinton-iowa 2023:             planting differs by 25 days
clinton-iowa 2022-23:          cover 'no cover crop detected' (R) vs 'possible cover crop' (Py)
clinton-iowa 2023:             armor observation count 7 (R) vs 12 (Py)
clinton-iowa 2023:             f_npv differs by 0.046
tifton-georgia 2022:           harvest differs by 4 days
example_field_covercrop 2026:  harvest present in Py only
mitchell-ga-conservation 2020: harvest differs by 51 days
mitchell-ga-conventional 2021: peak NDVI differs by 0.021
```

**They come from four root causes, not eight.** Four are Clinton, Iowa 2023.
One is a 4-day harvest on Tifton 2022 against a 3-day tolerance. The 2026
one-sided harvest is the incomplete current season, where R declines to date a
senescence it cannot see the end of and Python commits to one; it will resolve
itself when the year closes.

The fourth is new and is the interesting one. **Mitchell County 2020 is a
cotton season followed straight into a cover crop**, so the autumn curve falls
and climbs again with no clean return to baseline. R puts harvest at 17 October
and Python at 7 December — 51 days, the largest disagreement anywhere in the
library. Neither is obviously wrong from the curve alone; October is the
typical Georgia cotton harvest and December is late but not impossible. It is
the same *kind* of failure as Clinton: two smoothers choosing between candidate
baselines when the signal gives no sharp one, except here it is the cover crop
rather than a slow spring that removes the sharp edge.

Worth stating plainly, because it is the project's own finding turned back on
itself: a cover crop obscures the harvest signal the same way it obscures the
tillage signal. The season-marker confidence flag does not catch this one — R
calls it high confidence — so it is not currently detectable from the output
alone. Grower harvest dates would settle it; nothing else will.

The 0.021 peak NDVI on Mitchell conventional 2021 is marginally over the 0.018
the 11-field library used to show, which is what adding four fields to a
distribution does rather than a regression.

Clinton's spring is a slow ramp with no distinct trough, so the "last
near-minimum before the peak" rule is choosing between two nearly equal
candidates — Python's lands at 0.173 against a 0.174 band edge. That 25-day
planting difference then propagates: the cover crop window ends at planting
minus 3 days, and so does the residue window.

The residue items are **entirely** that window, not the residue code. Scored
over R's window, Python reports n=7 and a minimum of 0.1244 against R's n=7 and
0.1246 — agreement to 0.0002. Python's longer window simply picks up four more
bare dates (26 Apr, 28 Apr, 1 May, 3 May 2023), one of which is lower.

Both readings of Clinton 2023 are defensible and the season is already flagged
`medium`. It is left alone deliberately: tightening the rule to settle one
season would be fitting it to one field.

### A note on the smoother, if you change it

`daily_series()` uses `scipy.interpolate.make_smoothing_spline` — the penalized
spline corresponding to R's `smooth.spline` — at a **fixed penalty**,
`SMOOTH_LAM = 50`, rather than letting GCV pick one per series.

That is deliberate and it matters. With GCV choosing, Python was systematically
under-smoothed relative to R's `spar = 0.35`: peak NDVI differed by up to 0.081
across the library, 12 of 77 seasons fell outside the comparison tolerance, and
the fitted peak sat above the highest actual observation in 41 of 77 seasons.
Sweeping `lam` against the R reference, 50 puts the mean peak difference at
0.004 and the worst at 0.018 — none outside tolerance — and reproduces R's
plateau behavior exactly, both smoothers sitting a little above the maximum
observation in the same 26 seasons. Fixing the penalty cut whole-library
disagreements from 22 to 3.

The earlier alternative, `UnivariateSpline` with a hand-set smoothing factor,
**overshoots badly at a plateau**: on the Iowa 2022 season it put peak NDVI at
0.987 where the highest actual observation was 0.884 — not a physically possible
canopy value, and it propagates into the amplitude that every threshold is
measured against.

If you change the smoother, re-run `compare_with_r.py` and check the fitted peak
against the observed maximum before trusting anything downstream.
