# Methods

Every formula, constant and chart in this pipeline, written for someone who
wants to check the reasoning rather than run the code. It describes the state of
`main` at the time of writing and is meant to be read alongside the source: each
section names the file it documents.

Two things to hold throughout. **Almost nothing here is calibrated** — the
exceptions are CDL crop labels, soil armor and cover crop detection, all tested
against a 347-field-year Georgia farmer survey and reported in the root
`README.md`. And **every constant fitted on this library was fitted on eleven
fields**, which is not a sample anyone should generalise from.

---

## 1. Imagery: from COG to reflectance

`r/R/imagery.R`, `python/fieldrs/imagery.py`

### Source and selection

Sentinel-2 L2A from Microsoft Planetary Computer's STAC API. Scenes are searched
by the field's bounding box and filtered to `eo:cloud_cover < 70` (scene-level,
`max_cloud`). Assets are read as Cloud-Optimized GeoTIFFs over HTTP range
requests through GDAL's `/vsicurl/`, so only the window covering the field is
transferred, not the scene.

### How a COG read works, and which machine does it

Worth stating plainly, because it is usually assumed backwards: **the reading is
done locally.** Microsoft serves bytes and nothing else.

A Cloud-Optimized GeoTIFF is an ordinary GeoTIFF written so it can be read in
pieces. Measured on a Sentinel-2 B04 asset:

| | |
|---|---|
| Full raster | 10,980 × 10,980 px (≈230 MB uncompressed) |
| Internal layout | **512 × 512 px tiles**, not full-width strips |
| Compression | deflate, per tile |
| Embedded overviews | levels 2, 4, 8, 16 |

Tiling and the front-loaded index are the whole trick, and they are a property
of how the file was *written*. That is the host's contribution. The other is an
HTTP server that honors `Range` requests — Azure Blob Storage answers
`bytes=1234-5678` with those bytes and has no idea it is serving geospatial
data.

Everything else happens in GDAL, on the machine running this pipeline, through
`terra` in R and `rasterio` in Python:

1. Range-request the first few kilobytes; read the TIFF header and tile index.
2. Reproject the field boundary into the raster's CRS.
3. Compute which 512 px tiles the boundary overlaps.
4. Range-request exactly those byte offsets.
5. Decompress and assemble the array.

On the 6.6 ha Georgia field that comes to a **20 × 36 px window, 0.0006% of the
scene**. The reduction is not the host being clever on our behalf; it is GDAL
declining to ask for the rest.

Three consequences follow, and they are why this matters beyond mechanism:

- **There is no server-side component.** COG works against dumb storage — Azure
  Blob, S3, a static Apache directory. Nothing needs to run at the far end.
- **This traffic is not API traffic.** Byte-range fetches against static files
  never touch the rate-limited STAC or token endpoints (§11), which is why the
  request volume there stays small however many scenes are read.
- **It is why the catalog is swappable** (§11). The reading machinery is ours
  and does not care whose bucket the bytes come from.

Band identifiers used:

| Name here | Sentinel-2 | Center | Native res. |
|---|---|---|---|
| `blue` | B02 | 490 nm | 10 m |
| `green` | B03 | 560 nm | 10 m |
| `red` | B04 | 665 nm | 10 m |
| `rededge1` | B05 | 705 nm | 20 m |
| `nir` | B08 | 842 nm | 10 m |
| `swir16` | B11 | 1610 nm | 20 m |
| `swir22` | B12 | 2190 nm | 20 m |
| `scl` | SCL | — | 20 m |

`coastal` (B01, 60 m), `rededge2` (B06), `rededge3` (B07) and `nir08` (B8A, all
20 m) are also mapped but unused by any index registered here.

20 m bands are resampled onto the 10 m grid. **SCL is resampled nearest
neighbor**; a bilinear resample of a categorical mask invents classes that do
not exist.

### Scaling and the baseline offset

Stored DNs become bottom-of-atmosphere reflectance as

```
rho = (DN + offset) / 10000
```

`offset` is **0** for scenes processed under baseline < 04.00 and **−1000** for
04.00 and later (ESA changed the encoding in January 2022). The value is read
per scene from the item's processing baseline rather than assumed. Skipping this
shifts every index across the 2022 boundary and produces a step change that
looks like a management event.

### Cloud masking

Pixels are kept where SCL ∈ {4, 5, 6, 7} — vegetation, bare soil, water, unclassified.
Everything else (cloud, cirrus, shadow, snow, saturated, defective) is set to NA.

Snow removal is deliberate and has a consequence worth stating: snowy dates
disappear from the record rather than reading as bare soil, which is correct but
thins winter coverage. Every off-season output therefore reports `n_obs`
alongside the value.

### Per-scene field statistic

For each scene and each index, pixels whose center falls inside the boundary are
taken and the scene is either kept or dropped:

```
valid_frac = (clear field pixels) / (field pixels)
keep the scene if valid_frac >= min_valid          min_valid = 0.75
```

From the kept pixels the pipeline records `mean`, `median`, `sd`, `p10`, `p90`,
`n`, `valid_frac` and the scene's cloud cover. **`mean` is what every downstream
model uses.**

### Same-date de-duplication

Neighboring Sentinel-2 tiles overlap, so a field near a seam appears in two
scenes on one date. Left alone these become duplicate x-values in the phenology
spline and double-weight that date. One row per (index, date) is kept, ranked by
`valid_frac` descending then `cloud` ascending.

---

## 2. Spectral indices

`r/R/indices.R`, `python/fieldrs/indices.py`. All are computed per pixel and then
averaged over the field by §1, **not** computed from field-average reflectance —
the two differ for any non-linear index.

| Name | Formula | Display range |
|---|---|---|
| `ndvi` | (NIR − Red) / (NIR + Red) | −0.2 … 1 |
| `evi2` | 2.5 (NIR − Red) / (NIR + 2.4 Red + 1) | −0.2 … 1.2 |
| `ndwi` | (Green − NIR) / (Green + NIR) | −1 … 1 |
| `ndmi` | (NIR − SWIR1.6) / (NIR + SWIR1.6) | −1 … 1 |
| `ndti` | (SWIR1.6 − SWIR2.2) / (SWIR1.6 + SWIR2.2) | −0.2 … 0.6 |
| `ndi7` | (NIR − SWIR2.2) / (NIR + SWIR2.2) | −1 … 1 |
| `ndsvi` | (SWIR1.6 − Red) / (SWIR1.6 + Red) | −1 … 1 |
| `ndre` | (NIR − RedEdge1) / (NIR + RedEdge1) | −0.2 … 1 |
| `savi` | 1.5 (NIR − Red) / (NIR + Red + 0.5) | −0.2 … 1.2 |
| `gcvi` | (NIR / Green) − 1 | 0 … 12 |
| `dfi` | 100 (1 − SWIR2.2/SWIR1.6) (Red/NIR) | −5 … 45 |

