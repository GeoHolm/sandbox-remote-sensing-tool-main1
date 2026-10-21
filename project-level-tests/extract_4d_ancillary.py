#!/usr/bin/env python3
"""Mine the 4D farm ancillary export for what the OpenET workbook asks for.

    python project-level-tests/extract_4d_ancillary.py

Walks every crop / year / irrigation / field combination and pulls out
operation dates and implements (from the per-operation ReadMe files and the
operations log), yield (from the cleaned harvest point data) and whatever the
as-applied logs record about tillage.

Prints a per-field-year summary and writes 4d-farm/ancillary_summary.csv.
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd  # noqa: E402

PROJ = Path(__file__).resolve().parent / "4d-farm"
ANC = PROJ / "ancillary data"

FIELD_MAP = {"front": "front-field", "west": "west-field",
             "north_pivot": "north-pivot", "south_pivot": "south-pivot"}


def read_readme(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    g = lambda pat: (re.search(pat, t, re.I | re.M).group(1).strip()
                     if re.search(pat, t, re.I | re.M) else "")
    prod = ""
    m = re.search(r"Product\(s\) Used:\s*\n(.+?)(\n\n|\n#|\Z)", t, re.S | re.I)
    if m:
        prod = " / ".join(x.strip() for x in m.group(1).strip().splitlines()
                          if x.strip())
    return {
        "date": g(r"Date Performed:\s*(.+)$"),
        "implement": g(r"Implement:\s*(.+)$"),
        "tractor": g(r"Tractor:\s*(.+)$"),
        "fuel_gal": g(r"Fuel Used:\s*([\d.]+)"),
        "products": prod,
    }


rows = []
combos = sorted({p for p in ANC.rglob("*") if p.is_dir()
                 and p.parent.name in FIELD_MAP} | {
                p.parent for p in ANC.rglob("*")
                if p.parent.name in FIELD_MAP})
seen = set()
for d in sorted({p for p in ANC.rglob("*") if p.is_dir()
                 and p.name in FIELD_MAP}):
    parts = d.parts
    field = FIELD_MAP[d.name]
    irr = parts[-2]                      # irrigated | dryland
    year = int(parts[-3])
    crop = parts[-4]
    key = (field, year)
    if key in seen:
        print("  NOTE: %s %d appears more than once" % key)
    seen.add(key)

    ops = []
    for rm in sorted(d.rglob("*_ReadMe.txt")):
        info = read_readme(rm)
        info["name"] = rm.name.replace("_ReadMe.txt", "")
        if info["date"]:
            ops.append(info)

    # The 2023 south pivot has a tabular log instead of per-file ReadMes.
    log = list(d.rglob("operations_log.txt"))
    log_rows = []
    if log:
        for line in log[0].read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            f = [x.strip() for x in line.split("\t")]
            if len(f) > 2 and re.match(r"\d+/\d+/\d{4}", f[0]):
                log_rows.append({"date": f[0], "name": f[1],
                                 "products": f[2] if len(f) > 2 else "",
                                 "implement": "", "tractor": "", "fuel_gal": ""})
    ops += log_rows

    # Yield from the cleaned harvest points.
    yld = yld_units = yld_n = ""
    for h in sorted(d.rglob("Cleaned_Yield_Data.csv")):
        try:
            y = pd.read_csv(h, low_memory=False)
        except Exception:
            continue
        col = next((c for c in y.columns if "Yield (Dry)" in c), None)
        if col is None:
            col = next((c for c in y.columns if c.startswith("Yield")), None)
        if col:
            yld = round(float(y[col].mean()), 1)
            yld_n = len(y)
            m = re.search(r"\((.*?)\)\s*$", col)
            yld_units = m.group(1) if m else ""
            break

    # Tillage type as the planter logged it, if present.
    till_logged = ""
    for a in sorted(d.rglob("*.csv")):
        if "as-applied" not in str(a):
            continue
        try:
            head = pd.read_csv(a, nrows=400, low_memory=False)
        except Exception:
            continue
        if "Tillage Type" in head.columns:
            v = head["Tillage Type"].dropna().astype(str)
            if len(v):
                till_logged = v.mode().iloc[0]
                break

    ops_sorted = sorted(ops, key=lambda o: pd.to_datetime(o["date"],
                                                          errors="coerce")
                        or pd.Timestamp("2100-01-01"))
    rows.append({
        "field": field, "year": year, "crop": crop, "water": irr,
        "yield": yld, "yield_units": yld_units, "yield_points": yld_n,
        "tillage_type_logged": till_logged,
        "n_operations": len(ops_sorted),
        "operations": " | ".join("%s %s" % (o["date"], o["name"])
                                 for o in ops_sorted),
        "implements": " | ".join(sorted({o["implement"] for o in ops_sorted
                                         if o["implement"]})),
        "products": " | ".join(sorted({o["products"] for o in ops_sorted
                                       if o["products"]}))[:600],
    })

df = pd.DataFrame(rows).sort_values(["field", "year"])
for _, r in df.iterrows():
    print("=" * 76)
    print("%s  %d  %s  (%s)" % (r.field, r.year, r.crop, r.water))
    print("  yield          : %s %s  (%s points)" % (r["yield"], r.yield_units,
                                                     r.yield_points))
    print("  tillage logged : %s" % (r.tillage_type_logged or "—"))
    print("  operations     : %d" % r.n_operations)
    for o in str(r.operations).split(" | "):
        if o.strip():
            print("      %s" % o)
    if r.implements:
        print("  implements     : %s" % r.implements)
    if r.products:
        print("  products       : %s" % r.products[:300])

df.to_csv(PROJ / "ancillary_summary.csv", index=False)
print("\nwrote ancillary_summary.csv  (%d field-years)" % len(df))
