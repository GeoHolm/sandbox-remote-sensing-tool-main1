#!/usr/bin/env python3
"""The Illinois case study as an editable .pptx.

    python project-level-tests/build_flash_pptx.py

Same 24 slides as the PDF, but every heading, paragraph, bullet, card and
table is a real PowerPoint object rather than a picture, so the text can be
edited. Only the charts are images.

Layout is top-aligned rather than vertically centred: PowerPoint has no flex
box, and a deck someone is about to edit should not shift its whole body every
time a line is added.
"""
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJ = HERE / "project-FLASH"
FIG = PROJ / "figures"
BRAND = REPO / "pitch" / "branding-assets"
OUT = PROJ / "Illinois-FLASH-Case-Study.pptx"

W, H = 13.333, 7.5
M = 0.62
FTR_Y, FTR_H = 7.12, 0.30
TITLE_Y, SUB_Y, BODY_Y = 1.10, 1.70, 2.22
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
LINE = RGBColor(0xDD, 0xDD, 0xDD)

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
         align=PP_ALIGN.LEFT, spacing=1.30, anchor=MSO_ANCHOR.TOP, bullet=False):
    """`body` is a string, a list of lines, or a list of [(run, bold), ...]."""
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
        p.space_after = Pt(6 if len(lines) > 1 else 0)
        runs = line if isinstance(line, list) else [(line, bold)]
        if bullet:
            runs = [("•  ", False)] + list(runs)
        for rt, rb in runs:
            r = p.add_run(); r.text = rt
            r.font.size, r.font.bold = Pt(size), rb
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


def cards(s, items, y=2.30, h=1.42):
    """items: list of (big, label, color)."""
    n = len(items)
    gap = 0.20
    w = (W - 2 * M - gap * (n - 1)) / n
    for i, (big, lab, col) in enumerate(items):
        x = M + i * (w + gap)
        _rect(s, x, y, w, h, WHITE, col, rounded=True, lw=1.5)
        text(s, big, x + 0.22, y + 0.17, w - 0.44, 0.60, 34, col, True, HEAD,
             spacing=1.0)
        text(s, lab, x + 0.22, y + 0.78, w - 0.44, h - 0.92, 10.5, GRAY,
             spacing=1.26)


def table(s, rows, x, y, w, col_w, size=11.5, head_h=0.36, row_h=0.34):
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
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = (BLUE if i == 0 else
                                        (WHITE if i % 2 else LTGRAY))
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
            strong = val.startswith("*")
            r = p.add_run(); r.text = val.lstrip("*")
            r.font.size = Pt(size)
            r.font.bold = (i == 0) or strong
            r.font.name = HEAD if i == 0 else TEXT
            r.font.color.rgb = WHITE if i == 0 else (BLUE if strong else
                                                     RGBColor(0x44, 0x44, 0x44))
    return shp


def pic(s, name, x, y, w=None, h=None):
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    return s.shapes.add_picture(str(FIG / name), Inches(x), Inches(y), **kw)


RCOL = 7.30          # left edge of the right-hand text column on figure slides
RW = W - M - RCOL    # its width

# ========================================================== 1 cover =========
s = slide(logo=False)
s.shapes.add_picture(str(BRAND / "FTM-H_wTAG_rgb.png"), Inches(M),
                     Inches(0.70), width=Inches(4.4))
text(s, ["Illinois case study:", "what the satellite saw"], M, 2.45, 11.0, 1.6,
     42, BLUE, True, HEAD, spacing=1.06)
_rect(s, M, 4.30, 2.1, 0.06, ORANGE)
text(s, [[("98 fields enrolled in ", False),
          ("Farmer-Led Advances in Soil Health", True),
          (", read from free satellite imagery and compared against what was "
           "entered in Fieldprint.", False)]],
     M, 4.62, 9.0, 0.9, 14, GRAY, spacing=1.40)
text(s, "Fieldprint project 370   ·   winters 2022-23 to 2025-26   ·   "
        "analysis run 11 October 2026", M, 6.35, 10.0, 0.3, 10.5, MUTED)
notes(s, "98 Illinois fields from a soil health project. Everything here comes "
         "from free satellite imagery; nobody visited a field.")

