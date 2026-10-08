# Field remote sensing — R and Python

> ### Status: demonstration and handoff — expected to be retired
>
> This exists to show the data pipeline to developers and stakeholders, and to
> support the case for building it into the **Fieldprint Platform**. It is not
> production software and is not intended to be maintained. Once the pipeline
> lands on the platform side — expected during 2026 — this repository can be
> archived.
>
> **What is meant to outlive it:** the `python/` package, which is the thing to
> adapt; the cross-implementation parity evidence, which is what makes the
> Python port trustworthy; and the measured findings recorded in this README.
> The Shiny app is the vehicle for the conversation, not the deliverable.
>
> **Stakeholder material** built from these findings lives in
> [`pitch/`](pitch/): the cotton industry deck and a developer-hour estimate
> for platform integration. Where the deck and this README differ in emphasis,
> this README is authoritative.
>
> **Before porting: refit the constants.** Several numbers here were fitted to
> these eleven demo fields and will not hold at platform scale. Each is marked
> provisional in the source, but the risk is that a fitted-looking constant
> gets inherited without question:
>
> | Constant | Where | Fitted on |
> |---|---|---|
> | `ARMOR_ENDMEMBERS` | `armor.R` / `armor.py` | 65,555 pixels from six of these fields |
> | `ARMOR_BREAKS` (0.40 / 0.75) | `armor.R` / `armor.py` | this library's own distribution; validation suggests ~0.44–0.59 and crop-specific |
> | `RESIDUE_BREAKS` (0.05 / 0.09) | `residue.R` / `residue.py` | p33 / p75 of 64 seasons here |
> | `CC_GREEN_MIN` / `CC_STRONG` (0.30 / 0.35) | `covercrop.R` / `covercrop.py` | **Mid-Atlantic, not Iowa** — the lineage runs through Chesapeake-region work, not the Corn Belt. **Measured wrong for Georgia** — 98% of no-cover fields clear 0.30. The origin of the number is still unverified; see *What was found for the cover crop thresholds* in `METHODS.md` |
| `CROP_LAGS`, `SPLIT_*` | various | literature-typical, never calibrated |
>
> The endmembers deserve particular care: they came from real pixels, so they
> *look* empirical, which makes them more likely to be carried across intact.
> They describe six fields in four states. Refit them on production geography
> before trusting the cover fractions outside this library.
>
> **Almost nothing here is calibrated against ground truth.** The exceptions
> are CDL crop labels, soil armor and cover crop detection, all now tested
> against a 347-field-year Georgia farmer survey — see *Validation against
> ground truth*, whose **Scorecard** counts every category in one table. Read it before quoting armor as a tillage metric, because the
> headline result is that it is not one; note that CDL agrees with the grower
> only 80.7% of the time, rising to 88.7% once low-purity boundaries are
> excluded; and **do not ship the cover crop verdict as it stands** — its
> thresholds are Iowa's and in Georgia it says "likely cover crop" to 96% of
> fields. Planting and harvest dates remain untested against anything. Ingesting grower-reported dates and residue line transects is the
> step that turns those into defensible numbers, and is the main thing this
> demonstration is arguing for.

**[`METHODS.md`](METHODS.md) documents every formula, constant and chart** in
enough detail to be reviewed by a geospatial scientist without reading the source.

Reads a field's management history out of free satellite imagery. Give it a
boundary and it returns: what data exists for that field, what was grown each
year, when it was planted and harvested, whether anything grew over the winter,
and whether the boundary is actually one field.

Two implementations of the same pipeline, sharing one library of field
boundaries.

```
.
├── data/fields/        15 example boundaries, shared by both implementations
├── r/                  R implementation — Shiny app + pipeline
└── python/             Python implementation — library + CLI, no app
```

| | `r/` | `python/` |
|---|---|---|
| For | Exploring, demonstrating, showing stakeholders | Embedding in a platform |
| Interface | Shiny app, 7 tabs | Importable package + CLI |
| Entry point | `shiny::runApp()` | `analyze_field()` / `run_field.py` |
| Pre-computed demo library | Yes — any field opens in <1 s | No — computes on demand |

Both read the same boundaries from `data/fields/`, hit the same public data
sources, and implement the same algorithms. Neither needs an account or an API
key for anything.

## Quick start

**R — the app.** Best for seeing what the pipeline does.

```r
setwd("r")
source("setup.R")        # once
```
```bash
cd r && Rscript warm_cache.R    # once, ~35 min: pre-computes the demo library
```
```r
shiny::runApp()          # from r/
```

Load one of the fifteen example fields, upload your own boundary, or **trace one
on the map** with the polygon tool. A traced boundary has its crop history read
and shown for confirmation before anything expensive runs — see
[`r/README.md`](r/README.md) for the purity bands it warns on, which come
straight from the validation section below.

**Python — the library.** Best for building on.

```bash
cd python
pip install -r requirements.txt
python run_field.py ../data/fields/example_field.geojson
```

```python
from fieldrs import analyze_field
r = analyze_field("field.geojson", years=(2020, 2026))
r.summary          # one row per season
r.write("out/")    # every table to CSV
```

## Which is authoritative?

The R version came first and is the reference implementation. The Python port
was validated against it field by field. `python/compare_with_r.py` diffs all
15 fields, exiting non-zero on any disagreement. It reads Python's cache
directly and R's through a CSV export, so `Rscript export_r_reference.R` has to
be re-run in `r/` whenever a field is added.

| Checked | Result |
|---|---|
| Boundary verdicts | **15 / 15** match |
| CDL crop names | **0** mismatches of 90 |
| CDL flagged area | within **0.45 ha**; 12 of 15 identical |
| Observation counts | within 2 everywhere |
| Season markers | **190 / 193** within 3 days |
| Peak NDVI | within **0.021** everywhere |
| Cover crop verdicts (90) | **89 / 90** match |

**It reports 10 disagreements, from four root causes** — four from Clinton, Iowa
2023, where the spring is a slow ramp with no distinct trough and the two
smoothers pick different candidate baselines; a 4-day harvest on Tifton 2022; a
2026 harvest Python dates and R declines to, which the incomplete season
explains; and a 51-day harvest gap on Mitchell County 2020, where a cover crop
sown straight after cotton leaves the autumn curve with no clean return to
baseline. That last one is the largest disagreement in the library and the only
one neither implementation flags as low confidence. `python/README.md` lists all
ten so a developer can tell them from a real regression; the check is *meant*
to exit non-zero on a clean checkout.

Two of the ten appeared in October 2026 when `window_source`, `window_start`,
`window_end` and `ndvi_med` were added to the R export. All four are computed
by both implementations and none had ever been compared, so a disagreement in
any of them would have been invisible. `window_source` matches on all 105 rows.

Porting was worth it beyond the deliverable: comparing two implementations
caught two problems neither would have shown alone. `terra::mask()` defaults to
`touches = TRUE` for polygons, so the R CDL clip was keeping every 30 m cell the
boundary so much as clipped — 233 cells (21.0 ha) on a 17.2 ha field. Those
cells carry the neighboring field's crop, which inflated CDL areas and biased
the boundary check toward "split". Fixed in both.

