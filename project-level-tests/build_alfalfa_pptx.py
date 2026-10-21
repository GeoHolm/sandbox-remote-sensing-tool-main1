#!/usr/bin/env python3
"""The New Mexico alfalfa cutting study as an editable .pptx.

    python project-level-tests/build_alfalfa_pptx.py

The same fourteen slides as the PDF, but every heading, paragraph, bullet,
card and table is a real PowerPoint object rather than a picture, so the text
can be edited. Only the charts are images.

Layout is top-aligned rather than vertically centred: PowerPoint has no flex
box, and a deck someone is about to edit should not shift its whole body every
time a line is added.

Helpers follow build_flash_pptx.py so the two decks stay one family.

Ends with a fit check over text boxes, pictures AND tables. On the Illinois
deck the checker looked at text boxes only, and three pictures ran into the
footnote band and the brand bar without it noticing.
"""
import sys
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJ = HERE / "alfalfa-nm"
FIG = PROJ / "figures" / "deck"
BRAND = REPO / "pitch" / "branding-assets"
OUT = PROJ / "NewMexico-Alfalfa-Cuttings.pptx"

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

summ = pd.read_csv(PROJ / "cutting_summary.csv")

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


def cards(s, items, y=2.30, h=1.42, big_size=34):
    """items: list of (big, label, color)."""
    n = len(items)
    gap = 0.20
    w = (W - 2 * M - gap * (n - 1)) / n
    for i, (big, lab, col) in enumerate(items):
        x = M + i * (w + gap)
        _rect(s, x, y, w, h, WHITE, col, rounded=True, lw=1.5)
        text(s, big, x + 0.22, y + 0.17, w - 0.44, 0.60,
             big_size if len(big) < 11 else 20, col, True, HEAD, spacing=1.0)
        text(s, lab, x + 0.22, y + 0.80, w - 0.44, h - 0.94, 10.5, GRAY,
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
            p.alignment = PP_ALIGN.LEFT if j < 2 else PP_ALIGN.CENTER
            strong = val.startswith("*")
            flag = val.endswith("~")
            r = p.add_run(); r.text = val.lstrip("*").rstrip("~")
            r.font.size = Pt(size)
            r.font.bold = (i == 0) or strong
            r.font.name = HEAD if i == 0 else TEXT
            r.font.color.rgb = (WHITE if i == 0 else
                                ORANGE if flag else
                                BLUE if strong else RGBColor(0x44, 0x44, 0x44))
    return shp


def pic(s, name, x, y, w=None, h=None):
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    return s.shapes.add_picture(str(FIG / name), Inches(x), Inches(y), **kw)


def centered(s, name, y, h):
    """Place a figure centred horizontally at a given height."""
    p = pic(s, name, 0, y, h=h)
    p.left = Inches((W - p.width / Inches(1)) / 2)
    return p


RCOL = 7.55
RW = W - M - RCOL

# ========================================================== 1 cover ========
s = slide(logo=False)
s.shapes.add_picture(str(BRAND / "FTM-H_wTAG_rgb.png"), Inches(M),
                     Inches(0.70), width=Inches(4.4))
text(s, ["Counting alfalfa cuttings", "from orbit"], M, 2.45, 11.0, 1.6, 42,
     BLUE, True, HEAD, spacing=1.06)
_rect(s, M, 4.30, 2.1, 0.06, ORANGE)
text(s, [[("One 62-acre field in northwestern New Mexico, read from free "
           "satellite imagery. The pipeline was built to find one planting "
           "and one harvest a year. This field is cut ", False),
          ("three to four times every summer", True),
          (" — and the imagery shows every one.", False)]],
     M, 4.62, 9.2, 0.9, 14, GRAY, spacing=1.40)
text(s, "Field to Market remote sensing demonstration   ·   713 clear "
        "observations, January 2020 to September 2026   ·   analysis run "
        "19 October 2026", M, 6.35, 11.0, 0.3, 10.5, MUTED)
notes(s, "One alfalfa field in San Juan County, New Mexico. Everything here "
         "comes from free satellite imagery; nobody visited the field and no "
         "grower was asked.")

# ========================================================== 2 the field ====
s = slide("One field, seven years",
          "A single management unit: on average 100% of the boundary is one "
          "crop, so the curves below belong to the whole field and not to an "
          "average of two.")
cards(s, [("62", "acres (25.2 ha)\nSan Juan County, New Mexico", BLUE),
          ("713", "cloud-free observations\nJan 2020 – Sep 2026", BLUE),
          ("3 days", "typical gap between\nclear images", BLUE),
          ("Wheat → Alfalfa", "winter wheat 2020–21,\nalfalfa 2022 onward",
           ORANGE)])
text(s, [[("The crop changed in 2022. ", True),
          ("USDA's Cropland Data Layer records winter wheat in 2020 and 2021, "
           "then alfalfa from 2022 onward, at 99.6–100% purity every year. "
           "That rotation is what makes this field useful: it contains its "
           "own control.", False)]], M, 4.10, 5.85, 1.6)
text(s, [[("Density is the whole story. ", True),
          ("An image every three days is what makes a cutting visible at all. "
           "A crop that is mown and regrows inside five weeks is invisible to "
           "a sensor that passes monthly — the field would simply look green "
           "all summer.", False)]], 6.95, 4.10, 5.76, 1.6)
note(s, "Crop type from the USDA Cropland Data Layer (30 m). Greenness from "
        "Sentinel-2 surface reflectance (10 m), cloud-masked. Boundary "
        "supplied with the report pack; no field visit and no grower input.")

# ========================================================== 3 location ====
s = slide("Where the field is",
          "San Juan County, New Mexico — the irrigated valley northwest of "
          "Farmington, at about 1,600 m.")
centered(s, "07_location.png", 1.78, 3.52)
text(s, [[("It is a center pivot", True),
          (" — a 122-acre irrigated circle, wheel tracks and center point "
           "visible. That is why the water goes on so regularly, and why the "
           "cutting schedule is so steady.", False)]], M, 5.46, 5.85, 1.0, 12)
text(s, [[("The orange box is drawn, not surveyed: ", True),
          ("a hand-drawn rectangle covering ", False), ("51% of the pivot", True),
          (", well inside the circle. It never touches the dry corners, which "
           "is why the crop layer reads 100% one crop — and it means every "
           "number here describes half a pivot.", False)]],
     6.95, 5.46, 5.76, 1.0, 12)
notes(s, "The boundary came with the report pack as an axis-aligned rectangle "
         "with field_id 'drawn'. The aerial imagery shows it sits inside a "
         "center pivot and covers about half of it.")

# ========================================================== 4 the hero =====
s = slide("What a cutting looks like from space")
centered(s, "01_sawtooth_2023.png", 1.72, 4.70)
note(s, "A full alfalfa canopy reads about 0.93 on the greenness index. Within "
        "days of mowing, the same field reads 0.32 — bare stubble and windrows. "
        "Then it regrows and the pattern repeats. The two narrow spikes in "
        "August and late September are cloud shadow, not cuttings, and are "
        "rejected: see slide 9.")
notes(s, "The hero chart. Four cuttings in 2023, each one a fall from full "
         "canopy to stubble inside a single revisit gap.")

# ========================================================== 5 the count ====
s = slide("Three to four cuttings a year, every year",
          "Fifteen cuttings detected across five alfalfa seasons. The two "
          "wheat years, read by the identical method, give one biomass "
          "removal each — the grain harvest.")
cards(s, [("3–4", "cuttings per complete\nalfalfa season", ORANGE),
          ("43 days", "median between cuttings\n(range 33 – 62)", BLUE),
          ("4–15 Jun", "first cutting, all five years\nan 11-day spread", BLUE),
          ("0.93 → 0.48", "typical greenness\nacross a cutting", BLUE)],
      y=2.34, h=1.34)
rows = [["Year", "Crop (USDA)", "Cuttings", "First to last", "Mean gap (days)"]]
for _, r in summ.iterrows():
    crop = r.crop if isinstance(r.crop, str) else "not yet published"
    n = int(r.cuttings)
    cnt = "%d%s" % (n, "  (%d flagged)" % int(r.cuttings_flagged)
                    if r.cuttings_flagged else "")
    span = ("—" if n < 2 else
            "%s – %s" % (pd.to_datetime(r.first_cut).strftime("%d %b"),
                         pd.to_datetime(r.last_cut).strftime("%d %b")))
    gap = "—" if pd.isna(r.mean_regrowth_days) else "%.0f" % r.mean_regrowth_days
    rows.append(["*%d" % r.year, crop,
                 cnt + ("~" if r.cuttings_flagged else ""), span, gap])
table(s, rows, M, 4.00, W - 2 * M, [1.0, 2.0, 1.5, 1.6, 1.5], row_h=0.305)
note(s, '"Flagged" marks a cutting detected after 1 October, when a hard '
        "freeze would produce the same signature. It is counted and labeled, "
        "not hidden.")

# ========================================================== 6 every year ===
s = slide("The same rhythm, year after year")
centered(s, "02_all_years.png", 1.68, 4.78)
note(s, "2026 is a part year, running to 20 September. Dashed lines are the "
        "flagged late-season cuttings.")

# ========================================================== 7 calendar =====
s = slide("A cutting calendar, built without visiting the farm")
centered(s, "04_cutting_calendar.png", 1.62, 3.72)
text(s, [[("The schedule is remarkably stable. ", True),
          ("First cutting between 4 and 15 June in all five years, then "
           "roughly every six weeks until the stand goes dormant.", False)]],
     M, 5.60, 5.85, 0.9, 12)
text(s, [[("2024 is the exception", True),
          (" — three cuttings, with 48- and 52-day gaps where other years run "
           "33 to 45. Something stretched the cycle that summer. The imagery "
           "shows that it happened; it cannot say why.", False)]],
     6.95, 5.60, 5.76, 0.9, 12)

# ========================================================== 8 the control ==
s = slide("The method did not know which crop it was looking at",
          "Same field, same algorithm, same constants. Only the crop changed.")
centered(s, "03_wheat_vs_alfalfa.png", 2.08, 4.28)
note(s, "This is the closest thing to a control available without a grower "
        "record: a field that grew an annual grain and then a perennial "
        "forage, read by one unchanged method. One removal in the wheat "
        "years, four in the alfalfa year.")

# ========================================================== 9 regrowth =====
s = slide("The biology is visible too")
pic(s, "05_regrowth.png", M, 1.78, w=6.55)
text(s, "WHAT THE CURVE SAYS", RCOL, 1.78, RW, 0.26, 9.5, ORANGE, True, HEAD,
     spacing=1.0)
text(s, [[("Fifteen days from stubble back to full canopy", True),
          (", as a median across all fifteen cuttings. The regrowth curves sit "
           "almost on top of one another — this stand behaves the same way "
           "every time it is cut.", False)],
         [("Then it waits. ", True),
          ("The median gap between cuttings is 43 days, but the canopy is full "
           "again by day 15. The remaining four weeks are the grower letting "
           "the stand build yield before mowing again.", False)],
         [("The one flat track ", True),
          ("near 0.47 is a late-October cutting that never regrows, because "
           "the stand is going dormant.", False)]],
     RCOL, 2.16, RW, 3.4, 12.5)
note(s, '"Full canopy" is a greenness of 0.80, the level this stand plateaus '
        "at through the summer. Each track stops at the next cutting.")

# ========================================================= 10 method =======
s = slide("Telling a cutting from a cloud",
          "A fall in greenness is not enough on its own. Four tests, each one "
          "added because a real case in this field's own record defeated the "
          "rule before it.")
table(s, [["Test", "What it requires", "The case that put it there"],
          ["*Standing", "Greenness above 0.60 before the fall",
           "Dormant winter regrowth oscillates around 0.45 and is not a crop "
           "anyone cuts."],
          ["*Step", "A drop of 0.30 or more, measured from the last standing "
           "observation, completed within 12 days",
           "A mature stand sits near its peak for weeks before it is cut. "
           "Measuring from the seasonal peak instead turned the 7-day first "
           'cutting of 2023 into a "27-day senescence" and missed it entirely.'],
          ["*Persistent", "The low holds across at least two clear observations",
           "On 12 August 2023 the field reads 0.49 between a 0.90 and a 0.93 "
           "five days later. Alfalfa cannot regrow a canopy in five days — "
           "that is cloud shadow. Without this test 2023 reads six cuttings "
           "instead of four."],
          ["*Spaced", "At least 18 days since the previous cutting",
           "A stand needs about a month to regrow; two cuttings a fortnight "
           "apart would be one event counted twice."]],
      M, 2.26, W - 2 * M, [1.3, 3.4, 5.2], size=11, row_h=0.90)
note(s, "Cloud is judged on the share of FIELD pixels that survived masking, "
        "not the scene cloud percentage: five of the twenty detected falls sit "
        "under scenes 14–34% clouded, and the field itself is clear in every "
        "one.")

# ====================================================== 11 annual model ====
s = slide("What an annual-crop model makes of a perennial",
          "This is the finding that matters for the people building the "
          "production pipeline.")
centered(s, "06_pipeline_vs_cuttings.png", 2.12, 4.22)
note(s, 'The pipeline reports one planting and one harvest per year. On this '
        'field its "harvest" lands on the first cutting in 2023, the second in '
        "2026, the third in 2025, and on nothing at all in 2022 and 2024 — and "
        "the season it reports swings from 63 to 264 days on an unchanging "
        "crop.")

# ====================================================== 12 off-season ======
s = slide("A perennial has no off-season, so two of our metrics stop "
          "meaning anything")
text(s, "COVER CROP", M, 1.82, 5.85, 0.26, 9.5, ORANGE, True, HEAD, spacing=1.0)
text(s, [[("Of the five winters from 2021–22 onward, the pipeline calls four "
           "a ", False), ("likely cover crop", True),
          (" and the fifth a possible one. There is no cover crop. There is "
           "alfalfa, which was there in August and is still there in "
           "December.", False)],
         [("The clearest case is winter 2023–24, scored on an \"off-season\" "
           "greenness peak of ", False), ("0.94 on 6 October", True),
          (". That is not a cover crop establishing. It is the standing hay "
           "crop, five days before the fourth cutting.", False)]],
     M, 2.20, 5.85, 2.6)
text(s, "SOIL ARMOR BEFORE PLANTING", 6.95, 1.82, 5.76, 0.26, 9.5, ORANGE,
     True, HEAD, spacing=1.0)
text(s, [[("The pre-planting window runs from last year's harvest to this "
           "year's planting. On a perennial there is no planting, so in ",
           False), ("2024 and 2026 the window collapses to nothing", True),
          (" and no figure is produced at all.", False)],
         [("Where a figure does appear it is not wrong so much as beside the "
           "point: March 2025 reads 0.97 covered, 96% of it classed as "
           "residue. That is a dormant alfalfa stand, not last year's crop "
           "residue.", False)]], 6.95, 2.20, 5.76, 2.6)
_rect(s, M, 5.10, 0.05, 0.56, ORANGE)
text(s, "Neither metric is broken. Both were defined for a crop that is "
        "planted and harvested once a year, and this field is not one.",
     M + 0.22, 5.14, 11.6, 0.5, 14, INK, spacing=1.40)

# ====================================================== 13 caveats =========
s = slide("What this is not")
text(s, [[("No cutting record has ever been checked against this. ", True),
          ("Not for this field, not for any field. Every count in this deck is "
           "read from the shape of a curve. The pattern is strong and the "
           "biology is consistent, but no accuracy figure exists and none is "
           "quoted here.", False)],
         [("Autumn is genuinely ambiguous. ", True),
          ("Three of the fifteen cuttings fall after 1 October, when a hard "
           "freeze would take a canopy down the same way. They are flagged "
           "throughout rather than quietly counted or quietly dropped.", False)],
         [("Dates carry a window, not a day. ", True),
          ("A cutting is placed between the last clear image showing a "
           "standing crop and the first showing stubble — a median of 10 days "
           "apart. That window is set by cloud and revisit, not by the "
           "method.", False)],
         [("The thresholds were tuned on this one field. ", True),
          ("Four tests and seven constants, read against this field's own 2023 "
           "season and then left alone across the other six years. That is a "
           "demonstration, not a validated model.", False)],
         [("One field is one field — and only half a pivot of it. ", True),
          ("Everything here is a drawn rectangle covering 51% of one center "
           "pivot in one irrigated valley. A boundary taken out to the pivot "
           "edge would include the wetted margin and the dry corners, and "
           "would not behave the same way.", False)]],
     M, 1.90, W - 2 * M, 4.6, 13, bullet=True, spacing=1.36)

# ====================================================== 14 what's next =====
s = slide("Why it is worth doing properly")
text(s, "WHAT THIS WOULD UNLOCK", M, 1.82, 5.85, 0.26, 9.5, ORANGE, True,
     HEAD, spacing=1.0)
text(s, [[("Forage is a blind spot. ", True),
          ("Hay and alfalfa are poorly served by metrics built around a single "
           "annual harvest, and they are a large share of irrigated acreage in "
           "the West.", False)],
         [("Cutting count and timing are the management signal. ", True),
          ("How many times a stand is cut, and how long it is allowed to "
           "recover, is most of what distinguishes one alfalfa operation from "
           "another.", False)],
         [("It needs no new data. ", True),
          ("Every number here came from imagery the pipeline already downloads "
           "for every field it touches.", False)]], M, 2.20, 5.85, 3.0)
text(s, "WHAT IT WOULD TAKE TO TRUST IT", 6.95, 1.82, 5.76, 0.26, 9.5, ORANGE,
     True, HEAD, spacing=1.0)
text(s, [[("One season of real cutting dates. ", True),
          ("A grower's log for ten alfalfa fields over one summer would be "
           "enough to measure, for the first time, whether the count is right "
           "and how close the dates land.", False)],
         [("A perennial path through the pipeline. ", True),
          ("Detect the crop as perennial from the Cropland Data Layer, then "
           "skip planting, harvest, cover crop and pre-planting armor, and "
           "report a cutting series instead.", False)],
         [("Fields outside this valley. ", True),
          ("Rain-fed and shorter-season stands, to see whether constants "
           "fitted here travel at all.", False)]], 6.95, 2.20, 5.76, 3.0)
_rect(s, M, 5.52, 0.05, 0.56, ORANGE)
text(s, "The pipeline found something it was never designed to look for. "
        "That is worth a validation season.", M + 0.22, 5.56, 11.6, 0.5, 14,
     INK, spacing=1.40)

# ============================================================ fit check ====
prs.save(OUT)

LIMIT = FTR_Y - 0.04          # nothing may cross into the brand bar
NOTE_TOP = NOTE_Y - 0.06      # nor into the footnote band, if there is one
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
        # Classify on shape_type, not has_text_frame: an autoshape reports
        # has_text_frame True, so testing that first labelled the white
        # background rectangle and all six brand-bar segments as overflowing
        # text and buried the real findings.
        st = int(sh.shape_type) if sh.shape_type is not None else -1
        kind = {13: "picture", 19: "table", 17: "text",
                1: "shape"}.get(st, "shape")
        if kind == "shape":
            # the page background and the brand bar are meant to reach the edge
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