# ========================================================== 2 cohort ========
s = slide("The cohort", "195 Fieldprint payloads resolve to 98 distinct field "
                        "boundaries.")
cards(s, [("98", "distinct field boundaries", BLUE),
          ("8,668", "acres, median field 79", BLUE),
          ("6", "counties, all Illinois", BLUE),
          ("15,323", "cloud-free observations read", ORANGE)], y=2.22, h=1.34)
table(s, [["County", "fields"], ["Jo Daviess", "39"], ["Montgomery", "25"],
          ["Champaign", "12"], ["Livingston", "9"], ["Coles", "7"],
          ["Ford", "5"]],
      M, 3.80, 5.0, [2.6, 1.4])
pic(s, "01_field_size.png", 6.45, 3.80, w=5.55)
note(s, "The same physical field appears once per crop year under a different "
        "Fieldprint id, so boundaries were deduplicated on geometry. Keying on "
        "the id would have run the pipeline twice over identical ground and "
        "reported the two runs as independent agreement.")

# ========================================================== 3 what ran ======
s = slide("What was run", "One boundary in; crop history, season dates and an "
                          "off-season verdict out.")
text(s, [[("Sentinel-2 L2A", True), (" surface reflectance, 10 m, cloud-masked "
                                     "with the scene classification layer.", False)],
          [("2022 to present", True), (" — four complete off-seasons: 2022-23, "
                                       "2023-24, 2024-25, 2025-26.", False)],
          [("USDA Cropland Data Layer", True), (" for crop type and for the check "
           "on whether a boundary holds one field or several.", False)],
          [("88.3 minutes", True), (" for all 98 fields, ", False),
           ("zero failures", True), (". Median 126 clear observations per field.",
                                     False)]],
     M, BODY_Y, 6.2, 2.4, 12.5, GRAY, bullet=True, spacing=1.34)
text(s, [[("Crops present", True),
          (" (CDL): corn on 97 fields, soybeans on 91, winter wheat on 4, with "
           "small areas of grass, pasture and alfalfa.", False)]],
     M, 4.80, 6.2, 0.7, 12.5, GRAY, spacing=1.34)
pic(s, "02_boundary_quality.png", 6.95, 2.30, w=5.75)
text(s, "Boundary quality is checked before anything else, because every "
        "number downstream averages over whatever the outline contains.",
     6.95, 4.35, 5.75, 0.7, 11.5, GRAY, spacing=1.32)

# ========================================================== 4 season ========
s = slide("The growing season", "What a corn and soybean rotation looks like "
                                "from orbit.")
pic(s, "03_season_curve.png", M, 2.30, w=7.0)
text(s, [[("The cash crop is unmistakable: bare ground through April, canopy "
           "closing in June, senescence from late August.", False)],
          [("That part is easy, and it is not what this study is about. ", False),
           ("The cover crop question lives in the flat stretch between November "
            "and April", True),
           (", where the signal is small, the sky is cloudy and the difference "
            "between a sown cover and bare residue is a few hundredths of NDVI.",
            False)]],
     7.85, 2.40, 4.85, 2.6, 12.5, GRAY, spacing=1.36)
text(s, "Everything that follows concerns that off-season window.",
     7.85, 5.05, 4.85, 0.5, 13, ORANGE, True, spacing=1.30)

# ========================================================== 5 entered =======
s = slide("What project staff entered",
          "The Fieldprint payloads carry a cover crop record in exactly one winter.")
table(s, [["Winter", "fields with a cover crop recorded", "What the payload contains"],
          ["2020-21", "0", "tillage, planting, fertilizer, harvest"],
          ["2021-22", "0", "tillage, planting, fertilizer, harvest"],
          ["2022-23", "0", "tillage, planting, fertilizer, harvest"],
          ["2023-24", "0", "tillage, planting, fertilizer, harvest"],
          ["2024-25", "0", "tillage, planting, fertilizer, harvest"],
          ["*2025-26", "*98 of 98", "*+ planting_cover, with sowing and termination dates"]],
      M, BODY_Y, 12.09, [1.6, 3.2, 5.6])
text(s, [[("A ", False), ("planting_cover", True),
          (" activity appears 98 times in the entire archive", True),
          (" — once per field, all in the 2026 harvest-year interval. Every "
           "year from 2008 to 2025 carries the other four activity types and "
           "no cover crop record at all.", False)]],
     M, 5.20, 12.09, 0.7, 12.5, GRAY, spacing=1.34)
