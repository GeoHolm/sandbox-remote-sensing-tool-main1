#!/usr/bin/env python3
"""Build the New Mexico alfalfa cutting-detection case study as a slide PDF.

    python project-level-tests/build_alfalfa_pdf.py [--keep-html]

HTML pages sized 13.333 x 7.5in, printed through headless Edge -- the same
mechanism build_flash_pdf.py and pitch/build_methods_pdf.py use, and the same
Field to Market branding.

Fourteen slides. Everything on them comes from the report pack or from
detect_alfalfa_cuttings.py; nothing is estimated, and no accuracy figure
appears anywhere, because none has been measured.
"""
import base64
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJ = HERE / "alfalfa-nm"
# The title-free renderings: the slide carries the heading.
FIG = PROJ / "figures" / "deck"
BRAND = REPO / "pitch" / "branding-assets"
OUT_HTML = PROJ / "_alfalfa_slides.html"
OUT_PDF = PROJ / "NewMexico-Alfalfa-Cuttings.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

BLUE, ORANGE = "#10427C", "#F46C09"
INK, GRAY, MUTED = "#212121", "#58595B", "#8a8c8e"
BAR = [("#10427C", 40), ("#F46C09", 40), ("#00B14C", 5), ("#0D9AC6", 5),
       ("#462668", 5), ("#FFD103", 5)]

cut = pd.read_csv(PROJ / "cuttings.csv", parse_dates=["first_cut_obs"])
summ = pd.read_csv(PROJ / "cutting_summary.csv")


def b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()


def img(name, style=""):
    return f'<img src="data:image/png;base64,{b64(FIG / name)}" style="{style}">'


CSS = """
@page { size: 13.333in 7.5in; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: #212121;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.slide { position: relative; width: 13.333in; height: 7.5in;
         padding: 1.05in 0.62in 0.78in;
         display: flex; flex-direction: column; justify-content: center;
         page-break-after: always; overflow: hidden; background: #fff; }
.slide > * { flex: 0 0 auto; }
.slide:last-child { page-break-after: auto; }
.bar { position: absolute; left: 0; right: 0; bottom: 0; height: 0.30in;
       display: flex; }
.bar span { height: 100%; }
h1 { font-family: "Arial Narrow", Arial, sans-serif; font-size: 40pt; line-height: 1.08;
     color: #10427C; margin: 0 0 .12in; font-weight: 700; }
h2 { font-family: "Arial Narrow", Arial, sans-serif; font-size: 25pt; color: #10427C;
     margin: 0 0 .07in; font-weight: 700; }
.sub { font-size: 12.5pt; color: #58595B; margin: 0 0 .20in; line-height: 1.40; }
.note { position: absolute; left: .62in; right: .62in; bottom: .42in;
        font-size: 9.2pt; color: #8a8c8e; line-height: 1.38; }
.fig { display: block; margin: 0 auto; }
p, li { font-size: 12.5pt; line-height: 1.52; color: #58595B; }
b, strong { color: #212121; }
ul { margin: .04in 0 0; padding-left: .22in; }
li { margin-bottom: .07in; }
.cols { display: flex; gap: .34in; }
.col { flex: 1 1 0; min-width: 0; }
.col img { width: 100%; height: auto; }
.cards { display: flex; gap: .20in; margin: .10in 0 .18in; align-items: stretch; }
.card { flex: 1; border: 1.5px solid #10427C; border-radius: 9px; padding: .17in .19in; }
.card.o { border-color: #F46C09; }
.card .big { font-family: "Arial Narrow", Arial, sans-serif; font-size: 36pt;
             font-weight: 700; color: #10427C; line-height: 1; }
.card.o .big { color: #F46C09; }
.card .lab { font-size: 10.5pt; color: #58595B; margin-top: .07in; line-height: 1.32; }
table { border-collapse: collapse; width: 100%; font-size: 11.5pt; margin-top: .08in; }
th { background: #10427C; color: #fff; text-align: left; padding: .09in .12in;
     font-family: "Arial Narrow", Arial, sans-serif; font-size: 11.5pt; }
td { padding: .085in .12in; border-bottom: 1px solid #e8e8e8; color: #444; }
tr:nth-child(even) td { background: #f7f7f7; }
td.n, th.n { text-align: center; }
.kicker { font-size: 9.5pt; letter-spacing: .09em; text-transform: uppercase;
          color: #F46C09; font-weight: 700; margin-bottom: .10in; }
.quote { border-left: 4px solid #F46C09; padding-left: .18in; font-size: 14pt;
         color: #212121; line-height: 1.42; }
.logo { position: absolute; right: .62in; top: .42in; width: 2.0in; }
.flag { color: #F46C09; font-weight: 700; }
"""