`ndti`, `ndi7` and `ndsvi` are the multispectral residue indices evaluated by
Sonmez & Slater (2016). `dfi` is the Dead Fuel Index of Cao et al. (2010). The
vegetation and water indices are the standard published forms: `ndvi` from
Rouse et al. (1974), `savi` from Huete (1988), `evi2` from Jiang et al. (2008),
`ndmi` from Gao (1996), `ndwi` from McFeeters (1996), `ndre` from Gitelson &
Merzlyak (1994) and `gcvi` from Gitelson et al. (2003). Sources are listed in
full under *References*, along with the four formulas here that do **not** have
one.

Two naming collisions worth stating, because both appear in the literature
under the other's name. Gao's NIR−SWIR1.6 index was published as NDWI and is
now usually called NDMI, which is what this table calls it; McFeeters' Green−NIR
index, also published as NDWI, is the one this table calls `ndwi`. They measure
different things — vegetation water content and open water respectively.

**CAI is not computable here.** The hyperspectral cellulose absorption index the
residue literature favors needs three narrow bands inside 2000–2200 nm;
Sentinel-2 B12 is a single ~180 nm band covering the whole feature.

### Two documented failure modes of NDTI

1. **Soil moisture moves it more than tillage does.** On the Iowa field, 18 and
   20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 — a four-fold
   swing from rain with no change in residue. Single-date NDTI is not usable;
   the validated approach is multitemporal (minimum NDTI over a bare-soil
   window, Zheng et al. 2013).
2. **It does not separate residue from green cover.** NDTI reads 0.15–0.24 over
   a cover crop because green canopy absorbs in the SWIR. This is the defect
   that motivated §4.

---

## 3. Smoothing: the daily curve

`daily_series()` in `r/R/extract.R`; `python/fieldrs/phenology.py`

Observations are irregular because cloud decides when you get one. Threshold
crossings need a continuous curve, so a penalized smoothing spline is fitted to
(date, mean) and predicted onto a **1-day grid**.

- **R:** `stats::smooth.spline(x, y, spar = 0.35)`, and `spar = 0.5` inside the
  cover-crop module, which fits a shorter window.
- **Python:** `scipy.interpolate.make_smoothing_spline` at a **fixed penalty
  `lam = 50.0`**, not GCV-selected.

The fixed penalty is not arbitrary. Letting GCV choose per series put peak NDVI
up to 0.081 above the highest actual observation in 41 of 77 seasons — a
physically impossible curve — and disagreed with R on 22 seasons. At `lam = 50`
the two implementations disagree on 3.

**Gaps are not bridged.** Any day further than `max_gap / 2 = 22.5` days from the
nearest real observation is set to NA, so a two-month winter hole stays a hole
instead of becoming a confident-looking line.

The spline is always fitted to the window in question plus a margin, never to the
whole multi-year record: one smoothing parameter cannot represent six annual
cycles, and fitting globally flattens the off-season features being measured.

---

## 4. Soil armor: NDVI–DFI ternary unmixing

`r/R/armor.R`, `python/fieldrs/armor.py`

### Why it replaced minimum NDTI

NDTI measures crop residue, which is only half of soil cover: a field under a
living cover crop or a perennial stand is protected just as well as one under
stubble, and NDTI scores it as bare. On this library that error was not subtle —
the Washington alfalfa pivot, the best-protected soil present, ranked **last of
eleven**. It now ranks first.

### Where this comes from

The model is published, not invented here. Linear unmixing of fPV / fNPV / fBS
inside a triangle formed by NDVI against a shortwave residue index is
Guerschman et al. (2009), who built it with the hyperspectral Cellulose
Absorption Index over Australian savanna. The specific NDVI–DFI pairing this
pipeline uses — substituting Cao's broadband Dead Fuel Index for CAI, which is
what makes it computable on Sentinel-2 — is Wang et al. (2019), validated on
MODIS over the Xilingol grasslands.

**What is ours is the endmember values, not the method.** Guerschman and Wang
supply the triangle; the three vertex coordinates in §4 were fitted on 65,555
cloud-free pixels from six fields in this library and are the part that will
not transfer. See the porting note in `README.md`.

Worth stating plainly because it cuts both ways: the method being published
means it is prior art, and it also means the accuracy Wang reports is not ours
to claim. Their validation was grassland at 500 m; this is cropland at 10 m.

### The model

Each pixel is placed in (NDVI, DFI) space and decomposed into three fractions
that sum to one:

- **fPV** — photosynthetic vegetation, living green cover
- **fNPV** — non-photosynthetic vegetation: residue, stubble, litter
- **fBS** — bare soil

with

```
DFI = 100 (1 − SWIR2.2/SWIR1.6) (Red/NIR)
```

The first term is the lignocellulose absorption near 2100 nm that residue has and
soil does not; the second suppresses green canopy.

Solving the linear mixture means inverting

```
        | NDVI_PV   NDVI_NPV   NDVI_BS |   | f_PV  |   | NDVI |
    A = | DFI_PV    DFI_NPV    DFI_BS  | , | f_NPV | = | DFI  |
        |    1          1          1   |   | f_BS  |   |  1   |
```

`A⁻¹` is computed once at load time and each fraction is an affine function of
(NDVI, DFI), so the whole decomposition is three multiply-adds per pixel.

### Endmembers

Fitted on **65,555 cloud-free pixels across six fields** spanning permanent
green, heavy residue and clean tilled soil:

| Endmember | NDVI | DFI |
|---|---|---|
| PV (living canopy) | 0.961 | 1.212 |
| NPV (residue) | 0.232 | 25.642 |
| BS (bare soil) | 0.183 | 3.296 |

NPV and BS differ by only 0.05 in NDVI and by 22 in DFI — **DFI is what
separates residue from soil; NDVI alone cannot.**

Water and deep shadow were excluded before fitting, and that mattered: as NIR
collapses, DFI's Red/NIR term explodes, so the highest-DFI pixels in the raw pool
were flooded rice and cloud shadow rather than residue. Left in, they put the NPV
vertex at NDVI −0.02, which is not a surface any crop field has.

### Clamping and masking

Spectral variability puts roughly **one pixel in eight** just outside the
triangle. Those are clamped to [0, 1] and renormalized to sum to one, rather than
discarded: a pixel at −0.03 is a pure endmember with noise on it, not a
measurement failure.

Pixels below **NDVI 0.05** are water or deep shadow, where DFI is meaningless.
They are masked to NA so they drop out of the field average instead of corrupting
it.

```
armor = 1 − fBS
```

### The summary statistic: time-weighted, not median or minimum

Over the reporting window, armor is summarized by a **trapezoidal average over
observation dates**:

```
armor_bar = SUM[ (t_i+1 − t_i) (a_i + a_i+1) / 2 ] / (t_n − t_1)
```

Minimum was right for NDTI, where a single wet morning could quadruple the
reading. A cover fraction is a different quantity, so this started as a median —
but the cross-implementation check caught that being fragile: on the Georgia
field in 2026 the two implementations saw 7 and 8 observations of a steeply
falling series and the extra date moved the median from 0.59 to 0.72. The
trapezoidal average gave 0.500 against 0.497.