The second was in the port: letting scipy pick its own smoothing penalty by GCV
left Python systematically under-smoothed against R, with the fitted NDVI peak
sitting above the highest actual observation in 41 of 77 seasons. Pinning the
penalty to match R's `smooth.spline(spar = 0.35)` cut whole-library
disagreements from 22 to 3 — before the residue work, which later added two
more items tracing to the same Clinton season rather than to any new cause.

## Data sources

All free, all public, none requiring an account.

| Source | Resolution | Used for |
|---|---|---|
| Sentinel-2 L2A (Planetary Computer) | 10 m | NDVI, RGB, cloud masking |
| Landsat 8/9, HLS, Sentinel-1, MODIS, NAIP | 30 m – 0.6 m | Data availability view |
| USDA CDL (CropScape, or a local bulk copy) | 30 m | Crop type per field per year |

### Every external endpoint

The complete list, for a firewall rule or a security review. Nothing else is
contacted. [`METHODS.md`](METHODS.md) §11 carries the same list with the
measured request volumes — it is duplicated deliberately, because that document
is sent out as a standalone PDF, so **edit both**.

**Server-side** — requested by the R or Python process:

| Endpoint | Method | Used by |
|---|---|---|
| `planetarycomputer.microsoft.com/api/stac/v1` | POST | `search_scenes()`, `field_catalog()` |
| `planetarycomputer.microsoft.com/api/sas/v1/token/{collection}` | GET | `rstac::sign_planetary_computer()`, `planetary_computer.sign()` — called for us, not by us |
| `sentinel2l2a01.blob.core.windows.net/sentinel2-l2a/…` | GET (range) | Every COG read, through GDAL `/vsicurl/` |
| `nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile` | GET | `get_cdl()` — **fallback only** since the local CDL store |
| `www.nass.usda.gov/Research_and_Science/Cropland/Release/datasets/{year}_30m_cdls.zip` | GET | `download_cdl.py`, once per year per machine |

**Browser-side** — requested by the viewer's browser, never by the server:

| Endpoint | Used by |
|---|---|
| `server.arcgisonline.com/…/World_Imagery/MapServer/tile/{z}/{y}/{x}` | Satellite basemap |
| `server.arcgisonline.com/…/Reference/World_Boundaries_and_Places/…` | State lines and place names |
| `server.arcgisonline.com/…/Reference/World_Transportation/…` | Major roads |

Seven STAC collections are queried, all through the one STAC endpoint:
`sentinel-2-l2a`, `landsat-c2-l2`, `hls2-s30`, `hls2-l30`, `sentinel-1-rtc`,
`modis-13Q1-061` and `naip`. Only the first is read for analysis; the rest are
counted for the Data availability tab.

No account, key or token is required for any of them. The SAS token is fetched
anonymously and expires in about 45 minutes.

`r/R/gee.R` mentions `code.earthengine.google.com` in a comment. It is never
called, and `.rscignore` keeps it out of any deployment — the Earth Engine
backend was never wired in.

### Planetary Computer: what this actually costs them

Worth knowing before scaling, and measured rather than assumed.

| Call | Volume | Where it goes |
|---|---|---|
| STAC search | **1 per unique field and date range**, then cached on disk | PC API |
| SAS token | **~1 per 45 minutes** — `rstac` caches per container until expiry | PC API |
| COG range reads | **thousands per field** | Azure Blob Storage |

Nearly all the traffic is the third row, and it is blob storage rather than the
API — which is what the service exists for. The two rows that touch a
rate-limited API are tiny, and the one throttling incident seen so far was four
heavy searches in quick succession, not sustained volume.

Three things keep it that way:

- **The client identifies itself.** `pc_identify()` sets a user agent that GDAL
  sends on every range read and `httr` on every API call. It cost nothing and
  anonymous traffic is what gets throttled first.
- **Searches retry with backoff and honour `Retry-After`** when the service
  sends one — see `stac_search_retry()`.
- **Everything is cached**, per field, per year, on disk. A re-run costs no
  requests at all, which is also why the demo library ships warm.

**At platform scale this changes.** A few thousand fields is a few million blob
reads, and that is a conversation to have with Microsoft rather than a limit to
guess at. It belongs in the same planning as the CDL mirror below.

### CDL: read the layers locally, not through the API

CropScape is a public web service and behaves like one. The 347-field-year
validation run took **52 minutes** and was one request away from failing at any
point; it returns HTTP 500 often enough that a run of any size will meet one.
It also serves an incomplete TLS chain, which is why `cropland.py` carries a
`truststore` workaround.

A published CDL year never changes, so the whole national raster can be
downloaded once per machine and read from disk thereafter:

```bash
python python/download_cdl.py            # 2018-2025, ~1.8 GB zipped per year
python python/download_cdl.py --status
```

The store lives **outside the repository** at `~/geodata/cdl` (override with
`CDL_DIR`) so it cannot be committed and so every project on the machine shares
one copy. Both implementations pick it up automatically once any year is
present — `cdl_local.py` and `cdl_local.R` — and fall back to the API for years
that are missing. `FIELDRS_CDL_LOCAL=0` forces the API.

**A fresh clone works without downloading anything.** `r/make_cdl_clips.R` cuts
one small GeoTIFF per demo field per year out of the national store, and those
clips are committed: 120 files, **2.3 MB**, keyed by the same geometry hash as
the rest of the cache. Both implementations read them before the national store,
so someone who clones this repo gets the fifteen example fields working
immediately -- no 25 GB download, and no CropScape call. Regenerate them when a
field or a CDL year is added.

On a machine that *has* the store, the clips are redundant but harmless: any
boundary resolves from the national rasters, including one loaded through the
app at 0.57 s for four years. The clips matter for two cases only -- a
colleague's fresh clone, and a hosted deployment, where ~25 GB cannot ship and
an uploaded boundary would still have to fall back to CropScape.

**What it changed, measured on the same 347 field-years:**

| | CropScape API | Local store |
|---|---|---|
| Time to score all 347 | **52 min** | **5.6 s** |
| One 5-year stack, Python | ~45 s | 0.20 s |
| One 5-year stack, R | 56.7 s | 0.97 s |
| Dominant crop | — | **agrees on 346 of 347** |
| Area vs polygon geometry | +0.06% mean, 11.23% worst | +0.23% mean, 6.74% worst |

**It did not change the numbers, and that is the point.** The single crop
disagreement is a field CropScape called 33.0% Corn and the local store called
32.7% Peanuts — a coin flip between the top two classes where neither answer is
more correct. Area error for both sits inside 30 m pixel quantization and is
concentrated in fields under 10 ha, where a 0.09 ha pixel is a larger share of
the boundary. Go local for reliability and speed; there is no accuracy gain to
claim.

Two things worth knowing if you adapt this:

- **The published files are not consistent between years.** Some carry no CRS
  tag, so the reader states EPSG:5070 rather than trusting the file. Some ship
  `.ovr` display pyramids that nothing here reads and that can be deleted —
  they ran to 5 GB per year on this machine, more than the raster itself.
- **`path.expand("~")` on Windows is not the home directory.** R expands it to
  `Documents`, so R looked for the store in a different place than the Python
  downloader wrote it, found nothing, and silently fell back to the API. The R
  reader resolves `USERPROFILE` instead. Any cross-language store has this trap.

## How far back can this go?

Measured, not estimated: the numbers below come from running the pipeline on
the early years rather than from the sensors' spec sheets. Worth reading before
anyone promises a partner a ten-year history.

