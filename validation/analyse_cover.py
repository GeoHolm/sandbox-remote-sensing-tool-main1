#!/usr/bin/env python
"""Score the off-season cover-crop verdict against the grower's answer.

    python validation/analyse_cover.py

Two things are scored separately, because they fail for different reasons:
the **shipped verdict** (thresholds as they stand) and the **raw signal**
(how well max NDVI could separate the classes at any threshold). A weak
verdict over a strong signal is a tuning problem; weak on both is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
POS = {"likely cover crop", "green cover -- cover crop or small grain"}
UNKNOWN_PREFIX = ("insufficient data", "perennial", "off-season flooded", "ERROR")


def auc(score: np.ndarray, y: np.ndarray) -> float:
    ok = np.isfinite(score)
    score, y = score[ok], y[ok]
    if y.sum() < 5 or (~y).sum() < 5:
        return float("nan")
    r = pd.Series(score).rank().to_numpy()
    return float((r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum()))


def cv_threshold(d: pd.DataFrame, col: str, seed: int = 0) -> tuple[float, float]:
    """5-fold accuracy, threshold fitted on train folds, split by field."""
    rng = np.random.default_rng(seed)
    ids = d["field_id"].unique().copy()
    rng.shuffle(ids)
    accs = []
    for fold in np.array_split(ids, 5):
        te, tr = d[d["field_id"].isin(fold)], d[~d["field_id"].isin(fold)]
        if len(te) < 5 or len(tr) < 20:
            continue
        ytr, xtr = tr["truth"].to_numpy(), tr[col].to_numpy()
        best = max((((xtr >= c) == ytr).mean(), c) for c in np.unique(xtr))
        accs.append((((te[col].to_numpy() >= best[1]) == te["truth"].to_numpy()).mean()))
    return float(np.mean(accs)), float(np.std(accs))


def main() -> int:
    t = pd.read_csv(HERE / "truth.csv")
    c = pd.read_csv(HERE / "cover.csv")
    d = t.merge(c, on="key")
    d = d[d["cover"].isin(["Yes", "No"])].copy()
    d["truth"] = d["cover"] == "Yes"

    n_all = len(d)
    unknown = d["verdict"].str.startswith(UNKNOWN_PREFIX)
    print(f"scored {n_all} field-winters ({d['field_id'].nunique()} fields); "
          f"{int(unknown.sum())} returned no usable verdict\n")

    print("=== verdict vs grower ===")
    print(pd.crosstab(d["verdict"], d["cover"], margins=True).to_string())

    j = d[~unknown].copy()
    j["pred"] = j["verdict"].isin(POS)
    tp = int((j["pred"] & j["truth"]).sum())
    fp = int((j["pred"] & ~j["truth"]).sum())
    fn = int((~j["pred"] & j["truth"]).sum())
    tn = int((~j["pred"] & ~j["truth"]).sum())
    print(f"\n=== shipped thresholds, treating 'possible' as negative "
          f"(n={len(j)}) ===")
    print(f"  accuracy     {100 * (tp + tn) / len(j):.1f}%")
    print(f"  sensitivity  {100 * tp / max(tp + fn, 1):.1f}%  "
          f"(found {tp} of {tp + fn} real cover crops)")
    print(f"  specificity  {100 * tn / max(tn + fp, 1):.1f}%  "
          f"({fp} false alarms on {tn + fp} no-cover fields)")

    j2 = j.copy()
    j2["pred"] = j2["verdict"].isin(POS | {"possible cover crop"})
    tp2 = int((j2["pred"] & j2["truth"]).sum())
    fp2 = int((j2["pred"] & ~j2["truth"]).sum())
    print(f"  counting 'possible' as positive: accuracy "
          f"{100 * ((j2['pred'] == j2['truth']).mean()):.1f}%, "
          f"sensitivity {100 * tp2 / max(int(j2['truth'].sum()), 1):.1f}%, "
          f"{fp2} false alarms")

    print("\n=== raw signal (any threshold) ===")
    for col, lab in [("max_ndvi", "max NDVI"), ("mean_ndvi", "mean NDVI"),
                     ("green_days", "green days")]:
        if col not in j:
            continue
        a = auc(j[col].to_numpy(float), j["truth"].to_numpy())
        acc, sd = cv_threshold(j.dropna(subset=[col]), col)
        print(f"  {lab:12s} AUC {a:.3f}   CV accuracy {100 * acc:.1f}% "
              f"+/- {100 * sd:.1f}")
    base = max(j["truth"].mean(), 1 - j["truth"].mean())
    print(f"  {'baseline':12s}            {100 * base:.1f}% (majority class)")

    print("\n=== by crop and year ===")
    for k in ("crop", "year"):
        g = j.groupby(k).apply(
            lambda x: pd.Series({
                "n": len(x),
                "AUC": round(auc(x["max_ndvi"].to_numpy(float),
                                 x["truth"].to_numpy()), 3),
                "verdict_acc": round(100 * (x["verdict"].isin(POS)
                                            == x["truth"]).mean(), 1)}),
            include_groups=False)
        print(g.to_string(), "\n")

    print("=== does a later window start help? (late cotton harvest) ===")
    raw = HERE / "cover_series.csv"
    if raw.exists():
        s = pd.read_csv(raw, parse_dates=["date"])
        s = s.merge(d[["key", "field_id", "truth", "crop"]], on="key")
        for start_md in ["10-15", "11-01", "11-15", "12-01"]:
            mm, dd = start_md.split("-")
            lo = pd.to_datetime(dict(year=s["date"].dt.year.where(
                s["date"].dt.month >= 10, s["date"].dt.year - 1),
                month=int(mm), day=int(dd)))
            w = s[s["date"] >= lo]
            agg = (w.groupby(["key", "field_id", "truth", "crop"])["ndvi"]
                     .max().reset_index())
            a_all = auc(agg["ndvi"].to_numpy(), agg["truth"].to_numpy())
            a_cot = auc(agg[agg["crop"] == "Cotton"]["ndvi"].to_numpy(),
                        agg[agg["crop"] == "Cotton"]["truth"].to_numpy())
            print(f"  start {start_md}: max-NDVI AUC all {a_all:.3f}, "
                  f"cotton {a_cot:.3f}  (n={len(agg)})")
    else:
        print("  cover_series.csv not found")

    out = HERE / "cover_scored.csv"
    d.to_csv(out, index=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