It is also the right quantity on its own terms: soil is exposed to erosion over
*time*, so what matters is average cover through the window, not the middle value
of however many scenes happened to be clear.

### Extraction span vs reporting window — these are different

- **`ARMOR_SPAN = 01-01 … 12-31`.** The imagery pass covers whole calendar years,
  so the charts show fall tillage, cover crop establishment and overwinter
  residue loss.
- **The reported figure still comes from the pre-planting window only**, from
  `residue_window()` (§6). Widening the extraction did not change any number the
  validation scored.

`ARMOR_MIN_OBS = 3`: fewer usable observations in the window and the season is
reported as unreadable rather than summarized.

### Provisional bands

`ARMOR_BREAKS = (0.40, 0.75)` → "mostly bare" / "partly covered" / "well
covered". These are this library's own distribution, rounded. Validation suggests
crop-specific values near 0.44 (cotton) and 0.59 (peanuts); they were
deliberately **not** written into the source, because fitting a threshold on 226
Georgia fields and shipping it as a global constant is the mistake the whole
document warns about.

---

## 5. Phenology: planting and harvest

`r/R/phenology.R`, `python/fieldrs/phenology.py`

Operates on the daily NDVI curve (§3) for one calendar year. Requires ≥10
observations and ≥60 non-NA days in the curve.

**1. Peak.** Maximum of the smoothed curve inside the peak window, **1 June –
15 September** by default. If `peak < 0.45`, the season is reported as "no summer
crop detected" — fallow, or a failure.

**2. Applicability.** The annual-row-crop model is abandoned if

```
min(curve) >= 0.30   AND   fraction of year above NDVI 0.50 >= 0.80
```

Both conditions, not either. A threshold on the minimum alone does not work: a
heavily cover-cropped Maryland corn field bottoms out at 0.31 and the alfalfa
pivot at 0.33, which is not a gap you can put a threshold in. What separates them
is time-above: alfalfa years sit above 0.50 for 86–95% of the year, every genuine
row-crop year at or below 72%.

**3. Baseline.** Within 1 March → peak − 20 days, take `gmin = min(curve)` and
then the **last** day satisfying `value <= gmin + 0.06`.

Taking the last near-minimum rather than the global one is deliberate. On a
cover-cropped field the curve dips twice before the cash crop: winter dormancy,
then cover-crop termination. Anchoring on the global minimum reads the spring
cover-crop green-up as crop emergence — which produced a February planting date
for corn before it was fixed.

**4. Green-up.** With `amp = peak − baseline` (abandon if `amp < 0.2`), the first
day on the rising limb where

```
value >= baseline + 0.20 * amp
```

**5. Planting** = green-up − crop lag. Lags are days from planting to 20% of
amplitude, **literature-typical and uncalibrated**:

| Crop | Lag (days) |
|---|---|
| Corn | 21 |
| Soybeans | 18 |
| Winter Wheat | 0 |
| Cotton | 24 |
| Sorghum | 20 |
| Rice | 20 |
| *default* | 20 |

Listed in the order they appear in `CROP_LAGS`, so the table can be checked
against the source line by line. **Winter wheat is zero because it is planted
the previous autumn** — the spring rise is regrowth from an established stand,
not emergence, so there is no lag to subtract. `default` applies to any crop
CDL reports that is not named above.

**6. Harvest.** Anchored on the **post-peak minimum**, not the spring baseline.
Requires a real drop, `peak − post_trough >= 0.35 * amp`, then the first day at or
below `post_trough + 0.20 (peak − post_trough)`.

Spring-anchoring fails wherever something green follows the cash crop: on a
cover-cropped cotton field NDVI falls after defoliation then climbs again without
reaching the spring floor, and a spring-anchored threshold reported **no harvest
at all for five seasons running**. The amplitude guard stops a season still under
way being read as an early harvest.

**7. Uncertainty from actual observation density.** Rather than quoting a flat
±14 days, the window is widened by the real gap in observations around each
crossing:

```
window = max(14, ceil(nearest observation gap))
```

Confidence is `high` if the larger gap ≤ 10 d, `medium` if ≤ 20 d, otherwise
`low`. A crossing sitting in the middle of a three-week cloud gap is a guess and
says so.

**Untested.** No planting or harvest estimate in this pipeline has ever been
compared against a grower-reported date. This is the largest uncalibrated
component.

---

## 6. Off-season windows

`residue_window()` in `r/R/phenology.R`

The bare-soil period between one crop's harvest and the next crop's planting:

```
start = harvest(year−1) + 7      RESIDUE_HARVEST_LAG
end   = planting(year)  − 3      RESIDUE_PLANT_LEAD
```

Either end falls back to fixed dates when phenology could not supply it —
`start = Oct 15 (year−1)`, `end = May 10 (year)` — the same fallbacks the
cover-crop module uses, so the two agree on what "the off-season" means. The
`spring` season additionally clips `start` to 1 March. A window whose end is at or
before its start returns nothing rather than a negative span.

The 7-day lag lets residue settle after harvest traffic; the 3-day lead stops
before planting disturbs the surface.

---

## 7. Cover crop detection

`r/R/covercrop.R`, `python/fieldrs/covercrop.py`

Window Oct 15 (fall year) → May 10 (following year), narrowed to
`harvest + 7 … planting − 3` when phenology supplies them.

| Constant | Value | Meaning |
|---|---|---|
| `CC_RESIDUE_MAX` | 0.25 | NDVI ceiling for crop residue |
| `CC_GREEN_MIN` | 0.30 | level sustained green must reach |
| `CC_STRONG` | 0.35 | level for a confident call |
| `CC_WATER_NDVI` | 0.05 | open water |
| `CC_WATER_SHARE` | 0.25 | share of window flooded before "not detectable" |

`green_days` is the count of days in the window where the smoothed curve
(`spar = 0.5`, fitted to the window ±45 days) is at or above `CC_GREEN_MIN`.

Verdicts, in order of precedence: winter cash crop (from CDL) → double crop →
`likely cover crop` (`max ≥ 0.35` and ≥2 observations above 0.30) → `possible
cover crop` (`max ≥ 0.30`) → `no cover crop detected`. Perennial stands and
persistently flooded windows return "not applicable" and "not detectable"
respectively — which are different answers from "none".

> **These thresholds are measured wrong outside the region they came from.** Against 347
> Georgia field-winters the shipped detector said "likely cover crop" to 332 of
> 347 fields: **98.4% sensitivity, 7.1% specificity, 57.5% accuracy** against a
> 55.2% majority-class baseline. The cause is climate, not code — 98.1% of
> *no-cover* Georgia fields exceed NDVI 0.30, and the median one peaks at 0.53.
> The residue ceiling the detector is built around does not exist there. Refit
> per region before surfacing the verdict.

---

## 8. Crop type: USDA CDL

`r/R/cropland.R`, `r/R/cdl_local.R`, `python/fieldrs/cropland.py`