### Sentinel-2 — usable floor is 2017, hard wall at 2015

Sentinel-2A launched mid-2015 and 2B reached full operations in 2018, so US
revisit improves sharply across those years. Clear observations actually
extracted for the Iowa field:

| Year | Catalog dates | Clear obs | Phenology result |
|---|---|---|---|
| 2015 | 3 (from October) | — | nothing to work with |
| 2016 | 23 | 11 | 8 May / 22 Sep — *low, sparse imagery* |
| 2017 | 38 | 19 | 11 May / 2 Oct — *low, sparse imagery* |
| 2018 | 97 | 48 | 10 May / 21 Sep — **high** |
| 2020–25 | ~100 | 50–70 | high / medium |

2016 and 2017 do produce seasons, and the dates are plausible — all three
plantings fall inside the 8 May – 7 Jun range the 2020–2025 seasons show. The
confidence flag is doing its job: eleven observations across a year means the
green-up crossing can sit inside a three-week gap. Cover crop degrades first —
the 2016-17 winter had 6 observations in the window against a minimum of 4.

**2017 is a safe floor with no code change. 2016 runs but everything before
2018 should be read as indicative.**

### USDA CDL — 2008 nationally, and it fails silently before that

CropScape returns a raster for any year you ask for. For Georgia in 2000 and
2006 **every cell came back class 0** — no data, no error. Iowa returned real
Corn/Soybeans for 2000 because Iowa is one of the early CDL states.

Two things to handle if the range is ever widened:

- **Guard against the silent empty.** Outside the early states, a pre-2008 year
  yields a meaningless crop label rather than a failure. `get_cdl()` should
  treat an all-zero return as "no CDL for this year and state".
- **Early CDL is 56 m, not 30 m.** The 6.6 ha Georgia field drops from 76 cells
  in 2020 to 20 in 2008. The dominant-crop share gets coarse and the boundary
  split check stops being meaningful — it looks for 2 ha contiguous, which is
  about six cells at 56 m.

### Landsat — the only route earlier than 2015

Same free Planetary Computer catalog, already listed in `catalog.R` for the
availability view but not wired into extraction. For the Iowa field it holds
**2,955 scenes from November 1982**, across Landsat 4/5/7/8/9.

| Era | Apr–Oct scenes under 70% cloud, per year |
|---|---|
| 1984–1998 (L5) | 17 |
| 1999–2011 (L5 + L7) | 34 |
| 2014–2025 (L8/L9) | 34–39 |

**1999 onward is denser than Sentinel-2's 2017**, so a Landsat path would buy
roughly fifteen extra years at present quality and another fifteen at 2016-like
quality. What it costs:

- 30 m instead of 10 m. The 6.6 ha Georgia field is ~70 Landsat pixels against
  ~660 Sentinel-2 pixels; small fields get noisy and `min_valid` needs rethinking.
- Landsat 7 SLC-off striping after May 2003 punches gaps through every scene,
  which `valid_fraction` will read as cloud.
- Different band names and reflectance scaling, so `imagery.R` and `indices.R`
  each need a second reader rather than a config flag.
- CDL runs out at 2008 outside the early states, so `crop_lag()` falls back to
  its 20-day default and seasons lose their crop label.

This is a genuine piece of work, not a configuration change — but it is the
difference between a six-year history and a forty-year one, and for a
sustainability baseline that may be the more interesting number.

### Soil armor (residue cover): a research surface, not an output

Implemented in both, and visualized in the app's **Soil armor** tab.
**Higher NDTI means more residue on the surface; lower means barer ground.** The
multispectral indices from Sonmez & Slater (2016) are registered — **`ndti`**,
**`ndi7`**, **`ndsvi`** — `residue_window()` returns the bare-soil period
between one crop's harvest and the next crop's planting, and `residue.R` /
`residue.py` summarize the indices over it: clear observations split into bare
and green, then min / median / max NDTI over the bare ones. The minimum is the
headline, which is what the minNDTI literature validates.

It is a **separate, opt-in extraction** — spring only, four bands — so it does
not slow the main path. `analyze_field(..., residue=True)`, `run_field.py
--residue`, or the button in the app.

**Nothing computes a tillage class, deliberately.** Two findings from testing
these on real scenes say why:

- **Soil moisture moves NDTI more than tillage does.** On the Iowa field,
  18 and 20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 — a
  four-fold swing from rain, two days apart, with no change in residue.
  Single-date NDTI is not usable. The validated approach is multitemporal
  (minNDTI across the residue window, Zheng et al. 2013).
- **NDTI does not separate residue from green cover.** It reads 0.15–0.24 on
  the Maryland cover-cropped field because green canopy absorbs in the SWIR,
  not because there is residue. Dates above NDVI 0.30 are screened out and
  counted. On that field it leaves no bare ground at all in 4 of 7 springs —
  the cover crop runs to planting — and the tools report "not enough bare
  ground to read" rather than inventing a number.

### Provisional reference bands, and what calibration would buy

The **Soil armor** tab draws three reference levels behind the data — below
**0.05**, 0.05–0.09, above **0.09**. They are the 33rd and 75th percentiles of
this library's own 64 seasons, rounded, and they express rank among these
eleven fields. They are drawn, never tabulated: no class is written into any
output.

Two results from the library say why thresholds belong on `min_ndti` and
nowhere else:

| | |
|---|---|
| NDTI spread *within* one spring window | median **0.080** |
| Full spread of `min_ndti` *between* the eleven fields | **0.135** |
| Year-to-year SD of `min_ndti` *within* a field | **0.007–0.031** |

A single observation carries nearly as much noise as the entire between-field
signal. Taking the minimum over the window collapses that to roughly **8:1**,
which is what makes any threshold conversation possible at all.

**Stratify by the previous crop before trusting one cut.** Spring residue is
last season's crop, and the median `min_ndti` orders exactly as agronomy
predicts — Corn 0.078, Peanuts 0.067, Soybeans 0.066, Cotton 0.062, Rice 0.051,
double-crop 0.014. Corn stover is roughly twice soybean residue by mass and far
more persistent. A single global threshold would sort fields by what they grew
rather than by how they were managed.

**What ground truth converts this into.** The policy-relevant classes are
defined by residue cover, not by an index: conventional <15%, reduced 15–30%,
conservation >30% (CTIC). Calibration means line-transect residue on 30–50
fields spanning the range, measured inside the window and stratified by
previous crop, fitted as `CRC ~ min_ndti` and inverted at those boundaries.
Published minNDTI regressions reach R² ≈ 0.89 with RMSD ≈ 10.6 points of
cover — comparable to the width of the reduced class, so even a calibrated
model flips fields near a boundary. That is worth knowing before anyone builds
eligibility logic on it, and it is the honest scope of what this can become.

The hyperspectral index that paper found best, CAI, **cannot be computed from
Sentinel-2**: it needs three narrow bands inside the 2000–2200 nm cellulose
feature and B12 is one 180 nm-wide band covering all of it. The realistic
ceiling on free imagery is the 73–80% field-level accuracy tier, not the >90%
hyperspectral tier — roughly one field in four misclassified.

That matters more here than for cover crops. A cover-crop verdict is framed as
evidence with its confounders named; a tillage class feeds conservation program
eligibility and credit accounting. Residue line-transect ground truth comes
before any verdict ships.

