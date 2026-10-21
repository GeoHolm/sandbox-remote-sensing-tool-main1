#!/usr/bin/env python3
"""Hyper-local benchmarks: the member-facing case, as a slide PDF.

    python project-level-tests/build_benchmark_pdf.py [--keep-html]

Twenty slides. Same mechanism and branding as build_flash_pdf.py and
build_alfalfa_pdf.py: HTML pages at 13.333 x 7.5in printed through headless
Edge.

Framing: members tell us national and state comparisons are not valid for
their farm. This deck says they are right, puts a number on how wrong those
comparisons are, and shows that a local alternative already runs.

Every figure comes from _across/ or one of the three county directories.
No accuracy figure appears anywhere, because none has been measured.
"""
import base64
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ACROSS = HERE / "_across" / "deck"   # title-free: the slide supplies the heading
BRAND = REPO / "pitch" / "branding-assets"
OUT_HTML = HERE / "_benchmark_slides.html"
OUT_PDF = HERE / "Hyper-Local-Benchmarks.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

BLUE, ORANGE = "#10427C", "#F46C09"
INK, GRAY, MUTED = "#212121", "#58595B", "#8a8c8e"
BAR = [("#10427C", 40), ("#F46C09", 40), ("#00B14C", 5), ("#0D9AC6", 5),
       ("#462668", 5), ("#FFD103", 5)]


def b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()


def img(path, style=""):
    return f'<img src="data:image/png;base64,{b64(path)}" style="{style}">'


def across(name, style=""):
    return img(ACROSS / name, style)


