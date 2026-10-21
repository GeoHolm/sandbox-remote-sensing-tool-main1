# Alfalfa cuttings, San Juan County, New Mexico

One 62-acre field, read from a Shiny report pack exported on 19 October 2026.
The pack carries 713 cloud-free observations from January 2020 to September
2026, a clear image about every three days.

The field grew winter wheat in 2020 and 2021 and alfalfa from 2022 onward
(USDA Cropland Data Layer, 99.6–100% purity every year). That rotation is why
it is worth the attention: it contains its own control.

## Where it is, and what the boundary actually is

San Juan County, New Mexico — the irrigated valley northwest of Farmington,
at about 1,600 m. The county is read from the Census polygon containing the
centroid (-108.22897, 36.57477), not asserted.

USDA NAIP imagery at 0.6 m, flown 25 May 2022, shows what the tables do not:
**this is a center pivot**, a 49.3 ha (122-acre) irrigated circle with its
wheel tracks and center point plainly visible. Pivot area measured from the
NAIP near-infrared band.

**The boundary that came with the report pack is an axis-aligned rectangle
with `field_id: "drawn"`** — drawn by hand in the Shiny app, not digitized
from a field record. It is inscribed inside the pivot and covers **51% of
it**, never reaching the dry corners.

That cuts both ways, and both belong in any reading of the numbers:

- It explains the unusually clean signal. The crop layer reads 100% one crop
  and the NDVI curve has no edge effects because the box samples the middle
  of a uniform pivot.
- Every figure in this study therefore describes **half a pivot**, not a
  whole field. A boundary drawn to the pivot edge would include the wetted
  margin and the dry corners and would not behave the same way.

`figure_alfalfa_location.py` writes the map and `alfalfa-nm/location.json`.

## What was found

**Three to four cuttings a year, in every alfalfa season.** Fifteen cuttings
across five seasons, detected from the shape of the NDVI curve alone.

| Year | Crop | Cuttings | First to last | Mean gap |
|---|---|---|---|---|
| 2020 | Winter Wheat | 1 | 28 Jun | — |
| 2021 | Winter Wheat | 1 | 25 Jun | — |
| 2022 | Alfalfa | 4 (1 flagged) | 13 Jun – 18 Oct | 42 d |
| 2023 | Alfalfa | 4 (1 flagged) | 15 Jun – 11 Oct | 39 d |
| 2024 | Alfalfa | 3 | 04 Jun – 12 Sep | 50 d |
| 2025 | Alfalfa | 4 (1 flagged) | 12 Jun – 01 Nov | 47 d |
| 2026 | not published yet | 3 | 02 Jun – 08 Aug | 34 d |

2026 runs to 20 September only. "Flagged" means detected after 1 October, when
a hard freeze would produce the same signature.

Supporting numbers: median gap between cuttings 43 days (range 33–62); first
cutting between 4 and 15 June in all five years; greenness falls from a median
0.93 to 0.48 across a cutting and is back to full canopy in a median of 15
days.

**The two wheat years give one biomass removal each** — the grain harvest —
from the identical method with no constant changed. That is the closest thing
to a control available without a grower record.

## What this says about the pipeline

**The annual-crop phenology model mis-reads a perennial.** It reports one
planting and one harvest per year. On this field the reported "harvest" lands
on the first cutting in 2023, the second in 2026, the third in 2025, and on
nothing at all in 2022 and 2024. The reported season length swings from 63 to
264 days on an unchanging crop.

**Cover crop and pre-planting soil armor stop meaning anything.** A perennial
has no off-season. Four of the five winters from 2021–22 are scored "likely
cover crop" and the fifth "possible"; the clearest case is winter 2023–24,
scored on an off-season greenness peak of 0.94 on 6 October, which is the
standing hay crop five days before the fourth cutting. The pre-planting armor
window collapses to nothing in 2024 and 2026 because there is no planting.

Neither metric is broken. Both were defined for a crop planted and harvested
once a year.

**Suggested path:** detect the crop as perennial from the Cropland Data Layer,
then skip planting, harvest, cover crop and pre-planting armor for that field,
and report a cutting series instead.

## How a cutting is detected

`detect_alfalfa_cuttings.py`. A cutting is a step down in NDVI meeting four
tests, each added because a case in this field's own record defeated the rule
before it:

| Test | Requires | The case behind it |
|---|---|---|
| Standing | Greenness above 0.60 before the fall | Dormant winter regrowth oscillates near 0.45 |
| Step | A drop of ≥0.30 from the **last standing observation**, within 12 days | Measuring from the seasonal peak instead turned the 7-day first cutting of 2023 into a "27-day senescence" and missed it |
| Persistent | The low holds for ≥2 clear observations | 12 Aug 2023 reads 0.49 between a 0.90 and a 0.93 five days later — cloud shadow. Without this, 2023 reads six cuttings |
| Spaced | ≥18 days since the previous cutting | A stand needs about a month to regrow |

Cloud is judged on `valid_frac`, the share of **field** pixels surviving the
mask, not scene cloud percentage: five of the twenty detected falls sit under
scenes 14–34% clouded and the field is clear in every one.

## What has not been established

- **No cutting record has ever been checked against this**, for this field or
  any other. Every count here is read from the shape of a curve. No accuracy
  figure exists and none is quoted.
- **Autumn is ambiguous.** Three of fifteen cuttings fall after 1 October,
  where a hard freeze is indistinguishable. They are flagged, not dropped.
  The weakest is 1 November 2025: it passes every test on a fully clear field,
  but the canopy reads 0.82 again eight days later and nothing else in four
  years of this stand regrows that fast.
- **Dates are windows, not days** — a median of 10 days between the last
  standing image and the first showing stubble, set by cloud and revisit.
- **The constants were tuned on this one field**, read against its 2023 season
  and then left alone across the other six years.
- **It is one field, and only half a pivot of it** — a drawn rectangle
  covering 51% of one center pivot in one irrigated valley. A boundary taken
  to the pivot edge would include the wetted margin and would not behave the
  same way.

## Files

| | |
|---|---|
| `detect_alfalfa_cuttings.py` | the detector; prints an audit trail of every candidate accepted or rejected |
| `figures_alfalfa.py` | six figures from the pack; `--bare` writes the title-free set the deck uses |
| `figure_alfalfa_location.py` | the locator map and NAIP panel; needs the network, which is why it is separate |
| `build_alfalfa_pdf.py` | the 14-slide deck, printed through headless Edge |
| `build_alfalfa_pptx.py` | the same deck as editable PowerPoint, with a fit check over text, pictures and tables |
| `alfalfa-nm/cuttings.csv` | one row per detected cutting, with diagnostics |
| `alfalfa-nm/cutting_summary.csv` | one row per year |
| `alfalfa-nm/location.json` | county, centroid, acreage, NAIP scene used |

The report pack it all reads from is not committed: it carries a precise farm
boundary, the same reasoning as the Fieldprint payloads under
`project-level-tests/*/`. Drop the pack back into `alfalfa-nm/pack/` to
reproduce.