On prior art: there is granted US patent activity on remote-sensing algorithms
for mapping regenerative agriculture practices. The indices used here are not
novel — NDTI, NDI and NDSVI are from the 1990s and 2000s, and the specific
combination was published by Sonmez & Slater in 2016 — so the position taken is
that this rests on prior art rather than on anyone's patent. That is a
deliberate decision recorded here, not legal advice; anything added later that
goes beyond published indices should be looked at again.

### Before changing the year range

`YEAR_MIN` in `r/app.R` sets the slider's default range, and that range feeds
`analysis_window()`, which feeds **every cache key**. Widening it to 2016 makes
the default window 2016–2026 and turns all fifteen warmed fields cold — an
85-minute re-warm in R and 65 in Python, longer with the extra years. Do it deliberately with a
re-warm scheduled, not as a one-line edit the morning of a demo.

## The current year: crop type before CDL exists

Not implemented. Notes from a research pass in September 2026, recorded so the
work does not start from scratch.

CDL for a crop year is published the following January or February, so the
current season never has a crop label. Today that year shows a blank crop and
`crop_lag()` falls back to its 20-day default — honest, but it throws away
signal that is already sitting in the cache.

### How the literature does it

Three families: phenology rules (planting date, peak timing, season length),
machine learning over multi-temporal spectral features, and deep learning on
the time series. In Iowa, random forest reaches **F1 ≈ 0.89 for corn by
silking and 0.85 for soybean by flowering** — so mid-to-late July, not before.

The directly relevant one is that **USDA NASS is building an In-Season CDL**
using a "trusted pixel" approach: historical CDL pixels with high confidence
become the training labels, so no current-year ground truth is needed. There is
a parallel academic line generating labels from archival land cover the same
way. That is exactly the position this pipeline is in — six CDL-labeled years
per field, already cached.

### What was measured on this library

| Signal | Accuracy | Detail |
|---|---|---|
| Rotation prior (modal successor) | **73%** (55 transitions) | Soybeans→Corn 8/8, Rice→Rice 5/5, but Corn→? only 56% |
| Planting day-of-year | 77% | corn 137, soy 147 |
| Season length | 77% | corn 113 d, soy 105 d |
| Peak NDVI | 74% | corn 0.88, soy 0.91 — barely separates |
| Peak-season GCVI (p90) | **70%** | **no better than always guessing corn** |

**The GCVI result is a negative worth keeping.** The literature points at GCVI
for corn/soy separation, so it looked like the obvious addition. Extracted over
5 Jul – 20 Aug for 30 field-years, corn median was 9.30 against soy 9.51; the
best possible single cut is 70%, which is exactly the majority-class baseline.
Within fields it is inconsistent — soy reads higher in two, lower in two.

The reason is visible in the same data: GCVI climbs monotonically across every
crop and every field, 8.12 in 2020 to 10.88 in 2025. That year effect swamps
the crop signal. Published results use **growth-stage-normalized** inputs, not
a fixed calendar window. Do not re-run this probe as-is expecting a different
answer; normalize first.

### What to build, in order

1. **Rotation prior.** An afternoon, no new imagery — `cdl_history` is already
   there. 73% for free, and it knows its own weak cases: report Soybeans→Corn
   confidently and Corn→? as a coin flip.
2. **Phenology-aligned nearest-neighbor match.** This is the growth-stage
   normalization the literature says matters, and the pipeline is unusually
   well placed for it because green-up is already computed per season. Re-index
   each year's NDVI curve to *days since green-up* rather than calendar date,
   then match the current partial curve against the same field's own
   CDL-labeled years. Nearest labeled year wins; the distance is the
   confidence. Self-supervised, no external training set, and it compares shape
   rather than absolute level — which is what sank the GCVI attempt.
3. **Combine.** Rotation as the prior, curve match as the likelihood.
   Disagreement between them is itself a useful low-confidence flag.

### Expectations and one open decision

Do not expect the literature's 0.85–0.89 — that comes from properly trained
regional classifiers. A per-field method on six labeled years will be worse,
and corn-on-corn will stay hard. Nothing useful arrives before about mid-July.
Surface it as `Corn (preliminary)` with a confidence, never as a CDL-equivalent
label.

**Open question, decide before building:** should a preliminary crop label feed
back into `crop_lag()` and shift the current year's planting estimate? It helps
when the label is right and hurts when it is wrong, and it couples two uncertain
things. The default recommendation is to display it but not let it drive
phenology until it has been validated against known fields.

## Soil armor: the metric that replaced minimum NDTI

> This section describes what the metric is and why it replaced minimum NDTI,
> on internal evidence only. It was written before any ground truth existed.
> **Validation against ground truth** below is the external check, and it
> qualifies the claims here in one important way: armor beats NDTI on peanuts
> but not on cotton, and most of its apparent tillage signal is cover-crop
> adoption.

**Implemented.** `r/R/armor.R` and `python/fieldrs/armor.py`.

Every pixel is decomposed into three fractions that sum to one — living green
cover (`f_pv`), crop residue (`f_npv`) and bare soil (`f_bs`) — and **soil armor
is `1 - f_bs`**: cover from any source.

### Why minimum NDTI had to go

NDTI measures residue. Soil armor is protection, and a living cover crop or a
perennial stand protects soil just as well as stubble does. Scoring only the
dead half systematically penalized exactly the fields the metric should reward.

On this library the error was not subtle:

| Field | old: min NDTI | rank | **new: armor** | living | residue | rank | move |
|---|---|---|---|---|---|---|---|
| WA alfalfa | 0.006 | 11 | **0.98** | 0.89 | 0.08 | 1 | **+10** |
| Maryland covercrop | 0.141 | 1 | 0.74 | 0.29 | 0.43 | 2 | −1 |
| CA Central | 0.018 | 10 | 0.69 | 0.56 | 0.13 | 3 | +7 |
| GA Tifton | 0.093 | 3 | 0.63 | 0.21 | 0.42 | 4 | −1 |
| Arkansas rice | 0.051 | 7 | 0.61 | 0.02 | 0.59 | 5 | +2 |
| Iowa Clinton | 0.103 | 2 | 0.55 | 0.02 | 0.54 | 6 | −4 |
| GA ElDorado | 0.048 | 8 | 0.49 | 0.08 | 0.37 | 7 | +1 |
| TX Lubbock | 0.057 | 6 | 0.49 | 0.06 | 0.39 | 7 | −1 |
| Kansas | 0.071 | 4 | 0.41 | 0.00 | 0.40 | 9 | −5 |
| Iowa overgrown | 0.071 | 5 | 0.38 | 0.04 | 0.33 | 10 | −5 |
| Iowa Story | 0.038 | 9 | **0.32** | 0.01 | 0.32 | 11 | −2 |

The Washington alfalfa pivot — a permanent stand, the best-protected soil in the
library — ranked **last of eleven**. It now ranks first. Iowa Story, a
conventional corn/soy rotation with genuinely bare springs, moves to last.

**Coverage went from 64 of 77 field-years to 75.** The old metric abstained
whenever a spring was too green to read; those fields were not unmeasurable,
they were *fully covered*, which is the answer.

