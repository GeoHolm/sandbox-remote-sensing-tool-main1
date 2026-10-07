#!/usr/bin/env python
"""Render METHODS.md as a branded PDF.

    python pitch/build_methods_pdf.py

Two steps, because nothing here can do it in one: pandoc converts the Markdown
to an HTML fragment, and headless Edge prints that to PDF. There is no LaTeX,
wkhtmltopdf or weasyprint on this machine, and Chromium's print engine handles
the paged-media CSS below correctly.

Branding follows pitch/branding-assets/ftm_brand.md. The six-colour bar is one
linear-gradient with hard stops at the stated 40/40/5/5/5/5 proportions, in a
fixed element so Chromium repeats it on every printed page.
"""
from __future__ import annotations

import base64
import subprocess
import time
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "METHODS.md"
BRAND = REPO / "pitch" / "branding-assets"
OUT_HTML = REPO / "pitch" / "_methods.html"
OUT_PDF = REPO / "pitch" / "Field-to-Market-Remote-Sensing-Methods.pdf"

PANDOC = Path(r"C:\Program Files\RStudio\resources\app\bin\quarto\bin\tools\pandoc.exe")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

BAR = ("linear-gradient(to right,"
       "#10427c 0 40%,#f46c09 40% 80%,#00b14c 80% 85%,"
       "#0d9ac6 85% 90%,#462668 90% 95%,#ffd103 95% 100%)")

CSS = """
@page { size: A4; margin: 19mm 17mm 20mm 17mm; }

:root {
  --blue:#10427c; --orange:#f46c09; --green:#00b14c; --teal:#0d9ac6;
  --purple:#462668; --yellow:#ffd103; --gray:#58595b; --ltgray:#eeeeee;
  --dkgray:#444444; --black:#212121;
}

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9.6pt; line-height: 1.55; color: var(--gray);
  margin: 0; hyphens: none;
}

/* Repeated on every printed page by Chromium. */
.brandbar { position: fixed; left: 0; right: 0; bottom: 0; height: 5.5mm;
            background: __BAR__; }
.runfoot  { position: fixed; left: 0; right: 0; bottom: 6.5mm;
            font-size: 7pt; color: #8a8c8e; letter-spacing: .02em; }

h1, h2, h3, h4 {
  font-family: "Arial Narrow", Arial, sans-serif;
  color: var(--blue); font-weight: bold; line-height: 1.18;
  margin: 0 0 .35em; break-after: avoid;
}
h2 { font-size: 19pt; margin-top: 0; padding-top: 0;
     border-top: 2.5px solid var(--orange); padding-top: 5mm; break-before: page; }
h3 { font-size: 13pt; margin-top: 1.5em; color: var(--black); }
h4 { font-size: 10.5pt; margin-top: 1.2em; color: var(--dkgray);
     text-transform: uppercase; letter-spacing: .06em; }
p  { margin: 0 0 .7em; }
strong { color: var(--black); }
a { color: var(--blue); }

code { font-family: "Courier New", monospace; font-size: 8.6pt;
       background: var(--ltgray); color: var(--dkgray);
       padding: .5pt 2.5pt; border-radius: 2px; }
pre  { background: var(--ltgray); border-left: 3px solid var(--blue);
       padding: 3.5mm 4mm; overflow-x: hidden; break-inside: avoid;
       margin: 0 0 1em; }
pre code { background: none; padding: 0; font-size: 8.4pt; line-height: 1.45; }

table { border-collapse: collapse; width: 100%; margin: .3em 0 1.1em;
        font-size: 8.8pt; break-inside: avoid; }
th { background: var(--blue); color: #fff; text-align: left;
     font-family: "Arial Narrow", Arial, sans-serif; font-weight: bold;
     padding: 2.4mm 2.6mm; font-size: 9pt; }
td { padding: 1.9mm 2.6mm; border-bottom: .5px solid #dcdcdc;
     vertical-align: top; }
tr:nth-child(even) td { background: #f7f7f7; }

blockquote { margin: 0 0 1.1em; padding: 3mm 4mm; background: #fdf1e8;
             border-left: 3px solid var(--orange); break-inside: avoid; }
blockquote p:last-child { margin-bottom: 0; }

ul, ol { margin: 0 0 .8em; padding-left: 5mm; }
li { margin-bottom: .3em; }
hr { border: none; border-top: .5px solid #d8d8d8; margin: 1.6em 0; }

/* ---- cover ---- */
.cover { height: 247mm; display: flex; flex-direction: column;
         justify-content: space-between; break-after: page; }
.cover img { width: 68mm; }
.cover h1 { font-size: 33pt; color: var(--blue); margin: 0 0 4mm;
            line-height: 1.1; }
.cover .rule { width: 34mm; height: 1.6mm; background: var(--orange);
               margin: 0 0 6mm; }
.cover .sub { font-size: 12pt; color: var(--gray); line-height: 1.5;
              max-width: 132mm; }
.cover .meta { font-size: 8.6pt; color: #8a8c8e; }
.cover .warn { font-size: 9pt; background: #fdf1e8; border-left: 3px solid
               var(--orange); padding: 3.5mm 4mm; max-width: 150mm; }
.toc { font-size: 9.2pt; }
.toc td { border: none; padding: 1.3mm 0; }
.toc td:first-child { color: var(--orange); font-weight: bold; width: 9mm;
                      font-family: "Arial Narrow", Arial, sans-serif; }
"""

HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Field to Market \u2014 Remote Sensing Methods</title>
<style>__CSS__</style></head><body>
<div class="brandbar"></div>
<div class="runfoot">Field to Market \u00b7 Remote Sensing Methods \u00b7 __DATE__</div>

<div class="cover">
  <img src="data:image/png;base64,__LOGO__" alt="Field to Market">
  <div>
    <h1>Remote Sensing<br>Methods Reference</h1>
    <div class="rule"></div>
    <p class="sub">Every formula, constant and chart in the field remote
    sensing pipeline, written to be checked rather than run.</p>
  </div>
  <div class="warn"><strong>Almost nothing here is calibrated.</strong> The
  exceptions are CDL crop labels, soil armor and cover crop detection, tested
  against a 347-field-year Georgia farmer survey. Every constant fitted on this
  library was fitted on eleven fields. Section 10 lists what not to quote
  without its caveat.</div>
  <table class="toc"><tbody>__TOC__</tbody></table>
  <div class="meta">__DATE__ \u00b7 Generated from METHODS.md \u00b7
  github.com/Field-to-Market/sandbox-remote-sensing-tool</div>
</div>
__BODY__
</body></html>
"""

SECTIONS = [
    ("1", "Imagery: from COG to reflectance"),
    ("2", "Spectral indices"),
    ("3", "Smoothing: the daily curve"),
    ("4", "Soil armor: NDVI\u2013DFI ternary unmixing"),
    ("5", "Phenology: planting and harvest"),
    ("6", "Off-season windows"),
    ("7", "Cover crop detection"),
    ("8", "Crop type: USDA CDL"),
    ("9", "Charts"),
    ("10", "Numbers not to quote without their caveat"),
    ("11", "External endpoints"),
]


def main() -> int:
    for tool, name in ((PANDOC, "pandoc"), (EDGE, "Edge")):
        if not tool.exists():
            print(f"{name} not found at {tool}")
            return 1

    frag = subprocess.run(
        [str(PANDOC), str(SRC), "-f", "gfm", "-t", "html", "--wrap=none"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout

    # The Markdown opens with an H1 and a preamble that the cover already says;
    # drop everything before the first section so the body starts at "## 1.".
    cut = frag.find('<h2 id="1-imagery')
    if cut > 0:
        frag = frag[cut:]

    logo = base64.b64encode((BRAND / "FTM-H_wTAG_rgb.png").read_bytes()).decode()
    date = "September 2026"
    toc = "".join(f"<tr><td>{n}</td><td>{t}</td></tr>" for n, t in SECTIONS)

    html = (HTML.replace("__CSS__", CSS.replace("__BAR__", BAR))
                .replace("__LOGO__", logo).replace("__TOC__", toc)
                .replace("__DATE__", date).replace("__BODY__", frag))
    OUT_HTML.write_text(html, encoding="utf-8")

    OUT_PDF.unlink(missing_ok=True)
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu",
                    "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=10000",
                    f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
                   capture_output=True, timeout=180)

    # Edge detaches and finishes writing after the launcher process returns,
    # so a single exists() check straight afterwards loses a race it usually
    # wins and sometimes does not. It reported failure on a run that had in
    # fact produced a correct 19-page PDF -- and since the old file is
    # unlinked above, believing that message means believing the PDF is gone
    # when it is sitting right there. Wait for the file to appear and stop
    # growing before judging.
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
        return 1
    if "--keep-html" in sys.argv:
        print(f"kept {OUT_HTML}")
    else:
        OUT_HTML.unlink(missing_ok=True)
    print(f"wrote {OUT_PDF}  ({OUT_PDF.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