30 m annual crop-type raster, CONUS, EPSG:5070 (Albers equal-area). Read from a
local bulk copy when present, falling back to the CropScape API.

**Clipping uses center-in-polygon (`touches = FALSE`).** The default — every cell
the polygon so much as clips — returned 233 cells (21.0 ha) on a 17.2 ha field,
**22% too many**, and those extra cells carry the neighboring field's crop. That
inflates every CDL area figure and biases the boundary check toward "split".

Local and API agree on the dominant crop for **346 of 347** field-years; the one
disagreement is 33.0% Corn against 32.7% Peanuts. Against polygon geometric area
the API is +0.06% mean and local +0.23%, both inside 30 m pixel quantization.

### Boundary check (`cdl_split_advice`)

Per year, the dominant class and its share. Then, on the value matrix across
years:

```
dom_k    = modal class of year k
dis_ik   = 1 if pixel i differs from dom_k in year k, else 0
persist_i = SUM_k dis_ik / (years pixel i was observed)
flagged_i = persist_i >= 0.6                      SPLIT_PERSIST
frac      = flagged pixels / field pixels
```

Verdict: **split** if `frac >= 0.12` (`SPLIT_MIN_FRAC`) and the largest flagged
block `>= 2.0 ha` (`SPLIT_MIN_HA`); **trim** instead if ≥60% of the flagged area
is non-crop (farmstead, road, water, woodland); otherwise **single unit**.

This is computed on the extracted value matrix rather than with `terra::app()`
across layers — the per-layer rasters come back from `app()` without values
materialised, and stacking them yields an all-NA result that silently reports no
disagreement at all, however split the boundary actually is.

> **Measured:** boundary purity predicts crop agreement almost completely. Under
> 60% single-crop, CDL matched the grower **12.9%** of the time; above 75%,
> **88.7%**. Gating at ≥75% keeps 84% of rows and lifts overall agreement from
> 80.7% to 88.7%.

### Hand-drawn boundaries

`r/R/draw.R`. A traced polygon is validated (`st_make_valid`), area-checked
(0.5–500 ha) and CONUS-checked, then its CDL history is read and shown *before*
any imagery is fetched. Purity bands in the verdict are the validation numbers
above.

---

## 9. Charts

Every figure is base R graphics. No ggplot2 anywhere.

### Percentile stretch (all RGB and false-color imagery)

`stretch_band()` in `r/R/plotting.R`:

```
lim  = quantile(v, c(0.02, 0.98))
out  = clamp((v − lim1) / (lim2 − lim1), 0, 1)
out  = clamp(out^0.8 * 255, 0, 255)
```

The 2–98% clip discards outliers that would otherwise flatten the image; gamma
0.8 lifts the mid-tones. **The stretch is per scene**, so brightness is not
comparable between panels of a contact sheet — only structure is.

| Composite | Channels |
|---|---|
| True color | Red, Green, Blue |
| False color | NIR, Red, Green |

### Index maps

`plot_index()` — a fixed color ramp over the index's registered display range,
so the same color means the same value in every panel and across fields. Soil
armor uses the vegetation palette over 0–1.

### Soil armor, per calendar year (`plot_armor`)

One panel per year, up to 4 columns. Within each panel:

- x: 1 Jan → 31 Dec, ticks every 2 months (twelve labels collide at quarter
  width)
- y: cover fraction, fixed 0–1 so panels are comparable
- **filled teal** = fPV from 0; **filled tan** = fNPV stacked on top; the
  **unfilled white gap to the top is fBS** — the quantity being measured is the
  empty space, not a color needing a legend
- a gray line and points at fPV + fNPV = armor
- **gray shaded band + dashed lines** = the pre-planting window. The panel title
  quotes the armor figure, which is averaged over that band only, so the shading
  stops the eye reading an annual average off a twelve-month chart
- legend on the first panel only

Areas are drawn between consecutive observations. Sparse stretches therefore show
as long straight segments — honest about where there is no data, but not to be
read as measurement.

### CDL matrix (`plot_cdl_matrix`)

One small map per year, row-major so years read left to right then down, with one
shared legend in an extra row. **Colors are assigned once across all years**, so
a crop keeps its color from panel to panel; classes under `min_pct = 1` are
dropped from the legend. A boundary that is one management unit shows one color
filling it every year — that visual is the whole diagnostic.

### Boundary disagreement (`plot_cdl_split`)

Maps `persist_i` — the share of years each pixel differed from that year's
dominant class. Pale means it agrees every year; a persistent block outlined in
red is a sub-area farmed separately. One red year is classification noise, five
is a second field.

### Cover crop matrix (`plot_cover_crop_matrix`)

Every winter on a shared Oct → Jun x-axis and a common y-axis, one panel per
winter, so winters stack comparably. Threshold lines at `CC_GREEN_MIN` and the
residue ceiling.

### Phenology (`plot_phenology`, `plot_phenology_timeline`)

Observations as points, the smoothed daily curve as a line, and vertical markers
at estimated planting and harvest with their uncertainty windows shaded. The
timeline variant stacks seasons on a common day-of-year axis.

### Data availability (`plot_catalog_timeline`)

One row per source (Sentinel-2, Landsat 8/9, HLS, Sentinel-1, MODIS, NAIP …), one
mark per acquisition. Shows what exists, not what is usable — cloud is not
applied here.

### Contact sheets (`plot_scene_grid`)

Every scene in a quarter as thumbnails at `max_px = 180`, cached per
(field, scene set, view). A dimensionality guard refuses to cache a 3-band array
under a single-index key — a bug that once poisoned the cache with RGB arrays
stored as if they were NDVI, and then masked its own fix.

---

## 10. Numbers not to quote without their caveat

| Number | What it is | Caveat |
|---|---|---|
| `ARMOR_ENDMEMBERS` | 6 fields, 4 states | Looks empirical, is local. Refit before use elsewhere |
| `ARMOR_BREAKS` 0.40 / 0.75 | This library's distribution | Validation suggests ~0.44 / 0.59, crop-specific |
| `RESIDUE_BREAKS` 0.05 / 0.09 | p33 / p75 of 64 seasons here | Rank among eleven fields, not an absolute scale |
| `CC_GREEN_MIN` 0.30, `CC_STRONG` 0.35 | Mid-Atlantic lineage, origin unverified | **Measured wrong for Georgia** — 7.1% specificity |
| `CROP_LAGS` | Literature-typical | Never calibrated against a planting date |
| `SPLIT_*` | Chosen | Never calibrated, though the purity bands behind them now are |

Soil armor is a **cover** metric, not a tillage metric. Validation showed its
apparent tillage signal running largely through cover-crop adoption: a
conventionally tilled cotton field *with* a cover crop reads 0.604, statistically
indistinguishable from a conservation-tilled one at 0.625 and far above a
conventionally tilled field without one at 0.344.

---

## 11. External endpoints