The `living` and `residue` columns are why this is more than a reordering.
Maryland and Iowa Clinton are both well up the table, but Maryland is 0.29
living / 0.43 residue and Clinton is 0.02 / 0.54 — a cover-cropped field and a
heavy-stubble field, previously indistinguishable.

### Washington year by year, the internal check

| Year | obs | f_pv | f_npv | f_bs | armor |
|---|---|---|---|---|---|
| 2020 | 5 | 0.93 | 0.05 | 0.02 | 0.98 |
| 2021 | 6 | 0.90 | 0.08 | 0.03 | 0.97 |
| 2022 | 0 | — | — | — | *no window* |
| 2023 | 14 | 0.70 | 0.19 | 0.12 | 0.88 |
| **2024** | 5 | **0.00** | 0.08 | **0.92** | **0.08** |
| 2025 | 7 | 0.96 | 0.03 | 0.01 | 0.99 |
| 2026 | 8 | 0.89 | 0.09 | 0.02 | 0.98 |

2024 is the **potato** year in the rotation, and its pre-planting window really
is bare ground. The method separates it from the alfalfa years inside the same
field, which is the check that it is measuring cover rather than just rewarding
greenness.

### Coloring the three fractions — prototyped, not adopted

The Imagery tab's Soil armor sheet renders `1 - f_bs` on a single brown-to-teal
ramp, which shows **how much** cover there is and not **what kind**. Half
living / half bare and half residue / half bare both come out the same cream.
On the Maryland field, 21 April 2026 (`fPV` 0.08, `fNPV` 0.73, `fBS` 0.19) the
sheet is uniform teal — correctly "well covered", silent about it being stubble.

Three alternatives were rendered on that scene and compared. Recorded so the
next person does not repeat the exercise:

![Four ways of coloring the same scene: the current single-number brown-to-teal
ramp, a linear mix of green/brown/red weighted by the three fractions, an RGB
channel assignment, and a dominant-class map](r/outputs/18_palette_options.png)

*Maryland, 21 April 2026. Left to right: current ramp, A, B, C.*

| | Scheme | Verdict |
|---|---|---|
| **A** | Linear color mix: `f_pv`·green + `f_npv`·brown + `f_bs`·red | **Best of the three.** Field reads brown for residue, rust where bare bleeds through, green on the grassed waterway. Intuitive and keeps gradation |
| **B** | RGB channels: R = bare, G = living, B = residue | Mathematically cleanest — every fraction triple gets a unique color, no ambiguity. But residue lands on blue, and nobody reads blue as straw |
| **C** | Dominant class, lightness by dominance | Legible but flat; every residue-majority pixel looks identical |

**The catch with A**, which is why B exists in the literature: brown is red plus
green in RGB, so a half-living / half-bare pixel mixes toward brown and can be
mistaken for genuine residue. B is the only scheme without that ambiguity.

**Not adopted for now.** Building it means the contact-sheet cache stores three
bands per scene instead of one, and the view should be renamed (`cover` rather
than `armor`) so the existing 2-D cache entries cannot be served into a 3-band
renderer — a stale-cache trap this project has hit more than once. The
single-number ramp plus the Soil armor tab's separate Living and Residue
columns covers the same ground without that work.

### A full annual cycle, and what it suggests next

Two consecutive calendar years on the Iowa field — soybeans 2024, corn 2025,
109 clear dates, fractions summing to 1.000 throughout. Teal is living, tan is
residue, white to the top is bare soil.

![Stacked cover fractions across 2024 and 2025 with planting and harvest marked,
above the two inputs that drive them: NDVI and DFI on separate
axes](r/outputs/19_two_year_cover.png)

**The lower panel is the argument for the whole method.** On 10 April 2024 and
20 October 2024 NDVI is *identical* at 0.17 — no green either time. DFI is 8.7
and 23.5. NDVI alone cannot separate those; both read "bare". DFI says one is
soil and the other is fresh soybean stubble:

| Date | NDVI | DFI | living | residue | bare |
|---|---|---|---|---|---|
| 10 Apr 2024 | 0.17 | 8.7 | 0.00 | 0.23 | **0.77** |
| 16 Aug 2024 | 0.93 | 2.0 | **0.96** | 0.03 | 0.01 |
| 20 Oct 2024 | 0.17 | **23.5** | 0.00 | **0.84** | 0.16 |
| 28 Jan 2025 | 0.19 | 9.3 | 0.02 | 0.26 | 0.73 |
| 08 Apr 2025 | 0.19 | 7.7 | 0.01 | 0.20 | 0.79 |

Three other things the cycle shows. **Residue decays visibly** — 0.84 just after
harvest, 0.26 by late January, 0.20 by the following April, as stover weathers.
**Living and residue trade off** as the canopy closes: residue reads 0.03 in
August not because the stubble is gone but because the crop is covering it,
which is the honest answer for a metric about what protects the surface.
And the **spiky tan excursions in Feb–Apr** are soil moisture moving DFI, not
residue appearing and vanishing — the reason the summary statistic is a
time-weighted average rather than any single date.

#### Two cotton fields, same crop, different off-season

The clearest case in the library for why the off-season is the part worth
measuring. Both fields grow continuous cotton and reach nearly the same peak
canopy — 0.81 and 0.83 living in August. **During the season they are
indistinguishable.** The whole difference is in the eight months when nothing
is growing.

![Stacked cover fractions for two continuous-cotton fields: Tifton Georgia
2023-24, where winter carries a living cover crop, above Lubbock Texas 2021-22,
where bare soil dominates the off-season](r/outputs/20_cotton_two_years.png)

| | Tifton, GA (6.6 ha, cover cropped) | Lubbock, TX (41.5 ha, pivot) |
|---|---|---|
| Peak living, August | 0.81 | 0.83 |
| Living, mid-February | **0.31 → 0.50** | 0.13 / 0.07 |
| Bare soil, off-season | never above ~0.35 | **0.55–0.73** |
| Spring armor | 0.64 → **0.76** | 0.49 / 0.50 |
| Cover-crop winters | 6 of 6 | 4 of 7 |

At Tifton the teal band never collapses: a winter cover crop carries the field,
and when it is terminated in spring the residue takes over — 0.63 residue on
1 May 2023. At Lubbock the living fraction flatlines between harvest and the
next planting, and bare soil reaches 0.73 by December. In the High Plains that
off-season exposure is the wind-erosion risk.

Across the library the same split shows up by region rather than by crop: the
southern cotton and peanut fields run 6 of 6 winters with green cover, against
0 of 6 in Iowa and Kansas.

**Two caveats when showing this.** Tifton has 64 clear dates against Lubbock's
189, so its curve is choppier — the gap is far larger than the noise, but
week-to-week wiggles there are not signal. And these are uncalibrated
fractions: the ranking and the seasonal pattern are real, "0.73 bare" is not a
validated 73%.

#### What this suggests for a production version

- **The window misses the best signal.** `ARMOR_SPAN` is 1 Mar – 30 Jun, and
  peak residue lands in **October**, entirely outside it. The current metric
  measures the weathered remnant in spring rather than what was actually left
  after harvest. Extending the span across autumn is the single highest-value
  change, and costs a re-warm rather than new science.
- **Residue at planting is the CTIC-aligned number.** Tillage classes are
  defined by residue cover *at planting* (conventional <15%, reduced 15–30%,
  conservation >30%). `f_npv` on the planting date is a more direct estimate of
  that than a window average, and would map onto the existing class boundaries
  without a separate calibration.
