#!/usr/bin/env python
"""Build the cotton pitch deck as a native .pptx, on Field to Market branding.

    python pitch/cotton-2026/build_pptx.py

Follows pitch/branding-assets/ftm_brand.md: the six-colour palette at its stated
40/40/5/5/5/5 weighting, the 1.25in blue header bar, the 0.38in brand footer
strip at y = 7.12, Arial Narrow Bold headings over Arial body, and the
horizontal logo.

Two things the brand guide settles that would otherwise be judgement calls.
Deep Current and Ember Glow carry 80% of the weight between them, so the four
accent colours appear only where something genuinely needs a third signal.
And the logo is dark blue on transparent with no reversed version supplied, so
it goes on light slides only -- the brand footer strip is what carries the
identity on the blue ones.
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

REPO = Path(__file__).resolve().parents[2]
BRAND = REPO / "pitch" / "branding-assets"
OUT = REPO / "pitch" / "cotton-2026" / "Cotton-Remote-Sensing-Pitch.pptx"

W, H = 13.333, 7.5
HDR_H, FTR_H, FTR_Y = 1.25, 0.38, 7.12
M = 0.55                                  # side margin
BODY_TOP, BODY_BOT = 1.58, 6.92

BLUE   = RGBColor(0x10, 0x42, 0x7C)       # Deep Current   primary 40%
ORANGE = RGBColor(0xF4, 0x6C, 0x09)       # Ember Glow     primary 40%
GREEN  = RGBColor(0x00, 0xB1, 0x4C)       # Meadow Pulse   accent 5%
TEAL   = RGBColor(0x0D, 0x9A, 0xC6)       # Sky Drift      accent 5%
PURPLE = RGBColor(0x46, 0x26, 0x68)       # Twilight Bloom accent 5%
YELLOW = RGBColor(0xFF, 0xD1, 0x03)       # Solar Bloom    accent 5%
GRAY   = RGBColor(0x58, 0x59, 0x5B)       # Iron Whisper   body text
LTGRAY = RGBColor(0xEE, 0xEE, 0xEE)
DKGRAY = RGBColor(0x44, 0x44, 0x44)
BLACK  = RGBColor(0x21, 0x21, 0x21)       # Night Spark    headings
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
ONBLUE = RGBColor(0xD6, 0xE0, 0xEC)       # body text on Deep Current

HEAD, TEXT = "Arial Narrow", "Arial"
BAR = [(BLUE, 40), (ORANGE, 40), (GREEN, 5), (TEAL, 5), (PURPLE, 5), (YELLOW, 5)]

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
BLANK = prs.slide_layouts[6]


def _rect(s, x, y, w, h, fill, line=None, rounded=False, lw=1.0):
    shp = s.shapes.add_shape(5 if rounded else 1, Inches(x), Inches(y),
                             Inches(w), Inches(h))
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    if rounded:
        shp.adjustments[0] = 0.05
    return shp


def brand_bar(s, y=FTR_Y, h=FTR_H):
    """The six brand colours left to right at their stated proportions."""
    x = 0.0
    for col, pct in BAR:
        seg = W * pct / 100.0
        _rect(s, x, y, seg + 0.004, h, col)       # hairline overlap, no seams
        x += seg


def slide(bg=WHITE, header=None, logo=False):
    s = prs.slides.add_slide(BLANK)
    _rect(s, 0, 0, W, H, bg)
    if header is not None:
        _rect(s, 0, 0, W, HDR_H, BLUE)
        text(s, header, M, 0.36, W - 2 * M - 2.2, 0.62, 27, WHITE, True, HEAD,
             spacing=1.0)
    if logo:
        s.shapes.add_picture(str(BRAND / "FTM-H_rgb.png"), Inches(W - M - 2.3),
                             Inches(0.30), width=Inches(2.3))
    brand_bar(s)
    return s


def text(s, txt, x, y, w, h, size=14, color=GRAY, bold=False, font=TEXT,
         align=PP_ALIGN.LEFT, spacing=1.2, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(txt if isinstance(txt, list) else [txt]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        for rt, rb in (line if isinstance(line, list) else [(line, bold)]):
            run = p.add_run(); run.text = rt
            run.font.size, run.font.bold = Pt(size), rb
            run.font.color.rgb = color; run.font.name = font
    return tb


def card(s, x, y, w, h, fill=WHITE, line=RGBColor(0xDD, 0xDD, 0xDD), lw=1.0):
    return _rect(s, x, y, w, h, fill, line, rounded=True, lw=lw)


def bar(s, x, y, w, h, fill):
    return _rect(s, x, y, w, h, fill)


def footer(s, txt, color=GRAY):
    text(s, txt, M, FTR_Y - 0.34, W - 2 * M, 0.28, 9, color)


def notes(s, txt):
    s.notes_slide.notes_text_frame.text = txt


def table(s, rows, x, y, w, col_w, size=12, head_h=0.38, row_h=0.36):
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
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = (BLUE if i == 0 else
                                        (WHITE if i % 2 else LTGRAY))
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
            strong = val.startswith("*")
            run = p.add_run(); run.text = val.lstrip("*")
            run.font.size = Pt(size)
            run.font.bold = (i == 0) or strong
            run.font.name = HEAD if i == 0 else TEXT
            run.font.color.rgb = (WHITE if i == 0 else
                                  (BLUE if strong else DKGRAY))
    return shp


# ----------------------------------------------------------------- 1 cover ---
s = slide()
s.shapes.add_picture(str(BRAND / "FTM-H_wTAG_rgb.png"), Inches(M),
                     Inches(0.75), width=Inches(4.6))
text(s, ["Cotton ground,", "measured from orbit"], M, 2.5, 11.8, 2.0, 46,
     BLUE, True, HEAD, spacing=1.0)
_rect(s, M, 4.62, 2.2, 0.055, ORANGE)
text(s, "A working pipeline that reads tillage, residue and cover crops off "
        "free satellite imagery — and an honest account of what it can "
        "and cannot do yet.", M, 4.95, 10.2, 1.0, 17, GRAY, spacing=1.35)
for i, t in enumerate(["Validated against 183 cotton field-years",
                       "Georgia, 2018–2021", "September 2026"]):
    text(s, t, M + i * 3.9, 6.45, 3.7, 0.3, 11, GRAY)
notes(s, "Open by saying this is not a concept deck. The pipeline runs today, "
         "and we have finished testing it against real farmer-reported data. "
         "Some of what we found is good and some of it is not, and both are in "
         "this deck.")

# ------------------------------------------------------------------- 2 ask ---
s = slide(header="What we are asking cotton for", logo=True)
text(s, "The ask comes first, because the technical work only matters if it "
        "gets finished. Two things are needed, and one of them is not money.",
     M, BODY_TOP, 11.4, 0.5, 15, GRAY, spacing=1.3)
for i, (n, t, b, col) in enumerate([
        ("ONE", "Implementation funding",
         "To move this out of demonstration and into the Fieldprint Platform, "
         "where growers and brands actually use it.", BLUE),
        ("TWO", "Ground truth from cotton ground",
         "Residue transects and practice records. Without them the numbers "
         "stay provisional, and we will keep saying so.", ORANGE)]):
    x = M + i * 6.15
    card(s, x, 2.45, 5.75, 2.25, WHITE, col, 1.5)
    text(s, n, x + 0.35, 2.72, 4, 0.25, 11, col, True, HEAD)
    text(s, t, x + 0.35, 3.05, 5.05, 0.5, 20, BLACK, True, HEAD)
    text(s, b, x + 0.35, 3.72, 5.05, 0.8, 13, GRAY, spacing=1.3)
text(s, [[("The second cannot be bought from a vendor. ", True),
          ("Only growers and their agronomists have it, which is why this "
           "conversation is with you and not with a software company.", False)]],
     M, 5.05, 11.8, 0.6, 14, BLUE, spacing=1.3)
footer(s, "Field to Market  ·  Cotton remote sensing")
notes(s, "Lead with the ask so nobody spends the next twelve slides wondering "
         "where this is going. Put weight on the closing line: the data is the "
         "part only this room can supply.")

# --------------------------------------------------------------- 3 problem ---
s = slide(BLUE)
text(s, "Nearly every sustainability claim made about cotton rests on what "
        "someone remembered and wrote down.", M, 1.35, 11.9, 1.9, 34, WHITE,
     True, HEAD, spacing=1.12)
_rect(s, M, 3.5, 2.2, 0.055, ORANGE)
text(s, "Self-reported practice data is costly to collect, impossible to audit "
        "at scale, and slow to arrive. Brands are being asked to verify what "
        "nobody can see.", M, 3.9, 5.6, 1.3, 14, ONBLUE, spacing=1.4)
text(s, "Meanwhile satellites photograph every cotton field in the country "
        "every five days, free of charge, and have done since 2017. The "
        "question is whether that imagery can carry the claim.",
     M + 6.25, 3.9, 5.6, 1.3, 14, ONBLUE, spacing=1.4)
text(s, "We spent this year finding out. This deck is what we learned, "
        "including where it fell short.", M, 5.8, 10.5, 0.5, 15, YELLOW,
     spacing=1.3)
notes(s, "Framing slide. Do not rush it. The audience knows the self-reporting "
         "problem intimately, because they pay for it. Land the last line so "
         "the honesty later reads as credibility rather than retreat.")

# ----------------------------------------------------------------- 4 built ---
s = slide(header="What we built", logo=True)
text(s, "A field boundary goes in. All of this comes out, for every season "
        "back to 2017, with no field visit and no cost per acre.",
     M, BODY_TOP, 11.4, 0.4, 15, GRAY, spacing=1.3)
for i, (t, b) in enumerate([
        ("Crop grown", "Each year of the rotation, from the USDA Cropland Data Layer."),
        ("Planting and harvest", "Inferred from the green-up and senescence curve."),
        ("Cover crops", "Off-season green cover between cash crops."),
        ("Soil armor", "How much of the surface is protected, by residue or by anything living.")]):
    x = M + i * 3.07
    card(s, x, 2.35, 2.87, 1.95)
    _rect(s, x + 0.25, 2.58, 0.34, 0.055, ORANGE)
    text(s, t, x + 0.25, 2.75, 2.4, 0.45, 15, BLUE, True, HEAD)
    text(s, b, x + 0.25, 3.28, 2.4, 0.95, 11, GRAY, spacing=1.3)
card(s, M, 4.65, 11.85, 0.95, LTGRAY, LTGRAY)
for i, (h, d) in enumerate([("Sentinel-2", "10 m pixels, every 5 days, free"),
                            ("Two implementations", "R and Python, checked against each other"),
                            ("No new sensors", "Nothing to install on a farm")]):
    x = M + 0.35 + i * 3.85
    text(s, h, x, 4.86, 3.6, 0.26, 13, BLUE, True, HEAD)
    text(s, d, x, 5.14, 3.6, 0.32, 11, GRAY)
footer(s, "Field to Market  ·  Cotton remote sensing")
notes(s, "The bottom band is the cost story: no hardware, no per-acre imagery "
         "fee. The imagery is a public good already paid for.")

# ------------------------------------------------------------------ 5 demo ---
s = slide(header="Two cotton fields, two years, every clear day", logo=True)
IMG_H = 3.75
s.shapes.add_picture(str(REPO / "r" / "outputs" / "20_cotton_two_years.png"),
                     Inches((W - IMG_H / 0.5556) / 2), Inches(BODY_TOP),
                     height=Inches(IMG_H))
text(s, [[("Green is living cover. Tan is residue. White is bare soil. ", True),
          ("Both fields grow continuous cotton, so the crop is not what "
           "separates them.", False)]], M, 5.62, 5.7, 0.9, 12, GRAY, spacing=1.3)
text(s, "The Georgia field is cover cropped and never opens up. The Texas "
        "pivot returns to bare ground after every harvest and stays there "
        "until June.", M + 6.15, 5.62, 5.7, 0.9, 12, GRAY, spacing=1.3)
footer(s, "Sentinel-2, all cloud-free dates. Dashed lines mark inferred "
          "planting and harvest.")
notes(s, "Linger here. Everything is computed, not drawn by hand. The winter "
         "gap in the Texas panel is exactly the erosion-exposure window a "
         "Fieldprint score should care about, and nobody visited either field.")

# ----------------------------------------------------------------- 6 armor ---
s = slide(header="Soil armor: cover from any source", logo=True)
text(s, "Every pixel is split into three fractions that add to one. A field "
        "protected by stubble and a field protected by a living cover crop "
        "both score high, because both resist erosion.",
     M, BODY_TOP, 11.4, 0.5, 15, GRAY, spacing=1.3)
# Night Spark on Meadow Pulse and Ember Glow, not white: both brand primaries
# are mid-luminance, so white text on them measures 2.8-3.0:1 against the
# 4.5:1 floor, while #212121 measures 5.5-5.7:1.
for i, (t, d, fill, tc, dc) in enumerate([
        ("Living", "Green canopy or cover crop", GREEN, BLACK, BLACK),
        ("Residue", "Stubble, litter, dead stalks", ORANGE, BLACK, BLACK),
        ("Bare soil", "Exposed, erodible ground", LTGRAY, BLACK, GRAY)]):
    x = M + i * 4.08
    card(s, x, 2.45, 3.82, 1.5, fill, fill if i < 2 else RGBColor(0xDD, 0xDD, 0xDD))
    text(s, t, x + 0.3, 2.72, 3.2, 0.4, 19, tc, True, HEAD)
    text(s, d, x + 0.3, 3.22, 3.2, 0.5, 12, dc, spacing=1.25)
card(s, M, 4.3, 11.85, 1.1, LTGRAY, LTGRAY)
text(s, "Soil armor = 1 − bare soil", M + 0.35, 4.55, 4.0, 0.4, 20, BLUE,
     True, HEAD)
text(s, "Separating residue from bare soil needs shortwave infrared, not just "
        "a greenness index — to visible light, dry stubble and dry dirt "
        "look nearly the same.", M + 4.6, 4.57, 6.85, 0.75, 12, GRAY, spacing=1.3)
footer(s, "Ternary unmixing in NDVI–DFI space. Endmembers fitted on "
          "65,555 cloud-free pixels — provisional.")
notes(s, "The important idea is that armor counts residue and living cover "
         "together. That is deliberate, and it is also why armor turns out not "
         "to be a tillage detector.")

# ------------------------------------------------------------ 7 separation ---
s = slide(header="On cotton, armor tracks reported tillage", logo=True)
text(s, "Median spring soil armor for 183 cotton field-years, grouped by the "
        "residue class the grower reported. The order is right and the spread "
        "is wide.", M, BODY_TOP, 11.4, 0.5, 15, GRAY, spacing=1.3)
SCALE = 8.0 / 0.70
for i, (lab, sub, val, n, col) in enumerate([
        ("Conventional", "under 15% residue", 0.408, 48, GRAY),
        ("Reduced", "15 to 30% residue", 0.508, 9, ORANGE),
        ("Conservation", "over 30% residue", 0.594, 126, BLUE)]):
    y = 2.45 + i * 0.88
    text(s, lab, M, y + 0.02, 2.0, 0.28, 13, BLACK, True)
    text(s, sub, M, y + 0.28, 2.0, 0.28, 11, GRAY)
    bar(s, M + 2.1, y, val * SCALE, 0.58, col)
    # Not `col`: Ember Glow on white measures 3.0:1, which is at the large-text
    # limit rather than clear of it. The bar carries the category.
    text(s, f"{val:.3f}", M + 2.25 + val * SCALE, y + 0.04, 1.0, 0.38, 19,
         BLACK, True, HEAD)
    text(s, f"n = {n}", M + 3.2 + val * SCALE, y + 0.12, 0.9, 0.28, 10, GRAY)
text(s, [[("A conservation-tilled cotton field carries roughly half again as "
           "much cover ", True),
          ("through the spring as a conventionally tilled one. Slide 12 "
           "explains what is really driving that gap.", False)]],
     M, 5.35, 11.7, 0.7, 14, GRAY, spacing=1.3)
footer(s, "Time-weighted mean, 1 March to 15 May. Bars scaled to 0.70.")
notes(s, "Flag the n of 9 on the reduced class honestly if asked: too small to "
         "lean on, and excluded from every accuracy figure later.")

# --------------------------------------------------------------- 8 dataset ---
s = slide(BLUE)
text(s, "Then we checked it against farmers", M, 0.75, 11.9, 0.65, 34, WHITE,
     True, HEAD)
_rect(s, M, 1.55, 2.2, 0.055, ORANGE)
text(s, "A University of Georgia grower survey gave us boundaries, crop, "
        "tillage class, cover crop and irrigation, field by field and year by "
        "year. It is the first time any of this was tested against something a "
        "farmer said.", M, 1.9, 11.5, 0.75, 15, ONBLUE, spacing=1.3)
for i, (v, l) in enumerate([("183", "cotton field-years"),
                            ("144", "distinct cotton fields"),
                            ("34", "Georgia counties"),
                            ("21,129", "acres of cotton")]):
    x = M + i * 3.07
    card(s, x, 3.15, 2.87, 1.5, RGBColor(0x1B, 0x55, 0x96),
         RGBColor(0x1B, 0x55, 0x96))
    text(s, v, x + 0.3, 3.35, 2.4, 0.66, 34, YELLOW, True, HEAD)
    text(s, l, x + 0.3, 4.06, 2.4, 0.42, 12, ONBLUE, spacing=1.2)
text(s, "Every field-year was scored blind: the pipeline never saw the survey "
        "answers. Accuracy figures below are cross-validated by field, so "
        "repeat years of one farm cannot flatter the result.",
     M, 5.0, 11.5, 0.75, 14, ONBLUE, spacing=1.35)
footer(s, "Survey years 2018–2021. Median field 82 acres. 78% irrigated.",
       ONBLUE)
notes(s, "Stress the blind scoring and the by-field cross-validation. "
         "Technical audiences will ask; getting in front of it buys trust for "
         "the next slide.")

# ------------------------------------------------------------- 9 scorecard ---
s = slide(header="The cotton scorecard", logo=True)
table(s, [["What we measure", "Field-years", "Correct", "Catches", "False alarms"],
          ["Crop is cotton", "183", "*85.2%", "156 of 183", "25"],
          ["Cover crop grown", "182", "*75.3%", "111 of 114", "42"],
          ["Conservation tillage", "174", "*76.4%", "105 of 126", "20"]],
      M, BODY_TOP, 11.85, [3.2, 1.6, 1.6, 2.2, 1.8], 13, 0.46, 0.5)
text(s, [[("Cotton is the strong crop. ", True),
          ("It misses almost nothing: 97% of cover crops and 83% of "
           "conservation-tilled fields are caught.", False)]],
     M, 3.85, 5.7, 1.0, 13, GRAY, spacing=1.3)
text(s, [[("False alarms are the weak point. ", True),
          ("The system over-calls conservation practice, which is exactly "
           "what calibration data fixes.", False)]],
     M + 6.15, 3.85, 5.7, 1.0, 13, GRAY, spacing=1.3)
footer(s, "Cover crop and tillage thresholds fitted in-sample; cross-validated "
          "they fall to 75.2% and 73.8%.")
notes(s, "Do not hide the footnote. The in-sample figures are the optimistic "
         "view; the cross-validated ones are what to plan against. Both are in "
         "the written report.")

# --------------------------------------------------------------- 10 purity ---
s = slide(header="Bad field boundaries break everything downstream", logo=True)
text(s, "A boundary drawn around two management units blends two crops into "
        "one curve. We can detect that before reporting anything — and it "
        "predicts almost perfectly whether we get the crop right.",
     M, BODY_TOP, 11.4, 0.5, 14, GRAY, spacing=1.3)
for i, (lab, pct, n, col) in enumerate([
        ("Under 60% one crop", 12.9, 31, PURPLE),
        ("60–75% one crop", 72.0, 25, ORANGE),
        ("75–90% one crop", 90.0, 90, BLUE),
        ("Over 90% one crop", 88.1, 201, BLUE)]):
    y = 2.35 + i * 0.68
    text(s, lab, M, y + 0.1, 2.4, 0.28, 12, GRAY)
    bar(s, M + 2.5, y, pct / 100 * 7.1, 0.47, col)
    text(s, f"{pct:.1f}%", M + 2.65 + pct / 100 * 7.1, y + 0.04, 1.0, 0.33, 16,
         BLACK, True, HEAD)
    text(s, f"{n} fields", M + 3.6 + pct / 100 * 7.1, y + 0.1, 1.1, 0.28, 10, GRAY)
text(s, [[("This is free quality control. ", True),
          ("Refusing to score the worst 16% of boundaries lifts crop accuracy "
           "from 80.7% to 88.7% and costs nothing but an honest “we cannot "
           "read this field”.", False)]],
     M, 5.3, 11.7, 0.8, 14, GRAY, spacing=1.3)
footer(s, "Agreement with grower-reported crop, by share of the boundary CDL "
          "assigns to a single class. All 347 field-years.")
notes(s, "This shows operational maturity rather than a science result. "
         "Knowing when to refuse to answer is what a platform needs.")

# --------------------------------------------------------- 11 uncalibrated ---
s = slide(header="What an uncalibrated threshold costs", logo=True)
text(s, "Our cover crop threshold came from Mid-Atlantic literature, where "
        "winter residue sits at NDVI 0.10–0.25. In Georgia the median "
        "field with no cover crop at all peaks at 0.53 — 0.50 on cotton. "
        "Winter weeds, "
        "volunteer and a mild climate put green on ground nobody planted.",
     M, BODY_TOP, 11.4, 0.7, 14, GRAY, spacing=1.3)
for i, (tag, big, body, col) in enumerate([
        ("OUT-OF-REGION THRESHOLD", "60",
         "false alarms out of 68 cotton fields that grew no cover crop. It "
         "called almost every field a cover crop, so the answer carried no "
         "information.", PURPLE),
        ("REFITTED ON COTTON GROUND", "42",
         "false alarms, while still catching 111 of 114 real cover crops. "
         "Accuracy 67% to 75% from a single recalibrated number.", BLUE)]):
    x = M + i * 6.15
    card(s, x, 2.6, 5.75, 2.35, WHITE, col, 1.75)
    text(s, tag, x + 0.35, 2.85, 5.05, 0.28, 10, col, True, HEAD)
    text(s, big, x + 0.35, 3.12, 2.0, 0.72, 40, col, True, HEAD)
    text(s, body, x + 0.35, 3.95, 5.05, 0.85, 12, GRAY, spacing=1.3)
text(s, [[("One constant, refitted on 182 fields, removed 18 of every 60 false "
           "alarms. ", True),
          ("That is what your data buys, and it is the cheapest improvement "
           "available to us.", False)]],
     M, 5.25, 11.7, 0.7, 14, BLACK, spacing=1.3)
footer(s, "Cotton field-years only. Threshold moved from NDVI 0.35 to 0.449.")
notes(s, "This is the money slide for the funding ask. The defect was "
         "invisible for the entire life of the project and took real ground "
         "truth to surface. Say that plainly: we could not have found it any "
         "other way.")

# ------------------------------------------------------------- 12 confound ---
s = slide(header="The finding we did not want", logo=True)
text(s, "Split the same cotton fields by tillage and cover crop, then read "
        "— down the columns rather than across the rows.",
     M, BODY_TOP, 11.4, 0.4, 14, GRAY, spacing=1.3)
# A true 2x2 rather than four stacked rows: the whole point is a column-wise
# reading, and a four-row list hides it.
table(s, [["Median spring armor", "No cover crop", "With cover crop"],
          ["Conventional tillage", "*0.344   n = 35", "*0.604   n = 13"],
          ["Conservation tillage", "*0.507   n = 31", "*0.625   n = 95"]],
      M, 2.12, 11.85, [4.0, 4.0, 4.0], 14, 0.46, 0.46)
text(s, [[("A conventionally tilled field with a cover crop reads 0.604 — "
           "indistinguishable from a conservation-tilled one at 0.625, and "
           "far above a conventionally tilled field without one at 0.344. ",
           True),
          ("Armor is not reading the tillage pass — it is reading the "
           "cover crop, and 75% of conservation-tilled cotton here also has "
           "one.", False)]],
     M, 3.6, 11.7, 0.7, 13, GRAY, spacing=1.3)
card(s, M, 4.45, 11.85, 1.15, WHITE, BLUE, 1.5)
text(s, "All four combinations are loaded in the demo app", M + 0.3, 4.62,
     11.2, 0.3, 13, BLUE, True, HEAD)
text(s, [[("Georgia cotton, grower-confirmed practice.  With a cover crop: ", True),
          ("Mitchell Co., no-till 0.624 · Jefferson Co., tilled 0.553.   ", False),
          ("Without one: ", True),
          ("Mitchell Co., tilled 0.488 · Screven Co., no-till 0.480.   ", False),
          ("Cover crop column 0.589, column without 0.484.", True)]],
     M + 0.3, 4.95, 11.2, 0.55, 12, GRAY, spacing=1.3)
text(s, [[("So we report it as cover, not tillage. ", True),
          ("That is the honest claim, it is the one that resists erosion, and "
           "it is the one we will defend.", False)]],
     M, 5.75, 11.7, 0.5, 13, BLUE, spacing=1.3)
footer(s, "Time-weighted spring soil armor, 174 cotton field-years with a "
          "reported tillage class. The four named fields illustrate the "
          "pattern; the 174 establish it.")
notes(s, "Include this slide deliberately. An audience that has been sold "
         "remote sensing before is waiting for the catch, and showing it "
         "ourselves is worth more than any accuracy figure.\n\n"
         "The table is the evidence; the four named fields are the "
         "demonstration. If anyone doubts it, open the app and filter the "
         "field library on \"grower-confirmed\". Read the four down the "
         "columns, not across: the two with a cover crop average 0.589, the "
         "two without average 0.484. Tillage moves these four by 0.03, the "
         "cover crop by 0.11 -- the same split the 174 field-years show.\n\n"
         "Do not offer a ratio for how much more armor reads cover than "
         "tillage. The slide used to say 0.26 against 0.02, which took the "
         "largest cover cell and the smallest tillage cell from opposite "
         "corners of the table. Read fairly it is 0.19 against 0.09, and on "
         "marginal medians 0.200 against 0.186. The direction holds under "
         "every reading; no single multiple does, so make the point with the "
         "three cells instead.\n\n"
         "Do not lean on the 0.480 against 0.488 pair even though it points "
         "the right way. Eight thousandths on an index this deck calls "
         "provisional is not a number to defend in a room, and offering it "
         "invites the one objection that would cost us the rest.\n\n"
         "Jefferson Co. is the soft one if pressed: its 2021 phenology "
         "confidence is low, and the armor window closes three days before an "
         "estimated planting date. It still lands above both fields with no "
         "cover crop, which is the point being made.\n\n"
         "Be straight that four fields illustrate rather than prove. They also "
         "differ in size, county and irrigation. The 174 field-years carry the "
         "claim.")

# ----------------------------------------------------------------- 13 buys ---
s = slide(header="What your ground truth would buy", logo=True)
table(s, [["What we need", "What it fixes", "Why it cannot wait"],
          ["Residue line transects", "Turns soil armor from a rank into a real percentage of ground covered",
           "The one measurement that separates residue from a cover crop"],
          ["Practice records outside Georgia", "Regional thresholds instead of one national constant",
           "An out-of-region number cost us 60 false alarms on 68 fields"],
          ["Planting and harvest dates", "The only component still untested against anything",
           "Every seasonal window in the pipeline depends on these"],
          ["Reduced-till fields, 15–30%", "A three-class answer instead of a two-class one",
           "We have 9 such cotton fields. Nine is not enough to fit anything"]],
      M, BODY_TOP, 11.85, [3.3, 4.3, 4.3], 11, 0.42, 0.74)
text(s, "None of this requires new instruments or a research station. It is a "
        "clipboard, a tape, and the records growers already keep — "
        "matched to fields we can already see.",
     M, 5.5, 11.7, 0.6, 14, GRAY, spacing=1.3)
footer(s, "Field to Market  ·  Cotton remote sensing")
notes(s, "We are asking for measurements that are cheap on the ground but "
         "impossible to synthesise from orbit. Make clear we are not asking "
         "anyone to fund a satellite.")

# --------------------------------------------------------------- 14 invest ---
s = slide(BLUE)
text(s, "The commitment we are seeking", M, 0.75, 11.9, 0.65, 34, WHITE, True,
     HEAD)
_rect(s, M, 1.55, 2.2, 0.055, ORANGE)
for i, (ph, t, d, money) in enumerate([
        ("PHASE 1", "Platform integration",
         "Move the pipeline into the Fieldprint Platform so growers see it in "
         "their own reports.", "[__ months]"),
        ("PHASE 2", "Cotton calibration campaign",
         "Residue transects and practice records on [___] cotton fields "
         "across [___] regions.", "[__ growing seasons]"),
        ("PHASE 3", "Cotton Belt rollout",
         "Regional thresholds from Georgia to the High Plains, reported with "
         "stated confidence.", "[__ months]")]):
    x = M + i * 4.08
    card(s, x, 2.0, 3.82, 2.95, RGBColor(0x1B, 0x55, 0x96),
         RGBColor(0x1B, 0x55, 0x96))
    text(s, ph, x + 0.3, 2.2, 3.2, 0.25, 10, YELLOW, True, HEAD)
    text(s, t, x + 0.3, 2.5, 3.2, 0.55, 17, WHITE, True, HEAD)
    text(s, d, x + 0.3, 3.2, 3.2, 0.95, 11, ONBLUE, spacing=1.3)
    text(s, "[$____]", x + 0.3, 4.2, 3.2, 0.32, 15, YELLOW, True, HEAD)
    text(s, money, x + 0.3, 4.55, 3.2, 0.28, 10, ONBLUE)
text(s, "What you get is not a score with a number after it. It is a "
        "measurement with a stated accuracy, an audit trail back to public "
        "imagery, and a published account of where it fails.",
     M, 5.3, 11.7, 0.75, 14, ONBLUE, spacing=1.35)
footer(s, "Field to Market  ·  Cotton remote sensing", ONBLUE)
notes(s, "Figures in brackets need filling before this is presented. Do not "
         "improvise them in the room. If pressed, offer to follow up in "
         "writing the same week.")

# ---------------------------------------------------------------- 15 close ---
s = slide()
s.shapes.add_picture(str(BRAND / "FTM-H_rgb.png"), Inches(W - M - 2.5),
                     Inches(0.5), width=Inches(2.5))
text(s, "The imagery is already free. The fields are already photographed. "
        "What is missing is the ground.", M, 1.35, 9.8, 1.5, 33, BLUE, True,
     HEAD, spacing=1.12)
_rect(s, M, 3.05, 2.2, 0.055, ORANGE)
text(s, "Cotton is the crop this works best on today. Of everything we tested, "
        "cotton gave the cleanest separation and the highest catch rate "
        "— 97% of cover crops, 83% of conservation-tilled fields.",
     M, 3.4, 5.7, 1.2, 13, GRAY, spacing=1.35)
text(s, "It is also where the gaps are clearest. We can name every one of "
        "them, which is how you know the rest of the numbers are worth "
        "something.", M + 6.15, 3.4, 5.7, 1.2, 13, GRAY, spacing=1.35)
text(s, "Fund the integration, supply the ground truth, and cotton gets a soil "
        "cover measurement its supply chain can actually audit.",
     M, 4.9, 11.7, 0.7, 16, BLUE, True, HEAD, spacing=1.25)
_rect(s, M, 5.85, 11.85, 0.01, RGBColor(0xDD, 0xDD, 0xDD))
text(s, ["Eric Coronel", "Field to Market"], M, 6.05, 3.5, 0.55, 12, GRAY)
text(s, "ecoronel@fieldtomarket.org", M + 4.1, 6.05, 3.6, 0.28, 12, GRAY)
text(s, ["Full validation report and", "source code available on request"],
     M + 8.2, 6.05, 4.2, 0.55, 12, GRAY)
notes(s, "Close on the ask, not the technology. Offer the written validation "
         "report in the room: it contains every number in this deck plus the "
         "ones that did not flatter us, and handing it over is the strongest "
         "trust signal available.")

# ------------------------------------------------------------- 16 appendix ---
s = slide(header="Appendix — Phase 1 engineering breakdown", logo=True)
table(s, [["Workstream", "Hours"],
          ["Read and understand the existing pipeline", "16–24"],
          ["Dependency packaging, GDAL in containers", "16–24"],
          ["Job orchestration: queue, workers, retries", "40–60"],
          ["Caching layer on S3", "24–32"],
          ["CDL bulk store on S3 — pattern already built", "8–16"],
          ["API service and boundary validation", "32–40"],
          ["Hardening external dependencies", "16–24"],
          ["Test suite — none exists today", "40–56"],
          ["Observability and cost controls", "16–24"],
          ["Infrastructure as code, CI/CD", "24–32"],
          ["*Sum, one senior developer", "*232–332"],
          ["Integration with Fieldprint internals", "not estimable"]],
      M, BODY_TOP, 7.3, [5.4, 1.9], 11, 0.34, 0.325)
for i, (t, b, col) in enumerate([
        ("Lean MVP: 150–190 h",
         "Batch only, one region, no public API. Results written to a table "
         "the platform reads.", RGBColor(0xDD, 0xDD, 0xDD)),
        ("Risk already retired",
         "USDA CropScape could not take platform traffic — a 40-hour "
         "contingency. Now built and measured: 52 minutes to 5.6 seconds, "
         "agreeing with the API on 346 of 347 fields.", BLUE),
        ("Measured, not guessed",
         "1.3 min per field for 7 seasons · 2,415 lines of Python · "
         "zero tests today", RGBColor(0xDD, 0xDD, 0xDD))]):
    y = BODY_TOP + i * 1.42
    card(s, 8.15, y, 4.62, 1.28, WHITE, col, 1.75 if i == 1 else 1.0)
    text(s, t, 8.4, y + 0.14, 4.1, 0.28, 13, BLUE if i != 2 else BLACK, True, HEAD)
    text(s, b, 8.4, y + 0.46, 4.1, 0.72, 10, GRAY, spacing=1.25)
text(s, "Productionisation, not research: the algorithms are finished and "
        "cross-checked between two implementations. Refitting constants per "
        "region is science work, costed under Phase 2.",
     M, 6.25, 11.7, 0.5, 12, GRAY, spacing=1.3)
footer(s, "Assumes AWS, containerised workers, an existing API gateway. The "
          "integration line needs sight of the platform.")
notes(s, "Only show this if a technical evaluator is in the room. Per-field "
         "runtime of over a minute rules out a synchronous API, which is why "
         "orchestration is the largest line. The retired-risk card is the one "
         "to dwell on: the biggest contingency in the September estimate was "
         "closed by building it. Be candid that the integration row cannot be "
         "estimated from outside.")

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"wrote {OUT}")
print(f"slides: {len(prs.slides._sldIdLst)}")