Every network call the pipeline makes. Listed here so a reader can see exactly
what the numbers in this document were derived from, and reproduce them.

**Server-side** — requested by the R or Python process:

| Endpoint | Method | Used by |
|---|---|---|
| `planetarycomputer.microsoft.com/api/stac/v1` | POST | `search_scenes()`, `field_catalog()` |
| `planetarycomputer.microsoft.com/api/sas/v1/token/{collection}` | GET | Asset signing, called by `rstac`/`planetary_computer` rather than by this code |
| `sentinel2l2a01.blob.core.windows.net/sentinel2-l2a/…` | GET (range) | Every COG read, through GDAL `/vsicurl/` |
| `nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile` | GET | `get_cdl()`, fallback only once a local CDL store exists (§8) |
| `www.nass.usda.gov/…/datasets/{year}_30m_cdls.zip` | GET | `download_cdl.py`, once per year per machine |

**Browser-side** — requested by the viewer's browser, never by the server:

| Endpoint | Used by |
|---|---|
| `server.arcgisonline.com/…/World_Imagery/MapServer/tile/{z}/{y}/{x}` | Satellite basemap |
| `server.arcgisonline.com/…/Reference/World_Boundaries_and_Places/…` | State lines and place names |
| `server.arcgisonline.com/…/Reference/World_Transportation/…` | Major roads |

Seven STAC collections are queried through the single STAC endpoint:
`sentinel-2-l2a`, `landsat-c2-l2`, `hls2-s30`, `hls2-l30`, `sentinel-1-rtc`,
`modis-13Q1-061` and `naip`. **Only `sentinel-2-l2a` is read for analysis** —
every index, fraction and date in this document comes from it. The other six
are counted, never read, to report what else exists over a field.

No account, key or token is needed for any of them. The SAS token is fetched
anonymously and lasts about 45 minutes; `rstac` caches it per container, so
signing several hundred scenes costs one request rather than several hundred.

### The catalog is swappable; the data is not

Worth separating, because the two are often conflated. **Sentinel-2 is an ESA
mission** — the European Space Agency builds, flies and processes it, and
publishes the imagery free and open under Copernicus. **Planetary Computer is
Microsoft's mirror of it**: a copy on Azure Blob Storage with a STAC catalog in
front. Microsoft neither produces nor owns the data.

So the imagery is a hard dependency and the catalog is not. The same scenes are
mirrored elsewhere, and the closest alternative is
`earth-search.aws.element84.com/v1` on AWS. Checked against it directly:

| | Planetary Computer | Earth Search (AWS) |
|---|---|---|
| Collection id | `sentinel-2-l2a` | `sentinel-2-l2a` — identical |
| Asset keys | `B04`, `B08`, `B11`, `B12`, `SCL` | `red`, `nir`, `swir16`, `swir22`, `scl` |
| Asset host | Azure Blob Storage | `sentinel-cogs.s3.us-west-2.amazonaws.com` |
| Signing | SAS token, ~45 min | **none — public S3** |

Moving would be *simpler* than the present arrangement, not harder. The
collection id is the same string; the signing step disappears; and Earth
Search's asset keys are already the internal band names this pipeline uses
(§1), because both follow the STAC common-band convention while Planetary
Computer exposes ESA's raw B-numbers. `S2_BANDS` would become an identity map.

**Nothing in this document would change.** Every formula, endmember, threshold
and validated figure describes Sentinel-2 surface reflectance, not the route it
arrived by. What would change is `PC_STAC`, the band map and the signing call —
which is the argument for keeping those three behind one seam when this is
ported, rather than spread through the read path.

One correction, since it is the obvious thing to reach for: ESA's own
**Copernicus Data Space is not a drop-in STAC swap**. Its
`/stac/collections` endpoint lists ten collections and no Sentinel-2 among
them; its Sentinel holdings are served through different interfaces. It is the
authoritative source, not an equivalent endpoint.

### Request volume, measured

| Call | Volume | Goes to |
|---|---|---|
| STAC search | 1 per unique field and date range, then cached on disk | Rate-limited API |
| SAS token | ~1 per 45 minutes | Rate-limited API |
| COG range reads | thousands per field | Azure Blob Storage |

Nearly all of it is the third row, which is bulk object storage rather than an
API. Searches retry four times at 2/6/15 s and honor `Retry-After` when the
service sends one; the throttling seen in practice came from four heavy
searches in quick succession, not from sustained volume.

## 12. Winter crops and fallow

`phenology_all_years` in `r/R/phenology.R` and `python/fieldrs/phenology.py`.

The summer model (§5) looks for a June–September peak and reads spring green-up
as planting, so a winter small grain gets an April "planting" or no season at
all. The CDL label picks the model:

| CDL label | Model | `season_type` |
|---|---|---|
| Winter Wheat, Rye, Triticale | winter model | `winter` |
| Fallow/Idle Cropland | fallow row with the fallow period | `fallow` |
| none yet (current year) | summer and winter both run; the curve decides | `winter (from curve)`, `fallow (from curve)` or `summer` |
| anything else | summer model (§5) | `summer` |

**Winter model.** Season `year` is the harvest year. The curve is fitted from
1 July of the year before to 31 October.

- **Peak:** the spring maximum, between 15 March and 30 June.
- **Sowing:** the minimum between 1 August and 31 October the autumn before. If
  the curve then rises at least 0.08 by 31 December, sowing is the 20% point of
  that rise minus 14 days. It must fall by 15 December and no earlier than
  15 August.
- **Green-up:** the 20% point from the late-winter low to the peak.
- **Harvest:** the 20% point back down from the peak to the summer low, by
  30 September. The drop has to be at least 0.20.
- **Windows and confidence:** as in §5.
- **No crop:** a peak below 0.45 is "no winter crop detected", and the
  perennial test of §5 applies to the crop year.

**A year with no CDL label** is read as winter only when all of these hold:
- the winter model finds sowing, a peak of at least 0.45 and a harvest;
- the summer model is not refusing a perennial;
- the summer model either found nothing, or only the tail of that same canopy
  (peak by 10 June and no more than 0.02 above the winter peak).

Autumn emergence is the deciding evidence: a southern spring crop can peak in
early June too, but has nothing green the autumn before.

**Fallow.** The period runs from the previous season's harvest to the next
season's planting. `fallow_green_days` counts days the smoothed curve sits at or
above 0.30 inside it, which is weeds or volunteer grain, and is noted. Soil armor
and the cover crop check skip winter-crop years: their spring is canopy, not a
pre-planting period.

Checked on the two Akron, Colorado wheat-fallow fields, where the summer model
had dated 3 of 6 wheat seasons, all with April–May planting.

## 13. Cover crop seeding and termination

`cover_crop_dates` in `r/R/covercrop.R` and `python/fieldrs/covercrop.py`. Only
winters whose verdict is a (possible) cover crop are dated. Never "high"
confidence: nothing is fitted to recorded dates.