- **The decay rate is itself a signal.** How fast residue falls from its
  post-harvest peak separates a field left alone from one worked over winter.
  That is a slope, not a level, and slopes are far less sensitive to the
  absolute-calibration problem that dogs the fractions.
- **Moisture normalization is the obvious accuracy win** — and needs care. The
  Indigo Ag patents in this space claim SMAP soil-moisture filtering as a claim
  element (see the patent notes above), so a wetness correction built from
  bands already in hand, such as the registered `ndmi`, is the more prudent
  route.

### The summary statistic: time-weighted, not median

Armor is a **trapezoidal average over the observation dates**, not the median
and not the minimum. Minimum was right for NDTI, where a wet morning could
quadruple the reading and the lowest value was the least contaminated. A cover
fraction is a different quantity.

It started as a median, and the cross-implementation check caught that being
fragile: on GA ElDorado in 2026 the two implementations saw 7 and 8 observations
of a steeply falling series over an identical window, and the single extra date
moved the median from 0.594 to 0.720. Time-weighted, the same pair gives 0.500
and 0.497.

The physical argument points the same way — soil is exposed to erosion over
*time*, so what matters is average cover through the window, not the middle
value of however many scenes happened to be cloud-free.

### How it works, and what is not calibrated

DFI = 100 x (1 - SWIR2/SWIR1) x (Red/NIR), Cao et al. (2010). The first term is
the lignocellulose absorption near 2100 nm that residue has and soil does not;
the second suppresses green canopy. Each pixel is then unmixed against three
endmembers in NDVI-DFI space, fitted from **65,555 cloud-free pixels** across six
fields spanning permanent green, heavy residue and clean tilled soil:

| Endmember | NDVI | DFI |
|---|---|---|
| PV (living canopy) | 0.961 | 1.2 |
| NPV (residue) | 0.232 | 25.6 |
| BS (bare soil) | 0.183 | 3.3 |

**Residue and bare soil differ by 0.05 in NDVI and by 22 in DFI.** NDVI genuinely
cannot tell them apart; that gap is the entire reason an index pair is needed.

Filtering water and deep shadow first was essential. As NIR collapses, DFI's
Red/NIR term explodes, so the highest-DFI pixels in the raw pool were flooded
rice and cloud shadow rather than residue — they put the NPV vertex at NDVI
-0.02, a surface no crop field has.

About one pixel in eight falls just outside the triangle and is clamped and
renormalized, which is ordinary for a linear mixture model.

**Not calibrated.** The endmembers come from this library's own pixels, so the
fractions are internally consistent and comparable between these fields but are
not validated cover percentages. Ground truth here means line transects scoring
green cover, residue and bare soil *separately* — a richer ask than the residue-
only transects the old metric needed, and one that validates all three
fractions at once.

### Dead Fuel Index: the background

DFI is algebraically a repackaging of NDTI and NDVI. With r = SWIR2/SWIR1 and
q = Red/NIR, NDTI = (1-r)/(1+r) and NDVI = (1-q)/(1+q), so exactly, pixel-wise:

```
DFI = 100 * [ 2*NDTI / (1 + NDTI) ] * [ (1 - NDVI) / (1 + NDVI) ]
```

On its own it is the wrong target — it measures *non-photosynthetic* cover, so
it reads the Washington alfalfa pivot at DFI 2.0 and would rank it least
protected. The value is not DFI as an index but DFI as the **second axis** that
makes the three-way unmixing possible.

## Validation against ground truth (first real test)

Everything above this section was internally consistent but never checked
against anything a farmer said. This section is the first time it was. Read it
before quoting soil armor as a tillage metric, because the headline result is
that **it is not one**.

### The dataset

A University of Georgia farmer survey: **347 field-years**, 226 distinct
fields, 2018–2021, cotton and peanuts in Georgia. Each row carries a boundary,
the crop planted, self-reported tillage class (CTIC residue bands), cover crop
yes/no, and irrigation. Every boundary was run through the pipeline over a
fixed pre-planting window (1 Mar – 15 May), producing time-weighted `f_pv`,
`f_npv`, `f_bs`, `armor`, plus `min_ndti` and `med_ndti`. Median 10 clear dates
per field-year; all 347 scored, none dropped.

Scoring is **always within crop**. Cotton is 72% conservation-till in this
sample and peanuts 27%, so any pooled number is partly just reading the crop.

### Scorecard: every category, counted

Taking the survey as truth. This is the at-a-glance view; the sections that
follow explain each one and why the number is what it is. **Read the warning
under the tables before quoting a single figure from them.**

| category | n | correct | wrong | rate |
|---|---|---|---|---|
| Crop type (CDL) | 347 | 280 | 67 | **80.7%** |
| Crop type, boundaries at purity ≥ 75% | 291 | 258 | 33 | **88.7%** |
| Cover crop, shipped thresholds | 346 | 199 | 147 | **57.5%** |
| Cover crop, recalibrated — cotton | 182 | 137 | 45 | 75.3% |
| Cover crop, recalibrated — peanuts | 164 | 104 | 60 | 63.4% |
| Tillage (soil armor) — cotton | 174 | 133 | 41 | 76.4% |
| Tillage (soil armor) — peanuts | 157 | 131 | 26 | 83.4% |

**Crop type**, per crop treated as the positive class:

| positive class | TP | FP | FN | TN | precision | recall |
|---|---|---|---|---|---|---|
| Cotton | 156 | 25 | 27 | 139 | 86.2% | 85.2% |
| Peanuts | 124 | 17 | 40 | 166 | 87.9% | 75.6% |

Precision is alike, but peanuts are *missed* far more — 40 of 164 peanut
field-years carry another label, mostly cotton. Half of all 67 errors sit in
the 16% of rows with CDL purity under 75%.

**Cover crop** (positive = a cover crop was grown):

| | TP | FP | FN | TN | sensitivity | specificity |
|---|---|---|---|---|---|---|
| shipped, NDVI ≥ 0.35 | 188 | **144** | 3 | 11 | 98.4% | **7.1%** |
| cotton, recalibrated ≥ 0.449 | 111 | 42 | 3 | 26 | 97.4% | 38.2% |
| peanuts, recalibrated ≥ 0.700 | 25 | 8 | **52** | 79 | **32.5%** | 90.8% |

97% of the shipped detector's errors are false positives. Recalibrating cotton
clears 102 of those 144 false alarms while losing nothing — false negatives
stay at 3.

**Tillage** (positive = conservation till, >30% residue; the 16 rows in the
15–30% class are excluded as too few to fit or test):

| | TP | FP | FN | TN | sensitivity | specificity |
|---|---|---|---|---|---|---|
| cotton, armor ≥ 0.437 | 105 | 20 | 21 | 28 | 83.3% | 58.3% |
| peanuts, armor ≥ 0.594 | 24 | 8 | **18** | 107 | **57.1%** | 93.0% |

#### The warning: accuracy on an imbalanced class rewards silence

**Both peanut detectors reach their headline accuracy largely by declining to
fire.** Peanuts are 27% conservation-till and 47% cover-cropped, so the
accuracy-optimal threshold exploits that imbalance. Peanut cover-crop detection
misses **52 of 77** real cover crops. Peanut tillage misses **18 of 42**
conservation fields. The 83.4% in the first table is the best number in this
entire validation, and it belongs to a detector that finds well under half of
what it is looking for.

