#!/usr/bin/env python3
"""Detect alfalfa cuttings in the NDVI series of a field report pack.

    python project-level-tests/detect_alfalfa_cuttings.py \n        project-level-tests/alfalfa-nm/pack project-level-tests/alfalfa-nm

A cutting is a STEP DOWN in NDVI: a standing crop on one clear date, stubble
and windrow on the next, with the low holding. Four tests, each put there by
a case in this field's own series that an earlier rule got wrong:

  standing    the crop must be there to be cut (NDVI >= PEAK_MIN before the
              fall). Rules out the winter baseline and dormant regrowth.
  step        the fall is measured from the last standing observation to the
              first low one, and both must be real observations within
              FALL_DAYS of each other. Measuring instead from the seasonal
              peak is wrong twice over: a mature stand plateaus near its peak
              for weeks before it is cut, which made the 7-day first cutting
              of 2023 look like a 27-day senescence; and after a slow decline
              it reports a "cut" whose actual step is 0.004 NDVI, as it did
              on 19 Dec 2025.
  persistent  the low holds for at least two clear observations. On 12 Aug
              2023 this field reads 0.485 between a 0.904 and a 0.932 five
              days later. Alfalfa cannot regrow a canopy in five days, so
              that is cloud shadow, not a cutting.
  spaced      at least REFRACTORY days since the last cut, because a stand
              needs roughly a month to regrow.

Deliberately NOT a test: whether the stand regrew afterwards. It separates a
cutting from dormancy cleanly in midsummer and fails exactly where it matters,
on the last cutting of the year -- which by definition does not regrow. It
threw away the fall of 8 Oct 2023, a full canopy at 0.93 dropping to 0.43 in
three days, which is mechanical removal if anything is.

Autumn is still the ambiguous season: a hard freeze also takes a canopy down.
Cuttings after LATE_FROM are flagged `late_season` in the output rather than
silently counted or silently dropped, because this field sits at about 1,600 m
in northwestern New Mexico and the two causes are not separable from NDVI
alone.

Nothing here has been validated against a grower's cutting record anywhere.
These are estimates from the shape of a curve.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

# --- detection constants, all provisional --------------------------------
DROP = 0.30        # NDVI step down, standing -> low, that counts as a cut
PEAK_MIN = 0.60    # NDVI the standing crop must reach to be worth cutting
FALL_DAYS = 12     # the step must complete within this many days
RECOVER = 0.25     # "still down" means below standing - RECOVER
MIN_PERSIST = 2    # consecutive observations that must stay down
REFRACTORY = 18    # days before another cut can be counted (regrowth time)
SNAPBACK = 0.10    # a "cut" whose canopy returns to within this of the
SNAPBACK_DAYS = 12 # standing level within this many days was never cut
LATE_FROM = 274    # day of year (1 Oct) after which a fall is flagged as
#                    possibly a freeze rather than a cutting


def detect(ser):
    """ser: one year of date/mean, sorted. Returns (events, audit)."""
    d = ser.reset_index(drop=True)
    nd, dt = d["mean"].tolist(), d["date"].tolist()
    cl = d["valid_frac"].tolist()
    n = len(d)
    events, audit = [], []
    last_cut = None
    i = 0
    while i < n - 1:
        standing = nd[i]
        # first later observation at least DROP below this one, inside FALL_DAYS
        j = None
        for k in range(i + 1, n):
            if (dt[k] - dt[i]).days > FALL_DAYS:
                break
            if standing - nd[k] >= DROP:
                j = k
                break
        if j is None:
            i += 1
            continue

        persist = 0
        for k in range(j, n):
            if nd[k] < standing - RECOVER:
                persist += 1
            else:
                break
        need = min(MIN_PERSIST, n - j)
        since = None if last_cut is None else (dt[j] - last_cut).days

        # How fast does the canopy come back? This field's own cuttings take
        # 13 days at the very fastest to climb back to 0.80, so a stand that
        # is whole again inside 12 days was never cut. That is what November
        # 2025 looks like: 0.91 -> 0.53 -> 0.82 in eight days, inside a month
        # of oscillation between 0.44 and 0.82 at low sun angle. The test is
        # deliberately one-sided -- a cut need NOT regrow, because the last
        # cutting of the year never does -- so it rejects noise without
        # throwing away the autumn cuttings of 2022 and 2023.
        snap = None
        for k in range(j + 1, n):
            if (dt[k] - dt[j]).days > SNAPBACK_DAYS:
                break
            if nd[k] >= standing - SNAPBACK:
                snap = (dt[k] - dt[j]).days, nd[k]
                break

        why = None
        if standing < PEAK_MIN:
            why = "standing crop only %.2f (<%.2f), nothing to cut" % (standing, PEAK_MIN)
        elif persist < need:
            why = "down for %d observation(s), needs %d: cloud shadow" % (persist, need)
        elif since is not None and since < REFRACTORY:
            why = "only %d days since the last cut (<%d)" % (since, REFRACTORY)
        elif snap is not None:
            why = ("back to %.2f after only %d days (<%d): no stand regrows "
                   "that fast, so this is noise" % (snap[1], snap[0], SNAPBACK_DAYS))

        # Diagnostics, recorded whether or not the event is accepted, so the
        # judgment stays visible instead of hiding inside a constant.
        #
        # Cloud is measured as valid_frac, the share of FIELD pixels that
        # survived the mask, not the scene cloud percentage. Scene cloud is
        # a property of a 110 km tile and says almost nothing about a 25 ha
        # field inside it: five of these twenty lows sit under scenes 14-34%
        # clouded, and every one of the twenty has a fully clear field.
        #
        # What remains flagged is the low of 1 Nov 2025, which clears every
        # test above on a clear field, yet reads 0.82 again eight days later.
        # Nothing in four years of this stand regrows that fast. Not enough
        # to reject, not enough to present as fact, so: reported, flagged.
        # The low observation itself, not the run: the drop magnitude is
        # measured from this one pixel-set, and it is the number the whole
        # detection rests on. A partly masked CONFIRMING observation weakens
        # the persistence test rather than the drop, which is a second-order
        # worry and not worth a flag on a slide.
        low_valid = cl[j]
        rec_days, rec_to = "", ""
        for k in range(j + 1, n):
            if nd[k] >= standing - SNAPBACK:
                rec_days, rec_to = (dt[k] - dt[j]).days, round(nd[k], 3)
                break

        late = dt[j].dayofyear >= LATE_FROM
        shaky = (low_valid < 0.95) or (rec_days != "" and rec_days <= 14)
        audit.append({
            "standing": round(standing, 3), "standing_on": dt[i],
            "low": round(nd[j], 3), "low_on": dt[j],
            "fall_days": (dt[j] - dt[i]).days, "persist": persist,
            "accepted": why is None, "late": late,
            "reason": why or "accepted",
            "flag": "; ".join(
                ([ "after 1 Oct, a hard freeze would look the same"] if late else [])
                + (["only %.0f%% of field pixels clear" % (low_valid * 100)]
                   if low_valid < 0.95 else [])
                + (["canopy back to %.2f in %d days" % (rec_to, rec_days)]
                   if rec_days != "" and rec_days <= 14 else [])),
        })
        if why is None:
            events.append({
                "last_standing": dt[i], "ndvi_standing": round(standing, 3),
                "first_cut_obs": dt[j], "ndvi_after": round(nd[j], 3),
                "drop": round(standing - nd[j], 3),
                "cut_window_days": (dt[j] - dt[i]).days,
                "late_season": late,
                "low_min_valid_frac": round(low_valid, 3),
                "regained_in_days": rec_days, "regained_to": rec_to,
                "uncertain": bool(late or shaky),
            })
            last_cut = dt[j]
            i = j + 1
        else:
            i += 1
    return events, audit


D = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else D

s = pd.read_csv(D / "series" / "ndvi-by-date.csv", parse_dates=["date"])
s = s.sort_values("date").reset_index(drop=True)
cdl = pd.read_csv(D / "tables" / "crop-rotation.csv")
crop_of = dict(zip(cdl.year, cdl.crop))

rows, summ = [], []
for yr, y in s.groupby(s.date.dt.year):
    crop = crop_of.get(yr, "")
    ev, audit = detect(y)
    print("=" * 78)
    print("%d  %s   (%d clear observations)" % (yr, crop or "no CDL yet", len(y)))
    print("=" * 78)
    for a in audit:
        print("  %s %.3f on %s -> %.3f on %s  in %2dd  %s%s"
              % ("CUT " if a["accepted"] else " -- ", a["standing"],
                 a["standing_on"].strftime("%d %b"), a["low"],
                 a["low_on"].strftime("%d %b"), a["fall_days"], a["reason"],
                 "  [FLAGGED: %s]" % a["flag"]
                 if a["accepted"] and a["flag"] else ""))
    prev = None
    for k, e in enumerate(ev, 1):
        e.update(year=yr, crop=crop, cutting=k)
        e["days_since_prev"] = "" if prev is None else (e["first_cut_obs"] - prev).days
        prev = e["first_cut_obs"]
        rows.append(e)
    nf = sum(e["uncertain"] for e in ev)
    print("  => %d cutting(s)%s" % (len(ev), "  (%d flagged)" % nf if nf else ""))
    gaps = [e["days_since_prev"] for e in ev[1:]]
    summ.append({
        "year": yr, "crop": crop, "n_obs": len(y), "cuttings": len(ev),
        "cuttings_firm": sum(not e["uncertain"] for e in ev),
        "cuttings_flagged": sum(e["uncertain"] for e in ev),
        "first_cut": ev[0]["first_cut_obs"].date() if ev else "",
        "last_cut": ev[-1]["first_cut_obs"].date() if ev else "",
        "mean_regrowth_days": round(pd.Series(gaps).mean(), 1) if gaps else "",
        "max_ndvi": round(y["mean"].max(), 3),
        "longest_gap_days": int(y.date.diff().dt.days.max()),
    })

cut = pd.DataFrame(rows)
sm = pd.DataFrame(summ)
print("\n" + "=" * 78)
print(sm.to_string(index=False))
cut.to_csv(OUT / "cuttings.csv", index=False)
sm.to_csv(OUT / "cutting_summary.csv", index=False)
print("\nwrote cuttings.csv (%d events), cutting_summary.csv" % len(cut))
