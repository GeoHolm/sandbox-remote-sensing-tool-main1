# Field remote sensing explorer

A Shiny app and R pipeline that reads a field's management history out of free
satellite imagery. Upload a boundary and get: what data exists for that field,
what was grown each year, when it was planted and harvested, and whether
anything was growing over the winter.

Built as a proof of concept — every threshold is a literature-typical starting
value, not calibrated against ground truth. See [Limits](#limits-read-this-before-quoting-numbers).

## Quick start

```r
source("setup.R")     # once
```

```bash
Rscript warm_cache.R  # once, ~30 min: pre-computes the demo library
```

```r
shiny::runApp()
```

Pick any field from the dropdown and it opens immediately. Uploading a new
boundary takes about 4 minutes the first time (it reads ~700 scenes), then it is
cached too.

For scripting without the app:

```r
source("pipeline.R")

field <- load_field("data/fields/example_field.geojson")
ts    <- extract_field_series(field, "2020-01-01", "2026-09-16")
hist  <- cdl_history(field)
phen  <- phenology_all_years(ts, crop_lookup(hist))
cc    <- cover_crop_all_years(ts, phen, crop_lookup(hist))
```

Every formula and chart behind these tabs is documented in
[`../METHODS.md`](../METHODS.md).

## The app

| Tab | What it shows |
|---|---|
| **Field** | Boundary on satellite basemap, area, CDL crop rotation — or trace a new one by hand |
| **CDL** | Crop type per year as a matrix, and whether the boundary is one field |
| **Data availability** | Every acquisition 2020→now across 8 sources |
| **Imagery** | Contact sheet: every scene in a quarter — true/false color, NDVI, NDTI |
| **Season analysis** | Whole record, split panels, or a single season |
| **Cover crops** | Every winter at once, on a shared Oct-to-Jun axis |
| **Soil armor** | Surface cover — living, residue, bare — whole calendar years, pre-planting window shaded |
| **Summary** | One row per season — the leadership view, downloadable as CSV |

### The basemap

Esri satellite imagery with two transparent reference layers on top: boundaries
and place names, and transportation. There is no layer control — toggling was
never the point, being able to tell where you are was. Imagery alone is
disorienting, because a field is a rectangle of dirt among other rectangles of
dirt with nothing to say which county it is in.

`basemap_hybrid()` in `R/aoi.R` builds it, and both map paths use it: the
loaded-field view via `preview_field()` and the empty startup map. Two details
that will bite anyone editing it. The reference layers are **not** in leaflet's
`providers` list in this version, so they go in by URL; and ArcGIS REST serves
tiles as `{z}/{y}/{x}`, not the `{z}/{x}/{y}` most servers use — swapped, the
map silently serves the wrong tiles rather than failing. Each layer gets an
explicit `zIndex`, because all tile layers share one pane and without it the
labels can end up under the imagery.

### Getting the figures out

Every chart has a **PNG** button in its card header and every table a
**Download CSV** button above it. Both name the file for what it holds, which
field it came from and the date — `soil-armor_tifton-georgia_2026-10-02.csv`,
`armor_tifton-georgia_2026-10-02.png`. Comparing three fields is the normal use
of this app, and downloads that all arrive as `table.csv` overwrite each other
in the download folder.

The two work differently, for a reason. Tables go through `dt_dl()`, a thin
wrapper over `DT::datatable()` that attaches DataTables' own CSV export, so the
file is generated from the rendered rows and matches what is on screen --
column names, rounding and all. A separate handler reading the underlying frame
would drift from the display the first time either changed.

Charts are base R drawn into a device, so there is nothing client-side to
export and `dl_plot()` has to redraw them. It renders at print size rather than
browser size, which is what the on-screen version is fitted to, and it catches
the case where the analysis has not run: you get a PNG saying so rather than a
corrupt zero-byte file.

**A download button on an unvisited tab has an empty link until you open that
tab.** Shiny suspends outputs on hidden tabs, so the handler is not registered
until the tab is shown. That is normal and resolves itself; it only looks
alarming if you inspect the DOM.

### Keeping a boundary

**Download boundary (GeoJSON)** appears in the sidebar alongside **Clear field**
whenever a field is loaded. A drawn boundary exists nowhere else — the cache is
keyed on geometry and stores results, not the outline — so without this a field
traced on the map is gone the moment it is cleared.

The file is WGS84 with `field_id` and `area_ha` and nothing else, and it
reloads through `load_field()` unchanged: a drawn 18.8252 ha field exports and
comes back at 18.8252 ha. An example field keeps its name
(`tifton-georgia_2026-09-29.geojson`); a drawn one is `drawn-field_<date>`.

### One field at a time

The app opens with nothing loaded — a satellite map and the draw tools, so the
first action is available immediately. Nothing is preloaded, because opening on
an example field made the app look as though it had already answered a question
nobody asked.

Every path in — example tile, upload, drawing — passes through `single_field()`
in `R/aoi.R`, which reduces a boundary to one field or refuses it. **Clear
field** in the sidebar appears once something is loaded and returns the app to
empty. Discarding a drawing with **Redraw** wipes it from the map, so a second
attempt never sits beside the first.

Negligible parts are dropped rather than refused: under 0.05 ha, or under 0.5%
of the largest part. That distinction is not academic —
`example_field_covercrop.geojson` is a MULTIPOLYGON whose second part is 0.00 ha
sitting 200 m away, a digitizing artifact rather than a second field, and a
strict multipart rule would reject one of the eleven demo fields. Two
substantive fields are refused with both areas named.

### Drawing a boundary on the map

The Field map carries a polygon and a rectangle tool. Tracing a field does not
start an analysis. It reads that boundary's crop history, shows the per-year CDL
maps and a verdict, and waits for a confirmation.

The ordering is the whole point, and it only became worth doing once CDL moved
to a local copy: reading crop history for a drawn shape costs about half a
second, against one to three minutes for the full pipeline. Checking first is
therefore free, so the expensive read never starts on a boundary that was not
worth reading.

A traced boundary earns that check more than any other kind. Someone sketching
from memory over satellite imagery will sometimes take in a headland, a turn
row, or half the next field, and nothing downstream recovers from it — the
season curve becomes a blend of two crops and the planting date belongs to
neither. The validation run measured the cost, and the verdict quotes it:

| Median share of the boundary CDL gives one crop | Verdict |
|---|---|
| 75% or more | **Looks like one field** — boundaries this clean matched the grower's own answer 88.7% of the time |
| 60–75% | **Mixed** — borderline; part of a neighboring field or a headland is probably inside the line |
| under 60% | **Two fields, not one** — boundaries this mixed agreed with the grower just 12.9% of the time |

Three drawings are refused outright rather than run: over **500 ha** (the demo
library tops out at 173, and one careless drag can otherwise enqueue a county
and stall the app in front of an audience), under **0.5 ha**, and anything
outside the continental US, where CDL has no coverage at all.

Worth knowing before a demo: an arbitrary rectangle dropped on farmland will
usually come back "two fields, not one", because it usually is. That is the
tool working. For a clean demonstration, trace an actual field edge on the
satellite imagery.

### CDL: is this one field?

Everything downstream averages NDVI over whatever the boundary contains. A
boundary spanning two fields farmed differently produces a season curve that is
a blend of two crops and a planting date belonging to neither — so this tab
checks the boundary before you trust anything else.

It shows each year's CDL as a map (three per row), and tests for **persistence**
rather than disagreement in any single year. One year of disagreement is
classification noise along the edges; the same block disagreeing in four years
out of six is a second field. A region is only flagged when it covers ≥12% of
the boundary, forms a contiguous block of ≥2 ha, and differs in ≥60% of years.

Three verdicts:

- **single unit** — no persistent sub-area; the numbers elsewhere are sound
- **split** — a contiguous block is cropped differently most years; splitting
  the boundary along that line would sharpen every other tab
- **trim** — the flagged area is mostly non-crop (farmstead, road, water,
  woodland). It drags field NDVI down all season; clipping it out is worth more
  than splitting

The disagreement map shows the share of years each pixel differed from that
year's dominant crop, with the flagged region outlined.

### Imagery: contact sheets

A dropdown of 700 scenes is unusable, so the Imagery tab renders a whole quarter
at once as a grid, in true color, false color, NDVI or **NDTI**. A quarter is
20–30 scene reads, so it loads only when you press **Show imagery** rather than
on every change of the dropdown.

### Reading the Soil armor view

It shows **`1 − f_bs`** — one number per pixel — on the six-stop BrBG scale
`veg_palette()`, stretched over 0 to 1:

| | armor | meaning |
|---|---|---|
| `#8c510a` dark brown | 0.0 | fully exposed soil |
| `#d8b365` tan | 0.2 | |
| `#f6e8c3` cream | 0.4–0.5 | about half covered |
| `#c7eae5` pale teal | 0.7 | |
| `#01665e` dark teal | 1.0 | fully covered |

Fixed, not per-scene, so two dates are comparable. Gray is masked — cloud,
shadow, snow, or water (below NDVI 0.05, where DFI breaks down).

**It shows how much cover, not what kind.** The three fractions are collapsed
into a single number before coloring, so half-living/half-bare and
half-residue/half-bare both render as the same cream. On the Maryland field on
21 April 2026 — `fPV` 0.08, `fNPV` 0.73, `fBS` 0.19 — the sheet is a uniform
teal that correctly reads "well covered" and gives no hint the cover is
stubble rather than a living crop. For that split, use the **Soil armor** tab,
which reports `Living` and `Residue` as separate columns and stacks them in
the per-season plot.

A three-color rendering was prototyped and not adopted — see *Coloring the
three fractions* in the root `README.md` for what was tried and why it is
parked.

The NDTI view uses its own scale — 0 to 0.25 on a pale-straw-to-dark-brown
ramp, not the NDVI ramp, whose teal end would read as green canopy when NDTI's
high end means the opposite. **It only means residue on bare ground:** a live
canopy absorbs in the shortwave infrared too. On the Kansas field's 2025-Q2
sheet you can watch that happen — pale tan through April and May, then dark
from 7 June as the crop comes up. Past that point the sheet is reading the crop,
not the surface. The Soil armor tab exists because it restricts NDTI to the
pre-planting window automatically.

Every cell shares **one fixed brightness scale**, so dates are genuinely
comparable — a cell is greener because the field was greener, not because it was
stretched differently. Gray means the pixel was masked as cloud, shadow or snow,
so a gray cell is a date the satellite passed over and saw nothing usable. Each
cell is labeled with the share of the field that came through clear.

June 2024 on the Iowa field reads straight off the sheet: bare tilled soil on
the 9th and 14th, canopy emerging by the 24th — consistent with the estimated
7 June planting date.

### Season analysis: three views

- **Whole record, split** (default) — roughly three-year panels, so seven
  seasons stay legible on one screen
- **Whole record, one axis** — everything on a single timeline
- **Single season** — one year with the uncertainty bands drawn

All three mark planting (blue) and harvest (orange) and shade the off-season.
The curve is smoothed **per season, never across years** — one smoothing
parameter cannot represent seven annual cycles, and fitting globally flattens
every peak.

## The demo library

### The gallery

The library lives on the **Field** tab, under the summary: a responsive grid of
cards, each carrying the field's name, its CDL rotation and the one line from
`library.csv` saying what it demonstrates. A filter box narrows by any word in
any of those three, so "georgia cotton" finds two fields and "cover crop" finds
four — including the rice field, whose description explains that flooding makes
a cover crop undetectable rather than absent. Searching the descriptions rather
than only the names is most of the value.

It moved out of the sidebar because 320 px stopped being enough. Eleven tiles
fitted; thirteen was tight; forty would be a scroll tunnel, and the sidebar
could never show what a field is *for*. The sidebar now says which field is
loaded, its area, and where to change it.

### Four Georgia cotton fields that show the confound

Filter the gallery on **grower-confirmed** and four fields come up. They are the
same crop in the same state in years the demo window covers, promoted from
`validation/boundaries/` because the grower told us what was actually done, and
between them they fill every cell of the tillage x cover crop square:

| Spring armor (living fraction) | No cover crop | With cover crop |
|---|---|---|
| **Conventional till** | 0.508 (PV 0.12) — Mitchell Co. | 0.649 (PV 0.17) — Jefferson Co. |
| **Conservation till** | 0.480 (PV 0.04) — Screven Co. | 0.649 (PV 0.25) — Mitchell Co. |

Read down the columns rather than across the rows. A cover crop puts armor at
0.649 whichever way the field was tilled; without one it sits near 0.49 whichever
way the field was tilled. **The conservation-tilled field with no cover crop
scores lower than the conventionally tilled one.** Residue fractions barely move
between them; the living fraction does all the work.

That is the validation section's central finding standing up on four real
fields: soil armor is a cover metric, and its apparent tillage signal runs
through cover-crop adoption. A reviewer who doubts it can be shown it.

**Four fields illustrate; they do not evidence.** The 347 field-years do that.
The fields differ in size, county and irrigation, so this is a demonstration
chosen for clean boundaries — though barely chosen at all: with CDL purity above
92% in the demo window there were three candidates for one off-diagonal cell and
one for the other.

### Adding a field

From the R console, which is where most of this work happens — `Rscript` is a
shell command and cannot be typed at a `>` prompt:

```r
source("r/add_field.R")                 # defines the functions, runs nothing
add_field("validation/boundaries/40464_2020.geojson",
          stem  = "mitchell-ga",
          label = "Georgia - Mitchell Co.",
          shows = "conservation till with a cover crop")
library_status()                        # manifest vs boundaries on disk
```

Or from a shell — RStudio's **Terminal** tab, not the Console:

```bash
Rscript r/add_field.R <boundary.geojson> --label "Georgia - Mitchell Co."                                          --shows "what this field demonstrates"
Rscript r/add_field.R --status
```

Both run the same code; the command line is a thin wrapper. Sourcing the file
defines `add_field()` and `library_status()` and does nothing else.

One command does the lot: validates the boundary through `single_field()` — the
same rule the app enforces, so nothing enters the library that the UI would
refuse — writes the cleaned single-field geometry into `data/fields/`, appends a
row to `data/fields/library.csv`, warms all four caches the app needs, cuts the
CDL clips, and prints what to commit. **Roughly 10 to 25 minutes per field**, nearly
all of it the NDVI series and soil armor. The spread is Planetary Computer's
throughput on the day, not field size: the same armor step has taken 5 and 19
minutes on fields of similar area.

It is idempotent. Re-running a field already in the library re-warms only what
is missing and finishes in seconds, so an interrupted add is fixed by running it
again.

`data/fields/library.csv` carries `stem, label, shows, added`. Manifest order is
tile order. A boundary with no row still appears, labelled from its filename —
the library keeps working when the manifest falls behind, it just looks worse.
These labels used to be a constant in `app.R`, which meant adding a field
required editing the application; that was the friction worth removing.

**Keep the warm list in step with `run_analysis()` in `app.R`.** It asks for the
availability catalog first and returns NULL the moment anything is missing, so a
field warmed without it reads as entirely cold however much else is cached. That
is not hypothetical — it is what happened the first time this script ran.



A set of pre-analyzed fields spanning US cropping systems ships in
`data/fields/`. They appear in the sidebar as a two-across grid of tiles, each
captioned with the place and the CDL rotation, and clicking one opens it
**immediately** — no progress bar — because the results are already in
`cache/`. The loaded field is the highlighted tile.

The sidebar puts **your own boundary first** and the examples below it: the
examples are there to demonstrate, but the point of the tool is a field you
bring to it. Uploading clears the tile highlight, because what is loaded is the
upload — even if it happens to be a copy of one of the examples.

Captions come from `DEMO_LABELS` in `app.R` (the place) and
`outputs/demo_library.csv` (the crops, written by `warm_cache.R` from CDL).
A boundary dropped into `data/fields/` that is not in `DEMO_LABELS` still gets
a tile, captioned from its filename.

Warm the library once:

```bash
Rscript warm_cache.R
```

Then any field in it is one click. An uploaded boundary loads, you press **Run
analysis**, and it is cached from then on. If an uploaded boundary happens to
match one already in the cache, it restores instantly too — the key is the
geometry, not the filename.

**Changing the year range is not a one-line edit.** `YEAR_MIN` at the top of
`app.R` sets the slider's default, which feeds `analysis_window()`, which feeds
every cache key — widen it and the whole warmed library goes cold. See *How far
back can this go?* in the root `README.md` for what each earlier year is
actually worth: 2017 is a safe floor, 2016 runs but is indicative, and anything
before 2015 needs a Landsat reader that does not exist yet.

**Re-warm monthly.** `analysis_window()` ends the analysis at the start of the
current month rather than at today's date. Cache keys include that window, so an
end date of "today" would generate a new key every day and the library would go
cold overnight. The cost is excluding the current month, which against a
six-year series with an incomplete final season changes nothing material.

Uploads accept GeoJSON, KML, GeoPackage, or a shapefile (zipped, or select
`.shp`/`.shx`/`.dbf`/`.prj` together).

## The library, as analyzed

Every field below opens in well under a second. Crops are what CDL reported, not
labels I typed; `boundary` is the CDL tab's verdict; `cover` counts winters with
a likely cover crop or small grain.

| Field | Area | Obs. | Crops (CDL) | Boundary | Cover |
|---|---|---|---|---|---|
| Iowa, Story Co. | 65.9 ha | 368 | Soybeans/Corn | single unit | 0 |
| Iowa, Clinton Co. | 14.8 ha | 366 | Corn | single unit | 1 |
| Kansas, Riley Co. — rainfed | 12.5 ha | 257 | Corn/Soybeans | single unit | 0 |
| Maryland, Caroline Co. | 46.7 ha | 197 | Corn/Soybeans | single unit | 5 |
| Georgia, Tifton — El Dorado | 17.2 ha | 239 | Peanuts/Cotton | **split** | 6 |
| Georgia, Tifton — Carpenter Rd | 6.6 ha | 226 | Cotton/Peanuts | single unit | 6 |
| Arkansas, Lonoke Co. | 22.6 ha | 189 | Rice | single unit | 2 |
| Texas, Lubbock — pivot | 41.5 ha | 632 | Cotton/Corn/Fallow | single unit | 4 |
| Washington, Columbia Basin — pivot | 21.8 ha | 254 | Alfalfa/Potatoes | single unit | 2 |
| California, Central Valley | 13.2 ha | 341 | Dbl Crop WinWht/Corn, Triticale/Corn | single unit | 1 |
| Iowa — boundary drawn too wide | 173.4 ha | 360 | Soybeans/Corn | **split** | 0 |

Three results worth pointing at in a demo. The Arkansas field reads **Rice** and
the Washington pivot reads **Alfalfa/Potatoes** — neither was hinted at anywhere
in the code, both are exactly right for their region. And the southern
cotton/peanut fields show cover or small grain in **6 of 6 winters** against
**0 of 6** in Iowa and Kansas, which is the real regional contrast in
off-season cover, not an artifact.

Warming the full library from cold took **37 minutes**; re-running it against a
warm cache takes **0.0 minutes**.

### Where the model does not apply, and how it says so

Planting is read off a bare-soil-to-canopy transition. A perennial stand never
makes that transition, so the honest answer there is no answer — but the
tempting test, "NDVI never reaches bare soil", does not work on its own. The
heavily cover-cropped Maryland field bottoms out at **0.31** and the Washington
alfalfa pivot at **0.33**; that is not a gap you can put a threshold in, and an
early version of this check duly threw away a perfectly good Maryland planting
date.

What separates them is how much of the year is green. The alfalfa seasons sit
above NDVI 0.50 for **86–95%** of the year; every genuine row crop season in the
library, cover-cropped ones included, stays at or below **72%**, because residue
and the shoulder seasons pull the curve down even under a cover crop. So a
season is declared outside the model only when it never drops below 0.30 **and**
is green for 80%+ of the year.

On this library that flags 4 of the Washington pivot's 7 seasons and nothing
else. CDL independently reports **Alfalfa** for three of them, which is a useful
check on a rule derived purely from the NDVI curve. Those seasons report no
dates and say why; the pivot's potato years (2022–2024) still report dates
normally, which is the right per-season behavior for a field that rotates out
of alfalfa.

Standing water is handled separately and more gently. Open water reads as
negative NDVI, and rice ground is commonly held flooded through the winter. The
Arkansas field reaches −0.60 at its annual minimum, so all six of its seasons
carry the flood as a stated caveat and are capped at low confidence — the dates
are still reported, because they are indicative rather than meaningless. Its
cover crop verdicts for the flooded winters read **"off-season flooded — cover
crop not detectable"** rather than "no cover crop detected", which is the
difference between *unknown* and *none*. The two winters where real green did
appear (peaks of 0.37 and 0.64) are still reported as likely cover crop.

This is also why the Washington cover count in the table above is 2 rather than
5: three of those winters were the alfalfa stand being green in January, which
is not a cover crop sown after harvest.

### A correction worth knowing about

These figures are post-fix. Porting the pipeline to Python surfaced a bug here:
`terra::mask()` defaults to `touches = TRUE` for polygons, so the CDL clip was
keeping every 30 m cell the boundary so much as clipped — 233 cells (21.0 ha) on
a 17.2 ha field, 22% too many. Those extra cells sit mostly outside the field
and carry the neighbor's crop, so they inflated CDL areas, diluted the
dominant-crop percentage and biased the boundary check toward "split".

Fixed with `touches = FALSE`. Verdicts did not change; the numbers did. The
Georgia field's flagged area went from 7.1 ha to 5.2 ha, and California dropped
from 3 apparent cover-crop winters to 1. The Sentinel-2 path was never affected —
it uses `rasterize`, which already counted cell centers correctly.

## What it found

### Iowa — 368 clear observations from 681 scenes

| Year | Crop (CDL) | Planting | Harvest | Season | Peak NDVI | Confidence |
|---|---|---|---|---|---|---|
| 2020 | Soybeans | 28 May | 21 Sep | 98 d | 0.92 | high |
| 2021 | Corn | 17 May | 1 Oct | 116 d | 0.87 | high |
| 2022 | Corn | 29 May | 18 Oct | 121 d | 0.89 | high |
| 2023 | Corn | 10 May | 25 Sep | 117 d | 0.94 | high |
| 2024 | Soybeans | 7 Jun | 4 Oct | 101 d | 0.93 | high |
| 2025 | Corn | 11 May | 9 Sep | 100 d | 0.92 | medium |

Corn seasons average ~113 days against ~100 for soybeans, which is agronomically
right and was not imposed anywhere in the code. The rotation is corn-on-corn
2021–23 rather than strict alternation — CDL confirms that independently.

Off-season NDVI peaks at 0.21–0.28 across all six winters: bare residue, **no
cover crop in any year**. That is the expected answer for a conventional Iowa
field and it is what makes the Maryland comparison meaningful.

### Maryland — the cover crop case

| Winter | Max off-season NDVI | Verdict |
|---|---|---|
| 2020-21 | 0.44 | likely cover crop |
| 2021-22 | 0.57 | green cover — cover crop or small grain |
| 2022-23 | 0.59 | likely cover crop |
| 2023-24 | 0.61 | green cover — cover crop or small grain |
| 2024-25 | 0.32 | possible cover crop |
| 2025-26 | 0.57 | likely cover crop |

Off-season NDVI peaks each April at 0.44–0.61, two to three times the Iowa
field. The two hedged winters are the ones followed by soybeans planted in late
June — the signature of double cropping after a harvested small grain rather
than a terminated cover crop. The code flags that rather than asserting a
practice, because NDVI alone cannot separate the two.

The 2024-25 winter reads "possible" on a single observation above threshold —
correctly hedged rather than counted.

## Python port

`python/` holds a full port of this pipeline for the platform team — library
modules and a CLI, no app. Same data sources, same algorithms, same cache
semantics, with the module layout mirroring `R/` one-to-one.

```bash
cd python && pip install -r requirements.txt
python run_field.py ../data/fields/example_field.geojson
```

Validated against this R pipeline on three fields (Iowa, Maryland, Georgia):
identical observation counts, boundary verdicts and cover crop verdicts, with
season dates never more than one day apart. See `python/README.md` for the
comparison table and the places the two implementations deliberately differ.

## Data sources

All free, all public, none requiring an account.

| Source | Resolution | Revisit | Used for |
|---|---|---|---|
| Sentinel-2 L2A | 10 m | ~5 days | Everything — NDVI, RGB, cloud masking |
| Landsat 8/9 | 30 m | ~8 days | Long baselines (archive to 1982) |
| HLS (S30/L30) | 30 m | ~5/8 days | Harmonised Landsat+Sentinel |
| Sentinel-1 RTC | 10 m | ~12 days | Radar — sees through cloud |
| MODIS 16-day NDVI | 250 m | 16 days | Coarse 2000→now reference |
| NAIP | 0.6 m | 2–3 years | Sub-meter aerial context |
| USDA CDL | 30 m | Annual | Crop type per field per year |

The Data availability tab queries catalog metadata only, so the whole sweep
takes seconds. It is a good opening slide: it shows how much exists for a field
before anyone commits to processing it.

## How the estimates work

**Planting and harvest.** NDVI cannot see a planter or a combine. It sees the
canopy. The pipeline smooths the season's observations, finds the summer peak,
takes the trough before it as bare soil, and marks where the curve crosses 20%
of the way up on the rising limb. Planting is that green-up date minus a
crop-specific lag (21 days corn, 18 soybeans).

Harvest is measured against the **lowest point after the peak**, not against
spring. Wherever something green follows the cash crop, NDVI never returns to
the spring floor, so a spring-anchored threshold reports no harvest at all — on
a cover-cropped cotton field that blanked five consecutive seasons. A season
still under way is left blank rather than guessed.

The quoted window is ±14 days, and **widens automatically** where cloud left a
gap near the transition — a crossing that falls inside a three-week hole is
reported as such rather than quietly given the same confidence as one bracketed
by clear images.

**Cover crops.** After harvest an Iowa field is residue: NDVI 0.10–0.25 all
winter. A cover crop establishes in autumn and greens up again in spring,
appearing as a hump above that floor. The verdict is driven by peak off-season
NDVI and how many observations sustain it.

Every winter is drawn at once as small multiples on a shared October-to-June
axis, rather than one at a time. Lining them up is the point: six flat Iowa
winters beside six humped Maryland ones makes the difference obvious without
reading a single number.

**The cover crop / phenology interaction.** A cover-cropped field has a bimodal
NDVI curve — cover crop peak, dip at termination, then cash crop peak. Anchoring
the season baseline on "spring NDVI" would read the cover crop as an early cash
crop. The code anchors on the trough immediately before the summer peak instead,
which is bare soil in both cases.

## Limits — read this before quoting numbers

- **Nothing here is calibrated.** Thresholds and lags are literature-typical
  starting values. Regressing these estimates against member-reported planting
  dates is the single highest-value next step and would turn ±14 days into
  something defensible.
- **NDVI sees green, not intent.** A cover crop verdict cannot be separated from
  volunteer grain, winter annual weeds, or a grassed waterway inside the
  boundary on spectral evidence alone. Winter cash crops are flagged via CDL;
  the rest are named as confounders, not resolved.
- **Scene cloud percentage is not field cloud percentage.** The catalog figure
  covers a 110 km tile. Filtering is done on the fraction of *field* pixels that
  survive masking.
- **Winter coverage is thin.** Snow is masked out, so snowy dates vanish rather
  than reading as bare soil. That is correct but it thins exactly the window
  cover crop detection needs — `n_obs` is reported alongside every verdict.
- **Boundary quality drives everything.** A boundary spanning two management
  units averages two different crops. The CDL tab shows the dominant class share
  so this is visible.
- **The 2022 reflectance offset.** ESA added a −1000 offset from processing
  baseline 04.00. Handled per scene. Pipelines that miss it show a step change in
  early 2022 that looks like a trend.

## Performance

Measured on the Iowa field, 2020 → Sept 2026:

| Stage | First run | Cached |
|---|---|---|
| Catalog sweep (8 sources, 3,573 acquisitions) | ~60 s | instant |
| CDL crop history (6 years) | ~90 s | instant |
| Imagery: 681 scenes → 368 clear observations | 254 s | instant |

2.3 s/scene sequentially, ~0.6 s/scene across 8 parallel workers. Everything is
cached to `cache/` keyed on the boundary geometry, so re-analysis is instant,
re-uploading the same boundary hits the cache, and editing a boundary correctly
misses it.

**For a live demo, run each field once beforehand** so the cache is warm and the
app responds instantly.

### The Imagery tab

The contact sheet is the one place that still does real work mid-demo, because
a quarter you have not opened before is 16-33 scenes that have to be read. Three
fixed costs used to sit in front of that read and have been removed:

| | Before | After |
|---|---|---|
| Catalog search, first press after app start | 8.8 s | 0.2 s |
| Signing scenes before reading | 22.7 s | ~0.4 s |
| Worker pool spin-up, **every press** | 2.0 s | 0 s (once at startup) |
| Cold quarter, 33 scenes, true color | — | 21 s |
| Cold quarter, 16 scenes, NDVI | — | 6 s |
| Any quarter already viewed in that view | — | 0.02 s |

- **The catalog is cached to disk** like everything else. It was the only
  network call in the app that always went out. The key carries the literal end
  date rather than being floored to the month the way `analysis_window()` does:
  a stale month would hide the newest acquisitions from the one tab whose job is
  showing what was collected, so a past-year range caches indefinitely and the
  current year re-queries once a day.
- **Only the quarter being viewed gets signed.** `items_sign()` rewrites every
  asset href on every feature it is handed, so signing the whole 823-scene
  catalog to look at 16 thumbnails was the single largest cost in the tab —
  larger than the imagery read it preceded. `sign_subset()` signs the slice.
- **One worker pool, held open.** `future::plan(multisession)` spawns fresh R
  subprocesses; both the contact sheet and the extraction used to set a plan on
  entry and tear it down on exit, so every press paid the spin-up again.
  `ensure_workers()` starts the pool once and only ever grows it, and `app.R`
  starts it at launch.

**The tab tells you which it will be before you press the button.** A live
notice above the contact sheet reads either *"Already loaded — opens
instantly"* or *"First load — N scenes to read, up to 90 seconds"*, and flips
to the green state as soon as a sheet has been written. It is computed from
`grid_cached()`, the same key function `scene_grid()` uses, so the promise
cannot drift from what actually happens; an indicator that says "instant" and
then takes a minute would be worse than no indicator.

It never triggers a network call to work this out. If the catalog for that
field is not on disk yet there are no scene ids to hash, so it falls back to
the general first-load wording — opening the Imagery tab has to stay free,
which is the same reason the quarter dropdown is built from the calendar
rather than from a search.

One thing to know for a demo: **the view is part of the cache key.** Flipping
true color → NDVI on a quarter you just loaded re-reads it, because those are
different bands. The notice says so, and switches back to orange when you
change the view to one that has not been read.

## Figures

`run_demo.R` and the app write to `outputs/`. The two worth putting in front of
leadership:

- `08_timeline.png` — every acquisition over one field since 2020, all sources
- `10_covercrop_maryland.png` — the cover crop signal: dips to residue in
  November, climbs all winter, peaks 0.61 in mid-April, back to 0.25 by June.
  Compare with `10_covercrop_iowa.png`, which never leaves the residue band.
- `13_phenology_timeline_2panel.png` — seven seasons with crop labels and
  planting/harvest markers; the flat winters make "no cover crop" obvious
- `16_cdl_matrix_overgrown.png` / `17_cdl_split_overgrown.png` — the boundary
  check catching a deliberately overgrown boundary: the real field is the pale
  core, the buffered-on ring is red in every year
- `12_grid_ndvi_2024Q3.png` — 25 dates in one quarter; the 2024 soybean harvest
  is visible between 7 and 30 September

## Project layout

```
app.R              the Shiny app
warm_cache.R       pre-compute the demo library (run monthly)
pipeline.R         source() this to load everything
run_demo.R         single-season worked example
setup.R            install + connectivity check
R/aoi.R            boundary loading and cleaning
R/imagery.R        Sentinel-2 search and load
R/extract.R        parallel multi-year extraction
R/cache.R          disk cache
R/parallel.R       the shared worker pool
R/catalog.R        multi-source availability
R/cropland.R       USDA CDL fetch, stack and rotation table
R/cdl_split.R      boundary check: one field or two?
R/indices.R        NDVI and friends — add your own here
R/thumbnails.R     contact sheets for a period
R/phenology.R      planting and harvest
R/covercrop.R      off-season green cover
R/armor.R          soil armor: NDVI-DFI cover unmixing
R/residue.R        residue and tillage indices (superseded by armor.R)
R/plotting.R       maps and composites
R/timeseries.R     single-season curves
R/gee.R            optional Earth Engine backend (not wired into the app)
```

## The Soil armor tab

`R/armor.R` reads the shortwave infrared through each season's pre-planting
window and reports how much of the surface is protected — **by anything**.

Every pixel is decomposed into three fractions that sum to one: living green
cover (`f_pv`), crop residue (`f_npv`) and bare soil (`f_bs`). **Soil armor is
`1 - f_bs`.**

This replaced an earlier minimum-NDTI metric, and the reason is worth keeping.
NDTI measures residue only, so a field under a living cover crop or a perennial
stand scored as though it were bare. On this library that was not a subtle
error: the Washington alfalfa pivot — a permanent stand, the best-protected
soil here — ranked **last of eleven fields**. It now ranks first. See *Soil
armor: the metric that replaced minimum NDTI* in the root `README.md` for the
side-by-side.

The separation comes from DFI, not NDVI. In the fitted endmembers, residue and
bare soil differ by **0.05 in NDVI and by 22 in DFI** — NDVI genuinely cannot
tell them apart, which is why an index pair is needed rather than a single one. It is on its own button, like the Imagery
tab, because it is a second pass over the archive on different bands — and like
that tab it says whether the field is already cached before you press it. The
demo library is warmed, so those eleven open instantly.

Per year it reports the window, how many clear observations fell in it, how
many of those were bare versus green, and the minimum, median and maximum NDTI
over the bare ones. **Every season gets a row**, including the ones with
nothing to report — a year with no window, no usable observation or no bare
ground says so in `note` rather than going missing. That keeps this table the
same length as the Summary tab's, and stops "absent" being confused with
"never computed". Across the demo library that is 77 rows, 64 of which carry a
readable minimum. The plot shows every observation so the number is auditable:
filled points are bare ground, hollow gray ones were screened out as green.

Three reference bands sit behind the data — below 0.05, 0.05–0.09, above 0.09,
the 33rd and 75th percentiles of this library's own 64 seasons. They are drawn
and never tabulated, so a reader can see where a field sits without the app
asserting a class. `RESIDUE_BREAKS` in `R/residue.R` and `residue.py` holds
them, and `residue_band()` applies them — deliberately not called by
`residue_summary()`.

**There is no tillage class, on purpose.** Three reasons, the first two measured
on this library rather than taken from the literature:

- **Soil moisture moves NDTI more than tillage does.** On the Iowa field, 18 and
  20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 — a four-fold
  swing on rain, two days apart, with no change in residue. That is why the
  minimum across a window is the headline number rather than any single date,
  which is also what the minNDTI literature settled on.
- **NDTI cannot tell residue from green cover**, because a live canopy absorbs
  in the SWIR too. Dates above NDVI 0.30 are screened out and counted. On the
  Maryland cover-cropped field that leaves no bare ground at all in 4 of 7
  springs — the cover crop runs right up to planting — and the tab says
  "not enough bare ground to read" rather than inventing a number.
- **Published field-level accuracy is 73–80%** for this family of multispectral
  methods, so roughly one field in four would be misclassified. The accurate
  method, CAI at over 90%, needs three narrow bands inside the 2000–2200 nm
  cellulose feature; Sentinel-2's B12 is one 180 nm-wide band covering all of
  it, so CAI is out of reach here.

Calibrating `min_ndti` against residue line-transect measurements is what would
turn this into a class. Until then it is a research surface, not an output.

### The pieces

| | |
|---|---|
| `ndti`, `ndi7`, `ndsvi` | registered indices, no band changes needed |
| `residue_window(phen, year, season)` | the bare-soil period, from the phenology table |
| `residue_series(aoi, years)` | spring-only extraction, 1 Mar–30 Jun per year |
| `residue_all_years(ts, phen)` | one row per season |
| `plot_residue(ts, res)` | the per-year panels the tab draws |

`season = "spring"` (the default) starts no earlier than 1 March, the window
minNDTI-style methods use. `season = "full"` runs from the previous harvest and
so also covers fall tillage, over a much longer span where moisture varies more
— note the warmed series only covers spring.

## Adding an index

Everything downstream picks it up automatically:

```r
add_index("my_index",
  fn    = function(b) (b$nir - b$swir22) / (b$nir + b$swir22),
  bands = c("nir", "swir22"),
  range = c(-1, 1),
  desc  = "Testing against yield data")

extract_field_series(field, indices = c("ndvi", "my_index"))
```

Index functions must be self-contained arithmetic on `b` — they are shipped to
parallel workers with their environment stripped.

## On Earth Engine

Still not needed and still not wired in. The app reads Sentinel-2 directly from
Microsoft Planetary Computer, which needs no account and no Python. `R/gee.R`
remains as a starting point for when this moves to thousands of fields, where
server-side reduction would pay for the setup. It has not been run against a
live account.
