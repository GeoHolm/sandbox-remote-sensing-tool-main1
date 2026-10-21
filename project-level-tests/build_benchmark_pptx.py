#!/usr/bin/env python3
"""The hyper-local benchmark deck as an editable .pptx.

    python project-level-tests/build_benchmark_pptx.py

The same twenty slides as the PDF, but every heading, paragraph, bullet,
card and table is a real PowerPoint object rather than a picture, so the
text can be edited before it goes in front of members. Only the charts are
images.

Helpers follow build_alfalfa_pptx.py so the decks stay one family, and the
fit check at the end covers text boxes, pictures AND tables.
"""
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ACROSS = HERE / "_across" / "deck"
BRAND = REPO / "pitch" / "branding-assets"
OUT = HERE / "Hyper-Local-Benchmarks.pptx"

W, H = 13.333, 7.5
M = 0.62
FTR_Y, FTR_H = 7.12, 0.30
TITLE_Y, SUB_Y = 1.10, 1.70
NOTE_Y = 6.62

BLUE = RGBColor(0x10, 0x42, 0x7C)
ORANGE = RGBColor(0xF4, 0x6C, 0x09)
GREEN = RGBColor(0x00, 0xB1, 0x4C)
TEAL = RGBColor(0x0D, 0x9A, 0xC6)
PURPLE = RGBColor(0x46, 0x26, 0x68)
YELLOW = RGBColor(0xFF, 0xD1, 0x03)
INK = RGBColor(0x21, 0x21, 0x21)
GRAY = RGBColor(0x58, 0x59, 0x5B)
MUTED = RGBColor(0x8A, 0x8C, 0x8E)
LTGRAY = RGBColor(0xF2, 0xF2, 0xF2)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

HEAD, TEXT = "Arial Narrow", "Arial"
BAR = [(BLUE, 40), (ORANGE, 40), (GREEN, 5), (TEAL, 5), (PURPLE, 5), (YELLOW, 5)]

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
BLANK = prs.slide_layouts[6]


def _rect(s, x, y, w, h, fill, line=None, rounded=False, lw=1.25):
    shp = s.shapes.add_shape(5 if rounded else 1, Inches(x), Inches(y),
                             Inches(w), Inches(h))
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    if rounded:
        shp.adjustments[0] = 0.06
    return shp


def text(s, body, x, y, w, h, size=12.5, color=GRAY, bold=False, font=TEXT,
         align=PP_ALIGN.LEFT, spacing=1.30, anchor=MSO_ANCHOR.TOP,
         bullet=False, italic=False):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = body if isinstance(body, list) else [body]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(7 if len(lines) > 1 else 0)
        runs = line if isinstance(line, list) else [(line, bold)]
        if bullet:
            runs = [("•  ", False)] + list(runs)
        for rt, rb in runs:
            r = p.add_run(); r.text = rt
            r.font.size, r.font.bold = Pt(size), rb
            r.font.italic = italic
            r.font.color.rgb = color; r.font.name = font
    return tb


def brand_bar(s):
    x = 0.0
    for col, pct in BAR:
        seg = W * pct / 100.0
        _rect(s, x, FTR_Y, seg + 0.01, FTR_H, col)
        x += seg


def slide(title=None, sub=None, kicker=None, logo=True, title_size=25):
    s = prs.slides.add_slide(BLANK)
    _rect(s, 0, 0, W, H, WHITE)
    if logo:
        s.shapes.add_picture(str(BRAND / "FTM-H_rgb.png"), Inches(W - M - 2.0),
                             Inches(0.42), width=Inches(2.0))
    y = TITLE_Y
    if kicker:
        text(s, kicker.upper(), M, 0.98, 8.0, 0.26, 9.5, ORANGE, True, HEAD,
             spacing=1.0)
        y = TITLE_Y + 0.28
    if title:
        text(s, title, M, y, W - 2 * M - 2.3, 0.62, title_size, BLUE, True,
             HEAD, spacing=1.0)
    if sub:
        text(s, sub, M, (SUB_Y + 0.28) if kicker else SUB_Y, 11.2, 0.42, 12.5,
             GRAY, spacing=1.32)
    brand_bar(s)
    return s