If the platform's purpose is to *find* conservation practice, those two rows
are close to meaningless as stated. Tune for recall, and report
sensitivity/specificity pairs rather than accuracy. Cotton is the opposite case
and genuinely useful: 83.3% sensitivity on tillage, 97.4% on cover crop after
recalibration.

Two things the counts do not show. The tillage and recalibrated-cover
thresholds are **fitted in sample**, so they are the optimistic view —
cross-validated, cotton tillage falls to 73.8%. And every cover-crop figure
rests on the unresolved winter-mapping assumption recorded at the end of that
section.

Reproduce all of the above with `validation/confusion.py`.

### CDL crop labels: 81% agreement, and boundary purity is the gate

Scored first, because CDL is an **input**, not an output. Phenology picks its
crop lags from the CDL label and the cover-crop logic keys off it, so CDL's
error rate bounds everything downstream. One CropScape clip per surveyed
field-year, dominant class against the grower's reported crop; all 347 scored.

| | agreement |
|---|---|
| overall | **80.7%** |
| Cotton (n=183) | 85.2% |
| Peanuts (n=164) | 75.6% |
| by year | 84.3% (2018), 83.1% (2019), 74.0% (2020), 79.7% (2021) |

Errors are overwhelmingly **cotton ↔ peanuts**: 42 of the 67 disagreements.
Corn takes another 18. Nothing exotic — no field is being called water or
forest.

**Boundary purity predicts agreement almost completely**, which is the
practical result:

| dominant CDL class covers | n | agreement |
|---|---|---|
| < 60% of the field | 31 | **12.9%** |
| 60–75% | 25 | 72.0% |
| 75–90% | 90 | 90.0% |
| > 90% | 201 | 88.1% |

A boundary whose dominant CDL class is under 60% of its area agrees with the
grower one time in eight. Gating on purity ≥ 75% keeps 84% of the rows and
lifts agreement from 80.7% to **88.7%**; tightening further buys nothing
(≥90% actually dips to 88.2%). **That is a shippable rule**: the CDL tab's
boundary check already computes this number, and it should be a gate, not
advice.

The two failure modes are different, and the split is by field size:

| | grower's crop still present at | dominant class |
|---|---|---|
| disagreements over 200 ac (n=19) | median **32%** of the field | median **51%** |
| disagreements at or under 200 ac (n=48) | median **5.6%** | median 84.6% |

Large disagreeing boundaries are genuine two-crop mosaics — the grower's crop
is right there, just not dominant — which is the multiple-management-unit
problem the boundary check was built for. Fields over 200 acres agree only
56.8% of the time against ~85% everywhere else. Small disagreeing fields are a
different animal: high purity, and the grower's crop essentially absent. That
is either real CDL misclassification or a misremembered survey answer, and
this dataset cannot tell which.

**CDL error does not explain the soil armor results.** The obvious worry was
that armor's mediocre tillage performance was really CDL noise leaking through
the within-crop scoring. It is not:

| armor AUC | Cotton | Peanuts |
|---|---|---|
| all rows | 0.735 | 0.791 |
| CDL agrees with grower | 0.756 | 0.773 |
| purity ≥ 75% | 0.720 | 0.771 |
| both | 0.749 | 0.757 |

Cotton nudges up, peanuts goes *down*, nothing moves more than a few points.
Cleaning the crop labels does not rescue the metric, which leaves the
cover-crop confound below as the real constraint. Note also that the armor
scores were computed within the **grower's** crop, not CDL's, so they never
depended on CDL being right in the first place.

Reproduce with `validation/run_cdl.py` then `validation/analyse_cdl.py`.

### Separating conservation (>30% residue) from conventional (<15%)

AUC, and 5-fold cross-validated accuracy with the threshold fitted on the
training folds only. Folds are split **by field, not by row**, so repeat years
of the same field never straddle the split — 347 rows over 226 fields would
otherwise leak.

| | Cotton AUC | Cotton CV acc. | Peanuts AUC | Peanuts CV acc. |
|---|---|---|---|---|
| soil armor (1 − fBS) | 0.735 | 73.8% ± 7.2 | **0.791** | **83.4% ± 5.4** |
| median NDTI | 0.743 | **77.1% ± 3.3** | 0.766 | 77.6% ± 5.8 |
| minimum NDTI (old metric) | 0.744 | 74.7% ± 6.3 | 0.709 | 77.9% ± 6.9 |
| residue fraction (fNPV) | 0.698 | 72.4% ± 10.3 | 0.658 | 73.9% ± 7.1 |
| *majority-class baseline* | — | *72%* | — | *73%* |

Three things to take from this, in order of how much they should change your
expectations:

**1. On cotton, soil armor barely beats guessing.** 73.8% against a 72%
baseline, with a ±7.2 spread that swallows the difference. Median NDTI — a
one-line index, no unmixing — does better at 77.1% and is the most stable
column in the table. The elaborate metric is not earning its complexity here.

**2. The balanced pilot was optimistic, as pilots are.** A 60-field stratified
sample scored armor at 0.822 / 0.844 AUC. The full set gives 0.735 / 0.791.
Nothing was wrong with the pilot; it just sampled away the marginal cases. If
you have seen the pilot numbers quoted anywhere, these supersede them.

**3. Soil armor is mostly detecting the cover crop.** This is the finding that
matters, and it is visible directly in the group medians:

| crop | tillage | cover crop | median armor | n |
|---|---|---|---|---|
| Cotton | < 15% (conventional) | No | **0.344** | 35 |
| Cotton | < 15% (conventional) | Yes | **0.604** | 13 |
| Cotton | > 30% (conservation) | No | 0.507 | 31 |
| Cotton | > 30% (conservation) | Yes | 0.625 | 95 |
| Peanuts | < 15% | No | 0.410 | 71 |
| Peanuts | < 15% | Yes | 0.401 | 44 |
| Peanuts | > 30% | No | 0.580 | 9 |
| Peanuts | > 30% | Yes | 0.614 | 33 |

A conventionally tilled cotton field **with** a cover crop reads 0.604 —
statistically indistinguishable from a conservation-tilled field at 0.625, and
far above a conventionally tilled field without one at 0.344. The two practices
are confounded in the population: 75% of conservation-till cotton has a cover
crop against 27% of conventional (peanuts: 79% vs 38%).

Hold cover crop constant and the tillage signal largely goes:

| among fields with **no** cover crop | Cotton AUC | Peanuts AUC |
|---|---|---|
| soil armor | 0.670 | 0.695 |
| median NDTI | 0.703 | 0.709 |
| residue fraction (fNPV) | **0.716** | 0.606 |

And asked directly whether a field had a cover crop, armor scores **AUC 0.793
on cotton** — higher than it scores for tillage on the same fields.

### What this means

**Soil armor works. It is being asked the wrong question.** The metric is
`1 − fBS`: cover from any source, deliberately, because that is what resists
erosion. A tilled field under a thick cover crop *is* protected soil, and armor
correctly says so. The survey's tillage variable is a different quantity, and
the apparent tillage signal was running through cover-crop adoption.

So:

- **For erosion exposure, keep armor** and report it as cover, not tillage.
  This is the defensible framing and the one worth taking to the platform.
- **For tillage specifically, armor is the wrong tool.** The residue-only
  measures are more appropriate, and `fNPV` is the best of them on cotton once
  the cover-crop confound is removed (0.716). That it ranks worst on the
  confounded comparison and best on the clean one is the whole story in one
  number.
- **Do not present a single number as "tillage detection accuracy."** Any such
  figure from this dataset is partly a cover-crop detector.

### Cover crop detection: the thresholds are Iowa's, and Georgia is not Iowa

347 field-winters, one NDVI series each over Oct 15 → May 10, scored against
the grower's yes/no. This is the run that found a real defect.

**The shipped detector is close to a constant classifier on this dataset.** It
returned "likely cover crop" for **332 of 347** fields:

| | accuracy | sensitivity | specificity |
|---|---|---|---|
| shipped thresholds | **57.5%** | 98.4% | **7.1%** |
| *majority-class baseline* | *55.2%* | | |

It finds 188 of 191 real cover crops and raises 144 false alarms on 155
no-cover fields. A verdict that says yes to everything is worth almost nothing.

**The cause is climate, not code.** `CC_GREEN_MIN` (0.30) and `CC_STRONG`
(0.35) are documented in `covercrop.R` as Iowa-typical, where winter residue
sits at NDVI 0.10–0.25. A Georgia winter does not look like that:

| max NDVI in the window | cover-crop fields | **no-cover fields** |
|---|---|---|
| ≥ 0.30 | 99.5% | **98.1%** |
| ≥ 0.35 (shipped) | 99.0% | **92.9%** |
| ≥ 0.45 | 93.2% | 74.2% |
| ≥ 0.65 | 47.1% | 17.4% |
| ≥ 0.75 | 27.7% | 3.9% |

The median no-cover field in Georgia peaks at **NDVI 0.53** — winter weeds,
volunteer and a mild climate put green on ground nobody planted. The residue
ceiling the detector was built around does not exist here.

**The underlying signal is real but modest**, and it is much better on cotton:

| | AUC | CV accuracy | baseline |
|---|---|---|---|
| Cotton, max NDVI | **0.783** | **75.2% ± 6.3** | 62.6% |
| Peanuts, max NDVI | 0.642 | 60.6% ± 7.8 | 53.0% |
| Peanuts, mean NDVI | — | 63.0% ± 7.9 | 53.0% |

Accuracy is 5-fold, threshold fitted on training folds only, split by field.
Recalibrating cotton from 0.35 to a fitted **0.449** moves specificity from
11.8% to 38.2% and accuracy from 67.0% to 75.3% — still a weak detector, but
no longer a broken one. The fitted peanut threshold is far higher (≈0.70) and
still only reaches 63%.

**Late harvest is not the problem.** I expected standing cotton on 15 October
to inflate detection, so the raw series was kept to test it. Moving the window
start to 1 December improves cotton AUC only 0.783 → 0.799 and pooled 0.719 →
0.738. Worth adopting, not worth much.

**What this means for the platform.** Cover-crop thresholds must be regional,
fitted per climate and probably per crop, and the current constants should
carry a region tag rather than being global. Reporting "likely cover crop" at
98% sensitivity and 7% specificity is worse than reporting nothing, because it
looks like a finding. Of everything in this validation, this is the defect most
likely to embarrass a production deployment, and it was invisible until real
ground truth arrived — which is the argument for ground truth in one example.

Reproduce with `validation/run_cover.R` then `validation/analyse_cover.py`.
The raw per-date NDVI is kept in `validation/cover_series.csv`, so window and
threshold changes can be re-tested without re-running the 66-minute extraction.

**One unresolved assumption.** A survey row for crop year Y is read as the
winter *before* that crop (`fall_year = Y − 1`). 62 fields have consecutive
survey years, giving 82 shared winters, but the two candidate answers disagree
on only 18 — too few to settle it. If the survey meant the following winter,
every row here is shifted by one year and these numbers understate the method.

### Caveats that limit all of the above

- **Self-reported practice, not measured residue.** No line transects. A
  grower's "conservation tillage" is a recollection of an operation, not a
  percentage of ground covered. Some of the unexplained variance is the label.
- **Georgia only, two crops, four years.** Soils, residue types and spring
  rainfall all differ elsewhere. Nothing here transfers unexamined.
- **The reduced-till class (15–30%) is unusable.** n = 9 cotton, n = 7 peanuts.
  It sits between the other two and is excluded from every score above, which
  means all of this is a two-class problem, not the three-class one a platform
  would actually want.
- **`armor` and `f_bs` are the same test.** Armor is 1 − fBS, so their AUCs are
  identical by construction. Counting them as two agreeing methods would be
  double-counting one.
- **`ARMOR_BREAKS` is still not refit.** The fitted in-sample thresholds are
  armor ≥ 0.437 (cotton) and ≥ 0.594 (peanuts) — crop-specific, and both
  differ from the shipped 0.40 / 0.75. They are recorded here rather than
  written into the source, because fitting a threshold on 226 Georgia fields
  and shipping it as a constant is the exact mistake the status block at the
  top of this README warns about.

Reproduce with `validation/analyse.py`; inputs are `validation/truth.csv` and
`validation/metrics.csv`, boundaries in `validation/boundaries/`.

### Still untested

Planting and harvest dates remain untested against anything — the survey does
not carry them, and they are the input the phenology-dependent windows all
rest on. Cover crop detection **has** now been validated; see above.

## Read this before quoting any number

**Almost nothing is calibrated.** Every threshold and crop lag is a
literature-typical starting value, not fitted to ground truth. Soil armor is
the sole exception and its validation comes with heavy caveats — see the
section above. Regressing the planting estimates against grower-reported dates
is the single highest-value next step, and it is what would turn "±14 days"
into a defensible figure.

**Soil armor is a cover metric, not a tillage metric.** Validation showed its
apparent tillage signal running largely through cover-crop adoption. Report it
as cover.

**Cover crop verdicts are evidence, not findings, and in the South they are
barely even that.** NDVI sees green, not intent; volunteer grain, winter weeds
and a grassed waterway inside the boundary all look similar. Measured against
347 Georgia field-winters the shipped thresholds reach 7.1% specificity — see
the validation section. Refit them per region before surfacing the verdict.

**The model assumes an annual row crop, and checks.** Planting is inferred from
a bare-soil-to-canopy transition, which a perennial stand never makes. A season
that stays green almost all year reports no dates and says why — on the
Washington pivot that is 4 of 7 seasons, and CDL independently calls three of
them Alfalfa. Winter-flooded rice ground reports its dates with the flood
attached as a caveat, and its cover crop verdict reads "not detectable" rather
than "none".

**Boundary quality gates everything, and this is now measured.** A boundary
whose dominant CDL class covers under 60% of its area matches the grower's
reported crop **12.9%** of the time, against ~89% for clean boundaries. Fields
over 200 acres agree 56.8% of the time — they are usually several management
units in one outline. Check the CDL tab first, and treat purity ≥ 75% as a
gate rather than advice.

Each implementation's README has the detail: `r/README.md` for the app and the
demo library, `python/README.md` for the module map, the deliberate differences
between the two, and the environment gotchas.