note(s, "Read plainly: the historical intervals are rotation skeletons — the "
        "crop history Fieldprint needs for its calculations — while only the "
        "current submission year carries full practice detail. The earlier "
        "zeros are silence, not a statement that no cover crop was grown.")

# ========================================================== 6 permits =======
s = slide("What that permits, and what it rules out")
cards(s, [("98", "labelled positives\n(winter 2025-26)", BLUE),
          ("0", "labelled negatives\nanywhere in the archive", ORANGE)],
      y=2.10, h=1.45)
text(s, "Measurable", M, 3.85, 5.6, 0.36, 15, BLUE, True, HEAD)
text(s, [[("Sensitivity.", True),
           (" Of 98 fields known to have been sown to a cover crop, how many "
            "does the satellite find?", False)]],
     M, 4.28, 5.6, 1.0, 12.5, GRAY, spacing=1.34)
text(s, "Not measurable", 6.90, 3.85, 5.8, 0.36, 15, ORANGE, True, HEAD)
text(s, [[("Specificity.", True),
           (" With no field known not to have a cover crop, there is no way to "
            "count false alarms. Lowering the detection threshold would look "
            "free on this data and is not.", False)]],
     6.90, 4.28, 5.8, 1.2, 12.5, GRAY, spacing=1.34)
text(s, [[("The three earlier winters are reported in this deck as ", False),
          ("what the detector claims", True), (", never scored as right or wrong.",
                                               False)]],
     M, 5.75, 12.09, 0.5, 12.5, GRAY, spacing=1.32)

# ========================================================== 7 prevalence ====
s = slide("Cover prevalence the satellite reports",
          "Four winters, same 98 fields, same thresholds.")
pic(s, "06_prevalence.png", M, 2.30, w=6.4)
text(s, [[("The trend is monotonic and the rise is substantial — from under a "
           "third of fields showing off-season green in 2022-23 to roughly two "
           "thirds in 2025-26.", False)],
          [("That is the shape a cohort progressively adopting cover crops "
            "would produce, which is what a soil health project is designed to "
            "create.", False)],
          [("It is also the shape a drifting detector would produce", True),
           (", and only the last winter carries a label. Nothing in this "
            "dataset separates the two.", False)]],
     7.30, 2.40, 5.4, 3.0, 12.5, GRAY, spacing=1.36)

# ========================================================== 8 headline ======
s = slide(None, None, kicker="The comparison you asked for")
text(s, ["Of 98 fields sown to a cover crop,", "the satellite finds 63."],
     M, 1.42, 11.0, 1.2, 28, BLUE, True, HEAD, spacing=1.08)
cards(s, [("35.7%", "strict reading\n\"likely cover crop\" only — 35 of 98", BLUE),
          ("64.3%", "loose reading\nany off-season green — 63 of 98", BLUE),
          ("35", "missed entirely\n\"no cover crop detected\"", ORANGE)],
      y=2.95, h=1.50)
table(s, [["Verdict, winter 2025-26", "fields"],
          ["likely cover crop", "35"], ["possible cover crop", "26"],
          ["green cover — cover crop or small grain", "2"],
          ["no cover crop detected", "35"]],
      M, 4.72, 12.09, [8.0, 1.6])

# ========================================================== 9 misses ========
s = slide("The misses are not bare fields",
          "Every missed field showed green. None of it reached the threshold.")
pic(s, "05_peak_ndvi.png", M, 2.30, w=7.0)
text(s, [[("All 35 misses fall between ", False),
           ("NDVI 0.193 and 0.292", True), (".", False)],
          [("Not one is below 0.15, which is what genuinely bare ground reads. ",
            False),
           ("34 of the 35 sit in the band 0.20 to 0.30", True),
           (" — immediately under the line.", False)],
          [("The detector is not confusing a cover crop with bare soil. It is "
            "seeing a modest amount of green and declining to call it.", False)]],
     7.85, 2.40, 4.85, 3.0, 12.5, GRAY, spacing=1.36)

# ========================================================== 10 off-season ===
s = slide("The off-season, detected against missed",
          "Both groups were sown. The separation is real but small.")