def note(s, body):
    text(s, body, M, NOTE_Y, W - 2 * M, 0.42, 9.2, MUTED, spacing=1.32)


def notes(s, body):
    s.notes_slide.notes_text_frame.text = body


def cards(s, items, y=2.30, h=1.40, big=34):
    n = len(items)
    gap = 0.20
    w = (W - 2 * M - gap * (n - 1)) / n
    for i, (b, lab, col) in enumerate(items):
        x = M + i * (w + gap)
        _rect(s, x, y, w, h, WHITE, col, rounded=True, lw=1.5)
        text(s, b, x + 0.22, y + 0.17, w - 0.44, 0.60,
             big if len(b) < 9 else 22, col, True, HEAD, spacing=1.0)
        text(s, lab, x + 0.22, y + 0.80, w - 0.44, h - 0.94, 10.5, GRAY,
             spacing=1.26)


def table(s, rows, x, y, w, col_w, size=11, head_h=0.34, row_h=0.70):
    shp = s.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y),
                             Inches(w), Inches(head_h + row_h * (len(rows) - 1)))
    t = shp.table
    t.first_row = True
    for j, cw in enumerate(col_w):
        t.columns[j].width = Emu(int(Inches(w) * cw / sum(col_w)))
    t.rows[0].height = Inches(head_h)
    for i in range(1, len(rows)):
        t.rows[i].height = Inches(row_h)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.09)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = (BLUE if i == 0 else
                                        (WHITE if i % 2 else LTGRAY))
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j < 2 else PP_ALIGN.CENTER
            strong = val.startswith("*")
            r = p.add_run(); r.text = val.lstrip("*")
            r.font.size = Pt(size)
            r.font.bold = (i == 0) or strong
            r.font.name = HEAD if i == 0 else TEXT
            r.font.color.rgb = (WHITE if i == 0 else
                                BLUE if strong else RGBColor(0x44, 0x44, 0x44))
    return shp


def pic(s, path, x, y, w=None, h=None):
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    return s.shapes.add_picture(str(path), Inches(x), Inches(y), **kw)


def centered(s, path, y, h):
    p = pic(s, path, 0, y, h=h)
    p.left = Inches((W - p.width / Inches(1)) / 2)
    return p


def across(name):
    return ACROSS / name


def cdeck(d, name):
    return HERE / d / "figures" / "deck" / name


def quote(s, body, y, size=14):
    _rect(s, M, y, 0.05, 0.56, ORANGE)
    text(s, body, M + 0.22, y + 0.04, 11.6, 0.5, size, INK, spacing=1.40)


RCOL, RW = 7.55, W - M - 7.55

# ===================================================== 1 cover ============
s = slide(logo=False)
s.shapes.add_picture(str(BRAND / "FTM-H_wTAG_rgb.png"), Inches(M),
                     Inches(0.70), width=Inches(4.4))
text(s, ["Benchmarks a grower", "will actually accept"], M, 2.45, 11.0, 1.6,
     42, BLUE, True, HEAD, spacing=1.06)
_rect(s, M, 4.30, 2.1, 0.06, ORANGE)
text(s, [[("Members tell us a national or state comparison does not describe "
           "their farm. They are right — and we can measure how wrong it is. "
           "A working alternative, built from free satellite imagery, that "
           "compares a field with ", False), ("its own neighbors", True),
          (".", False)]], M, 4.62, 9.2, 0.9, 14, GRAY, spacing=1.40)
text(s, "Field to Market remote sensing demonstration   ·   203 fields "
        "across three counties and three rotations   ·   20 October 2026",
     M, 6.35, 11.0, 0.3, 10.5, MUTED)
notes(s, "This work started from member feedback that national and state "
         "benchmarks are not valid comparisons for an individual farm.")