def slide(body, logo=True):
    bar = "".join(f'<span style="background:{c};width:{p}%"></span>' for c, p in BAR)
    lg = (f'<img class="logo" src="data:image/png;base64,{b64(BRAND / "FTM-H_rgb.png")}">'
          if logo else "")
    return f'<section class="slide">{lg}{body}<div class="bar">{bar}</div></section>'


def head(title, sub=None):
    return f'<h2>{title}</h2>' + (f'<p class="sub">{sub}</p>' if sub else "")


S = []

# 1 ------------------------------------------------------------------ cover
S.append(slide(f"""<div style="margin-top:-.30in"></div>
<img src="data:image/png;base64,{b64(BRAND / 'FTM-H_wTAG_rgb.png')}" style="width:4.4in">
<h1 style="margin-top:1.05in">Counting alfalfa cuttings<br>from orbit</h1>
<div style="width:2.1in;height:5px;background:{ORANGE};margin:.10in 0 .22in"></div>
<p style="font-size:14pt;width:9.0in;line-height:1.45">One 62-acre field in
northwestern New Mexico, read from free satellite imagery. The pipeline was
built to find one planting and one harvest a year. This field is cut
<b>three to four times every summer</b> — and the imagery shows every one.</p>
<p style="font-size:10.5pt;color:{MUTED};margin-top:.40in">
Field to Market remote sensing demonstration &nbsp;·&nbsp; 713 clear
observations, January 2020 to September 2026 &nbsp;·&nbsp; analysis run 19
October 2026</p>""", logo=False))

# 2 ------------------------------------------------------------- the field
S.append(slide(head("One field, seven years",
                    "A single management unit: on average 100% of the boundary "
                    "is one crop, so the curves below belong to the whole field "
                    "and not to an average of two.") + f"""
<div class="cards">
  <div class="card"><div class="big">62</div>
    <div class="lab">acres (25.2 ha)<br>San Juan County, New Mexico</div></div>
  <div class="card"><div class="big">713</div>
    <div class="lab">cloud-free observations<br>Jan 2020 – Sep 2026</div></div>
  <div class="card"><div class="big">3 days</div>
    <div class="lab">typical gap between<br>clear images</div></div>
  <div class="card o"><div class="big" style="font-size:26pt">Wheat&nbsp;→&nbsp;Alfalfa</div>
    <div class="lab">winter wheat 2020–21,<br>alfalfa 2022 onward</div></div>
</div>
<div class="cols" style="margin-top:.10in">
 <div class="col">
  <p><b>The crop changed in 2022.</b> USDA's Cropland Data Layer records winter
  wheat in 2020 and 2021, then alfalfa from 2022 onward, at 99.6–100% purity
  every year. That rotation is what makes this field useful: it contains its
  own control.</p>
 </div>
 <div class="col">
  <p><b>Density is the whole story.</b> An image every three days is what makes
  a cutting visible at all. A crop that is mown and regrows inside five weeks
  is invisible to a sensor that passes monthly — the field would simply look
  green all summer.</p>
 </div>
</div>
<div class="note">Crop type from the USDA Cropland Data Layer (30&nbsp;m).
Greenness from Sentinel-2 surface reflectance (10&nbsp;m), cloud-masked.
Boundary supplied with the report pack; no field visit and no grower input.</div>"""))

# 3 ------------------------------------------------------------- location
S.append(slide(head("Where the field is",
                    "San Juan County, New Mexico — the irrigated valley "
                    "northwest of Farmington, at about 1,600 m.") +
               img("07_location.png", "max-height:3.62in;width:auto;"
                   "display:block;margin:.02in auto 0") + f"""
<div class="cols" style="margin-top:.06in">
 <div class="col"><p><b>It is a center pivot</b> — a 122-acre irrigated
 circle, wheel tracks and center point visible. That is why the water goes
 on so regularly, and why the cutting schedule is so steady.</p></div>
 <div class="col"><p><b>The orange box is drawn, not surveyed:</b> a hand-drawn
 rectangle covering <b>51% of the pivot</b>, well inside the circle. It never
 touches the dry corners, which is why the crop layer reads 100% one crop —
 and it means every number here describes half a pivot.</p></div>
</div>
<div class="note">Imagery: USDA National Agriculture Imagery Program, flown 25 May
2022 at 0.6 m, public domain. County outline from the US Census Bureau; the county
is the one whose polygon contains the field centroid. Pivot area measured from the
NAIP near-infrared band.</div>"""))

