# Pitch material

Stakeholder-facing material built from this repository's findings. Kept here so
the numbers on a slide can be traced back to the code that produced them, and
so the deck outlives the demonstration app.

## Contents

| | |
|---|---|
| `cotton-2026/` | Slide source for the cotton industry funding pitch, September 2026 |
| `cotton-2026/Cotton-Remote-Sensing-Pitch.pptx` | The same deck as a native PowerPoint, rebuilt by `build_pptx.py` |
| `IMPLEMENTATION-ESTIMATE.md` | Developer-hour estimate for moving the pipeline into the Fieldprint Platform |
| `branding-assets/` | Field to Market brand guide and horizontal logos |
| `Field-to-Market-Remote-Sensing-Methods.pdf` | The methods reference as a branded PDF, built by `build_methods_pdf.py` |

## The cotton deck

16 slides: a 15-slide narrative plus a technical appendix shown only if an
engineering evaluator is in the room. The live version is a Claude Artifact,
which is where it is edited and where a `.pptx` or PDF is downloaded from. The
files here are that deck's source, copied out so it is under version control.

`deck.json` is the index — slide order, sections and typefaces. Each
`slides/<id>.html` is one slide; the `<aside>` at the end of each is the
speaker notes, which carry the argument to make and where to slow down.

**Editing.** Change the artifact, then re-copy these files. Editing here alone
changes nothing that anyone will present.

**The .pptx is a rebuild, not an export — and it is the branded one.**
`build_pptx.py` reconstructs the deck with `python-pptx` on Field to Market
branding per `branding-assets/ftm_brand.md`: the six-color palette at its
40/40/5/5/5/5 weighting, the 1.25in Deep Current header bar, the 0.38in brand
footer strip at y = 7.12, Arial Narrow Bold headings over Arial body, and the
horizontal logo. The web artifact keeps its own look, so **the two decks do not
match** — use the .pptx when the deck should look like Field to Market, and the
artifact's Share > Export when it should look like what you reviewed on screen.
Re-run `python pitch/cotton-2026/build_pptx.py` after changing the slides.

Two brand decisions worth knowing. The supplied logo is Deep Current on
transparent with no reversed version, so it appears on light slides only and the
footer strip carries the identity on the blue ones. And text on the Meadow Pulse
and Ember Glow fills is Night Spark rather than white: both primaries are
mid-luminance, so white on them measures 2.8–3.0:1 against a 4.5:1 floor, while
#212121 measures 5.5–5.7:1. Ember Glow on white is 3.0:1, so it is used for
bars, rules and borders but never for small text — Twilight Bloom carries the
"worst case" signal instead.

**The one image** is referenced as `/_blob/ca4882e2b861cf1698a0cd028fb40e70`
in `slides/demo.html`, which resolves only inside the artifact. It is
[`r/outputs/20_cotton_two_years.png`](../r/outputs/20_cotton_two_years.png) —
Tifton, Georgia and Lubbock, Texas, two years of cover fractions each.

## Where the numbers come from

Every figure in the deck traces to the validation work:

| Slide | Source |
|---|---|
| Cotton scorecard, confusion counts | `validation/confusion.py` |
| The tillage x cover 2x2, and the four named fields | `validation/analyse.py`, `data/fields/library.csv` |
| Soil armor by tillage class | `validation/metrics.csv` |
| Boundary purity gate | `validation/analyse_cdl.py` |
| Cover crop thresholds, Corn Belt vs refitted | `validation/analyse_cover.py` |
| Two-field cover fraction chart | `r/outputs/20_cotton_two_years.png` |

The root README's *Validation against ground truth* section is the written
account, including the caveats the deck compresses.

## Placeholders still open

`slides/invest.html` carries `[$____]`, `[__ months]`, `[___] cotton fields`
and `[___] regions`. These were deliberately not invented.
`IMPLEMENTATION-ESTIMATE.md` gives a defensible basis for the Phase 1 figure.

## A caution

The deck argues a case. The root README does not. Where the two differ in
emphasis, **the README is authoritative** — it states the limits in full, and
those limits are what anyone quoting a number needs. In particular: soil armor
is a cover metric and not a tillage metric, all validation is Georgia, and the
Texas field on the demo slide is an illustration rather than a validated
result.

## The methods PDF

[`../METHODS.md`](../METHODS.md) rendered on Field to Market branding, for
sending to a reviewer who will not read a repository. Rebuild it after changing
the Markdown:

```bash
python pitch/build_methods_pdf.py              # add --keep-html to inspect
```

Two steps, because nothing on a standard Windows install does it in one: pandoc
converts the Markdown to an HTML fragment, and headless Edge prints that to PDF.
There is no LaTeX, wkhtmltopdf or weasyprint here, and Chromium handles the
paged-media CSS correctly. The six-color brand strip is one `linear-gradient`
with hard stops at the 40/40/5/5/5/5 proportions, in a `position: fixed`
element so it repeats on every page; each `##` section starts a new page.

**If Edge hangs,** something else has the output PDF open — a viewer holding the
file lock is enough. Close it and re-run.

**No page numbers.** Chromium will not evaluate `counter(page)` inside a fixed
element, and Edge's own footer would stamp the local file path across the
bottom of every page. The running footer carries the document name instead.