# ===================================================== 2 the problem ======
s = slide("The complaint we keep hearing")
quote(s, "The objection, as it reaches us: a national or state average pools "
         "farms with different soils, different weather and different crops — "
         "so being told you are below it says very little about how a field "
         "is managed.", 1.78, 14)
text(s, [[("It is not a complaint about the metric. ", True),
          ("It is a complaint about the comparison group — and on the "
           "evidence here, it is correct.", False)],
         [("We tested it on soil cover across three counties with three "
           "different rotations: corn and soybeans in Illinois, winter wheat "
           "and double crop in Kansas, peanuts and cotton in Georgia.",
           False)]], M, 3.10, 5.85, 1.9)
text(s, "WHAT WE FOUND", 6.95, 3.10, 5.76, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("72% of the variation in soil cover sits between counties", True),
          (", not between neighboring farms. A benchmark that pools them is "
           "mostly measuring WHERE a grower farms, not HOW.", False)]],
     6.95, 3.48, 5.76, 1.5)
note(s, "Variance decomposition over 203 field means, pre-planting soil "
        "armor. The same figure is 66% for annual residue cover and 37% for "
        "the annual worst-case.")

# ===================================================== 3 pooled ===========
s = slide("A pooled benchmark grades the county, not the farmer")
centered(s, across("C_pooled_vs_local.png"), 1.80, 4.35)
note(s, "Every field in three counties. The dashed line is the median of all "
        "203 — a stand-in for a national figure. EVERY SINGLE Champaign "
        "County field falls below it on pre-plant armor, as do 82% of "
        "Mitchell's, while 91% of Sumner's sit above. None of that is "
        "management.")

# ===================================================== 4 two benchmarks ===
s = slide("The same field, two benchmarks, two verdicts")
pic(s, across("D_same_field_two_benchmarks.png"), M, 1.80, w=6.55)
text(s, "WHAT MOVES", RCOL, 1.80, RW, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("Our Illinois field sits in the ", False),
          ("top fifth of its own neighborhood", True),
          (" on every measure. Pooled with Kansas and Georgia it reads "
           "below average.", False)],
         [("The Kansas field is the mirror image: ", False),
          ("8th percentile locally", True), (", about average once pooled.",
                                             False)],
         [("Nothing about either field changed. Only the comparison group "
           "did.", False)],
         [("This is the member complaint, measured.", True)]],
     RCOL, 2.18, RW, 3.6, 12.5)
note(s, 'Three scores per field. "Local" is the field\'s own 50 to 100 '
        'qualifying neighbors; "pooled" is all 203 fields across the three '
        'counties.')

# ===================================================== 5 the proposal =====
s = slide("The proposal: benchmark a field against its neighbors",
          "Same weather. Same soils. Same markets. Same season. The "
          "comparison a grower would make themselves.")
cards(s, [("50–100", "qualifying cropland fields\naround the member's field",
           ORANGE),
          ("2.5–4.3 km", "the radius that takes\nto reach them", BLUE),
          ("0", "new data from the grower\nor from the neighbors", BLUE),
          ("~2 min", "of compute per field,\nonce, per year", BLUE)],
      y=2.34)
text(s, [[("The neighbors never have to enroll. ", True),
          ("Their boundaries come from public USDA data and their cover is "
           "read from free satellite imagery. No neighbor is identified, "
           "contacted, or asked for anything.", False)]],
     M, 4.06, 5.85, 1.5)
text(s, [[("The member's field is the only one named. ", True),
          ("Everything else is an anonymous distribution — which is also "
           "what makes it safe to show a grower where they sit.", False)]],
     6.95, 4.06, 5.76, 1.5)
note(s, "Boundaries: USDA FSA Common Land Unit, 2008 public release, which "
        "carries geometry and acreage only — every identifying attribute was "
        "stripped before release.")

# ===================================================== 6 what counts ======
s = slide("What counts as a neighbor",
          "A benchmark is only as good as its comparison group, so the "
          "filters are deliberate and stated.")