# 4 ------------------------------------------------------------- the hero
S.append(slide(head("What a cutting looks like from space") +
               img("01_sawtooth_2023.png", "max-height:5.3in;width:auto;display:block;margin:0 auto") +
               f"""<div class="note">A full alfalfa canopy reads about 0.93 on the
greenness index. Within days of mowing, the same field reads 0.32 — bare stubble and
windrows. Then it regrows and the pattern repeats. The two narrow spikes in August
and late September are cloud shadow, not cuttings, and are rejected: see "Telling a cutting from a cloud".</div>"""))

# 5 --------------------------------------------------------------- the count
rows = ""
for _, r in summ.iterrows():
    crop = r.crop if isinstance(r.crop, str) else "not yet published"
    n = int(r.cuttings)
    flag = (f' <span class="flag">({int(r.cuttings_flagged)} flagged)</span>'
            if r.cuttings_flagged else "")
    span = ("—" if n < 2 else
            f"{pd.to_datetime(r.first_cut).strftime('%d %b')} – "
            f"{pd.to_datetime(r.last_cut).strftime('%d %b')}")
    gap = "—" if pd.isna(r.mean_regrowth_days) else f"{r.mean_regrowth_days:.0f}"
    note = "part year, to 20 Sep" if r.year == 2026 else ""
    rows += (f'<tr><td><b>{r.year}</b></td><td>{crop}</td>'
             f'<td class="n">{n}{flag}</td><td class="n">{span}</td>'
             f'<td class="n">{gap}</td><td>{note}</td></tr>')
S.append(slide(head("Three to four cuttings a year, every year",
                    "Fifteen cuttings detected across five alfalfa seasons. "
                    "The two wheat years, read by the identical method, give "
                    "one biomass removal each — the grain harvest.") + f"""
<div class="cards">
  <div class="card o"><div class="big">3–4</div>
    <div class="lab">cuttings per complete<br>alfalfa season</div></div>
  <div class="card"><div class="big">43 days</div>
    <div class="lab">median between cuttings<br>(range 33 – 62)</div></div>
  <div class="card"><div class="big">4–15 Jun</div>
    <div class="lab">first cutting, all five years<br>an 11-day spread</div></div>
  <div class="card"><div class="big">0.93&nbsp;→&nbsp;0.48</div>
    <div class="lab">typical greenness<br>across a cutting</div></div>
</div>
<table><tr><th>Year</th><th>Crop (USDA)</th><th class="n">Cuttings</th>
<th class="n">First to last</th><th class="n">Mean gap (days)</th><th></th></tr>
{rows}</table>
<div class="note">"Flagged" marks a cutting detected after 1 October, when a hard
freeze would produce the same signature. It is counted and labeled, not hidden.</div>"""))

# 6 ------------------------------------------------------------- every year
S.append(slide(head("The same rhythm, year after year") +
               img("02_all_years.png", "width:11.9in;max-height:5.3in;display:block;margin:.05in auto 0") +
               """<div class="note">2026 is a part year, running to 20 September.
Dashed lines are the flagged late-season cuttings.</div>"""))

# 7 ---------------------------------------------------------- the calendar
S.append(slide(head("A cutting calendar, built without visiting the farm") +
               img("04_cutting_calendar.png", "max-height:4.25in;width:auto;display:block;margin:0 auto") + f"""
<div class="cols" style="margin-top:.04in">
 <div class="col"><p><b>The schedule is remarkably stable.</b> First cutting
 between 4 and 15 June in all five years, then roughly every six weeks until
 the stand goes dormant.</p></div>
 <div class="col"><p><b>2024 is the exception</b> — three cuttings, with
 48- and 52-day gaps where other years run 33 to 45. Something stretched the
 cycle that summer. The imagery shows that it happened; it cannot say why.</p></div>
</div>"""))

