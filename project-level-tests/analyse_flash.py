#!/usr/bin/env python3
"""Compare the remote sensing cover crop verdicts against the FLASH payloads.

    python project-level-tests/analyse_flash.py

Runs on whatever rs_covercrop.csv holds, so it is useful mid-run.

WHAT CAN AND CANNOT BE MEASURED
Only winter 2025-26 carries a grower label, and every one of the 98 fields is
labeled positive -- `planting_cover` appears exactly 98 times in the archive,
all in the 2026 harvest-year intervals. Earlier years are rotation skeletons
with no cover crop records at all, so their silence is not a negative.

That gives sensitivity and nothing else. Specificity -- the half Georgia
measured at 7.1% -- needs negatives, and there are none. The earlier winters
are therefore reported as what the detector *claims*, against published
Illinois adoption, which is a weaker but real check: a detector reporting
near-universal cover cropping in 2022 is reporting something that did not
happen.
"""
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 200)

PROJ = Path(__file__).resolve().parent / "project-FLASH"

rs = pd.read_csv(PROJ / "rs_covercrop.csv")
truth = pd.read_csv(PROJ / "cover_truth.csv")
fields = pd.read_csv(PROJ / "fields.csv")
runs = pd.read_csv(PROJ / "rs_fields.csv")

ok = runs[runs.status == "ok"]
print("=" * 72)
print("FLASH project-level test -- %d of %d boundaries analysed%s"
      % (len(ok), len(fields), "  (RUN STILL IN PROGRESS)"
         if len(ok) < len(fields) else ""))
print("=" * 72)
if (runs.status != "ok").any():
    print("\nFAILED fields:")
    print(runs[runs.status != "ok"][["key", "error"]].to_string(index=False))

print("\n--- pipeline behaviour ---")
print("  mean minutes per field : %.2f" % ok.minutes.mean())
print("  observations per field : median %.0f  (min %d, max %d)"
      % (ok.obs.median(), ok.obs.min(), ok.obs.max()))
print("  winters resolved       : %s" % ok.winters.value_counts().to_dict())
print("  boundary verdicts      : %s" % ok.boundary_verdict.value_counts().to_dict())

# Boundary quality gates everything downstream -- say so before any accuracy.
split = ok[ok.boundary_verdict != "single unit"]
if len(split):
    print("  NOTE: %d of %d boundaries are not a single management unit; their "
          "winter curves average over more than one field."
          % (len(split), len(ok)))

print("\n--- what the detector said, by winter ---")
tab = (rs.groupby(["winter", "verdict"]).size().unstack(fill_value=0))
print(tab.to_string())

# Positive class, two readings. Georgia's 57.5% used "likely" alone.
STRICT = ["likely cover crop"]
LOOSE = ["likely cover crop", "possible cover crop",
         "green cover -- cover crop or small grain"]
rs["pos_strict"] = rs.verdict.isin(STRICT)
rs["pos_loose"] = rs.verdict.isin(LOOSE)

print("\n--- winter 2025-26: the only labelled winter, all 98 positive ---")
lab = rs[rs.winter == "2025-26"].merge(
    truth[truth.fall_year == 2025][["key", "reported"]], on="key", how="inner")
if len(lab):
    print("  fields with both a label and a verdict : %d" % len(lab))
    print("  all labels positive                    : %s"
          % bool((lab.reported == "yes").all()))
    print("  SENSITIVITY, strict (likely only)      : %d / %d = %.1f%%"
          % (lab.pos_strict.sum(), len(lab), 100 * lab.pos_strict.mean()))
    print("  SENSITIVITY, loose  (likely+possible+green) : %d / %d = %.1f%%"
          % (lab.pos_loose.sum(), len(lab), 100 * lab.pos_loose.mean()))
    print("\n  misses (grower says cover crop, detector does not):")
    miss = lab[~lab.pos_loose]
    if len(miss):
        print(miss[["key", "n_obs", "max_ndvi", "green_days", "verdict"]]
              .to_string(index=False))
    else:
        print("    none")
else:
    print("  no labelled winters analysed yet")

print("\n--- earlier winters: no labels, so this is a claim, not a score ---")
for w in sorted(x for x in rs.winter.unique() if x != "2025-26"):
    g = rs[rs.winter == w]
    print("  %s  n=%3d   strict %5.1f%%   loose %5.1f%%"
          % (w, len(g), 100 * g.pos_strict.mean(), 100 * g.pos_loose.mean()))
print("\n  Illinois cover crop adoption is a small single-digit to low double-digit")
print("  share of cropland in this period. A detector claiming most of these")
print("  fields were cover cropped in 2022-23 is describing the false positive")
print("  rate, not the practice.")

print("\n--- does the detector's 'winter cash crop' call track actual wheat? ---")
wc = rs[rs.verdict == "winter cash crop, not a cover crop"]
if len(wc):
    fc = fields.set_index("key")
    rows = []
    for _, o in wc.iterrows():
        crops = ok.set_index("key").loc[o.key, "crops"] if o.key in ok.key.values else ""
        rows.append({"key": o.key, "winter": o.winter,
                     "rotation_crops": crops, "max_ndvi": o.max_ndvi})
    d = pd.DataFrame(rows)
    d["has_wheat"] = d.rotation_crops.fillna("").str.contains("Wheat", case=False)
    print("  %d 'winter cash crop' calls; %d on fields whose CDL rotation "
          "includes wheat" % (len(d), int(d.has_wheat.sum())))
    print(d.head(12).to_string(index=False))
else:
    print("  none")

out = PROJ / "flash_comparison.csv"
rs.merge(truth[["key", "fall_year", "reported", "cover_crop_id", "planted",
                "terminated"]], on=["key", "fall_year"], how="left") \
  .merge(fields[["key", "field_name", "location", "acres"]], on="key", how="left") \
  .to_csv(out, index=False)
print("\nwrote %s" % out.name)