table(s, [["Filter", "Why", "Effect in Sumner County"],
          ["*40–400 acres", "Below 40 the satellite sample thins and edge "
           "pixels dominate; above 400 a single CLU unit is usually "
           "rangeland", "25,576 → 4,840"],
          ["*Compact shape", "Grass waterways, terraces and road verges are "
           "all separate units in the CLU, and all are long and thin",
           "included above"],
          ["*Cropland, 3 of 4 years", "Dominant USDA crop class at 60%+ "
           "purity. Doubles as a staleness check on an 18-year-old boundary",
           "4,840 → 3,610"],
          ["*No perennials", "An orchard has a permanent canopy and an "
           "alfalfa stand is green for years — both score high cover for "
           "reasons unrelated to the management being compared",
           "removes pecan groves,\nhay and orchards"]],
      M, 2.26, W - 2 * M, [2.0, 6.0, 2.6], row_h=0.82)
text(s, [[("Then the radius grows until it holds enough of them. ", True),
          ("A dense county needs 2.5 km; a sparser one needs 3.9.", False)]],
     M, 5.80, W - 2 * M, 0.5, 12.5)
note(s, "Mitchell County put four pecan groves into a cohort of fifty before "
        "the perennial filter existed. Filters like this are the difference "
        "between a comparison and a coincidence.")

# ===================================================== 7 rotation =========
s = slide("One step further: compare like with like",
          "A neighbor growing a different rotation is still the wrong "
          "comparison. Matching on crop sequence is the single largest "
          "improvement available.")
centered(s, across("F_rotation_match.png"), 2.20, 3.30)
text(s, [[("Crop sequence explains more of the spread inside a county than "
           "county explains between them. ", True),
          ("Match this year and last and it accounts for 78% of the "
           "variation in pre-plant cover - so an unmatched local benchmark "
           "is still partly ranking rotations.", False)]],
     M, 5.72, 5.85, 1.1, 11.5)
text(s, [[("But the matched cohort only survives where rotations repeat. ",
           True),
          ("In Champaign, every corn field followed soybeans, so matching is "
           "free. In Kansas and Georgia, requiring two years leaves six or "
           "seven neighbors - too few to rank anyone against.", False)]],
     6.95, 5.72, 5.76, 1.1, 11.5)
notes(s, "Recommendation: match on this year's crop always, add last year's "
         "where enough neighbors survive, and widen the radius rather than "
         "loosen the match. Never require three years - in Georgia that "
         "never reaches ten peers at any distance still worth calling local.")

# ===================================================== 8 Champaign ========
s = slide("Champaign County, Illinois",
          "Corn and soybeans. 50 neighbors inside 2.5 km.")
centered(s, cdeck("champaign-il", "01_cohort_map.png"), 2.10, 4.30)
note(s, "The dashed circle is the radius needed to reach 50 qualifying "
        "fields. Fields inside it that are not outlined failed a filter — "
        "the cohort is a screened subset of the neighborhood, not everything "
        "in it.")

# ===================================================== 8 Sumner ===========
s = slide("Sumner County, Kansas",
          "Winter wheat, wheat/soybean double crop, milo and cotton. "
          "100 neighbors inside 4.3 km.")
centered(s, cdeck("sumner-ks", "01_cohort_map.png"), 2.10, 4.30)
note(s, "A wider radius, because the qualifying fields are spread more thinly "
        "here. The dark wooded band running southwest is a riparian corridor "
        "- several cohort fields wrap around it, which is why their shapes "
        "are irregular. This is the 100-field cohort; the other two counties "
        "use 50.")

# ===================================================== 9 Mitchell =========
s = slide("Mitchell County, Georgia",
          "Peanuts and cotton, almost entirely center pivot. 50 neighbors "
          "inside 3.9 km.")
centered(s, cdeck("mitchell-ga", "01_cohort_map.png"), 2.10, 4.30)
note(s, "A different farming system in every respect — and the method did "
        "not change between this slide and the last one.")