pic(s, "04_offseason_curve.png", M, 2.30, w=7.0)
text(s, [[("Both groups sit near 0.20 from November to March. The split opens "
           "in ", False), ("April", True),
           (", when the detected group climbs toward 0.39 and the missed group "
            "reaches about 0.27.", False)],
          [("At 42° north a cover crop drilled in late October accumulates very "
            "little biomass before dormancy. ", False),
           ("Almost the entire usable signal is compressed into four to six "
            "weeks in spring", True),
           (" — the window where Illinois cloud is heaviest.", False)]],
     7.85, 2.40, 4.85, 3.0, 12.5, GRAY, spacing=1.36)

# ========================================================== 11 all fields ===
s = slide("Every field, every clear date",
          "Off-season 2025-26. One thin line per field, both group medians on top.")
pic(s, "11_all_fields_offseason.png", M, 2.32, w=10.45)
note(s, "The spread is the finding: the two groups overlap through most of "
        "the winter and separate only in April. Markers show dates carrying at "
        "least twenty clear fields — between early December and early February "
        "almost none did, so the medians bridge that stretch.")

# ========================================================== 12 examples =====
s = slide("Two fields, side by side",
          "Both were sown in October 2025. Only one cleared the line.")
pic(s, "10_examples.png", M, 2.40, w=11.3)
note(s, "Left: a clear spring rise that stays near or above 0.30 from March. "
        "Right: a collapse to 0.12 by November, a flat winter near 0.18, and a "
        "rise that only begins in May — reaching 0.34 at the very edge of the "
        "window, after the grower's 20 May termination date. NDVI sees green, "
        "not intent: neither panel can distinguish a sown cover crop from "
        "volunteer regrowth.")

# ========================================================== 13 threshold ====
s = slide("What the threshold costs",
          "The constant doing the work is CC_GREEN_MIN = 0.30.")
pic(s, "07_threshold.png", M, 2.30, w=6.4)
table(s, [["Threshold", "caught"], ["0.20", "99%"], ["0.25", "82%"],
          ["*0.30 — shipped", "*64%"], ["0.35", "41%"]],
      7.30, 2.40, 5.4, [3.0, 2.0])
text(s, [[("This slide cannot be used to pick a threshold.", True),
          (" With no labelled negatives, lowering it appears costless here — "
           "and the cost is precisely the thing this dataset cannot see.",
           False)]],
     7.30, 4.45, 5.4, 1.2, 12.5, ORANGE, spacing=1.36)

# ========================================================== 14 observations =
s = slide("Thin winters hide cover crops",
          "Detection tracks how many clear days the window contains.")
pic(s, "08_observations.png", M, 2.30, w=6.4)
text(s, [[("Fields with ten or fewer clear observations are detected ", False),
           ("35.7%", True), (" of the time. Fields with more than twenty are "
                             "detected ", False), ("88.5%", True),
           (" of the time — two and a half times the rate, on the same practice.",
            False)],
          [("The median winter here carries ", False), ("15", True),
           (" clear observations and the thinnest carries ", False), ("7", True),
           (". Seventeen of the 53 dates in the window had fewer than twenty of "
            "the 98 fields clear at once.", False)],
          [("Some of the 35 misses are a cloud record, not a farming record.",
            True)]],
     7.30, 2.40, 5.4, 3.2, 12.5, GRAY, spacing=1.36)

# ========================================================== 15 boundary =====
s = slide("Impure boundaries detect more, not less",
          "The opposite of what you would expect, and it matters.")
pic(s, "09_boundary_effect.png", M, 2.30, w=6.4)
text(s, [[("Boundaries the CDL check flags as holding more than one management "
           "unit are detected at ", False), ("83%", True),
           (". Clean single-unit boundaries are detected at ", False),
           ("56%", True), (".", False)],
          [("A boundary spilling into a grassed waterway, a field margin or a "
            "neighbour's ground collects winter green that does not belong to "
            "the field, and the average rises above the threshold.", False)],
          [("29 of these 98 boundaries are not a single management unit.", True),
           (" On this cohort that inflates apparent adoption rather than "
            "degrading it.", False)]],
     7.30, 2.40, 5.4, 3.2, 12.5, GRAY, spacing=1.36)

