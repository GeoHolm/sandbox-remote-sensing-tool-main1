#!/usr/bin/env python3
"""Spot test: compare a field only with neighbours growing the same sequence.

    python project-level-tests/match_rotation.py [dir ...]

The cohort benchmark currently compares a field with every qualifying
neighbour. The obvious refinement is to compare like with like -- corn
after soybeans against other corn after soybeans -- so that the ranking
cannot be an artefact of what was planted.

The obvious cost is sample size. This measures both, at three levels of
strictness:

  same crop        this year's crop matches
  same pair        this year AND last year match
  same triple      three consecutive years match

and asks three questions:

  1. How many neighbours actually survive the match?
  2. Does the focus field's percentile move when they do?
  3. Does crop sequence explain enough of the spread to be worth the cost?

Question 3 is the one that decides it. If fields growing the same sequence
are no more alike than fields growing different ones, matching buys nothing
and costs most of the cohort.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT = ["champaign-il", "sumner-ks", "mitchell-ga"]
SCORES = ["preplant", "residue", "worst"]
LABEL = {"preplant": "pre-plant armor", "residue": "annual residue",
         "worst": "worst 10%"}
MIN_PEERS = 10          # below this a percentile is not worth reporting

pd.set_option("display.width", 220)


def load(d):
    meta = json.loads((HERE / d / "cohort_meta.json").read_text())
    ann = pd.read_csv(HERE / d / "annual_armor_options.csv")
    hist = pd.read_csv(HERE / d / "history.csv")
    crop = hist.set_index(["fid", "year"]).crop
    rows = []
    for _, r in ann.iterrows():
        c0 = crop.get((r.fid, r.year))
        c1 = crop.get((r.fid, r.year - 1))
        c2 = crop.get((r.fid, r.year - 2))
        rows.append({
            "fid": r.fid, "year": int(r.year),
            "crop": c0,
            "pair": None if (pd.isna(c0) or pd.isna(c1)) else "%s<-%s" % (c0, c1),
            "triple": None if (pd.isna(c0) or pd.isna(c1) or pd.isna(c2))
            else "%s<-%s<-%s" % (c0, c1, c2),
            **{s: r[s] for s in SCORES},
        })
    t = pd.DataFrame(rows)
    t["county"] = meta.get("county", d).split(" County")[0]
    t["dir"] = d
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", default=DEFAULT)
    ap.add_argument("--bare", action="store_true",
                    help="drop chart titles; the slide supplies them")
    a = ap.parse_args()
    A = pd.concat([load(d) for d in (a.dirs or DEFAULT)], ignore_index=True)
    A = A[A.crop.notna()].copy()          # 2026 has no CDL

    LEVELS = [("all neighbours", None), ("same crop", "crop"),
              ("same pair", "pair"), ("same triple", "triple")]

    # ---- 1. how many peers survive ---------------------------------------
    print("=" * 100)
    print("1. HOW MANY NEIGHBOURS SURVIVE THE MATCH")
    print("=" * 100)
    print("   median peers available to a field-year, and the share of "
          "field-years left with %d or more" % MIN_PEERS)
    print()
    rows = []
    for cty, sub in A.groupby("county"):
        rec = {"county": cty, "field_years": len(sub)}
        for name, key in LEVELS:
            counts = []
            for _, r in sub.iterrows():
                if key is None:
                    peers = sub[(sub.year == r.year) & (sub.fid != r.fid)]
                elif pd.isna(r[key]):
                    continue
                else:
                    peers = sub[(sub.year == r.year) & (sub.fid != r.fid)
                                & (sub[key] == r[key])]
                counts.append(len(peers))
            counts = np.array(counts) if counts else np.array([0])
            rec["%s_med" % name] = int(np.median(counts))
            rec["%s_ok%%" % name] = round(100 * (counts >= MIN_PEERS).mean())
        rows.append(rec)
    S1 = pd.DataFrame(rows)
    print(S1.to_string(index=False))

    # ---- 2. does the focus field move ------------------------------------
    print()
    print("=" * 100)
    print("2. DOES THE FOCUS FIELD'S PERCENTILE MOVE?")
    print("=" * 100)
    rows = []
    for d, sub in A.groupby("dir"):
        cty = sub.county.iloc[0]
        for _, r in sub[sub.fid == "focus"].sort_values("year").iterrows():
            rec = {"county": cty, "year": r.year, "crop": r.crop}
            for name, key in LEVELS:
                if key is None:
                    peers = sub[(sub.year == r.year) & (sub.fid != "focus")]
                elif pd.isna(r[key]):
                    peers = sub.iloc[0:0]
                else:
                    peers = sub[(sub.year == r.year) & (sub.fid != "focus")
                                & (sub[key] == r[key])]
                v = r["residue"]
                rec["%s_n" % name] = len(peers)
                rec["%s_pct" % name] = (
                    round(100 * (peers["residue"] <= v).mean())
                    if len(peers) >= MIN_PEERS and pd.notna(v) else np.nan)
            rows.append(rec)
    S2 = pd.DataFrame(rows)
    print("   percentile on ANNUAL RESIDUE; blank where fewer than %d peers "
          "survive" % MIN_PEERS)
    print()
    print(S2.to_string(index=False))

    # ---- 3. does sequence explain the spread? ----------------------------
    print()
    print("=" * 100)
    print("3. DOES CROP SEQUENCE EXPLAIN THE SPREAD?")
    print("=" * 100)
    print("   share of within-county, within-year variance explained by the "
          "grouping (eta^2).")
    print("   0% means fields growing the same thing are no more alike than "
          "fields that are not.")
    print()
    rows = []
    for score in SCORES:
        rec = {"score": LABEL[score]}
        for name, key in LEVELS[1:]:
            num = den = 0.0
            for (cty, yr), g in A.groupby(["county", "year"]):
                g = g.dropna(subset=[score, key])
                if len(g) < 12 or g[key].nunique() < 2:
                    continue
                grand = g[score].mean()
                between = sum(len(h) * (h[score].mean() - grand) ** 2
                              for _, h in g.groupby(key))
                total = ((g[score] - grand) ** 2).sum()
                num += between
                den += total
            rec["%s_eta2%%" % name] = round(100 * num / den, 1) if den else np.nan
        rows.append(rec)
    S3 = pd.DataFrame(rows)
    print(S3.to_string(index=False))

    print()
    print("   for scale, the same calculation for COUNTY, pooling years:")
    for score in SCORES:
        g = A.dropna(subset=[score])
        grand = g[score].mean()
        between = sum(len(h) * (h[score].mean() - grand) ** 2
                      for _, h in g.groupby("county"))
        total = ((g[score] - grand) ** 2).sum()
        print("     %-18s county explains %4.1f%%"
              % (LABEL[score], 100 * between / total))

    out = HERE / "_across"
    S1.to_csv(out / "match_peers.csv", index=False)
    S2.to_csv(out / "match_focus.csv", index=False)
    S3.to_csv(out / "match_variance.csv", index=False)
    print()
    print("wrote match_peers.csv, match_focus.csv, match_variance.csv")

    figure(A, S1, S3, bare="--bare" in sys.argv)


def figure(A, S1, S3, bare=False):
    """What matching buys, beside what it costs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    INK, INK2, MUTED = "#212121", "#58595B", "#9a9b9d"
    ORANGE = "#F46C09"
    RAMP = ["#10427C", "#2f74c4", "#85b6ef"]
    GRID = "#e6e6e6"
    plt.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "white",
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    })
    out = HERE / "_across" / ("deck" if bare else "")
    out.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.5))

    # left: what it buys
    ax = axes[0]
    lv = ["same crop", "same pair", "same triple"]
    x = np.arange(len(lv))
    w = 0.38
    for k, (s, lab, col) in enumerate([("pre-plant armor", "pre-plant armor",
                                        RAMP[2]),
                                       ("annual residue", "annual residue",
                                        ORANGE)]):
        v = [S3.loc[S3.score == s, "%s_eta2%%" % l].iloc[0] for l in lv]
        ax.bar(x + (k - .5) * w, v, w, color=col, label=lab, linewidth=0)
        for i, u in enumerate(v):
            ax.text(i + (k - .5) * w, u + 1.5, "%.0f" % u, ha="center",
                    fontsize=10, color=INK2)
    ax.axhline(41.4, color=RAMP[0], lw=2, ls=(0, (5, 4)), zorder=5)
    ax.text(2.42, 43.5, "county explains 41%", ha="right", fontsize=10,
            color=RAMP[0], fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(lv, fontsize=11)
    ax.set_ylim(0, 100); ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    ax.set_ylabel("% of within-county spread explained", fontsize=10)
    if not bare:
        ax.set_title("What matching buys", color=INK, fontsize=12.5,
                     fontweight="bold", loc="left", pad=10)

    # right: what it costs
    ax = axes[1]
    cols = {"Champaign": RAMP[2], "Sumner": RAMP[1], "Mitchell": RAMP[0]}
    w = 0.26
    for k, cty in enumerate(["Champaign", "Sumner", "Mitchell"]):
        r = S1[S1.county == cty].iloc[0]
        v = [r["%s_med" % l] for l in lv]
        ax.bar(x + (k - 1) * w, v, w, color=cols[cty], label=cty, linewidth=0)
        for i, u in enumerate(v):
            ax.text(i + (k - 1) * w, u + 0.8, "%d" % u, ha="center",
                    fontsize=9.5, color=INK2)
    ax.axhline(MIN_PEERS, color=ORANGE, lw=2, ls=(0, (5, 4)), zorder=5)
    ax.text(2.44, MIN_PEERS + 1.2, "%d peers, the floor" % MIN_PEERS,
            ha="right", fontsize=10, color=ORANGE, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(lv, fontsize=11)
    ax.set_ylim(0, 32); ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=10, ncol=3, loc="upper right")
    ax.set_ylabel("median neighbours left", fontsize=10)
    if not bare:
        ax.set_title("What matching costs", color=INK, fontsize=12.5,
                     fontweight="bold", loc="left", pad=10)

    if not bare:
        fig.suptitle("Compare like with like — where there is enough of it",
                     x=.045, ha="left", y=1.045, fontsize=13.5,
                     fontweight="bold", color=INK)
        fig.text(.045, 1.0, "Crop sequence explains more of the spread inside "
                 "a county than county explains between them — but outside "
                 "the Corn Belt the matched cohort collapses.",
                 fontsize=10, color=INK2, ha="left", va="top")
    fig.tight_layout()
    fig.savefig(out / "F_rotation_match.png", dpi=170, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print("  wrote F_rotation_match.png")


if __name__ == "__main__":
    main()
