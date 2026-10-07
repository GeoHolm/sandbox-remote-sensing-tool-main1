# FTM Brand Reference
**Field to Market — Brand Guide v1.0, January 2026**

---

## Color Palette

| Variable | Hex | Name | Role | Bar % |
|----------|-----|------|------|-------|
| `FTM_BLUE` | `#10427c` | Deep Current | Primary | 40% |
| `FTM_ORANGE` | `#f46c09` | Ember Glow | Primary | 40% |
| `FTM_GREEN` | `#00b14c` | Meadow Pulse | Accent | 5% |
| `FTM_TEAL` | `#0d9ac6` | Sky Drift | Accent | 5% |
| `FTM_PURPLE` | `#462668` | Twilight Bloom | Accent | 5% |
| `FTM_YELLOW` | `#ffd103` | Solar Bloom | Accent | 5% |

### Brand Color Bar
The 6 colors appear left-to-right in the proportions above as a decorative header or footer strip.

```
████████████████████████████████████████ ████████████████████████████████████████ ████ ████ ████ ████
     Deep Current #10427c (40%)               Ember Glow #f46c09 (40%)            5%   5%   5%   5%
```

### Neutral / UI Colors

| Variable | Hex | Name | Use |
|----------|-----|------|-----|
| `FTM_GRAY` | `#58595b` | Iron Whisper | Body text |
| `FTM_LTGRAY` | `#eeeeee` | — | Code box / table backgrounds |
| `FTM_DKGRAY` | `#444444` | — | Code text inside boxes |
| `FTM_BLACK` | `#212121` | Night Spark | Heading text |
| `FTM_WHITE` | `#ffffff` | — | Text on dark backgrounds |

---

## Typography

| Role | Official Font | System Substitute |
|------|--------------|-------------------|
| Headlines | Trade Gothic Next LT Pro Heavy Condensed | **Arial Narrow Bold** |
| Body | Trade Gothic Next LT Pro | **Arial** |
| Code | — | **Courier New** |

> **Local font file (Windows):** `C:/Windows/Fonts/ARIALNB.TTF` (Arial Narrow Bold)
> The brand guide explicitly allows Arial as the system substitute when Trade Gothic is unavailable.

---

## Canvas Dimensions (magick / PNG output)

| Constant | Value | Notes |
|----------|-------|-------|
| `FTM_CANVAS_W` | `4000` px | Widescreen 16:9 |
| `FTM_CANVAS_H` | `2250` px | |
| `FTM_CANVAS_DPI` | `300` | Print-quality |
| `FTM_CANVAS_HEADER_H` | `150` px | Brand bar height at top |
| `FTM_CANVAS_FOOTER_H` | `110` px | Brand bar height at bottom |
| `FTM_CANVAS_PAD` | `14` px | Padding around each logo cell |

---

## PowerPoint Slide Dimensions (officer)

| Constant | Value | Notes |
|----------|-------|-------|
| `FTM_SLIDE_W` | `13.333"` | Widescreen 16:9 |
| `FTM_SLIDE_H` | `7.5"` | |
| `FTM_SLIDE_EMU_W` | `12192000` | EMU = inches × 914400 |
| `FTM_SLIDE_EMU_H` | `6858000` | |
| `FTM_HDR_H` | `1.25"` | Blue header bar height |
| `FTM_FTR_H` | `0.38"` | Brand footer strip height |
| `FTM_FTR_Y` | `7.12"` | Footer y-start (SH − FTR_H) |

---

## Standard Slide Layout (recommendation slides)

```
┌─────────────────────────────────────────────────────────┐ y=0
│  [BLUE HEADER — full width, 1.25"]                      │
│  REC ##  Title Text                                      │ y=1.25
├──────────────────────────────────┬──────────────────────┤
│  Left body (x=0.40, w=7.80)      │  Right panel         │
│                                  │  (x=8.55, w=4.45)    │
│  THE PROBLEM                     │  ┌────────────────┐  │
│  • bullet                        │  │  Code box      │  │
│  • bullet                        │  │  (Courier New) │  │
│                                  │  └────────────────┘  │
│  THE SOLUTION                    │  [EFFORT  badge]      │
│  • bullet                        │  [IMPACT  badge]      │
│  • bullet                        │  [PRIORITY badge]     │
├──────────────────────────────────┴──────────────────────┤ y=7.12
│  ████████████████████████ ██████████████████ ██ ██ ██ ██│ footer
└─────────────────────────────────────────────────────────┘ y=7.50
```

---

## R Source File

All constants and helper functions are available by sourcing:

```r
source("ftm_brand.R")
```

### Helper Functions

| Function | Description |
|----------|-------------|
| `ftm_brand_bar_magick(w, h)` | Returns a magick image of the 6-color brand bar at the given pixel dimensions |
| `ftm_add_footer_strip_officer(doc)` | Appends the 6-color footer strip to an officer pptx object |
| `ftm_pick_logo(folder)` | Returns path to best logo in a folder (`_primary_` prefix → white-avoidance heuristic → random) |
| `ftm_fix_pptx_boxes(path)` | Post-processes a saved PPTX: fixes widescreen slide size + colored-box rendering (officer 0.7.x bug workaround) |

---

## Known officer / PPTX Issues & Fixes

### 1. `fp_par` parameter names changed in officer 0.7.x
```r
# WRONG (throws "unused arguments" error):
fp_par(space_before = 0, space_after = 4)

# CORRECT:
fp_par(padding.top = 0, padding.bottom = 4)
```

### 2. Colored boxes not rendering (officer 0.7.x)
`ph_location(bg = "#10427c")` writes the fill to XML correctly, but the `<p:ph/>` placeholder tag causes PowerPoint to override it with the slide master's transparent style.

**Fix:** call `ftm_fix_pptx_boxes(OUT)` after `print(doc, target = OUT)`.

### 3. Default slide size is 4:3, not widescreen
`read_pptx()` creates a 10" × 7.5" slide. All FTM layouts use SW = 13.333".

**Fix:** also handled automatically by `ftm_fix_pptx_boxes()`.

### 4. Multi-line `Rscript -e` segfaults on Windows
Write R code to a temp `.R` file and run `Rscript path/to/file.R` instead.

---

## Project Files

| File | Description |
|------|-------------|
| `ftm_brand.R` | Sourceable R file — all constants + helper functions |
| `ftm_brand.md` | This file — human-readable reference |
| `build_logo_canvas.R` | Builds all-member canvas + Grower Sector canvas |
| `build_recommendations_deck.R` | Builds 14-slide enhancement recommendations PPTX |
| `FTM_Member_Logos_Canvas.png` | All-member canvas (85 logos, 4000×2250 @300dpi) |
| `FTM_Member_Logos_Canvas_Grower_Sector.png` | Grower sector canvas (12 logos) |
| `FTM_Logo_Repo_Recommendations.pptx` | 14-slide deck for colleague conversation |
| `FTM_Brand Guidelines_011626.pdf` | Official brand guide source |

---

## Folder Structure Notes

- **Working directory:** `C:/Users/EricCoronel/Field to Market/FTM Staff Team - Current Member Logos/`
- **86 member subfolders** — naming convention: `OrgName_Logos/`
- **141 loose files** in root (improvement rec: move into subfolders)
- **DAS_Logos** — EPS files only; skipped (Ghostscript not installed)
- **NECGA_Logos** — contains two orgs: NECGA + Nebraska Corn Board (`NCB_Logo2.jpg`)