# ========================================================== 16 armor what ===
s = slide("Soil armor: a second, independent measurement",
          "Different bands, different physics, same imagery.")
text(s, [[("Everything so far came from ", False), ("NDVI", True),
          (" — greenness in the visible and near-infrared. Soil armor comes "
           "from the ", False), ("shortwave infrared", True),
          (", where cellulose and lignin absorb, and decomposes every pixel "
           "into three fractions that sum to one:", False)]],
     M, BODY_Y, 6.0, 1.2, 12.5, GRAY, spacing=1.34)
text(s, [[("living cover", True), (" — green canopy", False)],
          [("crop residue", True), (" — stubble, litter, a terminated cover crop",
                                    False)],
          [("bare soil", True)]],
     M, 3.55, 6.0, 1.0, 12.5, GRAY, bullet=True, spacing=1.30)
text(s, [[("Soil armor is one minus the bare fraction", True),
          (" — the share of the surface protected by anything at all.", False)]],
     M, 4.90, 6.0, 0.6, 12.5, GRAY, spacing=1.34)
_rect(s, 6.95, 2.18, 5.78, 2.30, WHITE, ORANGE, rounded=True, lw=1.5)
text(s, "It is not a tillage metric", 7.20, 2.36, 5.3, 0.3, 13, ORANGE, True, HEAD)
text(s, [[("The name invites that reading and the reading is wrong. Checked "
           "against 347 farmer-reported field-years, armor's apparent tillage "
           "signal ran almost entirely through ", False),
          ("cover crop adoption", True), (" instead.", False)],
          [("Report it as ground cover. A field under a living cover crop and a "
            "field under heavy stubble are both protected, and armor counts "
            "both.", False)]],
     7.20, 2.76, 5.28, 1.6, 11.5, GRAY, spacing=1.32)
text(s, "Method: NDVI–DFI ternary unmixing, after Guerschman et al. (2009) and "
        "Wang et al. (2019). The endmembers were fitted on eleven fields "
        "elsewhere and are provisional.",
     6.95, 4.62, 5.78, 0.8, 11, GRAY, spacing=1.32)

# ========================================================== 17 armor read ===
s = slide("Armor cannot always be read here",
          "It needs clear days in a narrow pre-planting window, and northern "
          "Illinois does not always supply them.")
pic(s, "12_armor_readable.png", M, 2.45, w=6.4)
text(s, [[("408 of 490 field-years", True), (" produced a reading — 83%.", False)],
          [("The failures are almost entirely too few clear dates: 72 of the 82 "
            "gaps are windows with ", False),
           ("one or two usable observations", True),
           (", below the minimum of three.", False)],
          [("2022 is the worst year at ", False), ("59%", True),
           (" readable, with a median of three observations per window. 2025 is "
            "the best at 98%.", False)]],
     7.30, 2.50, 5.4, 2.8, 12.5, GRAY, spacing=1.36)
text(s, [[("This is the same cloud problem that suppresses cover crop detection",
           True), (", now hitting a second metric — and the armor window is "
                   "narrower, so it bites harder.", False)]],
     7.30, 5.25, 5.4, 0.8, 12.5, ORANGE, spacing=1.34)

# ========================================================== 18 armor agree ==
s = slide("The two measurements agree with each other",
          "Spring 2026 ground cover against what NDVI concluded about the "
          "winter before it.")
pic(s, "13_armor_vs_verdict.png", M, 2.45, w=6.4)
table(s, [["Spring 2026", "armor", "n"],
          ["detector said cover crop", "*0.615", "56"],
          ["detector said none", "0.514", "25"]],
      7.30, 2.50, 5.4, [3.2, 1.1, 0.8])
text(s, [[("A gap of ", False), ("0.101", True), (", with ", False),
          ("AUC 0.83", True), (" (p < 0.001). Fields NDVI called cover-cropped "
                               "carry measurably more ground cover into spring.",
                               False)]],
     7.30, 3.95, 5.4, 0.9, 12.5, GRAY, spacing=1.34)
text(s, [[("This is consistency, not accuracy.", True),
          (" Both numbers come from the same satellite over the same field, and "
           "a weedy field looks green to one and covered to the other. "
           "Agreement rules out a coding error; it cannot rule out a shared "
           "confounder.", False)]],
     7.30, 4.90, 5.4, 1.3, 12.5, ORANGE, spacing=1.34)