# 8 ------------------------------------------------------------ the control
S.append(slide(head("The method did not know which crop it was looking at",
                    "Same field, same algorithm, same constants. Only the crop "
                    "changed.") +
               img("03_wheat_vs_alfalfa.png", "max-height:4.65in;width:auto;display:block;margin:0 auto") + """
<div class="note">This is the closest thing to a control available without a grower
record: a field that grew an annual grain and then a perennial forage, read by one
unchanged method. One removal in the wheat years, four in the alfalfa year.</div>"""))

# 9 ------------------------------------------------------------- regrowth
S.append(slide(f"""{head("The biology is visible too")}
<div class="cols">
 <div class="col" style="flex:1.35 1 0">{img("05_regrowth.png", "width:100%")}</div>
 <div class="col" style="flex:1 1 0">
  <p class="kicker">What the curve says</p>
  <p><b>Fifteen days from stubble back to full canopy</b>, as a median across
  all fifteen cuttings. The regrowth curves sit almost on top of one another —
  this stand behaves the same way every time it is cut.</p>
  <p><b>Then it waits.</b> The median gap between cuttings is 43 days, but the
  canopy is full again by day 15. The remaining four weeks are the grower
  letting the stand build yield before mowing again.</p>
  <p><b>The one flat track</b> near 0.47 is a late-October cutting that never
  regrows, because the stand is going dormant.</p>
 </div>
</div>
<div class="note">"Full canopy" is a greenness of 0.80, the level this stand plateaus
at through the summer. Each track stops at the next cutting.</div>"""))

# 10 -------------------------------------------------------------- method
S.append(slide(head("Telling a cutting from a cloud",
                    "A fall in greenness is not enough on its own. Four tests, "
                    "each one added because a real case in this field's own "
                    "record defeated the rule before it.") + f"""
<table>
<tr><th style="width:1.5in">Test</th><th>What it requires</th>
<th style="width:5.1in">The case that put it there</th></tr>
<tr><td><b>Standing</b></td><td>Greenness above 0.60 before the fall</td>
<td>Dormant winter regrowth oscillates around 0.45 and is not a crop anyone cuts.</td></tr>
<tr><td><b>Step</b></td><td>A drop of 0.30 or more, measured from the last
standing observation, completed within 12 days</td>
<td>A mature stand sits near its peak for weeks before it is cut. Measuring from
the seasonal peak instead turned the 7-day first cutting of 2023 into a "27-day
senescence" and missed it entirely.</td></tr>
<tr><td><b>Persistent</b></td><td>The low holds across at least two clear
observations</td>
<td>On 12 August 2023 the field reads 0.49 between a 0.90 and a 0.93 five days
later. Alfalfa cannot regrow a canopy in five days — that is cloud shadow. Without
this test 2023 reads six cuttings instead of four.</td></tr>
<tr><td><b>Spaced</b></td><td>At least 18 days since the previous cutting</td>
<td>A stand needs about a month to regrow; two cuttings a fortnight apart would be
one event counted twice.</td></tr>
</table>
<div class="note">Cloud is judged on the share of <b>field</b> pixels that survived
masking, not the scene cloud percentage: five of the twenty detected falls sit under
scenes 14–34% clouded, and the field itself is clear in every one.</div>"""))

# 11 -------------------------------------------------- the annual-crop model
S.append(slide(head("What an annual-crop model makes of a perennial",
                    "This is the finding that matters for the people building "
                    "the production pipeline.") +
               img("06_pipeline_vs_cuttings.png", "max-height:5.0in;width:auto;display:block;margin:0 auto") + """
<div class="note">The pipeline reports one planting and one harvest per year. On this
field its "harvest" lands on the first cutting in 2023, the second in 2026, the third
in 2025, and on nothing at all in 2022 and 2024 — and the season it reports swings
from 63 to 264 days on an unchanging crop.</div>"""))

# 12 ------------------------------------------------ the off-season problem
S.append(slide(head("A perennial has no off-season, so two of our metrics "
                    "stop meaning anything") + f"""
<div class="cols">
 <div class="col">
  <p class="kicker">Cover crop</p>
  <p>Of the five winters from 2021–22 onward, the pipeline calls four a
  <b>likely cover crop</b> and the fifth a possible one. There is no cover
  crop. There is alfalfa, which was there in August and is still there in
  December.</p>
  <p>The clearest case is winter 2023–24, scored on an "off-season" greenness
  peak of <b>0.94 on 6 October</b>. That is not a cover crop establishing. It is
  the standing hay crop, five days before the fourth cutting.</p>
 </div>
 <div class="col">
  <p class="kicker">Soil armor before planting</p>
  <p>The pre-planting window runs from last year's harvest to this year's
  planting. On a perennial there is no planting, so in <b>2024 and 2026 the
  window collapses to nothing</b> and no figure is produced at all.</p>
  <p>Where a figure does appear it is not wrong so much as beside the point:
  March 2025 reads 0.97 covered, 96% of it classed as residue. That is a
  dormant alfalfa stand, not last year's crop residue.</p>
 </div>
</div>
<p class="quote" style="margin-top:.20in">Neither metric is broken. Both were
defined for a crop that is planted and harvested once a year, and this field
is not one.</p>"""))

