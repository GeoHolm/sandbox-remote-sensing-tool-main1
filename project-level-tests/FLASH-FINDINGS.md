# FLASH project-level test — 98 Illinois fields

Run 11 October 2026. 98 distinct boundaries, winters 2022-23 to 2025-26,
88.3 minutes, 0 failures.

Project 370, *Farmer-Led Advances in Soil Health*, 195 Fieldprint payloads from
Jo Daviess County and nearby, Illinois. 6–291 acres, median 79.

---

## The headline

**Georgia fields with no cover crop are greener in winter than Illinois fields
with one.**

| | median peak off-season NDVI |
|---|---|
| Georgia, **no** cover crop reported (n = 155) | **0.530** |
| Georgia, cover crop reported (n = 191) | 0.638 |
| Illinois FLASH, **cover crop** reported (n = 98) | **0.330** |

96.1% of Georgia's no-cover fields sit above the median Illinois
cover-cropped field. Against the shipped `CC_GREEN_MIN` of 0.30 the same
constant produces:

- **98.1%** of Georgia's no-cover fields called positive — near-total false
  positives, the 7.1% specificity already documented
- **35.7%** of Illinois' cover-cropped fields called negative — false negatives,
  the opposite failure

One national threshold cannot serve both. This is the single-number case for
regional calibration, and it now rests on two independent datasets rather than
one.

---

## What the test could and could not measure

`planting_cover` appears **98 times in the whole archive — once per field, all
in the 2026 harvest-year interval.** Every year from 2008 to 2025 carries
tillage, planting, fertilizer and harvest activities and zero cover crop
records: the historical intervals are rotation skeletons, not practice records.

So the labelled set is 98 positives and **no negatives**. Sensitivity is
measurable; specificity is not. The earlier winters are reported as what the
detector *claims*, not as a score.

---

## Sensitivity, winter 2025-26

| reading | caught |
|---|---|
| strict — *likely cover crop* only | **35 / 98 = 35.7%** |
| loose — *likely + possible + green cover* | **63 / 98 = 64.3%** |

Georgia reached 98.4% sensitivity. Same detector, same constants, inverted
failure.

### The misses are not bare fields

All 35 misses fall between NDVI **0.193 and 0.292**. Not one is below 0.15;
34 of 35 sit in 0.20–0.30. The detector saw green on every missed field and
none of it cleared the line.

| peak NDVI threshold | sensitivity |
|---|---|
| ≥ 0.20 | 99.0% |
| ≥ 0.25 | 81.6% |
| **≥ 0.30 (shipped)** | **64.3%** |
| ≥ 0.35 (`CC_STRONG`) | 40.8% |

A threshold at 0.25 would catch 18 more of these fields. **This cannot be used
to pick one** — with no labelled negatives, lowering the threshold has no
measurable cost here, and the Georgia data says that cost is severe.

---

## What else moves detection

**Winter observation count, strongly.**

| clear observations in the window | detection rate |
|---|---|
| ≤ 10 | 35.7% |
| 11–15 | 56.8% |
| 16–20 | 66.7% |
| > 20 | 88.5% |

Median 14 observations per winter, minimum 8. Gaps of 10 Nov → 13 Feb → 4 May
appear on individual fields. Northern Illinois winter cloud is thinning the
record where the signal lives.

**Boundary quality, in the direction nobody expects.**

| boundary verdict | detection rate |
|---|---|
| single unit (n = 69) | **56.5%** |
| trim (n = 11) | 81.8% |
| split (n = 18) | **83.3%** |

Impure boundaries detect cover crops *more* often. A boundary spilling into a
grassed waterway, a field margin or a neighbor's ground picks up winter green
that is not the field's, and the average rises. 29 of 98 boundaries here are
not a single management unit — a much higher rate than the demo library — and
on this cohort that inflates detection rather than degrading it.

---

## The four-winter trend

| winter | any green reported | median peak NDVI |
|---|---|---|
| 2022-23 | 30.6% | 0.281 |
| 2023-24 | 46.9% | 0.300 |
| 2024-25 | 54.1% | 0.312 |
| 2025-26 | 64.3% | 0.330 |

Monotonic. This is what a cohort progressively adopting cover crops looks
like — which is what a soil health project is — but only the last winter is
labelled, so nothing here separates adoption from detector drift.

---

## Is 35.7% a detector failure?

Not necessarily, and the distinction matters.

A cover crop drilled 19 October at 42° N and terminated 20 May may genuinely
carry very little biomass until late spring. The grower reports **an action**,
with planting and termination dates. The satellite reports **biomass**. Those
are different claims, and the cover crop literature this threshold came from is
framed around *performance* for exactly that reason.

So the 35 misses are either a threshold set too high for this latitude, or a
true statement that those stands did not establish. Only agronomic ground truth
— biomass cuts or percent-groundcover transects — separates them, and that is
the same ask the cotton deck already makes.

One hypothesis **was tested and rejected**: that the window closes before
termination and clips the spring green-up. Across the cohort the window closes
a median of 5 days *after* termination. It does happen on individual fields —
`09d2bc91439b`'s window ended 28 April against a 20 May termination, and its
only green-up fell outside — but it is not the explanation.

---

## Reproducing

```
python project-level-tests/extract_flash.py     # payloads -> boundaries + labels
python project-level-tests/run_flash.py         # the pipeline, ~90 min
python project-level-tests/analyse_flash.py     # the comparison
python project-level-tests/threshold_flash.py   # threshold sensitivity
```

The payload archive, the boundaries and `fields.csv` are **not committed** —
they carry grower email addresses, farm names, yields and precise field
locations. Everything else is keyed by a geometry hash. Drop the archive back
into `project-FLASH/Fieldprint-payloads/` to re-run.

One detail worth keeping: 195 payloads collapse to 98 boundaries. The same
physical field appears once per crop year under a different Fieldprint id, so
keying on that id would run the pipeline twice over identical ground and report
the two runs as independent agreement.