# ========================================================== 19 armor why ====
s = slide("And they agree for the right reason",
          "The separation sits in living cover, not in residue.")
pic(s, "14_armor_fractions.png", M, 2.35, w=9.4)
text(s, [[("Residue is identical", True), (" between the two groups — 0.49 "
           "against 0.48. ", False), ("Living cover is four times higher", True),
           (" on the fields NDVI called: 0.11 against 0.03.", False)]],
     M, 5.10, 5.9, 1.0, 12.5, GRAY, spacing=1.34)
text(s, [[("That is the Georgia finding reproduced independently, in a "
           "different region, by a different measurement: ", False),
          ("what armor separates is cover crops, not tillage.", True)]],
     6.80, 5.10, 5.9, 1.0, 12.5, GRAY, spacing=1.34)
note(s, "Living cover is low in both groups because the window closes three "
        "days before planting and terminations ran to 20 May — by then much of "
        "a terminated cover crop has already become residue, where armor still "
        "counts it.")

# ========================================================== 20 assessment ===
s = slide("Does the data entry match what the satellite sees?",
          "Three separate answers, because the question has three parts.",
          kicker="Assessment", title_size=24)
table(s, [["Question", "Answer", "Basis"],
          ["*Does the entered practice match the imagery?", "*Partly — 64%",
           "63 of 98 fields show off-season green consistent with the recorded "
           "cover crop; 35 do not."],
          ["*Is the entry trustworthy where it exists?", "*Yes, and specific",
           "Sowing and termination dates are present on all 98 and are "
           "agronomically plausible for Illinois."],
          ["*Is the entry complete?", "*No",
           "Eighteen crop years carry no cover crop field at all. The project "
           "cannot show change over time from this export."]],
      M, 2.55, 12.09, [3.3, 2.1, 6.6], row_h=0.62)
text(s, [[("The disagreement is ", False), ("not", True),
          (" evidence that growers misreported. It is the expected result of "
           "comparing ", False), ("an action", True),
          (" — sown on this date, terminated on that one — against ", False),
          ("a biomass measurement", True),
          (" taken through cloud at 42° north.", False)]],
     M, 5.10, 12.09, 0.8, 12.5, GRAY, spacing=1.34)

# ========================================================== 21 readings =====
s = slide("Is 36% a detector failure, or a finding?",
          "Both readings survive this data. They have different consequences.")
_rect(s, M, 2.35, 5.84, 2.65, WHITE, BLUE, rounded=True, lw=1.5)
text(s, "Reading A — the threshold is wrong here", M + 0.25, 2.54, 5.3, 0.3,
     12, BLUE, True, HEAD)
text(s, [[("0.30 came from Mid-Atlantic work and was reused in the eastern Corn "
           "Belt. Northern Illinois has a shorter autumn window and heavier "
           "winter cloud. A regional threshold near 0.25 would recover 18 of "
           "the 35 misses.", False)],
          [("If true:", True), (" recalibration fixes it, and the project's "
                                "reported adoption is roughly right.", False)]],
     M + 0.25, 2.94, 5.34, 1.9, 11.5, GRAY, spacing=1.32)
_rect(s, 6.88, 2.35, 5.84, 2.65, WHITE, ORANGE, rounded=True, lw=1.5)
text(s, "Reading B — the stands did not establish", 7.13, 2.54, 5.3, 0.3,
     12, ORANGE, True, HEAD)
text(s, [[("A cover crop drilled on 19 October at this latitude may carry "
           "almost no biomass before dormancy. The grower reports an action; "
           "the satellite reports what grew.", False)],
          [("If true:", True), (" the satellite is measuring cover crop "
                                "performance, which is the more valuable "
                                "number — and 35 fields got less benefit than "
                                "the acreage implies.", False)]],
     7.13, 2.94, 5.34, 1.9, 11.5, GRAY, spacing=1.32)
text(s, "Only agronomic ground truth separates them: biomass cuts or "
        "percent-groundcover transects on a sample of these same fields, in "
        "the same spring.",
     M, 5.30, 12.09, 0.6, 13, BLUE, True, align=PP_ALIGN.CENTER, spacing=1.32)