- **Seeding.**
  - Find the trough within −7 to +45 days of the cash harvest.
  - The rise after it must be at least 0.08 and reach 0.30, within 100 days of
    the trough.
  - Seeding is the 20% point of that rise minus 14 days. The rise must start
    within 90 days of harvest and by 31 January.
  - A seeding date before the harvest is clamped to the harvest and noted (a
    cover seeded at harvest or interseeded).
- **Termination.**
  - Find the last hump before the pre-plant trough, within 100 days of it,
    inside the off-season window and after seeding.
  - It must peak at 0.30 or above and fall at least 0.10.
  - Termination is the midpoint of the decline minus 7 days (the lag between
    spraying and browning).
  - A decline ending in open water (NDVI below 0.05) is flooding and is not
    dated.
- **Windows:** ±max(14 days, the observation gap at the crossing).

**`green_days` smoothing.** R fits the local curve with `smooth.spline(spar =
0.5)`. Python uses `make_smoothing_spline(lam = 800)`, which was chosen by a
sweep against R over the library's 90 winters:
- lam 50 gave a mean absolute difference of 5.9 days;
- lam 800 gives 3.1 days, with 79% of winters within 3 days.

## 14. Weather-checked field-work dates (gridMET)

`r/R/climate.R` and `python/fieldrs/climate.py`.

**The data.** Daily gridMET (4 km, CONUS, 1979 to about two days ago) at the
field centroid, read through the CSIP climate service at Colorado State.

**What the check does.** NDVI dates the canopy, not the planter or combine, and
is good to roughly two weeks. Within that window a day nobody could work is the
least likely answer. The check applies to planting, harvest, cover seeding and
cover termination:

- A date on a workable day stays.
- Otherwise it moves to the last workable day before it (farmers act ahead of
  the forecast), at most `FORECAST_DAYS` = 5 days earlier.
- Failing that, it moves to the first workable day after.
- It never leaves its uncertainty window.
- A cover crop's seeding window never opens before the cash crop's final
  harvest.

**A day is workable** when all of these hold:
- its rain is at most `DRY_PR_MM` = 0 mm;
- it is not within `HEAVY_RAIN_WET_DAYS` = 1 day after `HEAVY_RAIN_MM` = 25 mm
  of rain (wet soil);
- with the wind check on, its daily-mean wind is below `WIND_MAX_KMH` = 30 km/h.
  gridMET has no gusts, so the limit is on the daily mean.

**Outputs.** `<event>_date`, `_shift_d`, `_pr_mm`, `_wind_kmh` and
`_weather_note`, plus `season_days_final` and `cover_days_final`. The `_est`
columns are never changed.

## 15. Irrigation (USGS irrigated agriculture maps)

`r/R/irrigation.R` and `python/fieldrs/irrigation.py`.

**The maps.** Binary CONUS rasters in EPSG:5070: 2002 and 2007 at 50 m, 2012 and
2017 at 30 m.

**The share.** The irrigated share is the fraction of pixels whose centre lies
inside the boundary that are mapped 1. A field smaller than a pixel takes the
pixel under its centroid.

- **Labels:**
  - irrigated at 50% or more;
  - partly irrigated at 10% or more;
  - otherwise not irrigated.
- **Which map:** each CDL year takes the nearest map at or before it, and says
  which.
- **Consistency:** `irrigated_maps` ("3 of 4") shows how many maps agree.

**Caveat.** Single maps are not reliable at field level (§10). There is no map
after 2017.

## 16. HLS imagery

`r/R/imagery.R`, `r/R/extract.R`, `python/fieldrs/imagery.py` and
`python/fieldrs/extract.py`.

**The data.** NASA HLS v2.0 from Planetary Computer, from 2020: S30 (Sentinel-2)
and L30 (Landsat 8/9) on one 30 m grid.

- **Masking:** Fmask bits 1–4 are dropped (cloud, adjacent, shadow, snow).
  Water and aerosol are kept.
- **Bad pixels:** any band at or below zero reflectance is dropped.
- **Edge pixels:** pixels are kept when their centre is 15 m inside the
  boundary, or the whole boundary is used if that leaves fewer than 10.
- **NIR band:** S30 uses B8A, the narrow NIR that HLS matches to Landsat B05.

**NDVI transfer to the Sentinel-2 scale.** Every NDVI threshold here was set on
Sentinel-2 L2A, and HLS reads higher over bare ground, so HLS NDVI is mapped
onto the Sentinel-2 scale:
- S30: `ndvi = 1.0733 · ndvi_hls − 0.0758`
- L30: `ndvi = 1.0707 · ndvi_hls − 0.0686`

These were fitted on same-day field medians: 2,941 S30 and 818 L30 pairs, RMSE
0.026 and 0.024.

**Spike filter, HLS only.** It drops a reading that is more than 0.10 from the
nearest reading on both sides, in the same direction, within 20 days. From
November to March a reading with no neighbour on one side is judged against the
other side alone, when that side holds two or more readings within 20 days that
agree to 0.05. Both the transfer and the spike filter are applied after the
cache, which stays raw.

## 17. Sentinel-1 radar: planting and harvest windows

`r/R/sar.R` and `python/fieldrs/sar.py`. **A prototype.** Nothing is checked
against grower dates.

**The data.** Planetary Computer `sentinel-1-rtc`: terrain-corrected gamma0,
10 m, linear power.

- **Pixels:** those with their centre 10 m inside the boundary. The scene must
  cover at least 80% of them.
- **Field values:** VV and VH are averaged in linear power, then converted to
  dB.
- **One per pass:** one acquisition per (date, relative orbit).

**Moisture and freeze.** Wetting brightens VV just as tillage roughening does.

- **Rain index:** an antecedent precipitation index
  `API_t = 0.7·API_{t−1} + 0.3·pr_t`, divided by 0.3. It is read for the UTC
  date minus one day, because passes are around 6 pm local the evening before.
- **Moisture fit:** per orbit, VV on bare (NDVI < 0.30), unfrozen dates is
  regressed on log(1 + API). The residual `vv_adj` removes both the rain effect
  and the orbit offset. At least 10 dates are needed.
- **Freeze:** dates whose 3-day mean air temperature is 1 °C or below are
  frozen and dropped.
- **VH:** each orbit's VH is centred on its own median.

**Events.**
- **Planting:** the largest drop in `vv_adj` on bare ground, from 1 April to
  7 days after the NDVI planting window.
- **Harvest:** the largest drop in VH from 14 days before to 28 days after the
  NDVI harvest window.