# ===================================================== 9 it runs ==========
s = slide("This is not a concept. It ran.")
cards(s, [("203", "fields benchmarked\nacross three counties", BLUE),
          ("1,015", "field-years\n2022 to 2026", BLUE),
          ("0", "failures\nin 493 minutes", ORANGE),
          ("$0", "in data cost: Sentinel-2,\nUSDA CDL and CLU", BLUE)],
      y=2.10)
text(s, [[("Three rotations, one unchanged method. ", True),
          ("Corn/soy, winter wheat with double crop, and peanut/cotton under "
           "pivot. No per-county tuning.", False)]], M, 3.95, 5.85, 1.5)
text(s, [[("It uses imagery we already download. ", True),
          ("Every number here came from a pass the pipeline makes anyway for "
           "any field it is given.", False)]], 6.95, 3.95, 5.76, 1.5)
note(s, "Run on one laptop. Per-field cost ranged from 1.5 minutes in "
        "Illinois to 2.7 in Georgia, where cloud forces more scenes to be "
        "read.")

# ===================================================== 10 what it measures
s = slide("What it measures: how covered the ground is",
          "Soil armor is the share of ground covered by anything at all — "
          "living plants or crop residue.")
text(s, [[("Every pixel is split into three parts that add to one: ", False),
          ("living green cover", True), (", ", False), ("crop residue", True),
          (", and ", False), ("bare soil", True),
          (". Armor is one minus the bare fraction.", False)],
         [("It is a COVER metric, not a tillage metric. Checked against 347 "
           "farmer-reported field-years, almost all of its apparent tillage "
           "signal ran through cover crop adoption instead.", False)]],
     M, 2.20, 5.85, 2.4)
text(s, "WHY COVER IS THE RIGHT THING TO BENCHMARK LOCALLY", 6.95, 2.20,
     5.76, 0.26, 9.5, ORANGE, True, HEAD, spacing=1.0)
text(s, [[("It responds to management within a season, it does not need a "
           "yield figure or an input record, and ", False),
          ("it can be read for a neighbor who has never enrolled", True),
          (" — which is what makes a local comparison group possible at all.",
           False)]], 6.95, 2.58, 5.76, 2.0)
quote(s, "The constants behind it were fitted on eleven fields. Everything "
         "in this deck is provisional in that specific way.", 5.05)

# ================================================ 12 window and the fix ===
s = slide("One thing needed fixing first",
          "The shipped figure covers only the weeks before planting. In a "
          "cloudy spring that window is nearly empty - so we now score the "
          "whole calendar year too.")
centered(s, across("B_coverage_independence.png"), 2.22, 3.40)
text(s, [[("Illinois gets a pre-plant reading for only 74% of field-years", True),
          (", and where it does, the median field-year rests on three clear "
           "images. Kansas gets 98% off a median of eleven.", False)]],
     M, 5.82, 5.85, 1.0, 11.5)
text(s, [[("Annual residue cover", True),
          (" excludes a living crop by construction, so it compares a wheat "
           "field with a cotton field fairly. ", False),
          ("The worst 10% of the year", True),
          (" asks how bare the field got, not how bare on average. Both "
           "cover 100% of field-years.", False)]],
     6.95, 5.82, 5.76, 1.0, 11.5)

# ===================================================== 13 member view =====
s = slide("What a member would actually see",
          "Their field, ranked against the anonymous distribution of its own "
          "neighbors.")
centered(s, cdeck("sumner-ks", "04_cover_ranked.png"), 2.18, 4.15)
note(s, "One bar per field, the member's in orange. No neighbor is named and "
        "no neighbor had to enroll. This is the Kansas field, which sits in "
        "the bottom sixth of its neighborhood for off-season cover.")

# ===================================================== 14 three fields ====
s = slide("Three fields, three honest answers")
pic(s, across("E_focus_by_county.png"), M, 1.90, w=6.70)
text(s, "READ LOCALLY", RCOL, 1.90, RW, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("Illinois", True),
          (" — well covered by local standards on all three measures. A "
           "grower who would have been told they were below the national "
           "line.", False)],
         [("Kansas", True),
          (" — genuinely below its neighborhood, and the scores agree on "
           "that.", False)],
         [("Georgia", True),
          (" — the window score says middling, annual residue says bottom "
           "tenth. The largest disagreement we found, and a reminder that "
           "which score we publish is a decision, not a detail.", False)]],
     RCOL, 2.28, RW, 3.6, 12)