# 13 ------------------------------------------------------------ caveats
S.append(slide(head("What this is not") + """
<ul style="font-size:13pt">
<li><b>No cutting record has ever been checked against this.</b> Not for this
field, not for any field. Every count on these slides is read from the shape of a
curve. The pattern is strong and the biology is consistent, but no accuracy figure
exists and none is quoted here.</li>
<li><b>Autumn is genuinely ambiguous.</b> Three of the fifteen cuttings fall after
1 October, when a hard freeze would take a canopy down the same way. They are
flagged throughout rather than quietly counted or quietly dropped.</li>
<li><b>Dates carry a window, not a day.</b> A cutting is placed between the last
clear image showing a standing crop and the first showing stubble — a median of
10 days apart. That window is set by cloud and revisit, not by the method.</li>
<li><b>The thresholds were tuned on this one field.</b> Four tests and seven
constants, read against this field's own 2023 season and then left alone across
the other six years. That is a demonstration, not a validated model.</li>
<li><b>One field is one field — and only half a pivot of it.</b> Everything here
is a drawn rectangle covering 51% of one center pivot in one irrigated valley. A
boundary taken out to the pivot edge would include the wetted margin and the dry
corners, and would not behave the same way.</li>
</ul>"""))

# 14 ---------------------------------------------------------- what's next
S.append(slide(head("Why it is worth doing properly") + f"""
<div class="cols">
 <div class="col">
  <p class="kicker">What this would unlock</p>
  <p><b>Forage is a blind spot.</b> Hay and alfalfa are poorly served by metrics
  built around a single annual harvest, and they are a large share of irrigated
  acreage in the West.</p>
  <p><b>Cutting count and timing are the management signal.</b> How many times a
  stand is cut, and how long it is allowed to recover, is most of what
  distinguishes one alfalfa operation from another.</p>
  <p><b>It needs no new data.</b> Every number here came from imagery the
  pipeline already downloads for every field it touches.</p>
 </div>
 <div class="col">
  <p class="kicker">What it would take to trust it</p>
  <p><b>One season of real cutting dates.</b> A grower's log for ten alfalfa
  fields over one summer would be enough to measure, for the first time,
  whether the count is right and how close the dates land.</p>
  <p><b>A perennial path through the pipeline.</b> Detect the crop as perennial
  from the Cropland Data Layer, then skip planting, harvest, cover crop and
  pre-planting armor, and report a cutting series instead.</p>
  <p><b>Fields outside this valley.</b> Rain-fed and shorter-season stands, to
  see whether constants fitted here travel at all.</p>
 </div>
</div>
<p class="quote" style="margin-top:.18in">The pipeline found something it was never
designed to look for. That is worth a validation season.</p>""" ))

html = (f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>New Mexico alfalfa cuttings</title><style>{CSS}</style></head>"
        f"<body>{''.join(S)}</body></html>")
OUT_HTML.write_text(html, encoding="utf-8")
print("slides:", len(S))

OUT_PDF.unlink(missing_ok=True)
subprocess.run([str(EDGE), "--headless=new", "--disable-gpu",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=20000",
                f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
               capture_output=True, timeout=240)

# Edge finishes writing after the launcher returns -- wait for the file to
# settle rather than checking once. See the same note in build_methods_pdf.py.
size = -1
for _ in range(60):
    if OUT_PDF.exists():
        now = OUT_PDF.stat().st_size
        if now > 0 and now == size:
            break
        size = now
    time.sleep(0.5)
else:
    print("Edge produced no PDF after 30 s")
    sys.exit(1)

if "--keep-html" not in sys.argv:
    OUT_HTML.unlink(missing_ok=True)
print("wrote %s  (%.0f KB)" % (OUT_PDF, OUT_PDF.stat().st_size / 1024))
