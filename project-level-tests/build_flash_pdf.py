#!/usr/bin/env python3
"""Build the Illinois (FLASH) case study as a slide-format PDF.

    python project-level-tests/build_flash_pdf.py [--keep-html]

HTML pages sized 13.333 x 7.5in, printed through headless Edge -- the same
mechanism pitch/build_methods_pdf.py uses. Field to Market branding.

Illinois only. The Georgia validation is referenced once, in the limitations,
and never mixed into a chart.
"""
import base64
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJ = HERE / "project-FLASH"
FIG = PROJ / "figures"
BRAND = REPO / "pitch" / "branding-assets"
OUT_HTML = PROJ / "_flash_slides.html"
OUT_PDF = PROJ / "Illinois-FLASH-Case-Study.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

BLUE, ORANGE = "#10427C", "#F46C09"
INK, GRAY, MUTED = "#212121", "#58595B", "#8a8c8e"
BAR = [("#10427C", 40), ("#F46C09", 40), ("#00B14C", 5), ("#0D9AC6", 5),
       ("#462668", 5), ("#FFD103", 5)]


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
.sub { font-size: 12.5pt; color: #58595B; margin: 0 0 .22in; line-height: 1.40; }
.note { position: absolute; left: .62in; right: .62in; bottom: .42in;
        font-size: 9.2pt; color: #8a8c8e; line-height: 1.38; }
.fig { display: block; margin: 0 auto; }
p, li { font-size: 12.5pt; line-height: 1.52; color: #58595B; }
b, strong { color: #212121; }
ul { margin: .04in 0 0; padding-left: .22in; }
li { margin-bottom: .07in; }
.cols { display: flex; gap: .34in; }
/* flex-basis 0, not auto: with auto the columns size to their text and the
   1.5:1 ratios asked for below are ignored, which shrank every chart. */
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
<h1 style="margin-top:1.15in">Illinois case study:<br>what the satellite saw</h1>
<div style="width:2.1in;height:5px;background:{ORANGE};margin:.10in 0 .22in"></div>
<p style="font-size:14pt;width:8.6in;line-height:1.45">98 fields enrolled in
<b>Farmer-Led Advances in Soil Health</b>, read from free satellite imagery and
compared against what was entered in Fieldprint.</p>
<p style="font-size:10.5pt;color:{MUTED};margin-top:.45in">
Fieldprint project 370 &nbsp;·&nbsp; winters 2022-23 to 2025-26 &nbsp;·&nbsp;
analysis run 11 October 2026</p>""", logo=False))

# 2 ------------------------------------------------------------ the cohort
S.append(slide(head("The cohort",
                    "195 Fieldprint payloads resolve to 98 distinct field boundaries.") + f"""
<div class="cards">
  <div class="card"><div class="big">98</div><div class="lab">distinct field boundaries</div></div>
  <div class="card"><div class="big">8,668</div><div class="lab">acres, median field 79</div></div>
  <div class="card"><div class="big">6</div><div class="lab">counties, all Illinois</div></div>
  <div class="card o"><div class="big">15,323</div><div class="lab">cloud-free observations read</div></div>
</div>
<div class="cols">
  <div class="col">
  <table>
  <tr><th>County</th><th class="n">fields</th></tr>
  <tr><td>Jo Daviess</td><td class="n">39</td></tr>
  <tr><td>Montgomery</td><td class="n">25</td></tr>
  <tr><td>Champaign</td><td class="n">12</td></tr>
  <tr><td>Livingston</td><td class="n">9</td></tr>
  <tr><td>Coles</td><td class="n">7</td></tr>
  <tr><td>Ford</td><td class="n">5</td></tr>
  </table></div>
  <div class="col">{img('01_field_size.png', 'width:100%')}</div>
</div>
<div class="note">The same physical field appears once per crop year under a different
Fieldprint id, so boundaries were deduplicated on geometry. Keying on the id would
have run the pipeline twice over identical ground and reported the two runs as
independent agreement.</div>"""))

# 3 ------------------------------------------------------------- what ran
S.append(slide(head("What was run",
                    "One boundary in; crop history, season dates and an off-season verdict out.") + f"""
<div class="cols">
 <div class="col">
  <ul>
  <li><b>Sentinel-2 L2A</b> surface reflectance, 10 m, cloud-masked with the
      scene classification layer.</li>
  <li><b>2022 to present</b> — four complete off-seasons: 2022-23, 2023-24,
      2024-25, 2025-26.</li>
  <li><b>USDA Cropland Data Layer</b> for crop type and for the check on whether
      a boundary holds one field or several.</li>
  <li><b>88.3 minutes</b> for all 98 fields, <b>zero failures</b>. Median 126
      clear observations per field.</li>
  </ul>
  <p style="margin-top:.16in"><b>Crops present</b> (CDL): corn on 97 fields,
  soybeans on 91, winter wheat on 4, with small areas of grass, pasture and
  alfalfa.</p>
 </div>
 <div class="col">{img('02_boundary_quality.png', 'width:100%')}
 <p style="font-size:10pt;margin-top:.10in">Boundary quality is checked before
 anything else, because every number downstream averages over whatever the
 outline contains.</p>
 </div>
</div>"""))

# 4 --------------------------------------------------------- season curve
S.append(slide(head("The growing season",
                    "What a corn and soybean rotation looks like from orbit.") + f"""
<div class="cols">
 <div class="col" style="flex:1.45">{img('03_season_curve.png', 'width:100%')}</div>
 <div class="col">
  <p>The cash crop is unmistakable: bare ground through April, canopy closing in
  June, senescence from late August.</p>
  <p>That part is easy, and it is not what this study is about. <b>The cover crop
  question lives in the flat stretch between November and April</b>, where the
  signal is small, the sky is cloudy and the difference between a sown cover and
  bare residue is a few hundredths of NDVI.</p>
  <p style="color:{ORANGE}"><b>Everything that follows concerns that off-season
  window.</b></p>
 </div>
</div>"""))

# 5 -------------------------------------------------------- what was entered
S.append(slide(head("What project staff entered",
                    "The Fieldprint payloads carry a cover crop record in exactly one winter.") + f"""
<table>
<tr><th>Winter</th><th class="n">fields with a cover crop recorded</th><th>What the payload contains</th></tr>
<tr><td>2020-21</td><td class="n">0</td><td>tillage, planting, fertilizer, harvest</td></tr>
<tr><td>2021-22</td><td class="n">0</td><td>tillage, planting, fertilizer, harvest</td></tr>
<tr><td>2022-23</td><td class="n">0</td><td>tillage, planting, fertilizer, harvest</td></tr>
<tr><td>2023-24</td><td class="n">0</td><td>tillage, planting, fertilizer, harvest</td></tr>
<tr><td>2024-25</td><td class="n">0</td><td>tillage, planting, fertilizer, harvest</td></tr>
<tr><td><b>2025-26</b></td><td class="n"><b>98 of 98</b></td><td><b>+ planting_cover, with sowing and termination dates</b></td></tr>
</table>
<p style="margin-top:.16in"><b>A <code>planting_cover</code> activity appears 98 times in the
entire archive</b> — once per field, all in the 2026 harvest-year interval. Every year
from 2008 to 2025 carries the other four activity types and no cover crop record at all.</p>
<div class="note">Read plainly: the historical intervals are rotation skeletons — the crop
history Fieldprint needs for its calculations — while only the current submission year
carries full practice detail. The earlier zeros are silence, not a statement that no
cover crop was grown.</div>"""))

# 6 ----------------------------------------------------- what that permits
S.append(slide(head("What that permits, and what it rules out") + f"""
<div class="cards">
 <div class="card"><div class="big">98</div><div class="lab">labelled positives<br>(winter 2025-26)</div></div>
 <div class="card o"><div class="big">0</div><div class="lab">labelled negatives<br>anywhere in the archive</div></div>
</div>
<div class="cols" style="margin-top:.10in">
 <div class="col">
 <h2 style="font-size:15pt">Measurable</h2>
 <p><b>Sensitivity.</b> Of 98 fields known to have been sown to a cover crop, how
 many does the satellite find?</p>
 </div>
 <div class="col">
 <h2 style="font-size:15pt;color:{ORANGE}">Not measurable</h2>
 <p><b>Specificity.</b> With no field known <i>not</i> to have a cover crop, there is
 no way to count false alarms. Lowering the detection threshold would look free
 on this data and is not.</p>
 </div>
</div>
<p style="margin-top:.10in">The three earlier winters are reported in this deck as
<b>what the detector claims</b>, never scored as right or wrong.</p>"""))

# 7 ------------------------------------------------------------ prevalence
S.append(slide(head("Cover prevalence the satellite reports",
                    "Four winters, same 98 fields, same thresholds.") + f"""
<div class="cols">
 <div class="col">{img('06_prevalence.png', 'width:100%')}</div>
 <div class="col">
  <p>The trend is monotonic and the rise is substantial — from under a third of
  fields showing off-season green in 2022-23 to roughly two thirds in 2025-26.</p>
  <p>That is the shape a cohort progressively adopting cover crops would
  produce, which is what a soil health project is designed to create.</p>
  <p><b>It is also the shape a drifting detector would produce</b>, and only the
  last winter carries a label. Nothing in this dataset separates the two.</p>
 </div>
</div>"""))

# 8 ------------------------------------------------------- the match, headline
S.append(slide(f"""<div class="kicker">The comparison you asked for</div>
<h2 style="font-size:28pt">Of 98 fields sown to a cover crop,<br>the satellite finds 63.</h2>
<div class="cards" style="margin-top:.22in">
 <div class="card"><div class="big">35.7%</div><div class="lab"><b>strict reading</b><br>"likely cover crop" only — 35 of 98</div></div>
 <div class="card"><div class="big">64.3%</div><div class="lab"><b>loose reading</b><br>any off-season green — 63 of 98</div></div>
 <div class="card o"><div class="big">35</div><div class="lab"><b>missed entirely</b><br>"no cover crop detected"</div></div>
</div>
<table style="margin-top:.14in">
<tr><th>Verdict, winter 2025-26</th><th class="n">fields</th></tr>
<tr><td>likely cover crop</td><td class="n">35</td></tr>
<tr><td>possible cover crop</td><td class="n">26</td></tr>
<tr><td>green cover — cover crop or small grain</td><td class="n">2</td></tr>
<tr><td>no cover crop detected</td><td class="n">35</td></tr>
</table>"""))

# 9 ------------------------------------------------------------ the misses
S.append(slide(head("The misses are not bare fields",
                    "Every missed field showed green. None of it reached the threshold.") + f"""
<div class="cols">
 <div class="col" style="flex:1.4">{img('05_peak_ndvi.png', 'width:100%')}</div>
 <div class="col">
  <p>All 35 misses fall between <b>NDVI 0.193 and 0.292</b>.</p>
  <p>Not one is below 0.15, which is what genuinely bare ground reads.
  <b>34 of the 35 sit in the band 0.20 to 0.30</b> — immediately under the line.</p>
  <p>The detector is not confusing a cover crop with bare soil. It is seeing a
  modest amount of green and declining to call it.</p>
 </div>
</div>"""))

# 10 --------------------------------------------------------- off-season curve
S.append(slide(head("The off-season, detected against missed",
                    "Both groups were sown. The separation is real but small.") + f"""
<div class="cols">
 <div class="col" style="flex:1.5">{img('04_offseason_curve.png', 'width:100%')}</div>
 <div class="col">
  <p>Both groups sit near 0.20 from November to March. The split opens in
  <b>April</b>, when the detected group climbs toward 0.39 and the missed group
  reaches about 0.27.</p>
  <p>At 42&deg; north a cover crop drilled in late October accumulates very
  little biomass before dormancy. <b>Almost the entire usable signal is
  compressed into four to six weeks in spring</b> — the window where Illinois
  cloud is heaviest.</p>
 </div>
</div>"""))

# 11 ------------------------------------------------- every field, one plot
S.append(slide(head("Every field, every clear date",
                    "Off-season 2025-26. One thin line per field, both group medians on top.") +
               img("11_all_fields_offseason.png", "width:12.1in") + """
<div class="note">The spread is the finding. Fields the detector called are not uniformly
green and fields it missed are not uniformly bare — the two groups overlap through most
of the winter and separate only in April, briefly. Markers on the thick lines show the
dates that carried at least twenty clear fields; between early December and early
February almost none did, so the medians bridge that stretch rather than describe it.</div>"""))

# 13 ---------------------------------------------------------------- examples
S.append(slide(head("Two fields, side by side",
                    "Both were sown in October 2025. Only one cleared the line.") +
               img("10_examples.png", "width:11.9in;margin-top:.04in") + """
<div class="note">Left: a clear spring rise that stays near or above 0.30 from March.
Right: a collapse to 0.12 by November, a flat winter near 0.18, and a rise that only
begins in May — reaching 0.34 at the very edge of the window, after the grower's
20 May termination date. NDVI sees green, not intent: neither panel can distinguish
a sown cover crop from volunteer regrowth.</div>"""))

# 12 --------------------------------------------------------- threshold
S.append(slide(head("What the threshold costs",
                    "The constant doing the work is CC_GREEN_MIN = 0.30.") + f"""
<div class="cols">
 <div class="col">{img('07_threshold.png', 'width:100%')}</div>
 <div class="col">
  <table>
  <tr><th>Threshold</th><th class="n">caught</th></tr>
  <tr><td>0.20</td><td class="n">99%</td></tr>
  <tr><td>0.25</td><td class="n">82%</td></tr>
  <tr><td><b>0.30 — shipped</b></td><td class="n"><b>64%</b></td></tr>
  <tr><td>0.35</td><td class="n">41%</td></tr>
  </table>
  <p style="margin-top:.14in;color:{ORANGE}"><b>This slide cannot be used to pick a
  threshold.</b> With no labelled negatives, lowering it appears costless here —
  and the cost is precisely the thing this dataset cannot see.</p>
 </div>
</div>"""))

# 14 ------------------------------------------------------- confounder: obs
S.append(slide(head("Thin winters hide cover crops",
                    "Detection tracks how many clear days the window contains.") + f"""
<div class="cols">
 <div class="col">{img('08_observations.png', 'width:100%')}</div>
 <div class="col">
  <p>Fields with ten or fewer clear observations are detected <b>35.7%</b> of the
  time. Fields with more than twenty are detected <b>88.5%</b> of the time — two
  and a half times the rate, on the same practice.</p>
  <p>The median winter here carries <b>15</b> clear observations and the thinnest
  carries <b>7</b>. Seventeen of the 53 dates in the window had fewer than twenty
  of the 98 fields clear at once.</p>
  <p><b>Some of the 35 misses are a cloud record, not a farming record.</b></p>
 </div>
</div>"""))

# 15 --------------------------------------------------- confounder: boundary
S.append(slide(head("Impure boundaries detect <i>more</i>",
                    "The opposite of what you would expect, and it matters.") + f"""
<div class="cols">
 <div class="col">{img('09_boundary_effect.png', 'width:100%')}</div>
 <div class="col">
  <p>Boundaries the CDL check flags as holding more than one management unit are
  detected at <b>83%</b>. Clean single-unit boundaries are detected at
  <b>56%</b>.</p>
  <p>A boundary spilling into a grassed waterway, a field margin or a neighbour's
  ground collects winter green that does not belong to the field, and the average
  rises above the threshold.</p>
  <p><b>29 of these 98 boundaries are not a single management unit.</b> On this
  cohort that inflates apparent adoption rather than degrading it.</p>
 </div>
</div>"""))

# 16 --------------------------------------------------- armor: what it is
S.append(slide(head("Soil armor: a second, independent measurement",
                    "Different bands, different physics, same imagery.") + f"""
<div class="cols">
 <div class="col">
  <p>Everything so far came from <b>NDVI</b> — greenness in the visible and
  near-infrared. Soil armor comes from the <b>shortwave infrared</b>, where
  cellulose and lignin absorb, and decomposes every pixel into three fractions
  that sum to one:</p>
  <ul>
  <li><b>living cover</b> — green canopy</li>
  <li><b>crop residue</b> — stubble, litter, a terminated cover crop</li>
  <li><b>bare soil</b></li>
  </ul>
  <p style="margin-top:.12in"><b>Soil armor is one minus the bare fraction</b> —
  the share of the surface protected by anything at all.</p>
 </div>
 <div class="col">
  <div class="card o">
   <div class="lab" style="font-size:12pt;color:{ORANGE}"><b>It is not a tillage metric</b></div>
   <p style="font-size:12pt">The name invites that reading and the reading is
   wrong. Checked against 347 farmer-reported field-years, armor's apparent
   tillage signal ran almost entirely through <b>cover crop adoption</b>
   instead.</p>
   <p style="font-size:12pt">Report it as ground cover. A field under a living
   cover crop and a field under heavy stubble are both protected, and armor
   counts both.</p>
  </div>
  <p style="margin-top:.14in;font-size:11pt">Method: NDVI–DFI ternary unmixing,
  after Guerschman et al. (2009) and Wang et al. (2019). The endmembers were
  fitted on eleven fields elsewhere and are <b>provisional</b>.</p>
 </div>
</div>"""))

# 21 ------------------------------------------------- armor: readability
S.append(slide(head("Armor cannot always be read here",
                    "It needs clear days in a narrow pre-planting window, and northern Illinois does not always supply them.") + f"""
<div class="cols">
 <div class="col">{img('12_armor_readable.png')}</div>
 <div class="col">
  <p><b>408 of 490 field-years</b> produced a reading — 83%.</p>
  <p>The failures are almost entirely too few clear dates: 72 of the 82 gaps
  are windows with <b>one or two usable observations</b>, below the minimum of
  three.</p>
  <p>2022 is the worst year at <b>59%</b> readable, with a median of three
  observations per window. 2025 is the best at 98%.</p>
  <p style="color:{ORANGE}"><b>This is the same cloud problem that suppresses
  cover crop detection</b>, now hitting a second metric — and the armor window
  is narrower, so it bites harder.</p>
 </div>
</div>"""))

# 22 ----------------------------------------- armor: against the verdict
S.append(slide(head("The two measurements agree with each other",
                    "Spring 2026 ground cover against what NDVI concluded about the winter before it.") + f"""
<div class="cols">
 <div class="col">{img('13_armor_vs_verdict.png')}</div>
 <div class="col">
  <table>
  <tr><th>Spring 2026</th><th class="n">armor</th><th class="n">n</th></tr>
  <tr><td>detector said cover crop</td><td class="n"><b>0.615</b></td><td class="n">56</td></tr>
  <tr><td>detector said none</td><td class="n">0.514</td><td class="n">25</td></tr>
  </table>
  <p style="margin-top:.14in">A gap of <b>0.101</b>, with <b>AUC 0.83</b>
  (p &lt; 0.001). Fields NDVI called cover-cropped carry measurably more ground
  cover into spring.</p>
  <p style="color:{ORANGE}"><b>This is consistency, not accuracy.</b> Both
  numbers come from the same satellite over the same field, and a weedy field
  looks green to one and covered to the other. Agreement rules out a coding
  error; it cannot rule out a shared confounder.</p>
 </div>
</div>"""))

# 23 ------------------------------------------------- armor: the mechanism
S.append(slide(head("And they agree for the right reason",
                    "The separation sits in living cover, not in residue.") +
               img("14_armor_fractions.png", "width:9.6in") + f"""
<div class="cols" style="margin-top:.10in">
 <div class="col">
  <p><b>Residue is identical</b> between the two groups — 0.49 against 0.48.
  <b>Living cover is four times higher</b> on the fields NDVI called:
  0.11 against 0.03.</p>
 </div>
 <div class="col">
  <p>That is the Georgia finding reproduced independently, in a different
  region, by a different measurement: <b>what armor separates is cover crops,
  not tillage.</b></p>
 </div>
</div>
<div class="note">Living cover is low in both groups because the window closes three days
before planting and terminations ran to 20 May — by then much of a terminated cover crop
has already become residue, where armor still counts it.</div>"""))

# 24 ------------------------------------------------------------ assessment
S.append(slide(f"""<div class="kicker">Assessment</div>
<h2 style="font-size:26pt">Does the data entry match what the satellite sees?</h2>
<p class="sub" style="margin-bottom:.14in">Three separate answers, because the question
has three parts.</p>
<table>
<tr><th style="width:26%">Question</th><th style="width:20%">Answer</th><th>Basis</th></tr>
<tr><td><b>Does the entered practice match the imagery?</b></td>
    <td><b>Partly — 64%</b></td>
    <td>63 of 98 fields show off-season green consistent with the recorded cover crop; 35 do not.</td></tr>
<tr><td><b>Is the entry trustworthy where it exists?</b></td>
    <td><b>Yes, and specific</b></td>
    <td>Sowing and termination dates are present on all 98 and are agronomically plausible for Illinois.</td></tr>
<tr><td><b>Is the entry complete?</b></td>
    <td style="color:{ORANGE}"><b>No</b></td>
    <td>Eighteen crop years carry no cover crop field at all. The project cannot show change over time from this export.</td></tr>
</table>
<p style="margin-top:.18in">The disagreement is <b>not</b> evidence that growers
misreported. It is the expected result of comparing <b>an action</b> — sown on this
date, terminated on that one — against <b>a biomass measurement</b> taken through
cloud at 42&deg; north.</p>"""))

# 17 ----------------------------------------------------- failure or finding
S.append(slide(head("Is 36% a detector failure, or a finding?",
                    "Both readings survive this data. They have different consequences.") + f"""
<div class="cols">
 <div class="col">
  <div class="card">
   <div class="lab" style="font-size:11pt;color:{BLUE}"><b>Reading A — the threshold is wrong here</b></div>
   <p style="font-size:11pt">0.30 came from Mid-Atlantic work and was reused in the
   eastern Corn Belt. Northern Illinois has a shorter autumn window and heavier
   winter cloud. A regional threshold near 0.25 would recover 18 of the 35 misses.</p>
   <p style="font-size:11pt"><b>If true:</b> recalibration fixes it, and the
   project's reported adoption is roughly right.</p>
  </div>
 </div>
 <div class="col">
  <div class="card o">
   <div class="lab" style="font-size:11pt;color:{ORANGE}"><b>Reading B — the stands did not establish</b></div>
   <p style="font-size:11pt">A cover crop drilled on 19 October at this latitude may
   carry almost no biomass before dormancy. The grower reports an action; the
   satellite reports what grew.</p>
   <p style="font-size:11pt"><b>If true:</b> the satellite is measuring cover crop
   <i>performance</i>, which is the more valuable number — and 35 fields got less
   benefit than the acreage implies.</p>
  </div>
 </div>
</div>
<p style="margin-top:.16in;text-align:center"><b>Only agronomic ground truth separates
them: biomass cuts or percent-groundcover transects on a sample of these same fields,
in the same spring.</b></p>"""))

# 18 ----------------------------------------------------------- limitations
S.append(slide(head("What this study cannot tell you") + """
<ul style="font-size:12pt">
<li><b>Nothing about false alarms.</b> No field in this project is known to be
without a cover crop, so specificity is unmeasured. Against a Georgia dataset that
did carry negatives, the same detector reached 7.1% specificity — the opposite
failure, and the reason the threshold should not simply be lowered.</li>
<li><b>Nothing about adoption before 2025.</b> The payload history has no cover crop
records, so the rising trend on slide 7 cannot be verified against anything.</li>
<li><b>Nothing about species, biomass or termination quality.</b> NDVI sees green.
It does not see what was planted, how much of it grew, or whether it was terminated
on time.</li>
<li><b>Nothing validated about planting and harvest dates.</b> Those estimates have
never been checked against a grower record in any region, including this one.</li>
<li><b>The soil armor metric was not run here.</b> It is a cover measurement rather
than a tillage measurement and needs its own window and a second pass over the
archive.</li>
</ul>"""))

# 19 -------------------------------------------------------------- next
S.append(slide(head("What would make the next run decisive") + f"""
<div class="cards">
 <div class="card"><div class="big">1</div><div class="lab"><b>Enter cover crops for prior years</b><br>
 Even two retrospective winters per field would turn a one-sided test into a real one.</div></div>
 <div class="card"><div class="big">2</div><div class="lab"><b>Identify fields with no cover crop</b><br>
 Twenty confirmed negatives would measure the false alarm rate that this project cannot.</div></div>
 <div class="card o"><div class="big">3</div><div class="lab"><b>Spring biomass on a subsample</b><br>
 Twenty fields, one visit, settles whether 36% is a threshold problem or a performance finding.</div></div>
</div>
<div class="cols" style="margin-top:.18in">
 <div class="col">
  <p><b>Cheapest first.</b> Items 1 and 2 are data entry, not fieldwork, and together
  they would let the next run report an accuracy figure instead of a sensitivity
  figure.</p>
 </div>
 <div class="col">
  <p><b>Also worth fixing:</b> 29 of 98 boundaries hold more than one management unit.
  Redrawing those is free, improves every number in this deck, and removes the
  inflation shown on slide 14.</p>
 </div>
</div>"""))

# 20 ---------------------------------------------------------------- close
S.append(slide(f"""<div class="kicker">In one page</div>
<div class="quote" style="margin-bottom:.26in">98 Illinois fields, all sown to a cover
crop in autumn 2025. The satellite finds 63 of them.</div>
<div class="cols">
 <div class="col">
  <p><b>The 35 it misses are not bare.</b> Every one shows green between NDVI 0.19
  and 0.29 — under a threshold borrowed from a milder region.</p>
  <p><b>Winter cloud explains part of it.</b> Fields with more than twenty clear
  days are detected two and a half times more often than fields with ten or fewer.</p>
 </div>
 <div class="col">
  <p><b>The project's data entry is accurate where it exists and absent everywhere
  else.</b> One winter of 98 positives, no negatives, eighteen blank years.</p>
  <p><b>The pipeline itself held up.</b> 98 fields, 88 minutes, no failures, on
  boundaries it had never seen.</p>
 </div>
</div>
<p style="margin-top:.22in;font-size:13pt;color:{BLUE}"><b>The honest headline is not
an accuracy number. It is that a national threshold cannot serve northern Illinois and
the Deep South at the same time, and this project is now the northern half of the
evidence.</b></p>"""))

html = (f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Illinois FLASH case study</title><style>{CSS}</style></head>"
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