note(s, "Percentile among each field's own cohort. Higher is better covered.")

# ============================================ 16 cover warning + truth ====
s = slide("Do not ship the cover crop verdict yet",
          "One threshold, three counties - and we already measured that the "
          "Georgia end is wrong.")
centered(s, across("A_cover_by_county.png"), 2.20, 3.15)
text(s, [[("6% of Illinois winters score as off-season green, 61% of Kansas, "
           "88% of Georgia", True),
          (" - because the underlying distributions sit in different places. "
           "One number cannot be right in all three.", False)]],
     M, 5.60, 5.85, 1.2, 11.5)
text(s, [[("Mitchell County is the second-largest site in our own Georgia "
           "ground-truth cohort", True),
          (", 28 farmer-reported field-years, where this threshold scored "
           "144 false positives against 11 true negatives. \"100% of "
           "Mitchell fields show a cover crop\" is that false-positive rate, "
           "reproduced on new fields.", False)]],
     6.95, 5.60, 5.76, 1.2, 11.5)
notes(s, "The benchmark machinery is sound. The cover crop threshold behind "
         "one of its inputs is not, and we measured that ourselves before "
         "this deck existed.")

# ===================================================== 17 rank not judge ==
s = slide("So rank, do not judge",
          "The fix is to stop asking a yes/no question that depends on a "
          "threshold we cannot set nationally.")
text(s, "INSTEAD OF", M, 2.20, 5.85, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("\"Your field did NOT have a cover crop.\"", True)]],
     M, 2.60, 5.85, 0.5, 14, INK)
text(s, "A verdict that flips on four thousandths of an index. The Kansas "
        "field's two winters peaked at 0.296 and 0.277 against a 0.30 line.",
     M, 3.30, 5.85, 1.2)
text(s, "SAY", 6.95, 2.20, 5.76, 0.26, 9.5, ORANGE, True, HEAD, spacing=1.0)
text(s, [[("\"Your off-season cover was in the lowest sixth of 100 fields "
           "within three miles.\"", True)]], 6.95, 2.60, 5.76, 0.8, 14, INK)
text(s, "No threshold, no national constant, and the ranking held when we "
        "removed the threshold entirely.", 6.95, 3.52, 5.76, 1.2)
quote(s, "A ranking against real neighbors is both more defensible and more "
         "useful than a verdict against a national constant — and it is the "
         "thing members have been asking for.", 4.95)

# ===================================================== 18 to ship =========
s = slide("What it would take to offer this")
table(s, [["Step", "What is involved", "Size"],
          ["*Field boundaries", "The 2008 public CLU is eighteen years "
           "stale. Current CLU is restricted, but Field to Market may "
           "qualify for access — worth a conversation with FSA before "
           "anything is built. Commercial boundary sets are the fallback",
           "a phone call,\nthen a decision"],
          ["*A cohort service", "Given a member field, select neighbors, run "
           "the pass, return percentiles. Everything here already exists as "
           "scripts", "weeks"],
          ["*Regional thresholds\nor none at all", "Publish rankings on the "
           "continuous measures. Keep cover crop verdicts out of the member "
           "view until they are regionally calibrated", "a policy decision"],
          ["*A validation season", "Grower-reported cover and residue for a "
           "few dozen fields, to check the ranking against what was actually "
           "done", "one season"]],
      M, 2.10, W - 2 * M, [2.4, 7.3, 1.9], row_h=0.88)
note(s, "The compute is not the constraint: 203 fields ran on a laptop in "
        "eight hours, and a member's cohort is a few minutes of that.")