def county(d, name, style=""):
    return img(HERE / d / "figures" / "deck" / name, style)


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
p, li { font-size: 12.5pt; line-height: 1.52; color: #58595B; }
b, strong { color: #212121; }
ul { margin: .04in 0 0; padding-left: .22in; }
li { margin-bottom: .09in; }
.cols { display: flex; gap: .34in; }
.col { flex: 1 1 0; min-width: 0; }
.col img { width: 100%; height: auto; }
.cards { display: flex; gap: .20in; margin: .10in 0 .18in; align-items: stretch; }
.card { flex: 1; border: 1.5px solid #10427C; border-radius: 9px; padding: .17in .19in; }
.card.o { border-color: #F46C09; }
.card .big { font-family: "Arial Narrow", Arial, sans-serif; font-size: 34pt;
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
.member { border-left: 4px solid #10427C; padding-left: .20in; font-size: 16pt;
          color: #212121; line-height: 1.44; font-style: italic; }
.logo { position: absolute; right: .62in; top: .42in; width: 2.0in; }
.hl { color: #F46C09; font-weight: 700; }
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
<h1 style="margin-top:1.00in">Benchmarks a grower<br>will actually accept</h1>
<div style="width:2.1in;height:5px;background:{ORANGE};margin:.10in 0 .22in"></div>
<p style="font-size:14pt;width:9.2in;line-height:1.45">Members tell us a
national or state comparison does not describe their farm. They are right —
and we can measure how wrong it is. A working alternative, built from free
satellite imagery, that compares a field with <b>its own neighbors</b>.</p>
<p style="font-size:10.5pt;color:{MUTED};margin-top:.40in">
Field to Market remote sensing demonstration &nbsp;·&nbsp; 203 fields across
three counties and three rotations &nbsp;·&nbsp; 20 October 2026</p>""",
               logo=False))

# 2 ------------------------------------------------------------ the problem
S.append(slide(head("The complaint we keep hearing") + f"""
<p class="member" style="margin:.10in 0 .26in">The objection, as it reaches us:
a national or state average pools farms with different soils, different
weather and different crops — so being told you are below it says very
little about how a field is managed.</p>
<div class="cols">
 <div class="col">
  <p><b>It is not a complaint about the metric.</b> It is a complaint about
  the comparison group — and on the evidence here, it is correct.</p>
  <p>We tested it on soil cover across three counties with three different
  rotations: corn and soybeans in Illinois, winter wheat and double crop in
  Kansas, peanuts and cotton in Georgia.</p>
 </div>
 <div class="col">
  <p class="kicker">What we found</p>
  <p><b>72% of the variation in soil cover sits between counties</b>, not
  between neighboring farms. A benchmark that pools them is mostly measuring
  <i>where</i> a grower farms, not <i>how</i>.</p>
 </div>
</div>
<div class="note">Variance decomposition over 203 field means, pre-planting soil
armor. The same figure is 66% for annual residue cover and 37% for the annual
worst-case.</div>"""))

# 3 ------------------------------------------------------- pooled grades county
S.append(slide(head("A pooled benchmark grades the county, not the farmer") +
               across("C_pooled_vs_local.png",
                      "max-height:4.55in;width:auto;display:block;margin:0 auto") + """
<div class="note">Every field in three counties. The dashed line is the median of
all 203 — a stand-in for a national figure. <b>Every single Champaign County field
falls below it on pre-plant armor</b>, as do 82% of Mitchell's, while 91% of Sumner's
sit above. None of that is management.</div>"""))

# 4 ----------------------------------------------------- same field two marks
S.append(slide(f"""{head("The same field, two benchmarks, two verdicts")}
<div class="cols">
 <div class="col" style="flex:1.45 1 0">
  {across("D_same_field_two_benchmarks.png", "width:100%")}
 </div>
 <div class="col" style="flex:1 1 0">
  <p class="kicker">What moves</p>
  <p>Our Illinois field sits in the <b>top fifth of its own neighborhood</b> on
  every measure. Pooled with Kansas and Georgia it reads
  <span class="hl">below average</span>.</p>
  <p>The Kansas field is the mirror image: <b>8th percentile locally</b>,
  about average once pooled.</p>
  <p>Nothing about either field changed. Only the comparison group did.</p>
  <p style="margin-top:.16in"><b>This is the member complaint, measured.</b></p>
 </div>
</div>
<div class="note">Three scores per field. "Local" is the field's own 50 to 100
qualifying neighbors; "pooled" is all 203 fields across the three counties.</div>"""))

# 5 ------------------------------------------------------------- the proposal
S.append(slide(head("The proposal: benchmark a field against its neighbors",
                    "Same weather. Same soils. Same markets. Same season. "
                    "The comparison a grower would make themselves.") + f"""
<div class="cards">
  <div class="card o"><div class="big">50–100</div>
    <div class="lab">qualifying cropland fields<br>around the member's field</div></div>
  <div class="card"><div class="big">2.5–4.3 km</div>
    <div class="lab">the radius that takes<br>to reach them</div></div>
  <div class="card"><div class="big">0</div>
    <div class="lab">new data from the grower<br>or from the neighbors</div></div>
  <div class="card"><div class="big">~2 min</div>
    <div class="lab">of compute per field,<br>once, per year</div></div>
</div>
<div class="cols" style="margin-top:.08in">
 <div class="col"><p><b>The neighbors never have to enroll.</b> Their boundaries
 come from public USDA data and their cover is read from free satellite imagery.
 No neighbor is identified, contacted, or asked for anything.</p></div>
 <div class="col"><p><b>The member's field is the only one named.</b> Everything
 else is an anonymous distribution — which is also what makes it safe to show a
 grower where they sit.</p></div>
</div>
<div class="note">Boundaries: USDA FSA Common Land Unit, 2008 public release, which
carries geometry and acreage only — every identifying attribute was stripped before
release.</div>"""))

# 6 ---------------------------------------------------------- how chosen
S.append(slide(head("What counts as a neighbor",
                    "A benchmark is only as good as its comparison group, so "
                    "the filters are deliberate and stated.") + """
<table>
<tr><th style="width:2.0in">Filter</th><th>Why</th><th class="n" style="width:3.1in">Effect in Sumner County</th></tr>
<tr><td><b>40–400 acres</b></td><td>Below 40 the satellite sample thins and edge
pixels dominate; above 400 a single CLU unit is usually rangeland</td>
<td class="n">25,576 &rarr; 4,840</td></tr>
<tr><td><b>Compact shape</b></td><td>Grass waterways, terraces and road verges are
all separate units in the CLU, and all are long and thin</td>
<td class="n">included above</td></tr>
<tr><td><b>Cropland, 3 of 4 years</b></td><td>Dominant USDA crop class at 60%+
purity. Doubles as a staleness check on an 18-year-old boundary</td>
<td class="n">4,840 &rarr; <b>3,610</b></td></tr>
<tr><td><b>No perennials</b></td><td>An orchard has a permanent canopy and an
alfalfa stand is green for years — both score high cover for reasons unrelated to
the management being compared</td>
<td class="n">removes pecan groves,<br>hay and orchards</td></tr>
</table>
<p style="margin-top:.18in"><b>Then the radius grows until it holds enough of
them.</b> A dense county needs 2.5 km; a sparser one needs 3.9.</p>
<div class="note">Mitchell County put four pecan groves into a cohort of fifty before
the perennial filter existed. Filters like this are the difference between a
comparison and a coincidence.</div>"""))

# 7 ------------------------------------------------------- rotation matching
S.append(slide(head("One step further: compare like with like",
                    "A neighbor growing a different rotation is still the "
                    "wrong comparison. Matching on crop sequence is the "
                    "single largest improvement available.") +
               across("F_rotation_match.png",
                      "max-height:3.65in;width:auto;display:block;margin:0 auto") + """
<div class="cols" style="margin-top:.08in">
 <div class="col"><p><b>Crop sequence explains more of the spread inside a
 county than county explains between them.</b> Match this year and last and it
 accounts for 78% of the variation in pre-plant cover — so an unmatched local
 benchmark is still partly ranking rotations.</p></div>
 <div class="col"><p><b>But the matched cohort only survives where rotations
 repeat.</b> In Champaign, every corn field followed soybeans, so matching is
 free. In Kansas and Georgia, requiring two years leaves six or seven
 neighbors — too few to rank anyone against.</p></div>
</div>
<div class="note">Recommendation: match on this year's crop always, add last
year's where enough neighbors survive, and widen the radius rather than loosen
the match. Never require three years — in Georgia that never reaches ten peers
at any distance still worth calling local.</div>"""))

# 8 ------------------------------------------------------------ Champaign map
S.append(slide(head("Champaign County, Illinois",
                    "Corn and soybeans. 50 neighbors inside 2.5 km.") +
               county("champaign-il", "01_cohort_map.png",
                      "max-height:4.65in;width:auto;display:block;margin:0 auto") + """
<div class="note">The dashed circle is the radius needed to reach 50 qualifying
fields. Fields inside it that are not outlined failed a filter — the cohort is a
screened subset of the neighborhood, not everything in it.</div>"""))

# 8 -------------------------------------------------------------- Sumner map
S.append(slide(head("Sumner County, Kansas",
                    "Winter wheat, wheat/soybean double crop, milo and "
                    "cotton. 100 neighbors inside 4.3 km.") +
               county("sumner-ks", "01_cohort_map.png",
                      "max-height:4.65in;width:auto;display:block;margin:0 auto") + """
<div class="note">A wider radius, because the qualifying fields are spread more
thinly here. The dark wooded band running southwest is a riparian corridor —
several cohort fields wrap around it, which is why their shapes are irregular.
This is the 100-field cohort; the other two counties use 50.</div>"""))

# 9 ------------------------------------------------------------ Mitchell map
S.append(slide(head("Mitchell County, Georgia",
                    "Peanuts and cotton, almost entirely center pivot. "
                    "50 neighbors inside 3.9 km.") +
               county("mitchell-ga", "01_cohort_map.png",
                      "max-height:4.65in;width:auto;display:block;margin:0 auto") + """
<div class="note">A different farming system in every respect — and the method did
not change between this slide and the last one.</div>"""))

# 9 --------------------------------------------------------------- it runs
S.append(slide(head("This is not a concept. It ran.") + f"""
<div class="cards">
  <div class="card"><div class="big">203</div>
    <div class="lab">fields benchmarked<br>across three counties</div></div>
  <div class="card"><div class="big">1,015</div>
    <div class="lab">field-years<br>2022 to 2026</div></div>
  <div class="card o"><div class="big">0</div>
    <div class="lab">failures<br>in 493 minutes</div></div>
  <div class="card"><div class="big">$0</div>
    <div class="lab">in data cost: Sentinel-2,<br>USDA CDL and CLU</div></div>
</div>
<div class="cols" style="margin-top:.10in">
 <div class="col">
  <p><b>Three rotations, one unchanged method.</b> Corn/soy, winter wheat with
  double crop, and peanut/cotton under pivot. No per-county tuning.</p>
 </div>
 <div class="col">
  <p><b>It uses imagery we already download.</b> Every number here came from a
  pass the pipeline makes anyway for any field it is given.</p>
 </div>
</div>
<div class="note">Run on one laptop. Per-field cost ranged from 1.5 minutes in
Illinois to 2.7 in Georgia, where cloud forces more scenes to be read.</div>"""))

# 10 ------------------------------------------------------- what it measures
S.append(slide(head("What it measures: how covered the ground is",
                    "Soil armor is the share of ground covered by anything at "
                    "all — living plants or crop residue.") + f"""
<div class="cols">
 <div class="col">
  <p>Every pixel is split into three parts that add to one: <b>living green
  cover</b>, <b>crop residue</b>, and <b>bare soil</b>. Armor is one minus the
  bare fraction.</p>
  <p>It is a <b>cover</b> metric, not a tillage metric. Checked against 347
  farmer-reported field-years, almost all of its apparent tillage signal ran
  through cover crop adoption instead.</p>
 </div>
 <div class="col">
  <p class="kicker">Why cover is the right thing to benchmark locally</p>
  <p>It responds to management within a season, it does not need a yield
  figure or an input record, and <b>it can be read for a neighbor who has
  never enrolled</b> — which is what makes a local comparison group possible
  at all.</p>
 </div>
</div>
<p class="quote" style="margin-top:.18in">The constants behind it were fitted on
eleven fields. Everything in this deck is provisional in that specific way.</p>"""))

# 12 -------------------------------------------- the window, and the fix
S.append(slide(head("One thing needed fixing first",
                    "The shipped figure covers only the weeks before "
                    "planting. In a cloudy spring that window is nearly "
                    "empty — so we now score the whole calendar year too.") +
               across("B_coverage_independence.png",
                      "max-height:3.95in;width:auto;display:block;margin:0 auto") + f"""
<div class="cols" style="margin-top:.06in">
 <div class="col"><p><b>Illinois gets a pre-plant reading for only 74% of
 field-years</b>, and where it does, the median field-year rests on
 <span class="hl">three clear images</span>. Kansas gets 98% off a median of
 eleven.</p></div>
 <div class="col"><p><b>Annual residue cover</b> excludes a living crop by
 construction, so it compares a wheat field with a cotton field fairly.
 <b>The worst 10% of the year</b> asks how bare the field got, not how bare on
 average. Both cover 100% of field-years.</p></div>
</div>
<div class="note">Both now ship in the Python pipeline as annual_residue and
annual_worst, read from imagery the pipeline already downloads.</div>"""))

# 13 --------------------------------------------------- what a member sees
S.append(slide(head("What a member would actually see",
                    "Their field, ranked against the anonymous distribution of "
                    "its own neighbors.") +
               county("sumner-ks", "04_cover_ranked.png",
                      "max-height:4.5in;width:auto;display:block;margin:0 auto") + """
<div class="note">One bar per field, the member's in orange. No neighbor is named
and no neighbor had to enroll. This is the Kansas field, which sits in the bottom
sixth of its neighborhood for off-season cover.</div>"""))

# 14 ---------------------------------------------------- three focus fields
S.append(slide(f"""{head("Three fields, three honest answers")}
<div class="cols">
 <div class="col" style="flex:1.4 1 0">
  {across("E_focus_by_county.png", "width:100%")}
 </div>
 <div class="col" style="flex:1 1 0">
  <p class="kicker">Read locally</p>
  <p><b>Illinois</b> — well covered by local standards on all three measures.
  A grower who would have been told they were below the national line.</p>
  <p><b>Kansas</b> — genuinely below its neighborhood, and the scores agree
  on that.</p>
  <p><b>Georgia</b> — the window score says middling, annual residue says
  bottom tenth. <b>The largest disagreement we found</b>, and a reminder that
  which score we publish is a decision, not a detail.</p>
 </div>
</div>
<div class="note">Percentile among each field's own cohort. Higher is better
covered.</div>"""))

# 16 ------------------------------- cover crop warning, with our ground truth
S.append(slide(head("Do not ship the cover crop verdict yet",
                    "One threshold, three counties — and we already measured "
                    "that the Georgia end is wrong.") +
               across("A_cover_by_county.png",
                      "max-height:3.55in;width:auto;display:block;margin:0 auto") + """
<div class="cols" style="margin-top:.08in">
 <div class="col"><p><b>6% of Illinois winters score as off-season green, 61%
 of Kansas, 88% of Georgia</b> — because the underlying distributions sit in
 different places. One number cannot be right in all three.</p></div>
 <div class="col"><p><b>Mitchell County is the second-largest site in our own
 Georgia ground-truth cohort</b>, 28 farmer-reported field-years, where this
 threshold scored <span class="hl">144 false positives against 11 true
 negatives</span>. "100% of Mitchell fields show a cover crop" is that
 false-positive rate, reproduced on new fields.</p></div>
</div>
<div class="note">The benchmark machinery is sound. The cover crop threshold
behind one of its inputs is not, and we measured that ourselves before this deck
existed.</div>"""))

# 17 --------------------------------------------------------- rank not verdict
S.append(slide(head("So rank, do not judge",
                    "The fix is to stop asking a yes/no question that depends "
                    "on a threshold we cannot set nationally.") + """
<div class="cols">
 <div class="col">
  <p class="kicker">Instead of</p>
  <p style="font-size:14pt">"Your field did <b>not</b> have a cover crop."</p>
  <p>A verdict that flips on four thousandths of an index. The Kansas field's
  two winters peaked at 0.296 and 0.277 against a 0.30 line.</p>
 </div>
 <div class="col">
  <p class="kicker">Say</p>
  <p style="font-size:14pt">"Your off-season cover was in the <b>lowest sixth</b>
  of 100 fields within three miles."</p>
  <p>No threshold, no national constant, and the ranking held when we removed
  the threshold entirely.</p>
 </div>
</div>
<p class="quote" style="margin-top:.20in">A ranking against real neighbors is both
more defensible and more useful than a verdict against a national constant — and
it is the thing members have been asking for.</p>"""))

# 18 --------------------------------------------------------- to ship it
S.append(slide(head("What it would take to offer this") + """
<table>
<tr><th style="width:2.5in">Step</th><th>What is involved</th><th class="n" style="width:1.6in">Size</th></tr>
<tr><td><b>Field boundaries</b></td><td>The 2008 public CLU is eighteen years
stale. Current CLU is restricted, but Field to Market may qualify for access —
worth a conversation with FSA before anything is built. Commercial boundary sets
are the fallback</td><td class="n">a phone call,<br>then a decision</td></tr>
<tr><td><b>A cohort service</b></td><td>Given a member field, select neighbors,
run the pass, return percentiles. Everything here already exists as scripts</td>
<td class="n">weeks</td></tr>
<tr><td><b>Regional thresholds<br>or none at all</b></td><td>Publish rankings on
the continuous measures. Keep cover crop verdicts out of the member view until
they are regionally calibrated</td><td class="n">a policy decision</td></tr>
<tr><td><b>A validation season</b></td><td>Grower-reported cover and residue for
a few dozen fields, to check the ranking against what was actually done</td>
<td class="n">one season</td></tr>
</table>
<div class="note">The compute is not the constraint: 203 fields ran on a laptop in
eight hours, and a member's cohort is a few minutes of that.</div>"""))

# 19 ----------------------------------------------------------- what it is not
S.append(slide(head("What this is not") + """
<ul style="font-size:13pt">
<li><b>Not validated.</b> No grower record has been checked against any of this,
in any of the three counties. Every criterion we used to choose between scores
measures behavior — crop neutrality, independence, stability, coverage — not
accuracy.</li>
<li><b>Not a judgment of any individual field.</b> Three counties of internal
consistency is not evidence that a given grower is doing well or badly.</li>
<li><b>Not current boundaries.</b> 2008 CLU, with a purity filter that removes
the worst drift and cannot fix a field split along a line the crop layer still
reads as uniform.</li>
<li><b>Not a national result.</b> Three counties. No irrigated West, no Delta,
no Northern Plains, no specialty crops.</li>
<li><b>Not a tillage metric.</b> Soil armor measures cover from any source. We
have measured that its apparent tillage signal runs through cover cropping.</li>
</ul>"""))

# 20 ------------------------------------------------------------- the ask
S.append(slide(head("What we are asking for") + f"""
<div class="cols">
 <div class="col">
  <p class="kicker">The finding</p>
  <p><b>Members are right about the benchmark.</b> Nearly three quarters of the
  variation in soil cover is between counties. Pooling them tells an Illinois
  grower they are below average for farming in Illinois.</p>
  <p><b>A local comparison already runs</b>, on free imagery, with no data asked
  of the member or of anyone around them.</p>
 </div>
 <div class="col">
  <p class="kicker">The next three steps</p>
  <p><b>1.</b> Ask FSA whether we qualify for current CLU.</p>
  <p><b>2.</b> Pick one member cooperative and run their fields the way we ran
  these three counties.</p>
  <p><b>3.</b> Collect one season of grower-reported cover on a few dozen of
  those fields, and find out whether the ranking is right.</p>
 </div>
</div>
<p class="quote" style="margin-top:.20in">We can stop telling growers they are
below a national average that was never about them.</p>"""))

html = (f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Hyper-local benchmarks</title><style>{CSS}</style></head>"
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