- `in_ndvi_window` reports agreement, not accuracy.
- **Winter crops:** sowing is searched from 1 August of the autumn before the
  harvest year (the winter model's sowing search), not from 1 April. From
  1 April the span was empty for every wheat year.
- **Same-day passes:** two orbits passing on one day give no interval. Their
  difference is orbit residual, not a change on the ground. Intervals are
  built in date-then-orbit order on both sides, so R and Python pair the same
  acquisitions. Akron sits under four orbits and had 81 same-day dates.

**Narrowing.** Inside each NDVI window:
- The strongest drop is scored as z: the drop over 1.4826 × the median absolute
  deviation of all intervals of the same kind.
- At z ≥ 2 the window narrows to the workable days (§14, plus not frozen) inside
  that interval. Otherwise rain days are struck out.
- A step more than 1 z stronger outside the window is flagged as a conflict.
- Read `span_days`, not `candidate_days`, as how far a date is pinned down.

**What was found on four test fields:**
- Harvest is narrowed in 2–5 of 6 seasons per field, from about 30 days to 7–11.
- Planting almost never, because backscatter at a 6–12-day revisit carries
  little planting signal here.
- Filters that ignore NDVI (a workable day in the interval, the same moisture
  state at both ends, a step that persists) did not improve agreement with the
  NDVI windows.

## 18. Hay cuttings

`r/R/forage.R` and `python/fieldrs/forage.py`. **A prototype.** Nothing is
checked against grower dates.

**Which years.** Those CDL calls Alfalfa, Other Hay/Non Alfalfa,
Clover/Wildflowers or Vetch. Also a year with no CDL label yet, when the year
before was forage and the season model found a perennial stand. Pasture is
excluded, because grazing looks like a slow cut.

**Finding a cut.** Only 1 April to 15 November is searched.

- **Stand:** NDVI at or above 0.60.
- **Trough:** the first low after the drop. The decline is followed until NDVI
  rises 0.06 above its lowest reading so far, or 21 days pass.
- **Drop:** at least 0.20, against a full-stand noise level of 0.016 (median) and
  0.060 (95th percentile).
- **Bracket:** the first scene at least halfway down to the trough, and the
  scene before it.
- **Labels:** a trough below 0.20 is "to bare soil" (tillage, reseeding,
  removal). No regrowth of 0.15 within 45 days is flagged.

**Narrowing.** Radar VH from every orbit (no VV moisture fit is needed) narrows
the bracket when the strongest drop inside it reaches z ≥ 2, with z scored on
growing-season intervals. Rain days are then struck out.

**On the Washington pivot:** 20 hay cuts in five alfalfa years. Radar narrowed 12
of them, and the median bracket went from 5 days to 4.

## 19. Keeping R and Python in step

Every section above exists in both implementations. `python/compare_with_r.py`
diffs the Python results against R's `r/export_r_reference.R` output.

**Must match exactly:**
- verdicts and season types;
- CDL crop names, dominant and secondary classes;
- irrigation labels.

**Tolerances:**
- dates and fallow days: ±3 days (fallow days carry both ends' tolerance);
- peak NDVI: ±0.02;
- green days: ±10;
- observations: ±2.

The remaining date disagreements come from the two smoothers being matched by
sweep rather than identical (§3). Sections 14–18 were also checked on identical
inputs fed to both sides:
- **Weather, irrigation, HLS, radar and hay cuts:** every value matched, apart
  from float32 rounding in backscatter.
- **Winter, fallow and cover crop dates:** these differ only where a smoothed
  curve sits on a threshold.

## 20. Does the curve contradict CDL?

`r/R/cdl_check.R` and `python/fieldrs/cdl_check.py`. This is a flag, not a
correction.

**Why it can't correct CDL.** Crops can't be told apart by how green they get.
On the library's seasons where the CDL label covers at least 90% of the field,
peak NDVI overlaps almost completely:

| Crop | Peak NDVI |
|---|---|
| Corn | 0.76–0.94 |
| Soybeans | 0.86–0.93 |
| Rice | 0.84–0.93 |
| Peanuts | 0.88–0.92 |
| Cotton | 0.65–0.89 |

Cotton and peanuts also peak within days of each other, with the same season
length. So the curve can't say which crop a season was. It can only say when
the label can't be right.

**Rules giving `cdl_flag_kind = "contradicts"`** (the first that applies wins):
1. A winter grain label (Winter Wheat, Rye, Triticale), but no spring canopy.
2. A fallow label, but a summer canopy.
3. A summer row-crop label (Corn, Soybeans, Cotton, Peanuts, Rice, Sorghum,
   Sunflower, Dry Beans), but no summer canopy.
4. An annual crop label, but the field is green all year (the perennial test
   in §5).
5. A hay or alfalfa label, but a single annual season with a bare-soil period.
6. A summer row-crop label, but planted before 1 March or harvested before
   1 July: a winter or spring grain's calendar.

**Mixed.** `"mixed"` marks a season whose CDL dominant crop covers less than 75%
of the field. The curve then blends whatever grows in the boundary and can't
confirm the label either way.

**On the library** (17 fields, 2020–2026), four seasons contradict their label:
- Mitchell Co. conventional 2022, "Cotton" harvested 25 June;
- Washington pivot 2022 and 2023, "Alfalfa" around the stand being removed and
  reseeded;
- Lubbock 2025, "Fallow" with a summer canopy.

Twenty seasons are mixed. Both implementations flag the same seasons.

**Parity.** "mixed" isn't compared, because it rests on the dominant-crop share,
and each side may have cached a different copy of CDL. None of this is checked
against grower records yet.

## 21. Suspect readings

`r/R/outliers.R` and `python/fieldrs/outliers.py`. Readings are flagged, never
removed. Every date, verdict and cut in the tool uses all readings.

**What's flagged.** The cloud mask misses some snow, thin cloud and shadow. A
reading is flagged as suspect when either:
- it is more than 0.10 from the nearest reading on both sides, in the same
  direction, both within 20 days; or
- in November to March, with no neighbour within 20 days on one side, it is more
  than 0.10 from the median of at least two readings on the other side that
  agree to 0.05.

This is the same test as the HLS spike filter (§16).

**Never flagged:**
- **Open water:** a reading below NDVI 0.05 that is either negative (water
  absorbs NIR, while snow and cloud sit around zero) or next to another reading
  below 0.05 within 20 days, as in a flooded run. A single near-zero dip between
  normal readings is still flagged.
- **Hay cutting season:** anything between 1 April and 15 November in a year
  read as hay (§18). A dip there is a cut, and a peak is the stand regrowing
  between cuts.

**Why nothing is deleted.** Tested on the library's 5,216 Sentinel-2 readings:
- Deleting spikes year-round would remove 87 readings, 20 of them hay-cut
  troughs.
- Distance from the fitted curve flags 9% of readings, mostly June–September,
  where the smoother fails to follow real harvests and cuts.
- Even a winter-only filter removed open water on the rice field. That flipped
  a cover crop verdict from "flooded, not detectable" to "no cover crop
  detected", and moved two planting dates by up to 7 days.

**On the library**, 58 of 5,216 readings (1.1%) are flagged. R and Python flag
the same readings on identical input.

**Where it shows.** Flagged readings are ringed in red on the season charts. The
Season analysis tab gives the count and a table of them, and the series
download has `suspect` and `suspect_reason` columns.

## References

### Spectral indices

- Rouse, J. W., Haas, R. H., Schell, J. A., Deering, D. W. (1974). Monitoring
  vegetation systems in the Great Plains with ERTS. *Third ERTS Symposium, NASA
  SP-351.* — NDVI. A symposium paper rather than a journal article; it is the
  conventional origin citation.
- Huete, A. R. (1988). A soil-adjusted vegetation index (SAVI). *Remote Sensing
  of Environment.* — SAVI
- Jiang, Z., Huete, A. R., Didan, K., Miura, T. (2008). Development of a
  two-band enhanced vegetation index without a blue band. *Remote Sensing of
  Environment.* — EVI2
- Gao, B.-C. (1996). NDWI — a normalized difference water index for remote
  sensing of vegetation liquid water from space. *Remote Sensing of
  Environment.* — NDMI (published under the name NDWI; see §2)
- McFeeters, S. K. (1996). The use of the Normalized Difference Water Index
  (NDWI) in the delineation of open water features. *International Journal of
  Remote Sensing.* — NDWI
- Gitelson, A., Merzlyak, M. N. (1994). Spectral reflectance changes associated
  with autumn senescence of *Aesculus hippocastanum* L. and *Acer platanoides*
  L. leaves. *Journal of Plant Physiology.* — NDRE
- Gitelson, A. A., Gritz, Y., Merzlyak, M. N. (2003). Relationships between leaf
  chlorophyll content and spectral reflectance and algorithms for
  non-destructive chlorophyll assessment in higher plant leaves. *Journal of
  Plant Physiology.* — GCVI
- Cao, X., Chen, J., Matsushita, B., Imura, H. (2010). Developing a MODIS-based
  index to discriminate dead fuel from photosynthetic vegetation. *International
  Journal of Remote Sensing.* — DFI
- Sonmez, N. K., Slater, B. (2016). Measuring intensity of tillage and plant
  residue cover using remote sensing. *European Journal of Remote Sensing.* —
  NDTI, NDI7, NDSVI, CAI

### Methods

- Guerschman, J. P., Hill, M. J., Renzullo, L. J., Barrett, D. J., Marks, A. S.,
  Botha, E. J. (2009). Estimating fractional cover of photosynthetic vegetation,
  non-photosynthetic vegetation and bare soil in the Australian tropical savanna
  region upscaling the EO-1 Hyperion and MODIS sensors. *Remote Sensing of
  Environment,* 113(5), 928–945. doi:10.1016/j.rse.2009.01.006 — the NDVI ×
  shortwave-index unmixing triangle, originally with CAI
- Wang, G., Wang, J., Zou, X., Chai, G., Wu, M., Wang, Z. (2019). Estimating the
  fractional cover of photosynthetic vegetation, non-photosynthetic vegetation
  and bare soil from MODIS data: assessing the applicability of the NDVI-DFI
  model in the typical Xilingol grasslands. *International Journal of Applied
  Earth Observation and Geoinformation,* 76, 154–166.
  doi:10.1016/j.jag.2018.11.006 — the NDVI–DFI model this pipeline implements
- Zheng, B., Campbell, J. B., de Beurs, K. M. (2013). Remote sensing of crop
  residue cover using multi-temporal Landsat imagery. *Remote Sensing of
  Environment.* — minimum-NDTI method

### Data

- USDA NASS Cropland Data Layer — https://nassgeodata.gmu.edu/CropScape/
- Microsoft Planetary Computer, Sentinel-2 L2A —
  https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a

### Formulas in this document with no published source

Listed rather than left implicit. Every index above traces to a paper; these
three do not, and two of them are described elsewhere in the repository as
coming from the literature without a paper ever being named. Until each line
below is closed, treat the method as this project's own construction and say so
when reporting it.

The NDVI–DFI unmixing was on this list until October 2026 and is now sourced to
Guerschman et al. (2009) and Wang et al. (2019); see §4.

| What | Where | What is needed |
|---|---|---|
| Planting and harvest extraction | §5 | A source for the amplitude-threshold-on-a-smoothed-curve approach. The thresholds and the smoothing penalty are ours; the technique is not new |
| `CC_GREEN_MIN` 0.30, `CC_STRONG` 0.35, `CC_RESIDUE_MAX` 0.25 | §7 | Partly traced — see below. 0.30 has a documented lineage but not a verified origin; 0.35 and 0.25 have neither |
| `CROP_LAGS` | §6 | Described as "literature-typical, never calibrated". Same problem, lower stakes |

Closing these matters beyond tidiness. Published prior art is what narrows a
patent claim, and an unsourced claim of a literature source is weaker than
saying plainly that a number was chosen.

### What was found for the cover crop thresholds, October 2026

Searched rather than recalled, and recorded with its uncertainty because the
answer is partial.

**0.30 is a real number in this literature, with a traceable chain of use:**

- Hively, W. D., Duiker, S., McCarty, G. W., Prabhakara, K. (2015). Remote
  sensing to monitor cover crop adoption in southeastern Pennsylvania.
  *Journal of Soil and Water Conservation,* 70(6), 340–352.
  doi:10.2489/jswc.70.6.340 — Landsat and SPOT NDVI, the CDL and windshield
  surveys over the Chesapeake Bay watershed, 2010–2013. Later work credits this
  study with determining an in-situ-verified NDVI threshold for identifying
  winter cover crops.
- KC, K., Zhao, K., Romanko, M., Khanal, S. (2021). Assessment of the spatial
  and temporal patterns of cover crops using remote sensing. *Remote Sensing,*
  13(14), 2689. doi:10.3390/rs13142689 — reuses that threshold over the Maumee
  River watershed (Ohio, Indiana, Michigan), 2008–2019.

**Three reasons this is not yet a citation.**

1. *The number has not been verified against either primary text.* Both papers
   are behind paywalls that refused automated retrieval. The 0.30 figure is
   attested only by later work citing them. One secondary source also suggests
   the 0.30 cutoff in Maryland originates as a **state Department of
   Agriculture program rule** marking low-performing or terminated fields,
   rather than as a finding of the 2015 paper. Those are different kinds of
   number and the difference matters.
2. *The statistic differs.* KC et al. apply 0.30 to a **seasonal average NDVI
   per field**. §7 applies `CC_GREEN_MIN` to **individual observations** when
   counting green days, and `CC_STRONG` to the **window maximum**. Reusing a
   threshold against a different statistic is not reusing the threshold.
3. *`CC_STRONG` 0.35 and `CC_RESIDUE_MAX` 0.25 were not found at all.* No
   source surfaced for either.

**The geography was wrong and is now corrected.** `covercrop.R`, the root
README and the cotton deck all described these as Corn Belt or Iowa values. The
lineage runs through **southeastern Pennsylvania and the Chesapeake Bay**; the
Corn Belt is where the number was later reused, not where it was established.

That correction sharpens the Georgia result rather than softening it. A
threshold set in the Mid-Atlantic — milder and wetter than Iowa, and closer to
Georgia in winter behavior — still reached only 7.1% specificity against
Georgia ground truth. The failure is not a simple matter of latitude, which is
what "an Iowa number used in the South" implied.