# ========================================================== 22 limits =======
s = slide("What this study cannot tell you")
text(s, [[("Nothing about false alarms.", True),
           (" No field in this project is known to be without a cover crop, so "
            "specificity is unmeasured. Against a Georgia dataset that did "
            "carry negatives, the same detector reached 7.1% specificity — the "
            "opposite failure, and the reason the threshold should not simply "
            "be lowered.", False)],
          [("Nothing about adoption before 2025.", True),
           (" The payload history has no cover crop records, so the rising "
            "trend on slide 7 cannot be verified against anything.", False)],
          [("Nothing about species, biomass or termination quality.", True),
           (" NDVI sees green. It does not see what was planted, how much of it "
            "grew, or whether it was terminated on time.", False)],
          [("Nothing validated about planting and harvest dates.", True),
           (" The entered dates take only two to four distinct values per year "
            "across 98 fields — they are templates, not per-field "
            "observations.", False)],
          [("The soil armor caveat stands.", True),
           (" It is a cover measurement, not a tillage measurement, and this "
            "cohort cannot test it against tillage: 465 of 490 field-years "
            "report the identical pair of tillage operations.", False)]],
     M, BODY_Y, 12.09, 4.2, 12.5, GRAY, bullet=True, spacing=1.34)

# ========================================================== 23 next =========
s = slide("What would make the next run decisive")
cards(s, [("1", "Enter cover crops for prior years\nEven two retrospective "
                "winters per field would turn a one-sided test into a real one.",
           BLUE),
          ("2", "Identify fields with no cover crop\nTwenty confirmed negatives "
                "would measure the false alarm rate that this project cannot.",
           BLUE),
          ("3", "Spring biomass on a subsample\nTwenty fields, one visit, "
                "settles whether 36% is a threshold problem or a performance "
                "finding.", ORANGE)], y=2.30, h=2.05)
text(s, [[("Cheapest first.", True), (" Items 1 and 2 are data entry, not "
           "fieldwork, and together they would let the next run report an "
           "accuracy figure instead of a sensitivity figure.", False)]],
     M, 4.70, 5.8, 1.0, 12.5, GRAY, spacing=1.34)
text(s, [[("Also worth fixing:", True), (" 29 of 98 boundaries hold more than "
           "one management unit. Redrawing those is free, improves every number "
           "in this deck, and removes the inflation shown earlier.", False)]],
     6.90, 4.70, 5.8, 1.0, 12.5, GRAY, spacing=1.34)

# ========================================================== 24 close ========
s = slide(None, None, kicker="In one page")
_rect(s, M, 1.48, 0.055, 0.72, ORANGE)
text(s, "98 Illinois fields, all sown to a cover crop in autumn 2025. The "
        "satellite finds 63 of them.",
     M + 0.26, 1.48, 11.4, 0.8, 17, INK, spacing=1.34)
text(s, [[("The 35 it misses are not bare.", True),
           (" Every one shows green between NDVI 0.19 and 0.29 — under a "
            "threshold borrowed from a milder region.", False)],
          [("Winter cloud explains part of it.", True),
           (" Fields with more than twenty clear days are detected two and a "
            "half times more often than fields with ten or fewer.", False)]],
     M, 2.80, 5.8, 1.8, 12.5, GRAY, spacing=1.36)
text(s, [[("The project's data entry is accurate where it exists and absent "
           "everywhere else.", True),
           (" One winter of 98 positives, no negatives, eighteen blank years.",
            False)],
          [("The pipeline itself held up.", True),
           (" 98 fields, 88 minutes, no failures, on boundaries it had never "
            "seen.", False)]],
     6.90, 2.80, 5.8, 1.8, 12.5, GRAY, spacing=1.36)
text(s, "The honest headline is not an accuracy number. It is that a national "
        "threshold cannot serve northern Illinois and the Deep South at the "
        "same time, and this project is now the northern half of the evidence.",
     M, 5.05, 12.09, 0.9, 14, BLUE, True, spacing=1.36)

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(str(OUT))
n = len(prs.slides._sldIdLst)
print("wrote %s  (%d slides, %.0f KB)" % (OUT, n, OUT.stat().st_size / 1024))
if n > 30:
    print("WARNING: over the 30-slide ceiling")
    sys.exit(1)