# ===================================================== 19 what it is not ==
s = slide("What this is not")
text(s, [[("Not validated. ", True),
          ("No grower record has been checked against any of this, in any of "
           "the three counties. Every criterion we used to choose between "
           "scores measures behavior — crop neutrality, independence, "
           "stability, coverage — not accuracy.", False)],
         [("Not a judgment of any individual field. ", True),
          ("Three counties of internal consistency is not evidence that a "
           "given grower is doing well or badly.", False)],
         [("Not current boundaries. ", True),
          ("2008 CLU, with a purity filter that removes the worst drift and "
           "cannot fix a field split along a line the crop layer still reads "
           "as uniform.", False)],
         [("Not a national result. ", True),
          ("Three counties. No irrigated West, no Delta, no Northern Plains, "
           "no specialty crops.", False)],
         [("Not a tillage metric. ", True),
          ("Soil armor measures cover from any source. We have measured that "
           "its apparent tillage signal runs through cover cropping.",
           False)]], M, 1.95, W - 2 * M, 4.6, 13, bullet=True, spacing=1.36)

# ===================================================== 20 the ask =========
s = slide("What we are asking for")
text(s, "THE FINDING", M, 1.90, 5.85, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("Members are right about the benchmark. ", True),
          ("Nearly three quarters of the variation in soil cover is between "
           "counties. Pooling them tells an Illinois grower they are below "
           "average for farming in Illinois.", False)],
         [("A local comparison already runs", True),
          (", on free imagery, with no data asked of the member or of anyone "
           "around them.", False)]], M, 2.28, 5.85, 2.6)
text(s, "THE NEXT THREE STEPS", 6.95, 1.90, 5.76, 0.26, 9.5, ORANGE, True,
     HEAD, spacing=1.0)
text(s, [[("1. ", True), ("Ask FSA whether we qualify for current CLU.",
                          False)],
         [("2. ", True), ("Pick one member cooperative and run their fields "
                          "the way we ran these three counties.", False)],
         [("3. ", True), ("Collect one season of grower-reported cover on a "
                          "few dozen of those fields, and find out whether "
                          "the ranking is right.", False)]],
     6.95, 2.28, 5.76, 2.6)
quote(s, "We can stop telling growers they are below a national average "
         "that was never about them.", 5.25)

# ============================================================ fit check ====
prs.save(OUT)

LIMIT = FTR_Y - 0.04
NOTE_TOP = NOTE_Y - 0.06
problems = []
for i, sl in enumerate(prs.slides, 1):
    has_note = any(sh.has_text_frame and sh.top is not None
                   and abs(sh.top / Inches(1) - NOTE_Y) < 0.02
                   for sh in sl.shapes)
    for sh in sl.shapes:
        if sh.top is None or sh.height is None:
            continue
        top = sh.top / Inches(1)
        bottom = top + sh.height / Inches(1)
        st = int(sh.shape_type) if sh.shape_type is not None else -1
        kind = {13: "picture", 19: "table", 17: "text", 1: "shape"}.get(st, "shape")
        if kind == "shape":
            if abs(top) < 0.02 and abs(bottom - H) < 0.02:
                continue
            if abs(top - FTR_Y) < 0.02:
                continue
        if bottom > LIMIT:
            problems.append("slide %2d: %-7s bottom %.2f in > %.2f"
                            % (i, kind, bottom, LIMIT))
        elif has_note and kind in ("picture", "table") and bottom > NOTE_TOP:
            problems.append("slide %2d: %-7s bottom %.2f in runs into the "
                            "footnote at %.2f" % (i, kind, bottom, NOTE_TOP))
        if sh.left is not None and sh.width is not None:
            right = (sh.left + sh.width) / Inches(1)
            if right > W - M + 0.02 and kind in ("picture", "table"):
                problems.append("slide %2d: %-7s right edge %.2f in > %.2f"
                                % (i, kind, right, W - M))

print("slides: %d" % len(prs.slides._sldIdLst))
if problems:
    print("FIT PROBLEMS:")
    for p in problems:
        print("  " + p)
    sys.exit(1)
print("fit check: clean (text, pictures and tables)")
print("wrote %s  (%.0f KB)" % (OUT, OUT.stat().st_size / 1024))
